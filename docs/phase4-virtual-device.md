# Phase 4: The virtual Xbox controller

Goal: a virtual HID device that macOS treats as an **Xbox Series X|S
controller over Bluetooth LE (`045E:0B13`)**, fed by the Phase 3 bridge.
Phase 2 showed that Apple's allowlist matches this ID to its Xbox driver
and allows virtual devices for it (`GCIOMatchVirtual = true`). Phase 1
showed the Raikiri already produces this controller's exact report format.

**Read this whole page before changing any security setting.** Nothing in
this project changes settings for you; every change below is one you make
by hand, and each has an undo.

## 1. Two ways to create a virtual HID device

macOS offers exactly two ways to create a "real" HID device from software,
one that the rest of the system can't tell from hardware:

| | **Core HID `HIDVirtualDevice`** | **DriverKit driver (`IOUserHIDDevice`)** |
|---|---|---|
| What it is | A Swift API (macOS 15+). A normal program creates the device. | A driver extension (`.dext`) that runs in its own sandboxed process, installed by an app as a *system extension*. |
| Entitlement | `com.apple.developer.hid.virtual.device` | `com.apple.developer.driverkit` plus the HID family/transport entitlements (exact list confirmed in step B) |
| Can a paid developer account sign it for your own Mac? | **Not yet.** Apple DTS (March 2026): no development variant exists; it needs Apple's approval. Apple said it's looking into adding one. | **Yes.** Every DriverKit entitlement has a "development only" variant usable with a paid account, no approval. |
| Tools | Command Line Tools (what you have) | Full **Xcode** (for the DriverKit SDK), `arm64e` builds, an app to install it, and your approval in System Settings |
| Code size | ~100 lines (`bridge/Sources/raikiri-bridge/VirtualXbox.swift`) | A driver, a connection between driver and bridge, and an installer app |

The bridge, the Xbox identity and the descriptor are shared by both. Only
the "create the virtual device" piece differs.

## 2. Why these entitlements exist

A virtual HID device can type keystrokes and move the mouse. Malware
would love that. So Apple makes it a **restricted entitlement**: a program
may only use it if its code signature says so *and* an Apple-issued
provisioning profile backs that claim. The component that checks this at
launch is **AMFI** (Apple Mobile File Integrity).

## 3. Your plan: test with SIP and AMFI off, then get the account

It works, with two caveats:

1. **The test answers the important question.** Will macOS and GeForce
   NOW accept a virtual Xbox Series controller? The answer doesn't depend
   on how the program is signed. If it's yes, paying for the account is
   worth it.
2. **Caveat: AMFI off hides signing mistakes.** With AMFI off, nothing is
   checked, so step B (the properly signed version) can still hit
   entitlement or provisioning errors. Those are fixable, but they're
   separate work.
3. **Caveat: the test uses Core HID, the final version likely DriverKit.**
   Core HID is far quicker to test (no Xcode, no driver install). But a
   paid account can't sign Core HID today, so the final version will
   probably be DriverKit. Everything except the ~100-line virtual-device
   piece carries over. If Apple adds the development variant for Core HID,
   the test program becomes the final one, just properly signed.

```
Step A  (SIP + AMFI off, ~1 evening)
  Core HID proof of concept: does macOS show an Xbox controller? Does GFN accept it?
    |-- yes --> restore protections --> join the Developer Program --> Step B:
    |           DriverKit version, properly signed, with protections ON
    |-- no  --> before paying: try the DriverKit version with SIP/AMFI off
                (it creates the device differently, and Apple's virtual-device
                filtering may treat it differently)
```

## 4. What SIP and AMFI are, and what turning them off means

- **SIP (System Integrity Protection)** stops even administrators from
  modifying system files, attaching debuggers to system processes, loading
  unsigned kernel code, and changing protected NVRAM settings, including
  the boot arguments needed to turn AMFI off.
- **AMFI** enforces code signing and entitlements. With the boot argument
  `amfi_get_out_of_my_way=1`, it stops enforcing, and any program can claim
  any entitlement.

On Apple Silicon, turning SIP off also lowers the Mac's **startup security
policy** from Full Security. That's why it's done from the recovery system.

**While they're off:**

- Any program you run, including malware, can grant itself restricted
  entitlements (like creating virtual keyboards), and system files are no
  longer protected.
- Apple disables some features: **Apple Pay** stops working and
  **iPhone/iPad apps won't open**. Apps that check system integrity may
  refuse to run.
- Your data isn't at risk just because the protections are off. The risk is
  what happens *if* something malicious runs during that window.

**Precautions:**

- Keep the window short: turn them off, test, and turn them back on the same day.
- Don't install or run anything new or untrusted while they're off.
- You're on macOS 27 ("Version 27.0 (Build 26A428)"). If it's a beta,
  behavior may differ from what's described here.

## 5. Step A: turning protections off (Apple Silicon)

This uses Apple's own recovery tools. Have your admin password ready.

1. **Shut down** the Mac.
2. **Press and hold the power button** until "Loading startup options"
   appears. Choose **Options → Continue**, and sign in as an administrator
   if asked.
3. Menu bar **Utilities → Startup Security Utility**. Select your startup
   disk, click **Security Policy…**, choose **Reduced Security**, and click OK.
4. Menu bar **Utilities → Terminal**, then run:
   ```
   csrutil disable
   ```
   Confirm when asked. Then **restart** from the Apple menu.
5. Back in macOS, open Terminal:
   ```bash
   sudo nvram boot-args="amfi_get_out_of_my_way=1"
   ```
   Then **restart** again.
6. Check:
   ```bash
   csrutil status        # "System Integrity Protection status: disabled."
   nvram boot-args       # boot-args	amfi_get_out_of_my_way=1   (stored for next boot)
   sysctl kern.bootargs  # kern.bootargs: amfi_get_out_of_my_way=1  (active now: the one that matters)
   ```
   If `kern.bootargs` is empty, AMFI is still enforcing, and the test build
   is killed with `amfid ... "The file is adhoc signed but contains
   restricted entitlements"` in the system log. Set the boot argument again
   (step 5) and restart.

## 6. Step A: the test

```bash
cd ~/raikiri && git pull && cd bridge
./build-virtual.sh                                   # builds and signs with the entitlement
.build/release/raikiri-bridge --virtual --seize
```

Expected: `Virtual controller created: Xbox Wireless Controller 045E:0B13`,
then `Connected: RAIKIRI II PRO PC ...`. `--seize` hides the real Raikiri
from other apps while the bridge runs, so nothing sees two controllers. If
seize fails, run without it. Keep this window open, and in a **second**
window, check in this order:

1. **Apple's framework:** `cd ~/raikiri/recognition && swift gc_probe.swift 30`.
   Hoped for: `CONNECTED: Xbox Wireless Controller`, profile **Xbox**, and
   your button presses printed. This is the key result.
2. **System Settings → Game Controllers:** is there an Xbox Wireless Controller?
3. **Chrome** at a gamepad tester: does it now say *STANDARD GAMEPAD, Vendor 045e Product 0b13*?
4. **GeForce NOW** (normal launch, no script): start a game and play.

Paste the bridge's output and the probe's output. If `--virtual` fails with
"the system refused", paste that too. It says which part isn't accepted.

## 7. Restoring protections (do this when testing is done)

1. In macOS Terminal:
   ```bash
   sudo nvram -d boot-args
   ```
2. Shut down, then hold the power button → **Options** → **Utilities → Terminal**:
   ```
   csrutil enable
   ```
3. **Utilities → Startup Security Utility** → your disk → **Security
   Policy…** → **Full Security** → OK.
4. Restart and check:
   ```bash
   csrutil status        # "System Integrity Protection status: enabled."
   nvram boot-args       # error: "boot-args" not found (that's what you want)
   ```

After this, the ad-hoc-signed test build won't launch any more (macOS kills
it). That's expected, and shows AMFI is back on.

## Step A result: it works

With SIP off and `amfi_get_out_of_my_way=1` active (the first attempt
failed only because the boot argument hadn't been set; amfid logged "The
file is adhoc signed but contains restricted entitlements"), `raikiri-bridge
--virtual --seize` created the virtual controller. **GeForce NOW accepted
it**, and all controls worked in a game. Sticks seemed dead at first, but
that turned out to be the game's aim setting (mouse), not the bridge.

Open issue: the game felt very laggy. Possible sources, largest first:
GeForce NOW streaming (network), Wi-Fi/Bluetooth coexistence on 2.4 GHz,
the controller's ~30 ms report cadence (Phase 1), and the virtual device
hand-off, which Phase 3's numbers don't cover. The bridge now reports the
last one as `virtual: queue wait` and `virtual: dispatch` in its statistics.

## 8. Step B: running with protections on

With SIP and AMFI on, macOS only lets a program create a virtual HID device
if its restricted entitlement is backed by an Apple-issued provisioning
profile. There's no way around that; it's the security boundary working as
designed. So Step B needs:

1. **Your own Apple Developer Program membership** ($99/year, individual).
   Enrollment can take up to 48 hours.
2. **Full Xcode** from the App Store. Open it once, and add your Apple ID
   under Xcode → Settings → Accounts.
3. **Your Mac registered** to your developer team. Xcode does this
   automatically the first time it signs for it.

Then one check decides the route:

| If your team can add the "HID Virtual Device" capability (`com.apple.developer.hid.virtual.device`) | If it can't |
|---|---|
| **B1: Core HID, properly signed.** The Step A code stays as it is. It moves into a small app bundle, because provisioning profiles attach to apps, and gets signed with a development profile for your Mac. | **B2: DriverKit.** A driver extension creates the virtual device (DriverKit's development entitlements work with any paid account, no approval). The same app installs it as a system extension; you approve it once in System Settings. The bridge sends reports to the driver. |

Either way you get a **menu bar app**: starts at login, runs the bridge,
no Terminal needed.

Development signing isn't permanent. Certificates and provisioning profiles
expire (typically after a year), and the membership renews yearly. When a
profile expires, rebuilding in Xcode renews it.

**Restore protections now (section 7), without waiting for Step B.** The
test build stops launching (macOS kills it), and the controller goes back
to not working in GeForce NOW until Step B is done. That's expected.

**Tried: [PadLink](https://padlink.nimets.com/)** (notarized; presents
unrecognized controllers as a virtual DualShock 4). Right after launch it
listed the Raikiri as connected, but its driver never created a virtual
device (no `IOUserHIDDevice`, nothing with Sony's vendor ID 1356 in the
IORegistry). After a restart it listed the Raikiri under **"Handled by
macOS — Recognized by macOS"** and left it alone. That's the macOS 27 gap
from Phase 2: `GCController.supportsHIDDevice` returns YES for the
Raikiri, but no `GCController` is ever created, so any tool that defers to
the framework drops it. PadLink would need a "take over anyway" option.
Until then it doesn't help here.

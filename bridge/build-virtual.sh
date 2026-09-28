#!/bin/bash
# Phase 4, step A: build raikiri-bridge and ad-hoc sign it with the virtual HID
# entitlement. An ad-hoc signature can't vouch for a restricted entitlement, so
# macOS only runs the result while AMFI enforcement is off; otherwise the
# process is killed at launch ("Killed: 9"). See docs/phase4-virtual-device.md.
set -euo pipefail
cd "$(dirname "$0")"
swift build -c release
codesign --force --sign - --entitlements virtual-device.entitlements .build/release/raikiri-bridge
echo
echo "Signed. Entitlements now embedded:"
codesign -d --entitlements - .build/release/raikiri-bridge 2>/dev/null
echo
echo "Run:  .build/release/raikiri-bridge --virtual --seize"

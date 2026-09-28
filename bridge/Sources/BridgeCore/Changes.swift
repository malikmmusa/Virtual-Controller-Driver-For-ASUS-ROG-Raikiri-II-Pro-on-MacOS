// Human-readable descriptions of what changed between two gamepad states,
// for the bridge's console output. Coarse on purpose: sticks report a
// direction, triggers a released/half/full level, so jitter doesn't spam.

public enum Changes {
    /// Stick direction with a 25% dead zone around the center. HID Y grows
    /// downward, so a small Y means "up".
    public static func direction(x: UInt16, y: UInt16) -> String {
        let dx = Int(x) - 32768, dy = Int(y) - 32768
        let dead = 32768 / 4
        let h = dx < -dead ? "left" : (dx > dead ? "right" : "")
        let v = dy < -dead ? "up" : (dy > dead ? "down" : "")
        switch (v.isEmpty, h.isEmpty) {
        case (true, true): return "center"
        case (true, false): return h
        case (false, true): return v
        case (false, false): return "\(v)-\(h)"
        }
    }

    /// 10-bit trigger value as released (<10%), half, or full (>90%).
    public static func triggerLevel(_ value: UInt16) -> String {
        value < 102 ? "released" : (value > 921 ? "full" : "half")
    }

    public static func describe(from old: GamepadState, to new: GamepadState) -> [String] {
        var out: [String] = []
        let pressed = new.buttons.subtracting(old.buttons)
        let released = old.buttons.subtracting(new.buttons)
        out += pressed.names.map { "\($0) pressed" }
        out += released.names.map { "\($0) released" }
        if old.hat != new.hat {
            out.append("D-pad \(new.hat == 0 ? "released" : new.hatName)")
        }
        let (l0, l1) = (direction(x: old.leftX, y: old.leftY), direction(x: new.leftX, y: new.leftY))
        if l0 != l1 { out.append("left stick \(l1)") }
        let (r0, r1) = (direction(x: old.rightX, y: old.rightY), direction(x: new.rightX, y: new.rightY))
        if r0 != r1 { out.append("right stick \(r1)") }
        let (lt0, lt1) = (triggerLevel(old.leftTrigger), triggerLevel(new.leftTrigger))
        if lt0 != lt1 { out.append("LT \(lt1)") }
        let (rt0, rt1) = (triggerLevel(old.rightTrigger), triggerLevel(new.rightTrigger))
        if rt0 != rt1 { out.append("RT \(rt1)") }
        return out
    }
}

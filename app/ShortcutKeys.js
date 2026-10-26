.pragma library

function keyName(key, modifiers) {
    if (modifiers & Qt.KeypadModifier) {
        if (key >= Qt.Key_0 && key <= Qt.Key_9) return "KP" + (key - Qt.Key_0)
        const keypad = {}
        keypad[Qt.Key_Enter] = "KPENTER"; keypad[Qt.Key_Return] = "KPENTER"
        keypad[Qt.Key_Plus] = "KPPLUS"; keypad[Qt.Key_Minus] = "KPMINUS"
        keypad[Qt.Key_Asterisk] = "KPASTERISK"; keypad[Qt.Key_Slash] = "KPSLASH"
        keypad[Qt.Key_Period] = "KPDOT"; keypad[Qt.Key_Delete] = "KPDOT"
        keypad[Qt.Key_Insert] = "KP0"; keypad[Qt.Key_End] = "KP1"
        keypad[Qt.Key_Down] = "KP2"; keypad[Qt.Key_PageDown] = "KP3"
        keypad[Qt.Key_Left] = "KP4"; keypad[Qt.Key_Clear] = "KP5"
        keypad[Qt.Key_Right] = "KP6"; keypad[Qt.Key_Home] = "KP7"
        keypad[Qt.Key_Up] = "KP8"; keypad[Qt.Key_PageUp] = "KP9"
        return keypad[key] || ""
    }
    if (key >= Qt.Key_A && key <= Qt.Key_Z) return String.fromCharCode(65 + key - Qt.Key_A)
    if (key >= Qt.Key_0 && key <= Qt.Key_9) return String.fromCharCode(48 + key - Qt.Key_0)
    if (key >= Qt.Key_F1 && key <= Qt.Key_F24) return "F" + (key - Qt.Key_F1 + 1)
    const names = {}
    names[Qt.Key_Left] = "LEFT"; names[Qt.Key_Right] = "RIGHT"
    names[Qt.Key_Up] = "UP"; names[Qt.Key_Down] = "DOWN"
    names[Qt.Key_Return] = "ENTER"; names[Qt.Key_Enter] = "KPENTER"
    names[Qt.Key_Space] = "SPACE"; names[Qt.Key_Tab] = "TAB"; names[Qt.Key_Backtab] = "TAB"
    names[Qt.Key_Backspace] = "BACKSPACE"; names[Qt.Key_Delete] = "DELETE"
    names[Qt.Key_Home] = "HOME"; names[Qt.Key_End] = "END"
    names[Qt.Key_PageUp] = "PAGEUP"; names[Qt.Key_PageDown] = "PAGEDOWN"
    names[Qt.Key_Insert] = "INSERT"; names[Qt.Key_Print] = "SYSRQ"
    names[Qt.Key_VolumeUp] = "VOLUMEUP"; names[Qt.Key_VolumeDown] = "VOLUMEDOWN"
    names[Qt.Key_VolumeMute] = "MUTE"; names[Qt.Key_MediaPlay] = "PLAYPAUSE"
    names[Qt.Key_MediaTogglePlayPause] = "PLAYPAUSE"; names[Qt.Key_MediaNext] = "NEXTSONG"
    names[Qt.Key_MediaPrevious] = "PREVIOUSSONG"; names[Qt.Key_Pause] = "PAUSE"
    names[Qt.Key_CapsLock] = "CAPSLOCK"
    names[Qt.Key_Minus] = "MINUS"; names[Qt.Key_Equal] = "EQUAL"
    names[Qt.Key_Comma] = "COMMA"; names[Qt.Key_Period] = "DOT"
    names[Qt.Key_Slash] = "SLASH"; names[Qt.Key_Backslash] = "BACKSLASH"
    names[Qt.Key_Semicolon] = "SEMICOLON"; names[Qt.Key_Apostrophe] = "APOSTROPHE"
    names[Qt.Key_BracketLeft] = "LEFTBRACE"; names[Qt.Key_BracketRight] = "RIGHTBRACE"
    names[Qt.Key_QuoteLeft] = "GRAVE"
    return names[key] || ""
}

function chord(key, modifiers, altGrHeld) {
    const name = keyName(key,modifiers)
    if (!name) return null
    const altGr = altGrHeld || !!(modifiers & Qt.GroupSwitchModifier)
    const result = []
    // Qt can synthesize Ctrl+Alt for AltGr. Preserve the right-alt key instead.
    if (!altGr && (modifiers & Qt.ControlModifier)) result.push("CTRL")
    if (!altGr && (modifiers & Qt.AltModifier)) result.push("ALT")
    if ((modifiers & Qt.ShiftModifier) || key === Qt.Key_Backtab) result.push("SHIFT")
    if (modifiers & Qt.MetaModifier) result.push("SUPER")
    if (altGr) result.push("RIGHTALT")
    result.push(name)
    return result
}

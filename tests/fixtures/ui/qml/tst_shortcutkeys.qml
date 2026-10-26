import QtQuick
import QtTest
import "../../../../app/ShortcutKeys.js" as ShortcutKeys

TestCase {
    name: "ShortcutKeys"
    function test_letters_numbers_function_keys() {
        for (let i = 0; i < 26; i++) compare(ShortcutKeys.chord(Qt.Key_A + i,0,false),[String.fromCharCode(65 + i)])
        for (let i = 0; i < 10; i++) {
            compare(ShortcutKeys.chord(Qt.Key_0 + i,0,false),[String(i)])
            compare(ShortcutKeys.chord(Qt.Key_0 + i,Qt.KeypadModifier,false),["KP" + i])
        }
        for (let i = 1; i <= 24; i++) compare(ShortcutKeys.chord(Qt.Key_F1 + i - 1,0,false),["F" + i])
    }
    function test_combinations_data() {
        return [
            {tag:"AltGr+Q",key:Qt.Key_Q,mods:Qt.GroupSwitchModifier,held:false,want:["RIGHTALT","Q"]},
            {tag:"AltGr tracked",key:Qt.Key_Q,mods:Qt.ControlModifier | Qt.AltModifier,held:true,want:["RIGHTALT","Q"]},
            {tag:"AltGr synthetic modifiers",key:Qt.Key_Q,mods:Qt.ControlModifier | Qt.AltModifier | Qt.GroupSwitchModifier,held:false,want:["RIGHTALT","Q"]},
            {tag:"Ctrl+Alt+Q",key:Qt.Key_Q,mods:Qt.ControlModifier | Qt.AltModifier,held:false,want:["CTRL","ALT","Q"]},
            {tag:"Backtab",key:Qt.Key_Backtab,mods:0,want:["SHIFT","TAB"]},
            {tag:"Shift Backtab",key:Qt.Key_Backtab,mods:Qt.ShiftModifier,want:["SHIFT","TAB"]},
            {tag:"all modifiers",key:Qt.Key_A,mods:Qt.ControlModifier | Qt.AltModifier | Qt.ShiftModifier | Qt.MetaModifier,want:["CTRL","ALT","SHIFT","SUPER","A"]},
            {tag:"keypad left",key:Qt.Key_Left,mods:Qt.KeypadModifier,want:["KP4"]},
            {tag:"normal left",key:Qt.Key_Left,mods:0,want:["LEFT"]},
            {tag:"Ctrl keypad 4",key:Qt.Key_4,mods:Qt.KeypadModifier | Qt.ControlModifier,want:["CTRL","KP4"]},
            {tag:"keypad enter",key:Qt.Key_Enter,mods:Qt.KeypadModifier,want:["KPENTER"]},
            {tag:"enter key without modifier",key:Qt.Key_Enter,mods:0,want:["KPENTER"]},
            {tag:"keypad plus",key:Qt.Key_Plus,mods:Qt.KeypadModifier,want:["KPPLUS"]},
            {tag:"keypad minus",key:Qt.Key_Minus,mods:Qt.KeypadModifier,want:["KPMINUS"]},
            {tag:"keypad multiply",key:Qt.Key_Asterisk,mods:Qt.KeypadModifier,want:["KPASTERISK"]},
            {tag:"keypad divide",key:Qt.Key_Slash,mods:Qt.KeypadModifier,want:["KPSLASH"]},
            {tag:"keypad dot",key:Qt.Key_Period,mods:Qt.KeypadModifier,want:["KPDOT"]},
            {tag:"media",key:Qt.Key_MediaNext,mods:0,want:["NEXTSONG"]},
            {tag:"mute",key:Qt.Key_VolumeMute,mods:0,want:["MUTE"]},
            {tag:"unsupported Unicode",key:Qt.Key_At,mods:Qt.GroupSwitchModifier,want:null},
            {tag:"unsupported keypad equal",key:Qt.Key_Equal,mods:Qt.KeypadModifier,want:null},
            {tag:"unsupported media",key:Qt.Key_MediaStop,mods:0,want:null},
            {tag:"unknown",key:Qt.Key_unknown,mods:0,want:null}
        ]
    }
    function test_combinations(data) { compare(ShortcutKeys.chord(data.key,data.mods,data.held || false),data.want) }
    function test_named_key_table() {
        const rows = [
            [Qt.Key_Up,"UP"],[Qt.Key_Down,"DOWN"],[Qt.Key_Right,"RIGHT"],
            [Qt.Key_Return,"ENTER"],[Qt.Key_Space,"SPACE"],[Qt.Key_Tab,"TAB"],
            [Qt.Key_Backspace,"BACKSPACE"],[Qt.Key_Delete,"DELETE"],[Qt.Key_Insert,"INSERT"],
            [Qt.Key_Home,"HOME"],[Qt.Key_End,"END"],[Qt.Key_PageUp,"PAGEUP"],[Qt.Key_PageDown,"PAGEDOWN"],
            [Qt.Key_Print,"SYSRQ"],[Qt.Key_Pause,"PAUSE"],[Qt.Key_CapsLock,"CAPSLOCK"],
            [Qt.Key_VolumeUp,"VOLUMEUP"],[Qt.Key_VolumeDown,"VOLUMEDOWN"],
            [Qt.Key_MediaPlay,"PLAYPAUSE"],[Qt.Key_MediaTogglePlayPause,"PLAYPAUSE"],[Qt.Key_MediaPrevious,"PREVIOUSSONG"],
            [Qt.Key_Minus,"MINUS"],[Qt.Key_Equal,"EQUAL"],[Qt.Key_Comma,"COMMA"],[Qt.Key_Period,"DOT"],
            [Qt.Key_Slash,"SLASH"],[Qt.Key_Backslash,"BACKSLASH"],[Qt.Key_Semicolon,"SEMICOLON"],
            [Qt.Key_Apostrophe,"APOSTROPHE"],[Qt.Key_BracketLeft,"LEFTBRACE"],[Qt.Key_BracketRight,"RIGHTBRACE"],[Qt.Key_QuoteLeft,"GRAVE"]
        ]
        rows.forEach(function(row) { compare(ShortcutKeys.chord(row[0],0,false),[row[1]]) })
        const keypad = [
            [Qt.Key_Home,"KP7"],[Qt.Key_Up,"KP8"],[Qt.Key_PageUp,"KP9"],
            [Qt.Key_Left,"KP4"],[Qt.Key_Clear,"KP5"],[Qt.Key_Right,"KP6"],
            [Qt.Key_End,"KP1"],[Qt.Key_Down,"KP2"],[Qt.Key_PageDown,"KP3"],
            [Qt.Key_Insert,"KP0"],[Qt.Key_Delete,"KPDOT"],[Qt.Key_Return,"KPENTER"]
        ]
        keypad.forEach(function(row) { compare(ShortcutKeys.chord(row[0],Qt.KeypadModifier,false),[row[1]]) })
    }
}

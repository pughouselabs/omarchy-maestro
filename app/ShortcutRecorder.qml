pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Shapes
import QtQuick.Controls as Controls
import "ShortcutKeys.js" as ShortcutKeys

Column {
  id: root
  property var keys: []
  property var previousKeys: []
  property bool recording: false
  property string message: ""
  signal recorded(var chord)
  signal recordingStarted()
  signal canceled()
  spacing: Style.spacingLg

  property bool altGrHeld:false
  readonly property bool valid:keys.length > 0 && message === ""
  signal rejected(string reason)
  function keyName(key) { return ShortcutKeys.keyName(key,0) }
  function record(key,modifiers) {
    const chord = ShortcutKeys.chord(key,modifiers,altGrHeld)
    if (!chord) {
      keys = []; message = "That key can't be recorded"; rejected(message); return
    }
    keys = chord; message = ""; recorded(chord)
  }

  Card {
    width: parent.width
    height:72
    color:Theme.background; radius:8; border.width:root.recording ? 2 : root.keys.length ? 1 : 0
    border.color:root.recording ? Theme.accent : Theme.border
    FocusRing { control:input }
    Shape { id:idleOutline; anchors.fill:parent; visible:!root.recording && !root.keys.length
      ShapePath { fillColor:"transparent"; strokeColor:Theme.boundary; strokeWidth:1; strokeStyle:ShapePath.DashLine; dashPattern:[4,3]
        startX:8; startY:0
        PathLine { x:idleOutline.width-8; y:0 }
        PathArc { x:idleOutline.width; y:8; radiusX:8; radiusY:8 }
        PathLine { x:idleOutline.width; y:idleOutline.height-8 }
        PathArc { x:idleOutline.width-8; y:idleOutline.height; radiusX:8; radiusY:8 }
        PathLine { x:8; y:idleOutline.height }
        PathArc { x:0; y:idleOutline.height-8; radiusX:8; radiusY:8 }
        PathLine { x:0; y:8 }
        PathArc { x:8; y:0; radiusX:8; radiusY:8 }
      }
    }
    Controls.Control {
      id: input
      anchors.fill: parent
      activeFocusOnTab: true
      onActiveFocusChanged: {
        if (activeFocus) { root.previousKeys = root.keys.slice(); root.recording = true; root.message = ""; root.recordingStarted() }
        else { root.recording = false; root.altGrHeld = false }
      }
      MouseArea { anchors.fill: parent; onClicked: input.forceActiveFocus(Qt.MouseFocusReason) }
      Keys.priority: Keys.BeforeItem
      Keys.onPressed: function(event) {
        event.accepted = true
        if (event.isAutoRepeat) return
        if (event.key === Qt.Key_Escape) {
          root.keys = root.previousKeys.slice(); root.recording = false
          input.focus = false; root.message = "Recording canceled."; root.canceled()
          return
        }
        if (event.key === Qt.Key_AltGr) { root.altGrHeld = true; return }
        if ([Qt.Key_Control,Qt.Key_Shift,Qt.Key_Alt,Qt.Key_Meta].indexOf(event.key) >= 0) return
        root.record(event.key,event.modifiers)
      }
      Keys.onReleased:function(event) {
        if (event.key === Qt.Key_AltGr) root.altGrHeld = false
        event.accepted = true
      }

      Label { anchors.centerIn:parent; visible:!root.keys.length; text:root.recording ? "Press a shortcut" : "Click to record a shortcut"; color:Theme.muted }
      Row { anchors.centerIn:parent; spacing:6
        Repeater { model:root.keys
          Row { id:keycap; required property string modelData; required property int index; spacing:6
            Label { visible:keycap.index > 0; text:"+"; font.pixelSize:Style.fontCaption; color:Theme.muted; anchors.verticalCenter:parent.verticalCenter }
            Rectangle { width:keyLabel.implicitWidth+16; height:28; radius:6; color:Theme.surface; border.color:Theme.border
              Label { id:keyLabel; anchors.centerIn:parent; text:keycap.modelData; font.pixelSize:13; font.weight:Font.DemiBold }
            }
          }
        }
      }
    }
  }
  Label { width:parent.width; text:"Press the keys you want. Esc cancels."; font.pixelSize:Style.fontCaption; color:Theme.muted }
  Label { width: parent.width; visible: root.message !== ""; text: root.message; color: Theme.muted }
}

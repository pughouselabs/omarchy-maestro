pragma ComponentBehavior: Bound
import QtQuick
Rectangle {
  objectName:"keyboard-focus-ring"
  required property var control
  anchors.fill:parent; anchors.margins:-4
  radius:12; color:"transparent"; border.width:2; border.color:Theme.accent
  visible:control.visualFocus === true; z:100; Accessible.ignored:true
}

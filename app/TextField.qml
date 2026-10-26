pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls as Controls
Controls.TextField {
  id: root
  color: Theme.foreground
  placeholderTextColor: Theme.muted
  font.family: Theme.fontFamily; font.pixelSize: Style.fontBody
  implicitHeight:40
  padding:8; leftPadding:12; rightPadding:12
  verticalAlignment:TextInput.AlignVCenter
  selectByMouse: true
  selectionColor: Theme.accent; selectedTextColor: Theme.accentText
  background: Rectangle { color: Theme.background; radius: 8; border.color:Theme.boundary; FocusRing { control:root } }
}

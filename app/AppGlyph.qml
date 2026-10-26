pragma ComponentBehavior: Bound
import QtQuick
import Quickshell
Item {
  id:root
  property string icon:""
  property string label:""
  width:24; height:24
  Rectangle { anchors.fill:parent; radius:6; color:Theme.raised; visible:picture.status !== Image.Ready
    Label { anchors.centerIn:parent; text:root.label.slice(0,1).toUpperCase(); font.pixelSize:12; font.weight:Font.DemiBold }
  }
  Image { id:picture; anchors.fill:parent; source:root.icon.indexOf("fixture-") === 0 ? Quickshell.shellDir + "/../tests/fixtures/ui/icons/" + root.icon.slice(8) + ".svg" : root.icon ? Quickshell.iconPath(root.icon,true) : "" }
}

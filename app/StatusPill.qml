pragma ComponentBehavior: Bound
import QtQuick
Rectangle {
  id:root
  property string text:""
  property string glyph:"connection"
  property real level:-1
  implicitWidth:statusText.implicitWidth+44; implicitHeight:28
  width:implicitWidth; height:28; radius:14; color:Theme.raised
  Icon { x:10; anchors.verticalCenter:parent.verticalCenter; width:16; height:16; name:root.glyph; color:root.level >= 0 && root.level < 20 ? Theme.urgent : Theme.muted; visible:root.level < 0 }
  Item { x:10; width:16; height:12; anchors.verticalCenter:parent.verticalCenter; visible:root.level >= 0
    Rectangle { x:0; y:1; width:14; height:10; radius:2; color:"transparent"; border.color:root.level < 20 ? Theme.urgent : Theme.muted }
    Rectangle { x:2; y:3; width:10*Math.max(0,Math.min(100,root.level))/100; height:6; radius:1; color:root.level < 20 ? Theme.urgent : Theme.muted }
    Rectangle { x:14; y:4; width:2; height:4; radius:1; color:Theme.muted }
  }
  Label { id:statusText; x:32; anchors.verticalCenter:parent.verticalCenter; text:root.text; font.pixelSize:Style.fontCaption; color:Theme.muted }
}

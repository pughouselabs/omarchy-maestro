pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls as Controls
Controls.Slider {
  id:root
  implicitHeight:28
  activeFocusOnTab:true
  background:Rectangle {
    x:root.leftPadding; y:root.topPadding + root.availableHeight/2-height/2
    width:root.availableWidth; height:4; radius:2; color:Theme.border
    Rectangle { width:root.visualPosition*parent.width; height:parent.height; radius:2; color:Theme.accent }
  }
  handle:Rectangle {
    x:root.leftPadding+root.visualPosition*(root.availableWidth-width); y:root.topPadding+root.availableHeight/2-height/2
    width:18; height:18; radius:9; color:Theme.luminance(Theme.background) > 0.45 ? "white" : Theme.surface; border.width:1; border.color:Theme.muted
    Rectangle { z:-1; x:0; y:1; width:18; height:18; radius:9; color:"#40000000" }
    FocusRing { control:root; radius:13 }
  }
}

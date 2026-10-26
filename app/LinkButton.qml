pragma ComponentBehavior: Bound
import QtQuick
Button {
  id:root
  height:32; foreground:Theme.accent; leftPadding:0; rightPadding:0
  contentItem:Row { spacing:8
    Label { text:root.text; color:Theme.accent; font.underline:root.hovered; anchors.verticalCenter:parent.verticalCenter }
    Icon { name:"external"; width:14; height:14; color:Theme.accent; anchors.verticalCenter:parent.verticalCenter }
  }
}

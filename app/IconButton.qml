pragma ComponentBehavior: Bound
import QtQuick
Button {
  id:root
  width:32; height:32; padding:8; leftPadding:8; rightPadding:8
  Accessible.name:tooltipText
  contentItem:Icon { name:root.glyph; color:root.ink; opacity:root.enabled ? 1 : 0.38 }
}

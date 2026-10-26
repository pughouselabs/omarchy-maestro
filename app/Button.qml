pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls as Controls
Controls.Button {
  id:root
  property bool selected:false
  property bool bordered:false
  property bool focusable:true
  property bool leftAlign:false
  property string kind:"quiet"
  property string glyph:""
  property int glyphSize:16
  property int iconGap:8
  property color foreground:Theme.foreground
  property string tooltipText:""
  property color fill:"transparent"
  property color accent:Theme.accent
  readonly property bool primary:kind === "primary"
  readonly property color ink:primary ? Theme.accentText : selected && kind !== "segment" ? Theme.accent : foreground
  activeFocusOnTab:focusable
  padding:8; leftPadding:12; rightPadding:12
  implicitHeight:36
  font.family:Theme.fontFamily; font.pixelSize:Style.fontBody
  font.weight:selected || primary ? Font.DemiBold : Font.Normal
  contentItem:Item {
    implicitWidth:buttonLabel.implicitWidth + (root.glyph ? root.glyphSize+root.iconGap : 0)
    implicitHeight:20
    opacity:root.enabled ? 1 : root.primary ? 0.6 : 0.38
    Icon { visible:root.glyph !== ""; name:root.glyph; color:root.ink; width:root.glyphSize; height:root.glyphSize; anchors.left:parent.left; anchors.verticalCenter:parent.verticalCenter }
    Text {
      id:buttonLabel; anchors.fill:parent; anchors.leftMargin:root.glyph ? root.glyphSize+root.iconGap : 0
      text:root.text; textFormat:Text.PlainText; color:root.ink; font:root.font; elide:Text.ElideRight
      horizontalAlignment:root.leftAlign ? Text.AlignLeft : Text.AlignHCenter; verticalAlignment:Text.AlignVCenter
    }
  }
  background:Rectangle {
    radius:8
    color:root.primary ? Theme.alpha(Theme.accent,root.enabled ? 1 : 0.3) : root.selected ? root.kind === "segment" ? Theme.raised : Theme.accentWash : root.kind === "secondary" ? Theme.surface : root.fill
    border.width:root.bordered || root.kind === "secondary" ? 1 : 0
    border.color:Theme.alpha(root.selected ? Theme.accent : Theme.border,root.enabled ? root.selected ? 0.4 : 1 : 0.24)
    Rectangle { anchors.fill:parent; radius:parent.radius; color:Theme.foreground; opacity:root.down ? 0.1 : root.hovered ? 0.06 : 0; Behavior on opacity { NumberAnimation { duration:Style.motion; easing.type:Easing.OutCubic } } }
    FocusRing { control:root }
    Behavior on color { ColorAnimation { duration:Style.motion; easing.type:Easing.OutCubic } }
  }
  Controls.ToolTip { visible:root.hovered && root.tooltipText !== ""; text:root.tooltipText; delay:600
    enter:Transition { NumberAnimation { property:"opacity"; from:0; to:1; duration:100 } }
    exit:Transition { NumberAnimation { property:"opacity"; to:0; duration:0 } }
  }
}

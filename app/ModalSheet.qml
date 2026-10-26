pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Window
FocusScope {
  id:root
  property real sheetWidth:560
  property real sheetHeight:400
  default property alias content:sheet.data
  signal dismissed()
  anchors.fill:parent; z:45; visible:false
  function contains(item) { while (item) { if (item === root) return true; item=item.parent } return false }
  function cycle(backwards) {
    let item=root.Window.window.activeFocusItem || root
    for (let i=0;i<500;i++) { item=item.nextItemInFocusChain(!backwards); if (item !== root && root.contains(item) && item.activeFocusOnTab && item.visible && item.enabled) { item.forceActiveFocus(Qt.TabFocusReason); return } }
  }
  onVisibleChanged:if (visible) Qt.callLater(function() { if (!root.contains(root.Window.window.activeFocusItem)) { root.forceActiveFocus(); root.cycle(false) } })
  Keys.onPressed:function(event) {
    if (event.key === Qt.Key_Tab || event.key === Qt.Key_Backtab) { cycle(event.key === Qt.Key_Backtab || !!(event.modifiers & Qt.ShiftModifier)); event.accepted=true }
    if (event.key === Qt.Key_Escape) { root.dismissed(); event.accepted=true }
  }
  Rectangle { parent:root; anchors.fill:parent; color:Theme.alpha(Theme.background,0.7); MouseArea { anchors.fill:parent } }
  Card {
    id:sheet; width:Math.min(root.sheetWidth,root.width-64); height:Math.min(root.sheetHeight,root.height-64); anchors.centerIn:parent
    opacity:root.visible ? 1 : 0
    transform:Translate { y:root.visible ? 0 : 16; Behavior on y { NumberAnimation { duration:Style.panelMotion; easing.type:Easing.OutQuint } } }
  }
}

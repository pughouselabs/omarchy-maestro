pragma ComponentBehavior: Bound
import QtQuick

Item {
  id:root
  property int itemIndex:0
  property int itemCount:1
  property real rowHeight:80
  property color color:"#808080"
  property real dragOffset:0
  readonly property bool dragging:handler.active
  signal moved(int distance)
  implicitWidth:24; implicitHeight:44
  Repeater {
    model:6
    Rectangle {
      required property int index
      x:8+(index%2)*6; y:13+Math.floor(index/2)*7
      width:2; height:2; radius:1; color:root.color
    }
  }
  DragHandler {
    id:handler; target:null; xAxis.enabled:false
    grabPermissions:PointerHandler.CanTakeOverFromAnything
    // Qt clears translation before the release notification. Keep the last
    // offset while active, then consume it once on release.
    onTranslationChanged:if (active) root.dragOffset = translation.y
    onActiveChanged: {
      if (active) root.dragOffset = 0
      else {
        const distance = Math.max(-root.itemIndex,Math.min(root.itemCount-1-root.itemIndex,Math.round(root.dragOffset/root.rowHeight)))
        root.dragOffset = 0
        if (distance) root.moved(distance)
      }
    }
  }
}

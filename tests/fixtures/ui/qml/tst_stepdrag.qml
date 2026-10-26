pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls as Controls
import QtTest
import "../../../../app/interaction" as App

Item {
  id:surface; width:600; height:580
  property var order:["First","Second","Third"]
  property int moves:0
  Controls.ScrollView {
    id:scroll; width:500; height:400; contentWidth:availableWidth
    Flickable {
      id:flick; contentWidth:500; contentHeight:rows.implicitHeight
    Column {
      id:rows; width:500; spacing:16
      Repeater {
        model:surface.order
        Rectangle {
          id:row; required property int index; required property string modelData
          width:500; height:80; color:"#ddd"
          transform:Translate { y:handle.dragging ? handle.dragOffset : 0 }
          App.StepDragHandle {
            id:handle; objectName:"drag-"+row.index; width:24; height:44; y:18
            itemIndex:row.index; itemCount:surface.order.length; rowHeight:96
            onMoved:function(distance) {
              let next=surface.order.slice(), value=next.splice(row.index,1)[0]
              next.splice(row.index+distance,0,value); surface.order=next; surface.moves++
            }
          }
          Text { x:48; anchors.verticalCenter:parent.verticalCenter; text:row.modelData }
        }
      }
      Item { width:500; height:400 }
    }
    }
  }
  TestCase {
    name:"StepDrag"; when:windowShown
    function init() { surface.order=["First","Second","Third"]; surface.moves=0; flick.contentY=0; wait(30) }
    function drag(index,delta) {
      const handle=findChild(surface,"drag-"+index), point=handle.mapToItem(surface,12,22)
      mousePress(surface,point.x,point.y)
      mouseMove(surface,point.x,point.y+(delta>0 ? 20 : -20),30)
      mouseMove(surface,point.x,point.y+delta,30)
      mouseRelease(surface,point.x,point.y+delta)
      wait(30)
    }
    function test_release_reorders_without_scroll_steal() {
      drag(0,116)
      compare(surface.order,["Second","First","Third"])
      compare(surface.moves,1)
      compare(flick.contentY,0)
      drag(1,-116)
      compare(surface.order,["First","Second","Third"])
      compare(surface.moves,2)
    }
    function test_return_to_start_does_not_reorder() {
      const handle=findChild(surface,"drag-0"), point=handle.mapToItem(surface,12,22)
      mousePress(surface,point.x,point.y)
      mouseMove(surface,point.x,point.y+20,30)
      mouseMove(surface,point.x,point.y+116,30)
      mouseMove(surface,point.x,point.y,30)
      mouseRelease(surface,point.x,point.y)
      wait(30)
      compare(surface.order,["First","Second","Third"])
      compare(surface.moves,0)
    }
    function test_short_drag_does_not_reorder() { drag(0,30); compare(surface.order,["First","Second","Third"]); compare(surface.moves,0) }
    function test_drop_clamps_to_last_step() { drag(0,350); compare(surface.order,["Second","Third","First"]); compare(surface.moves,1) }
  }
}

pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls as Controls
ModalSheet {
  id:root
  required property var controller
  property int deleting:-1
  sheetWidth:560; sheetHeight:Math.min(500,180+controller.profiles.length*120)
  Column { anchors.fill:parent; anchors.margins:24; spacing:16
    Label { text:"Application profiles"; font.pixelSize:Style.fontTitle; font.weight:Font.DemiBold }
    Controls.ScrollView { width:parent.width; height:parent.height-104; contentWidth:availableWidth; clip:true
      Column { width:parent.width; spacing:16
        Label { visible:!root.controller.profiles.length; text:"Add an application to create its own settings."; color:Theme.muted }
        Repeater { model:root.controller.profiles
          Column { id:profileRow; required property var modelData; required property int index; width:parent.width; spacing:8
            Row { width:parent.width; spacing:12
              AppGlyph { icon:root.controller.profileIcon(profileRow.modelData); label:profileRow.modelData.name; anchors.verticalCenter:parent.verticalCenter }
              Column { width:(parent.width-92)/2; spacing:4
                Label { text:"Name"; font.pixelSize:Style.fontCaption; color:Theme.muted }
                TextField { width:parent.width; text:profileRow.modelData.name || ""; enabled:!root.controller.applying; onEditingFinished:if (text !== profileRow.modelData.name) root.controller.change("profiles."+profileRow.index+".name",text,false,true) }
              }
              Column { width:(parent.width-92)/2; spacing:4
                Label { text:"Window class"; font.pixelSize:Style.fontCaption; color:Theme.muted }
                TextField { width:parent.width; font.family:"monospace"; font.pixelSize:13; text:profileRow.modelData.match.class || ""; enabled:!root.controller.applying; onEditingFinished:if (text !== profileRow.modelData.match.class) root.controller.change("profiles."+profileRow.index+".match.class",text,false,true) }
              }
              IconButton { glyph:"trash"; tooltipText:"Delete profile"; foreground:hovered ? Theme.urgent : Theme.muted; anchors.verticalCenter:parent.verticalCenter; onClicked:root.deleting=profileRow.index }
            }
            Row { visible:root.deleting === profileRow.index; spacing:8
              Label { text:"Delete " + profileRow.modelData.name + "?"; anchors.verticalCenter:parent.verticalCenter }
              Button { text:"Delete"; foreground:Theme.urgent; enabled:!root.controller.applying; onClicked:{ let next=root.controller.copy(root.controller.config); next.profiles.splice(profileRow.index,1); root.controller.profileIndex=-1; root.controller.apply(next,false); root.deleting=-1 } }
              Button { text:"Cancel"; onClicked:root.deleting=-1 }
            }
            Rectangle { width:parent.width; height:1; color:Theme.alpha(Theme.border,0.6) }
          }
        }
      }
    }
    Button { text:"Done"; kind:"primary"; anchors.right:parent.right; onClicked:root.dismissed() }
  }
}

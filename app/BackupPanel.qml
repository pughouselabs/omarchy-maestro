pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls as Controls
import "BackupTime.js" as BackupTime
Item {
  id:root
  required property var controller
  signal restoreRequested(string name)
  Controls.ScrollView {
    width:Math.min(720,parent.width); height:parent.height; clip:true; contentWidth:availableWidth
    Column { width:parent.width; spacing:24
      Label { text:"Made automatically before every change."; color:Theme.muted; font.pixelSize:Style.fontCaption }
      Label { width:parent.width; visible:!root.controller.backups.length; text:"No backups yet. The first one is made when you change a setting."; color:Theme.muted }
      Column { width:parent.width; spacing:8
        Repeater { model:root.controller.backups
          Column {
            id:entry; required property var modelData; required property int index; width:parent.width; spacing:8
            SectionLabel { text:BackupTime.day(entry.modelData.time || entry.modelData.name); visible:entry.index === 0 || BackupTime.day(root.controller.backups[entry.index-1].time) !== text }
            Button { id:backupRow; width:parent.width; height:56; leftPadding:16; rightPadding:16; bordered:true; fill:Theme.surface; enabled:root.controller.configLoaded && !root.controller.applying
              contentItem:Item {
                Icon { x:0; name:"clock"; width:16; height:16; color:Theme.muted; anchors.verticalCenter:parent.verticalCenter }
                Column { x:28; width:parent.width-restore.width-40-(latest.visible ? latest.width+12 : 0); anchors.verticalCenter:parent.verticalCenter
                  Label { width:parent.width; text:BackupTime.format(entry.modelData.time || entry.modelData.name); maximumLineCount:1; elide:Text.ElideRight }
                  Label { text:entry.modelData.reason || "Automatic backup"; font.pixelSize:Style.fontCaption; color:Theme.muted }
                }
                StatusPill { id:latest; anchors.right:restore.left; anchors.rightMargin:12; text:"Latest"; glyph:"check"; color:Theme.accentWash; visible:entry.index === 0; anchors.verticalCenter:parent.verticalCenter }
                Button { id:restore; anchors.right:parent.right; text:"Restore"; foreground:hovered || visualFocus || backupRow.hovered || backupRow.visualFocus ? Theme.accent : Theme.muted; anchors.verticalCenter:parent.verticalCenter; onClicked:root.restoreRequested(entry.modelData.name) }
              }
              onClicked:root.restoreRequested(entry.modelData.name)
            }
          }
        }
      }
    }
  }
}

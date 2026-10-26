pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls as Controls
Item {
  id:root
  required property var controller
  property string credit:""
  property string changes:""
  property string creditUrl:""
  property string license:"CC BY-NC 4.0"
  property string licenseUrl:"https://creativecommons.org/licenses/by-nc/4.0/"
  property string imageModel:""
  property bool silhouette:false
  property url guide
  property bool keyboardOpen:false
  property bool creditsOpen:false
  signal tour()
  Controls.ScrollView { width:Math.min(720,parent.width); height:parent.height; contentWidth:availableWidth; clip:true
    Card { width:parent.width; height:helpRows.height
      Column { id:helpRows; width:parent.width
        Repeater { model:[{name:"Take the tour",description:"Three short steps",icon:"chevron-right",action:"tour"},{name:"Setup guide",description:"Start the background service, grant device access",icon:"external",action:"guide"},{name:"Report a problem",description:"",icon:"external",action:"report"},{name:"Keyboard shortcuts",description:"",icon:root.keyboardOpen ? "chevron-down" : "chevron-right",action:"keyboard"},{name:"About",description:"Maestro " + root.controller.versionString + " · Pughouse Labs" + " · engine " + (root.controller.catalog.engine_version || root.controller.versionString) + " · service " + (root.controller.serviceInactive ? "stopped" : "running"),icon:"copy",action:"about"},{name:"Image credits",description:"",icon:root.creditsOpen ? "chevron-down" : "chevron-right",action:"credits"}]
          Column { id:helpRow; required property var modelData; required property int index; width:parent.width
            Button { width:parent.width; height:52; leftAlign:true; leftPadding:16; rightPadding:16
              contentItem:Item {
                Column { width:parent.width-40; anchors.verticalCenter:parent.verticalCenter
                  Label { text:helpRow.modelData.name }
                  Label { width:parent.width; text:helpRow.modelData.description; visible:text !== ""; font.pixelSize:Style.fontCaption; color:Theme.muted; maximumLineCount:1; elide:Text.ElideRight }
                }
                Icon { anchors.right:parent.right; anchors.verticalCenter:parent.verticalCenter; width:16; height:16; name:helpRow.modelData.icon; color:Theme.muted }
              }
              onClicked: {
                if (helpRow.modelData.action === "tour") root.tour()
                else if (helpRow.modelData.action === "guide") Qt.openUrlExternally(root.guide)
                else if (helpRow.modelData.action === "report") Qt.openUrlExternally("https://github.com/pughouselabs/omarchy-maestro/issues")
                else if (helpRow.modelData.action === "keyboard") root.keyboardOpen=!root.keyboardOpen
                else if (helpRow.modelData.action === "credits") root.creditsOpen=!root.creditsOpen
                else if (helpRow.modelData.action === "about") { aboutCopy.selectAll(); aboutCopy.copy(); aboutCopy.deselect() }
              }
            }
            Column { x:16; width:parent.width-32; spacing:8; visible:helpRow.modelData.action === "credits" && root.creditsOpen
              Rectangle { width:parent.width; height:1; color:Theme.alpha(Theme.border,0.6) }
              Label { width:parent.width; visible:root.imageModel !== ""; text:root.silhouette ? "Picture shown for " + root.imageModel + ": neutral silhouette (no picture of this model yet)" : "Picture shown for " + root.imageModel; font.pixelSize:Style.fontCaption; font.weight:Font.DemiBold }
              Label { width:parent.width; text:root.credit; color:Theme.muted; font.pixelSize:Style.fontCaption }
              Label { width:parent.width; text:(root.changes ? root.changes + " " : "") + "This image is not covered by Maestro's MIT license" + (root.license.indexOf("NC") >= 0 ? " and may not be used commercially" : "") + ". Not affiliated with or endorsed by Logitech."; color:Theme.muted; font.pixelSize:Style.fontCaption }
              LinkButton { text:"Original model"; visible:root.creditUrl !== ""; onClicked:Qt.openUrlExternally(root.creditUrl) }
              LinkButton { text:root.license; onClicked:Qt.openUrlExternally(root.licenseUrl) }
              Item { width:1; height:8 }
            }
            Label { x:16; width:parent.width-32; bottomPadding:16; visible:helpRow.modelData.action === "keyboard" && root.keyboardOpen; text:"Esc closes a pane. Tab moves between dots. Enter opens the selected control."; color:Theme.muted }
            Rectangle { width:parent.width-32; x:16; height:1; color:Theme.alpha(Theme.border,0.6); visible:helpRow.index < 5 }
          }
        }
      }
    }
  }
  TextEdit { id:aboutCopy; visible:false; text:"Maestro " + root.controller.versionString + " · Pughouse Labs" + " · engine " + (root.controller.catalog.engine_version || root.controller.versionString) + " · service " + (root.controller.serviceInactive ? "stopped" : "running"); readOnly:true }
}

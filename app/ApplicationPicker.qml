pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls as Controls
import Quickshell.Hyprland
ModalSheet {
  id:root
  required property var controller
  signal closed()
  sheetWidth:560; sheetHeight:560
  property var openApps:[]
  onDismissed:visible=false
  function open() {
    visible=true; search.text=""; search.forceActiveFocus()
    if (controller.fixtureMode) refreshOpenApps()
    else { Hyprland.refreshToplevels(); Qt.callLater(refreshOpenApps) }
  }
  function refreshOpenApps() {
    if (controller.fixtureMode) {
      openApps=controller.applicationEntries.filter(function(e) { return e.open }).map(function(e) { return {name:e.name,appClass:e.startupClass,title:"",icon:e.icon,open:true} }); return
    }
    let list=[], values=Hyprland.toplevels.values
    for (let i=0;i<values.length;i++) {
      let data=values[i].lastIpcObject || {}
      if (data.class && !list.some(function(app) { return app.appClass === data.class })) list.push({name:data.class,appClass:data.class,title:data.title || "",icon:"",open:true})
    }
    openApps=list
  }
  function choose(app) {
    if (!app || !controller.configLoaded || controller.applying) return
    controller.addProfile(app.name,app.appClass); visible=false; closed()
  }
  function applications() {
    let needle=search.text.toLowerCase(), all=openApps.slice(), values=controller.applicationEntries
    for (let i=0;i<values.length;i++) {
      const entry=values[i], appClass=entry.startupClass || entry.id.replace(/\.desktop$/,"")
      const open=all.filter(function(app) { return app.appClass.toLowerCase() === appClass.toLowerCase() })[0]
      if (open) { open.name=entry.name; open.icon=entry.icon }
      else all.push({name:entry.name,appClass:appClass,title:"",icon:entry.icon,open:false})
    }
    return all.filter(function(app) { return (app.name+" "+app.appClass+" "+app.title).toLowerCase().indexOf(needle) >= 0 })
  }
  Column { anchors.fill:parent; anchors.margins:24; spacing:16
    Row { width:parent.width; spacing:8
      Label { width:parent.width-40; text:"Add application"; font.pixelSize:Style.fontTitle; font.weight:Font.DemiBold }
      IconButton { glyph:"close"; tooltipText:"Close"; onClicked:root.visible=false }
    }
    TextField { id:search; width:parent.width; placeholderText:"Find an application"; leftPadding:36
      Icon { name:"search"; x:12; width:16; height:16; anchors.verticalCenter:parent.verticalCenter; color:Theme.muted }
      Keys.onDownPressed:{ appList.currentIndex=0; appList.forceActiveFocus() }
    }
    ListView { id:appList; width:parent.width; height:parent.height-y; clip:true; spacing:0
      model:root.visible ? root.applications() : []; activeFocusOnTab:true; keyNavigationEnabled:true
      Controls.ScrollBar.vertical:Controls.ScrollBar {}
      section.property:"open"; section.criteria:ViewSection.FullString
      section.delegate:SectionLabel { required property string section; text:section === "true" ? "Open now" : "Installed"; height:28; verticalAlignment:Text.AlignVCenter }
      Keys.onReturnPressed:root.choose(appList.model[appList.currentIndex])
      FocusRing { control:({visualFocus:appList.activeFocus}) }
      delegate:Button { id:appRow; required property var modelData; required property int index; width:appList.width; height:52; leftAlign:true
        selected:appList.activeFocus && appList.currentIndex === index; enabled:root.controller.configLoaded && !root.controller.applying; Accessible.name:modelData.name
        contentItem:Row { spacing:12
          AppGlyph { icon:appRow.modelData.icon; label:appRow.modelData.name; anchors.verticalCenter:parent.verticalCenter }
          Column { width:parent.width-36; anchors.verticalCenter:parent.verticalCenter
            Label { width:parent.width; text:appRow.modelData.name; elide:Text.ElideRight; maximumLineCount:1 }
            Label { width:parent.width; text:appRow.modelData.appClass; font.pixelSize:Style.fontCaption; color:Theme.muted; maximumLineCount:1; elide:Text.ElideRight }
          }
        }
        onClicked:root.choose(modelData)
      }
    }
  }
  Connections { target:Hyprland.toplevels; function onValuesChanged() { if (root.visible && !root.controller.fixtureMode) root.refreshOpenApps() } }
}

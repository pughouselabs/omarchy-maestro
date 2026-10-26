pragma ComponentBehavior: Bound
import QtQuick
import Quickshell
import Quickshell.Io

ModalSheet {
  id:root
  required property var controller
  property int step:0
  property bool ready:false
  property bool completed:false
  property bool skipped:false
  property string starter:""
  readonly property string statePath:(Quickshell.env("XDG_STATE_HOME") || Quickshell.env("HOME") + "/.local/state") + "/maestro/welcome.json"
  signal chooseStarter(string id)
  sheetWidth:560; sheetHeight:root.step === 2 || !root.controller.device ? 512 : 460; z:60; visible:false
  signal finished()
  onDismissed:root.dismiss()
  function open() { step=0; visible=true; forceActiveFocus() }
  function save() { stateFile.setText(JSON.stringify({version:1,completed:completed,skipped:skipped})+"\n"); visible=false }
  function dismiss() { skipped=true; save() }
  function finish() { completed=true; skipped=false; save(); finished() }
  function maybeOpen() { if (ready && controller.configLoaded && !completed && !skipped) open() }
  FileView {
    id:stateFile; path:root.statePath; preload:true; printErrors:false; atomicWrites:true; blockWrites:true
    onLoaded: {
      try { const state=JSON.parse(text()); root.completed=state.completed === true; root.skipped=state.skipped === true }
      catch(error) { root.completed=false; root.skipped=false }
      root.ready=true; root.maybeOpen()
    }
    onLoadFailed: { root.ready=true; root.maybeOpen() }
  }
  Connections { target:root.controller; function onConfigLoadedChanged() { root.maybeOpen() } }
  Column {
    anchors.fill:parent; anchors.margins:32; spacing:16
    Row { anchors.horizontalCenter:parent.horizontalCenter; spacing:8; height:14
      Repeater { model:3; Rectangle { required property int index; width:6; height:6; radius:3; color:index === root.step ? Theme.accent : Theme.border } }
    }
    Label { text:root.step === 0 ? "Meet your mouse" : root.step === 1 ? "Try the gesture button" : "Pick a starter routine"; width:parent.width; font.pixelSize:22; font.weight:Font.DemiBold; horizontalAlignment:Text.AlignHCenter }
    Item { width:parent.width; height:200
      DeviceImage { anchors.fill:parent; visible:root.step < 2; hotspots:false; controller:root.controller; modelName:root.controller.device ? root.controller.device.model : "unknown"; view:root.step === 1 ? "top-down" : "hero" }
      Icon { visible:root.step === 2; anchors.centerIn:parent; name:"routine"; width:64; height:64; color:Theme.accent }
      Repeater { model:root.step === 1 ? [{x:0.5,y:0.02,icon:"chevron-up"},{x:0.25,y:0.5,icon:"chevron-left"},{x:0.75,y:0.5,icon:"chevron-right"},{x:0.5,y:0.85,icon:"chevron-down"}] : []
        Icon { required property var modelData; x:parent.width*modelData.x-10; y:parent.height*modelData.y; width:20; height:20; name:modelData.icon; color:Theme.accent; opacity:0; NumberAnimation on opacity { from:0; to:1; duration:400; running:root.visible && root.step === 1 } }
      }
    }
    Label { width:Math.min(440,parent.width); anchors.horizontalCenter:parent.horizontalCenter; color:Theme.muted; horizontalAlignment:Text.AlignHCenter; maximumLineCount:2
      text:root.step === 0 ? root.controller.device ? root.controller.device.model + " · " + root.controller.batteryLabel(root.controller.device) + " · " + root.controller.connectionLabel(root.controller.device) : "Wake your MX mouse, then choose Refresh to connect." : root.step === 1 ? "Hold the thumb button and move the mouse. Tap it to switch apps." : "Start with a routine. You can edit it and choose a button next."
    }
    Button { visible:root.step === 0 && !root.controller.device; text:root.controller.loading ? "Looking for your mouse…" : "Refresh"; bordered:true; enabled:!root.controller.loading; anchors.horizontalCenter:parent.horizontalCenter; onClicked:root.controller.refresh() }
    Dropdown { visible:root.step === 2; width:parent.width; value:root.starter; options:[{value:"",label:"Choose a starter (optional)"}].concat((root.controller.catalog.smart_action_templates || []).map(function(t) { return {value:t.id || t.name,label:t.name} })); onChanged:function(value) { root.starter=value } }
  }
    Item { anchors.left:parent.left; anchors.right:parent.right; anchors.bottom:parent.bottom; anchors.margins:32; height:36
      Button { text:"Skip"; tooltipText:"You can reopen this tour in Help."; onClicked:root.dismiss() }
      Row { anchors.right:parent.right; spacing:8
        Button { text:"Back"; visible:root.step > 0; onClicked:root.step-- }
        Button { text:root.step === 2 ? root.starter ? "Use this routine" : "Finish" : "Continue"; kind:"primary"; onClicked:{ if (root.step < 2) root.step++; else { if (root.starter) root.chooseStarter(root.starter); root.finish() } } }
      }
    }
}

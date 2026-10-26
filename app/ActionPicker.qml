pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls as Controls
import "CommandArgs.js" as CommandArgs

Rectangle {
  id: root
  property var catalog: ({groups:[]})
  property var automations: ({})
  property var candidate: null
  property var currentAction: null
  property var recorderOriginal: null
  property var describe: function(action) { return action ? action.type === "key" ? action.keys.join(" + ") : action.type === "command" ? action.argv.join(" ") : action.type === "automation" ? "Smart Action" : action.action || action.dispatcher || action.button || action.type : "Default" }
  property bool inheritable: false
  property bool stepMode: false
  property string category: ""
  property string editor: "catalog"
  property string message: ""
  property string title: "Choose an action"
  readonly property bool hasPendingEdits:visible && (!sameAction(candidate,currentAction) || message !== "")
  readonly property var recordedKeys:shortcut.keys
  readonly property string recordingMessage:shortcut.message
  function recordTestKey(key,modifiers,altGrHeld) {
    shortcut.altGrHeld = altGrHeld; shortcut.record(key,modifiers)
  }
  signal selected(var action, bool inherit)
  signal canceled()
  signal tryAction(var action)
  color:Theme.surface
  visible: false
  z: 10

  function sameAction(left,right) {
    if (left === right) return true
    if (!left || !right || typeof left !== "object" || typeof right !== "object" || Array.isArray(left) !== Array.isArray(right)) return false
    let keys = Object.keys(left)
    return keys.length === Object.keys(right).length && keys.every(function(key) {
      return Object.prototype.hasOwnProperty.call(right,key) && sameAction(left[key],right[key])
    })
  }
  function open(action, allowInherit, stepsOnly) {
    candidate = action; currentAction = action; inheritable = allowInherit; stepMode = stepsOnly || false
    message = ""; category = ""; search.text = ""; editor = stepsOnly && action && action.type === "key" ? "shortcut" : action && action.type === "command" ? "command" : "catalog"
    shortcut.keys = action && action.type === "key" ? action.keys : []
    argv.text = action && action.type === "command" ? CommandArgs.format(action.argv) : ""
    visible = true; search.forceActiveFocus()
  }
  function choose(action) {
    candidate = action; message = ""
    if (!stepMode) selected(action,false)
  }
  function categoryIcon(id) {
    return {omarchy:"maestro",windows:"windows",media:"media",browser:"windows",editing:"productivity",zoom:"screenshot",mouse:"mouse"}[id] || "routine"
  }
  function actions() {
    const result = !stepMode && !category && !search.text ? [{label:"Do nothing",action:{type:"none"},icon:"ban"}] : [], needle = search.text.toLowerCase()
    ;(catalog.groups || []).forEach(function(group) {
      if (root.category && root.category !== group.id) return
      const matches = (group.actions || []).filter(function(action) {
        return (!root.stepMode || ["key","command","desktop","mouse","hyprland"].indexOf(action.action.type) >= 0)
          && (action.label + " " + (action.description || "")).toLowerCase().indexOf(needle) >= 0
      })
      if (matches.length && !root.category) result.push({header:true,label:group.label,id:group.id})
      matches.forEach(function(action) { result.push(action) })
    })
    return result
  }
  function commandAction() {
    try {
      const args = CommandArgs.split(argv.text)
      if (!Array.isArray(args) || !args.length || args.some(function(value) { return typeof value !== "string" || !value.length || value.indexOf("\u0000") >= 0 }))
        throw new Error("Enter a program and its arguments.")
      candidate = {type:"command", argv:args}; message = ""
    } catch (error) { message = "Command: " + error.message }
  }
  Column {
    id:pickerBody; anchors.left:parent.left; anchors.right:parent.right; anchors.top:parent.top; anchors.bottom:footer.top; anchors.margins:16; spacing:12
    Row { width:parent.width; height:32; spacing:8
      IconButton { visible:root.stepMode; glyph:"chevron-left"; tooltipText:"Back"; onClicked:{ root.visible=false; root.canceled() } }
      Label { width:parent.width-40-(root.stepMode ? 40 : 0); text:root.title; font.pixelSize:Style.fontTitle; font.weight:Font.DemiBold; maximumLineCount:1; elide:Text.ElideRight }
      IconButton { glyph:"close"; tooltipText:"Close pane"; onClicked:{ root.visible=false; root.canceled() } }
    }
    Label { width:parent.width; text:"Now: " + root.describe(root.currentAction); font.pixelSize:Style.fontCaption; color:Theme.muted; maximumLineCount:1; elide:Text.ElideRight }
    Rectangle { width:parent.width; height:36; radius:8; color:Theme.background; border.color:Theme.border
      Row { anchors.fill:parent; anchors.margins:3; spacing:2
        Repeater { model:[{label:"Action",value:"catalog"},{label:"Shortcut",value:"shortcut"},{label:"Smart Action",value:"smart"},{label:"Command",value:"command"}].filter(function(item) { return !root.stepMode || item.value !== "smart" })
          Button { required property var modelData; text:modelData.label; width:(parent.width-(root.stepMode ? 4 : 6))/(root.stepMode ? 3 : 4); height:30; padding:4; leftPadding:2; rightPadding:2; font.pixelSize:Style.fontCaption; kind:"segment"; selected:root.editor === modelData.value; onClicked:root.editor=modelData.value }
        }
      }
    }
    TextField { id:search; width:parent.width; height:40; visible:root.editor === "catalog"; placeholderText:"Search actions"; leftPadding:36
      Icon { name:"search"; x:12; width:16; height:16; anchors.verticalCenter:parent.verticalCenter; color:Theme.muted }
    }
    Item { width:parent.width; height:28; visible:root.editor === "catalog"
      Flickable { id:categoryScroll; anchors.fill:parent; contentWidth:categories.width; contentHeight:28; clip:true; boundsBehavior:Flickable.StopAtBounds
      Row { id:categories; spacing:6
        Repeater { model:[{id:"",label:"All"}].concat(root.catalog.groups || [])
          Button { required property var modelData; text:modelData.label; height:28; padding:4; leftPadding:10; rightPadding:10; font.pixelSize:Style.fontCaption; bordered:true; selected:root.category === modelData.id; onClicked:root.category=modelData.id; background:Rectangle { radius:14; color:parent.selected ? Theme.accentWash : "transparent"; border.color:parent.selected ? Theme.alpha(Theme.accent,0.4) : Theme.border; FocusRing { control:parent.parent } } }
        }
      }
    }
      Rectangle { anchors.right:parent.right; width:24; height:28; visible:categoryScroll.contentX+categoryScroll.width < categoryScroll.contentWidth-1
        gradient:Gradient { orientation:Gradient.Horizontal; GradientStop { position:0; color:Theme.alpha(Theme.surface,0) } GradientStop { position:1; color:Theme.surface } }
      }
    }
    Controls.ScrollView { id:actionScroll; width:parent.width; height:Math.max(32,pickerBody.height-y); clip:true; contentWidth:availableWidth
      Column { width:actionScroll.availableWidth; spacing:0
        Repeater { model:root.editor === "catalog" ? root.actions() : []
          Item { id:actionRow; required property var modelData; width:parent.width; height:modelData.header ? 32 : 44
            SectionLabel { anchors.verticalCenter:parent.verticalCenter; width:parent.width; visible:!!actionRow.modelData.header; text:actionRow.modelData.label }
            Button { id:actionButton; width:parent.width; height:44; visible:!actionRow.modelData.header; leftAlign:true; fill:Theme.background
              readonly property bool isCurrent:root.sameAction(root.stepMode ? root.candidate : root.currentAction,actionRow.modelData.action)
              text:actionRow.modelData.label; glyph:actionRow.modelData.icon || ""; tooltipText:actionRow.modelData.description || ""; selected:isCurrent; rightPadding:32
              Icon { anchors.right:parent.right; anchors.rightMargin:12; anchors.verticalCenter:parent.verticalCenter; visible:actionButton.isCurrent; name:"check"; width:16; height:16; color:Theme.accent }
              Rectangle { anchors.bottom:parent.bottom; x:12; width:parent.width-24; height:1; color:Theme.alpha(Theme.border,0.6) }
              onClicked:root.choose(actionRow.modelData.action)
            }
          }
        }
        ShortcutRecorder { id:shortcut; width:parent.width; visible:root.editor === "shortcut"
          onRecordingStarted:root.recorderOriginal=root.candidate
          onCanceled:{ root.candidate=root.recorderOriginal; root.message="" }
          onRecorded:function(chord) { root.candidate={type:"key",keys:chord}; root.message="" }
          onRejected:function(reason) { root.candidate=root.recorderOriginal; root.message=reason }
        }
        Column { width:parent.width; spacing:12; visible:root.editor === "command"
          Label { text:"Command"; font.weight:Font.DemiBold }
          TextField { id:argv; width:parent.width; placeholderText:'notify-send "Hello from Maestro"'; onTextEdited:root.commandAction() }
          Label { width:parent.width; text:"Runs the program directly, without a shell. Quote arguments that contain spaces."; font.pixelSize:Style.fontCaption; color:Theme.muted }
        }
        Column { width:parent.width; visible:root.editor === "smart" && !root.stepMode
          Repeater { model:Object.keys(root.automations)
            Button { required property string modelData; width:parent.width; height:44; leftAlign:true; glyph:"routine"; text:(root.automations[modelData] || {}).name || modelData; selected:root.candidate && root.candidate.type === "automation" && root.candidate.id === modelData; onClicked:root.choose({type:"automation",id:modelData}) }
          }
          Label { visible:Object.keys(root.automations).length === 0; text:"Create one on the Smart Actions page."; color:Theme.muted }
        }
      }
    }
  }
  Column { id:footer; anchors.left:parent.left; anchors.right:parent.right; anchors.bottom:parent.bottom; spacing:4
    Label { width:parent.width-32; x:16; text:root.message; visible:text !== ""; color:Theme.urgent; font.pixelSize:Style.fontCaption }
    Item { width:parent.width; height:64
      Rectangle { width:parent.width; height:1; color:Theme.border }
      Button { x:8; anchors.verticalCenter:parent.verticalCenter; visible:!root.stepMode; text:"Restore default"; tooltipText:root.inheritable ? "Same as All applications" : "Restore default"; onClicked:root.inheritable ? root.selected(null,true) : root.choose(null) }
      Row { anchors.right:parent.right; anchors.rightMargin:16; anchors.verticalCenter:parent.verticalCenter; spacing:8
        Button { text:"Try it"; kind:"secondary"; enabled:!root.message && root.candidate !== null; onClicked:root.tryAction(root.candidate) }
        Button { text:"Assign"; kind:"primary"; enabled:!root.message && (root.editor === "shortcut" ? shortcut.valid : root.editor === "command" ? argv.text !== "" : root.candidate !== null) && (root.stepMode || !root.sameAction(root.candidate,root.currentAction)); onClicked:{ if (root.editor === "command") root.commandAction(); if (!root.message) { root.selected(root.candidate,false); if (root.stepMode) root.visible=false } } }
      }
    }
  }
  Keys.onEscapePressed:{ visible=false; canceled() }
}

pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls as Controls
import "interaction" as Interaction

Item {
  id: root
  required property var controller
  property string selectedId: ""
  property int editingStep: -1
  property bool stepEditorOpen:false
  property string deleteId: ""
  property string templateCategory:"All"
  property bool trySucceeded:false
  onSelectedIdChanged:trySucceeded = false
  function category(template) {
    const name = (template.name || "").toLowerCase()
    return name.indexOf("screen") >= 0 ? "Screenshots" : /mute|media|volume/.test(name) ? "Media" : /apps|window|workspace/.test(name) ? "Windows" : "Productivity"
  }
  function categoryIcon(name) { return {Productivity:"productivity",Media:"media",Screenshots:"screenshot",Windows:"windows"}[name] || "routine" }
  function templates() { return (controller.catalog.smart_action_templates || []).filter(function(t) { return root.templateCategory === "All" || root.category(t) === root.templateCategory }) }
  function tryRoutine() {
    trySucceeded = false
    commitPending(function(ok) {
      if (ok && root.automation) root.controller.testAction({type:"sequence",steps:root.automation.steps},function(success) { root.trySucceeded = success; if (success) successTimer.restart() })
    })
  }
  Timer { id:successTimer; interval:4000; onTriggered:root.trySucceeded = false }
  property var drafts: ({})
  property string draftError:""
  property alias stepPicker:picker
  readonly property bool pickerStepPending:stepEditorOpen && (editingStep < 0 || picker.hasPendingEdits)
  readonly property bool hasPendingEdits:Object.keys(drafts).length > 0 || pickerStepPending
  readonly property var automation: controller.automations[selectedId] || null
  readonly property var currentSteps:draftValue("steps",automation ? automation.steps : [])
  signal assign(string id)
  signal editingRequested(real position)
  function scrollToBottom() { smartBar.position=1-smartBar.size }
  function scrollToTop() { smartBar.position=0 }

  function draftValue(path,fallback) {
    const fields = drafts[selectedId] || {}
    if (Object.prototype.hasOwnProperty.call(fields,path)) return fields[path]
    const staged = path.indexOf("steps.") === 0 ? controller.read(fields,path) : undefined
    return staged === undefined ? fallback : staged
  }
  function setDraft(path,value) {
    if (!automation) return
    // Keep an unchanged staged steps array stable while typing in a field.
    const next = Object.assign({},drafts), fields = Object.assign({},next[selectedId] || {})
    const base = path.indexOf("steps.") === 0 && fields.steps ? fields : automation
    if (String(controller.read(base,path)) === String(value)) delete fields[path]
    else fields[path] = value
    if (Object.keys(fields).length) next[selectedId] = fields
    else delete next[selectedId]
    drafts = next; draftError = ""
  }
  function discardPending() { drafts = ({}); draftError = ""; stepEditorOpen=false; picker.visible = false }
  function commitPending(callback) {
    if (controller.applying) { if (callback) callback(false); return }
    if (pickerStepPending && !stagePickerAction(picker.candidate)) { if (callback) callback(false); return }
    if (!hasPendingEdits) { if (callback) callback(true); return }
    let next = controller.copy(controller.config), error = "", savedDrafts = controller.copy(drafts)
    Object.keys(savedDrafts).forEach(function(id) {
      if (!next.automations[id]) { error = "This Smart Action no longer exists. Keep editing or discard its pending changes."; return }
      let stepsEdited = false
      Object.keys(savedDrafts[id]).forEach(function(path) {
        const value = savedDrafts[id][path]
        if ((path === "name" || path === "description") && (!value.trim() || value.length > 500)) error = "Enter a name and description of 1 to 500 characters."
        if (path === "steps" || path.indexOf("steps.") === 0) stepsEdited = true
        controller.write(next.automations[id],path,path === "steps" ? controller.copy(value) : value,false)
      })
      if (stepsEdited) next.automations[id].steps.forEach(function(step) {
        if (step.type === "delay") {
          if (!/^\d+$/.test(String(step.ms)) || Number(step.ms) > 5000) error = "Enter a delay from 0 to 5000 milliseconds."
          else step.ms = Number(step.ms)
        }
        if (step.type === "text" && step.text.length > 500) error = "Text steps can contain up to 500 characters."
      })
    })
    if (error) { draftError = error; if (callback) callback(false); return }
    controller.apply(next,false,function(ok) {
      if (ok) {
        let remaining = controller.copy(root.drafts)
        Object.keys(savedDrafts).forEach(function(id) {
          Object.keys(savedDrafts[id]).forEach(function(path) {
            if (remaining[id] && root.controller.sameAction(remaining[id][path],savedDrafts[id][path])) delete remaining[id][path]
          })
          if (remaining[id] && !Object.keys(remaining[id]).length) delete remaining[id]
        })
        root.drafts = remaining; root.draftError = ""; picker.visible = false
      } else root.draftError = root.controller.fieldErrors.map(function(error) { return error.message }).join(" · ") || root.controller.message || "The pending changes could not be saved."
      if (callback) callback(ok && !root.hasPendingEdits)
    })
  }

  function stepValues() {
    let next = controller.copy(currentSteps), fields = drafts[selectedId] || {}
    Object.keys(fields).forEach(function(path) {
      if (path.indexOf("steps.") === 0) controller.write(next,path.slice(6),fields[path],false)
    })
    return next
  }
  function stageSteps(nextSteps) {
    // Fold positional field drafts into the steps before changing their order.
    // Keep the whole edited list pending if another field is not valid yet.
    const next = controller.copy(drafts), fields = next[selectedId] || {}
    Object.keys(fields).forEach(function(path) { if (path.indexOf("steps.") === 0) delete fields[path] })
    fields.steps = nextSteps; next[selectedId] = fields; drafts = next
  }
  function steps(nextSteps) { stageSteps(nextSteps); commitPending() }
  function stagePickerAction(action) {
    if (picker.message || !action) { draftError = picker.message || "Choose a valid step action."; return false }
    let next = stepValues()
    if (editingStep < 0) next.push(controller.copy(action))
    else next[editingStep] = controller.copy(action)
    stageSteps(next)
    // Use action and window close consume the same candidate exactly once.
    stepEditorOpen=false; picker.visible = false; picker.candidate = null; picker.currentAction = null
    editingStep = -1
    return true
  }
  function addStep(step) {
    let next = stepValues(); next.push(step); steps(next)
  }
  function openStepEditor(index) {
    editingStep = index; stepEditorOpen=true
    picker.open(index < 0 ? {type:"key",keys:["CTRL","C"]} : stepValues()[index],false,true)
  }
  function moveStep(index, direction) {
    if (pickerStepPending) {
      commitPending(function(ok) { if (ok) root.moveStep(index,direction) }); return
    }
    let next = stepValues(), value = next.splice(index,1)[0]
    next.splice(index + direction,0,value); steps(next)
  }
  function create(name, steps, description) {
    let next = controller.copy(controller.config), id = name.toLowerCase().replace(/[^a-z0-9]+/g,"-").replace(/^-|-$/g,"")
    next.automations = next.automations || {}
    let unique = id, n = 2
    while (Object.prototype.hasOwnProperty.call(next.automations,unique)) { unique = id + "-" + n; n++ }
    next.automations[unique] = {name:name,description:description || name,steps:steps}
    selectedId = unique; controller.apply(next,false)
    Qt.callLater(function() { root.editingRequested(editorSection.y) })
  }
  Controls.ScrollView {
    id:scroller; width:parent.width; anchors.top:parent.top; anchors.bottom:root.automation ? builderFooter.top : parent.bottom; contentWidth:availableWidth; clip:true
    Controls.ScrollBar.vertical:Controls.ScrollBar { id:smartBar }
    Column {
      width:root.automation ? Math.min(720,scroller.availableWidth) : scroller.availableWidth; spacing:24
      Column {
        width:parent.width; spacing:24; visible:root.automation === null
        Item { width:parent.width; height:36
          Button { anchors.right:parent.right; text:"New Smart Action"; glyph:"plus"; kind:"primary"; enabled:root.controller.configLoaded && !root.controller.applying; onClicked:root.create("My Smart Action",[{type:"delay",ms:250}]) }
        }
        Card { width:parent.width; height:120; visible:!Object.keys(root.controller.automations).length
          Label { anchors.centerIn:parent; text:"No routines yet. Start from a template below."; color:Theme.muted }
        }
        Card { width:parent.width; height:savedRows.height; visible:!!Object.keys(root.controller.automations).length
          Column { id:savedRows; width:parent.width
            Repeater { model:Object.keys(root.controller.automations)
              Button { id:savedAction; required property string modelData; required property int index; width:parent.width; height:56; leftAlign:true
                contentItem:Row { spacing:12
                  Rectangle { width:32; height:32; radius:6; color:Theme.accentWash; anchors.verticalCenter:parent.verticalCenter; Icon { anchors.centerIn:parent; name:"routine"; width:20; height:20; color:Theme.accent } }
                  Column { width:parent.width-assignAction.width-56; anchors.verticalCenter:parent.verticalCenter
                    Label { width:parent.width; text:(root.controller.automations[savedAction.modelData] || {}).name || savedAction.modelData; font.weight:Font.DemiBold; maximumLineCount:1; elide:Text.ElideRight }
                    Label { width:parent.width; text:root.controller.assignmentLocations(savedAction.modelData).length ? "On " + root.controller.assignmentLocations(savedAction.modelData).join(", ") : "Not on a button yet"; color:Theme.muted; font.pixelSize:Style.fontCaption; maximumLineCount:1; elide:Text.ElideRight }
                  }
                  Button { id:assignAction; text:"Assign"; glyph:"chevron-right"; anchors.verticalCenter:parent.verticalCenter; enabled:root.controller.device !== null; onClicked:root.assign(savedAction.modelData) }
                }
                Rectangle { x:16; width:parent.width-32; height:1; anchors.bottom:parent.bottom; color:Theme.alpha(Theme.border,0.6); visible:savedAction.index < savedRows.children.length-2 }
                onClicked:{ root.selectedId=modelData; root.scrollToTop() }
              }
            }
          }
        }
        Label { text:"Templates"; font.pixelSize:Style.fontHeading; font.weight:Font.DemiBold }
        Flow { width:parent.width; spacing:8
          Repeater { model:["All","Productivity","Media","Screenshots","Windows"]
            Button { required property string modelData; text:modelData; height:28; font.pixelSize:Style.fontCaption; selected:root.templateCategory === modelData; bordered:true; onClicked:root.templateCategory=modelData }
          }
        }
        Label { visible:!root.templates().length; text:"No templates here yet."; color:Theme.muted }
        Flow { id:templateGrid; width:parent.width; spacing:16
          readonly property int columns:Style.windowWidth > 1400 ? 4 : Style.windowWidth >= 1200 ? 3 : 2
          Repeater { model:root.templates()
            Button { id:templateCard; required property var modelData; width:(templateGrid.width-(templateGrid.columns-1)*16)/templateGrid.columns; height:180; bordered:true; fill:Theme.surface; leftAlign:true; padding:16; leftPadding:16; rightPadding:16
              enabled:root.controller.configLoaded && !root.controller.applying
              contentItem:Column { spacing:8
                Rectangle { width:36; height:36; radius:8; color:Theme.accentWash; Icon { anchors.centerIn:parent; name:root.categoryIcon(root.category(templateCard.modelData)); color:Theme.accent; width:20; height:20 } }
                Label { width:parent.width; height:22; text:templateCard.modelData.name; font.weight:Font.DemiBold; maximumLineCount:1; elide:Text.ElideRight }
                Label { width:parent.width; height:36; text:templateCard.modelData.description; font.pixelSize:Style.fontCaption; color:Theme.muted; maximumLineCount:2; elide:Text.ElideRight }
                Label { text:templateCard.modelData.steps.length === 1 ? "1 step" : templateCard.modelData.steps.length + " steps"; font.pixelSize:Style.fontCaption; color:Theme.muted }
              }
              onClicked:root.create(modelData.name,modelData.steps,modelData.description)
            }
          }
        }
      }
      Column {
        id:editorSection; width:parent.width; spacing:16; visible:root.automation !== null; enabled:!root.controller.applying
        Row { width:parent.width; spacing:8
          IconButton { glyph:"chevron-left"; tooltipText:"All Smart Actions"; onClicked:root.commitPending(function(ok) { if (ok) root.selectedId="" }) }
          TextField { id:nameInput; width:parent.width-48; height:40; topPadding:6; bottomPadding:6; font.pixelSize:Style.fontTitle; font.weight:Font.DemiBold; text:root.draftValue("name",root.automation ? root.automation.name : ""); onTextEdited:root.setDraft("name",text); onEditingFinished:root.commitPending()
            background:Rectangle { color:nameInput.activeFocus ? Theme.background : "transparent"; radius:8; border.width:nameInput.activeFocus ? 1 : 0; border.color:Theme.boundary; FocusRing { control:nameInput } }
          }
        }
        Label { text:"Smart Action"; font.pixelSize:Style.fontCaption; color:Theme.muted }
        TextField { width:parent.width; text:root.draftValue("description",root.automation ? root.automation.description : ""); placeholderText:"Description"; onTextEdited:root.setDraft("description",text); onEditingFinished:root.commitPending() }
        Label { width:parent.width; visible:root.hasPendingEdits; text:root.draftError || "Unsaved changes"; color:root.draftError ? Theme.urgent : Theme.muted }
        Card { width:parent.width; height:stepRows.height
          Column { id:stepRows; width:parent.width
            Repeater { model:root.currentSteps
              Item { id:stepCard; required property var modelData; required property int index; width:parent.width; height:48
                z:stepHandle.dragging ? 2 : 0
                transform:Translate { y:stepHandle.dragging ? stepHandle.dragOffset : 0; Behavior on y { enabled:!stepHandle.dragging; NumberAnimation { duration:180; easing.type:Easing.OutCubic } } }
                Rectangle { width:parent.width; height:2; color:Theme.accent; visible:stepHandle.dragging }
                Row { x:12; width:parent.width-24; height:48; spacing:8
                  Interaction.StepDragHandle { id:stepHandle; objectName:"step-handle-"+stepCard.index; width:24; height:44; itemIndex:stepCard.index; itemCount:root.currentSteps.length; rowHeight:48; color:Theme.muted; onMoved:function(distance) { root.moveStep(stepCard.index,distance) } }
                  Label { width:16; text:stepCard.index+1; color:Theme.muted; font.pixelSize:Style.fontCaption; anchors.verticalCenter:parent.verticalCenter }
                  Item { width:parent.width-168; height:48
                    Button { anchors.fill:parent; visible:stepCard.modelData.type !== "text" && stepCard.modelData.type !== "delay"; text:root.controller.describe(stepCard.modelData); leftAlign:true; leftPadding:0; onClicked:root.openStepEditor(stepCard.index) }
                    TextField { width:parent.width; height:36; anchors.verticalCenter:parent.verticalCenter; visible:stepCard.modelData.type === "text"; text:root.draftValue("steps."+stepCard.index+".text",stepCard.modelData.text || ""); placeholderText:"Text to type"; onTextEdited:root.setDraft("steps."+stepCard.index+".text",text); onEditingFinished:root.commitPending() }
                    Row { visible:stepCard.modelData.type === "delay"; anchors.verticalCenter:parent.verticalCenter; width:parent.width; spacing:4
                      Label { text:"Wait"; width:Math.max(32,parent.width-160); anchors.verticalCenter:parent.verticalCenter }
                      IconButton { width:24; glyph:"minus"; tooltipText:"Decrease delay"; onClicked:{ root.setDraft("steps."+stepCard.index+".ms",Math.max(0,Number(delayInput.text)-50)); root.commitPending() } }
                      TextField { id:delayInput; width:96; height:32; rightPadding:28; text:String(root.draftValue("steps."+stepCard.index+".ms",stepCard.modelData.ms || 0)); onTextEdited:root.setDraft("steps."+stepCard.index+".ms",text); onEditingFinished:root.commitPending()
                        Label { text:"ms"; anchors.right:parent.right; anchors.rightMargin:8; anchors.verticalCenter:parent.verticalCenter; color:Theme.muted; font.pixelSize:Style.fontCaption }
                      }
                      IconButton { width:24; glyph:"plus"; tooltipText:"Increase delay"; onClicked:{ root.setDraft("steps."+stepCard.index+".ms",Math.min(5000,Number(delayInput.text)+50)); root.commitPending() } }
                    }
                  }
                  IconButton { glyph:"chevron-up"; tooltipText:"Move up"; anchors.verticalCenter:parent.verticalCenter; enabled:stepCard.index > 0; onClicked:root.moveStep(stepCard.index,-1) }
                  IconButton { glyph:"chevron-down"; tooltipText:"Move down"; anchors.verticalCenter:parent.verticalCenter; enabled:stepCard.index < root.currentSteps.length-1; onClicked:root.moveStep(stepCard.index,1) }
                  IconButton { glyph:"trash"; tooltipText:"Remove step"; anchors.verticalCenter:parent.verticalCenter; enabled:root.currentSteps.length > 1; onClicked:{ let next=root.stepValues(); next.splice(stepCard.index,1); root.steps(next) } }
                }
                Rectangle { anchors.bottom:parent.bottom; width:parent.width-32; x:16; height:1; color:Theme.alpha(Theme.border,0.6) }
              }
            }
            Button { width:parent.width; height:48; text:"Add step"; glyph:"plus"; foreground:Theme.accent; leftAlign:true; onClicked:addStepMenu.open()
              Controls.Menu { id:addStepMenu; y:parent.height
                Controls.MenuItem { text:"Key or action"; onTriggered:root.openStepEditor(-1) }
                Controls.MenuItem { text:"Text"; onTriggered:root.addStep({type:"text",text:"Hello"}) }
                Controls.MenuItem { text:"Delay"; onTriggered:root.addStep({type:"delay",ms:250}) }
                Controls.MenuItem { text:"Mouse click"; onTriggered:root.addStep({type:"mouse",button:"left"}) }
                palette.window:Theme.surface; palette.text:Theme.foreground
              }
            }
          }
        }
        Label { width:parent.width; text:root.controller.errorsFor("automations."+root.selectedId,true); visible:text !== ""; color:Theme.urgent }
      }
    }
  }
  Item { id:builderFooter; anchors.bottom:parent.bottom; width:Math.min(720,parent.width); height:64; visible:root.automation !== null
    Rectangle { anchors.fill:parent; color:Theme.background }
    Rectangle { width:parent.width; height:1; color:Theme.border }
    Button { text:"Delete"; foreground:Theme.urgent; anchors.verticalCenter:parent.verticalCenter; onClicked:root.deleteId=root.selectedId }
    Row { anchors.right:parent.right; anchors.verticalCenter:parent.verticalCenter; spacing:8
      Button { objectName:"try-action"; text:root.trySucceeded ? "Started" : "Try it"; glyph:root.trySucceeded ? "check" : "play"; kind:"secondary"; onClicked:root.tryRoutine() }
      Button { text:"Assign to a button"; kind:"primary"; enabled:root.controller.device !== null; onClicked:root.commitPending(function(ok) { if (ok) root.assign(root.selectedId) }) }
    }
  }
  ModalSheet { visible:root.deleteId !== ""; sheetWidth:440; sheetHeight:180; onDismissed:root.deleteId=""
    Column { anchors.fill:parent; anchors.margins:24; spacing:16
      Label { text:"Delete this Smart Action?"; font.pixelSize:Style.fontTitle; font.weight:Font.DemiBold }
      Row { spacing:8
        Button { text:"Cancel"; onClicked:root.deleteId="" }
        Button { text:"Delete"; foreground:Theme.urgent; onClicked:{ let next=root.controller.copy(root.controller.config); delete next.automations[root.deleteId]; root.controller.apply(next,false); root.selectedId=""; root.deleteId="" } }
      }
    }
  }
  ModalSheet { visible:root.stepEditorOpen; sheetWidth:560; sheetHeight:Math.min(650,root.height); onDismissed:{ root.stepEditorOpen=false; picker.visible=false }
    ActionPicker { id:picker; anchors.fill:parent; catalog:root.controller.catalog; automations:root.controller.automations
      onCanceled:root.stepEditorOpen=false
      onSelected:function(action) { if (!root.controller.applying && root.stagePickerAction(action)) root.commitPending() }
      onTryAction:function(action) { root.controller.testAction(action) }
    }
  }
}

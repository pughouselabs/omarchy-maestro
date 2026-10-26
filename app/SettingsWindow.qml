pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Window
import QtQuick.Controls as Controls
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import "BackupTime.js" as BackupTime

Item {
  id: root
  property alias controller: appController
  property string page: "home"
  property string deviceTab: "buttons"
  property string drawer: ""
  onDrawerChanged: if (drawer !== "actions") picker.visible = false
  property string actionPath: ""
  property string pendingAutomation: ""
  property string restoreName: ""
  property int deletingProfile: -1
  property bool managingProfiles: false
  property bool resettingDefaults:false
  property int activationAttempts: 0
  property bool captureDone:false
  property bool serviceHelpAvailable:false
  property bool closeDialog:false
  property bool closePending:false
  property bool closingSave:false
  property bool allowExit:false
  property int focusRequests:0
  readonly property bool pendingSmartEdits:smartActions.hasPendingEdits
  readonly property var smartDrafts:smartActions.drafts
  readonly property var recordedKeys:picker.recordedKeys
  readonly property string recordingMessage:picker.recordingMessage
  readonly property string serviceLauncherPath:appController.queue.repoPath + "/bin/maestrod"
  readonly property url serviceGuideUrl:"file://" + appController.queue.repoPath.split("/").map(encodeURIComponent).join("/") + "/README.md#start-maestros-background-service"
  property var focusProbeResult:({})
  readonly property var designStatus:({focusProbe:focusProbeResult,fixtureApps:appController.fixtureMode ? appController.applicationEntries.map(function(e) { return e.name }) : [],uiBoundaryContrast:Math.min(Theme.contrast(Theme.boundary,Theme.background),Theme.contrast(Theme.boundary,Theme.surface),Theme.contrast(Theme.boundary,Theme.raised)),hotspots:deviceView.probeGeometry,focusStops:deviceView.focusStops(),credit:root.deviceImageCredit,welcomeSkipped:welcome.skipped,welcomeReady:welcome.ready,welcomeVisible:welcome.visible,welcomeStep:welcome.step,welcomeCompleted:welcome.completed,welcomePath:welcome.statePath,trySucceeded:smartActions.trySucceeded,templateCount:smartActions.templates().length,themeColors:{accent:Theme.accent.toString(),accentText:Theme.accentText.toString(),white:Theme.contrast(Theme.accent,"#ffffff"),black:Theme.contrast(Theme.accent,"#111111")},contrast:{foreground:Math.min(Theme.contrast(Theme.foreground,Theme.background),Theme.contrast(Theme.foreground,Theme.surface),Theme.contrast(Theme.foreground,Theme.raised)),muted:Math.min(Theme.contrast(Theme.muted,Theme.background),Theme.contrast(Theme.muted,Theme.surface),Theme.contrast(Theme.muted,Theme.raised)),accent:Math.min(Theme.contrast(Theme.accent,Theme.background),Theme.contrast(Theme.accent,Theme.surface),Theme.contrast(Theme.accent,Theme.raised)),primary:Theme.contrast(Theme.accentText,Theme.accent)}})
  readonly property bool opened: window.visible
  readonly property var metrics:({width:window.width,height:window.height,screen:window.screen ? window.screen.name : "",dpr:window.screen ? window.screen.devicePixelRatio : 1,fontBody:Style.fontBody,fontCaption:Style.fontCaption,heading:Style.fontHeading})

  property bool keyboardHelp:false
  property bool creditsOpen:false
  property bool overflowOpen:false
  property string tourToast:""
  // Credits follow the picture the device view shows for this model (DeviceAssets.js).
  readonly property string deviceImageCredit:deviceView.credit.text
  readonly property string deviceImageChanges:deviceView.credit.changes
  AppState { id: appController }
  FileView {
    id:serviceLauncher
    path:root.serviceLauncherPath
    preload:true; watchChanges:true; printErrors:false
    onFileChanged:reload()
    onLoaded:root.serviceHelpAvailable = true
    onLoadFailed:root.serviceHelpAvailable = false
  }
  function focusWindow() {
    focusRequests++
    window.visible = true; window.minimized = false; focusScope.forceActiveFocus()
    activationAttempts = 0; activationTimer.restart()
  }
  function finishClose() { allowExit = true; Qt.quit() }
  function requestClose() {
    if (allowExit || closingSave) return
    window.visible = true
    if (appController.applying) { closePending = true; return }
    closePending = false
    if (!smartActions.hasPendingEdits) { finishClose(); return }
    closingSave = true
    smartActions.commitPending(function(ok) {
      root.closingSave = false
      if (ok) root.finishClose()
      else { root.closeDialog = true; root.focusWindow() }
    })
  }
  function keepEditing() { closeDialog = false; closePending = false; focusWindow() }
  function discardAndClose() { smartActions.discardPending(); finishClose() }
  function activate() {
    let values = ToplevelManager.toplevels.values
    for (let i = 0; i < values.length; i++) {
      if (values[i].title === "Maestro") { values[i].activate(); return }
    }
    activationAttempts++
    if (activationAttempts < 8) activationTimer.restart()
  }
  function selectControl(name) {
    if (name === "thumb_wheel" && appController.builtInThumbWheel) { drawer = "wheel"; return }
    if (!appController.writable || !appController.available(name)) return
    if (name === "gesture" && appController.device.gesture === true && !pendingAutomation) { drawer = "gestures"; return }
    if (name === "thumb_wheel") { drawer = "wheel"; return }
    pick("buttons." + name)
  }
  function pick(path) {
    actionPath = path; drawer = "actions"
    picker.title = path.indexOf("gesture.") === 0 ? "Gesture · " + path.split(".")[1] : path.indexOf("thumb_wheel") === 0 ? "Thumb wheel · " + path.split(".")[1] : path.split(".")[1].replace(/_/g," ")
    picker.title = picker.title.charAt(0).toUpperCase() + picker.title.slice(1) + (path.indexOf("buttons.") === 0 && path !== "buttons.thumb_wheel" ? " button" : "")
    picker.open(pendingAutomation ? {type:"automation",id:pendingAutomation} : appController.effective(path,null),appController.profileIndex >= 0,false)
  }
  function profileIcon() {
    if (appController.profileIndex < 0 || appController.profileIndex >= appController.profiles.length) return "input-mouse"
    let match = appController.profiles[appController.profileIndex].match.class.toLowerCase(), entries = appController.applicationEntries
    for (let i = 0; i < entries.length; i++) {
      if ((entries[i].startupClass || "").toLowerCase() === match || entries[i].id.toLowerCase().replace(/\.desktop$/,"") === match) return entries[i].icon
    }
    return "application-x-executable"
  }
  Timer { id:activationTimer; interval:75; onTriggered:root.activate() }
  Component.onCompleted: { serviceLauncher.reload(); appController.refresh(); root.focusWindow() }

  FloatingWindow {
    id:window
    title:"Maestro"; color:Theme.background
    implicitWidth:root.testDimension("MAESTRO_UI_WIDTH",1280,1000)
    implicitHeight:root.testDimension("MAESTRO_UI_HEIGHT",820,680)
    minimumSize:Qt.size(1000,680)
    onWidthChanged:Style.windowWidth=width
    Component.onCompleted:Style.windowWidth=width
    visible:true
    onClosed: {
      if (root.allowExit) return
      visible=false
      Qt.callLater(function() { window.visible=true; root.requestClose() })
    }
    FocusScope {
      id:focusScope; anchors.fill:parent; focus:true
      Rectangle { anchors.fill:parent; color:Theme.background; z:-1 }
      Keys.onPressed:function(event) {
        if (event.key !== Qt.Key_Escape) return
        if (root.closeDialog) root.keepEditing()
        else if (welcome.visible) welcome.dismiss()
        else if (root.resettingDefaults) root.resettingDefaults=false
        else if (root.restoreName) root.restoreName=""
        else if (root.managingProfiles) root.managingProfiles=false
        else if (applications.visible) applications.visible=false
        else if (root.drawer !== "") { root.drawer=""; picker.visible=false }
        else if (root.page === "device") root.page="home"
        event.accepted=true
      }
      Rectangle {
        id:rail; width:220; anchors.top:parent.top; anchors.bottom:parent.bottom; color:Theme.surface
        enabled:!root.closeDialog && !welcome.visible && !root.resettingDefaults && !root.managingProfiles && !root.restoreName && !applications.visible
        opacity:welcome.visible ? 0.4 : 1
        Rectangle { anchors.right:parent.right; width:1; height:parent.height; color:Theme.border }
        Column {
          anchors.left:parent.left; anchors.right:parent.right; anchors.top:parent.top; anchors.margins:16; anchors.topMargin:24; spacing:8
          Item { width:parent.width; height:48; Brand { anchors.top:parent.top; height:40 } }
          Button { width:parent.width; height:36; text:"My devices"; glyph:"mouse"; glyphSize:18; iconGap:12; leftAlign:true; selected:root.page === "home" || root.page === "device"; onClicked:{ root.page="home"; root.drawer="" } }
          Button { width:parent.width; height:36; text:"Smart Actions"; glyph:"routine"; glyphSize:18; iconGap:12; leftAlign:true; selected:root.page === "smart"; onClicked:{ root.page="smart"; root.drawer="" } }
          Button { width:parent.width; height:36; text:"Backups"; glyph:"backup"; glyphSize:18; iconGap:12; leftAlign:true; selected:root.page === "backups"; onClicked:{ root.page="backups"; root.drawer=""; appController.loadBackups() } }
        }
        Column {
          anchors.left:parent.left; anchors.right:parent.right; anchors.bottom:parent.bottom; anchors.margins:16; spacing:8
          Button { width:parent.width; text:"Help"; glyph:"help"; glyphSize:18; iconGap:12; leftAlign:true; selected:root.page === "help"; onClicked:{ root.page="help"; root.drawer="" } }
          Label { leftPadding:12; text:"Maestro " + appController.versionString; color:Theme.muted; font.pixelSize:Style.fontCaption }
        }
      }
      Item {
        id:content; x:rail.width+32+Math.max(0,(parent.width-rail.width-64-1040)/2); y:24
        width:Math.min(1040,parent.width-rail.width-64); height:parent.height-48
        enabled:rail.enabled; opacity:welcome.visible ? 0.4 : 1
        Item {
          id:header; width:parent.width; height:40
          Label { id:pageTitle; anchors.left:parent.left; anchors.verticalCenter:parent.verticalCenter; width:parent.width-headerActions.width-24; wrapMode:Text.NoWrap; maximumLineCount:1; elide:Text.ElideRight
            text:root.page === "home" ? "Your devices" : root.page === "smart" ? "Smart Actions" : root.page === "backups" ? "Backups" : root.page === "help" ? "Help" : appController.device ? appController.device.model : "Your mouse"
            font.pixelSize:Style.fontDisplay; font.weight:Font.DemiBold; font.letterSpacing:-0.3; lineHeight:1.2
          }
          Row { id:headerActions; anchors.right:parent.right; anchors.verticalCenter:parent.verticalCenter; spacing:8
            Row { visible:root.page === "device" && !!appController.device; spacing:8; rightPadding:8; anchors.verticalCenter:parent.verticalCenter
              StatusPill { text:appController.batteryLabel(appController.device); level:appController.device && appController.device.battery ? appController.device.battery.percent : -1; glyph:"battery" }
              StatusPill { text:appController.connectionLabel(appController.device) }
            }
            Button { text:"Undo"; visible:appController.undoConfig !== null && appController.toast === ""; enabled:!appController.applying; onClicked:appController.undo() }
            IconButton { glyph:"refresh"; tooltipText:appController.loading ? "Refreshing…" : "Refresh devices"; enabled:!appController.loading && !appController.applying; onClicked:appController.refresh() }
            IconButton { glyph:"close"; tooltipText:"Close Maestro"; onClicked:root.requestClose() }
          }
        }
        Column {
          id:notice; anchors.top:header.bottom; anchors.topMargin:appController.serviceInactive || appController.message || appController.fieldErrors.length || appController.applying ? 16 : 0; width:parent.width; spacing:8
          Card { width:parent.width; height:serviceBannerLabel.implicitHeight+32; visible:appController.serviceInactive; color:Theme.accentWash; radius:8; border.color:Theme.alpha(Theme.accent,0.4)
            Row { anchors.fill:parent; anchors.margins:16; spacing:16
              Icon { name:"info"; width:20; height:20; color:Theme.accent }
              Label { id:serviceBannerLabel; width:parent.width-36-(startServiceHelp.visible ? startServiceHelp.width+16 : 0); text:appController.serviceNotice }
              Button { id:startServiceHelp; visible:root.serviceHelpAvailable; text:"How to start it"; glyph:"external"; foreground:Theme.accent; padding:0; leftPadding:0; rightPadding:0; onClicked:Qt.openUrlExternally(root.serviceGuideUrl) }
            }
          }
          Label { width:parent.width; visible:appController.message !== ""; text:appController.message; color:Theme.urgent }
          Button { visible:appController.message !== "" && appController.device !== null && appController.device.release_available === true; text:"Release button"; bordered:true; enabled:!appController.applying; tooltipText:"Free a button that another app or an earlier Maestro run left diverted"; onClicked:appController.releaseButtons() }
          Repeater { model:appController.fieldErrors; Label { required property var modelData; width:notice.width; text:modelData.path+": "+modelData.message; color:Theme.urgent; font.pixelSize:12 } }
          Label { visible:appController.applying; text:"Saving…"; color:Theme.muted }
        }
        Item {
          id:body; anchors.top:notice.bottom; anchors.topMargin:24; anchors.bottom:parent.bottom; width:parent.width
          HomePanel { anchors.fill:parent; visible:root.page === "home"; controller:appController; onSelectedDevice:function(index) { appController.deviceIndex=index; root.page="device"; root.drawer="" } }
          Item {
            anchors.fill:parent; visible:root.page === "device"
            Item {
              id:deviceHeader; width:parent.width; height:40
              Rectangle { width:tabRow.width+8; height:40; radius:8; color:Theme.surface; border.color:Theme.border
                Row { id:tabRow; anchors.centerIn:parent; spacing:4
                  Button { text:"Buttons"; kind:"segment"; height:32; selected:root.deviceTab === "buttons"; onClicked:{ root.deviceTab="buttons"; root.drawer="" } }
                  Button { text:"Point & scroll"; kind:"segment"; height:32; selected:root.deviceTab === "point"; onClicked:{ root.deviceTab="point"; root.drawer="" } }
                }
              }
              Row { anchors.right:parent.right; spacing:8
                Dropdown { width:220; profileMenu:true; value:String(appController.profileIndex); options:appController.profileOptions(); onChanged:function(value) { if (value === "add") applications.open(); else if (value === "manage") root.managingProfiles=true; else { appController.profileIndex=Number(value); root.drawer="" } } }
                IconButton { glyph:"more"; tooltipText:"Device options"; onClicked:overflowMenu.open() }
                Controls.Menu { id:overflowMenu; y:40; width:220
                  Controls.MenuItem { text:"Reset to defaults"; enabled:appController.writable && !!appController.catalog.defaults; onTriggered:root.resettingDefaults=true }
                  Controls.MenuItem { text:"Manage profiles"; onTriggered:root.managingProfiles=true }
                  palette.window:Theme.surface; palette.text:Theme.foreground
                }
              }
            }
            Label { id:profileHint; anchors.top:deviceHeader.bottom; anchors.topMargin:8; width:parent.width; visible:appController.profileIndex >= 0 || !!root.pendingAutomation || !!appController.device && !appController.device.writable; font.pixelSize:Style.fontCaption; color:Theme.muted
              text:root.pendingAutomation ? "Choose a button for " + (appController.automations[root.pendingAutomation] || {}).name : appController.device && !appController.device.writable ? "This mouse is read only. Check its connection and device access, then choose Refresh." : appController.profileIndex >= 0 ? "Only in " + appController.profiles[appController.profileIndex].name + ". Buttons you don't change keep the All applications setting." : ""
            }
            Item {
              id:deviceWork; anchors.top:deviceHeader.bottom; anchors.topMargin:profileHint.visible ? profileHint.height+16 : 24; anchors.bottom:parent.bottom; width:parent.width
              DeviceImage { id:deviceView; width:Math.max(0,parent.width-(root.drawer ? drawerCard.width+16 : 0)); height:parent.height; visible:root.deviceTab === "buttons"; controller:appController; onChosen:function(name) { root.selectControl(name) } }
              Controls.ScrollView {
                Controls.ScrollBar.vertical:Controls.ScrollBar { id:pointBar }
                width:Math.min(720,parent.width-(root.drawer ? drawerCard.width+16 : 0)); height:parent.height
                visible:root.deviceTab === "point"; clip:true; contentWidth:availableWidth
                PointScroll { width:parent.width; controller:appController; onPick:function(path) { root.pick(path) } }
              }
              Rectangle {
                id:drawerCard; width:420; height:parent.height; anchors.right:parent.right; color:Theme.surface; visible:opacity > 0; opacity:root.drawer ? 1 : 0
                Rectangle { width:1; height:parent.height; color:Theme.border }
                transform:Translate { x:root.drawer ? 0 : 16; Behavior on x { NumberAnimation { duration:Style.panelMotion; easing.type:Easing.OutQuint } } }
                Behavior on opacity { NumberAnimation { duration:Style.panelMotion; easing.type:Easing.OutQuint } }
                Item { anchors.fill:parent; visible:root.drawer === "gestures" || root.drawer === "wheel"
                  IconButton { id:closePane; anchors.top:parent.top; anchors.right:parent.right; anchors.margins:12; z:2; glyph:"close"; tooltipText:"Close pane"; onClicked:root.drawer="" }
                  Controls.ScrollView { anchors.fill:parent; anchors.margins:16; anchors.topMargin:20; clip:true; contentWidth:availableWidth
                    Column { width:parent.width; spacing:16
                      GesturePanel { id:gestureEditor; width:parent.width; controller:appController; visible:root.drawer === "gestures"; onPick:function(path) { root.pick(path) } }
                      PointScroll { width:parent.width; controller:appController; visible:root.drawer === "wheel"; wheelOnly:true; onPick:function(path) { root.pick(path) } }
                    }
                  }
                }
                ActionPicker { id:picker; anchors.fill:parent; catalog:appController.catalog; automations:appController.automations; describe:appController.describe
                  onSelected:function(action,inherit) {
                    if (!appController.writable) return
                    if (root.actionPath === "buttons.gesture") appController.setGestureAction(action,inherit)
                    else if (root.actionPath.indexOf("thumb_wheel") === 0) appController.changeWheel(root.actionPath,action,inherit)
                    else appController.change(root.actionPath,action,inherit)
                    root.pendingAutomation=""
                  }
                  onCanceled:root.drawer=""
                  onTryAction:function(action) { appController.testAction(action,function(ok,data,error) { if (!ok) picker.message=error || (data && data.errors ? data.errors.map(function(item) { return item.message }).join(" · ") : "This action could not run.") }) }
                }
              }
            }
          }
          Item {
            id:smartScroll; anchors.fill:parent; visible:root.page === "smart"
            // SmartActions owns its scroller so the builder footer stays in place.
            property real availableWidth:width
            SmartActions { id:smartActions; anchors.fill:parent; controller:appController; onEditingRequested:function(position) {} ; onAssign:function(id) { root.pendingAutomation=id; root.page="device"; root.deviceTab="buttons"; root.drawer="" } }
          }
          HelpPanel { id:helpPanel; anchors.fill:parent; visible:root.page === "help"; controller:appController; credit:root.deviceImageCredit; changes:root.deviceImageChanges; creditUrl:deviceView.credit.url; license:deviceView.credit.license; licenseUrl:deviceView.credit.licenseUrl; imageModel:appController.device ? String(appController.device.model || "") : ""; silhouette:deviceView.folder === ""; guide:root.serviceGuideUrl; onTour:welcome.open() }
          BackupPanel { anchors.fill:parent; visible:root.page === "backups"; controller:appController; onRestoreRequested:function(name) { root.restoreName=name } }
        }
      }
      ApplicationPicker { id:applications; controller:appController; anchors.fill:parent }
      ProfileManager { id:profileManager; anchors.fill:parent; visible:root.managingProfiles; controller:appController; onDismissed:root.managingProfiles=false }
      ModalSheet { visible:root.restoreName !== ""; sheetWidth:440; sheetHeight:250; onDismissed:root.restoreName=""
        Column { anchors.fill:parent; anchors.margins:24; spacing:16
          Label { text:"Restore this backup?"; font.pixelSize:Style.fontTitle; font.weight:Font.DemiBold }
          Label { width:parent.width; text:"Settings from " + BackupTime.format(root.restoreName) + " will replace your current setup. Your current setup is saved as a new backup first."; color:Theme.muted }
          Row { anchors.right:parent.right; spacing:8
            Button { text:"Cancel"; onClicked:root.restoreName="" }
            Button { text:"Restore"; kind:"primary"; enabled:!appController.applying; onClicked:{ appController.restore(root.restoreName); root.restoreName="" } }
          }
        }
      }
      ModalSheet { visible:root.resettingDefaults; sheetWidth:560; sheetHeight:280; onDismissed:root.resettingDefaults=false
        Column { anchors.fill:parent; anchors.margins:24; spacing:16
          Label { text:"Reset to defaults?"; font.pixelSize:Style.fontTitle; font.weight:Font.DemiBold }
          Label { width:parent.width; text:"This resets button changes, gestures, and app profiles for all mice. Smart Actions are kept. Saved pointer preferences are cleared; the mouse keeps its current speed until you change it. You can Undo this change."; color:Theme.muted }
          Row { anchors.right:parent.right; spacing:8
            Button { text:"Cancel"; onClicked:root.resettingDefaults=false }
            Button { text:"Reset to defaults"; kind:"primary"; enabled:!appController.applying; onClicked:{ appController.restoreDeviceDefaults(); root.resettingDefaults=false } }
          }
        }
      }
      ModalSheet { visible:root.closeDialog; sheetWidth:560; sheetHeight:240; onDismissed:root.keepEditing()
        Column { anchors.fill:parent; anchors.margins:24; spacing:16
          Label { text:"Unsaved changes"; font.pixelSize:Style.fontTitle; font.weight:Font.DemiBold }
          Label { width:parent.width; text:smartActions.draftError || "Save your Smart Action edits before closing Maestro." }
          Row { spacing:8
            Button { text:"Save"; kind:"primary"; enabled:!appController.applying; onClicked:root.requestClose() }
            Button { text:"Discard"; enabled:!appController.applying; onClicked:root.discardAndClose() }
            Button { id:keepEditingButton; text:"Keep editing"; enabled:!appController.applying; onClicked:root.keepEditing() }
          }
        }
      }
      Welcome { id:welcome; anchors.fill:parent; controller:appController
        onFinished:{ root.tourToast="Changes save as you go. Undo is in the top bar."; tourTimer.restart() }
        onChooseStarter:function(id) { let template=(appController.catalog.smart_action_templates || []).find(function(t) { return (t.id || t.name) === id }); if (template) { root.page="smart"; smartActions.create(template.name,template.steps,template.description) } }
      }
      Timer { id:tourTimer; interval:4000; onTriggered:root.tourToast="" }
      Card {
        id:toastCard; enabled:rail.enabled; visible:appController.toast !== "" || root.tourToast !== ""; z:30
        anchors.bottom:parent.bottom; anchors.horizontalCenter:content.horizontalCenter; anchors.bottomMargin:24
        width:Math.min(content.width,toastLabel.implicitWidth+(undoButton.visible ? undoButton.width+16 : 0)+32); height:Math.max(54,toastLabel.implicitHeight+24)
        Row { anchors.fill:parent; anchors.margins:12; spacing:16
          Label { id:toastLabel; width:parent.width-(undoButton.visible ? undoButton.width+16 : 0); text:appController.toast || root.tourToast; anchors.verticalCenter:parent.verticalCenter }
          Button { id:undoButton; text:"Undo"; visible:appController.undoConfig !== null && appController.toast !== ""; enabled:!appController.applying; onClicked:appController.undo() }
        }
      }
    }
  }
  function checkFocus(screen) {
    preview(screen || "buttons")
    let controls=[], failures=[], mouseFailures=[]
    function scan(item) {
      if (item.activeFocusOnTab && item.visible && item.enabled && item.width > 0) controls.push(item)
      const children=item.children || []
      for (let i=0;i<children.length;i++) scan(children[i])
    }
    function hasRing(item) {
      if (item.objectName === "keyboard-focus-ring" && item.visible) return true
      const children=item.children || []
      for (let i=0;i<children.length;i++) if (hasRing(children[i])) return true
      return false
    }
    scan(focusScope)
    for (let i=0;i<controls.length;i++) {
      controls[i].forceActiveFocus(Qt.TabFocusReason)
      if (!hasRing(controls[i])) failures.push(controls[i].toString())
      controls[(i+1)%controls.length].forceActiveFocus(Qt.OtherFocusReason)
      controls[i].forceActiveFocus(Qt.MouseFocusReason)
      if (hasRing(controls[i])) mouseFailures.push(controls[i].toString())
    }
    const dots=deviceView.focusProbe()
    managingProfiles=true
    const sheet=profileManager
    let trapped=true
    for (let i=0;i<8;i++) { sheet.cycle(false); trapped=trapped && sheet.contains(focusScope.Window.window.activeFocusItem) }
    for (let i=0;i<8;i++) { sheet.cycle(true); trapped=trapped && sheet.contains(focusScope.Window.window.activeFocusItem) }
    managingProfiles=false
    focusProbeResult={controls:controls.length,failures:failures,mouseFailures:mouseFailures,order:dots.order,rings:dots.rings,trapped:trapped}
  }
  function testDimension(name,fallback,minimum) {
    if (!Quickshell.env("MAESTRO_CLI") || Quickshell.env("MAESTRO_UI_TEST") !== "1") return fallback
    const value = Number(Quickshell.env(name))
    return isFinite(value) && value > 0 ? Math.max(minimum,value) : fallback
  }
  function createTestAutomation() {
    if (!Quickshell.env("MAESTRO_CLI") || Quickshell.env("MAESTRO_UI_TEST") !== "1") return
    smartActions.create("Test routine",[{type:"delay",ms:250}])
  }
  function stageTestSmartDraft(path,value) {
    if (!Quickshell.env("MAESTRO_CLI") || Quickshell.env("MAESTRO_UI_TEST") !== "1") return
    page = "smart"; smartActions.selectedId = "paste-and-send"
    smartActions.setDraft(path,value)
  }
  function testRepair(operation,value) {
    if (!Quickshell.env("MAESTRO_CLI") || Quickshell.env("MAESTRO_UI_TEST") !== "1") return
    if (operation === "theme-path" && /^\/usr\/share\/omarchy\/themes\/[a-z0-9-]+\/?$/.test(value)) Theme.fixtureThemePath=value
    if (operation === "theme") Theme.colors=Theme.parse(value)
    if (operation === "focus-probe") checkFocus(value)
    if (operation === "welcome-skip") welcome.dismiss()
    if (operation === "welcome-finish") welcome.finish()
    if (operation === "restore-defaults") appController.restoreDeviceDefaults()
    if (operation === "template-category") smartActions.templateCategory = value
    if (operation === "try-routine") { page = "smart"; smartActions.selectedId = "paste-and-send"; smartActions.tryRoutine() }
    if (operation === "device") appController.deviceIndex = Number(value)
    if (operation === "dpi") appController.changeDeviceSetting("dpi",Number(value))
    if (operation === "invert") appController.changeDeviceSetting("invert",value === "true")
    if (operation === "smartshift") appController.changeDeviceSetting("smartshift",JSON.parse(value))
    if (operation === "wheel-mode") appController.changeWheel("thumb_wheel.mode",value,false)
    if (operation === "gesture-single") appController.setGestureAction({type:"key",keys:["CTRL","C"]},false)
    if (operation === "gesture-native") appController.setGestureAction(null,false)
    if (operation === "gesture-media") gestureEditor.choosePreset("media")
    if (operation === "draft-name") stageTestSmartDraft("name",value)
    if (operation === "draft-description") stageTestSmartDraft("description",value)
    if (operation === "draft-delay") stageTestSmartDraft("steps.1.ms",value)
    if (operation === "draft-text") stageTestSmartDraft("steps.3.text",value)
    if (operation === "draft-first-text") stageTestSmartDraft("steps.0.text",value)
    if (operation === "move-step") { const move = JSON.parse(value); smartActions.moveStep(move.index,move.direction) }
    if (operation === "commit-drafts") smartActions.commitPending()
    if (operation === "step-picker-open") { page = "smart"; smartActions.selectedId = "paste-and-send"; smartActions.openStepEditor(-1) }
    if (operation === "step-picker-change") smartActions.stepPicker.choose(JSON.parse(value))
    if (operation === "step-picker-use") { smartActions.stepPicker.selected(smartActions.stepPicker.candidate,false); smartActions.stepPicker.visible = false }
    if (operation === "close") requestClose()
    if (operation === "wm-close") focusScope.Window.window.close()
    if (operation === "keep") keepEditing()
    if (operation === "discard") discardAndClose()
    if (operation.indexOf("record-") === 0) {
      preview("shortcut")
      if (operation === "record-altgr") picker.recordTestKey(Qt.Key_Q,Qt.GroupSwitchModifier,false)
      if (operation === "record-keypad") picker.recordTestKey(Qt.Key_4,Qt.KeypadModifier,false)
      if (operation === "record-backtab") picker.recordTestKey(Qt.Key_Backtab,0,false)
      if (operation === "record-unknown") picker.recordTestKey(Qt.Key_unknown,0,false)
    }
  }
  function capturePreview(path) {
    if (!Quickshell.env("MAESTRO_CLI") || Quickshell.env("MAESTRO_UI_TEST") !== "1" || !/^\/tmp\/maestro-ui-[^/]+\.png$/.test(path)) return
    captureDone = false
    focusScope.grabToImage(function(result) { root.captureDone = result.saveToFile(path) })
  }
  // Accessible only in an explicitly isolated fixture session.
  function preview(screen) {
    if (!Quickshell.env("MAESTRO_CLI") || Quickshell.env("MAESTRO_UI_TEST") !== "1") return
    managingProfiles = false; applications.visible = false; welcome.visible = false; resettingDefaults = false; appController.toast = ""
    page = screen === "smart" || screen === "backups" || screen === "home" ? screen : "device"
    deviceTab = screen === "point" || screen === "point-bottom" ? "point" : "buttons"
    drawer = screen === "gestures" ? "gestures" : screen === "wheel" ? "wheel" : ""
    if (screen === "picker" || screen === "shortcut" || screen === "command") {
      pick("buttons.back")
      if (screen !== "picker") picker.editor = screen
    }
    if (screen === "applications") applications.open()
    if (screen === "profiles" || screen === "profiles-manage") managingProfiles = true
    if (screen === "backups" || screen === "backup-restore") { page="backups"; appController.loadBackups(); restoreName=screen === "backup-restore" ? "2026-10-24T09-30-00" : "" }
    else restoreName=""
    if (screen === "smart") { smartActions.selectedId = ""; smartActions.templateCategory = "All" }
    if (screen === "smart-empty") { page="smart"; smartActions.selectedId=""; smartActions.templateCategory="Unavailable" }
    if (screen === "builder" || screen === "builder-bottom") { page = "smart"; smartActions.selectedId = Object.keys(appController.automations)[0] || "" }
    if (screen === "builder-bottom") smartActions.scrollToBottom()
    else smartActions.scrollToTop()
    pointBar.position = screen === "point-bottom" ? 1-pointBar.size : 0
    if (screen.indexOf("welcome") === 0) page="home"
    if (screen === "welcome") welcome.open()
    if (screen === "welcome-gesture") { welcome.open(); welcome.step = 1 }
    if (screen === "welcome-starter") { welcome.open(); welcome.step = 2 }
    if (screen === "help" || screen === "help-credits" || screen === "help-shortcuts") { page="help"; helpPanel.creditsOpen=screen === "help-credits"; helpPanel.keyboardOpen=screen === "help-shortcuts" }
    if (screen === "step-picker") { page="smart"; smartActions.selectedId="paste-and-send"; smartActions.openStepEditor(-1) }
    if (screen === "defaults") resettingDefaults = true
    focusWindow()
  }
  Connections {
    target: appController
    function onApplyingChanged() { if (!appController.applying && root.closePending && !root.closingSave) Qt.callLater(root.requestClose) }
    function onConfigChanged() { if (root.drawer === "actions") { picker.candidate = appController.effective(root.actionPath,null); picker.currentAction = picker.candidate } }
    function onFieldErrorsChanged() { if (root.drawer === "actions") picker.message = appController.errorsFor(root.actionPath) }
  }
}

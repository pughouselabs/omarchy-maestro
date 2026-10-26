pragma ComponentBehavior: Bound
import QtQuick
import Quickshell
import Quickshell.Io

ShellRoot {
  id:root
  SettingsWindow { id:settings }
  ShortcutRecorder { id:fixtureRecorder; visible:false }
  property bool fixtureKeysOK:false
  IpcHandler {
    target:"maestro"
    function focus():void { settings.focusWindow() }
    function preview(screen:string):void { settings.preview(screen) }
    function capture(path:string):void { settings.capturePreview(path) }
    function fixtureRepair(operation:string,value:string):void { settings.testRepair(operation,value) }
    function fixtureStatus():string {
      if (Quickshell.env("MAESTRO_UI_TEST") !== "1" || !Quickshell.env("MAESTRO_CLI")) return "{}"
      return JSON.stringify({config:settings.controller.config,message:settings.controller.message,errors:settings.controller.fieldErrors,applying:settings.controller.applying,busy:settings.controller.queue.busy,undo:settings.controller.undoConfig !== null,page:settings.page,toast:settings.controller.toast,serviceInactive:settings.controller.serviceInactive,serviceNotice:settings.controller.serviceNotice,serviceHelp:settings.serviceHelpAvailable,servicePath:settings.serviceLauncherPath,battery:settings.controller.batteryLabel(settings.controller.device),wheelAssignment:settings.controller.assignment("thumb_wheel"),builtInWheel:settings.controller.builtInThumbWheel,theme:Theme.background,profiles:settings.controller.profileIndex,devices:settings.controller.devices,keysOK:root.fixtureKeysOK,design:settings.designStatus,metrics:settings.metrics,locations:settings.controller.assignmentLocations("paste-and-send"),captured:settings.captureDone,closeDialog:settings.closeDialog,pendingSmart:settings.pendingSmartEdits,smartDrafts:settings.smartDrafts,recordedKeys:settings.recordedKeys,recordingMessage:settings.recordingMessage,focusRequests:settings.focusRequests,selectedDpi:settings.controller.deviceSetting("dpi",null),writable:settings.controller.writable})
    }
    function fixtureCheck(operation:string):void {
      if (Quickshell.env("MAESTRO_UI_TEST") !== "1" || !Quickshell.env("MAESTRO_CLI")) return
      if (operation === "keys") {
        root.fixtureKeysOK = fixtureRecorder.keyName(Qt.Key_A) === "A"
          && fixtureRecorder.keyName(Qt.Key_9) === "9"
          && fixtureRecorder.keyName(Qt.Key_F1) === "F1"
          && fixtureRecorder.keyName(Qt.Key_F24) === "F24"
          && fixtureRecorder.keyName(Qt.Key_Left) === "LEFT"
          && fixtureRecorder.keyName(Qt.Key_MediaNext) === "NEXTSONG"
          && fixtureRecorder.keyName(Qt.Key_VolumeMute) === "MUTE"
          && settings.controller.sameAction({keys:["CTRL","C"],type:"key"},{type:"key",keys:["CTRL","C"]})
      }
      if (operation === "assign-smart") settings.controller.change("buttons.back",{type:"automation",id:"paste-and-send"})
      if (operation === "save") settings.controller.change("buttons.back",{type:"key",keys:["CTRL","C"]})
      if (operation === "undo") settings.controller.undo()
      if (operation === "invalid") settings.controller.change("buttons.back",{type:"key",keys:["INVALID"]})
      if (operation === "test") settings.controller.testAction({type:"key",keys:["CTRL","C"]})
      if (operation === "restore") settings.controller.restore("2026-10-24T09-30-00")
      if (operation === "backups") settings.controller.loadBackups()
      if (operation === "restore-latest" && settings.controller.backups.length) settings.controller.restore(settings.controller.backups[0].name)
      if (operation === "new-smart") settings.createTestAutomation()
      if (operation === "refresh") settings.controller.refresh()
      if (operation === "profile") settings.controller.profileIndex = 0
      if (operation === "reset-profile") settings.controller.profileIndex = -1

    }
  }
}

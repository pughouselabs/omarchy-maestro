import QtQuick
import Quickshell.Io
import qs.Commons
import qs.Commons as Commons
import qs.Ui as Ui

Ui.BarWidget {
  id: root
  moduleName: "io.github.nodrej.maestro"
  implicitWidth: pill.implicitWidth
  implicitHeight: pill.implicitHeight

  readonly property string executable: decodeURIComponent(Qt.resolvedUrl("bin/maestro").toString().replace(/^file:\/\//, ""))
  property var mouse: null
  property string errorMessage: ""
  property bool busy: false
  readonly property bool opened: panel.opened
  readonly property bool popoutSwitchClosing: panel.popoutSwitchClosing
  readonly property real openPanelIndicatorWidth: pill.implicitWidth

  function open() { panel.open() }
  function close() { panel.close() }
  function closeForPopoutSwitch() { panel.closeForPopoutSwitch() }

  function section(name) {
    var value = mouse ? mouse[name] : null
    return value && !value.error ? value : null
  }

  readonly property var battery: section("battery")
  readonly property bool hasPercent: battery !== null && battery.percent !== null
    && battery.percent !== undefined && isFinite(Number(battery.percent))
  readonly property bool charging: battery !== null && (battery.charging === true
    || battery.status === "charging" || battery.status === "charging slowly")
  readonly property bool lowBattery: hasPercent && Number(battery.percent) <= 15
  // Sentence-case state for labels; empty while simply running on battery.
  readonly property string batteryState: {
    var status = battery && battery.status ? String(battery.status) : ""
    if (status === "charging slowly") return "Charging slowly"
    if (status === "almost full") return "Almost full"
    if (status === "full") return "Fully charged"
    if (charging) return "Charging"
    if (!status || status === "discharging") return lowBattery ? "Battery low" : ""
    return status.charAt(0).toUpperCase() + status.slice(1)
  }
  readonly property string batteryLabel: !battery ? "Battery unavailable"
    : (hasPercent ? "Battery " + Math.round(Number(battery.percent)) + "%" : "Battery level unknown")
      + (batteryState ? " · " + batteryState : "")
  readonly property string modelName: mouse ? String(mouse.model || mouse.name) : "MX Master"

  // The bar creates a widget on every monitor. Elect one queue owner for all
  // copies, and publish each result to the others before starting the next job.
  property bool retiring: false
  function peers() {
    var items = bar ? bar.moduleWidgets(moduleName).filter(function(item) { return item && !item.retiring }) : []
    return items.length ? items : [root]
  }
  function coordinator() { return peers()[0] }
  function publish() {
    var items = peers()
    for (var i = 0; i < items.length; i++) {
      if (items[i] !== root) {
        items[i].mouse = mouse
        items[i].errorMessage = errorMessage
      }
      items[i].busy = activeJob !== null || jobs.length > 0
    }
  }
  function fail(message) {
    errorMessage = String(message).trim().replace(/\s+/g, " ").slice(0, 240)
    errorTimer.restart()
    publish()
  }

  property var jobs: []
  property var activeJob: null
  property string output: ""
  property string errors: ""
  property bool outputDone: false
  property bool errorsDone: false
  property bool exited: false
  property int resultCode: -1
  property bool processStarted: false

  function checkStartFailure() {
    if (!activeJob || command.running || processStarted || exited) return
    errors = "Could not run Maestro: " + executable + " (failed to start)"
    resultCode = -1
    outputDone = true; errorsDone = true; exited = true
    finish()
  }

  function recoverQueue(pending) {
    // An interrupted write may already have reached the mouse. Read back its
    // state instead of replaying it; only requests not yet started transfer.
    jobs = [["status", "--json"]].concat(pending.filter(function(job) { return job[0] !== "status" }))
    if (errorMessage) errorTimer.restart()
    publish()
    recoveryTimer.restart()
  }

  Component.onDestruction: {
    retiring = true
    if (!activeJob && !jobs.length) return
    var survivors = peers().filter(function(item) { return item !== root })
    if (survivors.length) survivors[0].recoverQueue(jobs)
  }

  function refresh() { coordinator().enqueue(["status", "--json"]) }
  function change(args) { coordinator().enqueue(args.concat(["--json"])) }
  function enqueue(args) {
    var read = args[0] === "status"
    if (read && ((activeJob && activeJob[0] === "status")
      || jobs.some(function(job) { return job[0] === "status" }))) return
    jobs = jobs.concat([args])
    startNext()
  }
  function startNext() {
    if (activeJob || !jobs.length) { publish(); return }
    activeJob = jobs[0]
    jobs = jobs.slice(1)
    output = ""; errors = ""; outputDone = false; errorsDone = false
    exited = false; resultCode = -1; processStarted = false
    command.command = [executable].concat(activeJob)
    command.running = true
    publish()
  }
  function finish() {
    // Stream completion and process exit can arrive in either order.
    if (!activeJob || !exited || !outputDone || !errorsDone) return
    var read = activeJob[0] === "status"
    if (resultCode === 0) {
      try {
        var data = JSON.parse(output)
        if (read && !Array.isArray(data)) throw new Error("Expected a mouse list")
        var next = read ? (data.length ? data[0] : null) : data
        if (next && (!next.name || String(next.name).indexOf("MX Master") < 0))
          throw new Error("Unexpected mouse in status")
        if (!read && (!next || Array.isArray(next))) throw new Error("Expected mouse status")
        mouse = next
        var issues = []
        if (mouse) ["battery", "dpi", "smartshift", "wheel"].forEach(function(key) {
          if (mouse[key] && mouse[key].error) issues.push(key + ": " + mouse[key].error)
        })
        if (issues.length) fail(issues.join("; "))
      } catch (e) {
        if (read) mouse = null
        fail("Could not read mouse status: " + e.message)
      }
    } else {
      if (read || resultCode === 2) mouse = null
      fail(errors || "Maestro command failed (exit " + resultCode + ")")
    }
    activeJob = null
    // Always confirm after a write, including unsupported CLI options.
    if (!read) jobs = [["status", "--json"]].concat(jobs.filter(function(job) { return job[0] !== "status" }))
    publish()
    Qt.callLater(startNext)
  }

  Process {
    id: command
    onStarted: root.processStarted = true
    onRunningChanged: if (!running) Qt.callLater(root.checkStartFailure)
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: { root.output = text; root.outputDone = true; root.finish() }
    }
    stderr: StdioCollector {
      waitForEnd: true
      onStreamFinished: { root.errors = text; root.errorsDone = true; root.finish() }
    }
    onExited: function(code) { root.resultCode = code; root.exited = true; root.finish() }
  }
  Timer {
    id: recoveryTimer
    // Start on the next event loop turn, after the old Process is destroyed.
    interval: 1
    onTriggered: root.startNext()
  }
  Timer {
    id: errorTimer
    interval: 8000
    onTriggered: { root.errorMessage = ""; root.publish() }
  }
  Timer {
    interval: 120000
    repeat: true
    running: root.bar !== null
    onTriggered: root.refresh()
  }
  // Wait for the host to inject the bar and register all monitor copies.
  Timer {
    interval: 300
    running: root.bar !== null
    onTriggered: root.refresh()
  }

  Ui.WidgetButton {
    id: pill
    bar: root.bar
    text: "󰍽" + (root.charging ? " 󱐋" : "")
      + (root.mouse && root.hasPercent && root.setting("showPercent", true)
        ? " " + Math.round(Number(root.battery.percent)) + "%" : "")
    dimmed: root.mouse === null
    foreground: root.lowBattery ? Commons.Color.urgent : (root.bar ? root.bar.barForeground : Commons.Color.bar.text)
    tooltipText: root.mouse ? root.modelName + "\n" + root.batteryLabel : "MX Master not connected. Move it to wake it."
    onPressed: function(button) { if (button === Qt.LeftButton) panel.toggle() }
  }

  Panel {
    id: panel
    bar: root.bar
    hostWidget: root
    anchorItem: pill
    settings: root.settings
  }
}

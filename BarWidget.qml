import QtQuick
import QtQuick.Controls as Controls
import "app" as App
import qs.Commons
import qs.Commons as Commons
import qs.Ui as Ui

Ui.BarWidget {
  id: root
  moduleName: "io.github.pughouselabs.maestro"
  implicitWidth: pill.implicitWidth
  implicitHeight: pill.implicitHeight

  readonly property string executable: decodeURIComponent(Qt.resolvedUrl("bin/maestro").toString().replace(/^file:\/\//, ""))
  property var mouse: null
  property string errorMessage: ""
  // Set while another app (Solaar, logiops) owns the mouse and the service waits.
  property string paused: ""
  readonly property string pausedLabel: paused ? "Paused: " + paused + " is running" : ""
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
  readonly property string modelName: mouse ? String(mouse.model || mouse.name) : "MX mouse"

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
        items[i].paused = paused
      }
      items[i].busy = queue.busy
    }
  }
  function fail(message) {
    errorMessage = String(message).trim().replace(/\s+/g, " ").slice(0, 240)
    errorTimer.restart()
    publish()
  }

  function recoverQueue(pending) {
    queue.recover(pending)
    if (errorMessage) errorTimer.restart()
    publish()
  }

  Component.onDestruction: {
    retiring = true
    if (!queue.busy) return
    var survivors = peers().filter(function(item) { return item !== root })
    if (survivors.length) survivors[0].recoverQueue(queue.jobs)
  }

  function refresh() { coordinator().enqueue(queue.statusJob) }
  function change(args) { coordinator().enqueue(args.concat(["--json"])) }
  function enqueue(args) { queue.enqueue(args) }

  App.BarQueue {
    id: queue
    executable: root.executable
    onBusyChanged: root.publish()
    onUpdated: { root.mouse = queue.mouse; root.paused = queue.paused; root.publish() }
    onFailed: function(message) { root.fail(message) }
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
    HoverHandler { id: pillHover }
    Controls.ToolTip {
      id: pillTip
      visible: pillHover.hovered
      delay: 600
      text: (root.paused ? root.pausedLabel : root.mouse ? root.modelName + "\n" + root.batteryLabel : "MX mouse not connected. Move it to wake it.").slice(0,1024)
      contentItem: Text { text: pillTip.text; textFormat: Text.PlainText; color: Commons.Color.popups.text }
    }
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

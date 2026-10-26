pragma ComponentBehavior: Bound
import QtQuick

QtObject {
  id: root
  required property string executable
  property int timeout: 30000
  property var jobs: []
  property var active: null
  property var activeProcess: null
  property var mouse: null
  // Name of another app that owns the mouse while the service waits for it.
  property string paused: ""
  readonly property var statusJob: ["status", "--json", "--with-state"]
  readonly property bool busy: active !== null || jobs.length > 0
  signal updated()
  signal failed(string message)

  function enqueue(args) {
    if (args[0] === "status" && ((active && active[0] === "status")
      || jobs.some(function(job) { return job[0] === "status" }))) return
    jobs = jobs.concat([args]); next()
  }
  function recover(pending) {
    // An interrupted write may already have reached the mouse. Only read it
    // back; transfer requests that had not started, without replaying a write.
    jobs = [statusJob].concat(pending.filter(function(job) { return job[0] !== "status" }))
    launchTimer.restart()
  }
  function next() {
    if (active || !jobs.length) return
    active = jobs[0]; jobs = jobs.slice(1)
    activeProcess = processFactory.createObject(root, {command: [executable].concat(active)})
    activeProcess.running = true
    startGuard.restart(); deadline.restart()
  }
  function finish(worker) {
    if (!active || worker !== activeProcess) return
    deadline.stop(); startGuard.stop()
    let read = active[0] === "status"
    if (!worker.failure && worker.code === 0) {
      try {
        let data = JSON.parse(worker.output)
        if (read && data && !Array.isArray(data) && Array.isArray(data.devices)) {
          paused = typeof data.paused_by === "string" ? data.paused_by.slice(0, 64) : ""
          data = data.devices
        } else if (read) paused = ""
        if (read && !Array.isArray(data)) throw new Error("Expected a mouse list")
        // Default CLI writes select the first supported device in status order.
        let nextMouse = read ? data.find(function(item) { return item && item.supported === true }) || null : data
        if (!read && (!nextMouse || Array.isArray(nextMouse) || nextMouse.supported !== true))
          throw new Error("Expected supported mouse status")
        mouse = nextMouse
        let issues = []
        if (mouse) ["battery", "dpi", "smartshift", "wheel"].forEach(function(key) {
          if (mouse[key] && mouse[key].error) issues.push(key + ": " + mouse[key].error)
        })
        if (issues.length) failed(issues.join("; "))
      } catch (error) {
        if (read) mouse = null
        failed("Could not read mouse status: " + error.message)
      }
    } else {
      if (read || worker.code === 2) mouse = null
      failed(worker.failure || worker.errors || "Maestro command failed (exit " + worker.code + ")")
    }
    active = null; activeProcess = null; worker.destroy()
    if (!read) jobs = [statusJob].concat(jobs.filter(function(job) { return job[0] !== "status" }))
    updated(); launchTimer.restart()
  }
  property Component processFactory: Component {
    BoundedProcess { id: worker; onCompleted: root.finish(worker) }
  }
  property Timer launchTimer: Timer { interval: 1; onTriggered: root.next() }
  property Timer startGuard: Timer {
    interval: 250
    onTriggered: {
      let worker = root.activeProcess
      if (worker && !worker.started && !worker.running) worker.abort("Could not start Maestro. Check that it is installed.")
    }
  }
  property Timer deadline: Timer {
    interval: root.timeout
    onTriggered: if (root.activeProcess) root.activeProcess.abort("Maestro took too long. Try again.")
  }
}

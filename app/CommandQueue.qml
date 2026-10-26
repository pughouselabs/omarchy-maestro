pragma ComponentBehavior: Bound
import QtQuick
import Quickshell
import Quickshell.Io

QtObject {
  id: root
  // Quickshell blocks Qt.resolvedUrl() paths outside its config directory.
  readonly property string repoPath:Quickshell.shellDir.replace(/\/+$/,"").replace(/\/[^/]+$/,"")
  readonly property string executable: Quickshell.env("MAESTRO_CLI") || repoPath + "/bin/maestro"
  property var jobs: []
  property var active: null
  property var activeProcess: null
  readonly property bool busy: active !== null || jobs.length > 0

  function request(args, input, callback) {
    jobs = jobs.concat([{args:args,input:input,callback:callback}]); launchTimer.restart()
  }
  function next() {
    if (active || !jobs.length) return
    active = jobs[0]; jobs = jobs.slice(1)
    // Give each job its own stream collectors. Late events from the previous
    // Process cannot complete, reset, or swallow the next request.
    activeProcess = processFactory.createObject(root,{command:[executable].concat(active.args),stdinEnabled:active.input !== undefined})
    activeProcess.running = true
    startGuard.restart()
    deadline.interval = active.args[0] === "test-action" ? 120000 : 30000
    deadline.restart()
  }
  function finish(worker) {
    if (!active || worker !== activeProcess || !worker.exited || !worker.outputDone || !worker.errorsDone) return
    deadline.stop(); startGuard.stop()
    let job = active, data = null, message = ""
    try { data = JSON.parse(worker.output) } catch (error) { message = "Maestro returned an unreadable response." }
    if (worker.timedOut) message = "Maestro took too long. Try again."
    else if (worker.code !== 0 && !data) message = worker.errors.trim().slice(0,240) || "Maestro could not complete this request."
    if (data && data.ok === false && !data.errors) message = data.message || data.error || "Maestro could not complete this request."
    let ok = worker.code === 0 && data !== null && data.ok !== false && !message
    active = null; activeProcess = null
    worker.destroy()
    try { job.callback(ok,data,message) } catch (error) { console.warn("Maestro response: " + error.message) }
    launchTimer.restart()
  }
  property Component processFactory: Component {
    Process {
      id: worker
      property string output: ""
      property string errors: ""
      property bool outputDone:false
      property bool errorsDone:false
      property bool exited:false
      property int code:-1
      property bool started:false
      property bool timedOut:false
      onStarted: {
        started = true
        if (root.active && root.active.input !== undefined) {
          write(JSON.stringify(root.active.input) + "\n")
          // Flush queued data, then close stdin so the engine can read to EOF.
          stdinEnabled = false
        }
      }
      onExited:function(exitCode) { code = exitCode; exited = true; root.finish(worker) }
      stdout:StdioCollector { waitForEnd:true; onStreamFinished:{ worker.output = text; worker.outputDone = true; root.finish(worker) } }
      stderr:StdioCollector { waitForEnd:true; onStreamFinished:{ worker.errors = text; worker.errorsDone = true; root.finish(worker) } }
    }
  }
  property Timer launchTimer:Timer { interval:1; onTriggered:root.next() }
  property Timer startGuard:Timer {
    interval:250
    onTriggered: {
      let worker = root.activeProcess
      if (!worker || worker.started || worker.running) return
      worker.errors = "Could not start Maestro. Check that it is installed."
      worker.outputDone = true; worker.errorsDone = true; worker.exited = true; worker.code = -1
      root.finish(worker)
    }
  }
  property Timer deadline:Timer {
    onTriggered: {
      let worker = root.activeProcess
      if (!worker) return
      worker.timedOut = true
      if (worker.running) worker.signal(9)
      else {
        worker.code = -1; worker.exited = true; worker.outputDone = true; worker.errorsDone = true
        root.finish(worker)
      }
    }
  }
}

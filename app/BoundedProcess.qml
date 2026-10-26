pragma ComponentBehavior: Bound
import QtQuick
import Quickshell.Io

Process {
  id: worker
  // IPC is at most 64 KiB, encoded as ASCII JSON. Inspect each arriving chunk
  // instead of waiting for EOF. Detach collectors immediately on overflow so
  // a child cannot keep growing their buffers while it is being terminated.
  property int outputLimit: 65536
  property string output: ""
  property string errors: ""
  property string failure: ""
  property bool outputDone: false
  property bool errorsDone: false
  property bool exited: false
  property int code: -1
  property bool started: false
  signal completed()
  function finish() { if (exited && outputDone && errorsDone) completed() }
  function abort(message) {
    if (failure) return
    failure = message
    stdout = null; stderr = null
    output = ""; errors = ""
    outputDone = true; errorsDone = true
    if (running) signal(9)
    else { exited = true; code = -1; finish() }
  }
  onStarted: started = true
  onExited: function(exitCode) { code = exitCode; exited = true; finish() }
  stdout: StdioCollector {
    waitForEnd: false
    onDataChanged: if (text.length > worker.outputLimit) worker.abort("Maestro output exceeded 65536 characters.")
    onStreamFinished: {
      if (!worker.failure) worker.output = text
      worker.outputDone = true; worker.finish()
    }
  }
  stderr: StdioCollector {
    waitForEnd: false
    onDataChanged: if (text.length > worker.outputLimit) worker.abort("Maestro error output exceeded 65536 characters.")
    onStreamFinished: {
      if (!worker.failure) worker.errors = text
      worker.errorsDone = true; worker.finish()
    }
  }
}

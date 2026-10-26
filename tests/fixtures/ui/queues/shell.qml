pragma ComponentBehavior: Bound
import QtQuick
import Quickshell
import "./app" as App

ShellRoot {
  id: test
  property var failures: []
  property var starts: []
  property var pendingCondition: null
  property var pendingCallback: null
  property real due: 0
  property var families: ["MX Master", "MX Master 2S", "MX Master 3", "MX Master 3S", "MX Master 4",
    "MX Anywhere 2", "MX Anywhere 2S", "MX Anywhere 3", "MX Anywhere 3S", "MX Vertical", "MX Ergo", "MX Ergo S", "Reported product name"]
  property App.BarQueue queue: App.BarQueue {
    executable: Quickshell.env("MAESTRO_QUEUE_CLI")
    timeout: 500
    onFailed: function(message) { test.failures.push(message) }
    onActiveChanged: if (active) test.starts.push(active[0])
  }
  property App.BoundedProcess worker: App.BoundedProcess {}
  property App.CommandQueue settingsQueue: App.CommandQueue {}
  property App.Button button: App.Button { tooltipText: "<b>literal command</b>" }
  property App.AppState controller: App.AppState {
    config: ({automations:{example:{name:"Example",description:"Example routine",steps:[{type:"delay",ms:50},{type:"command",argv:["missing-program"]}]}}})
  }
  property App.SmartActions actions: App.SmartActions { controller: test.controller; selectedId: "example" }
  function check(value, message) { if (!value) throw new Error(message) }
  function equal(actual, expected) { check(JSON.stringify(actual) === JSON.stringify(expected), JSON.stringify(actual) + " != " + JSON.stringify(expected)) }
  function waitFor(condition, callback) {
    pendingCondition = condition; pendingCallback = callback; due = Date.now() + 5000
  }
  function idle(callback) { waitFor(function() { return !queue.busy }, callback) }
  function reset() { failures = []; starts = [] }
  function family() {
    if (!families.length) { unsupported(); return }
    let name = families.shift()
    queue.enqueue(["status", "--json", JSON.stringify([{supported:false,name:"keyboard"}, {supported:true,model:name,name:name}, {supported:true,name:"second mouse"}])])
    idle(function() { equal(queue.mouse.name,name); equal(failures,[]); family() })
  }
  function unsupported() {
    queue.enqueue(["status", "--json", '[{"supported":false,"name":"MX Master"}]'])
    idle(function() { equal(queue.mouse,null); paused() })
  }
  function paused() {
    // Another app owns the mouse: a paused state, not an error.
    reset()
    queue.enqueue(["status", "--json", "--with-state", '{"devices":[],"paused_by":"Solaar","problem":"Solaar is running and controls the mouse. Close Solaar to use Maestro."}'])
    idle(function() {
      equal(queue.mouse,null); equal(queue.paused,"Solaar"); equal(failures,[])
      queue.enqueue(queue.statusJob)
      idle(function() { equal(queue.paused,""); equal(queue.mouse.name,"MX Anywhere 3"); watchdog() })
    })
  }
  function watchdog() {
    reset(); queue.enqueue(["hang-write"]); queue.enqueue(["pending-write"])
    idle(function() {
      equal(starts,["hang-write","status","pending-write","status"])
      equal(failures.length,1); check(failures[0].includes("too long"),"watchdog failure")
      equal(queue.mouse.name,"MX Anywhere 3"); overflow("overflow-write")
    })
  }
  function overflow(operation) {
    reset(); queue.enqueue([operation])
    idle(function() {
      equal(starts,[operation,"status"]); equal(failures.length,1)
      check(failures[0].includes("exceeded"),"output budget failure: " + failures[0])
      equal(queue.mouse.name,"MX Anywhere 3")
      if (operation === "overflow-write") overflow("stderr-write")
      else fragmented()
    })
  }
  function fragmented() {
    worker.command = ["python3", "-c", "import sys,time; sys.stdout.write('{'); sys.stdout.flush(); time.sleep(.02); print('}'); print('note',file=sys.stderr)"]
    worker.running = true
    waitFor(function() { return worker.exited && worker.outputDone && worker.errorsDone }, function() {
      equal(worker.code,0); equal(worker.output.trim(),"{}"); equal(worker.errors.trim(),"note")
      settingsOverflow()
    })
  }
  function settingsOverflow() {
    settingsQueue.request(["overflow-write"],undefined,function(ok,data,message) {
      check(!ok && message.includes("exceeded"),"settings output limit")
      settingsQueue.request(["status","--json"],undefined,function(ok,data,message) {
        check(ok && data[0].supported,"settings queue continuation")
        presentation()
      })
    })
  }
  function find(object, name) {
    if (object.objectName === name) return object
    for (let child of object.children || []) { let result = find(child,name); if (result) return result }
    for (let child of object.data || []) { if (child.objectName === name) return child }
    return null
  }
  function presentation() {
    let tooltip = find(button,"maestro-tooltip")
    check(tooltip !== null,"tooltip found")
    equal(tooltip.contentItem.textFormat,Text.PlainText)
    equal(tooltip.contentItem.text,"<b>literal command</b>")
    button.tooltipText = "x".repeat(2000)
    equal(tooltip.contentItem.text.length,1024)
    // Acknowledgment means only that the daemon accepted the delayed routine.
    actions.tryRoutine()
    waitFor(function() { return actions.trySucceeded },function() {
      equal(find(actions,"try-action").text,"Started")
      missing()
    })
  }
  function missing() {
    reset(); queue.executable = "/no-such-maestro-test-executable"
    queue.enqueue(["status", "--json"])
    idle(function() {
      equal(failures.length,1); check(failures[0].includes("Could not start"),"start failure")
      console.log("PASS: bounded queues: all MX families, paused state, ordering, watchdog, readback, no replay, stdout/stderr limits, fragmented output, missing executable")
      Qt.quit()
    })
  }
  property Timer poll: Timer {
    interval: 10; repeat: true; running: true
    onTriggered: {
      if (!test.pendingCondition) return
      try {
        test.check(Date.now() < test.due,"test deadline expired")
        if (!test.pendingCondition()) return
        let callback = test.pendingCallback
        test.pendingCondition = null; test.pendingCallback = null
        callback()
      } catch (error) { console.error("FAIL: " + error.message); Qt.quit() }
    }
  }
  property Timer overallTimer: Timer {
    interval: 15000; running: true
    onTriggered: { console.error("FAIL: queue test did not finish"); Qt.quit() }
  }
  Component.onCompleted: family()
}

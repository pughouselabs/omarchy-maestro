pragma ComponentBehavior: Bound
import QtQuick
import Quickshell
import Quickshell.Io

QtObject {
  id: root
  property CommandQueue queue: CommandQueue {}
  readonly property bool fixtureMode:Quickshell.env("MAESTRO_UI_TEST") === "1" && !!Quickshell.env("MAESTRO_CLI")
  property var fixtureApplications:[]
  readonly property var applicationEntries:fixtureMode ? fixtureApplications : DesktopEntries.applications.values
  property FileView applicationFixture:FileView {
    path:root.fixtureMode ? root.queue.repoPath + "/tests/fixtures/ui/applications.json" : ""
    preload:root.fixtureMode; printErrors:false
    onLoaded: { try { root.fixtureApplications=JSON.parse(text()) } catch(error) { root.fixtureApplications=[] } }
  }
  property string versionString:"0.3.2"
  property FileView versionFile:FileView {
    path:root.queue.repoPath + "/pyproject.toml"; preload:true; printErrors:false
    onLoaded: { const match=text().match(/^version\s*=\s*"([^"]+)"/m); if (match) root.versionString=match[1] }
  }
  property var config: ({})
  property var catalog: ({groups:[]})
  property var devices: []
  property var backups: []
  property var fieldErrors: []
  property var undoConfig: null
  property bool configLoaded: false
  property bool applying: false
  property bool loading: false
  property string message: ""
  property string toast: ""
  property bool serviceInactive:false
  property int deviceIndex: 0
  property int profileIndex: -1
  readonly property var device: deviceIndex >= 0 && devices.length > deviceIndex ? devices[deviceIndex] : null
  readonly property var profiles: config.profiles || []
  readonly property var automations: config.automations || ({})
  // A mouse's controls stay unavailable until its resolved options load.
  readonly property bool writable: configLoaded && device !== null && device.writable === true && device.options !== undefined && !applying
  readonly property bool builtInThumbWheel:device !== null && !available("thumb_wheel") && device.thumb_wheel !== undefined && String(device.model || "").indexOf("MX Master") === 0
  readonly property string serviceNotice:"Changes are saved, but won't take effect until the Maestro service starts."

  function batteryLabel(item) {
    const battery = item && item.battery
    if (!battery || typeof battery.percent !== "number") return "Battery unavailable"
    return battery.percent + " %" + (battery.charging ? " · Charging" : battery.status === "full" ? " · Fully charged" : "")
  }

  function sameAction(left,right) {
    if (left === right) return true
    if (!left || !right || typeof left !== "object" || typeof right !== "object" || Array.isArray(left) !== Array.isArray(right)) return false
    let keys = Object.keys(left)
    return keys.length === Object.keys(right).length && keys.every(function(key) {
      return Object.prototype.hasOwnProperty.call(right,key) && sameAction(left[key],right[key])
    })
  }
  function copy(value) { return JSON.parse(JSON.stringify(value)) }
  function read(object, path) {
    let parts = path.split("."), value = object
    for (let i = 0; i < parts.length; i++) {
      if (value === null || value === undefined || !Object.prototype.hasOwnProperty.call(value, parts[i])) return undefined
      value = value[parts[i]]
    }
    return value
  }
  function write(object, path, value, remove) {
    let parts = path.split("."), target = object
    for (let i = 0; i < parts.length - 1; i++) {
      if (!target[parts[i]] || typeof target[parts[i]] !== "object") target[parts[i]] = {}
      target = target[parts[i]]
    }
    if (remove) delete target[parts[parts.length - 1]]
    else target[parts[parts.length - 1]] = value
  }
  function scope(configObject) { return profileIndex >= 0 ? (configObject.profiles || [])[profileIndex] || {} : configObject }
  function local(path) { return read(scope(config), path) }
  function effective(path, fallback) {
    let value = profileIndex >= 0 ? local(path) : undefined
    if (value === undefined && device) value = read(device.options || {},path)
    if (value === undefined) value = read(config, path)
    return value === undefined ? fallback : value
  }
  function deviceSetting(path,fallback) {
    const value = device ? read((device.options || {}).settings || {},path) : undefined
    return value === undefined ? fallback : value
  }
  function deviceRuleIndex(object) {
    const entries = object.devices || [], identity = device && device.identity
    if (!identity || !identity.name || !Number.isInteger(identity.index)) return -1
    for (let i = entries.length - 1; i >= 0; i--) if (sameAction(entries[i].match,identity)) return i
    return -1
  }
  function changeDeviceOption(path,value,inherit) {
    if (!writable) return
    if (!device.identity || !device.identity.name || !Number.isInteger(device.identity.index)) {
      message = "Refresh to identify this mouse before changing its settings."; return
    }
    let next = copy(config); next.devices = next.devices || []
    let index = deviceRuleIndex(next)
    // Match the IPC writer: a precise final rule wins later wildcard/path rules.
    if (index !== next.devices.length - 1 || index < 0) {
      next.devices.push({match:copy(device.identity)}); index = next.devices.length - 1
    }
    write(next.devices[index],path,value,inherit || false)
    if (!sameAction(next,config)) apply(next,false)
  }
  function changeDeviceSetting(path,value) { changeDeviceOption("settings." + path,value,false) }
  function changeWheel(path,value,inherit) {
    if (profileIndex >= 0) change(path,value,inherit)
    else changeDeviceOption(path,value,inherit)
  }
  function deviceErrors(path) {
    return errorsFor("devices[" + deviceRuleIndex(config) + "].settings." + path,true)
  }
  function wheelErrors(path) {
    return profileIndex >= 0 ? errorsFor(path) : errorsFor("devices[" + deviceRuleIndex(config) + "]." + path,true)
  }
  function updateDevices(items) {
    const identity = device && device.identity, next = visibleDevices(items)
    const position = identity ? next.findIndex(function(item) { return sameAction(item.identity,identity) }) : 0
    devices = next; deviceIndex = next.length ? position : -1
    loadDeviceOptions()
  }
  // The device list leaves out each mouse's resolved options so it stays
  // within the 64 KiB response limit with several mice. Read them for one
  // mouse at a time; each of those responses fits the configuration budget.
  // A reply only counts for the mouse it was requested for; a list that
  // changed in the meantime keeps its own entries.
  function mergeOptions(items, number, fresh) {
    const at = items.findIndex(function(item) {
      return item.device === number && sameAction(item.identity,fresh.identity) && sameAction(item.selector,fresh.selector)
    })
    if (at < 0) return null
    const next = items.slice(); next[at] = fresh
    return next
  }
  function withOptions(number, callback) {
    queue.request(["controls","--mouse",String(number),"--json"],undefined,function(ok,data,error) {
      const fresh = ok && data && Array.isArray(data.devices) && data.devices.length === 1 && data.devices[0].options !== undefined ? data.devices[0] : null
      callback(fresh,error)
    })
  }
  // Calls back with (ok, data, error, optionsFailed). A mouse whose options
  // could not be read stays in the list without options, so its controls stay
  // unavailable, and optionsFailed tells the caller not to report success.
  function loadControls(callback) {
    queue.request(["controls","--json"],undefined,function(ok,data,error) {
      if (!ok || !data || !Array.isArray(data.devices)) { callback(false,data,error,false); return }
      const numbers = visibleDevices(data.devices).map(function(item) { return item.device }).filter(Number.isInteger)
      let failure = ""
      function step(items, at) {
        if (at >= numbers.length) { callback(true,Object.assign({},data,{devices:items}),failure,failure !== ""); return }
        root.withOptions(numbers[at],function(fresh,detail) {
          const next = fresh ? root.mergeOptions(items,numbers[at],fresh) : null
          if (!next && !failure) failure = detail || "This mouse's settings could not be read. Try Refresh."
          step(next || items,at + 1)
        })
      }
      step(data.devices,0)
    })
  }
  function loadDeviceOptions() {
    const item = device
    if (!item || item.options !== undefined || !Number.isInteger(item.device)) return
    withOptions(item.device,function(fresh) {
      if (!fresh) { if (!message) message = "This mouse's settings could not be read. Try Refresh."; return }
      // Ignore a reply for a mouse that is no longer in the current list.
      const next = root.mergeOptions(devices,item.device,fresh)
      if (next) devices = next
    })
  }
  onDeviceIndexChanged: loadDeviceOptions()
  function releaseButtons() {
    if (!device || applying) return
    const number = device.device
    // The selector names this exact mouse, so a changed list is refused
    // before anything is written instead of releasing another mouse.
    if (!Number.isInteger(number) || !device.selector) { message = "Refresh to identify this mouse before releasing its buttons."; return }
    applying = true; message = ""
    queue.request(["release-buttons","--mouse",String(number),"--selector",JSON.stringify(device.selector),"--json"],undefined,function(ok,data,error) {
      applying = false
      if (ok && data.ok === true) {
        const released = (data.devices || []).reduce(function(all,item) { return all.concat(item.released || []) },[])
        toast = released.length ? "Released the " + released.join(", ") : "Nothing needed releasing"
        toastTimer.restart()
      } else report(data,error || "The button could not be released. Turn the mouse off and on.")
      root.refresh()
    })
  }
  function setGestureMode(bundle) {
    // A profile cannot erase a mapping inherited from All applications.
    // Null means native, so it must never be used as an inheritance marker.
    const baseButtons = device ? read(device.options || {},"buttons") : config.buttons
    if (profileIndex >= 0 && baseButtons && Object.prototype.hasOwnProperty.call(baseButtons,"gesture")) {
      message = "Choose Gestures in All applications first, then customize this application's gestures."; return false
    }
    let next = copy(config), target = scope(next)
    target.gesture = copy(effective("gesture",{}))
    Object.keys(bundle || {}).forEach(function(direction) { target.gesture[direction] = bundle[direction] })
    target.gesture.enabled = true
    if (!target.buttons) target.buttons = {}
    delete target.buttons.gesture
    apply(next,false)
    return true
  }
  function setGestureAction(action,inherit) {
    let next = copy(config), target = scope(next)
    write(target,"gesture.enabled",false,inherit)
    write(target,"buttons.gesture",action,inherit)
    apply(next,false)
  }
  function inherited(path) { return profileIndex >= 0 && local(path) === undefined }
  function fullPath(path) { return (profileIndex >= 0 ? "profiles[" + profileIndex + "]." : "") + path }
  function errorsFor(path, global) {
    let prefix = global ? path : fullPath(path)
    return fieldErrors.filter(function(error) {
      let at = String(error.path || "").replace(/^config\./, "")
      return at === prefix || at.indexOf(prefix + ".") === 0 || at.indexOf(prefix + "[") === 0
    }).map(function(error) { return error.message }).join(" · ")
  }
  function warningText(value) {
    if (!value) return ""
    let items = Array.isArray(value) ? value : [value]
    return items.map(function(item) { return typeof item === "string" ? item : item.message || item.error || "A device could not update yet" }).join(" · ")
  }
  function savedMessage(data,label) {
    let result = label
    if (typeof data.reloaded === "boolean") serviceInactive = !data.reloaded
    const warnings = [warningText(data.warnings),warningText(data.device_errors),warningText(data.errors)].filter(function(item) { return item !== "" }).join(" · ")
    return result + (warnings ? " · " + warnings : "")
  }
  function report(data, fallback) {
    fieldErrors = data && Array.isArray(data.errors) ? data.errors : []
    message = fallback || (fieldErrors.length ? "This change could not be saved. Check the highlighted setting." : "Maestro could not complete this request.")
  }
  function refresh() {
    if (applying || loading) return
    loading = true; message = ""
    loadControls(function(ok, data, error, optionsFailed) {
      if (ok && Array.isArray(data.devices)) {
        updateDevices(data.devices)
        serviceInactive = data.daemon === false
        const problems = data.devices.map(function(item) { return item && item.problem ? item.problem : "" }).filter(function(item) { return item !== "" })
        // The service is paused while another app (Solaar, logiops) owns the mouse.
        if (typeof data.problem === "string" && data.problem) problems.unshift(data.problem)
        if (optionsFailed) problems.push("This mouse's settings could not be read. Try Refresh.")
        if (problems.length) message = problems.join(" · ")
      }
      else { devices = []; message = error || warningText(data && data.errors) || "Mouse controls are unavailable. Wake the mouse and try Refresh." }
      if (deviceIndex >= devices.length) deviceIndex = 0
    })
    queue.request(["catalog", "--json"], undefined, function(ok, data, error) {
      if (ok && Array.isArray(data.groups)) catalog = data
      else message = error || warningText(data && data.errors) || "The action list could not be loaded. Try Refresh."
    })
    queue.request(["config", "get"], undefined, function(ok, data, error) {
      loading = false
      if (ok && typeof data === "object" && !Array.isArray(data) && data.version === 1) {
        config = data; configLoaded = true; fieldErrors = []; undoConfig = null
        if (profileIndex >= profiles.length) profileIndex = -1
      } else { configLoaded = false; report(data, error || "Settings could not be loaded. Try Refresh.") }
    })
  }
  function apply(next, undoing, callback) {
    if (!configLoaded || applying) { if (callback) callback(false); return }
    let previous = copy(config)
    applying = true; fieldErrors = []; message = ""; toast = ""
    config = copy(next)
    queue.request(["config", "apply", "--stdin"], next, function(ok, data, error) {
      if (ok && data.ok === true) {
        root.readSaved(data,undoing ? "Change undone" : "Saved",undoing ? null : previous,callback)
      } else {
        applying = false; config = previous
        if (profileIndex >= profiles.length) profileIndex = -1
        report(data, error); if (callback) callback(false)
      }
    })
  }
  function change(path, value, inherit, global) {
    if (!configLoaded || applying) return
    let next = copy(config)
    write(global ? next : scope(next), path, value, inherit || false)
    if (sameAction(config,next)) { fieldErrors = []; message = ""; return }
    apply(next, false)
  }
  function undo() {
    if (!undoConfig || applying) return
    applying = true; fieldErrors = []; message = ""; toast = ""
    queue.request(["config","undo"],undefined,function(ok,data,error) {
      if (ok && data.ok === true) root.readSaved(data,"Change undone",null)
      else { applying = false; report(data,error) }
    })
  }
  function readSaved(result,label,previous,callback) {
    queue.request(["config","get"],undefined,function(ok,data,error) {
      if (ok && data.version === 1) {
        config = data; undoConfig = previous; fieldErrors = []
        if (profileIndex >= profiles.length) profileIndex = -1
        root.loadControls(function(loaded,controls,failure,optionsFailed) {
          applying = false
          if (loaded && !optionsFailed && Array.isArray(controls.devices)) {
            updateDevices(controls.devices)
            toast = savedMessage(result,label); toastTimer.restart()
          } else if (loaded && Array.isArray(controls.devices)) {
            // The change was saved, but a mouse's options could not be read
            // back: keep that mouse's controls unavailable and say so.
            updateDevices(controls.devices)
            report(null,"Saved, but this mouse's settings could not be read. Try Refresh.")
          } else {
            configLoaded = false
            report(controls,failure || "Saved, but this mouse's settings could not be read. Try Refresh.")
          }
          if (callback) callback(loaded && !optionsFailed && configLoaded)
        })
      } else {
        applying = false; configLoaded = false; undoConfig = null
        report(data,error || "The saved settings could not be read. Try Refresh.")
        if (callback) callback(false)
      }
    })
  }
  function available(name) {
    if (!device) return false
    if (name === "thumb_wheel") return device.thumb_wheel && device.thumb_wheel.available === true
    return (device.buttons || []).some(function(button) { return button.name === name && button.available === true })
  }
  function describe(action) {
    if (action === undefined || action === null) return "Default"
    if (action.type === "key") return action.keys.join(" + ")
    if (action.type === "none") return "Do nothing"
    if (action.type === "automation") return automations[action.id] ? automations[action.id].name : "Missing Smart Action"
    if (action.type === "sequence") return "Smart Action · " + action.steps.length + " steps"
    if (action.type === "command") return action.argv.join(" ")
    if (action.type === "text") return "Type: " + action.text
    if (action.type === "delay") return "Wait " + action.ms + " ms"
    let result = ""
    ;(catalog.groups || []).some(function(group) {
      return group.actions.some(function(item) {
        if (sameAction(item.action,action)) { result = item.label; return true }
        return false
      })
    })
    if (!result && action.type === "desktop") result = {apps:"Application launcher",menu:"Omarchy menu",app_switcher:"Switch applications",fullscreen:"Full screen",workspace_previous:"Previous workspace",workspace_next:"Next workspace"}[action.action] || ""
    return result || (action.type === "mouse" ? action.button.charAt(0).toUpperCase() + action.button.slice(1) + " click" : (action.action || action.dispatcher || action.type).replace(/_/g," "))
  }
  function isFixtureDevice(item) {
    return item.fixture === true || item.test_only === true || item.fixture_only === true || /\(fixture\)/i.test(String(item.model || ""))
  }
  function visibleDevices(items) {
    const testMode = Quickshell.env("MAESTRO_UI_TEST") === "1"
    return items.filter(function(item) { return testMode || !isFixtureDevice(item) })
  }
  function connectionLabel(item) {
    if (!item) return ""
    const connection = item.connection || item.transport || ""
    const value = typeof connection === "object" ? connection.type || connection.name || "" : String(connection)
    const names = {unifying:"Unifying receiver",bolt:"Bolt receiver",bluetooth:"Bluetooth",usb:"USB receiver"}
    return names[value.toLowerCase()] || value
  }
  function assignment(name) {
    if (name === "thumb_wheel") {
      if (builtInThumbWheel) return "Horizontal scroll"
      const mode = effective("thumb_wheel.mode","horizontal")
      return {horizontal:"Default",volume:"Volume",zoom:"Zoom",tabs:"Browser tabs",workspaces:"Workspaces",custom:"Custom actions"}[mode] || mode
    }
    if (name === "gesture" && effective("gesture.enabled",true) && effective("buttons.gesture",undefined) === undefined) return "Gestures"
    const action = effective("buttons." + name,null)
    return action === null || (action.type === "mouse" && action.button === name) ? "Default" : describe(action)
  }
  function controlOverridden(name) {
    if (profileIndex < 0) return false
    if (name === "thumb_wheel") return local("thumb_wheel") !== undefined && Object.keys(local("thumb_wheel")).length > 0
    if (name === "gesture" && assignment(name) === "Gestures") return local("gesture") !== undefined && Object.keys(local("gesture")).length > 0
    return local("buttons." + name) !== undefined
  }
  function assignmentLocations(id) {
    const results = [], names = {gesture:"Gesture button",back:"Back",forward:"Forward",middle:"Middle click",mode_shift:"Wheel mode"}
    function collect(options,prefix) {
      Object.keys(options.buttons || {}).forEach(function(name) {
        const action = options.buttons[name]
        if (action && action.type === "automation" && action.id === id) results.push(prefix + (names[name] || name))
      })
      ;["tap","up","down","left","right"].forEach(function(direction) {
        const action = (options.gesture || {})[direction]
        if (action && action.type === "automation" && action.id === id) results.push(prefix + "Gesture " + direction)
      })
      ;["left","right"].forEach(function(direction) {
        const action = (options.thumb_wheel || {})[direction]
        if (action && action.type === "automation" && action.id === id) results.push(prefix + "Thumb wheel " + direction)
      })
    }
    collect(config,"")
    profiles.forEach(function(profile) { collect(profile,(profile.name || profile.match.class) + " · ") })
    return results
  }
  function testAction(action, callback) {
    if (applying) return
    queue.request(["test-action", "--stdin"], action, function(ok, data, error) {
      if (ok) { toast = "Action sent"; toastTimer.restart() }
      else report(data, error || "This action could not run.")
      if (callback) callback(ok, data, error)
    })
  }
  function loadBackups() {
    queue.request(["config", "backups", "--json"], undefined, function(ok, data, error) {
      if (ok && Array.isArray(data.backups)) backups = data.backups
      else report(data, error || "Backups could not be loaded.")
    })
  }
  function restoreDeviceDefaults() {
    if (!writable) return
    if (!catalog.defaults || catalog.defaults.version !== 1) { message = "Refresh to load the default setup."; return }
    const next = copy(catalog.defaults)
    next.automations = copy(automations)
    profileIndex = -1
    apply(next,false)
  }
  function restore(name) {
    if (applying) return
    let previous = copy(config)
    applying = true; message = ""; fieldErrors = []; toast = ""
    queue.request(["config", "restore", name], undefined, function(ok, data, error) {
      if (ok && data.ok === true) {
        profileIndex = -1
        root.readSaved(data,"Backup restored",previous)
      } else { applying = false; report(data, error) }
    })
  }
  function profileIcon(profile) {
    let entries = applicationEntries, match = String((profile.match || {}).class || "").toLowerCase()
    for (let i = 0; i < entries.length; i++) {
      if ((entries[i].startupClass || "").toLowerCase() === match || entries[i].id.toLowerCase().replace(/\.desktop$/,"") === match) return entries[i].icon
    }
    return "application-x-executable"
  }
  function profileOptions() {
    return [{value:"-1", label:"All applications"}].concat(profiles.map(function(profile, index) {
      return {value:String(index), label:profile.name || profile.match.class,icon:profileIcon(profile)}
    })).concat([{value:"add", label:"Add application…"},{value:"manage",label:"Manage profiles…"}])
  }
  function addProfile(name, appClass) {
    let next = copy(config); next.profiles = next.profiles || []
    let index = next.profiles.length
    next.profiles.push({name:name, match:{class:appClass}})
    apply(next, false); profileIndex = index
  }
  property Timer toastTimer: Timer { interval: 5000; onTriggered: root.toast = "" }
}

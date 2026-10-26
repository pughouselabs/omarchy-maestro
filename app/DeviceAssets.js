.pragma library
// Which picture folder under assets/devices shows a mouse model.
// Order: the model's own folder, then a folder whose render has the same body,
// then nothing (the neutral silhouette). A model never borrows the picture of
// a mouse with a different body.
const SAME_BODY = {
  "MX Master":"mx-master",
  "MX Master 2S":"mx-master",
  "MX Master 3":"mx-master-3s",
  "MX Master 3S":"mx-master-3s",
  "MX Master 4":"mx-master-3s",
  "MX Vertical":"mx-vertical"
}
const SILHOUETTE_CREDIT = "MX Master 2S 3D model by danish_blends (sketchfab.com/3d-models/logitech-mx-master-2s-danish-blends-e8f3235951934a01aba4e0ee3de72e71), licensed CC BY-NC 4.0; rendered for Maestro."
const SILHOUETTE_CHANGES = "Shown as a neutral silhouette traced from that render and tinted with the current theme."
const SILHOUETTE_URL = "https://sketchfab.com/3d-models/logitech-mx-master-2s-danish-blends-e8f3235951934a01aba4e0ee3de72e71"
const DEFAULT_LICENSE = "CC BY-NC 4.0"
const DEFAULT_LICENSE_URL = "https://creativecommons.org/licenses/by-nc/4.0/"

// "MX Master 3S" -> "mx-master-3s". Empty for an unknown model.
function slug(model) {
  const name = String(model || "").trim()
  if (!name || name.toLowerCase() === "unknown") return ""
  return name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "")
}

// Folders to try, in order, for one model name.
function candidates(model) {
  const list = []
  const own = slug(model)
  if (own) list.push(own)
  const shared = SAME_BODY[String(model || "").trim()]
  if (shared && list.indexOf(shared) < 0) list.push(shared)
  return list
}

// ready maps a folder to true (has a hero or top image), false (has none) or
// undefined (still checking). Returns the first folder with an image, "" when
// none has one (show the silhouette), or null while an earlier folder is unknown.
function choose(list, ready) {
  for (let i = 0; i < list.length; i++) {
    const state = ready ? ready[list[i]] : undefined
    if (state === undefined) return null
    if (state === true) return list[i]
  }
  return ""
}

// True while a folder preferred over the one shown has no picture yet, so a
// picture added there later still appears (for example an MX Master 2S folder
// beside the shared MX Master render). folder is what choose() returned.
function preferredMissing(list, folder) {
  if (folder === null || folder === undefined) return true
  const shown = folder ? list.indexOf(folder) : list.length
  return shown !== 0
}

// Help credits for the picture shown. metadata is the folder's hotspots.json
// (or {} while loading, {placeholder:true} when missing or unreadable).
function credit(folder, metadata) {
  if (!folder) return {text:SILHOUETTE_CREDIT, changes:SILHOUETTE_CHANGES, url:SILHOUETTE_URL, license:DEFAULT_LICENSE, licenseUrl:DEFAULT_LICENSE_URL}
  const data = metadata && typeof metadata === "object" ? metadata : {}
  return {
    text:typeof data.credit === "string" && data.credit ? data.credit : "No image credit supplied.",
    changes:typeof data.credit_changes === "string" ? data.credit_changes : "",
    url:typeof data.credit_url === "string" ? data.credit_url : "",
    license:typeof data.license === "string" && data.license ? data.license : DEFAULT_LICENSE,
    licenseUrl:typeof data.license_url === "string" && data.license_url ? data.license_url : DEFAULT_LICENSE_URL
  }
}

// Hotspots for the controls this mouse reports. device is the settings-app
// device ({buttons:[{name, available}], thumb_wheel:{available}}); without one
// (no mouse yet) every hotspot is kept. builtIn names a control shown even when
// not reported (the MX Master's horizontal-scroll thumb wheel).
function reported(points, device, builtIn) {
  if (!device || !Array.isArray(device.buttons)) return points
  return points.filter(function(point) {
    if (builtIn && builtIn.indexOf(point.name) >= 0) return true
    if (point.name === "thumb_wheel") return !!(device.thumb_wheel && device.thumb_wheel.available === true)
    return device.buttons.some(function(button) { return button.name === point.name && button.available === true })
  })
}

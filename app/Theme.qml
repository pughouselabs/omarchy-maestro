pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io

QtObject {
  id: root
  property var colors: ({})
  readonly property color background: colors.background || "#171b22"
  readonly property color seed: colors.foreground || "#e8ecf0"
  readonly property color surface: mix(background,seed,0.035)
  readonly property color raised: mix(background,seed,0.075)
  readonly property color border: mix(background,seed,0.18)
  readonly property color boundary:readableAt(mix(background,seed,0.38),[background,surface,raised],3.05)
  readonly property color foreground: readable(seed,[background,surface,raised])
  readonly property color muted: readable(mix(background,seed,0.62),[background,surface,raised])
  readonly property color accent: readable(colors.accent || colors.color4 || "#9dc8b8",[background,surface,raised])
  readonly property color urgent: readable(colors.red || colors.color1 || "#e59494",[background,surface,raised])
  readonly property color accentText: contrast(accent,"#ffffff") > contrast(accent,"#111111") ? "#ffffff" : "#111111"
  readonly property color accentWash: mix(background,accent,0.08)
  property string fixtureThemePath:""
  readonly property string statePath: (fixtureThemePath || Quickshell.env("MAESTRO_THEME_PATH") || (Quickshell.env("XDG_STATE_HOME") || Quickshell.env("HOME") + "/.local/state") + "/omarchy/current/theme").replace(/\/+$/,"") + "/"
  function rgb(c) {
    if (typeof c !== "string") return c
    let h = c.replace("#","")
    return Qt.rgba(parseInt(h.slice(0,2),16)/255,parseInt(h.slice(2,4),16)/255,parseInt(h.slice(4,6),16)/255,1)
  }
  function alpha(c,a) { c=rgb(c); return Qt.rgba(c.r,c.g,c.b,a) }
  function mix(a,b,t) { a = rgb(a); b = rgb(b); return Qt.rgba(a.r+(b.r-a.r)*t,a.g+(b.g-a.g)*t,a.b+(b.b-a.b)*t,1) }
  function luminance(c) {
    c = rgb(c)
    function channel(v) { return v <= 0.04045 ? v/12.92 : Math.pow((v+0.055)/1.055,2.4) }
    return 0.2126*channel(c.r)+0.7152*channel(c.g)+0.0722*channel(c.b)
  }
  function contrast(a,b) { let x = luminance(a), y = luminance(b); return (Math.max(x,y)+0.05)/(Math.min(x,y)+0.05) }
  function readable(c,backgrounds) { return readableAt(c,backgrounds,4.6) }
  function readableAt(c,backgrounds,minimum) {
    let target = luminance(background) > 0.45 ? "#000000" : "#ffffff", result = rgb(c)
    for (let i=0;i<=100;i++) {
      result = mix(c,target,i/100)
      if (backgrounds.every(function(bg) { return contrast(result,bg) >= minimum })) return result
    }
    return result
  }
  property string fontFamily: Qt.application.font.family || "Inter, Cantarell, Noto Sans, sans-serif"
  property int fontSize: 14
  function parse(text) {
    let result = {}, section = ""
    text.split(/\r?\n/).forEach(function(line) {
      let heading = line.match(/^\s*\[([^\]]+)\]/)
      if (heading) { section = heading[1]; return }
      let match = line.match(/^\s*([\w-]+)\s*=\s*["']([^"']*)["']/)
      if (match) result[(section ? section + "." : "") + match[1]] = match[2]
      let number = line.match(/^\s*([\w-]+)\s*=\s*(\d+)/)
      if (number) result[(section ? section + "." : "") + number[1]] = Number(number[2])
    })
    return result
  }
  property FileView colorFile: FileView {
    path: root.statePath + "colors.toml"; preload: true; watchChanges: true; printErrors: false
    onFileChanged: reload()
    onLoaded: root.colors = root.parse(text())
    onLoadFailed: root.colors = ({})
  }
  property Timer themePoll: Timer {
    interval: 2000; repeat: true; running: true
    onTriggered: { root.colorFile.reload(); root.shellFile.reload() }
  }
  property FileView shellFile: FileView {
    path: root.statePath + "shell.toml"; preload: true; watchChanges: true; printErrors: false
    onFileChanged: reload()
    onLoaded: {
      let values = root.parse(text())
      root.fontFamily = values["font.family"] || Qt.application.font.family || "Inter, Cantarell, Noto Sans, sans-serif"
      root.fontSize = Math.max(14,Math.min(16,values["font.base-size"] || 14))
    }
  }
}

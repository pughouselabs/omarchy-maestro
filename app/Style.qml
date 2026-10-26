pragma Singleton
import QtQuick
QtObject {
  property real windowWidth:1280
  readonly property real uiScale:1
  readonly property int cornerRadius:12
  readonly property color normalBorderColor:Theme.luminance(Theme.background) > 0.45 ? Theme.alpha(Theme.border,0.6) : Theme.border
  function space(value) { return value }
  readonly property int fontDisplay:26
  readonly property int fontTitle:20
  readonly property int fontHeading:15
  readonly property int fontBody:14
  readonly property int fontCaption:12
  readonly property int spacingSm:4
  readonly property int spacingMd:8
  readonly property int spacingLg:16
  readonly property int motion:120
  readonly property int panelMotion:220
}

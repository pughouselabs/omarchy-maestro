pragma ComponentBehavior: Bound
import QtQuick

Text {
  textFormat: Text.PlainText
  color: Theme.foreground
  font.family: Theme.fontFamily
  font.pixelSize: Style.fontBody
  lineHeight:font.pixelSize === Style.fontBody ? 1.4 : 1.2
  wrapMode: Text.WordWrap
}

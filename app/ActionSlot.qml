pragma ComponentBehavior: Bound
import QtQuick

Column {
  id: root
  property string label: ""
  property string summary: "Default"
  property string error: ""
  signal clicked()
  spacing: Style.spacingSm
  Button {
    width: parent.width
    text: root.label + "  ·  " + root.summary
    tooltipText: text
    bordered: true; focusable: true; leftAlign: true
    onClicked: root.clicked()
  }
  Label { width: parent.width; visible: root.error !== ""; text: root.error; color: Theme.urgent }
}

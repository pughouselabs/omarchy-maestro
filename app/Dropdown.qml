pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls as Controls
import Quickshell
Controls.ComboBox {
  id: root
  property var options: []
  property string value: ""
  property bool profileMenu:false
  readonly property var selectedOption:options.find(function(option) { return String(option.value) === value }) || ({})
  signal changed(string value)
  model: options
  textRole: "label"; valueRole: "value"
  currentIndex: {
    for (let i = 0; i < options.length; i++) if (String(options[i].value) === value) return i
    return -1
  }
  delegate:Controls.ItemDelegate {
    id:menuRow
    required property var modelData
    required property int index
    width:root.width; height:40
    highlighted:root.highlightedIndex === index
    font:root.font
    contentItem:Row { spacing:8
      AppGlyph { width:16; height:16; visible:!!menuRow.modelData.icon; icon:menuRow.modelData.icon || ""; label:menuRow.modelData.label; anchors.verticalCenter:parent.verticalCenter }
      Icon { width:16; height:16; visible:root.profileMenu && !menuRow.modelData.icon; name:menuRow.modelData.value === "add" ? "plus" : menuRow.modelData.value === "manage" ? "gear" : "apps"; anchors.verticalCenter:parent.verticalCenter; color:Theme.muted }
      Label { text:menuRow.modelData.label; width:parent.width-24; maximumLineCount:1; elide:Text.ElideRight; anchors.verticalCenter:parent.verticalCenter }
    }
    background:Rectangle { color:menuRow.highlighted ? Theme.raised : Theme.surface }
    Rectangle { width:parent.width; height:1; color:Theme.border; visible:menuRow.modelData.value === "add" }
  }
  contentItem:Item {
    AppGlyph { x:12; width:16; height:16; visible:root.profileMenu && !!root.selectedOption.icon; icon:root.selectedOption.icon || ""; label:root.displayText; anchors.verticalCenter:parent.verticalCenter }
    Icon { x:12; width:16; height:16; visible:root.profileMenu && !root.selectedOption.icon; name:"apps"; anchors.verticalCenter:parent.verticalCenter; color:Theme.muted }
    Text { anchors.fill:parent; text:root.displayText; textFormat:Text.PlainText; font:root.font; color:Theme.foreground; leftPadding:root.profileMenu ? 36 : 12; rightPadding:32; verticalAlignment:Text.AlignVCenter; elide:Text.ElideRight }
  }
  indicator:Icon { name:"chevron"; width:16; height:16; x:root.width-width-12; y:(root.height-height)/2; color:Theme.muted }
  background:Rectangle { radius:8; color:root.hovered ? Theme.raised : Theme.surface; border.width:1; border.color:Theme.boundary; FocusRing { control:root } Behavior on color { ColorAnimation { duration:Style.motion; easing.type:Easing.OutCubic } } }
  onActivated: changed(String(currentValue))
  implicitWidth: 250; implicitHeight:36
  palette.button: Theme.surface; palette.buttonText: Theme.foreground
  palette.window: Theme.surface; palette.text: Theme.foreground
  palette.highlight: Theme.accent; palette.highlightedText: Theme.accentText
  font.family: Theme.fontFamily; font.pixelSize: Style.fontBody
}

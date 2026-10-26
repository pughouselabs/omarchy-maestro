pragma ComponentBehavior: Bound

import QtQuick
import Quickshell.Io
import QtQuick.Controls as Controls
import qs.Commons
import qs.Commons as Commons
import qs.Ui as Ui

Ui.Panel {
  id: root
  moduleName: "io.github.nodrej.maestro"
  manageIpc: false
  property var hostWidget: null
  property Item anchorItem: null
  readonly property var mouse: hostWidget ? hostWidget.mouse : null
  readonly property var dpi: hostWidget ? hostWidget.section("dpi") : null
  readonly property var smartshift: hostWidget ? hostWidget.section("smartshift") : null
  readonly property var wheel: hostWidget ? hostWidget.section("wheel") : null
  readonly property bool busy: hostWidget ? hostWidget.busy : false
  readonly property var presets: {
    var setting = root.setting("dpiPresets", "800, 1000, 1600, 2400")
    var values = Array.isArray(setting) ? setting : String(setting).split(",")
    var choices = dpi && dpi.choices ? dpi.choices : []
    var result = []
    for (var i = 0; i < values.length; i++) {
      var value = Number(values[i])
      if (value > 0 && Math.floor(value) === value && choices.indexOf(value) >= 0 && result.indexOf(value) < 0)
        result.push(value)
    }
    return result
  }

  // Same type roles and colors as the shell's own panels (power, audio).
  readonly property color foreground: bar ? bar.foreground : Commons.Color.popups.text
  readonly property color muted: Qt.darker(foreground, 1.4)
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family
  // Text sits on one left edge; surfaces (rows, buttons, rules) span the full width.
  readonly property int inset: Style.spacing.lg

  readonly property string connectionLabel: {
    var kind = mouse ? mouse.connection : ""
    if (kind === "unifying") return "Unifying receiver"
    if (kind === "bolt") return "Bolt receiver"
    if (kind === "bluetooth") return "Bluetooth"
    return ""
  }
  readonly property string heroStatus: {
    if (!mouse) return busy ? "Looking for your mouse…" : "Not connected"
    var parts = [connectionLabel, hostWidget.batteryState].filter(function(part) { return part !== "" })
    return parts.length ? parts.join(" · ") : "Connected"
  }

  Process {
    id: settingsLauncher
    command: [decodeURIComponent(Qt.resolvedUrl("bin/maestro-settings").toString().replace(/^file:\/\//, ""))]
  }

  onOpenedChanged: if (opened && hostWidget) hostWidget.refresh()

  Ui.KeyboardPanel {
    id: popup
    anchorItem: root.anchorItem
    owner: root.hostWidget || root
    bar: root.bar
    open: root.opened
    focusTarget: content
    contentWidth: fittedContentWidth(Style.space(380))
    contentHeight: fittedContentHeight(body.implicitHeight)

    Controls.ScrollView {
      id: content
      anchors.fill: parent
      clip: true
      contentWidth: availableWidth
      Keys.onEscapePressed: root.close()

      Column {
        id: body
        width: content.availableWidth
        spacing: Style.space(14)

        // ---------- Hero: mouse · model and status · battery ----------
        Column {
          width: parent.width
          spacing: Style.space(10)

          Item {
            x: root.inset
            width: parent.width - root.inset * 2
            implicitHeight: Math.max(heroIcon.implicitHeight, heroLabels.implicitHeight, heroPercent.implicitHeight, openButton.implicitHeight)

            Text {
              id: heroIcon
              textFormat: Text.PlainText
              text: "󰍽"
              color: root.foreground
              opacity: root.mouse ? 1 : 0.5
              font.family: root.fontFamily
              font.pixelSize: Style.font.display
              anchors.left: parent.left
              anchors.verticalCenter: parent.verticalCenter
            }

            Column {
              id: heroLabels
              anchors.left: heroIcon.right
              anchors.leftMargin: Style.space(14)
              anchors.right: heroPercent.left
              anchors.rightMargin: Style.space(10)
              anchors.verticalCenter: parent.verticalCenter
              spacing: Style.space(2)

              Text {
                width: parent.width
                textFormat: Text.PlainText
                text: root.hostWidget ? root.hostWidget.modelName : "MX Master"
                color: root.foreground
                font.family: root.fontFamily
                font.pixelSize: Style.font.title
                font.weight: Font.DemiBold
                elide: Text.ElideRight
              }
              Text {
                width: parent.width
                textFormat: Text.PlainText
                text: root.heroStatus.toUpperCase()
                color: root.muted
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
                font.weight: Font.DemiBold
                font.letterSpacing: 1.2
                elide: Text.ElideRight
              }
            }

            Text {
              id: heroPercent
              visible: root.mouse !== null && root.hostWidget.hasPercent
              textFormat: Text.PlainText
              text: visible ? Math.round(Number(root.hostWidget.battery.percent)) + "%" : ""
              color: root.hostWidget && root.hostWidget.lowBattery ? Commons.Color.urgent : root.foreground
              font.family: root.fontFamily
              font.pixelSize: Style.font.display
              font.weight: Font.DemiBold
              anchors.right: openButton.left
              anchors.rightMargin: Style.space(12)
              anchors.verticalCenter: parent.verticalCenter
            }

            // Opens the full Maestro settings app (top right of the panel).
            Ui.Button {
              id: openButton
              text: "Open Maestro"
              iconText: "󰒓"
              iconSize: Style.font.caption
              fontSize: Style.font.caption
              tooltipText: "Customize buttons, gestures and Smart Actions"
              foreground: root.foreground
              fontFamily: root.fontFamily
              bordered: true
              focusable: true
              anchors.right: parent.right
              anchors.top: parent.top
              onClicked: { settingsLauncher.startDetached(); root.close() }
            }
          }

          // Battery level, drawn like the shell's battery panel but without the pulse.
          Rectangle {
            visible: heroPercent.visible
            x: root.inset
            width: parent.width - root.inset * 2
            height: Style.space(6)
            radius: Style.cornerRadius > 0 ? height / 2 : 0
            color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.12)

            Rectangle {
              height: parent.height
              radius: parent.radius
              width: heroPercent.visible
                ? Math.max(parent.height, parent.width * Math.max(0, Math.min(100, Number(root.hostWidget.battery.percent))) / 100)
                : 0
              color: heroPercent.color

              Behavior on width { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }
            }
          }

          Caption {
            visible: !root.mouse && !root.busy
            text: "Move the mouse to wake it, then open this panel again."
          }
          Caption {
            visible: root.hostWidget !== null && root.hostWidget.errorMessage !== ""
            text: root.hostWidget ? root.hostWidget.errorMessage : ""
            color: Commons.Color.urgent
          }
        }

        // ---------- Pointer speed ----------
        Ui.PanelSeparator {
          visible: root.dpi !== null
          foreground: root.foreground
        }

        Column {
          width: parent.width
          spacing: Style.space(10)
          visible: root.dpi !== null

          SectionHeader {
            text: "POINTER SPEED"
            value: root.dpi ? root.dpi.current + " DPI" : ""
          }

          Row {
            id: presetRow
            width: parent.width
            spacing: Style.space(6)
            visible: root.presets.length > 0
            readonly property real cellWidth: root.presets.length > 0
              ? (width - spacing * (root.presets.length - 1)) / root.presets.length : 0

            Repeater {
              model: root.presets
              Ui.Button {
                required property var modelData
                width: presetRow.cellWidth
                text: String(modelData)
                foreground: root.foreground
                fontFamily: root.fontFamily
                verticalPadding: Style.spacing.controlPaddingY + Style.space(2)
                bordered: true
                selected: root.dpi !== null && root.dpi.current === modelData
                enabled: !root.busy
                focusable: true
                onClicked: root.hostWidget.change(["dpi", String(modelData)])
              }
            }
          }
          Caption {
            visible: root.presets.length === 0
            text: "None of the configured presets work with this mouse. Change them in the widget settings."
          }
        }

        // ---------- Scroll wheel ----------
        Ui.PanelSeparator {
          visible: root.smartshift !== null || root.wheel !== null
          foreground: root.foreground
        }

        Column {
          width: parent.width
          spacing: Style.space(6)
          visible: root.smartshift !== null || root.wheel !== null

          SectionHeader { text: "SCROLL WHEEL" }

          SwitchRow {
            visible: root.smartshift !== null
            label: "Free spin"
            description: checked ? "The wheel always spins freely."
              : "Clicks in steps. SmartShift frees it when you scroll fast."
            checked: root.smartshift !== null && root.smartshift.mode === "freespin"
            enabled: !root.busy
            onToggled: root.hostWidget.change(["smartshift", "--mode", checked ? "ratchet" : "freespin"])
          }

          Column {
            width: parent.width
            spacing: Style.space(6)
            visible: root.smartshift !== null
            topPadding: Style.space(4)

            Item {
              x: root.inset
              width: parent.width - root.inset * 2
              implicitHeight: Math.max(thresholdLabel.implicitHeight, thresholdValue.implicitHeight)

              Text {
                id: thresholdLabel
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                textFormat: Text.PlainText
                text: "SmartShift threshold"
                color: root.foreground
                font.family: root.fontFamily
                font.pixelSize: Style.font.body
              }
              Text {
                id: thresholdValue
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                textFormat: Text.PlainText
                text: threshold.dragging ? Math.round(threshold.liveValue)
                  : (root.smartshift ? String(root.smartshift.threshold) : "")
                color: root.muted
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
                font.weight: Font.DemiBold
              }
            }
            Ui.PanelSlider {
              id: threshold
              x: root.inset
              width: parent.width - root.inset * 2
              bar: root.bar
              minimum: 1
              maximum: 50
              step: 1
              integer: true
              value: root.smartshift ? Math.max(1, Math.min(50, root.smartshift.threshold)) : 1
              enabled: !root.busy
              onReleased: function(value) {
                root.hostWidget.change(["smartshift", "--threshold", String(Math.round(value))])
              }
            }
            Caption {
              text: root.smartshift && root.smartshift.threshold > 50
                ? "Set to " + root.smartshift.threshold + " elsewhere. Moving the slider sets a value from 1 to 50."
                : "Lower values switch to free spin sooner."
            }
          }

          SwitchRow {
            visible: root.wheel !== null
            label: "Natural scrolling"
            description: "Content moves the same way as the wheel."
            checked: root.wheel !== null && root.wheel.inverted === true
            enabled: !root.busy
            onToggled: root.hostWidget.change(["scroll", "--invert", checked ? "off" : "on"])
          }
        }

      }
    }
  }

  // Muted helper text on the shared left edge.
  component Caption: Text {
    x: root.inset
    width: parent.width - root.inset * 2
    textFormat: Text.PlainText
    color: root.muted
    font.family: root.fontFamily
    font.pixelSize: Style.font.caption
    lineHeight: 1.2
    wrapMode: Text.WordWrap
  }

  // The shell's section header, with an optional current value on the right.
  component SectionHeader: Item {
    property string text: ""
    property string value: ""
    x: root.inset
    width: parent.width - root.inset * 2
    implicitHeight: Math.max(headerLabel.implicitHeight, headerValue.implicitHeight)

    Ui.PanelSectionHeader {
      id: headerLabel
      text: parent.text
      foreground: root.foreground
      fontFamily: root.fontFamily
      anchors.left: parent.left
      anchors.verticalCenter: parent.verticalCenter
    }
    Text {
      id: headerValue
      visible: text !== ""
      textFormat: Text.PlainText
      text: parent.value
      color: root.muted
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
      font.weight: Font.DemiBold
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
    }
  }

  // A plain settings row: label and description, switch at the end. No box at
  // rest; hover and keyboard focus use the shell's shared cursor highlight.
  component SwitchRow: Ui.CursorSurface {
    id: row
    property string label: ""
    property string description: ""
    property bool checked: false
    signal toggled()

    width: parent.width
    implicitHeight: Math.max(rowSwitch.implicitHeight, rowText.implicitHeight) + Style.spacing.controlPaddingY * 2
    foreground: root.foreground
    hasCursor: rowMouse.containsMouse || activeFocus
    activeFocusOnTab: true
    Keys.onReturnPressed: row.toggled()
    Keys.onEnterPressed: row.toggled()
    Keys.onSpacePressed: row.toggled()

    Column {
      id: rowText
      anchors.left: parent.left
      anchors.leftMargin: root.inset
      anchors.right: rowSwitch.left
      anchors.rightMargin: Style.spacing.rowPaddingX
      anchors.verticalCenter: parent.verticalCenter
      spacing: Style.spacing.xxs

      Text {
        width: parent.width
        textFormat: Text.PlainText
        text: row.label
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.body
        font.weight: Font.DemiBold
        elide: Text.ElideRight
      }
      Text {
        width: parent.width
        visible: text !== ""
        textFormat: Text.PlainText
        text: row.description
        color: root.muted
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        wrapMode: Text.WordWrap
      }
    }

    Ui.ToggleSwitch {
      id: rowSwitch
      anchors.right: parent.right
      anchors.rightMargin: root.inset
      anchors.verticalCenter: parent.verticalCenter
      checked: row.checked
      interactive: false
      foreground: root.foreground
    }

    MouseArea {
      id: rowMouse
      anchors.fill: parent
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      onClicked: row.toggled()
    }
  }
}

pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls as Controls

Column {
  id: root
  required property var controller
  property bool wheelOnly: false
  readonly property var device: controller.device || ({})
  readonly property var dpi: device.dpi || ({choices:[]})
  readonly property var wheel: device.thumb_wheel || ({available:false})
  readonly property bool natural: controller.deviceSetting("invert",undefined) === undefined ? !!(device.scroll || {}).inverted : controller.deviceSetting("invert",undefined) === true
  readonly property string shiftMode: controller.deviceSetting("smartshift.mode",undefined) || (device.smartshift || {}).mode || "ratchet"
  readonly property int shiftThreshold: controller.deviceSetting("smartshift.threshold",undefined) || (device.smartshift || {}).threshold || 16
  readonly property bool wheelAvailable: wheel.available === true
  spacing:16

  function changeWheelMode(mode) {
    let next = controller.copy(controller.effective("thumb_wheel", {mode:"horizontal",step:120}))
    next.mode = mode
    if (mode === "custom") {
      next.left = controller.effective("thumb_wheel.left", {type:"key",keys:["LEFT"]})
      next.right = controller.effective("thumb_wheel.right", {type:"key",keys:["RIGHT"]})
    }
    controller.changeWheel("thumb_wheel",next)
  }
  signal pick(string path)
  SectionLabel { visible:!root.wheelOnly; text:"Pointer" }
  Card {
    visible:!root.wheelOnly; width:parent.width; height:104
    Item { width:parent.width; height:52
      Column { x:16; anchors.verticalCenter:parent.verticalCenter; width:parent.width-328
        Label { text:"Pointer speed" }
        Label { text:"Higher is faster"; font.pixelSize:Style.fontCaption; color:Theme.muted }
      }
      Column { anchors.right:parent.right; anchors.rightMargin:16; width:280; spacing:0
        Label { width:parent.width; horizontalAlignment:Text.AlignRight; text:(root.dpi.choices && root.dpi.choices.length ? root.dpi.choices[Math.round(dpiSlider.value)] : "Unavailable") + " DPI"; font.pixelSize:Style.fontCaption; color:Theme.muted }
        Slider { id:dpiSlider; width:parent.width; height:22; enabled:root.dpi.choices && root.dpi.choices.length > 0
          from:0; to:Math.max(1,(root.dpi.choices || []).length-1); stepSize:1; snapMode:Controls.Slider.SnapAlways
          value:Math.max(0,(root.dpi.choices || []).indexOf(root.controller.deviceSetting("dpi",undefined) || root.dpi.current))
          onPressedChanged:if (!pressed && enabled) root.controller.changeDeviceSetting("dpi",root.dpi.choices[Math.round(value)])
          onMoved:if (!pressed && enabled) root.controller.changeDeviceSetting("dpi",root.dpi.choices[Math.round(value)])
        }
        Row { width:parent.width
          Label { width:parent.width/2; text:"Slow"; font.pixelSize:Style.fontCaption; color:Theme.muted }
          Label { width:parent.width/2; text:"Fast"; horizontalAlignment:Text.AlignRight; font.pixelSize:Style.fontCaption; color:Theme.muted }
        }
      }
    }
    Rectangle { y:52; x:16; width:parent.width-32; height:1; color:Theme.alpha(Theme.border,0.6) }
    Item { y:52; width:parent.width; height:52
      Label { x:16; text:"Scroll direction"; anchors.verticalCenter:parent.verticalCenter }
      Row { anchors.right:parent.right; anchors.rightMargin:16; anchors.verticalCenter:parent.verticalCenter; spacing:4
        Button { text:"Traditional"; kind:"segment"; selected:!root.natural; enabled:!!root.device.scroll; onClicked:root.controller.changeDeviceSetting("invert",false) }
        Button { text:"Natural"; kind:"segment"; selected:root.natural; enabled:!!root.device.scroll; onClicked:root.controller.changeDeviceSetting("invert",true) }
      }
    }
  }
  Label { visible:!root.wheelOnly && !dpiSlider.enabled; width:parent.width; text:"Pointer speed is unavailable on this connection. Wake your mouse and try Refresh."; color:Theme.muted; font.pixelSize:Style.fontCaption }
  Label { visible:!root.wheelOnly && text !== ""; text:root.controller.deviceErrors("dpi") || root.controller.deviceErrors("invert"); color:Theme.urgent }
  SectionLabel { visible:!root.wheelOnly; text:"Smart scroll (SmartShift)"; topPadding:8 }
  Card {
    visible:!root.wheelOnly; width:parent.width; height:104
    Item { width:parent.width; height:52
      Label { x:16; text:"Mode"; anchors.verticalCenter:parent.verticalCenter }
      Row { anchors.right:parent.right; anchors.rightMargin:16; anchors.verticalCenter:parent.verticalCenter; spacing:4
        Button { text:"Automatic"; kind:"segment"; selected:root.shiftThreshold < 255 && root.shiftMode !== "freespin"; enabled:!!root.device.smartshift; onClicked:root.controller.changeDeviceSetting("smartshift",{mode:"ratchet",threshold:16}) }
        Button { text:"Clicky"; kind:"segment"; selected:root.shiftThreshold === 255 && root.shiftMode !== "freespin"; enabled:!!root.device.smartshift; onClicked:root.controller.changeDeviceSetting("smartshift",{mode:"ratchet",threshold:255}) }
        Button { text:"Free spin"; kind:"segment"; selected:root.shiftMode === "freespin"; enabled:!!root.device.smartshift; onClicked:root.controller.changeDeviceSetting("smartshift.mode","freespin") }
      }
    }
    Rectangle { y:52; x:16; width:parent.width-32; height:1; color:Theme.alpha(Theme.border,0.6) }
    Item { y:52; width:parent.width; height:52
      Label { x:16; text:"Switch sensitivity"; anchors.verticalCenter:parent.verticalCenter }
      Row { anchors.right:parent.right; anchors.rightMargin:16; anchors.verticalCenter:parent.verticalCenter; width:280; spacing:12
        Slider { id:shiftSlider; width:parent.width-40; from:1; to:50; stepSize:1; enabled:!!root.device.smartshift && root.shiftThreshold !== 255 && root.shiftMode !== "freespin"; value:Math.min(50,root.shiftThreshold)
          onPressedChanged:if (!pressed && enabled) root.controller.changeDeviceSetting("smartshift.threshold",Math.round(value))
          onMoved:if (!pressed && enabled) root.controller.changeDeviceSetting("smartshift.threshold",Math.round(value))
        }
        Label { text:Math.round(shiftSlider.value); color:Theme.muted; font.pixelSize:Style.fontCaption; anchors.verticalCenter:parent.verticalCenter }
      }
    }
  }
  Label { visible:!root.wheelOnly; width:parent.width; text:"Automatic switches to free spin when you flick the wheel."; color:Theme.muted; font.pixelSize:Style.fontCaption }
  Label { visible:!root.wheelOnly && text !== ""; width:parent.width; text:root.controller.deviceErrors("smartshift"); color:Theme.urgent }
  Rectangle {
    color:root.wheelOnly ? "transparent" : Theme.surface; radius:12; border.width:root.wheelOnly ? 0 : 1; border.color:Theme.border
    width:parent.width; height:wheelBody.implicitHeight+(root.wheelOnly ? 0 : 32)
    Column {
      id:wheelBody; anchors.left:parent.left; anchors.right:parent.right; anchors.top:parent.top; anchors.margins:root.wheelOnly ? 0 : 16; spacing:16
  Label { text:"Thumb wheel"; font.pixelSize:Style.fontTitle; font.weight:Font.DemiBold }
  Label { width:parent.width; visible:!root.wheelAvailable; text:root.controller.builtInThumbWheel ? "Turn the thumb wheel to scroll sideways. On this mouse, horizontal scrolling is built in and cannot be changed here." : "Thumb-wheel actions are unavailable on this connection. Built-in sideways scrolling still works where supported."; color:Theme.muted }
  Column {
    width:parent.width; spacing:16; visible:root.wheelAvailable
    Label { width:parent.width; text:root.controller.inherited("thumb_wheel.mode") ? "Mode · Same as All applications" : "Mode" }
    Dropdown {
      width:parent.width
      value:root.controller.effective("thumb_wheel.mode","horizontal")
      options:[{value:"horizontal",label:"Horizontal scroll"},{value:"volume",label:"Volume"},{value:"zoom",label:"Zoom"},{value:"tabs",label:"Browser tabs"},{value:"workspaces",label:"Workspaces"},{value:"custom",label:"Custom actions"}]
      onChanged:function(value) { root.changeWheelMode(value) }
    }
    Label { width:parent.width; text:"Wheel speed · " + Math.round(wheelSpeedSlider.value) + (root.controller.inherited("thumb_wheel.step") ? " · Same as All applications" : "") }
    Slider {
      id:wheelSpeedSlider; width:parent.width; from:1; to:360; stepSize:1
      value:root.controller.effective("thumb_wheel.step",120)
      onPressedChanged:if (!pressed && enabled) root.controller.changeWheel("thumb_wheel.step",Math.round(value))
      onMoved:if (!pressed && enabled) root.controller.changeWheel("thumb_wheel.step",Math.round(value))
      }
    Label { width:parent.width; text:"Choose Custom actions to reverse the wheel's left and right actions."; color:Theme.muted }
    ActionSlot { width:parent.width; visible:root.controller.effective("thumb_wheel.mode","horizontal") === "custom"; label:"Turn left"; summary:root.controller.describe(root.controller.effective("thumb_wheel.left",null)); error:root.controller.wheelErrors("thumb_wheel.left"); onClicked:root.pick("thumb_wheel.left") }
    ActionSlot { width:parent.width; visible:root.controller.effective("thumb_wheel.mode","horizontal") === "custom"; label:"Turn right"; summary:root.controller.describe(root.controller.effective("thumb_wheel.right",null)); error:root.controller.wheelErrors("thumb_wheel.right"); onClicked:root.pick("thumb_wheel.right") }
    Button {
      visible:root.controller.effective("thumb_wheel.mode","horizontal") === "custom"; text:"Reverse left and right"
      onClicked: {
        let wheel = root.controller.copy(root.controller.effective("thumb_wheel",{}))
        wheel.left = root.controller.effective("thumb_wheel.right",null); wheel.right = root.controller.effective("thumb_wheel.left",null)
        root.controller.changeWheel("thumb_wheel",wheel)
      }
    }
    Button { visible:root.controller.profileIndex >= 0; text:"Use All applications wheel settings"; onClicked:root.controller.changeWheel("thumb_wheel",null,true) }
  }
  Label { width:parent.width; text:root.controller.wheelErrors("thumb_wheel"); visible:text !== ""; color:Theme.urgent }
    }
  }
}

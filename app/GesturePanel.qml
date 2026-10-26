pragma ComponentBehavior: Bound
import QtQuick

Column {
  id: root
  required property var controller
  property string preset: ""
  signal pick(string path)
  width: parent.width
  spacing:16
  function presets() {
    let result = {
      windows: {tap:{type:"desktop",action:"app_switcher"}, up:{type:"desktop",action:"fullscreen"}, down:{type:"desktop",action:"menu"}, left:{type:"desktop",action:"workspace_previous"}, right:{type:"desktop",action:"workspace_next"}},
      desktop: {tap:{type:"desktop",action:"apps"}, up:{type:"desktop",action:"menu"}, down:{type:"desktop",action:"app_switcher"}, left:{type:"desktop",action:"workspace_previous"}, right:{type:"desktop",action:"workspace_next"}},
      media: {tap:{type:"key",keys:["PLAYPAUSE"]}, up:{type:"key",keys:["VOLUMEUP"]}, down:{type:"key",keys:["VOLUMEDOWN"]}, left:{type:"key",keys:["PREVIOUSSONG"]}, right:{type:"key",keys:["NEXTSONG"]}},
      zoom: {tap:{type:"key",keys:["CTRL","0"]}, up:{type:"key",keys:["CTRL","EQUAL"]}, down:{type:"key",keys:["CTRL","MINUS"]}, left:{type:"key",keys:["CTRL","MINUS"]}, right:{type:"key",keys:["CTRL","EQUAL"]}}
    }
    ;(controller.catalog.gesture_presets || []).forEach(function(item) {
      result[item.id === "workspaces" ? "desktop" : item.id] = item.gesture
    })
    return result
  }
  function currentPreset() {
    let options = presets(), current = "custom"
    Object.keys(options).some(function(id) {
      if (["tap","up","down","left","right"].every(function(direction) {
        return controller.sameAction(controller.effective("gesture." + direction, null),options[id][direction])
      })) { current = id; return true }
      return false
    })
    return current
  }
  function choosePreset(value) {
    preset = controller.setGestureMode(value === "custom" ? {} : presets()[value]) ? value : ""
  }
  Label { text:"Gesture button"; font.pixelSize:Style.fontTitle; font.weight:Font.DemiBold }
  Row { width:parent.width; height:96; spacing:16
    DeviceImage { width:72; height:96; hotspots:false; view:"top-down"; controller:root.controller }
    Label { width:parent.width-88; anchors.verticalCenter:parent.verticalCenter; text:"Hold the thumb button and move the mouse. Tap without moving for the center action."; color:Theme.muted }
  }
  Dropdown {
    width:parent.width
    options:[{value:"windows",label:"Preset: Window navigation"},{value:"desktop",label:"Desktop / workspaces"},{value:"media",label:"Media"},{value:"zoom",label:"Zoom"},{value:"custom",label:"Custom"}]
    value:root.preset || root.currentPreset()
    onChanged:function(value) {
      root.choosePreset(value)
    }
  }
  Item {
    width:parent.width; height:304
    Rectangle { x:parent.width / 2 - 1; y:42; width:1; height:222; color:Theme.border }
    Rectangle { x:30; y:151; width:parent.width - 60; height:1; color:Theme.border }
    Repeater {
      model:[{key:"up",label:"Up",px:0.5,py:0},{key:"left",label:"Left",px:0.04,py:0.37},{key:"tap",label:"Tap",px:0.5,py:0.37},{key:"right",label:"Right",px:0.96,py:0.37},{key:"down",label:"Down",px:0.5,py:0.75}]
      Button {
        id: directionButton
        required property var modelData
        width:Math.min(112, root.width / 3); height:84
        x:Math.max(0, Math.min(parent.width - width, parent.width * modelData.px - width / 2)); y:modelData.py * 280
        text:modelData.label + "\n" + root.controller.describe(root.controller.effective("gesture." + modelData.key, null))
        tooltipText:text; bordered:true; fill:modelData.key === "tap" ? Theme.accentWash : Theme.surface
        contentItem:Column {
          spacing:2
          Icon { name:directionButton.modelData.key === "up" ? "chevron-up" : directionButton.modelData.key === "left" ? "chevron-left" : directionButton.modelData.key === "right" ? "chevron-right" : directionButton.modelData.key === "down" ? "chevron-down" : "mouse"; width:14; height:14; anchors.horizontalCenter:parent.horizontalCenter; color:Theme.muted }
          Label { width:parent.width; text:directionButton.modelData.label.toUpperCase(); color:Theme.muted; horizontalAlignment:Text.AlignHCenter; font.pixelSize:Style.fontCaption }
          Label { width:parent.width; text:root.controller.describe(root.controller.effective("gesture." + directionButton.modelData.key,null)); horizontalAlignment:Text.AlignHCenter; font.pixelSize:13; font.weight:Font.Medium; maximumLineCount:2; elide:Text.ElideRight }
        }
        onClicked:root.pick("gesture." + modelData.key)
      }
    }
  }
  Row { width:parent.width
    Label { width:parent.width-40; text:"Movement distance" }
    Label { text:Math.round(gestureDistanceSlider.value); color:Theme.muted }
  }
  Slider {
    id:gestureDistanceSlider; width:parent.width; from:10; to:200; stepSize:5
    value:root.controller.effective("gesture.threshold",50)
    onPressedChanged:if (!pressed) root.controller.change("gesture.threshold", Math.round(value))
    onMoved:if (!pressed) root.controller.change("gesture.threshold", Math.round(value))
  }
  Label { width:parent.width; text:root.controller.errorsFor("gesture"); visible:text !== ""; color:Theme.urgent }
  Button { visible:root.controller.profileIndex >= 0; text:"Use All applications gestures"; onClicked:root.controller.change("gesture",null,true) }
  Button { text:"Assign a single action instead"; glyph:"chevron-right"; foreground:Theme.accent; onClicked:root.pick("buttons.gesture") }
  Connections { target:root.controller; function onConfigChanged() { root.preset = "" } }
}

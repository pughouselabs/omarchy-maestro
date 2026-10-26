pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls as Controls
Item {
  id:root
  required property var controller
  signal selectedDevice(int index)
  Controls.ScrollView {
    anchors.fill:parent; contentWidth:availableWidth; clip:true
    Column {
      width:parent.width; spacing:24
      Label { text:root.controller.devices.length === 1 ? "1 mouse connected" : root.controller.devices.length ? root.controller.devices.length + " mice connected" : "No mouse connected"; color:Theme.muted; font.pixelSize:Style.fontCaption }
      Flow {
        id:deviceGrid; width:parent.width; spacing:16
        Repeater {
          model:root.controller.devices
          Button {
            id:deviceCard; required property var modelData; required property int index
            readonly property bool stacked:root.controller.devices.length > 1
            width:stacked ? (deviceGrid.width-16)/2 : deviceGrid.width; height:stacked ? 280 : 320
            bordered:true; fill:Theme.surface; padding:0; leftPadding:0; rightPadding:0
            Accessible.name:"Customize " + modelData.model
            contentItem:Item {
              DeviceImage { id:heroImage; x:deviceCard.stacked ? 16 : 24; y:deviceCard.stacked ? 0 : 0; width:deviceCard.stacked ? parent.width-32 : Math.min(440,parent.width*0.50); height:deviceCard.stacked ? 160 : 320; hotspots:false; modelName:deviceCard.modelData.model }
              Column {
                x:deviceCard.stacked ? 24 : heroImage.width+32; y:deviceCard.stacked ? 160 : (parent.height-height)/2
                width:parent.width-x-24; spacing:deviceCard.stacked ? 8 : 16
                Row { width:parent.width; spacing:8
                  Rectangle { width:8; height:8; radius:4; color:deviceCard.modelData.writable ? Theme.accent : Theme.muted; anchors.verticalCenter:parent.verticalCenter
                    Controls.ToolTip.visible:connectionHover.containsMouse; Controls.ToolTip.text:deviceCard.modelData.writable ? "Connected" : "Read only"; MouseArea { id:connectionHover; anchors.fill:parent; hoverEnabled:true }
                  }
                  Label { width:parent.width-16; text:deviceCard.modelData.model; font.pixelSize:Style.fontTitle; font.weight:Font.DemiBold; maximumLineCount:1; elide:Text.ElideRight }
                }
                Flow { width:parent.width; spacing:8
                  StatusPill { text:root.controller.batteryLabel(deviceCard.modelData); level:(deviceCard.modelData.battery || {}).percent === undefined ? -1 : deviceCard.modelData.battery.percent; glyph:"battery" }
                  StatusPill { text:root.controller.connectionLabel(deviceCard.modelData) }
                }
                Button { text:"Customize"; kind:deviceCard.index === 0 ? "primary" : "secondary"; height:40; leftPadding:20; rightPadding:20; focusable:false; focusPolicy:Qt.NoFocus; onClicked:root.selectedDevice(deviceCard.index) }
              }
            }
            onClicked:root.selectedDevice(index)
          }
        }
      }
      DeviceImage { visible:!root.controller.devices.length; width:parent.width; height:220; hotspots:false; modelName:"unknown" }
      Label { visible:!root.controller.devices.length; width:parent.width; text:root.controller.loading ? "Looking for your mouse…" : "Wake your MX mouse, check the receiver or Bluetooth connection, then choose Refresh."; color:Theme.muted; horizontalAlignment:Text.AlignHCenter }
    }
  }
}

pragma ComponentBehavior: Bound
import QtQuick
import Quickshell
import Quickshell.Io
Image {
  id:root
  property string name:"mouse"
  property color color:Theme.foreground
  property string svg:""
  width:20; height:20
  source:svg ? "data:image/svg+xml;utf8," + encodeURIComponent(svg.replace(/#ffffff/g,color.toString())) : ""
  sourceSize:Qt.size(width*2,height*2)
  FileView {
    path:root.name ? Quickshell.shellDir + "/assets/icons/" + root.name + ".svg" : ""
    preload:true; printErrors:false
    onLoaded:root.svg = text()
    onLoadFailed:root.svg = ""
  }
}

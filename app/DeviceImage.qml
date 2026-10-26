pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Shapes
import Quickshell
import Quickshell.Io
import "DeviceAssets.js" as DeviceAssets
Item {
  id:root
  property var controller:null
  property bool hotspots:true
  property string view:"hero"
  property string modelName:controller && controller.device ? controller.device.model : "MX Master 2S"
  // The model's own picture folder, then one with the same body, else the silhouette (DeviceAssets.js).
  readonly property var folders:DeviceAssets.candidates(modelName)
  property var folderImages:({})
  readonly property var chosenFolder:DeviceAssets.choose(folders,folderImages)
  readonly property string folder:chosenFolder || ""
  readonly property string assetRoot:folder ? Quickshell.shellDir+"/assets/devices/"+folder+"/" : ""
  // Each file records the path it loaded, so a stale load from another folder never counts.
  property var loadedMetadata:({path:"",data:({})})
  readonly property var metadata:!assetRoot ? ({placeholder:true}) : loadedMetadata.path === assetRoot+"hotspots.json" ? loadedMetadata.data : ({})
  property string heroLoaded:""
  property string rimLoaded:""
  property string thumbLoaded:""
  property string planLoaded:""
  readonly property bool heroReady:assetRoot !== "" && heroLoaded === assetRoot+"hero.png"
  readonly property bool rimReady:assetRoot !== "" && rimLoaded === assetRoot+"hero-rim.png"
  readonly property bool thumbReady:assetRoot !== "" && thumbLoaded === assetRoot+"thumb.png"
  readonly property bool planReady:assetRoot !== "" && planLoaded === assetRoot+"top-down.png"
  readonly property var credit:DeviceAssets.credit(folder,metadata)
  property bool silhouetteReady:false
  property string selectedControl:""
  signal recheck(bool all)
  function setFolderImages(name,state) {
    if (folderImages[name] === state) return
    const next=Object.assign({},folderImages); next[name]=state; folderImages=next
  }
  readonly property bool showCallouts:hotspots && width >= 660
  readonly property bool showInset:showCallouts && Style.windowWidth >= 1100 && thumbReady && normalize(metadata.inset_hotspots || []).length >= 3
  readonly property real calloutWidth:184
  readonly property real hitSize:22
  readonly property bool hasImage:photo.status === Image.Ready
  readonly property var fallback:[{name:"middle",label:"Middle click",x:0.276,y:0.244,side:"left"},{name:"thumb_wheel",label:"Thumb wheel",x:0.627,y:0.565,side:"left"},{name:"gesture",label:"Gesture button",x:0.449,y:0.667,side:"left"},{name:"mode_shift",label:"Wheel mode",x:0.479,y:0.205,side:"right"},{name:"forward",label:"Forward",x:0.691,y:0.568,side:"right"},{name:"back",label:"Back",x:0.79,y:0.561,side:"right"}]
  // Only controls this mouse reports get a hotspot (an MX Vertical has no thumb wheel).
  readonly property var points:DeviceAssets.reported(normalize(metadata.hotspots || fallback),controller ? controller.device : null,controller && controller.builtInThumbWheel ? ["thumb_wheel"] : [])
  readonly property var placedPoints:placePoints()
  readonly property var probeGeometry:({hitSize:hitSize,callouts:showCallouts,inset:showInset,groupRing:showInset ? {diameter:36,x:sideCluster.x,y:sideCluster.y,line:magnifierLine} : null,frame:{x:frame.x,y:frame.y,width:frame.width,height:frame.height},points:placedPoints.map(function(point) { return {name:point.name,number:point.number,x:point.dotX,y:point.dotY,side:point.side,inset:point.inset,leader:root.leaderRoute(point),labelX:root.labelX(point),labelY:root.labelY(point),labelWidth:calloutWidth,labelHeight:56} })})
  readonly property real paintedWidth:hasImage ? photo.paintedWidth : frame.width*0.72
  readonly property real paintedHeight:hasImage ? photo.paintedHeight : frame.height*0.9
  readonly property var sideCluster:clusterCenter()
  readonly property var magnifierLine:magnifierRoute()
  function clusterCenter() {
    const cluster=points.filter(function(p) { return ["thumb_wheel","forward","back"].indexOf(p.name) >= 0 })
    const x=cluster.length ? cluster.reduce(function(sum,p) { return sum+p.x },0)/cluster.length : 0.69
    const y=cluster.length ? cluster.reduce(function(sum,p) { return sum+p.y },0)/cluster.length : 0.545
    return {x:frame.x+(frame.width-paintedWidth)/2+x*paintedWidth,y:frame.y+(frame.height-paintedHeight)/2+y*paintedHeight}
  }
  function magnifierRoute() {
    const startX=sideCluster.x+18/Math.sqrt(2),startY=sideCluster.y+18/Math.sqrt(2)
    const centerX=inset.x+inset.width/2,centerY=inset.y+inset.height/2
    const dx=startX-centerX,dy=startY-centerY,length=Math.sqrt(dx*dx+dy*dy) || 1
    return {startX:startX,startY:startY,endX:centerX+dx/length*inset.width/2,endY:centerY+dy/length*inset.height/2}
  }
  function leaderRoute(point) {
    const startX=labelX(point)+(point.side === "left" ? calloutWidth : 0),startY=labelY(point)+28
    const elbowX=point.side === "left" ? frame.x-16 : frame.x+frame.width+16
    const dx=elbowX-point.dotX,dy=startY-point.dotY,length=Math.sqrt(dx*dx+dy*dy) || 1
    const clearance=(selectedControl === point.name ? 14 : 11)+4
    return {startX:startX,startY:startY,elbowX:elbowX,elbowY:startY,endX:point.dotX+dx/length*clearance,endY:point.dotY+dy/length*clearance}
  }
  function tetherEnd(point) {
    const dx=point.anchorX-point.dotX,dy=point.anchorY-point.dotY,length=Math.sqrt(dx*dx+dy*dy) || 1
    const clearance=(selectedControl === point.name ? 14 : 11)+4
    return {x:point.dotX+dx/length*clearance,y:point.dotY+dy/length*clearance,visible:length > clearance}
  }
  signal chosen(string name)
  implicitWidth:800; implicitHeight:480
  function normalize(value) {
    const items=Array.isArray(value) ? value : Object.keys(value && typeof value === "object" ? value : {}).map(function(name) { return Object.assign({name:name},value[name]) })
    return items.filter(function(p) { return p && typeof p.name === "string" && typeof p.x === "number" && isFinite(p.x) && typeof p.y === "number" && isFinite(p.y) }).map(function(p) { const name=p.name === "wheel_mode" ? "mode_shift" : p.name; return Object.assign({},p,{name:name,label:p.label || name.replace(/_/g," "),x:Math.max(0,Math.min(1,p.x)),y:Math.max(0,Math.min(1,p.y)),side:p.side === "right" ? "right" : "left"}) })
  }
  function focusStops() {
    let dots=0,labels=0
    for (let i=0;i<markers.count;i++) { const item=markers.itemAt(i); if (item) { dots+=item.dotTabStop ? 1 : 0; labels+=item.labelTabStop ? 1 : 0 } }
    return {dots:dots,labels:labels}
  }
  function focusProbe() {
    if (!markers.count) return ({order:[],rings:false})
    let item=markers.itemAt(0).dotControl, order=[], rings=true
    for (let n=0;n<markers.count;n++) {
      item.forceActiveFocus(Qt.TabFocusReason)
      order.push(item.objectName)
      rings=rings && item.visualFocus
      let next=item
      for (let i=0;i<500;i++) { next=next.nextItemInFocusChain(true); if (next.activeFocusOnTab && next.visible && next.enabled) break }
      item=next
    }
    return {order:order,rings:rings}
  }
  function labelX(point) { return point.side === "left" ? 0 : width-calloutWidth }
  function labelY(point) {
    const side=placedPoints.filter(function(p) { return p.side === point.side })
    const position=side.findIndex(function(p) { return p.name === point.name })
    return Math.max(8,Math.min(height-56,frame.y+(frame.height-side.length*72)/2+position*72))
  }
  function placePoints() {
    const imageWidth=paintedWidth, imageHeight=paintedHeight
    let placed=points.map(function(p) { const x=frame.x+(frame.width-imageWidth)/2+p.x*imageWidth,y=frame.y+(frame.height-imageHeight)/2+p.y*imageHeight; return Object.assign({},p,{anchorX:x,anchorY:y,dotX:x,dotY:y,inset:false}) })
    // Resolve controls on the same horizontal strip in left-to-right order,
    // then number the resulting side columns by vertical reading order.
    for (let i=0;i<placed.length;i++) for (let j=i+1;j<placed.length;j++) {
      const a=placed[i],b=placed[j]
      if (a.side === b.side && Math.abs(a.y-b.y)<0.025) {
        const middle=(a.dotY+b.dotY)/2
        a.dotY=middle+(a.dotX < b.dotX ? -13 : 13); b.dotY=middle+(a.dotX < b.dotX ? 13 : -13)
      }
    }
    placed.sort(function(a,b) { return a.side === b.side ? a.dotY-b.dotY : a.side === "left" ? -1 : 1 })
    placed.forEach(function(p,i) { p.number=i+1 })
    if (showInset) {
      const closeups=normalize(metadata.inset_hotspots).filter(function(p) { return p.name !== "gesture" })
      placed.forEach(function(p) { const detail=closeups.find(function(v) { return v.name === p.name }); if (detail) { p.dotX=inset.x+detail.x*inset.width; p.dotY=inset.y+detail.y*inset.height; p.anchorX=p.dotX; p.anchorY=p.dotY; p.inset=true } })
    }
    const insetPoints=placed.filter(function(p) { return p.inset }).sort(function(a,b) { return a.anchorX-b.anchorX })
    if (insetPoints.length > 1) {
      const mean=insetPoints.reduce(function(sum,p) { return sum+p.anchorX },0)/insetPoints.length
      const half=(insetPoints.length-1)*20
      const center=Math.max(inset.x+half+12,Math.min(inset.x+inset.width-half-12,mean))
      insetPoints.forEach(function(p,index) { p.dotX=center+(index-(insetPoints.length-1)/2)*40 })
    }
    for (let pass=0;pass<12;pass++) for (let i=0;i<placed.length;i++) for (let j=i+1;j<placed.length;j++) {
      if (placed[i].inset !== placed[j].inset) continue
      const dx=placed[j].dotX-placed[i].dotX,dy=placed[j].dotY-placed[i].dotY,d=Math.sqrt(dx*dx+dy*dy),minimum=placed[i].inset ? 40 : hitSize+2
      if (d<minimum) { const shift=(minimum-d)/2,ux=d ? dx/d : 1,uy=d ? dy/d : 0; placed[i].dotX-=ux*shift; placed[i].dotY-=uy*shift; placed[j].dotX+=ux*shift; placed[j].dotY+=uy*shift }
    }
    return placed
  }
  function choose(name) { selectedControl=name; chosen(name) }
  // One probe per candidate folder: does it hold a hero or top image?
  Repeater {
    model:root.folders
    Item {
      id:probe; required property string modelData; visible:false
      readonly property string base:Quickshell.shellDir+"/assets/devices/"+modelData+"/"
      property var hasHero:undefined
      property var hasTop:undefined
      readonly property var found:hasHero === true || hasTop === true ? true : hasHero === false && hasTop === false ? false : undefined
      onFoundChanged:if (found !== undefined) root.setFolderImages(modelData,found)
      Component.onCompleted:if (found !== undefined) root.setFolderImages(modelData,found)
      FileView { id:probeHero; path:probe.base+"hero.png"; preload:true; watchChanges:true; printErrors:false; onFileChanged:reload(); onLoaded:probe.hasHero=true; onLoadFailed:probe.hasHero=false }
      FileView { id:probeTop; path:probe.base+"top.png"; preload:true; watchChanges:true; printErrors:false; onFileChanged:reload(); onLoaded:probe.hasTop=true; onLoadFailed:probe.hasTop=false }
      // A folder already found is reloaded only when the shown pictures are incomplete.
      Connections { target:root; function onRecheck(all) { if (all || probe.found !== true) { probeHero.reload(); probeTop.reload() } } }
    }
  }
  FileView { path:root.assetRoot ? root.assetRoot+"hotspots.json" : ""; preload:true; watchChanges:true; printErrors:false; onFileChanged:reload(); onLoaded:{ let data; try { data=JSON.parse(text()) } catch(error) { data=({placeholder:true}) } root.loadedMetadata={path:path,data:data} } onLoadFailed:root.loadedMetadata={path:path,data:({placeholder:true})} }
  FileView { id:heroFile; path:root.assetRoot ? root.assetRoot+"hero.png" : ""; preload:true; watchChanges:true; printErrors:false; onFileChanged:reload(); onLoaded:root.heroLoaded=path; onLoadFailed:if (root.heroLoaded === path) root.heroLoaded="" }
  FileView { id:rimFile; path:root.assetRoot ? root.assetRoot+"hero-rim.png" : ""; preload:true; watchChanges:true; printErrors:false; onFileChanged:reload(); onLoaded:root.rimLoaded=path; onLoadFailed:if (root.rimLoaded === path) root.rimLoaded="" }
  FileView { id:thumbFile; path:root.assetRoot ? root.assetRoot+"thumb.png" : ""; preload:true; watchChanges:true; printErrors:false; onFileChanged:reload(); onLoaded:root.thumbLoaded=path; onLoadFailed:if (root.thumbLoaded === path) root.thumbLoaded="" }
  FileView { id:planFile; path:root.assetRoot ? root.assetRoot+"top-down.png" : ""; preload:true; watchChanges:true; printErrors:false; onFileChanged:reload(); onLoaded:root.planLoaded=path; onLoadFailed:if (root.planLoaded === path) root.planLoaded="" }
  FileView { path:Quickshell.shellDir+"/assets/devices/silhouette.png"; preload:true; printErrors:false; onLoaded:root.silhouetteReady=true; onLoadFailed:root.silhouetteReady=false }
  // Pictures added while the app runs (or a folder that gains one) show up within a few seconds.
  // A preferred folder that is still missing keeps being probed even while a complete
  // fallback is shown, so a model's own pictures added later replace the fallback.
  readonly property bool incomplete:!heroReady || !thumbReady
  readonly property bool probing:incomplete || DeviceAssets.preferredMissing(folders,chosenFolder)
  Timer { interval:5000; running:root.probing; repeat:true; onTriggered:{ root.recheck(root.incomplete); if (root.incomplete && root.assetRoot) { heroFile.reload(); rimFile.reload(); thumbFile.reload(); planFile.reload() } } }
  Item {
    id:frame
    width:Math.max(0,root.showCallouts ? root.width-2*(root.calloutWidth+32) : Math.min(840,root.width-16))
    height:Math.max(0,Math.min(root.height-(root.hotspots ? 48 : 0),width/(root.view === "top-down" && root.planReady ? 0.75 : 4/3)))
    anchors.horizontalCenter:parent.horizontalCenter
    y:root.showCallouts ? 32 : (root.height-height)/2
    Image {
      id:photo; anchors.fill:parent; fillMode:Image.PreserveAspectFit; asynchronous:true; mipmap:true
      source:root.view === "top-down" && root.planReady ? root.assetRoot+(root.metadata.top_down_image || "top-down.png") : root.heroReady ? root.assetRoot+(Theme.luminance(Theme.background) < 0.45 && root.rimReady ? root.metadata.image_dark || "hero-rim.png" : root.metadata.image || "hero.png") : root.metadata.placeholder !== true && root.metadata.hotspots ? root.assetRoot+(root.metadata.image || "top.png") : ""
    }
    Canvas {
      id:silhouette; anchors.fill:parent; visible:!root.hasImage && root.silhouetteReady; opacity:0.45
      readonly property string imagePath:Quickshell.shellDir+"/assets/devices/silhouette.png"
      Component.onCompleted:loadImage(imagePath)
      onImageLoaded:requestPaint(); onWidthChanged:requestPaint(); onHeightChanged:requestPaint(); onVisibleChanged:requestPaint()
      onPaint: {
        const ctx=getContext("2d"); ctx.clearRect(0,0,width,height)
        if (!isImageLoaded(imagePath)) return
        // Plan-view outline (900x1200, 3:4): keep its shape and keep it quiet, at most 200 px tall.
        const h=Math.min(height,width/0.75,200),w=h*0.75
        ctx.globalCompositeOperation="source-over"; ctx.drawImage(imagePath,(width-w)/2,(height-h)/2,w,h)
        ctx.globalCompositeOperation="source-in"; ctx.fillStyle=Theme.muted; ctx.fillRect(0,0,width,height); ctx.globalCompositeOperation="source-over"
      }
      Connections { target:Theme; function onMutedChanged() { silhouette.requestPaint() } }
    }
    Rectangle { anchors.centerIn:parent; width:96; height:96; radius:12; color:Theme.raised; visible:!root.hasImage && !root.silhouetteReady; Icon { anchors.centerIn:parent; name:"mouse"; width:48; height:48; color:Theme.muted } }
  }
  Shape { anchors.fill:parent; visible:root.showInset
    ShapePath { strokeColor:Theme.alpha(Theme.foreground,0.28); strokeWidth:1; fillColor:"transparent"
      startX:root.magnifierLine.startX; startY:root.magnifierLine.startY
      PathLine { x:root.magnifierLine.endX; y:root.magnifierLine.endY }
    }
  }
  Item {
    id:inset; visible:root.showInset
    x:frame.x+frame.width-168; y:Math.max(0,Math.min(root.height-184,frame.y+frame.height-80)); width:168; height:168
    Image { anchors.fill:parent; source:root.thumbReady ? root.assetRoot+(root.metadata.inset_image || "thumb.png") : ""; fillMode:Image.PreserveAspectFit; mipmap:true }
    Rectangle { anchors.fill:parent; radius:width/2; color:"transparent"; border.width:1; border.color:Theme.border }
  }
  Button {
    visible:root.showInset; focusable:false; focusPolicy:Qt.NoFocus; width:36; height:36; padding:0; leftPadding:0; rightPadding:0
    Accessible.name:"Side buttons"; tooltipText:"Side buttons: Back, Forward, Thumb wheel"
    x:root.sideCluster.x-width/2; y:root.sideCluster.y-height/2; onClicked:root.choose("back")
    background:Rectangle { radius:18; color:"transparent"; border.width:1; border.color:Theme.alpha(Theme.accent,0.4) }
  }
  Repeater {
    id:markers; model:root.hotspots ? root.placedPoints : []
    Item {
      id:marker; required property var modelData; anchors.fill:parent
      readonly property var dotControl:hotspot
      readonly property bool dotTabStop:hotspot.activeFocusOnTab
      readonly property bool labelTabStop:callout.activeFocusOnTab
      readonly property bool available:root.controller && root.controller.available(modelData.name)
      readonly property bool builtIn:modelData.name === "thumb_wheel" && root.controller && root.controller.builtInThumbWheel
      readonly property bool overridden:root.controller && !builtIn && root.controller.controlOverridden(modelData.name)
      readonly property var action:root.controller ? root.controller.effective("buttons."+modelData.name,null) : null
      readonly property string actionIcon:action ? ({key:"keyboard",automation:"routine",command:"terminal",desktop:"windows",mouse:"mouse",hyprland:"windows"}[action.type] || "") : ""
      readonly property string summary:available || builtIn ? root.controller.assignment(modelData.name) : "Unavailable"
      readonly property var leader:root.leaderRoute(modelData)
      readonly property var tether:root.tetherEnd(modelData)
      readonly property bool highlighted:hotspot.hovered || callout.hovered || hotspot.activeFocus || root.selectedControl === modelData.name
      Shape {
        anchors.fill:parent; visible:root.showCallouts && !marker.modelData.inset
        ShapePath {
          strokeColor:Theme.alpha(Theme.foreground,0.28); strokeWidth:1; fillColor:"transparent"
          startX:marker.leader.startX; startY:marker.leader.startY
          PathLine { x:marker.leader.elbowX; y:marker.leader.elbowY }
          PathLine { x:marker.leader.endX; y:marker.leader.endY }
        }
      }
      Shape { anchors.fill:parent; visible:marker.tether.visible
        ShapePath { strokeColor:Theme.accent; strokeWidth:1; fillColor:"transparent"; startX:marker.modelData.anchorX; startY:marker.modelData.anchorY; PathLine { x:marker.tether.x; y:marker.tether.y } }
      }
      Button {
        id:hotspot; objectName:"hotspot-"+marker.modelData.number; x:marker.modelData.dotX-width/2; y:marker.modelData.dotY-height/2; width:root.selectedControl === marker.modelData.name ? 28 : 22; height:width; padding:0; leftPadding:0; rightPadding:0
        enabled:marker.available || marker.builtIn; Accessible.name:marker.modelData.number+". "+marker.modelData.label; Accessible.description:marker.summary; tooltipText:marker.modelData.label+": "+marker.summary
        Behavior on width { NumberAnimation { duration:160; easing.type:Easing.OutCubic } }
        background:Rectangle { radius:width/2; color:root.selectedControl === marker.modelData.name ? Theme.accent : Theme.surface; border.width:hotspot.hovered ? 2 : 1.5; border.color:Theme.accent; FocusRing { control:hotspot; radius:parent.radius+4 } }
        contentItem:Label { text:marker.modelData.number; color:root.selectedControl === marker.modelData.name ? Theme.accentText : Theme.foreground; horizontalAlignment:Text.AlignHCenter; verticalAlignment:Text.AlignVCenter; font.pixelSize:11; font.weight:Font.DemiBold }
        onClicked:root.choose(marker.modelData.name)
      }
      Button {
        id:callout; focusable:false; focusPolicy:Qt.NoFocus; Accessible.ignored:true; visible:root.showCallouts; x:root.labelX(marker.modelData); y:root.labelY(marker.modelData); width:root.calloutWidth; height:56
        enabled:marker.available || marker.builtIn; padding:8; leftPadding:12; rightPadding:12; bordered:true; fill:Theme.surface; tooltipText:marker.summary
        contentItem:Column { spacing:4
          Label { width:parent.width; text:marker.modelData.number+" · "+marker.modelData.label+(marker.overridden ? " · App" : ""); font.pixelSize:Style.fontCaption; color:Theme.muted; maximumLineCount:1; elide:Text.ElideRight }
          Row { width:parent.width; spacing:8
            Icon { width:16; height:16; name:marker.actionIcon; visible:marker.actionIcon !== ""; anchors.verticalCenter:parent.verticalCenter }
            Label { width:parent.width-(marker.actionIcon ? 24 : 0); text:marker.summary; font.pixelSize:Style.fontHeading; font.weight:Font.DemiBold; maximumLineCount:1; elide:Text.ElideRight }
          }
        }
        background:Rectangle { color:Theme.surface; radius:8; border.color:marker.highlighted ? Theme.accent : Theme.border }
        onClicked:root.choose(marker.modelData.name)
      }
    }
  }
  Label { anchors.bottom:parent.bottom; width:parent.width; text:root.hotspots ? "Choose a dot to customize" : ""; horizontalAlignment:Text.AlignHCenter; color:Theme.muted; font.pixelSize:Style.fontCaption }
}

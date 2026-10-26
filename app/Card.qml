pragma ComponentBehavior: Bound
import QtQuick
Rectangle {
  id:root
  color:Theme.surface
  border.color:Style.normalBorderColor
  radius:Style.cornerRadius
  // Canvas shadows also render in software/offscreen previews.
  Canvas {
    id:shadow; z:-1; x:-16; y:-16; width:root.width+32; height:root.height+32
    visible:Theme.luminance(Theme.background) > 0.45
    onWidthChanged:requestPaint(); onHeightChanged:requestPaint(); onVisibleChanged:requestPaint()
    function rounded(ctx) {
      const x=16,y=16,w=root.width,h=root.height,r=root.radius
      ctx.beginPath(); ctx.moveTo(x+r,y); ctx.lineTo(x+w-r,y); ctx.quadraticCurveTo(x+w,y,x+w,y+r)
      ctx.lineTo(x+w,y+h-r); ctx.quadraticCurveTo(x+w,y+h,x+w-r,y+h)
      ctx.lineTo(x+r,y+h); ctx.quadraticCurveTo(x,y+h,x,y+h-r); ctx.lineTo(x,y+r); ctx.quadraticCurveTo(x,y,x+r,y); ctx.closePath()
    }
    onPaint: {
      const ctx=getContext("2d"); ctx.clearRect(0,0,width,height)
      ctx.fillStyle=Theme.surface; ctx.shadowOffsetX=0
      ctx.shadowOffsetY=4; ctx.shadowBlur=12; ctx.shadowColor="rgba(0,0,0,0.04)"; rounded(ctx); ctx.fill()
      ctx.shadowOffsetY=1; ctx.shadowBlur=2; ctx.shadowColor="rgba(0,0,0,0.06)"; rounded(ctx); ctx.fill()
    }
    Connections { target:Theme; function onSurfaceChanged() { shadow.requestPaint() } }
  }
}

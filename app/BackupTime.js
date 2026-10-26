.pragma library
function date(value) {
  return new Date(String(value).replace(/T(\d\d)-(\d\d)-(\d\d)/,"T$1:$2:$3"))
}
function day(value) {
  const d=date(value), now=new Date(), yesterday=new Date(now)
  yesterday.setDate(now.getDate()-1)
  if (isNaN(d.getTime())) return String(value)
  if (d.toDateString() === now.toDateString()) return "Today"
  if (d.toDateString() === yesterday.toDateString()) return "Yesterday"
  return d.toLocaleDateString(Qt.locale(),d.getFullYear() === now.getFullYear() ? "MMM d" : "MMM d, yyyy")
}
function format(value) {
  const d=date(value)
  return isNaN(d.getTime()) ? String(value) : day(value) + ", " + d.toLocaleTimeString(Qt.locale(),"h:mm AP")
}

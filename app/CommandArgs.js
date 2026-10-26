.pragma library
// POSIX-style quoting only. No shell expansion, execution, or interpolation.
function split(text) {
  if (text.trim().charAt(0) === "[") return JSON.parse(text)
  let args=[], word="", quote="", started=false
  for (let i=0;i<text.length;i++) {
    const ch=text[i]
    if (quote === "'") { if (ch === "'") quote=""; else word+=ch; continue }
    if (ch === "\\") {
      if (i+1 >= text.length) throw new Error("Finish the escaped argument.")
      const next=text[++i]
      if (quote === '"' && next !== '"' && next !== "\\") word+="\\"
      word+=next; started=true; continue
    }
    if (quote === '"') { if (ch === '"') quote=""; else word+=ch; continue }
    if (ch === "'" || ch === '"') { quote=ch; started=true; continue }
    if (/\s/.test(ch)) { if (started) { args.push(word); word=""; started=false } }
    else { word+=ch; started=true }
  }
  if (quote) throw new Error("Close the quoted argument.")
  if (started) args.push(word)
  return args
}
function format(args) { return args.map(function(arg) { return /^[\w./:-]+$/.test(arg) ? arg : "'" + arg.replace(/'/g,"'\\''") + "'" }).join(" ") }

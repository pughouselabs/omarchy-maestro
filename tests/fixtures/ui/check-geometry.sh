#!/usr/bin/env bash
set -euo pipefail
repo=$(cd -- "$(dirname -- "$0")/../../.." && pwd)
source "$repo/tests/fixtures/ui/isolation.sh"
qs -p "$repo/app" ipc --any-display call maestro fixtureStatus | python3 -c '
import json, math, sys
snapshot=json.load(sys.stdin)
g=snapshot["design"]["hotspots"]
assert snapshot["design"]["focusStops"] == {"dots":6,"labels":0}, snapshot["design"]["focusStops"]
assert "danish_blends" in snapshot["design"]["credit"]
p=g["points"]
assert sorted(v["number"] for v in p) == list(range(1,7))
assert [v["name"] for v in p] == ["middle","thumb_wheel","gesture","mode_shift","forward","back"]
if g.get("inset"):
    inset = [v for v in p if v.get("inset")]
    assert len(inset) == 3
    for i,a in enumerate(inset):
        for b in inset[i+1:]:
            assert math.hypot(a["x"]-b["x"],a["y"]-b["y"]) >= 39.9
for i,a in enumerate(p):
    for b in p[i+1:]:
        assert math.hypot(a["x"]-b["x"], a["y"]-b["y"]) >= g["hitSize"]+1.9, (a,b)
if g["callouts"]:
    frame=g["frame"]
    for a in p:
        assert a["labelX"]+a["labelWidth"] <= frame["x"] or a["labelX"] >= frame["x"]+frame["width"]
    for side in ("left","right"):
        rows=sorted((v for v in p if v["side"] == side), key=lambda v:v["number"])
        for a,b in zip(rows,rows[1:]):
            assert a["labelY"]+a["labelHeight"] <= b["labelY"], (a,b)
    def cross(a,b,c): return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
    lines=[]
    for a in (point for point in p if not point.get("inset")):
        route=a["leader"]
        assert route["startY"] == route["elbowY"], route
        assert math.hypot(route["endX"]-a["x"], route["endY"]-a["y"]) >= 14.9
        lines.append(((route["startX"],route["startY"]),(route["elbowX"],route["elbowY"])))
        lines.append(((route["elbowX"],route["elbowY"]),(route["endX"],route["endY"])))
    for i,(a,b) in enumerate(lines):
        for c,d in lines[i+1:]:
            assert not (cross(a,b,c)*cross(a,b,d)<0 and cross(c,d,a)*cross(c,d,b)<0), (a,b,c,d)
print("PASS: six numbered controls, separate hit targets, one tab stop each, uncrossed nonoverlapping callouts, metadata credit")
'

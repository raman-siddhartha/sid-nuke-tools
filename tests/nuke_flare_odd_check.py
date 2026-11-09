# Odd-size format check inside Nuke (works in Non-Commercial mode):
#     "C:/Program Files/Nuke17.1v3/Nuke17.1.exe" --nc -t tests/nuke_flare_odd_check.py
# 2048x858 at Quarter resolution: the working frame (512 x 214.5) does not
# divide evenly, so this checks that the flare comes back to the exact plate
# format (bbox) and that axial placement survives the rounding. Touches about
# 4 Python Node objects (root, the test source, the LensFlare group, plus
# selectedNode inside make_lens_flare). Exits non-zero on failure.
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import nuke  # noqa: E402

FAILS = []


def check(cond, msg):
    print(("PASS  " if cond else "FAIL  ") + msg)
    if not cond:
        FAILS.append(msg)


W, H = 2048, 858
nuke.addFormat("%d %d 1 flareodd" % (W, H))
nuke.root()["format"].setValue("flareodd")
P = (1500.5, 600.5)
nuke.tcl("""
Constant { inputs 0 channels rgba color {0.02 0.02 0.02 0.5} format "%(w)d %(h)d 0 0 %(w)d %(h)d 1 flareodd" }
Expression {
 expr0 {hypot(x+0.5-%(x)s,y+0.5-%(y)s)<8?5:r}
 expr1 {hypot(x+0.5-%(x)s,y+0.5-%(y)s)<8?5:g}
 expr2 {hypot(x+0.5-%(x)s,y+0.5-%(y)s)<8?5:b}
 expr3 {a}
 name flareTestSrc
}
""" % {"w": W, "h": H, "x": P[0], "y": P[1]})
src = nuke.toNode("flareTestSrc")
src.setSelected(True)

import sid_lens_flare as lf  # noqa: E402

g = lf.make_lens_flare()
g["flareRes"].setValue("Quarter")
g["outputMode"].setValue("Flare Only")
for name in ("ghostsOn", "starOn", "glareOn"):
    g[name].setValue(False)
g["irisOn"].setValue(True)


def s(x, y, ch="g"):
    return nuke.sample(g, ch, x, y)


bb = g.bbox()
bb = (bb.x(), bb.y(), bb.w(), bb.h())
check(bb == (0, 0, W, H), "2048x858 Quarter: Flare Only bbox equals the format: x, y, w, h = %s" % (bb,))

POS = -0.6
for c in ((W / 2.0, H / 2.0), (700.0, 300.0)):
    g["opticalCenter"].setValue(list(c))
    px, py = c[0] + POS * (P[0] - c[0]), c[1] + POS * (P[1] - c[1])
    half_w = 90.0                     # Iris radius 60 plate px + margin
    wsum = cx = cy = 0.0
    y = py - half_w
    while y <= py + half_w:
        x = px - half_w
        while x <= px + half_w:
            w = max(s(x, y), 0.0)
            wsum += w; cx += w * x; cy += w * y
            x += 3.0
        y += 3.0
    mx, my = cx / max(wsum, 1e-12), cy / max(wsum, 1e-12)
    err = math.hypot(mx - px, my - py)
    check(wsum > 0 and err < 3.0, "Quarter 2048x858, centre %s: Iris centroid (%.1f, %.1f) within 3px of "
          "predicted (%.1f, %.1f), error %.2fpx" % (c, mx, my, px, py, err))

print("\n%d failure(s)" % len(FAILS))
sys.exit(1 if FAILS else 0)

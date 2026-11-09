# Integration check inside Nuke (works in Non-Commercial mode):
#     "C:/Program Files/Nuke17.1v3/Nuke17.1.exe" --nc -t tests/nuke_flare_check.py
# Touches about 6 Python Node objects (root, the test source, the LensFlare
# group, the internal starKernel and hotspot nodes, plus selectedNode inside make_lens_flare),
# well under the NC 10-node limit. Exits non-zero on failure.
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import nuke  # noqa: E402
import sid_lens_optics as _o  # noqa: E402

FAILS = []


def check(cond, msg):
    print(("PASS  " if cond else "FAIL  ") + msg)
    if not cond:
        FAILS.append(msg)


nuke.addFormat("640 360 1 flaretest")
nuke.root()["format"].setValue("flaretest")
SRC_X, SRC_Y, SRC_V = 480.5, 250.5, 5.0
nuke.tcl("""
Constant { inputs 0 channels rgba color {0.02 0.02 0.02 0.5} format "640 360 0 0 640 360 1 flaretest" }
Expression {
 expr0 {hypot(x+0.5-%(x)s,y+0.5-%(y)s)<6?%(v)s:r}
 expr1 {hypot(x+0.5-%(x)s,y+0.5-%(y)s)<6?%(v)s:g}
 expr2 {hypot(x+0.5-%(x)s,y+0.5-%(y)s)<6?%(v)s:b}
 expr3 {a}
 name flareTestSrc
}
""" % {"x": SRC_X, "y": SRC_Y, "v": SRC_V})
src = nuke.toNode("flareTestSrc")
src.setSelected(True)

import sid_lens_flare as lf  # noqa: E402
import sid_flare_elements as fe  # noqa: E402

g = lf.make_lens_flare()


def s(x, y, ch="g"):
    return nuke.sample(g, ch, x, y)


def ghost_centre(slot):
    sc = g["g%dsG" % slot].value()
    return 320 + sc * (SRC_X - 320), 180 + sc * (SRC_Y - 180), sc


DEFAULT_PRESCRIPTION = _o.format_prescription(_o.preset(_o.PRESET_NAMES[0]))


def reset():
    """Restore every knob the checks touch, then re-solve (the flipped-ghost
    block overwrites ghost energies), so no check depends on state left by an
    earlier section."""
    g["lensPreset"].setValue(_o.PRESET_NAMES[0])
    g["customPrescription"].setValue(DEFAULT_PRESCRIPTION)
    for name, val in (("fstop", 2.8), ("ghostCount", 8), ("ghostIntensity", 1.0),
                      ("starIntensity", 0.02), ("glareIntensity", 1e-5), ("blades", 6),
                      ("apRotation", 0.0)):
        g[name].setValue(val)
    g["outputMode"].setValue("Flare over Plate")
    g["flareRes"].setValue("Half")
    for name in ("ghostsOn", "starOn", "glareOn"):
        g[name].setValue(True)
    for name, val in (("starLength", 60.0), ("starThickness", 2.0), ("starFalloff", 1.0),
                      ("starRotation", 0.0), ("starChroma", 1.0), ("starIrregularity", 0.0)):
        g[name].setValue(val)
    for eid, _l, _f, src_default in fe.ELEMENTS:
        g[eid + "On"].setValue(False)
        g[eid + "Intensity"].setValue(fe.DEFAULT_INTENSITY[eid])
        g[eid + "Source"].setValue(src_default)
        g[eid + "Tint"].setValue([1.0, 1.0, 1.0])
        g[eid + "Offset"].setValue([0.0, 0.0])
        for suffix, _lab, kind, _lo, _hi, default, _tip in fe.EXTRA[eid]:   # extras back to defaults
            g[eid + suffix].setValue(int(default) if kind != "d" else default)
    for prefix in list(fe.COLOURED) + ["ghosts"]:
        g[prefix + "ColorMode"].setValue(0)
        g[prefix + "Noise"].setValue(0.0)
        g[prefix + "NoiseSpeed"].setValue(0.0)
        g[prefix + "LightColor"].setValue(1.0)
        g[prefix + "ColorWidth"].setValue(1.0 if prefix in fe.RING_TYPES else 0.35)
        for i, (col, pos) in enumerate(fe.RAMP_DEFAULTS):
            g["%sRamp%d" % (prefix, i)].setValue(list(col))
            g["%sRampPos%d" % (prefix, i)].setValue(pos)
    for prefix in ("ghosts", "star"):
        g[prefix + "Offset"].setValue([0.0, 0.0])
    g["overscan"].setValue(25.0)
    g["opticalCenter"].setValue([320.0, 180.0])
    g["apRoundness"].setValue(0.1)
    lf.solve(g)


def ghosts_only(count):
    g["starIntensity"].setValue(0)
    g["glareIntensity"].setValue(0)
    g["outputMode"].setValue("Flare Only")
    g["ghostCount"].setValue(count)


check(g.input(0) is not None, "auto-connected to selected node")
check(g["status"].value().startswith("EFL 50.0mm"), "status after build: %s" % g["status"].value())

# --- slot 0: position (centroid), dark surround, coating colour ---------------------
reset()
ghosts_only(1)
px, py, sc = ghost_centre(0)
rad = g["g0rad"].value() * 640 / g["sensorWidth"].value()
# Brightness-weighted centroid of the green channel. Slot 0 spans x 516..608,
# y 240..332 in the 640x360 frame, so it is fully inside and unclipped: both axes
# are meaningful without moving the source.
half_w = rad + 10
wsum = cx = cy = 0.0
y = max(0.0, py - half_w)
while y <= min(359.0, py + half_w):
    x = max(0.0, px - half_w)
    while x <= min(639.0, px + half_w):
        w = max(s(x, y), 0.0)
        wsum += w; cx += w * x; cy += w * y
        x += 2.0
    y += 2.0
check(px - half_w >= 0 and px + half_w <= 640 and py - half_w >= 0 and py + half_w <= 360,
      "slot 0 window unclipped by the frame")
# 3px tolerance = 2px sampling grid + about one half-res pixel (the flare is built at
# half resolution and upsampled). The measured error is a steady ~(-1.6, -1.4) px;
# shifting the samples by a pixel-centre convention (+0.5 / +1.0) only reduces it to
# ~(-1.1, -0.9) / (-0.6, -0.4) and there is no principled choice, so the plain
# prediction is kept and the tolerance is not loosened.
err = math.hypot(cx / max(wsum, 1e-12) - px, cy / max(wsum, 1e-12) - py)
check(wsum > 0 and err < 3.0,
      "slot 0 centroid (%.1f, %.1f) within 3px of predicted (%.1f, %.1f), error %.2fpx"
      % (cx / max(wsum, 1e-12), cy / max(wsum, 1e-12), px, py, err))
probes = [(px - rad - 15, py), (px + rad + 15, py), (px, py - rad - 15), (px, py + rad + 15)]
probes = [(x, y) for x, y in probes if 0 <= x < 640 and 0 <= y < 360]
pmax = max((s(x, y) for x, y in probes), default=0.0)
check(len(probes) > 0, "slot 0 dark probes: %d of 4 inside the frame" % len(probes))
check(len(probes) > 0 and pmax < 1e-6,
      "slot 0 dark at %d probes just outside its %.1fpx spot: max %.3g" % (len(probes), rad, pmax))
rgb = [s(px, py, c) for c in "rgb"]
check(max(rgb) / max(min(rgb), 1e-12) > 1.2, "coating gives the ghost a colour: %s" % [round(v, 4) for v in rgb])


# --- flipped (negative-scale) ghost -----------------------------------------------------
def flipped_ghost_checks():
    reset()
    ghosts_only(8)
    neg = next((n for n in range(8) if g["g%dsG" % n].value() < 0), None)
    if neg is None:
        check(False, "no negative-scale ghost slot in the first 8")
        return
    g["ghostCount"].setValue(neg + 1)
    for n in range(neg):          # leave only the flipped slot's energy non-zero
        g["g%deR" % n].setValue(0); g["g%deG" % n].setValue(0); g["g%deB" % n].setValue(0)
    nx, ny, nsc = ghost_centre(neg)
    check(nx < 320 and ny < 180, "negative-scale slot %d lands on the flipped side (%.1f, %.1f)" % (neg, nx, ny))
    check(s(nx, ny) > 1e-4, "flipped ghost is lit: %.4g" % s(nx, ny))
    # Unflipped mirror position c + |s|*(p - c). It must be >20px from the flipped
    # centre, and < 10% of the flipped brightness shows the ghost really is mirrored.
    mx, my = 320 + abs(nsc) * (SRC_X - 320), 180 + abs(nsc) * (SRC_Y - 180)
    check(math.hypot(mx - nx, my - ny) > 20 and s(mx, my) < 0.1 * s(nx, ny),
          "flipped ghost absent at unflipped mirror (%.1f, %.1f): %.3g vs %.3g" % (mx, my, s(mx, my), s(nx, ny)))


flipped_ghost_checks()

# --- zero ghosts, then starburst and glare isolated --------------------------------------
reset()
ghosts_only(0)
peak = max(s(x, y) for x in range(5, 640, 20) for y in range(5, 360, 20))
check(peak == 0.0, "Ghost Count 0 with starburst/glare off gives black: max %.3g" % peak)

g["starIntensity"].setValue(0.02)
star_on = s(SRC_X + 20, SRC_Y)
g["starIntensity"].setValue(0)
star_off = s(SRC_X + 20, SRC_Y)
check(star_on > 1e-3 and star_off < 1e-6,
      "starburst alone lights next to the source: %.3g (off: %.3g)" % (star_on, star_off))
# No "dark far from every spike" control: the starburst tail falls off smoothly
# (still ~1e-4 at 150px even between spikes) and never reaches zero inside the frame.
g["glareIntensity"].setValue(1e-5)
glare_on = s(SRC_X, SRC_Y - 40)
g["glareIntensity"].setValue(0)
glare_off = s(SRC_X, SRC_Y - 40)
# Threshold 1e-4, not 1e-3: glare at its default 1e-5 is subtle (~2.4e-4 measured at
# 40px); the off control at the same point proves the signal comes from the glare.
check(glare_on > 1e-4 and glare_off < 1e-6,
      "glare alone lights 40px below the source: %.3g (off: %.3g)" % (glare_on, glare_off))

# --- alpha -------------------------------------------------------------------------------
reset()
# Only slots 0-1 (radii 46 and 87 px, far from the corner): the outer slots have
# 126..350 px spots that legitimately cover (2, 2) with a faint tail.
ghosts_only(2)
a_g, a_c = s(px, py, "a"), s(2, 2, "a")
check(0.0 <= a_g <= 1.0 and 0.0 <= a_c <= 1.0 and a_g > 0 and abs(a_c) < 1e-6,
      "Flare Only alpha: ghost centre %.4g in (0,1], dark corner %.3g == 0" % (a_g, a_c))

reset()    # Flare over Plate with default ghosts, starburst and glare
p_g, p_c = s(px, py, "a"), s(2, 2, "a")
check(abs(p_g - 0.5) < 1e-6 and abs(p_c - 0.5) < 1e-6,
      "Flare over Plate keeps plate alpha 0.5 (ghost centre %.6g, corner %.6g)" % (p_g, p_c))

# --- preview modes -----------------------------------------------------------------------
reset()
g["outputMode"].setValue("Highlights")
check(abs(s(SRC_X, SRC_Y) - SRC_V * 2 ** 12) < 1.0, "Highlights preview = source x 2^12")
g["outputMode"].setValue("Aperture")
check(s(320, 180, "a") > 0.99 and s(5, 5, "a") < 1e-6, "Aperture preview draws centred shape")

# --- resolution --------------------------------------------------------------------------
reset()
ghosts_only(1)
half = s(px, py)
g["flareRes"].setValue("Full")
full = s(px, py)
check(abs(full - half) / max(full, 1e-9) < 0.05,
      "Full vs Half resolution agree at ghost centre: %.4g vs %.4g" % (full, half))

# --- custom prescription / f-stop clamp ---------------------------------------------------
reset()
g["lensPreset"].setValue("Custom")          # default table = 50mm preset, solves fine
before = g["g0sG"].value()
g["customPrescription"].setValue("not a lens\n")
check("Prescription error, line 1" in g["status"].value(), "bad custom table reported")
check(g["g0sG"].value() == before, "bad custom table keeps the previous solve")

reset()
g["fstop"].setValue(1.2)
check("clamped" in g["status"].value(), "f-stop clamp noted: %s" % g["status"].value())
check(abs(g["effFstop"].value() - 2.0) < 1e-6, "effFstop clamped to 2.0: %s" % g["effFstop"].value())

# --- starburst spike count ----------------------------------------------------------------
# Must follow the blade rule (odd n -> 2n, even n -> n). Reads the diffraction kernel
# itself (one extra Node object, still NC-safe).
reset()
with g:
    kern = nuke.toNode("starKernel")
check(kern is not None, "starKernel found")
if kern is not None:
    kw, kh = kern.width(), kern.height()
    N = 720                      # ring samples: 0.5 degree resolution
    R = 40                       # ring radius in kernel pixels (well inside the kernel)
    for blades in (5, 6):
        g["blades"].setValue(blades)
        ring = [nuke.sample(kern, "g", kw / 2.0 + R * math.cos(2 * math.pi * i / N),
                            kh / 2.0 + R * math.sin(2 * math.pi * i / N)) for i in range(N)]
        top = max(ring)
        # Local maxima above half the ring maximum (0.5 * top ignores weak ripple).
        cand = [i for i in range(N)
                if ring[i] > 0.5 * top and ring[i] >= ring[i - 1] and ring[i] > ring[(i + 1) % N]]
        # Merge ripple/wrap-around splits of one spike: candidates within 10 samples
        # (5 degrees) of the previous one, circularly, belong to the same spike.
        peaks = sum(1 for k, i in enumerate(cand) if (i - cand[k - 1]) % N > 10) if cand else 0
        check(peaks == _o.starburst_spikes(blades),
              "blades %d -> %d starburst spikes (expected %d)" % (blades, peaks, _o.starburst_spikes(blades)))

    # Length must really shorten the spikes (old bug: a 1px floor plus a 1/r^2
    # tail made Length 1 and 10 render identically). Spike at 30 deg for 6 blades.
    g["blades"].setValue(6)
    g["starRotation"].setValue(0.0)

    def along(r):
        a = math.radians(30.0)
        return nuke.sample(kern, "g", kw / 2.0 + r * math.cos(a), kh / 2.0 + r * math.sin(a))

    rel = {}
    for L in (1.0, 10.0, 60.0):
        g["starLength"].setValue(L)
        rel[L] = along(12) / max(along(3), 1e-30)
    check(rel[1.0] < 1e-4 < rel[10.0] < rel[60.0],
          "Length shortens spikes: r12/r3 = %.3g (L1) < %.3g (L10) < %.3g (L60)"
          % (rel[1.0], rel[10.0], rel[60.0]))

# -- Flare elements (v2) ----------------------------------------------------------
# Each element alone (everything else off, Flare Only): off adds exactly 0; on
# lights the expected place clearly more than a control place.
P = (SRC_X, SRC_Y)
C = (320.0, 180.0)


def axial(pos):
    return C[0] + pos * (P[0] - C[0]), C[1] + pos * (P[1] - C[1])


def grid_max():
    return max(s(x, y) for x in range(5, 640, 30) for y in range(5, 360, 30))


def ring_max(cx, cy, r):
    return max(s(cx + r * math.cos(i / 10.0), cy + r * math.sin(i / 10.0)) for i in range(63))


def elements_only(eid):
    reset()
    for name in ("ghostsOn", "starOn", "glareOn"):
        g[name].setValue(False)
    g["outputMode"].setValue("Flare Only")
    if eid:
        g[eid + "On"].setValue(True)


elements_only(None)
check(grid_max() == 0.0, "everything off (ghosts/star/glare switches + all elements) gives black")

ring_dir = (P[0] - C[0], P[1] - C[1])
ring_n = math.hypot(*ring_dir)
ring_r = 0.45 * 360
EXPECT = {
    # eid: (bright point value, control value, description)
    "streak": (lambda: s(P[0] + 60, P[1]), lambda: s(P[0], P[1] + 60), "along the streak vs across it"),
    "spikeBall": (lambda: ring_max(P[0], P[1], 30), lambda: s(5, 5), "rays around the light vs far corner"),
    "shimmer": (lambda: ring_max(P[0], P[1], 25), lambda: s(5, 5), "rays around the light vs far corner"),
    "sparkle": (lambda: s(*P), lambda: s(5, 5), "at the light vs far corner"),
    "glint": (lambda: s(*P), lambda: s(P[0] + 30, P[1]), "core vs off-spike point"),
    "iris": (lambda: s(*axial(-0.6)), lambda: s(*axial(0.6)), "at Position -0.6 vs +0.6"),
    "multiIris": (lambda: max(s(*axial(t / 20.0)) for t in range(-24, 25)), lambda: s(5, 355),
                  "along the axis vs off-axis corner"),
    "rings": (lambda: s(axial(-0.9)[0] + 120, axial(-0.9)[1]), lambda: s(*axial(-0.9)), "on the ring vs its centre"),
    "caustic": (lambda: s(axial(-0.3)[0] + 80, axial(-0.3)[1]), lambda: s(*axial(-0.3)),
                "bright edge vs dim centre"),
    "ringHalo": (lambda: s(C[0] + ring_r * ring_dir[0] / ring_n, C[1] + ring_r * ring_dir[1] / ring_n),
                 lambda: s(*C), "orbital ring (arc facing the light) vs the optical centre"),
    "bloom": (lambda: s(P[0] + 15, P[1]), lambda: s(5, 5), "glow next to the light vs far corner"),
    "wash": (lambda: s(5, 5), lambda: 0.0, "far corner is lifted"),
    "orbs": (lambda: sum(s(x, y) for x in range(330, 640, 10) for y in range(180, 360, 10)),
             lambda: sum(s(x, y) for x in range(0, 310, 10) for y in range(0, 180, 10)),
             "quadrant near the light vs far quadrant"),
}
for eid, (bright, control, what) in EXPECT.items():
    elements_only(eid)
    if eid == "multiIris":
        g["multiIrisCount"].setValue(8)
    b, c = bright(), control()
    check(b > 1e-6 and b > 2.0 * abs(c), "%s on: %s (%.4g vs %.4g)" % (eid, what, b, c))
    g[eid + "On"].setValue(False)
    check(grid_max() == 0.0, "%s off adds nothing" % eid)

# Tint and animation.
elements_only("shimmer")
pt = (P[0] + 20, P[1] + 7)
g["shimmerTint"].setValue([1.0, 0.0, 0.0])
check(s(pt[0], pt[1], "r") > 0 and s(pt[0], pt[1], "g") == 0.0, "Tint red: only red survives")
g["shimmerTint"].setValue([1.0, 1.0, 1.0])
g["shimmerSpeed"].setValue(2.0)
nuke.frame(1)
f1 = s(*pt)
nuke.frame(5)
f5 = s(*pt)
g["shimmerSpeed"].setValue(0.0)
z5 = s(*pt)
nuke.frame(1)
z1 = s(*pt)
check(abs(f1 - f5) > 1e-6 and z1 == z5, "Shimmer animates at Speed 2 (%.4g -> %.4g), still at Speed 0" % (f1, f5))

elements_only("sparkle")
g["sparkleIntensity"].setValue(0.01)
ray = (P[0] + 12, P[1])                       # on the 0-degree ray of the default 4-point sparkle
g["sparkleSpeed"].setValue(2.0)
nuke.frame(1)
f1 = s(*ray)
nuke.frame(5)
f5 = s(*ray)
g["sparkleSpeed"].setValue(0.0)
z5 = s(*ray)
nuke.frame(1)
z1 = s(*ray)
check(f1 > 0 and abs(f1 - f5) > 1e-6 * f1 and z1 == z5,
      "Sparkle twinkles at Speed 2 (%.4g -> %.4g), still at Speed 0" % (f1, f5))

# Each existing-part switch removes exactly that part: (all on) - (X off) == (X only).
probes = [(P[0] + 20, P[1] + 2), (P[0], P[1] - 40), (330, 200), (150, 110), (562, 286)]


def total():
    return [s(x, y) for x, y in probes]


for part in ("ghostsOn", "starOn", "glareOn"):
    reset()
    g["outputMode"].setValue("Flare Only")
    everything = total()
    g[part].setValue(False)
    without = total()
    for other in ("ghostsOn", "starOn", "glareOn"):
        g[other].setValue(other == part)
    alone = total()
    err = max(abs((a - b) - c) for a, b, c in zip(everything, without, alone))
    check(max(alone) > 0 and err <= 1e-4 * max(everything), "%s switch removes exactly that part (err %.3g)" % (part, err))

# Iris is an aperture ghost: stopping down shrinks it (size x 2.8 / effective f-stop).
def iris_width():
    cx, cy = axial(-0.6)
    return sum(1 for d in range(-80, 81) if s(cx + d, cy) > 1e-4)


elements_only("iris")
w28 = iris_width()
g["fstop"].setValue(5.6)
w56 = iris_width()
check(w56 > 0 and abs(w56 / float(w28) - 0.5) < 0.15, "Iris halves when stopping down f/2.8 -> f/5.6 (%d -> %d px)" % (w28, w56))

# Glint: the 45-degree spike (default Angle 45) is much brighter than an off-spike point.
elements_only("glint")
spike = s(P[0] + 20 * math.cos(math.radians(45)), P[1] + 20 * math.sin(math.radians(45)))
off_spike = s(P[0] + 20, P[1])
check(spike > 1e-6 and spike > 5.0 * abs(off_spike),
      "glint kernel: 45-degree spike %.4g > 5x off-spike %.4g" % (spike, off_spike))

# Extreme values stay finite: every Double/Int extra at its slider maximum.
for eid, _l, _f, _s in fe.ELEMENTS:
    elements_only(eid)
    for suffix, _lab, kind, _lo, hi, _default, _tip in fe.EXTRA[eid]:
        if kind == "d" or kind == "i":
            g[eid + suffix].setValue(hi)
    pts = [(5 + 70 * i, 5 + 85 * j) for i in range(9) for j in range(5)] + [P]
    vals = [s(x, y) for x, y in pts]
    check(all(math.isfinite(v) for v in vals) and any(v != 0.0 for v in vals),
          "%s at slider maxima: finite and not all zero (max %.4g)" % (eid, max(vals)))

# -- v3: overscan, optical centre, offset, ring colour, ring/halo, bloom, wash ----

# Overscan: a large Iris is capped by the kernel canvas without overscan
# (Half res canvas 320x180 -> radius cap 86 working px = 172 plate px) but not
# with 25% (cap 131 working px). Size 200 plate px at f/2.8: a point 185 plate
# px from the iris centre is inside the shape only when not capped.
elements_only("iris")
g["irisSize"].setValue(200.0)
ic = axial(-0.6)
probe = (ic[0] + 185, ic[1])
g["overscan"].setValue(0.0)
os0 = s(*probe)
g["overscan"].setValue(25.0)
os25 = s(*probe)
check(os25 > 1e-4 and os25 > 10 * abs(os0),
      "Overscan 25 keeps a large Iris uncropped (185px from centre: %.4g with overscan vs %.4g without)" % (os25, os0))

# Optical centre at Overscan 25: the Iris follows c + Position*(p - c).
elements_only("iris")
g["opticalCenter"].setValue([200.0, 100.0])
c2 = (200.0, 100.0)
pred = (c2[0] - 0.6 * (P[0] - c2[0]), c2[1] - 0.6 * (P[1] - c2[1]))
ok = s(*pred) > 1e-3 and s(*pred) > 5 * abs(s(*axial(-0.6)))
check(ok, "moving Optical Centre moves the Iris to (%.1f, %.1f): %.4g there vs %.4g at the old spot"
      % (pred[0], pred[1], s(*pred), s(*axial(-0.6))))

# Offset moves an element by exactly the set amount (plate px).
elements_only("iris")
g["irisOffset"].setValue([200.0, 0.0])
ic = axial(-0.6)
moved = s(ic[0] + 200, ic[1])
left = s(*ic)
check(moved > 1e-3 and moved > 5 * abs(left), "Iris Offset (200, 0): %.4g at +200px vs %.4g at the old spot" % (moved, left))

# Ring colour system on a Ring: Spectrum puts red outside, violet/blue inside.
def ring_pts():
    rc = axial(-0.9)
    return rc, 120.0


def rb(pt):
    return s(pt[0], pt[1], "r") / max(s(pt[0], pt[1], "b"), 1e-12)


elements_only("rings")
g["ringsCount"].setValue(1)
g["ringsThickness"].setValue(20.0)
g["ringsColorWidth"].setValue(1.0)
rc, rr = ring_pts()
inner, outer = (rc[0] + rr - 8, rc[1]), (rc[0] + rr + 8, rc[1])
g["ringsColorMode"].setValue(1)
check(rb(outer) > 1.5 * rb(inner), "Spectrum: ring outside redder than inside (r/b %.3g vs %.3g)" % (rb(outer), rb(inner)))
g["ringsColorMode"].setValue(2)
check(rb(inner) > 1.5 * rb(outer), "Ramp (default red inside -> blue outside): r/b inside %.3g vs outside %.3g"
      % (rb(inner), rb(outer)))
g["ringsColorMode"].setValue(0)
check(abs(rb(outer) - rb(inner)) < 0.05 * max(rb(outer), 1e-9), "Tint: ring colour uniform across its width")

# Noise breaks up brightness around the ring; Speed animates it.
def around():
    pts = [(rc[0] + rr * math.cos(i * math.pi / 12), rc[1] + rr * math.sin(i * math.pi / 12)) for i in range(24)]
    return [s(x, y) for x, y in pts if 1 <= x < 639 and 1 <= y < 359]


vals = [v for v in around() if 0 <= v]
flat = max(vals) / max(min(vals), 1e-12)
g["ringsNoise"].setValue(1.0)
vals = around()
bumpy = max(vals) / max(min(vals), 1e-12)
check(bumpy > 1.5 * flat, "Noise varies brightness around the ring (max/min %.3g vs %.3g without)" % (bumpy, flat))
g["ringsNoiseSpeed"].setValue(2.0)
pt = (rc[0] + rr, rc[1])
nuke.frame(1)
n1 = s(*pt)
nuke.frame(5)
n5 = s(*pt)
g["ringsNoiseSpeed"].setValue(0.0)
z5 = s(*pt)
nuke.frame(1)
z1 = s(*pt)
check(abs(n1 - n5) > 1e-6 * max(n1, 1e-9) and z1 == z5, "Noise Speed animates (%.4g -> %.4g), still at 0" % (n1, n5))

# Ring / Halo: Arc 1 makes the facing arc dominate more than Arc 0.
def arc_ratio():
    a = s(C[0] + ring_r * ring_dir[0] / ring_n, C[1] + ring_r * ring_dir[1] / ring_n)
    b = s(C[0] - ring_r * ring_dir[0] / ring_n, C[1] - ring_r * ring_dir[1] / ring_n)
    return a / max(b, 1e-12)


elements_only("ringHalo")
g["ringHaloArc"].setValue(0.0)
even = arc_ratio()
g["ringHaloArc"].setValue(1.0)
facing = arc_ratio()
check(facing > 1.5 * even, "Ring/Halo Arc 1 vs 0: facing/opposite %.3g vs %.3g" % (facing, even))

# Ring / Halo in Light mode: a halo ring around the light itself.
elements_only("ringHalo")
g["ringHaloCentre"].setValue(1)
on_ring = s(P[0] - ring_r, P[1])
gap = s(P[0] - ring_r / 2, P[1])
check(on_ring > 1e-6 and on_ring > 3 * abs(gap), "Ring/Halo Light mode: ring around the light (%.4g on ring vs %.4g inside)"
      % (on_ring, gap))

# Wash: Bias 0 is near even over the frame, Bias 1 concentrates toward the light;
# more light in frame -> more wash.
elements_only("wash")
near, far = (P[0] - 20, P[1] - 20), (5, 5)
g["washBias"].setValue(0.0)
r0 = s(*near) / max(s(*far), 1e-12)
w_far = s(*far)
g["washBias"].setValue(1.0)
r1 = s(*near) / max(s(*far), 1e-12)
check(r0 < 3 and r1 > 2 * r0, "Wash Bias 0 near-even (near/far %.3g), Bias 1 toward the light (%.3g)" % (r0, r1))
g["washBias"].setValue(0.0)
g["sourceStops"].setValue(13.0)
check(s(*far) > 1.8 * w_far, "Wash doubles when the light doubles (%.4g -> %.4g)" % (w_far, s(*far)))
g["sourceStops"].setValue(12.0)

# Hotspot: two separated lights -> exactly two hotspot pixels, at the light centres.
src["expr0"].setValue("hypot(x+0.5-160.5,y+0.5-90.5)<6?5:(hypot(x+0.5-480.5,y+0.5-250.5)<10?3:r)")
src["expr1"].setValue("hypot(x+0.5-160.5,y+0.5-90.5)<6?5:(hypot(x+0.5-480.5,y+0.5-250.5)<10?3:g)")
src["expr2"].setValue("hypot(x+0.5-160.5,y+0.5-90.5)<6?5:(hypot(x+0.5-480.5,y+0.5-250.5)<10?3:b)")
elements_only("glint")                        # glint defaults to Hotspot, so the detector runs
with g:
    hot = nuke.toNode("hotspot")
check(hot is not None, "hotspot node found")
if hot is not None:
    hw, hh = hot.width(), hot.height()       # working (half) resolution, overscan-padded canvas
    padx, pady = (hw - 320) // 2, (hh - 180) // 2   # 25% overscan pad at Half res (80, 45)
    peaks = [(x, y) for x in range(hw) for y in range(hh) if nuke.sample(hot, "g", x + 0.5, y + 0.5) > 0]
    near = all(min(math.hypot(2 * (x - padx + 0.5) - lx, 2 * (y - pady + 0.5) - ly)
                   for lx, ly in ((160.5, 90.5), (480.5, 250.5))) < 4
               for x, y in peaks)
    check(len(peaks) == 2 and near, "two lights (one clipped flat) -> exactly 2 hotspots at their centres: %s" % peaks)
    # Energy: each hotspot pixel carries its light's box-summed energy, so the sum over
    # both equals the working-resolution highlight energy (plate-px energy / 4 at Half).
    hot_sum = sum(nuke.sample(hot, "g", x + 0.5, y + 0.5) for x, y in peaks)
    expect_e = (5 * math.pi * 6 ** 2 + 3 * math.pi * 10 ** 2) * 4096 / 4.0
    check(abs(hot_sum - expect_e) < 0.05 * expect_e,
          "hotspot energy %.5g within 5%% of the lights' working-res energy %.5g" % (hot_sum, expect_e))

    # Big clipped light: a flat disc far wider than a point must still give ONE hotspot, near its centre.
    DX, DY = 420.5, 200.5
    for ch in ("expr0", "expr1", "expr2"):
        src[ch].setValue("hypot(x+0.5-%s,y+0.5-%s)<30?3:%s" % (DX, DY, "rgb"[int(ch[-1])]))
    elements_only("glint")
    big = [(x, y) for x in range(hw) for y in range(hh) if nuke.sample(hot, "g", x + 0.5, y + 0.5) > 0]
    big_near = all(math.hypot(2 * (x - padx + 0.5) - DX, 2 * (y - pady + 0.5) - DY) <= 3 for x, y in big)
    check(len(big) == 1 and big_near, "big clipped disc (radius 30) -> exactly 1 hotspot within 3px of its centre: %s" % big)

# Restore the single-light source for anything that follows.
for ch, c in (("expr0", "r"), ("expr1", "g"), ("expr2", "b")):
    src[ch].setValue("hypot(x+0.5-%s,y+0.5-%s)<6?%s:%s" % (SRC_X, SRC_Y, SRC_V, c))

# Ramp with stops red (0), green (0.33), blue (0.66), white (1) across a thick
# ring: inner side red, middle green/blue, outer side blue/white.
reset()
elements_only("rings")
g["ringsCount"].setValue(1)
g["ringsThickness"].setValue(20.0)
g["ringsColorWidth"].setValue(1.0)
g["ringsColorMode"].setValue(2)
for i, (col, pos) in enumerate((([1, 0, 0], 0.0), ([0, 1, 0], 0.33), ([0, 0, 1], 0.66), ([1, 1, 1], 1.0))):
    g["ringsRamp%d" % i].setValue(col)
    g["ringsRampPos%d" % i].setValue(pos)
rc = axial(-0.9)
rr = 120.0


def rgb_at(dx):
    return [s(rc[0] + rr + dx, rc[1], ch) for ch in "rgb"]


inner_c, mid_c, outer_c = rgb_at(-15.3), rgb_at(0.0), rgb_at(11.4)   # u ~ 0.05, 0.5, 0.83
check(inner_c[0] > inner_c[1] and inner_c[0] > inner_c[2]
      and (mid_c[1] + mid_c[2]) / 2 > mid_c[0]
      and outer_c[2] > outer_c[0],
      "Ramp stops red/green/blue/white: inner %s, middle %s, outer %s"
      % ([round(v, 4) for v in inner_c], [round(v, 4) for v in mid_c], [round(v, 4) for v in outer_c]))

# FFT wrap: a large Iris on a light near the right edge must not leak onto the
# left edge (with Overscan 25; the Overscan 0 value is printed for reference).
for i in range(3):
    src["expr%d" % i].setValue("hypot(x+0.5-620.5,y+0.5-250.5)<6?5:%s" % "rgb"[i])
elements_only("iris")
g["irisPosition"].setValue(1.0)
g["irisSize"].setValue(150.0)
left = (8, 250)
g["overscan"].setValue(0.0)
wrap0 = s(*left)
g["overscan"].setValue(25.0)
wrap25 = s(*left)
check(abs(wrap25) < 1e-6 and s(600, 250) > 1e-4,
      "no FFT wrap to the opposite edge with Overscan 25 (left edge %.3g; %.3g at Overscan 0)" % (wrap25, wrap0))

# Light Colour: a red light gives a red Iris at 1 and a neutral Iris at 0.
for i in range(3):
    src["expr%d" % i].setValue("hypot(x+0.5-480.5,y+0.5-250.5)<6?%s:%s" % ("5" if i == 0 else "0", "rgb"[i]))
elements_only("iris")
ip = axial(-0.6)
g["irisLightColor"].setValue(1.0)
red_ratio = s(ip[0], ip[1], "g") / max(s(ip[0], ip[1], "r"), 1e-12)
g["irisLightColor"].setValue(0.0)
grey_ratio = s(ip[0], ip[1], "g") / max(s(ip[0], ip[1], "r"), 1e-12)
check(red_ratio < 0.05 and grey_ratio > 0.9,
      "Light Colour: red light -> red Iris at 1 (g/r %.3g), neutral at 0 (g/r %.3g)" % (red_ratio, grey_ratio))

# -- v3 review fixes ---------------------------------------------------------------
for ch, c in (("expr0", "r"), ("expr1", "g"), ("expr2", "b")):
    src[ch].setValue("hypot(x+0.5-%s,y+0.5-%s)<6?%s:%s" % (SRC_X, SRC_Y, SRC_V, c))


def set_ramp(prefix, cols, poss=(0.0, 0.33, 0.66, 1.0)):
    for i, (col, pos) in enumerate(zip(cols, poss)):
        g["%sRamp%d" % (prefix, i)].setValue(list(col))
        g["%sRampPos%d" % (prefix, i)].setValue(pos)


def default_ramp(prefix):
    set_ramp(prefix, [c for c, _p in fe.RAMP_DEFAULTS], [p for _c, p in fe.RAMP_DEFAULTS])


def finite_zero(v):
    return math.isfinite(v) and abs(v) < 1e-6


# Zero-sum colour kernels: a pure-red ramp has an all-zero green/blue kernel;
# the centre floor keeps those channels finite and the balance (0) blacks them.
RED4 = [[1, 0, 0]] * 4
elements_only("rings")
g["ringsCount"].setValue(1)
g["ringsColorMode"].setValue(2)
set_ramp("rings", RED4)
rc = axial(-0.9)
on = (rc[0] + 120.0, rc[1])
rv, gv, bv = [s(on[0], on[1], c) for c in "rgb"]
check(rv > 0 and finite_zero(gv) and finite_zero(bv),
      "Rings pure-red ramp: r %.4g > 0, g %.3g, b %.3g finite and 0" % (rv, gv, bv))
default_ramp("rings")

elements_only("iris")
g["irisColorMode"].setValue(2)
g["irisColorWidth"].setValue(1.0)
set_ramp("iris", RED4)
ip = axial(-0.6)
pts = [ip, (ip[0] + 30, ip[1]), (ip[0], ip[1] + 50)]
vals = [[s(x, y, c) for c in "rgb"] for x, y in pts]
check(all(v[0] > 0 for v in vals[:2]) and all(finite_zero(v[1]) and finite_zero(v[2]) for v in vals),
      "Iris pure-red ramp at Colour Width 1: g, b finite and 0 (%s)" % [[round(c, 6) for c in v] for v in vals])
default_ramp("iris")

# Balance = kernel-weighted mean colour: inside the white core the Iris stays neutral.
for mode, label in ((2, "Ramp"), (1, "Spectrum")):
    elements_only("iris")
    g["irisColorMode"].setValue(mode)
    rgbc = [s(ip[0], ip[1], c) for c in "rgb"]
    ratio = max(rgbc) / max(min(rgbc), 1e-12)
    check(min(rgbc) > 0 and ratio < 1.1, "%s Iris centre (white core) neutral: rgb %s, max/min %.3f"
          % (label, [round(c, 4) for c in rgbc], ratio))
    elements_only("caustic")
    g["causticColorMode"].setValue(mode)
    cc = axial(-0.3)
    rgbc = [s(cc[0], cc[1], c) for c in "rgb"]
    ratio = max(rgbc) / max(min(rgbc), 1e-12)
    check(min(rgbc) > 0 and ratio < 1.1, "%s Caustic centre (white core) neutral: rgb %s, max/min %.3f"
          % (label, [round(c, 4) for c in rgbc], ratio))
    # Aperture extremes (default Colour Width): a triangle's inscribed radius
    # (0.5 R) lies inside the white core, 12 blades are near round; roundness 0 / 1.
    for blades, roundness in ((3, 0.0), (3, 1.0), (12, 0.0), (12, 1.0)):
        elements_only("iris")
        g["irisColorMode"].setValue(mode)
        g["blades"].setValue(blades)
        g["apRoundness"].setValue(roundness)
        rgbc = [s(ip[0], ip[1], c) for c in "rgb"]
        ratio = max(rgbc) / max(min(rgbc), 1e-12)
        check(min(rgbc) > 0 and ratio < 1.1, "%s Iris centre neutral at %d blades, roundness %g: rgb %s, max/min %.3f"
              % (label, blades, roundness, [round(c, 4) for c in rgbc], ratio))
    g["apRoundness"].setValue(0.1)

# Ring/Halo Optical Centre mode colours per pixel: no balance in the gain. With
# all stops (0, 0.5, 0) green must be 0.5 x Tint; applying the colour twice
# (per pixel and again as a gain balance) would give ~0.25.
face = (C[0] + ring_r * ring_dir[0] / ring_n, C[1] + ring_r * ring_dir[1] / ring_n)
elements_only("ringHalo")
tint_g = s(face[0], face[1], "g")
g["ringHaloColorMode"].setValue(2)
set_ramp("ringHalo", [[0, 0.5, 0]] * 4)
rv, gv, bv = [s(face[0], face[1], c) for c in "rgb"]
check(gv > 0 and finite_zero(rv) and finite_zero(bv) and 0.4 < gv / max(tint_g, 1e-12) < 0.6,
      "Ring/Halo Optical Centre ramp (0, 0.5, 0): g %.4g = %.3f x Tint %.4g, r %.3g, b %.3g"
      % (gv, gv / max(tint_g, 1e-12), tint_g, rv, bv))
default_ramp("ringHalo")

# Even fields use a fixed reference: Wash at Bias 0 does not depend on Spread.
elements_only("wash")
g["washBias"].setValue(0.0)
g["washSpread"].setValue(100.0)
w100 = s(5, 5)
g["washSpread"].setValue(3000.0)
w3000 = s(5, 5)
check(w100 > 0 and abs(w100 - w3000) / w100 < 0.01,
      "Wash Bias 0 independent of Spread: far corner %.5g (Spread 100) vs %.5g (Spread 3000)" % (w100, w3000))

# Ring/Halo Arc 0: the even field does not depend on Arc Falloff.
elements_only("ringHalo")
g["ringHaloArc"].setValue(0.0)
back = (C[0] - ring_r * ring_dir[0] / ring_n, C[1] - ring_r * ring_dir[1] / ring_n)
g["ringHaloArcFalloff"].setValue(100.0)
e100 = s(*back)
g["ringHaloArcFalloff"].setValue(3000.0)
e3000 = s(*back)
check(e100 > 0 and abs(e100 - e3000) / e100 < 0.01,
      "Ring/Halo Arc 0 independent of Arc Falloff: %.5g vs %.5g" % (e100, e3000))

# Output bbox is clamped to the frame (overscan does not leak).
reset()
g["outputMode"].setValue("Flare Only")
bb = g.bbox()
bb = (bb.x(), bb.y(), bb.w(), bb.h())
check(bb[0] >= 0 and bb[1] >= 0 and bb[0] + bb[2] <= 640 and bb[1] + bb[3] <= 360,
      "Flare Only bbox inside the 640x360 format: x, y, w, h = %s" % (bb,))

print("\n%d failure(s)" % len(FAILS))
sys.exit(1 if FAILS else 0)

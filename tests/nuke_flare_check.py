# Integration check inside Nuke (works in Non-Commercial mode):
#     "C:/Program Files/Nuke17.1v3/Nuke17.1.exe" --nc -t tests/nuke_flare_check.py
# Touches about 5 Python Node objects (root, the test source, the LensFlare
# group, the internal starKernel, plus selectedNode inside make_lens_flare),
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

print("\n%d failure(s)" % len(FAILS))
sys.exit(1 if FAILS else 0)

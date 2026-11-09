# Sid Lens Flare -- flare elements (v3).
#
# Switchable elements of the Lens Flare node:
#   centred on each light : Streak, Spike Ball, Shimmer, Sparkle, Glint, Bloom
#   along the flare axis  : Iris, Multi-Iris, Rings, Caustic
#   ring                  : Ring / Halo (around the optical centre or each light)
#   fixed to the glass    : Lens Orbs, Overscreen Wash
# Each element reads either the padded, downscaled highlights ($hl) or the
# hotspot stream ($hot: one point per light), and ends in an Offset translate.
#
# Overscan: $hl is padded by PADX/PADY working px per side (see
# sid_lens_flare.build_tcl), so every frame position adds the pad and frame
# sizes come from `flareDown.width/height` (the unpadded working frame), not
# from `width/height` (the padded canvas). Pad, frame size, optical centre,
# animation times and colour balances are knobs on the flareGeo NoOp
# (geo_tcl), read by name from the other nodes' expressions.
#
# Ring colour system (Iris, Multi-Iris, Rings, Caustic, Ring/Halo, and the
# ghosts in sid_lens_flare): Colour Mode Tint / Spectrum / Ramp, Colour
# Width, Light Colour, Noise. Coloured modes use an RGB kernel and one
# Convolve2 per channel; Tint keeps the single alpha Convolve2.
#
# Rules: TCL generators are pure string functions; the graph is built in the
# node's single nuke.tcl() call; no internal node lookups from Python; no
# space inside any single {{...}}; temp names never r/g/b/a/x/y/z; gain nodes
# never disabled (an element that is off is disabled upstream AND multiplied
# by its On knob, which is 0); at most 4 temps per Expression.
#
# Strict ASCII.

import math

RES = "pow(0.5,parent.flareRes)"          # plate px -> working px
OS = "parent.overscan/100"
GEO = "flareGeo"                          # helper NoOp holding per-frame constants (geo_tcl)
# The raw expressions live once on the flareGeo NoOp; every other node reads
# its knobs, so these are evaluated once per frame instead of per pixel.
PADX_EXPR = "floor(flareDown.width*%s)" % OS   # overscan pad, working px
PADY_EXPR = "floor(flareDown.height*%s)" % OS
# Plate px -> working px for positions: the real ratio of the working frame to
# the plate (flareDown rounds the working format, e.g. 858 x 0.25 = 214.5),
# which is exactly what flareUp (to box, distort) undoes.
SX_EXPR = "flareDown.width/highlights.width"
SY_EXPR = "flareDown.height/highlights.height"
CX_EXPR = "(parent.opticalCenter.x*%s+%s)" % (SX_EXPR, PADX_EXPR)   # optical centre on the padded canvas
CY_EXPR = "(parent.opticalCenter.y*%s+%s)" % (SY_EXPR, PADY_EXPR)
PADX = GEO + ".padx"
PADY = GEO + ".pady"
FW = GEO + ".fw"                          # unpadded working frame size (flareDown.width)
FH = GEO + ".fh"
CX = GEO + ".cx"
CY = GEO + ".cy"
AA = 0.35                                 # minimum sigma (working px) against aliasing
EVEN_REF_PX = 600.0                       # Ring/Halo even-field reference reach (plate px)
WASH_REF_PX = 800.0                       # Wash even-field reference spread (plate px)
MULTI_IRIS_SLOTS = 8
RING_SLOTS = 4
MAX_SPIKE_RAYS = 64
MAX_SPARKLE_POINTS = 8
MAX_ORBS = 64

# Added to every kernel channel that is normalized (alpha of mono kernels;
# r, g, b and alpha of coloured kernels) so the centre pixel(s) always carry
# a tiny weight: Convolve2 normalize divides each channel by that kernel
# channel's sum, and a zero-sum channel (a ring larger than the canvas, or a
# colour with no green) would blow up.
CENTRE_FLOOR = ("((x+0.5-width/2)*(x+0.5-width/2)+(y+0.5-height/2)*(y+0.5-height/2)<1?0.000001:0)")

SOURCES = ["All highlights", "Hotspot"]

# id, label, family, default source index. `family` documents the grouping
# used in the panel/README; nothing derives from it.
ELEMENTS = (
    ("streak", "Streak", "centred", 1),
    ("spikeBall", "Spike Ball", "centred", 1),
    ("shimmer", "Shimmer", "centred", 1),
    ("sparkle", "Sparkle", "centred", 1),
    ("glint", "Glint", "centred", 1),
    ("bloom", "Bloom", "centred", 0),
    ("iris", "Iris", "axial", 0),
    ("multiIris", "Multi-Iris", "axial", 0),
    ("rings", "Rings", "axial", 0),
    ("caustic", "Caustic", "axial", 0),
    ("ringHalo", "Ring / Halo", "ring", 0),
    ("orbs", "Lens Orbs", "glass", 0),
    ("wash", "Overscreen Wash", "glass", 0),
)

# Elements that get the ring colour system.
COLOURED = ("iris", "multiIris", "rings", "caustic", "ringHalo")

# Extra controls per element: (knob suffix, label, kind, lo, hi, default, tooltip)
# kind: "d" Double, "i" Int, "e:<a|b|c>" Enumeration.
EXTRA = {
    "streak": (
        ("Length", "Length", "d", 1, 2000, 300, "Half-length in plate px."),
        ("Thickness", "Thickness", "d", 0.5, 40, 3, "Width in plate px."),
        ("Angle", "Angle", "d", -180, 180, 0, "0 = horizontal (anamorphic)."),
        ("Falloff", "Falloff", "d", 0.3, 8, 1, "1 = soft tail, 2 = Gaussian, higher = hard end."),
    ),
    "spikeBall": (
        ("Rays", "Rays", "i", 8, MAX_SPIKE_RAYS, 32, "Number of rays. Max 64."),
        ("Length", "Length", "d", 1, 1000, 120, "Plate px."),
        ("Variation", "Length Variation", "d", 0, 1, 0.6, None),
        ("Thickness", "Thickness", "d", 0.5, 10, 1, "Plate px."),
        ("Seed", "Seed", "i", 0, 9999, 0, None),
    ),
    "shimmer": (
        ("Rays", "Rays", "d", 16, 128, 48, "Angular detail of the rays."),
        ("Length", "Length", "d", 1, 1000, 150, "Plate px."),
        ("Speed", "Speed", "d", 0, 10, 1, "Flicker speed; 0 = static."),
        ("Seed", "Seed", "i", 0, 9999, 0, None),
    ),
    "sparkle": (
        ("Points", "Points", "e:4|6|8", 0, 0, 0, None),
        ("Size", "Size", "d", 1, 400, 40, "Plate px."),
        ("Rotation", "Rotation", "d", -180, 180, 0, None),
        ("Speed", "Twinkle Speed", "d", 0, 10, 0, "0 = static."),
    ),
    "glint": (
        ("Size", "Size", "d", 0.5, 100, 6, "Core size in plate px."),
        ("SpikeLength", "Spike Length", "d", 1, 500, 40, "Plate px."),
        ("Angle", "Angle", "d", -180, 180, 45, None),
    ),
    "bloom": (
        ("Size", "Size", "d", 1, 500, 20, "Smallest glow size in plate px (the glow also uses 3x and 9x)."),
        ("Falloff", "Falloff", "d", 0, 1, 0.5, "Weight of the wider glows: 0 = tight, 1 = wide."),
    ),
    "iris": (
        ("Position", "Position", "d", -2, 2, -0.6, "Along the flare axis: 1 = at the light, 0 = optical centre, -1 = mirror."),
        ("Size", "Size", "d", 1, 1000, 60, "Radius in plate px at f/2.8 (shrinks as you stop down). Shapes larger than the canvas are capped."),
        ("Softness", "Softness", "d", 0, 50, 1, "Edge softness in plate px."),
    ),
    "multiIris": (
        ("Count", "Count", "i", 1, MULTI_IRIS_SLOTS, 5, "Number of irises. Max 8."),
        ("Spread", "Spread", "d", 0, 2, 1.2, "Positions are spread over -Spread..+Spread along the axis."),
        ("SizeMin", "Size Min", "d", 1, 1000, 15, "Plate px at f/2.8. Shapes larger than the canvas are capped."),
        ("SizeMax", "Size Max", "d", 1, 1000, 70, "Plate px at f/2.8. Shapes larger than the canvas are capped."),
        ("ColorVar", "Colour Variation", "d", 0, 1, 0.5, None),
        ("Seed", "Seed", "i", 0, 9999, 0, None),
    ),
    "rings": (
        ("Count", "Count", "i", 1, RING_SLOTS, 2, "Number of rings. Max 4."),
        ("Position", "Position", "d", -2, 2, -0.9, "First ring along the flare axis."),
        ("Spacing", "Spacing", "d", -1, 1, 0.25, "Axis distance between rings."),
        ("Radius", "Radius", "d", 2, 1500, 120, "Plate px. Shapes larger than the canvas are capped."),
        ("Thickness", "Thickness", "d", 0.5, 50, 3, "Plate px."),
    ),
    "caustic": (
        ("Position", "Position", "d", -2, 2, -0.3, None),
        ("Size", "Size", "d", 2, 1000, 90, "Radius in plate px. Shapes larger than the canvas are capped."),
        ("Sharpness", "Edge Sharpness", "d", 0.5, 10, 3, "Higher = thinner, brighter caustic edge."),
    ),
    "ringHalo": (
        ("Centre", "Centre", "e:Optical Centre (Orbital / Rainbow Ring)|Light (Halo)", 0, 0, 0,
         "Optical Centre: a ring around the optical centre, lit by nearby light. "
         "Light: a halo ring around each light."),
        ("Radius", "Radius", "d", 0.02, 1.5, 0.45, "Fraction of frame height."),
        ("Width", "Width", "d", 0.5, 300, 16, "Plate px."),
        ("Arc", "Arc", "d", 0, 1, 0.7, "Optical Centre mode: 0 = evenly lit ring, 1 = only the arc facing the light. "
         "The even part uses a fixed reference size (600 plate px), independent of Arc Falloff."),
        ("ArcFalloff", "Arc Falloff", "d", 10, 3000, 600, "How far light reaches around the ring (plate px)."),
    ),
    "orbs": (
        ("Count", "Count", "i", 8, MAX_ORBS, 24, "Number of orbs. Max 64."),
        ("SizeMin", "Size Min", "d", 1, 500, 10, "Radius in plate px."),
        ("SizeMax", "Size Max", "d", 1, 500, 45, "Radius in plate px."),
        ("Proximity", "Proximity", "d", 10, 3000, 400, "How close a light must be to light an orb (plate px)."),
        ("Softness", "Softness", "d", 0, 1, 0.5, None),
        ("Seed", "Seed", "i", 0, 9999, 0, None),
    ),
    "wash": (
        ("Spread", "Spread", "d", 10, 5000, 800, "Size of the light-biased veil in plate px."),
        ("Bias", "Bias", "d", 0, 1, 0.5, "0 = even over the frame, 1 = concentrated toward the light. "
         "The even part uses a fixed reference size (800 plate px), independent of Spread."),
    ),
}

# Ring colour knobs (suffix, label, kind, lo, hi, default, tooltip) added to every
# COLOURED element, plus 4 ramp stops (Color knob RampN + position RampPosN).
COLOUR_EXTRA = (
    ("ColorMode", "Colour Mode", "e:Tint|Spectrum|Ramp", 0, 0, 0,
     "Tint: one colour. Spectrum: physical rainbow across the colour band (violet inside, red outside). "
     "Ramp: your 4 colour stops across the band. "
     "Spectrum/Ramp cost 3x the render time of Tint for that element."),
    ("ColorWidth", "Colour Width", "d", 0.05, 1, 0.35,
     "Filled shapes: fraction of the radius, in from the edge, that carries the colour. "
     "Rings: how much of the ring's width the colour band spans."),
    ("LightColor", "Light Colour", "d", 0, 1, 1, "1 = take the light's own colour, 0 = treat the light as white."),
    ("Noise", "Noise", "d", 0, 1, 0, "Breaks up brightness around the shape."),
    ("NoiseScale", "Noise Scale", "d", 1, 64, 8, "Number of noise features around the shape."),
    ("NoiseSpeed", "Noise Speed", "d", 0, 10, 0, "0 = static."),
)
RAMP_DEFAULTS = (((1.0, 0.2, 0.1), 0.0), ((1.0, 0.85, 0.2), 0.35), ((0.2, 0.9, 0.5), 0.65), ((0.3, 0.4, 1.0), 1.0))

# Tuned in Nuke on a 6px light at value 5 with Source Gain 12 stops, so each
# element peaks around 0.5-4 near the light. Hotspot-fed elements are small
# because a hotspot carries the light's whole energy in one pixel.
DEFAULT_INTENSITY = {
    "streak": 0.002, "spikeBall": 0.004, "shimmer": 0.01, "sparkle": 0.0002, "glint": 0.0005,
    "bloom": 0.002, "iris": 0.002, "multiIris": 0.0005, "rings": 0.002, "caustic": 0.002,
    "ringHalo": 0.01, "orbs": 0.04, "wash": 0.05,
}


def colour_knob_names(prefix):
    names = [prefix + spec[0] for spec in COLOUR_EXTRA]
    for i in range(4):
        names += ["%sRamp%d" % (prefix, i), "%sRampPos%d" % (prefix, i)]
    return names


def knob_names(eid):
    """Every knob an element owns (for tests and the knob builder)."""
    names = [eid + "On", eid + "Intensity", eid + "Source", eid + "Tint", eid + "Offset"]
    names += [eid + spec[0] for spec in EXTRA[eid]]
    if eid in COLOURED:
        names += colour_knob_names(eid)
    return names


# -- small expression helpers ----------------------------------------------------

def p(eid, suffix):
    return "parent.%s%s" % (eid, suffix)


def _hash(index, a, b, seed_expr):
    """Deterministic 0..1 for `index`, re-rolled by `seed_expr`."""
    v = "sin(%g+(%s)*%g)*43758.5453" % (index * a + 1.0, seed_expr, b)
    return "((%s)-floor(%s))" % (v, v)


def _on(eid):
    return "{{!parent.%sOn}}" % eid


def _source(eid, light_colour=False):
    """Switch between $hl (0) and $hot (1) by the element's Source knob. With
    `light_colour`, blend the light's colour toward its luminance by
    (1 - Light Colour)."""
    out = ("push $hot\npush $hl\nSwitch {\n inputs 2\n which {{parent.%sSource}}\n name %sSrc\n}\n"
           % (eid, eid))
    if light_colour:
        out += light_colour_tcl(eid, "%sLight" % eid) + "\n"
    return out + "set %s_src [stack 0]" % eid


def light_colour_tcl(prefix, name):
    lc = p(prefix, "LightColor")
    return ("Expression {\n temp_name0 lm\n temp_expr0 {0.2126*r+0.7152*g+0.0722*b}\n"
            " expr0 {lerp(lm,r,%s)}\n expr1 {lerp(lm,g,%s)}\n expr2 {lerp(lm,b,%s)}\n expr3 0\n"
            " disable {{!parent.%sOn}}\n name %s\n}" % (lc, lc, lc, prefix, name))


def with_floor(lines):
    """Add CENTRE_FLOOR to every braced expr0..expr3 line. Mono kernels write
    `expr0 0` (no braces) for rgb, so only their alpha gets the floor; coloured
    kernels get it on all four channels."""
    out = []
    for ln in lines:
        for i in range(4):
            head = " expr%d {" % i
            if ln.startswith(head):
                ln = "%s(%s)+%s}" % (head, ln[len(head):-1], CENTRE_FLOOR)
                break
        out.append(ln)
    return out


def _kernel(eid, name, body_lines, disable=None):
    """Procedural kernel Expression centred on the (padded) canvas. Every
    braced channel gets CENTRE_FLOOR so its sum is always positive. The kernel
    reads $hl only for its format."""
    return ("push $hl\nExpression {\n%s\n disable %s\n name %s\n}"
            % ("\n".join(with_floor(body_lines)), disable or _on(eid), name))


def _convolve(kernel_var, src_var, disable, name):
    return ("push $%s\npush $%s\nConvolve2 {\n inputs 2\n channels rgb\n filter_channel rgba.alpha\n"
            " normalize true\n disable %s\n name %s\n}" % (kernel_var, src_var, disable, name))


def _gain(eid, name, extra="1", chan=("1", "1", "1")):
    """Never disabled: multiplies by On, Intensity, Tint, `extra` and per-channel `chan`."""
    k = "parent.%sOn*parent.%sIntensity*(%s)" % (eid, eid, extra)
    return ("Expression {\n temp_name0 kk\n temp_expr0 {%s}\n"
            " expr0 {r*kk*parent.%sTint.r*(%s)}\n expr1 {g*kk*parent.%sTint.g*(%s)}\n"
            " expr2 {b*kk*parent.%sTint.b*(%s)}\n"
            " expr3 0\n name %s\n}" % (k, eid, chan[0], eid, chan[1], eid, chan[2], name))


def offset_tcl(prefix, name):
    """Art-direct translate (plate px) on an element's final output."""
    return ("Transform {\n translate {{parent.%sOffset.x*%s} {parent.%sOffset.y*%s}}\n name %s\n}"
            % (prefix, RES, prefix, RES, name))


def _centre_temps():
    return [" temp_name0 dx", " temp_expr0 {x+0.5-width/2}",
            " temp_name1 dy", " temp_expr1 {y+0.5-height/2}"]


def _ray(angle_expr, length_expr, sigma_expr, falloff="1"):
    """One half-ray from the centre: Gaussian cross-section, exp fall-off."""
    return ("(cos(atan2(dy,dx)-(%s))>0)*exp(-pow(hypot(dx,dy)*sin(atan2(dy,dx)-(%s))/(%s),2)/2)"
            "*exp(-pow(hypot(dx,dy)/max(0.01,%s),max(0.2,%s)))" % (angle_expr, angle_expr, sigma_expr, length_expr, falloff))


def _finish(eid, out_lines, kernel, conv_src="%s_src", gain_extra="1"):
    """Mono (alpha) kernel element: kernel -> Convolve2 -> gain -> offset."""
    out_lines.append(kernel)
    out_lines.append("set %sK [stack 0]" % eid)
    out_lines.append(_convolve("%sK" % eid, conv_src % eid, _on(eid), "%sConv" % eid))
    out_lines.append(_gain(eid, "%sGain" % eid, gain_extra))
    out_lines.append(offset_tcl(eid, "%sOffsetT" % eid))
    out_lines.append("set el_%s [stack 0]" % eid)
    return "\n".join(out_lines)


# -- ring colour system ------------------------------------------------------------------

def _spectrum(u, chan):
    """HSV rainbow, violet at u=0 (inside) to red at u=1 (outside)."""
    h = "(0.75*(1-(%s)))" % u
    return {"r": "clamp(abs(%s*6-3)-1,0,1)" % h,
            "g": "clamp(2-abs(%s*6-2),0,1)" % h,
            "b": "clamp(2-abs(%s*6-4),0,1)" % h}[chan]


def _ramp(prefix, u, chan):
    """4-stop piecewise-linear ramp over u, flat beyond the end stops."""
    c = ["%s.%s" % (p(prefix, "Ramp%d" % i), chan) for i in range(4)]
    q = [p(prefix, "RampPos%d" % i) for i in range(4)]
    seg = lambda i: "lerp(%s,%s,clamp(((%s)-%s)/max(0.0001,%s-%s),0,1))" % (c[i], c[i + 1], u, q[i], q[i + 1], q[i])
    return "((%s)<%s?%s:((%s)<%s?%s:%s))" % (u, q[1], seg(0), u, q[2], seg(1), seg(2))


def _band_colour(prefix, u, chan):
    """Spectrum (mode 1) or Ramp (mode 2) colour at band coordinate u, >= 0."""
    mode = p(prefix, "ColorMode")
    return "max(0,(%s==1?%s:%s))" % (mode, _spectrum(u, chan), _ramp(prefix, u, chan))


# Which kernel shape each coloured prefix's balance integrates over.
BALANCE_SHAPES = (("iris", "filled"), ("multiIris", "filled"), ("caustic", "filled"),
                  ("rings", "ring"), ("ringHalo", "ring"), ("ghosts", "filled"))
FILLED_SAMPLES = 8
CORE_SAMPLES = 4
RING_SAMPLES = 16
APERTURE_SEC = "(2*pi/clamp(parent.blades,3,12))"
APERTURE_MIN = "((1-parent.apRoundness)*cos(%s/2)+parent.apRoundness)" % APERTURE_SEC   # inscribed radius / R


def aperture_cover(r):
    """Fraction of the angles at normalised radius r (0..1 of R) that lie
    inside the aperture polygon (APERTURE_EDGE): 1 up to the inscribed radius,
    falling to 0 at the vertices."""
    sec, rd = APERTURE_SEC, "parent.apRoundness"
    return ("((%s)<=%s?1:clamp(1-2*acos(clamp((1-%s)*cos(%s/2)/((%s)-%s),-1,1))/%s,0,1))"
            % (r, APERTURE_MIN, rd, sec, r, rd, sec))


def _filled_weights(prefix):
    """(name, expr) of the flareGeo weight knobs for a filled shape: the white
    core, the FILLED_SAMPLES band samples and their sum. Area weight of radius
    r is 2r dr, times the shape's coverage there: the aperture polygon's
    angular coverage (iris, multi-iris, ghosts) or the caustic's radial
    brightness profile."""
    cw = "clamp(%s,0.05,1)" % p(prefix, "ColorWidth")
    names = []
    if prefix == "caustic":
        pc = "(max(0.1,%s)*4)" % p(prefix, "Sharpness")
        core = "0.12*pow(1-%s,2)+2*pow(1-%s,%s+2)/(%s+2)" % (cw, cw, pc, pc)
        cover = lambda r: "(0.12+pow(%s,%s))" % (r, pc)
    else:
        span = "max(0,1-%s-%s)" % (cw, APERTURE_MIN)      # part of the core past the inscribed radius
        parts = ["pow(min(1-%s,%s),2)" % (cw, APERTURE_MIN)]
        for j in range(CORE_SAMPLES):
            rj = "(%s+%s*%g)" % (APERTURE_MIN, span, (j + 0.5) / CORE_SAMPLES)
            parts.append("%g*%s*%s*%s" % (2.0 / CORE_SAMPLES, rj, aperture_cover(rj), span))
        core = "+".join(parts)
        cover = aperture_cover
    names.append(("w_%s_core" % prefix, core))
    for k in range(FILLED_SAMPLES):
        rk = "(1-%s+%s*%g)" % (cw, cw, (k + 0.5) / FILLED_SAMPLES)
        names.append(("w_%s_%d" % (prefix, k), "%g*%s*%s*%s" % (2.0 / FILLED_SAMPLES, cw, rk, cover(rk))))
    names.append(("w_%s_sum" % prefix, "+".join("%s.%s" % (GEO, n) for n, _e in names)))
    return names


def balance_weight_knobs(prefix, shape):
    """flareGeo helper knobs colour_balance(prefix, shape) reads."""
    return _filled_weights(prefix) if shape == "filled" else []


def colour_balance(prefix, shape):
    """Per-channel kernel-weighted mean colour M_c (r, g, b expressions).

    Convolve2 normalize divides channel c by sum(kernel_c) = area x M_c, so
    multiplying the gain by M_c restores the colour the kernel carries.
    filled: white core (colour 1) of weight (1-cw)^2 plus 8 midpoint samples
      of the band, u_k = (k+0.5)/8, weight 2*cw*(1-cw+cw*u_k)/8, colour
      col_c(u_k); M_c = (core + sum w_k col_c)/(core + sum w_k). Each weight
      also carries the shape's coverage at that radius (_filled_weights): the
      aperture polygon covers only part of the outer band (without this a
      6-blade Iris centre is 15-30% off neutral), the caustic is edge-weighted.
      The weights are flareGeo knobs (w_<prefix>_*), shared by r, g and b.
    ring: Gaussian ring profile, 16 samples d_k = -4+8*(k+0.5)/16 sigma,
      weight exp(-d_k^2/2) (normalised here), u = clamp(d_k/(4*cw)+0.5,0,1)
      as in ring_band.
    Tint (mode 0) -> 1. Never floored: a channel the colour lacks gets 0."""
    mode = p(prefix, "ColorMode")
    cw = "clamp(%s,0.05,1)" % p(prefix, "ColorWidth")
    out = []
    for ch in "rgb":
        if shape == "filled":
            terms = ["%s.w_%s_core" % (GEO, prefix)]
            for k in range(FILLED_SAMPLES):
                uk = (k + 0.5) / FILLED_SAMPLES
                terms.append("%s.w_%s_%d*%s" % (GEO, prefix, k, _band_colour(prefix, "%g" % uk, ch)))
            body = "(%s)/%s.w_%s_sum" % ("+".join(terms), GEO, prefix)
        elif shape == "ring":
            ds = [-4.0 + 8.0 * (k + 0.5) / RING_SAMPLES for k in range(RING_SAMPLES)]
            ws = [math.exp(-d * d / 2.0) for d in ds]
            tot = sum(ws)
            terms = []
            for d, w in zip(ds, ws):
                uk = "clamp(%g/(4*%s)+0.5,0,1)" % (d, cw)
                terms.append("%.6g*%s" % (w / tot, _band_colour(prefix, uk, ch)))
            body = "+".join(terms)
        else:
            raise ValueError(shape)
        out.append("(%s==0?1:(%s))" % (mode, body))
    return tuple(out)


def balance_refs(prefix):
    """flareGeo knobs holding colour_balance(prefix, ...) for r, g, b."""
    return tuple("%s.bal_%s_%s" % (GEO, prefix, ch) for ch in "rgb")


def colour_expr(prefix, u, inside_band, chan):
    """Colour of the shape at band coordinate `u` for one channel (>= 0)."""
    mode = p(prefix, "ColorMode")
    return "max(0,((%s)?(%s==1?%s:(%s==2?%s:1)):1))" % (
        inside_band, mode, _spectrum(u, chan), mode, _ramp(prefix, u, chan))


def time_ref(prefix):
    """flareGeo knob holding frame*<prefix>NoiseSpeed (or *Speed)."""
    return "%s.t_%s" % (GEO, prefix)


def noise_expr(prefix, angle, slot=0):
    """Angular noise; each slot gets its own pattern (z offset slot*7.31)."""
    amt = "clamp(%s,0,1)" % p(prefix, "Noise")
    sc = "%s/(2*pi)" % p(prefix, "NoiseScale")
    z = "%s*0.1" % time_ref(prefix)
    if slot:
        z += "+%g" % (slot * 7.31)
    return ("(1-%s+%s*clamp(0.5+1.2*noise(cos(%s)*%s,sin(%s)*%s,%s),0,1))"
            % (amt, amt, angle, sc, angle, sc, z))


def geo_tcl():
    """The flareGeo NoOp: pad, frame size and optical centre (working px), the
    animation times and every coloured prefix's colour balance, evaluated once
    per frame. Other nodes read them as flareGeo.<knob> (expression syntax; no
    Python node access). The only place `frame` appears in the graph."""
    knobs = [("padx", PADX_EXPR), ("pady", PADY_EXPR), ("fw", "flareDown.width"), ("fh", "flareDown.height"),
             ("cx", CX_EXPR), ("cy", CY_EXPR)]
    for prefix in list(COLOURED) + ["ghosts"]:
        knobs.append(("t_" + prefix, "frame*%s" % p(prefix, "NoiseSpeed")))
    knobs.append(("t_shimmer", "frame*%s" % p("shimmer", "Speed")))
    knobs.append(("t_sparkle", "frame*%s" % p("sparkle", "Speed")))
    for prefix, shape in BALANCE_SHAPES:
        knobs += balance_weight_knobs(prefix, shape)
        for ch, expr in zip("rgb", colour_balance(prefix, shape)):
            knobs.append(("bal_%s_%s" % (prefix, ch), expr))
    lines = ["NoOp {", " name %s" % GEO, " addUserKnob {20 User}"]
    for name, expr in knobs:
        lines.append(" addUserKnob {7 %s}" % name)
        lines.append(" %s {{%s}}" % (name, expr))
    lines.append("}")
    return "\n".join(lines)


def coloured_kernel_lines(prefix, temps, shape, u, inside_band, angle, slot=0):
    """RGBA kernel: rgb = shape x noise x colour(u), alpha = shape x noise."""
    nz = noise_expr(prefix, angle, slot)
    lines = list(temps)
    for i, ch in enumerate("rgb"):
        lines.append(" expr%d {(%s)*%s*%s}" % (i, shape, nz, colour_expr(prefix, u, inside_band, ch)))
    lines.append(" expr3 {(%s)*%s}" % (shape, nz))
    return lines


def coloured_conv_tcl(prefix, kernel_var, src_var, off_expr, tag):
    """Tint branch (one alpha Convolve2) and colour branch (one Convolve2 per
    channel), picked by Colour Mode. Unused branch is disabled. Leaves the
    picked result on the stack."""
    mode = p(prefix, "ColorMode")
    mono_off = "{{%s||%s>0}}" % (off_expr, mode)
    col_off = "{{%s||%s==0}}" % (off_expr, mode)
    out = [_convolve(kernel_var, src_var, mono_off, "%sMono" % tag), "set %sM [stack 0]" % tag,
           "push $%s\nset %sC [stack 0]" % (src_var, tag)]
    for ch in ("red", "green", "blue"):
        out.append("push $%s\npush $%sC\nConvolve2 {\n inputs 2\n channels rgba.%s\n filter_channel rgba.%s\n"
                   " normalize true\n disable %s\n name %s_%s\n}\nset %sC [stack 0]"
                   % (kernel_var, tag, ch, ch, col_off, tag, ch, tag))
    out.append("push $%sC\npush $%sM\nSwitch {\n inputs 2\n which {{%s>0}}\n name %sPick\n}" % (tag, tag, mode, tag))
    return "\n".join(out)


# -- centred elements ---------------------------------------------------------------

def _streak_tcl():
    e = "streak"
    th = "%s*pi/180" % p(e, "Angle")
    body = _centre_temps() + [
        " temp_name2 sw", " temp_expr2 {hypot(%s*%s/2.355,%g)}" % (p(e, "Thickness"), RES, AA),
        " temp_name3 sl", " temp_expr3 {max(0.5,%s*%s)}" % (p(e, "Length"), RES),
        " expr0 0", " expr1 0", " expr2 0",
        " expr3 {exp(-pow(abs(dx*cos(%s)+dy*sin(%s))/sl,max(0.2,%s)))*exp(-pow((-dx*sin(%s)+dy*cos(%s))/sw,2)/2)}"
        % (th, th, p(e, "Falloff"), th, th),
    ]
    return _finish(e, [_source(e)], _kernel(e, "streakKernel", body))


def _spike_ball_tcl():
    e = "spikeBall"
    seed = p(e, "Seed")
    terms = []
    for k in range(MAX_SPIKE_RAYS):
        ang = "2*pi*%s" % _hash(k, 12.9898, 78.233, seed)
        length = "sl*(1-%s*%s)" % (p(e, "Variation"), _hash(k, 39.3467, 11.135, seed))
        terms.append("(%d<%s)*%s" % (k, p(e, "Rays"), _ray(ang, length, "sw")))
    body = _centre_temps() + [
        " temp_name2 sw", " temp_expr2 {hypot(%s*%s/2.355,%g)}" % (p(e, "Thickness"), RES, AA),
        " temp_name3 sl", " temp_expr3 {max(0.01,%s*%s)}" % (p(e, "Length"), RES),
        " expr0 0", " expr1 0", " expr2 0",
        " expr3 {hypot(dx,dy)<0.5?0:%s}" % "+".join(terms),
    ]
    return _finish(e, [_source(e)], _kernel(e, "spikeBallKernel", body))


def _shimmer_tcl():
    e = "shimmer"
    f = "%s/(2*pi)" % p(e, "Rays")
    body = _centre_temps() + [
        " temp_name2 rr", " temp_expr2 {hypot(dx,dy)}",
        " temp_name3 nz",
        " temp_expr3 {noise(cos(atan2(dy,dx))*%s+%s*1.37,sin(atan2(dy,dx))*%s,%s*0.15)}"
        % (f, p(e, "Seed"), f, time_ref(e)),
        " expr0 0", " expr1 0", " expr2 0",
        " expr3 {rr<0.5?0:pow(clamp(0.5+1.5*nz,0,1),6)*exp(-rr/max(0.01,%s*%s))}" % (p(e, "Length"), RES),
    ]
    return _finish(e, [_source(e)], _kernel(e, "shimmerKernel", body))


def _sparkle_tcl():
    e = "sparkle"
    npts = "(4+2*%s)" % p(e, "Points")           # enum 0/1/2 -> 4/6/8
    terms = []
    for k in range(MAX_SPARKLE_POINTS):
        ang = "%s*pi/180+%d*2*pi/%s" % (p(e, "Rotation"), k, npts)
        tw = "(0.6+0.4*sin(%s+%d*2.399))" % (time_ref(e), k)
        terms.append("(%d<%s)*%s*%s" % (k, npts, tw, _ray(ang, "sz", "%g" % 0.6)))
    body = _centre_temps() + [
        " temp_name2 sz", " temp_expr2 {max(0.01,%s*%s)}" % (p(e, "Size"), RES),
        " expr0 0", " expr1 0", " expr2 0",
        " expr3 {(hypot(dx,dy)<0.5?0:%s)+4*exp(-pow(hypot(dx,dy)/max(0.5,sz*0.06),2)/2)}" % "+".join(terms),
    ]
    return _finish(e, [_source(e)], _kernel(e, "sparkleKernel", body))


def _glint_tcl():
    e = "glint"
    rays = []
    for k in range(4):
        ang = "%s*pi/180+%d*pi/2" % (p(e, "Angle"), k)
        rays.append(_ray(ang, "gl", "%g" % 0.5))
    body = _centre_temps() + [
        " temp_name2 gs", " temp_expr2 {hypot(%s*%s/2.355,%g)}" % (p(e, "Size"), RES, AA),
        " temp_name3 gl", " temp_expr3 {max(0.01,%s*%s)}" % (p(e, "SpikeLength"), RES),
        " expr0 0", " expr1 0", " expr2 0",
        " expr3 {8*exp(-pow(hypot(dx,dy)/gs,2)/2)+(hypot(dx,dy)<0.5?0:%s)}" % "+".join(rays),
    ]
    return _finish(e, [_source(e)], _kernel(e, "glintKernel", body))


def _bloom_tcl():
    """Multi-scale glow: Blurs at Size, 3x and 9x, weighted 1, f, f^2 (normalized)."""
    e = "bloom"
    out = [_source(e)]
    for i, mult in enumerate((1, 3, 9)):
        out.append("push $%s_src\nBlur {\n channels rgb\n size {{max(1,%s*%d*%s)}}\n disable %s\n name bloomBlur%d\n}"
                   "\nset bl%d [stack 0]" % (e, p(e, "Size"), mult, RES, _on(e), i, i))
    f = p(e, "Falloff")
    # (bl0 + f*bl1 + f^2*bl2) / (1 + f + f^2), as two two-input mixes.
    out.append("push $bl1\npush $bl0\nMergeExpression {\n inputs 2\n"
               " expr0 {B.r+A.r*%s}\n expr1 {B.g+A.g*%s}\n expr2 {B.b+A.b*%s}\n expr3 0\n"
               " disable %s\n name bloomMix01\n}\nset bl01 [stack 0]" % (f, f, f, _on(e)))
    out.append("push $bl2\npush $bl01\nMergeExpression {\n inputs 2\n temp_name0 wsum\n temp_expr0 {1+%s+%s*%s}\n"
               " expr0 {(B.r+A.r*%s*%s)/wsum}\n expr1 {(B.g+A.g*%s*%s)/wsum}\n expr2 {(B.b+A.b*%s*%s)/wsum}\n"
               " expr3 0\n disable %s\n name bloomMix\n}" % (f, f, f, f, f, f, f, f, f, _on(e)))
    out.append(_gain(e, "bloomGain"))
    out.append(offset_tcl(e, "bloomOffsetT"))
    out.append("set el_%s [stack 0]" % e)
    return "\n".join(out)


# -- axial elements -------------------------------------------------------------------

def _safe_pos(expr):
    """Signed position kept at |p| >= 0.05 (gain divides by p^2)."""
    return "(abs(%s)<0.05?(%s<0?-0.05:0.05):%s)" % (expr, expr, expr)


def _axial_copy(eid, pos_expr, disable, name):
    """Highlights scaled about the optical centre by `pos_expr` (1 = at the light)."""
    return ("push $%s_src\nTransformMasked {\n channels rgb\n scale {{%s}}\n center {{%s} {%s}}\n"
            " filter cubic\n black_outside true\n disable %s\n name %s\n}" % (eid, pos_expr, CX, CY, disable, name))


SHAPE_TEMPS_R = " temp_expr3 {max(0.5,min(%s,min(width,height)/2-4))}"


def shape_temps(radius_expr):
    """Centred kernel temps: dist, sec, aw (aperture angle), R (clamped to the canvas)."""
    return [" temp_name0 dist", " temp_expr0 {hypot(x+0.5-width/2,y+0.5-height/2)}",
            " temp_name1 sec", " temp_expr1 {2*pi/clamp(parent.blades,3,12)}",
            " temp_name2 aw", " temp_expr2 {atan2(y+0.5-height/2,x+0.5-width/2)-parent.apRotation*pi/180}",
            " temp_name3 R", SHAPE_TEMPS_R % radius_expr]


APERTURE_EDGE = "lerp(R*cos(sec/2)/cos(aw-sec*floor(aw/sec)-sec/2),R,parent.apRoundness)"


def iris_shape(soft_expr):
    return "clamp((%s-dist)/max(0.5,%s)+0.5,0,1)" % (APERTURE_EDGE, soft_expr)


def filled_band(prefix):
    """(u, inside_band) for filled shapes: colour lives in the outer
    Colour Width fraction of the radius."""
    cw = "clamp(%s,0.05,1)" % p(prefix, "ColorWidth")
    return ("clamp((dist-R*(1-%s))/(R*%s),0,1)" % (cw, cw), "dist>R*(1-%s)" % cw)


def _coloured_axial(e, tag, pos, off, kernel_body_shape, radius, gain_on, chan_tint=("1", "1", "1"), slot=0):
    """One coloured axial copy: transform -> RGBA kernel -> picked convolve -> gain."""
    u, band = filled_band(e)
    out = [_axial_copy(e, pos, off, "%sCopy" % tag), "set %sT [stack 0]" % tag]
    lines = coloured_kernel_lines(e, shape_temps(radius), kernel_body_shape, u, band, "aw", slot)
    out.append("push $hl\nExpression {\n%s\n disable %s\n name %sKernel\n}" % ("\n".join(with_floor(lines)), off, tag))
    out.append("set %sK [stack 0]" % tag)
    out.append(coloured_conv_tcl(e, "%sK" % tag, "%sT" % tag, off.strip("{}"), tag))
    bal = balance_refs(e)
    chan = tuple("%s*%s" % (b, t) for b, t in zip(bal, chan_tint))
    out.append(_gain(e, "%sGain" % tag, "%s/pow(%s,2)" % (gain_on, pos), chan))
    return "\n".join(out)


def _iris_tcl():
    e = "iris"
    pos = _safe_pos(p(e, "Position"))
    radius = "%s*%s*2.8/parent.effFstop" % (p(e, "Size"), RES)
    body = _coloured_axial(e, "iris", pos, _on(e), iris_shape("%s*%s" % (p(e, "Softness"), RES)), radius, "1")
    return "\n".join([_source(e, True), body, offset_tcl(e, "irisOffsetT"), "set el_%s [stack 0]" % e])


def _multi_iris_tcl():
    e = "multiIris"
    seed = p(e, "Seed")
    out = [_source(e, True)]
    for i in range(MULTI_IRIS_SLOTS):
        off = "{{!parent.%sOn||parent.%sCount<=%d}}" % (e, e, i)
        pos = _safe_pos("lerp(-%s,%s,%s)" % (p(e, "Spread"), p(e, "Spread"), _hash(i, 3.17, 5.71, seed)))
        size = "lerp(%s,%s,%s)*%s*2.8/parent.effFstop" % (p(e, "SizeMin"), p(e, "SizeMax"),
                                                          _hash(i, 7.31, 2.93, seed), RES)
        cv = p(e, "ColorVar")
        tint = tuple("(1+%s*(%s-0.5))" % (cv, _hash(i, c, hb, seed))
                     for c, hb in ((11.1, 1.618), (22.2, 2.414), (33.3, 3.732)))
        out.append(_coloured_axial(e, "multiIris%d" % i, pos, off, iris_shape("1"), size,
                                   "(parent.%sCount>%d)" % (e, i), tint, slot=i))
        out.append("set mi%d [stack 0]" % i)
    acc = "$mi0"
    for i in range(1, MULTI_IRIS_SLOTS):
        out.append("push $mi%d\npush %s\nMerge2 { inputs 2 operation plus also_merge all }\nset mi_acc [stack 0]" % (i, acc))
        acc = "$mi_acc"
    out.append("push %s\n%s\nset el_%s [stack 0]" % (acc, offset_tcl(e, "multiIrisOffsetT"), e))
    return "\n".join(out)


def ring_band(prefix, offset_expr, sigma_expr):
    """u across a ring: 0 inside .. 1 outside over 4 sigma x Colour Width."""
    cw = "clamp(%s,0.05,1)" % p(prefix, "ColorWidth")
    return "clamp((%s)/(4*%s*%s)+0.5,0,1)" % (offset_expr, sigma_expr, cw)


def ring_profile(prefix, sigma_expr):
    """(shape, u, inside_band) for a Gaussian ring of radius R."""
    s = "hypot(%s,%g)" % (sigma_expr, AA)
    return ("exp(-pow((dist-R)/%s,2)/2)" % s, ring_band(prefix, "dist-R", s), "1")


def _rings_tcl():
    e = "rings"
    out = [_source(e, True)]
    for i in range(RING_SLOTS):
        off = "{{!parent.%sOn||parent.%sCount<=%d}}" % (e, e, i)
        pos = _safe_pos("(%s+%d*%s)" % (p(e, "Position"), i, p(e, "Spacing")))
        tag = "rings%d" % i
        out.append(_axial_copy(e, pos, off, "%sCopy" % tag))
        out.append("set %sT [stack 0]" % tag)
        shape, u, band = ring_profile(e, "%s*%s/2.355" % (p(e, "Thickness"), RES))
        radius = "%s*%s*(1+%d*0.18)" % (p(e, "Radius"), RES, i)
        lines = coloured_kernel_lines(e, shape_temps(radius), shape, u, band, "aw", i)
        out.append("push $hl\nExpression {\n%s\n disable %s\n name %sKernel\n}" % ("\n".join(with_floor(lines)), off, tag))
        out.append("set %sK [stack 0]" % tag)
        out.append(coloured_conv_tcl(e, "%sK" % tag, "%sT" % tag, off.strip("{}"), tag))
        out.append(_gain(e, "%sGain" % tag, "(parent.%sCount>%d)/pow(%s,2)" % (e, i, pos), balance_refs(e)))
        out.append("set rg%d [stack 0]" % i)
    acc = "$rg0"
    for i in range(1, RING_SLOTS):
        out.append("push $rg%d\npush %s\nMerge2 { inputs 2 operation plus also_merge all }\nset rg_acc [stack 0]" % (i, acc))
        acc = "$rg_acc"
    out.append("push %s\n%s\nset el_%s [stack 0]" % (acc, offset_tcl(e, "ringsOffsetT"), e))
    return "\n".join(out)


def _caustic_tcl():
    e = "caustic"
    pos = _safe_pos(p(e, "Position"))
    shape = ("clamp(R-dist+0.5,0,1)*(0.12+pow(clamp(dist/R,0,1),max(0.1,%s)*4))"
             "*(0.65+0.35*cos(clamp(parent.blades,3,12)*aw))" % p(e, "Sharpness"))
    body = _coloured_axial(e, "caustic", pos, _on(e), shape, "%s*%s" % (p(e, "Size"), RES), "1")
    return "\n".join([_source(e, True), body, offset_tcl(e, "causticOffsetT"), "set el_%s [stack 0]" % e])


# -- ring / halo -------------------------------------------------------------------------

def _ring_halo_tcl():
    """Centre = Optical Centre: ring drawn around the optical centre, lit by
    lerp(even frame-wide light, light reaching around from the nearest side,
    Arc). Centre = Light: ring kernel convolved with the source (a halo
    around each light). A Switch picks the mode; the other branch is disabled."""
    e = "ringHalo"
    mode = p(e, "Centre")
    orb_off = "{{!parent.%sOn||%s==1}}" % (e, mode)
    even_off = "{{!parent.%sOn||%s==1||%s>=1}}" % (e, mode, p(e, "Arc"))     # Arc 1 never reads it
    halo_off = "{{!parent.%sOn||%s==0}}" % (e, mode)
    sig = "%s*%s/2.355" % (p(e, "Width"), RES)
    s = "hypot(%s,%g)" % (sig, AA)
    out = [_source(e, True)]
    # Optical Centre (orbital / rainbow ring) branch.
    out.append("push $%s_src\nBlur {\n channels rgb\n size {{max(1,%s*%s)}}\n disable %s\n name ringHaloReach\n}"
               "\nset rhD [stack 0]" % (e, p(e, "ArcFalloff"), RES, orb_off))
    out.append("push $%s_src\nBlur {\n channels rgb\n size {{4*%s}}\n disable %s\n name ringHaloEven\n}"
               "\nset rhE [stack 0]" % (e, FW, even_off))
    u = ring_band(e, "dd-rr", s)
    nz = noise_expr(e, "atan2(y+0.5-%s,x+0.5-%s)" % (CY, CX))
    # The even blur is spread far wider than the reach blur; scale it to the
    # peak level of a reach blur of fixed size EVEN_REF_PX, so the even field
    # does not depend on Arc Falloff.
    comp = "pow(4*%s/(%g*%s),2)" % (FW, EVEN_REF_PX, RES)
    arc = p(e, "Arc")
    rows = []
    for i, ch in enumerate("rgb"):
        rows.append(" expr%d {(%s>=1?A.%s:lerp(B.%s*%s,A.%s,%s))*mm*%s}" % (
            i, arc, ch, ch, comp, ch, arc, colour_expr(e, u, "1", ch)))
    out.append("push $rhD\npush $rhE\nMergeExpression {\n inputs 2\n"
               " temp_name0 dd\n temp_expr0 {hypot(x+0.5-%s,y+0.5-%s)}\n"
               " temp_name1 rr\n temp_expr1 {%s*%s}\n"
               " temp_name2 mm\n temp_expr2 {exp(-pow((dd-rr)/%s,2)/2)*%s}\n"
               "%s\n expr3 0\n disable %s\n name ringHaloOrbital\n}\nset rhO [stack 0]"
               % (CX, CY, p(e, "Radius"), FH, s, nz, "\n".join(rows), orb_off))
    # Light (halo) branch.
    shape, hu, band = ring_profile(e, sig)
    lines = coloured_kernel_lines(e, shape_temps("%s*%s" % (p(e, "Radius"), FH)), shape, hu, band, "aw")
    out.append("push $hl\nExpression {\n%s\n disable %s\n name ringHaloKernel\n}" % ("\n".join(with_floor(lines)), halo_off))
    out.append("set rhK [stack 0]")
    out.append(coloured_conv_tcl(e, "rhK", "%s_src" % e, halo_off.strip("{}"), "ringHaloHalo"))
    out.append("set rhH [stack 0]")
    out.append("push $rhH\npush $rhO\nSwitch {\n inputs 2\n which {{%s}}\n name ringHaloPick\n}" % mode)
    # Light mode is a normalized convolution and needs the balance; Optical
    # Centre mode applies the colour per pixel, unnormalized.
    out.append(_gain(e, "ringHaloGain", "1", tuple("(%s==1?%s:1)" % (mode, b) for b in balance_refs(e))))
    out.append(offset_tcl(e, "ringHaloOffsetT"))
    out.append("set el_%s [stack 0]" % e)
    return "\n".join(out)


# -- fixed to the glass ---------------------------------------------------------------------

def _orbs_tcl():
    e = "orbs"
    seed = p(e, "Seed")
    discs = []
    for k in range(MAX_ORBS):
        ox = "(%s+%s*%s)" % (PADX, _hash(k, 1.13, 4.7, seed), FW)
        oy = "(%s+%s*%s)" % (PADY, _hash(k, 2.71, 9.2, seed), FH)
        orad = "max(0.5,lerp(%s,%s,%s)*%s)" % (p(e, "SizeMin"), p(e, "SizeMax"), _hash(k, 3.33, 1.9, seed), RES)
        opac = "(0.3+0.7*%s)" % _hash(k, 5.55, 6.1, seed)
        soft = "max(0.5,%s*%s)" % (p(e, "Softness"), orad)
        discs.append("(%d<%s)*%s*clamp((%s-hypot(x+0.5-%s,y+0.5-%s))/%s+0.5,0,1)"
                     % (k, p(e, "Count"), opac, orad, ox, oy, soft))
    return "\n".join([
        _source(e),
        "push $%s_src\nBlur {\n channels rgb\n size {{%s*%s}}\n disable %s\n name orbsReach\n}" % (
            e, p(e, "Proximity"), RES, _on(e)),
        "Expression {\n temp_name0 dust\n temp_expr0 {%s}\n"
        " expr0 {r*dust}\n expr1 {g*dust}\n expr2 {b*dust}\n expr3 0\n disable %s\n name orbsShape\n}" % (
            "+".join(discs), _on(e)),
        _gain(e, "orbsGain"),
        offset_tcl(e, "orbsOffsetT"),
        "set el_%s [stack 0]" % e,
    ])


def _wash_tcl():
    """Frame-wide veil: lerp(near-uniform field, light-biased field, Bias)."""
    e = "wash"
    # Even field scaled to the peak level of a fixed WASH_REF_PX blur, so it
    # does not depend on Spread. Each blur is disabled where Bias ignores it.
    comp = "pow(4*%s/(%g*%s),2)" % (FW, WASH_REF_PX, RES)
    bias = p(e, "Bias")
    rows = "".join(" expr%d {(%s>=1?A.%s:(%s<=0?B.%s*%s:lerp(B.%s*%s,A.%s,%s)))}\n"
                   % (i, bias, ch, bias, ch, comp, ch, comp, ch, bias) for i, ch in enumerate("rgb"))
    return "\n".join([
        _source(e),
        "push $%s_src\nBlur {\n channels rgb\n size {{4*%s}}\n disable {{!parent.%sOn||%s>=1}}\n name washEven\n}"
        "\nset wsE [stack 0]" % (e, FW, e, bias),
        "push $%s_src\nBlur {\n channels rgb\n size {{max(1,%s*%s)}}\n disable {{!parent.%sOn||%s<=0}}\n name washNear\n}"
        "\nset wsN [stack 0]" % (e, p(e, "Spread"), RES, e, bias),
        "push $wsN\npush $wsE\nMergeExpression {\n inputs 2\n%s expr3 0\n"
        " disable %s\n name washMix\n}" % (rows, _on(e)),
        _gain(e, "washGain"),
        offset_tcl(e, "washOffsetT"),
        "set el_%s [stack 0]" % e,
    ])


# -- hotspot + assembly ------------------------------------------------------------------

def _any_hot_user():
    return "||".join("(parent.%sOn&&parent.%sSource==1)" % (eid, eid) for eid, _l, _f, _s in ELEMENTS)


def hotspot_tcl():
    """$hot: one pixel per light carrying that light's energy. Score = blurred
    luminance with a tiny position tie-break (clipped, flat-topped lights
    would otherwise make every pixel a peak); a pixel survives where it equals
    the local max (Dilate). Energy = box-blur average x box area."""
    off = "{{!(%s)}}" % _any_hot_user()
    rad = "parent.hotRadius*" + RES
    return "\n".join([
        "push $hl\nBlur {\n channels rgb\n size {{max(1,%s)}}\n disable %s\n name hotSmooth\n}" % (rad, off),
        "Expression {\n expr0 {(0.2126*r+0.7152*g+0.0722*b)*(1+0.000001*(x+0.618*y))}\n expr1 0\n expr2 0\n expr3 0\n"
        " disable %s\n name hotScore\n}" % off,
        "set hotS [stack 0]",
        "Dilate {\n channels rgb\n size {{max(1,%s)}}\n disable %s\n name hotMax\n}" % (rad, off),
        "set hotD [stack 0]",
        "push $hl\nBlur {\n channels rgb\n size {{max(1,2*%s)}}\n filter box\n disable %s\n name hotEnergy\n}" % (rad, off),
        "set hotE [stack 0]",
        "push $hotD\npush $hotS\nMergeExpression {\n inputs 2\n expr0 {(B.r>0&&B.r>=A.r)?1:0}\n expr1 0\n expr2 0\n"
        " expr3 0\n disable %s\n name hotPeak\n}" % off,
        "set hotM [stack 0]",
        "push $hotE\npush $hotM\nMergeExpression {\n inputs 2\n temp_name0 area\n temp_expr0 {pow(max(1,2*%s),2)}\n"
        " expr0 {B.r*A.r*area}\n expr1 {B.r*A.g*area}\n expr2 {B.r*A.b*area}\n expr3 0\n disable %s\n name hotspot\n}"
        % (rad, off),
        "set hot [stack 0]",
    ])


GENERATORS = {
    "streak": _streak_tcl, "spikeBall": _spike_ball_tcl, "shimmer": _shimmer_tcl,
    "sparkle": _sparkle_tcl, "glint": _glint_tcl, "bloom": _bloom_tcl, "iris": _iris_tcl,
    "multiIris": _multi_iris_tcl, "rings": _rings_tcl, "caustic": _caustic_tcl,
    "ringHalo": _ring_halo_tcl, "orbs": _orbs_tcl, "wash": _wash_tcl,
}


def elements_tcl():
    """Hotspot detector + every element branch. Leaves $el_<id> for each."""
    return "\n".join([hotspot_tcl()] + [GENERATORS[eid]() for eid, _l, _f, _s in ELEMENTS])


def element_vars():
    return ["$el_%s" % eid for eid, _l, _f, _s in ELEMENTS]


# -- knobs (needs nuke) -------------------------------------------------------------------

def _make_knob(nuke, name, lab, kind, lo, hi, default, tip):
    if kind.startswith("e:"):
        k = nuke.Enumeration_Knob(name, lab, kind[2:].split("|"))
        k.setValue(int(default))
    elif kind == "i":
        k = nuke.Int_Knob(name, lab)
        k.setRange(lo, hi)
        k.setValue(int(default))
    else:
        k = nuke.Double_Knob(name, lab)
        k.setRange(lo, hi)
        k.setValue(default)
    if tip:
        k.setTooltip(tip)
    return k


RING_TYPES = ("rings", "ringHalo")      # their colour band defaults to the ring's full width


def colour_knobs(nuke, prefix):
    """The ring colour system knobs for one element (or 'ghosts')."""
    knobs = []
    for s, lab, kind, lo, hi, d, tip in COLOUR_EXTRA:
        if s == "ColorWidth" and prefix in RING_TYPES:
            d = 1.0
        knobs.append(_make_knob(nuke, prefix + s, lab, kind, lo, hi, d, tip))
    for i, (col, pos) in enumerate(RAMP_DEFAULTS):
        c = nuke.Color_Knob("%sRamp%d" % (prefix, i), "Ramp %d" % (i + 1))
        c.setValue(list(col))
        knobs.append(c)
        knobs.append(_make_knob(nuke, "%sRampPos%d" % (prefix, i), "Position", "d", 0, 1, pos,
                                "Where this colour sits across the band (0 = inside, 1 = outside). "
                                "Positions should increase from stop 1 to 4."))
    return knobs


def add_element_knobs(group, nuke, center_knob=None):
    """Elements tab: Optical Centre, Hotspot Radius, then one closed group per element."""
    group.addKnob(nuke.Tab_Knob("tabElements", "Elements"))
    if center_knob is not None:
        group.addKnob(center_knob)
    hot = nuke.Double_Knob("hotRadius", "Hotspot Radius")
    hot.setRange(2, 300)
    hot.setValue(24)
    hot.setTooltip("Plate px. Use at least the radius of your biggest light; lights closer than this merge into one hotspot.")
    group.addKnob(hot)
    for eid, label, family, src in ELEMENTS:
        group.addKnob(nuke.Tab_Knob("grp_" + eid, label, nuke.TABBEGINCLOSEDGROUP))
        group.addKnob(nuke.Boolean_Knob(eid + "On", "Enable", False))
        inten = nuke.Double_Knob(eid + "Intensity", "Intensity")
        inten.setRange(0, DEFAULT_INTENSITY[eid] * 10)
        inten.setValue(DEFAULT_INTENSITY[eid])
        group.addKnob(inten)
        srck = nuke.Enumeration_Knob(eid + "Source", "Source", SOURCES)
        srck.setValue(src)
        srck.setTooltip("All highlights: every bright pixel. Hotspot: one point per light.")
        group.addKnob(srck)
        tint = nuke.Color_Knob(eid + "Tint", "Tint")
        tint.setValue([1.0, 1.0, 1.0])
        group.addKnob(tint)
        for suffix, lab, kind, lo, hi, default, tip in EXTRA[eid]:
            group.addKnob(_make_knob(nuke, eid + suffix, lab, kind, lo, hi, default, tip))
        if eid in COLOURED:
            for k in colour_knobs(nuke, eid):
                group.addKnob(k)
        off = nuke.XY_Knob(eid + "Offset", "Offset")
        off.setValue([0.0, 0.0])
        off.setTooltip("Art-direct move in plate px, on top of the element's physical position.")
        group.addKnob(off)
        group.addKnob(nuke.Tab_Knob("grp_%s_end" % eid, "", nuke.TABENDGROUP))

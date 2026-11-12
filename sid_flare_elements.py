# Sid Lens Flare -- flare elements (v4).
#
# Switchable elements of the Lens Flare node:
#   centred on each light : Streak (up to 8 slots), Spike Ball, Shimmer, Sparkle, Glint, Bloom
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
# Line profile (v4): every line / ring shape (Streak, Spike Ball, Shimmer,
# Sparkle, Glint spikes, Starburst spikes, Rings, Ring / Halo) has the
# cross-section p(d) = clamp((T/2-|d|)/max(AA,S)+0.5,0,1): Thickness T is the
# solid core width, Softness S the edge falloff width. The kernel stores its
# exact pixel coverage (p integrated over the 1 working px pixel box, see
# profile()), not p sampled at the pixel centre: a point-sampled line thinner
# than ~1 px falls between pixels (BF-12). The constants it needs (hw, sf, hp,
# hm, kq, wi) live on flareGeo, per prefix.
#
# Rules: TCL generators are pure string functions; the graph is built in the
# node's single nuke.tcl() call; no internal node lookups from Python; no
# space inside any single {{...}}; temp names never r/g/b/a/x/y/z; gain nodes
# never disabled (an element that is off is disabled upstream AND multiplied
# by its On knob, which is 0); at most 4 temps per Expression.
#
# Strict ASCII.


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
MAX_SPARKLE_POINTS = 32
SPARKLE_POINTS = (4, 6, 8, 16, 32)       # Points enum index -> number of points
MAX_SHIMMER_RAYS = 128
STREAK_SLOTS = 8
# Default Angle per streak slot, so a slot added with + does not sit on top of
# the ones before it.
STREAK_DEFAULT_ANGLES = (0.0, 90.0, 45.0, 135.0, 22.5, 112.5, 67.5, 157.5)
MAX_ORBS = 64

# Kernel centre (BF-12b). Convolve2 puts a kernel's origin on the pixel with
# index floor(width/2), floor(height/2) (measured in Nuke 17.1 on even and odd
# formats from 8x6 to 2048x858), i.e. on that pixel's CENTRE. Every kernel is
# drawn about it: dx, dy are pixel offsets from that pixel (pixel centre x+0.5
# minus (floor(width/2)+0.5)). The old x+0.5-width/2 was the pixel boundary on
# even canvases, half a pixel off (output shifted by -0.5 working px) and a
# 1 px line fell between two rows.
KDX = "(x-floor(width/2))"
KDY = "(y-floor(height/2))"

# Added to every kernel channel that is normalized (alpha of mono kernels;
# r, g, b and alpha of coloured kernels) so the centre pixel(s) always carry
# a tiny weight: Convolve2 normalize divides each channel by that kernel
# channel's sum, and a zero-sum channel (a ring larger than the canvas, or a
# colour with no green) would blow up.
CENTRE_FLOOR = ("((%s)*(%s)+(%s)*(%s)<1?0.000001:0)" % (KDX, KDX, KDY, KDY))

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
    # Per streak slot (knobs streak0Length ... streak7Length, see streak_slot_knob_names()).
    "streak": (
        ("Angle", "Angle", "d", -180, 180, 0, "0 = horizontal (anamorphic)."),
        ("Length", "Length", "d", 1, 2000, 300, "Half-length in plate px."),
        ("Thickness", "Thickness", "d", 0.5, 40, 3, "Solid core width in plate px."),
        ("Softness", "Softness", "d", 0, 40, 1.8, "Edge falloff width in plate px (0 = crisp edge)."),
        ("Falloff", "Falloff", "d", 0.3, 8, 1, "1 = soft tail, 2 = Gaussian, higher = hard end."),
    ),
    "spikeBall": (
        ("Rays", "Rays", "i", 8, MAX_SPIKE_RAYS, 32, "Number of rays. Max %d." % MAX_SPIKE_RAYS),
        ("Length", "Length", "d", 1, 1000, 120, "Plate px."),
        ("Variation", "Length Variation", "d", 0, 1, 0.6, None),
        ("Thickness", "Thickness", "d", 0.5, 10, 1, "Solid core width in plate px."),
        ("Softness", "Softness", "d", 0, 10, 0.6, "Edge falloff width in plate px (0 = crisp edge)."),
        ("Seed", "Seed", "i", 0, 9999, 0, None),
    ),
    "shimmer": (
        ("Rays", "Rays", "i", 16, MAX_SHIMMER_RAYS, 48, "Number of thin rays at random angles. Max %d." % MAX_SHIMMER_RAYS),
        ("Length", "Length", "d", 1, 1000, 150, "Plate px."),
        ("Thickness", "Thickness", "d", 0.5, 10, 1, "Solid core width in plate px."),
        ("Softness", "Softness", "d", 0, 10, 0.6, "Edge falloff width in plate px (0 = crisp edge)."),
        ("Speed", "Speed", "d", 0, 10, 1, "Flicker speed of each ray's brightness; 0 = static."),
        ("Seed", "Seed", "i", 0, 9999, 0, "Re-rolls the ray angles and flicker."),
    ),
    "sparkle": (
        ("Points", "Points", "e:4|6|8|16|32", 0, 0, 0, None),
        ("Size", "Size", "d", 1, 400, 40, "Plate px."),
        ("Thickness", "Thickness", "d", 0.5, 20, 2.8, "Solid core width of the rays in plate px."),
        ("Softness", "Softness", "d", 0, 20, 1.7, "Edge falloff width in plate px (0 = crisp edge)."),
        ("Rotation", "Rotation", "d", -180, 180, 0, None),
        ("Speed", "Twinkle Speed", "d", 0, 10, 0, "0 = static."),
    ),
    "glint": (
        ("Size", "Size", "d", 0.5, 100, 6, "Core size in plate px."),
        ("SpikeLength", "Spike Length", "d", 1, 500, 40, "Plate px."),
        ("Thickness", "Thickness", "d", 0.5, 20, 2.4, "Solid core width of the spikes in plate px."),
        ("Softness", "Softness", "d", 0, 20, 1.4, "Edge falloff width in plate px (0 = crisp edge)."),
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
        ("Count", "Count", "i", 1, MULTI_IRIS_SLOTS, 5, "Number of irises. Max %d." % MULTI_IRIS_SLOTS),
        ("Spread", "Spread", "d", 0, 2, 1.2, "Positions are spread over -Spread..+Spread along the axis."),
        ("SizeMin", "Size Min", "d", 1, 1000, 15, "Plate px at f/2.8. Shapes larger than the canvas are capped."),
        ("SizeMax", "Size Max", "d", 1, 1000, 70, "Plate px at f/2.8. Shapes larger than the canvas are capped."),
        ("ColorVar", "Colour Variation", "d", 0, 1, 0.5, None),
        ("Seed", "Seed", "i", 0, 9999, 0, None),
    ),
    "rings": (
        ("Shape", "Shape", "e:Procedural|Input", 0, 0, 0,
         "Procedural: drawn rings. Input: use the image on the Ring input, which appears on the node while Input is "
         "chosen, as the ring shape (luminance = shape, colour = colour; Thickness and Softness no longer apply; "
         "nothing connected = procedural)."),
        ("Count", "Count", "i", 1, RING_SLOTS, 2, "Number of rings. Max %d." % RING_SLOTS),
        ("Position", "Position", "d", -2, 2, -0.9, "First ring along the flare axis."),
        ("Spacing", "Spacing", "d", -1, 1, 0.25, "Axis distance between rings."),
        ("Radius", "Radius", "d", 2, 1500, 120, "Plate px. Shapes larger than the canvas are capped."),
        ("Thickness", "Thickness", "d", 0.5, 50, 12, "Solid core width in plate px."),
        ("Softness", "Softness", "d", 0, 50, 6, "Edge falloff width in plate px (0 = crisp edge)."),
    ),
    "caustic": (
        ("Shape", "Shape", "e:Procedural|Input", 0, 0, 0,
         "Procedural: the cusped caustic. Input: use the image on the Caustic input, which appears on the node while "
         "Input is chosen, as the shape (luminance = shape, colour = colour; nothing connected = procedural)."),
        ("Position", "Position", "d", -2, 2, -0.3, None),
        ("Size", "Size", "d", 2, 1000, 90, "Radius in plate px. Shapes larger than the canvas are capped."),
        ("Sharpness", "Edge Sharpness", "d", 0.5, 10, 3, "Higher = thinner, brighter caustic edge."),
    ),
    "ringHalo": (
        ("Shape", "Shape", "e:Procedural|Input", 0, 0, 0,
         "Procedural: a drawn ring. Input: use the image on the Ring input (shared with Rings), which appears on the "
         "node while Input is chosen, as the halo shape. Only in Centre = Light (Halo): the ring around the optical "
         "centre is always drawn. Nothing connected = procedural."),
        ("Centre", "Centre", "e:Optical Centre (Orbital / Rainbow Ring)|Light (Halo)", 0, 0, 0,
         "Optical Centre: a ring around the optical centre, lit by nearby light. "
         "Light: a halo ring around each light."),
        ("Radius", "Radius", "d", 0.02, 1.5, 0.45, "Fraction of frame height."),
        ("Width", "Width", "d", 0.5, 300, 40, "Solid core width of the ring in plate px."),
        ("Softness", "Softness", "d", 0, 300, 10, "Edge falloff width in plate px (0 = crisp edge)."),
        ("Arc", "Arc", "d", 0, 1, 0.7, "Optical Centre mode: 0 = evenly lit ring, 1 = only the arc facing the light. "
         "The even part uses a fixed reference size (600 plate px), independent of Arc Falloff."),
        ("ArcFalloff", "Arc Falloff", "d", 10, 3000, 600, "How far light reaches around the ring (plate px)."),
    ),
    "orbs": (
        ("Count", "Count", "i", 8, MAX_ORBS, 24, "Number of orbs. Max %d." % MAX_ORBS),
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
    ("ColorStrength", "Colour Strength", "d", 0, 1, 1,
     "How much of the Spectrum / Ramp colour is applied: 0 = plain Tint (white), 1 = full colour. "
     "Each channel is mixed from 1 toward the band colour."),
    ("ColorWidth", "Colour Width", "d", 0.05, 1, 1,
     "Filled shapes: fraction of the radius, in from the edge, that carries the colour (1 = the whole "
     "shape, less leaves a white core). Rings: how much of the ring's width the colour band spans."),
    ("ColorBalance", "Balance Colours", "b", 0, 0, True,
     "On: the colours are balanced so the shape keeps its overall colour balance (neutral white core, "
     "channel means preserved), which can look washed out. Off: the colours appear exactly as picked "
     "(brighter and more saturated). Ring / Halo in Optical Centre mode never balances."),
    ("LightColor", "Light Colour", "d", 0, 1, 1, "1 = take the light's own colour, 0 = treat the light as white."),
    ("Noise", "Noise", "d", 0, 1, 0, "Breaks up brightness around the shape."),
    ("NoiseScale", "Noise Scale", "d", 1, 64, 8, "Number of noise features around the shape."),
    ("NoiseSpeed", "Noise Speed", "d", 0, 10, 0, "0 = static."),
)
# Saturated rainbow, red inside to blue outside (05c; v3 stops were pale and averaged near neutral).
RAMP_DEFAULTS = (((1.0, 0.0, 0.0), 0.0), ((1.0, 0.9, 0.0), 0.35), ((0.0, 1.0, 0.2), 0.65), ((0.1, 0.3, 1.0), 1.0))

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


def streak_slot_prefix(i):
    return "streak%d" % i


def streak_slot_knob_names(i):
    """Knobs of one streak slot (shown while the slot is below Count; the Offset
    XY knob also needs its Use Offset)."""
    pf = streak_slot_prefix(i)
    return ([pf + "Hdr", pf + "Intensity", pf + "Tint"] + [pf + spec[0] for spec in EXTRA["streak"]]
            + [pf + "OffsetOn", pf + "Offset"])


def knob_names(eid):
    """Every knob an element owns that the graph reads (for tests and the knob
    builder). The Streak's + / - buttons and slot headings are not read by the
    graph and are not listed."""
    if eid == "streak":
        names = ["streakOn", "streakSource", "streakCount"]
        for i in range(STREAK_SLOTS):
            names += [n for n in streak_slot_knob_names(i) if not n.endswith("Hdr")]
        return names
    names = [eid + "On", eid + "Intensity", eid + "Source", eid + "Tint", eid + "Offset", eid + "OffsetOn"]
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
    """Art-direct translate (plate px) on an element's final output; only
    applied while the element's Use Offset checkbox is on."""
    return ("Transform {\n translate {{parent.%sOffset.x*%s*parent.%sOffsetOn} "
            "{parent.%sOffset.y*%s*parent.%sOffsetOn}}\n name %s\n}"
            % (prefix, RES, prefix, prefix, RES, prefix, name))


OFFSET_PREFIXES = ["ghosts", "star"]    # + every element id (see offset_prefixes())


def offset_prefixes():
    """Every prefix with Use Offset + Offset; the Streak has one per slot."""
    out = list(OFFSET_PREFIXES)
    for eid, _l, _f, _s in ELEMENTS:
        if eid == "streak":
            out += [streak_slot_prefix(i) for i in range(STREAK_SLOTS)]
        else:
            out.append(eid)
    return out


def offset_knobs(nuke, prefix):
    """'Use Offset' checkbox + the Offset XY knob. The XY knob (and so its
    Viewer handle) is hidden until Use Offset is ticked, so the handles of
    the elements you are not moving don't pile up in the Viewer."""
    use = nuke.Boolean_Knob(prefix + "OffsetOn", "Use Offset", False)
    use.setFlag(nuke.STARTLINE)
    use.setTooltip("Show and apply the Offset for this element only.")
    off = nuke.XY_Knob(prefix + "Offset", "Offset")
    off.setValue([0.0, 0.0])
    off.setTooltip("Art-direct move in plate px, on top of the physical position.")
    off.setVisible(False)
    return [use, off]


def _streak_count(group, knobs):
    if "streakCount" not in knobs:
        return None                        # a v3 node (single streak, no slots)
    return max(1, min(STREAK_SLOTS, int(group["streakCount"].value())))


def _streak_slot_of(prefix):
    if prefix.startswith("streak") and prefix[6:].isdigit():
        return int(prefix[6:])
    return None


def sync_offset_visibility(group, prefix=None):
    """Show each Offset XY knob only while its Use Offset is on, and only the
    streak slots below Streak Count. Knob visibility is not saved with the
    script, so this also runs on load (the group's onCreate). With `prefix`
    only that prefix's Offset knob is updated."""
    knobs = group.knobs()
    count = _streak_count(group, knobs)
    if prefix is None and count is not None:
        for i in range(STREAK_SLOTS):
            for name in streak_slot_knob_names(i):
                if name == streak_slot_prefix(i) + "Offset":
                    continue                                      # Offset XY: handled below
                if name in knobs:
                    group[name].setVisible(i < count)
    # "streak": the single streak of a v3 node (skipped where its knobs are absent).
    for pf in ([prefix] if prefix else offset_prefixes() + ["streak"]):
        if pf + "OffsetOn" in knobs and pf + "Offset" in knobs:
            show = bool(group[pf + "OffsetOn"].value())
            slot = _streak_slot_of(pf)
            if slot is not None and count is not None:
                show = show and slot < count
            group[pf + "Offset"].setVisible(show)


SQUEEZE_STREAK_TINT = (0.55, 0.75, 1.0)


def _close(a, b):
    return len(a) == len(b) and all(abs(x - y) < 1e-6 for x, y in zip(a, b))


def squeeze_streak_defaults(group):
    """Anamorphic Squeeze above 1x gives the first Streak (the horizontal one) the blue anamorphic streak tint, but
    only while that slot is still untouched (angle 0 and a white tint); back at 1x it returns to white, but only if
    the tint is still the one set here. A slot the user changed is never touched."""
    pf = streak_slot_prefix(0)
    if pf + "Tint" not in group.knobs() or pf + "Angle" not in group.knobs():
        return
    tint = list(group[pf + "Tint"].value())
    if float(group[pf + "Angle"].value()) != 0.0:
        return
    if group["squeeze"].value() != SQUEEZES[0]:
        if _close(tint, [1.0, 1.0, 1.0]):
            group[pf + "Tint"].setValue(list(SQUEEZE_STREAK_TINT))
    elif _close(tint, SQUEEZE_STREAK_TINT):
        group[pf + "Tint"].setValue([1.0, 1.0, 1.0])


def streak_step(group, delta):
    """+ / - buttons: change Streak Count by `delta` (1..STREAK_SLOTS) and show
    or hide the slot knobs. Touches only the Group's own knobs."""
    n = max(1, min(STREAK_SLOTS, int(group["streakCount"].value()) + int(delta)))
    group["streakCount"].setValue(n)
    sync_offset_visibility(group)
    return n


def _centre_temps():
    return [" temp_name0 dx", " temp_expr0 {%s}" % KDX,
            " temp_name1 dy", " temp_expr1 {%s}" % KDY]


# -- line profile (v4) -------------------------------------------------------------

# (prefix, Thickness knob, Softness knob) of every line / ring shape. flareGeo
# holds hw_<prefix> = Thickness/2 and sf_<prefix> = max(AA, Softness), both in
# working px; rings also get bw_<prefix>, the full band width 2*hw+sf.
PROFILE_PREFIXES = ([(streak_slot_prefix(i), "streak%dThickness" % i, "streak%dSoftness" % i)
                     for i in range(STREAK_SLOTS)]
                    + [(e, e + "Thickness", e + "Softness") for e in ("spikeBall", "shimmer", "sparkle", "glint", "rings")]
                    + [("ringHalo", "ringHaloWidth", "ringHaloSoftness"), ("star", "starThickness", "starSoftness")])
BAND_PREFIXES = ("rings", "ringHalo")


def hw_ref(prefix):
    return "%s.hw_%s" % (GEO, prefix)


def sf_ref(prefix):
    return "%s.sf_%s" % (GEO, prefix)


def bw_ref(prefix):
    return "%s.bw_%s" % (GEO, prefix)


def geo_ref(prefix, name):
    return "%s.%s_%s" % (GEO, name, prefix)


def profile(d_expr, prefix):
    """Exact pixel coverage of the line profile at signed distance `d_expr`
    (working px, perpendicular to the line / radial for rings) from the
    centre-line: the integral of p(d) = clamp((hw-|d|)/sf+0.5,0,1) over the
    1 px box [d-0.5,d+0.5] (a pixel of the kernel canvas).

    With r(u) = clamp(u/sf+0.5,0,1) and its antiderivative A(u) = u for
    u >= sf/2, (u+sf/2)^2/(2 sf) for |u| < sf/2, 0 below, the integral of p up
    to d is W(d) = A(hw+d) (d <= 0) or Winf - A(hw-d) (d > 0), and
    coverage = W(d+0.5) - W(d-0.5). With a = |d| and Aq(v) = A(hw-v)
    = clamp(hp-v,0,sf)^2*kq + max(0,hm-v) (hp = hw+sf/2, hm = hw-sf/2,
    kq = 1/(2 sf), Winf = wi):
        a >= 0.5: Aq(a-0.5) - Aq(a+0.5)
        a <  0.5: wi - Aq(0.5-a) - Aq(a+0.5)
    Sums to Winf (= 2 hw once hw >= sf/2) across the line, so thin lines keep
    their energy and Convolve2 normalizes the rest."""
    hp, hm, sf, kq, wi = (geo_ref(prefix, n) for n in ("hp", "hm", "sf", "kq", "wi"))
    a = "abs(%s)" % d_expr

    def aq(v):
        return "(pow(clamp(%s-%s,0,%s),2)*%s+max(0,%s-%s))" % (hp, v, sf, kq, hm, v)

    return "((%s>=0.5?%s:%s-%s)-%s)" % (a, aq("(%s-0.5)" % a), wi, aq("(0.5-%s)" % a), aq("(%s+0.5)" % a))


def profile_geo_knobs():
    """(name, expr) of the flareGeo profile knobs (PROFILE_PREFIXES): hw
    (Thickness/2), sf (max(AA, Softness)), hp = hw+sf/2, hm = hw-sf/2,
    kq = 1/(2 sf), wi = Winf = 2*(min(hp,sf)^2*kq + max(0,hm)); rings also bw,
    the full band width 2*hw+sf."""
    out = []
    for prefix, thick, soft in PROFILE_PREFIXES:
        out.append(("hw_" + prefix, "parent.%s*%s/2" % (thick, RES)))
        out.append(("sf_" + prefix, "max(%g,parent.%s*%s)" % (AA, soft, RES)))
        out.append(("hp_" + prefix, "%s+%s/2" % (hw_ref(prefix), sf_ref(prefix))))
        out.append(("hm_" + prefix, "%s-%s/2" % (hw_ref(prefix), sf_ref(prefix))))
        out.append(("kq_" + prefix, "1/(2*%s)" % sf_ref(prefix)))
        out.append(("wi_" + prefix, "2*(pow(min(%s,%s),2)*%s+max(0,%s))"
                    % (geo_ref(prefix, "hp"), sf_ref(prefix), geo_ref(prefix, "kq"), geo_ref(prefix, "hm"))))
        if prefix in BAND_PREFIXES:
            out.append(("bw_" + prefix, "2*%s+%s" % (hw_ref(prefix), sf_ref(prefix))))
    return out


def _polar_temps():
    """Temps 0-1: rr, an (polar coordinates about the canvas centre)."""
    return [" temp_name0 rr", " temp_expr0 {hypot(%s,%s)}" % (KDX, KDY),
            " temp_name1 an", " temp_expr1 {atan2(%s,%s)}" % (KDY, KDX)]


def _ray(prefix, angle_expr, length_expr, falloff="1"):
    """One half-ray from the centre (temps rr, an): line coverage across,
    exp fall-off along."""
    return ("(cos(an-(%s))>0)*%s*exp(-pow(rr/max(0.01,%s),max(0.2,%s)))"
            % (angle_expr, profile("rr*sin(an-(%s))" % angle_expr, prefix), length_expr, falloff))


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


def colour_strength(prefix):
    return "clamp(%s,0,1)" % p(prefix, "ColorStrength")


def _band_colour(prefix, u, chan):
    """Spectrum (mode 1) or Ramp (mode 2) colour at band coordinate u, >= 0,
    mixed from white by Colour Strength (the same mix as colour_expr, so the
    balance quadrature matches the kernel at every strength)."""
    mode = p(prefix, "ColorMode")
    return "max(0,1+%s*((%s==1?%s:%s)-1))" % (colour_strength(prefix), mode, _spectrum(u, chan), _ramp(prefix, u, chan))


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


def ring_sample_offsets():
    """x_k across the ring band, in units of the full band width (-0.5..0.5)."""
    return [-0.5 + (k + 0.5) / RING_SAMPLES for k in range(RING_SAMPLES)]


def _ring_weights(prefix):
    """(name, expr) of the flareGeo weight knobs for a ring: the line profile
    at the RING_SAMPLES band samples and their sum. In band units the profile
    is clamp((0.5-|x|)*bw/sf,0,1) (bw = 2*hw+sf, see profile())."""
    names = [("w_%s_%d" % (prefix, k), "clamp(%g*%s/%s,0,1)" % (0.5 - abs(x), bw_ref(prefix), sf_ref(prefix)))
             for k, x in enumerate(ring_sample_offsets())]
    names.append(("w_%s_sum" % prefix, "+".join("%s.%s" % (GEO, n) for n, _e in names)))
    return names


def balance_weight_knobs(prefix, shape):
    """flareGeo helper knobs colour_balance(prefix, shape) reads."""
    return _filled_weights(prefix) if shape == "filled" else _ring_weights(prefix)


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
    ring: line profile across the band, 16 samples x_k = -0.5+(k+0.5)/16 of
      the full band width, weight = the profile there (flareGeo knobs
      w_<prefix>_k, _ring_weights), u = clamp(x_k/cw+0.5,0,1) as in ring_band.
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
            terms = []
            for k, xk in enumerate(ring_sample_offsets()):
                uk = "clamp(%g/%s+0.5,0,1)" % (xk, cw)
                terms.append("%s.w_%s_%d*%s" % (GEO, prefix, k, _band_colour(prefix, uk, ch)))
            body = "(%s)/%s.w_%s_sum" % ("+".join(terms), GEO, prefix)
        else:
            raise ValueError(shape)
        out.append("(%s==0?1:(%s))" % (mode, body))
    return tuple(out)


def balance_refs(prefix):
    """The balance gain for r, g, b: the flareGeo knobs holding
    colour_balance(prefix, ...), or 1 while Balance Colours is off."""
    return tuple("(%s?%s.bal_%s_%s:1)" % (p(prefix, "ColorBalance"), GEO, prefix, ch) for ch in "rgb")


def colour_expr(prefix, u, inside_band, chan):
    """Colour of the shape at band coordinate `u` for one channel (>= 0)."""
    mode = p(prefix, "ColorMode")
    return "max(0,1+%s*(((%s)?(%s==1?%s:(%s==2?%s:1)):1)-1))" % (
        colour_strength(prefix), inside_band, mode, _spectrum(u, chan), mode, _ramp(prefix, u, chan))


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


FLICKER_PHASES = (("r", 3.7), ("g", 7.9), ("b", 12.1))


def flicker_geo_knobs():
    """Master flicker gain per channel: fl_<c> = max(0, 1 + Amount*n0(t) +
    Colour Jitter*n_c(t)), n = noise at t = flareGeo.t_flicker (frame*Speed)
    and Seed; the jitter noise of each channel has its own phase. Amount and
    Jitter 0 give exactly 1 on every frame (no time dependence downstream)."""
    t = "%s.t_flicker*0.25+0.31" % GEO
    seed = "parent.flickerSeed*1.731"
    base = "parent.flickerAmount*noise(%s,%s+0.5)" % (t, seed)
    return [("fl_%s" % ch, "max(0,1+%s+parent.flickerJitter*noise(%s,%s+%g))" % (base, t, seed, ph))
            for ch, ph in FLICKER_PHASES]


def geo_tcl():
    """The flareGeo NoOp: pad, frame size and optical centre (working px), the
    animation times, every coloured prefix's colour balance, the line profile
    widths, the Shimmer ray table and the Master flicker gains, evaluated once
    per frame. Other nodes read them as flareGeo.<knob> (expression syntax; no
    Python node access). The only place `frame` appears in the graph."""
    knobs = [("padx", PADX_EXPR), ("pady", PADY_EXPR), ("fw", "flareDown.width"), ("fh", "flareDown.height"),
             ("cx", CX_EXPR), ("cy", CY_EXPR)]
    for prefix in list(COLOURED) + ["ghosts"]:
        knobs.append(("t_" + prefix, "frame*%s" % p(prefix, "NoiseSpeed")))
    knobs.append(("t_shimmer", "frame*%s" % p("shimmer", "Speed")))
    knobs.append(("t_sparkle", "frame*%s" % p("sparkle", "Speed")))
    knobs.append(("t_flicker", "frame*parent.flickerSpeed"))
    knobs.append(("sq", squeeze_expr()))
    knobs += flicker_geo_knobs()
    knobs += profile_geo_knobs()
    knobs += shimmer_geo_knobs()
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
    """STREAK_SLOTS streaks sharing Enable and Source. Slot i is live while
    i < Streak Count: past it the kernel and Convolve2 are disabled and the
    gain is multiplied by 0. Each slot has its own Offset."""
    e = "streak"
    out = [_source(e)]
    for i in range(STREAK_SLOTS):
        pf = streak_slot_prefix(i)
        off = "{{!parent.%sOn||parent.%sCount<=%d}}" % (e, e, i)
        th = "%s*pi/180" % p(pf, "Angle")
        body = [" temp_name0 al", " temp_expr0 {%s*cos(%s)+%s*sin(%s)}" % (KDX, th, KDY, th),
                " temp_name1 ac", " temp_expr1 {%s*cos(%s)-%s*sin(%s)}" % (KDY, th, KDX, th),
                " temp_name2 sl", " temp_expr2 {max(0.5,%s*%s)}" % (p(pf, "Length"), RES),
                " expr0 0", " expr1 0", " expr2 0",
                " expr3 {exp(-pow(abs(al)/sl,max(0.2,%s)))*%s}"
                % (p(pf, "Falloff"), profile("ac", pf))]
        out.append(_kernel(e, "%sKernel" % pf, body, off))
        out.append("set %sK [stack 0]" % pf)
        out.append(_convolve("%sK" % pf, "%s_src" % e, off, "%sConv" % pf))
        k = "parent.%sOn*(parent.%sCount>%d)*parent.%sIntensity" % (e, e, i, pf)
        out.append("Expression {\n temp_name0 kk\n temp_expr0 {%s}\n"
                   " expr0 {r*kk*parent.%sTint.r}\n expr1 {g*kk*parent.%sTint.g}\n expr2 {b*kk*parent.%sTint.b}\n"
                   " expr3 0\n name %sGain\n}" % (k, pf, pf, pf, pf))
        out.append(offset_tcl(pf, "%sOffsetT" % pf))
        out.append("set sk%d [stack 0]" % i)
    acc = "$sk0"
    for i in range(1, STREAK_SLOTS):
        out.append("push $sk%d\npush %s\nMerge2 { inputs 2 operation plus also_merge all }\nset sk_acc [stack 0]" % (i, acc))
        acc = "$sk_acc"
    out.append("push %s\nset el_%s [stack 0]" % (acc, e))
    return "\n".join(out)


def _spike_ball_tcl():
    e = "spikeBall"
    seed = p(e, "Seed")
    sl = "%s*%s" % (p(e, "Length"), RES)
    terms = []
    for k in range(MAX_SPIKE_RAYS):
        ang = "2*pi*%s" % _hash(k, 12.9898, 78.233, seed)
        length = "%s*(1-%s*%s)" % (sl, p(e, "Variation"), _hash(k, 39.3467, 11.135, seed))
        terms.append("(%d<%s)*%s" % (k, p(e, "Rays"), _ray(e, ang, length)))
    body = _polar_temps() + [
        " expr0 0", " expr1 0", " expr2 0",
        " expr3 {rr<0.5?0:%s}" % "+".join(terms),
    ]
    return _finish(e, [_source(e)], _kernel(e, "spikeBallKernel", body))


def shimmer_geo_knobs():
    """flareGeo knobs of the Shimmer rays: direction (sh_c<k>, sh_s<k> = cos,
    sin of a random angle from Seed) and brightness sh_b<k> = 0.5+0.5*noise
    over flareGeo.t_shimmer, 0 for rays past Rays. Once per frame, so the
    kernel does no trig per ray."""
    e = "shimmer"
    seed = p(e, "Seed")
    out = []
    for k in range(MAX_SHIMMER_RAYS):
        ang = "2*pi*%s" % _hash(k, 12.9898, 78.233, seed)
        out.append(("sh_c%d" % k, "cos(%s)" % ang))
        out.append(("sh_s%d" % k, "sin(%s)" % ang))
        out.append(("sh_b%d" % k, "(%d<%s)*clamp(0.5+0.5*noise(%g,%s*1.37+0.31,%s*0.2),0,1)"
                    % (k, p(e, "Rays"), k * 1.618 + 0.5, seed, time_ref(e))))
    return out


def _shimmer_tcl():
    """Rays thin half-rays at random angles with the line profile and an exp
    fall-off (Length); each ray's brightness flickers (sh_b<k> on flareGeo)."""
    e = "shimmer"
    terms = []
    for k in range(MAX_SHIMMER_RAYS):
        c, sn, b = ("%s.sh_%s%d" % (GEO, t, k) for t in "csb")
        terms.append("%s*((dx*%s+dy*%s)>0)*%s" % (b, c, sn, profile("dy*%s-dx*%s" % (c, sn), e)))
    body = _centre_temps() + [
        " expr0 0", " expr1 0", " expr2 0",
        " expr3 {hypot(dx,dy)<0.5?0:exp(-hypot(dx,dy)/max(0.01,%s*%s))*(%s)}"
        % (p(e, "Length"), RES, "+".join(terms)),
    ]
    return _finish(e, [_source(e)], _kernel(e, "shimmerKernel", body))


def sparkle_points_expr():
    pts = p("sparkle", "Points")
    out = "%d" % SPARKLE_POINTS[-1]
    for i in range(len(SPARKLE_POINTS) - 2, -1, -1):
        out = "(%s==%d?%d:%s)" % (pts, i, SPARKLE_POINTS[i], out)
    return out


def _sparkle_tcl():
    e = "sparkle"
    npts = sparkle_points_expr()
    sz = "max(0.01,%s*%s)" % (p(e, "Size"), RES)
    terms = []
    for k in range(MAX_SPARKLE_POINTS):
        ang = "%s*pi/180+%d*2*pi/%s" % (p(e, "Rotation"), k, npts)
        tw = "(0.6+0.4*sin(%s+%d*2.399))" % (time_ref(e), k)
        terms.append("(%d<%s)*%s*%s" % (k, npts, tw, _ray(e, ang, sz)))
    body = _polar_temps() + [
        " expr0 0", " expr1 0", " expr2 0",
        " expr3 {(rr<0.5?0:%s)+4*exp(-pow(rr/max(0.5,%s*0.06),2)/2)}" % ("+".join(terms), sz),
    ]
    return _finish(e, [_source(e)], _kernel(e, "sparkleKernel", body))


def _glint_tcl():
    e = "glint"
    gl = "%s*%s" % (p(e, "SpikeLength"), RES)
    rays = []
    for k in range(4):
        ang = "%s*pi/180+%d*pi/2" % (p(e, "Angle"), k)
        rays.append(_ray(e, ang, gl))
    gs = "hypot(%s*%s/2.355,%g)" % (p(e, "Size"), RES, AA)
    body = _polar_temps() + [
        " expr0 0", " expr1 0", " expr2 0",
        " expr3 {8*exp(-pow(rr/%s,2)/2)+(rr<0.5?0:%s)}" % (gs, "+".join(rays)),
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
SQUEEZES = ["1x", "1.33x", "1.5x", "1.8x", "2x"]
SQUEEZE_VALUES = (1.0, 1.33, 1.5, 1.8, 2.0)
SQ = GEO + ".sq"                                  # anamorphic squeeze factor (flareGeo)


def squeeze_expr():
    """Squeeze menu index -> factor, as an expression."""
    out = "%g" % SQUEEZE_VALUES[-1]
    for i in range(len(SQUEEZE_VALUES) - 2, -1, -1):
        out = "(parent.squeeze==%d?%g:%s)" % (i, SQUEEZE_VALUES[i], out)
    return out


def shape_temps(radius_expr, squeeze=True, clamp=True):
    """Centred kernel temps: dist, sec, aw (aperture angle), R (clamped to the canvas unless `clamp` is off: an
    image kernel is already sized from the clamped radius). With `squeeze` the kernel x axis is scaled by the
    anamorphic Squeeze, so the shape comes out 1/Squeeze as wide (an oval, taller than wide); rings stay round."""
    kx = "%s*%s" % (KDX, SQ) if squeeze else KDX
    return [" temp_name0 dist", " temp_expr0 {hypot(%s,%s)}" % (kx, KDY),
            " temp_name1 sec", " temp_expr1 {2*pi/clamp(parent.blades,3,12)}",
            " temp_name2 aw", " temp_expr2 {atan2(%s,%s)-parent.apRotation*pi/180}" % (KDY, kx),
            " temp_name3 R", SHAPE_TEMPS_R % radius_expr if clamp else " temp_expr3 {%s}" % radius_expr]


# -- kernels from a connected image (Caustic / Ring / Aperture inputs) ------------------------------

def kernel_radius(radius_expr):
    """Kernel radius clamped to the padded canvas, exactly as shape_temps' R."""
    return "max(0.5,min(%s,min(overscanPad.width,overscanPad.height)/2-4))" % radius_expr


def custom_kernel_tcl(prefix, tag, src_var, radius, off_inner, active_inner, squeeze, slot=0):
    """Kernel from the image on an optional input, leaving it on the stack. The image is fitted (aspect kept) into a
    square box of odd side 2*floor(R)+1, squeezed horizontally to an odd width 2*floor(R/Squeeze)+1 when `squeeze`, and
    used as the kernel image itself: its centre pixel is exactly Convolve2's origin (pixel floor(w/2), floor(h/2)),
    so the kernel is centred to the pixel like the drawn ones (BF-12b). Read as alpha = luminance (the shape), rgb =
    the image colour times the colour system (Tint ignores the colour, Spectrum / Ramp tint it across the radius),
    with the same normalisation floor as every kernel. Disabled unless the element is on and the input is chosen and
    connected (`active_inner`)."""
    off = "{{%s||!(%s)}}" % (off_inner, active_inner)
    rr = kernel_radius(radius)
    side = "(2*floor(%s)+1)" % rr
    out = ["push $%s\nReformat {\n type \"to box\"\n box_width {{%s}}\n box_height {{%s}}\n box_fixed true\n"
           " resize fit\n disable %s\n name %sCFit\n}" % (src_var, side, side, off, tag)]
    if squeeze:
        out.append("Reformat {\n type \"to box\"\n box_width {{2*floor(%s/%s)+1}}\n box_height {{%s}}\n"
                   " box_fixed true\n resize distort\n disable %s\n name %sCSq\n}" % (rr, SQ, side, off, tag))
    u, band = filled_band(prefix)
    nz = noise_expr(prefix, "aw", slot)
    lines = list(shape_temps(rr, squeeze, False))
    for i, ch in enumerate("rgb"):
        lines.append(" expr%d {max(0,%s)*%s*%s}" % (i, ch, nz, colour_expr(prefix, u, band, ch)))
    lines.append(" expr3 {max(0,0.2126*r+0.7152*g+0.0722*b)*%s}" % nz)
    out.append("Expression {\n%s\n disable %s\n name %sCKernel\n}" % ("\n".join(with_floor(lines)), off, tag))
    return "\n".join(out)


CUSTOM_INPUTS = ("in_caustic", "in_ring", "in_aperture")


def mean_colour_tcl():
    """For every custom-shape input a uniform padded-canvas image of its average colour ($<input>_mean): the input
    shrunk to one pixel (Parzen filter: a non-negative weighted average) and stretched back. Convolve2 normalizes
    each colour channel's kernel to sum 1, so an image kernel's colour has to be restored by the ratio of its mean
    channel to its mean luminance (custom_balance_tcl), the same job colour_balance does for drawn shapes."""
    out = []
    for var in CUSTOM_INPUTS:
        name = "".join(w.capitalize() for w in var.split("_")[1:])
        out.append("push $%s\nReformat {\n type \"to box\"\n box_width 1\n box_height 1\n box_fixed true\n resize distort\n"
                   " filter Parzen\n name %sMean1\n}\nReformat {\n type \"to box\"\n box_width {{overscanPad.width}}\n"
                   " box_height {{overscanPad.height}}\n box_fixed true\n resize distort\n filter impulse\n name %sMean\n}\n"
                   "set %s_mean [stack 0]" % (var, name, name, var))
    return "\n".join(out)


def custom_balance_tcl(prefix, tag, src_var, active_inner):
    """After an element's gain: restore the colour an image kernel carries (channel mean / luminance mean of the
    image, from mean_colour_tcl). Only while the image kernel is active and a colour mode with Balance Colours is
    on; otherwise the node is disabled and passes the gain through (B = the stream, input 0)."""
    on = "(%s)&&parent.%sColorMode>0&&parent.%sColorBalance" % (active_inner, prefix, prefix)
    rows = "\n".join(" expr%d {B.%s*A.%s/lm}" % (i, ch, ch) for i, ch in enumerate("rgb"))
    return ("set %sBS [stack 0]\npush $%s_mean\npush $%sBS\nMergeExpression {\n inputs 2\n temp_name0 lm\n"
            " temp_expr0 {max(0.000001,0.2126*A.r+0.7152*A.g+0.0722*A.b)}\n%s\n expr3 {B.a}\n disable {{!(%s)}}\n name %sCBal\n}"
            % (tag, src_var, tag, rows, on, tag))


def pick_kernel_tcl(tag, proc_tcl, custom_tcl, active_inner):
    """Procedural kernel (`proc_tcl`) or the image kernel (`custom_tcl`), picked by `active_inner`. Leaves the
    pick on the stack."""
    return "\n".join([proc_tcl, "set %sKP [stack 0]" % tag, custom_tcl, "set %sKC [stack 0]" % tag,
                      "push $%sKC\npush $%sKP\nSwitch {\n inputs 2\n which {{%s}}\n name %sKSel\n}" % (tag, tag, active_inner, tag)])


def custom_active(shape_knob, input_name, extra="1"):
    """Expression: the element's Shape is Input, the input has an image, and `extra` holds."""
    return "parent.%s==1&&%s.bbox.w>1&&(%s)" % (shape_knob, input_name + "Src", extra)


APERTURE_EDGE = "lerp(R*cos(sec/2)/cos(aw-sec*floor(aw/sec)-sec/2),R,parent.apRoundness)"


def iris_shape(soft_expr):
    return "clamp((%s-dist)/max(0.5,%s)+0.5,0,1)" % (APERTURE_EDGE, soft_expr)


def filled_band(prefix):
    """(u, inside_band) for filled shapes: colour lives in the outer
    Colour Width fraction of the radius."""
    cw = "clamp(%s,0.05,1)" % p(prefix, "ColorWidth")
    return ("clamp((dist-R*(1-%s))/(R*%s),0,1)" % (cw, cw), "dist>R*(1-%s)" % cw)


def _coloured_axial(e, tag, pos, off, kernel_body_shape, radius, gain_on, chan_tint=("1", "1", "1"), slot=0,
                    custom=None):
    """One coloured axial copy: transform -> RGBA kernel -> picked convolve -> gain. `custom` = (input var,
    active expression) adds the image kernel from an optional input, picked while active."""
    u, band = filled_band(e)
    out = [_axial_copy(e, pos, off, "%sCopy" % tag), "set %sT [stack 0]" % tag]
    lines = coloured_kernel_lines(e, shape_temps(radius), kernel_body_shape, u, band, "aw", slot)
    kernel = "push $hl\nExpression {\n%s\n disable %s\n name %sKernel\n}" % ("\n".join(with_floor(lines)), off, tag)
    if custom:
        kernel = pick_kernel_tcl(tag, kernel, custom_kernel_tcl(e, tag, custom[0], radius, off.strip("{}"), custom[1], True, slot),
                                 custom[1])
    out.append(kernel)
    out.append("set %sK [stack 0]" % tag)
    out.append(coloured_conv_tcl(e, "%sK" % tag, "%sT" % tag, off.strip("{}"), tag))
    bal = balance_refs(e)
    if custom:                                         # an image kernel carries its own colour balance
        bal = tuple("((%s)?1:%s)" % (custom[1], b) for b in bal)
    chan = tuple("%s*%s" % (b, t) for b, t in zip(bal, chan_tint))
    out.append(_gain(e, "%sGain" % tag, "%s/pow(%s,2)" % (gain_on, pos), chan))
    if custom:
        out.append(custom_balance_tcl(e, tag, custom[0], custom[1]))
    return "\n".join(out)


def _iris_tcl():
    e = "iris"
    pos = _safe_pos(p(e, "Position"))
    radius = "%s*%s*2.8/parent.effFstop" % (p(e, "Size"), RES)
    body = _coloured_axial(e, "iris", pos, _on(e), iris_shape("%s*%s" % (p(e, "Softness"), RES)), radius, "1",
                           custom=("in_aperture", custom_active("apShape", "Aperture")))
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
                                   "(parent.%sCount>%d)" % (e, i), tint, slot=i,
                                   custom=("in_aperture", custom_active("apShape", "Aperture"))))
        out.append("set mi%d [stack 0]" % i)
    acc = "$mi0"
    for i in range(1, MULTI_IRIS_SLOTS):
        out.append("push $mi%d\npush %s\nMerge2 { inputs 2 operation plus also_merge all }\nset mi_acc [stack 0]" % (i, acc))
        acc = "$mi_acc"
    out.append("push %s\n%s\nset el_%s [stack 0]" % (acc, offset_tcl(e, "multiIrisOffsetT"), e))
    return "\n".join(out)


def ring_band(prefix, offset_expr):
    """u across a ring: 0 inside .. 1 outside over the ring's full band width
    (Thickness + Softness, flareGeo.bw_<prefix>) x Colour Width."""
    cw = "clamp(%s,0.05,1)" % p(prefix, "ColorWidth")
    return "clamp((%s)/(%s*%s)+0.5,0,1)" % (offset_expr, bw_ref(prefix), cw)


def ring_profile(prefix):
    """(shape, u, inside_band) for a ring of radius R with the line profile."""
    return (profile("dist-R", prefix), ring_band(prefix, "dist-R"), "1")


def _rings_tcl():
    e = "rings"
    out = [_source(e, True)]
    for i in range(RING_SLOTS):
        off = "{{!parent.%sOn||parent.%sCount<=%d}}" % (e, e, i)
        pos = _safe_pos("(%s+%d*%s)" % (p(e, "Position"), i, p(e, "Spacing")))
        tag = "rings%d" % i
        out.append(_axial_copy(e, pos, off, "%sCopy" % tag))
        out.append("set %sT [stack 0]" % tag)
        shape, u, band = ring_profile(e)
        radius = "%s*%s*(1+%d*0.18)" % (p(e, "Radius"), RES, i)
        lines = coloured_kernel_lines(e, shape_temps(radius, False), shape, u, band, "aw", i)
        kernel = "push $hl\nExpression {\n%s\n disable %s\n name %sKernel\n}" % ("\n".join(with_floor(lines)), off, tag)
        active = custom_active("ringsShape", "Ring")
        out.append(pick_kernel_tcl(tag, kernel, custom_kernel_tcl(e, tag, "in_ring", radius, off.strip("{}"), active, False, i),
                                   active))
        out.append("set %sK [stack 0]" % tag)
        out.append(coloured_conv_tcl(e, "%sK" % tag, "%sT" % tag, off.strip("{}"), tag))
        out.append(_gain(e, "%sGain" % tag, "(parent.%sCount>%d)/pow(%s,2)" % (e, i, pos),
                         tuple("((%s)?1:%s)" % (active, b) for b in balance_refs(e))))
        out.append(custom_balance_tcl(e, tag, "in_ring", active))
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
    body = _coloured_axial(e, "caustic", pos, _on(e), shape, "%s*%s" % (p(e, "Size"), RES), "1",
                           custom=("in_caustic", custom_active("causticShape", "Caustic")))
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
    out = [_source(e, True)]
    # Optical Centre (orbital / rainbow ring) branch.
    out.append("push $%s_src\nBlur {\n channels rgb\n size {{max(1,%s*%s)}}\n disable %s\n name ringHaloReach\n}"
               "\nset rhD [stack 0]" % (e, p(e, "ArcFalloff"), RES, orb_off))
    out.append("push $%s_src\nBlur {\n channels rgb\n size {{4*%s}}\n disable %s\n name ringHaloEven\n}"
               "\nset rhE [stack 0]" % (e, FW, even_off))
    u = ring_band(e, "dd-rr")
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
               " temp_name2 mm\n temp_expr2 {%s*%s}\n"
               "%s\n expr3 0\n disable %s\n name ringHaloOrbital\n}\nset rhO [stack 0]"
               % (CX, CY, p(e, "Radius"), FH, profile("dd-rr", e), nz, "\n".join(rows), orb_off))
    # Light (halo) branch.
    shape, hu, band = ring_profile(e)
    lines = coloured_kernel_lines(e, shape_temps("%s*%s" % (p(e, "Radius"), FH)), shape, hu, band, "aw")
    kernel = "push $hl\nExpression {\n%s\n disable %s\n name ringHaloKernel\n}" % ("\n".join(with_floor(lines)), halo_off)
    active = custom_active("ringHaloShape", "Ring", "%s==1" % mode)
    out.append(pick_kernel_tcl("rhK", kernel, custom_kernel_tcl(e, "ringHalo", "in_ring", "%s*%s" % (p(e, "Radius"), FH),
                                                              halo_off.strip("{}"), active, True), active))
    out.append("set rhK [stack 0]")
    out.append(coloured_conv_tcl(e, "rhK", "%s_src" % e, halo_off.strip("{}"), "ringHaloHalo"))
    out.append("set rhH [stack 0]")
    out.append("push $rhH\npush $rhO\nSwitch {\n inputs 2\n which {{%s}}\n name ringHaloPick\n}" % mode)
    # Light mode is a normalized convolution and needs the balance; Optical
    # Centre mode applies the colour per pixel, unnormalized.
    out.append(_gain(e, "ringHaloGain", "1", tuple("(%s==1?((%s)?1:%s):1)" % (mode, active, b) for b in balance_refs(e))))
    out.append(custom_balance_tcl(e, "ringHaloG", "in_ring", active))
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

def bool_knob(nuke, name, label, value):
    """A checkbox that keeps its state when the script is saved and reopened. A Boolean_Knob made with a True
    constructor default is NOT written to the script (Nuke thinks True is its default) and comes back off, so the
    value is set after construction instead."""
    k = nuke.Boolean_Knob(name, label)
    k.setValue(bool(value))
    return k


def _make_knob(nuke, name, lab, kind, lo, hi, default, tip):
    if kind.startswith("e:"):
        k = nuke.Enumeration_Knob(name, lab, kind[2:].split("|"))
        k.setValue(int(default))
    elif kind == "b":
        k = bool_knob(nuke, name, lab, default)
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
        knobs.append(_make_knob(nuke, prefix + s, lab, kind, lo, hi, d, tip))
    for i, (col, pos) in enumerate(RAMP_DEFAULTS):
        c = nuke.Color_Knob("%sRamp%d" % (prefix, i), "Ramp %d" % (i + 1))
        c.setValue(list(col))
        knobs.append(c)
        knobs.append(_make_knob(nuke, "%sRampPos%d" % (prefix, i), "Position", "d", 0, 1, pos,
                                "Where this colour sits across the band (0 = inside, 1 = outside). "
                                "Positions should increase from stop 1 to 4."))
    return knobs


STREAK_STEP_SCRIPT = "import sid_flare_elements\nsid_flare_elements.streak_step(nuke.thisNode(), %d)\n"


def streak_knobs(nuke, src):
    """Streak group body (after Enable): shared Source, + / - buttons, the
    hidden Streak Count, then STREAK_SLOTS slots. Slots past Count are hidden
    (sync_offset_visibility re-applies this on load)."""
    e = "streak"
    knobs = []
    srck = nuke.Enumeration_Knob(e + "Source", "Source", SOURCES)
    srck.setValue(src)
    srck.setTooltip("All highlights: every bright pixel. Hotspot: one point per light.")
    knobs.append(srck)
    add = nuke.PyScript_Knob(e + "Add", "+", STREAK_STEP_SCRIPT % 1)
    add.setTooltip("Add a streak (up to %d)." % STREAK_SLOTS)
    add.setFlag(nuke.STARTLINE)
    rem = nuke.PyScript_Knob(e + "Remove", "-", STREAK_STEP_SCRIPT % -1)
    rem.setTooltip("Remove the last streak (at least one stays).")
    count = nuke.Int_Knob(e + "Count", "Streak Count")
    count.setValue(1)
    count.setFlag(nuke.INVISIBLE)
    knobs += [add, rem, count]
    for i in range(STREAK_SLOTS):
        pf = streak_slot_prefix(i)
        slot = [nuke.Text_Knob(pf + "Hdr", "<b>Streak %d</b>" % (i + 1), "")]
        inten = nuke.Double_Knob(pf + "Intensity", "Intensity")
        inten.setRange(0, DEFAULT_INTENSITY[e] * 10)
        inten.setValue(DEFAULT_INTENSITY[e])
        tint = nuke.Color_Knob(pf + "Tint", "Tint")
        tint.setValue([1.0, 1.0, 1.0])
        slot += [inten, tint]
        for suffix, lab, kind, lo, hi, default, tip in EXTRA[e]:
            if suffix == "Angle":
                default = STREAK_DEFAULT_ANGLES[i]
            slot.append(_make_knob(nuke, pf + suffix, lab, kind, lo, hi, default, tip))
        offs = offset_knobs(nuke, pf)
        if i > 0:
            for k in slot + offs[:1]:
                k.setVisible(False)
        knobs += slot + offs
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
        if eid == "streak":
            for k in streak_knobs(nuke, src):
                group.addKnob(k)
            group.addKnob(nuke.Tab_Knob("grp_%s_end" % eid, "", nuke.TABENDGROUP))
            continue
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
        for k in offset_knobs(nuke, eid):
            group.addKnob(k)
        group.addKnob(nuke.Tab_Knob("grp_%s_end" % eid, "", nuke.TABENDGROUP))

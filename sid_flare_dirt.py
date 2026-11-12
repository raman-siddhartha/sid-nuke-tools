# Sid Lens Flare -- global Lens Dirt (v4, Task 06A / 06A-2).
#
# One dirt layer for the whole node. Dirt does not exist on its own: it is
# lit by the flare. glow = dirt x Blur(summed flare + highlights, Spread)
# ^ Response x Intensity x Tint, added to the flare just before Master.
#
# Texture:
#   Procedural : six layers drawn in frame coordinates (resolution
#                independent, fixed to the glass): Specks, Smudges, Floaters
#                (bubbles with a bright rim), Fibres (curly hairs), Scratches
#                and a Fingerprint. Each has its own Amount and Count.
#   Input      : the node input "Dirt", fitted to the frame (Fill / Fit).
# Both are then shaped by Placement (All over / Centre / Edges / Mask, the
# mask being the node input "DirtMask") and a Breakup noise that makes the
# dirt patchy instead of uniform.
#
# Specks, Smudges, Floaters and Fibres use a jittered grid: one object per
# cell with hashed position, size, opacity and shape, so Count is the number
# of cells and a pixel only looks at its own and the 8 neighbouring cells
# (constant cost for any Count). Every radius / length is clamped to the
# cell so 3 x 3 cells always cover every object that can touch the pixel.
# Each of the 9 neighbours is its own Expression node (the 4 temps of an
# Expression hold the hashes; long inline hashes would make the expression
# thousands of terms long); Merge2 max combines them. Floaters and Fibres use
# two nodes per neighbour (hashes -> rgba, then the shape). Scratches are
# long, so they are not cell based: their 24 slots are precomputed on the
# dirtGeo NoOp.
#
# Overscan: the texture is anchored on the unpadded frame (flareGeo.padx /
# pady, fw / fh); the padded border is cropped away afterwards.
#
# Same rules as sid_flare_elements: TCL generators are pure string
# functions; the graph is built in the node's single nuke.tcl() call; no
# space inside any expression; temp names never r/g/b/a/x/y/z; at most 4
# temps per Expression; gain nodes never disabled (a disabled generator is
# followed by a gate that multiplies by 0); no `frame` (the dirt is static
# so its texture stays cached across frames).
#
# Strict ASCII.

import sid_flare_elements as el

GEO = "dirtGeo"                          # helper NoOp: per-frame constants, read as dirtGeo.<knob>
FGEO = el.GEO                            # flareGeo: pad and frame size
RES = el.RES
TEXTURES = ["Procedural", "Input"]
FITS = ["Fill", "Fit"]
PLACEMENTS = ["All over", "Centre", "Edges", "Mask"]
MASK_CHANNELS = ["Alpha", "Luminance"]
SEED = "parent.dirtSeed"
# (a, b) multipliers of the (cell x, cell y) hash, one pair per hashed value.
HASH_COEF = ((12.9898, 78.233), (39.3467, 11.135), (73.156, 52.235), (21.2, 94.7), (53.3, 19.19), (31.7, 66.6))
SCRATCH_SLOTS = 24
PRINT_RIDGES = 9.0                       # fingerprint ridges from the centre to the edge
PI = 3.14159265
TWO_PI = 6.2831853

# knob suffix -> (label, kind, lo, hi, default, tooltip); kind as in sid_flare_elements._make_knob
AMOUNT_TIP = "Brightness of this layer in the dirt texture (0 = off)."
ON_TIP = "Switch this layer on. All layers start off."
BK_TIP = ("How much of the overall Breakup and Internal Breakup this layer takes: 1 = all of it, 0 = none "
          "(a fresh fingerprint, a crisp scratch), in between = a partial amount.")
KNOBS = (
    ("Intensity", "Intensity", "d", 0.0, 100.0, 0.1,
     "Brightness of the dirt glow. The dirt is lit by the flare, which is very bright after Source Gain, "
     "so values far below 1 are normal for strong lights."),
    ("Spread", "Spread", "d", 10.0, 2000.0, 300.0,
     "How far the light that reaches the dirt is spread out, in plate px (a blur of the flare + highlights)."),
    ("Response", "Response", "d", 0.2, 4.0, 1.0,
     "Gamma on the light that reaches the dirt: below 1 lifts weak light, above 1 keeps only strong light."),
    ("Seed", "Seed", "i", 0, 1000, 0, "Re-rolls the procedural dirt."),
    ("Soften", "Softness", "d", 0.0, 50.0, 3.0,
     "Blurs the whole dirt texture (plate px) to remove jagged, aliased edges. Raise it for out-of-focus dirt; "
     "0 = as drawn."),
    ("Placement", "Placement", "e:" + "|".join(PLACEMENTS), 0, 0, 0,
     "Where the dirt sits. All over: everywhere. Centre: strongest around Position. Edges: strongest away from "
     "Position (the frame edges). Mask: the image on the DirtMask input, which appears on the node only "
     "while Mask is chosen (switching away removes the pipe)."),
    ("PlaceRadius", "Radius", "d", 10.0, 4000.0, 450.0,
     "Centre and Edges: size of the area around Position, plate px."),
    ("PlaceFalloff", "Falloff", "d", 0.0, 1.0, 0.7,
     "Centre and Edges: how softly the area fades (0 = hard edge, 1 = fades from Position)."),
    ("Invert", "Invert", "b", 0, 1, 0, "Swap where the dirt is and is not (all four Placement modes)."),
    ("MaskChan", "Mask Channel", "e:" + "|".join(MASK_CHANNELS), 0, 0, 0,
     "Mask placement: use the mask image's alpha or its luminance. Nothing shows while DirtMask is unconnected."),
    ("Breakup", "Breakup", "d", 0.0, 1.0, 0.7,
     "Cloudy noise that thins the dirt out in patches so it is not uniform. 0 = none."),
    ("BreakupSoftness", "Breakup Softness", "d", 0.0, 1.0, 0.7,
     "How soft the edges of the patches are: 0 = hard-edged patches, 1 = very gradual."),
    ("BreakupScale", "Breakup Size", "d", 20.0, 3000.0, 250.0, "x/y size of the patches, plate px."),
    ("BreakupType", "Breakup Type", "e:fBm|Turbulence", 0, 0, 0,
     "fBm: smooth clouds. Turbulence: creased, billowy noise."),
    ("BreakupZ", "Breakup Z", "d", 0.0, 50.0, 0.0, "Moves through the 3D noise: a different pattern at the same place. Animate to evolve it."),
    ("BreakupOctaves", "Breakup Octaves", "i", 1, 10, 2, "Number of noise layers added together (more = finer detail)."),
    ("BreakupLac", "Breakup Lacunarity", "d", 1.0, 10.0, 2.1, "How much finer each octave is than the one before."),
    ("BreakupGain", "Breakup Gain", "d", 0.1, 1.0, 0.6, "How strong each finer octave is compared with the one before."),
    ("BreakupGamma", "Breakup Gamma", "d", 0.0, 1.0, 0.5,
     "Contrast curve of the noise: 0.5 = neutral, lower = darker / more breakup, higher = lighter / less."),
    ("Grain", "Internal Breakup", "d", 0.0, 1.0, 0.5,
     "Fractal noise inside every speck, smudge, fibre and scratch: erodes and mottles them so they are not "
     "solid shapes. 0 = none."),
    ("GrainScale", "Internal Size", "d", 2.0, 300.0, 14.0, "x/y size of the mottling, plate px."),
    ("GrainType", "Internal Type", "e:fBm|Turbulence", 0, 0, 0,
     "fBm: smooth clouds. Turbulence: creased, billowy noise."),
    ("GrainZ", "Internal Z", "d", 0.0, 50.0, 0.0, "Moves through the 3D noise: a different pattern at the same place. Animate to evolve it."),
    ("GrainOctaves", "Internal Octaves", "i", 1, 10, 3, "Number of noise layers added together (more = finer detail)."),
    ("GrainLac", "Internal Lacunarity", "d", 1.0, 10.0, 2.1, "How much finer each octave is than the one before."),
    ("GrainGain", "Internal Gain", "d", 0.1, 1.0, 0.6, "How strong each finer octave is compared with the one before."),
    ("GrainGamma", "Internal Gamma", "d", 0.0, 1.0, 0.5,
     "Contrast curve of the noise: 0.5 = neutral, lower = darker / more breakup, higher = lighter / less."),
    # Specks
    ("SpeckOn", "Enable", "b", 0, 1, 0, ON_TIP),
    ("SpeckBreak", "Use Breakup", "d", 0.0, 1.0, 1.0, BK_TIP),
    ("SpeckAmount", "Amount", "d", 0.0, 4.0, 1.0, AMOUNT_TIP),
    ("SpeckCount", "Count", "i", 0, 5000, 1200, "Number of specks over the frame."),
    ("SpeckSize", "Size", "d", 0.5, 30.0, 2.5, "Largest speck radius, plate px."),
    ("SpeckSoftness", "Softness", "d", 0.0, 1.0, 0.25, "0 = sharp dust, 1 = out-of-focus blobs."),
    ("SpeckShape", "Irregularity", "d", 0.0, 1.0, 0.6, "0 = round, 1 = lumpy, every speck a different outline."),
    ("SpeckElong", "Elongation", "d", 0.0, 1.0, 0.5, "0 = round, 1 = stretched, randomly rotated."),
    ("SpeckVariation", "Variation", "d", 0.0, 1.0, 0.8,
     "0 = every speck the same size and brightness; 1 = mostly tiny and faint with a few big bright ones."),
    # Smudges
    ("SmudgeOn", "Enable", "b", 0, 1, 0, ON_TIP),
    ("SmudgeBreak", "Use Breakup", "d", 0.0, 1.0, 1.0, BK_TIP),
    ("SmudgeAmount", "Amount", "d", 0.0, 4.0, 0.6, AMOUNT_TIP),
    ("SmudgeCount", "Count", "i", 0, 200, 8, "Number of smudges over the frame."),
    ("SmudgeSize", "Size", "d", 5.0, 800.0, 90.0, "Largest smudge radius, plate px."),
    ("SmudgeSoftness", "Softness", "d", 0.0, 1.0, 0.8, "0 = sharp edge, 1 = fades from the centre."),
    ("SmudgeShape", "Irregularity", "d", 0.0, 1.0, 0.6, "0 = round, 1 = lumpy, irregular blobs."),
    ("SmudgeVariation", "Variation", "d", 0.0, 1.0, 0.6, "Random size and brightness per smudge."),
    # Floaters
    ("FloaterOn", "Enable", "b", 0, 1, 0, ON_TIP),
    ("FloaterBreak", "Use Breakup", "d", 0.0, 1.0, 1.0, BK_TIP),
    ("FloaterAmount", "Amount", "d", 0.0, 4.0, 0.8, AMOUNT_TIP),
    ("FloaterCount", "Count", "i", 0, 100, 6, "Number of floaters (bubbles, droplets, blobs with a bright rim)."),
    ("FloaterSize", "Size", "d", 5.0, 400.0, 40.0, "Largest floater radius, plate px."),
    ("FloaterSoftness", "Softness", "d", 0.0, 1.0, 0.3, "0 = crisp rim, 1 = out of focus."),
    ("FloaterRim", "Rim", "d", 0.0, 2.0, 0.7, "Brightness of the bright rim compared with the body."),
    ("FloaterElong", "Elongation", "d", 0.0, 1.0, 0.5, "0 = round, 1 = oval, randomly rotated."),
    ("FloaterVariation", "Variation", "d", 0.0, 1.0, 0.6, "Random size and brightness per floater."),
    # Fibres
    ("FibreOn", "Enable", "b", 0, 1, 0, ON_TIP),
    ("FibreBreak", "Use Breakup", "d", 0.0, 1.0, 1.0, BK_TIP),
    ("FibreAmount", "Amount", "d", 0.0, 4.0, 1.0, AMOUNT_TIP),
    ("FibreCount", "Count", "i", 0, 500, 40, "Number of hairs / fibres over the frame."),
    ("FibreLength", "Length", "d", 5.0, 800.0, 90.0, "Longest fibre, plate px (limited by Count: fewer, longer ones need a lower Count)."),
    ("FibreThickness", "Thickness", "d", 0.3, 6.0, 1.5, "Plate px."),
    ("FibreSoftness", "Softness", "d", 0.0, 20.0, 1.0, "Edge falloff of the fibres, plate px (never sharper than 1 working px)."),
    ("FibreCurl", "Curl", "d", 0.0, 1.0, 0.6, "0 = straight, 1 = tightly curled."),
    ("FibreVariation", "Variation", "d", 0.0, 1.0, 0.7, "Random length and brightness per fibre."),
    # Scratches
    ("ScratchOn", "Enable", "b", 0, 1, 0, ON_TIP),
    ("ScratchBreak", "Use Breakup", "d", 0.0, 1.0, 1.0, BK_TIP),
    ("ScratchAmount", "Amount", "d", 0.0, 4.0, 0.8, AMOUNT_TIP),
    ("ScratchCount", "Count", "i", 0, SCRATCH_SLOTS, 6, "Number of long scratches. Max %d." % SCRATCH_SLOTS),
    ("ScratchLength", "Length", "d", 20.0, 3000.0, 500.0, "Longest scratch, plate px."),
    ("ScratchThickness", "Thickness", "d", 0.3, 6.0, 1.5, "Plate px."),
    ("ScratchSoftness", "Softness", "d", 0.0, 20.0, 1.0, "Edge falloff of the scratches, plate px (never sharper than 1 working px)."),
    ("ScratchAngle", "Angle", "d", -180.0, 180.0, 80.0, "Main scratch direction, degrees (90 = vertical)."),
    ("ScratchSpread", "Angle Spread", "d", 0.0, 180.0, 30.0, "Random deviation from the main direction, degrees."),
    ("ScratchVariation", "Variation", "d", 0.0, 1.0, 0.7, "Random thickness, length and brightness per scratch."),
    # Fingerprint
    ("PrintOn", "Enable", "b", 0, 1, 0, ON_TIP),
    ("PrintBreak", "Use Breakup", "d", 0.0, 1.0, 1.0, BK_TIP),
    ("PrintAmount", "Amount", "d", 0.0, 1.0, 0.3, "Strength of the fingerprint. 0 = none."),
    ("PrintSoftness", "Softness", "d", 0.0, 1.0, 0.3,
     "Softens the ridges and the edge of the print: 0 = crisp and fresh, 1 = smeared."),
    ("PrintSize", "Size", "d", 0.2, 4.0, 1.0, "Size of the print (1 = about a quarter of the frame height)."),
    ("PrintAngle", "Angle", "d", -180.0, 180.0, 20.0, "Rotation of the print, degrees."),
)

# (group id, label, knob suffixes shown inside, one per line of the panel)
LAYERS = (
    ("Speck", "Specks", ("SpeckOn", "SpeckAmount", "SpeckCount", "SpeckSize", "SpeckSoftness", "SpeckShape",
                         "SpeckElong", "SpeckVariation", "SpeckBreak")),
    ("Smudge", "Smudges", ("SmudgeOn", "SmudgeAmount", "SmudgeCount", "SmudgeSize", "SmudgeSoftness", "SmudgeShape",
                           "SmudgeVariation", "SmudgeBreak")),
    ("Floater", "Floaters", ("FloaterOn", "FloaterAmount", "FloaterCount", "FloaterSize", "FloaterSoftness",
                             "FloaterRim", "FloaterElong", "FloaterVariation", "FloaterBreak")),
    ("Fibre", "Fibres", ("FibreOn", "FibreAmount", "FibreCount", "FibreLength", "FibreThickness", "FibreSoftness",
                         "FibreCurl", "FibreVariation", "FibreBreak")),
    ("Scratch", "Scratches", ("ScratchOn", "ScratchAmount", "ScratchCount", "ScratchLength", "ScratchThickness",
                              "ScratchSoftness", "ScratchAngle", "ScratchSpread", "ScratchVariation", "ScratchBreak")),
    ("Print", "Fingerprint", ("PrintOn", "PrintAmount", "PrintSize", "PrintSoftness", "PrintAngle", "PrintBreak")),
)


def knob_names():
    """Every knob the graph reads."""
    return (["dirtOn", "dirtTint", "dirtTexture", "dirtFit", "dirtPlacePos", "dirtPrintPos", "dirtBreakupMove",
             "dirtGrainMove"]
            + ["dirt" + k[0] for k in KNOBS])


# -- hashing ---------------------------------------------------------------------------

def _hash(k, ci, cj, salt):
    """Deterministic 0..1 for the cell (ci, cj), re-rolled by Seed; `k` picks the
    hashed value, `salt` the layer."""
    a, b = HASH_COEF[k]
    v = "sin((%s)*%g+(%s)*%g+%s*37.719+%d)*43758.5453" % (ci, a, cj, b, SEED, k + 10 * salt)
    return "((%s)-floor(%s))" % (v, v)


def _fract(expr):
    return "((%s)-floor(%s))" % (expr, expr)


def _max_all(terms):
    out = terms[0]
    for t in terms[1:]:
        out = "max(%s,%s)" % (t, out)
    return out


# -- cell layers -----------------------------------------------------------------------

def _cell_index(axis, cell, i):
    ax = "x" if axis == 0 else "y"
    return "(floor((%s+0.5-%s.pad%s)/%s.%s)%+d)" % (ax, FGEO, ax, GEO, cell, i)


def _offset(axis, cell, i, h):
    """Working px from the pixel centre back to the cell's object (cell + i, jittered by hash `h`)."""
    ax = "x" if axis == 0 else "y"
    return "(%s+0.5-%s.pad%s-(%s+%s)*%s.%s)" % (ax, FGEO, ax, _cell_index(axis, cell, i), h, GEO, cell)


def _proc_on(amount, extra):
    return ("parent.dirtOn*(parent.dirtTexture==0)*(parent.dirtIntensity>0)*parent.%s*(parent.%s>0)*(%s)"
            % (amount.replace("Amount", "On"), amount, extra))


def _proc_off(amount, extra):
    return "{{!(%s)}}" % _proc_on(amount, extra)


def _gate(name, amount, extra):
    """Never disabled. The generators in front of it are disabled when the layer
    is off, so they pass $hl through: this gate multiplies that by 0. It scales
    the layer by its Amount, multiplies it by the Breakup mask unless the layer's
    Use Breakup is off, and copies the generator's red channel (grey dirt) to
    rgb. B = the Breakup mask (input 0), A = the layer (input 1)."""
    return ("push $dirt_break\nMergeExpression {\n inputs 2\n temp_name0 kk\n temp_expr0 {%s*parent.%s}\n"
            " temp_name1 mk\n temp_expr1 {lerp(1,B.r,parent.%s)}\n expr0 {A.r*kk*mk}\n expr1 {A.r*kk*mk}\n expr2 {A.r*kk*mk}\n"
            " expr3 0\n name %s\n}" % (_proc_on(amount, extra), amount, amount.replace("Amount", "Break"), name))


def _line(dist, hw, sw, energy):
    """Anti-aliased line cross-section: coverage 1 inside the half width `hw`, falling off over the Softness width
    `sw` (never under 1 working px). A line thinner than 1.5 working px is drawn 1.5 px wide and dimmed by the
    `energy` ratio instead (so it fades rather than aliasing into jagged steps)."""
    return "%s*smoothstep(0,1,clamp((%s-%s)/%s+0.5,0,1))" % (energy, hw, dist, sw)


def _thin(t):
    """(half width, energy ratio) of a line `t` working px thick, never drawn under 1.5 px."""
    hw = "max((%s)/2,0.75)" % t
    return hw, "min(1,(%s)/(2*%s))" % (t, hw)


def _speck_temps(h):
    """h = (r, g, b, a) channels holding the hashes (x, y, size + rotation, opacity + shape phases)."""
    v = "parent.dirtSpeckVariation"
    return [("sn", "sin(%s*%g)" % (_fract(h[2] + "*13.7"), PI)),
            ("cs", "cos(%s*%g)" % (_fract(h[2] + "*13.7"), PI)),
            ("el", "sqrt(1+parent.dirtSpeckElong*1.5*%s)" % _fract(h[2] + "*3.9")),
            ("rd", "max(1,%s.speck_r*(1-%s+%s*%s*%s*%s))" % (GEO, v, v, h[2], h[2], h[2]))]


def _speck(dx, dy, h):
    """One speck: a randomly rotated, optionally stretched, lumpy-outlined blob with a power-law size, random
    opacity and a Softness edge. The outline is bent by three angular harmonics with random phases."""
    v, soft, shape = "parent.dirtSpeckVariation", "parent.dirtSpeckSoftness", "parent.dirtSpeckShape"
    lx = "(%s*cs+%s*sn)" % (dx, dy)
    ly = "(-%s*sn+%s*cs)" % (dx, dy)
    ang = "atan2(%s,%s)" % (ly, lx)
    lump = "(1+%s*0.3*(sin(2*%s+%g*%s)+0.7*sin(3*%s+%g*%s)+0.5*sin(5*%s+%g*%s)))" % (
        shape, ang, TWO_PI, _fract(h[3] + "*37.7"), ang, TWO_PI, _fract(h[3] + "*29.3"),
        ang, TWO_PI, _fract(h[3] + "*19.1"))
    rr = "(rd*%s)" % lump
    op = "((1-%s)+%s*(0.15+0.85*%s*%s))" % (v, v, h[3], h[3])
    return _speck_temps(h), "%s*smoothstep(0,1,clamp((%s-hypot(%s/el,%s*el))/max(1.5,rd*%s*1.5)+0.5,0,1))" % (
        op, rr, lx, ly, soft)


def _smudge(dx, dy, h):
    """One smudge: a soft, lumpy blob (two angular harmonics bend the radius)."""
    v, soft, shape = "parent.dirtSmudgeVariation", "parent.dirtSmudgeSoftness", "parent.dirtSmudgeShape"
    rad = "(%s.smudge_r*(1-%s+%s*(0.3+0.7*%s)))" % (GEO, v, v, h[2])
    ang = "atan2(%s,%s)" % (dy, dx)
    lump = "(1+%s*0.3*(sin(2*%s+%g*%s)+0.6*sin(3*%s+%g*%s)))" % (
        shape, ang, TWO_PI, _fract(h[2] + "*37.7"), ang, TWO_PI, _fract(h[3] + "*29.3"))
    rr = "(%s*%s)" % (rad, lump)
    op = "lerp(0.25,0.06+0.3*%s,%s)" % (h[3], v)
    return [], "%s*smoothstep(0,1,clamp((%s-hypot(%s,%s))/max(1,%s*%s),0,1))" % (op, rr, dx, dy, rr, soft)


def _floater_temps(h):
    """h = (r, g, b, a) channels holding the hashes (x, y, angle + size, aspect + opacity)."""
    v = "parent.dirtFloaterVariation"
    return [("sn", "sin(%s*%g)" % (h[2], PI)),
            ("cs", "cos(%s*%g)" % (h[2], PI)),
            ("asp", "(1+parent.dirtFloaterElong*1.2*%s)" % _fract(h[3] + "*5.3")),
            ("rd", "max(1.5,%s.floater_r*(1-%s+%s*(0.25+0.75*%s)))" % (GEO, v, v, _fract(h[2] + "*13.7")))]


def _floater(dx, dy, h):
    """One floater: an optionally elongated, randomly rotated blob, a soft body
    plus a bright rim just inside its edge."""
    v, soft = "parent.dirtFloaterVariation", "parent.dirtFloaterSoftness"
    lx = "(%s*cs+%s*sn)" % (dx, dy)
    ly = "(-%s*sn+%s*cs)" % (dx, dy)
    ee = "hypot(%s/sqrt(asp),%s*sqrt(asp))" % (lx, ly)
    sw = "max(1.5,rd*%s*0.5)" % soft
    disc = "clamp((rd-%s)/%s+0.5,0,1)" % (ee, sw)
    rim = "exp(-pow((%s-rd*0.92)/max(1.5,rd*0.09+%s*0.6),2))" % (ee, sw)
    op = "((1-%s)*0.6+%s*(0.3+0.7*%s))" % (v, v, _fract(h[3] + "*17.1"))
    return _floater_temps(h), "%s*(0.28*%s+parent.dirtFloaterRim*%s)" % (op, disc, rim)


def _fibre_temps(h):
    """Sign-folded direction (s*sin, s*cos), half turning angle and arc radius of
    a circular arc through the cell point."""
    v = "parent.dirtFibreVariation"
    sign = "(%s>0.5?1:-1)" % _fract(h[3] + "*17.13")
    length = "%s.fibre_len*(1-%s+%s*(0.3+0.7*%s))" % (GEO, v, v, _fract(h[2] + "*13.7"))
    beta = "max(0.03,parent.dirtFibreCurl*(0.15+0.85*%s)*2.8)" % h[3]
    return [("sn", "%s*sin(%s*%g)" % (sign, h[2], TWO_PI)),
            ("cs", "%s*cos(%s*%g)" % (sign, h[2], TWO_PI)),
            ("be", beta),
            ("rc", "(%s)/(2*%s)" % (length, beta))]


def _fibre(dx, dy, h):
    """One fibre: a circular arc (a hair: straight for Curl 0, a hook or loop
    for high Curl) of Thickness px (varied per fibre) with square 1 px ends."""
    v = "parent.dirtFibreVariation"
    wx = "(%s+rc*sn)" % dx
    wy = "(%s-rc*cs)" % dy
    dphi = "atan2(%s*sn+%s*cs,%s*sn-%s*cs)" % (wy, wx, wx, wy)
    t = "parent.dirtFibreThickness*%s*(1-%s+%s*(0.4+1.2*%s))" % (RES, v, v, _fract(h[3] + "*7.9"))
    hw, energy = _thin(t)
    ring = _line("abs(hypot(%s,%s)-rc)" % (wx, wy), hw, "%s.fb_sw" % GEO, energy)
    arc = "smoothstep(0,1,clamp((be-abs(%s))*rc/%s.fb_sw+0.5,0,1))" % (dphi, GEO)
    op = "((1-%s)+%s*(0.35+0.65*%s))" % (v, v, _fract(h[3] + "*31.7"))
    return _fibre_temps(h), "%s*%s*%s" % (op, ring, arc)


def _cell_layer(part, salt, cell, layer, amount, extra, two_stage=False):
    """The 3 x 3 neighbour nodes of one cell layer, combined by Merge2 max and
    gated by `_gate`. Leaves the gated layer on the stack."""
    off = _proc_off(amount, extra)
    outs = []
    for j in (-1, 0, 1):
        for i in (-1, 0, 1):
            name = "dirt%s_%d%d" % (part, i + 1, j + 1)
            hs = [_hash(k, _cell_index(0, cell, i), _cell_index(1, cell, j), salt) for k in range(4)]
            if two_stage:
                dx, dy = _offset(0, cell, i, "r"), _offset(1, cell, j, "g")
                temps, value = layer(dx, dy, ("r", "g", "b", "a"))
                node = ("push $hl\nExpression {\n expr0 {%s}\n expr1 {%s}\n expr2 {%s}\n expr3 {%s}\n disable %s\n name %sH\n}\n"
                        % (hs[0], hs[1], hs[2], hs[3], off, name))
                lines = []
                for n, (tn, te) in enumerate(temps):
                    lines.append(" temp_name%d %s\n temp_expr%d {%s}" % (n, tn, n, te))
                node += ("Expression {\n%s\n expr0 {%s}\n expr1 0\n expr2 0\n expr3 0\n disable %s\n name %s\n}"
                         % ("\n".join(lines), value, off, name))
            else:
                names = ("hx", "hy", "ha", "hb")
                dx, dy = _offset(0, cell, i, names[0]), _offset(1, cell, j, names[1])
                _no_temps, value = layer(dx, dy, names)
                lines = []
                for n in range(4):
                    lines.append(" temp_name%d %s\n temp_expr%d {%s}" % (n, names[n], n, hs[n]))
                node = ("push $hl\nExpression {\n%s\n expr0 {%s}\n expr1 0\n expr2 0\n expr3 0\n disable %s\n name %s\n}"
                        % ("\n".join(lines), value, off, name))
            outs.append(node + "\nset %s_v [stack 0]" % name)
    out = list(outs)
    out.append("push $dirt%s_00_v\nset dirt%s_acc [stack 0]" % (part, part))
    acc = "$dirt%s_acc" % part
    k = 0
    for j in (0, 1, 2):
        for i in (0, 1, 2):
            if (i, j) == (0, 0):
                continue
            k += 1
            out.append("push $dirt%s_%d%d_v\npush %s\nMerge2 { inputs 2 operation max also_merge all name dirt%sMax%d }\n"
                       "set dirt%s_acc [stack 0]" % (part, i, j, acc, part, k, part))
    out.append(_gate("dirt%sGate" % part, amount, extra))
    return "\n".join(out)


# -- scratches and fingerprint -------------------------------------------------------------

def _slot_hash(k, m):
    return _fract("sin(%d*12.9898+%d*78.233+%s*37.719+7)*43758.5453" % (k + 1, m + 1, SEED))


def _scratch_tcl():
    """SCRATCH_SLOTS long thin lines; slot k exists while k < Count. Per-slot
    constants (centre, direction, half length, brightness) live on dirtGeo."""
    terms = []
    for k in range(SCRATCH_SLOTS):
        dx = "(x+0.5-%s.s%d_x)" % (GEO, k)
        dy = "(y+0.5-%s.s%d_y)" % (GEO, k)
        across = "abs(%s*%s.s%d_c-%s*%s.s%d_s)" % (dy, GEO, k, dx, GEO, k)
        along = "abs(%s*%s.s%d_c+%s*%s.s%d_s)" % (dx, GEO, k, dy, GEO, k)
        line = _line(across, "%s.s%d_hw" % (GEO, k), "%s.sc_sw" % GEO, "%s.s%d_e" % (GEO, k))
        terms.append("(%d<parent.dirtScratchCount)*%s.s%d_o*%s*smoothstep(0,1,clamp((%s.s%d_l-%s)/%s.sc_sw+0.5,0,1))"
                     % (k, GEO, k, line, GEO, k, along, GEO))
    amount, extra = "dirtScratchAmount", "parent.dirtScratchCount>0"
    return ("push $hl\nExpression {\n expr0 {%s}\n expr1 0\n expr2 0\n expr3 0\n disable %s\n name dirtScratch\n}\n%s"
            % (_max_all(terms), _proc_off(amount, extra), _gate("dirtScratchGate", amount, extra)))


def _print_tcl():
    """Fingerprint: concentric, noise-bent ridges in an oval patch that is
    broken up into blotches. Placed by Position, sized by Size, turned by Angle."""
    lx = "((x+0.5-%s.pr_x)*%s.pa_c+(y+0.5-%s.pr_y)*%s.pa_s)" % (GEO, GEO, GEO, GEO)
    ly = "(-(x+0.5-%s.pr_x)*%s.pa_s+(y+0.5-%s.pr_y)*%s.pa_c)" % (GEO, GEO, GEO, GEO)
    rr = "%s.pr_r" % GEO
    ee = "(hypot(%s/1.2,%s*1.2)/%s)" % (lx, ly, rr)
    amount, extra = "dirtPrintAmount", "1"
    ps = "parent.dirtPrintSoftness"
    return ("push $hl\nExpression {\n temp_name0 ee\n temp_expr0 {%s}\n"
            " temp_name1 wn\n temp_expr1 {noise(%s/%s*2.5+%s*1.7,%s/%s*2.5,0.7)}\n"
            " temp_name2 br\n temp_expr2 {lerp(1,smoothstep(0.35,0.65,0.5+0.5*noise(%s/%s*4+%s*3.1,%s/%s*4,2.1)),parent.dirtPrintBreak)}\n"
            " temp_name3 pt\n temp_expr3 {1-smoothstep(1-(0.1+0.6*%s),1,%s)}\n"
            " expr0 {pt*(0.2+0.8*lerp(0.5+0.5*sin(ee*%g+4*wn),0.5,0.8*%s)*br)}\n expr1 0\n expr2 0\n expr3 0\n"
            " disable %s\n name dirtPrint\n}\n%s"
            % (ee, lx, rr, SEED, ly, rr, lx, rr, SEED, ly, rr, ps, ee, TWO_PI * PRINT_RIDGES, ps,
               _proc_off(amount, extra), _gate("dirtPrintGate", amount, extra)))


# -- geo ---------------------------------------------------------------------------------

def geo_tcl():
    """The dirtGeo NoOp: cell sizes, clamped radii, placement, fingerprint and
    scratch-slot constants (working px on the padded canvas), evaluated once
    per frame. Other nodes read them as dirtGeo.<knob>."""
    sx, sy = el.SX_EXPR, el.SY_EXPR
    knobs = []
    for part, count, size, cap, floor in (("speck", "dirtSpeckCount", "dirtSpeckSize", "cell", 0.5),
                                          ("smudge", "dirtSmudgeCount", "dirtSmudgeSize", "cell", 0.5),
                                          ("floater", "dirtFloaterCount", "dirtFloaterSize", "cell*0.6", 1.5),
                                          ("fibre", "dirtFibreCount", "dirtFibreLength", "cell*1.8", 2.0)):
        cell = "%s.%s_cell" % (GEO, part)
        knobs.append((part + "_cell", "max(1,sqrt(%s.fw*%s.fh/max(1,parent.%s)))" % (FGEO, FGEO, count)))
        cap = cap.replace("cell", cell)
        knobs.append((part + ("_len" if part == "fibre" else "_r"),
                      "max(%g,min(parent.%s*%s,%s))" % (floor, size, RES, cap)))
    knobs.append(("fb_sw", "max(1,parent.dirtFibreSoftness*%s)" % RES))
    knobs.append(("sc_sw", "max(1,parent.dirtScratchSoftness*%s)" % RES))
    knobs.append(("pr_x", "parent.dirtPrintPos.x*%s+%s.padx" % (sx, FGEO)))
    knobs.append(("pr_y", "parent.dirtPrintPos.y*%s+%s.pady" % (sy, FGEO)))
    knobs.append(("pr_r", "max(4,0.22*%s.fh*parent.dirtPrintSize)" % FGEO))
    knobs.append(("pa_c", "cos(parent.dirtPrintAngle*pi/180)"))
    knobs.append(("pa_s", "sin(parent.dirtPrintAngle*pi/180)"))
    knobs.append(("place_cx", "parent.dirtPlacePos.x*%s+%s.padx" % (sx, FGEO)))
    knobs.append(("place_cy", "parent.dirtPlacePos.y*%s+%s.pady" % (sy, FGEO)))
    knobs.append(("place_r", "max(1,parent.dirtPlaceRadius*%s)" % RES))
    knobs.append(("bk_s", "max(2,parent.dirtBreakupScale*%s)" % RES))
    knobs.append(("gr_s", "max(1,parent.dirtGrainScale*%s)" % RES))
    for k, g in (("dirtBreakup", "bk"), ("dirtGrain", "gr")):
        knobs.append((g + "_tx", "parent.%sMove.x*%s" % (k, sx)))
        knobs.append((g + "_ty", "parent.%sMove.y*%s" % (k, sy)))
        # sum of the octave weights gain^i, i < octaves (gain 1 gives the octave count)
        knobs.append((g + "_n", "(parent.%sGain==1?parent.%sOctaves:(1-pow(parent.%sGain,parent.%sOctaves))/(1-parent.%sGain))"
                      % (k, k, k, k, k)))
    for k in range(SCRATCH_SLOTS):
        ang = "(parent.dirtScratchAngle+parent.dirtScratchSpread*(2*%s-1))*pi/180" % _slot_hash(k, 2)
        knobs.append(("s%d_x" % k, "%s.padx+%s*%s.fw" % (FGEO, _slot_hash(k, 0), FGEO)))
        knobs.append(("s%d_y" % k, "%s.pady+%s*%s.fh" % (FGEO, _slot_hash(k, 1), FGEO)))
        knobs.append(("s%d_c" % k, "cos(%s)" % ang))
        knobs.append(("s%d_s" % k, "sin(%s)" % ang))
        v = "parent.dirtScratchVariation"
        knobs.append(("s%d_l" % k, "max(1,parent.dirtScratchLength*%s*0.5*(1-%s+%s*(0.3+0.7*%s)))"
                      % (RES, v, v, _slot_hash(k, 3))))
        knobs.append(("s%d_o" % k, "(1-%s)*0.7+%s*(0.3+0.7*%s*%s)" % (v, v, _slot_hash(k, 4), _slot_hash(k, 4))))
        t = "parent.dirtScratchThickness*%s*(1-%s+%s*(0.2+1.6*%s))" % (RES, v, v, _slot_hash(k, 5))
        hw, energy = _thin(t)
        knobs.append(("s%d_hw" % k, hw))
        knobs.append(("s%d_e" % k, energy))
    lines = ["push $hl", "NoOp {", " name %s" % GEO, " addUserKnob {20 User}"]
    for name, expr in knobs:
        lines.append(" addUserKnob {7 %s}" % name)
        lines.append(" %s {{%s}}" % (name, expr))
    lines.append("}")
    return "\n".join(lines)


# -- texture inputs, placement ------------------------------------------------------------------

def _fit_pad_tcl(src, prefix, fit_modes, off, which):
    """`src` fitted to the frame with each Reformat mode in `fit_modes`, picked
    by `which`, then centred on the padded canvas exactly like the highlights
    (overscanPad)."""
    out = []
    for mode in fit_modes:
        out.append("push $%s\nReformat {\n type \"to box\"\n box_width {{flareDown.width}}\n"
                   " box_height {{flareDown.height}}\n box_fixed true\n resize %s\n disable %s\n name %s_%s\n}"
                   % (src, mode, off, prefix, mode))
    if len(fit_modes) > 1:
        out.append("Switch {\n inputs %d\n which {{%s}}\n name %sFitPick\n}" % (len(fit_modes), which, prefix))
    out.append("Reformat {\n type \"to box\"\n box_width {{overscanPad.width}}\n box_height {{overscanPad.height}}\n"
               " box_fixed true\n resize none\n center true\n black_outside true\n disable %s\n name %sPad\n}" % (off, prefix))
    return "\n".join(out)


def _input_tcl():
    """The Dirt input (Fill or Fit), gated by Texture, then thinned by the Breakup mask."""
    off = "{{!parent.dirtOn||parent.dirtTexture!=1||parent.dirtIntensity<=0}}"
    # the last Reformat pushed is Switch input 0 (Fill = knob index 0)
    out = [_fit_pad_tcl("in_dirt", "dirt", ("fit", "fill"), off, "parent.dirtFit"),
           "Expression {\n temp_name0 kk\n temp_expr0 {parent.dirtOn*(parent.dirtTexture==1)*(parent.dirtIntensity>0)}\n"
           " expr0 {r*kk}\n expr1 {g*kk}\n expr2 {b*kk}\n expr3 0\n name dirtInGate\n}",
           "push $dirt_break\nMergeExpression {\n inputs 2\n expr0 {A.r*B.r}\n expr1 {A.g*B.r}\n expr2 {A.b*B.r}\n"
           " expr3 0\n name dirtInBreak\n}",
           "set dirt_in [stack 0]"]
    return "\n".join(out)


def _mask_tcl():
    """The DirtMask input stretched to the frame, then centred on the padded
    canvas. rgb = the chosen channel; zero unless Placement is Mask."""
    off = "{{!parent.dirtOn||parent.dirtPlacement!=3||parent.dirtIntensity<=0}}"
    return "\n".join([
        _fit_pad_tcl("in_dirtmask", "dirtMask", ("distort",), off, "0"),
        "Expression {\n temp_name0 mm\n temp_expr0 {parent.dirtMaskChan==0?a:0.2126*r+0.7152*g+0.0722*b}\n"
        " temp_name1 kk\n temp_expr1 {parent.dirtOn*(parent.dirtPlacement==3)*(parent.dirtIntensity>0)}\n"
        " expr0 {mm*kk}\n expr1 {mm*kk}\n expr2 {mm*kk}\n expr3 0\n name dirtMaskGate\n}",
        "set dirt_mask [stack 0]"])


def _place_tcl():
    """Placement weight applied to the texture. B = the mask (input 0), A = the
    texture (input 1). Disabled with the layer; the glow multiplies by Enable,
    so a pass-through here is harmless."""
    off = "{{!parent.dirtOn||parent.dirtIntensity<=0}}"
    dist = "hypot(x+0.5-%s.place_cx,y+0.5-%s.place_cy)" % (GEO, GEO)
    cw = "(1-smoothstep(%s.place_r*(1-parent.dirtPlaceFalloff),%s.place_r+0.001,%s))" % (GEO, GEO, dist)
    p = ("(parent.dirtPlacement==0?1:(parent.dirtPlacement==3?clamp(B.r,0,1):"
         "(parent.dirtPlacement==1?%s:1-%s)))" % (cw, cw))
    rows = "\n".join(" expr%d {A.%s*pl}" % (i, ch) for i, ch in enumerate("rgb"))
    return ("push $dirt_tex\npush $dirt_mask\nMergeExpression {\n inputs 2\n temp_name0 pl\n"
            " temp_expr0 {abs(parent.dirtInvert-%s)}\n%s\n expr3 0\n disable %s\n name dirtPlace\n}" % (p, rows, off))


MAX_OCTAVES = 10


def _fbm(k, g):
    """Noise field 0..1 (0.5 = average) of the Nuke-Noise-like knobs `k`Type / Z / Octaves / Lac / Gain / Gamma,
    sized by dirtGeo.<g>_s and moved by dirtGeo.<g>_tx / _ty (frame anchored). fBm adds `Octaves` layers of
    noise, each `Lacunarity` finer and `Gain` weaker; Turbulence uses the creased |noise|. Normalised by the sum of
    the octave weights, stretched about 0.5 and bent by Gamma (0.5 = neutral)."""
    px = "((x+0.5-%s.padx-%s.%s_tx)/%s.%s_s)" % (FGEO, GEO, g, GEO, g)
    py = "((y+0.5-%s.pady-%s.%s_ty)/%s.%s_s)" % (FGEO, GEO, g, GEO, g)
    terms = []
    for i in range(MAX_OCTAVES):
        n = "noise(%s*pow(parent.%sLac,%d)+%d,%s*pow(parent.%sLac,%d)+%d,parent.%sZ+%s*0.37+%g)" % (
            px, k, i, 17 * i, py, k, i, 5 * i, k, SEED, 0.37 * i)
        terms.append("(%d<parent.%sOctaves)*pow(parent.%sGain,%d)*lerp(%s,2*abs(%s)-0.4,parent.%sType)"
                     % (i, k, k, i, n, n, k))
    f = "clamp(0.5+1.6*(%s)/%s.%s_n,0,1)" % ("+".join(terms), GEO, g)
    return "pow(%s,0.5/max(0.05,parent.%sGamma))" % (f, k)


def _break_tcl():
    """The Breakup mask (grey, 1 = untouched): patch noise (Breakup amount, Softness and the noise controls) times
    Internal Breakup (its own noise controls). Every procedural layer multiplies by it, by its own Use Breakup
    amount, and so does the Input texture. Disabled only with the whole dirt: the layer gates multiply by
    Enable then."""
    hw = "(0.02+0.48*parent.dirtBreakupSoftness)"
    patch = "lerp(1,smoothstep(0.5-%s,0.5+%s,%s),parent.dirtBreakup)" % (hw, hw, _fbm("dirtBreakup", "bk"))
    grain = "lerp(1,smoothstep(0.1,0.9,%s),parent.dirtGrain)" % _fbm("dirtGrain", "gr")
    rows = "\n".join(" expr%d {pa*gn}" % i for i in range(3))
    return ("push $hl\nExpression {\n temp_name0 pa\n temp_expr0 {%s}\n temp_name1 gn\n temp_expr1 {%s}\n%s\n expr3 0\n"
            " disable {{!parent.dirtOn||parent.dirtIntensity<=0}}\n name dirtBreak\n}\nset dirt_break [stack 0]"
            % (patch, grain, rows))


# -- assembly ---------------------------------------------------------------------------

def dirt_tcl(acc_var):
    """The dirt branch. `acc_var` is the summed flare (a TCL variable such as
    "$acc"). Leaves $dirtGlow, to be added to the flare. Disabled nodes
    upstream of the glow pass their input through; the glow multiplies by
    Enable, so it is exactly 0 while the layer is off."""
    off = "{{!parent.dirtOn||parent.dirtIntensity<=0}}"
    rows = "\n".join(
        " expr%d {parent.dirtOn*parent.dirtIntensity*parent.dirtTint.%s*A.%s*pow(max(0,B.%s),parent.dirtResponse)}"
        % (i, ch, ch, ch) for i, ch in enumerate("rgb"))
    parts = [geo_tcl(), _break_tcl()]
    layers = [
        ("Speck", _cell_layer("Speck", 0, "speck_cell", _speck, "dirtSpeckAmount", "parent.dirtSpeckCount>0", True)),
        ("Smudge", _cell_layer("Smudge", 1, "smudge_cell", _smudge, "dirtSmudgeAmount", "parent.dirtSmudgeCount>0")),
        ("Floater", _cell_layer("Floater", 2, "floater_cell", _floater, "dirtFloaterAmount",
                                "parent.dirtFloaterCount>0", True)),
        ("Fibre", _cell_layer("Fibre", 3, "fibre_cell", _fibre, "dirtFibreAmount", "parent.dirtFibreCount>0", True)),
        ("Scratch", _scratch_tcl()),
        ("Print", _print_tcl()),
    ]
    prev = None
    for n, (part, tcl) in enumerate(layers):
        parts.append(tcl)
        if prev is not None:
            parts.append("push $%s\nMerge2 { inputs 2 operation plus also_merge all name dirtSum%d }" % (prev, n))
        parts.append("set dirt_sum%d [stack 0]" % n)
        prev = "dirt_sum%d" % n
    parts += [
        "Expression {\n expr0 {min(1,r)}\n expr1 {min(1,g)}\n expr2 {min(1,b)}\n expr3 0\n name dirtProc\n}",
        "set dirt_proc [stack 0]",
        _input_tcl(),
        "push $dirt_in\npush $dirt_proc\nSwitch {\n inputs 2\n which {{parent.dirtTexture}}\n name dirtTexPick\n}",
        "Blur {\n channels rgb\n size {{parent.dirtSoften*%s}}\n"
        " disable {{!parent.dirtOn||parent.dirtIntensity<=0||parent.dirtSoften<=0}}\n name dirtSoften\n}" % RES,
        "set dirt_tex [stack 0]",
        _mask_tcl(),
        _place_tcl(),
        "set dirt_placed [stack 0]",
        # A = the shaped texture (pushed first); B = the light that reaches the dirt:
        # flare + highlights, spread out (pushed last = input 0)
        "push $dirt_placed",
        "push $hl\npush %s\nMerge2 { inputs 2 operation plus also_merge all disable %s name dirtLight }" % (acc_var, off),
        "Blur {\n channels rgb\n size {{parent.dirtSpread*%s}}\n disable %s\n name dirtBlur\n}" % (RES, off),
        "MergeExpression {\n inputs 2\n%s\n expr3 0\n name dirtGlow\n}" % rows,
        "set dirtGlow [stack 0]",
    ]
    return "\n".join(parts)


# -- knobs -------------------------------------------------------------------------------

def add_dirt_knobs(group, nuke, width=640, height=360):
    """The Dirt tab."""
    by = dict((k[0], k[1:]) for k in KNOBS)

    def knob(suffix, label=None):
        spec = list(by[suffix])
        if label:
            spec[0] = label
        return el._make_knob(nuke, "dirt" + suffix, *spec)

    def heading(name, label):
        return nuke.Text_Knob(name, "<b>%s</b>" % label, "")

    on = nuke.Boolean_Knob("dirtOn", "Enable", False)
    on.setTooltip("Lens dirt, lit by the flare. One layer for the whole node.")
    tint = nuke.Color_Knob("dirtTint", "Tint")
    tint.setValue([1.0, 1.0, 1.0])
    tex = nuke.Enumeration_Knob("dirtTexture", "Texture", TEXTURES)
    tex.setValue(0)
    tex.setTooltip("Procedural: the six layers below. Input: the image connected to the Dirt input, which appears "
                   "on the node only while Input is chosen (its colour is kept; nothing shows while it is "
                   "unconnected; switching back to Procedural removes the pipe).")
    fit = nuke.Enumeration_Knob("dirtFit", "Input Fit", FITS)
    fit.setValue(0)
    fit.setTooltip("Fill: scale the Dirt input to cover the frame (may crop). "
                   "Fit: scale it to fit inside the frame (may leave bars).")
    place_pos = nuke.XY_Knob("dirtPlacePos", "Position")
    place_pos.setValue([width / 2.0, height / 2.0])
    place_pos.setTooltip("Centre and Edges placement: the middle of the area, plate px.")
    print_pos = nuke.XY_Knob("dirtPrintPos", "Position")
    print_pos.setValue([width * 0.3, height * 0.35])
    print_pos.setTooltip("Where the fingerprint sits, plate px.")
    breakup_move = nuke.XY_Knob("dirtBreakupMove", "Breakup Translate")
    breakup_move.setValue([0.0, 0.0])
    breakup_move.setTooltip("Slides the breakup patches across the frame, plate px.")
    grain_move = nuke.XY_Knob("dirtGrainMove", "Internal Translate")
    grain_move.setValue([0.0, 0.0])
    grain_move.setTooltip("Slides the internal mottling across the frame, plate px.")
    knobs = [nuke.Tab_Knob("tabDirt", "Dirt"), on, knob("Intensity"), tint, tex, fit, knob("Seed"), knob("Soften"),
             heading("dirtDivLight", "Lighting"), knob("Spread"), knob("Response"),
             heading("dirtDivPlace", "Placement"), knob("Placement"), place_pos, knob("PlaceRadius"),
             knob("PlaceFalloff"), knob("Invert"), knob("MaskChan"),
             heading("dirtDivBreak", "Breakup"), knob("Breakup"), knob("BreakupSoftness"), knob("BreakupType"),
             knob("BreakupScale"), knob("BreakupZ"), knob("BreakupOctaves"), knob("BreakupLac"), knob("BreakupGain"),
             knob("BreakupGamma"), breakup_move,
             heading("dirtDivGrain", "Internal Breakup"), knob("Grain"), knob("GrainType"), knob("GrainScale"),
             knob("GrainZ"), knob("GrainOctaves"), knob("GrainLac"), knob("GrainGain"), knob("GrainGamma"), grain_move]
    for gid, label, suffixes in LAYERS:
        knobs.append(nuke.Tab_Knob("grp_dirt" + gid, label, nuke.TABBEGINCLOSEDGROUP))
        for s in suffixes:
            knobs.append(knob(s))
            if s == "PrintAmount":
                knobs.append(print_pos)
        knobs.append(nuke.Tab_Knob("grp_dirt%s_end" % gid, "", nuke.TABENDGROUP))
    for k in knobs:
        group.addKnob(k)

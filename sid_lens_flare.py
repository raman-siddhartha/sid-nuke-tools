# Sid Lens Flare for Nuke -- image-driven, physically traced lens flare.
#
# Every highlight in the plate flares. Ghost position, flip, size, colour and
# chromatic fringing come from tracing light through a real lens prescription
# (sid_lens_optics.py); each ghost is the highlights remapped through that
# reflection path and convolved with the actual aperture shape.
#
# The whole internal graph is built by ONE nuke.tcl() call and Python never
# looks up nodes inside the Group -- it only reads and
# writes the Group's own knobs, which internal nodes follow via parent.*
# expressions. TCL {{ }} expressions contain no spaces (Nuke splits on them).
#
# Install (menu.py):
#     import sid_lens_flare
#     sid_lens_flare.install_menu()
#
# Strict ASCII.

import nuke

import sid_lens_optics as optics
import sid_flare_elements as elements
import sid_flare_dirt as dirt
import sid_flare_inputs as inputs
import sid_flare_presets as presets

SLOTS = optics.MAX_GHOST_SLOTS
RES = "pow(0.5,parent.flareRes)"          # Full=1, Half=0.5, Quarter=0.25
SLOT_KNOB_SUFFIXES = ("sR", "sG", "sB", "rad", "eR", "eG", "eB")
INPUT_KNOBS = ("dirtTexture", "dirtPlacement", "causticShape", "ringsShape", "ringHaloShape", "apShape")
SOLVE_KNOBS = ("lensPreset", "customPrescription", "fstop", "ghostCount", "coatings")
CUSTOM = "Custom"
REF_FSTOP = 4.0           # Starburst Length is defined at f/4 (spikes lengthen as you stop down)
MAX_RAYS = 24             # 12 blade edges x 2 half-rays
BLADES = "clamp(parent.blades,3,12)"   # every TCL use of the Blades knob goes through this


def _html(text):
    """Escape text for the status knob (rich text)."""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# -- TCL generation --------------------------------------------------------------

def _aperture_expr(radius_expr, channels=(3,)):
    """Expression body for an anti-aliased n-blade polygon (blended toward a
    circle by Roundness) centred on the format, radius `radius_expr` px.
    The shape goes into each expr index in `channels`; the others are 0.
    Temp names avoid r/g/b/a, which Nuke reserves for the input pixel."""
    shape = ("clamp(lerp(apR*cos(sec/2)/cos(aw-sec*floor(aw/sec)-sec/2),apR,"
             "parent.apRoundness)-dist+0.5,0,1)")
    lines = [
        " temp_name0 dist",
        " temp_expr0 {hypot(x+0.5-width/2,y+0.5-height/2)}",
        " temp_name1 sec",
        " temp_expr1 {2*pi/" + BLADES + "}",
        " temp_name2 aw",
        " temp_expr2 {atan2(y+0.5-height/2,x+0.5-width/2)-parent.apRotation*pi/180}",
        " temp_name3 apR",
        " temp_expr3 {max(0.5,%s)}" % radius_expr,
    ]
    for i in range(4):
        lines.append(" expr%d {%s}" % (i, shape) if i in channels else " expr%d 0" % i)
    return "\n".join(lines) + "\n"


def _ghost_tcl(n):
    """One ghost slot: per-channel scale about the optical centre (dispersion),
    aperture convolution at the solved spot radius, coating colour x energy.
    Slots at or beyond Ghost Count are disabled and output black. The ghosts
    Offset is applied once to the summed slots (_ghosts_sum_tcl)."""
    off_inner = "parent.ghostCount<=%d||!parent.ghostsOn" % n
    off = "{{%s}}" % off_inner
    cx = "{%s}" % elements.CX          # optical centre on the overscan-padded canvas
    cy = "{%s}" % elements.CY
    out = ["push $ghl"]                # highlights after the ghosts' Light Colour blend
    for ch, key in (("red", "R"), ("green", "G"), ("blue", "B")):
        if key == "G":
            scale = "parent.g%dsG" % n
        else:
            scale = "parent.g%dsG+parent.dispersion*(parent.g%ds%s-parent.g%dsG)" % (n, n, key, n)
        out.append(
            "TransformMasked {\n channels rgba.%s\n scale {{%s}}\n center {%s %s}\n"
            " filter cubic\n black_outside true\n disable %s\n name g%dT%s\n}" % (ch, scale, cx, cy, off, n, key))
    out.append("set g%dsrc [stack 0]" % n)
    # RGBA aperture kernel: px per mm comes from the unpadded working width.
    radius = "parent.g%drad*%s/parent.sensorWidth" % (n, elements.FW)
    u, band = elements.filled_band("ghosts")
    lines = elements.coloured_kernel_lines("ghosts", elements.shape_temps(radius),
                                           elements.iris_shape("0.5"), u, band, "aw", n)
    kernel = ("push $hl\nExpression {\n%s\n disable %s\n name g%dAperture\n}"
              % ("\n".join(elements.with_floor(lines)), off, n))
    active = elements.custom_active("apShape", "Aperture")
    out.append(elements.pick_kernel_tcl("g%d" % n, kernel,
                                        elements.custom_kernel_tcl("ghosts", "g%d" % n, "in_aperture", radius, off_inner,
                                                                   active, True), active))
    out.append("set g%dK [stack 0]" % n)
    out.append(elements.coloured_conv_tcl("ghosts", "g%dK" % n, "g%dsrc" % n, off_inner, "g%d" % n))
    bal = tuple("((%s)?1:%s)" % (active, b) for b in elements.balance_refs("ghosts"))     # an image kernel brings its own
    out.append(
        "Expression {\n"
        " temp_name0 on\n temp_expr0 {parent.ghostsOn*(parent.ghostCount>%d)*parent.ghostIntensity}\n"
        " expr0 {r*on*parent.g%deR*%s}\n expr1 {g*on*parent.g%deG*%s}\n expr2 {b*on*parent.g%deB*%s}\n expr3 0\n"
        " name g%dGain\n}" % (n, n, bal[0], n, bal[1], n, bal[2], n))
    out.append(elements.custom_balance_tcl("ghosts", "g%d" % n, "in_aperture", active))
    out.append("set g%d [stack 0]" % n)
    return "\n".join(out)


def _ghosts_sum_tcl():
    """Sum of every ghost slot, then the ghosts Offset once. Leaves $ghosts."""
    out = []
    acc = "$g0"
    for n in range(1, SLOTS):
        out.append("push $g%d\npush %s\nMerge2 { inputs 2 operation plus also_merge all }\nset gh_acc [stack 0]"
                   % (n, acc))
        acc = "$gh_acc"
    out.append("push %s\n%s\nset ghosts [stack 0]" % (acc, elements.offset_tcl("ghosts", "ghostsOffsetT")))
    return "\n".join(out)


def _hash(j, a, b):
    """Deterministic pseudo-random 0..1 for ray j, re-rolled by Seed
    (fract(sin(.)*43758.5453); Nuke expressions have no user functions)."""
    v = "sin(%g+parent.starSeed*%g)*43758.5453" % (j * a, b)
    return "((%s)-floor(%s))" % (v, v)


def _spike_sum(length_px_expr):
    """Diffraction spikes of an n-blade aperture as 2n half-rays (up to 12
    blades): for each blade edge a ray along its normal and one opposite.
    Odd blade counts give 2n distinct spikes; even counts give n, as
    opposite rays coincide (Convolve2 normalize removes the doubling).
    Per ray: line coverage across (Thickness core, Softness edge; flareGeo
    knobs *_star, see sid_flare_elements.profile), fall-off
    exp(-(r/L)^Falloff) with L = `length_px_expr`, and Irregularity
    randomising each ray's length and brightness (Seed)."""
    rot = "(parent.apRotation+parent.starRotation)*pi/180"
    terms = []
    for j in range(MAX_RAYS):
        k, half = j % 12, j // 12
        th = "(%s+sec/2+%d*sec+%d*pi)" % (rot, k, half)
        ray_len = "max(0.01,(%s)*max(0.05,1+parent.starIrregularity*(2*%s-1)))" % (
            length_px_expr, _hash(j, 12.9898, 78.233))
        bright = "(1-0.8*parent.starIrregularity*%s)" % _hash(j, 39.3467, 11.135)
        across = elements.profile("rad*sin(ang-%s)" % th, "star")
        terms.append(
            "(%d<%s)*(cos(ang-%s)>0)*%s*%s"
            "*exp(-pow(rad/%s,max(0.2,parent.starFalloff)))"
            % (k, BLADES, th, bright, across, ray_len))
    return "(rad<0.5?0:%s)" % "+".join(terms)


def _starburst_tcl():
    """Analytic diffraction kernel (wavelength-scaled per channel), convolved
    with the highlights one channel at a time. Length and Thickness are in
    plate px, converted to the working resolution here (the profile
    constants are the flareGeo knobs *_star)."""
    lines = ["push $hl", "Expression {",
             " temp_name0 rad", " temp_expr0 {hypot(%s,%s)}" % (elements.KDX, elements.KDY),
             " temp_name1 ang", " temp_expr1 {atan2(%s,%s)}" % (elements.KDY, elements.KDX),
             " temp_name2 sec", " temp_expr2 {2*pi/" + BLADES + "}"]
    kernel = []
    for i, w in enumerate(optics.WAVELENGTHS_UM):
        chroma = w / optics.WAVELENGTHS_UM[1] - 1.0
        length = "parent.starLength*%s*parent.effFstop/%g*(1+parent.starChroma*%.4f)" % (
            RES, REF_FSTOP, chroma)
        kernel.append(" expr%d {%s}" % (i, _spike_sum(length)))
    # CENTRE_FLOOR keeps the kernel sum > 0 (Convolve2 normalize divides by it)
    # even when every spike underflows (huge Falloff, tiny Length).
    lines += elements.with_floor(kernel)
    lines += [" expr3 0"," disable {{parent.starIntensity<=0||!parent.starOn}}", " name starKernel", "}",
              "set starK [stack 0]", "push $hl", "set star_in [stack 0]"]
    for ch in ("red", "green", "blue"):
        lines += ["push $starK", "push $star_in",
                  "Convolve2 {", " inputs 2", " channels rgba.%s" % ch, " filter_channel rgba.%s" % ch,
                  " normalize true", " disable {{parent.starIntensity<=0||!parent.starOn}}", " name star_%s" % ch, "}",
                  "set star_in [stack 0]"]
    lines += ["Expression {", " expr0 {r*parent.starOn*parent.starIntensity}", " expr1 {g*parent.starOn*parent.starIntensity}",
              " expr2 {b*parent.starOn*parent.starIntensity}", " expr3 0", " name starGain", "}",
              elements.offset_tcl("star", "starOffsetT"), "set star [stack 0]"]
    return "\n".join(lines)


def _master_tcl():
    """Master on the summed flare (before the overscan crop): Saturation about
    the luminance (clamped >= 0, the flare is added to the plate), Intensity,
    Tint and the flicker gain (flareGeo.fl_<c>, exactly 1 at Amount and
    Colour Jitter 0). A gain node, never disabled."""
    rows = []
    for i, ch in enumerate("rgb"):
        rows.append(" expr%d {max(0,lerp(lm,%s,parent.masterSaturation))*parent.masterIntensity"
                    "*parent.masterTint.%s*%s.fl_%s}" % (i, ch, ch, elements.GEO, ch))
    return ("push $acc\nExpression {\n temp_name0 lm\n temp_expr0 {0.2126*r+0.7152*g+0.0722*b}\n%s\n"
            " expr3 {a}\n name masterGain\n}" % "\n".join(rows))


def build_tcl():
    """Whole internal graph as TCL. Order: highlights -> Reformat down ->
    overscan pad ($hl: the padded, downscaled highlight stream every branch
    reads) -> ghost slots, starburst, glare, hotspot + flare elements
    (sid_flare_elements) -> summed -> Lens Dirt (sid_flare_dirt, lit by the sum) -> overscan crop -> Reformat up -> Crop
    (bbox clamped to the frame) -> merged over the plate -> output switch ->
    mask mix. Master (intensity, tint, saturation, flicker) is applied to the
    sum just before the crop. The flareGeo NoOp (sid_flare_elements.geo_tcl)
    sits after the pad and holds the per-frame constants every branch reads."""
    parts = ["""
Input { inputs 0 name Source xpos 0 ypos 0 }
set in_src [stack 0]
Input { inputs 0 name Mask number 1 xpos 400 ypos 0 }
set in_mask [stack 0]
""" + inputs.placeholders_tcl() + """

push $in_src
Expression {
 temp_name0 lum
 temp_expr0 {0.2126*r+0.7152*g+0.0722*b}
 temp_name1 wt
 temp_expr1 {smoothstep(parent.threshold-parent.knee,parent.threshold+parent.knee+0.00001,lum)*pow(2,parent.sourceStops)}
 expr0 {r*wt}
 expr1 {g*wt}
 expr2 {b*wt}
 expr3 0
 name highlights
}
set hl_full [stack 0]
Reformat {
 type "to box"
 box_width {{max(1,floor(highlights.width*""" + RES + """+0.5))}}
 box_height {{max(1,floor(highlights.height*""" + RES + """+0.5))}}
 box_fixed true
 resize distort
 name flareDown
}
Reformat {
 type "to box"
 box_width {{input.width+2*floor(input.width*parent.overscan/100)}}
 box_height {{input.height+2*floor(input.height*parent.overscan/100)}}
 box_fixed true
 resize none
 center true
 black_outside true
 name overscanPad
}
AdjBBox {
 numpixels {{max(floor(flareDown.width*parent.overscan/100),floor(flareDown.height*parent.overscan/100))+4}}
 name overscanGrow
}
set hl [stack 0]
""" + elements.geo_tcl() + """
""" + elements.mean_colour_tcl() + """
push $hl
""" + elements.light_colour_tcl("ghosts", "ghostsLight") + """
set ghl [stack 0]
"""]
    for n in range(SLOTS):
        parts.append(_ghost_tcl(n))
    parts.append(_ghosts_sum_tcl())
    parts.append(_starburst_tcl())
    parts.append("""
push $hl
Blur { channels rgb size {{parent.glareSize*""" + RES + """}} disable {{parent.glareIntensity<=0||!parent.glareOn}} name glareA }
set glareA [stack 0]
push $hl
Blur { channels rgb size {{parent.glareSize*4*""" + RES + """}} disable {{parent.glareIntensity<=0||!parent.glareOn}} name glareB }
push $glareA
Merge2 { inputs 2 operation plus also_merge all name glareSum }
Expression {
 expr0 {r*0.5*parent.glareOn*parent.glareIntensity}
 expr1 {g*0.5*parent.glareOn*parent.glareIntensity}
 expr2 {b*0.5*parent.glareOn*parent.glareIntensity}
 expr3 0
 name glareGain
}
set glare [stack 0]
""")
    parts.append(elements.elements_tcl())
    acc = "$star"
    for src in ["$glare", "$ghosts"] + elements.element_vars():
        parts.append("push %s\npush %s\nMerge2 { inputs 2 operation plus also_merge all }\nset acc [stack 0]"
                     % (src, acc))
        acc = "$acc"
    parts.append(dirt.dirt_tcl(acc))
    parts.append("push $dirtGlow\npush %s\nMerge2 { inputs 2 operation plus also_merge all name dirtAdd }\nset acc [stack 0]"
                 % acc)
    parts.append(_master_tcl())
    parts.append("""
Reformat {
 type "to box"
 box_width {{flareDown.width}}
 box_height {{flareDown.height}}
 box_fixed true
 resize none
 center true
 name overscanCrop
}
Reformat {
 type "to box"
 box_width {{highlights.width}}
 box_height {{highlights.height}}
 box_fixed true
 resize distort
 name flareUp
}
Crop {
 box {{0} {0} {highlights.width} {highlights.height}}
 crop false
 name flareCrop
}
set flare [stack 0]

push $flare
push $in_src
MergeExpression {
 inputs 2
 expr0 {parent.outputMode==1?A.r:B.r+A.r}
 expr1 {parent.outputMode==1?A.g:B.g+A.g}
 expr2 {parent.outputMode==1?A.b:B.b+A.b}
 expr3 {parent.outputMode==1?clamp(max(A.r,max(A.g,A.b)),0,1):B.a}
 name combine
}
set combined [stack 0]

push $in_src
Expression {
""" + _aperture_expr("height/4", (0, 1, 2, 3)) + """ name aperturePreview
}
set ap_prev [stack 0]

push $ap_prev
push $hl_full
push $combined
Switch {
 inputs 3
 which {{parent.outputMode<2?0:parent.outputMode-1}}
 name outputSwitch
}
set switched [stack 0]

push $in_mask
push $switched
push $in_src
Merge2 {
 inputs 2+1
 operation copy
 also_merge all
 invert_mask {{parent.invertMask}}
 mix {{parent.mix}}
 name finalMerge
}
Output { name Output1 }
""")
    return "\n".join(parts)


# -- Knobs ---------------------------------------------------------------------

def _double(name, label, lo, hi, value, tip=None):
    k = nuke.Double_Knob(name, label)
    k.setRange(lo, hi)
    k.setValue(value)
    if tip:
        k.setTooltip(tip)
    return k


def _divider(name):
    return nuke.Text_Knob(name, "", "")


def _heading(name, label):
    return nuke.Text_Knob(name, "<b>%s</b>" % label, "")


def _master_knobs():
    """Master section at the top of the Ghosts & Glare tab."""
    inten = _double("masterIntensity", "Master Intensity", 0.0, 4.0, 1.0, "Scales the whole flare.")
    tint = nuke.Color_Knob("masterTint", "Master Tint")
    tint.setValue([1.0, 1.0, 1.0])
    sat = _double("masterSaturation", "Master Saturation", 0.0, 2.0, 1.0, "0 = grey flare, 1 = as is, 2 = double.")
    amt = _double("flickerAmount", "Flicker Amount", 0.0, 1.0, 0.0,
                  "Random brightness flicker of the whole flare over time; 0 = steady.")
    spd = _double("flickerSpeed", "Flicker Speed", 0.0, 20.0, 4.0, "How fast the flicker changes.")
    jit = _double("flickerJitter", "Colour Jitter", 0.0, 1.0, 0.0,
                  "Independent flicker per colour channel; 0 = brightness only.")
    seed = nuke.Int_Knob("flickerSeed", "Flicker Seed")
    seed.setValue(0)
    seed.setTooltip("Re-rolls the flicker pattern.")
    return [_heading("hdrMaster", "Master"), inten, tint, sat, amt, spd, jit, seed]


def _add_knobs(group, width, height):
    preset_k = nuke.Enumeration_Knob("lensPreset", "Lens", list(optics.PRESET_NAMES) + [CUSTOM])
    custom_k = nuke.Multiline_Eval_String_Knob("customPrescription", "Custom Prescription")
    custom_k.setValue(optics.format_prescription(optics.preset(optics.PRESET_NAMES[0])))
    custom_k.setTooltip("One surface per row: radius thickness n_d V_d coated (radius 0 = flat, "
                        "n_d/V_d = medium after the surface, air = 1.0 0). One row "
                        "'STOP semi_diameter thickness' marks the aperture stop. # = comment. "
                        "Avoid [ ] and $ (the knob evaluates TCL).")
    noanim = " Not animatable: changing it re-traces the lens."
    fstop_k = _double("fstop", "F-Stop", 1.0, 22.0, 2.8, "Aperture of the lens." + noanim)
    fstop_k.setFlag(nuke.NO_ANIMATION)
    sensor_k = _double("sensorWidth", "Sensor Width (mm)", 8.0, 70.0, 36.0)
    center_k = nuke.XY_Knob("opticalCenter", "Optical Centre")
    center_k.setValue([width / 2.0, height / 2.0])

    thr_k = _double("threshold", "Threshold", 0.0, 10.0, 1.0)
    knee_k = _double("knee", "Soft Knee", 0.0, 2.0, 0.25)
    stops_k = _double("sourceStops", "Source Gain (stops)", 0.0, 20.0, 12.0,
                      "Real light sources are far brighter than a clipped plate. "
                      "Lifts highlights by 2^stops before they flare.")

    blades_k = nuke.Int_Knob("blades", "Blades")
    blades_k.setValue(6)
    blades_k.setRange(3, 12)
    round_k = _double("apRoundness", "Roundness", 0.0, 1.0, 0.1)
    rot_k = _double("apRotation", "Rotation", -180.0, 180.0, 0.0)
    apshape_k = nuke.Enumeration_Knob("apShape", "Aperture Shape", ["Procedural", "Input"])
    apshape_k.setTooltip("Procedural: the n-blade polygon. Input: use the image on the Aperture input, which appears on "
                         "the node while Input is chosen, as the aperture of the ghosts, Iris and Multi-Iris (luminance "
                         "= shape, colour = colour). The Starburst keeps the blade-count diffraction: a true diffraction "
                         "pattern of an arbitrary image needs an FFT that Nuke does not provide. Nothing connected = "
                         "the n-blade polygon.")
    squeeze_k = nuke.Enumeration_Knob("squeeze", "Squeeze", elements.SQUEEZES)
    squeeze_k.setTooltip("Anamorphic squeeze: stretches the aperture-shaped ghosts, Iris, Multi-Iris, Caustic and "
                         "Ring / Halo (Light) into ovals, 1/Squeeze as wide as tall. Above 1x the first Streak gets "
                         "the blue anamorphic tint (only while it is untouched).")

    count_k = nuke.Int_Knob("ghostCount", "Ghost Count")
    count_k.setValue(8)
    count_k.setRange(0, SLOTS)
    gint_k = _double("ghostIntensity", "Ghost Intensity", 0.0, 10.0, 1.0)
    disp_k = _double("dispersion", "Dispersion", 0.0, 2.0, 1.0, "1 = physical glass dispersion, 0 = none.")
    count_k.setTooltip("Number of ghosts (brightest first)." + noanim)
    count_k.setFlag(nuke.NO_ANIMATION)
    coat_k = elements.bool_knob(nuke, "coatings", "Coatings", True)
    coat_k.setTooltip("Anti-reflection coatings on the surfaces marked coated." + noanim)
    coat_k.setFlag(nuke.NO_ANIMATION)

    sint_k = _double("starIntensity", "Starburst Intensity", 0.0, 0.5, 0.02)
    slen_k = _double("starLength", "Length", 0.5, 1000.0, 60.0,
                     "Spike length in plate pixels at f/4 (spikes lengthen as you stop down).")
    sthk_k = _double("starThickness", "Thickness", 0.5, 20.0, 2.0, "Solid core width of the spikes in plate pixels.")
    ssoft_k = _double("starSoftness", "Softness", 0.0, 20.0, 1.2,
                      "Edge falloff width of the spikes in plate pixels (0 = crisp edge).")
    sfall_k = _double("starFalloff", "Falloff", 0.3, 8.0, 1.0,
                      "How spikes fade: 1 = soft exponential tail, 2 = Gaussian, higher = hard-ended needle.")
    srot_k = _double("starRotation", "Rotation", -180.0, 180.0, 0.0,
                     "Extra starburst rotation on top of the aperture Rotation.")
    schr_k = _double("starChroma", "Chromatic Spread", 0.0, 3.0, 1.0,
                     "0 = white spikes, 1 = physical (red longer than blue), above 1 = exaggerated.")
    sirr_k = _double("starIrregularity", "Irregularity", 0.0, 1.0, 0.0,
                     "Random per-spike length and brightness, like imperfect real blades.")
    sseed_k = nuke.Int_Knob("starSeed", "Seed")
    sseed_k.setValue(0)
    sseed_k.setTooltip("Re-rolls the Irregularity pattern.")
    glint_k = _double("glareIntensity", "Glare Intensity", 0.0, 0.1, 0.00001,
                      "Tiny values are normal: highlights are already lifted by Source Gain (2^stops).")
    glsize_k = _double("glareSize", "Glare Size", 10.0, 1000.0, 200.0)

    res_k = nuke.Enumeration_Knob("flareRes", "Flare Resolution", ["Full", "Half", "Quarter"])
    res_k.setValue("Half")
    mode_k = nuke.Enumeration_Knob("outputMode", "Output",
                                   ["Flare over Plate", "Flare Only", "Highlights", "Aperture"])
    inv_k = nuke.Boolean_Knob("invertMask", "Invert Mask", False)
    inv_k.setFlag(nuke.STARTLINE)
    mix_k = _double("mix", "Mix", 0.0, 1.0, 1.0)
    mix_k.clearFlag(nuke.STARTLINE)
    status_k = nuke.Text_Knob("status", "Status", "(not solved)")
    note_k = nuke.Text_Knob("inputsNote", "", "")

    hidden = []
    for n in range(SLOTS):
        for suffix in SLOT_KNOB_SUFFIXES:
            default = 0.0 if suffix[0] == "e" else 1.0
            k = nuke.Double_Knob("g%d%s" % (n, suffix), "g%d%s" % (n, suffix))
            k.setValue(default)
            k.setFlag(nuke.INVISIBLE)
            hidden.append(k)
    eff_k = nuke.Double_Knob("effFstop", "effFstop")
    eff_k.setValue(2.8)
    eff_k.setFlag(nuke.INVISIBLE)
    hidden.append(eff_k)

    ghosts_on = elements.bool_knob(nuke, "ghostsOn", "Ghosts", True)
    star_on = elements.bool_knob(nuke, "starOn", "Starburst", True)
    glare_on = elements.bool_knob(nuke, "glareOn", "Veiling Glare", True)
    overscan_k = _double("overscan", "Overscan %", 0.0, 100.0, 25.0,
                         "Extra canvas around the frame (per side) so shapes are not cropped at the "
                         "frame edge and light does not wrap across it. Costs render time: "
                         "25% is about 2.25x the canvas area.")

    lens_tab = [nuke.Tab_Knob("tabLens", "Lens")] + presets.row_knobs(nuke) + [
                preset_k, custom_k, fstop_k, sensor_k,
                _divider("divSrc"), _heading("hdrSrc", "Source"), thr_k, knee_k, stops_k,
                _divider("divAp"), _heading("hdrAp", "Aperture"), blades_k, round_k, rot_k, apshape_k, squeeze_k,
                _divider("divOut"), _heading("hdrOut", "Output"), res_k, overscan_k, mode_k, inv_k, mix_k,
                status_k, note_k]
    ghosts_tab = ([nuke.Tab_Knob("tabGhosts", "Ghosts & Glare")]
                  + _master_knobs()
                  + [_divider("divGhosts"), ghosts_on, count_k, gint_k, disp_k, coat_k]
                  + elements.colour_knobs(nuke, "ghosts")
                  + elements.offset_knobs(nuke, "ghosts")
                  + [_divider("divStar"), star_on, sint_k, slen_k, sthk_k, ssoft_k, sfall_k,
                     srot_k, schr_k, sirr_k, sseed_k]
                  + elements.offset_knobs(nuke, "star")
                  + [_divider("divGlare"), glare_on, glint_k, glsize_k])
    for k in lens_tab + ghosts_tab + hidden:
        group.addKnob(k)

    elements.add_element_knobs(group, nuke, center_k)
    dirt.add_dirt_knobs(group, nuke, width, height)

    group.addKnob(_divider("creditDivider"))
    group.addKnob(nuke.Text_Knob("credit", "", "<span style='color:#777; font-size:11px;'>"
                                 "Made by Sid (www.sidmanvfx.com)</span>"))


# -- Solve ---------------------------------------------------------------------

def _current_lens(group):
    name = group["lensPreset"].value()
    if name == CUSTOM:
        return optics.parse_prescription(group["customPrescription"].value())
    return optics.preset(name)


def solve(group):
    """Re-trace the lens and write every ghost slot's knobs. On a bad custom
    prescription (or a lens that cannot be traced) the previous solve is kept
    and Status shows the error."""
    count = max(0, min(SLOTS, int(group["ghostCount"].value())))
    try:
        lens = _current_lens(group)
        ghosts, info = optics.solve(lens, group["fstop"].value(), bool(group["coatings"].value()), count)
    except optics.PrescriptionError as err:
        group["status"].setValue("<span style='color:#e05050'>Prescription error, %s "
                                 "(previous solve kept)</span>" % _html(err))
        return
    except (ArithmeticError, ValueError) as err:
        group["status"].setValue("<span style='color:#e05050'>Lens could not be traced: %s "
                                 "(previous solve kept)</span>" % _html(err))
        return
    for n in range(SLOTS):
        if n < len(ghosts):
            g = ghosts[n]
            vals = (g.scale[0], g.scale[1], g.scale[2], g.radius_mm, g.rgb[0], g.rgb[1], g.rgb[2])
        else:
            vals = (1.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0)
        for suffix, v in zip(SLOT_KNOB_SUFFIXES, vals):
            group["g%d%s" % (n, suffix)].setValue(v)
    group["effFstop"].setValue(info["fnumber"])
    msg = "EFL %.1fmm  f/%.1f  %d of %d ghosts" % (info["efl"], info["fnumber"], len(ghosts), info["pairs"])
    if info["clamped"]:
        msg += "  (f-stop clamped to lens maximum f/%.1f)" % info["max_fnumber"]
    group["status"].setValue(msg)


def finish_preset(group):
    """After a preset was applied (callbacks muted): re-trace the lens, redraw the Offset handles and recreate the
    optional input pipes once."""
    solve(group)
    elements.sync_offset_visibility(group)
    inputs.sync(group)


def _on_knob_changed():
    if presets.muted():
        return
    k = nuke.thisKnob()
    if k is not None and (k.name().endswith("OffsetOn") or k.name() == "streakCount"):
        try:
            if k.name() == "streakCount":
                elements.sync_offset_visibility(nuke.thisNode())
            else:
                elements.sync_offset_visibility(nuke.thisNode(), k.name()[:-len("OffsetOn")])
        except Exception as err:
            print("Lens Flare: could not update knob visibility: %s" % err)
        return
    if k is not None and k.name() == "squeeze":
        try:
            elements.squeeze_streak_defaults(nuke.thisNode())
        except Exception as err:
            print("Lens Flare: could not update the Streak default: %s" % err)
        return
    if k is not None and (k.name() in INPUT_KNOBS or k.name() == "inputChange"):
        try:
            if k.name() == "inputChange":
                inputs.update_note(nuke.thisNode())
            else:
                inputs.sync(nuke.thisNode())
        except Exception as err:
            print("Lens Flare: could not update the optional inputs: %s" % err)
        return
    if k is not None and k.name() in SOLVE_KNOBS:
        node = nuke.thisNode()
        try:
            solve(node)
        except Exception as err:
            node["status"].setValue("<span style='color:#e05050'>Solve failed: %s</span>" % _html(err))


# -- Create / menu ---------------------------------------------------------------

def make_lens_flare():
    selected = None
    try:
        selected = nuke.selectedNode()
    except ValueError:
        pass
    if selected is not None and selected.width() > 0 and selected.height() > 0:
        width, height = selected.width(), selected.height()
    else:
        fmt = nuke.root().format()
        width, height = fmt.width(), fmt.height()
    group = nuke.createNode("Group", inpanel=False)
    group.setName("LensFlare")
    with group:
        nuke.tcl(build_tcl())
    before = set(group.knobs())
    _add_knobs(group, width, height)
    presets.record_knobs(group, before)
    presets.refresh_menu(group)
    elements.sync_offset_visibility(group)
    group["knobChanged"].setValue("import sid_lens_flare\nsid_lens_flare._on_knob_changed()\n")
    # Knob visibility is not saved with the script: re-apply it (Use Offset and
    # the streak slots) when the script loads.
    group["onCreate"].setValue("import sid_flare_elements\n"
                               "sid_flare_elements.sync_offset_visibility(nuke.thisNode())\n"
                               "import sid_flare_presets\n"
                               "sid_flare_presets.refresh_menu(nuke.thisNode())\n")
    solve(group)
    group["label"].setValue("[value lensPreset]  f/[value effFstop]")
    if selected is not None:
        try:
            group.setInput(0, selected)
        except Exception:
            pass
    if nuke.GUI:
        group.showControlPanel()
    return group


def install_menu():
    nuke.menu("Nodes").addMenu("Sid", icon=None).addCommand("Lens Flare", make_lens_flare)

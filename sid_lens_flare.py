# Sid Lens Flare for Nuke -- image-driven, physically traced lens flare.
#
# Every highlight in the plate flares. Ghost position, flip, size, colour and
# chromatic fringing come from tracing light through a real lens prescription
# (sid_lens_optics.py); each ghost is the highlights remapped through that
# reflection path and convolved with the actual aperture shape.
#
# Non-Commercial safe: the whole internal graph is built by ONE nuke.tcl()
# call and Python never looks up nodes inside the Group -- it only reads and
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

SLOTS = optics.MAX_GHOST_SLOTS
RES = "pow(0.5,parent.flareRes)"          # Full=1, Half=0.5, Quarter=0.25
SLOT_KNOB_SUFFIXES = ("sR", "sG", "sB", "rad", "eR", "eG", "eB")
SOLVE_KNOBS = ("lensPreset", "customPrescription", "fstop", "ghostCount", "coatings")
CUSTOM = "Custom"
SPIKE_WIDTH_PX = 1.2      # starburst spike cross-section width, in working-resolution px
REF_WIDTH = 1920.0        # Starburst Length is defined for a 1920px-wide frame
REF_FSTOP = 4.0           # Starburst Length is defined at f/4
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
    Slots at or beyond Ghost Count are disabled and output black."""
    off = "{{parent.ghostCount<=%d}}" % n
    cx = "{parent.opticalCenter.x*%s}" % RES
    cy = "{parent.opticalCenter.y*%s}" % RES
    out = ["push $hl"]
    for ch, key in (("red", "R"), ("green", "G"), ("blue", "B")):
        if key == "G":
            scale = "parent.g%dsG" % n
        else:
            scale = "parent.g%dsG+parent.dispersion*(parent.g%ds%s-parent.g%dsG)" % (n, n, key, n)
        out.append(
            "TransformMasked {\n channels rgba.%s\n scale {{%s}}\n center {%s %s}\n"
            " filter cubic\n black_outside true\n disable %s\n name g%dT%s\n}" % (ch, scale, cx, cy, off, n, key))
    out.append("set g%dsrc [stack 0]" % n)
    out.append("push $hl")
    out.append("Expression {\n%s disable %s\n name g%dAperture\n}"
               % (_aperture_expr("parent.g%drad*width/parent.sensorWidth" % n), off, n))
    out.append("push $g%dsrc" % n)
    out.append("Convolve2 {\n inputs 2\n channels rgb\n filter_channel rgba.alpha\n normalize true\n"
               " disable %s\n name g%dConv\n}" % (off, n))
    out.append(
        "Expression {\n"
        " temp_name0 on\n temp_expr0 {(parent.ghostCount>%d)*parent.ghostIntensity}\n"
        " expr0 {r*on*parent.g%deR}\n expr1 {g*on*parent.g%deG}\n expr2 {b*on*parent.g%deB}\n expr3 0\n"
        " name g%dGain\n}" % (n, n, n, n, n))
    out.append("set g%d [stack 0]" % n)
    return "\n".join(out)


def _sinc2(arg):
    """(sin(pi*s)/(pi*s))^2 written inline, guarded at 0 (Nuke expressions
    have no user-defined functions)."""
    return "((%s)<0.0001?1:pow(sin(pi*(%s))/(pi*(%s)),2))" % (arg, arg, arg)


def _spike_sum(length_px_expr):
    """Diffraction spikes of an n-blade aperture: one full line through the
    centre along each edge normal (up to 12 blades), sinc^2 cross-profile,
    Lorentzian ~1/r^2 fall-off of length `length_px_expr`. Odd blade counts
    give 2n spikes; even counts give n, as opposite pairs coincide (the
    doubled intensity is removed by Convolve2 normalize)."""
    terms = []
    for k in range(12):
        th = "(parent.apRotation*pi/180+sec/2+%d*sec)" % k
        terms.append("(%d<%s)*%s"
                     % (k, BLADES, _sinc2("rad*abs(sin(ang-%s))/%g" % (th, SPIKE_WIDTH_PX))))
    return "(rad<1.5?0:(%s)/(1+pow(rad/max(1,%s),2)))" % ("+".join(terms), length_px_expr)


def _starburst_tcl():
    """Analytic diffraction kernel (wavelength-scaled per channel), convolved
    with the highlights one channel at a time."""
    lines = ["push $hl", "Expression {",
             " temp_name0 rad", " temp_expr0 {hypot(x+0.5-width/2,y+0.5-height/2)}",
             " temp_name1 ang", " temp_expr1 {atan2(y+0.5-height/2,x+0.5-width/2)}",
             " temp_name2 sec", " temp_expr2 {2*pi/" + BLADES + "}"]
    for i, w in enumerate(optics.WAVELENGTHS_UM):
        length = "parent.starLength*width/%g*parent.effFstop/%g*%.4f" % (
            REF_WIDTH, REF_FSTOP, w / optics.WAVELENGTHS_UM[1])
        lines.append(" expr%d {%s}" % (i, _spike_sum(length)))
    lines += [" expr3 0", " disable {{parent.starIntensity<=0}}", " name starKernel", "}",
              "set starK [stack 0]", "push $hl", "set star_in [stack 0]"]
    for ch in ("red", "green", "blue"):
        lines += ["push $starK", "push $star_in",
                  "Convolve2 {", " inputs 2", " channels rgba.%s" % ch, " filter_channel rgba.%s" % ch,
                  " normalize true", " disable {{parent.starIntensity<=0}}", " name star_%s" % ch, "}",
                  "set star_in [stack 0]"]
    lines += ["Expression {", " expr0 {r*parent.starIntensity}", " expr1 {g*parent.starIntensity}",
              " expr2 {b*parent.starIntensity}", " expr3 0", " name starGain", "}", "set star [stack 0]"]
    return "\n".join(lines)


def build_tcl():
    """Whole internal graph as TCL. Order: highlights -> Reformat down ($hl, the
    downscaled highlight stream every branch reads) -> ghost slots, starburst,
    glare -> summed, Reformat up -> merged over the plate -> output switch -> mask mix."""
    parts = ["""
Input { inputs 0 name Source xpos 0 ypos 0 }
set in_src [stack 0]
Input { inputs 0 name Mask number 1 xpos 400 ypos 0 }
set in_mask [stack 0]

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
 type scale
 scale {{""" + RES + """}}
 name flareDown
}
set hl [stack 0]
"""]
    for n in range(SLOTS):
        parts.append(_ghost_tcl(n))
    parts.append(_starburst_tcl())
    parts.append("""
push $hl
Blur { channels rgb size {{parent.glareSize*""" + RES + """}} disable {{parent.glareIntensity<=0}} name glareA }
set glareA [stack 0]
push $hl
Blur { channels rgb size {{parent.glareSize*4*""" + RES + """}} disable {{parent.glareIntensity<=0}} name glareB }
push $glareA
Merge2 { inputs 2 operation plus also_merge all name glareSum }
Expression {
 expr0 {r*0.5*parent.glareIntensity}
 expr1 {g*0.5*parent.glareIntensity}
 expr2 {b*0.5*parent.glareIntensity}
 expr3 0
 name glareGain
}
set glare [stack 0]
""")
    acc = "$star"
    for src in ["$glare"] + ["$g%d" % n for n in range(SLOTS)]:
        parts.append("push %s\npush %s\nMerge2 { inputs 2 operation plus also_merge all }\nset acc [stack 0]"
                     % (src, acc))
        acc = "$acc"
    parts.append("""
push $acc
Reformat {
 type scale
 scale {{1/""" + RES + """}}
 name flareUp
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

    count_k = nuke.Int_Knob("ghostCount", "Ghost Count")
    count_k.setValue(8)
    count_k.setRange(0, SLOTS)
    gint_k = _double("ghostIntensity", "Ghost Intensity", 0.0, 10.0, 1.0)
    disp_k = _double("dispersion", "Dispersion", 0.0, 2.0, 1.0, "1 = physical glass dispersion, 0 = none.")
    count_k.setTooltip("Number of ghosts (brightest first)." + noanim)
    count_k.setFlag(nuke.NO_ANIMATION)
    coat_k = nuke.Boolean_Knob("coatings", "Coatings", True)
    coat_k.setTooltip("Anti-reflection coatings on the surfaces marked coated." + noanim)
    coat_k.setFlag(nuke.NO_ANIMATION)

    sint_k = _double("starIntensity", "Starburst Intensity", 0.0, 0.5, 0.02)
    slen_k = _double("starLength", "Starburst Length", 1.0, 400.0, 60.0)
    glint_k = _double("glareIntensity", "Glare Intensity", 0.0, 0.0005, 0.00001,
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

    for k in [preset_k, custom_k, fstop_k, sensor_k, center_k,
              _divider("divSrc"), _heading("hdrSrc", "Source"), thr_k, knee_k, stops_k,
              _divider("divAp"), _heading("hdrAp", "Aperture"), blades_k, round_k, rot_k,
              _divider("divGhost"), _heading("hdrGhost", "Ghosts"), count_k, gint_k, disp_k, coat_k,
              _divider("divStar"), _heading("hdrStar", "Starburst"), sint_k, slen_k,
              _divider("divGlare"), _heading("hdrGlare", "Veiling Glare"), glint_k, glsize_k,
              _divider("divOut"), _heading("hdrOut", "Output"), res_k, mode_k, inv_k, mix_k, status_k] + hidden:
        group.addKnob(k)

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


def _on_knob_changed():
    k = nuke.thisKnob()
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
    _add_knobs(group, width, height)
    group["knobChanged"].setValue("import sid_lens_flare\nsid_lens_flare._on_knob_changed()\n")
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

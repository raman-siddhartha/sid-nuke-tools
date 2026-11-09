# Sid Lens Flare -- flare elements (v2).
#
# Eleven switchable elements added to the Lens Flare node: five centred on
# each light (Streak, Spike Ball, Shimmer, Sparkle, Glint), four placed along
# the flare axis (Iris, Multi-Iris, Rings, Caustic) and two lit by nearby
# light (Hoop, Lens Orbs). Each element reads either the downscaled
# highlights ($hl) or the hotspot stream ($hot: one point per light).
#
# Same rules as sid_lens_flare.py: the TCL generators here are pure string
# functions; the graph is built in the node's single nuke.tcl() call; no
# internal node lookups; no space inside any single {{...}}; temp names never
# r/g/b/a/x/y/z; gain nodes never disabled (an element that is off is
# disabled upstream AND multiplied by its On knob, which is 0).
#
# Strict ASCII.

RES = "pow(0.5,parent.flareRes)"          # plate px -> working px
CX = "parent.opticalCenter.x*" + RES      # optical centre in working px
CY = "parent.opticalCenter.y*" + RES
AA = 0.35                                 # minimum sigma (working px) against aliasing
MULTI_IRIS_SLOTS = 8
RING_SLOTS = 4
MAX_SPIKE_RAYS = 64
MAX_SPARKLE_POINTS = 8
MAX_ORBS = 64

# Added to every kernel's alpha so the centre pixel(s) always carry a tiny
# weight: Convolve2 normalize divides by the kernel sum, and a zero-sum kernel
# (e.g. a ring larger than the frame) would blow up.
CENTRE_FLOOR = ("((x+0.5-width/2)*(x+0.5-width/2)+(y+0.5-height/2)*(y+0.5-height/2)<1?0.000001:0)")

SOURCES = ["All highlights", "Hotspot"]

# id, label, family, default source index. `family` only documents the grouping
# used in the panel/README; nothing derives from it.
ELEMENTS = (
    ("streak", "Streak", "centred", 1),
    ("spikeBall", "Spike Ball", "centred", 1),
    ("shimmer", "Shimmer", "centred", 1),
    ("sparkle", "Sparkle", "centred", 1),
    ("glint", "Glint", "centred", 1),
    ("iris", "Iris", "axial", 0),
    ("multiIris", "Multi-Iris", "axial", 0),
    ("rings", "Rings", "axial", 0),
    ("caustic", "Caustic", "axial", 0),
    ("hoop", "Hoop", "lit", 0),
    ("orbs", "Lens Orbs", "lit", 0),
)

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
    "iris": (
        ("Position", "Position", "d", -2, 2, -0.6, "Along the flare axis: 1 = at the light, 0 = optical centre, -1 = mirror."),
        ("Size", "Size", "d", 1, 500, 60, "Radius in plate px at f/2.8 (shrinks as you stop down). Shapes larger than the frame are capped."),
        ("Softness", "Softness", "d", 0, 50, 1, "Edge softness in plate px."),
    ),
    "multiIris": (
        ("Count", "Count", "i", 1, MULTI_IRIS_SLOTS, 5, "Number of irises. Max 8."),
        ("Spread", "Spread", "d", 0, 2, 1.2, "Positions are spread over -Spread..+Spread along the axis."),
        ("SizeMin", "Size Min", "d", 1, 500, 15, "Plate px at f/2.8. Shapes larger than the frame are capped."),
        ("SizeMax", "Size Max", "d", 1, 500, 70, "Plate px at f/2.8. Shapes larger than the frame are capped."),
        ("ColorVar", "Colour Variation", "d", 0, 1, 0.5, None),
        ("Seed", "Seed", "i", 0, 9999, 0, None),
    ),
    "rings": (
        ("Count", "Count", "i", 1, RING_SLOTS, 2, "Number of rings. Max 4."),
        ("Position", "Position", "d", -2, 2, -0.9, "First ring along the flare axis."),
        ("Spacing", "Spacing", "d", -1, 1, 0.25, "Axis distance between rings."),
        ("Radius", "Radius", "d", 2, 900, 120, "Plate px. Shapes larger than the frame are capped."),
        ("Thickness", "Thickness", "d", 0.5, 50, 3, "Plate px."),
    ),
    "caustic": (
        ("Position", "Position", "d", -2, 2, -0.3, None),
        ("Size", "Size", "d", 2, 500, 90, "Radius in plate px. Shapes larger than the frame are capped."),
        ("Sharpness", "Edge Sharpness", "d", 0.5, 10, 3, "Higher = thinner, brighter caustic edge."),
    ),
    "hoop": (
        ("Radius", "Radius", "d", 0.05, 1.5, 0.45, "Fraction of frame height."),
        ("Width", "Width", "d", 0.5, 200, 12, "Plate px."),
        ("Arc", "Arc Falloff", "d", 10, 3000, 600, "How far light reaches around the hoop (plate px blur)."),
    ),
    "orbs": (
        ("Count", "Count", "i", 8, MAX_ORBS, 24, "Number of orbs. Max 64."),
        ("SizeMin", "Size Min", "d", 1, 500, 10, "Radius in plate px."),
        ("SizeMax", "Size Max", "d", 1, 500, 45, "Radius in plate px."),
        ("Proximity", "Proximity", "d", 10, 3000, 400, "How close a light must be to light an orb (plate px)."),
        ("Softness", "Softness", "d", 0, 1, 0.5, None),
        ("Seed", "Seed", "i", 0, 9999, 0, None),
    ),
}

# Tuned in Nuke on a 6px light at value 5 with Source Gain 12 stops, so each
# element peaks around 0.5-4 near the light. Hotspot-fed elements are small
# because a hotspot carries the light's whole energy in one pixel.
DEFAULT_INTENSITY = {
    "streak": 0.002, "spikeBall": 0.004, "shimmer": 0.01, "sparkle": 0.0002, "glint": 0.0005,
    "iris": 0.002, "multiIris": 0.0005, "rings": 0.002, "caustic": 0.002,
    "hoop": 0.01, "orbs": 0.04,
}


def knob_names(eid):
    """Every knob an element owns (for tests and the knob builder)."""
    names = [eid + "On", eid + "Intensity", eid + "Source", eid + "Tint"]
    names += [eid + spec[0] for spec in EXTRA[eid]]
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


def _source(eid):
    """Switch between $hl (0) and $hot (1) by the element's Source knob."""
    return ("push $hot\npush $hl\nSwitch {\n inputs 2\n which {{parent.%sSource}}\n name %sSrc\n}\n"
            "set %s_src [stack 0]" % (eid, eid, eid))


def _kernel(eid, name, body_lines, disable=None):
    """Procedural kernel Expression (alpha only) centred on the working format.
    The alpha gets CENTRE_FLOOR added so the kernel sum is always positive."""
    lines = []
    for ln in body_lines:
        if ln.startswith(" expr3 {"):
            ln = " expr3 {(%s)+%s}" % (ln[len(" expr3 {"):-1], CENTRE_FLOOR)
        lines.append(ln)
    return ("push $hl\nExpression {\n%s\n disable %s\n name %s\n}"
            % ("\n".join(lines), disable or _on(eid), name))


def _convolve(eid, kernel_var, src_var, name):
    return ("push $%s\npush $%s\nConvolve2 {\n inputs 2\n channels rgb\n filter_channel rgba.alpha\n"
            " normalize true\n disable %s\n name %s\n}" % (kernel_var, src_var, _on(eid), name))


def _gain(eid, name, extra="1"):
    """Never disabled: multiplies by On, Intensity, Tint and `extra`."""
    k = "parent.%sOn*parent.%sIntensity*(%s)" % (eid, eid, extra)
    return ("Expression {\n temp_name0 kk\n temp_expr0 {%s}\n"
            " expr0 {r*kk*parent.%sTint.r}\n expr1 {g*kk*parent.%sTint.g}\n expr2 {b*kk*parent.%sTint.b}\n"
            " expr3 0\n name %s\n}" % (k, eid, eid, eid, name))


def _centre_temps():
    return [" temp_name0 dx", " temp_expr0 {x+0.5-width/2}",
            " temp_name1 dy", " temp_expr1 {y+0.5-height/2}"]


def _ray(angle_expr, length_expr, sigma_expr, falloff="1"):
    """One half-ray from the centre: Gaussian cross-section, exp fall-off."""
    return ("(cos(atan2(dy,dx)-(%s))>0)*exp(-pow(hypot(dx,dy)*sin(atan2(dy,dx)-(%s))/(%s),2)/2)"
            "*exp(-pow(hypot(dx,dy)/max(0.01,%s),max(0.2,%s)))" % (angle_expr, angle_expr, sigma_expr, length_expr, falloff))


def _finish(eid, out_lines, kernel, conv_src="%s_src", gain_extra="1"):
    out_lines.append(kernel)
    out_lines.append("set %sK [stack 0]" % eid)
    out_lines.append(_convolve(eid, "%sK" % eid, conv_src % eid, "%sConv" % eid))
    out_lines.append(_gain(eid, "%sGain" % eid, gain_extra))
    out_lines.append("set el_%s [stack 0]" % eid)
    return "\n".join(out_lines)


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
        " temp_expr3 {noise(cos(atan2(dy,dx))*%s+%s*1.37,sin(atan2(dy,dx))*%s,frame*%s*0.15)}"
        % (f, p(e, "Seed"), f, p(e, "Speed")),
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
        tw = "(0.6+0.4*sin(frame*%s+%d*2.399))" % (p(e, "Speed"), k)
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


# -- axial elements -------------------------------------------------------------------

def _safe_pos(expr):
    """Signed position kept at |p| >= 0.05 (gain divides by p^2)."""
    return "(abs(%s)<0.05?(%s<0?-0.05:0.05):%s)" % (expr, expr, expr)


def _axial_copy(eid, pos_expr, disable, name):
    """Highlights scaled about the optical centre by `pos_expr` (1 = at the light)."""
    return ("push $%s_src\nTransformMasked {\n channels rgb\n scale {{%s}}\n center {{%s} {%s}}\n"
            " filter cubic\n black_outside true\n disable %s\n name %s\n}" % (eid, pos_expr, CX, CY, disable, name))


def _shape_lines(radius_expr, shape_expr):
    """Centred kernel temps: dist, sec, aw (aperture angle), R."""
    return [" temp_name0 dist", " temp_expr0 {hypot(x+0.5-width/2,y+0.5-height/2)}",
            " temp_name1 sec", " temp_expr1 {2*pi/clamp(parent.blades,3,12)}",
            " temp_name2 aw", " temp_expr2 {atan2(y+0.5-height/2,x+0.5-width/2)-parent.apRotation*pi/180}",
            " temp_name3 R", " temp_expr3 {max(0.5,min(%s,min(width,height)/2-4))}" % radius_expr,
            " expr0 0", " expr1 0", " expr2 0", " expr3 {%s}" % shape_expr]


APERTURE_EDGE = "lerp(R*cos(sec/2)/cos(aw-sec*floor(aw/sec)-sec/2),R,parent.apRoundness)"


def _iris_shape(soft_expr):
    return "clamp((%s-dist)/max(0.5,%s)+0.5,0,1)" % (APERTURE_EDGE, soft_expr)


def _iris_tcl():
    e = "iris"
    pos = _safe_pos(p(e, "Position"))
    out = [_source(e), _axial_copy(e, pos, _on(e), "irisCopy"), "set irisSrcT [stack 0]"]
    radius = "%s*%s*2.8/parent.effFstop" % (p(e, "Size"), RES)
    kernel = _kernel(e, "irisKernel", _shape_lines(radius, _iris_shape("%s*%s" % (p(e, "Softness"), RES))))
    return _finish(e, out, kernel, conv_src="%sSrcT", gain_extra="1/pow(%s,2)" % pos)


def _multi_iris_tcl():
    e = "multiIris"
    seed = p(e, "Seed")
    out = [_source(e)]
    for i in range(MULTI_IRIS_SLOTS):
        off = "{{!parent.%sOn||parent.%sCount<=%d}}" % (e, e, i)
        pos = _safe_pos("lerp(-%s,%s,%s)" % (p(e, "Spread"), p(e, "Spread"), _hash(i, 3.17, 5.71, seed)))
        size = "lerp(%s,%s,%s)*%s*2.8/parent.effFstop" % (p(e, "SizeMin"), p(e, "SizeMax"),
                                                          _hash(i, 7.31, 2.93, seed), RES)
        out.append(_axial_copy(e, pos, off, "multiIrisCopy%d" % i))
        out.append("set mi%dT [stack 0]" % i)
        out.append(_kernel(e, "multiIrisKernel%d" % i, _shape_lines(size, _iris_shape("1")), off))
        out.append("set mi%dK [stack 0]" % i)
        out.append("push $mi%dK\npush $mi%dT\nConvolve2 {\n inputs 2\n channels rgb\n filter_channel rgba.alpha\n"
                   " normalize true\n disable %s\n name multiIrisConv%d\n}" % (i, i, off, i))
        cv = p(e, "ColorVar")
        tint = ["(1+%s*(%s-0.5))" % (cv, _hash(i, c, hb, seed)) for c, hb in ((11.1, 1.618), (22.2, 2.414), (33.3, 3.732))]
        out.append(
            "Expression {\n temp_name0 kk\n temp_expr0 {parent.%sOn*(parent.%sCount>%d)*parent.%sIntensity/pow(%s,2)}\n"
            " expr0 {r*kk*parent.%sTint.r*%s}\n expr1 {g*kk*parent.%sTint.g*%s}\n expr2 {b*kk*parent.%sTint.b*%s}\n"
            " expr3 0\n name multiIrisGain%d\n}" % (e, e, i, e, pos, e, tint[0], e, tint[1], e, tint[2], i))
        out.append("set mi%d [stack 0]" % i)
    acc = "$mi0"
    for i in range(1, MULTI_IRIS_SLOTS):
        out.append("push $mi%d\npush %s\nMerge2 { inputs 2 operation plus also_merge all }\nset mi_acc [stack 0]" % (i, acc))
        acc = "$mi_acc"
    out.append("push %s\nset el_%s [stack 0]" % (acc, e))
    return "\n".join(out)


def _rings_tcl():
    e = "rings"
    out = [_source(e)]
    for i in range(RING_SLOTS):
        off = "{{!parent.%sOn||parent.%sCount<=%d}}" % (e, e, i)
        pos = _safe_pos("(%s+%d*%s)" % (p(e, "Position"), i, p(e, "Spacing")))
        out.append(_axial_copy(e, pos, off, "ringsCopy%d" % i))
        out.append("set rg%dT [stack 0]" % i)
        shape = "exp(-pow((dist-R)/hypot(%s*%s/2.355,%g),2)/2)" % (p(e, "Thickness"), RES, AA)
        radius = "%s*%s*(1+%d*0.18)" % (p(e, "Radius"), RES, i)
        out.append(_kernel(e, "ringsKernel%d" % i, _shape_lines(radius, shape), off))
        out.append("set rg%dK [stack 0]" % i)
        out.append("push $rg%dK\npush $rg%dT\nConvolve2 {\n inputs 2\n channels rgb\n filter_channel rgba.alpha\n"
                   " normalize true\n disable %s\n name ringsConv%d\n}" % (i, i, off, i))
        out.append(
            "Expression {\n temp_name0 kk\n temp_expr0 {parent.%sOn*(parent.%sCount>%d)*parent.%sIntensity/pow(%s,2)}\n"
            " expr0 {r*kk*parent.%sTint.r}\n expr1 {g*kk*parent.%sTint.g}\n expr2 {b*kk*parent.%sTint.b}\n"
            " expr3 0\n name ringsGain%d\n}" % (e, e, i, e, pos, e, e, e, i))
        out.append("set rg%d [stack 0]" % i)
    acc = "$rg0"
    for i in range(1, RING_SLOTS):
        out.append("push $rg%d\npush %s\nMerge2 { inputs 2 operation plus also_merge all }\nset rg_acc [stack 0]" % (i, acc))
        acc = "$rg_acc"
    out.append("push %s\nset el_%s [stack 0]" % (acc, e))
    return "\n".join(out)


def _caustic_tcl():
    e = "caustic"
    pos = _safe_pos(p(e, "Position"))
    out = [_source(e), _axial_copy(e, pos, _on(e), "causticCopy"), "set causticSrcT [stack 0]"]
    shape = ("clamp(R-dist+0.5,0,1)*(0.12+pow(clamp(dist/R,0,1),max(0.1,%s)*4))"
             "*(0.65+0.35*cos(clamp(parent.blades,3,12)*aw))" % p(e, "Sharpness"))
    kernel = _kernel(e, "causticKernel", _shape_lines("%s*%s" % (p(e, "Size"), RES), shape))
    return _finish(e, out, kernel, conv_src="%sSrcT", gain_extra="1/pow(%s,2)" % pos)


# -- light-lit elements (no convolution) ----------------------------------------------

def _hoop_tcl():
    e = "hoop"
    return "\n".join([
        _source(e),
        "push $%s_src\nBlur {\n channels rgb\n size {{%s*%s}}\n disable %s\n name hoopReach\n}" % (
            e, p(e, "Arc"), RES, _on(e)),
        "Expression {\n temp_name0 hd\n temp_expr0 {hypot(x+0.5-%s,y+0.5-%s)}\n"
        " temp_name1 hr\n temp_expr1 {%s*height}\n"
        " temp_name2 hw\n temp_expr2 {hypot(%s*%s/2.355,%g)}\n"
        " temp_name3 m\n temp_expr3 {exp(-pow((hd-hr)/hw,2)/2)}\n"
        " expr0 {r*m}\n expr1 {g*m}\n expr2 {b*m}\n expr3 0\n disable %s\n name hoopShape\n}" % (
            CX, CY, p(e, "Radius"), p(e, "Width"), RES, AA, _on(e)),
        _gain(e, "hoopGain"),
        "set el_%s [stack 0]" % e,
    ])


def _orbs_tcl():
    e = "orbs"
    seed = p(e, "Seed")
    discs = []
    for k in range(MAX_ORBS):
        ox = "%s*width" % _hash(k, 1.13, 4.7, seed)
        oy = "%s*height" % _hash(k, 2.71, 9.2, seed)
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
    "sparkle": _sparkle_tcl, "glint": _glint_tcl, "iris": _iris_tcl, "multiIris": _multi_iris_tcl,
    "rings": _rings_tcl, "caustic": _caustic_tcl, "hoop": _hoop_tcl, "orbs": _orbs_tcl,
}


def elements_tcl():
    """Hotspot detector + every element branch. Leaves $el_<id> for each."""
    return "\n".join([hotspot_tcl()] + [GENERATORS[eid]() for eid, _l, _f, _s in ELEMENTS])


def element_vars():
    return ["$el_%s" % eid for eid, _l, _f, _s in ELEMENTS]


# -- knobs (needs nuke) -------------------------------------------------------------------

def add_element_knobs(group, nuke):
    """Elements tab: Hotspot Radius, then one closed group per element."""
    group.addKnob(nuke.Tab_Knob("tabElements", "Elements"))
    hot = nuke.Double_Knob("hotRadius", "Hotspot Radius")
    hot.setRange(2, 300)
    hot.setValue(24)
    hot.setTooltip("Plate px. Use at least the radius of your biggest light; lights closer than this merge into one hotspot.")
    group.addKnob(hot)
    for eid, label, family, src in ELEMENTS:
        group.addKnob(nuke.Tab_Knob("grp_" + eid, label, nuke.TABBEGINCLOSEDGROUP))
        on = nuke.Boolean_Knob(eid + "On", "Enable", False)
        group.addKnob(on)
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
            name = eid + suffix
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
            group.addKnob(k)
        group.addKnob(nuke.Tab_Knob("grp_%s_end" % eid, "", nuke.TABENDGROUP))

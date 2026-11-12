# Sid Lens Flare -- optional node inputs.
#
# The Lens Flare node has Source and Mask, plus optional inputs that exist on
# the node only while they are chosen (no hanging pipes):
#     Dirt      Texture = Input                (sid_flare_dirt)
#     DirtMask  Placement = Mask               (sid_flare_dirt)
#     Caustic   Caustic Shape = Input          (sid_flare_elements)
#     Ring      Rings or Ring / Halo Shape = Input
#     Aperture  Aperture Shape = Input         (ghosts, Iris, Multi-Iris)
# Until chosen, a black Constant (<Name>Off) stands in and a Dot (<Name>Src)
# carries it into the graph; every branch reads the Dot. sync() creates the
# Input node and feeds the Dot from it, or feeds the Dot from the stand-in again
# and deletes the Input node. It runs from knobChanged with nuke.tcl inside the
# group, so no Python Node objects are created. Input numbers stay gap free in
# the order above: Source 0, Mask 1, then the chosen ones from 2.
#
# An Input node that is not connected has a 1 px wide bounding box, so
# `<Name>Src.bbox.w>1` tells a connected input from an empty one in an expression
# (sid_flare_elements.custom_active builds it).
#
# Strict ASCII.

import nuke


class Spec(object):
    def __init__(self, name, var, wanted, empty_note):
        self.name = name                       # the Input node (arrow label)
        self.var = var                         # TCL variable holding the Dot output in build_tcl
        self.standin = name + "Off"            # black Constant used while the input does not exist
        self.dot = name + "Src"                # the node every branch reads
        self.wanted = wanted                   # group -> bool
        self.empty_note = empty_note           # what an unconnected input does


def _is(knob, value):
    return lambda group: group[knob].value() == value


SPECS = (
    Spec("Dirt", "in_dirt", _is("dirtTexture", "Input"), "no dirt is shown"),
    Spec("DirtMask", "in_dirtmask", _is("dirtPlacement", "Mask"), "no dirt is shown"),
    Spec("Caustic", "in_caustic", _is("causticShape", "Input"), "the procedural Caustic shape is used"),
    Spec("Ring", "in_ring",
         lambda g: g["ringsShape"].value() == "Input" or g["ringHaloShape"].value() == "Input",
         "the procedural ring shape is used"),
    Spec("Aperture", "in_aperture", _is("apShape", "Input"), "the n-blade aperture is used"),
)
FIRST_NUMBER = 2


def placeholders_tcl():
    """The stand-ins and Dots, leaving $in_dirt, $in_dirtmask, $in_caustic, $in_ring, $in_aperture."""
    out = []
    for i, s in enumerate(SPECS):
        out.append("Constant { inputs 0 channels rgba color {0 0 0 0} name %s xpos %d ypos 0 }\n"
                   "Dot { name %s }\nset %s [stack 0]" % (s.standin, 800 + 400 * i, s.dot, s.var))
    return "\n".join(out)


def _has_node(name):
    try:
        nuke.tcl("knob %s.name" % name)
        return True
    except Exception:
        return False


def numbers(group):
    """{input name: number} of the inputs that are wanted right now, gap free."""
    out, n = {}, FIRST_NUMBER
    for s in SPECS:
        if s.wanted(group):
            out[s.name] = n
            n += 1
    return out


def sync(group):
    """Create / remove the optional Input nodes to match the knobs, renumber them gap free, update the note."""
    nums = numbers(group)
    with group:
        for s in SPECS:
            has = _has_node(s.name)
            if s.name in nums and not has:
                nuke.tcl("Input { inputs 0 name %s number %d xpos %d ypos 0 }" % (s.name, nums[s.name], 800 + 400 * SPECS.index(s)))
                nuke.tcl("input %s 0 %s" % (s.dot, s.name))
            elif has and s.name not in nums:
                nuke.tcl("input %s 0 %s" % (s.dot, s.standin))
                nuke.tcl("delete %s" % s.name)
        for name, n in nums.items():
            nuke.tcl("knob %s.number %d" % (name, n))
    update_note(group, nums)


def update_note(group, nums=None):
    """Warn in the `inputsNote` knob about chosen inputs that have nothing connected (read with TCL from the
    group's own input list: no Python Node objects)."""
    if "inputsNote" not in group.knobs():
        return
    if nums is None:
        nums = numbers(group)
    lines = []
    for s in SPECS:
        if s.name in nums:
            try:
                connected = str(nuke.tcl("input %s %d" % (group.name(), nums[s.name]))) != "0"
            except Exception:
                connected = True
            if not connected:
                lines.append("%s input is not connected: %s." % (s.name, s.empty_note))
    group["inputsNote"].setValue("<span style='color:#d0a040'>%s</span>" % "<br>".join(lines) if lines else "")

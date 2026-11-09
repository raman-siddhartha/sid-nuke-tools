# Checks the generated TCL without Nuke (a stub `nuke` module is installed).
#     python -m unittest discover -s tests -v
import os
import re
import sys
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.modules.setdefault("nuke", types.ModuleType("nuke"))
import sid_lens_flare as lf  # noqa: E402
import sid_flare_elements as fe  # noqa: E402


class TclTests(unittest.TestCase):
    def setUp(self):
        self.tcl = lf.build_tcl()

    def test_no_spaces_inside_double_brace_expressions(self):
        # Nuke keeps only the first token of a spaced {{...}} expression.
        bad = [m for m in re.findall(r"\{\{[^}]*\}\}", self.tcl) if " " in m]
        self.assertEqual(bad, [])

    def test_braces_balanced(self):
        self.assertEqual(self.tcl.count("{"), self.tcl.count("}"))

    def test_every_slot_built_and_gated(self):
        for n in range(lf.SLOTS):
            self.assertIn("name g%dConv" % n, self.tcl)
            self.assertIn("{{parent.ghostCount<=%d||!parent.ghostsOn}}" % n, self.tcl)
            self.assertIn("(parent.ghostCount>%d)*parent.ghostIntensity" % n, self.tcl)

    def test_gain_nodes_never_disabled(self):
        # A disabled gain node would pass its unscaled input straight into the sum.
        element_gains = ["%sGain" % eid for eid, _l, _f, _s in fe.ELEMENTS if eid not in ("multiIris", "rings")]
        element_gains += ["multiIrisGain%d" % i for i in range(fe.MULTI_IRIS_SLOTS)]
        element_gains += ["ringsGain%d" % i for i in range(fe.RING_SLOTS)]
        for name in ["starGain", "glareGain"] + ["g%dGain" % n for n in range(lf.SLOTS)] + element_gains:
            block = re.search(r"Expression \{[^{}]*(?:\{[^{}]*\}[^{}]*)*name %s\b" % name, self.tcl)
            self.assertIsNotNone(block, name)
            self.assertNotIn("disable", block.group(0), name)

    def test_no_reserved_temp_names(self):
        temps = re.findall(r"temp_name\d (\w+)", self.tcl)
        self.assertFalse(set(temps) & {"r", "g", "b", "a", "x", "y", "z"})

    def test_starburst_uses_effective_fstop(self):
        self.assertNotIn("parent.fstop", self.tcl)
        self.assertIn("parent.effFstop", self.tcl)

    def test_single_tcl_block_has_one_output(self):
        self.assertEqual(self.tcl.count("Output {"), 1)

    def test_every_blade_edge_has_two_opposite_half_rays(self):
        # Odd blades -> 2n spikes needs a ray AND its opposite (+1*pi) per edge,
        # for each of the 3 wavelength channels.
        for k in range(12):
            self.assertEqual(self.tcl.count("+sec/2+%d*sec+0*pi)" % k), 3 * 2)
            self.assertEqual(self.tcl.count("+sec/2+%d*sec+1*pi)" % k), 3 * 2)

    def test_starburst_length_has_no_pixel_floor(self):
        # Old bug: max(1,length) made Length 1..10 render identically.
        end = self.tcl.index("name starKernel")
        block = self.tcl[self.tcl.rindex("Expression {", 0, end):end]
        self.assertNotIn("max(1,", block)
        self.assertIn("parent.starFalloff", block)

    def test_star_shape_knobs_used(self):
        for knob in ("starThickness", "starFalloff", "starRotation", "starChroma",
                     "starIrregularity", "starSeed", "starLength"):
            self.assertIn("parent.%s" % knob, self.tcl, knob)

    def test_blades_always_clamped(self):
        self.assertGreater(self.tcl.count("parent.blades"), 0)
        self.assertEqual(self.tcl.count("parent.blades"), self.tcl.count("clamp(parent.blades,3,12)"))


class _Knob(object):
    def __init__(self, v):
        self.v = v

    def value(self):
        return self.v

    def setValue(self, v):
        self.v = v


class SolveTests(unittest.TestCase):
    def _group(self, preset, text="", fstop=2.8):
        g = {"lensPreset": _Knob(preset), "customPrescription": _Knob(text), "fstop": _Knob(fstop),
             "ghostCount": _Knob(8), "coatings": _Knob(True), "status": _Knob(""), "effFstop": _Knob(2.8)}
        for n in range(lf.SLOTS):
            for s in ("sR", "sG", "sB", "rad", "eR", "eG", "eB"):
                g["g%d%s" % (n, s)] = _Knob(-7.0)
        return g

    def test_preset_solve_fills_slots(self):
        g = self._group(lf.optics.PRESET_NAMES[0])
        lf.solve(g)
        self.assertTrue(g["status"].value().startswith("EFL 50.0mm"))
        self.assertNotEqual(g["g0sG"].value(), -7.0)
        self.assertEqual(g["g15eG"].value(), 0.0)   # unused slot zeroed

    def test_bad_custom_keeps_previous_values(self):
        g = self._group(lf.CUSTOM, "not a lens\n")
        lf.solve(g)
        self.assertIn("Prescription error", g["status"].value())
        self.assertEqual(g["g0sG"].value(), -7.0)

    def test_untraceable_lens_is_caught(self):
        # Absurd thickness overflows the trace; must not raise into Nuke.
        g = self._group(lf.CUSTOM, "50 1e308 1.5 60 1\n-50 1e308 1.0 0 1\nSTOP 5 40\n")
        lf.solve(g)
        self.assertIn("previous solve kept", g["status"].value())
        self.assertEqual(g["g0sG"].value(), -7.0)

    def test_eff_fstop_clamped_and_passthrough(self):
        g = self._group(lf.optics.PRESET_NAMES[0], fstop=1.2)
        lf.solve(g)
        self.assertAlmostEqual(g["effFstop"].value(), 2.0, places=6)
        g = self._group(lf.optics.PRESET_NAMES[0], fstop=5.6)
        lf.solve(g)
        self.assertAlmostEqual(g["effFstop"].value(), 5.6, places=6)

    def test_ghost_count_clamped(self):
        g = self._group(lf.optics.PRESET_NAMES[0])
        g["ghostCount"].setValue(99)
        lf.solve(g)
        shown = int(re.search(r"(\d+) of", g["status"].value()).group(1))
        self.assertLessEqual(shown, lf.SLOTS)
        g = self._group(lf.optics.PRESET_NAMES[0])
        g["ghostCount"].setValue(-5)
        lf.solve(g)
        self.assertIn(" 0 of ", g["status"].value())


class KnobChangedTests(unittest.TestCase):
    def setUp(self):
        self._saved = (getattr(lf.nuke, "thisKnob", None), getattr(lf.nuke, "thisNode", None), lf.solve)
        self.calls = []
        lf.solve = lambda node: self.calls.append(node)

    def tearDown(self):
        lf.nuke.thisKnob, lf.nuke.thisNode, lf.solve = self._saved

    def _fire(self, knob, node):
        lf.nuke.thisKnob = lambda: knob
        lf.nuke.thisNode = lambda: node
        lf._on_knob_changed()

    def test_knob_changed_ignores_other_knobs_and_none(self):
        node = {"status": _Knob("")}
        self._fire(None, node)
        self.assertEqual(self.calls, [])
        mix = types.SimpleNamespace(name=lambda: "mix")
        self._fire(mix, node)
        self.assertEqual(self.calls, [])
        self._fire(types.SimpleNamespace(name=lambda: "fstop"), node)
        self.assertEqual(len(self.calls), 1)

    def test_knob_changed_reports_unexpected_error(self):
        def boom(node):
            raise TypeError("boom<")
        lf.solve = boom
        node = {"status": _Knob("")}
        self._fire(types.SimpleNamespace(name=lambda: "fstop"), node)
        self.assertIn("Solve failed", node["status"].value())
        self.assertIn("boom&lt;", node["status"].value())


class _FakeKnobBase(object):
    def __init__(self, name, *args):
        self._name = name
        self.args = args

    def name(self):
        return self._name

    def __getattr__(self, attr):          # setValue, setRange, setFlag, setTooltip, ...
        return lambda *a, **k: None


class _FakeFormat(object):
    def width(self):
        return 640

    def height(self):
        return 360


class _FakeNuke(object):
    """Just enough of the nuke module for _add_knobs: every knob class records
    its name, so tests can compare created knobs with the TCL's references."""
    INVISIBLE = NO_ANIMATION = STARTLINE = ENDLINE = 0
    TABBEGINCLOSEDGROUP = TABBEGINGROUP = TABENDGROUP = 0

    def __getattr__(self, cls):
        return _FakeKnobBase


class _FakeGroup(object):
    def __init__(self):
        self.names = []
        self.knobs = []

    def addKnob(self, k):
        self.names.append(k.name())
        self.knobs.append(k)


class ElementTests(unittest.TestCase):
    def setUp(self):
        self.tcl = lf.build_tcl()
        saved = lf.nuke
        lf.nuke = _FakeNuke()
        try:
            self.group = _FakeGroup()
            lf._add_knobs(self.group, 640, 360)
        finally:
            lf.nuke = saved

    def test_every_tcl_reference_is_a_created_knob(self):
        refs = set(re.findall(r"parent\.([A-Za-z_]\w*)", self.tcl))
        missing = sorted(refs - set(self.group.names))
        self.assertEqual(missing, [])

    def test_knob_names_unique(self):
        dupes = sorted(set(n for n in self.group.names if self.group.names.count(n) > 1))
        self.assertEqual(dupes, [])

    def test_every_element_knob_created_and_used(self):
        for eid, _l, _f, _s in fe.ELEMENTS:
            for name in fe.knob_names(eid):
                self.assertIn(name, self.group.names, name)
                self.assertIn("parent.%s" % name, self.tcl, name)

    def test_every_element_gated_by_its_switch(self):
        for eid, _l, _f, _s in fe.ELEMENTS:
            self.assertIn("!parent.%sOn" % eid, self.tcl, eid)              # expensive nodes disabled
            self.assertIn("parent.%sOn*" % eid, self.tcl, eid)              # gain multiplied by On
            self.assertIn("$el_%s" % eid, self.tcl, eid)                    # summed into the flare

    def test_existing_parts_have_switches(self):
        for knob in ("ghostsOn", "starOn", "glareOn"):
            self.assertIn(knob, self.group.names)
            self.assertIn("!parent.%s" % knob, self.tcl)
            self.assertIn("parent.%s*" % knob, self.tcl)

    def test_elements_default_off(self):
        by_name = dict((k.name(), k) for k in self.group.knobs)
        for eid, _l, _f, _s in fe.ELEMENTS:
            knob = by_name[eid + "On"]
            self.assertTrue(len(knob.args) > 0 and knob.args[-1] is False, eid)

    def test_every_kernel_has_centre_floor(self):
        names = ["streakKernel", "spikeBallKernel", "shimmerKernel", "sparkleKernel", "glintKernel",
                 "irisKernel", "causticKernel"]
        names += ["multiIrisKernel%d" % i for i in range(fe.MULTI_IRIS_SLOTS)]
        names += ["ringsKernel%d" % i for i in range(fe.RING_SLOTS)]
        for name in names:
            end = self.tcl.index("name %s\n" % name)
            block = self.tcl[self.tcl.rindex("Expression {", 0, end):end]
            self.assertIn(fe.CENTRE_FLOOR, block, name)

    def test_expensive_element_nodes_have_disable(self):
        part = fe.elements_tcl()
        blocks = re.findall(r"(?:Convolve2|TransformMasked|Blur|Dilate) \{.*?\n\}", part, re.S)
        self.assertGreater(len(blocks), 20)
        for b in blocks:
            self.assertIn("\n disable ", b, b)

    def test_hotspot_only_runs_when_used(self):
        end = self.tcl.index("name hotSmooth")
        block = self.tcl[self.tcl.rindex("Blur {", 0, end):end]
        for eid, _l, _f, _s in fe.ELEMENTS:
            self.assertIn("(parent.%sOn&&parent.%sSource==1)" % (eid, eid), block)


if __name__ == "__main__":
    unittest.main()

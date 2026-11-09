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
            self.assertIn("{{parent.ghostCount<=%d}}" % n, self.tcl)
            self.assertIn("(parent.ghostCount>%d)*parent.ghostIntensity" % n, self.tcl)

    def test_gain_nodes_never_disabled(self):
        # A disabled gain node would pass its unscaled input straight into the sum.
        for name in ["starGain", "glareGain"] + ["g%dGain" % n for n in range(lf.SLOTS)]:
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

    def test_spike_gate_has_no_half_line_filter(self):
        self.assertNotIn("cos(ang-", self.tcl)

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


if __name__ == "__main__":
    unittest.main()

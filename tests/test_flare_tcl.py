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
            self.assertIn("name g%dMono" % n, self.tcl)
            self.assertIn("{{parent.ghostCount<=%d||!parent.ghostsOn}}" % n, self.tcl)
            self.assertIn("(parent.ghostCount>%d)*parent.ghostIntensity" % n, self.tcl)

    def test_gain_nodes_never_disabled(self):
        # A disabled gain node would pass its unscaled input straight into the sum.
        element_gains = ["%sGain" % eid for eid, _l, _f, _s in fe.ELEMENTS if eid not in ("multiIris", "rings")]
        element_gains += ["multiIris%dGain" % i for i in range(fe.MULTI_IRIS_SLOTS)]
        element_gains += ["rings%dGain" % i for i in range(fe.RING_SLOTS)]
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
        names += ["multiIris%dKernel" % i for i in range(fe.MULTI_IRIS_SLOTS)]
        names += ["rings%dKernel" % i for i in range(fe.RING_SLOTS)]
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

    def test_coloured_elements_have_both_branches(self):
        # Tint = one alpha Convolve2, Spectrum/Ramp = one per channel; a Switch on Colour Mode picks.
        for prefix in list(fe.COLOURED) + ["ghosts"]:
            self.assertIn("which {{parent.%sColorMode>0}}" % prefix, self.tcl, prefix)
            self.assertIn("parent.%sColorMode>0}}" % prefix, self.tcl, prefix)     # mono branch off in colour modes
            self.assertIn("parent.%sColorMode==0}}" % prefix, self.tcl, prefix)    # colour branch off in Tint
        for tag in ["iris", "caustic", "ringHaloHalo"] + ["g%d" % n for n in range(lf.SLOTS)]:
            for ch in ("red", "green", "blue"):
                self.assertIn("name %s_%s" % (tag, ch), self.tcl, tag)

    def test_overscan_pad_and_crop(self):
        self.assertIn("name overscanPad", self.tcl)
        self.assertIn("name overscanGrow", self.tcl)
        self.assertIn("name overscanCrop", self.tcl)
        self.assertLess(self.tcl.index("name overscanPad"), self.tcl.index("name g0Aperture"))
        self.assertGreater(self.tcl.index("name overscanCrop"), self.tcl.index("set el_wash"))
        self.assertLess(self.tcl.index("name overscanCrop"), self.tcl.index("name flareUp"))

    def test_optical_centre_always_padded(self):
        # Positions scale by the real working/plate ratio (flareDown/highlights), then add the pad.
        uses = re.findall(r"parent\.opticalCenter\.[xy]\*flareDown\.(?:width|height)/highlights\.(?:width|height)"
                          r"(\+floor)?", self.tcl)
        self.assertTrue(uses)
        self.assertTrue(all(uses), "an opticalCenter use lacks the overscan pad")

    def test_every_element_has_offset(self):
        for eid, _l, _f, _s in fe.ELEMENTS:
            self.assertIn("parent.%sOffset.x" % eid, self.tcl, eid)
        for prefix in ("ghosts", "star"):
            self.assertIn("parent.%sOffset.x" % prefix, self.tcl, prefix)

    def test_offset_only_applied_when_use_offset_is_on(self):
        for prefix in fe.offset_prefixes():
            self.assertIn("parent.%sOffset.x*pow(0.5,parent.flareRes)*parent.%sOffsetOn" % (prefix, prefix),
                          self.tcl, prefix)
            self.assertIn("parent.%sOffset.y*pow(0.5,parent.flareRes)*parent.%sOffsetOn" % (prefix, prefix),
                          self.tcl, prefix)
            names = self.group.names
            self.assertIn(prefix + "OffsetOn", names, prefix)
            self.assertEqual(names.index(prefix + "OffsetOn") + 1, names.index(prefix + "Offset"), prefix)

    def test_use_offset_defaults_off(self):
        for prefix in fe.offset_prefixes():
            knob = self.group.knobs[self.group.names.index(prefix + "OffsetOn")]
            self.assertIs(knob.args[-1], False, prefix)

    def test_optical_centre_on_elements_tab(self):
        names = self.group.names
        self.assertGreater(names.index("opticalCenter"), names.index("tabElements"))
        self.assertLess(names.index("overscan"), names.index("tabGhosts"))

    def test_hotspot_only_runs_when_used(self):
        end = self.tcl.index("name hotSmooth")
        block = self.tcl[self.tcl.rindex("Blur {", 0, end):end]
        for eid, _l, _f, _s in fe.ELEMENTS:
            self.assertIn("(parent.%sOn&&parent.%sSource==1)" % (eid, eid), block)

    def _block(self, name, kind="Expression"):
        end = self.tcl.index("name %s\n" % name)
        return self.tcl[self.tcl.rindex("%s {" % kind, 0, end):end]

    def _geo_span(self):
        start = self.tcl.index("NoOp {\n name %s\n" % fe.GEO)
        return start, self.tcl.index("\n}", start)

    def test_coloured_kernels_floor_every_channel(self):
        # Convolve2 normalizes each channel by its own kernel sum: r, g, b and
        # alpha all need the floor (a pure-red ramp has a zero-sum green kernel).
        names = ["irisKernel", "causticKernel", "ringHaloKernel"]
        names += ["multiIris%dKernel" % i for i in range(fe.MULTI_IRIS_SLOTS)]
        names += ["rings%dKernel" % i for i in range(fe.RING_SLOTS)]
        names += ["g%dAperture" % n for n in range(lf.SLOTS)]
        for name in names:
            block = self._block(name)
            for i in range(4):
                line = re.search(r"\n expr%d \{.*\}\n" % i, block).group(0)
                self.assertIn(fe.CENTRE_FLOOR, line, "%s expr%d" % (name, i))
        for name in ("streakKernel", "glintKernel"):           # mono: alpha only
            self.assertEqual(self._block(name).count(fe.CENTRE_FLOOR), 1, name)

    def test_colour_clamped_non_negative(self):
        self.assertTrue(fe.colour_expr("iris", "0.5", "1", "r").startswith("max(0,"))

    def test_no_frame_outside_flare_geo(self):
        # Per-frame values live once on the flareGeo NoOp, not in per-pixel expressions.
        start, end = self._geo_span()
        outside = [m.start() for m in re.finditer(r"\bframe\b", self.tcl) if not start <= m.start() < end]
        self.assertEqual(outside, [])
        geo = self.tcl[start:end]
        for prefix in list(fe.COLOURED) + ["ghosts"]:
            self.assertIn(" t_%s {{frame*parent.%sNoiseSpeed}}" % (prefix, prefix), geo)
        self.assertIn(" t_shimmer {{frame*parent.shimmerSpeed}}", geo)
        self.assertIn(" t_sparkle {{frame*parent.sparkleSpeed}}", geo)

    def test_flare_geo_refs_are_defined(self):
        start, end = self._geo_span()
        defined = set(re.findall(r"addUserKnob \{7 (\w+)\}", self.tcl[start:end]))
        used = set(re.findall(r"%s\.(\w+)" % fe.GEO, self.tcl))
        self.assertTrue(used)
        self.assertEqual(sorted(used - defined), [])
        self.assertLess(self.tcl.index("name overscanGrow"), start)
        self.assertLess(start, self.tcl.index("name ghostsLight"))

    def test_balance_per_shape_unfloored(self):
        start, end = self._geo_span()
        geo = self.tcl[start:end]
        for prefix, shape in fe.BALANCE_SHAPES:
            for ch, expr in zip("rgb", fe.colour_balance(prefix, shape)):
                self.assertIn(" bal_%s_%s {{%s}}" % (prefix, ch, expr), geo)
                self.assertTrue(expr.startswith("(parent.%sColorMode==0?1:(" % prefix), expr[:60])
        filled = fe.colour_balance("iris", "filled")[0]
        ring = fe.colour_balance("rings", "ring")[0]
        weights = dict(fe.balance_weight_knobs("iris", "filled"))
        self.assertEqual(len(weights), fe.FILLED_SAMPLES + 2)
        for name, expr in weights.items():
            self.assertIn(" %s {{%s}}" % (name, expr), geo)
        self.assertTrue(weights["w_iris_core"].startswith("pow(min(1-clamp(parent.irisColorWidth,0.05,1),"))
        self.assertIn("acos(", weights["w_iris_7"])                                   # aperture polygon coverage
        self.assertIn("parent.causticSharpness", dict(fe.balance_weight_knobs("caustic", "filled"))["w_caustic_3"])
        self.assertTrue(filled.endswith(")/%s.w_iris_sum))" % fe.GEO))
        self.assertIn("%s.w_iris_core+" % fe.GEO, filled)                           # white core, colour 1
        self.assertEqual(filled.count("max(0,(parent.irisColorMode==1?"), fe.FILLED_SAMPLES)
        self.assertEqual(ring.count("max(0,(parent.ringsColorMode==1?"), fe.RING_SAMPLES)
        # Old bug: the balance was floored, so a channel the colour lacks
        # still got a faint centre dot. Only ramp position spans are floored.
        self.assertEqual(re.findall(r"max\(0\.0001,[^,()]*Ramp\d\.[rgb]", filled + ring), [])
        for tag in ["iris", "caustic"] + ["multiIris%d" % i for i in range(fe.MULTI_IRIS_SLOTS)]:
            self.assertIn("%s.bal_" % fe.GEO, self._block(tag + "Gain"), tag)

    def test_ring_halo_balance_only_in_light_mode(self):
        block = self._block("ringHaloGain")
        for b in fe.balance_refs("ringHalo"):
            self.assertIn("(parent.ringHaloCentre==1?%s:1)" % b, block)

    def test_even_fields_use_fixed_reference(self):
        self.assertNotIn("ArcFalloff", self._block("ringHaloOrbital", "MergeExpression"))
        self.assertNotIn("washSpread", self._block("washMix", "MergeExpression"))
        self.assertIn("/(%g*" % fe.EVEN_REF_PX, self._block("ringHaloOrbital", "MergeExpression"))
        self.assertIn("/(%g*" % fe.WASH_REF_PX, self._block("washMix", "MergeExpression"))
        self.assertIn("parent.ringHaloArc>=1}}", self._block("ringHaloEven", "Blur"))
        self.assertIn("!parent.ringHaloOn||", self._block("ringHaloEven", "Blur"))
        self.assertIn("{{!parent.washOn||parent.washBias>=1}}", self._block("washEven", "Blur"))
        self.assertIn("{{!parent.washOn||parent.washBias<=0}}", self._block("washNear", "Blur"))

    def test_noise_clamped_and_per_slot(self):
        for prefix in list(fe.COLOURED) + ["ghosts"]:
            self.assertIn("clamp(parent.%sNoise,0,1)" % prefix, self.tcl, prefix)
            self.assertNotIn("(1-parent.%sNoise+" % prefix, self.tcl, prefix)
        self.assertIn("%s*0.1+7.31)" % fe.time_ref("rings"), self._block("rings1Kernel"))
        self.assertIn("%s*0.1+%g)" % (fe.time_ref("multiIris"), 3 * 7.31), self._block("multiIris3Kernel"))
        self.assertIn("%s*0.1+%g)" % (fe.time_ref("ghosts"), 2 * 7.31), self._block("g2Aperture"))
        self.assertIn("%s*0.1)" % fe.time_ref("ghosts"), self._block("g0Aperture"))

    def test_output_bbox_cropped_to_frame(self):
        self.assertIn("Crop {\n box {{0} {0} {highlights.width} {highlights.height}}\n crop false\n name flareCrop\n}",
                      self.tcl)
        # Down and up are both to-box distorts, so the up-scale exactly inverts
        # the down-scale even when the working size rounds (858 x 0.25).
        for name in ("flareDown", "flareUp"):
            end = self.tcl.index("name %s\n" % name)
            block = self.tcl[self.tcl.rindex("Reformat {", 0, end):end]
            self.assertIn(' type "to box"\n', block, name)
            self.assertIn(" resize distort\n", block, name)
        self.assertIn("box_width {{highlights.width}}", self.tcl)
        self.assertIn("box_height {{highlights.height}}", self.tcl)
        self.assertLess(self.tcl.index("name flareUp"), self.tcl.index("name flareCrop"))
        self.assertLess(self.tcl.index("name flareCrop"), self.tcl.index("name combine"))

    def test_ghosts_offset_applied_once(self):
        self.assertEqual(self.tcl.count("parent.ghostsOffset.x"), 1)
        self.assertGreater(self.tcl.index("name ghostsOffsetT"), self.tcl.index("name g%dGain" % (lf.SLOTS - 1)))
        self.assertIn("push $ghosts\n", self.tcl)
        for n in range(lf.SLOTS):
            self.assertNotIn("push $g%d\npush $acc" % n, self.tcl)

    def test_tooltips(self):
        mode_tip = [t for t in fe.COLOUR_EXTRA if t[0] == "ColorMode"][0][-1]
        self.assertIn("Spectrum/Ramp cost 3x the render time of Tint for that element.", mode_tip)
        for eid, suffix in (("ringHalo", "Arc"), ("wash", "Bias")):
            tip = [t for t in fe.EXTRA[eid] if t[0] == suffix][0][-1]
            self.assertIn("fixed reference size", tip, eid)


if __name__ == "__main__":
    unittest.main()

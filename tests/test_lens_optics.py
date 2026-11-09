# Run from the folder that holds sid_lens_optics.py:
#     python -m unittest discover -s tests -v
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sid_lens_optics as o  # noqa: E402


class PresetTests(unittest.TestCase):
    def test_focal_length_within_2_percent(self):
        for name in o.PRESET_NAMES:
            with self.subTest(name=name):
                efl = o.effective_focal_length(o.preset(name))
                self.assertLess(abs(efl - o.PRESET_FOCAL[name]) / o.PRESET_FOCAL[name], 0.02)

    def test_double_gauss_base_matches_published_example(self):
        # Textbook "Double Gauss 28 degree field": EFL ~99.5mm, BFD ~57.3mm.
        base = o._build(o._DG_BASE, 1.0, 3.0)
        self.assertAlmostEqual(o.effective_focal_length(base), 99.5, delta=0.5)
        bfd = o.sensor_z(base) - sum(s.thickness for s in base[:-1])
        self.assertAlmostEqual(bfd, 57.3, delta=0.5)

    def test_pair_count_is_n_choose_2(self):
        for name in o.PRESET_NAMES:
            with self.subTest(name=name):
                lens = o.preset(name)
                n = sum(1 for s in lens if not s.is_stop)
                self.assertEqual(len(o.reflecting_pairs(lens)), n * (n - 1) // 2)

    def test_prescription_roundtrip(self):
        lens = o.preset(o.PRESET_NAMES[2])
        again = o.parse_prescription(o.format_prescription(lens))
        self.assertAlmostEqual(o.effective_focal_length(again), o.effective_focal_length(lens), delta=0.01)


class PhysicsTests(unittest.TestCase):
    def test_coating_reduces_reflectance_at_green(self):
        self.assertLess(o.coated_reflectance(1.0, 1.62, 0.55), o.fresnel_reflectance(1.0, 1.62))

    def test_coating_is_coloured(self):
        r, g, b = (o.coated_reflectance(1.0, 1.62, w) for w in o.WAVELENGTHS_UM)
        self.assertLess(g, r)   # minimum at the 550nm design wavelength
        self.assertLess(g, b)

    def test_dispersion_index_order_and_n_d(self):
        n = [o.index_at(1.6204, 60.32, w) for w in o.WAVELENGTHS_UM]
        self.assertTrue(n[0] < n[1] < n[2])
        self.assertAlmostEqual(o.index_at(1.6204, 60.32, 0.5876), 1.6204, places=9)
        self.assertEqual(o.index_at(1.0, 0.0, 0.45), 1.0)

    def test_starburst_spike_rule(self):
        for blades, spikes in ((5, 10), (6, 6), (7, 14), (8, 8)):
            self.assertEqual(o.starburst_spikes(blades), spikes)


class SolveTests(unittest.TestCase):
    def setUp(self):
        self.dg = o.preset(o.PRESET_NAMES[0])

    def test_channel_scales_differ_with_dispersion(self):
        ghosts, _ = o.solve(self.dg, 2.8, True, 8)
        self.assertTrue(any(abs(g.scale[0] - g.scale[1]) > 1e-4 or abs(g.scale[2] - g.scale[1]) > 1e-4
                            for g in ghosts))

    def test_ranks_and_limits(self):
        ghosts, info = o.solve(self.dg, 2.8, True, 5)
        self.assertEqual(len(ghosts), 5)
        peaks = [g.peak for g in ghosts]
        self.assertEqual(peaks, sorted(peaks, reverse=True))
        self.assertEqual(info["pairs"], 45)
        for g in ghosts:
            self.assertTrue(o.MIN_ABS_SCALE <= abs(g.scale[1]) <= o.MAX_ABS_SCALE)
            self.assertGreater(g.radius_mm, 0)
            self.assertTrue(all(c > 0 for c in g.rgb))

    def test_count_capped_at_slots(self):
        ghosts, _ = o.solve(o.preset(o.PRESET_NAMES[1]), 2.8, True, 99)
        self.assertLessEqual(len(ghosts), o.MAX_GHOST_SLOTS)

    def test_fnumber_clamped_to_lens_maximum(self):
        _g, info = o.solve(self.dg, 1.0, True, 4)
        self.assertTrue(info["clamped"])
        self.assertAlmostEqual(info["fnumber"], 2.0, places=6)

    def test_stopping_down_shrinks_ghosts(self):
        wide = {g.pair: g.radius_mm for g in o.solve(self.dg, 2.0, True, 16)[0]}
        narrow = {g.pair: g.radius_mm for g in o.solve(self.dg, 8.0, True, 16)[0]}
        common = set(wide) & set(narrow)
        self.assertTrue(common)
        for p in common:
            self.assertLess(narrow[p], wide[p])

    def test_coatings_off_brightens_ghosts(self):
        on = {g.pair: g.rgb[1] for g in o.solve(self.dg, 2.8, True, 16)[0]}
        off = {g.pair: g.rgb[1] for g in o.solve(self.dg, 2.8, False, 16)[0]}
        common = set(on) & set(off)
        self.assertTrue(common)
        for p in common:
            self.assertGreater(off[p], on[p])


class ParserTests(unittest.TestCase):
    def test_bad_prescription_reports_line(self):
        cases = (
            ("50 5 1.5 60 1\n-50 2 1.0 0 1\n30 3 1.5 60 x\n-30 2 1.0 0 1\nSTOP 5 40\n", 3),  # coated not a number
            ("50 5 1.5 60 1\n-50 40 1.0 0 1\n", 2),                  # no STOP (last line)
            ("50 5 1.5 60\n-50 2 1.0 0 1\nSTOP 5 40\n", 1),           # 4 values
            ("50 5 1.5 0 1\n-50 2 1.0 0 1\nSTOP 5 40\n", 1),          # glass without V_d
            ("50 5 1.5 60 1\nnan 2 1.0 0 1\nSTOP 5 40\n", 2),         # nan value
            ("50 -5 1.5 60 1\n-50 2 1.0 0 1\nSTOP 5 40\n", 1),        # negative thickness
            ("50 5 1.5 60 1\nSTOP 5 5\n-50 40 1.0 0 1\n", 2),         # STOP in glass
            ("0 5 1.5 60 1\n0 2 1.0 0 1\nSTOP 5 40\n", 3),            # flat plate, no power
            ("-50 5 1.5 60 1\n50 2 1.0 0 1\nSTOP 5 40\n", 3),         # diverging lens
        )
        for text, line in cases:
            with self.subTest(text=text):
                with self.assertRaises(o.PrescriptionError) as err:
                    o.parse_prescription(text)
                self.assertEqual(err.exception.line, line)

    def test_comments_and_blank_lines_ignored(self):
        text = "# demo\n\n50 5 1.5 60 1\n-50 2 1.0 0 1\nSTOP 5 40\n"
        self.assertEqual(len(o.parse_prescription(text)), 3)

    def test_presets_roundtrip_through_parser(self):
        for name in o.PRESET_NAMES:
            with self.subTest(name=name):
                o.parse_prescription(o.format_prescription(o.preset(name)))


class CountTests(unittest.TestCase):
    def test_nonpositive_count_returns_empty(self):
        dg = o.preset(o.PRESET_NAMES[0])
        self.assertEqual(o.solve(dg, 2.8, True, 0)[0], [])
        self.assertEqual(o.solve(dg, 2.8, True, -3)[0], [])


if __name__ == "__main__":
    unittest.main()

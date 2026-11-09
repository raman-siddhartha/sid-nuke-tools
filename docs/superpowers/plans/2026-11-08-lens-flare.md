# Sid Lens Flare Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an image-driven, physically traced lens flare node ("Nodes > Sid > Lens Flare") to the Sid Nuke Tools.

**Architecture:** `sid_lens_optics.py` is plain Python: it parses a lens prescription, traces every pair of reflecting surfaces with paraxial ray-transfer maths at three wavelengths, and ranks the ghosts. `sid_lens_flare.py` builds the whole node graph in ONE `nuke.tcl()` call (16 ghost slots, starburst, glare, output) and writes the solved numbers into hidden knobs on the Group. Internal nodes follow them via `parent.*` expressions, so Python never touches nodes inside the Group (Nuke Non-Commercial 10-node limit).

**Tech Stack:** Python 3.11 (Nuke 17.1's interpreter), Nuke TCL, stdlib `unittest`. No third-party packages.

**Spec:** `F:\Python\Nuke\docs\superpowers\specs\2026-11-08-lens-flare-design.md`

**Every file below was prototyped and verified in Nuke 17.1 Non-Commercial before this plan was written** (34 unit tests pass, 25/25 Nuke checks pass). It was then hardened by per-task spec and code-quality reviews; the code below is the reviewed final version. Type it exactly.

---

## Ground rules (read before starting)

1. Work folder is `F:\Python\Nuke`. It is NOT a git repo; git only happens in Task 5, in the sid-nuke-tools clone.
2. **NC limit:** production code never calls `nuke.toNode`, `nuke.allNodes`, `group.node()`, or iterates nodes inside the Group.
3. **TCL `{{ }}` expressions must contain no spaces.** Nuke keeps only the first token. `tests/test_flare_tcl.py` enforces this.
4. **Never disable a gain node.** A disabled node passes its input straight through; disable the expensive upstream node instead.
5. **Temp variable names must not be `r g b a x y z`** (Nuke reserves them for the input pixel).
6. Nuke runs use non-commercial terminal mode: `"C:/Program Files/Nuke17.1v3/Nuke17.1.exe" --nc -t <script>`. No licence needed.
7. Shell is Git Bash; paths use `/f/Python/Nuke`.

## File map

| File | Create/Modify | Responsibility |
|---|---|---|
| `F:\Python\Nuke\sid_lens_optics.py` | Create | Prescriptions, presets, paraxial tracing, coatings, dispersion, ranking. No `nuke` import. |
| `F:\Python\Nuke\sid_lens_flare.py` | Create | TCL graph generator, knobs, solve callback, `make_lens_flare()`, `install_menu()`. |
| `F:\Python\Nuke\tests\test_lens_optics.py` | Create | 18 unit tests for the optics. |
| `F:\Python\Nuke\tests\test_flare_tcl.py` | Create | 9 TCL lint tests, 5 solve tests, 2 knobChanged tests (stub `nuke`). |
| `F:\Python\Nuke\tests\nuke_flare_check.py` | Create | 25 integration checks run inside Nuke NC. |
| `F:\Python\Nuke\menu.py`, `C:\Users\raman\.nuke\menu.py` | Modify | Register Lens Flare. |
| `F:\Python\Nuke\README.txt` | Modify | Document the tool. |

---

### Task 1: Optics module

**Files:**
- Create: `F:\Python\Nuke\tests\test_lens_optics.py`
- Create: `F:\Python\Nuke\sid_lens_optics.py`

- [ ] **Step 1: Write the failing tests**

Create `F:\Python\Nuke\tests\test_lens_optics.py`:

```python
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
```

- [ ] **Step 2: Run the tests to make sure they fail**

Run: `cd /f/Python/Nuke && python -m unittest tests.test_lens_optics -v`
Expected: ERROR, `ModuleNotFoundError: No module named 'sid_lens_optics'`

- [ ] **Step 3: Write the optics module**

Create `F:\Python\Nuke\sid_lens_optics.py`:

```python
# Sid Lens Optics -- pure-Python paraxial lens model for the Sid Lens Flare.
#
# No `nuke` import: everything here is plain maths so it can be unit tested
# outside Nuke. sid_lens_flare.py calls solve() and writes the result into
# hidden knobs on the Group.
#
# Model
#   * Lens = list of refracting surfaces + one aperture stop, read from a
#     text prescription (see parse_prescription).
#   * Paraxial ray trace with signed indices: a reflection is a "refraction"
#     into index -n, and distances travelled backwards are negative. This is
#     the standard unfolded formalism, so one trace routine handles both
#     forward and reflected passes.
#   * A ghost is light that reflects off surface j, back off surface i (i<j),
#     then travels forward to the sensor. For each ghost and each of three
#     wavelengths we get its scale about the optical centre (negative =
#     flipped), the radius of the aperture's image on the sensor, and its
#     colour from Fresnel / single-layer coating reflectance.
#
# Strict ASCII.

import math

WAVELENGTHS_UM = (0.650, 0.550, 0.450)   # R, G, B
_LAMBDA_D, _LAMBDA_F, _LAMBDA_C = 0.5876, 0.4861, 0.6563
COATING_INDEX = 1.38                     # MgF2
COATING_DESIGN_UM = 0.550                # quarter-wave at green
MAX_GHOST_SLOTS = 16
MIN_ABS_SCALE = 0.02     # below this a ghost squeezes the whole frame to a point
MAX_ABS_SCALE = 50.0


class PrescriptionError(ValueError):
    """Bad custom prescription. `line` is the 1-based line number."""

    def __init__(self, line, message):
        ValueError.__init__(self, "line %d: %s" % (line, message))
        self.line = line


class Surface(object):
    __slots__ = ("radius", "thickness", "n_d", "v_d", "coated", "is_stop", "semi")

    def __init__(self, radius, thickness, n_d, v_d, coated, is_stop=False, semi=0.0):
        self.radius = radius
        self.thickness = thickness
        self.n_d = n_d
        self.v_d = v_d
        self.coated = coated
        self.is_stop = is_stop
        self.semi = semi


def parse_prescription(text):
    """One surface per row: `radius thickness n_d V_d coated`.
    radius 0 = flat. n_d / V_d describe the medium AFTER the surface
    (air = `1.0 0`). coated is 0 or 1. Exactly one row
    `STOP semi_diameter thickness` marks the aperture stop (in air).
    Blank lines and lines starting with # are ignored."""
    surfaces = []
    stops = 0
    last_line = 1
    prev_n = 1.0
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        last_line = lineno
        parts = line.split()
        if parts[0].upper() == "STOP":
            if len(parts) != 3:
                raise PrescriptionError(lineno, "STOP needs: STOP semi_diameter thickness")
            try:
                semi, thick = float(parts[1]), float(parts[2])
            except ValueError:
                raise PrescriptionError(lineno, "STOP values must be numbers")
            if not (math.isfinite(semi) and math.isfinite(thick)):
                raise PrescriptionError(lineno, "values must be finite numbers")
            if semi <= 0:
                raise PrescriptionError(lineno, "STOP semi_diameter must be > 0")
            if prev_n != 1.0:
                raise PrescriptionError(lineno, "STOP must be in air (previous row's n_d must be 1.0)")
            surfaces.append(Surface(0.0, thick, 1.0, 0.0, False, True, semi))
            stops += 1
            continue
        if len(parts) != 5:
            raise PrescriptionError(lineno, "expected 5 values: radius thickness n_d V_d coated")
        try:
            r, t, n, v = (float(p) for p in parts[:4])
            coated = int(parts[4])
        except ValueError:
            raise PrescriptionError(lineno, "values must be numbers")
        if not all(math.isfinite(x) for x in (r, t, n, v)):
            raise PrescriptionError(lineno, "values must be finite numbers")
        if t < 0:
            raise PrescriptionError(lineno, "thickness must be >= 0")
        if coated not in (0, 1):
            raise PrescriptionError(lineno, "coated must be 0 or 1")
        if n < 1.0:
            raise PrescriptionError(lineno, "n_d must be >= 1.0")
        if n > 1.0 and v <= 0:
            raise PrescriptionError(lineno, "glass needs V_d > 0")
        surfaces.append(Surface(r, t, n, v, bool(coated)))
        prev_n = n
    if stops != 1:
        raise PrescriptionError(last_line, "exactly one STOP row required (found %d)" % stops)
    if sum(1 for s in surfaces if not s.is_stop) < 2:
        raise PrescriptionError(last_line, "need at least two refracting surfaces")
    _validate(surfaces, last_line)
    return surfaces


def _validate(surfaces, line):
    """Whole-lens checks (d-line); raises PrescriptionError at `line`."""
    lens = _Lens(surfaces, _LAMBDA_D)
    _y, u, _z, _n = lens.trace(1.0, 0.0, lens.forward_path())
    if abs(u) < 1e-12:
        raise PrescriptionError(line, "lens has no optical power")
    if -1.0 / u <= 0:
        raise PrescriptionError(line, "diverging lens (negative focal length) not supported")
    a, _b = lens.to_stop_coeffs()
    if abs(a) < 1e-12:
        raise PrescriptionError(line, "aperture stop sits at an image plane")


def index_at(n_d, v_d, wavelength_um):
    """Two-term Cauchy fit through n_d at 587.6nm with the Abbe-number
    dispersion nF - nC = (n_d - 1) / V_d. V_d == 0 -> non-dispersive."""
    if v_d <= 0 or n_d <= 1.0:
        return n_d
    b = ((n_d - 1.0) / v_d) / (1.0 / _LAMBDA_F ** 2 - 1.0 / _LAMBDA_C ** 2)
    a = n_d - b / _LAMBDA_D ** 2
    return a + b / wavelength_um ** 2


def fresnel_reflectance(n1, n2):
    return ((n1 - n2) / (n1 + n2)) ** 2


def coated_reflectance(n1, n2, wavelength_um):
    """Normal-incidence reflectance of a single quarter-wave MgF2 layer
    (designed at 550nm) between media n1 and n2."""
    nf = COATING_INDEX
    r1 = (n1 - nf) / (n1 + nf)
    r2 = (nf - n2) / (nf + n2)
    delta = math.pi * COATING_DESIGN_UM / wavelength_um   # 4*pi*nf*d/lambda, d = lambda0/(4 nf)
    c = math.cos(delta)
    return (r1 * r1 + r2 * r2 + 2 * r1 * r2 * c) / (1 + r1 * r1 * r2 * r2 + 2 * r1 * r2 * c)


class _Lens(object):
    """Surfaces resolved at one wavelength: z positions, curvatures and the
    index on each side of every surface."""

    def __init__(self, surfaces, wavelength_um):
        self.surfaces = surfaces
        self.z = []
        self.c = []
        self.n_after = []
        z = 0.0
        for s in surfaces:
            self.z.append(z)
            self.c.append(0.0 if s.radius == 0 else 1.0 / s.radius)
            self.n_after.append(index_at(s.n_d, s.v_d, wavelength_um))
            z += s.thickness
        self.n_before = [1.0] + self.n_after[:-1]
        self.stop = next(k for k, s in enumerate(surfaces) if s.is_stop)

    def trace(self, y, u, path):
        """Paraxial trace. `path` is a list of (surface index, kind) with kind
        'T' (transmit) or 'R' (reflect). Starts at the first surface's z in
        object space (index 1, travelling +z). Returns (y, u, z, n_signed)."""
        z = self.z[0]
        n = 1.0
        for k, kind in path:
            y = y + u * (self.z[k] - z)
            z = self.z[k]
            direction = 1.0 if n > 0 else -1.0
            if kind == "R":
                n2 = -n
            else:
                n2 = direction * (self.n_after[k] if direction > 0 else self.n_before[k])
            u = (n * u - y * self.c[k] * (n2 - n)) / n2
            n = n2
        return y, u, z, n

    def forward_path(self):
        return [(k, "T") for k in range(len(self.surfaces))]

    def ghost_path(self, i, j):
        last = len(self.surfaces)
        return ([(k, "T") for k in range(0, j)] + [(j, "R")] +
                [(k, "T") for k in range(j - 1, i, -1)] + [(i, "R")] +
                [(k, "T") for k in range(i + 1, last)])

    def to_stop_coeffs(self):
        """Ray height at the stop is a*y0 + b*u0 for an object-space ray
        (y0, u0) given at the first surface."""
        path = [(k, "T") for k in range(self.stop)]
        ya, ua, za, _ = self.trace(1.0, 0.0, path)
        ya = ya + ua * (self.z[self.stop] - za)
        yb, ub, zb, _ = self.trace(0.0, 1.0, path)
        yb = yb + ub * (self.z[self.stop] - zb)
        return ya, yb


def effective_focal_length(surfaces, wavelength_um=_LAMBDA_D):
    """Paraxial effective focal length in mm at the given wavelength (default d-line)."""
    lens = _Lens(surfaces, wavelength_um)
    _y, u, _z, _n = lens.trace(1.0, 0.0, lens.forward_path())
    return -1.0 / u


def max_aperture_fnumber(surfaces):
    """Smallest achievable f-number, i.e. the widest aperture the STOP allows."""
    lens = _Lens(surfaces, _LAMBDA_D)
    a, _b = lens.to_stop_coeffs()
    entrance_radius = surfaces[lens.stop].semi / abs(a)
    return effective_focal_length(surfaces) / (2.0 * entrance_radius)


def sensor_z(surfaces):
    """Paraxial focus for an object at infinity, at green."""
    lens = _Lens(surfaces, WAVELENGTHS_UM[1])
    y, u, z, _n = lens.trace(1.0, 0.0, lens.forward_path())
    return z - y / u


def reflecting_pairs(surfaces):
    idx = [k for k, s in enumerate(surfaces) if not s.is_stop]
    return [(idx[a], idx[b]) for a in range(len(idx)) for b in range(a + 1, len(idx))]


def surface_reflectance(lens, k, wavelength_um, coatings):
    n1, n2 = lens.n_before[k], lens.n_after[k]
    if coatings and lens.surfaces[k].coated:
        return coated_reflectance(n1, n2, wavelength_um)
    return fresnel_reflectance(n1, n2)


class Ghost(object):
    __slots__ = ("pair", "scale", "radius_mm", "rgb", "peak")

    def __init__(self, pair, scale, radius_mm, rgb, peak):
        self.pair = pair            # (i, j) surface indices
        self.scale = scale          # (sR, sG, sB), signed
        self.radius_mm = radius_mm  # aperture image radius on sensor, mm (green)
        self.rgb = rgb              # render multiplier per channel = R_i*R_j / sG^2
        self.peak = peak            # ranking value: peak irradiance at green


def solve(surfaces, fnumber, coatings=True, count=8):
    """Trace every reflecting surface pair, rank by peak brightness and
    return (ghosts[:count], info). fnumber is clamped to the lens maximum;
    info has 'efl', 'fnumber', 'clamped', 'max_fnumber', 'pairs'."""
    efl = effective_focal_length(surfaces)
    max_n = max_aperture_fnumber(surfaces)
    clamped = fnumber < max_n
    fnumber = max(fnumber, max_n)
    entrance_radius = efl / (2.0 * fnumber)
    z_sensor = sensor_z(surfaces)

    lenses = [_Lens(surfaces, w) for w in WAVELENGTHS_UM]
    a, b = lenses[1].to_stop_coeffs()
    # Chief ray for unit field angle: u0 = 1, height chosen to cross the stop
    # centre. Marginal ray: parallel to axis at the entrance-pupil edge.
    chief = (-b / a, 1.0)
    marginal = (entrance_radius, 0.0)
    primary_height = efl   # image height for unit field angle (green)

    pairs = reflecting_pairs(surfaces)
    ghosts = []
    for (i, j) in pairs:
        scales = []
        for lens in lenses:
            path = lens.ghost_path(i, j)
            y, u, z, _n = lens.trace(chief[0], chief[1], path)
            scales.append((y + u * (z_sensor - z)) / primary_height)
        lens_g = lenses[1]
        y, u, z, _n = lens_g.trace(marginal[0], marginal[1], lens_g.ghost_path(i, j))
        radius = abs(y + u * (z_sensor - z))
        s_g = scales[1]
        if not all(math.isfinite(s) for s in scales) or not math.isfinite(radius):
            continue
        if abs(s_g) > MAX_ABS_SCALE or abs(s_g) < MIN_ABS_SCALE:
            continue
        refl = [surface_reflectance(lens, i, w, coatings) * surface_reflectance(lens, j, w, coatings)
                for lens, w in zip(lenses, WAVELENGTHS_UM)]
        # Transform scales area by s^2 without conserving energy; undo that.
        rgb = tuple(r / (s_g * s_g) for r in refl)
        spot = max(radius, 1e-3)
        peak = refl[1] * (entrance_radius / spot) ** 2
        ghosts.append(Ghost((i, j), tuple(scales), radius, rgb, peak))

    ghosts.sort(key=lambda g: g.peak, reverse=True)
    info = {"efl": efl, "fnumber": fnumber, "clamped": clamped,
            "max_fnumber": max_n, "pairs": len(pairs)}
    return ghosts[:max(0, min(count, MAX_GHOST_SLOTS))], info


def starburst_spikes(blades):
    """Diffraction spikes from an n-blade aperture: even -> n, odd -> 2n."""
    blades = int(blades)
    return blades if blades % 2 == 0 else 2 * blades


# -- Presets -------------------------------------------------------------------
# Approximations of classic published designs (not a specific product).
# Double-Gauss: the textbook "Double Gauss 28 degree field" example, scaled.

_DG_BASE = [
    # radius, thickness, n_d, V_d, coated
    (54.153, 8.747, 1.6074, 56.65, 1),
    (152.522, 0.500, 1.0, 0.0, 1),
    (35.951, 14.000, 1.6204, 60.32, 1),
    (0.0, 3.777, 1.6034, 38.03, 0),
    (22.270, 14.253, 1.0, 0.0, 1),
    ("STOP", 12.428),
    (-25.685, 3.777, 1.6034, 38.03, 1),
    (0.0, 10.834, 1.6204, 60.32, 0),
    (-36.980, 0.500, 1.0, 0.0, 1),
    (196.417, 6.858, 1.6204, 60.32, 1),
    (-67.148, 57.315, 1.0, 0.0, 1),
]

_RETRO_FRONT = [
    (60.0, 2.5, 1.6204, 60.32, 1),
    (22.0, 30.0, 1.0, 0.0, 1),
]


def _build(rows, scale, stop_fnumber):
    """Scale a row list, then size the stop for the requested max f-number."""
    out = []
    for row in rows:
        if row[0] == "STOP":
            out.append(Surface(0.0, row[1] * scale, 1.0, 0.0, False, True, 1.0))
        else:
            r, t, n, v, c = row
            out.append(Surface(r * scale, t * scale, n, v, bool(c)))
    lens = _Lens(out, _LAMBDA_D)
    a, _b = lens.to_stop_coeffs()
    out[lens.stop].semi = abs(a) * effective_focal_length(out) / (2.0 * stop_fnumber)
    return out


def _scaled_to(rows, focal_mm, stop_fnumber):
    unit = _build(rows, 1.0, stop_fnumber)
    return _build(rows, focal_mm / effective_focal_length(unit), stop_fnumber)


def format_prescription(surfaces):
    lines = ["# radius thickness n_d V_d coated   (STOP semi_diameter thickness)"]
    for s in surfaces:
        if s.is_stop:
            lines.append("STOP %.4f %.4f" % (s.semi, s.thickness))
        else:
            lines.append("%.4f %.4f %.4f %.2f %d" % (s.radius, s.thickness, s.n_d, s.v_d, int(s.coated)))
    return "\n".join(lines)


_PRESETS = (
    ("50mm f/2 Double-Gauss", _DG_BASE, 50.0, 2.0),
    ("24mm f/2.8 Retrofocus", _RETRO_FRONT + _DG_BASE, 24.0, 2.8),
    ("85mm f/1.8 Portrait", _DG_BASE, 85.0, 1.8),
)
PRESET_NAMES = tuple(p[0] for p in _PRESETS)
PRESET_FOCAL = dict((p[0], p[2]) for p in _PRESETS)


def preset(name):
    for pname, rows, focal, fnum in _PRESETS:
        if pname == name:
            return _scaled_to(rows, focal, fnum)
    raise KeyError(name)
```

- [ ] **Step 4: Run the tests to make sure they pass**

Run: `cd /f/Python/Nuke && python -m unittest tests.test_lens_optics -v`
Expected: `Ran 18 tests ... OK`

- [ ] **Step 5: Sanity-print the 50mm solve**

```bash
cd /f/Python/Nuke && python -c "
import sid_lens_optics as o
g, i = o.solve(o.preset(o.PRESET_NAMES[0]), 2.8, True, 3)
print(round(i['efl'],2), i['pairs'], [(x.pair, round(x.scale[1],3)) for x in g])"
```

Expected: `50.0 45 [((1, 9), 1.509), ((8, 10), 0.867), ((4, 6), -1.19)]`

---

### Task 2: Nuke node builder

**Files:**
- Create: `F:\Python\Nuke\tests\test_flare_tcl.py`
- Create: `F:\Python\Nuke\sid_lens_flare.py`

- [ ] **Step 1: Write the failing TCL lint tests**

Create `F:\Python\Nuke\tests\test_flare_tcl.py`:

```python
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
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `cd /f/Python/Nuke && python -m unittest tests.test_flare_tcl -v`
Expected: ERROR, `ModuleNotFoundError: No module named 'sid_lens_flare'`

- [ ] **Step 3: Write the builder**

Create `F:\Python\Nuke\sid_lens_flare.py`:

```python
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
```

- [ ] **Step 4: Run all unit tests**

Run: `cd /f/Python/Nuke && python -m unittest discover -s tests -v`
Expected: `Ran 34 tests ... OK`

---

### Task 3: Integration check inside Nuke

**Files:**
- Create: `F:\Python\Nuke\tests\nuke_flare_check.py`

- [ ] **Step 1: Write the Nuke check script**

Create `F:\Python\Nuke\tests\nuke_flare_check.py`:

```python
# Integration check inside Nuke (works in Non-Commercial mode):
#     "C:/Program Files/Nuke17.1v3/Nuke17.1.exe" --nc -t tests/nuke_flare_check.py
# Touches about 5 Python Node objects (root, the test source, the LensFlare
# group, the internal starKernel, plus selectedNode inside make_lens_flare),
# well under the NC 10-node limit. Exits non-zero on failure.
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import nuke  # noqa: E402
import sid_lens_optics as _o  # noqa: E402

FAILS = []


def check(cond, msg):
    print(("PASS  " if cond else "FAIL  ") + msg)
    if not cond:
        FAILS.append(msg)


nuke.addFormat("640 360 1 flaretest")
nuke.root()["format"].setValue("flaretest")
SRC_X, SRC_Y, SRC_V = 480.5, 250.5, 5.0
nuke.tcl("""
Constant { inputs 0 channels rgba color {0.02 0.02 0.02 0.5} format "640 360 0 0 640 360 1 flaretest" }
Expression {
 expr0 {hypot(x+0.5-%(x)s,y+0.5-%(y)s)<6?%(v)s:r}
 expr1 {hypot(x+0.5-%(x)s,y+0.5-%(y)s)<6?%(v)s:g}
 expr2 {hypot(x+0.5-%(x)s,y+0.5-%(y)s)<6?%(v)s:b}
 expr3 {a}
 name flareTestSrc
}
""" % {"x": SRC_X, "y": SRC_Y, "v": SRC_V})
src = nuke.toNode("flareTestSrc")
src.setSelected(True)

import sid_lens_flare as lf  # noqa: E402

g = lf.make_lens_flare()


def s(x, y, ch="g"):
    return nuke.sample(g, ch, x, y)


def ghost_centre(slot):
    sc = g["g%dsG" % slot].value()
    return 320 + sc * (SRC_X - 320), 180 + sc * (SRC_Y - 180), sc


DEFAULT_PRESCRIPTION = _o.format_prescription(_o.preset(_o.PRESET_NAMES[0]))


def reset():
    """Restore every knob the checks touch, then re-solve (the flipped-ghost
    block overwrites ghost energies), so no check depends on state left by an
    earlier section."""
    g["lensPreset"].setValue(_o.PRESET_NAMES[0])
    g["customPrescription"].setValue(DEFAULT_PRESCRIPTION)
    for name, val in (("fstop", 2.8), ("ghostCount", 8), ("ghostIntensity", 1.0),
                      ("starIntensity", 0.02), ("glareIntensity", 1e-5), ("blades", 6),
                      ("apRotation", 0.0)):
        g[name].setValue(val)
    g["outputMode"].setValue("Flare over Plate")
    g["flareRes"].setValue("Half")
    lf.solve(g)


def ghosts_only(count):
    g["starIntensity"].setValue(0)
    g["glareIntensity"].setValue(0)
    g["outputMode"].setValue("Flare Only")
    g["ghostCount"].setValue(count)


check(g.input(0) is not None, "auto-connected to selected node")
check(g["status"].value().startswith("EFL 50.0mm"), "status after build: %s" % g["status"].value())

# --- slot 0: position (centroid), dark surround, coating colour ---------------------
reset()
ghosts_only(1)
px, py, sc = ghost_centre(0)
rad = g["g0rad"].value() * 640 / g["sensorWidth"].value()
# Brightness-weighted centroid of the green channel. Slot 0 spans x 516..608,
# y 240..332 in the 640x360 frame, so it is fully inside and unclipped: both axes
# are meaningful without moving the source.
half_w = rad + 10
wsum = cx = cy = 0.0
y = max(0.0, py - half_w)
while y <= min(359.0, py + half_w):
    x = max(0.0, px - half_w)
    while x <= min(639.0, px + half_w):
        w = max(s(x, y), 0.0)
        wsum += w; cx += w * x; cy += w * y
        x += 2.0
    y += 2.0
check(px - half_w >= 0 and px + half_w <= 640 and py - half_w >= 0 and py + half_w <= 360,
      "slot 0 window unclipped by the frame")
# 3px tolerance = 2px sampling grid + about one half-res pixel (the flare is built at
# half resolution and upsampled). The measured error is a steady ~(-1.6, -1.4) px;
# shifting the samples by a pixel-centre convention (+0.5 / +1.0) only reduces it to
# ~(-1.1, -0.9) / (-0.6, -0.4) and there is no principled choice, so the plain
# prediction is kept and the tolerance is not loosened.
err = math.hypot(cx / max(wsum, 1e-12) - px, cy / max(wsum, 1e-12) - py)
check(wsum > 0 and err < 3.0,
      "slot 0 centroid (%.1f, %.1f) within 3px of predicted (%.1f, %.1f), error %.2fpx"
      % (cx / max(wsum, 1e-12), cy / max(wsum, 1e-12), px, py, err))
probes = [(px - rad - 15, py), (px + rad + 15, py), (px, py - rad - 15), (px, py + rad + 15)]
probes = [(x, y) for x, y in probes if 0 <= x < 640 and 0 <= y < 360]
pmax = max((s(x, y) for x, y in probes), default=0.0)
check(len(probes) > 0, "slot 0 dark probes: %d of 4 inside the frame" % len(probes))
check(len(probes) > 0 and pmax < 1e-6,
      "slot 0 dark at %d probes just outside its %.1fpx spot: max %.3g" % (len(probes), rad, pmax))
rgb = [s(px, py, c) for c in "rgb"]
check(max(rgb) / max(min(rgb), 1e-12) > 1.2, "coating gives the ghost a colour: %s" % [round(v, 4) for v in rgb])


# --- flipped (negative-scale) ghost -----------------------------------------------------
def flipped_ghost_checks():
    reset()
    ghosts_only(8)
    neg = next((n for n in range(8) if g["g%dsG" % n].value() < 0), None)
    if neg is None:
        check(False, "no negative-scale ghost slot in the first 8")
        return
    g["ghostCount"].setValue(neg + 1)
    for n in range(neg):          # leave only the flipped slot's energy non-zero
        g["g%deR" % n].setValue(0); g["g%deG" % n].setValue(0); g["g%deB" % n].setValue(0)
    nx, ny, nsc = ghost_centre(neg)
    check(nx < 320 and ny < 180, "negative-scale slot %d lands on the flipped side (%.1f, %.1f)" % (neg, nx, ny))
    check(s(nx, ny) > 1e-4, "flipped ghost is lit: %.4g" % s(nx, ny))
    # Unflipped mirror position c + |s|*(p - c). It must be >20px from the flipped
    # centre, and < 10% of the flipped brightness shows the ghost really is mirrored.
    mx, my = 320 + abs(nsc) * (SRC_X - 320), 180 + abs(nsc) * (SRC_Y - 180)
    check(math.hypot(mx - nx, my - ny) > 20 and s(mx, my) < 0.1 * s(nx, ny),
          "flipped ghost absent at unflipped mirror (%.1f, %.1f): %.3g vs %.3g" % (mx, my, s(mx, my), s(nx, ny)))


flipped_ghost_checks()

# --- zero ghosts, then starburst and glare isolated --------------------------------------
reset()
ghosts_only(0)
peak = max(s(x, y) for x in range(5, 640, 20) for y in range(5, 360, 20))
check(peak == 0.0, "Ghost Count 0 with starburst/glare off gives black: max %.3g" % peak)

g["starIntensity"].setValue(0.02)
star_on = s(SRC_X + 20, SRC_Y)
g["starIntensity"].setValue(0)
star_off = s(SRC_X + 20, SRC_Y)
check(star_on > 1e-3 and star_off < 1e-6,
      "starburst alone lights next to the source: %.3g (off: %.3g)" % (star_on, star_off))
# No "dark far from every spike" control: the starburst tail falls off smoothly
# (still ~1e-4 at 150px even between spikes) and never reaches zero inside the frame.
g["glareIntensity"].setValue(1e-5)
glare_on = s(SRC_X, SRC_Y - 40)
g["glareIntensity"].setValue(0)
glare_off = s(SRC_X, SRC_Y - 40)
# Threshold 1e-4, not 1e-3: glare at its default 1e-5 is subtle (~2.4e-4 measured at
# 40px); the off control at the same point proves the signal comes from the glare.
check(glare_on > 1e-4 and glare_off < 1e-6,
      "glare alone lights 40px below the source: %.3g (off: %.3g)" % (glare_on, glare_off))

# --- alpha -------------------------------------------------------------------------------
reset()
# Only slots 0-1 (radii 46 and 87 px, far from the corner): the outer slots have
# 126..350 px spots that legitimately cover (2, 2) with a faint tail.
ghosts_only(2)
a_g, a_c = s(px, py, "a"), s(2, 2, "a")
check(0.0 <= a_g <= 1.0 and 0.0 <= a_c <= 1.0 and a_g > 0 and abs(a_c) < 1e-6,
      "Flare Only alpha: ghost centre %.4g in (0,1], dark corner %.3g == 0" % (a_g, a_c))

reset()    # Flare over Plate with default ghosts, starburst and glare
p_g, p_c = s(px, py, "a"), s(2, 2, "a")
check(abs(p_g - 0.5) < 1e-6 and abs(p_c - 0.5) < 1e-6,
      "Flare over Plate keeps plate alpha 0.5 (ghost centre %.6g, corner %.6g)" % (p_g, p_c))

# --- preview modes -----------------------------------------------------------------------
reset()
g["outputMode"].setValue("Highlights")
check(abs(s(SRC_X, SRC_Y) - SRC_V * 2 ** 12) < 1.0, "Highlights preview = source x 2^12")
g["outputMode"].setValue("Aperture")
check(s(320, 180, "a") > 0.99 and s(5, 5, "a") < 1e-6, "Aperture preview draws centred shape")

# --- resolution --------------------------------------------------------------------------
reset()
ghosts_only(1)
half = s(px, py)
g["flareRes"].setValue("Full")
full = s(px, py)
check(abs(full - half) / max(full, 1e-9) < 0.05,
      "Full vs Half resolution agree at ghost centre: %.4g vs %.4g" % (full, half))

# --- custom prescription / f-stop clamp ---------------------------------------------------
reset()
g["lensPreset"].setValue("Custom")          # default table = 50mm preset, solves fine
before = g["g0sG"].value()
g["customPrescription"].setValue("not a lens\n")
check("Prescription error, line 1" in g["status"].value(), "bad custom table reported")
check(g["g0sG"].value() == before, "bad custom table keeps the previous solve")

reset()
g["fstop"].setValue(1.2)
check("clamped" in g["status"].value(), "f-stop clamp noted: %s" % g["status"].value())
check(abs(g["effFstop"].value() - 2.0) < 1e-6, "effFstop clamped to 2.0: %s" % g["effFstop"].value())

# --- starburst spike count ----------------------------------------------------------------
# Must follow the blade rule (odd n -> 2n, even n -> n). Reads the diffraction kernel
# itself (one extra Node object, still NC-safe).
reset()
with g:
    kern = nuke.toNode("starKernel")
check(kern is not None, "starKernel found")
if kern is not None:
    kw, kh = kern.width(), kern.height()
    N = 720                      # ring samples: 0.5 degree resolution
    R = 40                       # ring radius in kernel pixels (well inside the kernel)
    for blades in (5, 6):
        g["blades"].setValue(blades)
        ring = [nuke.sample(kern, "g", kw / 2.0 + R * math.cos(2 * math.pi * i / N),
                            kh / 2.0 + R * math.sin(2 * math.pi * i / N)) for i in range(N)]
        top = max(ring)
        # Local maxima above half the ring maximum (0.5 * top ignores weak ripple).
        cand = [i for i in range(N)
                if ring[i] > 0.5 * top and ring[i] >= ring[i - 1] and ring[i] > ring[(i + 1) % N]]
        # Merge ripple/wrap-around splits of one spike: candidates within 10 samples
        # (5 degrees) of the previous one, circularly, belong to the same spike.
        peaks = sum(1 for k, i in enumerate(cand) if (i - cand[k - 1]) % N > 10) if cand else 0
        check(peaks == _o.starburst_spikes(blades),
              "blades %d -> %d starburst spikes (expected %d)" % (blades, peaks, _o.starburst_spikes(blades)))

print("\n%d failure(s)" % len(FAILS))
sys.exit(1 if FAILS else 0)
```

- [ ] **Step 2: Run it in Nuke Non-Commercial terminal mode**

Run: `cd /f/Python/Nuke && timeout 900 "C:/Program Files/Nuke17.1v3/Nuke17.1.exe" --nc -t tests/nuke_flare_check.py; echo exit=$?`
Expected: 25 lines starting `PASS`, then `0 failure(s)` and `exit=0`.
Reference values: slot 0 at `(562.2, 286.4)` lit about `0.0178`; coating colour about `[0.0368, 0.0178, 0.066]`; flipped slot 2 at `(129.0, 96.1)`.

If a check fails, fix the code, not the check. Two known test traps are already handled: changing Ghost Count re-solves (only the first N slots get values), and switching Lens to Custom re-solves from a 4-decimal table.

---

### Task 4: Install and document

**Files:**
- Modify: `F:\Python\Nuke\menu.py` (append)
- Modify: `C:\Users\raman\.nuke\menu.py` (append)
- Modify: `F:\Python\Nuke\README.txt`

- [ ] **Step 1: Register the menu in both menu.py files**

Append to the end of `F:\Python\Nuke\menu.py` AND `C:\Users\raman\.nuke\menu.py`:

```python

import sid_lens_flare
sid_lens_flare.install_menu()
```

- [ ] **Step 2: Copy the two modules to Nuke's plugin folder**

Run: `cp /f/Python/Nuke/sid_lens_optics.py /f/Python/Nuke/sid_lens_flare.py /c/Users/raman/.nuke/ && cmp /f/Python/Nuke/sid_lens_flare.py /c/Users/raman/.nuke/sid_lens_flare.py && echo SYNCED`
Expected: `SYNCED`

- [ ] **Step 3: Document it in README.txt**

In `F:\Python\Nuke\README.txt`, replace:

```
sid_edge_extend_blur.py - Edge Extend Blur (Edge Extend + final edge blur)
```

with:

```
sid_edge_extend_blur.py - Edge Extend Blur (Edge Extend + final edge blur)
sid_lens_flare.py    - Lens Flare (needs sid_lens_optics.py next to it)
```

Change `merge the six lines` to `merge the eight lines`, and `list all eight tools` to `list all nine tools`. Then append at the end:

```
Lens Flare (sid_lens_flare.py + sid_lens_optics.py)
------------------------------------------------------
An image-driven, physically traced lens flare. Every highlight in the
plate flares. Ghosts come from tracing light through a real lens
prescription: each reflection between two glass surfaces gives a ghost
whose position, flip, size, coating colour and colour fringing are
computed, then the highlights are convolved with the actual aperture
shape. Also: diffraction starburst (spike count follows the blades:
even n gives n spikes, odd n gives 2n) and veiling glare.

- Lens: 50mm f/2 double-Gauss, 24mm f/2.8 retrofocus, 85mm f/1.8, or
  paste a Custom prescription (radius thickness n_d V_d coated, plus
  one "STOP semi_diameter thickness" row, the stop in air). Errors
  show in the Status line and keep the previous solve.
- Source Gain is in stops (default 12): real light sources are far
  brighter than a clipped plate.
- F-Stop, Ghost Count and Coatings re-trace the lens and cannot be
  animated.
- Flare Resolution Half (default) renders about 4x faster than Full.
- Output: Flare over Plate, Flare Only, Highlights, Aperture.
- Tests: python -m unittest discover -s tests   (no Nuke needed)
         Nuke17.1.exe --nc -t tests/nuke_flare_check.py   (inside Nuke)
```

- [ ] **Step 4: Manual GUI check (the user does this in Nuke)**

Restart Nuke, select a Read with a bright light in it, then Nodes > Sid > Lens Flare. Confirm:
1. Ghosts sit along the line through the light and the frame centre, some on the opposite side.
2. Moving the light (or Optical Centre) moves the ghosts live.
3. Blades / Roundness / Rotation reshape ghosts and starburst instantly.
4. F-Stop 2 vs 8 changes ghost sizes, and the Status line updates.

---

### Task 5: Publish to GitHub

The tools repo clone is `C:\Users\raman\AppData\Local\Temp\sidnuketools_repo` (remote `raman-siddhartha/sid-nuke-tools`, branch `master`). Its local git config forces OpenSSL, which fails on this machine, so push with `-c http.sslBackend=schannel`.

- [ ] **Step 1: Copy files into the clone and re-run the unit tests there**

```bash
R=/c/Users/raman/AppData/Local/Temp/sidnuketools_repo
cp /f/Python/Nuke/sid_lens_optics.py /f/Python/Nuke/sid_lens_flare.py /f/Python/Nuke/menu.py $R/
mkdir -p $R/tests $R/docs/superpowers/specs $R/docs/superpowers/plans
cp /f/Python/Nuke/tests/test_lens_optics.py /f/Python/Nuke/tests/test_flare_tcl.py /f/Python/Nuke/tests/nuke_flare_check.py $R/tests/
cp /f/Python/Nuke/README.txt $R/README.md
cp /f/Python/Nuke/docs/superpowers/specs/2026-11-08-lens-flare-design.md $R/docs/superpowers/specs/
cp /f/Python/Nuke/docs/superpowers/plans/2026-11-08-lens-flare.md $R/docs/superpowers/plans/
printf "__pycache__/
*.pyc
" > $R/.gitignore
cd $R && python -B -m unittest discover -s tests && git status --short
```

Expected: `OK`, then the new and modified files listed.

- [ ] **Step 2: Commit and push**

```bash
cd /c/Users/raman/AppData/Local/Temp/sidnuketools_repo
git add .gitignore sid_lens_optics.py sid_lens_flare.py menu.py README.md tests docs
git commit -m "Add Lens Flare: image-driven, physically traced lens flare

Ghosts traced through real lens prescriptions (paraxial, 3 wavelengths),
coating colour, dispersion, aperture convolution, diffraction starburst
and veiling glare. Graph built in one TCL block (NC-safe).

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git -c http.sslBackend=schannel push origin master
```

Expected: a line ending `master -> master`.

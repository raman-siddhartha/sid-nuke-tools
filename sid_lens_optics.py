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

# Sid Lens Flare — Design

**Date:** 2026-11-08
**Status:** Approved design. Revised after prototyping in Nuke 17.1 NC (see Revision notes).
**Target:** Nuke 17.1 (must also run under Nuke Non-Commercial)

## Goal

A Nuke node that produces a lens flare by simulating a real lens, not by
drawing shapes and blurring them. Every bright part of the plate flares, the
flare follows moving lights frame by frame with no re-analysis, and ghost
position, size, flip, colour and fringing come from tracing light through an
actual lens prescription.

## Hard constraints

1. **Non-Commercial 10-node limit.** Nuke NC returns `None` once Python has
   touched 10 Node objects. Therefore:
   - The entire internal graph is built by ONE `nuke.tcl()` call. Python only
     generates the TCL text (string building, loops are fine).
   - Python never retrieves nodes inside the Group (`nuke.toNode`,
     `nuke.allNodes`, `group.node()` are banned). It reads and writes only the
     Group's own knobs.
   - Internal nodes read their values from the Group via `parent.<knob>`
     expressions.
2. **No spaces inside `{{ }}` TCL knob expressions.** Nuke splits on spaces
   there and silently keeps only the first token (this broke Edge Blur
   earlier). Free-text expression knobs such as `expr0 {...}` may contain
   spaces.
3. Strict ASCII source, matching the other Sid tools.
4. Re-solving the lens in Python happens only on knob changes, never per frame.

## Files

| File | Responsibility | Depends on |
|---|---|---|
| `sid_lens_optics.py` | Lens prescriptions, parsing, paraxial tracing, coatings, dispersion, ghost ranking, starburst parameters. Pure Python, no `nuke` import. | stdlib only |
| `sid_lens_flare.py` | Generates the TCL graph, creates knobs, writes solved values to hidden knobs, knobChanged callback, `install_menu()` adding **Nodes > Sid > Lens Flare**. | `nuke`, `sid_lens_optics` |
| `menu.py` | Adds `import sid_lens_flare; sid_lens_flare.install_menu()`. | |
| `tests/test_lens_optics.py` | Plain-Python tests for the optics module. | `sid_lens_optics` |
| `tests/test_flare_tcl.py` | Lint of the generated TCL plus solve/knobChanged tests, with a stub `nuke`. | `sid_lens_flare` |
| `tests/nuke_flare_check.py` | Integration checks run inside Nuke NC terminal mode. | Nuke 17.1 |

## Internal graph (built in one TCL block)

```
Source -> Highlights (Expression: threshold, soft knee, source gain)
            -> Reformat down by Flare Resolution (Full / Half / Quarter)
            |
            +-> Ghost slot 0..15  (16 fixed slots)
            |     3 x TransformMasked (channels red / green / blue): scale the
            |                 highlights about Optical Centre by the slot's
            |                 per-channel scale (negative = flip) -> dispersion
            |     Expression: the slot's own aperture image (n-blade polygon,
            |                 radius = slot spot radius in px)
            |     Convolve2:  image x aperture filter, normalize on (FFT)
            |     Expression gain: x coating/energy RGB x Ghost Intensity x
            |                 (ghostCount > N); never disabled
            |     disable {{parent.ghostCount<=N}} on transforms/aperture/convolve
            |
            +-> Starburst: analytic diffraction kernel (Expression, per-channel
            |              wavelength-scaled) -> 3 x Convolve2 (one per channel)
            +-> Veiling glare: two wide Blurs, summed, x Glare Intensity
            |
            v
Sum (Merge plus chain) -> Reformat back up -> Output Mode switch
   (Flare Only / Flare over Plate / Highlights preview / Aperture preview)
   -> Mask & Mix (Merge2 copy, mask input, invert, mix) -> Output
```

- Ghost Count changes only disable expressions; the graph is never rebuilt.
- Convolve2 input order in TCL: push filter, push image, `Convolve2 {inputs 2}`.
  Its kernel is centred on the filter's format centre; `normalize` conserves
  energy. (ZDefocus2 was rejected: it needs a depth setup for constant blur.)
- Gain/multiply nodes are never disabled: a disabled node passes its input
  through, which would leak unscaled highlights into the sum.
- Temp variable names never use r, g, b, a, x, y, z (reserved by Nuke).

## Optics model (`sid_lens_optics.py`)

**Prescription format**, one surface per row:
`radius_mm thickness_mm n_d V_d coated` where `radius_mm = 0` means flat,
`n_d`/`V_d` describe the medium AFTER the surface (air = `1.0 0`),
`coated` is `0` or `1`. Exactly one row is `STOP <semi_diameter_mm> <thickness_mm>`,
marking the aperture stop (in air). The sensor sits at the paraxial focus for
infinity at 550 nm, so the last row's thickness is not used for placement. Comment lines start with `#`.

**Presets:** 50mm f/2 double-Gauss, 24mm f/2.8 retrofocus, 85mm f/1.8
portrait. Approximations derived from published patent-style examples, not a
specific manufacturer's lens; each preset's computed effective focal length
must be within 2% of its nominal focal length.

**Paraxial tracing:** y-u ray trace with signed indices (equivalent to 2x2
ray-transfer matrices for refraction, reflection and translation). For every surface pair i < j (both non-STOP): path is forward to
j, reflect back to i, reflect forward to the sensor. Per ghost, per R/G/B
wavelength (650 / 550 / 450 nm):
- **scale** = ghost chief-ray height at sensor / primary image height. Negative
  means flipped about the optical centre.
- **spot radius** = marginal-ray height at the sensor for a ray from the stop
  edge at the current f-stop, converted mm to px:
  `px = mm * plate_width_px / sensor_width_mm`.
- **render multiplier** (per channel) = R_i(lambda) x R_j(lambda) / sG^2.
  TransformMasked scales area by s^2 without conserving energy, so 1/s^2 undoes
  it; the normalized Convolve2 then spreads that energy over the spot.
- **ranking peak** = R_i x R_j (green) x (entrance pupil radius / spot radius)^2.
- Ghosts with |sG| < 0.02 (whole frame squeezed to a point) or > 50 are dropped.
- Spot radius in px is computed inside the aperture Expression:
  `max(0.5, g{N}rad * width / sensorWidth)`, `width` being the working
  (possibly downscaled) format, so no plate size is needed in Python.

**Reflectance:** uncoated surfaces use normal-incidence Fresnel
`((n1-n2)/(n1+n2))^2`. Coated surfaces use single-layer quarter-wave MgF2
(n = 1.38, designed at 550 nm) thin-film reflectance evaluated at each of the
three wavelengths, which gives each ghost its RGB colour.

**Dispersion:** two-term Cauchy fit per glass, `n(lambda) = A + B/lambda^2`
(lambda in micrometres), with
`B = ((n_d - 1)/V_d) / (1/0.4861^2 - 1/0.6563^2)` and
`A = n_d - B/0.5876^2`, so that n(587.6 nm) = n_d and
n(486.1 nm) - n(656.3 nm) = (n_d - 1)/V_d. Media with `V_d = 0` (air) are
non-dispersive. A Dispersion knob scales the deviation of
the R and B scales from G (1 = physical, 0 = none).

**Ranking:** all pairs ranked by peak; the top Ghost Count go into slots
0..15. Unused slots get multiplier 0.

**Starburst parameters:** spike count = blades if blades is even, else
2 x blades. Spike length proportional to wavelength x f-number (so red spikes
are longer). The diffraction image Expression renders per-edge spikes with a
sinc^2 cross-profile and 1/r^2 envelope.

**Veiling glare:** two Gaussian scatter widths (Glare Size and 4 x Glare
Size), equal weights, scaled by Glare Intensity. Achromatic.

## Controls

| Section | Knobs |
|---|---|
| Lens | Preset (50mm / 24mm / 85mm / Custom), Custom Prescription (multiline), F-Stop, Sensor Width (mm, default 36), Optical Centre (XY, default frame centre) |
| Source | Threshold, Soft Knee, Source Gain (stops, default 12: real sources are ~2^12 brighter than a clipped plate) |
| Aperture | Blades (3-12), Roundness (0-1), Rotation (deg) |
| Ghosts | Ghost Count (0-16, default 8), Ghost Intensity, Dispersion (0-2, default 1), Coatings (on/off) |
| Starburst | Intensity (default 0.02), Length |
| Veiling Glare | Intensity (default 0.00001), Size |
| Output | Flare Resolution (Full / Half / Quarter, default Half), Mode (Flare over Plate / Flare Only / Highlights / Aperture), Invert Mask, Mix, Status (read-only text), credit knob |

Hidden per-slot knobs (written by Python): `g{N}sR g{N}sG g{N}sB` (scale),
`g{N}rad` (spot radius, mm on sensor), `g{N}eR g{N}eG g{N}eB` (render multiplier).

**Re-solve triggers** (knobChanged): Preset, Custom Prescription, F-Stop,
Ghost Count, Coatings. Sensor Width, Blades, Roundness, Rotation, Dispersion
and all intensities act downstream in expressions and need no re-solve.

**Alpha:** Flare over Plate passes the plate alpha through unchanged. Flare
Only outputs `clamp(max(r,g,b),0,1)` as alpha.

## Error handling

- Invalid custom prescription: Status shows the error and line number, the
  previous solve's hidden knob values are kept.
- F-Stop faster than the lens's maximum aperture: clamped to the maximum,
  noted in Status.
- No highlights above threshold: output is the plate / black, no errors.
- A numerically degenerate ghost (non-finite values, |scale| > 50, or
  |scale| < 0.02) is dropped from ranking.

## Testing

1. **Plain Python** (`python -m unittest discover -s tests`, stdlib only):
   - each preset EFL within 2% of nominal
   - surface pair count = N(N-1)/2 for N reflecting surfaces
   - coated reflectance < uncoated for the same interface at 550 nm
   - R and B ghost scales differ from G. (Dispersion = 0 gives equal scales
     by construction: the TCL scale is `sG+dispersion*(sR-sG)`; not unit-tested.)
   - starburst spike count rule for blades 5 (10) and 6 (6)
   - custom prescription parser rejects malformed rows with a line number
2. **Nuke NC terminal** (`Nuke17.1.exe --nc -t`), TCL queries only, never more
   than 10 Python Node objects: single bright dot on black; check that slot 0
   energy appears at the solver-predicted position on the flipped side of the
   optical centre; check Flare over Plate alpha equals plate alpha; check Ghost
   Count 0 gives no ghosts.
3. **Lint:** fail if any `{{...}}` in generated TCL contains a space.

## Out of scope (v1)

Anamorphic lenses, off-axis vignetting of ghosts, spectral rendering with
more than three wavelengths, depth-dependent flare, GPU-specific code paths,
point-light mode.

## Revision notes (after prototyping in Nuke 17.1 NC)

- Convolve2 replaces ZDefocus; TransformMasked (has a `channels` knob)
  replaces a per-channel Expression resample, giving filtered resampling.
- STOP rows carry a thickness; sensor placed at paraxial focus.
- Energy model split into render multiplier (1/s^2) and ranking peak.
- Sensor Width no longer needs a re-solve (spot px computed in expressions).
- Measured: the 50mm double-Gauss base computes EFL 99.50 mm / BFD 57.49 mm,
  matching the published example (99.5 / 57.3). A slot-0 ghost lands exactly at
  the predicted position with a sharp aperture edge; Full vs Half resolution
  agree within 0.3 %; the 132-node graph builds in ~0.15 s.

## Revision notes (after per-task code review)

- Custom prescriptions are fully validated in the parser: non-finite values,
  negative thickness, a STOP not in air, a lens with no optical power, a
  diverging lens and a stop at an image plane all raise `PrescriptionError`
  with a line number. `solve()` in the node additionally catches arithmetic
  errors and `_on_knob_changed` catches anything else, so a bad lens can never
  put a Python traceback in front of the user; the previous solve is kept.
- Starburst: each blade edge contributes a full line through the centre, so
  odd blade counts really give 2n spikes (verified on the rendered kernel in
  Nuke: 5 blades -> 10, 6 -> 6). Blades are clamped 3..12 everywhere.
- Optical Centre defaults to the selected input's own size (falls back to the
  project format), so 4K plates in HD projects flare about the right point.
- F-Stop, Ghost Count and Coatings are NO_ANIMATION (they re-trace the lens).
- Starburst length and the node label use the clamped (effective) f-number.
- Final test counts: 34 plain-Python tests, 25 checks inside Nuke NC.

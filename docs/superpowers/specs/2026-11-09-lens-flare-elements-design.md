# Sid Lens Flare -- Flare Elements (v2) Design

**Date:** 2026-11-09
**Status:** Approved design
**Builds on:** `2026-11-08-lens-flare-design.md` (Lens Flare v1: traced ghosts,
starburst, veiling glare). All v1 hard constraints still apply.

## Goal

Add 11 flare elements to the existing Lens Flare node -- Iris, Multi-Iris,
Rings, Hoop, Caustic, Lens Orbs, Streak, Spike Ball, Shimmer, Sparkle, Glint --
each a separate, switchable property. Each element defaults to behaviour
derived from the lens (position along the flare axis, f-stop, blades, optical
centre, coating tint) and has art-direct overrides.

## Hard constraints (unchanged from v1)

1. One `nuke.tcl()` call builds the whole graph; Python never looks up nodes
   inside the Group (Nuke Non-Commercial 10-node limit).
2. No space inside any single `{{...}}` TCL expression.
3. Temp variable names never `r g b a x y z`.
4. Gain nodes are never disabled (a disabled node passes its input through);
   switch-off = expensive upstream nodes disabled + gain multiplied by 0.
5. Strict ASCII. No per-frame Python: animation comes from `frame` inside
   expressions.

## Files

| File | Responsibility |
|---|---|
| `sid_flare_elements.py` (new) | One TCL generator + one knob-builder per element, the hotspot detector, shared kernel helpers. TCL generators are pure string functions (testable with a stub `nuke`); only the knob builders call `nuke`. |
| `sid_lens_flare.py` | Calls the element generators from `build_tcl()`, adds tabs and the element knobs, adds On/Off for Ghosts / Starburst / Glare. |
| `tests/test_flare_tcl.py` | Lint tests extended to every element. |
| `tests/nuke_flare_check.py` | Per-element integration checks in Nuke NC. |

## Sources

Each element has a **Source** enum: `All highlights` / `Hotspot`.

- **All highlights** = `$hl`, the existing downscaled highlight stream.
- **Hotspot** = `$hot`: one point per light, every frame, no Python.
  Score = luminance of a lightly blurred `$hl` (blur = Hotspot Radius / 3),
  multiplied by `1 + 1e-6*(x + 0.618*y)` as a tie-break (clipped, flat-topped
  lights would otherwise make every pixel a peak). Dilate (max filter,
  Hotspot Radius) gives the local max; a pixel survives where score >= the
  dilated score. A surviving pixel carries its light's energy: a box blur of
  `$hl` (2 x Hotspot Radius) times the box area. Hotspot Radius (default 24
  plate px) sets how close two lights can be before they merge. The whole
  detector is disabled unless some enabled element uses Hotspot.

Defaults: axial elements use All highlights; centred elements use Hotspot.

## Elements

Every element has: **Enable** (Boolean, default off), **Intensity**,
**Source**, **Tint** (Color, default white x lens coating tint where noted).
Position along the flare axis is a signed scale about the Optical Centre:
`1` = at the light, `0` = optical centre, `-1` = mirror point.

### Centred (rendered as kernel x Convolve2 around each source point)

| Element | Physical basis | Extra controls |
|---|---|---|
| Streak | Anamorphic (cylindrical) glass smears light along one axis | Length, Thickness, Angle (default 0 = horizontal), Falloff |
| Spike Ball | Fine scratches / debris: many thin random rays | Rays (8-64), Length, Length Variation, Thickness, Seed |
| Shimmer | Atmospheric turbulence: fine radial rays that flicker | Rays (16-128), Length, Speed (0 = static), Seed |
| Sparkle | Small sharp star from a tiny bright point | Points (4/6/8), Size, Twinkle Speed (0 = static) |
| Glint | Intense core + short cross spikes on the hottest point | Size, Spike Length, Angle |

Kernels are procedural Expressions centred on the working format, normalized
by Convolve2 (`normalize true`), so Intensity is the fraction of the source
energy the element carries.

### Axial (rendered as scaled copy of the source about the Optical Centre, convolved with the element shape)

| Element | Physical basis | Extra controls |
|---|---|---|
| Iris | One aperture ghost; shape follows Blades / Roundness / Rotation | Position (default -0.6), Size (plate px radius, default 60, scaled by 2.8 / effective f-stop so stopping down shrinks it like a real ghost), Softness |
| Multi-Iris | Several aperture ghosts along the axis, like a chain of coated-surface reflections | Count (1-8 slots), Spread (position range), Size Min / Max, Seed, Colour Variation |
| Rings | Thin circular ghosts from strongly curved surfaces | Count (1-4 slots), Position, Radius, Thickness, Spacing |
| Caustic | Spherical-aberration ghost: bright cusped edge, dim centre | Position (default -0.3), Size, Edge Sharpness |
| Hoop | Internal barrel reflection: large ring around the optical centre, brightest on the side facing the light | Radius (default 0.45 x frame height), Width, Arc Falloff |
| Lens Orbs | Dust / smudges on the front glass, lit when a light is near | Count (8-64), Size Min / Max, Seed, Proximity (blur radius), Softness |

- Iris / Multi-Iris / Rings / Caustic: TransformMasked scale = Position about
  the Optical Centre (scaled to working resolution), then Convolve2 with the
  shape kernel. Like v1, Transform does not conserve energy, so the gain
  includes `1/Position^2` (Position clamped to |p| >= 0.05).
- Multi-Iris slot i: position = lerp(-Spread, +Spread, hash_i), size =
  lerp(Size Min, Size Max, hash'_i), tint varied by Colour Variation; slots
  >= Count are disabled with gain 0.
- Hoop: annulus mask around the Optical Centre x a very wide Blur of the
  source (Arc Falloff = blur size), so the arc nearest the light brightens.
  No transform.
- Lens Orbs: procedural dust pattern (Count soft discs from Seed, fixed in
  frame) x a wide Blur of the source (Proximity). No transform.

## Existing parts get On/Off

`ghostsOn`, `starOn`, `glareOn` Booleans (default on). Off = their gain is 0
and their expensive nodes are disabled, exactly like Ghost Count 0.

## Panel layout

Three tabs:
1. **Lens** -- lens, f-stop, sensor, optical centre, source threshold/knee/gain,
   aperture, flare resolution, output, mask/mix, status.
2. **Ghosts & Glare** -- ghosts (+ On), starburst (+ On, shape controls),
   veiling glare (+ On).
3. **Elements** -- Hotspot Radius, then 11 collapsible groups (closed by
   default), each starting with its Enable checkbox.

## Defaults

All 11 elements off, so existing flares look identical and cost nothing
extra. Enabling one element costs about one extra FFT convolution at the
working resolution (Multi-Iris / Rings: one per active slot).

## Error handling

No new error paths: all element controls are clamped in TCL
(`clamp(...)`/`max(...)`, no spaces), so extreme values cannot produce NaNs
or divide by zero.

## Testing

1. **Plain Python** (`python -B -m unittest discover -s tests`):
   - every element's expensive nodes are gated by its Enable knob, its gain
     multiplies by the Enable knob, gains never disabled;
   - every element knob referenced in the TCL is created, and vice versa;
   - no spaces inside `{{...}}`, no reserved temp names, ASCII.
2. **Nuke NC** (`tests/nuke_flare_check.py`), per element, starting from a
   reset state with all other elements off:
   - Enable off: output identical to the no-element baseline (max abs diff 0);
   - Enable on: lit where expected -- centred elements around the light,
     axial ones at the predicted position `c + Position*(p - c)`, Hoop
     brighter on the light side than the opposite side, Orbs brighter near
     the light than far from it;
   - Hotspot: two separated lights give exactly two hotspot pixels;
   - Shimmer / Sparkle: frame 1 vs 2 differ when Speed > 0, identical at 0;
   - Ghosts / Starburst / Glare Off switches give exactly 0 from that part.

## Build order (one spec, plan in batches)

1. Framework: tabs, On/Off for existing parts, hotspot detector, element
   module skeleton, test helpers.
2. Centred elements: Streak, Spike Ball, Shimmer, Sparkle, Glint.
3. Axial elements: Iris, Multi-Iris, Rings, Caustic.
4. Hoop, Lens Orbs.
5. README / website docs, full regression, publish to GitHub.

## Out of scope

Per-element animation curves beyond Speed, user-supplied textures for orbs,
lens-dirt image input, depth-aware occlusion.

## Revision notes (implementation)

- Verified in Nuke 17.1 NC: 58 integration checks pass (every element lit
  where expected and exactly 0 when off; two lights -> exactly two hotspots,
  one of them clipped flat; Shimmer and Sparkle animate only when Speed > 0;
  each Ghosts / Starburst / Glare switch removes exactly that part; Iris
  halves from f/2.8 to f/5.6). 43 plain-Python tests pass.
- Default intensities were tuned so each element peaks around 0.5-4 near a
  small light at Source Gain 12 stops.

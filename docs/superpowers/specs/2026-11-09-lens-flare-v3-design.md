# Sid Lens Flare v3 -- Overscan, Ring Colour, Ring/Halo, Bloom, Wash, Offsets

**Date:** 2026-11-09
**Status:** Approved design
**Builds on:** v1 (`2026-11-08-lens-flare-design.md`) and v2 elements
(`2026-11-09-lens-flare-elements-design.md`). All earlier hard constraints
apply (one `nuke.tcl()` call, no internal node lookups from Python, no space
inside a single `{{...}}`, temp names never r/g/b/a/x/y/z, gains never
disabled, strict ASCII, no per-frame Python).

Follow-up project (separate spec): a **Lens Aberrations** node (spherical
aberration, field curvature, coma, chromatic aberration, distortion,
vignetting, diffraction, focus shift).

## 1. Overscan

Problem: shapes are drawn on a canvas the size of the (working) frame, so
large shapes are capped and cropped, and FFT convolution wraps light that
leaves one edge onto the opposite edge.

- New knob **Overscan** (Lens tab, % of frame per side, 0-100, default 25).
- Down/up scale: `flareDown` is a `Reformat to box`, `resize distort`,
  `box = floor(highlights.width*RES+0.5) x floor(highlights.height*RES+0.5)`;
  `flareUp` is a `Reformat to box`, `resize distort`, back to
  `highlights.width x highlights.height`. A `type scale` Reformat floors the
  working format (2048x858 at Quarter -> 512x214) but scales the content by
  exactly RES, so the format no longer matched the content and the
  up-scale could not invert it. With both as distorts, the content scale is
  the format ratio and `flareUp` undoes `flareDown` exactly at any size.
- After `flareDown`, the highlight stream is padded symmetrically:
  `Reformat to box`, `box_width = input.width + 2*floor(input.width*OS)`,
  same for height, `resize none`, `center true`, black outside
  (OS = Overscan/100). `$hl` is the padded stream.
- Pad offsets: `padx = floor(flareDown.width*OS)`,
  `pady = floor(flareDown.height*OS)` (node-name references inside the
  Group are expression syntax, not Python node access).
- **flareGeo NoOp.** Built in the same `nuke.tcl()` call, right after the
  pad (`NoOp { name flareGeo addUserKnob {20 User} addUserKnob {7 padx}
  padx {{...}} ... }`; TCL `addUserKnob` verified in Nuke 17.1 NC). It
  holds, once per frame instead of per pixel: `padx`, `pady`, `fw`, `fh`
  (`flareDown.width/height`), `cx`, `cy` (optical centre on the padded
  canvas), the animation times `t_<prefix> = frame*<prefix>NoiseSpeed` for
  every coloured prefix and ghosts, `t_shimmer = frame*shimmerSpeed`,
  `t_sparkle = frame*sparkleSpeed`, and the colour balance knobs
  (`w_<prefix>_*`, `bal_<prefix>_<r|g|b>`, section 2). Every other node
  reads them as `flareGeo.<knob>` (the Python constants PADX, PADY, FW, FH,
  CX, CY are these references); `frame` appears nowhere else.
- Static kernels are not re-rendered per frame (measured in Nuke 17.1 NC
  with performance timers): with every speed 0, `irisKernel` and
  `g0Aperture` call counts stay identical from frame 1 to frames 2 and 3
  (Tint and Ramp); with Iris Noise Speed 2 only `irisKernel` re-executes
  each frame while `g0Aperture` stays cached. So no FrameHold is needed:
  Nuke's hash already excludes `frame` when no time term is animated.
- Everything positioned in working px adds the pad: optical centre
  (`opticalCenter.x*flareDown.width/highlights.width+padx`, same for y with
  heights: the real working/plate ratio, which equals RES except for the
  rounding of odd sizes), Lens Orbs dust positions (spread over the
  unpadded frame), Ring/Halo radius (fraction of `flareDown.height`), ghost
  aperture size (px per mm uses `flareDown.width`, not the padded width).
- After all branches are summed, crop back: `Reformat to box`
  `flareDown.width x flareDown.height`, `resize none`, `center true`, then
  `flareUp`, then `Crop { box {{0} {0} {highlights.width}
  {highlights.height}} crop false name flareCrop }`. The Reformat changes only
  the format; without the Crop the overscan stayed in the bbox. With
  `crop false` the bbox equals the frame exactly (`crop true` adds a 1px
  black border, measured -1,-1,642,362).
- The kernel radius cap (`min(width,height)/2-4`) now applies to the padded
  canvas, so shapes up to roughly the frame size fit at 25%.

## 2. Ring colour system

Applies to: Ghosts, Iris, Multi-Iris, Rings, Caustic, Ring/Halo.

Per element (ghosts share one set):
- **Colour Mode**: `Tint` (current behaviour) / `Spectrum` / `Ramp`.
- **Colour Width** (0.05-1, default 0.35): for filled shapes (ghosts, Iris,
  Multi-Iris, Caustic) the fraction of the radius, measured in from the
  edge, that carries the colour; inside it the shape is white. For Rings and
  Ring/Halo it is the fraction of the ring's width the colour band spans
  (default 1 = full width).
- **Spectrum**: physical rainbow across the colour band, violet on the inner
  side to red on the outer side (hue = 0.75*(1-u), HSV -> RGB, u = 0 inner
  .. 1 outer).
- **Ramp**: 4 colour stops (Color knob + position 0-1 each) across u,
  piecewise linear, flat beyond the end stops.
- **Light Colour** (0-1, default 1): 1 = the element takes the light's own
  colour, 0 = the light is treated as white (luminance only).
- **Noise** (0-1, default 0), **Noise Scale** (default 8 = features around
  the shape), **Noise Speed** (default 0 = static): angular noise
  modulating the shape's brightness (and so its colour bands).

Rendering:
- `Tint` mode keeps the existing single Convolve2 (alpha kernel). `Spectrum`
  / `Ramp` use an RGB kernel and three Convolve2 nodes (red, green, blue
  filter channels). A Switch picks the branch; the unused branch is
  disabled, so Tint costs nothing extra.
- Colour is clamped to >= 0 (`max(0,...)`) in the kernel.
- Centre floor: Convolve2 normalize divides each channel by that kernel
  channel's sum, so `CENTRE_FLOOR` (1e-6 on the centre pixels) is added to
  expr0..expr3 of every coloured kernel (alpha only for mono kernels). A
  channel the colour lacks (pure-red ramp -> zero green kernel) then stays
  finite instead of dividing by zero.
- Balance. The per-channel gain of a normalized coloured convolution is
  multiplied by the kernel-weighted mean colour M_c (both Spectrum and
  Ramp; Tint -> 1; never floored, so a missing channel gets gain 0 and no
  faint centre dot). col_c(u) is the same Spectrum/Ramp expression as the
  kernel; cw = clamp(Colour Width,0.05,1).
  - Filled shapes (ghosts, Iris, Multi-Iris, Caustic): white core weight
    (1-cw)^2 (colour 1) plus 8 band samples u_k = (k+0.5)/8 with weight
    2*cw*(1-cw+cw*u_k)/8, M_c = (core + sum w_k col_c(u_k)) / (core + sum
    w_k). Each weight also carries the shape's coverage at radius
    r = 1-cw+cw*u_k (normalised to R): for aperture shapes the angular
    fraction inside the polygon, 1 up to the inscribed radius
    a = (1-Roundness)*cos(pi/n)+Roundness, beyond it
    1-2*acos((1-Roundness)*cos(pi/n)/(r-Roundness))/(2*pi/n); the part of
    the core past a is integrated with 4 samples. Measured cause: with the
    plain disc weights a default 6-blade Iris centre was 1.17 (Ramp) /
    1.30 (Spectrum) off neutral; with the coverage it is 1.007. Caustic
    uses its radial profile 0.12+r^(4*Sharpness) instead (core analytic).
    The weights are flareGeo knobs `w_<prefix>_core`, `w_<prefix>_0..7`,
    `w_<prefix>_sum`, shared by r, g, b.
  - Rings and Ring/Halo (Light mode kernel): Gaussian profile, 16 samples
    d_k = -4+8*(k+0.5)/16 (sigma units), weight exp(-d_k^2/2),
    u = clamp(d_k/(4*cw)+0.5,0,1) (as the kernel's ring band),
    M_c = sum(w col_c(u)) / sum(w).
  - Balances are flareGeo knobs `bal_<prefix>_<r|g|b>`.
- Ring/Halo in Optical Centre mode draws its ring directly (no
  convolution, no normalization), so its colour is applied per pixel and
  its gain uses `(Centre==1 ? balance : 1)`.
- Noise amount is clamped to 0..1; each slot (ghost n, multi-iris i,
  ring i) adds slot*7.31 to the noise z so slots get their own pattern.

## 3. Ring / Halo (replaces Hoop)

Practical names: Rainbow Ring Flare, Ring / Halo Flare, Orbis / Orbital
Flare.
- **Centre**: `Optical Centre` (Orbital / Rainbow Ring: ring around the
  optical centre, lit by nearby light, as the old Hoop) or `Light` (Halo:
  ring around each light; rendered as a ring kernel convolved with the
  element's Source).
- **Arc** (0-1, default 0.7): Optical Centre mode only. 0 = evenly lit ring
  (frame-wide light average), 1 = only the arc facing the light lights up.
- Radius, Width, Arc Falloff as before; plus the ring colour system and
  Offset.
- Even field: the frame-wide Blur (size 4 x frame width) is scaled by
  comp = (4*FW/(EVEN_REF_PX*RES))^2, EVEN_REF_PX = 600 plate px, a fixed
  reference, so the even field no longer changes with Arc Falloff (the
  default Arc Falloff equals the reference, so defaults are unchanged).
  The even Blur is disabled when Arc >= 1 (and when off / Light mode); the
  mix uses `Arc>=1 ? reach : lerp(even*comp, reach, Arc)`, so a disabled
  blur's pass-through is never read.

## 4. Bloom

Soft glow around highlights: sum of three Blurs of the source at Size, 3 x
Size and 9 x Size, weighted 1, Falloff, Falloff^2 and normalized.
Controls: Enable, Intensity, Source, Tint, Size (plate px, default 20),
Falloff (0-1, default 0.5), Offset.

## 5. Overscreen Wash

Frame-wide veil that lifts blacks, scaling with the light in frame:
lerp(near-uniform field (Blur size 4 x frame), field biased toward the
light (Blur size Spread), Bias). The even field is scaled by
comp = (4*FW/(WASH_REF_PX*RES))^2, WASH_REF_PX = 800 plate px (fixed; it
no longer depends on Spread; default Spread equals it). washEven is
disabled at Bias >= 1, washNear at Bias <= 0 (both also when off); the mix
picks the single field at those ends.
Controls: Enable, Intensity, Source, Tint, Spread (plate px, default 800),
Bias (0-1, default 0.5), Offset.

## 6. Offset

Every element (and Ghosts, Starburst as groups) gets an **Offset** XY knob
(plate px, default 0,0) applied as a translate on its final output, for art
direction on top of the physical placement. The 16 ghost slots are summed
in their own chain and the ghosts Offset is one Transform on that sum.

Placement by family (unchanged physics, documented in the README):
- Centred elements (Streak, Spike Ball, Shimmer, Sparkle, Glint, Starburst,
  Bloom, Ring/Halo in Light mode) sit on the light.
- Axial elements (Ghosts, Iris, Multi-Iris, Rings, Caustic, Ring/Halo in
  Optical Centre mode) move with both the light and the Optical Centre.
- Lens Orbs and Wash are fixed to the glass / frame.

## 7. Panel

- Optical Centre moves to the Elements tab, above Hotspot Radius.
- Overscan goes in the Lens tab, Output section, next to Flare Resolution.
- Element groups: Bloom and Overscreen Wash added; Hoop renamed Ring / Halo.
- Tooltips: Colour Mode notes Spectrum/Ramp cost 3x the render time of Tint
  for that element; Overscan notes 25% is about 2.25x the canvas area; Ramp
  positions should increase from stop 1 to 4.

## Testing

Plain Python (stub nuke): all existing lint rules; every new knob created
and referenced; every coloured element has both branches with a Switch on
its Colour Mode; every `opticalCenter` use in the TCL includes the pad
offset; coloured kernels floor all four channels; `frame` only on flareGeo
and every `flareGeo.<knob>` reference defined there; balances unfloored
and per shape; Ring/Halo balance only in Light mode; even fields use the
fixed references; noise clamped and per slot; flareCrop after flareUp;
ghosts Offset applied once.

Nuke NC checks (in addition to all existing ones):
- Overscan: an Iris whose shape extends past the frame edge is not cut at
  the working-canvas edge (with Overscan 0 vs 25, the in-frame part next to
  the edge is unchanged or brighter, and no light appears at the opposite
  edge from FFT wrap).
- Optical centre and Offset: moving Optical Centre moves axial elements by
  the predicted amount at Overscan 25; Offset (100, 0) moves an element's
  peak by 100 plate px.
- Spectrum: on a Ring, the outer side is redder (r/b higher) than the inner
  side. Ramp: with stops red/green/blue/white, sampled colours follow the
  stops. Noise > 0 makes brightness vary around the ring; Speed > 0 changes
  it between frames, Speed 0 does not.
- Light Colour: a red light gives a red Iris at 1 and a neutral Iris at 0.
- Ring/Halo: Centre = Light draws a ring around the light (ring radius
  sample brighter than the light's inner gap); Arc 0 vs 1 changes the ratio
  of facing arc to opposite arc.
- Bloom and Wash: off adds exactly 0; on lights near the light; Wash at
  Bias 0 is near-uniform across the frame and rises with more light.
- Zero-sum colour kernels: pure-red ramp on Rings (Ramp mode) and on an
  Iris at Colour Width 1: g and b finite and |v| < 1e-6, r > 0.
- Balance: Ramp and Spectrum Iris (and Caustic) centre, inside the white
  core, neutral: max/min(r,g,b) < 1.1.
- Ring/Halo Optical Centre, pure-green ramp: g > 0, r and b 0, facing-arc
  brightness within 2x of Tint mode.
- Wash Bias 0: far corner equal (< 1%) for Spread 100 vs 3000; Ring/Halo
  Arc 0 equal for Arc Falloff 100 vs 3000.
- Flare Only bbox within the format (0, 0, 640, 360).
- Ring/Halo Optical Centre with all stops (0, 0.5, 0): g = 0.4..0.6 x Tint
  (double application of the colour would give ~0.25), r and b 0.
- Neutral Iris core also at 3 and 12 blades, roundness 0 and 1.
- `tests/nuke_flare_odd_check.py`: 2048x858 at Quarter, bbox equals the
  format exactly and the Iris brightness-weighted centroid is within 3
  plate px of c + Position*(p - c) for two optical centres.
- All earlier checks still pass.

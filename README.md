Sid Nuke Tools
==============

Contents
--------
sid_match_tools.py   - Neutralize, Match Black, Match White, Match Colour
sid_edge_extend.py   - Alpha Edge
sid_edge_blur2.py    - Edge Extend Blur
sid_light_wrap2.py   - Light Wrap
sid_lens_flare.py    - Lens Flare (needs sid_lens_optics.py and
                       sid_flare_elements.py next to it)
menu.py              - registers all of the above under Nodes > Sid

Install
-------
1. Copy this whole folder's contents into your Nuke user directory
   (the folder already on NUKE_PATH, usually ~/.nuke), or any folder
   you add to NUKE_PATH.
2. If you already have a menu.py there, merge the registration lines from this
   one into it instead of overwriting your existing file.
3. Restart Nuke. Nodes > Sid will list all the tools.

Match Tools (sid_match_tools.py)
---------------------------------
Each node takes Source (input 0), Target (input 1), and an optional
Mask (input 2).

- Neutralize    : matches Source's tonal bands to Target's band
                   mean/stddev.
- Match Black    : two-point affine solve pinned at white, matching
                   Source's dark point to Target's.
- Match White    : two-point affine solve pinned at black, matching
                   Source's bright point to Target's.
- Match Colour   : per-channel quantile/histogram match of Source to
                   Target.

Common controls on all four:
- Mode (Live/Locked): Live re-samples automatically when inputs or
  key knobs change; Locked only updates when you click Set Reference.
- Analyze: re-runs the match now.
- Reference Frame + Set Reference: pick a specific frame of Target to
  lock onto.
- Reset: clears the current match back to neutral.
- Mask Applies To (Target/Source/Both): when a Mask is connected,
  restricts which side's sampling is weighted by the mask.
- View Mask: swaps the Output to show the raw Mask input, for
  checking coverage.
- Clamp (Min/Max per channel, plus an All multiplier): limits the
  corrected output range.
- Range: shows the lowest/highest sampled values on the node.

Neutralize and Match Colour also have a Preserve Saturation toggle
(off by default). With it off, both match per channel exactly as
before. With it on, brightness and saturation-strength are matched as
two separate quantities, which stays correct even when Target has had
its Saturation or Gamma adjusted after the original grade.

Alpha Edge (sid_edge_extend.py)
-------------------------------
Alpha-only processor - grow/shrink (in sub-pixel 0.1 px steps), edge smoothing, contrast, and
blur. Takes a Mask input and a Mix slider for standard masked/partial
application.


Edge Extend Blur (sid_edge_blur2.py)
--------------------------------------
Cleans the RGB edge of a keyed or rotoed element so it blends into a new
background without a dark or bright rim. Alpha is never changed.
Inputs: Source, Sample, Mask, Omit.
- Method: Clean Core Extend, Eroded Inner Ring Sample, or Dark / Bright
  Fringe Kill Only.
- Clean Bias, Clear Dark / Clear White and All-Edge Strength set how much of
  a contaminated edge is replaced. Edge Blend feathers where the cleaned
  zone meets the original.
- Recover Grain + Grain Softness bring the original texture back, no blur.
- Use Sample (checkbox): draw an area on the Sample input and its colour is
  mixed over Clean Core only inside that area (a KeyMix).
- Omit: connect an alpha to skip the edge clean there.
- Show Edge Matte (checkbox) shows the treated band. Edge Blur is a final
  colour-only blur in 0.1 steps.
- Premult Input / Output are off by default.

Light Wrap (sid_light_wrap2.py)
---------------------------------
Light wrap that follows the shape of the foreground, built on normals.
Inputs: FG, BG, Mask, Normals (optional).
- Normals cover the whole FG. Normal Source: Alpha Dome (silhouette only),
  Image Detail + Dome (default: the FG's own luminance, bright = raised, adds
  the surface detail) or Image Detail Only. Normal Blur, Normal Smooth,
  Normal Height, Detail Strength, Detail Smoothing, Flip Normals and
  Normal Strength adjust them; View Normals shows them as colour.
- The wrap colour is the diffuse BG picked up along the normal (BG Reach).
- Coverage: Edge Only (Edge Width), Grow Inwards (Wrap Depth) or Whole
  Object. Controls that do nothing in the current mode are greyed out.
  Wrap Softness smooths where the wrap ends.
- Relight (checkbox): the same normals light the FG with a direction,
  elevation, colour, intensity, softness and ambient; the wrap is applied on
  top of the relit FG.
- Output Mode: FG Only, FG Over BG, LightWrap Only (solo on black) or
  Normals (raw, -1..1 float RGB with the FG alpha, for use in other relight
  setups). Use Normals Input swaps in a normal map of your own (encoded 0..1
  or raw -1..1, green = up).
- Blend Modes: Add, Screen, SoftLight, BG Bleed. Premult Input / Output are
  off by default.
- The normals come from the alpha and the image luminance, not true depth;
  a real normal map on the Normals input is more accurate.

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

Lens Flare panel tabs
- Lens: lens, F-Stop, sensor, source threshold/gain, aperture, output.
  Overscan % (default 25) pads the working canvas so shapes are not
  cropped at the frame edge and light does not wrap across it.
- Ghosts & Glare: Ghosts, Starburst and Veiling Glare, each with its
  own on/off switch. Starburst shape: Length (plate px at f/4, no
  minimum), Thickness, Falloff (1 soft tail, 2 Gaussian, higher = hard
  needle), Rotation, Chromatic Spread, Irregularity + Seed.
- Elements: Optical Centre, Hotspot Radius, then the elements, all off
  by default. Each has Enable, Intensity, Tint, Offset and Source:
    All highlights - every bright pixel drives the element.
    Hotspot        - one point per light (found every frame with native
                     nodes; set Hotspot Radius to at least the radius of
                     your biggest light). Keeps rays crisp on big lights.
  Centred on each light (they follow the light, not the optical centre):
    Streak      anamorphic streak (Length, Thickness, Angle, Falloff)
    Spike Ball  many thin random rays (Rays, Length, Variation, Seed)
    Shimmer     flickering fine rays (Rays, Length, Speed, Seed)
    Sparkle     small twinkling star (Points 4/6/8, Size, Twinkle Speed)
    Glint       intense core + cross spikes (Size, Spike Length, Angle)
    Bloom       soft multi-scale glow (Size, Falloff)
  Along the flare axis (move with both the light and the Optical Centre;
  Position: 1 = at the light, 0 = optical centre, -1 = mirror point):
    Iris        one aperture-shaped ghost (follows Blades/Roundness)
    Multi-Iris  up to 8 aperture ghosts spread along the axis
    Rings       up to 4 thin circular ghosts
    Caustic     ghost with a bright cusped edge
  Ring / Halo (Rainbow Ring, Ring / Halo, Orbis / Orbital flare):
    Centre = Optical Centre: a ring around the optical centre, lit from
    the side facing the light (Arc 0 = evenly lit, 1 = facing arc only).
    Centre = Light: a halo ring around each light.
  Fixed to the glass / frame:
    Lens Orbs        dust on the front glass that lights up near a light
    Overscreen Wash  frame-wide veil that lifts the blacks (Spread, Bias)
  Ring colour (Ghosts, Iris, Multi-Iris, Rings, Caustic, Ring / Halo):
    Colour Mode Tint / Spectrum (rainbow: violet inside, red outside) /
    Ramp (4 colour stops), Colour Width, Light Colour (1 = take the
    light's colour), Noise + Noise Scale + Noise Speed.
  Use Offset (per element, off by default) shows that element's Offset
  handle and moves it in plate px on top of its physical position; the
  handles of elements you are not moving stay hidden.

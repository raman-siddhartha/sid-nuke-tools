Sid Nuke Tools
==============

Contents
--------
sid_match_tools.py   - Neutralize, Match Black, Match White, Match Colour
sid_edge_extend.py   - Edge Extend, Alpha Edge, Light Wrap
sid_edge_extend_blur.py - Edge Extend Blur (Edge Extend + final edge blur)
sid_lens_flare.py    - Lens Flare (needs sid_lens_optics.py next to it)
menu.py              - registers all of the above under Nodes > Sid

Install
-------
1. Copy this whole folder's contents into your Nuke user directory
   (the folder already on NUKE_PATH, usually ~/.nuke), or any folder
   you add to NUKE_PATH.
2. If you already have a menu.py there, merge the eight lines from this
   one into it instead of overwriting your existing file.
3. Restart Nuke. Nodes > Sid will list all nine tools.

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

Edge Extend Tools (sid_edge_extend.py)
----------------------------------------
- Edge Extend  : pulls clean colour over a rough alpha edge and
                  suppresses dark/bright fringing. Four edge-sampling
                  methods, with an optional Roto Sample input to
                  source clean colour from a separate plate/roto.
- Alpha Edge   : alpha-only processor - grow/shrink, edge smoothing,
                  contrast, and blur.
- Light Wrap   : wraps background light around a foreground edge, or
                  composites FG over BG directly, with adjustable
                  intensity, depth, diffusion, and falloff.

All three take a Mask input and a Mix slider for standard masked/
partial application.

Edge Extend Blur (sid_edge_extend_blur.py)
--------------------------------------------
A separate copy of Edge Extend (the original is unchanged) with one
extra control, Edge Blur, applied as the very last step - after Mask
& Mix. It blurs RGB only, inside a band around the alpha edge; the
output alpha is never changed and no colour spills outside the matte.
Edge Blur moves in 0.1 steps; 0 = off.


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

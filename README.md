Sid Nuke Tools
==============

Contents
--------
sid_match_tools.py   - Neutralize, Match Black, Match White, Match Colour
sid_edge_extend.py   - Edge Extend, Alpha Edge, Light Wrap
menu.py              - registers all of the above under Nodes > Sid

Install
-------
1. Copy this whole folder's contents into your Nuke user directory
   (the folder already on NUKE_PATH, usually ~/.nuke), or any folder
   you add to NUKE_PATH.
2. If you already have a menu.py there, merge the four lines from this
   one into it instead of overwriting your existing file.
3. Restart Nuke. Nodes > Sid will list all seven tools.

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

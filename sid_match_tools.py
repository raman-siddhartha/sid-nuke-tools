# Sid match-grade tools for Nuke -- Neutralize / Match Black / Match White.
#
# Pure native nodes (Grade, Expression) plus Python for the one-time
# per-frame statistics sampling. No Blinkscript, no compiled plugin.
#
# Every child node is wired from its own Python variable at build time,
# never looked up by name afterward. Each internal node's relevant knobs
# are expression-linked ("parent.foo") to same-named knobs on the Group
# itself. The Analyze / Set Reference buttons only ever touch
# nuke.thisNode() (the group), its .input(0)/.input(1), and knob values
# on the group -- this avoids Nuke non-commercial's 10-result cap on
# nuke.toNode()/nuke.allNodes().
#
# Install: drop this file somewhere on NUKE_PATH (e.g. ~/.nuke) and add to
# menu.py:
#     import sid_match_tools
#     sid_match_tools.install_menu()
# Nodes > Sid then has Neutralize / Match Black / Match White.
#
# Each gizmo has Mode (Live/Locked), Mix, Analysis Size (proxy resolution
# used only for statistics, default 64), Analyze (button: re-samples now),
# and Set Reference (Locked mode: samples target now and caches it).
# Neutralize also has Bands (1/3/5) -- after changing it, click Analyze
# once to rebuild the band layout.
#
# Known approximation: Neutralize blends tonal bands by each pixel's RAW
# LUMA rather than its percentile rank within the frame (a per-pixel rank
# needs a global sort, which has no per-pixel Expression-node equivalent).
# Exact when src/target have similar overall exposure; bands=1 (no
# banding) is exact either way. Match Black / Match White are exact ports
# (their math is a plain 2-point affine -- exactly what Nuke's native
# Grade node computes via its blackpoint/black, whitepoint/white knobs).
#
# Strict ASCII.

import nuke

LUMA_R, LUMA_G, LUMA_B = 0.2126, 0.7152, 0.0722
STD_EPS = 1e-4
MAX_BANDS = 5


def _create_sid_group(name):
    """Creates the Group at the current node graph cursor position and wires
    Source (input 0) to whatever node was selected beforehand, if any."""
    selected = None
    try:
        selected = nuke.selectedNode()
    except ValueError:
        pass
    try:
        group = nuke.createNode("Group", inpanel=False)
        group.setName(name)
    except Exception:
        group = nuke.nodes.Group(name=name)
    if selected:
        try:
            group.setInput(0, selected)
        except Exception:
            pass
    return group


# -- Shared stats -------------------------------------------------------------

def _luma(px):
    return LUMA_R * px[0] + LUMA_G * px[1] + LUMA_B * px[2]


def _has_channel(node, ch):
    """node.channels() returns fully-qualified names like 'rgba.alpha',
    never the bare 'alpha' -- so `"alpha" in node.channels()` is always
    False even when alpha genuinely exists. This checks the actual
    layer-qualified form."""
    return any(c == ch or c.endswith("." + ch) for c in node.channels())


def _mask_for(group, side):
    """Returns the connected Mask input only if the gizmo's maskApplyTo
    switch ("Target"/"Source"/"Both") says this `side` ("Source" or
    "Target") should be restricted by it; None otherwise, meaning that
    side samples the full frame unmasked as before."""
    mode = group["maskApplyTo"].value()
    if mode == side or mode == "Both":
        return group.input(2)
    return None


def _sample_plane(node, size, mask_node=None):
    """Render `node` through a `size`x`size` proxy Reformat and read it back
    as a flat list of (r, g, b, w) floats via nuke.sample() -- `w` is the
    per-pixel WEIGHT already consumed throughout `_weighted_stats` /
    `_weighted_percentile_anchor` / `_band_stats` (normally the plate's
    own alpha, or 1.0 with none). When `mask_node` is connected, its luma
    is multiplied into that same weight, at the same proxy resolution and
    pixel grid as `node` -- so a masked-out pixel simply carries zero
    weight into every stat, with no change to the stats math itself.
    Creating and deleting a node is construction, not graph retrieval, so
    it is not subject to the NC node-lookup cap."""
    if node is None:
        return []
    w = h = max(8, int(size))
    rz = nuke.nodes.Reformat(inputs=[node], type="to box",
                              box_width=w, box_height=h, box_fixed=True,
                              resize="fill", black_outside=True)
    mz = None
    if mask_node is not None:
        mz = nuke.nodes.Reformat(inputs=[mask_node], type="to box",
                                  box_width=w, box_height=h, box_fixed=True,
                                  resize="fill", black_outside=True)
    try:
        has_alpha = _has_channel(rz, "alpha")
        # Many mask sources (Roto, etc.) carry only an alpha channel, no
        # RGB -- sampling "r"/"g"/"b" on those throws "unable to sample
        # node for given channel". Prefer the mask's own alpha (the
        # normal convention for a matte); only fall back to RGB luma
        # when there genuinely is no alpha to read.
        mask_has_alpha = mz is not None and _has_channel(mz, "alpha")
        mask_has_rgb = mz is not None and _has_channel(mz, "red")
        pixels = []
        for y in range(h):
            for x in range(w):
                sx, sy = x + 0.5, y + 0.5
                r = nuke.sample(rz, "r", sx, sy) or 0.0
                g = nuke.sample(rz, "g", sx, sy) or 0.0
                b = nuke.sample(rz, "b", sx, sy) or 0.0
                wt = (nuke.sample(rz, "a", sx, sy) or 0.0) if has_alpha else 1.0
                if mz is not None:
                    if mask_has_alpha:
                        wt *= nuke.sample(mz, "a", sx, sy) or 0.0
                    elif mask_has_rgb:
                        mr = nuke.sample(mz, "r", sx, sy) or 0.0
                        mg = nuke.sample(mz, "g", sx, sy) or 0.0
                        mb = nuke.sample(mz, "b", sx, sy) or 0.0
                        wt *= _luma((mr, mg, mb, 1.0))
                pixels.append((r, g, b, wt))
        return pixels
    finally:
        nuke.delete(rz)
        if mz is not None:
            nuke.delete(mz)


def _sample_plane_at_frame(node, size, frame, mask_node=None):
    """Same as `_sample_plane`, but samples at an arbitrary frame instead
    of the current one -- moves the playhead there, samples, then puts
    it back exactly where it was."""
    cur = nuke.frame()
    try:
        nuke.frame(frame)
        return _sample_plane(node, size, mask_node)
    finally:
        nuke.frame(cur)


def _weighted_percentile_anchor(pixels, percent, want_darkest):
    by_luma = sorted(pixels, key=_luma)
    total_w = sum(px[3] for px in pixels)
    if total_w <= 0.0:
        return (0.0, 0.0, 0.0)
    target_w = total_w * max(0.0, min(100.0, percent)) / 100.0
    seq = by_luma if want_darkest else list(reversed(by_luma))
    acc_w = sum_w = sum_r = sum_g = sum_b = 0.0
    for px in seq:
        if acc_w >= target_w:
            break
        w = px[3]
        acc_w += w
        sum_w += w
        sum_r += w * px[0]
        sum_g += w * px[1]
        sum_b += w * px[2]
    if sum_w <= 0.0:
        return (0.0, 0.0, 0.0)
    return (sum_r / sum_w, sum_g / sum_w, sum_b / sum_w)


def _weighted_stats(pixels):
    total_w = sum(px[3] for px in pixels)
    if total_w <= 0.0:
        return (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
    mean = [sum(px[3] * px[c] for px in pixels) / total_w for c in range(3)]
    var = [sum(px[3] * (px[c] - mean[c]) ** 2 for px in pixels) / total_w
           for c in range(3)]
    std = [v ** 0.5 for v in var]
    return tuple(mean), tuple(std)


def _tent_weight(y, center, spacing):
    return max(0.0, 1.0 - abs(y - center) / spacing)


def _band_centers(bands):
    spacing = 1.0 / bands
    return [(i + 0.5) * spacing for i in range(bands)]


def _band_stats(pixels, bands):
    if bands <= 1:
        return [_weighted_stats(pixels)]
    centers = _band_centers(bands)
    spacing = 1.0 / bands
    global_stats = _weighted_stats(pixels)
    out = []
    for center in centers:
        weighted = [(px[0], px[1], px[2],
                     px[3] * _tent_weight(_luma(px), center, spacing))
                    for px in pixels]
        if sum(px[3] for px in weighted) > 1e-6:
            out.append(_weighted_stats(weighted))
        else:
            out.append(global_stats)
    return out


def _chroma_mag(px):
    lum = _luma(px)
    dr, dg, db = px[0] - lum, px[1] - lum, px[2] - lum
    return (dr * dr + dg * dg + db * db) ** 0.5


def _chroma_band_means(pixels, bands):
    pseudo = [(_chroma_mag(px), _chroma_mag(px), _chroma_mag(px), px[3]) for px in pixels]
    return [mean[0] for mean, _std in _band_stats(pseudo, bands)]


def _solve_two_point(pivot, anchor_src, anchor_tgt):
    a, b = [1.0, 1.0, 1.0], [0.0, 0.0, 0.0]
    for c in range(3):
        denom = pivot[c] - anchor_src[c]
        a[c] = (pivot[c] - anchor_tgt[c]) / denom if abs(denom) > STD_EPS else 1.0
        b[c] = anchor_tgt[c] - a[c] * anchor_src[c]
    return a, b



def _add_credit_knob(group):
    group.addKnob(nuke.Text_Knob("creditDivider", "", ""))   # empty label+value = a real divider rule
    group.addKnob(nuke.Text_Knob("credit", "", "Made by Sid (www.sidmanvfx.com)"))
    import base64
    sig = nuke.Text_Knob("_sig", "", base64.b64decode("TWFkZSBieSBTaWQgKHd3dy5zaWRtYW52ZnguY29tKQ==").decode("ascii"))
    sig.setFlag(nuke.INVISIBLE)
    group.addKnob(sig)


def _hidden_double_knobs(names):
    out = []
    for nm in names:
        k = nuke.Double_Knob(nm, nm)
        k.setFlag(nuke.INVISIBLE)
        out.append(k)
    return out


def _link_grade_to_parent(grade):
    """Realize out = a*in + b (per R/G/B) via Grade's native 2-point knobs
    (blackpoint=0 -> black=b, whitepoint=1 -> white=a+b), with every
    component expression-linked to a same-named hidden knob on the parent
    Group (aR/aG/aB/bR/bG/bB) so an Analyze button never has to touch this
    node by name again. Alpha is a fixed identity pass."""
    grade["blackpoint"].setValue([0.0, 0.0, 0.0, 0.0])
    grade["whitepoint"].setValue([1.0, 1.0, 1.0, 1.0])
    grade["black_clamp"].setValue(False)
    grade["white_clamp"].setValue(False)
    for i, ch in enumerate(("R", "G", "B")):
        grade["black"].setExpression("parent.b" + ch, i)
        grade["white"].setExpression("parent.a" + ch + "+parent.b" + ch, i)
    grade["black"].setExpression("0", 3)
    grade["white"].setExpression("1", 3)


def _divider(name):
    return nuke.Text_Knob(name, "", "")   # empty label+value = a real divider rule


def _section_heading(name, label):
    return nuke.Text_Knob(name, label, "")


def _range_info_knobs():
    """A read-only display of the last Analyze's lowest-low/highest-high,
    written directly onto the node's panel on its own row (ENDLINE so
    nothing else shares it), followed by a divider separating it from
    the buttons below."""
    info = nuke.Text_Knob("rangeInfo", "Range", "(not analyzed yet)")
    info.setFlag(nuke.ENDLINE)
    return [info, _divider("divRange")]


def _clamp_knobs():
    """Divider + heading + a checkbox + Clamp Min/Max, same on every
    gizmo. Clamp is off by default (no behaviour change unless turned
    on). Each has a master knob (a MULTIPLIER -- grows/shrinks all
    three RGB values proportionally, starts at 1.0 = no change) plus a
    Color knob underneath for adjusting each channel individually.
    Editing the Color knob directly leaves the master alone. The hidden
    *Prev knobs track the master's last value so each change can be
    turned into a ratio (new/old) rather than an absolute overwrite."""
    en = nuke.Boolean_Knob("clampEnable", "Enable")
    en.setValue(False)
    lo_all = nuke.Double_Knob("clampMinAll", "Clamp Min (All x)")
    lo_all.setValue(1.0)
    lo = nuke.Color_Knob("clampMin", "Clamp Min RGB")
    lo.setValue([0.0, 0.0, 0.0])
    hi_all = nuke.Double_Knob("clampMaxAll", "Clamp Max (All x)")
    hi_all.setValue(1.0)
    hi = nuke.Color_Knob("clampMax", "Clamp Max RGB")
    hi.setValue([1.0, 1.0, 1.0])
    hidden_prev = _hidden_double_knobs(["clampMinAllPrev", "clampMaxAllPrev"])
    for k in hidden_prev:
        k.setValue(1.0)
    # Plain scalar mirror knobs (clampMinR/G/B, clampMaxR/G/B) kept in
    # sync with the Color knobs above by Python, not by a cross-knob
    # expression -- the Clamp node links to THESE via the same proven
    # "scalar knob, explicit channel index" pattern already used for
    # Grade's black/white linking elsewhere in this file, instead of
    # relying on Color-knob sub-channel dot syntax.
    mirrors = _hidden_double_knobs(
        ["clampMinR", "clampMinG", "clampMinB", "clampMaxR", "clampMaxG", "clampMaxB"])
    for k in mirrors:
        k.setValue(0.0 if k.name().startswith("clampMin") else 1.0)
    return ([_divider("divClamp"), _section_heading("clampHeading", "Clamp"),
             en, lo_all, lo, hi_all, hi] + hidden_prev + mirrors +
            [_divider("divRangeTop")])


def _add_clamp_node(upstream, ypos):
    """Per-channel RGB clamp built as an Expression node, not Nuke's
    native Clamp node -- the native Clamp's minimum/maximum knobs turned
    out NOT to support true independent per-channel values (every
    channel ended up following whichever setExpression call landed last),
    so each channel's floor/ceiling is done directly in per-pixel math
    here instead, exactly like Neutralize/Match Colour already do.
    Alpha is left untouched (expr3 unset -> passthrough)."""
    c = nuke.nodes.Expression(name="clampOut")
    c.setInput(0, upstream)
    c.setXYpos(upstream.xpos(), ypos)
    for i, ch in enumerate(("r", "g", "b")):
        c["expr%d" % i].setValue(
            "parent.clampEnable?clamp(%s,parent.clampMin%s,parent.clampMax%s):%s"
            % (ch, ch.upper(), ch.upper(), ch))
    return c


def _add_view_mask_switch(corrected, mask_input, ypos):
    """Switch between the normal corrected output and the raw Mask input,
    so turning on View Mask shows exactly what's being sampled instead
    of guessing from the result."""
    sw = nuke.nodes.Switch(inputs=[corrected, mask_input])
    sw.setXYpos(corrected.xpos(), ypos)
    sw["which"].setExpression("parent.viewMask")
    return sw


def _format_range(label, pixels):
    if not pixels:
        return "%s: no pixels sampled" % label
    lo = min(min(px[0], px[1], px[2]) for px in pixels)
    hi = max(max(px[0], px[1], px[2]) for px in pixels)
    return "%s range: lowest low %.5f  highest high %.5f" % (label, lo, hi)


def _print_range(label, pixels):
    print(_format_range(label, pixels))


def _show_ranges(group, lines):
    """Writes the lowest-low/highest-high report onto the node's own
    panel (not just the Script Editor console)."""
    if "rangeInfo" in group.knobs():
        group["rangeInfo"].setValue("\n".join(lines))


def _auto_clamp_from_target(group, tgt_px):
    """Sets Clamp Min/Max RGB to Target's own per-channel darkest/
    brightest sampled values, so Clamp (once enabled) floors/ceilings
    to what Target actually has rather than a generic 0..1."""
    if not tgt_px:
        return
    mn = [min(px[c] for px in tgt_px) for c in range(3)]
    mx = [max(px[c] for px in tgt_px) for c in range(3)]
    group["clampMin"].setValue(mn)
    group["clampMax"].setValue(mx)
    for i, ch in enumerate(("R", "G", "B")):
        group["clampMin" + ch].setValue(mn[i])
        group["clampMax" + ch].setValue(mx[i])


def _scale_clamp_rgb(group, which):
    """Called when clampMinAll/clampMaxAll (a MULTIPLIER, not an
    absolute value) changes: turns the change into a ratio against its
    own last value and multiplies the corresponding Color knob's three
    channels by it, so the RGB values grow/shrink proportionally
    instead of collapsing to one shared value."""
    all_knob = group["clamp%sAll" % which]
    prev_knob = group["clamp%sAllPrev" % which]
    rgb_knob = group["clamp%s" % which]
    cur = all_knob.value()
    prev = prev_knob.value()
    ratio = cur / prev if prev != 0 else 1.0
    new_vals = [rgb_knob.value(i) * ratio for i in range(3)]
    rgb_knob.setValue(new_vals)
    for i, ch in enumerate(("R", "G", "B")):
        group["clamp%s%s" % (which, ch)].setValue(new_vals[i])
    prev_knob.setValue(cur)


def _sync_clamp_mirror(group, which):
    """Called when clampMin/clampMax (the Color knob) is edited directly
    in the UI: copies its three channel values into the scalar mirror
    knobs the Clamp node actually links to."""
    rgb_knob = group["clamp%s" % which]
    for i, ch in enumerate(("R", "G", "B")):
        group["clamp%s%s" % (which, ch)].setValue(rgb_knob.value(i))


def _install_live_refresh(group, analyze_fn_name, extra_knobs=(), setref_fn_name=None):
    """Mode, input-connection changes, and now any of `extra_knobs` (the
    gizmo's own analysis-affecting params -- percent/bands/analysisSize)
    all re-run the analysis automatically, so adjusting any of those
    doesn't need a manual Analyze click. What is deliberately NOT included:
    a per-frame/time trigger -- re-running the pixel-sampling loop on every
    single frame during playback or scrubbing would stutter it; Analyze
    stays a manual click for "I moved to a different shot" type changes.
    `refFrame` (when `setref_fn_name` is given) is the one exception:
    typing a frame number directly into that box re-samples the
    reference at that frame, an alternate path to clicking Set
    Reference."""
    # Mode-aware: switching TO Live re-samples target live; switching TO
    # Locked uses whatever was last cached by Set Reference, same contract
    # as pressing those buttons directly -- a mode flip was wrongly always
    # forcing a live re-sample regardless of which way it flipped.
    watched = ("mode",) + tuple(extra_knobs)
    refframe_clause = (
        "elif k is not None and k.name() == 'refFrame':\n"
        "    _s.%s(g, True)\n" % setref_fn_name) if setref_fn_name else ""
    script = (
        "import sid_match_tools as _s\n"
        "k = nuke.thisKnob()\n"
        "g = nuke.thisNode()\n"
        "if k is not None and k.name() == 'clampMinAll':\n"
        "    _s._scale_clamp_rgb(g, 'Min')\n"
        "elif k is not None and k.name() == 'clampMaxAll':\n"
        "    _s._scale_clamp_rgb(g, 'Max')\n"
        "elif k is not None and k.name() == 'clampMin':\n"
        "    _s._sync_clamp_mirror(g, 'Min')\n"
        "elif k is not None and k.name() == 'clampMax':\n"
        "    _s._sync_clamp_mirror(g, 'Max')\n"
        + refframe_clause +
        "if k is not None and k.name() in %r:\n"
        "    _s.%s(g, g['mode'].value() == 'Live')\n" % (watched, analyze_fn_name))
    group["knobChanged"].setValue(script)
    group["inputChange"].setValue(
        "import sid_match_tools as _s\n"
        "_s.%s(nuke.thisNode(), True)\n" % analyze_fn_name)


# -- Match Black ----------------------------------------------------------

def _mb_analyze(group, use_live_target):
    size = group["analysisSize"].value()
    pct = group["percent"].value()
    src_px = _sample_plane(group.input(0), size, _mask_for(group, "Source"))
    lines = [_format_range("MatchBlack src", src_px)]

    # Pivot pinned to literal white (1.0), not a sampled near-white
    # pixel -- a sampled pivot sits slightly below true white whenever
    # the footage has no pixel exactly at 1.0, so real white (and
    # anything near it) would still drift along the resulting slope.
    # Pinning it to 1.0 exactly guarantees white never moves, only
    # black does (same "Lift" shape: out(1)=1 always, regardless of a).
    src_pivot = (1.0, 1.0, 1.0)
    src_black = _weighted_percentile_anchor(src_px, pct, True)

    if use_live_target:
        tgt_px = _sample_plane(group.input(1), size, _mask_for(group, "Target"))
        _auto_clamp_from_target(group, tgt_px)
        lines.append(_format_range("MatchBlack target", tgt_px))
        tgt_black = _weighted_percentile_anchor(tgt_px, pct, True)
    else:
        tgt_black = (group["refR"].value(), group["refG"].value(), group["refB"].value())

    a, b = _solve_two_point(src_pivot, src_black, tgt_black)
    group["aR"].setValue(a[0]); group["aG"].setValue(a[1]); group["aB"].setValue(a[2])
    group["bR"].setValue(b[0]); group["bG"].setValue(b[1]); group["bB"].setValue(b[2])
    for l in lines:
        print(l)
    _show_ranges(group, lines)


def _mb_set_reference(group, use_frame_from_box=False):
    size = group["analysisSize"].value()
    pct = group["percent"].value()
    if use_frame_from_box:
        frame = int(round(group["refFrame"].value()))
        tgt_px = _sample_plane_at_frame(group.input(1), size, frame, _mask_for(group, "Target"))
    else:
        frame = int(round(nuke.frame()))
        tgt_px = _sample_plane(group.input(1), size, _mask_for(group, "Target"))
        group["refFrame"].setValue(frame)
    _auto_clamp_from_target(group, tgt_px)
    print(_format_range("MatchBlack target (reference)", tgt_px))
    tb = _weighted_percentile_anchor(tgt_px, pct, True)
    group["refR"].setValue(tb[0]); group["refG"].setValue(tb[1]); group["refB"].setValue(tb[2])
    _mb_analyze(group, use_live_target=False)


def _mb_reset(group):
    group["mode"].setValue("Live")
    group["maskApplyTo"].setValue("Target")
    group["viewMask"].setValue(False)
    group["percent"].setValue(1.0)
    group["mix"].setValue(1.0)
    group["analysisSize"].setValue(64)
    group["clampEnable"].setValue(False)
    group["clampMinAll"].setValue(1.0)
    group["clampMinAllPrev"].setValue(1.0)
    group["clampMin"].setValue([0.0, 0.0, 0.0])
    group["clampMaxAll"].setValue(1.0)
    group["clampMaxAllPrev"].setValue(1.0)
    group["clampMax"].setValue([1.0, 1.0, 1.0])
    for ch in ("R", "G", "B"):
        group["clampMin" + ch].setValue(0.0)
        group["clampMax" + ch].setValue(1.0)
    group["rangeInfo"].setValue("(not analyzed yet)")
    group["refFrame"].setValue(1)
    for ch in ("R", "G", "B"):
        group["a%s" % ch].setValue(1.0)
        group["b%s" % ch].setValue(0.0)
        group["ref%s" % ch].setValue(0.0)


def make_match_black():
    group = _create_sid_group("MatchBlack")
    with group:
        in_src = nuke.nodes.Input(name="Source"); in_src.setXYpos(0, 0)
        in_tgt = nuke.nodes.Input(name="Target"); in_tgt.setXYpos(150, 0)
        in_mask = nuke.nodes.Input(name="Mask"); in_mask.setXYpos(300, 0)
        xform = nuke.nodes.Grade(name="xform")
        xform.setInput(0, in_src)
        xform.setXYpos(0, 100)

        mix_merge = nuke.nodes.Dissolve(name="mixOut")
        mix_merge.setInput(0, in_src)
        mix_merge.setInput(1, xform)
        mix_merge["which"].setExpression("parent.mix")
        mix_merge.setXYpos(0, 200)

        clamp_node = _add_clamp_node(mix_merge, 300)
        view_switch = _add_view_mask_switch(clamp_node, in_mask, 350)
        out = nuke.nodes.Output()
        out.setInput(0, view_switch)
        out.setXYpos(0, 400)

        mode_k = nuke.Enumeration_Knob("mode", "Mode", ["Live", "Locked"])
        mask_apply_k = nuke.Enumeration_Knob("maskApplyTo", "Mask Applies To", ["Target", "Source", "Both"])
        mask_apply_k.setValue("Target")
        view_mask_k = nuke.Boolean_Knob("viewMask", "View Mask")
        view_mask_k.setValue(False)
        pct_k = nuke.Double_Knob("percent", "Black %"); pct_k.setRange(0.0, 100.0); pct_k.setValue(1.0)
        mix_k = nuke.Double_Knob("mix", "Mix"); mix_k.setRange(0.0, 1.0); mix_k.setValue(1.0)
        size_k = nuke.Int_Knob("analysisSize", "Analysis Size"); size_k.setValue(64)
        hidden = _hidden_double_knobs(["aR", "aG", "aB", "bR", "bG", "bB", "refR", "refG", "refB"])
        for k in hidden:
            if k.name() in ("aR", "aG", "aB"):
                k.setValue(1.0)
        analyze_btn = nuke.PyScript_Knob(
            "analyze", "Analyze",
            "import sid_match_tools; sid_match_tools._mb_analyze(nuke.thisNode(), True)")
        analyze_btn.setFlag(nuke.STARTLINE)
        setref_btn = nuke.PyScript_Knob(
            "setref", "Set Reference",
            "import sid_match_tools; sid_match_tools._mb_set_reference(nuke.thisNode())")
        refframe_k = nuke.Int_Knob("refFrame", "Reference Frame")
        refframe_k.setValue(1)
        refframe_k.setFlag(nuke.STARTLINE)
        refframe_k.setTooltip(
            "Type a frame number to sample the reference from that frame "
            "directly, or click Set Reference to sample the current "
            "frame (which then updates this box to match).")
        reset_btn = nuke.PyScript_Knob(
            "reset", "Reset",
            "import sid_match_tools; sid_match_tools._mb_reset(nuke.thisNode())")
        reset_btn.setFlag(nuke.STARTLINE)
        for k in ([mode_k, mask_apply_k, view_mask_k, pct_k, mix_k, size_k] + hidden + _clamp_knobs() +
                  _range_info_knobs() + [analyze_btn, refframe_k, setref_btn, reset_btn]):
            group.addKnob(k)
        _add_credit_knob(group)

        _link_grade_to_parent(xform)
        _install_live_refresh(group, "_mb_analyze", extra_knobs=("percent", "analysisSize", "maskApplyTo"),
                               setref_fn_name="_mb_set_reference")

    group["label"].setValue("[value mode] [value percent]%")
    # Deliberately NOT auto-analyzing here: at this point nothing real is
    # wired to Input1/Input2 yet (the node was just created), so sampling
    # now would bake in a degenerate result. The inputChange hook
    # (_install_live_refresh) runs the real analysis once actual footage
    # gets connected; until then the defaults above are a safe identity.
    return group


# -- Match White (symmetric) -----------------------------------------------

def _mw_analyze(group, use_live_target):
    size = group["analysisSize"].value()
    pct = group["percent"].value()
    src_px = _sample_plane(group.input(0), size, _mask_for(group, "Source"))
    lines = [_format_range("MatchWhite src", src_px)]

    # Pivot pinned to literal black (0.0), not a sampled near-black
    # pixel -- same reasoning as Match Black's white pivot, mirrored:
    # guarantees black never moves, only white does.
    src_pivot = (0.0, 0.0, 0.0)
    src_white = _weighted_percentile_anchor(src_px, pct, False)

    if use_live_target:
        tgt_px = _sample_plane(group.input(1), size, _mask_for(group, "Target"))
        _auto_clamp_from_target(group, tgt_px)
        lines.append(_format_range("MatchWhite target", tgt_px))
        tgt_white = _weighted_percentile_anchor(tgt_px, pct, False)
    else:
        tgt_white = (group["refR"].value(), group["refG"].value(), group["refB"].value())

    a, b = _solve_two_point(src_pivot, src_white, tgt_white)
    group["aR"].setValue(a[0]); group["aG"].setValue(a[1]); group["aB"].setValue(a[2])
    group["bR"].setValue(b[0]); group["bG"].setValue(b[1]); group["bB"].setValue(b[2])
    for l in lines:
        print(l)
    _show_ranges(group, lines)


def _mw_set_reference(group, use_frame_from_box=False):
    size = group["analysisSize"].value()
    pct = group["percent"].value()
    if use_frame_from_box:
        frame = int(round(group["refFrame"].value()))
        tgt_px = _sample_plane_at_frame(group.input(1), size, frame, _mask_for(group, "Target"))
    else:
        frame = int(round(nuke.frame()))
        tgt_px = _sample_plane(group.input(1), size, _mask_for(group, "Target"))
        group["refFrame"].setValue(frame)
    _auto_clamp_from_target(group, tgt_px)
    print(_format_range("MatchWhite target (reference)", tgt_px))
    tw = _weighted_percentile_anchor(tgt_px, pct, False)
    group["refR"].setValue(tw[0]); group["refG"].setValue(tw[1]); group["refB"].setValue(tw[2])
    _mw_analyze(group, use_live_target=False)


def _mw_reset(group):
    group["mode"].setValue("Live")
    group["maskApplyTo"].setValue("Target")
    group["viewMask"].setValue(False)
    group["percent"].setValue(1.0)
    group["mix"].setValue(1.0)
    group["analysisSize"].setValue(64)
    group["clampEnable"].setValue(False)
    group["clampMinAll"].setValue(1.0)
    group["clampMinAllPrev"].setValue(1.0)
    group["clampMin"].setValue([0.0, 0.0, 0.0])
    group["clampMaxAll"].setValue(1.0)
    group["clampMaxAllPrev"].setValue(1.0)
    group["clampMax"].setValue([1.0, 1.0, 1.0])
    for ch in ("R", "G", "B"):
        group["clampMin" + ch].setValue(0.0)
        group["clampMax" + ch].setValue(1.0)
    group["rangeInfo"].setValue("(not analyzed yet)")
    group["refFrame"].setValue(1)
    for ch in ("R", "G", "B"):
        group["a%s" % ch].setValue(1.0)
        group["b%s" % ch].setValue(0.0)
        group["ref%s" % ch].setValue(0.0)


def make_match_white():
    group = _create_sid_group("MatchWhite")
    with group:
        in_src = nuke.nodes.Input(name="Source"); in_src.setXYpos(0, 0)
        in_tgt = nuke.nodes.Input(name="Target"); in_tgt.setXYpos(150, 0)
        in_mask = nuke.nodes.Input(name="Mask"); in_mask.setXYpos(300, 0)
        xform = nuke.nodes.Grade(name="xform")
        xform.setInput(0, in_src)
        xform.setXYpos(0, 100)

        mix_merge = nuke.nodes.Dissolve(name="mixOut")
        mix_merge.setInput(0, in_src)
        mix_merge.setInput(1, xform)
        mix_merge["which"].setExpression("parent.mix")
        mix_merge.setXYpos(0, 200)

        clamp_node = _add_clamp_node(mix_merge, 300)
        view_switch = _add_view_mask_switch(clamp_node, in_mask, 350)
        out = nuke.nodes.Output()
        out.setInput(0, view_switch)
        out.setXYpos(0, 400)

        mode_k = nuke.Enumeration_Knob("mode", "Mode", ["Live", "Locked"])
        mask_apply_k = nuke.Enumeration_Knob("maskApplyTo", "Mask Applies To", ["Target", "Source", "Both"])
        mask_apply_k.setValue("Target")
        view_mask_k = nuke.Boolean_Knob("viewMask", "View Mask")
        view_mask_k.setValue(False)
        pct_k = nuke.Double_Knob("percent", "White %"); pct_k.setRange(0.0, 100.0); pct_k.setValue(1.0)
        mix_k = nuke.Double_Knob("mix", "Mix"); mix_k.setRange(0.0, 1.0); mix_k.setValue(1.0)
        size_k = nuke.Int_Knob("analysisSize", "Analysis Size"); size_k.setValue(64)
        hidden = _hidden_double_knobs(["aR", "aG", "aB", "bR", "bG", "bB", "refR", "refG", "refB"])
        for k in hidden:
            if k.name() in ("aR", "aG", "aB"):
                k.setValue(1.0)
        analyze_btn = nuke.PyScript_Knob(
            "analyze", "Analyze",
            "import sid_match_tools; sid_match_tools._mw_analyze(nuke.thisNode(), True)")
        analyze_btn.setFlag(nuke.STARTLINE)
        setref_btn = nuke.PyScript_Knob(
            "setref", "Set Reference",
            "import sid_match_tools; sid_match_tools._mw_set_reference(nuke.thisNode())")
        refframe_k = nuke.Int_Knob("refFrame", "Reference Frame")
        refframe_k.setValue(1)
        refframe_k.setFlag(nuke.STARTLINE)
        refframe_k.setTooltip(
            "Type a frame number to sample the reference from that frame "
            "directly, or click Set Reference to sample the current "
            "frame (which then updates this box to match).")
        reset_btn = nuke.PyScript_Knob(
            "reset", "Reset",
            "import sid_match_tools; sid_match_tools._mw_reset(nuke.thisNode())")
        reset_btn.setFlag(nuke.STARTLINE)
        for k in ([mode_k, mask_apply_k, view_mask_k, pct_k, mix_k, size_k] + hidden + _clamp_knobs() +
                  _range_info_knobs() + [analyze_btn, refframe_k, setref_btn, reset_btn]):
            group.addKnob(k)
        _add_credit_knob(group)

        _link_grade_to_parent(xform)
        _install_live_refresh(group, "_mw_analyze", extra_knobs=("percent", "analysisSize", "maskApplyTo"),
                               setref_fn_name="_mw_set_reference")

    group["label"].setValue("[value mode] [value percent]%")
    # See the matching note in make_match_black -- no auto-analyze with
    # nothing real connected yet; inputChange handles it once wired.
    return group


# -- Neutralize -------------------------------------------------------------
#
# A single Expression node ("xform") does the whole band blend per pixel.
# Its expr text is written ONCE at build time with symbolic references to
# MAX_BANDS fixed slots of group-level knobs (center_i, a_i*, b_i* per
# channel), so Analyze only ever sets knob VALUES on the group -- never
# touches the Expression node by name again. Bands not in use get a center
# far outside [0,1] so their tent weight is always ~0 and they drop out of
# the blend on their own.

_UNUSED_CENTER = -999.0


def _nz_band_weight_terms(luma):
    terms_w = []
    for i in range(MAX_BANDS):
        terms_w.append("max(0,1-abs(%s-parent.center%d)/parent.spacing)" % (luma, i))
    return terms_w


def _nz_expr_for_channel(ch):
    luma = "(0.2126*r+0.7152*g+0.0722*b)"
    terms_w = _nz_band_weight_terms(luma)
    den = "+".join(terms_w) + "+1e-6"

    # Default: per-channel variance-ratio gain, matched independently per
    # band and blended across bands by luma tent weight.
    terms_wv = []
    for i, w in enumerate(terms_w):
        terms_wv.append("(%s)*(parent.a%d%s*%s+parent.b%d%s)" % (w, i, ch, ch.lower(), i, ch))
    per_channel = "((%s)/(%s))" % ("+".join(terms_wv), den)

    # Preserve Saturation: match LUMA (brightness/contrast) and CHROMA
    # MAGNITUDE (distance from grey -- i.e. saturation strength) as two
    # separate band-blended quantities, then recombine preserving hue.
    # A pure Saturation/Gamma push on Target changes these in ways a
    # per-channel ratio can't track without desaturating or no-opping.
    terms_lum = []
    terms_cg = []
    for i, w in enumerate(terms_w):
        terms_lum.append("(%s)*(parent.a%dR*%s+parent.blum%d)" % (w, i, luma, i))
        terms_cg.append("(%s)*(parent.cg%d)" % (w, i))
    matched_luma = "((%s)/(%s))" % ("+".join(terms_lum), den)
    chroma_scale = "((%s)/(%s))" % ("+".join(terms_cg), den)
    lo = ch.lower()
    preserve = "(%s+(%s-%s)*%s)" % (matched_luma, lo, luma, chroma_scale)

    corrected = "(parent.preserveSaturation?%s:%s)" % (preserve, per_channel)
    return "%s+(%s-%s)*parent.mix" % (lo, corrected, lo)


def _bands_from_index(bands_value):
    # The "bands" Enumeration_Knob's own option strings ARE the band
    # counts ("1"/"3"/"5"), not indices into some other list -- .value()
    # returns that string directly.
    try:
        n = int(bands_value)
    except (TypeError, ValueError):
        n = 1
    return n if n in (1, 3, 5) else 1


def _nz_analyze(group, use_live_target):
    bands = _bands_from_index(group["bands"].value())
    size = group["analysisSize"].value()
    preserve_sat = group["preserveSaturation"].value()
    src_px = _sample_plane(group.input(0), size, _mask_for(group, "Source"))
    lines = [_format_range("Neutralize src", src_px)]
    src_bands = _band_stats(src_px, bands)
    src_chroma = _chroma_band_means(src_px, bands) if preserve_sat else None

    if use_live_target:
        tgt_px = _sample_plane(group.input(1), size, _mask_for(group, "Target"))
        _auto_clamp_from_target(group, tgt_px)
        lines.append(_format_range("Neutralize target", tgt_px))
        tgt_bands = _band_stats(tgt_px, bands)
        tgt_chroma = _chroma_band_means(tgt_px, bands) if preserve_sat else None
    elif preserve_sat:
        tgt_chroma = [group["refChroma_%d" % i].value() for i in range(bands)]

    centers = _band_centers(bands)
    spacing = 1.0 / bands
    group["spacing"].setValue(spacing)

    for i in range(MAX_BANDS):
        if i >= bands:
            group["center%d" % i].setValue(_UNUSED_CENTER)
            for ch in ("R", "G", "B"):
                group["a%d%s" % (i, ch)].setValue(1.0)
                group["b%d%s" % (i, ch)].setValue(0.0)
            group["blum%d" % i].setValue(0.0)
            group["cg%d" % i].setValue(1.0)
            continue

        group["center%d" % i].setValue(centers[i])
        src_mean, src_std = src_bands[i]
        if use_live_target:
            tgt_mean, tgt_std = tgt_bands[i]
        else:
            tgt_mean = (group["refMeanR_%d" % i].value(), group["refMeanG_%d" % i].value(),
                        group["refMeanB_%d" % i].value())
            tgt_std = (group["refStdR_%d" % i].value(), group["refStdG_%d" % i].value(),
                       group["refStdB_%d" % i].value())

        # Per-channel variance-ratio gain: each channel matched
        # independently to its OWN target mean/stddev. Clamp guards the
        # near-zero-stddev division blowup in a thin/flat band.
        for c, ch in enumerate(("R", "G", "B")):
            a = tgt_std[c] / max(src_std[c], STD_EPS)
            a = max(1e-3, min(1e3, a))
            b = tgt_mean[c] - a * src_mean[c]
            group["a%d%s" % (i, ch)].setValue(a)
            group["b%d%s" % (i, ch)].setValue(b)

        # Preserve Saturation: match luma (brightness/contrast) and
        # chroma magnitude (distance from grey) as two separate
        # band-blended quantities instead, so a Target grade that only
        # changes saturation (luma held constant, by definition) still
        # gets picked up via the chroma-magnitude ratio.
        if preserve_sat:
            src_luma_mean = LUMA_R * src_mean[0] + LUMA_G * src_mean[1] + LUMA_B * src_mean[2]
            tgt_luma_mean = LUMA_R * tgt_mean[0] + LUMA_G * tgt_mean[1] + LUMA_B * tgt_mean[2]
            src_luma_std = LUMA_R * src_std[0] + LUMA_G * src_std[1] + LUMA_B * src_std[2]
            tgt_luma_std = LUMA_R * tgt_std[0] + LUMA_G * tgt_std[1] + LUMA_B * tgt_std[2]
            luma_gain = max(1e-3, min(1e3, tgt_luma_std / max(src_luma_std, STD_EPS)))
            blum = tgt_luma_mean - luma_gain * src_luma_mean
            # a{i}R carries the shared luma gain for this band's
            # matched-luma term in the expression.
            group["a%dR" % i].setValue(luma_gain)
            group["blum%d" % i].setValue(blum)
            cg = tgt_chroma[i] / max(src_chroma[i], STD_EPS)
            group["cg%d" % i].setValue(max(1e-3, min(1e3, cg)))

    for l in lines:
        print(l)
    _show_ranges(group, lines)


def _nz_set_reference(group, use_frame_from_box=False):
    bands = _bands_from_index(group["bands"].value())
    size = group["analysisSize"].value()
    if use_frame_from_box:
        frame = int(round(group["refFrame"].value()))
        tgt_px = _sample_plane_at_frame(group.input(1), size, frame, _mask_for(group, "Target"))
    else:
        frame = int(round(nuke.frame()))
        tgt_px = _sample_plane(group.input(1), size, _mask_for(group, "Target"))
        group["refFrame"].setValue(frame)
    _auto_clamp_from_target(group, tgt_px)
    print(_format_range("Neutralize target (reference)", tgt_px))
    tgt_bands = _band_stats(tgt_px, bands)
    tgt_chroma = _chroma_band_means(tgt_px, bands)
    for i in range(bands):
        group["refChroma_%d" % i].setValue(tgt_chroma[i])
        mean, std = tgt_bands[i]
        group["refMeanR_%d" % i].setValue(mean[0])
        group["refMeanG_%d" % i].setValue(mean[1])
        group["refMeanB_%d" % i].setValue(mean[2])
        group["refStdR_%d" % i].setValue(std[0])
        group["refStdG_%d" % i].setValue(std[1])
        group["refStdB_%d" % i].setValue(std[2])
    _nz_analyze(group, use_live_target=False)


def _nz_reset(group):
    group["mode"].setValue("Live")
    group["maskApplyTo"].setValue("Target")
    group["viewMask"].setValue(False)
    group["bands"].setValue("1")
    group["mix"].setValue(1.0)
    group["analysisSize"].setValue(64)
    group["preserveSaturation"].setValue(False)
    group["clampEnable"].setValue(False)
    group["clampMinAll"].setValue(1.0)
    group["clampMinAllPrev"].setValue(1.0)
    group["clampMin"].setValue([0.0, 0.0, 0.0])
    group["clampMaxAll"].setValue(1.0)
    group["clampMaxAllPrev"].setValue(1.0)
    group["clampMax"].setValue([1.0, 1.0, 1.0])
    for ch in ("R", "G", "B"):
        group["clampMin" + ch].setValue(0.0)
        group["clampMax" + ch].setValue(1.0)
    group["rangeInfo"].setValue("(not analyzed yet)")
    group["refFrame"].setValue(1)
    group["spacing"].setValue(1.0)
    for i in range(MAX_BANDS):
        group["center%d" % i].setValue(_UNUSED_CENTER)
        for ch in ("R", "G", "B"):
            group["a%d%s" % (i, ch)].setValue(1.0)
            group["b%d%s" % (i, ch)].setValue(0.0)
        for nm in ("refMeanR", "refMeanG", "refMeanB", "refStdR", "refStdG", "refStdB",
                    "refChroma"):
            group["%s_%d" % (nm, i)].setValue(0.0)
        group["blum%d" % i].setValue(0.0)
        group["cg%d" % i].setValue(1.0)


def make_neutralize():
    group = _create_sid_group("Neutralize")
    with group:
        in_src = nuke.nodes.Input(name="Source"); in_src.setXYpos(0, 0)
        in_tgt = nuke.nodes.Input(name="Target"); in_tgt.setXYpos(150, 0)
        in_mask = nuke.nodes.Input(name="Mask"); in_mask.setXYpos(300, 0)
        xform = nuke.nodes.Expression(name="xform")
        xform.setInput(0, in_src)
        xform.setXYpos(0, 100)
        clamp_node = _add_clamp_node(xform, 200)
        view_switch = _add_view_mask_switch(clamp_node, in_mask, 250)
        out = nuke.nodes.Output()
        out.setInput(0, view_switch)
        out.setXYpos(0, 300)

        bands_k = nuke.Enumeration_Knob("bands", "Bands", ["1", "3", "5"])
        mode_k = nuke.Enumeration_Knob("mode", "Mode", ["Live", "Locked"])
        mask_apply_k = nuke.Enumeration_Knob("maskApplyTo", "Mask Applies To", ["Target", "Source", "Both"])
        mask_apply_k.setValue("Target")
        view_mask_k = nuke.Boolean_Knob("viewMask", "View Mask")
        view_mask_k.setValue(False)
        mix_k = nuke.Double_Knob("mix", "Mix"); mix_k.setRange(0.0, 1.0); mix_k.setValue(1.0)
        size_k = nuke.Int_Knob("analysisSize", "Analysis Size"); size_k.setValue(64)
        preserve_sat_k = nuke.Boolean_Knob("preserveSaturation", "Preserve Saturation")
        preserve_sat_k.setValue(False)
        preserve_sat_k.setTooltip(
            "Matches luma and chroma magnitude (distance from grey) as "
            "two separate band-blended quantities instead of a per-"
            "channel ratio -- holds up when Target has had Saturation or "
            "Gamma pushed, at the cost of matching each channel's own "
            "distribution less exactly.")

        hidden_names = ["spacing"]
        for i in range(MAX_BANDS):
            hidden_names.append("center%d" % i)
            hidden_names.append("blum%d" % i)
            hidden_names.append("cg%d" % i)
            for ch in ("R", "G", "B"):
                hidden_names.append("a%d%s" % (i, ch))
                hidden_names.append("b%d%s" % (i, ch))
            for nm in ("refMeanR", "refMeanG", "refMeanB", "refStdR", "refStdG", "refStdB",
                        "refChroma"):
                hidden_names.append("%s_%d" % (nm, i))
        hidden = _hidden_double_knobs(hidden_names)
        for k in hidden:
            nm = k.name()
            # Safe identity defaults for BEFORE any analysis has ever run
            # (brand new node, nothing connected yet): every band's gain=1,
            # offset=0 makes corrected == r regardless of band weighting,
            # and spacing must be non-zero (it's a divisor in the kernel
            # text) or the Expression node NaNs out on an unconnected node.
            if nm == "spacing":
                k.setValue(1.0)
            elif nm[0] == "a" and nm[1:2].isdigit():
                k.setValue(1.0)
            elif nm[:2] == "cg":
                k.setValue(1.0)

        analyze_btn = nuke.PyScript_Knob(
            "analyze", "Analyze (click after changing Bands too)",
            "import sid_match_tools; sid_match_tools._nz_analyze(nuke.thisNode(), True)")
        analyze_btn.setFlag(nuke.STARTLINE)
        setref_btn = nuke.PyScript_Knob(
            "setref", "Set Reference",
            "import sid_match_tools; sid_match_tools._nz_set_reference(nuke.thisNode())")
        refframe_k = nuke.Int_Knob("refFrame", "Reference Frame")
        refframe_k.setValue(1)
        refframe_k.setFlag(nuke.STARTLINE)
        refframe_k.setTooltip(
            "Type a frame number to sample the reference from that frame "
            "directly, or click Set Reference to sample the current "
            "frame (which then updates this box to match).")
        reset_btn = nuke.PyScript_Knob(
            "reset", "Reset",
            "import sid_match_tools; sid_match_tools._nz_reset(nuke.thisNode())")
        reset_btn.setFlag(nuke.STARTLINE)

        for k in ([bands_k, mode_k, mask_apply_k, view_mask_k, mix_k, size_k, preserve_sat_k] + hidden + _clamp_knobs() +
                  _range_info_knobs() + [analyze_btn, refframe_k, setref_btn, reset_btn]):
            group.addKnob(k)
        _add_credit_knob(group)

        xform["expr0"].setValue(_nz_expr_for_channel("R"))
        xform["expr1"].setValue(_nz_expr_for_channel("G"))
        xform["expr2"].setValue(_nz_expr_for_channel("B"))
        _install_live_refresh(group, "_nz_analyze",
                               extra_knobs=("bands", "analysisSize", "preserveSaturation", "maskApplyTo"),
                               setref_fn_name="_nz_set_reference")

    # See the matching note in make_match_black -- no auto-analyze with
    # nothing real connected yet; inputChange handles it once wired.
    group["label"].setValue("[value mode] [value bands] bands")
    return group


# -- Match Colour ------------------------------------------------------------
#
# Deliberately different math from Neutralize: true per-channel quantile
# (histogram) matching instead of a few tonal-band mean/stddev ratios.
# K_POINTS percentile values are sampled from src's and target's own sorted
# per-channel distributions; src's value at each percentile maps to
# target's value at that SAME percentile. Applied as a piecewise-linear
# curve via the classic "sum of clamped ramps" trick (one term per
# segment), entirely in the Expression node's own per-pixel math -- no
# lookup-curve knob API needed. Monotonic by construction (every segment's
# height is the sorted-value's non-negative step to the next percentile),
# and -- unlike Neutralize's variance-ratio gain -- there is no division by
# a per-band stddev anywhere, so it does not blow up in flat/clipped
# regions the way Neutralize's `tgtStd/srcStd` can.
#
# Flat extrapolation outside the sampled range: below the darkest sampled
# percentile the output clamps to that percentile's target value; above
# the brightest, to that one's. (Clipped-highlight regions map to
# whatever target value the brightest percentile anchor holds -- they
# don't extrapolate further.)

K_POINTS = 17   # 16 segments: percentiles 0, 1/16, ..., 16/16


def _nearest_rank_value(sorted_vals, percent):
    if not sorted_vals:
        return 0.0
    idx = int(round(percent / 100.0 * (len(sorted_vals) - 1)))
    idx = max(0, min(len(sorted_vals) - 1, idx))
    return sorted_vals[idx]


def _mc_curve_expr(ch, suffix, var):
    """Piecewise-linear sum-of-clamped-ramps curve (+ linear extrapolation
    past the sampled ends) mapping `var` through knots mcX{i}{suffix} ->
    mcY{i}{suffix}. `suffix` is a channel letter ("R"/"G"/"B") for the
    per-channel knot set, or "" for the shared luma knot set."""
    terms = ["parent.mcY0%s" % suffix]
    for k in range(K_POINTS - 1):
        span = "(parent.mcX%d%s-parent.mcX%d%s)" % (k + 1, suffix, k, suffix)
        t = "clamp((%s-parent.mcX%d%s)/(%s+1e-6),0,1)*(parent.mcY%d%s-parent.mcY%d%s)" % (
            var, k, suffix, span, k + 1, suffix, k, suffix)
        terms.append(t)
    flat = "(" + "+".join(terms) + ")"
    last = K_POINTS - 1
    slope0 = "((parent.mcY1%s-parent.mcY0%s)/(parent.mcX1%s-parent.mcX0%s+1e-6))" % (
        suffix, suffix, suffix, suffix)
    slopeN = "((parent.mcY%d%s-parent.mcY%d%s)/(parent.mcX%d%s-parent.mcX%d%s+1e-6))" % (
        last, suffix, last - 1, suffix, last, suffix, last - 1, suffix)
    ext_lo = "min(0,%s-parent.mcX0%s)*%s" % (var, suffix, slope0)
    ext_hi = "max(0,%s-parent.mcX%d%s)*%s" % (var, last, suffix, slopeN)
    return "(%s+%s+%s)" % (flat, ext_lo, ext_hi)


def _mc_expr_for_channel(ch):
    """Per-channel quantile match (R to R's own histogram, etc) by
    default. When Preserve Saturation is on, match luma and chroma
    magnitude (distance from grey) as two separate quantile curves
    instead, then recombine preserving hue -- a pure Saturation push on
    Target holds luma constant by definition, so matching luma alone
    would be blind to it; matching chroma magnitude too actually
    transfers the saturation change instead of just surviving it."""
    lo = ch.lower()
    per_channel = _mc_curve_expr(ch, ch, lo)
    luma = "(0.2126*r+0.7152*g+0.0722*b)"
    mapped_luma = _mc_curve_expr(ch, "", luma)
    chroma_cur = "sqrt((r-%s)*(r-%s)+(g-%s)*(g-%s)+(b-%s)*(b-%s))" % ((luma,) * 6)
    mapped_chroma = _mc_curve_expr(ch, "C", chroma_cur)
    chroma_scale = "(%s/max(%s,1e-6))" % (mapped_chroma, chroma_cur)
    shared = "(%s+(%s-%s)*%s)" % (mapped_luma, lo, luma, chroma_scale)
    corrected = "(parent.preserveSaturation?%s:%s)" % (shared, per_channel)
    return "%s+(%s-%s)*parent.mix" % (lo, corrected, lo)


def _mc_analyze(group, use_live_target):
    size = group["analysisSize"].value()
    src_px = _sample_plane(group.input(0), size, _mask_for(group, "Source"))
    lines = [_format_range("MatchColour src", src_px)]
    percentiles = [i * 100.0 / (K_POINTS - 1) for i in range(K_POINTS)]

    for c, ch in enumerate(("R", "G", "B")):
        src_sorted = sorted(px[c] for px in src_px)
        for i, pct in enumerate(percentiles):
            x = _nearest_rank_value(src_sorted, pct)
            group["mcX%d%s" % (i, ch)].setValue(x)
    src_luma_sorted = sorted(_luma(px) for px in src_px)
    for i, pct in enumerate(percentiles):
        group["mcX%d" % i].setValue(_nearest_rank_value(src_luma_sorted, pct))
    src_chroma_sorted = sorted(_chroma_mag(px) for px in src_px)
    for i, pct in enumerate(percentiles):
        group["mcX%dC" % i].setValue(_nearest_rank_value(src_chroma_sorted, pct))

    if use_live_target:
        tgt_px = _sample_plane(group.input(1), size, _mask_for(group, "Target"))
        _auto_clamp_from_target(group, tgt_px)
        lines.append(_format_range("MatchColour target", tgt_px))
        for c, ch in enumerate(("R", "G", "B")):
            tgt_sorted = sorted(px[c] for px in tgt_px)
            for i, pct in enumerate(percentiles):
                y = _nearest_rank_value(tgt_sorted, pct)
                group["mcY%d%s" % (i, ch)].setValue(y)
        tgt_luma_sorted = sorted(_luma(px) for px in tgt_px)
        for i, pct in enumerate(percentiles):
            group["mcY%d" % i].setValue(_nearest_rank_value(tgt_luma_sorted, pct))
        tgt_chroma_sorted = sorted(_chroma_mag(px) for px in tgt_px)
        for i, pct in enumerate(percentiles):
            group["mcY%dC" % i].setValue(_nearest_rank_value(tgt_chroma_sorted, pct))
    else:
        for c, ch in enumerate(("R", "G", "B")):
            for i in range(K_POINTS):
                y = group["refY%d%s" % (i, ch)].value()
                group["mcY%d%s" % (i, ch)].setValue(y)
        for i in range(K_POINTS):
            group["mcY%d" % i].setValue(group["refY%d" % i].value())
            group["mcY%dC" % i].setValue(group["refY%dC" % i].value())

    for l in lines:
        print(l)
    _show_ranges(group, lines)


def _mc_set_reference(group, use_frame_from_box=False):
    size = group["analysisSize"].value()
    if use_frame_from_box:
        frame = int(round(group["refFrame"].value()))
        tgt_px = _sample_plane_at_frame(group.input(1), size, frame, _mask_for(group, "Target"))
    else:
        frame = int(round(nuke.frame()))
        tgt_px = _sample_plane(group.input(1), size, _mask_for(group, "Target"))
        group["refFrame"].setValue(frame)
    _auto_clamp_from_target(group, tgt_px)
    _print_range("MatchColour target (reference)", tgt_px)
    percentiles = [i * 100.0 / (K_POINTS - 1) for i in range(K_POINTS)]
    for c, ch in enumerate(("R", "G", "B")):
        tgt_sorted = sorted(px[c] for px in tgt_px)
        for i, pct in enumerate(percentiles):
            y = _nearest_rank_value(tgt_sorted, pct)
            group["refY%d%s" % (i, ch)].setValue(y)
    tgt_luma_sorted = sorted(_luma(px) for px in tgt_px)
    for i, pct in enumerate(percentiles):
        group["refY%d" % i].setValue(_nearest_rank_value(tgt_luma_sorted, pct))
    tgt_chroma_sorted = sorted(_chroma_mag(px) for px in tgt_px)
    for i, pct in enumerate(percentiles):
        group["refY%dC" % i].setValue(_nearest_rank_value(tgt_chroma_sorted, pct))
    _mc_analyze(group, use_live_target=False)


def _mc_reset(group):
    group["mode"].setValue("Live")
    group["maskApplyTo"].setValue("Target")
    group["viewMask"].setValue(False)
    group["mix"].setValue(1.0)
    group["analysisSize"].setValue(64)
    group["preserveSaturation"].setValue(False)
    group["clampEnable"].setValue(False)
    group["clampMinAll"].setValue(1.0)
    group["clampMinAllPrev"].setValue(1.0)
    group["clampMin"].setValue([0.0, 0.0, 0.0])
    group["clampMaxAll"].setValue(1.0)
    group["clampMaxAllPrev"].setValue(1.0)
    group["clampMax"].setValue([1.0, 1.0, 1.0])
    for ch in ("R", "G", "B"):
        group["clampMin" + ch].setValue(0.0)
        group["clampMax" + ch].setValue(1.0)
    group["rangeInfo"].setValue("(not analyzed yet)")
    group["refFrame"].setValue(1)
    for i in range(K_POINTS):
        v = -10.0 + i * (20.0 / (K_POINTS - 1))
        cv = i * (10.0 / (K_POINTS - 1))
        for ch in ("R", "G", "B"):
            group["mcX%d%s" % (i, ch)].setValue(v)
            group["mcY%d%s" % (i, ch)].setValue(v)
            group["refY%d%s" % (i, ch)].setValue(v)
        group["mcX%d" % i].setValue(v)
        group["mcY%d" % i].setValue(v)
        group["refY%d" % i].setValue(v)
        group["mcX%dC" % i].setValue(cv)
        group["mcY%dC" % i].setValue(cv)
        group["refY%dC" % i].setValue(cv)


def make_match_colour():
    group = _create_sid_group("MatchColour")
    with group:
        in_src = nuke.nodes.Input(name="Source"); in_src.setXYpos(0, 0)
        in_tgt = nuke.nodes.Input(name="Target"); in_tgt.setXYpos(150, 0)
        in_mask = nuke.nodes.Input(name="Mask"); in_mask.setXYpos(300, 0)
        xform = nuke.nodes.Expression(name="xform")
        xform.setInput(0, in_src)
        xform.setXYpos(0, 100)
        clamp_node = _add_clamp_node(xform, 200)
        view_switch = _add_view_mask_switch(clamp_node, in_mask, 250)
        out = nuke.nodes.Output()
        out.setInput(0, view_switch)
        out.setXYpos(0, 300)

        mode_k = nuke.Enumeration_Knob("mode", "Mode", ["Live", "Locked"])
        mask_apply_k = nuke.Enumeration_Knob("maskApplyTo", "Mask Applies To", ["Target", "Source", "Both"])
        mask_apply_k.setValue("Target")
        view_mask_k = nuke.Boolean_Knob("viewMask", "View Mask")
        view_mask_k.setValue(False)
        mix_k = nuke.Double_Knob("mix", "Mix"); mix_k.setRange(0.0, 1.0); mix_k.setValue(1.0)
        size_k = nuke.Int_Knob("analysisSize", "Analysis Size"); size_k.setValue(64)
        preserve_sat_k = nuke.Boolean_Knob("preserveSaturation", "Preserve Saturation")
        preserve_sat_k.setValue(False)
        preserve_sat_k.setTooltip(
            "Match luma and chroma magnitude (distance from grey) as two "
            "separate curves instead of matching each channel's own "
            "histogram, recombined preserving hue -- holds up when "
            "Target has had Saturation or Gamma pushed, at the cost of "
            "matching each channel's own distribution less exactly.")

        hidden_names = []
        for i in range(K_POINTS):
            for ch in ("R", "G", "B"):
                hidden_names.append("mcX%d%s" % (i, ch))
                hidden_names.append("mcY%d%s" % (i, ch))
                hidden_names.append("refY%d%s" % (i, ch))
            hidden_names.append("mcX%d" % i)
            hidden_names.append("mcY%d" % i)
            hidden_names.append("refY%d" % i)
            hidden_names.append("mcX%dC" % i)
            hidden_names.append("mcY%dC" % i)
            hidden_names.append("refY%dC" % i)
        hidden = _hidden_double_knobs(hidden_names)
        # Safe identity default for BEFORE any analysis has ever run: every
        # mcX_i == mcY_i == refY_i (a generous -10..10 spread, wide enough
        # to cover real HDR values) makes the piecewise-linear LUT the
        # y=x line exactly, so a brand new/unconnected node shows the
        # original image instead of black (all-zero knots would collapse
        # the whole curve to a constant 0 = pure black). The chroma-
        # magnitude knots (mcC*) use a 0..10 spread instead -- chroma
        # magnitude is never negative.
        identity_default = {}
        for i in range(K_POINTS):
            v = -10.0 + i * (20.0 / (K_POINTS - 1))
            cv = i * (10.0 / (K_POINTS - 1))
            for ch in ("R", "G", "B"):
                for prefix in ("mcX", "mcY", "refY"):
                    identity_default["%s%d%s" % (prefix, i, ch)] = v
            for prefix in ("mcX", "mcY", "refY"):
                identity_default["%s%d" % (prefix, i)] = v
            for prefix in ("mcX", "mcY", "refY"):
                identity_default["%s%dC" % (prefix, i)] = cv
        for k in hidden:
            if k.name() in identity_default:
                k.setValue(identity_default[k.name()])

        analyze_btn = nuke.PyScript_Knob(
            "analyze", "Analyze",
            "import sid_match_tools; sid_match_tools._mc_analyze(nuke.thisNode(), True)")
        analyze_btn.setFlag(nuke.STARTLINE)
        setref_btn = nuke.PyScript_Knob(
            "setref", "Set Reference",
            "import sid_match_tools; sid_match_tools._mc_set_reference(nuke.thisNode())")
        refframe_k = nuke.Int_Knob("refFrame", "Reference Frame")
        refframe_k.setValue(1)
        refframe_k.setFlag(nuke.STARTLINE)
        refframe_k.setTooltip(
            "Type a frame number to sample the reference from that frame "
            "directly, or click Set Reference to sample the current "
            "frame (which then updates this box to match).")
        reset_btn = nuke.PyScript_Knob(
            "reset", "Reset",
            "import sid_match_tools; sid_match_tools._mc_reset(nuke.thisNode())")
        reset_btn.setFlag(nuke.STARTLINE)

        for k in ([mode_k, mask_apply_k, view_mask_k, mix_k, size_k, preserve_sat_k] + hidden + _clamp_knobs() +
                  _range_info_knobs() + [analyze_btn, refframe_k, setref_btn, reset_btn]):
            group.addKnob(k)
        _add_credit_knob(group)

        xform["expr0"].setValue(_mc_expr_for_channel("R"))
        xform["expr1"].setValue(_mc_expr_for_channel("G"))
        xform["expr2"].setValue(_mc_expr_for_channel("B"))
        _install_live_refresh(group, "_mc_analyze", extra_knobs=("analysisSize", "maskApplyTo"),
                               setref_fn_name="_mc_set_reference")

    # See the matching note in make_match_black -- no auto-analyze with
    # nothing real connected yet; inputChange handles it once wired.
    group["label"].setValue("[value mode]")
    return group


# -- Menu ----------------------------------------------------------------------

def install_menu():
    m = nuke.menu("Nodes").addMenu("Sid", icon=None)
    m.addCommand("Neutralize", make_neutralize)
    m.addCommand("Match Black", make_match_black)
    m.addCommand("Match White", make_match_white)
    m.addCommand("Match Colour", make_match_colour)

# Sid VFX Suite for Nuke -- Professional Compositing Tools
# Contains:
#   1. Edge Extend  - Multi-mode RGB edge extend, dual reach & fringe suppression
#   2. Alpha Edge   - Sub-pixel alpha processor (Grow/Shrink, De-Jitter, Contrast, Blur)
#   3. Light Wrap   - Physically accurate LightWrap & BG Edge Mix with true Gaussian pattern blur
#
# Install:
#   Add to menu.py:
#       import sid_edge_extend
#       sid_edge_extend.install_menu()
#   Nodes > Sid then provides Edge Extend, Alpha Edge, and Light Wrap.
#
# Strict ASCII.

import nuke


def _divider(name):
    return nuke.Text_Knob(name, "", "")


def _section_heading(name, label):
    return nuke.Text_Knob(name, f"<b>{label}</b>", "")


def _add_credit_knob(group):
    group.addKnob(_divider("creditDivider"))
    group.addKnob(nuke.Text_Knob("credit", "", "<span style='color:#777; font-size:11px;'>Made by Sid (www.sidmanvfx.com)</span>"))
    import base64
    sig = nuke.Text_Knob("_sig", "", base64.b64decode("TWFkZSBieSBTaWQgKHd3dy5zaWRtYW52ZnguY29tKQ==").decode("ascii"))
    sig.setFlag(nuke.INVISIBLE)
    group.addKnob(sig)


def _create_sid_group(name):
    """Creates a Group node placed at the cursor / DAG center and auto-connected to selected node."""
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

    return group, selected


def _connect_sid_group(group, selected):
    """Connects the newly created group to the previously selected node."""
    if selected and group:
        try:
            group.setInput(0, selected)
        except Exception:
            pass
    try:
        for n in nuke.selectedNodes():
            n.setSelected(False)
        group.setSelected(True)
    except Exception:
        pass
    if nuke.GUI:
        try:
            group.showControlPanel()
        except Exception:
            pass


# =============================================================================
# 1. EDGE EXTEND (Pure RGB Edge Extend & Fringe Suppression)
# =============================================================================

def _update_edge_extend_ui(group):
    """Dynamically shows/enables controls based on selected Extend Method and Roto Mode."""
    knobs = group.knobs()
    if "extendMethod" not in knobs:
        return

    method = int(group["extendMethod"].getValue())
    roto_mode = int(group["rotoMode"].getValue())

    if "sampleRingWidth" in knobs:
        show_ring = (method == 1)
        knobs["sampleRingWidth"].setVisible(show_ring)
        knobs["sampleRingWidth"].setEnabled(show_ring)

    if "baseEdgeStrength" in knobs:
        show_base = (method != 3)
        knobs["baseEdgeStrength"].setVisible(show_base)
        knobs["baseEdgeStrength"].setEnabled(show_base)

    show_roto = (method == 2)
    for k in ("divRoto", "hdrRoto", "rotoMode", "rotoStrength", "rotoSampleErode",
              "rotoSampleGain", "rotoSampleGamma"):
        if k in knobs:
            knobs[k].setVisible(show_roto)
            knobs[k].setEnabled(show_roto)

    if "rotoSampleSpread" in knobs:
        knobs["rotoSampleSpread"].setVisible(show_roto and (roto_mode == 1))
        knobs["rotoSampleSpread"].setEnabled(show_roto and (roto_mode == 1))


def make_edge_extend():
    group, selected = _create_sid_group("EdgeExtend")
    with group:
        nuke.tcl("""
            Input {
                inputs 0
                name Source
                xpos 0
                ypos 0
            }
            set in_src [stack 0]

            Input {
                inputs 0
                name RotoSample
                xpos 300
                ypos 0
                number 1
            }
            set in_roto [stack 0]

            Input {
                inputs 0
                name Mask
                xpos 600
                ypos 0
                number 2
            }
            set in_mask [stack 0]

            # 1. Unpremult input if needed
            push $in_src
            Unpremult {
                disable {{!parent.premultipliedInput}}
                name unpreSource
                xpos 0
                ypos 60
            }
            set unpre_src [stack 0]

            # 2. Pre-Weight: compute sample weight W and pre-weighted RGB
            push $in_roto
            push $unpre_src
            MergeExpression {
                inputs 2
                temp_name0 roto_m
                temp_expr0 {(parent.extendMethod == 2 ? (parent.rotoMode == 1 ? (1.0 - parent.rotoStrength * (1.0 - clamp(A.a, 0.0001, 1.0))) : (1.0 - clamp(A.a * parent.rotoStrength, 0.0, 1.0))) : 1.0)}
                temp_name1 weight
                temp_expr1 {pow(clamp(B.a, 0, 1), 1.5) * roto_m}
                channel0 red
                expr0 {B.r * weight}
                channel1 green
                expr1 {B.g * weight}
                channel2 blue
                expr2 {B.b * weight}
                channel3 alpha
                expr3 {weight}
                name preWeight
                xpos 0
                ypos 120
            }

            # 3. 12-Tap Kernel Sampler (Pure fetches, zero math per tap)
            Expression {
                temp_name0 d1
                temp_expr0 {max(1, parent.rotoSampleErode + parent.edgeErode + (parent.extendMethod == 1 ? parent.sampleRingWidth * 0.5 + parent.extendOutward * 0.5 : ((parent.extendMethod == 2 && parent.rotoMode == 1) ? parent.rotoSampleSpread * 0.45 : (parent.extendDistance + parent.extendOutward) * 0.45)))}
                temp_name1 d2
                temp_expr1 {max(2, parent.rotoSampleErode + parent.edgeErode + (parent.extendMethod == 1 ? parent.sampleRingWidth + parent.extendOutward : ((parent.extendMethod == 2 && parent.rotoMode == 1) ? parent.rotoSampleSpread : (parent.extendDistance + parent.extendOutward))))}
                temp_name2 sumW
                temp_expr2 {a(x+d1*0.5,y) + a(x-d1*0.5,y) + a(x,y+d1*0.5) + a(x,y-d1*0.5) + a(x+d1,y) + a(x-d1,y) + a(x,y+d1) + a(x,y-d1) + a(x+d2*0.7,y+d2*0.7) + a(x-d2*0.7,y+d2*0.7) + a(x+d2*0.7,y-d2*0.7) + a(x-d2*0.7,y-d2*0.7)}
                channel0 red
                expr0 {sumW > 0.0001 ? (r(x+d1*0.5,y) + r(x-d1*0.5,y) + r(x,y+d1*0.5) + r(x,y-d1*0.5) + r(x+d1,y) + r(x-d1,y) + r(x,y+d1) + r(x,y-d1) + r(x+d2*0.7,y+d2*0.7) + r(x-d2*0.7,y+d2*0.7) + r(x+d2*0.7,y-d2*0.7) + r(x-d2*0.7,y-d2*0.7)) / sumW : r}
                channel1 green
                expr1 {sumW > 0.0001 ? (g(x+d1*0.5,y) + g(x-d1*0.5,y) + g(x,y+d1*0.5) + g(x,y-d1*0.5) + g(x+d1,y) + g(x-d1,y) + g(x,y+d1) + g(x,y-d1) + g(x+d2*0.7,y+d2*0.7) + g(x-d2*0.7,y+d2*0.7) + g(x+d2*0.7,y-d2*0.7) + g(x-d2*0.7,y-d2*0.7)) / sumW : g}
                channel2 blue
                expr2 {sumW > 0.0001 ? (b(x+d1*0.5,y) + b(x-d1*0.5,y) + b(x,y+d1*0.5) + b(x,y-d1*0.5) + b(x+d1,y) + b(x-d1,y) + b(x,y+d1) + b(x,y-d1) + b(x+d2*0.7,y+d2*0.7) + b(x-d2*0.7,y+d2*0.7) + b(x+d2*0.7,y-d2*0.7) + b(x-d2*0.7,y-d2*0.7)) / sumW : b}
                channel3 alpha
                expr3 {sumW > 0.0001 ? 1.0 : 0.0}
                name tapSampler
                xpos 0
                ypos 180
            }
            set raw_ext [stack 0]

            # 4. Edge Grade (B = raw_ext, A = in_roto to carry roto alpha)
            push $in_roto
            push $raw_ext
            MergeExpression {
                inputs 2
                temp_name0 rotoG
                temp_expr0 {parent.extendMethod == 2 ? parent.rotoSampleGain : 1.0}
                temp_name1 rotoGam
                temp_expr1 {parent.extendMethod == 2 ? max(0.1, parent.rotoSampleGamma) : 1.0}
                temp_name2 origLum
                temp_expr2 {0.2126*B.r + 0.7152*B.g + 0.0722*B.b}
                channel0 red
                expr0 {lerp(origLum, pow(max(0, B.r * rotoG), 1.0 / rotoGam) * parent.edgeMultiply, parent.edgeSaturation)}
                channel1 green
                expr1 {lerp(origLum, pow(max(0, B.g * rotoG), 1.0 / rotoGam) * parent.edgeMultiply, parent.edgeSaturation)}
                channel2 blue
                expr2 {lerp(origLum, pow(max(0, B.b * rotoG), 1.0 / rotoGam) * parent.edgeMultiply, parent.edgeSaturation)}
                channel3 alpha
                expr3 {A.a}
                name edgeGrade
                xpos 0
                ypos 240
            }
            set graded_ext [stack 0]

            # 5. Fringe Suppression & Core Combiner (B = unpre_src, A = graded_ext)
            push $graded_ext
            push $unpre_src
            MergeExpression {
                inputs 2
                temp_name0 er
                temp_expr0 {max(0.5, parent.edgeErode)}
                temp_name1 erd
                temp_expr1 {max(0.5, parent.edgeErode * 0.707)}
                temp_name2 core_min
                temp_expr2 {min(B.a, min(min(min(B.a(x+er,y), B.a(x-er,y)), min(B.a(x,y+er), B.a(x,y-er))), min(min(B.a(x+erd,y+erd), B.a(x-erd,y+erd)), min(B.a(x+erd,y-erd), B.a(x-erd,y-erd)))))}
                temp_name3 edgeW
                temp_expr3 {clamp(max((1.0 - core_min) / max(0.01, parent.edgeInnerSoftness * 0.1), (parent.extendMethod == 2 && parent.rotoMode == 0 ? clamp(A.a * parent.rotoStrength, 0, 1) : 0)), 0, 1)}
                channel0 red
                expr0 {B.a > 0.001 ? lerp(B.r, A.r + ((B.a > 0.5 ? (B.r - A.r) : 0) * parent.recoverDetail), clamp(max(edgeW * clamp((parent.extendMethod == 3 ? 0.0 : parent.baseEdgeStrength) + max((A.r - B.r - parent.fringeThreshold)*parent.clearDarkEdges, (B.r - A.r - parent.fringeThreshold)*parent.clearBrightEdges)*parent.fringeSensitivity, 0, 1), (parent.extendMethod == 2 && parent.rotoMode == 0 ? clamp(A.a * parent.rotoStrength, 0, 1) : 0)), 0, 1)) : A.r}
                channel1 green
                expr1 {B.a > 0.001 ? lerp(B.g, A.g + ((B.a > 0.5 ? (B.g - A.g) : 0) * parent.recoverDetail), clamp(max(edgeW * clamp((parent.extendMethod == 3 ? 0.0 : parent.baseEdgeStrength) + max((A.g - B.g - parent.fringeThreshold)*parent.clearDarkEdges, (B.g - A.g - parent.fringeThreshold)*parent.clearBrightEdges)*parent.fringeSensitivity, 0, 1), (parent.extendMethod == 2 && parent.rotoMode == 0 ? clamp(A.a * parent.rotoStrength, 0, 1) : 0)), 0, 1)) : A.g}
                channel2 blue
                expr2 {B.a > 0.001 ? lerp(B.b, A.b + ((B.a > 0.5 ? (B.b - A.b) : 0) * parent.recoverDetail), clamp(max(edgeW * clamp((parent.extendMethod == 3 ? 0.0 : parent.baseEdgeStrength) + max((A.b - B.b - parent.fringeThreshold)*parent.clearDarkEdges, (B.b - A.b - parent.fringeThreshold)*parent.clearBrightEdges)*parent.fringeSensitivity, 0, 1), (parent.extendMethod == 2 && parent.rotoMode == 0 ? clamp(A.a * parent.rotoStrength, 0, 1) : 0)), 0, 1)) : A.b}
                channel3 alpha
                expr3 {B.a}
                name fringeCombiner
                xpos 0
                ypos 300
            }
            set clean_unpre [stack 0]

            # 6. Premult output
            push $clean_unpre
            Premult {
                disable {{!parent.premultipliedOutput}}
                name premultOut
                xpos 0
                ypos 360
            }
            set p0_final [stack 0]

            # Preview Mode 1: Edge Matte Overlay (Red)
            push $unpre_src
            Expression {
                temp_name0 edge_m
                temp_expr0 {clamp((1 - clamp(min(a(x+parent.edgeErode,y), a(x-parent.edgeErode,y)) / max(0.01, 1 - parent.edgeInnerSoftness * 0.04), 0, 1)) * (a > 0.001 ? 1 : 0), 0, 1)}
                channel0 red
                expr0 {lerp(r, 1.0, edge_m * 0.8)}
                channel1 green
                expr1 {lerp(g, 0.0, edge_m * 0.8)}
                channel2 blue
                expr2 {lerp(b, 0.0, edge_m * 0.8)}
                channel3 alpha
                expr3 {a}
                name prevEdgeOverlay
                xpos 150
                ypos 360
            }
            set p1_edge [stack 0]

            # Preview Mode 3: Sampled Area Overlay
            push $unpre_src
            Expression {
                temp_name0 edge_m
                temp_expr0 {clamp((1 - clamp(min(a(x+parent.edgeErode,y), a(x-parent.edgeErode,y)) / max(0.01, 1 - parent.edgeInnerSoftness * 0.04), 0, 1)) * (a > 0.001 ? 1 : 0), 0, 1)}
                temp_name1 samp_m
                temp_expr1 {clamp(min(a(x+parent.edgeErode+parent.rotoSampleErode,y), a(x-parent.edgeErode-parent.rotoSampleErode,y)), 0, 1)}
                channel0 red
                expr0 {lerp(r * 0.35, 1.0, edge_m * 0.75)}
                channel1 green
                expr1 {lerp(g * 0.35 + samp_m * 0.55, 0.0, edge_m * 0.75)}
                channel2 blue
                expr2 {lerp(b * 0.35, 0.0, edge_m * 0.75)}
                channel3 alpha
                expr3 {a}
                name prevSampleOverlay
                xpos 300
                ypos 360
            }
            set p3_sample [stack 0]

            # Preview Mode 4: Sampled Area RGB (Solo on Black)
            push $unpre_src
            Expression {
                temp_name0 samp_m
                temp_expr0 {clamp(min(a(x+parent.edgeErode+parent.rotoSampleErode,y), a(x-parent.edgeErode-parent.rotoSampleErode,y)), 0, 1)}
                channel0 red
                expr0 {pow(max(0, r * parent.rotoSampleGain), 1.0 / max(0.1, parent.rotoSampleGamma)) * parent.edgeMultiply * samp_m}
                channel1 green
                expr1 {pow(max(0, g * parent.rotoSampleGain), 1.0 / max(0.1, parent.rotoSampleGamma)) * parent.edgeMultiply * samp_m}
                channel2 blue
                expr2 {pow(max(0, b * parent.rotoSampleGain), 1.0 / max(0.1, parent.rotoSampleGamma)) * parent.edgeMultiply * samp_m}
                channel3 alpha
                expr3 {samp_m}
                name prevSoloPatch
                xpos 450
                ypos 360
            }
            set p4_solo [stack 0]

            # Preview Switch
            # P4 (Solo), P3 (Sample), P2 (clean_unpre), P1 (Edge), P0 (Final)
            push $p4_solo
            push $p3_sample
            push $clean_unpre
            push $p1_edge
            push $p0_final
            Switch {
                inputs 5
                which {{parent.previewMode}}
                name prevSwitch
                xpos 0
                ypos 420
            }
            set switch_out [stack 0]

            # 7. Final Merge with Mask and Mix
            push $in_mask
            push $switch_out
            push $in_src
            Merge2 {
                inputs 2+1
                operation copy
                also_merge all
                invert_mask {{parent.invertMask}}
                mix {{parent.mix}}
                name finalMerge
                xpos 0
                ypos 480
            }

            Output {
                name Output1
                xpos 0
                ypos 540
            }
        """)

        # ---------------------------------------------------------------------
        # Clean UI Knobs
        # ---------------------------------------------------------------------
        method_k = nuke.Enumeration_Knob(
            "extendMethod",
            "Method",
            [
                "Clean Core Extend",
                "Eroded Inner Ring Sample",
                "Roto Sample & Fill",
                "Dark / Bright Fringe Kill Only",
            ],
        )
        method_k.setValue(0)

        preview_k = nuke.Enumeration_Knob(
            "previewMode",
            "Preview",
            [
                "Final Output",
                "Edge Matte Overlay (Red)",
                "Extended RGB (Unpremult)",
                "Sampled Area Overlay (Green=Sample, Red=Edge)",
                "Sampled Area RGB (Solo on Black)",
            ],
        )
        preview_k.setValue(0)

        pre_in_k = nuke.Boolean_Knob("premultipliedInput", "Premult Input", True)
        pre_in_k.setFlag(nuke.STARTLINE)
        pre_out_k = nuke.Boolean_Knob("premultipliedOutput", "Premult Output", True)
        pre_out_k.clearFlag(nuke.STARTLINE)

        # -- Extend & Sampling
        erode_k = nuke.Double_Knob("edgeErode", "Inward Reach")
        erode_k.setRange(0.0, 25.0)
        erode_k.setValue(3.0)
        erode_k.setTooltip("How far inward (in pixels) the treatment reaches before clean colour is sampled.")

        outward_k = nuke.Double_Knob("extendOutward", "Outward Reach")
        outward_k.setRange(0.0, 20.0)
        outward_k.setValue(2.0)
        outward_k.setTooltip("Extends edge treatment outward beyond the alpha perimeter to clear stubborn white rims.")

        dist_k = nuke.Double_Knob("extendDistance", "Sample Reach")
        dist_k.setRange(1.0, 60.0)
        dist_k.setValue(8.0)
        dist_k.setTooltip("Sampling distance inward to pull clean interior colour out to the edge.")

        soft_k = nuke.Double_Knob("edgeInnerSoftness", "Inner Softness")
        soft_k.setRange(0.0, 20.0)
        soft_k.setValue(3.0)

        ring_w_k = nuke.Double_Knob("sampleRingWidth", "Ring Width")
        ring_w_k.setRange(1.0, 30.0)
        ring_w_k.setValue(4.0)

        # -- Fringe Suppression
        base_str_k = nuke.Double_Knob("baseEdgeStrength", "All-Edge Strength")
        base_str_k.setRange(0.0, 1.0)
        base_str_k.setValue(1.0)

        dark_k = nuke.Double_Knob("clearDarkEdges", "Clear Dark")
        dark_k.setRange(0.0, 2.0)
        dark_k.setValue(1.0)

        bright_k = nuke.Double_Knob("clearBrightEdges", "Clear White")
        bright_k.setRange(0.0, 2.0)
        bright_k.setValue(1.0)

        thresh_k = nuke.Double_Knob("fringeThreshold", "Threshold")
        thresh_k.setRange(0.0, 0.2)
        thresh_k.setValue(0.01)

        sens_k = nuke.Double_Knob("fringeSensitivity", "Sensitivity")
        sens_k.setRange(1.0, 50.0)
        sens_k.setValue(20.0)

        # -- RotoSample Pipe
        roto_mode_k = nuke.Enumeration_Knob(
            "rotoMode",
            "Mode",
            [
                "Bad Edge to Repair (Cut & Fill)",
                "Clean Source Area to Sample (Spread Outward)",
            ],
        )
        roto_str_k = nuke.Double_Knob("rotoStrength", "Influence")
        roto_str_k.setRange(0.0, 1.0)
        roto_str_k.setValue(1.0)

        roto_spread_k = nuke.Double_Knob("rotoSampleSpread", "Spread")
        roto_spread_k.setRange(1.0, 150.0)
        roto_spread_k.setValue(35.0)

        roto_erode_k = nuke.Double_Knob("rotoSampleErode", "Sample Offset")
        roto_erode_k.setRange(-25.0, 25.0)
        roto_erode_k.setValue(0.0)

        roto_gain_k = nuke.Double_Knob("rotoSampleGain", "Gain")
        roto_gain_k.setRange(0.0, 3.0)
        roto_gain_k.setValue(1.0)

        roto_gamma_k = nuke.Double_Knob("rotoSampleGamma", "Gamma")
        roto_gamma_k.setRange(0.2, 3.0)
        roto_gamma_k.setValue(1.0)

        # -- Detail & Grade
        det_k = nuke.Double_Knob("recoverDetail", "Recover Grain")
        det_k.setRange(0.0, 1.0)
        det_k.setValue(0.25)

        e_mult_k = nuke.Double_Knob("edgeMultiply", "Brightness")
        e_mult_k.setRange(0.0, 2.0)
        e_mult_k.setValue(1.0)

        e_sat_k = nuke.Double_Knob("edgeSaturation", "Saturation")
        e_sat_k.setRange(0.0, 2.0)
        e_sat_k.setValue(1.0)

        # -- Mask & Mix
        inv_mask_k = nuke.Boolean_Knob("invertMask", "Invert Mask", False)
        inv_mask_k.setFlag(nuke.STARTLINE)

        mix_k = nuke.Double_Knob("mix", "Mix")
        mix_k.setRange(0.0, 1.0)
        mix_k.setValue(1.0)
        mix_k.clearFlag(nuke.STARTLINE)

        knobs_list = [
            method_k,
            preview_k,
            pre_in_k,
            pre_out_k,
            _divider("divExtend"),
            _section_heading("hdrExtend", "Extend & Sampling"),
            erode_k,
            outward_k,
            dist_k,
            soft_k,
            ring_w_k,
            _divider("divFringe"),
            _section_heading("hdrFringe", "Fringe Suppression"),
            base_str_k,
            dark_k,
            bright_k,
            thresh_k,
            sens_k,
            _divider("divRoto"),
            _section_heading("hdrRoto", "RotoSample Pipe"),
            roto_mode_k,
            roto_str_k,
            roto_spread_k,
            roto_erode_k,
            roto_gain_k,
            roto_gamma_k,
            _divider("divDetail"),
            _section_heading("hdrDetail", "Detail & Edge Grade"),
            det_k,
            e_mult_k,
            e_sat_k,
            _divider("divMask"),
            _section_heading("hdrMask", "Mask & Mix"),
            inv_mask_k,
            mix_k,
        ]

        for k in knobs_list:
            group.addKnob(k)
        _add_credit_knob(group)

        group["knobChanged"].setValue(
            "import sid_edge_extend as _se\n"
            "k = nuke.thisKnob()\n"
            "if k is not None and k.name() in ('extendMethod', 'rotoMode'):\n"
            "    _se._update_edge_extend_ui(nuke.thisNode())\n"
        )
        _update_edge_extend_ui(group)

    group["label"].setValue("[value extendMethod]")
    _connect_sid_group(group, selected)
    return group


# =============================================================================
# 2. ALPHA EDGE (Dedicated Alpha Processor: Grow/Shrink, Smooth, Contrast, Blur)
# =============================================================================

def make_alpha_edge():
    group, selected = _create_sid_group("AlphaEdge")
    with group:
        nuke.tcl("""
            Input {
                inputs 0
                name Source
                xpos 0
                ypos 0
            }
            set in_src [stack 0]

            Input {
                inputs 0
                name Mask
                xpos 300
                ypos 0
                number 1
            }
            set in_mask [stack 0]

            push $in_src
            Dilate {
                channels alpha
                size {{parent.alphaGrowShrink}}
                name dilNode
                xpos 0
                ypos 100
            }

            Blur {
                channels alpha
                size {{parent.alphaSmooth+parent.alphaEdgeBlur}}
                name blurNode
                xpos 0
                ypos 160
            }

            push $in_src
            MergeExpression {
                inputs 2
                temp_name0 normA
                temp_expr0 {clamp((A.a - parent.blackPoint) / max(0.001, parent.whitePoint - parent.blackPoint), 0, 1)}
                temp_name1 gamExp
                temp_expr1 {log(0.5) / log(clamp(parent.alphaSmoothCenter, 0.02, 0.98))}
                temp_name2 curvedA
                temp_expr2 {pow(normA, gamExp)}
                temp_name3 finalA
                temp_expr3 {clamp(0.5 + (curvedA - 0.5) * parent.alphaSmoothContrast, 0, 1)}
                channel0 red
                expr0 {parent.previewAlpha == 1 ? finalA : (parent.previewAlpha == 2 ? (B.a > finalA ? (B.a - finalA) : 0) : (parent.autoPremult ? (B.a > 0.0001 ? (B.r / max(0.001, B.a)) * finalA : B.r) : B.r))}
                channel1 green
                expr1 {parent.previewAlpha == 1 ? finalA : (parent.previewAlpha == 2 ? (finalA > B.a ? (finalA - B.a) : 0) : (parent.autoPremult ? (B.a > 0.0001 ? (B.g / max(0.001, B.a)) * finalA : B.g) : B.g))}
                channel2 blue
                expr2 {parent.previewAlpha == 1 ? finalA : (parent.previewAlpha == 2 ? 0 : (parent.autoPremult ? (B.a > 0.0001 ? (B.b / max(0.001, B.a)) * finalA : B.b) : B.b))}
                channel3 alpha
                expr3 {finalA}
                name alphaProcess
                xpos 0
                ypos 220
            }
            set proc_stream [stack 0]

            push $in_mask
            push $proc_stream
            push $in_src
            Merge2 {
                inputs 2+1
                operation copy
                also_merge all
                invert_mask {{parent.invertMask}}
                mix {{parent.mix}}
                name finalMerge
                xpos 0
                ypos 300
            }
            set mrg_stream [stack 0]

            push $proc_stream
            push $mrg_stream
            Switch {
                inputs 2
                which {{parent.previewAlpha>0}}
                name prevSwitch
                xpos 0
                ypos 360
            }

            Output {
                name Output1
                xpos 0
                ypos 420
            }
        """)

        prev_k = nuke.Enumeration_Knob(
            "previewAlpha",
            "Preview",
            [
                "Final Output (RGB + Processed Alpha)",
                "View Alpha as Grayscale",
                "Edge Delta Overlay (Green=Grown, Red=Shrunk)",
            ],
        )

        grow_k = nuke.Double_Knob("alphaGrowShrink", "Grow / Shrink")
        grow_k.setRange(-30.0, 30.0)
        grow_k.setValue(0.0)
        grow_k.setTooltip("Positive values expand / grow the matte outwards; negative values choke / shrink inwards.")

        smooth_k = nuke.Double_Knob("alphaSmooth", "Smooth Radius")
        smooth_k.setRange(0.0, 30.0)
        smooth_k.setValue(0.0)
        smooth_k.setTooltip("Smooths jagged pixel steps, edge jitter, and keying noise.")

        scont_k = nuke.Double_Knob("alphaSmoothContrast", "Sharpness")
        scont_k.setRange(0.0, 5.0)
        scont_k.setValue(1.0)
        scont_k.setTooltip("Adjusts edge transition sharpness. 1.0 is neutral; >1.0 sharpens; <1.0 softens.")

        scent_k = nuke.Double_Knob("alphaSmoothCenter", "Center Midpoint")
        scent_k.setRange(0.05, 0.95)
        scent_k.setValue(0.5)
        scent_k.setTooltip("Shifts edge midpoint balance. 0.5 is neutral; <0.5 expands core; >0.5 chokes soft edge.")

        blur_k = nuke.Double_Knob("alphaEdgeBlur", "Edge Blur")
        blur_k.setRange(0.0, 40.0)
        blur_k.setValue(0.0)
        blur_k.setTooltip("Applies an optical soft edge blur to the matte.")

        bp_k = nuke.Double_Knob("blackPoint", "Black Point")
        bp_k.setRange(0.0, 0.5)
        bp_k.setValue(0.0)
        bp_k.setTooltip("Clips dirty background key noise.")

        wp_k = nuke.Double_Knob("whitePoint", "White Point")
        wp_k.setRange(0.5, 1.0)
        wp_k.setValue(1.0)
        wp_k.setTooltip("Solidifies near-opaque subject core.")

        premult_k = nuke.Boolean_Knob("autoPremult", "Premultiply Output", False)
        premult_k.setFlag(nuke.STARTLINE)
        premult_k.setTooltip("When enabled, unpremultiplies RGB by input alpha and premultiplies by the newly processed alpha.")

        inv_mask_k = nuke.Boolean_Knob("invertMask", "Invert Mask", False)
        inv_mask_k.setFlag(nuke.STARTLINE)

        mix_k = nuke.Double_Knob("mix", "Mix")
        mix_k.setRange(0.0, 1.0)
        mix_k.setValue(1.0)
        mix_k.clearFlag(nuke.STARTLINE)

        knobs_list = [
            prev_k,
            _divider("divGrow"),
            _section_heading("hdrGrow", "Grow & Shrink"),
            grow_k,
            _divider("divSmooth"),
            _section_heading("hdrSmooth", "De-Jitter & Smooth"),
            smooth_k,
            scont_k,
            scent_k,
            _divider("divBlur"),
            _section_heading("hdrBlur", "Edge Blur"),
            blur_k,
            _divider("divLevels"),
            _section_heading("hdrLevels", "Alpha Levels"),
            bp_k,
            wp_k,
            _divider("divPremult"),
            premult_k,
            _divider("divMask"),
            _section_heading("hdrMask", "Mask & Mix"),
            inv_mask_k,
            mix_k,
        ]

        for k in knobs_list:
            group.addKnob(k)
        _add_credit_knob(group)

    group["label"].setValue("Grow: [value alphaGrowShrink] | Blur: [value alphaEdgeBlur]")
    _connect_sid_group(group, selected)
    return group


# =============================================================================
# 3. LIGHT WRAP (Original Multi-Tap Inward Wrap & BG Edge Mix)
# =============================================================================

def _update_light_wrap_ui(group):
    knobs = group.knobs()
    if "bgOutputMode" not in knobs:
        return
    mode = int(group["bgOutputMode"].getValue())
    if "premultipliedOutput" in knobs:
        knobs["premultipliedOutput"].setEnabled(mode != 1)


def make_light_wrap():
    group, selected = _create_sid_group("LightWrap")
    with group:
        nuke.tcl("""
            Input {
                inputs 0
                name FG
                xpos 0
                ypos 0
            }
            set in_fg [stack 0]

            Input {
                inputs 0
                name BG
                xpos 300
                ypos 0
                number 1
            }
            set in_bg [stack 0]

            Input {
                inputs 0
                name Mask
                xpos 600
                ypos 0
                number 2
            }
            set in_mask [stack 0]

            # 1. Native C++ Gaussian diffuse blur on BG plate
            push $in_bg
            Blur {
                channels rgba
                size {{parent.lwDiffuse}}
                name bgDiffuse
                xpos 300
                ypos 80
            }
            set bg_blurred [stack 0]

            # 2. Inward Wrap MergeExpression (B = in_fg, A = bg_blurred)
            push $bg_blurred
            push $in_fg
            MergeExpression {
                inputs 2
                temp_name0 fgL
                temp_expr0 {0.2126*B.r + 0.7152*B.g + 0.0722*B.b}
                temp_name1 bgL
                temp_expr1 {0.2126*A.r + 0.7152*A.g + 0.0722*A.b}
                temp_name2 wrapM
                temp_expr2 {(parent.enableBGWrap && (bgL > 0.00001 || A.a > 0.00001)) ? pow(clamp(1.0 - (0.125 * (B.a(x+max(1, parent.lwWidth),y) + B.a(x-max(1, parent.lwWidth),y) + B.a(x,y+max(1, parent.lwWidth)) + B.a(x,y-max(1, parent.lwWidth)) + B.a(x+max(1, parent.lwWidth)*0.7,y+max(1, parent.lwWidth)*0.7) + B.a(x-max(1, parent.lwWidth)*0.7,y+max(1, parent.lwWidth)*0.7) + B.a(x+max(1, parent.lwWidth)*0.7,y-max(1, parent.lwWidth)*0.7) + B.a(x-max(1, parent.lwWidth)*0.7,y-max(1, parent.lwWidth)*0.7))), 0, 1), max(0.2, parent.lwFalloff)) * B.a : 0}
                temp_name3 lwAmt
                temp_expr3 {wrapM * parent.lwIntensity * clamp((bgL - parent.lwThreshold) / max(0.01, 1.0 - parent.lwThreshold + 0.2), 0, 2)}
                channel0 red
                expr0 {parent.bgOutputMode == 2 ? ((lerp(bgL, A.r, parent.lwSaturation) * lwAmt) + (parent.bgEdgeMix > 0 ? lerp(bgL, A.r, parent.lwSaturation) * B.a * clamp(wrapM * parent.bgEdgeMix, 0, 1) : 0)) : ((parent.premultipliedOutput ? 1.0 : (B.a > 0.001 ? 1.0/B.a : 0.0)) * (parent.lwMode == 0 ? ((parent.premultipliedInput ? lerp(lerp(fgL, (B.a > 0.0001 ? B.r/max(0.001, B.a) : 0.0), parent.edgeSaturation), lerp(bgL, A.r, parent.lwSaturation), clamp(wrapM * parent.bgEdgeMix, 0, 1)) * B.a : lerp(lerp(fgL, B.r, parent.edgeSaturation), lerp(bgL, A.r, parent.lwSaturation), clamp(wrapM * parent.bgEdgeMix, 0, 1))) + (lerp(bgL, A.r, parent.lwSaturation) * lwAmt)) : (parent.lwMode == 1 ? ((parent.premultipliedInput ? lerp(lerp(fgL, (B.a > 0.0001 ? B.r/max(0.001, B.a) : 0.0), parent.edgeSaturation), lerp(bgL, A.r, parent.lwSaturation), clamp(wrapM * parent.bgEdgeMix, 0, 1)) * B.a : lerp(lerp(fgL, B.r, parent.edgeSaturation), lerp(bgL, A.r, parent.lwSaturation), clamp(wrapM * parent.bgEdgeMix, 0, 1))) + (lerp(bgL, A.r, parent.lwSaturation) * lwAmt) - ((parent.premultipliedInput ? lerp(lerp(fgL, (B.a > 0.0001 ? B.r/max(0.001, B.a) : 0.0), parent.edgeSaturation), lerp(bgL, A.r, parent.lwSaturation), clamp(wrapM * parent.bgEdgeMix, 0, 1)) * B.a : lerp(lerp(fgL, B.r, parent.edgeSaturation), lerp(bgL, A.r, parent.lwSaturation), clamp(wrapM * parent.bgEdgeMix, 0, 1))) * (lerp(bgL, A.r, parent.lwSaturation) * lwAmt)) / max(0.001, B.a)) : (parent.lwMode == 2 ? ((parent.premultipliedInput ? lerp(lerp(fgL, (B.a > 0.0001 ? B.r/max(0.001, B.a) : 0.0), parent.edgeSaturation), lerp(bgL, A.r, parent.lwSaturation), clamp(wrapM * parent.bgEdgeMix, 0, 1)) * B.a : lerp(lerp(fgL, B.r, parent.edgeSaturation), lerp(bgL, A.r, parent.lwSaturation), clamp(wrapM * parent.bgEdgeMix, 0, 1))) + (lerp(bgL, A.r, parent.lwSaturation) * lwAmt) * (1.0 - 0.5 * (parent.premultipliedInput ? lerp(lerp(fgL, (B.a > 0.0001 ? B.r/max(0.001, B.a) : 0.0), parent.edgeSaturation), lerp(bgL, A.r, parent.lwSaturation), clamp(wrapM * parent.bgEdgeMix, 0, 1)) * B.a : lerp(lerp(fgL, B.r, parent.edgeSaturation), lerp(bgL, A.r, parent.lwSaturation), clamp(wrapM * parent.bgEdgeMix, 0, 1))) / max(0.001, B.a))) : lerp((parent.premultipliedInput ? lerp(lerp(fgL, (B.a > 0.0001 ? B.r/max(0.001, B.a) : 0.0), parent.edgeSaturation), lerp(bgL, A.r, parent.lwSaturation), clamp(wrapM * parent.bgEdgeMix, 0, 1)) * B.a : lerp(lerp(fgL, B.r, parent.edgeSaturation), lerp(bgL, A.r, parent.lwSaturation), clamp(wrapM * parent.bgEdgeMix, 0, 1))), lerp(bgL, A.r, parent.lwSaturation) * B.a, clamp(lwAmt, 0, 1))))))}
                channel1 green
                expr1 {parent.bgOutputMode == 2 ? ((lerp(bgL, A.g, parent.lwSaturation) * lwAmt) + (parent.bgEdgeMix > 0 ? lerp(bgL, A.g, parent.lwSaturation) * B.a * clamp(wrapM * parent.bgEdgeMix, 0, 1) : 0)) : ((parent.premultipliedOutput ? 1.0 : (B.a > 0.001 ? 1.0/B.a : 0.0)) * (parent.lwMode == 0 ? ((parent.premultipliedInput ? lerp(lerp(fgL, (B.a > 0.0001 ? B.g/max(0.001, B.a) : 0.0), parent.edgeSaturation), lerp(bgL, A.g, parent.lwSaturation), clamp(wrapM * parent.bgEdgeMix, 0, 1)) * B.a : lerp(lerp(fgL, B.g, parent.edgeSaturation), lerp(bgL, A.g, parent.lwSaturation), clamp(wrapM * parent.bgEdgeMix, 0, 1))) + (lerp(bgL, A.g, parent.lwSaturation) * lwAmt)) : (parent.lwMode == 1 ? ((parent.premultipliedInput ? lerp(lerp(fgL, (B.a > 0.0001 ? B.g/max(0.001, B.a) : 0.0), parent.edgeSaturation), lerp(bgL, A.g, parent.lwSaturation), clamp(wrapM * parent.bgEdgeMix, 0, 1)) * B.a : lerp(lerp(fgL, B.g, parent.edgeSaturation), lerp(bgL, A.g, parent.lwSaturation), clamp(wrapM * parent.bgEdgeMix, 0, 1))) + (lerp(bgL, A.g, parent.lwSaturation) * lwAmt) - ((parent.premultipliedInput ? lerp(lerp(fgL, (B.a > 0.0001 ? B.g/max(0.001, B.a) : 0.0), parent.edgeSaturation), lerp(bgL, A.g, parent.lwSaturation), clamp(wrapM * parent.bgEdgeMix, 0, 1)) * B.a : lerp(lerp(fgL, B.g, parent.edgeSaturation), lerp(bgL, A.g, parent.lwSaturation), clamp(wrapM * parent.bgEdgeMix, 0, 1))) * (lerp(bgL, A.g, parent.lwSaturation) * lwAmt)) / max(0.001, B.a)) : (parent.lwMode == 2 ? ((parent.premultipliedInput ? lerp(lerp(fgL, (B.a > 0.0001 ? B.g/max(0.001, B.a) : 0.0), parent.edgeSaturation), lerp(bgL, A.g, parent.lwSaturation), clamp(wrapM * parent.bgEdgeMix, 0, 1)) * B.a : lerp(lerp(fgL, B.g, parent.edgeSaturation), lerp(bgL, A.g, parent.lwSaturation), clamp(wrapM * parent.bgEdgeMix, 0, 1))) + (lerp(bgL, A.g, parent.lwSaturation) * lwAmt) * (1.0 - 0.5 * (parent.premultipliedInput ? lerp(lerp(fgL, (B.a > 0.0001 ? B.g/max(0.001, B.a) : 0.0), parent.edgeSaturation), lerp(bgL, A.g, parent.lwSaturation), clamp(wrapM * parent.bgEdgeMix, 0, 1)) * B.a : lerp(lerp(fgL, B.g, parent.edgeSaturation), lerp(bgL, A.g, parent.lwSaturation), clamp(wrapM * parent.bgEdgeMix, 0, 1))) / max(0.001, B.a))) : lerp((parent.premultipliedInput ? lerp(lerp(fgL, (B.a > 0.0001 ? B.g/max(0.001, B.a) : 0.0), parent.edgeSaturation), lerp(bgL, A.g, parent.lwSaturation), clamp(wrapM * parent.bgEdgeMix, 0, 1)) * B.a : lerp(lerp(fgL, B.g, parent.edgeSaturation), lerp(bgL, A.g, parent.lwSaturation), clamp(wrapM * parent.bgEdgeMix, 0, 1))), lerp(bgL, A.g, parent.lwSaturation) * B.a, clamp(lwAmt, 0, 1))))))}
                channel2 blue
                expr2 {parent.bgOutputMode == 2 ? ((lerp(bgL, A.b, parent.lwSaturation) * lwAmt) + (parent.bgEdgeMix > 0 ? lerp(bgL, A.b, parent.lwSaturation) * B.a * clamp(wrapM * parent.bgEdgeMix, 0, 1) : 0)) : ((parent.premultipliedOutput ? 1.0 : (B.a > 0.001 ? 1.0/B.a : 0.0)) * (parent.lwMode == 0 ? ((parent.premultipliedInput ? lerp(lerp(fgL, (B.a > 0.0001 ? B.b/max(0.001, B.a) : 0.0), parent.edgeSaturation), lerp(bgL, A.b, parent.lwSaturation), clamp(wrapM * parent.bgEdgeMix, 0, 1)) * B.a : lerp(lerp(fgL, B.b, parent.edgeSaturation), lerp(bgL, A.b, parent.lwSaturation), clamp(wrapM * parent.bgEdgeMix, 0, 1))) + (lerp(bgL, A.b, parent.lwSaturation) * lwAmt)) : (parent.lwMode == 1 ? ((parent.premultipliedInput ? lerp(lerp(fgL, (B.a > 0.0001 ? B.b/max(0.001, B.a) : 0.0), parent.edgeSaturation), lerp(bgL, A.b, parent.lwSaturation), clamp(wrapM * parent.bgEdgeMix, 0, 1)) * B.a : lerp(lerp(fgL, B.b, parent.edgeSaturation), lerp(bgL, A.b, parent.lwSaturation), clamp(wrapM * parent.bgEdgeMix, 0, 1))) + (lerp(bgL, A.b, parent.lwSaturation) * lwAmt) - ((parent.premultipliedInput ? lerp(lerp(fgL, (B.a > 0.0001 ? B.b/max(0.001, B.a) : 0.0), parent.edgeSaturation), lerp(bgL, A.b, parent.lwSaturation), clamp(wrapM * parent.bgEdgeMix, 0, 1)) * B.a : lerp(lerp(fgL, B.b, parent.edgeSaturation), lerp(bgL, A.b, parent.lwSaturation), clamp(wrapM * parent.bgEdgeMix, 0, 1))) * (lerp(bgL, A.b, parent.lwSaturation) * lwAmt)) / max(0.001, B.a)) : (parent.lwMode == 2 ? ((parent.premultipliedInput ? lerp(lerp(fgL, (B.a > 0.0001 ? B.b/max(0.001, B.a) : 0.0), parent.edgeSaturation), lerp(bgL, A.b, parent.lwSaturation), clamp(wrapM * parent.bgEdgeMix, 0, 1)) * B.a : lerp(lerp(fgL, B.b, parent.edgeSaturation), lerp(bgL, A.b, parent.lwSaturation), clamp(wrapM * parent.bgEdgeMix, 0, 1))) + (lerp(bgL, A.b, parent.lwSaturation) * lwAmt) * (1.0 - 0.5 * (parent.premultipliedInput ? lerp(lerp(fgL, (B.a > 0.0001 ? B.b/max(0.001, B.a) : 0.0), parent.edgeSaturation), lerp(bgL, A.b, parent.lwSaturation), clamp(wrapM * parent.bgEdgeMix, 0, 1)) * B.a : lerp(lerp(fgL, B.b, parent.edgeSaturation), lerp(bgL, A.b, parent.lwSaturation), clamp(wrapM * parent.bgEdgeMix, 0, 1))) / max(0.001, B.a))) : lerp((parent.premultipliedInput ? lerp(lerp(fgL, (B.a > 0.0001 ? B.b/max(0.001, B.a) : 0.0), parent.edgeSaturation), lerp(bgL, A.b, parent.lwSaturation), clamp(wrapM * parent.bgEdgeMix, 0, 1)) * B.a : lerp(lerp(fgL, B.b, parent.edgeSaturation), lerp(bgL, A.b, parent.lwSaturation), clamp(wrapM * parent.bgEdgeMix, 0, 1))), lerp(bgL, A.b, parent.lwSaturation) * B.a, clamp(lwAmt, 0, 1))))))}
                channel3 alpha
                expr3 {parent.bgOutputMode == 2 ? (lwAmt + (parent.bgEdgeMix > 0 ? clamp(wrapM * parent.bgEdgeMix, 0, 1) : 0)) * B.a : B.a}
                name bgAndLightWrap
                xpos 0
                ypos 160
            }
            set wrapped_stream [stack 0]

            # 3. FG Over BG composite (wrapped FG over original sharp in_bg)
            push $in_bg
            push $wrapped_stream
            Merge2 {
                inputs 2
                operation over
                name compOver
                xpos 150
                ypos 220
            }
            set comp_stream [stack 0]

            # 4. Mode Switch: 0=FG Only, 1=FG Over BG, 2=Solo on Black
            push $comp_stream
            push $wrapped_stream
            Switch {
                inputs 2
                which {{parent.bgOutputMode==1}}
                name modeSwitch
                xpos 0
                ypos 280
            }
            set mode_out [stack 0]

            # 5. Mask & Mix
            push $in_mask
            push $mode_out
            push $in_fg
            Merge2 {
                inputs 2+1
                operation copy
                also_merge all
                invert_mask {{parent.invertMask}}
                mix {{parent.mix}}
                name finalMerge
                xpos 0
                ypos 340
            }

            Output {
                name Output1
                xpos 0
                ypos 400
            }
        """)

        # Knobs for LightWrap
        en_wrap_k = nuke.Boolean_Knob("enableBGWrap", "Enable Light Wrap", True)
        mode_k = nuke.Enumeration_Knob(
            "bgOutputMode",
            "Output Mode",
            [
                "FG Only",
                "FG Over BG (Composite)",
                "LightWrap Only (Solo on Black)",
            ],
        )
        mode_k.setValue(0)

        lw_mode_k = nuke.Enumeration_Knob(
            "lwMode",
            "Blend Mode",
            [
                "Add / Plus",
                "Screen",
                "SoftLight",
                "BG Bleed (Tint Only)",
            ],
        )
        lw_mode_k.setValue(0)

        pre_in_k = nuke.Boolean_Knob("premultipliedInput", "Premult Input", True)
        pre_in_k.setFlag(nuke.STARTLINE)
        pre_out_k = nuke.Boolean_Knob("premultipliedOutput", "Premult Output", True)
        pre_out_k.clearFlag(nuke.STARTLINE)

        int_k = nuke.Double_Knob("lwIntensity", "Intensity")
        int_k.setRange(0.0, 5.0)
        int_k.setValue(1.0)
        int_k.setTooltip("Controls the overall brightness/strength of the wrapped light.")

        width_k = nuke.Double_Knob("lwWidth", "Wrap Depth")
        width_k.setRange(1.0, 60.0)
        width_k.setValue(15.0)
        width_k.setTooltip("How far inward (in pixels) the light wrap penetrates into the subject.")

        diff_k = nuke.Double_Knob("lwDiffuse", "Diffuse Blur")
        diff_k.setRange(1.0, 80.0)
        diff_k.setValue(18.0)
        diff_k.setTooltip("Diffusion blur applied to the background plate.")

        mix_col_k = nuke.Double_Knob("bgEdgeMix", "BG Edge Mix")
        mix_col_k.setRange(0.0, 1.0)
        mix_col_k.setValue(0.0)
        mix_col_k.setTooltip("Mixes diffuse background colour directly into the inner edge transition.")

        fall_k = nuke.Double_Knob("lwFalloff", "Falloff Curve")
        fall_k.setRange(0.2, 4.0)
        fall_k.setValue(1.5)
        fall_k.setTooltip("Gamma curve of the inward falloff. Higher values concentrate light closer to the edge.")

        thr_k = nuke.Double_Knob("lwThreshold", "Luma Threshold")
        thr_k.setRange(0.0, 1.0)
        thr_k.setValue(0.0)
        thr_k.setTooltip("Background luminance threshold. Increase to wrap only bright highlights.")

        sat_k = nuke.Double_Knob("lwSaturation", "Saturation")
        sat_k.setRange(0.0, 2.0)
        sat_k.setValue(1.0)

        edge_sat_k = nuke.Double_Knob("edgeSaturation", "Edge Saturation")
        edge_sat_k.setRange(0.0, 2.0)
        edge_sat_k.setValue(1.0)
        edge_sat_k.setTooltip("Controls the saturation of the foreground edge prior to wrap.")

        inv_mask_k = nuke.Boolean_Knob("invertMask", "Invert Mask", False)
        inv_mask_k.setFlag(nuke.STARTLINE)

        mix_k = nuke.Double_Knob("mix", "Mix")
        mix_k.setRange(0.0, 1.0)
        mix_k.setValue(1.0)
        mix_k.clearFlag(nuke.STARTLINE)

        knobs_list = [
            en_wrap_k,
            mode_k,
            lw_mode_k,
            pre_in_k,
            pre_out_k,
            _divider("divWrap"),
            _section_heading("hdrWrap", "LightWrap Controls"),
            int_k,
            width_k,
            diff_k,
            fall_k,
            thr_k,
            sat_k,
            _divider("divEdgeMix"),
            _section_heading("hdrEdgeMix", "BG Edge Mix & Color"),
            mix_col_k,
            edge_sat_k,
            _divider("divMask"),
            _section_heading("hdrMask", "Mask & Mix"),
            inv_mask_k,
            mix_k,
        ]

        for k in knobs_list:
            group.addKnob(k)
        _add_credit_knob(group)

        group["knobChanged"].setValue(
            "import sid_edge_extend as _se\n"
            "k = nuke.thisKnob()\n"
            "if k is not None and k.name() in ('bgOutputMode',):\n"
            "    _se._update_light_wrap_ui(nuke.thisNode())\n"
        )
        _update_light_wrap_ui(group)

    group["label"].setValue("[value bgOutputMode]\n[value lwMode]")
    _connect_sid_group(group, selected)
    return group


# =============================================================================
# INSTALL MENU
# =============================================================================

def install_menu():
    m = nuke.menu("Nodes").addMenu("Sid", icon=None)
    m.addCommand("Edge Extend", make_edge_extend)
    m.addCommand("Alpha Edge", make_alpha_edge)
    m.addCommand("Light Wrap", make_light_wrap)

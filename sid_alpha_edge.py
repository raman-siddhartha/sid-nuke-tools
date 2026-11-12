# Sid VFX Suite for Nuke -- Professional Compositing Tools
# Contains:
#   Alpha Edge - Sub-pixel alpha processor (Grow/Shrink, De-Jitter, Contrast, Blur)
#
# Install:
#   Add to menu.py:
#       import sid_alpha_edge
#       sid_alpha_edge.install_menu()
#   Nodes > Sid then provides Alpha Edge.
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
# ALPHA EDGE (Dedicated Alpha Processor: Grow/Shrink, Smooth, Contrast, Blur)
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

            # Grow / Shrink in sub-pixel steps: Dilate only works in whole pixels, so the matte is the blend of
            # the two nearest whole-pixel dilations (e.g. 1.3 = 70% of 1px + 30% of 2px).
            push $in_src
            Dilate {
                channels alpha
                size {{int(parent.alphaGrowShrink)}}
                name dilNode
                xpos 0
                ypos 100
            }
            set dil_a [stack 0]
            push $in_src
            Dilate {
                channels alpha
                size {{int(parent.alphaGrowShrink)+(parent.alphaGrowShrink<0?-1:1)}}
                name dilNodeNext
                xpos 150
                ypos 100
            }
            push $dil_a
            MergeExpression {
                inputs 2
                channel0 red
                expr0 {B.r}
                channel1 green
                expr1 {B.g}
                channel2 blue
                expr2 {B.b}
                channel3 alpha
                expr3 {lerp(B.a,A.a,abs(parent.alphaGrowShrink-int(parent.alphaGrowShrink)))}
                name growMix
                xpos 0
                ypos 130
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
        grow_k.setTooltip("Positive values expand / grow the matte outwards; negative values choke / shrink inwards. Works in sub-pixel steps (0.1 px).")

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
# INSTALL MENU
# =============================================================================

def install_menu():
    m = nuke.menu("Nodes").addMenu("Sid", icon=None)
    m.addCommand("Alpha Edge", make_alpha_edge)

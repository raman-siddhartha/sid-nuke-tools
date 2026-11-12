# Sid VFX Suite for Nuke -- Edge Extend Blur
# Working copy of the ORIGINAL Edge Extend Blur (as released on GitHub, before the Edge Extend rewrite). Edit this
# file; the shipped modules are left untouched. Original header: copy of Edge Extend, with one
# addition: a final Edge Blur stage applied after every other operation
# (after Mask & Mix), adjustable in 0.1 steps.
#
# Install:
#   Add to menu.py:
#       import sid_edge_blur
#       sid_edge_blur.install_menu()
#   Nodes > Sid then also provides "Edge Extend Blur".
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
    """Dynamically shows/enables controls based on the Extend Method and the Use Sample checkbox."""
    knobs = group.knobs()
    if "extendMethod" not in knobs:
        return

    method = int(group["extendMethod"].getValue())
    use_sample = bool(group["useSample"].getValue()) if "useSample" in knobs else False

    if "sampleRingWidth" in knobs:
        show_ring = (method == 1)
        knobs["sampleRingWidth"].setVisible(show_ring)
        knobs["sampleRingWidth"].setEnabled(show_ring)

    if "baseEdgeStrength" in knobs:
        show_base = (method != 2)
        knobs["baseEdgeStrength"].setVisible(show_base)
        knobs["baseEdgeStrength"].setEnabled(show_base)

    for k in ("rotoStrength", "rotoFeather", "rotoSampleSpread", "rotoSampleGain", "rotoSampleGamma"):
        if k in knobs:
            knobs[k].setEnabled(use_sample)


def _snap_edge_blur(knob):
    """Snaps Edge Blur to 0.1 steps (and never below 0). Animated values are
    left alone so keyframes aren't rewritten. Only writes when the value
    actually changes, so the knobChanged it triggers stops immediately."""
    if knob.isAnimated():
        return
    v = knob.value()
    snapped = max(0.0, round(v * 10.0) / 10.0)
    if abs(snapped - v) > 1e-9:
        knob.setValue(snapped)


def _zone_cov(k):
    """Zone coverage at the k-th of 8 radii, from Inward Reach down to Inward Reach - Edge Blend. A pixel is covered
    (1) when some pixel within that radius has alpha below 1 (Inner Softness sets how far below), as the zone always
    was; averaging 8 radii turns the hard inner end of the zone into a ramp Edge Blend pixels wide, ending where
    Inward Reach ends."""
    r = "max(0.5,parent.edgeErode-parent.edgeBlend*%d/7)" % k
    d = "(%s*0.707)" % r
    core_min = ("min(B.a,min(min(min(B.a(x+{r},y),B.a(x-{r},y)),min(B.a(x,y+{r}),B.a(x,y-{r}))),"
                "min(min(B.a(x+{d},y+{d}),B.a(x-{d},y+{d})),min(B.a(x+{d},y-{d}),B.a(x-{d},y-{d})))))").format(r=r, d=d)
    return "clamp((1-%s)/max(0.01,parent.edgeInnerSoftness*0.1),0,1)" % core_min


_ZONE_TEMPS = ["(%s+%s)" % (_zone_cov(2 * j), _zone_cov(2 * j + 1)) for j in range(4)]
_ROTO_CUT = "0"
_EDGE_W = "clamp(max((z0+z1+z2+z3)/8,%s),0,1)" % _ROTO_CUT


def make_edge_extend():
    group, selected = _create_sid_group("EdgeExtendBlur")
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
                name Sample
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

            Input {
                inputs 0
                name Omit
                xpos 900
                ypos 0
                number 3
            }
            set in_omit [stack 0]

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
                temp_expr0 {1.0}
                temp_name1 weight
                temp_expr1 {pow(clamp(B.a, 0, 1), parent.edgeTrust) * roto_m}
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
            set pre_w [stack 0]

            # 3. 12-Tap Kernel Sampler (Pure fetches, zero math per tap)
            Expression {
                temp_name0 d1
                temp_expr0 {max(1, parent.edgeErode + (parent.extendMethod == 1 ? parent.sampleRingWidth * 0.5 + parent.extendOutward * 0.5 : (parent.extendDistance + parent.extendOutward) * 0.45))}
                temp_name1 d2
                temp_expr1 {max(2, parent.edgeErode + (parent.extendMethod == 1 ? parent.sampleRingWidth + parent.extendOutward : (parent.extendDistance + parent.extendOutward)))}
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
                temp_expr0 {1.0}
                temp_name1 rotoGam
                temp_expr1 {1.0}
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
                temp_name0 z0
                temp_expr0 {@ZT0@}
                temp_name1 z1
                temp_expr1 {@ZT1@}
                temp_name2 z2
                temp_expr2 {@ZT2@}
                temp_name3 z3
                temp_expr3 {@ZT3@}
                channel0 red
                expr0 {B.a > 0.001 ? lerp(B.r, A.r + (((B.r - A.r) * smoothstep(0.5 - max(0.0005, parent.grainSoftness * 0.5), 0.5 + max(0.0005, parent.grainSoftness * 0.5), B.a)) * parent.recoverDetail), clamp(max(@EDGEW@ * clamp((parent.extendMethod == 2 ? 0.0 : parent.baseEdgeStrength) + parent.clearDarkEdges*clamp((A.r - B.r - parent.fringeThreshold)*parent.fringeSensitivity, 0, 1) + parent.clearBrightEdges*clamp((B.r - A.r - parent.fringeThreshold)*parent.fringeSensitivity, 0, 1), 0, 1), 0), 0, 1)) : A.r}
                channel1 green
                expr1 {B.a > 0.001 ? lerp(B.g, A.g + (((B.g - A.g) * smoothstep(0.5 - max(0.0005, parent.grainSoftness * 0.5), 0.5 + max(0.0005, parent.grainSoftness * 0.5), B.a)) * parent.recoverDetail), clamp(max(@EDGEW@ * clamp((parent.extendMethod == 2 ? 0.0 : parent.baseEdgeStrength) + parent.clearDarkEdges*clamp((A.g - B.g - parent.fringeThreshold)*parent.fringeSensitivity, 0, 1) + parent.clearBrightEdges*clamp((B.g - A.g - parent.fringeThreshold)*parent.fringeSensitivity, 0, 1), 0, 1), 0), 0, 1)) : A.g}
                channel2 blue
                expr2 {B.a > 0.001 ? lerp(B.b, A.b + (((B.b - A.b) * smoothstep(0.5 - max(0.0005, parent.grainSoftness * 0.5), 0.5 + max(0.0005, parent.grainSoftness * 0.5), B.a)) * parent.recoverDetail), clamp(max(@EDGEW@ * clamp((parent.extendMethod == 2 ? 0.0 : parent.baseEdgeStrength) + parent.clearDarkEdges*clamp((A.b - B.b - parent.fringeThreshold)*parent.fringeSensitivity, 0, 1) + parent.clearBrightEdges*clamp((B.b - A.b - parent.fringeThreshold)*parent.fringeSensitivity, 0, 1), 0, 1), 0), 0, 1)) : A.b}
                channel3 alpha
                expr3 {B.a}
                name fringeCombiner
                xpos 0
                ypos 300
            }
            set clean_main [stack 0]

            # 7. Sample branch (only used when Use Sample is on): colour taken inside the Sample area, blurred
            # wide and divided by the blurred weight, then run through its own grade + combiner.
            push $in_roto
            push $unpre_src
            MergeExpression {
                inputs 2
                temp_name0 sw
                temp_expr0 {pow(clamp(B.a,0,1),parent.edgeTrust)*clamp(A.a,0.0001,1)}
                channel0 red
                expr0 {B.r*sw}
                channel1 green
                expr1 {B.g*sw}
                channel2 blue
                expr2 {B.b*sw}
                channel3 alpha
                expr3 {sw}
                name sampleWeight
                xpos 150
                ypos 120
            }
            Blur {
                size {{max(1,parent.rotoSampleSpread)}}
                crop false
                name sampleBlur
                xpos 150
                ypos 180
            }
            Expression {
                channel0 red
                expr0 {a > 0.00001 ? r / a : 0}
                channel1 green
                expr1 {a > 0.00001 ? g / a : 0}
                channel2 blue
                expr2 {a > 0.00001 ? b / a : 0}
                channel3 alpha
                expr3 {a > 0.00001 ? 1.0 : 0.0}
                name sampleFill
                xpos 150
                ypos 240
            }
            set samp_ext [stack 0]

            # 7. Sample branch: edge grade
            push $in_roto
            push $samp_ext
            MergeExpression {
                inputs 2
                temp_name0 rotoG
                temp_expr0 {parent.rotoSampleGain}
                temp_name1 rotoGam
                temp_expr1 {max(0.1, parent.rotoSampleGamma)}
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
                name edgeGradeS
                xpos 0
                ypos 240
            }
            set graded_s [stack 0]

            # 7b. Sample branch: fringe combiner
            push $graded_s
            push $unpre_src
            MergeExpression {
                inputs 2
                temp_name0 z0
                temp_expr0 {@ZT0@}
                temp_name1 z1
                temp_expr1 {@ZT1@}
                temp_name2 z2
                temp_expr2 {@ZT2@}
                temp_name3 z3
                temp_expr3 {@ZT3@}
                channel0 red
                expr0 {B.a > 0.001 ? lerp(B.r, A.r + (((B.r - A.r) * smoothstep(0.5 - max(0.0005, parent.grainSoftness * 0.5), 0.5 + max(0.0005, parent.grainSoftness * 0.5), B.a)) * parent.recoverDetail), clamp(max(@EDGEW@ * clamp((parent.extendMethod == 2 ? 0.0 : 1.0) + parent.clearDarkEdges*clamp((A.r - B.r - parent.fringeThreshold)*parent.fringeSensitivity, 0, 1) + parent.clearBrightEdges*clamp((B.r - A.r - parent.fringeThreshold)*parent.fringeSensitivity, 0, 1), 0, 1), 0), 0, 1)) : A.r}
                channel1 green
                expr1 {B.a > 0.001 ? lerp(B.g, A.g + (((B.g - A.g) * smoothstep(0.5 - max(0.0005, parent.grainSoftness * 0.5), 0.5 + max(0.0005, parent.grainSoftness * 0.5), B.a)) * parent.recoverDetail), clamp(max(@EDGEW@ * clamp((parent.extendMethod == 2 ? 0.0 : 1.0) + parent.clearDarkEdges*clamp((A.g - B.g - parent.fringeThreshold)*parent.fringeSensitivity, 0, 1) + parent.clearBrightEdges*clamp((B.g - A.g - parent.fringeThreshold)*parent.fringeSensitivity, 0, 1), 0, 1), 0), 0, 1)) : A.g}
                channel2 blue
                expr2 {B.a > 0.001 ? lerp(B.b, A.b + (((B.b - A.b) * smoothstep(0.5 - max(0.0005, parent.grainSoftness * 0.5), 0.5 + max(0.0005, parent.grainSoftness * 0.5), B.a)) * parent.recoverDetail), clamp(max(@EDGEW@ * clamp((parent.extendMethod == 2 ? 0.0 : 1.0) + parent.clearDarkEdges*clamp((A.b - B.b - parent.fringeThreshold)*parent.fringeSensitivity, 0, 1) + parent.clearBrightEdges*clamp((B.b - A.b - parent.fringeThreshold)*parent.fringeSensitivity, 0, 1), 0, 1), 0), 0, 1)) : A.b}
                channel3 alpha
                expr3 {B.a}
                name fringeCombinerS
                xpos 0
                ypos 300
            }
            set clean_samp [stack 0]

            # 8. KeyMix: the Sample branch over Clean Core, only inside the (feathered) Sample area
            push $in_roto
            Blur {
                size {{max(0.01,parent.rotoFeather)}}
                crop false
                name areaFeather
                xpos 300
                ypos 180
            }
            Expression {
                channel3 alpha
                expr3 {clamp(a*parent.rotoStrength,0,1)}
                name sampleMask
                xpos 300
                ypos 240
            }
            set samp_mask [stack 0]
            push $samp_mask
            push $clean_samp
            push $clean_main
            Merge2 {
                inputs 2+1
                operation copy
                also_merge all
                disable {{!parent.useSample}}
                name sampleKeymix
                xpos 150
                ypos 330
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
                temp_expr1 {clamp(min(a(x+parent.edgeErode,y), a(x-parent.edgeErode,y)), 0, 1)}
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
                temp_expr0 {clamp(min(a(x+parent.edgeErode,y), a(x-parent.edgeErode,y)), 0, 1)}
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
                which {{parent.showEdgeMatte?1:parent.previewMode}}
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
            set merged [stack 0]

            # 8. Edge Blur -- last step, after mask & mix. RGB only: the
            # output alpha is never changed. The image is blurred
            # premultiplied (premultiplying first when Premult Output is
            # off), then divided by the blurred alpha -- an alpha-weighted
            # colour blur that pulls in no black from outside the matte --
            # and multiplied back by the ORIGINAL alpha when the output is
            # premultiplied, so no colour spills past the unchanged matte.
            # Blended in only inside a band around the edge: 4a(1-a) of the
            # blurred alpha peaks at 1 on the edge and falls to 0 in the
            # solid core and empty background, widening with blur size.
            # Size 0 = bypassed. Final Output only, so previews stay readable.
            push $merged
            Premult {
                disable {{parent.premultipliedOutput||parent.edgeBlurSize<=0||parent.previewMode!=0||parent.showEdgeMatte}}
                name edgeBlurPremult
                xpos 150
                ypos 510
            }
            Blur {
                channels rgba
                size {{parent.edgeBlurSize}}
                disable {{parent.edgeBlurSize<=0||parent.previewMode!=0||parent.showEdgeMatte}}
                name edgeBlurBlur
                xpos 150
                ypos 540
            }
            set blurred [stack 0]

            push $blurred
            push $merged
            MergeExpression {
                inputs 2
                temp_name0 em
                temp_expr0 {A.a > 0.0001 ? clamp(4 * A.a * (1 - A.a), 0, 1) : 0}
                temp_name1 ia
                temp_expr1 {A.a > 0.0001 ? 1.0 / A.a : 0}
                temp_name2 k
                temp_expr2 {parent.premultipliedOutput ? B.a : 1.0}
                channel0 red
                expr0 {lerp(B.r, A.r * ia * k, em)}
                channel1 green
                expr1 {lerp(B.g, A.g * ia * k, em)}
                channel2 blue
                expr2 {lerp(B.b, A.b * ia * k, em)}
                channel3 alpha
                expr3 {B.a}
                disable {{parent.edgeBlurSize<=0||parent.previewMode!=0||parent.showEdgeMatte}}
                name edgeBlurMix
                xpos 0
                ypos 600
            }
            set final_out [stack 0]

            # 9. Omit -- where the alpha of the Omit input is on, the original image comes back (as it would
            # be output: premultiplied again when Premult Output is on), so nothing is treated there. The treated
            # image is A and the original is B, with the mask inverted: a Merge2 whose mask input is not connected
            # applies A everywhere, so with no Omit connected the whole image is treated.
            push $unpre_src
            Premult {
                disable {{!parent.premultipliedOutput}}
                name omitOriginal
                xpos 300
                ypos 600
            }
            set omit_orig [stack 0]

            push $in_omit
            push $final_out
            push $omit_orig
            Merge2 {
                inputs 2+1
                operation copy
                also_merge all
                invert_mask true
                name omitMerge
                xpos 0
                ypos 660
            }

            Output {
                name Output1
                xpos 0
                ypos 720
            }
        """.replace("@EDGEW@", _EDGE_W).replace("@ZT0@", _ZONE_TEMPS[0]).replace("@ZT1@", _ZONE_TEMPS[1])
           .replace("@ZT2@", _ZONE_TEMPS[2]).replace("@ZT3@", _ZONE_TEMPS[3]))

        # ---------------------------------------------------------------------
        # Clean UI Knobs
        # ---------------------------------------------------------------------
        method_k = nuke.Enumeration_Knob(
            "extendMethod",
            "Method",
            [
                "Clean Core Extend",
                "Eroded Inner Ring Sample",
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

        show_matte_k = nuke.Boolean_Knob("showEdgeMatte", "Show Edge Matte")
        show_matte_k.setFlag(nuke.STARTLINE)
        show_matte_k.setTooltip("Shows the Edge Matte Overlay (red = the edge band being treated) without changing the "
                                "Preview menu.")

        pre_in_k = nuke.Boolean_Knob("premultipliedInput", "Premult Input")
        pre_in_k.setFlag(nuke.STARTLINE)
        pre_out_k = nuke.Boolean_Knob("premultipliedOutput", "Premult Output")
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

        blend_k = nuke.Double_Knob("edgeBlend", "Edge Blend")
        blend_k.setRange(0.0, 30.0)
        blend_k.setValue(0.0)
        blend_k.setTooltip("Feathers where the treatment ends on the inside, so the cleaned edge fades into the "
                           "untouched image instead of showing a hard line. The treatment ends where Inward Reach ends "
                           "and fades in over this many pixels before it. The image is not blurred. 0 = off.")

        ring_w_k = nuke.Double_Knob("sampleRingWidth", "Ring Width")
        ring_w_k.setRange(1.0, 30.0)
        ring_w_k.setValue(4.0)

        # -- Fringe Suppression
        trust_k = nuke.Double_Knob("edgeTrust", "Clean Bias")
        trust_k.setRange(1.0, 8.0)
        trust_k.setValue(3.0)
        trust_k.setTooltip("How strongly clean (solid) pixels outweigh the contaminated edge pixels when the replacement "
                           "colour is made. Raise it if a dark or bright edge still shows through the fill. 1.5 is the "
                           "old behaviour.")

        base_str_k = nuke.Double_Knob("baseEdgeStrength", "All-Edge Strength")
        base_str_k.setRange(0.0, 1.0)
        base_str_k.setValue(0.5)
        base_str_k.setTooltip("How much of the edge band is replaced whatever its colour. Clear Dark and Clear White "
                              "add to it, so lower it to let them decide.")

        dark_k = nuke.Double_Knob("clearDarkEdges", "Clear Dark")
        dark_k.setRange(0.0, 2.0)
        dark_k.setValue(1.0)
        dark_k.setTooltip("How strongly edge pixels that are darker than the clean colour are replaced. 0 = not at all.")

        bright_k = nuke.Double_Knob("clearBrightEdges", "Clear White")
        bright_k.setRange(0.0, 2.0)
        bright_k.setValue(1.0)
        bright_k.setTooltip("How strongly edge pixels that are brighter than the clean colour are replaced. 0 = not at all.")

        thresh_k = nuke.Double_Knob("fringeThreshold", "Threshold")
        thresh_k.setRange(0.0, 0.2)
        thresh_k.setValue(0.01)

        sens_k = nuke.Double_Knob("fringeSensitivity", "Sensitivity")
        sens_k.setRange(1.0, 50.0)
        sens_k.setValue(20.0)

        # -- Sample pipe
        use_sample_k = nuke.Boolean_Knob("useSample", "Use Sample")
        use_sample_k.setFlag(nuke.STARTLINE)
        use_sample_k.setTooltip("Mixes the Sample result over Clean Core, only inside the area drawn on the Sample "
                                "input (a KeyMix). Off = the Sample input is ignored.")
        roto_str_k = nuke.Double_Knob("rotoStrength", "Influence")
        roto_str_k.setRange(0.0, 1.0)
        roto_str_k.setValue(1.0)

        roto_feather_k = nuke.Double_Knob("rotoFeather", "Area Feather")
        roto_feather_k.setRange(0.0, 100.0)
        roto_feather_k.setValue(10.0)
        roto_feather_k.setTooltip("Softens the edge of the Sample area. The sample is only mixed over Clean Core "
                                  "Extend inside this area.")
        roto_spread_k = nuke.Double_Knob("rotoSampleSpread", "Fill Softness")
        roto_spread_k.setRange(1.0, 150.0)
        roto_spread_k.setValue(35.0)

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
        det_k.setTooltip("Brings the original pixels (grain) back into the replaced colour.")

        grain_soft_k = nuke.Double_Knob("grainSoftness", "Grain Softness")
        grain_soft_k.setRange(0.0, 1.0)
        grain_soft_k.setValue(0.5)
        grain_soft_k.setTooltip("How gradually Recover Grain fades in across the alpha edge. 0 = switches on at alpha 0.5, "
                                "which can leave a hard edge; 1 = fades in over the whole alpha range. The image is not blurred.")

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

        # -- Edge Blur (applied last). Small slider range keeps drag steps
        # fine; knobChanged also snaps every value to 0.1 increments.
        # Larger values can still be typed in.
        eblur_k = nuke.Double_Knob("edgeBlurSize", "Edge Blur")
        eblur_k.setRange(0.0, 10.0)
        eblur_k.setValue(0.0)
        eblur_k.setTooltip("Blurs only the alpha edge band, after every other step "
                           "(including Mask & Mix). Steps of 0.1. 0 = off.")

        knobs_list = [
            method_k,
            preview_k,
            show_matte_k,
            pre_in_k,
            pre_out_k,
            _divider("divExtend"),
            _section_heading("hdrExtend", "Extend & Sampling"),
            erode_k,
            outward_k,
            dist_k,
            soft_k,
            blend_k,
            ring_w_k,
            _divider("divFringe"),
            _section_heading("hdrFringe", "Fringe Suppression"),
            trust_k,
            base_str_k,
            dark_k,
            bright_k,
            thresh_k,
            sens_k,
            _divider("divRoto"),
            _section_heading("hdrRoto", "Sample"),
            use_sample_k,
            roto_str_k,
            roto_feather_k,
            roto_spread_k,
            roto_gain_k,
            roto_gamma_k,
            _divider("divDetail"),
            _section_heading("hdrDetail", "Detail & Edge Grade"),
            det_k,
            grain_soft_k,
            e_mult_k,
            e_sat_k,
            _divider("divMask"),
            _section_heading("hdrMask", "Mask & Mix"),
            inv_mask_k,
            mix_k,
            _divider("divEdgeBlur"),
            _section_heading("hdrEdgeBlur", "Edge Blur (Final)"),
            eblur_k,
        ]

        for k in knobs_list:
            group.addKnob(k)
        _add_credit_knob(group)

        group["knobChanged"].setValue(
            "import sid_edge_blur as _se\n"
            "k = nuke.thisKnob()\n"
            "if k is not None and k.name() in ('extendMethod', 'useSample'):\n"
            "    _se._update_edge_extend_ui(nuke.thisNode())\n"
            "elif k is not None and k.name() == 'edgeBlurSize':\n"
            "    _se._snap_edge_blur(k)\n"
        )
        _update_edge_extend_ui(group)

    group["label"].setValue("[value extendMethod]\nBlur: [value edgeBlurSize]")
    _connect_sid_group(group, selected)
    return group


# =============================================================================
# INSTALL MENU
# =============================================================================

def _on_group_create():
    """Re-applies which controls are shown / enabled when a saved script is opened (Nuke does not keep that)."""
    try:
        node = nuke.thisNode()
        if "useSample" in node.knobs() and "extendMethod" in node.knobs():
            _update_edge_extend_ui(node)
    except Exception:
        pass


def install_menu():
    m = nuke.menu("Nodes").addMenu("Sid", icon=None)
    m.addCommand("Edge Extend Blur", make_edge_extend)
    nuke.addOnCreate(_on_group_create, nodeClass="Group")

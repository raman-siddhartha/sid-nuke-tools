# Sid VFX Suite for Nuke -- Light Wrap
# Normal-driven light wrap. The BG light is not blurred in place: for every pixel near the FG edge the wrap colour is
# fetched from the BG along the edge NORMAL (the direction pointing out of the FG, taken from the gradient of a
# smoothed alpha), so the light wraps around the shape instead of forming rings. Wrap amount falls off smoothly with
# depth from a Gaussian-smoothed alpha, so there are no sample-pattern artefacts.
#
# Install:
#   Add to menu.py:
#       import sid_light_wrap
#       sid_light_wrap.install_menu()
#   Nodes > Sid then provides "Light Wrap".
#

import nuke


def _checked_knob(name, label):
    """A checkbox that is ON by default and keeps its state when the script is saved and reopened. A Boolean_Knob
    built with a True constructor default is not written to the script (Nuke takes True as its default) and comes
    back OFF, so the value is set after construction instead."""
    k = nuke.Boolean_Knob(name, label)
    k.setValue(True)
    return k


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
# LIGHT WRAP 2
# =============================================================================

def _update_light_wrap_ui(group):
    """Greys out the controls that do nothing in the current settings, so only the active ones can be touched."""
    knobs = group.knobs()
    if "lwCoverage" not in knobs:
        return
    cov = int(group["lwCoverage"].getValue())
    src = int(group["lwNormalSource"].getValue())
    relight = bool(group["lwRelight"].getValue())
    use_in = bool(group["lwUseNormalsInput"].getValue())
    state = {
        "lwEdgeWidth": cov == 0,        # only the Edge Only band uses it
        "lwWidth": cov == 1,            # only Grow Inwards uses it
        "lwFalloff": cov != 2,          # Whole Object has no falloff
        "lwDetailStrength": src != 0,   # the Alpha Dome ignores the image
        "lwDetailBlur": src != 0,
        "lwNormalsEncoded": use_in,
    }
    for k in ("lwLightAz", "lwLightElev", "lwLightColor", "lwLightIntensity", "lwLightWrap", "lwAmbient",
              "lwRelightAmount"):
        state[k] = relight
    for name, on in state.items():
        if name in knobs:
            knobs[name].setEnabled(on)


def _on_group_create():
    """Re-applies the greyed-out state when a saved script is opened (Nuke does not keep it)."""
    try:
        node = nuke.thisNode()
        if "lwCoverage" in node.knobs():
            _update_light_wrap_ui(node)
    except Exception:
        pass


def _channel_expr(c):
    """Final colour expression for channel c (r/g/b). Temps: fgL (FG luma, straight), wL (wrap luma), wM (wrap
    amount incl. enable), amt (wrap strength after intensity and luma threshold)."""
    F = "(parent.premultipliedInput ? (B.a > 0.0001 ? B.%s / B.a : 0) : B.%s)" % (c, c)
    Wc = "lerp(wL, A.%s, parent.lwSaturation)" % c
    base = "lerp(lerp(fgL, %s, parent.edgeSaturation), %s, clamp(wM * parent.bgEdgeMix, 0, 1))" % (F, Wc)
    m0 = "(%s + %s * amt)" % (base, Wc)
    m1 = "(1 - (1 - %s) * (1 - clamp(%s * amt, 0, 1)))" % (base, Wc)
    m2 = "(%s + %s * amt * (1 - 0.5 * %s))" % (base, Wc, base)
    m3 = "lerp(%s, %s, clamp(amt, 0, 1))" % (base, Wc)
    comp = "(parent.lwMode == 0 ? %s : (parent.lwMode == 1 ? %s : (parent.lwMode == 2 ? %s : %s)))" % (m0, m1, m2, m3)
    solo = "(%s * (amt + clamp(wM * parent.bgEdgeMix, 0, 1)))" % Wc
    return "parent.bgOutputMode == 2 ? %s : (%s * (parent.premultipliedOutput ? B.a : 1.0))" % (solo, comp)


_TCL = """
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

            Input {
                inputs 0
                name Normals
                xpos 900
                ypos 0
                number 3
            }
            set in_norm [stack 0]

            # 1. Diffuse BG (Gaussian) -- the light source
            push $in_bg
            Blur {
                channels rgba
                size {{parent.lwDiffuse}}
                name bgDiffuse
                xpos 300
                ypos 80
            }
            set bg_blurred [stack 0]

            # 2. Smooth FG alpha for the wrap DEPTH (Gaussian, so the falloff has no sample pattern)
            push $in_fg
            Blur {
                channels alpha
                size {{parent.lwCoverage==0?max(1,parent.lwEdgeWidth):max(1,parent.lwWidth)}}
                name depthBlur
                xpos 0
                ypos 80
            }
            set depth_blur [stack 0]

            # 3. NORMALS for the WHOLE FG. The alpha smoothed at four scales (x1, x3, x9, x27 of Normal Blur) is a
            # soft "dome". Direction = gradient of the plain sum (the fine scale follows the contour at the edge, the
            # coarse ones keep a direction deep inside). Tilt = slope of the sum weighted by sqrt(size) x Normal Height, so
            # the tilt keeps growing across the whole object (like a rounded dome). n = (nx, ny, nz), unit length.
            push $in_fg
            Blur {
                channels alpha
                size {{max(0.5,parent.lwNormalBlur*1)}}
                name normalBlur0
                xpos 150
                ypos 80
            }
            set nb0 [stack 0]
            push $in_fg
            Blur {
                channels alpha
                size {{max(0.5,parent.lwNormalBlur*3)}}
                name normalBlur1
                xpos 300
                ypos 80
            }
            set nb1 [stack 0]
            push $in_fg
            Blur {
                channels alpha
                size {{max(0.5,parent.lwNormalBlur*9)}}
                name normalBlur2
                xpos 450
                ypos 80
            }
            set nb2 [stack 0]
            push $in_fg
            Blur {
                channels alpha
                size {{max(0.5,parent.lwNormalBlur*27)}}
                name normalBlur3
                xpos 600
                ypos 80
            }
            set nb3 [stack 0]
            push $nb0
            push $nb1
            MergeExpression {
                inputs 2
                channel0 red
                expr0 {0}
                channel1 green
                expr1 {0}
                channel2 blue
                expr2 {0}
                channel3 alpha
                expr3 {A.a+B.a}
                name domeSum01
                xpos 150
                ypos 110
            }
            push $nb2
            MergeExpression {
                inputs 2
                channel0 red
                expr0 {0}
                channel1 green
                expr1 {0}
                channel2 blue
                expr2 {0}
                channel3 alpha
                expr3 {A.a+B.a}
                name domeSum012
                xpos 150
                ypos 125
            }
            push $nb3
            MergeExpression {
                inputs 2
                channel0 red
                expr0 {0}
                channel1 green
                expr1 {0}
                channel2 blue
                expr2 {0}
                channel3 alpha
                expr3 {A.a+B.a}
                name domeSum
                xpos 150
                ypos 140
            }
            set dome_dir [stack 0]
            push $nb0
            push $nb1
            MergeExpression {
                inputs 2
                channel0 red
                expr0 {0}
                channel1 green
                expr1 {0}
                channel2 blue
                expr2 {0}
                channel3 alpha
                expr3 {A.a*parent.lwNormalBlur+B.a*parent.lwNormalBlur*1.732}
                name tiltSum01
                xpos 600
                ypos 110
            }
            push $nb2
            MergeExpression {
                inputs 2
                channel0 red
                expr0 {0}
                channel1 green
                expr1 {0}
                channel2 blue
                expr2 {0}
                channel3 alpha
                expr3 {A.a+B.a*parent.lwNormalBlur*3}
                name tiltSum012
                xpos 600
                ypos 125
            }
            push $nb3
            MergeExpression {
                inputs 2
                channel0 red
                expr0 {0}
                channel1 green
                expr1 {0}
                channel2 blue
                expr2 {0}
                channel3 alpha
                expr3 {A.a+B.a*parent.lwNormalBlur*5.196}
                name tiltSum
                xpos 600
                ypos 140
            }
            set dome_tilt [stack 0]
            push $dome_dir
            push $dome_tilt
            MergeExpression {
                inputs 2
                temp_name0 dx
                temp_expr0 {(A.a(x-1,y)-A.a(x+1,y))*(parent.lwFlipNormals?-1:1)}
                temp_name1 dy
                temp_expr1 {(A.a(x,y-1)-A.a(x,y+1))*(parent.lwFlipNormals?-1:1)}
                temp_name2 dl
                temp_expr2 {sqrt(dx*dx+dy*dy)}
                temp_name3 hm
                temp_expr3 {parent.lwNormalHeight*sqrt(pow(B.a(x-1,y)-B.a(x+1,y),2)+pow(B.a(x,y-1)-B.a(x,y+1),2))}
                channel0 red
                expr0 {dl>0.0000001?dx/dl*hm/sqrt(1+hm*hm):0}
                channel1 green
                expr1 {dl>0.0000001?dy/dl*hm/sqrt(1+hm*hm):0}
                channel2 blue
                expr2 {1/sqrt(1+hm*hm)}
                channel3 alpha
                expr3 {1}
                name edgeNormals
                xpos 150
                ypos 160
            }
            set dome_n [stack 0]

            # 3a. IMAGE-DETAIL normals: the FG luminance (bright = raised) is the height. Normalised convolution
            # (blur of L*alpha / blur of alpha) fills outside the matte so the silhouette gives no false edge. Two
            # scales (Detail Smoothing x1 and x3); slope = -gradient x Detail Strength x Detail Smoothing.
            push $in_fg
            Expression {
                temp_name0 lm
                temp_expr0 {0.2126*r+0.7152*g+0.0722*b}
                channel0 red
                expr0 {parent.premultipliedInput ? lm : lm*a}
                channel1 green
                expr1 {0}
                channel2 blue
                expr2 {0}
                channel3 alpha
                expr3 {a}
                name lumNum
                xpos 600
                ypos 80
            }
            set lum_num [stack 0]
            Blur {
                channels rgba
                size {{max(0.5,parent.lwDetailBlur)}}
                name lumBlurFine
                xpos 600
                ypos 110
            }
            Expression {
                channel0 red
                expr0 {a>0.00001?r/a:0}
                channel1 green
                expr1 {0}
                channel2 blue
                expr2 {0}
                channel3 alpha
                expr3 {1}
                name lumFillFine
                xpos 600
                ypos 140
            }
            set lf1 [stack 0]
            push $lum_num
            Blur {
                channels rgba
                size {{max(0.5,parent.lwDetailBlur*3)}}
                name lumBlurCoarse
                xpos 750
                ypos 110
            }
            Expression {
                channel0 red
                expr0 {a>0.00001?r/a:0}
                channel1 green
                expr1 {0}
                channel2 blue
                expr2 {0}
                channel3 alpha
                expr3 {1}
                name lumFillCoarse
                xpos 750
                ypos 140
            }
            set lf3 [stack 0]
            push $lf1
            push $lf3
            MergeExpression {
                inputs 2
                temp_name0 gx
                temp_expr0 {(A.r(x+1,y)-A.r(x-1,y)+B.r(x+1,y)-B.r(x-1,y))*0.5}
                temp_name1 gy
                temp_expr1 {(A.r(x,y+1)-A.r(x,y-1)+B.r(x,y+1)-B.r(x,y-1))*0.5}
                channel0 red
                expr0 {-gx*parent.lwDetailStrength*parent.lwDetailBlur}
                channel1 green
                expr1 {-gy*parent.lwDetailStrength*parent.lwDetailBlur}
                channel2 blue
                expr2 {0}
                channel3 alpha
                expr3 {1}
                name detailSlope
                xpos 600
                ypos 180
            }
            set detail_s [stack 0]

            # 3b. Compose in slope space: Normal Source 0 = alpha dome only, 1 = dome + image detail, 2 = image detail only
            push $dome_n
            push $detail_s
            MergeExpression {
                inputs 2
                temp_name0 sx
                temp_expr0 {(parent.lwNormalSource==2?0:1)*A.r/max(A.b,0.0001)+(parent.lwNormalSource==0?0:1)*B.r*(parent.lwFlipNormals?-1:1)}
                temp_name1 sy
                temp_expr1 {(parent.lwNormalSource==2?0:1)*A.g/max(A.b,0.0001)+(parent.lwNormalSource==0?0:1)*B.g*(parent.lwFlipNormals?-1:1)}
                temp_name2 nzz
                temp_expr2 {1/sqrt(1+sx*sx+sy*sy)}
                channel0 red
                expr0 {sx*nzz}
                channel1 green
                expr1 {sy*nzz}
                channel2 blue
                expr2 {nzz}
                channel3 alpha
                expr3 {1}
                name normalsCompose
                xpos 150
                ypos 170
            }
            Blur {
                channels rgb
                size {{max(0.01,parent.lwNormalSmooth)}}
                name normalsSmooth
                xpos 150
                ypos 180
            }
            Expression {
                temp_name0 nl
                temp_expr0 {sqrt(r*r+g*g+b*b)}
                channel0 red
                expr0 {nl>0.0001?r/nl:0}
                channel1 green
                expr1 {nl>0.0001?g/nl:0}
                channel2 blue
                expr2 {nl>0.0001?b/nl:1}
                channel3 alpha
                expr3 {1}
                name normalsFinal
                xpos 150
                ypos 200
            }
            set norm_calc [stack 0]

            # 3c. Optional external normals (Normals input + Use Normals Input): replaces the computed ones
            push $in_norm
            Expression {
                temp_name0 ex
                temp_expr0 {parent.lwNormalsEncoded?2*r-1:r}
                temp_name1 ey
                temp_expr1 {parent.lwNormalsEncoded?2*g-1:g}
                temp_name2 ez
                temp_expr2 {parent.lwNormalsEncoded?2*b-1:b}
                temp_name3 el
                temp_expr3 {sqrt(ex*ex+ey*ey+ez*ez)}
                channel0 red
                expr0 {el>0.0001?ex*(parent.lwFlipNormals?-1:1)/el:0}
                channel1 green
                expr1 {el>0.0001?ey*(parent.lwFlipNormals?-1:1)/el:0}
                channel2 blue
                expr2 {el>0.0001?ez/el:1}
                channel3 alpha
                expr3 {1}
                name normalsExt
                xpos 300
                ypos 200
            }
            push $norm_calc
            Switch {
                inputs 2
                which {{parent.lwUseNormalsInput}}
                name normalsSwitch
                xpos 150
                ypos 230
            }
            set normals [stack 0]

            # 4. Info image: r,g = normal tilt (nx,ny) x Normal Strength, b = wrap amount (Coverage: edge band / grown
            # inwards / whole object), a = 1
            push $normals
            push $depth_blur
            MergeExpression {
                inputs 2
                channel0 red
                expr0 {A.r*parent.lwNormalStrength}
                channel1 green
                expr1 {A.g*parent.lwNormalStrength}
                channel2 blue
                expr2 {parent.lwCoverage==2?1:pow(1-smoothstep(0.45,1.0,B.a),parent.lwFalloff)}
                channel3 alpha
                expr3 {1}
                name wrapInfo
                xpos 150
                ypos 200
            }
            Blur {
                channels blue
                size {{max(0.01,parent.lwWrapSoft)}}
                name wrapSoftBlur
                xpos 150
                ypos 215
            }
            set info [stack 0]

            # 5. Wrap colour: the diffuse BG fetched along the normal, bilinear (3 taps on one line, no blockiness)
            push $info
            push $bg_blurred
            MergeExpression {
                inputs 2
                temp_name0 ix
                temp_expr0 {floor(x+A.r*parent.lwReach*0.4)}
                temp_name1 iy
                temp_expr1 {floor(y+A.g*parent.lwReach*0.4)}
                temp_name2 fx
                temp_expr2 {x+A.r*parent.lwReach*0.4-ix}
                temp_name3 fy
                temp_expr3 {y+A.g*parent.lwReach*0.4-iy}
                channel0 red
                expr0 {lerp(lerp(B.r(ix,iy),B.r(ix+1,iy),fx),lerp(B.r(ix,iy+1),B.r(ix+1,iy+1),fx),fy)}
                channel1 green
                expr1 {lerp(lerp(B.g(ix,iy),B.g(ix+1,iy),fx),lerp(B.g(ix,iy+1),B.g(ix+1,iy+1),fx),fy)}
                channel2 blue
                expr2 {lerp(lerp(B.b(ix,iy),B.b(ix+1,iy),fx),lerp(B.b(ix,iy+1),B.b(ix+1,iy+1),fx),fy)}
                channel3 alpha
                expr3 {A.b}
                name wrapTap1
                xpos 0
                ypos 260
            }
            set tap1 [stack 0]
            push $info
            push $bg_blurred
            MergeExpression {
                inputs 2
                temp_name0 ix
                temp_expr0 {floor(x+A.r*parent.lwReach*0.7)}
                temp_name1 iy
                temp_expr1 {floor(y+A.g*parent.lwReach*0.7)}
                temp_name2 fx
                temp_expr2 {x+A.r*parent.lwReach*0.7-ix}
                temp_name3 fy
                temp_expr3 {y+A.g*parent.lwReach*0.7-iy}
                channel0 red
                expr0 {lerp(lerp(B.r(ix,iy),B.r(ix+1,iy),fx),lerp(B.r(ix,iy+1),B.r(ix+1,iy+1),fx),fy)}
                channel1 green
                expr1 {lerp(lerp(B.g(ix,iy),B.g(ix+1,iy),fx),lerp(B.g(ix,iy+1),B.g(ix+1,iy+1),fx),fy)}
                channel2 blue
                expr2 {lerp(lerp(B.b(ix,iy),B.b(ix+1,iy),fx),lerp(B.b(ix,iy+1),B.b(ix+1,iy+1),fx),fy)}
                channel3 alpha
                expr3 {A.b}
                name wrapTap2
                xpos 150
                ypos 260
            }
            set tap2 [stack 0]
            push $info
            push $bg_blurred
            MergeExpression {
                inputs 2
                temp_name0 ix
                temp_expr0 {floor(x+A.r*parent.lwReach*1.0)}
                temp_name1 iy
                temp_expr1 {floor(y+A.g*parent.lwReach*1.0)}
                temp_name2 fx
                temp_expr2 {x+A.r*parent.lwReach*1.0-ix}
                temp_name3 fy
                temp_expr3 {y+A.g*parent.lwReach*1.0-iy}
                channel0 red
                expr0 {lerp(lerp(B.r(ix,iy),B.r(ix+1,iy),fx),lerp(B.r(ix,iy+1),B.r(ix+1,iy+1),fx),fy)}
                channel1 green
                expr1 {lerp(lerp(B.g(ix,iy),B.g(ix+1,iy),fx),lerp(B.g(ix,iy+1),B.g(ix+1,iy+1),fx),fy)}
                channel2 blue
                expr2 {lerp(lerp(B.b(ix,iy),B.b(ix+1,iy),fx),lerp(B.b(ix,iy+1),B.b(ix+1,iy+1),fx),fy)}
                channel3 alpha
                expr3 {A.b}
                name wrapTap3
                xpos 300
                ypos 260
            }
            set tap3 [stack 0]
            push $tap1
            push $tap2
            MergeExpression {
                inputs 2
                channel0 red
                expr0 {(A.r+B.r)*0.5}
                channel1 green
                expr1 {(A.g+B.g)*0.5}
                channel2 blue
                expr2 {(A.b+B.b)*0.5}
                channel3 alpha
                expr3 {A.a}
                name wrapAvg12
                xpos 150
                ypos 300
            }
            push $tap3
            MergeExpression {
                inputs 2
                channel0 red
                expr0 {(2*A.r+B.r)/3}
                channel1 green
                expr1 {(2*A.g+B.g)/3}
                channel2 blue
                expr2 {(2*A.b+B.b)/3}
                channel3 alpha
                expr3 {A.a}
                name wrapColour
                xpos 150
                ypos 340
            }
            set wrap_col [stack 0]

            # 5b. Relight (optional, Relight checkbox): the normals light the FG. d = N . L (L from Light Direction /
            # Elevation), wrapped-Lambert lit term, ambient + lit x intensity x colour as a gain on the FG colour.
            # A gain works the same on premultiplied and straight colour, so Premult Input does not matter here.
            push $normals
            push $in_fg
            MergeExpression {
                inputs 2
                temp_name0 dd
                temp_expr0 {A.r*cos(radians(parent.lwLightElev))*cos(radians(parent.lwLightAz))+A.g*cos(radians(parent.lwLightElev))*sin(radians(parent.lwLightAz))+A.b*sin(radians(parent.lwLightElev))}
                temp_name1 lit
                temp_expr1 {clamp((dd+parent.lwLightWrap)/(1+parent.lwLightWrap),0,1)}
                channel0 red
                expr0 {parent.lwRelight ? B.r * lerp(1, parent.lwAmbient + lit * parent.lwLightIntensity * parent.lwLightColor.r, parent.lwRelightAmount) : B.r}
                channel1 green
                expr1 {parent.lwRelight ? B.g * lerp(1, parent.lwAmbient + lit * parent.lwLightIntensity * parent.lwLightColor.g, parent.lwRelightAmount) : B.g}
                channel2 blue
                expr2 {parent.lwRelight ? B.b * lerp(1, parent.lwAmbient + lit * parent.lwLightIntensity * parent.lwLightColor.b, parent.lwRelightAmount) : B.b}
                channel3 alpha
                expr3 {B.a}
                name relightFG
                xpos 0
                ypos 290
            }
            set fg_relit [stack 0]

            # 6. Combine with the (relit) FG (B = FG, A = wrap colour with the wrap amount in alpha)
            push $wrap_col
            push $fg_relit
            MergeExpression {
                inputs 2
                temp_name0 fgL
                temp_expr0 {parent.premultipliedInput ? (B.a > 0.0001 ? (0.2126*B.r+0.7152*B.g+0.0722*B.b)/B.a : 0) : (0.2126*B.r+0.7152*B.g+0.0722*B.b)}
                temp_name1 wL
                temp_expr1 {0.2126*A.r+0.7152*A.g+0.0722*A.b}
                temp_name2 wM
                temp_expr2 {parent.enableBGWrap ? A.a * B.a : 0}
                temp_name3 amt
                temp_expr3 {wM * parent.lwIntensity * clamp((wL - parent.lwThreshold) / max(0.01, 1.0 - parent.lwThreshold + 0.2), 0, 2)}
                channel0 red
                expr0 {@R@}
                channel1 green
                expr1 {@G@}
                channel2 blue
                expr2 {@B@}
                channel3 alpha
                expr3 {parent.bgOutputMode == 2 ? clamp(amt + clamp(wM * parent.bgEdgeMix, 0, 1), 0, 1) : B.a}
                name lightWrapCombine
                xpos 0
                ypos 320
            }
            set wrapped_stream [stack 0]

            # 7. FG over BG: the FG must be premultiplied for the Over (FG = A / front, BG = B / back)
            push $wrapped_stream
            Premult {
                disable {{parent.premultipliedOutput}}
                name compPremult
                xpos 150
                ypos 380
            }
            push $in_bg
            Merge2 {
                inputs 2
                operation over
                name compOver
                xpos 150
                ypos 420
            }
            set comp_stream [stack 0]

            # 8. Output mode: FG Only / FG Over BG / Solo on black (solo is handled in the combine expression)
            push $comp_stream
            push $wrapped_stream
            Switch {
                inputs 2
                which {{parent.bgOutputMode==1}}
                name modeSwitch
                xpos 0
                ypos 460
            }
            set mode_out [stack 0]

            # 9. Mask & Mix
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
                ypos 520
            }
            set final_out [stack 0]

            # 10. View Normals (checkbox): the normals as colour (0.5 + 0.5 n). Output Mode "Normals (raw)" gives the
            # unit normals as float RGB (-1..1) with the FG alpha, ready for a relight.
            push $normals
            Expression {
                channel0 red
                expr0 {0.5+0.5*r}
                channel1 green
                expr1 {0.5+0.5*g}
                channel2 blue
                expr2 {0.5+0.5*b}
                channel3 alpha
                expr3 {1}
                name normalsViz
                xpos 300
                ypos 520
            }
            set viz [stack 0]
            push $normals
            push $in_fg
            MergeExpression {
                inputs 2
                channel0 red
                expr0 {A.r}
                channel1 green
                expr1 {A.g}
                channel2 blue
                expr2 {A.b}
                channel3 alpha
                expr3 {B.a}
                name normalsRaw
                xpos 450
                ypos 520
            }
            push $viz
            push $final_out
            Switch {
                inputs 3
                which {{parent.lwViewNormals?1:(parent.bgOutputMode==3?2:0)}}
                name viewSwitch
                xpos 0
                ypos 560
            }

            Output {
                name Output1
                xpos 0
                ypos 620
            }
"""


def make_light_wrap():
    group, selected = _create_sid_group("LightWrap")
    tcl = _TCL.replace("@R@", _channel_expr("r")).replace("@G@", _channel_expr("g")).replace("@B@", _channel_expr("b"))
    with group:
        nuke.tcl(tcl)

        en_wrap_k = _checked_knob("enableBGWrap", "Enable Light Wrap")
        mode_k = nuke.Enumeration_Knob(
            "bgOutputMode",
            "Output Mode",
            [
                "FG Only",
                "FG Over BG (Composite)",
                "LightWrap Only (Solo on Black)",
                "Normals (raw, for relighting)",
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

        pre_in_k = nuke.Boolean_Knob("premultipliedInput", "Premult Input")
        pre_in_k.setFlag(nuke.STARTLINE)
        pre_out_k = nuke.Boolean_Knob("premultipliedOutput", "Premult Output")
        pre_out_k.clearFlag(nuke.STARTLINE)

        int_k = nuke.Double_Knob("lwIntensity", "Intensity")
        int_k.setRange(0.0, 5.0)
        int_k.setValue(1.0)
        int_k.setTooltip("Controls the overall brightness/strength of the wrapped light.")

        width_k = nuke.Double_Knob("lwWidth", "Wrap Depth")
        width_k.setRange(1.0, 60.0)
        width_k.setValue(15.0)
        width_k.setTooltip("How far inward (in pixels) the wrap reaches for Coverage = Grow Inwards.")

        cov_k = nuke.Enumeration_Knob(
            "lwCoverage",
            "Coverage",
            [
                "Edge Only",
                "Grow Inwards (Wrap Depth)",
                "Whole Object",
            ],
        )
        cov_k.setValue(1)
        cov_k.setTooltip("Where the wrap is applied. The normals themselves always cover the whole FG. Edge Only = "
                         "a thin band (Edge Width), Grow Inwards = as deep as Wrap Depth, Whole Object = everywhere.")

        edge_w_k = nuke.Double_Knob("lwEdgeWidth", "Edge Width")
        edge_w_k.setRange(1.0, 60.0)
        edge_w_k.setValue(4.0)
        edge_w_k.setTooltip("Width of the band for Coverage = Edge Only (pixels).")

        height_k = nuke.Double_Knob("lwNormalHeight", "Normal Height")
        height_k.setRange(0.1, 20.0)
        height_k.setValue(3.0)
        height_k.setTooltip("How steeply the normals tilt. Higher = the surface turns away from the camera sooner "
                            "(rounder, more of the object is tilted); lower = a flatter face with the tilt only at "
                            "the rim. Check it with View Normals.")

        soft_k = nuke.Double_Knob("lwWrapSoft", "Wrap Softness")
        soft_k.setRange(0.0, 80.0)
        soft_k.setValue(0.0)
        soft_k.setTooltip("Extra smoothing of the wrap amount (pixels). Use it to soften any visible line where the "
                          "wrap ends.")

        reach_k = nuke.Double_Knob("lwReach", "BG Reach")
        reach_k.setRange(1.0, 120.0)
        reach_k.setValue(20.0)
        reach_k.setTooltip("How far out along the edge normal the background light is picked up from (pixels).")

        nstr_k = nuke.Double_Knob("lwNormalStrength", "Normal Strength")
        nstr_k.setRange(0.0, 3.0)
        nstr_k.setValue(1.0)
        nstr_k.setTooltip("How strongly the edge normals steer where the wrap colour is picked up. 0 = no normals "
                          "(the BG straight behind the pixel), 1 = along the normal, above 1 exaggerates it "
                          "(reaches further along the normal).")

        norm_k = nuke.Double_Knob("lwNormalBlur", "Normal Blur")
        norm_k.setRange(0.5, 60.0)
        norm_k.setValue(6.0)
        norm_k.setTooltip("How much the alpha is smoothed before the normals are taken (pixels). LOW = the normals "
                          "follow the contour and small details of the edge; HIGH = they follow only the overall "
                          "silhouette. Turn on View Normals to see the effect.")

        nsm_k = nuke.Double_Knob("lwNormalSmooth", "Normal Smooth")
        nsm_k.setRange(0.0, 30.0)
        nsm_k.setValue(3.0)
        nsm_k.setTooltip("Smooths the normal directions themselves (not the alpha). Removes jitter and flipped "
                         "normals in hair and noisy edges while keeping the contour.")

        nsrc_k = nuke.Enumeration_Knob(
            "lwNormalSource",
            "Normal Source",
            [
                "Alpha Dome (silhouette only)",
                "Image Detail + Dome",
                "Image Detail Only",
            ],
        )
        nsrc_k.setValue(1)
        nsrc_k.setTooltip("Where the normals come from. The alpha dome only knows the silhouette. Image Detail "
                          "also reads the FG's own luminance (bright = raised), so the normals follow the surface "
                          "detail across the whole object.")

        dstr_k = nuke.Double_Knob("lwDetailStrength", "Detail Strength")
        dstr_k.setRange(0.0, 10.0)
        dstr_k.setValue(3.0)
        dstr_k.setTooltip("How strongly the image detail tilts the normals.")

        dblur_k = nuke.Double_Knob("lwDetailBlur", "Detail Smoothing")
        dblur_k.setRange(0.5, 30.0)
        dblur_k.setValue(3.0)
        dblur_k.setTooltip("Smoothing (pixels) of the luminance before the detail normals are taken. Low = fine "
                           "texture and grain, high = broad forms only.")

        usen_k = nuke.Boolean_Knob("lwUseNormalsInput", "Use Normals Input")
        usen_k.setFlag(nuke.STARTLINE)
        usen_k.setTooltip("Use the map connected to the Normals input instead of the computed normals.")

        encn_k = _checked_knob("lwNormalsEncoded", "Normals Input is Encoded (0..1)")
        encn_k.clearFlag(nuke.STARTLINE)
        encn_k.setTooltip("On = the input holds n * 0.5 + 0.5 (a normal map image). Off = raw -1..1 vectors. "
                          "Green = up.")

        flip_k = nuke.Boolean_Knob("lwFlipNormals", "Flip Normals")
        flip_k.setFlag(nuke.STARTLINE)
        flip_k.setTooltip("Reverses the normal direction (the wrap is then picked up from the opposite side).")

        view_k = nuke.Boolean_Knob("lwViewNormals", "View Normals")
        view_k.clearFlag(nuke.STARTLINE)
        view_k.setTooltip("Shows the normals as colour: red = points right, green = points up, 0.5 grey = no "
                          "direction. Flip is included.")

        relight_k = nuke.Boolean_Knob("lwRelight", "Relight")
        relight_k.setFlag(nuke.STARTLINE)
        relight_k.setTooltip("Lights the FG with the normals: light direction, colour, intensity and ambient. "
                             "The wrap is applied on top of the relit FG.")

        az_k = nuke.Double_Knob("lwLightAz", "Light Direction")
        az_k.setRange(-180.0, 180.0)
        az_k.setValue(45.0)
        az_k.setTooltip("Where the light comes from, in degrees on screen. 0 = from the right, 90 = from above, "
                        "180 = from the left, -90 = from below.")

        elev_k = nuke.Double_Knob("lwLightElev", "Light Elevation")
        elev_k.setRange(0.0, 90.0)
        elev_k.setValue(30.0)
        elev_k.setTooltip("0 = the light grazes the surface from the side, 90 = the light comes straight from the "
                          "camera.")

        lcol_k = nuke.Color_Knob("lwLightColor", "Light Colour")
        lcol_k.setValue([1.0, 1.0, 1.0])

        lint_k = nuke.Double_Knob("lwLightIntensity", "Light Intensity")
        lint_k.setRange(0.0, 5.0)
        lint_k.setValue(1.3)

        lwrap_k = nuke.Double_Knob("lwLightWrap", "Light Softness")
        lwrap_k.setRange(0.0, 1.0)
        lwrap_k.setValue(0.15)
        lwrap_k.setTooltip("Wraps the light past the terminator (wrapped Lambert). 0 = hard N.L, 1 = very soft.")

        amb_k = nuke.Double_Knob("lwAmbient", "Ambient")
        amb_k.setRange(0.0, 2.0)
        amb_k.setValue(0.35)
        amb_k.setTooltip("Brightness of the unlit side (1 = unchanged colour).")

        ramt_k = nuke.Double_Knob("lwRelightAmount", "Relight Amount")
        ramt_k.setRange(0.0, 1.0)
        ramt_k.setValue(1.0)

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

        inv_mask_k = nuke.Boolean_Knob("invertMask", "Invert Mask")
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
            cov_k,
            width_k,
            edge_w_k,
            soft_k,
            reach_k,
            height_k,
            nstr_k,
            norm_k,
            nsm_k,
            nsrc_k,
            dstr_k,
            dblur_k,
            usen_k,
            encn_k,
            flip_k,
            view_k,
            diff_k,
            fall_k,
            thr_k,
            sat_k,
            _divider("divRelight"),
            _section_heading("hdrRelight", "Relight (uses the normals)"),
            relight_k,
            az_k,
            elev_k,
            lcol_k,
            lint_k,
            lwrap_k,
            amb_k,
            ramt_k,
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
            "import sid_light_wrap as _lw\n"
            "k = nuke.thisKnob()\n"
            "if k is not None and k.name() in ('lwCoverage', 'lwNormalSource', 'lwRelight', 'lwUseNormalsInput'):\n"
            "    _lw._update_light_wrap_ui(nuke.thisNode())\n"
        )
        _update_light_wrap_ui(group)

    group["label"].setValue("[value bgOutputMode]\n[value lwMode]")
    _connect_sid_group(group, selected)
    return group


def install_menu():
    m = nuke.menu("Nodes").addMenu("Sid", icon=None)
    m.addCommand("Light Wrap", make_light_wrap)
    nuke.addOnCreate(_on_group_create, nodeClass="Group")

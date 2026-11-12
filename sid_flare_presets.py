# Sid Lens Flare -- Look presets.
#
# A preset is a set of knob values of the Lens Flare node. Four built-ins live in code (BUILTINS); your own are JSON
# files in ~/.nuke/sid_flare_presets/<name>.json holding every look knob of the node: lens, elements, colours, dirt,
# master. Not stored: the composite knobs (Output, Invert Mask, Mix), the Optical Centre (it belongs to the shot, not
# the look), the hidden solve knobs and the status lines. Built-ins set the knobs they list and leave the rest.
#
# Apply sets the knobs with the node's own knobChanged callbacks muted (so e.g. the Squeeze default for the Streak
# cannot overwrite a stored tint), then re-solves the lens, redraws the Offset handles and recreates the optional
# input pipes once. Python only touches the Group's own knobs.
#
# Strict ASCII.

import json
import os
import re

import nuke

import sid_flare_elements as el
import sid_lens_optics as optics

PRESET_DIR = os.path.join(os.path.expanduser("~"), ".nuke", "sid_flare_presets")
KNOB_LIST = "presetKnobs"                  # hidden knob: the names a preset stores, recorded when the node is made
MENU = "lookPreset"
PRESET_CLASSES = ("Double_Knob", "Int_Knob", "Boolean_Knob", "Enumeration_Knob", "Color_Knob", "XY_Knob",
                  "String_Knob", "Multiline_Eval_String_Knob")
EXCLUDED = ("outputMode", "invertMask", "mix", "opticalCenter", MENU, "status", "inputsNote", KNOB_LIST, "effFstop")
HIDDEN_SOLVE = re.compile(r"^g\d+(sR|sG|sB|rad|eR|eG|eB)$")
VERSION = 1
_muted = [False]


def muted():
    """True while a preset is being applied: knobChanged callbacks should do nothing."""
    return _muted[0]


# -- which knobs a preset stores --------------------------------------------------------------------

def eligible(name, klass):
    return klass in PRESET_CLASSES and name not in EXCLUDED and not HIDDEN_SOLVE.match(name)


def record_knobs(group, before):
    """Remember the look knobs of a node just built: every Lens Flare knob added since `before` (a set of the
    group's knob names) of a storable class, minus the excluded ones. Stored in a hidden knob so a node loaded
    from a script knows its own list."""
    names = sorted(n for n in set(group.knobs()) - set(before) if eligible(n, group[n].Class()))
    k = nuke.String_Knob(KNOB_LIST, KNOB_LIST)
    k.setValue(",".join(names))
    k.setFlag(nuke.INVISIBLE)
    group.addKnob(k)
    return names


def look_knobs(group):
    return [n for n in group[KNOB_LIST].value().split(",") if n and n in group.knobs()]


def _plain(v):
    if isinstance(v, (list, tuple)):
        return [float(x) for x in v]
    if isinstance(v, bool) or isinstance(v, str):
        return v
    if isinstance(v, int):
        return int(v)
    return float(v)


def snapshot(group):
    """{knob: value} of the look knobs (enums as their text, colours and XY as lists)."""
    return dict((n, _plain(group[n].value())) for n in look_knobs(group))


def apply_values(group, values):
    """Set the stored knobs that exist on the node, callbacks muted. Returns the names that could not be set."""
    skipped = []
    _muted[0] = True
    try:
        for name in sorted(values):
            if name not in group.knobs() or name in EXCLUDED:
                skipped.append(name)
                continue
            try:
                group[name].setValue(values[name])
            except Exception:
                skipped.append(name)
    finally:
        _muted[0] = False
    return skipped


# -- built-in looks -----------------------------------------------------------------------------------

ELEMENT_IDS = [e[0] for e in el.ELEMENTS]


def _elements_only(*on):
    out = dict((eid + "On", False) for eid in ELEMENT_IDS)
    out.update(dict((eid + "On", True) for eid in on))
    return out


def _clean_prime():
    v = _elements_only("bloom")
    v.update({"lensPreset": optics.PRESET_NAMES[0], "fstop": 4.0, "coatings": True, "blades": 9, "apRoundness": 0.7,
              "apRotation": 0.0, "squeeze": "1x", "apShape": "Procedural", "ghostsOn": True, "ghostCount": 5,
              "ghostIntensity": 0.7, "dispersion": 0.6, "starOn": True, "starIntensity": 0.012, "starLength": 45.0,
              "starChroma": 0.5, "glareOn": True, "glareIntensity": 0.00001, "bloomIntensity": 0.0015,
              "masterIntensity": 1.0, "masterSaturation": 0.9, "masterTint": [1.0, 1.0, 1.0], "dirtOn": False})
    return v


def _vintage_uncoated():
    v = _elements_only("bloom", "wash", "caustic", "multiIris", "orbs")
    v.update({"lensPreset": optics.PRESET_NAMES[min(2, len(optics.PRESET_NAMES) - 1)],
              "fstop": 2.0, "coatings": False, "blades": 6, "apRoundness": 0.15, "squeeze": "1x", "apShape": "Procedural",
              "ghostsOn": True, "ghostCount": 12, "ghostIntensity": 2.0, "dispersion": 1.6, "starOn": True,
              "starIntensity": 0.02, "starLength": 90.0, "starChroma": 1.6, "starIrregularity": 0.4, "glareOn": True,
              "glareIntensity": 0.00003, "glareSize": 350.0, "washIntensity": 0.08, "bloomIntensity": 0.003,
              "multiIrisCount": 6, "masterSaturation": 1.1, "masterTint": [1.0, 0.93, 0.8],
              "dirtOn": True, "dirtSpeckOn": True, "dirtSmudgeOn": True, "dirtFibreOn": True, "dirtIntensity": 0.08})
    return v


def _anamorphic_sci_fi():
    v = _elements_only("glint", "bloom")
    v.update({"lensPreset": optics.PRESET_NAMES[1] if len(optics.PRESET_NAMES) > 1 else optics.PRESET_NAMES[0],
              "fstop": 2.8, "coatings": True, "blades": 6, "apRoundness": 0.3, "squeeze": "2x", "apShape": "Procedural",
              "ghostsOn": True, "ghostCount": 4, "ghostIntensity": 0.8, "starOn": False, "glareOn": True,
              "glareIntensity": 0.00002, "streakOn": True, "streakCount": 1, "streak0Angle": 0.0, "streak0Length": 900.0,
              "streak0Thickness": 2.5, "streak0Tint": list(el.SQUEEZE_STREAK_TINT), "streak0Intensity": 0.004,
              "bloomTint": [0.6, 0.8, 1.0], "bloomIntensity": 0.003, "glintIntensity": 0.0008,
              "masterTint": [0.85, 0.92, 1.0], "masterSaturation": 1.1, "dirtOn": False})
    return v


def _sun_flare():
    v = _elements_only("bloom", "ringHalo", "streak", "wash")
    v.update({"lensPreset": optics.PRESET_NAMES[1] if len(optics.PRESET_NAMES) > 1 else optics.PRESET_NAMES[0],
              "fstop": 8.0, "coatings": True, "blades": 7, "apRoundness": 0.0, "squeeze": "1x", "apShape": "Procedural",
              "ghostsOn": True, "ghostCount": 8, "ghostIntensity": 1.0, "dispersion": 1.0, "starOn": True,
              "starIntensity": 0.03, "starLength": 200.0, "starChroma": 1.2, "glareOn": True, "glareIntensity": 0.00004,
              "glareSize": 400.0, "bloomIntensity": 0.004, "ringHaloCentre": 0, "ringHaloColorMode": 1,
              "ringHaloIntensity": 0.006, "washIntensity": 0.05, "streakCount": 1, "streak0Angle": 0.0,
              "streak0Tint": [1.0, 1.0, 1.0], "masterTint": [1.0, 0.92, 0.78], "masterSaturation": 1.0, "dirtOn": False})
    return v


BUILTINS = (("Clean Prime", _clean_prime), ("Vintage Uncoated", _vintage_uncoated),
            ("Anamorphic Sci-Fi", _anamorphic_sci_fi), ("Sun Flare", _sun_flare))
BUILTIN_NAMES = [n for n, _f in BUILTINS]


def builtin(name):
    for n, f in BUILTINS:
        if n == name:
            return f()
    return None


# -- files ------------------------------------------------------------------------------------------------

def safe_name(name):
    """A preset name usable as a file name: letters, digits, space, - and _ ."""
    name = re.sub(r"[^A-Za-z0-9 _-]", "", (name or "")).strip()
    return name


def _path(name):
    return os.path.join(PRESET_DIR, name + ".json")


def user_names():
    try:
        return sorted(f[:-5] for f in os.listdir(PRESET_DIR) if f.lower().endswith(".json"))
    except OSError:                                    # no folder yet, or it cannot be read
        return []


def names():
    return BUILTIN_NAMES + [n for n in user_names() if n not in BUILTIN_NAMES]


def load(name):
    """Stored values of a built-in or saved preset, or None."""
    b = builtin(name)
    if b is not None:
        return b
    try:
        with open(_path(name)) as fh:
            data = json.load(fh)
    except (IOError, OSError, ValueError):
        return None
    return data.get("knobs") if isinstance(data, dict) else None


def save(group, name):
    """Write the node's look to <name>.json. Returns (ok, message)."""
    clean = safe_name(name)
    if not clean:
        return False, "Enter a name (letters, digits, spaces, - and _)."
    if clean in BUILTIN_NAMES:
        return False, "'%s' is a built-in look: pick another name." % clean
    try:
        if not os.path.isdir(PRESET_DIR):
            os.makedirs(PRESET_DIR)
        with open(_path(clean), "w") as fh:
            json.dump({"version": VERSION, "name": clean, "knobs": snapshot(group)}, fh, indent=1, sort_keys=True)
    except (IOError, OSError) as err:
        return False, "The look could not be saved in %s: %s" % (PRESET_DIR, err)
    return True, clean


def delete(name):
    """Remove a saved preset. Built-ins cannot be deleted. Returns (ok, message)."""
    if name in BUILTIN_NAMES:
        return False, "'%s' is a built-in look and cannot be deleted." % name
    try:
        os.remove(_path(name))
    except OSError:
        return False, "'%s' could not be deleted." % name
    return True, name


# -- the node's Preset row ---------------------------------------------------------------------------------

def refresh_menu(group, select=None):
    """List the built-in and saved presets in the Preset menu, keeping (or setting) the selection."""
    if MENU not in group.knobs():
        return
    keep = select or group[MENU].value()
    all_names = names()
    group[MENU].setValues(all_names)
    group[MENU].setValue(keep if keep in all_names else all_names[0])


def apply_selected(group):
    """Apply button: the looks in the menu to the node. Returns the names that could not be set."""
    values = load(group[MENU].value())
    if values is None:
        return None
    skipped = apply_values(group, values)
    import sid_lens_flare
    sid_lens_flare.finish_preset(group)
    return skipped


def save_dialog(group):
    """Save Preset... button."""
    name = nuke.getInput("Save the current look as", group[MENU].value() if group[MENU].value() not in BUILTIN_NAMES else "My Look")
    if name is None:
        return
    ok, msg = save(group, name)
    if ok:
        refresh_menu(group, msg)
    else:
        nuke.message(msg)


def delete_selected(group):
    """Delete button: remove the saved preset in the menu (after asking)."""
    name = group[MENU].value()
    if name in BUILTIN_NAMES:
        nuke.message("'%s' is a built-in look and cannot be deleted." % name)
        return
    if not nuke.ask("Delete the saved look '%s'?" % name):
        return
    ok, msg = delete(name)
    if ok:
        refresh_menu(group)
    else:
        nuke.message(msg)


def row_knobs(nk):
    """The Preset menu and its three buttons, one row at the top of the Lens tab (`nk` is the nuke module)."""
    menu = nk.Enumeration_Knob(MENU, "Look Preset", BUILTIN_NAMES)
    menu.setTooltip("Built-in looks and your saved ones. Choose one, then press Apply.")
    out = [menu]
    for name, label, call, tip in (
            ("lookApply", "Apply", "apply_selected", "Set the node's knobs to the chosen look (built-ins set the knobs they list; "
             "your saved looks set every look knob)."),
            ("lookSave", "Save Preset...", "save_dialog", "Save the node's current look under a name, in ~/.nuke/sid_flare_presets."),
            ("lookDelete", "Delete", "delete_selected", "Delete the chosen saved look (built-ins cannot be deleted).")):
        b = nk.PyScript_Knob(name, label, "import sid_flare_presets\nsid_flare_presets.%s(nuke.thisNode())\n" % call)
        b.setTooltip(tip)
        b.clearFlag(nk.STARTLINE)
        out.append(b)
    return out

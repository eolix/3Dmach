# 0005: How the Max-Style keymap is built, registered and activated

- Status: Proposed
- Date: 2026-10-16

## Context

ROADMAP Phase 1a asks for a full Max-style keymap in the `mx_keymap` add-on that:

1. works as a standalone add-on on stock Blender 5.2, and later is the default in the fork;
2. is selectable in Preferences > Keymap like Blender's own presets, and can be activated from the add-on
   preferences with one click;
3. applies Max-like navigation preferences when it is activated, but changes nothing when the add-on is merely
   enabled.

How Blender 5.2 handles key configurations (`scripts/modules/bpy/utils/__init__.py`,
`source/blender/windowmanager/intern/wm.cc`, `wm_init_exit.cc`):

- The Preferences > Keymap preset menu lists the `.py` files in `bpy.utils.preset_paths("keyconfig")`: the
  `presets/keyconfig` directories of the system, user and script paths, plus directories registered with
  `bpy.utils.register_preset_path()`. Picking one runs it (`bpy.utils.keyconfig_set`), which must create a key
  configuration named after the file, and makes it active.
- The preferences only store the *name* of the active key configuration. At startup `bpy.utils.keyconfig_init()`
  loads `Blender.py`, then looks for a preset file with the stored name and runs it. **This happens before add-ons
  are registered.** If the file isn't found, the active key configuration silently falls back to Blender's (and the
  stored name is lost the next time preferences are saved).
- A key-map item that refers to an operator that isn't registered yet can't get its properties set
  (`keyconfig_init_from_data` prints warnings and drops them).

So a key configuration built only by the add-on (`wm.keyconfigs.new` + `keyconfig_init_from_data` in `register()`)
is not listed in the preset menu and is not restored at startup. A preset file registered by the add-on with
`register_preset_path()` is listed, but is not found at startup either, because the add-on registers its path after
`keyconfig_init()` ran.

## Decision

**One small preset file, the key-map built by the add-on.**

- `Max-Style.py` is an ordinary key configuration preset with identical contents in two places:
  `scripts/addons_core/mx_keymap/presets/keyconfig/` (for stock Blender) and `scripts/presets/keyconfig/`
  (for the fork, where it is found like `Blender.py`). A test checks the two copies are identical.
- The preset holds no key-map data. It checks that the add-on is enabled (otherwise it raises, so Blender keeps
  its own keymap and says why in the console), creates the "Max-Style" key configuration and asks the add-on to
  fill it. At startup the add-on isn't registered yet, so the preset leaves the key configuration empty but active
  and the add-on fills it from `register()`.
- The data comes from `mx_keymap/keymap_data.py`, which does not import `bpy`: it takes Blender's own default
  key-map data (`keymap_data/blender_default.py`, left-click select, the fallback select tool on) and overrides the
  3D viewport bindings. It is based on Blender's default rather than on "Industry Compatible", because the default
  covers every editor and is the most tested; Industry Compatible changes far more keys we would have to change
  back (F1-F4 views, Tab search, Alt+LMB orbit) and only defines a subset of key-maps itself.
- Overrides are applied by putting the Max item first in its key-map and removing every item that can be
  triggered by the same input from the key-maps that would shadow it: the object/edit-mode key-maps, "Object
  Non-modal", "Frames", "3D View Generic" and "3D View". Paint, sculpt, text and Grease Pencil modes keep their keys.
  Tool key-maps (the Move/Rotate/Scale tools, the select tools and their "(fallback)" variants) are rewritten
  explicitly. Everything else in Blender's key-map is kept, so Blender changes come for free when the fork rebases.
- **Stock Blender:** while the add-on is enabled and no installed copy of the preset exists, it registers its own
  `presets` directory, so "Max-Style" is listed in Preferences > Keymap. Activating it (from that menu or the
  add-on's "Activate Max-Style Keymap" button) copies the preset to the user's `scripts/presets/keyconfig/`, exactly
  what Blender's own "Import Key Configuration" does, and stops registering the add-on directory so the menu doesn't
  show it twice. From then on Blender finds the preset at startup.
- **Fork:** the preset is in `scripts/presets/keyconfig/`. Making it the default needs the add-on enabled by default
  and `active_keyconfig = "Max-Style"` in the default preferences (part of ROADMAP §11 task 5); nothing in the add-on
  changes.
- **Navigation preferences** (orbit around selection, zoom to mouse position, auto-perspective off so orthographic
  views stay orthographic when orbiting, turntable orbit) are applied when the keymap is *activated*, if the add-on
  preference "Max-Like Navigation" is on (the default). The values from before the first activation are kept in the
  add-on preferences and a button restores them. Enabling the add-on changes neither the active keymap nor any
  preference.
- Blender also runs the active preset from `keyconfig_init()` when it reloads key-maps (at startup, after a script
  reload, when "Emulate 3 Button Mouse" changes). That is not an activation, so the preferences must not be
  re-applied. The add-on tells the two apart by looking for `bpy.utils.keyconfig_init` on the call stack. This is
  a small hack against a stable, internal call path; if it ever stops matching, the only effect is that the
  navigation preferences are re-applied on reload.
- **Disabling the add-on** empties the key configuration (its items refer to the add-on's operators) but keeps it
  active, so a script reload, which unregisters and registers add-ons, keeps the keymap. A timer checks right after
  `unregister()`: if the add-on is really disabled, it removes the key configuration and Blender's becomes active
  again.

## Consequences

- One code path for stock Blender and the fork; the fork only adds the preset file and default preferences.
- The keymap's own data is plain Python and can be diffed against Blender's default (useful when rebasing).
- On stock Blender the user preset copy stays behind if the add-on is uninstalled. Blender then reports at startup
  that the add-on is missing and uses its own keymap. Deleting `scripts/presets/keyconfig/Max-Style.py` from the
  user configuration directory removes it.
- The preset name is the file name. Renaming the keymap means renaming both copies of the file.
- Key-map items of the add-on refer to `mx_keymap.*` operators: renaming the module prefix (ROADMAP §4.2) also
  changes operator ids users may have customised.

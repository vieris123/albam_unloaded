# Albam tests

End-to-end checks for the DMC4 fork, kept from the work sessions that built each feature. They drive the add-on the
way a user does (import, edit, export) in headless Blender, or run the pure-Python format code over the game's files.
Nothing here starts the game: they prove that Albam agrees with itself and with the files (byte-identical round
trips, edits landing in the right bytes), not that the game shows the result as expected. That's checked by hand;
see ROADMAP.md "Check in the game".

## Running

```
python tests/run_tests.py              # everything, 4 at a time
python tests/run_tests.py keys wait    # tests whose file name contains one of these words
python tests/run_tests.py -j 2 --blender "C:/Program Files/Blender Foundation/Blender 4.2/blender.exe"
python tests/run_tests.py --timeout 600 actions   # a test still running after that many seconds is killed and fails (default 1800)
```

A test passes when it prints `FAILURES: []`, no line starting with `FAIL `, and exits with 0; one that lacks an
optional data file prints `SKIPPED:` and counts as passed. Logs (one per test) go to `<temp>/albam_tests/logs`.
A single Blender test can also be run directly:

```
"C:/Program Files/Blender Foundation/Blender 4.2/blender.exe" -b --factory-startup --python tests/blender/test_keys.py
```

## Data

The tests only read game files, never write them.

| Variable | Default | What |
|---|---|---|
| `ALBAM_DMC4_DATA` | `E:\DMC mod stuffs` | the folder holding `arctool` (extracted DX9 arcs; Nero is `arctool\uPlayerNero-vanilla`) |
| `ALBAM_DMC4_MODS` | `D:\DMC4 mods` | mod packs; DanteJDC's `ec002_00v0` is used by `test_missing` and `test_billboard_modes` |
| `ALBAM_TEST_OUT` | `<temp>/albam_tests` | where tests write (exports, Save to Game Folder output, logs) |
| `ALBAM_BLENDER` | Blender 4.2's default path | the Blender the runner starts (`--blender` too; the suite also runs on 5.4 alpha) |

`tests/common.py` holds these paths; tests use `common.DATA`, `common.NERO`, `common.out_dir(name)` and
`common.skip_unless(path)`.

## What's here

`blender/` (headless Blender, effects unless noted):

| Test | Covers |
|---|---|
| `test_all_play`, `test_all_play_arm` | every Nero effect imports and plays (without / with the character's armature) |
| `test_keys`, `test_wait` | keyframes as F-curves: tracks, random parts, loop, interpolation, markers, WaitFrame offsets |
| `test_kf_tab` | the Keys tab and keyframe export |
| `test_bulk_edit` | editing several selected records, the records list's Outliner-like clicks (plain / Shift / Ctrl) and All / None / Same Type, selection across rebuilds, Copy one field / one track / Draw Common / Generator Common / Life / section / tab to Selected |
| `test_live`, `test_apply_blend` | live preview, Blender's own tools on records (Shift+D, X), blending edits |
| `test_sections`, `test_flag_ui`, `test_flags`, `test_relation`, `test_options`, `test_filter` | Effect Editor sections, flag checkboxes, RelationType 2, import options, spawn filter |
| `test_retype_blender` | Change Type in Blender |
| `test_line_type` | editing LineType / ClothType / a FIX line's LineOfsNum rebuilds the block for its layout |
| `test_linked`, `test_linked_export`, `test_new_files` | linked `.efs` / `.ean`: rebuilds, own Export rows, New Strip / New Flipbook |
| `test_efs_ean`, `test_efs_curve`, `test_efs_join` | strips: round trip, edits, a strip converted to a curve, a mesh joined into a strip |
| `test_ean_uv`, `test_ean_mesh`, `test_ean_hidden` | flipbooks: UV editing, joining meshes / frames from a mesh, hidden state over rebuilds |
| `test_game_folder` | Save to Game Folder |
| `test_actions` | (not effects) actions on this Blender's API, 4.2 or 5: LMT import plays and re-exports, the foot IK ghost plays the same action, an SDL round-trips and follows a key edit |
| `test_frame_cache` | the per-frame playback cache: replays, scrubbing and fresh computation draw the same; camera moves redraw |
| `test_ribbon_nodes` | line ribbons built by the Ribbons node group match the points' camera-facing strips, UVs, colours and material |
| `test_missing` | missing textures |
| `test_culling`, `test_orient`, `test_billboard_face`, `test_billboard_modes`, `test_polygon_align`, `test_light`, `test_light_group` | preview rules: culling fade, particle orientation, camera facing, lights, light groups |

`corpus/` (plain Python over every unique DX9 `.efl`):

| Test | Covers |
|---|---|
| `efl_roundtrip` | `engines/mtfw/scripts/efl_check.py`: every file writes back byte-identical, no check issues |
| `sim_all` | the particle simulation runs on every record |
| `retype_all` | Change Type on 60 sampled files to every type and variant |

## Adding a test

Copy the top of an existing one: put `tests/` on `sys.path`, `import common`, `common.register()` (Blender) or
`common.plain()` (plain Python), collect failures with `check(cond, msg)` and end with `print("FAILURES:", failures)`.
Take paths from `common`, never write under the data folders, and name new Blender tests `test_<what>.py`.

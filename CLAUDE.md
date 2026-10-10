# CLAUDE.md

Albam Unloaded: a fork of [Brachi's Albam](https://github.com/Brachi/albam) Blender addon for MT Framework games.

**This fork is focused solely on Devil May Cry 4 (`app_id="dmc4"`).**
- Code for the other games (re0, re1, re5, re6, rev1, rev2, dd, and RE Engine) is inherited from upstream and is not maintained or tested here.
- Design and test every change for DMC4 first.
- DMC4-only shortcuts are acceptable. Hardcoding `'dmc4'` is already common.
- Code paths shared with other games (e.g. `Mod156`/`Mod21`, `tex_157`, `Sbc21`) don't need to keep working for those games, but avoid breaking them without a reason.
- When the re5 and dmc4 code paths overlap (`mod_156_mesh`, `tex_112`, `lmt_49`, `Sbc156`), DMC4 behaviour wins.

The addon imports and exports models (.mod), textures (.tex/.rtex), collision (.sbc) and animations (.lmt). Version `0.4.0.dev11` (`__version__.py`); `bl_info` must be kept in sync by hand.

- Runtime: Blender 4.x (the pycache is cpython-311). The addon is imported as the `albam` package from `E:\DMC mod stuffs\blender_addon\addons\`.
- There is no test suite, no build script and no linter config. Verify changes in Blender. Blender 4.2 is installed, so many changes can be tested headless:
  `"C:\Program Files\Blender Foundation\Blender 4.2\blender.exe" -b --factory-startup --python test.py`
  The script should put `E:\DMC mod stuffs\blender_addon\addons` on `sys.path`, `import albam`, call `albam.register()`, then drive `bpy.context.scene.albam.*` and the operators. Panels can't be drawn headless; call `UIList.filter_items` with a stub `self` instead.
- Test data (read-only, never write to it):
  - `E:\DMC mod stuffs\Dante Cyber porting\m20_100s` holds extracted **DX9 (mod v153)** files. Example: `model\demo\pl000\pl000.mod` imports with 37 textures.
  - `E:\DMC mod stuffs\arc files\em*` holds **Special Edition** files (mod v210 + .mrl). They are not the target format, and importing them fails in `material.py` (`KeyError: 'features'`) on the original code too.
- Debugging: `.vscode/launch.json` attaches debugpy on `localhost:7120`. The sibling addon `blender-debugger-for-vscode-master` provides the server, and its port must be set to 7120 (its default is 5678).
- Branches: `master` and `event-test` (LMT event and animation export work).

Open work is tracked in `ROADMAP.md` (repo root): keep it up to date when an item is done or a new gap is found.

## Layout

| Path | Purpose |
|---|---|
| `__init__.py` | `register()`: puts `albam_vendor/` on `sys.path`, imports engine modules so their decorators fill the registry, then registers classes and builds the custom-property factories. **Import order matters**: the factories snapshot the registry. |
| `registry.py` | The `blender_registry` singleton. Everything is wired through its decorators (see below). |
| `apps.py` | The `APPS` enum (re0, re1, re5, re6, rev1, rev2, dd, dmc4). RE Engine apps are added only when `ALBAM_ENABLE_REEN` is set. |
| `vfs.py` | Virtual file system stored in scene `CollectionProperty`s (`scene.albam.vfs`, `scene.albam.exported`). File bytes live in `BYTE_STRING` props. |
| `rfs.py` | Fork addition, and the **main DMC4 file browser** ("Game Files" panel): `scene.albam.rfs` lists folders of extracted game files. See [Game Files (RFS)](#game-files-rfs). |
| `blender_ui/` | Panels and operators. `import_panel.py` / `export_panel.py` are in the 3D View sidebar tab "Albam [Beta]". `tools.py` has the UV seam split, normal transfer, bone rename, VG merge and collision face editor. `anim_tools.py` is the Dope Sheet LMT section (LMT → Animations → Events). `custom_properties.py` is the per-app property factory. `error_handling.py` is the error popup. |
| `engines/mtfw/` | MT Framework: `mesh.py` (.mod), `material.py` (materials/MRL), `texture.py` (tex↔DDS), `animation.py` (.lmt), `collision.py` (.sbc import/export, Blender side), `sbc_bvh.py` (DMC4 SBC1 reader/writer, pure Python), `placement.py` (.pla) and `scheduler.py` (.sdl) Blender import/export over the vendored `dmc4xml`, `xml_edit.py` (Edit as XML / Apply XML for them), `cns_chain.py` (.phs model chains), `col_shapes.py` (.col collision shapes) and `cns_chain_preview.py` (chain motion preview, the import wiring between them), `archive.py` (.arc + dmc4 loose files), `__init__.py` (bone anim mapping enums, file-id↔extension hash tables). |
| `engines/mtfw/structs/` | Kaitai Struct `.ksy` sources and the **generated** read-write `.py` parsers. |
| `engines/mtfw/efl/` | Fork addition: DMC4 DX9 `.efl` (effects) parser/writer; `edit.py` maps block fields, keyframes and sub-structs to and from custom properties and restructures records. **Pure Python, not Kaitai, relative imports only**, so it runs without Blender. `schema.py` is the single layout table, with an evidence tier per field. `model.py` holds blocks as raw bytes with typed views (exact round-trip). `check.py` has the invariants and corpus coverage, `export_json.py` the JSON dump, `primmodel.py` the PrimModel mesh builders, `ean.py` the `.ean` flipbook tables, `keyframe.py` keyframe curves, `efs.py` `.efs` path curves, `sim.py` the particle simulation, `field_help.py` the plain-language help for every field, `retype.py` block type changes. The Blender import is `engines/mtfw/effect.py`; animated playback is `engines/mtfw/effect_sim.py`; export is `engines/mtfw/effect_export.py`; the editor panel is `engines/mtfw/effect_editor.py`; the spawn filter is `engines/mtfw/effect_filter.py`; Change Type is `engines/mtfw/effect_retype.py`; `.efs` / `.ean` import / export is `engines/mtfw/effect_efs.py` / `effect_ean.py`. See [EFL](#efl-effects). |
| `engines/mtfw/defines/shader-objects.json` | Shader-object hashes, regenerated by `scripts/dump_mfx.py` from `.mfx` files. It has no re5 or dmc4 entries; it is used only by the MRL (v21) path. |
| `engines/reng/` | Experimental RE Engine support (pak/mesh/mdf/tex), gated by `ALBAM_ENABLE_REEN`. |
| `lib/` | Helpers: `blender.py` (mesh/material utilities), `bvh_construction.py` + `primitive_geometry.py` + `pymorton.py` + `rays.py` (BVH for the SBC21 export of other games; DMC4 uses `engines/mtfw/sbc_bvh.py`), `bone_names.py` (bone rename presets), `common_op.py`, `dds.py`, `vec_op.py` (**`vec_mult` actually divides**). |
| `albam_vendor/` | Vendored `kaitaistruct` (the read-write runtime), `pymmh3` and `dmc4xml` (the `.sdl` / `.pla` codecs, a **third-party copy** of the package in the user's [dmc4_xml](https://github.com/vieris123/dmc4_xml) repo: never edit it here, change it upstream and run `scripts/sync_dmc4xml.py <dmc4_xml checkout>`, which records the commit in `albam_vendor/dmc4xml/UPSTREAM.txt`). They can only be imported after `register()` has put this folder on `sys.path`. |
| `scripts/sync_dmc4xml.py` | Re-syncs `albam_vendor/dmc4xml` from a dmc4_xml checkout (default: `E:\DMC mod stuffs\dmc4_xml`). |

## DMC4 reverse-engineering notes

`E:\DMC mod stuffs\Vibed\RE` holds the reverse-engineering notes for the DMC4 **DX9** executable (`DevilMayCry4_DX9.exe`), made in IDA and cross-checked against the Special Edition PDB.
- **Check them before guessing at a format field.** They are derived from the binary and often correct the community `.ksy` labels.
- Offsets differ between DX9 and SE; the notes say which build each one applies to.

The notes most relevant to the addon:

| File | Covers |
|---|---|
| `vertex_format.md` | How mod v153 vertex-element codes (`pvdecl`/`pvdeclbase`) become D3D9 vertex declarations. |
| `cMaterialStandard.md`, `texture_binding.md`, `rTexture.md` | Material record layout, texture slots → samplers, and the `.tex` resource. |
| `uDevil4Model_skinmesh.md` | Skin-mesh pipeline. `SkinRemap` is shader constant handles, not a bone remap. |
| `sShader_name_hash.md`, `sShader_hash_ids.json` | Technique/parameter name hash (not CRC32) and 487 verified IDs. These are relevant to `htechnique`. |
| `motion_runtime_findings.md`, `ik_constraint_findings.md` | LMT evaluation at runtime, and leg IK. |
| `sbc_moving_parts.md` | Moving collision: part matrices per group_id, uStageSetMoveFloor, riding (surface 0x40), the authoring recipe, 20 proposed IDB renames. |
| `chain_cnschain.md` | Model chains (`.phs` = rCnsChain): file layout, the per-frame solver step by step, `.col` collision, where Nero's coat hangs (body joint 2). |
| `sdl_scheduler_runtime.md` | How `.sdl` schedulers load and evaluate: header fields, track binding, key modes (step / one-shot / linear / Catmull-Rom / counter), refs, events, the DTI hash; `.pla` `mRotY` / `mAngle` units. |
| `sbc_dx9_format.md` | **The DX9 `.sbc` (SBC1 v18) format**: loader, node / group / triangle layout, traversal, what each triangle field does. Read this before touching collision. |
| `collision_findings.md`, `collision_lineCast.md`, `sCollision_LineSeg_findings.md` | SBC/BVH collision runtime and line casts. |
| `efl.bt`, `efl_generator_struct.md`, `efl_import_plan.md`, `particle_*.md` | The `.efl` effect format and a not-yet-implemented import plan. |

The rest of the folder (player/enemy classes, input, multiplayer, `scripts/` IDAPython) is gameplay research rather than file formats.

## Registry pattern

Engines register by decorator. Nothing is hand-wired in the UI:

```python
@blender_registry.register_import_function(app_id="dmc4", extension="mod", file_category="MESH")
@blender_registry.register_export_function(app_id="dmc4", extension="mod")
@blender_registry.register_archive_loader / register_archive_accessor(app_id, extension)
@blender_registry.register_blender_type          # panels and operators
@blender_registry.register_blender_prop_albam("name")   # -> scene.albam.<name>
@blender_registry.register_custom_properties_{material,mesh,image,action}(name, app_ids, is_secondary=False)
@blender_registry.register_import_options_custom_draw_func / _poll_func(extension)
```

Custom properties end up at `<Material|Mesh|Image|Action>.albam_custom_properties`, with attributes named `{app_id}__{name}`. Use `get_custom_properties_for_appid(app_id)` to read them. `get_parent_albam_asset` resolves only Mesh and Material, so the animation code hardcodes `'dmc4'`.

When you add a new engine module, import it in `__init__.register()` **before** the factories are created.

## Workflows

**DMC4 does not expand `.arc` files in the addon.** Its loader and accessor are registered with `extension=None` (`archive.py`), so the VFS "Archives" panel is hidden when dmc4 is selected. The intended flow is:

1. Extract arcs with an external tool.
2. In "Game Files", click Add Folder and pick the extracted arc folder (the one containing `model\`, etc.).
3. Select a file and click Import (`albam.import_real`).
4. Edit the result in Blender.
5. Select it under Export and click Export. Files appear in the "exported" VFS.
6. Use Save, or Patch (`albam.patch` → `archive.update_arc`) to rewrite an arc in place.
   - Entries are matched by (path without extension, file type), and the type comes from the extension through
     `file_type_for_extension` (`engines/mtfw/__init__.py`), which knows every DMC4 resource class
     (`DMC4_RESOURCE_CLASSES`, from `Note\DMC4Extensions.txt`; arc type = `~crc32(class) & 0x7FFFFFFF`) under all the
     names extraction tools give it: the class name or the DTI hash in hex (old arctool: `pl023.rCollisionIdxData`,
     `pl000.0CA6AED4` = rMotionSe), the native extension (new arctool with `-allowDuplicateExt`,
     `arctool\pc-dmc4-full-ext.bat`: `.idx`, `.sif`), and the tool's own names (`DMC4_TOOL_EXTENSIONS`: `.phs`,
     `.sreq`, `.spac` = rSoundBank 0x15D782FB, `.dnrs`). `.bin` (rCharTbl and rPlParamTbl) takes the type of the
     existing entry at its path; a new `.bin` or an unknown extension is refused (`AlbamCheckFailure`). Checked on
     uPlayerNero.arc: every spelling replaces its entry, a new `.rCollisionIdxData` is added with its type.

Texture and MRL lookup during import goes through `scene.albam.rfs.get_vfile(app_id, game_path)` (the VFS path is commented out). **The added root folder must be the arc root**, so that paths relative to it equal the in-game paths stored in the .mod.

### Game Files (RFS)

- `rfs.py` walks the folder with `os.scandir` (folders first, then sorted by name) into `rfs.file_list`.
  - Item `name` is `app_id::part::part` relative to the root folder. `get_vfile` relies on this format.
  - If several roots contain the same path, the first one wins.
  - Each root gets a unique id (`dmc4::name (2)`); children point to it via `tree_node.root_id`. Depth is `tree_node.depth` (root = 0).
- File bytes are **read from disk on demand** (`RealFile.get_bytes`). Nothing is stored in the .blend. Old .blend files that still carry stored bytes shrink after a Refresh.
- `RealFile` reuses `VirtualFile`'s path helpers (`extension`, `relative_path_windows_no_ext`, …), so import functions accept either.
- Visibility is the pure function `compute_visible_items`, which handles search, "importable only" and collapsed folders. `ALBAM_UL_RealFileSystemUI.filter_items` caches its result keyed on `rfs.revision`. **Bump `rfs.revision` whenever you change the list or `is_expanded`.**
- Operators: `albam.add_real_root_folder`, `albam.remove_imported_real` (removes the root of the selected item), `albam.refresh_real_folders`, `albam.collapse_real_folders`, `albam.real_file_item_collapse_toggle`, `albam.import_real`.
- Panel layout:
  - Import → Game Files (`ALBAM_PT_RealFileSystem`)
    - Per-extension import options (`ALBAM_PT_ImportOptionsCustom`, e.g. the LMT armature picker)
    - Import button (`ALBAM_PT_RealFileSystemImport`)
  - Import → Archives (`ALBAM_PT_VirtualFileSystem`), shown for non-dmc4 apps only.
- Performance: a 37k-file folder adds in under 1 s, and the uncached filter takes about 40 ms.

### LMT section (Dope Sheet → Action Editor sidebar → "Albam [Beta]")

LMT work happens outside the 3D View export flow. `albam.export_anim` writes an LMT (an `AlbamActionGroup` in `scene.albam.lmt_groups`) straight to a `.lmt` file. It remembers the path in `export_path`, which import fills with the source file.

- **Data model** (`animation.py`):
  - `lmt_groups.anim_group[active_group_id]` is the LMT file. It holds `actions` (`Lmt49Action` rows that point to an Action), `num_slots` and `armature`.
  - Per-animation data is **only** on the action: `get_lmt_props(action)` returns the `dmc4__lmt_49` custom props (`lmt_id` = slot, `num_frames`, `loop_frames` (-1 = no loop), `end_pos/quat`, `events_params_01/02`, `event_markers`).
- **Helpers:** use `get_active_lmt/anim/event(context)`, `find_event_marker` and `link_legacy_events` instead of indexing collections directly. They return None instead of raising.
- **`anim_tools.py` must not import `animation.py` at module level.** `animation.py` needs `kaitaistruct`, which can only be imported after `register()` puts `albam_vendor` on `sys.path`. Go through `_animation()` and the thin wrappers at the top of `anim_tools.py`.
- **Events:**
  - Each `DMC4EventGroup` is linked to its pose marker by `marker_name`, so markers can be moved freely in the timeline.
  - Events from .blend files saved before `marker_name` existed are paired by position until `link_legacy_events` runs. It runs when an animation is selected, from the event operators, and on export.
  - `encode()` / `setup()` convert to and from the 32-bit value: slots in bits 0-7, the named flags from `GroupHash`/`GroupBitNum`, and the remaining bits in `extra_bits`.
  - In the game, the two event tables are (value, duration) runs that always start at frame 0 and add up to `num_frames`. All 256 DX9 blocks on disk follow this.
  - Export fills a gap before the first event, or an empty table, with zero-value events.
- **Slots:**
  - Add Animation picks the first free slot.
  - Selecting an animation in the list assigns it to the armature (the `active_id` update callback).
  - `_check_lmt_group` raises `AlbamCheckFailure` for slot clashes, slots ≥ `num_slots`, events with missing markers or outside the animation, and two events of one type on the same frame.

### Foot IK preview (`blender_ui/foot_ik.py`, LMT panel → Foot IK Preview)

This reproduces the game's player foot planting (`cLegIkCtrl` + `cCnsIK`, see `Vibed/RE/ik_constraint_findings.md`) on the LMT's armature. It's **for previewing only**: nothing is keyed or exported, and LMT export output is byte-identical with the rig present.

- **Enable flags.** In the game, foot IK is turned on per leg by the `right_foot_ik` (bit 24) and `left_foot_ik` (bit 25) flags of **first-table** events.
  - Across the DX9 files, those bits appear in the first table in 1,222 blocks, mostly `pl*` files. The second table uses them in only 95 blocks, mostly enemies.
  - That these flags are the enable read by `getNumberFromMotSeq` is an inference: the RE notes don't name the bits.
- **Game behaviour:**
  - A ray goes from 30 above to 14 below the animated ankle.
  - On a hit, the ankle target becomes hit + 12. On a miss, the target is the animated ankle.
  - A 2-bone IK (thigh, shin, ankle as effector) solves to the target, keeping the animated foot rotation.
  - The IK fades in and out by `blend_speed` per frame (0.1).
  - The same distances in Blender units are 0.30 / 0.14 / 0.12.
- **Rig structure:**
  - A hidden **FK ghost** object shares the armature data and plays the same action. It supplies the IK-free ankle, knee and foot rotation without dependency cycles.
  - The ghost copies the armature's own pose constraints (e.g. the hips following `root_motion`, added by LMT import). Rebuild after changing those.
  - The ground window is two Shrinkwrap PROJECT constraints on a probe bone 12 below the ankle: +Z with limit 0.42 and −Z with limit 0.02.
- **Blender IK can't solve the game's leg bones directly.** They are 5 cm stubs, unconnected, pointing +Z.
  - The solver models a chain from head-to-tail lengths and puts the effector at a bone tail, so on these bones it folds the leg toward the hip.
  - So it solves a helper hip → knee → ankle chain instead (`IKP_ik_thigh/shin`, knee pre-bent 1 cm, because a straight chain won't bend).
  - Follow bones are children of that chain with the real bones' rest frames. The real thigh and shin Copy Transforms from them with the fade weight.
  - Don't change the real bones' tails: LMT export depends on `matrix_local`.
- **Pole angle** is calibrated numerically at build time: bend the ghost's knee, then search for the angle where the IK knee matches. Accuracy: the ankle is exact, the knee within about 1 cm.
- **Fading:** a `frame_change_pre` handler (`register_handlers()` in `albam.register()`) syncs the ghost's action and sets the fade per leg.
- **Naming:** helper bones are prefixed `IKP_` and constraints `ALBAM_IKP_`. Remove deletes all of them and the ghost.
- **Not modelled:** the game's rule of keeping the original height when the ground is within 1 cm, and the knee-plane joints `mDir`/`mUp` (the RE note hasn't pinned them down yet).

## Format and version branching

- **.mod** import picks the parser from the version byte (`mod_bytes[4]`): 153→`Mod153`, 156→`Mod156`, 210/211/212→`Mod21`. Export picks it by app_id: dmc4→Mod153, re5→Mod156, everything else→Mod21.
  - 153/156 store materials inside the .mod. 21x uses an external `.mrl`.
  - 153 has no RCN header (`size_top_level_` = header + 72, versus +104 for 156).
  - The DMC4 vertex format is driven by the **material's** `vtype` / `func_skin` custom props.
  - Bone palettes hold at most 32 bones.
  - Mod export **copies bones from `original_bytes`**, so armature edits are not exported.
  - **Light group** (`engines/mtfw/model_settings.py`, Object Properties > Albam Asset > Model Settings): header 0x88
    `model_info.light_group` (`uModel::setModel` -> `uModel.mLightGroup`). Import fills `Object.albam_mod.light_group`
    (32 toggles) and sets `loaded`; export writes it when `loaded`, else the source file's value (older imports; the
    panel's Load from File reads it). The panel also works with a mesh of the model selected (`model_root`).
- **.tex**: re5 and dmc4 use `tex_112` / `rtex_112`; the others use `tex_157`.
- **.sbc**: the byte at offset 3 is 49 (`SBC1`, DMC4 DX9 v18; also re5) or 255 (`Sbc21`, the other games; SE DMC4 files
  are `SBCÿ` too). See [SBC (collision)](#sbc-collision).
- **.lmt**: v49 is written; 51 and 67 are parse-only. Import works for re5 and dmc4; export is dmc4 only.
  - Coordinates: positions are ÷100 on import and ×100 on export. Meshes are converted from Y-up cm to Z-up m: `(x*.01, -z*.01, y*.01)`. Quaternions are `(w,x,y,z)`.
  - Bones map through the bone property `bone['mtfw.anim_retarget']`. Index 255 is root motion and creates a `root_motion` bone; 254 is skipped.
  - **Key timing** (see [LMT key timing](#lmt-key-timing-confirmed-in-ida-fixed-2026-10-05)):
    - Stored keys start at frame 0.
    - A key's duration is the number of frames to the next key, and 0 marks the last key, which holds.
    - `ref_data` equals the first key, in the same (game) space.
  - Import puts keys on their game frames; durations become `None` padding frames. The framerate is forced to 60.
  - **Events** are pose markers named `ev{1|2}_{frame}_{group_id}` on import (ev1 = Hitbox, ev2 = Sound). See [LMT section](#lmt-section-dope-sheet--action-editor-sidebar--albam-beta). In the first table, slot bit k turns on `.col` group `events_params_01[k]` (see "Groups follow the LMT events" under Model chains). The second table is sound effects with the same slot scheme (slot bit k plays `events_params_02[k]`, per the user); sound isn't scoped in Albam yet.
  - **Track export** (`_serialize_tracks`):
    - Tracks are built per (bone, property) straight from `action.fcurves` (`_get_export_tracks`), so F-Curve grouping doesn't matter: FBX and Bake Action output works as-is. Order matches the game's files: root motion first, then armature bone order, then rotation > location > scale.
    - Properties other than location/rotation/scale (e.g. `bbone_*`) are skipped and reported.
    - **Timing (`ExportTiming`)** converts on the fly and never edits the action:
      - The action is shifted so its first key, or first event, lands on game frame 0.
      - It's scaled from the animation's **Frame Rate** (`source_fps`, per action: 60 for imported, the scene fps for Add Animation) to 60.
      - Curves are evaluated on whole game frames.
      - `Frames` and `Loop Start` are game frames; `game_length()` converts.
      - The export reports what it adjusted (`export_lmt(lmt, notes)`).
    - Each track is written on the **union of its channels' keyframes**, plus frame 0 for animated tracks, with every channel evaluated there (`_track_keys`).
      - Gaps over 255 frames are split, because the rotation key duration is 8 bits.
      - Durations come from `_key_durations`: the gap to the next key, 0 on the last.
    - Quaternion tracks are slerped between keys (`_quaternion_keys`), because Blender's per-component interpolation breaks across q/−q flips, which imported animations have.
    - Rotation:
      - Accepts quaternion, Euler (converted with the pose bone's rotation order) and axis-angle.
      - Keys are normalized to unit length with w ≥ 0 (`_normalized_rotation`), because the file stores only x/y/z.
      - Animated rotations are written as type 6, constant ones as type 4.
      - If a bone has curves in several rotation modes, its rotation mode picks which one is exported.
    - Root-motion bone (255): rotation is written as usage 3 (absolute), location as usage 4.
    - **New LMT** (`albam.new_lmt`) creates an empty LMT for an armature with game bones. Reorganize F-Curves was removed: grouping no longer matters.
    - External animations still have to be retargeted and baked onto the DMC4 armature first: tracks need bones with `mtfw.anim_retarget`.
  - **Buffer types seen in the DX9 files:**
    - Rotation: 6 (`FrameQuat4_14`, 8 bytes per key, an 8-bit duration) and 4 (quat x/y/z as floats, w implied).
    - Vectors: 9 (`fffI`, with a duration) and 2 (constant `fff`).
    - No Euler storage exists.

## SBC (collision)

DMC4 DX9 collision is `SBC1` version 18. The format and what the game does with every field are in
`Vibed/RE/sbc_dx9_format.md` (IDA, checked against all 74 DX9 files). Rewritten 2026-10-10; the old export (the
upstream `lib/bvh_construction.py` path) produced trees the game can't fully traverse (see the note's Albam section).

- **Layout:** header 0x30, nodes (80 B), groups (96 B), triangles (28 B), vertices (16 B), packed, no offsets. The
  loader checks only the magic and version 18.
  - `boxes[0:ntop]` is a BVH over the groups (`ntop` = groups - 1, or 1 for one group: child 0 empty, child 1 leaf
    group 0, flags 0x80). Each group then has its own BVH of `max(1, triangles - 1)` nodes at `start_boxes`, preorder.
  - Node flags 0x40 / 0x80 = child 0 / 1 is a leaf (one triangle / one group). Inner child indices are relative to the
    tree's base, and **index 0 means "no child"**. Bits 0-5 (child 0 min < child 1 min, max > max per axis) aren't
    read but are written as the files have them.
  - **The shipped traversal (`enumSomeContacts`) reads top node k's child boxes from group record k** (`vmin/vmax`),
    so the group record must repeat top node k; the last group's copy is its own box twice.
  - Triangle vertex indices and leaf indices are relative to the group (`start_vertices` / `start_tris`, u16, so 65,536
    vertices and triangles per group at most). Groups must be in ascending, contiguous order.
  - `num_groups_nodes` and the two nest counts aren't read by the game; they're written as the files have them.
- **Triangle fields:**
  - `type` = **ground material ID** (footstep / effect material through `cUtil::getEfctMtrlFlg`; 0 = none). The face
    layer is still called `group` (old name), shown as "Material" in the face editor.
  - `special_attr` = channels the face lets through (bits 8-14 floor, 16-22 wall); 0x10000000 / 0x20000000 replace
    the channels.
  - `surface_attr` = 0x20 force floor, 0x10 force wall, 0x1000 sheltered from rain.
  - `runtime_attr` is rebuilt at load for stages and gimmicks; always write 0x3FFFFF00 (matches every query).
  - `unk_00` / `unk_01` have no reader; kept as face layers `sbc_unk_00` / `sbc_unk_01`. `unk_02` and vertex w are 0.
- **One-sided.** The game computes the normal as (v1-v0)x(v2-v0); line casts only hit the side it points to, and
  floor vs wall comes from its y (> sin 40 deg = floor). Albam's axis conversion is a rotation, so Blender normals
  must point out of the walkable side. Export flips the winding back for objects with a mirroring transform.
- **Import** (`collision.load_sbc156`, via `sbc_bvh.read_sbc1_groups`): one mesh per group, `<file>_<index>`, with
  `ob["sbc_group"]` (group order) and `ob["sbc_group_id"]` (the part ID scripts switch with `Sbc::activateParts`, -1 =
  none, stored signed) and face int layers `sbc.FACE_LAYERS`.
- **Export** (`export_sbc156` -> `sbc156_groups` -> `sbc_bvh.build_sbc1`):
  - Meshes under the root in `sbc_group` order, then by name (new meshes go last). Modifiers and transforms
    applied, n-gons triangulated, zero-area triangles skipped, meshes over 65,536 vertices split along their longest
    axis into several groups with the same ID. Missing face layers are written as 0 (the "Auto" preset). Each of
    these is reported in the console and in `root["sbc_export_notes"]`.
  - Collision imported before 2026-10-10 has no `sbc_group_id`: the IDs come from the source file by mesh order
    when the mesh count still matches.
  - The BVHs are built from scratch (median split on the longest centroid axis, exact child boxes; shallower than
    the game's own trees). Triangles are reordered into leaf order, as in the game files.
- **Moving collision ("dynamic SBC", `Vibed/RE/sbc_moving_parts.md`):** any registered `.sbc` can move. The game sets
  the matrix of **every group whose `group_id` equals the unit's part ID** (`sub_946E60`, mCoord / mCoordOld per part;
  reset = teleport). `uStageSetMoveFloor` (a scheduler / placement unit: `mpCollision` .sbc, `mpModel`, `mPartsId`,
  keyed `mPos` / `mAngle`, optional `mpParent`, `mDisp` on/off) registers its own copy of the .sbc, marks every
  triangle surface 0x40 (actors standing on it are carried by inverse(mCoordOld) * mCoord) and drives it from its
  world matrix each frame. Its geometry is in the unit's **local frame**. Groups with another ID stay inactive.
  - Albam: **collision exports relative to its root Empty** (stage roots sit at the origin, so nothing changes for
    them). **Object Properties > Collision Part** shows a mesh's part ID and **Set Part ID** (`albam.sbc_set_part_id`)
    sets it on the selected collision meshes (-1 = static, the default for new meshes; a moving piece needs its
    unit's mPartsId, usually 0). Scheduler units with mPos / mAngle move with their keys (drivers, see SDL / PLA), so
    parenting a collision root to such a unit previews the moving floor; export stays local.
  - New moving floor recipe: model + `.sbc` in local space (part ID = mPartsId), a uStageSetMoveFloor unit (in a
    `.sdl` with mPos / mAngle keys, or a `.pla`) that the room already loads (`scr\stXXX\etc\stXXX.pla`,
    `scr\stXXX\sdl\stXXX.sdl`, both loaded by `aRoom::setRoom` 0x40D4F0), mMode 0. Add the unit with **Edit as XML**
    (see SDL / PLA): copy an existing `classref_track` (e.g. st405 `blade01.sdl`'s), rename it, set its resources and
    keys, Apply XML.
- **Tests** (scratch scripts, not in the repo): all 67 unique DX9 files rebuild in plain Python and round-trip through
  Blender with every layout rule holding, identical triangles, attributes and group IDs, the same file size, and
  every triangle reachable by a point query that follows the game's traversal.

## SDL / PLA (scheduler, placement)

`.sdl` (`rScheduler`, keyed property tracks: fades, fog, lights, sounds, cutscene units) and `.pla` (`rPlacement`,
static placement trees: enemy sets, stage sets, wait / group data). The format code is **not Albam's**: it is the
`dmc4xml` package from the dmc4_xml repo, vendored in `albam_vendor/dmc4xml` (see Layout). Its corpus test is
`tests/test_sdl_pla.py` there: every DX9 file round-trips byte-identical (`st008a.sdl`, written by another tool, comes
back with the same content in the standard layout). SE `.sdl` files are version 22 and are refused.

- **Format facts** (corpus + IDA, `Vibed/RE/sdl_scheduler_runtime.md`; module docstrings in `dmc4xml/sdl.py` /
  `pla.py`):
  - SDL header: frames word = loop length (bits 0-23, 1 frame = 1/60 s) + flags (bit 24: floor the frame; 2 files);
    +0x0C = **index of the marker (cut) track** (its key frames are cuts; 0 = none), not a DTI table.
  - SDL tracks 0x18: u8 type, u8 MtPropertyType, u16 keys, u32 parent, u32 name, u32 dti, u32 timing, u32 data.
    Types 1 root, 2 unit (dti = class created with newInstance, **parent = sUnit move line**), 3 system (bound to a
    `sDevil4Main` singleton of that class: sCamera, sShader, sVibration), 4 ignored by the game, 5 object (a class
    member of track `parent`), 6 int (**every key a 4-byte slot**, U8 / U16 too), 7 vector (**16 bytes per key** for
    every property type), 8 float, 9 bool (1 byte), 10 ref (**a track index**: the unit / system bound by that
    track, 0 = null), 11 resource (offset of u32 dti + path; every resource is loaded with the .sdl), 12 string (not
    in the files), 13 event, 14 custom (64 bytes). Object and value tracks use `dti` as the array index. Timing word
    = frame (bits 0-23) + mode (24-31). A track may hold two keys on one frame and keys out of frame order.
  - **Key modes** (`rScheduler::keying` 0x90AF00): key i's mode governs i -> i+1. 0 step; 2 step written only on the
    tick that reaches the key (one-shot; every event key); 3 linear (no slerp for vectors); 5 uniform Catmull-Rom
    (tangent (v[i+1] - v[i-1]) / 2, ends clamped); 1 / 4 counter (value + elapsed frames, no end). Bools ignore it.
  - DTI hashes are `MtCRC::getCRC` (MT19937 per character pair), `dmc4xml.dti.dti_hash`, not CRC32: any class
    name can be typed in the XML.
  - PLA tracks 0x1C: u32 type, prop, parent, move line, name, dti, data. Types 1 root, 3 group, 4 unit, 5 object, 6
    bool, 7 int, 8 float, 9 vector, 10 ref (a track index), 11 resource. One value per track (4 bytes, 16 for
    vectors) at the next 16-byte boundary; value tracks with one name and dti 0, 1, 2 ... form an array.
  - Track order is always a preorder of the parent tree. The name area's string order isn't reconstructible, so
    the codecs keep each string's source offset as a hint (new strings are appended).
- **Blender** (`engines/mtfw/placement.py`, `scheduler.py`): the root Empty `PLA_<file>` / `SDL_<file>` and one Empty
  per container track (group, unit, object), all in the file's own collection (named like the root; the loaders are
  `build_pla_objects` / `build_sdl_objects`, which take the collection to rebuild into, and return None to the
  importer). Each keeps its track fields in `pla_track` / `sdl_track` and the order of
  its children (value entries and child containers, with their string offsets) in `pla_layout` / `sdl_layout`
  (JSON). Values are custom properties on their container (`name`, or `name[i]` for arrays).
  - **PLA:** an `mPos` vector moves its Empty (cm, Y up -> m, Z up), `mRotY` (degrees) turns it; a unit without its
    own position sits on its first positioned descendant (an enemy unit on its mEnemyCreateData). Moving / turning
    the Empty writes them back on export (`_sync_transform`, 0.01 cm / 1e-4 deg tolerance so untouched files stay
    identical). Ref values are object pointers (export turns them back into the target's new track index). Export
    runs `view_layer.update()` first: right after an import every matrix_world is still identity.
  - **PLA rotations:** `mRotY` is degrees about the game's up axis; `mAngle` (uStageSet*, `uCoord::setAngle`) is a
    radian Euler in game axes, Blender order ZXY (the default `uCoord::mOrder` 4), mapped through `GAME_AXES`.
  - **SDL:** numeric tracks (int, float, bool, vector) are custom properties keyed with F-curves, one keyframe per
    key on the key's frame (scene frame = scheduler frame); a vector is a 4-float property with 4 curves. Modes map
    to interpolation (0 / 2 CONSTANT, 3 LINEAR, 5 BEZIER with the exact Catmull-Rom handles, 1 / 4 LINEAR as an
    approximation); the preview matches the game's evaluation to 6e-5 on every 0 / 3 / 5 track of st502_smdl00. Key
    modes are kept per frame (`modes`); new keys take `KEY_MODES[interpolation]` (CONSTANT 0, LINEAR 3, BEZIER 5).
    Unchanged curves give the source keys back exactly (two keys on one frame, source order). A track without
    F-curves exports one key at frame 0 with the property's value. Resource / string / ref / event / custom keys
    live in the layout entry; a single-key resource is also a string property (its path). Ref values and the
    marker track are renumbered on export (`track` = source index in each entry); a ref to a deleted track is an
    error, a deleted marker track a note.
  - **SDL unit transforms:** a unit with `mPos` / `mAngle` properties gets drivers on its Empty (location = (x, -z,
    y) / 100, rotation_mode 'YXZ' = (ax, -az, ay): the game's Euler ZXY in Blender axes, exact), and `mpParent`
    becomes a Child Of constraint `ALBAM_SDL_Parent` (identity inverse). They only show the keys; export reads the
    properties. Checked on st405 `blade01.sdl`: the blade's yaw matches the game's evaluation to 1e-7 rad.
  - **Editing:** values in Object Properties > Custom Properties, keys in the Dope Sheet / Graph Editor, positions in
    the viewport. Duplicating a container (with its children) adds its tracks right after the original
    (`placement.ordered_children`); deleting one drops them.
  - **Edit as XML** (`xml_edit.py`; Object Properties > Scheduler / Placement XML, and the Text Editor's Albam tab)
    for what the objects can't do (new units, new property tracks, another class): `albam.xml_edit` exports the file
    as it is now (edits included) through `dmc4xml.xmlconv` into a Text block `<root>.xml`; `albam.xml_apply` turns
    the text back into bytes (read back to check), refuses track tags the format doesn't have (xmlconv would skip
    them silently) and rebuilds the Empties in place (`xml_edit.rebuild`: same collection, name, transform, parent;
    objects parented to an Empty from outside and constraints targeting one are re-attached by the Empty's path from
    the root). The rebuilt file is the new source; Undo reverts. Checked: every DX9 `.pla` (105) and `.sdl` (338 of
    339; st008a.sdl normalises as above) is byte-identical through the indented XML; blade01 / emset105 rebuild
    byte-identical with a parented collision root and a constraint kept; a copied `uStageSetMoveFloor` unit exports.
  - Import functions are registered for `dmc4` / `pla` (category PLACEMENT) and `sdl` (SCHEDULE); `rPlacement`'s file
    id `0x42EA212F` is in `FILE_ID_TO_EXTENSION` so Patch can add `.pla` entries. The one double-extension file
    (`emset001.pla.pla`, an extraction quirk) is listed with extension `pla.pla` and isn't importable.

## EFL (effects)

Work in progress. The plan and all layout evidence are in `Vibed/RE/efl_import_plan.md`. The parser (M1a), the
Blender import (`engines/mtfw/effect.py`) and its particle preview (`effect_sim.py`) are done; export of edits is in
`engines/mtfw/effect_export.py`.

- **Export** (`effect_export.py`, registered as the dmc4 `efl` export function):
  - **Transform conventions** (verified 2026-10-09, `uEffectVFR::setQuatParentOfs` 0x9687B0): Quat (x, y, z, w) builds
    the same rotation as Blender's `Quaternion((w, x, y, z))` (MT row-vector layout = Blender's matrix transposed),
    Scale scales before the rotation, Pos is the translation; with a joint parent the matrix is (S R) . J, i.e. Pos /
    Quat in the joint frame, as import and export assume.
  - **RelationType 2** (generator AxisFlags bits 8-11 -> Generator+0x110): position from the joint, rotation = own Quat
    in **world** axes (2,609 generators, 1,059 on joints; `ec002_00v0` uses it almost everywhere). A bone-attached
    type 2 generator gets a companion Empty `<record>_rot` under the effect root (`effect_export.attach_rotation_handle`,
    keys `efl_rot_handle` / `efl_rot_handle_of`): the generator keeps its bone parent (Pos turned by the joint), a Copy
    Rotation constraint `ALBAM_EFL_WorldRotation` takes the companion's world rotation, the companion sits at the joint
    (Copy Location on the bone; following the generator would be a dependency cycle). Export reads Quat from the
    companion in the root's frame; generator rotation keys go on the companion; Duplicate / Copy to make a new one,
    Remove deletes it, rebuilds recreate it. RelationType 3 (ignore the parent) isn't in the files. Root-attached type 2
    generators differ only by the armature object's own rotation and aren't special-cased.
  - Import stores the source bytes in `root.albam_asset.original_bytes` and adds the root Empty `EFL_<file>` to the
    Export list. Record Empties point back at it with `ob['efl_root']` and carry `efl_record` (the source record
    index; -1 = a new record built from its `efl_raw` blocks), `efl_gen/ptcl/life/move` (fields, `efl/edit.py`
    `block_props`), `efl_kf` ({slot: {offset field: keyframe}}) and `efl_sub` ({slot: {offset field: collision /
    culling fields}}). Offset fields (`sub=`) aren't stored: they're layout, rewritten by the keyframe write-back. The
    root stores `efl_stem` and `efl_options` (import options) for rebuilding.
  - `build_efl_bytes(root)` parses the source again and: keeps source records that still have an object (in
    order), appends new records, writes back the props that differ from the file, then the generator Empty's
    transform (Pos / Quat / Scale base from the parent bone's head frame or the root, i.e. what the viewport
    shows; channels with F-curves are skipped) and re-parenting (`ParentNo` = the bone's `mtfw.anim_retarget`,
    -1 when detached). Bad values raise `AlbamCheckFailure` listing every problem.
  - Keyframes: same size or smaller = rewritten in place; larger or new = appended at the block end and the offset
    repointed (no other data moves, so offsets the schema doesn't know stay valid); no keys = offset 0.
    Offsets into blocks, block types and untyped keyframes are read-only. The unit generator isn't editable.
  - Untouched effects export byte-identical (all 110 Nero effects; the pure prop round-trip on 1,079 files).
  - `apply_to_scene`: **Apply** (the only button; Rebuild was folded into it 2026-10-10) replays the simulation from
    the rebuilt bytes (`root['efl_data']`) when only per-frame simulation inputs changed. It rebuilds
    (`effect.rebuild_effect` re-imports the effect from the edited bytes: same armature, start frame, options; images
    tagged `efl_texture` are reused) when records were added/removed or retyped, a linked file changed
    (`structure_changed`), an edit touches what the import bakes into the objects (`built_changed`: any particle
    block byte (material, blending, texture, shape, flipbook, orient / culling settings), generator keyframes /
    RangeStripPath / ParticleScale / AxisFlags / Pos / Quat / Scale / ParentNo, a path move's strip, collision on or
    off), a missing texture is now under the Game Files roots (`found_missing_textures`), or with the operator's
    **Rebuild Everything** option (redo panel). After a rebuild the edited bytes are the new source, so Revert goes
    back to them, not to the game file. Add new build-time inputs to `built_changed`.
- **Effect Editor** (`effect_editor.py`, sidebar panel "Effect Editor", and the same panel in Object Properties:
  `_EflEditorDraw` mixin, `ALBAM_PT_EflEditor` / `ALBAM_PT_EflEditorObject`): the active record (msgbus on the active
  object, or Edit Record) is loaded into `scene.albam.efl_editor.fields`, one item per schema field / bit-field
  with a widget for its type (floats, ints, hex u32 words, text paths, BGRA colour pickers, enums for blend /
  shapes / axes / orders / types). Each edit writes the record's custom props right away; words and their
  bit-fields stay in step; gen `Scale` also sets the Empty's scale; `Pos` / `Quat` / `ParentNo` are read-only (move
  or parent the Empty). Tabs: Generator / Particle / Life / Move / Keys (one keyframe at a time: interpolation,
  timer, loop, init-only, key list with add / remove / sort) / More (collision, culling). Records box: a scrollable
  list (`ALBAM_UL_EflRecords` over `efl_editor.records`, kept in step by `sync_records`) to select, then Duplicate, Copy to (another imported effect; attaches to the same joint if its armature has it), Remove.
  Unverified fields (tiers other than dx9 / se) are hidden unless toggled. The panel can't be drawn headless;
  tests call `ALBAM_PT_EflEditor.draw` with a stub layout.
  - **Live preview** (`efl_editor.live`, default on; 2026-10-10): every editor edit (`_on_item_edit`,
    `write_keyframe`) calls `schedule_live_apply(root)`, and a `bpy.app.timers` timer (`_live_apply`, 0.2 s
    debounce) runs `apply_to_scene` (replay, or rebuild when `built_changed`); errors land in `efl_editor.live_error`
    (shown in the panel) instead of a popup. Operators use `live_apply_now`. Apply stays for Live off and for
    transform / pose changes (nothing watches those). Headless tests call `_live_apply()` directly (timers don't
    run in `-b`).
  - **Blender's own tools on effect objects** (`_on_depsgraph`, a `depsgraph_update_post` handler that is read-only
    and queues work for the same timer, `_queue` / `_run_job`): a record Empty copied with Shift+D or Ctrl+C / V is
    found by `session_uid` (`_scan_objects`, run when `len(bpy.data.objects)` changes or after `forget_objects()`)
    and `effect_export.adopt_duplicate` makes it a new record of its effect (or of the effect root it was parented
    to: Copy to), with its own serial, `efl_raw` and rotation companion (`_make_new_record`, shared with the
    Duplicate / Copy to operators); copies of linked `.efs` / `.ean` objects and of rotation companions are cut loose
    (`efl_linked` / `efl_root` removed). A deletion (X) queues a `structure_changed` check, so the rebuild drops the
    record. A game texture (image tagged `efl_texture`) swapped in an effect material's Image Texture node writes its
    path into the records drawn with it (`_material_image_changed`, matching `material["efl_base_map"]`). A linked
    strip / flipbook whose geometry updated (after Edit Mode) is applied. Tests drive the handler with a stub
    depsgraph (`SimpleNamespace(updates=[...])`).
  - **Path pickers**: path fields in `PATH_EXTENSIONS` (textures, ModelPath, AnimPath, strips) get a search button
    (`albam.efl_pick_path`: the Game Files entries with that extension as game paths, plus the effect's linked
    `.efs` / `.ean` objects) and texture fields an image dropdown (`AlbamEflFieldItem.image`, loaded `efl_texture`
    images only; picking sets the path, typing a path selects the image).
  - **Flag fields** (`_FLAG_LABELS`, kind `flags`): TransMode, ColorFlag, AnimFlag, ModelAnimFlag, ParticleOptionFlag,
    LightAttribute and the particle CullingFlag are one checkbox per named bit; bits without a name keep their value and are shown as
    "other bits ... kept". Only bits with a DX9 reader get a checkbox.
  - **Particle tab sections** (`PTCL_SECTIONS`, `ptcl_section`, `item.section`): the Particle tab's fields are grouped
    into collapsible boxes (Drawing & Blending, Texture & Flipbook, Colour, Size & Shape, Rotation, Model, Line &
    Cloth, Light, Other), shown only when the type has fields there, with a count. Fields of a LineType / ClothType
    extension go in Line & Cloth; an unlisted bit-field goes with its word; anything else unlisted lands in Other
    (today only `member_*` and PrimFlags2). Open state is `efl_editor.ptcl_open` (Texture, Colour, Size open by
    default); a search shows matches in every section. Add new particle fields to a section's name list.
  - **Field tooltips:** each field's name is an `albam.efl_field_info` button whose dynamic `description` is
    `field_tooltip(item)`: the plain-language help from `efl/field_help.py` (`HELP["<slot>:<field>"]`, slot gen /
    ptcl / life / move / collision / culling; `item.help_key`), an editing hint per type, the evidence tier, and the
    schema note as "RE note". Property descriptions can't vary per field, so the value widgets only point at the
    name. Every new schema field needs a `HELP` entry. Note that `schema.all_structs()` doesn't include the
    LineType / ClothType extended structs; coverage checks have to build them with `schema.extended_struct`.
- **Change Type** (`efl/retype.py` + `effect_retype.py`, Particle / Move tab button `albam.efl_change_type`): a
  block's type can't just be relabelled (each type has its own layout), so a new block is built:
  - Its bytes start from a **template**: the real block of that type (and LineType / ClothType variant) with the
    fewest keyframes. The search covers the imported effects, then every `.efl` under the Game Files roots. Game
    Files are indexed once per session in `effect_retype._templates`.
  - Without a template the block starts from zeros plus `retype.DEFAULTS`, and the report says so. Filter and Hit
    are template-only, because only a minimum size of their layout is known.
  - Fields with the same name and type are copied from the old block, including unapplied edits
    (`current_block`). The extension-choosing fields (LineType, LineOfsNum, ClothType) and their words are the
    exception: only the other bits of those words are copied. In Polyline / ClothPolyline the ClothType bits live
    in `SizePlaceFlags`.
  - The old block's keyframes and collision / culling data are appended for offset fields the new type has. The
    template's keyframes are dropped; its collision / culling data is kept when the old block had none.
  - Source records store the result in `efl_replaced` ({slot: {type, data}}), which `build_efl_bytes` swaps in at
    the same file position (`_replace_block`). New records rewrite `efl_raw`. A pending `efl_replaced` counts as a
    structure change, so Apply rebuilds the effect.
  - Generator and life types aren't offered: their layouts are identical and what the type changes is unknown.
    ClothLine (14) and move 7 aren't offered either.
  - Test: retyping 60 sampled files' blocks to every type and variant (14,807 cases) writes, reads back, keeps the
    shared fields and keyframes, and simulates.
- **Linked `.efs` / `.ean`:** importing an `.efl` also brings in the files its records reference
  (`_EffectBuilder.efs_for` / `anim_for`), as `EFS_` meshes parented to the first generator that uses them (points in
  game axes, `efs_space = "game"`, so the strip shows where particles ride) and `EAN_` holders under the root. They
  carry `efl_root` and `efl_linked` (`"efs:<path>"` / `"ean:<path>"`); `effect.linked_objects(root)` finds them. The
  preview reads their current data, not the disk. `root['efl_linked_hash']` (crc32 hex strings) records what the
  effect was built with; `effect_export.linked_changes` / `structure_changed` make Apply rebuild after an edit, and
  `rebuild_effect` keeps the linked objects (re-parented, moved into the new collection; ones no longer referenced
  are removed). `export_efl` returns the `.efl` plus every linked file whose bytes differ from its source. The
  Effect Editor lists them (Linked files box, `albam.efl_select_linked`). Standalone `.efs` / `.ean` import still
  exists for files no effect references.
- **`.efs` strip curves** (`effect_efs.py`, layout in `efl/efs.py`; DX9 and SE share it, field names from the SE PDB):
  import makes an edge mesh `EFS_<file>`, one chain per part, in Blender axes (cm -> m, Y up -> Z up), with point
  attributes `efs_part`, `efs_norm` and the packed `efs_blend_indices` / `efs_blend_weights`. Export rebuilds the
  parts from the connected chains (ordered by `efs_part`, then vertex index; each walked from its lowest-numbered
  end; branches are refused), normalises the normals, and gives unmoved points the source file's exact floats
  (`_keep_unmoved`), so untouched files export byte-identical (all 55). Extruding or Shift+D-duplicating a chain
  copies its attributes; a duplicate becomes a new part after its source.
- **`.ean` flipbooks, edited like UVs** (`effect_ean.py`, layout in `efl/ean.py`): import makes a mesh `EAN_<file>`
  with one quad face per frame. UV layer `Flipbook` = the frame's rectangle as `pixel / ean_uv_size` (V flipped); face
  attributes `ean_seq` / `ean_frame` place it (a Shift+D duplicate copies them and lands after its source). The
  material's active Image Texture is the sheet: the particle's texture when linked from an effect, else a UV-grid
  stand-in of `guess_size` (SE stored UVs, else the frames' extent rounded to a power of two). In Edit Mode the UV
  editor draws the frames over the texture. Export takes each face's UV bounds rounded to whole pixels (every frame in
  the game's files has a positive size). Header and per-sequence settings (default flags, pivot, grid, SE stored UVs)
  live in `ean_data` JSON. The **Flipbook** panel sits in the Image Editor's **Albam** tab, next to the texture asset
  panel (`ALBAM_PT_EanFlipbook`): sequence list, Select Frames (Edit Mode with that sequence selected), New Sequence
  from Selected, the sequence settings, Generate Grid. `_faces` reads through bmesh, because Edit Mode mesh data is
  empty. Untouched files export byte-identical (all 4,127 in plain Python, 300 sampled through Blender). Linked
  flipbooks start hidden (`hide_set`); the Effect Editor's Linked files button unhides and selects them. The eye-icon
  state lives on the collection link, so `rebuild_effect` records it before moving the linked objects and
  `_reuse_linked` restores it (`linked_hidden`); without that every rebuild (e.g. adding a keyframe) showed the
  flipbook's frame grid.
- **New `.efs` / `.ean`** (Effect Editor > Linked files: `albam.efs_new`, `albam.ean_new`; Image Editor > Albam >
  New Flipbook: `albam.ean_new_for_image`):
  - A new strip takes its points from a chosen curve or mesh (evaluated, every chain or spline a part, converted
    into the record generator's space) or a straight line along +Y. The record's `RangeStripPath` (spawn strip) or,
    for PathStrip moves, `PathStripPath` points at it.
  - A new flipbook is a DX9 one-sequence grid over the particle's texture; the particle's `AnimPath` points at it.
  - The objects are linked like imported ones (`efl_root` / `efl_linked`, `original_bytes` empty, so they always
    export). The effect rebuilds right away, so the preview uses them. The game path is the user's (63 characters at
    most), and a path the effect already links is refused.
  - `archive.update_arc` adds entries an `.arc` doesn't have, and both extensions are in the file-type tables, so
    Patch can put new files into the game.
- **Spawn filter** (`effect_filter.py`, verified in IDA 2026-10-06, `efl_import_plan.md` §3.2): the game builds a
  record only if `GroupFlag & group mask` and `MaterialFlag & material mask` are both non-zero. The masks come from
  the spawn call: the group mask picks a variant of the effect, and the material mask is the ground-surface bit
  under the character (`cUtil::getEfctMtrlFlg`; 0 on a ray miss). If nothing passes, nothing is shown.
  - Import options and the Effect Editor's Spawn Filter box set the masks (All Groups / 16 group bits / Surface),
    stored on the root as `efl_group_mask` / `efl_material_mask` (u32 > 2^31 stored as hex strings, like `to_prop`).
  - Every record is still imported, because export keeps only records that have an object. `apply_filter(root)`
    hides the particle/shape objects of records that fail, saving their own hide state in `efl_filter_hidden`, and
    sets `efl_filtered` on the record Empty, which stays visible and editable. The particle handler skips hidden
    objects; showing them again updates them.
  - Re-applied on import, rebuild (masks carried over), Apply, and edits to GroupFlag / MaterialFlag. Export ignores
    the masks: they belong to the spawn call, not the file.

- **Import** (`effect.py`): registered as the dmc4 `efl` import function (category EFFECT), with options
  `scene.albam.import_options_efl` (armature, build geometry, load textures).
  - It returns `None` and links its objects into its own `EFL_<file>` collection, because joint-attached Empties
    aren't children of the root, so the operator's `children_recursive` linking would miss them.
  - **`ParentNo` is the MT joint number** (`bone['mtfw.anim_retarget']`), not the bone name/index. Attach with
    `parent_type='BONE'` and `matrix_parent_inverse = Translation(0, -bone.length, 0)`, so `Pos`/`Quat` apply in
    the bone head frame (Albam bone frames are the game joint frames).
  - **Flipbooks:** effect textures are sheets of frames. `efl/ean.py` parses the particle's `.ean` (`AnimPath`):
    sequences of pixel rects `s16 (x, y, w, h)`. The mesh UVs are remapped into rect `SeqNoMin`/`PatNoMin` as
    `sub_9632F0` does (AnimFlag 0x100 flip U, 0x200 flip V, 0x1000 rotate). Only the first frame is shown; there
    is no animation.
  - **Untextured PrimModels:** types 0 Ring, 2 Sphere and 4 Grid draw in a solid colour; only 1 TexRing, 3 TexSphere
    and 5 TexGrid fetch BaseMapPath (`renderPrimModelRing/Sphere/Grid` 0x9B5D20 / 0x9BADF0 / 0x9BFEB0 never call
    `getTexHandleWrapper`). `effect._base_map(ptcl)` returns the texture the game actually uses; go through it,
    not BaseMapPath. Example: `ec002_00v0` record 27 is a semi-transparent dark purple sphere, not a streaked one.
  - PrimModel meshes come from `efl/primmodel.py` (pure Python). Textures load through
    `texture.build_blender_textures` one path at a time; a missing file raises `KeyError` from `rfs.get_vfile`.
  - **Particles** (option "Simulate particles", on by default) for Billboard/Polygon/PrimModel records:
    - `efl/sim.py` reproduces emission, spawn shapes, direction, Add/Mul motion, life fade and flipbook
      timing, ported from the DX9 runtime (addresses in its docstring). It is pure Python and deterministic
      (seeded per record).
    - `effect_sim.py`:
      - Each record gets a point-cloud object under its generator, with the `ALBAM_EFL_Particles_v1`
        Geometry Nodes group. The group instances the hidden source shape and applies per-point `rot`,
        `scale3`, `alpha`, `uv_off` and `uv_scale`.
      - A `frame_change_pre` handler (registered in `albam.register()` like foot IK) rewrites the points.
    - Game frame = (scene frame - `root['efl_start_frame']`) x 60 / scene fps.
    - Particles move in the generator's local frame, so they follow the bone (in the game they're
      world-space after spawn).
    - The `.efl` bytes are stored base64 in `root['efl_data']`, so playback survives save/reload.
    - **Emission space** (`sim.emission_space`):
      - Move-None particles follow the generator: their points object is parented to it.
      - Add/Mul particles stay where they were emitted: their points object is unparented, and they use the
        generator's world matrix at their birth frame. Those matrices are recorded by a
        `frame_change_post` handler while playing, or all at once with `albam.efl_record_motion`.
  - **Materials** follow the game's D3D9 blend state:
    - BlendSrc/BlendDst/BlendOp nibbles = enum - 1, built as `Emission(src*Fs) + Transparent(Fd)`;
      reverse-subtract becomes darkening.
    - Colour x Intensity and alpha come from the `EdgeAlpha` colour attribute, written per particle by the
      GN group (v3) or baked into static meshes.
    - `MtColor` bytes are **B, G, R, A** (`schema.bgra_to_rgba`).
    - **AnimFlag** is `rEffectAnim::ANIM_FLAG`. In DX9, `uEffectVFR::getAnimFlag` 0x980140 gives each particle 0x200
      (flip V) for VFLIP_RAND 0x800 and 0x100 (flip U) for HFLIP_RAND 0x400 with probability 1/2 each; 0xC00 is the
      most common value in the files (7,989 particles). The preview rolls them per particle (`sim._random_flips`,
      `Particle.flip` / `ParticleState.flip`, applied to the frame row by `effect_sim._frame_row` with
      `ean.flip_affine_row`). REVERSE_RAND 0x10 isn't handled in DX9 (no file uses it); KEYFRAME 0x8000 is set at
      runtime (with MOVE) when there's a PatNo keyframe.
    - **Particle header (verified 2026-10-08 against SE `rEffectList::EFL_PARTICLE_COMMON`, `PARTICLE_OPTION_FLAG`,
      `CULLING_FLAG`, `nPrim::Material::AttributeType` and the DX9 readers; details in the schema notes and
      `efl_import_plan.md` "Particle header flags"):** 0x02 is a u8 `CullingFlag` (1 ON, 2 OCCLUSION, 4 PARTICLE,
      0x80 ANGLE) and 0x03 a separate u8 `VolumeBlendRate` (SE `BlendState`): non-zero selects the VOLUME pixel
      shader (DEPTH_VOLUME / PARALLAX with option 0x800 / 0x400) and is written into every vertex; 26,626 particles
      have it, and the preview ignores it. They used to be one u16; `edit.upgrade_props` converts props stored by older
      imports (also `uknDraw_0x14` -> `OtDepthBias` f32), on export and when the Effect Editor loads the record.
      `ParticleOptionFlag`: see the schema note; 0x8 INV_VOLUME has no DX9 reader, and 0x80000 (SE
      EDGE_ALPHA_OFF) **turns the PrimModel edge fade on** in DX9 (`buildPrimModelRing` 0x9CDB1B), as `primmodel.py` does. `LightGroupFlag` is the light-group
      mask models use too (per the user, TransMode and the light group are uModel-wide): Light particles hand it to
      their light (`updateParticleLight` 0x99C1BB; 0xFFFFFFFF on 153 of 177), other particles are lit when it's non-zero
      (ATTR_LIGHTING; 337 Model, 21 Polygon). Light `LightAttribute` = `rEffectList::LIGHT_ATTR` (2 SH, 8 PERPIXEL,
      0x10 SIMPLE = every file; written | 0x40 into the light). Shadow groups: DX9 `uModel` has `mLightGroup` +0x130 (from the
      `.mod` header 0x88, `model_info.light_group`, via `uModel::setModel`; constructor default 3), `mShadowCastGroup`
      +0x134 and `mShadowRecvGroup` +0x138 (default 1, not loaded from the `.mod`). Effects have no shadow group in
      DX9 (SE's Model particle `ShadowCastGroup` / `ShadowReceiveGroup` at 0x10E/0x10F don't exist there: the DX9
      Model block has zeros at 0x114-0x11F in all 853 files and no reader); they only have TransMode's shadow bits.
      Not modelled in the preview: soft edges, volume, lighting (ROT_LOCAL / ROT_INIT / MDLSCL_AFTER are, for Model /
      PrimModel: see "Model / PrimModel orientation" below).
    - **ModelAnimFlag** is `nEffect::MODEL_ANIM_FLAG` for 1/2/4/8, but in DX9 **0x10 is UV scroll** (initParticleModel
      0x97BB04, move 0x99008D, renderModel 0x9A228B), not SE's REVERSE_RAND: all 179 records with 0x10 have non-zero
      ScrollU/V, and only 1 record with it has none. 0x10000 = ModelZofs; 0x10000000 and up are runtime state.
    - A particle's start colour follows `ColorFlag` (`nEffect::COLOR_FLAG`, `sim._src_color` = DX9 `calcSrcColor`):
      bits 1/2/4/8 mix R/G/B/A from Color0 toward Color1 by a random t, 0x10 re-rolls t per channel; 0x20 CHOICE
      isn't in DX9.
    - `TransMode` is a render-pass mask (`cTrans::MODE`: 0x1 WORLD = main view, 0x2 REFLECTION, 0x4 SHADOW_RECV,
      0x8 SHADOW_CAST, 0x10 ENV, 0x20 MOTIONBLUR; the files use 1, 0 and once 3): without 0x1, no geometry is built.
      The game's gate (`uEffectVFR::isGeneratorVisible` 0x53D460) ANDs the view's mode word with the generator's:
      TransMode in bits 0-7 and PassBits (PrimMaterialFlags bits 12-15) in bits 8-11, so PassBits is a second view
      mask, not a `cTrans::PASS`. `cTrans::PASS` (0 BEGIN ... 6 EFFECT, 8 FILTER, 9 SCREEN) is a draw's sort layer;
      refraction draws in 8 FILTER. Details in `efl_import_plan.md` "Draw gate and passes".
  - **Rotation orders** (verified 2026-10-09 by emulating the DX9 `MtMatrix::setRotate*` functions with Unicorn,
    `setMatFromAngle` 0x95FF70): RotOrder 0-5 apply the axes in the order `sim.ROT_ORDERS` = XYZ, XZY, YXZ, YZX, ZXY,
    ZYX (first letter first = Blender's Euler order string), although the game calls them setRotateZYX, ZXY, YZX, YXZ,
    XZY, XYZ (`sim.ROT_ORDER_NAMES`). Until then the preview used the names as the order, so every rotation with more
    than one non-zero angle was wrong: move Rot directions (3,751 records), particle Rot (2,090 Polygon, 1,342
    PrimModel, 554 Model, 46 PolygonStrip), generator rotation keyframes, chain / line / culling directions. Every
    effect-side Euler goes through setMatFromAngle (calcDir, calcParticleMatrix, the path moves, sub_9600A0 = Euler ->
    quaternion for the generator keyframes, sub_988B00 = the Polygon / SizeBillboard / strip / Light matrix). The
    Effect Editor shows "XYZ (game ZYX)" etc.
  - **Model / PrimModel orientation** (`effect_sim._model_rotation`, `uEffectVFR::calcParticleMatrix` 0x98A6A0, info
    `orient`): column form `G . R`, R = Euler(Rot, RotOrder) (Model's RotOrder comes from ModelFlags now; it was
    always 5), G = the generator's **current** rotation (Generator+0x150, rebuilt every frame by updateWorldMatrix), also
    for Add / Mul particles (they used the birth rotation before). ParticleOptionFlag 0x100000 ROT_LOCAL: no G (game
    world axes). 0x200000 ROT_INIT (also sets ROT_LOCAL): `Rot += Euler(spawn-time generator rotation)` (sub_98C800;
    the spawn call never carries the direction flag, so it never aligns). Otherwise DirAxisType != 6 replaces G by the
    shortest rotation taking that axis onto the move direction (None: the spawn direction through the current
    generator; Add / Mul / paths: the frame-to-frame position change). Game world -> Blender is the constant
    `GAME_TO_BLENDER` (as `world_axes`). Polygon uses the same rules (`sub_988B00`, without MDLSCL_AFTER;
    renderPolygon passes the particle's stored move flags +0xEE and direction), so kind 2 gets `orient` too.
    PolygonStrip (also sub_988B00) and Polygon camera facing (PolygonBillBoardType 1 / 3, 469 particles) aren't
    modelled.
  - **Scale after rotation** (0x40000 MDLSCL_AFTER, 904 Model / PrimModel particles with a non-uniform scale): node
    groups `ALBAM_EFL_Particles_v5` / `ALBAM_EFL_Models_v3` end with `_after_scale`: position = p_center + (position -
    p_center) x scale_after (point attributes; (1, 1, 1) otherwise, and ModelScale then goes into scale3). The axes are
    the points object's: right for Move None (parented to the generator), approximate for world-space particles.
  - **Culling fade** (`sim.culling_params` / `culling_fade` = `uEffectVFR::calc_culling_fade` 0x963BD0, info `culling`,
    `effect_sim._Culling`): with the particle's CullingFlag bit 0, alpha x= distance fade (option 0x2000: hidden at
    <= NearStart or >= FarEnd, linear in the near / far bands, 0x4000 / 0x8000 cut instead) x angle fade (block flag
    0x80: a = acos(dir . to camera), 1 - a / AngleEnd, or with 0x800 1 until AngleStart then by Rate; 0x1 also the
    opposite direction, max, or min with 0x1000). dir = calcDir(CullingRot) turned by the generator; measured once at
    the generator, or per particle with block flag 0x4. Uses `scene.camera` and updates on frame change. Applied to the
    GN particles, line ribbons and sword trails; Model particles have no per-particle alpha.
  - Billboards are pixel-sized: `Scale x pattern px (x AspectRatio)` in cm on a 1 cm source quad.
  - **Camera facing.** Billboard particles (type 0) are expanded by the vertex shader along the camera's right / up axes
    (the CPU passes only corner codes, `sub_961250`), so they lie in the screen plane: the preview uses the scene
    camera's rotation (`cam_rot`), not a look-at toward its position (fixed 2026-10-09). Only the scene camera counts,
    and the points update on frame changes, not when the viewport is orbited. Polygon / Model / PrimModel have a
    billboard mode (PolygonBillBoardType = PolygonFlags bits 20-23, ModelBillboardType = ModelFlags bits 8-11 /
    PrimFlags bits 24-27) read by renderPolygon / renderModel / renderPrimModel* into `build_view_basis`: 0 none,
    1 the camera's rotation (view-inverse at render context +0x100) multiplied after the particle matrix, 2 / 3 / 4 keep
    world X / Y / Z and turn the rest toward the camera. Files: 1 on 465 PrimModel, 340 Polygon, 179 Model; 3 on 129
    Polygon. The basis multiplies the **whole** particle matrix (renderPolygon 0x99F8AD: P . V, P from sub_988B00 with
    the generator), so in column form it is `V . G . R`: G (generator rotation, alignment, or none with ROT_LOCAL)
    still applies, and only an unrotated generator gives a screen-aligned particle. Preview: `orient["billboard"]`,
    `effect_sim._view_basis` (modes 2-4 build a reflection in the game; one axis is negated so Blender gets a rotation).
    Example: `ec002_00v0` records 5-8 (Polygon, mode 1) were tilted before this (2026-10-09).
  - Polygon `Width`/`Height` are **half-extents** (the quad is 2W x 2H); `PolygonFixType` is the pivot, `PolygonAxis`
    the plane, `DistortRate` scales each corner (`effect._polygon_mesh`).
  - **Per-particle shapes** (Polygon W/H, PrimModel Radius0/1 + Height0/1, growing by their Add fields or keyframed):
    every source vertex is linear in the four shape values, so the source mesh carries basis attributes
    `shape_a..d` + `src_co` (`effect._set_shape_basis`, `primmodel.PrimMesh.basis`) and the node group
    (`ALBAM_EFL_Particles_v4`, now v5) moves each realized vertex by `rot(scale3 * (sum(basis * shape) - src_co))` where the
    point's `shape_on` is 1.
  - Model UV scroll (ModelAnimFlag 0x10): `offset += speed` per frame (ScrollU/V or their keyframes), wrapped to
    [-1, 1]; `ALBAM_EFL_Models_v2` adds it to the meshes' `uv1` (V negated).
  - **Spawn flags** (verified 2026-10-10, schema notes; IDA names `calcRangeStrip*`, `calcSpawnOffset`):
    `MoveOptionFlag` 0x1 COLLISION has no DX9 reader (collision = `CollParamOffset` set); `RangeOptionFlags` 0x1
    EACH_FRAME numbers particles by spawning frame (`sim.simulate`: a frame's batch shares one RangeDivideNum slot /
    ORDER strip index; no game file combines it with either); `uknRangeFlag` is `RangeDisperseType` (renamed,
    `RENAMED_PROPS`); `RangeStripType` picks the sampler (0 point, 1 line, 2 / 3 curves = linear in the preview, 4
    triangle, unused); `RangeStripFlag` 0x20 ALL_PARTS with RangeDivideNum spreads the slots across all parts
    (`strip_point`), 0x40 SKINING isn't previewed. The editor shows them as checkboxes / enums.
  - **Life** (`EFL_LIFE_FRAME`, verified 2026-10-10, schema notes): Appear / Keep / Vanish frames, and `KeepOptions`
    = `HoldUntilEffectEnds` (SE KeepHoldFlag) + KeepFrame keyframe offset + `HoldFrameLimit` (SE KeepHoldFrame;
    renamed, `edit.RENAMED_PROPS` upgrades props stored under the old names). A held particle's Keep phase waits
    until the effect's owner ends it (`checkEnd` -> `doFinish` / `doKeepHoldOff`), a path move ends with
    PathOptionFlag 4, a collision with CollFlag 4, or the limit runs out (then Vanish at once); then KeepFrame and
    Vanish. 1,506 particles hold, nearly all with KeepFrame 0-1 and no limit, so they used to flash for a frame in
    the preview; now they last until the end of the simulated range (`sim.spawn`). Life types are SE
    `LIFE_TYPE` 1 FrameAlpha, 2 FrameColor (the files), 3 / 4 Keyframe Alpha / Color (DX9 reads them; no file).
  - Keyframes: a keyed value is absolute (its `*Add` is ignored); InitOnly keys are evaluated once at spawn and then
    the Add applies (`Particle.keyed_or`). The generator's Range keyframe replaces Range (s and r) at spawn; rope
    keyframes (Length = total, Rot / BlendRot = re-derived pull directions, BlendRate) use the generator timer for
    PathChain and the particle timer for CHAIN trails.
  - Polyline/Line particles (`RIBBON_TYPES`, simulation only) are camera-facing ribbons whose mesh is rebuilt
    in world space every frame (`effect_sim._update_lines`); there is no GN group for them.
  - Particle types and their Blender objects:
    - Billboard / Polygon / PrimModel: GN instances (`ALBAM_EFL_Particles_v3`).
    - Model: GN collection instances (`ALBAM_EFL_Models_v1`); the `.mod` is imported once off-scene, in game
      axes.
    - Light: a pool of point lights under a holder Empty.
    - Polyline / Texline / Line and the cloth variants (1, 3, 4, 12-14), and PolygonStrip (15): meshes rebuilt
      per frame.
    - Types 12-14 are the *cloth* variants. 15 is PolygonStrip, a sword trail.
  - **Cloth** (12-14) runs by ClothType (`sim._ClothChain` / `_cloth_curve` / `_cloth_zigzag`): 0 CHAIN is a rope
    from the particle to the tail `SubOfs` under a constant pull; 1 CURVE is an analytic bend; 2 ZIGZAG is the bend
    plus random jitter (lightning). It's simulated in generator space. World-fixed pulls use the generator's world
    axes measured at import (`info['world_axes']`), so they're wrong if the bone rotates a lot afterwards.
  - Generator keyframes (position/rotation/scale) are baked as F-curves on the generator Empty.
  - RangeStripPath and PathStrip load `.efs` through RFS.
  - Collision uses a ground plane at world z = 0, measured in generator space at import.
  - Path moves (3-6) ride the generator until released. Each `ParticleState.anchor` says which generator
    frame places it: None = the current frame.
  - Headless test: import `arctool\uPlayerNero-vanilla\model\game\pl000\pl000.mod`, pick its armature, then import
    every `effect\efl\**.efl` (110 files, 0 failures). EEVEE and Cycles renders of the textured character crash
    headless on this machine (GPU/memory); hide the character meshes to render effects alone.

- **Test:** `python engines/mtfw/scripts/efl_check.py "E:\DMC mod stuffs" [--coverage] [--json-dir DIR]` (plain
  Python). It must report `round-trip ok: 1109` and `no check issues`.
  - The DX9 files are mostly under `E:\DMC mod stuffs\arctool\*`. `Demo\` and `arc files\` hold SE files
    (`0x20120306`), which the parser rejects.
- **Container:** a 0x20-byte header, then 16-byte records of four packed dwords `(offset << 8) | type` (gen, ptcl,
  life, move). Offsets are relative to file+0x20.
  - Each block runs to the next block start, so it includes its trailing keyframe/culling/collision data.
  - The writer recomputes all offsets, so blocks may change size.
- **Extensions are schema fields.** `schema.struct_for_data` gives Polyline/Texline/Line blocks a struct extended by
  their LineType extension (FIX points, CHAIN = EFL_PARAM_CHAIN, LENGTH stick) and cloth blocks (12/13) one extended
  by their ClothType extension (ClothCHAIN / ClothCURVE / ClothZIGZAG), e.g. `EFL_PARTICLE_Polyline+CHAIN`. Their
  keyframe offsets are ordinary `sub=` fields, so they're parsed, checked, edited and written like any other.
  `Struct.base_size` is where the extension starts (sim.py reads raw extensions from there);
  `schema.struct_for_props` rebuilds the same struct from stored props. `schema.FIELD_ALIASES` maps renamed fields
  (the generator keyframes 0x1D4/0x1D8/0x1DC are now KeyframeRange/Pos/RotParamOffset).
- **Schema offsets are file offsets.** The DX9 IDB's `EFL_GENERATOR` and `EFL_PARTICLE_*` types were retyped to
  match them on 2026-10-05. The old declarations are in `Vibed/RE/type_backups/`.
- **Self-relative offsets:** fields with `sub=` in the schema (rel16/rel32) point into the same block. A bit-field
  can hold one too (`Bits.sub`; the life `KeyframeKeepFrameParamOffset` = bits 1-15 of `KeepOptions`): go through
  `Struct.offset_fields()` / `offset_field(name)` rather than `struct.fields` when looking for offsets. Offsets are
  never props (`block_props` / `apply_props` skip them); the keyframe write-back sets them.
  - **Keyframe audit (2026-10-10):** every DX9 keyframe read goes through `getKeyframeTimer` / `calcKeyframe*`
    (~60 callers). Matched against the schema: Line `0x54` was a colour keyframe for its second colour (PlaceColor
    at 0x58; now `KeyframePlaceColorParamOffset`, no file uses it), Billboard `KeyframeAngleParamOffset` 0x190 is
    read by `initParticleBillboard` (promoted to dx9). LiteBillboard / SizeBillboard (16 / 17) have readers but no
    files and only their 0x170 common part is known (SizeBillboard reads keyframe offsets at 0x1D8 / 0x1DC), so
    Change Type no longer offers them. 16-bit offsets are loaded as `dword & 0xFFFF`, so a scan for them must allow
    that. Keyframe
  sub-blocks are a header dword (`EFL_KEYFRAME_INDEX`) followed by SE-layout keys, padded to 16 bytes. Key sizes:
  f32/color 12, u32 8, vec3 28.
- Paths are stored without an extension, like `.mod` texture paths.

### Model chains (soft-body links, `.phs`)

Researched 2026-10-05, supported 2026-10-10 (import / export, motion preview). Runtime: `Vibed/RE/chain_cnschain.md`
(the whole solver, the resource copy and the collision helpers; IDB names applied).

- **Not the effect chains.** EFL LineType / ClothType CHAIN ropes (`efl/sim.py` Rope / `_ClothChain`) are a separate
  system in the game (uEffectVFR moveChain 0x994C20, cloth 0x992EC0, their own parameters); cCnsChain (move
  0x42DB00, solver 0x430A20) shares no code with them beyond sqrt / sin / cos. Keep the code apart: model chains are
  `engines/mtfw/cns_chain.py`, `phs_*` properties, `import_options_phs`, bone collections `Chain <file>`.
- **Import workflow** (redone 2026-10-10; no armature picker): import the `.mod`s, `.phs` and `.col` in any order
  and they connect themselves (`cns_chain_preview.wire_scene`, run after every dmc4 `.mod` with bones, `.phs` and
  `.col` import).
  - **A chain's model** is the first `<name>.mod` that exists in the Game Files, from the chain's own name down
    (`chain_model_path`, stored as `phs_model`): pl000_03_00 -> pl000_03.mod. Only that model's imported armature
    is used (`find_model_armature`; it must have every joint), because one character's models share joint numbers
    (the coat has the body's 0-38). The active armature is the fallback only when no model file is found.
  - **A `.col`'s armature** (`col_shapes.find_col_armature`): next to `<name>_NN.phs` chains (pl000_03.col) it's the
    body `<name>.mod` (pl000.mod) only; otherwise the model named like it, or the longest model name it starts with
    (em010shl.col -> em010.mod), picking the one with the most of its joints (shapes on joints it lacks are skipped
    and listed), else the active armature.
  - **The chain's collision** is the COL_ object of `<chain minus _NN>.col`; a coat (`COAT_BODY_JOINT`: pl000_03,
    pl006_03 -> joint 2) is attached to the shapes' body armature.
  - **Still missing** pieces are listed on the chain (`phs_status`) and shown in the Chain panel. **Attach to
    Armature** (`albam.attach_to_armature`, Chain and Collision Shapes panels) moves a chain or a COL_ object to
    another armature (defaulting to the one found automatically).
- **Blender** (`cns_chain.py`, registered for `phs` and `clt`, category CHAIN): import makes an Empty `PHS_<file>`
  (parented to its model's armature, see above) with every rCnsChain
  setting as a custom property with a tooltip (mDir / mUp / mParentMode with min / max), `phs_joints` (the joint
  list) and a bone collection `Chain <file>` on the armature (bones matched by `mtfw.anim_retarget`). Export
  re-reads the source XFS and writes only what changed (all 41 files round-trip byte-identical, with or without an
  armature); the joint list comes from the bone collection: bones still in it keep the source order, new ones go
  after their parent. A chain can hold several strands or branch (Sanctus' pl023 chains), and the slots after the
  first -1 may hold leftovers (kept when the chain is unchanged). Errors: more than 32 joints, a bone without a joint
  number, an axis value out of range.
- **Motion preview** (`cns_chain_preview.py`, Object Properties > Chain on the `PHS_` Empty, `ob.albam_phs`):
  the DX9 solver (cCnsChain::move 0x42DB00 + calcJointImpl 0x430A20) replayed on the armature while the animation
  plays; preview only (nothing keyed, export unchanged).
  - **Per frame:** `frame_change_pre` puts the chain bones back to their pose without the preview (`phs_preview_base`,
    stored when it's turned on) so the animation drives them. `frame_change_post` reads the animated pose, steps
    every previewed chain of each armature round(60 / fps) times in hierarchy order, and writes the bones'
    `matrix_basis`.
  - **Cache:** frames are cached per armature. Playing forward steps; a cached frame shows its pose; any other frame
    restarts there (a 2-frame reset that copies the animation, as the game does). **Simulate Range**
    (`albam.phs_simulate_range`) fills the scene range.
  - **Parent frame:** the armature object times its `root_motion` bone (mParentMode 1: its parent armature's).
  - **Collision:** `albam_phs.collision_shapes` = an imported COL_ object (set by wire_scene); the shapes are placed
    from the parsed `.col` and its armature each step, every shape in file order.
  - **Attach to Body** (`albam.phs_attach_to_body`, done by wire_scene for coats): parents the chain's model so its
    joint 0 follows a body joint (2 for Nero's coat: in the game a cCnsMatrix puts coat joint 0 on body joint 2; the
    coat's LMTs don't move joint 0). Without it the coat stays at the origin.
  - **Game quirks kept:** mDamping > 1 (Sanctus: 10 / 20) only bounded by mMaxSpeed; mTurbulence never applies at a
    steady 60 fps; a pushed joint position survives only for the chain root, so segments can still clip a capsule
    mid-length in fast motion; mBlend < 1 and bind offsets off the mDir axis change segment lengths.
  - **Tests** (headless, scratch): with no forces the rest pose holds exactly; all 41 DX9 chains run on their models;
    Nero's coat on a body + coat LMT pair, attached at joint 2, collides with pl000_03.col (~8 ms per frame for six
    chains).
- **DX9 chains are `.phs` files** = class **`rCnsChain`** (file-type id `0x006F4D08` = `~crc32("rCnsChain") &
  0x7FFFFFFF`, DTI hash 0x4D990996), **XFS v5** (SE stores the same class as XFS v15 with the raw hash as extension).
  dmc4_xml reads and writes them byte-exact (`dmc4xml/xfs.py`, all 297 DX9 XFS files). 41 unique files, all under
  `arctool` (players pl000 / pl006, enemies em010 / em018 / em030 ...); the game's own extension is `clt`.
  - One chain per file: `mBone` = S16[32], -1 padded, a parent-linked run of bones of the **attached model**
    (pl000_03_00..05.phs = the six coat tails of `pl000_03.mod`, the coat model, bones 1-7, 8-13 ... each starting
    under bone 0). Physics: mGravity, mSpring, mDamping, mMaxSpeed, mWind, mTurbulence, mTailLength, mFloorLevel,
    mCollisionSize, mStretch / mStretchLimit, mBlend, mDir / mUp (axis enums), mParentMode and *Local flags;
    `mBoneData` = 32 x `cBONE_DATA` per-bone limits (never enabled in the files).
- **Collision shapes: `.col` = `rCollisionShape`** (file id `0x5B9071CF`, DTI 0x4EA4E09A): the hitbox format (see
  ROADMAP "Hitboxes"); chains collide with its shapes on the body model (`pl000_03.col`). Codec: `dmc4xml/col.py`
  (byte-exact on the 110 DX9 files).
  - **Import** (`col_shapes.py`, dmc4 `col`, category HITBOX, import only): an Empty `COL_<file>` in its own
    collection (group kinds / flags as properties, `col_shapes` JSON = the shape objects in file order) and per shape
    a sphere Empty (size = radius) bone-parented at its joint offset (joint -1: placed in the model's own space, a
    guess), or for a
    capsule one per end plus a wire tube whose two rings are hooked to the ends (follows the pose exactly), coloured
    by group flags (attack red, grab yellow, hurt blue, push green). Shapes on joints the armature lacks are skipped
    and listed (`col_missing_joints`); type 1 shapes are skipped. Nero's `Collision\pl000.col`: 205 groups, 575
    spheres. Panel: Object Properties > Collision Shapes (summary per kind / flags, Attach).
  - **Groups follow the LMT events** (`col_shapes.active_groups` / `update_visibility`, run by the chain preview's
    `frame_change_post` handler): bit k (k < 8) of the first event table's value switches on group
    `events_params_01[k]` ("Hitbox Slot Values") of the action playing on the shapes' armature; XOR consecutive
    values to see which slots change. Other groups' objects are hidden with `hide_set` (still evaluated). On by
    default for hitbox files (`col_follow_events`), off for a chain model's body shapes (pl000_03.col isn't indexed
    by the events). Without LMT events every group is shown. Seen in the data (Nero: slots 0 / 1 = hurt + push
    groups 5 / 6; the Snatch, pl000_02 block 30, turns on grab groups 120-122 on frames 9 / 10 / 11 and off on 17),
    not traced in the game code.
- **Cutscenes** drive chains through `uCnsChain` units in `.sdl` (m01_100s_B, m20_100s): object `mCnsChain`
  (cCnsChain) with `mpCltRes` (the .phs), `mpModel` (ref -> model unit), `mpCollisionShape` (the .col),
  `mpCollisionModel` (ref -> the model carrying the shapes) and keyed mBlend / mWind / mEnable / mFloorLevel /
  mCollisionSize / mChainReset / mGravityLocal. These already import / export through the SDL support.
- **Not used by DMC4:** `.chn` (`rChain`, `0x3E363245`) and `.ccl` (`rChainCol`, `0x26E7FF`) are later MT Framework
  formats; the `.chn` / `.ccl` under `arctool\uPl01ShebaCos2` are Dragon's Dogma files.
- **Runtime classes in the DX9 IDB:** `uChain` (`JointWork`, `CollisionWork`), `cCnsChain` / `uCnsChain` /
  `uCnsChainReset`, `uCloth::Chain`, `rClothXml::Chain`, `rLeafAnim::Chain`, player members `mCnsChainL/R` and
  `mCnsChain0..5`.
- **Upstream support:** neither `HenryOfCarim/albam_reloaded` nor `Brachi/albam` has it (`Brachi/albam`'s "chains"
  are LMT limb IK chains, `joint_type` on a chain's root track; this fork's export always writes `joint_type = 0`).

## Kaitai structs

- `structs/*.py` are generated by `kaitai-struct-compiler` in **read-write** mode (`_write`, `_check`), except `mfx.py`, which is read-only.
- There is no build script, so regenerate by hand and keep the `.ksy` and `.py` in sync.
- Known drift: `mod_156.py` has only `mod-156-bkup.ksy`, and `sbc_21.py` has no `.ksy`.
- Serialization pattern:
  1. Build `Cls.Sub(_parent=, _root=)` objects and set their fields.
  2. Call `_check()`.
  3. Compute the total size from the `size_` instances defined in the .ksy.
  4. Pre-allocate `KaitaiStream(BytesIO(bytearray(size)))`, then `_write()`.
- If you add fields to a .ksy, update its `size_` instances too, or the writes overflow or truncate.

## Error handling

Operators wrap their work in try/except and call `bpy.ops.albam.error_handler_popup("INVOKE_DEFAULT")` from **inside** the `except` block, because the popup reads `sys.exc_info()`. Raise `exceptions.AlbamCheckFailure(message, details, solution)` for user-facing validation errors; it is used by the `@check_dds_textures` and `@check_mtfw_shader_group` export decorators.

## LMT key timing (confirmed in IDA, fixed 2026-10-05)

**Sources:** IDA (`uModel::calcMotionQuaternion` @ 0xAE0400, IDB `Vibed/DevilMayCry4_DX9.exe.i64`, ida-pro-mcp on port 13337, JSON-RPC `tools/call` at `http://127.0.0.1:13337/mcp`), plus every DX9 LMT under `Dante Cyber porting` (9,307 tracks).

- **Game semantics:**
  - Stored keys start at **frame 0**; the first stored key always equals `ref_data`.
  - A key's duration is the **number of frames to the next key**. Interpolation is `(frame - key_start) / duration`.
  - **Duration 0 marks the last key**, which is then held.
  - For every type-9 track the durations add up to `num_frames - 1`, and for 94% of type-6 tracks; the rest end early and hold.
  - The `FrameQuat4_14` bit layout matches Albam's (17/17/19 bits, 3 sign bits, 8-bit duration in the top byte).
- **Until 2026-10-05, Albam got this wrong on both sides:**
  - It put the first stored key on frame 1, inserted `ref_data` on frame 0, and used `duration = gap - 1`.
  - Imported animations came out about twice as long, so events and loops didn't line up with the motion.
  - Exporting keys on consecutive frames wrote duration 0, so the game stopped after the first key.
- **Now:**
  - Import and export follow the game.
  - Re-exporting the game's `m20_100s_cut01.lmt` reproduces its key durations exactly on every animated track.
  - Positions and scales match exactly, and rotations within compression precision.
  - Rotation `ref_data` is the first key in game space. The old export wrote it in bone space.
  - The parented-location `- 1` and scale frame-0 quirks are gone.
- **Breaking change:** .blend files with animations imported before this fix hold stretched keys, which now export at double length. **Re-import those LMTs.**

## Known bugs and gotchas

These are recorded, not fixed. Don't "fix" them silently in unrelated changes.

- Texture slots don't round-trip:
  - Import maps shadowmap→UNK_01 and additionalmap→ALPHAMAP.
  - Export writes shadowmap←ALPHAMAP and sets additionalmap to 0.
- The detail-map driver path is hardcoded to `re5__mod_156_material` (`texture.py`), which is wrong for dmc4.
- `animation.py`:
  - `world_pos_fix` is a no-op.
  - Several GroupHash bits overlap (kept as found).
  - Type-6 rotation keys whose z component is close to 0 can come out about 0.04° off after re-export. The compression rebuilds z from the other values, so near zero it is very sensitive to rounding.
- `collision.py`, SBC21 path only (other games): `_serialize_bvhc` reuses one node object for every node, and
  `export_sbc` shadows its `errors` list in an `except ... as errors`.
- `unregister()` doesn't unregister the factory or `prop_types` classes, so hot-reload can leave stale state. Restarting Blender is the reliable fix.
- LMT code uses `action.fcurves` / `action.groups`, which is likely to break on Blender 4.4+ slotted actions.
- `copy_custom_properties_to/from` is duplicated across modules (`# FIXME: dedupe`).
- The error popup links point to upstream Albam, not this fork.
- `texture.py` prints every texture path it loads (a leftover debug `print`).
- EFL materials: reverse-subtract (darkening) blends dim the background with transmittance
  `max(Fd - k x src x Fs, 0)` instead of subtracting (node group `ALBAM_EFL_Darken_v3`, Value node `Strength` = k,
  shared by every effect material). k is **Darkening Strength** (`import_options_efl.darken_strength`, default 1.5,
  also in the Effect Editor), which updates the group live. Measured against the formula on a quad of colour
  (0.6, 0.3, 0.2), alpha 0.5: k = 1 is 0.12 too light over a 0.6 background, k = 1.5 is 0.03 off, k = 2 is 0.06 too
  dark. Over a 0.1 background every k stays about 0.085 off. Particle edits (blending, textures) rebuild the effect on
  Apply.
  - **Draw order, game vs Blender** (tested headless 2026-10-07): the game depth-sorts effect primitives
    (`uEffectVFR::setPrimEnv` 0x99DB60 returns an ordering-table depth from the generator position; ParticleOptionFlag
    0x1 OT_DEPTH returns the marker 0x8000 so each particle is sorted at its own position (`sub_961250`), 0x2 OT_FIX
    = `FixOtDepth`, 0x100 OT_UNIT = the owning unit's position, the sign bit moves the point toward the camera by
    `OtDepthBias` (0 in every file), and 0x40 NO_CLIP keeps depths behind the camera, which are otherwise dropped). EEVEE 4.2 sorts blended objects by **object origin** depth, and exact ties go to **creation order** (later
    = drawn last); names and material slots don't matter. Records at the same generator therefore draw in record
    order in both. World-space particle objects (Add/Mul moves, ribbons) have their origin at the world origin, so
    their order is wrong; fixing it means giving them the generator's origin.
  - A material whose Transparent BSDF is constant black counts as opaque in EEVEE and is drawn first. Keep that in
    mind when testing order.
  - Example: `ec002_00v0` (DanteJDC mod). Record 27 is a dark purple translucent sphere (subtracts a yellow-green
    tint, alpha 0.2), and 9 / 10 a darkening ring under an identical glow ring. Record 28 has ParticleOptionFlag 0x10
    REFRACT (a revolving refracted ring).
  - **Refraction particles** (ParticleOptionFlag 0x10, unless CullingFlag 0x2 OCCLUSION is set; `sim.refracts`).
    Until 2026-10-08 the check used 0x200 of the old u16 CullingFlag, i.e. a VolumeBlendRate bit, and 324 of the
    1,304 refraction particles were previewed without refraction.
    In the game (`initGeneratorParam` 0x96B612 -> prim attr 1 -> `sPrim::setPrimitiveTechnique` 0xA35746 ->
    XfPrim `PRIM_EX_REFRACT`, PS 45), the pixel is the screen at `pixel + (BaseMap.rg - 0.5) x Intensity / 100`
    (screen-UV units, +v down) times the particle colour, with alpha = BaseMap.a x particle alpha, through the normal
    blend nibbles. Intensity doesn't tint them (`Particle.refract`, `_tint_mesh`). The batches go in sort layer 8 at
    half depth (`sPrim::drawTags` 0xA36F31). 1,304 of 34,703 DX9 particles refract, all with a BaseMap only.
  - `effect._build_refract_material`:
    - **Alpha-blended refraction with a texture** (928 of the 1,304): `mix(Transparent, Refraction(colour), alpha)`,
      the game's lerp with the refracted scene in place of the screen. The bend tilts the normal (Geometry Incoming,
      facing the camera) along the camera axes by `(rg - 0.5) x Intensity / 100 x REFRACT_GAIN` (2.0, IOR 1.5;
      calibrated from the deviation ~ tilt x (1 - 1/IOR) for a ~0.7 rad screen, not measured against the game). The
      texture is read raw (Gamma 1/2.2 undoes sRGB). The strength is the record's base Intensity (keys aren't
      followed; materials are keyed by it). Render method Dithered + Raytraced Transmission + Slab thickness, and
      import turns on scene EEVEE raytracing (without it EEVEE shows the world colour). Cycles bends properly
      (checker-sky render of `ec002_00v0` record 28). EEVEE (Material Preview too, per the user) refracts only
      weakly: a faint smeared band, not a grey blob.
    - **Other blend modes, or no texture:** a single blended Transparent BSDF with transmittance =
      colour x Fs (op) Fd (the source taken as background x colour). Measured exact against the formula minus the
      offset in EEVEE and Cycles; transmittance > 1 works for additive.
  - **Missing textures.** `texture.build_blender_textures` doesn't fail on a missing `.tex`: it returns a
    placeholder (`_missing_texture_image`, a black 4x4 image with alpha 1, marked `MISSING_TEXTURE_PROP`). Used as an
    effect texture, that turned every particle into a solid black shape. The user hit this in Material Preview with a
    mod-pack folder holding only the `.efl` as the Game Files root (the textures are in the base game's folders).
    `_EffectBuilder.image_for` now treats the placeholder as missing (the particle colour alone is used, and it isn't
    tagged `efl_texture` for reuse), records the paths in `root['efl_missing_textures']`, and the Effect Editor shows
    a warning box. On 2026-10-07 the black was first blamed on draw order and on a negative-emission material, which
    was reverted for that reason. Negative emission is still a poor fit: Cycles sums every layer before clamping,
    unlike the game's per-draw clamp, and EEVEE clamps negative light to 0.
  - **Cycles orders transparent layers by depth**, unlike the game's draw order. In `com\ec000_03v2`, darkening
    discs in front of the glow make a dark hole in Cycles with any version of these materials. EEVEE shows the glow
    on top.

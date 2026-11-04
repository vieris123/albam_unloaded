# Roadmap

Open work for the DMC4 fork, mostly the EFL (effects) side. Items are grouped by kind and roughly ordered by value
inside each group. Addresses are in the DMC4 DX9 executable; reverse-engineering details are in
`Vibed/RE/efl_import_plan.md`, and the current state of each feature is in `CLAUDE.md`.

Last updated: 2026-10-11.

## Housekeeping

- [ ] **Decide whether to save the DX9 IDB.** A stray script may have blanked the comment on the first instruction of
  `initGeneratorParam` (0x96AEC0). Saving keeps the `isGeneratorVisible` (0x53D460) rename but may lose that comment;
  not saving keeps the comment and loses the rename.

## Check in the game

The preview follows the DX9 code for these, but they haven't been compared with the game itself.

- [ ] **`com\ec002_00v0` (DanteJDC mod) re-imported with the armature.** Most of its generators use RelationType 2
  (follow the joint's position, keep a world rotation) and its quads use camera facing; both are new. Is it still
  askew?
- [ ] **`ec002_00v0` record 28, the refracting ring.** It is a PrimModel with ModelBillboardType 1. By the game's
  math its axis (Y) points screen-up, so it may look nearly edge-on while it spins. If the game shows it face-on, the
  PrimModel billboard path (renderPrimModel*) needs another look.
- [ ] **Camera-facing particles on a bone.** The billboard basis multiplies the whole particle matrix, generator
  rotation included (renderPolygon 0x99F8AD), so camera-facing quads on a tilted generator tilt with it. Confirm the
  game does this.
- [ ] **Preview additions of 2026-10-10:** compare a sword trail (`com\ec000_01v0` record 3), a rim-faded PrimModel
  (`com\ec024_60v0`), a row gradient (`com\ec001_01v2`), a held glow with End Effect set, and a model particle
  (`ene\ee005_52v0` record 23, fading) with the game.

- [ ] **Exported collision (`.sbc`).** The writer was rewritten on 2026-10-10 (`engines/mtfw/sbc_bvh.py`). Patch
  an edited stage collision (e.g. `st001-a-00`) and a single-group prop (e.g. `ko904-a00`) into the game: walk on
  floors, run into walls, check footstep sounds (ground material) and any scripted parts (group IDs).

- [ ] **Edited placements and schedulers (`.pla` / `.sdl`, 2026-10-10).** Move an enemy in an `emset*.pla`, change a
  fade in a `game_cmn\Fade\*.sdl`, Patch them in and check the game reads them (the files round-trip byte-identical,
  but no edited one has been loaded yet).

- [ ] **Model chains (2026-10-10).** Patch an edited chain (e.g. Nero's coat `pl000_03_00.phs` with another mSpring /
  mGravity) and compare the coat with Albam's motion preview (Nero + coat LMTs, coat attached at body joint 2): swing,
  how far it clips the legs when dashing (the preview clips mid-segment like the decompiled solver predicts). Then
  a new chain / new `.col` (New Chain from Selected Bones, New Collision Shapes) loaded by the user's own loader.
- [ ] **A moving floor (2026-10-10).** Edit or add a `uStageSetMoveFloor` piece (e.g. st405's blades: `blade01.sdl` +
  `st405-a-02.sbc`, part ID 0), Patch it in, check the floor moves, carries the player and collides; then a new
  platform following the recipe in `CLAUDE.md` ("Moving collision").

## Flags still to dig up

The SE PDB names these, but their DX9 meaning hasn't been checked. Two SE names have already proved wrong for DX9
(ParticleOptionFlag 0x10 is refraction, not ALPHA_BLUR; ModelAnimFlag 0x10 is UV scroll, not REVERSE_RAND), so verify
in the DX9 code before trusting one.

- [ ] **LiteBillboard / SizeBillboard layouts** (particle types 16 / 17): the DX9 code has readers
  (`initParticleLiteBillboard` 0x9DCB70, `initParticleSizeBillboard` 0x97F4E0, which reads keyframe offsets at
  0x1D8 / 0x1DC), but no file uses them and only their 0x170-byte common part is known. Change Type doesn't offer
  them until their tails are mapped.
- [ ] **MassBillboard / LensFlare trailing data**: 61 MassBillboard blocks carry 64 non-zero bytes after the struct
  and 2 LensFlare blocks 656, reached by no known offset (LensFlare is probably its element table). Read
  `initParticleMassBillboard` 0x97D860 / `initParticleLensFlare` 0x97D2A0.

## LMT

- [x] **Bone 0's location off by its rest position on game-model rigs.** Done 2026-10-14: a bone without a parent
  is relative to the game's model space (`rest_in_parent`, `GAME_FRAME`) on import and export; the single-key
  location y / z swap is gone. Breaking for actions imported or keyed before (see CLAUDE.md). Clean pl006 and the
  user's joint-255-parented retarget rig now pose identically, feet on the floor.
- [x] **Tracks for joints the armature lacks, and usage 5 tracks, are kept.** Done 2026-10-14: import stores them
  on the action (`_lmt_kept_tracks`) and export writes them back byte-identical unless curves now animate that
  joint and channel. Usage 5 (68 constant joint-255 tracks in the m20_100s cutscene LMTs) is never read by DX9
  (`uModel::setupMotionParam` binds usages 0-4 only).
- [ ] **Kept tracks don't follow re-timing:** an animation exported at another frame rate writes them unconverted
  (a note says so). Converting the durations of type 6 / 9 data would fix it.
- [ ] **Scene frame rate:** import forces the scene to 60 fps, so other animations in the scene play at the wrong
  speed. Proposed: leave it alone when the scene already has other animation, and say so in a note.

## Preview gaps

The game behaviour is known; Blender only approximates it. The other preview gaps were closed on 2026-10-10 (see
`CLAUDE.md`, EFL "Preview additions 2026-10-10").

- [ ] **Measured once at import** (they are right while the generator keeps the orientation it had then): the world
  down used for gravity, the world axes of world-fixed rope / cloth pulls, the ground plane for collision, and the
  joint frame of skinned spawn strips (RangeStripFlag 0x40, `ee022_02v0` only). The game re-reads them every frame;
  doing that would need the simulation to take the generator's motion as an input.
- [ ] **Root-attached RelationType 2 generators** turn with the armature object in Blender; the game keeps their
  rotation in world axes. Only matters if the armature object itself is rotated (root motion rotates a bone, which
  is fine). A fix would put the rotation companions under a world-axes Empty instead of the effect root and change
  how export reads them.
- [ ] **Small leftovers:** `ScaleMatRelationType` isn't used (World Scale takes the generator's whole world scale);
  World Scale uses the mean scale for Model / PrimModel too (the game scales them per axis); a billboard mode 2-4
  particle that also has Scale After Rotation keeps the rotation instead of the mirror; RangeDisperseType and
  sword-trail history need recorded emitter motion (playing the timeline, or Record Emitter Motion).
- [ ] **Renderer-dependent, only roughly possible in Blender:** soft edges (`ParticleOptionFlag` 0x4), the volume
  shader (`VolumeBlendRate`, 26,626 particles), lighting (`LightGroupFlag`, Model particles are unlit effect materials
  now), fog, the game's draw order (including `EntryType`'s draw passes: Screen draws last, Overlap with ordinary
  transparent objects).

## Larger features

- [ ] **Model chains: check per-bone limits in the game.** No shipped chain enables mBoneAdjust; Albam writes and
  previews it from the decompiled code (grid 2 clamps cleanly, grids 0 / 1 don't measure back inside their limits as
  decoded). First real use: Ellen's chest (`chains\boobs.clt` in both ellen mods, 2026-11-03: grid 2, X max at the
  rest + 0.5 deg, the bones re-framed to the clamp's no-roll rebuild, mDir +Y). Compare in the game; a half-turn flip
  on a clamp would mean the rebuild differs from the decode.
- [ ] **Model chains: Dante's coat attachment.** The preview's Attach to Body uses body joint 2, which is what
  `uPlayerNero::initModel` does for Nero's coat; Dante's (pl006_03, `uPlayerDante::setupDanteModel`?) wasn't traced.
- [ ] **Move definition files: Albam's share (phase C, started 2026-10-29).** One XML per player move, run by
  dmc4_hook's `MoveDef` mod (v1 2026-10-24: row, input command, runtime motion bank, stage with stick-direction slots,
  synthesised `.ctn` cancels, ballistics, effects by frame, hand-offs, overlays on vanilla moves; phase B adds the
  overlays' synthesised scripts on vanilla motions). Design, schema, decisions: `E:\DMC mod stuffs\Vibed\MoveDef\README.md`.
  - [x] **Authoring panel** (2026-10-29, `engines/mtfw/movedef/` + `movedef_blender.py`, guide `docs/movedef.md`): moves
    from LMT animations (new move: id, LMT, row, stage; overlay on a vanilla motion), the file as an element tree with
    a widget and tooltip per attribute (`movedef/schema.py` = the runner's "Implemented" subset), frames as pose
    markers, Import / Write XML keeping hand-written files byte for byte apart from the edits, the checks (ids, banks,
    blocks exist and have keys, frames inside the motion, names, limits, `.atk` entries). Tests: `test_movedef`,
    `corpus/movedef_check`.
  - [x] **Motion registry form (D26, 2026-10-29):** New Move writes `<lmt path>` without `bank=` (dmc4_hook's registry
    places it) and `<stage block="N">` for the move's own blocks; the checks know both forms (the bank clash only for a
    fixed `bank=`; `block=` needs an `<lmt path>`, excludes `motion=`, 0-255; `motion=` in a runtime bank, 10-14 and Nero's
    4 / 6-9, is refused unless it's the file's own fixed bank (overlays exempt), a bank over 15 always, as the runner does).
    Grab overlays: `motion="15:N"`, Cancels from .ctn reads the chosen enemy's `.ctn` bank 10-29. Per-enemy grab
    overlays would need a runner attribute (not asked for yet). Runner side built 2026-11-04, not checked in the game yet.
  - [x] **Extract a vanilla motion's cancels** from `.ctn` (`movedef/extract.py`, Cancels from .ctn): all 941 scripts of
    pl000 / pl006 extract and check clean; the 12 looping ones are flagged (the runner can't override them).
  - [x] **`.atk` codec** upstream (`dmc4xml/atk.py`, `tests/test_atk.py`: 61 DX9 files byte-identical; the 6 SE ones,
    version 8 with 0x6C-byte entries, are refused), vendored; the checks read `<shell entry=>` names from it.
  - [ ] Save to Game Folder of the move's xml + LMT (+ `.atk`) in one go (Write XML and Export LMT are separate now).
  - [x] **`<attack>`** (the user's decision D25, 2026-10-29: attack data defined in the XML or taken from an `.atk`):
    attacks under `<move>` (an entry with overrides, or values over Nero's RED-ComboA_00), `<shell attack=>` as a
    dropdown of the file's attacks, `entry=` by index or name with the picked entry shown; checks for both.
  - [ ] Writing new entries into `.atk` files (phase D, hits on the game's own `.idx` / LMT-event path; not needed by
    `<attack>`).
  - [ ] Effects picked from Game Files / the scene's effects; joints by name (the runner reads self / weapon only).
  - [ ] Check an authored move in the game (Write XML + Reload in the runner's panel). Nothing tested in-game yet.

- [ ] **ModelExtension lists: Albam's share (started 2026-11-03).** `nativePC\model_ext\*.xml`, run by dmc4_hook's
  ModelExtension, which owns the format.
  - [x] **Lists in Blender** (`engines/mtfw/movedef/ext_list.py`, `engines/mtfw/model_ext.py`): `EXT_<file>` objects in
    the Export list, byte-for-byte text, Object Properties panel, checks (including a collision model that isn't out
    when its chain spawns), Fill from Scene, attachment preview (skin, rigid). Tests: `test_model_ext`,
    `corpus/ext_list_check`. On Ellen's file Fill gives all 14 installed entries; her 4 lists round-trip.
  - [x] **Constraints** (`<pin>`, `<aim>`, `<offset>`, spec `Vibed\ModelExt\schema.md`): panel entries, a joint picker,
    checks, preview with named constraints and offset Empties, each matrix tested against the schema's table.
  - [x] **Links** (`<link a b max stiffness>`, 2026-11-04, runner `sdk/ChainLink`, built 2026-11-04): panel entry, checks (a
    joint no listed chain holds, two tendril roots, a == b), run by the chain preview after the chains
    (`cns_chain_preview.apply_links`: 4 passes, root rule, turn about the tendril parent, re-aim, velocity drop).
    Test: `test_chain_link`. First use: 2B's left-thigh seam (rows 224-219 ... 221-216). Not checked in the game yet.
  - [x] **Link Ellen's dress the same way** (2026-11-04, both ellen mods and blends): the front columns (13, 14, 0, 1, 2)
    moved into `dress_00` (Blend 1.0, radius 7.5, gravity kept at 0.03, Parent 1 on every dress chain), the four front
    seams linked row by row (the seams over the thighs + 0.5 cm, the others + 2 cm) and the bottom two rows of the
    seams where the front meets the sides (2|3, 12|13, + 1 cm); 20 links. In the preview, cloth behind / inside a thigh
    went from 78 / 53 (stride) and 70 / 80 (leg raise) to 0 everywhere; the front of the flare sags 4.6 cm standing
    (1.4 before). Not checked in the game.
  - [ ] **Check the preview against the game.** The formulas come from the runner and the schema. dmc4_hook's constraints
    and retrying lookups were written 2026-11-03 and built 2026-11-04; no rigid attachment or constraint has been compared in-game.
  - [ ] **Fractional twist / the mean of two joints** (forearms, skirt roots): needs a new runner element. No game class
    does it, and `wrist_deform` (202 / 206) has no roll to borrow, only up to 7 deg of the wrist's bend. Not needed for
    Ellen (measured 2026-11-03): her wrist rolls up to 107 deg, but her cuffs hide it and only 4-5 of ~1,600 forearm
    edges squash. Wait for a model with bare forearms.
  - [x] **In-game test list** (big head, neck aim, sword pinned above the head): worked in the game, removed 2026-11-03.
  - [ ] **True size in the game** ("ellen (org size)" mod, `Ellen true size.blend`, 2026-11-03): a new root joint 73
    scaled 0.72 by `<offset>` and joint 0 by 1 / 0.72, with the rig, meshes, shapes and chain settings scaled 0.72. The
    preview keeps her feet on the floor and the chain metrics identical; not tried in the game. Root motion stays
    Nero's, so expect foot sliding. Automated 2026-11-03: Match Game Skeleton > Match Size off > Animations at Own Size
    (`skeleton_match.keep_own_size`, test in `test_match_skeleton`). Shrinking an existing game-size setup is still a
    script.
  - [ ] **2B on Dante** ("2B (Albam)" mod, `2B_DMC4.blend`, 2026-11-03): own size 0.831; hair, whole dress and tattered
    dress as their own models with chains and collision on their own copies of the body's joints. The tattered dress is
    on the Devil Trigger body, `model\game\pl006\pl009` = a copy of her body .mod, with the size offsets too.
    Preview-checked on Dante's walk / run; nothing tried in the game. The DT toggle crash was the game's setModel race
    with joint 0 at index 1 (fixed in dmc4_hook, built 2026-11-04; the toggle not retried yet).
    Her 928 NieR motions are retargeted onto the matched rig as `2B_<motion>` actions (muted NLA tracks): per-bone constant
    corrections from Match's plan, the rip's object root motion baked into the hips, keys only on the original key
    frames; checked against the original deformation (median under 0.4 mm). The original rig is kept as
    `2BRip_Original` (not exported). Not made into LMTs yet (frame rate and root motion split still to decide).

- [ ] **Hitboxes (saved for later, 2026-10-10).** Four file types keyed to a model's joints, already mined in IDA
  (per the user) and described by 010 templates in `E:\DMC mod stuffs\DMC4 templates`:
  - `.col` = `rCollisionShape` (shapes): codec done (`dmc4xml/col.py`, byte-exact on 110 DX9 files); Blender import,
    export and new files done (2026-10-10, `col_shapes.py`: sphere / capsule objects on the joints, edited with
    move / scale / Shift+D / X / re-parent, groups' kind and flags in the panel; untouched files export
    byte-identical). Check an edited / new `.col` in the game. Hitbox files also use joint -1, placed in the model's own space (a guess: check it
    against the game). Which groups are on comes from the LMT's first event table (bit k = group
    events_params_01[k]); the preview shows / hides groups with it. Groups carry
    kind (cCollisionGroup.mKind) and flags (1 attack, 2 hurt, 4 push, 8 grab, 0x20 friendly attack); shapes are
    spheres (type 0) / capsules (type 3) on joint IDs of the collision model, radius, pos0 / pos1 in the bones'
    frames. `DMC4_col.bt`.
  - `.atk` (186 files, `ATK\0`, u16, u16 count): **codec done 2026-10-29** (`dmc4xml/atk.py`: the 61 unique DX9 files
    byte-identical, SE version 8 refused). `kAttackStatus` per entry (`DMC4_atk.bt`): mAsName[16], mAttackID (the
    template's 4 unknown bytes), mDamageValue, mAttackLv, mAttackLvI / B, mRangeType, mHitStopTimer, mDamageType / I / B (launch etc.),
    mHitMarkAngle, mHitSE, mStylishPoint, mStylishTimer, mDTAdd, mAttackFlag, mBlownAngleType, mElementType.
  - `.dfd` (32 files, `DFD\0`, u16, u16 count): `kDefendStatus` (`DMC4_dfd.bt`): mAsName[16], mResist[3],
    mMaxInterrupt[5], mMaxBlown[5].
  - `.rCollisionIdxData` (13 files): a tab-separated text table (first line = row count), probably linking shape
    groups to attack / defend entries; not decoded yet.
  - Plan: codecs for dfd / idx in dmc4xml (byte-exact on the corpus; atk done), then Albam: the attack / defend entries
    editable alongside the `.col` groups.
- [x] **Bones added in Blender export to the `.mod`.** Done 2026-10-16 (`joints.py`, see CLAUDE.md): new bones get
  joint numbers and go after the model's own; renamed / reordered bones are fine. Check in the game: a model with a
  new bone weighted to some vertices, animated by an LMT track and driving a chain. Still refused: deleting a model's
  own bones (needs remapping every LMT / chain / .col / effect that refers to them).
- [x] **Match Game Skeleton.** Done 2026-11-02 (`skeleton_match.py`, `docs/new_model.md`): a rig from elsewhere takes a
  game model's parents and rest frames, is posed (T-pose, shape keys too) and scaled to it, so its LMTs play as on the
  game's model. Check in the game: a matched model replacing `pl006`, shoulders and wrists first. Twist bones stay in the
  mesh without a track (MMD's Transform constraints are muted), so forearm twist collapses as it does on any
  skinned model without them; a rig could feed them from the hand's rotation at export if it shows.
- [x] **Convert existing models.** Done 2026-11-01 (`new_model.update_model`, `texture_convert.py`, `lib/dxt.py`): New
  DMC4 Model reads Base Color / Alpha / Normal / Specular / Roughness (packed channels too), encodes DDS itself (DXT1,
  DXT5, DXT5nm, mips, the game's revisions) and splits multi-material meshes and meshes over 32 bones; export converts what's added later and names what
  it can't take.
  Green direction of normal maps follows the shader notes: not checked in the game yet.
- [x] **Bones named after their joints.** Done 2026-10-31 (`joints.PLAYER_JOINTS`, `name_bones`): player-type
  skeletons import as `thumb_1_r`, `thigh_l` ... (checked on pl000 / pl006); Name Bones by Joint for older rigs;
  the Effect Editor's ParentNo shows the joint's name; a new bone's Game Joint panel says what its number is in the
  player skeleton and has a search picker of the player joints by name (`albam.pick_joint_number`, 2026-11-01), and
  Not a Game Joint can be set on all selected bones (`albam.set_not_joint`). The 2xx helper joints are named by where they sit
  (`elbow_deform_r` ...), not by a verified role; enemies have no name table.
- [x] **Editable `.mod` model settings beyond the light group.** Done 2026-10-17: LOD distances and per-mesh LOD
  toggles (Model Settings panel); strip type is 0 in every file and stays as the source has it.
- [x] **New `.mod` from scratch.** Done 2026-10-28 (`new_model.py`, `mesh_prep.py`; user guide `docs/new_model.md`):
  New DMC4 Model on an armature / Empty / mesh, export from a generated blank source, bones numbered from 0, part
  records generated, meshes triangulated / seam-split / moved into the root's frame on temporary copies at export.
  Open:
  - [ ] **Check in the game:** a static prop and a small skinned model (bones from scratch, an LMT on them) load
    and draw; the generated part record keeps meshes drawn at every distance.
  - [x] **Images to DDS.** Done 2026-11-01 (`texture_convert.py`, `lib/dxt.py`, see Convert existing models): any
    Blender image in a shader slot is encoded as DXT1 / DXT5 with full mips, and re-encoded when its pixels change.
  - [x] **Normal maps.** Done 2026-11-01: a regular normal map is swizzled to DXT5nm (X in alpha, Y in green) and
    connected. The green direction isn't checked in the game yet.
  - [ ] **Modifiers.** Export reads the mesh data and ignores every modifier but the vertex groups (a Mirror or
    Subdivision has to be applied first). Evaluating the mesh without its Armature modifier in `mesh_prep` would fix
    it.
  - [ ] **Part records of edited game models.** Export now adds a record for a part number without one: that
    changes the output of the 90 DX9 models whose meshes already lack one (they drew by a stale stack byte before).
    Harmless by the code, not checked in the game.
- [x] **Particle keyframes as F-curves.** Done 2026-10-11 (`effect_keys.py`): tracks are custom properties on the
  record Empty with F-curves ("… Rand" / "… B" for the random part), generator keys are transform keys, loop is a
  Cycles modifier, interpolation follows the keys; the timer and init-only stay in the Keys tab. Keyframe decorators
  on the field rows. Every imported file still exports byte-identical. Not covered: keys of a track whose random
  part should differ per key but isn't keyed (set a static Rand or key it), and a one-frame rounding when the scene
  fps isn't a divisor of 60.
- [x] **Timeline integration for effects.** Done 2026-10-11: start and end markers per effect (drag the start marker
  to move the effect, keys included), the simulated length follows the scene's End frame.
- [ ] **Faster first pass for ribbon-heavy effects.** Done 2026-10-13: per-frame cache (replay / scrubbing), a
  scalar rope step, cached gradient factors, cheaper cache signature: `ec024_60v2` first pass 34 -> 26 ms per frame,
  replay 25 -> 8 ms, load simulation 1.2 -> 0.5 s. Ribbon strips moved to a Geometry Nodes group the same day
  (`ALBAM_EFL_Ribbons_v1`): Python only writes the points, and orbiting with Face Viewport no longer recomputes
  ribbons; the per-frame total stayed about the same (Blender's evaluation of the node groups costs what Python
  saved). What's left of a first pass is particle state evaluation in `sim.state_at` (about half) spread over many
  small per-particle steps: no single hotspot remains, so further gains need a different approach (evaluating a
  record's particles in bulk with numpy, or caching line points per particle across frames).
- [ ] **Keyframe UX leftovers.** A record's custom-property tracks share the Empty's action with its transform keys,
  so the Dope Sheet shows them under the object; a channel group per track is set. Possible next steps: an
  "Animate" entry in the field's right-click menu (needs the editor's items to be real RNA paths), showing the Rand
  property next to its track in the Keys tab, and a per-track key list for people who prefer numbers.

- [x] **SDL / PLA: add new property tracks from Blender.** Done 2026-10-10 through Edit as XML / Apply XML
  (`xml_edit.py`): new units, property tracks and classes are typed in dmc4_xml's XML. A form-style "Add Property"
  operator (the types the files use per class) could still make it friendlier.
- [ ] **Edit as XML for `.phs` chains (and other XFS files).** The vendored `dmc4xml.xfsxml` converts XFS both ways;
  `xml_edit.py` only handles `.sdl` / `.pla` so far.
- [ ] **Sound effects (not scoped yet, for a later session).** LMT event table 2 plays sounds: slot bit k ->
  `events_params_02[k]`, the same scheme as the hitbox groups of table 1. Per the user, the sound effect data follows
  the XFS format (dmc4xml's XFS codec reads it), so the work starts there. What a player's `sound\se\player\pl000\`
  holds (uPlayerNero.arc): rMotionSe (`pl000.0CA6AED4`, native `.msse`, XFS v5; one per motion bank: pl000, pl020,
  pl000_majin, wp024; most likely the slot value -> sound table), rSndIf (`.rSndIf` / `.sif`, XFS), rAttributeSe
  (`.ase`, XFS), rSoundEngine / rSoundEngineValue (`.eng` / `.engv`, XFS), and the binary banks: rSoundRequest
  (`.sreq`, magic SREQ v15), rSoundBank (`.spac`, magic SPAC v4; not in the class table, arc type 0x15D782FB),
  rSoundRandom (`.dnrs`, magic DNRS).
- [ ] **XFS files (`.cam` rDevilCamera and the rest) in Albam.** The XFS codec is byte-exact on all 297 DX9 XFS files
  and vendored (`dmc4xml/xfs.py`, `xfsxml.py`; the layout table's attr / getter / setter fields and the header version
  are kept since 2026-10-10); `.phs` chains already use it. Still missing: a Blender import for the other classes,
  in the order of "Resource classes" below, starting with `.cam` (a camera-area import was prototyped, scratch only).

## Resource classes: native support by priority (2026-10-10)

Which of the game's resource classes (`Note\DMC4Extensions.txt`, `DMC4_RESOURCE_CLASSES`) need Blender support
beyond plain XML editing. Ranked by: spatial data (in a level or on a skeleton, painful as numbers), corpus size
(unique files under `arctool`, SE and mod copies included), and whether XML editing is possible at all (only XFS
classes and `.sdl` / `.pla`; binary formats need a codec first). Already native: `.mod`, `.tex`, `.lmt`, `.efl` /
`.efs` / `.ean`, `.sbc`, `.sdl`, `.pla`, `.phs` / `.clt`, `.col` (import).

1. [ ] **Hitboxes:** `.atk` (145; codec done, no Blender editing yet), `.dfd` (23), `.idx` (23); `.col` (114) import /
   export / new is done.
   Binary, so not even XML-editable yet; shapes on joints, switched by LMT events. See "Hitboxes" above.
2. [ ] **Camera areas, `.cam` rDevilCamera** (17, XFS): cCameraNormal mCameraPos / mTargetPos / mCameraUp / mFov /
   Fog, area boxes (`mppBox`), area links (cCamAreaConnect). Cameras, boxes and link lines in Blender.
3. [ ] **Level trigger volumes:** `.evh` rEventHit (18, XFS: cEventHitData Shape, Pos0-3, PosY, Height, facing
   condition, player / camera placement on trigger, cEventPosData) and `.seg` rSoundSeg (17, XFS: SEG_HIT_DATA, the
   same shapes plus radius, SE / stream to play). One volume builder for both.
4. [ ] **AI routes, `.rut` rRouteNode** (53, XFS): nodeData minpos / maxpos boxes, attribute, nodeLink linkId / fCost.
   Boxes and editable link edges.
5. [ ] **Room defaults, `.rdf` rRoomDefault** (17, XFS): a spawn marker (mPlPos / mPlAngY, mCmrAngY); the rest (force
   vector, light / particle scales, shadow switches) is fine as XML.
6. [ ] **Sound:** rMotionSe (31, XFS: per entry mSeReqID, mSeJointID, attach and attribute flags; the LMT table-2 ->
   sound link, so it belongs next to the LMT events) and the binary banks `.sreq` (126) / `.spac` (66) / `.dnrs` (59),
   which need codecs. See "Sound effects" above.
7. [ ] **Codec only, no Blender view:** `.msg` rMessage (237, MSG2 binary: game text; an editing job, XML / JSON is
   enough) and `.mot`: no game file is an rMotion (no entry of type 0x1A773D0C in 3,422 .arc files; the native format is "MOT\0" v48, 32-byte tracks, loader 0xADF830). The 85 `.mot` under `arctool` are an LMT splitter's output (`pl006_01\`: one block per `_NNN` = block NNN-1, with `.motptr` / `.motindex` / `.atk` / `.atkindex` and a `.lmtheader`), so they're covered by LMT support.

**Plain XML is enough** (XFS, values only), once Edit as XML handles XFS (item above): `.sprmap` rSprLayout (33, UI
layout; a 2D preview would be a luxury), `.sif`, `.ase`, `.eng` / `.engv`, `.ssd`, `.equ`, `.rev_win`.

**Not in the extracted folders yet:** `.nav`, `.lcm`, `.lge`, `.cdf`, `.nls`, `.shp` / `.shw`, `.fca`, `.esd` / `.esl`.
If stage or demo archives with them get extracted, `.nav` (navigation mesh) and `.lge` (grid lighting) would rank
high: both are spatial.

Suggested order: finish 1, then Edit as XML for XFS (unlocks every plain-XML class), then 2 and 3.

## Inherited bugs (from upstream Albam)

Recorded under "Known bugs and gotchas" in `CLAUDE.md`, not fixed yet: re5 texture slots,
the SBC21 (other games) export bugs in `collision.py`, `world_pos_fix` being a no-op, stale state after hot-reload,
and others. (Slotted actions on Blender 4.4+ / 5 are handled since 2026-10-14, `lib/blender_compat.py`.)

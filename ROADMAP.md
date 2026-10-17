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
  decoded). Patch a chain with a limited bone and compare.
- [ ] **Model chains: Dante's coat attachment.** The preview's Attach to Body uses body joint 2, which is what
  `uPlayerNero::initModel` does for Nero's coat; Dante's (pl006_03, `uPlayerDante::setupDanteModel`?) wasn't traced.
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
  - `.atk` (186 files, `ATK\0`, u16, u16 count): `kAttackStatus` per entry (`DMC4_atk.bt`): mAsName[16], 4 unknown
    bytes, mDamageValue, mAttackLv, mAttackLvI / B, mRangeType, mHitStopTimer, mDamageType / I / B (launch etc.),
    mHitMarkAngle, mHitSE, mStylishPoint, mStylishTimer, mDTAdd, mAttackFlag, mBlownAngleType, mElementType.
  - `.dfd` (32 files, `DFD\0`, u16, u16 count): `kDefendStatus` (`DMC4_dfd.bt`): mAsName[16], mResist[3],
    mMaxInterrupt[5], mMaxBlown[5].
  - `.rCollisionIdxData` (13 files): a tab-separated text table (first line = row count), probably linking shape
    groups to attack / defend entries; not decoded yet.
  - Plan: codecs for atk / dfd / idx in dmc4xml (byte-exact on the corpus), then Albam: the attack / defend entries
    editable alongside the `.col` groups.
- [x] **Bones added in Blender export to the `.mod`.** Done 2026-10-16 (`joints.py`, see CLAUDE.md): new bones get
  joint numbers and go after the model's own; renamed / reordered bones are fine. Check in the game: a model with a
  new bone weighted to some vertices, animated by an LMT track and driving a chain. Still refused: deleting a model's
  own bones (needs remapping every LMT / chain / .col / effect that refers to them).
- [x] **Editable `.mod` model settings beyond the light group.** Done 2026-10-17: LOD distances and per-mesh LOD
  toggles (Model Settings panel); strip type is 0 in every file and stays as the source has it.
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

1. [ ] **Hitboxes:** `.atk` (145), `.dfd` (23), `.idx` (23); `.col` (114) import / export / new is done.
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

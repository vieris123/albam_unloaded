# Roadmap

Open work for the DMC4 fork, mostly the EFL (effects) side. Items are grouped by kind and roughly ordered by value
inside each group. Addresses are in the DMC4 DX9 executable; reverse-engineering details are in
`Vibed/RE/efl_import_plan.md`, and the current state of each feature is in `CLAUDE.md`.

Last updated: 2026-10-10.

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

- [ ] **Exported collision (`.sbc`).** The writer was rewritten on 2026-10-10 (`engines/mtfw/sbc_bvh.py`). Patch
  an edited stage collision (e.g. `st001-a-00`) and a single-group prop (e.g. `ko904-a00`) into the game: walk on
  floors, run into walls, check footstep sounds (ground material) and any scripted parts (group IDs).

- [ ] **Edited placements and schedulers (`.pla` / `.sdl`, 2026-10-10).** Move an enemy in an `emset*.pla`, change a
  fade in a `game_cmn\Fade\*.sdl`, Patch them in and check the game reads them (the files round-trip byte-identical,
  but no edited one has been loaded yet).

- [ ] **Model chains (2026-10-10).** Patch an edited chain (e.g. Nero's coat `pl000_03_00.phs` with another mSpring /
  mGravity) and compare the coat with Albam's motion preview (Nero + coat LMTs, coat attached at body joint 2): swing,
  how far it clips the legs when dashing (the preview clips mid-segment like the decompiled solver predicts).
- [ ] **A moving floor (2026-10-10).** Edit or add a `uStageSetMoveFloor` piece (e.g. st405's blades: `blade01.sdl` +
  `st405-a-02.sbc`, part ID 0), Patch it in, check the floor moves, carries the player and collides; then a new
  platform following the recipe in `CLAUDE.md` ("Moving collision").

## Flags still to dig up

The SE PDB names these, but their DX9 meaning hasn't been checked. Two SE names have already proved wrong for DX9
(ParticleOptionFlag 0x10 is refraction, not ALPHA_BLUR; ModelAnimFlag 0x10 is UV scroll, not REVERSE_RAND), so verify
in the DX9 code before trusting one.

- [ ] **`MoveOptionFlag` 0x1** (SE `MOVE_OPTION_FLAG_COLLISION`): 199 records.
- [ ] **Generator `RangeStripFlag`** (SE `STRIP_FLAG`: 0x1 ORDER on 128 records, 0x40 SKINING on 17, 0x20 ALL_PARTS
  on 1) and **`RangeOptionFlags` 0x1** (SE EACH_FRAME, 121 records).
- [ ] **`ChainOptionFlag`** (SE: 0x1 NO_MAT_DIR, 0x2 NO_MAT_BDIR, 0x20 MUL_MAT_BDIR). The preview treats 0x1 / 0x2 as
  world-fixed pulls.
- [ ] **Collision `CollFlag`.** In moveParticlePosCollision (0x99A210) bit 0 returns move result 4 (FIN_ANIM_STOP),
  bit 1 returns 8 (SE FIN_ROT_STOP?) and bit 2 returns 2, which releases a life hold (FIN_KEEP_HOLD_OFF, confirmed
  2026-10-10). What results 4 and 8 do hasn't been traced; SE also names PATH_CANCEL, SPHERE_CORRECT, ROT_ATTENUATE.
- [ ] **Generator `AxisFlags` `Order` / `AxisType`** (unverified).
- [ ] **`ParticleOptionFlag` 0x20000** (SE EXT_LINE_POS, 1,807 particles): only the line renderers read it
  (renderPolyline / Texline / Line); what it changes is unknown.
- [ ] **`PassBits`** (PrimMaterialFlags bits 12-15): which views set the matching mode bits 8-11, and the per-particle
  call it triggers at spawn (effect vtable slot 42 in initParticleBillboard).
- [ ] **`LightGroupFlag` matching rule.** It's the same light-group mask models use (`uModel` +0x130, from the `.mod`
  header 0x88), but the code that compares a light's group with a model's hasn't been found. The tooltips say
  "most likely when they share a bit".
- [ ] **Culling `OcclusionRadius`**: SE-named, DX9 use not traced.

## Preview gaps

The game behaviour is known; Blender doesn't show it yet.

- [ ] **PrimModel colour gradient** (`ColorPlaceType` / `ColorPlaceInpType` in PrimFlags, `calc_color_gradient`
  0x9B52A0). Lines and trails already use it.
- [ ] **PrimModel rim fade** (`NormAttenuateFlag`, NormAttenuateAngle*): fade where the surface is edge-on to the
  camera; value 3 makes it one-sided.
- [ ] **World Scale** (`ParticleOptionFlag` 0x200 WMAT_SCALE): particle size follows the generator's scale
  (updateWorldMatrix 0x96E835).
- [ ] **Life hold releases other than the end of the range.** Held particles (`HoldUntilEffectEnds`, 1,506) stay
  until the end of the simulated range or `HoldFrameLimit`; a path move's end with PathOptionFlag 4 (34 of them) and
  collisions with CollFlag 4 also release them in the game. An "effect ends at frame" preview option would let the
  user see the fade-out where the owning move ends.
- [ ] **PolygonStrip (sword trail) direction alignment**: the trail goes through the same matrix code as Polygon
  (sub_988B00), but trails are built separately in the preview.
- [ ] **Face the viewport.** Camera facing and the culling fade use the scene camera and update on frame changes
  only, so orbiting the viewport doesn't turn the billboards. An optional mode could follow the viewport (costs
  performance).
- [ ] **Approximations to tighten:**
  - Scale-after-rotation (0x40000) scales along the points object's axes: right for particles that follow the
    generator, approximate for particles that stay where they were emitted.
  - Root-attached RelationType 2 generators turn with the armature object in Blender; the game ignores the owner's
    rotation for them (only matters if the armature object itself is rotated).
  - Model particles have no per-particle alpha, so they can't fade (culling fade, life fade).
  - Billboard modes 2-4 are a reflection in the game; the preview uses the matching rotation (same look on a flat
    quad, texture may be mirrored).
- [ ] **Renderer-dependent, only roughly possible in Blender:** soft edges (`ParticleOptionFlag` 0x4), the volume
  shader (`VolumeBlendRate`, 26,626 particles), lighting (`LightGroupFlag`), fog, the game's draw order.

## Larger features

- [ ] **Model chains: Dante's coat attachment.** The preview's Attach to Body uses body joint 2, which is what
  `uPlayerNero::initModel` does for Nero's coat; Dante's (pl006_03, `uPlayerDante::setupDanteModel`?) wasn't traced.
- [ ] **Hitboxes (saved for later, 2026-10-10).** Four file types keyed to a model's joints, already mined in IDA
  (per the user) and described by 010 templates in `E:\DMC mod stuffs\DMC4 templates`:
  - `.col` = `rCollisionShape` (shapes): codec done (`dmc4xml/col.py`, byte-exact on 110 DX9 files); Blender import
    done (2026-10-10, `col_shapes.py`: sphere / capsule objects on the joints, coloured by group flags), export of
    edited shapes still to do. Hitbox files also use joint -1, placed in the model's own space (a guess: check it
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
  - Plan: codecs for atk / dfd / idx in dmc4xml (byte-exact on the corpus), then Albam: `.col` export from the shape
    objects, groups with kind / flags editable, and the attack / defend entries alongside.
- [ ] **Editable `.mod` model settings beyond the light group** (`model_info`: middist, lowdist, strip type).

- [x] **SDL / PLA: add new property tracks from Blender.** Done 2026-10-10 through Edit as XML / Apply XML
  (`xml_edit.py`): new units, property tracks and classes are typed in dmc4_xml's XML. A form-style "Add Property"
  operator (the types the files use per class) could still make it friendlier.
- [ ] **Edit as XML for `.phs` chains (and other XFS files).** The vendored `dmc4xml.xfsxml` converts XFS both ways;
  `xml_edit.py` only handles `.sdl` / `.pla` so far.
- [ ] **Sound effects (not scoped yet, for a later session).** LMT event table 2 plays sounds: slot bit k ->
  `events_params_02[k]`, the same scheme as the hitbox groups of table 1. Per the user, the sound effect data follows
  the XFS format (dmc4xml's XFS codec reads it), so the work starts there.
- [ ] **XFS files (`.cam` rDevilCamera and the rest) in Albam.** The XFS codec is byte-exact on all 297 DX9 XFS files
  and vendored (`dmc4xml/xfs.py`, `xfsxml.py`; the layout table's attr / getter / setter fields and the header version
  are kept since 2026-10-10); `.phs` chains already use it. Still missing: a Blender import for the other classes,
  starting with `.cam` (a camera-area import was prototyped, scratch only).

## Inherited bugs (from upstream Albam)

Recorded under "Known bugs and gotchas" in `CLAUDE.md`, not fixed yet: texture slots don't round-trip,
the SBC21 (other games) export bugs in `collision.py`, the detail-map driver path, `world_pos_fix` being a no-op, stale state after hot-reload,
LMT code that will break with Blender 4.4+ slotted actions, and others.

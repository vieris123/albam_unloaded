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

## Flags still to dig up

The SE PDB names these, but their DX9 meaning hasn't been checked. Two SE names have already proved wrong for DX9
(ParticleOptionFlag 0x10 is refraction, not ALPHA_BLUR; ModelAnimFlag 0x10 is UV scroll, not REVERSE_RAND), so verify
in the DX9 code before trusting one.

- [ ] **`MoveOptionFlag` 0x1** (SE `MOVE_OPTION_FLAG_COLLISION`): 199 records.
- [ ] **Generator `RangeStripFlag`** (SE `STRIP_FLAG`: 0x1 ORDER on 128 records, 0x40 SKINING on 17, 0x20 ALL_PARTS
  on 1) and **`RangeOptionFlags` 0x1** (SE EACH_FRAME, 121 records).
- [ ] **`ChainOptionFlag`** (SE: 0x1 NO_MAT_DIR, 0x2 NO_MAT_BDIR, 0x20 MUL_MAT_BDIR). The preview treats 0x1 / 0x2 as
  world-fixed pulls.
- [ ] **Collision `CollFlag`.** Only bit 0 (FIN_ANIM_STOP) is named. SE adds FIN_ROT_STOP, FIN_KEEP_HOLD_OFF,
  PATH_CANCEL, SPHERE_CORRECT and ROT_ATTENUATE.
- [ ] **Life `KeepFlags`** (still an unverified guess: hold bit plus a frame count in bits 16-23) and **generator
  `AxisFlags` `Order` / `AxisType`** (also unverified).
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

- [ ] **Chains (`rCnsChain`, soft-body links).** Researched (see "Chains" in `CLAUDE.md`), not supported.
- [ ] **Editable `.mod` model settings beyond the light group** (`model_info`: middist, lowdist, strip type).

## Inherited bugs (from upstream Albam)

Recorded under "Known bugs and gotchas" in `CLAUDE.md`, not fixed yet: texture slots don't round-trip,
the SBC21 (other games) export bugs in `collision.py`, the detail-map driver path, `world_pos_fix` being a no-op, stale state after hot-reload,
LMT code that will break with Blender 4.4+ slotted actions, and others.

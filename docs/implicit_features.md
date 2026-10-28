# What Albam does without a button

Much of Albam works through ordinary Blender actions: moving, duplicating (Shift+D), deleting (X), parenting, bone
collections, timeline markers, the Graph Editor. Nothing on screen says so. This page lists those behaviours, by
area. Each entry says what you do, and what Albam does in response.

Panels mentioned here are in the Properties editor (Object / Bone tabs) unless another editor is named.

## Models and bones (`.mod`)

- **Add bones in Edit Mode, and they export.** New bones go into the `.mod` after the model's own. Each gets a joint
  number the first time something needs one: .mod or LMT export, New Chain, assigning it to a chain's bone
  collection, Add Sphere / Capsule, parenting an effect to it.
- **Shift+D a bone** and the copy gets its own joint number. The bone whose name has no `.001` suffix keeps the
  original's.
- **Bone Properties > Game Joint** shows and sets a bone's **Joint Number** (what LMT tracks, chains, .col shapes and
  effects refer to), its **Mirror Bone** (empty = automatic: the bone at the mirrored position across X = 0), and
  **Not a Game Joint** (a helper bone that isn't exported). Bones named `root_motion`, `IKP_…` or `IK_Foot…` are
  always helpers.
- **Rename or reorder bones freely.** Export matches the model's bones by joint number, not name or order. Deleting
  one of the model's own bones is refused, because animations, chains, .col and effects refer to it.
- **Move a mesh object** (relative to its model's root) and it exports where you see it. Quads, n-gons, UV seams,
  sharp edges and flat shading are handled at export too, on a temporary copy; your mesh isn't changed. Modifiers
  other than the Armature modifier are not applied: apply them first.
- **Select a mesh of a model** and Model Settings (Object Properties > Albam Asset) still shows its model's settings,
  plus that mesh's **Draw At** Near / Mid / Far toggles.
- **Materials show what the game does** with their DMC4 functions: unlit (LIGHTING_NONE) draws its base colour
  flat, THIN gets a translucent layer, LIGHTMAP_SHADOW masks the specular, POWMAP drops the environment reflection.
  A texture can feed other nodes as well as the shader group; export still finds it.
- **New DMC4 Model** has its own guide: [new_model.md](new_model.md).

## Model chains (`.phs`)

- **The chain *is* its bone collection.** Each chain has a bone collection on its armature, named `Chain <file>`
  (Armature Properties > Bone Collections). Edit the chain by editing that collection:
  - **Assign a bone to it** (Pose Mode: select the bone, pick the collection in Armature Properties > Bone
    Collections, click Assign) and the bone joins the chain. If its parent is the tip of a tendril, the tendril grows by that bone. Otherwise (a branch, or
    a bone whose parent isn't in the chain) it starts a new tendril at the end.
  - **Remove a bone from it** (same place, Remove) and its slot goes. A tendril left empty goes too.
  - Bones that stay keep their slots and tendrils.
  - The Chain panel (Object Properties on the `PHS_` Empty) lists the tendrils, and the bone count it sees.
  - **A new bone gets its joint number by itself** as soon as it's in a chain's collection (the highest free
    number, as for any bone added in Blender). If you assign it while still in Edit Mode, it gets the number when
    you leave Edit Mode. Exporting the chain or turning its preview on does the same.
- **Bone Properties > Chain Bone** (on a chain bone, Pose Mode):
  - **Tendril Root** on: the chain is cut before this bone, so it starts a new tendril and keeps its animated
    position. Off: it merges into the tendril before it.
  - **Limits:** the per-bone angle limits the game supports (no game chain uses them).
- **Shift+D the `PHS_` Empty** to make a new chain with the same settings. The copy gets the next free file name,
  its own `Chain <file>` collection with the same bones, an Export list row, and its preview off. The original
  exports unchanged.
- **Imports connect themselves.** Import the `.mod`s, `.phs` and `.col` in any order:
  - A chain finds its model by name (`pl000_03_00.phs` → `pl000_03.mod`).
  - It finds its collision from the `.col` named like the chain without the `_NN` (`pl000_03.col`).
  - A coat (pl000_03, pl006_03) is attached to body joint 2, as the game does.
  - What's still missing is listed in the Chain panel.
  - **Attach to Armature** moves a chain or a `COL_` object to another armature.
- **Preview Motion** (Chain panel) runs the game's chain solver while the animation plays. Playing forward steps
  the simulation. A frame already played shows its stored result. Jumping to any other frame restarts the
  simulation there, as the game does on a reset. **Simulate Range** fills the whole scene range at once. Nothing is
  keyed or exported.
- **Delete the `PHS_` Empty** (X) and its bones go back to their pose without the preview. Its bone collection and
  its Export row are removed.

## Collision shapes (`.col`: hitboxes, push and chain collision)

- **Edit shapes as objects.**
  - Move or scale a sphere Empty: size × scale is the radius.
  - Shift+D copies a shape; on a capsule, select both ends.
  - X deletes it.
  - **Ctrl+P > Bone** moves it to another joint.
  - Its group is set in the Collision Shapes panel.
- **Capsules look after themselves.** The tube between two ends is rebuilt when either end moves. Both ends keep
  the same size: the one you resized last wins. A copied pair becomes a new capsule. A tube whose ends are gone is
  removed.
- **Colours** show the group's kind: attack red, grab yellow, hurt blue, push green.
- **Groups follow the animation.** With **Follow Animation Events** on (Collision Shapes panel), only the groups
  the playing LMT animation switches on are shown, frame by frame. Bit k of the first event table turns on group
  `Hitbox Slot Values[k]` of that animation. It's on by default for hitbox files and off for a chain model's body
  shapes. Without events, every group shows.
- **Delete the `COL_` Empty** and its shapes go with it.

## Animations (`.lmt`, Dope Sheet > Action Editor > Albam)

- **Clicking an animation in the LMT list puts it on the armature:**
  - the action it replaces gets a fake user if this would delete it;
  - the pose resets to rest first (LMTs don't key every channel);
  - bones switch to the rotation mode the action's curves use.
  Picking an action in Blender's own Action editor does the same.
- **Events are pose markers** named `ev1_<frame>_<id>` (hitbox table) and `ev2_<frame>_<id>` (sound table). Drag
  them in the timeline to move the event: each event is tied to its marker by name, not by position.
- **Export adapts the action without changing it:**
  - It's shifted so its first key (or event) is game frame 0.
  - It's rescaled from the animation's Frame Rate to 60 fps.
  - Euler and axis-angle rotations are converted.
  - F-Curve groups don't matter, so FBX imports and Bake Action output export as they are.
  - What it adjusted is reported.
- **Tracks the armature can't show are kept.** Joints the rig doesn't have (an LMT shared with the character's
  other models) and track kinds the game ignores are stored on the action and exported back as they were, unless
  you animate that joint.
- **A `root_motion` bone** is created for joint 255 (the character's movement). The hips follow it.
- **Foot IK Preview** (LMT panel) plants the feet the way the game does wherever the animation's foot IK event
  flags are on. Preview only: export is unaffected.

## Effects (`.efl`, the Effect Editor)

**Selecting and editing**
- **Click a record's Empty** in the viewport and the Effect Editor loads it. Clicking particles works too: a rebuild
  keeps the same objects selected and active.
- **Select several record Empties** and every field edit goes to all of them (to records whose block has the same
  field; the panel says how many). The copy buttons next to fields and sections send a value without editing it.
- **The records list works like the Outliner:** click = select only that one, Shift = add, Ctrl = toggle.
- **Edits show at once** (Live, on by default), including keys changed in the Graph Editor or Dope Sheet. Turn Live
  off to apply by hand (Apply). Transform and pose changes still need Apply.
- **Changing a field the layout depends on** (LineType, ClothType, a FIX line's point count) rebuilds the block for
  the new layout, as Change Type does, keeping the shared fields and keys.

**Duplicating, moving between effects, deleting**
- **Shift+D or Ctrl+C / Ctrl+V a record Empty** = a new record in the same effect. **Parent the copy to another
  effect's root** = the record is copied into that effect (attached to the same joint if that armature has it).
- **X a record Empty** = the record is removed from the file.
- **Copies of linked strips / flipbooks and of rotation helpers** are cut loose: they become plain objects.

**Transforms**
- **Move, rotate, scale or re-parent a generator Empty** (to a bone, or off it) = its position, rotation, scale and
  joint in the file. Keyed channels are the generator's keyframes instead.
- **`<record>_rot` Empties** belong to generators that keep a world rotation while following a joint
  (RelationType 2). Rotate the `_rot` Empty, not the generator.
- **`<record>:<Field>` Empties** are the record's vector keyframe tracks (particle / move rotation, path offset,
  spawn range, model scale...). Their location, rotation or scale keys are the track's keys. The record list and
  Show Curves select them, so the Graph Editor shows their curves.

**Timeline**
- **The marker `<effect> start`** is the effect's frame 0. Drag it to move the whole effect: its keys move along.
- **The marker `<effect> end`** is End Effect: the moment the owner stops the effect, when held particles are
  released. Drag it, or set it at the top of the Effect Editor.
- **Change the scene frame rate** and every effect's keys are rescaled, so they keep their game timing. Import sets
  the scene to 60 fps.
- **Generator-timer keys are offset by the record's WaitFrame**, as the game starts that timer only when the
  generator fires. Change WaitFrame and the keys move with it.

**Textures and materials**
- **Swap the image in an effect material's Image Texture node** (for another game texture loaded in Blender) and
  the records drawn with that material get the new texture path.
- **Darkening Strength** (Effect Editor) changes how strongly darkening blends draw, live, for every effect.

**Preview options**
- **Face Viewport** (Effect Editor): camera-facing particles face the viewport you're working in instead of the
  scene camera.
- **Spawn Filter** (Effect Editor): the group / surface masks the game spawns the effect with. Records that wouldn't
  spawn are hidden but stay editable and exported.

## Strips (`.efs`) and flipbooks (`.ean`)

- **Edit a strip mesh in Edit Mode** and the effect applies it when you leave Edit Mode. Points you didn't move keep
  their exact values, so an untouched strip exports identical.
- **Convert a strip to a curve** (Object > Convert > Curve) and it still exports, as Blender draws it.
- **Extrude or Shift+D a chain of a strip** = a new part after its source.
- **Flipbooks are UV maps.** In Edit Mode, the UV editor shows each frame over the texture; moving UVs moves the
  frame's rectangle. Shift+D a frame face = a new frame after it. The Flipbook panel is in the Image Editor's
  **Albam** tab.
- **Ctrl+J a UV-mapped mesh into a flipbook**: its faces become new frames, taking their rectangles from the
  mesh's own UVs.
- **Linked flipbooks start hidden** (their frame grid would cover the effect). The Effect Editor's Linked files
  button shows and selects one. Its hidden state survives rebuilds.

## Scheduler (`.sdl`) and placement (`.pla`)

- **Move or turn a placement Empty** = its `mPos` / `mRotY` (or `mAngle`) in the file. Untouched Empties export
  unchanged.
- **Scheduler units with keyed `mPos` / `mAngle` move with their keys** while the timeline plays (drivers). The
  keys are custom properties keyed in the Graph Editor; moving the Empty by hand doesn't change them.
- **Parent a collision root to a scheduler unit** to preview a moving floor (`uStageSetMoveFloor`). The collision
  still exports in its own space.
- **Duplicate a container Empty** (with its children) = its tracks are copied right after the original. Delete it =
  its tracks are dropped.
- **Edit as XML** (Object Properties > Scheduler / Placement XML) covers what the objects can't (new units, new
  tracks). Objects you had parented to the Empties and constraints on them survive Apply XML.

## Stage collision (`.sbc`)

- **Collision exports relative to its root Empty**, so a moving piece can be built in its own local space.
- **The faces' normals decide the walkable side.** The game's collision is one-sided: normals must point out of the
  walkable side. A mirrored object (negative scale) is handled at export.
- **New meshes default to static** (part ID -1). Object Properties > Collision Part sets a moving piece's ID.
- **Export splits, triangulates and applies for you:** modifiers and transforms are applied, n-gons triangulated,
  zero-area triangles skipped, meshes over 65,536 vertices split. Each change is reported.

## Files, exporting and the Export list

- **Delete an object** (X) and its row leaves the Export list:
  - a chain also restores its bones and removes its bone collection;
  - a `COL_` root removes its shapes.
- **The Export list knows every DMC4 file type** under any name the extraction tools give it (class names, hashes,
  native extensions). An exported file replaces the archive entry at the same path.
- **Save to Game Folder** (folder button next to Save) writes every file of the selected export, including an
  effect's edited strips and flipbooks, at its game path under the loose-file folder. The folder is remembered in
  the add-on preferences, so new .blend files start with it.
- **The Game Files root must be the arc root** (the folder holding `model\`, `effect\`...). Textures, linked files
  and templates are looked up by their game path under it. If several roots hold the same path, the first wins.
- **Missing textures** become placeholders (an effect shows a warning; a model keeps the reference and writes no
  file for it). Add the folder that has them as another Game Files root.

# Shape keys in DMC4

DMC4 (DX9) has a morph-target system that no game file uses. Albam exports a model's shape keys into it, and
dmc4_hook's ModelExtension and MoveDef play them. Status 2026-11-08: works in the game. In the test, Nero's body
breathed on list 0 and puffed up on Streak's finish through a MoveDef `<shape>` (results in
`Vibed\RE\shape_morph.md`).

## What you do

1. **Add shape keys** to the model's meshes as usual (Object Data Properties > Shape Keys).
2. **Set or animate them:**
   - A key **set above 0** is a fixed change (a body shape).
   - A key **animated** (keyframe its Value) is played by a clip. A clip is an action on the mesh's shape keys: the
     one assigned now, and every one in its NLA (Shape Key Editor > Stash or Push Down).
   - A key **left at 0 and not animated** does nothing and isn't exported. An imported model's unused expressions
     don't change the export.
   - A **muted** key isn't exported.
3. **Export the model.** Next to `<model>.mod`, at the same game path, the export writes:
   - `<model>.shp`: the keys' vertex offsets;
   - `<model>.shw`: the keys' set values (a key some clip animates is 0 here);
   - `<model>_<clip>.shw`: one per clip, named after the action (`pl000_01_smile.shw`).

   Save to Game Folder delivers them all.
4. **Put the shapes on the model** with a ModelExtension list: Object Properties > Model Extension List > **Fill from
   Scene** adds `<shape shp="<model>" shw="...">`. Its `shw` is list 0, which plays from the start: the clip assigned
   now (an idle loop), else the set values. Without a `<shape>` entry nothing moves in the game, and the list panel
   warns about it.
5. **Play clips from moves:** a MoveDef stage's `<shape frame= shw="<model>_<clip>" list="1"/>` starts one,
   `<shape_stop>` stops it. A face clip goes on the face model (`on="face"`, `pl000_01` for Nero), so its keys must be
   on the face model's meshes.

## Rules the game sets

- **Meshes:** a mesh with keys needs a 4-weight skinned material (VTYPE_SKIN, SKIN_4WT). Export refuses the mesh and
  says why if its material is 8-weight or static, or has lighting / normal map / specular settings with no shape
  shader (lighting 1, specular 2, normal maps 2-3, most lightmaps). Fix the material, or mute the keys.
- **Materials:** export switches the material to SKIN_4WT_SHAPE by itself. A material that also draws meshes without
  keys is written twice.
- **Normals don't morph:** the shading stays the basis shape's.
- **Parts:** a part (the mesh's Group ID) blends at most 15 keys with a weight above 0 at once. Export prints a
  warning when a part has more.
- **Clips and key names:** a clip drives every key of the names it animates, on every mesh of the model. A body split
  into several meshes, each with its own Key of the same names, follows one clip.
- **Lists are averaged:** when several lists play (list 0 and a clip from a move), each key's weight is the average of
  their curves, weighted by `rate`. A clip playing beside list 0 therefore shares each weight with it. Keys a list
  doesn't animate hold their set value there, so a body shape stays as it is.
- **One-shot clips** (`loop="false"` on a move's `<shape>`): the runner stops the list when the clip ends, so it
  drops out of the average and its keys go back to the other lists' values. With `hold="true"` it keeps its last
  frame until a `<shape_stop>` or another `<shape>` on that list. List 0 (the ModelExtension entry's) is never stopped.
- **Timing:** clips run at 60 game frames per second from their first key (or the action's manual frame range), at
  the scene's frame rate. They are sampled on every game frame and written as straight-line keys.

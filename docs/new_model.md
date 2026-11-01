# Making a new DMC4 model

Albam can export a `.mod` you built in Blender, with no game model to start from: a static prop, or a skinned model
with its own rig. (Before 2026-10-28 a model could only be exported if it had been imported.)

## Quick start

1. Build the model as usual, or open one you already have:
   - **Static prop:** one or more meshes. Parent them to an Empty, or just select them.
   - **Skinned model:** an armature, with meshes weighted to its bones (vertex groups named after the bones) and an
     Armature modifier on them, or parented to it.
2. Select the armature, the Empty or a mesh, and click **New DMC4 Model**, in **Object Properties > DMC4 Model** or in
   the sidebar's Albam **Export** panel. Type the game path, e.g. `model\game\mymodel\mymodel.mod`.
3. Read the panel's list of what was done and what needs fixing (red lines), fix those, then export from the
   **Export** list like any imported model (Export, then Save / Save to Game Folder).

Materials and textures are converted for you: ordinary Blender materials with PNG, TGA or JPG images are fine.

## What New DMC4 Model does

- **The root.** The armature or Empty becomes the model. An Empty holding one armature (how model importers often
  leave things) uses that armature, so the model is skinned. A lone mesh gets a new Empty named after the file. Meshes
  that belong to the model but aren't under it yet are parented to it, staying where they are: the selected meshes
  (unless another armature deforms them), and for an armature every mesh its Armature modifier deforms.
- **Several materials on one mesh:** the mesh is split into one object per material, keeping its weights and
  modifiers (the game's mesh records have one material each).
- **Bones** without a joint number get 0, 1, 2... in the armature's order (parents first), so the root bone is
  joint 0, as in the game's models. Bones that already have a number (a rig taken from a game model) keep it, so
  their animations still fit. Numbers are shown, and can be changed, in Bone Properties > Game Joint. The search
  button next to the number lists the player skeleton's joints by name (14 thigh_r, 100 thumb_1_r ...): give your
  bones those numbers and the rig can play Nero's / Dante's animations.
- **Materials** without the DMC4 shader get it, read from what the material shows (a Principled BSDF, or another
  shader's colour input). See Materials and textures below. The settings match the mesh:
  - static (no armature): no skinning;
  - skinned with up to 4 bone weights per vertex: 4-weight skinning;
  - more than 4: 8-weight skinning.
  Lighting is the game's usual one. Every combination used exists in the game's shader. Materials already set up for
  DMC4 (e.g. copied from an imported model) are left alone. The old shader nodes are removed (Undo brings them back).
- **Images** become DDS and get a game path next to the model (`model\game\mymodel\<image name>_BM.tex`). Change it
  in the Image Editor's Albam tab if you want it elsewhere.
- The model is added to the **Export** list. Its settings (light group, level of detail) are in Object Properties >
  Albam Asset > Model Settings, with the game's usual values.

Nothing is changed if New DMC4 Model refuses (no meshes, an object that is already part of an imported file, a
game path already used in this .blend). Undo (Ctrl+Z) reverts it.

## What export takes care of

You can model the normal way: export makes a temporary copy of each mesh that needs it, and never changes yours.
- **Position:** a mesh moved, rotated or scaled relative to the model root is exported where you see it.
- **Quads and n-gons** are triangulated.
- **UV seams and hard edges:** the game stores one UV and one normal per vertex, so vertices are split where faces
  meet with different UVs, along sharp edges and around flat-shaded faces. Smooth and flat shading come out as
  Blender shows them.

**Not handled yet:** modifiers (Mirror, Subdivision...) are ignored: apply them before exporting. The Armature
modifier and the vertex groups are what skinning uses, so keep those.

## Materials and textures

| In your material | In the game |
|---|---|
| Base Color image | base map: DXT1, or DXT5 if the alpha is used |
| Alpha (the base image's or another image; or a Mix Shader with a Transparent BSDF) | alpha test for cut-outs (hair, lace), blending if the image is mostly half transparent; opaque if it has no real transparency |
| Base Color with no image | a small flat colour texture |
| Normal Map node with an image | normal map, in the game's layout (X in alpha, Y in green) |
| Specular image | mask map (specular colour) |
| Roughness image | mask map, as 1 - roughness (multiplied with a Specular image if there's both). Channels of packed images are followed through a Separate Color node |
| Roughness value | the specular highlight's sharpness |

Not used (the panel says so): Bump nodes (the game takes normal maps), Metallic and Emission maps. A material with no
Specular or Roughness image has no specular at all.

- **DirectX normal maps:** Blender's Normal Map node expects green pointing up. Maps made for DirectX, as most games'
  are, have it down: turn on **DirectX Normal Maps** in the New DMC4 Model dialog for those.
- **Sizes:** textures go to the nearest power of two (up to 4096), with full mipmaps. A 2048 texture takes a few
  seconds; the console shows each one.
- **Your images stay:** the conversion makes a packed `.dds` image and leaves the source in the file. The viewport then
  shows the compressed result, as the game will.
- **Keeping things up to date:** export converts what changed by itself: a PNG put in a shader slot, a material
  added to the model, or a source image you repainted. **Update Materials & Textures** in the DMC4 Model panel does
  the same at any time, to see the result first.
- Existing `.dds` images are used as they are.

## Limits and notes

- One material per mesh. New DMC4 Model splits meshes; one you add to the model later needs Separate > By Material.
- Up to 32 bones influence one mesh, 254 bones per model, 8 weights per vertex. A rig with more bones is refused:
  mark its helper bones with Bone Properties > Game Joint > **Mark Selected** first (that panel shows on any armature).
- The model's part number (`Group ID` in the mesh's DMC4 properties, 0 by default) decides the level-of-detail part a
  mesh belongs to; export writes a part record for each one used, centred on its meshes. Leave it at 0 unless you
  need parts switched separately.
- Not yet checked in the game (2026-10-28): the exported files follow everything known about the format, but a new
  model hasn't been loaded in DMC4 yet. If something doesn't show up, the Model Settings and these notes are the
  first places to look.

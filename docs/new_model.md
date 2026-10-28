# Making a new DMC4 model

Albam can export a `.mod` you built in Blender, with no game model to start from: a static prop, or a skinned model
with its own rig. (Before 2026-10-28 a model could only be exported if it had been imported.)

## Quick start

1. Pick **DMC4** as the app in the Albam panel.
2. Build the model as usual:
   - **Static prop:** one or more meshes. Parent them to an Empty, or just select them.
   - **Skinned model:** an armature, with meshes weighted to its bones (vertex groups named after the bones) and an
     Armature modifier on them, or parented to it.
3. Give each mesh one material. The material's **Base Color** image (an Image Texture node into the Principled BSDF)
   becomes the model's texture. It must be a **DDS** image (see Textures below).
4. Select the armature, the Empty or a mesh, and in **Object Properties > DMC4 Model** click **New DMC4 Model**. Type
   the game path, e.g. `model\game\mymodel\mymodel.mod`.
5. Read the panel's list of what was done and what needs fixing (red lines), fix those, then export from the
   **Export** list like any imported model (Export, then Save / Save to Game Folder).

## What New DMC4 Model does

- **The root.** The armature or Empty becomes the model. A lone mesh gets a new Empty named after the file. Meshes
  that belong to the model but aren't under it yet are parented to it, staying where they are: the selected meshes,
  and for an armature every mesh its Armature modifier deforms.
- **Bones** without a joint number get 0, 1, 2... in the armature's order (parents first), so the root bone is
  joint 0, as in the game's models. Bones that already have a number (a rig taken from a game model) keep it, so
  their animations still fit. Numbers are shown, and can be changed, in Bone Properties > Game Joint.
- **Materials** without the DMC4 shader get it: the Base Color image is wired to *Diffuse BM*; if the Principled
  Alpha was used, the material becomes alpha-tested. The DMC4 material settings are chosen to match the mesh:
  - static (no armature): no skinning;
  - skinned with up to 4 bone weights per vertex: 4-weight skinning;
  - more than 4: 8-weight skinning.
  Lighting is the game's usual one; there is no normal map or specular map. Every combination used exists in the
  game's shader. Materials already set up for DMC4 (e.g. copied from an imported model) are left alone.
- **Images** get a game path next to the model (`model\game\mymodel\<image name>.tex`). Change it in the Image
  Editor's Albam tab if you want it elsewhere.
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

## Textures

- **Export needs DDS images.** Albam can't convert PNG / TGA yet. Save the texture as `.dds` with an image tool
  (e.g. DXT1 for opaque, DXT5 for alpha), then open that file in the Image Texture node. A non-DDS image is listed in
  red in the panel and export refuses it.
- **Normal maps** aren't connected automatically: DMC4 reads them in the DXT5nm layout (X in the alpha channel,
  Y in green), which ordinary normal maps aren't. Convert one to that layout, then connect it to the shader group's
  *Normal NM* input, and set the material's normal map function in its DMC4 properties.

## Limits and notes

- One material per mesh (separate by material: Edit Mode > Mesh > Separate > By Material).
- Up to 32 bones influence one mesh, 255 bones per model, 8 weights per vertex.
- The model's part number (`Group ID` in the mesh's DMC4 properties, 0 by default) decides the level-of-detail part a
  mesh belongs to; export writes a part record for each one used, centred on its meshes. Leave it at 0 unless you
  need parts switched separately.
- Not yet checked in the game (2026-10-28): the exported files follow everything known about the format, but a new
  model hasn't been loaded in DMC4 yet. If something doesn't show up, the Model Settings and these notes are the
  first places to look.

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
- **Meshes the game can't take in one piece are split**, keeping their weights, modifiers and shading (normals along
  the cut stay as they were, so no seam shows): one object per material, and meshes weighted to more than 32 bones
  into parts of up to 32. **Update Materials & Textures** does the same later.
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
  in the Image Editor's Albam tab if you want it elsewhere. If you change the model's own path later, its textures move
  to the new folder at the next export, unless you set their path by hand. Export again after changing it: the
  `.mod` holds the textures' full paths.
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
  added to the model, or a source image you repainted. Export never splits your meshes: one added later with several
  materials or more than 32 bones is refused by name. **Update Materials & Textures** in the DMC4 Model panel
  (on imported models too) does all of it at any time.
- Existing `.dds` images are used as they are.

## Playing the game's animations

Right joint numbers aren't enough for a model to play Dante's or Nero's animations. An animation sets each joint's
rotation relative to its parent, in that joint's own orientation, and the root's position outright. So the rig has to
agree with the game's model on parents, bone orientation, rest pose and size. A rig from MMD or another game doesn't,
and the character comes out twisted.

**Match Game Skeleton** (Object Properties > DMC4 Model) does all of that:

1. Give the main bones their numbers first: root, spine, neck, head, shoulders, arms, hands, fingers, thighs, shins,
   feet (Bone Properties > Game Joint, the search button lists them by name). Number the real deforming bones, not MMD's
   control bones (`足D.R`, not `足.R`).
2. Press the button, pick the **Game Model** it replaces (it has to be in Game Files), read the list of what will happen,
   press OK. **Use the same character it exports as:** Dante's and Nero's joints differ, and the game looks up the
   joints of the model it loads. The dialog warns if they don't match.
3. Import an LMT to try it. **Import LMTs after matching**: ones imported before are out of date.

What it changes (Undo reverts all of it):

- **Parents and orientation:** every joint the game model has takes its parent and rest orientation. Bones look
  like the game's afterwards: short, and not pointing along the limbs. That's expected.
- **The pose and the mesh:** the mesh, with every shape key, is posed into the game model's stance (an A-pose goes to
  a T-pose, palms matched). Feet and toes keep their pitch, so heels stay heels.
- **Size:** the model is scaled so its hips stand as high as the game model's. Turn off **Match Size** to keep its size,
  but the animations still lift the hips to that height, so a smaller model's feet leave the floor.
- **Hips:** joint 13 goes to the bone the thighs hang from.
- **Missing joints:** joints the game model has and the rig lacks are added as small bones that deform nothing
  (`game_shoulder_deform_r`...). Leave them: the game reads some without checking they exist, and a missing one
  crashes it the moment the character appears. Dante's coat pins to 200 and 204, for instance. Weapons hang on 150, 151
  (hands) and 152 (back): without them they sit at the model's root. Export refuses a `pl006`, `pl009` or `pl000`
  model without any of those joints. `game_weapon_back` starts at the game model's offset from the spine; animations
  with a location track on it (most) set that offset themselves, so moving the bone won't move the sword there.
- **Other numbers:** outside the body and fingers, a bone that isn't where the game model has that joint loses the
  number (automatic numbers often land on the game's joints), and the bones outside the match get numbers
  the game model doesn't use, so its animations can't reach them.
- **Control bones:** unweighted bones outside the match (IK, `_dummy_`, `_shadow_`) become Not a Game Joint, except
  chain bones. Don't remove them unless you like: they just aren't exported.
- **Constraints** on the bones are muted, not removed: the game has none, and they'd fight the animations in Blender.

Running it again is safe: a rig already matched keeps its pose, and only its size and missing joints change. Other
armatures in the file (a separate dress or tail rig) aren't touched, so scale those to match yourself.

The mesh is posed with plain weighted skinning, as the game draws it, so check the shoulders and wrists after a big
change of pose: their weights may want painting. Twist bones stay in the mesh but no animation drives them, so they
follow their parent.

The character's other models load as usual. Replacing `pl006.mod` leaves Dante's face (`pl006_01`), hair
(`pl006_02`) and coat (`pl006_03`) on top of the new body; replace those too (an empty model works) to hide them.

## Cloth, tails and other extra parts

A part with its own physics works best as its own `.mod`, skinned to the body with ModelExtension (`<attach>` without
`joint=`), with its chains on that model. Copy the body joints it uses into its armature at the body's exact rest pose,
with the same numbers, and give its own bones numbers the body doesn't have: joints with the same number follow the body.

- **A file holds 32 slots** (bones plus one between tendrils): 3 tendrils of 5, or one side of a long ribbon.
- **Don't copy a coat's gravity.** Nero's is a sideways vector tuned to trail behind him, and it blows a skirt to one side.
- **Keep a flared skirt's shape with weak gravity and a low blend** (gravity 0.03, `mBlend` 0.4 on Ellen). Stronger gravity
  collapses the flare onto the legs, and collision then shoves it back out into a shelf.
- **Keep collision shapes inside the cloth at rest.** A capsule that pokes through makes the cloth drape over nothing.
  Start thigh capsules partway down the thigh, and remember the chain's `mCollisionSize` adds to their radius.
- **For walking, use pairs of capsules in front of and behind the thigh** rather than one fat one, upper and lower pairs
  tapering toward the knee. They catch the stride without pushing the skirt's sides outward, which makes the shelf.
- **One chain can collide with another part.** Put its `.col` on that part's joints, with capsules along the moving bones,
  and set `collision_model` to that part. A chain finds its collision model when it spawns and lists load in name order,
  so attach that part first: keep both in one list, in that order, or the chain silently gets no collision.
- **Gravity can have a direction.** With `mGravityLocal` on it's in the character's own frame, so `-Z` pulls backward
  whichever way she faces (game axes: Y up, +Z forward).
- **`mBlend` compounds along a chain.** A 19-joint tail needs about 0.2 or it behaves like a rope.
- **Judge it with textures on.** A grey render hides a panel sticking out.

### The list file

The game finds extra parts through a list in `nativePC\model_ext`. Albam can write it for you:

1. Select a model and click **New Extension List** in Object Properties > Model Extension List. With **Fill from Scene** on,
   it lists every chain in the scene, and every model that follows another through `ALBAM_FollowBody` constraints.
2. Check the entries in the same panel. Hover a setting's name to see what it does, and read any warnings at the top.
3. Pick the list in the **Export** list, then Export and Save to Game Folder.

To edit a list you already have, add its `nativePC` folder to Game Files and import the `.xml`. Anything you don't change,
comments included, stays exactly as it was.

**Preview Attachments** makes the list's attachments follow their owners in the viewport, as they do in the game. A chain's
bones stay free, because the game gives them to the chain. The constraints are never exported.

## Limits and notes

- One material and up to 32 weighted bones per mesh (split for you, see above; zero weights don't count).
- 254 bones per model, 8 weights per vertex. A rig with more bones is refused:
  mark its helper bones with Bone Properties > Game Joint > **Mark Selected** first (that panel shows on any armature).
- Game paths are English letters, digits, `_` and `-` only, because the `.mod`'s texture table is ASCII. Anything else
  is replaced: a model or image with a Japanese name gets `model\game\model\model.mod` or `texture_BM.tex`, and a
  model saved with an older path is corrected at its next export (the new path is in the console). Object, mesh,
  material and bone names can be anything: they don't go in the file.
- The model's part number (`Group ID` in the mesh's DMC4 properties, 0 by default) decides the level-of-detail part a
  mesh belongs to; export writes a part record for each one used, centred on its meshes. Leave it at 0 unless you
  need parts switched separately.
- Not yet checked in the game (2026-10-28): the exported files follow everything known about the format, but a new
  model hasn't been loaded in DMC4 yet. If something doesn't show up, the Model Settings and these notes are the
  first places to look.

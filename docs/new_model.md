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
- **Size:** the model is scaled so its hips stand as high as the game model's. Turn off **Match Size** to keep its own
  size. **Animations at Own Size**, on by default, then keeps its feet on the floor (it needs dmc4_hook):
  - **The new root:** a root bone `game_size_root` above joint 0, at the game's model frame, with a number no animation
    uses.
  - **The list:** two Offsets in the model's list (a new `model_ext\<model>_size.xml` if no list has it yet): the root
    scaled by the model's size against the game model's, joint 0 by the inverse. The game's hip motion shrinks to the
    model's height, while its bones keep their own size, so chains and collision built at that size stay right.
  - **The catch:** moves still carry it the game model's distances, so the feet slide a little, and jumps and dashes keep
    the game's height and length.
  - **Needs a recent dmc4_hook:** the new root moves joint 0 to the second slot of the joint table. The game only copes
    with that while a model swaps its file (Dante's Devil Trigger) with dmc4_hook built after 2026-11-03; older builds
    crash when Devil Trigger is toggled.
  - **Undoing it:** running it again keeps one root and two Offsets; Match Size on removes them and scales the model
    instead.
  - **An existing game-size setup:** a model already set up at the game's size, with parts, chains and collision (Ellen),
    has to be scaled down first: rigs, meshes, shapes and chain settings. That's a script for now (Ellen, 2026-11-03:
    `Ellen true size.blend`, the "ellen (org size)" mod).
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
- **Keep a flared skirt's shape with weak gravity and a low blend** (gravity 0.03, `mBlend` 0.4 on Ellen's sides and
  back). Stronger gravity collapses the flare onto the legs, and collision then shoves it back out into a shelf. The
  columns the legs push through are the exception: see the links below.
- **Keep collision shapes inside the cloth at rest.** A capsule that pokes through makes the cloth drape over nothing.
  Start thigh capsules partway down the thigh, and remember the chain's `mCollisionSize` adds to their radius.
- **For walking, use pairs of capsules in front of and behind the thigh** rather than one fat one, upper and lower pairs
  tapering toward the knee. They catch the stride without pushing the skirt's sides outward, which makes the shelf.
- **A leg between two bone columns opens a seam, and the chain settings can't close it.** Each column is simulated on
  its own, so collision shoves both sideways and the cloth between them stretches open (2B's left thigh, columns from
  joints 225 and 220, 2026-11-04). Tried and reverted:
  - **A third column in front of the leg, as a chain:** capsule collision has no friction, so the leg pushes it round
    its side and it ends up behind the thigh.
  - **The same column pinned to the thigh** (`<pin mode="rot">`): it looked better in the preview but not in the game.
  - **Limits on the columns' roots** (with the roots' rest set to the clamp's own rebuild, so nothing twists): the
    seam opened *wider* in the preview. The solver places every joint below a root from its own simulation, and a
    limit only clamps a bone's rotation, keeping its position (`Vibed/RE/chain_cnschain.md` 3.2 h and j). So limits
    only hold single-bone chains (Ellen's chest), not a column's lower joints.
  - What holds two columns together is a **Link** between their joints in the model's list (see The list file).
    Link only the seams the legs push through, the front: each linked seam makes the cloth less able to get out of the
    leg's way. On 2B a ladder round the whole skirt made a stiff tube the legs went through (cloth behind a thigh while
    running 282-394, against 10 with the front linked), and a single ring at the hem let the panels part above it
    (159-184): link every row of a front seam, and leave the back free. Then **raise the linked chains' collision radius**: the column meets the leg while the
    leg is still behind it, so the push is forward, and the links stop the columns spreading. 2B, 16 links across the
    front-left (the seam at the thigh at its rest distance + 0.5 cm, the others + 2 cm), radius 1.5 -> 7.5 and Blend with
    Animation 1.0 on those chains: in the preview, cloth inside the leg over a stride went from 7,156 / 9,520 (slow /
    fast) to 0 / 0, and on a 100 deg leg raise the cloth stopped tucking in behind the thigh (41 / 52 joint-frames -> 3 /
    8). A low blend pulls the cloth back toward its modelled place, which a raised thigh now occupies, so it folds in
    behind the leg; a big radius with a 0.7 blend pushed the skirt out at rest (21 cm). Check a leg raise as well as a
    stride.
  - **Turn Carried by Parent on for clothing** (Follow Position + Follow Rotation, Parent 1, as the game's coats). Off,
    the cloth stays in the world while she runs, so her legs come forward through it and it ends up behind them (2B:
    front-left cloth behind a thigh 63 joint-frames striding in place, 146 running; with carry on, 63 at any speed).
  - **At Blend 1.0, give the cloth real gravity.** Nothing else brings lifted cloth back down: real gravity is about
    0.27 cm per frame² at 60 fps, and 2B's dress had 0.03, so after a leg raise it stayed bunched (20 cm off its shape
    1.5 s later). 0.3 halved that, with the resting shape barely changed. The big radius and the links that stop the
    tuck also keep some folds in place after the leg drops: smaller radius or no links bunch less but tuck more.
  - **Only on the chains the legs push through.** The back of a skirt sits out over the butt because of its modelled
    shape: at Blend 1.0 with real gravity 2B's back hung straight down and her butt clipped through (back panels 3.8 cm
    in towards her body on average, 15 cm at worst). Keep the back at a low blend (0.4) with weak gravity, or give the
    butt collision shapes. These settings are per chain file, so sort the columns into files by where they hang:
    2B's back-left columns (135, 140) sat in the front-left file and clipped her hip until they moved to the back file
    (worst 14 -> 8 cm), while the column right beside the thigh (193) has to stay with the front ones or the leg goes
    through it again.
  - **Side seams at idle.** Where the linked front meets the free back, the seam opens when she stands with her legs
    apart, and the legs show through (2B: up to 5-6 cm with the thighs 15 deg out). Linking the bottom rows of a seam
    that sits clear of a thigh closes it (2B's right side, 169|174, two rows at + 1 cm: 4.9 -> 1.6 cm) for little cost
    to the legs. A seam right beside a thigh has to stay free: on 2B's left side (193|135) every link made the left leg
    tuck 3-6 times as often. With the right side linked, 2B's idle looked right (2026-11-04).
  - **Where a Blend 1.0 file meets a low-blend one, link that seam too.** The two settle differently and the seam
    between them opens (Ellen: 6 cm between her front and side columns with the legs apart). Linking its bottom two
    rows closed it and took the last tucks out: cloth behind / inside a thigh went from 78 / 53 striding and 70 / 80 on a
    leg raise (as she was) to 0 everywhere; all four rows was worse on a leg raise (11-13 inside).
  - **A flared skirt keeps its weak gravity.** Ellen's skirt stands out from her legs and doesn't bunch after a leg
    raise (1.8 cm off its shape 1 s later at gravity 0.03), so 2B's 0.3 only made the front sag more (5.6 cm against
    4.6). Blend 1.0 alone costs some of the flare's shape (4.6 cm against 1.4 at 0.4); Blend 0.7 let cloth into the
    thighs again on a leg raise.
- **Blend with Animation scales collision.** Collision pushes the simulation, and a low blend draws only that fraction
  of the push.
- **One chain can collide with another part.** Put its `.col` on that part's joints, with capsules along the moving bones,
  and set `collision_model` to that part. A dmc4_hook built before 2026-11-03 looks the model up once, when the chain
  spawns, so attach that part first (both in one list, in that order), or the chain silently gets no collision. Newer
  builds retry until the model is out, so the order doesn't matter there.
- **Gravity can have a direction.** With `mGravityLocal` on it's in the character's own frame, so `-Z` pulls backward
  whichever way she faces (game axes: Y up, +Z forward).
- **`mBlend` compounds along a chain.** A 19-joint tail needs about 0.2 or it behaves like a rope.
- **Judge it with textures on.** A grey render hides a panel sticking out.
- **To stop a bone swinging one way, use Limits** (Bone Properties > Chain Bone, Z axis). Set the blocked side at the bone's
  rest angle and leave the other side open. Three things decide whether a clamp works:
  - **The bone's rest pose:** when a clamp engages, the game rebuilds the bone's rotation from the two measured angles and
    drops any roll. A bone rolled against that rebuild flips half a turn on every clamp (Ellen's chest did). Give the bone
    the rest the rebuild produces, with the chain along +Y, and copy that rest to every model sharing the joint.
  - **Up Axis:** keep it positive (+X / +Y / +Z). The preview applies a negative one negated, which turns the bone half a
    turn.
  - **Pointing straight up or down:** the measured axis must not point that way, or swings past it read backward. With the
    chain on +Y, the measured Z is near horizontal.
  - Ellen's chest: `Ellen true size.blend`, 2026-11-03. Not checked in the game yet.

### The list file

The game finds extra parts through a list in `nativePC\model_ext`. Albam can write it for you:

1. Select a model and click **New Extension List** in Object Properties > Model Extension List. With **Fill from Scene** on,
   it lists every chain in the scene, and every model that follows another through `ALBAM_FollowBody` constraints.
2. Check the entries in the same panel. Hover a setting's name to see what it does, and read any warnings at the top.
3. Pick the list in the **Export** list, then Export and Save to Game Folder.

To edit a list you already have, add its `nativePC` folder to Game Files and import the `.xml`. Anything you don't change,
comments included, stays exactly as it was.

A **Model** entry can also hold joint constraints, added with the buttons on its row. The search button picks a joint by its
bone's name:

- **Pin:** a joint follows another joint, on any model. Blend mixes it with the joint's own animation.
- **Aim:** an axis of a joint points at another joint, for example a head looking at a target.
- **Offset:** a joint is moved, turned or scaled, on top of the animation or instead of it.

A joint holds one entry, and the first in file order wins. A constraint beats a skin attachment's follow on that joint. Some
joints refuse constraints, and the panel warns about them:

- **A chain's joints.**
- **The player body's joints 1 and 13**, which shake on hits.
- **The ankles, 16 and 20**, which the foot planting holds. The thighs and shins (14, 15, 18, 19) take a constraint, but lose it
  while the feet are planted.
- **Face, hair and coat joints that are pinned to the body.** There is no fractional twist: a Pin with Blend 0.5 mixes in half the bend too.

A **Link** on a Model entry keeps two of its chain joints within a distance (Max, in cm), so neighbouring tendrils can't
part: the game simulates every tendril alone, so nothing else holds them together. It isn't a constraint: it holds no joint
and runs after the chains have moved. Both joints must be held by chains listed on that model. A tendril's first joint keeps
its place, so its partner takes the whole pull, and a link between two first joints is refused. Max at the rest distance,
or a little more, holds the cloth without making it look stiff. A link can pull a joint into a collision shape for a frame.
The chain preview runs the links, as the game does (needs a dmc4_hook with links).

**Preview Attachments** shows the attachments and constraints in the viewport. A chain's bones stay free, because the game gives
them to the chain. It uses `ALBAM_` constraints and `EXTP_` Empties, which are never exported. It's close, not exact: Blend is
approximate, Aim's Up axis is approximate and its Limit isn't shown. On a coat model, set Of, because the preview can't tell
whose coat it is.

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

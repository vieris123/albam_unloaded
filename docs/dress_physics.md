# Dress physics playbook

How to give a character's skirt or dress cloth physics that holds up in DMC4, from Ellen's dress and 2B's skirt
(November 2026). It covers the order to work in, the settings that worked and what each problem looks like with its
fix. The reference for every setting is [new_model.md](new_model.md) ("Cloth, tails and other extra parts" and "The
list file"); this guide is the route through it.

You need Albam and a dmc4_hook build with ModelExtension's `<physics>` solver at version 2.7 or later. Earlier builds
fed the drawn pose back into the simulation, so a dress with a Blend below 1 jittered.

## The short version

1. Make the dress its own `.mod`, skinned to the body with ModelExtension.
2. Give it one bone chain (a tendril) per strip of cloth, rooted on the hips.
3. Put the thigh and shin collision capsules on the body.
4. Hand the chains to dmc4_hook's solver as one closed sheet:

   ```xml
   <physics clt="chains\dress_00" stiffness="0.3 0.05" damp_to="world" damping="0.2"/>
   <!-- one <physics> per chain file -->
   <cloth roots="<every strip's first joint, in order round the waist>" closed="true"/>
   ```

5. Check every chain file's collision radius (Collision Size), and tune damping and radius in the preview on the game's
   own motions.

The rest of this guide is the detail behind each step, and what to do when it goes wrong.

## 1. The dress as its own model

- **A separate `.mod`.** Attach it with `<attach path="...dress" to="...body"/>` (no `joint=`: a skin attachment). Its
  chains go on that model, so the body's chains and the dress's don't compete for slots.
- **The body's joints, copied exactly.** Copy the body joints the dress is weighted to into its armature, at the body's
  rest pose and with the same joint numbers: a joint with the same number follows the body.
- **New joint numbers for the dress's own bones.** They must be numbers the body doesn't use. Albam's automatic numbering
  only knows the armature it's numbering, so check against the body. Ellen's ring bone first got 252, the body's left
  shoulder, and followed the shoulder. Also stay clear of the player rigs' face joints (155-165) and deform joints
  (200-215).
- **One tendril per strip of cloth,** a chain of 4-6 bones from the waist to the hem. A chain file holds 32 slots,
  counting one between tendrils, so a skirt takes several files. Settings are per file, so sort the strips into files by
  where they hang: front, sides, back.

## 2. Where the strips hang from

Check the parent of each strip's root bone. The cloth turns with that bone.

- **Hips (joint 13): good.** 2B's skirt hangs from the hips and needed nothing here.
- **Chest: fix it.** Ellen's hung from the chest, because her skirt starts above the hips. Nero's run leans the chest
  50-90 degrees, which swings the front strips back through the thighs, and they stayed folded on them after she
  stopped.

  Moving the roots onto the hips opens a gap between skirt and bodice of up to 23 cm. Give each root a pivot instead:
  1. In Edit Mode, add a bone at each root's head, with the hips' rotation, parented to the chest. Make it a
     non-deforming bone with a free joint number.
  2. Parent the strip's root bone to it.
  3. Add `<pin joint="<pivot>" to="13" mode="rot"/>` for each pivot in the dress's list.

  The roots stay on the waistline and the strips turn with the pelvis. In the preview, Ellen's front strips folded in
  47% of running frames before this and 0% after. One ring bone for every root also works, but turning it moves the
  waistline by up to 16 cm.

## 3. The animated pose the cloth is pulled toward

dmc4_hook's solver pulls each segment toward its animated direction (Stiffness). Look at the dress's animated pose while
she walks and runs: that is the shape the cloth is drawn toward.

- **A skirt modelled flared (2B):** the animated pose is the bell she was modelled with. Nothing to do.
- **A skirt rigged to hang straight and follow the hips** (MMD and other games' models; Ellen): the animated pose runs
  through her legs whenever she takes a step. Two fixes, used together:
  - **`damp_to="world"`:** damping slows the cloth toward standing still instead of toward the animation, so the
    skirt lags her like real cloth instead of being dragged into the legs. Leave `backstop` off with it, or it pulls
    the cloth back into the fold.
  - **Flare the strips in Edit Mode:** select each strip's root bone with everything under it and turn it outward about
    its head (20 degrees on Ellen). The mesh doesn't move, but the animated pose now clears the legs.
- **After flaring, grow the radius along the strip.** Collision is worked out on the bones, and the mesh now hangs
  inside them. At the tail, the gap is about 2 × the strip's length × sin(flare / 2): 15 cm on a 44 cm strip flared
  20 degrees. Make the radius grow by that much from root to tail, or her legs come through the skirt at idle. Ellen:
  `radius="1.08 11.98"`.

## 4. Collision shapes

- **On the body, collided against with `collision_model`.** Put the `.col` on the body's joints and set
  `collision_model` to the body on the dress's Model entry. The shapes then move with the legs whatever the dress does.
- **Pairs of capsules in front of and behind each thigh,** upper and lower pairs tapering toward the knee, plus the
  shins. One fat capsule per thigh pushes the sides out into a shelf.
- **Inside the cloth at rest.** A capsule poking through makes the cloth drape over nothing. Start the thigh capsules
  partway down the thigh.
- **The chain's radius adds to the shapes'.** See step 6: this is the setting to check first when the cloth stands off
  her body.

## 5. On dmc4_hook's solver, as one sheet

The game's own solver simulates every tendril alone. A leg pushing between two strips shoves them apart and the cloth
between them stretches open. Links between neighbouring joints only partly hold them, and the front strips stay folded
after she stops. On 2B, with 27 links:
- **Running:** strips up to 5.7× their rest distance apart, sticking out sideways.
- **After stopping:** a front strip folded in 97% of frames.

Put every skirt chain on dmc4_hook's solver and join the strips into one closed sheet:

- **One `<physics clt=...>` per chain file,** on the dress's Model entry. The quickest way: select each `PHS_` Empty and
  click **Use dmc4_hook's Solver** in its Chain panel.
- **One `<cloth roots="..." closed="true"/>`** listing every strip's first joint in order round the waist. Overlapping
  layers go in the order they sit. Closed joins the last strip to the first; leave it off for an open coat.
- **Remove the `<link>`s:** the sheet replaces them.

On 2B as a sheet:
- **Running:** strips at most 2.8× their rest distance apart, and the skirt drapes over the raised thigh in one piece.
- **After stopping:** nothing folded.

## 6. Settings that worked

| Setting | Value | Why |
|---|---|---|
| `stiffness` | `"0.3 0.05"` | Firm at the waist, loose at the hem: keeps the shape without stiffening the hem. |
| `damp_to` | `world` | Lags like cloth; needed for straight-hanging rigs, and slightly better on 2B's flared one. |
| `damping` | `0.2` | Calms it. The default (1 minus the file's Damping, at least 0.1) took 94 frames to settle after a stop on 2B; 0.2 took 37, 0.35 took 22. It barely changes the motion while running. |
| `radius` | 1.5-2.5 cm, or a root-to-tail list after flaring | See below. |
| Gravity, Blend | the chain file's | Gravity 0.3 vs 0.03 made little difference with the sheet. Blend only shapes what's drawn now, not the simulation. |

**Check every chain file's collision radius.** Left out of the list, `radius` is the file's Collision Size, and files
tuned for the game's solver may carry big values. 2B's front and left files had 7.5 cm, the others 1.5. On the sheet
that held her front-left panels about 5 cm off her leg at idle, and the cloth between strips stretched. With
`radius="2.5"` on those two files:
- **Idle:** within 2 cm of the modelled shape, and fewer leg vertices through the skirt (113 instead of 185).
- **Running:** the front strips flew up in half the frames instead of nine in ten.

## 7. The chest (and other single-joint chains)

A one-joint chain is a pendulum hanging from that joint, with the file's Tail Length as the string.

- **Too fast:** lengthen the tail. Each swing takes about √(length / gravity) times longer; 2B's chest went from 10 to
  15 cm, about a fifth slower.
- **Turning or flipping sideways:** use the joint's Limits (Bone Properties > Chain Bone).
  - Measured axis: **Z**.
  - Sideways range (Y): **min and max both 0**.
  - Forward / back range (X): **-180 to 180**.

  When a clamp engages, the game rebuilds the joint's rotation from the two measured angles and drops any turn about
  the measured axis. A sideways range of exactly 0 clamps every frame, so the turn about Z never survives and the bounce
  stays free. On 2B's chest, unlimited, the up axis turned about 100 degrees on average (up to 180: the chest flipped);
  limited, not at all.
  - **Measured axis X or Y doesn't work** on a joint with this rest pose: X adds a 90-degree twist, and Y doesn't stop
    the turn.
  - **To cap the bounce too,** set the forward / back range to the rest angle ± 30.
  - **The joint's rest pose must match the rebuild** (no roll, chain along +Y). If it doesn't, every clamp flips the
    joint half a turn: Ellen's chest did, until its rest was fixed. [new_model.md](new_model.md) has the details.

## 8. Testing

- **The game's own motions, not a swing from a clean start.** Import the character's body LMT onto the body and play
  idle, then several run loops, then idle again. Use Nero's `pl000_01` blocks 0 idle, 1 walk, 3 run, or Dante's
  `pl006_01`. The stop at the end is where folds show. Swinging a thigh from rest hid every one of the problems above.
- **Carry the travel.** A run animated in place understates what the cloth goes through. Move the armature by each
  loop's root motion, or check the run in the game.
- **Watch for these:** a front strip folded or caught behind a thigh; seams opening between strips; legs through the
  cloth at idle; cloth stuck out from the body at idle; how long it takes to settle after a stop.
- **Textures on.** A grey render hides a panel sticking out.
- **The preview is close, not the game.** It runs the same solver, but in-game reports outrank it: Ellen's
  front at Blend 1.0 on the game's solver passed the preview and folded at her hips in the game. When the game
  disagrees, a recording of the run in the game is what finds the cause.
- **Mod packages:** after changing files in a package under the mod manager, reinstall the package before testing.

## Symptoms and fixes

| You see | Cause | Fix |
|---|---|---|
| Strips part and stick out sideways while running | The game's solver moves each strip alone | dmc4_hook's solver as one closed sheet (step 5) |
| Front strips stay folded after she stops | Same | Same |
| The skirt folds over the standing leg while running | The animated pose runs through the legs | `damp_to="world"`, flare the strips (step 3) |
| Front strips swing back through the thighs on a run | Strips hang from the chest, which leans | Pivot bones pinned to the hips (step 2) |
| Legs through the skirt at idle after flaring | Collision is on the bones, outside the mesh | Radius growing root to tail (step 3) |
| Panels stand out from the legs at idle, cloth stretched | A chain file's Collision Size is too big | `radius=` 1.5-2.5 on those files (step 6) |
| The skirt keeps swinging after a stop | Damping too low | `damping="0.2"` (step 6) |
| The cloth jitters while still | A dmc4_hook build before solver version 2.7 | Update dmc4_hook |
| Chest too quick | Short pendulum | Longer Tail Length (step 7) |
| Chest turns or flips sideways | Nothing stops a turn about its forward axis | Limit: measured axis Z, sideways range 0 to 0 (step 7) |
| Chest flips half a turn when a limit engages | Its rest pose doesn't match the clamp's rebuild | Fix the rest pose ([new_model.md](new_model.md)) |

## Worked examples

**2B** (`2B (Albam)\nativePC\model_ext\2b.xml`): a flared skirt, roots on the hips, 17 strips in four files.

```xml
<model path="model\game\pl006\2b_dress" collision_model="model\game\pl006\2b_dress">
  <chain clt="chains\2b_dress_00" col="chains\2b_dress"/>
  <!-- ... _01 to _03 ... -->
  <physics clt="chains\2b_dress_00" stiffness="0.3 0.05" damp_to="world" damping="0.2"/>
  <physics clt="chains\2b_dress_01" radius="2.5" stiffness="0.3 0.05" damp_to="world" damping="0.2"/>
  <physics clt="chains\2b_dress_02" radius="2.5" stiffness="0.3 0.05" damp_to="world" damping="0.2"/>
  <physics clt="chains\2b_dress_03" stiffness="0.3 0.05" damp_to="world" damping="0.2"/>
  <cloth roots="186 159 164 169 174 179 236 239 231 225 220 198 193 135 140 145 191" closed="true"/>
</model>
```

Her chest (`chains\2b_boobs.clt`, on the body): Tail Length 15, Limits on joint 88 with measured axis Z and the
sideways range 0 to 0.

**Ellen** (`ellen\nativePC\model_ext\dress.xml`): an MMD skirt hanging straight from the chest, 15 strips flared
20 degrees, each with a pivot pinned to the hips.

```xml
<model path="model\game\pl000\ellen_dress" collision_model="model\game\pl000\pl000">
  <!-- <chain> entries for dress_00 to _04 and the belt ribbons -->
  <physics clt="chains\dress_00" stiffness="0.3 0.05" damp_to="world" radius="2.16 13.06"/>
  <physics clt="chains\dress_01" stiffness="0.3 0.05" damp_to="world" radius="1.08 11.98"/>
  <!-- ... _02 to _04 like _01 ... -->
  <cloth roots="227 222 217 192 187 179 174 169 147 142 134 97 92 87 80" closed="true"/>
  <pin joint="71" to="13" mode="rot"/>
  <!-- ... one pin per strip's pivot bone ... -->
</model>
```

Its belt ribbons stay on the game's solver. The danglies hanging off it collide with the skirt
(`collision_model="...ellen_dress"`), so the dress attaches first in the same file.

# Effect keyframes in Blender

How the keyframes of a DMC4 `.efl` effect are edited in Albam, and what happens to them on export. Read this
once before animating an effect; the short version is in "The workflow".

## What the game stores

A record (one emitter and its particles) can animate some of its fields over time with a **keyframe track**:
a list of keys, each at a game frame (60 per second) with a value. A record has a fixed set of possible tracks,
one per animatable field; most records use none or a few (Intensity, Color, Scale and Speed are the common ones).

Each key holds **two** values:

- the **value**;
- a **random part**: when a particle spawns, the game draws a random number r in 0-1 once, and the key's value
  for that particle is `value + random part x r`. Colour keys hold two colours instead, A and B, and the
  particle's colour is mixed from A toward B by r.

Every track also has four settings that apply to the whole track:

| Setting | Meaning |
|---|---|
| Interpolation | 0 linear between keys, 1 hermite (smooth), 2 spline (smooth, through four neighbouring keys) |
| Timer | which clock the key frames count on: the particle's age (frame 0 = its birth), the generator's timer (frame 0 = the end of the generator's WaitFrame), or the effect / parent / global timer (frame 0 = the effect's start) |
| Loop | start over after the last key instead of holding its value |
| Init only | evaluate the keys once, when the particle spawns; after that the field's `...Add` value applies every frame |

**WaitFrame and the timers.** A generator waits `WaitFrame` frames before it first spawns. Particle-age keys
start at each particle's birth, so they come after the wait anyway. The generator's timer stands still during
the wait (the game's generator tick doesn't advance it until the generator fires), so generator-timer keys also
start when the wait ends; the generator's own position / rotation / scale keys hold their first value during the
wait. Effect-timer keys ignore the wait.

While a track has keys the field's plain value is ignored. A keyed value is absolute: the field's `...Add`
(per-frame growth) is ignored too, unless the track is Init only.

## Where they live in Blender

Importing an effect makes an Empty per record (`<file>.NN_<type>`). Its keyframes are F-curves on that Empty,
in an action named `<Empty>_keys`:

- **Generator position, rotation, scale** keys are the Empty's own `location`, `rotation_euler` and `scale`
  keys. The Empty's rotation mode is set to the game's rotation order (the generator's `Order` field). A
  RelationType 2 generator (joint position, world rotation) keeps its rotation keys on its `_rot` companion.
- **Every other track** is a custom property on the Empty named `<Block> <Field>`: `Particle Intensity`,
  `Particle Color`, `Particle Scale`, `Move Speed`, `Move Rot`, `Life KeepFrame`, `Generator SetNum`... They
  are listed in Object Properties > Custom Properties, and in the Dope Sheet / Graph Editor under the Empty.
- The **random part** is a sibling property `<track> Rand` (`Particle Intensity Rand`). For colour tracks it is
  `<track> B`, the second colour of the mix. It is a plain value (one random part for every key) until you key
  it: then each key of the value track reads the Rand curve at its own frame.

Units:

| Track type | Property | Value in Blender |
|---|---|---|
| number (Intensity, Scale, Speed, Width...) | one float | as the game's value |
| whole number (SetNum, KeepFrame, PatNo...) | one integer | as the game's value |
| colour (Color, PlaceColor) | 4 floats, colour picker | RGBA 0-1 (the game stores bytes) |
| vector (Rot, ModelScale, Ofs...) | 3 floats | as the game's value; rotations in radians, shown as degrees |
| generator Pos | `location` | metres (the game uses centimetres) |
| generator Rot | `rotation_euler` | radians, the game's order |
| generator Scale | `scale` | as the game's value |

Hover a property for its tooltip: it carries the field's help text.

Time: the effect's frame 0 is the timeline marker **`EFL_<file> start`**, placed at the frame the effect was
imported on. A key at game frame `g` sits on scene frame `start + g x fps / 60`. At 60 fps (the LMT import's
setting, recommended for effects) that is simply `start + g`, for effect-timer tracks.

Generator-timer and particle-age tracks are drawn after the record's wait: `start + (WaitFrame + g) x fps / 60`.
For the generator timer that is exactly when the key plays. A particle-age curve is drawn for the **first**
particle, which is born when the wait ends; a particle born later plays the same curve from its own birth.
Editing WaitFrame in the Effect Editor, or a track's Timer in the Keys tab, moves the track's keys to match;
their game frames don't change. A key can't go before the start of its curve (game frame 0 of its timer):
Insert Key moves such a key there and says so.

## The workflow

**See the keys.** Select the record Empty (click it in the viewport, or a row of the Effect Editor's records
list) and open a Dope Sheet or Graph Editor. Both show only selected objects by default, and the keys are on the
Empty, not on its particles object. The Effect Editor's **Keys** tab lists the record's tracks with their key
counts; clicking a track's name selects its curves so the Graph Editor shows just them.

**Add keys to a field that has none.** In the Effect Editor, every field that can be keyed has a keyframe dot
at the end of its row, like Blender's own. Click it: a key is inserted at the current frame with the field's
present value and random part, and the track's property appears on the Empty. From then on:

- set the timeline to another frame, change the property (Custom Properties, or the Keys tab's dot again after
  typing a new value in the property) and insert another key with the dot, or hover the property and press
  **I**;
- or add and move keys straight in the Graph Editor / Dope Sheet.

For the generator's position, rotation and scale, move or rotate the Empty and press I over it in the
viewport, or use the dots next to the Generator tab's `Pos` / `Scale` tracks in the Keys tab.

**Edit keys.** Drag them in the Dope Sheet (time) or Graph Editor (time and value), or type values in the
sidebar (N) of the Graph Editor. Selecting a key and setting its interpolation (T) works as in any animation:
Linear exports as the game's linear, Bezier as the smooth type the track had (hermite unless it was spline). The
Keys tab's **Interpolation** sets it for the whole track. **Loop** adds a Cycles modifier to the curves (you can
add it yourself in the Graph Editor's Modifiers tab, with Repeat Motion); **Timer** and **Init only** have no
Blender equivalent and are only in the Keys tab.

**Colour keys.** Colour tracks are colour properties: in Object Properties > Custom Properties, `Particle
Color` and `Particle Color B` are swatches that open Blender's colour picker (wheel, HSV, hex). Pick a colour,
hover the swatch and press **I** to key it at the current frame; move on, pick again, **I** again. The Graph
Editor shows a colour only as its four channels, as it does for any colour in Blender.

**The random part.** Type a value into `<track> Rand` for one random range on every key. Key it (I over it)
when the range should differ per key; keep its keys on the same frames as the value's. For colours, pick
`<track> B`; equal A and B mean no random mixing.

**Remove keys.** Delete keys in the Dope Sheet / Graph Editor; deleting the last one removes the keyframe and the
field's plain value is used again. The Keys tab's **X** clears a whole track at once. **Revert Fields** puts
the file's keys back.

**Preview.** With Live on (the default), every key edit replays the particles a moment later. Particle keys
replay; generator position keys are Blender's own animation, so they show at once, and the recorded emitter
motion is dropped when they change (play the timeline again, or Record Emitter Motion).

**Timing the effect.** Drag the start marker to move the whole effect in time: every key of its records and
its end marker move with it. **End Effect** (top of the Effect Editor) puts an `EFL_<file> end` marker where the
effect's owner would end it; drag it to try other lengths, or delete the marker to turn it off. The particles
are simulated up to the scene's End frame, so extend the scene range for long effects.

**Export.** Nothing to do: the game keyframes are rebuilt from the curves when the effect is exported or
applied. Tracks you didn't touch keep their exact bytes.

## Limits and pitfalls

- **Whole game frames.** Keys export at `round((frame - start) x 60 / fps)`. At 24 or 30 fps a key can land
  one game frame off; two keys that round to the same game frame refuse to export ("key frames must
  increase"). Work at 60 fps when the exact frame matters.
- **Keys before the start of their curve** (the start marker plus the wait, for generator-timer and
  particle-age tracks) would be negative game frames and refuse to export; Insert Key won't put them there, but
  dragging them there in the Graph Editor will.
- **Key frames must increase**, and a track holds at most 255 keys. The first key doesn't have to be at frame 0:
  before it the first key's value holds.
- **Blender's curve is not the game's.** The preview evaluates the game's own interpolation (from the exported
  keys), so what the particles show is right. The Graph Editor's Bezier handles are a drawing: the game's
  hermite uses the neighbouring keys as tangents and its spline passes through four keys, so tweaking handles
  changes nothing in the game. Only the keys' positions and values export.
- **Loop** repeats from the first key to the last (the game's rule); the Cycles modifier shows the same thing.
- **Colours** export as bytes (0-255 per channel) and whole-number tracks as integers; in-between values round.
- **A random WaitFrame** (a non-zero random part, on about 150 game records) is rolled per spawn in the game.
  Generator-timer curves are placed after its base value; the preview rolls it, so a generator can start up to
  the random part later than its curve shows.
- **Changing WaitFrame outside the Effect Editor** (typing into the record's `efl_gen` custom property) doesn't
  move the curves; the keys still export at the right game frames, only the curve's place on the timeline is
  stale until the next edit of WaitFrame or a rebuild.
- **A per-key random part that isn't keyed** at a key's frame reads the Rand curve there (interpolated), or
  the static Rand value when the curve has no keys.
- **Rebuilds recreate the Empties.** Edits that change what the import builds (a particle's blending, texture,
  shape, a new record, a changed strip) rebuild the effect; the keys come back from the exported bytes, but curve
  selection and any handle tweaks are lost.
- **Effects imported before 2026-10-11** (older .blend files) keep their old baked generator curves and export
  their stored keys until a track is animated; that rebuilds all the record's curves. Re-importing is simpler.
- The particle **Color** track has no single field (the particle's start colour comes from Color0 / Color1 by
  ColorFlag), so it has no dot in the field rows: add its first key from the Keys tab. The same goes for PatNo,
  Ofs (path offset), FallSpeed, Radius0/1 and Height0/1, SpotRot and the generator's Rot.

## Track reference

Which tracks each block can have (the property name is `<Block> <Name>`):

| Block | Tracks |
|---|---|
| Generator | Pos, Rot, Scale (transform keys), SetNum, Range |
| Life | KeepFrame |
| Move Add / Mul | Speed, Rot, FallSpeed |
| Move paths (PathStrip, PathChain, PathKeyframe, PathLine) | Speed, Rot, FallSpeed, ReleaseFrame; PathKeyframe: Ofs; PathChain: Length, ChainRot, BlendRot, BlendRate |
| Every particle | Intensity, Color, Scale, PatNo |
| Billboard | Angle |
| Polygon, PolygonStrip | Width, Height (Polygon), Rot, PlaceColor (PolygonStrip) |
| PrimModel | Radius0, Radius1, Height0, Height1, ModelScale, Rot, PlaceColor |
| Model | ModelScale, Rot, ScrollU, ScrollV |
| Polyline, Texline, Line (and cloth) | HeadSize, PlaceSize (Polyline), PlaceColor; CHAIN / LENGTH extensions: Length, ChainRot, BlendRot, BlendRate, LineLength, LineRot |
| Light | SpotRot |

The Effect Editor's Keys tab is the authoritative list for the record in front of you.

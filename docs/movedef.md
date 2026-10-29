# Moves (MoveDef files)

A MoveDef file is one XML per player move, read by dmc4_hook's `MoveDef` mod from `nativePC\movedef\`. It gives the
move its input, its motion, its cancel windows, effects, sounds, hitboxes and hand-offs to other moves. The format and
what each element does in the game are in the modder guide, `D:\dmc4_hook\docs\movedef.html`. This page covers making
and editing those files in Blender.

The panel is in the **Dope Sheet > Action Editor**, sidebar (N), tab **Albam [Beta]**, under the LMT panels:
**Moves (MoveDef)**.

## Making a move from an animation

1. Import or make the LMT the move plays (LMT panel), and select its animation in the Animations list.
2. In Moves, click **+** (New Move):
   - **New Move**: a move of its own. It gets the character's first free id (Nero 0x34 and up, Dante 0x6C and up),
     a move-table row (Input: command, melee or gun; Where: ground, air or both), its LMT (`<lmt path=>`, no bank:
     dmc4_hook's motion registry puts it in a free bank in the game), and a stage that plays the selected
     animation (`block=`, the animation's block number in that LMT) and borrows the vanilla `.ctn` script 0:5. A
     command row comes with a starter input command (lock-on + style) to edit.
   - **Overlay on Vanilla**: adds to a vanilla move. Pick the animation from the vanilla LMT (`pl000_NN` /
     `pl006_NN`); the stage then names that motion (bank NN - 1). Fill in the move's vanilla ids (`ids`, e.g.
     `28 29` for Nero's Streak).
3. Edit the elements (below), then **Write XML**. The default location is `movedef\<name>.xml` under the game folder
   (Export panel > Game Folder), which is where the runner reads it. Export the LMT too (LMT panel > Export LMT) to
   the path in the move's `<lmt>`.

**Import** (the import icon next to the list) reads an existing `.xml`, hand-written or not.

## Editing

The **Elements** list shows the file as a tree: `<move>`, its `<table>`, `<command>`, `<lmt>`, `<stage>` and what's
inside them. Select one to edit its attributes below the list.

- **+** adds an element inside the selected one (only what the runner reads there is offered). **−** removes the
  selected element and everything in it.
- Each attribute has a widget for its kind (numbers, toggles, a dropdown, the eight cancel categories as buttons).
  **Hover an attribute's name** for what it does and its default; **X** removes it (the runner then uses the default);
  **Add Attribute** sets one the element doesn't have yet.
- **Frames are pose markers.** Cancels, triggers, effects, sounds, shells, the launch, a `<next frame=>` and the
  stage's `cancel_frame` each get a marker named `md <element>` on the stage's animation (its first `<slot>`'s block,
  its `block=`, or its `motion=`). Drag the marker in the Action editor (View > Show Pose Markers) to change the frame. Frames are
  game frames at 60 fps, converted the way LMT export converts (from the animation's start and Frame Rate). A new
  element lands on the current frame. A stage whose animation isn't in the scene shows plain numbers.
- **Cancels from .ctn** (the import icon next to the Elements list): fills the selected stage's cancels and triggers
  from the game's script of its motion (`chartbl\<character>.ctn`, from Game Files). For an overlay that's the vanilla
  windows to edit: the runner replaces all the motion's cancel commands with the file's `<cancel>`s, and all its
  trigger / vibration commands with its `<trigger>`s, so keep every one you want. 12 vanilla scripts loop (9 of
  Nero's, 3 of Dante's); the runner can't change those and the report says so.
- **Buster grabs:** every grab motion plays from motion bank 15 (the grabbed enemy's LMT, `pl000_<target>_00`), so an
  overlay made from a grab animation gets `motion="15:N"`. Its script is one per enemy (`.ctn` banks 10-29), so
  Cancels from .ctn asks which enemy's to read (preset from the LMT's name). The overlay covers slot N of every
  enemy's grab; there's no attribute yet to pick one enemy.

## Hits: `<attack>` and `<shell>`

A `<shell>` is a hitbox capsule the move carries; what a hit does (damage, reaction, hit stop, style points ...) comes
from attack data:

- **From an `.atk` file:** the shell's `atk` (default: the character's own, `Collision\pl000` / `pl006`) and `entry`.
  `entry` is an index or an entry's name (case-insensitive); the panel shows which entry it picks
  (`14 Dropkick`) when the `.atk` is in Game Files.
- **From an `<attack>`** (add one to `<move>`): give it a name and pick it in the shell's `attack` dropdown. An attack
  is an `.atk` entry (`atk` / `entry`) with the values you set on top, or, without `atk` / `entry`, only the values
  you set (the rest are Nero's RED-ComboA_00: damage 80, level I 2, hit stop 3 ...), so it needs no file entry.
  Its name is also the hit's name in the game: 15 characters at most.
- A shell's own values (damage, damage_type ...) override either source.
- `atk` without `entry` means entry 0, and entry 0 of the characters' own `.atk` files is an empty placeholder (Nero's
  `No_used`, Dante's `no-attack`). Check warns when the picked entry deals no damage and nothing sets `damage=`
  (some real entries do too: the Streak's `_HIT` hit checks).

## Checks

**Check** (and Write XML, which refuses to write with errors) tests what the runner would refuse or ignore, plus
what only Blender knows:

- the move has a name, a character and an id in range (an overlay names a vanilla id), unique against the other moves
  in the scene and the `.xml` files in the game folder's `movedef\`;
- the `<lmt>` has a path; a fixed `bank=` (the old form, only to match a C++ mod that keeps its own bank) is 10-14,
  and no other move of the character puts another LMT in it. Without `bank=` the motion registry places the file, so
  moves don't compete for banks;
- a stage plays `<slot>`s, `block=` (0-255, needs the `<lmt>`) or `motion=` (a vanilla `bank:slot`), not `block=` and
  `motion=` together; a `motion=` bank is 0-15 (a grab's `.ctn` bank 10-29 isn't a motion bank); `motion=` in a runtime bank (10-14, and Nero's 4 / 6-9) is refused unless it's the move's own
  fixed `bank=`: the registry fills those banks (use `block=`);
- every block a stage plays exists in the LMT and has keys (an empty block soft-locks the game), and every frame is
  inside the motion (a `<next frame=>` past it is a warning: the runner never reaches that frame, a looping block wraps
  first, so the transition never fires; `ticks=` is the way to give a stage a time limit);
- `<input command=>` names a command, `<follows>` / `<next to=>` name existing moves, at most five cancel words, eight
  shells, known categories, contact bytes and directions;
- a `<shell>`'s or `<attack>`'s `entry` exists in its `.atk`, by index or name (when the `.atk` is in Game Files);
  `<shell attack=>` names an `<attack>` of the file (the runner drops the shell otherwise); attack names are unique,
  and a name over 15 characters is a warning (the game cuts it);
- elements and attributes the runner doesn't read are warnings; they stay in the file.

## What's kept

Writing changes only what you edited: comments, line breaks inside tags, attribute order and anything Albam or the
runner doesn't know stay as they were. A file written back without edits is byte-identical.

## Not yet

- Save to Game Folder writing the xml, LMT and `.atk` together (Write XML and Export LMT are separate for now).
- Writing new entries into an `.atk` file: not needed for `<attack>`s (they live in the move file); the codec
  (`dmc4xml/atk.py`) is there for hits on the game's own path later.
- Effects picked from Game Files, joints by name: the runner reads `joint="self|weapon"` only.

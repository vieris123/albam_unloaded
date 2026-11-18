# Game Link

Albam can talk to the running game through dmc4_hook's debug server:
- it shows what the game is doing (room, mission, frame);
- it sends your scheduler (`.sdl`) key edits to the game as you make them;
- it ties Blender's playhead to a scheduler's clock in the game.

## Setting it up

1. In `dmc4_hook.cfg`, set `debug_server_enabled = true`, or tick the checkbox in dmc4_hook's Debug server panel. The
   server listens on port 13350 unless `debug_server_port` says otherwise.
2. In Blender, open the 3D View sidebar's **Albam [Beta]** tab and the **Game Link** panel.
3. Set the port if you changed it, then click **Connect to Game**.

The game can start before or after you connect. Until it answers, the panel says "Game not answering", and Albam
keeps asking every 2 seconds.

## What the panel shows

| Row | Meaning |
|---|---|
| Room | The room number and its stage; "custom" for a room added by dmc4_hook |
| Mission | The mission number |
| Frame | The game's frame count. It goes up while the game runs, so you can see the link is live. "(paused)" when the debug server paused the game |
| Players | How many players are in the game |
| Load | A number that goes up each time the game loads a room. Shown once dmc4_hook reports it |

The last line gives the debug server's phase and build time.

**Disconnect** (the X) stops Albam from asking. It changes nothing in the game, except that a scheduler paused by
Drive Game runs again.

## Live scheduler edits

Under **Schedulers (.sdl)**, turn on **Live .sdl Edits**. This needs dmc4_hook's Dev tools
(`debug_server_dev_tools = true` in `dmc4_hook.cfg`, or the Dev tools checkbox in its panel).

Every `.sdl` you imported into the scene is matched with the game by its game path, for example
`scr\st405\data\blade01`. The list shows each one's state:

| State | Meaning |
|---|---|
| live | The game's copy matches Blender. Your edits go to the game as you make them |
| not loaded in the game | The current room doesn't use this file |
| a different file in the game | The game loaded another version of the file (other tracks or keys). Albam won't touch it. Export it, deploy it, and reload the room |
| needs export + room reload | Your last edit added or removed keys or tracks, or changed names or resources. The game can only take changes to existing keys. Export, deploy, and reload the room. Undoing the edit makes the file live again |

When a file goes live, the game's copy first takes Blender's values, in case the game loaded an older version of
it. After that, every edit is sent a moment after you make it:
- a key's value in the Graph Editor or Dope Sheet;
- a key's frame, if no keys are added or removed;
- a property's value in Object Properties > Custom Properties.

To move or turn a unit (its `mPos` / `mAngle`), edit those properties. Its Empty only shows them.

These track types are sent: int, float, bool and vector. Resource, string, ref and event keys need export + reload.

When the game loads another room, Albam checks and sends again by itself.

Re-sending a key the scheduler is sitting on makes a one-shot (event-style) key fire again.

## Playhead and the game's clock

In the same panel, pick a **Scheduler** (one of the imported `SDL_` roots) and a **Clock** mode. A scene frame is
one scheduler frame, 1/60 s.

| Clock | What happens |
|---|---|
| Off | Blender and the game run on their own |
| Follow Game | Blender's playhead follows the scheduler's frame in the game, so the Graph Editor shows where the game is |
| Drive Game | The scheduler in the game is paused and set to Blender's playhead. Scrubbing in Blender scrubs the game. For a looping scheduler the frame wraps into its length |

Off, another scheduler, or Disconnect lets a driven scheduler run again.

## Good to know

- Albam never waits for the game. The calls run in the background, so Blender stays responsive even when the game is
  loading or stopped in a debugger.
- The link carries no files. Files still reach the game through the mod manager or Save to Game Folder. The link only
  reads and changes what the game has already loaded.
- Nothing about the link is saved in the `.blend` except the port.

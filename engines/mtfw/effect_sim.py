"""Animated particle preview for imported .efl effects (efl_import_plan.md M2).

Each simulated record gets a point-cloud object. A shared Geometry Nodes group instances the particle's shape (a
hidden source object: billboard/polygon quad or PrimModel mesh) on the points, using per-point attributes for
rotation, scale, tint (colour x intensity), alpha and the UV transform of the current flipbook frame. A
frame_change_pre handler re-evaluates the simulation (efl/sim.py) for the current frame and rewrites the points.

Emission space (efl.sim.emission_space):
- follow: the points object is a child of the generator, positions are generator-local (move type None).
- world / translation: the points object has no parent; each particle is placed with the generator's world matrix
  of its birth frame, so it stays where it was emitted when the bone moves. Those matrices are recorded per frame
  by a frame_change_post handler (or all at once with albam.efl_record_motion); frames not seen yet use the
  generator's current matrix.

The .efl bytes are stored on the effect root, so playback rebuilds itself after reopening the .blend.
Frame 0 of the effect is the scene frame stored as root['efl_start_frame']; game time runs at 60 fps.
"""
import base64
import math
from array import array

import bpy
from bpy.app.handlers import persistent
from mathutils import Euler, Matrix, Quaternion, Vector

from albam.registry import blender_registry
from .efl import EffectList
from .efl.ean import ANIM_FLIP_U, ANIM_FLIP_V, flip_affine_row
from .efl.sim import (CULL_PER_PARTICLE, ROT_ORDERS, ext_line_range, SPACE_FOLLOW, SPACE_FOLLOW_TRANSLATION, culling_fade, simulate,
                      state_at)

NODE_GROUP = "ALBAM_EFL_Particles_v6"   # v1: uv_off/uv_scale; v2: affine uv_u/uv_v; v3: + tint; v4: + shape;
                                        # v5: + scale_after; v6: + PrimModel colour gradient (efl_grad, place_*)
TINT_GROUPS = ("ALBAM_EFL_Particles_v3", "ALBAM_EFL_Particles_v4", "ALBAM_EFL_Particles_v5",
               "ALBAM_EFL_Particles_v6", "ALBAM_EFL_Models_v4")   # alpha = colour alpha
GRADIENT_ATTR = "efl_grad"   # PrimModel source vertices: factor toward colour B (efl/primmodel.py)
UV_STRIDE = 8                           # per pattern: a, b, off_u, c, d, off_v, width px, height px
GAME_FPS = 60.0
SCALE = 0.01
SIM_KEY = "efl_sim"
LINE_KINDS = (1, 3, 4, 12, 13, 14)   # Polyline, Texline, Line + cloth variants: ribbons (points + Geometry Nodes)
LINE_NODE_GROUP = "ALBAM_EFL_Ribbons_v1"   # camera-facing strips from point chains (effect_sim._ribbon_node_group)
LINE_EYE = "Eye"                           # its input: the eye position in the object's space (set every update)
LINE_MATERIAL = "Material"                 # its input: the ribbon material (Curve to Mesh carries none)
STRIP_KINDS = (15,)                  # PolygonStrip sword trails
HAIRLINE_KINDS = (3, 4, 13, 14)      # 1-pixel strips in the game
MODEL_KIND, LIGHT_KIND = 5, 10
MODEL_NODE_GROUP = "ALBAM_EFL_Models_v4"   # v2: + UV scroll on "uv1"; v3: + scale_after; v4: + EdgeAlpha tint
GAME_TO_BLENDER = Matrix(((1.0, 0.0, 0.0), (0.0, 0.0, -1.0), (0.0, 1.0, 0.0)))   # game Y-up -> Blender Z-up
BLENDER_TO_GAME = GAME_TO_BLENDER.transposed()
MODEL_UV = "uv1"                           # Albam's first .mod UV layer
MAX_LIGHTS = 8                       # light pool per record
LINE_HALF_WIDTH = 0.25       # cm; Line particles are 1-pixel strips in the game
EDGE_ALPHA_ATTR = "EdgeAlpha"
_cache = {}     # object name -> list of efl.sim.Particle
_history = {}   # object name -> {scene frame: generator world Matrix}
_window = {}    # object name -> (first birth, last end) game frames of its particles, or None (it has none)
_topology = {}  # object name -> ribbon layout (point count per ribbon) its mesh was last built with
_frames = {}    # object name -> {scene frame: (inputs signature, mesh payload)}: replays and scrubbing reuse them
MAX_CACHED_FRAMES = 1200   # per object; past it the object's cache starts over


def invalidate():
    """Forget simulated particles (after the stored .efl bytes changed); they're rebuilt on the next frame."""
    _cache.clear()
    _window.clear()
    _frames.clear()


def forget(name):
    """Drop cached state of an object that is about to be removed."""
    _cache.pop(name, None)
    _history.pop(name, None)
    _window.pop(name, None)
    _topology.pop(name, None)
    _frames.pop(name, None)


def forget_history(root):
    """Drop the recorded emitter motion of an effect (its generators' keyframes changed)."""
    for ob in bpy.data.objects:
        if ob.get("efl_root") == root:
            _history.pop(ob.name, None)
            _frames.pop(ob.name, None)


def store_source(root, efl_bytes, start_frame):
    root["efl_data"] = base64.b64encode(efl_bytes).decode("ascii")
    root["efl_start_frame"] = int(start_frame)
    ensure_start_marker(root, bpy.context.scene)


# -- timeline markers ---------------------------------------------------------------------------
# The effect's frame 0 is a timeline marker "<root> start" (drag it to move the effect in time: its objects' keys
# move with it); End Effect is a marker "<root> end" (the preview's stand-in for the owner ending the effect).

START_MARKER = "efl_start_marker"   # effect root: the start marker's name
END_MARKER = "efl_end_marker"       # effect root: the end marker's name (missing marker = the effect never ends)


def _marker(root, key, scene):
    name = root.get(key) if root is not None else None
    return scene.timeline_markers.get(name) if name else None


def ensure_start_marker(root, scene):
    marker = _marker(root, START_MARKER, scene)
    if marker is None:
        name = f"{root.name} start"
        marker = scene.timeline_markers.get(name) or scene.timeline_markers.new(name, frame=int(root["efl_start_frame"]))
        root[START_MARKER] = name
    marker.frame = int(root["efl_start_frame"])
    return marker


def set_end(root, scene, frame):
    """End Effect: put the end marker at a scene frame, or remove it (None)."""
    marker = _marker(root, END_MARKER, scene)
    if frame is None:
        if marker is not None:
            scene.timeline_markers.remove(marker)
        root.pop(END_MARKER, None)
    else:
        if marker is None:
            name = f"{root.name} end"
            marker = scene.timeline_markers.get(name) or scene.timeline_markers.new(name, frame=int(frame))
            root[END_MARKER] = name
        marker.frame = int(frame)
    refresh_root(root, scene)


def end_frame_of(root, scene=None):
    """The scene frame of the effect's end marker, or None."""
    marker = _marker(root, END_MARKER, scene or bpy.context.scene)
    return marker.frame if marker is not None else None


def sync_markers(scene):
    """A dragged start marker moves its effect: the start frame, every key of its objects and its end marker."""
    for root in scene.objects:
        if root.albam_asset.extension != "efl" or START_MARKER not in root:
            continue
        marker = _marker(root, START_MARKER, scene)
        if marker is None:
            continue
        delta = marker.frame - int(root.get("efl_start_frame", marker.frame))
        if delta:
            shift_effect(root, scene, delta)


def shift_effect(root, scene, delta):
    """Move an effect by delta scene frames: its start, its objects' keys and its end marker."""
    from .effect_keys import shift
    root["efl_start_frame"] = int(root.get("efl_start_frame", scene.frame_current)) + delta
    ensure_start_marker(root, scene)
    for ob in bpy.data.objects:
        if ob.get("efl_root") == root:
            shift(ob, delta)
    end = _marker(root, END_MARKER, scene)
    if end is not None:
        end.frame += delta
    forget_history(root)
    refresh_root(root, scene)


def create_sim_object(collection, name, generator, source, root, record_index, info):
    """Points object instancing `source` (hidden). info: dict stored as ob['efl_sim']."""
    mesh = bpy.data.meshes.new(f"{name}_points")
    ob = bpy.data.objects.new(f"{name}_particles", mesh)
    collection.objects.link(ob)
    if info.get("space", SPACE_FOLLOW) == SPACE_FOLLOW:
        ob.parent = generator
    ob["efl_root"] = root
    ob["efl_generator"] = generator
    ob[SIM_KEY] = dict(info, record=record_index, uv_stride=UV_STRIDE)
    modifier = ob.modifiers.new("EFL Particles", "NODES")
    modifier.node_group = _node_group()
    for item in modifier.node_group.interface.items_tree:
        if getattr(item, "in_out", None) == "INPUT" and item.name == "Source":
            modifier[item.identifier] = source
    source.hide_viewport = True
    source.hide_render = True
    update_object(ob, bpy.context.scene)
    return ob


def create_model_object(collection, name, generator, root, record_index, info, source_collection):
    """Points object instancing one mesh of `source_collection` per particle (Model particles)."""
    mesh = bpy.data.meshes.new(f"{name}_points")
    ob = bpy.data.objects.new(f"{name}_particles", mesh)
    collection.objects.link(ob)
    if info.get("space", SPACE_FOLLOW) == SPACE_FOLLOW:
        ob.parent = generator
    ob["efl_root"] = root
    ob["efl_generator"] = generator
    ob[SIM_KEY] = dict(info, record=record_index, uv_stride=UV_STRIDE)
    modifier = ob.modifiers.new("EFL Model Particles", "NODES")
    modifier.node_group = _model_node_group()
    for item in modifier.node_group.interface.items_tree:
        if getattr(item, "in_out", None) == "INPUT" and item.name == "Collection":
            modifier[item.identifier] = source_collection
    update_object(ob, bpy.context.scene)
    return ob


def create_light_object(collection, name, generator, root, record_index, info):
    """A holder Empty with a pool of point lights, re-assigned to the live Light particles every frame."""
    holder = bpy.data.objects.new(f"{name}_lights", None)
    holder.empty_display_type = "SPHERE"
    holder.empty_display_size = 0.05
    collection.objects.link(holder)
    holder["efl_root"] = root
    holder["efl_generator"] = generator
    holder[SIM_KEY] = dict(info, record=record_index, uv_stride=UV_STRIDE)
    peak = 0
    for frame in range(0, info["frames"], 2):
        peak = max(peak, sum(1 for p in _particles(holder) if state_at(p, frame) is not None))
    for i in range(min(max(peak, 1), MAX_LIGHTS)):
        light = bpy.data.lights.new(f"{name}_light{i}", "POINT")
        light_ob = bpy.data.objects.new(light.name, light)
        collection.objects.link(light_ob)
        light_ob.parent = holder
        light_ob["efl_light_slot"] = i
    update_object(holder, bpy.context.scene)
    return holder


def create_line_object(collection, name, generator, root, record_index, info, material):
    """Ribbon object for Polyline/Line particles: its mesh holds each ribbon's points as an edge chain (positions,
    half widths, UVs, colours per point, written every frame), and the Ribbons node group turns them into
    camera-facing strips."""
    mesh = bpy.data.meshes.new(f"{name}_ribbons")
    if material is not None:
        mesh.materials.append(material)
    ob = bpy.data.objects.new(f"{name}_particles", mesh)
    collection.objects.link(ob)
    ob["efl_root"] = root
    ob["efl_generator"] = generator
    ob[SIM_KEY] = dict(info, record=record_index, uv_stride=UV_STRIDE)
    _ensure_ribbon_modifier(ob)
    update_object(ob, bpy.context.scene)
    return ob


def _ensure_ribbon_modifier(ob):
    """The Ribbons node group on a line object (added to objects from before it existed too)."""
    modifier = next((m for m in ob.modifiers if m.type == "NODES" and m.node_group is not None
                     and m.node_group.name == LINE_NODE_GROUP), None)
    if modifier is None:
        for old in [m for m in ob.modifiers if m.type == "NODES"]:
            ob.modifiers.remove(old)
        modifier = ob.modifiers.new("EFL Ribbons", "NODES")
        modifier.node_group = _ribbon_node_group()
        _topology.pop(ob.name, None)   # the mesh holds points now, not strips
    material = ob.data.materials[0] if ob.data.materials else None
    for item in modifier.node_group.interface.items_tree:
        if getattr(item, "in_out", None) == "INPUT" and item.name == LINE_MATERIAL:
            if modifier[item.identifier] != material:
                modifier[item.identifier] = material
            break
    return modifier


def _set_eye(ob, eye):
    """The eye position (object space) the ribbons face, on the modifier."""
    modifier = _ensure_ribbon_modifier(ob)
    for item in modifier.node_group.interface.items_tree:
        if getattr(item, "in_out", None) == "INPUT" and item.name == LINE_EYE:
            if tuple(modifier[item.identifier]) != tuple(eye):
                modifier[item.identifier] = tuple(eye)
            break


def frame_tables(anim, image, anim_flag, ean_module):
    """Per flipbook sequence: (affine ((a, b, off_u), (c, d, off_v)), width px, height px) per pattern."""
    tex_w, tex_h = (image.size[0], image.size[1]) if image is not None and image.size[0] else (64, 64)
    whole = (ean_module.IDENTITY_AFFINE, tex_w, tex_h)
    if anim is None or image is None or not anim.sequences or not image.size[0]:
        return [[whole]]
    return [[(ean_module.uv_affine(p, tex_w, tex_h, anim_flag), abs(p[2]), abs(p[3])) for p in seq.patterns]
            or [whole] for seq in anim.sequences]


def _frame_row(rows, seq_offsets, seq_counts, s):
    """The flipbook row (affine UV + pixel size) of a particle state's frame, with its own random flips applied."""
    seq = min(s.sequence, len(seq_counts) - 1)
    row = rows[seq_offsets[seq] + min(s.pattern, seq_counts[seq] - 1)]
    if not s.flip:
        return row
    row = list(row)
    if s.flip & ANIM_FLIP_U:
        row[0:3] = flip_affine_row(*row[0:3])
    if s.flip & ANIM_FLIP_V:
        row[3:6] = flip_affine_row(*row[3:6])
    return row


def table_info(tables):
    """Flatten frame tables for ob['efl_sim']: UV_STRIDE floats per pattern, plus per-sequence offset and count."""
    flat, offsets, counts = [], [], []
    for seq in tables:
        offsets.append(len(flat) // UV_STRIDE)
        counts.append(len(seq))
        for ((a, b, ou), (c, d, ov)), w, h in seq:
            flat.extend((a, b, ou, c, d, ov, w, h))
    return {"uv": flat, "seq_offsets": offsets, "seq_counts": counts}


# -- playback ---------------------------------------------------------------------------------

_table_cache = {}


def _tables(info, ob=None):
    """(rows of UV_STRIDE floats, seq_offsets, seq_counts, sized) for v3 and the older layouts (cached per object)."""
    if ob is None:
        return _tables_uncached(info)
    key = ob.name
    if key not in _table_cache:
        _table_cache[key] = _tables_uncached(info)
    return _table_cache[key]


def _tables_uncached(info):
    if info.get("uv_stride") == UV_STRIDE:
        flat = list(info["uv"])
        rows = [flat[i:i + UV_STRIDE] for i in range(0, len(flat), UV_STRIDE)]
        return rows, list(info["seq_offsets"]), list(info["seq_counts"]), True
    if "seq_counts" in info:   # v2: 6 floats per pattern, source quads already sized
        flat = list(info["uv"])
        rows = [flat[i:i + 6] + [1.0, 1.0] for i in range(0, len(flat), 6)]
        return rows, list(info["seq_offsets"]), list(info["seq_counts"]), False
    old = list(info["rects"])  # v1: (off_u, off_v, scale_u, scale_v), one sequence
    rows = [[old[i + 2], 0.0, old[i], 0.0, old[i + 3], old[i + 1], 1.0, 1.0] for i in range(0, len(old), 4)]
    return rows, [0], [len(rows)], False


def sim_length(ob, scene=None):
    """Game frames simulated for a particle system: up to the scene's end frame (at least one frame)."""
    scene = scene or bpy.context.scene
    start, rate = _start_and_rate(ob, scene)
    return max(int(math.floor((scene.frame_end - start) * rate)) + 1, 1)


def _particles(ob):
    scene = bpy.context.scene
    root = ob.get("efl_root")
    key = (sim_length(ob, scene), end_game_frame(root, scene) if root is not None else None)
    cached = _cache.get(ob.name)
    if cached is not None and cached[0] == key:
        return cached[1]
    particles = []
    info = ob.get(SIM_KEY)
    if info and root is not None and root.get("efl_data"):
        try:
            efl = EffectList.from_bytes(base64.b64decode(root["efl_data"]))
            record = efl.records[info["record"]]
            strip = info.get("strip")
            strip_points = [tuple(strip[i:i + 3]) for i in range(0, len(strip), 3)] if strip else None
            range_strip = range_normals = None
            if info.get("range_strip"):
                sizes = list(info["range_strip_sizes"])
                range_strip = _unflatten(info["range_strip"], sizes)
                if info.get("range_strip_normals"):
                    range_normals = _unflatten(info["range_strip_normals"], sizes)
            particles = simulate(record, seed=info["record"], max_frames=key[0],
                                 pat_counts=list(_tables(info, ob)[2]), strip_points=strip_points,
                                 range_strip=range_strip, ground_y=info.get("ground_y"),
                                 world_axes=info.get("world_axes"), end_frame=key[1],
                                 range_normals=range_normals, down=info.get("down"))
        except Exception as err:   # a broken record must not break playback of the rest
            print(f"EFL: simulation failed for {ob.name}: {err}")
    for particle in particles:   # life window, to skip state_at for particles not alive at a frame
        particle.end = particle.birth + particle.lifetime()
    _cache[ob.name] = (key, particles)
    _frames.pop(ob.name, None)   # results of the previous simulation
    _window[ob.name] = (min(p.birth for p in particles), max(p.end for p in particles)) if particles else None
    return particles


def _unflatten(flat, sizes):
    """Per part, its points from a flat [x, y, z, ...] list."""
    flat, out, at = list(flat), [], 0
    for size in sizes:
        out.append([tuple(flat[at + 3 * i:at + 3 * i + 3]) for i in range(size)])
        at += 3 * size
    return out


def _alive_states(ob, frame):
    if frame < 0:
        return []
    particles = _particles(ob)
    window = _window.get(ob.name)
    if window is None or not window[0] <= frame < window[1]:   # nothing of this system is alive now
        return []
    out = []
    for p in particles:
        if p.birth <= frame < p.end:
            s = state_at(p, frame)
            if s is not None:
                out.append((p, s))
    return out


def end_game_frame(root, scene=None):
    """Game frame (from the effect's start) at which the preview ends the effect (the end marker), or None."""
    scene = scene or bpy.context.scene
    end = end_frame_of(root, scene)
    if end is None:
        return None
    fps = scene.render.fps / (scene.render.fps_base or 1.0)
    start = root.get("efl_start_frame", scene.frame_start)
    return max(int(math.floor((end - start) * GAME_FPS / fps)), 0)


def refresh_root(root, scene):
    """Re-simulate and redraw one effect's particles (after a preview setting changed)."""
    for ob in _sim_objects(scene):
        if ob.get("efl_root") == root:
            _cache.pop(ob.name, None)
            _frames.pop(ob.name, None)
            update_object(ob, scene)


def _start_and_rate(ob, scene):
    root = ob.get("efl_root")
    start = root.get("efl_start_frame", scene.frame_start) if root is not None else scene.frame_start
    fps = scene.render.fps / (scene.render.fps_base or 1.0)
    return start, GAME_FPS / fps


def _game_frame(ob, scene):
    start, rate = _start_and_rate(ob, scene)
    return int(math.floor((scene.frame_current - start) * rate))


def _disperse_shift(ob, scene, p, gen_now, birth_m):
    """RangeDisperseType (calcSpawnOffset 0x998F00): the game adds (previous generator position - current) x i / count
    to the particle's local spawn offset, which the generator's matrix then turns and scales like the rest of it. The
    previous position is the generator one game frame before the birth (recorded emitter motion; nothing without it)."""
    _start, rate = _start_and_rate(ob, scene)
    previous = _birth_matrix(ob, scene, p.birth - max(rate, 1.0), gen_now)
    delta = BLENDER_TO_GAME @ ((previous.translation - birth_m.translation) / (SCALE * max(rate, 1.0)))
    return birth_m.to_3x3() @ (delta * (p.disperse * SCALE))


def _birth_matrix(ob, scene, birth, current):
    """Generator world matrix at a particle's birth: recorded history, else the current one."""
    history = _history.get(ob.name)
    if not history:
        return current
    start, rate = _start_and_rate(ob, scene)
    frame = start + int(math.floor(birth / rate))
    if frame in history:
        return history[frame]
    earlier = [f for f in history if f <= frame]
    return history[max(earlier)] if earlier else current


def _idle(ob, scene):
    """True when nothing of a mesh-drawn system is alive at this frame and its mesh is already empty: the update
    can be skipped (long timelines with many effects mostly hold idle systems)."""
    if ob.type != "MESH" or len(ob.data.vertices):
        return False
    _particles(ob)
    window = _window.get(ob.name)
    frame = _game_frame(ob, scene)
    return window is None or not window[0] <= frame < window[1]


def _signature(ob, scene, info):
    """What a system's mesh at the current frame depends on besides its simulation: the game frame, the generator's
    and the object's transforms, and the camera for camera-facing systems (the recorded emitter motion is handled
    where it's recorded). Two visits with the same signature draw the same mesh. The matrices are compared exactly
    (mathutils' own comparison: rounding them in Python was a third of a replayed frame)."""
    generator = ob.get("efl_generator")
    # ribbons face the eye through their node group (the Eye input is set on every update), so without a culling
    # fade their payload doesn't depend on the camera
    depends = _camera_dependent(ob) and not (info["kind"] in LINE_KINDS and info.get("culling") is None)
    camera = _camera_matrix(scene) if depends else None
    return (_game_frame(ob, scene), generator.matrix_world if generator is not None else None,
            ob.matrix_world, ob.matrix_parent_inverse.copy(), camera)


def update_object(ob, scene):
    info = ob[SIM_KEY]
    if info["kind"] != LIGHT_KIND and _idle(ob, scene):
        return
    if info["kind"] == LIGHT_KIND:
        _update_lights(ob, scene, info)
        return
    if info["kind"] not in LINE_KINDS + STRIP_KINDS and info.get("space", SPACE_FOLLOW) == SPACE_FOLLOW:
        generator = ob.get("efl_generator")   # keeps matrix_parent_inverse right on cache hits too
        _cancel_generator_scale(ob, generator, generator.matrix_world.copy() if generator is not None
                                else ob.matrix_world.copy())
    _particles(ob)   # a new simulation drops the object's cached frames
    signature = _signature(ob, scene, info)
    cached = _frames.setdefault(ob.name, {})
    hit = cached.get(scene.frame_current)
    if hit is not None and hit[0] == signature:
        payload = hit[1]
    else:
        if info["kind"] in STRIP_KINDS:
            payload = _update_strips(ob, scene, info)
        elif info["kind"] in LINE_KINDS:
            payload = _update_lines(ob, scene, info)
        else:
            payload = _point_payload(ob, scene, info)
        if len(cached) >= MAX_CACHED_FRAMES:
            cached.clear()
        cached[scene.frame_current] = (signature, payload)
    if info["kind"] in LINE_KINDS:
        _write_line_points(ob, payload)
        camera = _camera_matrix(scene)
        to_local = ob.matrix_world.inverted()
        _set_eye(ob, to_local @ (camera.translation if camera is not None else Vector((0.0, 0.0, 1.0e6))))
    elif info["kind"] in STRIP_KINDS:
        _write_ribbons(ob, *payload)
    else:
        _write_points(ob, payload)


def _point_payload(ob, scene, info):
    """The point attributes of an instanced system (Billboard / Polygon / PrimModel / Model) at the current frame:
    {attribute: (domain type, array)} plus "co" and the point count."""
    rows, seq_offsets, seq_counts, sized = _tables(info, ob)
    v3 = ob.modifiers and ob.modifiers[0].type == "NODES" and ob.modifiers[0].node_group is not None and \
        ob.modifiers[0].node_group.name.startswith(TINT_GROUPS)
    frame = _game_frame(ob, scene)
    alive = _alive_states(ob, frame)

    kind = info["kind"]
    space = info.get("space", SPACE_FOLLOW)
    order = ROT_ORDERS[info["rot_order"]] if 0 <= info["rot_order"] < len(ROT_ORDERS) else "XYZ"
    unit = info["particle_scale"]
    generator = ob.get("efl_generator")
    gen_now = generator.matrix_world.copy() if generator is not None else ob.matrix_world.copy()
    gen_scale = _cancel_generator_scale(ob, generator, gen_now) if space == SPACE_FOLLOW else None
    size_k = _world_scale(info, gen_now)
    # identity for unparented (world-space) objects; follow objects: the generator without its scale
    to_local = (gen_now @ ob.matrix_parent_inverse if gen_scale is not None else ob.matrix_world).inverted()
    to_local_rot = to_local.to_quaternion()
    camera = _camera_matrix(scene)
    cam_world = camera.translation if camera is not None else None
    cam_rot = camera.to_quaternion() if camera is not None else Quaternion()

    co, rot, scale, alpha, tint, uv_u, uv_v, off, sc, part = [], [], [], [], [], [], [], [], [], []
    shape, shape_w, shape_on, scroll, after, after_rot = [], [], [], [], [], []
    place_tint, place_alpha = [], []
    culling = _Culling(info, gen_now, cam_world)
    groups = list(info.get("model_groups", []))
    orient = info.get("orient") if kind in (2, 5, 6) else None
    zofs = info.get("model_zofs", 0.0) * SCALE
    for p, s in alive:
        local = Vector(s.pos) * SCALE
        if space == SPACE_FOLLOW:
            world_m = gen_now
            pos_world = gen_now @ local
            # the generator's scale moves the spawn points (initParticle: mWmat . (mLscale * offset)), not the sizes
            pos = Vector([c * k for c, k in zip(local, gen_scale)]) if gen_scale is not None else local
        else:   # anchor None = riding a path in the current generator space
            world_m = gen_now if s.anchor is None else _birth_matrix(ob, scene, s.anchor, gen_now)
            pos_world = world_m @ local
            if p.disperse and s.anchor is not None:
                pos_world = pos_world + _disperse_shift(ob, scene, p, gen_now, world_m)
            if space == SPACE_FOLLOW_TRANSLATION:
                pos_world = pos_world + (gen_now.translation - world_m.translation)
            pos = to_local @ pos_world
        if zofs and cam_world is not None:   # ModelZofs: push along camera -> particle
            pos_world = pos_world + (pos_world - cam_world).normalized() * zofs
            pos = to_local @ pos_world
        co.extend(pos)
        after.extend((1.0, 1.0, 1.0))
        after_rot.extend((0.0, 0.0, 0.0))
        if groups:   # Model: first mesh whose idx_group matches the part number, else mesh 0
            part.append(groups.index(s.pattern) if s.pattern in groups else 0)

        row = _frame_row(rows, seq_offsets, seq_counts, s)
        if kind == 0:   # screen-aligned: the vertex shader expands the quad along the camera's right / up axes
            q = to_local_rot @ cam_rot @ Quaternion((0.0, 0.0, 1.0), s.angle)
            rot.extend(q.to_euler("XYZ"))
            size = s.scale * unit * size_k
            if sized:   # 1 cm source quad: width = S * pattern w * aspect, height = S * pattern h
                scale.extend((size * row[6] * s.aspect, size * row[7], 1.0))
            else:
                scale.extend((size,) * 3)
        elif orient is not None:   # Model / PrimModel: calcParticleMatrix; Polygon: sub_988B00 (same rules)
            full, outer, mirror = _model_rotation(ob, scene, p, s, frame, order, orient, gen_now, world_m, space,
                                                  cam_rot if camera is not None else None)
            r = to_local_rot.to_matrix() @ full
            rot.extend(r.to_euler("XYZ"))
            if orient["after"]:   # ModelScale along the frame the generator / alignment / view basis set up
                scale.extend((s.scale * unit * size_k,) * 3)
                after[-3:] = list(s.model_scale)
                after_rot[-3:] = list((to_local_rot.to_matrix() @ outer).to_euler("XYZ"))
            else:
                scale.extend(m * s.scale * unit * size_k for m in s.model_scale)
                if mirror is not None:   # billboard modes 2-4: the game's view basis mirrors one of its axes
                    after[-3:] = [-1.0 if i == mirror[1] else 1.0 for i in range(3)]
                    after_rot[-3:] = list((to_local_rot.to_matrix() @ mirror[0]).to_euler("XYZ"))
        else:
            r = Euler(s.rot, order).to_matrix().to_4x4()
            if space != SPACE_FOLLOW:   # carry the birth-frame generator rotation into world space
                r = to_local @ Matrix.LocRotScale(None, world_m.to_quaternion(), None) @ r
            rot.extend(r.to_euler("XYZ"))
            scale.extend((s.scale * unit * size_k,) * 3)
        fade = culling.fade(pos_world)
        alpha.append((s.alpha * s.color[3] if v3 else s.alpha) * fade)
        place = s.place_color if s.place_color is not None else s.color   # PrimModel colour B (gradient rows)
        place_tint.extend(place[:3])
        place_alpha.append(s.alpha * place[3] * fade)
        if s.shape is not None:   # node group rebuilds the source as sum(basis * shape)
            shape.extend(s.shape[:3])
            shape_w.append(s.shape[3])
            shape_on.append(1.0)
        else:
            shape.extend((0.0, 0.0, 0.0))
            shape_w.append(0.0)
            shape_on.append(0.0)
        scroll.extend((s.uv_scroll[0], -s.uv_scroll[1], 0.0) if s.uv_scroll is not None else (0.0, 0.0, 0.0))
        tint.extend(s.color[:3])
        a, b, ou, c, d, ov = row[:6]
        uv_u.extend((a, b, ou))
        uv_v.extend((c, d, ov))
        off.extend((ou, ov, 0.0))   # v1 node groups: axis-aligned cells only
        sc.extend((a, d, 1.0))

    floats = lambda values: array("f", values)   # noqa: E731 (compact: the payload may be cached per frame)
    attributes = [(name, kind_, floats(values)) for name, kind_, values in (
        ("rot", "FLOAT_VECTOR", rot), ("scale3", "FLOAT_VECTOR", scale), ("tint", "FLOAT_VECTOR", tint),
        ("uv_u", "FLOAT_VECTOR", uv_u), ("uv_v", "FLOAT_VECTOR", uv_v),
        ("uv_off", "FLOAT_VECTOR", off), ("uv_scale", "FLOAT_VECTOR", sc),
        ("alpha", "FLOAT", alpha), ("shape", "FLOAT_VECTOR", shape),
        ("shape_w", "FLOAT", shape_w), ("shape_on", "FLOAT", shape_on),
        ("uv_scroll", "FLOAT_VECTOR", scroll), ("scale_after", "FLOAT_VECTOR", after),
        ("after_rot", "FLOAT_VECTOR", after_rot),
        ("place_tint", "FLOAT_VECTOR", place_tint), ("place_alpha", "FLOAT", place_alpha))]
    co = floats(co)
    attributes.append(("p_center", "FLOAT_VECTOR", co))
    return {"count": len(alive), "co": co, "attributes": attributes,
            "part": array("i", part) if groups else None}


def _write_points(ob, payload):
    """Write an instanced system's points from a payload (_point_payload)."""
    mesh = ob.data
    if len(mesh.vertices) != payload["count"]:
        mesh.clear_geometry()
        mesh.vertices.add(payload["count"])
    mesh.vertices.foreach_set("co", payload["co"])
    for name, kind_, values in payload["attributes"]:
        attr = mesh.attributes.get(name) or mesh.attributes.new(name, kind_, "POINT")
        attr.data.foreach_set("vector" if kind_ == "FLOAT_VECTOR" else "value", values)
    if payload["part"] is not None:
        attr = mesh.attributes.get("instance_index") or mesh.attributes.new("instance_index", "INT", "POINT")
        attr.data.foreach_set("value", payload["part"])
    mesh.update()


def _update_lights(holder, scene, info):
    """Assign live Light particles to the pooled point lights (position, colour, radius)."""
    frame = _game_frame(holder, scene)
    space = info.get("space", SPACE_FOLLOW)
    generator = holder.get("efl_generator")
    gen_now = generator.matrix_world.copy() if generator is not None else Matrix.Identity(4)
    unit = info["particle_scale"]
    lights = sorted((c for c in holder.children if c.type == "LIGHT"), key=lambda c: c.get("efl_light_slot", 0))
    states = [s for _p, s in _alive_states(holder, frame) if s.light is not None]
    for i, light_ob in enumerate(lights):
        light = light_ob.data
        if i >= len(states):
            light.energy = 0.0
            continue
        s = states[i]
        m = gen_now if space == SPACE_FOLLOW or s.anchor is None else _birth_matrix(holder, scene, s.anchor, gen_now)
        light_ob.matrix_world = Matrix.Translation(m @ (Vector(s.pos) * SCALE))
        start, end = (r * SCALE * unit * _world_scale(info, gen_now) for r in s.light)
        rgb = s.color[:3]
        peak = max(max(rgb), 1e-6)
        light.color = tuple(c / peak for c in rgb)
        # game falloff is linear from start to end; approximate the reach with inverse-square power
        light.energy = 40.0 * peak * s.alpha * max(end, 0.05) ** 2
        light.shadow_soft_size = max(start * 0.1, 0.01)
        if hasattr(light, "use_custom_distance"):
            light.use_custom_distance = True
            light.cutoff_distance = max(end, 0.01)


def _update_lines(ob, scene, info):
    """The ribbons' points at this frame (object space), one edge chain per ribbon, with per point the half width,
    the UVs of the left and right edge (u across the strip, v along it: head v = 1; Texline keeps u fixed, its
    texture runs along the line) and the colour (gradient x alpha). The Ribbons node group builds the camera-facing
    strip: each point moves +/- half along normalize((next - previous) x (eye - point))."""
    rows, seq_offsets, seq_counts, _sized = _tables(info, ob)
    frame = _game_frame(ob, scene)
    space = info.get("space", SPACE_FOLLOW)
    generator = ob.get("efl_generator")
    gen_now = generator.matrix_world.copy() if generator is not None else Matrix.Identity(4)
    to_local = ob.matrix_world.inverted()
    camera = _camera_matrix(scene)
    cam = camera.translation if camera is not None else None
    unit = info["particle_scale"] * _world_scale(info, gen_now)
    hairline = info["kind"] in HAIRLINE_KINDS
    across = 0.0 if info["kind"] in (3, 13) else None

    verts, edges, halves, uv_l, uv_r, colors, layout = [], [], [], [], [], [], []
    culling = _Culling(info, gen_now, cam)
    u_left, u_right = (0.0, 1.0) if across is None else (across, across)
    for p, s in _alive_states(ob, frame):
        if not s.line:
            continue
        line = s.line
        if info.get("ext_line_pos"):   # ParticleOptionFlag 0x20000
            span = ext_line_range([q for q, *_ in line])
            if span is None:
                continue
            line = line[span[0]:span[1] + 1]
        last = len(line) - 1
        if last < 1:
            continue
        a, b, ou, c, d, ov = _frame_row(rows, seq_offsets, seq_counts, s)[:6]
        first = gen_now if space == SPACE_FOLLOW or line[0][1] is None else _birth_matrix(ob, scene, line[0][1], gen_now)
        fade = culling.fade(first @ (Vector(line[0][0]) * SCALE))
        base = len(halves)
        layout.append(len(line))
        for i, (q, anchor, width, rgba) in enumerate(line):
            m = gen_now if space == SPACE_FOLLOW or anchor is None else _birth_matrix(ob, scene, anchor, gen_now)
            verts.extend(to_local @ (m @ (Vector(q) * SCALE)))
            halves.append(LINE_HALF_WIDTH * SCALE if hairline else width * SCALE * unit)
            v = 1.0 - i / last
            uv_l.extend((a * u_left + b * v + ou, c * u_left + d * v + ov))
            uv_r.extend((a * u_right + b * v + ou, c * u_right + d * v + ov))
            colors.extend((rgba[0], rgba[1], rgba[2], rgba[3] * s.alpha * fade))
            if i:
                edges.append((base + i - 1, base + i))
    return (array("f", verts), edges, array("f", halves), array("f", uv_l), array("f", uv_r), array("f", colors),
            ("line", tuple(layout)))


def _write_line_points(ob, payload):
    """Write a line object's points (_update_lines): the chains are rebuilt when the layout changed, else every
    attribute is written in place."""
    verts, edges, halves, uv_l, uv_r, colors, layout = payload
    mesh = ob.data
    count = len(halves)
    if _topology.get(ob.name) != layout or len(mesh.vertices) != count or len(mesh.edges) != len(edges):
        mesh.clear_geometry()
        mesh.from_pydata([verts[i:i + 3] for i in range(0, len(verts), 3)], edges, [])
        _topology[ob.name] = layout
    elif count:
        mesh.vertices.foreach_set("co", verts)
    if count:
        attr = mesh.attributes.get("half") or mesh.attributes.new("half", "FLOAT", "POINT")
        attr.data.foreach_set("value", halves)
        for name, values in (("uv_l", uv_l), ("uv_r", uv_r)):
            attr = mesh.attributes.get(name) or mesh.attributes.new(name, "FLOAT2", "POINT")
            attr.data.foreach_set("vector", values)
        attr = mesh.color_attributes.get(EDGE_ALPHA_ATTR) or \
            mesh.color_attributes.new(name=EDGE_ALPHA_ATTR, type="FLOAT_COLOR", domain="POINT")
        attr.data.foreach_set("color", colors)
    mesh.update()


def _cancel_generator_scale(ob, generator, gen_now):
    """Follow-space points objects sit in the generator's frame without its scale (matrix_parent_inverse = the
    inverse scale), so the instances aren't stretched by it; returns the scale, which the caller applies to the point
    positions. The game sizes particles from Generator+0x40 / +0x150 (updateWorldMatrix 0x96E832): ParticleScale x the
    effect's scale, x the generator's world scale only with World Scale (ParticleOptionFlag 0x200)."""
    if generator is None or ob.parent != generator:
        return None
    scale = gen_now.to_scale()
    scale = Vector([c if abs(c) > 1e-8 else 1e-8 for c in scale])
    inverse = Matrix.Diagonal((1.0 / scale.x, 1.0 / scale.y, 1.0 / scale.z, 1.0))
    if any(abs(a - b) > 1e-7 for row_a, row_b in zip(ob.matrix_parent_inverse, inverse) for a, b in zip(row_a, row_b)):
        ob.matrix_parent_inverse = inverse
    return scale


def _world_scale(info, gen_now):
    """Size factor of World Scale (ParticleOptionFlag 0x200 WMAT_SCALE): the mean of the generator's world scale, as the
    game's Generator+0x40 (updateWorldMatrix 0x96E86D: (sx + sy + sz) / 3); 1 without it."""
    if not info.get("world_scale"):
        return 1.0
    return sum(gen_now.to_scale()) / 3.0


def _ribbon_payload(verts, faces, uvs, colors, layout):
    """A ribbon / trail mesh as compact arrays (cached per frame by update_object). The UVs are per loop, in the
    order the faces list their vertices (from_pydata keeps it), so a write needs no lookup of the mesh's loops."""
    return (array("f", [c for v in verts for c in v]), faces,
            array("f", [c for face in faces for i in face for c in uvs[i]]),
            array("f", [c for col in colors for c in col]), layout)


def _write_ribbons(ob, verts, faces, uvs, colors, layout):
    """Write a ribbon / trail mesh (_ribbon_payload). When its layout (the point count of every ribbon) is the one
    the mesh already has, only the positions, UVs and colours change: they're written in place instead of
    rebuilding the mesh."""
    mesh = ob.data
    count = len(verts) // 3
    same = _topology.get(ob.name) == layout and len(mesh.vertices) == count and len(mesh.polygons) == len(faces)
    if same:
        mesh.vertices.foreach_set("co", verts)
    else:
        mesh.clear_geometry()
        mesh.from_pydata([verts[i:i + 3] for i in range(0, len(verts), 3)], [], faces)
        _topology[ob.name] = layout
    uv_layer = mesh.uv_layers.get("UVMap") or mesh.uv_layers.new(name="UVMap")
    if len(uvs) and len(uvs) == 2 * len(mesh.loops):   # per-loop UVs (_ribbon_payload)
        uv_layer.data.foreach_set("uv", uvs)
    attr = mesh.color_attributes.get(EDGE_ALPHA_ATTR) or \
        mesh.color_attributes.new(name=EDGE_ALPHA_ATTR, type="FLOAT_COLOR", domain="POINT")
    if len(colors):
        attr.data.foreach_set("color", colors)
    mesh.update()


def _catmull_rom(points, divisions):
    """Uniform Catmull-Rom through points (ends extrapolated), `divisions` pieces per segment."""
    if len(points) < 3 or divisions <= 1:
        return list(points)
    ext = [2 * points[0] - points[1]] + list(points) + [2 * points[-1] - points[-2]]
    out = []
    for k in range(1, len(ext) - 2):
        p0, p1, p2, p3 = ext[k - 1], ext[k], ext[k + 1], ext[k + 2]
        for j in range(divisions):
            t = j / divisions
            t2, t3 = t * t, t * t * t
            out.append(0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2 +
                              (-p0 + 3 * p1 - 3 * p2 + p3) * t3))
    out.append(points[-1])
    return out


def _update_strips(ob, scene, info):
    """PolygonStrip sword trails: world-space quads between the A and B edge histories, texture stretched once."""
    rows, seq_offsets, seq_counts, _sized = _tables(info, ob)
    frame = _game_frame(ob, scene)
    space = info.get("space", SPACE_FOLLOW)
    generator = ob.get("efl_generator")
    gen_now = generator.matrix_world.copy() if generator is not None else Matrix.Identity(4)
    to_local = ob.matrix_world.inverted()

    verts, faces, uvs, colors, layout = [], [], [], [], []
    camera = _camera_matrix(scene)
    culling = _Culling(info, gen_now, camera.translation if camera is not None else None)
    orient = info.get("orient") or {}
    unit = info["particle_scale"] * _world_scale(info, gen_now)
    for p, s in _alive_states(ob, frame):
        if not s.strip:
            continue
        edges, head, tail, divisions, axis, order, pivot = s.strip
        a_pts, b_pts = [], []
        for i, e in enumerate(edges):
            # the trail is a world-space history: each edge pair was built with the generator of its own tick
            tick = p.birth + e.age
            m_tick = gen_now if e.age == frame - p.birth else _birth_matrix(ob, scene, tick, gen_now)
            m_pos = m_tick if space == SPACE_FOLLOW or e.anchor is None else \
                _birth_matrix(ob, scene, p.birth + e.anchor, gen_now)
            point = m_pos @ (Vector(e.pos) * SCALE)
            later = edges[i - 1] if i else None
            r = _strip_rotation(ob, scene, p, e, later, order, orient, m_tick, m_pos, space)
            span = r @ (Vector(axis) * (e.scale * unit * SCALE))
            a_pts.append(point + span * (e.width * (1.0 - pivot)))
            b_pts.append(point - span * (e.width * pivot))
        if len(a_pts) < 2:
            continue
        a_pts, b_pts = _catmull_rom(a_pts, divisions), _catmull_rom(b_pts, divisions)
        lengths = [0.0]
        for i in range(1, len(a_pts)):
            lengths.append(lengths[-1] + ((a_pts[i] - a_pts[i - 1]).length + (b_pts[i] - b_pts[i - 1]).length) / 2)
        total = lengths[-1] or 1.0
        ra, rb, ou, rc, rd, ov = _frame_row(rows, seq_offsets, seq_counts, s)[:6]
        fade = culling.fade((a_pts[0] + b_pts[0]) / 2)
        base = len(verts)
        layout.append(len(a_pts))
        for i, (pa, pb) in enumerate(zip(a_pts, b_pts)):
            t = lengths[i] / total
            color = tuple(h + (tl - h) * t for h, tl in zip(head, tail))
            for k, point in enumerate((pa, pb)):
                verts.append(to_local @ point)
                u, v = t, 1.0 - k      # cell-local: along, A edge on top
                uvs.append((ra * u + rb * v + ou, rc * u + rd * v + ov))
                colors.append((color[0], color[1], color[2], color[3] * s.alpha * fade))
            if i:
                j = base + 2 * i
                faces.append((j - 2, j, j + 1, j - 1))

    return _ribbon_payload(verts, faces, uvs, colors, ("strip", tuple(layout)))


# -- facing the viewport ----------------------------------------------------------------------------------
# Camera-facing particles (billboards, ribbons, billboard modes) and the culling fade use the scene camera. With Face
# Viewport on, a timer follows the largest 3D viewport's view instead and redraws them when it turns (the scene
# camera is still used while rendering).

_view = {"on": False, "matrix": None}


def _camera_matrix(scene):
    """World matrix of the eye the preview faces: the followed viewport's, else the scene camera's, else None."""
    if _view["on"] and _view["matrix"] is not None and not _rendering():
        return _view["matrix"]
    return scene.camera.matrix_world.copy() if scene.camera is not None else None


def _rendering():
    try:
        return bpy.app.is_job_running("RENDER")
    except Exception:
        return False


def _viewport_matrix():
    """The eye of the largest 3D viewport (its camera when looking through it), or None."""
    best, size = None, -1
    for window in getattr(bpy.context.window_manager, "windows", []):
        for area in window.screen.areas:
            if area.type != "VIEW_3D" or area.width * area.height <= size:
                continue
            space = area.spaces.active
            region = getattr(space, "region_3d", None)
            if region is None:
                continue
            if region.view_perspective == "CAMERA":
                camera = space.camera or window.scene.camera
                best = camera.matrix_world.copy() if camera is not None else None
            else:
                best = region.view_matrix.inverted()
            size = area.width * area.height
    return best


def _camera_dependent(ob):
    info = ob[SIM_KEY]
    kind = info["kind"]
    orient = info.get("orient") or {}
    return kind == 0 or kind in LINE_KINDS or info.get("culling") is not None or orient.get("billboard") or \
        info.get("model_zofs")


def _viewport_tick():
    if not _view["on"]:
        return None
    matrix = _viewport_matrix()
    old = _view["matrix"]
    changed = matrix is not None and (old is None or any(
        abs(a - b) > 1e-5 for row_a, row_b in zip(matrix, old) for a, b in zip(row_a, row_b)))
    if changed:
        _view["matrix"] = matrix
        scene = bpy.context.scene
        for ob in _sim_objects(scene):
            if _camera_dependent(ob):
                try:
                    update_object(ob, scene)
                except Exception as err:
                    print(f"EFL: particle update failed for {ob.name}: {err}")
    return 0.1


def set_face_viewport(on):
    """Turn Face Viewport on or off (a 0.1 s timer while on)."""
    _view["on"] = bool(on)
    _view["matrix"] = None
    if on and not bpy.app.timers.is_registered(_viewport_tick):
        bpy.app.timers.register(_viewport_tick, first_interval=0.1, persistent=True)
    if not on:
        scene = bpy.context.scene
        for ob in _sim_objects(scene):
            if _camera_dependent(ob):
                update_object(ob, scene)


def _sim_objects(scene):
    # objects hidden by the spawn filter (effect_filter.py) are skipped; it updates them when they're shown again
    return [ob for ob in scene.objects if SIM_KEY in ob and ob.type in ("MESH", "EMPTY")
            and "efl_filter_hidden" not in ob]


@persistent
def _on_frame_change(scene, depsgraph=None):
    try:
        sync_markers(scene)
    except Exception as err:
        print(f"EFL: marker sync failed: {err}")
    for ob in _sim_objects(scene):
        try:
            update_object(ob, scene)
        except Exception as err:
            print(f"EFL: particle update failed for {ob.name}: {err}")


@persistent
def _on_frame_change_post(scene, depsgraph=None):
    """Record generator world matrices for world-space emission and sword-trail histories."""
    for ob in _sim_objects(scene):
        if ob[SIM_KEY].get("space", SPACE_FOLLOW) == SPACE_FOLLOW and ob[SIM_KEY]["kind"] not in STRIP_KINDS:
            continue
        generator = ob.get("efl_generator")
        if generator is not None:
            history = _history.setdefault(ob.name, {})
            frame, matrix = scene.frame_current, generator.matrix_world.copy()
            if history.get(frame) != matrix:   # later frames computed without (or with another) motion are stale
                cached = _frames.get(ob.name)
                if cached:
                    for later in [f for f in cached if f > frame]:
                        del cached[later]
            history[frame] = matrix


@persistent
def _on_load(_dummy=None):
    _cache.clear()
    _window.clear()
    _table_cache.clear()
    _history.clear()
    _view["on"], _view["matrix"] = False, None
    bpy.app.timers.register(_restore_face_viewport, first_interval=0.5)   # bpy.data may be restricted here


def _restore_face_viewport():
    try:
        if bpy.context.scene.albam.efl_editor.face_viewport:
            set_face_viewport(True)
    except Exception:
        pass
    return None


@blender_registry.register_blender_type
class ALBAM_OT_EflRecordMotion(bpy.types.Operator):
    """Step through the effects' frame range once, recording where each emitter is on every frame, so particles
    that stay where they were emitted and sword trails show correctly when you jump or scrub to a frame (playing
    the timeline forward records it too). Run it again after changing the animation"""
    bl_idname = "albam.efl_record_motion"
    bl_label = "Record Emitter Motion"

    def execute(self, context):
        scene = context.scene
        objects = [ob for ob in _sim_objects(scene) if ob[SIM_KEY].get("space", SPACE_FOLLOW) != SPACE_FOLLOW
                   or ob[SIM_KEY]["kind"] in STRIP_KINDS]
        if not objects:
            self.report({"INFO"}, "No effect particles in the scene need emitter motion")
            return {"CANCELLED"}
        current = scene.frame_current
        first = min(_start_and_rate(ob, scene)[0] for ob in objects)
        last = max(scene.frame_end, first)
        for frame in range(first, last + 1):
            scene.frame_set(frame)
        scene.frame_set(current)
        self.report({"INFO"}, f"Recorded frames {first}-{last} for {len(objects)} particle systems")
        return {"FINISHED"}


def register_handlers():
    for handlers, fn in ((bpy.app.handlers.frame_change_pre, _on_frame_change),
                         (bpy.app.handlers.frame_change_post, _on_frame_change_post),
                         (bpy.app.handlers.load_post, _on_load)):
        if fn not in handlers:
            handlers.append(fn)


def unregister_handlers():
    for handlers, fn in ((bpy.app.handlers.frame_change_pre, _on_frame_change),
                         (bpy.app.handlers.frame_change_post, _on_frame_change_post),
                         (bpy.app.handlers.load_post, _on_load)):
        for handler in list(handlers):
            if getattr(handler, "__name__", "") == fn.__name__ and \
                    getattr(handler, "__module__", "") == fn.__module__:
                handlers.remove(handler)


# -- node groups ------------------------------------------------------------------------------

def _after_scale(nodes, links, geometry):
    """ParticleOptionFlag 0x40000 (MDLSCL_AFTER, calcParticleMatrix 0x98B094): the particle matrix is R . S instead of
    S . R (row vectors) before the generator basis, i.e. G . S . R in column form: ModelScale applies after Rot, along
    the axes of G (generator rotation, alignment or none, times the view basis), given per point as the Euler after_rot:
    position = p_center + F (scale_after * F^-1 (position - p_center)) ((1, 1, 1) / identity otherwise)."""
    def attr(name):
        n = nodes.new("GeometryNodeInputNamedAttribute")
        n.data_type = "FLOAT_VECTOR"
        n.inputs["Name"].default_value = name
        return n.outputs["Attribute"]

    def math(operation, a, b):
        n = nodes.new("ShaderNodeVectorMath")
        n.operation = operation
        links.new(a, n.inputs[0])
        links.new(b, n.inputs[1])
        return n.outputs["Vector"]

    def turn(vector, invert):
        n = nodes.new("ShaderNodeVectorRotate")
        n.rotation_type = "EULER_XYZ"
        n.invert = invert
        links.new(vector, n.inputs["Vector"])
        links.new(attr("after_rot"), n.inputs["Rotation"])
        return n.outputs["Vector"]

    center = attr("p_center")
    offset = math("SUBTRACT", nodes.new("GeometryNodeInputPosition").outputs["Position"], center)
    moved = math("ADD", center, turn(math("MULTIPLY", turn(offset, True), attr("scale_after")), False))
    set_pos = nodes.new("GeometryNodeSetPosition")
    links.new(geometry, set_pos.inputs["Geometry"])
    links.new(moved, set_pos.inputs["Position"])
    return set_pos.outputs["Geometry"]


class _Culling:
    """Per-frame culling fade of a record (calc_culling_fade): once for the generator, or per particle with the
    block's PARTICLE flag. Distances are game cm (Blender m / SCALE); the direction follows the generator."""

    def __init__(self, info, gen_now, cam_world):
        self.c = info.get("culling")
        if self.c is None or cam_world is None:
            self.c = None
            return
        self.cam = cam_world
        self.dir = (gen_now.to_3x3() @ Vector(self.c["dir"])).normalized()
        self.per_particle = bool(self.c["flags"] & CULL_PER_PARTICLE)
        self.shared = None if self.per_particle else self.at(gen_now.translation)

    def at(self, pos_world):
        return culling_fade(self.c, (self.cam - pos_world) / SCALE, self.dir)

    def fade(self, pos_world):
        if self.c is None:
            return 1.0
        return self.at(pos_world) if self.per_particle else self.shared


def _view_basis(mode, view):
    """uEffectVFR::build_view_basis 0x9B4EC0 in column form: view = the camera's axes in game world (columns). Mode 1
    (and any other value) keeps the camera's rotation; 2 / 3 / 4 keep world X / Y / Z and turn the other two axes
    around it toward the camera (rows n2_2 = L x camera axis n2_1, n2_1 = L x row n2_2). The game's basis is a
    reflection; the row n2_1 is negated here so Blender gets a rotation (a flat quad looks the same)."""
    picks = {2: (0, 1, 2), 3: (1, 2, 0), 4: (2, 0, 1)}   # mode -> (locked n2, camera axis n2_1, n2_2)
    if mode not in picks:
        return view, None
    n2, n2_1, n2_2 = picks[mode]
    lock = Vector([1.0 if i == n2 else 0.0 for i in range(3)])
    a = lock.cross(view.col[n2_1])
    if a.length < 1.1920929e-07:   # looking straight along the locked axis
        a = view.col[n2_2].cross(lock)
    a.normalize()
    b = lock.cross(a).normalized()
    rows = [None, None, None]
    rows[n2], rows[n2_2], rows[n2_1] = lock, a, b
    basis = Matrix(rows).transposed()   # rows (where each local axis goes) -> columns
    if basis.determinant() < 0:
        basis.col[n2_1] = -basis.col[n2_1]
        return basis, n2_1
    return basis, None


def _model_rotation(ob, scene, p, s, frame, order, orient, gen_now, world_m, space, cam_rot=None):
    """World (Blender) rotation of a Model / PrimModel particle, as uEffectVFR::calcParticleMatrix 0x98A6A0 builds it
    (Polygon: sub_988B00, the same branches without MDLSCL_AFTER)
    (column form G . R): R = Euler(Rot, RotOrder); G = the generator's current rotation (Generator+0x150, rebuilt each
    frame by updateWorldMatrix); ParticleOptionFlag 0x100000 ROT_LOCAL drops G (world axes); 0x200000 ROT_INIT (sets
    ROT_LOCAL too) adds the Euler angles of the generator's rotation at spawn to Rot (sub_98C800: the spawn call never
    has the direction flag, so it always takes the generator branch); with neither, a DirAxisType other than 6 and
    a move direction, G is replaced by the shortest rotation taking that axis onto the direction (world space).
    Billboard modes (ModelBillboardType / PolygonBillBoardType; renderModel 0x9A2A31, renderPolygon 0x99F8AD) multiply
    the result by the camera basis (_view_basis): column form V . G . R, so with an unrotated generator mode 1 lies in
    the screen plane with Rot on top. Returns (that rotation, the outer frame V . G: MDLSCL_AFTER scales along it,
    (the view basis' frame, the axis it mirrors) when the game's basis is a reflection (modes 2-4), else None)."""
    rot = s.rot
    if orient["init"]:
        birth = _birth_matrix(ob, scene, p.birth, gen_now).to_quaternion().to_matrix()
        spawn = (BLENDER_TO_GAME @ birth).to_euler(order)
        rot = tuple(a + b for a, b in zip(rot, spawn))
    r = Euler(rot, order).to_matrix()
    inner = None   # G in game world
    if orient["local"]:
        inner = Matrix.Identity(3)
    elif orient["axis"] is not None:
        direction = _move_direction(ob, scene, p, s, frame, gen_now, world_m, space)
        if direction is not None:
            inner = Vector(orient["axis"]).rotation_difference(BLENDER_TO_GAME @ direction).to_matrix()
    if inner is None:
        inner = BLENDER_TO_GAME @ gen_now.to_quaternion().to_matrix()
    mode = orient.get("billboard", 0)
    mirror = None
    if mode and cam_rot is not None:
        basis, flipped = _view_basis(mode, BLENDER_TO_GAME @ cam_rot.to_matrix())
        inner = basis @ inner
        if flipped is not None:
            mirror = (GAME_TO_BLENDER @ basis, flipped)
    return GAME_TO_BLENDER @ inner @ r, GAME_TO_BLENDER @ inner, mirror


def _strip_rotation(ob, scene, p, e, later, order, orient, m_tick, m_pos, space):
    """World (Blender) rotation of a PolygonStrip edge's particle matrix at its tick (sub_988B00, as _model_rotation):
    G . R with R = Euler(Rot), G = that tick's generator rotation, none with ROT_LOCAL, Rot + the spawn rotation with
    ROT_INIT, or with DirAxisType != 6 the shortest rotation taking that axis onto the movement direction."""
    rot = e.rot
    order = ROT_ORDERS[order] if 0 <= order < len(ROT_ORDERS) else "XYZ"
    if orient.get("init"):
        birth = _birth_matrix(ob, scene, p.birth, m_tick).to_quaternion().to_matrix()
        rot = tuple(a + b for a, b in zip(rot, (BLENDER_TO_GAME @ birth).to_euler(order)))
    r = Euler(rot, order).to_matrix()
    inner = None
    if orient.get("local"):
        inner = Matrix.Identity(3)
    elif orient.get("axis") is not None:
        if space == SPACE_FOLLOW and not p.path:
            d = m_tick.to_3x3() @ Vector(p.dir)
        elif later is not None:   # the movement over the tick after this one
            d = m_pos.to_3x3() @ (Vector(later.pos) - Vector(e.pos))
        else:
            d = Vector()
        if d.length > 1e-9:
            inner = Vector(orient["axis"]).rotation_difference(BLENDER_TO_GAME @ d.normalized()).to_matrix()
    if inner is None:
        inner = BLENDER_TO_GAME @ m_tick.to_quaternion().to_matrix()
    return GAME_TO_BLENDER @ inner @ r


def _move_direction(ob, scene, p, s, frame, gen_now, world_m, space):
    """The direction the game hands calcParticleMatrix, in Blender world space: Move None reports the spawn direction
    in generator space (moveParticleMoveNone 0x995E60), Add / Mul / paths their velocity (moveParticleMoveAdd 0x996160:
    normalize(speed - fall)), approximated by the position change over a frame."""
    if space == SPACE_FOLLOW and not p.path:
        d = gen_now.to_3x3() @ Vector(p.dir)
    else:
        other = state_at(p, frame - 1) if frame - 1 >= p.birth else state_at(p, frame + 1)
        if other is None:
            return None
        delta = Vector(s.pos) - Vector(other.pos)
        if frame - 1 < p.birth:
            delta = -delta
        m = gen_now if s.anchor is None else world_m
        d = m.to_3x3() @ delta
    return d.normalized() if d.length > 1e-9 else None


def _ribbon_node_group():
    """Camera-facing strips from point chains (the line objects' meshes): each point moves +/- its `half` along
    normalize((next - previous) x (Eye - point)) (next / previous within its chain, the point itself at an end), the
    UVs come from the points' uv_l / uv_r, EdgeAlpha rides along. Curve to Mesh with a free normal: the profile's
    X axis (-1 .. 1, scaled by the point's radius) follows the normal, and its point attributes propagate."""
    ng = bpy.data.node_groups.get(LINE_NODE_GROUP)
    if ng is not None:
        return ng
    ng = bpy.data.node_groups.new(LINE_NODE_GROUP, "GeometryNodeTree")
    ng.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    eye = ng.interface.new_socket(LINE_EYE, in_out="INPUT", socket_type="NodeSocketVector")
    eye.default_value = (0.0, 0.0, 1.0e6)
    ng.interface.new_socket(LINE_MATERIAL, in_out="INPUT", socket_type="NodeSocketMaterial")
    ng.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    nodes, links = ng.nodes, ng.links
    group_in, group_out = nodes.new("NodeGroupInput"), nodes.new("NodeGroupOutput")

    def attr(name, data_type):
        n = nodes.new("GeometryNodeInputNamedAttribute")
        n.data_type = data_type
        n.inputs["Name"].default_value = name
        return n.outputs["Attribute"]

    def vmath(op, a, b=None):
        n = nodes.new("ShaderNodeVectorMath")
        n.operation = op
        links.new(a, n.inputs[0])
        if b is not None:
            links.new(b, n.inputs[1])
        return n.outputs["Value" if op == "LENGTH" else "Vector"]

    def switch(kind, condition, when_false, when_true):
        n = nodes.new("GeometryNodeSwitch")
        n.input_type = kind
        links.new(condition, n.inputs["Switch"])
        links.new(when_false, n.inputs["False"])
        links.new(when_true, n.inputs["True"])
        return n.outputs["Output"]

    def less(value, limit):
        n = nodes.new("FunctionNodeCompare")
        n.data_type, n.operation = "FLOAT", "LESS_THAN"
        links.new(value, n.inputs["A"])
        n.inputs["B"].default_value = limit
        return n.outputs["Result"]

    curve = nodes.new("GeometryNodeMeshToCurve")
    links.new(group_in.outputs["Geometry"], curve.inputs["Mesh"])
    index = nodes.new("GeometryNodeInputIndex").outputs["Index"]
    position = nodes.new("GeometryNodeInputPosition").outputs["Position"]
    neighbours = []
    for offset in (1, -1):   # the next / previous point of the same chain, or the point itself at a chain end
        step = nodes.new("GeometryNodeOffsetPointInCurve")
        links.new(index, step.inputs["Point Index"])
        step.inputs["Offset"].default_value = offset
        at = switch("INT", step.outputs["Is Valid Offset"], index, step.outputs["Point Index"])
        sample = nodes.new("GeometryNodeSampleIndex")
        sample.data_type, sample.domain = "FLOAT_VECTOR", "POINT"
        links.new(curve.outputs["Curve"], sample.inputs["Geometry"])
        links.new(position, sample.inputs["Value"])
        links.new(at, sample.inputs["Index"])
        neighbours.append(sample.outputs["Value"])
    tangent = vmath("SUBTRACT", neighbours[0], neighbours[1])
    view = vmath("SUBTRACT", group_in.outputs[LINE_EYE], position)
    side = vmath("CROSS_PRODUCT", tangent, view)
    up = nodes.new("FunctionNodeInputVector")
    up.vector = (0.0, 0.0, 1.0)
    fallback = vmath("CROSS_PRODUCT", tangent, up.outputs["Vector"])   # eye along the tangent: any side will do
    side = switch("VECTOR", less(vmath("LENGTH", side), 1e-12), side, fallback)
    right = nodes.new("FunctionNodeInputVector")
    right.vector = (1.0, 0.0, 0.0)
    side = switch("VECTOR", less(vmath("LENGTH", side), 1e-12), side, right.outputs["Vector"])
    normal = nodes.new("GeometryNodeSetCurveNormal")
    normal.mode = "FREE"
    links.new(curve.outputs["Curve"], normal.inputs["Curve"])
    links.new(vmath("NORMALIZE", side), normal.inputs["Normal"])
    radius = nodes.new("GeometryNodeSetCurveRadius")
    links.new(normal.outputs["Curve"], radius.inputs["Curve"])
    links.new(attr("half", "FLOAT"), radius.inputs["Radius"])
    profile = nodes.new("GeometryNodeCurvePrimitiveLine")
    profile.inputs["Start"].default_value = (-1.0, 0.0, 0.0)
    profile.inputs["End"].default_value = (1.0, 0.0, 0.0)
    side_k = nodes.new("GeometryNodeStoreNamedAttribute")   # 0 on the profile's first point, 1 on its second
    side_k.data_type, side_k.domain = "FLOAT", "POINT"
    side_k.inputs["Name"].default_value = "side_k"
    links.new(profile.outputs["Curve"], side_k.inputs["Geometry"])
    links.new(nodes.new("GeometryNodeInputIndex").outputs["Index"], side_k.inputs["Value"])
    strip = nodes.new("GeometryNodeCurveToMesh")
    links.new(radius.outputs["Curve"], strip.inputs["Curve"])
    links.new(side_k.outputs["Geometry"], strip.inputs["Profile Curve"])
    # UVs: left edge uv_l, right edge uv_r (point attributes of the chain, carried to both strip vertices)
    span = vmath("SUBTRACT", attr("uv_r", "FLOAT_VECTOR"), attr("uv_l", "FLOAT_VECTOR"))
    scaled = nodes.new("ShaderNodeVectorMath")
    scaled.operation = "SCALE"
    links.new(span, scaled.inputs[0])
    links.new(attr("side_k", "FLOAT"), scaled.inputs["Scale"])
    uv = vmath("ADD", attr("uv_l", "FLOAT_VECTOR"), scaled.outputs["Vector"])
    store = nodes.new("GeometryNodeStoreNamedAttribute")
    store.data_type, store.domain = "FLOAT2", "CORNER"
    store.inputs["Name"].default_value = "UVMap"
    links.new(strip.outputs["Mesh"], store.inputs["Geometry"])
    links.new(uv, store.inputs["Value"])
    material = nodes.new("GeometryNodeSetMaterial")   # the strip is new geometry: it needs the ribbon material
    links.new(store.outputs["Geometry"], material.inputs["Geometry"])
    links.new(group_in.outputs[LINE_MATERIAL], material.inputs["Material"])
    links.new(material.outputs["Geometry"], group_out.inputs["Geometry"])
    return ng


def _model_node_group():
    """Instance one child of a collection per point (instance_index), with rot / scale3."""
    ng = bpy.data.node_groups.get(MODEL_NODE_GROUP)
    if ng is not None:
        return ng
    ng = bpy.data.node_groups.new(MODEL_NODE_GROUP, "GeometryNodeTree")
    ng.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    ng.interface.new_socket("Collection", in_out="INPUT", socket_type="NodeSocketCollection")
    ng.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    nodes, links = ng.nodes, ng.links
    group_in, group_out = nodes.new("NodeGroupInput"), nodes.new("NodeGroupOutput")
    info = nodes.new("GeometryNodeCollectionInfo")
    info.transform_space = "ORIGINAL"
    info.inputs["Separate Children"].default_value = True
    info.inputs["Reset Children"].default_value = False
    links.new(group_in.outputs["Collection"], info.inputs["Collection"])
    instance = nodes.new("GeometryNodeInstanceOnPoints")
    instance.inputs["Pick Instance"].default_value = True
    links.new(group_in.outputs["Geometry"], instance.inputs["Points"])
    links.new(info.outputs["Instances"], instance.inputs["Instance"])

    def attr(name, data_type):
        n = nodes.new("GeometryNodeInputNamedAttribute")
        n.data_type = data_type
        n.inputs["Name"].default_value = name
        return n.outputs["Attribute"]

    links.new(attr("instance_index", "INT"), instance.inputs["Instance Index"])
    links.new(attr("rot", "FLOAT_VECTOR"), instance.inputs["Rotation"])
    links.new(attr("scale3", "FLOAT_VECTOR"), instance.inputs["Scale"])
    realize = nodes.new("GeometryNodeRealizeInstances")
    links.new(instance.outputs["Instances"], realize.inputs["Geometry"])
    # UV scroll (renderModel 0x9A20C0 -> gXfUVScroll): uv1 += (u, -v) per particle (V flipped for Blender)
    add = nodes.new("ShaderNodeVectorMath")
    add.operation = "ADD"
    links.new(attr(MODEL_UV, "FLOAT_VECTOR"), add.inputs[0])
    links.new(attr("uv_scroll", "FLOAT_VECTOR"), add.inputs[1])
    exists = nodes.new("GeometryNodeInputNamedAttribute")   # only meshes that have the UV layer
    exists.data_type = "FLOAT_VECTOR"
    exists.inputs["Name"].default_value = MODEL_UV
    store = nodes.new("GeometryNodeStoreNamedAttribute")
    store.data_type, store.domain = "FLOAT2", "CORNER"
    store.inputs["Name"].default_value = MODEL_UV
    links.new(_after_scale(nodes, links, realize.outputs["Geometry"]), store.inputs["Geometry"])
    links.new(exists.outputs["Exists"], store.inputs["Selection"])
    links.new(add.outputs["Vector"], store.inputs["Value"])
    # the particle's colour x intensity and alpha for the effect materials (renderModel draws the model with them)
    tint = nodes.new("ShaderNodeSeparateXYZ")
    links.new(attr("tint", "FLOAT_VECTOR"), tint.inputs["Vector"])
    color = nodes.new("FunctionNodeCombineColor")
    for axis, channel in zip("XYZ", ("Red", "Green", "Blue")):
        links.new(tint.outputs[axis], color.inputs[channel])
    links.new(attr("alpha", "FLOAT"), color.inputs["Alpha"])
    store_color = nodes.new("GeometryNodeStoreNamedAttribute")
    store_color.data_type, store_color.domain = "FLOAT_COLOR", "POINT"
    store_color.inputs["Name"].default_value = EDGE_ALPHA_ATTR
    links.new(store.outputs["Geometry"], store_color.inputs["Geometry"])
    links.new(color.outputs["Color"], store_color.inputs["Value"])
    links.new(store_color.outputs["Geometry"], group_out.inputs["Geometry"])
    return ng


def _node_group():
    ng = bpy.data.node_groups.get(NODE_GROUP)
    if ng is not None:
        return ng
    ng = bpy.data.node_groups.new(NODE_GROUP, "GeometryNodeTree")
    ng.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    ng.interface.new_socket("Source", in_out="INPUT", socket_type="NodeSocketObject")
    ng.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    nodes, links = ng.nodes, ng.links

    def node(kind, x, y, **props):
        n = nodes.new(kind)
        n.location = (x, y)
        for key, value in props.items():
            setattr(n, key, value)
        return n

    def attr(name, data_type, x, y):
        n = node("GeometryNodeInputNamedAttribute", x, y, data_type=data_type)
        n.inputs["Name"].default_value = name
        return n

    group_in = node("NodeGroupInput", -900, 0)
    group_out = node("NodeGroupOutput", 1500, 0)
    info = node("GeometryNodeObjectInfo", -700, -200, transform_space="ORIGINAL")
    links.new(group_in.outputs["Source"], info.inputs["Object"])

    instance = node("GeometryNodeInstanceOnPoints", -400, 0)
    links.new(group_in.outputs["Geometry"], instance.inputs["Points"])
    links.new(info.outputs["Geometry"], instance.inputs["Instance"])
    links.new(attr("rot", "FLOAT_VECTOR", -700, -400).outputs["Attribute"], instance.inputs["Rotation"])
    links.new(attr("scale3", "FLOAT_VECTOR", -700, -550).outputs["Attribute"], instance.inputs["Scale"])
    realize = node("GeometryNodeRealizeInstances", -200, 0)
    links.new(instance.outputs["Instances"], realize.inputs["Geometry"])

    # per-particle shape (Polygon / PrimModel sizes, keyframed or growing): the source vertex is
    # sum(basis_i * shape_i); move each realized vertex by rot(scale3 * (that - rest position)) * shape_on
    def weighted(basis, value_socket, x, y):
        n = node("ShaderNodeVectorMath", x, y, operation="SCALE")
        links.new(attr(basis, "FLOAT_VECTOR", x - 200, y).outputs["Attribute"], n.inputs[0])
        links.new(value_socket, n.inputs["Scale"])
        return n.outputs["Vector"]

    shape_xyz = node("ShaderNodeSeparateXYZ", -400, 600)
    links.new(attr("shape", "FLOAT_VECTOR", -600, 600).outputs["Attribute"], shape_xyz.inputs["Vector"])
    terms = [weighted("shape_a", shape_xyz.outputs["X"], -100, 900),
             weighted("shape_b", shape_xyz.outputs["Y"], -100, 750),
             weighted("shape_c", shape_xyz.outputs["Z"], -100, 600),
             weighted("shape_d", attr("shape_w", "FLOAT", -400, 450).outputs["Attribute"], -100, 450)]
    total = terms[0]
    for i, term in enumerate(terms[1:]):
        add = node("ShaderNodeVectorMath", 100 + 100 * i, 800, operation="ADD")
        links.new(total, add.inputs[0])
        links.new(term, add.inputs[1])
        total = add.outputs["Vector"]
    delta = node("ShaderNodeVectorMath", 450, 800, operation="SUBTRACT")
    links.new(total, delta.inputs[0])
    links.new(attr("src_co", "FLOAT_VECTOR", 250, 650).outputs["Attribute"], delta.inputs[1])
    scaled = node("ShaderNodeVectorMath", 600, 800, operation="MULTIPLY")
    links.new(delta.outputs["Vector"], scaled.inputs[0])
    links.new(attr("scale3", "FLOAT_VECTOR", 450, 650).outputs["Attribute"], scaled.inputs[1])
    rotated = node("ShaderNodeVectorRotate", 750, 800, rotation_type="EULER_XYZ")
    links.new(scaled.outputs["Vector"], rotated.inputs["Vector"])
    links.new(attr("rot", "FLOAT_VECTOR", 600, 650).outputs["Attribute"], rotated.inputs["Rotation"])
    gated = node("ShaderNodeVectorMath", 900, 800, operation="SCALE")
    links.new(rotated.outputs["Vector"], gated.inputs[0])
    links.new(attr("shape_on", "FLOAT", 750, 650).outputs["Attribute"], gated.inputs["Scale"])
    reshape = node("GeometryNodeSetPosition", 0, 0)
    links.new(realize.outputs["Geometry"], reshape.inputs["Geometry"])
    links.new(gated.outputs["Vector"], reshape.inputs["Offset"])

    # UV of the current flipbook frame: u' = uv_u . (u, v, 1), v' = uv_v . (u, v, 1)
    homogeneous = node("ShaderNodeVectorMath", -50, -250, operation="ADD")
    links.new(attr("UVMap", "FLOAT_VECTOR", -250, -250).outputs["Attribute"], homogeneous.inputs[0])
    homogeneous.inputs[1].default_value = (0.0, 0.0, 1.0)
    dot_u = node("ShaderNodeVectorMath", 150, -250, operation="DOT_PRODUCT")
    links.new(homogeneous.outputs["Vector"], dot_u.inputs[0])
    links.new(attr("uv_u", "FLOAT_VECTOR", -50, -420).outputs["Attribute"], dot_u.inputs[1])
    dot_v = node("ShaderNodeVectorMath", 150, -420, operation="DOT_PRODUCT")
    links.new(homogeneous.outputs["Vector"], dot_v.inputs[0])
    links.new(attr("uv_v", "FLOAT_VECTOR", -50, -570).outputs["Attribute"], dot_v.inputs[1])
    combine_uv = node("ShaderNodeCombineXYZ", 300, -300)
    links.new(dot_u.outputs["Value"], combine_uv.inputs["X"])
    links.new(dot_v.outputs["Value"], combine_uv.inputs["Y"])
    store_uv = node("GeometryNodeStoreNamedAttribute", 450, 0, data_type="FLOAT2", domain="CORNER")
    store_uv.inputs["Name"].default_value = "UVMap"
    links.new(_after_scale(nodes, links, reshape.outputs["Geometry"]), store_uv.inputs["Geometry"])
    links.new(combine_uv.outputs["Vector"], store_uv.inputs["Value"])

    # material colour: EdgeAlpha = (tint rgb, source edge alpha * particle alpha), both mixed toward colour B by the
    # source vertex's gradient factor (PrimModel rows; 0 elsewhere)
    edge = attr("EdgeAlpha", "FLOAT_COLOR", 450, -300)
    split = node("FunctionNodeSeparateColor", 650, -300)
    links.new(edge.outputs["Attribute"], split.inputs["Color"])
    grad = attr(GRADIENT_ATTR, "FLOAT", 250, -800).outputs["Attribute"]
    mix_alpha = node("ShaderNodeMix", 650, -450, data_type="FLOAT")   # inputs: 0 factor, 2 / 3 float A / B
    links.new(grad, mix_alpha.inputs[0])
    links.new(attr("alpha", "FLOAT", 450, -500).outputs["Attribute"], mix_alpha.inputs[2])
    links.new(attr("place_alpha", "FLOAT", 450, -600).outputs["Attribute"], mix_alpha.inputs[3])
    times = node("ShaderNodeMath", 850, -300, operation="MULTIPLY")
    links.new(split.outputs["Alpha"], times.inputs[0])
    links.new(mix_alpha.outputs[0], times.inputs[1])
    mix_tint = node("ShaderNodeMix", 650, -700, data_type="VECTOR")   # inputs: 0 factor, 4 / 5 vector A / B
    links.new(grad, mix_tint.inputs[0])
    links.new(attr("tint", "FLOAT_VECTOR", 450, -700).outputs["Attribute"], mix_tint.inputs[4])
    links.new(attr("place_tint", "FLOAT_VECTOR", 450, -850).outputs["Attribute"], mix_tint.inputs[5])
    tint = node("ShaderNodeSeparateXYZ", 850, -550)
    links.new(mix_tint.outputs[1], tint.inputs["Vector"])
    combine = node("FunctionNodeCombineColor", 1100, -300)
    links.new(tint.outputs["X"], combine.inputs["Red"])
    links.new(tint.outputs["Y"], combine.inputs["Green"])
    links.new(tint.outputs["Z"], combine.inputs["Blue"])
    links.new(times.outputs["Value"], combine.inputs["Alpha"])
    store_alpha = node("GeometryNodeStoreNamedAttribute", 1300, 0, data_type="FLOAT_COLOR", domain="POINT")
    store_alpha.inputs["Name"].default_value = "EdgeAlpha"
    links.new(store_uv.outputs["Geometry"], store_alpha.inputs["Geometry"])
    links.new(combine.outputs["Color"], store_alpha.inputs["Value"])
    links.new(store_alpha.outputs["Geometry"], group_out.inputs["Geometry"])
    return ng

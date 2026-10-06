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

import bpy
from bpy.app.handlers import persistent
from mathutils import Euler, Matrix, Quaternion, Vector

from albam.registry import blender_registry
from .efl import EffectList
from .efl.sim import ROT_ORDERS, SPACE_FOLLOW, SPACE_FOLLOW_TRANSLATION, simulate, state_at

NODE_GROUP = "ALBAM_EFL_Particles_v4"   # v1: uv_off/uv_scale; v2: affine uv_u/uv_v; v3: + tint; v4: + shape
TINT_GROUPS = ("ALBAM_EFL_Particles_v3", "ALBAM_EFL_Particles_v4")   # alpha carries the colour alpha
UV_STRIDE = 8                           # per pattern: a, b, off_u, c, d, off_v, width px, height px
GAME_FPS = 60.0
SCALE = 0.01
SIM_KEY = "efl_sim"
LINE_KINDS = (1, 3, 4, 12, 13, 14)   # Polyline, Texline, Line + cloth variants: ribbons rebuilt per frame
STRIP_KINDS = (15,)                  # PolygonStrip sword trails
HAIRLINE_KINDS = (3, 4, 13, 14)      # 1-pixel strips in the game
MODEL_KIND, LIGHT_KIND = 5, 10
MODEL_NODE_GROUP = "ALBAM_EFL_Models_v2"   # v2: + UV scroll on "uv1"
MODEL_UV = "uv1"                           # Albam's first .mod UV layer
MAX_LIGHTS = 8                       # light pool per record
LINE_HALF_WIDTH = 0.25       # cm; Line particles are 1-pixel strips in the game
EDGE_ALPHA_ATTR = "EdgeAlpha"
_cache = {}     # object name -> list of efl.sim.Particle
_history = {}   # object name -> {scene frame: generator world Matrix}


def invalidate():
    """Forget simulated particles (after the stored .efl bytes changed); they're rebuilt on the next frame."""
    _cache.clear()


def forget(name):
    """Drop cached state of an object that is about to be removed."""
    _cache.pop(name, None)
    _history.pop(name, None)


def store_source(root, efl_bytes, start_frame):
    root["efl_data"] = base64.b64encode(efl_bytes).decode("ascii")
    root["efl_start_frame"] = int(start_frame)


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
    """Ribbon object for Polyline/Line particles; its mesh is rebuilt every frame in world space."""
    mesh = bpy.data.meshes.new(f"{name}_ribbons")
    if material is not None:
        mesh.materials.append(material)
    ob = bpy.data.objects.new(f"{name}_particles", mesh)
    collection.objects.link(ob)
    ob["efl_root"] = root
    ob["efl_generator"] = generator
    ob[SIM_KEY] = dict(info, record=record_index, uv_stride=UV_STRIDE)
    update_object(ob, bpy.context.scene)
    return ob


def frame_tables(anim, image, anim_flag, ean_module):
    """Per flipbook sequence: (affine ((a, b, off_u), (c, d, off_v)), width px, height px) per pattern."""
    tex_w, tex_h = (image.size[0], image.size[1]) if image is not None and image.size[0] else (64, 64)
    whole = (ean_module.IDENTITY_AFFINE, tex_w, tex_h)
    if anim is None or image is None or not anim.sequences or not image.size[0]:
        return [[whole]]
    return [[(ean_module.uv_affine(p, tex_w, tex_h, anim_flag), abs(p[2]), abs(p[3])) for p in seq.patterns]
            or [whole] for seq in anim.sequences]


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


def _particles(ob):
    if ob.name in _cache:
        return _cache[ob.name]
    particles = []
    info, root = ob.get(SIM_KEY), ob.get("efl_root")
    if info and root is not None and root.get("efl_data"):
        try:
            efl = EffectList.from_bytes(base64.b64decode(root["efl_data"]))
            record = efl.records[info["record"]]
            strip = info.get("strip")
            strip_points = [tuple(strip[i:i + 3]) for i in range(0, len(strip), 3)] if strip else None
            range_strip = None
            if info.get("range_strip"):
                flat, sizes, range_strip, at = list(info["range_strip"]), list(info["range_strip_sizes"]), [], 0
                for size in sizes:
                    range_strip.append([tuple(flat[at + 3 * i:at + 3 * i + 3]) for i in range(size)])
                    at += 3 * size
            particles = simulate(record, seed=info["record"], max_frames=info["frames"],
                                 pat_counts=list(_tables(info, ob)[2]), strip_points=strip_points,
                                 range_strip=range_strip, ground_y=info.get("ground_y"),
                                 world_axes=info.get("world_axes"))
        except Exception as err:   # a broken record must not break playback of the rest
            print(f"EFL: simulation failed for {ob.name}: {err}")
    for particle in particles:   # life window, to skip state_at for particles not alive at a frame
        particle.end = particle.birth + particle.lifetime()
    _cache[ob.name] = particles
    return particles


def _alive_states(ob, frame):
    if frame < 0:
        return []
    out = []
    for p in _particles(ob):
        if p.birth <= frame < p.end:
            s = state_at(p, frame)
            if s is not None:
                out.append((p, s))
    return out


def _start_and_rate(ob, scene):
    root = ob.get("efl_root")
    start = root.get("efl_start_frame", scene.frame_start) if root is not None else scene.frame_start
    fps = scene.render.fps / (scene.render.fps_base or 1.0)
    return start, GAME_FPS / fps


def _game_frame(ob, scene):
    start, rate = _start_and_rate(ob, scene)
    return int(math.floor((scene.frame_current - start) * rate))


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


def update_object(ob, scene):
    info = ob[SIM_KEY]
    if info["kind"] == LIGHT_KIND:
        _update_lights(ob, scene, info)
        return
    if info["kind"] in STRIP_KINDS:
        _update_strips(ob, scene, info)
        return
    if info["kind"] in LINE_KINDS:
        _update_lines(ob, scene, info)
        return
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
    to_local = ob.matrix_world.inverted()                 # identity for unparented (world-space) objects
    to_local_rot = to_local.to_quaternion()
    cam_world = scene.camera.matrix_world.translation if scene.camera is not None else None

    co, rot, scale, alpha, tint, uv_u, uv_v, off, sc, part = [], [], [], [], [], [], [], [], [], []
    shape, shape_w, shape_on, scroll = [], [], [], []
    groups = list(info.get("model_groups", []))
    zofs = info.get("model_zofs", 0.0) * SCALE
    for p, s in alive:
        local = Vector(s.pos) * SCALE
        if space == SPACE_FOLLOW:
            world_m = gen_now
            pos_world = gen_now @ local
            pos = local
        else:   # anchor None = riding a path in the current generator space
            world_m = gen_now if s.anchor is None else _birth_matrix(ob, scene, s.anchor, gen_now)
            pos_world = world_m @ local
            if space == SPACE_FOLLOW_TRANSLATION:
                pos_world = pos_world + (gen_now.translation - world_m.translation)
            pos = to_local @ pos_world
        if zofs and cam_world is not None:   # ModelZofs: push along camera -> particle
            pos_world = pos_world + (pos_world - cam_world).normalized() * zofs
            pos = to_local @ pos_world
        co.extend(pos)
        if groups:   # Model: first mesh whose idx_group matches the part number, else mesh 0
            part.append(groups.index(s.pattern) if s.pattern in groups else 0)

        seq = min(s.sequence, len(seq_counts) - 1)
        row = rows[seq_offsets[seq] + min(s.pattern, seq_counts[seq] - 1)]
        if kind == 0:
            facing = (cam_world - pos_world).to_track_quat("Z", "Y") if cam_world is not None else Quaternion()
            q = to_local_rot @ facing @ Quaternion((0.0, 0.0, 1.0), s.angle)
            rot.extend(q.to_euler("XYZ"))
            size = s.scale * unit
            if sized:   # 1 cm source quad: width = S * pattern w * aspect, height = S * pattern h
                scale.extend((size * row[6] * s.aspect, size * row[7], 1.0))
            else:
                scale.extend((size,) * 3)
        else:
            r = Euler(s.rot, order).to_matrix().to_4x4()
            if space != SPACE_FOLLOW:   # carry the birth-frame generator rotation into world space
                r = to_local @ Matrix.LocRotScale(None, world_m.to_quaternion(), None) @ r
            rot.extend(r.to_euler("XYZ"))
            if kind in (5, 6):
                scale.extend(m * s.scale * unit for m in s.model_scale)
            else:
                scale.extend((s.scale * unit,) * 3)
        alpha.append(s.alpha * s.color[3] if v3 else s.alpha)
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

    mesh = ob.data
    mesh.clear_geometry()
    mesh.vertices.add(len(alive))
    mesh.vertices.foreach_set("co", co)
    for name, kind_, values in (("rot", "FLOAT_VECTOR", rot), ("scale3", "FLOAT_VECTOR", scale),
                                ("tint", "FLOAT_VECTOR", tint),
                                ("uv_u", "FLOAT_VECTOR", uv_u), ("uv_v", "FLOAT_VECTOR", uv_v),
                                ("uv_off", "FLOAT_VECTOR", off), ("uv_scale", "FLOAT_VECTOR", sc),
                                ("alpha", "FLOAT", alpha), ("shape", "FLOAT_VECTOR", shape),
                                ("shape_w", "FLOAT", shape_w), ("shape_on", "FLOAT", shape_on),
                                ("uv_scroll", "FLOAT_VECTOR", scroll)):
        attr = mesh.attributes.get(name) or mesh.attributes.new(name, kind_, "POINT")
        attr.data.foreach_set("vector" if kind_ == "FLOAT_VECTOR" else "value", values)
    if groups:
        attr = mesh.attributes.get("instance_index") or mesh.attributes.new("instance_index", "INT", "POINT")
        attr.data.foreach_set("value", part)
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
        start, end = (r * SCALE * unit for r in s.light)
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
    """Camera-facing ribbons, two vertices per point; UV across x along; EdgeAlpha = colour gradient x alpha."""
    rows, seq_offsets, seq_counts, _sized = _tables(info, ob)
    frame = _game_frame(ob, scene)
    space = info.get("space", SPACE_FOLLOW)
    generator = ob.get("efl_generator")
    gen_now = generator.matrix_world.copy() if generator is not None else Matrix.Identity(4)
    to_local = ob.matrix_world.inverted()
    cam = scene.camera.matrix_world.translation if scene.camera is not None else None
    unit = info["particle_scale"]
    hairline = info["kind"] in HAIRLINE_KINDS
    across = 0.0 if info["kind"] in (3, 13) else None   # Texline: u fixed, texture runs along the line

    verts, faces, uvs, colors = [], [], [], []
    for p, s in _alive_states(ob, frame):
        if not s.line:
            continue
        pts = []
        for q, anchor, width, rgba in s.line:
            m = gen_now if space == SPACE_FOLLOW or anchor is None else _birth_matrix(ob, scene, anchor, gen_now)
            pts.append((m @ (Vector(q) * SCALE), LINE_HALF_WIDTH * SCALE if hairline else width * SCALE * unit, rgba))
        last = len(pts) - 1
        if last < 1:
            continue
        seq = min(s.sequence, len(seq_counts) - 1)
        a, b, ou, c, d, ov = rows[seq_offsets[seq] + min(s.pattern, seq_counts[seq] - 1)][:6]
        base = len(verts)
        for i, (pw, half, rgba) in enumerate(pts):
            tangent = (pts[min(i + 1, last)][0] - pts[max(i - 1, 0)][0])
            view = (cam - pw) if cam is not None else Vector((0.0, 0.0, 1.0))
            side = tangent.cross(view)
            if side.length < 1e-9:
                side = tangent.orthogonal() if tangent.length > 1e-9 else Vector((1.0, 0.0, 0.0))
            side = side.normalized() * half
            for k, offset in enumerate((-side, side)):
                verts.append(to_local @ (pw + offset))
                u, v = (float(k) if across is None else across), 1.0 - i / last   # across, along (head v = 1)
                uvs.append((a * u + b * v + ou, c * u + d * v + ov))
                colors.append((rgba[0], rgba[1], rgba[2], rgba[3] * s.alpha))
            if i:
                j = base + 2 * i
                faces.append((j - 2, j - 1, j + 1, j))

    mesh = ob.data
    mesh.clear_geometry()
    mesh.from_pydata(verts, [], faces)
    _set_loop_uvs(mesh, uvs)
    attr = mesh.color_attributes.get(EDGE_ALPHA_ATTR) or \
        mesh.color_attributes.new(name=EDGE_ALPHA_ATTR, type="FLOAT_COLOR", domain="POINT")
    if colors:
        attr.data.foreach_set("color", [c for col in colors for c in col])
    mesh.update()


def _set_loop_uvs(mesh, uvs):
    """Per-vertex UVs onto the loops in one bulk call."""
    uv_layer = mesh.uv_layers.get("UVMap") or mesh.uv_layers.new(name="UVMap")
    if not uvs or not len(mesh.loops):
        return
    vertex_index = [0] * len(mesh.loops)
    mesh.loops.foreach_get("vertex_index", vertex_index)
    uv_layer.data.foreach_set("uv", [c for i in vertex_index for c in uvs[i]])


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

    verts, faces, uvs, colors = [], [], [], []
    for p, s in _alive_states(ob, frame):
        if not s.strip:
            continue
        edges, head, tail, divisions = s.strip
        a_pts, b_pts = [], []
        for a, b, anchor in edges:
            m = gen_now if space == SPACE_FOLLOW or anchor is None else _birth_matrix(ob, scene, anchor, gen_now)
            a_pts.append(m @ (Vector(a) * SCALE))
            b_pts.append(m @ (Vector(b) * SCALE))
        if len(a_pts) < 2:
            continue
        a_pts, b_pts = _catmull_rom(a_pts, divisions), _catmull_rom(b_pts, divisions)
        lengths = [0.0]
        for i in range(1, len(a_pts)):
            lengths.append(lengths[-1] + ((a_pts[i] - a_pts[i - 1]).length + (b_pts[i] - b_pts[i - 1]).length) / 2)
        total = lengths[-1] or 1.0
        seq = min(s.sequence, len(seq_counts) - 1)
        ra, rb, ou, rc, rd, ov = rows[seq_offsets[seq] + min(s.pattern, seq_counts[seq] - 1)][:6]
        base = len(verts)
        for i, (pa, pb) in enumerate(zip(a_pts, b_pts)):
            t = lengths[i] / total
            color = tuple(h + (tl - h) * t for h, tl in zip(head, tail))
            for k, point in enumerate((pa, pb)):
                verts.append(to_local @ point)
                u, v = t, 1.0 - k      # cell-local: along, A edge on top
                uvs.append((ra * u + rb * v + ou, rc * u + rd * v + ov))
                colors.append((color[0], color[1], color[2], color[3] * s.alpha))
            if i:
                j = base + 2 * i
                faces.append((j - 2, j, j + 1, j - 1))

    mesh = ob.data
    mesh.clear_geometry()
    mesh.from_pydata(verts, [], faces)
    _set_loop_uvs(mesh, uvs)
    attr = mesh.color_attributes.get(EDGE_ALPHA_ATTR) or \
        mesh.color_attributes.new(name=EDGE_ALPHA_ATTR, type="FLOAT_COLOR", domain="POINT")
    if colors:
        attr.data.foreach_set("color", [c for col in colors for c in col])
    mesh.update()


def _sim_objects(scene):
    # objects hidden by the spawn filter (effect_filter.py) are skipped; it updates them when they're shown again
    return [ob for ob in scene.objects if SIM_KEY in ob and ob.type in ("MESH", "EMPTY")
            and "efl_filter_hidden" not in ob]


@persistent
def _on_frame_change(scene, depsgraph=None):
    for ob in _sim_objects(scene):
        try:
            update_object(ob, scene)
        except Exception as err:
            print(f"EFL: particle update failed for {ob.name}: {err}")


@persistent
def _on_frame_change_post(scene, depsgraph=None):
    """Record generator world matrices for world-space emission."""
    for ob in _sim_objects(scene):
        if ob[SIM_KEY].get("space", SPACE_FOLLOW) == SPACE_FOLLOW:
            continue
        generator = ob.get("efl_generator")
        if generator is not None:
            _history.setdefault(ob.name, {})[scene.frame_current] = generator.matrix_world.copy()


@persistent
def _on_load(_dummy=None):
    _cache.clear()
    _table_cache.clear()
    _history.clear()


@blender_registry.register_blender_type
class ALBAM_OT_EflRecordMotion(bpy.types.Operator):
    """Step through the effect's frame range once, recording where each emitter is, so world-space
    particles stay where they were emitted even when you jump to a frame"""
    bl_idname = "albam.efl_record_motion"
    bl_label = "Record Emitter Motion"

    def execute(self, context):
        scene = context.scene
        objects = [ob for ob in _sim_objects(scene) if ob[SIM_KEY].get("space", SPACE_FOLLOW) != SPACE_FOLLOW]
        if not objects:
            self.report({"INFO"}, "No world-space effect particles in the scene")
            return {"CANCELLED"}
        current = scene.frame_current
        first = min(_start_and_rate(ob, scene)[0] for ob in objects)
        last = max(_start_and_rate(ob, scene)[0] + int(ob[SIM_KEY]["frames"] / _start_and_rate(ob, scene)[1])
                   for ob in objects)
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
    links.new(realize.outputs["Geometry"], store.inputs["Geometry"])
    links.new(exists.outputs["Exists"], store.inputs["Selection"])
    links.new(add.outputs["Vector"], store.inputs["Value"])
    links.new(store.outputs["Geometry"], group_out.inputs["Geometry"])
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
    links.new(reshape.outputs["Geometry"], store_uv.inputs["Geometry"])
    links.new(combine_uv.outputs["Vector"], store_uv.inputs["Value"])

    # material colour: EdgeAlpha = (tint rgb, source edge alpha * particle alpha)
    edge = attr("EdgeAlpha", "FLOAT_COLOR", 450, -300)
    split = node("FunctionNodeSeparateColor", 650, -300)
    links.new(edge.outputs["Attribute"], split.inputs["Color"])
    times = node("ShaderNodeMath", 850, -300, operation="MULTIPLY")
    links.new(split.outputs["Alpha"], times.inputs[0])
    links.new(attr("alpha", "FLOAT", 650, -500).outputs["Attribute"], times.inputs[1])
    tint = node("ShaderNodeSeparateXYZ", 850, -550)
    links.new(attr("tint", "FLOAT_VECTOR", 650, -650).outputs["Attribute"], tint.inputs["Vector"])
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

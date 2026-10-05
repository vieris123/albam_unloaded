"""Animated particle preview for imported .efl effects (efl_import_plan.md M2, first version).

Each simulated record gets a point-cloud object under its generator Empty. A shared Geometry Nodes group instances
the particle's shape (a hidden source object: billboard/polygon quad or PrimModel mesh) on the points, using
per-point attributes for rotation, scale, alpha and the UV rectangle of the current flipbook frame. A
frame_change_pre handler re-evaluates the simulation (efl/sim.py) for the current frame and rewrites the points.

The .efl bytes are stored on the effect root, so playback rebuilds itself after reopening the .blend.
Frame 0 of the effect is the scene frame stored as root['efl_start_frame']; game time runs at 60 fps.
"""
import base64
import math

import bpy
from bpy.app.handlers import persistent
from mathutils import Euler, Quaternion, Vector

from .efl import EffectList
from .efl.sim import ROT_ORDERS, simulate, state_at

NODE_GROUP = "ALBAM_EFL_Particles_v1"
GAME_FPS = 60.0
SCALE = 0.01
SIM_KEY = "efl_sim"
_cache = {}   # object name -> list of efl.sim.Particle


def store_source(root, efl_bytes, start_frame):
    root["efl_data"] = base64.b64encode(efl_bytes).decode("ascii")
    root["efl_start_frame"] = int(start_frame)


def create_sim_object(collection, name, parent, source, root, record_index, info):
    """Points object under `parent` that instances `source` (hidden). info: dict stored as ob['efl_sim']."""
    mesh = bpy.data.meshes.new(f"{name}_points")
    ob = bpy.data.objects.new(f"{name}_particles", mesh)
    collection.objects.link(ob)
    ob.parent = parent
    ob["efl_root"] = root
    ob[SIM_KEY] = dict(info, record=record_index)
    modifier = ob.modifiers.new("EFL Particles", "NODES")
    modifier.node_group = _node_group()
    for item in modifier.node_group.interface.items_tree:
        if getattr(item, "in_out", None) == "INPUT" and item.name == "Source":
            modifier[item.identifier] = source
    source.hide_viewport = True
    source.hide_render = True
    update_object(ob, bpy.context.scene)
    return ob


def frame_rects(anim, sequence_no, image, anim_flag, ean_module):
    """Blender-space UV affine (off_u, off_v, scale_u, scale_v) per pattern of one sequence."""
    if anim is None or image is None or not anim.sequences or not image.size[0]:
        return [(0.0, 0.0, 1.0, 1.0)]
    seq = anim.sequences[min(max(sequence_no, 0), len(anim.sequences) - 1)]
    rects = []
    for pattern in seq.patterns or [(0, 0, image.size[0], image.size[1])]:
        (u0, v0, u1, v1), _rotate = ean_module.pattern_uv_rect(pattern, image.size[0], image.size[1], anim_flag)
        rects.append((u0, 1.0 - v1, u1 - u0, v1 - v0))
    return rects


# -- playback ---------------------------------------------------------------------------------

def _particles(ob):
    if ob.name in _cache:
        return _cache[ob.name]
    particles = []
    info, root = ob.get(SIM_KEY), ob.get("efl_root")
    if info and root is not None and root.get("efl_data"):
        try:
            efl = EffectList.from_bytes(base64.b64decode(root["efl_data"]))
            record = efl.records[info["record"]]
            particles = simulate(record, seed=info["record"], max_frames=info["frames"],
                                 pat_count=len(info["rects"]) // 4)
        except Exception as err:   # a broken record must not break playback of the rest
            print(f"EFL: simulation failed for {ob.name}: {err}")
    _cache[ob.name] = particles
    return particles


def _game_frame(ob, scene):
    root = ob.get("efl_root")
    start = root.get("efl_start_frame", scene.frame_start) if root is not None else scene.frame_start
    fps = scene.render.fps / (scene.render.fps_base or 1.0)
    return int(math.floor((scene.frame_current - start) * GAME_FPS / fps))


def update_object(ob, scene):
    info = ob[SIM_KEY]
    rects = info["rects"]
    frame = _game_frame(ob, scene)
    states = [s for s in (state_at(p, frame) for p in _particles(ob)) if s is not None] if frame >= 0 else []

    billboard = info["kind"] == 0
    order = ROT_ORDERS[info["rot_order"]] if 0 <= info["rot_order"] < len(ROT_ORDERS) else "XYZ"
    unit = info["particle_scale"]
    cam_local = None
    if billboard and scene.camera is not None:
        cam_local = ob.matrix_world.inverted() @ scene.camera.matrix_world.translation

    co, rot, scale, alpha, off, sc = [], [], [], [], [], []
    for s in states:
        p = Vector(s.pos) * SCALE
        co.extend(p)
        if billboard:
            q = (cam_local - p).to_track_quat("Z", "Y") if cam_local is not None else Quaternion()
            rot.extend((q @ Quaternion((0.0, 0.0, 1.0), s.angle)).to_euler("XYZ"))
            scale.extend((s.scale * unit,) * 3)
        elif info["kind"] == 6:
            rot.extend(Euler(s.rot, order).to_matrix().to_euler("XYZ"))
            scale.extend(m * s.scale * unit for m in s.model_scale)
        else:
            rot.extend(Euler(s.rot, order).to_matrix().to_euler("XYZ"))
            scale.extend((s.scale * unit,) * 3)
        alpha.append(s.alpha)
        i = min(s.pattern, len(rects) // 4 - 1) * 4
        off.extend((rects[i], rects[i + 1], 0.0))
        sc.extend((rects[i + 2], rects[i + 3], 1.0))

    mesh = ob.data
    mesh.clear_geometry()
    mesh.vertices.add(len(states))
    mesh.vertices.foreach_set("co", co)
    for name, kind, values in (("rot", "FLOAT_VECTOR", rot), ("scale3", "FLOAT_VECTOR", scale),
                               ("uv_off", "FLOAT_VECTOR", off), ("uv_scale", "FLOAT_VECTOR", sc),
                               ("alpha", "FLOAT", alpha)):
        attr = mesh.attributes.get(name) or mesh.attributes.new(name, kind, "POINT")
        attr.data.foreach_set("vector" if kind == "FLOAT_VECTOR" else "value", values)
    mesh.update()


@persistent
def _on_frame_change(scene, depsgraph=None):
    for ob in scene.objects:
        if SIM_KEY in ob and ob.type == "MESH":
            try:
                update_object(ob, scene)
            except Exception as err:
                print(f"EFL: particle update failed for {ob.name}: {err}")


@persistent
def _on_load(_dummy=None):
    _cache.clear()


def register_handlers():
    if _on_frame_change not in bpy.app.handlers.frame_change_pre:
        bpy.app.handlers.frame_change_pre.append(_on_frame_change)
    if _on_load not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load)


def unregister_handlers():
    for handlers, fn in ((bpy.app.handlers.frame_change_pre, _on_frame_change),
                         (bpy.app.handlers.load_post, _on_load)):
        for handler in list(handlers):
            if getattr(handler, "__name__", "") == fn.__name__ and \
                    getattr(handler, "__module__", "") == fn.__module__:
                handlers.remove(handler)


# -- node group -------------------------------------------------------------------------------

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
    group_out = node("NodeGroupOutput", 1300, 0)
    info = node("GeometryNodeObjectInfo", -700, -200, transform_space="ORIGINAL")
    links.new(group_in.outputs["Source"], info.inputs["Object"])

    instance = node("GeometryNodeInstanceOnPoints", -400, 0)
    links.new(group_in.outputs["Geometry"], instance.inputs["Points"])
    links.new(info.outputs["Geometry"], instance.inputs["Instance"])
    links.new(attr("rot", "FLOAT_VECTOR", -700, -400).outputs["Attribute"], instance.inputs["Rotation"])
    links.new(attr("scale3", "FLOAT_VECTOR", -700, -550).outputs["Attribute"], instance.inputs["Scale"])
    realize = node("GeometryNodeRealizeInstances", -200, 0)
    links.new(instance.outputs["Instances"], realize.inputs["Geometry"])

    # UV of the current flipbook frame: uv * uv_scale + uv_off
    mul = node("ShaderNodeVectorMath", 0, -250, operation="MULTIPLY")
    links.new(attr("UVMap", "FLOAT_VECTOR", -200, -250).outputs["Attribute"], mul.inputs[0])
    links.new(attr("uv_scale", "FLOAT_VECTOR", -200, -400).outputs["Attribute"], mul.inputs[1])
    add = node("ShaderNodeVectorMath", 200, -250, operation="ADD")
    links.new(mul.outputs["Vector"], add.inputs[0])
    links.new(attr("uv_off", "FLOAT_VECTOR", -200, -550).outputs["Attribute"], add.inputs[1])
    store_uv = node("GeometryNodeStoreNamedAttribute", 400, 0, data_type="FLOAT2", domain="CORNER")
    store_uv.inputs["Name"].default_value = "UVMap"
    links.new(realize.outputs["Geometry"], store_uv.inputs["Geometry"])
    links.new(add.outputs["Vector"], store_uv.inputs["Value"])

    # material alpha: EdgeAlpha.a * life alpha
    edge = attr("EdgeAlpha", "FLOAT_COLOR", 400, -300)
    split = node("FunctionNodeSeparateColor", 600, -300)
    links.new(edge.outputs["Attribute"], split.inputs["Color"])
    times = node("ShaderNodeMath", 800, -300, operation="MULTIPLY")
    links.new(split.outputs["Alpha"], times.inputs[0])
    links.new(attr("alpha", "FLOAT", 600, -500).outputs["Attribute"], times.inputs[1])
    combine = node("FunctionNodeCombineColor", 1000, -300)
    for channel in ("Red", "Green", "Blue"):
        combine.inputs[channel].default_value = 1.0
    links.new(times.outputs["Value"], combine.inputs["Alpha"])
    store_alpha = node("GeometryNodeStoreNamedAttribute", 1100, 0, data_type="FLOAT_COLOR", domain="POINT")
    store_alpha.inputs["Name"].default_value = "EdgeAlpha"
    links.new(store_uv.outputs["Geometry"], store_alpha.inputs["Geometry"])
    links.new(combine.outputs["Color"], store_alpha.inputs["Value"])
    links.new(store_alpha.outputs["Geometry"], group_out.inputs["Geometry"])
    return ng

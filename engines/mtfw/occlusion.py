"""Bake Occlusion (2026-11-15): ambient occlusion into a DMC4 model's per-vertex occlusion, tangent.w.

The game's shaders (XfMaterialStandard, and dmc4_hook's PbrMaterials) multiply each vertex's direct light (spot and
point lights, diffuse and specular) by tangent.w / 255; the stock shaders also apply it to the vertex-colour /
lightmap ambient through AmbientOccBias. Albam's v153 export writes it from the point attribute `mtfw_tangent_w`
(0..1, mesh.TANGENT_W_ATTR), 254 for meshes without one. It works with or without PBR.

The bake (`bake_occlusion`) runs in Python, not Cycles, so the occluders can be chosen and hidden meshes still get
baked:
- every mesh of the model is baked, in the rest pose (armatures switched to Rest Position meanwhile; the mesh as its
  modifiers make it, when they keep the vertex count);
- the occluders are the meshes of DMC4 models (this one and the others in the scene) that are visible in the
  viewport: hide a model (or a mesh, like an overlay that sits on the skin) to leave it out;
- per vertex, `samples` cosine-weighted rays over the normal's hemisphere (a stratified Hammersley set turned by a
  per-vertex angle, so neighbours don't share the pattern), from 1 mm off the surface, up to `distance`; occlusion =
  the share of rays that hit;
- a triangle of a material the game draws with alpha test or blending (attr 0x8 / 0x20 / 0x40) blocks a ray only where
  its base texture's alpha (first UV map) is above the alpha reference (0.5 for blending); elsewhere the ray goes on.
  Without that, hair cards and lace counted as solid sheets and darkened the whole head of hair. Stored value = darkest + (1 - darkest) x (1 - occlusion): the term multiplies direct
  light, so fully enclosed spots keep `darkest` of it.
"""
import math

import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

from albam.exceptions import AlbamCheckFailure
from albam.registry import blender_registry
from . import joints
from .mesh import TANGENT_W_ATTR
from .model_settings import model_root

APP_ID = "dmc4"
BIAS = 0.001            # ray start off the surface (m)
DEFAULT_DISTANCE = 0.2
DEFAULT_SAMPLES = 64
DEFAULT_DARKEST = 0.35


def _model_roots(scene):
    return [o for o in scene.objects if model_root(o) is o and o.albam_asset.app_id == APP_ID]


def _armatures(meshes):
    found = []
    for ob in meshes:
        for mod in ob.modifiers:
            if mod.type == "ARMATURE" and mod.object is not None and mod.object not in found:
                found.append(mod.object)
    return found


class _Geometry:
    """ob in the world, as evaluated (or its own data when the modifiers change the vertex count: exact False):
    co / normals n x 3, tris m x 3 vertex indices, uvs m x 3 x 2 (first UV map, None without one), slots m (material
    slot per triangle)"""

    def __init__(self, ob, depsgraph):
        evaluated = ob.evaluated_get(depsgraph)
        me = evaluated.to_mesh()
        self.exact = len(me.vertices) == len(ob.data.vertices)
        if not self.exact:
            evaluated.to_mesh_clear()
            me = ob.data
        n = len(me.vertices)
        co = np.empty(n * 3, np.float32)
        me.vertices.foreach_get("co", co)
        normals = np.empty(n * 3, np.float32)
        me.vertex_normals.foreach_get("vector", normals)
        me.calc_loop_triangles()
        m = len(me.loop_triangles)
        tris = np.empty(m * 3, np.int32)
        me.loop_triangles.foreach_get("vertices", tris)
        loops = np.empty(m * 3, np.int32)
        me.loop_triangles.foreach_get("loops", loops)
        self.slots = np.empty(m, np.int32)
        me.loop_triangles.foreach_get("material_index", self.slots)
        self.uvs = None
        if me.uv_layers:
            uv = np.empty(len(me.loops) * 2, np.float32)
            me.uv_layers[0].data.foreach_get("uv", uv)
            self.uvs = uv.reshape(-1, 2)[loops].reshape(m, 3, 2)
        if self.exact:
            evaluated.to_mesh_clear()
        world = np.array(ob.matrix_world, np.float64)
        self.co = co.reshape(-1, 3) @ world[:3, :3].T + world[:3, 3]
        normals = normals.reshape(-1, 3) @ np.linalg.inv(world[:3, :3])
        self.normals = normals / np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-12)
        self.tris = tris.reshape(-1, 3)


def _alpha_map(mat):
    """(alpha rows x columns, top row first, 0..1; the opacity it takes to block light) for a DMC4 material the game
    draws with alpha test or blending, from its base texture; None for an opaque one"""
    from .new_model import _upstream_image
    from .texture_convert import read_pixels
    try:
        props = mat.albam_custom_properties.get_custom_properties_for_appid(APP_ID)
        attr = int(props.attr, 16)
    except Exception:
        return None
    group = mat.node_tree.nodes.get("MTFrameworkGroup") if mat.node_tree else None
    if attr not in (0x8, 0x20, 0x40) or group is None:
        return None
    node = _upstream_image(group.inputs["Diffuse BM"])
    px = read_pixels(node.image) if node is not None and node.image is not None else None
    if px is None:
        return None
    threshold = (props.alpha_ref & 0xFF) / 255.0 if attr == 0x8 else 0.5
    return px[..., 3].astype(np.float32) / 255.0, threshold


class _Occluders:
    """the BVH of the occluding triangles, with what it takes to let rays through alpha-tested holes"""
    LAYERS = 32   # alpha-tested layers a ray goes through at most

    def __init__(self, items):
        verts, tris, corners, uvs, maps, which, offset = [], [], [], [], [], [], 0
        cache = {}
        for ob, geo in items:
            verts.append(geo.co)
            tris.append(geo.tris + offset)
            corners.append(geo.co[geo.tris])
            uvs.append(geo.uvs if geo.uvs is not None else np.zeros((len(geo.tris), 3, 2), np.float32))
            per_slot = []
            for slot in ob.material_slots:
                mat = slot.material
                if mat not in cache:
                    cache[mat] = _alpha_map(mat) if mat is not None else None
                    if cache[mat] is not None:
                        maps.append(cache[mat])
                        cache[mat] = len(maps) - 1
                per_slot.append(cache[mat] if cache[mat] is not None and geo.uvs is not None else -1)
            per_slot = np.array(per_slot or [-1], np.int32)
            which.append(per_slot[np.clip(geo.slots, 0, len(per_slot) - 1)])
            offset += len(geo.co)
        self.bvh = BVHTree.FromPolygons(np.concatenate(verts).tolist(), np.concatenate(tris).tolist(),
                                        all_triangles=True)
        self.corners = np.concatenate(corners)
        self.uvs = np.concatenate(uvs)
        self.which = np.concatenate(which).tolist()
        self.maps = maps

    def solid(self, index, point):
        """True if the triangle blocks light at point (opaque, or its texture's alpha there is high enough)"""
        m = self.which[index]
        if m < 0:
            return True
        a, b, c = self.corners[index]
        v0, v1, v2 = b - a, c - a, np.asarray(point) - a
        d00, d01, d11 = v0 @ v0, v0 @ v1, v1 @ v1
        d20, d21 = v2 @ v0, v2 @ v1
        den = d00 * d11 - d01 * d01
        if abs(den) < 1e-20:
            return True
        w1 = (d11 * d20 - d01 * d21) / den
        w2 = (d00 * d21 - d01 * d20) / den
        uv = self.uvs[index]
        u, v = uv[0] * (1 - w1 - w2) + uv[1] * w1 + uv[2] * w2
        alpha, threshold = self.maps[m]
        h, w = alpha.shape
        return alpha[min(int((1.0 - v % 1.0) * h), h - 1), min(int((u % 1.0) * w), w - 1)] > threshold

    def blocked(self, origin, direction, distance):
        ray_cast = self.bvh.ray_cast
        for _layer in range(self.LAYERS):
            loc, _n, index, dist = ray_cast(origin, direction, distance)
            if loc is None:
                return False
            if self.solid(index, loc):
                return True
            origin = loc + direction * BIAS
            distance -= dist + BIAS
            if distance <= 0:
                return False
        return True


def _hemisphere(samples):
    """cosine-weighted directions around +Z (Hammersley): samples x 3"""
    i = np.arange(samples)
    u = (i + 0.5) / samples
    v = np.array([int(format(k, "032b")[::-1], 2) / 2.0 ** 32 for k in i])
    r = np.sqrt(u)
    phi = 2 * math.pi * v
    return np.stack((r * np.cos(phi), r * np.sin(phi), np.sqrt(np.maximum(1 - u, 0))), axis=1)


def _basis(n):
    """tangent, bitangent for normal n"""
    helper = np.array((1.0, 0.0, 0.0)) if abs(n[0]) < 0.9 else np.array((0.0, 1.0, 0.0))
    t = np.cross(helper, n)
    t /= np.linalg.norm(t)
    return t, np.cross(n, t)


def occlusion_values(co, normals, occluders, distance, samples):
    """the unoccluded share (0..1) per vertex"""
    local = _hemisphere(samples)
    golden = (math.sqrt(5) - 1) / 2
    out = np.empty(len(co), np.float32)
    blocked = occluders.blocked
    for k in range(len(co)):
        n = normals[k]
        t, b = _basis(n)
        a = 2 * math.pi * ((k * golden) % 1.0)
        ca, sa = math.cos(a), math.sin(a)
        t, b = t * ca + b * sa, b * ca - t * sa
        dirs = local[:, :1] * t + local[:, 1:2] * b + local[:, 2:] * n
        origin = Vector(co[k] + n * BIAS)
        hits = 0
        for d in dirs:
            if blocked(origin, Vector(d), distance):
                hits += 1
        out[k] = 1.0 - hits / samples
    return out


def bake_occlusion(context, root, distance=DEFAULT_DISTANCE, samples=DEFAULT_SAMPLES, darkest=DEFAULT_DARKEST):
    """bake every mesh of the model; returns notes. See the module doc."""
    targets = joints.model_meshes(root)
    if not targets:
        raise AlbamCheckFailure(f"{root.name} has no meshes", details=root.name,
                                solution="Parent the model's meshes to it first")
    occluders = []
    for other in _model_roots(context.scene):
        occluders += [m for m in joints.model_meshes(other) if m.visible_get() and m not in occluders]
    involved = list(dict.fromkeys(targets + occluders))
    armatures = _armatures(involved)
    saved = {arm.data: arm.data.pose_position for arm in armatures}
    notes = []
    try:
        for data in saved:
            data.pose_position = "REST"
        context.view_layer.update()
        depsgraph = context.evaluated_depsgraph_get()
        geometry = {ob: _Geometry(ob, depsgraph) for ob in involved}
    finally:
        for data, position in saved.items():
            data.pose_position = position
        context.view_layer.update()
    for ob, geo in geometry.items():
        if not geo.exact:
            notes.append(f"{ob.name}: its modifiers change the vertex count, baked without them")
    if not occluders:
        raise AlbamCheckFailure("Nothing to cast shadows", details="every mesh is hidden",
                                solution="Show the model's meshes in the viewport")
    blockers = _Occluders([(ob, geometry[ob]) for ob in occluders])
    low, total, count = 1.0, 0.0, 0
    for ob in targets:
        geo = geometry[ob]
        open_share = occlusion_values(geo.co, geo.normals, blockers, distance, samples)
        value = darkest + (1.0 - darkest) * open_share
        me = ob.data
        old = me.attributes.get(TANGENT_W_ATTR)
        if old is not None and (old.domain != "POINT" or old.data_type != "FLOAT"):
            me.attributes.remove(old)
            old = None
        attribute = old or me.attributes.new(TANGENT_W_ATTR, "FLOAT", "POINT")
        attribute.data.foreach_set("value", value.astype(np.float32))
        me.update()
        low = min(low, float(value.min()))
        total += float(value.sum())
        count += len(value)
    notes.insert(0, f"baked occlusion on {len(targets)} meshes, {count} vertices: darkest {low:.2f}, mean "
                    f"{total / max(count, 1):.2f} (1 = open), {len(occluders)} meshes cast shadows"
                    + (f" ({len(blockers.maps)} through their alpha)" if blockers.maps else ""))
    return notes


def clear_occlusion(root):
    for ob in joints.model_meshes(root):
        attribute = ob.data.attributes.get(TANGENT_W_ATTR)
        if attribute is not None:
            ob.data.attributes.remove(attribute)


@blender_registry.register_blender_type
class ALBAM_OT_ModBakeOcclusion(bpy.types.Operator):
    """Bake ambient occlusion into the model's vertices (the game's per-vertex occlusion, which darkens the direct
    light of lights in creases, under hair and clothing...). Baked in the rest pose; the meshes of DMC4 models visible
    in the viewport cast the shadows, so hide the ones that shouldn't (e.g. a dress the other body doesn't wear)"""
    bl_idname = "albam.mod_bake_occlusion"
    bl_label = "Bake Occlusion"
    bl_options = {"REGISTER", "UNDO"}

    distance: bpy.props.FloatProperty(
        name="Distance", default=DEFAULT_DISTANCE, min=0.001, soft_max=2.0, subtype="DISTANCE",
        description="How far away something still shades a point. About 0.2 m suits a character (creases, "
                    "armpits, under the chin and hair, between legs and clothing)")
    samples: bpy.props.IntProperty(
        name="Samples", default=DEFAULT_SAMPLES, min=4, max=1024,
        description="Rays per vertex: more is smoother and slower")
    darkest: bpy.props.FloatProperty(
        name="Darkest", default=DEFAULT_DARKEST, min=0.0, max=1.0, subtype="FACTOR",
        description="How much light a fully enclosed spot keeps (it multiplies the light from the game's lights): "
                    "0 black, 1 no occlusion at all. 0.35 darkens creases without making them black")

    @classmethod
    def poll(cls, context):
        root = model_root(context.object) if context.object is not None else None
        return root is not None and root.albam_asset.app_id == APP_ID

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        if context.object.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        root = model_root(context.object)
        try:
            notes = bake_occlusion(context, root, self.distance, self.samples, self.darkest)
        except AlbamCheckFailure:
            bpy.ops.albam.error_handler_popup("INVOKE_DEFAULT")
            return {"CANCELLED"}
        for note in notes:
            print(f"[Albam] {root.name}: {note}")
        self.report({"INFO"}, notes[0])
        return {"FINISHED"}


@blender_registry.register_blender_type
class ALBAM_OT_ModClearOcclusion(bpy.types.Operator):
    """Remove the model's per-vertex occlusion: its vertices then export fully lit. An imported game model loses
    the occlusion it came with too (re-import it to get that back)"""
    bl_idname = "albam.mod_clear_occlusion"
    bl_label = "Clear Occlusion"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        root = model_root(context.object) if context.object is not None else None
        return root is not None and any(m.data.attributes.get(TANGENT_W_ATTR) for m in joints.model_meshes(root))

    def execute(self, context):
        clear_occlusion(model_root(context.object))
        return {"FINISHED"}

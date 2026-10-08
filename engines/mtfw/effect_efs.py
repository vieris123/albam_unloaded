"""DMC4 .efs (effect strip curves) import / export as an editable edge mesh (efl/efs.py has the layout).

Each part becomes a chain of vertices joined by edges, all in one mesh; positions are converted from game
centimetres (Y up) to Blender metres (Z up). Edit it like any mesh: move, extrude, subdivide or delete points, or
duplicate a chain (Shift+D) to add a part. Export rebuilds the parts from the connected chains: they're ordered by
their `efs_part` attribute (copied along when extruding or duplicating), then by vertex index, and each chain is
walked from its lowest-numbered end. Per-point normals and blend indices / weights ride along as attributes.
"""
import bpy

from albam.exceptions import AlbamCheckFailure
from albam.registry import blender_registry
from albam.vfs import VirtualFileData
from .efl import efs

SCALE = 0.01
PART_ATTR = "efs_part"
NORM_ATTR = "efs_norm"
BLEND_INDEX_ATTR = "efs_blend_indices"   # the 4 u8 packed in an int
BLEND_WEIGHT_ATTR = "efs_blend_weights"


def _to_blender(v, game_space=False):
    x, y, z = v
    return (x * SCALE, y * SCALE, z * SCALE) if game_space else (x * SCALE, -z * SCALE, y * SCALE)


def _to_game(v, game_space=False):
    x, y, z = v
    return (x / SCALE, y / SCALE, z / SCALE) if game_space else (x / SCALE, z / SCALE, -y / SCALE)


def _pack(b):
    value = b[0] | (b[1] << 8) | (b[2] << 16) | (b[3] << 24)
    return value - (1 << 32) if value >= 1 << 31 else value   # int attributes are signed 32-bit


def _unpack(value):
    value &= 0xFFFFFFFF
    return tuple((value >> s) & 0xFF for s in (0, 8, 16, 24))


@blender_registry.register_import_function(app_id="dmc4", extension="efs", file_category="EFFECT")
def load_efs(file_item, context):
    data = file_item.get_bytes()
    try:
        strip = efs.parse_strip(data)
    except efs.EfsError as err:
        raise AlbamCheckFailure("This .efs file can't be imported", details=str(err),
                                solution="Only DMC4 effect strip files are supported")
    name = file_item.display_name.rsplit(".", 1)[0]
    ob = create_efs_object(name, strip, data, context.collection or context.scene.collection)
    ob.albam_asset.app_id = file_item.app_id
    ob.albam_asset.relative_path = getattr(file_item, "relative_path", "") or file_item.display_name
    exportable = context.scene.albam.exportable.file_list.add()
    exportable.bl_object = ob
    return None   # linked above


def create_efs_object(name, strip, data, collection, game_space=False):
    """Edge-mesh object for a parsed strip. game_space: points in game axes (metres), for parenting under an
    effect's generator (whose frame is in game axes); else converted to Blender axes."""
    verts, edges, parts, norms, indices, weights = [], [], [], [], [], []
    for p, part in enumerate(strip.parts):
        first = len(verts)
        for v in part.vertices:
            verts.append(_to_blender(v.pos, game_space))
            norms.append(_to_blender(v.norm, game_space))
            parts.append(p)
            indices.append(_pack(v.blend_indices))
            weights.append(_pack(v.blend_weights))
        edges += [(first + i, first + i + 1) for i in range(len(part.vertices) - 1)]
    mesh = bpy.data.meshes.new(f"EFS_{name}")
    mesh.from_pydata(verts, edges, [])
    for attr_name, kind, values in ((PART_ATTR, "INT", parts), (NORM_ATTR, "FLOAT_VECTOR", norms),
                                    (BLEND_INDEX_ATTR, "INT", indices), (BLEND_WEIGHT_ATTR, "INT", weights)):
        attr = mesh.attributes.new(attr_name, kind, "POINT")
        if kind == "FLOAT_VECTOR":
            attr.data.foreach_set("vector", [c for v in values for c in v])
        else:
            attr.data.foreach_set("value", values)
    mesh.update()
    ob = bpy.data.objects.new(f"EFS_{name}", mesh)
    collection.objects.link(ob)
    ob["efs_version"] = strip.version
    ob["efs_space"] = "game" if game_space else "blender"
    ob["efs_header_320c"] = strip.header_320c
    ob["efs_joint_num"] = strip.joint_num
    if any(part.indices for part in strip.parts):   # STRIP_TYPE_MODEL triangles (no game file has any)
        ob["efs_part_indices"] = [[list(i) for i in part.indices] for part in strip.parts]
    ob.albam_asset.original_bytes = data
    ob.albam_asset.extension = "efs"
    return ob


def _chains(mesh):
    """Vertex index lists, one per connected chain, in export order; raises AlbamCheckFailure on branches."""
    n = len(mesh.vertices)
    adjacent = [[] for _ in range(n)]
    for e in mesh.edges:
        a, b = e.vertices
        adjacent[a].append(b)
        adjacent[b].append(a)
    branches = [i for i in range(n) if len(adjacent[i]) > 2]
    if branches:
        raise AlbamCheckFailure("An .efs part branches", details=f"vertices {branches[:10]} join more than two edges",
                                solution="Each part must be a single chain of points: delete the extra edges")
    part_attr = mesh.attributes.get(PART_ATTR)
    part_of = [0] * n
    if part_attr is not None:
        part_attr.data.foreach_get("value", part_of)
    seen, chains = [False] * n, []
    for start in range(n):
        if seen[start]:
            continue
        component, stack = [], [start]   # the component, then walk it from its lowest-numbered end
        seen[start] = True
        while stack:
            v = stack.pop()
            component.append(v)
            for w in adjacent[v]:
                if not seen[w]:
                    seen[w] = True
                    stack.append(w)
        ends = [v for v in component if len(adjacent[v]) < 2]
        first = min(ends) if ends else min(component)   # a closed loop starts at its lowest vertex
        order, prev, cur = [first], None, first
        while len(order) < len(component):
            options = [w for w in adjacent[cur] if w != prev]
            if not options:
                break
            nxt = min(options)   # only a loop's first step has two options: take the lower neighbour
            if nxt == first:
                break
            order.append(nxt)
            prev, cur = cur, nxt
        chains.append((min(part_of[v] for v in component), min(component), order))
    chains.sort(key=lambda c: (c[0], c[1]))
    return [c[2] for c in chains]


def build_efs_bytes(ob):
    mesh = ob.data
    n = len(mesh.vertices)
    coords = [0.0] * (n * 3)
    mesh.vertices.foreach_get("co", coords)

    def read(name, kind, default):
        attr = mesh.attributes.get(name)
        if attr is None or attr.domain != "POINT":
            return [default] * n
        if kind == "vector":
            flat = [0.0] * (n * 3)
            attr.data.foreach_get("vector", flat)
            return [tuple(flat[i * 3:i * 3 + 3]) for i in range(n)]
        values = [0] * n
        attr.data.foreach_get("value", values)
        return values

    game_space = ob.get("efs_space") == "game"
    norms = read(NORM_ATTR, "vector", (0.0, 0.0, 1.0))
    indices = read(BLEND_INDEX_ATTR, "int", 0)
    weights = read(BLEND_WEIGHT_ATTR, "int", 0)
    strip = efs.EffectStrip(int(ob.get("efs_version", efs.VERSION_DX9)), [], int(ob.get("efs_header_320c", 0)),
                            int(ob.get("efs_joint_num", 0)))
    for chain in _chains(mesh):
        part = efs.Part()
        for v in chain:
            nx, ny, nz = _to_game(norms[v], game_space)
            length = (nx * nx + ny * ny + nz * nz) ** 0.5
            norm = (nx / length, ny / length, nz / length) if length > 1e-8 else (0.0, 1.0, 0.0)
            part.vertices.append(efs.Vertex(_to_game(tuple(coords[v * 3:v * 3 + 3]), game_space), norm,
                                            _unpack(indices[v]), _unpack(weights[v])))
        strip.parts.append(part)
    _keep_unmoved(strip, ob)
    stored = ob.get("efs_part_indices")
    if stored is not None:
        for part, idx in zip(strip.parts, stored):
            if idx and max(max(t[:3]) for t in idx) >= len(part.vertices):
                raise AlbamCheckFailure("The .efs model triangles no longer fit their part",
                                        solution="Keep the parts' point counts, or re-import the .efs")
            part.indices = [tuple(int(x) for x in t) for t in idx]
    return efs.to_bytes(strip)


def _keep_unmoved(strip, ob):
    """Points that weren't edited take the source file's exact values: the cm -> m -> cm conversion and the
    normal re-normalisation would otherwise change the last bits, so untouched files export byte-identical."""
    data = ob.albam_asset.original_bytes
    if not data:
        return
    try:
        source = efs.parse_strip(bytes(data))
    except efs.EfsError:
        return
    for part, src in zip(strip.parts, source.parts):
        for v, s in zip(part.vertices, src.vertices):
            if all(abs(a - b) <= 1e-3 * max(1.0, abs(b)) for a, b in zip(v.pos, s.pos)):
                v.pos = s.pos
            if all(abs(a - b) <= 1e-4 for a, b in zip(v.norm, s.norm)):
                v.norm = s.norm


@blender_registry.register_export_function(app_id="dmc4", extension="efs")
def export_efs(bl_obj):
    data = build_efs_bytes(bl_obj)
    asset = bl_obj.albam_asset
    return [VirtualFileData(asset.app_id, asset.relative_path, data_bytes=data)]


# -- new strips -------------------------------------------------------------------------------------

PATH_MAX = 63   # str64 field, NUL-terminated
SKIP_TYPES = ("efl_record", "efl_root", "efl_generator")


def _source_items(self, context):
    items = [("LINE", "Straight line", "A straight line of points along the generator's +Y axis (up in the game)")]
    for ob in context.scene.objects:
        if ob.type in ("MESH", "CURVE") and not any(k in ob for k in SKIP_TYPES) and "efs_version" not in ob \
                and "ean_data" not in ob:
            items.append((ob.name, ob.name, f"Use {ob.name}'s points: each connected chain of a mesh, or each "
                                             "spline of a curve, becomes a part"))
    _source_items.cache = items   # Blender needs the list kept alive
    return items


def _use_items(self, context):
    from .effect_export import record_object
    record = record_object(context.active_object)
    items = [("RANGE", "Spawn strip (RangeStripPath)",
              "Particles spawn along the strip (generator Range strip, spread by RangeStripType / Flag)")]
    move = record.get("efl_move") if record is not None else None
    if move is not None and int(move.get("type", -1)) == 3:
        items.append(("PATH", "Move path (PathStripPath)", "Particles ride along the strip (this record's PathStrip move)"))
    _use_items.cache = items
    return items


def _strip_from_points(chains):
    """EffectStrip from lists of game-space points (cm)."""
    strip = efs.EffectStrip(efs.VERSION_DX9)
    for points in chains:
        strip.parts.append(efs.Part([efs.Vertex(tuple(p), (0.0, 1.0, 0.0)) for p in points]))
    return strip


@blender_registry.register_blender_type
class ALBAM_OT_EfsNew(bpy.types.Operator):
    """Make a new .efs strip for the active effect record and point the record at it: particles then spawn along it
    (spawn strip) or ride it (PathStrip moves). Its points come from a curve or mesh you drew, or a straight line.
    The effect rebuilds so the preview uses it; exporting the effect writes the new file"""
    bl_idname = "albam.efs_new"
    bl_label = "New Strip"
    bl_options = {"REGISTER", "UNDO"}

    path: bpy.props.StringProperty(
        name="Game Path", maxlen=PATH_MAX,
        description="Where the strip goes in the game files, without the extension, e.g. effect\\efs\\com\\my_strip. "
                    "Export writes it there; Patch adds it to the .arc")
    use_for: bpy.props.EnumProperty(name="Use For", items=_use_items,
                                    description="Which of the record's strip fields points at the new file")
    source: bpy.props.EnumProperty(name="Points From", items=_source_items,
                                   description="Where the strip's points come from")
    points: bpy.props.IntProperty(name="Points", default=8, min=2, max=4096,
                                  description="Number of points of the straight line")
    length: bpy.props.FloatProperty(name="Length (cm)", default=200.0, min=0.0,
                                    description="Length of the straight line in game centimetres")

    @classmethod
    def poll(cls, context):
        from .effect_export import record_object
        return record_object(context.active_object) is not None

    def invoke(self, context, event):
        from .effect_export import effect_root, record_object
        record = record_object(context.active_object)
        root = effect_root(record)
        stem = root.get("efl_stem", "effect") if root is not None else "effect"
        number = int(record["efl_record"])
        self.path = "effect\\efs\\com\\" + f"{stem}_{number if number >= 0 else 'new'}"
        return context.window_manager.invoke_props_dialog(self, width=420)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "path")
        layout.prop(self, "use_for")
        layout.prop(self, "source")
        if self.source == "LINE":
            row = layout.row(align=True)
            row.prop(self, "points")
            row.prop(self, "length")

    def execute(self, context):
        from .effect import linked_objects
        from .effect_export import _report_failure, apply_to_scene, effect_root, record_object
        record = record_object(context.active_object)
        root = effect_root(record)
        path = self.path.strip().replace("/", "\\")
        if path.lower().endswith(".efs"):
            path = path[:-4]
        if not path or len(path.encode("latin-1", "replace")) > PATH_MAX:
            self.report({"ERROR"}, f"Give a game path of 1 to {PATH_MAX} characters")
            return {"CANCELLED"}
        if f"efs:{path}" in linked_objects(root):
            self.report({"ERROR"}, f"This effect already has a strip at {path}")
            return {"CANCELLED"}
        generator = record   # strips are in the generator's space (game axes)
        to_local = generator.matrix_world.inverted()
        if self.source == "LINE":
            step = self.length / (self.points - 1)
            chains = [[(0.0, i * step, 0.0) for i in range(self.points)]]
        else:
            src = context.scene.objects.get(self.source)
            if src is None:
                self.report({"ERROR"}, "Pick the curve or mesh to take the points from")
                return {"CANCELLED"}
            evaluated = src.evaluated_get(context.evaluated_depsgraph_get())
            mesh = evaluated.to_mesh()
            try:
                world = [src.matrix_world @ v.co for v in mesh.vertices]
                chains = [[tuple(c / SCALE for c in to_local @ world[i]) for i in chain] for chain in _chains(mesh)]
            finally:
                evaluated.to_mesh_clear()
            if not chains:
                self.report({"ERROR"}, f"{src.name} has no points")
                return {"CANCELLED"}
        strip = _strip_from_points(chains)
        collection = root.users_collection[0] if root.users_collection else context.scene.collection
        ob = create_efs_object(path.rsplit("\\", 1)[-1], strip, b"", collection, game_space=True)
        ob.albam_asset.app_id = root.albam_asset.app_id
        ob.albam_asset.relative_path = path + ".efs"
        ob.parent = generator
        ob.matrix_parent_inverse.identity()
        ob["efl_root"] = root
        ob["efl_linked"] = f"efs:{path}"
        if self.use_for == "PATH":
            record["efl_move"]["PathStripPath"] = path
        else:
            record["efl_gen"]["RangeStripPath"] = path
        try:
            apply_to_scene(context, root)
        except Exception as err:
            return _report_failure(self, err)
        self.report({"INFO"}, f"New strip {path}.efs ({sum(len(p.vertices) for p in strip.parts)} points)")
        return {"FINISHED"}

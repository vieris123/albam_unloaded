import bpy
import bmesh
from kaitaistruct import KaitaiStream
import colorsys
import numpy as np
from mathutils import Vector
from io import BytesIO

from albam.registry import blender_registry
from albam.vfs import VirtualFileData
from albam.exceptions import AlbamCheckFailure
from .structs.sbc_156 import Sbc156
from .structs.sbc_21 import Sbc21
from . import sbc_bvh
from albam.lib.primitive_geometry import eps, Tri
import albam.lib.primitive_geometry as geo
import albam.lib.bvh_construction as bvh
import albam.lib.common_op as common

SBC_CLASS_MAPPER = {
    49: Sbc156,
    255: Sbc21,
}

APPID_SBC_CLASS_MAPPER = {
    "re0": Sbc21,
    "re1": Sbc21,
    "re5": Sbc156,
    "dmc4": Sbc156,
    "rev1": Sbc21,
    "rev2": Sbc21,
    "dd": Sbc21,
}


# DMC4 SBC1: face int layers holding each triangle's values, in SbcGroup.attributes order. The first three are edited
# by Tools > Face Properties Edit ("group" is the triangle's `type`).
FACE_LAYERS = ("group", "special_attr", "surface_attr", "sbc_unk_00", "sbc_unk_01")
SBC_GROUP_INDEX = "sbc_group"       # mesh object: its group index in the source file (export order)
SBC_GROUP_ID = "sbc_group_id"       # mesh object: the group record's group_id (-1 = none)
MIN_TRIANGLE_AREA = 1e-10           # m^2; the game divides by the triangle normal's length


class TriangulationRequiredError(Exception):
    pass


class ExportingFailedError(Exception):
    pass


class MaterialMissingError(Exception):
    pass


class SBCObject():
    def __init__(self, info, BVHTree, faces, vertices, pairs):
        self.sbcinfo = info
        self.bvhtree = BVHTree
        self.faces = bvh.indexize_ob([geo.Tri(face, vertices) for face in faces])
        self.vertices = vertices
        self.pairs = bvh.indexize_ob([geo.QuadPair(self.faces[pair.face_01], self.faces[pair.face_02])
                                     if pair.face_02 != 0xFFFF else
                                     self.faces[pair.face_01]
                                     for pair in pairs])

# Very smartass(?) way to dynamically create a list with 44 colors
class counter():
    def __init__(self):
        self.i = 0

    def count(self):
        self.i += 1
        return self.i


i = counter()


def cycle():
    return [0.4, 0.6, 0.8, 1.0][i.count() % 4]


palette = [colorsys.hsv_to_rgb(c / 55, 1.0, cycle()) for c in range(44)]
palette = [(i[0], i[1], i[2], 1.0) for i in palette]


@blender_registry.register_import_function(app_id="re0", extension='sbc', file_category="COLLISION")
@blender_registry.register_import_function(app_id="re1", extension='sbc', file_category="COLLISION")
# @blender_registry.register_import_function(app_id="re5", extension='sbc', file_category="COLLISION")
# @blender_registry.register_import_function(app_id="re6", extension='sbc', file_category="COLLISION")
@blender_registry.register_import_function(app_id="rev1", extension='sbc', file_category="COLLISION")
@blender_registry.register_import_function(app_id="rev2", extension='sbc', file_category="COLLISION")
@blender_registry.register_import_function(app_id="dd", extension='sbc', file_category="COLLISION")
def load_sbc21(file_item, context):
    app_id = file_item.app_id
    sbc_bytes = file_item.get_bytes()
    sbc_version = sbc_bytes[3]
    assert sbc_version in SBC_CLASS_MAPPER, f"Unsupported version: {sbc_version}"
    SbcCls = SBC_CLASS_MAPPER[sbc_version]
    sbc = SbcCls.from_bytes(sbc_bytes)
    sbc._read()

    bl_object_name = file_item.display_name
    bl_object = bpy.data.objects.new(bl_object_name, None)

    cBVH = [b for i, b in enumerate(sbc.sbc_bvhc)]
    faceCollection = [fc for i, fc in enumerate(sbc.faces)]
    vertexCollection = [vc for i, vc in enumerate(sbc.vertices)]
    pairCollection = [pc for i, pc in enumerate(sbc.pairs_collections)]
    objects = []

    print("sbc type {}".format(sbc_version))
    for ix, ob_info in enumerate(sbc.sbc_info):
        ps, pc = ob_info.pairs_start, ob_info.pairs_count
        fs, fc = ob_info.faces_start, ob_info.face_count
        vs, vc = ob_info.vertex_start, ob_info.vertex_count
        obj = SBCObject(ob_info, cBVH[ix], faceCollection[fs:fs + fc],
                        vertexCollection[vs:vs + vc], pairCollection[ps:ps + pc])
        objects.append(obj)

    print("num sbc objects {}".format(len(objects)))
    for obj in objects:
        mesh, ob = create_collision_mesh(obj)
        ob.parent = bl_object
    for i, typing in enumerate(sbc.collision_types):
        empty = create_link_ob(typing)
        empty.parent = bl_object

    bl_object.albam_asset.original_bytes = sbc_bytes
    bl_object.albam_asset.app_id = app_id
    bl_object.albam_asset.relative_path = file_item.relative_path
    bl_object.albam_asset.extension = file_item.extension

    exportable = context.scene.albam.exportable.file_list.add()
    exportable.bl_object = bl_object

    context.scene.albam.exportable.file_list.update()
    return bl_object

@blender_registry.register_import_function(app_id="re5", extension='sbc', file_category="COLLISION")
@blender_registry.register_import_function(app_id="dmc4", extension='sbc', file_category="COLLISION")
def load_sbc156(file_item, context):
    """DMC4 DX9 SBC1: one mesh per collision group, triangle values as face int layers (FACE_LAYERS)."""
    app_id = file_item.app_id
    sbc_bytes = file_item.get_bytes()
    groups = sbc_bvh.read_sbc1_groups(sbc_bytes)

    bl_object_name = file_item.display_name
    bl_object = bpy.data.objects.new(bl_object_name, None)
    stem = bl_object_name.rsplit(".", 1)[0]
    for ix, group in enumerate(groups):
        ob = create_sbc_mesh156(f"{stem}_{ix:03d}", group)
        ob[SBC_GROUP_INDEX] = ix
        ob[SBC_GROUP_ID] = _to_signed(group.group_id)
        ob.parent = bl_object

    bl_object.albam_asset.original_bytes = sbc_bytes
    bl_object.albam_asset.app_id = app_id
    bl_object.albam_asset.relative_path = file_item.relative_path
    bl_object.albam_asset.extension = file_item.extension

    exportable = context.scene.albam.exportable.file_list.add()
    exportable.bl_object = bl_object

    context.scene.albam.exportable.file_list.update()
    return bl_object

def create_collision_mesh(sbcObject):
    mesh, obj = create_sbc_mesh("CollisionMesh.000", decompose_sbc_ob(sbcObject))
    obj["Type"] = "SBC_Mesh"
    obj["indexID"] = str(sbcObject.sbcinfo.index_id)
    return mesh, obj


def create_link_ob(link_ob):
    sbcEmpty = common.create_root_nub("SBC Stage Link.000")
    sbcEmpty["Type"] = "SBC_Link"
    sbcEmpty["unk_01"] = link_ob.unk_01
    sbcEmpty["unk_02"] = link_ob.unk_02
    sbcEmpty["unk_03"] = link_ob.unk_03
    sbcEmpty["unk_04"] = link_ob.unk_04
    sbcEmpty["jp_path"] = link_ob.jp_path
    return sbcEmpty


def decompose_sbc_ob(sbc_ob):
    sbc_geom = {}
    sbc_geom["vertices"] = [(vert.x * 0.01, vert.z * -0.01, vert.y * 0.01)
                            for vert in sbc_ob.vertices]
    sbc_geom["faces"] = [face.dataFace.vert for face in sbc_ob.faces]
    sbc_geom["materials"] = materials_from_sbc(sbc_ob)
    return sbc_geom

def materials_from_sbc(sbc_ob):
    materials = {}
    for ix, face in enumerate(sbc_ob.faces):
        if face.type not in materials:
            materials[face.type] = []
        materials[face.type].append(ix)
    return materials


def create_sbc_mesh(name, meshpart):
    blenderMesh = bpy.data.meshes.new(name)
    blenderMesh.from_pydata(meshpart["vertices"], [], meshpart["faces"])
    blenderMesh.update()
    blenderObject = bpy.data.objects.new(name, blenderMesh)
    # bpy.context.scene.objects.link(blenderObject)
    bpy.context.collection.objects.link(blenderObject)

    bm = bmesh.new()
    bm.from_mesh(blenderMesh)
    bm.faces.ensure_lookup_table()
    for ix, material in enumerate(meshpart["materials"]):
        mat = bpy.data.materials.new(name="Type %03d" % material)
        try:
            mat.diffuse_color = palette[material]
        except IndexError:
            colorsys.hsv_to_rgb(0, 0, 0)
            print("Unknown colision type: %d" % material)
        blenderMesh.materials.append(mat)
        for face in meshpart["materials"][material]:
            bm.faces[face].material_index = ix

    bm.to_mesh(blenderMesh)
    return blenderMesh, blenderObject

def create_sbc_mesh156(name, group):
    """SbcGroup (game space) -> mesh object (Blender space, m, Z up) with the triangle values as face layers."""
    mesh = bpy.data.meshes.new(name)
    vertices = [(x * 0.01, z * -0.01, y * 0.01) for x, y, z in group.vertices]
    mesh.from_pydata(vertices, [], group.triangles)
    mesh.update()
    ob = bpy.data.objects.new(name, mesh)
    ob["Type"] = "SBC_Mesh"

    # from_pydata can drop faces it considers invalid; keep the rows aligned with the faces it made
    keep = len(mesh.polygons) == len(group.triangles)
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.faces.ensure_lookup_table()
    layers = [bm.faces.layers.int.new(name) for name in FACE_LAYERS]
    if keep:
        for face, values in zip(bm.faces, group.attributes):
            for layer, value in zip(layers, values):
                face[layer] = _to_signed(value)
    bm.to_mesh(mesh)
    bm.free()
    return ob


def _to_signed(value):
    value &= 0xFFFFFFFF
    return value - 0x100000000 if value >= 0x80000000 else value

def cycles(verts):
    return [(verts[i % 3].index, verts[(i + 1) % 3].index) for i in range(len(verts))]


@blender_registry.register_export_function(app_id="re0", extension="sbc")
@blender_registry.register_export_function(app_id="re1", extension="sbc")
@blender_registry.register_export_function(app_id="rev1", extension="sbc")
@blender_registry.register_export_function(app_id="rev2", extension="sbc")
@blender_registry.register_export_function(app_id="dd", extension="sbc")
def export_sbc(bl_obj):
    asset = bl_obj.albam_asset
    app_id = asset.app_id
    Sbc = Sbc21

    src_sbc = Sbc.from_bytes(asset.original_bytes)
    src_sbc._read()
    dst_sbc = Sbc()

    meshes = [c for c in bl_obj.children_recursive if c.type == "MESH"]
    links = [c for c in bl_obj.children_recursive if c.type == "EMPTY"]
    clones = [common.clone_mesh(mesh) for mesh in meshes]
    clones = [mesh_rescale(clone) for clone in clones]
    vertList = []
    trisList = []
    quadList = []
    sbcsList = []
    mesh_metadata = []
    errors = []
    options = {"clusteringFunction": bvh.HybridClustering,
               "metric": bvh.Cluster.SAHMetric,
               "partition": bvh.morton_partition,
               "mode": bvh.CAPCOM}
    vfiles = []
    print("Initiate export")
    for mesh in clones:
        try:
            vertices, tris = mesh_to_tri(mesh)
        except TriangulationRequiredError as errors:
            errors.append("%s requires triangulating." % mesh.name)
        print("Mesh processed")
        quads, sbc = bvh.primitive_to_sbc(tris, **options)
        vertList.append(vertices)
        trisList.append(tris)
        quadList.append(quads)
        sbcsList.append(sbc)
        mesh_metadata.append({"indexID": mesh["indexID"]})
    parent_tree = bvh.trees_to_sbc_col(sbcsList, **options)
    final_size, serialized = build_sbc(bl_obj, src_sbc, dst_sbc, vertList, trisList, quadList, sbcsList,
                                        links, parent_tree, mesh_metadata)
    stream = KaitaiStream(BytesIO(bytearray(final_size)))
    dst_sbc._check()
    dst_sbc._write(stream)
    sbc_vf = VirtualFileData(app_id, asset.relative_path, data_bytes=stream.to_byte_array())
    vfiles.append(sbc_vf)
    for clone in clones:
        common.delete_ob(clone)
    return vfiles


def build_sbc(bl_obj, src_sbc, dst_sbc, verts, tris, quads, sbcs, links, parent_tree, mesh_metadata):
    def tally(x):
        return sum(map(len, x))
    # headerData = formHeader(len(verts), tally(verts), tally(tris), tally(
    #    quads), len(links), tally(sbcs+[parentTree]), parentTree)
    _init_sbc_header(bl_obj, src_sbc, dst_sbc, len(verts), len(links), tally(quads), tally(tris),
                     tally(verts), parent_tree, tally(sbcs + [parent_tree]))
    # header = buildHeader(headerData)
    # cBVH = list(map(buildCollision,sbcs))
    dst_sbc.sbc_bvhc = [_serialize_bvhc(dst_sbc, sbc) for sbc in sbcs]

    # cBVHCollision = buildCollision(parentTree)
    dst_sbc.bvh = _serialize_bvhc(dst_sbc, parent_tree)

    # faceCollection = list(map(buildFaces, tris))
    dst_sbc.faces = [_serialize_faces(dst_sbc, face) for face in tris][0]

    # vertexCollection = list(map(buildVertices, verts))
    dst_sbc.vertices = [_serialize_vertices(dst_sbc, v) for v in verts][0]

    # collisionTypes = list(map(buildTypes, links))
    dst_sbc.collision_types = [_serialize_col_types(dst_sbc, link) for link in links]

    # pairCollection = list(map(buildPairs, quads))
    dst_sbc.pairs_collections = [_serialize_pairs(dst_sbc, p) for p in quads][0]

    # infoCollection = buildInfo(
    #    header, tris, verts, collisionTypes, quads, cBVH, cBVHCollision, meshmetadata)
    dst_sbc.sbc_info = _serialize_infos(dst_sbc, tris, verts, dst_sbc.collision_types,
                                        quads, dst_sbc.sbc_bvhc, dst_sbc.bvh, mesh_metadata)

    bvhc_size = 0
    for i, bvhc in enumerate(dst_sbc.sbc_bvhc):
        bvhc_size += 64 + bvhc.node_count * 112

    bvh_size = 64 + dst_sbc.bvh.node_count * 112

    final_size = sum((
        84,
        dst_sbc.header.object_count * 80,
        bvhc_size,
        bvh_size,
        dst_sbc.header.face_count * 32,
        dst_sbc.header.vertex_count * 16,
        dst_sbc.header.stage_count * 32,
        dst_sbc.header.pair_count * 10,
    ))

    # def flatten(x): return b''.join(x)
    # return (header +
    #        flatten(infoCollection) +
    #        flatten(cBVH) +
    #        cBVHCollision +
    #        flatten(faceCollection) +
    #        flatten(vertexCollection) +
    #        flatten(collisionTypes) +
    #        flatten(pairCollection))
    return final_size, dst_sbc

def _init_sbc_header(bl_obj, src_sbc, dst_sbc, object_count, stage_count, pair_count, face_count,
                     vertex_count, parent_tree, aabb_count):
    dst_sbc_header = dst_sbc.SbcHeader(_parent=dst_sbc, _root=dst_sbc._root)
    bbox_data = parent_tree.boundingBox().serialize()
    bbox = dst_sbc.Bbox(_parent=dst_sbc_header, _root=dst_sbc._root)
    bbox.min = [v for v in bbox_data["minPos"].values()]
    bbox.max = [v for v in bbox_data["maxPos"].values()]
    dst_sbc_header.__dict__.update(dict(
        magic=b"SBC\xFF",
        unk_00=src_sbc.header.unk_00,
        unk_02=0,
        unk_03=0,
        object_count=object_count,
        stage_count=stage_count,
        pair_count=pair_count,
        face_count=face_count,
        vertex_count=vertex_count,
        nulls=[0, 0, 0, 0],
        box=bbox,
        bb_size=0x70 * (aabb_count),
    ))

    dst_sbc_header._check()
    dst_sbc.header = dst_sbc_header
    return dst_sbc_header

def _serialize_bvhc(dst_sbc, bvhc_data):
    bvh_col = dst_sbc.BvhCollision(_parent=dst_sbc, _root=dst_sbc._root)
    bbox = dst_sbc.Bbox(_parent=bvh_col, _root=dst_sbc._root)
    bvh_node = dst_sbc.BvhNode(_parent=bvh_col, _root=dst_sbc._root)
    aabb = dst_sbc.AabbBlock(_parent=bvh_node, _root=dst_sbc._root)
    bvhc_raw = bvhc_data.primitiveSerialize()

    bvh_col.bvhc = [1128814146, 2008120100]  # Bound Volume Hierarchy Collision Identifier
    bvh_col.soh = bvhc_raw["SOH"]
    bvh_col.unk_01 = 0
    bbox_data = bvhc_raw["boundingBox"]
    bbox.min = [v for v in bbox_data["minPos"].values()]
    bbox.max = [v for v in bbox_data["maxPos"].values()]
    bvh_col.bounding_box = bbox
    bvh_col.node_count = bvhc_raw["nodeCount"]
    bvh_col.nulls = [0, 0, 0]
    bvh_nodes = []
    for bvnode in bvhc_raw["AABBArray"]:
        bvh_node.node_type = bvnode["nodeType"]
        bvh_node.node_id = bvnode["nodeId"]
        bvh_node.unk_05 = 0  # 0xCDCDCDCD
        min_aabb = bvnode["minAABB"]
        aabb.x = min_aabb["xArray"]
        aabb.y = min_aabb["yArray"]
        aabb.z = min_aabb["zArray"]
        bvh_node.min_aabb = aabb
        max_aabb = bvnode["maxAABB"]
        aabb.x = max_aabb["xArray"]
        aabb.y = max_aabb["yArray"]
        aabb.z = max_aabb["zArray"]
        bvh_node.max_aabb = aabb
        bvh_nodes.append(bvh_node)
    bvh_col.nodes = bvh_nodes
    bvh_col._check()
    print("SBC BVH started")
    return bvh_col


def _serialize_faces(dst_sbc, face_data):
    faces = []
    print("lenght of face data is {}".format(len(face_data)))
    for f in face_data:
        face = dst_sbc.Face(_parent=dst_sbc, _root=dst_sbc._root)
        face_raw = f.triSerialize()
        face.normal = face_raw["normal"]
        face.vert = face_raw["vert"]
        face.type = face_raw["type"]
        face.nulls = face_raw["null1"]
        face.adjacent = face_raw["adjacent"]
        face.nulls_01 = face_raw["null2"]
        face.nulls_02 = face_raw["null3"]
        face._check()
        faces.append(face)
    return faces

def _serialize_vertices(dst_sbc, vertex_data):
    vertices = []
    for v in vertex_data:
        dst_vertex = dst_sbc.Vertex(_parent=dst_sbc, _root=dst_sbc._root)
        vertex_raw = geo.vec_unfold(v)
        dst_vertex.x = vertex_raw["x"]
        dst_vertex.y = vertex_raw["y"]
        dst_vertex.z = vertex_raw["z"]
        dst_vertex.w = vertex_raw["w"]
        #dst_vertex._check()
        vertices.append(dst_vertex)
    return vertices

def _serialize_col_types(dst_sbc, col_types_data):
    coltype = dst_sbc.CollisionType(_parent=dst_sbc, _root=dst_sbc._root)
    coltype.unk_01 = col_types_data["unk_01"]
    coltype.unk_02 = col_types_data["unk_02"]
    coltype.unk_03 = col_types_data["unk_03"]
    coltype.unk_04 = [v for v in col_types_data["unk_04"]]
    coltype.jp_path = col_types_data["jp_path"]
    coltype._check()
    return coltype


def _serialize_pairs(dst_sbc, pairs_data):
    pairs = []
    pair = dst_sbc.SFacePair(_parent=dst_sbc, _root=dst_sbc._root)
    for pd in pairs_data:
        pair_raw = pd.primitiveSerialize()
        pair.face_01 = pair_raw["face1"]
        pair.face_02 = pair_raw["face2"]
        pair.quad_order = pair_raw["quadOrder"]
        pair.type = pair_raw["type"]
        pair._check()
        pairs.append(pair)
    return pairs


def _serialize_infos(dst_sbc, faces, vertices, stages, pairs, sbcs, sbcC, metadata):
    f0, v0, p0 = 0, 0, 0,
    infos = []
    info = dst_sbc.Info(_parent=dst_sbc, _root=dst_sbc._root)
    bbox = dst_sbc.Bbox(_parent=info, _root=dst_sbc._root)
    for f, v, p, s, m in zip(faces, vertices, pairs, sbcs, metadata):
        bbox_data = get_vertex_box(v).serialize()
        bbox.min = [v for v in bbox_data["minPos"].values()]
        bbox.max = [v for v in bbox_data["maxPos"].values()]
        info.unk_01 = 0  # not really, looks like a hash
        info.nulls_01 = [0, 0]
        info.bounding_box = bbox
        info.pairs_start = f0
        info.pairs_count = len(p)
        info.faces_start = f0
        info.face_count = len(f)
        info.vertex_start = v0
        info.vertex_count = len(v)
        info.index_id = int(m["indexID"])  # something wrong
        info.nulls_02 = [0, 0]
        info._check()
        f0 += len(f)
        v0 += len(v)
        p0 += len(p)
        infos.append(info)
    return infos


def get_vertex_box(v):
    return geo.BoundingBox(v)


class SemiTri():
    def __init__(self, face, matType=None):
        if not len(face.verts) == 3:
            raise TriangulationRequiredError()
        self.vert = [int(v.index) for v in face.verts]
        self.adjacent = self.getAdjacent(face)
        self.normal = SemiTri.calcNormal(face)
        self.type = matType
        # (0 = 90°, 1 = 0°, 2 > 180°, 3<180°)

    def getAdjacent(self, face):
        adjacents = []
        for edge in face.edges:
            bA = None
            for lf in edge.link_faces:
                if lf != face:
                    bA = SemiTri.byteAngle(face, lf)
            if bA is None:
                bA = 0
            adjacents.append(bA)
        return adjacents

    def setIndex(self, value):
        self._index = value
        return self

    def index(self):
        return self._index

    @staticmethod
    def calcNormal(face1):
        v = Vector(np.cross(
            face1.verts[1].co - face1.verts[0].co, face1.verts[2].co - face1.verts[0].co))
        v.normalize()
        return v

    @staticmethod
    def edges(face):
        e1 = cycles(face.verts)
        return e1

    @staticmethod
    def barycenter(face):
        return sum([v.co for v in face.verts], Vector([0, 0, 0])) / len(face.verts)

    @staticmethod
    def byteAngle(face1, face2):
        n1 = SemiTri.calcNormal(face1)
        n2 = SemiTri.calcNormal(face2)
        fv1 = [v.co for v in face1.verts]
        e1 = SemiTri.edges(face1)
        e2 = SemiTri.edges(face2)
        facing = None
        for ix, e in enumerate(e1):
            if tuple(reversed(e)) in e2:
                edgem = (fv1[ix] + fv1[(ix + 1) % 3]) / 2
                bary = (SemiTri.barycenter(face1) + SemiTri.barycenter(face2)) / 2
                facing = bary - edgem
                facing.normalize()
        if facing is None:
            # Not exactly correct but correct most of the time (1.5% fail rate)
            return 0

        if (n1 - n2).magnitude < eps:
            return 1
        if (n1 + n2).magnitude < eps:
            return 4
        n = (n1 + n2)
        n.normalize()
        signum = (n1 + n2).dot(facing) > 0
        if not signum:
            if n1.dot(n2) < eps:
                return 0
            return 2
        else:
            return 4

    @staticmethod
    def getMaterial(face, mesh):
        try:
            ix = face.material_index
            slot = mesh.material_slots[ix]
            mat = slot.material.name
            return int(mat[len("Type "):len("Type 000")])
        except IndexError:
            raise MaterialMissingError

def mesh_to_tri(mesh):
    bm = bmesh.new()
    # bm.from_object(mesh, bpy.context.scene)
    bm.from_mesh(mesh.data)
    vertices = [Vector(v.co) for v in bm.verts]
    faces = [Tri(SemiTri(face, SemiTri.getMaterial(face, mesh)), vertices)
             for face in bm.faces]
    bm.free()
    return vertices, faces


def mesh_rescale(ob):
    '''Meshes should be transformed back to the game's up axis and scale'''
    bpy.ops.object.mode_set(mode='OBJECT')
    mesh = ob.data

    # Swap Y and Z coordinates for each vertex and rescale
    for vert in mesh.vertices:
        x = vert.co.x * 100
        y = vert.co.y * -100
        z = vert.co.z * 100
        vert.co.x = x
        vert.co.y = z
        vert.co.z = y
    return ob


@blender_registry.register_export_function(app_id="dmc4", extension="sbc")
@blender_registry.register_export_function(app_id="re5", extension="sbc")
def export_sbc156(bl_obj):
    """Every mesh under the root is one or more collision groups (split at 65,536 vertices); faces are triangulated,
    modifiers applied, and the geometry is written relative to the root Empty (a stage's root sits at the origin; a
    moving part's .sbc is in its unit's local frame, so its root can be parented to the unit to preview it in place).
    The trees are rebuilt from scratch by sbc_bvh."""
    asset = bl_obj.albam_asset
    groups, notes = sbc156_groups(bl_obj)
    try:
        data = sbc_bvh.build_sbc1(groups)
    except sbc_bvh.SbcBuildError as err:
        raise AlbamCheckFailure(
            f"Collision {bl_obj.name} can't be exported",
            details=str(err),
            solution="Fix the listed meshes (remove empty or broken meshes, split very large ones).")
    print(f"SBC export {asset.relative_path}: {len(groups)} group(s), "
          f"{sum(len(g.triangles) for g in groups)} triangles")
    for note in notes:
        print("  " + note)
    bl_obj["sbc_export_notes"] = notes[:200]
    return [VirtualFileData(asset.app_id, asset.relative_path, data_bytes=data)]


def sbc156_meshes(bl_obj):
    """Collision meshes under the root, in group order (imported index, then name)."""
    meshes = [c for c in bl_obj.children_recursive if c.type == "MESH"]
    return sorted(meshes, key=lambda ob: (ob.get(SBC_GROUP_INDEX, 1 << 30), ob.name))


def _legacy_group_ids(bl_obj, meshes):
    """Group IDs for collision imported before the meshes stored them: the source file's, by mesh order, when no
    mesh has the property and the mesh count still equals the source's group count. Else None."""
    if any(SBC_GROUP_ID in ob for ob in meshes):
        return None
    try:
        source = sbc_bvh.read_sbc1_groups(bytes(bl_obj.albam_asset.original_bytes))
    except Exception:
        return None
    if len(source) != len(meshes):
        return None
    return [g.group_id for g in source]


def sbc156_groups(bl_obj):
    """-> (SbcGroup list, notes). Coordinates go back to game space (cm, Y up), relative to the root Empty."""
    bpy.context.view_layer.update()     # matrix_world is still identity right after an import or a parenting
    depsgraph = bpy.context.evaluated_depsgraph_get()
    to_root = bl_obj.matrix_world.inverted()
    groups, notes = [], []
    meshes = sbc156_meshes(bl_obj)
    if not meshes:
        raise AlbamCheckFailure(
            f"Collision {bl_obj.name} has no meshes",
            details="The collision root has no mesh children, so there is nothing to export.",
            solution="Parent the collision meshes to the root Empty.")
    legacy_ids = _legacy_group_ids(bl_obj, meshes)
    if legacy_ids:
        notes.append("group IDs taken from the source file by mesh order (imported before IDs were kept)")
    for mesh_index, ob in enumerate(meshes):
        if ob.mode == "EDIT":
            ob.update_from_editmode()
        ob_eval = ob.evaluated_get(depsgraph)
        bm = bmesh.new()
        bm.from_mesh(ob_eval.to_mesh())
        ob_eval.to_mesh_clear()
        local = to_root @ ob.matrix_world
        bm.transform(local)
        if local.determinant() < 0:
            # a mirroring transform turns the faces inside out; collision is one-sided (floors must face up)
            bmesh.ops.reverse_faces(bm, faces=bm.faces[:])
            notes.append(f"{ob.name}: mirrored by its transform, face winding kept")
        layers = [bm.faces.layers.int.get(name) for name in FACE_LAYERS]
        missing = [name for name, layer in zip(FACE_LAYERS[:3], layers) if layer is None]
        if missing:
            notes.append(f"{ob.name}: no {', '.join(missing)} face values, written as 0 (Auto)")
        ngons = [f for f in bm.faces if len(f.verts) > 3]
        if ngons:
            bmesh.ops.triangulate(bm, faces=ngons)
            notes.append(f"{ob.name}: {len(ngons)} faces triangulated")
        tiny = [f for f in bm.faces if f.calc_area() < MIN_TRIANGLE_AREA]
        if tiny:
            notes.append(f"{ob.name}: {len(tiny)} zero-area triangles skipped")
        tiny = set(tiny)
        group_id = ob.get(SBC_GROUP_ID, legacy_ids[mesh_index] if legacy_ids else -1) & 0xFFFFFFFF
        faces = list(bm.faces)
        if len(bm.verts) > sbc_bvh.MAX_INDEX + 1:
            # will be split: take faces along the longest axis so each part is a compact slab
            lo = [min(v.co[a] for v in bm.verts) for a in range(3)]
            hi = [max(v.co[a] for v in bm.verts) for a in range(3)]
            axis = max(range(3), key=lambda a: hi[a] - lo[a])
            faces.sort(key=lambda f: f.calc_center_median()[axis])
        chunk = None
        part = 0
        for face in faces:
            if face in tiny:
                continue
            if chunk is None or len(chunk[0]) + 3 > sbc_bvh.MAX_INDEX + 1 or len(chunk[1]) > sbc_bvh.MAX_INDEX:
                if chunk is not None:
                    groups.append(sbc_bvh.SbcGroup(*chunk[:3], group_id=group_id, name=f"{ob.name} part {part}"))
                    part += 1
                chunk = ([], [], [], {})
            vertices, triangles, attributes, remap = chunk
            tri = []
            for v in face.verts:
                index = remap.get(v.index)
                if index is None:
                    index = remap[v.index] = len(vertices)
                    x, y, z = v.co
                    vertices.append((x * 100.0, z * 100.0, y * -100.0))
                tri.append(index)
            triangles.append(tri)
            attributes.append(tuple(face[layer] & 0xFFFFFFFF if layer is not None else 0 for layer in layers))
        bm.free()
        if chunk is None:
            notes.append(f"{ob.name}: no triangles, skipped")
            continue
        name = ob.name if part == 0 else f"{ob.name} part {part}"
        groups.append(sbc_bvh.SbcGroup(*chunk[:3], group_id=group_id, name=name))
        if part:
            notes.append(f"{ob.name}: split into {part + 1} groups (65,536 vertices per group at most)")
    return groups, notes


# ---- part IDs (moving collision) ---------------------------------------------------------------------------------

def sbc_root(ob):
    """The collision root Empty above a mesh (albam_asset extension sbc), or None."""
    while ob is not None:
        if ob.albam_asset.extension == "sbc" and ob.albam_asset.relative_path:
            return ob
        ob = ob.parent
    return None


def part_id(ob):
    return ob.get(SBC_GROUP_ID, -1)


@blender_registry.register_blender_type
class ALBAM_OT_SbcSetPartId(bpy.types.Operator):
    """Set the part ID (the group record's group_id) of the selected collision meshes. A moving piece's meshes need
    the ID its unit moves (uStageSetMoveFloor mPartsId, usually 0); static collision uses -1"""
    bl_idname = "albam.sbc_set_part_id"
    bl_label = "Set Part ID"
    bl_options = {"REGISTER", "UNDO"}

    part_id: bpy.props.IntProperty(
        name="Part ID",
        description="group_id written for the selected collision meshes: -1 = never moved or switched (static "
                    "stage collision); 0 and up = the ID a moving unit (uStageSetMoveFloor mPartsId) or a script "
                    "(Sbc::activateParts) uses for these triangles",
        default=0, min=-1, max=0x7FFFFFFF)

    @classmethod
    def poll(cls, context):
        return any(o.type == "MESH" and sbc_root(o) for o in context.selected_objects)

    def invoke(self, context, event):
        if context.object is not None and sbc_root(context.object):
            self.part_id = part_id(context.object)
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        meshes = [o for o in context.selected_objects if o.type == "MESH" and sbc_root(o)]
        for o in meshes:
            o[SBC_GROUP_ID] = self.part_id
        self.report({"INFO"}, f"Part ID {self.part_id} on {len(meshes)} collision mesh(es)")
        return {"FINISHED"}


@blender_registry.register_blender_type
class ALBAM_PT_SbcPart(bpy.types.Panel):
    bl_label = "Collision Part"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "object"

    @classmethod
    def poll(cls, context):
        ob = context.object
        return ob is not None and ob.type == "MESH" and sbc_root(ob) is not None and \
            sbc_root(ob).albam_asset.app_id == "dmc4"

    def draw(self, context):
        ob = context.object
        layout = self.layout
        pid = part_id(ob)
        row = layout.row()
        row.label(text=f"Part ID: {pid}" + ("  (static)" if pid == -1 else ""), icon="MOD_PHYSICS")
        row.operator("albam.sbc_set_part_id", text="Set", icon="GREASEPENCIL")
        col = layout.column(align=True)
        col.label(text=f"Root: {sbc_root(ob).name} (geometry is exported relative to it)", icon="EMPTY_AXIS")
        if pid >= 0:
            col.label(text="Moves with the unit whose mPartsId is this ID", icon="INFO")

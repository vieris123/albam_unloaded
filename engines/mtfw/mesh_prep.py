"""Meshes as the .mod export needs them (DMC4, 2026-10-28).

The vertex export writes one value per vertex: the UVs and normal of the vertex's first corner (get_uvs_per_vertex,
get_normals_per_vertex), and the strip builder assumes triangles. Imported meshes are like that already; a mesh made
in Blender usually isn't: quads, UV seams and flat or sharp shading share vertices between corners that need
different values, and its object may sit somewhere other than its model root, whose frame the export writes.

`prepared_meshes` gives export a temporary copy of each mesh that needs it (never changing the user's mesh):
- the object's transform relative to the model root applied to the vertices;
- faces with more than 3 corners triangulated;
- vertices split along edges whose two faces disagree there: any UV layer, or the corner normal (flat faces, sharp
  edges, custom normals); custom normals are set again on the split copy.
A mesh that needs none of it is passed through as it is, so imported meshes export exactly as before.
"""
import bmesh
import bpy
from mathutils import Matrix

UV_TOLERANCE = 1e-5
NORMAL_TOLERANCE = 2e-3        # 1 - cos of the angle between two corner normals (~3.6 deg): imported custom
                               # normals drift by up to ~0.8 deg between corners of one vertex (em010_01 mesh 5)
TRANSFORM_TOLERANCE = 1e-6
FLAT_AREA = 1e-12              # faces this small have no meaningful corner normals (the attr 1 "fin" meshes are all
                               # zero-area triangles): their normals aren't compared


def relative_matrix(root, ob):
    """ob's transform in its model root's frame (the frame the export writes)"""
    return root.matrix_world.inverted_safe() @ ob.matrix_world


def _is_identity(m):
    identity = Matrix.Identity(4)
    return all(abs(m[i][j] - identity[i][j]) < TRANSFORM_TOLERANCE for i in range(4) for j in range(4))


def _corner_normals(me):
    """corner (loop) normal vectors, as Blender shades the mesh: smooth / flat faces, sharp edges, custom normals"""
    return [tuple(n.vector) for n in me.corner_normals]


def _same_normal(a, b):
    """True if the corner normals agree, or either is zero (Blender gives near-degenerate faces zero corner normals:
    3 stage meshes of st001 have them; they carry no shading to keep)"""
    dot = a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
    if a[0] * a[0] + a[1] * a[1] + a[2] * a[2] < 0.25 or b[0] * b[0] + b[1] * b[1] + b[2] * b[2] < 0.25:
        return True
    return 1.0 - dot < NORMAL_TOLERANCE


def _same_uv(a, b):
    return abs(a[0] - b[0]) < UV_TOLERANCE and abs(a[1] - b[1]) < UV_TOLERANCE


def _corner_at(loop, vert):
    """the corner of loop's face at vert, one end of loop's edge"""
    return loop if loop.vert == vert else loop.link_loop_next


def _split_edges(bm, normals):
    """edges whose two faces have different UVs or corner normals at either end. normals: {BMLoop.index: vector}
    (the caller numbers the corners as the mesh does)"""
    uv_layers = list(bm.loops.layers.uv.values())
    split = []
    for edge in bm.edges:
        if len(edge.link_loops) != 2:
            continue
        a, b = edge.link_loops
        pairs = [(_corner_at(a, v), _corner_at(b, v)) for v in edge.verts]
        shaded = a.face.calc_area() > FLAT_AREA and b.face.calc_area() > FLAT_AREA
        if (shaded and any(not _same_normal(normals[x.index], normals[y.index]) for x, y in pairs)) or \
                any(not _same_uv(x[layer].uv, y[layer].uv) for layer in uv_layers for x, y in pairs):
            split.append(edge)
    return split


def needs_preparing(root, ob):
    """why ob's mesh can't be exported as it is: a list of reasons ('moved', 'n-gons', 'seams'), empty if it can"""
    me = ob.data
    reasons = []
    if not _is_identity(relative_matrix(root, ob)):
        reasons.append("moved")
    if any(p.loop_total > 3 for p in me.polygons):
        reasons.append("n-gons")
        return reasons
    normals = _corner_normals(me)
    vertex_normal, vertex_uvs = {}, {}
    uv_data = [layer.data for layer in me.uv_layers]
    for p in me.polygons:
        shaded = p.area > FLAT_AREA
        for i in p.loop_indices:
            v = me.loops[i].vertex_index
            uvs = [tuple(d[i].uv) for d in uv_data]
            if v not in vertex_uvs:
                vertex_uvs[v] = uvs
            elif any(not _same_uv(a, b) for a, b in zip(vertex_uvs[v], uvs)):
                reasons.append("seams")
                return reasons
            if not shaded:
                continue
            n = normals[i]
            if v not in vertex_normal:
                if n[0] * n[0] + n[1] * n[1] + n[2] * n[2] >= 0.25:   # a zero normal isn't a reference
                    vertex_normal[v] = n
            elif not _same_normal(vertex_normal[v], normals[i]):
                reasons.append("seams")
                return reasons
    return reasons


def prepared_mesh(root, ob):
    """a new Mesh: ob's mesh in the root's frame, triangulated, split where corners differ (see the module doc)"""
    me = ob.data.copy()
    matrix = relative_matrix(root, ob)
    if not _is_identity(matrix):
        me.transform(matrix)
        if matrix.determinant() < 0:   # a mirroring transform turns the faces inside out
            me.flip_normals()
    bm = bmesh.new()
    bm.from_mesh(me)
    ngons = [f for f in bm.faces if len(f.verts) > 3]
    if ngons:
        bmesh.ops.triangulate(bm, faces=ngons)
    bm.to_mesh(me)
    bm.free()

    custom = me.has_custom_normals
    normals = _corner_normals(me)
    bm = bmesh.new()
    bm.from_mesh(me)
    index = 0
    for face in bm.faces:            # number the corners as the mesh does (faces in order, corners in order)
        for loop in face.loops:
            loop.index = index
            index += 1
    corner = {loop.index: normals[loop.index] for face in bm.faces for loop in face.loops}
    edges = _split_edges(bm, corner)
    face_normals = [[corner[loop.index] for loop in face.loops] for face in bm.faces]
    if edges:
        bmesh.ops.split_edges(bm, edges=edges)
    bm.to_mesh(me)
    bm.free()
    if custom:   # the split keeps faces and corners in order
        me.normals_split_custom_set([n for face in face_normals for n in face])
    return me


def prepared_meshes(root, obs):
    """(objects to export, temporary objects to remove afterwards): obs, with a temporary copy (not in any scene)
    in place of each mesh object needs_preparing; its mesh is prepared_mesh, its vertex groups, materials and
    modifiers are the original's"""
    result, temporary = [], []
    for ob in obs:
        if not needs_preparing(root, ob):
            result.append(ob)
            continue
        copy = ob.copy()
        copy.data = prepared_mesh(root, ob)
        copy["albam_export_copy_of"] = ob.name
        result.append(copy)
        temporary.append(copy)
    return result, temporary


def remove_temporary(temporary):
    for ob in temporary:
        me = ob.data
        bpy.data.objects.remove(ob, do_unlink=True)
        if me is not None and me.users == 0:
            bpy.data.meshes.remove(me)

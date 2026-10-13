"""Headless test: line ribbons built by the Ribbons node group match the camera-facing strips the points describe
(each point +/- half along normalize((next - previous) x (eye - point))), with the points' UVs and colours."""
import os, sys  # noqa: E401
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tests/: common.py
import common  # noqa: E402  (game data / add-on / output paths)
import traceback  # noqa: E402
from types import SimpleNamespace  # noqa: E402

common.register()
import bpy  # noqa: E402
from mathutils import Vector  # noqa: E402
from albam.engines.mtfw import effect, effect_sim  # noqa: E402

failures = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


def expected_strip(ob, eye_local):
    """The strip the Python description of the points implies, as (vertex positions, uv per vertex, colour per
    vertex) in the chain order (left, right per point)."""
    me = ob.data
    n = len(me.vertices)
    pos = [me.vertices[i].co.copy() for i in range(n)]
    half = [me.attributes["half"].data[i].value for i in range(n)]
    uv_l = [tuple(me.attributes["uv_l"].data[i].vector) for i in range(n)]
    uv_r = [tuple(me.attributes["uv_r"].data[i].vector) for i in range(n)]
    col = [tuple(me.color_attributes["EdgeAlpha"].data[i].color) for i in range(n)]
    chains, chain = [], []
    linked = {}
    for e in me.edges:
        a, b = e.vertices
        linked.setdefault(a, []).append(b)
        linked.setdefault(b, []).append(a)
    for i in range(n):   # chains are stored in order: a vertex starts one when nothing links to it from before
        if i - 1 in linked.get(i, ()):
            chain.append(i)
        else:
            if chain:
                chains.append(chain)
            chain = [i]
    if chain:
        chains.append(chain)
    verts, uvs, cols = [], [], []
    for c in chains:
        for k, i in enumerate(c):
            nxt, prv = c[min(k + 1, len(c) - 1)], c[max(k - 1, 0)]
            tangent = pos[nxt] - pos[prv]
            side = tangent.cross(eye_local - pos[i])
            if side.length < 1e-12:
                side = tangent.cross(Vector((0, 0, 1)))
            side = side.normalized() * half[i]
            verts += [pos[i] - side, pos[i] + side]
            uvs += [uv_l[i], uv_r[i]]
            cols += [col[i], col[i]]
    return verts, uvs, cols, [len(c) for c in chains]


try:
    scene = bpy.context.scene
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob)
    scene.render.fps = 60
    scene.frame_start, scene.frame_end, scene.frame_current = 1, 200, 1
    scene.albam.import_options_efl.load_textures = False
    em009 = os.path.join(common.ARCTOOL, "em009")
    cases = [(common.NERO, r"effect\efl\com\ec024_60v2.efl")]
    if os.path.isdir(em009):
        cases.append((em009, r"effect\efl\ene\ee008_40v0.efl"))   # chains (ropes) and Texlines
    for root_dir, rel in cases:
        scene.albam.rfs.add_root_folder("dmc4", root_dir)
        data = open(os.path.join(root_dir, rel), "rb").read()
        effect.load_efl(SimpleNamespace(app_id="dmc4", display_name=os.path.basename(rel), relative_path=rel,
                                        get_bytes=lambda: data), bpy.context)
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
    scene.collection.objects.link(cam)
    scene.camera = cam
    cam.location = (0.5, -3.0, 1.2)
    cam.rotation_euler = (1.3, 0.0, 0.2)
    bpy.context.view_layer.update()
    lines = [o for o in effect_sim._sim_objects(scene) if o[effect_sim.SIM_KEY]["kind"] in effect_sim.LINE_KINDS]
    check(all(any(m.type == "NODES" and m.node_group and m.node_group.name == effect_sim.LINE_NODE_GROUP
                  for m in o.modifiers) for o in lines), f"every line object ({len(lines)}) has the Ribbons modifier")

    checked = worst = 0
    bad_uv = bad_col = bad_faces = 0
    for f in (8, 30, 70):
        scene.frame_set(f)
        dg = bpy.context.evaluated_depsgraph_get()
        for ob in lines:
            if not len(ob.data.vertices):
                continue
            eye = ob.matrix_world.inverted() @ cam.matrix_world.translation
            verts, uvs, cols, layout = expected_strip(ob, eye)
            ev = ob.evaluated_get(dg).to_mesh()
            try:
                if len(ev.vertices) != len(verts):
                    bad_faces += 1
                    continue
                got = [v.co.copy() for v in ev.vertices]
                # strip vertices come out in chain order, two per point: match each expected vertex to the nearest
                dev = max((min((got[2 * i] - verts[2 * i]).length, (got[2 * i + 1] - verts[2 * i]).length)
                           for i in range(len(verts) // 2)), default=0.0)
                worst = max(worst, dev)
                if len(ev.polygons) != sum(n - 1 for n in layout):
                    bad_faces += 1
                uv = ev.attributes.get("UVMap")
                col = ev.color_attributes.get("EdgeAlpha")
                for poly in ev.polygons:
                    for li, vi in zip(poly.loop_indices, poly.vertices):
                        off_l = max(abs(a - b) for a, b in zip(uv.data[li].vector, uvs[vi])) if uv is not None else 0.0
                        off_r = max(abs(a - b) for a, b in zip(uv.data[li].vector, uvs[vi ^ 1])) if uv is not None else 0.0
                        if off_l > 1e-5 and off_r > 1e-5:
                            bad_uv += 1
                        if col is not None and max(abs(a - b) for a, b in zip(col.data[vi].color, cols[vi])) > 1e-5:
                            bad_col += 1
                checked += 1
            finally:
                ob.evaluated_get(dg).to_mesh_clear()
    check(checked > 20, f"{checked} line systems compared over 3 frames")
    check(worst < 1e-5, f"strip vertices match the Python description (worst deviation {worst:.2e} m)")
    check(bad_faces == 0, f"every chain gives points - 1 quads ({bad_faces} systems off)")
    check(bad_uv == 0, f"corner UVs are the points' left / right UVs ({bad_uv} off)")
    check(bad_col == 0, f"vertex colours ride along ({bad_col} off)")

    # the eye follows the camera: moving it changes the strips without a frame change
    scene.frame_set(30)
    ob = next(o for o in lines if len(o.data.vertices))
    dg = bpy.context.evaluated_depsgraph_get()
    before = [v.co.copy() for v in ob.evaluated_get(dg).to_mesh().vertices]
    ob.evaluated_get(dg).to_mesh_clear()
    cam.location = (-3.0, 0.5, 1.2)
    bpy.context.view_layer.update()
    scene.frame_set(30)
    dg = bpy.context.evaluated_depsgraph_get()
    after = [v.co.copy() for v in ob.evaluated_get(dg).to_mesh().vertices]
    ob.evaluated_get(dg).to_mesh_clear()
    check(any((a - b).length > 1e-6 for a, b in zip(before, after)), "the strips turn toward a moved camera")
except Exception:
    traceback.print_exc()
    failures.append("exception")
print("FAILURES:", failures)

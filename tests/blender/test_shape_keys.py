"""Shape keys export as the game's morph targets (shape_keys.py, shape_format.py): on Nero's body, a mesh with keys gets
the shape flag, a skin-5 material record (a copy when the material also draws plain meshes), its texels in TEXCOORD0 and
its UV in TEXCOORD1, everything else stays as it was; the .shp holds the deltas in game axes (vertex groups, a moved
mesh), the .shw the keys' curves on game frames; bad materials are refused; ModelExtension <shape> / <weights> entries;
the format agrees with the hand-made files that worked in the game."""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import common  # noqa: E402

common.register()
import io  # noqa: E402
import bpy  # noqa: E402
from mathutils import Matrix  # noqa: E402
from albam.exceptions import AlbamCheckFailure  # noqa: E402
from albam.engines.mtfw import mesh, model_ext, shape_format, shape_keys  # noqa: E402
from albam.engines.mtfw.movedef import ext_list  # noqa: E402
from albam.lib import blender_compat  # noqa: E402
from albam.lib.blender_compat import action_fcurves  # noqa: E402

failures = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


BODY = r"model\game\pl000\pl000.mod"
REFERENCE = os.path.join(common.DATA, "Vibed", "ShapeTest", "out", "shape_test")   # the in-game test kit's files
common.skip_unless(os.path.join(common.NERO, BODY))
scene = bpy.context.scene
scene.albam.rfs.add_root_folder("dmc4", common.NERO)


def parse(data):
    m = mesh.Mod153(mesh.KaitaiStream(io.BytesIO(bytes(data))))
    m._read()
    return m


def export(root):
    """{extension: file} for the .mod / .shp / rest .shw, {lower path: file} for every file under "all\""""
    files = mesh.export_mod(root)
    stem = root.albam_asset.relative_path.rsplit(".", 1)[0].lower()
    out = {v.relative_path.lower()[len(stem) + 1:]: v for v in files if v.relative_path.lower() in
           (stem + ".mod", stem + ".shp", stem + ".shw")}
    out["all"] = {v.relative_path.lower(): v for v in files}
    return out


def vertex(mod, me, k):
    """raw 32 bytes of vertex k of a mesh record"""
    start = me.vertex_offset + (me.face_offset + me.min_index + k) * me.vertex_stride
    return bytes(mod.vertex_buffer[start:start + me.vertex_stride])


def props(mat):
    return mat.albam_custom_properties.get_custom_properties_for_appid("dmc4")


try:
    # -- the reference files of the in-game test parse and rebuild byte for byte --------------------------------------
    if os.path.exists(REFERENCE + ".shp"):
        shp = open(REFERENCE + ".shp", "rb").read()
        shw = open(REFERENCE + ".shw", "rb").read()
        maps, targets = shape_format.parse_shp(shp)
        rebuilt = shape_format.build_shp([(m.part, m.width, m.height) for m in maps], targets)
        check(rebuilt == shp, f"reference .shp: {len(maps)} maps, {len(targets)} targets rebuild byte for byte")
        frame_max, first, index, curves = shape_format.parse_shw(shw)
        check(index == list(range(len(curves))) and shape_format.build_shw(curves, frame_max, first) == shw,
              f"reference .shw: {len(curves)} curves rebuild byte for byte")
        check(abs(shape_format.evaluate(curves[0], 30) - 0.5) < 1e-6, "reference curve 0 is 0.5 at frame 30")
    else:
        print("note: no reference files, skipped")
    check(shape_format.linear_keys([0, 0, 0, 1, 2, 3, 3]) == [(0, 0), (2, 0), (5, 3), (6, 3)],
          "linear keys keep only the corners")
    check([shape_format.texel(n) for n in (0, 254, 255, 600)] == [(0, 0), (254, 0), (0, 1), (90, 2)],
          "texels skip the last column")
    check([shape_format.map_height(n) for n in (1, 255, 256, 510, 511)] == [2, 2, 3, 3, 4], "map heights")

    # -- Nero's body ---------------------------------------------------------------------------------------------------
    item = next(i for i in scene.albam.rfs.file_list if i.name.lower().endswith(BODY.lower().replace("\\", "::")))
    before = set(bpy.data.objects)
    mesh.build_blender_model(item, bpy.context)
    arm = next(o for o in set(bpy.data.objects) - before if o.type == "ARMATURE")
    if arm.name not in scene.collection.objects:
        scene.collection.objects.link(arm)
    meshes = [c for c in arm.children_recursive if c.type == "MESH"]
    base = export(arm)
    check("shp" not in base and "shw" not in base, "no shape keys: no .shp / .shw")
    base_mod = parse(base["mod"].data_bytes)

    def usable(ob):
        p = props(ob.data.materials[0])
        return int(p.vtype, 16) == 0 and shape_keys.shader_key(p) in shape_keys.SHADER_KEYS

    users = {}
    for i, ob in enumerate(meshes):
        users.setdefault(ob.data.materials[0].name, []).append(i)
    shared = [i for i, ob in enumerate(meshes) if usable(ob) and len(users[ob.data.materials[0].name]) > 1]
    alone = [i for i, ob in enumerate(meshes) if usable(ob) and len(users[ob.data.materials[0].name]) == 1]
    check(bool(shared) and bool(alone), f"pl000 has meshes to test with ({len(shared)} shared, {len(alone)} alone)")
    part = lambda ob: ob.data.albam_custom_properties.get_custom_properties_for_appid("dmc4").idx_group  # noqa: E731
    alone.sort(key=lambda i: part(meshes[i]) == part(meshes[shared[0]]))    # another part first: two maps
    a, b = meshes[shared[0]], meshes[alone[0]]
    part_a = a.data.albam_custom_properties.get_custom_properties_for_appid("dmc4").idx_group
    part_b = b.data.albam_custom_properties.get_custom_properties_for_appid("dmc4").idx_group
    print(f"mesh a {a.name} (part {part_a}, {len(a.data.vertices)} vertices, material {a.data.materials[0].name} "
          f"shared), mesh b {b.name} (part {part_b}, {len(b.data.vertices)} vertices)")

    # keys: Up on a (all +0.1 m z, keyed 0 -> 1 over 30 frames at 30 fps), Side on a (+0.05 m x, half the vertices by a
    # vertex group, set to 0.5), Muted on a, Up on b (same name, another part: another target)
    scene.render.fps, scene.render.fps_base = 30, 1.0
    for ob in (a, b):
        ob.shape_key_add(name="Basis")
    up = a.shape_key_add(name="Up", from_mix=False)
    for d in up.data:
        d.co.z += 0.1
    side = a.shape_key_add(name="Side", from_mix=False)
    for d in side.data:
        d.co.x += 0.05
    group = a.vertex_groups.new(name="side_half")
    half = [v.index for v in a.data.vertices if v.index % 2 == 0]
    group.add(half, 0.5, "REPLACE")
    side.vertex_group = group.name
    side.value = 0.5
    muted = a.shape_key_add(name="Muted", from_mix=False)
    for d in muted.data:
        d.co.y += 1.0
    muted.mute = True
    zero = a.shape_key_add(name="Zero", from_mix=False)     # left at 0, not animated: an unused expression
    for d in zero.data:
        d.co.y += 1.0
    zero.value = 0.0        # Blender 5 makes new keys at 1, 4.2 at 0
    c = meshes[next(i for i in range(len(meshes)) if i not in (shared[0], alone[0]))]
    c.shape_key_add(name="Basis")
    unused = c.shape_key_add(name="Unused", from_mix=False)
    for d in unused.data:
        d.co.z += 1.0
    unused.value = 0.0
    up.value = 0.0
    up.keyframe_insert("value", frame=10)
    up.value = 1.0
    up.keyframe_insert("value", frame=40)
    key_a = a.data.shape_keys
    smile = key_a.animation_data.action
    smile.name = "smile"
    # a second clip, stashed in the NLA: Side 0 -> 1 over frames 1-7
    blink = bpy.data.actions.new("blink")
    blender_compat.assign_action(key_a, blink)
    side.value = 0.0
    side.keyframe_insert("value", frame=1)
    side.value = 1.0
    side.keyframe_insert("value", frame=7)
    track = key_a.animation_data.nla_tracks.new()
    track.strips.new("blink", 1, blink)
    blender_compat.assign_action(key_a, smile)
    side.value = 0.5
    for action in (smile, blink):
        for fc in action_fcurves(action):
            for kp in fc.keyframe_points:
                kp.interpolation = "LINEAR"
    up_b = b.shape_key_add(name="Up", from_mix=False)
    for d in up_b.data:
        d.co.z += 0.02
    up_b.value = 1.0

    files = export(arm)
    check({"mod", "shp", "shw"} <= set(files), "the export writes .mod, .shp and .shw")
    stem = BODY.rsplit(".", 1)[0].lower()
    check(files["shp"].relative_path.lower() == stem + ".shp" and files["shw"].relative_path.lower() == stem + ".shw",
          "beside the .mod, at its path")
    mod = parse(files["mod"].data_bytes)
    mats = mod.materials_data.materials
    i_a, i_b = shared[0], alone[0]
    check([m.shape for m in mod.meshes_data.meshes] == [i in (i_a, i_b) for i in range(len(meshes))],
          "shape flag on the two morphing meshes only (a mesh whose only key stays at 0 doesn't morph)")
    check(len(mats) == len(base_mod.materials_data.materials) + 1, "one more material record (the shared one's copy)")
    me_a, me_b = mod.meshes_data.meshes[i_a], mod.meshes_data.meshes[i_b]
    check(mats[me_a.idx_material].func_skin == 5 and mats[me_b.idx_material].func_skin == 5, "both draw with skin 5")
    others = [mod.meshes_data.meshes[i] for i in users[a.data.materials[0].name] if i != i_a]
    check(all(mats[m.idx_material].func_skin == base_mod.materials_data.materials[base_mod.meshes_data.meshes[
        users[a.data.materials[0].name][0]].idx_material].func_skin for m in others) and
          all(mats[m.idx_material].func_skin != 5 for m in others), "the shared material's other meshes keep theirs")
    check(mats[me_a.idx_material].pipeline % 7 == 5, "pipeline key follows")
    copy, orig = mats[me_a.idx_material], mats[others[0].idx_material]
    check(all(getattr(copy, f) == getattr(orig, f) for f in ("basemap", "normalmap", "maskmap", "vtype", "func_lighting",
                                                             "func_normalmap", "func_specular")),
          "the copy keeps the textures and functions")
    base_meshes = base_mod.meshes_data.meshes
    ok_uv, ok_tex = True, True
    for i, me in ((i_a, me_a), (i_b, me_b)):
        for k in range(me.num_vertices):
            new, old = vertex(mod, me, k), vertex(base_mod, base_meshes[i], k)
            ok_uv &= new[28:32] == old[24:28] and new[:24] == old[:24]
            col, row = struct.unpack("<ee", new[24:28])
            ok_tex &= col == int(col) and row == int(row) and col < 255
    check(ok_uv, "TEXCOORD1 holds the UV TEXCOORD0 had, the rest of the vertex unchanged")
    check(ok_tex, "TEXCOORD0 holds whole texel numbers, never the last column")
    rest = [i for i in range(len(meshes)) if i not in (i_a, i_b)]
    check(all(vertex(mod, mod.meshes_data.meshes[i], k) == vertex(base_mod, base_meshes[i], k)
              for i in rest for k in range(0, base_meshes[i].num_vertices, 7)), "other meshes' vertices unchanged")

    maps, targets = shape_format.parse_shp(files["shp"].data_bytes)
    by_part = {m.part: (n, m) for n, m in enumerate(maps)}
    check(set(by_part) == {part_a, part_b} if part_a != part_b else len(maps) == 1, f"one map per part: {maps}")
    n_a, map_a = by_part[part_a]
    check(map_a.count == 2, "part a has Up and Side (Muted and Zero left out)")
    up_t, side_t = targets[map_a.first], targets[map_a.first + 1]
    # where a's vertices are: its texels from its TEXCOORD0
    worst_up = worst_side = 0.0
    for k in range(me_a.num_vertices):
        col, row = (int(c) for c in struct.unpack("<ee", vertex(mod, me_a, k)[24:28]))
        du = shape_format.texel_delta(up_t, map_a, col, row)
        ds = shape_format.texel_delta(side_t, map_a, col, row)
        worst_up = max(worst_up, max(abs(x - y) for x, y in zip(du, (0.0, 10.0, 0.0))))
        want = (5.0 * (0.5 if k % 2 == 0 else 0.0), 0.0, 0.0)
        worst_side = max(worst_side, max(abs(x - y) for x, y in zip(ds, want)))
    check(worst_up < 1e-4, f"Up: +10 cm game y on every vertex of a (worst {worst_up:.2e})")
    check(worst_side < 1e-4, f"Side: +5 cm game x x the group weight (worst {worst_side:.2e})")
    last = struct.unpack_from("<4f", up_t.texels, (map_a.width - 1) * 16)
    check(last == (0.0, 0.0, 0.0, 0.0), "the last column holds nothing")

    shws = {p: v for p, v in files["all"].items() if p.endswith(".shw")}
    check(sorted(shws) == sorted(f"{stem}{s}.shw" for s in ("", "_smile", "_blink")),
          f"weight lists: the rest one and one per clip (active and stashed): {sorted(shws)}")

    def lists(suffix):
        frame_max, first, index, curves = shape_format.parse_shw(shws[f"{stem}{suffix}.shw"].data_bytes)
        check(len(curves) == len(targets) and index == list(range(len(targets))) and first == 0,
              f"{suffix or 'rest'}: one curve per target")
        return frame_max, curves

    def values(curves):
        return [[round(k[2], 4) for k in c.keys] for c in curves]

    b_up = by_part[part_b][1].first if part_a != part_b else None
    frame_max, curves = lists("")
    check(frame_max == 1 and values(curves)[map_a.first:map_a.first + 2] == [[0.0], [0.0]],
          "rest: keys a clip drives are 0 (Up, Side)")
    if b_up is not None:
        check(values(curves)[b_up] == [0.0], "rest: b's Up 0 too: a's clip drives the name Up model-wide")
    frame_max, curves = lists("_smile")
    check(frame_max == 60, f"smile: 30 frames at 30 fps = 60 game frames (got {frame_max})")
    cu, cs = curves[map_a.first], curves[map_a.first + 1]
    check([(k[0], round(k[2], 4)) for k in cu.keys] == [(0, 0.0), (60, 1.0)], f"smile: Up linear 0 -> 1 ({cu.keys})")
    check(abs(shape_format.evaluate(cu, 30) - 0.5) < 1e-4, "smile: Up is 0.5 at game frame 30")
    check([k[2] for k in cs.keys] == [0.0], "smile: Side, which it doesn't animate, at its rest value 0")
    if b_up is not None:
        check(values(curves)[b_up] == [0.0, 1.0], "smile: drives b's Up too (same name, another mesh)")
    frame_max, curves = lists("_blink")
    check(frame_max == 12 and [(k[0], round(k[2], 4)) for k in curves[map_a.first + 1].keys] == [(0, 0.0), (12, 1.0)]
          and values(curves)[map_a.first] == [0.0], f"blink (stashed): Side 0 -> 1 over 12 game frames, Up 0")
    if part_a != part_b:
        map_b = by_part[part_b][1]
        tb = targets[map_b.first]
        worst = max(max(abs(x - y) for x, y in zip(shape_format.texel_delta(tb, map_b, *(int(c) for c in struct.unpack(
            "<ee", vertex(mod, me_b, k)[24:28]))), (0.0, 2.0, 0.0))) for k in range(me_b.num_vertices))
        check(map_b.count == 1 and worst < 1e-4, f"b's Up: its own map, its own target, +2 cm (worst {worst:.2e})")
    rest, clip_lists, active = shape_keys.model_weight_lists(arm)
    check(rest is None and sorted(p.lower() for p in clip_lists) == sorted([stem + "_smile", stem + "_blink"]) and
          active.lower() == stem + "_smile", f"model_weight_lists: {rest}, {clip_lists}, {active}")

    # -- a moved mesh: the deltas turn with it (mesh_prep transforms the keys too) -------------------------------------
    saved = a.matrix_world.copy()
    a.matrix_world = Matrix.Rotation(1.5707963267948966, 4, "Z") @ saved
    bpy.context.view_layer.update()
    files2 = export(arm)
    maps2, targets2 = shape_format.parse_shp(files2["shp"].data_bytes)
    map2 = next(m for m in maps2 if m.part == part_a)
    side2 = targets2[map2.first + 1]
    mod2 = parse(files2["mod"].data_bytes)
    me2 = mod2.meshes_data.meshes[i_a]
    deltas = []
    for k in range(me2.num_vertices):
        col, row = (int(c) for c in struct.unpack("<ee", vertex(mod2, me2, k)[24:28]))
        deltas.append(shape_format.texel_delta(side2, map2, col, row))
    off = max(max(abs(d[0]), abs(d[1]), min(abs(d[2]), abs(d[2] + 2.5))) for d in deltas)
    check(off < 1e-3 and any(abs(d[2] + 2.5) < 1e-3 for d in deltas),
          f"turned 90 deg about Z: Side moves along game -z, not x (off {off:.2e})")
    a.matrix_world = saved
    bpy.context.view_layer.update()

    # -- refused materials ----------------------------------------------------------------------------------------------
    p = props(b.data.materials[0])
    old = p.vtype
    p.vtype = "0x1"
    try:
        export(arm)
        check(False, "a vtype 1 material is refused")
    except AlbamCheckFailure as err:
        check("can't morph" in err.message and "vtype 1" in err.details, f"a vtype 1 material is refused: {err.details}")
    p.vtype = old

    # -- ModelExtension -------------------------------------------------------------------------------------------------
    root = model_ext.new_root(bpy.context, "model_ext\\shape.xml", ext_list.new_list().text(), b"")
    issues = model_ext.all_issues(bpy.context, root)
    check(any("no list has a <shape>" in m for _, _, m in issues), "a model with keys and no <shape> is flagged")
    model_ext.fill_from_scene(bpy.context, root)
    d = model_ext.list_doc(root)
    shapes = ext_list.shapes(d)
    check(len(shapes) == 1 and shapes[0][0].get("shp").lower() == stem and
          shapes[0][0].get("shw").lower() == stem + "_smile" and shapes[0][1].get("path").lower() == stem,
          "Fill from Scene adds <shape shp= shw=> under the model, list 0 = the clip on the Keys now")
    check(not any("shape" in m for _, _, m in model_ext.all_issues(bpy.context, root)), "then nothing is flagged")
    check(model_ext.fill_from_scene(bpy.context, root) == 0, "a second fill adds nothing")
    shape = shapes[0][0]
    for k in range(4):
        model_ext.add_element(d, "weights", shape, [("shw", f"x\\w{k}"), ("rate", "0.5")])
    model_ext.store(root, d)
    text = model_ext.list_doc(root).text()
    d2 = ext_list.parse(text)
    check(len(d2.children(ext_list.shapes(d2)[0][0], "weights")) == 4, "<weights> nest under <shape> and read back")
    check(any("5 weight lists" in m for _, _, m in ext_list.issues([("shape.xml", d2)])), "5 lists: warned")
    check("<weights" in text and "</shape>" in text, "written as children of <shape>")
    bad = ext_list.parse('<extensions><model path="a"><shape shp="a.shp" speed="fast"/></model></extensions>')
    found = ext_list.issues([("x.xml", bad)])
    check(any("speed" in m for _, _, m in found) and any("extension" in m for _, _, m in found),
          "a non-number speed and a path with an extension are flagged")
    data = """<!-- Shape test: Nero's parts rise and slide (morph targets, Vibed\ShapeTest). -->
<extensions>
  <model path="model\game\pl000\pl000">
    <shape shp="shape_test\shape_test" shw="shape_test\shape_test" speed="1"/>
  </model>
</extensions>
"""     # the runner session's test list (its package is gone)
    check(ext_list.parse(data).text() == data and not ext_list.issues([("shape_test.xml", ext_list.parse(data))]),
          "the runner's own shape_test.xml reads back unchanged, no issues")
except Exception:
    import traceback
    traceback.print_exc()
    failures.append("exception")

print("FAILURES:", failures)
sys.stdout.flush()
sys.exit(1 if failures else 0)

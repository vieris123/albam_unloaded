import os, sys  # noqa: E401
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tests/: common.py
import common  # noqa: E402  (game data / add-on / output paths)
import sys, traceback, glob, os
sys.path.insert(0, common.ADDONS)
import bpy, bmesh
import albam
albam.register()
from albam.registry import blender_registry
from albam.engines.mtfw import effect_efs, effect_ean
from albam.engines.mtfw.efl import efs, ean

failures = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


class F:
    app_id = "dmc4"

    def __init__(self, path, rel):
        self.path, self.relative_path = path, rel
        self.display_name = os.path.basename(path)

    def get_bytes(self):
        return open(self.path, "rb").read()


class Stub:
    def __getattr__(self, name):
        return lambda *a, **k: self
    def __setattr__(self, name, value):
        object.__setattr__(self, name, value)


try:
    ctx = bpy.context
    # ---------------- EFS
    dx9_efs = common.DATA + r"\arctool\Anima\uPlayerDante\effect\efs\com\ec000_00v2.efs"
    se_efs = common.DATA + r"\arctool\uPlayerNero-SE\effect\efs\com\ec000_00v2.efs"
    many = max((p for p in glob.glob(common.DATA + r"\arctool\**\*.efs", recursive=True)),
               key=lambda p: struct_parts(p) if False else os.path.getsize(p))
    for path in (dx9_efs, se_efs, many):
        before = set(bpy.data.objects)
        blender_registry.import_registry[("dmc4", "efs")](F(path, r"effect\efs\com\x.efs"), ctx)
        ob = (set(bpy.data.objects) - before).pop()
        out = blender_registry.export_registry[("dmc4", "efs")](ob)[0]
        data = out.data_bytes
        check(data == open(path, "rb").read(), f"efs untouched export identical: {os.path.basename(path)} "
                                              f"({len(efs.parse_strip(data).parts)} parts)")
    ob = [o for o in bpy.data.objects if o.name.startswith("EFS_")][-1]
    src = efs.parse_strip(open(many, "rb").read())
    n0 = len(src.parts[0].vertices)
    # move the 2nd point of part 0 by +1 m along Blender X (= +100 cm game X)
    ob.data.vertices[1].co.x += 1.0
    strip = efs.parse_strip(effect_efs.build_efs_bytes(ob))
    check(abs(strip.parts[0].vertices[1].pos[0] - (src.parts[0].vertices[1].pos[0] + 100)) < 1e-3, "moved point exported")
    # extrude the last point of part 0
    bm = bmesh.new(); bm.from_mesh(ob.data); bm.verts.ensure_lookup_table()
    last = bm.verts[n0 - 1]
    res = bmesh.ops.extrude_vert_indiv(bm, verts=[last])
    newv = res["verts"][0]
    newv.co.z += 0.5
    bm.to_mesh(ob.data); bm.free()
    strip = efs.parse_strip(effect_efs.build_efs_bytes(ob))
    p0 = strip.parts[0]
    check(len(p0.vertices) == n0 + 1 and abs(p0.vertices[-1].pos[1] - (src.parts[0].vertices[-1].pos[1] + 50)) < 1e-3,
          f"extruded point appended to part 0 ({len(p0.vertices)} points)")
    check(abs(sum(c * c for c in p0.vertices[-1].norm) - 1) < 1e-4, "extruded point has a unit normal")
    check(len(strip.parts) == len(src.parts), "part count unchanged")
    # duplicate part 0 -> a new part right after it
    bm = bmesh.new(); bm.from_mesh(ob.data); bm.verts.ensure_lookup_table()
    chain = [v for v in bm.verts if v.index < n0 + 1 and v.index < n0] + [bm.verts[-1]]
    geom = bmesh.ops.duplicate(bm, geom=chain + [e for e in bm.edges if all(v in chain for v in e.verts)])
    for v in geom["geom"]:
        if isinstance(v, bmesh.types.BMVert):
            v.co.x += 2.0
    bm.to_mesh(ob.data); bm.free()
    strip = efs.parse_strip(effect_efs.build_efs_bytes(ob))
    check(len(strip.parts) == len(src.parts) + 1 and len(strip.parts[1].vertices) == n0 + 1,
          f"duplicated chain became part 1 ({len(strip.parts)} parts)")
    # a branch is refused
    bm = bmesh.new(); bm.from_mesh(ob.data); bm.verts.ensure_lookup_table()
    v = bm.verts.new((0, 0, 0)); bm.verts.ensure_lookup_table(); bm.edges.new((bm.verts[1], v))
    bm.to_mesh(ob.data); bm.free()
    try:
        effect_efs.build_efs_bytes(ob)
        check(False, "branch refused")
    except Exception as err:
        check("branches" in str(getattr(err, "message", err)), "branch refused")

    print("FAILURES:", failures)
    raise SystemExit(0)  # the EAN part below is superseded by test_ean_uv.py
    # ---------------- EAN
    dx9_ean = common.DATA + r"\000 laser test\nativePC\effect\ean\com\ec032_02.ean"
    se_ean = common.DATA + r"\arc files\em000\effect\ean\com\ec032_02.ean"
    for path in (dx9_ean, se_ean):
        before = set(bpy.data.objects)
        blender_registry.import_registry[("dmc4", "ean")](F(path, r"effect\ean\com\ec032_02.ean"), ctx)
        ob = (set(bpy.data.objects) - before).pop()
        data = blender_registry.export_registry[("dmc4", "ean")](ob)[0].data_bytes
        check(data == open(path, "rb").read(), f"ean untouched export identical: {path.split(os.sep)[-5]}")
    state = ctx.scene.albam.ean_editor
    for path, ob in ((dx9_ean, [o for o in bpy.data.objects if o.name.startswith("EAN_")][0]),
                     (se_ean, [o for o in bpy.data.objects if o.name.startswith("EAN_")][1])):
        ctx.view_layer.objects.active = ob
        effect_ean.load_target(state, ob)
        tag = "SE" if "arc files" in path else "DX9"
        check(len(state.sequences) == 13, f"{tag}: 13 sequences listed")
        state.seq_index = 0
        before = list(state.frames[0].rect)
        state.frames[0].rect = (before[0] + 8, before[1], before[2], before[3])
        anim = ean.parse(effect_ean.build_ean_bytes(ob))
        check(list(anim.sequences[0].patterns[0]) == [before[0] + 8] + before[1:], f"{tag}: frame edit exported")
        if tag == "SE":
            tw, th = ean.texture_size(anim)
            u0 = anim.sequences[0].uvs[0][0]
            check(abs(u0 - (before[0] + 8) / tw) < 1e-6, f"SE: changed frame's UV recomputed ({tw}x{th})")
        # generate grid
        state.con_pat_base_point = (0, 0)
        state.con_pat_col_num = 4
        state.con_pat_total_num = 8
        state.con_pat_size = (32, 64)
        bpy.ops.albam.ean_generate_grid()
        anim = ean.parse(effect_ean.build_ean_bytes(ob))
        s0 = anim.sequences[0]
        check(len(s0.patterns) == 8 and tuple(s0.patterns[5]) == (32, 64, 32, 64) and s0.default_pat_center == (16, 32),
              f"{tag}: generate grid ({len(s0.patterns)} frames, frame 5 {s0.patterns[5]})")
        n_seq = len(anim.sequences)
        bpy.ops.albam.ean_sequence_add()
        bpy.ops.albam.ean_frame_add()
        anim = ean.parse(effect_ean.build_ean_bytes(ob))
        check(len(anim.sequences) == n_seq + 1 and len(anim.sequences[1].patterns) == 9, f"{tag}: add sequence + frame")
        bpy.ops.albam.ean_sequence_remove()
        bpy.ops.albam.ean_frame_remove()
        anim = ean.parse(effect_ean.build_ean_bytes(ob))
        check(len(anim.sequences) == n_seq, f"{tag}: remove sequence")
        p = type("P", (), {})(); p.layout = Stub()
        effect_ean.ALBAM_PT_EanEditor.draw(p, ctx)
        check(True, f"{tag}: panel draws")
    # tooltips on every new property and operator
    missing = []
    for cls in (effect_ean.AlbamEanEditor, effect_ean.AlbamEanFrameItem):
        for prop in cls.bl_rna.properties:
            if prop.identifier in ("rna_type", "name", "target", "sequences", "frames"):
                continue
            if not prop.description:
                missing.append(f"{cls.__name__}.{prop.identifier}")
    for op in ("ean_load", "ean_sequence_add", "ean_sequence_remove", "ean_frame_add", "ean_frame_remove",
               "ean_generate_grid"):
        if not getattr(bpy.ops.albam, op).get_rna_type().description:
            missing.append(op)
    check(not missing, f"every control has a tooltip {missing}")
except Exception:
    traceback.print_exc()
    failures.append("exception")
print("FAILURES:", failures)

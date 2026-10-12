import os, sys  # noqa: E401
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tests/: common.py
import common  # noqa: E402  (game data / add-on / output paths)
import sys, traceback, os
sys.path.insert(0, common.ADDONS)
import bpy, bmesh
import albam
albam.register()
from albam.registry import blender_registry
from albam.engines.mtfw import effect, effect_ean, effect_export
from albam.engines.mtfw.efl import ean

failures = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


class F:
    app_id = "dmc4"

    def __init__(self, path, rel):
        self.path, self.relative_path, self.display_name = path, rel, os.path.basename(path)

    def get_bytes(self):
        return open(self.path, "rb").read()


class Stub:
    def __init__(self):
        self.texts = []
    def __getattr__(self, name):
        def f(*a, **k):
            if "text" in k:
                self.texts.append(k["text"])
            return self
        return f
    def __setattr__(self, name, value):
        object.__setattr__(self, name, value)


def shift_face_uv(ob, face_index, du_px, size):
    uv = ob.data.uv_layers[effect_ean.UV_LAYER]
    for i in ob.data.polygons[face_index].loop_indices:
        uv.data[i].uv[0] += du_px / size[0]


try:
    ctx = bpy.context
    dx9 = common.DATA + r"\000 laser test\nativePC\effect\ean\com\ec032_02.ean"
    se = common.DATA + r"\arc files\em000\effect\ean\com\ec032_02.ean"
    common.skip_unless(dx9)
    if not os.path.exists(se):
        print(f"skip: no Special Edition sample at {se}")
    for path, tag in [(p, t) for p, t in ((dx9, "DX9"), (se, "SE")) if os.path.exists(p)]:
        before = set(bpy.data.objects)
        blender_registry.import_registry[("dmc4", "ean")](F(path, r"effect\ean\com\ec032_02.ean"), ctx)
        ob = (set(bpy.data.objects) - before).pop()
        src = ean.parse(open(path, "rb").read())
        check(ob.type == "MESH" and len(ob.data.polygons) == sum(len(s.patterns) for s in src.sequences),
              f"{tag}: one face per frame ({len(ob.data.polygons)})")
        data = effect_ean.build_ean_bytes(ob)
        check(data == open(path, "rb").read(), f"{tag}: untouched export byte-identical (UV size {effect_ean.uv_size(ob)})")
        size = effect_ean.uv_size(ob)
        # move frame 0 of sequence 0 by +8 px in the UV editor
        shift_face_uv(ob, 0, 8, size)
        anim = ean.parse(effect_ean.build_ean_bytes(ob))
        r0 = src.sequences[0].patterns[0]
        check(tuple(anim.sequences[0].patterns[0]) == (r0[0] + 8, r0[1], r0[2], r0[3]), f"{tag}: UV move exported")
        if tag == "SE":
            tw, th = ean.texture_size(anim)
            check(abs(anim.sequences[0].uvs[0][0] - (r0[0] + 8) / tw) < 1e-6, f"SE: moved frame's stored UV recomputed")
        # panel + sequence select (edit mode)
        ctx.view_layer.objects.active = ob
        ob.select_set(True)
        state = ctx.scene.albam.ean_editor
        bpy.ops.albam.ean_load()
        check(len(state.sequences) == len(src.sequences), f"{tag}: {len(state.sequences)} sequences listed")
        state.seq_index = 2
        bpy.ops.albam.ean_select_sequence()
        bm = bmesh.from_edit_mesh(ob.data)
        seq = bm.faces.layers.int.get(effect_ean.SEQ_ATTR)
        sel = [f for f in bm.faces if f.select]
        check(ob.mode == "EDIT" and sel and all(f[seq] == 2 for f in sel) and len(sel) == len(src.sequences[2].patterns),
              f"{tag}: Select Frames selects sequence 2 in Edit Mode ({len(sel)} faces)")
        # duplicate one selected frame (Shift+D): it lands after its source
        first = min(sel, key=lambda f: f.index)
        for f in bm.faces:
            f.select_set(f == first)
        bpy.ops.mesh.duplicate()
        bpy.ops.object.mode_set(mode="OBJECT")
        anim = ean.parse(effect_ean.build_ean_bytes(ob))
        n2 = len(src.sequences[2].patterns)
        check(len(anim.sequences[2].patterns) == n2 + 1, f"{tag}: duplicated face adds a frame to its sequence")
        # new sequence from selected: the duplicate
        bpy.ops.object.mode_set(mode="EDIT")
        bm = bmesh.from_edit_mesh(ob.data)
        for f in bm.faces:
            f.select_set(f.index == len(bm.faces) - 1)
        bmesh.update_edit_mesh(ob.data)
        bpy.ops.albam.ean_new_sequence()
        bpy.ops.object.mode_set(mode="OBJECT")
        anim = ean.parse(effect_ean.build_ean_bytes(ob))
        check(len(anim.sequences) == len(src.sequences) + 1 and len(anim.sequences[-1].patterns) == 1
              and len(anim.sequences[2].patterns) == n2, f"{tag}: New Sequence from Selected")
        # generate grid on the new sequence
        state.con_pat_base_point = (0, 0)
        state.con_pat_col_num = 4
        state.con_pat_total_num = 8
        state.con_pat_size = (32, 64)
        bpy.ops.albam.ean_generate_grid()
        anim = ean.parse(effect_ean.build_ean_bytes(ob))
        last = anim.sequences[-1]
        check(len(last.patterns) == 8 and tuple(last.patterns[5]) == (32, 64, 32, 64) and last.default_pat_center == (16, 32),
              f"{tag}: Generate Grid ({len(last.patterns)} frames)")
        layout = Stub(); p = type("P", (), {})(); p.layout = layout
        effect_ean.ALBAM_PT_EanFlipbook.draw(p, ctx)
        check(any(t and "UVs over" in t for t in layout.texts), f"{tag}: Image Editor panel draws")
    missing = [f"{c.__name__}.{p.identifier}" for c in (effect_ean.AlbamEanEditor,) for p in c.bl_rna.properties
               if p.identifier not in ("rna_type", "name", "target", "sequences") and not p.description]
    missing += [op for op in ("ean_load", "ean_select_sequence", "ean_new_sequence", "ean_generate_grid")
                if not getattr(bpy.ops.albam, op).get_rna_type().description]
    check(not missing, f"every control has a tooltip {missing}")

    # linked from an effect: the particle's texture backs the UVs
    ROOT = common.DATA + r"\arctool\uPlayerNero-vanilla"
    REL = r"effect\efl\com\ec000_00v2"
    DATA = open(os.path.join(ROOT, REL + ".efl"), "rb").read()

    class FE:
        app_id = "dmc4"
        display_name = "ec000_00v2.efl"
        relative_path = REL + ".efl"

        def get_bytes(self):
            return DATA

    ctx.scene.albam.rfs.add_root_folder("dmc4", ROOT)
    ctx.scene.albam.import_options_efl.sim_frames = 30
    effect.load_efl(FE(), ctx)
    root = next(o for o in bpy.data.objects if o.albam_asset.extension == "efl")
    eans = [o for k, o in effect.linked_objects(root).items() if k.startswith("ean:")]
    textured = [o for o in eans if o.data.materials[0].node_tree.nodes.active.image.get("efl_texture")]
    check(eans and len(textured) == len(eans), f"linked flipbooks show their particle's texture ({len(textured)}/{len(eans)})")
    check(all(o.hide_get() for o in eans), "linked flipbooks start hidden")
    vfiles = effect_export.export_efl(root)
    check(len(vfiles) == 1 and vfiles[0].data_bytes == DATA, "untouched effect export: just the .efl")
    ob = eans[0]
    img = ob.data.materials[0].node_tree.nodes.active.image
    check(tuple(effect_ean.uv_size(ob)) == tuple(img.size), f"UV size is the texture's {tuple(img.size)}")
    bpy.ops.albam.efl_select_linked(name=ob.name)
    check(not ob.hide_get() and ctx.view_layer.objects.active == ob, "Linked files button unhides and selects it")
    shift_face_uv(ob, 0, 4, effect_ean.uv_size(ob))
    vfiles = effect_export.export_efl(root)
    check(len(vfiles) == 2 and any(v.relative_path.lower().endswith(".ean") for v in vfiles),
          "edited flipbook exported with the effect")
    check(effect_export.structure_changed(root), "flipbook edit asks for a rebuild")
except Exception:
    traceback.print_exc()
    failures.append("exception")
print("FAILURES:", failures)

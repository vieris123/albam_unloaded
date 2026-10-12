import os, sys  # noqa: E401
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tests/: common.py
import common  # noqa: E402  (game data / add-on / output paths)
import sys, os, traceback
from types import SimpleNamespace
sys.path.insert(0, common.ADDONS)
import bpy
import albam
albam.register()
from albam.engines.mtfw import effect, effect_export, effect_editor, effect_sim

failures = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


class Stub:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def f(*a, **k):
            self.calls.append((name, a, k))
            return self
        return f


def roots():
    return [o for o in bpy.data.objects if o.albam_asset.extension == "efl"]


def root_of():
    return roots()[0]


def depsgraph(updates=()):
    """The handler reads len(bpy.data.objects) and depsgraph.updates."""
    effect_editor._on_depsgraph(bpy.context.scene, SimpleNamespace(updates=list(updates)))


def record(index):
    return next(o for o in effect_export.all_record_objects(root_of()) if int(o["efl_record"]) == index)


def materials_of(rec):
    mats = set()
    for o in bpy.data.objects:
        if o.type == "MESH" and (o.parent == rec or o.get("efl_generator") == rec):
            mats |= {m for m in o.data.materials if m}
    return mats


try:
    ROOT = common.DATA + r"\arctool\uPlayerNero-vanilla"
    scene = bpy.context.scene
    scene.albam.rfs.add_root_folder("dmc4", ROOT)
    opts = scene.albam.import_options_efl
    opts.sim_frames = 30
    opts.load_textures = True
    rel = r"effect\efl\com\ec024_60v2"
    data = open(os.path.join(ROOT, rel + ".efl"), "rb").read()
    effect.load_efl(SimpleNamespace(app_id="dmc4", display_name="ec024_60v2.efl", relative_path=rel + ".efl",
                                    get_bytes=lambda: data), bpy.context)
    depsgraph()   # the update after the import: take stock
    state = scene.albam.efl_editor
    check(state.live, "Live is on by default")
    n_records = len(effect_export.all_record_objects(root_of()))

    # --- Properties editor panel
    rec = next(o for o in effect_export.all_record_objects(root_of())
               if "efl_ptcl" in o and "BlendOp" in o["efl_ptcl"] and any(c.get("efl_generator") == o for c in bpy.data.objects))
    index = int(rec["efl_record"])
    bpy.context.view_layer.objects.active = rec
    effect_editor.load_record(state, rec)
    check(effect_editor.ALBAM_PT_EflEditorObject.poll(bpy.context), "Object Properties panel polls for a record")
    stub = Stub()
    effect_editor.ALBAM_PT_EflEditorObject.draw(SimpleNamespace(layout=stub), bpy.context)
    names = [c[0] for c in stub.calls]
    check("operator" in names and any("live" in c[1] for c in stub.calls if c[0] == "prop"),
          "the panel draws Apply with the Live toggle")

    # --- live: a sim-only edit replays without a rebuild
    item = state.fields.get("gen/SetNum")
    before = root_of()["efl_data"]
    item.ints[0] = item.ints[0] + 1
    check(root_of().name in effect_editor._pending, "editing a field schedules a live apply")
    effect_editor._live_apply()
    check(root_of() == rec["efl_root"] and root_of()["efl_data"] != before and not state.live_error,
          "a generator edit is applied by the timer without rebuilding")

    # --- live: a blend edit rebuilds and the material follows
    item = state.fields.get("ptcl/BlendOp")
    old_root = root_of()
    item.enum_value = "2" if item.enum_value != "2" else "0"
    effect_editor._live_apply()
    rec = record(index)
    blends = {m.get("efl_blend") for m in materials_of(rec)}
    want = "op REVSUBTRACT" if item.enum_value == "2" or state.fields.get("ptcl/BlendOp").enum_value == "2" else "op ADD"
    check(root_of() != old_root and any(want in b for b in blends), f"a blend edit rebuilds the effect live ({blends})")
    depsgraph()   # the update after the rebuild

    # --- Shift+D: a plain object copy becomes a new record
    rec = record(index)
    copy = rec.copy()
    for c in rec.users_collection:
        c.objects.link(copy)
    bpy.context.view_layer.objects.active = copy   # as Shift+D does
    depsgraph()
    check(any(j[0] == "adopt" and j[1] == copy for j in effect_editor._queue), "a duplicated record Empty is queued for adoption")
    effect_editor._live_apply()
    check(len(effect_export.all_record_objects(root_of())) == n_records + 1 and not state.live_error,
          f"the copy became a new record and the effect rebuilt with it ({state.live_error})")
    check(int(record(index)["efl_record"]) == index and record(n_records) is not None,
          "the original kept its index; the copy is the last record")
    depsgraph()
    new_rec = record(n_records)
    check(any(o.get("efl_generator") == new_rec for o in bpy.data.objects), "the new record got its own particle objects")
    check(bpy.context.view_layer.objects.active == new_rec, "the new record is the active object")

    # --- X: deleting a record Empty removes the record
    victim = new_rec
    bpy.data.objects.remove(victim)
    depsgraph()
    check(any(j[0] == "structure" for j in effect_editor._queue), "a deletion queues a structure check")
    effect_editor._live_apply()
    check(len(effect_export.all_record_objects(root_of())) == n_records and not state.live_error,
          "the effect rebuilt without the deleted record")
    depsgraph()

    # --- image picker and material swap
    images = [im for im in bpy.data.images if im.get("efl_texture")]
    print("   loaded game textures:", len(images))
    rec = record(index)
    bpy.context.view_layer.objects.active = rec
    effect_editor.load_record(state, rec)
    item = state.fields.get("ptcl/BaseMapPath")
    if item is not None and len(images) >= 2:
        current = item.text
        check(item.image is not None and item.image.get("efl_texture") == current,
              "the BaseMapPath field shows the loaded texture")
        other = next(im for im in images if im.get("efl_texture") != current)
        item.image = other
        check(item.text == other["efl_texture"] and rec["efl_ptcl"]["BaseMapPath"] == other["efl_texture"],
              "picking an image writes the path into the record")
        effect_editor._live_apply()
        rec = record(index)
        check(any(m.get("efl_base_map") == other["efl_texture"] for m in materials_of(rec)),
              "after the live rebuild the record's material uses the picked texture")
        depsgraph()
        # swap the image in the material's node: the path follows
        mat = next(m for m in materials_of(rec) if m.get("efl_base_map") == other["efl_texture"])
        node = next(n for n in mat.node_tree.nodes if n.type == "TEX_IMAGE")
        back = next(im for im in images if im.get("efl_texture") == current)
        node.image = back
        depsgraph([SimpleNamespace(id=mat, is_updated_geometry=False)])
        effect_editor._live_apply()
        rec = record(index)
        check(rec["efl_ptcl"]["BaseMapPath"] == current, "swapping the material's image writes the path back")
        depsgraph()
    else:
        print("   (image picker test skipped: no two loaded textures)")
    items = effect_editor._path_items(SimpleNamespace(extension="tex"), bpy.context)
    check(len(items) > 10 and all("\\" in i[0] and not i[0].lower().endswith(".tex") for i in items),
          f"the picker lists Game Files .tex paths without extension ({len(items)})")

    # --- live off: nothing is scheduled
    state.live = False
    item = state.fields.get("gen/SetNum")
    item.ints[0] = item.ints[0] + 1
    check(not effect_editor._pending, "with Live off, edits wait for Apply")
    state.live = True
except Exception:
    traceback.print_exc()
    failures.append("exception")
print("FAILURES:", failures)

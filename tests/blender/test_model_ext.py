"""ModelExtension lists: import / export byte for byte, Save to Game Folder, Fill from Scene, and the attachment preview
(skin: shared bones follow the owner, a chain's joints stay free; rigid: the model sits at joint x offset)."""
import os
import shutil
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import common  # noqa: E402

common.register()
import bpy  # noqa: E402
from mathutils import Euler, Matrix, Vector  # noqa: E402
from albam.engines.mtfw import cns_chain, joints, model_ext  # noqa: E402
from albam.engines.mtfw.movedef import ext_list  # noqa: E402

failures = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


TEXT = """<extensions>\r
  <attach path="model\\game\\x\\dress" to="model\\game\\x\\body"/>  <!-- skin -->\r
  <attach path="model\\game\\x\\prop" to="model\\game\\x\\body" joint="1" pos="10 0 0" rot="0 90 0" scale="2"/>\r
</extensions>\r
"""


class Item:
    app_id, relative_path, display_name = "dmc4", "model_ext\\ellen.xml", "ellen.xml"

    def __init__(self, data):
        self.data = data

    def get_bytes(self):
        return self.data


def armature(name, path, bones):
    """{bone name: (joint, parent, head)}"""
    data = bpy.data.armatures.new(name)
    ob = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(ob)
    bpy.context.view_layer.objects.active = ob
    bpy.ops.object.mode_set(mode="EDIT")
    for n, (_, parent, head) in bones.items():
        eb = data.edit_bones.new(n)
        eb.head, eb.tail = head, Vector(head) + Vector((0, 0.1, 0))
        if parent:
            eb.parent = data.edit_bones[parent]
    bpy.ops.object.mode_set(mode="OBJECT")
    for n, (number, _, _) in bones.items():
        data.bones[n][joints.JOINT_PROP] = str(number)
    ob.albam_asset.app_id, ob.albam_asset.relative_path, ob.albam_asset.extension = "dmc4", path, "mod"
    return ob


context = bpy.context
scene = context.scene
data = TEXT.encode("utf-8")
model_ext.load_ext(Item(data), context)
root = next(o for o in bpy.data.objects if o.name.startswith("EXT_"))
check(model_ext.is_list(root), "the import makes a list object")
check(any(i.bl_object == root for i in scene.albam.exportable.file_list), "it's in the Export list")
check(model_ext.export_ext(root)[0].data_bytes == data, "untouched export is byte-identical")
item = next(e for e in root.albam_ext.elems if e.tag == "attach")
item.attrs[1].value = "model\\game\\x\\other"
check(model_ext.export_ext(root)[0].data_bytes == data.replace(b'to="model\\game\\x\\body"/>  <!--',
                                                                b'to="model\\game\\x\\other"/>  <!--'),
      "an edit changes only its value")
item.attrs[1].value = "model\\game\\x\\body"

rot = Euler((0.4, 0.2, 0.1)).to_matrix().to_4x4()
body = armature("body", "model\\game\\x\\body.mod", {"hips": (0, None, (0, 0, 1)), "spine": (1, "hips", (0, 0, 1.2))})
dress = armature("dress", "model\\game\\x\\dress.mod", {"hips2": (0, None, (0, 0, 1)), "spine2": (1, "hips2", (0, 0, 1.2)),
                                                       "skirt": (200, "hips2", (0, 0.1, 0.9))})
prop = bpy.data.objects.new("prop", None)
scene.collection.objects.link(prop)
prop.albam_asset.app_id, prop.albam_asset.relative_path, prop.albam_asset.extension = "dmc4", "model\\game\\x\\prop.mod", "mod"
chain = bpy.data.objects.new("PHS_c", None)
scene.collection.objects.link(chain)
chain.parent = dress
chain.albam_asset.app_id, chain.albam_asset.relative_path, chain.albam_asset.extension = "dmc4", "chains\\c.clt", "clt"
chain["phs_joints"] = [1, -1]
col = bpy.data.objects.new("COL_c", None)
scene.collection.objects.link(col)
col.albam_asset.app_id, col.albam_asset.relative_path, col.albam_asset.extension = "dmc4", "chains\\k.col", "col"
col[cns_chain.ARMATURE_PROP] = body
chain.albam_phs.collision_shapes = col

check(model_ext.fill_from_scene(context, root) == 1, "fill adds the chain (both attachments are listed)")
check(model_ext.fill_from_scene(context, root) == 0, "a second fill adds nothing")
d = model_ext.list_doc(root)
model = d.child(d.root, "model")
check(model.get("path") == "model\\game\\x\\dress" and model.get("collision_model") == "model\\game\\x\\body", "model entry")
check(d.child(model, "chain").get("clt") == "chains\\c" and d.child(model, "chain").get("col") == "chains\\k", "chain entry")

root.albam_ext.preview = True
names = {b.name: [c.name for c in b.constraints] for b in dress.pose.bones}
check(names["hips2"] == [model_ext.FOLLOW], "a shared joint follows")
check(names["spine2"] == [], "a chain's joint stays free")
check(names["skirt"] == [], "a joint the owner lacks stays free")
body.pose.bones["hips"].rotation_mode = "QUATERNION"
body.pose.bones["hips"].location = (0.1, 0.2, 0.3)
context.view_layer.update()
got = dress.matrix_world @ dress.pose.bones["hips2"].matrix
want = body.matrix_world @ body.pose.bones["hips"].matrix
check((got.translation - want.translation).length < 1e-5, "the shared bone sits on the owner's")

joint = body.matrix_world @ body.pose.bones["spine"].matrix
offset = Matrix.Translation((0.1, 0, 0)) @ Euler((0, 1.5707963, 0), "XYZ").to_matrix().to_4x4() @ Matrix.Diagonal((2, 2, 2, 1))
want = joint @ offset @ model_ext.GAME_TO_BLENDER.inverted()
check(all(abs(a - b) < 1e-4 for r, s in zip(prop.matrix_world, want) for a, b in zip(r, s)), "rigid: joint x offset")
check(ext_list.issues([("ellen.xml", model_ext.list_doc(root))]) == [], "no issues")

root.albam_ext.preview = False
check(not any(b.constraints for b in dress.pose.bones) and not prop.constraints, "turning it off removes the constraints")


class Stub:
    def __getattr__(self, name):
        return lambda *args, **kwargs: Stub()


context.view_layer.objects.active = root
model_ext.ALBAM_PT_ModelExtList.draw(SimpleNamespace(layout=Stub()), context)
check(True, "the panel draws")

items = scene.albam.exportable.file_list
scene.albam.exportable.file_list_selected_index = next(i for i, it in enumerate(items) if it.bl_object == root)
bpy.ops.albam.export()
vfs = scene.albam.exported
vfs.file_list_selected_index = next(i for i, vf in enumerate(vfs.file_list) if vf.is_root)
OUT = common.out_dir("model_ext_out")
shutil.rmtree(OUT, ignore_errors=True)
os.makedirs(OUT)
bpy.ops.albam.save_to_game_folder(directory=OUT)
saved = os.path.join(OUT, "model_ext", "ellen.xml")
check(os.path.exists(saved) and open(saved, "rb").read() == model_ext.export_ext(root)[0].data_bytes,
      "Save to Game Folder writes the list at its game path")

# a part colliding with another part: Fill attaches the one carrying the shapes first, whatever the scene's order
part = armature("a_part", "model\\game\\x\\a_part.mod", {"p": (0, None, (0, 0, 1))})
skirt = armature("z_skirt", "model\\game\\x\\z_skirt.mod", {"s": (0, None, (0, 0, 1))})
for rig, bone in ((part, "p"), (skirt, "s")):
    con = rig.pose.bones[bone].constraints.new("COPY_TRANSFORMS")
    con.name, con.target, con.subtarget = model_ext.FOLLOW, body, "hips"
chain2 = bpy.data.objects.new("PHS_p", None)
scene.collection.objects.link(chain2)
chain2.parent = part
chain2.albam_asset.app_id, chain2.albam_asset.relative_path, chain2.albam_asset.extension = "dmc4", "chains\\p.clt", "clt"
col2 = bpy.data.objects.new("COL_p", None)
scene.collection.objects.link(col2)
col2.albam_asset.app_id, col2.albam_asset.relative_path, col2.albam_asset.extension = "dmc4", "chains\\p.col", "col"
col2[cns_chain.ARMATURE_PROP] = skirt
chain2.albam_phs.collision_shapes = col2
second = model_ext.new_root(context, "model_ext\\second.xml", ext_list.new_list().text(), b"")
model_ext.fill_from_scene(context, second)
d2 = model_ext.list_doc(second)
order = [ext_list.normalize(a.get("path")) for a in d2.children(d2.root, "attach")]
check(order.index("model\\game\\x\\z_skirt") < order.index("model\\game\\x\\a_part"), "the collision model attaches first")
check(not [i for i in ext_list.issues([("second.xml", d2)]) if "attached after" in i[2]], "and the check agrees")

for bad in ("<move/>", "not xml"):
    try:
        model_ext.load_ext(Item(bad.encode()), context)
        check(False, f"{bad} refused")
    except Exception as err:
        check("ModelExtension" in str(err) or "extensions" in str(err), f"{bad} refused: {type(err).__name__}")

print("FAILURES:", failures)
sys.exit(1 if failures else 0)

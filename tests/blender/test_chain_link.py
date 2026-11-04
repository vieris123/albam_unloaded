"""ModelExtension <link> in the chain preview (dmc4_hook sdk/ChainLink.cpp, Vibed/ModelExt/schema.md "<link>"): two
tendrils splayed apart, a link pulls their tips to `max`, a tendril root keeps its place, what the runner refuses is
reported and not run."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import common  # noqa: E402

common.register()
import bpy  # noqa: E402
from mathutils import Vector  # noqa: E402
from albam.engines.mtfw import cns_chain, joints, model_ext  # noqa: E402

failures = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


common.skip_unless(common.NERO)
context = bpy.context
scene = context.scene
scene.albam.rfs.add_root_folder("dmc4", common.NERO)      # a chain file to build the new one on

# a skirt: hips (joint 0) and two tendrils of three bones, splayed apart, hanging down (+Y of each bone downwards)
BONES = {"hips": (0, None, (0, 0, 1.0), (0, 0, 1.1))}
for side, sign, base in (("L", -1, 10), ("R", 1, 20)):
    for k in range(3):
        head = (sign * (0.05 + 0.02 * k), 0, 0.9 - 0.1 * k)
        tail = (sign * (0.07 + 0.02 * k), 0, 0.8 - 0.1 * k)
        BONES[f"{side}{k}"] = (base + k, "hips" if k == 0 else f"{side}{k - 1}", head, tail)
data = bpy.data.armatures.new("skirt")
arm = bpy.data.objects.new("skirt", data)
scene.collection.objects.link(arm)
context.view_layer.objects.active = arm
bpy.ops.object.mode_set(mode="EDIT")
for name, (_, parent, head, tail) in BONES.items():
    eb = data.edit_bones.new(name)
    eb.head, eb.tail = head, tail
    if parent:
        eb.parent = data.edit_bones[parent]
bpy.ops.object.mode_set(mode="OBJECT")
for name, (number, _, _, _) in BONES.items():
    data.bones[name][joints.JOINT_PROP] = str(number)
arm.albam_asset.app_id, arm.albam_asset.relative_path, arm.albam_asset.extension = "dmc4", "model\\game\\x\\skirt.mod", "mod"

settings = dict(cns_chain.DEFAULTS, mDir=1, mUp=2, mGravity=[0.0, 0.0, 0.0], mBlend=1.0)
chain = cns_chain.new_chain(context, arm, [data.bones[n] for n in BONES if n != "hips"], "chains\\lk.clt", settings)
check([int(j) for j in chain[cns_chain.JOINTS_PROP]] == [10, 11, 12, -1, 20, 21, 22], "one chain, two tendrils")


def make_list(links):
    for ob in [o for o in bpy.data.objects if model_ext.is_list(o)]:
        bpy.data.objects.remove(ob)
    text = ('<extensions>\n  <model path="model\\game\\x\\skirt">\n    <chain clt="chains\\lk"/>\n' +
            "".join(f"    {link}\n" for link in links) + "  </model>\n</extensions>\n")
    return model_ext.new_root(context, "model_ext\\lk.xml", text, text.encode())


def head(name):
    return arm.matrix_world @ arm.pose.bones[name].head


def play(frames=30):
    chain.albam_phs.preview = False
    scene.frame_set(1)
    chain.albam_phs.preview = True
    for f in range(1, frames + 1):
        scene.frame_set(f)


rest = (data.bones["L2"].head_local - data.bones["R2"].head_local).length
make_list([])
play()
check(abs((head("L2") - head("R2")).length - rest) < 1e-3, f"without a link the tips stay {rest * 100:.0f} cm apart")

root = make_list(['<link a="12" b="22" max="10"/>'])
check(model_ext.preview_links(arm) == [("L2", "R2", 0.1, 1.0)], "the preview finds the link")
play()
gap = (head("L2") - head("R2")).length
check(abs(gap - 0.1) < 2e-3, f"a link pulls the tips to max ({gap * 100:.2f} cm)")
check(all(abs((head(f"{s}2") - head(f"{s}1")).length -
               (data.bones[f"{s}2"].head_local - data.bones[f"{s}1"].head_local).length) < 1e-3 for s in "LR"),
      "the moved joints keep their distance to their tendril parents")
aim = (arm.matrix_world.to_3x3() @ arm.pose.bones["L1"].matrix.to_3x3()).col[1].normalized()
check(aim.dot((head("L2") - head("L1")).normalized()) > 0.9999, "a joint is re-aimed at its moved child")
check(not [i for i in model_ext.all_issues(context, root) if i[0] == "error" or "link" in i[2]], "the list checks clean")

make_list(['<link a="10" b="21" max="2"/>'])
play()
check((head("L0") - (arm.matrix_world @ data.bones["L0"].head_local)).length < 1e-6, "a tendril root keeps its place")
check((head("L0") - head("R1")).length < 0.021, f"its partner takes the whole pull ({(head('L0') - head('R1')).length * 100:.2f} cm)")

root = make_list(['<link a="10" b="20" max="2"/>', '<link a="12" b="99" max="2"/>'])
found = [i[2] for i in model_ext.all_issues(context, root)]
check(any("both are tendril roots" in m for m in found), "two roots are reported")
check(any("holds joint 99" in m for m in found), "a joint no chain holds is reported")
check(model_ext.preview_links(arm) == [], "and neither runs in the preview")
chain.albam_phs.preview = False
print("FAILURES:", failures)
sys.exit(1 if failures else 0)

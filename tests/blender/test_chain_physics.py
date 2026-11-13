"""ModelExtension <physics>: dmc4_hook's chain solver (Vibed/ModelExt/chain_solver.md) in the list format and the chain
preview. The list entry parses, checks and round-trips; the Chain panel's settings write it; the preview runs the
solver for the chain it names: the rest pose holds without forces, lengths hold under gravity, the same time at 30 and
60 fps gives the same pose, pin holds the animation, shapes and the stage floor keep the points out, links still run."""
import math
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import common  # noqa: E402

common.register()
import bpy  # noqa: E402
from mathutils import Matrix, Vector  # noqa: E402
from albam.engines.mtfw import cns_chain, cns_chain_hook, cns_chain_preview, joints, model_ext  # noqa: E402
from albam.engines.mtfw.movedef import ext_list  # noqa: E402

failures = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


# ---- the format -------------------------------------------------------------------------------------------------------
TEXT = ('<extensions>\n  <model path="model\\game\\x\\skirt">\n'
        '    <physics clt="chains\\lk" substeps="20" axis="+Z" radius="3" ground="true"/>\n'
        '    <physics clt="chains\\lk" stiffness="0.5" damping="1.5"/>\n'
        '    <physics clt="chains\\bad" axis="w"/>\n'
        '  </model>\n</extensions>\n')
d = ext_list.parse(TEXT)
check(d.text() == TEXT, "a list with <physics> round-trips byte for byte")
first, _, bad = [e for e, _ in ext_list.physics(d)]
values = ext_list.physics_values(first)
check(values["substeps"] == 16 and values["axis"] == 2 and values["radius"] == [3.0] and values["ground"],
      f"values as the runner reads them, clamped ({values})")
check(values["inertia"] is None and values["inertia_turn"] is None and values["friction"] == 0.2
      and values["iterations"] == 1 and values["gravity"] == [1.0], "absent ones: defaults (version 2: 8 x 1)")
check(values["damping"] is None and ext_list.physics_values(d.elems[[e.tag for e in d.elems].index("physics") + 1])
      ["damping"] == [1.0], "damping: None (auto) when absent, clamped to 0-1")
any_s = {"pos_local": False, "pos_local_y": False, "rot_local": False, "radius": 0.01, "dir": 1, "up": 1}
check(abs(cns_chain_hook.Hook(values, dict(any_s, damping=1.0)).damping[0] - 0.1) < 1e-9
      and abs(cns_chain_hook.Hook(values, dict(any_s, damping=0.6)).damping[0] - 0.4) < 1e-9
      and cns_chain_hook.Hook(dict(values, damping=[0.3]), dict(any_s, damping=1.0)).damping == [0.3],
      "auto damping = 1 - the chain file's, at least 0.1; the attribute wins")
hook = cns_chain_hook.Hook(dict(values, inertia=0.5, inertia_turn=1.0), dict(any_s, damping=1.0))
check(hook.inertia_move == 0.5 and hook.inertia_turn == 1.0, "inertia_move / inertia_turn default to inertia")

# lists along the tendril (V2.2), parsed as the runner's parse_curve
LISTS = ('<extensions>\n  <model path="m">\n'
         '    <physics clt="a" radius="6 2" stiffness="0.15,0.02, 2" gravity="200" limit=""/>\n'
         '    <physics clt="b" pin="0.1 x"/>\n'
         '    <physics clt="c" damping="1 2 3 4 5 6 7 8 9"/>\n'
         '  </model>\n</extensions>\n')
lists = ext_list.parse(LISTS)
la, lb, lc = [ext_list.physics_values(e) for e, _ in ext_list.physics(lists)]
check(la["radius"] == [6.0, 2.0] and la["stiffness"] == [0.15, 0.02, 1.0] and la["gravity"] == [100.0]
      and la["limit"] == [0.0], f"lists: spaces or commas, each clamped, an empty one the default ({la})")
check(lb is None and lc is None, "a value that isn't a number, or a 9th, drops the entry as the runner does")
list_issues = [(level, m) for level, _, m in ext_list.issues([("lists.xml", lists)])]
check(any(level == "error" and "pin=" in m and "drops" in m for level, m in list_issues)
      and any(level == "error" and "damping=" in m for level, m in list_issues)
      and any(level == "warning" and "gravity=" in m and "clamps" in m for level, m in list_issues),
      f"list problems reported ({list_issues})")
check(cns_chain_hook.along([6.0, 2.0], 0.0) == 6.0 and cns_chain_hook.along([6.0, 2.0], 0.5) == 4.0
      and cns_chain_hook.along([0.0, 1.0, 0.0], 0.75) == 0.5 and cns_chain_hook.along([3.0], 0.9) == 3.0,
      "along: evenly spread, read linearly")
check(cns_chain_hook.compliance(1.0) == 0.0 and cns_chain_hook.compliance(0.0) is None
      and abs(1.0 / (1.0 + 16.0 * cns_chain_hook.compliance(0.3)) - cns_chain_hook._per_step(0.3, 0.25)) < 1e-12,
      "compliance: hard at 1, off at 0, version 1's share at 4 substeps")
check(ext_list.physics_values(bad) is None, "a bad axis drops the entry, as the runner does")
found = ext_list.issues([("lk.xml", d)])
messages = [m for _, _, m in found]
check(any("substeps" in m and "1-16" in m for m in messages), "substeps out of range is reported")
check(any(level == "error" and "axis" in m for level, _, m in found), "a bad axis is an error")
check(any("listed already" in m for m in messages), "a second entry for the same model and file is reported")

CLOTHS = ('<extensions>\n  <model path="m">\n'
          '    <cloth roots="1, 8 14 20 26 32" closed="true" shear="2"/>\n'
          '    <cloth roots="40 8"/>\n'
          '    <cloth roots="5"/>\n'
          '    <cloth roots="5 5"/>\n'
          '    <cloth roots="5 300"/>\n'
          '  </model>\n</extensions>\n')
d = ext_list.parse(CLOTHS)
sheets = [e for e, _ in ext_list.cloths(d)]
values = ext_list.cloth_values(sheets[0])
check(values == {"roots": [1, 8, 14, 20, 26, 32], "closed": True, "stretch": 1.0, "shear": 1.0, "bend": 0.0},
      f"a <cloth> as the runner reads it ({values})")
check([ext_list.cloth_values(e) is None for e in sheets[2:]] == [True] * 3, "one root, a root twice, a root over 255: dropped")
messages = [m for _, _, m in ext_list.issues([("c.xml", d)])]
check(any("root 8 is in an earlier <cloth>" in m for m in messages), "a root in an earlier sheet: the later one is dropped")
check(sum("the game drops it" in m for m in messages) == 3, "the dropped entries are errors")

# ---- the preview ------------------------------------------------------------------------------------------------------
common.skip_unless(common.NERO)
context = bpy.context
scene = context.scene
scene.albam.rfs.add_root_folder("dmc4", common.NERO)      # a chain file to build the new one on

# the skirt of test_chain_link: hips (joint 0) and two tendrils of three bones, splayed apart, hanging down
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
check(model_ext.chain_model_path(chain) == "model\\game\\x\\skirt", "the chain's model path")
context.view_layer.objects.active = chain
check(bpy.ops.albam.phs_hook_use() == {"FINISHED"}, "Use dmc4_hook's Solver adds an entry")
lists = [o for o in bpy.data.objects if model_ext.is_list(o)]
check(len(lists) == 1 and lists[0].albam_asset.relative_path == "model_ext\\skirt.xml", "in a new list for the model")
text = model_ext.list_doc(lists[0]).text()
check('<model path="model\\game\\x\\skirt">' in text and '<physics clt="chains\\lk"/>' in text, f"the entry:\n{text}")

s = chain.albam_phs
check(s.hook_substeps == 8 and s.hook_iterations == 1 and abs(s.hook_inertia - 1.0) < 1e-6
      and abs(s.hook_inertia_turn - 1.0) < 1e-6 and s.hook_axis == "+y",
      "the panel shows the runner's defaults, inertia and axis from the chain file")
s.hook_stiffness = 0.25
s.hook_axis = "+z"
s.hook_substeps = 6
text = model_ext.list_doc(lists[0]).text()
check('stiffness="0.25"' in text and 'axis="+z"' in text and 'substeps="6"' in text, "the settings write the entry")
s.hook_substeps = 8
check('substeps' not in model_ext.list_doc(lists[0]).text(), "a setting set to its default is taken out")
bpy.ops.albam.phs_hook_default(attr="axis")
bpy.ops.albam.phs_hook_default(attr="stiffness")
check('<physics clt="chains\\lk"/>' in model_ext.list_doc(lists[0]).text(), "Use Default takes settings out")
s.hook_inertia_move = 0.0
check('inertia_move="0"' in model_ext.list_doc(lists[0]).text() and abs(s.hook_inertia_turn - 1.0) < 1e-6,
      "Inertia Move writes its own attribute, Inertia Turn still follows Inertia")
bpy.ops.albam.phs_hook_default(attr="inertia_move")
bpy.ops.albam.phs_hook_along(attr="radius")
radius_cm = round(cns_chain_preview._settings(chain)["radius"] / cns_chain_hook.SCALE, 4)
check(f'radius="{radius_cm:g} {radius_cm:g}"' in model_ext.list_doc(lists[0]).text(),
      f"Along the Tendril makes the setting a list (root and tail): {model_ext.list_doc(lists[0]).text()}")
s.hook_radius_along = "6, 2"
check('radius="6 2"' in model_ext.list_doc(lists[0]).text() and abs(s.hook_radius - 6.0) < 1e-6,
      "the list is edited as text; the single field shows the root's value")
s.hook_radius_along = "6 x"
check('radius="6 2"' in model_ext.list_doc(lists[0]).text(), "text the runner would drop isn't written")
bpy.ops.albam.phs_hook_along(attr="radius")
check('radius="6"' in model_ext.list_doc(lists[0]).text(), "Along the Tendril again: back to one value, the root's")
bpy.ops.albam.phs_hook_default(attr="radius")
check(not [i for i in model_ext.all_issues(context, lists[0]) if i[0] == "error"], "the list checks clean")


class Stub:
    """a layout that takes any call (panels can't be drawn headless)"""

    def __getattr__(self, name):
        return lambda *args, **kwargs: Stub()

    def __setattr__(self, name, value):
        pass


try:
    cns_chain_preview._draw_hook(Stub(), context, chain)
    drawn = True
except Exception as err:        # noqa: BLE001
    print(err)
    drawn = False
check(drawn, "the Chain panel's dmc4_hook box draws")


# a skin attachment's model matrix is its owner's (dmc4_hook ModelAttach: mpParent = the owner): the chain's
# reference frame follows the armature its bones follow (ALBAM_FollowBody), as its own object stands still
owner_data = bpy.data.armatures.new("owner")
owner = bpy.data.objects.new("owner", owner_data)
scene.collection.objects.link(owner)
context.view_layer.objects.active = owner
bpy.ops.object.mode_set(mode="EDIT")
owner_data.edit_bones.new("hips").tail = (0.0, 0.0, 0.1)
bpy.ops.object.mode_set(mode="OBJECT")
owner.location = (1.0, 2.0, 0.0)
owner.rotation_euler = (0.0, 0.0, 0.5)
context.view_layer.update()
follow = arm.pose.bones["hips"].constraints.new("COPY_TRANSFORMS")
follow.name, follow.target, follow.subtarget = model_ext.FOLLOW, owner, "hips"
frame = cns_chain_preview._parent_frame(arm, 0)
check((frame.translation - owner.location).length < 1e-6
      and abs(frame.to_euler().z - 0.5) < 1e-6, "an attachment's reference frame is its owner's")
arm.pose.bones["hips"].constraints.remove(follow)
check(cns_chain_preview._parent_frame(arm, 0).translation.length < 1e-6, "without one, its own")
bpy.data.objects.remove(owner)
context.view_layer.objects.active = chain


def runner():
    return cns_chain_preview._runners.get(arm.name)


def head(name):
    return arm.matrix_world @ arm.pose.bones[name].head


def play(frames, fps=60):
    scene.render.fps, scene.render.fps_base = fps, 1.0
    chain.albam_phs.preview = False
    scene.frame_set(1)
    chain.albam_phs.preview = True
    for f in range(1, frames + 1):
        scene.frame_set(f)


def set_chain(**props):
    for key, value in props.items():
        chain[key] = value


rest = {n: arm.matrix_world @ data.bones[n].head_local for n in BONES}
play(30)
check(runner() is not None and all(c.hook is not None for _, c in runner().chains), "the preview runs the hook solver")
worst = max((head(n) - rest[n]).length for n in BONES)
check(worst < 1e-5, f"without forces the rest pose holds ({worst:.2e} m)")

set_chain(mGravity=[0.0, -1.0, 0.0])
play(60)
lengths = max(abs((head(f"{t}{k}") - head(f"{t}{k - 1}")).length - (rest[f"{t}{k}"] - rest[f"{t}{k - 1}"]).length)
              for t in "LR" for k in (1, 2))
check(lengths < 1e-4, f"under gravity the segments keep their lengths ({lengths:.2e} m)")
swing = abs(head("L2").x) < abs(rest["L2"].x) - 0.005
check(swing, f"gravity swings the splayed tendrils toward hanging straight (x {rest['L2'].x:.3f} -> {head('L2').x:.3f})")
at60 = {n: head(n) for n in BONES}
play(31, fps=30)        # the first 2 frames copy the animation: 58 solved frames at 60 fps, 29 of 2 at 30 fps
apart = max((head(n) - at60[n]).length for n in BONES)
check(apart < 1e-4, f"one second at 30 fps ends where one at 60 fps does ({apart:.2e} m)")
scene.render.fps = 60

model_ext.set_physics_attr(context, chain, "pin", "1")
play(30)
worst = max((head(n) - rest[n]).length for n in BONES)
check(worst < 1e-4, f"pin 1 holds the animated places under gravity ({worst:.2e} m)")
model_ext.set_physics_attr(context, chain, "pin", None)

# links run after the hook solver as after the game's; a chain the <physics> entry puts on the solver counts as listed
# without a <chain> (the game's own chains: Nero's coat)
d = model_ext.list_doc(lists[0])
model = d.children(d.root, "model")[0]
model_ext.add_element(d, "link", model, [("a", "12"), ("b", "22"), ("max", "10")])
model_ext.store(lists[0], d)
set_chain(mGravity=[0.0, 0.0, 0.0])
play(30)
gap = (head("L2") - head("R2")).length
check(abs(gap - 0.1) < 2e-3, f"a <link> on <physics> chains (no <chain>) pulls the tips to max ({gap * 100:.2f} cm)")
check(not [i for i in model_ext.all_issues(context, lists[0]) if "link" in i[2]], "and the list check accepts it")

# <cloth>: the two tendrils as one sheet (roots 10 and 20, one chain file)
d = model_ext.list_doc(lists[0])
model = d.children(d.root, "model")[0]
for e in d.children(model, "link"):
    d.remove(e)
model_ext.add_element(d, "cloth", model, [("roots", "10 20")])
model_ext.store(lists[0], d)
check(model_ext.cloth_sheets(arm) == [{"roots": [10, 20], "closed": False, "stretch": 1.0, "shear": 0.5, "bend": 0.0,
                                      "members": [(chain.name, 0), (chain.name, 4)]}], "the sheet's members are found")
check(not [i for i in model_ext.all_issues(context, lists[0]) if "cloth" in i[2]], "the list checks clean")
try:
    cns_chain_preview._draw_hook(Stub(), context, chain)      # the sheet line
    drawn = True
except Exception as err:        # noqa: BLE001
    print(err)
    drawn = False
check(drawn, "the Chain panel draws a chain in a sheet")
play(30)
worst = max((head(n) - rest[n]).length for n in BONES)
check(runner().sheets and worst < 1e-5, f"a sheet without forces holds the rest pose ({worst:.2e} m)")
set_chain(mGravity=[0.0, -1.0, 0.0])
play(60)
gaps = [abs((head(f"L{k}") - head(f"R{k}")).length - (rest[f"L{k}"] - rest[f"R{k}"]).length) for k in (1, 2)]
check(max(gaps) < 5e-3, f"under gravity the sheet keeps the tendrils' spacing (off by {max(gaps) * 100:.2f} cm)")
d = model_ext.list_doc(lists[0])
model = d.children(d.root, "model")[0]
d.children(model, "cloth")[0].set("roots", "10 99")
model_ext.store(lists[0], d)
play(60)
gap = (head("L2") - head("R2")).length
check(not runner().sheets and abs(gap - (rest["L2"] - rest["R2"]).length) > 0.02,
      f"a sheet with a root no tendril starts doesn't run (tips {gap * 100:.1f} cm apart, rest 18)")
found = [m for _, _, m in model_ext.all_issues(context, lists[0])]
check(any("root 99: no chain of this model starts a tendril there" in m for m in found), "and the check says why")

# a root on another model: a <cloth> can't cross models
data2 = bpy.data.armatures.new("cape")
arm2 = bpy.data.objects.new("cape", data2)
scene.collection.objects.link(arm2)
context.view_layer.objects.active = arm2
bpy.ops.object.mode_set(mode="EDIT")
for k in range(2):
    eb = data2.edit_bones.new(f"C{k}")
    eb.head, eb.tail = (0.3, 0, 0.9 - 0.1 * k), (0.3, 0, 0.8 - 0.1 * k)
    if k:
        eb.parent = data2.edit_bones["C0"]
bpy.ops.object.mode_set(mode="OBJECT")
for k in range(2):
    data2.bones[f"C{k}"][joints.JOINT_PROP] = str(30 + k)
arm2.albam_asset.app_id, arm2.albam_asset.relative_path, arm2.albam_asset.extension = "dmc4", "model\\game\\x\\cape.mod", "mod"
cape = cns_chain.new_chain(context, arm2, list(data2.bones), "chains\\cape.clt", settings)
model_ext.add_physics(context, cape)
d = model_ext.list_doc(lists[0])
model = next(m for m in d.children(d.root, "model") if m.get("path") == "model\\game\\x\\skirt")
d.children(model, "cloth")[0].set("roots", "10 30")
model_ext.store(lists[0], d)
found = [m for _, _, m in model_ext.all_issues(context, lists[0])]
check(any("root 30" in m and "can't cross models" in m for m in found), "a root on another model: can't cross models")
model_ext.remove_physics(context, chain)
d = model_ext.list_doc(lists[0])
model = next(m for m in d.children(d.root, "model") if m.get("path") == "model\\game\\x\\skirt")
d.children(model, "cloth")[0].set("roots", "10 20")
model_ext.store(lists[0], d)
found = [m for _, _, m in model_ext.all_issues(context, lists[0])]
check(any("root 10" in m and "no <physics> entry" in m for m in found), "a root on a chain without <physics>: said so")
model_ext.add_physics(context, chain)
chain.albam_phs.preview = False


# ---- shapes and the floor, on the solver directly -----------------------------------------------------------------
def fake_chain(values, **overrides):
    """three joints hanging down 10 cm apart from the origin, aimed along -Z, and its tail"""
    s = dict(cns_chain_preview._settings(chain), gravity=Vector((0.0, 0.0, -0.01)), tail=0.1, dir=5, up=1,
             blend=1.0, stretch=False, pos_local=False, pos_local_y=False, rot_local=False, floor_on=False)
    s.update(overrides)
    names = ["a", "b", "c"]
    fake = SimpleNamespace(joints=names, mats=[Matrix.Identity(4) for _ in range(4)], vel=[Vector() for _ in range(4)],
                           s=s, wind=Vector(), parent=Matrix.Identity(4), in_reset=False)
    fake.hook = cns_chain_hook.Hook(dict(ext_list.physics_values(ext_list.parse(
        '<extensions><model path="m"><physics clt="c"/></model></extensions>').elems[-1]), **values), s)
    bones = {"a": SimpleNamespace(parent=None)}
    bones["b"] = SimpleNamespace(parent=SimpleNamespace(name="a"))
    bones["c"] = SimpleNamespace(parent=SimpleNamespace(name="b"))
    fake_arm = SimpleNamespace(data=SimpleNamespace(bones=bones))
    return fake, fake_arm


def run(fake, fake_arm, shapes=(), ground=None, frames=60, local=(0.0, 0.0, -0.1)):
    for _ in range(frames):
        cns_chain_hook.solve_tendril(fake, 0, Matrix.Identity(4), fake_arm, lambda n: Matrix.Translation(local),
                                     1.0, list(shapes), ground)
    return [fake.mats[k].translation.copy() for k in range(4)]


def segment_distance(p0, p1, c):
    ab = p1 - p0
    t = max(0.0, min(1.0, (c - p0).dot(ab) / ab.length_squared))
    return (p0 + ab * t - c).length


fake, fake_arm = fake_chain({})
points = run(fake, fake_arm, frames=5)
check(max((points[k] - Vector((0, 0, -0.1 * k))).length for k in range(4)) < 1e-6, "hanging straight stays put")

centre = Vector((0.02, 0.0, -0.2))
fake, fake_arm = fake_chain({"radius": 1.0, "friction": 0.2})
points = run(fake, fake_arm, shapes=[(centre, centre, 0.05)])
inside = min(segment_distance(points[k], points[k + 1], centre) for k in range(3))
check(inside > 0.05 + 0.01 - 0.003, f"the segments stay out of a sphere (closest {inside * 100:.2f} cm, wants 6)")
check(abs((points[3] - points[2]).length - 0.1) < 1e-5, "and keep their lengths")

centre = Vector((0.02, 0.0, 0.0))       # the root sits inside: the root push moves it out (chain_solver.md step 5)
fake, fake_arm = fake_chain({"radius": 1.0})
points = run(fake, fake_arm, shapes=[(centre, centre, 0.05)])
check((points[0] - centre).length > 0.06 - 1e-5, f"a root inside a shape is pushed out ({(points[0] - centre).length * 100:.2f} cm "
                                                 "from the centre, wants 6)")
inside = min(segment_distance(points[k], points[k + 1], centre) for k in range(3))
check(inside > 0.06 - 0.003, f"so its first segment gets out too (closest {inside * 100:.2f} cm)")

plane = bpy.data.meshes.new("stage")
plane.from_pydata([(-1, -1, -0.15), (1, -1, -0.15), (1, 1, -0.15), (-1, 1, -0.15)], [], [(0, 1, 2, 3)])
stage = bpy.data.objects.new("stage_0", plane)
stage["sbc_group"] = 0
scene.collection.objects.link(stage)
ground = cns_chain_hook.ground_caster(scene)
check(ground is not None and abs(ground(Vector((0, 0, 0.5)), 1.0)[1].z + 0.15) < 1e-6, "the stage collision is found")
SLANT = (0.03, 0.0, -0.1)      # a chain hanging exactly plumb can't fold: each length pass pushes it straight down
fake, fake_arm = fake_chain({"ground": True, "radius": 0.0})
points = run(fake, fake_arm, ground=ground, local=SLANT)
low = min(p.z for p in points)
check(low > -0.15 - 2e-3, f"ground keeps the points on the stage floor (lowest {low:.4f} m)")
fake, fake_arm = fake_chain({"ground": True, "radius": 0.0})
low = min(p.z for p in run(fake, fake_arm, ground=None, local=SLANT))
check(low < -0.25, f"without stage collision ground is skipped (lowest {low:.4f} m)")


def swinging(values, frames=240):
    """a slanted tendril swinging down under gravity, its chain file's Damping 1.0 (the coats'): how far its tip
    still moves in the last frame"""
    fake, fake_arm = fake_chain(values, damping=1.0)
    before = run(fake, fake_arm, frames=frames - 1, local=SLANT)[3]
    return (run(fake, fake_arm, frames=1, local=SLANT)[3] - before).length


calm, lively = swinging({}), swinging({"damping": 0.0})
check(calm < lively / 20, f"the chain file's Damping 1.0 still settles (auto 0.1: {calm * 100:.4f} cm per frame); "
                            f"damping 0 keeps swinging ({lively * 100:.3f} cm)")


# ---- version 2's checks (chain_solver.md "Checks before it counts as done") ---------------------------------------
def settled_angle(substeps, iterations, frames=400):
    """check 1: stiffness 0.03 against a sideways gravity: the tendril's angle from its animated (straight down)
    direction once it has settled, in degrees"""
    fake, fake_arm = fake_chain({"stiffness": 0.03, "substeps": substeps, "iterations": iterations},
                                gravity=Vector((0.01, 0.0, 0.0)), damping=0.5)
    points = run(fake, fake_arm, frames=frames)
    d = points[3] - points[0]
    return math.degrees(math.acos(min(max(-d.z / d.length, -1.0), 1.0)))


angles = {(n, i): settled_angle(n, i) for n in (4, 8, 16) for i in (1, 2, 4)}
spread = max(angles.values()) - min(angles.values())
check(spread < 0.5 and min(angles.values()) > 1.0,
      f"stiffness settles at the same angle at any substeps / iterations ({min(angles.values()):.2f} to "
      f"{max(angles.values()):.2f} deg)")

# check 5: radius="6 2" = 6 cm at the root, 2 at the tail, linear in between; a segment tapers between its ends
fake, fake_arm = fake_chain({"radius": [6.0, 2.0]}, gravity=Vector())
t = cns_chain_hook._Tendril(fake, 0, Matrix.Identity(4), fake_arm, lambda n: Matrix.Translation((0.0, 0.0, -0.1)),
                            1.0, [])
want = [6.0, 6.0 - 4.0 / 3.0, 2.0 + 4.0 / 3.0, 2.0]
check(all(abs(t.r[k] / cns_chain_hook.SCALE - want[k]) < 1e-9 for k in range(4)),
      f"radius 6 2 along the tendril: {[round(t.r[k] * 100, 3) for k in range(4)]} cm")
fake, fake_arm = fake_chain({"radius": [6.0, 2.0], "pin": 1.0}, gravity=Vector())
centre = Vector((0.02, 0.0, -0.25))        # beside the last segment's middle (the tendril runs 0 to -0.3)
points = run(fake, fake_arm, shapes=[(centre, centre, 0.0)], frames=5)     # pinned: the push alone moves it
u, _ = cns_chain_hook._closest(points[2], points[3], centre, centre)
dist = (points[2].lerp(points[3], u) - centre).length
taper = (want[2] + (want[3] - want[2]) * u) * cns_chain_hook.SCALE
check(abs(dist - taper) < 1e-3, f"a shape keeps the segment's tapered radius ({dist * 100:.2f} cm at u {u:.2f}, "
                                f"wants {taper * 100:.2f})")

# V2.4: a strand trapped on the far side of a shape comes back to its animated side (Ellen's skirt behind a thigh).
# The animated strand hangs straight down at x = 0, clear of a sphere at x = 5 cm; the solved one starts behind it.
def trap(backstop):
    """the tip after 120 frames of a strand started on the far side of a sphere its animated pose clears"""
    fake, fake_arm = fake_chain({"radius": 0.5, "stiffness": 0.3, "backstop": backstop},
                                gravity=Vector((0.0, 0.0, -0.001)))
    run(fake, fake_arm, frames=1)                               # the first solve copies the animation
    trapped = [Vector((0, 0, 0)), Vector((0.06, 0, -0.08)), Vector((0.10, 0, -0.17)), Vector((0.12, 0, -0.27))]
    for k, p in enumerate(trapped):
        fake.mats[k].translation = p
        fake.vel[k] = Vector()
    centre = Vector((0.05, 0.0, -0.15))
    return run(fake, fake_arm, shapes=[(centre, centre, 0.04)], frames=120)


points = trap(True)
check(max(abs(p.x) for p in points) < 0.02 and points[3].z < -0.25,
      f"backstop: a strand trapped behind a shape comes back to its animated side (tip x {points[3].x * 100:.1f} cm, "
      f"z {points[3].z * 100:.1f})")
points = trap(False)
check(points[3].x > 0.08, f"without backstop it stays where it went (tip x {points[3].x * 100:.1f} cm)")
backstop = ext_list.parse('<extensions><model path="m"><physics clt="c" backstop="true"/></model></extensions>')
check(ext_list.physics_values(backstop.elems[-1])["backstop"] and not ext_list.physics_values(ext_list.parse(
      '<extensions><model path="m"><physics clt="c"/></model></extensions>').elems[-1])["backstop"],
      "backstop= parses, off by default")


# V2.5: damp_to="world" slows the points toward standing still instead of toward the animated motion (Ellen's skirt,
# animated rigid to the hips through the legs). The root is carried 1 cm a frame sideways; full damping.
def trailing(damp_world):
    """how far the tip trails the root, in x, after 60 frames of the root moving +x"""
    fake, fake_arm = fake_chain({"damping": [1.0], "damp_world": damp_world, "inertia": 1.0},
                                gravity=Vector((0.0, 0.0, -0.001)))
    for f in range(60):
        cns_chain_hook.solve_tendril(fake, 0, Matrix.Translation((0.01 * f, 0.0, 0.0)), fake_arm,
                                     lambda n: Matrix.Translation((0.0, 0.0, -0.1)), 1.0, [], None)
    return fake.mats[0].translation.x - fake.mats[3].translation.x


animated, world = trailing(False), trailing(True)
check(abs(animated) < 0.01 and world > 0.1,
      f"damp_to animation keeps up with the moving root (tip {animated * 100:.2f} cm behind), world lags it "
      f"({world * 100:.1f} cm behind)")


def damp_to(value):
    text = '<physics clt="c"/>' if value is None else f'<physics clt="c" damp_to="{value}"/>'
    e = ext_list.parse(f'<extensions><model path="m">{text}</model></extensions>').elems[-1]
    values = ext_list.physics_values(e)
    return None if values is None else values["damp_world"]


check((damp_to(None), damp_to("animation"), damp_to("world"), damp_to("World")) == (False, False, True, None),
      "damp_to= parses: animation by default, world, anything else drops the entry (the runner matches exactly)")
d = ext_list.parse('<extensions><model path="m"><physics clt="c" damp_to="still"/></model></extensions>')
check(any(level == "error" and "damp_to" in m for level, _, m in ext_list.issues([("d.xml", d)])),
      "a bad damp_to is an error in Check")


# V2.6: the shapes move across the substeps from where they were at the last solve. A sphere moves 4 cm a frame into
# a hanging strand (a leg into Ellen's skirt); taken at the frame's pose, its whole frame of motion hit the strand in
# the first substep, which left far faster than the sphere moves.
def sweep(v26):
    """the fastest any point moves after a frame (cm per frame) while a sphere moves in +x into the strand"""
    fake, fake_arm = fake_chain({"radius": 0.5, "stiffness": 0.3}, gravity=Vector((0.0, 0.0, -0.001)),
                                max_speed=100.0)
    gather = cns_chain_hook._Tendril.gather

    def as_now(self, ground):
        gather(self, ground)
        self.shapes_from = self.shapes_to       # V2.5: the shapes as now in every substep
    if not v26:
        cns_chain_hook._Tendril.gather = as_now
    try:
        fastest = 0.0
        for f in range(12):
            centre = Vector((min(-0.15 + 0.04 * f, -0.03), 0.0, -0.2))     # 3.5 cm into the strand, then held
            run(fake, fake_arm, shapes=[(centre, centre, 0.06)], frames=1)
            fastest = max(fastest, max(v.length for v in fake.vel))
    finally:
        cns_chain_hook._Tendril.gather = gather
    return fastest * 100


moved, jumped = sweep(True), sweep(False)
check(moved < 4.0 * 2.0 and jumped > moved * 2.0,
      f"V2.6: a sphere moving 4 cm a frame into the strand pushes it at {moved:.1f} cm a frame; taken as now in every "
      f"substep it threw it at {jumped:.1f}")
fake, fake_arm = fake_chain({"radius": 0.5})
centre = Vector((0.0, 0.0, -0.15))
run(fake, fake_arm, shapes=[(centre, centre, 0.03)], frames=2)
check(len(fake.hook.shapes_prev.get(0, [])) == 1, "the last solve's shapes are kept per tendril")
run(fake, fake_arm, shapes=[(centre, centre, 0.03), (centre, centre, 0.02)], frames=1)
check(len(fake.hook.shapes_prev[0]) == 2, "a different shape count starts again from the shapes as now")

# V2.7: the solver keeps its own points; mBlend shapes only the drawn matrices. A strand pushed by a sphere with
# mBlend 0.5: the drawn joint sits halfway to the FK, the next solve starts from the solved point (fed back, the drawn
# one snapped the strand back every frame while its speed stayed the solver's), and from the matrix when another
# writer changed it.
fake, fake_arm = fake_chain({"radius": 0.5, "pin": 0.0}, blend=0.5, gravity=Vector())
centre = Vector((-0.02, 0.0, -0.2))
run(fake, fake_arm, shapes=[(centre, centre, 0.03)], frames=3)
solved, drawn = fake.hook.solved[2], fake.mats[2].translation.copy()


def start_point(k):
    t = cns_chain_hook._Tendril(fake, 0, Matrix.Identity(4), fake_arm, lambda n: Matrix.Translation((0, 0, -0.1)),
                                1.0, [])
    return t.x[k]


check((solved - drawn).length > 0.005 and (start_point(2) - solved).length < 1e-9,
      f"V2.7: with mBlend 0.5 the drawn joint is {(solved - drawn).length * 100:.1f} cm from the solved point, and the "
      "next solve starts from the solved one")
fake.mats[2].translation = drawn + Vector((0.0, 0.01, 0.0))     # another writer (the game's solver, a reset)
check((start_point(2) - fake.mats[2].translation).length < 1e-9, "when something else wrote the joint, from the joint")
chain.albam_phs.hook_damp_to = "world"
check(model_ext.physics_entry(context, chain)[2].get("damp_to") == "world"
      and cns_chain_preview._hook_effective(chain)["damp_to"] == "world", "Damp To in the Chain panel writes the list")
chain.albam_phs.hook_damp_to = "animation"
check(cns_chain_preview._hook_effective(chain)["damp_to"] == "animation"
      and not model_ext.physics_entry(context, chain)[2].has("damp_to"), "and back to the default removes it")

print("FAILURES:", failures)
sys.exit(1 if failures else 0)

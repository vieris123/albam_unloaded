"""Shape keys as the game's morph targets (DMC4 DX9 .mod v153, 2026-11-08; format: shape_format.py,
Vibed/RE/shape_morph.md; user guide docs/shape_keys.md).

DX9 has a complete GPU morph-target system that no shipped file uses: an `.shp` (rShape) holds per model part a map
of position deltas per shape key, an `.shw` (rShapeWeight) the keys' weight curves, and dmc4_hook's ModelExtension
`<shape>` entry puts them on the model (the game never sets them itself, and players never run the weight update).

A key plays when it's set above 0 or one of the Key's clips animates it (`playing_keys`); keys left at 0 (an imported
model's unused expressions) change nothing. At .mod export (`ShapePlan`, used by mesh.py), every mesh with a playing
key that moves a vertex morphs:
- its record gets the shape flag (+0xB bit 0): the draw binds the part's map only for flagged meshes;
- its material record skin function 5, SKIN_4WT_SHAPE (vtype 0 only; a material also drawing meshes that don't morph
  is written twice, since those meshes' TEXCOORD1 holds no UV);
- each vertex's TEXCOORD0 its texel (column, row) in its part's map (`shape_format.texel`), TEXCOORD1 its UV: every
  shape vertex shader reads the UVs there.
The `.shp` goes beside the .mod (same game path). A target is a (part, key name): meshes of one part share the part's
map, so a key of the same name on two of them is one target. Deltas are key minus its relative key (times the key's
vertex group), in the model's rest frame; the game adds them before skinning. Normals don't morph.

Weight lists (`.shw`), each with a curve for every target (the game leaves a list off otherwise):
- `<model>.shw`: the keys' set values, one key per curve (0 for keys a clip animates): a body shape. The
  ModelExtension `<shape shw=>` plays it as list 0.
- `<model>_<clip>.shw` per clip: an action on a morphing mesh's Key, active or in its NLA (stashed ones too). Its
  F-curves are sampled on game frames (60 fps, from the clip's start) as linear keys; the keys it doesn't animate keep
  their set value. MoveDef `<shape shw=>` (lists 1-3) plays them from a move, or `<shape shw=>` as the idle.
The game averages the playing lists by rate, so a clip playing beside list 0 shares each weight with it.
"""
from collections import OrderedDict

import bpy
import numpy as np

from albam.exceptions import AlbamCheckFailure
from albam.lib.blender_compat import fcurves_of
from albam.vfs import VirtualFileData
from . import shape_format
from .shape_format import Curve, Target

SHAPE_SKIN = 5              # SKIN_4WT_SHAPE
SHAPE_VTYPE = 0             # the 4-weight layout, TEXCOORD0 at +24 and TEXCOORD1 at +28
SHAPE_COPY = "shape"        # materials_map key (name, SHAPE_COPY): the skin-5 copy of a material shared with plain meshes
DELTA_EPSILON = 1e-7        # Blender units: a key moving no vertex more than this doesn't morph
FRAMERATE = 60
# The shader keys (pipeline // 7: lighting + 5 normalmap + 20 specular + 100 lightmap + 800 multitexture) that have a
# SKIN_4WT_SHAPE vertex and pixel shader in XfMaterialStandard.bfx (permutation table at 0x56C; 74 of the 194 SKIN_4WT
# keys have none: lighting 1, specular 2, normal maps 2 / 3, most lightmaps)
SHADER_KEYS = frozenset((
    0, 2, 3, 4, 5, 7, 8, 9, 10, 12, 13, 14, 20, 22, 23, 24, 25, 27, 28, 29, 30, 32, 33, 34,
    60, 62, 63, 64, 65, 67, 68, 69, 70, 72, 73, 74, 80, 82, 83, 84, 85, 87, 88, 89, 90, 92, 93, 94,
    700, 702, 703, 704, 705, 707, 708, 709, 710, 712, 713, 714, 720, 722, 723, 724, 725, 727, 728, 729, 730, 732, 733, 734,
    760, 762, 763, 764, 765, 767, 768, 769, 770, 772, 773, 774, 780, 782, 783, 784, 785, 787, 788, 789, 790, 792, 793, 794,
    4020, 4022, 4023, 4024, 4025, 4027, 4028, 4029, 4030, 4032, 4033, 4034,
    4080, 4082, 4083, 4084, 4085, 4087, 4088, 4089, 4090, 4092, 4093, 4094))


def _vertex_coords(data, count):
    flat = np.empty(count * 3, dtype=np.float64)
    data.foreach_get("co", flat)
    return flat.reshape(count, 3)


def clips(key):
    """the actions of a Key: the active one, then its NLA strips' (stashed actions too), each once"""
    ad = key.animation_data if key is not None else None
    if ad is None:
        return []
    out = [ad.action] if ad.action is not None else []
    for track in ad.nla_tracks:
        out += [s.action for s in track.strips if s.action is not None and s.action not in out]
    return out


def _value_path(name):
    return f'key_blocks["{bpy.utils.escape_identifier(name)}"].value'


def key_curve(action, name, key):
    """the F-curve animating key block `name` in an action (a Key's slot on Blender 5), or None"""
    path = _value_path(name)
    return next((fc for fc in fcurves_of(action, key) if fc.data_path == path and len(fc.keyframe_points)), None)


def _animated(key):
    """escaped names of the key blocks the Key's clips animate"""
    out = set()
    for action in clips(key):
        out |= {fc.data_path[len('key_blocks["'):-len('"].value')] for fc in fcurves_of(action, key)
                if fc.data_path.startswith('key_blocks["') and fc.data_path.endswith('"].value') and
                len(fc.keyframe_points)}
    return out


def model_animated(obs):
    """escaped key names any clip of these meshes' Keys animates: a clip drives its key names on the whole model"""
    out = set()
    for ob in obs:
        key = _source(ob).data.shape_keys if ob.type == "MESH" else None    # an export copy's Key may lack the animation
        if key is not None:
            out |= _animated(key)
    return out


def playing_keys(ob, animated=None):
    """the shape keys of ob that do something: not the reference key, not muted, relative, and set above 0 or animated
    (`animated`: model_animated of the model's meshes, else ob's own clips). Keys left at 0 (an imported model's unused
    expressions) don't make the mesh morph."""
    key = ob.data.shape_keys if ob.type == "MESH" else None
    if key is None or not key.use_relative or len(key.key_blocks) < 2:
        return []
    if animated is None:
        animated = model_animated([ob])
    return [kb for kb in key.key_blocks if kb != key.reference_key and not kb.mute and kb.relative_key != kb and
            (kb.value != 0.0 or bpy.utils.escape_identifier(kb.name) in animated)]


def moving_keys(ob, animated=None):
    """[(key name, deltas (n x 3, Blender units, the mesh's frame))] of the playing_keys that move ob's vertices"""
    keys = playing_keys(ob, animated)
    if not keys:
        return []
    count = len(ob.data.vertices)
    coords = {}

    def co(kb):
        if kb.name not in coords:
            coords[kb.name] = _vertex_coords(kb.data, count)
        return coords[kb.name]

    out = []
    for kb in keys:
        deltas = co(kb) - co(kb.relative_key)
        group = ob.vertex_groups.get(kb.vertex_group) if kb.vertex_group else None
        if group is not None:
            weights = np.zeros(count)
            for v in ob.data.vertices:
                for g in v.groups:
                    if g.group == group.index:
                        weights[v.index] = g.weight
            deltas = deltas * weights[:, None]
        if np.abs(deltas).max(initial=0.0) > DELTA_EPSILON:
            out.append((kb.name, deltas))
    return out


def model_has_keys(root):
    """a quick test (no vertices read, for panels): a mesh of the model has a shape key that plays"""
    from .joints import model_meshes
    obs = model_meshes(root)
    animated = model_animated(obs)
    return any(playing_keys(ob, animated) for ob in obs)


def model_weight_lists(root):
    """(rest list or None, [clip lists], the active clip's list or None): the .shw paths (without extension) a model's
    export writes, for pickers and Fill from Scene, read cheaply (a clip animating only keys that move nothing is
    listed too). The rest list counts only when a key is set above 0 without a clip driving it."""
    from .joints import model_meshes
    model_path = root.albam_asset.relative_path
    keys, playing, active = [], [], None
    obs = model_meshes(root)
    animated = model_animated(obs)
    for ob in obs:
        mine = playing_keys(ob, animated)
        if mine and ob.data.shape_keys not in keys:
            keys.append(ob.data.shape_keys)
        playing += mine
    rest = any(kb.value != 0.0 and bpy.utils.escape_identifier(kb.name) not in animated for kb in playing)
    actions, used = [], set()
    for key in keys:
        for action in clips(key):
            if action not in [a for a, _ in actions]:
                path = clip_path(model_path, action.name, used)
                used.add(path.lower())
                actions.append((action, path))
                if active is None and key.animation_data.action == action:
                    active = path
    stem = model_path.rsplit(".", 1)[0]
    return (stem if rest else None), [p for _, p in actions], active


def _hex(props, name, default=0):
    try:
        return int(getattr(props, name), 16)
    except (AttributeError, TypeError, ValueError):
        return default


def shader_key(props):
    """the material's shader key without its skin function (pipeline // 7)"""
    return (_hex(props, "func_lighting") + 5 * _hex(props, "func_normalmap") + 20 * _hex(props, "func_specular") +
            100 * _hex(props, "func_lightmap") + 800 * _hex(props, "func_multitexture"))


def _source(ob):
    """the object a prepared export copy (mesh_prep) was made from: its Key's animation is the user's"""
    name = ob.get("albam_export_copy_of")
    return bpy.data.objects.get(name, ob) if name else ob


class ShapePlan:
    """The morphs of a model's exported meshes (`bl_meshes` in export order). Empty (falsy) when none morphs."""

    def __init__(self, app_id, bl_meshes, has_bones):
        self.app_id = app_id
        self.texel_start = {}           # mesh index: its first vertex's number in its part's map
        self.maps = []                  # [(part, width, height)]
        self.targets = []               # [Target]
        self.target_sources = []        # per target: (key name, [mesh objects of the part with that key])
        self.materials = {}             # material name: also drawn by a mesh that doesn't morph
        self.notes = []
        animated = model_animated(bl_meshes)
        keys = {i: moving_keys(ob, animated) for i, ob in enumerate(bl_meshes)}
        morphing = [i for i, k in keys.items() if k]
        if not morphing:
            return
        self._check(bl_meshes, morphing, has_bones)
        for i, ob in enumerate(bl_meshes):
            name = ob.data.materials[0].name
            if i in morphing:
                self.materials.setdefault(name, False)
        for i, ob in enumerate(bl_meshes):
            name = ob.data.materials[0].name
            if i not in morphing and name in self.materials:
                self.materials[name] = True
        parts = OrderedDict()
        for i in morphing:
            parts.setdefault(self._part(bl_meshes[i]), []).append(i)
        for part in sorted(parts):
            self._add_part(part, parts[part], bl_meshes, keys)

    def __bool__(self):
        return bool(self.texel_start)

    def _part(self, ob):
        return ob.data.albam_custom_properties.get_custom_properties_for_appid(self.app_id).idx_group

    def _check(self, bl_meshes, morphing, has_bones):
        problems = []
        if not has_bones:
            problems.append("the model has no bones: the shape shaders skin with 4 weights")
        for i in morphing:
            ob = bl_meshes[i]
            mat = ob.data.materials[0]
            props = mat.albam_custom_properties.get_custom_properties_for_appid(self.app_id)
            vtype = _hex(props, "vtype")
            if vtype != SHAPE_VTYPE:
                problems.append(f"{ob.name}: material {mat.name} has vtype {vtype}, shape keys need VTYPE_SKIN (0, "
                                "4 weights per vertex)")
            elif shader_key(props) not in SHADER_KEYS:
                problems.append(f"{ob.name}: material {mat.name} has no SKIN_4WT_SHAPE shader for its lighting / "
                                "normal map / specular / lightmap functions")
            if self._part(ob) >= shape_format.MAX_PARTS:
                problems.append(f"{ob.name}: part (Group ID) {self._part(ob)} is past the game's {shape_format.MAX_PARTS}")
        if problems:
            raise AlbamCheckFailure(
                "Some meshes with shape keys can't morph in the game", details="\n".join(problems),
                solution="Use a 4-weight skinned material (VTYPE_SKIN, SKIN_4WT: limit the weights to 4 with Weights > "
                         "Limit Total) with lighting other than 1, normal map 0 or 1, specular other than 2; or "
                         "delete or mute the shape keys of these meshes")

    def _add_part(self, part, indices, bl_meshes, keys):
        width = shape_format.MAP_WIDTH
        count = 0
        for i in indices:
            self.texel_start[i] = count
            count += len(bl_meshes[i].data.vertices)
        if count > shape_format.max_vertices(width):
            raise AlbamCheckFailure(
                f"Part {part} has too many vertices with shape keys", details=f"{count} vertices",
                solution=f"A part's map addresses {shape_format.max_vertices(width)}: give some of its meshes another "
                         "Group ID (Object Data Properties > DMC4 mesh)")
        height = shape_format.map_height(count, width)
        map_index = len(self.maps)
        self.maps.append((part, width, height))
        names = []
        for i in indices:
            names += [name for name, _ in keys[i] if name not in names]
        for name in names:
            texels = np.zeros((width * height, 4), dtype=np.float32)
            holders = []
            for i in indices:
                deltas = next((d for n, d in keys[i] if n == name), None)
                if deltas is None:
                    continue
                holders.append(bl_meshes[i])
                number = self.texel_start[i] + np.arange(len(deltas))
                address = (number // (width - 1)) * width + number % (width - 1)
                texels[address, 0] = deltas[:, 0] * 100.0       # Blender (x, y, z) m -> game (x, z, -y) cm
                texels[address, 1] = deltas[:, 2] * 100.0
                texels[address, 2] = -deltas[:, 1] * 100.0
            self.targets.append(Target(map_index, texels.tobytes()))
            self.target_sources.append((name, holders))
        if len(names) > shape_format.MAX_ACTIVE_TARGETS:
            self.notes.append(f"part {part} has {len(names)} shape keys: the game blends at most "
                              f"{shape_format.MAX_ACTIVE_TARGETS} with a weight above 0 at once")

    def texels(self, mesh_index, count):
        """[(column, row)] of a morphing mesh's vertices, else None"""
        start = self.texel_start.get(mesh_index)
        if start is None:
            return None
        return [shape_format.texel(start + k) for k in range(count)]

    def shp(self):
        return shape_format.build_shp(self.maps, self.targets)

    def _keys(self):
        """the Keys of the morphing meshes as the user has them (an export copy's source), each once"""
        out = []
        for _, holders in self.target_sources:
            for ob in holders:
                key = _source(ob).data.shape_keys
                if key is not None and key not in out:
                    out.append(key)
        return out

    def clips(self):
        """[(action, owner Key)] of every clip of the morphing meshes' Keys"""
        out = []
        for key in self._keys():
            out += [(action, key) for action in clips(key) if action not in [a for a, _ in out]]
        return out

    def rest_values(self):
        """per target: its key's set value, 0 for a key name a clip animates (the clip drives it)"""
        animated = set()
        for key in self._keys():
            animated |= _animated(key)
        out = []
        for name, holders in self.target_sources:
            kb = _source(holders[0]).data.shape_keys.key_blocks.get(name)
            out.append(0.0 if bpy.utils.escape_identifier(name) in animated or kb is None else kb.value)
        return out

    def rest_shw(self):
        """the weight list holding every key at its rest value"""
        return shape_format.build_shw([Curve(v, [(0, shape_format.INTERP_LINEAR, v)]) for v in self.rest_values()], 1)

    def clip_shw(self, action, key, scene):
        """a clip's weight list, or None when it animates none of the targets. It drives every key of a name it
        animates, on every mesh (pieces of one mesh split by material each have their own Key)"""
        fps = scene.render.fps / scene.render.fps_base
        found = [key_curve(action, name, key) for name, _ in self.target_sources]
        animated = [fc for fc in found if fc is not None]
        if not animated:
            return None
        if action.use_frame_range:
            start, end = action.frame_range
        else:
            start, end = min(fc.range()[0] for fc in animated), max(fc.range()[1] for fc in animated)
        frame_max = max(1, round((end - start) * FRAMERATE / fps))
        out = []
        for fcurve, rest in zip(found, self.rest_values()):
            if fcurve is None:
                out.append(Curve(rest, [(0, shape_format.INTERP_LINEAR, rest)]))
                continue
            samples = [fcurve.evaluate(start + g * fps / FRAMERATE) for g in range(frame_max + 1)]
            keys = shape_format.linear_keys(samples)
            out.append(Curve(keys[0][1], [(f, shape_format.INTERP_LINEAR, v) for f, v in keys]))
        return shape_format.build_shw(out, frame_max)

    def files(self, app_id, model_path, scene):
        """the .shp, the rest list <model>.shw and one <model>_<clip>.shw per clip (clip_path)"""
        stem = model_path.rsplit(".", 1)[0]
        out = [VirtualFileData(app_id, f"{stem}.shp", data_bytes=self.shp()),
               VirtualFileData(app_id, f"{stem}.shw", data_bytes=self.rest_shw())]
        used = set()
        for action, key in self.clips():
            data = self.clip_shw(action, key, scene)
            if data is not None:
                path = clip_path(model_path, action.name, used)
                used.add(path.lower())
                out.append(VirtualFileData(app_id, f"{path}.shw", data_bytes=data))
        return out


def clip_path(model_path, action_name, used=()):
    """a clip's .shw game path without extension: <model>_<action name>, ASCII, numbered if taken"""
    from .texture_convert import game_name
    stem = model_path.rsplit(".", 1)[0]
    path = f"{stem}_{game_name(action_name, 'clip')}"
    n = 2
    while path.lower() in used:
        path = f"{stem}_{game_name(action_name, 'clip')}_{n}"
        n += 1
    return path

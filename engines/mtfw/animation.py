from ctypes import Structure, Union, c_ulonglong, c_double, c_uint64, c_uint8
from enum import Enum

import ctypes
import math
import io
import struct
import numpy as np
import bpy
from kaitaistruct import KaitaiStream
from mathutils import Euler, Matrix, Vector, Quaternion
from io import BytesIO
import mathutils
import numpy as np

from albam.exceptions import AlbamCheckFailure
from albam.registry import blender_registry
from .structs.lmt import Lmt

class BufferType49(Enum):
    SingleVector3 = 2
    StepRotationQuat3 = 4
    HermiteVector3 = 5
    LinearRotationQuat4_14bit = 6
    LinearVector3 = 9

class TrackType(Enum):
    LocalRotation = 0
    LocalPosition = 1
    LocalScale = 2
    AbsoluteRotation = 3
    AbsolutePosition = 4

# HACKY_BONE_INDEX_IK_FOOT_RIGHT = 19
# HACKY_BONE_INDEX_IK_FOOT_LEFT = 23
HACKY_BONE_INDEX_IK_FOOT_RIGHT = 16
RIGHT_LEG_BONE0 = 14
RIGHT_LEG_BONE1 = 15
HACKY_BONE_INDEX_IK_FOOT_LEFT = 20
LEFT_LEG_BONE0 = 18
LEFT_LEG_BONE1 = 19
IK_HIPS = 0
HACKY_BONE_INDICES_IK_FOOT = {HACKY_BONE_INDEX_IK_FOOT_RIGHT, HACKY_BONE_INDEX_IK_FOOT_LEFT}
ROOT_UNK_BONE_ID = 254
ROOT_MOTION_BONE_ID = 255
ROOT_MOTION_BONE_NAME = 'root_motion'
ROOT_BONE_NAME = '0'
ROOT_BONE_RENAMED = 'root'
FRAMERATE = 60

#TODO: Fix reference frame
@blender_registry.register_import_function(app_id="re5", extension='lmt', file_category="ANIMATION")
@blender_registry.register_import_function(app_id="dmc4", extension='lmt', file_category="ANIMATION")
def load_lmt(file_item, context):
    app_id = file_item.app_id
    lmt_bytes = file_item.get_bytes()
    lmt = Lmt(KaitaiStream(io.BytesIO(lmt_bytes)))
    lmt._read()
    armature = context.scene.albam.import_options_lmt.armature
    renamed_bone_flag = context.scene.albam.import_options_lmt.renamed_bone_flag
    mapping = _create_bone_mapping(armature)

    lmt_group = context.scene.albam.lmt_groups.add(file_item.display_name)
    lmt_group.num_slots = lmt.num_block_offsets
    lmt_group.armature = armature
    lmt_group.export_path = getattr(file_item, "absolute_path", "")

    context.scene.render.fps = FRAMERATE

    # DEBUG_BLOCK = 2
    DEBUG_BLOCK = None

    for block_index, block in enumerate(lmt.block_offsets):
        if block.offset == 0:
            continue
        if DEBUG_BLOCK is not None and DEBUG_BLOCK != block_index:
            continue
        armature.animation_data_create()
        name = f"{armature.name}.{file_item.display_name}.{str(block_index).zfill(4)}"

        action = bpy.data.actions.new(name)
        lmt_group.add(action)
        action.frame_end = block.block_header.num_frames

        action.albam_asset.app_id = app_id
        action.albam_asset.lmt_index = block_index
        custom_property = action.albam_custom_properties.get_custom_properties_for_appid(app_id)
        custom_property.copy_from_lmt(block.block_header, block_index)

        _import_events(action, custom_property, block.block_header.events_01, "Hitbox")
        _import_events(action, custom_property, block.block_header.events_02, "Sound")

        #Loops
        is_cyclic = False
        if block.block_header.loop_frames > -1:
            action.use_cyclic = True
            is_cyclic = True
            #action.use_frame_range = True
            #action.frame_range = Vector([block.block_header.loop_frames, block.block_header.num_frames])

        action.use_fake_user = True
        #context.scene.albam.import_options_lmt.armature.animation_data.action = action
        
        for track_index, track in enumerate(block.block_header.tracks):
            bone_index = mapping.get(str(track.bone_index))

            if bone_index is None and track.bone_index == ROOT_MOTION_BONE_ID:
                bone_index = _get_or_create_root_motion_bone(armature)

            elif bone_index is None and track.bone_index == ROOT_UNK_BONE_ID:
                # Probably some kind of object tracker bone (weapon?)
                # TODO: do something with this
                continue
            elif bone_index is None:
                # TODO: better stats
                print(f"bone_index not found!: [{track.bone_index}]")
                continue
            # if track.bone_index in HACKY_BONE_INDICES_IK_FOOT:
            #     bone_index = _get_or_create_ik_bone(armature, track.bone_index, bone_index)

            if track.buffer_type == 6:
                TRACK_MODE = "rotation_quaternion"  # TODO: improve naming
                action_type = 'rotation'
                decoded_frames = decode_type_6(track.data)
                decoded_frames = _parent_space_to_local_rot(decoded_frames, armature, bone_index)

            elif track.buffer_type == 4:
                TRACK_MODE = "rotation_quaternion"
                action_type = 'rotation'
                decoded_frames = decode_type_4(track.data)
                decoded_frames = _parent_space_to_local_rot(decoded_frames, armature, bone_index)

            elif track.buffer_type == 2:
                print(f'Buffer type 2 track type {track.usage}')
                if track.usage == 1:
                    TRACK_MODE = 'location'
                    action_type = 'location'
                    decoded_frames = decode_type_2(track.data)
                    decoded_frames = _parent_space_to_local(decoded_frames, armature, bone_index)
                elif track.usage == 2:
                    TRACK_MODE = 'scale'
                    action_type = 'scale'
                    decoded_frames = decode_type_2_scale(track.data)
                    world_pos_fix(decoded_frames)
                elif track.usage == 4:
                    TRACK_MODE = 'location'
                    action_type = 'location'
                    decoded_frames = decode_type_2(track.data)
                    world_pos_fix(decoded_frames)
                else:
                    continue

            elif track.buffer_type == 9:
                print(f'Buffer type 9 track type {track.usage}')
                if track.usage == 1:
                    TRACK_MODE = 'location'
                    action_type = 'location'
                    decoded_frames = decode_type_9(track.data)
                    decoded_frames = _parent_space_to_local(decoded_frames, armature, bone_index)

                elif track.usage == 2:
                    TRACK_MODE = 'scale'
                    action_type = 'scale'
                    decoded_frames = decode_type_9_scale(track.data)
                    world_pos_fix(decoded_frames)

                elif track.usage == 4:
                    TRACK_MODE = 'location'
                    action_type = 'location'
                    decoded_frames = decode_type_9(track.data)
                    world_pos_fix(decoded_frames)
                else:
                    continue

            else:
                # TODO: print statistics of missing tracks
                # print("Unknown buffer_type, skipping", track.buffer_type)
                continue
            
            # group_name = f"{track.bone_index}.{bone_index}.{action_type}"
            # group = action.groups.get(group_name) or action.groups.new(group_name)

            #TOGGLE RENAMED BONES
            if renamed_bone_flag:
                data_path = f"pose.bones[\"{armature.data.bones[bone_index].name}\"].{TRACK_MODE}"
                group_name = f"{track.bone_index}.{armature.data.bones[bone_index].name}.{action_type}"
                group = action.groups.get(group_name) or action.groups.new(group_name)
            else:
                data_path = f"pose.bones[\"{bone_index}\"].{TRACK_MODE}"
                group_name = f"{track.bone_index}.{bone_index}.{action_type}"
                group = action.groups.get(group_name) or action.groups.new(group_name)
            try:
                num_curv = len(decoded_frames[0])
            except IndexError:
                print(f'Index out of range\n ',
                      f'Buffer type: {track.buffer_type}, track type {track.usage}, mode {TRACK_MODE}\n',
                      f'Track num {track_index}')

            print(f"Block {block_index}, track {track_index}, bone {track.bone_index}: {num_curv}")
            curves = []
            for i in range(num_curv):
                try:
                    #action.fcurves.new(data_path=data_path, index=i, action_group=group_name)
                    curve = action.fcurves.new(data_path=data_path, index=i, action_group=group_name)
                    curves.append(curve)
                    if is_cyclic:
                        mod = curve.modifiers.new('CYCLES')
                        mod.use_restricted_range = True
                        mod.frame_start = block.block_header.loop_frames

                except KeyError as err:
                    print('unknown error:', err)
                    curves.append(action.fcurves.new(data_path=data_path+'[1]', index=i, action_group=group_name))

            # stored keys start at frame 0, the game's frames (see decode_type_6)
            for frame_index, frame_data in enumerate(decoded_frames):
                if frame_data is None:
                    continue
                for curve_idx, curve in enumerate(curves):
                    curve.keyframe_points.add(1)
                    curve.keyframe_points[-1].co = (frame_index, frame_data[curve_idx])
                    curve.keyframe_points[-1].interpolation = 'LINEAR'
                        
    lmt_groups = context.scene.albam.lmt_groups
    lmt_groups.active_group_id = len(lmt_groups.anim_group) - 1
    lmt_groups.anim_group[-1].active_id = 0


def _create_bone_mapping(armature_obj):
    mapping = {}

    for b_idx, mapped_bone in enumerate(armature_obj.data.bones):
        reference_bone_id = mapped_bone.get('mtfw.anim_retarget')  # TODO: better name

        if reference_bone_id is None:
            print(f"WARNING: {armature_obj.name}->{mapped_bone.name} doesn't contain a mapped bone")
            continue

        if reference_bone_id in mapping:
            print(f"WARNING: bone_id {b_idx} already mapped. TODO")
        mapping[reference_bone_id] = b_idx
        
    return mapping

class FrameQuat4_14(Structure):
    _fields_ = (
        ('_x', c_uint64, 17),
        ('_y', c_uint64, 17),
        ('_wComp', c_uint64, 19),
        ('_x_sign', c_uint64, 1),
        ('_y_sign', c_uint64, 1),
        ('_z_sign', c_uint64, 1),
        ('duration', c_uint64, 8)
    )

    mask = struct.unpack('@d', struct.pack('@d', ((1 << 17) - 1)))[0]
    maskW = struct.unpack('@d', struct.pack('@d', ((1 << 19) - 1)))[0]
    maskInv = mask / (np.pi / 2.0)
    maskMult = 1.0 / maskInv
    maskMultW = 1.0 / maskW

    wComp = 0
    x = 0
    y = 0
    z = 0
    w = 0

    def calc_components(self):
        self.wComp = self._wComp * self.maskMultW
        self.wComp = 1.0 - (self.wComp * self.wComp)
        magnitude = np.sqrt(1.0 - (self.wComp * self.wComp))

        self.x = struct.unpack('@d', struct.pack('@d', self._x))[0]
        self.y = struct.unpack('@d', struct.pack('@d', self._y))[0]

        self.x = self.x * self.maskMult
        self.y = self.y * self.maskMult
        self.z = self.x - (np.pi / 2.0)
        self.w = self.y - (np.pi / 2.0)

        trig_arr = [np.sin(self.x), np.sin(self.y), np.cos(self.x), np.cos(self.y)]

        self.x = trig_arr[0] * trig_arr[3] * magnitude
        self.y = trig_arr[1] * magnitude
        self.z = trig_arr[2] * trig_arr[3] * magnitude
        self.w = self.wComp

        if self._x_sign:
            self.x *= -1.0

        if self._y_sign:
            self.y *= -1.0

        if self._z_sign:
            self.z *= -1.0

    def from_quat(self, quat, duration):
        # w is stored without a sign, so flip the whole quaternion first (same rotation),
        # then store the x, y, z signs
        if quat[0] < 0.0:
            quat = [x * -1.0 for x in quat]

        if quat[1] < 0.0:
            quat[1] *= -1.0
            self._x_sign = 1

        if quat[2] < 0.0:
            quat[2] *= -1.0
            self._y_sign = 1

        if quat[3] < 0.0:
            quat[3] *= -1.0
            self._z_sign = 1

        R = np.sqrt(1.0 - quat[0])
        mag_safe = np.sqrt(1.0 - (quat[0] * quat[0]))
        mag = 1.0 if mag_safe < 0.00001 else mag_safe

        phi = np.arcsin(np.clip((quat[2] / mag), -1.0, 1.0))
        theta = np.arcsin(np.clip((quat[1] / (np.cos(phi) * mag)), -1.0, 1.0))
        test = theta * self.maskInv
        try:
            self._x = int(theta * self.maskInv)
            #self._x = struct.unpack('@Q', struct.pack('@d', (theta * self.maskInv)))[0]
            #self._x = int(theta * self.maskInv)
            self._y = int(phi * self.maskInv)
            #self._y = struct.unpack('@Q', struct.pack('@d', (phi * self.maskInv)))[0]
            self._wComp = int(R * self.maskW)
            #self._wComp = struct.unpack('@Q', struct.pack('@d', (R * self.maskW)))[0]
            self.duration = duration
        except ValueError:
            print(f'X val: {quat[1]}')
            print(f'Y val: {quat[2]}')
            print(f'Phi: {phi}')
            print(f'Theta: {theta}')
            print(f'Mag: {mag}')

    def send(self):
        return buffer(self)[:]
        
class FrameQuat4_14U(Union):
    _fields_ = [('quat4_14', FrameQuat4_14),
                ('val', c_ulonglong)]

def decode_type_9(data):
    decoded_frames = []
    CHUNK_SIZE = 16

    for start in range(0, len(data), CHUNK_SIZE):
        chunk = data[start: start + CHUNK_SIZE]
        u = struct.unpack("fffI", chunk)
        floats = (u[0] / 100, u[1] / 100, u[2] / 100)
        duration = u[3]
        decoded_frames.append(floats)
        decoded_frames.extend([None] * max(duration - 1, 0))
    return decoded_frames

def decode_type_9_scale(data):
    decoded_frames = []
    CHUNK_SIZE = 16

    for start in range(0, len(data), CHUNK_SIZE):
        chunk = data[start: start + CHUNK_SIZE]
        u = struct.unpack("fffI", chunk)
        floats = (u[0], u[1], u[2])
        duration = u[3]
        decoded_frames.append(floats)
        decoded_frames.extend([None] * max(duration - 1, 0))
    return decoded_frames

def decode_type_2(data):
    decoded_frames = []
    CHUNK_SIZE = 12

    for start in range(0, len(data), CHUNK_SIZE):
        chunk = data[start: start + CHUNK_SIZE]
        u = struct.unpack("fff", chunk)
        floats = (u[0] / 100, u[1] / 100, u[2] / 100)
        decoded_frames.append(floats)
    return decoded_frames

def decode_type_2_scale(data):
    decoded_frames = []
    CHUNK_SIZE = 12

    for start in range(0, len(data), CHUNK_SIZE):
        chunk = data[start: start + CHUNK_SIZE]
        u = struct.unpack("fff", chunk)
        floats = (u[0], u[1], u[2])
        decoded_frames.append(floats)
    return decoded_frames

def decode_type_4(data):
    decoded_frames = []
    CHUNK_SIZE = 12

    for start in range(0, len(data), CHUNK_SIZE):
        chunk = data[start: start + CHUNK_SIZE]
        u = struct.unpack("fff", chunk)
        w = u[0] ** 2 + u[1] ** 2 + u[2] ** 2
        w = 1.0 - w
        if (w < 0.0):
            w = 0.0
        w = np.sqrt(w)

        floats= (w, u[0], u[1], u[2])
        decoded_frames.append(floats)
    return decoded_frames

def decode_type_4_euler(data):
    decoded_frames = []
    CHUNK_SIZE = 12

    for start in range(0, len(data), CHUNK_SIZE):
        chunk = data[start: start + CHUNK_SIZE]
        u = struct.unpack("fff", chunk)
        w = u[0] ** 2 + u[1] ** 2 + u[2] ** 2
        w = 1.0 - w
        if (w < 0.0):
            w = 0.0
        floats = (u[0], u[2], -u[1])
        decoded_frames.append(floats)
    return decoded_frames

def decode_type_6(data):
    """
    Keys in game frames, None where there's no key. Stored keys start at frame 0 (the first one
    equals the track's ref_data) and a key's duration is the number of frames to the next key,
    0 on the last key, which holds. Confirmed in uModel::calcMotionQuaternion (0xAE0400) and
    against all DX9 files: durations always add up to num_frames - 1
    """
    decoded_frames = []

    for idx, start in enumerate(range(0, len(data), 8)):
        chunk = data[start: start + 8]
        frame = FrameQuat4_14()
        io.BytesIO(chunk).readinto(frame)
        frame.calc_components()

        decoded_frames.append((frame.w, frame.x, frame.y, frame.z))
        decoded_frames.extend([None] * max(frame.duration - 1, 0))

    return decoded_frames


def _get_or_create_ik_bone(armature, track_bone_index, bone_index):

    if track_bone_index == HACKY_BONE_INDEX_IK_FOOT_RIGHT:
        postfix = "R"
    else:
        postfix = "L"

    bone_name = f"IK_Foot.{postfix}"
    if bone_name in armature.data.bones:
        return bone_name

    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    # deselect all objects
    bpy.ops.object.select_all(action='DESELECT')
    bpy.context.view_layer.objects.active = armature
    armature.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')

    blender_bone = armature.data.edit_bones.new(bone_name)
    blender_bone.head = armature.data.edit_bones[bone_index].head
    blender_bone.tail = armature.data.edit_bones[bone_index].tail
    bpy.ops.object.mode_set(mode='OBJECT')

    pose_bone = armature.pose.bones[str(bone_index)]
    constraint = pose_bone.constraints.new('IK')
    constraint.target = armature
    constraint.subtarget = bone_name
    constraint.chain_count = 3
    constraint.use_rotation = True

    root_motion_bone = _get_or_create_root_motion_bone(armature)
    pose_bone = armature.pose.bones[bone_name]
    constraint = pose_bone.constraints.new('COPY_LOCATION')
    constraint.target = armature
    constraint.subtarget = root_motion_bone
    constraint.use_offset = True

    return bone_name


def _get_or_create_root_motion_bone(armature):
    bone_name = ROOT_MOTION_BONE_NAME
    if bone_name in armature.data.bones:
        return bone_name

    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    # deselect all objects
    bpy.ops.object.select_all(action='DESELECT')
    bpy.context.view_layer.objects.active = armature
    armature.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')

    blender_bone = armature.data.edit_bones.new(bone_name)
    blender_bone.tail[2] += 0.01
    bpy.ops.object.mode_set(mode='OBJECT')

    if ROOT_BONE_NAME in armature.pose.bones.keys():
        pose_bone = armature.pose.bones[ROOT_BONE_NAME]
    else:
        pose_bone = armature.pose.bones[ROOT_BONE_RENAMED]
    constraint = pose_bone.constraints.new('COPY_LOCATION')
    constraint.target = armature
    constraint.subtarget = bone_name
    constraint.use_offset = True

    return bone_name


def _parent_space_to_local(decoded_frames, armature, bone_index):
    local_space_frames = []
    for frame in decoded_frames:
        if frame is None:
            local_space_frames.append(None)
            continue

        bone = armature.data.bones[bone_index]
        if bone.parent:
            parent_space = bone.parent.matrix_local.inverted() @ bone.matrix_local #child - parent matrix

        elif bone_index == 255:
            parent_space = Matrix([[1.0, 0.0, 0.0, 0.0],
                                    [0.0, 0.0, 1.0, 0.0],
                                    [0.0, -1.0, 0.0, 0.0],
                                    [0.0, 0.0, 0.0, 1.0]])
            
        else:
            parent_space = Matrix([[1.0, 0.0, 0.0, 0.0],
                                    [0.0, 1.0, 0.0, 0.0],
                                    [0.0, 0.0, 1.0, 0.0],
                                    [0.0, 0.0, 0.0, 1.0]])
        transform_mat = Matrix.Translation(frame)
    
        local_space_frame = (parent_space.inverted() @ transform_mat).to_translation()
        local_space_frames.append(local_space_frame)
    return local_space_frames


def _parent_space_to_local_rot(decoded_frames, armature, bone_index):
    local_space_frames = []
    for frame in decoded_frames:
        if frame is None:
            local_space_frames.append(None)
            continue

        #bone = armature.data.bones[bone_index]
        bone = armature.data.bones[bone_index]
        parent = bone.parent

        if parent is None:
            local_space_frames.append(frame)
            continue

        parent_mat = parent.matrix_local.inverted() @ bone.matrix_local
        parent_quat = parent_mat.inverted().to_quaternion()
        local_space_frame = parent_quat @ Quaternion([frame[0], frame[1], frame[2], frame[3]])
        local_space_frames.append(local_space_frame)
    return local_space_frames


def world_pos_fix(decoded_frames):
    for frame in decoded_frames:
        if frame is not None:
            frame = ([frame[2], frame[1], frame[0]])


@blender_registry.register_export_function(app_id="dmc4", extension="lmt")
def export_lmt(lmt_group, notes=None):
    """
    The LMT file as bytes. Adjustments made on the way (timing conversion, ignored F-Curves)
    are appended to notes, if given
    """
    notes = notes if notes is not None else []
    timings = {item.action.name: ExportTiming(item.action) for item in lmt_group.actions if item.action}
    _check_lmt_group(lmt_group, timings)
    dst_lmt = Lmt()
    header_size = _serialize_top_level_lmt(dst_lmt, lmt_group)
    final_size = _serialize_block(dst_lmt, lmt_group, header_size, timings, notes)
    stream = KaitaiStream(BytesIO(bytearray(final_size)))
    dst_lmt._check()
    dst_lmt._write(stream)
    return stream.to_byte_array()


class ExportTiming:
    """
    Maps action frames to game frames. The game plays at 60 fps and starts at frame 0 (frame 0
    is the tracks' reference value), so actions are shifted to start at their first keyframe and
    scaled from the scene frame rate. Keys are then written on whole game frames. The Blender
    action is never changed
    """

    def __init__(self, action):
        self.fps = get_lmt_props(action).source_fps
        self.scale = FRAMERATE / self.fps
        key_frames = [kp.co[0] for fc in action.fcurves if fc.data_path.startswith('pose.bones["')
                      for kp in fc.keyframe_points]
        # events count too: an LMT block with only constant tracks has its keys on frame 1
        # but its first events on frame 0
        props = get_lmt_props(action)
        markers = (find_event_marker(action, event, i) for i, event in enumerate(props.event_markers))
        event_frames = [marker.frame for marker in markers if marker is not None]
        # without keyframes there's nothing to line up, leave events where they are
        self.start = min(key_frames + event_frames) if key_frames else 0
        self.fractional = any(abs(f - round(f)) > 1e-4 for f in key_frames)

    @property
    def is_identity(self):
        return self.start == 0 and abs(self.scale - 1.0) < 1e-9 and not self.fractional

    def to_game(self, frame):
        return (frame - self.start) * self.scale

    def to_action(self, game_frame):
        return self.start + game_frame / self.scale

    def describe(self):
        changes = []
        if self.start != 0:
            changes.append(f"shifted {-self.start:+g} frames to start at 0")
        if abs(self.scale - 1.0) >= 1e-9:
            changes.append(f"converted from {self.fps:g} to {FRAMERATE} fps")
        if self.fractional:
            changes.append("keys between whole frames resampled")
        return ", ".join(changes)


def game_length(action):
    """Length of the action in game frames, for the Frames property"""
    timing = ExportTiming(action)
    return max(0, int(round(timing.to_game(action.frame_range[1]))))


def _event_game_frame(timing, marker):
    return int(round(timing.to_game(marker.frame)))


def _check_lmt_group(lmt_group, timings):
    """Raise AlbamCheckFailure for problems that would produce a broken or crashing export"""
    if not lmt_group.armature:
        raise AlbamCheckFailure(
            "The LMT has no armature", "", "Set the armature in the LMT panel")
    missing_actions = [str(i + 1) for i, item in enumerate(lmt_group.actions) if not item.action]
    if missing_actions:
        raise AlbamCheckFailure(
            "Some animations have no action",
            f"Animation rows: {', '.join(missing_actions)}",
            "Remove those rows from the Animations list")

    slots = {}
    for item in lmt_group.actions:
        slots.setdefault(get_lmt_props(item.action).lmt_id, []).append(item.action.name)
    clashes = [f"slot {slot}: {', '.join(names)}" for slot, names in sorted(slots.items()) if len(names) > 1]
    if clashes:
        raise AlbamCheckFailure(
            "Several animations use the same LMT slot", "; ".join(clashes),
            "Give each animation its own Slot in the Animations panel")
    out_of_range = [slot for slot in slots if not 0 <= slot < lmt_group.num_slots]
    if out_of_range:
        raise AlbamCheckFailure(
            "Animation slots are outside the LMT's slot count",
            f"Slots {sorted(out_of_range)}, slot count {lmt_group.num_slots}",
            "Raise Slots in the LMT panel, or change the animations' Slot")

    problems = []
    for item in lmt_group.actions:
        action = item.action
        props = get_lmt_props(action)
        timing = timings[action.name]
        seen = set()
        for i, event in enumerate(props.event_markers):
            marker = find_event_marker(action, event, i)
            label = event.marker_name or f"event {i + 1}"
            if marker is None:
                problems.append(f"{action.name}: {label} has no marker")
                continue
            frame = _event_game_frame(timing, marker)
            if not 0 <= frame < props.num_frames:
                problems.append(
                    f"{action.name}: {label} is on frame {marker.frame} (game frame {frame}), "
                    f"outside game frames 0-{props.num_frames - 1}")
            key = (event.param_ev_type, frame)
            if key in seen:
                problems.append(f"{action.name}: two {event.param_ev_type} events on game frame {frame}")
            seen.add(key)
    if problems:
        raise AlbamCheckFailure(
            "Some events can't be exported", "; ".join(problems),
            "Fix them in the Events panel (each event needs its marker, inside the animation, "
            "and at most one event of each type per frame)")


def _serialize_top_level_lmt(dst_lmt, lmt_group):
    dst_lmt.id_magic = bytearray('\x4c\x4d\x54\x00', encoding='utf-8')
    dst_lmt.version = 49
    dst_lmt.num_block_offsets = lmt_group.num_slots
    return lmt_group.num_slots * 4 + 8

def _serialize_block(dst_lmt, lmt_group, header_size, timings, notes):
    dst_lmt.block_offsets = []
    for i in range(dst_lmt.num_block_offsets):
        block_offset = dst_lmt.BlockOffset(_parent=dst_lmt, _root=dst_lmt._root)
        block_offset.offset = 0
        dst_lmt.block_offsets.append(block_offset)

    cml_size = header_size + len(lmt_group.actions) * 0xC0
    for i, group in enumerate(lmt_group.actions):
        action = group.action
        custom_property = get_lmt_props(action)
        timing = timings[action.name]
        if not timing.is_identity:
            notes.append(f"{action.name}: {timing.describe()}")

        block = dst_lmt.BlockHeader49(_parent=dst_lmt, _root=dst_lmt._root)
        block.num_frames = custom_property.num_frames
        block.loop_frames = custom_property.loop_frames

        active_offset = dst_lmt.block_offsets[custom_property.lmt_id]
        active_offset.offset = header_size + i * 0xC0
        active_offset.block_header = block
        block.ofs_frame = cml_size
        tracks, track_bf_size = _serialize_tracks(dst_lmt, lmt_group, action, block, cml_size, timing, notes)
        cml_size = track_bf_size
        block.tracks = tracks
        block.num_tracks = len(tracks)
        block.end_pos = dst_lmt.Vec4(_parent=block, _root=dst_lmt._root)
        block.end_pos.x = custom_property.end_pos[0]
        block.end_pos.y = custom_property.end_pos[1]
        block.end_pos.z = custom_property.end_pos[2]
        block.end_pos.w = 0
        block.end_quat = dst_lmt.Vec4(_parent=block, _root=dst_lmt._root)
        block.end_quat.x = custom_property.end_quat[0]
        block.end_quat.y = custom_property.end_quat[1]
        block.end_quat.z = custom_property.end_quat[2]
        block.end_quat.w = custom_property.end_quat[3]

        events01, events02 = _serialize_events(dst_lmt, block, action, timing)
        block.events_01 = events01
        block.events_02 = events02

        block.event_buffer_01 = cml_size
        block.num_events_01 = len(events01)
        block.events_params_01 = custom_property.events_params_01
        block.unused_ev_01 = [0] * 24
        cml_size += block.num_events_01 * 8

        block.event_buffer_02 = cml_size
        block.num_events_02 = len(events02)
        block.events_params_02 = custom_property.events_params_02
        block.unused_ev_02 = [0] * 24
        cml_size += block.num_events_02 * 8

    return cml_size


EULER_ORDERS = {'XYZ', 'XZY', 'YXZ', 'YZX', 'ZXY', 'ZYX'}
MAX_KEY_GAP = 255  # FrameQuat4_14 durations are 8 bits
ROTATION_PROPS = ('rotation_quaternion', 'rotation_euler', 'rotation_axis_angle')
TRACK_PROP_ORDER = {'rotation': 0, 'location': 1, 'scale': 2}


def _get_export_tracks(action, armature, notes):
    """
    [(bone name, property, {array_index: fcurve})], one per exported track, ordered like the
    game's files: root motion first, then bones in skeleton order, rotation > location > scale.
    Built from the F-Curves themselves, so their grouping doesn't matter. When a bone has
    curves for several rotation modes, the bone's current rotation mode picks which one
    """
    tracks = {}
    ignored = {}
    for fc in action.fcurves:
        data_path = fc.data_path
        if not data_path.startswith('pose.bones["') or not fc.keyframe_points:
            continue
        end = data_path.find('"].')
        bone_name, prop = data_path[len('pose.bones["'):end], data_path[end + 3:]
        if prop in ('location', 'scale') or prop in ROTATION_PROPS:
            tracks.setdefault((bone_name, prop), {})[fc.array_index] = fc
        else:
            ignored[prop] = ignored.get(prop, 0) + 1
    if ignored:
        notes.append(f"{action.name}: ignored F-Curves the LMT format can't store: "
                     + ", ".join(f"{prop} ({count})" for prop, count in sorted(ignored.items())))

    rotation_props = {}
    for bone_name, prop in tracks:
        if prop in ROTATION_PROPS:
            rotation_props.setdefault(bone_name, set()).add(prop)
    for bone_name, props in rotation_props.items():
        if len(props) < 2:
            continue
        pose_bone = armature.pose.bones.get(bone_name)
        mode = pose_bone.rotation_mode if pose_bone else 'QUATERNION'
        keep = ('rotation_euler' if mode in EULER_ORDERS else
                'rotation_axis_angle' if mode == 'AXIS_ANGLE' else 'rotation_quaternion')
        if keep not in props:
            keep = 'rotation_quaternion' if 'rotation_quaternion' in props else sorted(props)[0]
        for prop in props - {keep}:
            del tracks[(bone_name, prop)]

    bone_order = {bone.name: i for i, bone in enumerate(armature.data.bones)}

    def sort_key(item):
        bone_name, prop = item[0]
        kind = 'rotation' if prop in ROTATION_PROPS else prop
        return (bone_name != ROOT_MOTION_BONE_NAME, bone_order.get(bone_name, len(bone_order)), TRACK_PROP_ORDER[kind])

    return [(bone_name, prop, channels) for (bone_name, prop), channels in sorted(tracks.items(), key=sort_key)]


def _serialize_tracks(dst_lmt, lmt_group, action, block, cml_size, timing, notes):
    tracks = []
    armature = lmt_group.armature
    export_tracks = _get_export_tracks(action, armature, notes)
    cml_size += len(export_tracks) * 32
    for bone_name, action_type, channels in export_tracks:
        track = dst_lmt.Track49(_parent=block, _root=dst_lmt._root)
        track.joint_type = 0

        bone = armature.data.bones.get(bone_name)
        if bone is None:
            raise AlbamCheckFailure(
                f"Animation {action.name} animates a bone that isn't in the armature",
                f"Bone: {bone_name}, armature: {armature.name}",
                "Retarget the animation onto the LMT's armature, or set the LMT's armature to the right one")
        #Bone index
        if bone_name == ROOT_MOTION_BONE_NAME:
            track.bone_index = ROOT_MOTION_BONE_ID
        else:
            retarget_index = bone.get('mtfw.anim_retarget')
            if retarget_index is None:
                raise AlbamCheckFailure(
                    f"Bone {bone_name} has no game bone index",
                    f"Animation {action.name} animates it, but the bone has no 'mtfw.anim_retarget' property",
                    "Animate only bones that came from an imported model, or add the property to the bone")
            track.bone_index = int(retarget_index)

        #Track type
        if action_type in ROTATION_PROPS:
            # the root motion bone's rotation is absolute, like in the game's files
            track.usage = 3 if track.bone_index == ROOT_MOTION_BONE_ID else 0
            track.buffer_type = 6
            pose_bone = armature.pose.bones.get(bone_name)
            order = pose_bone.rotation_mode if pose_bone and pose_bone.rotation_mode in EULER_ORDERS else 'XYZ'
            keys = _rotation_keys(channels, action_type, order, timing)
            buffer, bf_size = _serialize_bone_rotation(dst_lmt, bone, track, keys)
        elif action_type == 'location':
            if track.bone_index == ROOT_MOTION_BONE_ID:
                track.usage = 4
            else:
                track.usage = 1
            track.buffer_type = 9
            keys = _track_keys(channels, (0.0, 0.0, 0.0), timing)
            buffer, bf_size = _serialize_bone_location(dst_lmt, bone, track, keys)
        else:
            track.usage = 2
            track.buffer_type = 9
            keys = _track_keys(channels, (1.0, 1.0, 1.0), timing)
            buffer, bf_size = _serialize_bone_scale(dst_lmt, track, keys)

        track.weight = 1.0
        track.data = buffer.to_byte_array()
        track.len_data = bf_size
        track.ofs_data = cml_size
        cml_size += bf_size
        tracks.append(track)
    return tracks, cml_size


def _serialize_events(dst_lmt, dst_action, action, timing):
    """
    Events are stored per table (Hitbox, Sound) as (value, duration) pairs that cover
    the whole animation, so a value holds until the next event. The game's files always
    start at frame 0 and have at least one event per table, so an empty table becomes
    a single zero event, and a gap before the first event is filled with a zero event
    """
    custom_prop = get_lmt_props(action)
    tables = {'Hitbox': [], 'Sound': []}
    for ind, ev in enumerate(custom_prop.event_markers):
        marker = find_event_marker(action, ev, ind)
        tables[ev.param_ev_type if ev.param_ev_type in tables else 'Hitbox'].append(
            (_event_game_frame(timing, marker), ev.encode()))

    serialized = []
    for frames_values in tables.values():
        frames_values.sort()
        if not frames_values or frames_values[0][0] > 0:
            frames_values.insert(0, (0, 0))
        events = []
        for i, (frame, value) in enumerate(frames_values):
            frame_next = frames_values[i + 1][0] if i + 1 < len(frames_values) else dst_action.num_frames
            event = dst_lmt.Event49(_parent=dst_action, _root=dst_lmt._root)
            event.group_id = value
            event.frame = max(frame_next - frame, 0)
            events.append(event)
        serialized.append(events)
    return serialized[0], serialized[1]


def _track_keys(channels, defaults, timing):
    """
    (game frame, [values]) for every game frame where any channel of the track has a keyframe,
    with every channel evaluated there. The file stores all components of a track per key, so
    channels keyed on different frames are filled in from their curves. Keyframes are mapped to
    whole game frames (see ExportTiming). Animated tracks always get a key on frame 0, where the
    game starts reading them, and gaps longer than 255 frames are split, the most a rotation
    key's 8-bit duration can hold. Channels missing from the track take their value from defaults
    """
    frames = {round(timing.to_game(kp.co[0])) for c in channels.values() for kp in c.keyframe_points}
    if len(frames) > 1:
        frames.add(0)
        ordered = sorted(frames)
        for before, after in zip(ordered, ordered[1:]):
            frames.update(range(before + MAX_KEY_GAP, after, MAX_KEY_GAP))
    return [
        (float(frame), [channels[i].evaluate(timing.to_action(frame)) if i in channels else default
                        for i, default in enumerate(defaults)])
        for frame in sorted(frames)
    ]


def _rotation_keys(channels, prop, euler_order, timing):
    """(game frame, Quaternion) for a rotation track in any of Blender's rotation modes"""
    if prop == 'rotation_euler':
        return [(frame, Euler(xyz, euler_order).to_quaternion())
                for frame, xyz in _track_keys(channels, (0.0, 0.0, 0.0), timing)]
    if prop == 'rotation_axis_angle':
        keys = []
        for frame, (angle, x, y, z) in _track_keys(channels, (0.0, 0.0, 1.0, 0.0), timing):
            axis = Vector((x, y, z))
            keys.append((frame, Quaternion(axis.normalized(), angle) if axis.length > 1e-9 else Quaternion()))
        return keys
    return _quaternion_keys(channels, timing)


def _quaternion_keys(channels, timing):
    """
    (game frame, Quaternion) for a rotation_quaternion track. Between keyframes, Blender
    interpolates each component on its own, which goes wrong when neighbouring keys are in
    opposite hemispheres (q and -q, same rotation; imported animations have these). So keys
    are evaluated where they are and slerped in between
    """
    defaults = (1.0, 0.0, 0.0, 0.0)

    def at(frame):
        return Quaternion([channels[i].evaluate(frame) if i in channels else defaults[i] for i in range(4)])

    key_times = sorted({kp.co[0] for c in channels.values() for kp in c.keyframe_points})
    keys = []
    for game_frame, _ in _track_keys(channels, defaults, timing):
        t = timing.to_action(game_frame)
        after = next((i for i, kt in enumerate(key_times) if kt >= t - 1e-6), len(key_times))
        if after == len(key_times) or after == 0 or abs(key_times[after] - t) < 1e-6:
            keys.append((game_frame, at(t)))
            continue
        before_time, after_time = key_times[after - 1], key_times[after]
        q0, q1 = at(before_time).normalized(), at(after_time).normalized()
        if q0.dot(q1) < 0.0:
            q1.negate()
        keys.append((game_frame, q0.slerp(q1, (t - before_time) / (after_time - before_time))))
    return keys


def _normalized_rotation(quat):
    """
    Unit quaternion with w >= 0. Rotation tracks store only x, y, z and the game rebuilds
    w = sqrt(1 - x^2 - y^2 - z^2), so a non unit or negative w quaternion comes out wrong.
    Keyed quaternions in Blender aren't kept normalized
    """
    quat = quat.normalized()
    if quat.w < 0.0:
        quat.negate()
    return quat


def _key_durations(keys):
    """
    Duration per key, as the game reads them: frames to the next key, 0 on the last key
    (which holds). See decode_type_6
    """
    return [int(keys[k + 1][0] - keys[k][0]) for k in range(len(keys) - 1)] + [0]


def _serialize_bone_rotation(dst_lmt, bone, track, keys):
    parent_quat = None
    if bone.parent:
        parent_mat = bone.parent.matrix_local.inverted() @ bone.matrix_local
        parent_quat = parent_mat.to_quaternion() #convert back to bone space

    # to the game's space, which is what the file stores (keys and ref_data alike)
    keys = [(frame, _normalized_rotation(parent_quat @ quat if parent_quat is not None else quat))
            for frame, quat in keys]
    kf_num = len(keys)
    track.ref_data = dst_lmt.Vec4(_parent=track, _root=dst_lmt._root)
    first = keys[0][1]
    track.ref_data.x = first.x
    track.ref_data.y = first.y
    track.ref_data.z = first.z
    track.ref_data.w = first.w
    if kf_num == 1:
        # constant rotation: quaternion x, y, z, w is implied
        buffer = KaitaiStream(BytesIO(bytearray(12)))
        track.buffer_type = 4
        buffer.write_bytes(struct.pack('fff', first.x, first.y, first.z))
        return buffer, 12

    buffer = KaitaiStream(BytesIO(bytearray(kf_num * 8)))
    for (frame, rot), duration in zip(keys, _key_durations(keys)):
        frame_quat = FrameQuat4_14()
        frame_quat.from_quat([rot.w, rot.x, rot.y, rot.z], duration)
        buffer.write_bytes(bytes(frame_quat))
    return buffer, (kf_num * 8)


def _serialize_bone_location(dst_lmt, bone, track, keys):
    kf_num = len(keys)
    track.ref_data = dst_lmt.Vec4(_parent=track, _root=dst_lmt._root)
    parent_space = None
    if bone.parent:
        parent_space = bone.parent.matrix_local.inverted() @ bone.matrix_local

    if kf_num == 1:
        buffer = KaitaiStream(BytesIO(bytearray(12)))
        track.buffer_type = 2
        x, y, z = keys[0][1]

        if parent_space is not None:
            parent_space_frame = (parent_space @ Matrix.Translation([x, y, z])).to_translation()
            x, y, z = parent_space_frame.x, parent_space_frame.y, parent_space_frame.z
            written = (x, y, z)
        elif track.bone_index == ROOT_MOTION_BONE_ID:
            written = (x, y, z)
        else:
            written = (x, z, -y)
        track.ref_data.x = x * 100.0
        track.ref_data.y = y * 100.0
        track.ref_data.z = z * 100.0
        track.ref_data.w = 1.0
        buffer.write_bytes(struct.pack('fff', *(v * 100.0 for v in written)))
        return buffer, 12

    buffer = KaitaiStream(BytesIO(bytearray(kf_num * 16)))
    for k, ((frame, (x, y, z)), duration) in enumerate(zip(keys, _key_durations(keys))):
        if parent_space is not None:
            parent_space_frame = (parent_space @ Matrix.Translation([x, y, z])).to_translation()
            x, y, z = parent_space_frame.x, parent_space_frame.y, parent_space_frame.z
        if k == 0:
            track.ref_data.x = x * 100.0
            track.ref_data.y = y * 100.0
            track.ref_data.z = z * 100.0
            track.ref_data.w = 1.0
        buffer.write_bytes(struct.pack('fffI', x * 100.0, y * 100.0, z * 100.0, duration))
    return buffer, (kf_num * 16)


def _serialize_bone_scale(dst_lmt, track, keys):
    kf_num = len(keys)
    track.ref_data = dst_lmt.Vec4(_parent=track, _root=dst_lmt._root)
    x, y, z = keys[0][1]
    track.ref_data.x = x
    track.ref_data.y = y
    track.ref_data.z = z
    track.ref_data.w = 1.0
    if kf_num == 1:
        buffer = KaitaiStream(BytesIO(bytearray(12)))
        track.buffer_type = 2
        buffer.write_bytes(struct.pack('fff', x, y, z))
        return buffer, 12

    buffer = KaitaiStream(BytesIO(bytearray(kf_num * 16)))
    for (frame, (x, y, z)), duration in zip(keys, _key_durations(keys)):
        buffer.write_bytes(struct.pack('fffI', x, y, z, duration))
    return buffer, (kf_num * 16)


def filter_armatures(self, obj):
    # TODO: filter by custom properties that indicate is
    # a RE5 compatible armature
    return obj.type == 'ARMATURE'


# Named flags of an event value: first bit and bit count. Some flags share bits
# (e.g. dante_yamato_display and stand_fade_efx), they're kept as found in the game's files.
# Bits 0-7 are the slot toggles
GroupHash = {
    'dante_yamato_display': 0xA,
    'stand_fade_efx': 0xA,
    'ex_speedup': 0xB,
    'stand_fade': 0xB,
    'stand_flicker': 0xC,
    'stand_transp': 0xD,
    'right_foot_ik': 0x18,
    'left_foot_ik': 0x19,
    'gun_display': 0x1A,
    'main_sword_display': 0x1B,
    'face_swap': 0x1D,
    'stand_sword_disp': 0x1E,
    'sword_trail': 0x1F
}

GroupBitNum = {
    'dante_yamato_display': 2,
    'stand_fade_efx': 1,
    'ex_speedup': 1,
    'stand_fade': 1,
    'stand_flicker': 1,
    'stand_transp': 2,
    'right_foot_ik': 1,
    'left_foot_ik': 1,
    'gun_display': 1,
    'main_sword_display': 2,
    'face_swap': 3,
    'stand_sword_disp': 1,
    'sword_trail': 1
}

EVENT_SLOT_COUNT = 8
EVENT_KNOWN_BITS = (1 << EVENT_SLOT_COUNT) - 1
for _name, _bit in GroupHash.items():
    EVENT_KNOWN_BITS |= ((1 << GroupBitNum[_name]) - 1) << _bit

EVENT_TYPES = [
    ('Hitbox', 'Hitbox', 'Event of the first event table (hitboxes)', 'MESH_CUBE', 0),
    ('Sound', 'Sound', 'Event of the second event table (sounds)', 'SPEAKER', 1),
]


def _flag_property(name):
    bit, count = GroupHash[name], GroupBitNum[name]
    bits = f"bit {bit}" if count == 1 else f"bits {bit}-{bit + count - 1}"
    return bpy.props.IntProperty(description=f"Event flag, {bits} of the event value", min=0, max=(1 << count) - 1)


def _get_event_type(self):
    return 1 if self.param_ev_type == 'Sound' else 0


def _set_event_type(self, value):
    self.param_ev_type = EVENT_TYPES[value][0]


@blender_registry.register_blender_prop
class DMC4EventGroup(bpy.types.PropertyGroup):
    """
    An LMT event. Its frame is the frame of the action's pose marker named marker_name.
    Events from .blend files saved before marker_name existed are paired with markers by position
    """
    marker_name: bpy.props.StringProperty(name="Marker")
    main_sword_display: _flag_property('main_sword_display')
    dante_yamato_display: _flag_property('dante_yamato_display')
    stand_fade_efx: _flag_property('stand_fade_efx')
    ex_speedup: _flag_property('ex_speedup')
    stand_fade: _flag_property('stand_fade')
    stand_flicker: _flag_property('stand_flicker')
    stand_transp: _flag_property('stand_transp')
    right_foot_ik: _flag_property('right_foot_ik')
    left_foot_ik: _flag_property('left_foot_ik')
    gun_display: _flag_property('gun_display')
    face_swap: _flag_property('face_swap')
    stand_sword_disp: _flag_property('stand_sword_disp')
    sword_trail: _flag_property('sword_trail')
    extra_bits: bpy.props.IntProperty(
        name="Other Bits",
        description="Bits of the event value that aren't slots or named flags, kept as imported",
        min=0,
    )
    slots: bpy.props.BoolVectorProperty(name='Toggles', size=EVENT_SLOT_COUNT)
    param_ev_type: bpy.props.StringProperty()  # 'Hitbox' or 'Sound'
    ev_type: bpy.props.EnumProperty(name="Type", items=EVENT_TYPES, get=_get_event_type, set=_set_event_type)

    def setup(self, ev_type, value):
        for k, v in GroupHash.items():
            setattr(self, k, (value >> v) & ((1 << GroupBitNum[k]) - 1))
        for i in range(EVENT_SLOT_COUNT):
            self.slots[i] = bool((value >> i) & 1)
        self.extra_bits = value & ~EVENT_KNOWN_BITS
        self.param_ev_type = ev_type

    def encode(self):
        """The event value written to the LMT file"""
        value = self.extra_bits & ~EVENT_KNOWN_BITS
        for k, v in GroupHash.items():
            value |= (getattr(self, k) & ((1 << GroupBitNum[k]) - 1)) << v
        for i in range(EVENT_SLOT_COUNT):
            value |= int(self.slots[i]) << i
        return value


def _on_active_event_changed(self, context):
    """Select the event's marker and move the playhead to it"""
    action = self.id_data
    if not isinstance(action, bpy.types.Action):
        return
    try:
        event = self.event_markers[self.active_event_index]
    except IndexError:
        return
    marker = find_event_marker(action, event, self.active_event_index)
    if marker is None:
        return
    for m in action.pose_markers:
        m.select = m == marker
    context.scene.frame_current = marker.frame


@blender_registry.register_custom_properties_action("lmt_49", ("re5", "dmc4"))
@blender_registry.register_blender_prop
class Lmt49ActionCustomProperties(bpy.types.PropertyGroup):
    lmt_id: bpy.props.IntProperty(name='Slot', description="Index of this animation in the LMT file", default=0, min=0)
    num_frames: bpy.props.IntProperty(name='Frames', description="Length of the animation", min=0)
    loop_frames: bpy.props.IntProperty(
        name='Loop Start',
        description="Frame the animation loops back to. -1 means it doesn't loop",
        default=-1,
        min=-1,
    )
    source_fps: bpy.props.FloatProperty(
        name="Frame Rate",
        description="Frame rate the action was made at. The game plays at 60 fps, export converts. "
                    "Frames and Loop Start are in game frames",
        default=FRAMERATE,
        min=1.0,
    )
    end_pos: bpy.props.FloatVectorProperty(name='End Position', size=3)
    end_quat: bpy.props.FloatVectorProperty(name='End Rotation', size=4)
    events_params_01: bpy.props.IntVectorProperty(name="Hitbox Slot Values", size=EVENT_SLOT_COUNT, min=0, max=0xFFFF)
    events_params_02: bpy.props.IntVectorProperty(name="Sound Slot Values", size=EVENT_SLOT_COUNT, min=0, max=0xFFFF)
    event_markers: bpy.props.CollectionProperty(type=DMC4EventGroup)
    active_event_index: bpy.props.IntProperty(update=_on_active_event_changed)

    def copy_from_lmt(self, lmt_act, index):
        self.lmt_id = index
        self.num_frames = lmt_act.num_frames
        self.loop_frames = lmt_act.loop_frames
        self.end_pos[0] = lmt_act.end_pos.x
        self.end_pos[1] = lmt_act.end_pos.y
        self.end_pos[2] = lmt_act.end_pos.z
        self.end_quat[0] = lmt_act.end_quat.x
        self.end_quat[1] = lmt_act.end_quat.y
        self.end_quat[2] = lmt_act.end_quat.z
        self.end_quat[3] = lmt_act.end_quat.w
        self.events_params_01 = lmt_act.events_params_01
        self.events_params_02 = lmt_act.events_params_02


@blender_registry.register_blender_prop
class Lmt49Action(bpy.types.PropertyGroup):
    """An animation of an LMT file. Its LMT data lives in the action's custom properties"""
    action: bpy.props.PointerProperty(type=bpy.types.Action)
    name: bpy.props.StringProperty(name='Action', default='')


def _on_active_anim_changed(self, context):
    """Play the selected animation on the LMT's armature"""
    try:
        action = self.actions[self.active_id].action
    except IndexError:
        return
    if action is None:
        return
    link_legacy_events(action)
    if self.armature:
        self.armature.animation_data_create()
        self.armature.animation_data.action = action


@blender_registry.register_blender_prop
class AlbamActionGroup(bpy.types.PropertyGroup):
    """An LMT file: its animations, slot count and armature"""
    actions: bpy.props.CollectionProperty(type=Lmt49Action)
    active_id: bpy.props.IntProperty(name="Active Animation", update=_on_active_anim_changed)
    num_slots: bpy.props.IntProperty(name="Slots", description="Number of animation slots in the LMT file", min=0)
    armature: bpy.props.PointerProperty(
        type=bpy.types.Object,
        poll=filter_armatures,
        name="Armature",
        description="Armature the animations play on",
    )
    export_path: bpy.props.StringProperty(subtype="FILE_PATH")

    def add(self, action):
        item = self.actions.add()
        item.name = action.name
        item.action = action
        return item

    def slot_counts(self):
        counts = {}
        for item in self.actions:
            if item.action:
                slot = get_lmt_props(item.action).lmt_id
                counts[slot] = counts.get(slot, 0) + 1
        return counts

    def free_slot(self):
        used = self.slot_counts()
        return next(i for i in range(len(used) + 1) if i not in used)


@blender_registry.register_blender_prop_albam(name="lmt_groups")
class AlbamLmtGroups(bpy.types.PropertyGroup):
    """The LMT files in the scene"""
    anim_group: bpy.props.CollectionProperty(type=AlbamActionGroup)
    active_group_id: bpy.props.IntProperty()

    def add(self, name=''):
        group = self.anim_group.add()
        group.name = name
        return group


def get_lmt_props(action):
    return action.albam_custom_properties.get_custom_properties_for_appid("dmc4")


def get_active_lmt(context):
    groups = context.scene.albam.lmt_groups
    try:
        return groups.anim_group[groups.active_group_id]
    except IndexError:
        return None


def get_active_anim(context):
    """The active LMT's selected animation list item, or None"""
    lmt = get_active_lmt(context)
    if lmt is None:
        return None
    try:
        return lmt.actions[lmt.active_id]
    except IndexError:
        return None


def get_active_event(context):
    """(action, event, marker) of the selected event of the selected animation, or None"""
    anim = get_active_anim(context)
    if anim is None or anim.action is None:
        return None
    props = get_lmt_props(anim.action)
    try:
        event = props.event_markers[props.active_event_index]
    except IndexError:
        return None
    return anim.action, event, find_event_marker(anim.action, event, props.active_event_index)


def find_event_marker(action, event, index):
    if event.marker_name:
        return action.pose_markers.get(event.marker_name)
    # events from .blend files saved before marker_name existed are paired by position
    if index < len(action.pose_markers):
        return action.pose_markers[index]
    return None


def link_legacy_events(action):
    """Store the marker name in events that are still paired with markers by position"""
    props = get_lmt_props(action)
    if all(event.marker_name for event in props.event_markers):
        return
    taken = {event.marker_name for event in props.event_markers if event.marker_name}
    for i, event in enumerate(props.event_markers):
        if event.marker_name:
            continue
        marker = find_event_marker(action, event, i)
        if marker is None:
            continue
        if marker.name in taken:
            marker.name = unique_marker_name(action, marker.name)
        event.marker_name = marker.name
        taken.add(marker.name)


def unique_marker_name(action, base):
    names = {m.name for m in action.pose_markers}
    name = base
    n = 2
    while name in names:
        name = f"{base}.{n:03d}"
        n += 1
    return name


def _import_events(action, custom_property, events, ev_type):
    """Events are stored as (value, duration) pairs, the first starting at frame 0"""
    prefix = "ev1" if ev_type == "Hitbox" else "ev2"
    frame = 0
    for event in events:
        marker = action.pose_markers.new(unique_marker_name(action, f"{prefix}_{frame}_{event.group_id}"))
        marker.frame = frame
        event_prop = custom_property.event_markers.add()
        event_prop.setup(ev_type, event.group_id)
        event_prop.marker_name = marker.name
        frame += event.frame


@blender_registry.register_blender_prop_albam(name='import_options_lmt')
class ImportOptionsLMT(bpy.types.PropertyGroup):
    armature: bpy.props.PointerProperty(type=bpy.types.Object, poll=filter_armatures)
    renamed_bone_flag: bpy.props.BoolProperty(name = 'Renamed bones',
                                              description='Check this box when bones are auto-renamed so import works properly')


@blender_registry.register_import_options_custom_draw_func(extension='lmt')
def draw_lmt_options(panel_instance, context):
    panel_instance.bl_label = "LMT Options"
    panel_instance.layout.prop(context.scene.albam.import_options_lmt, 'armature')
    panel_instance.layout.prop(context.scene.albam.import_options_lmt, 'renamed_bone_flag')


@blender_registry.register_import_options_custom_poll_func(extension='lmt')
def poll_lmt_options(panel_instance, context):
    return True


@blender_registry.register_import_operator_poll_func(extension='lmt')
def poll_import_operator_for_lmt(panel_class, context):
    return bool(context.scene.albam.import_options_lmt.armature)

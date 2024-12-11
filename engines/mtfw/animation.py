from ctypes import Structure, c_ulonglong, c_double, c_uint64, c_uint8
from enum import Enum

import ctypes
import io
import struct
import numpy as np
import bpy
from kaitaistruct import KaitaiStream
from mathutils import Matrix, Vector, Quaternion
import mathutils
import numpy as np

from albam.registry import blender_registry
from .structs.lmt import Lmt

class BufferType(Enum):
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
HACKY_BONE_INDEX_IK_FOOT_LEFT = 20
IK_HIPS = 0
HACKY_BONE_INDICES_IK_FOOT = {HACKY_BONE_INDEX_IK_FOOT_RIGHT, HACKY_BONE_INDEX_IK_FOOT_LEFT}
ROOT_UNK_BONE_ID = 254
ROOT_MOTION_BONE_ID = 255
ROOT_MOTION_BONE_NAME = 'root_motion'
ROOT_BONE_NAME = '0'
FRAMERATE = 60.0

@blender_registry.register_import_function(app_id="re5", extension='lmt', file_category="ANIMATION")
@blender_registry.register_import_function(app_id="dmc4", extension='lmt', file_category="ANIMATION")
def load_lmt(file_item, context):
    lmt_bytes = file_item.get_bytes()
    lmt = Lmt(KaitaiStream(io.BytesIO(lmt_bytes)))
    armature = context.scene.albam.import_options_lmt.armature
    mapping = _create_bone_mapping(armature)

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
        action.use_fake_user = True
        context.scene.albam.import_options_lmt.armature.animation_data.action = action
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
                decoded_frames = decode_type_6(track.data)
                decoded_frames = _parent_space_to_local_rot(decoded_frames, armature, bone_index)

            elif track.buffer_type == 4:
                # TRACK_MODE = "rotation_euler"
                # decoded_frames = decode_type_4_euler(track.data)
                # world_pos_fix(decoded_frames)

                TRACK_MODE = "rotation_quaternion"
                decoded_frames = decode_type_4(track.data)
                decoded_frames = _parent_space_to_local_rot(decoded_frames, armature, bone_index)

            elif track.buffer_type == 2:
                print(f'Buffer type 2 track type {track.usage}')
                if track.usage == 1:
                    TRACK_MODE = 'location'
                    decoded_frames = decode_type_2(track.data)
                    decoded_frames = _parent_space_to_local(decoded_frames, armature, bone_index)
                elif track.usage == 2:
                    TRACK_MODE = 'scale'
                    decoded_frames = decode_type_2_scale(track.data)
                    world_pos_fix(decoded_frames)
                    #_parent_space_to_local(decoded_frames, armature, bone_index)
                elif track.usage == 4:
                    TRACK_MODE = 'location'
                    decoded_frames = decode_type_2(track.data)
                    world_pos_fix(decoded_frames)
                else:
                    continue

            elif track.buffer_type == 9:
                #decoded_frames = decode_type_9(track.data, block.block_header.num_frames)
                print(f'Buffer type 9 track type {track.usage}')
                if track.usage == 1:
                    TRACK_MODE = 'location'
                    decoded_frames = decode_type_9(track.data)
                    #decoded_frames = decode_type_9(track.data, block.block_header.num_frames)
                    decoded_frames = _parent_space_to_local(decoded_frames, armature, bone_index)
                elif track.usage == 2:
                    TRACK_MODE = 'scale'
                    decoded_frames = decode_type_9_scale(track.data)
                    world_pos_fix(decoded_frames)
                    #_parent_space_to_local(decoded_frames, armature, bone_index)
                elif track.usage == 4:
                    TRACK_MODE = 'location'
                    #decoded_frames = decode_type_9(track.data)
                    decoded_frames = decode_type_9(track.data)
                    world_pos_fix(decoded_frames)
                else:
                    continue
                #decoded_frames = _parent_space_to_local(decoded_frames, armature, bone_index)

            else:
                # TODO: print statistics of missing tracks
                # print("Unknown buffer_type, skipping", track.buffer_type)
                continue

            group_name = str(bone_index)
            group = action.groups.get(group_name) or action.groups.new(group_name)
            data_path = f"pose.bones[\"{bone_index}\"].{TRACK_MODE}"
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
                    curves.append(action.fcurves.new(data_path=data_path, index=i, action_group=group_name))
            # for c in curves:
            #     c.group = group
                except KeyError as err:
                    print('unknown error:', err)
                    curves.append(action.fcurves.new(data_path=data_path+'[1]', index=i, action_group=group_name))

            for frame_index, frame_data in enumerate(decoded_frames):
                if frame_data is None:
                    continue
                for curve_idx, curve in enumerate(curves):
                    curve.keyframe_points.add(1)
                    curve.keyframe_points[-1].co = (frame_index + 1, frame_data[curve_idx])
                    curve.keyframe_points[-1].interpolation = 'CUBIC'


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


# def decode_type_9(data, num_frames):
#     decoded_frames = []
#     CHUNK_SIZE = 16
#     frame_count = 0
#     remaining_frames = num_frames
#     for start in range(0, len(data) - CHUNK_SIZE, CHUNK_SIZE):
#         chunk1 = data[start: start + CHUNK_SIZE]
#         chunk2 = data[start + CHUNK_SIZE: start + CHUNK_SIZE*2]
#         u1 = struct.unpack("fffI", chunk1)
#         floats1 = u1[:3]
#         duration = u1[3]

#         u2 = struct.unpack("fffI", chunk1)
#         floats2 = u2[:3]

#         keyframes = []
#         for i in range(duration-1):
#             x = (floats2[0] - floats1[0]) * (frame_count + i - remaining_frames) + floats1[0]
#             y = (floats2[1] - floats1[1]) * (frame_count + i - remaining_frames) + floats1[1]
#             z = (floats2[2] - floats1[2]) * (frame_count + i - remaining_frames) + floats1[2]
#             keyframes.append([x / 1000.0, y / 1000.0, z / 1000.0])

#         #floats = (u[0] / 100, u[1] / 100, u[2] / 100)
#         #
#         # decoded_frames.append(floats)
#         # decoded_frames.extend([None] * (duration - 1))

#         decoded_frames.extend(keyframes)

#         frame_count += duration
#         remaining_frames -= duration

#     return decoded_frames

def decode_type_9(data):
    decoded_frames = []
    CHUNK_SIZE = 16

    for start in range(0, len(data), CHUNK_SIZE):
        chunk = data[start: start + CHUNK_SIZE]
        u = struct.unpack("fffI", chunk)
        floats = (u[0] / 100, u[1] / 100, u[2] / 100)
        duration = u[3]
        decoded_frames.append(floats)
        decoded_frames.extend([None] * (duration - 1))
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
        decoded_frames.extend([None] * (duration - 1))
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
        #floats = list(quat_fix(mathutils.Quaternion([w, u[0], u[1], u[2]])))
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
    decoded_frames = []

    for idx, start in enumerate(range(0, len(data), 8)):
        chunk = data[start: start + 8]
        frame = FrameQuat4_14()
        io.BytesIO(chunk).readinto(frame)
        frame.calc_components()

        #decoded_frames.append(list(quat_fix(mathutils.Quaternion([frame.w, frame.x, frame.y, frame.z]))))
        decoded_frames.append((frame.w, frame.x, frame.y, frame.z))
        decoded_frames.extend([None] * frame.duration)

    return decoded_frames

def quat_fix(quat):
    mat_l2r = mathutils.Matrix([[1.0, 0.0, 0.0],
                                [0.0, 0.0, 1.0],
                                [0.0, -1.0, 0.0]])
    mat_r2l = mat_l2r.inverted()

    #m_rot = mat_l2r @ Vector((quat.x, quat.y, quat.z, quat.w)) @ mat_l2r
    m_rot = (mat_l2r @ quat.to_matrix()).to_quaternion()
    return m_rot
    #return Quaternion((-quat.w, quat.x, quat.y, quat.z))



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

    pose_bone = armature.pose.bones[ROOT_BONE_NAME]
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

        else:
            parent_space = Matrix([[1.0, 0.0, 0.0, 0.0],
                                    [0.0, 0.0, 1.0, 0.0],
                                    [0.0, -1.0, 0.0, 0.0],
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

# def _parent_space_to_local(decoded_frames, armature, bone_index):
# # XXX Temp hack
#     local_space_frames = []
#     for frame in decoded_frames:
#         if frame is None:
#             local_space_frames.append(None)
#             continue
#         bone = armature.data.bones[bone_index]
#         v = armature.matrix_world
#         v = (v[0], v[2], -v[1])
#         parent_space = Matrix.Identity(4).inverted() @ Matrix.Translation(v)
#         transform_mat = Matrix.Translation([frame[0], frame[2],-frame[1]])
#         translation = bone
#         local_space_frame = (bone.convert).to_translation()
#         local_space_frames.append(local_space_frame)
#         return local_space_frames

def slerp(start: Quaternion, end: Quaternion, delta):
    end_copy = end.copy()
    dot = start.dot(end_copy)

    if dot < 0.0:
        end_copy *= -1.0
        dot *= -1.0

    DOT_THRESHOLD = 0.9995

    if (dot > DOT_THRESHOLD):
        return (start + (end_copy - start) * delta).normalized()

    theta00 = np.acos(dot)
    theta01 = theta00 * t
    theta02 = np.sin(theta01)
    theta03 = 1.0 / np.sin(theta00)
    s0 = np.cos(theta01) - dot * theta02 * theta03
    s1 = theta02 * theta03

    return ((start * s0) + (end_copy * s1)).normalized() 

def slerp_eval(track, block, frame_data, time):
    frameDelta = time* FRAMERATE
    frame = int(frameDelta)
    num_frames = block.block_header.num_frames

    def ref_to_quat(ref_data):
        return Quaternion.Fill(ref_data.w, ref_data.x, ref_data.y, ref_data.z)

    if not num_frames:
        return ref_to_quat(track.ref_data)
    
    if track.loop_frame < 1:
        if not frame:
            if frameDelta < 0.0001:
                return ref_to_quat(track.ref_data)
            else:
                frameDelta -= 1.0
                ref_quat = ref_to_quat(track.ref_data)
                quat_data = Quaternion(*frame_data[0])
                return ref_data + (quat_data - ref_data) * frameDelta
        else:
            frame -= 1
            frameDelta -= 1.0    

def filter_armatures(self, obj):
    # TODO: filter by custom properties that indicate is
    # a RE5 compatible armature
    return obj.type == 'ARMATURE'

@blender_registry.register_blender_prop_albam(name='import_options_lmt')
class ImportOptionsLMT(bpy.types.PropertyGroup):
    armature: bpy.props.PointerProperty(type=bpy.types.Object, poll=filter_armatures)


@blender_registry.register_import_options_custom_draw_func(extension='lmt')
def draw_lmt_options(panel_instance, context):
    panel_instance.bl_label = "LMT Options"
    panel_instance.layout.prop(context.scene.albam.import_options_lmt, 'armature')


@blender_registry.register_import_options_custom_poll_func(extension='lmt')
def poll_lmt_options(panel_instance, context):
    return True


@blender_registry.register_import_operator_poll_func(extension='lmt')
def poll_import_operator_for_lmt(panel_class, context):
    return bool(context.scene.albam.import_options_lmt.armature)

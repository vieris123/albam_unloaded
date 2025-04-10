from ctypes import Structure, Union, c_ulonglong, c_double, c_uint64, c_uint8
from enum import Enum

import ctypes
import io
import struct
import numpy as np
import bpy
from kaitaistruct import KaitaiStream
from mathutils import Matrix, Vector, Quaternion
from io import BytesIO
import mathutils
import numpy as np

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

class AlbamAction(bpy.types.Action):
    pass

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
        action_group = lmt_group.add(name)
        action_group.action = action

        action_group.frames = block.block_header.num_frames
        action.frame_end = action_group.frames
        action_group.lmt_id = block_index
        
        action_group.loop_frames = int(block.block_header.loop_frames)


        action.albam_asset.app_id = app_id
        action.albam_asset.lmt_index = block_index
        custom_property = action.albam_custom_properties.get_custom_properties_for_appid(app_id)
        #custom_property.copy_custom_properties_from(block.block_header)
        custom_property.copy_from_lmt(block.block_header, block_index)
        #custom_property.copy_custom_properties_to(action)

        #Events
        cumulative_frames = 0
        action_group.coll_ev = block.block_header.events_params_01
        for event in block.block_header.events_01:
            event_prop = custom_property.event_markers.add()
            marker = action.pose_markers.new(f'ev1_{cumulative_frames}_{event.group_id}')
            marker.frame = cumulative_frames
            event_prop.setup('Hitbox', event.group_id)
            event_prop.action = action_group
            event.name = marker.name
            cumulative_frames += event.frame

        cumulative_frames = 0
        action_group.sfx_ev = block.block_header.events_params_01
        for event in block.block_header.events_02:
            event_prop = custom_property.event_markers.add()
            marker = action.pose_markers.new(f'ev2_{cumulative_frames}_{event.group_id}')
            marker.frame = cumulative_frames
            event_prop.setup('Sound', event.group_id)
            event_prop.action = action_group
            event.name = marker.name
            cumulative_frames += event.frame

        #Loops
        is_cyclic = False
        if block.block_header.loop_frames > 0:
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
                if block.block_header.loop_frames > 0 and len(decoded_frames) > block.block_header.loop_frames:
                    ref_frame = _parent_space_to_local_rot([Quaternion([track.ref_data.w, track.ref_data.x,
                                                                track.ref_data.y, track.ref_data.z])],
                                                                armature, bone_index)[0]
                    decoded_frames[block.block_header.loop_frames - 1] = ref_frame
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
                    if block.block_header.loop_frames > 0 and len(decoded_frames) > block.block_header.loop_frames:
                        ref_frame = _parent_space_to_local([Vector([track.ref_data.x / 100.0, track.ref_data.y / 100.0,
                                                                     track.ref_data.z / 100.0])],
                                                            armature, bone_index)[0]
                        decoded_frames[block.block_header.loop_frames - 1] = ref_frame
                elif track.usage == 2:
                    TRACK_MODE = 'scale'
                    action_type = 'scale'
                    decoded_frames = decode_type_9_scale(track.data)
                    world_pos_fix(decoded_frames)
                    if block.block_header.loop_frames > 0 and len(decoded_frames) > block.block_header.loop_frames:
                        ref_frame = [Vector([track.ref_data.x, track.ref_data.y, track.ref_data.z])]
                        world_pos_fix(ref_frame)
                        decoded_frames[block.block_header.loop_frames - 1] = ref_frame[0]
                elif track.usage == 4:
                    TRACK_MODE = 'location'
                    action_type = 'location'
                    decoded_frames = decode_type_9(track.data)
                    world_pos_fix(decoded_frames)
                    if block.block_header.loop_frames > 0 and len(decoded_frames) > block.block_header.loop_frames:
                        ref_frame = [Vector([track.ref_data.x / 100.0, track.ref_data.y / 100.0, track.ref_data.z / 100.0])]
                        world_pos_fix(ref_frame)
                        decoded_frames[block.block_header.loop_frames - 1] = ref_frame[0]
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

    def from_quat(self, quat, duration):
        if quat[1] < 0.0:
            quat[1] *= -1.0
            self._x_sign = 1

        if quat[2] < 0.0:
            quat[2] *= -1.0
            self._y_sign = 1

        if quat[3] < 0.0:
            quat[3] *= -1.0
            self._z_sign = 1
            
        if quat[0] < 0.0:
            quat = [x * -1.0 for x in quat]

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
        decoded_frames.extend([None] * (duration))
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
        decoded_frames.extend([None] * (duration))
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
    decoded_frames = []

    for idx, start in enumerate(range(0, len(data), 8)):
        chunk = data[start: start + 8]
        frame = FrameQuat4_14()
        io.BytesIO(chunk).readinto(frame)
        frame.calc_components()

        decoded_frames.append((frame.w, frame.x, frame.y, frame.z))
        decoded_frames.extend([None] * frame.duration)

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

@blender_registry.register_export_function(app_id="dmc4", extension="lmt")
def export_lmt(lmt_group):
    export_settings = bpy.context.scene.albam.export_settings
    # asset = bl_obj.albam_asset
    # app_id = asset.app_id
    # Mod = APPID_CLASS_MAPPER[app_id]
    #vfiles = []

    dst_lmt = Lmt()
    header_size = _serialize_top_level_lmt(dst_lmt, lmt_group)
    final_size = _serialize_block(dst_lmt, lmt_group, header_size)
    #final_size = header_size + block_size
    stream = KaitaiStream(BytesIO(bytearray(final_size)))
    dst_lmt._check()
    dst_lmt._write(stream)
    return stream.to_byte_array()

def _serialize_top_level_lmt(dst_lmt, lmt_group):
    dst_lmt.id_magic = bytearray('\x4c\x4d\x54\x00', encoding='utf-8')
    dst_lmt.version = 49
    dst_lmt.num_block_offsets = lmt_group.num_slots
    return lmt_group.num_slots * 4 + 8 

def _serialize_block(dst_lmt, lmt_group, header_size):
    dst_lmt.block_offsets = []
    for i in range(dst_lmt.num_block_offsets):
        block_offset = dst_lmt.BlockOffset(_parent=dst_lmt, _root=dst_lmt._root)
        block_offset.offset = 0
        dst_lmt.block_offsets.append(block_offset)
    
    cml_size = header_size + len(lmt_group.actions) * 0xC0
    for i, group in enumerate(lmt_group.actions):
        action = group.action
        custom_property = action.albam_custom_properties.get_custom_properties_for_appid('dmc4')

        block = dst_lmt.BlockHeader49(_parent=dst_lmt, _root=dst_lmt._root)
        block.num_frames = custom_property.num_frames
        block.loop_frames = custom_property.loop_frames

        active_offset = dst_lmt.block_offsets[custom_property.lmt_id]
        active_offset.offset = header_size + i * 0xC0
        active_offset.block_header = block
        block.ofs_frame = cml_size
        tracks, track_bf_size = _serialize_tracks(dst_lmt, lmt_group, action, block, cml_size)
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

        events01, events02 = _serialize_events(dst_lmt, block, action)
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

def _serialize_tracks(dst_lmt, lmt_group, action, block, cml_size):
    tracks = []
    armature = lmt_group.armature
    cml_size += len(action.groups) * 32
    for curve_group in action.groups:
        track = dst_lmt.Track49(_parent=block, _root=dst_lmt._root)
        name = curve_group.name
        #retarget_index, index, action_type = name.split('.')
        track.joint_type = 0

        data_path = curve_group.channels[0].data_path
        bone_name = data_path[data_path.find('[\"')+2:data_path.find('\"]')]
        bone = armature.data.bones[bone_name]
        retarget_index = bone.get('mtfw.anim_retarget')
        action_type = data_path.split('.')[-1]
        #Bone index
        if bone_name == 'root_motion':
            track.bone_index = 255
        else:
            track.bone_index = int(retarget_index)

        try:
            #Track type
            if action_type in ['rotation', 'rotation_quaternion']:
                track.usage = 0
                track_range = curve_group.channels[0].range()
                # if track_range[0] == track_range[1]:
                #     track.buffer_type = 4
                # else:
                track.buffer_type = 6
                buffer, bf_size = _serialize_bone_rotation(dst_lmt, bone, track, curve_group)
            elif action_type == 'location':
                if track.bone_index == 255:
                    track.usage = 4
                else:
                    track.usage = 1
                track.buffer_type = 9
                buffer, bf_size = _serialize_bone_location(dst_lmt, bone, track, curve_group)
            elif action_type == 'scale':
                track.usage = 2
                track.buffer_type = 9
                buffer, bf_size = _serialize_bone_scale(dst_lmt, track, curve_group)
            else:
                raise Exception(f'No anim data at {data_path}')
        except IndexError:
            print('BAKE YOUR ANIM!!!!')
        
        track.weight = 1.0
        track.data = buffer.to_byte_array()
        track.len_data = bf_size
        track.ofs_data = cml_size
        cml_size += bf_size
        tracks.append(track)
    return tracks, cml_size

def _serialize_events(dst_lmt, dst_action, action):
    pose_markers = action.pose_markers
    custom_prop = action.get_custom_properties_for_appid('dmc4')
    ev1_markers = []
    ev2_markers = []
    for ev in custom_prop.event_markers:
        event = dst_lmt.Event49(_parent=dst_action, _root=dst_lmt._root)
        event.frame = ev.marker.frame
        val = 0
        for k, v in GroupHash.items():
            bit = getattr(ev, k)
            val |= (bit << v)
        for i in range(8):
            bit = ev.slots[i]
            val |= bit << i
        event.group_id = val

        if ev.param_ev_type == 'Hitbox':
            ev1_markers.append(event)
        else:
            ev2_markers.append(event)

    ev1_markers.sort(key=lambda x: x.frame)
    ev2_markers.sort(key=lambda x: x.frame)

    for i in range(len(ev1_markers) - 1):
        ev1_markers[i].frame = ev1_markers[i+1].frame - ev1_markers[i].frame
    ev1_markers[-1].frame = dst_action.num_frames - ev1_markers[-1].frame
    for i in range(len(ev2_markers) - 1):
        ev2_markers[i].frame = ev2_markers[i+1].frame - ev2_markers[i].frame
    ev2_markers[-1].frame = dst_action.num_frames - ev2_markers[-1].frame
    
    return ev1_markers, ev2_markers

def _serialize_bone_rotation(dst_lmt, bone, track, fcurve_group):
    kf_num = len(fcurve_group.channels[0].keyframe_points)
    frame_counter = 1
    if kf_num == 1:
        buffer = KaitaiStream(BytesIO(bytearray(12)))
        if bone.parent:
            parent = bone.parent
            parent_mat = parent.matrix_local.inverted() @ bone.matrix_local
            parent_quat = parent_mat.to_quaternion() #convert back to bone space
            track.buffer_type = 4
            frame, w = fcurve_group.channels[0].keyframe_points[0].co
            x = fcurve_group.channels[1].keyframe_points[0].co[1]
            y = fcurve_group.channels[2].keyframe_points[0].co[1]
            z = fcurve_group.channels[3].keyframe_points[0].co[1]
            rot = parent_quat @ Quaternion([w, x, y, z])
            track.ref_data = dst_lmt.Vec4(_parent=track, _root=dst_lmt._root)
            track.ref_data.x = rot.x
            track.ref_data.y = rot.y
            track.ref_data.z = rot.z
            track.ref_data.w = rot.w
            buffer.write_bytes(struct.pack('fff', rot.x, rot.y, rot.z))
            return buffer, 12
        else:
            frame, w = fcurve_group.channels[0].keyframe_points[0].co
            x = fcurve_group.channels[1].keyframe_points[0].co[1]
            y = fcurve_group.channels[2].keyframe_points[0].co[1]
            z = fcurve_group.channels[3].keyframe_points[0].co[1]
            track.ref_data = dst_lmt.Vec4(_parent=track, _root=dst_lmt._root)
            track.ref_data.x = x
            track.ref_data.y = y
            track.ref_data.z = z
            track.ref_data.w = w
            buffer.write_bytes(struct.pack('fff', x, y, z))
            return buffer, 12
    else:
        buffer = KaitaiStream(BytesIO(bytearray(kf_num * 8)))
        track.ref_data = dst_lmt.Vec4(_parent=track, _root=dst_lmt._root)
        track.ref_data.x = 0.0
        track.ref_data.y = 0.0
        track.ref_data.z = 0.0
        track.ref_data.w = 1.0
        for k in range(kf_num):
            if bone.parent:
                parent = bone.parent
                parent_mat = parent.matrix_local.inverted() @ bone.matrix_local
                parent_quat = parent_mat.to_quaternion() #convert back to bone space
                if k < kf_num - 1:
                    frame_next = fcurve_group.channels[0].keyframe_points[k + 1].co[0]
                    if frame_next == track._parent.loop_frames and track._parent.loop_frames > 0:
                        if k < kf_num - 2:
                            frame_next = fcurve_group.channels[0].keyframe_points[k + 2].co[0]
                        else:
                            frame_next = track._parent.num_frames
                else:
                    frame_next = track._parent.num_frames
                frame, w = fcurve_group.channels[0].keyframe_points[k].co
                x = fcurve_group.channels[1].keyframe_points[k].co[1]
                y = fcurve_group.channels[2].keyframe_points[k].co[1]
                z = fcurve_group.channels[3].keyframe_points[k].co[1]
                rot = parent_quat @ Quaternion([w, x, y, z])
                if frame == track._parent.loop_frames and track._parent.loop_frames > 0:
                    track.ref_data.x = x
                    track.ref_data.y = y
                    track.ref_data.z = z
                    track.ref_data.w = w
                    continue
                quat = FrameQuat4_14()
                quat.from_quat([rot.w, rot.x, rot.y, rot.z], int(frame_next - frame - 1 if frame_next > frame else 0))
            else:
                if k < kf_num - 1:
                    frame_next = fcurve_group.channels[0].keyframe_points[k + 1].co[0]
                    if frame_next == track._parent.loop_frames and track._parent.loop_frames > 0:
                        if k < kf_num - 2:
                            frame_next = fcurve_group.channels[0].keyframe_points[k + 2].co[0]
                        else:
                            frame_next = track._parent.num_frames
                else:
                    frame_next = track._parent.num_frames
                frame, w = fcurve_group.channels[0].keyframe_points[k].co
                x = fcurve_group.channels[1].keyframe_points[k].co[1]
                y = fcurve_group.channels[2].keyframe_points[k].co[1]
                z = fcurve_group.channels[3].keyframe_points[k].co[1]
                if frame == track._parent.loop_frames and track._parent.loop_frames > 0:
                    track.ref_data.x = x
                    track.ref_data.y = y
                    track.ref_data.z = z
                    track.ref_data.w = w
                    continue
                quat = FrameQuat4_14()
                quat.from_quat([w, x, y, z], int(frame_next - frame - 1 if frame_next > frame else 0))
            buffer.write_bytes(bytes(quat))
            frame_counter += frame if frame > 0 else 1
        return buffer, (kf_num * 8)

def _serialize_bone_location(dst_lmt, bone, track, fcurve_group):
    kf_num = len(fcurve_group.channels[0].keyframe_points)
    frame_counter = 1
    if kf_num == 1:
        buffer = KaitaiStream(BytesIO(bytearray(12)))
        track.buffer_type = 2
        frame, x = fcurve_group.channels[0].keyframe_points[0].co
        y = fcurve_group.channels[1].keyframe_points[0].co[1]
        z = fcurve_group.channels[2].keyframe_points[0].co[1]
        track.ref_data = dst_lmt.Vec4(_parent=track, _root=dst_lmt._root)

        if bone.parent:
            parent_space = bone.parent.matrix_local.inverted() @ bone.matrix_local
            transform_mat = Matrix.Translation([x, y, z])
            parent_space_frame = (parent_space @ transform_mat).to_translation()
            x = parent_space_frame.x
            y = parent_space_frame.y
            z = parent_space_frame.z
            track.ref_data.x = x * 100.0
            track.ref_data.y = y * 100.0
            track.ref_data.z = z * 100.0
            track.ref_data.w = 1.0
            buffer.write_bytes(struct.pack('fff', x * 100.0, y * 100.0, z * 100.0))
        else:
            if track.bone_index == 255:
                track.ref_data.x = x * 100.0
                track.ref_data.y = y * 100.0
                track.ref_data.z = z * 100.0
                track.ref_data.w = 1.0
                buffer.write_bytes(struct.pack('fff', x * 100.0, y * 100.0, z * 100.0))
            else:
                track.ref_data.x = x * 100.0
                track.ref_data.y = z * 100.0
                track.ref_data.z = -y * 100.0
                track.ref_data.w = 1.0
                buffer.write_bytes(struct.pack('fff', x * 100.0, z * 100.0, -y * 100.0))
        return buffer, 12
    else:
        buffer = KaitaiStream(BytesIO(bytearray(kf_num * 16)))
        track.ref_data = dst_lmt.Vec4(_parent=track, _root=dst_lmt._root)
        track.ref_data.x = 0.0
        track.ref_data.y = 0.0
        track.ref_data.z = 0.0
        track.ref_data.w = 1.0
        for k in range(kf_num):
            frame, x = fcurve_group.channels[0].keyframe_points[k].co
            y = fcurve_group.channels[1].keyframe_points[k].co[1]
            z = fcurve_group.channels[2].keyframe_points[k].co[1]

            if k < kf_num - 1:
                frame_next = fcurve_group.channels[0].keyframe_points[k + 1].co[0]
                if frame_next == track._parent.loop_frames and track._parent.loop_frames > 0:
                    if k < kf_num - 2:
                        frame_next = fcurve_group.channels[0].keyframe_points[k + 2].co[0]
                    else:
                        frame_next = track._parent.num_frames
            else:
                frame_next = track._parent.num_frames

            if bone.parent:
                parent_space = bone.parent.matrix_local.inverted() @ bone.matrix_local
                transform_mat = Matrix.Translation([x, y, z])
                parent_space_frame = (parent_space @ transform_mat).to_translation()
                x = parent_space_frame.x
                y = parent_space_frame.y
                z = parent_space_frame.z
                if frame == track._parent.loop_frames and track._parent.loop_frames > 0:
                    track.ref_data.x = x * 100.0
                    track.ref_data.y = y * 100.0
                    track.ref_data.z = z * 100.0
                    track.ref_data.w = 1.0
                    continue
                buffer.write_bytes(struct.pack('fffI', x * 100.0, y * 100.0,
                                    z * 100.0, int(frame_next - frame if frame_next > frame else 0)))
            else:
                if track.bone_index == 255:
                    if frame == track._parent.loop_frames and track._parent.loop_frames > 0:
                        track.ref_data.x = x * 100.0
                        track.ref_data.y = y * 100.0
                        track.ref_data.z = z * 100.0
                        track.ref_data.w = 1.0
                        continue
                    buffer.write_bytes(struct.pack('fffI', x * 100.0, y * 100.0,
                                                    z * 100.0, int(frame_next - frame - 1 if frame_next > frame else 0)))
                else:
                    if frame == track._parent.loop_frames and track._parent.loop_frames > 0:
                        track.ref_data.x = x * 100.0
                        track.ref_data.y = z * 100.0
                        track.ref_data.z = -y * 100.0
                        track.ref_data.w = 1.0
                        continue
                    buffer.write_bytes(struct.pack('fffI', x * 100.0, z * 100.0,
                                                    -y * 100.0, int(frame_next - frame - 1 if frame_next > frame else 0)))
            frame_counter += frame if frame > 0 else 1
        return buffer, (kf_num * 16)

def _serialize_bone_scale(dst_lmt, track, fcurve_group):
    kf_num = len(fcurve_group.channels[0].keyframe_points)

    frame_counter = 1
    if kf_num == 1:
        buffer = KaitaiStream(BytesIO(bytearray(12)))
        track.buffer_type = 2
        frame, x = fcurve_group.channels[0].keyframe_points[0].co
        y = fcurve_group.channels[1].keyframe_points[0].co[1]
        z = fcurve_group.channels[2].keyframe_points[0].co[1]
        track.ref_data = dst_lmt.Vec4(_parent=track, _root=dst_lmt._root)
        track.ref_data.x = x
        track.ref_data.y = y
        track.ref_data.z = z
        track.ref_data.w = 1.0
        buffer.write_bytes(struct.pack('fff', x, y, z))
        return buffer, 12
    else:
        buffer = KaitaiStream(BytesIO(bytearray(kf_num * 16)))
        for k in range(kf_num):
            frame, x = fcurve_group.channels[0].keyframe_points[k].co
            y = fcurve_group.channels[1].keyframe_points[k].co[1]
            z = fcurve_group.channels[2].keyframe_points[k].co[1]
            if k < kf_num - 1:
                frame_next = fcurve_group.channels[0].keyframe_points[k + 1].co[0]
            else:
                frame_next = track._parent.num_frames
            if k == kf_num - 1:
                track.ref_data = dst_lmt.Vec4(_parent=track, _root=dst_lmt._root)
                track.ref_data.x = x
                track.ref_data.y = y
                track.ref_data.z = z
                track.ref_data.w = 1.0
            buffer.write_bytes(struct.pack('fffI', x, y, z, int(frame_next - frame - 1 if frame_next > frame else 0)))
            frame_counter += frame if frame > 0 else 1
        return buffer, (kf_num * 16)

def filter_armatures(self, obj):
    # TODO: filter by custom properties that indicate is
    # a RE5 compatible armature
    return obj.type == 'ARMATURE'

#@blender_registry.register_blender_props_to_type('TimelineMarker', 'dmc4_event_props')
@blender_registry.register_blender_prop
class DMC4EventGroup(bpy.types.PropertyGroup):
    main_sword_display: bpy.props.IntProperty()
    dante_yamato_display: bpy.props.IntProperty()
    stand_fade_efx: bpy.props.IntProperty()
    ex_speedup: bpy.props.IntProperty()
    stand_fade: bpy.props.IntProperty()
    stand_flicker: bpy.props.IntProperty()
    stand_transp: bpy.props.IntProperty()
    right_foot_ik: bpy.props.IntProperty()
    left_foot_ik: bpy.props.IntProperty()
    gun_display: bpy.props.IntProperty()
    face_swap: bpy.props.IntProperty()
    stand_sword_disp: bpy.props.IntProperty()
    sword_trail: bpy.props.IntProperty()
    slots: bpy.props.BoolVectorProperty(name='Toggles',size=8)
    param_ev_type: bpy.props.StringProperty()

    def setup(self, ev_type, value):
        for k, v in GroupHash.items():
            val = (value >> v) & ((1 << GroupBitNum[k]) - 1)
            setattr(self, k, val)
            #self.__dict__.update({k:val})
        for i in range(8):
            self.slots[i] = ((value >> i) & 1)
        self.param_ev_type = ev_type

    def copy_custom_properties_to(self, dst_obj):
        for attr_name in self.__annotations__:
            if type(getattr(self, attr_name)) is str:
                setattr(dst_obj, attr_name, int(getattr(self, attr_name), 16))
            else:
                setattr(dst_obj, attr_name, getattr(self, attr_name))

    # FIXME: dedupe
    def copy_custom_properties_from(self, src_obj):
        for attr_name in self.__annotations__:
            try:
                setattr(self, attr_name, getattr(src_obj, attr_name))
            except TypeError:
                setattr(self, attr_name, hex(getattr(src_obj, attr_name)))


@blender_registry.register_custom_properties_action("lmt_49", ("re5", "dmc4"))
@blender_registry.register_blender_prop
class Lmt49ActionCustomProperties(bpy.types.PropertyGroup):
    lmt_id: bpy.props.IntProperty(name='LMT index',default=0)
    num_frames: bpy.props.IntProperty(name='Frames')
    loop_frames: bpy.props.IntProperty(name='Loop frames')
    end_pos: bpy.props.FloatVectorProperty(name='Pos',size=3)
    end_quat: bpy.props.FloatVectorProperty(name='Quat',size=4)
    events_params_01: bpy.props.IntVectorProperty(size=8)
    events_params_02: bpy.props.IntVectorProperty(size=8)
    event_markers: bpy.props.CollectionProperty(type=DMC4EventGroup)
    def copy_custom_properties_to(self, dst_obj):
        for attr_name in self.__annotations__:
            if type(getattr(self, attr_name)) is str:
                setattr(dst_obj, attr_name, int(getattr(self, attr_name), 16))
            else:
                setattr(dst_obj, attr_name, getattr(self, attr_name))

    # FIXME: dedupe
    def copy_custom_properties_from(self, src_obj):
        for attr_name in self.__annotations__:
            try:
                setattr(self, attr_name, getattr(src_obj, attr_name))
            except TypeError:
                setattr(self, attr_name, hex(getattr(src_obj, attr_name)))

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
    action: bpy.props.PointerProperty(type=bpy.types.Action)
    name: bpy.props.StringProperty(name='Action', default='')
    lmt_id: bpy.props.IntProperty(name='LMT index',default=0)
    frames: bpy.props.IntProperty()
    loop_frames: bpy.props.IntProperty()
    coll_ev: bpy.props.IntVectorProperty(size=8)
    sfx_ev: bpy.props.IntVectorProperty(size=8)

# class AlbamAction(Lmt49Action, bpy.types.PropertyGroup):
#     pass

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

@blender_registry.register_blender_prop
class AlbamActionGroup(bpy.types.PropertyGroup):
    #Group of actions by LMT file
    actions: bpy.props.CollectionProperty(type=Lmt49Action)
    active_id: bpy.props.IntProperty(name="Active action")
    num_slots: bpy.props.IntProperty(name="Track count")
    #name: bpy.props.StringProperty()
    armature: bpy.props.PointerProperty(type=bpy.types.Object, poll=filter_armatures)
    export_path: bpy.props.StringProperty()

    def add(self, name=''):
        action = self.actions.add()
        action.name = name
        return action
        

@blender_registry.register_blender_prop_albam(name="lmt_groups")
class AlbamLmtGroups(bpy.types.PropertyGroup):
    #Meta collection of LMT files
    anim_group: bpy.props.CollectionProperty(type=AlbamActionGroup)
    active_group_id: bpy.props.IntProperty()
    active_group: bpy.props.PointerProperty(type=AlbamActionGroup)

    def add(self, name=''):
        group = self.anim_group.add()
        group.name = name
        return group


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

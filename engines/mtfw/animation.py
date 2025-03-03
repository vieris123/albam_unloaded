from ctypes import Structure, Union, c_ulonglong, c_double, c_uint64, c_uint8
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
        custom_property.copy_custom_properties_from(block.block_header)
        #custom_property.copy_custom_properties_to(action)

        #Events
        cumulative_frames = 0
        action_group.coll_ev = block.block_header.events_params_01[:8]
        for event in block.block_header.events_01:
            marker = action.pose_markers.new(f'ev1_{cumulative_frames}_{event.group_id}')
            marker.frame = cumulative_frames
            marker.dmc4_event_props.setup('Hitbox', event.group_id)
            marker.dmc4_event_props.action = action_group
            cumulative_frames += event.frame

        cumulative_frames = 0
        action_group.sfx_ev = block.block_header.events_params_01[:8]
        for event in block.block_header.events_02:
            marker = action.pose_markers.new(f'ev2_{cumulative_frames}_{event.group_id}')
            marker.frame = cumulative_frames
            marker.dmc4_event_props.setup('Sound', event.group_id)
            marker.dmc4_event_props.action = action_group
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

            group_name = f"{track.bone_index}.{bone_index}.{action_type}"
            group = action.groups.get(group_name) or action.groups.new(group_name)

            #TOGGLE RENAMED BONES
            if renamed_bone_flag:
                data_path = f"pose.bones[\"{armature.data.bones[bone_index].name}\"].{TRACK_MODE}"
            else:
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

    # exportable = context.scene.albam.exportable.file_list.add()
    # exportable.bl_object = lmt_group

    # context.scene.albam.exportable.file_list.update()


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
            quat *= -1.0

        R = np.sqrt(1.0 - quat[0])
        mag_safe = np.sqrt(1.0 - (quat[0] * quat[0]))
        mag = 1.0 if mag_safe < 0.00001 else mag_safe

        phi = np.arcsin(quat[2] / mag)
        theta = np.arcsin(quat[1] / (np.cos(phi) * mag))
        test = theta * self.maskInv
        self._x = int(theta * self.maskInv)
        #self._x = struct.unpack('@Q', struct.pack('@d', (theta * self.maskInv)))[0]
        #self._x = int(theta * self.maskInv)
        self._y = int(phi * self.maskInv)
        #self._y = struct.unpack('@Q', struct.pack('@d', (phi * self.maskInv)))[0]
        self._wComp = int(R * self.maskW)
        #self._wComp = struct.unpack('@Q', struct.pack('@d', (R * self.maskW)))[0]
        self.duration = duration

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

    if armature.pose.bones[ROOT_BONE_NAME] is not None:
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
    block_size = _serialize_block(dst_lmt, lmt_group, header_size)
    final_size = header_size + block_size
    stream = KaitaiStream(BytesIO(bytearray(final_size)))
    dst_lmt._check()
    dst_lmt._write(stream)
    pass

def _serialize_top_level_lmt(dst_lmt, lmt_group):
    dst_lmt.id_magic = bytearray('\x4c\x4d\x54\x00')
    dst_lmt.version = 49
    dst_lmt.num_block_offsets = lmt_group.num_slots
    return num_slots * 4 + 8 

def _serialize_block(dst_lmt, lmt_group, header_size):
    dst_lmt.block_offsets = []
    for i in range(dst_lmt.num_block_offsets):
        block_offset = dst_lmt.BlockOffset(_parent=dst_lmt, _root=dst_lmt._root)
        block_offset.offset = 0
        dst_lmt.block_offsets.append(block_offset)
    
    cml_size = header_size
    for group in lmt_group.actions:
        action = group.action
        block = dst_lmt.BlockHeader49()
        
        
        active_offset = dst_lmt.block_offsets[action.lmt_id]
        active_offset.block_header = block
    
    return cml_size

def _serialize_tracks(dst_lmt, action):
    tracks = []
    cml_size = 0
    for curve_group in action.groups:
        track = dst_lmt.Track49()
        name = curve_group.name
        retarget_index, index, action_type = name.split('.')
        track.joint_type = 0

        #Bone index
        if index == 'root_motion':
            track.bone_index = 255
        else:
            track.bone_index = int(retarget_index)

        #Track type
        if action_type == 'rotation':
            track.usage = 0
            track_range = curve_group.channels[0].range()
            # if track_range[0] == track_range[1]:
            #     track.buffer_type = 4
            # else:
            track.buffer_type = 6
            buffer, bf_size = _serialize_bone_rotation(dst_lmt, curve_group)
        elif action_type == 'location':
            track.usage = 1
            buffer, bf_size = _serialize_bone_location(dst_lmt, curve_group)
        elif action_type == 'scale':
            track.usage = 2
            buffer, bf_size = _serialize_bone_scale(dst_lmt, curve_group)
        
        track.data = buffer
        track.len_data = bf_size
        track.ofs_data = cml_size
        cml_size += bf_size
        tracks.append(track)
    return tracks

def _serialize_events(dst_lmt, action):
    pass

def _serialize_bone_rotation(dst_lmt, fcurve_group):
    kf_num = len(fcurve_group.channels[0].keyframe_points)
    buffer = KaitaiStream(BytesIO(bytearray(kf_num * 8)))
    frame_counter = 1
    for k in range(kf_num):
        frame, w = fcurve_group.channels[0].keyframe_points[k].co
        x = fcurve_group.channels[1].keyframe_points[k].co[1]
        y = fcurve_group.channels[2].keyframe_points[k].co[1]
        z = fcurve_group.channels[3].keyframe_points[k].co[1]
        quat = FrameQuat4_14()
        quat.from_quat([w, x, y, z], int(frame - frame_counter + 1))
        buffer.write_bytes(bytes(quat))
        frame_counter += frame
    return buffer, (kf_num * 8)

def _serialize_bone_location(dst_lmt, fcurve_group):
    kf_num = len(fcurve_group.channels[0].keyframe_points)
    buffer = KaitaiStream(BytesIO(bytearray(kf_num * 8)))
    frame_counter = 1
    for k in range(kf_num):
        frame, x = fcurve_group.channels[0].keyframe_points[k].co
        y = fcurve_group.channels[1].keyframe_points[k].co[1]
        z = fcurve_group.channels[2].keyframe_points[k].co[1]
        buffer.write_bytes(struct.pack('fffI', x * 100.0, z * 100.0, -y * 100.0, int(frame - frame_counter + 1)))
        frame_counter += frame
    return buffer, (kf_num * 8)

def _serialize_bone_scale(dst_lmt, fcurve_group):
    kf_num = len(fcurve_group.channels[0].keyframe_points)
    buffer = KaitaiStream(BytesIO(bytearray(kf_num * 8)))
    frame_counter = 1
    for k in range(kf_num):
        frame, x = fcurve_group.channels[0].keyframe_points[k].co
        y = fcurve_group.channels[1].keyframe_points[k].co[1]
        z = fcurve_group.channels[2].keyframe_points[k].co[1]
        buffer.write_bytes(struct.pack('fffI', x, y, z, int(frame - frame_counter + 1)))
        frame_counter += frame
    return buffer, (kf_num * 8)

def filter_armatures(self, obj):
    # TODO: filter by custom properties that indicate is
    # a RE5 compatible armature
    return obj.type == 'ARMATURE'

@blender_registry.register_custom_properties_action("lmt_49", ("re5", "dmc4"))
@blender_registry.register_blender_prop
class Lmt49ActionCustomProperties(bpy.types.PropertyGroup):
    #lmt_id: bpy.props.IntProperty(name='LMT index',default=0)
    num_frames: bpy.props.IntProperty(name='Frames')
    loop_frames: bpy.props.IntProperty(name='Loop frames')

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

@blender_registry.register_blender_props_to_type('TimelineMarker', 'dmc4_event_props')
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
    slots: bpy.props.BoolVectorProperty(name='Param',size=8)
    param_ev_type: bpy.props.StringProperty()
    action: bpy.props.PointerProperty(type=Lmt49Action)

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
    active_group: bpy.props.IntProperty()

    def add(self, name=''):
        group = self.anim_group.add()
        group.name = name
        return group


@blender_registry.register_blender_prop_albam(name='import_options_lmt')
class ImportOptionsLMT(bpy.types.PropertyGroup):
    armature: bpy.props.PointerProperty(type=bpy.types.Object, poll=filter_armatures)
    renamed_bone_flag: bpy.props.BoolProperty(name = 'Renamed bones')


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

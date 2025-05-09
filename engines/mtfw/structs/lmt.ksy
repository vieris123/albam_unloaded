meta:
  endian: le
  file-extension: lmt
  id: lmt
  ks-version: 0.10
  title: MTFramework animation format


seq:
  - {id: id_magic, contents: [0x4c, 0x4d, 0x54, 0x00]}
  - {id: version, type: u2}
  - {id: num_block_offsets, type: u2}
  - {id: block_offsets, type: block_offset, repeat: expr, repeat-expr: num_block_offsets}

types:
  block_offset:
    seq:
      - {id: offset, type: u4}
    instances:
      lmt_ver:
        value: _parent.version
      block_header:
        pos: offset
        type:
          switch-on: lmt_ver
          cases:
            49: block_header49
            51: block_header51
            67: block_header67
        if: offset != 0

  block_header49:
    seq:
      - {id: ofs_frame, type: u4}
      - {id: num_tracks, type: u4}
      - {id: num_frames, type: u4}
      - {id: loop_frames, type: s4}
      - {id: end_pos, type: vec4}
      - {id: end_quat, type: vec4}
      - {id: events_params_01, type: u2, repeat: expr, repeat-expr: 8}
      - {id: unused_ev_01, type: u2, repeat: expr, repeat-expr: 24}
      - {id: num_events_01, type: u4}
      - {id: event_buffer_01, type: u4}
      - {id: events_params_02, type: u2, repeat: expr, repeat-expr: 8}
      - {id: unused_ev_02, type: u2, repeat: expr, repeat-expr: 24}
      - {id: num_events_02, type: u4}
      - {id: event_buffer_02, type: u4}
    instances:
      size_:
        value: 0xC0
      tracks:
        {pos: ofs_frame, type: track49, repeat: expr, repeat-expr: num_tracks}
      events_01:
        {pos: event_buffer_01, type: event49, repeat: expr, repeat-expr: num_events_01}
      events_02:
        {pos: event_buffer_02, type: event49, repeat: expr, repeat-expr: num_events_02}
    
  track49:
    seq:
      - {id: buffer_type, type: u1}
      - {id: usage, type: u1}
      - {id: joint_type, type: u1}
      - {id: bone_index, type: u1}
      - {id: weight, type: f4}
      - {id: len_data, type: u4}
      - {id: ofs_data, type: u4}
      - {id: ref_data, type: vec4}
    instances:
      size_:
        value: 0x20
      data:
        {pos: ofs_data, size: len_data}
  
  event49:
    seq:
      - {id: group_id, type: u4}
      - {id: frame, type: u4}
  
  block_header51:
    seq:
      - {id: ofs_frame, type: u4}
      - {id: num_tracks, type: u4}
      - {id: num_frames, type: u4}
      - {id: loop_frames, type: u4}
      - {id: end_pos, type: vec4}
      - {id: end_quat, type: vec4}
      - {id: display_events, type: u4, repeat: expr, repeat-expr: 16}
      - {id: num_events_01, type: u4}
      - {id: ofs_buffer_01, type: u4}
      - {id: sfx_events, type: u2, repeat: expr, repeat-expr: 32}
      - {id: num_events_02, type: u4}
      - {id: ofs_buffer_02, type: u4}
    instances:
      tracks:
        {pos: ofs_frame, type: track51, repeat: expr, repeat-expr: num_tracks}
      atk_buff:
        {pos: ofs_buffer_01, type: atk, repeat: expr, repeat-expr: num_events_01}
      atk_buff2:
        {pos: ofs_buffer_02, type: atk2, repeat: expr, repeat-expr: num_events_02}

  track51:
    seq:
      - {id: buffer_type, type: u1}
      - {id: usage, type: u1}
      - {id: joint_type, type: u1}
      - {id: bone_index, type: u1}
      - {id: unk_01, type: f4}
      - {id: len_data, type: u4}
      - {id: ofs_data, type: u4}
      - {id: ref_data, type: vec4}
    instances:
      data:
        {pos: ofs_data, size: len_data}
        
  atk:
    seq:
      - {id: unk_00, type: u4}
      - {id: duration, type: u4}
      
  atk2:
    seq:
      - {id: unk_00, type: u4}
      - {id: unk_01, type: u4}
      
  block_header67:
    seq:
      - {id: ofs_frame, type: u4}
      - {id: num_tracks, type: u4}
      - {id: num_frames, type: u4}
      - {id: loop_frame, type: u4}
      - {id: unk_floats, type: f4, repeat: expr, repeat-expr: 8}
      - {id: unk_00, type: u4}
      - {id: ofs_buffer_1, type: u4}
      - {id: ofs_buffer_2, type: u4}
    instances:
      tracks:
        {pos: ofs_frame, type: track67, repeat: expr, repeat-expr: num_tracks}

  track67:
    seq:
      - {id: buffer_type, type: u1}
      - {id: usage, type: u1}
      - {id: joint_type, type: u1}
      - {id: bone_index, type: u1}
      - {id: weight, type: f4}
      - {id: len_data, type: u4}
      - {id: ofs_data, type: u4}
      - {id: unk_reference_data, type: f4, repeat: expr, repeat-expr: 4}
      - {id: ofs_floats, type:  ofs_float_buff}
    instances:
      data:
        {pos: ofs_data, size: len_data}

  ofs_float_buff:
    seq:
    - {id: ofs_buffer, type: u4}
    instances:
      is_exist:
        value: ofs_buffer
      body:
        pos: ofs_buffer
        type: float_buffer
        if: is_exist !=0
  
  float_buffer:
    seq:
      - {id: unk_00, type: f4, repeat: expr, repeat-expr: 8}
      
  vec3:
    seq:
      - {id: x, type: f4}
      - {id: y, type: f4}
      - {id: z, type: f4}
      
  vec4:
    seq:
      - {id: x, type: f4}
      - {id: y, type: f4}
      - {id: z, type: f4}
      - {id: w, type: f4}

meta:
  id: sbc_156
  file-extension: sbc
  endian: le
  title:  DMC4 DX9 / Resident Evil 5 (MTFramework) SBC1 collision format
  # DMC4 field meanings: Vibed/RE/sbc_dx9_format.md. Albam reads and writes DMC4 files with engines/mtfw/sbc_bvh.py.
  license: CC0-1.0
  ks-version: 0.10

seq:
  - {id: id_magic, contents: [0x53, 0x42, 0x43, 0x31]} # SBC1
  - {id: version, type: u2}
  - {id: num_groups, type: u2}
  - {id: num_groups_nodes, type: u2} # top-tree nodes: max(1, num_groups - 1); not read by DX9
  - {id: max_parts_nest_count, type: u1} # top-tree depth in nodes; not read by DX9
  - {id: max_nest_count, type: u1} # deepest group tree in nodes; not read by DX9
  - {id: num_boxes, type: u4}
  - {id: num_faces, type: u4}
  - {id: num_vertices, type: u4}
  - {id: bbox, type: tbox}
  - {id: boxes, type: re5boxes, repeat: expr, repeat-expr: num_boxes}
  - {id: groups, type: sbcgroup, repeat: expr, repeat-expr: num_groups}
  - {id: triangles, type : re5triangle, repeat: expr, repeat-expr: num_faces}
  - {id: vertices, type: vertex, repeat: expr, repeat-expr: num_vertices}
  
types:

  sbcgroup: #96 bytes
    seq:
      - {id: base, type: u4}
      - {id: start_tris, type: u4}
      - {id: start_boxes, type: u4} # root node of this group's tree
      - {id: start_vertices, type: u4}
      - {id: group_id, type: u4} # part ID for Sbc::activateParts, 0xFFFFFFFF = none
      - {id: bbox_this, type: tbox}
      - {id: vmin, type: vec3, repeat: expr, repeat-expr: 2} # top node k's child boxes (read by the DX9 traversal)
      - {id: vmax, type: vec3, repeat: expr, repeat-expr: 2}
      - {id: child_index, type: u2, repeat: expr, repeat-expr: 2} # top node k's leaf children, 0 for inner

  re5triangle: #28 bytes
    seq:
      - {id: vert, type: u2, repeat: expr, repeat-expr: 3}
      - {id: unk_00, type: u1} # no DX9 reader
      - {id: unk_01, type: u1} # no DX9 reader
      - {id: runtime_attr, type: u4} # channel mask rebuilt at load; 0x3FFFFF00 in every DX9 file
      - {id: type, type: u4} # ground material ID (cUtil::getEfctMtrlFlg)
      - {id: special_attr, type: u4} # channels let through; 0x10000000 / 0x20000000 override
      - {id: surface_attr, type: u4} # 0x20 force floor, 0x10 force wall, 0x1000 sheltered
      - {id: unk_02, type: u4}
  
  re5boxes: # 80 bytes
    seq:
      - {id: boxes, type: pbox, repeat: expr, repeat-expr: 2}
      - {id: bit, type: u2} # 0x40 / 0x80 child 0 / 1 is a leaf; bits 0-5 min/max order per axis
      - {id: child_index, type: u2, repeat: expr, repeat-expr: 2} # leaf: item; inner: node relative to the tree, 0 = none
      - {id: nulls, type: u1, repeat: expr, repeat-expr: 10}
      
  vertex:
    seq:
      - {id: vector, type: vec4}
  
  tbox:
    seq:
      - {id: min, type: vec3}
      - {id: max, type: vec3}
      
  pbox:
    seq:
      - {id: min, type: vec4}
      - {id: max, type: vec4}
      
  vec4:
    seq:
      - {id: x, type: f4}
      - {id: y, type: f4}
      - {id: z, type: f4}
      - {id: w, type: f4}

  vec3:
    seq:
      - {id: x, type: f4}
      - {id: y, type: f4}
      - {id: z, type: f4}
      
  rgba:
    seq:
      - {id: red, type: u1}
      - {id: green, type: u1}
      - {id: blue, type: u1}
      - {id: alpha, type: u1}
  

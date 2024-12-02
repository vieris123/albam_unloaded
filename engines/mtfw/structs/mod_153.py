# This is a generated file! Please edit source .ksy file and use kaitai-struct-compiler to rebuild

import kaitaistruct
from kaitaistruct import KaitaiStruct, KaitaiStream, BytesIO
import collections


if getattr(kaitaistruct, 'API_VERSION', (0, 9)) < (0, 9):
    raise Exception("Incompatible Kaitai Struct Python API: 0.9 or later is required, but you have %s" % (kaitaistruct.__version__))

class Mod153(KaitaiStruct):
    SEQ_FIELDS = ["header", "reserved_01", "reserved_02", "bsphere", "bbox_min", "bbox_max", "model_info"]
    def __init__(self, _io, _parent=None, _root=None):
        self._io = _io
        self._parent = _parent
        self._root = _root if _root else self
        self._debug = collections.defaultdict(dict)

    def _read(self):
        self._debug['header']['start'] = self._io.pos()
        self.header = Mod153.ModHeader(self._io, self, self._root)
        self.header._read()
        self._debug['header']['end'] = self._io.pos()
        self._debug['reserved_01']['start'] = self._io.pos()
        self.reserved_01 = self._io.read_u4le()
        self._debug['reserved_01']['end'] = self._io.pos()
        self._debug['reserved_02']['start'] = self._io.pos()
        self.reserved_02 = self._io.read_u4le()
        self._debug['reserved_02']['end'] = self._io.pos()
        self._debug['bsphere']['start'] = self._io.pos()
        self.bsphere = Mod153.Vec4(self._io, self, self._root)
        self.bsphere._read()
        self._debug['bsphere']['end'] = self._io.pos()
        self._debug['bbox_min']['start'] = self._io.pos()
        self.bbox_min = Mod153.Vec4(self._io, self, self._root)
        self.bbox_min._read()
        self._debug['bbox_min']['end'] = self._io.pos()
        self._debug['bbox_max']['start'] = self._io.pos()
        self.bbox_max = Mod153.Vec4(self._io, self, self._root)
        self.bbox_max._read()
        self._debug['bbox_max']['end'] = self._io.pos()
        self._debug['model_info']['start'] = self._io.pos()
        self.model_info = Mod153.ModelInfo(self._io, self, self._root)
        self.model_info._read()
        self._debug['model_info']['end'] = self._io.pos()

    class Vec4(KaitaiStruct):
        SEQ_FIELDS = ["x", "y", "z", "w"]
        def __init__(self, _io, _parent=None, _root=None):
            self._io = _io
            self._parent = _parent
            self._root = _root if _root else self
            self._debug = collections.defaultdict(dict)

        def _read(self):
            self._debug['x']['start'] = self._io.pos()
            self.x = self._io.read_f4le()
            self._debug['x']['end'] = self._io.pos()
            self._debug['y']['start'] = self._io.pos()
            self.y = self._io.read_f4le()
            self._debug['y']['end'] = self._io.pos()
            self._debug['z']['start'] = self._io.pos()
            self.z = self._io.read_f4le()
            self._debug['z']['end'] = self._io.pos()
            self._debug['w']['start'] = self._io.pos()
            self.w = self._io.read_f4le()
            self._debug['w']['end'] = self._io.pos()


    class BonePalette(KaitaiStruct):
        SEQ_FIELDS = ["unk_01", "indices"]
        def __init__(self, _io, _parent=None, _root=None):
            self._io = _io
            self._parent = _parent
            self._root = _root if _root else self
            self._debug = collections.defaultdict(dict)

        def _read(self):
            self._debug['unk_01']['start'] = self._io.pos()
            self.unk_01 = self._io.read_u4le()
            self._debug['unk_01']['end'] = self._io.pos()
            self._debug['indices']['start'] = self._io.pos()
            self.indices = []
            for i in range(32):
                if not 'arr' in self._debug['indices']:
                    self._debug['indices']['arr'] = []
                self._debug['indices']['arr'].append({'start': self._io.pos()})
                self.indices.append(self._io.read_u1())
                self._debug['indices']['arr'][i]['end'] = self._io.pos()

            self._debug['indices']['end'] = self._io.pos()

        @property
        def size_(self):
            if hasattr(self, '_m_size_'):
                return self._m_size_

            self._m_size_ = 36
            return getattr(self, '_m_size_', None)


    class ModHeader(KaitaiStruct):
        SEQ_FIELDS = ["ident", "version", "revision", "num_bones", "num_meshes", "num_materials", "num_vertices", "num_faces", "num_edges", "size_vertex_buffer", "size_vertex_buffer_2", "num_textures", "num_groups", "num_bone_palettes", "offset_bones_data", "offset_groups", "offset_materials_data", "offset_meshes_data", "offset_vertex_buffer", "offset_vertex_buffer_2", "offset_index_buffer"]
        def __init__(self, _io, _parent=None, _root=None):
            self._io = _io
            self._parent = _parent
            self._root = _root if _root else self
            self._debug = collections.defaultdict(dict)

        def _read(self):
            self._debug['ident']['start'] = self._io.pos()
            self.ident = self._io.read_bytes(4)
            self._debug['ident']['end'] = self._io.pos()
            if not self.ident == b"\x4D\x4F\x44\x00":
                raise kaitaistruct.ValidationNotEqualError(b"\x4D\x4F\x44\x00", self.ident, self._io, u"/types/mod_header/seq/0")
            self._debug['version']['start'] = self._io.pos()
            self.version = self._io.read_u1()
            self._debug['version']['end'] = self._io.pos()
            self._debug['revision']['start'] = self._io.pos()
            self.revision = self._io.read_u1()
            self._debug['revision']['end'] = self._io.pos()
            self._debug['num_bones']['start'] = self._io.pos()
            self.num_bones = self._io.read_u2le()
            self._debug['num_bones']['end'] = self._io.pos()
            self._debug['num_meshes']['start'] = self._io.pos()
            self.num_meshes = self._io.read_u2le()
            self._debug['num_meshes']['end'] = self._io.pos()
            self._debug['num_materials']['start'] = self._io.pos()
            self.num_materials = self._io.read_u2le()
            self._debug['num_materials']['end'] = self._io.pos()
            self._debug['num_vertices']['start'] = self._io.pos()
            self.num_vertices = self._io.read_u4le()
            self._debug['num_vertices']['end'] = self._io.pos()
            self._debug['num_faces']['start'] = self._io.pos()
            self.num_faces = self._io.read_u4le()
            self._debug['num_faces']['end'] = self._io.pos()
            self._debug['num_edges']['start'] = self._io.pos()
            self.num_edges = self._io.read_u4le()
            self._debug['num_edges']['end'] = self._io.pos()
            self._debug['size_vertex_buffer']['start'] = self._io.pos()
            self.size_vertex_buffer = self._io.read_u4le()
            self._debug['size_vertex_buffer']['end'] = self._io.pos()
            self._debug['size_vertex_buffer_2']['start'] = self._io.pos()
            self.size_vertex_buffer_2 = self._io.read_u4le()
            self._debug['size_vertex_buffer_2']['end'] = self._io.pos()
            self._debug['num_textures']['start'] = self._io.pos()
            self.num_textures = self._io.read_u4le()
            self._debug['num_textures']['end'] = self._io.pos()
            self._debug['num_groups']['start'] = self._io.pos()
            self.num_groups = self._io.read_u4le()
            self._debug['num_groups']['end'] = self._io.pos()
            self._debug['num_bone_palettes']['start'] = self._io.pos()
            self.num_bone_palettes = self._io.read_u4le()
            self._debug['num_bone_palettes']['end'] = self._io.pos()
            self._debug['offset_bones_data']['start'] = self._io.pos()
            self.offset_bones_data = self._io.read_u4le()
            self._debug['offset_bones_data']['end'] = self._io.pos()
            self._debug['offset_groups']['start'] = self._io.pos()
            self.offset_groups = self._io.read_u4le()
            self._debug['offset_groups']['end'] = self._io.pos()
            self._debug['offset_materials_data']['start'] = self._io.pos()
            self.offset_materials_data = self._io.read_u4le()
            self._debug['offset_materials_data']['end'] = self._io.pos()
            self._debug['offset_meshes_data']['start'] = self._io.pos()
            self.offset_meshes_data = self._io.read_u4le()
            self._debug['offset_meshes_data']['end'] = self._io.pos()
            self._debug['offset_vertex_buffer']['start'] = self._io.pos()
            self.offset_vertex_buffer = self._io.read_u4le()
            self._debug['offset_vertex_buffer']['end'] = self._io.pos()
            self._debug['offset_vertex_buffer_2']['start'] = self._io.pos()
            self.offset_vertex_buffer_2 = self._io.read_u4le()
            self._debug['offset_vertex_buffer_2']['end'] = self._io.pos()
            self._debug['offset_index_buffer']['start'] = self._io.pos()
            self.offset_index_buffer = self._io.read_u4le()
            self._debug['offset_index_buffer']['end'] = self._io.pos()

        @property
        def size_(self):
            if hasattr(self, '_m_size_'):
                return self._m_size_

            self._m_size_ = 72
            return getattr(self, '_m_size_', None)


    class Vertex(KaitaiStruct):
        SEQ_FIELDS = ["position", "bone_indices", "weight_values", "normal", "tangent", "uv", "uv2"]
        def __init__(self, _io, _parent=None, _root=None):
            self._io = _io
            self._parent = _parent
            self._root = _root if _root else self
            self._debug = collections.defaultdict(dict)

        def _read(self):
            self._debug['position']['start'] = self._io.pos()
            self.position = Mod153.Vec4S2(self._io, self, self._root)
            self.position._read()
            self._debug['position']['end'] = self._io.pos()
            self._debug['bone_indices']['start'] = self._io.pos()
            self.bone_indices = []
            for i in range(4):
                if not 'arr' in self._debug['bone_indices']:
                    self._debug['bone_indices']['arr'] = []
                self._debug['bone_indices']['arr'].append({'start': self._io.pos()})
                self.bone_indices.append(self._io.read_u1())
                self._debug['bone_indices']['arr'][i]['end'] = self._io.pos()

            self._debug['bone_indices']['end'] = self._io.pos()
            self._debug['weight_values']['start'] = self._io.pos()
            self.weight_values = []
            for i in range(4):
                if not 'arr' in self._debug['weight_values']:
                    self._debug['weight_values']['arr'] = []
                self._debug['weight_values']['arr'].append({'start': self._io.pos()})
                self.weight_values.append(self._io.read_u1())
                self._debug['weight_values']['arr'][i]['end'] = self._io.pos()

            self._debug['weight_values']['end'] = self._io.pos()
            self._debug['normal']['start'] = self._io.pos()
            self.normal = Mod153.Vec4U1(self._io, self, self._root)
            self.normal._read()
            self._debug['normal']['end'] = self._io.pos()
            self._debug['tangent']['start'] = self._io.pos()
            self.tangent = Mod153.Vec4U1(self._io, self, self._root)
            self.tangent._read()
            self._debug['tangent']['end'] = self._io.pos()
            self._debug['uv']['start'] = self._io.pos()
            self.uv = Mod153.Vec2HalfFloat(self._io, self, self._root)
            self.uv._read()
            self._debug['uv']['end'] = self._io.pos()
            self._debug['uv2']['start'] = self._io.pos()
            self.uv2 = Mod153.Vec2HalfFloat(self._io, self, self._root)
            self.uv2._read()
            self._debug['uv2']['end'] = self._io.pos()


    class Vec2HalfFloat(KaitaiStruct):
        SEQ_FIELDS = ["u", "v"]
        def __init__(self, _io, _parent=None, _root=None):
            self._io = _io
            self._parent = _parent
            self._root = _root if _root else self
            self._debug = collections.defaultdict(dict)

        def _read(self):
            self._debug['u']['start'] = self._io.pos()
            self.u = self._io.read_bytes(2)
            self._debug['u']['end'] = self._io.pos()
            self._debug['v']['start'] = self._io.pos()
            self.v = self._io.read_bytes(2)
            self._debug['v']['end'] = self._io.pos()


    class RcnTriangle(KaitaiStruct):
        SEQ_FIELDS = ["v0", "v1", "v2", "reserved"]
        def __init__(self, _io, _parent=None, _root=None):
            self._io = _io
            self._parent = _parent
            self._root = _root if _root else self
            self._debug = collections.defaultdict(dict)

        def _read(self):
            self._debug['v0']['start'] = self._io.pos()
            self.v0 = self._io.read_bits_int_le(21)
            self._debug['v0']['end'] = self._io.pos()
            self._debug['v1']['start'] = self._io.pos()
            self.v1 = self._io.read_bits_int_le(21)
            self._debug['v1']['end'] = self._io.pos()
            self._debug['v2']['start'] = self._io.pos()
            self.v2 = self._io.read_bits_int_le(21)
            self._debug['v2']['end'] = self._io.pos()
            self._debug['reserved']['start'] = self._io.pos()
            self.reserved = self._io.read_bits_int_le(1) != 0
            self._debug['reserved']['end'] = self._io.pos()


    class Matrix4x4(KaitaiStruct):
        SEQ_FIELDS = ["row_1", "row_2", "row_3", "row_4"]
        def __init__(self, _io, _parent=None, _root=None):
            self._io = _io
            self._parent = _parent
            self._root = _root if _root else self
            self._debug = collections.defaultdict(dict)

        def _read(self):
            self._debug['row_1']['start'] = self._io.pos()
            self.row_1 = Mod153.Vec4(self._io, self, self._root)
            self.row_1._read()
            self._debug['row_1']['end'] = self._io.pos()
            self._debug['row_2']['start'] = self._io.pos()
            self.row_2 = Mod153.Vec4(self._io, self, self._root)
            self.row_2._read()
            self._debug['row_2']['end'] = self._io.pos()
            self._debug['row_3']['start'] = self._io.pos()
            self.row_3 = Mod153.Vec4(self._io, self, self._root)
            self.row_3._read()
            self._debug['row_3']['end'] = self._io.pos()
            self._debug['row_4']['start'] = self._io.pos()
            self.row_4 = Mod153.Vec4(self._io, self, self._root)
            self.row_4._read()
            self._debug['row_4']['end'] = self._io.pos()


    class Material153(KaitaiStruct):
        SEQ_FIELDS = ["fog_enable", "zwrite", "attr", "num", "envmap_bias", "vtype", "uvscroll_enable", "ztest", "func_skin", "func_reserved2", "func_lighting", "func_normalmap", "func_specular", "func_lightmap", "func_multitexture", "func_reserved", "htechnique", "pipeline", "pvdeclbase", "pvdecl", "basemap", "normalmap", "maskmap", "lightmap", "shadowmap", "additionalmap", "envmap", "heightmap", "glossmap", "transparency", "fresnel_factor", "lightmap_factor", "detail_factor", "transmit_factor", "parallax_factor", "blend_state", "alpha_ref", "reserved2"]
        def __init__(self, _io, _parent=None, _root=None):
            self._io = _io
            self._parent = _parent
            self._root = _root if _root else self
            self._debug = collections.defaultdict(dict)

        def _read(self):
            self._debug['fog_enable']['start'] = self._io.pos()
            self.fog_enable = self._io.read_bits_int_le(1) != 0
            self._debug['fog_enable']['end'] = self._io.pos()
            self._debug['zwrite']['start'] = self._io.pos()
            self.zwrite = self._io.read_bits_int_le(1) != 0
            self._debug['zwrite']['end'] = self._io.pos()
            self._debug['attr']['start'] = self._io.pos()
            self.attr = self._io.read_bits_int_le(12)
            self._debug['attr']['end'] = self._io.pos()
            self._debug['num']['start'] = self._io.pos()
            self.num = self._io.read_bits_int_le(8)
            self._debug['num']['end'] = self._io.pos()
            self._debug['envmap_bias']['start'] = self._io.pos()
            self.envmap_bias = self._io.read_bits_int_le(5)
            self._debug['envmap_bias']['end'] = self._io.pos()
            self._debug['vtype']['start'] = self._io.pos()
            self.vtype = self._io.read_bits_int_le(3)
            self._debug['vtype']['end'] = self._io.pos()
            self._debug['uvscroll_enable']['start'] = self._io.pos()
            self.uvscroll_enable = self._io.read_bits_int_le(1) != 0
            self._debug['uvscroll_enable']['end'] = self._io.pos()
            self._debug['ztest']['start'] = self._io.pos()
            self.ztest = self._io.read_bits_int_le(1) != 0
            self._debug['ztest']['end'] = self._io.pos()
            self._debug['func_skin']['start'] = self._io.pos()
            self.func_skin = self._io.read_bits_int_le(4)
            self._debug['func_skin']['end'] = self._io.pos()
            self._debug['func_reserved2']['start'] = self._io.pos()
            self.func_reserved2 = self._io.read_bits_int_le(2)
            self._debug['func_reserved2']['end'] = self._io.pos()
            self._debug['func_lighting']['start'] = self._io.pos()
            self.func_lighting = self._io.read_bits_int_le(4)
            self._debug['func_lighting']['end'] = self._io.pos()
            self._debug['func_normalmap']['start'] = self._io.pos()
            self.func_normalmap = self._io.read_bits_int_le(4)
            self._debug['func_normalmap']['end'] = self._io.pos()
            self._debug['func_specular']['start'] = self._io.pos()
            self.func_specular = self._io.read_bits_int_le(4)
            self._debug['func_specular']['end'] = self._io.pos()
            self._debug['func_lightmap']['start'] = self._io.pos()
            self.func_lightmap = self._io.read_bits_int_le(4)
            self._debug['func_lightmap']['end'] = self._io.pos()
            self._debug['func_multitexture']['start'] = self._io.pos()
            self.func_multitexture = self._io.read_bits_int_le(4)
            self._debug['func_multitexture']['end'] = self._io.pos()
            self._debug['func_reserved']['start'] = self._io.pos()
            self.func_reserved = self._io.read_bits_int_le(6)
            self._debug['func_reserved']['end'] = self._io.pos()
            self._io.align_to_byte()
            self._debug['htechnique']['start'] = self._io.pos()
            self.htechnique = self._io.read_u4le()
            self._debug['htechnique']['end'] = self._io.pos()
            self._debug['pipeline']['start'] = self._io.pos()
            self.pipeline = self._io.read_u4le()
            self._debug['pipeline']['end'] = self._io.pos()
            self._debug['pvdeclbase']['start'] = self._io.pos()
            self.pvdeclbase = self._io.read_u4le()
            self._debug['pvdeclbase']['end'] = self._io.pos()
            self._debug['pvdecl']['start'] = self._io.pos()
            self.pvdecl = self._io.read_u4le()
            self._debug['pvdecl']['end'] = self._io.pos()
            self._debug['basemap']['start'] = self._io.pos()
            self.basemap = self._io.read_u4le()
            self._debug['basemap']['end'] = self._io.pos()
            self._debug['normalmap']['start'] = self._io.pos()
            self.normalmap = self._io.read_u4le()
            self._debug['normalmap']['end'] = self._io.pos()
            self._debug['maskmap']['start'] = self._io.pos()
            self.maskmap = self._io.read_u4le()
            self._debug['maskmap']['end'] = self._io.pos()
            self._debug['lightmap']['start'] = self._io.pos()
            self.lightmap = self._io.read_u4le()
            self._debug['lightmap']['end'] = self._io.pos()
            self._debug['shadowmap']['start'] = self._io.pos()
            self.shadowmap = self._io.read_u4le()
            self._debug['shadowmap']['end'] = self._io.pos()
            self._debug['additionalmap']['start'] = self._io.pos()
            self.additionalmap = self._io.read_u4le()
            self._debug['additionalmap']['end'] = self._io.pos()
            self._debug['envmap']['start'] = self._io.pos()
            self.envmap = self._io.read_u4le()
            self._debug['envmap']['end'] = self._io.pos()
            self._debug['heightmap']['start'] = self._io.pos()
            self.heightmap = self._io.read_u4le()
            self._debug['heightmap']['end'] = self._io.pos()
            self._debug['glossmap']['start'] = self._io.pos()
            self.glossmap = self._io.read_u4le()
            self._debug['glossmap']['end'] = self._io.pos()
            self._debug['transparency']['start'] = self._io.pos()
            self.transparency = self._io.read_f4le()
            self._debug['transparency']['end'] = self._io.pos()
            self._debug['fresnel_factor']['start'] = self._io.pos()
            self.fresnel_factor = []
            for i in range(4):
                if not 'arr' in self._debug['fresnel_factor']:
                    self._debug['fresnel_factor']['arr'] = []
                self._debug['fresnel_factor']['arr'].append({'start': self._io.pos()})
                self.fresnel_factor.append(self._io.read_f4le())
                self._debug['fresnel_factor']['arr'][i]['end'] = self._io.pos()

            self._debug['fresnel_factor']['end'] = self._io.pos()
            self._debug['lightmap_factor']['start'] = self._io.pos()
            self.lightmap_factor = []
            for i in range(4):
                if not 'arr' in self._debug['lightmap_factor']:
                    self._debug['lightmap_factor']['arr'] = []
                self._debug['lightmap_factor']['arr'].append({'start': self._io.pos()})
                self.lightmap_factor.append(self._io.read_f4le())
                self._debug['lightmap_factor']['arr'][i]['end'] = self._io.pos()

            self._debug['lightmap_factor']['end'] = self._io.pos()
            self._debug['detail_factor']['start'] = self._io.pos()
            self.detail_factor = []
            for i in range(4):
                if not 'arr' in self._debug['detail_factor']:
                    self._debug['detail_factor']['arr'] = []
                self._debug['detail_factor']['arr'].append({'start': self._io.pos()})
                self.detail_factor.append(self._io.read_f4le())
                self._debug['detail_factor']['arr'][i]['end'] = self._io.pos()

            self._debug['detail_factor']['end'] = self._io.pos()
            self._debug['transmit_factor']['start'] = self._io.pos()
            self.transmit_factor = []
            for i in range(4):
                if not 'arr' in self._debug['transmit_factor']:
                    self._debug['transmit_factor']['arr'] = []
                self._debug['transmit_factor']['arr'].append({'start': self._io.pos()})
                self.transmit_factor.append(self._io.read_f4le())
                self._debug['transmit_factor']['arr'][i]['end'] = self._io.pos()

            self._debug['transmit_factor']['end'] = self._io.pos()
            self._debug['parallax_factor']['start'] = self._io.pos()
            self.parallax_factor = []
            for i in range(4):
                if not 'arr' in self._debug['parallax_factor']:
                    self._debug['parallax_factor']['arr'] = []
                self._debug['parallax_factor']['arr'].append({'start': self._io.pos()})
                self.parallax_factor.append(self._io.read_f4le())
                self._debug['parallax_factor']['arr'][i]['end'] = self._io.pos()

            self._debug['parallax_factor']['end'] = self._io.pos()
            self._debug['blend_state']['start'] = self._io.pos()
            self.blend_state = self._io.read_u4le()
            self._debug['blend_state']['end'] = self._io.pos()
            self._debug['alpha_ref']['start'] = self._io.pos()
            self.alpha_ref = self._io.read_u4le()
            self._debug['alpha_ref']['end'] = self._io.pos()
            self._debug['reserved2']['start'] = self._io.pos()
            self.reserved2 = []
            for i in range(2):
                if not 'arr' in self._debug['reserved2']:
                    self._debug['reserved2']['arr'] = []
                self._debug['reserved2']['arr'].append({'start': self._io.pos()})
                self.reserved2.append(self._io.read_f4le())
                self._debug['reserved2']['arr'][i]['end'] = self._io.pos()

            self._debug['reserved2']['end'] = self._io.pos()

        @property
        def size_(self):
            if hasattr(self, '_m_size_'):
                return self._m_size_

            self._m_size_ = 160
            return getattr(self, '_m_size_', None)


    class Bone(KaitaiStruct):
        SEQ_FIELDS = ["idx_anim_map", "idx_parent", "idx_mirror", "idx_mapping", "unk_01", "parent_distance", "location"]
        def __init__(self, _io, _parent=None, _root=None):
            self._io = _io
            self._parent = _parent
            self._root = _root if _root else self
            self._debug = collections.defaultdict(dict)

        def _read(self):
            self._debug['idx_anim_map']['start'] = self._io.pos()
            self.idx_anim_map = self._io.read_u1()
            self._debug['idx_anim_map']['end'] = self._io.pos()
            self._debug['idx_parent']['start'] = self._io.pos()
            self.idx_parent = self._io.read_u1()
            self._debug['idx_parent']['end'] = self._io.pos()
            self._debug['idx_mirror']['start'] = self._io.pos()
            self.idx_mirror = self._io.read_u1()
            self._debug['idx_mirror']['end'] = self._io.pos()
            self._debug['idx_mapping']['start'] = self._io.pos()
            self.idx_mapping = self._io.read_u1()
            self._debug['idx_mapping']['end'] = self._io.pos()
            self._debug['unk_01']['start'] = self._io.pos()
            self.unk_01 = self._io.read_f4le()
            self._debug['unk_01']['end'] = self._io.pos()
            self._debug['parent_distance']['start'] = self._io.pos()
            self.parent_distance = self._io.read_f4le()
            self._debug['parent_distance']['end'] = self._io.pos()
            self._debug['location']['start'] = self._io.pos()
            self.location = Mod153.Vec3(self._io, self, self._root)
            self.location._read()
            self._debug['location']['end'] = self._io.pos()

        @property
        def size_(self):
            if hasattr(self, '_m_size_'):
                return self._m_size_

            self._m_size_ = 24
            return getattr(self, '_m_size_', None)


    class Vertex0(KaitaiStruct):
        SEQ_FIELDS = ["position", "normal", "tangent", "uv", "uv2", "uv3"]
        def __init__(self, _io, _parent=None, _root=None):
            self._io = _io
            self._parent = _parent
            self._root = _root if _root else self
            self._debug = collections.defaultdict(dict)

        def _read(self):
            self._debug['position']['start'] = self._io.pos()
            self.position = Mod153.Vec3(self._io, self, self._root)
            self.position._read()
            self._debug['position']['end'] = self._io.pos()
            self._debug['normal']['start'] = self._io.pos()
            self.normal = Mod153.Vec4U1(self._io, self, self._root)
            self.normal._read()
            self._debug['normal']['end'] = self._io.pos()
            self._debug['tangent']['start'] = self._io.pos()
            self.tangent = Mod153.Vec4U1(self._io, self, self._root)
            self.tangent._read()
            self._debug['tangent']['end'] = self._io.pos()
            self._debug['uv']['start'] = self._io.pos()
            self.uv = Mod153.Vec2HalfFloat(self._io, self, self._root)
            self.uv._read()
            self._debug['uv']['end'] = self._io.pos()
            self._debug['uv2']['start'] = self._io.pos()
            self.uv2 = Mod153.Vec2HalfFloat(self._io, self, self._root)
            self.uv2._read()
            self._debug['uv2']['end'] = self._io.pos()
            self._debug['uv3']['start'] = self._io.pos()
            self.uv3 = Mod153.Vec2HalfFloat(self._io, self, self._root)
            self.uv3._read()
            self._debug['uv3']['end'] = self._io.pos()


    class ModelInfo(KaitaiStruct):
        SEQ_FIELDS = ["middist", "lowdist", "light_group", "strip_type", "memory", "reserved"]
        def __init__(self, _io, _parent=None, _root=None):
            self._io = _io
            self._parent = _parent
            self._root = _root if _root else self
            self._debug = collections.defaultdict(dict)

        def _read(self):
            self._debug['middist']['start'] = self._io.pos()
            self.middist = self._io.read_s4le()
            self._debug['middist']['end'] = self._io.pos()
            self._debug['lowdist']['start'] = self._io.pos()
            self.lowdist = self._io.read_s4le()
            self._debug['lowdist']['end'] = self._io.pos()
            self._debug['light_group']['start'] = self._io.pos()
            self.light_group = self._io.read_u4le()
            self._debug['light_group']['end'] = self._io.pos()
            self._debug['strip_type']['start'] = self._io.pos()
            self.strip_type = self._io.read_u1()
            self._debug['strip_type']['end'] = self._io.pos()
            self._debug['memory']['start'] = self._io.pos()
            self.memory = self._io.read_u1()
            self._debug['memory']['end'] = self._io.pos()
            self._debug['reserved']['start'] = self._io.pos()
            self.reserved = self._io.read_u2le()
            self._debug['reserved']['end'] = self._io.pos()

        @property
        def size_(self):
            if hasattr(self, '_m_size_'):
                return self._m_size_

            self._m_size_ = 16
            return getattr(self, '_m_size_', None)


    class Vec2(KaitaiStruct):
        SEQ_FIELDS = ["x", "y"]
        def __init__(self, _io, _parent=None, _root=None):
            self._io = _io
            self._parent = _parent
            self._root = _root if _root else self
            self._debug = collections.defaultdict(dict)

        def _read(self):
            self._debug['x']['start'] = self._io.pos()
            self.x = self._io.read_f4le()
            self._debug['x']['end'] = self._io.pos()
            self._debug['y']['start'] = self._io.pos()
            self.y = self._io.read_f4le()
            self._debug['y']['end'] = self._io.pos()


    class Vec4U1(KaitaiStruct):
        SEQ_FIELDS = ["x", "y", "z", "w"]
        def __init__(self, _io, _parent=None, _root=None):
            self._io = _io
            self._parent = _parent
            self._root = _root if _root else self
            self._debug = collections.defaultdict(dict)

        def _read(self):
            self._debug['x']['start'] = self._io.pos()
            self.x = self._io.read_u1()
            self._debug['x']['end'] = self._io.pos()
            self._debug['y']['start'] = self._io.pos()
            self.y = self._io.read_u1()
            self._debug['y']['end'] = self._io.pos()
            self._debug['z']['start'] = self._io.pos()
            self.z = self._io.read_u1()
            self._debug['z']['end'] = self._io.pos()
            self._debug['w']['start'] = self._io.pos()
            self.w = self._io.read_u1()
            self._debug['w']['end'] = self._io.pos()


    class MeshesData(KaitaiStruct):
        SEQ_FIELDS = ["meshes", "num_weight_bounds", "weight_bounds"]
        def __init__(self, _io, _parent=None, _root=None):
            self._io = _io
            self._parent = _parent
            self._root = _root if _root else self
            self._debug = collections.defaultdict(dict)

        def _read(self):
            self._debug['meshes']['start'] = self._io.pos()
            self.meshes = []
            for i in range(self._root.header.num_meshes):
                if not 'arr' in self._debug['meshes']:
                    self._debug['meshes']['arr'] = []
                self._debug['meshes']['arr'].append({'start': self._io.pos()})
                _t_meshes = Mod153.Mesh(self._io, self, self._root)
                _t_meshes._read()
                self.meshes.append(_t_meshes)
                self._debug['meshes']['arr'][i]['end'] = self._io.pos()

            self._debug['meshes']['end'] = self._io.pos()
            self._debug['num_weight_bounds']['start'] = self._io.pos()
            self.num_weight_bounds = self._io.read_u4le()
            self._debug['num_weight_bounds']['end'] = self._io.pos()
            self._debug['weight_bounds']['start'] = self._io.pos()
            self.weight_bounds = []
            for i in range(self.num_weight_bounds):
                if not 'arr' in self._debug['weight_bounds']:
                    self._debug['weight_bounds']['arr'] = []
                self._debug['weight_bounds']['arr'].append({'start': self._io.pos()})
                _t_weight_bounds = Mod153.WeightBound(self._io, self, self._root)
                _t_weight_bounds._read()
                self.weight_bounds.append(_t_weight_bounds)
                self._debug['weight_bounds']['arr'][i]['end'] = self._io.pos()

            self._debug['weight_bounds']['end'] = self._io.pos()

        @property
        def size_(self):
            if hasattr(self, '_m_size_'):
                return self._m_size_

            self._m_size_ = (((self._root.header.num_meshes * self.meshes[0].size_) + 4) + (self.num_weight_bounds * self.weight_bounds[0].size_))
            return getattr(self, '_m_size_', None)


    class Mesh(KaitaiStruct):
        SEQ_FIELDS = ["idx_group", "idx_material", "disp", "level_of_detail", "alpha_priority", "vertex_format", "vertex_stride", "vertex_stride_2", "connective", "shape", "env", "refrect", "reserved2", "shadow_cast", "shadow_receive", "sort", "num_vertices", "vertex_position_end", "vertex_position_2", "vertex_offset", "vertex_offset_2", "face_position", "num_indices", "face_offset", "vdeclbase", "vdecl", "vertex_position", "num_weight_bounds", "idx_bone_palette", "rcn_base", "boundary"]
        def __init__(self, _io, _parent=None, _root=None):
            self._io = _io
            self._parent = _parent
            self._root = _root if _root else self
            self._debug = collections.defaultdict(dict)

        def _read(self):
            self._debug['idx_group']['start'] = self._io.pos()
            self.idx_group = self._io.read_u2le()
            self._debug['idx_group']['end'] = self._io.pos()
            self._debug['idx_material']['start'] = self._io.pos()
            self.idx_material = self._io.read_u2le()
            self._debug['idx_material']['end'] = self._io.pos()
            self._debug['disp']['start'] = self._io.pos()
            self.disp = self._io.read_u1()
            self._debug['disp']['end'] = self._io.pos()
            self._debug['level_of_detail']['start'] = self._io.pos()
            self.level_of_detail = self._io.read_u1()
            self._debug['level_of_detail']['end'] = self._io.pos()
            self._debug['alpha_priority']['start'] = self._io.pos()
            self.alpha_priority = self._io.read_u1()
            self._debug['alpha_priority']['end'] = self._io.pos()
            self._debug['vertex_format']['start'] = self._io.pos()
            self.vertex_format = self._io.read_u1()
            self._debug['vertex_format']['end'] = self._io.pos()
            self._debug['vertex_stride']['start'] = self._io.pos()
            self.vertex_stride = self._io.read_u1()
            self._debug['vertex_stride']['end'] = self._io.pos()
            self._debug['vertex_stride_2']['start'] = self._io.pos()
            self.vertex_stride_2 = self._io.read_u1()
            self._debug['vertex_stride_2']['end'] = self._io.pos()
            self._debug['connective']['start'] = self._io.pos()
            self.connective = self._io.read_u1()
            self._debug['connective']['end'] = self._io.pos()
            self._debug['shape']['start'] = self._io.pos()
            self.shape = self._io.read_bits_int_le(1) != 0
            self._debug['shape']['end'] = self._io.pos()
            self._debug['env']['start'] = self._io.pos()
            self.env = self._io.read_bits_int_le(1) != 0
            self._debug['env']['end'] = self._io.pos()
            self._debug['refrect']['start'] = self._io.pos()
            self.refrect = self._io.read_bits_int_le(1) != 0
            self._debug['refrect']['end'] = self._io.pos()
            self._debug['reserved2']['start'] = self._io.pos()
            self.reserved2 = self._io.read_bits_int_le(2)
            self._debug['reserved2']['end'] = self._io.pos()
            self._debug['shadow_cast']['start'] = self._io.pos()
            self.shadow_cast = self._io.read_bits_int_le(1) != 0
            self._debug['shadow_cast']['end'] = self._io.pos()
            self._debug['shadow_receive']['start'] = self._io.pos()
            self.shadow_receive = self._io.read_bits_int_le(1) != 0
            self._debug['shadow_receive']['end'] = self._io.pos()
            self._debug['sort']['start'] = self._io.pos()
            self.sort = self._io.read_bits_int_le(1) != 0
            self._debug['sort']['end'] = self._io.pos()
            self._io.align_to_byte()
            self._debug['num_vertices']['start'] = self._io.pos()
            self.num_vertices = self._io.read_u2le()
            self._debug['num_vertices']['end'] = self._io.pos()
            self._debug['vertex_position_end']['start'] = self._io.pos()
            self.vertex_position_end = self._io.read_u2le()
            self._debug['vertex_position_end']['end'] = self._io.pos()
            self._debug['vertex_position_2']['start'] = self._io.pos()
            self.vertex_position_2 = self._io.read_u4le()
            self._debug['vertex_position_2']['end'] = self._io.pos()
            self._debug['vertex_offset']['start'] = self._io.pos()
            self.vertex_offset = self._io.read_u4le()
            self._debug['vertex_offset']['end'] = self._io.pos()
            self._debug['vertex_offset_2']['start'] = self._io.pos()
            self.vertex_offset_2 = self._io.read_u4le()
            self._debug['vertex_offset_2']['end'] = self._io.pos()
            self._debug['face_position']['start'] = self._io.pos()
            self.face_position = self._io.read_u4le()
            self._debug['face_position']['end'] = self._io.pos()
            self._debug['num_indices']['start'] = self._io.pos()
            self.num_indices = self._io.read_u4le()
            self._debug['num_indices']['end'] = self._io.pos()
            self._debug['face_offset']['start'] = self._io.pos()
            self.face_offset = self._io.read_u4le()
            self._debug['face_offset']['end'] = self._io.pos()
            self._debug['vdeclbase']['start'] = self._io.pos()
            self.vdeclbase = self._io.read_u1()
            self._debug['vdeclbase']['end'] = self._io.pos()
            self._debug['vdecl']['start'] = self._io.pos()
            self.vdecl = self._io.read_u1()
            self._debug['vdecl']['end'] = self._io.pos()
            self._debug['vertex_position']['start'] = self._io.pos()
            self.vertex_position = self._io.read_u2le()
            self._debug['vertex_position']['end'] = self._io.pos()
            self._debug['num_weight_bounds']['start'] = self._io.pos()
            self.num_weight_bounds = self._io.read_u1()
            self._debug['num_weight_bounds']['end'] = self._io.pos()
            self._debug['idx_bone_palette']['start'] = self._io.pos()
            self.idx_bone_palette = self._io.read_u1()
            self._debug['idx_bone_palette']['end'] = self._io.pos()
            self._debug['rcn_base']['start'] = self._io.pos()
            self.rcn_base = self._io.read_u2le()
            self._debug['rcn_base']['end'] = self._io.pos()
            self._debug['boundary']['start'] = self._io.pos()
            self.boundary = self._io.read_u4le()
            self._debug['boundary']['end'] = self._io.pos()

        @property
        def size_(self):
            if hasattr(self, '_m_size_'):
                return self._m_size_

            self._m_size_ = 52
            return getattr(self, '_m_size_', None)

        @property
        def indices(self):
            if hasattr(self, '_m_indices'):
                return self._m_indices

            _pos = self._io.pos()
            self._io.seek(((self._root.header.offset_index_buffer + (self.face_offset * 2)) + (self.face_position * 2)))
            self._debug['_m_indices']['start'] = self._io.pos()
            self._m_indices = []
            for i in range(self.num_indices):
                if not 'arr' in self._debug['_m_indices']:
                    self._debug['_m_indices']['arr'] = []
                self._debug['_m_indices']['arr'].append({'start': self._io.pos()})
                self._m_indices.append(self._io.read_u2le())
                self._debug['_m_indices']['arr'][i]['end'] = self._io.pos()

            self._debug['_m_indices']['end'] = self._io.pos()
            self._io.seek(_pos)
            return getattr(self, '_m_indices', None)

        @property
        def vertices(self):
            if hasattr(self, '_m_vertices'):
                return self._m_vertices

            _pos = self._io.pos()
            self._io.seek((((self._root.header.offset_vertex_buffer + (self.vertex_position * self.vertex_stride)) + self.vertex_offset) if self.vertex_position > self.vertex_position_2 else ((self._root.header.offset_vertex_buffer + (self.vertex_position * self.vertex_stride)) + self.vertex_offset)))
            self._debug['_m_vertices']['start'] = self._io.pos()
            self._m_vertices = []
            for i in range((((self.vertex_position_end - self.vertex_position) + 1) if self.vertex_position > self.vertex_position_2 else self.num_vertices)):
                if not 'arr' in self._debug['_m_vertices']:
                    self._debug['_m_vertices']['arr'] = []
                self._debug['_m_vertices']['arr'].append({'start': self._io.pos()})
                _on = self.vertex_format
                if _on == 0:
                    if not 'arr' in self._debug['_m_vertices']:
                        self._debug['_m_vertices']['arr'] = []
                    self._debug['_m_vertices']['arr'].append({'start': self._io.pos()})
                    _t__m_vertices = Mod153.Vertex0(self._io, self, self._root)
                    _t__m_vertices._read()
                    self._m_vertices.append(_t__m_vertices)
                    self._debug['_m_vertices']['arr'][i]['end'] = self._io.pos()
                elif _on == 4:
                    if not 'arr' in self._debug['_m_vertices']:
                        self._debug['_m_vertices']['arr'] = []
                    self._debug['_m_vertices']['arr'].append({'start': self._io.pos()})
                    _t__m_vertices = Mod153.Vertex(self._io, self, self._root)
                    _t__m_vertices._read()
                    self._m_vertices.append(_t__m_vertices)
                    self._debug['_m_vertices']['arr'][i]['end'] = self._io.pos()
                elif _on == 6:
                    if not 'arr' in self._debug['_m_vertices']:
                        self._debug['_m_vertices']['arr'] = []
                    self._debug['_m_vertices']['arr'].append({'start': self._io.pos()})
                    _t__m_vertices = Mod153.Vertex5(self._io, self, self._root)
                    _t__m_vertices._read()
                    self._m_vertices.append(_t__m_vertices)
                    self._debug['_m_vertices']['arr'][i]['end'] = self._io.pos()
                elif _on == 7:
                    if not 'arr' in self._debug['_m_vertices']:
                        self._debug['_m_vertices']['arr'] = []
                    self._debug['_m_vertices']['arr'].append({'start': self._io.pos()})
                    _t__m_vertices = Mod153.Vertex5(self._io, self, self._root)
                    _t__m_vertices._read()
                    self._m_vertices.append(_t__m_vertices)
                    self._debug['_m_vertices']['arr'][i]['end'] = self._io.pos()
                elif _on == 1:
                    if not 'arr' in self._debug['_m_vertices']:
                        self._debug['_m_vertices']['arr'] = []
                    self._debug['_m_vertices']['arr'].append({'start': self._io.pos()})
                    _t__m_vertices = Mod153.Vertex(self._io, self, self._root)
                    _t__m_vertices._read()
                    self._m_vertices.append(_t__m_vertices)
                    self._debug['_m_vertices']['arr'][i]['end'] = self._io.pos()
                elif _on == 3:
                    if not 'arr' in self._debug['_m_vertices']:
                        self._debug['_m_vertices']['arr'] = []
                    self._debug['_m_vertices']['arr'].append({'start': self._io.pos()})
                    _t__m_vertices = Mod153.Vertex(self._io, self, self._root)
                    _t__m_vertices._read()
                    self._m_vertices.append(_t__m_vertices)
                    self._debug['_m_vertices']['arr'][i]['end'] = self._io.pos()
                elif _on == 5:
                    if not 'arr' in self._debug['_m_vertices']:
                        self._debug['_m_vertices']['arr'] = []
                    self._debug['_m_vertices']['arr'].append({'start': self._io.pos()})
                    _t__m_vertices = Mod153.Vertex5(self._io, self, self._root)
                    _t__m_vertices._read()
                    self._m_vertices.append(_t__m_vertices)
                    self._debug['_m_vertices']['arr'][i]['end'] = self._io.pos()
                elif _on == 8:
                    if not 'arr' in self._debug['_m_vertices']:
                        self._debug['_m_vertices']['arr'] = []
                    self._debug['_m_vertices']['arr'].append({'start': self._io.pos()})
                    _t__m_vertices = Mod153.Vertex5(self._io, self, self._root)
                    _t__m_vertices._read()
                    self._m_vertices.append(_t__m_vertices)
                    self._debug['_m_vertices']['arr'][i]['end'] = self._io.pos()
                elif _on == 2:
                    if not 'arr' in self._debug['_m_vertices']:
                        self._debug['_m_vertices']['arr'] = []
                    self._debug['_m_vertices']['arr'].append({'start': self._io.pos()})
                    _t__m_vertices = Mod153.Vertex(self._io, self, self._root)
                    _t__m_vertices._read()
                    self._m_vertices.append(_t__m_vertices)
                    self._debug['_m_vertices']['arr'][i]['end'] = self._io.pos()
                self._debug['_m_vertices']['arr'][i]['end'] = self._io.pos()

            self._debug['_m_vertices']['end'] = self._io.pos()
            self._io.seek(_pos)
            return getattr(self, '_m_vertices', None)

        @property
        def vertices2(self):
            if hasattr(self, '_m_vertices2'):
                return self._m_vertices2

            if self.vertex_stride_2 > 0:
                _pos = self._io.pos()
                self._io.seek(((self._root.header.offset_vertex_buffer_2 + (self.vertex_position_2 * self.vertex_stride_2)) + self.vertex_offset_2))
                self._debug['_m_vertices2']['start'] = self._io.pos()
                self._m_vertices2 = []
                for i in range(self.num_vertices):
                    if not 'arr' in self._debug['_m_vertices2']:
                        self._debug['_m_vertices2']['arr'] = []
                    self._debug['_m_vertices2']['arr'].append({'start': self._io.pos()})
                    _on = self.vertex_stride_2
                    if _on == 4:
                        if not 'arr' in self._debug['_m_vertices2']:
                            self._debug['_m_vertices2']['arr'] = []
                        self._debug['_m_vertices2']['arr'].append({'start': self._io.pos()})
                        _t__m_vertices2 = Mod153.Vertex24(self._io, self, self._root)
                        _t__m_vertices2._read()
                        self._m_vertices2.append(_t__m_vertices2)
                        self._debug['_m_vertices2']['arr'][i]['end'] = self._io.pos()
                    elif _on == 8:
                        if not 'arr' in self._debug['_m_vertices2']:
                            self._debug['_m_vertices2']['arr'] = []
                        self._debug['_m_vertices2']['arr'].append({'start': self._io.pos()})
                        _t__m_vertices2 = Mod153.Vertex28(self._io, self, self._root)
                        _t__m_vertices2._read()
                        self._m_vertices2.append(_t__m_vertices2)
                        self._debug['_m_vertices2']['arr'][i]['end'] = self._io.pos()
                    self._debug['_m_vertices2']['arr'][i]['end'] = self._io.pos()

                self._debug['_m_vertices2']['end'] = self._io.pos()
                self._io.seek(_pos)

            return getattr(self, '_m_vertices2', None)


    class RcnTable(KaitaiStruct):
        SEQ_FIELDS = ["vindex", "noffset", "edge"]
        def __init__(self, _io, _parent=None, _root=None):
            self._io = _io
            self._parent = _parent
            self._root = _root if _root else self
            self._debug = collections.defaultdict(dict)

        def _read(self):
            self._debug['vindex']['start'] = self._io.pos()
            self.vindex = self._io.read_bits_int_le(21)
            self._debug['vindex']['end'] = self._io.pos()
            self._debug['noffset']['start'] = self._io.pos()
            self.noffset = self._io.read_bits_int_le(10)
            self._debug['noffset']['end'] = self._io.pos()
            self._debug['edge']['start'] = self._io.pos()
            self.edge = self._io.read_bits_int_le(1) != 0
            self._debug['edge']['end'] = self._io.pos()


    class WeightBound(KaitaiStruct):
        SEQ_FIELDS = ["bone_id", "unk_01", "bsphere", "bbox_min", "bbox_max", "oabb", "oabb_dimension"]
        def __init__(self, _io, _parent=None, _root=None):
            self._io = _io
            self._parent = _parent
            self._root = _root if _root else self
            self._debug = collections.defaultdict(dict)

        def _read(self):
            self._debug['bone_id']['start'] = self._io.pos()
            self.bone_id = self._io.read_u4le()
            self._debug['bone_id']['end'] = self._io.pos()
            self._debug['unk_01']['start'] = self._io.pos()
            self.unk_01 = Mod153.Vec3(self._io, self, self._root)
            self.unk_01._read()
            self._debug['unk_01']['end'] = self._io.pos()
            self._debug['bsphere']['start'] = self._io.pos()
            self.bsphere = Mod153.Vec4(self._io, self, self._root)
            self.bsphere._read()
            self._debug['bsphere']['end'] = self._io.pos()
            self._debug['bbox_min']['start'] = self._io.pos()
            self.bbox_min = Mod153.Vec4(self._io, self, self._root)
            self.bbox_min._read()
            self._debug['bbox_min']['end'] = self._io.pos()
            self._debug['bbox_max']['start'] = self._io.pos()
            self.bbox_max = Mod153.Vec4(self._io, self, self._root)
            self.bbox_max._read()
            self._debug['bbox_max']['end'] = self._io.pos()
            self._debug['oabb']['start'] = self._io.pos()
            self.oabb = Mod153.Matrix4x4(self._io, self, self._root)
            self.oabb._read()
            self._debug['oabb']['end'] = self._io.pos()
            self._debug['oabb_dimension']['start'] = self._io.pos()
            self.oabb_dimension = Mod153.Vec4(self._io, self, self._root)
            self.oabb_dimension._read()
            self._debug['oabb_dimension']['end'] = self._io.pos()

        @property
        def size_(self):
            if hasattr(self, '_m_size_'):
                return self._m_size_

            self._m_size_ = 144
            return getattr(self, '_m_size_', None)


    class Vec3(KaitaiStruct):
        SEQ_FIELDS = ["x", "y", "z"]
        def __init__(self, _io, _parent=None, _root=None):
            self._io = _io
            self._parent = _parent
            self._root = _root if _root else self
            self._debug = collections.defaultdict(dict)

        def _read(self):
            self._debug['x']['start'] = self._io.pos()
            self.x = self._io.read_f4le()
            self._debug['x']['end'] = self._io.pos()
            self._debug['y']['start'] = self._io.pos()
            self.y = self._io.read_f4le()
            self._debug['y']['end'] = self._io.pos()
            self._debug['z']['start'] = self._io.pos()
            self.z = self._io.read_f4le()
            self._debug['z']['end'] = self._io.pos()


    class RcnVertex(KaitaiStruct):
        SEQ_FIELDS = ["x", "y", "z", "w", "w0", "w1", "w2", "w3", "j0", "j1", "j2", "j3"]
        def __init__(self, _io, _parent=None, _root=None):
            self._io = _io
            self._parent = _parent
            self._root = _root if _root else self
            self._debug = collections.defaultdict(dict)

        def _read(self):
            self._debug['x']['start'] = self._io.pos()
            self.x = self._io.read_u2le()
            self._debug['x']['end'] = self._io.pos()
            self._debug['y']['start'] = self._io.pos()
            self.y = self._io.read_u2le()
            self._debug['y']['end'] = self._io.pos()
            self._debug['z']['start'] = self._io.pos()
            self.z = self._io.read_u2le()
            self._debug['z']['end'] = self._io.pos()
            self._debug['w']['start'] = self._io.pos()
            self.w = self._io.read_u2le()
            self._debug['w']['end'] = self._io.pos()
            self._debug['w0']['start'] = self._io.pos()
            self.w0 = self._io.read_u1()
            self._debug['w0']['end'] = self._io.pos()
            self._debug['w1']['start'] = self._io.pos()
            self.w1 = self._io.read_u1()
            self._debug['w1']['end'] = self._io.pos()
            self._debug['w2']['start'] = self._io.pos()
            self.w2 = self._io.read_u1()
            self._debug['w2']['end'] = self._io.pos()
            self._debug['w3']['start'] = self._io.pos()
            self.w3 = self._io.read_u1()
            self._debug['w3']['end'] = self._io.pos()
            self._debug['j0']['start'] = self._io.pos()
            self.j0 = self._io.read_u1()
            self._debug['j0']['end'] = self._io.pos()
            self._debug['j1']['start'] = self._io.pos()
            self.j1 = self._io.read_u1()
            self._debug['j1']['end'] = self._io.pos()
            self._debug['j2']['start'] = self._io.pos()
            self.j2 = self._io.read_u1()
            self._debug['j2']['end'] = self._io.pos()
            self._debug['j3']['start'] = self._io.pos()
            self.j3 = self._io.read_u1()
            self._debug['j3']['end'] = self._io.pos()


    class Material156(KaitaiStruct):
        SEQ_FIELDS = ["fog_enable", "zwrite", "attr", "num", "envmap_bias", "vtype", "uvscroll_enable", "ztest", "func_skin", "func_reserved2", "func_lighting", "func_normalmap", "func_specular", "func_lightmap", "func_multitexture", "func_reserved", "htechnique", "pipeline", "pvdeclbase", "pvdecl", "basemap", "normalmap", "maskmap", "lightmap", "shadowmap", "additionalmap", "envmap", "detailmap", "occlusionmap", "transparency", "fresnel_factor", "lightmap_factor", "detail_factor", "reserved1", "reserved2", "lightblendmap", "shadowblendmap", "parallax_factor", "flip_binormal", "heightmap_occ", "blend_state", "alpha_ref", "heightmap", "glossmap"]
        def __init__(self, _io, _parent=None, _root=None):
            self._io = _io
            self._parent = _parent
            self._root = _root if _root else self
            self._debug = collections.defaultdict(dict)

        def _read(self):
            self._debug['fog_enable']['start'] = self._io.pos()
            self.fog_enable = self._io.read_bits_int_le(1) != 0
            self._debug['fog_enable']['end'] = self._io.pos()
            self._debug['zwrite']['start'] = self._io.pos()
            self.zwrite = self._io.read_bits_int_le(1) != 0
            self._debug['zwrite']['end'] = self._io.pos()
            self._debug['attr']['start'] = self._io.pos()
            self.attr = self._io.read_bits_int_le(12)
            self._debug['attr']['end'] = self._io.pos()
            self._debug['num']['start'] = self._io.pos()
            self.num = self._io.read_bits_int_le(8)
            self._debug['num']['end'] = self._io.pos()
            self._debug['envmap_bias']['start'] = self._io.pos()
            self.envmap_bias = self._io.read_bits_int_le(5)
            self._debug['envmap_bias']['end'] = self._io.pos()
            self._debug['vtype']['start'] = self._io.pos()
            self.vtype = self._io.read_bits_int_le(3)
            self._debug['vtype']['end'] = self._io.pos()
            self._debug['uvscroll_enable']['start'] = self._io.pos()
            self.uvscroll_enable = self._io.read_bits_int_le(1) != 0
            self._debug['uvscroll_enable']['end'] = self._io.pos()
            self._debug['ztest']['start'] = self._io.pos()
            self.ztest = self._io.read_bits_int_le(1) != 0
            self._debug['ztest']['end'] = self._io.pos()
            self._debug['func_skin']['start'] = self._io.pos()
            self.func_skin = self._io.read_bits_int_le(4)
            self._debug['func_skin']['end'] = self._io.pos()
            self._debug['func_reserved2']['start'] = self._io.pos()
            self.func_reserved2 = self._io.read_bits_int_le(2)
            self._debug['func_reserved2']['end'] = self._io.pos()
            self._debug['func_lighting']['start'] = self._io.pos()
            self.func_lighting = self._io.read_bits_int_le(4)
            self._debug['func_lighting']['end'] = self._io.pos()
            self._debug['func_normalmap']['start'] = self._io.pos()
            self.func_normalmap = self._io.read_bits_int_le(4)
            self._debug['func_normalmap']['end'] = self._io.pos()
            self._debug['func_specular']['start'] = self._io.pos()
            self.func_specular = self._io.read_bits_int_le(4)
            self._debug['func_specular']['end'] = self._io.pos()
            self._debug['func_lightmap']['start'] = self._io.pos()
            self.func_lightmap = self._io.read_bits_int_le(4)
            self._debug['func_lightmap']['end'] = self._io.pos()
            self._debug['func_multitexture']['start'] = self._io.pos()
            self.func_multitexture = self._io.read_bits_int_le(4)
            self._debug['func_multitexture']['end'] = self._io.pos()
            self._debug['func_reserved']['start'] = self._io.pos()
            self.func_reserved = self._io.read_bits_int_le(6)
            self._debug['func_reserved']['end'] = self._io.pos()
            self._io.align_to_byte()
            self._debug['htechnique']['start'] = self._io.pos()
            self.htechnique = self._io.read_u4le()
            self._debug['htechnique']['end'] = self._io.pos()
            self._debug['pipeline']['start'] = self._io.pos()
            self.pipeline = self._io.read_u4le()
            self._debug['pipeline']['end'] = self._io.pos()
            self._debug['pvdeclbase']['start'] = self._io.pos()
            self.pvdeclbase = self._io.read_u4le()
            self._debug['pvdeclbase']['end'] = self._io.pos()
            self._debug['pvdecl']['start'] = self._io.pos()
            self.pvdecl = self._io.read_u4le()
            self._debug['pvdecl']['end'] = self._io.pos()
            self._debug['basemap']['start'] = self._io.pos()
            self.basemap = self._io.read_u4le()
            self._debug['basemap']['end'] = self._io.pos()
            self._debug['normalmap']['start'] = self._io.pos()
            self.normalmap = self._io.read_u4le()
            self._debug['normalmap']['end'] = self._io.pos()
            self._debug['maskmap']['start'] = self._io.pos()
            self.maskmap = self._io.read_u4le()
            self._debug['maskmap']['end'] = self._io.pos()
            self._debug['lightmap']['start'] = self._io.pos()
            self.lightmap = self._io.read_u4le()
            self._debug['lightmap']['end'] = self._io.pos()
            self._debug['shadowmap']['start'] = self._io.pos()
            self.shadowmap = self._io.read_u4le()
            self._debug['shadowmap']['end'] = self._io.pos()
            self._debug['additionalmap']['start'] = self._io.pos()
            self.additionalmap = self._io.read_u4le()
            self._debug['additionalmap']['end'] = self._io.pos()
            self._debug['envmap']['start'] = self._io.pos()
            self.envmap = self._io.read_u4le()
            self._debug['envmap']['end'] = self._io.pos()
            self._debug['detailmap']['start'] = self._io.pos()
            self.detailmap = self._io.read_u4le()
            self._debug['detailmap']['end'] = self._io.pos()
            self._debug['occlusionmap']['start'] = self._io.pos()
            self.occlusionmap = self._io.read_u4le()
            self._debug['occlusionmap']['end'] = self._io.pos()
            self._debug['transparency']['start'] = self._io.pos()
            self.transparency = self._io.read_f4le()
            self._debug['transparency']['end'] = self._io.pos()
            self._debug['fresnel_factor']['start'] = self._io.pos()
            self.fresnel_factor = []
            for i in range(4):
                if not 'arr' in self._debug['fresnel_factor']:
                    self._debug['fresnel_factor']['arr'] = []
                self._debug['fresnel_factor']['arr'].append({'start': self._io.pos()})
                self.fresnel_factor.append(self._io.read_f4le())
                self._debug['fresnel_factor']['arr'][i]['end'] = self._io.pos()

            self._debug['fresnel_factor']['end'] = self._io.pos()
            self._debug['lightmap_factor']['start'] = self._io.pos()
            self.lightmap_factor = []
            for i in range(4):
                if not 'arr' in self._debug['lightmap_factor']:
                    self._debug['lightmap_factor']['arr'] = []
                self._debug['lightmap_factor']['arr'].append({'start': self._io.pos()})
                self.lightmap_factor.append(self._io.read_f4le())
                self._debug['lightmap_factor']['arr'][i]['end'] = self._io.pos()

            self._debug['lightmap_factor']['end'] = self._io.pos()
            self._debug['detail_factor']['start'] = self._io.pos()
            self.detail_factor = []
            for i in range(4):
                if not 'arr' in self._debug['detail_factor']:
                    self._debug['detail_factor']['arr'] = []
                self._debug['detail_factor']['arr'].append({'start': self._io.pos()})
                self.detail_factor.append(self._io.read_f4le())
                self._debug['detail_factor']['arr'][i]['end'] = self._io.pos()

            self._debug['detail_factor']['end'] = self._io.pos()
            self._debug['reserved1']['start'] = self._io.pos()
            self.reserved1 = self._io.read_u4le()
            self._debug['reserved1']['end'] = self._io.pos()
            self._debug['reserved2']['start'] = self._io.pos()
            self.reserved2 = self._io.read_u4le()
            self._debug['reserved2']['end'] = self._io.pos()
            self._debug['lightblendmap']['start'] = self._io.pos()
            self.lightblendmap = self._io.read_u4le()
            self._debug['lightblendmap']['end'] = self._io.pos()
            self._debug['shadowblendmap']['start'] = self._io.pos()
            self.shadowblendmap = self._io.read_u4le()
            self._debug['shadowblendmap']['end'] = self._io.pos()
            self._debug['parallax_factor']['start'] = self._io.pos()
            self.parallax_factor = []
            for i in range(2):
                if not 'arr' in self._debug['parallax_factor']:
                    self._debug['parallax_factor']['arr'] = []
                self._debug['parallax_factor']['arr'].append({'start': self._io.pos()})
                self.parallax_factor.append(self._io.read_f4le())
                self._debug['parallax_factor']['arr'][i]['end'] = self._io.pos()

            self._debug['parallax_factor']['end'] = self._io.pos()
            self._debug['flip_binormal']['start'] = self._io.pos()
            self.flip_binormal = self._io.read_f4le()
            self._debug['flip_binormal']['end'] = self._io.pos()
            self._debug['heightmap_occ']['start'] = self._io.pos()
            self.heightmap_occ = self._io.read_f4le()
            self._debug['heightmap_occ']['end'] = self._io.pos()
            self._debug['blend_state']['start'] = self._io.pos()
            self.blend_state = self._io.read_u4le()
            self._debug['blend_state']['end'] = self._io.pos()
            self._debug['alpha_ref']['start'] = self._io.pos()
            self.alpha_ref = self._io.read_u4le()
            self._debug['alpha_ref']['end'] = self._io.pos()
            self._debug['heightmap']['start'] = self._io.pos()
            self.heightmap = self._io.read_u4le()
            self._debug['heightmap']['end'] = self._io.pos()
            self._debug['glossmap']['start'] = self._io.pos()
            self.glossmap = self._io.read_u4le()
            self._debug['glossmap']['end'] = self._io.pos()

        @property
        def size_(self):
            if hasattr(self, '_m_size_'):
                return self._m_size_

            self._m_size_ = 160
            return getattr(self, '_m_size_', None)


    class MaterialsData(KaitaiStruct):
        SEQ_FIELDS = ["textures", "materials"]
        def __init__(self, _io, _parent=None, _root=None):
            self._io = _io
            self._parent = _parent
            self._root = _root if _root else self
            self._debug = collections.defaultdict(dict)

        def _read(self):
            self._debug['textures']['start'] = self._io.pos()
            self.textures = []
            for i in range(self._root.header.num_textures):
                if not 'arr' in self._debug['textures']:
                    self._debug['textures']['arr'] = []
                self._debug['textures']['arr'].append({'start': self._io.pos()})
                self.textures.append((KaitaiStream.bytes_terminate(self._io.read_bytes(64), 0, False)).decode(u"ASCII"))
                self._debug['textures']['arr'][i]['end'] = self._io.pos()

            self._debug['textures']['end'] = self._io.pos()
            self._debug['materials']['start'] = self._io.pos()
            self.materials = []
            for i in range(self._root.header.num_materials):
                if not 'arr' in self._debug['materials']:
                    self._debug['materials']['arr'] = []
                self._debug['materials']['arr'].append({'start': self._io.pos()})
                _t_materials = Mod153.Material153(self._io, self, self._root)
                _t_materials._read()
                self.materials.append(_t_materials)
                self._debug['materials']['arr'][i]['end'] = self._io.pos()

            self._debug['materials']['end'] = self._io.pos()

        @property
        def size_(self):
            if hasattr(self, '_m_size_'):
                return self._m_size_

            self._m_size_ = ((64 * self._root.header.num_textures) + (self._root.header.num_materials * self.materials[0].size_))
            return getattr(self, '_m_size_', None)


    class Vertex24(KaitaiStruct):
        SEQ_FIELDS = ["occlusion"]
        def __init__(self, _io, _parent=None, _root=None):
            self._io = _io
            self._parent = _parent
            self._root = _root if _root else self
            self._debug = collections.defaultdict(dict)

        def _read(self):
            self._debug['occlusion']['start'] = self._io.pos()
            self.occlusion = Mod153.Vec4U1(self._io, self, self._root)
            self.occlusion._read()
            self._debug['occlusion']['end'] = self._io.pos()


    class BonesData(KaitaiStruct):
        SEQ_FIELDS = ["bones_hierarchy", "parent_space_matrices", "inverse_bind_matrices", "bone_map", "bone_palettes"]
        def __init__(self, _io, _parent=None, _root=None):
            self._io = _io
            self._parent = _parent
            self._root = _root if _root else self
            self._debug = collections.defaultdict(dict)

        def _read(self):
            self._debug['bones_hierarchy']['start'] = self._io.pos()
            self.bones_hierarchy = []
            for i in range(self._root.header.num_bones):
                if not 'arr' in self._debug['bones_hierarchy']:
                    self._debug['bones_hierarchy']['arr'] = []
                self._debug['bones_hierarchy']['arr'].append({'start': self._io.pos()})
                _t_bones_hierarchy = Mod153.Bone(self._io, self, self._root)
                _t_bones_hierarchy._read()
                self.bones_hierarchy.append(_t_bones_hierarchy)
                self._debug['bones_hierarchy']['arr'][i]['end'] = self._io.pos()

            self._debug['bones_hierarchy']['end'] = self._io.pos()
            self._debug['parent_space_matrices']['start'] = self._io.pos()
            self.parent_space_matrices = []
            for i in range(self._root.header.num_bones):
                if not 'arr' in self._debug['parent_space_matrices']:
                    self._debug['parent_space_matrices']['arr'] = []
                self._debug['parent_space_matrices']['arr'].append({'start': self._io.pos()})
                _t_parent_space_matrices = Mod153.Matrix4x4(self._io, self, self._root)
                _t_parent_space_matrices._read()
                self.parent_space_matrices.append(_t_parent_space_matrices)
                self._debug['parent_space_matrices']['arr'][i]['end'] = self._io.pos()

            self._debug['parent_space_matrices']['end'] = self._io.pos()
            self._debug['inverse_bind_matrices']['start'] = self._io.pos()
            self.inverse_bind_matrices = []
            for i in range(self._root.header.num_bones):
                if not 'arr' in self._debug['inverse_bind_matrices']:
                    self._debug['inverse_bind_matrices']['arr'] = []
                self._debug['inverse_bind_matrices']['arr'].append({'start': self._io.pos()})
                _t_inverse_bind_matrices = Mod153.Matrix4x4(self._io, self, self._root)
                _t_inverse_bind_matrices._read()
                self.inverse_bind_matrices.append(_t_inverse_bind_matrices)
                self._debug['inverse_bind_matrices']['arr'][i]['end'] = self._io.pos()

            self._debug['inverse_bind_matrices']['end'] = self._io.pos()
            if self._root.header.num_bones != 0:
                self._debug['bone_map']['start'] = self._io.pos()
                self.bone_map = self._io.read_bytes(256)
                self._debug['bone_map']['end'] = self._io.pos()

            self._debug['bone_palettes']['start'] = self._io.pos()
            self.bone_palettes = []
            for i in range(self._root.header.num_bone_palettes):
                if not 'arr' in self._debug['bone_palettes']:
                    self._debug['bone_palettes']['arr'] = []
                self._debug['bone_palettes']['arr'].append({'start': self._io.pos()})
                _t_bone_palettes = Mod153.BonePalette(self._io, self, self._root)
                _t_bone_palettes._read()
                self.bone_palettes.append(_t_bone_palettes)
                self._debug['bone_palettes']['arr'][i]['end'] = self._io.pos()

            self._debug['bone_palettes']['end'] = self._io.pos()

        @property
        def size_(self):
            if hasattr(self, '_m_size_'):
                return self._m_size_

            self._m_size_ = ((((((self._root.header.num_bones * self.bones_hierarchy[0].size_) + (self._root.header.num_bones * 64)) + (self._root.header.num_bones * 64)) + 256) + (self._root.header.num_bone_palettes * self.bone_palettes[0].size_)) if self._root.header.num_bones > 0 else 0)
            return getattr(self, '_m_size_', None)


    class Vertex28(KaitaiStruct):
        SEQ_FIELDS = ["occlusion", "tangent"]
        def __init__(self, _io, _parent=None, _root=None):
            self._io = _io
            self._parent = _parent
            self._root = _root if _root else self
            self._debug = collections.defaultdict(dict)

        def _read(self):
            self._debug['occlusion']['start'] = self._io.pos()
            self.occlusion = Mod153.Vec4U1(self._io, self, self._root)
            self.occlusion._read()
            self._debug['occlusion']['end'] = self._io.pos()
            self._debug['tangent']['start'] = self._io.pos()
            self.tangent = Mod153.Vec4U1(self._io, self, self._root)
            self.tangent._read()
            self._debug['tangent']['end'] = self._io.pos()


    class RcnHeader(KaitaiStruct):
        SEQ_FIELDS = ["ptri", "pvtx", "ptb", "num_tri", "num_vtx", "num_tbl", "parts", "reserved"]
        def __init__(self, _io, _parent=None, _root=None):
            self._io = _io
            self._parent = _parent
            self._root = _root if _root else self
            self._debug = collections.defaultdict(dict)

        def _read(self):
            self._debug['ptri']['start'] = self._io.pos()
            self.ptri = self._io.read_u4le()
            self._debug['ptri']['end'] = self._io.pos()
            self._debug['pvtx']['start'] = self._io.pos()
            self.pvtx = self._io.read_u4le()
            self._debug['pvtx']['end'] = self._io.pos()
            self._debug['ptb']['start'] = self._io.pos()
            self.ptb = self._io.read_u4le()
            self._debug['ptb']['end'] = self._io.pos()
            self._debug['num_tri']['start'] = self._io.pos()
            self.num_tri = self._io.read_u4le()
            self._debug['num_tri']['end'] = self._io.pos()
            self._debug['num_vtx']['start'] = self._io.pos()
            self.num_vtx = self._io.read_u4le()
            self._debug['num_vtx']['end'] = self._io.pos()
            self._debug['num_tbl']['start'] = self._io.pos()
            self.num_tbl = self._io.read_u4le()
            self._debug['num_tbl']['end'] = self._io.pos()
            self._debug['parts']['start'] = self._io.pos()
            self.parts = self._io.read_u4le()
            self._debug['parts']['end'] = self._io.pos()
            self._debug['reserved']['start'] = self._io.pos()
            self.reserved = self._io.read_u4le()
            self._debug['reserved']['end'] = self._io.pos()

        @property
        def size_(self):
            if hasattr(self, '_m_size_'):
                return self._m_size_

            self._m_size_ = 32
            return getattr(self, '_m_size_', None)


    class Vec4S2(KaitaiStruct):
        SEQ_FIELDS = ["x", "y", "z", "w"]
        def __init__(self, _io, _parent=None, _root=None):
            self._io = _io
            self._parent = _parent
            self._root = _root if _root else self
            self._debug = collections.defaultdict(dict)

        def _read(self):
            self._debug['x']['start'] = self._io.pos()
            self.x = self._io.read_s2le()
            self._debug['x']['end'] = self._io.pos()
            self._debug['y']['start'] = self._io.pos()
            self.y = self._io.read_s2le()
            self._debug['y']['end'] = self._io.pos()
            self._debug['z']['start'] = self._io.pos()
            self.z = self._io.read_s2le()
            self._debug['z']['end'] = self._io.pos()
            self._debug['w']['start'] = self._io.pos()
            self.w = self._io.read_s2le()
            self._debug['w']['end'] = self._io.pos()


    class Group(KaitaiStruct):
        SEQ_FIELDS = ["group_index", "reserved", "pos", "radius"]
        def __init__(self, _io, _parent=None, _root=None):
            self._io = _io
            self._parent = _parent
            self._root = _root if _root else self
            self._debug = collections.defaultdict(dict)

        def _read(self):
            self._debug['group_index']['start'] = self._io.pos()
            self.group_index = self._io.read_u4le()
            self._debug['group_index']['end'] = self._io.pos()
            self._debug['reserved']['start'] = self._io.pos()
            self.reserved = []
            for i in range(3):
                if not 'arr' in self._debug['reserved']:
                    self._debug['reserved']['arr'] = []
                self._debug['reserved']['arr'].append({'start': self._io.pos()})
                self.reserved.append(self._io.read_u4le())
                self._debug['reserved']['arr'][i]['end'] = self._io.pos()

            self._debug['reserved']['end'] = self._io.pos()
            self._debug['pos']['start'] = self._io.pos()
            self.pos = Mod153.Vec3(self._io, self, self._root)
            self.pos._read()
            self._debug['pos']['end'] = self._io.pos()
            self._debug['radius']['start'] = self._io.pos()
            self.radius = self._io.read_f4le()
            self._debug['radius']['end'] = self._io.pos()

        @property
        def size_(self):
            if hasattr(self, '_m_size_'):
                return self._m_size_

            self._m_size_ = 32
            return getattr(self, '_m_size_', None)


    class Vertex5(KaitaiStruct):
        SEQ_FIELDS = ["position", "bone_indices", "weight_values", "normal", "uv"]
        def __init__(self, _io, _parent=None, _root=None):
            self._io = _io
            self._parent = _parent
            self._root = _root if _root else self
            self._debug = collections.defaultdict(dict)

        def _read(self):
            self._debug['position']['start'] = self._io.pos()
            self.position = Mod153.Vec4S2(self._io, self, self._root)
            self.position._read()
            self._debug['position']['end'] = self._io.pos()
            self._debug['bone_indices']['start'] = self._io.pos()
            self.bone_indices = []
            for i in range(8):
                if not 'arr' in self._debug['bone_indices']:
                    self._debug['bone_indices']['arr'] = []
                self._debug['bone_indices']['arr'].append({'start': self._io.pos()})
                self.bone_indices.append(self._io.read_u1())
                self._debug['bone_indices']['arr'][i]['end'] = self._io.pos()

            self._debug['bone_indices']['end'] = self._io.pos()
            self._debug['weight_values']['start'] = self._io.pos()
            self.weight_values = []
            for i in range(8):
                if not 'arr' in self._debug['weight_values']:
                    self._debug['weight_values']['arr'] = []
                self._debug['weight_values']['arr'].append({'start': self._io.pos()})
                self.weight_values.append(self._io.read_u1())
                self._debug['weight_values']['arr'][i]['end'] = self._io.pos()

            self._debug['weight_values']['end'] = self._io.pos()
            self._debug['normal']['start'] = self._io.pos()
            self.normal = Mod153.Vec4U1(self._io, self, self._root)
            self.normal._read()
            self._debug['normal']['end'] = self._io.pos()
            self._debug['uv']['start'] = self._io.pos()
            self.uv = Mod153.Vec2HalfFloat(self._io, self, self._root)
            self.uv._read()
            self._debug['uv']['end'] = self._io.pos()


    @property
    def vertex_buffer(self):
        if hasattr(self, '_m_vertex_buffer'):
            return self._m_vertex_buffer

        if self.header.offset_vertex_buffer > 0:
            _pos = self._io.pos()
            self._io.seek(self.header.offset_vertex_buffer)
            self._debug['_m_vertex_buffer']['start'] = self._io.pos()
            self._m_vertex_buffer = self._io.read_bytes(self.header.size_vertex_buffer)
            self._debug['_m_vertex_buffer']['end'] = self._io.pos()
            self._io.seek(_pos)

        return getattr(self, '_m_vertex_buffer', None)

    @property
    def materials_data(self):
        if hasattr(self, '_m_materials_data'):
            return self._m_materials_data

        if self.header.offset_materials_data > 0:
            _pos = self._io.pos()
            self._io.seek(self.header.offset_materials_data)
            self._debug['_m_materials_data']['start'] = self._io.pos()
            self._m_materials_data = Mod153.MaterialsData(self._io, self, self._root)
            self._m_materials_data._read()
            self._debug['_m_materials_data']['end'] = self._io.pos()
            self._io.seek(_pos)

        return getattr(self, '_m_materials_data', None)

    @property
    def bones_data_size_(self):
        if hasattr(self, '_m_bones_data_size_'):
            return self._m_bones_data_size_

        self._m_bones_data_size_ = (0 if self.header.num_bones == 0 else self.bones_data.size_)
        return getattr(self, '_m_bones_data_size_', None)

    @property
    def vertex_buffer_2(self):
        if hasattr(self, '_m_vertex_buffer_2'):
            return self._m_vertex_buffer_2

        if self.header.offset_vertex_buffer_2 > 0:
            _pos = self._io.pos()
            self._io.seek(self.header.offset_vertex_buffer)
            self._debug['_m_vertex_buffer_2']['start'] = self._io.pos()
            self._m_vertex_buffer_2 = self._io.read_bytes(self.header.size_vertex_buffer_2)
            self._debug['_m_vertex_buffer_2']['end'] = self._io.pos()
            self._io.seek(_pos)

        return getattr(self, '_m_vertex_buffer_2', None)

    @property
    def meshes_data(self):
        if hasattr(self, '_m_meshes_data'):
            return self._m_meshes_data

        if self.header.offset_meshes_data > 0:
            _pos = self._io.pos()
            self._io.seek(self.header.offset_meshes_data)
            self._debug['_m_meshes_data']['start'] = self._io.pos()
            self._m_meshes_data = Mod153.MeshesData(self._io, self, self._root)
            self._m_meshes_data._read()
            self._debug['_m_meshes_data']['end'] = self._io.pos()
            self._io.seek(_pos)

        return getattr(self, '_m_meshes_data', None)

    @property
    def index_buffer(self):
        if hasattr(self, '_m_index_buffer'):
            return self._m_index_buffer

        if self.header.offset_index_buffer > 0:
            _pos = self._io.pos()
            self._io.seek(self.header.offset_index_buffer)
            self._debug['_m_index_buffer']['start'] = self._io.pos()
            self._m_index_buffer = self._io.read_bytes(((self.header.num_faces * 2) - 2))
            self._debug['_m_index_buffer']['end'] = self._io.pos()
            self._io.seek(_pos)

        return getattr(self, '_m_index_buffer', None)

    @property
    def size_top_level_(self):
        if hasattr(self, '_m_size_top_level_'):
            return self._m_size_top_level_

        self._m_size_top_level_ = (self._root.header.size_ + 104)
        return getattr(self, '_m_size_top_level_', None)

    @property
    def bones_data(self):
        if hasattr(self, '_m_bones_data'):
            return self._m_bones_data

        if self.header.num_bones != 0:
            _pos = self._io.pos()
            self._io.seek(self.header.offset_bones_data)
            self._debug['_m_bones_data']['start'] = self._io.pos()
            self._m_bones_data = Mod153.BonesData(self._io, self, self._root)
            self._m_bones_data._read()
            self._debug['_m_bones_data']['end'] = self._io.pos()
            self._io.seek(_pos)

        return getattr(self, '_m_bones_data', None)

    @property
    def groups(self):
        if hasattr(self, '_m_groups'):
            return self._m_groups

        _pos = self._io.pos()
        self._io.seek(self.header.offset_groups)
        self._debug['_m_groups']['start'] = self._io.pos()
        self._m_groups = []
        for i in range(self.header.num_groups):
            if not 'arr' in self._debug['_m_groups']:
                self._debug['_m_groups']['arr'] = []
            self._debug['_m_groups']['arr'].append({'start': self._io.pos()})
            _t__m_groups = Mod153.Group(self._io, self, self._root)
            _t__m_groups._read()
            self._m_groups.append(_t__m_groups)
            self._debug['_m_groups']['arr'][i]['end'] = self._io.pos()

        self._debug['_m_groups']['end'] = self._io.pos()
        self._io.seek(_pos)
        return getattr(self, '_m_groups', None)

    @property
    def groups_size_(self):
        if hasattr(self, '_m_groups_size_'):
            return self._m_groups_size_

        self._m_groups_size_ = (self.groups[0].size_ * self.header.num_groups)
        return getattr(self, '_m_groups_size_', None)



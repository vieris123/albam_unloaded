# This is a generated file! Please edit source .ksy file and use kaitai-struct-compiler to rebuild
# type: ignore

import kaitaistruct
from kaitaistruct import ReadWriteKaitaiStruct, KaitaiStream, BytesIO


if getattr(kaitaistruct, 'API_VERSION', (0, 9)) < (0, 11):
    raise Exception("Incompatible Kaitai Struct Python API: 0.11 or later is required, but you have %s" % (kaitaistruct.__version__))

class Lmt(ReadWriteKaitaiStruct):
    def __init__(self, _io=None, _parent=None, _root=None):
        self._io = _io
        self._parent = _parent
        self._root = _root if _root else self

    def _read(self):
        self.id_magic = self._io.read_bytes(4)
        if not (self.id_magic == b"\x4C\x4D\x54\x00"):
            raise kaitaistruct.ValidationNotEqualError(b"\x4C\x4D\x54\x00", self.id_magic, self._io, u"/seq/0")
        self.version = self._io.read_u2le()
        self.num_block_offsets = self._io.read_u2le()
        self.block_offsets = []
        for i in range(self.num_block_offsets):
            _t_block_offsets = Lmt.BlockOffset(self._io, self, self._root)
            _t_block_offsets._read()
            self.block_offsets.append(_t_block_offsets)



    def _fetch_instances(self):
        pass
        for i in range(len(self.block_offsets)):
            pass
            self.block_offsets[i]._fetch_instances()



    def _write__seq(self, io=None):
        super(Lmt, self)._write__seq(io)
        self._io.write_bytes(self.id_magic)
        self._io.write_u2le(self.version)
        self._io.write_u2le(self.num_block_offsets)
        for i in range(len(self.block_offsets)):
            pass
            self.block_offsets[i]._write__seq(self._io)



    def _check(self):
        pass
        if (len(self.id_magic) != 4):
            raise kaitaistruct.ConsistencyError(u"id_magic", len(self.id_magic), 4)
        if not (self.id_magic == b"\x4C\x4D\x54\x00"):
            raise kaitaistruct.ValidationNotEqualError(b"\x4C\x4D\x54\x00", self.id_magic, None, u"/seq/0")
        if (len(self.block_offsets) != self.num_block_offsets):
            raise kaitaistruct.ConsistencyError(u"block_offsets", len(self.block_offsets), self.num_block_offsets)
        for i in range(len(self.block_offsets)):
            pass
            if self.block_offsets[i]._root != self._root:
                raise kaitaistruct.ConsistencyError(u"block_offsets", self.block_offsets[i]._root, self._root)
            if self.block_offsets[i]._parent != self:
                raise kaitaistruct.ConsistencyError(u"block_offsets", self.block_offsets[i]._parent, self)


    class Vec4(ReadWriteKaitaiStruct):
        def __init__(self, _io=None, _parent=None, _root=None):
            self._io = _io
            self._parent = _parent
            self._root = _root

        def _read(self):
            self.x = self._io.read_f4le()
            self.y = self._io.read_f4le()
            self.z = self._io.read_f4le()
            self.w = self._io.read_f4le()


        def _fetch_instances(self):
            pass


        def _write__seq(self, io=None):
            super(Lmt.Vec4, self)._write__seq(io)
            self._io.write_f4le(self.x)
            self._io.write_f4le(self.y)
            self._io.write_f4le(self.z)
            self._io.write_f4le(self.w)


        def _check(self):
            pass


    class BlockHeader49(ReadWriteKaitaiStruct):
        def __init__(self, _io=None, _parent=None, _root=None):
            self._io = _io
            self._parent = _parent
            self._root = _root
            self._should_write_tracks = False
            self.tracks__to_write = True
            self._should_write_events_01 = False
            self.events_01__to_write = True
            self._should_write_events_02 = False
            self.events_02__to_write = True

        def _read(self):
            self.ofs_frame = self._io.read_u4le()
            self.num_tracks = self._io.read_u4le()
            self.num_frames = self._io.read_u4le()
            self.loop_frames = self._io.read_u4le()
            self.end_pos = Lmt.Vec4(self._io, self, self._root)
            self.end_pos._read()
            self.end_quat = Lmt.Vec4(self._io, self, self._root)
            self.end_quat._read()
            self.events_params_01 = []
            for i in range(32):
                self.events_params_01.append(self._io.read_u2le())

            self.num_event_01 = self._io.read_u4le()
            self.event_buffer_01 = self._io.read_u4le()
            self.events_params_02 = []
            for i in range(32):
                self.events_params_02.append(self._io.read_u2le())

            self.num_event_02 = self._io.read_u4le()
            self.event_buffer_02 = self._io.read_u4le()


        def _fetch_instances(self):
            pass
            self.end_pos._fetch_instances()
            self.end_quat._fetch_instances()
            for i in range(len(self.events_params_01)):
                pass

            for i in range(len(self.events_params_02)):
                pass

            _ = self.tracks
            for i in range(len(self._m_tracks)):
                pass
                self.tracks[i]._fetch_instances()

            _ = self.events_01
            for i in range(len(self._m_events_01)):
                pass
                self.events_01[i]._fetch_instances()

            _ = self.events_02
            for i in range(len(self._m_events_02)):
                pass
                self.events_02[i]._fetch_instances()



        def _write__seq(self, io=None):
            super(Lmt.BlockHeader49, self)._write__seq(io)
            self._should_write_tracks = self.tracks__to_write
            self._should_write_events_01 = self.events_01__to_write
            self._should_write_events_02 = self.events_02__to_write
            self._io.write_u4le(self.ofs_frame)
            self._io.write_u4le(self.num_tracks)
            self._io.write_u4le(self.num_frames)
            self._io.write_u4le(self.loop_frames)
            self.end_pos._write__seq(self._io)
            self.end_quat._write__seq(self._io)
            for i in range(len(self.events_params_01)):
                pass
                self._io.write_u2le(self.events_params_01[i])

            self._io.write_u4le(self.num_event_01)
            self._io.write_u4le(self.event_buffer_01)
            for i in range(len(self.events_params_02)):
                pass
                self._io.write_u2le(self.events_params_02[i])

            self._io.write_u4le(self.num_event_02)
            self._io.write_u4le(self.event_buffer_02)


        def _check(self):
            pass
            if self.end_pos._root != self._root:
                raise kaitaistruct.ConsistencyError(u"end_pos", self.end_pos._root, self._root)
            if self.end_pos._parent != self:
                raise kaitaistruct.ConsistencyError(u"end_pos", self.end_pos._parent, self)
            if self.end_quat._root != self._root:
                raise kaitaistruct.ConsistencyError(u"end_quat", self.end_quat._root, self._root)
            if self.end_quat._parent != self:
                raise kaitaistruct.ConsistencyError(u"end_quat", self.end_quat._parent, self)
            if (len(self.events_params_01) != 32):
                raise kaitaistruct.ConsistencyError(u"events_params_01", len(self.events_params_01), 32)
            for i in range(len(self.events_params_01)):
                pass

            if (len(self.events_params_02) != 32):
                raise kaitaistruct.ConsistencyError(u"events_params_02", len(self.events_params_02), 32)
            for i in range(len(self.events_params_02)):
                pass


        @property
        def tracks(self):
            if self._should_write_tracks:
                self._write_tracks()
            if hasattr(self, '_m_tracks'):
                return self._m_tracks

            _pos = self._io.pos()
            self._io.seek(self.ofs_frame)
            self._m_tracks = []
            for i in range(self.num_tracks):
                _t__m_tracks = Lmt.Track49(self._io, self, self._root)
                _t__m_tracks._read()
                self._m_tracks.append(_t__m_tracks)

            self._io.seek(_pos)
            return getattr(self, '_m_tracks', None)

        @tracks.setter
        def tracks(self, v):
            self._m_tracks = v

        def _write_tracks(self):
            self._should_write_tracks = False
            _pos = self._io.pos()
            self._io.seek(self.ofs_frame)
            for i in range(len(self._m_tracks)):
                pass
                self.tracks[i]._write__seq(self._io)

            self._io.seek(_pos)


        def _check_tracks(self):
            pass
            if (len(self.tracks) != self.num_tracks):
                raise kaitaistruct.ConsistencyError(u"tracks", len(self.tracks), self.num_tracks)
            for i in range(len(self._m_tracks)):
                pass
                if self.tracks[i]._root != self._root:
                    raise kaitaistruct.ConsistencyError(u"tracks", self.tracks[i]._root, self._root)
                if self.tracks[i]._parent != self:
                    raise kaitaistruct.ConsistencyError(u"tracks", self.tracks[i]._parent, self)


        @property
        def events_01(self):
            if self._should_write_events_01:
                self._write_events_01()
            if hasattr(self, '_m_events_01'):
                return self._m_events_01

            _pos = self._io.pos()
            self._io.seek(self.event_buffer_01)
            self._m_events_01 = []
            for i in range(self.num_event_01):
                _t__m_events_01 = Lmt.Event49(self._io, self, self._root)
                _t__m_events_01._read()
                self._m_events_01.append(_t__m_events_01)

            self._io.seek(_pos)
            return getattr(self, '_m_events_01', None)

        @events_01.setter
        def events_01(self, v):
            self._m_events_01 = v

        def _write_events_01(self):
            self._should_write_events_01 = False
            _pos = self._io.pos()
            self._io.seek(self.event_buffer_01)
            for i in range(len(self._m_events_01)):
                pass
                self.events_01[i]._write__seq(self._io)

            self._io.seek(_pos)


        def _check_events_01(self):
            pass
            if (len(self.events_01) != self.num_event_01):
                raise kaitaistruct.ConsistencyError(u"events_01", len(self.events_01), self.num_event_01)
            for i in range(len(self._m_events_01)):
                pass
                if self.events_01[i]._root != self._root:
                    raise kaitaistruct.ConsistencyError(u"events_01", self.events_01[i]._root, self._root)
                if self.events_01[i]._parent != self:
                    raise kaitaistruct.ConsistencyError(u"events_01", self.events_01[i]._parent, self)


        @property
        def events_02(self):
            if self._should_write_events_02:
                self._write_events_02()
            if hasattr(self, '_m_events_02'):
                return self._m_events_02

            _pos = self._io.pos()
            self._io.seek(self.event_buffer_02)
            self._m_events_02 = []
            for i in range(self.num_event_02):
                _t__m_events_02 = Lmt.Event49(self._io, self, self._root)
                _t__m_events_02._read()
                self._m_events_02.append(_t__m_events_02)

            self._io.seek(_pos)
            return getattr(self, '_m_events_02', None)

        @events_02.setter
        def events_02(self, v):
            self._m_events_02 = v

        def _write_events_02(self):
            self._should_write_events_02 = False
            _pos = self._io.pos()
            self._io.seek(self.event_buffer_02)
            for i in range(len(self._m_events_02)):
                pass
                self.events_02[i]._write__seq(self._io)

            self._io.seek(_pos)


        def _check_events_02(self):
            pass
            if (len(self.events_02) != self.num_event_02):
                raise kaitaistruct.ConsistencyError(u"events_02", len(self.events_02), self.num_event_02)
            for i in range(len(self._m_events_02)):
                pass
                if self.events_02[i]._root != self._root:
                    raise kaitaistruct.ConsistencyError(u"events_02", self.events_02[i]._root, self._root)
                if self.events_02[i]._parent != self:
                    raise kaitaistruct.ConsistencyError(u"events_02", self.events_02[i]._parent, self)



    class Track49(ReadWriteKaitaiStruct):
        def __init__(self, _io=None, _parent=None, _root=None):
            self._io = _io
            self._parent = _parent
            self._root = _root
            self._should_write_data = False
            self.data__to_write = True

        def _read(self):
            self.buffer_type = self._io.read_u1()
            self.usage = self._io.read_u1()
            self.joint_type = self._io.read_u1()
            self.bone_index = self._io.read_u1()
            self.unk_01 = self._io.read_f4le()
            self.len_data = self._io.read_u4le()
            self.ofs_data = self._io.read_u4le()
            self.ref_data = Lmt.Vec4(self._io, self, self._root)
            self.ref_data._read()


        def _fetch_instances(self):
            pass
            self.ref_data._fetch_instances()
            _ = self.data


        def _write__seq(self, io=None):
            super(Lmt.Track49, self)._write__seq(io)
            self._should_write_data = self.data__to_write
            self._io.write_u1(self.buffer_type)
            self._io.write_u1(self.usage)
            self._io.write_u1(self.joint_type)
            self._io.write_u1(self.bone_index)
            self._io.write_f4le(self.unk_01)
            self._io.write_u4le(self.len_data)
            self._io.write_u4le(self.ofs_data)
            self.ref_data._write__seq(self._io)


        def _check(self):
            pass
            if self.ref_data._root != self._root:
                raise kaitaistruct.ConsistencyError(u"ref_data", self.ref_data._root, self._root)
            if self.ref_data._parent != self:
                raise kaitaistruct.ConsistencyError(u"ref_data", self.ref_data._parent, self)

        @property
        def data(self):
            if self._should_write_data:
                self._write_data()
            if hasattr(self, '_m_data'):
                return self._m_data

            _pos = self._io.pos()
            self._io.seek(self.ofs_data)
            self._m_data = self._io.read_bytes(self.len_data)
            self._io.seek(_pos)
            return getattr(self, '_m_data', None)

        @data.setter
        def data(self, v):
            self._m_data = v

        def _write_data(self):
            self._should_write_data = False
            _pos = self._io.pos()
            self._io.seek(self.ofs_data)
            self._io.write_bytes(self.data)
            self._io.seek(_pos)


        def _check_data(self):
            pass
            if (len(self.data) != self.len_data):
                raise kaitaistruct.ConsistencyError(u"data", len(self.data), self.len_data)


    class Event49(ReadWriteKaitaiStruct):
        def __init__(self, _io=None, _parent=None, _root=None):
            self._io = _io
            self._parent = _parent
            self._root = _root

        def _read(self):
            self.group_id = self._io.read_u4le()
            self.frame = self._io.read_u4le()


        def _fetch_instances(self):
            pass


        def _write__seq(self, io=None):
            super(Lmt.Event49, self)._write__seq(io)
            self._io.write_u4le(self.group_id)
            self._io.write_u4le(self.frame)


        def _check(self):
            pass


    class Atk(ReadWriteKaitaiStruct):
        def __init__(self, _io=None, _parent=None, _root=None):
            self._io = _io
            self._parent = _parent
            self._root = _root

        def _read(self):
            self.unk_00 = self._io.read_u4le()
            self.duration = self._io.read_u4le()


        def _fetch_instances(self):
            pass


        def _write__seq(self, io=None):
            super(Lmt.Atk, self)._write__seq(io)
            self._io.write_u4le(self.unk_00)
            self._io.write_u4le(self.duration)


        def _check(self):
            pass


    class BlockOffset(ReadWriteKaitaiStruct):
        def __init__(self, _io=None, _parent=None, _root=None):
            self._io = _io
            self._parent = _parent
            self._root = _root
            self._should_write_block_header = False
            self.block_header__to_write = True

        def _read(self):
            self.offset = self._io.read_u4le()


        def _fetch_instances(self):
            pass
            if (self.offset != 0):
                pass
                _ = self.block_header
                _on = self.lmt_ver
                if _on == 49:
                    pass
                    self.block_header._fetch_instances()
                elif _on == 51:
                    pass
                    self.block_header._fetch_instances()
                elif _on == 67:
                    pass
                    self.block_header._fetch_instances()



        def _write__seq(self, io=None):
            super(Lmt.BlockOffset, self)._write__seq(io)
            self._should_write_block_header = self.block_header__to_write
            self._io.write_u4le(self.offset)


        def _check(self):
            pass

        @property
        def lmt_ver(self):
            if hasattr(self, '_m_lmt_ver'):
                return self._m_lmt_ver

            self._m_lmt_ver = self._parent.version
            return getattr(self, '_m_lmt_ver', None)

        def _invalidate_lmt_ver(self):
            del self._m_lmt_ver
        @property
        def block_header(self):
            if self._should_write_block_header:
                self._write_block_header()
            if hasattr(self, '_m_block_header'):
                return self._m_block_header

            if (self.offset != 0):
                pass
                _pos = self._io.pos()
                self._io.seek(self.offset)
                _on = self.lmt_ver
                if _on == 49:
                    pass
                    self._m_block_header = Lmt.BlockHeader49(self._io, self, self._root)
                    self._m_block_header._read()
                elif _on == 51:
                    pass
                    self._m_block_header = Lmt.BlockHeader51(self._io, self, self._root)
                    self._m_block_header._read()
                elif _on == 67:
                    pass
                    self._m_block_header = Lmt.BlockHeader67(self._io, self, self._root)
                    self._m_block_header._read()
                self._io.seek(_pos)

            return getattr(self, '_m_block_header', None)

        @block_header.setter
        def block_header(self, v):
            self._m_block_header = v

        def _write_block_header(self):
            self._should_write_block_header = False
            if (self.offset != 0):
                pass
                _pos = self._io.pos()
                self._io.seek(self.offset)
                _on = self.lmt_ver
                if _on == 49:
                    pass
                    self.block_header._write__seq(self._io)
                elif _on == 51:
                    pass
                    self.block_header._write__seq(self._io)
                elif _on == 67:
                    pass
                    self.block_header._write__seq(self._io)
                self._io.seek(_pos)



        def _check_block_header(self):
            pass
            if (self.offset != 0):
                pass
                _on = self.lmt_ver
                if _on == 49:
                    pass
                    if self.block_header._root != self._root:
                        raise kaitaistruct.ConsistencyError(u"block_header", self.block_header._root, self._root)
                    if self.block_header._parent != self:
                        raise kaitaistruct.ConsistencyError(u"block_header", self.block_header._parent, self)
                elif _on == 51:
                    pass
                    if self.block_header._root != self._root:
                        raise kaitaistruct.ConsistencyError(u"block_header", self.block_header._root, self._root)
                    if self.block_header._parent != self:
                        raise kaitaistruct.ConsistencyError(u"block_header", self.block_header._parent, self)
                elif _on == 67:
                    pass
                    if self.block_header._root != self._root:
                        raise kaitaistruct.ConsistencyError(u"block_header", self.block_header._root, self._root)
                    if self.block_header._parent != self:
                        raise kaitaistruct.ConsistencyError(u"block_header", self.block_header._parent, self)



    class BlockHeader51(ReadWriteKaitaiStruct):
        def __init__(self, _io=None, _parent=None, _root=None):
            self._io = _io
            self._parent = _parent
            self._root = _root
            self._should_write_tracks = False
            self.tracks__to_write = True
            self._should_write_atk_buff = False
            self.atk_buff__to_write = True
            self._should_write_atk_buff2 = False
            self.atk_buff2__to_write = True

        def _read(self):
            self.ofs_frame = self._io.read_u4le()
            self.num_tracks = self._io.read_u4le()
            self.num_frames = self._io.read_u4le()
            self.loop_frames = self._io.read_u4le()
            self.end_pos = Lmt.Vec4(self._io, self, self._root)
            self.end_pos._read()
            self.end_quat = Lmt.Vec4(self._io, self, self._root)
            self.end_quat._read()
            self.display_events = []
            for i in range(16):
                self.display_events.append(self._io.read_u4le())

            self.num_event_01 = self._io.read_u4le()
            self.ofs_buffer_01 = self._io.read_u4le()
            self.sfx_events = []
            for i in range(32):
                self.sfx_events.append(self._io.read_u2le())

            self.num_event_02 = self._io.read_u4le()
            self.ofs_buffer_02 = self._io.read_u4le()


        def _fetch_instances(self):
            pass
            self.end_pos._fetch_instances()
            self.end_quat._fetch_instances()
            for i in range(len(self.display_events)):
                pass

            for i in range(len(self.sfx_events)):
                pass

            _ = self.tracks
            for i in range(len(self._m_tracks)):
                pass
                self.tracks[i]._fetch_instances()

            _ = self.atk_buff
            for i in range(len(self._m_atk_buff)):
                pass
                self.atk_buff[i]._fetch_instances()

            _ = self.atk_buff2
            for i in range(len(self._m_atk_buff2)):
                pass
                self.atk_buff2[i]._fetch_instances()



        def _write__seq(self, io=None):
            super(Lmt.BlockHeader51, self)._write__seq(io)
            self._should_write_tracks = self.tracks__to_write
            self._should_write_atk_buff = self.atk_buff__to_write
            self._should_write_atk_buff2 = self.atk_buff2__to_write
            self._io.write_u4le(self.ofs_frame)
            self._io.write_u4le(self.num_tracks)
            self._io.write_u4le(self.num_frames)
            self._io.write_u4le(self.loop_frames)
            self.end_pos._write__seq(self._io)
            self.end_quat._write__seq(self._io)
            for i in range(len(self.display_events)):
                pass
                self._io.write_u4le(self.display_events[i])

            self._io.write_u4le(self.num_event_01)
            self._io.write_u4le(self.ofs_buffer_01)
            for i in range(len(self.sfx_events)):
                pass
                self._io.write_u2le(self.sfx_events[i])

            self._io.write_u4le(self.num_event_02)
            self._io.write_u4le(self.ofs_buffer_02)


        def _check(self):
            pass
            if self.end_pos._root != self._root:
                raise kaitaistruct.ConsistencyError(u"end_pos", self.end_pos._root, self._root)
            if self.end_pos._parent != self:
                raise kaitaistruct.ConsistencyError(u"end_pos", self.end_pos._parent, self)
            if self.end_quat._root != self._root:
                raise kaitaistruct.ConsistencyError(u"end_quat", self.end_quat._root, self._root)
            if self.end_quat._parent != self:
                raise kaitaistruct.ConsistencyError(u"end_quat", self.end_quat._parent, self)
            if (len(self.display_events) != 16):
                raise kaitaistruct.ConsistencyError(u"display_events", len(self.display_events), 16)
            for i in range(len(self.display_events)):
                pass

            if (len(self.sfx_events) != 32):
                raise kaitaistruct.ConsistencyError(u"sfx_events", len(self.sfx_events), 32)
            for i in range(len(self.sfx_events)):
                pass


        @property
        def tracks(self):
            if self._should_write_tracks:
                self._write_tracks()
            if hasattr(self, '_m_tracks'):
                return self._m_tracks

            _pos = self._io.pos()
            self._io.seek(self.ofs_frame)
            self._m_tracks = []
            for i in range(self.num_tracks):
                _t__m_tracks = Lmt.Track51(self._io, self, self._root)
                _t__m_tracks._read()
                self._m_tracks.append(_t__m_tracks)

            self._io.seek(_pos)
            return getattr(self, '_m_tracks', None)

        @tracks.setter
        def tracks(self, v):
            self._m_tracks = v

        def _write_tracks(self):
            self._should_write_tracks = False
            _pos = self._io.pos()
            self._io.seek(self.ofs_frame)
            for i in range(len(self._m_tracks)):
                pass
                self.tracks[i]._write__seq(self._io)

            self._io.seek(_pos)


        def _check_tracks(self):
            pass
            if (len(self.tracks) != self.num_tracks):
                raise kaitaistruct.ConsistencyError(u"tracks", len(self.tracks), self.num_tracks)
            for i in range(len(self._m_tracks)):
                pass
                if self.tracks[i]._root != self._root:
                    raise kaitaistruct.ConsistencyError(u"tracks", self.tracks[i]._root, self._root)
                if self.tracks[i]._parent != self:
                    raise kaitaistruct.ConsistencyError(u"tracks", self.tracks[i]._parent, self)


        @property
        def atk_buff(self):
            if self._should_write_atk_buff:
                self._write_atk_buff()
            if hasattr(self, '_m_atk_buff'):
                return self._m_atk_buff

            _pos = self._io.pos()
            self._io.seek(self.ofs_buffer_01)
            self._m_atk_buff = []
            for i in range(self.num_event_01):
                _t__m_atk_buff = Lmt.Atk(self._io, self, self._root)
                _t__m_atk_buff._read()
                self._m_atk_buff.append(_t__m_atk_buff)

            self._io.seek(_pos)
            return getattr(self, '_m_atk_buff', None)

        @atk_buff.setter
        def atk_buff(self, v):
            self._m_atk_buff = v

        def _write_atk_buff(self):
            self._should_write_atk_buff = False
            _pos = self._io.pos()
            self._io.seek(self.ofs_buffer_01)
            for i in range(len(self._m_atk_buff)):
                pass
                self.atk_buff[i]._write__seq(self._io)

            self._io.seek(_pos)


        def _check_atk_buff(self):
            pass
            if (len(self.atk_buff) != self.num_event_01):
                raise kaitaistruct.ConsistencyError(u"atk_buff", len(self.atk_buff), self.num_event_01)
            for i in range(len(self._m_atk_buff)):
                pass
                if self.atk_buff[i]._root != self._root:
                    raise kaitaistruct.ConsistencyError(u"atk_buff", self.atk_buff[i]._root, self._root)
                if self.atk_buff[i]._parent != self:
                    raise kaitaistruct.ConsistencyError(u"atk_buff", self.atk_buff[i]._parent, self)


        @property
        def atk_buff2(self):
            if self._should_write_atk_buff2:
                self._write_atk_buff2()
            if hasattr(self, '_m_atk_buff2'):
                return self._m_atk_buff2

            _pos = self._io.pos()
            self._io.seek(self.ofs_buffer_02)
            self._m_atk_buff2 = []
            for i in range(self.num_event_02):
                _t__m_atk_buff2 = Lmt.Atk2(self._io, self, self._root)
                _t__m_atk_buff2._read()
                self._m_atk_buff2.append(_t__m_atk_buff2)

            self._io.seek(_pos)
            return getattr(self, '_m_atk_buff2', None)

        @atk_buff2.setter
        def atk_buff2(self, v):
            self._m_atk_buff2 = v

        def _write_atk_buff2(self):
            self._should_write_atk_buff2 = False
            _pos = self._io.pos()
            self._io.seek(self.ofs_buffer_02)
            for i in range(len(self._m_atk_buff2)):
                pass
                self.atk_buff2[i]._write__seq(self._io)

            self._io.seek(_pos)


        def _check_atk_buff2(self):
            pass
            if (len(self.atk_buff2) != self.num_event_02):
                raise kaitaistruct.ConsistencyError(u"atk_buff2", len(self.atk_buff2), self.num_event_02)
            for i in range(len(self._m_atk_buff2)):
                pass
                if self.atk_buff2[i]._root != self._root:
                    raise kaitaistruct.ConsistencyError(u"atk_buff2", self.atk_buff2[i]._root, self._root)
                if self.atk_buff2[i]._parent != self:
                    raise kaitaistruct.ConsistencyError(u"atk_buff2", self.atk_buff2[i]._parent, self)



    class Atk2(ReadWriteKaitaiStruct):
        def __init__(self, _io=None, _parent=None, _root=None):
            self._io = _io
            self._parent = _parent
            self._root = _root

        def _read(self):
            self.unk_00 = self._io.read_u4le()
            self.unk_01 = self._io.read_u4le()


        def _fetch_instances(self):
            pass


        def _write__seq(self, io=None):
            super(Lmt.Atk2, self)._write__seq(io)
            self._io.write_u4le(self.unk_00)
            self._io.write_u4le(self.unk_01)


        def _check(self):
            pass


    class Vec3(ReadWriteKaitaiStruct):
        def __init__(self, _io=None, _parent=None, _root=None):
            self._io = _io
            self._parent = _parent
            self._root = _root

        def _read(self):
            self.x = self._io.read_f4le()
            self.y = self._io.read_f4le()
            self.z = self._io.read_f4le()


        def _fetch_instances(self):
            pass


        def _write__seq(self, io=None):
            super(Lmt.Vec3, self)._write__seq(io)
            self._io.write_f4le(self.x)
            self._io.write_f4le(self.y)
            self._io.write_f4le(self.z)


        def _check(self):
            pass


    class Track51(ReadWriteKaitaiStruct):
        def __init__(self, _io=None, _parent=None, _root=None):
            self._io = _io
            self._parent = _parent
            self._root = _root
            self._should_write_data = False
            self.data__to_write = True

        def _read(self):
            self.buffer_type = self._io.read_u1()
            self.usage = self._io.read_u1()
            self.joint_type = self._io.read_u1()
            self.bone_index = self._io.read_u1()
            self.unk_01 = self._io.read_f4le()
            self.len_data = self._io.read_u4le()
            self.ofs_data = self._io.read_u4le()
            self.ref_data = Lmt.Vec4(self._io, self, self._root)
            self.ref_data._read()


        def _fetch_instances(self):
            pass
            self.ref_data._fetch_instances()
            _ = self.data


        def _write__seq(self, io=None):
            super(Lmt.Track51, self)._write__seq(io)
            self._should_write_data = self.data__to_write
            self._io.write_u1(self.buffer_type)
            self._io.write_u1(self.usage)
            self._io.write_u1(self.joint_type)
            self._io.write_u1(self.bone_index)
            self._io.write_f4le(self.unk_01)
            self._io.write_u4le(self.len_data)
            self._io.write_u4le(self.ofs_data)
            self.ref_data._write__seq(self._io)


        def _check(self):
            pass
            if self.ref_data._root != self._root:
                raise kaitaistruct.ConsistencyError(u"ref_data", self.ref_data._root, self._root)
            if self.ref_data._parent != self:
                raise kaitaistruct.ConsistencyError(u"ref_data", self.ref_data._parent, self)

        @property
        def data(self):
            if self._should_write_data:
                self._write_data()
            if hasattr(self, '_m_data'):
                return self._m_data

            _pos = self._io.pos()
            self._io.seek(self.ofs_data)
            self._m_data = self._io.read_bytes(self.len_data)
            self._io.seek(_pos)
            return getattr(self, '_m_data', None)

        @data.setter
        def data(self, v):
            self._m_data = v

        def _write_data(self):
            self._should_write_data = False
            _pos = self._io.pos()
            self._io.seek(self.ofs_data)
            self._io.write_bytes(self.data)
            self._io.seek(_pos)


        def _check_data(self):
            pass
            if (len(self.data) != self.len_data):
                raise kaitaistruct.ConsistencyError(u"data", len(self.data), self.len_data)


    class FloatBuffer(ReadWriteKaitaiStruct):
        def __init__(self, _io=None, _parent=None, _root=None):
            self._io = _io
            self._parent = _parent
            self._root = _root

        def _read(self):
            self.unk_00 = []
            for i in range(8):
                self.unk_00.append(self._io.read_f4le())



        def _fetch_instances(self):
            pass
            for i in range(len(self.unk_00)):
                pass



        def _write__seq(self, io=None):
            super(Lmt.FloatBuffer, self)._write__seq(io)
            for i in range(len(self.unk_00)):
                pass
                self._io.write_f4le(self.unk_00[i])



        def _check(self):
            pass
            if (len(self.unk_00) != 8):
                raise kaitaistruct.ConsistencyError(u"unk_00", len(self.unk_00), 8)
            for i in range(len(self.unk_00)):
                pass



    class OfsFloatBuff(ReadWriteKaitaiStruct):
        def __init__(self, _io=None, _parent=None, _root=None):
            self._io = _io
            self._parent = _parent
            self._root = _root
            self._should_write_body = False
            self.body__to_write = True

        def _read(self):
            self.ofs_buffer = self._io.read_u4le()


        def _fetch_instances(self):
            pass
            if (self.is_exist != 0):
                pass
                _ = self.body
                self.body._fetch_instances()



        def _write__seq(self, io=None):
            super(Lmt.OfsFloatBuff, self)._write__seq(io)
            self._should_write_body = self.body__to_write
            self._io.write_u4le(self.ofs_buffer)


        def _check(self):
            pass

        @property
        def is_exist(self):
            if hasattr(self, '_m_is_exist'):
                return self._m_is_exist

            self._m_is_exist = self.ofs_buffer
            return getattr(self, '_m_is_exist', None)

        def _invalidate_is_exist(self):
            del self._m_is_exist
        @property
        def body(self):
            if self._should_write_body:
                self._write_body()
            if hasattr(self, '_m_body'):
                return self._m_body

            if (self.is_exist != 0):
                pass
                _pos = self._io.pos()
                self._io.seek(self.ofs_buffer)
                self._m_body = Lmt.FloatBuffer(self._io, self, self._root)
                self._m_body._read()
                self._io.seek(_pos)

            return getattr(self, '_m_body', None)

        @body.setter
        def body(self, v):
            self._m_body = v

        def _write_body(self):
            self._should_write_body = False
            if (self.is_exist != 0):
                pass
                _pos = self._io.pos()
                self._io.seek(self.ofs_buffer)
                self.body._write__seq(self._io)
                self._io.seek(_pos)



        def _check_body(self):
            pass
            if (self.is_exist != 0):
                pass
                if self.body._root != self._root:
                    raise kaitaistruct.ConsistencyError(u"body", self.body._root, self._root)
                if self.body._parent != self:
                    raise kaitaistruct.ConsistencyError(u"body", self.body._parent, self)



    class Track67(ReadWriteKaitaiStruct):
        def __init__(self, _io=None, _parent=None, _root=None):
            self._io = _io
            self._parent = _parent
            self._root = _root
            self._should_write_data = False
            self.data__to_write = True

        def _read(self):
            self.buffer_type = self._io.read_u1()
            self.usage = self._io.read_u1()
            self.joint_type = self._io.read_u1()
            self.bone_index = self._io.read_u1()
            self.weight = self._io.read_f4le()
            self.len_data = self._io.read_u4le()
            self.ofs_data = self._io.read_u4le()
            self.unk_reference_data = []
            for i in range(4):
                self.unk_reference_data.append(self._io.read_f4le())

            self.ofs_floats = Lmt.OfsFloatBuff(self._io, self, self._root)
            self.ofs_floats._read()


        def _fetch_instances(self):
            pass
            for i in range(len(self.unk_reference_data)):
                pass

            self.ofs_floats._fetch_instances()
            _ = self.data


        def _write__seq(self, io=None):
            super(Lmt.Track67, self)._write__seq(io)
            self._should_write_data = self.data__to_write
            self._io.write_u1(self.buffer_type)
            self._io.write_u1(self.usage)
            self._io.write_u1(self.joint_type)
            self._io.write_u1(self.bone_index)
            self._io.write_f4le(self.weight)
            self._io.write_u4le(self.len_data)
            self._io.write_u4le(self.ofs_data)
            for i in range(len(self.unk_reference_data)):
                pass
                self._io.write_f4le(self.unk_reference_data[i])

            self.ofs_floats._write__seq(self._io)


        def _check(self):
            pass
            if (len(self.unk_reference_data) != 4):
                raise kaitaistruct.ConsistencyError(u"unk_reference_data", len(self.unk_reference_data), 4)
            for i in range(len(self.unk_reference_data)):
                pass

            if self.ofs_floats._root != self._root:
                raise kaitaistruct.ConsistencyError(u"ofs_floats", self.ofs_floats._root, self._root)
            if self.ofs_floats._parent != self:
                raise kaitaistruct.ConsistencyError(u"ofs_floats", self.ofs_floats._parent, self)

        @property
        def data(self):
            if self._should_write_data:
                self._write_data()
            if hasattr(self, '_m_data'):
                return self._m_data

            _pos = self._io.pos()
            self._io.seek(self.ofs_data)
            self._m_data = self._io.read_bytes(self.len_data)
            self._io.seek(_pos)
            return getattr(self, '_m_data', None)

        @data.setter
        def data(self, v):
            self._m_data = v

        def _write_data(self):
            self._should_write_data = False
            _pos = self._io.pos()
            self._io.seek(self.ofs_data)
            self._io.write_bytes(self.data)
            self._io.seek(_pos)


        def _check_data(self):
            pass
            if (len(self.data) != self.len_data):
                raise kaitaistruct.ConsistencyError(u"data", len(self.data), self.len_data)


    class BlockHeader67(ReadWriteKaitaiStruct):
        def __init__(self, _io=None, _parent=None, _root=None):
            self._io = _io
            self._parent = _parent
            self._root = _root
            self._should_write_tracks = False
            self.tracks__to_write = True

        def _read(self):
            self.ofs_frame = self._io.read_u4le()
            self.num_tracks = self._io.read_u4le()
            self.num_frames = self._io.read_u4le()
            self.loop_frame = self._io.read_u4le()
            self.unk_floats = []
            for i in range(8):
                self.unk_floats.append(self._io.read_f4le())

            self.unk_00 = self._io.read_u4le()
            self.ofs_buffer_1 = self._io.read_u4le()
            self.ofs_buffer_2 = self._io.read_u4le()


        def _fetch_instances(self):
            pass
            for i in range(len(self.unk_floats)):
                pass

            _ = self.tracks
            for i in range(len(self._m_tracks)):
                pass
                self.tracks[i]._fetch_instances()



        def _write__seq(self, io=None):
            super(Lmt.BlockHeader67, self)._write__seq(io)
            self._should_write_tracks = self.tracks__to_write
            self._io.write_u4le(self.ofs_frame)
            self._io.write_u4le(self.num_tracks)
            self._io.write_u4le(self.num_frames)
            self._io.write_u4le(self.loop_frame)
            for i in range(len(self.unk_floats)):
                pass
                self._io.write_f4le(self.unk_floats[i])

            self._io.write_u4le(self.unk_00)
            self._io.write_u4le(self.ofs_buffer_1)
            self._io.write_u4le(self.ofs_buffer_2)


        def _check(self):
            pass
            if (len(self.unk_floats) != 8):
                raise kaitaistruct.ConsistencyError(u"unk_floats", len(self.unk_floats), 8)
            for i in range(len(self.unk_floats)):
                pass


        @property
        def tracks(self):
            if self._should_write_tracks:
                self._write_tracks()
            if hasattr(self, '_m_tracks'):
                return self._m_tracks

            _pos = self._io.pos()
            self._io.seek(self.ofs_frame)
            self._m_tracks = []
            for i in range(self.num_tracks):
                _t__m_tracks = Lmt.Track67(self._io, self, self._root)
                _t__m_tracks._read()
                self._m_tracks.append(_t__m_tracks)

            self._io.seek(_pos)
            return getattr(self, '_m_tracks', None)

        @tracks.setter
        def tracks(self, v):
            self._m_tracks = v

        def _write_tracks(self):
            self._should_write_tracks = False
            _pos = self._io.pos()
            self._io.seek(self.ofs_frame)
            for i in range(len(self._m_tracks)):
                pass
                self.tracks[i]._write__seq(self._io)

            self._io.seek(_pos)


        def _check_tracks(self):
            pass
            if (len(self.tracks) != self.num_tracks):
                raise kaitaistruct.ConsistencyError(u"tracks", len(self.tracks), self.num_tracks)
            for i in range(len(self._m_tracks)):
                pass
                if self.tracks[i]._root != self._root:
                    raise kaitaistruct.ConsistencyError(u"tracks", self.tracks[i]._root, self._root)
                if self.tracks[i]._parent != self:
                    raise kaitaistruct.ConsistencyError(u"tracks", self.tracks[i]._parent, self)





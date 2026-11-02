# SPDX-License-Identifier: BSD-3-Clause
"""``save_writer.py``: the IDL SAVE file
``soda2_process_2d.pro:729-731`` writes, without GDL.

Three independent sides: ``scipy.io.readsav`` (a third-party reader of the
format) for the round trip; the vendored ``soda2_process_2d.pro`` source for
the tag order; and the descriptor of an IDL 8.5-written SODA-2 ``.dat`` for
the in-memory layout -- its structure only (types, dimensions, offsets), and
only when the file is present locally (it is UND's and never tracked).
The GDL side is ``test_soda2_save_writer_gdl.py``."""
from __future__ import annotations

import dataclasses
import os
import re
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

import numpy as np
from scipy.io import readsav
from tests import _upstream  # noqa: E402
from tests._repo import repo_only

from arrayprobe_soda2.process_2d import ProcessData, Soda2ProcessError, soda2_process_2d
from arrayprobe_soda2.save_writer import (
    PROCESS_DATA_TAGS,
    IdlSaveUnsupported,
    save_process_data,
    struct_layout,
    write_idl_save,
)

HERE = Path(__file__).resolve().parent
S2_FIXTURE = HERE / "data" / "s2_spec_raw_fixture"
IDL_SOURCE = _upstream.source("soda2") / "soda2_process_2d.pro"
#: UND's IDL-written .dat -- local only, main checkout only (never tracked).
#: Found as `test_soda2_probespecs_und_op` finds it (I3: was an absolute
#: personal path): `ARRAYPROBE_REFERENCE_DATA` first, then an
#: `arrayprobe-local-data/` beside any parent (a worktree reaches its main
#: checkout's).
_UND_REL = Path("2016-und-data/20160914_075310/HVPS3_Data/09142016_075310_HVPS3.dat")


def setUpModule():
    # Raised here rather than at import: an import-time SkipTest crashes
    # ``python -m unittest tests.<module>``, where ``discover`` reports it as a skip.
    _upstream.require("soda2")


def _und_dat() -> Path:
    roots = []
    if os.environ.get("ARRAYPROBE_REFERENCE_DATA"):
        roots.append(Path(os.environ["ARRAYPROBE_REFERENCE_DATA"]))
    roots += [p / "arrayprobe-local-data" for p in Path(__file__).resolve().parents]
    for root in roots:
        if (root / _UND_REL).is_file():
            return root / _UND_REL
    return roots[-1] / _UND_REL


UND_DAT = _und_dat()
TS = ("Tue Sep 15 00:00:00 2026", "u", "h")


def _roundtrip(value, *, compress=False):
    with tempfile.TemporaryDirectory() as tmp:
        p = write_idl_save(Path(tmp) / "x.sav", {"data": value}, compress=compress,
                           timestamp=TS)
        return readsav(str(p))["data"][0], p.read_bytes()


def _op(**overrides):
    op = dict(
        fn=str(S2_FIXTURE), date="20160906", starttime=24240.0, stoptime=24250.0,
        format="SPEC", subformat=0, probetype="2DS", res=10.0,
        endbins=[0.0, 50.0, 100.0, 200.0, 500.0], arendbins=[0.0, 0.5, 1.0],
        rate=1.0, smethod="xy", pth="", particlefile=0, inttime_reject=0,
        stuckbits=0, water=0, fixedtas=0.0, timeoffset=0.0, armwidth=6.3,
        numdiodes=128, greythresh=0, probeid="H", eawmethod="centerin",
        wavelength=0.785e-6, dofconst=8.12, ncdfparticlefile=0, asciipsdfile=0,
    )
    op.update(overrides)
    return op


class RoundTripThroughReadsav(unittest.TestCase):
    def test_every_scalar_type_keeps_its_idl_type_and_value(self):
        value = {"b": np.uint8(200), "i": np.int16(-3), "u": np.uint16(65535),
                 "l": np.int32(-70000), "ul": np.uint32(4000000000),
                 "l64": np.int64(-5 * 10**12), "ul64": np.uint64(2**64 - 1),
                 "f": np.float32(1.5), "d": np.float64(-2.25),
                 "c": np.complex64(1 - 2j), "dc": np.complex128(0.1 + 3j)}
        rec, _ = _roundtrip(value)
        want = {"b": ">u1", "i": ">i2", "u": ">u2", "l": ">i4", "ul": ">u4",
                "l64": ">i8", "ul64": ">u8", "f": ">f4", "d": ">f8", "c": ">c8",
                "dc": ">c16"}
        for tag, dt in want.items():
            with self.subTest(tag=tag):
                got = rec[tag]
                self.assertEqual(np.asarray(got).dtype.newbyteorder("="),
                                 np.dtype(dt).newbyteorder("="))
                self.assertEqual(got, value[tag])

    def test_strings_including_the_empty_one(self):
        rec, _ = _roundtrip({"s": "hello", "e": "", "arr": ["a", "", "xyz"]})
        self.assertEqual(rec["s"], b"hello")
        self.assertEqual(rec["e"], "")  # readsav's own empty-string form
        self.assertEqual([x if isinstance(x, str) else x.decode() for x in rec["arr"]],
                         ["a", "", "xyz"])

    def test_arrays_come_back_transposed_exactly_as_from_an_idl_file(self):
        """IDL dims = the port's numpy shape; readsav reverses them, so it
        returns the transpose -- the same as it does for IDL's own file."""
        a = np.arange(24, dtype=np.float32).reshape(2, 3, 4)
        i = np.array([[1, -2, 3], [-32768, 32767, 0]], dtype=np.int16)
        b = np.array([1, 2, 250, 0, 7], dtype=np.uint8)  # odd length: padding
        rec, _ = _roundtrip({"a": a, "i": i, "b": b}, compress=True)
        np.testing.assert_array_equal(rec["a"], a.T)
        np.testing.assert_array_equal(rec["i"], i.T)
        np.testing.assert_array_equal(rec["b"], b)
        self.assertEqual(rec["a"].dtype.newbyteorder("="), np.dtype("f4"))

    def test_nan_and_infinities_survive(self):
        f = np.array([np.nan, np.inf, -np.inf, -0.0], dtype=np.float32)
        rec, _ = _roundtrip({"f": f})
        np.testing.assert_array_equal(np.isnan(rec["f"]), np.isnan(f))
        self.assertEqual(list(rec["f"][1:]), [np.inf, -np.inf, 0.0])
        self.assertTrue(np.signbit(rec["f"][3]))

    def test_nested_structures_and_a_dataclass(self):
        @dataclasses.dataclass
        class Inner:
            c: np.int16
            d: list

        rec, _ = _roundtrip({"a": np.uint8(1), "b": 2.0,
                             "sub": {"x": Inner(np.int16(-7), ["p", "qq"])}})
        inner = rec["sub"][0]["x"][0]
        self.assertEqual(int(inner["c"]), -7)
        self.assertEqual([s.decode() for s in inner["d"]], ["p", "qq"])

    def test_compressed_and_plain_restore_identically(self):
        value = {"a": np.arange(10, dtype=np.int32), "s": "x"}
        r0, b0 = _roundtrip(value, compress=False)
        r1, b1 = _roundtrip(value, compress=True)
        self.assertEqual(b0[:4], b"SR\x00\x04")
        self.assertEqual(b1[:4], b"SR\x00\x06")
        np.testing.assert_array_equal(r0["a"], r1["a"])
        self.assertEqual(r0["s"], r1["s"])


class PythonValueTypes(unittest.TestCase):
    """The module docstring's rules for native Python values."""

    def test_python_int_follows_the_idl_literal_rule(self):
        rec, _ = _roundtrip({"a": 7, "b": 33000, "c": 5_000_000_000,
                             "arr": [1, 2, 33000]})
        self.assertEqual(np.asarray(rec["a"]).dtype.itemsize, 2)
        self.assertEqual(np.asarray(rec["b"]).dtype.itemsize, 4)
        self.assertEqual(np.asarray(rec["c"]).dtype.itemsize, 8)
        self.assertEqual(rec["arr"].dtype.newbyteorder("="), np.dtype("i4"))

    def test_python_float_is_double(self):
        rec, _ = _roundtrip({"a": 0.1, "arr": [0.5, 1.0]})
        self.assertEqual(np.asarray(rec["a"]).dtype.newbyteorder("="), np.dtype("f8"))
        self.assertEqual(float(rec["a"]), 0.1)
        self.assertEqual(rec["arr"].dtype.newbyteorder("="), np.dtype("f8"))


class RefusedByName(unittest.TestCase):
    def test_values_idl_cannot_hold_are_refused_not_coerced(self):
        bad = {
            "none": None,
            "int8": np.array([1], dtype=np.int8),
            "empty": np.zeros(0, dtype=np.float32),
            "nine_dims": np.zeros((1,) * 9, dtype=np.float32),
            "unicode": "µ" + "\u2603",
            "empty_list": [],
            "struct_array": [{"a": 1}],
        }
        for label, value in bad.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                with self.assertRaises(IdlSaveUnsupported):
                    write_idl_save(Path(tmp) / "x.sav", {"data": {"v": value}})


class FileStructure(unittest.TestCase):
    def test_record_sequence_is_idls_and_end_closes_the_file(self):
        """TIMESTAMP, VERSION, VARIABLE, END -- the sequence an IDL 8.5 file
        has; END is 16 bytes and the file stops there (GDL appends stale
        bytes after it; this writer does not)."""
        for compress in (False, True):
            _, raw = _roundtrip({"a": np.int32(1)}, compress=compress)
            pos, kinds = 4, []
            while True:
                rectype, lo, hi = struct.unpack(">lII", raw[pos:pos + 12])
                kinds.append(rectype)
                if rectype == 6:
                    self.assertEqual(len(raw), pos + 16)
                    break
                body = raw[pos + 16:lo + (hi << 32)]
                if compress:
                    zlib.decompress(body)  # each record is its own zlib stream
                pos = lo + (hi << 32)
            self.assertEqual(kinds, [10, 14, 2, 6])

    def test_same_data_and_timestamp_write_identical_bytes(self):
        value = {"a": np.arange(5, dtype=np.float32)}
        _, b1 = _roundtrip(value, compress=True)
        _, b2 = _roundtrip(value, compress=True)
        self.assertEqual(b1, b2)


class TagOrder(unittest.TestCase):
    @repo_only
    def test_tag_order_is_the_idl_sources(self):
        """``:678-687`` parsed from the vendored source, not transcribed."""
        text = IDL_SOURCE.read_text(encoding="latin1")
        block = text[text.index("data={op:op"):text.index("pbpstartindex:pbpstartindex}") + 30]
        tags = [t.lower() for t in re.findall(r"(\w+):", block)]
        self.assertEqual(tuple(tags), PROCESS_DATA_TAGS)

    def test_processdata_declares_the_same_order(self):
        names = [f.name for f in dataclasses.fields(ProcessData)]
        port_only = {"pbp_csv_path", "pbp_ncdf_path", "save_path"}
        self.assertEqual(tuple(n for n in names if n not in port_only), PROCESS_DATA_TAGS)


@repo_only
class TestLayoutAgainstIdlOpStruct(unittest.TestCase):
    """The descriptor's tag offsets follow 64-bit IDL's in-memory layout
    (STRING 16 bytes, C natural alignment, size padded to the widest
    member). The types, dimensions and offsets below are those of the
    ``op`` struct in an IDL 8.5-written SODA-2 ``.dat`` (structure only --
    no value of that file is used)."""

    def test_offsets_match_idl(self):
        s = ""
        op = {
            "fn": s, "date": s, "starttime": np.float64(0), "stoptime": np.float64(0),
            "format": s, "subformat": np.int16(0), "probetype": s, "res": np.float32(0),
            "endbins": np.zeros(29, np.int16), "arendbins": np.zeros(11, np.float32),
            "rate": np.int16(0), "smethod": s, "pth": s, "particlefile": np.int16(0),
            "savfile": np.int16(0), "inttime_reject": np.int16(0),
            "reconstruct": np.int16(0), "stuckbits": np.int16(0), "water": np.int16(0),
            "fixedtas": np.int16(0), "outdir": s, "project": s, "timeoffset": np.int16(0),
            "armwidth": np.float32(0), "numdiodes": np.float32(0), "probeid": s,
            "shortname": s, "greythresh": np.int16(0), "serialnum": s, "orientation": s,
            "crossbins": np.zeros(29, np.int32), "clusterthresh": np.float32(0),
            "wavelength": np.float32(0), "keeplargest": np.int16(0), "yres": np.float32(0),
        }
        size, offsets = struct_layout(op)
        self.assertEqual([o for _, o in offsets], [
            0, 16, 32, 40, 48, 64, 72, 88, 92, 152, 196, 200, 216, 232, 234, 236, 238,
            240, 242, 244, 248, 264, 280, 284, 288, 296, 312, 328, 336, 352, 368, 484,
            488, 492, 496])
        self.assertEqual(size, 504)


@unittest.skipUnless(UND_DAT.exists(), "UND's IDL-written .dat is local-only")
class TestLayoutAgainstIdlDescriptorOnDisk(unittest.TestCase):
    """Every struct offset in the IDL-written file's descriptor equals what
    ``struct_layout`` computes from the same types and dimensions. Reads the
    descriptor only (it precedes the data); asserts no value."""

    def test_every_offset(self):
        with open(UND_DAT, "rb") as f:
            head = f.read(1 << 16)
        pos = 4
        while True:
            rectype, lo, hi = struct.unpack(">lII", head[pos:pos + 12])
            if rectype == 2:
                break
            pos = lo + (hi << 32)
        r = _Reader(head, pos + 16)
        r.string()                   # varname
        r.long(), r.long()           # typecode, varflags
        r.arraydesc()
        checked = r.check_struct(self)
        self.assertGreater(checked, 60)


class _Reader:
    """Descriptor walker -- structure only."""

    _NP = {1: np.uint8, 2: np.int16, 3: np.int32, 4: np.float32, 5: np.float64,
           6: np.complex64, 9: np.complex128, 12: np.uint16, 13: np.uint32,
           14: np.int64, 15: np.uint64}

    def __init__(self, b, p):
        self.b, self.p = b, p

    def long(self):
        v = struct.unpack(">l", self.b[self.p:self.p + 4])[0]
        self.p += 4
        return v

    def string(self):
        n = self.long()
        s = self.b[self.p:self.p + n].decode("latin1")
        self.p += n + (-n % 4)
        return s

    def arraydesc(self):
        vals = [self.long() for _ in range(7)]
        dims = [self.long() for _ in range(self.long())]
        return vals, dims[:vals[4]]

    def check_struct(self, tc):
        """Asserts every struct's offsets; returns how many were checked."""
        return self._struct(tc)[1]

    def _struct(self, tc):
        self.long()
        self.string()
        self.long()
        ntags = self.long()
        self.long()
        tags = [(self.long(), self.long(), self.long()) for _ in range(ntags)]
        names = [self.string() for _ in range(ntags)]
        arrays = {names[i]: self.arraydesc()[1] for i in range(ntags) if tags[i][2] & 4}
        subs, n = {}, 0
        for i in range(ntags):
            if tags[i][2] & 32:
                subs[names[i]], k = self._struct(tc)
                n += k
        tmpl = {}
        for i, name in enumerate(names):
            off, code, flags = tags[i]
            if flags & 32:
                tmpl[name] = subs[name]
            elif code == 7:
                tmpl[name] = np.array([""] * int(np.prod(arrays[name])), dtype=object).reshape(
                    arrays[name]) if flags & 4 else ""
            elif flags & 4:
                tmpl[name] = np.zeros(arrays[name], dtype=self._NP[code])
            else:
                tmpl[name] = self._NP[code](0)
        _, offsets = struct_layout(tmpl)
        tc.assertEqual([o for _, o in offsets], [t[0] for t in tags])
        return tmpl, n + ntags


@unittest.skipUnless(S2_FIXTURE.exists(), "Tracked SPEC fixture is not distributed with the "
                                          "package")
class DriverWritesTheSaveFile(unittest.TestCase):
    """``:729-731``: ``fn_out=soda2_filename(op,op.shortname)``; ``IF
    op.savfile eq 1 THEN save,file=fn_out,data,/compress``."""

    def test_savfile_1_writes_the_dat_that_readsav_restores(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = soda2_process_2d(_op(savfile=1, outdir=tmp + os.sep, rate=1))
            assert isinstance(d, ProcessData)
            want = Path(tmp) / "20160906_064400_2DS_H.dat"
            self.assertEqual(Path(d.save_path or ""), want)
            raw = want.read_bytes()
            self.assertEqual(raw[:4], b"SR\x00\x06")  # /compress
            rec = readsav(str(want))["data"][0]
            self.assertEqual(tuple(n.lower() for n in rec.dtype.names), PROCESS_DATA_TAGS)
            for tag in ("conc1d", "spec2d", "activetime", "count_rejected", "pointer",
                        "dhist", "time"):
                with self.subTest(tag=tag):
                    got, port = rec[tag], np.asarray(getattr(d, tag))
                    self.assertEqual(got.dtype.newbyteorder("="), port.dtype)
                    np.testing.assert_array_equal(got, port.T)
            self.assertRegex(rec["date_processed"].decode(),
                             r"^\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}$")
            house = rec["house"][0]
            np.testing.assert_array_equal(house["tas"], np.asarray(d.house.tas).T)

    def test_savfile_other_than_1_writes_nothing(self):
        for savfile in (0, 2):
            with self.subTest(savfile=savfile), tempfile.TemporaryDirectory() as tmp:
                d = soda2_process_2d(_op(savfile=savfile, outdir=tmp + os.sep))
                assert isinstance(d, ProcessData)
                self.assertIsNone(d.save_path)
                self.assertEqual(list(Path(tmp).glob("*.dat")), [])

    def test_default_savfile_without_outdir_halts_by_name(self):
        """``update_op`` defaults ``savfile`` to 1 and never defaults
        ``outdir``; ``soda2_filename.pro:5`` then halts on ``op.outdir``."""
        with self.assertRaisesRegex(Soda2ProcessError, "OUTDIR"):
            soda2_process_2d(_op())

    def test_the_und_reference_tool_loads_a_port_written_dat_unchanged(self):
        """``load_reference`` (the sample-area stage's tool,
        not edited) reads the port's ``.dat`` as it reads UND's."""
        sys.path.insert(0, str(HERE.parent))
        from scripts.soda2_und_reference import FIELD_MAP, load_reference

        with tempfile.TemporaryDirectory() as tmp:
            d = soda2_process_2d(_op(savfile=1, outdir=tmp + os.sep))
            assert isinstance(d, ProcessData) and d.save_path
            op, data = load_reference(Path(d.save_path))
            self.assertEqual(op["probetype"], "2DS")
            for ref_key in FIELD_MAP:
                if ref_key in data:
                    np.testing.assert_array_equal(np.asarray(data[ref_key]),
                                                  np.asarray(getattr(d, FIELD_MAP[ref_key])).T)


class SaveProcessDataDirect(unittest.TestCase):
    def test_port_only_fields_are_not_written(self):
        @dataclasses.dataclass
        class Fake:
            pass

        fake = Fake()
        for tag in PROCESS_DATA_TAGS:
            setattr(fake, tag, np.float32(1) if tag != "op" else {"a": 1})
        fake.house = {"t": np.float32(0)}  # type: ignore[attr-defined]
        fake.pbp_csv_path = "x"  # type: ignore[attr-defined]
        with tempfile.TemporaryDirectory() as tmp:
            p = save_process_data(Path(tmp) / "x.dat", fake, timestamp=TS)
            rec = readsav(str(p))["data"][0]
            self.assertNotIn("pbp_csv_path", [n.lower() for n in rec.dtype.names])


if __name__ == "__main__":
    unittest.main()

# SPDX-License-Identifier: BSD-3-Clause
"""SODA-2 RAF Fast-2DC end to end: `soda2_process_2d.pro` over a synthetic RAF ``.2d``.

Three Fast2DC_v2 records (`soda2_read2dbuffer.pro:19-66`: a 20-byte big-endian header and
512 ``ulong64`` image words, 4116 bytes) after an XML preamble ending ``</OAP>``
(subformat 3, `:40-45`), each carrying the sync-delimited particles of
``test_soda2_processbuffer_f2dc.py`` Case A. Asserts the driver completes, accepts
particles, and refuses jobs > 1 by name. A second synthetic file of RAF 2DC records
(1024 ULONG slices, 0x55 timing words) runs end to end, and so do the two RAF 2DP
rows of the ported probe table (probe id 'P1', the 2DC route): 'NCAR 2DP' (subformat 3)
and 'Wyoming 2DP (NCAR-RAF format)' (subformat 4, which stops at `:43` on an ``</OAP>``
file). Documented semantics, not GDL output.
"""
from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path

import numpy as np

from arrayprobe_soda2.buildindex import buildindex_generic
from arrayprobe_soda2.process_2d import ProcessData, soda2_process_2d
from arrayprobe_soda2.update_op import update_op

BLANK = 0xFFFFFFFFFFFFFFFF
SYNC = 0xAAAA000000000000
M64 = 0xFFFFFFFFFFFFFFFF
T0 = 3723  # 01:02:03 UTC, seconds from midnight


def _case_a() -> list[int]:
    """`test_soda2_processbuffer_f2dc._case_a`'s bit patterns."""
    img = [BLANK] * 512
    img[0] = SYNC | 1000
    for i in range(1, 4):
        img[i] = ~(0x7 << 30) & M64
    img[10] = SYNC | 0x100000000000 | 2000
    for i in range(11, 13):
        img[i] = ~(0x1 << 20) & M64
    img[20] = SYNC | 3000
    return img


def _rec(sec: int, ms: int, tas: int = 100) -> bytes:
    hh, rem = divmod(sec, 3600)
    mm, ss = divmod(rem, 60)
    head = struct.pack(">BB9h", ord("C"), ord("4"), hh, mm, ss, 2024, 3, 11, tas, ms, 0)
    return head + struct.pack(">512Q", *_case_a())


def _write(d: str) -> Path:
    p = Path(d) / "synthetic_rf01.2d"
    # :42 seeks strpos('</OAP>') + 7, so the first record starts at byte 12.
    body = b"<OAP></OAP> " + b"".join(_rec(T0 + k, 0) for k in range(3))
    p.write_bytes(body)
    return p


def _op(fn: str, **over) -> dict:
    """`test_soda2_dmt_driver._op`'s literal with the RAF Fast-2DC fields swapped in."""
    op: dict = dict(
        fn=fn, date="03112024", starttime=T0 - 1, stoptime=T0 + 4,
        format="RAF", subformat=3, probetype="F2DC_v2", res=25.0, yres=25.0,
        armwidth=6.1, numdiodes=64, probeid="C4", shortname="F2DC", greythresh=0,
        wavelength=0.658e-6, dofconst=3.0, seatag=np.array([33000], dtype=np.int32),
        endbins=[25, 50, 75, 100, 125, 150, 200, 250, 300, 350, 400, 475, 550, 625,
                 700, 800, 900, 1000, 1200, 1400, 1600],
        arendbins=np.array([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
                           dtype=np.float32),
        rate=1, smethod="fastcircle", pth="", particlefile=0, inttime_reject=0,
        stuckbits=0, water=0, fixedtas=np.float32(0.0), project="",
        timeoffset=np.float32(0.0), eawmethod="centerin", savfile=0,
    )
    op.update(over)
    return op


class RafFast2dcDriver(unittest.TestCase):
    def test_index_walk_terminates_on_the_raf_null_buffer(self):
        """`soda2_buildindex.pro:39-49`: the walk stops at the RAF null buffer (EOF)."""
        with tempfile.TemporaryDirectory() as d:
            p = _write(d)
            idx = buildindex_generic(p, update_op(_op(str(p))))
        self.assertEqual(idx.error, 0)
        self.assertEqual(idx.count, 3)
        np.testing.assert_array_equal(idx.bufftime, [T0, T0 + 1, T0 + 2])
        # the first pointer is the pre-seek position 0 (`:38-42` skip the preamble after it).
        np.testing.assert_array_equal(idx.pointer, [0, 12 + 4116, 12 + 2 * 4116])

    def test_serial_run_completes_and_accepts_particles(self):
        with tempfile.TemporaryDirectory() as d:
            p = _write(d)
            data = soda2_process_2d(_op(str(p), outdir=d + "/"))
        self.assertIsInstance(data, ProcessData)
        assert isinstance(data, ProcessData)
        self.assertGreater(int(np.sum(data.count_accepted)), 0)
        self.assertTrue(np.all(np.isfinite(data.midbins)))
        self.assertTrue(np.all(np.isfinite(data.spec1d)))
        self.assertTrue(np.all(np.isfinite(data.conc1d)))

    def test_jobs_gt_1_refused_by_name(self):
        with tempfile.TemporaryDirectory() as d:
            p = _write(d)
            with self.assertRaisesRegex(NotImplementedError, r"soda2_process_2d\.pro:39"):
                soda2_process_2d(_op(str(p), outdir=d + "/"), jobs=2)

    def test_cli_sidecar_names_raf_f2dc_v2(self):
        """`arrayprobe soda2 run` on the synthetic RAF file: the `.pbp.call` sidecar names
        ``engine=soda2`` and ``probe = {format: RAF, probetype: F2DC_v2, subformat: 3}``."""
        import contextlib
        import io
        import json

        from arrayprobe import cli
        with tempfile.TemporaryDirectory() as d:
            p = _write(d)
            op = _op(str(p))
            toml = ['[run]', 'engine = "soda2"', '', '[soda2]']
            for k, v in op.items():
                if isinstance(v, np.ndarray):
                    v = v.tolist()
                elif isinstance(v, np.generic):
                    v = v.item()
                toml.append(f"{k} = {json.dumps(str(v).replace(chr(92), '/') if k == 'fn' else v)}")
            toml.append(f'outdir = {json.dumps(d.replace(chr(92), "/") + "/")}')
            cfg = Path(d) / "raf.toml"
            cfg.write_text("\n".join(toml) + "\n", encoding="utf-8")
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                rc = cli.main(["soda2", "run", str(cfg), "--out", d])
            self.assertEqual(rc, 0, err.getvalue())
            sidecars = list(Path(d).glob("*.pbp.call"))
            self.assertEqual(len(sidecars), 1, out.getvalue())
            rec = json.loads(sidecars[0].read_text(encoding="utf-8"))
        self.assertEqual(rec["engine"], "soda2")
        self.assertEqual(rec["probe"], {"format": "RAF", "probetype": "F2DC_v2",
                                        "subformat": 3})
        self.assertEqual(rec["op"]["format"], "RAF")

    def test_raf_2dc_synthetic_end_to_end(self):
        """RAF probetype 2DC through `soda2_process_2d.pro`: three 4116-byte records of
        1024 big-endian ULONG slices (`soda2_read2dbuffer.pro:21-23`) carrying the 2DC GDL
        bank's case A (four 0x55 time/sync pairs, `soda2_processbuffer.pro:84`). Asserts the
        run completes and accepts particles; nothing about science values."""
        with tempfile.TemporaryDirectory() as d:
            p = _write_2dc(d)
            data = soda2_process_2d(_op_2dc(str(p), outdir=d + "/"))
        self.assertIsInstance(data, ProcessData)
        assert isinstance(data, ProcessData)
        self.assertGreater(int(np.sum(data.count_accepted)), 0)


# Placeholder arm width for the synthetic 2DC test only. The real ACE-1 C1 arm width is an
# open author input; this value is not it and must not be copied into any run configuration.
TEST_ARMWIDTH = 6.1


def _rec_2dc(sec: int) -> bytes:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "validation" / "gdl"))  # noqa: E501
    import run_soda2_2dc_bank as bank
    img = [0xFFFFFFFF] * 1024
    for k, v in bank.case_a().items():
        img[k] = v
    hh, rem = divmod(sec, 3600)
    mm, ss = divmod(rem, 60)
    head = struct.pack(">BB9h", ord("C"), ord("1"), hh, mm, ss, 2024, 3, 11, 100, 0, 0)
    return head + struct.pack(">1024I", *img)


def _write_2dc(d: str) -> Path:
    p = Path(d) / "synthetic_rf01_2dc.2d"
    p.write_bytes(b"<OAP></OAP> " + b"".join(_rec_2dc(T0 + k) for k in range(3)))
    return p


def _op_2dc(fn: str, **over) -> dict:
    op = _op(fn, probetype="2DC", probeid="C1", shortname="2DC", res=25.0, yres=25.0,
             numdiodes=32.0, armwidth=TEST_ARMWIDTH)
    op.update(over)
    return op


def _rec_2dp(sec: int, pid: bytes = b"P1") -> bytes:
    """`_rec_2dc`'s record with the probe id bytes set to ``pid`` (`:54` matches it)."""
    rec = _rec_2dc(sec)
    return pid + rec[2:]


def _write_2dp(d: str, preamble: bytes) -> Path:
    p = Path(d) / "synthetic_rf01_2dp.2d"
    p.write_bytes(preamble + b"".join(_rec_2dp(T0 + k) for k in range(3)))
    return p


def _op_from_table(name: str, fn: str, **over) -> dict:
    """The run fields of `_op`, with every `soda2_probespecs` field of ``name`` laid over
    them -- the probe comes from the ported table, not from this file."""
    from arrayprobe_soda2.probespecs import soda2_probespecs
    spec = soda2_probespecs(name=name)
    assert isinstance(spec, dict) and spec["probename"] == name
    op = _op(fn)
    op.update(spec)
    op.update(over)
    return op


class RafTwoDpThroughThe2dcRoute(unittest.TestCase):
    """The two RAF 2DP rows of `soda2_probespecs.pro` -- 'NCAR 2DP' (`:839-857`,
    subformat 3) and 'Wyoming 2DP (NCAR-RAF format)' (`:899-917`, subformat 4) -- both
    carry probetype '2DC', so `soda2_processbuffer.pro` sends them down the 2DC branch.
    Synthetic records are `_rec_2dc`'s (1024 ULONG slices, the 2DC GDL bank's case A 0x55
    pairs) with probe id 'P1'. Completion and nonzero accepted counts only; no science
    values."""

    def test_ncar_2dp_subformat_3_runs_end_to_end(self):
        with tempfile.TemporaryDirectory() as d:
            p = _write_2dp(d, b"<OAP></OAP> ")   # `:40-43`: </OAP> needs subformat 3
            op = _op_from_table("NCAR 2DP", str(p), outdir=d + "/")
            self.assertEqual((op["format"], op["probetype"], op["probeid"],
                              int(op["subformat"]), float(op["res"]), int(op["numdiodes"])),
                             ("RAF", "2DC", "P1", 3, 200.0, 32))
            data = soda2_process_2d(op)
        self.assertIsInstance(data, ProcessData)
        assert isinstance(data, ProcessData)
        self.assertGreater(int(np.sum(data.count_accepted)), 0)

    def test_wyoming_2dp_subformat_4_runs_end_to_end_on_a_pms2d_file(self):
        """Subformat 4 passes `soda2_read2dbuffer.pro:38-46` only on a pre-2011 file whose
        preamble ends ``</PMS2D>`` (`:39` seeks pos+9; `:45` stops only subformat 3), and
        `:57` then scales TAS by 125/255. The probespecs comment "4 flags use of fix2dimage"
        is not acted on in the RAF branch: `fix2dimage` is called at `:179` (T28 branch)
        and the `:81` call is commented out."""
        with tempfile.TemporaryDirectory() as d:
            # '<PMS2D></PMS2D>' + 1 byte: pos=7, pos+9 = 16 = the first record.
            p = _write_2dp(d, b"<PMS2D></PMS2D> ")
            op = _op_from_table("Wyoming 2DP (NCAR-RAF format)", str(p), outdir=d + "/")
            self.assertEqual((op["format"], op["probetype"], op["probeid"],
                              int(op["subformat"]), float(op["res"]), int(op["numdiodes"])),
                             ("RAF", "2DC", "P1", 4, 200.0, 32))
            data = soda2_process_2d(op)
        self.assertIsInstance(data, ProcessData)
        assert isinstance(data, ProcessData)
        self.assertGreater(int(np.sum(data.count_accepted)), 0)

    def test_wyoming_2dp_subformat_4_on_an_oap_file_is_the_idl_stop_at_43(self):
        """`soda2_read2dbuffer.pro:43`: ``IF (*pop).subformat ne 3 THEN stop`` on a
        post-2011 ``</OAP>`` file -- IDL halts; the port raises `RafSubformatError`."""
        from arrayprobe_soda2.read2dbuffer import RafSubformatError
        with tempfile.TemporaryDirectory() as d:
            p = _write_2dp(d, b"<OAP></OAP> ")
            op = _op_from_table("Wyoming 2DP (NCAR-RAF format)", str(p), outdir=d + "/")
            with self.assertRaisesRegex(RafSubformatError, r"soda2_read2dbuffer\.pro:43"):
                soda2_process_2d(op)


if __name__ == "__main__":
    unittest.main()

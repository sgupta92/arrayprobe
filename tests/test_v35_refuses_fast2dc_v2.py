# SPDX-License-Identifier: BSD-3-Clause
"""The v3.5 engine refuses a Fast-2DC v2 raw file instead of writing an empty product.

The v3.5 engine frames Fast-2DC v1 only: a three-byte ``AA AA AA`` particle boundary and a
12 MHz clock. A Fast-2DC v2 file (NCAR RAF OAP format, ``<probe ... type="Fast2DC_v2">``)
marks each particle with a two-byte ``AA AA`` word and a 33.333 MHz 44-bit clock, so the v1
framing finds no particle and the engine would write an empty product with no error. The
probe element tested here is the one read from a real CAESAR 2024 file's header:
``<probe id="C4" type="Fast2DC_v2" resolution="25" nDiodes="64" clockFreq="33.333"
laserWaveLength="660" serialnumber="F2DC003" suffix="_RPC"/>``.

The helper :func:`arrayprobe_uiops.oap_read.refuse_unsupported_raf_probe` is asserted on a
synthetic file of each version, and the batch driver is run on the v2 file to show it exits 2
with the message before any stage runs.
"""
from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

from tests._repo import needs_enhancements  # noqa: E402

from arrayprobe_uiops.oap_read import UnsupportedProbeVersion, refuse_unsupported_raf_probe

_TOOLS = Path(__file__).resolve().parents[1] / "scripts"

#: One 8-byte Fast-2DC v2 particle word: ``AA AA`` then the 44-bit timing (a word of this
#: shape, not copied from any file).
_V2_SYNC_WORD = bytes.fromhex("aaaa1012fe75599e")


def _preamble(probe_type: str) -> bytes:
    lines = [
        '<?xml version="1.0" encoding="ISO-8859-1"?>',
        '<OAP version="1">',
        " <Source>test</Source>",
        " <Project>TEST</Project>",
        f' <probe id="C4" type="{probe_type}" resolution="25" nDiodes="64"'
        ' clockFreq="33.333" laserWaveLength="660" serialnumber="F2DC003" suffix="_RPC"/>',
        "</OAP>",
    ]
    return ("\n".join(lines) + "\n").encode("latin-1")


def _record() -> bytes:
    """One record: a 20-byte header (tag ``C4``) and 4096 data bytes holding the v2 word."""
    header = b"C4" + bytes(18)
    data = (_V2_SYNC_WORD * (4096 // len(_V2_SYNC_WORD)))
    assert len(data) == 4096
    return header + data


def _write(path: Path, probe_type: str) -> Path:
    path.write_bytes(_preamble(probe_type) + _record())
    return path


class TheHelperReadsTheProbeType(unittest.TestCase):

    def test_a_fast2dc_v2_file_is_refused_naming_soda2(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw = _write(Path(tmp) / "f.2d", "Fast2DC_v2")
            with self.assertRaises(UnsupportedProbeVersion) as cm:
                refuse_unsupported_raf_probe(raw)
        msg = str(cm.exception)
        self.assertIn("Fast2DC_v2", msg)
        self.assertIn("--engine soda2", msg)
        self.assertIn("33.333 MHz", msg)

    def test_the_error_is_a_value_error(self):
        self.assertTrue(issubclass(UnsupportedProbeVersion, ValueError))

    def test_a_fast2dc_v1_file_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw = _write(Path(tmp) / "f.2d", "Fast2DC")
            self.assertIsNone(refuse_unsupported_raf_probe(raw))

    def test_a_file_without_a_preamble_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp) / "f.2d"
            raw.write_bytes(_record())
            self.assertIsNone(refuse_unsupported_raf_probe(raw))


@needs_enhancements
class TheDriverRefusesAV2FileUnderEngine35(unittest.TestCase):
    _saved: Any  # assigned in setUpClass
    mod: Any  # assigned in setUpClass

    @classmethod
    def setUpClass(cls):
        if str(_TOOLS) not in sys.path:
            sys.path.insert(0, str(_TOOLS))
        import run_flight
        cls.mod = run_flight
        cls._saved = cls.mod.ACTIVE
        cls.addClassCleanup(lambda: cls.mod.use_preset(cls._saved.name))

    def _main(self, probe_type: str, tmp: Path) -> tuple[int, str]:
        name = "V35_F2DC_V2_GATE"
        presets = tmp / "camps.toml"
        presets.write_text(
            "[[campaign]]\n"
            f'name = "{name}"\n'
            'probe = "Fast2DC"\n'
            'orientation = "none"\n'
            'project = "TEST"\n'
            "d_choice = 6\n"
            "sa_method = 0\n"
            "pres_pa = 9e5\n"
            "temp_c = 15.0\n"
            'provenance = "a test, not a campaign"\n',
            encoding="utf-8")
        raw = _write(tmp / "base240101000000.2d", probe_type)
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                rc = self.mod.main([str(raw), "--presets", str(presets),
                                    "--preset", name, "--engine", "3.5",
                                    "--stages", "2", "--out", str(tmp / "out")])
        finally:
            self.mod.use_preset(self._saved.name)
            self.mod.PRESETS.pop(name, None)
        return rc, buf.getvalue()

    def test_a_v2_file_exits_2_naming_soda2(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc, out = self._main("Fast2DC_v2", Path(tmp))
            self.assertEqual(rc, 2, out[-2000:])
            self.assertIn("REFUSED   base240101000000.2d: probe type 'Fast2DC_v2'", out)
            self.assertIn("--engine soda2", out)
            self.assertFalse((Path(tmp) / "out").exists()
                             and any((Path(tmp) / "out").glob("*.nc")))

    def test_a_v1_file_is_not_refused_by_this_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, out = self._main("Fast2DC", Path(tmp))
            self.assertNotIn("Fast2DC_v2", out)


if __name__ == "__main__":
    unittest.main()

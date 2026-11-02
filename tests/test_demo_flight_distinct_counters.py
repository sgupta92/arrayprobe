# SPDX-License-Identifier: BSD-3-Clause
"""``distinct_counters``: the opt-in that lets SODA-2 see the demo flights' particles.

Every demo image packet carries the particle counter 7, and SODA-2's ``spec_index``
keeps a frame only when the counter changes, so it indexes one of the dense demo's
60 particles. ``distinct_counters=True`` writes
``(7 + k) mod 65536`` for the k-th packet (one 16-bit word). Pinned here: (1) the
default stays byte-identical to the builder before the option existed (SHA-256s
measured 2026-10-18 from the builder before the option existed); (2) with the option, SODA-2's
index sees more than one image; (3) both CLI surfaces forward the flag.
"""
from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from arrayprobe.tools import make_demo_flight as mdf
from arrayprobe_soda2.spec_index import spec_index

#: Default builds of the builder before ``distinct_counters`` existed.
DENSE_DEFAULT_SHA256 = "608fca4ef5176b6bdf79d52f0c42c7f4d03d974b964c29b58d447027a984c9a0"
PLAIN_DEFAULT_SHA256 = "eb4b212c9ae757133dd687d39310d87f0c0acfb652775deb2376e507b88a8502"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class TestDefaultIsByteIdentical(unittest.TestCase):
    def test_dense_default_bytes_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            p = mdf.build_dense_demo_flight(Path(d) / "dense.2DS")
            self.assertEqual(_sha(Path(p)), DENSE_DEFAULT_SHA256)

    def test_plain_default_bytes_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            p = mdf.build_demo_flight(Path(d) / "plain.2DS")
            self.assertEqual(_sha(Path(p)), PLAIN_DEFAULT_SHA256)

    def test_explicit_false_equals_default(self):
        with tempfile.TemporaryDirectory() as d:
            p = mdf.build_dense_demo_flight(Path(d) / "d.2DS", distinct_counters=False)
            self.assertEqual(_sha(Path(p)), DENSE_DEFAULT_SHA256)

    def test_counter_wraps_at_16_bits(self):
        self.assertEqual(mdf._packet_counter(0, True), 7)
        self.assertEqual(mdf._packet_counter(65528, True), 65535)
        self.assertEqual(mdf._packet_counter(65529, True), 0)
        self.assertEqual(mdf._packet_counter(123, False), 7)


class TestSoda2SeesMoreThanOneParticle(unittest.TestCase):
    def _numimages(self, distinct: bool) -> int:
        with tempfile.TemporaryDirectory() as d:
            p = mdf.build_dense_demo_flight(Path(d) / "base160906060640.2DS",
                                            n_seconds=5, distinct_counters=distinct)
            with open(p, "rb") as f:
                idx = spec_index(f)
            return int(idx.numimages.astype(int).sum())

    def test_distinct_counters_index_more_than_one_image(self):
        self.assertGreater(self._numimages(True), 1)

    def test_distinct_counters_index_more_than_the_default(self):
        self.assertGreater(self._numimages(True), self._numimages(False))


class TestCliForwardsTheFlag(unittest.TestCase):
    def test_tool_main_passes_flag_to_dense_builder(self):
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(mdf, "build_dense_demo_flight",
                                  wraps=mdf.build_dense_demo_flight) as b, \
                mock.patch("builtins.print"):
            mdf.main([str(Path(d) / "x.2DS"), "--dense", "--distinct-counters"])
            self.assertTrue(b.call_args.kwargs["distinct_counters"])

    def test_tool_main_passes_flag_to_plain_builder(self):
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(mdf, "build_demo_flight",
                                  wraps=mdf.build_demo_flight) as b, \
                mock.patch("builtins.print"):
            mdf.main([str(Path(d) / "x.2DS"), "--distinct-counters"])
            self.assertTrue(b.call_args.kwargs["distinct_counters"])

    def test_arrayprobe_subcommand_forwards_flag(self):
        from arrayprobe import cli
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(mdf, "main", return_value=0) as m:
            argv = ["make-demo-flight", str(Path(d) / "x.2DS"), "--dense",
                    "--distinct-counters"]
            cli.main(argv)
            self.assertIn("--distinct-counters", m.call_args.args[0])

    def test_default_does_not_forward_flag(self):
        from arrayprobe import cli
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(mdf, "main", return_value=0) as m:
            cli.main(["make-demo-flight", str(Path(d) / "x.2DS")])
            self.assertNotIn("--distinct-counters", m.call_args.args[0])


if __name__ == "__main__":
    unittest.main()

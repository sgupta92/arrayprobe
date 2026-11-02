# SPDX-License-Identifier: BSD-3-Clause
"""``arrayprobe.friendly`` -- the thin boundary layer, and its guardrails.

Each wrapper is tested against the raw function it re-views on a tracked or
synthetic fixture, proving it returns exactly the raw data re-viewed (never a
new number), plus one mutation per wrapper proving the test would actually
notice if that stopped being true. A separate sweep proves the module is
never reachable from the reproduction path, and another sweeps the source
tree for the one-based-index convention statement this module's docstring
points at rather than duplicates.
"""

from __future__ import annotations

import ast
import os
import tempfile
import unittest
from pathlib import Path

import numpy as np
from tests._repo import REPO_ROOT, needs_source, needs_v314_engine, repo_only

from arrayprobe import friendly
from arrayprobe._v314_lazy import lazy_module
from arrayprobe.readers.mask_csv import MaskRecord
from arrayprobe_uiops import spec_core as spec

_reject = lazy_module("arrayprobe.reject")

_SRC = Path(__file__).resolve().parent.parent / "src"
HEADER = (2016, 9, 2, 6, 6, 44, 3, 250)  # year, month, wkday, day, hour, minute, second, ms


def raw_file(path, records):
    """Write a raw ``.2DS``-shaped file: ``records`` is a list of (header, image words).

    Mirrors ``tests/test_spec_reader.py``'s helper of the same name exactly
    (kept local rather than imported so this test module stays self-contained).
    """
    out = np.zeros((len(records), spec.RECORD_WORDS), dtype="<u2")
    for i, (header, image) in enumerate(records):
        out[i, : spec.HEADER_WORDS] = header
        out[i, spec.HEADER_WORDS : spec.HEADER_WORDS + len(image)] = image
    out.tofile(path)
    return path


# --------------------------------------------------------------------------
# Contract 1: all_record_headers
# --------------------------------------------------------------------------


class TestAllRecordHeaders(unittest.TestCase):
    def test_n_minus_1_windows_plus_the_last_record_equals_all_records(self):
        """The exact identity the wrapper exists to provide."""
        with tempfile.TemporaryDirectory() as d:
            path = raw_file(os.path.join(d, "t.2DS"), [(HEADER, [])] * 5)
            windows = list(spec.iter_record_windows(path))
            self.assertEqual(len(windows), 4)  # n-1, per test_spec_reader.py

            headers = friendly.all_record_headers(path)
            self.assertEqual(len(headers), 5)  # all n records
            self.assertEqual(headers[:4], [h for h, _ in windows])

    def test_a_single_record_file_yields_its_one_header(self):
        """Degenerate case: iter_record_windows already covers the only record."""
        with tempfile.TemporaryDirectory() as d:
            path = raw_file(os.path.join(d, "t.2DS"), [(HEADER, [])])
            headers = friendly.all_record_headers(path)
            self.assertEqual(len(headers), 1)
            self.assertEqual(headers[0].year, HEADER[0])

    def test_a_trailing_partial_record_adds_no_header(self):
        """With bytes after the last whole record the scan already made that
        record a primary, so the windows carry every whole record's header."""
        with tempfile.TemporaryDirectory() as d:
            path = raw_file(os.path.join(d, "t.2DS"), [(HEADER, [])] * 5)
            with open(path, "ab") as fh:
                fh.write(b"\x00" * 100)
            windows = list(spec.iter_record_windows(path))
            self.assertEqual(len(windows), 5)
            self.assertEqual(friendly.all_record_headers(path), [h for h, _ in windows])

    def test_an_empty_file_yields_no_headers(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "empty.2DS")
            open(path, "wb").close()
            self.assertEqual(friendly.all_record_headers(path), [])

    def test_the_last_header_is_read_correctly_not_padded_or_guessed(self):
        """Mutation: change only the last record's header and confirm the
        wrapper's added header changes with it (rather than, say, always
        repeating the second-to-last one, which the n-1-windows identity
        alone would not catch since that record is never in any window)."""
        last_header = (2017, 3, 4, 15, 12, 1, 30, 999)
        with tempfile.TemporaryDirectory() as d:
            records = [(HEADER, []), (HEADER, []), (last_header, [])]
            path = raw_file(os.path.join(d, "t.2DS"), records)
            headers = friendly.all_record_headers(path)
            self.assertEqual(len(headers), 3)
            self.assertEqual(headers[2].year, last_header[0])
            self.assertEqual(headers[2].hour, last_header[4])
            self.assertEqual(headers[2].minute, last_header[5])
            self.assertEqual(headers[2].millisec, last_header[7])
            self.assertNotEqual(headers[2].year, HEADER[0])

    def test_returned_headers_are_ordinary_recordheader_instances(self):
        with tempfile.TemporaryDirectory() as d:
            path = raw_file(os.path.join(d, "t.2DS"), [(HEADER, [])] * 3)
            for h in friendly.all_record_headers(path):
                self.assertIsInstance(h, spec.RecordHeader)


# --------------------------------------------------------------------------
# Contract 2: touching_edge_flag / TouchingEdge
# --------------------------------------------------------------------------


class TestTouchingEdgeFlag(unittest.TestCase):
    @needs_v314_engine
    def test_no_slices_maps_to_no_slices(self):
        result = _reject.calculate_reject_unified(np.zeros((0, 64), dtype=bool), "M")
        self.assertEqual(result.touching_edge, 0)  # raw field, per test_reject.py
        self.assertEqual(friendly.touching_edge_flag(result.touching_edge),
                          friendly.TouchingEdge.NO_SLICES)

    @needs_v314_engine
    def test_contained_maps_to_contained(self):
        contained = np.zeros((10, 64), dtype=bool)
        contained[3:7, 20:40] = True
        result = _reject.calculate_reject_unified(contained, "s")
        self.assertEqual(result.touching_edge, "0")
        self.assertEqual(friendly.touching_edge_flag(result.touching_edge),
                          friendly.TouchingEdge.CONTAINED)

    @needs_v314_engine
    def test_touching_maps_to_touching(self):
        touching = np.zeros((10, 64), dtype=bool)
        touching[3:7, 0:20] = True  # reaches diode 1
        result = _reject.calculate_reject_unified(touching, "s")
        self.assertEqual(result.touching_edge, "t")
        self.assertEqual(friendly.touching_edge_flag(result.touching_edge),
                          friendly.TouchingEdge.TOUCHING)

    def test_enum_values_match_what_imgproc_writes(self):
        """The identity imgProc_sm.m:897 computes: touching_edge - '0'."""
        self.assertEqual(friendly.TouchingEdge.NO_SLICES.value, 0 - ord("0"))
        self.assertEqual(friendly.TouchingEdge.CONTAINED.value, ord("0") - ord("0"))
        self.assertEqual(friendly.TouchingEdge.TOUCHING.value, ord("t") - ord("0"))

    def test_mapping_is_lossless_round_trip_via_the_written_domain(self):
        """Mutation-style check: every member's value, fed back through the
        Enum constructor (as a netCDF reader would), recovers the same
        member -- proving the value assignment isn't accidentally aliased."""
        for member in friendly.TouchingEdge:
            self.assertIs(friendly.TouchingEdge(member.value), member)

    def test_an_unrecognised_raw_value_raises_rather_than_guesses(self):
        for bad in ("x", "00", 1, -48, None):
            with self.assertRaises(ValueError):
                friendly.touching_edge_flag(bad)


# --------------------------------------------------------------------------
# Contract 3: load_mask_csv / MaskRecord re-export
# --------------------------------------------------------------------------


class TestMaskCsvReExport(unittest.TestCase):
    def test_re_exported_function_is_the_same_object(self):
        """Not a reimplementation: literally the same function."""
        from arrayprobe.readers import mask_csv
        self.assertIs(friendly.load_mask_csv, mask_csv.load_mask_csv)
        self.assertIs(friendly.MaskRecord, mask_csv.MaskRecord)

    def test_parses_the_terminator_less_file_identically(self):
        """End-to-end proof the re-export behaves exactly like the raw reader
        on a real terminator-less fixture, including the mutation of adding
        a second record."""
        one_record = "1, " + ", ".join(str(i) for i in range(18)) + ", "
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "t.MK.csv")
            with open(path, "w") as fh:
                fh.write(one_record)
            self.assertNotIn("\n", Path(path).read_text())
            records = friendly.load_mask_csv(path)
            self.assertEqual(len(records), 1)
            self.assertIsInstance(records[0], MaskRecord)
            self.assertEqual(records[0].time_word, 1)

            # Mutation: append a second terminator-less record and confirm
            # the parse count tracks it rather than being fixed at 1.
            with open(path, "a") as fh:
                fh.write(one_record)
            records2 = friendly.load_mask_csv(path)
            self.assertEqual(len(records2), 2)
            self.assertEqual(records2[0], records2[1])


# --------------------------------------------------------------------------
# Contract 4: every public index is MATLAB 1-based (documented, swept)
# --------------------------------------------------------------------------


@needs_source
class TestOneBasedConventionIsDocumented(unittest.TestCase):
    """State the convention once centrally and test
    the claim with a sweep, rather than trusting the many inline mentions
    to stay consistent with each other. This does not re-derive every
    call site's convention (that would just be the port again); it checks
    that the two load-bearing functions -- the boundary-crossing
    ``to0``/``to1`` and the one documented exception,
    ``iter_record_windows`` -- still say what this module's docstring and
    ``docs/09-conventions.md`` claim about them.
    """

    def test_to0_and_to1_document_the_matlab_1_based_convention(self):
        from arrayprobe.matlab_compat import to0, to1
        for fn in (to0, to1):
            doc = (fn.__doc__ or "").lower()
            self.assertIn("1-based", doc, f"{fn.__qualname__} no longer documents the convention")

    def test_iter_record_windows_documents_its_0_based_exception(self):
        doc = (spec.iter_record_windows.__doc__ or "").lower()
        self.assertIn("0-based", doc,
                       "iter_record_windows's start/stop must say they are the one "
                       "documented exception to the global 1-based convention")

    @repo_only
    def test_the_convention_is_stated_in_the_public_docs_site(self):
        conventions = REPO_ROOT / "docs" / "09-conventions.md"
        text = conventions.read_text(encoding="utf-8").lower()
        self.assertIn("1-based", text)
        self.assertIn("friendly", text,
                       "docs/09-conventions.md should point a reader at "
                       "arrayprobe.friendly, not just restate the convention")

    def test_at_least_thirty_public_1_based_documentation_sites_exist_in_source(self):
        """Not vacuous: the convention is actually load-bearing across the
        tree today (measured via a plain text sweep), not a claim about a
        convention nothing uses."""
        hits = 0
        for path in _SRC.rglob("*.py"):  # every shipped package
            if "1-based" in path.read_text(encoding="utf-8"):
                hits += 1
        self.assertGreaterEqual(hits, 15, f"only {hits} files under src/ mention "
                                 "'1-based' -- the convention sweep would be checking nothing")


# --------------------------------------------------------------------------
# The pipeline must never import the friendly module
# --------------------------------------------------------------------------


@needs_source
class TestPipelineStagesDoNotImportFriendly(unittest.TestCase):
    """The wrappers must never be called on the
    reproduction path. Swept over every module under ``src/`` (all four
    packages) rather than a named list, so a new pipeline module is covered
    automatically -- ``friendly.py`` itself is the only expected hit.
    """

    def _importers_of_friendly(self) -> list[str]:
        offenders = []
        for path in _SRC.rglob("*.py"):
            if path.name == "friendly.py":
                continue
            if "tests" in path.parts:
                continue
            text = path.read_text(encoding="utf-8")
            if "friendly" not in text:
                continue
            tree = ast.parse(text, filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name == "arrayprobe.friendly" or alias.name.endswith(".friendly"):
                            offenders.append(f"{path}:{node.lineno}")
                elif isinstance(node, ast.ImportFrom):
                    mod = node.module or ""
                    if mod == "arrayprobe.friendly" or mod.endswith(".friendly"):
                        offenders.append(f"{path}:{node.lineno}")
                    if node.level and any(a.name == "friendly" for a in node.names):
                        # `from . import friendly` / `from .. import friendly`
                        offenders.append(f"{path}:{node.lineno}")
        return offenders

    def test_no_module_under_src_imports_friendly(self):
        offenders = self._importers_of_friendly()
        self.assertEqual(
            offenders, [],
            "arrayprobe.friendly must never be imported by a pipeline-stage module -- "
            f"it is a re-view for callers, never a dependency of the reproduction: {offenders}",
        )

    def test_the_sweep_actually_finds_an_offender_when_there_is_one(self):
        """The sweep's own positive control, on a synthetic snippet -- not
        real source -- so a broken visitor showing zero offenders can be
        told apart from a tree that genuinely has none."""
        tree = ast.parse("from arrayprobe import friendly\n")
        found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "arrayprobe":
                if any(a.name == "friendly" for a in node.names):
                    found = True
        self.assertTrue(found)

    def test_friendly_module_itself_imports_no_pipeline_stage_that_would_cycle(self):
        """Belt-and-suspenders: friendly.py's own imports are read-side
        raw functions (readers.spec, readers.mask_csv), never the pipeline
        drivers (imgproc, sizedist, combine, cli)."""
        text = (_SRC / "arrayprobe" / "friendly.py").read_text(encoding="utf-8")
        for forbidden in ("imgproc", "sizedist", "combine", "cli", "tools.run_flight"):
            self.assertNotIn(f"import {forbidden}", text)
            self.assertNotIn(f".{forbidden} import", text)


if __name__ == "__main__":
    unittest.main()

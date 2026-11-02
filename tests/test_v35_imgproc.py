# SPDX-License-Identifier: BSD-3-Clause
"""``arrayprobe_uiops.imgproc`` -- v3.5's ``imgProc_sm.m`` driver and writer (Part A).

Structural tests only: the variable table against the vendored file's own
``defVar``/``putAtt`` text, the writer against ``measure_record`` (the measurement-block
seam), the two preserved bugs, the refusals, and the reuse guard.  The
whole-chain Octave golden is Part B of the stage plan and is not here yet.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
from netCDF4 import Dataset
from tests import _upstream  # noqa: E402
from tests._repo import needs_v314_engine, repo_only

from arrayprobe import ncio
from arrayprobe_uiops import imgproc as v35_imgproc
from arrayprobe_uiops.imgproc import (
    PARTICLE_NUM_MODULUS_V35,
    PROBES_V35,
    SHARED_WITH_V314,
    WIDTH_MISMATCH_RETURNS,
    WRITER_GAPS,
    imgproc_sm_v35,
    imgproc_variables_v35,
    particle_num_v35,
)
from arrayprobe_uiops.measure import STOCK_V35_REJECT_CONFIG, RecordGeometry, measure_record

ROOT = Path(__file__).resolve().parents[1]
V35_IMGPROC_M = _upstream.source("uiops35") / "imgProc_sm.m"
V35_READ_BINARY_SPEC_M = _upstream.source("uiops35") / "read_binary_SPEC.m"
MEASURE_ORACLE = Path(__file__).resolve().parent / "data" / "v35_measure_oracle.json"
IMGPROC_ORACLE_PATH = Path(__file__).resolve().parent / "data" / "v35_imgproc_oracle.json"
IMGPROC_RAW_FIXTURE = Path(__file__).resolve().parent / "data" / "v35_imgproc_raw_fixture"
IMGPROC_ORACLE = json.loads(IMGPROC_ORACLE_PATH.read_text(encoding="utf-8"))

DS = PROBES_V35["2DS"].ds
TAS_TIME = np.array([60600.0, 60601.0, 60602.0, 60603.0])
TAS = np.array([120.0, 121.0, 122.0, 123.0])

#: ``:283-285``/``:297`` -- properties of the RUN (a caller-supplied path, a
#: timestamp), not of the file's content. Excluded from the golden comparison
#: the same way ``Creation Time`` always is; see ``TestAgainstTheOctaveGolden``.
_GOLDEN_NON_COMPARABLE_ATTRS = ("Creation Time", "Image Source",
                                "arrayprobe_engine", "arrayprobe_profile")


def setUpModule():
    # Raised here rather than at import: an import-time SkipTest crashes
    # ``python -m unittest tests.<module>``, where ``discover`` reports it as a skip.
    _upstream.require("uiops35")


def _run_port_chain(tmp, *, i_new_habit, tas_ratio, i_qc=0,
                    i_rect_ellipse=0, extended_ellipse_outputs=None):
    """The whole PORT chain -- ``read_binary_spec_v35`` then ``imgproc_sm_v35``
    -- on the SAME raw bytes :data:`IMGPROC_ORACLE` was built from, with the
    SAME arguments the Octave bank used. Both stages are the port's own code;
    this is an end-to-end check against the real vendored chain, not a
    transcription of either side.

    ``i_rect_ellipse``/``extended_ellipse_outputs`` (Part D) default to the
    Part B/C values (``0``/``None``) so every existing caller is unaffected;
    ``tests/test_v35_rect_ellipse.py::TestDegenerateImagesDoNotAbortThePort``
    is the only caller that overrides them, on this same 27-particle fixture,
    whose collinear particles abort the real MEX (A16) rather than golden it.
    """
    from arrayprobe_uiops.spec import read_binary_spec_v35

    stem = Path(tmp) / "decoded"
    n_h, _n_v = read_binary_spec_v35(
        IMGPROC_RAW_FIXTURE, stem, software="UIOOPS_v3.5",
        creation_time="2026/09/12 00:00:00", channels="H", sidecars=False,
    )
    assert n_h == IMGPROC_ORACLE["n_decoded_records"], (
        f"port decoded {n_h} H records, the golden's own bookkeeping recorded "
        f"{IMGPROC_ORACLE['n_decoded_records']}"
    )
    outfile = Path(tmp) / "out.proc.nc"
    imgproc_sm_v35(
        str(stem) + ".H.nc", outfile, "2DS", 1, 1000, "ORACLES",
        iCalcAllDiodeStats=1, iNewHabit=i_new_habit, iQC=i_qc,
        iRectEllipse=i_rect_ellipse, extended_ellipse_outputs=extended_ellipse_outputs,
        reject_config=STOCK_V35_REJECT_CONFIG,
        tas_time=IMGPROC_ORACLE["tas_time"], tas=IMGPROC_ORACLE["tas"],
        tas_ratio=tas_ratio, software="UIOOPS_v3.5",
        creation_time="2026/09/12 00:00:00",
    )
    return _read(outfile)


def _find_sphericity_growing_squares_record(variables: dict) -> list[int]:
    """The record built as three solid squares of side 2, 3, 4 diodes -- found
    by its own areas (``(k+2)**2`` diodes^2), not by a hardcoded record index,
    so a reordering of the bank's fixture cannot silently point this test at
    the wrong record."""
    parent = variables["parent_rec_num"]["values"]
    areas = variables["image_area"]["values"]
    groups: dict[float, list[int]] = {}
    for i, p in enumerate(parent):
        groups.setdefault(p, []).append(i)
    for idxs in groups.values():
        if len(idxs) != 3:
            continue
        diode_areas = [areas[i] / (DS * DS) for i in idxs]
        if all(abs(diode_areas[k] - (k + 2) ** 2) < 1e-6 for k in range(3)):
            return idxs
    raise AssertionError("no 3-particle growing-squares record found in the golden")


# --------------------------------------------------------------------------
# Input builder
# --------------------------------------------------------------------------

def _words_from_mask(mask: np.ndarray) -> np.ndarray:
    """A (slices x 128) boolean mask (True = shadowed) -> (slices x 8) data words.

    ``:792`` complements (``65535 - data``) and ``dec2bin(...,16)`` then reads
    ``'0'`` as shadowed, so a shadowed diode is a SET bit in the data word,
    most-significant bit first.  ``TestInputBuilder`` asserts this polarity
    through ``image_area`` rather than trusting this docstring.
    """
    m = np.asarray(mask, dtype=bool)
    assert m.shape[1] == 128
    words = np.zeros((m.shape[0], 8), dtype=np.int64)
    for k in range(8):
        bits = m[:, 16 * k:16 * (k + 1)]
        weights = 1 << np.arange(15, -1, -1)
        words[:, k] = (bits * weights).sum(axis=1)
    return words


def _record(particles, times, *, first_row_boundary=True) -> np.ndarray:
    """One 1700 x 8 ``data`` block: ``[boundary, header, slices...] * (P+1)``.

    ``imgProc_sm`` frames the image *between* two boundaries and takes the
    header that follows the terminating boundary (``header_loc = j+1``), so
    ``P`` particles need ``P+1`` boundary+header groups; ``times[k]`` is the
    clock count carried by group ``k+1``'s header, i.e. what particle ``k``
    receives.  ``-1`` fill terminates the scan (``:751``).
    """
    rows: list[np.ndarray] = []
    boundary = np.full(8, 43690, dtype=np.int64)

    def header(part_num, slice_count, clock):
        return np.array([0, 0, 0, 0, part_num, slice_count, clock >> 16, clock & 0xFFFF],
                        dtype=np.int64)

    rows.append(boundary)
    rows.append(header(0, 0, 0))
    for k, mask in enumerate(particles):
        for row in _words_from_mask(mask):
            rows.append(row)
        rows.append(boundary)
        rows.append(header(k + 1, np.asarray(mask).shape[0], int(times[k])))
    block = np.full((1700, 8), -1, dtype=np.int64)
    arr = np.asarray(rows)
    block[:arr.shape[0]] = arr
    return block


def _write_input(path, records, headers) -> None:
    """The v3.5 reader's ``.H.nc`` layout (``arrayprobe_uiops/spec.py::_ImageFileV35``)."""
    f = ncio.create(path, "clobber", format="NETCDF4")
    dim_time = f.def_dim("time", ncio.NC_UNLIMITED)
    dim_row = f.def_dim("ImgRowlen", 8)
    dim_block = f.def_dim("ImgBlocklen", 1700)
    tvars = (("year", "short"), ("month", "byte"), ("day", "byte"), ("hour", "byte"),
             ("minute", "byte"), ("second", "byte"), ("millisec", "short"), ("wkday", "byte"))
    varids = [f.def_var(n, t, dim_time) for n, t in tvars]
    varid_data = f.def_var("data", "int", [dim_row, dim_block, dim_time])
    f.def_var("tas", "double", dim_time)
    f.def_var("tasRatio", "double", dim_time)
    f.end_def()
    times = np.asarray(headers, dtype=np.int64)
    for k, vid in enumerate(varids):
        f.put_var(vid, 0, times.shape[0], times[:, k])
    block = np.stack(records)  # (n, 1700, 8) is already on-disk order
    ncio.write_record_block(f, varid_data, 0, block)
    f.close()


def _header(hour=6, minute=6, second=0, millisec=0):
    return (2016, 9, 6, hour, minute, second, millisec, 2)


def _square(top, left, size):
    m = np.zeros((size + 2, 128), dtype=bool)
    m[1:1 + size, left:left + size] = True
    return m


def _ring(top, left, size, hole):
    m = _square(top, left, size)
    h0 = 1 + (size - hole) // 2
    c0 = left + (size - hole) // 2
    m[h0:h0 + hole, c0:c0 + hole] = False
    return m


def _run(tmp, records, headers, **kw):
    infile = Path(tmp) / "in.H.nc"
    outfile = Path(tmp) / "out.proc.nc"
    _write_input(infile, records, headers)
    kw.setdefault("iNewHabit", 0)
    kw.setdefault("reject_config", STOCK_V35_REJECT_CONFIG)
    kw.setdefault("tas_time", TAS_TIME)
    kw.setdefault("tas", TAS)
    kw.setdefault("software", "UIOOPS_v3.5")
    kw.setdefault("creation_time", "2026/09/11 00:00:00")
    n = imgproc_sm_v35(infile, outfile, "2DS", 1, 1000, "ORACLES", **kw)
    return n, _read(outfile)


def _read(path) -> dict:
    out: dict = {"vars": {}, "order": [], "attrs": {}, "var_attrs": {}}
    with Dataset(path, "r") as ds:
        ds.set_auto_maskandscale(False)
        out["attrs"] = {k: ds.getncattr(k) for k in ds.ncattrs()}
        for name, v in ds.variables.items():
            out["order"].append(name)
            out["vars"][name] = np.asarray(v[:])
            out["var_attrs"][name] = {k: v.getncattr(k) for k in v.ncattrs()}
    return out


def _oracle_image(name: str) -> np.ndarray:
    cases = json.loads(MEASURE_ORACLE.read_text(encoding="utf-8"))["cases"]
    case = next(c for c in cases if c["name"] == name)
    im = case["images"][0]
    chars = np.array(list(im["flat"]), dtype="U1").reshape(im["rows"], im["cols"])
    return chars == "0"


# --------------------------------------------------------------------------
# Parsing the vendored file's own definition block
# --------------------------------------------------------------------------

_DIMS = {"dimid0": "time", "dimid1": "pos_count", "dimid2": "bin_count"}
_DEFVAR = re.compile(r"netcdf\.defVar\(f,\s*'(\w+)'\s*,\s*'(\w+)'\s*,\s*(\[[^\]]*\]|\w+)\)")
_PUTATT = re.compile(r"netcdf\.putAtt\(f,\s*varid\d+,\s*'(Units|Description)',\s*(.*)$")
_QUOTED = re.compile(r"'((?:[^']|'')*)'")

_GATES = {
    "probetype~=0 || probetype~=3": lambda g: True,
    "1==iQC": lambda g: g["iQC"] == 1,
    "1==iRectEllipse": lambda g: g["iRectEllipse"] == 1,
    "hasExtendedOutputs": lambda g: bool(g["extended_ellipse_outputs"]),
    "1 == iNewHabit": lambda g: g["iNewHabit"] == 1,
    "iCalcAllDiodeStats": lambda g: bool(g["iCalcAllDiodeStats"]),
}


def _parse_definitions(text: str):
    """(name, xtype, dims, units, description, gates) per LIVE defVar in ``:318-660``.

    Skips every line whose first non-blank character is ``%`` -- the five
    deleted diameters and ``RectangleX/Y`` are commented, not deleted.
    """
    lines = text.splitlines()
    first = next(i for i, ln in enumerate(lines) if "netcdf.defVar(f,'Date'" in ln)
    last = next(i for i, ln in enumerate(lines) if ln.strip().startswith("netcdf.endDef(f)"))
    out = []
    stack: list[tuple[str, bool]] = []
    i = first
    while i < last:
        ln = lines[i].strip()
        i += 1
        if not ln or ln.startswith("%"):
            continue
        while ln.endswith("...") and i < last:
            ln = ln[:-3] + lines[i].strip()
            i += 1
        if ln.startswith("if "):
            stack.append((ln[3:].split("%")[0].strip(), False))
            continue
        if ln.startswith("else"):
            stack[-1] = (stack[-1][0], True)
            continue
        if ln == "end":
            stack.pop()
            continue
        m = _DEFVAR.search(ln)
        if m:
            dims = tuple(_DIMS[d] for d in re.findall(r"dimid\d", m.group(3)))
            out.append({"name": m.group(1), "xtype": m.group(2), "dims": dims,
                        "Units": None, "Description": None, "gates": tuple(stack)})
            continue
        m = _PUTATT.search(ln)
        if m:
            value = "".join(s.replace("''", "'") for s in _QUOTED.findall(m.group(2)))
            # A putAtt under its own gate (holroyd_habit's Description) records
            # the gate with the value so the caller can pick the live one.
            key = m.group(1)
            if out[-1][key] is None or not stack:
                out[-1][key] = value
            else:
                out[-1].setdefault("gated", {})[(key, tuple(stack))] = value
    return out


def _live_table(flags):
    parsed = _parse_definitions(V35_IMGPROC_M.read_text(encoding="utf-8"))
    live = []
    for entry in parsed:
        ok = True
        for expr, is_else in entry["gates"]:
            truth = _GATES[expr](flags)
            ok = ok and (truth != is_else)
        if not ok:
            continue
        desc = entry["Description"]
        # holroyd_habit's Description is an if/else (:585-596): the parser
        # records the FIRST-seen branch (the `if`) as entry["Description"]
        # and the `else` branch keyed under "gated" by its own gate stack
        # (a 1-tuple, ``(("1 == iNewHabit", True),)``). This loop already
        # selects the right one for either flag value -- a since-removed
        # special case here duplicated the job with a mismatched tuple
        # nesting (looked up ``(first_gate[0], True)`` against a stored key
        # of ``((first_gate[0], True),)``) and raised KeyError for
        # iNewHabit=0. Two sides from two places still holds: this is a
        # bug in the parser, not in the vendored file or the port.
        for (key, gates), value in entry.get("gated", {}).items():
            if key != "Description":
                continue
            if all(_GATES[e](flags) != is_else for e, is_else in gates):
                desc = value
        live.append((entry["name"], entry["xtype"], entry["dims"], entry["Units"], desc))
    return live


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------

class TestInputBuilder(unittest.TestCase):
    def test_polarity_round_trips_through_image_area(self):
        """The builder's bit polarity is asserted, not assumed: a 4x4 square
        must come back as 16 shadowed diodes."""
        mask = _square(0, 60, 4)
        with tempfile.TemporaryDirectory() as tmp:
            n, got = _run(tmp, [_record([mask], [1000])], [_header()])
        self.assertEqual(n, 1)
        self.assertAlmostEqual(float(got["vars"]["image_area"][0]), 16 * DS * DS, places=12)
        self.assertEqual(int(got["vars"]["image_length"][0]), 4)
        self.assertEqual(int(got["vars"]["image_width"][0]), 4)


class TestVariableTableIsTheVendoredFiles(unittest.TestCase):
    """The port's table against the MATLAB text -- two sides from two places."""

    def _check(self, **flags):
        flags.setdefault("iRectEllipse", 0)
        flags.setdefault("iQC", 0)
        flags.setdefault("extended_ellipse_outputs", None)
        want = _live_table(flags)
        got = [(s.name, s.xtype, s.dims, s.units, s.description)
               for s in imgproc_variables_v35(probetype=2, **flags)]
        self.assertEqual([w[0] for w in want], [g[0] for g in got])
        for w, g in zip(want, got, strict=True):
            with self.subTest(variable=w[0]):
                self.assertEqual(g, w)

    @repo_only
    def test_newhabit0_alldiodestats1(self):
        self._check(iNewHabit=0, iCalcAllDiodeStats=1)

    @repo_only
    def test_newhabit1_alldiodestats1(self):
        self._check(iNewHabit=1, iCalcAllDiodeStats=1)

    @repo_only
    def test_newhabit0_alldiodestats0(self):
        self._check(iNewHabit=0, iCalcAllDiodeStats=0)

    @repo_only
    def test_rect_ellipse_ext0(self):
        """Part D: ``iRectEllipse=1``, the 3-output (old-binary) schema --
        six variables, no ``image_EllipseX``/``image_EllipseY``."""
        self._check(iNewHabit=0, iCalcAllDiodeStats=1, iRectEllipse=1,
                    extended_ellipse_outputs=False)

    @repo_only
    def test_rect_ellipse_ext1(self):
        """Part D: ``iRectEllipse=1``, the 5-output (``hasExtendedOutputs``)
        schema -- eight variables, including ``image_EllipseX``/``Y``."""
        self._check(iNewHabit=0, iCalcAllDiodeStats=1, iRectEllipse=1,
                    extended_ellipse_outputs=True)

    def test_ellipse_x_before_y(self):
        """``:548,:553`` -- ``image_EllipseX`` is defined before
        ``image_EllipseY`` in the vendored file, even though the *compute*
        side (``:1297``) assigns them in the opposite (Y, X) order."""
        names = [s.name for s in imgproc_variables_v35(
            iRectEllipse=1, iCalcAllDiodeStats=1, iQC=0, iNewHabit=0,
            extended_ellipse_outputs=True, probetype=2)]
        self.assertLess(names.index("image_EllipseX"), names.index("image_EllipseY"))

    @repo_only
    def test_the_parser_skipped_the_commented_diameters(self):
        names = [w[0] for w in _live_table(dict(iRectEllipse=0, iQC=0, iNewHabit=0,
                                                iCalcAllDiodeStats=1,
                                                extended_ellipse_outputs=None))]
        for gone in ("image_diam_circle_fit", "image_diam_horiz_chord",
                     "image_diam_horiz_chord_corr", "image_diam_following_bamex_code",
                     "image_diam_vert_chord"):
            self.assertNotIn(gone, names)
        text = V35_IMGPROC_M.read_text(encoding="utf-8")
        self.assertIn("% \tvarid21 = netcdf.defVar(f,'image_diam_circle_fit'", text)
        self.assertIn("sphericity", names)

    def test_the_file_order_is_the_written_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, got = _run(tmp, [_record([_square(0, 60, 4)], [1000])], [_header()],
                          iNewHabit=1, iCalcAllDiodeStats=1)
        want = [s.name for s in imgproc_variables_v35(
            iRectEllipse=0, iCalcAllDiodeStats=1, iQC=0, iNewHabit=1,
            extended_ellipse_outputs=None, probetype=2)]
        self.assertEqual(got["order"], want)
        for s in imgproc_variables_v35(iRectEllipse=0, iCalcAllDiodeStats=1, iQC=0,
                                       iNewHabit=1, extended_ellipse_outputs=None,
                                       probetype=2):
            self.assertEqual(got["var_attrs"][s.name],
                             {"Units": s.units, "Description": s.description})
        self.assertEqual(list(got["attrs"]), ["Software", "Creation Time", "Description",
                                              "Project", "Image Source", "Probe Type",
                                              "Optional parameters active",
                                              # Provenance: not MATLAB output, written after it.
                                              "arrayprobe_engine", "arrayprobe_profile"])
        self.assertEqual(got["attrs"]["Software"], "UIOOPS_v3.5")
        self.assertEqual(got["attrs"]["Optional parameters active"],
                         "Per-particle diode statistics")


class TestReuseIsNotAccidental(unittest.TestCase):
    @needs_v314_engine
    def test_the_shared_names_are_the_same_objects(self):
        from arrayprobe import imgproc as v314_imgproc
        for name in SHARED_WITH_V314:
            with self.subTest(name=name):
                self.assertIs(getattr(v35_imgproc, name), getattr(v314_imgproc, name))

    @needs_v314_engine
    def test_the_private_helpers_this_module_leans_on_still_exist(self):
        from arrayprobe import imgproc as v314_imgproc
        for name in ("_read_record_header", "_time_in_seconds_from_tas", "_one"):
            with self.subTest(name=name):
                self.assertTrue(hasattr(v314_imgproc, name))


class TestPreservedBugs(unittest.TestCase):
    def test_imgProc_858_particle_num_modulus_is_66536(self):  # noqa: N802
        """``:858`` -- ``mod(kk,66536)``; the v3.1.4 typo survives in v3.5."""
        self.assertEqual(PARTICLE_NUM_MODULUS_V35, 66536)
        self.assertEqual(particle_num_v35(66536), 0)
        self.assertEqual(particle_num_v35(66537), 1)
        self.assertEqual(particle_num_v35(65536), 65536)
        with tempfile.TemporaryDirectory() as tmp:
            _, got = _run(tmp, [_record([_square(0, 60, 4), _square(0, 70, 3)],
                                        [1000, 2000])], [_header()])
        np.testing.assert_array_equal(got["vars"]["particle_num"], [1, 2])

    def test_imgProc_1376_edge_at_max_hole_and_max_hole_diameter_are_swapped(self):  # noqa: N802
        """``:1376-1377`` -- varid29 (edge_at_max_hole) receives
        ``images.max_hole_diameter`` and varid30 the other way round."""
        ring = _oracle_image("small_ring_centred")
        geom = RecordGeometry(diodesize=DS, diodenum=128, tas_ratio=1.0, i_new_habit=0,
                              probename="2DS")
        p = measure_record([ring], geom, STOCK_V35_REJECT_CONFIG).particles[0]
        self.assertNotEqual(p.max_hole_diameter, p.edge_at_max_hole,
                            "the ring must make the two distinguishable")
        with tempfile.TemporaryDirectory() as tmp:
            _, got = _run(tmp, [_record([ring], [1000])], [_header()])
        self.assertEqual(int(got["vars"]["edge_at_max_hole"][0]), int(p.max_hole_diameter))
        self.assertEqual(int(got["vars"]["max_hole_diameter"][0]), int(p.edge_at_max_hole))

    def test_imgProc_850_width_mismatch_returns_silently(self):  # noqa: N802
        """``:850-853`` -- ``disp(...); return``: the record in hand is never
        written and the function exits with whatever earlier records wrote."""
        good = _record([_square(0, 60, 4)], [1000])
        bad = _record([_square(0, 60, 4)], [1000])
        bad[2, 1] = -1  # 65535 - (-1) = 65536 needs 17 bits -> 129 columns
        with tempfile.TemporaryDirectory() as tmp:
            n, got = _run(tmp, [good, bad], [_header(), _header(second=1)])
        self.assertEqual(n, 1)
        self.assertEqual(got["vars"]["image_area"].shape, (1,))
        # j is MATLAB's 1-based boundary-scan pointer (:751-780), the same j
        # that is live at :850. Traced by hand against the vendored file for
        # record 2 ("bad"): the record's rows (1-based) are 1=boundary,
        # 2=bootstrap header, 3-8=the 6 image-word rows (row 3's second word
        # corrupted), 9=the particle's closing boundary, 10=its header. The
        # first boundary (j=1) is the bootstrap pair and is discarded by the
        # `start > (j-1)` branch (:771, 1 > 0); the closing boundary is found
        # at j=9 (`isequal(data(j,1:8), boundary)` true, :756), where
        # `start > (j-1)` is now false (3 > 8) so :779 runs `header_loc=j+1;
        # w=w+1` with j still 9, and the width check at :850 fires with that
        # same j. (2, 6) had no derivation from the algorithm -- 6 is the
        # mask's own row count, not a scan position -- so it was the test's
        # misreading; (2, 9) is what a hand trace of :751-852 actually gives,
        # confirmed by the port's own value.
        self.assertEqual(WIDTH_MISMATCH_RETURNS, [(2, 9)])

    def test_imgProc_1272_sphericity_written_is_mrdivide_over_the_record(self):  # noqa: N802
        """``:1272`` -- the writer-level twin of the measurement block's own regression test,
        this time from the real Octave golden's written file rather than
        ``measure_record``'s return value: ``sphericity`` is exact for a
        record's first particle and diverges for every one after it, because
        ``:1382`` writes MATLAB mrdivide of the two GROWING row vectors
        ``image_area``/``image_perimeter``, not a per-particle ratio. See
        ``measure.py::sphericity_mrdivide`` for the port."""
        v = IMGPROC_ORACLE["cases"]["newhabit0_notas"]["variables"]
        idxs = _find_sphericity_growing_squares_record(v)
        area = [v["image_area"]["values"][i] for i in idxs]
        perim = [v["image_perimeter"]["values"][i] for i in idxs]
        written = [v["sphericity"]["values"][i] for i in idxs]
        per_particle = [math.sqrt(a) / p for a, p in zip(area, perim, strict=True)]
        self.assertAlmostEqual(written[0], per_particle[0], places=12)
        for k in (1, 2):
            with self.subTest(particle=k):
                self.assertNotAlmostEqual(written[k], per_particle[k], places=6)


class TestAgainstMeasureRecord(unittest.TestCase):
    """The a-half/b-half seam: every measurement variable equals its
    ``ParticleMeasurement`` field times its scale."""

    def _seam(self, i_new_habit, tas_ratio):
        parts = [_square(0, 60, 6), _oracle_image("small_ring_centred"), _square(0, 10, 3)]
        r = 1.0 if tas_ratio is None else tas_ratio
        geom = RecordGeometry(diodesize=DS, diodenum=128, tas_ratio=r,
                              i_new_habit=i_new_habit, probename="2DS",
                              i_calc_all_diode_stats=1)
        want = measure_record(parts, geom, STOCK_V35_REJECT_CONFIG)
        with tempfile.TemporaryDirectory() as tmp:
            n, got = _run(tmp, [_record(parts, [1000, 2000, 3000])], [_header()],
                          iNewHabit=i_new_habit, iCalcAllDiodeStats=1,
                          tas_ratio=None if tas_ratio is None else [tas_ratio])
        self.assertEqual(n, 3)
        v = got["vars"]
        scaled = {
            "image_length": ("image_length", 1), "image_width": ("image_width", 1),
            "image_area": ("image_area", DS * DS / r),
            "image_longest_y": ("longest_y_within_a_slice", 1),
            "image_max_top_edge_touching": ("max_top_edge_touching", 1),
            "image_max_bottom_edge_touching": ("max_bottom_edge_touching", 1),
            "image_hollow": ("is_hollow", 1), "image_center_in": ("center_in", 1),
            "image_axis_ratio": ("axis_ratio", 1), "image_diam_minR": ("minR", DS),
            "image_diam_AreaR": ("AreaR", DS), "image_perimeter": ("Perimeter", DS),
            "image_xpos": ("ctx", 1), "image_ypos": ("cty", 1),
            "part_z": ("part_z", 1), "size_factor": ("sf", 1),
            "fine_detail_ratio": ("FS", 1), "sphericity": ("sphericity", 1),
            "area_hole_ratio": ("area_hole_ratio", 1),
        }
        for name, (attr, scale) in scaled.items():
            with self.subTest(variable=name):
                np.testing.assert_allclose(
                    v[name], [getattr(p, attr) * scale for p in want.particles], rtol=1e-12)
        np.testing.assert_array_equal(v["holroyd_habit"],
                                      [ord(p.holroyd_habit) for p in want.particles])
        np.testing.assert_array_equal(v["image_auto_reject"],
                                      [ord(p.auto_reject) for p in want.particles])
        np.testing.assert_array_equal(v["bin_stats"], want.diode_stats_total)
        np.testing.assert_array_equal(v["image_bin_stats"],
                                      np.asarray([p.diode_stats for p in want.particles]))
        # percent_shadow_area is :1303-1309's circle form, not the reject function's.
        for k, p in enumerate(want.particles):
            L, W = p.image_length, p.image_width
            circle = p.image_area / (np.pi * max(L, W) ** 2 / 4) if max(L, W) else 0.0
            self.assertAlmostEqual(float(v["percent_shadow_area"][k]), circle, places=12)
        if i_new_habit:
            nh = [p.new_habit for p in want.particles]
            np.testing.assert_allclose(v["width_length_percentile"], [x.w_l_p * DS for x in nh])
            np.testing.assert_allclose(v["circle_area_ratio"], [x.c_r for x in nh])
            np.testing.assert_allclose(v["edge_maximum_dimension_ratio"], [x.e_d_r for x in nh])
            np.testing.assert_allclose(v["maximum_gap"], [x.m_g * DS for x in nh])
            np.testing.assert_allclose(v["opacity_coefficient"], [x.O for x in nh])
            np.testing.assert_allclose(v["aspect_ratio"], [x.a_r for x in nh])
            np.testing.assert_allclose(v["holroyd_perimeter"], [x.p * DS for x in nh])
        return v

    def test_newhabit0(self):
        self._seam(0, None)

    def test_newhabit1(self):
        self._seam(1, None)

    def test_newhabit1_tasratio(self):
        self._seam(1, 0.7)

    def test_bookkeeping_and_time(self):
        parts = [_square(0, 60, 6), _square(0, 10, 3)]
        with tempfile.TemporaryDirectory() as tmp:
            _, got = _run(tmp, [_record(parts, [1000, 2500]), _record(parts, [4000, 4600])],
                          [_header(second=0, millisec=7), _header(second=3, millisec=9)])
        v = got["vars"]
        np.testing.assert_array_equal(v["parent_rec_num"], [1, 1, 2, 2])
        np.testing.assert_array_equal(v["particle_num"], [1, 2, 1, 2])
        np.testing.assert_array_equal(v["Time"], [60600, 60600, 60603, 60603])
        np.testing.assert_array_equal(v["Date"], [20160906] * 4)
        np.testing.assert_array_equal(v["msec"], [7, 7, 9, 9])
        np.testing.assert_array_equal(v["particle_microsec"], [1000, 2500, 4000, 4600])
        np.testing.assert_array_equal(v["SliceCount"], [8, 5, 8, 5])
        np.testing.assert_array_equal(v["Particle_number_all"], [1, 2, 1, 2])
        np.testing.assert_array_equal(v["particle_time"], [0] * 4)
        np.testing.assert_array_equal(v["position"], [[3, 10], [13, 17], [3, 10], [13, 17]])
        # :1131-1170 with TAS 120 at 060600 and 123 at 060603, accumulated.
        s0 = DS / 1e3
        t = [1000 * s0 / 120]
        t.append(t[0] + 1500 * s0 / 120)
        t.append(t[1] + 1500 * s0 / 123)
        t.append(t[2] + 600 * s0 / 123)
        np.testing.assert_allclose(v["Time_in_seconds"], t, rtol=1e-12)
        # :1172-1176 -- int_arrival restarts at 0 in every record (probetype 2).
        np.testing.assert_allclose(v["inter_arrival"], [0, t[1] - t[0], 0, t[3] - t[2]],
                                   rtol=1e-12)

    def test_the_170_fallback_when_the_record_second_has_no_tas(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, got = _run(tmp, [_record([_square(0, 60, 4)], [1200])],
                          [_header(hour=7)])  # 070600 is not in TAS_TIME
        self.assertAlmostEqual(float(got["vars"]["Time_in_seconds"][0]),
                               1200 * DS / 1e3 / 170.0, places=15)


class TestTasRatioReachesTheFile(unittest.TestCase):
    def test_which_variables_move(self):
        parts = [_square(0, 60, 6), _oracle_image("small_ring_centred")]
        with tempfile.TemporaryDirectory() as tmp:
            _, a = _run(tmp, [_record(parts, [1000, 2000])], [_header()])
        with tempfile.TemporaryDirectory() as tmp:
            _, b = _run(tmp, [_record(parts, [1000, 2000])], [_header()], tas_ratio=[0.7])
        for name in ("image_area", "image_diam_AreaR", "image_perimeter", "image_xpos"):
            with self.subTest(variable=name):
                self.assertFalse(np.allclose(a["vars"][name], b["vars"][name]))
        for name in ("image_length", "Time", "Time_in_seconds", "image_ypos"):
            with self.subTest(variable=name):
                np.testing.assert_array_equal(a["vars"][name], b["vars"][name])
        np.testing.assert_allclose(b["vars"]["image_area"], a["vars"]["image_area"] / 0.7)


class TestRefusals(unittest.TestCase):
    def _kw(self, **over):
        kw = dict(iNewHabit=0, tas_time=TAS_TIME, tas=TAS, software="UIOOPS_v3.5",
                  reject_config=STOCK_V35_REJECT_CONFIG)
        kw.update(over)
        return kw

    def test_the_reject_configuration_is_required(self):
        """`imgProc_sm.m` reads its reject thresholds from
        `calculate_reject_unified.m`'s own unconditional assignments, and the
        ORACLES production tree ships a modified copy of that file. So the
        configuration is a fidelity decision, so
        no default may silently pick a side.

        This driver HARDCODED `STOCK_V35_REJECT_CONFIG` until 2026-09-12 --
        worse than a default, because a caller could not override it even
        deliberately, and it put one of the end-to-end validation's three Octave goldens
        (`oraclesprod_v35.nc`, run against the production reject tree) out of
        reach entirely. `test_profile_is_never_defaulted.py` could not catch it:
        that sweep looks for a parameter WITH a default, and this was a
        parameter that did not exist.
        """
        kw = self._kw()
        kw.pop("reject_config")
        with self.assertRaises(TypeError) as cm:
            imgproc_sm_v35("x", "y", "2DS", 1, 1, "P", **kw)
        self.assertIn("reject_config", str(cm.exception))

    def test_rect_ellipse_without_the_flag(self):
        with self.assertRaisesRegex(ValueError, "extended_ellipse_outputs"):
            imgproc_sm_v35("x", "y", "2DS", 1, 1, "P", iRectEllipse=1, **self._kw())

    def test_the_flag_without_rect_ellipse(self):
        with self.assertRaisesRegex(ValueError, "iRectEllipse=1"):
            imgproc_sm_v35("x", "y", "2DS", 1, 1, "P", extended_ellipse_outputs=True,
                           **self._kw())

    def test_rect_ellipse_no_longer_refused(self):
        """Part D (2026-09-13): ``iRectEllipse=1`` is ported
        (:func:`arrayprobe_uiops.rect_ellipse.rect_ellipse_for_image`); a call
        with it must not raise ``NotImplementedError`` -- it fails downstream
        on the fake ``"x"`` path instead, same as every other refusal-class
        test above that reaches real I/O."""
        with self.assertRaises(FileNotFoundError):
            imgproc_sm_v35("x", "y", "2DS", 1, 1, "P", iRectEllipse=1,
                           extended_ellipse_outputs=False, **self._kw())

    def test_iqc_no_longer_refused(self):
        """Part C (2026-09-13): ``iQC=1`` (the ``:801-846`` denoise pass) is
        ported (:func:`arrayprobe_uiops.qc.qc_image`); a whole-chain call with
        it must not raise ``NotImplementedError``."""
        with tempfile.TemporaryDirectory() as tmp:
            n, got = _run(tmp, [_record([_square(0, 60, 4)], [1000])], [_header()], iQC=1)
        self.assertEqual(n, 1)
        self.assertIn("subparticle_num", got["vars"])
        self.assertIn("subparticle_mindist", got["vars"])

    def test_probetype_not_2_no_longer_refused(self):
        """V-PT (2026-09-16): every probetype the v3.5 MATLAB handles is ported.

        The five non-probetype-2 probes used to raise ``UnportedProbeType``
        here. They must not any more -- each now reaches real I/O and fails on
        the fake ``"x"`` path, the same way every other ported-path refusal
        test in this class does.  ``tas_time``/``tas`` must be ``None``,
        because ``imgProc_sm.m``'s probe switch assigns ``varargin{1,2}`` only
        in the probetype-2 arms.
        """
        kw = self._kw()
        kw["tas_time"] = None
        kw["tas"] = None
        for name in ("2DC", "2DP", "CIP", "PIP", "Fast2DC"):
            with self.subTest(probe=name), self.assertRaises(FileNotFoundError):
                imgproc_sm_v35("x", "y", name, 1, 1, "P", **kw)

    def test_the_refusal_still_fires_for_an_unported_timing(self):
        """Narrowed, not deleted: ``UnportedProbeType`` must still fire for a
        probe whose timing branch has no transcription, and must name it."""
        probe = v35_imgproc.ProbeV35((1, 2, 3), 0, 0.01, 64, 9, timing="martian")
        with mock.patch.dict(v35_imgproc.PROBES_V35, {"MARS": probe}), \
                self.assertRaisesRegex(v35_imgproc.UnportedProbeType,
                                       r"probetype 9 \('martian' timing\)"):
            imgproc_sm_v35("x", "y", "MARS", 1, 1, "P",
                           **{**self._kw(), "tas_time": None, "tas": None})

    def test_tas_is_required_for_probetype_2_and_refused_otherwise(self):
        with self.assertRaisesRegex(ValueError, "probetype 2"):
            imgproc_sm_v35("x", "y", "2DS", 1, 1, "P",
                           **{**self._kw(), "tas_time": None, "tas": None})
        with self.assertRaisesRegex(ValueError, "probetype 0"):
            imgproc_sm_v35("x", "y", "2DC", 1, 1, "P", **self._kw())

    def test_unknown_probe(self):
        with self.assertRaises(ValueError):
            imgproc_sm_v35("x", "y", "2DX", 1, 1, "P", **self._kw())

    def test_short_tas_ratio_names_the_record(self):
        with tempfile.TemporaryDirectory() as tmp, \
                self.assertRaisesRegex(IndexError, r"tasRatio\(2\)"):
            _run(tmp, [_record([_square(0, 60, 4)], [1000])] * 2,
                 [_header(), _header(second=1)], tas_ratio=[1.0])

    def test_required_arguments_have_no_default(self):
        for missing in ("iNewHabit", "tas_time", "tas", "software"):
            kw = self._kw()
            del kw[missing]
            with self.subTest(missing=missing), self.assertRaises(TypeError):
                imgproc_sm_v35("x", "y", "2DS", 1, 1, "P", **kw)

    def test_the_probe_table_is_the_v35_one(self):
        self.assertEqual(PROBES_V35["2DC"].ds, 0.03)         # :141, was 0.025
        self.assertEqual(PROBES_V35["3VCPI_H"].ds, 0.050)     # :207
        self.assertEqual(PROBES_V35["3VCPI_V"].ds, 0.010)     # :219
        for name in ("HVPS", "2DS", "3VCPI_H", "3VCPI_V"):
            self.assertEqual(PROBES_V35[name].probetype, 2)
            self.assertEqual(PROBES_V35[name].boundary, (43690,) * 8)
            self.assertEqual(PROBES_V35[name].boundarytime, 0)


class TestIQCDefaultIsZero(unittest.TestCase):
    def test_default_iqc_is_zero_and_output_is_unchanged(self):
        """Part C (2026-09-13) added ``iQC=1``. The default -- ``iQC`` left
        unspecified -- must write exactly what it wrote before this stage: no
        ``subparticle_*`` columns, and the same values an explicit ``iQC=0``
        call produces."""
        with tempfile.TemporaryDirectory() as tmp:
            _, default = _run(tmp, [_record([_square(0, 60, 4)], [1000])], [_header()])
        with tempfile.TemporaryDirectory() as tmp:
            _, explicit = _run(tmp, [_record([_square(0, 60, 4)], [1000])], [_header()], iQC=0)
        self.assertNotIn("subparticle_num", default["vars"])
        self.assertNotIn("subparticle_mindist", default["vars"])
        self.assertEqual(default["order"], explicit["order"])
        for name in default["vars"]:
            with self.subTest(variable=name):
                np.testing.assert_array_equal(default["vars"][name], explicit["vars"][name])


class TestWriterGaps(unittest.TestCase):
    def test_the_gap_is_named(self):
        self.assertEqual(WRITER_GAPS, ("deflate", "chunking"))

    def test_deflate_changes_no_value_that_is_read_back(self):
        values = np.arange(-5, 5, dtype=np.float64) / 7.0
        out = []
        with tempfile.TemporaryDirectory() as tmp:
            for label, kw in (("plain", {}),
                              ("deflated", {"zlib": True, "complevel": 9, "shuffle": True})):
                path = Path(tmp) / f"{label}.nc"
                with Dataset(path, "w", format="NETCDF4") as ds:
                    ds.createDimension("time", None)
                    var = ds.createVariable("x", "f8", ("time",), **kw)
                    var[:] = values
                with Dataset(path, "r") as ds:
                    ds.set_auto_maskandscale(False)
                    out.append(np.asarray(ds.variables["x"][:]))
        np.testing.assert_array_equal(out[0], out[1])

    @repo_only
    def test_the_vendored_file_really_deflates_every_variable(self):
        text = V35_IMGPROC_M.read_text(encoding="utf-8")
        live = [ln for ln in text.splitlines() if not ln.strip().startswith("%")]
        n_def = sum("netcdf.defVar(" in ln for ln in live)
        n_deflate = sum("netcdf.defVarDeflate(" in ln for ln in live)
        self.assertEqual(n_def, n_deflate)
        self.assertGreater(n_def, 40)


class TestTheGoldenIsWhatItClaims(unittest.TestCase):
    """Both sides of Part B's golden, checked against what it claims to be --
    the same discipline ``test_v35_spec.py``/``test_v35_measure.py`` use."""

    def test_raw_fixture_hash(self):
        got = hashlib.sha256(IMGPROC_RAW_FIXTURE.read_bytes()).hexdigest()
        self.assertEqual(got, IMGPROC_ORACLE["raw_fixture_sha256"])

    @repo_only
    def test_vendored_imgproc_sm_hash(self):
        got = hashlib.sha256(V35_IMGPROC_M.read_bytes()).hexdigest()
        self.assertEqual(got, IMGPROC_ORACLE["imgproc_sm_sha256"])

    @repo_only
    def test_vendored_read_binary_spec_hash(self):
        got = hashlib.sha256(V35_READ_BINARY_SPEC_M.read_bytes()).hexdigest()
        self.assertEqual(got, IMGPROC_ORACLE["read_binary_spec_sha256"])

    def test_six_cases_present(self):
        self.assertEqual(set(IMGPROC_ORACLE["cases"]),
                         {"newhabit0_notas", "newhabit1_notas",
                          "newhabit0_tasratio", "newhabit1_tasratio",
                          "newhabit0_notas_qc1", "newhabit1_notas_qc1"})

    def test_qc1_cases_have_the_two_subparticle_variables(self):
        for case in ("newhabit0_notas_qc1", "newhabit1_notas_qc1"):
            with self.subTest(case=case):
                self.assertIn("subparticle_num", IMGPROC_ORACLE["cases"][case]["variables"])
                self.assertIn("subparticle_mindist",
                             IMGPROC_ORACLE["cases"][case]["variables"])

    def test_qc0_cases_do_not(self):
        for case in ("newhabit0_notas", "newhabit1_notas",
                     "newhabit0_tasratio", "newhabit1_tasratio"):
            with self.subTest(case=case):
                self.assertNotIn("subparticle_num", IMGPROC_ORACLE["cases"][case]["variables"])
                self.assertNotIn("subparticle_mindist",
                                IMGPROC_ORACLE["cases"][case]["variables"])

    def test_newhabit1_cases_have_the_seven_extra_variables(self):
        seven = ("width_length_percentile", "circle_area_ratio",
                "edge_maximum_dimension_ratio", "maximum_gap",
                "opacity_coefficient", "aspect_ratio", "holroyd_perimeter")
        for case in ("newhabit1_notas", "newhabit1_tasratio"):
            with self.subTest(case=case):
                for name in seven:
                    self.assertIn(name, IMGPROC_ORACLE["cases"][case]["variables"])
        for case in ("newhabit0_notas", "newhabit0_tasratio"):
            with self.subTest(case=case):
                for name in seven:
                    self.assertNotIn(name, IMGPROC_ORACLE["cases"][case]["variables"])

    @repo_only
    def test_textual_anchors_still_present(self):
        """Anchors, never line numbers -- a re-vendor that moves lines but
        keeps these strings still validates; one that removes them fails
        loudly instead of silently comparing against a golden that no longer
        describes the file on disk."""
        text = V35_IMGPROC_M.read_text(encoding="utf-8")
        for anchor in ("%% Determine the Particle Habit", "mod(kk,66536)",
                      "netcdf.putVar ( f, varid29", "hasExtendedOutputs", "if 1==iQC"):
            with self.subTest(anchor=anchor):
                self.assertIn(anchor, text)

    def test_no_width_mismatches_and_no_korolev_warnings(self):
        """Measured, not assumed: this fixture's particles never hit
        ``:850-853`` and the ``:1277`` Korolev warning never fires -- matching
        the measurement block's own derivation that the only path to ``ihollow=1`` also forces
        habit ``'s'``, so the warning's ``habit != 's'`` condition is
        unreachable from this driver."""
        for case in IMGPROC_ORACLE["cases"].values():
            self.assertEqual(case["n_width_mismatch"], 0)
            self.assertEqual(case["n_korolev_warning"], 0)


class TestAgainstTheOctaveGolden(unittest.TestCase):
    """The port's own chain -- ``read_binary_spec_v35`` then ``imgproc_sm_v35``
    -- against the real, unmodified vendored v3.5 chain's own output. Every
    variable, every variable attribute, every global attribute but the two
    named in :data:`_GOLDEN_NON_COMPARABLE_ATTRS`, and the variable order."""

    _CASES = {
        "newhabit0_notas": dict(i_new_habit=0, tas_ratio=None),
        "newhabit1_notas": dict(i_new_habit=1, tas_ratio=None),
        "newhabit0_tasratio": dict(
            i_new_habit=0, tas_ratio=[0.7] * IMGPROC_ORACLE["n_decoded_records"]),
        "newhabit1_tasratio": dict(
            i_new_habit=1, tas_ratio=[0.7] * IMGPROC_ORACLE["n_decoded_records"]),
        "newhabit0_notas_qc1": dict(i_new_habit=0, tas_ratio=None, i_qc=1),
        "newhabit1_notas_qc1": dict(i_new_habit=1, tas_ratio=None, i_qc=1),
    }

    def _check_case(self, case_name):
        kw = self._CASES[case_name]
        with tempfile.TemporaryDirectory() as tmp:
            got = _run_port_chain(tmp, **kw)
        golden = IMGPROC_ORACLE["cases"][case_name]

        self.assertEqual(got["order"], golden["order"],
                         "the port's variable order must equal the golden's")

        spec_table = {s.name: s.xtype for s in imgproc_variables_v35(
            iRectEllipse=0, iCalcAllDiodeStats=1, iQC=kw.get("i_qc", 0),
            iNewHabit=kw["i_new_habit"],
            extended_ellipse_outputs=None, probetype=2)}
        self.assertEqual(set(got["vars"]), set(golden["variables"]))
        for name in golden["variables"]:
            with self.subTest(variable=name):
                want = np.asarray(golden["variables"][name]["values"])
                have = np.asarray(got["vars"][name])
                if spec_table[name] == "double":
                    np.testing.assert_allclose(have.astype(float), want.astype(float),
                                               rtol=1e-9, equal_nan=True)
                else:
                    np.testing.assert_array_equal(have, want)
                self.assertEqual(dict(got["var_attrs"][name]),
                                 golden["variables"][name]["attrs"])

        for key, value in golden["global_attributes"].items():
            if key in _GOLDEN_NON_COMPARABLE_ATTRS:
                continue
            with self.subTest(attribute=key):
                self.assertEqual(str(got["attrs"][key]), value)

    def test_newhabit0_notas(self):
        self._check_case("newhabit0_notas")

    def test_newhabit1_notas(self):
        self._check_case("newhabit1_notas")

    def test_newhabit0_tasratio(self):
        self._check_case("newhabit0_tasratio")

    def test_newhabit1_tasratio(self):
        self._check_case("newhabit1_tasratio")

    def test_newhabit0_qc1(self):
        self._check_case("newhabit0_notas_qc1")

    def test_newhabit1_qc1(self):
        self._check_case("newhabit1_notas_qc1")

    def test_tasratio_cases_differ_from_notas_as_TestTasRatioReachesTheFile_says(self):  # noqa: N802,E501
        """Same predicate as ``TestTasRatioReachesTheFile`` (Part A), now
        checked against the real Octave golden's fuller, less symmetric
        particle set rather than a hand-built two-particle record.

        ``image_ypos`` is deliberately NOT asserted unchanged here, unlike
        Part A's version of this test. Measured on this fixture: for an
        irregular (random-blob) particle, scaling every shadowed pixel's
        SLICE coordinate by ``1/tasRatio`` before ``CGAL_minR`` computes the
        minimum enclosing circle can change *which* pixels are extremal, which
        moves the fitted circle's centre on BOTH axes -- ``cty`` is not scaled
        directly, but it is a function of the whole (now differently-scaled)
        point set. Part A's claim held only because its two particles (a
        solid square and a centred ring) are symmetric enough that x-axis
        scaling cannot change the extremal set. Generalizing that claim to
        arbitrary geometry was this test's own error, not a port defect;
        corrected here rather than carried into the design record as a
        surprise."""
        with tempfile.TemporaryDirectory() as tmp:
            a = _run_port_chain(tmp, i_new_habit=0, tas_ratio=None)
        with tempfile.TemporaryDirectory() as tmp:
            b = _run_port_chain(tmp, i_new_habit=0,
                                tas_ratio=[0.7] * IMGPROC_ORACLE["n_decoded_records"])
        for name in ("image_area", "image_diam_AreaR", "image_perimeter", "image_xpos"):
            with self.subTest(variable=name):
                self.assertFalse(np.allclose(a["vars"][name], b["vars"][name]))
        for name in ("image_length", "Time"):
            with self.subTest(variable=name):
                np.testing.assert_array_equal(a["vars"][name], b["vars"][name])


if __name__ == "__main__":
    unittest.main()

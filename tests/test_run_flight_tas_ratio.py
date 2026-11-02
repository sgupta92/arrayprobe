# SPDX-License-Identifier: BSD-3-Clause
"""--tas-ratio: opt-in aircraft TAS series for UIOOPS v3.5's decoder (read_binary_SPEC.m:176-193).

Off by default and byte-identical when off (the S2 stamp keeps ``tas_ratio=off`` verbatim and
the decoder receives no flight series); on needs an aircraft airspeed source and v3.5.
"""
from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np
from tests import _run_flight_state
from tests._repo import needs_v314_engine  # noqa: E402

from arrayprobe.driver import run_flight

V35 = ("--engine", "3.5", "--profile", "stock-v3.5")


class _Globals(unittest.TestCase):
    def setUp(self):
        _run_flight_state.preserve(self, run_flight)
        self._saved = (run_flight.TAS_RATIO, run_flight.TAS_FILE)

    def tearDown(self):
        run_flight.TAS_RATIO, run_flight.TAS_FILE = self._saved


class TestOffIsTheDefault(_Globals):
    def test_parser_default_is_off(self):
        self.assertEqual(run_flight.TAS_RATIO, False)

    def test_off_passes_no_series_and_stamps_off(self):
        run_flight.TAS_RATIO = False
        self.assertEqual(run_flight._tas_ratio_series(), (None, None))
        self.assertEqual(run_flight._tas_ratio_stamp(), "tas_ratio=off")


class TestOnPassesTheAircraftSeries(_Globals):
    def test_on_reads_the_aircraft_file_and_stamps_it(self):
        run_flight.TAS_RATIO = True
        run_flight.TAS_FILE = str(Path("C:/x/aircraft_tas.nc"))
        series = SimpleNamespace(time_hhmmss=[120000, 120001], tas_mps=[150.0, 151.0])
        with mock.patch.object(run_flight._tas_sources, "read_aircraft",
                               return_value=series) as ra, \
             mock.patch.object(run_flight._tas_sources, "substitute",
                               return_value=([150.0, 151.0], [])):
            t, v = run_flight._tas_ratio_series()
        ra.assert_called_once_with(run_flight.TAS_FILE)
        self.assertEqual(t, [120000, 120001])
        self.assertEqual(v, [150.0, 151.0])
        self.assertEqual(run_flight._tas_ratio_stamp(),
                         "tas_ratio=on tas_ratio_src=aircraft_tas.nc")


class TestOnResolvesTheSourceChainBeforeTheDecode(_Globals):
    """``--tas-ratio on --tas-source aircraft --tas-search DIR`` (2026-10-05, the 0706 ARM run).

    The per-file loop resolves the chain only after S2, so ``TAS_FILE`` is still ``None`` when
    the decoder needs the series; the series must be resolved for the raw file's own date at S2.
    """

    def setUp(self):
        super().setUp()
        self._saved_src = (run_flight.TAS_SOURCE, run_flight.TAS_SEARCH)
        run_flight.TAS_RATIO = True
        run_flight.TAS_FILE = None
        run_flight.TAS_SOURCE = "aircraft"
        run_flight.TAS_SEARCH = [str(Path("C:/arm"))]

    def tearDown(self):
        run_flight.TAS_SOURCE, run_flight.TAS_SEARCH = self._saved_src
        super().tearDown()

    def _chain(self, tier="aircraft"):
        return SimpleNamespace(tier=tier, time=np.array([82819.0, 82820.0]),
                               tas=np.array([120.0, 121.0]), lines=["TAS chain: used"])

    def test_aircraft_source_series_reaches_the_decoder_call(self):
        raw = Path("C:/arm/base170706082819.2DS")
        with mock.patch.object(run_flight._tas_sources, "resolve_chain",
                               return_value=self._chain()) as rc, \
             redirect_stdout(io.StringIO()):
            t, v = run_flight._tas_ratio_series(raw)
        rc.assert_called_once()
        self.assertEqual(rc.call_args.args, ("aircraft",))
        kw = rc.call_args.kwargs
        self.assertEqual(kw["yyyymmdd"], "20170706")
        self.assertEqual(kw["search_dirs"], [str(Path("C:/arm"))])
        self.assertIsNone(kw["probe_csv"])
        self.assertEqual(t, [82819.0, 82820.0])
        self.assertEqual(v, [120.0, 121.0])

    def test_a_chain_that_lands_on_the_probe_tier_is_refused(self):
        with mock.patch.object(run_flight._tas_sources, "resolve_chain",
                               return_value=self._chain("probe")), \
             redirect_stdout(io.StringIO()), \
             self.assertRaisesRegex(RuntimeError, "aircraft airspeed"):
            run_flight._tas_ratio_series(Path("base170706082819.2DS"))

    def test_stamp_names_the_chain_and_survives_the_per_file_chain_path(self):
        before = run_flight._tas_ratio_stamp()
        self.assertEqual(before, "tas_ratio=on tas_ratio_src=chain:aircraft")
        run_flight.TAS_FILE = str(Path("C:/out/base170706082819.tas_aircraft.cdf"))
        self.assertEqual(run_flight._tas_ratio_stamp(), before)

    def test_stage2_hands_the_raw_file_to_the_series_resolver(self):
        import inspect
        src = inspect.getsource(run_flight.stage2)
        self.assertIn("_tas_ratio_series(raw)", src)


class TestRefusals(_Globals):
    def _main(self, *extra):
        with tempfile.TemporaryDirectory() as d:
            raw = Path(d) / "base160101000000.2DS"
            raw.write_bytes(b"")
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = run_flight.main(["--preset", "DEMO_2DS_H", *extra, "--stages", "2",
                                      "--yes", "--out", d, str(raw)])
        return rc, buf.getvalue()

    def test_on_without_an_aircraft_source_is_refused(self):
        rc, out = self._main(*V35, "--tas-ratio", "on")
        self.assertEqual(rc, 2, out)
        self.assertIn("--tas-source", out)
        self.assertIn("--tas-file", out)

    @needs_v314_engine
    def test_on_with_engine_3_1_4_is_refused(self):
        rc, out = self._main("--engine", "3.1.4", "--port-validation", "--tas-ratio", "on")
        self.assertEqual(rc, 2, out)
        self.assertIn("--tas-ratio on", out)

    def test_on_with_parallel_decode_is_not_refused(self):
        # addc39e refused this pair while the parallel decode passed no flight series; it now
        # does (TestEveryDecodePathReceivesTheSeries), so main() hands it to stage2 intact.
        with mock.patch.object(run_flight, "stage2"):
            rc, out = self._main(*V35, "--tas-ratio", "on", "--tas-file",
                                 str(Path("C:/x/aircraft_tas.nc")), "--s2-jobs", "2")
        self.assertNotIn("Drop --s2-jobs", out)
        self.assertNotIn("serial-decode only", out)
        self.assertNotIn("does not write tasRatio", out)


def _decode(d: str, stamp: str, ratios=None) -> Path:
    """A synthetic S2 decode: a netCDF with ``time`` (and ``tasRatio`` if given), stamped."""
    import netCDF4
    image = Path(d) / "base160101000000.H.nc"
    with netCDF4.Dataset(str(image), "w", format="NETCDF3_CLASSIC") as ds:
        ds.createDimension("time", 3)
        if ratios is not None:
            ds.createVariable("tasRatio", "f8", ("time",))[:] = ratios
    run_flight.write_stamp(image, stamp)
    return image


class TestS3ReceivesTheRatio(_Globals):
    def _forwarded(self, image: Path):
        engine = mock.Mock()
        mod = SimpleNamespace(PROBES_V35={"2DS": SimpleNamespace(probetype=1)},
                              imgproc_sm_v35=mock.Mock(return_value=0))
        engine.module.return_value = mod
        with mock.patch.object(run_flight, "ENGINE", "3.5"), \
             mock.patch.object(run_flight, "PROBE", "2DS"), \
             mock.patch.object(run_flight, "_v35", return_value=engine), \
             mock.patch.object(run_flight, "_resolve_reject", return_value=None), \
             mock.patch.object(run_flight, "_s3_tas_qc_v35", return_value=None):
            run_flight._imgproc_sm_chunk(image, image.with_name("proc.nc"), 1, 3)
        return mod.imgproc_sm_v35.call_args.kwargs["tas_ratio"]

    def test_on_forwards_the_decodes_tasRatio_to_imgproc(self):
        run_flight.TAS_RATIO = True
        with tempfile.TemporaryDirectory() as d:
            image = _decode(d, "engine=3.5 tas_ratio=on tas_ratio_src=a.nc", [0.5, 1.0, 2.0])
            got = self._forwarded(image)
        self.assertEqual(list(got), [0.5, 1.0, 2.0])

    def test_off_forwards_none(self):
        run_flight.TAS_RATIO = False
        with tempfile.TemporaryDirectory() as d:
            image = _decode(d, "engine=3.5 tas_ratio=off")
            self.assertIsNone(self._forwarded(image))

    def test_proc_stamp_records_the_ratio(self):
        run_flight.TAS_RATIO = False
        self.assertIn("tas_ratio=off)", run_flight.V35_CALL.imgproc_stamp())
        self.assertIn("tas_ratio=on)", run_flight.V35_CALL.imgproc_stamp("on"))


class TestMismatchedDecodeIsRefused(_Globals):
    def test_on_over_a_decode_stamped_off_is_refused(self):
        run_flight.TAS_RATIO = True
        with tempfile.TemporaryDirectory() as d:
            image = _decode(d, "engine=3.5 tas_ratio=off")
            with self.assertRaises(run_flight.UnverifiableProvenance):
                run_flight._s3_tas_ratio(image)

    def test_off_over_a_decode_stamped_on_is_refused(self):
        run_flight.TAS_RATIO = False
        with tempfile.TemporaryDirectory() as d:
            image = _decode(d, "engine=3.5 tas_ratio=on tas_ratio_src=a.nc", [1.0, 1.0, 1.0])
            with self.assertRaises(run_flight.UnverifiableProvenance):
                run_flight._s3_tas_ratio(image)



class TestS3OutputThroughTheDriversReader(_Globals):
    """The engine called with what ``_s3_tas_ratio`` reads from a real decoded file.

    One 6 x 6 square is 36 shadowed pixels. ``imgProc_sm.m:1347`` writes
    ``images.image_area*diode_size*diode_size/handles.tasRatio``, so under a ratio of 0.7 the
    file holds ``36 * ds**2 / 0.7`` (hand-derived, not taken from the engine), and with the
    flag off the driver passes no ratio and every variable equals a stock call's bit for bit.
    """

    def _image(self, d, stamp, ratio):
        from tests import test_v35_imgproc as v
        image = Path(d) / "base160101060600.H.nc"
        parts = [v._square(0, 60, 6)]
        v._write_input(image, [v._record(parts, [1000, 2000])], [v._header()])
        if ratio is not None:
            import netCDF4
            with netCDF4.Dataset(str(image), "a") as ds:
                ds.variables["tasRatio"][0:1] = [ratio]
        run_flight.write_stamp(image, stamp)
        return v, image

    def _s3(self, v, image, out, **kw):
        kw.setdefault("iNewHabit", 0)
        kw.setdefault("reject_config", v.STOCK_V35_REJECT_CONFIG)
        v.v35_imgproc.imgproc_sm_v35(str(image), str(out), "2DS", 1, 1000, "ORACLES",
                                     tas_time=v.TAS_TIME, tas=v.TAS, software="UIOOPS_v3.5",
                                     creation_time="2026/09/11 00:00:00", **kw)
        return v._read(out)

    def test_on_divides_image_area_by_the_ratio_imgProc_sm_1347(self):  # noqa: N802
        run_flight.TAS_RATIO = True
        with tempfile.TemporaryDirectory() as d:
            v, image = self._image(d, "engine=3.5 tas_ratio=on tas_ratio_src=a.nc", 0.7)
            ratio = run_flight._s3_tas_ratio(image)
            self.assertEqual(list(ratio), [0.7])
            got = self._s3(v, image, Path(d) / "on.proc.nc", tas_ratio=ratio)
        area = got["vars"]["image_area"]
        self.assertEqual(area.shape, (1,))
        self.assertAlmostEqual(float(area[0]), 36 * v.DS * v.DS / 0.7, places=12)

    def test_off_is_bit_identical_to_a_stock_call(self):
        run_flight.TAS_RATIO = False
        with tempfile.TemporaryDirectory() as d:
            v, image = self._image(d, "engine=3.5 tas_ratio=off", None)
            ratio = run_flight._s3_tas_ratio(image)
            self.assertIsNone(ratio)
            a = self._s3(v, image, Path(d) / "off.proc.nc", tas_ratio=ratio)
            b = self._s3(v, image, Path(d) / "stock.proc.nc")
        self.assertEqual(a["order"], b["order"])
        for name in a["order"]:
            with self.subTest(variable=name):
                kind = a["vars"][name].dtype.kind
                self.assertTrue(np.array_equal(a["vars"][name], b["vars"][name],
                                               equal_nan=kind == "f"))


class TestEveryDecodePathReceivesTheSeries(_Globals):
    """--tas-ratio on reaches the v3.5 decoder on every S2 path, not only the serial one.

    The parallel decode (``--s2-jobs`` > 1) and its serial fallback once passed no flight
    series, so they wrote no ``tasRatio`` under a ``.call`` stamp saying ``tas_ratio=on``.
    Each path is driven through :func:`run_flight.stage2` with the reader mocked, and must hand
    the reader exactly what the serial path hands it. The parallel reader's byte identity with
    the serial one under a flight series is ``tests/test_v35_spec_parallel.py``'s.
    """

    SERIES = ([120000.0, 120001.0], [150.0, 151.0])

    def _stage2(self, s2_jobs, parallel_breaks=False):
        import concurrent.futures.process as cfp
        spec_mod = mock.Mock()
        spec_mod.SeamRerunWarning = type("SeamRerunWarning", (UserWarning,), {})
        spec_mod.read_binary_spec_v35.return_value = (1, 0)
        if parallel_breaks:
            spec_mod.read_binary_spec_v35_parallel.side_effect = cfp.BrokenProcessPool("x")
        else:
            spec_mod.read_binary_spec_v35_parallel.return_value = (1, 0)
        engine = mock.Mock()
        engine.module.return_value = spec_mod
        run_flight.TAS_RATIO = True
        run_flight.TAS_FILE = "aircraft_tas.nc"
        with (
            tempfile.TemporaryDirectory() as d,
            mock.patch.object(run_flight, "ENGINE", "3.5"),
            mock.patch.object(run_flight, "PROBE", "2DS"),
            mock.patch.object(run_flight, "ORIENTATION", "H"),
            mock.patch.object(run_flight, "_v35", return_value=engine),
            mock.patch.object(run_flight, "_tas_ratio_series", return_value=self.SERIES),
            mock.patch.object(run_flight, "_publish"),
            mock.patch.object(run_flight, "write_stamp"),
            redirect_stdout(io.StringIO()),
        ):
            raw = Path(d) / "base160101000000.2DS"
            raw.write_bytes(bytes(8))
            run_flight.stage2(raw, Path(d), s2_jobs=s2_jobs)
        return spec_mod

    def _assert_series(self, call):
        self.assertEqual(call.kwargs.get("flt_time"), self.SERIES[0])
        self.assertEqual(call.kwargs.get("flt_tas"), self.SERIES[1])

    def test_serial_decode_receives_the_series(self):
        spec_mod = self._stage2(1)
        self._assert_series(spec_mod.read_binary_spec_v35.call_args)

    def test_parallel_decode_receives_the_series(self):
        spec_mod = self._stage2(3)
        spec_mod.read_binary_spec_v35.assert_not_called()
        self._assert_series(spec_mod.read_binary_spec_v35_parallel.call_args)

    def test_serial_fallback_from_a_dead_pool_receives_the_series(self):
        spec_mod = self._stage2(3, parallel_breaks=True)
        self._assert_series(spec_mod.read_binary_spec_v35_parallel.call_args)
        self._assert_series(spec_mod.read_binary_spec_v35.call_args)

    def test_stage2_does_not_refuse_parallel_with_the_ratio(self):
        # addc39e's stage2 wall (RuntimeError for TAS_RATIO with s2_jobs > 1) is gone: every
        # path (serial, parallel, fallback from a dead pool) gets the same series.
        calls = [self._stage2(1).read_binary_spec_v35.call_args,
                 self._stage2(2).read_binary_spec_v35_parallel.call_args,
                 self._stage2(2, parallel_breaks=True).read_binary_spec_v35.call_args]
        for call in calls:
            self._assert_series(call)

    def test_off_passes_none_on_the_parallel_path(self):
        run_flight.TAS_RATIO = False
        with mock.patch.object(run_flight, "_tas_ratio_series",
                               wraps=run_flight._tas_ratio_series):
            self.assertEqual(run_flight._tas_ratio_series(), (None, None))


class TestParallelDecodeResolvesTheSourceChain(_Globals):
    """``--tas-ratio on --tas-source aircraft --s2-jobs >1`` (pre-push review, 2026-10-06).

    The parallel branch once called ``_tas_ratio_series()`` without ``raw``, which raises under
    ``--tas-source`` before decoding; the class above mocks ``_tas_ratio_series`` and could not
    see it. Here the real function runs and only the chain resolver is replaced by a synthetic
    aircraft series, so serial and parallel must hand the decoder the same series.
    """

    CHAIN = SimpleNamespace(tier="aircraft", time=np.array([120000.0, 120001.0]),
                            tas=np.array([150.0, 151.0]), lines=["TAS chain: synthetic"])

    def setUp(self):
        super().setUp()
        self._saved_src = (run_flight.TAS_SOURCE, run_flight.TAS_SEARCH)
        run_flight.TAS_RATIO = True
        run_flight.TAS_FILE = None
        run_flight.TAS_SOURCE = "aircraft"
        run_flight.TAS_SEARCH = []

    def tearDown(self):
        run_flight.TAS_SOURCE, run_flight.TAS_SEARCH = self._saved_src
        super().tearDown()

    def _stage2(self, s2_jobs):
        spec_mod = mock.Mock()
        spec_mod.SeamRerunWarning = type("SeamRerunWarning", (UserWarning,), {})
        spec_mod.read_binary_spec_v35.return_value = (1, 0)
        spec_mod.read_binary_spec_v35_parallel.return_value = (1, 0)
        engine = mock.Mock()
        engine.module.return_value = spec_mod
        with (
            tempfile.TemporaryDirectory() as d,
            mock.patch.object(run_flight, "ENGINE", "3.5"),
            mock.patch.object(run_flight, "PROBE", "2DS"),
            mock.patch.object(run_flight, "ORIENTATION", "H"),
            mock.patch.object(run_flight, "_v35", return_value=engine),
            mock.patch.object(run_flight._tas_sources, "resolve_chain",
                              return_value=self.CHAIN) as rc,
            mock.patch.object(run_flight, "_publish"),
            mock.patch.object(run_flight, "write_stamp"),
            redirect_stdout(io.StringIO()),
        ):
            raw = Path(d) / "base160101000000.2DS"
            raw.write_bytes(bytes(8))
            run_flight.stage2(raw, Path(d), s2_jobs=s2_jobs)
        self.assertEqual(rc.call_args.kwargs["yyyymmdd"], "20160101")
        return spec_mod

    def test_parallel_and_serial_receive_the_same_chain_series(self):
        serial = self._stage2(1).read_binary_spec_v35.call_args
        parallel = self._stage2(3).read_binary_spec_v35_parallel.call_args
        for call in (serial, parallel):
            self.assertEqual(call.kwargs.get("flt_time"), [120000.0, 120001.0])
            self.assertEqual(call.kwargs.get("flt_tas"), [150.0, 151.0])


if __name__ == "__main__":
    unittest.main()

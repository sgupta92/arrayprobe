# SPDX-License-Identifier: BSD-3-Clause
"""``arrayprobe.provenance``: five formats, one parser, and ``None`` when a product does not say.

**What this is defending** (2026-09-18). A 1.25 GB CIP product was called a v3.5 product for
a full day when the v3.1.4 engine wrote it. :class:`TheShippedPredicateIsWrongOnFourOfFive`
reproduces the line that made that possible -- ``src/arrayprobe/cli.py:1027``'s
``"3.5" if stamp.startswith("engine=3.5 ") else "3.1.4"`` -- and shows it returning a confident
``"3.1.4"`` for an absent stamp, a truncated stamp, a lane JSON and a pre-2026-09-15 driver stamp.
That class is not testing the new module; it is the *measurement* of the defect, kept beside the
fix so a future reader can see what was actually wrong rather than take it on trust. It will keep
passing after WP2 removes the line, because it holds the predicate's own text.

The fixture set is built by ``tests/data/make_provenance_fixtures.py``, which also declares the
expected state, engine and format for each product beside the bytes it writes. The expectations
therefore come from a different place than the code under test.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

from arrayprobe import provenance

sys.path.insert(0, str(Path(__file__).resolve().parent / "data"))
import make_provenance_fixtures as fx  # noqa: E402


class _FixtureDir(unittest.TestCase):
    """Materialises the fixture set once per class into a temporary directory."""
    _tmp: Any  # assigned in setUpClass/setUp; see there for the value
    dir: Any  # assigned in setUpClass/setUp; see there for the value
    stamped_only: Any  # assigned in setUpClass/setUp; see there for the value

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        root = Path(cls._tmp.name)
        cls.dir = fx.build(root)
        cls.stamped_only = fx.build_stamped_only(root)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()


class EveryFormatParsesToTheRecordedEngine(_FixtureDir):
    def test_each_fixture_reports_its_declared_engine(self):
        for name, expected in fx.EXPECTED_ENGINE.items():
            with self.subTest(name):
                stamp = provenance.read(self.dir / name)
                self.assertIsNotNone(stamp, f"{name} should have a sidecar")
                self.assertEqual(stamp.engine, expected)

    def test_each_fixture_reports_its_declared_format(self):
        for name, expected in fx.EXPECTED_FORMAT.items():
            with self.subTest(name):
                stamp = provenance.read(self.dir / name)
                self.assertEqual(stamp.format, expected)

    def test_all_five_formats_are_exercised(self):
        """A sweep that silently covered only one format would pass everything above."""
        seen = set(fx.EXPECTED_FORMAT.values())
        self.assertEqual(seen, set(provenance.FORMATS), f"formats not covered: "
                         f"{set(provenance.FORMATS) - seen}")

    def test_the_driver_stamp_keeps_its_other_fields(self):
        stamp = provenance.read(self.dir / "proc.driver_v314.nc")
        self.assertEqual(stamp.profile, "oracles-production")
        self.assertEqual(stamp.fields["shadow_diode"], "none")
        self.assertEqual(
            stamp.fields["reject"],
            "(rej_zero_area=True,rej_split=True,rej_hollow=False,shadowed_area=25,"
            "max_edge_img_ar=4,max_comp_img_ar=4)",
            "the parenthesised reject fragment must survive as ONE value -- its inner '=' signs "
            "are preceded by '(' or ',', never a space")

    def test_the_v35_combine_second_line_is_kept(self):
        stamp = provenance.read(self.dir / "sd.v35_combined.nc")
        self.assertEqual(stamp.fields["inputs"], "sd.base160101000000.H.nc")

    def test_the_legacy_json_keeps_stage_and_profile_but_has_no_engine(self):
        stamp = provenance.read(self.dir / "proc.legacy_lane.nc")
        self.assertEqual(stamp.stage, "S3 imgproc_sm, 8 chunks + merge_chunks")
        self.assertEqual(stamp.profile, "oracles-production")
        self.assertIsNone(stamp.engine)


class AbsenceIsNeverAnEngine(_FixtureDir):
    """The one rule the module exists for."""

    def test_a_driver_stamp_with_no_engine_key_gives_None(self):
        stamp = provenance.read(self.dir / "proc.driver_noengine.nc")
        self.assertEqual(stamp.format, "driver")
        self.assertIsNone(
            stamp.engine,
            "a v3.1.4 stamp written before 2026-09-15 has no engine= key. Reading it as '3.1.4' "
            "is the guess that made a v3.1.4 CIP product look like a v3.5 one for a day.")

    def test_read_returns_None_for_a_product_with_no_sidecar(self):
        self.assertIsNone(provenance.read(self.dir / "proc.unstamped.nc"))

    def test_require_raises_on_the_unstamped_product(self):
        """The firing test: nothing here is allowed to answer for a file that does not say."""
        with self.assertRaises(provenance.Unstamped) as caught:
            provenance.require(self.dir / "proc.unstamped.nc")
        self.assertIn("proc.unstamped.nc", str(caught.exception))

    def test_engine_of_raises_Unstamped_rather_than_defaulting(self):
        with self.assertRaises(provenance.Unstamped):
            provenance.engine_of(self.dir / "proc.unstamped.nc")

    def test_engine_of_raises_EngineUnrecorded_on_a_stamp_that_does_not_say(self):
        for name in ("proc.driver_noengine.nc", "proc.legacy_lane.nc", "proc.truncated.nc"):
            with self.subTest(name), self.assertRaises(provenance.EngineUnrecorded):
                provenance.engine_of(self.dir / name)

    def test_the_two_refusals_are_different_exceptions(self):
        """Folding them together would lose the distinction between 'predates stamping' and
        'stamped, in a format that never had the field'."""
        self.assertFalse(issubclass(provenance.Unstamped, provenance.EngineUnrecorded))
        self.assertFalse(issubclass(provenance.EngineUnrecorded, provenance.Unstamped))

    def test_engine_of_returns_the_recorded_name_when_there_is_one(self):
        self.assertEqual(provenance.engine_of(self.dir / "proc.driver_v314.nc"), "3.1.4")
        self.assertEqual(provenance.engine_of(self.dir / "sd.v35_combined.nc"), "3.5")
        self.assertEqual(provenance.engine_of(self.dir / "run.pbp"), "soda2")

    def test_an_unreadable_sidecar_is_absence_not_an_engine(self):
        with tempfile.TemporaryDirectory() as tmp:
            product = Path(tmp) / "proc.x.nc"
            product.write_bytes(b"")
            (Path(tmp) / "proc.x.nc.call").mkdir()  # a directory where a file should be
            self.assertIsNone(provenance.read_text(product))
            with self.assertRaises(provenance.Unstamped):
                provenance.engine_of(product)


class TheShippedPredicateIsWrongOnFourOfFive(_FixtureDir):
    """``src/arrayprobe/cli.py:1027`` as it stands today, measured against the same fixtures."""

    @staticmethod
    def _cli_1027(stamp_text: str) -> str:
        return "3.5" if stamp_text.startswith("engine=3.5 ") else "3.1.4"

    def test_it_answers_3_1_4_confidently_for_four_stamps_that_do_not_say(self):
        wrong = []
        for name in ("proc.unstamped.nc", "proc.driver_noengine.nc",
                     "proc.legacy_lane.nc", "proc.truncated.nc"):
            text = provenance.read_text(self.dir / name) or ""
            if self._cli_1027(text) == "3.1.4":
                wrong.append(name)
        self.assertEqual(
            sorted(wrong),
            ["proc.driver_noengine.nc", "proc.legacy_lane.nc",
             "proc.truncated.nc", "proc.unstamped.nc"],
            "this class records the measured defect it was opened for; if the list shrank, "
            "the predicate has changed and this class should be retired with a note")

    def test_the_new_parser_declines_all_four(self):
        for name in ("proc.unstamped.nc", "proc.driver_noengine.nc",
                     "proc.legacy_lane.nc", "proc.truncated.nc"):
            with self.subTest(name):
                stamp = provenance.read(self.dir / name)
                self.assertIsNone(stamp.engine if stamp else None)


class StateNamesWhatIsThere(_FixtureDir):
    def test_each_fixture_is_in_its_declared_state(self):
        for name, expected in fx.EXPECTED_STATE.items():
            with self.subTest(name):
                self.assertEqual(provenance.state(self.dir / name), expected)

    def test_every_state_is_exercised_by_the_fixture_set(self):
        seen = set(fx.EXPECTED_STATE.values())
        self.assertEqual(seen, set(provenance.STATES),
                         f"states not covered: {set(provenance.STATES) - seen}")

    def test_an_orphan_stamp_is_not_reported_as_unstamped(self):
        """The two are opposites: one is a product with no record, the other a record with no
        product. Five orphan sidecars sit in _decoded/cip160906/ today."""
        self.assertFalse((self.dir / "proc.deleted.nc").exists())
        self.assertTrue((self.dir / "proc.deleted.nc.call").exists())
        self.assertEqual(provenance.state(self.dir / "proc.deleted.nc"), "orphan-stamp")

    def test_in_flight_is_also_detected_from_an_inflight_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            product = Path(tmp) / "proc.base160906064017.H.nc"
            product.write_bytes(b"")
            (Path(tmp) / "_inflight").mkdir()
            (Path(tmp) / "_inflight" / "proc.base160906064017.H.nc.tmp").write_bytes(b"")
            self.assertEqual(provenance.state(product), "in-flight")


class WriteMirrorsTheDriverFormat(unittest.TestCase):
    def test_a_written_stamp_reads_back_with_the_same_engine_and_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            product = Path(tmp) / "proc.x.nc"
            product.write_bytes(b"")
            provenance.write(product, engine="3.5", profile="stock-v3.5", stage="S3")
            stamp = provenance.require(product)
            self.assertEqual((stamp.format, stamp.engine, stamp.profile, stamp.stage),
                             ("driver", "3.5", "stock-v3.5", "S3"))

    def test_the_text_begins_with_the_engine_key_like_run_flights_own_label(self):
        with tempfile.TemporaryDirectory() as tmp:
            product = Path(tmp) / "proc.x.nc"
            sidecar = provenance.write(product, engine="3.1.4", profile="oracles-production")
            self.assertTrue(sidecar.read_text(encoding="utf-8").startswith(
                "engine=3.1.4 profile=oracles-production"))

    def test_no_partial_file_survives_a_successful_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            product = Path(tmp) / "proc.x.nc"
            provenance.write(product, engine="3.1.4", profile=None)
            self.assertEqual(list(Path(tmp).glob("*.partial")), [])

    def test_an_unknown_engine_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                provenance.write(Path(tmp) / "proc.x.nc", engine="3.4.1", profile=None)

    def test_a_value_that_would_re_parse_as_a_second_key_is_refused(self):
        """``extra={"note": "rebuilt engine=3.5"}`` would silently change what the stamp says."""
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                provenance.write(Path(tmp) / "proc.x.nc", engine="3.1.4",
                                 extra={"note": "rebuilt engine=3.5"}, profile=None)

    def test_a_newline_in_a_value_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                provenance.write(Path(tmp) / "proc.x.nc", engine="3.1.4",
                                 extra={"note": "two\nlines"}, profile=None)


class ReportAnswersForADirectory(_FixtureDir):
    def test_require_is_non_zero_on_the_mixed_directory(self):
        text, code = provenance.report([self.dir], require=True)
        self.assertEqual(code, 1)
        self.assertIn("REQUIRE:", text)

    def test_require_is_zero_on_a_directory_where_everything_is_stamped(self):
        text, code = provenance.report([self.stamped_only], require=True)
        self.assertEqual(code, 0, text)
        self.assertNotIn("REQUIRE:", text)

    def test_without_require_the_exit_code_is_zero_even_when_products_are_unstamped(self):
        _, code = provenance.report([self.dir])
        self.assertEqual(code, 0)

    def test_require_fails_a_stamped_product_that_names_no_engine(self):
        """The subtle case: the sidecar is there and records the whole configuration, so the
        state is legitimately `stamped` -- and it still does not say what wrote the file. A
        --require that passed this would green-light exactly the products this test is about."""
        with tempfile.TemporaryDirectory() as tmp:
            product = Path(tmp) / "proc.old.nc"
            product.write_bytes(b"")
            (Path(tmp) / "proc.old.nc.call").write_text(fx.DRIVER_NO_ENGINE, encoding="utf-8")
            self.assertEqual(provenance.state(product), "stamped")
            text, code = provenance.report([Path(tmp)], require=True)
            self.assertEqual(code, 1, text)
            self.assertIn("naming no engine", text)

    def test_the_orphan_stamps_product_is_listed_even_though_the_file_is_gone(self):
        text, _ = provenance.report([self.dir])
        self.assertIn("proc.deleted.nc", text)
        self.assertIn("orphan-stamp", text)

    def test_an_unrecorded_engine_is_printed_as_unrecorded_not_as_a_version(self):
        text, _ = provenance.report([self.dir / "proc.legacy_lane.nc"])
        self.assertIn("unrecorded", text)
        self.assertNotIn("3.1.4", text.split("checkout:")[0].split("\n")[2])

    def test_an_empty_directory_says_so_rather_than_printing_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            text, _ = provenance.report([Path(tmp)])
            self.assertIn("no products found", text)

    def test_the_checkout_sha_is_labelled_as_not_the_products(self):
        text, _ = provenance.report([self.stamped_only])
        self.assertIn("this checkout, not the product's", text)

    def test_the_report_says_a_stamp_does_not_survive_a_rename(self):
        text, _ = provenance.report([self.stamped_only])
        self.assertIn("copy, hardlink or rename loses it", text)


def _nc_with_attrs(path: Path, attrs: dict) -> Path:
    import netCDF4

    with netCDF4.Dataset(str(path), "w", format="NETCDF3_CLASSIC") as ds:
        ds.createDimension("time", 1)
        for key, value in attrs.items():
            ds.setncattr(key, value)
    return path


class TheReportReadsTheInFileStamp(unittest.TestCase):
    """Question-ranking P1 (2026-09-29): the table reads the product's own ``arrayprobe_*``
    attributes beside its sidecar, as ``ncio.provenance_of`` does, so a renamed v3.5 product is
    accounted for and a sidecar that contradicts its file is caught."""

    def test_a_renamed_product_is_accounted_for_by_its_own_attributes(self):
        with tempfile.TemporaryDirectory() as tmp:
            _nc_with_attrs(Path(tmp) / "renamed.nc",
                           provenance.engine_attrs(engine="3.5", profile="stock-v3.5"))
            text, code = provenance.report([Path(tmp)], require=True)
        self.assertEqual(code, 0, text)
        self.assertIn("engine=3.5 profile=stock-v3.5", text)

    def test_a_sidecar_that_contradicts_the_file_is_reported_and_fails_require(self):
        with tempfile.TemporaryDirectory() as tmp:
            product = _nc_with_attrs(Path(tmp) / "proc.x.nc",
                                     provenance.engine_attrs(engine="3.5", profile="stock-v3.5"))
            provenance.write(product, engine="3.1.4", profile=None)
            text, code = provenance.report([Path(tmp)], require=True)
        self.assertEqual(code, 1, text)
        self.assertIn("DISAGREES", text)
        self.assertIn("1 whose sidecar and in-file stamp disagree", text)


class TheParserRefusesRatherThanGuesses(unittest.TestCase):
    def test_a_duplicated_key_is_unparseable_rather_than_last_wins(self):
        stamp = provenance.parse("engine=3.1.4 profile=a engine=3.5")
        self.assertEqual(stamp.format, "unparseable")
        self.assertIsNone(stamp.engine)

    def test_an_engine_name_this_module_does_not_know_is_None(self):
        stamp = provenance.parse("engine=3.4.1 profile=a")
        self.assertEqual(stamp.format, "driver")
        self.assertIsNone(stamp.engine,
                          "dispatching on an unrecognised engine string is the same failure as "
                          "dispatching on a guess")

    def test_an_empty_stamp_is_unparseable(self):
        self.assertEqual(provenance.parse("").format, "unparseable")

    def test_a_json_list_is_unparseable_rather_than_an_empty_legacy_stamp(self):
        self.assertEqual(provenance.parse('{"a": 1').format, "unparseable")

    def test_a_soda2_stamp_is_told_from_a_lane_json_by_its_engine_key(self):
        self.assertEqual(provenance.parse(fx.SODA2_PBP).format, "soda2-pbp")
        self.assertEqual(provenance.parse(fx.LEGACY_JSON).format, "legacy-json")

    def test_a_stamp_is_classified_by_content_not_by_filename(self):
        """A .pbp.call renamed does not stop being SODA-2 JSON."""
        with tempfile.TemporaryDirectory() as tmp:
            product = Path(tmp) / "proc.renamed.nc"
            product.write_bytes(b"")
            (Path(tmp) / "proc.renamed.nc.call").write_text(fx.SODA2_PBP, encoding="utf-8")
            self.assertEqual(provenance.engine_of(product), "soda2")


class TheModuleHasNoEngineDefaultAnywhere(unittest.TestCase):
    """A textual sweep of the module's own source, because the rule is about what it must never
    contain: a code path that produces an engine name the stamp did not."""

    def test_the_source_never_assigns_a_bare_engine_literal_as_a_fallback(self):
        src = Path(provenance.__file__).read_text(encoding="utf-8")
        code = "\n".join(line for line in src.splitlines()
                         if not line.lstrip().startswith("#"))
        body = code.split('"""', 2)[-1] if code.count('"""') >= 2 else code
        for bad in ('else "3.1.4"', "else '3.1.4'", 'or "3.1.4"', 'engine = "3.1.4"'):
            self.assertNotIn(bad, body, f"{bad!r} in provenance.py would be the defect this "
                                        "module exists to remove, reintroduced inside it")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

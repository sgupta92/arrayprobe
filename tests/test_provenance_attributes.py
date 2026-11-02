# SPDX-License-Identifier: BSD-3-Clause
"""Provenance carried by the bytes: the attribute, the sidecar, and their disagreement.

WHY THIS FILE EXISTS. A ``.call`` sidecar is keyed by filename, so a rename, a copy or a
hardlink separates a product from everything recorded about it, and the product then carries no
provenance at all. A global attribute travels with the bytes.

Three things are proved here, each on a real netCDF file rather than a mock:

1. the attribute survives the operation that loses the sidecar (``test_a_hardlink_keeps_...``);
2. **the default is off** -- nothing writes these attributes unless a caller asks, and a real
   MATLAB-written product carries none, so excluding them from a layer-1 comparison excludes
   something that genuinely is not there;
3. **the disagreement guard fires.** Six guards in this repository have been found reading fine
   while matching nothing, so the negative case is asserted with ``assertRaises`` on a file that
   really has an attribute saying one thing and a sidecar saying another.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path

import numpy as np

from arrayprobe import ncio, provenance

DATA = Path(__file__).resolve().parent / "data"

#: A real MATLAB-written product header (a 160 KiB cut of the ORACLES 2D-S file of record).
MATLAB_WRITTEN = DATA / "2DS_header_fixture.nc"


def _product(path: Path, *, stamp: dict[str, str] | None = None) -> Path:
    """A product-shaped NETCDF3_CLASSIC file, optionally carrying provenance attributes."""
    f = ncio.create(path)
    f.def_dim("time", 3)
    vid = f.def_var("Counts", "short", [0])
    f.put_att(ncio.NC_GLOBAL, "Creation Time", "01-Jan-2026 00:00:01")
    f.put_att(ncio.NC_GLOBAL, "SA Method", "randombins")
    if stamp is not None:
        # `profile` is required rather than defaulted (the no-silent-default rule), so
        # a caller meaning "this stamp names no profile" must say so. Splatting a dict
        # that omits the key would reintroduce exactly the silence the rule forbids.
        stamp.setdefault("profile", None)  # type: ignore[arg-type]
        ncio.put_provenance(f, **stamp)  # type: ignore[arg-type]
    f.end_def()
    f.put_var(vid, np.array([1, 2, 3], dtype="i2"))
    f.close()
    return path


class TheAttributeSurvivesWhatTheSidecarDoesNot(unittest.TestCase):
    """The failure of 2026-09-18, reproduced -- and no longer possible."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.product = _product(
            self.tmp / "proc.flight.H.nc",
            stamp={"engine": "3.1.4", "profile": "oracles-production", "stage": "proc"},
        )
        provenance.write(
            self.product, engine="3.1.4", profile="oracles-production", stage="proc")

    def test_the_attribute_round_trips_through_the_one_parser(self):
        stamp = ncio.read_provenance(self.product)
        self.assertIsNotNone(stamp)
        assert stamp is not None
        self.assertEqual(stamp.engine, "3.1.4")
        self.assertEqual(stamp.profile, "oracles-production")
        self.assertEqual(stamp.stage, "proc")
        self.assertEqual(stamp.format, "driver")

    def test_the_two_carriers_hold_the_same_text_by_construction(self):
        """One builder, stored twice -- not two writers that must be kept in step."""
        beside = provenance.read_text(self.product)
        assert beside is not None
        with ncio.open(self.product).dataset as ds:
            inside = ds.getncattr(provenance.ATTR_CALL)
        self.assertEqual(inside, beside.strip())

    def test_a_copy_under_a_new_name_keeps_the_provenance(self):
        renamed = self.tmp / "cip160906.v35.nc"
        shutil.copy2(self.product, renamed)
        self.assertIsNone(provenance.read(renamed), "the sidecar must NOT follow the copy")
        stamp = ncio.read_provenance(renamed)
        assert stamp is not None
        self.assertEqual(stamp.engine, "3.1.4")

    def test_a_hardlink_keeps_the_provenance_the_sidecar_loses(self):
        """The exact 2026-09-18 operation: one inode, a second name, no sidecar."""
        linked = self.tmp / "indexed_under_another_name.nc"
        try:
            os.link(self.product, linked)
        except (OSError, NotImplementedError) as exc:  # pragma: no cover - filesystem dependent
            self.skipTest(f"hardlinks unavailable here: {exc}")
        self.assertGreater(os.stat(linked).st_nlink, 1, "this is not a hardlink")
        self.assertIsNone(provenance.read(linked),
                          "the hardlinked name has no sidecar -- that is the failure")
        self.assertEqual(ncio.provenance_of(linked).engine, "3.1.4",
                         "the attribute must answer where the sidecar cannot")

    def test_an_unstamped_product_still_raises_rather_than_guessing(self):
        bare = _product(self.tmp / "bare.nc")
        self.assertIsNone(ncio.read_provenance(bare))
        with self.assertRaises(provenance.Unstamped):
            ncio.provenance_of(bare)
        with self.assertRaises(provenance.Unstamped):
            ncio.engine_of(bare)

    def test_engine_of_answers_from_the_bytes_when_the_sidecar_is_gone(self):
        """The consumer-facing form: ``cli.py:1027``'s ternary, replaced by a refusal."""
        renamed = self.tmp / "indexed_elsewhere.nc"
        shutil.copy2(self.product, renamed)
        self.assertEqual(ncio.engine_of(renamed), "3.1.4")

    def test_engine_of_refuses_a_carrier_that_does_not_name_an_engine(self):
        """A legacy-json sidecar and no attribute: silence, not v3.1.4."""
        legacy = _product(self.tmp / "legacy.nc")
        provenance.call_path(legacy).write_text(
            '{"stage": "proc", "profile": "oracles-production"}', encoding="utf-8")
        with self.assertRaises(provenance.EngineUnrecorded):
            ncio.engine_of(legacy)


class TheDefaultIsOff(unittest.TestCase):
    """Nothing gains an attribute it did not ask for -- the layer-1 claim depends on it."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_a_writer_that_does_not_opt_in_writes_no_provenance_attribute(self):
        bare = _product(self.tmp / "bare.nc")
        with ncio.open(bare).dataset as ds:
            names = list(ds.ncattrs())
        self.assertEqual([n for n in names if provenance.is_provenance_attr(n)], [])
        self.assertEqual(names, ["Creation Time", "SA Method"],
                         "the attribute set must be exactly what it was before the "
                         "provenance attributes")

    def test_a_real_matlab_written_product_carries_none(self):
        """Confirming the oracle: the layer-1 exclusion excludes something really absent.

        Measured 2026-09-18 on the tracked header cut of the ORACLES 2D-S file of record: it
        carries **no global attributes at all**. ``read_binary_SPEC.m`` writes none, which
        ``test_imgproc_oracle.py:313`` asserts from the other direction. So a layer-1 comparison
        that excludes the ``arrayprobe_`` prefix is excluding something the archive genuinely does
        not have -- it cannot be hiding one of *their* attributes, because on this file there are
        none to hide, and on a ``proc`` file every one of them is Title Case.
        """
        self.assertTrue(MATLAB_WRITTEN.exists(), MATLAB_WRITTEN)
        with ncio.open(MATLAB_WRITTEN).dataset as ds:
            names = list(ds.ncattrs())
            per_variable = {v: list(ds.variables[v].ncattrs()) for v in ds.variables}
        self.assertEqual(names, [], "MATLAB's decode writes no global attributes")
        self.assertGreater(len(per_variable), 0, "the fixture must really have variables")
        for var, attrs in per_variable.items():
            self.assertEqual([a for a in attrs if provenance.is_provenance_attr(a)], [], var)
        self.assertIsNone(ncio.read_provenance(MATLAB_WRITTEN))

    def test_the_prefix_cannot_collide_with_the_output_contract(self):
        """Every attribute UIOOPS writes is Title Case; ours is lowercase with underscores.

        The names are read from the port's own writers rather than invented here, so this stays
        true as the output contract grows.
        """
        theirs = ["Creation Time", "SA Method", "Data Source", "Dmax Definition",
                  "Units", "units", "Description"]
        for name in theirs:
            self.assertFalse(provenance.is_provenance_attr(name), name)


class TheDisagreementGuardFires(unittest.TestCase):
    """A guard that has never been seen to raise is a guard that may match nothing."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def _conflicting(self) -> Path:
        """A real file whose attribute says v3.5 and whose sidecar says v3.1.4."""
        product = _product(self.tmp / "proc.flight.H.nc",
                           stamp={"engine": "3.5", "profile": "stock-v35"})
        provenance.write(product, engine="3.1.4", profile="oracles-production")
        return product

    def test_a_conflicting_engine_raises(self):
        product = self._conflicting()
        with self.assertRaises(provenance.ProvenanceDisagreement) as caught:
            ncio.provenance_of(product)
        message = str(caught.exception)
        self.assertIn("'3.1.4'", message)
        self.assertIn("'3.5'", message)
        self.assertIn("engine", message)

    def test_the_raised_error_names_every_differing_field(self):
        product = self._conflicting()
        with self.assertRaises(provenance.ProvenanceDisagreement) as caught:
            ncio.provenance_of(product)
        keys = [line.split(":")[0] for line in caught.exception.differences]
        self.assertEqual(sorted(keys), ["engine", "profile"])

    def test_neither_carrier_wins(self):
        """The constraint in the instruction: a finding to surface, not a tie to break."""
        product = self._conflicting()
        with self.assertRaises(provenance.ProvenanceDisagreement):
            ncio.provenance_of(product)
        # and the two readers still each report their own side, unmodified
        inside = ncio.read_provenance(product)
        beside = provenance.read(product)
        assert inside is not None and beside is not None
        self.assertEqual(inside.engine, "3.5")
        self.assertEqual(beside.engine, "3.1.4")

    def test_agreement_does_not_raise(self):
        """Confirming the oracle from the other side: the guard must not fire on every file."""
        product = _product(self.tmp / "agree.nc",
                           stamp={"engine": "3.5", "profile": "stock-v35"})
        provenance.write(product, engine="3.5", profile="stock-v35")
        self.assertEqual(ncio.provenance_of(product).engine, "3.5")

    def test_silence_on_one_side_is_not_disagreement(self):
        """A legacy-json sidecar names no engine; the attribute supplying one is the point."""
        product = _product(self.tmp / "legacy.nc", stamp={"engine": "3.1.4"})
        provenance.call_path(product).write_text(
            '{"stage": "proc", "profile": "oracles-production"}', encoding="utf-8")
        beside = provenance.read(product)
        assert beside is not None
        self.assertIsNone(beside.engine, "the sidecar must really be silent on the engine")
        self.assertEqual(ncio.provenance_of(product).engine, "3.1.4")

    def test_an_extra_sidecar_key_is_not_disagreement(self):
        """The driver's ``reject=(...)`` fragment has no attribute; that is not a conflict."""
        product = _product(self.tmp / "extra.nc", stamp={"engine": "3.1.4"})
        provenance.write(product, engine="3.1.4",
                         extra={"reject": "(rej_hollow=0,max_edge_img_ar=4)"}, profile=None)
        self.assertEqual(ncio.provenance_of(product).engine, "3.1.4")

    def test_a_file_whose_own_keys_contradict_its_call_text_raises(self):
        """A hand-edited attribute -- ``attrs_for`` cannot produce this."""
        product = _product(self.tmp / "edited.nc", stamp={"engine": "3.1.4"})
        with ncio.open(product, "write").dataset as ds:
            ds.setncattr(provenance.ATTR_ENGINE, "3.5")
        with self.assertRaises(provenance.ProvenanceDisagreement):
            ncio.read_provenance(product)


class TheTwoComparisonsAreKeptApart(unittest.TestCase):
    """Provenance attributes are deterministic, so they are NOT volatile -- see the docstring
    on :data:`arrayprobe.provenance.PROVENANCE_ATTRS`."""

    def test_the_attribute_set_is_pinned(self):
        self.assertEqual(
            provenance.PROVENANCE_ATTRS,
            frozenset({"arrayprobe_engine", "arrayprobe_profile",
                       "arrayprobe_stage", "arrayprobe_call"}))

    def test_membership_is_recognised_by_prefix_not_by_enumeration(self):
        """So a fifth key added later is still excluded by every layer-1 comparison."""
        self.assertTrue(provenance.is_provenance_attr("arrayprobe_something_added_in_2027"))
        self.assertFalse(provenance.is_provenance_attr("Creation Time"))
        self.assertFalse(provenance.is_provenance_attr("Data Source"))
        for name in provenance.PROVENANCE_ATTRS:
            self.assertTrue(provenance.is_provenance_attr(name), name)

    def test_the_call_attribute_is_what_the_sidecar_would_hold(self):
        attrs = provenance.attrs_for(engine="3.1.4", profile="oracles-production")
        self.assertEqual(attrs[provenance.ATTR_CALL],
                         provenance.stamp_text(engine="3.1.4", profile="oracles-production"))

    def test_an_engine_outside_the_known_set_is_refused_on_write(self):
        with self.assertRaises(ValueError):
            provenance.attrs_for(engine="3.9", profile=None)

    def test_an_unknown_engine_read_back_is_none_rather_than_a_guess(self):
        stamp = provenance.stamp_from_attrs({"arrayprobe_engine": "3.9"})
        assert stamp is not None
        self.assertIsNone(stamp.engine)


if __name__ == "__main__":
    unittest.main()

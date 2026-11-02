# SPDX-License-Identifier: BSD-3-Clause
"""Build the ``.call`` fixture directory :mod:`tests.test_provenance` reads -- one product in each
of the states and formats :mod:`arrayprobe.provenance` distinguishes.

**Why a generator rather than tracked files** (2026-09-18). ``tests/data/`` already carries
generated fixtures behind tracked builders (``make_2ds_header_fixture.py`` and four siblings), and
this set *must* be generated rather than committed for a specific reason:
``tests/test_call_stamp_names_engine.py`` sweeps every tracked ``tests/data/**/*.call`` and requires
each one to carry an ``engine=`` key. That is a real guard on the stamps this project writes, and
half of the fixtures here are deliberate *negative* examples -- a driver stamp with no ``engine=``
key (every v3.1.4 stamp written before 2026-09-15 looks like this), and the lane scripts'
hand-rolled JSON, which has no engine key in any of its four shapes. Committing them would force an
exclusion into that sweep and weaken it. Generating them keeps both checks at full strength.

The fixture text is still reviewable in git, because it is the string constants below. Every path
in them is scrubbed: ``tests/test_no_personal_paths.py`` sweeps this file too.

Usage::

    from make_provenance_fixtures import build
    fixture_dir = build(Path(tmpdir))
"""
from __future__ import annotations

from pathlib import Path

#: ``scripts/run_flight.py``'s one-line text, as ``write_stamp`` writes it today (the shape
#: pinned by
#: ``tests/test_run_from_config.py::ValidatedCallStampsAreByteIdentical``).
DRIVER_V314 = (
    "engine=3.1.4 profile=oracles-production "
    "reject=(rej_zero_area=True,rej_split=True,rej_hollow=False,shadowed_area=25,"
    "max_edge_img_ar=4,max_comp_img_ar=4) shadow_diode=none\n"
)

#: The same writer before 2026-09-15 (R4s): no ``engine=`` key at all. Reading this as
#: v3.1.4 is a guess -- a well-founded one for the *resume* question, and not an answer at all to
#: "what wrote this file", which is the distinction ``provenance`` exists to hold.
DRIVER_NO_ENGINE = (
    "profile=oracles-production "
    "reject=(rej_zero_area=True,rej_split=True,rej_hollow=False,shadowed_area=25,"
    "max_edge_img_ar=4,max_comp_img_ar=4) shadow_diode=none\n"
)

#: ``arrayprobe_uiops/combine.py``'s mirrored two-line stamp (``CALL_STAMP`` + ``inputs=``).
V35_COMBINE = (
    "engine=3.5 combine=borrowed-oracles-fork:combine_sizedist.m "
    "opt_in=borrowed_combine=True\n"
    "inputs=sd.base160101000000.H.nc\n"
)

#: ``cli.py``'s SODA-2 ``.pbp.call``, cut to the keys that matter here.
SODA2_PBP = (
    '{\n'
    ' "engine": "soda2",\n'
    ' "config_path": "/scrubbed/example/soda2_cip.cfg",\n'
    ' "outputs": {"pbp_csv": "/scrubbed/example/run.pbp.csv"}\n'
    '}\n'
)

#: ``_decoded/cip160906/proc.cip_s2.nc.call`` verbatim in shape, paths scrubbed. This is the stamp
#: on the 1.25 GB CIP product that was called v3.5 for a day. Note what it does *not* contain.
LEGACY_JSON = (
    '{\n'
    ' "stage": "S3 imgproc_sm, 8 chunks + merge_chunks",\n'
    ' "infile": "/scrubbed/example/sea_s2.CIP.cdf",\n'
    ' "probename": "CIP",\n'
    ' "projectname": "ORACLES",\n'
    ' "profile": "oracles-production",\n'
    ' "reject": "RejectConfig(rej_zero_area=True, rej_split=True, rej_hollow=False, '
    'shadowed_area=25, max_edge_img_ar=4, max_comp_img_ar=4)",\n'
    ' "chunks": 8,\n'
    ' "particles": 3796565\n'
    '}\n'
)

#: A stamp killed mid-write. ``write_stamp``'s partial-then-rename exists to make this unreachable
#: through the driver; a hand-rolled writer elsewhere has no such protection.
TRUNCATED = "engi"

#: product name -> its stamp text (or ``None`` for a product with no sidecar).
STAMPS: dict[str, str | None] = {
    "proc.driver_v314.nc": DRIVER_V314,
    "proc.driver_noengine.nc": DRIVER_NO_ENGINE,
    "sd.v35_combined.nc": V35_COMBINE,
    "run.pbp": SODA2_PBP,
    "proc.legacy_lane.nc": LEGACY_JSON,
    "proc.truncated.nc": TRUNCATED,
    "proc.unstamped.nc": None,
    "proc.running.nc": None,
    "proc.deleted.nc": DRIVER_V314,
}

#: Products deliberately absent from disk, so their sidecar is an orphan (five such sidecars sit in
#: ``_decoded/cip160906/`` today).
ABSENT: frozenset[str] = frozenset({"proc.deleted.nc"})

#: Products with a ``.partial`` beside them, i.e. a run that appears to be writing right now.
IN_FLIGHT: frozenset[str] = frozenset({"proc.running.nc"})

#: What :func:`arrayprobe.provenance.state` must return for each product. The expectation is
#: written *here*, beside the bytes, rather than recomputed in the test from the same logic the
#: test is checking -- the two sides of the check come from different places.
EXPECTED_STATE: dict[str, str] = {
    "proc.driver_v314.nc": "stamped",
    "proc.driver_noengine.nc": "stamped",
    "sd.v35_combined.nc": "stamped",
    "run.pbp": "stamped",
    "proc.legacy_lane.nc": "legacy-json",
    "proc.truncated.nc": "unparseable",
    "proc.unstamped.nc": "unstamped",
    "proc.running.nc": "in-flight",
    "proc.deleted.nc": "orphan-stamp",
}

#: What :attr:`arrayprobe.provenance.Stamp.engine` must be. ``None`` is the answer under test.
EXPECTED_ENGINE: dict[str, str | None] = {
    "proc.driver_v314.nc": "3.1.4",
    "proc.driver_noengine.nc": None,
    "sd.v35_combined.nc": "3.5",
    "run.pbp": "soda2",
    "proc.legacy_lane.nc": None,
    "proc.truncated.nc": None,
    "proc.deleted.nc": "3.1.4",
}

#: What :attr:`arrayprobe.provenance.Stamp.format` must be.
EXPECTED_FORMAT: dict[str, str] = {
    "proc.driver_v314.nc": "driver",
    "proc.driver_noengine.nc": "driver",
    "sd.v35_combined.nc": "v35-combine",
    "run.pbp": "soda2-pbp",
    "proc.legacy_lane.nc": "legacy-json",
    "proc.truncated.nc": "unparseable",
    "proc.deleted.nc": "driver",
}


def build(dest: Path) -> Path:
    """Materialise the fixture set under ``dest/provenance`` and return that directory.

    Products are zero-byte files: nothing here reads a product's contents, and a fixture that
    needed real data would tie this check to the netCDF stack it has no business depending on.
    """
    out = Path(dest) / "provenance"
    out.mkdir(parents=True, exist_ok=True)
    for name, stamp in STAMPS.items():
        product = out / name
        if name not in ABSENT:
            product.write_bytes(b"")
        if stamp is not None:
            (out / (name + ".call")).write_text(stamp, encoding="utf-8")
        if name in IN_FLIGHT:
            (out / (name + ".partial")).write_bytes(b"")
    return out


def build_stamped_only(dest: Path) -> Path:
    """A directory holding one product, fully stamped -- the ``report(require=True)`` zero case."""
    out = Path(dest) / "stamped_only"
    out.mkdir(parents=True, exist_ok=True)
    (out / "proc.driver_v314.nc").write_bytes(b"")
    (out / "proc.driver_v314.nc.call").write_text(DRIVER_V314, encoding="utf-8")
    return out


if __name__ == "__main__":  # pragma: no cover
    import sys
    print(build(Path(sys.argv[1] if len(sys.argv) > 1 else ".")))

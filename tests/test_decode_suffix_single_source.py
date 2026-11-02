# SPDX-License-Identifier: BSD-3-Clause
"""A decode's extension is named in one place, ``arrayprobe_uiops.decode_naming``.

WHY. Five instance fixes between 2026-09-14 and 2026-09-30 (``4b497ae``, ``04c09c6``/``216a624``,
``bed81c7``, ``9736735``, ``46368b2``) each repaired one hard-coded ``.cdf`` or ``.nc`` decode name,
and none added a shared helper or a guard, so the rule drifted back in elsewhere: ``46368b2``
keyed it on the engine alone, which ``bed81c7`` had already shown wrong for a v3.5 CIP decode.
The author, 2026-09-30: *"this issue has come up before - fix it for good"*.

The guard sweeps every ``*.py``, ``*.toml`` and ``*.json`` under ``src`` and ``tools`` for a
decode-shaped ``.cdf`` spelling. Each hit must be in ``ALLOWLIST`` (reviewed: correct by
construction, not a decode, or text that already names both decodes) or ``PENDING`` (a known
defect or single-engine text, naming the slice
that removes it). Both are
keyed on the line's text, not its number, so editing an allowed line forces a re-review, and an
entry that matches nothing fails as stale. ``PENDING`` may only shrink.

Known gap: a hard-coded ``.H.nc`` decode is not swept, because ``proc.<flight>.H.nc`` has the
same spelling; the one such site (``enhancements_uiops/.../pipeline.py``) is converted in slice 5.
"""

# ALLOWLIST and PENDING hold source lines verbatim, so their keys cannot be wrapped.
# ruff: noqa: E501

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path
from typing import NamedTuple

from arrayprobe import provenance
from arrayprobe_uiops import decode_naming as dn

PORT = Path(__file__).resolve().parents[1]
ROOTS = ("src", "scripts")
EXCLUDED_VALIDATION = "scripts/validation"
# validation code was never in this scan's scope; it moved under scripts/ with the layout
# consolidation
EXEMPT = {"src/arrayprobe_uiops/decode_naming.py"}
PATTERNS = tuple(re.compile(p) for p in (
    r"\.H\.cdf|\.V\.cdf|\{channel\}\.cdf|\.cdf[\"']",   # the plan's audit grep
    r"replace\(\s*['\"]\.cdf",
    r"glob\([^)]*\.cdf",
))


class Finding(NamedTuple):
    path: str   # relative to the swept base, posix
    lineno: int
    text: str   # stripped


def sweep(base: Path = PORT, roots: tuple[str, ...] = ROOTS) -> list[Finding]:
    """Every decode-shaped ``.cdf`` spelling under ``base/<root>``, the helper module exempt."""
    out = []
    for root in roots:
        for p in sorted((base / root).rglob("*")):
            if p.suffix not in (".py", ".toml", ".json") or not p.is_file():
                continue
            rel = p.relative_to(base).as_posix()
            if rel in EXEMPT or rel.startswith(EXCLUDED_VALIDATION + "/"):
                continue
            text = p.read_text(encoding="utf-8", errors="replace")
            for i, line in enumerate(text.splitlines(), 1):
                if any(r.search(line) for r in PATTERNS):
                    out.append(Finding(rel, i, line.strip()))
    return out


def unreviewed(findings: list[Finding]) -> list[Finding]:
    return [f for f in findings if (f.path, f.text) not in ALLOWLIST
            and (f.path, f.text) not in PENDING]


_R_B = ("correct by construction: v3.1.4-only code, a SEA/PMS/DMT reader both engines share, "
        "or a v3.1.4 incident record")
_R_C = ("not a decode: combined product, TAS/aircraft, threshold or ARM file, generic suffix set, "
        "or fixed fixture")
_R_D_OK = "user-facing text that already names both decodes"

#: Size of PENDING when the guard landed; it may only shrink (27 lines, 25 distinct texts).
PENDING_AT_LANDING = 25

# Generated from the plan's classification tables (139 lines: 112 allowed, 27 pending) and
# reviewed; keys collapse lines whose text repeats within one file.
ALLOWLIST: dict[tuple[str, str], tuple[str, str]] = {
    ('src/arrayprobe/driver/run_flight.py', 'path = Path(directory) / "aircraft.cdf"'):
        ('c', _R_C),
    ('src/arrayprobe/__init__.py', 'with netCDF4.Dataset("decoded.CIP.cdf") as nc:'):
        ('b', _R_B),
    ('src/arrayprobe/__init__.py', '"decoded.CIP.cdf", "proc.nc", "CIP", 1, n_records, "UND2016",'):
        ('b', _R_B),
    ('src/arrayprobe/__init__.py', 'ap.imgproc_sm("decoded.H.cdf", "proc.nc", "2DS", 1, 1, "ORACLES",'):
        ('b', _R_B),
    ('src/arrayprobe/__init__.py', '"2DS_intArrThreshold_MISSING.cdf",'):
        ('c', _R_C),
    ('src/arrayprobe/cli.py', 'p.add_argument("outfile", help="output path: spec writes <outfile>.H.cdf / <outfile>.V.cdf, "'):
        ('b', _R_B),
    ('src/arrayprobe/cli.py', 'SPEC writes ``<outfile>.H.cdf`` / ``<outfile>.V.cdf`` per ``--channels``, PMS'):
        ('b', _R_B),
    ('src/arrayprobe/cli.py', 'suffixes = {"spec": [f"{c}.cdf" for c in (args.channels or "HV")],'):
        ('b', _R_B),
    ('src/arrayprobe/cli.py', '"pms": ["2dc.cdf", "f2dc.cdf", "2dp.cdf"],'):
        ('b', _R_B),
    ('src/arrayprobe/cli.py', '"sea": ["CIP.cdf", "2DC.cdf"]}.get(args.format)'):
        ('b', _R_B),
    ('src/arrayprobe/cli.py', '# Before any reader runs: SPEC creates its .H/.V.cdf files first and then raised'):
        ('b', _R_B),
    ('src/arrayprobe/cli.py', '+ ("(*.H.nc from v3.5, *.H.cdf from v3.1.4)"'):
        ('d-ok', _R_D_OK),
    ('src/arrayprobe/cli.py', 'p.add_argument("path", help="output path, e.g. aircraft_160906.cdf")'):
        ('c', _R_C),
    ('scripts/release_regression.py', 'NETCDF_SUFFIXES = (".nc", ".nc4", ".cdf")'):
        ('c', _R_C),
    ('src/arrayprobe/count_closure.py', 'and not iat_file[0].endswith("MISSING.cdf"):'):
        ('c', _R_C),
    ('src/arrayprobe/config.py', 'threshold_file = "2DS_intArrThreshold_MISSING.cdf"   # explicit: the twelfth argument'):
        ('c', _R_C),
    ('src/arrayprobe/config.py', 'tas_file = "../aircraft/flightData_160906.cdf"   # only if profile.time_in_seconds_from_tas'):
        ('c', _R_C),
    ('src/arrayprobe/masks.py', "``base160906064403.V.cdf`` is ``'V'``.  It is a positional index, not a"):
        ('b', _R_B),
    ('src/arrayprobe/masks.py', "input defaults to ``[path 'base' date time '.' orientation '_1.cdf']``"):
        ('b', _R_B),
    ('src/arrayprobe/masks.py', 'infile = f"{path_s}base{date}{time}.{orientation}_1.cdf"'):
        ('b', _R_B),
    ('src/arrayprobe_uiops/ncio.py', "``2DS.20151205_subset1.V.cdf`` holds it as ``('time','ImgBlocklen','ImgRowlen')``"):
        ('b', _R_B),
    ('src/arrayprobe_uiops/profiles.py', "* **Step 2** then reads ``[filename '.V.cdf']``."):
        ('b', _R_B),
    ('src/arrayprobe_uiops/profiles.py', "own basename** -- and feeds ``[filename '.V_1.cdf']`` to ``sizeDist``."):
        ('b', _R_B),
    ('src/arrayprobe_uiops/profiles.py', '``read_binary_SPEC`` produces exactly both: ``.H.cdf``/``.V.cdf`` at'):
        ('b', _R_B),
    ('src/arrayprobe_uiops/profiles.py', '``read_binary_SPEC`` over an HVPS file does emit an ``.H.cdf``, but that'):
        ('b', _R_B),
    ('src/arrayprobe_uiops/provenance.py', '_PRODUCT_SUFFIXES = (".nc", ".cdf")'):
        ('c', _R_C),
    ('src/arrayprobe_uiops/readers/pms.py', 'f_2dc, v_2dc = _def_output(f"{outfilename}.2dc.cdf", _N_2DC)'):
        ('b', _R_B),
    ('src/arrayprobe_uiops/readers/pms.py', 'f_f2dc, v_f2dc = _def_output(f"{outfilename}.f2dc.cdf", _N_F2DC)'):
        ('b', _R_B),
    ('src/arrayprobe_uiops/readers/pms.py', 'f_2dp, v_2dp = _def_output(f"{outfilename}.2dp.cdf", _N_2DP)'):
        ('b', _R_B),
    ('src/arrayprobe/readers/sea.py', 'f_cip = ncio.create(f"{outfilename}.CIP.cdf", "clobber")'):
        ('b', _R_B),
    ('src/arrayprobe/readers/sea.py', 'f_2dc = ncio.create(f"{outfilename}.2DC.cdf", "clobber")'):
        ('b', _R_B),
    ('src/arrayprobe/tools/make_demo_flight.py', 'return raw_path.with_name(raw_path.stem + ".aircraft.cdf")'):
        ('c', _R_C),
    ('src/arrayprobe/tools/make_tas_file.py', 'parser.add_argument("path", help="output path, e.g. aircraft_160906.cdf")'):
        ('c', _R_C),
    ('src/arrayprobe/tools/tas_sources.py', '"reads these names; tests/data/demo_flight_v35_aircraft.cdf"),'):
        ('c', _R_C),
    ('src/arrayprobe/triage_server.py', '``proc`` file whose companion decode (``<flight>.H.nc`` from v3.5, ``<flight>.H.cdf``'):
        ('d-ok', _R_D_OK),
    ('src/arrayprobe/triage_server.py', 'Requires the decode (`.H.nc` from v3.5, `.H.cdf` from v3.1.4) as well as the'):
        ('d-ok', _R_D_OK),
    ('src/arrayprobe/triage_server.py', 'f"the decode (<code>.H.nc</code> from v3.5, <code>.H.cdf</code> from "'):
        ('d-ok', _R_D_OK),
    ('src/arrayprobe/triage_server.py', 'Like the diode page it needs the decode (``.H.nc`` or ``.H.cdf``), and says so when the'):
        ('d-ok', _R_D_OK),
    ('src/arrayprobe/triage_server.py', 'f"(<code>.H.nc</code> from v3.5, <code>.H.cdf</code> from v3.1.4), "'):
        ('d-ok', _R_D_OK),
    ('src/arrayprobe/triage_server.py', '"(*.H.nc from v3.5, *.H.cdf from v3.1.4)")'):
        ('d-ok', _R_D_OK),
    ('src/arrayprobe/driver/run_flight.py', 'found += [(p, "original") for p in sorted(out_dir.glob("*.combined.*.cdf"))]'):
        ('c', _R_C),
    ('src/arrayprobe/validate_by_condition.py', 'product_dir, f"base{m.group(1)}*.combined.H.2DS_2.cdf")))'):
        ('c', _R_C),
    ('src/arrayprobe_uiops/spec.py', '4. **NETCDF4 output**, ``.H.cdf``/``.V.cdf`` -> ``.H.nc``/``.V.nc``, with two'):
        ('d-ok', _R_D_OK),
    ('scripts/make_demo_reference.py', '"raw.2DS", "image.cdf", "proc.nc", "sd.nc",'):
        ('b', _R_B),
    ('scripts/make_demo_reference.py', '"run.toml", "aircraft.cdf", "proc.nc", "sd.nc",'):
        ('c', _R_C),
    ('scripts/make_demo_reference.py', 'tas_file = "demo_flight_v35_aircraft.cdf"'):
        ('c', _R_C),
    ('scripts/make_demo_reference.py', 'combined = out_dir / f"{stem}.combined.H.2DS_2.cdf"'):
        ('c', _R_C),
    ('scripts/make_demo_reference.py', 'aircraft = write_aircraft_v35(out_dir / f"{PREFIX_V35}aircraft.cdf")'):
        ('c', _R_C),
    ('scripts/make_demo_reference.py', 'shutil.copyfile(paths["image"], REF_DIR / f"{PREFIX}image.cdf")'):
        ('b', _R_B),
    ('scripts/make_demo_reference.py', 'scrub_output(*(REF_DIR / f"{PREFIX}{n}" for n in ("image.cdf", "proc.nc", "sd.nc")))'):
        ('b', _R_B),
    ('scripts/make_demo_reference.py', 'tracked_image = ref_dir / f"{PREFIX}image.cdf"'):
        ('b', _R_B),
    ('scripts/make_demo_reference.py', 'shutil.copyfile(paths["aircraft"], REF_DIR / f"{PREFIX_V35}aircraft.cdf")'):
        ('c', _R_C),
    ('scripts/make_demo_reference.py', 'tracked_aircraft = ref_dir / f"{PREFIX_V35}aircraft.cdf"'):
        ('c', _R_C),
    ('src/arrayprobe/driver/reprocess.py', 'path = product.parent / f"{raw_stem}.tas_{tier}.cdf"'):
        ('c', _R_C),
    ('src/arrayprobe/driver/run_flight.py', '``read_binary_SPEC`` and written a plausible, wrong ``.H.cdf``.'):
        ('b', _R_B),
    ('src/arrayprobe/driver/run_flight.py', 'IAT_FILE = "2DS_intArrThreshold_MISSING.cdf"'):
        ('c', _R_C),
    ('src/arrayprobe/driver/run_flight.py', 'HVPS_IAT_MISSING = "HVPS_intArrThreshold_MISSING.V_1.cdf"'):
        ('c', _R_C),
    ('src/arrayprobe/driver/run_flight.py', 'args.iat_file = str(Path(args.out) / f"HVPS_intArrThreshold_{stem}.V_1.cdf")'):
        ('c', _R_C),
    ('src/arrayprobe_uiops/oap_read.py', 'The S2 file (``<stem>.H.cdf`` / ``.V.cdf``), written by'):
        ('b', _R_B),
    ('src/arrayprobe/driver/run_flight.py',
     'found = [p for p in sorted(Path(out_dir).glob("*.combined.*.cdf"))'):
        ('c', _R_C),
    ('src/arrayprobe/driver/run_flight.py', 'So a ``.H.cdf`` is exactly as unaskable about its own provenance as a'):
        ('b', _R_B),
    ('src/arrayprobe/driver/run_flight.py', '``.V.cdf`` stamped ``H``, which the next stage would then accept as matching.'):
        ('b', _R_B),
    ('src/arrayprobe/driver/run_flight.py', '# as an `.H.cdf` file name for a stream that was never split. What IS'):
        ('b', _R_B),
    ('src/arrayprobe/driver/run_flight.py', '# So: when the .H.cdf already exists, price S3 off its real record count at'):
        ('b', _R_B),
    ('src/arrayprobe/driver/run_flight.py', '# ~90%, and the .H.cdf came out at 12.4 GB and 14.1 GB from 1.07 GB of raw:'):
        ('b', _R_B),
    ('src/arrayprobe/driver/run_flight.py', '# S9r: this hint used to say "*.V.cdf are the soot-fouled channel" as'):
        ('b', _R_B),
    ('src/arrayprobe/driver/run_flight.py', 'log("  (one field campaign only: its .V.cdf is a soot-fouled channel and is "'):
        ('b', _R_B),
    ('src/arrayprobe/driver/run_flight.py', '# and would have written a plausible, wrong .H.cdf. Refusing here costs one'):
        ('b', _R_B),
    ('src/arrayprobe/driver/run_flight.py', 'native = staging / f"{raw.stem}.{_PMS_NATIVE_SUFFIX[PROBE]}.cdf"'):
        ('b', _R_B),
    ('src/arrayprobe/driver/run_flight.py', 'tas_chain_path = args.out / f"{raw.stem}.tas_{tas_res.tier}.cdf"'):
        ('c', _R_C),
    ('scripts/scrub_paths.py', 'NETCDF_SUFFIXES = frozenset({".nc", ".cdf"})'):
        ('c', _R_C),
    ('scripts/truth_harness.py', 'img = out / f"{raw.stem}.H.cdf"'):
        ('b', _R_B),
    ('scripts/truth_harness.py', 'varargin = ("2DS_intArrThreshold_MISSING.cdf",) if production else ()'):
        ('c', _R_C),
    ('scripts/truth_harness.py', 'decoded, proc, sd = out / "dmt.cdf", out / "proc.nc", out / "sd.nc"'):
        ('b', _R_B),
    ('src/arrayprobe/cli.py', '".H.cdf/.V.cdf); pairing them correctly is the "'):
        ('d-ok', _R_D_OK),
    ('src/arrayprobe/cli.py', '".H.cdf from engine 3.1.4)"'):
        ('d-ok', _R_D_OK),
    ('src/arrayprobe/driver/run_flight.py', 'decode (``.H.nc`` from engine 3.5, ``.H.cdf`` from 3.1.4), and restarting'):
        ('d-ok', _R_D_OK),
    ('src/arrayprobe/driver/run_flight.py', 'The decode is ``<base>.H.nc`` from engine 3.5 and ``<base>.H.cdf`` from 3.1.4'):
        ('d-ok', _R_D_OK),
}

# Rows for development tools the release does not ship live in a dev-only module.
try:  # by module path (python -m unittest tests.X) or as a sibling (discover -s tests)
    try:
        from tests._decode_suffix_dev_exemptions import DEV_EXEMPTIONS
    except ImportError:
        from _decode_suffix_dev_exemptions import DEV_EXEMPTIONS
except ImportError:  # the public release tree
    DEV_EXEMPTIONS = {}
_REASON = {'b': _R_B, 'c': _R_C, 'd-ok': _R_D_OK}
ALLOWLIST.update({k: (c, r or _REASON[c]) for k, (c, r) in DEV_EXEMPTIONS.items()})

PENDING: dict[tuple[str, str], tuple[str, str]] = {}


class TheGuard(unittest.TestCase):
    def test_every_decode_spelling_is_reviewed(self):
        bad = unreviewed(sweep())
        self.assertEqual(bad, [], "a decode name spelled outside arrayprobe_uiops.decode_naming; "
                         "use decode_suffix/decode_name/decode_path, or review the line into "
                         "ALLOWLIST with its class and reason")

    def test_no_stale_entry(self):
        live = {(f.path, f.text) for f in sweep()}
        # An entry for a development file the public release does not ship cannot be live there.
        present = {k for k in ALLOWLIST if (PORT / k[0]).exists()}
        self.assertEqual(sorted(present - live), [], "stale ALLOWLIST entries")
        self.assertEqual(sorted(set(PENDING) - live), [], "stale PENDING entries")

    def test_pending_only_shrinks(self):
        self.assertLessEqual(len(PENDING), PENDING_AT_LANDING)
        self.assertEqual(set(ALLOWLIST) & set(PENDING), set())
        for _key, (_cls, slice_) in PENDING.items():
            self.assertRegex(slice_, r"^slice [2-5]$")

    def test_the_guard_fires_on_a_synthetic_offender(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            (base / "scripts").mkdir()
            (base / "scripts" / "offender.py").write_text(
                'image = d / f"{flight}.H.cdf"\n'
                "target = x.name.replace('.cdf', '.nc')\n"
                "harmless = 'no decode here'\n", encoding="utf-8")
            self.assertEqual(len(unreviewed(sweep(base))), 2)

    def test_an_allowlisted_line_alone_gives_nothing(self):
        (path, text), _ = next(iter(ALLOWLIST.items()))
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / path
            f.parent.mkdir(parents=True)
            f.write_text(text + "\n", encoding="utf-8")
            found = sweep(Path(d))
            self.assertEqual(len(found), 1)
            self.assertEqual(unreviewed(found), [])


class TheHelper(unittest.TestCase):
    def test_engine_by_channel_table(self):
        cases = {("3.5", "H"): ".nc", ("3.5", "V"): ".nc", ("3.5", "CIP"): ".cdf",
                 ("3.5", "PIP"): ".cdf", ("3.1.4", "H"): ".cdf", (None, "V"): ".cdf",
                 ("soda2", "H"): ".cdf"}
        for (engine, channel), want in cases.items():
            self.assertEqual(dn.decode_suffix(engine, channel), want, (engine, channel))
        self.assertEqual(dn.decode_name("base160906", "CIP", "3.5"), "base160906.CIP.cdf")
        self.assertEqual(dn.decode_name("base160906", "H", "3.5"), "base160906.H.nc")

    def _proc(self, d: Path, channel: str = "H", stamp: str | None = None) -> Path:
        p = d / f"proc.base160906064017.{channel}.nc"
        p.write_bytes(b"")
        if stamp is not None:
            provenance.call_path(p).write_text(stamp + "\n", encoding="utf-8")
        return p

    def test_decode_path_follows_the_stamp(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._proc(Path(d), "H", "engine=3.5 stage=S3 profile=STOCK_V35")
            self.assertEqual(dn.decode_path(p).name, "base160906064017.H.nc")
            q = self._proc(Path(d), "CIP", "engine=3.5 stage=S3 profile=STOCK_V35")
            self.assertEqual(dn.decode_path(q).name, "base160906064017.CIP.cdf")

    def test_an_engine_less_stamp_reads_as_v314(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._proc(Path(d), "H", "stage=S3 profile=ORACLES_2016")
            self.assertEqual(dn.decode_path(p).name, "base160906064017.H.cdf")

    def test_no_stamp_raises_unless_the_caller_assumes(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._proc(Path(d), "H")
            with self.assertRaises(provenance.Unstamped):
                dn.decode_path(p)
            self.assertEqual(dn.decode_path(p, assume_engine="3.1.4").name,
                             "base160906064017.H.cdf")
            self.assertEqual(dn.decode_path(p, assume_engine="3.5").name,
                             "base160906064017.H.nc")

    def test_never_chosen_by_which_file_exists(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._proc(Path(d), "H", "engine=3.5 stage=S3 profile=STOCK_V35")
            (Path(d) / "base160906064017.H.cdf").write_bytes(b"stale")
            self.assertEqual(dn.decode_path(p).suffix, ".nc")

    def test_diodecorrected_proc(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "proc.base160906064017.H.diodecorrected.nc"
            p.write_bytes(b"")
            self.assertEqual(dn.decode_path(p, assume_engine="3.5").name,
                             "base160906064017.H.nc")


class ValidationIsExcluded(unittest.TestCase):
    def test_scripts_validation_exists_and_is_excluded(self):
        self.assertTrue((PORT / "scripts" / "validation").is_dir())
        self.assertFalse([f for f in sweep() if f.path.startswith(EXCLUDED_VALIDATION + "/")])


if __name__ == "__main__":
    unittest.main()

# A repository sweep: run before every full suite by the pre-suite gate
# (tests/test_presuite_covers_repo_sweeps.py keeps that true).
PRESUITE_GUARD = True

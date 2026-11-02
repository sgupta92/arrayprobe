# SPDX-License-Identifier: BSD-3-Clause
"""Octave oracle for v3.5 ``sizeDist.m``'s ``iaThreshType`` 1 and 2
shattering/reacceptance gates, and the new ``area_ratio`` clamp.

The tables bank (``run_v35_sizedist_tables_bank.py``) already measured the **new**
``iaThreshType == 3`` gate (``:1383-1428``) and its rewritten, bracketed
reacceptance scan.  This bank measures the other two gates in the same
function -- ``:1179-1221`` (``iaThreshType == 1``, a threshold **file**) and
``:1308-1354`` (``iaThreshType == 2``, a per-second constant) -- which are
**not new**: they are the same ``for iEvent = find(rBegin):find(rEnd)`` idiom
this project already documents as a preserved v3.1.4 defect
(``sizeDist.m:1036``/``:1169``; ``arrayprobe.sizedist._reaccept_shattered``).
The point of measuring them here, rather than assuming "unchanged" from the
2026-09-10 diff read, is that v3.5's own source now has **three** structurally
similar loops that do **not** all behave the same way, and getting that
uniform in either direction is the trap this stage exists to avoid.

Each block is sliced out of the vendored v3.5 file by a textual anchor, never a
line number, exactly as the tables bank's ``extract_type3_block`` does -- through the
``end`` immediately following ``auto_reject(eIndex) = 'R';`` -- so the same
free variables need binding: ``int_arr``, ``int_arr3``, ``particle_diameter_minR``,
``auto_reject``, ``reaccptShatrs``, ``reaccptD``, ``reaccptMaxIA``, plus
``iaThresh`` (type 1, a **per-particle vector** -- the file-derived threshold
varies within a second) or ``intar_threshold``/``i``/``int_arr2`` (type 2, a
**per-second scalar** -- ``intar_threshold(i)`` is the same value for every
particle in that second).  Nothing is written into either ``UIOOPS-*/`` tree.

A third, independent block is measured here too: the ``area_ratio`` clamp
added at v3.5 ``:1161`` (``area_ratio(area_ratio > 1.) = 1.; % Added by Joe
Finlon 03/19/23``), which v3.1.4 does not have (confirmed absent by grep) and
which was found only by reading the driver body directly --
it is a single line inside the driver, not a separate function.
It sits between the ``area_ratio`` computation and the ``'z'``
reject-code threshold test, so it changes every later reader of
``area_ratio`` (the written ``ar``/``dist_AreaR`` outputs, in particular) but
not, since it can only raise values, which particles are marked ``'z'``.

Run:  .venv/Scripts/python.exe octave_oracle/run_v35_sizedist_shatter_bank.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dewrap import OctaveUnavailable, octave_binary  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import _upstream  # noqa: E402
from scrub_paths import scrub_output  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
V35_SIZEDIST = _upstream.source("uiops35") / "sizeDist.m"
V314_SIZEDIST = _upstream.source("uiops314") / "sizeDist.m"
FIXTURE = (
    Path(__file__).resolve().parents[3] / "tests" / "data" / "v35_sizedist_shatter_oracle.json"
)

#: The SAME numeric cases the tables bank used for the type-3 gate (``TYPE3_CASES`` in
#: ``run_v35_sizedist_tables_bank.py``), transcribed rather than imported so
#: this bank has no import-time dependency on that one -- the two are allowed
#: to diverge if either gate's own case grid ever needs to grow.  Kept
#: numerically identical for the cases both banks share, which is what makes
#: the cross-gate divergence test meaningful: same inputs, different function.
SHARED_CASES = {
    "reaccept_two_events_spanned": {
        # two shattering events in one second; the OLD idiom
        # (find(rBegin):find(rEnd)) scans only 2:3 and reaccepts index 3 -- the
        # NEW bracketed scan (the tables bank, type 3) reaccepts index 6 instead. This is
        # the single case this whole bank exists to run.
        "int_arr": [5e-6, 5e-6, 1e-7, 5e-6, 5e-6, 1e-7, 5e-6],
        "int_arr3": [5e-6, 1e-7, 5e-6, 5e-6, 1e-7, 5e-6, 5e-6],
        "diam": [0.2, 0.2, 0.6, 0.2, 0.2, 0.8, 0.2],
        "thresh": 1e-6,
        "reaccpt": 1,
        "reaccptD": 0.5,
        "reaccptMaxIA": 1e-6,
    },
    "reaccept_one_large_fringe": {
        "int_arr": [5e-6, 5e-6, 1e-7, 1e-7, 1e-7, 5e-6],
        "int_arr3": [5e-6, 1e-7, 1e-7, 1e-7, 5e-6, 5e-6],
        "diam": [0.2, 0.2, 0.3, 0.9, 0.2, 0.2],
        "thresh": 1e-6,
        "reaccpt": 1,
        "reaccptD": 0.5,
        "reaccptMaxIA": 1e-6,
    },
    "reaccept_event_at_block_start": {
        "int_arr": [1e-7, 1e-7, 5e-6],
        "int_arr3": [1e-7, 5e-6, 5e-6],
        "diam": [0.9, 0.9, 0.2],
        "thresh": 1e-6,
        "reaccpt": 1,
        "reaccptD": 0.5,
        "reaccptMaxIA": 1e-6,
    },
    "reaccept_no_events": {
        "int_arr": [5e-6, 5e-6, 5e-6],
        "int_arr3": [5e-6, 5e-6, 5e-6],
        "diam": [0.9, 0.9, 0.9],
        "thresh": 1e-6,
        "reaccpt": 1,
        "reaccptD": 0.5,
        "reaccptMaxIA": 1e-6,
    },
    "single_particle_below": {
        "int_arr": [1e-7],
        "int_arr3": [5e-6],
        "diam": [0.2],
        "thresh": 1e-6,
        "reaccpt": 0,
        "reaccptD": 0.5,
        "reaccptMaxIA": 1e-6,
    },
    "equal_to_threshold_is_flagged": {
        "int_arr": [5e-6, 1e-6, 5e-6],
        "int_arr3": [1e-6, 5e-6, 5e-6],
        "diam": [0.2, 0.2, 0.2],
        "thresh": 1e-6,
        "reaccpt": 0,
        "reaccptD": 0.5,
        "reaccptMaxIA": 1e-6,
    },
}

#: Type-2-only cases exercising the ``int_arr2`` next-second boundary check
#: (``:1311-1315``), which neither the type-1 nor the type-3 gate has.
TYPE2_ONLY_CASES = {
    "next_second_opens_with_burst": {
        "int_arr": [5e-6, 5e-6, 5e-6],
        "int_arr3": [5e-6, 5e-6, 5e-6],
        "diam": [0.9, 0.9, 0.9],
        "thresh": 1e-6,
        "reaccpt": 0,
        "reaccptD": 0.5,
        "reaccptMaxIA": 1e-6,
        "int_arr2": [1e-7],
    },
    "next_second_calm": {
        "int_arr": [5e-6, 5e-6, 5e-6],
        "int_arr3": [5e-6, 5e-6, 5e-6],
        "diam": [0.9, 0.9, 0.9],
        "thresh": 1e-6,
        "reaccpt": 0,
        "reaccptD": 0.5,
        "reaccptMaxIA": 1e-6,
        "int_arr2": [5e-6],
    },
    "no_next_second": {
        "int_arr": [5e-6, 5e-6, 5e-6],
        "int_arr3": [5e-6, 5e-6, 5e-6],
        "diam": [0.9, 0.9, 0.9],
        "thresh": 1e-6,
        "reaccpt": 0,
        "reaccptD": 0.5,
        "reaccptMaxIA": 1e-6,
        "int_arr2": [],
    },
}

#: The area_ratio clamp (v3.5 ``:1160-1162``): (area, diameter) pairs chosen to
#: land above, at, and below both the 1.0 clamp and the 0.2 reject threshold.
AREA_RATIO_CASES = {
    "below_one_below_z": {"area": 0.005, "diam": 0.2},   # ar ~ 0.159 -> 'z'
    "below_one_above_z": {"area": 0.02, "diam": 0.2},    # ar ~ 0.637
    "above_one": {"area": 0.05, "diam": 0.2},            # raw ar ~ 1.59 -> clamped to 1
    "exactly_one": {"area": None, "diam": 0.2},          # area set to pi/4*d^2 exactly
    "nan_area": {"area": float("nan"), "diam": 0.2},
}


def _extract_gate_block(path: Path, anchor: str, *, label: str) -> dict:
    """From the line after the one starting with ``anchor`` through the ``end``
    immediately following ``auto_reject(eIndex) = 'R';`` -- the same boundary
    ``run_v35_sizedist_tables_bank.extract_type3_block`` uses for the type-3
    gate, applied here to the type-1 and type-2 gates."""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    head = next((i for i, ln in enumerate(lines) if ln.strip().startswith(anchor)), None)
    if head is None:
        raise RuntimeError(f"{label}: start anchor not found")
    tail = next(
        (
            i
            for i in range(head + 1, len(lines))
            if lines[i].strip() == "auto_reject(eIndex) = 'R';"
        ),
        None,
    )
    if tail is None:
        raise RuntimeError(f"{label}: reacceptance line not found")
    if lines[tail + 1].strip() != "end":
        raise RuntimeError(f"{label}: expected 'end' after the reacceptance assignment")
    text = "\n".join(lines[head + 1 : tail + 2]) + "\n"
    return {"start_line": head + 2, "end_line": tail + 2, "text": text}


def extract_type1_block(path: Path) -> dict:
    return _extract_gate_block(
        path, "if iaThreshType == 1 && applyIntArrThresh", label="type-1 gate"
    )


def extract_type2_block(path: Path) -> dict:
    return _extract_gate_block(
        path, "if iaThreshType == 2 && applyIntArrThresh", label="type-2 gate"
    )


def extract_area_ratio_block(path: Path) -> dict:
    """``area_ratio = area./(pi/4.*particle_diameter_minR.^2);`` through
    ``auto_reject(area_ratio < .2) = 'z';`` inclusive."""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    head = next(
        (
            i
            for i, ln in enumerate(lines)
            if ln.strip() == "area_ratio = area./(pi/4.*particle_diameter_minR.^2);"
        ),
        None,
    )
    if head is None:
        raise RuntimeError("area_ratio block: start anchor not found")
    tail = next(
        (
            i
            for i in range(head, min(head + 6, len(lines)))
            if lines[i].strip() == "auto_reject(area_ratio < .2) = 'z';"
        ),
        None,
    )
    if tail is None:
        raise RuntimeError("area_ratio block: 'z' threshold line not found nearby")
    text = "\n".join(lines[head : tail + 1]) + "\n"
    return {"start_line": head + 1, "end_line": tail + 1, "text": text}


_HARNESS = r"""
more off;
pkg load netcdf;
scratch = '{scratch}';
outfile = '{outfile}';
out = struct();

cases = jsondecode(fileread(fullfile(scratch, 'cases.json')));

% ---- type-1 gate: iaThresh is read from a FILE, a PER-PARTICLE vector -----
% The real block opens `iaThreshFile` itself (`netcdf.open`/`getVar('threshold')`
% with `start`/`count`), so the oracle must write a real threshold netCDF per
% case rather than bind `iaThresh` directly -- unlike the type-3 block, which
% receives its threshold as an ordinary bound variable.
blk = fileread(fullfile(scratch, 'type1.m'));
names = fieldnames(cases.type1);
recs = struct();
for k = 1:numel(names)
    clear -x blk cases names recs k out scratch outfile;
    c = cases.type1.(names{{k}});
    int_arr = c.int_arr(:);
    int_arr3 = c.int_arr3(:);
    particle_diameter_minR = c.diam(:);
    n = numel(int_arr);
    threshvals = repmat(c.thresh, n, 1);
    iaThreshFile = fullfile(scratch, sprintf('thresh_%d.nc', k));
    if exist(iaThreshFile, 'file'); delete(iaThreshFile); end
    wid = netcdf.create(iaThreshFile, 'clobber');
    tdim = netcdf.defDim(wid, 'Time', n);
    tvid = netcdf.defVar(wid, 'threshold', 'double', tdim);
    netcdf.endDef(wid);
    netcdf.putVar(wid, tvid, threshvals);
    netcdf.close(wid);
    start = 0;
    count = n;
    reaccptShatrs = c.reaccpt;
    reaccptD = c.reaccptD;
    reaccptMaxIA = c.reaccptMaxIA;
    auto_reject = repmat('A', numel(int_arr), 1);
    rec = struct('status', 'OK', 'message', '');
    try
        eval(blk);
        rec.auto_reject = reshape(auto_reject, 1, []);
        rec.iaThresh = reshape(iaThresh, 1, []);
        if exist('eIndex', 'var') == 1
            rec.eIndex = strtrim(sprintf('%d ', eIndex));
        else
            rec.eIndex = '__UNDEFINED__';
        end
    catch err
        rec.status = 'ERROR';
        rec.message = err.message;
    end
    recs.(names{{k}}) = rec;
end
out.type1 = recs;

% ---- type-2 gate: intar_threshold(i) is a PER-SECOND scalar ----------------
blk = fileread(fullfile(scratch, 'type2.m'));
names = fieldnames(cases.type2);
recs = struct();
for k = 1:numel(names)
    clear -x blk cases names recs k out scratch outfile;
    c = cases.type2.(names{{k}});
    int_arr = c.int_arr(:);
    int_arr3 = c.int_arr3(:);
    particle_diameter_minR = c.diam(:);
    i = 2;
    intar_threshold = [NaN c.thresh NaN];  % only intar_threshold(i) may be read
    if isfield(c, 'int_arr2') && ~isempty(c.int_arr2)
        int_arr2 = c.int_arr2(:);
    else
        int_arr2 = [];
    end
    reaccptShatrs = c.reaccpt;
    reaccptD = c.reaccptD;
    reaccptMaxIA = c.reaccptMaxIA;
    auto_reject = repmat('A', numel(int_arr), 1);
    rec = struct('status', 'OK', 'message', '');
    try
        eval(blk);
        rec.auto_reject = reshape(auto_reject, 1, []);
        if exist('eIndex', 'var') == 1
            rec.eIndex = strtrim(sprintf('%d ', eIndex));
        else
            rec.eIndex = '__UNDEFINED__';
        end
    catch err
        rec.status = 'ERROR';
        rec.message = err.message;
    end
    recs.(names{{k}}) = rec;
end
out.type2 = recs;

% ---- the area_ratio clamp (:1160-1162) -------------------------------------
blk = fileread(fullfile(scratch, 'area_ratio.m'));
names = fieldnames(cases.area_ratio);
recs = struct();
for k = 1:numel(names)
    clear -x blk cases names recs k out scratch outfile;
    c = cases.area_ratio.(names{{k}});
    particle_diameter_minR = c.diam;
    if isempty(c.area)
        area = (pi/4) * particle_diameter_minR^2;   % exactly 1.0 before any clamp
    else
        area = c.area;
    end
    auto_reject = 'A';
    rec = struct('status', 'OK', 'message', '');
    try
        eval(blk);
        rec.area_ratio = area_ratio;
        rec.auto_reject = auto_reject;
    catch err
        rec.status = 'ERROR';
        rec.message = err.message;
    end
    recs.(names{{k}}) = rec;
end
out.area_ratio = recs;

fid = fopen(outfile, 'w');
fprintf(fid, '%s', jsonencode(out));
fclose(fid);
"""


def main() -> int:
    try:
        octave = octave_binary()
    except OctaveUnavailable as exc:
        print(exc, file=sys.stderr)
        return 2

    type1_cases = dict(SHARED_CASES)
    type2_cases = {**SHARED_CASES, **TYPE2_ONLY_CASES}

    blocks = {
        "type1_v35": extract_type1_block(V35_SIZEDIST),
        "type2_v35": extract_type2_block(V35_SIZEDIST),
        "area_ratio_v35": extract_area_ratio_block(V35_SIZEDIST),
    }

    with tempfile.TemporaryDirectory() as tmp:
        scratch = Path(tmp)
        (scratch / "type1.m").write_text(blocks["type1_v35"]["text"], encoding="utf-8")
        (scratch / "type2.m").write_text(blocks["type2_v35"]["text"], encoding="utf-8")
        (scratch / "area_ratio.m").write_text(blocks["area_ratio_v35"]["text"], encoding="utf-8")
        cases_payload = {
            "type1": type1_cases,
            "type2": type2_cases,
            "area_ratio": {
                k: {"area": (None if v["area"] is None else v["area"]), "diam": v["diam"]}
                for k, v in AREA_RATIO_CASES.items()
            },
        }
        # jsondecode needs an explicit null, not a bare Python None serialized
        # inconsistently -- json.dumps already does the right thing for None.
        (scratch / "cases.json").write_text(json.dumps(cases_payload), encoding="utf-8")
        outfile = scratch / "out.json"
        script = scratch / "bank.m"
        script.write_text(
            _HARNESS.format(scratch=scratch.as_posix(), outfile=outfile.as_posix()),
            encoding="utf-8",
        )
        proc = subprocess.run(  # noqa: S603 - fixed binary, generated script
            [octave, "--quiet", "--no-gui", str(script)],
            capture_output=True,
            text=True,
            timeout=600,
        )
        if not outfile.exists():
            raise RuntimeError(
                f"Octave wrote no output.\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
            )
        raw = json.loads(outfile.read_text(encoding="utf-8"))

    def _decode_shatter(name: str) -> dict:
        table = {}
        for case, rec in raw[name].items():
            if rec["status"] == "OK":
                entry = {
                    "status": "OK",
                    "auto_reject": rec["auto_reject"],
                    "eIndex": [int(t) for t in rec["eIndex"].split()]
                    if rec["eIndex"] not in ("", "__UNDEFINED__")
                    else [],
                }
                if "iaThresh" in rec:
                    entry["iaThresh"] = rec["iaThresh"]
                table[case] = entry
            else:
                table[case] = {"status": "ERROR", "message": rec["message"]}
        return table

    type1 = _decode_shatter("type1")
    type2 = _decode_shatter("type2")

    area_ratio = {}
    for case, rec in raw["area_ratio"].items():
        if rec["status"] == "OK":
            area_ratio[case] = {
                "status": "OK",
                "area_ratio": rec["area_ratio"],
                "auto_reject": rec["auto_reject"],
            }
        else:
            area_ratio[case] = {"status": "ERROR", "message": rec["message"]}

    fixture = {
        "blocks": blocks,
        "type1_cases": type1_cases,
        "type2_cases": type2_cases,
        "area_ratio_cases": AREA_RATIO_CASES,
        "type1": type1,
        "type2": type2,
        "area_ratio": area_ratio,
    }
    FIXTURE.write_text(json.dumps(fixture, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    scrub_output(FIXTURE)  # path prefixes -> <repo>, <tmp>, ~
    n1 = sum(1 for r in type1.values() if r["status"] == "OK")
    n2 = sum(1 for r in type2.values() if r["status"] == "OK")
    nz = sum(1 for r in area_ratio.values() if r["status"] == "OK")
    print(f"wrote {FIXTURE}: type1 OK={n1}/{len(type1)}, type2 OK={n2}/{len(type2)}, "
          f"area_ratio OK={nz}/{len(area_ratio)}")
    t1 = type1.get("reaccept_two_events_spanned", {})
    t2 = type2.get("reaccept_two_events_spanned", {})
    print(f"reaccept_two_events_spanned: type1={t1} type2={t2}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

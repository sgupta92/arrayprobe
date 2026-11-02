# SPDX-License-Identifier: BSD-3-Clause
"""Octave oracle for the self-contained pieces of v3.5's ``sizeDist.m``.

Four blocks of ``sizeDist.m`` are pure — no file handles, no netCDF — and can be
measured on a case grid without the netCDF input the whole driver needs:

1. the campaign/probe ``switch`` block that sets ``num_bins``, ``kk`` and the
   other per-probe defaults (sliced out of **both** the v3.5 and the v3.1.4
   file, so the bin-table diff between releases is measured, not read);
2. v3.5's ``varargin`` block (``iaThreshType==3`` is new there);
3. v3.5's ``iNewHabit`` detection (``ismember('width_length_percentile', ...)``);
4. v3.5's ``iaThreshType==3`` shatter-flagging and reacceptance block.

Each block is **sliced out of the vendored file by a textual anchor**, never a
hard-coded line number, and ``eval``-ed under Octave with the block's free
variables bound per case.  The recovered text of every block is stored in the
fixture so ``tests/test_v35_sizedist_tables.py`` can re-slice the file and fail
when the vendored source moves.  Nothing is written into either ``UIOOPS-*/``
tree; the scratch directory is put on Octave's path.

Run:  .venv/Scripts/python.exe octave_oracle/run_v35_sizedist_tables_bank.py
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
FIXTURE = Path(__file__).resolve().parents[3] / "tests" / "data" / "v35_sizedist_tables_oracle.json"

#: Every campaign named by either file's outer ``switch``, plus one name neither
#: lists so the ``otherwise`` branch is exercised (ORACLES is what this project
#: actually processes, and it has never had its own branch in any release).
CAMPAIGNS = ["PECAN", "GPM", "SOCRATES", "IMPACTS", "ORACLES"]
#: Every probe named by either file's inner ``switch`` blocks.
PROBES = ["2DS", "HVPS", "CIP", "PIP", "2DC", "2DP", "F2DC", "Fast2DC", "3VCPI_V", "3VCPI_H"]
#: The variables the switch block can assign; dumped when they exist.
SWITCH_VARS = [
    "num_diodes",
    "diodesize",
    "armdst",
    "num_bins",
    "kk",
    "probetype",
    "tasMax",
    "applyIntArrThresh",
    "defaultIntArrThresh",
    "reaccptShatrs",
    "reaccptD",
    "reaccptMaxIA",
    "intar_threshold",
]

#: (iaThreshType, number of varargin entries) for the varargin block.
VARARGIN_CASES = [(t, n) for t in (0, 1, 2, 3) for n in (0, 1, 2)]

#: Variable lists handed to the iNewHabit block.
HABIT_CASES = {
    "old_scheme_file": ["Time", "image_diam_minR", "holroyd_habit"],
    "new_scheme_file": ["Time", "image_diam_minR", "holroyd_habit", "width_length_percentile"],
    "empty_list": [],
    "prefix_only": ["width_length_percentile_2"],
    "different_case": ["Width_Length_Percentile"],
}

#: Cases for the type-3 block: int_arr, int_arr3, diameters, threshold, reacceptance settings.
#: ``int_arr3`` is the block's own "next particle's inter-arrival" input; it is
#: bound here, not derived, since the block reads it and never defines it.
TYPE3_CASES = {
    "single_particle_below": {
        "int_arr": [1e-7],
        "int_arr3": [5e-6],
        "diam": [0.2],
        "thresh": 1e-6,
        "reaccpt": 0,
        "reaccptD": 0.5,
        "reaccptMaxIA": 1e-6,
    },
    "single_particle_above": {
        "int_arr": [5e-6],
        "int_arr3": [5e-6],
        "diam": [0.2],
        "thresh": 1e-6,
        "reaccpt": 0,
        "reaccptD": 0.5,
        "reaccptMaxIA": 1e-6,
    },
    "pair_flagged_by_second": {
        "int_arr": [5e-6, 1e-7, 5e-6, 5e-6],
        "int_arr3": [1e-7, 5e-6, 5e-6, 5e-6],
        "diam": [0.2, 0.2, 0.2, 0.2],
        "thresh": 1e-6,
        "reaccpt": 0,
        "reaccptD": 0.5,
        "reaccptMaxIA": 1e-6,
    },
    "first_and_interior": {
        "int_arr": [1e-7, 5e-6, 5e-6, 1e-7, 1e-7, 5e-6],
        "int_arr3": [5e-6, 5e-6, 1e-7, 1e-7, 5e-6, 5e-6],
        "diam": [0.2, 0.2, 0.2, 0.2, 0.2, 0.2],
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
    "reaccept_one_large_fringe": {
        # one shattering event: rBegin at 2 (int_arr>thr, next<thr), rEnd at 5
        "int_arr": [5e-6, 5e-6, 1e-7, 1e-7, 1e-7, 5e-6],
        "int_arr3": [5e-6, 1e-7, 1e-7, 1e-7, 5e-6, 5e-6],
        "diam": [0.2, 0.2, 0.3, 0.9, 0.2, 0.2],
        "thresh": 1e-6,
        "reaccpt": 1,
        "reaccptD": 0.5,
        "reaccptMaxIA": 1e-6,
    },
    "reaccept_two_events_spanned": {
        # two events; v3.5 type-3 scans first rBegin .. last rEnd as one range
        "int_arr": [5e-6, 5e-6, 1e-7, 5e-6, 5e-6, 1e-7, 5e-6],
        "int_arr3": [5e-6, 1e-7, 5e-6, 5e-6, 1e-7, 5e-6, 5e-6],
        "diam": [0.2, 0.2, 0.6, 0.2, 0.2, 0.8, 0.2],
        "thresh": 1e-6,
        "reaccpt": 1,
        "reaccptD": 0.5,
        "reaccptMaxIA": 1e-6,
    },
    "reaccept_nothing_large_enough": {
        "int_arr": [5e-6, 5e-6, 1e-7, 1e-7, 5e-6],
        "int_arr3": [5e-6, 1e-7, 1e-7, 5e-6, 5e-6],
        "diam": [0.2, 0.2, 0.3, 0.4, 0.2],
        "thresh": 1e-6,
        "reaccpt": 1,
        "reaccptD": 0.5,
        "reaccptMaxIA": 1e-6,
    },
    "reaccept_event_at_block_start": {
        # no rBegin can exist for an event that starts at index 1
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
}


def _slice(lines: list[str], start_pred, end_pred, *, label: str) -> tuple[int, int, str]:
    """Return (start_line_1based, end_line_1based, text) of the first block whose
    first line satisfies ``start_pred`` and whose last line is the first line
    after it satisfying ``end_pred``."""
    start = next((i for i, ln in enumerate(lines) if start_pred(ln)), None)
    if start is None:
        raise RuntimeError(f"{label}: start anchor not found")
    end = next((i for i in range(start + 1, len(lines)) if end_pred(lines[i])), None)
    if end is None:
        raise RuntimeError(f"{label}: end anchor not found")
    return start + 1, end + 1, "\n".join(lines[start : end + 1]) + "\n"


def extract_switch_block(path: Path) -> dict:
    """The ``switch projectname`` ... ``end`` block: opens at column 0 and is
    closed by the first column-0 ``end`` after it."""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    s, e, text = _slice(
        lines,
        lambda ln: ln.rstrip() == "switch projectname",
        lambda ln: ln.rstrip() == "end",
        label=f"switch block of {path.name}",
    )
    return {"start_line": s, "end_line": e, "text": text}


def extract_varargin_block(path: Path) -> dict:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    s, e, text = _slice(
        lines,
        lambda ln: ln.rstrip() == "if length(varargin) == 1",
        lambda ln: ln.rstrip() == "end",
        label="varargin block",
    )
    return {"start_line": s, "end_line": e, "text": text}


def extract_habit_block(path: Path) -> dict:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    s, e, text = _slice(
        lines,
        lambda ln: ln.rstrip() == "if ismember('width_length_percentile', ncnames)",
        lambda ln: ln.rstrip() == "end",
        label="iNewHabit block",
    )
    return {"start_line": s, "end_line": e, "text": text}


def extract_type3_block(path: Path) -> dict:
    """The body of ``if iaThreshType == 3 && applyIntArrThresh && length(varargin) == 1``:
    from the line after that ``if`` through the ``end`` that closes
    ``if reaccptShatrs`` (the line after ``auto_reject(eIndex) = 'R';``).
    The outer ``if``'s own line is not included, so the block's free variables
    are ``int_arr``, ``int_arr3``, ``particle_diameter_minR``, ``iatThresh``,
    ``i``, ``auto_reject``, ``reaccptShatrs``, ``reaccptD``, ``reaccptMaxIA``."""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    head = next(
        (
            i
            for i, ln in enumerate(lines)
            if ln.strip() == "if iaThreshType == 3 && applyIntArrThresh && length(varargin) == 1"
        ),
        None,
    )
    if head is None:
        raise RuntimeError("type-3 block: start anchor not found")
    tail = next(
        (
            i
            for i in range(head + 1, len(lines))
            if lines[i].strip() == "auto_reject(eIndex) = 'R';"
        ),
        None,
    )
    if tail is None:
        raise RuntimeError("type-3 block: 'auto_reject(eIndex) = 'R';' not found")
    if lines[tail + 1].strip() != "end":
        raise RuntimeError("type-3 block: expected 'end' after the reacceptance assignment")
    text = "\n".join(lines[head + 1 : tail + 2]) + "\n"
    return {"start_line": head + 2, "end_line": tail + 2, "text": text}


_HARNESS = r"""
more off;
scratch = '{scratch}';
outfile = '{outfile}';
out = struct();

% ---- 1. the campaign/probe switch block, both releases ----------------------
campaigns = {campaigns};
probes = {probes};
vars = {switch_vars};
versions = {{'v35', 'v314'}};
for iv = 1:numel(versions)
    blk = fileread(fullfile(scratch, ['switch_' versions{{iv}} '.m']));
    recs = struct();
    for ic = 1:numel(campaigns)
        for ip = 1:numel(probes)
            clear -x blk recs campaigns probes vars versions iv ic ip out scratch outfile;
            projectname = campaigns{{ic}};
            probename = probes{{ip}};
            ddate = '20150620';
            tas_time = [0 1 2];
            rec = struct('status', 'OK', 'message', '');
            try
                eval(blk);
            catch err
                rec.status = 'ERROR';
                rec.message = err.message;
            end
            for k = 1:numel(vars)
                v = vars{{k}};
                if exist(v, 'var') == 1
                    val = eval(v);
                    rec.(v) = strtrim(sprintf('%.17g ', val));
                end
            end
            key = sprintf('%s__%s', projectname, probename);
            recs.(key) = rec;
        end
    end
    out.(['switch_' versions{{iv}}]) = recs;
end

% ---- 2. the varargin block (v3.5) --------------------------------------------
blk = fileread(fullfile(scratch, 'varargin_v35.m'));
vc = {varargin_cases};
recs = struct();
for k = 1:size(vc, 1)
    clear -x blk recs vc k out scratch outfile;
    iaThreshType = vc(k, 1);
    n = vc(k, 2);
    varargin = cell(1, n);
    for q = 1:n
        varargin{{q}} = [0.001 0.002 0.003];  % a stand-in per-second array
    end
    rec = struct('status', 'OK', 'message', '');
    try
        eval(blk);
    catch err
        rec.status = 'ERROR';
        rec.message = err.message;
    end
    if exist('iaThreshFile', 'var') == 1
        if ischar(iaThreshFile)
            rec.iaThreshFile = iaThreshFile;
        else
            rec.iaThreshFile = strtrim(sprintf('%.17g ', iaThreshFile));
        end
    else
        rec.iaThreshFile = '__UNDEFINED__';
    end
    if exist('iatThresh', 'var') == 1
        rec.iatThresh = strtrim(sprintf('%.17g ', iatThresh));
    else
        rec.iatThresh = '__UNDEFINED__';
    end
    recs.(sprintf('type%d_nargs%d', iaThreshType, n)) = rec;
end
out.varargin_v35 = recs;

% ---- 3. the iNewHabit block (v3.5) -------------------------------------------
blk = fileread(fullfile(scratch, 'habit_v35.m'));
hc = jsondecode(fileread(fullfile(scratch, 'habit_cases.json')));
names = fieldnames(hc);
recs = struct();
for k = 1:numel(names)
    clear -x blk hc names recs k out scratch outfile;
    ncnames = hc.(names{{k}});
    if isempty(ncnames)
        ncnames = {{}};
    elseif ~iscell(ncnames)
        ncnames = cellstr(ncnames);
    end
    ncnames = reshape(ncnames, 1, []);
    rec = struct('status', 'OK', 'message', '');
    try
        eval(blk);
        rec.iNewHabit = iNewHabit;
        rec.attr_habit = attr_habit;
    catch err
        rec.status = 'ERROR';
        rec.message = err.message;
    end
    recs.(names{{k}}) = rec;
end
out.habit_v35 = recs;

% ---- 4. the iaThreshType==3 shatter/reacceptance block (v3.5) ----------------
blk = fileread(fullfile(scratch, 'type3_v35.m'));
tc = jsondecode(fileread(fullfile(scratch, 'type3_cases.json')));
names = fieldnames(tc);
recs = struct();
for k = 1:numel(names)
    clear -x blk tc names recs k out scratch outfile;
    c = tc.(names{{k}});
    int_arr = c.int_arr(:);
    int_arr3 = c.int_arr3(:);
    particle_diameter_minR = c.diam(:);
    i = 2;
    iatThresh = [NaN c.thresh NaN];   % only iatThresh(i) may be read
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
out.type3_v35 = recs;

fid = fopen(outfile, 'w');
fprintf(fid, '%s', jsonencode(out));
fclose(fid);
"""


def _cellstr(items: list[str]) -> str:
    return "{" + ", ".join("'" + s + "'" for s in items) + "}"


def _parse_numbers(s: str) -> list[float]:
    return [float(tok) for tok in s.split()] if s else []


def main() -> int:
    try:
        octave = octave_binary()
    except OctaveUnavailable as exc:
        print(exc, file=sys.stderr)
        return 2
    blocks = {
        "switch_v35": extract_switch_block(V35_SIZEDIST),
        "switch_v314": extract_switch_block(V314_SIZEDIST),
        "varargin_v35": extract_varargin_block(V35_SIZEDIST),
        "habit_v35": extract_habit_block(V35_SIZEDIST),
        "type3_v35": extract_type3_block(V35_SIZEDIST),
    }
    with tempfile.TemporaryDirectory() as tmp:
        scratch = Path(tmp)
        for name, blk in blocks.items():
            (scratch / f"{name}.m").write_text(blk["text"], encoding="utf-8")
        (scratch / "habit_cases.json").write_text(json.dumps(HABIT_CASES), encoding="utf-8")
        (scratch / "type3_cases.json").write_text(json.dumps(TYPE3_CASES), encoding="utf-8")
        outfile = scratch / "out.json"
        script = scratch / "bank.m"
        script.write_text(
            _HARNESS.format(
                scratch=scratch.as_posix(),
                outfile=outfile.as_posix(),
                campaigns=_cellstr(CAMPAIGNS),
                probes=_cellstr(PROBES),
                switch_vars=_cellstr(SWITCH_VARS),
                varargin_cases="[" + "; ".join(f"{t} {n}" for t, n in VARARGIN_CASES) + "]",
            ),
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

    # Decode the switch results into typed records.
    switch_results = {}
    for ver in ("v35", "v314"):
        table = {}
        for key, rec in raw[f"switch_{ver}"].items():
            campaign, probe = key.split("__", 1)
            out = {"status": rec["status"], "message": rec.get("message", "")}
            for v in SWITCH_VARS:
                if v in rec:
                    nums = _parse_numbers(rec[v])
                    out[v] = nums if v in ("kk", "intar_threshold") else nums[0]
                else:
                    out[v] = None
            table[f"{campaign}/{probe}"] = out
        switch_results[ver] = table

    type3 = {}
    for name, rec in raw["type3_v35"].items():
        if rec["status"] == "OK":
            type3[name] = {
                "status": "OK",
                "auto_reject": rec["auto_reject"],
                "eIndex": [int(t) for t in rec["eIndex"].split()]
                if rec["eIndex"] not in ("", "__UNDEFINED__")
                else [],
                "eIndex_defined": rec["eIndex"] != "__UNDEFINED__",
            }
        else:
            type3[name] = {"status": "ERROR", "message": rec["message"]}

    fixture = {
        "blocks": blocks,
        "campaigns": CAMPAIGNS,
        "probes": PROBES,
        "switch": switch_results,
        "varargin_cases": VARARGIN_CASES,
        "varargin": raw["varargin_v35"],
        "habit_cases": HABIT_CASES,
        "habit": raw["habit_v35"],
        "type3_cases": TYPE3_CASES,
        "type3": type3,
    }
    FIXTURE.write_text(json.dumps(fixture, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    scrub_output(FIXTURE)  # path prefixes -> <repo>, <tmp>, ~
    n_ok = {
        v: sum(1 for r in switch_results[v].values() if r["status"] == "OK") for v in switch_results
    }
    n_def = {
        v: sum(1 for r in switch_results[v].values() if r["num_bins"] is not None)
        for v in switch_results
    }
    print(
        f"wrote {FIXTURE.name}: switch cases {len(CAMPAIGNS) * len(PROBES)} per release, "
        f"status OK {n_ok}, num_bins defined {n_def}; "
        f"varargin {len(raw['varargin_v35'])}, habit {len(raw['habit_v35'])}, type3 {len(type3)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

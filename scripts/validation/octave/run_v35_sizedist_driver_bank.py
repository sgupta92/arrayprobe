# SPDX-License-Identifier: BSD-3-Clause
"""Octave oracle for the DRIVER pieces of v3.5's ``sizeDist.m``.

The tables bank (``run_v35_sizedist_tables_bank.py``) already covers the bin
tables, the ``varargin``/``iaThreshType==3`` block and ``iNewHabit``
detection. This bank covers what the driver pieces add on top of that:

1. **The two D3-preserving shattering blocks** -- ``iaThreshType == 1``
   (``:1185-1220``) and ``== 2`` (``:1308-1353``) -- sliced with their
   file-I/O or table-setup sub-steps excluded, so the free variables are
   plain arrays (``iaThresh``/``intar_threshold_i``, ``int_arr``,
   ``int_arr2``, ``int_arr3``, ``particle_diameter_minR``) exactly as
   ``arrayprobe_uiops.sizedist.apply_shattering`` receives them once its own
   (untested-here) I/O step has run.
2. **The multi-day particle-time fix** (``:783-798``,
   ``fix_multiday_particle_times``).
3. **The one-second block-resolution logic** (``:800-887``,
   ``resolve_particle_blocks``).
4. **The overload dead-time cap** (``:1113-1125``, ``overload_dead_time``).
5. **The ``area_ratio`` clip** (``:1160-1162``, ``clip_area_ratio``).

Each block is sliced out of the vendored v3.5 file by a textual anchor,
never a line number, and ``eval``-ed under Octave with its free variables
bound per case -- the same technique ``run_v35_sizedist_tables_bank.py``
uses. Nothing is written into ``UIOPS-v3.5/``.

Run:  .venv/Scripts/python.exe octave_oracle/run_v35_sizedist_driver_bank.py
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
#: Byte-identical across all three trees (V0's 18-file reuse list); the
#: block-resolution slice calls it, so it must be on Octave's path.
V35_HHMMSS2INSEC = _upstream.source("uiops35") / "hhmmss2insec.m"
FIXTURE = Path(__file__).resolve().parents[3] / "tests" / "data" / "v35_sizedist_driver_oracle.json"


def _read_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8", errors="replace").splitlines()


def _slice_between(
    lines: list[str], start_pred, end_pred, *, label: str, start_offset: int = 0
) -> dict:
    """Slice from the first line satisfying ``start_pred`` (inclusive, unless
    ``start_offset`` skips lines after it) through the first line at or after
    it satisfying ``end_pred`` (inclusive)."""
    start = next((i for i, ln in enumerate(lines) if start_pred(ln)), None)
    if start is None:
        raise RuntimeError(f"{label}: start anchor not found")
    search_from = start + start_offset
    end = next((i for i in range(search_from, len(lines)) if end_pred(lines[i])), None)
    if end is None:
        raise RuntimeError(f"{label}: end anchor not found")
    text = "\n".join(lines[search_from : end + 1]) + "\n"
    return {"start_line": search_from + 1, "end_line": end + 1, "text": text}


def extract_type1_block(path: Path) -> dict:
    """``:1185-1220`` -- the flagging if/else through the reacceptance
    ``end``, starting AFTER the netCDF read that binds ``iaThresh`` (that
    read is plain I/O, tested by :class:`TestApplyShatteringType1FileIO`
    directly against ``arrayprobe.ncio`` instead). Free variables: `int_arr`,
    `int_arr3`, `iaThresh`, `particle_diameter_minR`, `reaccptShatrs`,
    `reaccptD`, `reaccptMaxIA`."""
    lines = _read_lines(path)
    return _extract_through_next_end(
        lines,
        start_pred=lambda ln: ln.strip()
        == "if ((length(int_arr) == 1) && (int_arr(1) <= iaThresh(1)))",
        tail_literal="auto_reject(eIndex) = 'R';",
        label="type1 block",
    )


def _extract_through_next_end(
    lines: list[str], *, start_pred, tail_literal: str, label: str
) -> dict:
    head = next((i for i, ln in enumerate(lines) if start_pred(ln)), None)
    if head is None:
        raise RuntimeError(f"{label}: start anchor not found")
    tail = next(
        (i for i in range(head + 1, len(lines)) if lines[i].strip() == tail_literal), None
    )
    if tail is None:
        raise RuntimeError(f"{label}: tail literal {tail_literal!r} not found")
    if lines[tail + 1].strip() != "end":
        raise RuntimeError(f"{label}: expected 'end' immediately after {tail_literal!r}")
    text = "\n".join(lines[head : tail + 2]) + "\n"
    return {"start_line": head + 1, "end_line": tail + 2, "text": text}


def extract_type2_block(path: Path) -> dict:
    """``:1309-1353`` -- the BODY of ``if iaThreshType == 2 &&
    applyIntArrThresh`` (that outer ``if`` line itself is not included, the
    same technique the tables bank's own ``extract_type3_block`` uses, since the gate is
    always true for this bank's cases) through the reacceptance ``end``.
    Free variables: `int_arr`, `int_arr2`, `int_arr3`, `intar_threshold`,
    `i`, `particle_diameter_minR`, `reaccptShatrs`, `reaccptD`,
    `reaccptMaxIA`."""
    lines = _read_lines(path)
    anchor = "if iaThreshType == 2 && applyIntArrThresh"
    head = next((i for i, ln in enumerate(lines) if ln.strip() == anchor), None)
    if head is None:
        raise RuntimeError("type2 block: start anchor not found")
    return _extract_through_next_end(
        lines[head + 1 :],
        start_pred=lambda ln: True,  # first line of the body
        tail_literal="auto_reject(eIndex) = 'R';",
        label="type2 block",
    ) | {"start_line": head + 2}


def _slice_by_depth(lines: list[str], start_pred, *, label: str) -> dict:
    """Slice from the first line satisfying ``start_pred`` through the
    matching ``end`` of that statement, tracking nesting depth (``if``/``for``
    open, bare ``end`` closes; ``elseif``/``else`` do not change depth) --
    robust to a block containing more than one bare ``end`` before its own
    close, unlike a first-``end``-wins search."""
    start = next((i for i, ln in enumerate(lines) if start_pred(ln)), None)
    if start is None:
        raise RuntimeError(f"{label}: start anchor not found")
    depth = 0
    for i in range(start, len(lines)):
        stripped = lines[i].strip()
        if stripped.startswith(("if ", "if(", "for ", "while ", "switch ")):
            depth += 1
        elif stripped == "end":
            depth -= 1
            if depth == 0:
                text = "\n".join(lines[start : i + 1]) + "\n"
                return {"start_line": start + 1, "end_line": i + 1, "text": text}
    raise RuntimeError(f"{label}: never returned to depth 0")


def extract_multiday_block(path: Path) -> dict:
    """``:783-798`` -- the multi-day/corrupt particle-time fix. Free
    variable: `image_time_hhmmssall`."""
    lines = _read_lines(path)
    return _slice_by_depth(
        lines,
        lambda ln: ln.strip() == "if numel(find(diff(image_time_hhmmssall)<0))==1",
        label="multiday block",
    )


def extract_carryover_block(path: Path) -> dict:
    """``:809-811`` -- ``apply_flight_day_carryover``'s own block: *"Fix
    particle times if they do not span multiple days but the flight file
    does"*. Free variables: `timehhmmss`, `image_time_hhmmssall`."""
    lines = _read_lines(path)
    return _slice_by_depth(
        lines,
        lambda ln: ln.strip()
        == "if (numel(find(timehhmmss>240000))>0) && (numel(find(image_time_hhmmssall>240000))==0)",
        label="carryover block",
    )


def extract_blockres_block(path: Path) -> dict:
    """``:800-887`` -- one-second block resolution, from the block-start
    predicate through ``count_all(count_all<0)=1;``. Free variables:
    `image_time_hhmmssall`, `timehhmmss`, `NumofPart`."""
    lines = _read_lines(path)
    start = next(
        (i for i, ln in enumerate(lines) if "startindex=[true;(diff(hhmmss2insec" in ln), None
    )
    if start is None:
        raise RuntimeError("blockres block: start anchor not found")
    end = next(
        (i for i in range(start, len(lines)) if lines[i].strip() == "count_all(count_all<0)=1;"),
        None,
    )
    if end is None:
        raise RuntimeError("blockres block: end anchor not found")
    text = "\n".join(lines[start : end + 1]) + "\n"
    return {"start_line": start + 1, "end_line": end + 1, "text": text}


def extract_deadtime_block(path: Path) -> dict:
    """``:1115-1125`` -- the overload dead-time cap. Free variables:
    `int_arr`, `DMT_DOF_SPEC_OVERLOAD`, `probetype`, `i`."""
    lines = _read_lines(path)
    start = next(
        (
            i
            for i, ln in enumerate(lines)
            if ln.strip() == "time_interval72(i) = sum(int_arr(DMT_DOF_SPEC_OVERLOAD~=0));"
        ),
        None,
    )
    if start is None:
        raise RuntimeError("deadtime block: start anchor not found")
    set_to_1 = next(
        (i for i in range(start, len(lines)) if lines[i].strip() == "time_interval72(i) = 1;"),
        None,
    )
    if set_to_1 is None:
        raise RuntimeError("deadtime block: 'time_interval72(i) = 1;' not found")
    ends = [i for i in range(set_to_1, len(lines)) if lines[i].strip() == "end"]
    if len(ends) < 2:
        raise RuntimeError("deadtime block: expected two 'end' lines after the cap assignment")
    end = ends[1]
    text = "\n".join(lines[start : end + 1]) + "\n"
    return {"start_line": start + 1, "end_line": end + 1, "text": text}


def extract_arearatio_block(path: Path) -> dict:
    """``:1160-1162`` -- the area_ratio clip plus the (unchanged, literal
    ``.2``) reject test right after it. Free variables: `area`,
    `particle_diameter_minR`, `auto_reject`."""
    lines = _read_lines(path)
    start = next(
        (
            i
            for i, ln in enumerate(lines)
            if ln.strip() == "area_ratio = area./(pi/4.*particle_diameter_minR.^2);"
        ),
        None,
    )
    if start is None:
        raise RuntimeError("area_ratio block: start anchor not found")
    end = next(
        (
            i
            for i in range(start, len(lines))
            if lines[i].strip() == "auto_reject(area_ratio < .2) = 'z';"
        ),
        None,
    )
    if end is None:
        raise RuntimeError("area_ratio block: end anchor not found")
    text = "\n".join(lines[start : end + 1]) + "\n"
    return {"start_line": start + 1, "end_line": end + 1, "text": text}


# ---------------------------------------------------------------------------
# Case grids
# ---------------------------------------------------------------------------

#: Shared two-event shattering fixture -- the same shape the tables bank's own
#: ``reaccept_two_events_spanned`` case uses, so type-1/2's first-event-only
#: reacceptance can be compared directly against the tables bank's type-3 result on
#: identical inputs (the "two conventions differ" claim).
TWO_EVENT = {
    "int_arr": [5e-6, 5e-6, 1e-7, 5e-6, 5e-6, 1e-7, 5e-6],
    "int_arr3": [5e-6, 1e-7, 5e-6, 5e-6, 1e-7, 5e-6, 5e-6],
    "diam": [0.2, 0.2, 0.6, 0.2, 0.2, 0.8, 0.2],
    "thresh": 1e-6,
}

TYPE12_CASES = {
    "two_events_only_first_reaccepted": {**TWO_EVENT, "reaccpt": 1},
    "single_particle_below": {
        "int_arr": [1e-7], "int_arr3": [5e-6], "diam": [0.2], "thresh": 1e-6, "reaccpt": 0,
    },
    "single_particle_above": {
        "int_arr": [5e-6], "int_arr3": [5e-6], "diam": [0.2], "thresh": 1e-6, "reaccpt": 0,
    },
    "no_events": {
        "int_arr": [5e-6, 5e-6, 5e-6], "int_arr3": [5e-6, 5e-6, 5e-6],
        "diam": [0.9, 0.9, 0.9], "thresh": 1e-6, "reaccpt": 1,
    },
    "rEnd_before_rBegin_nothing_reaccepted": {
        # event starts at index 1 (block boundary): rBegin can never fire there
        "int_arr": [1e-7, 1e-7, 5e-6], "int_arr3": [1e-7, 5e-6, 5e-6],
        "diam": [0.9, 0.9, 0.2], "thresh": 1e-6, "reaccpt": 1,
    },
    "first_particle_flagged": {
        "int_arr": [1e-7, 5e-6, 5e-6], "int_arr3": [5e-6, 5e-6, 5e-6],
        "diam": [0.2, 0.2, 0.2], "thresh": 1e-6, "reaccpt": 0,
    },
}
#: reaccptD/reaccptMaxIA held fixed across the grid; only the shattering
#: shape varies case to case.
TYPE12_REACCPTD = 0.5
TYPE12_REACCPTMAXIA = 1e-6

MULTIDAY_CASES = {
    "no_decrease": [100000, 100001, 100002],
    "one_decrease_midnight": [235959, 235959, 10, 10, 20],
    "two_decreases_crossover_detected": [
        235959, 235959, 10,  # real crossover: 235959 -> 10
        20, 5,  # corrupt: briefly decreases again without crossing (20 -> 5)
    ],
    "two_decreases_no_crossover": [
        100010, 100005,  # corrupt decrease, not a real crossover (not > 230000)
        100020, 100015,  # another corrupt decrease
    ],
}

CARRYOVER_CASES = {
    "flight_crosses_midnight_particle_time_does_not": {
        "timehhmmss": [235959, 240001, 240010],
        "image_time_hhmmssall": [235958, 235959, 10, 20],
    },
    "neither_crosses": {
        "timehhmmss": [100000, 100001],
        "image_time_hhmmssall": [50000, 50001],
    },
    "both_already_cross": {
        "timehhmmss": [235959, 240010],
        "image_time_hhmmssall": [235959, 240005],
    },
}

BLOCKRES_CASES = {
    "monotonic_three_seconds": {
        "image_time_hhmmssall": [
            100000, 100000, 100000, 100001, 100001, 100001, 100002, 100002, 100002,
        ],
        "timehhmmss": [100000, 100001, 100002],
        "num_of_part": 9,
    },
    "midnight_rollover_then_two_more_seconds": {
        "image_time_hhmmssall": [235959, 235959, 240010, 240010, 240020],
        "timehhmmss": [235959, 240010, 240020],
        "num_of_part": 5,
    },
    "out_of_order_leading_block_dropped": {
        # a corrupt particle time places one particle from a LATER second at
        # the very start of the file, ahead of an earlier second's block.
        "image_time_hhmmssall": [100002, 100000, 100000, 100001, 100001],
        "timehhmmss": [100000, 100001, 100002],
        "num_of_part": 5,
    },
}

DEADTIME_CASES = {
    "under_warn_threshold": {"int_arr": [0.1, 0.2, 0.1], "overload": [0, 1, 1], "probetype": 2},
    "between_warn_and_cap": {"int_arr": [0.5, 0.4], "overload": [1, 1], "probetype": 2},
    "over_cap": {"int_arr": [0.9, 0.9], "overload": [1, 1], "probetype": 2},
    "not_probetype_2": {"int_arr": [0.9, 0.9], "overload": [1, 1], "probetype": 1},
}

AREARATIO_CASES = {
    "within_range": {"area": [1.0], "diam": [1.1283791671]},  # pi/4 * d^2 ~= area
    "exceeds_one_before_clip": {"area": [10.0], "diam": [1.0]},
    "below_reject_threshold": {"area": [0.01], "diam": [1.0]},
}


_HARNESS = r"""
more off;
scratch = '{scratch}';
outfile = '{outfile}';
addpath(scratch);
out = struct();

% ---- type1/type2 shattering blocks -------------------------------------
tc = jsondecode(fileread(fullfile(scratch, 'type12_cases.json')));
names = fieldnames(tc);

blk1 = fileread(fullfile(scratch, 'type1.m'));
recs1 = struct();
for k = 1:numel(names)
    clear -x blk1 tc names recs1 k out scratch outfile blk2 recs2;
    c = tc.(names{{k}});
    int_arr = c.int_arr(:);
    int_arr3 = c.int_arr3(:);
    particle_diameter_minR = c.diam(:);
    iaThresh = repmat(c.thresh, size(int_arr));
    reaccptShatrs = c.reaccpt;
    reaccptD = {reaccptd};
    reaccptMaxIA = {reaccptmaxia};
    auto_reject = repmat('A', numel(int_arr), 1);
    rec = struct('status', 'OK', 'message', '');
    try
        eval(blk1);
        rec.auto_reject = reshape(auto_reject, 1, []);
    catch err
        rec.status = 'ERROR';
        rec.message = err.message;
    end
    recs1.(names{{k}}) = rec;
end
out.type1 = recs1;

blk2 = fileread(fullfile(scratch, 'type2.m'));
recs2 = struct();
for k = 1:numel(names)
    clear -x blk1 blk2 tc names recs1 recs2 k out scratch outfile;
    c = tc.(names{{k}});
    int_arr = c.int_arr(:);
    int_arr3 = c.int_arr3(:);
    particle_diameter_minR = c.diam(:);
    intar_threshold = [NaN; c.thresh; NaN];   % only intar_threshold(i) may be read
    i = 2;
    int_arr2 = [];
    reaccptShatrs = c.reaccpt;
    applyIntArrThresh = 1;
    reaccptD = {reaccptd};
    reaccptMaxIA = {reaccptmaxia};
    auto_reject = repmat('A', numel(int_arr), 1);
    rec = struct('status', 'OK', 'message', '');
    try
        eval(blk2);
        rec.auto_reject = reshape(auto_reject, 1, []);
    catch err
        rec.status = 'ERROR';
        rec.message = err.message;
    end
    recs2.(names{{k}}) = rec;
end
out.type2 = recs2;

% ---- multi-day particle-time fix ----------------------------------------
blk = fileread(fullfile(scratch, 'multiday.m'));
mc = jsondecode(fileread(fullfile(scratch, 'multiday_cases.json')));
names = fieldnames(mc);
recs = struct();
for k = 1:numel(names)
    clear -x blk mc names recs k out scratch outfile;
    image_time_hhmmssall = mc.(names{{k}})(:);
    rec = struct('status', 'OK', 'message', '');
    try
        eval(blk);
        rec.image_time_hhmmssall = reshape(image_time_hhmmssall, 1, []);
    catch err
        rec.status = 'ERROR';
        rec.message = err.message;
    end
    recs.(names{{k}}) = rec;
end
out.multiday = recs;

% ---- flight-day carryover -------------------------------------------------
blk = fileread(fullfile(scratch, 'carryover.m'));
cc = jsondecode(fileread(fullfile(scratch, 'carryover_cases.json')));
names = fieldnames(cc);
recs = struct();
for k = 1:numel(names)
    clear -x blk cc names recs k out scratch outfile;
    timehhmmss = cc.(names{{k}}).timehhmmss(:);
    image_time_hhmmssall = cc.(names{{k}}).image_time_hhmmssall(:);
    rec = struct('status', 'OK', 'message', '');
    try
        eval(blk);
        rec.image_time_hhmmssall = reshape(image_time_hhmmssall, 1, []);
    catch err
        rec.status = 'ERROR';
        rec.message = err.message;
    end
    recs.(names{{k}}) = rec;
end
out.carryover = recs;

% ---- block-resolution logic ---------------------------------------------
blk = fileread(fullfile(scratch, 'blockres.m'));
bc = jsondecode(fileread(fullfile(scratch, 'blockres_cases.json')));
names = fieldnames(bc);
recs = struct();
for k = 1:numel(names)
    clear -x blk bc names recs k out scratch outfile;
    c = bc.(names{{k}});
    image_time_hhmmssall = c.image_time_hhmmssall(:);
    timehhmmss = c.timehhmmss(:);
    NumofPart = c.num_of_part;
    rec = struct('status', 'OK', 'message', '');
    try
        eval(blk);
        rec.starttime = reshape(starttime, 1, []);
        rec.start_all = reshape(start_all, 1, []);
        rec.count_all = reshape(count_all, 1, []);
    catch err
        rec.status = 'ERROR';
        rec.message = err.message;
    end
    recs.(names{{k}}) = rec;
end
out.blockres = recs;

% ---- overload dead-time cap ----------------------------------------------
blk = fileread(fullfile(scratch, 'deadtime.m'));
dc = jsondecode(fileread(fullfile(scratch, 'deadtime_cases.json')));
names = fieldnames(dc);
recs = struct();
for k = 1:numel(names)
    clear -x blk dc names recs k out scratch outfile;
    c = dc.(names{{k}});
    int_arr = c.int_arr(:);
    DMT_DOF_SPEC_OVERLOAD = c.overload(:);
    probetype = c.probetype;
    i = 1;
    time_interval72 = zeros(1,1);
    rec = struct('status', 'OK', 'message', '');
    try
        eval(blk);
        rec.time_interval72 = time_interval72(1);
    catch err
        rec.status = 'ERROR';
        rec.message = err.message;
    end
    recs.(names{{k}}) = rec;
end
out.deadtime = recs;

% ---- area_ratio clip ------------------------------------------------------
blk = fileread(fullfile(scratch, 'arearatio.m'));
ac = jsondecode(fileread(fullfile(scratch, 'arearatio_cases.json')));
names = fieldnames(ac);
recs = struct();
for k = 1:numel(names)
    clear -x blk ac names recs k out scratch outfile;
    c = ac.(names{{k}});
    area = c.area(:);
    particle_diameter_minR = c.diam(:);
    auto_reject = repmat('A', numel(area), 1);
    rec = struct('status', 'OK', 'message', '');
    try
        eval(blk);
        rec.area_ratio = reshape(area_ratio, 1, []);
        rec.auto_reject = reshape(auto_reject, 1, []);
    catch err
        rec.status = 'ERROR';
        rec.message = err.message;
    end
    recs.(names{{k}}) = rec;
end
out.arearatio = recs;

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

    blocks = {
        "type1": extract_type1_block(V35_SIZEDIST),
        "type2": extract_type2_block(V35_SIZEDIST),
        "multiday": extract_multiday_block(V35_SIZEDIST),
        "carryover": extract_carryover_block(V35_SIZEDIST),
        "blockres": extract_blockres_block(V35_SIZEDIST),
        "deadtime": extract_deadtime_block(V35_SIZEDIST),
        "arearatio": extract_arearatio_block(V35_SIZEDIST),
    }

    with tempfile.TemporaryDirectory() as tmp:
        scratch = Path(tmp)
        for name, blk in blocks.items():
            (scratch / f"{name}.m").write_text(blk["text"], encoding="utf-8")
        (scratch / "hhmmss2insec.m").write_text(
            V35_HHMMSS2INSEC.read_text(encoding="utf-8"), encoding="utf-8"
        )
        (scratch / "type12_cases.json").write_text(json.dumps(TYPE12_CASES), encoding="utf-8")
        (scratch / "multiday_cases.json").write_text(json.dumps(MULTIDAY_CASES), encoding="utf-8")
        (scratch / "carryover_cases.json").write_text(json.dumps(CARRYOVER_CASES), encoding="utf-8")
        (scratch / "blockres_cases.json").write_text(json.dumps(BLOCKRES_CASES), encoding="utf-8")
        (scratch / "deadtime_cases.json").write_text(json.dumps(DEADTIME_CASES), encoding="utf-8")
        (scratch / "arearatio_cases.json").write_text(json.dumps(AREARATIO_CASES), encoding="utf-8")
        outfile = scratch / "out.json"
        script = scratch / "bank.m"
        script.write_text(
            _HARNESS.format(
                scratch=scratch.as_posix(),
                outfile=outfile.as_posix(),
                reaccptd=TYPE12_REACCPTD,
                reaccptmaxia=TYPE12_REACCPTMAXIA,
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

    fixture = {
        "blocks": blocks,
        "type12_cases": TYPE12_CASES,
        "type12_reaccptD": TYPE12_REACCPTD,
        "type12_reaccptMaxIA": TYPE12_REACCPTMAXIA,
        "type1": raw["type1"],
        "type2": raw["type2"],
        "multiday_cases": MULTIDAY_CASES,
        "multiday": raw["multiday"],
        "carryover_cases": CARRYOVER_CASES,
        "carryover": raw["carryover"],
        "blockres_cases": BLOCKRES_CASES,
        "blockres": raw["blockres"],
        "deadtime_cases": DEADTIME_CASES,
        "deadtime": raw["deadtime"],
        "arearatio_cases": AREARATIO_CASES,
        "arearatio": raw["arearatio"],
    }
    FIXTURE.write_text(json.dumps(fixture, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    scrub_output(FIXTURE)  # path prefixes -> <repo>, <tmp>, ~
    groups = ("type1", "type2", "multiday", "carryover", "blockres", "deadtime", "arearatio")
    n_ok = sum(1 for group in groups for r in raw[group].values() if r["status"] == "OK")
    n_total = sum(len(raw[group]) for group in groups)
    print(f"wrote {FIXTURE.name}: {n_ok}/{n_total} cases OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

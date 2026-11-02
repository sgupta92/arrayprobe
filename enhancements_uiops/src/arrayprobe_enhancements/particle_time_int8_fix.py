# SPDX-License-Identifier: BSD-3-Clause
"""A15 -- recover ``particle_time`` where an ``int8`` seed saturates it to 127.

**What it corrects.**  ``imgProc_sm.m:886`` writes the proc file's ``particle_time`` as::

    netcdf.putVar(f, varid5, wstart, w-wstart+1,
                  part_hour(:)*10000 + part_min(:)*100 + part_sec(:));

For probetype 2 those three accumulators are literal ``0``; for probetype 1 they come from
``bin2dec``, which returns ``double`` whatever its input.  **For probetype 0 (2DC/2DP) and
probetype 3 (Fast2DC) they do not.**  The first particle of every image record seeds them
straight from the record header (``:606-608`` then ``:620-622``): ``:606`` copies the
header hour read by ``netcdf.getVar`` at ``:475``, in the file's own declared type, and
``:620`` stores it into ``part_hour``, whose class MATLAB's growth-by-indexing then inherits;
and ``read_binary_PMS.m:53-55`` declares ``hour``/``minute``/``second`` as ``'byte'``
(int8).  MATLAB integer arithmetic **saturates**, so ``part_hour*10000`` hits 127 for any
hour above 0, ``part_min*100`` hits it for any minute above 1, and the sum saturates again:
``particle_time`` collapses to a near-constant 127.

The same routine gets it right eighty lines earlier.  ``:726`` and ``:787`` both write
``double(handles.hour)*10000 + double(handles.minute)*100 + double(handles.second)`` --
that is why the proc file's ``Time`` variable carries the correct HHMMSS while
``particle_time``, documented in its own attribute as HHMMSS, does not.  The seed and the
cast the fix needs are both already in the file.

The port reproduces the saturation deliberately, in
``arrayprobe.imgproc._particle_time_write``; this module is the opt-in correction, outside
the port, per the fidelity doctrine.

**How it is proved, and why the proof exists at all.**  There is normally no MATLAB output
anywhere carrying a corrected ``particle_time`` to check against -- the value is destroyed
in the file it is written to.  But A15's own text names the corner of the value space where
the original is *right*: hour 0, and ``minute*100 + second`` under 127.  So
``scripts/a15_particle_time_bank.py`` builds **two raw 2DC files that differ only in the
record header's hour/minute/second** and runs the real unmodified ``read_binary_PMS.m`` +
``imgProc_sm.m`` over both under Octave:

===================  ==========================  =============================
record header        MATLAB's ``particle_time``  the true value
===================  ==========================  =============================
``00:00:58``         ``[58, 101]``               ``[58, 101]``  -- it agrees
``06:06:58``         ``[127, 127]``              ``[60658, 60701]``
===================  ==========================  =============================

Measured, not derived: the two goldens differ in exactly two variables, ``Time``
(+60600, correct in both) and ``particle_time``.  Every other column -- including
``Time_in_seconds``, ``particle_millisec`` and ``particle_microsec``, which the recovery
below consumes -- is bit-identical.  So :func:`corrected_particle_time` is checked against
**MATLAB's own arithmetic** in the corner where MATLAB can be trusted, and then applied in
the corner where it cannot.

**What it changes.**

* :func:`matlab_particle_time` is the faithful write, kept here so the module can state its
  own "before" side; ``test_particle_time_int8_fix.py`` asserts it equals
  ``arrayprobe.imgproc._particle_time_write`` element for element, so the equality is
  measured rather than argued.
* :func:`corrected_particle_time` is A15's suggested edit -- the same expression in double.
* :func:`recover_from_proc` recovers the correction from an **already-written** proc file,
  by replaying ``:604-652``'s own cascade in double from columns the same MATLAB wrote
  correctly (``parent_rec_num``, ``Time``, ``Time_in_seconds``, ``particle_millisec``,
  ``particle_microsec``).  The replay is self-checking: it recomputes ``particle_millisec``
  and ``particle_microsec`` too, and :func:`verify_replay` compares them against the file's
  own.  On the tracked Octave golden they agree to the last bit
  (``999.99999999982946974``), which is what makes the recovered hour/minute/second
  trustworthy -- the cascade is replayed, not re-derived.
* :func:`corrected_proc_file` writes a corrected copy; the source is never modified.

**What this module does NOT claim.**

* **It has never been run on a real 2DC, 2DP or Fast2DC campaign file, because this project
  holds none.**  ORACLES is a 2D-S/HVPS campaign -- probetype 2, where ``part_hour`` is a
  literal ``0`` and none of this applies.  Every measurement quoted above is from a
  hand-built synthetic raw file run through unmodified MATLAB source under Octave.  There is
  no real-flight A/B, no recovered-particle count, and no claim that any archived product
  changes.  That is a data gap, not an argument: the correction is complete and the
  measurement is owed the moment 2DC/2DP/Fast2DC data arrives.
* **The oracle covers 2DC (probetype 0) only.**  The port's own tracked Fast2DC golden
  (``tests/data/s7e_f2dc_octave_golden.nc``) shows the same collapse to
  ``[127, 127]``, so the *faithful* side is measured for probetype 3 as well; the
  *corrected* side is checked against real MATLAB output for probetype 0 alone.  The
  hour-0 fixture pair has not been rebuilt in Fast2DC's raw format.
* **The recovery needs the probetype told to it.**  A proc file does not record which
  probetype wrote it, and the two branches differ: ``:628-632`` computes ``frac_time`` from
  the *elapsed* time for probetype 3 and from ``part_time`` itself for probetype 0, while
  ``:636`` adds ``floor(part_time)`` to the seconds in **both** cases even though
  probetype 3's ``part_time`` is an absolute since-power-on clock.  Guessing from the data
  would be a coin flip on a small file, so the argument is required.
* **It does not fix the second-order oddity it has to reproduce.**  For probetype 3 the
  seconds accumulate by the absolute clock (``:636``, above), which is almost certainly not
  what was intended.  Correcting *that* would change ``particle_millisec`` and
  ``particle_microsec`` as well and is a separate decision with no oracle behind it; this
  module reproduces ``:636`` as written and corrects only the ``int8`` write.
* **It does not touch ``Time``.**  ``Time`` is already correct (``:787``); nothing here
  rewrites it, and a caller comparing the two variables after the correction should expect
  them to agree on the first particle of each record and to diverge afterwards, which is
  the point.
* **It does not claim more about v3.5 than one synthetic 2DC pair shows.**  The pair was
  rebuilt against the unmodified v3.5 tree on 2026-09-15 and **A15 survives**:
  ``a15_2dc_hour6_v35_octave_golden.nc`` writes ``[127, 127]`` where the true value is
  ``[60658, 60702]``, and its hour-0 twin writes ``[58, 102]``, which the correction
  reproduces exactly (``test_particle_time_int8_fix.py::AgainstTheV35OctaveOraclePair``).
  The write site is ``imgProc_sm.m:1336``, the same expression as v3.1.4's ``:886``, over
  the same ``int8`` header seed (``:697``, ``:887-889``; ``read_binary_PMS.m:53-55`` is
  byte-identical).  The v3.5 values differ from v3.1.4's ``[58, 101]`` for a reason that is
  not A15: v3.5 makes the 2DC diode 0.03 mm (``:141``, the upstream inconsistent 2DC diode size), so the same TAS-clock
  count is 3.96 s rather than 3.3 s.  The first attempt (2026-09-14) stopped at
  ``CGAL_minR: function called with too many inputs`` (``:1213``) because the bank put the
  v3.1.4 one-argument shim on the path; the bank now forwards to the real v3.5 MEX
  (``CGAL_minR_v35.mex``), so ``image_diam_minR`` in the v3.5 goldens is MEX-derived.
  ORACLES's own 2D-S data is probetype 2 on either engine, where this module does not
  apply -- measured on the tracked ``tests/data/demo_flight_v35_proc.nc``,
  where :func:`verify_replay` refuses probetype 2 by its own guard
  (``test_particle_time_int8_fix.py::OnTheV35DemoProc``).
"""

from __future__ import annotations

from pathlib import Path

import netCDF4
import numpy as np

__all__ = [
    "INT8_MIN",
    "INT8_MAX",
    "AFFECTED_PROBETYPES",
    "WRITE_SITE",
    "SEED_SITE",
    "CORRECT_SITE",
    "saturate_int8",
    "matlab_particle_time",
    "corrected_particle_time",
    "is_representable",
    "saturation_report",
    "hhmmss_parts",
    "replay_record",
    "recover_from_proc",
    "verify_replay",
    "corrected_proc_file",
]

#: MATLAB ``int8``'s saturating bounds.
INT8_MIN = -128.0
INT8_MAX = 127.0

#: The probetypes whose accumulators inherit ``int8`` from the record header.
#: 0 is 2DC/2DP, 3 is Fast2DC -- the shared ``firstpart`` block at ``:604-625``
#: sits inside the OUTER ``if probetype==0 || probetype==3`` guard.
AFFECTED_PROBETYPES = (0, 3)

#: ``part_hour(:)*10000 + part_min(:)*100 + part_sec(:)`` -- the saturating write.
WRITE_SITE = "imgProc_sm.m:886"

#: ``part_hour(kk) = start_hour`` on an undefined ``part_hour``, seeded from
#: ``netcdf.getVar(..., 'hour', ...)`` -- ``read_binary_PMS.m:53-55`` says ``'byte'``.
SEED_SITE = "imgProc_sm.m:606-608,620-622"

#: The same expression, done correctly, eighty lines earlier -- the file's ``Time``.
CORRECT_SITE = "imgProc_sm.m:787"


def saturate_int8(x):
    """MATLAB ``int8`` semantics: round to nearest, then clamp -- never wrap."""
    return np.clip(np.rint(np.asarray(x, dtype=np.float64)), INT8_MIN, INT8_MAX)


def matlab_particle_time(part_hour, part_min, part_sec):
    """``:886`` as it runs for probetype 0 and 3 -- every operation in ``int8``.

    Written independently of the port so the two can be compared: the test asserts this
    equals ``arrayprobe.imgproc._particle_time_write`` element for element, which is what
    makes the "before" side of every A/B here the port's own behaviour rather than a second
    transcription of the same MATLAB.
    """
    h = saturate_int8(part_hour)
    m = saturate_int8(part_min)
    s = saturate_int8(part_sec)
    return saturate_int8(saturate_int8(saturate_int8(h * 10000)
                                       + saturate_int8(m * 100)) + s)


def corrected_particle_time(part_hour, part_min, part_sec):
    """A15's suggested edit: the same expression, in ``double``.

    Identical to what ``:787`` already does for ``Time``, and to what probetypes 1 and 2
    get for free because their accumulators were never integers.
    """
    h = np.asarray(part_hour, dtype=np.float64)
    m = np.asarray(part_min, dtype=np.float64)
    s = np.asarray(part_sec, dtype=np.float64)
    return h * 10000.0 + m * 100.0 + s


def is_representable(part_hour, part_min, part_sec):
    """Where the original happens to be right -- ``matlab == corrected``, elementwise.

    Not a threshold rule: computed by running both sides, because the boundary is the
    result of three saturating operations and is easier to get wrong than to measure.  In
    practice it is hour 0 with ``minute*100 + second <= 127``.
    """
    return (matlab_particle_time(part_hour, part_min, part_sec)
            == corrected_particle_time(part_hour, part_min, part_sec))


def saturation_report(part_hour, part_min, part_sec) -> dict:
    """What ``:886`` did to one set of accumulators.  Changes nothing."""
    faithful = np.atleast_1d(matlab_particle_time(part_hour, part_min, part_sec))
    corrected = np.atleast_1d(corrected_particle_time(part_hour, part_min, part_sec))
    ok = faithful == corrected
    return {
        "n": int(faithful.size),
        "n_wrong": int(np.count_nonzero(~ok)),
        "fraction_wrong": (float(np.count_nonzero(~ok)) / faithful.size
                           if faithful.size else 0.0),
        "n_saturated_at_max": int(np.count_nonzero(faithful == INT8_MAX)),
        "distinct_written_values": int(np.unique(faithful).size),
        "distinct_true_values": int(np.unique(corrected).size),
        "written_range": (float(faithful.min()), float(faithful.max()))
        if faithful.size else (0.0, 0.0),
        "true_range": (float(corrected.min()), float(corrected.max()))
        if corrected.size else (0.0, 0.0),
    }


def hhmmss_parts(hhmmss):
    """Split a correct HHMMSS value (the proc file's ``Time``) into hour, minute, second.

    ``Time`` is written in double at :data:`CORRECT_SITE`, so it is the record header's own
    clock and is the seed :func:`replay_record` starts from.
    """
    v = np.asarray(hhmmss, dtype=np.float64)
    hour = np.floor(v / 10000.0)
    minute = np.floor((v - hour * 10000.0) / 100.0)
    second = v - hour * 10000.0 - minute * 100.0
    return hour, minute, second


def _cascade(hour, minute, second, milli, micro):
    """``:641-652`` -- one conditional subtraction per level, in this exact order.

    Deliberately **not** a modulo.  The source tests each level once, so a jump large
    enough to push seconds past 120 leaves them past 60; reproducing that is the whole
    point of replaying the cascade instead of computing a closed form.
    """
    if micro >= 1000.0:
        milli += 1.0
        micro -= 1000.0
    if milli >= 1000.0:
        second += 1.0
        milli -= 1000.0
    if second >= 60.0:
        minute += 1.0
        second -= 60.0
    if minute >= 60.0:
        hour += 1.0
        minute -= 60.0
    if hour >= 24.0:
        hour -= 24.0
    return hour, minute, second, milli, micro


def replay_record(rec_time_hhmmss, seed_millisec, time_in_seconds, probetype: int):
    """Replay ``:604-652`` in double for the particles of ONE image record.

    ``rec_time_hhmmss`` is the record's own ``Time`` (all particles in a record share it);
    ``seed_millisec`` is the first particle's ``particle_millisec``, which *is* the header's
    ``millisec`` field; ``time_in_seconds`` is the record's ``Time_in_seconds`` column, one
    entry per particle, which is ``part_time`` as ``:587``/``:593`` wrote it.

    Returns ``(hour, minute, second, milli, micro)``, each one array per particle.  The last
    two are recomputed rather than read so :func:`verify_replay` can check the replay against
    the file's own copies of them.
    """
    if probetype not in AFFECTED_PROBETYPES:
        raise ValueError(
            f"probetype {probetype} does not use the {SEED_SITE} seed -- its accumulators "
            "are double already (probetype 1 via bin2dec, probetype 2 via a literal 0), so "
            "particle_time is written correctly and there is nothing to recover."
        )
    pt = np.asarray(time_in_seconds, dtype=np.float64).ravel()
    n = pt.size
    hour = np.empty(n)
    minute = np.empty(n)
    second = np.empty(n)
    milli = np.empty(n)
    micro = np.empty(n)

    h0, m0, s0 = (float(np.ravel(a)[0]) for a in hhmmss_parts(rec_time_hhmmss))
    for k in range(n):
        if k == 0:                                              # :604-625
            h, m, s = h0, m0, s0
            mil = float(seed_millisec)
            mic = 0.0                                           # :617, start_microsec
        else:                                                   # :627-638
            if probetype == 0:                                  # :628-629
                frac_time = (pt[k] - np.floor(pt[k])) * 1000.0
            else:                                               # :630-632, Fast2DC
                time_diff = pt[k] - pt[k - 1]
                frac_time = 1000.0 * (time_diff - np.floor(time_diff))
            mic = micro[k - 1] + (frac_time - np.floor(frac_time)) * 1000.0
            mil = milli[k - 1] + np.floor(frac_time)
            # :636 adds floor(part_time) for BOTH probetypes, even though probetype 3's
            # part_time is an absolute since-power-on clock.  Reproduced as written.
            s = second[k - 1] + np.floor(pt[k])
            m = minute[k - 1]
            h = hour[k - 1]
        h, m, s, mil, mic = _cascade(h, m, s, mil, mic)
        hour[k], minute[k], second[k], milli[k], micro[k] = h, m, s, mil, mic
    return hour, minute, second, milli, micro


def _read_proc(path):
    with netCDF4.Dataset(Path(path)) as ds:
        out = {}
        for name in ("parent_rec_num", "Time", "Time_in_seconds",
                     "particle_millisec", "particle_microsec", "particle_time"):
            if name not in ds.variables:
                raise KeyError(f"{path}: proc file has no {name!r}")
            var = ds.variables[name]
            var.set_auto_mask(False)
            out[name] = np.asarray(var[:], dtype=np.float64).ravel()
    return out


def _record_slices(parent_rec_num):
    """Contiguous runs of equal ``parent_rec_num`` -- one image record each.

    ``firstpart`` is set at ``imgProc_sm.m:499``, inside the record loop, so it resets at
    every record boundary; the port records the same coincidence at ``imgproc.py:1138``.
    """
    rec = np.asarray(parent_rec_num)
    if rec.size == 0:
        return []
    edges = np.flatnonzero(np.diff(rec) != 0) + 1
    starts = np.concatenate([[0], edges])
    stops = np.concatenate([edges, [rec.size]])
    return list(zip(starts.tolist(), stops.tolist(), strict=True))


def recover_from_proc(path, probetype: int) -> dict:
    """Recover the corrected ``particle_time`` from an already-written proc file.

    Returns a dict carrying ``written`` (what the file holds), ``corrected`` (the recovery),
    the replayed ``millisec``/``microsec`` used to check it, and a
    :func:`saturation_report`-shaped summary.  Nothing is written.
    """
    cols = _read_proc(path)
    n = cols["particle_time"].size
    hour = np.empty(n)
    minute = np.empty(n)
    second = np.empty(n)
    milli = np.empty(n)
    micro = np.empty(n)
    for lo, hi in _record_slices(cols["parent_rec_num"]):
        h, m, s, ml, mc = replay_record(
            cols["Time"][lo], cols["particle_millisec"][lo],
            cols["Time_in_seconds"][lo:hi], probetype)
        hour[lo:hi], minute[lo:hi], second[lo:hi] = h, m, s
        milli[lo:hi], micro[lo:hi] = ml, mc

    corrected = corrected_particle_time(hour, minute, second)
    faithful = matlab_particle_time(hour, minute, second)
    report = saturation_report(hour, minute, second)
    report.update({
        "path": str(path),
        "probetype": probetype,
        "n_records": len(_record_slices(cols["parent_rec_num"])),
        "written": cols["particle_time"],
        "faithful": faithful,
        "corrected": corrected,
        "hour": hour, "minute": minute, "second": second,
        "millisec": milli, "microsec": micro,
        "replay_matches_file": bool(
            np.array_equal(milli, cols["particle_millisec"])
            and np.array_equal(micro, cols["particle_microsec"])),
        "faithful_matches_file": bool(np.array_equal(faithful, cols["particle_time"])),
    })
    return report


def verify_replay(path, probetype: int) -> dict:
    """Check the replay against the file's own ``particle_millisec``/``particle_microsec``.

    The two sides come from different places: one is what ``imgProc_sm`` wrote, the other is
    this module replaying ``:627-652`` from ``Time_in_seconds``.  They must agree exactly --
    they are the same cascade -- and if they do not, the recovered hour/minute/second from
    the same cascade cannot be trusted either.  ``max_millisec_error`` and
    ``max_microsec_error`` are reported rather than only a boolean so a near-miss is visible.
    """
    cols = _read_proc(path)
    rep = recover_from_proc(path, probetype)
    d_mil = np.abs(rep["millisec"] - cols["particle_millisec"])
    d_mic = np.abs(rep["microsec"] - cols["particle_microsec"])
    return {
        "path": str(path),
        "probetype": probetype,
        "n": int(cols["particle_time"].size),
        "max_millisec_error": float(d_mil.max()) if d_mil.size else 0.0,
        "max_microsec_error": float(d_mic.max()) if d_mic.size else 0.0,
        "exact": bool(d_mil.size == 0 or (d_mil.max() == 0.0 and d_mic.max() == 0.0)),
        "faithful_matches_file": rep["faithful_matches_file"],
    }


def corrected_proc_file(src, dst, probetype: int, *, require_exact_replay: bool = True):
    """Write a copy of ``src`` to ``dst`` with ``particle_time`` corrected.

    Every other dimension, variable, value and attribute is copied verbatim, and ``src`` is
    never modified.  With ``require_exact_replay`` (the default) the copy is refused unless
    the replay reproduces the file's own ``particle_millisec``/``particle_microsec``
    exactly -- there is no reason to trust a recovered hour/minute/second from a cascade
    that cannot reproduce the two columns the same cascade wrote.

    ``particle_time`` is ``int`` in the proc-file schema, and the corrected HHMMSS values
    are integers, so nothing is rounded away; the returned report carries the arrays.
    """
    src, dst = Path(src), Path(dst)
    check = verify_replay(src, probetype)
    if require_exact_replay and not check["exact"]:
        raise ValueError(
            f"{src}: replaying imgProc_sm.m:627-652 does not reproduce the file's own "
            f"particle_millisec/particle_microsec (max error {check['max_millisec_error']} "
            f"ms / {check['max_microsec_error']} us). Refusing to rewrite particle_time "
            "from a cascade that disagrees with the file. Pass require_exact_replay=False "
            "only to inspect the result."
        )
    rep = recover_from_proc(src, probetype)
    # Byte copy, then overwrite ``particle_time`` in place. The variable-by-variable rebuild
    # this replaces wrote a (time, 2) ``position`` in one call at netCDF-C's default (1, 2)
    # chunking, ~7 KB of memory per chunk
    # (measured).
    import shutil
    shutil.copyfile(src, dst)
    with netCDF4.Dataset(dst, "r+") as ds_out:
        out = ds_out.variables["particle_time"]
        out.set_auto_mask(False)
        out[:] = rep["corrected"].astype(out.dtype)
    rep["output"] = str(dst)
    rep["replay_check"] = check
    return rep

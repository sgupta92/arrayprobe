# SPDX-License-Identifier: BSD-3-Clause
r"""Round 8-A: the GDL differential for
``soda2_process_2d.pro`` (the whole driver, `:1-742`), the bank R7A owed.

Method 1: the real, **unmodified** vendored driver is run
under GDL with ``op.savfile=1``; the ``save``/``restore`` round trip was
measured to preserve every ``help,/struct`` type and bit pattern for a
struct shaped like the driver's ``data`` (nested anonymous structs, every
numeric type, a negative LONG, a STRING) in 0.3 s -- so
there is no need for the run-time-generated "shadow" struct (method 2); the
bank ``restore``s ``soda2_filename(op, op.shortname)`` after
``soda2_process_2d, op``.

**Two oracle shims that are not shims**, plus one real gap-filling shim:

1. ``interpol.pro`` -- **not this bank's invention**. The portable GDL
   tree ships its own library routine at
   ``%USERPROFILE%\tools\gdl\share\gnudatalanguage\lib\utilities\interpol.pro``,
   but ``locate.run_pro``'s ``GDL_PATH`` does not reach the ``lib`` tree, so
   the driver halts at ``:462`` (``probetas=interpol(...)``) with
   "undefined procedure: INTERPOL". This bank reads that
   exact file at start and passes it through ``extra_files`` unmodified --
   GDL's own code, placed where ``run_pro`` looks, not an edit.
2. ``spec_decompress.pro`` / ``erode.pro`` / ``uniq.pro`` -- already
   vendored oracle shims for the SPEC processing chain
   (``run_soda2_spec_read_frame_bank.decompress_shim``,
   ``run_soda2_aspect_ratio_bank._erode_shim``,
   ``run_soda2_processbuffer_spec_bank.UNIQ_SHIM``); ``soda2_process_2d``
   calls into ``soda2_processbuffer``, which needs all three.
3. ``median.pro`` -- a **real gap-filling shim**, because GDL's builtin
   ``MEDIAN`` refuses a 1-element struct-field expression
   (``soda2_particlesort.pro:12``), which every ``s2_*``
   case hits (the s2 fixture holds exactly one particle per probe id).
   **Asserted bit-for-bit against the builtin before being trusted**: a
   separate, shim-free ``run_pro`` call prints the builtin's value on three
   vectors (odd/even, with and without ``/even``) and a 1-element array;
   the shimmed call is asserted to reproduce every one of those values
   exactly before the case bank runs at all (``_assert_median_shim``). If
   the assertion fails, the bank refuses to write a golden and every
   ``s2_*`` case is recorded ``HALTED (GDL-only, median)`` -- see
   ``main()``.

   **Mechanism, measured 2026-09-14**: the gap is not "GDL's
   ``median`` refuses a 1-element array" -- ``median([7.0d])`` returns
   ``7.000`` on GDL, same as IDL. The gap is GDL **collapsing a field
   extracted from a 1-element structure array to a scalar** --
   ``st=replicate({buffertime:7.0d, reftime:1.0d},1)`` leaves
   ``st.buffertime`` a plain ``DOUBLE``, not ``DOUBLE Array[1]`` as IDL
   documents field extraction should yield -- after which ``median``
   (which refuses scalars in both IDL and GDL) halts. This is why
   ``median.pro`` shadows the builtin rather than delegating to it: the
   builtin never gets a chance to see a 1-element array in this call
   shape, only the collapsed scalar. Probed directly with three
   expressions in one script: ``median([7.0d])`` -> ``7.000``;
   ``help, st.buffertime`` -> ``<Expression> DOUBLE = 7.0000000`` (a
   scalar); ``median(st.buffertime-st.reftime)`` on that ``st`` ->
   ``% MEDIAN: Expression must be an array in this context``. Because the
   s2 fixture holds exactly one particle per probe id, every ``s2_*`` case
   reaches ``particlesort`` with a 1-element buffer and hits this; the
   ``frame_*`` cases (``soda2_spec_frame_fixture``) carry buffers with
   >= 2 particles and never reach it at all (see ``frame_full``'s
   ``NUMBUFFSACC``/``PBPSTARTINDEX`` below), which is why every purpose
   the seven HALTED ``s2_*`` rows were meant to exercise is instead
   exercised on ``frame_*`` twins.

**The halt measured (2026-09-15), and the next line.** Every
record now stores GDL's own halt text and a path-free ``halt_at`` stack
(previously the golden held a synthetic "median shim unavailable" string
for all seven ``s2_*`` rows, so the location was never in the golden). The
seven halt at ``SODA2_PARTICLESORT:12 <- SODA2_PROCESS_2D:579`` (the final
sort), confirming that location. Two further measurements, scratch
diagnostics: (a) with ``:12`` bypassed in a *scratch
copy* of ``soda2_particlesort.pro`` (never a golden), ``s2_full`` halts at
``:13`` -- ``difftime=[0,truetime[1:*]-truetime]`` -- with ``Subscript out
of range [s:*]``; (b) ``a=[7d] & b=[0,a[1:*]-a]`` halts the same way on a
genuine ``DOUBLE Array[1]`` (``help`` says ``Array[1]``), so ``:13`` does
not depend on GDL's struct-field collapse. IDL documents a subscript range
whose start exceeds the last index as an error, so **a ``particlesort``
call with exactly one particle is derived to halt in IDL as well, at
``:13``** -- the earlier "real IDL would not halt here" holds for ``:12`` only.
That is a candidate SODA-2 finding (derived, not measured against IDL) and
a port divergence (``particlesort.py`` does not evaluate ``:13`` for SPEC,
so the port returns a result where IDL halts);
the port is not changed here.

**The ``s2dup`` twins.** ``build_s2dup()`` copies the tracked s2 fixture
and places a second copy of buffer 0's H frame and buffer 1's V frame
directly after the first, particle counter 7 -> 8 (built at run time,
never tracked). ``spec_index`` then indexes both, and -- because the
last-seen counter is now 8 -- also the pc-7 H frames of buffers 2, 4 and 5
it skipped as repeats before, so every ``particlesort`` call gets >= 2
particles. Each ``s2_*`` HALTED row has an ``s2dup_*`` twin with the same
overrides; the discriminating check (the single-particle cause is the only halt) is that
the twins are ``OK``.

``--jobs N`` runs cases concurrently (each case is its own GDL process in
its own temp directory); records are written in ``CASES`` order, so the
golden does not depend on ``N``.

GDL-only gaps encountered (not IDL findings -- IDL documents field
extraction from an array of structures as returning an array with the
structure array's dimensions, and IDL's ``median`` accepts a 1-element
array; so this is GDL's gap, not a version
difference this port needs to reproduce):

============  ==============================================================
Gap           Where
============  ==============================================================
``median.pro``  ``soda2_particlesort.pro:12``, hit by every ``s2_*`` case
                that reaches ``particlesort`` (the s2 fixture has exactly
                one particle per probe id) -- worked around above. Root
                cause: GDL collapses a 1-element struct-array field
                extraction to a scalar, not a defect in ``median`` of a
                1-element array itself (measured 2026-09-14).
============  ==============================================================

Column-major flattening: every multi-dimensional field is read through
``print_field.pro`` (extra_files), which does
``reform(value, n_elements(value))`` before formatting -- IDL/GDL arrays
are stored column-major, so this is the same order
``numpy.asarray(a).ravel(order="F")`` produces; the test compares against
that explicitly (never plain ``.ravel()``).

Run:  .venv/Scripts/python.exe gdl_oracle/run_soda2_process_2d_bank.py [--jobs N]
(~1-2 min of GDL per case; run it detached through scripts/launch_detached.sh.)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from locate import GDLUnavailable, idl_double, run_pro  # noqa: E402
from run_soda2_aspect_ratio_bank import ERODE_EDGE_RULE, _erode_shim  # noqa: E402
from run_soda2_processbuffer_spec_bank import UNIQ_SHIM  # noqa: E402
from run_soda2_spec_read_frame_bank import decompress_shim  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from scrub_paths import scrub_output  # noqa: E402

DATA = Path(__file__).resolve().parents[3] / "tests" / "data"
GOLDEN = DATA / "gdl_soda2_process_2d_golden.json"
S2_FIXTURE = DATA / "s2_spec_raw_fixture"
FRAME_FIXTURE = DATA / "soda2_spec_frame_fixture"

#: `.get`, not `[]`: the test module imports `build_s2dup` from here on CI,
#: where USERPROFILE is unset.
INTERPOL_PATH = (Path(os.environ.get("USERPROFILE", str(Path.home()))) / "tools" / "gdl" / "share" /
                  "gnudatalanguage" / "lib" / "utilities" / "interpol.pro")


class InterpolMissing(RuntimeError):
    """GDL's own ``lib/utilities/interpol.pro`` is not where the bank expects
    it -- never inline a copy, so this is a hard stop."""


def _read_interpol() -> str:
    if not INTERPOL_PATH.is_file():
        raise InterpolMissing(f"GDL's own interpol.pro not found at {INTERPOL_PATH}")
    return INTERPOL_PATH.read_text(encoding="utf-8")


_BUFSIZE, _HEADER_BYTES = 4114, 16
#: (buffer, frame length in words) of the two frames `build_s2dup` doubles:
#: buffer 0's H frame `[12883, 4, 0, 7, 2]` + 4 payload words, buffer 1's V
#: frame `[12883, 0, 5, 7, 3]` + 5 payload words, each at data word 0 with
#: only zero words after it (measured on the tracked fixture).
_S2DUP_FRAMES = ((0, 9), (1, 10))


def build_s2dup() -> bytes:
    """The s2 fixture with a second copy of each of its two indexed frames
    placed directly after the first, particle counter 7 -> 8, so no
    `particlesort` call sees a single particle. Asserts every anchor before
    writing (a fixture drift stops the bank rather than building a
    different twin)."""
    raw = bytearray(S2_FIXTURE.read_bytes())
    assert len(raw) == 6 * _BUFSIZE, len(raw)
    for buf, nwords in _S2DUP_FRAMES:
        base = buf * _BUFSIZE + _HEADER_BYTES
        frame = bytearray(raw[base:base + 2 * nwords])
        assert int.from_bytes(frame[0:2], "little") == 12883, "no '2S' marker"
        assert int.from_bytes(frame[6:8], "little") == 7, "particle counter moved"
        dest = slice(base + 2 * nwords, base + 4 * nwords)
        assert raw[dest] == bytes(2 * nwords), "twin slot not empty"
        frame[6:8] = (8).to_bytes(2, "little")
        raw[dest] = frame
    return bytes(raw)


#: `soda2_particlesort.pro:12`, `fixstuckbits.pro:17`,
#: `soda2_processbuffer.pro:138` -- GDL's builtin MEDIAN refuses a
#: 1-element struct-field expression; this is a full replacement (a `.pro`
#: named `median` shadows the builtin, so it cannot delegate to it).
#: Asserted against the builtin by `_assert_median_shim` before use.
MEDIAN_SHIM = """FUNCTION median, x, even=even
   ; GDL gap: builtin MEDIAN refuses a 1-element struct-field expression
   ; (soda2_particlesort.pro:12). IDL semantics without /EVEN: the upper of
   ; the two middle values for even n.
   n = n_elements(x)
   s = sort(x)
   IF keyword_set(even) and (n mod 2 eq 0) THEN return, (x[s[n/2-1]] + x[s[n/2]]) / 2.0
   return, x[s[n/2]]
END
"""

#: `print_field, name, value` -- generic column-major hex/int printer.
#: DOUBLE -> `NAMEHEX=` Z016 words; FLOAT -> `NAMEHEX=` Z08 words; anything
#: else (INT/LONG/BYTE) -> `NAME=` plain decimal words. This is what makes
#: the key-naming convention (HEX suffix iff float/double) automatic rather
#: than hand-maintained per field.
PRINT_FIELD_SHIM = """PRO print_field, name, value
   tn = size(value, /tname)
   n = n_elements(value)
   flat = reform(value, n)
   CASE tn OF
      'DOUBLE': print, name+'HEX='+strjoin(string(ulong64(flat,0,n),format='(Z016)'),',')
      'FLOAT': print, name+'HEX='+strjoin(string(ulong(flat,0,n),format='(Z08)'),',')
      ELSE: print, name+'='+strjoin(strtrim(string(long(flat)),2),',')
   ENDCASE
END
"""

_MEDIAN_ASSERT_SCRIPT = """
a = [3.,1.,2.] & b = [4.,1.,3.,2.] & c = [5.,1.,4.,2.,3.,6.] & d = [7.]
print, 'MA=', median(a), format='(A,F0.6)'
print, 'MB=', median(b), format='(A,F0.6)'
print, 'MBE=', median(b,/even), format='(A,F0.6)'
print, 'MC=', median(c), format='(A,F0.6)'
print, 'MCE=', median(c,/even), format='(A,F0.6)'
print, 'MD=', median(d), format='(A,F0.6)'
st = {f: 7.0d}
print, 'MSTRUCT=', median(st.f), format='(A,F0.6)'
"""


def _parse_median_probe(stdout: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for raw in stdout.splitlines():
        line = raw.strip()
        if "=" in line:
            key, _, val = line.partition("=")
            try:
                out[key.strip()] = float(val.strip())
            except ValueError:
                continue
    return out


def _assert_median_shim() -> bool:
    """Run the probe script once with GDL's real builtin, once with the
    shim shadowing it, and require bit-for-bit (here: value-for-value,
    ``==``, no tolerance) agreement -- two sides from different places.
    Returns True iff the shim may be trusted.

    ``MA``..``MD`` alone do not discriminate: the shim and the builtin
    agree on every ordinary vector, so a probe using only those cannot
    tell "the shim ran" from "GDL silently used its own builtin instead"
    -- and that is exactly what measurement found (the real bank run
    still halted on every ``s2_*`` case with the builtin's own error text,
    ``median.pro`` present or not). ``MSTRUCT`` is the discriminator: it
    reproduces the exact 1-element struct-field expression
    (``soda2_particlesort.pro:12``) the builtin refuses. If it is missing
    from the shimmed run's stdout, GDL never dispatched to the user
    ``.pro`` for this call shape at all -- **GDL cannot override this
    builtin**, so the shim is refused and every case that needs it is
    recorded ``HALTED (GDL-only, median)``."""
    builtin_out, _ = run_pro(_MEDIAN_ASSERT_SCRIPT, timeout=60)
    shimmed_out, shimmed_err = run_pro(_MEDIAN_ASSERT_SCRIPT, timeout=60,
                                        extra_files={"median.pro": MEDIAN_SHIM})
    builtin = _parse_median_probe(builtin_out)
    shimmed = _parse_median_probe(shimmed_out)
    if not builtin or not shimmed:
        print("median shim assertion FAILED: one probe run produced no output")
        return False
    for key in ("MA", "MB", "MBE", "MC", "MCE", "MD"):
        if key not in builtin or key not in shimmed or builtin[key] != shimmed[key]:
            print(f"median shim assertion FAILED at {key}: "
                  f"builtin={builtin.get(key)} shim={shimmed.get(key)}")
            return False
    if "MSTRUCT" not in shimmed:
        print("median shim assertion FAILED: GDL did not dispatch to the "
              "user median.pro for the 1-element struct-field expression -- "
              f"it still raised the builtin's own error ({shimmed_err[-200:]!r}); "
              "GDL cannot override this builtin.")
        return False
    print(f"median shim assertion OK: {shimmed}")
    return True


@dataclass
class Case:
    name: str
    fixture: str  # "s2", "frame" or "s2dup" (build_s2dup, never tracked)
    overrides: dict[str, str] = field(default_factory=dict)
    expect: str = ""


CASES: list[Case] = [
    Case("s2_full", "s2", {},
         expect="OK; buffer accept/reject counts -- the golden decides"),
    Case("s2_fixedtas", "s2", {"fixedtas": "100.0"},
         expect="OK; TAS = 42C80000 everywhere"),
    Case("s2_window_mid", "s2",
         {"starttime": idl_double(24244.0), "stoptime": idl_double(24246.0)},
         expect="OK; IND[0] negative (R7A trap 1/11)"),
    Case("s2_rate_half", "s2",
         {"rate": idl_double(0.5), "stoptime": idl_double(24249.7)},
         expect="OK; check the printed NUMRECORDS, do not trust the arithmetic"),
    Case("s2_rate_float", "s2", {"rate": "1.0"},
         expect="OK; TN of activetime/time -- does it follow rate's type?"),
    Case("s2_probeid_v", "s2", {"probeid": "'V'"},
         expect="OK with the median shim (one V particle), else HALTED"),
    Case("frame_full", "frame", {}, expect="OK (M3 values)"),
    Case("frame_stretch", "frame",
         {"stretchcorrect": "1", "fixedtas": "120.0"}, expect="OK (M3)"),
    Case("date_off1", "s2", {"date": "'20160905'"}, expect="NO_OUTPUT"),
    Case("date_off10", "s2", {"date": "'20160827'"},
         expect="OK, every key identical to s2_full"),
    Case("window_empty", "s2",
         {"starttime": idl_double(24300.0), "stoptime": idl_double(24310.0)},
         expect="NO_OUTPUT"),
    # 2026-09-14: the six purposes below could only be exercised
    # on ``s2_*`` cases that HALT (median-of-collapsed-1-element-field, see
    # the module docstring). Every buffer in ``frame`` fixture has >= 2
    # particles and never reaches the halt, so each purpose is carried over
    # here on the ``frame`` fixture instead. The seven HALTED ``s2_*`` rows
    # above stay, unchanged, documented as GDL-only.
    Case("frame_fixedtas", "frame", {"fixedtas": "100.0"},
         expect="OK; TAS = 42C80000 everywhere (purpose carried over from s2_fixedtas)"),
    Case("frame_window_mid", "frame",
         {"starttime": idl_double(24243.0), "stoptime": idl_double(24245.0)},
         expect="OK; NUMBUFFSACC sums to 2 (the two accepted buffers at time "
                "idx 3, 4 in frame_full's window) -- if it sums to 0 the window "
                "missed them (purpose carried over from s2_window_mid)"),
    Case("frame_rate_half", "frame",
         {"rate": idl_double(0.5), "stoptime": idl_double(24249.7)},
         expect="OK; read NUMRECORDS from the print, do not compute it "
                "(purpose carried over from s2_rate_half)"),
    Case("frame_rate_float", "frame", {"rate": "1.0"},
         expect="OK; TN entry for data.activetime (5th of _TN_FIELDS) -- "
                "expected FLOAT (purpose carried over from s2_rate_float, "
                "pins S6-e's FLOAT branch, unmeasured until now)"),
    Case("frame_probeid_v", "frame", {"probeid": "'V'"},
         expect="either OK with zero accepted buffers or NO_OUTPUT -- "
                "whichever GDL prints is the measurement (purpose carried "
                "over from s2_probeid_v)"),
    Case("frame_date_off10", "frame", {"date": "'20160827'"},
         expect="OK, every key identical to frame_full "
                "(purpose carried over from date_off10)"),
    # The >= 2-particle twin of each HALTED s2_* row -- same
    # overrides, the s2dup fixture (build_s2dup). OK on every one means the
    # 1-particle particlesort halt is the only thing stopping the s2 rows.
    Case("s2dup_full", "s2dup", {},
         expect="OK -- discriminating: HALTED here means Y2's cause was not the only one"),
    Case("s2dup_fixedtas", "s2dup", {"fixedtas": "100.0"},
         expect="OK; TAS = 42C80000 everywhere"),
    Case("s2dup_window_mid", "s2dup",
         {"starttime": idl_double(24244.0), "stoptime": idl_double(24246.0)},
         expect="OK; IND[0] negative (R7A trap 1/11)"),
    Case("s2dup_rate_half", "s2dup",
         {"rate": idl_double(0.5), "stoptime": idl_double(24249.7)},
         expect="OK; NUMRECORDS read from the print"),
    Case("s2dup_rate_float", "s2dup", {"rate": "1.0"},
         expect="OK; TN of data.activetime"),
    Case("s2dup_probeid_v", "s2dup", {"probeid": "'V'"},
         expect="OK (two V particles in buffer 1)"),
    Case("s2dup_date_off10", "s2dup", {"date": "'20160827'"},
         expect="OK, every key identical to s2dup_full"),
]

#: The measured-to-run `op` literal, IDL literal strings
#: keyed by field name.
_BASE_FIELDS: dict[str, str] = {
    "date": "'20160906'",
    "starttime": idl_double(24240.0),
    "stoptime": idl_double(24250.0),
    "format": "'SPEC'",
    "subformat": "0",
    "probetype": "'2DS'",
    "shortname": "'2DS'",
    "res": "10.0",
    "yres": "10.0",
    "wavelength": "0.785e-6",
    "dofconst": "8.12",
    "armwidth": "6.3",
    "numdiodes": "128",
    "greythresh": "0",
    "tau": "41.0e-9",
    "endbins": "[10.0,50.0,100.0,200.0,500.0]",
    "arendbins": "[0.0,0.5,1.0]",
    "rate": idl_double(1.0),
    "smethod": "'xy'",
    "eawmethod": "'centerin'",
    "pth": "''",
    "particlefile": "0",
    "ncdfparticlefile": "0",
    "asciipsdfile": "0",
    "savfile": "1",
    "inttime_reject": "0",
    "reconstruct": "1",
    "stuckbits": "0",
    "water": "0",
    "fixedtas": "0.0",
    "project": "'x'",
    "timeoffset": "0.0",
    "probeid": "'H'",
    "dofreject": "0",
    "stretchcorrect": "0",
}

#: Keys printed for every OK case, in `print_field` call order. `NUMRECORDS`
#: and `HOUSENB` are handled separately (§3.4 of the plan).
_FIELD_KEYS: list[tuple[str, str]] = [
    ("TIME", "data.time"),
    ("TAS", "data.tas"),
    ("PROBETAS", "data.probetas"),
    ("MIDBINS", "data.midbins"),
    ("ACTIVETIME", "data.activetime"),
    ("SA", "data.sa"),
    ("INTSPECALL", "data.intspec_all"),
    ("INTSPECACC", "data.intspec_accepted"),
    ("INTENDBINS", "data.intendbins"),
    ("INTMIDBINS", "data.intmidbins"),
    ("COUNTREJ", "data.count_rejected"),
    ("TOTALCOUNTREJ", "data.total_count_rejected"),
    ("COUNTACC", "data.count_accepted"),
    ("COUNTMISSED", "data.count_missed"),
    ("MISSEDHIST", "data.missed_hist"),
    ("CONC1D", "data.conc1d"),
    ("SPEC1D", "data.spec1d"),
    ("SPEC2D", "data.spec2d"),
    ("SPEC2DASPR", "data.spec2d_aspr"),
    ("CORRFAC", "data.corr_fac"),
    ("POISSONFAC", "data.poisson_fac"),
    ("INTCUTOFF", "data.intcutoff"),
    ("ZDSPEC", "data.zdspec"),
    ("ZDENDBINS", "data.zdendbins"),
    ("ZDMIDBINS", "data.zdmidbins"),
    ("POINTER", "data.pointer"),
    ("IND", "data.ind"),
    ("CURRENTFILE", "data.currentfile"),
    ("NUMBUFFSACC", "data.numbuffsaccepted"),
    ("NUMBUFFSREJ", "data.numbuffsrejected"),
    ("DHIST", "data.dhist"),
    ("HIST3D", "data.hist3d"),
    ("SPEC2DORIENT", "data.spec2d_orientation"),
    ("ORIENTIDX", "data.orientation_index"),
    ("PBPSTARTINDEX", "data.pbpstartindex"),
    ("HOUSETIME", "data.house.time"),
    ("HOUSETAS", "data.house.tas"),
    ("HOUSENB", "data.house.nb"),
]

_TN_FIELDS = (
    "data.time", "data.tas", "data.probetas", "data.midbins",
    "data.activetime", "data.sa", "data.count_accepted",
    "data.numbuffsaccepted", "data.dhist", "data.ind", "data.currentfile",
    "data.pbpstartindex", "data.conc1d", "data.pointer", "data.zdspec",
    "data.hist3d",
)


def _op_literal(fixture_posix: str, outdir_posix: str, overrides: dict[str, str]) -> str:
    fields = dict(_BASE_FIELDS)
    fields.update(overrides)
    parts = [f"fn:'{fixture_posix}'", f"outdir:'{outdir_posix}/'"]
    for key, lit in fields.items():
        parts.append(f"{key}:{lit}")
    return "{" + ", ".join(parts) + "}"


def _script_for(case: Case, fixture_posix: str, outdir_posix: str) -> str:
    op_lit = _op_literal(fixture_posix, outdir_posix, case.overrides)
    tn_expr = "+','+".join(f"size({f},/tname)" for f in _TN_FIELDS)
    field_prints = "\n  ".join(
        f"print_field, '{key}', {expr}" for key, expr in _FIELD_KEYS)
    return f"""
op = {op_lit}
fnout = soda2_filename(op, op.shortname)
soda2_process_2d, op
print, 'CASE={case.name}'
IF file_test(fnout) THEN BEGIN
  restore, fnout
  print, 'STATUS=OK'
  print, 'NUMRECORDS=', n_elements(data.time), format='(A,I0)'
  {field_prints}
  print, 'TN=' + {tn_expr}
ENDIF ELSE print, 'STATUS=NO_OUTPUT'
"""


def _parse_case(stdout: str) -> dict[str, Any] | None:
    rec: dict[str, Any] = {}
    for raw in stdout.splitlines():
        line = raw.strip()
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        rec[key.strip()] = val.strip()
    return rec or None


#: `% Execution halted at: ROUTINE  LINE path` and its continuation lines
#: (`%   ROUTINE  LINE path`) -- routine and line only, never the path (temp
#: directories differ per run, and the golden must not).
_HALT_FRAME = re.compile(r"^%\s+(?:Execution halted at:\s+)?([A-Z0-9_$]+)\s+(\d+)\b")


def _halt_record(stderr: str) -> dict[str, Any]:
    """GDL's own first `%` line and a path-free `ROUTINE:LINE` stack."""
    lines = [ln.strip() for ln in stderr.splitlines() if ln.strip().startswith("%")]
    message = next((ln for ln in lines if "Execution halted" not in ln
                    and not _HALT_FRAME.match(ln)), lines[0] if lines else "")
    stack: list[str] = []
    seen_halt = False
    for ln in lines:
        if "Execution halted at:" in ln:
            seen_halt = True
        if not seen_halt:
            continue
        m = _HALT_FRAME.match(ln)
        if m and m.group(1) != "BANK":
            stack.append(f"{m.group(1)}:{m.group(2)}")
    return {"message": message, "halt_at": " <- ".join(stack)}


def _driver_prints(stdout: str) -> list[str]:
    """What the driver printed before the bank's own `CASE=` line -- for a
    NO_OUTPUT case this is the measured cause (e.g. `:430-433`'s "No
    buffers in specified time range")."""
    out: list[str] = []
    for raw in stdout.splitlines():
        line = raw.strip()
        if line.startswith("CASE="):
            break
        if line:
            out.append(line)
    return out


def _run_case(case: Case, fixture: Path, extra_files: dict[str, str]) -> dict[str, Any]:
    tmp = tempfile.mkdtemp(prefix="soda2_p2d_")
    try:
        script = _script_for(case, fixture.resolve().as_posix(),
                             Path(tmp).resolve().as_posix())
        stdout, stderr = run_pro(script, timeout=600, extra_files=extra_files)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    rec: dict[str, Any] = {
        "name": case.name, "fixture": case.fixture,
        "overrides": case.overrides, "expect": case.expect,
    }
    if "Execution halted" in stderr:
        rec["status"] = "HALTED"
        rec.update(_halt_record(stderr))
        print(f"{case.name}: HALTED -- {rec['message']} @ {rec['halt_at']}", flush=True)
        return rec

    parsed = _parse_case(stdout)
    if parsed is None or parsed.get("STATUS") not in ("OK", "NO_OUTPUT"):
        rec["status"] = "ERROR"
        rec["stdout"] = stdout[-1500:]
        rec["stderr"] = stderr[-800:]
        print(f"{case.name}: ERROR", flush=True)
        return rec

    if parsed["STATUS"] == "NO_OUTPUT":
        rec["status"] = "NO_OUTPUT"
        rec["driver_print"] = _driver_prints(stdout)
        print(f"{case.name}: NO_OUTPUT -- {rec['driver_print']}", flush=True)
        return rec

    rec["status"] = "OK"
    rec["NUMRECORDS"] = int(parsed["NUMRECORDS"])
    rec["TN"] = parsed.get("TN", "")
    for key, _ in _FIELD_KEYS:
        hexkey = key + "HEX"
        if hexkey in parsed:
            rec[hexkey] = parsed[hexkey].split(",") if parsed[hexkey] else []
        elif key in parsed:
            rec[key] = ([int(v) for v in parsed[key].split(",")]
                        if parsed[key] else [])
    print(f"{case.name}: OK NUMRECORDS={rec['NUMRECORDS']}", flush=True)
    return rec


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--jobs", type=int, default=1,
                    help="cases run concurrently (default 1); the golden "
                         "does not depend on it")
    args = ap.parse_args(argv)

    if not S2_FIXTURE.is_file() or not FRAME_FIXTURE.is_file():
        print(f"missing tracked fixture(s): {S2_FIXTURE}, {FRAME_FIXTURE}")
        return 2

    try:
        interpol_text = _read_interpol()
    except InterpolMissing as exc:
        print(str(exc))
        return 2

    try:
        median_ok = _assert_median_shim()
    except GDLUnavailable as exc:
        print(f"GDL unavailable: {exc}")
        return 2

    extra_files = {
        "interpol.pro": interpol_text,
        "spec_decompress.pro": decompress_shim(),
        "erode.pro": _erode_shim(ERODE_EDGE_RULE),
        "uniq.pro": UNIQ_SHIM,
        "print_field.pro": PRINT_FIELD_SHIM,
    }
    if median_ok:
        extra_files["median.pro"] = MEDIAN_SHIM

    fx_dir = tempfile.TemporaryDirectory(prefix="soda2_s2dup_")
    try:
        s2dup = Path(fx_dir.name) / "s2dup_fixture"
        s2dup.write_bytes(build_s2dup())
        fixtures = {"s2": S2_FIXTURE, "frame": FRAME_FIXTURE, "s2dup": s2dup}
        try:
            with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
                records = list(pool.map(
                    lambda c: _run_case(c, fixtures[c.fixture], extra_files), CASES))
        except GDLUnavailable as exc:
            print(f"GDL unavailable: {exc}")
            return 2
    finally:
        fx_dir.cleanup()

    records_out = [
        {"oracle_shims": [
            "interpol.pro (GDL's own lib/utilities/interpol.pro, not a shim; "
            "run_pro's GDL_PATH does not reach the lib tree)",
            "spec_decompress.pro (+1 line, ISHFT array quirk)",
            "erode.pro (ERODE_EDGE_RULE, aspect_ratio inside the tail)",
            "uniq.pro (fillholes.pro:14)",
            "print_field.pro (new -- generic column-major hex/int printer, "
            "not an oracle-behaviour shim)",
            "median.pro (GDL refuses a 1-element struct-field expression; "
            "asserted equal to the builtin on 3 vectors: "
            f"{'OK' if median_ok else 'FAILED, not applied'})",
        ]},
        *records,
    ]
    ok = sum(1 for r in records if r.get("status") == "OK")
    if ok == 0:
        print("refusing to write a golden in which every case errored")
        return 1
    GOLDEN.write_text(json.dumps(records_out, indent=2) + "\n", encoding="utf-8")
    scrub_output(GOLDEN)  # path prefixes -> <repo>, <tmp>, ~
    counts: dict[str, int] = {}
    for r in records:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    print(f"\nwrote {GOLDEN} -- {len(records)} cases, {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

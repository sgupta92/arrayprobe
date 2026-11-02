# SPDX-License-Identifier: BSD-3-Clause
# ruff: noqa: E501  (the GDL script literal and golden paths are long lines by nature)
r"""The GDL differential for SODA-2's CIP route through a SEA file,
stage by stage -- ``soda2_buildindex`` (generic walk, `:20-61`) over
``soda2_read2dbuffer``'s SEA branch (`:69-89`) and ``readseabuffer_caps`` /
``seaimagepointers`` / ``readdatadir``; ``decompress_dmt3`` with
``decode_header_slice``; and ``soda2_processbuffer``'s CIP branch (`:129-203`)
through the shared tail (`:612-747`), buffer after buffer with ``pmisc``
carried the way the driver carries it; plus the CIP-1D record walk
(``readseabuffer_caps, probetype='CIP1D'``) that ``process_cip1d_sea`` reads.

The real, unmodified vendored routines run under GDL; every result is written
by GDL's own ``save`` and read back with ``scipy.io.readsav`` (the round trip
R8A measured to preserve IDL types and bits). Oracle shims, the same ones the
``process_2d`` bank uses and for the same reason (GDL's library tree is not on
``!PATH``): ``erode.pro`` (``run_soda2_aspect_ratio_bank``) and ``uniq.pro``
(``run_soda2_processbuffer_spec_bank``). Nothing is written into ``SODA2/``.

Two inputs:

- ``--fixture`` (default): the tracked synthetic file
  ``tests/data/soda2_sea_cip_fixture.sea`` (``make_soda2_sea_cip_fixture.py``);
  the golden, ``tests/data/gdl_soda2_cip_golden.json``, is tracked.
- ``--und``: the UND 2016-09-06 06:40:17 ``.sea`` file, read at run time from
  the gitignored ``arrayprobe-local-data/2016-und-data/`` tree; the whole index
  plus the buffers of one window (``--start``/``--stop``, seconds from
  midnight). The golden goes to ``arrayprobe-local-data/soda2_cip_goldens/``
  and is **never tracked** (no UND bytes in the repository).

Run from the repository root::

    .venv/Scripts/python.exe gdl_oracle/run_soda2_cip_bank.py
    .venv/Scripts/python.exe gdl_oracle/run_soda2_cip_bank.py --und --start 25200 --stop 25260
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from locate import GDLUnavailable, run_pro  # noqa: E402
from run_soda2_aspect_ratio_bank import ERODE_EDGE_RULE, _erode_shim  # noqa: E402
from run_soda2_process_2d_bank import (  # noqa: E402
    _FIELD_KEYS,
    _TN_FIELDS,
    PRINT_FIELD_SHIM,
    _driver_prints,
    _halt_record,
    _parse_case,
)
from run_soda2_processbuffer_spec_bank import UNIQ_SHIM  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from scrub_paths import scrub_output  # noqa: E402

HERE = Path(__file__).resolve().parent
DATA = HERE.parents[2] / "tests" / "data"
FIXTURE = DATA / "soda2_sea_cip_fixture.sea"
GOLDEN = DATA / "gdl_soda2_cip_golden.json"
DRIVER_GOLDEN = DATA / "gdl_soda2_cip_driver_golden.json"
UND_REL = Path("2016-und-data/20160906_1/20160906_064017_1/PostProcessing/2016_09_06_06_40_17.sea")
LOCAL_GOLDEN_DIR = "soda2_cip_goldens"


def local_data_root() -> Path:
    """``ARRAYPROBE_REFERENCE_DATA`` first, then ``arrayprobe-local-data/``
    beside any parent (a worktree reaches its main checkout's)."""
    roots = []
    if os.environ.get("ARRAYPROBE_REFERENCE_DATA"):
        roots.append(Path(os.environ["ARRAYPROBE_REFERENCE_DATA"]))
    roots += [p / "arrayprobe-local-data" for p in HERE.parents]
    for root in roots:
        if (root / UND_REL).is_file():
            return root
    return roots[-1]


#: The op the bank hands the IDL: the `'UND CIP (SEA M300)'` row of
#: `soda2_probespecs.pro:1240-1256` (res, yres, armwidth, numdiodes, seatag)
#: plus the driver-level fields; `soda2_update_op` fills the rest.
def op_literal(fn: str, date: str = "09062016", starttime: float = 0.0,
               stoptime: float = 86400.0) -> str:
    return (
        f"op = {{fn:'{fn}', date:'{date}', starttime:{starttime}d, stoptime:{stoptime}d, "
        "format:'SEA', subformat:1, probetype:'CIP', res:25.0, yres:25.0, armwidth:6.0, "
        "numdiodes:64.0, probeid:'', shortname:'CIP', greythresh:0, wavelength:0.658e-6, "
        "dofconst:3.0, seatag:[33000, 32000, 0], "
        "endbins:[25,50,75,100,125,150,200,250,300,350,400,475,550,625,700,800,900,1000,"
        "1200,1400,1600], arendbins:[0.1,0.2,0.3,0.4,0.5,0.6,0.7,0.8,0.9,1.0], rate:1, "
        "smethod:'fastcircle', pth:'', particlefile:0, inttime_reject:0, stuckbits:0, "
        "water:0, fixedtas:0.0, outdir:'', project:'', timeoffset:0.0, eawmethod:'centerin'}\n"
        "soda2_update_op, op\n"
    )


def _script(fn: str, tmp: str, first: int, last: int) -> str:
    t = tmp.replace("\\", "/")
    return op_literal(fn) + f"""
pop = ptr_new(op)
misc={{f2d_remainder:ulon64arr(512), f2d_remainder_slices:0, lastbufftime:0D, aircrafttas:0.0, probetas:0.0,$
      nimages:0, imagepointers:lon64arr(500), hkpointers:lon64arr(500), lastclock:0d, lastparticlecount:0L, maxsfm:0D, $
      lastdhist:lonarr(op.numdiodes)}}
pmisc = ptr_new(misc)
y = soda2_buildindex(op.fn[0], pop)
save, file='{t}/index.sav', y
close, 1
openr, 1, op.fn[0]
first = {first} > 0
last = {last} < (y.count-1)
FOR i=first, last DO BEGIN
   point_lun, 1, y.pointer[i]
   b = soda2_read2dbuffer(1, pop)
   x = decompress_dmt3(b.image)
   b.time = y.bufftime[i]
   p = soda2_processbuffer(b, pop, pmisc)
   m = *pmisc
   save, file='{t}/buf_'+strtrim(string(i),2)+'.sav', b, x, p, m
ENDFOR
close, 1
openr, 2, op.fn[0]
c = 0L
st = dblarr(100000) & pt = dblarr(100000) & pcnt = lonarr(100000) & cnt0 = lonarr(100000)
REPEAT BEGIN
   a = readseabuffer_caps(2, probetype='CIP1D', tag=op.seatag[1])
   IF a.eof eq 0 THEN BEGIN
      st[c] = a.starttime & pt[c] = a.probetime & pcnt[c] = a.image.particlecounter
      cnt0[c] = total(a.image.count)
      c++
   ENDIF
ENDREP UNTIL (a.eof eq 1) or (c ge 100000)
close, 2
IF c gt 0 THEN BEGIN
   cip1d = {{starttime:st[0:c-1], probetime:pt[0:c-1], particlecounter:pcnt[0:c-1], counttotal:cnt0[0:c-1]}}
   save, file='{t}/cip1d.sav', cip1d
ENDIF
print, 'BANKDONE', first, last
"""


#: The composition-level driver golden: ``soda2_process_2d`` run whole
#: (never the sub-function walk above). Two cases: ``cip_single_tag``
#: (``seatag:[33000]``, the case the port must match bit-for-bit) and
#: ``cip_und_tags`` (``seatag:[33000,32000,0]``, recorded now for CIP-2).
_DRIVER_CASES: dict[str, str] = {
    "cip_single_tag": "[33000]",
    "cip_und_tags": "[33000, 32000, 0]",
}

#: `data.house.*` rows the SPEC driver bank prints -- excluded for the CIP
#: driver: `house={op:op}` (`cip_single_tag`) has none of these tags, and
#: printing them halts GDL.
_HOUSE_KEYS_EXCLUDED = {"HOUSETIME", "HOUSETAS", "HOUSENB"}

#: `process_cip1d_sea.pro:112-117`'s struct -- printed only for `cip_und_tags`
#: no `nb` field.
_CIP_UND_HOUSE_FIELDS: tuple[tuple[str, str], ...] = (
    ("HOUSETIME2", "data.house.time"),
    ("HOUSETASPITOT", "data.house.tas_pitot"),
    ("HOUSESPEC1D", "data.house.spec1d"),
    ("HOUSEPARTCOUNT", "data.house.particlecounter"),
)


def _driver_op_literal(fn_posix: str, outdir_posix: str, seatag_literal: str) -> str:
    """Same op as :func:`op_literal`'s literal fields, plus the driver-level
    ones the plan pins (§1): a 30 s window covering all 7 indexed buffers,
    `savfile:1` so the run can be `restore`d back in the same script."""
    return (
        f"{{fn:'{fn_posix}', date:'09062016', starttime:25800d, stoptime:25830d, "
        "format:'SEA', subformat:1, probetype:'CIP', res:25.0, yres:25.0, armwidth:6.0, "
        "numdiodes:64.0, probeid:'', shortname:'CIP', greythresh:0, wavelength:0.658e-6, "
        f"dofconst:3.0, seatag:{seatag_literal}, "
        "endbins:[25,50,75,100,125,150,200,250,300,350,400,475,550,625,700,800,900,1000,"
        "1200,1400,1600], arendbins:[0.1,0.2,0.3,0.4,0.5,0.6,0.7,0.8,0.9,1.0], rate:1, "
        "smethod:'fastcircle', pth:'', particlefile:0, inttime_reject:0, stuckbits:0, "
        f"water:0, fixedtas:0.0, outdir:'{outdir_posix}/', project:'', timeoffset:0.0, "
        "eawmethod:'centerin', savfile:1}"
    )


def _driver_script(case_name: str, fn_posix: str, outdir_posix: str) -> str:
    op_lit = _driver_op_literal(fn_posix, outdir_posix, _DRIVER_CASES[case_name])
    field_prints = "\n  ".join(
        f"print_field, '{key}', {expr}" for key, expr in _FIELD_KEYS
        if key not in _HOUSE_KEYS_EXCLUDED)
    house_extra = ""
    if case_name == "cip_und_tags":
        house_extra = "\n  " + "\n  ".join(
            f"print_field, '{key}', {expr}" for key, expr in _CIP_UND_HOUSE_FIELDS)
    tn_expr = "+','+".join(f"size({f},/tname)" for f in _TN_FIELDS)
    return f"""
op = {op_lit}
soda2_update_op, op
fnout = soda2_filename(op, op.shortname)
soda2_process_2d, op
print, 'CASE={case_name}'
IF file_test(fnout) THEN BEGIN
  restore, fnout
  print, 'STATUS=OK'
  print, 'NUMRECORDS=', n_elements(data.time), format='(A,I0)'
  {field_prints}
  print, 'HOUSETAGS=' + strjoin(tag_names(data.house), ','){house_extra}
  print, 'TN=' + {tn_expr}
ENDIF ELSE print, 'STATUS=NO_OUTPUT'
"""


def _run_driver_case(case_name: str, fn: Path, tmp: str) -> dict[str, Any]:
    extra = {"erode.pro": _erode_shim(ERODE_EDGE_RULE), "uniq.pro": UNIQ_SHIM,
             "print_field.pro": PRINT_FIELD_SHIM}
    script = _driver_script(case_name, fn.resolve().as_posix(), Path(tmp).resolve().as_posix())
    stdout, stderr = run_pro(script, timeout=600, extra_files=extra)
    rec: dict[str, Any] = {"name": case_name, "seatag": _DRIVER_CASES[case_name]}
    if "Execution halted" in stderr:
        rec["status"] = "HALTED"
        rec.update(_halt_record(stderr))
        print(f"{case_name}: HALTED -- {rec['message']} @ {rec['halt_at']}", flush=True)
        return rec
    parsed = _parse_case(stdout)
    if parsed is None or parsed.get("STATUS") not in ("OK", "NO_OUTPUT"):
        rec["status"] = "ERROR"
        rec["stdout"] = stdout[-1500:]
        rec["stderr"] = stderr[-800:]
        print(f"{case_name}: ERROR", flush=True)
        return rec
    if parsed["STATUS"] == "NO_OUTPUT":
        rec["status"] = "NO_OUTPUT"
        rec["driver_print"] = _driver_prints(stdout)
        print(f"{case_name}: NO_OUTPUT -- {rec['driver_print']}", flush=True)
        return rec
    rec["status"] = "OK"
    rec["NUMRECORDS"] = int(parsed["NUMRECORDS"])
    rec["TN"] = parsed.get("TN", "")
    rec["HOUSETAGS"] = parsed.get("HOUSETAGS", "")
    for key, _ in _FIELD_KEYS:
        if key in _HOUSE_KEYS_EXCLUDED:
            continue
        hexkey = key + "HEX"
        if hexkey in parsed:
            rec[hexkey] = parsed[hexkey].split(",") if parsed[hexkey] else []
        elif key in parsed:
            rec[key] = [int(v) for v in parsed[key].split(",")] if parsed[key] else []
    if case_name == "cip_und_tags":
        for key, _ in _CIP_UND_HOUSE_FIELDS:
            hexkey = key + "HEX"
            if hexkey in parsed:
                rec[hexkey] = parsed[hexkey].split(",") if parsed[hexkey] else []
            elif key in parsed:
                rec[key] = [int(v) for v in parsed[key].split(",")] if parsed[key] else []
    print(f"{case_name}: OK NUMRECORDS={rec['NUMRECORDS']}", flush=True)
    return rec


def run_driver() -> int:
    """CIP-1 §1: the composition-level golden, both cases, written whatever
    each one's status is (§1's stopping condition is read by the caller, not
    enforced here -- this only measures and records)."""
    records = []
    for case_name in _DRIVER_CASES:
        with tempfile.TemporaryDirectory() as tmp:
            try:
                records.append(_run_driver_case(case_name, FIXTURE, tmp))
            except GDLUnavailable as exc:
                print(exc, file=sys.stderr)
                return 2
    DRIVER_GOLDEN.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    scrub_output(DRIVER_GOLDEN)  # path prefixes -> <repo>, <tmp>, ~
    print(f"wrote {DRIVER_GOLDEN} ({DRIVER_GOLDEN.stat().st_size} bytes)")
    single = next((r for r in records if r["name"] == "cip_single_tag"), None)
    print(f"cip_single_tag status: {single.get('status') if single else 'MISSING'}")
    return 0


def _plain(v: Any) -> Any:
    """readsav value -> JSON-able, keeping dtype names for arrays."""
    if isinstance(v, np.recarray) or (isinstance(v, np.ndarray) and v.dtype.names):
        rec = v[0] if v.ndim else v
        return {name.lower(): _plain(rec[name]) for name in v.dtype.names}
    if isinstance(v, np.ndarray):
        if v.dtype == object:
            return [_plain(e) for e in v.ravel()]
        a = v.astype(v.dtype.newbyteorder("="))
        if a.dtype.kind == "f":
            return {"dtype": str(a.dtype), "shape": list(a.shape),
                    "hex": base64.b64encode(np.ascontiguousarray(a).tobytes()).decode()}
        return {"dtype": str(a.dtype), "shape": list(a.shape),
                "b64": base64.b64encode(np.ascontiguousarray(a).tobytes()).decode()}
    if isinstance(v, (bytes, np.bytes_)):
        return v.decode("latin-1")
    if isinstance(v, np.generic):
        return {"dtype": str(v.dtype), "value": v.item()}
    return v


def _compact(res: dict[str, Any]) -> dict[str, Any]:
    """Shrink a result for storage: the raw image bytes (``b.image``, ``x.image``)
    become SHA-256 digests, 0/1 ``bitimage`` arrays are bit-packed, and ``pmisc``
    keeps only the two fields the CIP branch writes."""
    import hashlib

    def digest(node: dict) -> str:
        return hashlib.sha256(base64.b64decode(node["b64"])).hexdigest()

    for buf in res["buffers"].values():
        if isinstance(buf["b"].get("image"), dict) and "b64" in buf["b"]["image"]:
            buf["b"]["image_sha256"] = digest(buf["b"].pop("image"))
        if isinstance(buf["x"].get("image"), dict) and "b64" in buf["x"]["image"]:
            buf["x"]["image_sha256"] = digest(buf["x"].pop("image"))
        for part in ("x", "p"):
            bi = buf[part].get("bitimage")
            if isinstance(bi, dict) and "b64" in bi and bi["dtype"] == "uint8":
                arr = np.frombuffer(base64.b64decode(bi["b64"]), dtype=np.uint8)
                if arr.size > 1 and arr.max() <= 1:
                    buf[part]["bitimage"] = {"packbits": base64.b64encode(np.packbits(arr)).decode(),
                                             "shape": bi["shape"], "n": int(arr.size)}
        buf["m"] = {k: buf["m"][k] for k in ("lastclock", "lastparticlecount")}
    return res


def decode(node: Any) -> Any:
    """Inverse of :func:`_plain` for arrays/scalars (dicts of fields stay dicts)."""
    if isinstance(node, dict) and "packbits" in node:
        bits = np.unpackbits(np.frombuffer(base64.b64decode(node["packbits"]), dtype=np.uint8))
        return bits[: node["n"]].reshape(node["shape"])
    if isinstance(node, dict) and "dtype" in node and ("b64" in node or "hex" in node):
        raw = base64.b64decode(node.get("b64") or node.get("hex"))
        return np.frombuffer(raw, dtype=np.dtype(node["dtype"])).reshape(node["shape"])
    if isinstance(node, dict) and "dtype" in node and "value" in node:
        return np.dtype(node["dtype"]).type(node["value"])
    if isinstance(node, dict):
        return {k: decode(v) for k, v in node.items()}
    return node


def run(fn: Path, first: int, last: int, timeout: int = 3600) -> dict[str, Any]:
    from scipy.io import readsav

    extra = {"erode.pro": _erode_shim(ERODE_EDGE_RULE), "uniq.pro": UNIQ_SHIM}
    with tempfile.TemporaryDirectory() as tmp:
        out, err = run_pro(_script(fn.as_posix(), tmp, first, last), timeout=timeout,
                           extra_files=extra)
        if "BANKDONE" not in out:
            raise RuntimeError(f"GDL bank did not finish:\nSTDOUT:\n{out[-3000:]}\nSTDERR:\n{err[-3000:]}")
        result: dict[str, Any] = {"gdl_stderr": err.strip()[-2000:]}
        result["index"] = _plain(readsav(os.path.join(tmp, "index.sav"))["y"])
        buffers = {}
        for name in sorted(os.listdir(tmp)):
            if name.startswith("buf_"):
                i = int(name[4:-4])
                s = readsav(os.path.join(tmp, name))
                buffers[str(i)] = {k: _plain(s[k]) for k in ("b", "x", "p", "m")}
        result["buffers"] = buffers
        if os.path.exists(os.path.join(tmp, "cip1d.sav")):
            result["cip1d"] = _plain(readsav(os.path.join(tmp, "cip1d.sav"))["cip1d"])
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--und", action="store_true")
    ap.add_argument("--driver", action="store_true",
                    help="run the whole soda2_process_2d driver (CIP-1 §1), not the "
                         "sub-function walk")
    ap.add_argument("--start", type=float, default=None, help="window start, s from midnight")
    ap.add_argument("--stop", type=float, default=None, help="window stop, s from midnight")
    args = ap.parse_args(argv)
    if args.driver:
        try:
            return run_driver()
        except GDLUnavailable as exc:
            print(exc, file=sys.stderr)
            return 2
    try:
        if args.und:
            root = local_data_root()
            fn = root / UND_REL
            if not fn.is_file():
                print(f"UND file not found at {fn}", file=sys.stderr)
                return 2
            from arrayprobe_soda2.buildindex import buildindex  # index in Python to pick buffers
            op = {"format": "SEA", "probetype": "CIP", "seatag": np.array([33000, 32000, 0]),
                  "fixedtas": np.float32(0), "timeoffset": np.float32(0)}
            y = buildindex(fn, op)
            sel = np.flatnonzero((y.bufftime >= args.start) & (y.bufftime <= args.stop))
            first = max(int(sel.min()) - 1, 0)
            last = int(sel.max()) + 1
            res = run(fn, first, last)
            res["window"] = [args.start, args.stop]
            out = root / LOCAL_GOLDEN_DIR / f"gdl_soda2_cip_und_{int(args.start)}_{int(args.stop)}.json"
            out.parent.mkdir(parents=True, exist_ok=True)
        else:
            res = run(FIXTURE, 0, 1000)
            out = GOLDEN
    except GDLUnavailable as exc:
        print(exc, file=sys.stderr)
        return 2
    out.write_text(json.dumps(_compact(res), sort_keys=True) + "\n", encoding="utf-8")
    scrub_output(out)  # path prefixes -> <repo>, <tmp>, ~
    print(f"wrote {out} ({out.stat().st_size} bytes); buffers {len(res['buffers'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# SPDX-License-Identifier: BSD-3-Clause
"""``arrayprobe reprocess <product> --preset NAME`` -- re-run a product's stage from its own stamp.

SODA-2's "Load Settings" (reprocessing from a saved options structure) is the model;
this project's ``.call`` sidecar (``run_flight.py``'s
``write_stamp``/``read_stamp``) already records how an S3 or S4 output was made. This closes the
loop: read the product's stamp, re-run the one stage that wrote it under exactly that
configuration, from the input the driver's own naming convention puts beside it, and report
whether the fresh output is identical to the product.

**Exactly as recorded, or refused.** The stamp is parsed only to *propose* a configuration
(engine, profile, the twelfth ``sizeDist`` argument, the diode mask, the aircraft file's name).
The proposal is then accepted only if ``run_flight``'s own label function, run under it, writes
the recorded stamp **character for character** -- the same equality test ``output_state`` makes
on every resume. So a profile whose thresholds moved since the stamp was written, a v3.5 call
switch that changed, an engine the stamp does not name, or a parse this module got wrong all end
in a refusal naming both strings, never in a run under a neighbouring configuration. The stage's
*input* is held to the same rule: an S4 reprocess needs a proc file whose own stamp matches
(``stage4``'s check, unchanged, with no ``accept_unstamped`` override); an S3 reprocess needs a
decoded image whose stamp is the one ``image_call_label`` would write. There is deliberately no
``--accept-unstamped`` here: an input of unknown configuration cannot be re-run "as recorded".

**What the stamp does not record, and what is asked for instead** (measured from
``config_label``/``sd_call_label``, 2026-09-14, not inferred):

* **the campaign preset** (probe, channel, project, ``d_choice``, ``sa_method``, pressure,
  temperature). No stamp carries it, so ``--preset`` is **required** -- never defaulted, the same
  rule ``arrayprobe run`` applies to ``[run].preset``. A wrong preset either fails the naming check
  (a channel that does not match the product's name) or shows up in the diff (``project`` is a
  written attribute; pressure and temperature reach the sd variables).
* **the aircraft TAS file's path** -- only its basename is stamped. S4 never reads the file, so the
  basename is enough to regenerate the label; S3 does read it, so ``--tas-file`` is required there
  and its basename must equal the stamped one.
* **a TAS source chain's sources** (``tas_chain=`` / ``tas_series=`` name the tier and the
  registered source, never a path), so the chain is not resolved again. What S3 and S4 consume is
  the series the chain wrote, ``<stem>.tas_<tier>.cdf`` beside the product, and that file is the
  input a chain product's reprocess reads -- for S3 in place of ``--tas-file``. Its own record of
  the chain and policy that wrote it must agree with the stamp; a missing file is refused by name.
* **the raw file** -- so S2 (decode) cannot be re-run from a stamp, and is refused rather than
  guessed at. Nor is S4c (combine): its stamp records the engine and the borrowed-combine opt-in
  but not the flight date or summary time the call needs.

**Which products.** ``proc.*.nc`` (S3, both engines; ``.diodecorrected.nc`` under v3.1.4 through
``stage3_corrected``) and ``sd.*.nc`` (S4, both engines).

**Identical means** every dimension, variable (name, order, type, dimensions, attributes, stored
bytes with masking and scaling off) and global attribute agrees, and the fresh ``.call`` text
equals the product's, with two exceptions, both the ones the existing byte-comparison tests make:
``Creation Time`` / ``Creation_Time`` is skipped (non-deterministic), and the
path-valued ``Image Source`` / ``Data Source`` / ``Data_Source`` are compared by **basename**
rather than skipped, because the fresh run necessarily reads from a different directory string
than the original may have, while a run that read the *wrong* file must still fail
(basenames are enough to tell files apart).

The driver is loaded as a **private copy per call**, never the shared ``sys.modules["run_flight"]``
that ``arrayprobe run`` and the tests bind to, so setting its globals from a stamp cannot leak into
anything else in the process, and every reprocess starts from the driver's module defaults rather
than whatever the last run left behind (``scripts/make_demo_reference.py``'s ``_load_tool_module``
records the incident that made this the rule).
"""
from __future__ import annotations

import argparse
import contextlib
import importlib.util
import itertools
import os
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

_TOOLS = Path(__file__).resolve().parent

#: Skipped outright: written from the clock, so it differs on every run.
VOLATILE_ATTRS = frozenset({"Creation Time", "Creation_Time"})

#: Compared by basename: a path the stage wrote from its own input argument.
PATH_ATTRS = frozenset({"Image Source", "Data Source", "Data_Source"})

#: A stamp's optional leading engine key. v3.5 stamps have carried it since 2026-09-13; v3.1.4
#: stamps since 2026-09-15. A stamp without it is v3.1.4, as
#: ``run_flight._stamps_equivalent`` reads it.
_ENGINE_KEY = re.compile(r"engine=(\S+) ")


class ReprocessRefused(ValueError):
    """The product cannot be re-run exactly as recorded; the message says why."""


# Kept as a name for the pre-2026-09-14 callers and tests.
StampFormatError = ReprocessRefused


@dataclass
class ReprocessResult:
    """What a reprocess found. ``differences`` is empty exactly when the fresh output is identical
    to the product under the rule in the module docstring."""

    product: Path
    stage: str
    engine: str
    stamp: str
    differences: list[str] = field(default_factory=list)

    @property
    def identical(self) -> bool:
        """True when the fresh output matched the product with no recorded difference."""
        return not self.differences


# --------------------------------------------------------------------------- the driver

_copies = itertools.count()


@contextlib.contextmanager
def _private_driver(log=None):
    """A fresh, private copy of ``scripts/run_flight.py`` at its module defaults.

    Registered in ``sys.modules`` under a private name only while it runs (a dataclass resolves its
    module there) and removed afterwards."""
    name = f"_reprocess_run_flight_{next(_copies)}"
    origin = importlib.util.find_spec("arrayprobe.driver.run_flight").origin
    spec = importlib.util.spec_from_file_location(name, origin)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
        module.log = log if log is not None else (lambda *a, **kw: None)
        yield module
    finally:
        sys.modules.pop(name, None)


# --------------------------------------------------------------------------- the stamp

def parse_stamp(text: str, stage: str) -> dict:
    """Propose the configuration a ``.call`` stamp names. A *proposal* only: :func:`reprocess`
    accepts it solely if ``run_flight`` regenerates ``text`` from it exactly.

    ``stage`` is ``"S3"`` (a proc stamp, ``proc_call_label``) or ``"S4"`` (an sd stamp,
    ``sd_call_label``). Raises :class:`ReprocessRefused` naming the field it could not find."""
    from arrayprobe_uiops import provenance

    text = text.strip()
    key = _ENGINE_KEY.match(text)
    engine = key[1] if key else "3.1.4"
    # Each key's value runs to the start of the next key (provenance's reader, shared with every
    # other stamp consumer), so a value never swallows the keys written after it.
    parsed = provenance.parse(text)
    fields = dict(parsed.fields) if parsed.format == "driver" else {}
    # Neither engine= nor port_validation= (R4) is part of the stage's own key order:
    # an sd stamp now reads ``engine=3.1.4 port_validation=on iat_file=...``.
    keys = [k for k in fields if k not in ("engine", "port_validation")]
    iat_file = None
    if stage == "S4":
        if not keys or keys[0] != "iat_file" or keys[1:2] != ["profile"]:
            raise ReprocessRefused(f"not an sd stamp (no leading iat_file=...): {text!r}")
        iat_file = None if fields["iat_file"] == "<none>" else fields["iat_file"]
    elif keys[:1] == ["iat_file"]:
        raise ReprocessRefused(f"an sd stamp where a proc stamp was expected: {text!r}")
    profile, shadow = fields.get("profile"), fields.get("shadow_diode")
    if not profile or not shadow:
        raise ReprocessRefused(f"stamp names no profile= / shadow_diode=: {text!r}")
    # A TAS chain names itself as tas_chain= (a profile that reads an aircraft file) or, in an sd
    # stamp, as tas_series=; tas_series=probe_hk:... is a different mechanism (the CIP borrowing
    # the 2D-S's airspeed), not a chain.
    chain = fields.get("tas_chain")
    series = fields.get("tas_series")
    if chain is None and series is not None and not series.startswith("probe_hk:"):
        chain = series
    policy = fields.get("tas_policy", fields.get("tas_series_policy"))
    return {
        "engine": engine,
        "port_validation": fields.get("port_validation") == "on",
        "iat_file": iat_file,
        "profile_name": profile,
        "shadow_diode": None if shadow == "none" else [int(x) for x in shadow.split(",")],
        "tas_file_name": fields.get("tas_file"),
        "tas_chain": chain,
        "tas_policy": policy[1:-1] if policy and policy[0] == "(" and policy[-1] == ")" else policy,
        "tas_grid": fields.get("tas_grid"),
        # The stray-pixel rule: a v3.5 stamp names stray_pixel=on:<params> or stray_pixel=off; a
        # v3.5 stamp written before the correction carries no key and was made uncorrected (None
        # here, regenerated as off). Only the on/off switch is restored; the parameters are the
        # driver's own, so a stamp recording other parameters fails the regeneration check.
        "stray_pixel": fields.get("stray_pixel"),
        # The NCAR 2DC timing conversion, the same way: a v3.5 probetype-0 stamp names
        # ncar_2dc_timing=on:fix2dimage or ncar_2dc_timing=off; no key reads as off.
        "ncar_2dc_timing": fields.get("ncar_2dc_timing"),
    }


def parse_sd_stamp(text: str) -> dict:
    """:func:`parse_stamp` for an S4 stamp (the pre-2026-09-14 name, kept)."""
    return parse_stamp(text, "S4")


def stage_of(product: Path) -> str:
    """``"S3"`` for ``proc.*``, ``"S4"`` for ``sd.*``; anything else is refused by name."""
    if product.name.startswith("proc."):
        return "S3"
    if product.name.startswith("sd."):
        return "S4"
    raise ReprocessRefused(
        f"{product.name}: only a proc.* (S3) or sd.* (S4) product can be reprocessed from its "
        "stamp -- an S2 stamp does not record the raw file, and an S4c stamp does not record the "
        "flight date or summary time its call needs")


def proc_path_for(sd_path: Path) -> Path:
    """The proc file an sd file's own name says sits beside it (``run_flight.sd_path``'s
    convention, read in the other direction)."""
    if not sd_path.name.startswith("sd."):
        raise ReprocessRefused(f"{sd_path.name} does not start with 'sd.'")
    return sd_path.with_name("proc." + sd_path.name.removeprefix("sd."))


# --------------------------------------------------------------------------- the diff

def _attr_equal(a, b) -> bool:
    if isinstance(a, str) or isinstance(b, str):
        return isinstance(a, str) and isinstance(b, str) and a == b
    aa, bb = np.asarray(a), np.asarray(b)
    return aa.dtype == bb.dtype and aa.shape == bb.shape and aa.tobytes() == bb.tobytes()


def _basename(value) -> str:
    return os.path.basename(str(value).replace("\\", "/"))


def _diff_attrs(where: str, a, b, out: list[str]) -> None:
    names_a, names_b = list(a.ncattrs()), list(b.ncattrs())
    if names_a != names_b:
        out.append(f"{where}: attribute names/order differ: {names_a} vs {names_b}")
        return
    for key in names_a:
        if key in VOLATILE_ATTRS:
            continue
        va, vb = a.getncattr(key), b.getncattr(key)
        if key in PATH_ATTRS:
            if _basename(va) != _basename(vb):
                out.append(f"{where}@{key}: input basename differs: {va!r} vs {vb!r}")
        elif not _attr_equal(va, vb):
            out.append(f"{where}@{key}: {va!r} vs {vb!r}")


def _diff_group(where: str, a, b, out: list[str]) -> None:
    dims_a = [(n, len(d), d.isunlimited()) for n, d in a.dimensions.items()]
    dims_b = [(n, len(d), d.isunlimited()) for n, d in b.dimensions.items()]
    if dims_a != dims_b:
        out.append(f"{where}: dimensions differ: {dims_a} vs {dims_b}")
    _diff_attrs(where or "<global>", a, b, out)
    vars_a, vars_b = list(a.variables), list(b.variables)
    if vars_a != vars_b:
        out.append(f"{where}: variable names/order differ: "
                   f"only fresh {sorted(set(vars_a) - set(vars_b))}, "
                   f"only product {sorted(set(vars_b) - set(vars_a))}")
    for name in (n for n in vars_a if n in b.variables):
        va, vb = a.variables[name], b.variables[name]
        label = f"{where}/{name}"
        if va.dtype != vb.dtype or va.dimensions != vb.dimensions or va.shape != vb.shape:
            out.append(f"{label}: definition differs: {va.dtype} {va.dimensions} {va.shape} vs "
                       f"{vb.dtype} {vb.dimensions} {vb.shape}")
            continue
        _diff_attrs(label, va, vb, out)
        va.set_auto_maskandscale(False)
        vb.set_auto_maskandscale(False)
        ra = np.ascontiguousarray(va[...])
        rb = np.ascontiguousarray(vb[...])
        if ra.tobytes() != rb.tobytes():
            n = int(np.count_nonzero(ra != rb)) if ra.shape == rb.shape else -1
            out.append(f"{label}: stored values differ ({n} element(s))")
    groups_a, groups_b = list(a.groups), list(b.groups)
    if groups_a != groups_b:
        out.append(f"{where}: groups differ: {groups_a} vs {groups_b}")
    for g in (g for g in groups_a if g in b.groups):
        _diff_group(f"{where}/{g}", a.groups[g], b.groups[g], out)


def content_differences(fresh: Path, product: Path) -> list[str]:
    """Every way ``fresh`` differs from ``product`` under the module docstring's rule; ``[]`` when
    identical. The file format is compared too (NETCDF3_CLASSIC is part of the output contract)."""
    import netCDF4

    out: list[str] = []
    with netCDF4.Dataset(str(fresh)) as a, netCDF4.Dataset(str(product)) as b:
        if a.data_model != b.data_model:
            out.append(f"file format differs: {a.data_model} vs {b.data_model}")
        _diff_group("", a, b, out)
    return out


# --------------------------------------------------------------------------- reprocess

def reprocess(product, *, preset: str, tas_file=None, log=None) -> ReprocessResult:
    """Re-run the stage that wrote ``product`` under its recorded configuration and diff.

    Raises :class:`ReprocessRefused` (or ``run_flight.UnverifiableProvenance`` from the stage's
    own input check) when the product cannot be re-run exactly as recorded."""
    product = Path(product).resolve()
    stage = stage_of(product)
    if not product.is_file():
        raise ReprocessRefused(f"{product} is not a file")

    with _private_driver(log) as drv:
        stamp = drv.read_stamp(product)
        if stamp is None:
            raise ReprocessRefused(
                f"{product.name} has no .call sidecar; with no recorded configuration there is "
                "nothing to reprocess it from")
        cfg = parse_stamp(stamp, stage)

        if preset not in drv.PRESETS:
            raise ReprocessRefused(f"unknown preset {preset!r}; the driver knows "
                                   f"{', '.join(sorted(drv.PRESETS))}")
        drv.use_preset(preset)
        drv.ENGINE = cfg["engine"]
        # A stamp that records port_validation=on is regenerated with it on, so the comparison
        # below sees the token and the fresh product carries it; a stamp from before R4 has none.
        drv.PORT_VALIDATION = cfg["port_validation"]
        # The stray-pixel switch is part of the recorded configuration (ON by default for engine
        # 3.5 since 2026-10-03), so it is restored from the stamp rather than left at the private
        # driver's import-time False, which refused every default v3.5 product.
        drv.STRAY_PIXEL = (cfg["engine"] == "3.5" and cfg["stray_pixel"] is not None
                           and cfg["stray_pixel"].startswith("on"))
        # The NCAR 2DC timing switch (ON by default for engine 3.5 2DC/2DP since 2026-10-07),
        # restored from the stamp for the same reason.
        drv.NCAR_2DC_TIMING = (cfg["engine"] == "3.5" and cfg["ncar_2dc_timing"] is not None
                               and cfg["ncar_2dc_timing"].startswith("on"))

        from arrayprobe.profiles import PROFILES
        if cfg["profile_name"] not in PROFILES:
            raise ReprocessRefused(
                f"the stamp names profile {cfg['profile_name']!r}, which is not registered in "
                "this process (a register_profile() variant has to be imported first)")
        drv.PROFILE = PROFILES[cfg["profile_name"]]

        raw_stem = product.name.split(".")[1]
        chain_file = None
        if cfg["tas_chain"] is not None:
            chain_file = _restore_chain(drv, product, raw_stem, cfg)
            if tas_file is None and stage == "S3" and cfg["tas_file_name"] is not None:
                # The chain's own output is the aircraft file S3 read; it sits beside the
                # product by the driver's naming convention, so it need not be named.
                tas_file = chain_file

        stamped_tas = cfg["tas_file_name"]
        if stage == "S3" and stamped_tas is not None:
            if tas_file is None:
                raise ReprocessRefused(
                    f"{product.name} was framed with aircraft file {stamped_tas} (stamped by "
                    "name only); S3 reads it, so pass --tas-file")
            tas_path = Path(tas_file).resolve()
            if tas_path.name != stamped_tas:
                raise ReprocessRefused(f"--tas-file {tas_path.name} is not the stamped "
                                       f"{stamped_tas}")
            if not tas_path.is_file():
                raise ReprocessRefused(f"--tas-file {tas_path} does not exist")
            drv.TAS_FILE = str(tas_path)
        elif tas_file is not None:
            why = ("no aircraft file is stamped" if stamped_tas is None
                   else "S4 never reads the aircraft file")
            raise ReprocessRefused(f"--tas-file given, but {why} for {product.name}; drop it "
                                   "rather than carry an input the run ignores")
        else:
            # S4: the file is never read; only its stamped name enters the label.
            drv.TAS_FILE = stamped_tas

        shadow = cfg["shadow_diode"]
        if stage == "S4":
            want = drv.sd_call_label(cfg["iat_file"], shadow_diode=shadow)
        else:
            want = drv.proc_call_label(shadow_diode=shadow)
        if not drv._stamps_equivalent(stamp, want):
            raise ReprocessRefused(
                f"{product.name} cannot be re-run as recorded: under the configuration its stamp "
                f"names, this driver would stamp\n  {want}\nbut the product records\n  {stamp}")

        expected = (drv.sd_path if stage == "S4" else drv.proc_path)(
            raw_stem, product.parent, shadow)
        if expected.name != product.name:
            raise ReprocessRefused(
                f"under preset {preset} this product would be named {expected.name}, not "
                f"{product.name} -- the preset's channel or the diode mask does not match")

        with tempfile.TemporaryDirectory(prefix="reprocess_") as tmp:
            out_dir = Path(tmp)
            try:
                if stage == "S4":
                    fresh = _rerun_s4(drv, product, raw_stem, out_dir, cfg)
                else:
                    fresh = _rerun_s3(drv, product, raw_stem, out_dir, shadow)
            except drv.UnverifiableProvenance as exc:
                # The stage's own input check (stage4's proc-stamp test), unchanged.
                raise ReprocessRefused(str(exc)) from exc
            differences = content_differences(fresh, product)
            fresh_stamp = drv.read_stamp(fresh)
            if fresh_stamp is None or not drv._stamps_equivalent(stamp, fresh_stamp):
                differences.append(f".call: fresh {fresh_stamp!r} vs product {stamp!r}")
        return ReprocessResult(product, stage, cfg["engine"], stamp, differences)


def _restore_chain(drv, product: Path, raw_stem: str, cfg) -> Path:
    """Put the TAS chain a product was made under back into the private driver, from the chain's
    own output file beside the product (``<stem>.tas_<tier>.cdf``, the name ``run_flight`` gives
    it). Returns that file's path.

    The chain is not re-resolved: its sources (a merge or aircraft file) are recorded by name
    only, never by path. What S3 and S4 consume is the series the chain wrote -- S3 reads that
    file as its aircraft file, S4 sizes on the same ``Time``/``TAS`` values -- so re-running either
    stage needs that file and nothing upstream of it. The file's own record of which chain and
    policy wrote it must agree with the stamp, or the run is refused."""
    import netCDF4

    from arrayprobe.tools import make_tas_file, tas_sources

    chain = cfg["tas_chain"]
    tier, _, source = chain.partition(":")
    if tier not in tas_sources.TIERS or not source:
        raise ReprocessRefused(f"the stamp names TAS chain {chain!r}, which is not "
                               f"<tier>:<source> with a tier in {tas_sources.TIERS}")
    path = product.parent / f"{raw_stem}.tas_{tier}.cdf"
    if cfg["tas_file_name"] is not None and cfg["tas_file_name"] != path.name:
        raise ReprocessRefused(
            f"the stamp names aircraft file {cfg['tas_file_name']} and TAS chain {chain}, whose "
            f"output the driver writes as {path.name}; they disagree")
    if not path.is_file():
        raise ReprocessRefused(
            f"{product.name} was sized on TAS chain {chain}, and re-running it needs "
            f"{path.name} (the series that chain wrote) beside it. The chain cannot be resolved "
            "again here: its sources are recorded by name only, not by path")
    try:
        policy = (make_tas_file.TasPolicy.parse(cfg["tas_policy"]) if cfg["tas_policy"]
                  else make_tas_file.TasPolicy())
    except (KeyError, ValueError) as exc:
        raise ReprocessRefused(f"the stamp's TAS policy {cfg['tas_policy']!r} does not parse: "
                               f"{exc}") from exc
    with netCDF4.Dataset(str(path)) as ds:
        attrs = {k: ds.getncattr(k) for k in ds.ncattrs()}
        t_var, v_var = (ds.variables[make_tas_file.TIME_VARIABLE],
                        ds.variables[make_tas_file.TAS_VARIABLE])
        t_var.set_auto_maskandscale(False)
        v_var.set_auto_maskandscale(False)
        time = np.asarray(t_var[:], dtype=np.float64)
        tas = np.asarray(v_var[:], dtype=np.float64)
    for attr, want in (("tas_chain_used", chain), ("tas_policy", policy.token())):
        got = attrs.get(attr)
        if got != want:
            raise ReprocessRefused(f"{path.name} records {attr}={got!r}, but "
                                   f"{product.name}'s stamp names {want!r}")
    drv.TAS_POLICY = policy
    drv.TAS_GRID = cfg["tas_grid"] or "probe"
    drv.TAS_CHAIN = tas_sources.ChainResult(
        mode=str(attrs.get("tas_chain_mode", tier)), tier=tier, source=source, path=str(path),
        time=time, tas=tas, policy=policy, steps=[], substituted=[], lines=[], provenance=attrs)
    return path


def _rerun_s4(drv, product: Path, raw_stem: str, out_dir: Path, cfg) -> Path:
    proc = drv.proc_path(raw_stem, product.parent, cfg["shadow_diode"])
    tas_csv = product.parent / f"{raw_stem}.tas.csv"
    for need, what in ((proc, "the proc file S4 reads"), (tas_csv, "S2's TAS sidecar")):
        if not need.is_file():
            raise ReprocessRefused(f"{product.name} needs {need.name} ({what}) beside it")
    # stage4 reads the TAS sidecar from its own output directory.
    shutil.copy2(tas_csv, out_dir / tas_csv.name)
    # The TAS QC sidecar (<sd>.tasqc.json) is not part of the diff and lands in the discarded
    # temporary directory, but building it opens the aircraft file, which the stamp names by
    # basename only -- so every v3.5 re-run printed "S4 TAS QC record not written: cannot read
    # <name>", a warning about a file the product never needed (cold-user walk, 2026-09-26).
    # This is a private copy of the driver, so the override ends with it. Engine 3.5 also
    # writes the record INTO the sd file, so the re-run carries the record the user's
    # run wrote beside the product rather than none -- otherwise every v3.5 re-run differed from
    # its original by exactly those attributes.
    from arrayprobe.tools import tas_sources
    recorded = tas_sources.read_qc_sidecar(product)
    drv._tas_qc_record = lambda *_a, **_k: recorded
    fresh = drv.stage4(proc, raw_stem, out_dir, iat_file=cfg["iat_file"],
                       shadow_diode=cfg["shadow_diode"], accept_unstamped=False)
    if not fresh.is_file():
        raise ReprocessRefused(f"S4 wrote no {fresh.name}")
    return fresh


def _rerun_s3(drv, product: Path, raw_stem: str, out_dir: Path, shadow) -> Path:
    image = drv.image_path(raw_stem, product.parent)
    if not image.is_file():
        raise ReprocessRefused(f"{product.name} needs {image.name} (the decoded image S3 reads) "
                               "beside it")
    image_want = drv.image_call_label()
    image_got = drv.read_stamp(image)
    # The raw-input inventory keys S2 appends describe the input, not the configuration
    # (run_flight._strip_inventory, the driver's own rule).
    if image_got is None or drv._strip_inventory(image_got) != image_want:
        raise ReprocessRefused(
            f"{image.name} is {'unstamped' if image_got is None else f'stamped {image_got!r}'}, "
            f"but S3 under this configuration reads an image stamped {image_want!r}")
    if shadow:
        fresh = drv.stage3_corrected(image, out_dir, accept_unstamped=False)
        if fresh is None:
            raise ReprocessRefused(f"no registered diode override for {raw_stem}")
    else:
        fresh = drv.stage3(image, out_dir, chunks=1, accept_unstamped=False)
    if not fresh.is_file():
        raise ReprocessRefused(f"S3 wrote no {fresh.name}")
    return fresh


# --------------------------------------------------------------------------- command line

def run(args: argparse.Namespace) -> int:
    """``arrayprobe reprocess``'s handler body (the argument surface is ``arrayprobe.cli``'s, the
    one place it is declared). 0 identical, 1 differs, 2 refused -- the meanings ``arrayprobe
    compare`` gives 0/1/2."""
    from arrayprobe import __version__

    def log(msg: str) -> None:
        print(f"  {msg}", file=sys.stderr, flush=True)

    try:
        result = reprocess(args.product, preset=args.preset, tas_file=args.tas_file, log=log)
    except ReprocessRefused as exc:
        print(f"reprocess: REFUSED -- {exc}", file=sys.stderr)
        return 2
    print(f"product : {result.product}")
    print(f"stage   : {result.stage}, UIOPS {result.engine} engine, arrayprobe {__version__}")
    print(f"stamp   : {result.stamp}")
    if result.identical:
        print("result  : IDENTICAL (every dimension, variable and attribute; Creation Time "
              "skipped, source paths compared by basename)")
        return 0
    print(f"result  : DIFFERS in {len(result.differences)} place(s)")
    for line in result.differences:
        print(f"  {line}")
    return 1


def main(argv=None) -> int:
    """A shim onto ``arrayprobe reprocess``: one
    argument surface, so the script and the subcommand cannot drift apart."""
    from arrayprobe.cli import main as cli_main
    return cli_main(["reprocess", *(sys.argv[1:] if argv is None else argv)])


if __name__ == "__main__":
    raise SystemExit(main())

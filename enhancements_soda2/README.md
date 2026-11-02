# arrayprobe-soda2-enhancements

Opt-in corrections for findings against `arrayprobe_soda2` (NCAR SODA-2's Python port) --
never part of the faithful port itself. The SODA-2 counterpart of `enhancements_uiops/`
(`arrayprobe-uiops-enhancements`, for UIOOPS): same registry mechanism, same one-way dependency
(this package imports `arrayprobe_soda2`, never the reverse), same opt-in convention.
SODA-2 and UIOOPS are separate lineages with separate licences
(SODA-2 is BSD-3, UCAR 2016) and separate maintainers, so this is its own distribution rather
than a subpackage of `arrayprobe_enhancements` (the import name of
`arrayprobe-uiops-enhancements`) -- see `enhancements_soda2/tests/test_lineage_isolation.py`.

To use it:

```bash
python -m pip install arrayprobe-soda2-enhancements
```

**Applying the corrections to a run.** Every correction is opt-in -- name it `true` in the
config's `[enhancements]` table -- except the five in `registry.PROTECTIVE`, the corrections
for data-destroying upstream defects (`no_stuck_diode_fix`, `last_buffer_index_fix`,
`same_time_buffer_fix`, `pbp_rejectionflag_ubyte`, `dilation_clamp_fix`). SODA-2 has written no
archived product for any probe, so `arrayprobe soda2 run` applies those by default; name one `false`, or pass `--protective off`, to opt out. The `.pbp.call` sidecar
records the protective mode and set. Each module's reason: `BACKLOG_STATUS.md`.

```python
from arrayprobe_soda2.process_2d import soda2_process_2d
from arrayprobe_soda2_enhancements.registry import PROTECTIVE, apply, load_all, resolve

load_all()                                        # registration is an import side effect
with apply(resolve({"double_pi_fix": True}, protective=PROTECTIVE)) as record:
    data = soda2_process_2d(op)
record["applied"], record["skipped"]              # what reached the driver, and what did not
```

`apply` substitutes corrections at named bindings the port exposes in
`arrayprobe_soda2.enhancement_hooks` (the port never imports this package), and restores them
on exit. 14 of the 19 corrections reach the driver this way; the other five, and why, are listed
in `BACKLOG_STATUS.md`. With every correction OFF the run is byte-identical to the port.

Which findings ship here and why:
`BACKLOG_STATUS.md`. Corrections not shipped, each with what unblocks it: `docs/DEFERRED.md`.
Per-module design notes: `docs/CORRECTIONS.md`.

## From a clone

Contributors working from a checkout of the repository install it into the root package's
existing venv instead (a build-convenience choice, not a boundary one):

```bash
# Linux / macOS: .venv/bin/python in place of .venv/Scripts/python.exe
.venv/Scripts/python.exe -m pip install -e enhancements_soda2
cd enhancements_soda2
../.venv/Scripts/python.exe -m unittest discover -s tests -p "test_*.py"
```

SODA-2 is cited in the form its author, Aaron Bansemer, provided:

> Aaron Bansemer. (2026). abansemer/soda2: v2.26.0 (Version v2.26.0) [Computer software]. Zenodo. https://doi.org/10.5281/zenodo.18331418

# Enhancement registry — config-file reachability, **opt-in, default OFF**

**Status: all forty-two modules registered, each carrying `stage`/`consumes` fields; the
ratchet (`_NOT_YET_REGISTERED`) is empty.** Built 2026-09-10; completed in batches through
2026-09-14. Code: `enhancements_uiops/src/arrayprobe_enhancements/registry.py`. Checks:
`enhancements_uiops/tests/test_enhancement_registry.py`,
`enhancements_uiops/tests/test_enhancement_opt_in.py`.

> **The default was flipped from opt-out to opt-in 2026-09-16, and §2–§3 below record the reasoning that was
> superseded rather than pretending it never held.** From 2026-09-10 to that date
> this registry resolved an unmentioned enhancement **ON**, opt-out by name, on the argument
> in §2 that the default belongs to the pipeline you invoked. A cold-start usability audit
> measured what that meant to a user: a config whose only entry was `outoffocus = false`
> resolved **31 of 40** modules ON under the default v3.5 engine and applied four of them,
> two of which change numbers — while `README.md`, the enhancements page and
> the example configuration's own comment all said opt-in, and the inversion was stated
> in one inline comment on one page. The flip was approved on that measurement.
> **One TOML file means one thing to both drivers: an enhancement is ON only where a key
> names it `true`.** `arrayprobe_enhancements.pipeline` additionally refuses a config with no
> `[enhancements]` section rather than guessing, and prints the resolved-ON set on every run.

Supersedes §5's first open decision in
[`config_file_design.md`](config_file_design.md) — read that document for the config
file's overall inventory and precedence rules, which are unchanged. §1's "Enhancements
default OFF" bullet there stands again, unmodified.

## 1. The instruction

User-directed 2026-09-10:

> *"the impact of the enhancements will need to be demonstrated with impact on data. all of
> them will have to be in config file as an opt in as default but option for opt out."*

Two requirements. This document covers the second (config-file reachability by name; see §3a
for how the default was read then and is read now). **The first — demonstrated impact on real data for every module — is
tracked separately**; `docs/applicability_matrix.md` is where a module's measured effect on
production output is recorded, and the modules still lacking one are the audit that the same
instruction also calls for.

## 2. The problem this had to solve

The instruction says *default on*. The port says *never default on*:

- The rule for the port — "Any behaviour-changing deviation is an **opt-in flag,
  defaulting OFF**, with a test for both states."
- `arrayprobe.config.RunConfig.enabled()` — *"Default-off is the contract, not a
  convenience: an enhancement changes what the port computes away from the MATLAB, so it
  must be opted into by name."*
- `tests/test_no_enhancement_coupling.py` — `arrayprobe` may never import
  `arrayprobe_enhancements`, so the core cannot even discover what enhancement names exist,
  let alone default them on.

A naive reading — flip `enabled()` to default-true — would invalidate the
reproduction of the archived product that every other claim in this project rests on, because a
run with no config file would silently stop reproducing UIOOPS.

## 3. The decision, 2026-09-10 to 2026-09-16 — **superseded, recorded**

The reading then was that *the default belongs to the pipeline, not the file*:

| You invoked | Unmentioned enhancement | Why |
|---|---|---|
| the port (`arrayprobe`, `scripts/run_flight.py`) | **off** | it is a bug-for-bug reproduction; a correction switching itself on would break the reproduction |
| this package (`arrayprobe_enhancements`) | **on** | installing and calling into it is the opt-in; having opted in, you want the corrections |

Choosing the enhanced pipeline was taken to *be* the opt-in the fidelity doctrine requires.

**Why that was wrong, measured rather than argued.** The step it skipped is that a user does
not invoke a pipeline in the abstract — they write a file, and the file is what they read
back to see what they asked for. Two consequences the audit hit:

- **One line does not mean one thing.** `outoffocus = false` as the sole entry reads, to
  anyone, as "one module, off". It resolved 31 of 40 ON and applied four.
- **Nothing fails.** Every other finding in that audit is recoverable by reading harder. This
  one is not, because reading harder confirmed the wrong belief: four public surfaces said
  opt-in, and only one inline comment said otherwise.

## 3a. The decision — opt-in, in both pipelines

| You invoked | Unmentioned enhancement | Named `true` |
|---|---|---|
| the port (`arrayprobe`, `scripts/run_flight.py`) | **off** | still off — the port applies no enhancement at all |
| this package (`arrayprobe_enhancements`) | **off** | **on**, and only then |

The instruction's first half ("in config file as an opt in as default") is honoured by *reachability*:
every one of the forty-two modules is nameable from a config file, which is what the ratchet in
`test_enhancement_registry.py` exists to guarantee. Its second half ("option for opt out") is
subsumed: under opt-in, `false` and silence agree, so a user can always express either.
The later per-module ON defaults (`published_dof`, `reaccept_every_event_fix`) are superseded
with it — its operative half, *"users should be able to specify individual ones … to isolate
impact of each of them"*, is the only way any module runs.

Two mechanisms carry the decision beyond the default itself, because a default alone is a
rule and not a control:

- `pipeline.require_enhancement_policy` **refuses** a config with no `[enhancements]` section.
  Absent is not silently read as "off" either; the file is asked to say. An empty table is the
  explicit way to say "the port, unmodified".
- `pipeline.format_resolution` **prints every ON module by name** before the run starts, and
  the applied/skipped set afterwards. A count would have read as agreeing with "opt-in"; the
  names cannot.

`test_enhancement_opt_in.py` pins all three, and was measured failing against the old
behaviour (9 of its 16 tests) before the flip landed.

`test_enhancement_registry.test_the_port_and_this_package_agree_about_the_default` pins both
halves on one loaded config, so the two can only ever diverge again on purpose.

### What this costs the port: one boolean, and no computed number

`RunConfig.enhancements` already carried the raw `[enhancements]` table verbatim, and the
core's own docstring already delegated interpretation: *"validating them is the enhancements
package's job, and refusing here would couple the two in the direction
`test_no_enhancement_coupling.py` forbids."* This registry is that job.

The one core addition, 2026-09-16, is `RunConfig.enhancements_declared` — whether the file
carried an `[enhancements]` section *at all*, distinct from carrying an empty one. The loader
is the only place that still knows the difference, and it threw it away. The port does not use
it (absent and empty mean the same thing there), it selects nothing and computes nothing; it
exists so `pipeline.require_enhancement_policy` can refuse rather than guess. The dependency
arrow is unchanged — `arrayprobe_enhancements` → `arrayprobe`, never the reverse, and
`test_no_enhancement_coupling.py` still passes.

### Alternatives rejected

| Alternative | Why not |
|---|---|
| Flip `RunConfig.enabled()` to default-true | Breaks the reproduction: `run_flight.py` with no config would stop reproducing UIOOPS. Also requires the core to know the enhancement name list, which it cannot. |
| A `[enhancements] all = true` master switch in the core | Same problem one level up — the core still cannot enumerate what "all" means, so it could not report what was applied, and the misreported shattering attribute is precisely about outputs that cannot say what call made them. |
| Entry-point/plugin discovery (`importlib.metadata`) | Makes the registry contents depend on what happens to be pip-installed, so the same config resolves differently in two environments. A declarative table diffed against the files on disk is checkable; a discovery mechanism is not. |
| Each module calls `register()` at import | `resolve()` would then return different answers depending on import order — an enhancement unmentioned by a config would be "off" purely because nothing had imported it yet. |

## 4. The mechanism

```toml
[enhancements]          # every registered enhancement is ON unless named here
wide_hollow_fix = false # opt out of this one
```

```python
from arrayprobe.config import load_config
from arrayprobe_enhancements.registry import resolve_from_config, entry_point

cfg = load_config("run.toml")
on = resolve_from_config(cfg)        # {"wide_hollow_fix": False, "spot_edge_fix": True, ...}
if on["spot_edge_fix"]:
    correct = entry_point("spot_edge_fix")
```

- `EnhancementSpec(name, summary, finding, default_on, entry_point)` — `name` is both the
  config key and the module stem, deliberately the same string so the table and the
  filesystem compare directly rather than through a mapping that could itself drift.
- `resolve()` returns a decision for **every** registered enhancement, not only the
  mentioned ones, so a driver reads one complete answer rather than re-deriving defaults.
- **An unknown name raises.** The core returns `False` for a name it has not heard of
  (correct — it cannot know). Here a typo'd `wide_hollow_fx = true` is an error, because an
  ignored line means the file says something the run did not do: under opt-in the correction
  silently does not happen while whoever ran it believes they asked for it, and under the old
  default-on it silently kept happening. Either way this is the main reason the resolution
  step exists rather than a bare `dict.get`.

## 5. What is wired, and what remains

**Registered (40, complete):** every shipped module carries an `EnhancementSpec`, each with
`stage` (`"proc"` / `"sd"` / `"product"` / `"reader"` / `"none"`) and `consumes` (the real
netCDF variables or files the entry point needs) fields beyond the original four (`wide_hollow_fix`
(the diode-32 hollow test), `spot_edge_fix` (the missing decimal in spot_edge), `dmax_sensitivity`, `md_relations`) this document first shipped with.
`_NOT_YET_REGISTERED` in `test_enhancement_registry.py` is **empty** — the ratchet did its job
and stayed shrinking to zero rather than growing back. `TheRegistryMatchesTheModulesOnDisk`
still asserts both directions: every module on disk is registered, and no registry entry names a
module that is not.

**A driver consumes `resolve()`.** §6 item 5 below was the honest gap this document shipped
with; `enhancements_uiops/src/arrayprobe_enhancements/pipeline.py`'s `resolve_for_run` (a thin call onto
`registry.resolve_from_config`) runs first in `apply_enhancements`, before any adapter — so the
driver in the gap this section used to describe is `pipeline.py`, not a future step. §7 covers
which resolved-ON modules the driver can actually *apply* to a file, which is a narrower question
than resolution.

## 6. Test obligations, and which are met

Carried forward from `config_file_design.md` §4, restated for opt-in (2026-09-16):

1. ✅ A config naming nothing leaves the **port** byte-identical — unchanged, the port's
   default is untouched and `RunConfig.enabled()` still returns `False`.
2. ✅ Every registered enhancement is **off** until a config names it `true`, and each is
   individually selectable — `ResolutionIsOptIn`, and `test_enhancement_opt_in.py`, whose
   `NothingIsOnByDefault` also asserts that no spec claims a `default_on=True` exemption.
3. ✅ The registry agrees with the modules on disk, both directions, with a shrinking
   ratchet, now empty — `TheRegistryMatchesTheModulesOnDisk`.
4. ✅ `arrayprobe` still never imports this package —
   `test_no_enhancement_coupling.py`, unchanged and still passing.
5. ✅ The resolved set is written into the output's provenance stamp. Met by
   `pipeline.py`'s `<sd>.enhancements.json` sidecar (recording, per module, whether it resolved
   on, was applied, or was skipped and why) and `tests/test_pipeline_provenance.py` — which is
   the misreported shattering attribute's own complaint about the MATLAB, answered on the enhanced side.

All three load-bearing checks were **mutation-tested** when written: dropping a module from
the ratchet, flipping the default to off, and silently ignoring unknown names each made the
suite fail, and each was restored, because a check that passes without being able to fail
tests nothing.

## 7. Registration is not the same as a driver adapter (2026-09-14)

Being registered (§5) makes a module selectable by name and visible in the
`<sd>.enhancements.json` sidecar. It does not by itself let `arrayprobe-enhanced run` *apply* the
module to a file: that needs an entry in `pipeline.py`'s `_APPLIERS`, a function that copies the
port's `proc`/`sd`/product output and writes the corrected version. **13 of 42 modules have one
today.** The rest resolve ON but are recorded as a named skip in the sidecar, with the reason
naming *why* rather than a generic placeholder wherever one has been written.

| Has an adapter (`_APPLIERS`) | Named "no adapter" reason (`_NO_ADAPTER_REASON_BY_NAME`) | Reader-stage (decode already ran) | No file stage (`stage="none"`) | Registered, no adapter, generic reason |
|---|---|---|---|---|
| `hole_edge_swap`, `particle_number_all_fix`, `particle_time_glitch_fix`, `int_arr_rollback_fix`, `particle_time_int8_fix`, `outoffocus`, `overload_accounting_fix`, `published_dof`, `pressure_units_fix`, `arco_export` | `arm_export` (needs `[arm]` ids), `cf_export` (needs the flight date, not in the config), `dmax_sensitivity` (reports, writes no corrected file), `spot_edge_fix` (needs `area_ratio`, not a stored column), `wide_hollow_fix` (needs a reconstructed image), `rollover_fix` (in-memory time-array correction), `tas_grid_fix` (needs a run pressure not recoverable from the `.call` stamp, same gap as `pressure_units_fix`), `effective_density` (needs `area_ratio`), `distance_rejection` (needs `tas`/`threshold_distance`), `poisson_restore` (needs `false_rejection_fraction`), `analysis`, `poisson_uncertainty`, `ml_accept_reject`, `spec_artefact_filter` (analyses, write no corrected file), `probe_crossover` (compares two probes' files; a run processes one), `particle_clustering` (writes a labels sidecar, not a corrected proc/sd file; whether enhanced run runs analyses asks whether the driver should run analyses at all) | `pms_c6_routing_fix`, `last_record_fix` (`_READER_REASON` — correct the decode step, which already ran by the time a proc/sd pair exists; reader-stage enhancements in the driver records that `arrayprobe run` can accept a pre-existing image file for stages 3+, so a `--reader` option is mechanically reachable but not built) | `md_relations`, `probe_uncertainty` (`_NO_STAGE_REASON` — a lookup table / reference envelope, not a file-stage correction) | `int16_double_fix`, `conc_arear_fix`, `reshape_fix`, `diode_range_fix`, `intarr_threshold_fix`, `zero_image_recovery`, `mask_presence_fix` (registered `sd`/`proc`-stage corrections that could plausibly get a copy-then-correct adapter the same shape as the eight that have one, but were out of this stage's ~45-minute scope) |

The three superseded-on-v3.5 corrections in the last column (`int16_double_fix`, `conc_arear_fix`,
`reshape_fix`) already have a v3.1.4-side adapter shape to copy from (`pressure_units_fix`'s
`sd`-stage rerun pattern); building them was not attempted here and is not blocked on anything.

## 8. `all = true` names a computed set, not every module (2026-09-23)

Opt-in by name does not mean a config must list all 40+ modules to ask for "everything
applicable". `[enhancements] all = true` resolves to `registry.default_set(engine)` — every
registered module applicable to the run's engine, minus `registry.DEFAULT_SET_EXCLUSIONS` — and an
explicit `<name> = true`/`false` beside `all = true` still wins, so opt-out-by-name is still
possible under it. Before this, "v3.5 with all enhancements" existed only as hand-listed configs
(`v35_all_enhancements.toml`, naming 33 modules), so keeping a module out of the default meant
editing every such file. `default_set()` is computed from `applicability`, never listed, so a new
module joins the default and a superseded one falls out without a config edit.

The v3.5 exclusion set is `{"outoffocus"}` (project decision: *"outoffocus: ... make it an opt
in?"*). Measured on v3.5 runs, `outoffocus` changes no `image_diam_minR` on this engine
— v3.5's own pipeline already divides every `'H'`-rejected particle by its size factor
(`outoffocus.py`'s `already` guard) — only `image_area` on 0.2-0.4% of particles, for about 94% of
an enhancement pass's wall time (roughly 1.1-10.2 h per flight). It stays in the v3.1.4 default set,
where it does change diameters. `all = true` is a settled ruling, not a reopened question;
`registry.resolve()` and `tests/test_default_set.py` are where this is enforced.

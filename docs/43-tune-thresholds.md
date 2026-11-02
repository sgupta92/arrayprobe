# Tune thresholds on your own flight
> Which settings you can change, whether each one acts on your probe, and how to check a change against particles you labelled.

Tuning fits the accept/reject and shattering thresholds to the cloud you flew in, using particles
you labelled yourself. It changes only the settings you name, through the run file, a flag, a
regime, a probe case or a profile; every computed number otherwise stays the engine's own. Every
choice is recorded in the run's `.call` stamp, so `arrayprobe provenance` can say what made a
product. Warm and cold cloud are tuned separately: the thresholds that matter differ, and so do
the labels that settle them.

**In short:** the `tune` commands read a run's output and change nothing: `tune settings` lists what can
be changed, `tune sample` draws particles to label in the triage server, and `tune distributions`
shows where each threshold cuts. You change one setting where the configuration allows it,
re-run, and look again.

**See also** [Configuration](06-configuration.md) · [Visualisation and triage](03-visualisation.md) ·
[CLI reference](13-cli-reference.md#tune) · [Choosing an engine](27-choosing-an-engine.md).

## The loop

```text
  1. arrayprobe tune settings       what can change, and whether it acts on this probe case
  2. arrayprobe tune sample         particles from your time windows  ->  arrayprobe triage
                                    (a verdict and a phase per particle)
  3. arrayprobe tune distributions  the distributions, each active threshold marked
  4. change one setting             run file, command line, or a registration in Python
  5. re-run                         then repeat 2-3 on the new output and compare
```

Everything here is for the default engine, UIOOPS v3.5. The `tune` commands read a `proc` file a run
already wrote (`proc.<flight>.H.nc`); labelling also needs the decode beside it, as described under
[The triage server](03-visualisation.md#the-triage-server). None of them changes a computed number.

## 1. See what you can change

```bash
arrayprobe tune settings --probe-case v35-2ds-ladder-fix
arrayprobe tune settings --probe-case v35-2ds-ladder-fix --json
```

Each setting is listed with what it does, its default, where it is set, whether engine 3.5 accepts
it, whether it has any effect on the named probe case, and the source line its default was read
from; `--json` prints the same table with every source line. `--probe-case` takes any registered
case; `v35-2ds-ladder-fix`, the 2D-S case the batch driver applies by default on engine 3.5, is
always available, and a case of your own is available once the module that registers it is
imported (`--probe-case-module` on a run). Read the last three columns first. A setting falls into one of three groups:

- **Accepted and acting on this probe case.** Changing it changes the output.
- **Refused by engine 3.5.** A setting the engine cannot honour stops the run with exit 2 rather
  than being ignored. `regime` and the raw shattering override (`default_int_arr_thresh`) are not
  in this group: both are accepted on engine 3.5.
- **Accepted, but no effect on this probe case.** Where the probe case's `applyIntArrThresh` is 0,
  the shattering gate is off: the shattering threshold, a threshold file and the re-acceptance
  limits change no particle, though the run still accepts them. Turning the gate on is a probe-case
  change (step 4).

Where each kind of setting is set:

| Setting | Set by |
|---|---|
| area-ratio gate (reject `z`) | `[thresholds].area_ratio_z` in the run file, or `--area-ratio-z` |
| shattering threshold | `[thresholds].default_int_arr_thresh` in the run file, or `--default-int-arr-thresh` |
| per-time shattering threshold file | `[shattering].threshold_file`, or `--iat-file` |
| all eight thresholds above and below, as one named set | a regime: `--regime` or `[thresholds].regime` ([what a regime carries](06-configuration.md#what-a-regime-carries)) |
| the six reject thresholds (`rej_zero_area`, `rej_split`, `rej_hollow`, `shadowed_area`, `max_edge_img_ar`, `max_comp_img_ar`) | an [author-editable defaults file](06-configuration.md#advanced-a-defaults-file), or a [profile registered from Python](06-configuration.md#advanced-naming-your-own-forks-variant) |
| the shattering gate and the re-acceptance limits (and the case's own default threshold) | a probe case: [`register_probe_case()`](20-api-v35-pipeline.md#register_probe_case) from Python, selected with `--probe-case` and `--probe-case-module` |
| size definition, sample-area method, pressure, temperature | the campaign preset (`--preset`); for your own, see [a campaign the driver does not ship](06-configuration.md#advanced-a-campaign-the-driver-does-not-ship) |

Any other threshold written into a run file is refused when the file loads
([what the file refuses](06-configuration.md#what-the-file-can-select-and-what-it-refuses)).

## 2. Draw a sample and label it

Choose time windows inside cloud whose type you know from independent data: temperature, a phase
product, the flight notes. Write them as seconds of day, `lo-hi`, comma-separated on the command
line or in a file of one or more pairs per line, `#` starting a comment.

```bash
arrayprobe tune sample --proc out/proc.<flight>.H.nc --windows windows.txt \
    --queue-out review.json --queue-stem <name> --route "engine 3.5, stock settings"
arrayprobe triage --decoded-dir out --queue-file review.json --reviewer <you>
```

`tune sample` takes the particles inside the windows and at or above the first size edge, then draws
up to `--per-bin` from each size bin (`--size-edges`, in mm) at random. It writes two queues into
`review.json`, one of accepted image codes only (`<name>-accepted-…`) and one of every code
(`<name>-all-…`), each with a coverage block; other queues already in the file are kept. The same
`--seed` and inputs give the same queues.

In the triage server, open a queue and give each particle a **verdict** (`a` artifact, `r` real,
`t` mixed, `u` unsure) and a **phase** (`i` ice, `d` drizzle, `q` phase unsure). The phase is a
second field of the same record: `real` says the image is a particle, the phase says what kind.
Labels go to `out/triage_verdicts/<flight>.json`, plain JSON keyed by particle index. The accepted
queue shows what the thresholds keep; the all-codes queue shows what they reject as well.

### Label file format

Each `triage_verdicts/<flight>.json` is one JSON object whose keys are particle indices (as
strings) and whose values are label records. A record holds:

| Field | Meaning |
|---|---|
| `verdict` | `real`, `artifact`, `mixed` (more than one particle in the image) or `unsure` |
| `source` | where the label came from: `human`, `bulk-cluster` or `model` |
| `reviewer` | the id given with `--reviewer` (or `ARRAYPROBE_REVIEWER`) |
| `at` | when the label was made, UTC, ISO-8601 |
| `tool` | the package version that showed the image |
| `note` | free text, often empty |
| `phase`, `queue`, `comment` | present only when given: the phase label, the queue the particle was reviewed in, a reviewer's comment |
| `history` | present only when the particle was relabelled: earlier records, oldest first, each in this same shape without its own `history` |

The top-level fields are always the current label; a relabel never deletes the earlier one. For
training, keep `source == "human"` and leave out `unsure` and `mixed`, which do not say what the
image is.

## 3. Read the distributions

```bash
arrayprobe tune distributions --proc out/proc.<flight>.H.nc --windows windows.txt \
    --probe-case v35-2ds-ladder-fix --out distributions.json
```

For the same windows, the JSON report holds particles per second, inter-arrival times, area ratio
and axis ratio per size bin, the reject codes in words, habit codes and the hollow fraction.
Particles whose diameter is not finite get their own size bin. Each active threshold is marked where
it cuts, with where its value was read from:

- the area-ratio cut, v3.5's stock value unless you pass `--area-ratio-z`;
- the image-stage aspect-ratio ceilings;
- with `--probe-case`, the shattering threshold and whether that case's gate is on.

Read it beside your labels. A threshold worth moving is one whose line falls among particles you
labelled real, or leaves particles you labelled artifact on the accepted side. To see where a
candidate area-ratio cut would fall before re-running, pass it as `--area-ratio-z`: the report marks
that value instead.

## 4. Change one setting

- **Area-ratio gate:** `[thresholds].area_ratio_z` in the run file that `arrayprobe run` reads. The value is written to the size-distribution `.call` stamp only when given.
- **A reject threshold:** an [author-editable defaults file](06-configuration.md#advanced-a-defaults-file)
  overriding it, with a citation for each override; the file's name carries its content hash, so an
  unrenamed edit is refused.
- **Shattering threshold:** `--default-int-arr-thresh`, `[thresholds].default_int_arr_thresh` or a
  regime. On a probe case whose gate is off, changing the threshold does nothing. To turn the gate
  on or change the re-acceptance limits, register a probe case of your own with each value cited,
  then select it with `--probe-case` and `--probe-case-module`.
- **Several thresholds at once:** a regime from Python (`register_regime()`), selected with
  `--regime`; it carries all eight ([what a regime carries](06-configuration.md#what-a-regime-carries)).
- **Size definition, sample area, pressure, temperature:** a preset of your own
  ([how](06-configuration.md#advanced-a-campaign-the-driver-does-not-ship)).

Change one at a time, so a difference in the output has one cause.

## 5. Re-run and compare

Repeat your first run's command with the changed setting (for example `--area-ratio-z`), the
stages it acts on, and a new `--out` directory, so the first run stays to compare against. A stage
reads its input from `--out`, so copy the earlier stages' outputs there or start from decode. The
stages to re-run follow from where the setting acts: `4c` (size distributions and combine) for
the area-ratio gate and shattering, `34c` for a reject threshold, which is decided when particles are
framed and written into the `proc` file. Then:

```bash
arrayprobe provenance out_tuned
arrayprobe compare out_tuned/proc.<flight>.H.nc out/proc.<flight>.H.nc
arrayprobe tune distributions --proc out_tuned/proc.<flight>.H.nc --windows windows.txt \
    --probe-case v35-2ds-ladder-fix --out distributions_tuned.json
```

`provenance` shows what each product's stamp records, so you can confirm the run used the value you
set. `compare` joins the two `proc` files on particle identity and lists the variables that differ;
after an area-ratio or shattering change the `proc` file is unchanged and the difference is in the
`sd` and combined files. Re-reading the distributions on the new output, against the same labels,
shows whether the change did what the labels asked for.

## Walk-through: warm cloud

A 2D-S flight with no archived product, in summer marine boundary-layer cloud, processed on stock
settings with the `v35-2ds-ladder-fix` probe case (the batch driver's default for a 2D-S on
engine 3.5), or with a probe case of your own in its place.

1. `tune settings --probe-case v35-2ds-ladder-fix` reports the shattering settings as having no effect
   here (the case's gate is off), and the area-ratio gate and the six reject thresholds as acting.
2. Windows in warm liquid cloud; `tune sample … --queue-stem warm`; label each particle, with phase
   `d` for drizzle and `q` where you cannot tell.
3. `tune distributions` on the same windows. In liquid cloud the questions are whether the area-ratio
   cut, which measures departure from round, sits below the round drops you labelled real, and how
   much of the hollow fraction is out-of-focus drops (`rej_hollow` rejects those).
4. Move the setting the labels point at, and only that one.
5. Re-run, re-read the distributions, compare.

## Walk-through: cold cloud

A winter flight with ice on the same probe, the same probe case, the same commands. A worked record
of this procedure on one such flight (441 labels, seven decisions, the evidence for each) is kept
outside this package;
the image-assisted procedure itself is notebook
[11, image-assisted threshold](https://github.com/sgupta92/arrayprobe/blob/main/examples/5_data_quality/11_image_assisted_threshold.ipynb).

1. `tune settings` gives the same answer as for the warm flight: the probe case, not the weather,
   decides whether the shattering gate acts.
2. Windows in cloud known to hold ice; `tune sample … --queue-stem cold`; label with phase `i`, `d`
   or `q`.
3. `tune distributions … --probe-case v35-2ds-ladder-fix`. Ice is not round, so the area-ratio cut and the
   contained-particle aspect ceiling (`max_comp_img_ar`, reject `a`) may fall among real crystals as
   well as artifacts; the labels say which. The report marks the shattering threshold and says the
   gate is off: the inter-arrival distribution shows whether fragments are present, and acting on
   them needs a probe case of your own (step 4). The habit codes are in the report too.
4. Move one setting where the labels support it. To turn the shattering gate on for ice, register
   a probe case of your own with `applyIntArrThresh = 1` and its threshold, each value cited, and
   select it with `--probe-case` and `--probe-case-module`. Its threshold (`defaultIntArrThresh`)
   is read only under iaThreshType 2, so set `[shattering].ia_thresh_type = 2` in the run's `--config`
   file. `tune settings` cannot import your registration module, so check the case from Python,
   where `my_cases` is that module and `my-ice-case` the name it registers:

   ```python
   import importlib
   from arrayprobe.tune.settings import resolve_probe_defaults, settings_by_name

   importlib.import_module("my_cases")   # the module that registers your case
   print("applyIntArrThresh", resolve_probe_defaults("my-ice-case").applyIntArrThresh)
   print(settings_by_name()["defaultIntArrThresh"].effect("my-ice-case", ia_thresh_type=2))
   ```

   The first line should print `applyIntArrThresh 1`: the case is registered under that name and
   its gate is on (a misspelt name raises `UnknownProbeCase`). The second should print
   `effective=True`: under iaThreshType 2 the threshold is read on that case.
5. Re-run, re-read, compare. `arrayprobe tune score --queue-file review.json --decoded-dir out`
   counts, per reject code and size bin, what was rejected that you labelled real and what was
   accepted that you labelled artifact.

## Adding a cloud type

The loop above takes the cloud type as an input; nothing in `arrayprobe/tune/` is specific to warm
or cold cloud. Cloud types live in one module, `src/arrayprobe/regimes.py`:

| Where | What it defines |
|---|---|
| `regimes.py:110-167` | `Regime`: the two size-distribution thresholds, each with its justification, and six optional reject slots, checked at construction |
| `regimes.py:57-72` | `Inherit(reason)`: the marker for a reject slot the regime leaves to the run's profile |
| `regimes.py:87-95` | `REJECT_FIELDS`, the six reject thresholds a regime may set |
| `regimes.py:170`, `:200`, `:235` | the shipped regimes `liquid-warm`, `ice` and `mixed` |
| `regimes.py:260` | `_REGIMES`, the registry a run's `--regime` is looked up in |
| `regimes.py:267-282` | `register_regime()`, which adds a new cloud type and refuses a shipped name |

A regime is selected with `--regime` or `[thresholds].regime`, on either engine;
`--area-ratio-z` and `--default-int-arr-thresh` override it per field. A new cloud type is registered from Python; a run file may then
select it by name, never describe its numbers.

```python
from arrayprobe import regimes

regimes.register_regime(regimes.Regime(
    name="<cloud type>",
    area_ratio_z=MY_AREA_RATIO_Z,
    area_ratio_z_justification="<who chose it, from what evidence, with its source>",
    default_int_arr_thresh=MY_INT_ARR_THRESH,
    default_int_arr_thresh_justification="<the same, for this value>",
    provenance="<what ties these values to this cloud type>",
))
```

| Field | Holds |
|---|---|
| `name` | the name a run selects; may not shadow a shipped regime |
| `area_ratio_z` | the area-ratio cut: a particle below it is rejected (`z`); must lie within the range an area ratio can take |
| `area_ratio_z_justification` | the evidence and source for that value |
| `default_int_arr_thresh` | the shattering inter-arrival threshold, in seconds |
| `default_int_arr_thresh_justification` | the evidence and source for that value |
| `provenance` | the regime's own rationale: what ties these values to this cloud type |

The six reject thresholds (`rej_zero_area`, `rej_split`, `rej_hollow`, `shadowed_area`,
`max_edge_img_ar`, `max_comp_img_ar`) are optional keyword fields of the same constructor, each with
a `<field>_justification`; a slot left unset is `Inherit` and takes the run's profile value, and a
value set without a justification raises `UncitedRegimeField` (`regimes.py:146-167`).

The values are independent, so a regime may justify one and not another. Where no evidence is
held, the value is left at stock and its justification says so, `NOT JUSTIFIED FOR <cloud type>`,
as the shipped `ice` and `mixed` regimes do. Field definitions:
[`Regime` and `register_regime`](14-api-io-compat.md#register_regime).

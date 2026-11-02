# CLI reference
> Every `arrayprobe` subcommand's help text, generated from the real parser -- never hand-typed.

**In short:** one section per subcommand, and one per nested verb (`soda2 run`, `validate timing-closure`), each a fenced block of `arrayprobe <command> --help`'s actual output. Regenerate with `docs/_build/clidoc.py` (needs the venv) whenever a flag changes; `--check` fails if this page has drifted.

**See also** [Reference](08-reference.md) · [User guide](02-user-guide.md) · [Configuration](06-configuration.md).

<!-- argparse help as printed by Python 3.12; clidoc.py --check compares on that version -->

Start with `arrayprobe make-demo-flight`, which writes a small synthetic raw file, then process a flight with `arrayprobe run <config.toml>`: it runs every stage on the engine the file names ([run].engine, required; use "3.5", UIOOPS v3.5, for new data; examples/configs/ has configs). To run one stage at a time, use `arrayprobe run` with [run].stages. `arrayprobe engines` says which engine does what.

## Commands at a glance

**Run a whole flight.** Start here. One configuration file names every choice; these commands run it, or re-run one product exactly as it was made.

| Command | What it does |
|---|---|
| `run` | the one line: run a whole flight from one configuration file (the [run] table in the file drives it) |
| `soda2` | the SODA-2 engine (arrayprobe_soda2, a faithful port of NCAR's IDL): run a config, or list its enhancements |
| `reprocess` | re-run the stage that wrote a proc/sd product, exactly as its .call stamp records, and report whether the result is identical |

**Run one stage at a time.** Single steps on their own: stitch a flight's size distributions into one product, compute inter-arrival thresholds, find stuck diodes, write a self-describing product. `run` runs the whole chain, from the raw file to the stitched flight, on the engine its configuration file names.

| Command | What it does |
|---|---|
| `combine` | stitch a flight's sd files into one product (combine_sizedist) |
| `intarr-threshold` | per-particle inter-arrival thresholds (IntArrAnalysis_time) |
| `diode-masks` | find the stuck diodes in first-pass proc files (find_shadow_diodes.m) and show the per-diode occupancy beside them |
| `attributed` | write the self-describing sibling of a faithful product |

**Inspect and check what was written.** Read-only: look at particles, compare two files, or ask what made a product. None of these changes a number in any file.

| Command | What it does |
|---|---|
| `compare` | join two output files on particle identity, then diff by tolerance class |
| `provenance` | what wrote these products, read from their .call sidecars |
| `validate` | diagnostic checks on files the pipeline already wrote |
| `view` | diagnostic views of files the pipeline already wrote |
| `gallery` | render a whole flight's particles to disk, with index pages |
| `triage` | start the particle review and labelling server |

**Inputs and setup.** Make the small inputs a run needs when you do not have them, and see which package implements what.

| Command | What it does |
|---|---|
| `make-demo-flight` | write a synthetic raw .2DS file (no campaign data required) |
| `make-tas-file` | write the aircraft TAS file the v3.5 engine requires |
| `tas-from-nasa-ames` | convert a NASA-Ames 1001 true-air-speed file into the .tas.csv sidecar |
| `engines` | which engine to use for what; --catalogue for the per-module detail |

**Other commands.** Commands not yet sorted into a group above.

| Command | What it does |
|---|---|
| `inventory` | list raw files with size, SHA-256 and empty/truncated flags (JSON + CSV) |
| `check-counts` | reconcile a size-distribution file's binned counts with its particle file, second by second, naming the cause of every excluded particle |
| `triage-recheck` | write a blind re-check queue of particles a person already labelled |
| `triage-agreement` | report label agreement (Cohen's kappa) between first and re-check labels |
| `tune` | what a user can change for the default engine, and whether it has any effect |
| `reproduce-report` | compare a product with an archived product, listing every differing cell |

## How to read this page

Each command below is shown exactly as `arrayprobe <command> --help` prints it. In the **usage** line:

| Notation | Meaning |
|---|---|
| `[ ... ]` | optional -- leave it out and the command still runs |
| no brackets | required -- the command refuses to start without it |
| `UPPERCASE` | a value you supply, e.g. a file path or a number |
| `{a,b}` | pick exactly one of the listed values |
| `raw ...` | one or more of these, separated by spaces |

**positional arguments** are given in order with no flag in front; **options** start with `-` or `--`. A flag with no text after it has no further explanation in the parser. "Default off" means the run is unchanged unless you pass the flag.

## `run`

```
usage: arrayprobe run [-h] [--dry-run] [--yes] [--jobs N] [--enh-jobs N]
                      [--s2-jobs N] [--chunks N] [--jit] [--enhancements]
                      [--accept-preset-mismatch] [--accept-unstamped]
                      [--accept-flagged] [--accept-implausible]
                      [--allow-mixed-config] [--tas-grid {probe,regular}]
                      [--tas-ratio {off,on}] [--iat-file IAT_FILE]
                      config [raw ...]

One line of code to run and one file to configure. Every choice -- engine,
fidelity profile, campaign preset, output directory, which stages -- is named
in the file (arrayprobe.config); nothing here is assumed. Without [run].out,
output goes to an 'output' folder beside the config file. Runs the batch
driver (arrayprobe.driver.run_flight) with every setting read from [run] -- no
new pipeline logic.

positional arguments:
  config                a run configuration TOML (arrayprobe.config)
  raw                   raw files; wins over [run].raw in the file

options:
  -h, --help            show this help message and exit
  --dry-run             preflight only, decode nothing
  --yes, -y             accept the configuration this prints without being
                        asked. A config that declares [thresholds] needs no
                        confirmation and ignores this; one that declares none
                        is confirmed before the run starts, and where stdin is
                        not a terminal (a detached run, CI) it refuses to
                        start without this flag rather than blocking on a
                        prompt nobody can answer.
  --jobs N              process N raw files at once, one worker process each
                        (default 1). Helps a flight recorded as many files;
                        outputs are the same as a one-at-a-time run.
  --enh-jobs N          run the out-of-focus correction across N worker
                        processes when --enhancements applies it (default 1).
                        Separate from --jobs, which spreads raw files: the
                        corrections run after every file is done. The written
                        files are the same for any N.
  --s2-jobs N           decode one raw file across N worker processes (default
                        1). Helps a flight recorded as one large file, where
                        --jobs has nothing to spread; the decoded file is
                        byte-identical to a one-process decode. 2D-S/HVPS
                        (SPEC) files only: where the engine or format has no
                        parallel decoder the run refuses the flag rather than
                        ignore it.
  --chunks N            split each file's image processing (particle framing)
                        into N record ranges run in parallel and merged
                        (default 1); the merged file is byte-identical to an
                        unsplit run. Independent of --jobs, which spreads
                        files rather than one file's records.
  --jit                 speed only, default off: the image-processing stage's
                        hot kernels through numba (arrayprobe.jit_kernels);
                        the proc file is byte-identical, which the test suite
                        checks
  --enhancements        default off: after the stages finish, apply the
                        corrections this config's [enhancements] table names
                        to the products the run wrote, each into its own
                        <stem>.enh.<stage>.nc with an `enhancements=` fragment
                        in its .call. Off, the run is byte-identical to one
                        without the flag; the port's own outputs are never
                        overwritten either way. Needs `pip install arrayprobe-
                        uiops-enhancements`.
  --accept-preset-mismatch
                        default off, forwarded to the batch driver: run a raw
                        file whose extension names a different probe than the
                        preset (a renamed file); recorded as
                        accept_preset_mismatch=on in the .call stamps
  --accept-unstamped    default off, forwarded to the batch driver: accept an
                        input product with no .call stamp instead of refusing
                        it
  --accept-flagged      default off, forwarded to the batch driver: process a
                        raw file the input inventory flags as empty instead of
                        refusing it; the decode .call records the inventory
                        flags (inventory_empty=1), not the override
  --accept-implausible  default off, forwarded to the batch driver: accept a
                        size distribution the plausibility gate refuses; the
                        override is recorded in the .call stamps
  --allow-mixed-config  default off, forwarded to the batch driver: allow
                        inputs stamped with differing configurations to be
                        combined
  --tas-grid {probe,regular}
                        forwarded to the batch driver only when given: the
                        time vector the size-distribution stage gets under a
                        TAS source; run_flight's default when not given
  --tas-ratio {off,on}  forwarded to the batch driver only when given: v3.5
                        only: write tasRatio from an aircraft airspeed source
                        (changes the product); run_flight's default (off) when
                        not given
  --iat-file IAT_FILE   forwarded to the batch driver only when given:
                        sizeDist's twelfth argument, the inter-arrival
                        threshold file; run_flight's default (a threshold file
                        that does not exist, so the per-probe default
                        threshold applies) when not given
```

## `reprocess`

```
usage: arrayprobe reprocess [-h] --preset PRESET [--tas-file TAS_FILE] product

Reads the product's .call sidecar, re-runs the one stage that wrote it (image
processing for proc.*, size distribution for sd.*; either engine, from the
stamp) under exactly that configuration, from the input beside it, and diffs
the fresh file against the product. Refuses -- exit 2, nothing run -- unless
the batch driver's own label function regenerates the recorded stamp character
for character, and unless the stage's input carries the matching stamp. Exit 0
identical (Creation Time skipped, source paths compared by basename), 1
differs. The fresh file is written to a temporary directory and discarded; the
product is never modified. Decode and combine products are refused: their
stamps do not record the raw file or the combine call.

positional arguments:
  product              a proc.*.nc (image processing) or sd.*.nc (size
                       distribution) file with its .call sidecar beside it

options:
  -h, --help           show this help message and exit
  --preset PRESET      the campaign preset the product was run under (the
                       batch driver's PRESETS). REQUIRED: no stamp records the
                       preset, so it is named, never assumed
  --tas-file TAS_FILE  the aircraft TAS file, for a proc.* product whose stamp
                       names one (the stamp records its basename only, which
                       must match). Not needed for a product made under a TAS
                       source chain: the chain's own <stem>.tas_<tier>.cdf
                       beside it is read instead
```

## `combine`

```
usage: arrayprobe combine [-h] --flight-date FLIGHT_DATE --summary-time
                          SUMMARY_TIME --engine {3.5} [--borrowed-combine]
                          sd_files [sd_files ...] outfile

positional arguments:
  sd_files              sd files, IN ORDER (see combine_sizedist's own
                        docstring -- order is a contract, not a convenience)
  outfile

options:
  -h, --help            show this help message and exit
  --flight-date FLIGHT_DATE
                        'YYYYMMDD', full year
  --summary-time SUMMARY_TIME
                        'YY_MM_DD_HH_MM_SS', the campaign summary file's own
                        basename
  --engine {3.5}        which UIOOPS engine this stage runs: 3.5. Required,
                        with no default, so no run silently picks a side;
                        recorded in the .call stamp.
  --borrowed-combine    with --engine 3.5 only, and required there: opt in to
                        a campaign fork's combine_sizedist over v3.5 sd files.
                        No stock UIOOPS release ships a combine step, so on
                        3.5 it is borrowed and off by default.
```

## `compare`

```
usage: arrayprobe compare [-h] [-v] [--var NAME] [--classes]
                          [--min-join MIN_JOIN]
                          [left] [right]

Read the join block first, always. A value difference reported against a bad
join is an artefact of the alignment, not a finding, and the two are
indistinguishable once you are looking at a column of numbers. Exit status is
0 when the comparison is ACCEPTED (>=--min-join join, no failure in an
asserting tolerance class, no unclassified variable, no duplicate join keys)
and 1 otherwise, so it can gate a run without anyone reading the output; 2 is
a usage or file error.

positional arguments:
  left                 the file under test (usually ours)
  right                the reference file

options:
  -h, --help           show this help message and exit
  -v, --verbose        list bit-exact variables too, not only the differing
                       ones
  --var NAME           restrict the value comparison to these variables
                       (repeatable); the join is always computed in full
  --classes            print the tolerance classes and what each one means,
                       then exit
  --min-join MIN_JOIN  join fraction required for acceptance (default 0.999)
```

## `gallery`

```
usage: arrayprobe gallery [-h] --decoded-dir DECODED_DIR --flight FLIGHT --out
                          OUT
                          [--classes {accepted,rejected,unsure} [{accepted,rejected,unsure} ...]]
                          [--scale SCALE] [--no-crop] [--limit LIMIT]
                          [--no-index]

Visualisation only -- it reads a decoded file and its proc file and writes
images; it computes nothing and changes nothing.

options:
  -h, --help            show this help message and exit
  --decoded-dir DECODED_DIR
                        directory holding <flight>.cdf and proc.<flight>.nc
  --flight FLIGHT       flight stem including the channel, e.g.
                        base170817073523.H
  --out OUT             output root; a <flight>/ subdirectory is created under
                        it
  --classes {accepted,rejected,unsure} [{accepted,rejected,unsure} ...]
                        which classes to write (default: accepted only, which
                        keeps a large flight's gallery a manageable size)
  --scale SCALE         pixel scale (default 3)
  --no-crop             keep the full diode-search window instead of cropping
                        to the particle. The window can vastly exceed the
                        shadow right after a record reset, which is why
                        cropping is the default
  --limit LIMIT         stop after N particles
  --no-index            skip the index pages
```

## `inventory`

```
usage: arrayprobe inventory [-h] --out OUT [--format {spec,dmt,pms_2d}] dir

Reads raw bytes only; writes <out>.json and <out>.csv, one row per file.
Computes no product and changes nothing.

positional arguments:
  dir                   directory of raw files (or one file)

options:
  -h, --help            show this help message and exit
  --out OUT             output stem; writes <stem>.json and <stem>.csv
  --format {spec,dmt,pms_2d}
                        record format for every file (default: guessed per
                        file)
```

## `check-counts`

```
usage: arrayprobe check-counts [-h] [--out OUT] [--tolerance TOLERANCE]
                               sd proc

Reads the sd and proc files only and writes nothing but --out. Prints every
second whose binned count differs from the accepted particle count, each
excluded particle with its cause, a closure line and the probe's own reported
total (not available until a reader writes it). Exit 0 when closure is exact,
1 otherwise.

positional arguments:
  sd                    size-distribution netCDF (its .call sidecar beside it)
  proc                  the per-particle netCDF the sd file was made from

options:
  -h, --help            show this help message and exit
  --out OUT             write the full reconciliation as JSON
  --tolerance TOLERANCE
                        largest per-second residual still counted as closed
                        (default 0)
```

## `triage`

```
usage: arrayprobe triage [-h] --decoded-dir DECODED_DIR [--port PORT]
                         [--queue-file QUEUE_FILE] [--reviewer REVIEWER]
                         [--met-dir MET_DIR] [--state-file STATE_FILE]
                         [--state-var STATE_VAR] [--accept-unstamped]
                         [--run-root RUN_ROOT]

Manual labelling and visualisation. It writes verdicts to <decoded-
dir>/triage_verdicts/ and changes no computed number. --decoded-dir is
required, as it is for `python -m arrayprobe.triage_server`.

options:
  -h, --help            show this help message and exit
  --decoded-dir DECODED_DIR
                        directory containing proc.*.H.nc files and their
                        decodes (*.H.nc)
  --port PORT
  --queue-file QUEUE_FILE
                        JSON file of named curated particle lists for a
                        specific review pass
  --reviewer REVIEWER   who is labelling; REQUIRED to save labels and recorded
                        with every verdict (or set ARRAYPROBE_REVIEWER). With
                        neither, the server starts but refuses every save
                        (HTTP 400) -- the id is never guessed
  --met-dir MET_DIR     folder of ARM AAF merged files
                        (enaaafmergedF1.c1.*.nc); the particle page then shows
                        the air temperature at the particle's record time
  --state-file STATE_FILE
                        netCDF state-variable file for the air temperature
                        (any names: the temperature is chosen by units and
                        standard_name/long_name, and a file with several
                        candidates is refused, listing them). Takes precedence
                        over --met-dir. With neither, the index page asks for
                        the file
  --state-var STATE_VAR
                        the temperature variable in --state-file (default:
                        chosen by content)
  --accept-unstamped    index products whose provenance is unrecorded. WITHOUT
                        this flag they are refused and listed by name on the
                        index page under 'Refused: no provenance' -- never
                        silently dropped. Labels attached to a product of
                        unknown configuration cannot be traced afterwards.
                        Pass this when you know what you are looking at and
                        the stamp is simply absent.
  --run-root RUN_ROOT   folder whose _runs/ the Run page lists at /runs
                        (default: the output folder of the first run launched
                        from /run)
```

## `triage-recheck`

```
usage: arrayprobe triage-recheck [-h] --decoded-dir DECODED_DIR --flight
                                 FLIGHT --out OUT [--fraction FRACTION]
                                 [--seed SEED]

Draws a seeded random fraction of one flight's human labels into a queue file
whose name starts 'recheck-'. The triage server stores its verdicts separately
(triage_verdicts/<flight>.recheck.json) and hides the first label, so the
second is blind. Changes no computed number.

options:
  -h, --help            show this help message and exit
  --decoded-dir DECODED_DIR
                        the directory the triage server uses
  --flight FLIGHT       flight name as the triage server shows it
  --out OUT             queue file to write (JSON)
  --fraction FRACTION   share of the human-labelled particles to re-show
                        (default 0.2)
  --seed SEED           random seed, recorded in the file
```

## `triage-agreement`

```
usage: arrayprobe triage-agreement [-h] --decoded-dir DECODED_DIR --flight
                                   FLIGHT

Pairs each re-checked particle's first human label with its re-check label and
prints the observed and chance agreement, Cohen's kappa and the confusion
matrix.

options:
  -h, --help            show this help message and exit
  --decoded-dir DECODED_DIR
                        the directory the triage server uses
  --flight FLIGHT       flight name as the triage server shows it
```

## `provenance`

```
usage: arrayprobe provenance [-h] [--require] paths [paths ...]

Per file: the engine, profile and stage its stamp records, the stamp's format,
its link count, and its state -- stamped, unstamped, orphan-stamp (a sidecar
whose product is gone), in-flight, legacy-json or unparseable. A directory
expands to every .nc/.cdf in it plus every orphan sidecar. Nothing here infers
an engine from a date, a filename or a neighbouring file: a product whose
stamp does not name one is reported as unrecorded, which is the true answer.
The git revision printed at the end is THIS CHECKOUT's, not the product's --
no stamp records the revision that wrote it.

positional arguments:
  paths       products or directories

options:
  -h, --help  show this help message and exit
  --require   exit 1 unless every path is 'stamped' -- the form a script
              wants, and the form that makes 'all clear' mean something
```

## `diode-masks`

```
usage: arrayprobe diode-masks [-h] --proc PROC [--image IMAGE] [--date DATE]
                              [--time TIME] [--orientation {H,V}]
                              [--out-dir OUT_DIR] [--no-write]
                              [--profile NAME] [--probe NAME]

Runs masks.find_shadow_diodes -- a field-campaign fork's find_shadow_diodes.m,
bug for bug -- on each --proc, writing the diode.<date><time>.<or>[empty].mat
MATLAB writes (an upstream defect: an empty result is named ...<or>empty.mat,
which the second pass never loads) and nothing else. Beside it, prints
bin_stats and, when --image is given, diode_report's occupancy and SPEC's
noisy-diode flags. The mask reaches a second pass only when the diodes are
declared in [run].diode_masks AND the run is given --diode-corrected.

options:
  -h, --help           show this help message and exit
  --proc PROC          a first-pass proc file; repeat for several
  --image IMAGE        the decoded image .cdf for the matching --proc, in the
                       same order; enables the occupancy / SPEC view
  --date DATE          'YYMMDD'; default: parsed from the proc name
  --time TIME          'HHMMSS'; default: parsed from the proc name
  --orientation {H,V}  default: parsed from the proc name
  --out-dir OUT_DIR    where the .mat goes; default the proc's own directory
                       (MATLAB's `path`, which it both reads from and saves
                       to)
  --no-write           report only; write no .mat
  --profile NAME       the fidelity profile, when the proc file's stamp names
                       none (it decides whether bin_stats counts lit or
                       shadowed slices)
  --probe NAME         the probe whose image_slice_offset enters S for a
                       shadow count
```

## `validate`

```
usage: arrayprobe validate [-h] {timing-closure,by-condition} ...

Read-only checks. Nothing here computes or writes a pipeline number. Each
check reports a comparison and returns 0 on success -- none of them issues a
pass/fail verdict, because none of the sources they implement publishes a
tolerance.

positional arguments:
  {timing-closure,by-condition}
    timing-closure      does the probe's particle clock agree with its
                        housekeeping clock?
    by-condition        per-second agreement against the archived product,
                        split by how much cloud the probe was in

options:
  -h, --help            show this help message and exit
```

### `validate timing-closure`

```
usage: arrayprobe validate timing-closure [-h]
                                          [--day-rollover-h DAY_ROLLOVER_H]
                                          decoded proc

McFarquhar et al. (2017) ch. 11 p. 11.20. Compares the proc file's particle-
clock time span against the decoded file's own record-clock span, which is
measured by a different clock in the instrument. Probetype 2 (2D-S / HVPS)
only -- see arrayprobe.timing_closure for why.

positional arguments:
  decoded               the decoded file the proc file was framed from
                        (.H.nc/.V.nc from engine 3.5, or an archived
                        .H.cdf/.V.cdf); pairing them correctly is the caller's
                        responsibility
  proc                  the proc (image-processing) file

options:
  -h, --help            show this help message and exit
  --day-rollover-h DAY_ROLLOVER_H
                        hours added once if the record span looks negative (a
                        single midnight crossing); default 24.0
```

### `validate by-condition`

```
usage: arrayprobe validate by-condition [-h] [--product PRODUCT]
                                        [--product-dir PRODUCT_DIR]
                                        [--window WINDOW]
                                        [--drop-bins DROP_BINS]
                                        combined

A single headline percentage can hide a whole regime. The band for each second
is decided by the REFERENCE's own per-second particle total, never by ours --
using ours would make the stratification depend on the thing being tested.

positional arguments:
  combined              our combined product

options:
  -h, --help            show this help message and exit
  --product PRODUCT     the archived product; when omitted, found by date in
                        --product-dir
  --product-dir PRODUCT_DIR
  --window WINDOW       HHMMSS-HHMMSS, inclusive-exclusive, so a partially
                        processed flight is compared only where its raw files
                        are all present
  --drop-bins DROP_BINS
                        bins excluded from the 'used' columns (default 5)
```

## `view`

```
usage: arrayprobe view [-h] {strip,second,hollow} ...

Visualisation only: each view reads the port's own outputs and computes no
pipeline number (arrayprobe.diagnostic_views). The triage server serves the
record strip at /strip/<flight>.

positional arguments:
  {strip,second,hollow}
    strip               whole image records with their particles in place
                        (HydroViewer's view)
    second              one second of two sd files bin by bin, with the
                        particles behind the differing cells
    hollow              how much of a between-engine difference hollow ('H')
                        particles can make

options:
  -h, --help            show this help message and exit
```

### `view strip`

```
usage: arrayprobe view strip [-h] [--record RECORD] [--n-records N_RECORDS]
                             [--colour-by {reject,habit}] --out OUT
                             image proc

Consecutive 1700-slice records stacked one above the next, boundary slices
marked, each particle's shadow coloured by its reject code or habit, and every
fifth particle ticked in red.

positional arguments:
  image                 the decoded image file (.H.nc)
  proc                  the proc file framed from it

options:
  -h, --help            show this help message and exit
  --record RECORD       first record, 1-based (default 1)
  --n-records N_RECORDS
                        records to show (default 6)
  --colour-by {reject,habit}
  --out OUT             output file: .png for the image alone, anything else
                        for an HTML page with the legend and particle table
```

### `view second`

```
usage: arrayprobe view second [-h] --second SECOND [--variable VARIABLE]
                              [--proc PROC] [--diameter-var DIAMETER_VAR]
                              [--rtol RTOL] [--out OUT]
                              ours theirs

For validation: the port's second beside the archive's. Exact comparison
unless --rtol is given. The particle list is where to look, not what was
counted: `count` also requires the reject codes, centre-in and time window to
pass.

positional arguments:
  ours                  our sd (or combined) file
  theirs                the file to compare against, e.g. the archived product

options:
  -h, --help            show this help message and exit
  --second SECOND       the second, as HHMMSS
  --variable VARIABLE   a (time, bin) variable (default count)
  --proc PROC           the proc file behind OURS; lists the particles in
                        differing bins
  --diameter-var DIAMETER_VAR
                        the proc variable particles are placed in bins by
                        (default image_diam_minR); printed with every listing
  --rtol RTOL           relative tolerance; 0 (default) is an exact comparison
  --out OUT             also write an HTML page here
```

### `view hollow`

```
usage: arrayprobe view hollow [-h]
                              (--edges-um EDGES_UM | --edges-from EDGES_FROM)
                              [--min-fraction MIN_FRACTION]
                              proc

Reads one UIOOPS v3.5 proc file. Per size bin: accepted particles, accepted
'H' (hollow, Poisson-spot) particles, their share, how many the Korolev size
correction moves out of and into the bin, and the count with the correction
undone. Ends with a verdict: whether hollow sizing can explain a difference
between engines (SODA-2 does not divide) in this size range. Reads the file
and writes nothing.

positional arguments:
  proc                  the v3.5 proc file (proc.<stem>.<channel>.nc)

options:
  -h, --help            show this help message and exit
  --edges-um EDGES_UM   comma-separated bin edges in micrometres, e.g.
                        55,65,75,85,95,105,115
  --edges-from EDGES_FROM
                        a size-distribution file whose Bin Minimum/Bin Maximum
                        (mm) give the bins
  --min-fraction MIN_FRACTION
                        verdict threshold as a fraction of the range's count
                        (default 0.05)
```

## `intarr-threshold`

```
usage: arrayprobe intarr-threshold [-h] --probe PROBE --flight-date
                                   FLIGHT_DATE [--blocks BLOCKS]
                                   [--extra-thresholds-json EXTRA_THRESHOLDS_JSON]
                                   [--plot PLOT] [--fix-b8]
                                   [--mat-workspace MAT_WORKSPACE]
                                   proc_file outfile

Fit each population of inter-arrival times and write the threshold file
sizeDist accepts as its optional twelfth argument. NOTE: the production call
behind the archived products this port is validated against passed a threshold
file that does not exist, so nothing in them depends on this stage.

positional arguments:
  proc_file             a per-particle file (proc.*.nc) or a combined one
  outfile               threshold .cdf for sizeDist's optional twelfth
                        argument

options:
  -h, --help            show this help message and exit
  --probe PROBE         probe name, e.g. 2DS
  --flight-date FLIGHT_DATE
                        'YYYYMMDD', full year
  --blocks BLOCKS       number of populations to split the file into (the
                        source's fileNum); the block size is derived from it
                        exactly as IntArrAnalysis_time does
  --extra-thresholds-json EXTRA_THRESHOLDS_JSON
                        opt-in: write the two thresholds the source computes
                        but never writes (threshold, threshold_ww) to this
                        JSON sidecar, never a netCDF file (arrayprobe.intarr_a
                        nalysis.write_extra_thresholds_sidecar)
  --plot PLOT           opt-in: render IntArrAnalysis_time.m's contour figure
                        (arrayprobe.intarr_plots.plot_intarr_contour) to this
                        image path (matplotlib; requires the scipy/matplotlib
                        extras)
  --fix-b8              with --plot: use the corrected time axis instead of
                        reproducing the original's NaN gaps before 10:00:00 (a
                        defect in the original time axis)
  --mat-workspace MAT_WORKSPACE
                        opt-in: write IntArrAnalysis_time.m's :331 workspace
                        dump (arrayprobe.intarr_analysis.write_mat_workspace)
                        to this .mat path (requires the scipy extra)
```

## `attributed`

```
usage: arrayprobe attributed [-h] [--accept-unstamped]
                             [--enhancements ENHANCEMENTS]
                             [--layout {dimensions,particles}]
                             source [out]

Writes a SECOND file beside a faithful product, carrying the same values plus
the whole .call sidecar and a sourced unit on every variable, so a recipient
can answer 'where did this number come from' from one file. The faithful
product is opened READ-ONLY and never modified -- it is the byte-comparison
artefact and carries no attributes because the MATLAB combine step writes
none. Every unit is quoted from the MATLAB line that writes it; a product
shape with no sourced unit table is refused by name rather than exported with
a guess. Design: docs/developer/ATTRIBUTED_EXPORT.md.

positional arguments:
  source                the faithful product (its .call sidecar is read too)
  out                   output path (default: <source>.attributed.nc)

options:
  -h, --help            show this help message and exit
  --accept-unstamped    export a product with no .call sidecar; the file then
                        RECORDS that its provenance is not established, rather
                        than staying silent about the gap
  --enhancements ENHANCEMENTS
                        comma-separated names of enhancements the producing
                        chain applied; empty (the default) means none, which
                        is the port's own case by construction
  --layout {dimensions,particles}
                        'dimensions' (the default, unchanged) writes the
                        attributed netCDF4 sibling; 'particles' instead reads
                        a proc (per-particle) file and writes one Parquet
                        table, one row per particle (default
                        <source>.particles.parquet); needs the [parquet] extra
```

## `make-demo-flight`

```
usage: arrayprobe make-demo-flight [-h] [--seconds SECONDS]
                                   [--tas-mps TAS_MPS] [--dense]
                                   [--distinct-counters] [--with-config]
                                   path

Builds a raw SPEC-shaped .2DS recording from nothing -- the quickstart input,
so the pipeline can be exercised without any archived data or Octave.
Synthetic, not validated science: it proves the chain runs and writes valid
files, and is not a stand-in for the oracle-backed validation the fidelity
claims rest on. Name the output base<YYMMDDhhmmss>.2DS if you intend to reach
the combine stage, which reads the flight date from the stem. WITHOUT --dense
the flight is deliberately sparse: its one particle per second has an
arbitrary inter-arrival time, so sizeDist rejects every particle as sub-6 us
and the combined product is all fill value. Pass --dense for a run that yields
a real size distribution.

positional arguments:
  path                 output path, e.g. base160101000000.2DS

options:
  -h, --help           show this help message and exit
  --seconds SECONDS    number of one-second records to write (default: 5)
  --tas-mps TAS_MPS    synthetic true airspeed in m/s (default: 130.0)
  --dense              write the DENSE demo instead: many particles per second
                       with realistic inter-arrival gaps, so the size
                       distribution comes out populated. This is the demo to
                       run first.
  --distinct-counters  give each image packet its own particle counter
                       (default: the constant 7), so SODA-2's spec_index keeps
                       every particle; changes the written bytes
  --with-config        also create the output folder if needed and write a
                       ready-to-run run.toml beside the flight, so `arrayprobe
                       run <folder>/run.toml <flight> --yes` works from a
                       plain pip install, without the repository's examples/
                       folder
```

## `make-tas-file`

```
usage: arrayprobe make-tas-file [-h] [--from-tas-csv FROM_TAS_CSV]
                                [--constant-tas CONSTANT_TAS]
                                [--start-hhmmss START_HHMMSS]
                                [--seconds SECONDS]
                                [--second-rule {round,floor}]
                                [--neighbour {adjacent,nearest-present}]
                                [--on-unsettled {default,refuse}]
                                [--from-merge FROM_MERGE]
                                [--from-aircraft FROM_AIRCRAFT]
                                [--chain {auto,merge,aircraft,probe}]
                                [--date DATE] [--search SEARCH]
                                [--probe-csv PROBE_CSV]
                                [--cutoff-mps CUTOFF_MPS]
                                [--default-mps DEFAULT_MPS]
                                [--soda2-pth SODA2_PTH]
                                path

Writes the aircraft file stock imgProc_sm.m reads as varargin{1}: a netCDF
file with two 1-D f8 variables, `Time` (HHMMSS, e.g. 60638 for 06:06:38) and
`TAS` (m/s); the image-processing stage reads those exact names. The v3.5
engine -- the package default -- refuses to run without one. Build it from the
.tas.csv sidecar the decode already wrote, or state a constant speed
explicitly.

positional arguments:
  path                  output path, e.g. aircraft_160906.cdf

options:
  -h, --help            show this help message and exit
  --from-tas-csv FROM_TAS_CSV
                        the <stem>.tas.csv the decode wrote (columns:
                        timehhmmss, tas)
  --constant-tas CONSTANT_TAS
                        flat series at this speed, NOT a measurement (needs
                        --start-hhmmss and --seconds)
  --start-hhmmss START_HHMMSS
                        first sample's time as HHMMSS
  --seconds SECONDS     number of 1-Hz samples for --constant-tas
  --second-rule {round,floor}
                        fractional HHMMSS to whole seconds; default round
                        (this package's choice)
  --neighbour {adjacent,nearest-present}
                        the neighbouring second the duplicate-second rule
                        compares against; default adjacent (this package's
                        choice)
  --on-unsettled {default,refuse}
                        a duplicated second the duplicate-second rule cannot
                        settle; default: it takes --default-mps (this
                        package's choice)
  --from-merge FROM_MERGE
                        a campaign merge file, e.g.
                        mrg1_<platform>_<yyyymmdd>_R*.nc
  --from-aircraft FROM_AIRCRAFT
                        another registered aircraft file, e.g. ARM
                        enaaafmergedF1.c1.*.nc
  --chain {auto,merge,aircraft,probe}
                        resolve the source through the fallback chain (merge
                        -> aircraft -> probe)
  --date DATE           --chain: the flight date YYYYMMDD
  --search SEARCH       --chain: a directory holding merge/aircraft files
                        (repeatable)
  --probe-csv PROBE_CSV
                        --chain: the decode's <stem>.tas.csv
  --cutoff-mps CUTOFF_MPS
                        TAS above this takes --default-mps; default 300 (this
                        package's choice)
  --default-mps DEFAULT_MPS
                        the fall-back value; default 170, UIOOPS's own fall-
                        back airspeed
  --soda2-pth SODA2_PTH
                        also write the series as a SODA-2 op.pth ASCII file
```

## `tas-from-nasa-ames`

```
usage: arrayprobe tas-from-nasa-ames [-h] --out OUT --flight-date YYYY-MM-DD
                                     [--drop-missing] [--variable SUBSTRING]
                                     [--assume-units {as-declared,knots}]
                                     [--round-seconds]
                                     path

Reads a NASA-Ames 1001 aircraft true-air-speed file (plain or .gz) and writes
the .tas.csv sidecar arrayprobe.readers.tasinfo.load_tas_info reads, which
`make-tas-file --from-tas-csv` then turns into the aircraft netCDF the v3.5
engine requires. This is the SEA/CIP chain's route to a MEASURED TAS: `make-
tas-file --constant-tas` fabricates one and says so, and nothing on that chain
writes a sidecar of its own.

positional arguments:
  path                  the NASA-Ames 1001 file, e.g. <stem>.SODA2_TAS.1Hz.gz

options:
  -h, --help            show this help message and exit
  --out OUT             the .tas.csv to write
  --flight-date YYYY-MM-DD
                        the flight this series is for; must equal the file's
                        own DATE
  --drop-missing        leave out rows carrying the file's missing-value code
                        instead of refusing
  --variable SUBSTRING  name which true-air-speed variable to use, when the
                        file declares more than one (UND's own .basic.1Hz
                        declares two). The reader still refuses to choose on
                        its own; this is how an operator chooses, and the full
                        name of the column used is reported
  --assume-units {as-declared,knots}
                        declare the column's REAL units when they contradict
                        the file's header; 'knots' multiplies by 0.514444 and
                        reports it
  --round-seconds       attribute each sample to its nearest whole second, for
                        a file whose 1 Hz grid is offset from the integer
                        second (UND's .basic.1Hz sits 0.21 s off on the 2016
                        flights). The shift is reported
```

## `engines`

```
usage: arrayprobe engines [-h] [--catalogue] [--module NAME]

Prints which engine to use for what: UIOOPS v3.5 (the default) for new data
and SODA-2 as an independent second processing. Then states what the chosen
engine's results rest on. --catalogue adds, per module, which package
implements it and why. Reads nothing and writes nothing.

options:
  -h, --help     show this help message and exit
  --catalogue    also list every module and which package implements it for
                 that engine, and why
  --module NAME  describe only this module; repeatable
```

## `tune`

```
usage: arrayprobe tune [-h] {settings,sample,distributions,diodes,score} ...

Tuning a run on the default engine (UIOOPS v3.5). Nothing here runs the
pipeline or changes a product; `sample` writes only a review queue file and
`distributions` and `score` only a JSON report.

positional arguments:
  {settings,sample,distributions,diodes,score}
    settings            list every setting: what it does, its default, where
                        to set it
    sample              draw review queues from a proc file: particles inside
                        time windows, per size bin
    distributions       per-particle distributions inside time windows of a
                        proc file, thresholds marked
    diodes              stuck diodes from a proc file's bin_stats, with the
                        run-file lines that mask them
    score               the reviewer's labels per reject code and size bin:
                        what each code rejected that was labelled real, and
                        accepted that was labelled artifact

options:
  -h, --help            show this help message and exit
```

### `tune settings`

```
usage: arrayprobe tune settings [-h] [--probe-case NAME]
                                [--ia-thresh-type {0,1,2,3}] [--json]

Lists every setting a run on the default engine (UIOOPS v3.5) can change: what
it does, its default, where it is set (run file, run_flight.py flag, probe
case, profile or preset), and whether engine 3.5 accepts it. Given a probe
case, it also says whether each setting has any effect there: the shattering
settings change nothing where the case's applyIntArrThresh is 0, or where the
run's iaThreshType is 0 (engine 3.5's default without a threshold file). Each
default is cited to the source line it was read from; the JSON form lists them
all.

options:
  -h, --help            show this help message and exit
  --probe-case NAME     also say whether each setting has any effect on this
                        registered probe case (v35-2ds-ladder-fix is always
                        available)
  --ia-thresh-type {0,1,2,3}
                        the run's iaThreshType for the effect column (default
                        0, engine 3.5's default without a threshold file; 2 is
                        [shattering].ia_thresh_type = 2)
  --json                print the table as JSON, with every source line
```

### `tune sample`

```
usage: arrayprobe tune sample [-h] --proc PROC --windows W --queue-out Q
                              [--route R] [--flight FLIGHT]
                              [--queue-stem QUEUE_STEM]
                              [--size-edges MM [MM ...]] [--per-bin PER_BIN]
                              [--seed SEED]

From one proc file, take the particles whose record header time (Time, HHMMSS)
falls inside any window (seconds of day, both ends included) and whose
image_diam_minR is at least the first size edge, and draw up to --per-bin of
each size bin at random with a fixed seed. Two queues: the accepted image
codes only (0HhuR), and every code. They are merged into --queue-out, the file
`arrayprobe triage --queue-file` reads, with a coverage block per queue; other
queues in that file are kept.

options:
  -h, --help            show this help message and exit
  --proc PROC           the proc file to draw from
  --windows W           time windows as lo-hi seconds of day
                        ('47925-47959,51671-51797'), or a file of such pairs
                        (one or more per line, # for comments)
  --queue-out Q         queue file to write, or to add the two queues to
  --route R             how the proc file was made, recorded in the coverage
  --flight FLIGHT       flight name the triage server knows the particles by
                        (default: the proc file name without 'proc.' and
                        '.nc')
  --queue-stem QUEUE_STEM
                        queue name prefix; the queues are
                        <stem>-accepted-n<N>-s<seed> and
                        <stem>-all-n<N>-s<seed> (default: sample)
  --size-edges MM [MM ...]
                        size-bin edges in mm, increasing; the first is the
                        size floor and 'inf' closes the last bin (default:
                        0.055 0.1 0.2 0.4 1.0 inf)
  --per-bin PER_BIN     particles drawn per size bin (default: 40)
  --seed SEED           random seed; the same seed and inputs give the same
                        queues (default: 20260930)
```

### `tune distributions`

```
usage: arrayprobe tune distributions [-h] --proc PROC --windows W --out REPORT
                                     [--probe-case NAME] [--area-ratio-z Z]
                                     [--size-edges MM [MM ...]]

From one proc file, for the particles whose record header time (Time, HHMMSS)
falls inside any window (seconds of day, both ends included): particles per
second, inter-arrival time, area ratio and axis ratio per size bin, the reject
codes in words, habit codes and the hollow fraction. Each active threshold is
marked where it cuts, with where its value was read from: the area-ratio cut,
the image-stage aspect-ratio ceilings and, given --probe-case, the shattering
threshold, with whether it has any effect on that case. Non-finite diameters
get their own size bin. Writes only the JSON report.

options:
  -h, --help            show this help message and exit
  --proc PROC           the proc file to read
  --windows W           time windows as lo-hi seconds of day
                        ('47925-47959,51671-51797'), or a file of such pairs
                        (one or more per line, # for comments)
  --out REPORT          JSON report to write
  --probe-case NAME     mark this registered probe case's shattering threshold
                        and say whether its gate is on (v35-2ds-ladder-fix is
                        always available)
  --area-ratio-z Z      the area-ratio cut to mark: the value the run passes
                        for this flag (default: v3.5's stock cut)
  --size-edges MM [MM ...]
                        size-bin edges in mm, increasing; 'inf' closes the
                        last bin (default: 0 0.055 0.1 0.2 0.4 1.0 inf)
```

### `tune diodes`

```
usage: arrayprobe tune diodes [-h] --proc PROC [--profile NAME] [--probe NAME]
                              [--stem STEM] [--json] [--jobs N]

For each proc file, read bin_stats as lit counts (a shadow count is converted
as S - shadow, S the particles' slice total from position) and apply the
archived-product variant's stuck-diode rule (find_shadow_diodes.m:66-97):
below 0.80 x max, or below 0.80 x mean when a diode reads above 1.2 x mean.
The engine and profile come from the file's provenance; an unstamped file
needs --profile. Prints a [masking.diodes] entry per file, applied by a run
given --diode-corrected. Reads only.

options:
  -h, --help      show this help message and exit
  --proc PROC     a proc file to read (repeatable)
  --profile NAME  the fidelity profile, when the file's stamp names none
  --probe NAME    the probe whose image_slice_offset enters S (default: the
                  offset every probe of the file's diode count shares)
  --stem STEM     the raw stem the [masking.diodes] entry is keyed by
                  (default: the base<12 digits> in the proc file's name)
  --json          print the full report as JSON instead of the summary
  --jobs N        worker processes reading position for S (default: up to 8
                  above 2 M particles, else 1; 1 forces a serial read). A
                  parallel read that fails or stalls falls back to the serial
                  one; S is identical either way
```

### `tune score`

```
usage: arrayprobe tune score [-h] --queue-file Q --decoded-dir D
                             [--out REPORT] [--phase-verdicts V]

For each queue in --queue-file, join the verdicts and phases recorded in
`arrayprobe triage` (the verdict store under --decoded-dir; a recheck- queue
reads its own store) to the queue's particles, and count them per size bin and
per reject code (the code each particle carried when the queue was drawn). For
a rejecting code: how many it rejected that were labelled real; for an
accepted code: how many it accepted that were labelled artifact. Per size bin,
the ice fraction ice / (ice + drizzle) with a Wilson 95 % interval. Writes
only the JSON report.

options:
  -h, --help          show this help message and exit
  --queue-file Q      the queue file the labels were made from
  --decoded-dir D     the directory `arrayprobe triage --decoded-dir` was
                      given; verdicts are read from its triage_verdicts/
  --out REPORT        JSON report to write (default: print the summary only)
  --phase-verdicts V  comma-separated verdicts whose phase enters the ice
                      fraction (default: real)
```

## `soda2`

```
usage: arrayprobe soda2 [-h] {run,enhancements} ...

`soda2 run` reads [soda2] (the driver's op fields) from a config whose
[run].engine is "soda2", runs soda2_process_2d and writes a deterministic
<stem>.pbp.call sidecar beside the PBP outputs, <stem> being theirs. With
the optional correction package installed, every resolved-ON correction the
driver adapter can route is applied and the sidecar records which were
applied and which skipped, with the reason. `soda2 enhancements` lists the
optional correction package's registry. The UIOOPS version options do not
apply to this engine, and `arrayprobe run` refuses a soda2 config with a
pointer here. What a soda2 config may hold, and the IDL-type limit on
op.rate: `soda2 run --help`.

positional arguments:
  {run,enhancements}
    run               run soda2_process_2d from a config file
    enhancements      list the SODA-2 corrections (reachability; resolved
                      state from a config if given)

options:
  -h, --help          show this help message and exit
```

### `soda2 run`

```
usage: arrayprobe soda2 run [-h] [--out OUT] [--jobs N] [--chunks N] [--jit]
                            [--protective {auto,on,off}]
                            config

Run soda2_process_2d with op = the file's [soda2] table and write
<stem>.pbp.call beside the PBP outputs. Exit 2 for a config it cannot run, 1
when the driver returns no data.

positional arguments:
  config                a run configuration TOML with a [soda2] table

options:
  -h, --help            show this help message and exit
  --out OUT             output directory; overrides [soda2].outdir
  --jobs N              split soda2_process_2d's buffer loop across N
                        processes (default 1, serial). Byte-identical to
                        serial -- asserted by tests/test_soda2_parallel.py,
                        not claimed here -- and refused by name where it would
                        not be (op.stuckbits, op.activetimefrommissed, more
                        than one raw file). It composes with the correction
                        package: the enhancements are rebuilt by name inside
                        each worker and the split stays byte-identical to
                        serial with them ON
                        (tests/test_soda2_parallel_enhancements.py), so --jobs
                        is not a choice between fast and corrected. A resource
                        knob, not a threshold: it is a flag and not a config
                        key, because a config file may select a run's science
                        and never describe it
  --chunks N            how many contiguous buffer ranges --jobs splits the
                        loop into (default 0 = 4 per job). More than one per
                        job because a buffer's cost is its particle count, so
                        equal buffer counts are not equal work. SODA-2 engine
                        only, and read ONLY when --jobs > 1: with --jobs left
                        at 1 this value is accepted and never looked at
                        (process_2d.py's `if jobs > 1:` is its one reader), so
                        it is a balance knob for the split and not a way to
                        break one long run into resumable pieces
  --jit                 SODA-2 engine only. Speed only, default off: route
                        label_blobs's flood fill -- and fillholes' own call to
                        it -- through numba (arrayprobe_soda2.jit_kernels;
                        needs pip install "arrayprobe[jit]"). The PBP files
                        are byte-identical to a run without it, asserted in
                        tests/test_soda2_jit_product_identity.py (the written
                        product, off against on) over
                        tests/test_soda2_label_region_jit_identity.py (the
                        kernel's own array) and not claimed here, so it is not
                        written into op and the .pbp.call sidecar is the same
                        either way. Measured 36.2x at the kernel. It installs
                        no substitution (a --jit run leaves every
                        enhancement_hooks point pristine, measured), so it
                        composes with --jobs and --chunks at the engine level
                        and the same module asserts that. With arrayprobe-
                        soda2-enhancements installed, the two speedups and the
                        corrections compose in one run. `[run].jit = true` in
                        the config does the same thing; the two are ORed, so
                        this flag can turn the kernel on and never off
  --protective {auto,on,off}
                        The protective-corrections rule applied to SODA-2:
                        which of
                        arrayprobe_soda2_enhancements.registry.PROTECTIVE (the
                        corrections for data-destroying upstream defects) run
                        by default. 'auto' (the default) resolves
                        registry.protective_set for this config's
                        [soda2].probetype; 'on' applies every PROTECTIVE name
                        regardless of probe; 'off' applies none of them.
                        Omitted, the config's [enhancements] protective =
                        true/false decides (else 'auto'). An explicit
                        [enhancements] <name> = false in the config still wins
                        over a protective default. Recorded in the .pbp.call
                        sidecar's enhancements.protective_mode/protective_set

The config file: [run] holds engine = "soda2" and, optionally, jit = true
(the same switch as --jit, and the two are ORed); [soda2] holds the op
fields, names unchanged from IDL; [enhancements] is optional. No [fidelity]
table: the SODA-2 engine has one source tree and reads no UIOOPS profile, so
naming one is refused. Raw file and output
directory are [soda2].fn and [soda2].outdir (--out overrides outdir).

IDL types: TOML carries no IDL type, so every [soda2] number arrives as a
Python int or float, where the IDL op held INT or FLOAT. A field left out
takes soda2_update_op's default with IDL's own dtype. In IDL, activetime =
fltarr(n) + op.rate is FLOAT unless op.rate is DOUBLE (1.0d). The driver
reads a Python int rate as INT, so rate = 1 gives FLOAT as example_batch.pro's
rate=1 does; a TOML float such as rate = 1.0 is DOUBLE. A nonzero FLOAT
timeoffset is widened from FLOAT in IDL; to reproduce it, call the driver
from Python with numpy.float32 values, e.g. op["timeoffset"] =
numpy.float32(0.5):
  from arrayprobe_soda2.process_2d import soda2_process_2d
```

### `soda2 enhancements`

```
usage: arrayprobe soda2 enhancements [-h] [--protective {auto,on,off}]
                                     [config]

positional arguments:
  config

options:
  -h, --help            show this help message and exit
  --protective {auto,on,off}
                        same meaning as `soda2 run --protective`
```

## `reproduce-report`

```
usage: arrayprobe reproduce-report [-h] [--out OUT] [--json JSON]
                                   product archived

Read-only. Compares every variable the two netCDF files share, cell by cell,
and reports cells compared, exact matches, max absolute and relative residual,
every differing cell, and the engine and .call stamp of each file. Exits 0
when exact, 1 otherwise.

positional arguments:
  product      the product to check (netCDF)
  archived     the archived product (netCDF)

options:
  -h, --help   show this help message and exit
  --out OUT    write the Markdown report here (default: stdout)
  --json JSON  also write the report as JSON here
```

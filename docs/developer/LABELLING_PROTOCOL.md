# The labelling protocol — eye adjudication when there is no product of record

**Why this document exists.** For new processing of new data there is **no product of record and
no truth**. The project's three validation layers do not reach
it: layer 1 needs an archived product to compare against, layer 2 needs the original source
executing on the same bytes, layer 3 needs documented semantics for the quantity in question. Where
no product of record exists, none of the three is available. **So the adjudicator is human judgement on the particle
images**, through `arrayprobe.triage_server` and the gallery — not as a fallback, but as the only
instrument that can decide.

That has been done once, by practice rather than by protocol: 2016-09-06, 2D-S file `064403`,
one flight minute, 437 of 447 queued particles labelled, scored 2026-09-14. This document is that
practice written down precisely enough that someone else can run it and that a number derived
from it survives questioning.

Every statement below is tagged **measured** (run or read out of a produced file), **derived**
(follows from something measured), or **read** (read out of source without executing it). Where
the existing practice has no rule, the section says **not established** rather than inventing one.

---

## 1. How the queue is built — from chain disagreement, never at random

**A labelling pass is not a random audit of a flight.** Random sampling spends a human's attention
in proportion to the population, which is dominated by cells where both chains already agree. The
queue is built from the **cross-table of the two packages' verdicts**, one queue per cell, so the
labeller's attention lands where the chains disagree and the disagreement can be attributed to a
named criterion.

### 1.1 Pair the particles

The pairing tool matches the two packages' particles one to one on the raw 2D-S
particle header — the probe's 16-bit counter and the 32-bit particle clock (`compare_soda2_uiops.py:9-14`,
**read**). Both packages keep both fields, so the key is a property of the raw file and not of
either chain. A particle one package has and the other does not is **reported, never dropped**
(same lines): the two chains framing particles differently is itself a finding, and hiding it
inside a pairing would destroy it.

Each side is then reduced to one verdict per particle:

- **UIOOPS verdict** — the first gate in `sizeDist.m`'s own order that removes the particle
  (imgProc reject code, `I`, `z`, `S`, centre-in), from the production `sizeDist` replay in
  a reject-stage tally, which the pairing tool verifies cell for cell against the written
  `count` (`compare_soda2_uiops.py:16-19`, **read**).
- **SODA-2 verdict** — `rejectionflag`, decomposed into its named bits
  (`arearatio`, `interarrival`, `size_range`, `centerin`, `cluster`, `water`, `irregular`, `dof`;
  `compare_soda2_uiops.py:51-52`). It is stored `NC_BYTE`, so bit 128 reads −128 and is taken
  `& 0xFF` (finding S6-k, `:20-21`).

A particle can carry several SODA-2 bits, so a cell name like `imgproc_a / arearatio+interarrival`
is one cell, not two.

### 1.2 Sample each cell

`review_queues` (`compare_soda2_uiops.py:200-229`, **read**) writes one triage queue per
(UIOOPS verdict, SODA-2 verdict) cell, with these defaults:

| Parameter | Default | What it does |
|---|---|---|
| `per_cell` | 20 | up to this many particles sampled from the cell |
| `min_cell` | 5 | a cell with fewer matched particles gets **no queue at all** |
| `min_um` | 0.0 (CLI `--min-um`) | size floor on the UIOOPS `image_diam_minR` |
| `seed` | 20260915 | `np.random.default_rng(seed)`; the sample is reproducible |

Within a cell the sample **is** random (`rng.choice(..., replace=False)`, `:223`) — randomness
belongs inside a cell, where it makes the cell's labelled fraction an estimate of the cell's
fraction; it does not belong across cells, where it would just re-sample the population.

**Agreement cells are queued too** (`:204-205`): `accepted / accepted` and similar are the
controls the labeller calibrates against. In the 2026-09-15 pass they came out 1.00 real over 20
labels (label-scoring report, lines 31, **measured**) — which is what makes the 0.00-real cells
believable rather than a sign the labeller was rejecting everything.

Indices in the queue are the **UIOOPS proc's own 0-based rows**, which is what the triage server
reads, so the image the labeller sees is the UIOOPS reconstruction (`:205-206`). **Not established:**
whether a pass should be repeated against the SODA-2 reconstruction of the same particles. Only the
UIOOPS images have ever been labelled.

The pairing was run on one UIOOPS proc file and one SODA-2 `.pbp.nc` file, with the UIOOPS side's TAS supplied
as a CSV where the proc file did not carry it, a 105 µm floor, a queue output file and the flight stem. The
comparison tool is a development script that this package does not ship. Writing a queue file requires the
flight name (`:253-254`). The written file carries an `_about` block naming
the tool, the seed, `min_um` and `per_cell` (`:215-219`), and each item's `note` states its cell
and the **cell's full matched count** (`:226-228`) — so the queue file alone says what fraction of
each cell was shown.

### 1.3 The other sampler, and when it applies

`arrayprobe.review_sampling` builds a *stratified* queue over one proc's own variables, with a
`_coverage` statement written into the same file under `COVERAGE_KEY = "_coverage"`
(`review_sampling.py:59-62`, **read**). Its size strata are deliberately coarse, to spread
attention across sizes rather than to measure a distribution (`:75-79`). **That is the sampler for
one chain in isolation.** The disagreement sampler above is the one this protocol specifies,
because a disagreement cell is what a label can adjudicate.

---

## 2. How many labels per cell, and when a cell has enough

**What was done (measured):** 19–20 labels per cell, against cell populations of 123–479 for the
cells that mattered, with a Wilson 95 % interval reported per cell
(`score_soda2_uiops_labels.py:57-65`, label-scoring report, lines 17-44).

**The rules this establishes:**

1. **A cell below `min_cell` (5) gets no queue and no fraction.** Not a small fraction — none.
2. **Report the interval, always, per cell.** `f_real` without its `n` and interval is not a number
   this protocol produces.
3. **A cell is "enough" when the interval is narrow enough to separate it from the claim being
   made, not at a fixed count.** Twenty labels give roughly ±0.16 at the extremes and ±0.20 in the
   middle (**measured**, the report's own intervals). That separates 0.00 from 0.79. It does not
   separate 0.60 from 0.79, and no claim in the 2026-09-15 scoring depends on it doing so.

### The dominant uncertainty is not the interval

**Say this plainly wherever a scaled number is quoted.** The Wilson interval measures sampling
error *within* the labelled sample. The step that carries the real risk is the one after it: each
cell's fraction is applied to the cell's whole paired population — "each cell is like its sample"
(`score_soda2_uiops_labels.py:15-18`, and the report's own heading,
label-scoring report, lines 49). **Extrapolating ~20 labels to a cell of several hundred is the
dominant uncertainty, larger than the interval printed beside it.** The interval is what the
arithmetic can see; the extrapolation is what it cannot. A reader given only the interval will
under-read the uncertainty by an unknown factor.

**Not established:** any test of that assumption. Nobody has labelled one cell densely — 100+ of a
479-particle cell — to measure whether its fraction is stable as the sample grows. Until that is
done the linear scaling is an unvalidated assumption, and every band table derived from it
inherits that status.

---

## 3. What the labeller sees and decides

The labeller is shown one particle image at a time — the UIOOPS reconstruction from the proc — with
its queue `note` naming the cell, the two diameters and the UT second (`compare_soda2_uiops.py:226-228`).

The verdict vocabulary is fixed in code and validated server-side, because a POST body is otherwise
free-form text that reaches the sidecar and an HTML class attribute
(`triage_server.py:136-147`, **read**):

```
VALID_VERDICTS = frozenset({"artifact", "real", "unsure", "mixed"})
```

| Verdict | Means |
|---|---|
| `real` | a real hydrometeor image |
| `artifact` | not a particle: a streak, a stuck diode, a sparse or shattered fragment image |
| `mixed` | **more than one thing in one image** — a real droplet *and* an artifact. Added as the fourth label (`triage_server.py:142-146`) because reviewers had been forced to record it as `unsure`, collapsing a real category into the "could not tell" bucket and poisoning both. In the 2026-09-15 pass most mixed images in the `size_range` cells were a real droplet beside a stuck diode (label-scoring report, lines 46-47) |
| `unsure` | the reviewer could not decide from the image |

**`unsure` is counted and reported, and kept out of every denominator.** The scorer's denominator
is `SCORED = ("real", "mixed", "artifact")` (`score_soda2_uiops_labels.py:52-54`, `:138-141`), and
`unsure` appears in its own column of every cell row (`:144`). It is never discarded silently: an
`unsure` rate that climbs is evidence about the images, and a protocol that deletes it cannot see
that.

`mixed` **is** in the denominator, and the scorer carries two fractions per cell — real, and
real-plus-mixed (`:141`) — so a band table can be read both ways. Neither `unsure` nor `mixed` may
be fed to a classifier as ground truth (`TRAINING_EXCLUDED`, `triage_server.py:149-154`): that is a
separate consumer with a stricter rule than this one. **Why the split matters for scoring**: a
`mixed` image is a real measurement of a genuinely ambiguous particle — count it. An `unsure` label
is an absence of a verdict — it says the reviewer could not decide, not that the particle was
anything in particular, and averaging it into a fraction would silently turn "I don't know" into
evidence.

### 3.1 The viewer (read)

Keyboard labelling exists so a pass of hundreds of particles does not mean reaching for the
mouse every time (`triage_server.py:1727-1751`, **read**). Keys dispatch a click on the existing
verdict button rather than posting anything themselves, so saving, the selected highlight, queue
provenance and auto-advance all stay on the one code path the mouse already used:

| Key | Verdict / action |
|---|---|
| `a` | `artifact` |
| `r` | `real` |
| `t` | `mixed` ("two particles") |
| `u` | `unsure` |
| `&larr;` / `p` | previous particle |
| `&rarr;` / `n` | next particle |
| `Esc` | leaves the comment box, so the keys work again |

A **comment box** sits beside the four buttons — free text, saved with whichever verdict is
clicked next, capped at 2000 characters (`COMMENT_MAX_CHARS`, `triage_server.py:432`) and stored
in the label's own `comment` field when non-empty (`:483-485`). It exists for the case a fixed
vocabulary states badly — e.g. "two touching drops, called it real on the larger."

**`--reviewer` / `ARRAYPROBE_REVIEWER`** name who is labelling for the whole server session
(`triage_server.py:2060-2065`, `REVIEWER_ENV = "ARRAYPROBE_REVIEWER"` at `:411`). This is server
state, not something a page posts: `_reviewer_for` reads the body only as a fallback for a script
POSTing its own `reviewer`, and the rendered verdict button sends none (`:1051-1064`, `:1710-1712`,
**read** by inspecting the emitted JavaScript) — so no page can decide whose label this is. Unset,
the startup banner says so plainly ("Reviewer: NOT SET — labels will record no reviewer") and every
label from that session carries none (`:2011-2014`).

**Queue titles are rendered in words**, not just the raw cell key. A queue name such as
`U-z__S-accepted` is built for a filename, not for a person deciding what a particle is; `arrayprobe
triage`'s queue list shows `describe_queue(name)` — "UIOOPS rejects: area ratio below 0.5 ·
SODA-2 accepts" — with the raw name kept underneath in small type, because that is what the files
and scores are still keyed on (`triage_server.py:196-282`). Both vocabularies are read from their sources (`compare_soda2_uiops.uiops_reasons`,
`matlab_compat.REJECT_CODES`, `compare_soda2_uiops.SODA2_BITS`), and an unknown token is shown
verbatim rather than guessed at. **One trap worth knowing**: UIOOPS's queue token `z` here is
`sizeDist`'s area-ratio gate, not imgproc's own zero-area code of the same letter — the two are
different tests sharing a character.

---

## 4. What provenance travels with a label set

Labels are written to `<decoded_dir>/triage_verdicts/<flight>.json`, which sits beside the decoded
files and is gitignored — so the only copy of every hand label is one file on one disk
(`export_human_verdicts.py:3-6`). `scripts/export_human_verdicts.py` copies them into the repository
at `developer/data/labels/triage/<decoded_dir>__<flight>.json`, **`source: "human"` records only and nothing the
code wrote** (`:6-8`). It is deterministic: re-running with no new labels rewrites identical bytes
(`:15`).

Each record carries, per label (`triage_server.py:301-312`, `export_human_verdicts.py:38,72-76`):

| Field | What it pins |
|---|---|
| `verdict`, `note` | the decision |
| `at` | UTC ISO-8601, to the second |
| `source` | `human` / `bulk-cluster` / `model` — required, keyword-only, no default (`triage_server.py:162, 295-298, 319-321`). A verdict of unknown origin cannot be filtered out of a set later, and filtering it out later is the whole point |
| `tool` | the package version that rendered the image the label was made on |
| `reviewer`, `queue` | who, and which queue — written only if supplied |
| `Particle_number_all`, `particle_microsec`, `Time`, `msec`, `parent_rec_num` | **the particle's raw identity**, not just its row |
| `image_diam_minR`, `image_auto_reject`, `image_length`, `image_width` | context from the proc |

And per set: `flight`, `probe`, `decoded_dir`, `n_labels`, and the proc it was made against as
**name, byte size and SHA-256** (`export_human_verdicts.py:81`). **The sha256 is what makes a score
re-checkable** — it names the exact file whose rows the indices point into, so a reader can
establish that a reported fraction was computed against the same bytes.

**Why raw identity and not the index.** `particle_index` is a row of one proc file, and
reprocessing renumbers rows (`export_human_verdicts.py:9-14`). Carrying the probe counter and clock
means a label stays attached to its particle through any later processing of the same raw file — so
the same labels score a re-paired run (SODA-2 with enhancements on, or the v3.5 engine) **without
relabelling** (`score_soda2_uiops_labels.py:20-25`). That is the single most valuable property of
the format, and it is why a pass is worth running carefully once.

### The gap, and how it closed

**In the first pass, `reviewer` and `queue` were `null` on every label.** Verified by
reading the triage label files for `base160906064403` and `cip160906s1` in the triage label folder (not included in this release) (**measured**).
The cause was not an omission by the labeller: the server accepted `reviewer` and `queue` from a
POST body, but the rendered verdict button posted only `{flight, particle_index, verdict}` — no
page sent either field, so no browser label could carry them.

**Both are recorded, by two different mechanisms.** *Queue* is
posted by the rendered button on every save — the fetch body carries `queue` (`_recordable_queue`
of the queue the particle was served from, `triage_server.py:1664`, `:1710-1711`), so a label made
while working a named queue records that queue automatically. *Reviewer* did **not** end up as a
posted field: the design that shipped is server state instead — set once, at `arrayprobe triage
--reviewer <name>` / `ARRAYPROBE_REVIEWER`, and stamped on every label for that whole session
(§3.1). That is a stronger closing than a per-post field would have been, because a page cannot lie
about whose label it is by omitting or mistyping a value — the identity is fixed for the process,
not re-asserted per click.

Consequences:

- *Who labelled* a new pass is in the file, per label, once the server was started with
  `--reviewer`/`ARRAYPROBE_REVIEWER`. A pass run
  without either still records no reviewer, and the startup banner says so (§3.1); **a labeller
  running a real pass should always set one.**
- *Which queue* a label was made in is in the record automatically for anything labelled
  through a queue. The scorer still re-derives the cell from the pairing rather than trusting the
  stored name (`score_soda2_uiops_labels.py:19-25`) — that remains the better design regardless —
  and still optionally filters to the queue file's sampled rows (`--queue-file`).
- The existing 2026-09-15 label set is unaffected retroactively: its `reviewer`/`queue` fields stay
  `null`, because relabelling is not how this closes. Only labels made from here on carry them.

### Labels made outside the queue

The exported 2D-S set holds **466** labels (`n_labels`, **measured**) where the pass queued 447 and
labelled 437 of them (label-scoring report, lines 12-13). The difference is labels made
while browsing, outside any random sample. **A fraction is an estimate only for a random sample, and
a particle labelled while browsing is not one** (`score_soda2_uiops_labels.py:99-101`). So:

> **Score with `--queue-file` pointing at the queue the pass was built from.** Labels not in the
> sample are reported as `not_in_queue_sample` under `unplaced` (`:121-123`), never dropped
> silently. Without it every placed label counts — more labels, but not all of them random, and the
> Wilson interval then means less than it says.

Every other way a label can fail to place is reported too: `not_in_uiops_proc`, `ambiguous_key`,
`not_paired`, `below_min_um` (`:117-130`). **A label is never discarded without appearing in a
count.**

---

## 5. How a score is reported, and what it licenses

The scoring tool produces two tables:

**Per cell** — for each (UIOOPS verdict, SODA-2 verdict) cell at or above `--min-um`: the cell's
paired count, how many carry a label, the real / mixed / artifact / unsure counts, the fraction
real, and its Wilson 95 % interval.

**Per band** — UIOOPS `image_diam_minR` in 105–205, 205–305, ≥ 305 µm (`BANDS`, `:50-51`): each
cell's fraction applied to that cell's paired count in the band, giving estimated real particles and
how many of them each package accepts. The table also prints `paired_in_unlabelled_cells`
(`:164-168`) — the paired particles in cells that carry no label at all, which is the part of the
band the estimate says nothing about.

### The rules

1. **Never pool the cells into one number.** The per-cell table *is* the result. A single "fraction
   real for the flight" would average a 0.00 cell of 1,658 particles with a 1.00 cell of 106 and
   report something that describes no decision either chain made.
2. **Every fraction is quoted with its `n` and its interval.** A bare `0.79` is not a number this
   protocol produces.
3. **Every band number states the linear assumption and that it is unvalidated** (§2).
4. **Name the scope.** The 2026-09-15 result is *one flight, one file, one 38-second window*
   (label-scoring report, lines 7-11). It is not the flight, not the campaign, not the probe.

### What a score is, and is not

**It is a human-agreement measure.** It says how often a human, shown the image, agrees with a
package's decision on that particle. That is exactly what makes it the adjudicator where no truth
exists — and exactly what stops it being anything more.

**It is not a fidelity claim.** Fidelity here means reproducing an archived product bit for bit,
and that claim belongs to the v3.1.4 engine against an archived MATLAB product. A label set cannot
support it and must never be cited beside it as if it were the same kind of evidence.

**It is not validation.** No external instrument, no independent measurement, no ground truth is
involved. The correct vocabulary for the validation matrix is **adjudicated by eye, with n and
labeller stated** — a third mode, distinct from layer 1 and
layer 2, never recorded as either and never recorded as "unvalidated".

**What it does license is substantial.** It converts an unattributable disagreement into
an interpretable one, and it *bounds*. In the 2026-09-15 pass most disagreement cells came out 0.00 real —
both packages correctly dropping them — and the disagreement collapsed onto `z / accepted` at
**0.79 real over a 479-particle cell** (**measured**), i.e. UIOOPS's ORACLES area-ratio gate
discarding roughly four in five real particles SODA-2 keeps. And it bounds what acceptance can
explain at all: ~8 % of the paired population ≥ 105 µm, against chain ratios of 5–11× — which is
how we know the large ratios are a **denominator** difference, not an acceptance difference. A
bound of that kind is a result, and it came from 437 labels.

---

## 6. The failure modes

Stated honestly, each with what is actually done about it, and marked where nothing is.

### 6.1 A queue built from one flight minute

**The real limitation of the existing pass.** All 437 labels come from 06:55:00–06:55:38 of one
2D-S file (label-scoring report, lines 7-11). A 38-second window samples one cloud, one habit mix,
one shattering regime. Nothing in the tooling prevents generalising from it; only the report's own
scope line does.

**What is done:** every number from the pass states its window, and the report is marked
report-only, with no outward surface quoting it until it is cleared (`:3-5`). **What is
not:** no rule fixes a minimum number of windows or flights for a new campaign. **Not established.**
For a new campaign the first pass should span more than one window for the plain reason that one window has
never been shown to be representative — but the count is a choice for the project lead, not a protocol rule
this document may invent.

### 6.2 The labeller knows which chain produced which verdict

The queue `note` names the cell — `UIOOPS imgproc_a / SODA-2 arearatio` — and the queue file's name
encodes it (`queue_name`, `compare_soda2_uiops.py:195-197`). **So the existing pass was not blind.**
A labeller who knows one package rejected a particle can be pulled toward agreeing with it.

**What limits the damage today:** the agreement cells are queued as controls (`:204-205`), and they
came out 1.00 real over 20 and 0.00 over 20 in the cells at the extremes — so systematic
rubber-stamping would have shown up there. That is a check on gross bias, not on a subtle one.

**Not established:** there is no blinded mode. Removing the cell name from the note and shuffling
the queues would give one, and would cost the labeller the context that makes a hard image
interpretable. Nobody has decided that trade. **A new pass should record whether it was blinded,
because the existing set cannot claim it.**

### 6.3 Cells too thin to support a fraction

A cell of 6 paired particles with 6 labels reports `0.50 [0.19, 0.81]` (label-scoring report, lines 42)
— arithmetically correct and scientifically empty.

**What is done:** `min_cell = 5` keeps the thinnest cells out of the queue entirely
(`compare_soda2_uiops.py:221-222`), and every cell prints its `n` and interval so a reader can see
a wide one. **The rule this protocol adds:** *a cell whose interval spans more than about 0.4 may
appear in the table but may not carry a claim.* Below roughly 15 labels, no cell clears that.

### 6.4 Labelling until the answer looks right

The temptation is real and the mechanism is specific: label a cell, see a fraction that does not
suit, label a few more. The seeded sample, the `per_cell` cap and the `at` timestamps make it
visible after the fact, but nothing prevents it.

**What is done:**

- The sample is **seeded** (`seed=20260915`, `:211`), so the queue is fixed before any label exists
  and is reproducible from the queue file's own `_about` block.
- `per_cell` caps how many of a cell are shown.
- `--queue-file` excludes anything labelled outside the sample from the score (§4).
- Every label carries `at` to the second, so the order a set was built in is inspectable.

**The rules this protocol adds:**

1. **Build the queue, then label it, and do not rebuild it after seeing a result.** A second queue
   on the same cells is a second pass with its own seed and its own report, not an extension of the
   first.
2. **Label a queue through** — a cell abandoned partway biases toward whatever the labeller saw
   first. The existing pass labelled 437 of 447, and the ten unlabelled are why the per-cell
   `labelled` column exists rather than being assumed equal to `per_cell`.
3. **Score once, with `--queue-file`, and report the unplaced counts.**

**Not established:** no second labeller has ever labelled the same particles, so **there is no
inter-labeller agreement number for this project**. Every fraction reported so far is one person's
eye. That is the single largest unmeasured quantity in the method, and the cheapest one to fix: one
overlapping queue of 40 particles, two labellers, one agreement rate.

---

## Running a pass — the steps, as they were actually run

Step 1 pairs the chains and writes one queue per disagreement cell: it took the UIOOPS proc file and the SODA-2
`.pbp.nc` file, the TAS CSV, a 105 µm floor, a time window (`065500-065538`), an output queue file and the
flight stem. It was run by a development script that this package does not ship. Steps 2-4 run from the
repository root (Linux/macOS: `.venv/bin/python` in place of `.venv/Scripts/python.exe` throughout):

```bash
# 2. Label in the viewer, driven by that queue file. --reviewer names who is
#    labelling for this whole session (§3.1); every label made below carries it.
.venv/Scripts/python.exe -m arrayprobe.triage_server \
    --decoded-dir ../_decoded --queue-file queues.json --reviewer <your-name>

# 3. Export the human labels (source: human only, deterministic); without --out they go to
#    exported_labels inside the decoded directory.
.venv/Scripts/python.exe scripts/export_human_verdicts.py --decoded-dir ../_decoded
```

Step 4 scores per cell with n and Wilson interval, and per band with the linear assumption stated. It took the
proc and `.pbp.nc` files and TAS CSV of step 1, the exported labels, the same 105 µm floor and time window, the
queue file of step 1 and a JSON output path, and was run by a development script that this package does not
ship. Its queue-file argument is not optional in this protocol (§4). Step 3 writes `source: human`
records only, so a clustering bulk label or a model prediction can never reach a score
(`export_human_verdicts.py:6-8`, `triage_server.py:156-162`).

### The same commands, general form, and the export/score half from the repository root

Steps 3-4 take absolute or repo-relative paths and are equally usable from the repository root, which is how
they were run during a pass on one flight. The export writes a specific decoded directory's
verdicts to a named output subdirectory:

```bash
# 3. Export a specific decoded directory's verdicts to a named output subdirectory.
.venv/Scripts/python.exe scripts/export_human_verdicts.py \
    --decoded-dir <decoded_dir> --out developer/data/labels/<set-name>
# Linux/macOS: .venv/bin/python ...
```

The scoring step took the proc file `<decoded_dir>/proc.<flight>.<chan>.nc`, then the paired SODA-2 `.pbp.nc`,
the exported labels file for that decoded directory and flight, the queue file the pass was built from, and a
`--min-um` floor; 55 µm was one pass's floor, and a campaign sets its own (see below).

The two positional arguments to step 4 are always the same pair, whatever the campaign: the UIOOPS
`proc.<flight>.<chan>.nc` and the SODA-2 `.pbp.nc` for the *same raw file* — `--tas-csv` is optional
and needed only when the UIOOPS side's own TAS is not already in the proc file. `--min-um` is a
campaign choice, not a fixed number (ORACLES-2016's 105 µm floor does not necessarily apply to
another probe's mounting or DOF); one reported pass used 55 µm.

**The 2017-07-07 pass is complete: 371 labels, 371 placed, 0 unplaced, across 20 cells** — every
cell at the protocol's 20-label target or exhausted below it. This replaces the 2026-09-16 mid-pass
snapshot this section once reported (98 placed, 0 unplaced); that count is stale and should
not be quoted.

**Measured on the completed set, not carried over from the mid-pass point:** the
`accepted / accepted` agreement-cell control (§1.2) scores **0.95 real, Wilson 95 % [0.76, 0.99],
over 20 labels from a paired population of 1,890**. Scored 2026-09-17; the final 20-cell result supersedes
the earlier 238-label scoring. Two things about the control are worth stating plainly:

- **The control is not filler — check it first.** §1.2 already says agreement cells calibrate the
  pass; a control that comes out low means the labelling or the pairing is wrong, and every
  disagreement-cell fraction in the same pass should be read with that in mind *before* any of them
  are quoted.
- **A label is placed by the particle's raw identity, not by the queue it was reviewed in** (§4):
  the scorer re-derives which cell a label belongs to from the UIOPS/SODA-2 pairing at scoring
  time, using the particle's probe counter and clock rather than a stored queue name. This is why
  the same label set can score a re-paired run — enhancements on vs. off, a different engine — with
  no relabelling.

**Provenance.** Both numbers above are measured, not relayed: the scorer was re-run on the
label file for one flight (not included in this release, `n_labels` 371) against the
same queue the pass was built from, and printed `Labels: 371, placed 371, unplaced 0.`

**What is still self-reported, and stays flagged:** that the labeller considers the pass finished.
Completeness against the protocol's per-cell target is measured; "finished" is a judgement, and one
cell (`imgproc_i / interarrival`) reached its target only in this final pass after being reported
thin at 5 of 20 earlier the same day.

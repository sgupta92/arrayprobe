# 2. Processing

**What it is for.** Running the package on data of your own: other probes, whole campaigns,
your own configuration, and every switch that changes what is computed.

**Who it is for.** Someone who has finished `1_getting_started` and has, or is about to have,
raw probe files. The SODA-2 engine's end-to-end run is `1_getting_started/04_soda2_end_to_end`.

**Order.**

1. `08_opt_ins`: every switch that is off by default, and how to turn it on.
2. `09_enhancement_ab`: choosing an engine and an enhancement and seeing the effect on a size distribution.
3. `10_labelling_particles`: labelling in detail: the verdict store, review queues, keyboard keys, the triage server run from Python, and the piece-gap setting.
4. `07_reproducible_runs`: configuration files, the stamp each run leaves, and re-running a product from its stamp.
5. `03_whole_campaign`: many files at once, in parallel, with a resumable run.
6. `06_your_own_profile`: defining and selecting your own processing configuration.

**What you need.** Found by reading each notebook's code cells. Run from the repository root.

| Notebook | Beyond the core package | Data |
|---|---|---|
| `03_whole_campaign` | Launches `scripts/run_flight.py` as subprocesses; `numba` optional (adds the `--jit` run when present) | Synthetic files generated in the notebook. Give it a few minutes |
| `06_your_own_profile` | None beyond the core and v3.5 engine | Writes its own small TOML files and an example product in a work folder |
| `07_reproducible_runs` | None | Shipped fixtures `tests/data/demo_flight_dense_raw.2DS`, `demo_flight_v35_run.toml`, `demo_flight_v314_raw.2DS`, `demo_flight_v35_aircraft.cdf` |
| `08_opt_ins` | Enhancements package, and the SODA-2 enhancements package (each guarded; the second falls back to `enhancements_soda2/src` in a checkout) | None (writes a `run.toml`) |
| `09_enhancement_ab` | Enhancements package (`outoffocus`), required; v3.1.4 engine half runs only if installed | Shipped `tests/data/demo_flight_dense_raw.2DS` |
| `10_labelling_particles` | Starts a triage server on localhost and reads it with `urllib` (no outside network) | Copies the shipped `tests/data/demo_flight_dense_raw.2DS` |

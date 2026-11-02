# 7. Analysis and outputs

**What it is for.** Comparing products and probes, and writing results in forms that other
people and other tools can read, with a record of how each file was made.

**Who it is for.** Users who have processed data and need to compare it, share it, or feed it
to other software.

**Order.**

1. `01_cip_vs_2ds`: comparing two different probes, and the four ways the comparison misleads.
2. `02_probe_overlap_check`: whether two probes agree where their size ranges overlap.
3. `03_comparing_processing_chains_in_db`: comparing two chains' size distributions on a common time axis, with lag scan, cloud-leg composites and differences in dB.
4. `04_output_formats_and_tables`: one product as netCDF, Zarr and Parquet tables, with read costs.
5. `05_ml_particle_table`: a machine-learning-ready particle table, split by file.
6. `06_provenance`: reading which engine and configuration made a file, and checking the file is the original.
7. `07_arco_export_tour`: converting port output to an analysis-ready file without losing a value.
8. `08_enhancements_on_a_product`: the optional enhancements run on a processed product (read `1_getting_started/06_read_products` first).

**What you need.** Found by reading each notebook's code cells. Every notebook generates its
own input; none needs a file you supply. Run from the repository root.

| Notebook | Beyond the core package | Data |
|---|---|---|
| `01_cip_vs_2ds` | `arrayprobe.tools.probe_comparison` (core); v3.5 engine `sizedist_tables`; scipy. No enhancements | Synthetic 2D-S and CIP products written in the notebook |
| `02_probe_overlap_check` | Enhancements package (`probe_crossover`) | Seeded random data |
| `03_comparing_processing_chains_in_db` | Enhancements package (`analysis`), used by the appended composite sections | Seeded random data |
| `04_output_formats_and_tables` | **zarr** (required) and, for the Parquet cells, `pyarrow` and `pandas` via the `[parquet]` extra (guarded: prints an install line and skips) | Stand-in products built in the notebook |
| `05_ml_particle_table` | pandas (required) | Synthetic label sidecars built in the notebook |
| `06_provenance` | None | A stand-in product built in the notebook |
| `07_arco_export_tour` | Enhancements package (`arco_export`), xarray, netCDF4 | Writes a stand-in `proc_example.nc` unless a file of that name exists; point `SOURCE` at a real port output if you have one |
| `08_enhancements_on_a_product` | The enhancements package (`arrayprobe_enhancements`), optional: each enhancement section prints a skip message without it | Demo flight generated; shipped synthetic fixtures `tests/data/v35_probetype1_sizedist/test_cip.sd.nc` and `tests/data/v35_sizedist/main.nc` |

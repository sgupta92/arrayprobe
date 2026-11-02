# Examples

Runnable notebooks, grouped into seven tracks. Almost every notebook builds its own small
input (a synthetic probe flight, or seeded random size distributions), so you can run it
without any campaign data. Each track folder has its own README with the reading order, what
you need, and which notebooks read a file you supply.

## How to use the tracks

If you are new, open `1_getting_started/01_start_here.ipynb` and work through that track in
order; it takes about an hour and needs no knowledge of Python or of probe processing. After
that, pick the track that matches what you want to do next:

- `2_processing`: run the package on your own files.
- `3_validation`: find out whether a result can be trusted.
- `4_methods_and_literature`: the published methods the processing follows.
- `5_data_quality`: something odd in a size distribution (a spike, an empty second, a particle
  too big to be real); each notebook shows one artifact, how it looks, and how to test your own
  data for it.
- `6_science`: turn size distributions into quantities such as water content and reflectivity.
- `7_analysis_and_outputs`: compare products and write files others can read.

Notebooks are numbered within each track; read a track top to bottom the first time, then dip
in by title.

The notebooks run from a clone of the repository, not from a PyPI install: they start at the
repository root and read its `scripts/` and `tests/data/` folders. From a clone of the
repository, run a notebook from the repository root (`jupyter notebook examples/`); the working
directory matters because the notebooks locate the demo data from there.

"Prerequisites" lists the notebooks to read first and what each notebook imports or reads
beyond the core package, taken from its code cells. "Enhancements" means the
`arrayprobe-uiops-enhancements` package. "The v3.1.4 engine" is an earlier translation of
UIOOPS v3.1.4, which is not part of this package; a section that uses it carries a note inside
the notebook.

## 1_getting_started

| # | Notebook | What you learn | Prerequisites |
|---|---|---|---|
| 01 | [`01_start_here`](1_getting_started/01_start_here.ipynb) | Process one synthetic probe file and look at the particle images, verdicts and size distribution | None; demo data generated, shipped fixtures |
| 02 | [`02_quickstart`](1_getting_started/02_quickstart.ipynb) | The raw-file-to-size-distribution chain in five cells | 01; demo data generated |
| 03 | [`03_choosing_an_engine`](1_getting_started/03_choosing_an_engine.ipynb) | The two engines, what each is for, and how they differ on the same known-truth data | 02; runs the v3.5 and SODA-2 engines on the same data; shipped SODA-2 config |
| 04 | [`04_soda2_end_to_end`](1_getting_started/04_soda2_end_to_end.ipynb) | Run the SODA-2 engine on a known-truth flight | 03; SODA-2 engine; shipped SODA-2 config |
| 05 | [`05_triage_and_gallery`](1_getting_started/05_triage_and_gallery.ipynb) | Look at particles as a contact sheet and a gallery, and start the triage page to label them | 02; shipped raw demo file |
| 06 | [`06_read_products`](1_getting_started/06_read_products.ipynb) | How to open the output files directly and read what each variable means | 02 |
| 07 | [`07_working_with_an_ai_assistant`](1_getting_started/07_working_with_an_ai_assistant.ipynb) | The prompts to give an AI coding assistant: a first prompt, the questions it must ask before processing, already-processed data, and safe practice | 06; no data |
| 08 | [`08_ai_assistant_with_your_own_data`](1_getting_started/08_ai_assistant_with_your_own_data.ipynb) | The prompts for an AI coding assistant when your data are already processed: examine them, test a feature against them, check a data-quality aspect, convert formats | 07; no data |
| 09 | [`09_ai_assistant_limits_and_ethics`](1_getting_started/09_ai_assistant_limits_and_ethics.ipynb) | Responsibility, ethics and limits of an AI assistant: data that stays out of a prompt, the jobs not to hand it, the classes of mistake it makes and the check for each | 08; no data |

## 2_processing

| # | Notebook | What you learn | Prerequisites |
|---|---|---|---|
| 03 | [`03_whole_campaign`](2_processing/03_whole_campaign.ipynb) | Run many files at once, in parallel, and resume an interrupted run | 1_getting_started; numba optional; a few minutes |
| 06 | [`06_your_own_profile`](2_processing/06_your_own_profile.ipynb) | Define and select your own processing configuration | 07 helps; builds its own files |
| 07 | [`07_reproducible_runs`](2_processing/07_reproducible_runs.ipynb) | Configuration files, the stamp each run leaves, and re-running a product from its stamp | 1_getting_started/02; runs the v3.5 engine; shipped fixtures |
| 08 | [`08_opt_ins`](2_processing/08_opt_ins.ipynb) | Every switch that is off by default and how to turn it on | 07; enhancements and SODA-2 enhancements (guarded) |
| 09 | [`09_enhancement_ab`](2_processing/09_enhancement_ab.ipynb) | Choose an engine and an enhancement, and see what it does to a size distribution | 08; enhancements (required); the v3.1.4 half is optional (that engine is not included); shipped raw file |
| 10 | [`10_labelling_particles`](2_processing/10_labelling_particles.ipynb) | Labelling in detail: the verdict store, review queues, keyboard keys, the server run from Python | 1_getting_started/05; local triage server; shipped raw demo file |

## 3_validation

| # | Notebook | What you learn | Prerequisites |
|---|---|---|---|
| 01 | [`01_validate_against_a_product`](3_validation/01_validate_against_a_product.ipynb) | Compare a processed product with a reference, on demo data and then on your own two files | 1_getting_started/03; last section needs two files you supply; optional field-campaign subset cut |
| 02 | [`02_known_truth`](3_validation/02_known_truth.ipynb) | Check each engine against a flight whose true particles are known | 3_validation/01; runs the v3.5 and SODA-2 chains against the known truth |
| 03 | [`03_preregistered_test`](3_validation/03_preregistered_test.ipynb) | Write a hypothesis and pass rule down before the data, then score it reproducibly | 3_validation/01; stand-in data generated |

## 4_methods_and_literature

| # | Notebook | What you learn | Prerequisites |
|---|---|---|---|
| 01 | [`01_enclosing_circle_conventions`](4_methods_and_literature/01_enclosing_circle_conventions.ipynb) | How three enclosing-circle definitions size the same particles | None; synthetic |
| 02 | [`02_sample_area_conventions`](4_methods_and_literature/02_sample_area_conventions.ipynb) | How three sample-area conventions change concentration | None; synthetic |

## 5_data_quality

| # | Notebook | What you learn | Prerequisites |
|---|---|---|---|
| 01 | [`01_find_stuck_diodes`](5_data_quality/01_find_stuck_diodes.ipynb) | Find stuck diodes and reprocess without them | None; demo data generated |
| 02 | [`02_airspeed_and_stuck_airspeed`](5_data_quality/02_airspeed_and_stuck_airspeed.ipynb) | Where airspeed comes from and how to catch a held value | None; stuck-airspeed section uses files you supply |
| 03 | [`03_clock_offsets`](5_data_quality/03_clock_offsets.ipynb) | Find a clock offset between products, or on the probe | None; scan on your own products uses two files you supply |
| 04 | [`04_stray_pixel_images`](5_data_quality/04_stray_pixel_images.ipynb) | Find stray-pixel images in your own data | None; synthetic images |
| 05 | [`05_images_in_pieces`](5_data_quality/05_images_in_pieces.ipynb) | Find images that break into pieces | scipy; optional `.npz` you supply |
| 06 | [`06_duplicated_seconds`](5_data_quality/06_duplicated_seconds.ipynb) | Find seconds carried twice | None; a file you supply to run on your data |
| 07 | [`07_hollow_particles`](5_data_quality/07_hollow_particles.ipynb) | Hollow particles and the Korolev size factor, between chains | None; optional processed file you supply |
| 08 | [`08_interarrival_rollover`](5_data_quality/08_interarrival_rollover.ipynb) | A particle clock that wraps or steps back | None; a file you supply to run on your data |
| 09 | [`09_shattering_interarrival_fit`](5_data_quality/09_shattering_interarrival_fit.ipynb) | Reject shattered fragments by inter-arrival time | enhancements (required) |
| 10 | [`10_check_the_phase_assumption`](5_data_quality/10_check_the_phase_assumption.ipynb) | Test whether the cloud was really liquid | None; synthetic |
| 11 | [`11_image_assisted_threshold`](5_data_quality/11_image_assisted_threshold.ipynb) | Let labelled images choose a size threshold | None; synthetic |
| 12 | [`12_particle_gallery`](5_data_quality/12_particle_gallery.ipynb) | What an ordinary day of particle images looks like, as a baseline | 1_getting_started/05 and 01; core package only |
| 13 | [`13_shattering`](5_data_quality/13_shattering.ipynb) | What shattered fragments look like | 1_getting_started/05, 12; core package only |
| 14 | [`14_stray_pixels`](5_data_quality/14_stray_pixels.ipynb) | Stray pixels beside a real particle | 1_getting_started/05, 12; core package only |
| 15 | [`15_hollow_rings`](5_data_quality/15_hollow_rings.ipynb) | Ring-shaped (hollow) images | 1_getting_started/05, 12, 14; enhancements |
| 17 | [`17_stuck_diodes`](5_data_quality/17_stuck_diodes.ipynb) | A diode stuck on, as seen in images | 1_getting_started/05, 12; core package only |
| 18 | [`18_edge_touching`](5_data_quality/18_edge_touching.ipynb) | Particles cut off by the array edge | 1_getting_started/05, 12; enhancements |
| 19 | [`19_two_particles`](5_data_quality/19_two_particles.ipynb) | Two particles read as one image | 1_getting_started/05, 12, 14; core package only |

## 6_science

| # | Notebook | What you learn | Prerequisites |
|---|---|---|---|
| 01 | [`01_microphysics_moments`](6_science/01_microphysics_moments.ipynb) | Bulk quantities from a size distribution, and comparing them between products | None; SODA-2 engine, scipy |
| 02 | [`02_counting_uncertainty`](6_science/02_counting_uncertainty.ipynb) | Per-second counting uncertainty | enhancements |
| 03 | [`03_explicit_bin_edges`](6_science/03_explicit_bin_edges.ipynb) | Bin edges, widths and re-binning | None |
| 04 | [`04_size_definition_sensitivity`](6_science/04_size_definition_sensitivity.ipynb) | How much the size definition shifts the result, in dB | enhancements |
| 05 | [`05_ice_water_content_mass_relation`](6_science/05_ice_water_content_mass_relation.ipynb) | Ice water content and the mass-diameter relation | enhancements |
| 07 | [`07_gamma_fitting`](6_science/07_gamma_fitting.ipynb) | Fit a gamma distribution to a size distribution, by least squares and by the method of moments | 01; no enhancements |

## 7_analysis_and_outputs

| # | Notebook | What you learn | Prerequisites |
|---|---|---|---|
| 01 | [`01_cip_vs_2ds`](7_analysis_and_outputs/01_cip_vs_2ds.ipynb) | Compare two different probes and avoid four misleading comparisons | None; synthetic products written in the notebook |
| 02 | [`02_probe_overlap_check`](7_analysis_and_outputs/02_probe_overlap_check.ipynb) | Test agreement where two probes' size ranges overlap | enhancements |
| 03 | [`03_comparing_processing_chains_in_db`](7_analysis_and_outputs/03_comparing_processing_chains_in_db.ipynb) | Compare two chains' size distributions in dB, with composites over a cloud leg | enhancements |
| 04 | [`04_output_formats_and_tables`](7_analysis_and_outputs/04_output_formats_and_tables.ipynb) | One product as netCDF, Zarr and Parquet, and how fast each reads | zarr (required); `[parquet]` extra optional |
| 05 | [`05_ml_particle_table`](7_analysis_and_outputs/05_ml_particle_table.ipynb) | A machine-learning-ready particle table | pandas |
| 06 | [`06_provenance`](7_analysis_and_outputs/06_provenance.ipynb) | Which engine and configuration made a file | None; a stand-in product built in the notebook |
| 07 | [`07_arco_export_tour`](7_analysis_and_outputs/07_arco_export_tour.ipynb) | Convert port output to an analysis-ready file | enhancements; optional real file to replace the stand-in |
| 08 | [`08_enhancements_on_a_product`](7_analysis_and_outputs/08_enhancements_on_a_product.ipynb) | Run the optional enhancements on a processed product: moments, two-probe check, shattering filter, CF export, partial-image habit, record strip | 1_getting_started/06; enhancements optional; shipped fixtures |

SODA-2 is cited in the form its author, Aaron Bansemer, provided:

> Aaron Bansemer. (2026). abansemer/soda2: v2.26.0 (Version v2.26.0) [Computer software]. Zenodo. https://doi.org/10.5281/zenodo.18331418

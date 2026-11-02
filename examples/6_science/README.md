# 6. Science

**What it is for.** Turning size distributions into quantities you can report (concentration,
water content, reflectivity), with an honest uncertainty and an honest statement of how much
each choice of definition matters.

**Who it is for.** Users who already have a size distribution and want to use it in an analysis.

**Order.**

1. `01_microphysics_moments`: number, mean and median-volume diameter, liquid and ice water content and reflectivity, and the choices that decide whether a comparison between products means anything.
2. `02_counting_uncertainty`: per-second counting uncertainty and the 100-particle flag.
3. `03_explicit_bin_edges`: bin edges, widths and re-binning onto a common grid without losing particles.
4. `04_size_definition_sensitivity`: how far six size definitions move a result, in dB.
5. `05_ice_water_content_mass_relation`: ice water content, and what the mass-diameter relation costs you.
7. `07_gamma_fitting`: fitting a gamma distribution ($N_0$, $\mu$, $\lambda$) to a size distribution, by least squares and by the method of moments, set beside the distribution it came from.

**What you need.** Found by reading each notebook's code cells. No notebook reads a data file;
all build seeded synthetic or random input. Reflectivity is always in dBZ, and differences
between products in dB.

| Notebook | Beyond the core package |
|---|---|
| `01_microphysics_moments` | `scripts/truth_harness`, the SODA-2 engine (`export_ascii`) |
| `02_counting_uncertainty` | Enhancements package |
| `03_explicit_bin_edges` | v3.5 engine `constants` module only; no enhancements |
| `04_size_definition_sensitivity` | Enhancements package (`dmax_sensitivity`) |
| `05_ice_water_content_mass_relation` | Enhancements package (`brown_francis_1995`) |
| `07_gamma_fitting` | `scripts/truth_harness`; no enhancements |

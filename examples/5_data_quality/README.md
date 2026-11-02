# 5. Data quality

**What it is for.** Finding things that go wrong between a probe and a size distribution.
Each notebook shows one artifact, how it looks in the images and in the numbers, and how to
test your own data for it.

**Who it is for.** Anyone who has a size distribution that looks odd, and anyone who wants to
check a dataset before drawing conclusions from it.

**Order.** Notebooks 01 to 11 are the checks and fixes, each written so you can run it on
your own files. Notebooks 12 to 15 and 17 to 19 are seven short explainers that show each artifact in
pictures; they are new and awaiting your review, and no check depends on them.

1. `01_find_stuck_diodes`: the two-pass workflow for a stuck diode.
2. `02_airspeed_and_stuck_airspeed`: where airspeed comes from, and how to catch a held value that passes range checks.
3. `03_clock_offsets`: a clock offset between two products, and particle times left on the probe clock.
4. `04_stray_pixel_images`: find images with stray pixels beside a real particle.
5. `05_images_in_pieces`: find images that break into pieces.
6. `06_duplicated_seconds`: find seconds carried twice.
7. `07_hollow_particles`: hollow particles and the Korolev size factor, between chains.
8. `08_interarrival_rollover`: a particle clock that wraps or steps back.
9. `09_shattering_interarrival_fit`: reject shattered fragments by inter-arrival time.
10. `10_check_the_phase_assumption`: test whether a campaign called liquid-only flew through sub-zero cloud.
11. `11_image_assisted_threshold`: let labelled images choose a size threshold.
12. `12_particle_gallery` (new, awaiting your review): what a normal particle looks like.
13. `13_shattering` (new, awaiting your review): shattered fragments.
14. `14_stray_pixels` (new, awaiting your review): stray pixels.
15. `15_hollow_rings` (new, awaiting your review): hollow rings.
17. `17_stuck_diodes` (new, awaiting your review): stuck diodes.
18. `18_edge_touching` (new, awaiting your review): edge-touching particles.
19. `19_two_particles` (new, awaiting your review): two particles read as one.

**Overlaps with existing notebooks.** `12_particle_gallery` to `19_two_particles` are
picture-first explainers on the same artifacts that notebooks 01 to 09 detect. Of the pairs
you named: `07_hollow_particles` here vs a planned Korolev out-of-focus and hollow notebook for `4_methods_and_literature`
(new): to be decided when the new notebook is written.

**What you need.** Found by reading each notebook's code cells. Run from the repository root.
Of the existing notebooks, only `09` needs the enhancements package.

| Notebook | Beyond the core package | Data |
|---|---|---|
| `01_find_stuck_diodes` | Uses core modules only (`diode_report`, `masks`, `cli`, `config`) | Demo flight generated in the notebook |
| `02_airspeed_and_stuck_airspeed` | xarray, netCDF4 | Demo airspeed file generated. The appended stuck-airspeed section has placeholders `my_aircraft_state.nc` and `my_probe_housekeeping.nc` for **files you supply** |
| `03_clock_offsets` | xarray, netCDF4 | Two demo products generated. `PRODUCT_A` / `PRODUCT_B` are placeholders for **two products you supply**; the scan on them runs only if both exist |
| `04_stray_pixel_images` | v3.5 engine `stray_pixel` module | Synthetic images built in the notebook |
| `05_images_in_pieces` | scipy | Synthetic images; optional `decoded_images.npz` **you supply** (`.npz`, one 2D array per particle), used only if the path exists |
| `06_duplicated_seconds` | xarray | Demo data; placeholder `my_probe_1Hz.nc` for a **file you supply** |
| `07_hollow_particles` | v3.5 engine `reject` module (`is_it_hollow`), netCDF4, xarray | Synthetic particles; optional processed file **you supply**, used only if the path exists |
| `08_interarrival_rollover` | xarray | Demo data; placeholder `my_particle_file.nc` for a **file you supply** |
| `09_shattering_interarrival_fit` | Enhancements package (required); also puts `enhancements_uiops/src` (next to `examples/`, at the repository root) on the path, so it needs either the install or a checkout | Synthetic arrival times |
| `10_check_the_phase_assumption` | None (matplotlib only) | Synthetic data |
| `11_image_assisted_threshold` | v3.5 engine modules (`measure`, `reject`, `profiles`) | Synthetic labelled images; no files |
| `12` to `19` (new) | Not yet known | Not yet known |

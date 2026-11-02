# Constant and table provenance

Every physical constant and lookup table the port carries, with **where the MATLAB takes it
from** (`file:line`, checked) and **which published source it comes from** (stated only where
the MATLAB comment or netCDF attribute names one, or where a paper was opened and the value found — the *How* column says which). A row
that says *unverified* is a stated gap, not a citation that was skipped: the rule that overrides
speed here is **never invent a citation**.

**This table is checked.** `tests/test_constant_provenance.py` reads every row, opens
the port and MATLAB sites it names, and fails when a named line does not contain the quoted
value token — so a value that moves or a line that shifts fails the suite instead of leaving a
stale citation. It checks presence at the line, not the literature attribution; that column is
prose and is verified by the reader against the paper named.

`M/` cites a file of the UIOPS v3.1.4 release by its name in the upstream UIOPS repository
(`file.m:line`; that source is not included here). `V/` is `src/arrayprobe_uiops/`, the one home
of code both engines share (`lwc_calc`, C-41 and C-42; the constants and sample-area geometry).
`P/` is the earlier v3.1.4 translation (`src/arrayprobe/`, not shipped); its rows are kept for the
upstream line they cite.

| Id | Constant / table | Port site | MATLAB site | Value token | Literature source | How established |
|---|---|---|---|---|---|---|
| C-1 | Korolev depth grid `z_d = 0:.05:8.15` | `P/reject.py:174` | `M/calculate_reject_unified.m:14` | `8.15` | Korolev (2007) — named by the netCDF attribute `M/imgProc_sm.m:353` ("Korolev (2007) correction"), not by a comment at the table itself | MATLAB attribute names the paper; table values not regenerated from its equations (unverified) |
| C-2 | Korolev size-correction factor table (`edge_0`) | `P/reject.py:174` | `M/calculate_reject_unified.m:23` | `Korolev` `1.218` | as C-1 | as C-1; the `1.218` token here is a table entry, unrelated to C-9's exponent |
| C-3 | Korolev hole-to-edge ratio table (`spot_edge`), entry 147 `0757` | `P/reject.py:234` | `M/calculate_reject_unified.m:54` | `757.0` `0757` | as C-1 | as C-1; the literal `0757` (= 757) is the preserved upstream bug of the missing decimal in spot_edge, pinned by a Korolev-table regression test (not included in this release) |
| C-4 | Effective-array-width correction `EAWri = EAWci + 0.72*diameter` (sa_method 2) | `V/sample_area.py:83` | `M/calc_sa_randombins.m:36` | `0.72` | `M/calc_sa_randombins.m:1` names "Heymsfield and Parish (1978)" for the formulation; `V/sample_area.py:5-11` record that McFarquhar et al. (2017, Meteor. Monogr. 58 ch. 11) attribute the 0.72 to the 1979 NCAR TN-137+IA instead | MATLAB header comment names 1978; the 1979 attribution is carried by the paper's references file — the check against H&P 1979 pp. 17-36 has not yet been made |
| C-5 | Laser wavelength `lambda = 680e-6` mm | `V/sample_area.py:67` | `M/calc_sa_randombins.m:40` | `680` | source not stated in the MATLAB (comment reads only "mm,laser wavelength"); unverified | read |
| C-6 | DOF for probetype 2 (HVPS) `20.52*radius^2*1000` | `V/sample_area.py:86` | `M/calc_sa_randombins.m:42` | `20.52` | source not stated in the MATLAB; unverified | read |
| C-7 | DOF otherwise `6*radius^2/lambda` | `V/sample_area.py:88` | `M/calc_sa_randombins.m:44` | `6 * radius` `6*radius` | MATLAB comment is the truncated "% Using " — source not stated; unverified | read |
| C-8 | Baker-Lawson mass prefactor `0.115/1000` | `P/sizedist.py:1094` | `M/sizeDist.m:980` | `0.115` | "Baker and Lawson method" — named by the netCDF attribute `M/sizeDist.m:1946`, no year; the matching paper is Baker & Lawson (2006) | attribute names the authors; value **not** checked against the paper (unverified) |
| C-9 | Baker-Lawson mass exponent `1.218` | `P/sizedist.py:1095` | `M/sizeDist.m:980` | `1.218` | as C-8 | as C-8 |
| C-10 | Terminal velocity: Heymsfield & Westbrook (2010) drag `C=0.35`, `epsilon=8.0` | `V/particle_physics.py:190` | `M/single_vt.m:23` | `C=0.35` `Heymsfield and Westbrook (2010)` | Heymsfield & Westbrook (2010) — named in `M/single_vt.m:3` and `:23` | MATLAB comment names the paper; constants not checked against it (unverified) |
| C-11 | Terminal velocity: Mitchell (1996) drag `C=0.6`, `epsilon=5.83` | `V/particle_physics.py:194` | `M/single_vt.m:29` | `5.83` `Heymsfield and Westbrook (2010)` | Mitchell (1996), described at `M/single_vt.m:29` as a special case of H&W 2010 | MATLAB comment names it; constants not checked (unverified) |
| C-12 | Default inter-arrival threshold `6e-6` s (ORACLES) | `V/constants.py:681` | `V/constants.py:593` | `6e-6` | not a literature value: the ORACLES-variant edit is at `sizeDist.m:269` (that tree does not ship, so the checked site is the port's record of it); its comment reads "Changed from 1e-6 to 6e-6 for ORACLES" (`V/constants.py:592`) | project configuration, measured to reproduce the product of record |
| C-13 | Gravitational acceleration `g = 9.8` | `V/particle_physics.py:179` | `M/single_vt.m:12` | `9.8` | source not stated in the MATLAB (bare `g=9.8;`, no comment); unverified | read |
| C-14 | Local `pi = 3.1415926` (shadows MATLAB's built-in `pi`) | `V/particle_physics.py:180` | `M/single_vt.m:13` | `3.1415926` | source not stated in the MATLAB; unverified | read |
| C-15 | Specific gas constant for dry air `287.15` | `V/particle_physics.py:184` | `M/single_vt.m:18` | `287.15` | source not stated in the MATLAB (the line only computes `rho_a`); unverified | read |
| C-16 | Sutherland viscosity formula constants `18.27`, `291.15`, `120` | `V/particle_physics.py:186` | `M/single_vt.m:19` | `18.27` | MATLAB comment names only the formula ("Sutherland's formula to calculate the dynamic viscosity"), not a source for these three constants; unverified | read |
| C-17 | `single_area` habit `l`/`o` (Linear/Oriented), diameter >= 0.03 cm branch: prefactor `a=0.0512` | `P/particle_physics.py:46` | `M/single_area.m:20` | `0.0512` | source not stated in the MATLAB (no A-D relation reference anywhere in the file); unverified | read |
| C-18 | `single_area` habit `h` (Plate): prefactor `a=0.65` | `P/particle_physics.py:49` | `M/single_area.m:25` | `0.65` | as C-17 | read |
| C-19 | `single_area` habits `i`,`a`,`s`,`t` (Irregular): prefactor `a=0.2285` | `P/particle_physics.py:52` | `M/single_area.m:29` | `0.2285` | as C-17 | read |
| C-20 | `single_area` habit `g` (Graupel): prefactor `a=0.5` | `P/particle_physics.py:55` | `M/single_area.m:33` | `0.5` | as C-17 | read |
| C-21 | `single_area` habit `d` (Dendrite): prefactor `a=0.21` | `P/particle_physics.py:58` | `M/single_area.m:37` | `0.21` | as C-17 | read |
| C-22 | `single_mass` habits `s`,`t` (Sphere/Tiny): prefactor `a=0.00294` | `P/particle_physics.py:75` | `M/single_mass.m:7` | `0.00294` | source not stated in the MATLAB; unverified | read |
| C-23 | `single_mass` habits `l`,`o` (Linear/Oriented), diameter >= 0.03 cm branch: prefactor `a=0.000907` | `P/particle_physics.py:81` | `M/single_mass.m:17` | `0.000907` | as C-22 | read |
| C-24 | `single_mass` habit `h` (Plate): prefactor `a=0.00739` | `P/particle_physics.py:84` | `M/single_mass.m:22` | `0.00739` | as C-22 | read |
| C-25 | `single_mass` habits `i`,`a` (Irregular): prefactor `a=0.00294` | `P/particle_physics.py:87` | `M/single_mass.m:26` | `0.00294` | as C-22 | read |
| C-26 | `single_mass` habit `g` (Graupel): prefactor `a=0.049` | `P/particle_physics.py:90` | `M/single_mass.m:30` | `0.049` | as C-22 | read |
| C-27 | `single_mass` habit `d` (Dendrite): prefactor `a=0.000516` | `P/particle_physics.py:93` | `M/single_mass.m:34` | `0.000516` | as C-22 | read |
| C-28 | `dropsize` chord-table dimension `MAX_HORIZONTAL_CHORDS = 117` | `P/dropsize.py:125` | `M/dropsize.m:53` | `117` | source not stated in the MATLAB (no reference for the table's dimensions); unverified | read |
| C-29 | `dropsize` chord-table dimension `MAX_VERTICAL_CHORDS = 55` | `P/dropsize.py:126` | `M/dropsize.m:54` | `55` | as C-28 | read |
| C-30 | `dropsize` oversize sentinel `OVERSIZE = 9.1` | `P/dropsize.py:134` | `M/dropsize.m:205` | `9.1` | the comment at `M/dropsize.m:11` names only the sentinel ("oversize as 9.1"), not its provenance; unverified | read |
| C-31 | `dropsize` circle-fit method attribution | `P/dropsize.py:11` | `M/dropsize.m:22` | `Heymsfield & Parrish` `Heimsfield-Parish` | `M/dropsize.m:13-14,22` names "Heimsfield-Parish" (sic), "J. Atmos. and Oceanic Tech. Vol 4, Sept. '87" with no year attached to that name; `P/dropsize.py:10-11` spells it "Heymsfield & Parrish" and adds "(1978)" | MATLAB names the authors (misspelled) without a year for this attribution; the port's added "(1978)" is not sourced to a MATLAB comment and has not been checked against a paper -- unverified |
| C-32 | `holroyd` `PROBE_RESOLUTION = 0.025` mm (hardcoded, not read from the probe) | `P/habit.py:89` | `M/holroyd.m:32` | `0.025` `.025` | source not stated in the MATLAB; unverified | read |
| C-33 | `holroyd` slice-index ceiling `MAX_TWOD_DATA_LENGTH = 6000` | `V/habit_core.py:25` | `M/holroyd.m:108` | `6000` | source not stated in the MATLAB; unverified | read |
| C-34 | Holroyd (1987) reference, page range | `P/habit.py:9` | `M/holroyd.m:14` | `498-511` `498- 511` | `M/holroyd.m:1,13-14` names "Holroyd (1987)", "J. Atmos. and Oceanic Tech. Vol 4, Sept. '87, pages 498- 511"; `P/habit.py:9` records it as "Holroyd, J. Atmos. Oceanic Technol. 4, 498-511 (1987)" | MATLAB comment names the journal, volume, year and pages directly; not independently checked against the published paper |
| C-35 | 2D-S probe `diodesize = 0.010` mm (`STOCK_V314`) | `V/constants.py:520` | `M/sizeDist.m:368` | `0.010` `.010` | not a literature value: probe hardware geometry from the vendored `sizeDist.m` probe switch; unverified against instrument documentation | read |
| C-36 | 2D-S probe `armdst = 63.0` mm (`STOCK_V314`) | `V/constants.py:521` | `M/sizeDist.m:369` | `63.0` `63.` | as C-35 | read |
| C-37 | 2D-S `kk` bin-edge formula's `num_bins+0.6` fudge, evaluated to the literal `128.6` in the port | `V/constants.py:521` | `M/sizeDist.m:376` | `128.6` `0.6` | not a literature value; MATLAB keeps it symbolic (`(num_bins+0.6)`), the port evaluates it for `num_bins=128` | read |
| C-38 | HVPS probe `diodesize = 0.150` mm (`STOCK_V314`) | `V/constants.py:512` | `M/sizeDist.m:343` | `0.150` `.150` | not a literature value: probe hardware geometry; unverified against instrument documentation | read |
| C-39 | HVPS probe `armdst = 161.0` mm (`STOCK_V314`) | `V/constants.py:513` | `M/sizeDist.m:344` | `161.0` `161.` | as C-38 | read |
| C-40 | HVPS hand-written `kk` bin-edge table, first entry `200.0` | `V/constants.py:400` | `M/sizeDist.m:346` | `200.0` | not a literature value; unverified against instrument documentation | read |
| C-41 | `lwc_calc` sphere-volume micron-to-cm conversion `1e-4` (paired with `pi/6`) | `V/lwc.py:38` | `M/lwc_calc.m:6` | `1e-4` | not a literature value: a unit conversion inside a geometric (sphere-volume) identity; no citation applies | read |
| C-42 | `lwc_calc` cm^3-to-m^3 output conversion `1e6` | `V/lwc.py:69` | `M/lwc_calc.m:6` | `1e6` | as C-41 | read |

The `STOCK_V314` and ORACLES-production `ProbeConfig` tables carry the same 2D-S/HVPS geometry
(`V/constants.py:600-615` measures the full diff: only the reject/interarrival fields change),
so C-35..C-40 are cited against the vendored stock `M/sizeDist.m` even though ORACLES ran the
production table.

## Long tail (not yet verified)

Candidates found by grep and not yet tabulated: the rest of `holroyd.m`'s decision-tree numeric
thresholds inside `holroyd()` itself (the r2-correlation, F-fine-detail and S-ratio cutoffs --
`PROBE_RESOLUTION` and `MAX_TWOD_DATA_LENGTH` are covered above, the tree's other literals are
not); the `ProbeConfig` geometry for every probe besides 2D-S and HVPS (PECAN, GPM, SOCRATES,
CIP, PIP, 2DC, 2DP) in `V/constants.py`, which both engines share; the v3.5 engine's other counterparts in
`src/arrayprobe_uiops/`. **Paper verification (plan step 2) was not attempted**: no PDF
for any of `korolev_2007`, `heymsfield_parrish_1978`, `heymsfield_parrish_1979`,
`baker_lawson_2006`, `heymsfield_westbrook_2010`, or `mitchell_1996` was found under a `literature/` folder (not included in this release)
(only a `README.md`) or elsewhere in the repository, so every "unverified" row above
stays unverified rather than being checked against memory.

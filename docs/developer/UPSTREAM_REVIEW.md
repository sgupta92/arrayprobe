# The review of the upstream code

Porting UIOOPS and SODA-2 line by line meant reading every line, and running the original
code under Octave and GDL on the same inputs as the port. That work produced a review of the
upstream sources: places where the code's behaviour differs from its comments or documentation,
values that look like typing slips, and paths no configuration reaches.

The review is written for the upstream developers and is kept outside this package. It is theirs to read first.

What it means for a user of this package:

- **The v3.5 engine** applies the upstream developers' own fixes where they made them. Where an
  identified defect destroys or corrupts data, the correction is on by default, can be switched
  off, and is recorded in every run's `.call` stamp.
- **Other corrections** are opt-in enhancements, each measured by running with and without it on
  the same data; see the documentation site's Enhancements page and `enhancements_uiops/`.
- **The v3.1.4 engine**, which reproduces archived products exactly including their defects, is
  not part of this package; see [Two engines](TWO_ENGINES.md).

UIOOPS is developed by the McFarquhar group; please cite it alongside this package. SODA-2 is
cited as:

Aaron Bansemer. (2026). abansemer/soda2: v2.26.0 (Version v2.26.0) [Computer software]. Zenodo. https://doi.org/10.5281/zenodo.18331418

# Contributing to arrayprobe

Thank you for helping. This guide covers reporting a bug, proposing a change, the one rule every
change must respect, and the licence your contribution is made under.

## Reporting a bug

Open an issue and include:

- **The engine** you ran (`3.5`, the `engine` in your run file's `[run]` table, or `soda2` for
  `arrayprobe soda2 run`) and the package version.
- **The `.call` stamp** written beside the output. It records the exact configuration of the run,
  including any opt-in enhancements, and is usually the fastest way to reproduce a report.
- **The probe type** (2D-S, HVPS, CIP, 2DC, ...) and, where relevant, the channel.
- **The full command** and the error message or the output you did not expect.
- **A minimal raw sample**, if you can share it: the smallest slice of the raw file that shows the
  problem. If the data cannot be shared, say so; a synthetic reproduction is welcome too.

## Proposing a change

1. Fork the repository and create a branch for your change.
2. From a checkout of the repository, install in editable mode with the pinned test dependencies
   and the two corrections packages the suite needs:

   ```bash
   pip install -e ".[pinned]" -e enhancements_uiops -e enhancements_soda2
   ```

3. Add or update tests. The suite uses the standard library's `unittest`; please keep new tests in
   that style rather than converting them to another framework.
4. Run the suite and the linter before opening a pull request:

   ```bash
   python -m unittest discover -s tests -p "test_*.py"
   python -m ruff check src tests scripts enhancements_uiops enhancements_soda2
   ```

5. Open a pull request describing what changed and why, and how you tested it.

## The fidelity rule

The UIOOPS and SODA-2 engines are faithful reproductions of the original processing software.
Their job is to produce the same output the originals do, including known quirks, so that results
can be compared with the original software's output.

- **A change to a faithful engine must not change its output.** Speed-ups and refactors are welcome
  when they are byte-identical, and the pull request should include a test that shows it.
- **A change in behaviour is opt-in and off by default.** The one exception is a correction for a
  data-destroying defect: on engine 3.5 a batch run corrects these by default, stamped
  (`--protective off` opts out; stray-pixel removal has its own `--stray-pixel off`), and probes
  with no archived product get further corrections; the full list is in
  [Choosing an engine](docs/27-choosing-an-engine.md#corrections-engine-35-applies-by-default). New science, corrections and
  alternative methods are added as a selectable option, recorded in the run's `.call` stamp, with
  tests for both states: off (output unchanged) and on (the new behaviour).
- If you believe the original software has a defect, please report it in an issue with the
  evidence rather than changing the faithful path.

## Licence

arrayprobe is released under the 3-clause BSD licence (`LICENSE`). By contributing, you agree
that your contribution is licensed under the same terms; the Process2D-derived module also
keeps Apache-2.0 terms, as its `SPDX-License-Identifier` line says.

Some code is derived from UIOOPS and SODA-2; the notices their licences require are kept in
`NOTICE.md`. Please keep those notices intact, and add a notice if your contribution derives from
other licensed code.

When describing or using the SODA-2 engine, please cite:
Aaron Bansemer. (2026). abansemer/soda2: v2.26.0 (Version v2.26.0) [Computer software]. Zenodo. https://doi.org/10.5281/zenodo.18331418

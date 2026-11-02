## What this changes and why

## Which part does this touch?

- [ ] The UIOOPS engine (`src/arrayprobe_uiops/`): changes no computed number, or the change is
      byte-identical speed work behind an opt-in flag
- [ ] The SODA-2 engine (`src/arrayprobe_soda2/`): the same rule, against SODA-2
- [ ] The shared package (`src/arrayprobe/`): the command line, file I/O and processing code the
      engines share; the same rule
- [ ] Enhancements (`enhancements_uiops/`, `enhancements_soda2/`): opt-in and off by default, with
      tests for both states (see `CONTRIBUTING.md`, "The fidelity rule")
- [ ] Documentation / tooling / tests only

## Testing

- [ ] `python -m unittest discover -s tests -p "test_*.py"` passes
- [ ] `python -m ruff check src tests scripts enhancements_uiops enhancements_soda2` is clean
- [ ] A new test covers this change; tests stay `unittest`, not pytest

## AI assistance

- [ ] This contribution was produced or assisted by an AI tool (say which, briefly, if so)

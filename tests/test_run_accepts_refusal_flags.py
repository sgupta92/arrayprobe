# SPDX-License-Identifier: BSD-3-Clause
"""Every flag tools/run_flight.py's refusals tell the user to pass is reachable from
``arrayprobe run``.

WHAT THIS PROTECTS. ``run_flight.preset_mismatch_reason`` refused a renamed raw file and said
"pass --accept-preset-mismatch", a flag only run_flight's own argparse knew: a user of
``arrayprobe run`` who followed the message got argparse's exit 2. ``cli._run`` calls
``run_flight.main``, so every run_flight refusal reaches that user. A flag named in advice
("pass --X", "or --X", "give --X", "Drop --X") must be on ``arrayprobe run``'s parser, or map to a
config key that ``config.py`` knows and run_flight reads from ``--config``. The parser is built
and its option strings listed, and the config sides are read from ``config.py``'s own key sets,
never typed here as truth.
"""
import ast
import re
import unittest
from pathlib import Path

from arrayprobe import cli, config

RUN_FLIGHT = Path(cli.__file__).resolve().parent / "driver" / "run_flight.py"
CONFIG_SRC = Path(config.__file__).read_text(encoding="utf-8")
OVERRIDE = re.compile(r"(?<![\w-])--(?:accept|allow)-[a-z][a-z0-9-]*[a-z0-9]")
ADVICE = re.compile(r"(?:\bpass(?:es|ing)?|\bor|\bgive|\bDrop)\s+(--[a-z][a-z0-9-]*[a-z0-9])"
                    # "--tas-grid probe or --protective off": the first of an or-pair.
                    r"|(?<![\w-])(--[a-z][a-z0-9-]*[a-z0-9])(?=\s+\w+\s+or\s+--)")

#: Flags reachable from `arrayprobe run` through the config file it passes as --config:
#: flag -> (section, key). Each key is asserted against config.py's own key set below.
CONFIG_ROUTES = {
    "--presets": ("run", "presets"),
    "--probe-case": ("run", "probe_case"),
    "--engine": ("run", "engine"),
    "--tas-file": ("run", "tas_file"),
    "--regime": ("thresholds", "regime"),
    "--area-ratio-z": ("thresholds", "area_ratio_z"),
    "--tas-source": ("tas", "source"),
    "--protective": ("enhancements", "protective"),
    "--stray-pixel": ("enhancements", "stray_pixel_fix"),
    "--ncar-2dc-timing": ("enhancements", "ncar_2dc_timing_fix"),
    "--tas-max": ("thresholds", "tas_max"),
    "--pecan-params": ("thresholds", "pecan_params"),
    "--tas-from-probe": ("run", "tas_from_probe"),
    "--borrowed-combine": ("combine", "borrowed"),
    "--time-offset-s": ("time_offset", None),
}
_KEYSETS = {"run": config._RUN_KEYS, "thresholds": config._THRESHOLD_KEYS,
            "tas": config._TAS_KEYS}

#: Batch-driver-only; message to be fixed. Named by run_flight.py's advice but reachable from
#: `arrayprobe run` by no flag and no config key (verified 2026-10-18). Each is to leave this
#: set when `arrayprobe run` gains it (cli._RUN_OVERRIDES or a value-taking equivalent) or the
#: message is reworded; the set may shrink, never grow (the last test fails on a stale entry).
KNOWN_UNREACHABLE: set = set()


def _run_options() -> set:
    parser = cli.build_parser()
    sub = next(a for a in parser._actions if a.__class__.__name__ == "_SubParsersAction")
    return {s for a in sub.choices["run"]._actions for s in a.option_strings}


def _strings():
    tree = ast.parse(RUN_FLIGHT.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node
        elif isinstance(node, ast.JoinedStr):
            text = "".join(v.value for v in node.values
                           if isinstance(v, ast.Constant) and isinstance(v.value, str))
            yield ast.Constant(value=text, lineno=node.lineno)


def _named(pattern) -> dict:
    found = {}
    for node in _strings():
        for m in pattern.finditer(node.value):
            flag = next(g for g in m.groups() or (m.group(0),) if g)
            found.setdefault(flag, node.lineno)
    return found


class RunAcceptsEveryRefusalOverride(unittest.TestCase):
    def test_the_sweep_finds_the_known_overrides(self):
        # A regex that matched nothing would pass the check below vacuously.
        self.assertIn("--accept-preset-mismatch", _named(OVERRIDE))
        self.assertIn("--accept-preset-mismatch", _named(ADVICE))

    def test_every_override_run_flight_names_is_an_arrayprobe_run_option(self):
        opts = _run_options()
        missing = {f: line for f, line in _named(OVERRIDE).items() if f not in opts}
        self.assertEqual(missing, {}, "run_flight.py names these overrides (flag: line) that "
                                      "`arrayprobe run` rejects with exit 2; add them to "
                                      "cli._RUN_OVERRIDES")

    def test_each_override_is_forwarded_and_off_by_default(self):
        parser = cli.build_parser()
        ns = parser.parse_args(["run", "x.toml"])
        for flag in cli._RUN_OVERRIDES:
            self.assertFalse(getattr(ns, flag.replace("-", "_")), flag)
        ns = parser.parse_args(["run", "x.toml", "--accept-preset-mismatch"])
        self.assertTrue(ns.accept_preset_mismatch)


class RunReachesEveryAdvisedFlag(unittest.TestCase):
    def test_every_advised_flag_is_reachable_or_listed(self):
        opts = _run_options()
        missing = {f: line for f, line in _named(ADVICE).items()
                   if f not in opts and f not in CONFIG_ROUTES and f not in KNOWN_UNREACHABLE}
        self.assertEqual(missing, {}, "run_flight.py advises these flags (flag: line) that "
                                      "`arrayprobe run` cannot reach by flag or config key; "
                                      "add them to `arrayprobe run`, or reword the message")

    def test_config_routes_name_keys_config_py_knows(self):
        source = RUN_FLIGHT.read_text(encoding="utf-8")
        for flag, (section, key) in CONFIG_ROUTES.items():
            if section == "enhancements":
                # [enhancements] is open-keyed; run_flight pops the key from it.
                self.assertIn(f'cfg.enhancements.pop("{key}")', source, flag)
            elif section == "combine":
                self.assertIn(f'comb.pop("{key}"', CONFIG_SRC, flag)
            elif section == "time_offset":
                self.assertIn(section, config._SECTIONS, flag)
            else:
                self.assertIn(key, _KEYSETS[section], f"{flag} -> [{section}].{key}")

    def test_known_unreachable_entries_are_still_named_and_still_unreachable(self):
        advised, opts = _named(ADVICE), _run_options()
        for flag in KNOWN_UNREACHABLE:
            self.assertIn(flag, advised, f"{flag} is no longer advised; drop it from the set")
            self.assertNotIn(flag, opts, f"{flag} is now on `arrayprobe run`; drop it")
            self.assertNotIn(flag, CONFIG_ROUTES, flag)


if __name__ == "__main__":
    unittest.main()

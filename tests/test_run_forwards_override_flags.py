# SPDX-License-Identifier: BSD-3-Clause
"""Every override ``arrayprobe run`` accepts reaches ``tools/run_flight.py``'s argv.

``tests/test_run_accepts_refusal_flags.py`` proves the flags run_flight's refusals advise are on
``arrayprobe run``'s parser; this proves the parser's value is forwarded. It iterates
``cli._RUN_OVERRIDES`` (store_true) and ``cli._RUN_VALUE_OVERRIDES`` (value-taking) themselves,
so a new entry is covered without editing this file. The driver's ``main`` is replaced by a
recorder, so nothing runs and the argv the wrapper built is what is read.

A store_true flag must appear only when given; a value flag must appear with its value when
given and be absent otherwise, so run_flight's own default applies.
"""
from __future__ import annotations

import io
import tempfile
import types
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from arrayprobe import cli


def _argv_for(*flags: str) -> list[str]:
    root = Path(tempfile.mkdtemp())
    toml = root / "run.toml"
    toml.write_text(
        '[fidelity]\nprofile = "stock-v3.5"\n[run]\nengine = "3.5"\npreset = "DEMO_2DS_H"\n',
        encoding="utf-8")
    seen: list[list[str]] = []

    def record(argv):
        seen.append(list(argv))
        return 0

    fake = types.SimpleNamespace(PRESETS={}, main=record)
    with mock.patch.object(cli, "_load_run_flight", return_value=fake), \
            redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        rc = cli.main(["run", str(toml), str(root / "raw.2DS"), *flags])
    assert rc == 0 and seen, "the wrapper never reached the driver"
    return seen[0]


def _sample_value(choices) -> str:
    # A non-first choice where there is one, so a forward that hard-coded the first is caught.
    return choices[-1] if choices else str(Path(tempfile.gettempdir()) / "iat_threshold.cdf")


class TheTablesAreNotEmpty(unittest.TestCase):

    def test_both_tables_have_entries(self):
        # An empty table would make every loop below pass vacuously.
        self.assertTrue(cli._RUN_OVERRIDES)
        self.assertTrue(cli._RUN_VALUE_OVERRIDES)


class StoreTrueOverridesAreForwardedOnlyWhenGiven(unittest.TestCase):

    def test_absent_when_not_given(self):
        argv = _argv_for()
        for flag in cli._RUN_OVERRIDES:
            with self.subTest(flag=flag):
                self.assertNotIn(f"--{flag}", argv)

    def test_present_when_given(self):
        for flag in cli._RUN_OVERRIDES:
            with self.subTest(flag=flag):
                argv = _argv_for(f"--{flag}")
                self.assertEqual(argv.count(f"--{flag}"), 1)
                others = [f"--{f}" for f in cli._RUN_OVERRIDES if f != flag]
                self.assertFalse(set(others) & set(argv), "only the given flag is forwarded")


class ValueOverridesAreForwardedWithTheirValue(unittest.TestCase):

    def test_absent_when_not_given_so_run_flights_default_applies(self):
        argv = _argv_for()
        for flag in cli._RUN_VALUE_OVERRIDES:
            with self.subTest(flag=flag):
                self.assertNotIn(f"--{flag}", argv)

    def test_present_with_its_value_when_given(self):
        for flag, (choices, _why) in cli._RUN_VALUE_OVERRIDES.items():
            value = _sample_value(choices)
            with self.subTest(flag=flag, value=value):
                argv = _argv_for(f"--{flag}", value)
                self.assertEqual(argv.count(f"--{flag}"), 1)
                self.assertEqual(argv[argv.index(f"--{flag}") + 1], value)

    def test_every_choice_is_forwarded_verbatim(self):
        for flag, (choices, _why) in cli._RUN_VALUE_OVERRIDES.items():
            for value in choices or ():
                with self.subTest(flag=flag, value=value):
                    argv = _argv_for(f"--{flag}", value)
                    self.assertIn(f"--{flag}", argv)
                    self.assertEqual(argv[argv.index(f"--{flag}") + 1], value)


if __name__ == "__main__":
    unittest.main()

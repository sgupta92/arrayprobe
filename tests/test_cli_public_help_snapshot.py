# SPDX-License-Identifier: BSD-3-Clause
"""``arrayprobe --help`` in the public distribution is pinned: its commands, options and opening.

The release review of 2026-10-31 (fix-plan class 20d) found the top-level help listing 23
subcommands, maintainer tools among them, under a paragraph of internal vocabulary. The fix
left five maintainer commands out of the listing (``cli._UNLISTED_SUBCOMMANDS``; they still
run) and rewrote the opening around ``make-demo-flight`` and ``run``. This is the control that
keeps it so (fix-plan control 4): a command, an option or a word of the opening that changes
fails here, and the change is made on purpose by updating the snapshot below.

Compared as structure, not as raw text, so argparse's line wrapping (terminal width, Python
version) cannot fail it. Runs only where the v3.1.4 engine is absent, as in the public
distribution, because that engine adds its three stage commands and a different sentence.
"""
from __future__ import annotations

import contextlib
import io
import re
import unittest

from arrayprobe import cli

COMMANDS = ["run", "reprocess", "combine", "compare", "gallery", "inventory", "triage",
            "provenance", "diode-masks", "validate", "view", "intarr-threshold",
            "make-demo-flight", "make-tas-file", "tas-from-nasa-ames", "engines", "tune", "soda2"]
OPTIONS = ["-h", "--version", "--quiet", "--verbose"]
OPENING = ("Start with `arrayprobe make-demo-flight`, which writes a small synthetic raw file, "
           "then process a flight with `arrayprobe run <config.toml>`: it runs every stage on "
           "the engine the file names ([run].engine, required; use \"3.5\", UIOOPS v3.5, for "
           "new data; examples/configs/ has configs). To run one stage at a time, use "
           "`arrayprobe run` with [run].stages. `arrayprobe engines` says which engine does what.")


def public_help() -> str:
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.suppress(SystemExit):
        cli.main(["--help"])
    return out.getvalue()


def parse(text: str) -> tuple[list[str], list[str], str]:
    """The listed commands, the usage line's options and the opening paragraph of ``text``."""
    usage, _, rest = text.partition("\n\n")
    m = re.search(r"\{([a-z0-9,-]+)\}", usage)
    commands = m.group(1).split(",") if m else []
    options = re.findall(r"\[(-[-a-z]+)", usage.split("{")[0])
    options += re.findall(r"\|\s*(--[a-z-]+)", usage.split("{")[0])
    opening = " ".join(rest.split("positional arguments:")[0].split())
    return commands, options, opening


@unittest.skipIf(cli._v314_engine_present(), "the v3.1.4 engine changes the help (dev tree)")  # noqa: SLF001
class TestPublicHelpSnapshot(unittest.TestCase):
    def test_the_listing_is_the_reviewed_public_set(self):
        commands, options, opening = parse(public_help())
        self.assertEqual(commands, COMMANDS)
        self.assertEqual(sorted(options), sorted(OPTIONS))
        self.assertEqual(opening, OPENING)

    def test_every_unlisted_command_still_runs(self):
        for name in cli._UNLISTED_SUBCOMMANDS:  # noqa: SLF001
            with self.subTest(command=name):
                out = io.StringIO()
                with contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as cm:
                    cli.main([name, "--help"])
                self.assertEqual(cm.exception.code, 0)
                self.assertIn(f"usage: arrayprobe {name}", out.getvalue())

    def test_the_check_fires_on_an_added_command(self):
        text = public_help().replace("{run,", "{run,secret-tool,", 1)
        self.assertNotEqual(parse(text)[0], COMMANDS)


if __name__ == "__main__":
    unittest.main()

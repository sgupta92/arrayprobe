# SPDX-License-Identifier: BSD-3-Clause
"""The triage server refuses a product whose provenance is unrecorded -- and says so on the page.

WHY THIS EXISTS (2026-09-18). ``_discover_flights`` globbed ``proc.*.nc`` and indexed
whatever matched, never opening a ``.call`` sidecar -- by design, and stated as such in the
module. A hardlink of a CIP proc file, made for convenience under a second name, therefore
entered a review queue carrying no sidecar at all (a stamp is keyed by *name*, so a hardlink
leaves it behind), and the product it aliased had been described as written by v3.5 when
v3.1.4 wrote it. Nobody could have told from the server.

**Every assertion here is a firing test, not a happy path.** Five guards in this repository
were found reading correctly while matching nothing, and a test that only checked that a
stamped flight appears would have passed on all five. So each case below builds a real
unstamped file on disk and asserts the refusal *fires*: the flight is absent from the index,
its name is present in the rendered HTML under the refusal heading, and the same directory
with ``accept_unstamped=True`` produces the opposite result. The last of those is what proves
the refusal is doing the work rather than the fixture being empty.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from arrayprobe import provenance
from arrayprobe.triage_server import (
    TriageServer,
    _discover_flights,
    _refused_flights,
)


def _proc(d: Path, name: str, *, stamp: str | None = None) -> Path:
    """A zero-byte ``proc`` file, optionally with a sidecar.

    Zero-byte on purpose: discovery must reach its verdict from the sidecar alone, so a test
    that needed real netCDF content would be testing something else. The companion ``.cdf``
    is created too, because a flight with no image renders as "no matching raw/image file" and
    would leave the refusal untested behind a different branch.
    """
    p = d / f"proc.{name}.nc"
    p.write_bytes(b"")
    (d / f"{name}.cdf").write_bytes(b"")
    if stamp is not None:
        provenance.call_path(p).write_text(stamp + "\n", encoding="utf-8")
    return p


_STAMPED = "engine=3.1.4 profile=oracles-production stage=S3 writer=arrayprobe-cli"


class TheRefusalFires(unittest.TestCase):
    """The unstamped product is excluded, and the stamped one beside it is not."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.d = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        _proc(self.d, "160906064017.H", stamp=_STAMPED)
        _proc(self.d, "160906999999.H")  # no sidecar: the hardlink case

    def test_only_the_stamped_flight_is_indexed(self):
        flights = _discover_flights(self.d)
        self.assertEqual(sorted(flights), ["160906064017"])

    def test_the_refused_one_is_named_with_its_state(self):
        refused = _refused_flights(self.d)
        self.assertEqual(refused, [("proc.160906999999.H.nc", "unstamped")])

    def test_accept_unstamped_indexes_both_and_refuses_nothing(self):
        """The not-vacuous case. Without this, a fixture that simply failed to match the
        discovery regex would pass every assertion above while the guard did nothing."""
        flights = _discover_flights(self.d, accept_unstamped=True)
        self.assertEqual(sorted(flights), ["160906064017", "160906999999"])
        self.assertEqual(_refused_flights(self.d, accept_unstamped=True), [])

    def test_a_legacy_json_stamp_is_refused_too(self):
        """The CIP product's own format: a lane script's hand-rolled JSON, which records a
        stage and a profile and **no engine at all**. It is not indexed, because "something
        wrote a sidecar" is not the same as "the engine is recorded"."""
        p = _proc(self.d, "160906000001.H")
        provenance.call_path(p).write_text(
            '{"stage": "S3", "profile": "oracles-production", "reject": "production"}\n',
            encoding="utf-8")
        self.assertNotIn("160906000001", _discover_flights(self.d))
        self.assertIn(("proc.160906000001.H.nc", "legacy-json"), _refused_flights(self.d))


class TheRefusalIsVisible(unittest.TestCase):
    """A refusal nobody can see is a disappearance, which is the failure being fixed."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.d = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        _proc(self.d, "160906064017.H", stamp=_STAMPED)
        _proc(self.d, "160906999999.H")

    def _index_html(self, accept_unstamped: bool) -> str:
        """``_render_index`` without a socket: it reads only class attributes and the
        directory, so binding a real server here would test http.server, not this."""
        server = TriageServer.__new__(TriageServer)
        server.decoded_dir = self.d
        server.accept_unstamped = accept_unstamped
        server.queues = {}
        return server._render_index().decode("utf-8")

    def test_the_refused_file_is_named_in_the_rendered_page(self):
        html = self._index_html(accept_unstamped=False)
        self.assertIn("Refused: no provenance", html)
        self.assertIn("proc.160906999999.H.nc", html)
        self.assertIn("--accept-unstamped", html)

    def test_the_escape_hatch_is_named_on_the_page_that_refuses(self):
        """The user has to be able to get from the refusal to the way through it without
        reading the source. ``arrayprobe provenance`` and the flag are both on the page."""
        html = self._index_html(accept_unstamped=False)
        self.assertIn("arrayprobe provenance", html)

    def test_with_the_flag_there_is_no_refusal_panel(self):
        html = self._index_html(accept_unstamped=True)
        self.assertNotIn("Refused: no provenance", html)
        self.assertIn("160906999999", html)

    def test_the_index_shows_the_engine_it_read(self):
        html = self._index_html(accept_unstamped=False)
        self.assertIn("<th>Engine</th>", html)
        self.assertIn("3.1.4", html)

    def test_an_accepted_unstamped_flight_reports_its_engine_as_unrecorded(self):
        """Not blank, and never "3.1.4". The whole defect was absence reading as a version."""
        html = self._index_html(accept_unstamped=True)
        self.assertIn("unrecorded", html)


class TheFlagReachesTheServer(unittest.TestCase):
    """Threading a flag through three layers is exactly where a guard quietly stops firing."""

    def test_the_cli_parser_carries_accept_unstamped(self):
        from arrayprobe.cli import build_parser
        args = build_parser().parse_args(["triage", "--decoded-dir", "."])
        self.assertFalse(args.accept_unstamped)
        args = build_parser().parse_args(["triage", "--decoded-dir", ".", "--accept-unstamped"])
        self.assertTrue(args.accept_unstamped)

    def test_the_module_form_carries_it_too(self):
        """``python -m arrayprobe.triage_server`` is a supported entry point; a flag on only
        one of the two is a hole, and the module form is the one the design record cites."""
        import arrayprobe.triage_server as ts
        captured = {}

        def fake_run(decoded_dir, port=8765, queue_file=None, reviewer=None,
                     accept_unstamped=False, met_dir=None, state_file=None,
                     state_var=None, run_root=None):
            captured["accept_unstamped"] = accept_unstamped

        real, ts.run = ts.run, fake_run
        try:
            ts.main(["--decoded-dir", ".", "--accept-unstamped"])
            self.assertTrue(captured["accept_unstamped"])
            ts.main(["--decoded-dir", "."])
            self.assertFalse(captured["accept_unstamped"])
        finally:
            ts.run = real

    def test_the_server_defaults_to_refusing(self):
        """The class attribute is the default every handler reads. If this ever flips to True,
        every test above would still pass while the refusal was off for real users."""
        self.assertFalse(TriageServer.accept_unstamped)


if __name__ == "__main__":
    unittest.main()

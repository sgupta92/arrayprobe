# SPDX-License-Identifier: BSD-3-Clause
"""Run page HTTP surface (slice 3): form, same-origin guard, dry run, launch, run pages.

The launcher and the dry run are stubbed; no test starts a processing run.
"""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from arrayprobe import run_page

PORT = 8765
LOCAL = {"Host": f"127.0.0.1:{PORT}", "Origin": f"http://127.0.0.1:{PORT}"}


class TestRunPageRoutes(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.raw = self.root / "base.2DS"
        self.raw.write_bytes(b"\0")
        self.out = self.root / "out"
        self.out.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def _form(self, **kw):
        form = {"engine": "3.5", "preset": run_page.preset_choices()[0], "raw": str(self.raw),
                "out": str(self.out), "name": "demo",
                "profile": run_page.profile_choices()[0]}
        form.update(kw)
        return form

    def test_get_run_form_lists_engines_presets_probes(self):
        page = run_page.render_form()
        for value in run_page.ENGINES + run_page.preset_choices()[:1]:
            self.assertIn(f'value="{value}"', page)

    def test_post_run_with_bad_preset_returns_errors_json(self):
        status, reply = run_page.handle_post(self._form(preset="no-such"), LOCAL, PORT)
        self.assertEqual(status, 400)
        self.assertFalse(reply["ok"])
        self.assertTrue(reply["errors"])

    def test_post_run_dry_run_shows_driver_text(self):
        with mock.patch.object(run_page, "dry_run", return_value=(0, "preflight OK")) as dr, \
             mock.patch.object(run_page, "launch_detached",
                               side_effect=AssertionError("no launch on a dry run")):
            status, reply = run_page.handle_post(self._form(dry_run=True), LOCAL, PORT)
        self.assertEqual(status, 200, reply)
        self.assertEqual(reply["dry_run_text"], "preflight OK")
        self.assertIn("--dry-run", dr.call_args.args[0])

    def test_post_run_launch_writes_toml_and_redirects(self):
        with mock.patch.object(run_page, "launch_detached", return_value=4242):
            status, reply = run_page.handle_post(self._form(), LOCAL, PORT)
        self.assertEqual(status, 200, reply)
        run_id = reply["run_id"]
        self.assertIn(run_id, run_page.list_runs(self.out))
        record = run_page.read_record(self.out, run_id)
        self.assertEqual(record["pid"], 4242)
        self.assertTrue(Path(record["toml"]).is_file())

    def test_get_runs_unknown_id_is_404_without_touching_disk(self):
        with mock.patch.object(run_page, "read_record",
                               side_effect=AssertionError("read before whitelist")):
            status, page = run_page.get_run_page(self.out, "..%2F..%2Fetc")
        self.assertEqual(status, 404)
        self.assertIn("unknown run", page)

    def test_log_tail_is_html_escaped(self):
        page = run_page.render_run({"run_id": "r"}, {"log_tail": ["<script>x</script>"],
                                                     "call_files": [], "state": "running"})
        self.assertNotIn("<script>x", page)
        self.assertIn("&lt;script&gt;x", page)

    def test_post_run_rejects_foreign_origin(self):
        foreign = {"Host": f"127.0.0.1:{PORT}", "Origin": "http://evil.example"}
        with mock.patch.object(run_page, "launch_detached",
                               side_effect=AssertionError("launched cross-origin")):
            status, reply = run_page.handle_post(self._form(), foreign, PORT)
        self.assertEqual(status, 403)
        self.assertFalse(reply["ok"])

    def test_triage_server_routes_reach_run_page(self):
        src = (Path(run_page.__file__).parent / "triage_server.py").read_text(encoding="utf-8")
        self.assertIn('parsed.path == "/run"', src)
        self.assertIn("run_page.get_run_page(run_root, parts[1])", src)



class TestRunRoot(unittest.TestCase):
    """``--run-root`` reaches the server from both entry points, the banner names ``/run``, and
    a server started without it lists the first launched run's output folder."""

    def setUp(self):
        from arrayprobe import triage_server
        self.ts = triage_server
        saved = triage_server.TriageServer.run_root
        self.addCleanup(setattr, triage_server.TriageServer, "run_root", saved)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_module_main_forwards_run_root_resolved_and_defaults_to_none(self):
        with mock.patch.object(self.ts, "run") as run:
            # --decoded-dir is required since 2026-10-10 (triage requires its folder)
            self.ts.main(["--decoded-dir", str(self.root), "--run-root", str(self.root)])
            self.ts.main(["--decoded-dir", str(self.root)])
        self.assertEqual(run.call_args_list[0].kwargs["run_root"], self.root.resolve())
        self.assertIsNone(run.call_args_list[1].kwargs["run_root"])

    def test_cli_triage_forwards_run_root(self):
        from arrayprobe import cli
        with mock.patch.object(cli.triage_module, "run") as run:
            cli.main(["triage", "--decoded-dir", str(self.root), "--run-root", str(self.root)])
            cli.main(["triage", "--decoded-dir", str(self.root)])
        self.assertEqual(run.call_args_list[0].kwargs["run_root"], self.root.resolve())
        self.assertIsNone(run.call_args_list[1].kwargs["run_root"])

    def _banner(self, **kw) -> str:
        import contextlib
        import io
        server = mock.MagicMock()
        server.serve_forever.side_effect = KeyboardInterrupt
        buf = io.StringIO()
        with mock.patch.object(self.ts, "ThreadingHTTPServer", return_value=server), \
                contextlib.redirect_stdout(buf):
            self.ts.run(self.root, PORT, **kw)
        return buf.getvalue()

    def test_banner_names_the_run_page_and_sets_the_root(self):
        text = self._banner(run_root=self.root)
        self.assertIn(f"http://127.0.0.1:{PORT}/run", text)
        self.assertIn(str(self.root), text)
        self.assertEqual(self.ts.TriageServer.run_root, self.root)
        self.assertIn("--run-root", self._banner())
        self.assertIsNone(self.ts.TriageServer.run_root)

    def _post(self, form):
        import io
        import json
        body = json.dumps(form).encode()
        sent = []
        stub = mock.Mock()
        stub.path = "/run"
        stub.headers = {**LOCAL, "Content-Length": str(len(body))}
        stub.rfile = io.BytesIO(body)
        stub.server.server_address = ("127.0.0.1", PORT)
        stub._send.side_effect = lambda b, *a, **k: sent.append((b, a, k))
        self.ts.TriageServer.do_POST(stub)
        return json.loads(sent[0][0])

    def test_first_launch_without_run_root_lists_its_output_folder(self):
        out = self.root / "out"
        out.mkdir()
        raw = self.root / "base.2DS"
        raw.write_bytes(b"\0")
        form = {"engine": "3.5", "preset": run_page.preset_choices()[0], "raw": str(raw),
                "out": str(out), "name": "demo", "profile": run_page.profile_choices()[0]}
        self.ts.TriageServer.run_root = None
        with mock.patch.object(run_page, "launch_detached", return_value=4242):
            reply = self._post(form)
        self.assertTrue(reply["ok"], reply)
        self.assertEqual(self.ts.TriageServer.run_root, out.resolve())
        self.assertIn(reply["run_id"], run_page.render_runs(self.ts.TriageServer.run_root))


if __name__ == "__main__":
    unittest.main()

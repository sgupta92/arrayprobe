# SPDX-License-Identifier: BSD-3-Clause
"""``arrayprobe soda2 run --jit`` / ``[run].jit`` must REACH the kernel, not merely parse.

**Why this module exists.** ``arrayprobe_soda2.jit_kernels`` landed on 2026-09-18 with
``label_blobs(jit=)``, ``fillholes(jit=)``, ``TailOp.jit`` and fourteen identity tests --
and nothing that could set any of them. No CLI flag, no config key: the accelerated
kernel was unreachable by a user. That is the defect found the same morning as another one, where
a capability existed and nothing connected it to a run, and it is the shape a test can pass
over without noticing: *assert the flag parses* would be green on a completely disconnected
flag. So every test here follows the value to the far end of the chain

    ``--jit`` / ``[run].jit``  ->  ``cli._soda2_run``  ->  ``soda2_process_2d(jit=)``
      ->  ``process_2d._tail_op(op, jit=)``  ->  ``TailOp.jit``
      ->  ``processbuffer_tail``'s ``label_blobs(..., jit=)`` and ``fillholes(..., jit=)``

and each half carries its own **mutation**: the link is cut, and the test that asserted the
value arrives is required to fail. A test whose failure mode has never been seen is not a
control (the project's guard doctrine; four guards on this machine
matched nothing while reading fine).

Nothing here needs numba. The question is whether the switch is *connected*, not whether the
kernel is fast or exact -- speed is ``docs/SODA2_SPEED.md``'s business and byte-identity is
``tests/test_soda2_label_region_jit_identity.py``'s, which asserts it with ``np.array_equal``
on the kernel itself. Accordingly the kernel call sites are stubbed here and only the
``jit`` argument they were handed is read.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from arrayprobe import cli
from arrayprobe.config import ConfigError, load_config
from arrayprobe_soda2 import process_2d, processbuffer_tail
from arrayprobe_soda2.processbuffer_spec import SpecBufferParticles
from arrayprobe_soda2.processbuffer_tail import TailOp, process_buffer_tail

DATA = Path(__file__).resolve().parent / "data"
FRAME_FIXTURE = DATA / "soda2_spec_frame_fixture"

#: `test_cli_soda2._OP_TOML`'s op, trimmed to what this module needs. `[run].jit` is
#: substituted in, or left out entirely, per case.
_OP_TOML = """
[run]
engine = "soda2"
{jit_line}
[soda2]
fn = {fn!r}
date = "20160906"
starttime = 24240.0
stoptime = 24250.0
format = "SPEC"
subformat = 0
probetype = "2DS"
res = 10.0
endbins = [0.0, 50.0, 100.0, 200.0, 500.0]
arendbins = [0.0, 0.5, 1.0]
rate = 1.0
smethod = "xy"
pth = ""
particlefile = 1
inttime_reject = 0
stuckbits = 0
water = 0
fixedtas = 0.0
timeoffset = 0.0
armwidth = 6.3
numdiodes = 128
greythresh = 0
probeid = "H"
eawmethod = "centerin"
wavelength = 0.785e-6
dofconst = 8.12
ncdfparticlefile = 0
asciipsdfile = 0
shortname = "x1frame"
outdir = {outdir!r}
"""


def _write_config(tmp: str, *, jit_line: str = "") -> Path:
    text = _OP_TOML.format(fn=str(FRAME_FIXTURE).replace("\\", "/"),
                           outdir=(tmp + os.sep).replace("\\", "/"),
                           jit_line=jit_line)
    p = Path(tmp) / "soda2.toml"
    p.write_text(text, encoding="utf-8")
    return p


def _run_cli(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = cli.main(argv)
    return rc, out.getvalue(), err.getvalue()


@contextlib.contextmanager
def _watch_tail_ops():
    """Record every :class:`TailOp` the driver builds, leaving the value it builds alone.

    ``process_2d._tail_op`` is the join: it is the ONLY place a ``TailOp`` is constructed on
    the run path, and ``processbuffer_tail`` reads ``op.jit`` off that object (and, under
    ``jobs > 1``, off the copy that rides in ``_LoopContext`` into each worker). It is
    deliberately not an ``enhancement_hooks`` point, so this spy cannot collide with the
    optional correction package's substitutions, which are default-ON when it is installed.
    """
    seen: list[TailOp] = []
    real = process_2d._tail_op

    def spy(op, **kw):
        built = real(op, **kw)
        seen.append(built)
        return built

    with mock.patch.object(process_2d, "_tail_op", spy):
        yield seen


def _jit_values_from_a_run(argv_tail: list[str], *, jit_line: str = "") -> list[bool]:
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _write_config(tmp, jit_line=jit_line)
        with _watch_tail_ops() as seen:
            rc, _out, err = _run_cli(["soda2", "run", str(cfg), *argv_tail])
        assert rc == 0, f"soda2 run exited {rc}: {err[-800:]}"
        assert seen, "no TailOp was built -- the run never reached the buffer loop"
        return [bool(t.jit) for t in seen]


class TheFlagReachesTheDriversTailOp(unittest.TestCase):
    """CLI -> ``TailOp.jit``. The first half of the chain, end to end through ``cli.main``."""

    def test_a_bare_run_leaves_the_kernel_off(self) -> None:
        self.assertEqual(_jit_values_from_a_run([]), [False])

    def test_the_flag_turns_it_on(self) -> None:
        self.assertEqual(_jit_values_from_a_run(["--jit"]), [True])

    def test_the_config_key_turns_it_on_with_no_flag(self) -> None:
        self.assertEqual(_jit_values_from_a_run([], jit_line="jit = true\n"), [True])

    def test_the_config_key_set_false_leaves_it_off(self) -> None:
        self.assertEqual(_jit_values_from_a_run([], jit_line="jit = false\n"), [False])

    def test_flag_and_key_are_ORed_so_the_flag_can_only_turn_it_on(self) -> None:
        """`cli._soda2_run`: `args.jit or cfg.run["jit"]`. A flag that could silently
        switch OFF what the file asked for would make the file a suggestion."""
        self.assertEqual(_jit_values_from_a_run(["--jit"], jit_line="jit = false\n"), [True])
        self.assertEqual(_jit_values_from_a_run([], jit_line="jit = true\n"), [True])

    def test_the_switch_is_not_written_into_op_so_the_sidecar_is_the_same_either_way(
            self) -> None:
        """`jit` moves no written byte, so the `.pbp.call` record of the run's `op` must not
        distinguish the two runs -- the same treatment `--jobs`/`--chunks` get, and for the
        same reason. If `jit` ever leaked into the op dict this fails."""
        records = []
        for tail in ([], ["--jit"]):
            with tempfile.TemporaryDirectory() as tmp:
                cfg = _write_config(tmp)
                rc, _out, err = _run_cli(["soda2", "run", str(cfg), *tail])
                self.assertEqual(rc, 0, err[-800:])
                (sidecar,) = sorted(Path(tmp).glob("*.pbp.call"))
                rec = json.loads(sidecar.read_text(encoding="utf-8"))
                # `outdir` is this test's own temporary directory, different per case and
                # nothing to do with the switch.
                records.append({k: v for k, v in rec["op"].items() if k != "outdir"})
        self.assertEqual(records[0], records[1])
        self.assertNotIn("jit", records[0])


class AFlagThatIsParsedAndDroppedIsCaught(unittest.TestCase):
    """The mutation for the first half: cut the one link and require the tests above to fail.

    This is that same shape reproduced deliberately -- ``--jit`` still parses, still reaches
    ``soda2_process_2d``, and is then dropped on the floor at the last step. Without this
    test, ``TheFlagReachesTheDriversTailOp`` could be passing for a reason unrelated to the
    flag.
    """

    def test_dropping_jit_in_tail_op_makes_the_flag_stop_arriving(self) -> None:
        real = process_2d._tail_op

        def deaf(op, **_kw):           # the pre-2026-09-18 signature: `jit` ignored
            return real(op)

        with mock.patch.object(process_2d, "_tail_op", deaf):
            with self.assertRaises(AssertionError):
                # `_jit_values_from_a_run` wraps whatever `_tail_op` currently is, so the
                # spy still records -- it records False, and this is what must fail.
                values = _jit_values_from_a_run(["--jit"])
                self.assertEqual(values, [True])

    def test_the_config_key_is_a_switch_and_a_string_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _write_config(tmp, jit_line='jit = "yes"\n')
            with self.assertRaises(ConfigError) as ctx:
                load_config(cfg)
            self.assertIn("[run].jit", str(ctx.exception))

    def test_an_unrelated_run_key_is_still_refused(self) -> None:
        """Adding `jit` to `_SODA2_RUN_KEYS` must not have opened `[run]` generally."""
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _write_config(tmp, jit_line="preset = \"ORACLES_2016_2DS_H\"\n")
            with self.assertRaises(ConfigError) as ctx:
                load_config(cfg)
            self.assertIn("preset", str(ctx.exception))


def _one_particle_buffer(*, numdiodes: int = 128) -> SpecBufferParticles:
    """A two-slice particle with an interior hole, enough for the tail to run.

    Synthetic on purpose: this half of the chain is about which keyword argument arrives at
    ``label_blobs`` and ``fillholes``, and a golden buffer would only make the failure
    message longer.
    """
    n_slices = 6
    bitimage = np.zeros((n_slices, numdiodes), dtype=np.uint8)
    bitimage[1:5, 2:7] = 1
    bitimage[2:4, 3:6] = 0        # the hole `fillholes` exists for
    return SpecBufferParticles(
        rejectbuffer=0, num_images=1, bitimage=bitimage,
        startline=np.array([1], dtype=np.uint32),
        stopline=np.array([4], dtype=np.uint32),
        overload=np.array([0], dtype=np.uint8),
        particle_count=np.array([1], dtype=np.uint16),
        rawtime=np.array([0], dtype=np.uint32),
        clocktas=np.array([100.0], dtype=np.float32),
        stretch=np.array([1.0], dtype=np.float32),
        inttime=np.array([1e-6], dtype=np.float64),
        dof=np.array([1], dtype=np.int16),
        time_sfm=np.array([24240.0], dtype=np.float64),
        reftime=24240.0,
    )


class TheTailOpReachesTheKernelCallSites(unittest.TestCase):
    """``TailOp.jit`` -> the ``jit=`` keyword ``label_blobs`` and ``fillholes`` are called
    with. The second half of the chain, with the kernels stubbed so only the routing is read.

    ``keeplargest`` is nonzero here because the three ``label_blobs`` calls live inside
    ``processbuffer_tail.py``'s ``if op.keeplargest != 0:`` branch -- with the CIP default of
    0 they are never reached, which is exactly why a run can look healthy while that half of
    the switch is dead.
    """

    def _observe(self, *, jit: bool, keeplargest: int) -> dict[str, list[bool]]:
        seen: dict[str, list[bool]] = {"label_blobs": [], "fillholes": []}
        real_lb = processbuffer_tail.label_blobs
        real_fh = processbuffer_tail.fillholes

        def lb(img, **kw):
            seen["label_blobs"].append(bool(kw.get("jit", False)))
            return real_lb(img, **{k: v for k, v in kw.items() if k != "jit"})

        def fh(img, **kw):
            seen["fillholes"].append(bool(kw.get("jit", False)))
            return real_fh(img, **{k: v for k, v in kw.items() if k != "jit"})

        op = TailOp(stuckbits=0, rakefix=0, greythresh=0, dioderange=(0, 127),
                    numdiodes=128, keeplargest=keeplargest, res=10.0, yres=10.0, jit=jit)
        with mock.patch.object(processbuffer_tail, "label_blobs", lb), \
                mock.patch.object(processbuffer_tail, "fillholes", fh):
            process_buffer_tail(_one_particle_buffer(), op,
                                np.zeros(128, dtype=np.int32))
        return seen

    def test_jit_true_arrives_at_both_call_sites(self) -> None:
        seen = self._observe(jit=True, keeplargest=1)
        self.assertTrue(seen["label_blobs"], "label_blobs was never called")
        self.assertTrue(seen["fillholes"], "fillholes was never called")
        self.assertTrue(all(seen["label_blobs"]), seen)
        self.assertTrue(all(seen["fillholes"]), seen)

    def test_jit_false_arrives_as_false_so_the_observation_discriminates(self) -> None:
        seen = self._observe(jit=False, keeplargest=1)
        self.assertTrue(seen["label_blobs"] and seen["fillholes"])
        self.assertFalse(any(seen["label_blobs"]), seen)
        self.assertFalse(any(seen["fillholes"]), seen)

    def test_with_keeplargest_zero_only_fillholes_carries_it(self) -> None:
        """The CIP/SEA default. `fillholes` is on the unconditional path and still gets the
        switch; `label_blobs` is simply not called, which is a property of the IDL and not of
        this wiring."""
        seen = self._observe(jit=True, keeplargest=0)
        self.assertEqual(seen["label_blobs"], [])
        self.assertTrue(seen["fillholes"] and all(seen["fillholes"]), seen)

    def test_the_default_tail_op_has_it_off(self) -> None:
        """`TailOp.jit` is the one field with a default; every other is a fidelity-relevant
        threshold. An op built without it must be unchanged."""
        op = TailOp(stuckbits=0, rakefix=0, greythresh=0, dioderange=(0, 127),
                    numdiodes=128, keeplargest=1, res=10.0, yres=10.0)
        self.assertIs(op.jit, False)


class TheDriverCarriesItIntoASplitRun(unittest.TestCase):
    """`jobs > 1` reaches the same `TailOp` through `_LoopContext`, so the switch cannot be
    serial-only. Asserted structurally rather than by spawning workers: `soda2_process_2d`
    builds ONE `tail_op` and puts it in the context both loops read."""

    def test_tail_op_is_the_only_carrier_and_it_carries_jit(self) -> None:
        import inspect
        src = inspect.getsource(process_2d.soda2_process_2d)
        self.assertIn("tail_op = _tail_op(op, jit=jit)", src)
        self.assertIn("tail_op=tail_op", src)
        fields = {f.name for f in __import__("dataclasses").fields(process_2d._LoopContext)}
        self.assertIn("tail_op", fields)

    def test_soda2_process_2d_takes_jit_as_a_call_argument_not_an_op_key(self) -> None:
        import inspect
        sig = inspect.signature(process_2d.soda2_process_2d)
        self.assertIn("jit", sig.parameters)
        self.assertIs(sig.parameters["jit"].default, False)
        self.assertEqual(sig.parameters["jit"].kind, inspect.Parameter.KEYWORD_ONLY)


if __name__ == "__main__":
    unittest.main()

# SPDX-License-Identifier: BSD-3-Clause
"""``soda2 run --jit`` must move no written byte -- proven on the PRODUCT.

**Why this module exists, when two jit tests already did.**
*A byte-identical claim is a test, not a sentence.* Before this module, the
claim ``--jit`` makes on the command line -- *"The PBP files are byte-identical
to a run without it"* (``cli.py``'s ``soda2 run --jit`` help) -- was cited to
``tests/test_soda2_label_region_jit_identity.py``, which compares
**``label_blobs`` return arrays**, not PBP files. The two existing tests cover
the two ends and not the middle:

* ``test_soda2_label_region_jit_identity.py`` -- the kernel returns the same
  array, with mutation tests proving the comparison is not vacuous;
* ``test_soda2_jit_flag.py`` -- the flag reaches ``TailOp`` and both call
  sites.

Kernel-exact plus flag-arrives is a good *argument* that the product is
unchanged. It is not a measurement of it: everything between ``label_blobs``
and the bytes on disk -- ``fillholes``, ``particlesort``, the accumulator, the
PBP writers -- is taken on trust by that pair. This module runs the real
driver on a tracked fixture with the switch off and on and compares what was
actually written.

**The non-vacuity guard, and why it is the point.** A jit-vs-no-jit byte
comparison passes trivially if the kernel never engaged -- the two runs would
then be the same code path, and the test would certify nothing while looking
green. This is the failure the SODA-2 lane has already been bitten by once (a
refactor that was byte-identical *with every correction silently bypassed*).
So the child process reports ``arrayprobe_soda2.jit_kernels._LOADED is not
None`` after its run -- an observation made in the process that did the work,
of a module global only a ``jit=True`` ``label_blobs`` call sets -- and this
module requires it **True on the jit side and False on the other**. The two
sides of the check come from different places: one is the argument we passed,
the other is the module's own state afterwards.

**The exclusions are the sibling's, not new ones.** Comparison helpers are
imported from ``tests/test_soda2_parallel.py`` rather than restated, so the
one excused difference (``pbp_writer.py:235``'s ``Date Processed`` line, and
the ``.pbp.nc``'s ``DateProcessed`` attribute) is excused in exactly one place
and stays measured by that module's serial-vs-serial control.

Gated ``@slow`` for the same reason ``ParallelMatchesSerialSpec`` is: real
driver runs through a bounded subprocess, plus numba's first compile. CI runs
the gated set (``ARRAYPROBE_SLOW: "1"``).
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from typing import TYPE_CHECKING

from tests._slow import slow

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from test_soda2_parallel import (  # noqa: E402  (needs the sys.path line above)
    CIP_FIXTURE,
    SPEC_FIXTURE,
    _cip_op,
    _IdentityCase,
    _run_driver,
    _spec_op,
)


def _numba_present() -> bool:
    try:
        import numba  # noqa: F401
    except Exception:
        return False
    return True


if TYPE_CHECKING:  # the mixin type-checks as a TestCase; at runtime it stays a
    _MixinBase = unittest.TestCase  # plain object so the loader never collects it
else:
    _MixinBase = object


class _JitProductCase(_MixinBase):
    """One route's off-vs-on comparison. A mixin for the reason
    ``_IdentityCase`` is one: ``unittest`` collects every ``TestCase``
    subclass, so a base class holding these tests would run them with no
    ``op_builder``."""

    op_builder: staticmethod

    # The comparison, bound from the sibling module rather than restated, so
    # the timestamp exclusion lives in exactly one file and stays under that
    # file's serial-vs-serial control. Bound as plain functions: inheriting
    # `_IdentityCase` would also inherit its three jobs-vs-serial tests, which
    # this module has no business re-running.
    _assert_arrays_identical = _IdentityCase._assert_arrays_identical
    _assert_files_identical = _IdentityCase._assert_files_identical
    _assert_ncdf_identical = _IdentityCase._assert_ncdf_identical
    _differing_lines = _IdentityCase._differing_lines

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory(prefix="soda2jit_")
        self.addCleanup(self.tmpdir.cleanup)
        self.tmp = Path(self.tmpdir.name)
        self.op = type(self).op_builder(self.tmp)

    def test_the_product_is_identical_with_the_kernel_on(self) -> None:
        off = _run_driver(self.op, self.tmp, "jitoff", jobs=1, jit=False)
        on = _run_driver(self.op, self.tmp, "jiton", jobs=1, jit=True)
        # Non-vacuity FIRST: if the kernel did not engage, the comparison
        # below is two runs of one code path and means nothing, so fail here
        # with that reason rather than passing green further down.
        self.assertTrue(
            on.meta.get("kernel_loaded"),
            "the jit=True run finished without arrayprobe_soda2.jit_kernels ever "
            "loading, so the numba flood fill never ran and the byte comparison "
            "below would be comparing the pure-Python path with itself")
        self.assertFalse(
            off.meta.get("kernel_loaded"),
            "the jit=False run loaded the numba kernel, so `jit` is not the thing "
            "that selects it and this test does not discriminate")
        self._assert_arrays_identical(off, on, "jit-off-vs-jit-on")
        self._assert_files_identical(off, on, "jit-off-vs-jit-on")

    def test_it_is_still_identical_when_the_loop_is_also_split(self) -> None:
        """``--jit`` composes with ``--jobs``/``--chunks`` -- which the CLI help
        claims in a sentence, and which is the combination a long flight would
        actually be run with.

        **What this proves, and what it does not -- measured 2026-09-19.** The
        parent of a split run does **not** load the kernel, and that is correct
        rather than a break: the parent runs only the serial carry-in sweep
        (``_front_half``), and ``label_blobs``/``fillholes`` live in the tails,
        which run in the workers. So ``kernel_loaded`` is False here on a run
        that really did use the kernel, and asserting it True was this test's
        own first error. The assertion below therefore records where the work
        is, and engagement inside the worker is established elsewhere and by a
        different route:
        ``test_soda2_jit_flag.py::TheDriverCarriesItIntoASplitRun`` shows
        ``TailOp`` is the only carrier into a worker and that it carries
        ``jit``. That is the honest residual -- this module proves the split
        run's product is unchanged, not that the worker compiled."""
        off = _run_driver(self.op, self.tmp, "sjitoff", jobs=1, jit=False)
        on = _run_driver(self.op, self.tmp, "pjiton", jobs=2, chunks=3, jit=True)
        self.assertFalse(
            on.meta.get("kernel_loaded"),
            "the PARENT of a split jit run loaded the numba kernel. It should not: "
            "the parent runs only the carry-in sweep, and the per-buffer tails -- "
            "the only callers of label_blobs -- run in the workers. If this fires, "
            "tail work has moved back into the parent and the split is no longer "
            "doing what process_2d_parallel's docstring says it does")
        self._assert_arrays_identical(off, on, "serial-no-jit-vs-parallel-jit")
        self._assert_files_identical(off, on, "serial-no-jit-vs-parallel-jit")


@unittest.skipUnless(_numba_present(),
                     'numba is an optional extra (pip install "arrayprobe[jit]")')
@unittest.skipUnless(SPEC_FIXTURE.is_file(), f"missing fixture {SPEC_FIXTURE}")
@slow  # real driver runs through a bounded subprocess, plus numba's first compile.
class JitProductIdenticalSpec(_JitProductCase, unittest.TestCase):
    """The SPEC route -- the one the ENA 2D-S flights run, and the one the
    11-hour RF18 runs were on."""

    op_builder = staticmethod(_spec_op)


@unittest.skipUnless(_numba_present(),
                     'numba is an optional extra (pip install "arrayprobe[jit]")')
@unittest.skipUnless(CIP_FIXTURE.is_file(), f"missing fixture {CIP_FIXTURE}")
@slow  # same family.
class JitProductIdenticalCip(_JitProductCase, unittest.TestCase):
    """The SEA/CIP route, whose ``keeplargest`` path reaches ``fillholes`` --
    the second of the two call sites ``jit`` has to arrive at."""

    op_builder = staticmethod(_cip_op)


class TheHelpTextCitesAProductLevelTest(unittest.TestCase):
    """The reason this module was written, made mechanical.

    ``soda2 run --jit``'s help says the PBP files are byte-identical and names
    the test that asserts it. Until 2026-09-19 it named a test that compares
    ``label_blobs`` arrays. This check fails if the citation drifts back to a
    claim with no product-level test behind it -- a rule addressed to attention
    is not a control.
    """

    def test_the_flag_help_names_this_module(self) -> None:
        from arrayprobe import cli
        src = Path(cli.__file__).read_text(encoding="utf-8")
        self.assertIn("test_soda2_jit_product_identity.py", src,
                      "the --jit help no longer cites the product-level byte-identity "
                      "test; a byte-identical claim is a test, not a sentence")


if __name__ == "__main__":
    unittest.main()

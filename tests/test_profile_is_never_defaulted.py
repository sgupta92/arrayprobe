# SPDX-License-Identifier: BSD-3-Clause
"""No entry point may supply a ``FidelityProfile`` for a caller who forgot one.

WHY THIS EXISTS (2026-09-09).  ``profiles.py`` states the rule in its
own header -- *"No field gets a 'sensible' default that silently picks a side.
The profile is a required argument wherever it matters"* -- and
``read_binary_SPEC``'s docstring repeated it: *"it has no default that is safe to
rely on, so pass it explicitly."*  Its signature said otherwise.  Three reader
entry points carried one: ``read_binary_SPEC`` and ``read_binary_SPEC_parallel``
defaulted to ``STOCK_V314``, ``read_binary_hvps`` to ``ORACLES_2016``.

That is not a style point.  ``spec_buffer_guard`` is ``True`` in stock and
``False`` in the ORACLES variant, and it decides whether a truncated packet is
skipped or *raises* -- which is what the MATLAB of record does.  A caller who
omitted ``profile=`` got the stock reading of a file the reference data was not
produced under, and got it silently, with a plausible shorter output.  Every
call site in the package and the driver already passed one explicitly, so
removing the defaults changed no run: it closed a trap for the next caller.

**This is written as a sweep rather than as three assertions on purpose.**  The
same defect would be equally invisible in a fourth entry point added later, and
a test naming the three files it knows about would not see it.  So it walks the
package and fails on any parameter that names a profile and supplies one.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
import unittest

from tests._profile_registry_guard import module_hooks
from tests._repo import needs_v314_engine  # noqa: E402

import arrayprobe
import arrayprobe_soda2
import arrayprobe_uiops
from arrayprobe.profiles import FidelityProfile

# The package walk below imports arrayprobe_uiops.register_image_assisted and
# register_arm_stock, each of which registers a profile at import time; undo that
# so 'stock-v3.5-image-assisted' / 'arm-ena-stock-v3.5' do not leak into later modules.
setUpModule, tearDownModule = module_hooks()

#: Every port in this repository, not just the first one. Added 2026-09-12:
#: the sweep walked `arrayprobe` alone, so `arrayprobe_uiops` and
#: `arrayprobe_soda2` could carry exactly the defect it exists to catch and it
#: would pass. A guard scoped to one package in a repository that now ships
#: three is a guard that reports on a third of the code.
PACKAGES = (arrayprobe, arrayprobe_uiops, arrayprobe_soda2)

#: Callables whose ``profile=None`` default is accepted, each by its exact qualified name and
#: with the reason. An exemption covers that one function only; any other callable in any of
#: the three packages that defaults a profile still fails, and a row whose function stops
#: defaulting a profile (or disappears) fails :meth:`test_every_exemption_is_still_an_offender`.
_DRIVER_STAMP = (
    "The batch flight driver, moved into the package from scripts/ on 2026-10-01; in scripts/ it "
    "sat outside this sweep's scope. None here resolves to the driver's module global PROFILE "
    "at call time -- the one profile every stage of the run computes with, rebound by "
    "--profile or --config [fidelity].profile and logged at run start -- and the function only "
    "writes or compares the provenance stamp recording that profile. It selects no variant of "
    "its own: the stamp names whatever the run computes under.")
EXEMPT: dict[str, str] = {
    "arrayprobe.driver.run_flight.config_label": _DRIVER_STAMP,
    "arrayprobe.driver.run_flight.image_call_label": _DRIVER_STAMP,
    "arrayprobe.driver.run_flight.proc_call_label": _DRIVER_STAMP,
    "arrayprobe.driver.run_flight.sd_call_label": _DRIVER_STAMP,
    "arrayprobe.driver.run_flight.sd_is_current": _DRIVER_STAMP,
    "arrayprobe.tune.diodes.counting_convention": (
        "profile is a profile NAME (str), and None means 'take it from the proc file's own "
        ".call stamp'. With no stamped profile on a v3.1.4 file it raises DiodeReportError "
        "('no profile named ... name the profile') rather than picking one, and a profile that "
        "disagrees with the stamp is refused. Nothing is chosen for a caller who named nothing."),
    "arrayprobe.tune.diodes.report": (
        "Passes profile straight to counting_convention (above), which refuses rather than "
        "picks when neither the caller nor the file's stamp names a profile."),
}


def _every_callable():
    """(qualified name, object) for every function and method in the package."""
    seen = set()
    for pkg in PACKAGES:
      for info in pkgutil.walk_packages(pkg.__path__, prefix=pkg.__name__ + "."):
          module = importlib.import_module(info.name)
          for attr_name, attr in vars(module).items():
              if attr_name.startswith("_"):
                  continue
              if inspect.isfunction(attr) and attr.__module__ == info.name:
                  yield f"{info.name}.{attr_name}", attr
              elif inspect.isclass(attr) and attr.__module__ == info.name:
                  if attr in seen:
                      continue
                  seen.add(attr)
                  for meth_name, meth in vars(attr).items():
                      if inspect.isfunction(meth) and not meth_name.startswith("__"):
                          yield f"{info.name}.{attr_name}.{meth_name}", meth


def _offenders() -> list[str]:
    """``name(param=default)`` for every parameter that names a profile and has a default."""
    offenders = []
    for name, func in _every_callable():
        try:
            sig = inspect.signature(func)
        except (ValueError, TypeError):       # pragma: no cover -- builtins
            continue
        for param in sig.parameters.values():
            if param.default is inspect.Parameter.empty:
                continue
            names_a_profile = (
                param.name == "profile"
                or param.annotation is FidelityProfile
                or param.annotation == "FidelityProfile"
                or isinstance(param.default, FidelityProfile))
            if names_a_profile:
                offenders.append(f"{name}({param.name}={param.default!r})")
    return offenders


def _unexempted(offenders: list[str]) -> list[str]:
    """The offenders whose exact qualified name is not an :data:`EXEMPT` key."""
    return [o for o in offenders if o.split("(", 1)[0] not in EXEMPT]


class NoProfileParameterHasADefault(unittest.TestCase):
    @needs_v314_engine
    def test_the_sweep_reaches_the_readers_it_was_written_for(self):
        """A sweep that walked nothing would pass. Name what it must have seen."""
        names = {name for name, _ in _every_callable()}
        for expected in ("arrayprobe.readers.spec.read_binary_SPEC",
                         "arrayprobe.readers.spec.read_binary_SPEC_parallel",
                         "arrayprobe.readers.spec.read_binary_hvps",
                         "arrayprobe.imgproc.imgproc_sm",
                         # ...and the other two ports, so an extension that
                         # silently walked nothing fails here rather than passing.
                         "arrayprobe_uiops.imgproc.imgproc_sm_v35",
                         "arrayprobe_uiops.sizedist.run",
                         "arrayprobe_soda2.sample_area.sample_area"):
            self.assertIn(expected, names)

    def test_no_callable_defaults_a_profile(self):
        offenders = _unexempted(_offenders())
        self.assertEqual(
            offenders, [],
            "a profile with a default picks a MATLAB variant for a caller who did "
            "not name one; spec_buffer_guard alone is the difference between "
            "skipping a truncated packet and raising, which is what the MATLAB of "
            "record does. Make it required (keyword-only, no default) and pass it "
            "at the call site.")

    def test_every_exemption_is_still_an_offender(self):
        """An exemption whose function no longer defaults a profile is stale, never a skip."""
        live = {o.split("(", 1)[0] for o in _offenders()}
        stale = sorted(set(EXEMPT) - live)
        self.assertEqual(stale, [], f"EXEMPT rows that no longer default a profile: {stale}")

    def test_an_exemption_covers_its_own_function_only(self):
        """The filter the real sweep uses, fed a profile default added beside an exempt function
        in the same driver module and one in another module: both are reported."""
        planted = ["arrayprobe.driver.run_flight.config_label(profile=None)",
                   "arrayprobe.driver.run_flight.some_new_stage(profile=None)",
                   "arrayprobe.imgproc.some_new_entry(profile=None)"]
        self.assertEqual(_unexempted(planted), planted[1:])

    def test_exemption_reasons_are_substantive(self):
        for name, reason in EXEMPT.items():
            with self.subTest(name):
                self.assertGreater(len(reason.strip()), 60)

    @needs_v314_engine
    def test_the_three_readers_refuse_a_call_without_one(self):
        """The signature check above is structural; this executes the refusal.

        The paths are inside a temporary directory rather than bare names: with
        the default put back -- which is what mutation-testing this file does --
        the call is valid and the body opens its output for writing. Bare names
        left a file called ``no-such-output`` in ``python_port/``.
        """
        import tempfile

        from arrayprobe.readers import spec
        with tempfile.TemporaryDirectory() as tmp:
            for func in (spec.read_binary_SPEC, spec.read_binary_SPEC_parallel,
                         spec.read_binary_hvps):
                with self.subTest(func=func.__name__):
                    with self.assertRaises(TypeError):
                        func(f"{tmp}/no-such-input", f"{tmp}/no-such-output")


if __name__ == "__main__":
    unittest.main()

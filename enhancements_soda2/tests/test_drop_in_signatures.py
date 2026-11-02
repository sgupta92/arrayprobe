# SPDX-License-Identifier: BSD-3-Clause
"""Every routed SODA-2 correction accepts exactly the call its port binding accepts.

A substitution installed at an ``arrayprobe_soda2.enhancement_hooks`` point is called by the
unmodified driver with the port function's own arguments. When the port gains a keyword the
substitution does not take, the run fails with ``TypeError`` at the first particle -- which
is what happened to ``fillholes`` the day the port's version gained ``jit``. Checked here for
every point in ``_adapter.ROUTES`` rather than one test per module, so a new route or a new
port keyword is covered without anyone remembering to add a test.

Positional parameters must match in order, name, kind and default; keyword-only parameters
must match as a set (their order does not affect a call).
"""

from __future__ import annotations

import inspect
import unittest
from unittest import mock

from arrayprobe_soda2 import enhancement_hooks

from arrayprobe_soda2_enhancements import _adapter
from arrayprobe_soda2_enhancements.registry import load_all


def _shape(fn):
    params = list(inspect.signature(fn).parameters.values())
    positional = [(p.name, p.kind, p.default) for p in params
                  if p.kind is not inspect.Parameter.KEYWORD_ONLY]
    keyword = {p.name: p.default for p in params if p.kind is inspect.Parameter.KEYWORD_ONLY}
    return positional, keyword


def _replacement(name: str):
    point = _adapter.ROUTES[name]
    return _adapter.replacements({name: True})[0][point]


class EveryRoutedCorrectionMatchesItsPortBinding(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        load_all()

    def test_each_substitution_takes_the_port_functions_call(self):
        self.assertTrue(_adapter.ROUTES)
        for name, point in sorted(_adapter.ROUTES.items()):
            with self.subTest(correction=name, point=point):
                self.assertEqual(_shape(_replacement(name)),
                                 _shape(enhancement_hooks.original(point)))

    def test_mutation_a_port_keyword_the_substitution_lacks_is_caught(self):
        """The check has teeth: give one port binding a keyword its substitution lacks."""
        name, point = "fillholes_int_labels", _adapter.ROUTES["fillholes_int_labels"]
        port = enhancement_hooks.original(point)

        def widened(*args, new_keyword=False, **kwargs):
            return port(*args, **kwargs)
        widened.__signature__ = inspect.signature(port).replace(parameters=[
            *inspect.signature(port).parameters.values(),
            inspect.Parameter("new_keyword", inspect.Parameter.KEYWORD_ONLY, default=False)])
        with mock.patch.object(enhancement_hooks, "original", return_value=widened):
            self.assertNotEqual(_shape(_replacement(name)),
                                _shape(enhancement_hooks.original(point)))


if __name__ == "__main__":
    unittest.main()

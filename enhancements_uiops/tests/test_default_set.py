# SPDX-License-Identifier: BSD-3-Clause
"""``[enhancements] all = true`` and :func:`registry.default_set` -- the three outputs per run (2026-09-23).

The author's default is *v3.5 with all enhancements*. Until this date that default existed
only as config files naming every applicable module by hand, so taking one module out of the
default meant editing each of them. The author then ruled, on the measured cost of ``outoffocus``
(no diameter changed on v3.5, about 94 % of the enhancement pass's time): *"outoffocus: ... make it
an opt in?"*. These tests pin both states of that ruling:

* ``all = true`` on v3.5 does NOT switch ``outoffocus`` on;
* ``all = true`` plus ``outoffocus = true`` does, because naming a module is still the opt-in;

and the invariants that keep ``all`` from becoming a second, looser default:

* no ``[enhancements]`` entries, or ``all = false``, still resolves nothing ON;
* ``all = true`` never switches on a module the engine does not apply to, and never raises for one;
* an explicit ``<name> = false`` beside ``all = true`` wins.
"""

from __future__ import annotations

import contextlib
import importlib.util
import unittest
from unittest import mock

from arrayprobe_enhancements import applicability, registry

#: The v3.1.4 engine is installed in the development repository and absent from a
#: release tree. Read from the engine, not from the enhancement modules whose omission
#: the test below checks, and not from a repository file above this distribution's root.
V314_INSTALLED = importlib.util.find_spec("arrayprobe.sizedist") is not None


@contextlib.contextmanager
def simulated_release_view():
    """The release view inside the development tree: every ``REQUIRES_V314`` module moved
    from ``REGISTRY``/``APPLICABILITY`` to ``OMITTED``/``OMITTED_APPLICABILITY``, as the
    import-time pass does when the module file is absent. All four tables are restored."""
    names = sorted(applicability.REQUIRES_V314 & set(registry.REGISTRY))
    with mock.patch.dict(registry.REGISTRY), mock.patch.dict(registry.OMITTED),             mock.patch.dict(applicability.APPLICABILITY),             mock.patch.dict(applicability.OMITTED_APPLICABILITY):
        for n in names:
            registry.OMITTED[n] = registry.REGISTRY.pop(n)
            applicability.OMITTED_APPLICABILITY[n] = applicability.APPLICABILITY.pop(n)
        yield names


def _on(resolved: dict[str, bool]) -> set[str]:
    return {n for n, v in resolved.items() if v}


class OutoffocusIsOptInOnV35(unittest.TestCase):
    def test_all_does_not_switch_outoffocus_on_under_v35(self):
        self.assertNotIn("outoffocus", registry.default_set("3.5"))
        self.assertFalse(registry.resolve({"all": True}, engine="3.5")["outoffocus"])

    def test_naming_it_still_switches_it_on_under_v35(self):
        got = registry.resolve({"all": True, "outoffocus": True}, engine="3.5")
        self.assertTrue(got["outoffocus"])
        self.assertTrue(registry.resolve({"outoffocus": True}, engine="3.5")["outoffocus"])

    def test_v314_keeps_it_in_its_default_set(self):
        """On v3.1.4 the correction does change diameters, so the ruling is engine-scoped."""
        self.assertIn("outoffocus", registry.default_set("3.1.4"))
        self.assertTrue(registry.resolve({"all": True}, engine="3.1.4")["outoffocus"])

    def test_every_exclusion_names_a_registered_module_and_a_reason(self):
        for engine, table in registry.DEFAULT_SET_EXCLUSIONS.items():
            self.assertIn(engine, applicability.ENGINES)
            for name, reason in table.items():
                self.assertIn(name, registry.REGISTRY)
                self.assertTrue(reason.strip())


class AllIsNotALooserDefault(unittest.TestCase):
    def test_absent_or_false_resolves_nothing(self):
        for table in ({}, {"all": False}, None):
            with self.subTest(table=table):
                self.assertEqual(_on(registry.resolve(table, engine="3.5")), set())

    def test_all_is_exactly_the_applicable_set_minus_exclusions(self):
        for engine in applicability.ENGINES:
            with self.subTest(engine=engine):
                want = {n for n in registry.REGISTRY if applicability.applicable(n, engine)}
                want -= set(registry.DEFAULT_SET_EXCLUSIONS.get(engine, {}))
                self.assertEqual(_on(registry.resolve({"all": True}, engine=engine)), want)

    @unittest.skipIf("conc_arear_fix" in registry.OMITTED,
                     "release view: conc_arear_fix needs the v3.1.4 engine and does not ship; "
                     "test_all_never_resolves_an_omitted_module covers it there")
    def test_all_never_raises_for_a_module_the_engine_does_not_apply(self):
        # conc_arear_fix is fixed upstream in v3.5; naming it raises, `all` must not.
        self.assertFalse(applicability.applicable("conc_arear_fix", "3.5"))
        got = registry.resolve({"all": True}, engine="3.5")
        self.assertFalse(got["conc_arear_fix"])

    def test_all_resolves_every_inapplicable_module_off(self):
        """Both views: every registered module v3.5 does not apply resolves off under `all`."""
        got = registry.resolve({"all": True}, engine="3.5")
        for name in registry.REGISTRY:
            if not applicability.applicable(name, "3.5"):
                with self.subTest(name=name):
                    self.assertFalse(got[name])

    def _assert_omitted_are_refused(self):
        omitted = sorted(registry.OMITTED)
        self.assertTrue(omitted)
        self.assertLessEqual(set(omitted), set(applicability.REQUIRES_V314))
        self.assertEqual(set(omitted), set(applicability.OMITTED_APPLICABILITY))
        for engine in applicability.ENGINES:
            got = registry.resolve({"all": True}, engine=engine)
            for name in omitted:
                with self.subTest(engine=engine, name=name):
                    self.assertNotIn(name, got)
                    self.assertNotIn(name, registry.default_set(engine))
                    self.assertNotIn(name, applicability.APPLICABILITY)
                    with self.assertRaisesRegex(registry.UnknownEnhancement, name):
                        registry.resolve({name: True}, engine=engine)

    @unittest.skipUnless(registry.OMITTED, "development view: every module ships")
    def test_all_never_resolves_an_omitted_module(self):
        """Release view: an omitted module is absent from `all` and refused by name."""
        self._assert_omitted_are_refused()

    def test_the_release_view_refuses_each_omitted_module_simulated(self):
        before = (dict(registry.REGISTRY), dict(registry.OMITTED))
        with simulated_release_view() as names:
            self.assertEqual(sorted(registry.OMITTED), sorted(set(names) | set(before[1])))
            self._assert_omitted_are_refused()
        self.assertEqual((registry.REGISTRY, registry.OMITTED), before)  # restored

    def test_a_name_neither_registered_nor_omitted_still_fails(self):
        with simulated_release_view():
            with self.assertRaises(registry.UnknownEnhancement):
                registry.resolve({"conc_arear_fixx": True}, engine="3.5")
        with self.assertRaises(registry.UnknownEnhancement):
            registry.resolve({"conc_arear_fixx": True}, engine="3.5")

    def test_an_explicit_false_beside_all_wins(self):
        got = registry.resolve({"all": True, "published_dof": False}, engine="3.5")
        self.assertFalse(got["published_dof"])
        self.assertTrue(got["hole_edge_swap"])

    def test_the_all_key_is_not_itself_an_unknown_enhancement(self):
        registry.resolve({"all": True}, engine="3.5")  # does not raise UnknownEnhancement
        with self.assertRaises(registry.UnknownEnhancement):
            registry.resolve({"al": True}, engine="3.5")


@unittest.skipUnless(V314_INSTALLED, "release view: the v3.1.4 engine does not ship")
class TheDevelopmentViewOmitsNothing(unittest.TestCase):
    """With the allow-list present (development), every v3.1.4-only module ships, so no
    release-view excusal above can fire here."""

    def test_nothing_is_omitted(self):
        self.assertEqual(registry.OMITTED, {})
        self.assertEqual(applicability.OMITTED_APPLICABILITY, {})
        self.assertLessEqual(set(applicability.REQUIRES_V314), set(registry.REGISTRY))


if __name__ == "__main__":
    unittest.main()

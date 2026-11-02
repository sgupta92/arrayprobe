# SPDX-License-Identifier: BSD-3-Clause
"""``v35-2ds-ladder-fix`` is built from its cited tables, not from a campaign case.

The batch driver applies ``v35-2ds-ladder-fix`` by default to every engine-3.5 2D-S run
(``run_flight._s4_probe_case``), so the general correction must not depend on a case named
for one campaign. Two things are asserted:

1. **Its contents are pinned.** Every field equals a literal copied from the code as it
   stood when the case was still built through ``register_arm_ena_2ds()`` (captured
   2026-10-16, before the construction changed): v3.5's own ``otherwise``/``'2DS'``
   constants (``UIOPS-v3.5/joefinlon-UIOPS-039be82/sizeDist.m:499-520``) on v3.1.4's 128-bin
   10 um ladder (``UIOPS-v3.1.4/joefinlon-UIOPS-ba5e67c/sizeDist.m:374``, ``:376``). The
   ladder's edges are pinned by SHA-256 of their bytes, so a one-ULP change fails.
2. **Building it registers no other case**: with every ARM and ORACLES registration patched
   to raise, it still builds, and the only name it registers is its own.
"""

from __future__ import annotations

import hashlib
import importlib.util
import unittest
from unittest import mock

import numpy as np

from arrayprobe_uiops import probe_cases
from arrayprobe_uiops.sizedist_tables import BinLadder, ProbeDefaults


def _has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


#: The ARM ENA registration modules are development-only: a distribution may
#: ship without them, and the tests that exercise those cases skip there.
_needs_arm_ena = unittest.skipUnless(
    _has_module("arrayprobe_uiops.register_arm_ena_2ds"),
    "arrayprobe_uiops.register_arm_ena_2ds: the ARM ENA registration module is not in "
    "this distribution",
)

_V35 = "UIOPS-v3.5/joefinlon-UIOPS-039be82/sizeDist.m"
_V314 = "UIOPS-v3.1.4/joefinlon-UIOPS-ba5e67c/sizeDist.m"

#: Every ProbeDefaults field, with its type, as the case resolved before the refactor.
PINNED_DEFAULTS = {
    "num_diodes": 128,                 # v3.5 :499
    "diodesize": 0.01,                 # v3.5 :500
    "armdst": 63.0,                    # v3.5 :501
    "num_bins": 128,                   # v3.1.4 :374
    "probetype": 2,                    # v3.5 :508
    "tasMax": 170.0,                   # v3.5 :509
    "applyIntArrThresh": 0,            # v3.5 :514
    "defaultIntArrThresh": 4e-06,      # v3.5 :515
    "reaccptShatrs": 0,                # v3.5 :516
    "reaccptD": 0.5,                   # v3.5 :517
    "reaccptMaxIA": 1e-06,             # v3.5 :518
    "intar_threshold_defaulted": True,  # v3.5 :520
    "calls_getPECANparams": False,     # v3.5 :497-520
}

#: SHA-256 of ``bins.edges(0.01, 128)``'s bytes (129 float64 edges, 0.005 to 1.285 mm).
PINNED_EDGES_SHA256 = {
    False: "69304647c209ef6908fc0677c00c459c0c484edd60e9dd39ca36b7c5dd976182",  # MATLAB colon
    True: "1ce78d94c345b3f6fdccb9e38c0d911e16022b06ba1eb13ec8762487efd7e06d",  # Octave colon
}

PINNED_DESCRIPTION = (
    "Swapped-bin-table correction: a 2D-S on v3.5's otherwise branch is sized on the 2D-S "
    "128-bin 10 um ladder upstream commented out at sizeDist.m:506-507, not the HVPS 28-bin "
    "0.2-30 mm table at :502-505. Default on in the batch driver on engine 3.5."
)

PINNED_CITATIONS = {
    "num_diodes": f"{_V35}:499 -- num_diodes = 128",
    "diodesize": f"{_V35}:500 -- diodesize = .010",
    "armdst": f"{_V35}:501 -- armdst = 63.",
    "num_bins": f"{_V314}:374 -- num_bins = 128 (v3.5's :502 is the HVPS 28)",
    "bins": (
        f"{_V314}:376 -- kk = diodesize/2:diodesize:(num_bins+0.6)*diodesize "
        f"(the identical line is commented out at {_V35}:507)"
    ),
    "probetype": f"{_V35}:508 -- probetype = 2",
    "tasMax": f"{_V35}:509 -- tasMax = 170",
    "applyIntArrThresh": f"{_V35}:514 -- applyIntArrThresh = 0",
    "defaultIntArrThresh": f"{_V35}:515 -- defaultIntArrThresh = 4e-6",
    "reaccptShatrs": f"{_V35}:516 -- reaccptShatrs = 0",
    "reaccptD": f"{_V35}:517 -- reaccptD = 0.5",
    "reaccptMaxIA": f"{_V35}:518 -- reaccptMaxIA = 1e-6",
    "intar_threshold_defaulted": (
        f"{_V35}:520 -- intar_threshold = ones(size(tas_time))*defaultIntArrThresh"
    ),
    "calls_getPECANparams": (
        f"{_V35}:497-520 -- the otherwise/'2DS' case calls getPECANparams() nowhere"
    ),
}


class TestTheCaseEqualsItsPinnedConstants(unittest.TestCase):
    def setUp(self):
        self.case = probe_cases.register_v35_2ds_ladder_fix()

    def test_name_and_description(self):
        self.assertEqual(self.case.name, "v35-2ds-ladder-fix")
        self.assertEqual(self.case.description, PINNED_DESCRIPTION)

    def test_every_scalar_field_and_its_type(self):
        d = self.case.defaults
        self.assertIsInstance(d, ProbeDefaults)
        self.assertEqual(
            set(ProbeDefaults.__dataclass_fields__), set(PINNED_DEFAULTS) | {"bins"}
        )
        for field, want in PINNED_DEFAULTS.items():
            got = getattr(d, field)
            with self.subTest(field=field):
                self.assertIs(type(got), type(want))
                self.assertEqual(got, want)

    def test_the_ladder_edges_are_byte_identical(self):
        d = self.case.defaults
        self.assertIsInstance(d.bins, BinLadder)
        for octave, want in PINNED_EDGES_SHA256.items():
            edges = d.bins.edges(d.diodesize, d.num_bins, octave_colon=octave)
            with self.subTest(octave_colon=octave):
                self.assertEqual(edges.dtype, np.float64)
                self.assertEqual(edges.shape, (129,))
                self.assertEqual(hashlib.sha256(edges.tobytes()).hexdigest(), want)
        self.assertTrue(np.array_equal(d.kk(), d.bins.edges(d.diodesize, d.num_bins)))

    def test_citations(self):
        self.assertEqual(dict(self.case.citations), PINNED_CITATIONS)

    @_needs_arm_ena
    def test_it_still_equals_the_arm_case_it_was_built_from(self):
        # Same defaults as before the refactor, when it reused arm-ena-2ds's. The pinned
        # constants above stand on their own; this cross-check needs the ARM module.
        from arrayprobe_uiops import register_arm_ena_2ds as arm_ena_2ds

        self.assertEqual(self.case.defaults, arm_ena_2ds.register_arm_ena_2ds().defaults)


class TestBuildingItRegistersNoCampaignCase(unittest.TestCase):
    def test_no_arm_or_oracles_registration_is_called(self):
        registered: list[str] = []
        real_register = probe_cases.register_probe_case

        def spy(case):
            registered.append(case.name)
            return real_register(case)

        with mock.patch.multiple(
            probe_cases,
            register_probe_case=spy,
        ):
            case = probe_cases.register_v35_2ds_ladder_fix()
        self.assertFalse(hasattr(probe_cases, "register_oracles_2016_cip_iat"))
        self.assertEqual(registered, ["v35-2ds-ladder-fix"])
        self.assertEqual(case.name, "v35-2ds-ladder-fix")
        self.assertIs(probe_cases.V35_2DS_LADDER_FIX, case)


if __name__ == "__main__":
    unittest.main()

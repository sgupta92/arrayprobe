# SPDX-License-Identifier: BSD-3-Clause
"""A queue naming the channel explicitly still finds its flight.

THE INCIDENT, 2026-09-16. The ACE-ENA 07-07 labelling queue was built with
``"flight": "base170707102822.H"``. ``_discover_flights`` gives the **bare** stem
to whichever channel wins -- ``.H`` first -- so the directory yielded the key
``base170707102822`` and never ``base170707102822.H``. Every item in the queue
rendered "Queue item references unknown flight" while the index listed that very
flight one line above, and the labelling pass could not start at all.

WHY THE FIX IS IN THE LOOKUP AND NOT IN THE QUEUE FILE. Rewriting the one file
would have unblocked the evening and left the next queue from
a comparison run to hit it again. The resolver accepts the
explicit form only when dropping the channel lands on a real flight whose own
channel is the one asked for, so a genuinely wrong name still fails loudly rather
than being mapped onto a neighbouring flight -- which would attach labels to the
wrong particles, the worst outcome available here.
"""
from __future__ import annotations

import unittest

from arrayprobe.triage_server import _CHANNEL_PROBE, _resolve_queue_flight, describe_queue

FLIGHTS = {
    "base170707102822": {"probe": "2DS"},   # the .H proc, holding the bare stem
    "cip160906s1": {"probe": "CIP"},
}


class TheExplicitChannelFormResolves(unittest.TestCase):
    def test_the_H_form_finds_the_bare_stem(self) -> None:
        """The exact case that blocked the ARM labelling pass."""
        self.assertEqual("base170707102822",
                         _resolve_queue_flight("base170707102822.H", FLIGHTS))

    def test_the_bare_name_still_resolves_to_itself(self) -> None:
        self.assertEqual("base170707102822",
                         _resolve_queue_flight("base170707102822", FLIGHTS))

    def test_a_cip_queue_resolves_the_same_way(self) -> None:
        self.assertEqual("cip160906s1", _resolve_queue_flight("cip160906s1.CIP", FLIGHTS))


class AWrongNameStillFails(unittest.TestCase):
    """Loudly wrong beats quietly wrong: these labels identify particles."""

    def test_a_mismatched_channel_is_refused(self) -> None:
        """`.CIP` on a 2D-S flight is not a naming variant, it is a mistake."""
        self.assertIsNone(_resolve_queue_flight("base170707102822.CIP", FLIGHTS))
        self.assertIsNone(_resolve_queue_flight("cip160906s1.H", FLIGHTS))

    def test_an_unknown_flight_is_refused(self) -> None:
        self.assertIsNone(_resolve_queue_flight("nope", FLIGHTS))
        self.assertIsNone(_resolve_queue_flight("bogus.H", FLIGHTS))

    def test_a_non_string_is_refused(self) -> None:
        """A malformed queue file must not crash a labelling pass."""
        for bad in (None, 42, ["base170707102822"]):
            with self.subTest(value=bad):
                self.assertIsNone(_resolve_queue_flight(bad, FLIGHTS))

    def test_an_empty_stem_is_refused(self) -> None:
        self.assertIsNone(_resolve_queue_flight(".H", FLIGHTS))


class TheChannelMapIsWhatTheResolverTrusts(unittest.TestCase):
    def test_every_known_channel_maps_to_a_probe(self) -> None:
        """The resolver compares against this map, so an empty one would make it
        accept nothing -- the silent-guard failure this project keeps finding."""
        self.assertTrue(_CHANNEL_PROBE)
        self.assertIn("H", _CHANNEL_PROBE)
        for channel, probe in _CHANNEL_PROBE.items():
            with self.subTest(channel=channel):
                self.assertTrue(probe)



class QueueTitlesSpellOutWhatTheCodesMean(unittest.TestCase):
    """Author, 2026-09-16, mid-labelling-pass: *"U-imgproc_i__S-interarrival --
    these titles should spell out what the package and code mean for each
    category"*. Nobody should hold a reject-code table in their head while
    deciding what a particle is.
    """

    def test_both_sides_are_named_in_words(self) -> None:
        got = describe_queue("U-imgproc_i__S-interarrival")
        self.assertIn("UIOPS rejects", got)
        self.assertIn("side scans contradict the hollow verdict", got)
        self.assertIn("SODA-2 rejects", got)
        self.assertIn("inter-arrival time", got)

    def test_acceptance_reads_as_acceptance_not_as_a_rejection_reason(self) -> None:
        self.assertIn("SODA-2 accepts", describe_queue("U-z__S-accepted"))
        self.assertIn("UIOPS accepts", describe_queue("U-accepted__S-arearatio"))

    def test_combined_soda2_bits_are_all_named(self) -> None:
        got = describe_queue("U-imgproc_a__S-arearatio.interarrival.centerin")
        for phrase in ("area ratio", "inter-arrival time", "centre outside the sample area"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, got)

    def test_uiops_z_is_the_area_ratio_gate_not_zero_area(self) -> None:
        """Two different tests share the letter ``z``.

        UIOOPS's queue token ``z`` is sizeDist's area-ratio gate (the threshold
        ``compare_soda2_uiops.load_uiops`` reads from the product's stamp); imgproc's own ``z`` is
        zero area (``matlab_compat.REJECT_CODES``). Describing the first as the
        second would mislabel the very cell this campaign turns on.
        """
        self.assertIn("area ratio below", describe_queue("U-z__S-accepted"))
        self.assertIn("zero area", describe_queue("U-imgproc_z__S-accepted"))

    def test_an_unknown_token_is_shown_verbatim(self) -> None:
        """A new reject bit must appear as itself, never be guessed at."""
        got = describe_queue("U-brand_new_gate__S-someday_bit")
        self.assertIn("brand_new_gate", got)
        self.assertIn("someday_bit", got)

    def test_a_hand_written_queue_name_is_left_alone(self) -> None:
        self.assertEqual("my_review_pass", describe_queue("my_review_pass"))

    def test_every_documented_soda2_bit_has_words(self) -> None:
        """The map must cover the bit table it is derived from, or a real queue
        would render a raw token to the person labelling it."""
        from arrayprobe.triage_server import _SODA2_REASON_TEXT
        for bit in ("arearatio", "interarrival", "size_range", "centerin",
                    "cluster", "water", "irregular", "dof"):
            with self.subTest(bit=bit):
                self.assertIn(bit, _SODA2_REASON_TEXT)

if __name__ == "__main__":
    unittest.main()

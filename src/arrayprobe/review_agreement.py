# SPDX-License-Identifier: BSD-3-Clause
"""Label agreement for the triage server -- Track V phase 2, item 3.

**What the plan asked for:** *"re-show a fraction of already-reviewed particles, both to the same
reviewer later and to a second reviewer. Report Cohen's kappa. Until this exists, every accuracy
number in ``ml_accept_reject.py`` is measured against labels of unknown noise."*

Two halves:

* :func:`recheck_queue` writes a queue file of a seeded random fraction of the particles a
  *person* has labelled (``source == "human"``; bulk or model labels are never re-checked as
  though a person made them). The queue name starts with ``recheck-``, which the triage server
  reads as "store these verdicts in ``<flight>.recheck.json`` and do not show the first label".
* :func:`agreement` pairs the first labels with the re-check labels and reports Cohen's kappa,
  the observed and chance agreement, and the confusion matrix.

**This changes no computed number.** It chooses which particles a person sees again and
summarises what they said, beside ``review_sampling`` and ``triage_server``.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path

from .triage_server import RECHECK_PREFIX, _load_verdicts


@dataclass
class Agreement:
    """Agreement between two passes of labels over the same particles: how many, the observed
    and chance agreement, Cohen's kappa (``None`` when undefined) and the confusion matrix."""

    n: int
    observed: float
    expected: float
    kappa: float | None
    labels: list[str]
    confusion: dict[str, dict[str, int]] = field(default_factory=dict)
    """``confusion[first][second]``: how many particles got ``first`` then ``second``."""


def cohen_kappa(first: list[str], second: list[str]) -> Agreement:
    """Cohen's kappa for two label lists of equal length (Cohen 1960).

    ``kappa = (p_o - p_e) / (1 - p_e)``. When both raters used a single label for every item,
    ``p_e == 1`` and kappa is undefined: returned as ``None`` rather than a number that looks
    like a finding.
    """
    if len(first) != len(second):
        raise ValueError(f"paired label lists differ in length: {len(first)} != {len(second)}")
    n = len(first)
    labels = sorted(set(first) | set(second))
    confusion = {a: {b: 0 for b in labels} for a in labels}
    for a, b in zip(first, second, strict=True):
        confusion[a][b] += 1
    if n == 0:
        return Agreement(0, float("nan"), float("nan"), None, labels, confusion)
    p_o = sum(confusion[x][x] for x in labels) / n
    p_e = sum((sum(confusion[x].values()) / n) * (sum(confusion[a][x] for a in labels) / n)
              for x in labels)
    kappa = None if p_e == 1.0 else (p_o - p_e) / (1.0 - p_e)
    return Agreement(n, p_o, p_e, kappa, labels, confusion)


def human_labels(verdicts: dict) -> dict[str, str]:
    """``particle_index -> verdict`` for the entries a person made."""
    return {k: v["verdict"] for k, v in verdicts.items()
            if isinstance(v, dict) and v.get("source") == "human" and "verdict" in v}


def recheck_queue(decoded_dir: Path, flight: str, out: Path, *, fraction: float = 0.2,
                  seed: int = 0, minimum: int = 1) -> dict:
    """Write a re-check queue for ``flight`` to ``out`` and return what was written.

    Draws ``max(minimum, round(fraction * n))`` of the ``n`` human-labelled particles (all of
    them if fewer), in a seeded random order so the draw can be re-derived. The coverage block
    (``_about``) records the seed, the fraction and how many were drawn of how many.
    """
    first = human_labels(_load_verdicts(Path(decoded_dir), flight))
    pool = sorted(first, key=int)
    k = min(len(pool), max(minimum, round(fraction * len(pool))))
    drawn = random.Random(seed).sample(pool, k) if pool else []
    name = f"{RECHECK_PREFIX}{flight}-seed{seed}"[:64]
    data = {
        name: [{"flight": flight, "particle_index": int(i), "note": "re-check"} for i in drawn],
        "_about": {"what": "re-check of human-labelled particles (review_agreement)",
                   "flight": flight, "seed": seed, "fraction": fraction,
                   "drawn": k, "of_human_labelled": len(pool)},
    }
    Path(out).write_text(json.dumps(data, indent=1), encoding="utf-8")
    return data


def agreement(decoded_dir: Path, flight: str) -> Agreement:
    """Kappa between each re-checked particle's first human label and its re-check label."""
    first = human_labels(_load_verdicts(Path(decoded_dir), flight))
    second = human_labels(_load_verdicts(Path(decoded_dir), flight, recheck=True))
    common = sorted(set(first) & set(second), key=int)
    return cohen_kappa([first[i] for i in common], [second[i] for i in common])


def reviewer_labels(verdicts: dict, reviewer: str) -> dict[str, str]:
    """``particle_index -> verdict`` for the human labels ``reviewer`` made.

    Reads the current record and its ``history`` (where a superseded label moves, so a second
    reviewer's click never erases the first's): for each particle, the latest label stored
    under ``reviewer``. Records saved without a ``reviewer`` field match no reviewer.
    """
    out: dict[str, str] = {}
    for k, v in verdicts.items():
        if not isinstance(v, dict):
            continue
        entries = [*v.get("history", []), {x: y for x, y in v.items() if x != "history"}]
        for e in entries:  # oldest first, so a later label by the same reviewer wins
            if (isinstance(e, dict) and e.get("reviewer") == reviewer
                    and e.get("source") == "human" and "verdict" in e):
                out[k] = e["verdict"]
    return out


def reviewer_agreement(first: dict, second: dict, reviewer_a: str,
                       reviewer_b: str) -> Agreement:
    """Kappa between ``reviewer_a``'s labels in ``first`` and ``reviewer_b``'s in ``second``.

    ``first`` and ``second`` are loaded verdict sidecars (``_load_verdicts`` or the parsed
    JSON); pass the same one twice when both reviewers labelled into one store. Only the
    particles both reviewers labelled are paired.
    """
    a = reviewer_labels(first, reviewer_a)
    b = reviewer_labels(second, reviewer_b)
    common = sorted(set(a) & set(b), key=int)
    return cohen_kappa([a[i] for i in common], [b[i] for i in common])

"""Pre-committed relabel-sample selection rule (#98, DA2/#51, spec §6).

**The rule is committed now; the membership is computed later.** Per DA2
(``BUILD/DECISIONS.md``): the manifest states, before labelling begins, that
the relabel sample is the lowest 10% of labelled leaves by
``sha256(relabel_salt || question_id)``, drawn **per stratum** so the
agreement figure is not computed entirely on one corner of the corpus.
Membership cannot be known during labelling — the ranking needs the full
set of labelled leaves, which does not exist until #47 completes — and
fixing membership up front was rejected because it would let a labeller
game the known-watched leaves. Committing the *salt* now (see
``eval/relabel_manifest.json``) is what makes the eventual membership
unpredictable in advance while still deterministic and reproducible once
the population exists.

**No number generator, no seeded reordering anywhere in this module** — the
same discipline as DA1's split assignment: membership is a pure function of
``(relabel_salt, question_id)``, never of iteration order or a generated
seed.

**Stratification axis is a single-place parameter.** The 2026-08-25T14:41:54
authorisation resolves a discrepancy between two authorising records (DA2 /
the 2026-08-19T01:05 item wanted the full 3-axis DA1 stratum — syllabus code
x parse path x tariff band — while the later item specifies DA1 mark band
only, 1 / 2 / 3+). This module implements mark-band-only
(:func:`_stratum_by_mark_band`, the default ``stratify_by``), with the axis
passed as an explicit parameter so switching to the full 3-axis stratum
later is a one-line change at the call site, not a rewrite of the selection
logic.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from collections.abc import Callable


class LeafForSampling(TypedDict):
    """The minimal per-leaf shape :func:`select_relabel_sample` needs.

    ``mark_band`` is DA1's mark-band stratum value: ``"1"``, ``"2"``, or
    ``"3+"``.
    """

    question_id: str
    mark_band: str


def _stratum_by_mark_band(leaf: LeafForSampling) -> str:
    """Default stratification axis (the 2026-08-25T14:41:54 authorisation).

    The single place to change if/when the full 3-axis DA1 stratum
    (syllabus code x parse path x tariff band) replaces mark-band-only —
    pass a different ``stratify_by`` callable to
    :func:`select_relabel_sample` rather than editing its body.
    """
    return leaf["mark_band"]


def _rank_key(relabel_salt: str, question_id: str) -> str:
    """``sha256(relabel_salt || question_id)`` as a deterministic sort key."""
    digest = hashlib.sha256(f"{relabel_salt}{question_id}".encode())
    return digest.hexdigest()


def select_relabel_sample(
    leaves: list[LeafForSampling],
    *,
    relabel_salt: str,
    stratify_by: Callable[[LeafForSampling], str] = _stratum_by_mark_band,
    fraction: float = 0.10,
) -> set[str]:
    """Select the lowest ``fraction`` of ``leaves`` by salted hash, per stratum.

    Deterministic and pure: no number generator anywhere in this function.
    Ranking within a stratum is by ``sha256(relabel_salt || question_id)``
    (:func:`_rank_key`), which is order-independent — the result does not
    depend on the order ``leaves`` was supplied in (unlike a first-N-in-
    input-order selection, which would silently depend on iteration order).

    Selection is **proportional within stratum**: each stratum contributes
    ``round(len(stratum) * fraction)`` of its own leaves, so a small stratum
    is never starved to fill a large one's quota (and vice versa).
    """
    strata: dict[str, list[LeafForSampling]] = {}
    for leaf in leaves:
        strata.setdefault(stratify_by(leaf), []).append(leaf)

    selected: set[str] = set()
    for stratum_leaves in strata.values():
        ranked = sorted(
            stratum_leaves,
            key=lambda leaf: _rank_key(relabel_salt, leaf["question_id"]),
        )
        quota = round(len(ranked) * fraction)
        for leaf in ranked[:quota]:
            selected.add(leaf["question_id"])
    return selected

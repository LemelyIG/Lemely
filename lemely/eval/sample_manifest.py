"""Pre-committed relabel-sample selection rule (#98, DA2/#51, spec §6).

**The rule is committed now; the membership is computed later.** Per DA2
(``BUILD/DECISIONS.md``): the manifest states, before labelling begins, that
the relabel sample is the lowest 10% of labelled leaves by
``sha256(relabel_salt || paper_id || question_id)``, drawn **per stratum** so
the agreement figure is not computed entirely on one corner of the corpus.
(DA2 writes that hash over ``question_id`` alone; see :func:`_rank_key` for
why the full leaf identity is hashed instead, and note that nothing has been
sampled under either formula.)
Membership cannot be known during labelling — the ranking needs the full
set of labelled leaves, which does not exist until #47 completes — and
fixing membership up front was rejected because it would let a labeller
game the known-watched leaves.

**What the committed salt does and does not buy, stated precisely.** The
salt is committed in cleartext in ``eval/relabel_manifest.json``, so it is
*not* a secret and does not hide anything from a labeller who reads the
repo. Its job is the opposite one: it makes the selection **auditable and
un-gameable by the analyst**, because the rank is fixed in public before any
leaf exists, so nobody can mint a salt at analysis time that happens to
select a flattering sample. What keeps membership unknown *to a labeller
during labelling* is not secrecy but the population — ranking requires the
complete set of labelled leaves, which does not exist until #47 completes.
Once it does, anyone can recompute the same membership from public inputs.

**No number generator, no seeded reordering anywhere in this module** — the
same discipline as DA1's split assignment: membership is a pure function of
``(relabel_salt, paper_id, question_id)``, never of iteration order or a
generated seed.

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
import math
from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from collections.abc import Callable


class LeafForSampling(TypedDict):
    """The minimal per-leaf shape :func:`select_relabel_sample` needs.

    ``mark_band`` is DA1's mark-band stratum value: ``"1"``, ``"2"``, or
    ``"3+"``.

    ``paper_id`` is **not optional decoration**: a leaf is identified by
    ``(paper_id, question_id)`` throughout this programme (DA6, and
    ``lemely.eval.analyses._group_by_leaf``). Question ids like ``"1a"``
    recur in every paper, so keying a sample on ``question_id`` alone would
    silently merge one leaf per paper into a single selection unit — the
    narrowed-denominator failure mode D18 exists to prevent.
    """

    paper_id: str
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


def _rank_key(relabel_salt: str, paper_id: str, question_id: str) -> str:
    """``sha256(relabel_salt || paper_id || question_id)`` as a sort key.

    **Deviation from DA2's literal formula, recorded rather than hidden.**
    DA2 writes the rank as ``sha256(relabel_salt || question_id)``. That
    formula silently assumes ``question_id`` identifies a leaf; it does not
    — leaf identity is ``(paper_id, question_id)`` (DA6). Under the literal
    formula, ``1a`` in every paper of a stratum would receive the *same*
    rank and enter or leave the sample as a block, which is neither a 10%
    sample nor a per-leaf one. The full leaf identity is hashed instead.

    Components are joined with a NUL byte, which cannot occur in a validated
    identifier (``lemely.labelling.paths._IDENTIFIER_PATTERN``), so no pair
    of distinct ``(paper_id, question_id)`` leaves can collide by
    concatenation (``"ab" + "c"`` vs ``"a" + "bc"``).

    Nothing has been sampled under either formula — #47 has not completed —
    so this changes no committed membership.
    """
    digest = hashlib.sha256(f"{relabel_salt}\x00{paper_id}\x00{question_id}".encode())
    return digest.hexdigest()


def select_relabel_sample(
    leaves: list[LeafForSampling],
    *,
    relabel_salt: str,
    stratify_by: Callable[[LeafForSampling], str] = _stratum_by_mark_band,
    fraction: float = 0.10,
) -> set[tuple[str, str]]:
    """Select the lowest ``fraction`` of ``leaves`` by salted hash, per stratum.

    Returns a set of ``(paper_id, question_id)`` pairs — the programme's leaf
    identity (DA6), never bare question ids, which are not unique across
    papers.

    Deterministic and pure: no number generator anywhere in this function.
    Ranking within a stratum is by
    ``sha256(relabel_salt || paper_id || question_id)`` (:func:`_rank_key`),
    which is order-independent — the result does not depend on the order
    ``leaves`` was supplied in (unlike a first-N-in-input-order selection,
    which would silently depend on iteration order).

    Selection is **proportional within stratum**: each stratum contributes
    ``ceil(len(stratum) * fraction)`` of its own leaves, so a small stratum
    is never starved to fill a large one's quota (and vice versa). ``ceil``
    rather than ``round`` is deliberate and load-bearing: at ``fraction=0.1``
    a stratum of 4 rounds to **zero**, which would drop that stratum out of
    the agreement figure entirely while the docstring claimed it was never
    starved. Rounding up costs at most one extra leaf per stratum and keeps
    every non-empty stratum represented.

    ``fraction`` must lie in ``(0, 1]``. A negative value is rejected rather
    than applied: ``ceil(40 * -0.1)`` is ``-4``, and ``ranked[:-4]`` is a
    *slice from the end* that would quietly select 36 of 40 leaves — a
    typo'd sign turning a 10% sample into a 90% one with no error anywhere.
    """
    if not 0 < fraction <= 1:
        raise ValueError(f"fraction must be in (0, 1], got {fraction!r}")

    strata: dict[str, list[LeafForSampling]] = {}
    for leaf in leaves:
        strata.setdefault(stratify_by(leaf), []).append(leaf)

    selected: set[tuple[str, str]] = set()
    for stratum_leaves in strata.values():
        ranked = sorted(
            stratum_leaves,
            key=lambda leaf: _rank_key(relabel_salt, leaf["paper_id"], leaf["question_id"]),
        )
        quota = math.ceil(len(ranked) * fraction)
        for leaf in ranked[:quota]:
            selected.add((leaf["paper_id"], leaf["question_id"]))
    return selected

"""M0.9 (#33): the review-rate two-part ratchet CI gate (spec §4 M0.9, §5).

Pure — no I/O, no network, no filesystem — matching the M0.1 "pure analyses"
contract :mod:`lemely.eval.analyses` establishes. :func:`evaluate_review_rate_gate`
takes an already-computed :class:`~lemely.eval.analyses.ReviewRateResult` (itself
computed by :func:`lemely.eval.analyses.review_rate` over question-level,
distinct-leaf ``EvalRecord`` rows drawn **only** from a dev-split run — see that
function's docstring) and decides whether the run passes four independent limbs:

1. ``review_rate_signal <= review_rate_signal_target`` (default 8%).
2. ``review_rate_total <= review_rate_total_target`` (default 10%).
3. ``per_paper_p95 <= review_rate_p95_target`` (default 15%).
4. The ratchet: ``review_rate_total <= min(review_rate_total_target,
   last_merged_review_rate)`` — this can be *stricter* than limb 2 whenever the
   last merged run's rate was already below the 10% absolute cap, which is the
   point of a ratchet (spec §5): it can only tighten, never loosen.

A fifth check enforces spec §5/§7's stated invariant that ``review_rate_total ==
review_rate_signal`` until the ``random_audit`` trigger (M4/T1.10) exists — see
:func:`lemely.eval.analyses.review_rate`'s docstring. This is enforced here, not
left as a comment, so a hand-built or future-drifted ``ReviewRateResult`` cannot
silently carry ``total > signal`` headroom the programme has not earned yet.

``armed`` controls whether a breach is *blocking*. At M0 (``armed=False``) a
breach on any limb is recorded in ``breaches`` but ``blocking_failure`` stays
``False`` — the run is observed, not gated. Once M1 acceptance arms the ratchet
(``armed=True``), the identical breach makes ``blocking_failure`` ``True``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from lemely.eval.analyses import ReviewRateResult

DEFAULT_SIGNAL_TARGET = 0.08
DEFAULT_TOTAL_TARGET = 0.10
DEFAULT_P95_TARGET = 0.15


class ReviewRateGateResult(TypedDict):
    """Per-limb pass/fail plus the overall verdict for one gate evaluation."""

    signal_ok: bool
    total_ok: bool
    p95_ok: bool
    ratchet_ok: bool
    ratchet_ceiling: float
    invariant_ok: bool
    breaches: list[str]
    armed: bool
    blocking_failure: bool


def evaluate_review_rate_gate(
    rate: ReviewRateResult,
    *,
    last_merged_review_rate: float,
    armed: bool,
    signal_target: float = DEFAULT_SIGNAL_TARGET,
    total_target: float = DEFAULT_TOTAL_TARGET,
    p95_target: float = DEFAULT_P95_TARGET,
) -> ReviewRateGateResult:
    """Evaluate the M0.9 review-rate gate's four limbs against ``rate``.

    ``rate`` must already be computed over a dev-split run's question-level,
    distinct-leaf records (spec §5) — this function does not know or check
    where ``rate`` came from; that restriction is the caller's responsibility
    (see :func:`lemely.eval.analyses.review_rate`'s docstring and the CLI/CI
    callers of this function).
    """
    signal_ok = rate["review_rate_signal"] <= signal_target
    total_ok = rate["review_rate_total"] <= total_target
    p95_ok = rate["per_paper_p95"] <= p95_target
    ratchet_ceiling = min(total_target, last_merged_review_rate)
    ratchet_ok = rate["review_rate_total"] <= ratchet_ceiling
    invariant_ok = rate["review_rate_total"] == rate["review_rate_signal"]

    breaches: list[str] = []
    if not signal_ok:
        breaches.append(
            f"review_rate_signal {rate['review_rate_signal']:.4f} > target {signal_target:.4f}"
        )
    if not total_ok:
        breaches.append(
            f"review_rate_total {rate['review_rate_total']:.4f} > target {total_target:.4f}"
        )
    if not p95_ok:
        breaches.append(f"per_paper_p95 {rate['per_paper_p95']:.4f} > target {p95_target:.4f}")
    if not ratchet_ok:
        breaches.append(
            f"review_rate_total {rate['review_rate_total']:.4f} > "
            f"ratchet ceiling {ratchet_ceiling:.4f} "
            f"(min(total_target={total_target:.4f}, "
            f"last_merged_review_rate={last_merged_review_rate:.4f}))"
        )
    if not invariant_ok:
        breaches.append(
            f"review_rate_total {rate['review_rate_total']:.4f} != "
            f"review_rate_signal {rate['review_rate_signal']:.4f} — these must be "
            "equal until the random_audit trigger (M4/T1.10) exists (spec §5/§7)"
        )

    all_ok = signal_ok and total_ok and p95_ok and ratchet_ok and invariant_ok
    blocking_failure = armed and not all_ok

    return {
        "signal_ok": signal_ok,
        "total_ok": total_ok,
        "p95_ok": p95_ok,
        "ratchet_ok": ratchet_ok,
        "ratchet_ceiling": ratchet_ceiling,
        "invariant_ok": invariant_ok,
        "breaches": breaches,
        "armed": armed,
        "blocking_failure": blocking_failure,
    }

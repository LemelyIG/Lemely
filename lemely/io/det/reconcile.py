"""Mark-total reconciliation: compare leaf-mark sum to metadata.maximum_mark.

When the deterministic parser produces a result whose leaf-mark total does not
match the paper's stated maximum mark, that is a strong signal that something
went wrong (wrong column detected, phantom questions, marks defaulted, etc.).

The reconciler raises ``ParseError`` so the ``ChainedMarkSchemeParser`` can
route the paper to Gemini instead of writing a silently-wrong JSON output.

Both triggers are configurable through ``DetParserSettings``:
- ``escalate_on_mark_mismatch`` (default True) + ``mark_reconcile_tolerance`` (default 0)
- ``escalate_on_defaulted_marks`` (default True)

Passing ``escalate_on_mark_mismatch=False`` turns the reconciler into a
warning-only reporter (useful during development / debugging).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from lemely.runtime.errors import ParseError

if TYPE_CHECKING:
    from lemely.core.loose_schemas import MarkSchemeMetadata, Question

log = structlog.get_logger(__name__)


def _leaf_ids(questions: list[Question]) -> list[str]:
    """Every leaf question's id, in document order, WITH duplicates kept."""
    out: list[str] = []
    for q in questions:
        if q.parts:
            out.extend(_leaf_ids(q.parts))
        else:
            out.append(q.id)
    return out


def _leaf_marks(questions: list[Question]) -> int:
    """Recursively sum marks for all leaf questions (those with no sub-parts)."""
    total = 0
    for q in questions:
        if q.parts:
            total += _leaf_marks(q.parts)
        else:
            total += q.marks
    return total


def check(
    questions: list[Question],
    metadata: MarkSchemeMetadata,
    escalate_on_mark_mismatch: bool = True,
    mark_reconcile_tolerance: int = 0,
    escalate_on_defaulted_marks: bool = True,
    escalate_on_duplicate_leaf_ids: bool = False,
    source: str = "",
) -> None:
    """Self-check the parsed questions against the paper's stated maximum mark.

    Args:
        questions: Top-level question list from the state machine.
        metadata: Parsed metadata (provides ``maximum_mark``).
        escalate_on_mark_mismatch: Whether to raise ``ParseError`` on a mark
            total mismatch that exceeds the tolerance.
        mark_reconcile_tolerance: Allowed absolute deviation between the parsed
            leaf-mark total and ``metadata.maximum_mark``.  Defaults to 0 (strict).
        escalate_on_defaulted_marks: Whether to raise ``ParseError`` when any
            leaf question has marks derived from the 1-mark default (i.e. the
            marks cell was unparseable).

            **STILL NOT ARMED, and #38 (M1.3) deliberately did not arm it.**
            The hook was written on the assumption that defaulting is rare and
            therefore a good escalation signal. Measurement falsifies that: over
            a 60-PDF random sample (54 parsed), **44.4% of papers carry at least
            one defaulted point and 21.6% of all answer points are defaulted**
            (`marks_defaulted`, added by #38). Arming this as written would
            route nearly half the det-parsed corpus to the paid Gemini path.

            The cause is DA21 mechanism (B): where the marks column merges into
            the answer cell, the code arrives as trailing text and every point
            defaults. The default is right *by luck* for B1/M1/A1/C1, so most of
            those 21.6% are correct — which is exactly why "defaulted" is not by
            itself evidence of an error, and why a bare count is the wrong
            trigger. Whether to arm it, and on what predicate, is a cost and
            coverage decision escalated on #38 rather than chosen here.
        escalate_on_duplicate_leaf_ids: Whether to raise ``ParseError`` when two
            leaf questions in the same paper share an id.

            **Defaults to False — reported, not blocking — and that is a
            deliberate choice, not an oversight.** Leaf identity is
            ``(paper_id, question_id)`` (DA6), so duplicates COLLAPSE two
            different questions into one leaf and silently narrow every
            downstream denominator. That is the D18 shape #105 fixed at the
            analysis layer, except it originates here, so no amount of correct
            keying downstream repairs it.

            It is also **orthogonal to the mark total**: measured over 477
            parsed source schemes, **14 of the 333 that reconcile with their
            printed maximum exactly still carry duplicates**, so
            ``escalate_on_mark_mismatch`` cannot see it.

            Arming it routes the paper to the Gemini fallback — which #166
            measured **failing on roughly half** the schemes det cannot parse,
            and on 100% of 0606. So arming trades a silently-wrong paper for a
            probably-absent one: a cost AND coverage decision, on the same
            footing as ``escalate_on_defaulted_marks`` above, and not one to
            take as a tidy-up.
        source: Human-readable label for log messages (e.g. the PDF filename).
    """
    ids = _leaf_ids(questions)
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        dup_ctx = {
            "source": source or metadata.source_document or "?",
            "duplicate_ids": duplicates,
            "leaves": len(ids),
            "leaves_lost_to_collapse": len(ids) - len(set(ids)),
        }
        dup_msg = (
            f"Duplicate leaf question ids in {dup_ctx['source']}: "
            f"{', '.join(duplicates)} — {dup_ctx['leaves_lost_to_collapse']} of "
            f"{len(ids)} leaves collapse under (paper_id, question_id) identity"
        )
        if escalate_on_duplicate_leaf_ids:
            log.warning("duplicate_leaf_ids_escalating", **dup_ctx)
            raise ParseError(dup_msg)
        log.warning("duplicate_leaf_ids", **dup_ctx)

    maximum_mark = metadata.maximum_mark
    computed = _leaf_marks(questions)
    discrepancy = abs(computed - maximum_mark)

    log_ctx = {
        "source": source or metadata.source_document or "?",
        "computed_total": computed,
        "maximum_mark": maximum_mark,
        "discrepancy": discrepancy,
        "tolerance": mark_reconcile_tolerance,
    }

    if discrepancy == 0:
        log.debug("mark_total_ok", **log_ctx)
        return

    if discrepancy <= mark_reconcile_tolerance:
        log.info("mark_total_within_tolerance", **log_ctx)
        return

    # Discrepancy exceeds tolerance
    msg = (
        f"Mark total mismatch for {log_ctx['source']}: "
        f"parsed {computed}, expected {maximum_mark} "
        f"(discrepancy {discrepancy} > tolerance {mark_reconcile_tolerance})"
    )

    if escalate_on_mark_mismatch:
        log.warning("mark_total_mismatch_escalating", **log_ctx)
        raise ParseError(msg)
    else:
        log.warning("mark_total_mismatch_warning", **log_ctx)

"""Which review reasons say the transcription itself is in doubt.

A question flagged because its answer may belong to another question, or was
never read, carries a ``review_reason`` segment starting with
:data:`BINDING_REVIEW_PREFIX`. The writers of those segments live in
``lemely.io.correction_ai``; the rule that reads them lives in
``lemely.db.attempt_repo.grants_self_mark_authority``. This module is the one
place the prefix is spelled, so the two cannot drift apart
(``tests/test_binding_review.py`` checks every writer's constant against it).

WARNING: any new binding reason must start with :data:`BINDING_REVIEW_PREFIX`, or
the question it is written on silently regains self-mark authority and lets a
student's own claim close the teacher's row. The constants test
(``tests/test_binding_review.py``) covers only the reasons that exist today.

Pure: no imports from ``lemely.io`` or ``lemely.db``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lemely.core.binding import BindingReport

BINDING_REVIEW_PREFIX = "binding unverified:"

#: ``apply_integrity_checks`` and ``correction_ai._join_reason`` join segments with this.
_REASON_SEPARATOR = " | "


def has_binding_doubt(review_reason: str | None) -> bool:
    """Whether any ``" | "``-joined segment of ``review_reason`` starts with the prefix."""
    if not review_reason:
        return False
    return any(
        segment.startswith(BINDING_REVIEW_PREFIX)
        for segment in review_reason.split(_REASON_SEPARATOR)
    )


def is_unbound_question(review_reason: str | None, student_answer: str | None) -> bool:
    """Whether a binding-doubt question has no transcription to judge.

    An unbound question is one no answer was ever read for: no marking call, so
    ``student_answer`` is empty. A lenient judge would see only the mark-scheme
    point and the student's own description of their answer, so the claim is
    decided by a teacher, never the judge. An unverified answer, which does have
    a transcription, takes the ordinary evidence-and-judge route.
    """
    return has_binding_doubt(review_reason) and not (student_answer or "").strip()


def binding_blocks_publication(report: BindingReport | None) -> bool:
    """Whether a binding report forbids publishing the paper.

    ``None`` means no verdict exists (not a scan, or the gate is off or only
    observing), which never blocks. Any verdict but ``pass`` blocks, and
    ``retry`` after marking is treated like ``hold`` because there is no retry
    left at that point. The one rule: the web jobs, the Gradio app and the CLI
    all call it.
    """
    return report is not None and report.verdict != "pass"


__all__ = [
    "BINDING_REVIEW_PREFIX",
    "binding_blocks_publication",
    "has_binding_doubt",
    "is_unbound_question",
]

"""Which review reasons say the transcription itself is in doubt.

A question flagged because its answer may belong to another question, or was
never read, carries a ``review_reason`` segment starting with
:data:`BINDING_REVIEW_PREFIX`. The writers of those segments live in
``lemely.io.correction_ai``; the rule that reads them lives in
``lemely.db.attempt_repo.grants_self_mark_authority``. This module is the one
place the prefix is spelled, so the two cannot drift apart
(``tests/test_binding_review.py`` checks every writer's constant against it).

Pure: no imports from ``lemely.io`` or ``lemely.db``.
"""

from __future__ import annotations

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


__all__ = ["BINDING_REVIEW_PREFIX", "has_binding_doubt"]

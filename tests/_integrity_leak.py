"""Shared detectors for integrity-language leaks onto a student-facing surface.

QUALITY-BAR.md: integrity flags (``plagiarism_flagged``, ``ai_detection_flagged``,
and the integrity segments of ``review_reason``) are teacher-only. Task 8 (the
deletion routes) and Task 9 (teacher-facing copy that must still avoid naming a
*student*-visible reason) both need to prove a response body carries none of
that language — so the detectors live here, shared, rather than copied per test
module, and are applied to the **fully serialised** body, never to one field: a
leak hiding in a nested key would survive a single-field check.

:func:`leaks_integrity` matches the integrity vocabulary alone (segment
prefixes plus a few free-text words). :func:`leaks_to_student` adds "review" —
appropriate only on a route that must never mention a review at all, such as
the student deletion routes' 409, where naming "review" would itself concede
the paper was flagged.
"""

from __future__ import annotations

import json

from lemely.web.schemas import _INTEGRITY_REASON_PREFIXES

_INTEGRITY_WORDS = (
    *_INTEGRITY_REASON_PREFIXES,
    "integrity",
    "flag",
    "cheat",
    "similar",
    "score",
)


def _serialised(obj: object) -> str:
    return json.dumps(obj).lower()


def leaks_integrity(obj: object) -> bool:
    """Whether the serialised ``obj`` contains any integrity-related word."""
    text = _serialised(obj)
    return any(word in text for word in _INTEGRITY_WORDS)


def leaks_to_student(obj: object) -> bool:
    """Whether ``obj`` leaks integrity language, or even names "review"."""
    return leaks_integrity(obj) or "review" in _serialised(obj)


__all__ = ["leaks_integrity", "leaks_to_student"]

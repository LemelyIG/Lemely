"""``GET /api/student/classes`` DTOs (P5.8 chunk C, D5.14 §1).

A pure projection of :class:`~lemely.db.class_repo.StudentClassRow` — nothing
here is computed, aggregated or derived. The route exists because S-29's
``scope=class`` board needs a ``class_id`` and, before this, **no
student-facing route listed a student's own classes**: the only readers of
``ClassService.student_classes`` were the parent portal's P-01 and P-02.

**Answer-only, like every other Phase-5 student surface.** A class carries a
name and a subject; no mark, average, rank or grade field exists on these
models, and ``tests/test_schemas_student_classes.py`` introspects the field
sets so a well-meaning future addition fails a test rather than reaching the
wire (the pattern :mod:`lemely.web.schemas_leaderboard` established under
D5.1 §0).

Mirrors :mod:`lemely.web.schemas_leaderboard`'s style: an explicit
``ApiModel`` subclass per DTO, camelCase names declared directly (no alias
generator).
"""

from __future__ import annotations

from lemely.web.schemas import ApiModel


class StudentClassDTO(ApiModel):
    """One class the caller is enrolled in."""

    classId: str
    name: str
    subjectCode: str | None
    """``None`` for a class its teacher never scoped to a subject — never a
    fabricated placeholder code."""
    schoolName: str | None
    """``None`` for an independent teacher's class, which genuinely has no
    school (``SchoolClass.school_id`` is nullable). Not "unknown"."""


class StudentClassListDTO(ApiModel):
    """``GET /api/student/classes`` response.

    An empty ``classes`` list is an honest, successful answer: a student who
    subscribed directly and joined no teacher's class has none, and that is a
    normal account state rather than an error or a missing prerequisite.
    """

    classes: list[StudentClassDTO]


__all__ = ["StudentClassDTO", "StudentClassListDTO"]

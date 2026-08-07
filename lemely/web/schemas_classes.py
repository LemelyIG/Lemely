"""API DTOs for the class-model endpoints (``/api/classes/*``, D3.1).

Request/response models for class CRUD, roster listing, seat-based enrolment,
and the student-facing join-by-code flow. Field names are camelCase to match
the frontend contract, mirroring the other ``schemas_*.py`` modules.
"""

from __future__ import annotations

from lemely.web.schemas import ApiModel


class CreateClassRequestDTO(ApiModel):
    """Create a class owned by the authenticated teacher.

    ``schoolId`` is optional (an independent teacher passes none, per D3.1);
    when supplied the caller must hold a membership in that school.
    """

    name: str
    subjectCode: str | None = None
    schoolId: str | None = None


class UpdateClassRequestDTO(ApiModel):
    """Rename a class and/or change its subject code. Both fields optional."""

    name: str | None = None
    subjectCode: str | None = None


class EnrollStudentRequestDTO(ApiModel):
    """Direct-add an existing, seated student onto a class roster."""

    studentId: str


class JoinClassRequestDTO(ApiModel):
    """A student's self-enrolment request, keyed off the class join code."""

    joinCode: str


class JoinClassResponseDTO(ApiModel):
    """The class a student just joined (or was already enrolled in)."""

    classId: str
    className: str


class RosterEntryDTO(ApiModel):
    """One enrolled student's identity (no analytics — see ``StudentRowDTO``)."""

    studentId: str
    displayName: str


class RosterDTO(ApiModel):
    """Response for ``GET /api/classes/{class_id}/roster``."""

    students: list[RosterEntryDTO]


__all__ = [
    "CreateClassRequestDTO",
    "EnrollStudentRequestDTO",
    "JoinClassRequestDTO",
    "JoinClassResponseDTO",
    "RosterDTO",
    "RosterEntryDTO",
    "UpdateClassRequestDTO",
]

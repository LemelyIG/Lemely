"""API DTOs for the teacher announcement composer (``/api/teacher/announcements/*``).

T-12's backend prerequisite (P3.8 chunk a, D3.14). Field names are camelCase
to match the frontend contract, mirroring the other ``schemas_*.py`` modules.
Converters live in :mod:`lemely.web.routers.announcements`.

**No attachment field, anywhere in this module — deliberately (D3.14 §2).**
``announcements`` has no attachment column and no storage wiring for
anything but student paper uploads; the UI spec's "optional attachment" is
omitted entirely rather than shipped as a disabled control. Do not add one,
not even nullable.

**``publishAt`` is stored, not consumed.** See
``lemely.db.announcement_repo``'s module docstring — nothing in this
codebase reads this column back to decide when to deliver anything yet;
delivery is Phase 5's.
"""

from __future__ import annotations

from pydantic import Field

from lemely.web.schemas import ApiModel


class AnnouncementCreateRequestDTO(ApiModel):
    """Body for ``POST /api/teacher/announcements``.

    ``classIds`` fans out to one row per class (D3.14 §3: "one row per
    selected class, all written in one request and reported back as a
    group"). ``schoolWide`` instead creates a single row with ``schoolId``
    set and no class — restricted to ``school_admin`` (a teacher requesting
    it gets a 403).

    **Exactly one of ``classIds``/``schoolWide`` must be given** — neither is
    a 422, and so is *both*, because the two audiences overlap and a combined
    request would deliver twice to a student enrolled in a class of that
    school. See ``lemely.db.announcement_repo``'s module docstring; the rule
    is enforced in the service, so this DTO does not restate it as a
    validator. ``schoolId`` is required whenever ``schoolWide`` is ``true``.
    ``publishAt`` is an optional ISO 8601 timestamp; omitted (or ``null``)
    means "publish immediately".
    """

    title: str
    body: str
    classIds: list[str] = Field(default_factory=list)
    schoolWide: bool = False
    schoolId: str | None = None
    publishAt: str | None = None


class AnnouncementDTO(ApiModel):
    """One announcement row, exactly as stored — no derived/enriched fields."""

    announcementId: str
    authorId: str
    schoolId: str | None
    classId: str | None
    title: str
    body: str
    publishAt: str | None
    createdAt: str


class AnnouncementCreateResponseDTO(ApiModel):
    """Response for ``POST /api/teacher/announcements`` — every row the fan-out created."""

    announcements: list[AnnouncementDTO] = Field(default_factory=list)


class AnnouncementListDTO(ApiModel):
    """Response for ``GET /api/teacher/announcements``."""

    announcements: list[AnnouncementDTO] = Field(default_factory=list)


__all__ = [
    "AnnouncementCreateRequestDTO",
    "AnnouncementCreateResponseDTO",
    "AnnouncementDTO",
    "AnnouncementListDTO",
]

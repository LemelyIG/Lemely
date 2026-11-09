"""DTOs for the landing-page waitlist: the public two-step flow and the admin queue.

Public wire contract (camelCase, like the other portals): ``POST /api/waitlist`` (step 1)
and ``PATCH /api/waitlist`` (step 2). Every value is validated here against the vocabularies
in :mod:`lemely.core.waitlist`, so the repository only ever stores known values. ``website``
is the honeypot: a human never sees or fills it.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID  # noqa: TC003 - pydantic resolves the annotation at runtime

from pydantic import (
    AfterValidator,
    BeforeValidator,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

from lemely.core.waitlist import (
    ALL_SUBJECTS,
    CONSENT_VERSIONS,
    MAX_NAME_LENGTH,
    MAX_OTHER_SUBJECT_LENGTH,
    MAX_OTHER_SUBJECTS,
    clean_name,
    is_valid_exam_session,
    normalise_email,
    normalise_phone,
)
from lemely.web.schemas import ApiModel

# Same shape check as ``schemas_contact``: not deliverability, just no whitespace, brackets,
# quotes, commas or semicolons around one ``@`` and a dotted domain.
_EMAIL_PATTERN = r"^[^@\s<>\",;]+@[^@\s<>\",;]+\.[^@\s<>\",;]+$"
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")

RoleLit = Literal["student", "teacher", "parent", "centre_admin"]
LevelLit = Literal["o_level", "as_level", "a_level"]
BoardLit = Literal["caie", "edexcel", "oxford_aqa", "other"]
StatusLit = Literal["new", "contacted", "invited", "declined"]
StatusFilterLit = Literal["new", "contacted", "invited", "declined", "partial"]
SortLit = Literal["created_at", "email", "name", "role", "status", "exam_session"]


def _clean(value: object) -> object:
    """Strip a string and drop control characters; blank becomes ``None``."""
    if not isinstance(value, str):
        return value
    cleaned = _CONTROL_CHARS.sub(" ", value).strip()
    return cleaned or None


def _strip(value: object) -> object:
    return value.strip() if isinstance(value, str) else value


def _lower_email(value: str) -> str:
    return normalise_email(value)


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _known_subject(values: list[str]) -> list[str]:
    unknown = [v for v in values if v not in ALL_SUBJECTS]
    if unknown:
        raise ValueError(f"Pick subjects from the list ({unknown[0]!r} is not one).")
    return values


PHONE_MESSAGE = "Enter a mobile number: Egypt numbers start 01, or add a + and the country code."


def _e164(value: str | None) -> str | None:
    if value is None:
        return None
    number = normalise_phone(value)
    if number is None:
        raise ValueError(PHONE_MESSAGE)
    return number


def _name(value: str) -> str:
    return clean_name(value)


# ``max_length`` here is a cheap guard against huge bodies; the real 1-100 rule runs on the
# trimmed, whitespace-collapsed text in ``clean_name`` (so padding never counts).
PersonName = Annotated[str, Field(max_length=MAX_NAME_LENGTH * 4), AfterValidator(_name)]
Email = Annotated[
    str,
    BeforeValidator(_strip),
    Field(min_length=3, max_length=254, pattern=_EMAIL_PATTERN),
    AfterValidator(_lower_email),
]
# ``Field(max_length=...)`` sits on the ``str`` branch: put on the optional as a whole it would
# be applied to an explicit JSON ``null`` and crash instead of validating.
ShortText = Annotated[Annotated[str, Field(max_length=100)] | None, BeforeValidator(_clean)]
Levels = Annotated[
    list[LevelLit], Field(default_factory=list, max_length=3), AfterValidator(_dedupe)
]
Boards = Annotated[
    list[BoardLit], Field(default_factory=list, max_length=4), AfterValidator(_dedupe)
]
Subjects = Annotated[
    list[str],
    Field(default_factory=list, max_length=len(ALL_SUBJECTS), validate_default=True),
    AfterValidator(_dedupe),
    AfterValidator(_known_subject),
]


def _clean_list(value: object) -> object:
    """Clean each free-text entry and drop blanks (an over-long list is left for the cap)."""
    if not isinstance(value, list):
        return value
    cleaned = (_clean(v) for v in value)
    return [v for v in cleaned if v is not None]


def _dedupe_casefold(values: list[str]) -> list[str]:
    seen: dict[str, str] = {}
    for v in values:
        seen.setdefault(v.casefold(), v)
    return list(seen.values())


OtherSubjects = Annotated[
    list[Annotated[str, Field(max_length=MAX_OTHER_SUBJECT_LENGTH)]],
    BeforeValidator(_clean_list),
    Field(default_factory=list, max_length=MAX_OTHER_SUBJECTS, validate_default=True),
    AfterValidator(_dedupe_casefold),
]


def _clean_note(value: object) -> object:
    """An admin note keeps its line breaks (CRLF and CR become LF); other control characters go."""
    if not isinstance(value, str):
        return value
    text = value.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[\x00-\x09\x0b-\x1f\x7f]", " ", text).strip()
    return text or None


Honeypot = Annotated[Annotated[str, Field(max_length=200)] | None, BeforeValidator(_clean)]


class WaitlistCreateDTO(ApiModel):
    """Step 1: email, name, role, consent wording and the arrival's UTM tags."""

    email: Email
    name: PersonName
    role: RoleLit
    consentVersion: Annotated[str, Field(min_length=1, max_length=40)]
    utmSource: ShortText = None
    utmMedium: ShortText = None
    utmCampaign: ShortText = None
    utmContent: ShortText = None
    utmTerm: ShortText = None
    turnstileToken: Annotated[str | None, Field(default=None, max_length=2048)] = None
    website: Honeypot = None

    @field_validator("consentVersion")
    @classmethod
    def _known_consent_version(cls, value: str) -> str:
        if value not in CONSENT_VERSIONS:
            raise ValueError("Unknown consent version; reload the page.")
        return value


class WaitlistCreatedDTO(ApiModel):
    """Step 1 answer. ``token`` is present only for a newly created applicant."""

    status: Literal["created", "already_listed"]
    token: str | None = None


class WaitlistCompleteDTO(ApiModel):
    """Step 2: the optional detail, redeemed with the step-1 token."""

    token: Annotated[str, Field(min_length=20, max_length=200)]
    levels: Levels
    # ``otherSubjects`` precedes ``subjects`` so the subjects check can see it.
    otherSubjects: OtherSubjects
    subjects: Subjects
    examBoards: Boards
    examSession: Annotated[Annotated[str, Field(max_length=10)] | None, BeforeValidator(_clean)] = (
        None
    )
    phone: Annotated[
        Annotated[str, Field(max_length=40)] | None, BeforeValidator(_clean), AfterValidator(_e164)
    ] = None
    phoneHasWhatsapp: bool = False
    centreName: Annotated[Annotated[str, Field(max_length=120)] | None, BeforeValidator(_clean)] = (
        None
    )
    website: Honeypot = None

    @field_validator("subjects")
    @classmethod
    def _at_least_one_subject(cls, value: list[str], info: ValidationInfo) -> list[str]:
        other = info.data.get("otherSubjects")
        if not value and other is not None and not other:
            raise ValueError("Pick at least one subject, or add one under other subjects.")
        return value

    @field_validator("examSession")
    @classmethod
    def _upcoming_session(cls, value: str | None) -> str | None:
        if value is not None and not is_valid_exam_session(value, datetime.now(UTC).date()):
            raise ValueError("Pick one of the offered exam sessions.")
        return value


class WaitlistCompletedDTO(ApiModel):
    """Step 2 answer."""

    status: Literal["completed"]


class WaitlistApplicantDTO(ApiModel):
    """One applicant, every field. Admin-only: it carries the phone number."""

    id: UUID
    email: str
    name: str | None
    role: RoleLit
    centreName: str | None
    levels: list[str]
    subjects: list[str]
    otherSubjects: list[str]
    examBoards: list[str]
    examSession: str | None
    phone: str | None
    phoneHasWhatsapp: bool
    emailConfirmed: bool
    consentVersion: str
    consentText: str
    consentAt: datetime
    status: StatusLit
    adminNote: str | None
    utmSource: str | None
    utmMedium: str | None
    utmCampaign: str | None
    utmContent: str | None
    utmTerm: str | None
    completedAt: datetime | None
    partial: bool
    createdAt: datetime
    updatedAt: datetime


class WaitlistCountsDTO(ApiModel):
    """Chip counts over the filtered set (without the status filter)."""

    all: int
    new: int
    contacted: int
    invited: int
    declined: int
    partial: int


class WaitlistListDTO(ApiModel):
    """One page of the admin queue."""

    items: list[WaitlistApplicantDTO]
    total: int
    page: int
    pageSize: int
    counts: WaitlistCountsDTO


class WaitlistUpdateDTO(ApiModel):
    """Admin edit: a status change, a note change (``null`` clears it), or both."""

    status: StatusLit | None = None
    adminNote: Annotated[
        Annotated[str, Field(max_length=2000)] | None, BeforeValidator(_clean_note)
    ] = None

    @model_validator(mode="after")
    def _something_to_change(self) -> WaitlistUpdateDTO:
        if self.status is None and "adminNote" not in self.model_fields_set:
            raise ValueError("send status, adminNote or both")
        return self


class WaitlistConfigDTO(ApiModel):
    """Public settings the page needs: Turnstile's site key and the current consent wording."""

    turnstileSiteKey: str | None
    consentVersion: str
    consentText: str


class WaitlistDigestResultDTO(ApiModel):
    """Digest trigger answer: how many new applicants it covered and whether mail went out."""

    newApplicants: int
    sent: bool
    alreadySent: bool = False


__all__ = [
    "BoardLit",
    "LevelLit",
    "RoleLit",
    "SortLit",
    "StatusFilterLit",
    "StatusLit",
    "WaitlistApplicantDTO",
    "WaitlistCompleteDTO",
    "WaitlistCompletedDTO",
    "WaitlistConfigDTO",
    "WaitlistCountsDTO",
    "WaitlistCreateDTO",
    "WaitlistCreatedDTO",
    "WaitlistDigestResultDTO",
    "WaitlistListDTO",
    "WaitlistUpdateDTO",
]

"""API DTOs for the platform-admin console (``/api/admin/*``, UI spec 4.10).

Every field here is a counted fact. Where X-01/X-03 ask for something the system
does not record, the DTO carries an explicit ``None`` or omits the field and says
why in its docstring — it never carries a derived stand-in. That rule matters
more on this surface than anywhere else in the product: the reader is the person
who would act on the number, and nobody downstream re-checks their work.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class ApiModel(BaseModel):
    """Base DTO: forbids extra fields and serialises via camelCase aliases."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class PlatformCountsDTO(ApiModel):
    """Global row counts and the two live operational depths (X-01).

    ``papersMarked*`` counts past-paper attempts only; a quiz submission is also
    an attempt row but is not marking-pipeline throughput.
    """

    students: int
    parents: int
    teachers: int
    schoolAdmins: int
    platformAdmins: int
    schools: int
    classes: int
    papersMarkedTotal: int
    papersMarkedLast24Hours: int
    papersMarkedLast7Days: int
    openReviewItems: int
    uploadsByStatus: dict[str, int]


class SignupDTO(ApiModel):
    """One recently created account, any role (X-01)."""

    userId: str
    email: str
    displayName: str | None = None
    role: str
    createdAt: str


class SystemHealthDTO(ApiModel):
    """What the console can actually assert about the deployment (X-01).

    X-01 asks for "system health". These three are the checks this process can
    make honestly from inside a request: the database answered (it must have, to
    produce the counts beside this), a Gemini key is configured, and the app
    version. There is no uptime, no queue-worker heartbeat and no dependency
    ping, because nothing records them — a green light with no check behind it is
    worse than no light.
    """

    databaseReachable: bool
    geminiKeyConfigured: bool
    version: str


class PlatformOverviewDTO(ApiModel):
    """X-01 in one response.

    Carries no spend figure (DS3): the web process keeps no cost ledger to read
    one from, and the guard on Gemini spend is a Google Cloud billing budget on
    the deployed service, not this API.
    """

    counts: PlatformCountsDTO
    health: SystemHealthDTO
    recentSignups: list[SignupDTO]


class PendingActivationDTO(ApiModel):
    """One subscription awaiting a manual decision (X-02).

    ``priceMinor`` is in the plan's own ``currency``'s minor unit, as
    ``plan_tiers`` stores it. It is passed through unconverted so the screen
    formats it once, rather than the API guessing a locale.
    """

    subscriptionId: str
    userId: str
    email: str
    displayName: str | None = None
    role: str
    planCode: str
    planName: str
    priceMinor: int
    currency: str
    requestedAt: str


class ActivationQueueDTO(ApiModel):
    """The whole queue, oldest first."""

    pending: list[PendingActivationDTO]


class ActivationDecisionDTO(ApiModel):
    """Activate or reject one pending subscription.

    ``note`` is optional at the API level even though X-02 asks for one: the
    column is nullable because a note is a human sentence with no honest default
    (migration ``0019``). The screen is where "please say why" belongs.
    """

    note: str | None = None


class ActivationResultDTO(ApiModel):
    """The status the subscription now holds."""

    subscriptionId: str
    status: str


class SubjectCoverageDTO(ApiModel):
    """Mark-scheme coverage for one subject (X-03)."""

    subjectCode: str
    papers: int
    papersWithScheme: int
    papersWithoutScheme: int


class PipelineHealthDTO(ApiModel):
    """Corpus coverage, boundary reliance and ingestion outcomes (X-03).

    ``boundarySourceCounts`` is the observed distribution across recorded
    past-paper attempts: ``exact`` means a published boundary was found, the
    other two mean one was substituted. That is X-03's "whether predictions are
    real or estimated", measured rather than asserted.

    ``markingAccuracyNote`` is prose, not a number, and is the only such field in
    this module. X-03 asks for accuracy against the golden fixture set; that is
    produced by the accuracy harness into ``reports/``, not by anything a request
    can reach, and a figure read off a file the screen cannot date would be worse
    than saying where it lives.
    """

    subjects: list[SubjectCoverageDTO]
    boundarySourceCounts: dict[str, int]
    exactBoundaryKeys: int
    subjectDefaultBoundaryKeys: int
    uploadsByStatus: dict[str, int]
    recentFailedUploadIds: list[str]
    markingAccuracyNote: str


# ── Schools (D7.8, spec §1.1: the account graph's missing first link) ─────────


class SchoolAdminSummaryDTO(ApiModel):
    """One school_admin staffing a school, for the roster on the schools list."""

    userId: str
    email: str
    displayName: str | None = None


class SchoolSummaryDTO(ApiModel):
    """One school's provisioning state: quota, seat usage, and its admins.

    ``seatsAssigned`` counts non-revoked seats — the identical definition
    :class:`~lemely.web.schemas_school.SeatUsageDTO.used` already uses, so a
    seat count never means two different things depending on which screen
    reads it.
    """

    schoolId: str
    name: str
    seatQuota: int
    seatsAssigned: int
    seatsAvailable: int
    admins: list[SchoolAdminSummaryDTO]


class SchoolListDTO(ApiModel):
    """Every school on the platform (X-01's sibling list, but for schools)."""

    schools: list[SchoolSummaryDTO]


class CreateSchoolRequestDTO(ApiModel):
    """Create a school with an initial seat quota (D7.8).

    ``seatQuota`` is required rather than defaulted to the column's own
    ``0``: a platform admin creating a school is the one moment a real
    commercial quota should be set. D7.2 is the reason self-service signup
    never gets to do this at all — a visitor-created school would carry a
    quota of 0 and be unusable until a platform admin intervened anyway, so
    that intervention happens here, up front, instead.
    """

    name: str
    seatQuota: Annotated[int, Field(ge=0)]


class UpdateSchoolRequestDTO(ApiModel):
    """Update a school's name and/or seat quota. Both fields optional.

    Independently settable so a name correction and a quota change are
    different edits — a caller changing only the name is never forced to
    resend (and thus risk clobbering) a quota someone else is mid-edit on.
    A quota that would fall below the seats already assigned is refused by
    the service with a 409 naming both numbers (Task 12's own test for this).
    """

    name: str | None = None
    seatQuota: Annotated[int, Field(ge=0)] | None = None


class CreateSchoolAdminRequestDTO(ApiModel):
    """Create a school_admin account and bind it to the school in the path.

    Same credential handling as
    :class:`~lemely.web.schemas_school.InviteTeacherRequestDTO`: no email
    provider exists in v1 (D7.6), so an omitted ``password`` is generated
    once by the router and returned once in ``temporaryPassword`` for the
    platform admin to convey out of band.
    """

    email: str
    displayName: str | None = None
    password: str | None = None


class CreateSchoolAdminResponseDTO(ApiModel):
    """The created school_admin's identity, its membership, and any generated password."""

    userId: str
    membershipId: str
    email: str
    temporaryPassword: str | None = None


__all__ = [
    "ActivationDecisionDTO",
    "ActivationQueueDTO",
    "ActivationResultDTO",
    "ApiModel",
    "CreateSchoolAdminRequestDTO",
    "CreateSchoolAdminResponseDTO",
    "CreateSchoolRequestDTO",
    "PendingActivationDTO",
    "PipelineHealthDTO",
    "PlatformCountsDTO",
    "PlatformOverviewDTO",
    "SchoolAdminSummaryDTO",
    "SchoolListDTO",
    "SchoolSummaryDTO",
    "SignupDTO",
    "SubjectCoverageDTO",
    "SystemHealthDTO",
    "UpdateSchoolRequestDTO",
]

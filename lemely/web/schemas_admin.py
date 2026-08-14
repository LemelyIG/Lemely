"""API DTOs for the platform-admin console (``/api/admin/*``, UI spec 4.10).

Every field here is a counted fact. Where X-01/X-03 ask for something the system
does not record, the DTO carries an explicit ``None`` or omits the field and says
why in its docstring — it never carries a derived stand-in. That rule matters
more on this surface than anywhere else in the product: the reader is the person
who would act on the number, and nobody downstream re-checks their work.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


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


class SpendDTO(ApiModel):
    """Gemini spend against the configured hard ceiling (X-01).

    ``ceilingUsd`` and ``remainingUsd`` are ``None`` together when no ceiling is
    configured — a real state, distinct from a ceiling of zero.
    ``thresholdsUsd`` are the marks the runtime sends warnings at; a spend figure
    without its alarm points cannot be read as safe or unsafe.
    """

    cumulativeUsd: float
    ceilingUsd: float | None = None
    remainingUsd: float | None = None
    thresholdsUsd: list[float]


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
    """X-01 in one response."""

    counts: PlatformCountsDTO
    spend: SpendDTO
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


__all__ = [
    "ActivationDecisionDTO",
    "ActivationQueueDTO",
    "ActivationResultDTO",
    "ApiModel",
    "PendingActivationDTO",
    "PipelineHealthDTO",
    "PlatformCountsDTO",
    "PlatformOverviewDTO",
    "SignupDTO",
    "SpendDTO",
    "SubjectCoverageDTO",
    "SystemHealthDTO",
]

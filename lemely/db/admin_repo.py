"""Platform-admin console service — the internal, global view (UI spec 4.10).

This is the first surface in the product with **no tenant scope at all**, and
that is the single most important thing about it. Every other service in
``lemely/db`` narrows to what the caller owns: ``class_repo`` to the caller's own
classes, ``seat_repo`` and ``school_admin_repo`` to schools they hold a
membership for, ``parent_repo`` to linked children. Those services all treat
``platform_admin`` as holding *nothing*, on purpose (D1.6/D1.10, "no super-role
bypass") — a platform admin is not a teacher with wider eyes.

So the global view is a separate service reached by a separate router gated to
``platform_admin`` alone, rather than a flag that widens an existing query. That
keeps the blast radius of a bug in the tenancy filters where it already is: a
mistake here cannot leak one school's data into another school's screen, because
this module has no per-school screen to leak into. It answers only in aggregate,
plus two deliberately-narrow row lists (recent signups, the activation queue)
that a human has to act on.

**Everything here is counted, never estimated.** X-01 and X-03 are the screens
where a plausible-looking number is most dangerous, because the reader is the
person who would act on it and nobody downstream checks their work. Where a
figure the spec asks for has no source, the method returns ``None`` and says so
in its docstring rather than deriving something adjacent — see
:meth:`PlatformAdminService.pipeline_health` on marking accuracy.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from lemely.db.models import (
    Attempt,
    MarkScheme,
    Paper,
    PlanTier,
    ReviewQueueItem,
    School,
    SchoolClass,
    Subscription,
    Upload,
    User,
)
from lemely.db.models.enums import (
    AttemptOrigin,
    ReviewStatus,
    Role,
    SubscriptionStatus,
    UploadStatus,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker


class AdminError(Exception):
    """Base class for platform-admin failures."""


class SubscriptionNotFoundError(AdminError):
    """No subscription exists for the supplied id (→ 404)."""


class SubscriptionAlreadyDecidedError(AdminError):
    """The subscription has already left the queue (→ 409).

    Two admins working the same queue is the expected case, not an exotic one, so
    the second decision is refused rather than silently overwriting the first.
    """

    def __init__(self, status: SubscriptionStatus) -> None:
        """Record the status the row already holds."""
        super().__init__(f"Subscription is already {status.value}")
        self.status = status


@dataclass(frozen=True, slots=True)
class SignupRow:
    """One recently created account."""

    user_id: uuid.UUID
    email: str
    display_name: str | None
    role: Role
    created_at: datetime


@dataclass(frozen=True, slots=True)
class PlatformCounts:
    """Global row counts plus the two live operational depths.

    ``papers_marked_last_7_days`` counts past-paper attempts only. A quiz
    submission is also an ``Attempt`` row, and counting it as marking throughput
    would inflate the number with work the marking pipeline never did
    (``docs/quiz-model.md`` §5 draws the same line for averages).
    """

    students: int
    parents: int
    teachers: int
    school_admins: int
    platform_admins: int
    schools: int
    classes: int
    papers_marked_total: int
    papers_marked_last_24_hours: int
    papers_marked_last_7_days: int
    open_review_items: int
    uploads_by_status: dict[str, int]


@dataclass(frozen=True, slots=True)
class SpendSnapshot:
    """Gemini spend against the configured hard ceiling.

    ``ceiling_usd`` is ``None`` when no ceiling is configured, which is a real
    configuration state and not a zero. ``thresholds_usd`` are the warning marks
    the runtime notifies on; X-01 shows them because a number without its alarm
    points cannot be read as safe or unsafe.
    """

    cumulative_usd: float
    ceiling_usd: float | None
    thresholds_usd: list[float]

    @property
    def remaining_usd(self) -> float | None:
        """Headroom left, or ``None`` when there is no ceiling to be under."""
        if self.ceiling_usd is None:
            return None
        return max(0.0, self.ceiling_usd - self.cumulative_usd)


@dataclass(frozen=True, slots=True)
class PendingActivation:
    """One subscription awaiting a manual decision (X-02)."""

    subscription_id: uuid.UUID
    user_id: uuid.UUID
    email: str
    display_name: str | None
    role: Role
    plan_code: str
    plan_name: str
    price_minor: int
    currency: str
    requested_at: datetime


@dataclass(frozen=True, slots=True)
class SubjectCoverage:
    """Mark-scheme coverage for one subject."""

    subject_code: str
    papers: int
    papers_with_scheme: int

    @property
    def papers_without_scheme(self) -> int:
        """Papers in the corpus with no parsed mark scheme behind them."""
        return self.papers - self.papers_with_scheme


@dataclass(frozen=True, slots=True)
class PipelineHealth:
    """Corpus coverage, boundary reliance, and ingestion outcomes (X-03).

    ``boundary_source_counts`` is the *observed* distribution across recorded
    attempts, keyed by :class:`~lemely.db.models.enums.BoundarySource` value.
    That is the direct answer to X-03's "whether predictions are real or
    estimated": ``exact`` means a published boundary was found, the other two
    mean one was substituted.

    ``marking_accuracy`` is deliberately absent from this dataclass. X-03 asks
    for "marking accuracy metrics against the golden fixture set", and no table,
    file or endpoint carries that at runtime — it is produced by
    ``tests/test_accuracy_*.py`` into ``reports/`` when the harness is run.
    Reading a report file from a request handler would report whenever the file
    happened to last be written, with no way for the screen to know how stale it
    is, so the surface says the metric lives elsewhere instead of showing a
    number it cannot date.
    """

    subjects: list[SubjectCoverage]
    boundary_source_counts: dict[str, int]
    exact_boundary_keys: int
    subject_default_boundary_keys: int
    uploads_by_status: dict[str, int]
    recent_failed_uploads: list[uuid.UUID]


class PlatformAdminService:
    """Global counts and the manual-activation queue, for ``platform_admin``."""

    def __init__(self, sessionmaker: sessionmaker[Session]) -> None:
        """Bind the service to a session factory."""
        self._sessionmaker = sessionmaker

    # -- X-01 ---------------------------------------------------------------

    def counts(self, *, now: datetime | None = None) -> PlatformCounts:
        """Return the global counts behind X-01.

        ``now`` is injected rather than read here so the two rolling windows are
        reproducible in a test, matching :mod:`lemely.core.at_risk`'s convention.
        """
        moment = now or datetime.now(UTC)
        with self._sessionmaker() as session:
            by_role = {
                role: count
                for role, count in session.execute(
                    select(User.role, func.count()).group_by(User.role)
                ).all()
            }
            marked_total = self._paper_attempts_since(session, None)
            return PlatformCounts(
                students=int(by_role.get(Role.student, 0)),
                parents=int(by_role.get(Role.parent, 0)),
                teachers=int(by_role.get(Role.teacher, 0)),
                school_admins=int(by_role.get(Role.school_admin, 0)),
                platform_admins=int(by_role.get(Role.platform_admin, 0)),
                schools=int(session.scalar(select(func.count()).select_from(School)) or 0),
                classes=int(session.scalar(select(func.count()).select_from(SchoolClass)) or 0),
                papers_marked_total=marked_total,
                papers_marked_last_24_hours=self._paper_attempts_since(
                    session, moment - timedelta(hours=24)
                ),
                papers_marked_last_7_days=self._paper_attempts_since(
                    session, moment - timedelta(days=7)
                ),
                open_review_items=int(
                    session.scalar(
                        select(func.count())
                        .select_from(ReviewQueueItem)
                        .where(ReviewQueueItem.status == ReviewStatus.open)
                    )
                    or 0
                ),
                uploads_by_status=self._uploads_by_status(session),
            )

    def recent_signups(self, limit: int = 10) -> list[SignupRow]:
        """Return the most recently created accounts, newest first.

        Every role, not just students: X-01's reader is watching the platform,
        and a teacher or school-admin account appearing is the more interesting
        event of the two.
        """
        with self._sessionmaker() as session:
            rows = session.execute(
                select(User.id, User.email, User.display_name, User.role, User.created_at)
                .order_by(User.created_at.desc())
                .limit(limit)
            ).all()
        return [
            SignupRow(
                user_id=user_id,
                email=email,
                display_name=display_name,
                role=role,
                created_at=created_at,
            )
            for user_id, email, display_name, role, created_at in rows
        ]

    # -- X-02 ---------------------------------------------------------------

    def pending_activations(self) -> list[PendingActivation]:
        """Return every subscription still awaiting a manual decision.

        The queue is exactly ``status == inactive``: that is the column's server
        default, so a subscription that has never been decided on is in it by
        construction rather than by a flag someone has to remember to set.
        Oldest first — a queue worked newest-first starves its own tail.
        """
        with self._sessionmaker() as session:
            rows = session.execute(
                select(
                    Subscription.id,
                    Subscription.user_id,
                    User.email,
                    User.display_name,
                    User.role,
                    PlanTier.code,
                    PlanTier.name,
                    PlanTier.price_minor,
                    PlanTier.currency,
                    Subscription.created_at,
                )
                .join(User, User.id == Subscription.user_id)
                .join(PlanTier, PlanTier.id == Subscription.plan_tier_id)
                .where(Subscription.status == SubscriptionStatus.inactive)
                .order_by(Subscription.created_at)
            ).all()
        return [
            PendingActivation(
                subscription_id=subscription_id,
                user_id=user_id,
                email=email,
                display_name=display_name,
                role=role,
                plan_code=plan_code,
                plan_name=plan_name,
                price_minor=price_minor,
                currency=currency,
                requested_at=created_at,
            )
            for (
                subscription_id,
                user_id,
                email,
                display_name,
                role,
                plan_code,
                plan_name,
                price_minor,
                currency,
                created_at,
            ) in rows
        ]

    def decide_activation(
        self,
        subscription_id: uuid.UUID | str,
        *,
        activate: bool,
        note: str | None = None,
        now: datetime | None = None,
    ) -> SubscriptionStatus:
        """Activate or reject a pending subscription, recording the note.

        Returns the status the row now holds.

        A row that has already left ``inactive`` raises rather than being
        rewritten: two admins working one queue is the ordinary case, and the
        second click must not silently reverse the first decision.

        ``activated_at`` is set on activation only. A rejection has no activation
        instant, and reusing the column for "when we decided" would make the two
        events indistinguishable in the one table an audit reads.

        Raises:
            SubscriptionNotFoundError: No subscription with that id.
            SubscriptionAlreadyDecidedError: It is no longer ``inactive``.
        """
        moment = now or datetime.now(UTC)
        subscription_uuid = _as_uuid(subscription_id)
        with self._sessionmaker() as session, session.begin():
            # Locked for the duration: the check below is a read-then-write, and
            # the whole point of it is to be correct when two admins race.
            subscription = session.get(Subscription, subscription_uuid, with_for_update=True)
            if subscription is None:
                raise SubscriptionNotFoundError(f"Unknown subscription: {subscription_uuid}")
            if subscription.status is not SubscriptionStatus.inactive:
                raise SubscriptionAlreadyDecidedError(subscription.status)
            if activate:
                subscription.status = SubscriptionStatus.active
                subscription.is_manually_activated = True
                subscription.activated_at = moment
            else:
                subscription.status = SubscriptionStatus.rejected
            subscription.activation_note = note
            return subscription.status

    # -- X-03 ---------------------------------------------------------------

    def pipeline_health(
        self, *, exact_boundary_keys: int, subject_default_boundary_keys: int
    ) -> PipelineHealth:
        """Return corpus coverage, boundary reliance, and ingestion outcomes.

        The two boundary-key counts are passed in rather than read here: they
        come from :class:`~lemely.io.grade_boundaries.GradeBoundaryStore`, which
        is a file-backed I/O object, and this module deliberately touches nothing
        but the database.
        """
        with self._sessionmaker() as session:
            coverage_rows = session.execute(
                select(
                    Paper.subject_code,
                    func.count(func.distinct(Paper.id)),
                    func.count(func.distinct(MarkScheme.paper_id)),
                )
                .outerjoin(MarkScheme, MarkScheme.paper_id == Paper.id)
                .group_by(Paper.subject_code)
                .order_by(Paper.subject_code)
            ).all()
            boundary_counts = {
                source.value if source is not None else "unrecorded": int(count)
                for source, count in session.execute(
                    select(Attempt.boundary_source, func.count())
                    .where(Attempt.origin == AttemptOrigin.past_paper)
                    .group_by(Attempt.boundary_source)
                ).all()
            }
            failed = list(
                session.scalars(
                    select(Upload.id)
                    .where(Upload.status == UploadStatus.failed)
                    .order_by(Upload.created_at.desc())
                    .limit(10)
                ).all()
            )
            return PipelineHealth(
                subjects=[
                    SubjectCoverage(
                        subject_code=subject_code,
                        papers=int(papers),
                        papers_with_scheme=int(with_scheme),
                    )
                    for subject_code, papers, with_scheme in coverage_rows
                ],
                boundary_source_counts=boundary_counts,
                exact_boundary_keys=exact_boundary_keys,
                subject_default_boundary_keys=subject_default_boundary_keys,
                uploads_by_status=self._uploads_by_status(session),
                recent_failed_uploads=failed,
            )

    # -- Internals ----------------------------------------------------------

    def _paper_attempts_since(self, session: Session, since: datetime | None) -> int:
        stmt = (
            select(func.count())
            .select_from(Attempt)
            .where(Attempt.origin == AttemptOrigin.past_paper)
        )
        if since is not None:
            stmt = stmt.where(Attempt.recorded_at >= since)
        return int(session.scalar(stmt) or 0)

    def _uploads_by_status(self, session: Session) -> dict[str, int]:
        """Every status is present, including the zeroes.

        A missing key would make the screen infer "no failures" from an absent
        entry, which is the same shape as "the query did not run".
        """
        observed = {
            status.value: int(count)
            for status, count in session.execute(
                select(Upload.status, func.count()).group_by(Upload.status)
            ).all()
        }
        return {status.value: observed.get(status.value, 0) for status in UploadStatus}


def _as_uuid(value: uuid.UUID | str) -> uuid.UUID:
    """Coerce a str/UUID to :class:`uuid.UUID`, raising ``ValueError`` if invalid."""
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Identifier must be a UUID, got {value!r}") from exc


__all__ = [
    "AdminError",
    "PendingActivation",
    "PipelineHealth",
    "PlatformAdminService",
    "PlatformCounts",
    "SignupRow",
    "SpendSnapshot",
    "SubjectCoverage",
    "SubscriptionAlreadyDecidedError",
    "SubscriptionNotFoundError",
]

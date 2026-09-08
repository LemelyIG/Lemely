"""Idempotent database seeding: reference data and demo accounts.

Run via ``make seed`` or ``python -m lemely.db.seed`` AFTER the schema has been
migrated (``alembic upgrade head``). Seeding is split into:

* **reference data** — static, board-agnostic rows the app needs to function
  (the three CAIE subjects this build actually supports: 0580, 0606, 0625).
  Safe to run on every deploy.
* **demo accounts** — the five-role demo users used by local development and
  the Phase-6 fresh-clone acceptance test, on stable ``.local`` emails so this
  module doubles as the one place their credentials are documented. The demo
  parent is an ordinary email/password account like the other four (the
  parent-invites redesign retired phone-OTP parent login), linked directly to
  the demo student rather than through a redeemed invite — there is no other
  student around for it to redeem one from.

Both are idempotent — reference data by upsert (migration 0024 also writes
these rows, so insert-if-absent could no longer correct a drifted one), demo
accounts by insert-if-absent, and the demo-parent link by the same
check-then-insert :meth:`~lemely.db.parent_repo.ParentLinkService.link_in_session`
uses for a real redemption. The seeding *decisions* — which rows, which
accounts, how a second run recognises what the first run already did, and the
one recovery path (GoTrue-has-it-but-the-mirror-does-not) — live in the
pure/injected functions below
(:func:`subjects_to_upsert`, :func:`create_demo_accounts`), which
``tests/test_seed.py`` drives hermetically through the same in-memory fakes
:mod:`tests.auth_fakes` gives ``test_auth_service.py``. :func:`seed_reference_data`
and :func:`seed_demo_accounts` are thin wrappers that open a session, build the
real dependencies, and delegate — a seeder whose correctness can only be
checked against a live stack is a seeder nobody checks.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import select

from lemely.auth.gotrue import HttpGoTrueBackend
from lemely.auth.mirror import DbUserMirror
from lemely.auth.otp import OtpStore
from lemely.auth.service import AuthService
from lemely.auth.sms import MockSmsProvider
from lemely.db.models.academic import Subject
from lemely.db.models.enums import ExamBoard, QualificationLevel, Role
from lemely.db.parent_repo import ParentLinkService
from lemely.db.session import get_sessionmaker, session_scope
from lemely.io import syllabus_topics
from lemely.runtime.config import Settings, load_settings
from lemely.runtime.errors import AuthError, LemelyError

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.orm import Session, sessionmaker

    from lemely.auth.mirror import UserMirror

logger = structlog.get_logger(__name__)


class SeedError(LemelyError):
    """A seed step could not be completed safely and must not guess."""


# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SubjectSpec:
    """A reference ``subjects`` row this build declares support for."""

    code: str
    name: str
    board: ExamBoard = ExamBoard.caie
    qualification_level: QualificationLevel = QualificationLevel.igcse


#: The three CAIE syllabus codes the corpus, the accuracy harness and the
#: syllabus taxonomy all agree on (``lemely.io.det.profiles.SUBJECT_PROFILES``).
#: A fourth code here would be a claim of support nothing else in the build
#: backs. All three are IGCSE syllabuses.
CATALOGUE_SUBJECTS: tuple[SubjectSpec, ...] = (
    SubjectSpec(code="0580", name="Mathematics"),
    SubjectSpec(code="0606", name="Additional Mathematics"),
    SubjectSpec(code="0625", name="Physics"),
)


def subjects_to_upsert(existing_codes: set[str]) -> list[SubjectSpec]:
    """Return every :data:`CATALOGUE_SUBJECTS` row, regardless of what exists.

    Pure: no session, no I/O. Migration 0024 now inserts these same rows as
    part of the schema upgrade, so the seeder is no longer the only writer —
    insert-if-absent would leave a row that later drifted (e.g. a corrected
    ``name``) uncorrectable. Upserting every spec on every run means the two
    writers agree: same rows, same conflict handling, both idempotent.
    ``existing_codes`` is accepted so the call site still reads as "what's
    there vs. what should be there", but every spec is returned unconditionally.
    """
    del existing_codes
    return list(CATALOGUE_SUBJECTS)


# ---------------------------------------------------------------------------
# Demo accounts
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DemoAccount:
    """One email/password demo account this build ships with a declared role."""

    email: str
    role: Role
    display_name: str


#: A password shared by every demo account. Stable and documented (rather than
#: the random per-run secret ``scripts/seed_e2e.py`` mints) because the whole
#: point of this table is a credential a human or a fresh-clone test can name.
DEMO_PASSWORD = "Demo-Lemely-1!"  # noqa: S105 - a documented demo credential, not a real secret

#: One account per :class:`Role`, all created the same email/password way —
#: covers all five roles exactly once (pinned by
#: ``tests/test_seed.py::TestDemoAccountTable``). The parent used to be a
#: phone-OTP account (``DemoParent``); the parent-invites redesign retired
#: phone login, so it is an ordinary row here like the other four, linked to
#: the demo student by :func:`_link_demo_parent` rather than by a redeemed
#: invite.
DEMO_ACCOUNTS: tuple[DemoAccount, ...] = (
    DemoAccount(email="student@demo.lemely.local", role=Role.student, display_name="Demo Student"),
    DemoAccount(email="teacher@demo.lemely.local", role=Role.teacher, display_name="Demo Teacher"),
    DemoAccount(
        email="school-admin@demo.lemely.local",
        role=Role.school_admin,
        display_name="Demo School Admin",
    ),
    DemoAccount(
        email="platform-admin@demo.lemely.local",
        role=Role.platform_admin,
        display_name="Demo Platform Admin",
    ),
    DemoAccount(email="parent@demo.lemely.local", role=Role.parent, display_name="Demo Parent"),
)


@dataclass(frozen=True, slots=True)
class SeededAccount:
    """One demo account's resulting mirrored identity."""

    role: Role
    user_id: uuid.UUID
    email: str | None = None


@dataclass(frozen=True, slots=True)
class DemoAccountsResult:
    """Outcome of a :func:`create_demo_accounts` run."""

    created: int
    skipped: int
    accounts: tuple[SeededAccount, ...]


def create_demo_accounts(
    *,
    auth_service: AuthService,
    mirror: UserMirror,
    parent_link_service: ParentLinkService,
    session_factory: sessionmaker[Session],
) -> DemoAccountsResult:
    """Create (or recognise) every :data:`DEMO_ACCOUNTS` row, then link the parent to the student.

    Dependency-injected, no session of its own for account creation —
    ``auth_service`` and ``mirror`` are the exact seams
    :class:`~lemely.auth.service.AuthService` is built from, so that half can
    be driven hermetically (``tests/test_seed.py``) or against the live stack
    (:func:`seed_demo_accounts`) unchanged. Linking the parent does need an
    open session, because :meth:`~lemely.db.parent_repo.ParentLinkService.link_in_session`
    takes one rather than opening its own (its only production caller,
    ``InviteService.redeem``, needs the link and the invite's redemption in one
    transaction) — ``session_factory`` is that seam, and a fake in tests never
    needs to be a real engine since the fake link service never touches it.

    Idempotent: a second call creates nothing and reports every account
    skipped, with the same :class:`SeededAccount` ids as the first call, and
    re-links the same already-linked pair rather than duplicating it
    (``link_in_session`` checks first).

    Raises:
        SeedError: A future seed step raises it; nothing here does today (see
            the class docstring). Kept as the module's declared failure seam
            rather than removed along with the phone-OTP branch that used to
            raise it.
    """
    created = 0
    skipped = 0
    accounts: list[SeededAccount] = []

    for account in DEMO_ACCOUNTS:
        seeded, was_created = _create_or_recover_email_account(auth_service, mirror, account)
        accounts.append(seeded)
        created += was_created
        skipped += not was_created

    student_id = next(a.user_id for a in accounts if a.role is Role.student)
    parent_id = next(a.user_id for a in accounts if a.role is Role.parent)
    _link_demo_parent(session_factory, parent_link_service, parent_id, student_id)

    return DemoAccountsResult(created=created, skipped=skipped, accounts=tuple(accounts))


def _create_or_recover_email_account(
    auth_service: AuthService, mirror: UserMirror, account: DemoAccount
) -> tuple[SeededAccount, bool]:
    """Sign up ``account``, or recover it if GoTrue already holds the credential.

    A first run signs up cleanly. A second run — or a first run against a
    stack where GoTrue survived a wiped app schema — hits GoTrue's 422
    "already exists" and would fail signup forever. The naive recovery,
    logging in, is wrong on its own: :meth:`AuthService.login` falls back to
    ``student`` for a user the mirror has never seen, which would silently
    demote e.g. the demo teacher and 403 the teacher portal. So the recovery
    here verifies the credential via ``login`` and then explicitly mirrors the
    role :data:`DEMO_ACCOUNTS` declares, overwriting whatever ``login`` just
    wrote.
    """
    try:
        result = auth_service.signup(
            account.email, DEMO_PASSWORD, account.role, display_name=account.display_name
        )
        return (
            SeededAccount(email=account.email, role=account.role, user_id=result.user_id),
            True,
        )
    except AuthError as exc:
        if "(422)" not in str(exc):
            raise
        login_result = auth_service.login(account.email, DEMO_PASSWORD)
        # `login` already upserted a mirror row using its own fallback: the
        # DECLARED role when one was already mirrored, else `student`. That
        # tells us, without a second round trip, whether the mirror had this
        # user before this call: a mismatch against `account.role` can only
        # come from the `student` fallback, i.e. a genuinely fresh mirror row
        # (the "GoTrue survived, public.users did not" case this recovery
        # path exists for). A match means the row was already correct and
        # this call changed nothing observable.
        was_fresh = login_result.role is not account.role
        mirror.upsert(
            login_result.user_id,
            email=account.email,
            role=account.role,
            display_name=account.display_name,
        )
        return (
            SeededAccount(email=account.email, role=account.role, user_id=login_result.user_id),
            was_fresh,
        )


def _link_demo_parent(
    session_factory: sessionmaker[Session],
    parent_link_service: ParentLinkService,
    parent_id: uuid.UUID,
    student_id: uuid.UUID,
) -> None:
    """Link the demo parent to the demo student, the same way a redeemed invite would.

    :meth:`~lemely.db.parent_repo.ParentLinkService.link_in_session` takes an
    already-open session rather than opening one itself — its only production
    caller, ``InviteService.redeem``, needs the link row and the invite's
    redemption committed in one transaction. This seed has no invite to
    redeem (there is no other party to have issued one), so it opens and
    commits a single-purpose transaction of its own to reuse that exact
    method, rather than reaching into ``parent_child_links`` directly.

    Idempotent: re-linking an already-linked pair is a silent no-op
    (``link_in_session`` checks first), so a second ``make seed`` run is safe.
    """
    with session_factory() as session, session.begin():
        parent_link_service.link_in_session(session, parent_id, student_id)


# ---------------------------------------------------------------------------
# Thin DB-touching wrappers
# ---------------------------------------------------------------------------


def seed_reference_data(settings: Settings | None = None) -> int:
    """Upsert every :data:`CATALOGUE_SUBJECTS` row. Returns rows added.

    Migration 0024 also inserts these rows during the schema upgrade, so this
    upserts on ``code`` rather than inserting only what is missing — a row
    that drifted since the migration ran (e.g. a corrected ``name``) is
    corrected here too, not silently left alone. Existing columns this build
    does not declare (``syllabus_version``, ``source_url``) are left
    untouched.

    Invalidates :mod:`lemely.io.syllabus_topics`'s process cache — its loader
    queries ``Subject``, the exact table this upserts — so a long-lived
    process that seeded does not keep serving a subject list it cached before
    this run corrected the rows underneath it.
    :mod:`lemely.io.paper_timing` and :mod:`lemely.io.grade_boundaries` also
    carry process caches, but both are keyed off tables this function never
    writes to (``syllabus_papers``, ``component_thresholds`` respectively) —
    invalidating either here would be a no-op dressed up as caution, so both
    are deliberately left alone.
    """
    settings = settings or load_settings()
    with session_scope(settings) as session:
        to_upsert = subjects_to_upsert(set())
        existing_subjects = {
            subject.code: subject
            for subject in session.scalars(
                select(Subject).where(Subject.code.in_(spec.code for spec in to_upsert))
            )
        }
        added = 0
        for spec in to_upsert:
            subject = existing_subjects.get(spec.code)
            if subject is None:
                session.add(
                    Subject(
                        code=spec.code,
                        name=spec.name,
                        board=spec.board,
                        qualification_level=spec.qualification_level,
                        active=True,
                    )
                )
                added += 1
            else:
                subject.name = spec.name
                subject.qualification_level = spec.qualification_level
                subject.active = True
    syllabus_topics.invalidate_reference_cache()
    return added


def _build_auth_service(settings: Settings) -> tuple[AuthService, DbUserMirror]:
    """Wire a real :class:`AuthService` for seeding.

    Mirrors :func:`lemely.web.deps.get_auth_service`'s wiring, except the SMS
    provider is always the offline :class:`MockSmsProvider`. No demo account
    seeded here goes through the phone-OTP path any more (the parent-invites
    redesign moved the demo parent to email/password, see :data:`DEMO_ACCOUNTS`),
    but ``AuthService`` still requires an ``sms``/``otp_store`` pair to
    construct — :meth:`~lemely.auth.service.AuthService.request_otp`/``verify_otp``
    are kept as a seam for a possible future paid SMS channel — and seeding
    must never depend on a real gateway even for that unused path.
    """
    mirror = DbUserMirror(settings)
    otp_store = OtpStore(
        clock=lambda: datetime.now(UTC),
        rng=random.SystemRandom(),
        ttl_seconds=settings.auth.otp_ttl_seconds,
        max_attempts=settings.auth.otp_max_attempts,
        code_length=settings.auth.otp_length,
        min_resend_seconds=settings.auth.otp_min_resend_seconds,
    )
    auth_service = AuthService(
        gotrue=HttpGoTrueBackend(settings),
        mirror=mirror,
        sms=MockSmsProvider(),
        otp_store=otp_store,
        settings=settings,
    )
    return auth_service, mirror


def seed_demo_accounts(settings: Settings | None = None) -> int:
    """Create the five-role demo accounts against the live stack. Returns accounts created.

    Idempotent: an existing account is recognised (see
    :func:`create_demo_accounts`) and skipped rather than re-created, and the
    demo-parent link is re-linked into a no-op the same way.
    """
    settings = settings or load_settings()
    auth_service, mirror = _build_auth_service(settings)
    session_factory = get_sessionmaker(settings)
    parent_link_service = ParentLinkService(session_factory)
    result = create_demo_accounts(
        auth_service=auth_service,
        mirror=mirror,
        parent_link_service=parent_link_service,
        session_factory=session_factory,
    )
    return result.created


def seed_all(settings: Settings | None = None) -> None:
    """Run all idempotent seed steps in order."""
    settings = settings or load_settings()
    ref = seed_reference_data(settings)
    demo = seed_demo_accounts(settings)
    logger.info("db.seed.done", reference_rows=ref, demo_accounts=demo)


def main() -> None:
    """CLI entry point for ``python -m lemely.db.seed`` (``make seed``).

    Resolves the stack's service-role/anon keys (:func:`ensure_supabase_env`)
    before doing anything else, so this runs bare from a fresh clone exactly
    like ``scripts/seed_e2e.py`` does — without it the first admin-create call
    inside :func:`seed_demo_accounts` dies on a bare "service-role key is not
    configured" instead of a message telling the reader to start the stack or
    export two variables. Deliberately called here and nowhere else in this
    module: importing :mod:`lemely.db.seed` (or calling
    :func:`seed_reference_data`/:func:`seed_demo_accounts`/:func:`seed_all`
    directly, as the hermetic tests and any future library caller do) must
    never shell out to the ``supabase`` CLI.
    """
    from lemely.runtime.logging import configure_logging
    from lemely.runtime.supabase_env import ensure_supabase_env

    configure_logging()
    ensure_supabase_env()
    seed_all()


__all__ = [
    "CATALOGUE_SUBJECTS",
    "DEMO_ACCOUNTS",
    "DEMO_PASSWORD",
    "DemoAccount",
    "DemoAccountsResult",
    "SeedError",
    "SeededAccount",
    "SubjectSpec",
    "create_demo_accounts",
    "main",
    "seed_all",
    "seed_demo_accounts",
    "seed_reference_data",
    "subjects_to_upsert",
]


if __name__ == "__main__":
    main()

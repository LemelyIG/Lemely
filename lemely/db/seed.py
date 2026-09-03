"""Idempotent database seeding: reference data and demo accounts.

Run via ``make seed`` or ``python -m lemely.db.seed`` AFTER the schema has been
migrated (``alembic upgrade head``). Seeding is split into:

* **reference data** — static, board-agnostic rows the app needs to function
  (the three CAIE subjects this build actually supports: 0580, 0606, 0625).
  Safe to run on every deploy.
* **demo accounts** — the five-role demo users used by local development and
  the Phase-6 fresh-clone acceptance test, on stable ``.local`` emails/phone so
  this module doubles as the one place their credentials are documented.

Both are idempotent — reference data by upsert (migration 0024 also writes
these rows, so insert-if-absent could no longer correct a drifted one), demo
accounts by insert-if-absent. The seeding *decisions* — which rows, which
accounts, how a second run recognises what the first run already did, and the
two recovery paths (GoTrue-has-it-but-the-mirror-does-not; the OTP provider
that cannot hand back a code) — live in the pure/injected functions below
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
from lemely.db.session import session_scope
from lemely.io import paper_timing, syllabus_topics
from lemely.runtime.config import Settings, load_settings
from lemely.runtime.errors import AuthError, LemelyError

if TYPE_CHECKING:
    import uuid

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


@dataclass(frozen=True, slots=True)
class DemoParent:
    """The demo parent, reachable by phone-OTP rather than email/password."""

    phone: str
    display_name: str
    role: Role = Role.parent


#: A password shared by every demo account. Stable and documented (rather than
#: the random per-run secret ``scripts/seed_e2e.py`` mints) because the whole
#: point of this table is a credential a human or a fresh-clone test can name.
DEMO_PASSWORD = "Demo-Lemely-1!"  # noqa: S105 - a documented demo credential, not a real secret

#: One account per non-parent :class:`Role`. Together with :data:`DEMO_PARENT`
#: this covers all five roles exactly once (pinned by
#: ``tests/test_seed.py::TestDemoAccountTable``).
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
)

#: The demo parent. ``.local`` is reserved (RFC 6762) so, like the email
#: accounts above, this can never be a real handset number someone else owns.
DEMO_PARENT = DemoParent(phone="+10000000000", display_name="Demo Parent")


@dataclass(frozen=True, slots=True)
class SeededAccount:
    """One demo account's resulting mirrored identity, email or phone-only."""

    role: Role
    user_id: uuid.UUID
    email: str | None = None
    phone: str | None = None


@dataclass(frozen=True, slots=True)
class DemoAccountsResult:
    """Outcome of a :func:`create_demo_accounts` run."""

    created: int
    skipped: int
    accounts: tuple[SeededAccount, ...]


def create_demo_accounts(*, auth_service: AuthService, mirror: UserMirror) -> DemoAccountsResult:
    """Create (or recognise) every :data:`DEMO_ACCOUNTS` row plus :data:`DEMO_PARENT`.

    Dependency-injected, no session of its own — ``auth_service`` and
    ``mirror`` are the exact seams :class:`~lemely.auth.service.AuthService`
    is built from, so this can be driven hermetically (``tests/test_seed.py``)
    or against the live stack (:func:`seed_demo_accounts`) unchanged.

    Idempotent: a second call creates nothing and reports every account
    skipped, with the same :class:`SeededAccount` ids as the first call.

    Raises:
        SeedError: The phone-OTP account cannot be seeded because the
            configured SMS provider delivers out of band (D3.16) — see
            :meth:`~lemely.auth.service.AuthService.request_otp`.
    """
    created = 0
    skipped = 0
    accounts: list[SeededAccount] = []

    for account in DEMO_ACCOUNTS:
        seeded, was_created = _create_or_recover_email_account(auth_service, mirror, account)
        accounts.append(seeded)
        created += was_created
        skipped += not was_created

    parent_seeded, parent_created = _create_or_recover_parent(auth_service, mirror)
    accounts.append(parent_seeded)
    created += parent_created
    skipped += not parent_created

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


def _create_or_recover_parent(
    auth_service: AuthService, mirror: UserMirror
) -> tuple[SeededAccount, bool]:
    """Verify-or-recognise :data:`DEMO_PARENT` via the phone-OTP flow.

    Checked against the mirror *before* issuing a challenge, not by trying and
    recovering from failure: re-requesting an OTP for an already-seeded phone
    would needlessly cost a challenge (and, against a real gateway, an SMS)
    for no observable effect, since :meth:`AuthService.verify_otp` already
    reuses the existing mirrored row for a known phone.
    """
    existing = mirror.get_by_phone(DEMO_PARENT.phone)
    if existing is not None:
        _apply_parent_display_name(mirror, existing.id)
        return SeededAccount(phone=DEMO_PARENT.phone, role=Role.parent, user_id=existing.id), False

    code = auth_service.request_otp(DEMO_PARENT.phone)
    if code is None:
        raise SeedError(
            "Cannot seed the demo parent: the configured SMS provider delivers "
            "the OTP out of band, so request_otp() returned no code to verify "
            "with. Seed against a stack wired with an offline/mock SMS "
            "provider, or seed the parent manually."
        )
    result = auth_service.verify_otp(DEMO_PARENT.phone, code)
    _apply_parent_display_name(mirror, result.user_id)
    return SeededAccount(phone=DEMO_PARENT.phone, role=Role.parent, user_id=result.user_id), True


def _apply_parent_display_name(mirror: UserMirror, user_id: uuid.UUID) -> None:
    """Give the mirrored demo-parent row :data:`DEMO_PARENT`'s display name.

    The parent is the one demo account created through the OTP flow rather than
    :meth:`AuthService.signup`, and ``verify_otp`` mirrors a row with no display
    name — so ``DEMO_PARENT.display_name`` was declared and applied nowhere.
    Found by P6.10's fresh-clone run: the four password roles answered
    ``/api/me/profile`` with their demo names and the parent answered
    ``displayName: null``.

    Applied on the recognise path too, so a database seeded before this fix is
    corrected by the next ``make seed`` rather than staying nameless forever.
    """
    user = mirror.get_by_id(user_id)
    if user is None or user.display_name == DEMO_PARENT.display_name:
        return
    mirror.upsert(
        user_id=user.id,
        email=user.email,
        role=Role.parent,
        phone=user.phone,
        display_name=DEMO_PARENT.display_name,
    )


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

    Invalidates the process-level reference caches
    (:mod:`lemely.io.paper_timing`, :mod:`lemely.io.syllabus_topics`) so a
    long-lived process that seeded does not keep serving what it cached
    before this run corrected the rows underneath it.
    :mod:`lemely.io.grade_boundaries` also carries a cache, but it is keyed
    off ``component_thresholds`` (Task 12's ingest), a table this function
    never writes to — invalidating it here would be a no-op dressed up as
    caution, so it is deliberately left alone.
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
    paper_timing.invalidate_reference_cache()
    syllabus_topics.invalidate_reference_cache()
    return added


def _build_auth_service(settings: Settings) -> tuple[AuthService, DbUserMirror]:
    """Wire a real :class:`AuthService` for seeding.

    Mirrors :func:`lemely.web.deps.get_auth_service`'s wiring, except the SMS
    provider is always the offline :class:`MockSmsProvider`: demo/dev seeding
    must never depend on a real gateway to hand back the OTP code
    :func:`_create_or_recover_parent` verifies with.
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
    :func:`create_demo_accounts`) and skipped rather than re-created.
    """
    settings = settings or load_settings()
    auth_service, mirror = _build_auth_service(settings)
    result = create_demo_accounts(auth_service=auth_service, mirror=mirror)
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
    "DEMO_PARENT",
    "DEMO_PASSWORD",
    "DemoAccount",
    "DemoAccountsResult",
    "DemoParent",
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

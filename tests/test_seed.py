"""Tests for the demo/reference seeder (P6.10, refactor(seed) parent-invites).

Mostly hermetic: every demo-account test drives the real
:class:`~lemely.auth.service.AuthService` through the same in-memory fakes
``test_auth_service.py`` uses, so what is exercised here is the seeder's own
logic — idempotency, role fidelity, and the recovery path — rather than a
mock of it. Linking the demo parent to the demo student is exercised through
a fake :class:`~lemely.db.parent_repo.ParentLinkService`/session-factory pair
(:class:`_FakeParentLinkService`, :func:`_fake_session_factory`) rather than a
real one, for the same reason ``mirror``/``sms`` are faked: proving this
module's own linking call happens, not re-proving ``link_in_session``'s own
Postgres-backed idempotency (that lives in ``test_parent_repo.py``). The
seeding *decisions* for reference data live in the pure
:func:`subjects_to_upsert`, tested hermetically below.

One test is deliberately not hermetic:
``test_seed_reference_data_corrects_a_drifted_row`` calls
:func:`seed_reference_data` itself against a throwaway, migrated Postgres
(:func:`~tests.conftest.migrated_sessionmaker`) — a seeder whose
corrective-upsert behaviour can only be checked against a live stack is a
seeder nobody checks, and the pure function alone cannot prove a session
write actually corrects a drifted row.
"""

from __future__ import annotations

import os
import random
import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker

from lemely.auth.otp import OtpStore
from lemely.auth.service import AuthService
from lemely.auth.sms import MockSmsProvider
from lemely.db.models.academic import Subject
from lemely.db.models.enums import QualificationLevel, Role
from lemely.db.seed import (
    CATALOGUE_SUBJECTS,
    DEMO_ACCOUNTS,
    DEMO_PASSWORD,
    DemoAccountsResult,
    create_demo_accounts,
    seed_reference_data,
    subjects_to_upsert,
)
from lemely.db.session import dispose_engine
from lemely.runtime.config import Settings
from tests.auth_fakes import FakeGoTrueBackend, FakeUserMirror


class _FakeSession:
    """A no-op stand-in for :class:`~sqlalchemy.orm.Session`.

    :meth:`~lemely.db.parent_repo.ParentLinkService.link_in_session` takes an
    already-open session because its one production caller
    (``InviteService.redeem``) needs the link created in the same transaction
    as the invite being marked redeemed. ``_FakeParentLinkService`` below never
    actually touches the session it is handed, so this fake never needs a real
    engine — it exists only so ``create_demo_accounts``'s
    ``with session_factory() as session, session.begin():`` shape has
    something to enter.
    """

    def __enter__(self) -> _FakeSession:
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def begin(self) -> _FakeSession:
        return self


def _fake_session_factory() -> _FakeSession:
    """A ``sessionmaker``-shaped callable returning :class:`_FakeSession`."""
    return _FakeSession()


class _FakeParentLinkService:
    """Records ``(parent_id, child_id)`` pairs without touching a database.

    Deliberately ignores the ``session`` argument — this is a test double for
    the *seed script's own call*, not for ``link_in_session``'s Postgres
    behaviour, which ``test_parent_repo.py`` already proves against a real
    database. Dedupes exactly like the real
    :meth:`~lemely.db.parent_repo.ParentLinkService._link_if_absent` (checked
    first, no duplicate insert) — a fake that appended unconditionally could
    not tell a correctly-idempotent second call from a seeder that re-links
    on every run.
    """

    def __init__(self) -> None:
        self.links: list[tuple[uuid.UUID, uuid.UUID]] = []

    def link_in_session(self, session: object, parent_id: uuid.UUID, child_id: uuid.UUID) -> None:
        del session
        pair = (parent_id, child_id)
        if pair not in self.links:
            self.links.append(pair)


def _service(*, gotrue: FakeGoTrueBackend | None = None) -> tuple[AuthService, FakeUserMirror]:
    settings = Settings()
    mirror = FakeUserMirror()
    otp_store = OtpStore(
        clock=lambda: datetime.now(UTC),
        rng=random.Random(42),
        ttl_seconds=settings.auth.otp_ttl_seconds,
        max_attempts=settings.auth.otp_max_attempts,
        code_length=settings.auth.otp_length,
    )
    service = AuthService(
        gotrue=gotrue or FakeGoTrueBackend(),
        mirror=mirror,
        sms=MockSmsProvider(),  # type: ignore[arg-type]
        otp_store=otp_store,
        settings=settings,
    )
    return service, mirror


def _create_demo_accounts(
    *,
    gotrue: FakeGoTrueBackend | None = None,
    auth_service: AuthService | None = None,
    mirror: FakeUserMirror | None = None,
    parent_link_service: _FakeParentLinkService | None = None,
) -> tuple[DemoAccountsResult, AuthService, FakeUserMirror, _FakeParentLinkService]:
    """Drive :func:`create_demo_accounts` against the fakes above.

    Builds a fresh ``auth_service``/``mirror``/``parent_link_service`` unless
    the caller passes existing ones back in — which is how a test proves a
    *second* run against the same state is idempotent, rather than proving
    idempotency of two independent, freshly-seeded databases. Returns the
    result alongside every fake so a test can assert on any of them.
    """
    if auth_service is None or mirror is None:
        auth_service, mirror = _service(gotrue=gotrue)
    if parent_link_service is None:
        parent_link_service = _FakeParentLinkService()
    result = create_demo_accounts(
        auth_service=auth_service,
        mirror=mirror,
        parent_link_service=parent_link_service,  # type: ignore[arg-type]
        session_factory=_fake_session_factory,  # type: ignore[arg-type]
    )
    return result, auth_service, mirror, parent_link_service


# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------


class TestSubjectsToUpsert:
    def test_upserts_every_subject_into_an_empty_database(self) -> None:
        assert subjects_to_upsert(set()) == list(CATALOGUE_SUBJECTS)

    def test_upserts_every_subject_even_when_all_present(self) -> None:
        assert subjects_to_upsert({s.code for s in CATALOGUE_SUBJECTS}) == list(CATALOGUE_SUBJECTS)

    def test_upserts_every_subject_regardless_of_which_are_missing(self) -> None:
        assert [s.code for s in subjects_to_upsert({"0625"})] == ["0580", "0606", "0625"]

    def test_reference_subjects_are_the_three_the_product_supports(self) -> None:
        # The corpus, the accuracy harness and the syllabus taxonomy are all
        # 0580/0606/0625; a fourth code here would be a claim of support that
        # nothing else in the build backs.
        assert {s.code for s in CATALOGUE_SUBJECTS} == {"0580", "0606", "0625"}


def test_catalogue_subjects_carry_their_qualification_level() -> None:
    """0580, 0606 and 0625 are IGCSE syllabuses. The level belongs to the
    subject (spec D10), not to a question the wizard asks the student."""
    assert {s.code for s in CATALOGUE_SUBJECTS} == {"0580", "0606", "0625"}
    assert all(s.qualification_level is QualificationLevel.igcse for s in CATALOGUE_SUBJECTS)


def test_seed_reference_data_corrects_a_drifted_row(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    """Insert-if-absent was right when the seeder was the only writer. It is
    not now: migration 0024 also writes these rows, so a seeder that skips an
    existing row can never correct one that drifted.

    This is the one test in the file that actually calls
    :func:`seed_reference_data` against a database — a throwaway Postgres
    with migration 0024 applied (:func:`~tests.conftest.migrated_sessionmaker`),
    never the live dev database. It mutates ``0580``'s ``name`` and ``active``
    away from what :data:`CATALOGUE_SUBJECTS` declares, re-runs the seeder,
    and asserts both came back — the corrective-upsert behaviour the pure
    :func:`subjects_to_upsert` tests above cannot demonstrate on their own,
    since nothing ever writes their return value to a session there.
    """
    engine = migrated_sessionmaker.kw["bind"]
    rendered_url = engine.url.render_as_string(hide_password=False)
    previous_db_url = os.environ.get("LEMELY_DATABASE__URL")
    os.environ["LEMELY_DATABASE__URL"] = rendered_url

    with migrated_sessionmaker.begin() as session:
        subject = session.scalars(sa.select(Subject).where(Subject.code == "0580")).one()
        subject.name = "Drifted Name"
        subject.active = False

    try:
        seed_reference_data()
    finally:
        if previous_db_url is None:
            os.environ.pop("LEMELY_DATABASE__URL", None)
        else:
            os.environ["LEMELY_DATABASE__URL"] = previous_db_url
        dispose_engine()

    with migrated_sessionmaker() as session:
        subject = session.scalars(sa.select(Subject).where(Subject.code == "0580")).one()
        assert subject.name == "Mathematics"
        assert subject.active is True


# ---------------------------------------------------------------------------
# Demo accounts
# ---------------------------------------------------------------------------


class TestDemoAccountTable:
    def test_covers_all_five_roles_exactly_once(self) -> None:
        roles = [a.role for a in DEMO_ACCOUNTS]
        assert sorted(r.value for r in roles) == sorted(r.value for r in Role)

    def test_emails_are_unique_and_on_a_reserved_domain(self) -> None:
        emails = [a.email for a in DEMO_ACCOUNTS]
        assert len(set(emails)) == len(emails)
        # .local is reserved (RFC 6762) — a demo credential can never be a real
        # address someone else owns and could receive mail at.
        assert all(e.endswith(".local") for e in emails)


class TestCreateDemoAccounts:
    def test_creates_every_role_on_a_fresh_database(self) -> None:
        result, _auth_service, mirror, _link_service = _create_demo_accounts()

        assert result.created == len(DEMO_ACCOUNTS)
        assert len(mirror.rows) == len(DEMO_ACCOUNTS)
        assert sorted(r.role.value for r in mirror.rows.values()) == sorted(r.value for r in Role)

    def test_is_idempotent(self) -> None:
        first, auth_service, mirror, link_service = _create_demo_accounts()
        second, _auth_service, _mirror, _link_service = _create_demo_accounts(
            auth_service=auth_service, mirror=mirror, parent_link_service=link_service
        )

        assert first.created == len(DEMO_ACCOUNTS)
        assert second.created == 0
        assert second.skipped == len(DEMO_ACCOUNTS)
        # The second run must not mint a second row for anyone — the docstring
        # has promised "insert-if-absent" since Phase 0.
        assert len(mirror.rows) == len(DEMO_ACCOUNTS)
        assert first.accounts == second.accounts

    def test_mirrors_each_account_with_its_declared_role(self) -> None:
        _result, _auth_service, mirror, _link_service = _create_demo_accounts()

        by_email = {row.email: row for row in mirror.rows.values()}
        for account in DEMO_ACCOUNTS:
            assert by_email[account.email].role is account.role
            assert by_email[account.email].display_name == account.display_name

    def test_recovers_when_gotrue_has_the_user_but_the_mirror_does_not(self) -> None:
        # `supabase db reset` drops both, but a wiped *app* schema (or a failed
        # first run) leaves GoTrue holding the credential while public.users is
        # empty — signup then fails 422 forever and the seeder is stuck.
        gotrue = FakeGoTrueBackend()
        teacher = next(a for a in DEMO_ACCOUNTS if a.role is Role.teacher)
        gotrue.admin_create_user(teacher.email, DEMO_PASSWORD, teacher.role.value, None)

        result, _auth_service, mirror, _link_service = _create_demo_accounts(gotrue=gotrue)

        assert result.created == len(DEMO_ACCOUNTS)
        recovered = next(r for r in mirror.rows.values() if r.email == teacher.email)
        # The important half: `AuthService.login` falls back to `student` for an
        # unmirrored user, so a recovery that just logged in would quietly
        # demote the teacher and the demo teacher portal would 403.
        assert recovered.role is Role.teacher

    def test_recovery_branch_stamps_email_verified_for_the_parent(self) -> None:
        """Final review I-2: the 422 recovery branch (GoTrue survives a wiped
        ``public.users``) must stamp ``email_verified_at`` for an account
        :data:`DEMO_ACCOUNTS` declares verified — the demo parent is the only
        such account. Without the stamp, a recovered parent reads
        ``email_verified_at IS NULL``, the exact shape
        ``DemoAccount.email_verified``'s own comment says no real parent
        account ever has, and would then be 403'd by the verified-email
        dependency.
        """
        gotrue = FakeGoTrueBackend()
        parent = next(a for a in DEMO_ACCOUNTS if a.role is Role.parent)
        gotrue.admin_create_user(parent.email, DEMO_PASSWORD, parent.role.value, None)

        result, _auth_service, mirror, _link_service = _create_demo_accounts(gotrue=gotrue)

        assert result.created == len(DEMO_ACCOUNTS)
        recovered = mirror.get_by_email(parent.email)
        assert recovered is not None
        assert recovered.email_verified_at is not None

    def test_demo_parent_is_linked_to_demo_student(self) -> None:
        """The demo parent must be a real, usable fixture, not just an account
        that exists — so ``create_demo_accounts`` links it to the demo student
        the same way a redeemed invite would (D3.11's successor design), never
        leaving a human to link it by hand before the parent portal has
        anything to show.
        """
        result, _auth_service, mirror, link_service = _create_demo_accounts()

        student_account = next(a for a in DEMO_ACCOUNTS if a.role is Role.student)
        parent_account = next(a for a in DEMO_ACCOUNTS if a.role is Role.parent)
        by_email = {row.email: row for row in mirror.rows.values()}
        student_id = by_email[student_account.email].id
        parent_id = by_email[parent_account.email].id

        assert (parent_id, student_id) in link_service.links
        assert result.created == len(DEMO_ACCOUNTS)

    def test_demo_parent_is_created_email_verified(self) -> None:
        """Every parent a real invite redemption creates is stamped
        ``email_verified_at`` at signup (``AuthService.signup``'s
        ``email_verified=True`` branch) — the demo parent must match that
        shape rather than read, uniquely among real parents, as unverified.
        """
        _result, _auth_service, mirror, _link_service = _create_demo_accounts()

        parent_account = next(a for a in DEMO_ACCOUNTS if a.role is Role.parent)
        parent = mirror.get_by_email(parent_account.email)

        assert parent is not None
        assert parent.email_verified_at is not None

    def test_second_run_creates_nothing(self) -> None:
        """A second ``make seed`` must recognise every account rather than
        re-creating any of them, and must not re-link (or duplicate-link) the
        demo parent — the whole point of idempotent seeding (module
        docstring)."""
        _first, auth_service, mirror, link_service = _create_demo_accounts()
        student_account = next(a for a in DEMO_ACCOUNTS if a.role is Role.student)
        parent_account = next(a for a in DEMO_ACCOUNTS if a.role is Role.parent)
        by_email = {row.email: row for row in mirror.rows.values()}
        student_id = by_email[student_account.email].id
        parent_id = by_email[parent_account.email].id

        second, _auth_service, _mirror, _link_service = _create_demo_accounts(
            auth_service=auth_service, mirror=mirror, parent_link_service=link_service
        )

        assert second.created == 0
        assert second.skipped == len(DEMO_ACCOUNTS)
        assert len(mirror.rows) == len(DEMO_ACCOUNTS)
        # Exactly one link after two runs, not two identical entries — proves
        # the seeder recognised the existing link rather than re-linking.
        assert link_service.links == [(parent_id, student_id)]

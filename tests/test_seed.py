"""Tests for the demo/reference seeder (P6.10).

Mostly hermetic: every demo-account test drives the real
:class:`~lemely.auth.service.AuthService` through the same in-memory fakes
``test_auth_service.py`` uses, so what is exercised here is the seeder's own
logic — idempotency, role fidelity, and the two recovery paths — rather than a
mock of it. The seeding *decisions* for reference data live in the pure
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
from datetime import UTC, datetime

import pytest
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
    DEMO_PARENT,
    DEMO_PASSWORD,
    SeedError,
    create_demo_accounts,
    seed_reference_data,
    subjects_to_upsert,
)
from lemely.db.session import dispose_engine
from lemely.runtime.config import Settings
from tests.auth_fakes import FakeGoTrueBackend, FakeUserMirror


class _OutOfBandSms:
    """An SMS provider that really delivers, so ``request_otp`` returns no code.

    Mirrors :class:`~lemely.auth.sms.SmsProvider`'s contract for the real-gateway
    case (D3.16) — the branch the seeder must fail loudly on rather than skip.
    """

    delivers_out_of_band = True

    def send_code(self, phone: str, code: str) -> None:
        return None


def _service(
    *, sms: object | None = None, gotrue: FakeGoTrueBackend | None = None
) -> tuple[AuthService, FakeUserMirror]:
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
        sms=sms or MockSmsProvider(),  # type: ignore[arg-type]
        otp_store=otp_store,
        settings=settings,
    )
    return service, mirror


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
        roles = [a.role for a in DEMO_ACCOUNTS] + [DEMO_PARENT.role]
        assert sorted(r.value for r in roles) == sorted(r.value for r in Role)

    def test_emails_are_unique_and_on_a_reserved_domain(self) -> None:
        emails = [a.email for a in DEMO_ACCOUNTS]
        assert len(set(emails)) == len(emails)
        # .local is reserved (RFC 6762) — a demo credential can never be a real
        # address someone else owns and could receive mail at.
        assert all(e.endswith(".local") for e in emails)


class TestCreateDemoAccounts:
    def test_creates_every_role_on_a_fresh_database(self) -> None:
        service, mirror = _service()

        result = create_demo_accounts(auth_service=service, mirror=mirror)

        assert result.created == len(DEMO_ACCOUNTS) + 1  # + the phone-OTP parent
        assert len(mirror.rows) == len(DEMO_ACCOUNTS) + 1
        assert sorted(r.role.value for r in mirror.rows.values()) == sorted(r.value for r in Role)

    def test_is_idempotent(self) -> None:
        service, mirror = _service()

        first = create_demo_accounts(auth_service=service, mirror=mirror)
        second = create_demo_accounts(auth_service=service, mirror=mirror)

        assert first.created == len(DEMO_ACCOUNTS) + 1
        assert second.created == 0
        assert second.skipped == len(DEMO_ACCOUNTS) + 1
        # The second run must not mint a second row for anyone — the docstring
        # has promised "insert-if-absent" since Phase 0.
        assert len(mirror.rows) == len(DEMO_ACCOUNTS) + 1
        assert first.accounts == second.accounts

    def test_mirrors_each_account_with_its_declared_role(self) -> None:
        service, mirror = _service()

        create_demo_accounts(auth_service=service, mirror=mirror)

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
        service, mirror = _service(gotrue=gotrue)

        result = create_demo_accounts(auth_service=service, mirror=mirror)

        assert result.created == len(DEMO_ACCOUNTS) + 1
        recovered = next(r for r in mirror.rows.values() if r.email == teacher.email)
        # The important half: `AuthService.login` falls back to `student` for an
        # unmirrored user, so a recovery that just logged in would quietly
        # demote the teacher and the demo teacher portal would 403.
        assert recovered.role is Role.teacher

    def test_refuses_to_skip_the_parent_when_the_otp_cannot_be_read(self) -> None:
        service, mirror = _service(sms=_OutOfBandSms())

        with pytest.raises(SeedError, match="out of band"):
            create_demo_accounts(auth_service=service, mirror=mirror)

    def test_parent_is_reachable_by_the_documented_phone(self) -> None:
        service, mirror = _service()

        create_demo_accounts(auth_service=service, mirror=mirror)

        parent = mirror.get_by_phone(DEMO_PARENT.phone)
        assert parent is not None
        assert parent.role is Role.parent

    def test_parent_gets_the_declared_display_name(self) -> None:
        """P6.10: `verify_otp` mirrors a row with no display name, so
        `DEMO_PARENT.display_name` was declared and applied nowhere — the four
        password roles answered /api/me/profile with their demo names and the
        parent answered `displayName: null`.
        """
        service, mirror = _service()

        create_demo_accounts(auth_service=service, mirror=mirror)

        parent = mirror.get_by_phone(DEMO_PARENT.phone)
        assert parent is not None
        assert parent.display_name == DEMO_PARENT.display_name

    def test_a_nameless_parent_from_an_earlier_seed_is_backfilled(self) -> None:
        """The recognise path applies it too, so a database seeded before the fix
        is corrected by the next `make seed` instead of staying nameless.
        """
        service, mirror = _service()
        create_demo_accounts(auth_service=service, mirror=mirror)
        parent = mirror.get_by_phone(DEMO_PARENT.phone)
        assert parent is not None
        parent.display_name = None

        result = create_demo_accounts(auth_service=service, mirror=mirror)

        assert result.created == 0  # recognised, not recreated
        refreshed = mirror.get_by_phone(DEMO_PARENT.phone)
        assert refreshed is not None
        assert refreshed.display_name == DEMO_PARENT.display_name

"""Hermetic tests for the demo/reference seeder (P6.10).

No Postgres and no GoTrue: every test drives the real
:class:`~lemely.auth.service.AuthService` through the same in-memory fakes
``test_auth_service.py`` uses, so what is exercised here is the seeder's own
logic — idempotency, role fidelity, and the two recovery paths — rather than a
mock of it.

The DB-touching halves (``seed_reference_data``/``seed_demo_accounts``) are thin
wrappers that open a session and delegate to the functions tested below; the
seeding *decisions* all live in the pure/injected layer on purpose, because a
seeder whose correctness can only be checked against a live stack is a seeder
nobody checks.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime

import pytest

from lemely.auth.otp import OtpStore
from lemely.auth.service import AuthService
from lemely.auth.sms import MockSmsProvider
from lemely.db.models.enums import Role
from lemely.db.seed import (
    DEMO_ACCOUNTS,
    DEMO_PARENT,
    DEMO_PASSWORD,
    DEMO_SUBJECTS,
    SeedError,
    create_demo_accounts,
    subjects_to_insert,
)
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


class TestSubjectsToInsert:
    def test_inserts_every_subject_into_an_empty_database(self) -> None:
        assert subjects_to_insert(set()) == list(DEMO_SUBJECTS)

    def test_inserts_nothing_when_all_present(self) -> None:
        assert subjects_to_insert({s.code for s in DEMO_SUBJECTS}) == []

    def test_inserts_only_the_missing_ones(self) -> None:
        missing = subjects_to_insert({"0625"})
        assert [s.code for s in missing] == ["0580", "0606"]

    def test_reference_subjects_are_the_three_the_product_supports(self) -> None:
        # The corpus, the accuracy harness and the syllabus taxonomy are all
        # 0580/0606/0625; a fourth code here would be a claim of support that
        # nothing else in the build backs.
        assert {s.code for s in DEMO_SUBJECTS} == {"0580", "0606", "0625"}


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

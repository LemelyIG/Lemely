"""Catalogue defaults, current-version lookups and signup grants (Task 4)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from lemely.core.metered_actions import ACTION_SPECS, MeteredAction
from lemely.db.billing_repo import active_catalogue
from lemely.db.models.billing import CreditPack, PlanAudience
from lemely.db.models.enums import Role
from lemely.db.models.usage import (
    EstimatorInputKind,
    GrantKind,
    UsageEstimator,
    UsageGrant,
    UsageRate,
)
from lemely.db.usage_catalogue_repo import (
    SIGNUP_STUDENT_PACK,
    SIGNUP_TEACHER_PACK,
    TEACHER_SIGNUP_VALIDITY,
    current_estimator,
    current_rate_version,
    ensure_usage_catalogue,
    grant_signup_allowance,
)
from tests.usage_helpers import NOW, seed_user

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker


def test_ensure_inserts_every_default_once(migrated_sessionmaker: sessionmaker[Session]) -> None:
    with migrated_sessionmaker.begin() as session:
        ensure_usage_catalogue(session, now=NOW)
    with migrated_sessionmaker.begin() as session:
        assert ensure_usage_catalogue(session, now=NOW) == 0
    with migrated_sessionmaker() as session:
        actions = {a.value for a in MeteredAction}
        assert (
            set(session.scalars(select(UsageRate.action).where(UsageRate.version == 1))) >= actions
        )
        assert (
            set(session.scalars(select(UsageEstimator.action).where(UsageEstimator.version == 1)))
            >= actions
        )
        packs = {p.code: p for p in session.scalars(select(CreditPack))}
        assert packs[SIGNUP_STUDENT_PACK].units == 250
        assert packs[SIGNUP_TEACHER_PACK].units == 2000
        assert packs[SIGNUP_STUDENT_PACK].is_active is False
        assert packs[SIGNUP_STUDENT_PACK].price_minor == 0
        assert packs[SIGNUP_TEACHER_PACK].is_active is False
        assert packs[SIGNUP_TEACHER_PACK].price_minor == 0


def test_ensure_is_safe_when_two_callers_race(migrated_sessionmaker: sessionmaker[Session]) -> None:
    def run() -> int:
        with migrated_sessionmaker.begin() as session:
            return ensure_usage_catalogue(session, now=NOW)

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = [f.result() for f in [pool.submit(run) for _ in range(4)]]
    assert all(r >= 0 for r in results)
    with migrated_sessionmaker() as session:
        for model in (UsageRate, UsageEstimator):
            total = session.scalar(select(func.count()).select_from(model))
            distinct = session.scalar(
                select(func.count(func.distinct(model.action))).where(model.version == 1)
            )
            assert total == distinct == len(MeteredAction)
        packs = session.scalar(
            select(func.count())
            .select_from(CreditPack)
            .where(CreditPack.code.in_([SIGNUP_STUDENT_PACK, SIGNUP_TEACHER_PACK]))
        )
        assert packs == 2


def test_ensure_never_overwrites_an_admin_edit(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    with migrated_sessionmaker.begin() as session:
        ensure_usage_catalogue(session, now=NOW)
        pack = session.scalars(
            select(CreditPack).where(CreditPack.code == SIGNUP_STUDENT_PACK)
        ).one()
        pack.units = 999
    with migrated_sessionmaker.begin() as session:
        assert ensure_usage_catalogue(session, now=NOW) == 0
        pack = session.scalars(
            select(CreditPack).where(CreditPack.code == SIGNUP_STUDENT_PACK)
        ).one()
        assert pack.units == 999


def test_signup_packs_stay_out_of_the_public_catalogue(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    with migrated_sessionmaker.begin() as session:
        ensure_usage_catalogue(session, now=NOW)
    with migrated_sessionmaker() as session:
        for audience in PlanAudience:
            _tiers, packs = active_catalogue(session, audience=audience)
            codes = {p.code for p in packs}
            assert SIGNUP_STUDENT_PACK not in codes
            assert SIGNUP_TEACHER_PACK not in codes


def test_lookups_seed_lazily_and_return_the_defaults(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    with migrated_sessionmaker.begin() as session:
        params = current_estimator(session, MeteredAction.MARK_QUIZ, now=NOW)
        version = current_rate_version(session, MeteredAction.MARK_QUIZ, now=NOW)
    assert params == ACTION_SPECS[MeteredAction.MARK_QUIZ].default_estimator
    assert version == 1


def test_an_admin_version_wins_once_effective(migrated_sessionmaker: sessionmaker[Session]) -> None:
    with migrated_sessionmaker.begin() as session:
        ensure_usage_catalogue(session, now=NOW)
        session.add(
            UsageEstimator(
                version=2,
                action="mark_paper",
                input_kind=EstimatorInputKind.none,
                base_low=50,
                base_high=90,
                per_input_low=0,
                per_input_high=0,
                effective_from=NOW - timedelta(hours=1),
            )
        )
        session.add(
            UsageEstimator(
                version=3,
                action="mark_paper",
                input_kind=EstimatorInputKind.none,
                base_low=1,
                base_high=2,
                per_input_low=0,
                per_input_high=0,
                effective_from=NOW + timedelta(days=1),
            )
        )
        session.add(
            UsageRate(
                version=2,
                action="mark_paper",
                units_per_usd=2000,
                effective_from=NOW - timedelta(hours=1),
            )
        )
    with migrated_sessionmaker.begin() as session:
        params = current_estimator(session, MeteredAction.MARK_PAPER, now=NOW)
        assert (params.version, params.base_low, params.base_high) == (2, 50, 90)
        assert current_rate_version(session, MeteredAction.MARK_PAPER, now=NOW) == 2
        # Re-running the seed must not demote the admin's version.
        assert ensure_usage_catalogue(session, now=NOW) == 0
        assert current_rate_version(session, MeteredAction.MARK_PAPER, now=NOW) == 2


def test_student_signup_is_a_hidden_one_time_allowance(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    student = seed_user(migrated_sessionmaker, Role.student)
    with migrated_sessionmaker.begin() as session:
        first = grant_signup_allowance(session, user_id=student, role=Role.student, now=NOW)
    with migrated_sessionmaker.begin() as session:
        grant_signup_allowance(session, user_id=student, role=Role.student, now=NOW)
    assert first is not None
    with migrated_sessionmaker() as session:
        grants = list(
            session.scalars(select(UsageGrant).where(UsageGrant.owner_user_id == student))
        )
    assert len(grants) == 1
    assert grants[0].kind is GrantKind.signup
    assert grants[0].visible is False
    assert grants[0].expires_at is None
    assert grants[0].units == 250


def test_teacher_signup_is_visible_credits_for_thirty_days(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    teacher = seed_user(migrated_sessionmaker, Role.teacher)
    with migrated_sessionmaker.begin() as session:
        grant = grant_signup_allowance(session, user_id=teacher, role=Role.teacher, now=NOW)
        assert grant is not None
        assert grant.visible is True
        assert grant.units == 2000
        assert grant.expires_at == NOW + TEACHER_SIGNUP_VALIDITY


def test_other_roles_and_a_zeroed_pack_get_nothing(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    parent = seed_user(migrated_sessionmaker, Role.parent)
    student = seed_user(migrated_sessionmaker, Role.student)
    with migrated_sessionmaker.begin() as session:
        assert grant_signup_allowance(session, user_id=parent, role=Role.parent, now=NOW) is None
        ensure_usage_catalogue(session, now=NOW)
        pack = session.scalars(
            select(CreditPack).where(CreditPack.code == SIGNUP_STUDENT_PACK)
        ).one()
        pack.units = 0
    with migrated_sessionmaker.begin() as session:
        assert grant_signup_allowance(session, user_id=student, role=Role.student, now=NOW) is None
    with migrated_sessionmaker() as session:
        count = session.scalar(
            select(func.count())
            .select_from(UsageGrant)
            .where(UsageGrant.owner_user_id.in_([parent, student]))
        )
    assert count == 0


def test_catalogue_effective_from_predates_any_job(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    with migrated_sessionmaker.begin() as session:
        ensure_usage_catalogue(session, now=NOW)
        latest = session.scalar(
            select(func.max(UsageRate.effective_from)).where(UsageRate.version == 1)
        )
    assert latest is not None
    assert latest <= datetime(2026, 1, 1, tzinfo=UTC)

"""Migration 0055_subscription_periods (Paymob billing Phase 05, spec §4.3).

Names come from the ORM (``lemely/db/models/billing.py``), so the migration is compared with an
independent declaration. Per index R10 this file asserts only that 0055 is in the history and
round-trips; it never asserts that 0055 is the head.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.script import ScriptDirectory

from lemely.db.base import Base
from lemely.db.models import import_all_models
from lemely.db.models.billing import (
    LIVE_SUBSCRIPTION_STATUSES,
    PLAN_LIVE_STATUSES,
    PaymentPurpose,
    PlanAudience,
    PlanTier,
    Subscription,
)
from lemely.db.models.enums import Role, SubscriptionStatus
from lemely.db.models.users import User
from lemely.db.teacher_team_repo import LIVE_PLAN_STATUSES
from tests.team_db import team_database
from tests.test_migration_tutoring_enums import (
    column_names,
    current_revision,
    enum_labels,
    object_names,
    upgrade_head,
)
from tests.test_migration_usage_ledger import schema_dump

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.orm import Session, sessionmaker

import_all_models()

REVISION = "0055_subscription_periods"
DOWN_REVISION = "0054_teacher_team"
TABLE = "subscription_periods"
#: Owned by 0053 (index R8); 0055 must leave it alone.
PHASE_02_LIVE_INDEX = "uq_subscriptions_one_live_per_user"
GRANT_FK = "fk_usage_grants_subscription_period_id_subscription_periods"
NEW_SUBSCRIPTION_COLUMNS = {"paymob_amount_minor", "paymob_cancelled_at"}

#: Every table 0055 creates or alters, for the parity check.
PARITY_TABLES = (
    "subscription_periods",
    "subscriptions",
    "usage_grants",
    "notification_preferences",
)
PARITY_ENUMS = ("notificationtype",)


def _orm_names() -> set[str]:
    table = Base.metadata.tables[TABLE]
    names = {str(constraint.name) for constraint in table.constraints}
    return names | {str(index.name) for index in table.indexes}


def _user(sm: sessionmaker[Session]) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=Role.student, display_name="s"))
    return uid


def _tier(sm: sessionmaker[Session]) -> uuid.UUID:
    tid = uuid.uuid4()
    with sm.begin() as session:
        session.add(
            PlanTier(
                id=tid,
                code=f"t-{tid.hex[:8]}",
                name="Student monthly",
                price_minor=10_000,
                currency="EGP",
                audience=PlanAudience.student,
            )
        )
    return tid


def _sub(
    sm: sessionmaker[Session],
    user: uuid.UUID,
    tier: uuid.UUID,
    status: SubscriptionStatus,
    *,
    payer: uuid.UUID | None = None,
) -> uuid.UUID:
    sid = uuid.uuid4()
    with sm.begin() as session:
        session.add(
            Subscription(
                id=sid, user_id=user, plan_tier_id=tier, status=status, payer_user_id=payer
            )
        )
    return sid


def _payment(sm: sessionmaker[Session], user: uuid.UUID, tier: uuid.UUID) -> uuid.UUID:
    """A ``subscription_first`` payment row, inserted raw (the migrated schema has no ORM)."""
    pid = uuid.uuid4()
    with sm.begin() as session:
        session.execute(
            sa.text(
                "INSERT INTO payments (id, payer_user_id, beneficiary_user_id, purpose, "
                "plan_tier_id, amount_minor, special_reference) "
                "VALUES (:id, :u, :u, :purpose, :tier, 10000, :ref)"
            ),
            {
                "id": pid,
                "u": user,
                "purpose": PaymentPurpose.subscription_first.value,
                "tier": tier,
                "ref": str(pid),
            },
        )
    return pid


_INSERT_PERIOD = sa.text(
    "INSERT INTO subscription_periods (id, subscription_id, period_start, period_end, payment_id) "
    "VALUES (:id, :s, :a, :b, :p)"
)


def _period(
    sm: sessionmaker[Session],
    subscription: uuid.UUID,
    start: datetime,
    end: datetime,
    *,
    payment: uuid.UUID | None = None,
) -> uuid.UUID:
    period_id = uuid.uuid4()
    with sm.begin() as session:
        session.execute(
            _INSERT_PERIOD,
            {"id": period_id, "s": subscription, "a": start, "b": end, "p": payment},
        )
    return period_id


_INSERT_GRANT = sa.text(
    "INSERT INTO usage_grants (owner_user_id, kind, visible, priority, units, "
    "effective_at, idempotency_key, subscription_period_id) "
    "VALUES (:u, 'period_allowance', false, 10, 100, :at, :key, :period)"
)


def test_orm_declares_the_six_named_objects() -> None:
    assert _orm_names() == {
        "pk_subscription_periods",
        "fk_subscription_periods_subscription_id_subscriptions",
        "fk_subscription_periods_payment_id_payments",
        "uq_subscription_periods_subscription_id_period_start",
        "uq_subscription_periods_payment_id",
        "ck_subscription_periods_period_order",
    }


def test_revision_chains_from_0054_and_is_in_the_history() -> None:
    script_dir = ScriptDirectory.from_config(Config("alembic.ini"))
    revision = script_dir.get_revision(REVISION)
    assert revision is not None
    assert revision.down_revision == DOWN_REVISION
    assert len(REVISION) <= 32  # alembic_version.version_num is varchar(32)
    history = {rev.revision for rev in script_dir.walk_revisions()}
    assert REVISION in history  # never "is the head" (index R10)


def test_plan_live_statuses_match_phase_03() -> None:
    """One definition of "a plan is in force": Phase 03's constant and the billing one agree."""
    assert PLAN_LIVE_STATUSES == LIVE_PLAN_STATUSES
    assert (SubscriptionStatus.active, SubscriptionStatus.past_due) == PLAN_LIVE_STATUSES
    # A pending checkout is live for the one-per-user index but is not a plan in force.
    assert set(PLAN_LIVE_STATUSES) < set(LIVE_SUBSCRIPTION_STATUSES)


def test_named_objects_present(migrated_sessionmaker: sessionmaker[Session]) -> None:
    with migrated_sessionmaker() as session:
        assert object_names(session, [TABLE]) == _orm_names()
        # 0055 leaves Phase 02's index alone (index R8).
        assert PHASE_02_LIVE_INDEX in object_names(session, ["subscriptions"])
        assert GRANT_FK in object_names(session, ["usage_grants"])
        assert column_names(session, "subscriptions") >= NEW_SUBSCRIPTION_COLUMNS


def test_migrated_schema_equals_the_create_all_schema(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    """Parity: the migration builds what the models declare, definition by definition.

    Covers every table 0055 creates or alters, plus the ``notificationtype`` labels (in order),
    against a database built by ``create_all``.
    """
    with migrated_sessionmaker() as session:
        migrated = schema_dump(session, PARITY_TABLES, enums=PARITY_ENUMS)
    with team_database() as orm_sessionmaker, orm_sessionmaker() as session:
        orm = schema_dump(session, PARITY_TABLES, enums=PARITY_ENUMS)
    # Non-vacuous: every section that applies found something to compare.
    for section in ("columns", "constraints", "indexes", "enums"):
        assert migrated[section], section
    for section, rows in migrated.items():
        assert rows == orm[section], section


def test_period_order_and_uniqueness(migrated_sessionmaker: sessionmaker[Session]) -> None:
    sm = migrated_sessionmaker
    sid = _sub(sm, _user(sm), _tier(sm), SubscriptionStatus.active)
    start = datetime(2026, 11, 10, tzinfo=UTC)
    _period(sm, sid, start, datetime(2026, 12, 10, tzinfo=UTC))
    with (
        pytest.raises(sa.exc.IntegrityError, match="uq_subscription_periods_subscription_id"),
        sm.begin() as session,
    ):
        session.execute(
            _INSERT_PERIOD,
            {
                "id": uuid.uuid4(),
                "s": sid,
                "a": start,
                "b": datetime(2026, 12, 11, tzinfo=UTC),
                "p": None,
            },
        )
    with (
        pytest.raises(sa.exc.IntegrityError, match="ck_subscription_periods_period_order"),
        sm.begin() as session,
    ):
        session.execute(
            _INSERT_PERIOD,
            {
                "id": uuid.uuid4(),
                "s": sid,
                "a": datetime(2027, 1, 1, tzinfo=UTC),
                "b": start,
                "p": None,
            },
        )


def test_one_payment_pays_for_one_period(migrated_sessionmaker: sessionmaker[Session]) -> None:
    sm = migrated_sessionmaker
    user, tier = _user(sm), _tier(sm)
    sid = _sub(sm, user, tier, SubscriptionStatus.active, payer=user)
    payment = _payment(sm, user, tier)
    _period(
        sm,
        sid,
        datetime(2026, 11, 10, tzinfo=UTC),
        datetime(2026, 12, 10, tzinfo=UTC),
        payment=payment,
    )
    with (
        pytest.raises(sa.exc.IntegrityError, match="uq_subscription_periods_payment_id"),
        sm.begin() as session,
    ):
        session.execute(
            _INSERT_PERIOD,
            {
                "id": uuid.uuid4(),
                "s": sid,
                "a": datetime(2026, 12, 10, tzinfo=UTC),
                "b": datetime(2027, 1, 10, tzinfo=UTC),
                "p": payment,
            },
        )


def test_usage_grant_period_fk_enforced(migrated_sessionmaker: sessionmaker[Session]) -> None:
    """A grant naming an unknown period is refused: the column is a real foreign key now."""
    sm = migrated_sessionmaker
    user = _user(sm)
    with pytest.raises(sa.exc.IntegrityError, match=GRANT_FK), sm.begin() as session:
        session.execute(
            _INSERT_GRANT,
            {
                "u": user,
                "at": datetime(2026, 11, 10, tzinfo=UTC),
                "key": "fk-probe",
                "period": uuid.uuid4(),
            },
        )


def test_period_grant_fk_restricts_deleting_the_period(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    """``RESTRICT`` is stated: a period that backs a grant cannot be deleted."""
    with migrated_sessionmaker() as session:
        definition = session.execute(
            sa.text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = :n"),
            {"n": GRANT_FK},
        ).scalar_one()
    assert "ON DELETE RESTRICT" in definition


def test_billing_notification_type_and_toggle(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    with migrated_sessionmaker() as session:
        assert "billing" in enum_labels(session, "notificationtype")
        default = session.execute(
            sa.text(
                "SELECT column_default, is_nullable FROM information_schema.columns "
                "WHERE table_name = 'notification_preferences' AND column_name = 'billing'"
            )
        ).one()
        assert tuple(default) == ("true", "NO")


def test_phase_02_index_ignores_manual_rows(migrated_sessionmaker: sessionmaker[Session]) -> None:
    """Paid rows collide; payer-less (manual) rows do not. Manual rows are guarded in admin_repo."""
    sm = migrated_sessionmaker
    user, tier = _user(sm), _tier(sm)
    _sub(sm, user, tier, SubscriptionStatus.active, payer=user)
    _sub(sm, user, tier, SubscriptionStatus.active, payer=None)  # manual: no collision
    with pytest.raises(sa.exc.IntegrityError, match=PHASE_02_LIVE_INDEX):
        _sub(sm, user, tier, SubscriptionStatus.past_due, payer=user)


def test_downgrade_refuses_while_a_period_grant_exists(
    migrated_sessionmaker_with_downgrade: tuple[sessionmaker[Session], Callable[[str], None]],
) -> None:
    """A period grant cannot be deleted (ledger entries RESTRICT) or detached silently.

    Dropping ``subscription_periods`` would orphan the link, so the downgrade stops and the
    revision does not move (a downgrade is one transaction, so a later revision's steps roll
    back with it). It never nulls ledger links (0054 precedent).
    """
    sm, downgrade_to = migrated_sessionmaker_with_downgrade
    with sm() as session:
        revision_before = current_revision(session)
    user, tier = _user(sm), _tier(sm)
    sid = _sub(sm, user, tier, SubscriptionStatus.active, payer=user)
    period = _period(
        sm, sid, datetime(2026, 11, 10, tzinfo=UTC), datetime(2026, 12, 10, tzinfo=UTC)
    )
    with sm.begin() as session:
        session.execute(
            _INSERT_GRANT,
            {
                "u": user,
                "at": datetime(2026, 11, 10, tzinfo=UTC),
                "key": f"period:{period}",
                "period": period,
            },
        )

    with pytest.raises(RuntimeError, match="period grant"):
        downgrade_to(DOWN_REVISION)

    with sm() as session:
        assert current_revision(session) == revision_before
        assert TABLE in {
            row[0]
            for row in session.execute(
                sa.text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            )
        }
        assert GRANT_FK in object_names(session, ["usage_grants"])
        left = session.execute(
            sa.text("SELECT count(*) FROM usage_grants WHERE subscription_period_id = :p"),
            {"p": period},
        ).scalar_one()
        assert left == 1


def test_upgrade_downgrade_upgrade_round_trip(
    migrated_sessionmaker_with_downgrade: tuple[sessionmaker[Session], Callable[[str], None]],
) -> None:
    sm, downgrade_to = migrated_sessionmaker_with_downgrade
    user, tier = _user(sm), _tier(sm)
    other = _user(sm)
    with sm.begin() as session:
        session.execute(
            sa.text(
                "INSERT INTO notifications (user_id, type, title) VALUES "
                "(:u, 'billing', 'Payment received'), (:u, 'grade_ready', 'Graded')"
            ),
            {"u": user},
        )
    # A live paid subscription: its row survives the downgrade, its two columns do not.
    _sub(sm, other, tier, SubscriptionStatus.active, payer=other)

    downgrade_to(DOWN_REVISION)

    with sm() as session:
        assert current_revision(session) == DOWN_REVISION
        assert object_names(session, [TABLE]) == set()
        assert PHASE_02_LIVE_INDEX in object_names(session, ["subscriptions"])  # untouched
        assert GRANT_FK not in object_names(session, ["usage_grants"])
        assert NEW_SUBSCRIPTION_COLUMNS.isdisjoint(column_names(session, "subscriptions"))
        assert "billing" not in column_names(session, "notification_preferences")
        # Billing notices are deleted (older code cannot load them); others survive.
        types = set(
            session.execute(
                sa.text("SELECT type::text FROM notifications WHERE user_id = :u"), {"u": user}
            ).scalars()
        )
        assert types == {"grade_ready"}
        assert session.execute(sa.text("SELECT count(*) FROM subscriptions")).scalar_one() == 1

    # The fixture keeps LEMELY_DATABASE__URL pointed at the throwaway database for the whole
    # test, so ``upgrade_head`` migrates that database.
    upgrade_head()

    with sm() as session:
        # Never asserts "is the head" (index R10): later phases may add revisions.
        assert object_names(session, [TABLE]) == _orm_names()
        assert GRANT_FK in object_names(session, ["usage_grants"])
        assert column_names(session, "subscriptions") >= NEW_SUBSCRIPTION_COLUMNS
        assert "billing" in column_names(session, "notification_preferences")
        assert "billing" in enum_labels(session, "notificationtype")

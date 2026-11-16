"""Database helpers shared by the admin billing test modules (Phase 07).

Not a test module (no ``test_`` prefix). Each test module defines its own
``billing_db`` (module scope) and ``sm`` (per test) fixtures from these helpers:

    @pytest.fixture(scope="module")
    def billing_db() -> Iterator[sessionmaker[Session]]:
        with billing_database() as factory:
            yield factory

    @pytest.fixture
    def sm(billing_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
        yield from emptied_after(billing_db)

``NOW`` is the fixed clock every service under test is given. Seeds always pass
explicit instants: a server-default ``now()`` would be the real clock, not ``NOW``.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.db.admin_billing_repo import AdminCatalogueService
from lemely.db.admin_customer_repo import AdminCustomerService
from lemely.db.base import Base
from lemely.db.models import import_all_models
from lemely.db.models.admin_audit import AdminAuditLog
from lemely.db.models.billing import (
    CreditPack,
    Payment,
    PaymentPurpose,
    PaymentStatus,
    PlanAudience,
    PlanTier,
    Subscription,
    SubscriptionPeriod,
)
from lemely.db.models.enums import PlanInterval, Role, SubscriptionStatus
from lemely.db.models.usage import GrantKind, UsageJob, UsageRate
from lemely.db.models.users import User
from lemely.db.usage_ledger_repo import UsageLedger
from lemely.runtime.config import DatabaseSettings, PaymobSettings
from lemely.web.deps import AuthContext, get_auth_context
from lemely.web.deps_admin_billing import get_admin_catalogue_service, get_admin_customer_service
from tests.paymob_fixtures import PAYMOB_SETTINGS
from tests.paymob_fixtures import FakePaymobClient as BaseFakePaymobClient
from tests.tutoring_app import app_with_routers

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping
    from decimal import Decimal

    from lemely.core.usage_types import Payer

import_all_models()

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)

# Tables with no foreign key to ``users`` that the admin billing tests write directly. A
# ``TRUNCATE ... CASCADE`` on these also empties every table that references them:
# ``admin_audit_log``, ``payment_refunds`` and ``payments`` through ``users``,
# ``signup_allowance_off_periods`` through ``credit_packs``, ``usage_job_model_costs`` through
# the jobs of a user, ``plan_tier_terms`` through ``plan_tiers``. ``billing_settings`` and
# ``llm_price_overrides`` reference ``users`` (``updated_by``) so a cascade reaches them too;
# they are listed to be explicit.
_ROOT_TABLES = (
    "users",
    "plan_tiers",
    "credit_packs",
    "usage_rates",
    "usage_estimators",
    "job_runs",
    "paymob_webhook_failures",
    "paymob_events",
    "billing_settings",
    "llm_price_overrides",
)


@contextmanager
def billing_database() -> Iterator[sessionmaker[Session]]:
    """A fresh ``create_all`` database for one test module, dropped afterwards.

    Skips the test module when no local Postgres is reachable.
    """
    base = make_url(DatabaseSettings().url)
    admin = create_engine(base.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect():
            pass
    except OperationalError:
        admin.dispose()
        pytest.skip("local Postgres not reachable")
    name = f"lemely_test_{uuid.uuid4().hex[:12]}"
    with admin.connect() as conn:
        conn.execute(sa.text(f'CREATE DATABASE "{name}"'))
    engine = create_engine(base.set(database=name))
    try:
        Base.metadata.create_all(engine)
        yield sessionmaker(bind=engine, expire_on_commit=False, future=True)
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


def emptied_after(factory: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    """Yield ``factory``, then empty every table the admin billing tests write.

    ``billing_settings`` is emptied with the rest and its single row inserted again, as
    ``create_all`` and the migration leave it: a settings read never finds the table empty.
    """
    yield factory
    with factory.begin() as session:
        session.execute(sa.text(f"TRUNCATE {', '.join(_ROOT_TABLES)} CASCADE"))
        session.execute(sa.text("INSERT INTO billing_settings (id) VALUES (1)"))


def add_user(
    factory: sessionmaker[Session],
    role: Role | str = Role.student,
    *,
    email: str | None = None,
    display_name: str | None = None,
) -> uuid.UUID:
    """Insert one user and return its id."""
    uid = uuid.uuid4()
    with factory.begin() as session:
        session.add(
            User(
                id=uid,
                email=email or f"{uid}@example.com",
                role=Role(role),
                display_name=display_name,
                created_at=NOW,
            )
        )
    return uid


class FakePaymobClient(BaseFakePaymobClient):
    """Phase 02's scripted client plus the admin calls: each is recorded in ``calls``.

    A scripted result that is an exception instance is raised instead of returned
    (``None`` means the default). ``create_plan`` echoes its arguments with the next id.
    """

    def __init__(self) -> None:
        super().__init__(PAYMOB_SETTINGS)
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.next_plan_id = 9001
        self.create_plan_result: Mapping[str, Any] | BaseException | None = None
        self.refund_result: Mapping[str, Any] | BaseException = {"id": 555, "success": True}
        self.void_result: Mapping[str, Any] | BaseException = {"id": 556, "success": True}
        self.transaction_result: Mapping[str, Any] | BaseException | None = None
        self.subscription_result: Mapping[str, Any] | BaseException = {}
        self.cancel_result: Mapping[str, Any] | BaseException = {"state": "canceled"}

    @staticmethod
    def _out(result: Any) -> Any:
        if isinstance(result, BaseException):
            raise result
        return result

    def create_plan(self, **kwargs: Any) -> Any:
        self.calls.append(("create_plan", kwargs))
        if self.create_plan_result is not None:
            return self._out(self.create_plan_result)
        plan_id = self.next_plan_id
        self.next_plan_id += 1
        return {"id": plan_id, **kwargs}

    def refund(self, **kwargs: Any) -> Any:
        self.calls.append(("refund", kwargs))
        return self._out(self.refund_result)

    def void(self, **kwargs: Any) -> Any:
        self.calls.append(("void", kwargs))
        return self._out(self.void_result)

    def inquire_by_transaction(self, transaction_id: int) -> Any:
        self.calls.append(("inquire_by_transaction", {"transaction_id": transaction_id}))
        return self._out(self.transaction_result)

    def get_subscription(self, subscription_id: int) -> Any:
        self.calls.append(("get_subscription", {"subscription_id": subscription_id}))
        return self._out(self.subscription_result)

    def cancel_subscription(self, subscription_id: int) -> Any:
        self.calls.append(("cancel_subscription", {"subscription_id": subscription_id}))
        return self._out(self.cancel_result)


def add_plan_tier(
    factory: sessionmaker[Session],
    *,
    code: str = "student_monthly",
    audience: str = "student",
    price_minor: int = 20000,
    interval: PlanInterval = PlanInterval.monthly,
    allowance_units: int = 1000,
    included_seats: int = 0,
    seat_allowance_units: int = 0,
    extra_seat_price_minor: int = 0,
    paymob_plan_id: int | None = None,
    paymob_plan_mode: str | None = None,
    synced_price_minor: int | None = None,
    synced_frequency: int | None = None,
    synced_retrial_days: int | None = None,
) -> uuid.UUID:
    """Insert one active plan tier (its terms version 1 is written by the database trigger)."""
    tier_id = uuid.uuid4()
    with factory.begin() as session:
        session.add(
            PlanTier(
                id=tier_id,
                code=code,
                name=code.replace("_", " ").title(),
                audience=PlanAudience(audience),
                price_minor=price_minor,
                currency="EGP",
                interval=interval,
                allowance_units=allowance_units,
                included_seats=included_seats,
                seat_allowance_units=seat_allowance_units,
                extra_seat_price_minor=extra_seat_price_minor,
                paymob_plan_id=paymob_plan_id,
                paymob_plan_mode=paymob_plan_mode,
                paymob_plan_synced_price_minor=synced_price_minor,
                paymob_plan_synced_frequency=synced_frequency,
                paymob_plan_synced_retrial_days=synced_retrial_days,
                is_active=True,
            )
        )
    return tier_id


def add_credit_pack(
    factory: sessionmaker[Session],
    *,
    code: str = "pack_500",
    units: int = 500,
    price_minor: int = 10000,
) -> uuid.UUID:
    pack_id = uuid.uuid4()
    with factory.begin() as session:
        session.add(
            CreditPack(
                id=pack_id,
                code=code,
                name=code,
                units=units,
                price_minor=price_minor,
                currency="EGP",
                is_active=True,
            )
        )
    return pack_id


def audit_rows(factory: sessionmaker[Session], action: str) -> list[AdminAuditLog]:
    """Every audit row of ``action``, oldest first."""
    with factory() as session:
        return list(
            session.scalars(
                sa.select(AdminAuditLog)
                .where(AdminAuditLog.action == str(action))
                .order_by(AdminAuditLog.created_at, AdminAuditLog.id)
            )
        )


def audit_count(factory: sessionmaker[Session]) -> int:
    """How many audit rows of any action exist."""
    with factory() as session:
        return session.scalar(sa.select(sa.func.count()).select_from(AdminAuditLog)) or 0


def service_overrides(
    factory: sessionmaker[Session],
    paymob: FakePaymobClient,
    paymob_settings: PaymobSettings = PAYMOB_SETTINGS,
) -> dict[Callable[..., object], Callable[[], object]]:
    """Every admin billing service bound to ``factory``, ``paymob`` and ``NOW``.

    Later tasks add their services in their own test modules (DV-2).
    """

    def clock() -> datetime:
        return NOW

    return {
        get_admin_catalogue_service: lambda: AdminCatalogueService(
            factory, paymob, paymob_settings, now=clock
        ),
        get_admin_customer_service: lambda: AdminCustomerService(
            factory, paymob, paymob_settings, now=clock
        ),
    }


def admin_client(
    factory: sessionmaker[Session],
    admin_id: uuid.UUID,
    *,
    paymob: FakePaymobClient | None = None,
    paymob_settings: PaymobSettings = PAYMOB_SETTINGS,
) -> TestClient:
    """A client on the whole app, signed in as ``admin_id`` (a platform admin)."""
    app = app_with_routers()
    app.dependency_overrides.update(
        service_overrides(factory, paymob or FakePaymobClient(), paymob_settings)
    )
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(
        user_id=str(admin_id), role=Role.platform_admin.value
    )
    return TestClient(app)


def add_rate(
    factory: sessionmaker[Session], action: str, units_per_usd: int = 1000, version: int = 1
) -> None:
    with factory.begin() as session:
        session.add(
            UsageRate(
                version=version,
                action=action,
                units_per_usd=units_per_usd,
                effective_from=NOW - timedelta(days=60),
            )
        )


def grant(
    factory: sessionmaker[Session],
    owner: uuid.UUID,
    *,
    units: int,
    kind: GrantKind = GrantKind.adjustment,
    visible: bool = True,
    expires_at: datetime | None = NOW + timedelta(days=300),
    effective_at: datetime = NOW - timedelta(days=1),
    payment_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """Issue a grant through the ledger (so balances and debt repayment stay consistent)."""
    with factory.begin() as session:
        issued = UsageLedger(session).issue_grant(
            owner_user_id=owner,
            kind=kind,
            units=units,
            idempotency_key=f"seed:{uuid.uuid4()}",
            expires_at=expires_at,
            visible=visible,
            effective_at=effective_at,
            payment_id=payment_id,
        )
        return issued.id


def metered_job(
    factory: sessionmaker[Session],
    actor: uuid.UUID,
    payers: list[Payer],
    *,
    action: str = "mark_paper",
    low: int,
    high: int,
    cost: Decimal | None,
    estimator_version: int = 1,
    rate_version: int = 1,
    created_at: datetime = NOW,
) -> uuid.UUID:
    """Reserve and (when ``cost`` is given) settle one job; returns ``usage_jobs.id``.

    ``created_at`` is written afterwards because the row's default is the real clock.
    """
    job_id = uuid.uuid4()
    with factory.begin() as session:
        ledger = UsageLedger(session)
        ledger.reserve(
            job_id=job_id,
            actor_user_id=actor,
            action=action,
            payers=payers,
            estimate_low=low,
            estimate_high=high,
            estimator_version=estimator_version,
            rate_version=rate_version,
            teacher_member_id=None,
            expires_at=created_at + timedelta(minutes=10),
            now=created_at,
        )
        if cost is not None:
            ledger.settle(job_id, actual_cost_usd=cost, now=created_at)
    with factory.begin() as session:
        job = session.scalars(sa.select(UsageJob).where(UsageJob.job_id == job_id)).one()
        job.created_at = created_at
        return job.id


def add_payment(
    factory: sessionmaker[Session],
    *,
    payer: uuid.UUID,
    beneficiary: uuid.UUID | None = None,
    purpose: PaymentPurpose = PaymentPurpose.credit_pack,
    status: PaymentStatus = PaymentStatus.paid,
    amount_minor: int = 10000,
    paid_at: datetime | None = NOW,
    created_at: datetime = NOW - timedelta(minutes=5),
    updated_at: datetime | None = None,
    paymob_order_id: int | None = None,
    paymob_txn_id: int | None = None,
    plan_tier_id: uuid.UUID | None = None,
    credit_pack_id: uuid.UUID | None = None,
    last_callback: dict[str, object] | None = None,
) -> uuid.UUID:
    """One payment. A ``credit_pack`` payment with no pack gets a fresh one (a check demands it)."""
    pid = uuid.uuid4()
    if purpose is PaymentPurpose.credit_pack and credit_pack_id is None:
        credit_pack_id = add_credit_pack(factory, code=f"pack_{pid.hex[:12]}")
    with factory.begin() as session:
        session.add(
            Payment(
                id=pid,
                payer_user_id=payer,
                beneficiary_user_id=beneficiary or payer,
                purpose=purpose,
                status=status,
                amount_minor=amount_minor,
                currency="EGP",
                special_reference=str(pid),
                paymob_order_id=paymob_order_id,
                paymob_txn_id=paymob_txn_id,
                plan_tier_id=plan_tier_id,
                credit_pack_id=credit_pack_id,
                last_callback=last_callback,
                paid_at=paid_at if status is not PaymentStatus.created else None,
                created_at=created_at,
                updated_at=updated_at or created_at,
            )
        )
    return pid


def add_subscription(
    factory: sessionmaker[Session],
    user: uuid.UUID,
    tier: uuid.UUID,
    *,
    status: SubscriptionStatus = SubscriptionStatus.active,
    start: datetime = NOW - timedelta(days=4),
    end: datetime | None = NOW + timedelta(days=26),
    manual: bool = False,
    paymob_subscription_id: int | None = None,
) -> uuid.UUID:
    """A subscription and, when it has a period end, its ``subscription_periods`` row."""
    sid = uuid.uuid4()
    with factory.begin() as session:
        session.add(
            Subscription(
                id=sid,
                user_id=user,
                payer_user_id=user,
                plan_tier_id=tier,
                status=status,
                is_manually_activated=manual,
                current_period_start=start,
                current_period_end=end,
                paymob_subscription_id=paymob_subscription_id,
            )
        )
        session.flush()
        if end is not None:
            session.add(SubscriptionPeriod(subscription_id=sid, period_start=start, period_end=end))
    return sid

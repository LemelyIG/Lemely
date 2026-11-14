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
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.db.admin_billing_repo import AdminCatalogueService
from lemely.db.base import Base
from lemely.db.models import import_all_models
from lemely.db.models.admin_audit import AdminAuditLog
from lemely.db.models.billing import CreditPack, PlanAudience, PlanTier
from lemely.db.models.enums import PlanInterval, Role
from lemely.db.models.users import User
from lemely.runtime.config import DatabaseSettings, PaymobSettings
from lemely.web.deps import AuthContext, get_auth_context
from lemely.web.deps_admin_billing import get_admin_catalogue_service
from tests.paymob_fixtures import PAYMOB_SETTINGS
from tests.paymob_fixtures import FakePaymobClient as BaseFakePaymobClient
from tests.tutoring_app import app_with_routers

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping

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

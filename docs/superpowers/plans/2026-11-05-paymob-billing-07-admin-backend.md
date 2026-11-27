# Paymob billing 07 — admin backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give platform admins an audited API over the whole billing system: catalogue editing, a
customer view with money actions, a payments problem queue, money-and-margin reporting, and
billing health.

**Architecture:** One append-only `admin_audit_log` table, written by one helper (`audited`) inside
the same transaction as every admin money or catalogue change. Four focused services under
`lemely/db/admin_*_repo.py` (catalogue, customers, payments, margin) plus a health service, all
reached through one router `lemely/web/routers/admin_billing.py` (`/api/admin/billing`, gated to
`platform_admin` at router level). Small hooks into Phases 02, 04, 05 and the sweeper record the
facts the reports need (sweeper job runs, HMAC failures, per-model LLM cost, whether a payment's callback ever arrived).

**Tech Stack:** FastAPI, SQLAlchemy 2 (sync), Alembic, Postgres (`create_all` test databases and
`alembic upgrade head` migration tests), pydantic v2, pytest.

**Spec:** `docs/superpowers/specs/2026-11-02-paymob-billing-design.md` §4.7, §6, §7, §8.
**Index (names, files, interfaces):** `docs/superpowers/plans/2026-11-05-paymob-billing-00-index.md`.

## Global Constraints

- Signed commits only, path-scoped: `git add <paths> && git commit -S -m "feat(admin): …" -- <paths>`.
- Run `/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files` and fix every failure before
  each commit. The ruff hook autofixes: re-run it until it passes with no changes, then re-stage.
- Tests: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest --no-cov <touched files> -v`
  (`--no-cov` always: the repo's `--cov-fail-under=70` fails any subset run; index R2). Never run
  the full suite (`make test` or bare `pytest`). When a task adds a module under `lemely/`, also run
  `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest --no-cov tests/architecture -v`.
- Do not push. Do not open PRs.
- Money is integer minor units (piasters, `BIGINT`). Usage is integer units (`BIGINT`). USD LLM
  cost is `Decimal`, stored as `NUMERIC(12, 6)`.
- UUID primary keys with `server_default=sa.text("gen_random_uuid()")`; Postgres enums;
  `TimestampMixin` from `lemely.db.models.enums`.
- `lemely/db/models/*` never imports `lemely.core`.
- Paymob secret key, API key and HMAC secret: server only, never logged, never in a response.
- Every admin endpoint requires `platform_admin` (spec §7). Every admin money or catalogue change
  requires a non-blank reason and writes exactly one `admin_audit_log` row in the same
  transaction (spec §4.7, §8).
- No placeholder code: no `TODO`, no `pass` bodies, no `test.skip`, no stub tests.
- The local Postgres (`supabase start`, `127.0.0.1:54322`) must be running; DB tests skip
  without it, and a skipped test is not a passing test. If a DB test reports `SKIPPED`, start
  Postgres and re-run before claiming the step passes.

---

## Contract deviations

Each item below departs from, or adds to, the index's shared contracts. Reasons given.

1. **Router prefix is `/api/admin/billing`.** The index writes `/admin/billing`; every router in
   this codebase carries the `/api` prefix itself (`lemely/web/routers/admin.py`:
   `APIRouter(prefix="/api", …)`), and Phase 08 calls paths "under the `/api` proxy". Same
   surface, codebase convention.
2. **Route paths follow Phase 08's assumed table (A26–A33)**, which was written before this plan:
   `/tiers`, `/packs`, `/rates`, `/estimators`, `/free-allowances`, `/customers/{id}/grant|adjust|forgive-debt`,
   `/subscriptions/{id}/extend|cancel`, `/payments/{id}/refund|void|reconcile`, `/payments`,
   `/problems`, `/margin`, `/health`. Error bodies are `{"code": …, "message": …}` in `detail`,
   as Phase 08 assumes. One route Phase 08 does not list is added:
   `POST /customers/{user_id}/manual-activation` (complimentary subscriptions, spec §8 "manual
   activation … kept for complimentary accounts"). Phase 08 keeps pending-activation decisions on
   the existing `/api/admin/activations/*` routes; those stay working and now write audit rows
   (deviation 9).
3. **Migration `0057_admin_audit_log` creates more than the audit log**, because the index fixes one
   migration for this phase:
   - `job_runs` — the sweeper records nothing today (`run_jobs` in
     `lemely/web/scheduled_notifications.py` only logs a failure). Health needs last run and
     outcome per job.
   - `paymob_webhook_failures` — Phase 02 returns 401 on an HMAC mismatch and logs it; nothing is
     stored, and `paymob_events` holds verified callbacks only (spec §4.2). The problem queue and
     the webhook error rate need a count. A separate table keeps `paymob_events` meaning
     "verified".
   - `payment_refunds` — spec §6 requires "insert our own … refund row before calling Paymob";
     no phase creates one.
   - `usage_job_model_costs` — `usage_jobs` (spec §4.5) has no model column, and one job can call
     several models (extraction on Gemini, marking on Claude), so a single column would misreport.
     One row per (job, model).
   - `payments.callback_received_at` — "missing callback" means paid but Paymob never called us.
     Phase 02 records an identical `paymob_events` row whether a transaction arrives by callback or
     by reconcile inquiry, and a later callback is then a dedupe no-op, so the event table cannot
     tell the two apart. The callback entry point stamps this column, duplicates included.
   - `plan_tiers.paymob_plan_synced_price_minor` and `paymob_plan_synced_frequency` — the drift
     warning compares the tier with what was last sent to Paymob; `PaymobClient` has no "get plan".
   - Five indexes on Phase 01/02 tables for the margin and payments queries.
4. **Phase 02 hooks (Task 2):** `BillingService.reconcile_payment_now(payment_id, *, now) ->
   PaymentStatus` wraps Phase 02's existing private `_reconcile_one(payment, *, now)` for one
   locked payment; `apply_transaction_callback` stamps `payments.callback_received_at` for the
   payment its `merchant_order_id` names (before the dedupe check, so a callback after an inquiry
   still counts); the webhook routes record HMAC failures through `record_webhook_failure`.
   `PaymentNotFoundError(BillingError)` is added.
5. **Phase 04 hooks:** a second contextvar accumulator `lemely/io/llm/model_costs.py`
   (`model_cost_scope`, `record_model_cost`) sits beside Phase 04's `cost_meter`, fed next to the
   one `record_llm_cost(usd_decimal(usd))` call in `GeminiClient._record_spend`, and the metered
   job's `run()` persists it at settle (Task 3).
5a. **Free allowances follow Phase 04 deviation 7:** the student free allowance and teacher signup
   credits are the `credit_packs` rows `signup_student` / `signup_teacher`. `PUT /free-allowances`
   edits their `units` (audited as `catalogue.free_allowance.update` on the pack). The generic pack
   routes list and edit only sellable packs and refuse the two signup codes, so a signup pack can
   never be made purchasable by accident. Teacher signup validity stays Phase 04's constant
   `TEACHER_SIGNUP_VALIDITY` (30 days, spec §2.1); it is shown, not edited.
6. **Complimentary subscriptions (index R15):** admin manual activations have no
   `paymob_subscription_id`. Phase 05's period-end, overdue and drift queries already skip such
   rows; this phase adds the sweeper job `admin.expire_manual_subscriptions`, which ends them at
   `current_period_end`.
7. **Paymob plan sync (index R9):** the admin sync action calls Phase 05's
   `sync_paymob_plan(session, client, settings, plan_tier_id, force_new=True)` inside the audited
   transaction. Task 4 adds the two `0057` stamps (`paymob_plan_synced_price_minor`,
   `paymob_plan_synced_frequency`) inside that helper, so every link — admin or checkout — records
   what Paymob was sent; the drift warning compares them with the tier.
8. **Subscription "extend" applies to complimentary (manually activated, non-Paymob) subscriptions
   only.** Moving a Paymob-billed period end would desynchronise Paymob's billing date; for a paying
   customer the admin grants credits instead. The route answers 409 `paymob_billed`.
9. **`PlatformAdminService.decide_activation` gains a required keyword `admin_user_id`** and writes
   an audit row in its own transaction (keeping Phase 05's `SubscriptionConflictError` check). The two existing `/api/admin/activations/{id}/activate|reject`
   routes keep their request and response shapes, pass the caller, and are marked
   `deprecated=True` in OpenAPI. An empty note is audited with the reason
   `"Decided from the activations queue without a note."` so the old screen keeps working.

## Consumed interfaces — confirm before starting each task

Phases 01–06 were planned in parallel. These are the exact names and signatures this plan calls
beyond what the index fixes. Before starting a task, the implementer greps for each one the task
lists under **Consumes**. If the merged code differs (a renamed keyword, a different module), use
the merged name everywhere in that task — a mechanical rename, no behaviour change — and note it in
the commit body.

| Assumed | Where |
|---|---|
| `PlanAudience` enum (`student`, `teacher`) and `PlanTier.audience`, `.allowance_units`, `.paymob_plan_id` (integer), `.is_active`, `.included_seats`, `.seat_allowance_units`, `.extra_seat_price_minor` | `lemely/db/models/billing.py` (Phase 02) |
| `PaymentPurpose`, `PaymentStatus`, `Payment` (`payer_user_id`, `beneficiary_user_id`, `purpose`, `plan_tier_id`, `credit_pack_id`, `subscription_id`, `seat_quantity`, `amount_minor`, `currency`, `status`, `special_reference`, `paymob_order_id`, `paymob_txn_id`, `paid_at`, `created_at`, `updated_at`) | same |
| `PaymobEvent` (`kind: PaymobEventKind`, `dedupe_key`, `payload`, `processed_at`, TimestampMixin), `CreditPack` (`code`, `name`, `units`, `price_minor`, `currency`, `is_active`) | same |
| `Subscription.payer_user_id`, `.current_period_start`, `.cancel_at_period_end`, `.pending_plan_tier_id`, `.grace_until`, `.extra_seats`, `.pending_extra_seats`, `.paymob_subscription_id` (BigInteger); `SubscriptionStatus.pending_first_payment/past_due/expired` | `billing.py`, `enums.py` (Phase 02) |
| `SubscriptionPeriod` (`subscription_id`, `period_start`, `period_end`, `payment_id`; unique `(subscription_id, period_start)`) | `lemely/db/models/billing.py` (Phase 05) |
| `sync_paymob_plan(session, client, settings, plan_tier_id, *, force_new=False) -> int`, `PlanNotPurchasable(SubscriptionError)`, `InvalidPlanChange`, `SubscriptionNotFound`, `SUBSCRIPTION_WEBHOOK_PATH` | `lemely/db/subscription_repo.py` (Phase 05) |
| `paymob_frequency(interval: str) -> int` | `lemely/core/subscription_rules.py` (Phase 05) |
| `paymob_subscription_webhook(payload, deps)` (`deps.sessionmaker`, `deps.settings`) | `lemely/web/routers/paymob_webhooks.py` (Phase 05) |
| `SubscriptionConflictError` raised by `decide_activation` on a second live subscription | `lemely/db/admin_repo.py` (Phase 05) |
| `PaymobClient.create_plan(*, name, frequency_days, amount_cents, integration_id, webhook_url, …) -> dict`, `refund(*, transaction_id, amount_cents) -> dict`, `void(*, transaction_id) -> dict`, `inquire_by_transaction(transaction_id) -> dict | None`, `cancel_subscription(subscription_id) -> dict`; `PaymobError(message, *, status_code, timeout, body)` (raised for transport errors, timeouts and error statuses) | `lemely/io/paymob/client.py` (Phase 02) |
| `get_paymob_client()`, `get_billing_sessionmaker()` | `lemely/web/deps_billing.py` (Phase 02) |
| `PaymobSettings.moto_integration_id`, `.notification_base_url`; `Settings.paymob` | `lemely/runtime/config.py` (Phase 02) |
| `BillingService(session, client, settings, …)` with `self._session`, `_reconcile_one(payment, *, now)`, `_payment_for_reference(reference) -> Payment | None`, `apply_transaction_callback(obj)`, `_apply_transaction(obj, *, source, payment=None)`; `BillingError` | `lemely/db/billing_repo.py` (Phase 02) |
| `paymob_transaction_callback` (`POST /api/webhooks/paymob/transaction`, has `sm` from `get_billing_sessionmaker`) | `lemely/web/routers/paymob_webhooks.py` (Phase 02); the subscription callback route (Phase 05) |
| `SubscriptionService(session, client, settings)`, `.schedule_cancel(subscription_id: UUID, *, actor_user_id: UUID, now: datetime) -> Subscription` (payer-locked; refuses manual activations) | `lemely/db/subscription_repo.py` (Phase 05) |
| `cost_scope()`, `record_llm_cost(usd_decimal(usd))` in `GeminiClient._record_spend`; `MeteredJob.run()` and `MeteredJob._finish(cost_usd, *, settle)`, `UsageMeter.job(ctx)`, `UsageMeter.authorize(UsageRequest(...))`; test helpers `seed_catalogue`, `seed_user`, `give`, `jobs_for`, `enforcing_meter` | `lemely/io/llm/cost_meter.py`, `lemely/io/gemini.py`, `lemely/web/usage.py`, `tests/usage_helpers.py` (Phase 04) |
| `SIGNUP_STUDENT_PACK`, `SIGNUP_TEACHER_PACK`, `TEACHER_SIGNUP_VALIDITY`, `ensure_usage_catalogue(session, *, now) -> int` | `lemely/db/usage_catalogue_repo.py` (Phase 04) |
| `MeteredAction` | `lemely/core/metered_actions.py` (Phase 04) |
| `UsageJob.created_at`, `UsageGrant.created_at` (TimestampMixin), `UsageEntry.event_at`, `UsageGrantBalance(grant_id, remaining, held)`, `UsageDebt(owner_user_id, job_id, units, outstanding, created_at)` | `lemely/db/models/usage.py` (Phase 01) |
| `TeacherMember` and its enums | `lemely/db/models/team.py` (Phase 03) |
| Subscription webhook payloads stored with `trigger_type` at the top level of `PaymobEvent.payload` | Phase 02 |

## File structure

| File | Responsibility | Task |
|---|---|---|
| `lemely/db/models/admin_audit.py` | `AdminAuditLog` + append-only trigger DDL | 1 |
| `lemely/db/models/billing_ops.py` | `JobRun`, `PaymobWebhookFailure`, `PaymentRefund` (+`RefundKind`, `RefundStatus`), `UsageJobModelCost`, indexes on Phase 01/02 tables | 1 |
| `lemely/db/models/billing.py` (modify) | `PlanTier` synced-price columns, `Payment.callback_received_at` | 1 |
| `lemely/db/migrations/versions/0057_admin_audit_log.py` | All schema above | 1 |
| `lemely/db/admin_billing_repo.py` | `audited`, JSON snapshots, idempotency check, error types, action names, shared payment view, catalogue service | 1, 4 |
| `lemely/db/billing_observability_repo.py` | HMAC-failure writer, job-run recorder, per-model cost writer | 2, 3 |
| `lemely/io/llm/model_costs.py` | Per-model cost contextvar accumulator | 3 |
| `lemely/db/admin_customer_repo.py` | Customer search, detail, ledger and subscription actions, manual-subscription expiry job | 5, 6, 7 |
| `lemely/db/admin_payments_repo.py` | Payment list, problem queue, refund/void, reconcile | 8, 9 |
| `lemely/db/admin_margin_repo.py` | Revenue, cost, accuracy, exposure aggregates | 10 |
| `lemely/db/admin_health_repo.py` | Sweeper, webhook and charge-failure health | 11 |
| `lemely/web/schemas_admin_billing.py` | DTOs | 4–11 |
| `lemely/web/deps_admin_billing.py` | Service dependencies | 4–11 |
| `lemely/web/routers/admin_billing.py` | All 24 routes | 4–11 |
| `tests/admin_billing_db.py` | Throwaway DB, seeds, fake Paymob client, test client | 1–11 |

---

### Task 1: Audit log, phase schema and the `audited` helper

**Files:**
- Create: `lemely/db/models/admin_audit.py`
- Create: `lemely/db/models/billing_ops.py`
- Modify: `lemely/db/models/billing.py` (add 3 columns)
- Modify: `lemely/db/models/__init__.py` (register both new modules, re-export `AdminAuditLog`)
- Create: `lemely/db/migrations/versions/0057_admin_audit_log.py`
- Create: `lemely/db/admin_billing_repo.py`
- Create: `tests/admin_billing_db.py`
- Create: `tests/test_migration_admin_audit_log.py`
- Create: `tests/test_admin_billing_audit.py`
- Modify: `tests/test_db_schema.py` (`EXPECTED_TABLES`)

**Interfaces:**
- Consumes: `Payment`, `PaymobEvent`, `PlanTier` (Phase 02); `UsageJob`, `UsageEntry` (Phase 01); `User`, `Role`.
- Produces:
  - `AdminAuditLog` (`id`, `admin_user_id`, `action`, `target_kind`, `target_id: UUID`, `reason`, `before`, `after`, `created_at`).
  - `JobRun`, `PaymobWebhookFailure`, `PaymentRefund`, `RefundKind`, `RefundStatus`, `UsageJobModelCost` in `lemely.db.models.billing_ops`.
  - `PlanTier.paymob_plan_synced_price_minor: int | None`, `PlanTier.paymob_plan_synced_frequency: int | None`, `Payment.callback_received_at: datetime | None`.
  - In `lemely.db.admin_billing_repo`: `to_jsonable(value) -> object`, `snapshot(obj, fields) -> dict[str, object]`,
    `audited(session, admin_user_id, action, target_kind, target_id, reason, before, after) -> AdminAuditLog`,
    `already_applied(session, *, action: str, idempotency_key: str) -> bool`, `AuditAction`, `AuditTarget`,
    `AdminBillingError(code, message)`, `AdminNotFoundError`, `AdminConflictError`, `AdminInvalidError`,
    `PaymobCallError`, `ReasonRequiredError`.
  - In `tests.admin_billing_db`: `NOW`, `billing_database()`, `emptied_after(factory)`, `add_user(factory, role, *, email=None, display_name=None)`.

- [ ] **Step 1: Write the shared test helpers**

Create `tests/admin_billing_db.py`:

```python
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
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.db.base import Base
from lemely.db.models import import_all_models
from lemely.db.models.enums import Role
from lemely.db.models.users import User
from lemely.runtime.config import DatabaseSettings

if TYPE_CHECKING:
    from collections.abc import Iterator

import_all_models()

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)

# Tables with no foreign key to ``users``; ``TRUNCATE users CASCADE`` reaches the rest.
_ROOT_TABLES = (
    "users",
    "plan_tiers",
    "credit_packs",
    "usage_rates",
    "usage_estimators",
    "job_runs",
    "paymob_webhook_failures",
    "paymob_events",
)


@contextmanager
def billing_database() -> Iterator[sessionmaker[Session]]:
    """A fresh ``create_all`` database for one test module, dropped afterwards."""
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
    """Yield ``factory``, then empty every table the admin billing tests write."""
    yield factory
    with factory.begin() as session:
        session.execute(sa.text(f"TRUNCATE {', '.join(_ROOT_TABLES)} CASCADE"))


def add_user(
    factory: sessionmaker[Session],
    role: Role | str = Role.student,
    *,
    email: str | None = None,
    display_name: str | None = None,
) -> uuid.UUID:
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
```

- [ ] **Step 2: Write the failing audit tests**

Create `tests/test_admin_billing_audit.py`:

```python
"""The admin audit log: one append-only row per admin money or catalogue action (spec §4.7)."""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from sqlalchemy import select

from lemely.db.admin_billing_repo import (
    ReasonRequiredError,
    already_applied,
    audited,
    snapshot,
    to_jsonable,
)
from lemely.db.models.admin_audit import AdminAuditLog
from lemely.db.models.enums import Role
from tests.admin_billing_db import add_user, billing_database, emptied_after

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture(scope="module")
def billing_db() -> Iterator[sessionmaker[Session]]:
    with billing_database() as factory:
        yield factory


@pytest.fixture
def sm(billing_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(billing_db)


class _Colour(enum.Enum):
    red = "red"


def test_to_jsonable_converts_the_types_snapshots_carry() -> None:
    uid = uuid.uuid4()
    moment = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)
    assert to_jsonable(
        {"id": uid, "at": moment, "usd": Decimal("0.004100"), "c": _Colour.red, "xs": (1, "a")}
    ) == {"id": str(uid), "at": moment.isoformat(), "usd": "0.004100", "c": "red", "xs": [1, "a"]}


def test_to_jsonable_refuses_an_unknown_type() -> None:
    with pytest.raises(TypeError):
        to_jsonable(object())


def test_snapshot_reads_the_named_attributes() -> None:
    class Row:
        units = 5
        kind = _Colour.red

    assert snapshot(Row(), ["units", "kind"]) == {"units": 5, "kind": "red"}


def test_audited_writes_one_row_with_a_stripped_reason(sm: sessionmaker[Session]) -> None:
    admin = add_user(sm, Role.platform_admin)
    target = uuid.uuid4()
    with sm.begin() as session:
        row = audited(
            session,
            admin,
            "customer.grant",
            "user",
            target,
            "  goodwill after outage  ",
            {"balance": 0},
            {"balance": 100, "idempotency_key": "admin-grant:abc"},
        )
        row_id = row.id
    with sm() as session:
        stored = session.get(AdminAuditLog, row_id)
        assert stored is not None
        assert stored.reason == "goodwill after outage"
        assert stored.target_id == target
        assert stored.before == {"balance": 0}
        assert stored.after == {"balance": 100, "idempotency_key": "admin-grant:abc"}
        assert already_applied(session, action="customer.grant", idempotency_key="admin-grant:abc")
        assert not already_applied(session, action="customer.adjust", idempotency_key="admin-grant:abc")


@pytest.mark.parametrize("reason", ["", "   ", None])
def test_a_blank_reason_is_refused_and_nothing_is_written(
    sm: sessionmaker[Session], reason: str | None
) -> None:
    admin = add_user(sm, Role.platform_admin)
    with sm.begin() as session, pytest.raises(ReasonRequiredError):
        audited(session, admin, "customer.grant", "user", uuid.uuid4(), reason, None, None)  # type: ignore[arg-type]
    with sm() as session:
        assert session.scalar(select(sa.func.count()).select_from(AdminAuditLog)) == 0


def test_the_row_rolls_back_with_its_transaction(sm: sessionmaker[Session]) -> None:
    admin = add_user(sm, Role.platform_admin)
    with pytest.raises(RuntimeError), sm.begin() as session:
        audited(session, admin, "customer.grant", "user", uuid.uuid4(), "why", None, None)
        raise RuntimeError("the money change failed after the audit row")
    with sm() as session:
        assert session.scalar(select(sa.func.count()).select_from(AdminAuditLog)) == 0


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE admin_audit_log SET reason = 'rewritten'",
        "DELETE FROM admin_audit_log",
    ],
)
def test_create_all_installs_the_append_only_trigger(
    sm: sessionmaker[Session], statement: str
) -> None:
    admin = add_user(sm, Role.platform_admin)
    with sm.begin() as session:
        audited(session, admin, "customer.grant", "user", uuid.uuid4(), "why", None, None)
    with pytest.raises(sa.exc.DBAPIError, match="append-only"), sm.begin() as session:
        session.execute(sa.text(statement))
    with sm() as session:
        assert session.scalar(select(AdminAuditLog.reason)) == "why"
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest --no-cov tests/test_admin_billing_audit.py -v`
Expected: collection error, `ModuleNotFoundError: No module named 'lemely.db.admin_billing_repo'`.

- [ ] **Step 4: Create the audit model**

Create `lemely/db/models/admin_audit.py`:

```python
"""The admin audit log (spec §4.7): one append-only row per admin money or catalogue action.

``lemely.db.admin_billing_repo.audited`` is the only writer. A trigger rejects UPDATE
and DELETE. Migration ``0057_admin_audit_log`` installs it on real databases; the
``after_create`` listeners below install the same SQL on ``create_all`` databases (the
test harness), so both paths enforce one rule.

``admin_user_id`` is ``ON DELETE RESTRICT``: ``SET NULL`` would be an UPDATE the
trigger refuses, and ``CASCADE`` would erase history. ``target_id`` has no foreign
key, so deleting a customer leaves the record of what was done to them.
TRUNCATE is not blocked (statement-level, used by test cleanup only).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from lemely.db.base import Base

APPEND_ONLY_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION admin_audit_log_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'admin_audit_log is append-only'
        USING ERRCODE = 'restrict_violation';
END;
$$
"""

APPEND_ONLY_TRIGGER_SQL = """
CREATE TRIGGER trg_admin_audit_log_append_only
BEFORE UPDATE OR DELETE ON admin_audit_log
FOR EACH ROW EXECUTE FUNCTION admin_audit_log_append_only()
"""


class AdminAuditLog(Base):
    """One admin action: who, what, on which record, why, and the state before and after."""

    __tablename__ = "admin_audit_log"
    __table_args__ = (
        sa.CheckConstraint("length(btrim(reason)) > 0", name="reason_required"),
        sa.Index("ix_admin_audit_log_target", "target_kind", "target_id", "created_at"),
        sa.Index("ix_admin_audit_log_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
    )
    admin_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    action: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    target_kind: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    reason: Mapped[str] = mapped_column(sa.Text, nullable=False)
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


sa.event.listen(
    AdminAuditLog.__table__,
    "after_create",
    sa.DDL(APPEND_ONLY_FUNCTION_SQL).execute_if(dialect="postgresql"),
)
sa.event.listen(
    AdminAuditLog.__table__,
    "after_create",
    sa.DDL(APPEND_ONLY_TRIGGER_SQL).execute_if(dialect="postgresql"),
)

__all__ = ["APPEND_ONLY_FUNCTION_SQL", "APPEND_ONLY_TRIGGER_SQL", "AdminAuditLog"]
```

- [ ] **Step 5: Create the phase's other models**

Create `lemely/db/models/billing_ops.py`:

```python
"""Tables the admin billing surface owns (Phase 07, migration ``0057_admin_audit_log``).

* ``job_runs`` — last run and outcome per sweeper job (health view).
* ``paymob_webhook_failures`` — callbacks refused for a bad HMAC (problem queue).
* ``payment_refunds`` — refund and void attempts, inserted *before* Paymob is called
  (spec §6: Paymob has no idempotency keys).
* ``usage_job_model_costs`` — LLM cost per (job, model) for the margin view.

The ``sa.Index`` objects at the bottom index Phase 01/02 tables for the admin queries;
declaring them here keeps the ORM and migration ``0057`` in step without editing
those phases' models.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from lemely.db.base import Base
from lemely.db.models.billing import Payment
from lemely.db.models.enums import TimestampMixin
from lemely.db.models.usage import UsageEntry, UsageJob


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
    )


def _created_at() -> Mapped[datetime]:
    return mapped_column(sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


class RefundKind(enum.Enum):
    """A partial or full refund, or a same-day void."""

    refund = "refund"
    void = "void"


class RefundStatus(enum.Enum):
    """``unknown`` means Paymob did not answer; inquiry resolves it before any retry."""

    requested = "requested"
    succeeded = "succeeded"
    failed = "failed"
    unknown = "unknown"


class JobRun(Base):
    """The latest run of one sweeper job, upserted after every run."""

    __tablename__ = "job_runs"
    __table_args__ = (
        sa.CheckConstraint("last_outcome IN ('ok', 'failed')", name="outcome_known"),
        sa.CheckConstraint("consecutive_failures >= 0", name="failures_non_negative"),
    )

    job_name: Mapped[str] = mapped_column(sa.String(100), primary_key=True)
    last_started_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    last_finished_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    last_outcome: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    last_result_count: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    last_error: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    consecutive_failures: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default=sa.text("0")
    )
    total_runs: Mapped[int] = mapped_column(sa.BigInteger, nullable=False, server_default=sa.text("0"))
    total_failures: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False, server_default=sa.text("0")
    )


class PaymobWebhookFailure(Base):
    """One callback refused before processing (bad HMAC). The payload is capped at 8 KiB."""

    __tablename__ = "paymob_webhook_failures"
    __table_args__ = (
        sa.CheckConstraint("kind IN ('transaction', 'token', 'subscription')", name="kind_known"),
        sa.Index("ix_paymob_webhook_failures_received_at", "received_at"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    kind: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    reason: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    remote_addr: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    received_at: Mapped[datetime] = _created_at()


class PaymentRefund(TimestampMixin, Base):
    """One admin refund or void of a payment, written before Paymob is called."""

    __tablename__ = "payment_refunds"
    __table_args__ = (
        sa.CheckConstraint("amount_minor > 0", name="amount_positive"),
        sa.CheckConstraint("clawed_back_units >= 0", name="clawback_non_negative"),
        sa.Index("ix_payment_refunds_payment_id", "payment_id"),
        sa.Index("ix_payment_refunds_status_created_at", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    payment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("payments.id", ondelete="RESTRICT"), nullable=False
    )
    admin_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    kind: Mapped[RefundKind] = mapped_column(sa.Enum(RefundKind, name="refundkind"), nullable=False)
    status: Mapped[RefundStatus] = mapped_column(
        sa.Enum(RefundStatus, name="refundstatus"),
        nullable=False,
        server_default=sa.text("'requested'::refundstatus"),
    )
    amount_minor: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    reason: Mapped[str] = mapped_column(sa.Text, nullable=False)
    paymob_response: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    clawed_back_units: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False, server_default=sa.text("0")
    )


class UsageJobModelCost(Base):
    """The USD cost one model contributed to one usage job."""

    __tablename__ = "usage_job_model_costs"
    __table_args__ = (
        sa.UniqueConstraint("usage_job_id", "model"),
        sa.CheckConstraint("cost_usd >= 0", name="cost_non_negative"),
        sa.Index("ix_usage_job_model_costs_model", "model"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    usage_job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("usage_jobs.id", ondelete="CASCADE"), nullable=False
    )
    model: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    cost_usd: Mapped[Decimal] = mapped_column(sa.Numeric(12, 6), nullable=False)
    created_at: Mapped[datetime] = _created_at()


# Indexes on Phase 01/02 tables for the admin queries (migration 0057 creates them).
sa.Index("ix_admin_usage_jobs_created_at", UsageJob.created_at)
sa.Index("ix_admin_usage_jobs_action_estimator", UsageJob.action, UsageJob.estimator_version)
sa.Index("ix_admin_payments_paid_at", Payment.paid_at)
sa.Index("ix_admin_payments_status_created_at", Payment.status, Payment.created_at)
sa.Index("ix_admin_usage_entries_kind_event_at", UsageEntry.kind, UsageEntry.event_at)

__all__ = [
    "JobRun",
    "PaymentRefund",
    "PaymobWebhookFailure",
    "RefundKind",
    "RefundStatus",
    "UsageJobModelCost",
]
```

- [ ] **Step 6: Add the three columns to Phase 02's models**

In `lemely/db/models/billing.py`, add to `class PlanTier` (after `paymob_plan_id`):

```python
    paymob_plan_synced_price_minor: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
    """``price_minor`` as last sent to Paymob by the admin sync action (drift warning)."""
    paymob_plan_synced_frequency: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    """Paymob plan frequency in days (30 or 360) as last sent by the admin sync action."""
```

and to `class Payment`:

```python
    callback_received_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    """When Paymob last called us about this payment (admin "missing callback" queue)."""
```

- [ ] **Step 7: Register the modules**

In `lemely/db/models/__init__.py`: add `from lemely.db.models.admin_audit import AdminAuditLog` to
the alphabetised re-export block, add `"AdminAuditLog"` to `__all__` if the module has one, and add
`admin_audit,` and `billing_ops,` to the tuple imported inside `import_all_models()` (alphabetical:
`academic, admin_audit, attempts, …, billing, billing_ops, …`).

- [ ] **Step 8: Write the audit helper**

Create `lemely/db/admin_billing_repo.py`:

```python
"""Shared pieces of the admin billing surface (spec §8): the audit helper, errors, names.

**Every admin money or catalogue change goes through :func:`audited` in the same
session and transaction as the change.** The audit row and the change commit or roll
back together; a change with no audit row cannot exist.
"""

from __future__ import annotations

import enum
import uuid
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy import select

from lemely.db.models.admin_audit import AdminAuditLog

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


class AdminBillingError(Exception):
    """Base error; ``code`` is the machine-readable string the API returns."""

    def __init__(self, code: str, message: str | None = None) -> None:
        super().__init__(message or code)
        self.code = code
        self.message = message or code


class AdminNotFoundError(AdminBillingError):
    """The record named in the path does not exist (404)."""


class AdminConflictError(AdminBillingError):
    """The record's state forbids the action (409)."""


class AdminInvalidError(AdminBillingError):
    """The request is well-formed but its values are not acceptable (422)."""


class PaymobCallError(AdminBillingError):
    """Paymob refused or failed a call this action depends on (502)."""


class ReasonRequiredError(AdminInvalidError):
    """An admin change was attempted without a reason."""

    def __init__(self) -> None:
        super().__init__("reason_required", "Every admin change needs a reason.")


class AuditTarget(enum.StrEnum):
    PLAN_TIER = "plan_tier"
    CREDIT_PACK = "credit_pack"
    USAGE_RATE = "usage_rate"
    USAGE_ESTIMATOR = "usage_estimator"
    USER = "user"
    SUBSCRIPTION = "subscription"
    PAYMENT = "payment"


class AuditAction(enum.StrEnum):
    PLAN_TIER_CREATE = "catalogue.plan_tier.create"
    PLAN_TIER_UPDATE = "catalogue.plan_tier.update"
    PLAN_TIER_SYNC = "catalogue.plan_tier.sync_paymob"
    CREDIT_PACK_CREATE = "catalogue.credit_pack.create"
    CREDIT_PACK_UPDATE = "catalogue.credit_pack.update"
    FREE_ALLOWANCE_UPDATE = "catalogue.free_allowance.update"
    USAGE_RATE_VERSION = "catalogue.usage_rate.version"
    USAGE_ESTIMATOR_VERSION = "catalogue.usage_estimator.version"
    CUSTOMER_GRANT = "customer.grant"
    CUSTOMER_ADJUST = "customer.adjust"
    CUSTOMER_FORGIVE_DEBT = "customer.forgive_debt"
    SUBSCRIPTION_MANUAL_ACTIVATION = "subscription.manual_activation"
    SUBSCRIPTION_ACTIVATION_DECISION = "subscription.activation_decision"
    SUBSCRIPTION_EXTEND = "subscription.extend"
    SUBSCRIPTION_CANCEL = "subscription.cancel"
    PAYMENT_REFUND_REQUESTED = "payment.refund.requested"
    PAYMENT_VOID_REQUESTED = "payment.void.requested"
    PAYMENT_REFUND_SUCCEEDED = "payment.refund.succeeded"
    PAYMENT_REFUND_FAILED = "payment.refund.failed"
    PAYMENT_REFUND_UNKNOWN = "payment.refund.unknown"
    PAYMENT_RECONCILE = "payment.reconcile"


def to_jsonable(value: object) -> object:
    """Convert a snapshot value to JSON-safe data. Unknown types are an error, not ``str()``."""
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, enum.Enum):
        return to_jsonable(value.value)
    if isinstance(value, Mapping):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [to_jsonable(item) for item in value]
    raise TypeError(f"cannot audit a value of type {type(value).__name__}")


def snapshot(obj: object, fields: Sequence[str]) -> dict[str, object]:
    """The named attributes of ``obj`` as JSON-safe data, for ``before``/``after``."""
    return {name: to_jsonable(getattr(obj, name)) for name in fields}


def audited(
    session: Session,
    admin_user_id: uuid.UUID,
    action: str,
    target_kind: str,
    target_id: uuid.UUID,
    reason: str,
    before: Mapping[str, object] | None,
    after: Mapping[str, object] | None,
) -> AdminAuditLog:
    """Add one audit row to ``session``'s transaction and flush it.

    Raises:
        ReasonRequiredError: ``reason`` is empty or whitespace.
    """
    cleaned = (reason or "").strip()
    if not cleaned:
        raise ReasonRequiredError
    row = AdminAuditLog(
        admin_user_id=admin_user_id,
        action=str(action),
        target_kind=str(target_kind),
        target_id=target_id,
        reason=cleaned,
        before=None if before is None else to_jsonable(before),
        after=None if after is None else to_jsonable(after),
    )
    session.add(row)
    session.flush()
    return row


def already_applied(session: Session, *, action: str, idempotency_key: str) -> bool:
    """True when an audit row for ``action`` already carries ``after.idempotency_key``.

    Callers first take ``pg_advisory_xact_lock(hashtext(key))`` so two identical
    requests serialise on the key instead of both passing this check.
    """
    found = session.scalar(
        select(sa.literal(True))
        .where(
            AdminAuditLog.action == str(action),
            AdminAuditLog.after["idempotency_key"].astext == idempotency_key,
        )
        .limit(1)
    )
    return found is not None


def lock_idempotency_key(session: Session, idempotency_key: str) -> None:
    """Serialise concurrent requests carrying the same key until this transaction ends."""
    session.execute(select(sa.func.pg_advisory_xact_lock(sa.func.hashtext(idempotency_key))))


__all__ = [
    "AdminBillingError",
    "AdminConflictError",
    "AdminInvalidError",
    "AdminNotFoundError",
    "AuditAction",
    "AuditTarget",
    "PaymobCallError",
    "ReasonRequiredError",
    "already_applied",
    "audited",
    "lock_idempotency_key",
    "snapshot",
    "to_jsonable",
]
```

- [ ] **Step 9: Run the audit tests to verify they pass**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest --no-cov tests/test_admin_billing_audit.py -v`
Expected: 10 passed (no skips).

- [ ] **Step 10: Write the failing migration test**

Create `tests/test_migration_admin_audit_log.py`:

```python
"""Migration 0057_admin_audit_log: the admin audit log and the tables Phase 07 owns.

Expected names come from the ORM, so these tests compare the migration with an
independent declaration. The downgrade must remove exactly what the upgrade added.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.script import ScriptDirectory

from lemely.db.base import Base
from lemely.db.models import import_all_models
from tests.test_migration_tutoring_enums import (
    column_names,
    current_revision,
    head_revision,
    object_names,
    public_tables,
    upgrade_head,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.orm import Session, sessionmaker

import_all_models()

REVISION = "0057_admin_audit_log"
DOWN_REVISION = "0056_auto_topup"
NEW_TABLES = (
    "admin_audit_log",
    "job_runs",
    "paymob_webhook_failures",
    "payment_refunds",
    "usage_job_model_costs",
)
FOREIGN_INDEXES = {
    "ix_admin_usage_jobs_created_at",
    "ix_admin_usage_jobs_action_estimator",
    "ix_admin_payments_paid_at",
    "ix_admin_payments_status_created_at",
    "ix_admin_usage_entries_kind_event_at",
}
NEW_ENUMS = ("refundkind", "refundstatus")


def _orm_names(tables: tuple[str, ...]) -> set[str]:
    names: set[str] = set()
    for name in tables:
        table = Base.metadata.tables[name]
        names |= {str(c.name) for c in table.constraints}
        names |= {str(i.name) for i in table.indexes}
    return names


def _indexes(session: Session) -> set[str]:
    return set(
        session.execute(sa.text("SELECT indexname FROM pg_indexes WHERE schemaname = 'public'"))
        .scalars()
        .all()
    )


def _enums(session: Session) -> set[str]:
    return set(session.execute(sa.text("SELECT typname FROM pg_type WHERE typtype = 'e'")).scalars())


def test_revision_chains_from_0056_and_is_in_the_history() -> None:
    """Index R10: assert lineage, never "is the head" (later migrations must not break this)."""
    script_dir = ScriptDirectory.from_config(Config("alembic.ini"))
    revision = script_dir.get_revision(REVISION)
    assert revision is not None
    assert revision.down_revision == DOWN_REVISION
    assert len(REVISION) <= 32
    assert REVISION in {r.revision for r in script_dir.iterate_revisions(head_revision(), "base")}


def test_orm_declares_the_foreign_indexes() -> None:
    declared = {str(i.name) for t in Base.metadata.tables.values() for i in t.indexes}
    assert declared >= FOREIGN_INDEXES


def test_new_tables_match_the_orm(migrated_sessionmaker: sessionmaker[Session]) -> None:
    with migrated_sessionmaker() as session:
        assert object_names(session, NEW_TABLES) == _orm_names(NEW_TABLES)
        assert _indexes(session) >= FOREIGN_INDEXES
        assert {"paymob_plan_synced_price_minor", "paymob_plan_synced_frequency"} <= column_names(
            session, "plan_tiers"
        )
        assert "callback_received_at" in column_names(session, "payments")


@pytest.mark.parametrize(
    "statement",
    ["UPDATE admin_audit_log SET reason = 'rewritten'", "DELETE FROM admin_audit_log"],
)
def test_migrated_audit_log_is_append_only(
    migrated_sessionmaker: sessionmaker[Session], statement: str
) -> None:
    admin = uuid.uuid4()
    with migrated_sessionmaker.begin() as session:
        session.execute(
            sa.text("INSERT INTO users (id, email, role) VALUES (:u, :e, 'platform_admin')"),
            {"u": admin, "e": f"{admin}@example.com"},
        )
        session.execute(
            sa.text(
                "INSERT INTO admin_audit_log (admin_user_id, action, target_kind, target_id, reason)"
                " VALUES (:a, 'customer.grant', 'user', :t, 'why')"
            ),
            {"a": admin, "t": uuid.uuid4()},
        )
    with pytest.raises(sa.exc.DBAPIError, match="append-only"), migrated_sessionmaker.begin() as s:
        s.execute(sa.text(statement))


def test_a_blank_reason_is_refused_by_the_database(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    admin = uuid.uuid4()
    with migrated_sessionmaker.begin() as session:
        session.execute(
            sa.text("INSERT INTO users (id, email, role) VALUES (:u, :e, 'platform_admin')"),
            {"u": admin, "e": f"{admin}@example.com"},
        )
    with pytest.raises(sa.exc.IntegrityError), migrated_sessionmaker.begin() as session:
        session.execute(
            sa.text(
                "INSERT INTO admin_audit_log (admin_user_id, action, target_kind, target_id, reason)"
                " VALUES (:a, 'customer.grant', 'user', :t, '   ')"
            ),
            {"a": admin, "t": uuid.uuid4()},
        )


def test_upgrade_downgrade_upgrade_round_trip(
    migrated_sessionmaker_with_downgrade: tuple[sessionmaker[Session], Callable[[str], None]],
) -> None:
    sm, downgrade_to = migrated_sessionmaker_with_downgrade
    with sm() as session:
        after_upgrade = object_names(session, NEW_TABLES)

    downgrade_to(DOWN_REVISION)

    with sm() as session:
        assert current_revision(session) == DOWN_REVISION
        assert not set(NEW_TABLES) & public_tables(session)
        assert not FOREIGN_INDEXES & _indexes(session)
        assert not set(NEW_ENUMS) & _enums(session)
        assert "paymob_plan_synced_price_minor" not in column_names(session, "plan_tiers")
        assert "callback_received_at" not in column_names(session, "payments")
        assert (
            session.execute(
                sa.text("SELECT count(*) FROM pg_proc WHERE proname = 'admin_audit_log_append_only'")
            ).scalar_one()
            == 0
        )

    upgrade_head()

    with sm() as session:
        assert current_revision(session) == REVISION
        assert object_names(session, NEW_TABLES) == after_upgrade
```

- [ ] **Step 11: Run the migration test to verify it fails**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest --no-cov tests/test_migration_admin_audit_log.py -v`
Expected: `test_revision_chains_from_0056_and_is_in_the_history` FAILS (`revision is None`); the
`migrated_sessionmaker` tests FAIL because the tables do not exist.

- [ ] **Step 12: Write the migration**

Create `lemely/db/migrations/versions/0057_admin_audit_log.py`:

```python
"""admin audit log and the tables the admin billing surface owns

Revision ID: 0057_admin_audit_log
Revises: 0056_auto_topup
Create Date: 2026-11-05 00:00:00.000000

Phase 07 (spec §4.7, §6, §8). Additive only.

* ``admin_audit_log`` + ``admin_audit_log_append_only()`` and its BEFORE UPDATE OR
  DELETE trigger. ``admin_user_id`` is RESTRICT (SET NULL would be an UPDATE).
* ``job_runs``, ``paymob_webhook_failures``, ``payment_refunds`` (+ ``refundkind``,
  ``refundstatus``), ``usage_job_model_costs``.
* ``plan_tiers.paymob_plan_synced_price_minor`` / ``paymob_plan_synced_frequency``,
  ``payments.callback_received_at``.
* Indexes on ``usage_jobs``, ``payments``, ``usage_entries``, ``paymob_events`` for the
  admin margin and payments queries.

``downgrade`` removes exactly these objects.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0057_admin_audit_log"
down_revision: str | Sequence[str] | None = "0056_auto_topup"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_APPEND_ONLY_FUNCTION = """
CREATE OR REPLACE FUNCTION admin_audit_log_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'admin_audit_log is append-only'
        USING ERRCODE = 'restrict_violation';
END;
$$
"""

_APPEND_ONLY_TRIGGER = """
CREATE TRIGGER trg_admin_audit_log_append_only
BEFORE UPDATE OR DELETE ON admin_audit_log
FOR EACH ROW EXECUTE FUNCTION admin_audit_log_append_only()
"""


def _uuid_pk() -> sa.Column:
    return sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False)


def _now(name: str) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False)


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "admin_audit_log",
        _uuid_pk(),
        sa.Column("admin_user_id", sa.UUID(), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target_kind", sa.String(length=32), nullable=False),
        sa.Column("target_id", sa.UUID(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("before", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("after", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        _now("created_at"),
        sa.CheckConstraint(
            "length(btrim(reason)) > 0", name=op.f("ck_admin_audit_log_reason_required")
        ),
        sa.ForeignKeyConstraint(
            ["admin_user_id"],
            ["users.id"],
            name=op.f("fk_admin_audit_log_admin_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_admin_audit_log")),
    )
    op.create_index(
        "ix_admin_audit_log_target", "admin_audit_log", ["target_kind", "target_id", "created_at"]
    )
    op.create_index("ix_admin_audit_log_created_at", "admin_audit_log", ["created_at"])
    op.execute(_APPEND_ONLY_FUNCTION)
    op.execute(_APPEND_ONLY_TRIGGER)

    op.create_table(
        "job_runs",
        sa.Column("job_name", sa.String(length=100), nullable=False),
        sa.Column("last_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_outcome", sa.String(length=16), nullable=False),
        sa.Column("last_result_count", sa.Integer(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consecutive_failures", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("total_runs", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("total_failures", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.CheckConstraint(
            "last_outcome IN ('ok', 'failed')", name=op.f("ck_job_runs_outcome_known")
        ),
        sa.CheckConstraint(
            "consecutive_failures >= 0", name=op.f("ck_job_runs_failures_non_negative")
        ),
        sa.PrimaryKeyConstraint("job_name", name=op.f("pk_job_runs")),
    )

    op.create_table(
        "paymob_webhook_failures",
        _uuid_pk(),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.String(length=32), nullable=False),
        sa.Column("remote_addr", sa.String(length=64), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        _now("received_at"),
        sa.CheckConstraint(
            "kind IN ('transaction', 'token', 'subscription')",
            name=op.f("ck_paymob_webhook_failures_kind_known"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_paymob_webhook_failures")),
    )
    op.create_index(
        "ix_paymob_webhook_failures_received_at", "paymob_webhook_failures", ["received_at"]
    )

    op.create_table(
        "payment_refunds",
        _uuid_pk(),
        sa.Column("payment_id", sa.UUID(), nullable=False),
        sa.Column("admin_user_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.Enum("refund", "void", name="refundkind"), nullable=False),
        sa.Column(
            "status",
            sa.Enum("requested", "succeeded", "failed", "unknown", name="refundstatus"),
            server_default=sa.text("'requested'::refundstatus"),
            nullable=False,
        ),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("paymob_response", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("clawed_back_units", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        _now("created_at"),
        _now("updated_at"),
        sa.CheckConstraint("amount_minor > 0", name=op.f("ck_payment_refunds_amount_positive")),
        sa.CheckConstraint(
            "clawed_back_units >= 0", name=op.f("ck_payment_refunds_clawback_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["payment_id"],
            ["payments.id"],
            name=op.f("fk_payment_refunds_payment_id_payments"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["admin_user_id"],
            ["users.id"],
            name=op.f("fk_payment_refunds_admin_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payment_refunds")),
    )
    op.create_index("ix_payment_refunds_payment_id", "payment_refunds", ["payment_id"])
    op.create_index(
        "ix_payment_refunds_status_created_at", "payment_refunds", ["status", "created_at"]
    )

    op.create_table(
        "usage_job_model_costs",
        _uuid_pk(),
        sa.Column("usage_job_id", sa.UUID(), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("cost_usd", sa.Numeric(precision=12, scale=6), nullable=False),
        _now("created_at"),
        sa.CheckConstraint("cost_usd >= 0", name=op.f("ck_usage_job_model_costs_cost_non_negative")),
        sa.ForeignKeyConstraint(
            ["usage_job_id"],
            ["usage_jobs.id"],
            name=op.f("fk_usage_job_model_costs_usage_job_id_usage_jobs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_usage_job_model_costs")),
        sa.UniqueConstraint(
            "usage_job_id", "model", name=op.f("uq_usage_job_model_costs_usage_job_id")
        ),
    )
    op.create_index("ix_usage_job_model_costs_model", "usage_job_model_costs", ["model"])

    op.add_column(
        "plan_tiers", sa.Column("paymob_plan_synced_price_minor", sa.BigInteger(), nullable=True)
    )
    op.add_column(
        "plan_tiers", sa.Column("paymob_plan_synced_frequency", sa.Integer(), nullable=True)
    )
    op.add_column(
        "payments", sa.Column("callback_received_at", sa.DateTime(timezone=True), nullable=True)
    )

    op.create_index("ix_admin_usage_jobs_created_at", "usage_jobs", ["created_at"])
    op.create_index(
        "ix_admin_usage_jobs_action_estimator", "usage_jobs", ["action", "estimator_version"]
    )
    op.create_index("ix_admin_payments_paid_at", "payments", ["paid_at"])
    op.create_index("ix_admin_payments_status_created_at", "payments", ["status", "created_at"])
    op.create_index("ix_admin_usage_entries_kind_event_at", "usage_entries", ["kind", "event_at"])


def downgrade() -> None:
    """Downgrade schema: drop exactly what ``upgrade`` added."""
    op.drop_index("ix_admin_usage_entries_kind_event_at", table_name="usage_entries")
    op.drop_index("ix_admin_payments_status_created_at", table_name="payments")
    op.drop_index("ix_admin_payments_paid_at", table_name="payments")
    op.drop_index("ix_admin_usage_jobs_action_estimator", table_name="usage_jobs")
    op.drop_index("ix_admin_usage_jobs_created_at", table_name="usage_jobs")
    op.drop_column("payments", "callback_received_at")
    op.drop_column("plan_tiers", "paymob_plan_synced_frequency")
    op.drop_column("plan_tiers", "paymob_plan_synced_price_minor")
    op.drop_table("usage_job_model_costs")
    op.drop_table("payment_refunds")
    sa.Enum(name="refundstatus").drop(op.get_bind(), checkfirst=False)
    sa.Enum(name="refundkind").drop(op.get_bind(), checkfirst=False)
    op.drop_table("paymob_webhook_failures")
    op.drop_table("job_runs")
    op.drop_table("admin_audit_log")
    op.execute("DROP FUNCTION admin_audit_log_append_only()")
```

- [ ] **Step 13: Register the new tables in the schema test**

In `tests/test_db_schema.py`, add to the `EXPECTED_TABLES` set (it must equal
`Base.metadata.tables`):

```python
    "admin_audit_log",
    "job_runs",
    "paymob_webhook_failures",
    "payment_refunds",
    "usage_job_model_costs",
```

- [ ] **Step 14: Run every touched test**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest --no-cov tests/test_migration_admin_audit_log.py tests/test_admin_billing_audit.py tests/test_db_schema.py tests/architecture -v`
Expected: all pass, no skips.

- [ ] **Step 15: Commit**

```bash
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files
P="lemely/db/models/admin_audit.py lemely/db/models/billing_ops.py lemely/db/models/billing.py lemely/db/models/__init__.py lemely/db/migrations/versions/0057_admin_audit_log.py lemely/db/admin_billing_repo.py tests/admin_billing_db.py tests/test_migration_admin_audit_log.py tests/test_admin_billing_audit.py tests/test_db_schema.py"
git add $P
git commit -S -m "feat(admin): append-only admin audit log, phase schema and audited helper" -- $P
```

### Task 2: Record sweeper runs, HMAC failures and callback arrival; reconcile one payment

**Files:**
- Create: `lemely/db/billing_observability_repo.py`
- Modify: `lemely/web/scheduled_notifications.py` (`run_jobs`, `Sweeper`)
- Modify: `lemely/web/deps.py` (`get_sweeper`)
- Modify: `lemely/web/routers/paymob_webhooks.py` (Phase 02) and Phase 05's subscription callback handler
- Modify: `lemely/db/billing_repo.py` (Phase 02)
- Create: `tests/test_billing_observability.py`
- Modify: `tests/test_billing_callbacks.py` (Phase 02)

**Interfaces:**
- Consumes: `JobRun`, `PaymobWebhookFailure` (Task 1); `BillingService.reconcile_pending`, `apply_transaction_callback`, `Payment`, `PaymentStatus`, `PaymobEvent` (Phase 02).
- Produces:
  - `record_webhook_failure(factory: sessionmaker[Session], *, kind: str, reason: str, payload: Mapping[str, Any] | None, remote_addr: str | None) -> None`
  - `JobRunResult(name: str, started_at: datetime, finished_at: datetime, count: int | None, error: str | None)` and `JobRunRecorder(factory)`, callable with a `JobRunResult`.
  - `run_jobs(jobs, *, recorder: Callable[[JobRunResult], None] | None = None, clock: Callable[[], datetime] = _utcnow)`; `Sweeper.run_recorder: Callable[[JobRunResult], None] | None = None`.
  - `BillingService.reconcile_payment_now(payment_id: UUID, *, now: datetime) -> PaymentStatus`; `PaymentNotFoundError(BillingError)` in `lemely.db.billing_repo`.
  - `Payment.callback_received_at` is set by every verified transaction callback that names the payment (inquiry results never set it).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_billing_observability.py`:

```python
"""Facts the admin health and problem views read: job runs, HMAC failures, reconcile one."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from lemely.db.billing_observability_repo import (
    JobRunRecorder,
    JobRunResult,
    record_webhook_failure,
)
from lemely.db.models.billing_ops import JobRun, PaymobWebhookFailure
from lemely.runtime.config import Settings
from lemely.web.deps import get_settings
from lemely.web.deps_billing import get_billing_sessionmaker, get_paymob_client
from lemely.web.routers import paymob_webhooks
from lemely.web.scheduled_notifications import run_jobs
from tests.admin_billing_db import NOW, billing_database, emptied_after
from tests.tutoring_app import app_with_routers

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture(scope="module")
def billing_db() -> Iterator[sessionmaker[Session]]:
    with billing_database() as factory:
        yield factory


@pytest.fixture
def sm(billing_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(billing_db)


def _result(name: str, minutes: int, *, error: str | None = None) -> JobRunResult:
    started = NOW + timedelta(minutes=minutes)
    return JobRunResult(
        name=name,
        started_at=started,
        finished_at=started + timedelta(seconds=2),
        count=None if error else 3,
        error=error,
    )


def test_job_runs_track_outcome_streaks_and_last_success(sm: sessionmaker[Session]) -> None:
    record = JobRunRecorder(sm)
    record(_result("billing.reconcile_pending", 0))
    record(_result("billing.reconcile_pending", 1, error="RuntimeError: boom"))
    record(_result("billing.reconcile_pending", 2, error="RuntimeError: boom again"))

    with sm() as session:
        row = session.get(JobRun, "billing.reconcile_pending")
        assert row is not None
        assert row.last_outcome == "failed"
        assert row.last_error == "RuntimeError: boom again"
        assert row.last_result_count is None
        assert row.consecutive_failures == 2
        assert row.total_runs == 3
        assert row.total_failures == 2
        assert row.last_success_at == NOW + timedelta(seconds=2)

    record(_result("billing.reconcile_pending", 3))
    with sm() as session:
        row = session.get(JobRun, "billing.reconcile_pending")
        assert row is not None
        assert row.last_outcome == "ok"
        assert row.last_error is None
        assert row.last_result_count == 3
        assert row.consecutive_failures == 0
        assert row.total_runs == 4
        assert row.last_success_at == NOW + timedelta(minutes=3, seconds=2)


def test_run_jobs_reports_each_job_to_the_recorder() -> None:
    seen: list[JobRunResult] = []

    def boom() -> int:
        raise RuntimeError("boom")

    results = run_jobs([("a", lambda: 2), ("b", boom)], recorder=seen.append, clock=lambda: NOW)

    assert results == {"a": 2, "b": None}
    assert [(r.name, r.count, r.error) for r in seen] == [
        ("a", 2, None),
        ("b", None, "RuntimeError: boom"),
    ]


def test_a_failing_recorder_never_stops_the_jobs() -> None:
    ran: list[str] = []

    def broken(_: JobRunResult) -> None:
        raise RuntimeError("db down")

    def job(name: str) -> int:
        ran.append(name)
        return 1

    results = run_jobs([("a", lambda: job("a")), ("b", lambda: job("b"))], recorder=broken)

    assert ran == ["a", "b"]
    assert results == {"a": 1, "b": 1}


def test_webhook_failures_are_stored_and_large_payloads_capped(sm: sessionmaker[Session]) -> None:
    record_webhook_failure(
        sm, kind="transaction", reason="hmac_mismatch", payload={"obj": {"id": 1}}, remote_addr="1.2.3.4"
    )
    record_webhook_failure(
        sm, kind="subscription", reason="hmac_mismatch", payload={"blob": "x" * 9000}, remote_addr=None
    )
    with sm() as session:
        rows = {r.kind: r for r in session.scalars(select(PaymobWebhookFailure))}
    assert rows["transaction"].payload == {"obj": {"id": 1}}
    assert rows["transaction"].remote_addr == "1.2.3.4"
    # json.dumps gives '{"blob": "' + 9000 x + '"}' = 9012 bytes, over the 8192 cap.
    assert rows["subscription"].payload == {"truncated": True, "bytes": 9012}


def test_a_bad_transaction_hmac_is_recorded_before_the_401(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[dict[str, object]] = []
    monkeypatch.setattr(
        paymob_webhooks, "record_webhook_failure", lambda factory, **kwargs: seen.append(kwargs)
    )
    data = Settings().model_dump()
    data["paymob"]["hmac_secret"] = "s3cret"
    settings = Settings.model_validate(data)
    app = app_with_routers(paymob_webhooks.router)
    app.dependency_overrides[get_settings] = lambda: settings
    # Never reached: the HMAC check fails first. Overridden so nothing real is built.
    app.dependency_overrides[get_billing_sessionmaker] = lambda: None
    app.dependency_overrides[get_paymob_client] = lambda: None
    path = next(r.path for r in paymob_webhooks.router.routes if r.path.endswith("/transaction"))

    resp = TestClient(app).post(f"{path}?hmac=deadbeef", json={"type": "TRANSACTION", "obj": {"id": 1}})

    assert resp.status_code == 401
    assert len(seen) == 1
    assert seen[0]["kind"] == "transaction"
    assert seen[0]["reason"] == "hmac_mismatch"
```

Append to the same file the `reconcile_payment_now` tests (they reuse Phase 02's `BillingService`; the
fake client records calls so the test can prove a settled payment is not inquired again):

```python
from lemely.db.billing_repo import BillingService, PaymentNotFoundError  # noqa: E402
from lemely.db.models.billing import Payment, PaymentPurpose, PaymentStatus  # noqa: E402
from lemely.db.models.enums import Role  # noqa: E402
from tests.admin_billing_db import add_user  # noqa: E402


class _RecordingClient:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def __getattr__(self, name: str) -> object:
        def call(*args: object, **kwargs: object) -> dict[str, object]:
            self.calls.append(name)
            return {}

        return call


def _payment(sm: sessionmaker[Session], status: PaymentStatus) -> uuid.UUID:
    user = add_user(sm, Role.student)
    pid = uuid.uuid4()
    with sm.begin() as session:
        session.add(
            Payment(
                id=pid,
                payer_user_id=user,
                beneficiary_user_id=user,
                purpose=PaymentPurpose.credit_pack,
                amount_minor=10000,
                currency="EGP",
                status=status,
                special_reference=str(pid),
                created_at=NOW - timedelta(hours=2),
            )
        )
    return pid


def test_reconcile_payment_now_leaves_a_settled_payment_alone(sm: sessionmaker[Session]) -> None:
    pid = _payment(sm, PaymentStatus.paid)
    client = _RecordingClient()
    with sm.begin() as session:
        status = BillingService(session, client, Settings().paymob).reconcile_payment_now(pid, now=NOW)  # type: ignore[arg-type]
    assert status is PaymentStatus.paid
    assert client.calls == []


def test_reconcile_payment_now_runs_the_per_payment_routine_for_a_pending_payment(
    sm: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    pid = _payment(sm, PaymentStatus.pending)
    seen: list[uuid.UUID] = []

    def fake_routine(self: BillingService, payment: Payment, *, now: object) -> None:
        seen.append(payment.id)
        payment.status = PaymentStatus.failed

    monkeypatch.setattr(BillingService, "_reconcile_one", fake_routine)
    with sm.begin() as session:
        status = BillingService(session, _RecordingClient(), Settings().paymob).reconcile_payment_now(pid, now=NOW)  # type: ignore[arg-type]
    assert seen == [pid]
    assert status is PaymentStatus.failed


def test_reconcile_payment_now_raises_for_an_unknown_payment(sm: sessionmaker[Session]) -> None:
    with sm.begin() as session, pytest.raises(PaymentNotFoundError):
        BillingService(session, _RecordingClient(), Settings().paymob).reconcile_payment_now(uuid.uuid4(), now=NOW)  # type: ignore[arg-type]
```

Move the appended imports to the top import block when you paste (ruff will otherwise flag
E402; the `noqa` markers above exist only so this plan's snippet stays copy-pasteable in order).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest --no-cov tests/test_billing_observability.py -v`
Expected: collection error, `No module named 'lemely.db.billing_observability_repo'`.

- [ ] **Step 3: Write the observability repository**

Create `lemely/db/billing_observability_repo.py`:

```python
"""Write paths behind the admin health and problem views (Phase 07, spec §8 areas 3 and 5).

* :func:`record_webhook_failure` — one row per callback refused for a bad HMAC. Its
  own transaction: the request that triggers it ends in a 401 with nothing else to commit.
* :class:`JobRunRecorder` — upserts ``job_runs`` after each sweeper job.
* :func:`record_job_model_costs` — per-model LLM cost of a settled usage job (Task 3).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert

from lemely.db.models.billing_ops import JobRun, PaymobWebhookFailure

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime

    from sqlalchemy.orm import Session, sessionmaker

_MAX_PAYLOAD_BYTES = 8192
_MAX_ERROR_CHARS = 2000


def _capped(payload: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if payload is None:
        return None
    encoded = json.dumps(payload, default=str)
    size = len(encoded.encode("utf-8"))
    if size > _MAX_PAYLOAD_BYTES:
        return {"truncated": True, "bytes": size}
    decoded: dict[str, Any] = json.loads(encoded)
    return decoded


def record_webhook_failure(
    factory: sessionmaker[Session],
    *,
    kind: str,
    reason: str,
    payload: Mapping[str, Any] | None,
    remote_addr: str | None,
) -> None:
    """Store one refused callback. Payloads over 8 KiB are replaced by their size."""
    with factory.begin() as session:
        session.add(
            PaymobWebhookFailure(
                kind=kind, reason=reason, payload=_capped(payload), remote_addr=remote_addr
            )
        )


@dataclass(frozen=True, slots=True)
class JobRunResult:
    """One finished sweeper job: ``count`` is its return value, ``error`` set when it raised."""

    name: str
    started_at: datetime
    finished_at: datetime
    count: int | None
    error: str | None


class JobRunRecorder:
    """Upsert ``job_runs`` from a :class:`JobRunResult`, in its own transaction."""

    def __init__(self, factory: sessionmaker[Session]) -> None:
        self._factory = factory

    def __call__(self, result: JobRunResult) -> None:
        ok = result.error is None
        stmt = pg_insert(JobRun).values(
            job_name=result.name,
            last_started_at=result.started_at,
            last_finished_at=result.finished_at,
            last_outcome="ok" if ok else "failed",
            last_result_count=result.count,
            last_error=None if ok else (result.error or "")[:_MAX_ERROR_CHARS],
            last_success_at=result.finished_at if ok else None,
            consecutive_failures=0 if ok else 1,
            total_runs=1,
            total_failures=0 if ok else 1,
        )
        new = stmt.excluded
        stmt = stmt.on_conflict_do_update(
            index_elements=[JobRun.job_name],
            set_={
                "last_started_at": new.last_started_at,
                "last_finished_at": new.last_finished_at,
                "last_outcome": new.last_outcome,
                "last_result_count": new.last_result_count,
                "last_error": new.last_error,
                "last_success_at": sa.func.coalesce(new.last_success_at, JobRun.last_success_at),
                "consecutive_failures": sa.case(
                    (new.last_outcome == "ok", 0), else_=JobRun.consecutive_failures + 1
                ),
                "total_runs": JobRun.total_runs + 1,
                "total_failures": JobRun.total_failures + new.total_failures,
            },
        )
        with self._factory.begin() as session:
            session.execute(stmt)


__all__ = ["JobRunRecorder", "JobRunResult", "record_webhook_failure"]
```

- [ ] **Step 4: Report each sweeper job to a recorder**

In `lemely/web/scheduled_notifications.py`:

1. Move `def _utcnow()` (currently below `run_jobs`) above `run_jobs`, unchanged.
2. Add `from lemely.db.billing_observability_repo import JobRunResult` to the runtime imports.
3. Replace `run_jobs` with:

```python
def run_jobs(
    jobs: Sequence[tuple[str, Callable[[], int]]],
    *,
    recorder: Callable[[JobRunResult], None] | None = None,
    clock: Callable[[], datetime] = _utcnow,
) -> dict[str, int | None]:
    """Run each job in turn, each wrapped individually.

    A job that throws is a logged warning and the others still run (§4). The
    returned map carries each job's count, or ``None`` for one that threw.

    ``recorder`` (the admin health view's ``job_runs`` writer) hears about every
    job, success or failure. A recorder that throws is logged and ignored: losing
    one health row must never stop a billing job.
    """
    results: dict[str, int | None] = {}
    for name, job in jobs:
        started = clock()
        error: str | None = None
        try:
            results[name] = job()
        except Exception as exc:
            log.warning("sweep_job_failed", job=name, exc_info=True)
            results[name] = None
            error = f"{type(exc).__name__}: {exc}"
        if recorder is not None:
            try:
                recorder(
                    JobRunResult(
                        name=name,
                        started_at=started,
                        finished_at=clock(),
                        count=results[name],
                        error=error,
                    )
                )
            except Exception:
                log.warning("sweep_job_record_failed", job=name, exc_info=True)
    return results
```

4. In `class Sweeper`, add after `email_daily_cap`:

```python
    #: Writes ``job_runs`` for the admin health view (Phase 07). ``None`` in tests that
    #: build a sweeper without a database.
    run_recorder: Callable[[JobRunResult], None] | None = None
```

5. In `Sweeper.sweep_once`, replace the final `return run_jobs(jobs)` with
   `return run_jobs(jobs, recorder=self.run_recorder, clock=self.now)`.

In `lemely/web/deps.py` `get_sweeper`, add the argument
`run_recorder=JobRunRecorder(get_sessionmaker(settings)),` and import `JobRunRecorder` from
`lemely.db.billing_observability_repo`.

- [ ] **Step 5: Record HMAC failures in Phase 02's webhook router**

In `lemely/web/routers/paymob_webhooks.py` (Phase 02) add `Request` to the `fastapi` import, add
`from lemely.db.billing_observability_repo import record_webhook_failure`, and below `_VERIFIERS`:

```python
_FAILURE_KINDS = {"TRANSACTION": "transaction", "TOKEN": "token"}


def _record_hmac_failure(
    sm: sessionmaker[Session], request: Request, kind: str, payload: Mapping[str, Any] | None
) -> None:
    """Store a refused callback for the admin problem queue; never turn a 401 into a 500."""
    try:
        record_webhook_failure(
            sm,
            kind=kind,
            reason="hmac_mismatch",
            payload=payload,
            remote_addr=request.client.host if request.client else None,
        )
    except Exception:
        log.warning("paymob_webhook_failure_not_recorded", kind=kind, exc_info=True)
```

In `paymob_transaction_callback`, add the parameter `request: Request` (first, before `body`) and,
inside the `if not verifier(...)` branch, between the existing `log.error("paymob_hmac_mismatch", …)`
and `raise HTTPException(status.HTTP_401_UNAUTHORIZED, …)`, add:

```python
        _record_hmac_failure(sm, request, _FAILURE_KINDS[kind], obj)
```

Do the same in Phase 05's `paymob_subscription_webhook` (same module): add the parameter
`request: Request` (first), and between its `log.error("paymob_subscription_hmac_mismatch", …)` and
`raise HTTPException(status_code=401, detail="invalid hmac")` add:

```python
        _record_hmac_failure(deps.sessionmaker, request, "subscription", payload)
```

- [ ] **Step 6: Stamp callback arrival and add `reconcile_payment_now` in Phase 02's service**

In `lemely/db/billing_repo.py`:

1. Replace `apply_transaction_callback` with:

```python
    def apply_transaction_callback(self, obj: Mapping[str, Any]) -> None:
        """Apply a HMAC-verified transaction callback ``obj`` (spec §5.1 step 4, §6).

        Stamps ``callback_received_at`` before the dedupe check: a callback that arrives
        after reconcile already learned the result by inquiry is still a callback, and
        the admin "missing callback" queue (spec §8 area 3) must not list that payment.
        """
        order = obj.get("order")
        reference = order.get("merchant_order_id") if isinstance(order, dict) else None
        payment = self._payment_for_reference(reference)
        if payment is not None:
            payment.callback_received_at = self._now()
        self._apply_transaction(obj, source="callback", payment=payment)
```

   (`_apply_transaction` already skips its own lookup when `payment` is passed, and looks again —
   finding nothing — when it is `None`, so the unknown-reference log line is unchanged.)
2. Nothing else in `_apply_transaction` changes; the reconcile path (`source="inquiry"`) never
   touches `callback_received_at`.
3. Add, next to `MalformedCallback`:

```python
class PaymentNotFoundError(BillingError):
    """No payment has that id."""
```

4. Add to `class BillingService`, after `_reconcile_one`:

```python
    def reconcile_payment_now(self, payment_id: uuid.UUID, *, now: datetime) -> PaymentStatus:
        """Reconcile one payment now, ignoring its backoff schedule (admin trigger, spec §8).

        A payment that is no longer ``created`` or ``pending`` is returned untouched, so a
        double click cannot re-inquire or re-grant. The caller owns the transaction.
        """
        payment = self._session.get(Payment, payment_id, with_for_update=True)
        if payment is None:
            raise PaymentNotFoundError(str(payment_id))
        if payment.status in _OPEN:
            self._reconcile_one(payment, now=now)
        return payment.status
```

5. In `tests/test_billing_callbacks.py` (Phase 02), in the test that asserts
   `event.processed_at == FIXED_NOW`, add `assert payment.callback_received_at == FIXED_NOW` using
   that test's payment (load it with `session.get(Payment, <its payment id>)` if the test only
   holds the id). Add one test there: apply the same paid callback twice and assert the second
   (a dedupe no-op) still leaves `callback_received_at == FIXED_NOW`. In
   `tests/test_billing_reconcile.py`, in the test where an inquiry marks a payment paid, add
   `assert payment.callback_received_at is None`.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest --no-cov tests/test_billing_observability.py tests/test_scheduled_notifications.py tests/test_billing_callbacks.py tests/test_billing_reconcile.py tests/test_web_paymob_webhooks.py -v`
Expected: all pass. If a `test_scheduled_notifications.py` test builds a `Sweeper` positionally
past `email_daily_cap`, it still passes (new field is last, defaulted).

- [ ] **Step 8: Commit**

```bash
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files
P="lemely/db/billing_observability_repo.py lemely/web/scheduled_notifications.py lemely/web/deps.py lemely/web/routers/paymob_webhooks.py lemely/db/billing_repo.py tests/test_billing_observability.py tests/test_billing_callbacks.py tests/test_billing_reconcile.py"
git add $P
git commit -S -m "feat(admin): record sweeper runs, HMAC failures and callback arrival; reconcile one payment" -- $P
```

---

### Task 3: Record LLM cost per model for every usage job

**Files:**
- Create: `lemely/io/llm/model_costs.py`
- Modify: `lemely/db/billing_observability_repo.py` (add `record_job_model_costs`)
- Modify: `lemely/io/gemini.py` (`GeminiClient._record_spend`)
- Modify: `lemely/web/usage.py` (`UsageMeter`)
- Create: `tests/test_usage_model_costs.py`

**Interfaces:**
- Consumes: `UsageJobModelCost` (Task 1); `cost_scope`, `record_llm_cost`, `usd_decimal`, `MeteredJob.run`/`_finish`, `UsageMeter.job`/`authorize`, `UsageRequest`, `tests/usage_helpers.py` (Phase 04); `UsageLedger.settle` (Phase 01).
- Produces:
  - `model_cost_scope() -> ContextManager[dict[str, Decimal]]`, `record_model_cost(model: str, cost_usd: Decimal) -> None`.
  - `record_job_model_costs(session: Session, *, usage_job_id: UUID, costs: Mapping[str, Decimal]) -> int`.
  - After this task every settled usage job has one `usage_job_model_costs` row per model that cost money inside it.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_usage_model_costs.py`:

```python
"""Per-model LLM cost: accumulated inside a usage job, stored when the job settles."""

from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select

from lemely.core.usage_types import GrantScope, Payer
from lemely.db.billing_observability_repo import record_job_model_costs
from lemely.db.models.billing_ops import UsageJobModelCost
from lemely.db.models.enums import Role
from lemely.db.models.usage import GrantKind, UsageJob, UsageRate
from lemely.db.usage_ledger_repo import UsageLedger
from lemely.io.llm.model_costs import model_cost_scope, record_model_cost
from tests.admin_billing_db import NOW, add_user, billing_database, emptied_after

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture(scope="module")
def billing_db() -> Iterator[sessionmaker[Session]]:
    with billing_database() as factory:
        yield factory


@pytest.fixture
def sm(billing_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(billing_db)


def test_costs_outside_a_scope_are_dropped() -> None:
    record_model_cost("gemini-2.5-flash", Decimal("0.01"))
    with model_cost_scope() as costs:
        assert costs == {}


def test_costs_accumulate_per_model_inside_a_scope() -> None:
    with model_cost_scope() as costs:
        record_model_cost("gemini-2.5-flash", Decimal("0.002"))
        record_model_cost("claude-haiku-4-5", Decimal("0.001"))
        record_model_cost("gemini-2.5-flash", Decimal("0.003"))
        record_model_cost("gemini-2.5-flash", Decimal("0"))
    assert costs == {"gemini-2.5-flash": Decimal("0.005"), "claude-haiku-4-5": Decimal("0.001")}


def test_costs_recorded_in_a_worker_thread_reach_the_scope() -> None:
    async def run() -> dict[str, Decimal]:
        with model_cost_scope() as costs:
            await asyncio.to_thread(record_model_cost, "gemini-2.5-flash", Decimal("0.004"))
            return dict(costs)

    assert asyncio.run(run()) == {"gemini-2.5-flash": Decimal("0.004")}


def _settled_job(sm: sessionmaker[Session]) -> uuid.UUID:
    user = add_user(sm, Role.student)
    job_id = uuid.uuid4()
    with sm.begin() as session:
        session.add(UsageRate(version=1, action="mark_paper", units_per_usd=1000, effective_from=NOW - timedelta(days=1)))
        ledger = UsageLedger(session)
        ledger.issue_grant(
            owner_user_id=user, kind=GrantKind.adjustment, units=100, idempotency_key="seed",
            expires_at=NOW + timedelta(days=30), visible=True, effective_at=NOW - timedelta(days=1),
        )
        ledger.reserve(
            job_id=job_id, actor_user_id=user, action="mark_paper",
            payers=[Payer(owner_user_id=user, scope=GrantScope.CREDITS)],
            estimate_low=3, estimate_high=5, estimator_version=1, rate_version=1,
            teacher_member_id=None, expires_at=NOW + timedelta(minutes=10), now=NOW,
        )
        job = ledger.settle(job_id, actual_cost_usd=Decimal("0.004"), now=NOW)
        return job.id


def test_record_job_model_costs_stores_one_row_per_model_once(sm: sessionmaker[Session]) -> None:
    usage_job_id = _settled_job(sm)
    costs = {"gemini-2.5-flash": Decimal("0.0030004"), "claude-haiku-4-5": Decimal("0.001")}
    with sm.begin() as session:
        assert record_job_model_costs(session, usage_job_id=usage_job_id, costs=costs) == 2
        assert record_job_model_costs(session, usage_job_id=usage_job_id, costs=costs) == 0
    with sm() as session:
        rows = {r.model: r.cost_usd for r in session.scalars(select(UsageJobModelCost))}
    assert rows == {"gemini-2.5-flash": Decimal("0.003000"), "claude-haiku-4-5": Decimal("0.001000")}
```

Append the two integration tests that prove the metered job persists the costs. They use Phase
04's real API (`UsageMeter.job(UsageMeter.authorize(UsageRequest(...)))`) and its helpers in
`tests/usage_helpers.py`, on the migrated database (`migrated_sessionmaker` from `tests/conftest.py`).
Add these imports to the top block:

```python
from lemely.core.metered_actions import MeteredAction
from lemely.io.llm.cost_meter import record_llm_cost
from lemely.web.usage import UsageRequest
from tests.usage_helpers import enforcing_meter, give, jobs_for, seed_catalogue, seed_user
```

```python
def _model_rows(sm: sessionmaker[Session], usage_job_id: uuid.UUID) -> dict[str, Decimal]:
    with sm() as session:
        return {
            r.model: r.cost_usd
            for r in session.scalars(
                select(UsageJobModelCost).where(UsageJobModelCost.usage_job_id == usage_job_id)
            )
        }


def _mark_paper(student: uuid.UUID) -> UsageRequest:
    return UsageRequest(actor_user_id=student, actor_role=Role.student, action=MeteredAction.MARK_PAPER)


def test_a_settled_meter_job_stores_cost_per_model(migrated_sessionmaker: sessionmaker[Session]) -> None:
    sm = migrated_sessionmaker
    seed_catalogue(sm)
    student = seed_user(sm)
    give(sm, student, units=1000)
    meter = enforcing_meter(sm)

    with meter.job(meter.authorize(_mark_paper(student))):
        record_llm_cost(Decimal("0.003"))
        record_model_cost("gemini-2.5-flash", Decimal("0.002"))
        record_model_cost("claude-haiku-4-5", Decimal("0.001"))

    (job,) = jobs_for(sm, student)
    assert job.status is UsageJobStatus.settled
    assert _model_rows(sm, job.id) == {
        "gemini-2.5-flash": Decimal("0.002000"),
        "claude-haiku-4-5": Decimal("0.001000"),
    }


def test_a_released_meter_job_stores_no_model_costs(migrated_sessionmaker: sessionmaker[Session]) -> None:
    sm = migrated_sessionmaker
    seed_catalogue(sm)
    student = seed_user(sm)
    give(sm, student, units=1000)
    meter = enforcing_meter(sm)

    with pytest.raises(RuntimeError), meter.job(meter.authorize(_mark_paper(student))):
        record_llm_cost(Decimal("0.003"))
        record_model_cost("gemini-2.5-flash", Decimal("0.003"))
        raise RuntimeError("model call failed")

    (job,) = jobs_for(sm, student)
    assert job.status is UsageJobStatus.released
    assert _model_rows(sm, job.id) == {}
```

Also change the existing `from lemely.db.models.usage import GrantKind, UsageJob, UsageRate` line
to `from lemely.db.models.usage import GrantKind, UsageJobStatus, UsageRate` (`UsageJob` is no
longer used).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest --no-cov tests/test_usage_model_costs.py -v`
Expected: collection error, `No module named 'lemely.io.llm.model_costs'`.

- [ ] **Step 3: Write the accumulator**

Create `lemely/io/llm/model_costs.py`:

```python
"""Per-model LLM cost inside one usage job (admin margin view, spec §8 area 4).

Phase 04's ``cost_meter`` sums the job's total cost. This sums the same per-call
costs by model name, so the margin view can report cost by model. It is entered in
the same place as ``cost_scope()`` and fed beside every ``record_llm_cost`` call.

The bucket is a plain dict held in a contextvar: ``asyncio.to_thread`` copies the
context, and the copy points at the same dict, so worker-thread calls still land.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

_bucket: ContextVar[dict[str, Decimal] | None] = ContextVar("lemely_model_costs", default=None)


@contextmanager
def model_cost_scope() -> Iterator[dict[str, Decimal]]:
    """Collect per-model cost for the duration of the block; yields the live dict."""
    costs: dict[str, Decimal] = {}
    token = _bucket.set(costs)
    try:
        yield costs
    finally:
        _bucket.reset(token)


def record_model_cost(model: str, cost_usd: Decimal) -> None:
    """Add ``cost_usd`` to ``model`` in the active scope; a no-op outside one or for <= 0."""
    costs = _bucket.get()
    if costs is None or cost_usd <= 0:
        return
    costs[model] = costs.get(model, Decimal(0)) + cost_usd


__all__ = ["model_cost_scope", "record_model_cost"]
```

- [ ] **Step 4: Write the persistence function**

In `lemely/db/billing_observability_repo.py` add `import uuid` under `TYPE_CHECKING`, add
`from decimal import ROUND_HALF_UP, Decimal` and
`from lemely.db.models.billing_ops import UsageJobModelCost` at runtime, then:

```python
_SIX_PLACES = Decimal("0.000001")


def record_job_model_costs(
    session: Session, *, usage_job_id: uuid.UUID, costs: Mapping[str, Decimal]
) -> int:
    """Insert one row per model with a positive cost; a repeat for the same job is a no-op.

    Returns the number of rows inserted. Runs in the caller's transaction (the settle).
    """
    rows = [
        {
            "usage_job_id": usage_job_id,
            "model": model[:128],
            "cost_usd": cost.quantize(_SIX_PLACES, rounding=ROUND_HALF_UP),
        }
        for model, cost in sorted(costs.items())
        if cost > 0
    ]
    if not rows:
        return 0
    stmt = (
        pg_insert(UsageJobModelCost)
        .values(rows)
        .on_conflict_do_nothing(index_elements=["usage_job_id", "model"])
    )
    return int(session.execute(stmt).rowcount or 0)
```

Add `"record_job_model_costs"` to `__all__`.

- [ ] **Step 5: Feed the accumulator and persist it at settle**

1. In `lemely/io/gemini.py`, `GeminiClient._record_spend` (the one place both providers price a
   call; Phase 04 fed `record_llm_cost(usd_decimal(usd))` there), add directly after that line:

```python
            record_model_cost(model, usd_decimal(usd))
```

   and import `record_model_cost` from `lemely.io.llm.model_costs`. `model` is the model name that
   method already passes to `price_call`. Confirm with `grep -rn "record_llm_cost(" lemely/` that no
   other production call site exists; if one does, add the same line beside it.
2. In `lemely/web/usage.py` (Phase 04), import `model_cost_scope` from
   `lemely.io.llm.model_costs`, `record_job_model_costs` from
   `lemely.db.billing_observability_repo`, and `Mapping` under `TYPE_CHECKING`. Replace
   `MeteredJob.run` with:

```python
    @contextlib.contextmanager
    def run(self) -> Iterator[MeteredJob]:
        """Meter the enclosed work: settle on a normal exit, release on failure."""
        with cost_scope() as accumulator, model_cost_scope() as model_costs:
            try:
                yield self
            except BaseException:
                self._finish(accumulator.total_usd, settle=False)
                raise
            self._finish(
                accumulator.total_usd, settle=not self._abandoned, model_costs=model_costs
            )
```

   and in `_finish` change the signature to
   `def _finish(self, cost_usd: Decimal, *, settle: bool, model_costs: Mapping[str, Decimal] | None = None) -> None:`
   and its settle branch to:

```python
                if settle:
                    settled = ledger.settle(self.job_id, actual_cost_usd=cost_usd, now=now)
                    if model_costs:
                        record_job_model_costs(
                            session, usage_job_id=settled.id, costs=model_costs
                        )
```

   (`release()` keeps calling `self._finish(Decimal(0), settle=False)`.)

- [ ] **Step 6: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest --no-cov tests/test_usage_model_costs.py tests/test_web_usage_meter.py tests/test_cost_meter.py tests/architecture -v`
Expected: all pass. `tests/architecture` proves `lemely.io.llm.model_costs` imports nothing from
`lemely.db` or `lemely.web`.

- [ ] **Step 7: Commit**

```bash
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files
P="lemely/io/llm/model_costs.py lemely/db/billing_observability_repo.py lemely/web/usage.py $(grep -rln "record_model_cost(" lemely/ | grep -v model_costs.py) tests/test_usage_model_costs.py"
git add $P
git commit -S -m "feat(admin): record LLM cost per model for each settled usage job" -- $P
```

### Task 4: Admin billing router and the catalogue area

**Files:**
- Modify: `lemely/db/admin_billing_repo.py` (catalogue service)
- Create: `lemely/web/schemas_admin_billing.py`
- Create: `lemely/web/deps_admin_billing.py`
- Create: `lemely/web/routers/admin_billing.py`
- Modify: `lemely/web/app.py` (mount the router)
- Modify: `lemely/db/subscription_repo.py` (Phase 05 `sync_paymob_plan`: stamp synced price and frequency)
- Modify: `tests/admin_billing_db.py` (fake Paymob client, seeds, test client)
- Modify: `tests/test_authz_matrix_complete.py`
- Create: `tests/test_admin_billing_authz.py`
- Create: `tests/test_admin_billing_catalogue.py`

**Interfaces:**
- Consumes: `audited`, `snapshot`, `lock_idempotency_key`, error types, `AuditAction`, `AuditTarget` (Task 1); `PlanTier`, `PlanAudience`, `CreditPack`, `PaymobClient.create_plan` (Phase 02); `UsageRate`, `UsageEstimator`, `EstimatorInputKind` (Phase 01); `MeteredAction`, `SIGNUP_STUDENT_PACK`, `SIGNUP_TEACHER_PACK`, `TEACHER_SIGNUP_VALIDITY`, `ensure_usage_catalogue` (Phase 04); `get_paymob_client`, `PaymobSettings` (Phase 02); `sync_paymob_plan`, `PlanNotPurchasable` (`lemely.db.subscription_repo`), `paymob_frequency` (`lemely.core.subscription_rules`) (Phase 05).
- Produces:
  - `PlanTierFields`, `CreditPackFields`, `CatalogueSnapshot`, `PLAN_TIER_MUTABLE`, `CREDIT_PACK_MUTABLE`, `paymob_drift(tier) -> str`, `FreeAllowanceView(audience, pack, valid_days)`, `AdminCatalogueService(sessionmaker, client, paymob_settings, *, now=...)` with `catalogue()`, `create_plan_tier(fields, *, admin_user_id, reason)`, `update_plan_tier(plan_tier_id, changes, *, admin_user_id, reason)`, `sync_paymob_plan(plan_tier_id, *, admin_user_id, reason)`, `create_credit_pack(fields, *, admin_user_id, reason)`, `update_credit_pack(credit_pack_id, changes, *, admin_user_id, reason)`, `set_free_allowance(*, audience, units, admin_user_id, reason) -> FreeAllowanceView`, `add_usage_rate(*, action, units_per_usd, effective_from, admin_user_id, reason)`, `add_usage_estimator(*, action, input_kind, base_low, base_high, per_input_low, per_input_high, effective_from, admin_user_id, reason)`.
  - `router` (prefix `/api/admin/billing`), `admin_id(auth) -> UUID`, `mapped_errors()` context manager, `AdminAuth` dependency alias, in `lemely.web.routers.admin_billing`.
  - `get_admin_catalogue_service()` in `lemely.web.deps_admin_billing`.
  - `ReasonDTO`, `Reason` and the catalogue DTOs in `lemely.web.schemas_admin_billing`.
  - In `tests.admin_billing_db`: `TEST_PAYMOB`, `FakePaymobClient`, `add_plan_tier`, `add_credit_pack`, `audit_rows(factory, action)`, `service_overrides(factory, paymob)`, `admin_client(factory, admin_id, *, paymob=None)`.
  - Routes: `GET /catalogue`, `POST /tiers`, `PUT /tiers/{plan_tier_id}`, `POST /tiers/{plan_tier_id}/sync`, `POST /packs`, `PUT /packs/{credit_pack_id}`, `POST /rates`, `POST /estimators`, `PUT /free-allowances`.

- [ ] **Step 1: Extend the test helpers**

Append to `tests/admin_billing_db.py` (move the new imports into its import block):

```python
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from fastapi.testclient import TestClient

from lemely.db.admin_billing_repo import AdminCatalogueService
from lemely.db.models.admin_audit import AdminAuditLog
from lemely.db.models.billing import CreditPack, PlanAudience, PlanTier
from lemely.db.models.enums import PlanInterval
from lemely.runtime.config import Settings
from lemely.web.deps import AuthContext, get_auth_context
from lemely.web.deps_admin_billing import get_admin_catalogue_service
from lemely.web.routers import admin_billing
from tests.tutoring_app import app_with_routers


#: Paymob settings every service under test gets: a MOTO integration id so plan sync can run.
TEST_PAYMOB = Settings().paymob.model_copy(
    update={"moto_integration_id": 4569877, "notification_base_url": "https://lemelyig.com"}
)


@dataclass
class FakePaymobClient:
    """Duck-typed ``PaymobClient``: records every call; results are configurable.

    A result that is an exception instance is raised instead of returned.
    """

    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    next_plan_id: int = 9001
    create_plan_result: Mapping[str, Any] | BaseException | None = None
    refund_result: Mapping[str, Any] | BaseException = field(
        default_factory=lambda: {"id": 555, "success": True}
    )
    void_result: Mapping[str, Any] | BaseException = field(
        default_factory=lambda: {"id": 556, "success": True}
    )
    inquiry_result: Mapping[str, Any] | BaseException = field(default_factory=dict)
    cancel_result: Mapping[str, Any] | BaseException = field(
        default_factory=lambda: {"state": "canceled"}
    )

    @staticmethod
    def _out(result: Mapping[str, Any] | BaseException) -> Mapping[str, Any]:
        if isinstance(result, BaseException):
            raise result
        return result

    def create_plan(self, **kwargs: Any) -> Mapping[str, Any]:
        self.calls.append(("create_plan", kwargs))
        if self.create_plan_result is not None:
            return self._out(self.create_plan_result)
        plan_id = self.next_plan_id
        self.next_plan_id += 1
        return {"id": plan_id, **kwargs}

    def refund(self, **kwargs: Any) -> Mapping[str, Any]:
        self.calls.append(("refund", kwargs))
        return self._out(self.refund_result)

    def void(self, **kwargs: Any) -> Mapping[str, Any]:
        self.calls.append(("void", kwargs))
        return self._out(self.void_result)

    def inquire_by_transaction(self, transaction_id: int) -> Mapping[str, Any]:
        self.calls.append(("inquire_by_transaction", {"transaction_id": transaction_id}))
        return self._out(self.inquiry_result)

    def cancel_subscription(self, subscription_id: int) -> Mapping[str, Any]:
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
) -> uuid.UUID:
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
                is_active=True,
            )
        )
    return tier_id


def add_credit_pack(
    factory: sessionmaker[Session], *, code: str = "pack_500", units: int = 500, price_minor: int = 10000
) -> uuid.UUID:
    pack_id = uuid.uuid4()
    with factory.begin() as session:
        session.add(
            CreditPack(
                id=pack_id, code=code, name=code, units=units, price_minor=price_minor,
                currency="EGP", is_active=True,
            )
        )
    return pack_id


def audit_rows(factory: sessionmaker[Session], action: str) -> list[AdminAuditLog]:
    with factory() as session:
        return list(
            session.scalars(
                sa.select(AdminAuditLog)
                .where(AdminAuditLog.action == action)
                .order_by(AdminAuditLog.created_at, AdminAuditLog.id)
            )
        )


def service_overrides(
    factory: sessionmaker[Session], paymob: FakePaymobClient
) -> dict[Callable[..., object], Callable[[], object]]:
    """Every admin billing service bound to ``factory``, ``paymob`` and ``NOW``.

    Later tasks add one entry per service they introduce.
    """

    def clock() -> datetime:
        return NOW

    return {
        get_admin_catalogue_service: lambda: AdminCatalogueService(
            factory, paymob, TEST_PAYMOB, now=clock  # type: ignore[arg-type]
        ),
    }


def admin_client(
    factory: sessionmaker[Session], admin_id: uuid.UUID, *, paymob: FakePaymobClient | None = None
) -> TestClient:
    """A client on the admin billing router, signed in as ``admin_id`` (a platform admin)."""
    app = app_with_routers(admin_billing.router)
    app.dependency_overrides.update(service_overrides(factory, paymob or FakePaymobClient()))
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(
        user_id=str(admin_id), role=Role.platform_admin.value
    )
    return TestClient(app)
```

- [ ] **Step 2: Write the failing catalogue tests**

Create `tests/test_admin_billing_catalogue.py`:

```python
"""Admin catalogue (spec §8 area 1): every write is audited; versioned rows are never mutated."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select

from lemely.db.admin_billing_repo import AuditAction
from lemely.db.models.billing import CreditPack, PlanTier
from lemely.db.models.enums import Role
from lemely.db.models.usage import UsageRate
from lemely.db.usage_catalogue_repo import SIGNUP_STUDENT_PACK
from tests.admin_billing_db import (
    NOW,
    FakePaymobClient,
    add_plan_tier,
    add_user,
    admin_client,
    audit_rows,
    billing_database,
    emptied_after,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture(scope="module")
def billing_db() -> Iterator[sessionmaker[Session]]:
    with billing_database() as factory:
        yield factory


@pytest.fixture
def sm(billing_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(billing_db)


@pytest.fixture
def admin(sm: sessionmaker[Session]) -> uuid.UUID:
    return add_user(sm, Role.platform_admin)


TEACHER_TIER = {
    "code": "teacher_monthly",
    "name": "Teacher monthly",
    "audience": "teacher",
    "interval": "monthly",
    "priceMinor": 50000,
    "allowanceUnits": 5000,
    "includedSeats": 10,
    "seatAllowanceUnits": 300,
    "extraSeatPriceMinor": 2500,
    "reason": "launch catalogue",
}


def test_create_tier_is_audited_and_unsynced(sm: sessionmaker[Session], admin: uuid.UUID) -> None:
    resp = admin_client(sm, admin).post("/api/admin/billing/tiers", json=TEACHER_TIER)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["includedSeats"] == 10
    assert body["paymobDrift"] == "not_synced"
    [row] = audit_rows(sm, AuditAction.PLAN_TIER_CREATE)
    assert row.admin_user_id == admin
    assert row.target_id == uuid.UUID(body["id"])
    assert row.reason == "launch catalogue"
    assert row.before is None
    assert row.after["price_minor"] == 50000


def test_a_student_tier_with_seat_fields_is_refused(sm: sessionmaker[Session], admin: uuid.UUID) -> None:
    body = {**TEACHER_TIER, "code": "student_monthly", "audience": "student"}
    resp = admin_client(sm, admin).post("/api/admin/billing/tiers", json=body)

    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "seat_fields_on_student_tier"
    assert audit_rows(sm, AuditAction.PLAN_TIER_CREATE) == []


def test_a_duplicate_code_is_409(sm: sessionmaker[Session], admin: uuid.UUID) -> None:
    client = admin_client(sm, admin)
    assert client.post("/api/admin/billing/tiers", json=TEACHER_TIER).status_code == 200
    second = client.post("/api/admin/billing/tiers", json=TEACHER_TIER)
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "code_taken"


def test_a_blank_reason_is_422_and_writes_nothing(sm: sessionmaker[Session], admin: uuid.UUID) -> None:
    resp = admin_client(sm, admin).post("/api/admin/billing/tiers", json={**TEACHER_TIER, "reason": "  "})
    assert resp.status_code == 422
    with sm() as session:
        assert session.scalars(select(PlanTier)).all() == []


def test_sync_then_price_change_shows_drift(sm: sessionmaker[Session], admin: uuid.UUID) -> None:
    tier = add_plan_tier(sm, code="student_monthly", price_minor=20000)
    paymob = FakePaymobClient()
    client = admin_client(sm, admin, paymob=paymob)

    synced = client.post(f"/api/admin/billing/tiers/{tier}/sync", json={"reason": "first sync"})
    assert synced.status_code == 200, synced.text
    assert synced.json()["paymobPlanId"] == 9001
    assert synced.json()["paymobDrift"] == "in_sync"
    assert paymob.calls == [
        (
            "create_plan",
            {
                "name": "student_monthly",
                "frequency_days": 30,
                "amount_cents": 20000,
                "integration_id": 4569877,
                "webhook_url": "https://lemelyig.com/api/webhooks/paymob/subscription",
                "use_transaction_amount": True,
            },
        )
    ]

    update = {
        "name": "Student monthly",
        "priceMinor": 25000,
        "allowanceUnits": 1000,
        "includedSeats": 0,
        "seatAllowanceUnits": 0,
        "extraSeatPriceMinor": 0,
        "features": {},
        "isActive": True,
        "reason": "price rise",
    }
    changed = client.put(f"/api/admin/billing/tiers/{tier}", json=update)
    assert changed.status_code == 200, changed.text
    assert changed.json()["paymobDrift"] == "drifted"
    [row] = audit_rows(sm, AuditAction.PLAN_TIER_UPDATE)
    assert (row.before["price_minor"], row.after["price_minor"]) == (20000, 25000)
    [sync_row] = audit_rows(sm, AuditAction.PLAN_TIER_SYNC)
    assert sync_row.after["paymob_plan_id"] == 9001


def test_a_paymob_failure_leaves_the_tier_unsynced_and_unaudited(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    tier = add_plan_tier(sm)
    paymob = FakePaymobClient(create_plan_result=RuntimeError("paymob down"))
    resp = admin_client(sm, admin, paymob=paymob).post(
        f"/api/admin/billing/tiers/{tier}/sync", json={"reason": "sync"}
    )
    assert resp.status_code == 502
    with sm() as session:
        assert session.get(PlanTier, tier).paymob_plan_id is None
    assert audit_rows(sm, AuditAction.PLAN_TIER_SYNC) == []


def test_credit_pack_create_and_update_are_audited(sm: sessionmaker[Session], admin: uuid.UUID) -> None:
    client = admin_client(sm, admin)
    created = client.post(
        "/api/admin/billing/packs",
        json={"code": "pack_500", "name": "500 credits", "units": 500, "priceMinor": 10000, "reason": "launch"},
    )
    assert created.status_code == 200, created.text
    pack_id = created.json()["id"]
    updated = client.put(
        f"/api/admin/billing/packs/{pack_id}",
        json={"name": "500 credits", "units": 550, "priceMinor": 10000, "isActive": False, "reason": "promo"},
    )
    assert updated.status_code == 200
    assert (updated.json()["units"], updated.json()["isActive"]) == (550, False)
    assert len(audit_rows(sm, AuditAction.CREDIT_PACK_CREATE)) == 1
    [row] = audit_rows(sm, AuditAction.CREDIT_PACK_UPDATE)
    assert (row.before["units"], row.after["units"]) == (500, 550)


def test_free_allowances_edit_the_signup_packs(sm: sessionmaker[Session], admin: uuid.UUID) -> None:
    client = admin_client(sm, admin)
    student = client.put(
        "/api/admin/billing/free-allowances",
        json={"audience": "student", "units": 300, "reason": "three papers, not two"},
    )
    teacher = client.put(
        "/api/admin/billing/free-allowances",
        json={"audience": "teacher", "units": 2500, "reason": "launch promo"},
    )
    assert student.status_code == 200, student.text
    assert (student.json()["units"], student.json()["validDays"]) == (300, None)
    assert (teacher.json()["units"], teacher.json()["validDays"]) == (2500, 30)
    with sm() as session:
        pack = session.scalars(select(CreditPack).where(CreditPack.code == SIGNUP_STUDENT_PACK)).one()
        assert (pack.units, pack.price_minor, pack.is_active) == (300, 0, False)
    rows = audit_rows(sm, AuditAction.FREE_ALLOWANCE_UPDATE)
    assert [r.after["units"] for r in rows] == [300, 2500]
    assert rows[0].before["units"] == 250  # Phase 04's DEFAULT_SIGNUP_UNITS for students
    body = client.get("/api/admin/billing/catalogue").json()
    assert sorted(f["audience"] for f in body["freeAllowances"]) == ["student", "teacher"]
    assert body["creditPacks"] == []  # signup packs are never listed as sellable packs


def test_signup_packs_cannot_be_edited_as_sellable_packs(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    client = admin_client(sm, admin)
    pack_id = client.put(
        "/api/admin/billing/free-allowances",
        json={"audience": "student", "units": 300, "reason": "seed"},
    ).json()["creditPackId"]
    resp = client.put(
        f"/api/admin/billing/packs/{pack_id}",
        json={"name": "free", "units": 300, "priceMinor": 1000, "isActive": True, "reason": "oops"},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "signup_pack_use_free_allowances"


def test_a_backdated_version_is_refused(sm: sessionmaker[Session], admin: uuid.UUID) -> None:
    resp = admin_client(sm, admin).post(
        "/api/admin/billing/rates",
        json={
            "action": "mark_paper",
            "unitsPerUsd": 1000,
            "effectiveFrom": (NOW - timedelta(days=1)).isoformat(),
            "reason": "backdate",
        },
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "effective_from_in_past"


def test_usage_rates_version_per_action_and_never_mutate(sm: sessionmaker[Session], admin: uuid.UUID) -> None:
    client = admin_client(sm, admin)
    for action, rate in (("mark_paper", 1000), ("regrade", 800), ("mark_paper", 1200)):
        resp = client.post(
            "/api/admin/billing/rates",
            json={"action": action, "unitsPerUsd": rate, "reason": "tune"},
        )
        assert resp.status_code == 200, resp.text
    with sm() as session:
        rows = session.scalars(select(UsageRate).order_by(UsageRate.action, UsageRate.version)).all()
    assert [(r.action, r.version, r.units_per_usd) for r in rows] == [
        ("mark_paper", 1, 1000),
        ("mark_paper", 2, 1200),
        ("regrade", 1, 800),
    ]
    assert len(audit_rows(sm, AuditAction.USAGE_RATE_VERSION)) == 3


def test_an_unknown_action_is_refused(sm: sessionmaker[Session], admin: uuid.UUID) -> None:
    resp = admin_client(sm, admin).post(
        "/api/admin/billing/rates", json={"action": "mine_bitcoin", "unitsPerUsd": 1, "reason": "x y z"}
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "unknown_action"


def test_estimator_low_above_high_is_refused(sm: sessionmaker[Session], admin: uuid.UUID) -> None:
    resp = admin_client(sm, admin).post(
        "/api/admin/billing/estimators",
        json={
            "action": "mark_paper", "inputKind": "pages", "baseLow": 5, "baseHigh": 3,
            "perInputLow": 1, "perInputHigh": 2, "reason": "tune",
        },
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "low_above_high"


def test_get_catalogue_lists_everything(sm: sessionmaker[Session], admin: uuid.UUID) -> None:
    add_plan_tier(sm)
    client = admin_client(sm, admin)
    client.post(
        "/api/admin/billing/estimators",
        json={
            "action": "mark_paper", "inputKind": "pages", "baseLow": 1, "baseHigh": 2,
            "perInputLow": 1, "perInputHigh": 2, "reason": "seed",
        },
    )
    body = client.get("/api/admin/billing/catalogue").json()
    assert [t["code"] for t in body["planTiers"]] == ["student_monthly"]
    assert [(e["action"], e["version"]) for e in body["usageEstimators"]] == [("mark_paper", 1)]
    assert body["creditPacks"] == [] and body["freeAllowances"] == [] and body["usageRates"] == []
```

Create `tests/test_admin_billing_authz.py`:

```python
"""Every admin billing route is platform_admin only (spec §7), proven by request and by wiring.

``tests/test_authz_matrix_complete.py`` covers the whole app; this file pins the
billing surface itself so a route added here without a matching ``PLANNED`` entry
fails close to the change.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from lemely.runtime.config import Settings
from lemely.web import create_app
from lemely.web.deps import AuthContext, get_auth_context, get_settings
from lemely.web.routers import admin_billing
from tests.test_authz_matrix_complete import _concrete, _wired_guard
from tests.tutoring_app import flatten_routes

if TYPE_CHECKING:
    from pathlib import Path

    from fastapi import FastAPI

P = "/api/admin/billing"
PLANNED: set[tuple[str, str]] = {
    ("GET", f"{P}/catalogue"),
    ("POST", f"{P}/tiers"),
    ("PUT", f"{P}/tiers/{{plan_tier_id}}"),
    ("POST", f"{P}/tiers/{{plan_tier_id}}/sync"),
    ("POST", f"{P}/packs"),
    ("PUT", f"{P}/packs/{{credit_pack_id}}"),
    ("POST", f"{P}/rates"),
    ("POST", f"{P}/estimators"),
    ("PUT", f"{P}/free-allowances"),
}
ROUTES = sorted(
    (method, route.path)
    for route in flatten_routes(admin_billing.router)
    for method in route.methods
    if method not in {"HEAD", "OPTIONS"}
)
NON_ADMIN_ROLES = ("student", "parent", "teacher", "school_admin")


@pytest.fixture
def app(tmp_path: Path) -> FastAPI:
    data = Settings().model_dump()
    data["paths"]["output_dir"] = tmp_path / "outputs"
    settings = Settings.model_validate(data)
    application = create_app()
    application.dependency_overrides[get_settings] = lambda: settings
    return application


def test_the_router_serves_exactly_the_planned_routes() -> None:
    assert set(ROUTES) == PLANNED


def test_every_route_is_wired_to_platform_admin_alone() -> None:
    for route in flatten_routes(admin_billing.router):
        assert _wired_guard(route) == frozenset({"platform_admin"}), route.path


@pytest.mark.parametrize(("method", "path"), ROUTES, ids=str)
def test_anonymous_caller_is_401(app: FastAPI, method: str, path: str) -> None:
    assert TestClient(app).request(method, _concrete(path)).status_code == 401


@pytest.mark.parametrize(
    ("method", "path", "role"),
    [(m, p, r) for m, p in ROUTES for r in NON_ADMIN_ROLES],
    ids=str,
)
def test_every_other_role_is_403(app: FastAPI, method: str, path: str, role: str) -> None:
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(user_id="u1", role=role)
    assert TestClient(app).request(method, _concrete(path)).status_code == 403
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest --no-cov tests/test_admin_billing_catalogue.py tests/test_admin_billing_authz.py -v`
Expected: collection errors (`AdminCatalogueService`,
`lemely.web.routers.admin_billing` do not exist).

- [ ] **Step 4: Write the catalogue service**

Append to `lemely/db/admin_billing_repo.py` (merge imports into its import block; add the new
names to `__all__`):

```python
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, timedelta

from sqlalchemy.exc import IntegrityError

from lemely.core.metered_actions import MeteredAction
from lemely.db.models.billing import CreditPack, PlanAudience, PlanTier
from lemely.db.models.enums import PlanInterval
from lemely.db.models.usage import EstimatorInputKind, UsageEstimator, UsageRate
from lemely.core.subscription_rules import paymob_frequency
from lemely.db.subscription_repo import PlanNotPurchasable
from lemely.db.subscription_repo import sync_paymob_plan as link_paymob_plan
from lemely.db.usage_catalogue_repo import (
    SIGNUP_STUDENT_PACK,
    SIGNUP_TEACHER_PACK,
    TEACHER_SIGNUP_VALIDITY,
    ensure_usage_catalogue,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import sessionmaker

    from lemely.io.paymob.client import PaymobClient
    from lemely.runtime.config import PaymobSettings

# A version may start a little in the past (clock skew between admin and server), never more.
_BACKDATE_TOLERANCE = timedelta(minutes=5)

PLAN_TIER_MUTABLE = (
    "name",
    "price_minor",
    "allowance_units",
    "included_seats",
    "seat_allowance_units",
    "extra_seat_price_minor",
    "features",
    "is_active",
)
_PLAN_TIER_AUDIT = (
    "code",
    "name",
    "audience",
    "interval",
    "price_minor",
    "currency",
    "allowance_units",
    "included_seats",
    "seat_allowance_units",
    "extra_seat_price_minor",
    "features",
    "is_active",
    "paymob_plan_id",
    "paymob_plan_synced_price_minor",
    "paymob_plan_synced_frequency",
)
CREDIT_PACK_MUTABLE = ("name", "units", "price_minor", "is_active")
_CREDIT_PACK_AUDIT = ("code", "name", "units", "price_minor", "currency", "is_active")
#: Phase 04 deviation 7: the free start is two non-sellable credit packs.
_SIGNUP_CODES = {"student": SIGNUP_STUDENT_PACK, "teacher": SIGNUP_TEACHER_PACK}
_SIGNUP_AUDIENCE = {code: audience for audience, code in _SIGNUP_CODES.items()}
_RATE_AUDIT = ("version", "action", "units_per_usd", "effective_from")
_ESTIMATOR_AUDIT = (
    "version",
    "action",
    "input_kind",
    "base_low",
    "base_high",
    "per_input_low",
    "per_input_high",
    "effective_from",
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class PlanTierFields:
    code: str
    name: str
    audience: PlanAudience
    interval: PlanInterval
    price_minor: int
    currency: str
    allowance_units: int
    included_seats: int
    seat_allowance_units: int
    extra_seat_price_minor: int
    features: dict[str, object]
    is_active: bool


@dataclass(frozen=True, slots=True)
class CreditPackFields:
    code: str
    name: str
    units: int
    price_minor: int
    currency: str
    is_active: bool


@dataclass(frozen=True, slots=True)
class FreeAllowanceView:
    """The student free allowance or teacher signup credits, and the pack that stores it."""

    audience: str
    pack: CreditPack
    valid_days: int | None


def _free_allowance_view(audience: str, pack: CreditPack) -> FreeAllowanceView:
    days = None if audience == "student" else TEACHER_SIGNUP_VALIDITY.days
    return FreeAllowanceView(audience=audience, pack=pack, valid_days=days)


@dataclass(frozen=True, slots=True)
class CatalogueSnapshot:
    plan_tiers: list[PlanTier]
    credit_packs: list[CreditPack]
    free_allowances: list[FreeAllowanceView]
    usage_rates: list[UsageRate]
    usage_estimators: list[UsageEstimator]


def paymob_drift(tier: PlanTier) -> str:
    """``not_synced`` (no Paymob plan), ``unverified`` (plan set outside the admin sync),
    ``drifted`` (price or interval changed since the sync) or ``in_sync``."""
    if tier.paymob_plan_id is None:
        return "not_synced"
    if tier.paymob_plan_synced_price_minor is None or tier.interval is None:
        return "unverified"
    if (
        tier.paymob_plan_synced_price_minor != tier.price_minor
        or tier.paymob_plan_synced_frequency != paymob_frequency(tier.interval.value)
    ):
        return "drifted"
    return "in_sync"


def _check_tier_shape(tier: PlanTier) -> None:
    if tier.audience is PlanAudience.student and (
        (tier.included_seats or 0) or (tier.seat_allowance_units or 0) or (tier.extra_seat_price_minor or 0)
    ):
        raise AdminInvalidError("seat_fields_on_student_tier", "Student tiers carry no seats.")


def require_reason(reason: str) -> None:
    if not (reason or "").strip():
        raise ReasonRequiredError


class AdminCatalogueService:
    """Plan tiers, credit packs, free allowances, usage rates and estimators (spec §8 area 1).

    Tiers and packs are edited in place (their history is the audit log). Rates and
    estimators are versioned: every write is a new row with the next version for its
    action, and old rows are never touched. Free allowances are the two signup packs
    (Phase 04 deviation 7), edited only through :meth:`set_free_allowance`.
    """

    def __init__(
        self,
        sessionmaker: sessionmaker[Session],
        client: PaymobClient,
        paymob_settings: PaymobSettings,
        *,
        now: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._sm = sessionmaker
        self._client = client
        self._settings = paymob_settings
        self._now = now

    def catalogue(self) -> CatalogueSnapshot:
        with self._sm() as s:
            packs = list(s.scalars(select(CreditPack).order_by(CreditPack.code)))
            signup = {p.code: p for p in packs if p.code in _SIGNUP_AUDIENCE}
            return CatalogueSnapshot(
                plan_tiers=list(s.scalars(select(PlanTier).order_by(PlanTier.code))),
                credit_packs=[p for p in packs if p.code not in _SIGNUP_AUDIENCE],
                free_allowances=[
                    _free_allowance_view(audience, signup[code])
                    for audience, code in _SIGNUP_CODES.items()
                    if code in signup
                ],
                usage_rates=list(
                    s.scalars(select(UsageRate).order_by(UsageRate.action, UsageRate.version.desc()))
                ),
                usage_estimators=list(
                    s.scalars(
                        select(UsageEstimator).order_by(
                            UsageEstimator.action, UsageEstimator.version.desc()
                        )
                    )
                ),
            )

    # -- tiers ---------------------------------------------------------------

    def create_plan_tier(
        self, fields: PlanTierFields, *, admin_user_id: uuid.UUID, reason: str
    ) -> PlanTier:
        require_reason(reason)
        try:
            with self._sm.begin() as s:
                if s.scalar(select(PlanTier.id).where(PlanTier.code == fields.code)) is not None:
                    raise AdminConflictError("code_taken", f"A tier with code {fields.code} exists.")
                tier = PlanTier(**asdict(fields))
                _check_tier_shape(tier)
                s.add(tier)
                s.flush()
                audited(
                    s, admin_user_id, AuditAction.PLAN_TIER_CREATE, AuditTarget.PLAN_TIER, tier.id,
                    reason, None, snapshot(tier, _PLAN_TIER_AUDIT),
                )
                return tier
        except IntegrityError as exc:
            raise AdminConflictError("code_taken", f"A tier with code {fields.code} exists.") from exc

    def update_plan_tier(
        self,
        plan_tier_id: uuid.UUID,
        changes: Mapping[str, object],
        *,
        admin_user_id: uuid.UUID,
        reason: str,
    ) -> PlanTier:
        require_reason(reason)
        if set(changes) - set(PLAN_TIER_MUTABLE):
            raise AdminInvalidError("immutable_field", "code, audience, interval and currency are fixed.")
        with self._sm.begin() as s:
            tier = s.get(PlanTier, plan_tier_id, with_for_update=True)
            if tier is None:
                raise AdminNotFoundError("plan_tier_not_found")
            before = snapshot(tier, _PLAN_TIER_AUDIT)
            for name, value in changes.items():
                setattr(tier, name, value)
            _check_tier_shape(tier)
            s.flush()
            audited(
                s, admin_user_id, AuditAction.PLAN_TIER_UPDATE, AuditTarget.PLAN_TIER, tier.id,
                reason, before, snapshot(tier, _PLAN_TIER_AUDIT),
            )
            return tier

    def sync_paymob_plan(
        self, plan_tier_id: uuid.UUID, *, admin_user_id: uuid.UUID, reason: str
    ) -> PlanTier:
        """Create a new Paymob plan at the tier's current price and interval, and link it.

        Delegates to Phase 05's ``sync_paymob_plan(..., force_new=True)`` (index R9), which
        locks the tier, calls Paymob and stamps the synced price and frequency. A Paymob
        failure rolls the whole transaction back: no link, no audit row.
        """
        require_reason(reason)
        try:
            with self._sm.begin() as s:
                tier = s.get(PlanTier, plan_tier_id, with_for_update=True)
                if tier is None:
                    raise AdminNotFoundError("plan_tier_not_found")
                if tier.price_minor <= 0:
                    raise AdminInvalidError("not_billable", "A free tier has no Paymob plan.")
                before = snapshot(tier, _PLAN_TIER_AUDIT)
                link_paymob_plan(s, self._client, self._settings, plan_tier_id, force_new=True)
                s.flush()
                audited(
                    s, admin_user_id, AuditAction.PLAN_TIER_SYNC, AuditTarget.PLAN_TIER, tier.id,
                    reason, before, snapshot(tier, _PLAN_TIER_AUDIT),
                )
                return tier
        except PlanNotPurchasable as exc:
            raise AdminInvalidError("not_billable", str(exc)) from exc
        except AdminBillingError:
            raise
        except Exception as exc:  # noqa: BLE001 - any Paymob failure is a 502 with no DB change
            raise PaymobCallError("paymob_plan_create_failed", str(exc)) from exc

    # -- packs ---------------------------------------------------------------

    def create_credit_pack(
        self, fields: CreditPackFields, *, admin_user_id: uuid.UUID, reason: str
    ) -> CreditPack:
        require_reason(reason)
        if fields.code in _SIGNUP_AUDIENCE:
            raise AdminConflictError("reserved_code", "Signup packs are set through free allowances.")
        try:
            with self._sm.begin() as s:
                if s.scalar(select(CreditPack.id).where(CreditPack.code == fields.code)) is not None:
                    raise AdminConflictError("code_taken", f"A pack with code {fields.code} exists.")
                pack = CreditPack(**asdict(fields))
                s.add(pack)
                s.flush()
                audited(
                    s, admin_user_id, AuditAction.CREDIT_PACK_CREATE, AuditTarget.CREDIT_PACK,
                    pack.id, reason, None, snapshot(pack, _CREDIT_PACK_AUDIT),
                )
                return pack
        except IntegrityError as exc:
            raise AdminConflictError("code_taken", f"A pack with code {fields.code} exists.") from exc

    def update_credit_pack(
        self,
        credit_pack_id: uuid.UUID,
        changes: Mapping[str, object],
        *,
        admin_user_id: uuid.UUID,
        reason: str,
    ) -> CreditPack:
        require_reason(reason)
        if set(changes) - set(CREDIT_PACK_MUTABLE):
            raise AdminInvalidError("immutable_field", "code and currency are fixed.")
        with self._sm.begin() as s:
            pack = s.get(CreditPack, credit_pack_id, with_for_update=True)
            if pack is None:
                raise AdminNotFoundError("credit_pack_not_found")
            if pack.code in _SIGNUP_AUDIENCE:
                raise AdminConflictError(
                    "signup_pack_use_free_allowances", "Edit signup packs through free allowances."
                )
            before = snapshot(pack, _CREDIT_PACK_AUDIT)
            for name, value in changes.items():
                setattr(pack, name, value)
            s.flush()
            audited(
                s, admin_user_id, AuditAction.CREDIT_PACK_UPDATE, AuditTarget.CREDIT_PACK, pack.id,
                reason, before, snapshot(pack, _CREDIT_PACK_AUDIT),
            )
            return pack

    # -- versioned rows ------------------------------------------------------

    def _effective(self, effective_from: datetime | None) -> datetime:
        now = self._now()
        if effective_from is None:
            return now
        if effective_from < now - _BACKDATE_TOLERANCE:
            raise AdminInvalidError("effective_from_in_past", "A new version cannot start in the past.")
        return effective_from

    def set_free_allowance(
        self, *, audience: str, units: int, admin_user_id: uuid.UUID, reason: str
    ) -> FreeAllowanceView:
        """Set the units of the student free allowance or the teacher signup credits.

        Phase 04's ``ensure_usage_catalogue`` creates the signup packs on first use;
        calling it here makes the first admin edit work on a fresh database too.
        """
        require_reason(reason)
        code = _SIGNUP_CODES.get(audience)
        if code is None:
            raise AdminInvalidError("unknown_audience")
        with self._sm.begin() as s:
            ensure_usage_catalogue(s, now=self._now())
            pack = s.scalars(
                select(CreditPack).where(CreditPack.code == code).with_for_update()
            ).one()
            before = snapshot(pack, _CREDIT_PACK_AUDIT)
            pack.units = units
            try:
                s.flush()
            except IntegrityError as exc:
                raise AdminInvalidError("units_rejected", "The database refused these units.") from exc
            audited(
                s, admin_user_id, AuditAction.FREE_ALLOWANCE_UPDATE, AuditTarget.CREDIT_PACK,
                pack.id, reason, before, snapshot(pack, _CREDIT_PACK_AUDIT),
            )
            return _free_allowance_view(audience, pack)

    def add_usage_rate(
        self,
        *,
        action: str,
        units_per_usd: int,
        effective_from: datetime | None,
        admin_user_id: uuid.UUID,
        reason: str,
    ) -> UsageRate:
        require_reason(reason)
        _require_metered(action)
        starts = self._effective(effective_from)
        with self._sm.begin() as s:
            lock_idempotency_key(s, f"catalogue-version:usage_rates:{action}")
            latest = s.scalars(
                select(UsageRate)
                .where(UsageRate.action == action)
                .order_by(UsageRate.version.desc())
                .limit(1)
            ).first()
            row = UsageRate(
                version=(latest.version if latest else 0) + 1,
                action=action,
                units_per_usd=units_per_usd,
                effective_from=starts,
            )
            s.add(row)
            s.flush()
            audited(
                s, admin_user_id, AuditAction.USAGE_RATE_VERSION, AuditTarget.USAGE_RATE, row.id,
                reason, snapshot(latest, _RATE_AUDIT) if latest else None, snapshot(row, _RATE_AUDIT),
            )
            return row

    def add_usage_estimator(
        self,
        *,
        action: str,
        input_kind: EstimatorInputKind,
        base_low: int,
        base_high: int,
        per_input_low: int,
        per_input_high: int,
        effective_from: datetime | None,
        admin_user_id: uuid.UUID,
        reason: str,
    ) -> UsageEstimator:
        require_reason(reason)
        _require_metered(action)
        if base_low > base_high or per_input_low > per_input_high:
            raise AdminInvalidError("low_above_high", "Each low bound must not exceed its high bound.")
        if input_kind is EstimatorInputKind.none and (per_input_low or per_input_high):
            raise AdminInvalidError("per_input_without_input_kind")
        starts = self._effective(effective_from)
        with self._sm.begin() as s:
            lock_idempotency_key(s, f"catalogue-version:usage_estimators:{action}")
            latest = s.scalars(
                select(UsageEstimator)
                .where(UsageEstimator.action == action)
                .order_by(UsageEstimator.version.desc())
                .limit(1)
            ).first()
            row = UsageEstimator(
                version=(latest.version if latest else 0) + 1,
                action=action,
                input_kind=input_kind,
                base_low=base_low,
                base_high=base_high,
                per_input_low=per_input_low,
                per_input_high=per_input_high,
                effective_from=starts,
            )
            s.add(row)
            s.flush()
            audited(
                s, admin_user_id, AuditAction.USAGE_ESTIMATOR_VERSION, AuditTarget.USAGE_ESTIMATOR,
                row.id, reason,
                snapshot(latest, _ESTIMATOR_AUDIT) if latest else None,
                snapshot(row, _ESTIMATOR_AUDIT),
            )
            return row


def _require_metered(action: str) -> None:
    try:
        MeteredAction(action)
    except ValueError as exc:
        raise AdminInvalidError("unknown_action", f"{action} is not a metered action.") from exc
```

(The existing `if TYPE_CHECKING:` block gains the two new imports; do not create a second one.)

- [ ] **Step 5: Stamp the synced price and frequency in Phase 05's helper (index R9)**

In `lemely/db/subscription_repo.py`, in `sync_paymob_plan`, replace the line
`tier.paymob_plan_id = int(created["id"])` with:

```python
    tier.paymob_plan_id = int(created["id"])
    # Phase 07 drift warning: what Paymob was sent, compared with the tier later.
    tier.paymob_plan_synced_price_minor = tier.price_minor
    tier.paymob_plan_synced_frequency = paymob_frequency(tier.interval.value)
```

In Phase 05's `tests/test_subscription_plan_sync.py`, in the test that asserts the plan is created
and linked, add `assert (tier.paymob_plan_synced_price_minor, tier.paymob_plan_synced_frequency) ==
(tier.price_minor, 30)` using that test's tier row (reload it with `session.get(PlanTier, <id>)`
if the test holds only the id; use 360 if that test's tier is yearly).

- [ ] **Step 6: Write the DTOs**

Create `lemely/web/schemas_admin_billing.py`:

```python
"""DTOs for the admin billing surface (``/api/admin/billing/*``, spec §8).

camelCase on the wire, ``extra="forbid"`` (``ApiModel``). Money is integer piasters,
usage integer units, USD cost a decimal string (never a float that rounds).
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - pydantic resolves annotations at runtime
from typing import Annotated, Any, Literal

from pydantic import Field, StringConstraints

from lemely.web.schemas_admin import ApiModel

Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=2000)]
NonNegative = Annotated[int, Field(ge=0)]
Positive = Annotated[int, Field(gt=0)]
Code = Annotated[str, StringConstraints(pattern=r"^[a-z0-9_]{2,64}$")]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]


class ReasonDTO(ApiModel):
    reason: Reason


# -- catalogue ------------------------------------------------------------------


class PlanTierDTO(ApiModel):
    id: str
    code: str
    name: str
    audience: str
    interval: str | None
    priceMinor: int
    currency: str
    allowanceUnits: int
    includedSeats: int
    seatAllowanceUnits: int
    extraSeatPriceMinor: int
    features: dict[str, Any]
    isActive: bool
    paymobPlanId: int | None
    paymobDrift: Literal["in_sync", "not_synced", "unverified", "drifted"]


class CreditPackDTO(ApiModel):
    id: str
    code: str
    name: str
    units: int
    priceMinor: int
    currency: str
    isActive: bool


class FreeAllowanceDTO(ApiModel):
    audience: Literal["student", "teacher"]
    creditPackId: str
    units: int
    validDays: int | None


class UsageRateDTO(ApiModel):
    id: str
    version: int
    action: str
    unitsPerUsd: int
    effectiveFrom: datetime


class UsageEstimatorDTO(ApiModel):
    id: str
    version: int
    action: str
    inputKind: str
    baseLow: int
    baseHigh: int
    perInputLow: int
    perInputHigh: int
    effectiveFrom: datetime


class AdminCatalogueDTO(ApiModel):
    planTiers: list[PlanTierDTO]
    creditPacks: list[CreditPackDTO]
    freeAllowances: list[FreeAllowanceDTO]
    usageRates: list[UsageRateDTO]
    usageEstimators: list[UsageEstimatorDTO]


class PlanTierCreateDTO(ApiModel):
    code: Code
    name: Name
    audience: Literal["student", "teacher"]
    interval: Literal["monthly", "yearly"]
    priceMinor: NonNegative
    currency: Literal["EGP"] = "EGP"
    allowanceUnits: NonNegative
    includedSeats: NonNegative = 0
    seatAllowanceUnits: NonNegative = 0
    extraSeatPriceMinor: NonNegative = 0
    features: dict[str, Any] = Field(default_factory=dict)
    isActive: bool = True
    reason: Reason


class PlanTierUpdateDTO(ApiModel):
    name: Name
    priceMinor: NonNegative
    allowanceUnits: NonNegative
    includedSeats: NonNegative
    seatAllowanceUnits: NonNegative
    extraSeatPriceMinor: NonNegative
    features: dict[str, Any]
    isActive: bool
    reason: Reason


class CreditPackCreateDTO(ApiModel):
    code: Code
    name: Name
    units: Positive
    priceMinor: Positive
    currency: Literal["EGP"] = "EGP"
    isActive: bool = True
    reason: Reason


class CreditPackUpdateDTO(ApiModel):
    name: Name
    units: Positive
    priceMinor: Positive
    isActive: bool
    reason: Reason


class FreeAllowanceUpdateDTO(ApiModel):
    audience: Literal["student", "teacher"]
    units: NonNegative
    reason: Reason


class UsageRateVersionDTO(ApiModel):
    action: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    unitsPerUsd: Positive
    effectiveFrom: datetime | None = None
    reason: Reason


class UsageEstimatorVersionDTO(ApiModel):
    action: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    inputKind: Literal["pages", "marks", "questions", "none"]
    baseLow: NonNegative
    baseHigh: NonNegative
    perInputLow: NonNegative
    perInputHigh: NonNegative
    effectiveFrom: datetime | None = None
    reason: Reason
```

- [ ] **Step 7: Write the dependency module**

Create `lemely/web/deps_admin_billing.py`:

```python
"""Dependencies for the admin billing router; tests override each one.

Built per request: a service holds only the process sessionmaker and the Paymob
client, both cached elsewhere, so construction is free.
"""

from __future__ import annotations

from lemely.db.admin_billing_repo import AdminCatalogueService
from lemely.db.session import get_sessionmaker
from lemely.web.deps import get_settings
from lemely.web.deps_billing import get_paymob_client


def get_admin_catalogue_service() -> AdminCatalogueService:
    settings = get_settings()
    return AdminCatalogueService(get_sessionmaker(settings), get_paymob_client(), settings.paymob)


__all__ = ["get_admin_catalogue_service"]
```

- [ ] **Step 8: Write the router**

Create `lemely/web/routers/admin_billing.py`:

```python
"""Admin billing console API (spec §8) under ``/api/admin/billing``.

Gated at router level to ``platform_admin`` alone, like ``admin.py``: every route
added here inherits the 401-then-403 guard by construction. Handlers that write also
take ``AdminAuth`` to read the caller's id for the audit row; the two guards are the
same role set, so the effective guard is unchanged.

Every write requires ``reason`` and is audited by the service in the same
transaction as the change. Errors leave as ``{"code", "message"}`` in ``detail``.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from lemely.db.admin_billing_repo import (
    AdminBillingError,
    AdminCatalogueService,
    AdminConflictError,
    AdminInvalidError,
    AdminNotFoundError,
    CreditPackFields,
    FreeAllowanceView,
    PaymobCallError,
    PlanTierFields,
    paymob_drift,
)
from lemely.db.models.billing import CreditPack, PlanAudience, PlanTier
from lemely.db.models.enums import PlanInterval, Role
from lemely.db.models.usage import EstimatorInputKind, UsageEstimator, UsageRate
from lemely.web.deps import AuthContext, require_role
from lemely.web.deps_admin_billing import get_admin_catalogue_service
from lemely.web.schemas_admin_billing import (
    AdminCatalogueDTO,
    CreditPackCreateDTO,
    CreditPackDTO,
    CreditPackUpdateDTO,
    FreeAllowanceDTO,
    FreeAllowanceUpdateDTO,
    PlanTierCreateDTO,
    PlanTierDTO,
    PlanTierUpdateDTO,
    ReasonDTO,
    UsageEstimatorDTO,
    UsageEstimatorVersionDTO,
    UsageRateDTO,
    UsageRateVersionDTO,
)

router = APIRouter(
    prefix="/api/admin/billing",
    dependencies=[Depends(require_role(Role.platform_admin))],
)

AdminAuth = Annotated[AuthContext, Depends(require_role(Role.platform_admin))]
CatalogueService = Annotated[AdminCatalogueService, Depends(get_admin_catalogue_service)]

_STATUS: tuple[tuple[type[AdminBillingError], int], ...] = (
    (AdminNotFoundError, 404),
    (AdminConflictError, 409),
    (AdminInvalidError, 422),
    (PaymobCallError, 502),
)


def admin_id(auth: AuthContext) -> uuid.UUID:
    return uuid.UUID(auth.user_id)


@contextmanager
def mapped_errors() -> Iterator[None]:
    """Turn service errors into ``HTTPException`` with ``{"code", "message"}``."""
    try:
        yield
    except AdminBillingError as exc:
        status = next((code for kind, code in _STATUS if isinstance(exc, kind)), 500)
        raise HTTPException(
            status_code=status, detail={"code": exc.code, "message": exc.message}
        ) from exc


# -- DTO mapping ------------------------------------------------------------------


def plan_tier_dto(t: PlanTier) -> PlanTierDTO:
    return PlanTierDTO(
        id=str(t.id),
        code=t.code,
        name=t.name,
        audience=t.audience.value,
        interval=t.interval.value if t.interval else None,
        priceMinor=t.price_minor,
        currency=t.currency,
        allowanceUnits=t.allowance_units,
        includedSeats=t.included_seats or 0,
        seatAllowanceUnits=t.seat_allowance_units or 0,
        extraSeatPriceMinor=t.extra_seat_price_minor or 0,
        features=dict(t.features or {}),
        isActive=t.is_active,
        paymobPlanId=t.paymob_plan_id,
        paymobDrift=paymob_drift(t),  # type: ignore[arg-type]
    )


def credit_pack_dto(p: CreditPack) -> CreditPackDTO:
    return CreditPackDTO(
        id=str(p.id), code=p.code, name=p.name, units=p.units, priceMinor=p.price_minor,
        currency=p.currency, isActive=p.is_active,
    )


def free_allowance_dto(f: FreeAllowanceView) -> FreeAllowanceDTO:
    return FreeAllowanceDTO(
        audience=f.audience,  # type: ignore[arg-type]
        creditPackId=str(f.pack.id),
        units=f.pack.units,
        validDays=f.valid_days,
    )


def usage_rate_dto(r: UsageRate) -> UsageRateDTO:
    return UsageRateDTO(
        id=str(r.id), version=r.version, action=r.action, unitsPerUsd=r.units_per_usd,
        effectiveFrom=r.effective_from,
    )


def usage_estimator_dto(e: UsageEstimator) -> UsageEstimatorDTO:
    return UsageEstimatorDTO(
        id=str(e.id), version=e.version, action=e.action, inputKind=e.input_kind.value,
        baseLow=e.base_low, baseHigh=e.base_high, perInputLow=e.per_input_low,
        perInputHigh=e.per_input_high, effectiveFrom=e.effective_from,
    )


# -- area 1: catalogue ----------------------------------------------------------


@router.get("/catalogue", response_model=AdminCatalogueDTO)
def get_catalogue(service: CatalogueService) -> AdminCatalogueDTO:
    snap = service.catalogue()
    return AdminCatalogueDTO(
        planTiers=[plan_tier_dto(t) for t in snap.plan_tiers],
        creditPacks=[credit_pack_dto(p) for p in snap.credit_packs],
        freeAllowances=[free_allowance_dto(f) for f in snap.free_allowances],
        usageRates=[usage_rate_dto(r) for r in snap.usage_rates],
        usageEstimators=[usage_estimator_dto(e) for e in snap.usage_estimators],
    )


@router.post("/tiers", response_model=PlanTierDTO)
def create_tier(body: PlanTierCreateDTO, service: CatalogueService, auth: AdminAuth) -> PlanTierDTO:
    fields = PlanTierFields(
        code=body.code,
        name=body.name,
        audience=PlanAudience(body.audience),
        interval=PlanInterval(body.interval),
        price_minor=body.priceMinor,
        currency=body.currency,
        allowance_units=body.allowanceUnits,
        included_seats=body.includedSeats,
        seat_allowance_units=body.seatAllowanceUnits,
        extra_seat_price_minor=body.extraSeatPriceMinor,
        features=body.features,
        is_active=body.isActive,
    )
    with mapped_errors():
        tier = service.create_plan_tier(fields, admin_user_id=admin_id(auth), reason=body.reason)
    return plan_tier_dto(tier)


@router.put("/tiers/{plan_tier_id}", response_model=PlanTierDTO)
def update_tier(
    plan_tier_id: uuid.UUID, body: PlanTierUpdateDTO, service: CatalogueService, auth: AdminAuth
) -> PlanTierDTO:
    changes = {
        "name": body.name,
        "price_minor": body.priceMinor,
        "allowance_units": body.allowanceUnits,
        "included_seats": body.includedSeats,
        "seat_allowance_units": body.seatAllowanceUnits,
        "extra_seat_price_minor": body.extraSeatPriceMinor,
        "features": body.features,
        "is_active": body.isActive,
    }
    with mapped_errors():
        tier = service.update_plan_tier(
            plan_tier_id, changes, admin_user_id=admin_id(auth), reason=body.reason
        )
    return plan_tier_dto(tier)


@router.post("/tiers/{plan_tier_id}/sync", response_model=PlanTierDTO)
def sync_tier(
    plan_tier_id: uuid.UUID, body: ReasonDTO, service: CatalogueService, auth: AdminAuth
) -> PlanTierDTO:
    with mapped_errors():
        tier = service.sync_paymob_plan(plan_tier_id, admin_user_id=admin_id(auth), reason=body.reason)
    return plan_tier_dto(tier)


@router.post("/packs", response_model=CreditPackDTO)
def create_pack(body: CreditPackCreateDTO, service: CatalogueService, auth: AdminAuth) -> CreditPackDTO:
    fields = CreditPackFields(
        code=body.code, name=body.name, units=body.units, price_minor=body.priceMinor,
        currency=body.currency, is_active=body.isActive,
    )
    with mapped_errors():
        pack = service.create_credit_pack(fields, admin_user_id=admin_id(auth), reason=body.reason)
    return credit_pack_dto(pack)


@router.put("/packs/{credit_pack_id}", response_model=CreditPackDTO)
def update_pack(
    credit_pack_id: uuid.UUID, body: CreditPackUpdateDTO, service: CatalogueService, auth: AdminAuth
) -> CreditPackDTO:
    changes = {
        "name": body.name, "units": body.units, "price_minor": body.priceMinor,
        "is_active": body.isActive,
    }
    with mapped_errors():
        pack = service.update_credit_pack(
            credit_pack_id, changes, admin_user_id=admin_id(auth), reason=body.reason
        )
    return credit_pack_dto(pack)


@router.put("/free-allowances", response_model=FreeAllowanceDTO)
def set_free_allowance(
    body: FreeAllowanceUpdateDTO, service: CatalogueService, auth: AdminAuth
) -> FreeAllowanceDTO:
    with mapped_errors():
        view = service.set_free_allowance(
            audience=body.audience, units=body.units, admin_user_id=admin_id(auth), reason=body.reason
        )
    return free_allowance_dto(view)


@router.post("/rates", response_model=UsageRateDTO)
def add_rate(body: UsageRateVersionDTO, service: CatalogueService, auth: AdminAuth) -> UsageRateDTO:
    with mapped_errors():
        row = service.add_usage_rate(
            action=body.action, units_per_usd=body.unitsPerUsd, effective_from=body.effectiveFrom,
            admin_user_id=admin_id(auth), reason=body.reason,
        )
    return usage_rate_dto(row)


@router.post("/estimators", response_model=UsageEstimatorDTO)
def add_estimator(
    body: UsageEstimatorVersionDTO, service: CatalogueService, auth: AdminAuth
) -> UsageEstimatorDTO:
    with mapped_errors():
        row = service.add_usage_estimator(
            action=body.action,
            input_kind=EstimatorInputKind(body.inputKind),
            base_low=body.baseLow,
            base_high=body.baseHigh,
            per_input_low=body.perInputLow,
            per_input_high=body.perInputHigh,
            effective_from=body.effectiveFrom,
            admin_user_id=admin_id(auth),
            reason=body.reason,
        )
    return usage_estimator_dto(row)
```

If `lemely/web/routers/admin.py`'s module docstring explains the `from __future__` per-file
ignore in `pyproject.toml`, the same ignore pattern (`lemely/web/routers/*.py`) already covers this
file; if pre-commit flags `TC00x` here, add the same `# noqa: TC00x - FastAPI resolves it at
runtime` comments `admin_tutors.py` uses.

- [ ] **Step 9: Mount the router and register its routes in the matrix**

In `lemely/web/app.py`, add `admin_billing` to the `from lemely.web.routers import (...)` list
and `app.include_router(admin_billing.router)` directly after `app.include_router(admin.router)`.

In `tests/test_authz_matrix_complete.py`, inside the `PLATFORM_ADMIN` section of `EXPECTED`,
after the last `/api/admin/tutoring/...` entry, add:

```python
    # Admin billing (Phase 07, spec §8): one router gated to platform_admin; every
    # write is audited in the same transaction (tests/test_admin_billing_*.py).
    ("GET", "/api/admin/billing/catalogue"): PLATFORM_ADMIN,
    ("POST", "/api/admin/billing/tiers"): PLATFORM_ADMIN,
    ("PUT", "/api/admin/billing/tiers/{plan_tier_id}"): PLATFORM_ADMIN,
    ("POST", "/api/admin/billing/tiers/{plan_tier_id}/sync"): PLATFORM_ADMIN,
    ("POST", "/api/admin/billing/packs"): PLATFORM_ADMIN,
    ("PUT", "/api/admin/billing/packs/{credit_pack_id}"): PLATFORM_ADMIN,
    ("POST", "/api/admin/billing/rates"): PLATFORM_ADMIN,
    ("POST", "/api/admin/billing/estimators"): PLATFORM_ADMIN,
    ("PUT", "/api/admin/billing/free-allowances"): PLATFORM_ADMIN,
```

and increase the number in the `# ── PLATFORM_ADMIN (N) ──` heading by 9.

- [ ] **Step 10: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest --no-cov tests/test_admin_billing_catalogue.py tests/test_admin_billing_authz.py tests/test_authz_matrix_complete.py tests/test_subscription_plan_sync.py tests/architecture -v`
Expected: all pass, no skips.

- [ ] **Step 11: Commit**

```bash
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files
P="lemely/db/admin_billing_repo.py lemely/db/subscription_repo.py tests/test_subscription_plan_sync.py lemely/web/schemas_admin_billing.py lemely/web/deps_admin_billing.py lemely/web/routers/admin_billing.py lemely/web/app.py tests/admin_billing_db.py tests/test_authz_matrix_complete.py tests/test_admin_billing_authz.py tests/test_admin_billing_catalogue.py"
git add $P
git commit -S -m "feat(admin): admin billing router and audited catalogue editing" -- $P
```

### Task 5: Customer search and the customer detail read

**Files:**
- Modify: `lemely/db/admin_billing_repo.py` (shared `PaymentView`)
- Create: `lemely/db/admin_customer_repo.py`
- Modify: `lemely/web/schemas_admin_billing.py`, `lemely/web/deps_admin_billing.py`, `lemely/web/routers/admin_billing.py`
- Modify: `tests/admin_billing_db.py` (seeds for users' money state; customer service override)
- Modify: `tests/test_authz_matrix_complete.py`, `tests/test_admin_billing_authz.py`
- Create: `tests/test_admin_billing_customers.py`

**Interfaces:**
- Consumes: Task 1–4 names; `User`, `ParentChildLink`; `Subscription`, `SubscriptionPeriod`, `PlanTier`, `Payment` (Phases 02/05); `UsageGrant`, `UsageGrantBalance`, `UsageDebt`, `UsageJob`, `UsageRate`, `UsageLedger` (Phase 01); `TeacherMember`, `TeacherMemberKind` (Phase 03).
- Produces:
  - In `admin_billing_repo`: `PaymentView(payment: Payment, refunds: list[PaymentRefund])` with property `refunded_minor: int`; `payment_views(session, payments) -> list[PaymentView]`.
  - In `admin_customer_repo`: `BalanceView`, `balance_for(session, user_id, *, now) -> BalanceView`, `CustomerHit`, `GrantView`, `JobView`, `SubscriptionView`, `MemberView`, `CustomerDetail`, `AdminCustomerService(sessionmaker, client, paymob_settings, *, now=...)` with `search(q, *, limit=20) -> list[CustomerHit]` and `detail(user_id) -> CustomerDetail`.
  - DTOs `CustomerSearchResultDTO`, `CustomerDetailDTO`, `AdminPaymentRowDTO`, `RefundDTO` and their parts; router functions `payment_row_dto(view)` and `customer_detail_dto(detail)`.
  - `get_admin_customer_service()`.
  - Test seeds: `add_rate`, `grant`, `metered_job`, `add_payment`, `add_subscription`.
  - Routes: `GET /customers`, `GET /customers/{user_id}`.

- [ ] **Step 1: Extend the test helpers**

Append to `tests/admin_billing_db.py` (merge imports):

```python
from datetime import timedelta
from decimal import Decimal

from lemely.core.usage_types import Payer
from lemely.db.admin_customer_repo import AdminCustomerService
from lemely.db.models.billing import Payment, PaymentPurpose, PaymentStatus, Subscription, SubscriptionPeriod
from lemely.db.models.enums import SubscriptionStatus
from lemely.db.models.usage import GrantKind, UsageJob, UsageRate
from lemely.db.usage_ledger_repo import UsageLedger
from lemely.web.deps_admin_billing import get_admin_customer_service


def add_rate(factory: sessionmaker[Session], action: str, units_per_usd: int = 1000, version: int = 1) -> None:
    with factory.begin() as session:
        session.add(
            UsageRate(
                version=version, action=action, units_per_usd=units_per_usd,
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
            owner_user_id=owner, kind=kind, units=units, idempotency_key=f"seed:{uuid.uuid4()}",
            expires_at=expires_at, visible=visible, effective_at=effective_at, payment_id=payment_id,
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
            job_id=job_id, actor_user_id=actor, action=action, payers=payers,
            estimate_low=low, estimate_high=high, estimator_version=estimator_version,
            rate_version=rate_version, teacher_member_id=None,
            expires_at=created_at + timedelta(minutes=10), now=created_at,
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
) -> uuid.UUID:
    pid = uuid.uuid4()
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
                id=sid, user_id=user, payer_user_id=user, plan_tier_id=tier, status=status,
                is_manually_activated=manual, current_period_start=start, current_period_end=end,
                paymob_subscription_id=paymob_subscription_id,
            )
        )
        session.flush()
        if end is not None:
            session.add(SubscriptionPeriod(subscription_id=sid, period_start=start, period_end=end))
    return sid
```

and add to the dict returned by `service_overrides`:

```python
        get_admin_customer_service: lambda: AdminCustomerService(
            factory, paymob, TEST_PAYMOB, now=clock  # type: ignore[arg-type]
        ),
```

- [ ] **Step 2: Write the failing customer tests**

Create `tests/test_admin_billing_customers.py`:

```python
"""Customer view reads (spec §8 area 2): search, and the whole money picture of one account."""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from lemely.core.usage_types import GrantScope, Payer
from lemely.db.admin_billing_repo import audited
from lemely.db.models.enums import Role
from lemely.db.models.team import AssistantRole, TeacherMember, TeacherMemberKind, TeacherMemberStatus
from lemely.db.models.usage import GrantKind
from lemely.db.models.users import ParentChildLink
from tests.admin_billing_db import (
    NOW,
    add_payment,
    add_plan_tier,
    add_rate,
    add_subscription,
    add_user,
    admin_client,
    billing_database,
    emptied_after,
    grant,
    metered_job,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture(scope="module")
def billing_db() -> Iterator[sessionmaker[Session]]:
    with billing_database() as factory:
        yield factory


@pytest.fixture
def sm(billing_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(billing_db)


@pytest.fixture
def world(sm: sessionmaker[Session]) -> dict[str, uuid.UUID]:
    admin = add_user(sm, Role.platform_admin)
    student = add_user(sm, Role.student, email="s1@example.com", display_name="Amira Hassan")
    parent = add_user(sm, Role.parent, email="p1@example.com", display_name="Parent One")
    teacher = add_user(sm, Role.teacher, email="t1@example.com", display_name="Teacher One")
    assistant = add_user(sm, Role.teacher, email="a1@example.com", display_name="Assistant One")
    with sm.begin() as session:
        session.add(ParentChildLink(parent_id=parent, child_id=student))
        session.add(
            TeacherMember(
                teacher_user_id=teacher, member_user_id=student,
                kind=TeacherMemberKind.student_seat, status=TeacherMemberStatus.active,
                scope_subjects=["0625"], scope_actions=["mark_paper"],
            )
        )
        session.add(
            TeacherMember(
                teacher_user_id=teacher, member_user_id=assistant,
                kind=TeacherMemberKind.assistant, status=TeacherMemberStatus.active,
                role_preset=AssistantRole.co_teacher, permissions={},
            )
        )
    tier = add_plan_tier(sm)
    sub = add_subscription(sm, student, tier)
    grant(sm, student, units=1000, kind=GrantKind.period_allowance, visible=False, expires_at=NOW + timedelta(days=20))
    grant(sm, student, units=300)
    grant(
        sm, student, units=50, effective_at=NOW - timedelta(days=400),
        expires_at=NOW - timedelta(days=200),
    )
    add_rate(sm, "mark_paper")
    metered_job(
        sm, student,
        [Payer(owner_user_id=student, scope=GrantScope.ALLOWANCE), Payer(owner_user_id=student, scope=GrantScope.CREDITS)],
        low=3, high=5, cost=Decimal("0.004"),
    )
    payment = add_payment(sm, payer=student, paymob_order_id=777001, paymob_txn_id=888001)
    with sm.begin() as session:
        audited(session, admin, "customer.grant", "user", student, "seeded", None, None)
    return {
        "admin": admin, "student": student, "parent": parent, "teacher": teacher,
        "assistant": assistant, "tier": tier, "sub": sub, "payment": payment,
    }


@pytest.mark.parametrize(
    ("q", "matched_on"),
    [("s1@exa", "email"), ("Hassan", "name"), ("777001", "paymob_order")],
)
def test_search_finds_the_student(
    sm: sessionmaker[Session], world: dict[str, uuid.UUID], q: str, matched_on: str
) -> None:
    resp = admin_client(sm, world["admin"]).get("/api/admin/billing/customers", params={"q": q})
    assert resp.status_code == 200, resp.text
    hits = resp.json()["hits"]
    assert [(h["userId"], h["matchedOn"]) for h in hits] == [(str(world["student"]), matched_on)]


def test_search_by_user_id_and_like_wildcards_are_literal(
    sm: sessionmaker[Session], world: dict[str, uuid.UUID]
) -> None:
    client = admin_client(sm, world["admin"])
    by_id = client.get("/api/admin/billing/customers", params={"q": str(world["parent"])}).json()
    assert [h["matchedOn"] for h in by_id["hits"]] == ["user_id"]
    assert client.get("/api/admin/billing/customers", params={"q": "%%"}).json()["hits"] == []
    assert client.get("/api/admin/billing/customers", params={"q": "a"}).status_code == 422


def test_student_detail_shows_the_whole_money_picture(
    sm: sessionmaker[Session], world: dict[str, uuid.UUID]
) -> None:
    resp = admin_client(sm, world["admin"]).get(f"/api/admin/billing/customers/{world['student']}")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["user"]["email"] == "s1@example.com"
    assert body["balance"] == {
        "allowanceAvailable": 996, "creditsAvailable": 300, "seatAvailable": 0, "outstandingDebt": 0,
    }
    [sub] = body["subscriptions"]
    assert (sub["planCode"], sub["status"], len(sub["periods"])) == ("student_monthly", "active", 1)
    # The grant that expired 200 days ago is outside the 90-day window.
    assert sorted((g["kind"], g["units"], g["remaining"]) for g in body["grants"]) == [
        ("adjustment", 300, 300),
        ("period_allowance", 1000, 996),
    ]
    [job] = body["usageJobs"]
    assert (job["estimateLow"], job["estimateHigh"], job["actualUnits"], job["outsideRange"]) == (3, 5, 4, False)
    assert job["actualCostUsd"] == "0.004000"
    [payment] = body["payments"]
    assert (payment["paymobOrderId"], payment["status"], payment["refundedMinor"]) == ("777001", "paid", 0)
    assert [m["email"] for m in body["seatedWith"]] == ["t1@example.com"]
    assert [p["email"] for p in body["parents"]] == ["p1@example.com"]
    assert body["seats"] == [] and body["assistants"] == [] and body["children"] == []
    assert [a["action"] for a in body["audit"]] == ["customer.grant"]


def test_teacher_detail_lists_seats_and_assistants(
    sm: sessionmaker[Session], world: dict[str, uuid.UUID]
) -> None:
    body = admin_client(sm, world["admin"]).get(f"/api/admin/billing/customers/{world['teacher']}").json()
    assert [m["email"] for m in body["seats"]] == ["s1@example.com"]
    assert [(m["email"], m["rolePreset"]) for m in body["assistants"]] == [("a1@example.com", "co_teacher")]


def test_parent_detail_lists_children(sm: sessionmaker[Session], world: dict[str, uuid.UUID]) -> None:
    body = admin_client(sm, world["admin"]).get(f"/api/admin/billing/customers/{world['parent']}").json()
    assert [c["email"] for c in body["children"]] == ["s1@example.com"]


def test_an_unknown_customer_is_404(sm: sessionmaker[Session], world: dict[str, uuid.UUID]) -> None:
    resp = admin_client(sm, world["admin"]).get(f"/api/admin/billing/customers/{uuid.uuid4()}")
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "customer_not_found"
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest --no-cov tests/test_admin_billing_customers.py -v`
Expected: collection error, `No module named 'lemely.db.admin_customer_repo'`.

- [ ] **Step 4: Add the shared payment view**

Append to `lemely/db/admin_billing_repo.py` (merge imports; add names to `__all__`):

```python
from dataclasses import field

from lemely.db.models.billing import Payment
from lemely.db.models.billing_ops import PaymentRefund, RefundKind, RefundStatus


@dataclass(frozen=True, slots=True)
class PaymentView:
    """A payment with its refund attempts, oldest first."""

    payment: Payment
    refunds: list[PaymentRefund] = field(default_factory=list)

    @property
    def refunded_minor(self) -> int:
        return sum(
            r.amount_minor
            for r in self.refunds
            if r.status is RefundStatus.succeeded and r.kind is RefundKind.refund
        )


def payment_views(session: Session, payments: Sequence[Payment]) -> list[PaymentView]:
    """Attach refunds to ``payments`` in one query, keeping the input order."""
    ids = [p.id for p in payments]
    by_payment: dict[uuid.UUID, list[PaymentRefund]] = {pid: [] for pid in ids}
    if ids:
        for refund in session.scalars(
            select(PaymentRefund)
            .where(PaymentRefund.payment_id.in_(ids))
            .order_by(PaymentRefund.created_at, PaymentRefund.id)
        ):
            by_payment[refund.payment_id].append(refund)
    return [PaymentView(payment=p, refunds=by_payment[p.id]) for p in payments]
```

- [ ] **Step 5: Write the customer service (reads)**

Create `lemely/db/admin_customer_repo.py`:

```python
"""Admin customer view (spec §8 area 2): search, detail, and (Tasks 6–7) money actions.

The detail is the whole money picture of one account, read in one session so the
numbers agree with each other: subscriptions and periods, grants with balances,
debt, recent usage jobs (estimate against actual), payments with refunds, team
relationships, linked parents or children, and the admin actions taken on them.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_CEILING, Decimal
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy import and_, or_, select

from lemely.db.admin_billing_repo import (
    AdminInvalidError,
    AdminNotFoundError,
    PaymentView,
    payment_views,
)
from lemely.db.models.admin_audit import AdminAuditLog
from lemely.db.models.billing import Payment, PlanTier, Subscription, SubscriptionPeriod
from lemely.db.models.team import TeacherMember, TeacherMemberKind
from lemely.db.models.usage import UsageDebt, UsageGrant, UsageGrantBalance, UsageJob, UsageRate
from lemely.db.models.users import ParentChildLink, User

if TYPE_CHECKING:
    from sqlalchemy.orm import InstrumentedAttribute, Session, sessionmaker

    from lemely.io.paymob.client import PaymobClient
    from lemely.runtime.config import PaymobSettings

_GRANT_HISTORY = timedelta(days=90)
_RECENT_ROWS = 50
_PERIODS_PER_SUBSCRIPTION = 6


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class BalanceView:
    allowance_available: int
    credits_available: int
    seat_available: int
    outstanding_debt: int


def balance_for(session: Session, user_id: uuid.UUID, *, now: datetime) -> BalanceView:
    """``remaining - held`` over the owner's usable grants, split by kind, plus open debt."""
    rows = session.execute(
        select(
            UsageGrant.visible,
            UsageGrant.teacher_member_id,
            UsageGrantBalance.remaining - UsageGrantBalance.held,
        )
        .join(UsageGrantBalance, UsageGrantBalance.grant_id == UsageGrant.id)
        .where(
            UsageGrant.owner_user_id == user_id,
            UsageGrant.effective_at <= now,
            or_(UsageGrant.expires_at.is_(None), UsageGrant.expires_at > now),
        )
    ).all()
    allowance = credits = seat = 0
    for visible, member_id, available in rows:
        if member_id is not None:
            seat += int(available)
        elif visible:
            credits += int(available)
        else:
            allowance += int(available)
    debt = session.scalar(
        select(sa.func.coalesce(sa.func.sum(UsageDebt.outstanding), 0)).where(
            UsageDebt.owner_user_id == user_id
        )
    )
    return BalanceView(allowance, credits, seat, int(debt or 0))


@dataclass(frozen=True, slots=True)
class CustomerHit:
    user_id: uuid.UUID
    email: str
    display_name: str | None
    role: str
    matched_on: str


@dataclass(frozen=True, slots=True)
class GrantView:
    grant: UsageGrant
    remaining: int
    held: int


@dataclass(frozen=True, slots=True)
class JobView:
    job: UsageJob
    actual_units: int | None

    @property
    def outside_range(self) -> bool:
        return self.actual_units is not None and not (
            self.job.estimate_low <= self.actual_units <= self.job.estimate_high
        )


@dataclass(frozen=True, slots=True)
class SubscriptionView:
    subscription: Subscription
    plan_code: str
    plan_name: str
    periods: list[SubscriptionPeriod]


@dataclass(frozen=True, slots=True)
class MemberView:
    """A ``teacher_members`` row and the person on the other side of it."""

    member: TeacherMember
    other_user_id: uuid.UUID
    other_email: str


@dataclass(frozen=True, slots=True)
class CustomerDetail:
    user: User
    balance: BalanceView
    subscriptions: list[SubscriptionView]
    grants: list[GrantView]
    debts: list[UsageDebt]
    jobs: list[JobView]
    payments: list[PaymentView]
    seats: list[MemberView]
    assistants: list[MemberView]
    seated_with: list[MemberView]
    parents: list[User]
    children: list[User]
    audit: list[AdminAuditLog]


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def actual_units(cost_usd: Decimal | None, units_per_usd: int | None) -> int | None:
    """The units a job's actual cost converts to (ceil, as ``usd_to_units``)."""
    if cost_usd is None or units_per_usd is None:
        return None
    return int((cost_usd * units_per_usd).to_integral_value(rounding=ROUND_CEILING))


class AdminCustomerService:
    """Search and read one customer; Tasks 6–7 add the audited money actions."""

    def __init__(
        self,
        sessionmaker: sessionmaker[Session],
        client: PaymobClient,
        paymob_settings: PaymobSettings,
        *,
        now: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._sm = sessionmaker
        self._client = client
        self._settings = paymob_settings
        self._now = now

    # -- search ----------------------------------------------------------------

    def search(self, q: str, *, limit: int = 20) -> list[CustomerHit]:
        """Match a user id, a payment id, a Paymob order id, an email or a display name.

        Exact identifiers first, then email, then name; each user appears once,
        tagged with the first thing that matched.
        """
        term = q.strip()
        if len(term) < 2:
            raise AdminInvalidError("query_too_short", "Type at least two characters.")
        hits: dict[uuid.UUID, CustomerHit] = {}

        def add(users: list[User], matched_on: str) -> None:
            for u in users:
                hits.setdefault(
                    u.id, CustomerHit(u.id, u.email, u.display_name, u.role.value, matched_on)
                )

        def payment_parties(condition: sa.ColumnElement[bool]) -> list[User]:
            parties = select(Payment.payer_user_id).where(condition).union(
                select(Payment.beneficiary_user_id).where(condition)
            )
            return list(s.scalars(select(User).where(User.id.in_(parties)).order_by(User.email)))

        with self._sm() as s:
            try:
                as_uuid = uuid.UUID(term)
            except ValueError:
                as_uuid = None
            if as_uuid is not None:
                add(list(s.scalars(select(User).where(User.id == as_uuid))), "user_id")
                add(
                    payment_parties(
                        or_(Payment.id == as_uuid, Payment.special_reference == str(as_uuid))
                    ),
                    "payment_id",
                )
            if term.isdigit():
                add(
                    payment_parties(sa.cast(Payment.paymob_order_id, sa.String) == term),
                    "paymob_order",
                )
            pattern = f"%{_escape_like(term)}%"
            add(
                list(
                    s.scalars(
                        select(User)
                        .where(User.email.ilike(pattern, escape="\\"))
                        .order_by(User.email)
                        .limit(limit)
                    )
                ),
                "email",
            )
            add(
                list(
                    s.scalars(
                        select(User)
                        .where(User.display_name.ilike(pattern, escape="\\"))
                        .order_by(User.display_name)
                        .limit(limit)
                    )
                ),
                "name",
            )
        return list(hits.values())[:limit]

    # -- detail ----------------------------------------------------------------

    def detail(self, user_id: uuid.UUID) -> CustomerDetail:
        now = self._now()
        with self._sm() as s:
            user = s.get(User, user_id)
            if user is None:
                raise AdminNotFoundError("customer_not_found")

            subs = list(
                s.scalars(
                    select(Subscription)
                    .where(Subscription.user_id == user_id)
                    .order_by(Subscription.created_at.desc())
                )
            )
            tiers = {
                t.id: t
                for t in s.scalars(
                    select(PlanTier).where(PlanTier.id.in_({x.plan_tier_id for x in subs}))
                )
            }
            periods: dict[uuid.UUID, list[SubscriptionPeriod]] = {x.id: [] for x in subs}
            for period in s.scalars(
                select(SubscriptionPeriod)
                .where(SubscriptionPeriod.subscription_id.in_(list(periods)))
                .order_by(SubscriptionPeriod.period_start.desc())
            ):
                bucket = periods[period.subscription_id]
                if len(bucket) < _PERIODS_PER_SUBSCRIPTION:
                    bucket.append(period)

            grants = [
                GrantView(g, int(remaining), int(held))
                for g, remaining, held in s.execute(
                    select(UsageGrant, UsageGrantBalance.remaining, UsageGrantBalance.held)
                    .join(UsageGrantBalance, UsageGrantBalance.grant_id == UsageGrant.id)
                    .where(
                        UsageGrant.owner_user_id == user_id,
                        or_(
                            UsageGrant.expires_at.is_(None),
                            UsageGrant.expires_at > now - _GRANT_HISTORY,
                        ),
                    )
                    .order_by(UsageGrant.expires_at.asc().nulls_last(), UsageGrant.created_at)
                )
            ]
            debts = list(
                s.scalars(
                    select(UsageDebt)
                    .where(UsageDebt.owner_user_id == user_id, UsageDebt.outstanding > 0)
                    .order_by(UsageDebt.created_at)
                )
            )
            jobs = [
                JobView(job, actual_units(job.actual_cost_usd, rate))
                for job, rate in s.execute(
                    select(UsageJob, UsageRate.units_per_usd)
                    .outerjoin(
                        UsageRate,
                        and_(
                            UsageRate.version == UsageJob.rate_version,
                            UsageRate.action == UsageJob.action,
                        ),
                    )
                    .where(UsageJob.actor_user_id == user_id)
                    .order_by(UsageJob.created_at.desc())
                    .limit(_RECENT_ROWS)
                )
            ]
            payments = payment_views(
                s,
                list(
                    s.scalars(
                        select(Payment)
                        .where(
                            or_(Payment.payer_user_id == user_id, Payment.beneficiary_user_id == user_id)
                        )
                        .order_by(Payment.created_at.desc())
                        .limit(_RECENT_ROWS)
                    )
                ),
            )

            def members(
                mine: sa.ColumnElement[bool], other: InstrumentedAttribute[uuid.UUID]
            ) -> list[MemberView]:
                return [
                    MemberView(m, uid, email)
                    for m, uid, email in s.execute(
                        select(TeacherMember, User.id, User.email)
                        .join(User, User.id == other)
                        .where(mine)
                        .order_by(TeacherMember.created_at)
                    )
                ]

            seats = members(
                and_(
                    TeacherMember.teacher_user_id == user_id,
                    TeacherMember.kind == TeacherMemberKind.student_seat,
                ),
                TeacherMember.member_user_id,
            )
            assistants = members(
                and_(
                    TeacherMember.teacher_user_id == user_id,
                    TeacherMember.kind == TeacherMemberKind.assistant,
                ),
                TeacherMember.member_user_id,
            )
            seated_with = members(
                and_(
                    TeacherMember.member_user_id == user_id,
                    TeacherMember.kind == TeacherMemberKind.student_seat,
                ),
                TeacherMember.teacher_user_id,
            )
            parents = list(
                s.scalars(
                    select(User)
                    .join(ParentChildLink, ParentChildLink.parent_id == User.id)
                    .where(ParentChildLink.child_id == user_id)
                    .order_by(User.email)
                )
            )
            children = list(
                s.scalars(
                    select(User)
                    .join(ParentChildLink, ParentChildLink.child_id == User.id)
                    .where(ParentChildLink.parent_id == user_id)
                    .order_by(User.email)
                )
            )
            targets = {user_id, *(x.id for x in subs), *(v.payment.id for v in payments)}
            audit = list(
                s.scalars(
                    select(AdminAuditLog)
                    .where(AdminAuditLog.target_id.in_(targets))
                    .order_by(AdminAuditLog.created_at.desc(), AdminAuditLog.id)
                    .limit(_RECENT_ROWS)
                )
            )
            return CustomerDetail(
                user=user,
                balance=balance_for(s, user_id, now=now),
                subscriptions=[
                    SubscriptionView(
                        x, tiers[x.plan_tier_id].code, tiers[x.plan_tier_id].name, periods[x.id]
                    )
                    for x in subs
                ],
                grants=grants,
                debts=debts,
                jobs=jobs,
                payments=payments,
                seats=seats,
                assistants=assistants,
                seated_with=seated_with,
                parents=parents,
                children=children,
                audit=audit,
            )


__all__ = [
    "AdminCustomerService",
    "BalanceView",
    "CustomerDetail",
    "CustomerHit",
    "GrantView",
    "JobView",
    "MemberView",
    "SubscriptionView",
    "actual_units",
    "balance_for",
]
```

- [ ] **Step 6: Add the DTOs**

Append to `lemely/web/schemas_admin_billing.py`:

```python
# -- customers ------------------------------------------------------------------


class CustomerHitDTO(ApiModel):
    userId: str
    email: str
    displayName: str | None
    role: str
    matchedOn: Literal["user_id", "payment_id", "paymob_order", "email", "name"]


class CustomerSearchResultDTO(ApiModel):
    hits: list[CustomerHitDTO]


class CustomerUserDTO(ApiModel):
    id: str
    email: str
    displayName: str | None
    role: str
    createdAt: datetime


class BalanceDTO(ApiModel):
    allowanceAvailable: int
    creditsAvailable: int
    seatAvailable: int
    outstandingDebt: int


class PeriodDTO(ApiModel):
    periodStart: datetime
    periodEnd: datetime
    paymentId: str | None


class SubscriptionDTO(ApiModel):
    id: str
    planTierId: str
    planCode: str
    planName: str
    status: str
    payerUserId: str | None
    currentPeriodStart: datetime | None
    currentPeriodEnd: datetime | None
    cancelAtPeriodEnd: bool
    pendingPlanTierId: str | None
    graceUntil: datetime | None
    extraSeats: int
    pendingExtraSeats: int | None
    paymobSubscriptionId: str | None
    isManuallyActivated: bool
    periods: list[PeriodDTO]


class GrantDTO(ApiModel):
    id: str
    kind: str
    visible: bool
    units: int
    remaining: int
    held: int
    effectiveAt: datetime
    expiresAt: datetime | None
    teacherMemberId: str | None
    paymentId: str | None


class DebtDTO(ApiModel):
    id: str
    jobId: str | None
    units: int
    outstanding: int
    createdAt: datetime


class UsageJobDTO(ApiModel):
    jobId: str
    action: str
    status: str
    estimateLow: int
    estimateHigh: int
    estimatorVersion: int
    rateVersion: int
    reserved: int
    charged: int | None
    debtCreated: int | None
    actualCostUsd: str | None
    actualUnits: int | None
    outsideRange: bool
    createdAt: datetime
    settledAt: datetime | None


class RefundDTO(ApiModel):
    id: str
    kind: Literal["refund", "void"]
    status: Literal["requested", "succeeded", "failed", "unknown"]
    amountMinor: int
    reason: str
    adminUserId: str
    clawedBackUnits: int
    createdAt: datetime
    updatedAt: datetime


class AdminPaymentRowDTO(ApiModel):
    id: str
    payerUserId: str
    beneficiaryUserId: str
    purpose: str
    status: str
    amountMinor: int
    currency: str
    refundedMinor: int
    paymobOrderId: str | None
    paymobTxnId: str | None
    planTierId: str | None
    creditPackId: str | None
    subscriptionId: str | None
    seatQuantity: int | None
    createdAt: datetime
    paidAt: datetime | None
    refunds: list[RefundDTO]


class MemberDTO(ApiModel):
    memberId: str
    userId: str
    email: str
    kind: str
    status: str
    scopeSubjects: list[str] | None
    scopeActions: list[str] | None
    rolePreset: str | None
    capUnits: int | None
    capPeriod: str | None
    leavesAt: datetime | None


class LinkedUserDTO(ApiModel):
    userId: str
    email: str
    displayName: str | None


class AuditEntryDTO(ApiModel):
    id: str
    adminUserId: str
    action: str
    targetKind: str
    targetId: str
    reason: str
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    createdAt: datetime


class CustomerDetailDTO(ApiModel):
    user: CustomerUserDTO
    balance: BalanceDTO
    subscriptions: list[SubscriptionDTO]
    grants: list[GrantDTO]
    debts: list[DebtDTO]
    usageJobs: list[UsageJobDTO]
    payments: list[AdminPaymentRowDTO]
    seats: list[MemberDTO]
    assistants: list[MemberDTO]
    seatedWith: list[MemberDTO]
    parents: list[LinkedUserDTO]
    children: list[LinkedUserDTO]
    audit: list[AuditEntryDTO]
```

- [ ] **Step 7: Add the dependency and routes**

In `lemely/web/deps_admin_billing.py` add (and export):

```python
from lemely.db.admin_customer_repo import AdminCustomerService


def get_admin_customer_service() -> AdminCustomerService:
    settings = get_settings()  # one Settings read: sessionmaker and Paymob settings agree
    return AdminCustomerService(get_sessionmaker(settings), get_paymob_client(), settings.paymob)
```

In `lemely/web/routers/admin_billing.py` add the imports
(`AdminCustomerService`, `CustomerDetail`, `JobView`, `MemberView` from
`lemely.db.admin_customer_repo`; `PaymentView` from `lemely.db.admin_billing_repo`;
`AdminAuditLog`; `PaymentRefund`; `User`; `get_admin_customer_service`; `Query` from fastapi; the
new DTOs) and:

```python
CustomerService = Annotated[AdminCustomerService, Depends(get_admin_customer_service)]


def _id(value: object | None) -> str | None:
    return None if value is None else str(value)


def refund_dto(r: PaymentRefund) -> RefundDTO:
    return RefundDTO(
        id=str(r.id), kind=r.kind.value, status=r.status.value, amountMinor=r.amount_minor,  # type: ignore[arg-type]
        reason=r.reason, adminUserId=str(r.admin_user_id), clawedBackUnits=r.clawed_back_units,
        createdAt=r.created_at, updatedAt=r.updated_at,
    )


def payment_row_dto(view: PaymentView) -> AdminPaymentRowDTO:
    p = view.payment
    return AdminPaymentRowDTO(
        id=str(p.id),
        payerUserId=str(p.payer_user_id),
        beneficiaryUserId=str(p.beneficiary_user_id),
        purpose=p.purpose.value,
        status=p.status.value,
        amountMinor=p.amount_minor,
        currency=p.currency,
        refundedMinor=view.refunded_minor,
        paymobOrderId=_id(p.paymob_order_id),
        paymobTxnId=_id(p.paymob_txn_id),
        planTierId=_id(p.plan_tier_id),
        creditPackId=_id(p.credit_pack_id),
        subscriptionId=_id(p.subscription_id),
        seatQuantity=p.seat_quantity,
        createdAt=p.created_at,
        paidAt=p.paid_at,
        refunds=[refund_dto(r) for r in view.refunds],
    )


def _member_dto(view: MemberView) -> MemberDTO:
    m = view.member
    return MemberDTO(
        memberId=str(m.id),
        userId=str(view.other_user_id),
        email=view.other_email,
        kind=m.kind.value,
        status=m.status.value,
        scopeSubjects=list(m.scope_subjects) if m.scope_subjects is not None else None,
        scopeActions=list(m.scope_actions) if m.scope_actions is not None else None,
        rolePreset=m.role_preset.value if m.role_preset is not None else None,
        capUnits=m.cap_units,
        capPeriod=m.cap_period.value if m.cap_period is not None else None,
        leavesAt=m.leaves_at,
    )


def _linked(u: User) -> LinkedUserDTO:
    return LinkedUserDTO(userId=str(u.id), email=u.email, displayName=u.display_name)


def _job_dto(view: JobView) -> UsageJobDTO:
    j = view.job
    return UsageJobDTO(
        jobId=str(j.job_id),
        action=j.action,
        status=j.status.value,
        estimateLow=j.estimate_low,
        estimateHigh=j.estimate_high,
        estimatorVersion=j.estimator_version,
        rateVersion=j.rate_version,
        reserved=j.reserved,
        charged=j.charged,
        debtCreated=j.debt_created,
        actualCostUsd=None if j.actual_cost_usd is None else f"{j.actual_cost_usd:.6f}",
        actualUnits=view.actual_units,
        outsideRange=view.outside_range,
        createdAt=j.created_at,
        settledAt=j.settled_at,
    )


def _audit_dto(a: AdminAuditLog) -> AuditEntryDTO:
    return AuditEntryDTO(
        id=str(a.id), adminUserId=str(a.admin_user_id), action=a.action, targetKind=a.target_kind,
        targetId=str(a.target_id), reason=a.reason, before=a.before, after=a.after,
        createdAt=a.created_at,
    )


def customer_detail_dto(d: CustomerDetail) -> CustomerDetailDTO:
    return CustomerDetailDTO(
        user=CustomerUserDTO(
            id=str(d.user.id), email=d.user.email, displayName=d.user.display_name,
            role=d.user.role.value, createdAt=d.user.created_at,
        ),
        balance=BalanceDTO(
            allowanceAvailable=d.balance.allowance_available,
            creditsAvailable=d.balance.credits_available,
            seatAvailable=d.balance.seat_available,
            outstandingDebt=d.balance.outstanding_debt,
        ),
        subscriptions=[
            SubscriptionDTO(
                id=str(v.subscription.id),
                planTierId=str(v.subscription.plan_tier_id),
                planCode=v.plan_code,
                planName=v.plan_name,
                status=v.subscription.status.value,
                payerUserId=_id(v.subscription.payer_user_id),
                currentPeriodStart=v.subscription.current_period_start,
                currentPeriodEnd=v.subscription.current_period_end,
                cancelAtPeriodEnd=bool(v.subscription.cancel_at_period_end),
                pendingPlanTierId=_id(v.subscription.pending_plan_tier_id),
                graceUntil=v.subscription.grace_until,
                extraSeats=v.subscription.extra_seats or 0,
                pendingExtraSeats=v.subscription.pending_extra_seats,
                paymobSubscriptionId=_id(v.subscription.paymob_subscription_id),
                isManuallyActivated=v.subscription.is_manually_activated,
                periods=[
                    PeriodDTO(
                        periodStart=p.period_start, periodEnd=p.period_end, paymentId=_id(p.payment_id)
                    )
                    for p in v.periods
                ],
            )
            for v in d.subscriptions
        ],
        grants=[
            GrantDTO(
                id=str(g.grant.id), kind=g.grant.kind.value, visible=g.grant.visible,
                units=g.grant.units, remaining=g.remaining, held=g.held,
                effectiveAt=g.grant.effective_at, expiresAt=g.grant.expires_at,
                teacherMemberId=_id(g.grant.teacher_member_id), paymentId=_id(g.grant.payment_id),
            )
            for g in d.grants
        ],
        debts=[
            DebtDTO(
                id=str(x.id), jobId=_id(x.job_id), units=x.units, outstanding=x.outstanding,
                createdAt=x.created_at,
            )
            for x in d.debts
        ],
        usageJobs=[_job_dto(j) for j in d.jobs],
        payments=[payment_row_dto(p) for p in d.payments],
        seats=[_member_dto(m) for m in d.seats],
        assistants=[_member_dto(m) for m in d.assistants],
        seatedWith=[_member_dto(m) for m in d.seated_with],
        parents=[_linked(u) for u in d.parents],
        children=[_linked(u) for u in d.children],
        audit=[_audit_dto(a) for a in d.audit],
    )


# -- area 2: customers ----------------------------------------------------------


@router.get("/customers", response_model=CustomerSearchResultDTO)
def search_customers(
    service: CustomerService,
    q: Annotated[str, Query(min_length=1, max_length=200)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> CustomerSearchResultDTO:
    with mapped_errors():
        hits = service.search(q, limit=limit)
    return CustomerSearchResultDTO(
        hits=[
            CustomerHitDTO(
                userId=str(h.user_id), email=h.email, displayName=h.display_name, role=h.role,
                matchedOn=h.matched_on,  # type: ignore[arg-type]
            )
            for h in hits
        ]
    )


@router.get("/customers/{user_id}", response_model=CustomerDetailDTO)
def get_customer(user_id: uuid.UUID, service: CustomerService) -> CustomerDetailDTO:
    with mapped_errors():
        return customer_detail_dto(service.detail(user_id))
```

- [ ] **Step 8: Register the routes**

In `tests/test_authz_matrix_complete.py`, after the Task 4 block, add:

```python
    ("GET", "/api/admin/billing/customers"): PLATFORM_ADMIN,
    ("GET", "/api/admin/billing/customers/{user_id}"): PLATFORM_ADMIN,
```

and increase the `PLATFORM_ADMIN (N)` heading by 2. In `tests/test_admin_billing_authz.py` add
`("GET", f"{P}/customers")` and `("GET", f"{P}/customers/{{user_id}}")` to `PLANNED`.

- [ ] **Step 9: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest --no-cov tests/test_admin_billing_customers.py tests/test_admin_billing_authz.py tests/test_authz_matrix_complete.py tests/test_admin_billing_catalogue.py tests/architecture -v`
Expected: all pass, no skips.

- [ ] **Step 10: Commit**

```bash
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files
P="lemely/db/admin_billing_repo.py lemely/db/admin_customer_repo.py lemely/web/schemas_admin_billing.py lemely/web/deps_admin_billing.py lemely/web/routers/admin_billing.py tests/admin_billing_db.py tests/test_authz_matrix_complete.py tests/test_admin_billing_authz.py tests/test_admin_billing_customers.py"
git add $P
git commit -S -m "feat(admin): customer search and money detail view" -- $P
```

### Task 6: Customer ledger actions — grant credits, adjust, forgive debt

**Files:**
- Modify: `lemely/db/admin_customer_repo.py`
- Modify: `lemely/web/schemas_admin_billing.py`, `lemely/web/routers/admin_billing.py`
- Modify: `tests/test_authz_matrix_complete.py`, `tests/test_admin_billing_authz.py`
- Create: `tests/test_admin_billing_ledger_actions.py`

**Interfaces:**
- Consumes: `audited`, `already_applied`, `lock_idempotency_key`, `require_reason`, `AuditAction.CUSTOMER_GRANT/CUSTOMER_ADJUST/CUSTOMER_FORGIVE_DEBT`, `AuditTarget.USER` (Task 1); `AdminCustomerService.detail`, `balance_for` (Task 5); `UsageLedger.issue_grant`, `.adjust` (negative shortfall becomes debt), `.forgive_debt`, `GrantKind.adjustment` (Phase 01).
- Produces:
  - `AdminCustomerService.grant_credits(user_id, *, units: int, valid_days: int | None, request_id: UUID, admin_user_id: UUID, reason: str) -> CustomerDetail`
  - `AdminCustomerService.adjust(user_id, *, units: int, request_id: UUID, admin_user_id: UUID, reason: str) -> CustomerDetail`
  - `AdminCustomerService.forgive_debt(user_id, *, units: int | None, admin_user_id: UUID, reason: str) -> CustomerDetail`
  - DTOs `AdminGrantRequestDTO`, `AdminAdjustRequestDTO`, `AdminForgiveRequestDTO`.
  - Routes: `POST /customers/{user_id}/grant`, `POST /customers/{user_id}/adjust`, `POST /customers/{user_id}/forgive-debt` (each answers `CustomerDetailDTO`).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_admin_billing_ledger_actions.py`:

```python
"""Customer money actions (spec §8 area 2, §5.8): each audited in the same transaction."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select

from lemely.core.usage_types import GrantScope, Payer
from lemely.db import admin_customer_repo
from lemely.db.admin_billing_repo import AuditAction
from lemely.db.admin_customer_repo import AdminCustomerService
from lemely.db.models.enums import Role
from lemely.db.models.usage import UsageGrant
from tests.admin_billing_db import (
    NOW,
    TEST_PAYMOB,
    FakePaymobClient,
    add_rate,
    add_user,
    admin_client,
    audit_rows,
    billing_database,
    emptied_after,
    grant,
    metered_job,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture(scope="module")
def billing_db() -> Iterator[sessionmaker[Session]]:
    with billing_database() as factory:
        yield factory


@pytest.fixture
def sm(billing_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(billing_db)


@pytest.fixture
def admin(sm: sessionmaker[Session]) -> uuid.UUID:
    return add_user(sm, Role.platform_admin)


def _with_debt(sm: sessionmaker[Session], units_of_debt: int) -> uuid.UUID:
    """A student whose 5 credits were overrun by a job costing 5 + ``units_of_debt`` units."""
    student = add_user(sm, Role.student)
    add_rate(sm, "mark_paper")
    grant(sm, student, units=5)
    metered_job(
        sm, student, [Payer(owner_user_id=student, scope=GrantScope.CREDITS)],
        low=1, high=5, cost=Decimal(5 + units_of_debt) / 1000,
    )
    return student


def _url(user: uuid.UUID, action: str) -> str:
    return f"/api/admin/billing/customers/{user}/{action}"


def test_grant_is_audited_and_a_replay_changes_nothing(sm: sessionmaker[Session], admin: uuid.UUID) -> None:
    student = add_user(sm, Role.student)
    client = admin_client(sm, admin)
    body = {"units": 100, "validDays": 30, "requestId": str(uuid.uuid4()), "reason": "outage goodwill"}

    first = client.post(_url(student, "grant"), json=body)
    replay = client.post(_url(student, "grant"), json=body)

    assert first.status_code == 200, first.text
    assert first.json()["balance"]["creditsAvailable"] == 100
    assert replay.json()["balance"]["creditsAvailable"] == 100
    [row] = audit_rows(sm, AuditAction.CUSTOMER_GRANT)
    assert row.target_id == student
    assert (row.before["credits_available"], row.after["credits_available"]) == (0, 100)
    assert row.after["idempotency_key"] == f"admin-grant:{body['requestId']}"


def test_a_grant_repays_debt_first(sm: sessionmaker[Session], admin: uuid.UUID) -> None:
    student = _with_debt(sm, 3)
    resp = admin_client(sm, admin).post(
        _url(student, "grant"),
        json={"units": 10, "validDays": 30, "requestId": str(uuid.uuid4()), "reason": "settle up"},
    )
    assert resp.json()["balance"]["outstandingDebt"] == 0
    assert resp.json()["balance"]["creditsAvailable"] == 7


def test_the_grant_and_its_audit_row_commit_together(
    sm: sessionmaker[Session], admin: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    student = add_user(sm, Role.student)
    request_id = uuid.uuid4()

    def broken_audit(*args: object, **kwargs: object) -> None:
        raise RuntimeError("audit write failed")

    monkeypatch.setattr(admin_customer_repo, "audited", broken_audit)
    service = AdminCustomerService(sm, FakePaymobClient(), TEST_PAYMOB, now=lambda: NOW)  # type: ignore[arg-type]
    with pytest.raises(RuntimeError):
        service.grant_credits(
            student, units=100, valid_days=30, request_id=request_id, admin_user_id=admin, reason="x y z"
        )
    with sm() as session:
        assert session.scalars(select(UsageGrant).where(UsageGrant.owner_user_id == student)).all() == []


def test_adjust_moves_credits_both_ways(sm: sessionmaker[Session], admin: uuid.UUID) -> None:
    student = add_user(sm, Role.student)
    client = admin_client(sm, admin)
    up = client.post(_url(student, "adjust"), json={"units": 50, "requestId": str(uuid.uuid4()), "reason": "fix"})
    down = client.post(_url(student, "adjust"), json={"units": -20, "requestId": str(uuid.uuid4()), "reason": "fix"})
    assert up.status_code == 200, up.text
    assert down.json()["balance"]["creditsAvailable"] == 30
    assert [r.after["units"] for r in audit_rows(sm, AuditAction.CUSTOMER_ADJUST)] == [50, -20]


def test_a_debit_beyond_the_balance_becomes_debt(sm: sessionmaker[Session], admin: uuid.UUID) -> None:
    student = add_user(sm, Role.student)
    client = admin_client(sm, admin)
    client.post(_url(student, "adjust"), json={"units": 10, "requestId": str(uuid.uuid4()), "reason": "seed"})
    resp = client.post(
        _url(student, "adjust"), json={"units": -25, "requestId": str(uuid.uuid4()), "reason": "claw back"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["balance"]["creditsAvailable"] == 0
    assert resp.json()["balance"]["outstandingDebt"] == 15
    assert [d["outstanding"] for d in resp.json()["debts"]] == [15]
    [_, row] = audit_rows(sm, AuditAction.CUSTOMER_ADJUST)
    assert (row.before["outstanding_debt"], row.after["outstanding_debt"]) == (0, 15)


def test_a_zero_adjustment_is_422(sm: sessionmaker[Session], admin: uuid.UUID) -> None:
    student = add_user(sm, Role.student)
    resp = admin_client(sm, admin).post(
        _url(student, "adjust"), json={"units": 0, "requestId": str(uuid.uuid4()), "reason": "noop"}
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "zero_adjustment"


def test_forgive_all_then_nothing_left(sm: sessionmaker[Session], admin: uuid.UUID) -> None:
    student = _with_debt(sm, 3)
    client = admin_client(sm, admin)
    first = client.post(_url(student, "forgive-debt"), json={"reason": "estimator bug"})
    second = client.post(_url(student, "forgive-debt"), json={"reason": "estimator bug"})
    assert first.json()["balance"]["outstandingDebt"] == 0
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "no_outstanding_debt"
    [row] = audit_rows(sm, AuditAction.CUSTOMER_FORGIVE_DEBT)
    assert (row.before["outstanding_debt"], row.after["forgiven_units"]) == (3, 3)


def test_forgive_part_of_the_debt(sm: sessionmaker[Session], admin: uuid.UUID) -> None:
    student = _with_debt(sm, 3)
    resp = admin_client(sm, admin).post(_url(student, "forgive-debt"), json={"units": 2, "reason": "part"})
    assert resp.json()["balance"]["outstandingDebt"] == 1


def test_an_unknown_customer_is_404(sm: sessionmaker[Session], admin: uuid.UUID) -> None:
    resp = admin_client(sm, admin).post(
        _url(uuid.uuid4(), "grant"),
        json={"units": 1, "validDays": 1, "requestId": str(uuid.uuid4()), "reason": "who"},
    )
    assert resp.status_code == 404
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest --no-cov tests/test_admin_billing_ledger_actions.py -v`
Expected: FAIL — `AttributeError: 'AdminCustomerService' object has no attribute 'grant_credits'`
for the service test and 404/405 for the HTTP tests (routes missing).

- [ ] **Step 3: Implement the actions**

In `lemely/db/admin_customer_repo.py` extend the `admin_billing_repo` import with
`AdminConflictError`, `AuditAction`, `AuditTarget`, `already_applied`, `audited`,
`lock_idempotency_key`, `require_reason`; add `from dataclasses import asdict`,
`from lemely.db.models.usage import GrantKind` and
`from lemely.db.usage_ledger_repo import UsageLedger`; then add to
`AdminCustomerService`:

```python
    # -- ledger actions (Task 6) -------------------------------------------------

    @staticmethod
    def _require_user(s: Session, user_id: uuid.UUID) -> User:
        user = s.get(User, user_id)
        if user is None:
            raise AdminNotFoundError("customer_not_found")
        return user

    def grant_credits(
        self,
        user_id: uuid.UUID,
        *,
        units: int,
        valid_days: int | None,
        request_id: uuid.UUID,
        admin_user_id: uuid.UUID,
        reason: str,
    ) -> CustomerDetail:
        """Issue visible ``adjustment`` credits. The ledger repays debt first (spec §5.8).

        ``request_id`` makes the call idempotent: a replay finds its own audit row and
        changes nothing.
        """
        require_reason(reason)
        key = f"admin-grant:{request_id}"
        now = self._now()
        with self._sm.begin() as s:
            self._require_user(s, user_id)
            lock_idempotency_key(s, key)
            if not already_applied(s, action=AuditAction.CUSTOMER_GRANT, idempotency_key=key):
                before = asdict(balance_for(s, user_id, now=now))
                issued = UsageLedger(s).issue_grant(
                    owner_user_id=user_id,
                    kind=GrantKind.adjustment,
                    units=units,
                    idempotency_key=key,
                    expires_at=now + timedelta(days=valid_days) if valid_days else None,
                    visible=True,
                    effective_at=now,
                )
                audited(
                    s, admin_user_id, AuditAction.CUSTOMER_GRANT, AuditTarget.USER, user_id, reason,
                    before,
                    {
                        **asdict(balance_for(s, user_id, now=now)),
                        "grant_id": issued.id,
                        "units": units,
                        "expires_at": issued.expires_at,
                        "idempotency_key": key,
                    },
                )
        return self.detail(user_id)

    def adjust(
        self,
        user_id: uuid.UUID,
        *,
        units: int,
        request_id: uuid.UUID,
        admin_user_id: uuid.UUID,
        reason: str,
    ) -> CustomerDetail:
        """Add (positive) or debit (negative) units; a shortfall becomes debt (Phase 01)."""
        require_reason(reason)
        if units == 0:
            raise AdminInvalidError("zero_adjustment", "An adjustment must change the balance.")
        key = f"admin-adjust:{request_id}"
        now = self._now()
        with self._sm.begin() as s:
            self._require_user(s, user_id)
            lock_idempotency_key(s, key)
            if not already_applied(s, action=AuditAction.CUSTOMER_ADJUST, idempotency_key=key):
                before = asdict(balance_for(s, user_id, now=now))
                # Phase 01: a debit larger than the balance records a debt for the shortfall.
                UsageLedger(s).adjust(
                    owner_user_id=user_id, units=units, reason=reason.strip(),
                    idempotency_key=key, now=now,
                )
                audited(
                    s, admin_user_id, AuditAction.CUSTOMER_ADJUST, AuditTarget.USER, user_id, reason,
                    before,
                    {**asdict(balance_for(s, user_id, now=now)), "units": units, "idempotency_key": key},
                )
        return self.detail(user_id)

    def forgive_debt(
        self, user_id: uuid.UUID, *, units: int | None, admin_user_id: uuid.UUID, reason: str
    ) -> CustomerDetail:
        """Forgive ``units`` of outstanding debt, or all of it when ``units`` is None."""
        require_reason(reason)
        now = self._now()
        with self._sm.begin() as s:
            self._require_user(s, user_id)
            before = asdict(balance_for(s, user_id, now=now))
            forgiven = UsageLedger(s).forgive_debt(user_id, units=units, reason=reason.strip(), now=now)
            if forgiven == 0:
                raise AdminConflictError("no_outstanding_debt", "This account owes nothing.")
            audited(
                s, admin_user_id, AuditAction.CUSTOMER_FORGIVE_DEBT, AuditTarget.USER, user_id, reason,
                before,
                {
                    **asdict(balance_for(s, user_id, now=now)),
                    "forgiven_units": forgiven,
                    "requested_units": units,
                },
            )
        return self.detail(user_id)
```

- [ ] **Step 4: Add the DTOs and routes**

Append to `lemely/web/schemas_admin_billing.py` (add `import uuid  # noqa: TC003 - pydantic resolves it`
to the imports):

```python
# -- customer actions -----------------------------------------------------------


class AdminGrantRequestDTO(ApiModel):
    units: Annotated[int, Field(gt=0, le=1_000_000)]
    validDays: Annotated[int, Field(gt=0, le=730)] | None = 365
    requestId: uuid.UUID
    reason: Reason


class AdminAdjustRequestDTO(ApiModel):
    units: Annotated[int, Field(ge=-1_000_000, le=1_000_000)]
    requestId: uuid.UUID
    reason: Reason


class AdminForgiveRequestDTO(ApiModel):
    units: Positive | None = None
    reason: Reason
```

Append to `lemely/web/routers/admin_billing.py` (import the three DTOs):

```python
@router.post("/customers/{user_id}/grant", response_model=CustomerDetailDTO)
def grant_credits(
    user_id: uuid.UUID, body: AdminGrantRequestDTO, service: CustomerService, auth: AdminAuth
) -> CustomerDetailDTO:
    with mapped_errors():
        detail = service.grant_credits(
            user_id, units=body.units, valid_days=body.validDays, request_id=body.requestId,
            admin_user_id=admin_id(auth), reason=body.reason,
        )
    return customer_detail_dto(detail)


@router.post("/customers/{user_id}/adjust", response_model=CustomerDetailDTO)
def adjust_balance(
    user_id: uuid.UUID, body: AdminAdjustRequestDTO, service: CustomerService, auth: AdminAuth
) -> CustomerDetailDTO:
    with mapped_errors():
        detail = service.adjust(
            user_id, units=body.units, request_id=body.requestId, admin_user_id=admin_id(auth),
            reason=body.reason,
        )
    return customer_detail_dto(detail)


@router.post("/customers/{user_id}/forgive-debt", response_model=CustomerDetailDTO)
def forgive_debt(
    user_id: uuid.UUID, body: AdminForgiveRequestDTO, service: CustomerService, auth: AdminAuth
) -> CustomerDetailDTO:
    with mapped_errors():
        detail = service.forgive_debt(
            user_id, units=body.units, admin_user_id=admin_id(auth), reason=body.reason
        )
    return customer_detail_dto(detail)
```

- [ ] **Step 5: Register the routes**

Matrix (`tests/test_authz_matrix_complete.py`, after the Task 5 lines; heading `PLATFORM_ADMIN` +3):

```python
    ("POST", "/api/admin/billing/customers/{user_id}/grant"): PLATFORM_ADMIN,
    ("POST", "/api/admin/billing/customers/{user_id}/adjust"): PLATFORM_ADMIN,
    ("POST", "/api/admin/billing/customers/{user_id}/forgive-debt"): PLATFORM_ADMIN,
```

`PLANNED` in `tests/test_admin_billing_authz.py`:

```python
    ("POST", f"{P}/customers/{{user_id}}/grant"),
    ("POST", f"{P}/customers/{{user_id}}/adjust"),
    ("POST", f"{P}/customers/{{user_id}}/forgive-debt"),
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest --no-cov tests/test_admin_billing_ledger_actions.py tests/test_admin_billing_customers.py tests/test_admin_billing_authz.py tests/test_authz_matrix_complete.py -v`
Expected: all pass, no skips.

- [ ] **Step 7: Commit**

```bash
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files
P="lemely/db/admin_customer_repo.py lemely/web/schemas_admin_billing.py lemely/web/routers/admin_billing.py tests/test_authz_matrix_complete.py tests/test_admin_billing_authz.py tests/test_admin_billing_ledger_actions.py"
git add $P
git commit -S -m "feat(admin): audited grant, adjust and forgive-debt actions" -- $P
```

---

### Task 7: Subscription actions — manual activation, extend, cancel; audited activation queue

**Files:**
- Modify: `lemely/db/admin_customer_repo.py`
- Modify: `lemely/db/admin_repo.py` (`decide_activation` audits)
- Modify: `lemely/web/routers/admin.py` (pass the caller; mark the two routes deprecated)
- Modify: `lemely/web/scheduled_notifications.py` (expiry job)
- Modify: `lemely/web/schemas_admin_billing.py`, `lemely/web/routers/admin_billing.py`
- Modify: `tests/test_web_platform_admin.py`
- Modify: `tests/test_authz_matrix_complete.py`, `tests/test_admin_billing_authz.py`
- Create: `tests/test_admin_billing_subscriptions.py`

**Interfaces:**
- Consumes: Tasks 1, 5, 6; `Subscription`, `SubscriptionPeriod`, `PlanTier`, `PlanAudience`, `SubscriptionStatus` (Phases 02/05); `SubscriptionService.schedule_cancel(subscription_id, *, actor_user_id, now)`, `InvalidPlanChange`, `SubscriptionNotFound`, `SubscriptionConflictError` (Phase 05); `PaymobClient.cancel_subscription` (Phase 02); `UsageLedger.issue_grant`, `GrantKind.period_allowance` (Phase 01).
- Produces:
  - `AdminCustomerService.manual_activation(user_id, *, plan_tier_id: UUID, period_days: int, admin_user_id: UUID, reason: str) -> CustomerDetail`
  - `AdminCustomerService.extend_subscription(subscription_id, *, days: int, admin_user_id: UUID, reason: str) -> CustomerDetail`
  - `AdminCustomerService.cancel_subscription(subscription_id, *, when: Literal["period_end", "now"], admin_user_id: UUID, reason: str) -> CustomerDetail`
  - `expire_manual_subscriptions(factory: sessionmaker[Session], *, now: datetime) -> int`; sweeper job name `admin.expire_manual_subscriptions`.
  - `PlatformAdminService.decide_activation(subscription_id, *, activate, note=None, now=None, admin_user_id: UUID) -> SubscriptionStatus` (audits).
  - DTOs `ManualActivationRequestDTO`, `AdminExtendRequestDTO`, `AdminCancelRequestDTO`.
  - Routes: `POST /customers/{user_id}/manual-activation`, `POST /subscriptions/{subscription_id}/extend`, `POST /subscriptions/{subscription_id}/cancel`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_admin_billing_subscriptions.py`:

```python
"""Subscription actions (spec §8 area 2): complimentary activation, extend, cancel."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from lemely.db.admin_billing_repo import AuditAction
from lemely.db.admin_customer_repo import expire_manual_subscriptions
from lemely.db.models.billing import Subscription, SubscriptionPeriod
from lemely.db.models.enums import Role, SubscriptionStatus
from lemely.db.subscription_repo import SubscriptionService
from tests.admin_billing_db import (
    NOW,
    FakePaymobClient,
    add_plan_tier,
    add_subscription,
    add_user,
    admin_client,
    audit_rows,
    billing_database,
    emptied_after,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture(scope="module")
def billing_db() -> Iterator[sessionmaker[Session]]:
    with billing_database() as factory:
        yield factory


@pytest.fixture
def sm(billing_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(billing_db)


@pytest.fixture
def admin(sm: sessionmaker[Session]) -> uuid.UUID:
    return add_user(sm, Role.platform_admin)


def test_manual_activation_creates_a_live_complimentary_plan(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    student = add_user(sm, Role.student)
    tier = add_plan_tier(sm, allowance_units=1000)
    resp = admin_client(sm, admin).post(
        f"/api/admin/billing/customers/{student}/manual-activation",
        json={"planTierId": str(tier), "periodDays": 30, "reason": "school pilot"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    [sub] = body["subscriptions"]
    assert (sub["status"], sub["isManuallyActivated"], sub["paymobSubscriptionId"]) == ("active", True, None)
    # Compare instants, not strings: pydantic writes "Z", isoformat() writes "+00:00".
    assert datetime.fromisoformat(sub["currentPeriodEnd"]) == NOW + timedelta(days=30)
    [allowance] = [g for g in body["grants"] if g["kind"] == "period_allowance"]
    assert (allowance["units"], allowance["visible"]) == (1000, False)
    assert datetime.fromisoformat(allowance["expiresAt"]) == NOW + timedelta(days=30)
    assert body["balance"]["allowanceAvailable"] == 1000
    [row] = audit_rows(sm, AuditAction.SUBSCRIPTION_MANUAL_ACTIVATION)
    assert row.target_id == uuid.UUID(sub["id"])
    assert row.after["allowance_grant_id"] == allowance["id"]


def test_a_second_live_plan_is_409(sm: sessionmaker[Session], admin: uuid.UUID) -> None:
    student = add_user(sm, Role.student)
    tier = add_plan_tier(sm)
    add_subscription(sm, student, tier)
    resp = admin_client(sm, admin).post(
        f"/api/admin/billing/customers/{student}/manual-activation",
        json={"planTierId": str(tier), "periodDays": 30, "reason": "dup"},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "live_subscription_exists"


def test_a_teacher_tier_for_a_student_is_422(sm: sessionmaker[Session], admin: uuid.UUID) -> None:
    student = add_user(sm, Role.student)
    tier = add_plan_tier(sm, code="teacher_monthly", audience="teacher", included_seats=5)
    resp = admin_client(sm, admin).post(
        f"/api/admin/billing/customers/{student}/manual-activation",
        json={"planTierId": str(tier), "periodDays": 30, "reason": "wrong"},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "audience_mismatch"


def test_extend_moves_the_period_end_of_a_complimentary_plan(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    student = add_user(sm, Role.student)
    sub = add_subscription(sm, student, add_plan_tier(sm), manual=True, end=NOW + timedelta(days=5))
    resp = admin_client(sm, admin).post(
        f"/api/admin/billing/subscriptions/{sub}/extend", json={"days": 10, "reason": "exam season"}
    )
    assert resp.status_code == 200, resp.text
    with sm() as session:
        assert session.get(Subscription, sub).current_period_end == NOW + timedelta(days=15)
        period = session.query(SubscriptionPeriod).filter_by(subscription_id=sub).one()
        assert period.period_end == NOW + timedelta(days=15)
    [row] = audit_rows(sm, AuditAction.SUBSCRIPTION_EXTEND)
    assert datetime.fromisoformat(row.before["current_period_end"]) == NOW + timedelta(days=5)


def test_extending_a_paymob_billed_plan_is_409(sm: sessionmaker[Session], admin: uuid.UUID) -> None:
    student = add_user(sm, Role.student)
    sub = add_subscription(sm, student, add_plan_tier(sm), paymob_subscription_id=7001)
    resp = admin_client(sm, admin).post(
        f"/api/admin/billing/subscriptions/{sub}/extend", json={"days": 10, "reason": "no"}
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "paymob_billed"
    assert audit_rows(sm, AuditAction.SUBSCRIPTION_EXTEND) == []


def test_cancel_at_period_end_then_the_sweeper_ends_complimentary_plans(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    tier = add_plan_tier(sm)
    end = NOW + timedelta(days=3)
    cancelled = add_subscription(sm, add_user(sm, Role.student), tier, manual=True, end=end)
    lapsing = add_subscription(sm, add_user(sm, Role.student), tier, manual=True, end=end)
    legacy = add_subscription(sm, add_user(sm, Role.student), tier, manual=True, end=None)
    resp = admin_client(sm, admin).post(
        f"/api/admin/billing/subscriptions/{cancelled}/cancel",
        json={"when": "period_end", "reason": "pilot over"},
    )
    assert resp.status_code == 200, resp.text

    assert expire_manual_subscriptions(sm, now=end - timedelta(seconds=1)) == 0
    assert expire_manual_subscriptions(sm, now=end) == 2
    with sm() as session:
        assert session.get(Subscription, cancelled).status is SubscriptionStatus.cancelled
        assert session.get(Subscription, lapsing).status is SubscriptionStatus.expired
        assert session.get(Subscription, legacy).status is SubscriptionStatus.active
    [row] = audit_rows(sm, AuditAction.SUBSCRIPTION_CANCEL)
    assert row.after["when"] == "period_end"


def test_cancel_now_cancels_at_paymob_first(sm: sessionmaker[Session], admin: uuid.UUID) -> None:
    student = add_user(sm, Role.student)
    sub = add_subscription(sm, student, add_plan_tier(sm), paymob_subscription_id=7001)
    paymob = FakePaymobClient()
    resp = admin_client(sm, admin, paymob=paymob).post(
        f"/api/admin/billing/subscriptions/{sub}/cancel", json={"when": "now", "reason": "fraud"}
    )
    assert resp.status_code == 200, resp.text
    assert paymob.calls == [("cancel_subscription", {"subscription_id": 7001})]
    with sm() as session:
        row = session.get(Subscription, sub)
        assert (row.status, row.current_period_end) == (SubscriptionStatus.cancelled, NOW)
    assert len(audit_rows(sm, AuditAction.SUBSCRIPTION_CANCEL)) == 1


def test_a_paymob_cancel_failure_changes_nothing(sm: sessionmaker[Session], admin: uuid.UUID) -> None:
    student = add_user(sm, Role.student)
    sub = add_subscription(sm, student, add_plan_tier(sm), paymob_subscription_id=7001)
    paymob = FakePaymobClient(cancel_result=RuntimeError("paymob down"))
    resp = admin_client(sm, admin, paymob=paymob).post(
        f"/api/admin/billing/subscriptions/{sub}/cancel", json={"when": "now", "reason": "fraud"}
    )
    assert resp.status_code == 502
    with sm() as session:
        assert session.get(Subscription, sub).status is SubscriptionStatus.active
    assert audit_rows(sm, AuditAction.SUBSCRIPTION_CANCEL) == []


def test_cancel_at_period_end_of_a_paymob_plan_goes_through_phase_05(
    sm: sessionmaker[Session], admin: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    student = add_user(sm, Role.student)
    sub = add_subscription(sm, student, add_plan_tier(sm), paymob_subscription_id=7001)
    seen: list[uuid.UUID] = []

    def fake_schedule_cancel(
        self: SubscriptionService, subscription_id: uuid.UUID, *, actor_user_id: uuid.UUID, now: object
    ) -> None:
        seen.append(subscription_id)
        assert actor_user_id == student  # the payer: Phase 05 locks on the payer

    monkeypatch.setattr(SubscriptionService, "schedule_cancel", fake_schedule_cancel)
    resp = admin_client(sm, admin).post(
        f"/api/admin/billing/subscriptions/{sub}/cancel", json={"when": "period_end", "reason": "asked"}
    )
    assert resp.status_code == 200, resp.text
    assert seen == [sub]
    assert len(audit_rows(sm, AuditAction.SUBSCRIPTION_CANCEL)) == 1


def test_cancelling_a_cancelled_plan_is_409(sm: sessionmaker[Session], admin: uuid.UUID) -> None:
    student = add_user(sm, Role.student)
    sub = add_subscription(sm, student, add_plan_tier(sm), status=SubscriptionStatus.cancelled)
    resp = admin_client(sm, admin).post(
        f"/api/admin/billing/subscriptions/{sub}/cancel", json={"when": "now", "reason": "again"}
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "not_live"
```

In `tests/test_web_platform_admin.py`:

1. Add `from lemely.db.models.admin_audit import AdminAuditLog` to the imports.
2. In `_client`, replace `user_id=str(uuid.uuid4())` with a real admin row (the audit log has a
   foreign key to `users`):

```python
    admin_id = _user(sm, Role.platform_admin)
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(
        user_id=str(admin_id), role=Role.platform_admin.value
    )
```

3. Add `admin_user_id=_user(pg_sessionmaker, Role.platform_admin)` to every direct
   `decide_activation(...)` call — the original four and the two in Phase 05's appended
   `test_activation_is_refused_while_the_user_has_a_live_subscription` section (in the "second
   decision" test create the admin once and pass it to both calls). Phase 05's conflict test must
   still raise `SubscriptionConflictError` and write no audit row: add
   `assert session.scalars(sa.select(AdminAuditLog)).all() == []` to it.
4. Add:

```python
def test_each_activation_decision_is_audited(pg_sessionmaker: sessionmaker[Session]) -> None:
    plan = _plan(pg_sessionmaker)
    admin = _user(pg_sessionmaker, Role.platform_admin)
    with_note = _subscription(pg_sessionmaker, _user(pg_sessionmaker, Role.student), plan)
    without_note = _subscription(pg_sessionmaker, _user(pg_sessionmaker, Role.student), plan)
    service = PlatformAdminService(pg_sessionmaker)

    service.decide_activation(with_note, activate=True, note="Paid by transfer", admin_user_id=admin)
    service.decide_activation(without_note, activate=False, admin_user_id=admin)

    with pg_sessionmaker() as session:
        rows = {r.target_id: r for r in session.scalars(sa.select(AdminAuditLog))}
    assert rows[with_note].reason == "Paid by transfer"
    assert rows[with_note].after == {"status": "active", "is_manually_activated": True}
    assert rows[without_note].reason == "Decided from the activations queue without a note."
    assert rows[without_note].before == {"status": "inactive"}
    assert {r.admin_user_id for r in rows.values()} == {admin}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest --no-cov tests/test_admin_billing_subscriptions.py tests/test_web_platform_admin.py -v`
Expected: FAIL — `ImportError: cannot import name 'expire_manual_subscriptions'`; in
`test_web_platform_admin.py`, `TypeError: … unexpected keyword argument 'admin_user_id'`.

- [ ] **Step 3: Audit the activation queue**

In `lemely/db/admin_repo.py` import `AuditAction`, `AuditTarget`, `audited` from
`lemely.db.admin_billing_repo`, add the module constant

```python
#: The audit reason when the legacy activation screen sends no note (spec §8: a reason is required).
NO_NOTE_REASON = "Decided from the activations queue without a note."
```

and change `decide_activation` to:

```python
    def decide_activation(
        self,
        subscription_id: uuid.UUID | str,
        *,
        activate: bool,
        note: str | None = None,
        now: datetime | None = None,
        admin_user_id: uuid.UUID,
    ) -> SubscriptionStatus:
        """Activate or reject a pending subscription, recording the note and an audit row.

        (keep the existing docstring paragraphs and Raises section here)
        """
        moment = now or datetime.now(UTC)
        subscription_uuid = _as_uuid(subscription_id)
        with self._sessionmaker() as session, session.begin():
            subscription = session.get(Subscription, subscription_uuid, with_for_update=True)
            if subscription is None:
                raise SubscriptionNotFoundError(f"Unknown subscription: {subscription_uuid}")
            if subscription.status is not SubscriptionStatus.inactive:
                raise SubscriptionAlreadyDecidedError(subscription.status)
            before = {"status": subscription.status.value}
            if activate:
                subscription.status = SubscriptionStatus.active
                subscription.is_manually_activated = True
                subscription.activated_at = moment
                try:
                    session.flush()
                except IntegrityError as exc:  # Phase 05: one live subscription per user
                    raise SubscriptionConflictError(
                        "This user already has a live subscription; end it before activating"
                        " another."
                    ) from exc
            else:
                subscription.status = SubscriptionStatus.rejected
            subscription.activation_note = note
            audited(
                session,
                admin_user_id,
                AuditAction.SUBSCRIPTION_ACTIVATION_DECISION,
                AuditTarget.SUBSCRIPTION,
                subscription.id,
                (note or "").strip() or NO_NOTE_REASON,
                before,
                {
                    "status": subscription.status.value,
                    "is_manually_activated": subscription.is_manually_activated,
                },
            )
            return subscription.status
```

In `lemely/web/routers/admin.py`: add `deprecated=True` to the two
`@router.post("/admin/activations/{subscription_id}/activate|reject", …)` decorators, add the
parameter `auth: Annotated[AuthContext, Depends(require_role(Role.platform_admin))]` to both
handlers, give `_decide` a keyword `admin_user_id: uuid.UUID`, pass
`admin_user_id=uuid.UUID(auth.user_id)` from both handlers, and forward it to
`service.decide_activation(...)`. Extend the docstring of `activate_subscription` with:
"Deprecated: the admin billing customer view's manual activation (`/api/admin/billing`) is the
new home; this route stays for the existing Activations screen and is audited."

- [ ] **Step 4: Implement the subscription actions and the expiry job**

In `lemely/db/admin_customer_repo.py` add imports (`from typing import Literal`,
`PaymobCallError`, `snapshot` from `admin_billing_repo`, `PlanAudience` from
`lemely.db.models.billing`, `Role`, `SubscriptionStatus` from `lemely.db.models.enums`,
`InvalidPlanChange`, `SubscriptionNotFound`, `SubscriptionService` from
`lemely.db.subscription_repo`) and:

```python
_LIVE = (
    SubscriptionStatus.pending_first_payment,
    SubscriptionStatus.active,
    SubscriptionStatus.past_due,
)
_AUDIENCE_ROLE = {PlanAudience.student: Role.student, PlanAudience.teacher: Role.teacher}
_SUBSCRIPTION_AUDIT = (
    "status",
    "plan_tier_id",
    "current_period_start",
    "current_period_end",
    "cancel_at_period_end",
    "is_manually_activated",
    "paymob_subscription_id",
)


def expire_manual_subscriptions(factory: sessionmaker[Session], *, now: datetime) -> int:
    """End complimentary subscriptions whose period has run out (sweeper job).

    Only admin-created ones: manually activated, no Paymob subscription, and a period
    end (legacy manual activations have none and run until an admin cancels them).
    ``cancel_at_period_end`` ends as ``cancelled``; otherwise ``expired``.
    """
    with factory.begin() as session:
        rows = list(
            session.scalars(
                select(Subscription)
                .where(
                    Subscription.is_manually_activated.is_(True),
                    Subscription.paymob_subscription_id.is_(None),
                    Subscription.status == SubscriptionStatus.active,
                    Subscription.current_period_end.is_not(None),
                    Subscription.current_period_end <= now,
                )
                .with_for_update(skip_locked=True)
            )
        )
        for sub in rows:
            sub.status = (
                SubscriptionStatus.cancelled if sub.cancel_at_period_end else SubscriptionStatus.expired
            )
        return len(rows)
```

Add `"expire_manual_subscriptions"` to `__all__`, and to `AdminCustomerService`:

```python
    # -- subscription actions (Task 7) -------------------------------------------

    def manual_activation(
        self,
        user_id: uuid.UUID,
        *,
        plan_tier_id: uuid.UUID,
        period_days: int,
        admin_user_id: uuid.UUID,
        reason: str,
    ) -> CustomerDetail:
        """Create a live complimentary subscription with its period and allowance grant.

        No payment and no Paymob subscription: ``expire_manual_subscriptions`` ends it.
        Teacher seats pick up seat allowances from Phase 05's monthly job like any live plan.
        """
        require_reason(reason)
        now = self._now()
        with self._sm.begin() as s:
            user = self._require_user(s, user_id)
            tier = s.get(PlanTier, plan_tier_id)
            if tier is None:
                raise AdminNotFoundError("plan_tier_not_found")
            if user.role is not _AUDIENCE_ROLE[tier.audience]:
                raise AdminInvalidError("audience_mismatch", "That tier is for another role.")
            lock_idempotency_key(s, f"live-subscription:{user_id}")
            # One live subscription per user (index R8: Phase 02's partial unique index).
            live = s.scalar(
                select(Subscription.id)
                .where(Subscription.user_id == user_id, Subscription.status.in_(_LIVE))
                .limit(1)
            )
            if live is not None:
                raise AdminConflictError("live_subscription_exists", "Cancel the live plan first.")
            end = now + timedelta(days=period_days)
            sub = Subscription(
                user_id=user_id,
                payer_user_id=user_id,
                plan_tier_id=tier.id,
                status=SubscriptionStatus.active,
                is_manually_activated=True,
                activated_at=now,
                activation_note=reason.strip(),
                current_period_start=now,
                current_period_end=end,
            )
            s.add(sub)
            s.flush()
            period = SubscriptionPeriod(subscription_id=sub.id, period_start=now, period_end=end)
            s.add(period)
            s.flush()
            grant_id: uuid.UUID | None = None
            if tier.allowance_units > 0:
                grant_id = UsageLedger(s).issue_grant(
                    owner_user_id=user_id,
                    kind=GrantKind.period_allowance,
                    units=tier.allowance_units,
                    idempotency_key=f"admin-activation:{sub.id}",
                    expires_at=end,
                    visible=False,
                    effective_at=now,
                    subscription_period_id=period.id,
                ).id
            audited(
                s, admin_user_id, AuditAction.SUBSCRIPTION_MANUAL_ACTIVATION, AuditTarget.SUBSCRIPTION,
                sub.id, reason, None,
                {**snapshot(sub, _SUBSCRIPTION_AUDIT), "allowance_grant_id": grant_id},
            )
        return self.detail(user_id)

    def extend_subscription(
        self, subscription_id: uuid.UUID, *, days: int, admin_user_id: uuid.UUID, reason: str
    ) -> CustomerDetail:
        """Push a complimentary plan's period end out by ``days`` (deviation 8)."""
        require_reason(reason)
        with self._sm.begin() as s:
            sub = s.get(Subscription, subscription_id, with_for_update=True)
            if sub is None:
                raise AdminNotFoundError("subscription_not_found")
            if sub.paymob_subscription_id is not None:
                raise AdminConflictError("paymob_billed", "Grant credits instead; Paymob owns the date.")
            if not sub.is_manually_activated or sub.status is not SubscriptionStatus.active:
                raise AdminConflictError("not_extendable", "Only live complimentary plans extend.")
            if sub.current_period_end is None:
                raise AdminConflictError("open_ended", "This plan has no end to extend.")
            before = snapshot(sub, _SUBSCRIPTION_AUDIT)
            sub.current_period_end = sub.current_period_end + timedelta(days=days)
            latest = s.scalars(
                select(SubscriptionPeriod)
                .where(SubscriptionPeriod.subscription_id == sub.id)
                .order_by(SubscriptionPeriod.period_start.desc())
                .limit(1)
            ).first()
            if latest is not None:
                latest.period_end = sub.current_period_end
            s.flush()
            audited(
                s, admin_user_id, AuditAction.SUBSCRIPTION_EXTEND, AuditTarget.SUBSCRIPTION, sub.id,
                reason, before, {**snapshot(sub, _SUBSCRIPTION_AUDIT), "days": days},
            )
            user_id = sub.user_id
        return self.detail(user_id)

    def cancel_subscription(
        self,
        subscription_id: uuid.UUID,
        *,
        when: Literal["period_end", "now"],
        admin_user_id: uuid.UUID,
        reason: str,
    ) -> CustomerDetail:
        """Cancel now (Paymob first, then the row) or at period end.

        A Paymob-billed period-end cancel goes through Phase 05's ``schedule_cancel``;
        a complimentary one sets ``cancel_at_period_end`` for ``expire_manual_subscriptions``.
        If Paymob cancels but the DB write then fails, Phase 05's daily drift check
        mirrors Paymob's state.
        """
        require_reason(reason)
        now = self._now()
        with self._sm() as s:
            sub = s.get(Subscription, subscription_id)
            if sub is None:
                raise AdminNotFoundError("subscription_not_found")
            if sub.status not in _LIVE:
                raise AdminConflictError("not_live", "Only a live plan can be cancelled.")
            paymob_id = sub.paymob_subscription_id
        if when == "now" and paymob_id is not None:
            try:
                self._client.cancel_subscription(int(paymob_id))
            except Exception as exc:  # noqa: BLE001 - any Paymob failure is a 502 with no DB change
                raise PaymobCallError("paymob_cancel_failed", str(exc)) from exc
        with self._sm.begin() as s:
            sub = s.get(Subscription, subscription_id, with_for_update=True)
            if sub is None or sub.status not in _LIVE:
                raise AdminConflictError("not_live", "Only a live plan can be cancelled.")
            before = snapshot(sub, _SUBSCRIPTION_AUDIT)
            if when == "now":
                sub.status = SubscriptionStatus.cancelled
                sub.cancel_at_period_end = False
                sub.current_period_end = now
            elif paymob_id is not None:
                try:
                    SubscriptionService(s, self._client, self._settings).schedule_cancel(
                        sub.id, actor_user_id=sub.payer_user_id, now=now
                    )
                except (InvalidPlanChange, SubscriptionNotFound) as exc:
                    raise AdminConflictError("not_live", str(exc)) from exc
            else:
                sub.cancel_at_period_end = True
            s.flush()
            audited(
                s, admin_user_id, AuditAction.SUBSCRIPTION_CANCEL, AuditTarget.SUBSCRIPTION, sub.id,
                reason, before, {**snapshot(sub, _SUBSCRIPTION_AUDIT), "when": when},
            )
            user_id = sub.user_id
        return self.detail(user_id)
```

- [ ] **Step 5: Run the job on the sweeper and keep Phase 05 off complimentary plans**

In `lemely/web/scheduled_notifications.py` import `expire_manual_subscriptions` from
`lemely.db.admin_customer_repo` and, in `Sweeper.sweep_once`, append to `jobs` before the
`storage`/`bucket` block:

```python
        jobs.append(
            (
                "admin.expire_manual_subscriptions",
                lambda: expire_manual_subscriptions(self.sessionmaker, now=moment),
            )
        )
```

If a test in `tests/test_scheduled_notifications.py` asserts the exact key set `sweep_once`
returns, add `"admin.expire_manual_subscriptions"` to it (its value is `None` there when the test's
sessionmaker has no `subscriptions` table — `run_jobs` already reports a raising job as `None`).

Phase 05's period-end, overdue and drift queries already skip rows without a
`paymob_subscription_id` (index R15); nothing to change there.

- [ ] **Step 6: Add the DTOs and routes**

Append to `lemely/web/schemas_admin_billing.py`:

```python
class ManualActivationRequestDTO(ApiModel):
    planTierId: uuid.UUID
    periodDays: Annotated[int, Field(gt=0, le=400)]
    reason: Reason


class AdminExtendRequestDTO(ApiModel):
    days: Annotated[int, Field(gt=0, le=366)]
    reason: Reason


class AdminCancelRequestDTO(ApiModel):
    when: Literal["period_end", "now"]
    reason: Reason
```

Append to `lemely/web/routers/admin_billing.py` (import the three DTOs):

```python
@router.post("/customers/{user_id}/manual-activation", response_model=CustomerDetailDTO)
def manual_activation(
    user_id: uuid.UUID, body: ManualActivationRequestDTO, service: CustomerService, auth: AdminAuth
) -> CustomerDetailDTO:
    with mapped_errors():
        detail = service.manual_activation(
            user_id, plan_tier_id=body.planTierId, period_days=body.periodDays,
            admin_user_id=admin_id(auth), reason=body.reason,
        )
    return customer_detail_dto(detail)


@router.post("/subscriptions/{subscription_id}/extend", response_model=CustomerDetailDTO)
def extend_subscription(
    subscription_id: uuid.UUID, body: AdminExtendRequestDTO, service: CustomerService, auth: AdminAuth
) -> CustomerDetailDTO:
    with mapped_errors():
        detail = service.extend_subscription(
            subscription_id, days=body.days, admin_user_id=admin_id(auth), reason=body.reason
        )
    return customer_detail_dto(detail)


@router.post("/subscriptions/{subscription_id}/cancel", response_model=CustomerDetailDTO)
def cancel_subscription(
    subscription_id: uuid.UUID, body: AdminCancelRequestDTO, service: CustomerService, auth: AdminAuth
) -> CustomerDetailDTO:
    with mapped_errors():
        detail = service.cancel_subscription(
            subscription_id, when=body.when, admin_user_id=admin_id(auth), reason=body.reason
        )
    return customer_detail_dto(detail)
```

- [ ] **Step 7: Register the routes**

Matrix (+3 to the `PLATFORM_ADMIN` heading):

```python
    ("POST", "/api/admin/billing/customers/{user_id}/manual-activation"): PLATFORM_ADMIN,
    ("POST", "/api/admin/billing/subscriptions/{subscription_id}/extend"): PLATFORM_ADMIN,
    ("POST", "/api/admin/billing/subscriptions/{subscription_id}/cancel"): PLATFORM_ADMIN,
```

`PLANNED`:

```python
    ("POST", f"{P}/customers/{{user_id}}/manual-activation"),
    ("POST", f"{P}/subscriptions/{{subscription_id}}/extend"),
    ("POST", f"{P}/subscriptions/{{subscription_id}}/cancel"),
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest --no-cov tests/test_admin_billing_subscriptions.py tests/test_web_platform_admin.py tests/test_scheduled_notifications.py tests/test_admin_billing_authz.py tests/test_authz_matrix_complete.py $(grep -rln "SubscriptionService" tests/ | grep -v admin_billing) -v`
Expected: all pass, no skips.

- [ ] **Step 9: Commit**

```bash
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files
P="lemely/db/admin_customer_repo.py lemely/db/admin_repo.py lemely/web/routers/admin.py lemely/web/scheduled_notifications.py lemely/web/schemas_admin_billing.py lemely/web/routers/admin_billing.py tests/test_web_platform_admin.py tests/test_scheduled_notifications.py tests/test_authz_matrix_complete.py tests/test_admin_billing_authz.py tests/test_admin_billing_subscriptions.py"
git add $P
git commit -S -m "feat(admin): complimentary activation, extend and cancel; audit the activation queue" -- $P
```

### Task 8: Refund and void, with the refund row written before Paymob is called

**Files:**
- Create: `lemely/db/admin_payments_repo.py`
- Modify: `lemely/web/deps_admin_billing.py`, `lemely/web/routers/admin_billing.py`, `lemely/web/schemas_admin_billing.py`
- Modify: `tests/admin_billing_db.py` (payments service override)
- Modify: `tests/test_authz_matrix_complete.py`, `tests/test_admin_billing_authz.py`
- Create: `tests/test_admin_billing_refunds.py`

**Interfaces:**
- Consumes: `PaymentRefund`, `RefundKind`, `RefundStatus` (Task 1); `audited`, `to_jsonable`, `require_reason`, `PaymentView`, `payment_views`, errors, `AuditAction.PAYMENT_*` (Tasks 1, 5); `payment_row_dto` (Task 5); `Payment`, `PaymentStatus`, `PaymentPurpose`, `PaymobClient.refund/void`, `PaymobError` (Phase 02); `UsageLedger.claw_back_grant`, `UsageGrant` (Phase 01).
- Produces:
  - `AdminPaymentsService(sessionmaker, client, paymob_settings, *, now=...)` with `refund(payment_id, *, amount_minor: int | None, admin_user_id, reason) -> PaymentView`, `void(payment_id, *, admin_user_id, reason) -> PaymentView`, `payment_view(payment_id) -> PaymentView`, and the private `_close_refund(refund_id, *, outcome, response, admin_user_id, reason) -> None` that Task 9 reuses.
  - `get_admin_payments_service()`; DTO `AdminRefundRequestDTO`.
  - Routes: `POST /payments/{payment_id}/refund`, `POST /payments/{payment_id}/void` (each answers `AdminPaymentRowDTO`).

- [ ] **Step 1: Extend the test helpers**

In `tests/admin_billing_db.py` import `AdminPaymentsService` from `lemely.db.admin_payments_repo`
and `get_admin_payments_service` from `lemely.web.deps_admin_billing`, and add to the dict returned
by `service_overrides`:

```python
        get_admin_payments_service: lambda: AdminPaymentsService(
            factory, paymob, TEST_PAYMOB, now=clock  # type: ignore[arg-type]
        ),
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_admin_billing_refunds.py`:

```python
"""Refunds and voids (spec §6, §8 area 2): row first, Paymob second, unspent units clawed back."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import select

from lemely.core.usage_types import GrantScope, Payer
from lemely.db.admin_billing_repo import AuditAction
from lemely.db.models.billing import Payment, PaymentStatus
from lemely.db.models.billing_ops import PaymentRefund, RefundStatus
from lemely.db.models.enums import Role
from lemely.io.paymob.client import PaymobError
from tests.admin_billing_db import (
    FakePaymobClient,
    add_payment,
    add_rate,
    add_user,
    admin_client,
    audit_rows,
    billing_database,
    emptied_after,
    grant,
    metered_job,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture(scope="module")
def billing_db() -> Iterator[sessionmaker[Session]]:
    with billing_database() as factory:
        yield factory


@pytest.fixture
def sm(billing_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(billing_db)


@pytest.fixture
def admin(sm: sessionmaker[Session]) -> uuid.UUID:
    return add_user(sm, Role.platform_admin)


def _pack_bought_and_partly_spent(sm: sessionmaker[Session]) -> tuple[uuid.UUID, uuid.UUID]:
    """A paid 10,000-piaster pack of 500 units, of which a job spent 200. Returns (student, payment)."""
    student = add_user(sm, Role.student)
    payment = add_payment(sm, payer=student, amount_minor=10000, paymob_order_id=777001, paymob_txn_id=888001)
    grant(sm, student, units=500, payment_id=payment)
    add_rate(sm, "mark_paper")
    metered_job(
        sm, student, [Payer(owner_user_id=student, scope=GrantScope.CREDITS)],
        low=150, high=250, cost=Decimal("0.2"),
    )
    return student, payment


def _credits(sm: sessionmaker[Session], admin: uuid.UUID, student: uuid.UUID) -> int:
    body = admin_client(sm, admin).get(f"/api/admin/billing/customers/{student}").json()
    return int(body["balance"]["creditsAvailable"])


def test_a_full_refund_claws_back_only_unspent_units(sm: sessionmaker[Session], admin: uuid.UUID) -> None:
    student, payment = _pack_bought_and_partly_spent(sm)
    paymob = FakePaymobClient()
    resp = admin_client(sm, admin, paymob=paymob).post(
        f"/api/admin/billing/payments/{payment}/refund", json={"amountMinor": None, "reason": "duplicate purchase"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["status"], body["refundedMinor"]) == ("refunded", 10000)
    [refund] = body["refunds"]
    assert (refund["status"], refund["clawedBackUnits"]) == ("succeeded", 300)
    assert paymob.calls == [("refund", {"transaction_id": 888001, "amount_cents": 10000})]
    assert _credits(sm, admin, student) == 0
    assert len(audit_rows(sm, AuditAction.PAYMENT_REFUND_REQUESTED)) == 1
    [done] = audit_rows(sm, AuditAction.PAYMENT_REFUND_SUCCEEDED)
    assert (done.before["status"], done.after["status"]) == ("paid", "refunded")


def test_the_refund_row_exists_before_paymob_is_called(sm: sessionmaker[Session], admin: uuid.UUID) -> None:
    _, payment = _pack_bought_and_partly_spent(sm)
    seen: list[RefundStatus] = []

    class Inspecting(FakePaymobClient):
        def refund(self, **kwargs: Any) -> dict[str, Any]:
            with sm() as session:
                seen.extend(session.scalars(select(PaymentRefund.status)))
            return {"id": 1, "success": True}

    admin_client(sm, admin, paymob=Inspecting()).post(
        f"/api/admin/billing/payments/{payment}/refund", json={"amountMinor": 4000, "reason": "partial"}
    )
    assert seen == [RefundStatus.requested]


def test_a_partial_refund_keeps_the_credits_until_the_rest_is_refunded(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    student, payment = _pack_bought_and_partly_spent(sm)
    client = admin_client(sm, admin)
    partial = client.post(f"/api/admin/billing/payments/{payment}/refund", json={"amountMinor": 4000, "reason": "goodwill"})
    assert (partial.json()["status"], partial.json()["refundedMinor"]) == ("partially_refunded", 4000)
    assert _credits(sm, admin, student) == 300
    rest = client.post(f"/api/admin/billing/payments/{payment}/refund", json={"amountMinor": None, "reason": "rest"})
    assert (rest.json()["status"], rest.json()["refundedMinor"]) == ("refunded", 10000)
    assert rest.json()["refunds"][-1]["amountMinor"] == 6000
    assert _credits(sm, admin, student) == 0


def test_more_than_the_remainder_is_422_and_touches_nothing(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    _, payment = _pack_bought_and_partly_spent(sm)
    paymob = FakePaymobClient()
    resp = admin_client(sm, admin, paymob=paymob).post(
        f"/api/admin/billing/payments/{payment}/refund", json={"amountMinor": 10001, "reason": "too much"}
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "refund_amount_out_of_range"
    assert paymob.calls == []
    assert audit_rows(sm, AuditAction.PAYMENT_REFUND_REQUESTED) == []
    with sm() as session:
        assert session.scalars(select(PaymentRefund)).all() == []


def test_a_paymob_refusal_fails_the_refund_and_keeps_the_payment_paid(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    _, payment = _pack_bought_and_partly_spent(sm)
    paymob = FakePaymobClient(refund_result=PaymobError("declined", status_code=400, body={"detail": "no"}))
    resp = admin_client(sm, admin, paymob=paymob).post(
        f"/api/admin/billing/payments/{payment}/refund", json={"amountMinor": None, "reason": "try"}
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "paid"
    assert resp.json()["refunds"][0]["status"] == "failed"
    assert len(audit_rows(sm, AuditAction.PAYMENT_REFUND_FAILED)) == 1


def test_a_timeout_leaves_the_refund_unknown_and_blocks_a_retry(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    _, payment = _pack_bought_and_partly_spent(sm)
    paymob = FakePaymobClient(refund_result=PaymobError("timed out", timeout=True))
    client = admin_client(sm, admin, paymob=paymob)
    first = client.post(f"/api/admin/billing/payments/{payment}/refund", json={"amountMinor": None, "reason": "try"})
    assert first.json()["refunds"][0]["status"] == "unknown"
    second = client.post(f"/api/admin/billing/payments/{payment}/refund", json={"amountMinor": None, "reason": "again"})
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "refund_in_flight"
    assert len(paymob.calls) == 1
    assert len(audit_rows(sm, AuditAction.PAYMENT_REFUND_UNKNOWN)) == 1


def test_void_voids_and_claws_back(sm: sessionmaker[Session], admin: uuid.UUID) -> None:
    student, payment = _pack_bought_and_partly_spent(sm)
    paymob = FakePaymobClient()
    resp = admin_client(sm, admin, paymob=paymob).post(
        f"/api/admin/billing/payments/{payment}/void", json={"reason": "same-day mistake"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "voided"
    assert resp.json()["refunds"][0]["kind"] == "void"
    assert paymob.calls == [("void", {"transaction_id": 888001})]
    assert _credits(sm, admin, student) == 0
    assert len(audit_rows(sm, AuditAction.PAYMENT_VOID_REQUESTED)) == 1


def test_void_after_a_partial_refund_is_409(sm: sessionmaker[Session], admin: uuid.UUID) -> None:
    _, payment = _pack_bought_and_partly_spent(sm)
    client = admin_client(sm, admin)
    client.post(f"/api/admin/billing/payments/{payment}/refund", json={"amountMinor": 1000, "reason": "part"})
    resp = client.post(f"/api/admin/billing/payments/{payment}/void", json={"reason": "void"})
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "not_voidable"


def test_an_unpaid_payment_is_not_refundable(sm: sessionmaker[Session], admin: uuid.UUID) -> None:
    student = add_user(sm, Role.student)
    payment = add_payment(sm, payer=student, status=PaymentStatus.failed, paymob_txn_id=1)
    resp = admin_client(sm, admin).post(
        f"/api/admin/billing/payments/{payment}/refund", json={"amountMinor": None, "reason": "no"}
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "not_refundable"
    with sm() as session:
        assert session.get(Payment, payment).status is PaymentStatus.failed
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest --no-cov tests/test_admin_billing_refunds.py -v`
Expected: collection error, `No module named 'lemely.db.admin_payments_repo'`.

- [ ] **Step 4: Write the payments service (refund and void)**

Create `lemely/db/admin_payments_repo.py`:

```python
"""Admin payments (spec §6 refunds, §8 area 3): refund, void, list, problem queue, reconcile.

**Refunds follow spec §6 "insert our own refund row before calling Paymob".** One
transaction writes a ``requested`` row and its audit row; Paymob is called with no
transaction open; a second transaction records the outcome:

* ``succeeded`` — the payment becomes ``refunded``/``partially_refunded``/``voided``;
  a fully refunded or voided credit pack or auto top-up claws back the unspent units of
  its grants (spent units stay spent).
* ``failed`` — Paymob answered with a refusal (a 4xx). Nothing else changes.
* ``unknown`` — timeout, transport error or 5xx: Paymob may have refunded. The row
  blocks any new refund on the payment until reconcile (Task 9) settles it by inquiry.
  Never retry blindly (spec §6).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from lemely.db.admin_billing_repo import (
    AdminConflictError,
    AdminInvalidError,
    AdminNotFoundError,
    AuditAction,
    AuditTarget,
    PaymentView,
    audited,
    payment_views,
    require_reason,
    to_jsonable,
)
from lemely.db.models.billing import Payment, PaymentPurpose, PaymentStatus
from lemely.db.models.billing_ops import PaymentRefund, RefundKind, RefundStatus
from lemely.db.models.usage import UsageGrant
from lemely.db.usage_ledger_repo import UsageLedger
from lemely.io.paymob.client import PaymobError

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker

    from lemely.io.paymob.client import PaymobClient
    from lemely.runtime.config import PaymobSettings

_REFUNDABLE = frozenset({PaymentStatus.paid, PaymentStatus.partially_refunded})
_IN_FLIGHT = frozenset({RefundStatus.requested, RefundStatus.unknown})
_CLAWBACK_PURPOSES = frozenset({PaymentPurpose.credit_pack, PaymentPurpose.auto_topup})
_CLOSE_ACTIONS = {
    RefundStatus.succeeded: AuditAction.PAYMENT_REFUND_SUCCEEDED,
    RefundStatus.failed: AuditAction.PAYMENT_REFUND_FAILED,
    RefundStatus.unknown: AuditAction.PAYMENT_REFUND_UNKNOWN,
}


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _outcome_of(exc: Exception) -> RefundStatus:
    """A Paymob refusal (4xx) is final; anything else may have reached Paymob."""
    if isinstance(exc, PaymobError) and not exc.timeout and exc.status_code is not None:
        return RefundStatus.failed if exc.status_code < 500 else RefundStatus.unknown
    return RefundStatus.unknown


class AdminPaymentsService:
    """Refund, void (this task), list, problem queue and reconcile (Task 9)."""

    def __init__(
        self,
        sessionmaker: sessionmaker[Session],
        client: PaymobClient,
        paymob_settings: PaymobSettings,
        *,
        now: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._sm = sessionmaker
        self._client = client
        self._settings = paymob_settings
        self._now = now

    def payment_view(self, payment_id: uuid.UUID) -> PaymentView:
        with self._sm() as s:
            payment = s.get(Payment, payment_id)
            if payment is None:
                raise AdminNotFoundError("payment_not_found")
            return payment_views(s, [payment])[0]

    # -- refund and void ---------------------------------------------------------

    def refund(
        self,
        payment_id: uuid.UUID,
        *,
        amount_minor: int | None,
        admin_user_id: uuid.UUID,
        reason: str,
    ) -> PaymentView:
        """Refund ``amount_minor`` (``None`` = everything not yet refunded)."""
        return self._run(payment_id, RefundKind.refund, amount_minor, admin_user_id, reason)

    def void(self, payment_id: uuid.UUID, *, admin_user_id: uuid.UUID, reason: str) -> PaymentView:
        """Void a paid, never-refunded payment (Paymob allows it until settlement)."""
        return self._run(payment_id, RefundKind.void, None, admin_user_id, reason)

    def _run(
        self,
        payment_id: uuid.UUID,
        kind: RefundKind,
        amount_minor: int | None,
        admin_user_id: uuid.UUID,
        reason: str,
    ) -> PaymentView:
        require_reason(reason)
        refund_id, txn_id, amount = self._open_refund(
            payment_id, kind=kind, amount_minor=amount_minor, admin_user_id=admin_user_id, reason=reason
        )
        try:
            if kind is RefundKind.void:
                response: Mapping[str, Any] = self._client.void(transaction_id=txn_id)
            else:
                response = self._client.refund(transaction_id=txn_id, amount_cents=amount)
        except Exception as exc:  # noqa: BLE001 - every failure is recorded, none is retried
            outcome = _outcome_of(exc)
            detail: dict[str, Any] = {"error": str(exc)}
            if isinstance(exc, PaymobError):
                detail |= {"status_code": exc.status_code, "timeout": exc.timeout}
            self._close_refund(
                refund_id, outcome=outcome, response=detail, admin_user_id=admin_user_id, reason=reason
            )
        else:
            outcome = RefundStatus.succeeded if response.get("success") is True else RefundStatus.failed
            self._close_refund(
                refund_id, outcome=outcome, response=dict(response),
                admin_user_id=admin_user_id, reason=reason,
            )
        return self.payment_view(payment_id)

    def _open_refund(
        self,
        payment_id: uuid.UUID,
        *,
        kind: RefundKind,
        amount_minor: int | None,
        admin_user_id: uuid.UUID,
        reason: str,
    ) -> tuple[uuid.UUID, int, int]:
        """Validate, insert the ``requested`` row and its audit row; commit. Returns (id, txn, amount)."""
        with self._sm.begin() as s:
            payment = s.get(Payment, payment_id, with_for_update=True)
            if payment is None:
                raise AdminNotFoundError("payment_not_found")
            refunds = list(s.scalars(select(PaymentRefund).where(PaymentRefund.payment_id == payment.id)))
            if any(r.status in _IN_FLIGHT for r in refunds):
                raise AdminConflictError(
                    "refund_in_flight", "A refund is still unresolved; reconcile the payment first."
                )
            refunded = sum(r.amount_minor for r in refunds if r.status is RefundStatus.succeeded)
            if kind is RefundKind.void:
                if payment.status is not PaymentStatus.paid or refunded:
                    raise AdminConflictError("not_voidable", "Only a paid, unrefunded payment voids.")
                amount = payment.amount_minor
            else:
                if payment.status not in _REFUNDABLE:
                    raise AdminConflictError("not_refundable", "Only paid payments refund.")
                remaining = payment.amount_minor - refunded
                amount = remaining if amount_minor is None else amount_minor
                if amount <= 0 or amount > remaining:
                    raise AdminInvalidError(
                        "refund_amount_out_of_range", f"Refund between 1 and {remaining} piasters."
                    )
            if payment.paymob_txn_id is None:
                raise AdminConflictError("no_paymob_transaction", "Paymob never charged this payment.")
            row = PaymentRefund(
                payment_id=payment.id,
                admin_user_id=admin_user_id,
                kind=kind,
                status=RefundStatus.requested,
                amount_minor=amount,
                reason=reason.strip(),
            )
            s.add(row)
            s.flush()
            audited(
                s,
                admin_user_id,
                AuditAction.PAYMENT_VOID_REQUESTED if kind is RefundKind.void else AuditAction.PAYMENT_REFUND_REQUESTED,
                AuditTarget.PAYMENT,
                payment.id,
                reason,
                {"status": payment.status, "refunded_minor": refunded},
                {"refund_id": row.id, "kind": kind, "amount_minor": amount},
            )
            return row.id, int(payment.paymob_txn_id), amount

    def _close_refund(
        self,
        refund_id: uuid.UUID,
        *,
        outcome: RefundStatus,
        response: Mapping[str, Any],
        admin_user_id: uuid.UUID,
        reason: str,
    ) -> None:
        """Record Paymob's answer (payment locked first, then the refund row) and audit it."""
        with self._sm.begin() as s:
            payment_id = s.scalar(select(PaymentRefund.payment_id).where(PaymentRefund.id == refund_id))
            payment = s.get(Payment, payment_id, with_for_update=True)
            refund = s.get(PaymentRefund, refund_id, with_for_update=True)
            assert payment is not None and refund is not None  # noqa: S101 - rows written by _open_refund
            before = {"status": payment.status, "refund_status": refund.status}
            refund.status = outcome
            refund.paymob_response = to_jsonable(response)  # type: ignore[assignment]
            s.flush()
            if outcome is RefundStatus.succeeded:
                self._apply_success(s, payment, refund)
            audited(
                s, admin_user_id, _CLOSE_ACTIONS[outcome], AuditTarget.PAYMENT, payment.id, reason,
                before,
                {
                    "status": payment.status,
                    "refund_id": refund.id,
                    "refund_status": refund.status,
                    "clawed_back_units": refund.clawed_back_units,
                },
            )

    def _apply_success(self, s: Session, payment: Payment, refund: PaymentRefund) -> None:
        if refund.kind is RefundKind.void:
            payment.status = PaymentStatus.voided
            full = True
        else:
            refunded = sum(
                s.scalars(
                    select(PaymentRefund.amount_minor).where(
                        PaymentRefund.payment_id == payment.id,
                        PaymentRefund.status == RefundStatus.succeeded,
                        PaymentRefund.kind == RefundKind.refund,
                    )
                )
            )
            full = refunded >= payment.amount_minor
            payment.status = PaymentStatus.refunded if full else PaymentStatus.partially_refunded
        if full and payment.purpose in _CLAWBACK_PURPOSES:
            ledger = UsageLedger(s)
            grant_ids = s.scalars(
                select(UsageGrant.id).where(UsageGrant.payment_id == payment.id).order_by(UsageGrant.created_at)
            ).all()
            refund.clawed_back_units = sum(
                ledger.claw_back_grant(gid, reason=f"refund {refund.id}", now=self._now())
                for gid in grant_ids
            )
        s.flush()


__all__ = ["AdminPaymentsService"]
```

- [ ] **Step 5: Add the dependency, DTO and routes**

In `lemely/web/deps_admin_billing.py` add (and export):

```python
from lemely.db.admin_payments_repo import AdminPaymentsService


def get_admin_payments_service() -> AdminPaymentsService:
    settings = get_settings()
    return AdminPaymentsService(get_sessionmaker(settings), get_paymob_client(), settings.paymob)
```

Append to `lemely/web/schemas_admin_billing.py`:

```python
class AdminRefundRequestDTO(ApiModel):
    amountMinor: Positive | None = None
    reason: Reason
```

Append to `lemely/web/routers/admin_billing.py` (import `AdminPaymentsService`,
`get_admin_payments_service`, `AdminRefundRequestDTO`):

```python
PaymentsService = Annotated[AdminPaymentsService, Depends(get_admin_payments_service)]


# -- payments: money actions ----------------------------------------------------


@router.post("/payments/{payment_id}/refund", response_model=AdminPaymentRowDTO)
def refund_payment(
    payment_id: uuid.UUID, body: AdminRefundRequestDTO, service: PaymentsService, auth: AdminAuth
) -> AdminPaymentRowDTO:
    with mapped_errors():
        view = service.refund(
            payment_id, amount_minor=body.amountMinor, admin_user_id=admin_id(auth), reason=body.reason
        )
    return payment_row_dto(view)


@router.post("/payments/{payment_id}/void", response_model=AdminPaymentRowDTO)
def void_payment(
    payment_id: uuid.UUID, body: ReasonDTO, service: PaymentsService, auth: AdminAuth
) -> AdminPaymentRowDTO:
    with mapped_errors():
        view = service.void(payment_id, admin_user_id=admin_id(auth), reason=body.reason)
    return payment_row_dto(view)
```

- [ ] **Step 6: Register the routes**

Matrix (+2 to the `PLATFORM_ADMIN` heading):

```python
    ("POST", "/api/admin/billing/payments/{payment_id}/refund"): PLATFORM_ADMIN,
    ("POST", "/api/admin/billing/payments/{payment_id}/void"): PLATFORM_ADMIN,
```

`PLANNED`:

```python
    ("POST", f"{P}/payments/{{payment_id}}/refund"),
    ("POST", f"{P}/payments/{{payment_id}}/void"),
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest --no-cov tests/test_admin_billing_refunds.py tests/test_admin_billing_authz.py tests/test_authz_matrix_complete.py tests/architecture -v`
Expected: all pass, no skips.

- [ ] **Step 8: Commit**

```bash
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files
P="lemely/db/admin_payments_repo.py lemely/web/deps_admin_billing.py lemely/web/schemas_admin_billing.py lemely/web/routers/admin_billing.py tests/admin_billing_db.py tests/test_authz_matrix_complete.py tests/test_admin_billing_authz.py tests/test_admin_billing_refunds.py"
git add $P
git commit -S -m "feat(admin): audited refund and void with row-before-call and pack clawback" -- $P
```

---

### Task 9: Payments list, problem queue and manual reconcile

**Files:**
- Modify: `lemely/db/admin_payments_repo.py`
- Modify: `lemely/web/schemas_admin_billing.py`, `lemely/web/routers/admin_billing.py`
- Modify: `tests/test_authz_matrix_complete.py`, `tests/test_admin_billing_authz.py`
- Create: `tests/test_admin_billing_payments.py`

**Interfaces:**
- Consumes: `AdminPaymentsService._close_refund`, `payment_view` (Task 8); `PaymobWebhookFailure`, `Payment.callback_received_at` (Task 1); `BillingService.reconcile_payment_now` (Task 2); `encode_cursor`, `decode_cursor`, `CursorError` (`lemely.core.keyset`); `PaymobClient.inquire_by_transaction` (Phase 02).
- Produces:
  - `PaymentPage(items: list[PaymentView], next_cursor: str | None)`, `ProblemQueue(mismatches, stale_pending, missing_callbacks: list[PaymentView], hmac_failures: list[PaymobWebhookFailure], hmac_failures_24h: int, refunds_needing_attention: list[PaymentRefund])`.
  - `AdminPaymentsService.list_payments(*, status, purpose, user_id, start, end, cursor, limit) -> PaymentPage`, `.problems() -> ProblemQueue`, `.reconcile(payment_id, *, admin_user_id, reason) -> PaymentView`.
  - DTOs `AdminPaymentsPageDTO`, `WebhookFailureDTO`, `ProblemQueueDTO`.
  - Routes: `GET /payments`, `GET /problems`, `POST /payments/{payment_id}/reconcile`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_admin_billing_payments.py`:

```python
"""Payments list, problem queue and manual reconcile (spec §8 area 3)."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest

from lemely.db.admin_billing_repo import AuditAction
from lemely.db.billing_observability_repo import record_webhook_failure
from lemely.db.billing_repo import BillingService
from lemely.db.models.billing import Payment, PaymentPurpose, PaymentStatus
from lemely.db.models.billing_ops import PaymentRefund, PaymobWebhookFailure, RefundKind, RefundStatus
from lemely.db.models.enums import Role
from lemely.io.paymob.client import PaymobError
from tests.admin_billing_db import (
    NOW,
    FakePaymobClient,
    add_payment,
    add_user,
    admin_client,
    audit_rows,
    billing_database,
    emptied_after,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture(scope="module")
def billing_db() -> Iterator[sessionmaker[Session]]:
    with billing_database() as factory:
        yield factory


@pytest.fixture
def sm(billing_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(billing_db)


@pytest.fixture
def admin(sm: sessionmaker[Session]) -> uuid.UUID:
    return add_user(sm, Role.platform_admin)


def test_the_list_filters_and_pages_newest_first(sm: sessionmaker[Session], admin: uuid.UUID) -> None:
    student = add_user(sm, Role.student)
    other = add_user(sm, Role.student)
    ids = [
        add_payment(sm, payer=student, created_at=NOW - timedelta(minutes=m)) for m in (1, 2, 3)
    ]
    add_payment(sm, payer=student, status=PaymentStatus.failed, created_at=NOW - timedelta(minutes=4))
    add_payment(sm, payer=other, created_at=NOW - timedelta(minutes=5))
    client = admin_client(sm, admin)

    page1 = client.get(
        "/api/admin/billing/payments", params={"status": "paid", "userId": str(student), "limit": 2}
    ).json()
    page2 = client.get(
        "/api/admin/billing/payments",
        params={"status": "paid", "userId": str(student), "limit": 2, "cursor": page1["nextCursor"]},
    ).json()

    assert [p["id"] for p in page1["items"]] == [str(ids[0]), str(ids[1])]
    assert [p["id"] for p in page2["items"]] == [str(ids[2])]
    assert page2["nextCursor"] is None
    by_purpose = client.get("/api/admin/billing/payments", params={"purpose": "auto_topup"}).json()
    assert by_purpose["items"] == []


def test_a_tampered_cursor_is_422(sm: sessionmaker[Session], admin: uuid.UUID) -> None:
    resp = admin_client(sm, admin).get("/api/admin/billing/payments", params={"cursor": "not-a-cursor"})
    assert resp.status_code == 422


def test_the_problem_queue_finds_each_kind_of_problem(sm: sessionmaker[Session], admin: uuid.UUID) -> None:
    student = add_user(sm, Role.student)
    mismatch = add_payment(sm, payer=student, status=PaymentStatus.failed_mismatch, paymob_txn_id=11)
    stale = add_payment(sm, payer=student, status=PaymentStatus.pending, created_at=NOW - timedelta(hours=2))
    add_payment(sm, payer=student, status=PaymentStatus.pending, created_at=NOW - timedelta(minutes=30))
    missing = add_payment(sm, payer=student, paid_at=NOW - timedelta(hours=1), paymob_txn_id=12)
    heard = add_payment(sm, payer=student, paid_at=NOW - timedelta(hours=1), paymob_txn_id=13)
    add_payment(
        sm, payer=student, purpose=PaymentPurpose.subscription_renewal,
        paid_at=NOW - timedelta(hours=1), paymob_txn_id=14,
    )
    add_payment(sm, payer=student, paid_at=NOW - timedelta(minutes=5), paymob_txn_id=15)
    stuck = uuid.uuid4()
    with sm.begin() as session:
        session.get(Payment, heard).callback_received_at = NOW - timedelta(hours=1)
        session.add(
            PaymentRefund(
                id=stuck, payment_id=heard, admin_user_id=admin, kind=RefundKind.refund,
                status=RefundStatus.unknown, amount_minor=100, reason="timed out",
                created_at=NOW - timedelta(minutes=20), updated_at=NOW - timedelta(minutes=20),
            )
        )
    record_webhook_failure(sm, kind="transaction", reason="hmac_mismatch", payload={"obj": {}}, remote_addr=None)
    with sm.begin() as session:
        for row in session.query(PaymobWebhookFailure):
            row.received_at = NOW - timedelta(hours=3)

    body = admin_client(sm, admin).get("/api/admin/billing/problems").json()

    assert [p["id"] for p in body["mismatches"]] == [str(mismatch)]
    assert [p["id"] for p in body["stalePending"]] == [str(stale)]
    assert [p["id"] for p in body["missingCallbacks"]] == [str(missing)]
    assert [f["kind"] for f in body["hmacFailures"]] == ["transaction"]
    assert body["hmacFailures24h"] == 1
    assert [r["id"] for r in body["refundsNeedingAttention"]] == [str(stuck)]


def test_reconcile_runs_phase_02_inquiry_for_one_payment_and_is_audited(
    sm: sessionmaker[Session], admin: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    student = add_user(sm, Role.student)
    payment = add_payment(sm, payer=student, status=PaymentStatus.pending, created_at=NOW - timedelta(hours=2))
    seen: list[uuid.UUID] = []

    def fake_now(self: BillingService, payment_id: uuid.UUID, *, now: object) -> PaymentStatus:
        seen.append(payment_id)
        row = self._session.get(Payment, payment_id)
        row.status = PaymentStatus.paid
        return row.status

    monkeypatch.setattr(BillingService, "reconcile_payment_now", fake_now)
    resp = admin_client(sm, admin).post(
        f"/api/admin/billing/payments/{payment}/reconcile", json={"reason": "customer says paid"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "paid"
    assert seen == [payment]
    [row] = audit_rows(sm, AuditAction.PAYMENT_RECONCILE)
    assert (row.before["status"], row.after["status"]) == ("pending", "paid")


def test_reconcile_settles_an_unknown_refund_by_inquiry(sm: sessionmaker[Session], admin: uuid.UUID) -> None:
    student = add_user(sm, Role.student)
    payment = add_payment(sm, payer=student, paymob_txn_id=888001)
    paymob = FakePaymobClient(refund_result=PaymobError("timed out", timeout=True))
    client = admin_client(sm, admin, paymob=paymob)
    first = client.post(f"/api/admin/billing/payments/{payment}/refund", json={"amountMinor": 4000, "reason": "goodwill"})
    assert first.json()["refunds"][0]["status"] == "unknown"

    paymob.inquiry_result = {"id": 888001, "is_refunded": True, "refunded_amount_cents": 4000}
    resp = client.post(f"/api/admin/billing/payments/{payment}/reconcile", json={"reason": "check refund"})

    assert resp.json()["status"] == "partially_refunded"
    assert resp.json()["refunds"][0]["status"] == "succeeded"
    assert ("inquire_by_transaction", {"transaction_id": 888001}) in paymob.calls
    assert len(audit_rows(sm, AuditAction.PAYMENT_REFUND_SUCCEEDED)) == 1


def test_reconcile_of_an_unknown_payment_is_404(sm: sessionmaker[Session], admin: uuid.UUID) -> None:
    resp = admin_client(sm, admin).post(
        f"/api/admin/billing/payments/{uuid.uuid4()}/reconcile", json={"reason": "who"}
    )
    assert resp.status_code == 404
```


- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest --no-cov tests/test_admin_billing_payments.py -v`
Expected: FAIL — 404/405 on the three new routes.

- [ ] **Step 3: Add list, problems and reconcile to the service**

Append to `lemely/db/admin_payments_repo.py` (merge imports: `from dataclasses import dataclass`,
`from datetime import timedelta`, `import sqlalchemy as sa`, `from sqlalchemy import or_`,
`from lemely.core.keyset import decode_cursor, encode_cursor`, `from lemely.db.billing_repo import BillingService`,
`PaymobWebhookFailure` from `billing_ops`, `PaymobCallError`):

```python
_PAYMENTS_CURSOR = "admin.billing.payments"
STALE_PENDING_AFTER = timedelta(hours=1)
CALLBACK_GRACE = timedelta(minutes=15)
HMAC_WINDOW = timedelta(days=7)
REFUND_STUCK_AFTER = timedelta(minutes=10)
_QUEUE_LIMIT = 100


@dataclass(frozen=True, slots=True)
class PaymentPage:
    items: list[PaymentView]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class ProblemQueue:
    mismatches: list[PaymentView]
    stale_pending: list[PaymentView]
    missing_callbacks: list[PaymentView]
    hmac_failures: list[PaymobWebhookFailure]
    hmac_failures_24h: int
    refunds_needing_attention: list[PaymentRefund]
```

and to `AdminPaymentsService`:

```python
    # -- list, problems, reconcile (Task 9) --------------------------------------

    def list_payments(
        self,
        *,
        status: PaymentStatus | None,
        purpose: PaymentPurpose | None,
        user_id: uuid.UUID | None,
        start: datetime | None,
        end: datetime | None,
        cursor: str | None,
        limit: int,
    ) -> PaymentPage:
        """Newest first, keyset-paged on ``(created_at, id)``. Raises ``CursorError``."""
        stmt = select(Payment)
        if status is not None:
            stmt = stmt.where(Payment.status == status)
        if purpose is not None:
            stmt = stmt.where(Payment.purpose == purpose)
        if user_id is not None:
            stmt = stmt.where(or_(Payment.payer_user_id == user_id, Payment.beneficiary_user_id == user_id))
        if start is not None:
            stmt = stmt.where(Payment.created_at >= start)
        if end is not None:
            stmt = stmt.where(Payment.created_at < end)
        if cursor is not None:
            created, pid = decode_cursor(cursor, endpoint=_PAYMENTS_CURSOR, types=(datetime, uuid.UUID))
            stmt = stmt.where(sa.tuple_(Payment.created_at, Payment.id) < sa.tuple_(created, pid))
        with self._sm() as s:
            rows = list(
                s.scalars(stmt.order_by(Payment.created_at.desc(), Payment.id.desc()).limit(limit + 1))
            )
            page, more = rows[:limit], len(rows) > limit
            next_cursor = (
                encode_cursor(_PAYMENTS_CURSOR, [page[-1].created_at, page[-1].id]) if more else None
            )
            return PaymentPage(items=payment_views(s, page), next_cursor=next_cursor)

    def problems(self) -> ProblemQueue:
        """Everything an admin should look at today (spec §8 area 3)."""
        now = self._now()
        with self._sm() as s:

            def views(stmt: sa.Select[tuple[Payment]]) -> list[PaymentView]:
                return payment_views(s, list(s.scalars(stmt.limit(_QUEUE_LIMIT))))

            mismatches = views(
                select(Payment)
                .where(Payment.status == PaymentStatus.failed_mismatch)
                .order_by(Payment.created_at.desc())
            )
            stale = views(
                select(Payment)
                .where(
                    Payment.status.in_((PaymentStatus.created, PaymentStatus.pending)),
                    Payment.created_at < now - STALE_PENDING_AFTER,
                )
                .order_by(Payment.created_at)
            )
            # Renewals are charged by Paymob's scheduler and reported on the subscription
            # webhook, so they never get a transaction callback of their own.
            missing = views(
                select(Payment)
                .where(
                    Payment.status == PaymentStatus.paid,
                    Payment.purpose != PaymentPurpose.subscription_renewal,
                    Payment.paid_at < now - CALLBACK_GRACE,
                    Payment.callback_received_at.is_(None),
                )
                .order_by(Payment.paid_at.desc())
            )
            failures = list(
                s.scalars(
                    select(PaymobWebhookFailure)
                    .where(PaymobWebhookFailure.received_at >= now - HMAC_WINDOW)
                    .order_by(PaymobWebhookFailure.received_at.desc())
                    .limit(_QUEUE_LIMIT)
                )
            )
            failures_24h = int(
                s.scalar(
                    select(sa.func.count())
                    .select_from(PaymobWebhookFailure)
                    .where(PaymobWebhookFailure.received_at >= now - timedelta(hours=24))
                )
                or 0
            )
            stuck = list(
                s.scalars(
                    select(PaymentRefund)
                    .where(
                        PaymentRefund.status.in_(tuple(_IN_FLIGHT)),
                        PaymentRefund.created_at < now - REFUND_STUCK_AFTER,
                    )
                    .order_by(PaymentRefund.created_at)
                    .limit(_QUEUE_LIMIT)
                )
            )
            return ProblemQueue(mismatches, stale, missing, failures, failures_24h, stuck)

    def reconcile(self, payment_id: uuid.UUID, *, admin_user_id: uuid.UUID, reason: str) -> PaymentView:
        """Inquire Paymob for one payment now, then settle any ``unknown`` refund by inquiry."""
        require_reason(reason)
        with self._sm.begin() as s:
            payment = s.get(Payment, payment_id)
            if payment is None:
                raise AdminNotFoundError("payment_not_found")
            before = payment.status
            status = BillingService(s, self._client, self._settings).reconcile_payment_now(
                payment_id, now=self._now()
            )
            audited(
                s, admin_user_id, AuditAction.PAYMENT_RECONCILE, AuditTarget.PAYMENT, payment_id,
                reason, {"status": before}, {"status": status},
            )
        self._resolve_unknown_refunds(payment_id, admin_user_id=admin_user_id, reason=reason)
        return self.payment_view(payment_id)

    def _resolve_unknown_refunds(
        self, payment_id: uuid.UUID, *, admin_user_id: uuid.UUID, reason: str
    ) -> int:
        """Settle ``unknown`` refunds from Paymob's view of the transaction. Returns how many."""
        with self._sm() as s:
            payment = s.get(Payment, payment_id)
            unknown = list(
                s.scalars(
                    select(PaymentRefund)
                    .where(
                        PaymentRefund.payment_id == payment_id,
                        PaymentRefund.status == RefundStatus.unknown,
                    )
                    .order_by(PaymentRefund.created_at)
                )
            )
            refunded = sum(
                s.scalars(
                    select(PaymentRefund.amount_minor).where(
                        PaymentRefund.payment_id == payment_id,
                        PaymentRefund.status == RefundStatus.succeeded,
                        PaymentRefund.kind == RefundKind.refund,
                    )
                )
            )
            txn = payment.paymob_txn_id if payment is not None else None
        if not unknown or txn is None:
            return 0
        try:
            obj: Mapping[str, Any] = self._client.inquire_by_transaction(int(txn)) or {}
        except PaymobError as exc:
            raise PaymobCallError("paymob_inquiry_failed", str(exc)) from exc
        for refund in unknown:
            if refund.kind is RefundKind.void:
                done = obj.get("is_voided") is True
            else:
                done = int(obj.get("refunded_amount_cents") or 0) >= refunded + refund.amount_minor
            self._close_refund(
                refund.id,
                outcome=RefundStatus.succeeded if done else RefundStatus.failed,
                response={"inquiry": dict(obj)},
                admin_user_id=admin_user_id,
                reason=reason,
            )
            if done and refund.kind is RefundKind.refund:
                refunded += refund.amount_minor
        return len(unknown)
```

Add `"PaymentPage"`, `"ProblemQueue"` and the four threshold constants to `__all__`.

- [ ] **Step 4: Add the DTOs and routes**

Append to `lemely/web/schemas_admin_billing.py`:

```python
# -- payments -------------------------------------------------------------------


class AdminPaymentsPageDTO(ApiModel):
    items: list[AdminPaymentRowDTO]
    nextCursor: str | None


class WebhookFailureDTO(ApiModel):
    id: str
    kind: Literal["transaction", "token", "subscription"]
    reason: str
    remoteAddr: str | None
    receivedAt: datetime


class ProblemQueueDTO(ApiModel):
    mismatches: list[AdminPaymentRowDTO]
    stalePending: list[AdminPaymentRowDTO]
    missingCallbacks: list[AdminPaymentRowDTO]
    hmacFailures: list[WebhookFailureDTO]
    hmacFailures24h: int
    refundsNeedingAttention: list[RefundDTO]
```

Append to `lemely/web/routers/admin_billing.py` (imports: `datetime`, `CursorError` from
`lemely.core.keyset`, `PaymentPurpose`, `PaymentStatus`, the three DTOs):

```python
# -- area 3: payments -------------------------------------------------------------


@router.get("/payments", response_model=AdminPaymentsPageDTO)
def list_payments(
    service: PaymentsService,
    status: PaymentStatus | None = None,
    purpose: PaymentPurpose | None = None,
    userId: uuid.UUID | None = None,  # noqa: N803 - camelCase on the wire, like the DTOs
    start: Annotated[datetime | None, Query(alias="from")] = None,
    end: Annotated[datetime | None, Query(alias="to")] = None,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> AdminPaymentsPageDTO:
    try:
        page = service.list_payments(
            status=status, purpose=purpose, user_id=userId, start=start, end=end,
            cursor=cursor, limit=limit,
        )
    except CursorError as exc:
        raise HTTPException(status_code=422, detail={"code": "bad_cursor", "message": str(exc)}) from exc
    return AdminPaymentsPageDTO(items=[payment_row_dto(v) for v in page.items], nextCursor=page.next_cursor)


@router.get("/problems", response_model=ProblemQueueDTO)
def problem_queue(service: PaymentsService) -> ProblemQueueDTO:
    q = service.problems()
    return ProblemQueueDTO(
        mismatches=[payment_row_dto(v) for v in q.mismatches],
        stalePending=[payment_row_dto(v) for v in q.stale_pending],
        missingCallbacks=[payment_row_dto(v) for v in q.missing_callbacks],
        hmacFailures=[
            WebhookFailureDTO(
                id=str(f.id), kind=f.kind, reason=f.reason, remoteAddr=f.remote_addr,  # type: ignore[arg-type]
                receivedAt=f.received_at,
            )
            for f in q.hmac_failures
        ],
        hmacFailures24h=q.hmac_failures_24h,
        refundsNeedingAttention=[refund_dto(r) for r in q.refunds_needing_attention],
    )


@router.post("/payments/{payment_id}/reconcile", response_model=AdminPaymentRowDTO)
def reconcile_payment(
    payment_id: uuid.UUID, body: ReasonDTO, service: PaymentsService, auth: AdminAuth
) -> AdminPaymentRowDTO:
    with mapped_errors():
        view = service.reconcile(payment_id, admin_user_id=admin_id(auth), reason=body.reason)
    return payment_row_dto(view)
```

- [ ] **Step 5: Register the routes**

Matrix (+3 to the `PLATFORM_ADMIN` heading):

```python
    ("GET", "/api/admin/billing/payments"): PLATFORM_ADMIN,
    ("GET", "/api/admin/billing/problems"): PLATFORM_ADMIN,
    ("POST", "/api/admin/billing/payments/{payment_id}/reconcile"): PLATFORM_ADMIN,
```

`PLANNED`:

```python
    ("GET", f"{P}/payments"),
    ("GET", f"{P}/problems"),
    ("POST", f"{P}/payments/{{payment_id}}/reconcile"),
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest --no-cov tests/test_admin_billing_payments.py tests/test_admin_billing_refunds.py tests/test_admin_billing_authz.py tests/test_authz_matrix_complete.py -v`
Expected: all pass, no skips.

- [ ] **Step 7: Commit**

```bash
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files
P="lemely/db/admin_payments_repo.py lemely/web/schemas_admin_billing.py lemely/web/routers/admin_billing.py tests/test_authz_matrix_complete.py tests/test_admin_billing_authz.py tests/test_admin_billing_payments.py"
git add $P
git commit -S -m "feat(admin): payments list, problem queue and audited manual reconcile" -- $P
```

### Task 10: Money and margin report

**Files:**
- Create: `lemely/db/admin_margin_repo.py`
- Modify: `lemely/web/deps_admin_billing.py`, `lemely/web/schemas_admin_billing.py`, `lemely/web/routers/admin_billing.py`
- Modify: `tests/admin_billing_db.py` (margin service override)
- Modify: `tests/test_authz_matrix_complete.py`, `tests/test_admin_billing_authz.py`
- Create: `tests/test_admin_billing_margin.py`

**Interfaces:**
- Consumes: `UsageJobModelCost`, `PaymentRefund` and the five admin indexes (Task 1); `payments`, `plan_tiers`, `subscriptions`, `subscription_periods` (Phases 02/05); `usage_jobs`, `usage_rates`, `usage_grants`, `usage_grant_balances`, `usage_entries`, `usage_debts` (Phase 01); seeds `add_payment`, `add_subscription`, `grant`, `metered_job`, `add_rate`, `add_credit_pack` (Tasks 4–5).
- Produces:
  - `RECURRING_PURPOSES`, `PACK_PURPOSES`, `CostRow(key, jobs, cost_usd)`, `RevenueReport`, `CostReport`, `AccuracyRow`, `Debtor`, `ExposureReport`, `MarginReport`, `AdminMarginService(sessionmaker, *, now=...)` with `margin(start, end, *, egp_per_usd: Decimal | None) -> MarginReport`.
  - `get_admin_margin_service()`; DTO `MarginReportDTO` and parts.
  - Route: `GET /margin?from=&to=&egpPerUsd=`.

- [ ] **Step 1: Extend the test helpers**

In `tests/admin_billing_db.py` import `AdminMarginService` and `get_admin_margin_service`, and add
to `service_overrides`:

```python
        get_admin_margin_service: lambda: AdminMarginService(factory, now=clock),
```

- [ ] **Step 2: Write the failing tests with exact numbers**

Create `tests/test_admin_billing_margin.py`:

```python
"""Money and margin (spec §8 area 4): every figure asserted exactly against seeded rows."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa

from lemely.core.usage_types import GrantScope, Payer
from lemely.db.models.billing import PaymentPurpose, PaymentStatus
from lemely.db.models.billing_ops import PaymentRefund, RefundKind, RefundStatus, UsageJobModelCost
from lemely.db.models.enums import Role
from lemely.db.models.usage import GrantKind, UsageJob
from lemely.db.usage_ledger_repo import UsageLedger
from tests.admin_billing_db import (
    NOW,
    add_credit_pack,
    add_payment,
    add_plan_tier,
    add_rate,
    add_subscription,
    add_user,
    admin_client,
    billing_database,
    emptied_after,
    grant,
    metered_job,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker

NOV_1 = datetime(2026, 11, 1, tzinfo=UTC)
DEC_1 = datetime(2026, 12, 1, tzinfo=UTC)
WINDOW = {"from": NOV_1.isoformat(), "to": DEC_1.isoformat()}
EARLY = datetime(2026, 10, 1, tzinfo=UTC)


@pytest.fixture(scope="module")
def billing_db() -> Iterator[sessionmaker[Session]]:
    with billing_database() as factory:
        yield factory


@pytest.fixture
def sm(billing_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(billing_db)


@pytest.fixture
def admin(sm: sessionmaker[Session]) -> uuid.UUID:
    return add_user(sm, Role.platform_admin)


def _model_costs(sm: sessionmaker[Session], job: uuid.UUID, costs: dict[str, str]) -> None:
    with sm.begin() as session:
        for model, usd in costs.items():
            session.add(UsageJobModelCost(usage_job_id=job, model=model, cost_usd=Decimal(usd)))


def _seed_margin_world(sm: sessionmaker[Session]) -> None:
    student = add_user(sm, Role.student)
    teacher = add_user(sm, Role.teacher)
    tier = add_plan_tier(sm, code="student_monthly", price_minor=20000)
    pack = add_credit_pack(sm)
    add_subscription(sm, student, tier, start=NOV_1, end=DEC_1)

    add_payment(sm, payer=student, purpose=PaymentPurpose.subscription_first, amount_minor=20000,
                paid_at=NOV_1 + timedelta(hours=10), plan_tier_id=tier)
    add_payment(sm, payer=student, amount_minor=10000, paid_at=NOV_1 + timedelta(days=1), credit_pack_id=pack)
    refunded = add_payment(sm, payer=teacher, amount_minor=10000, paid_at=NOV_1 + timedelta(days=2),
                           credit_pack_id=pack, paymob_txn_id=5)
    add_payment(sm, payer=student, status=PaymentStatus.failed, amount_minor=9999, credit_pack_id=pack)
    add_payment(sm, payer=student, purpose=PaymentPurpose.subscription_renewal, amount_minor=20000,
                paid_at=EARLY, plan_tier_id=tier)
    admin_id = add_user(sm, Role.platform_admin)
    with sm.begin() as session:
        moment = NOV_1 + timedelta(days=3)
        session.add(
            PaymentRefund(
                payment_id=refunded, admin_user_id=admin_id, kind=RefundKind.refund,
                status=RefundStatus.succeeded, amount_minor=4000, reason="goodwill",
                created_at=moment, updated_at=moment,
            )
        )

    for action in ("mark_paper", "regrade", "generate_quiz"):
        add_rate(sm, action)
    grant(sm, student, units=100, effective_at=EARLY)
    grant(sm, teacher, units=10, effective_at=EARLY)
    s_pay = [Payer(owner_user_id=student, scope=GrantScope.CREDITS)]
    t_pay = [Payer(owner_user_id=teacher, scope=GrantScope.CREDITS)]
    nov3, nov4 = NOV_1 + timedelta(days=2), NOV_1 + timedelta(days=3)

    outside = metered_job(sm, student, s_pay, low=3, high=5, cost=Decimal("0.009"),
                          created_at=datetime(2026, 10, 15, tzinfo=UTC))
    j1 = metered_job(sm, student, s_pay, low=3, high=5, cost=Decimal("0.004"), created_at=nov3)
    j2 = metered_job(sm, student, s_pay, low=3, high=5, cost=Decimal("0.007"), created_at=nov3)
    metered_job(sm, student, s_pay, action="regrade", low=1, high=2, cost=Decimal("0.0005"), created_at=nov4)
    metered_job(sm, teacher, t_pay, low=2, high=4, cost=Decimal("0.0021"), created_at=nov4)
    expired = metered_job(sm, teacher, t_pay, action="generate_quiz", low=1, high=2, cost=None, created_at=nov4)
    with sm.begin() as session:
        UsageLedger(session).expire_stale_jobs(now=nov4 + timedelta(hours=1))
    with sm.begin() as session:
        session.execute(
            sa.update(UsageJob).where(UsageJob.id == expired).values(actual_cost_usd=Decimal("0.0015"))
        )
    _model_costs(sm, outside, {"gemini-2.5-flash": "0.009"})
    _model_costs(sm, j1, {"gemini-2.5-flash": "0.003", "claude-haiku-4-5": "0.001"})
    _model_costs(sm, j2, {"gemini-2.5-flash": "0.007"})


def test_revenue_cost_margin_and_accuracy_are_exact(sm: sessionmaker[Session], admin: uuid.UUID) -> None:
    _seed_margin_world(sm)
    resp = admin_client(sm, admin).get("/api/admin/billing/margin", params={**WINDOW, "egpPerUsd": "50"})
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["revenue"] == {
        "recurringMinor": 20000,
        "packsMinor": 20000,
        "refundedMinor": 4000,
        "netMinor": 36000,
        "byPurpose": {"credit_pack": 20000, "subscription_first": 20000},
        "byPlan": [{"key": "student_monthly", "minor": 20000}],
    }
    assert body["cost"] == {
        "totalUsd": "0.015100",
        "byAction": [
            {"key": "generate_quiz", "jobs": 1, "costUsd": "0.001500"},
            {"key": "mark_paper", "jobs": 3, "costUsd": "0.013100"},
            {"key": "regrade", "jobs": 1, "costUsd": "0.000500"},
        ],
        "byPlan": [
            {"key": "student_monthly", "jobs": 3, "costUsd": "0.011500"},
            {"key": None, "jobs": 2, "costUsd": "0.003600"},
        ],
        "byModel": [
            {"model": "claude-haiku-4-5", "costUsd": "0.001000"},
            {"model": "gemini-2.5-flash", "costUsd": "0.010000"},
        ],
        "unattributedModelUsd": "0.004100",
    }
    # 0.0151 USD x 50 EGP x 100 piasters = 75.5 -> 76 (half up); 36000 - 76.
    assert (body["costMinor"], body["marginMinor"]) == (76, 35924)
    assert body["accuracy"] == [
        {
            "action": "mark_paper", "estimatorVersion": 1, "jobs": 3, "below": 0, "above": 1,
            "shareOutside": 0.3333, "meanOverrunUnits": 2.0, "maxOverrunUnits": 2,
        },
        {
            "action": "regrade", "estimatorVersion": 1, "jobs": 1, "below": 0, "above": 0,
            "shareOutside": 0.0, "meanOverrunUnits": None, "maxOverrunUnits": None,
        },
    ]
    assert body["exposure"]["expiredJobs"] == {"count": 1, "costUsd": "0.001500"}


def test_without_an_exchange_rate_there_is_no_margin_figure(
    sm: sessionmaker[Session], admin: uuid.UUID
) -> None:
    _seed_margin_world(sm)
    body = admin_client(sm, admin).get("/api/admin/billing/margin", params=WINDOW).json()
    assert (body["costMinor"], body["marginMinor"]) == (None, None)


def test_exposure_counts_debt_limits_and_expiring_credits(sm: sessionmaker[Session], admin: uuid.UUID) -> None:
    add_rate(sm, "mark_paper")
    debtor = add_user(sm, Role.student, email="debtor@example.com")
    grant(sm, debtor, units=5, effective_at=EARLY)
    metered_job(sm, debtor, [Payer(owner_user_id=debtor, scope=GrantScope.CREDITS)],
                low=1, high=5, cost=Decimal("0.008"))
    capped = add_user(sm, Role.student)
    grant(sm, capped, units=4, kind=GrantKind.period_allowance, visible=False,
          expires_at=NOW + timedelta(days=20), effective_at=EARLY)
    metered_job(sm, capped, [Payer(owner_user_id=capped, scope=GrantScope.ALLOWANCE)],
                low=1, high=4, cost=Decimal("0.004"))
    soon = add_user(sm, Role.student)
    grant(sm, soon, units=50, expires_at=NOW + timedelta(days=10))
    later = add_user(sm, Role.student)
    grant(sm, later, units=30, expires_at=NOW + timedelta(days=40))
    lapsed = add_user(sm, Role.student)
    grant(sm, lapsed, units=20, effective_at=EARLY, expires_at=NOW - timedelta(days=1))
    with sm.begin() as session:
        UsageLedger(session).expire_grants(now=NOW)

    body = admin_client(sm, admin).get("/api/admin/billing/margin", params=WINDOW).json()

    assert body["exposure"] == {
        "outstandingDebtUnits": 3,
        "debtors": 1,
        "topDebtors": [{"userId": str(debtor), "email": "debtor@example.com", "outstanding": 3}],
        "usersAtLimit": 1,
        "creditsExpiring30dUnits": 50,
        "creditsExpiring30dOwners": 1,
        "creditsExpiredUnusedUnits": 20,
        "expiredJobs": {"count": 0, "costUsd": "0.000000"},
    }


def test_a_reversed_or_huge_window_is_422(sm: sessionmaker[Session], admin: uuid.UUID) -> None:
    client = admin_client(sm, admin)
    reversed_window = client.get("/api/admin/billing/margin", params={"from": DEC_1.isoformat(), "to": NOV_1.isoformat()})
    huge = client.get(
        "/api/admin/billing/margin",
        params={"from": NOV_1.isoformat(), "to": (NOV_1 + timedelta(days=401)).isoformat()},
    )
    assert reversed_window.status_code == 422
    assert huge.status_code == 422
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest --no-cov tests/test_admin_billing_margin.py -v`
Expected: collection error, `No module named 'lemely.db.admin_margin_repo'`.

- [ ] **Step 4: Write the margin service**

Create `lemely/db/admin_margin_repo.py`:

```python
"""Money and margin (spec §8 area 4): aggregate SQL over payments and the usage ledger.

Every figure is one ``GROUP BY`` over indexed columns (migration 0057 adds the
indexes this module's ``WHERE`` clauses use). Windows are half-open ``[start, end)``.

Definitions, stated once so the screen and the tests agree:

* **Revenue** — payments ``paid``/``partially_refunded``/``refunded`` with ``paid_at`` in
  the window, gross; **refunded** — successful refunds recorded in the window. Voided
  payments never count. Net = gross − refunded.
* **LLM cost** — ``usage_jobs.actual_cost_usd`` of jobs created in the window, any status
  (an expired job's cost is real money spent).
* **Cost by plan** — the plan of the actor's subscription period covering the job's
  creation; jobs with none (credits-only users, teachers' assistants acting without a plan
  of their own) are the ``None`` row.
* **Cost by model** — ``usage_job_model_costs``; the remainder of the total is
  ``unattributed`` (jobs settled before per-model recording, or expired by crash).
* **Accuracy** — settled jobs only; actual units = ``ceil(actual_cost_usd × units_per_usd)``
  at the job's own rate version, compared with its own estimate range.
* **Margin** — needs an EGP-per-USD rate from the caller; without one it is ``None``
  rather than a number built on a guessed rate.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, Final

import sqlalchemy as sa

from lemely.db.admin_billing_repo import AdminInvalidError
from lemely.db.models.billing import PaymentPurpose

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker

RECURRING_PURPOSES: Final = frozenset(
    {
        PaymentPurpose.subscription_first,
        PaymentPurpose.subscription_renewal,
        PaymentPurpose.upgrade_proration,
        PaymentPurpose.extra_seats,
    }
)
PACK_PURPOSES: Final = frozenset({PaymentPurpose.credit_pack, PaymentPurpose.auto_topup})
_MAX_WINDOW = timedelta(days=400)
_EXPIRING_SOON = timedelta(days=30)
_TOP_DEBTORS = 20
_ZERO = Decimal("0")

_REVENUE_FILTER = (
    "p.paid_at >= :start AND p.paid_at < :end"
    " AND p.status::text IN ('paid', 'partially_refunded', 'refunded')"
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class CostRow:
    key: str | None
    jobs: int
    cost_usd: Decimal


@dataclass(frozen=True, slots=True)
class RevenueReport:
    recurring_minor: int
    packs_minor: int
    refunded_minor: int
    net_minor: int
    by_purpose: dict[str, int]
    by_plan: list[tuple[str, int]]


@dataclass(frozen=True, slots=True)
class CostReport:
    total_usd: Decimal
    by_action: list[CostRow]
    by_plan: list[CostRow]
    by_model: list[tuple[str, Decimal]]
    unattributed_model_usd: Decimal


@dataclass(frozen=True, slots=True)
class AccuracyRow:
    action: str
    estimator_version: int
    jobs: int
    below: int
    above: int
    share_outside: float
    mean_overrun_units: float | None
    max_overrun_units: int | None


@dataclass(frozen=True, slots=True)
class Debtor:
    user_id: uuid.UUID
    email: str
    outstanding: int


@dataclass(frozen=True, slots=True)
class ExposureReport:
    outstanding_debt_units: int
    debtors: int
    top_debtors: list[Debtor]
    users_at_limit: int
    credits_expiring_30d_units: int
    credits_expiring_30d_owners: int
    credits_expired_unused_units: int
    expired_jobs: int
    expired_jobs_cost_usd: Decimal


@dataclass(frozen=True, slots=True)
class MarginReport:
    start: datetime
    end: datetime
    revenue: RevenueReport
    cost: CostReport
    egp_per_usd: Decimal | None
    cost_minor: int | None
    margin_minor: int | None
    accuracy: list[AccuracyRow]
    exposure: ExposureReport


class AdminMarginService:
    def __init__(
        self, sessionmaker: sessionmaker[Session], *, now: Callable[[], datetime] = _utcnow
    ) -> None:
        self._sm = sessionmaker
        self._now = now

    def margin(self, start: datetime, end: datetime, *, egp_per_usd: Decimal | None) -> MarginReport:
        if end <= start or end - start > _MAX_WINDOW:
            raise AdminInvalidError("bad_window", "The window must run forwards, at most 400 days.")
        window = {"start": start, "end": end}
        with self._sm() as s:
            revenue = self._revenue(s, window)
            cost = self._cost(s, window)
            accuracy = self._accuracy(s, window)
            exposure = self._exposure(s, window, now=self._now())
        cost_minor = margin_minor = None
        if egp_per_usd is not None:
            cost_minor = int((cost.total_usd * egp_per_usd * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))
            margin_minor = revenue.net_minor - cost_minor
        return MarginReport(start, end, revenue, cost, egp_per_usd, cost_minor, margin_minor, accuracy, exposure)

    # -- revenue -------------------------------------------------------------------

    @staticmethod
    def _revenue(s: Session, window: dict[str, datetime]) -> RevenueReport:
        by_purpose = {
            str(purpose): int(minor)
            for purpose, minor in s.execute(
                sa.text(
                    "SELECT p.purpose::text, SUM(p.amount_minor) FROM payments p"
                    f" WHERE {_REVENUE_FILTER} GROUP BY p.purpose::text"
                ),
                window,
            )
        }
        refunded = int(
            s.execute(
                sa.text(
                    "SELECT COALESCE(SUM(r.amount_minor), 0) FROM payment_refunds r"
                    " WHERE r.kind::text = 'refund' AND r.status::text = 'succeeded'"
                    " AND r.updated_at >= :start AND r.updated_at < :end"
                ),
                window,
            ).scalar_one()
        )
        by_plan = [
            (str(code), int(minor))
            for code, minor in s.execute(
                sa.text(
                    "SELECT t.code, SUM(p.amount_minor) FROM payments p"
                    " JOIN plan_tiers t ON t.id = p.plan_tier_id"
                    f" WHERE {_REVENUE_FILTER} GROUP BY t.code ORDER BY t.code"
                ),
                window,
            )
        ]
        recurring = sum(v for k, v in by_purpose.items() if PaymentPurpose(k) in RECURRING_PURPOSES)
        packs = sum(v for k, v in by_purpose.items() if PaymentPurpose(k) in PACK_PURPOSES)
        return RevenueReport(
            recurring_minor=recurring,
            packs_minor=packs,
            refunded_minor=refunded,
            net_minor=recurring + packs - refunded,
            by_purpose=dict(sorted(by_purpose.items())),
            by_plan=by_plan,
        )

    # -- cost ------------------------------------------------------------------------

    @staticmethod
    def _cost(s: Session, window: dict[str, datetime]) -> CostReport:
        jobs_in_window = (
            "j.created_at >= :start AND j.created_at < :end AND j.actual_cost_usd IS NOT NULL"
        )
        by_action = [
            CostRow(str(action), int(jobs), Decimal(cost))
            for action, jobs, cost in s.execute(
                sa.text(
                    "SELECT j.action, COUNT(*), SUM(j.actual_cost_usd) FROM usage_jobs j"
                    f" WHERE {jobs_in_window} GROUP BY j.action ORDER BY j.action"
                ),
                window,
            )
        ]
        by_plan = [
            CostRow(None if code is None else str(code), int(jobs), Decimal(cost))
            for code, jobs, cost in s.execute(
                sa.text(
                    "SELECT t.code, COUNT(*), SUM(j.actual_cost_usd) FROM usage_jobs j"
                    " LEFT JOIN LATERAL ("
                    "   SELECT s.plan_tier_id FROM subscription_periods sp"
                    "   JOIN subscriptions s ON s.id = sp.subscription_id"
                    "   WHERE s.user_id = j.actor_user_id"
                    "     AND sp.period_start <= j.created_at AND j.created_at < sp.period_end"
                    "   ORDER BY sp.period_start DESC LIMIT 1"
                    " ) plan ON TRUE"
                    " LEFT JOIN plan_tiers t ON t.id = plan.plan_tier_id"
                    f" WHERE {jobs_in_window} GROUP BY t.code ORDER BY t.code NULLS LAST"
                ),
                window,
            )
        ]
        by_model = [
            (str(model), Decimal(cost))
            for model, cost in s.execute(
                sa.text(
                    "SELECT c.model, SUM(c.cost_usd) FROM usage_job_model_costs c"
                    " JOIN usage_jobs j ON j.id = c.usage_job_id"
                    " WHERE j.created_at >= :start AND j.created_at < :end"
                    " GROUP BY c.model ORDER BY c.model"
                ),
                window,
            )
        ]
        total = sum((row.cost_usd for row in by_action), _ZERO)
        attributed = sum((cost for _, cost in by_model), _ZERO)
        return CostReport(total, by_action, by_plan, by_model, total - attributed)

    # -- estimate accuracy -------------------------------------------------------------

    @staticmethod
    def _accuracy(s: Session, window: dict[str, datetime]) -> list[AccuracyRow]:
        rows = s.execute(
            sa.text(
                "WITH settled AS ("
                "  SELECT j.action, j.estimator_version, j.estimate_low, j.estimate_high,"
                "         CEIL(j.actual_cost_usd * r.units_per_usd)::bigint AS actual_units"
                "  FROM usage_jobs j"
                "  JOIN usage_rates r ON r.version = j.rate_version AND r.action = j.action"
                "  WHERE j.status::text = 'settled' AND j.actual_cost_usd IS NOT NULL"
                "    AND j.created_at >= :start AND j.created_at < :end"
                ")"
                " SELECT action, estimator_version, COUNT(*),"
                "  COUNT(*) FILTER (WHERE actual_units < estimate_low),"
                "  COUNT(*) FILTER (WHERE actual_units > estimate_high),"
                "  AVG(actual_units - estimate_high) FILTER (WHERE actual_units > estimate_high),"
                "  MAX(actual_units - estimate_high) FILTER (WHERE actual_units > estimate_high)"
                " FROM settled GROUP BY action, estimator_version"
                " ORDER BY action, estimator_version"
            ),
            window,
        )
        return [
            AccuracyRow(
                action=str(action),
                estimator_version=int(version),
                jobs=int(jobs),
                below=int(below),
                above=int(above),
                share_outside=round((int(below) + int(above)) / int(jobs), 4),
                mean_overrun_units=None if mean is None else round(float(mean), 2),
                max_overrun_units=None if peak is None else int(peak),
            )
            for action, version, jobs, below, above, mean, peak in rows
        ]

    # -- exposure ----------------------------------------------------------------------

    @staticmethod
    def _exposure(s: Session, window: dict[str, datetime], *, now: datetime) -> ExposureReport:
        debt_units, debtors = s.execute(
            sa.text(
                "SELECT COALESCE(SUM(outstanding), 0), COUNT(DISTINCT owner_user_id)"
                " FROM usage_debts WHERE outstanding > 0"
            )
        ).one()
        top = [
            Debtor(uid, str(email), int(outstanding))
            for uid, email, outstanding in s.execute(
                sa.text(
                    "SELECT d.owner_user_id, u.email, SUM(d.outstanding) AS owed"
                    " FROM usage_debts d JOIN users u ON u.id = d.owner_user_id"
                    " WHERE d.outstanding > 0 GROUP BY d.owner_user_id, u.email"
                    " ORDER BY owed DESC, u.email LIMIT :top"
                ),
                {"top": _TOP_DEBTORS},
            )
        ]
        live = (
            "g.effective_at <= :now AND (g.expires_at IS NULL OR g.expires_at > :now)"
        )
        at_limit = s.execute(
            sa.text(
                "SELECT COUNT(*) FROM ("
                "  SELECT g.owner_user_id FROM usage_grants g"
                "  JOIN usage_grant_balances b ON b.grant_id = g.id"
                f"  WHERE g.kind::text = 'period_allowance' AND {live}"
                "  GROUP BY g.owner_user_id HAVING SUM(b.remaining - b.held) <= 0"
                ") at_limit"
            ),
            {"now": now},
        ).scalar_one()
        expiring_units, expiring_owners = s.execute(
            sa.text(
                "SELECT COALESCE(SUM(b.remaining - b.held), 0), COUNT(DISTINCT g.owner_user_id)"
                " FROM usage_grants g JOIN usage_grant_balances b ON b.grant_id = g.id"
                " WHERE g.visible AND g.expires_at > :now AND g.expires_at <= :soon"
                " AND b.remaining - b.held > 0"
            ),
            {"now": now, "soon": now + _EXPIRING_SOON},
        ).one()
        expired_unused = s.execute(
            sa.text(
                "SELECT COALESCE(SUM(ABS(e.units)), 0) FROM usage_entries e"
                " JOIN usage_grants g ON g.id = e.grant_id"
                " WHERE e.kind::text = 'expire' AND g.visible"
                " AND e.event_at >= :start AND e.event_at < :end"
            ),
            window,
        ).scalar_one()
        expired_jobs, expired_cost = s.execute(
            sa.text(
                "SELECT COUNT(*), COALESCE(SUM(actual_cost_usd), 0) FROM usage_jobs"
                " WHERE status::text = 'expired' AND created_at >= :start AND created_at < :end"
            ),
            window,
        ).one()
        return ExposureReport(
            outstanding_debt_units=int(debt_units),
            debtors=int(debtors),
            top_debtors=top,
            users_at_limit=int(at_limit),
            credits_expiring_30d_units=int(expiring_units),
            credits_expiring_30d_owners=int(expiring_owners),
            credits_expired_unused_units=int(expired_unused),
            expired_jobs=int(expired_jobs),
            expired_jobs_cost_usd=Decimal(expired_cost),
        )


__all__ = [
    "PACK_PURPOSES",
    "RECURRING_PURPOSES",
    "AccuracyRow",
    "AdminMarginService",
    "CostReport",
    "CostRow",
    "Debtor",
    "ExposureReport",
    "MarginReport",
    "RevenueReport",
]
```

- [ ] **Step 5: Add the dependency, DTOs and route**

In `lemely/web/deps_admin_billing.py` add (and export):

```python
from lemely.db.admin_margin_repo import AdminMarginService


def get_admin_margin_service() -> AdminMarginService:
    return AdminMarginService(get_sessionmaker(get_settings()))
```

Append to `lemely/web/schemas_admin_billing.py`:

```python
# -- margin ---------------------------------------------------------------------


class MoneyByKeyDTO(ApiModel):
    key: str
    minor: int


class CostRowDTO(ApiModel):
    key: str | None
    jobs: int
    costUsd: str


class ModelCostDTO(ApiModel):
    model: str
    costUsd: str


class RevenueDTO(ApiModel):
    recurringMinor: int
    packsMinor: int
    refundedMinor: int
    netMinor: int
    byPurpose: dict[str, int]
    byPlan: list[MoneyByKeyDTO]


class CostDTO(ApiModel):
    totalUsd: str
    byAction: list[CostRowDTO]
    byPlan: list[CostRowDTO]
    byModel: list[ModelCostDTO]
    unattributedModelUsd: str


class AccuracyRowDTO(ApiModel):
    action: str
    estimatorVersion: int
    jobs: int
    below: int
    above: int
    shareOutside: float
    meanOverrunUnits: float | None
    maxOverrunUnits: int | None


class DebtorDTO(ApiModel):
    userId: str
    email: str
    outstanding: int


class ExpiredJobsDTO(ApiModel):
    count: int
    costUsd: str


class ExposureDTO(ApiModel):
    outstandingDebtUnits: int
    debtors: int
    topDebtors: list[DebtorDTO]
    usersAtLimit: int
    creditsExpiring30dUnits: int
    creditsExpiring30dOwners: int
    creditsExpiredUnusedUnits: int
    expiredJobs: ExpiredJobsDTO


class MarginReportDTO(ApiModel):
    windowStart: datetime
    windowEnd: datetime
    revenue: RevenueDTO
    cost: CostDTO
    egpPerUsd: str | None
    costMinor: int | None
    marginMinor: int | None
    accuracy: list[AccuracyRowDTO]
    exposure: ExposureDTO
```

Append to `lemely/web/routers/admin_billing.py` (imports: `Decimal`, `AdminMarginService`,
`CostRow`, `MarginReport`, `get_admin_margin_service`, the margin DTOs):

```python
MarginService = Annotated[AdminMarginService, Depends(get_admin_margin_service)]


def _usd(value: Decimal) -> str:
    return f"{value:.6f}"


def _cost_row(row: CostRow) -> CostRowDTO:
    return CostRowDTO(key=row.key, jobs=row.jobs, costUsd=_usd(row.cost_usd))


def margin_dto(r: MarginReport) -> MarginReportDTO:
    return MarginReportDTO(
        windowStart=r.start,
        windowEnd=r.end,
        revenue=RevenueDTO(
            recurringMinor=r.revenue.recurring_minor,
            packsMinor=r.revenue.packs_minor,
            refundedMinor=r.revenue.refunded_minor,
            netMinor=r.revenue.net_minor,
            byPurpose=r.revenue.by_purpose,
            byPlan=[MoneyByKeyDTO(key=k, minor=v) for k, v in r.revenue.by_plan],
        ),
        cost=CostDTO(
            totalUsd=_usd(r.cost.total_usd),
            byAction=[_cost_row(x) for x in r.cost.by_action],
            byPlan=[_cost_row(x) for x in r.cost.by_plan],
            byModel=[ModelCostDTO(model=m, costUsd=_usd(c)) for m, c in r.cost.by_model],
            unattributedModelUsd=_usd(r.cost.unattributed_model_usd),
        ),
        egpPerUsd=None if r.egp_per_usd is None else str(r.egp_per_usd),
        costMinor=r.cost_minor,
        marginMinor=r.margin_minor,
        accuracy=[
            AccuracyRowDTO(
                action=a.action, estimatorVersion=a.estimator_version, jobs=a.jobs, below=a.below,
                above=a.above, shareOutside=a.share_outside, meanOverrunUnits=a.mean_overrun_units,
                maxOverrunUnits=a.max_overrun_units,
            )
            for a in r.accuracy
        ],
        exposure=ExposureDTO(
            outstandingDebtUnits=r.exposure.outstanding_debt_units,
            debtors=r.exposure.debtors,
            topDebtors=[
                DebtorDTO(userId=str(d.user_id), email=d.email, outstanding=d.outstanding)
                for d in r.exposure.top_debtors
            ],
            usersAtLimit=r.exposure.users_at_limit,
            creditsExpiring30dUnits=r.exposure.credits_expiring_30d_units,
            creditsExpiring30dOwners=r.exposure.credits_expiring_30d_owners,
            creditsExpiredUnusedUnits=r.exposure.credits_expired_unused_units,
            expiredJobs=ExpiredJobsDTO(
                count=r.exposure.expired_jobs, costUsd=_usd(r.exposure.expired_jobs_cost_usd)
            ),
        ),
    )


# -- area 4: money and margin ---------------------------------------------------


@router.get("/margin", response_model=MarginReportDTO)
def margin_report(
    service: MarginService,
    start: Annotated[datetime, Query(alias="from")],
    end: Annotated[datetime, Query(alias="to")],
    egpPerUsd: Annotated[Decimal | None, Query(gt=0, le=10_000)] = None,  # noqa: N803 - wire name
) -> MarginReportDTO:
    with mapped_errors():
        return margin_dto(service.margin(start, end, egp_per_usd=egpPerUsd))
```

- [ ] **Step 6: Register the route**

Matrix (+1 to the `PLATFORM_ADMIN` heading): `("GET", "/api/admin/billing/margin"): PLATFORM_ADMIN,`.
`PLANNED`: `("GET", f"{P}/margin"),`.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest --no-cov tests/test_admin_billing_margin.py tests/test_admin_billing_authz.py tests/test_authz_matrix_complete.py tests/architecture -v`
Expected: all pass, no skips. If a figure differs, the seed or the SQL is wrong — fix the code,
never the expected number (each is derived in the test's comments and the seed).

- [ ] **Step 8: Commit**

```bash
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files
P="lemely/db/admin_margin_repo.py lemely/web/deps_admin_billing.py lemely/web/schemas_admin_billing.py lemely/web/routers/admin_billing.py tests/admin_billing_db.py tests/test_authz_matrix_complete.py tests/test_admin_billing_authz.py tests/test_admin_billing_margin.py"
git add $P
git commit -S -m "feat(admin): money and margin report with exact aggregate queries" -- $P
```

---

### Task 11: Billing health

**Files:**
- Create: `lemely/db/admin_health_repo.py`
- Modify: `lemely/web/deps_admin_billing.py`, `lemely/web/schemas_admin_billing.py`, `lemely/web/routers/admin_billing.py`
- Modify: `tests/admin_billing_db.py` (health service override)
- Modify: `tests/test_authz_matrix_complete.py`, `tests/test_admin_billing_authz.py`
- Create: `tests/test_admin_billing_health.py`

**Interfaces:**
- Consumes: `JobRun`, `PaymobWebhookFailure` (Task 1); `JobRunRecorder`, `JobRunResult`, `record_webhook_failure` (Task 2); `PaymobEvent`, `PaymobEventKind`, `Payment`, `Subscription` (Phase 02).
- Produces:
  - `BILLING_JOB_NAMES: tuple[str, ...]`, `JobHealth(name, run: JobRun | None)`, `HealthReport`, `AdminHealthService(sessionmaker, *, now=...)` with `health(*, hours: int) -> HealthReport`.
  - `get_admin_health_service()`; DTOs `JobHealthDTO`, `BillingHealthDTO`.
  - Route: `GET /health?hours=`.

- [ ] **Step 1: Extend the test helpers**

In `tests/admin_billing_db.py` import `AdminHealthService` and `get_admin_health_service`, and add
to `service_overrides`:

```python
        get_admin_health_service: lambda: AdminHealthService(factory, now=clock),
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_admin_billing_health.py`:

```python
"""Billing health (spec §8 area 5): sweeper runs, webhook error rate, failed charges."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest

from lemely.db.admin_health_repo import BILLING_JOB_NAMES
from lemely.db.billing_observability_repo import JobRunRecorder, JobRunResult, record_webhook_failure
from lemely.db.models.billing import PaymentPurpose, PaymentStatus, PaymobEvent, PaymobEventKind
from lemely.db.models.billing_ops import PaymobWebhookFailure
from lemely.db.models.enums import Role, SubscriptionStatus
from tests.admin_billing_db import (
    NOW,
    add_payment,
    add_plan_tier,
    add_subscription,
    add_user,
    admin_client,
    billing_database,
    emptied_after,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture(scope="module")
def billing_db() -> Iterator[sessionmaker[Session]]:
    with billing_database() as factory:
        yield factory


@pytest.fixture
def sm(billing_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(billing_db)


@pytest.fixture
def admin(sm: sessionmaker[Session]) -> uuid.UUID:
    return add_user(sm, Role.platform_admin)


def _event(sm: sessionmaker[Session], kind: PaymobEventKind, hours_ago: int, payload: dict[str, object]) -> None:
    with sm.begin() as session:
        session.add(
            PaymobEvent(
                kind=kind, dedupe_key=str(uuid.uuid4()), payload=payload,
                processed_at=NOW - timedelta(hours=hours_ago),
            )
        )


def test_health_reports_jobs_webhooks_and_failed_charges(sm: sessionmaker[Session], admin: uuid.UUID) -> None:
    record = JobRunRecorder(sm)
    record(JobRunResult("billing.reconcile_pending", NOW - timedelta(minutes=5), NOW - timedelta(minutes=5), 2, None))
    record(JobRunResult("usage.expire_grants", NOW - timedelta(minutes=5), NOW - timedelta(minutes=5), None, "RuntimeError: boom"))
    for _ in range(3):
        _event(sm, PaymobEventKind.transaction, 1, {"obj": {}})
    _event(sm, PaymobEventKind.subscription, 2, {"trigger_type": "Failed Transaction", "id": 1})
    _event(sm, PaymobEventKind.subscription, 30, {"trigger_type": "Failed Overdue Transaction", "id": 1})
    record_webhook_failure(sm, kind="transaction", reason="hmac_mismatch", payload=None, remote_addr=None)
    with sm.begin() as session:
        for row in session.query(PaymobWebhookFailure):
            row.received_at = NOW - timedelta(hours=1)
    student = add_user(sm, Role.student)
    add_payment(sm, payer=student, status=PaymentStatus.failed_mismatch, updated_at=NOW - timedelta(hours=1))
    add_payment(sm, payer=student, purpose=PaymentPurpose.auto_topup, status=PaymentStatus.failed,
                updated_at=NOW - timedelta(hours=2))
    add_payment(sm, payer=student, purpose=PaymentPurpose.extra_seats, status=PaymentStatus.failed,
                updated_at=NOW - timedelta(hours=3))
    add_payment(sm, payer=student, purpose=PaymentPurpose.extra_seats, status=PaymentStatus.failed,
                updated_at=NOW - timedelta(hours=48))
    add_subscription(sm, student, add_plan_tier(sm), status=SubscriptionStatus.past_due)

    resp = admin_client(sm, admin).get("/api/admin/billing/health", params={"hours": 24})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    jobs = {j["name"]: j for j in body["jobs"]}
    assert set(BILLING_JOB_NAMES) <= set(jobs)
    assert (jobs["billing.reconcile_pending"]["lastOutcome"], jobs["billing.reconcile_pending"]["lastResultCount"]) == ("ok", 2)
    assert (jobs["usage.expire_grants"]["lastOutcome"], jobs["usage.expire_grants"]["consecutiveFailures"]) == ("failed", 1)
    assert jobs["seats.release_due"]["neverRun"] is True
    assert {k: body[k] for k in (
        "windowHours", "verifiedEvents", "hmacFailures", "webhookErrorRate", "mismatches",
        "renewalFailureEvents", "pastDueNow", "failedAutoTopups", "failedExtraSeatCharges",
    )} == {
        "windowHours": 24,
        "verifiedEvents": 4,
        "hmacFailures": 1,
        "webhookErrorRate": 0.2,
        "mismatches": 1,
        "renewalFailureEvents": 1,
        "pastDueNow": 1,
        "failedAutoTopups": 1,
        "failedExtraSeatCharges": 1,
    }


def test_no_traffic_means_no_error_rate(sm: sessionmaker[Session], admin: uuid.UUID) -> None:
    body = admin_client(sm, admin).get("/api/admin/billing/health").json()
    assert body["webhookErrorRate"] is None
    assert all(j["neverRun"] for j in body["jobs"])
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest --no-cov tests/test_admin_billing_health.py -v`
Expected: collection error, `No module named 'lemely.db.admin_health_repo'`.

- [ ] **Step 4: Write the health service**

Create `lemely/db/admin_health_repo.py`:

```python
"""Billing health (spec §8 area 5): what ran, what failed, and how webhooks are doing.

``BILLING_JOB_NAMES`` lists every billing sweeper job the index names (plus the admin
expiry job), so a job that has never run shows as ``never_run`` instead of being absent.
Any other job that ``job_runs`` has seen (the notification jobs) is listed too.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final

import sqlalchemy as sa
from sqlalchemy import select

from lemely.db.models.billing import (
    Payment,
    PaymentPurpose,
    PaymentStatus,
    PaymobEvent,
    PaymobEventKind,
    Subscription,
)
from lemely.db.models.billing_ops import JobRun, PaymobWebhookFailure
from lemely.db.models.enums import SubscriptionStatus

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker

BILLING_JOB_NAMES: Final = (
    "billing.reconcile_pending",
    "usage.expire_stale_jobs",
    "usage.expire_grants",
    "usage.reconcile_balances",
    "subscriptions.expire_overdue",
    "subscriptions.period_end",
    "subscriptions.drift_check",
    "seats.monthly_allowance",
    "seats.release_due",
    "billing.auto_topup",
    "billing.extra_seat_renewal_charge",
    "admin.expire_manual_subscriptions",
)
_RENEWAL_FAILURES: Final = ("Failed Transaction", "Failed Overdue Transaction")
_FAILED: Final = (PaymentStatus.failed, PaymentStatus.failed_mismatch)


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class JobHealth:
    name: str
    run: JobRun | None


@dataclass(frozen=True, slots=True)
class HealthReport:
    window_hours: int
    jobs: list[JobHealth]
    verified_events: int
    hmac_failures: int
    webhook_error_rate: float | None
    mismatches: int
    renewal_failure_events: int
    past_due_now: int
    failed_auto_topups: int
    failed_extra_seat_charges: int


class AdminHealthService:
    def __init__(
        self, sessionmaker: sessionmaker[Session], *, now: Callable[[], datetime] = _utcnow
    ) -> None:
        self._sm = sessionmaker
        self._now = now

    def health(self, *, hours: int) -> HealthReport:
        since = self._now() - timedelta(hours=hours)
        with self._sm() as s:

            def count(stmt: sa.Select[tuple[int]]) -> int:
                return int(s.scalar(stmt) or 0)

            runs = {r.job_name: r for r in s.scalars(select(JobRun))}
            names = sorted(set(BILLING_JOB_NAMES) | set(runs))
            events = count(
                select(sa.func.count()).select_from(PaymobEvent).where(PaymobEvent.processed_at >= since)
            )
            failures = count(
                select(sa.func.count())
                .select_from(PaymobWebhookFailure)
                .where(PaymobWebhookFailure.received_at >= since)
            )
            mismatches = count(
                select(sa.func.count())
                .select_from(Payment)
                .where(Payment.status == PaymentStatus.failed_mismatch, Payment.updated_at >= since)
            )
            renewal_failures = count(
                select(sa.func.count())
                .select_from(PaymobEvent)
                .where(
                    PaymobEvent.kind == PaymobEventKind.subscription,
                    PaymobEvent.payload["trigger_type"].astext.in_(_RENEWAL_FAILURES),
                    PaymobEvent.processed_at >= since,
                )
            )
            past_due = count(
                select(sa.func.count())
                .select_from(Subscription)
                .where(Subscription.status == SubscriptionStatus.past_due)
            )

            def failed(purpose: PaymentPurpose) -> int:
                return count(
                    select(sa.func.count())
                    .select_from(Payment)
                    .where(
                        Payment.purpose == purpose,
                        Payment.status.in_(_FAILED),
                        Payment.updated_at >= since,
                    )
                )

            seen = events + failures
            return HealthReport(
                window_hours=hours,
                jobs=[JobHealth(name, runs.get(name)) for name in names],
                verified_events=events,
                hmac_failures=failures,
                webhook_error_rate=round(failures / seen, 4) if seen else None,
                mismatches=mismatches,
                renewal_failure_events=renewal_failures,
                past_due_now=past_due,
                failed_auto_topups=failed(PaymentPurpose.auto_topup),
                failed_extra_seat_charges=failed(PaymentPurpose.extra_seats),
            )


__all__ = ["BILLING_JOB_NAMES", "AdminHealthService", "HealthReport", "JobHealth"]
```

- [ ] **Step 5: Add the dependency, DTOs and route**

In `lemely/web/deps_admin_billing.py` add (and export):

```python
from lemely.db.admin_health_repo import AdminHealthService


def get_admin_health_service() -> AdminHealthService:
    return AdminHealthService(get_sessionmaker(get_settings()))
```

Append to `lemely/web/schemas_admin_billing.py`:

```python
# -- health ---------------------------------------------------------------------


class JobHealthDTO(ApiModel):
    name: str
    neverRun: bool
    lastStartedAt: datetime | None
    lastFinishedAt: datetime | None
    lastOutcome: Literal["ok", "failed"] | None
    lastResultCount: int | None
    lastError: str | None
    lastSuccessAt: datetime | None
    consecutiveFailures: int
    totalRuns: int
    totalFailures: int


class BillingHealthDTO(ApiModel):
    windowHours: int
    jobs: list[JobHealthDTO]
    verifiedEvents: int
    hmacFailures: int
    webhookErrorRate: float | None
    mismatches: int
    renewalFailureEvents: int
    pastDueNow: int
    failedAutoTopups: int
    failedExtraSeatCharges: int
```

Append to `lemely/web/routers/admin_billing.py` (imports: `AdminHealthService`, `JobHealth`,
`get_admin_health_service`, the two DTOs):

```python
HealthService = Annotated[AdminHealthService, Depends(get_admin_health_service)]


def _job_health_dto(j: JobHealth) -> JobHealthDTO:
    r = j.run
    return JobHealthDTO(
        name=j.name,
        neverRun=r is None,
        lastStartedAt=r.last_started_at if r else None,
        lastFinishedAt=r.last_finished_at if r else None,
        lastOutcome=r.last_outcome if r else None,  # type: ignore[arg-type]
        lastResultCount=r.last_result_count if r else None,
        lastError=r.last_error if r else None,
        lastSuccessAt=r.last_success_at if r else None,
        consecutiveFailures=r.consecutive_failures if r else 0,
        totalRuns=r.total_runs if r else 0,
        totalFailures=r.total_failures if r else 0,
    )


# -- area 5: health ---------------------------------------------------------------


@router.get("/health", response_model=BillingHealthDTO)
def billing_health(
    service: HealthService, hours: Annotated[int, Query(ge=1, le=720)] = 24
) -> BillingHealthDTO:
    h = service.health(hours=hours)
    return BillingHealthDTO(
        windowHours=h.window_hours,
        jobs=[_job_health_dto(j) for j in h.jobs],
        verifiedEvents=h.verified_events,
        hmacFailures=h.hmac_failures,
        webhookErrorRate=h.webhook_error_rate,
        mismatches=h.mismatches,
        renewalFailureEvents=h.renewal_failure_events,
        pastDueNow=h.past_due_now,
        failedAutoTopups=h.failed_auto_topups,
        failedExtraSeatCharges=h.failed_extra_seat_charges,
    )
```

- [ ] **Step 6: Register the route**

Matrix (+1 to the `PLATFORM_ADMIN` heading): `("GET", "/api/admin/billing/health"): PLATFORM_ADMIN,`.
`PLANNED`: `("GET", f"{P}/health"),`. After this task `PLANNED` holds 24 routes and the Phase 07
lines in the matrix add 24 to the `PLATFORM_ADMIN` count.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest --no-cov tests/test_admin_billing_health.py tests/test_admin_billing_authz.py tests/test_authz_matrix_complete.py tests/architecture -v`
Expected: all pass, no skips.

- [ ] **Step 8: Commit**

```bash
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files
P="lemely/db/admin_health_repo.py lemely/web/deps_admin_billing.py lemely/web/schemas_admin_billing.py lemely/web/routers/admin_billing.py tests/admin_billing_db.py tests/test_authz_matrix_complete.py tests/test_admin_billing_authz.py tests/test_admin_billing_health.py"
git add $P
git commit -S -m "feat(admin): billing health — sweeper runs, webhook error rate, failed charges" -- $P
```

- [ ] **Step 9: Phase sweep on the final tree**

Run every test file this phase created or touched, plus the repo lint tests, once, on the
committed tree:

```bash
PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest --no-cov \
  tests/test_migration_admin_audit_log.py tests/test_admin_billing_audit.py \
  tests/test_billing_observability.py tests/test_usage_model_costs.py \
  tests/test_admin_billing_catalogue.py tests/test_admin_billing_authz.py \
  tests/test_admin_billing_customers.py tests/test_admin_billing_ledger_actions.py \
  tests/test_admin_billing_subscriptions.py tests/test_admin_billing_refunds.py \
  tests/test_admin_billing_payments.py tests/test_admin_billing_margin.py \
  tests/test_admin_billing_health.py tests/test_authz_matrix_complete.py \
  tests/test_web_platform_admin.py tests/test_scheduled_notifications.py \
  tests/test_billing_callbacks.py tests/test_billing_reconcile.py tests/test_web_paymob_webhooks.py \
  tests/test_db_schema.py tests/architecture -v
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files
git status --short
```

Expected: all pass with no skips; pre-commit passes with no changes; `git status` shows nothing
of this phase uncommitted. If `graphify-out/` exists in the worktree, run `graphify update .`
(project rule after code changes).

---

## Spec coverage (self-review)

| Spec requirement | Task |
|---|---|
| §4.7 `admin_audit_log`, append-only trigger, reason required, same transaction | 1 (model, migration, trigger on both paths, CHECK), every action task asserts its row |
| §8.1 tiers incl. seats fields, Paymob plan sync and drift warning | 4 |
| §8.1 credit packs, signup grants and free allowance | 4 (via Phase 04's signup packs) |
| §8.1 usage rates and estimators, versioned | 4 (new versions only; old rows asserted unchanged) |
| §8.2 search by name, email, Paymob order id | 5 |
| §8.2 subscription and period, grants with expiry, balance, debt, jobs estimate vs actual, payments, seats/assistants, linked parents | 5 |
| §8.2 grant credits, adjust, forgive debt | 6 |
| §8.2 extend or cancel subscription; manual activation (Activations kept, audited) | 7 |
| §8.2 refund or void; §6 refund row before call; claw back unspent units only | 8 |
| §8.3 live list with filters; problem queue (mismatch, pending > 1h, missing callbacks, HMAC failures); manual reconcile | 2 (facts), 9 |
| §8.4 revenue vs LLM cost by action, plan, model; estimate accuracy per action and estimator version; debt; users at limit; expiring credits; expired-job cost | 3 (per-model cost), 10 |
| §8.5 last run per sweeper job, webhook error rate, renewal failures, failed auto top-ups, failed extra-seat charges | 2 (job runs), 11 |
| §7 admin endpoints require `platform_admin`; non-admins rejected | 4 (router guard, `test_admin_billing_authz.py`), matrix entries in 4–11 |
| §9 "every admin money action writes an audit row" | 4, 6, 7, 8, 9 |

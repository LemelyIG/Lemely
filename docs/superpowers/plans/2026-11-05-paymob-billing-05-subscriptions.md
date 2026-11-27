# Paymob billing 05 — subscriptions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Card subscriptions on Paymob's subscriptions module: checkout, first payment, renewals,
3-day grace, expiry, downgrade, cancel at period end, a daily drift check, and monthly seat
allowances for seated students, with the existing manual-activation path still working.

**Architecture:** `SubscriptionService` (`lemely/db/subscription_repo.py`) owns the subscription
lifecycle. It creates the first payment through Phase 02's `BillingService.create_intention_checkout`,
registers paid handlers for `subscription_first` and `subscription_renewal`, and turns every paid
period into one `subscription_periods` row plus one `period_allowance` grant through Phase 01's
`UsageLedger.issue_grant`, which repays debt first. Paymob subscription webhooks are verified by HMAC,
deduplicated through `paymob_events`, and never trusted for state or amounts: the service re-fetches
the subscription and the last transaction from Paymob. Sweeper jobs (expiry, period-end changes, drift,
seat allowances, seat release) run in the existing in-process sweeper.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2 ORM, Alembic, Postgres, pydantic v2, structlog,
pytest. Paymob subscriptions API (research `docs/billing/research/02` §2.3, §6 and `04` §2).

## Global Constraints

- Spec: `docs/superpowers/specs/2026-11-02-paymob-billing-design.md` (revision 2) is the source of truth for behaviour. Index: `docs/superpowers/plans/2026-11-05-paymob-billing-00-index.md` is the source of truth for names, files, migration numbers and cross-phase interfaces.
- Signed commits only: `git add <paths> && git commit -S -m "<msg>" -- <paths>`. Scopes `feat(billing):`, `test(billing):`, `fix(billing):`.
- Before each commit run `/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files` and fix every failure. The ruff hook autofixes: re-run it until it passes, then re-stage the fixed files.
- Tests: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest --no-cov <touched test files> -v` (`--no-cov` always: the repo's `--cov-fail-under=70` fails any subset run; index R2). Never run the full suite (`make test`, bare `pytest`). When a task adds a module under `lemely/`, also run `tests/architecture/`.
- After code changes, run `graphify update .` (project rule; AST-only, no API cost) and include `graphify-out/` in the commit if it changed.
- Do not push. Do not open PRs.
- Money is integer minor units (piasters, `BIGINT`). Usage is integer units (`BIGINT`).
- UUID primary keys with `server_default=sa.text("gen_random_uuid()")`, Postgres enums, `TimestampMixin` from `lemely.db.models.enums`.
- `lemely/db/models/*` never imports `lemely.core`. `lemely/core/*` never imports `lemely.db` or `lemely.web`. Import-linter contracts in `pyproject.toml` stay green.
- Paymob secret key, API key and HMAC secret are read on the server only. Never log them.
- Every webhook state change happens in one DB transaction; return 200 only after commit.
- No placeholder code: no `TODO`, no `pass` bodies, no `test.skip`, no stub tests.
- Grace period after a failed renewal: exactly 3 days (spec §2.6, §5.2).
- Paymob plan frequencies allowed: 7, 15, 30, 60, 90, 180, 360 days (research 02 §6). Monthly = 30, yearly = 360.

---

## Contract deviations

Each item departs from, or adds to, the index's Phase 05 contract. Later phases use the names as
written here.

1. **`seat_allowance_repo` functions take a session.** The index gives
   `grant_monthly_seat_allowances(now) -> int` and `grant_seat_allowance_on_claim(member_id, now)`.
   They are `grant_monthly_seat_allowances(session: Session, *, now: datetime) -> int` and
   `grant_seat_allowance_on_claim(session: Session, member_id: UUID, *, now: datetime) -> UsageGrant | None`.
   Reason: every other DB entry point takes the caller's session, and the claim hook must run inside
   `TeacherTeamService.claim_seat_for_class_join`'s transaction.
2. **`SubscriptionService` constructor and signatures.** The index lists method names only. The
   constructor is `SubscriptionService(session, client, settings)` (mirrors `BillingService`); the
   signatures are in the Interfaces blocks below. Sweep methods (`expire_overdue`,
   `apply_period_end_changes`, `check_drift`) commit after each subscription so one Paymob failure
   cannot undo another subscription's change. `create_subscription_checkout` is committed by Phase
   02's `create_intention_checkout` (spec §6: the payment row exists before Paymob is called), so
   its caller must not wrap it in `session.begin()`. All other methods leave the commit to the
   caller.
3. **The one-live-subscription index is Phase 02's, not 0055's (index R8).** `0053` creates
   `uq_subscriptions_one_live_paid` (per `user_id`, live statuses, `payer_user_id IS NOT NULL`) and
   `LIVE_SUBSCRIPTION_STATUSES` (tuple of `SubscriptionStatus`) in `lemely/db/models/billing.py`;
   Phase 05 imports both and adds only `PLAN_LIVE_STATUSES` (`active`, `past_due`). Because the
   index ignores payer-less manual activations, Phase 05 guards in application code: checkout
   refuses when the beneficiary holds *any* live subscription (a complimentary one included), and
   `admin_repo.decide_activation` refuses (409 `SubscriptionConflictError`) to activate a manual plan
   beside another live one. The index stays the race guard between two paid checkouts.
4. **0055 adds four things beyond the spec's table:** `subscriptions.paymob_amount_minor` (the
   renewal amount Lemely last set at Paymob, the expected amount of the next charge and the drift
   reference), `subscriptions.paymob_cancelled_at` (so a Paymob cancel is pushed once), the
   `notificationtype` value `billing` and the `notification_preferences.billing` column (the existing
   Resend outbox gates every template on a notification type). `billing` has no user toggle (no
   `set()` keyword, no `/api/me` field): payment notices are transactional.
5. **Routes.** The spec's `POST /billing/checkout` is `POST {billing prefix}/subscriptions/checkout`,
   so it cannot collide with Phase 02's pack checkout. Phase 08 also gets
   `GET {billing prefix}/subscriptions`, `POST {billing prefix}/subscriptions/{id}/downgrade` and
   `POST {billing prefix}/subscriptions/{id}/cancel`, plus `GET /api/billing/summary` (deviation
   15, Task 13). The billing prefix is `/api/billing` (index R1).
6. **Periods follow Paymob cycles.** Monthly periods are 30 days and yearly 360 days, matching the
   Paymob plan frequency, so Lemely's period and Paymob's billing date never drift apart. Seat
   allowances alone use calendar months (spec §5.9).
7. **Paymob plans use `use_transaction_amount=true`,** so extra seats bought at the first checkout
   are part of every renewal charge.
8. **Cancel at period end is pushed to Paymob on the next sweep, not at period end.** Paymob cancel
   is permanent and Paymob charges on the `next_billing` date, which can come before a period-end
   sweep. Local access continues until `current_period_end`; the mirror ignores Paymob's `canceled`
   webhook for a subscription Lemely is cancelling at period end.
9. **`paymob_events` payload for `kind=subscription`** is `{"body": <webhook JSON>, "remote": <GET
   subscriptions/{id} JSON>}`. Linking a Paymob subscription to ours reads only `remote` (the
   webhook body is not covered by the HMAC).
10. **Expected renewal amount and pending seats (index R6).** The API Phase 06 calls:
    - `SubscriptionService.next_renewal_amount(subscription) -> int` is the only place the amount
      Paymob should charge next is computed. The period-end push and the drift check use it; the
      renewal mismatch check compares against `paymob_amount_minor`, which only
      `sync_renewal_amount` and the first payment write. Phase 06 changes only this method's body
      for its fallback path; it does not edit `check_drift`.
    - `SubscriptionService.sync_renewal_amount(subscription) -> bool` PUTs that amount and stamps
      `paymob_amount_minor` in the caller's transaction. Phase 06 calls it after changing
      `extra_seats` / `pending_extra_seats` on a locked row instead of PUTting itself. A renewal
      charge of any other amount is recorded `failed_mismatch` with no grant (spec §6).
    - Phase 05 alone applies `pending_plan_tier_id` and `pending_extra_seats` at renewal
      (`_grant_renewal_period`), then moves excess seats to `leaving`. Phase 06's renewal hook only
      queues the fallback seat charge.
11. **Abandoned checkouts.** A `pending_first_payment` subscription whose first payment failed, is
    older than 2 hours, or was started by the same payer is set to `expired` when a new checkout for
    the same beneficiary starts. A late paid callback for such a row reactivates it if the user has
    no other live subscription, and otherwise logs `subscription_first_paid_for_superseded_checkout`
    for a manual refund.
12. **New modules not named in the index:** `lemely/core/subscription_rules.py` (pure arithmetic),
    `lemely/db/billing_notices.py` (outbox helper), `lemely/web/subscription_deps.py`,
    `lemely/web/subscription_jobs.py`, `lemely/web/schemas_subscriptions.py`,
    `tests/subscription_fixtures.py`.
13. **Billing emails link to `/billing`.** Phase 08 must serve the payer's billing screen at that
    path.
14. **Seat grants never repay the student's debt (index R13, Phase 01 behaviour).** Task 10's
    `test_seat_grant_never_repays_the_students_own_debt` pins it from this side.
15. **`GET /api/billing/summary?beneficiaryId=` (index R3).** Owned here; Phase 08 matches it. Its
    `beneficiary`, `subscription`, `canManage`, `managedByName` and `savedCard` fields follow Phase
    08's `BillingSummary` type, with `subscription.tier` / `pendingTier` as Phase 02's `PlanTierDTO`
    (so the tier id is `planTierId`, as in the catalogue). It adds `usage` (allowance meter),
    `credits` (balance with expiry breakdown), `debtUnits` and, for teachers, `seats`. Phase 08 must
    extend its type with those four fields.
16. **Complimentary subscriptions (index R15).** `expire_overdue`, `apply_period_end_changes` and
    `check_drift` select only rows with a `paymob_subscription_id`.
17. **Downgrades on the fallback path (Phase 06 reconciliation).** With
    `PaymobSettings.subscription_amount_updatable=False`, `schedule_downgrade` raises
    `DowngradeUnavailable` (`downgrade_unavailable`, HTTP 409), matching Phase 06's
    `upgrade_unavailable`. Clearing a pending downgrade and cancelling stay allowed. Phase 05 runs
    before Phase 06, so Task 8 adds the `subscription_amount_updatable: bool = True` field to
    `PaymobSettings`; Phase 06 must use it and not add it a second time.

## Pre-flight: upstream names this plan assumes

Phases 01–04 were planned in parallel with this one. Before Task 1, the controller runs these checks
on the merged branch and fixes this plan's text if a name differs (a rename here, not a redesign).

| Assumed name | Phase | Check |
|---|---|---|
| `lemely.db.models.usage`: `UsageGrant` (columns per spec §4.5), `UsageGrantBalance` (PK `grant_id`, `remaining`, `held`), `UsageDebt` (`owner_user_id`, `job_id` nullable, `units`, `outstanding`), `GrantKind` — verified against the Phase 01 plan | 01 | `grep -n "class UsageGrant\b\|class UsageGrantBalance\|class UsageDebt\|class GrantKind" lemely/db/models/usage.py` |
| `UsageLedger(session).issue_grant(*, owner_user_id, kind, units, idempotency_key, expires_at, visible, effective_at=None, payment_id=None, subscription_period_id=None, teacher_member_id=None)`, `.has_debt(owner_user_id)`, `.meter_fraction(owner_user_id, *, teacher_member_id, now)` — verified. `adjust(units=-n)` never creates debt (raises `InsufficientBalance`), so tests seed `UsageDebt` rows directly (`seed_debt`). Seat grants never repay debt (R13) | 01 | read `lemely/db/usage_ledger_repo.py` |
| `lemely.core.usage_pricing.prorate_units(units, period_start, period_end, now) -> int` (ceil, 0..units) — verified | 01 | `grep -n "def prorate_units" lemely/core/usage_pricing.py` |
| `SubscriptionStatus.pending_first_payment`, `.past_due` | 02 | `lemely/db/models/enums.py` |
| `lemely.db.models.billing`: `PlanAudience` (`student`, `teacher`), `PaymentPurpose`, `PaymentStatus`, `Payment`, `PaymobEvent` (`kind`, `dedupe_key`, `payload`, `processed_at` nullable, `created_at`), `PaymobEventKind.subscription` | 02 | `grep -n "^class " lemely/db/models/billing.py` |
| `Subscription` columns `payer_user_id`, `cancel_at_period_end`, `pending_plan_tier_id`, `current_period_start`, `grace_until`, `extra_seats`, `pending_extra_seats`, `paymob_subscription_id` (int), `version`; `PlanTier` columns `audience`, `allowance_units`, `paymob_plan_id` (int), `is_active`, `included_seats`, `seat_allowance_units`, `extra_seat_price_minor`; `Payment.paymob_txn_id` (int) | 02 | same file |
| `PaymobClient` methods as in the Phase 02 plan: `create_intention(body: dict)`, `create_plan(*, name, frequency_days, amount_cents, integration_id, webhook_url, use_transaction_amount)`, `get_subscription(id)`, `update_subscription(id, *, amount_cents)`, `cancel_subscription(id)`, `last_transaction(id)`; `PaymobError(message, *, status_code, timeout, body)` raised on any failed call | 02 | `lemely/io/paymob/client.py` |
| `verify_subscription_hmac(trigger_type, sub_id, received, secret) -> bool` | 02 | `lemely/io/paymob/hmac.py` |
| `PaymobSettings` field names and types (`hmac_secret` may be `SecretStr`) | 02 | `lemely/runtime/config.py` |
| `lemely.db.billing_repo`: `BillingService`, `CheckoutResult(payment_id, checkout_url)`, `register_paid_handler`, `billing_data_for(user: User) -> dict[str, str]`, `CheckoutUnavailable`. `create_intention_checkout` **commits** the session before and after calling Paymob, and on a Paymob failure marks the payment `failed`, commits and raises `CheckoutUnavailable` | 02 | `grep -n "def \|class " lemely/db/billing_repo.py` |
| `lemely.web.deps_billing.get_paymob_client()` and `reset_billing_singletons()`; `get_sweeper` imports from `deps_billing` locally | 02 | `grep -n "^def " lemely/web/deps_billing.py` |
| Routers `lemely/web/routers/billing.py` (`APIRouter(prefix="/api/billing")`) and `lemely/web/routers/paymob_webhooks.py` (`APIRouter(prefix="/api/webhooks/paymob")`); `SUBSCRIPTION_WEBHOOK_PATH` (Task 3) is `/api/webhooks/paymob/subscription` | 02 | `grep -n "APIRouter(" lemely/web/routers/billing.py lemely/web/routers/paymob_webhooks.py` |
| `Sweeper.billing_reconcile` field and the `billing.reconcile_pending` job block in `sweep_once` | 02 | `grep -n "billing_reconcile" lemely/web/scheduled_notifications.py` |
| `lemely.db.models.team`: `TeacherMember` (`teacher_user_id`, `member_user_id`, `kind`, `status`, `scope_subjects`, `scope_actions`, `cap_units`, `cap_period`, `leaves_at`, `created_at`), `TeacherMemberKind`, `TeacherMemberStatus`, `CapPeriod` | 03 | `lemely/db/models/team.py` |
| `TeacherTeamService(session)` (stores `self._session`); `claim_seat_for_class_join` contains `del now` and returns `existing` or `member` (Task 10 hooks both); `request_removal(member_id, *, now)`, `release_due(*, now) -> int`; module `month_end(now)` is the first instant of the next UTC month, equal to `calendar_month_bounds(now)[1]` (Task 3) | 03 | `lemely/db/teacher_team_repo.py` |
| Phase 03's migration revision id is `0054_teacher_team` (confirmed in the Phase 03 plan) | 03 | `ls lemely/db/migrations/versions/0054_*` |

---

## File structure

| File | Responsibility |
|---|---|
| `lemely/db/migrations/versions/0055_subscription_periods.py` | Create | Table, FK, two columns, partial unique index, `billing` notification type |
| `lemely/db/models/billing.py` | Modify | `SubscriptionPeriod`, two `Subscription` columns, live-status constants, the index |
| `lemely/db/models/usage.py` | Modify | FK on `UsageGrant.subscription_period_id` |
| `lemely/db/models/enums.py`, `lemely/db/models/ops.py`, `lemely/db/notification_repo.py`, `lemely/db/notification_prefs_repo.py` | Modify | `billing` notification type and its preference column |
| `lemely/db/admin_repo.py`, `lemely/web/routers/admin.py` | Modify | Manual activation refused (409) when a live subscription exists |
| `lemely/io/notify_email.py` | Modify | `subscription_notice` template |
| `lemely/db/billing_notices.py` | Create | Enqueue a subscription notice to the payer |
| `lemely/core/subscription_rules.py` | Create | Pure: periods, amounts, seat capacity, month bounds, charge checks |
| `lemely/db/subscription_repo.py` | Create | `SubscriptionService`, paid handlers, plan sync |
| `lemely/db/seat_allowance_repo.py` | Create | Monthly and on-claim seat allowances |
| `lemely/db/teacher_team_repo.py` | Modify | Call `grant_seat_allowance_on_claim` after a seat claim |
| `lemely/web/subscription_deps.py` | Create | `SubscriptionDeps` bundle (sessionmaker, client, settings) |
| `lemely/web/schemas_subscriptions.py` | Create | DTOs |
| `lemely/web/routers/billing.py`, `lemely/web/routers/paymob_webhooks.py`, `lemely/web/deps_billing.py`, `lemely/web/deps.py` (`get_sweeper`) | Modify | Routes and dependencies |
| `lemely/web/subscription_jobs.py` | Create | Sweeper job functions |
| `lemely/db/billing_summary.py` | Create | Read model behind `GET /api/billing/summary` (index R3) |
| `lemely/web/scheduled_notifications.py` | Modify | Register the five jobs |
| `tests/subscription_fixtures.py` | Create | Throwaway DB, Paymob fake, seed helpers |

---

### Task 1: Migration 0055, models, `billing` notification type, manual activation guard

**Files:**
- Create: `lemely/db/migrations/versions/0055_subscription_periods.py`
- Modify: `lemely/db/models/billing.py`, `lemely/db/models/usage.py`, `lemely/db/models/__init__.py`, `lemely/db/models/enums.py`, `lemely/db/models/ops.py`, `lemely/db/notification_repo.py`, `lemely/db/notification_prefs_repo.py`, `lemely/db/admin_repo.py`, `lemely/web/routers/admin.py`
- Test: `tests/test_migration_subscription_periods.py` (create), `tests/test_db_schema.py`, `tests/test_web_platform_admin.py` (modify)

**Interfaces:**
- Consumes: Phase 01 `usage_grants.subscription_period_id` (plain UUID column); Phase 02 `payments`, `SubscriptionStatus.pending_first_payment`/`past_due`, `LIVE_SUBSCRIPTION_STATUSES` (strings) and `uq_subscriptions_one_live_paid` (index R8: not recreated here); revision `0054_teacher_team`.
- Produces:
  - `lemely.db.models.billing.SubscriptionPeriod` (`id`, `subscription_id`, `period_start`, `period_end`, `payment_id | None`, timestamps).
  - `Subscription.paymob_amount_minor: int | None`, `Subscription.paymob_cancelled_at: datetime | None`.
  - `PLAN_LIVE_STATUSES: tuple[SubscriptionStatus, ...]` (`active`, `past_due`) in `lemely.db.models.billing`.
  - `NotificationType.billing`; preference field `billing` (index R7).
  - `lemely.db.admin_repo.SubscriptionConflictError(AdminError)` (application-level guard, since Phase 02's index ignores manual rows); `POST /api/admin/activations/{id}/activate` answers 409 with it.

- [ ] **Step 1: Write the failing migration test**

Create `tests/test_migration_subscription_periods.py`:

```python
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
from lemely.db.models.billing import PlanAudience, PlanTier, Subscription
from lemely.db.models.enums import Role, SubscriptionStatus
from lemely.db.models.usage import GrantKind, UsageGrant
from lemely.db.models.users import User
from tests.test_migration_tutoring_enums import current_revision, enum_labels, object_names

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.orm import Session, sessionmaker

import_all_models()

REVISION = "0055_subscription_periods"
DOWN_REVISION = "0054_teacher_team"
TABLE = "subscription_periods"
PHASE_02_LIVE_INDEX = "uq_subscriptions_one_live_paid"  # owned by 0053 (index R8)


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
        session.add(Subscription(id=sid, user_id=user, plan_tier_id=tier, status=status,
                                 payer_user_id=payer))
    return sid


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


def test_named_objects_present(migrated_sessionmaker: sessionmaker[Session]) -> None:
    with migrated_sessionmaker() as session:
        assert object_names(session, [TABLE]) == _orm_names()
        # 0055 leaves Phase 02's index alone (index R8).
        assert PHASE_02_LIVE_INDEX in object_names(session, ["subscriptions"])
        assert (
            "fk_usage_grants_subscription_period_id_subscription_periods"
            in object_names(session, ["usage_grants"])
        )


def test_period_order_and_uniqueness(migrated_sessionmaker: sessionmaker[Session]) -> None:
    sm = migrated_sessionmaker
    sid = _sub(sm, _user(sm), _tier(sm), SubscriptionStatus.active)
    start = datetime(2026, 11, 10, tzinfo=UTC)
    insert = sa.text(
        "INSERT INTO subscription_periods (subscription_id, period_start, period_end) "
        "VALUES (:s, :a, :b)"
    )
    with sm.begin() as session:
        session.execute(insert, {"s": sid, "a": start, "b": datetime(2026, 12, 10, tzinfo=UTC)})
    with pytest.raises(sa.exc.IntegrityError), sm.begin() as session:
        session.execute(insert, {"s": sid, "a": start, "b": datetime(2026, 12, 11, tzinfo=UTC)})
    with pytest.raises(sa.exc.IntegrityError), sm.begin() as session:
        session.execute(insert, {"s": sid, "a": datetime(2027, 1, 1, tzinfo=UTC), "b": start})


def test_usage_grant_period_fk_enforced(migrated_sessionmaker: sessionmaker[Session]) -> None:
    sm = migrated_sessionmaker
    user = _user(sm)
    with pytest.raises(sa.exc.IntegrityError), sm.begin() as session:
        session.add(
            UsageGrant(
                owner_user_id=user,
                kind=GrantKind.period_allowance,
                visible=False,
                priority=10,
                units=100,
                effective_at=datetime(2026, 11, 10, tzinfo=UTC),
                expires_at=None,
                idempotency_key="fk-probe",
                subscription_period_id=uuid.uuid4(),
            )
        )


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
        assert default == ("true", "NO")


def test_upgrade_downgrade_upgrade_round_trip(
    migrated_sessionmaker_with_downgrade: tuple[sessionmaker[Session], Callable[[str], None]],
) -> None:
    sm, downgrade_to = migrated_sessionmaker_with_downgrade
    downgrade_to(DOWN_REVISION)
    with sm() as session:
        assert current_revision(session) == DOWN_REVISION
        assert object_names(session, [TABLE]) == set()
        assert PHASE_02_LIVE_INDEX in object_names(session, ["subscriptions"])  # untouched
        columns = {
            row[0]
            for row in session.execute(
                sa.text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'subscriptions'"
                )
            )
        }
        assert {"paymob_amount_minor", "paymob_cancelled_at"}.isdisjoint(columns)

    # The fixture yields only a downgrade callable; it keeps LEMELY_DATABASE__URL pointed at the
    # throwaway database for the whole test, so command.upgrade migrates that database.
    command.upgrade(Config("alembic.ini"), "head")
    with sm() as session:
        assert object_names(session, [TABLE]) == _orm_names()
```

Add `from alembic import command` to the test module's imports.

- [ ] **Step 2: Add the table to the schema pin**

In `tests/test_db_schema.py`, add `"subscription_periods",` to `EXPECTED_TABLES` (keep the set
sorted the way it is). No head assertion needs moving: Phase 01 replaced the "is head" checks
with history checks (index R10).

Add one migration test that pins Phase 02's index filter as Phase 05 relies on it (append to
`tests/test_migration_subscription_periods.py`):

```python
def test_phase_02_index_ignores_manual_rows(migrated_sessionmaker: sessionmaker[Session]) -> None:
    """Paid rows collide; payer-less (manual) rows do not. Manual rows are guarded in admin_repo."""
    sm = migrated_sessionmaker
    user, tier = _user(sm), _tier(sm)
    _sub(sm, user, tier, SubscriptionStatus.active, payer=user)
    _sub(sm, user, tier, SubscriptionStatus.active, payer=None)  # manual: no collision
    with pytest.raises(sa.exc.IntegrityError):
        _sub(sm, user, tier, SubscriptionStatus.past_due, payer=user)
```

Append to `tests/test_web_platform_admin.py` (add `SubscriptionConflictError` to the
`lemely.db.admin_repo` import; `_subscription` gains a `payer_id: uuid.UUID | None = None` keyword
passed as `payer_user_id=payer_id`):

```python
# ── Manual activation beside Paymob subscriptions (billing Phase 05) ─────────


@pytest.mark.parametrize(
    ("status", "paid"),
    [
        (SubscriptionStatus.active, True),
        (SubscriptionStatus.past_due, True),
        (SubscriptionStatus.pending_first_payment, True),
        (SubscriptionStatus.active, False),  # another complimentary plan
    ],
)
def test_activation_is_refused_while_the_user_has_a_live_subscription(
    pg_sessionmaker: sessionmaker[Session], status: SubscriptionStatus, paid: bool
) -> None:
    plan = _plan(pg_sessionmaker)
    user = _user(pg_sessionmaker, Role.student)
    _subscription(pg_sessionmaker, user, plan, status=status, payer_id=user if paid else None)
    queued = _subscription(pg_sessionmaker, user, plan)

    with pytest.raises(SubscriptionConflictError):
        PlatformAdminService(pg_sessionmaker).decide_activation(queued, activate=True, note="comp")

    with pg_sessionmaker() as session:
        row = session.get(Subscription, queued)
        assert row.status is SubscriptionStatus.inactive
        assert row.is_manually_activated is False


def test_activation_still_works_when_only_ended_subscriptions_exist(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    plan = _plan(pg_sessionmaker)
    user = _user(pg_sessionmaker, Role.student)
    _subscription(pg_sessionmaker, user, plan, status=SubscriptionStatus.expired, payer_id=user)
    queued = _subscription(pg_sessionmaker, user, plan)

    status = PlatformAdminService(pg_sessionmaker).decide_activation(queued, activate=True)

    assert status is SubscriptionStatus.active


def test_activation_route_answers_409_on_a_live_subscription(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    plan = _plan(pg_sessionmaker)
    user = _user(pg_sessionmaker, Role.student)
    _subscription(pg_sessionmaker, user, plan, status=SubscriptionStatus.past_due, payer_id=user)
    queued = _subscription(pg_sessionmaker, user, plan)

    for client in _client(pg_sessionmaker):
        response = client.post(f"/api/admin/activations/{queued}/activate", json={"note": "x"})
        assert response.status_code == 409
        assert "live subscription" in response.json()["detail"]
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest --no-cov tests/test_migration_subscription_periods.py tests/test_db_schema.py::test_all_expected_tables_registered tests/test_web_platform_admin.py -v`
Expected: FAIL — `ImportError: cannot import name 'SubscriptionPeriod'`, `KeyError: 'subscription_periods'`, `cannot import name 'SubscriptionConflictError'`.

- [ ] **Step 4: Write the migration**

Create `lemely/db/migrations/versions/0055_subscription_periods.py`:

```python
"""subscription periods: one row per paid period, Paymob amount and cancel stamps, billing notices

Revision ID: 0055_subscription_periods
Revises: 0054_teacher_team
Create Date: 2026-11-05 00:00:00.000000

Paymob billing spec §4.3, §5.1-§5.3 (Phase 05). Additive:

* ``subscription_periods``: one row per paid period. Unique ``(subscription_id, period_start)``
  so a period's allowance grant is issued once; ``payment_id`` unique, so one payment pays for at
  most one period. ``CASCADE`` with the subscription; ``RESTRICT`` against the payment.
* ``usage_grants.subscription_period_id`` gains its foreign key (the column exists since 0052).
* ``subscriptions.paymob_amount_minor`` (the renewal amount Lemely last set at Paymob) and
  ``subscriptions.paymob_cancelled_at`` (when the Paymob subscription was cancelled).
* The one-live-subscription index is ``uq_subscriptions_one_live_paid`` from 0053; this
  revision does not touch it.
* ``notificationtype`` gains ``billing``; ``notification_preferences`` gains ``billing`` (``NOT NULL
  DEFAULT true``) so ``test_notification_type_enum_matches_preference_columns`` keeps holding.

``downgrade`` deletes ``billing`` notifications first (older code cannot load them, precedent
0039), then drops the column, the two subscription columns, the foreign key and the table. The ``billing`` enum value stays: Postgres has no ``DROP VALUE`` (precedent 0044).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
# Kept to <=32 chars: alembic_version.version_num is varchar(32).
revision: str = "0055_subscription_periods"
down_revision: str | Sequence[str] | None = "0054_teacher_team"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GRANT_FK = "fk_usage_grants_subscription_period_id_subscription_periods"


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "subscription_periods",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("subscription_id", sa.UUID(), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payment_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "period_end > period_start", name=op.f("ck_subscription_periods_period_order")
        ),
        sa.ForeignKeyConstraint(
            ["subscription_id"],
            ["subscriptions.id"],
            name=op.f("fk_subscription_periods_subscription_id_subscriptions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["payment_id"],
            ["payments.id"],
            name=op.f("fk_subscription_periods_payment_id_payments"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_subscription_periods")),
        sa.UniqueConstraint(
            "subscription_id",
            "period_start",
            name=op.f("uq_subscription_periods_subscription_id_period_start"),
        ),
        sa.UniqueConstraint("payment_id", name=op.f("uq_subscription_periods_payment_id")),
    )
    op.create_foreign_key(
        op.f(GRANT_FK),
        "usage_grants",
        "subscription_periods",
        ["subscription_period_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.add_column("subscriptions", sa.Column("paymob_amount_minor", sa.BigInteger(), nullable=True))
    op.add_column(
        "subscriptions",
        sa.Column("paymob_cancelled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute("ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'billing'")
    op.add_column(
        "notification_preferences",
        sa.Column("billing", sa.Boolean(), server_default=sa.true(), nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema. The ``billing`` notificationtype value stays."""
    op.execute("DELETE FROM notifications WHERE type = 'billing'")
    op.drop_column("notification_preferences", "billing")
    op.drop_column("subscriptions", "paymob_cancelled_at")
    op.drop_column("subscriptions", "paymob_amount_minor")
    op.drop_constraint(op.f(GRANT_FK), "usage_grants", type_="foreignkey")
    op.drop_table("subscription_periods")
```

- [ ] **Step 5: Add the ORM declarations**

In `lemely/db/models/billing.py`:

- Add `from typing import Final` to the imports if missing.
- After Phase 02's `LIVE_SUBSCRIPTION_STATUSES` (keep it unchanged; it holds string values and
  backs `uq_subscriptions_one_live_paid`), add:

```python
#: The statuses in which a plan is in force: access, allowances, teacher seat allowances.
#: ``past_due`` is the 3-day grace after a failed renewal (spec §2.6). Enum members, unlike
#: ``LIVE_SUBSCRIPTION_STATUSES``, so Python comparisons against ``Subscription.status`` work.
PLAN_LIVE_STATUSES: Final = (SubscriptionStatus.active, SubscriptionStatus.past_due)
```

- Add to `Subscription` (after Phase 02's Paymob columns):

```python
    paymob_amount_minor: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
    """The renewal amount Lemely last set at Paymob: the first payment's amount, then each PUT.
    The next renewal charge must equal it (spec §6 mismatch rule)."""
    paymob_cancelled_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    """When the Paymob subscription was cancelled; ``None`` while Paymob may still charge."""
```

- Add the model after `Subscription`:

```python
class SubscriptionPeriod(TimestampMixin, Base):
    """One paid period of a :class:`Subscription` (spec §4.3).

    Unique ``(subscription_id, period_start)`` guarantees one allowance grant per period, so a
    duplicate renewal webhook is harmless. ``payment_id`` is unique: one payment pays for one
    period at most.
    """

    __tablename__ = "subscription_periods"
    __table_args__ = (
        sa.UniqueConstraint(
            "subscription_id",
            "period_start",
            name="uq_subscription_periods_subscription_id_period_start",
        ),
        sa.CheckConstraint("period_end > period_start", name="period_order"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    subscription_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("subscriptions.id", ondelete="CASCADE"),
        nullable=False,
    )
    period_start: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    payment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("payments.id", ondelete="RESTRICT"),
        nullable=True,
        unique=True,
    )
```

- Add `"PLAN_LIVE_STATUSES"` and `"SubscriptionPeriod"` to `__all__`.

In `lemely/db/models/usage.py`, give `UsageGrant.subscription_period_id` its foreign key:

```python
    subscription_period_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("subscription_periods.id", ondelete="RESTRICT"),
        nullable=True,
    )
```

In `lemely/db/models/__init__.py`, add `SubscriptionPeriod` to the `lemely.db.models.billing`
import and to `__all__`.

- [ ] **Step 6: Add the `billing` notification type**

`lemely/db/models/enums.py`, at the end of `NotificationType` (and add one sentence to its
docstring: "``billing`` is the payment notices' type (migration ``0055``); it has a preference column
but no user toggle."):

```python
    billing = "billing"
```

`lemely/db/models/ops.py`, after the `tutoring_report` column of `NotificationPreference`:

```python
    # Payment notices (migration 0055, Paymob billing). Not user-switchable: no /api/me toggle
    # and no NotificationPreferencesService.set keyword write it.
    billing: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, server_default=sa.true())
```

`lemely/db/notification_repo.py`, in `PREFERENCE_FIELD_FOR_TYPE`:

```python
    NotificationType.billing: "billing",
```

`lemely/db/notification_prefs_repo.py`: add `billing: bool = True` to `NotificationPreferencesRow`
after `tutoring_report`, and `billing=model.billing,` to `_row_from_model` after
`tutoring_report=model.tutoring_report,`. Do not add a `set()` keyword.

- [ ] **Step 7: Refuse a manual activation that would make a second live subscription**

Phase 02's `uq_subscriptions_one_live_paid` ignores payer-less (manual) rows, so the database will
not stop an admin from activating a complimentary plan beside a live paid one. The guard is in
application code. In `lemely/db/admin_repo.py`, import `LIVE_SUBSCRIPTION_STATUSES` from
`lemely.db.models.billing` and, after `SubscriptionAlreadyDecidedError`, add:

```python
class SubscriptionConflictError(AdminError):
    """Activating would give the user a second live subscription.

    One live subscription per user (spec §4.3). Phase 02's partial unique index covers paid rows
    only (``payer_user_id IS NOT NULL``), so this check covers manual activation.
    """
```

In `decide_activation`, replace the `if activate:` branch with:

```python
            if activate:
                other_live = session.scalar(
                    select(Subscription.id).where(
                        Subscription.user_id == subscription.user_id,
                        Subscription.id != subscription.id,
                        Subscription.status.in_(LIVE_SUBSCRIPTION_STATUSES),
                    )
                )
                if other_live is not None:
                    raise SubscriptionConflictError(
                        "This user already has a live subscription; end it before activating"
                        " another."
                    )
                subscription.status = SubscriptionStatus.active
                subscription.is_manually_activated = True
                subscription.activated_at = moment
```

Add `SubscriptionConflictError:` to the docstring's `Raises:` list and to `__all__` if the module
has one.

In `lemely/web/routers/admin.py`, import `SubscriptionConflictError` and add to `_decide`:

```python
    except SubscriptionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest --no-cov tests/test_migration_subscription_periods.py tests/test_db_schema.py tests/test_web_platform_admin.py tests/test_notification_repo.py tests/test_notification_prefs_repo.py tests/test_web_notify.py tests/test_web_me.py tests/test_me_router.py -v`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add lemely/db/migrations/versions/0055_subscription_periods.py lemely/db/models/billing.py \
  lemely/db/models/usage.py lemely/db/models/__init__.py lemely/db/models/enums.py \
  lemely/db/models/ops.py lemely/db/notification_repo.py lemely/db/notification_prefs_repo.py \
  lemely/db/admin_repo.py lemely/web/routers/admin.py tests/test_migration_subscription_periods.py \
  tests/test_db_schema.py tests/test_web_platform_admin.py
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files
git commit -S -m "feat(billing): subscription periods, billing notices type, manual activation guard" -- \
  lemely/db/migrations/versions/0055_subscription_periods.py lemely/db/models/billing.py \
  lemely/db/models/usage.py lemely/db/models/__init__.py lemely/db/models/enums.py \
  lemely/db/models/ops.py lemely/db/notification_repo.py lemely/db/notification_prefs_repo.py \
  lemely/db/admin_repo.py lemely/web/routers/admin.py tests/test_migration_subscription_periods.py \
  tests/test_db_schema.py tests/test_web_platform_admin.py
```

---

### Task 2: Billing email template and notice helper

**Files:**
- Modify: `lemely/io/notify_email.py`
- Create: `lemely/db/billing_notices.py`
- Test: `tests/test_notify_email.py` (modify), `tests/test_billing_notices.py` (create)

**Interfaces:**
- Consumes: `NotificationType.billing` (Task 1); `lemely.db.email_outbox_repo.enqueue_in_session`.
- Produces:
  - Template `subscription_notice` with context `{subscription_id: UUID, notice: "renewed" | "payment_failed" | "expired" | "cancelled", effective_at: aware datetime}`; `BILLING_EMAIL_TEMPLATES: frozenset[str]` in `lemely.io.notify_email`.
  - `lemely.db.billing_notices.SubscriptionNoticeKind` (the `Literal` above) and
    `enqueue_subscription_notice(session: Session, *, subscription: Subscription, notice: SubscriptionNoticeKind, effective_at: datetime) -> bool` (recipient is the payer; `False` when the subscription has no payer, the payer opted out, or the notice was already queued).

- [ ] **Step 1: Write the failing tests**

In `tests/test_notify_email.py`, add `BILLING_EMAIL_TEMPLATES` to the `lemely.io.notify_email`
import and change the first assertion of `test_templates_are_exactly_the_ones_the_spec_table_names`
to:

```python
    assert set(EMAIL_TEMPLATES) - BILLING_EMAIL_TEMPLATES == named
```

Append:

```python
# -- billing (Paymob billing Phase 05) -----------------------------------------

SUBSCRIPTION_ID = uuid.UUID("66666666-6666-4666-8666-666666666666")


def _notice(notice: str) -> dict[str, object]:
    return {
        "subscription_id": str(SUBSCRIPTION_ID),
        "notice": notice,
        "effective_at": "2026-12-10T09:00:00+00:00",
    }


def test_billing_templates_are_disjoint_from_the_tutoring_spec() -> None:
    assert BILLING_EMAIL_TEMPLATES == {"subscription_notice"}
    assert BILLING_EMAIL_TEMPLATES <= set(EMAIL_TEMPLATES)
    assert EMAIL_TEMPLATES["subscription_notice"].notification_type.value == "billing"  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("notice", "words"),
    [
        ("renewed", "renewed"),
        ("payment_failed", "could not take"),
        ("expired", "ended"),
        ("cancelled", "cancelled"),
    ],
)
def test_subscription_notice_renders_each_notice(notice: str, words: str) -> None:
    subject, html_body, text = render_email(
        "subscription_notice", _notice(notice), app_base_url=BASE_URL
    )
    assert subject == "Your Lemely plan"
    assert words in text
    assert "10 Dec 2026" in text  # Cairo date of the instant
    assert f"{BASE_URL}/billing" in html_body


def test_subscription_notice_rejects_extra_keys_and_unknown_notices() -> None:
    for extra in ("note", "email", "amount", "plan_name"):
        with pytest.raises(InvalidEmailContext):
            validate_context("subscription_notice", {**_notice("renewed"), extra: "x"})
    with pytest.raises(InvalidEmailContext):
        validate_context("subscription_notice", _notice("refunded"))
    with pytest.raises(InvalidEmailContext):
        validate_context(
            "subscription_notice", {**_notice("renewed"), "effective_at": "2026-12-10T09:00:00"}
        )  # naive instant refused
```

Create `tests/test_billing_notices.py`:

```python
"""Subscription notices go to the payer through the Resend outbox, once per event (Phase 05)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.db.base import Base
from lemely.db.billing_notices import enqueue_subscription_notice
from lemely.db.models import import_all_models
from lemely.db.models.billing import PlanAudience, PlanTier, Subscription
from lemely.db.models.enums import Role, SubscriptionStatus
from lemely.db.models.tutoring import EmailOutbox
from lemely.db.models.users import User
from lemely.db.notification_prefs_repo import NotificationPreferencesService
from lemely.runtime.config import DatabaseSettings

if TYPE_CHECKING:
    from collections.abc import Iterator

import_all_models()

WHEN = datetime(2026, 12, 10, 9, 0, tzinfo=UTC)


@pytest.fixture
def pg_sessionmaker() -> Iterator[sessionmaker[Session]]:
    """A throwaway database, dropped afterwards (mirrors ``test_web_platform_admin.py``)."""
    base_url = DatabaseSettings().url
    server_url = make_url(base_url).set(database="postgres")
    probe = create_engine(server_url)
    try:
        with probe.connect():
            pass
    except OperationalError:
        pytest.skip("local Postgres not reachable")
    finally:
        probe.dispose()
    admin = create_engine(server_url, isolation_level="AUTOCOMMIT")
    dbname = f"lemely_test_{uuid.uuid4().hex[:12]}"
    with admin.connect() as conn:
        conn.execute(sa.text(f'CREATE DATABASE "{dbname}"'))
    engine = create_engine(make_url(base_url).set(database=dbname))
    Base.metadata.create_all(engine)
    try:
        yield sessionmaker(bind=engine, expire_on_commit=False, future=True)
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE)'))
        admin.dispose()


def seed_user(sm: sessionmaker[Session], role: Role) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(User(id=uid, email=f"{uid}@example.com", role=role, display_name="u"))
    return uid


def seed_tier(sm: sessionmaker[Session]) -> uuid.UUID:
    tid = uuid.uuid4()
    with sm.begin() as session:
        session.add(PlanTier(id=tid, code=f"t-{tid.hex[:8]}", name="Plan", price_minor=10_000,
                             currency="EGP", audience=PlanAudience.student))
    return tid


def seed_subscription(
    sm: sessionmaker[Session],
    *,
    user_id: uuid.UUID,
    tier_id: uuid.UUID,
    payer_id: uuid.UUID | None,
    status: SubscriptionStatus = SubscriptionStatus.active,
    is_manually_activated: bool = False,
) -> uuid.UUID:
    sid = uuid.uuid4()
    with sm.begin() as session:
        session.add(Subscription(id=sid, user_id=user_id, plan_tier_id=tier_id,
                                 payer_user_id=payer_id, status=status,
                                 is_manually_activated=is_manually_activated))
    return sid


def _outbox(sm: sessionmaker[Session]) -> list[EmailOutbox]:
    with sm() as session:
        return list(session.scalars(sa.select(EmailOutbox).order_by(EmailOutbox.created_at)))


def test_notice_goes_to_the_payer_not_the_beneficiary(pg_sessionmaker: sessionmaker[Session]) -> None:
    parent, child = seed_user(pg_sessionmaker, Role.parent), seed_user(pg_sessionmaker, Role.student)
    sid = seed_subscription(
        pg_sessionmaker, user_id=child, tier_id=seed_tier(pg_sessionmaker), payer_id=parent
    )
    with pg_sessionmaker.begin() as session:
        sub = session.get(Subscription, sid)
        assert enqueue_subscription_notice(
            session, subscription=sub, notice="renewed", effective_at=WHEN
        )
    rows = _outbox(pg_sessionmaker)
    assert [(r.recipient_user_id, r.template) for r in rows] == [(parent, "subscription_notice")]
    assert rows[0].context["notice"] == "renewed"


def test_the_same_notice_is_queued_once(pg_sessionmaker: sessionmaker[Session]) -> None:
    payer = seed_user(pg_sessionmaker, Role.student)
    sid = seed_subscription(
        pg_sessionmaker, user_id=payer, tier_id=seed_tier(pg_sessionmaker), payer_id=payer
    )
    with pg_sessionmaker.begin() as session:
        sub = session.get(Subscription, sid)
        first = enqueue_subscription_notice(
            session, subscription=sub, notice="expired", effective_at=WHEN
        )
        second = enqueue_subscription_notice(
            session, subscription=sub, notice="expired", effective_at=WHEN
        )
    assert (first, second) == (True, False)
    assert len(_outbox(pg_sessionmaker)) == 1


def test_manual_subscription_without_payer_queues_nothing(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    user = seed_user(pg_sessionmaker, Role.student)
    sid = seed_subscription(
        pg_sessionmaker,
        user_id=user,
        tier_id=seed_tier(pg_sessionmaker),
        payer_id=None,
        is_manually_activated=True,
    )
    with pg_sessionmaker.begin() as session:
        sub = session.get(Subscription, sid)
        assert not enqueue_subscription_notice(
            session, subscription=sub, notice="renewed", effective_at=WHEN
        )
    assert _outbox(pg_sessionmaker) == []


def test_opted_out_payer_gets_nothing(pg_sessionmaker: sessionmaker[Session]) -> None:
    payer = seed_user(pg_sessionmaker, Role.student)
    sid = seed_subscription(
        pg_sessionmaker,
        user_id=payer,
        tier_id=seed_tier(pg_sessionmaker),
        payer_id=payer,
        status=SubscriptionStatus.active,
    )
    with pg_sessionmaker.begin() as session:
        session.execute(
            sa.text(
                "INSERT INTO notification_preferences (user_id, billing) VALUES (:u, false)"
            ),
            {"u": payer},
        )
    assert NotificationPreferencesService(pg_sessionmaker).get(payer).billing is False
    with pg_sessionmaker.begin() as session:
        sub = session.get(Subscription, sid)
        assert not enqueue_subscription_notice(
            session, subscription=sub, notice="renewed", effective_at=WHEN
        )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest --no-cov tests/test_notify_email.py tests/test_billing_notices.py -v`
Expected: FAIL — `cannot import name 'BILLING_EMAIL_TEMPLATES'`, `No module named 'lemely.db.billing_notices'`.

- [ ] **Step 3: Add the template**

In `lemely/io/notify_email.py`, after `ClassJoinedTutor`:

```python
class SubscriptionNotice(EmailContext):
    """A subscription event the payer must hear about (Paymob billing spec §2.6, §5.2).

    No amount, plan name or card detail travels in the mail: the screen behind the link shows
    them to a signed-in payer.
    """

    template: ClassVar[str] = "subscription_notice"
    notification_type: ClassVar[NotificationType] = NotificationType.billing
    subject: ClassVar[str] = "Your Lemely plan"
    button: ClassVar[str] = "Open billing"

    subscription_id: uuid.UUID
    notice: Literal["renewed", "payment_failed", "expired", "cancelled"]
    effective_at: AwareDatetime

    _LEADS: ClassVar[dict[str, str]] = {
        "renewed": "Your Lemely plan renewed. The new period ends on {date}.",
        "payment_failed": (
            "We could not take your plan payment. Paymob will retry, and your plan stays on"
            " until {date}."
        ),
        "expired": "Your Lemely plan ended on {date} because the renewal payment did not go through.",
        "cancelled": "Your Lemely plan was cancelled and ended on {date}.",
    }

    def lead(self) -> str:
        local = self.effective_at.astimezone(ZoneInfo(DEFAULT_TUTOR_ZONE))
        return self._LEADS[self.notice].format(date=local.strftime("%d %b %Y"))

    def detail(self) -> str | None:
        return None

    def path(self) -> str:
        return "/billing"
```

Add `SubscriptionNotice,` at the end of `_TEMPLATE_CLASSES`, then after `EMAIL_TEMPLATES`:

```python
#: Templates outside the tutoring spec's §b.4 table (Paymob billing).
BILLING_EMAIL_TEMPLATES: Final[frozenset[str]] = frozenset({SubscriptionNotice.template})
```

Add `"BILLING_EMAIL_TEMPLATES"` and `"SubscriptionNotice"` to `__all__`.

- [ ] **Step 4: Add the helper**

Create `lemely/db/billing_notices.py`:

```python
"""Subscription notices through the transactional email outbox (Paymob billing spec §3 Jobs).

The payer hears about renewals, failed renewals, expiry and cancellation. The beneficiary (a
child, when a parent pays) sees the plan in the app instead. The row is written in the caller's
transaction, so the notice commits or rolls back with the state change it describes.
"""

from __future__ import annotations

from datetime import UTC
from typing import TYPE_CHECKING, Literal

from lemely.db.email_outbox_repo import enqueue_in_session

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.orm import Session

    from lemely.db.models.billing import Subscription

SubscriptionNoticeKind = Literal["renewed", "payment_failed", "expired", "cancelled"]


def enqueue_subscription_notice(
    session: Session,
    *,
    subscription: Subscription,
    notice: SubscriptionNoticeKind,
    effective_at: datetime,
) -> bool:
    """Queue one notice to the payer. ``True`` when a row was written.

    ``False`` when the subscription has no payer (a manual activation), the payer switched
    billing notices off, or this notice for this instant is already queued.
    """
    if subscription.payer_user_id is None:
        return False
    instant = effective_at.astimezone(UTC)
    return enqueue_in_session(
        session,
        recipient_user_id=subscription.payer_user_id,
        template="subscription_notice",
        context={
            "subscription_id": subscription.id,
            "notice": notice,
            "effective_at": instant,
        },
        dedupe_key=f"subscription:{subscription.id}:{notice}:{instant:%Y%m%dT%H%M%S}",
    )


__all__ = ["SubscriptionNoticeKind", "enqueue_subscription_notice"]
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest --no-cov tests/test_notify_email.py tests/test_billing_notices.py tests/test_email_outbox_repo.py tests/test_tutoring_email.py tests/architecture/ -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add lemely/io/notify_email.py lemely/db/billing_notices.py tests/test_notify_email.py \
  tests/test_billing_notices.py
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files
git commit -S -m "feat(billing): subscription notice email through the outbox" -- \
  lemely/io/notify_email.py lemely/db/billing_notices.py tests/test_notify_email.py \
  tests/test_billing_notices.py
```

---

### Task 3: Subscription rules, test fixtures and Paymob plan sync

**Files:**
- Create: `lemely/core/subscription_rules.py`, `lemely/db/subscription_repo.py`, `tests/subscription_fixtures.py`, `tests/test_subscription_rules.py`, `tests/test_subscription_plan_sync.py`

**Interfaces:**
- Consumes: Phase 02 `PaymobClient.create_plan`, `PaymobSettings.moto_integration_id`, `.notification_base_url`; `PlanTier.paymob_plan_id`.
- Produces (`lemely.core.subscription_rules`):
  - `GRACE_PERIOD = timedelta(days=3)`, `STALE_CHECKOUT_AFTER = timedelta(hours=2)`, `MAX_EXTRA_SEATS_AT_CHECKOUT = 200`, `PERIOD_DAYS: Mapping[str, int]` (`monthly` 30, `yearly` 360).
  - `paymob_frequency(interval: str) -> int`, `period_end(start: datetime, interval: str) -> datetime`.
  - `subscription_amount_minor(*, price_minor: int, extra_seats: int, extra_seat_price_minor: int | None) -> int`.
  - `seat_capacity_for(*, included_seats: int | None, extra_seats: int) -> int`.
  - `calendar_month_bounds(now: datetime) -> tuple[datetime, datetime]` (UTC), `start_of_day(now: datetime) -> datetime`.
  - `is_successful_charge(txn: Mapping[str, object]) -> bool`, `parse_paymob_time(value: object) -> datetime | None`, `renewal_period_start(*, current_period_end: datetime | None, charged_at: datetime) -> datetime`.
- Produces (`lemely.db.subscription_repo`):
  - Errors: `SubscriptionError(Exception)` with `code: ClassVar[str]`; `PlanNotPurchasable` (`plan_not_purchasable`), `AlreadySubscribed` (`already_subscribed`), `NotLinkedParent` (`not_linked_parent`), `InvalidExtraSeats` (`invalid_extra_seats`), `SubscriptionNotFound` (`subscription_not_found`), `InvalidPlanChange` (`invalid_plan_change`), `SeatsInsufficient(in_use: int, capacity: int)` (`seats_insufficient`), `MalformedWebhook` (`malformed_webhook`).
  - `SUBSCRIPTION_WEBHOOK_PATH: str`, `subscription_webhook_url(settings: PaymobSettings) -> str`.
  - `sync_paymob_plan(session, client, settings, plan_tier_id: UUID, *, force_new: bool = False) -> int` (the linked Paymob plan id).
  - `class SubscriptionService: __init__(self, session: Session, client: PaymobClient, settings: PaymobSettings)`.
- Produces (`tests/subscription_fixtures.py`): `throwaway_database()`, `paymob_settings()`, `FakePaymobClient`, `seed_user`, `seed_tier`, `link_parent`, `seed_subscription`, `seed_first_payment`, `seed_seat`, `grants_of`, `seed_debt`, `subscription_webhook`, `charge`, `remote_subscription`, `HMAC_SECRET`, `T0`.

- [ ] **Step 1: Create the shared test fixtures**

Create `tests/subscription_fixtures.py`:

```python
"""Throwaway Postgres, a Paymob fake and seed helpers for the Phase 05 subscription tests.

Not a test module: test files import from it. The database is built with
``Base.metadata.create_all`` (like ``test_web_platform_admin.py``), which creates the partial
unique index because the ORM declares it. ``FakePaymobClient`` records every call so a test can
prove Paymob was, or was not, asked to do something.
"""

from __future__ import annotations

import hashlib
import hmac
import itertools
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from lemely.db.base import Base
from lemely.db.models import import_all_models
from lemely.db.models.billing import (
    Payment,
    PaymentPurpose,
    PaymentStatus,
    PlanAudience,
    PlanTier,
    Subscription,
)
from lemely.db.models.enums import PlanInterval, Role, SubscriptionStatus
from lemely.db.models.team import CapPeriod, TeacherMember, TeacherMemberKind, TeacherMemberStatus
from lemely.db.models.usage import UsageDebt, UsageGrant
from lemely.db.models.users import ParentChildLink, User
from lemely.io.paymob.client import PaymobError
from lemely.runtime.config import DatabaseSettings, PaymobSettings

if TYPE_CHECKING:
    from collections.abc import Iterator

import_all_models()

HMAC_SECRET = "test-hmac-secret"
T0 = datetime(2026, 11, 10, 9, 0, tzinfo=UTC)


def throwaway_database() -> Iterator[sessionmaker[Session]]:
    """Yield a sessionmaker on a fresh database; drop it afterwards. Skip without Postgres."""
    base_url = DatabaseSettings().url
    server_url = make_url(base_url).set(database="postgres")
    probe = create_engine(server_url)
    try:
        with probe.connect():
            pass
    except OperationalError:
        pytest.skip("local Postgres not reachable")
    finally:
        probe.dispose()
    admin = create_engine(server_url, isolation_level="AUTOCOMMIT")
    dbname = f"lemely_test_{uuid.uuid4().hex[:12]}"
    with admin.connect() as conn:
        conn.execute(sa.text(f'CREATE DATABASE "{dbname}"'))
    engine = create_engine(make_url(base_url).set(database=dbname))
    Base.metadata.create_all(engine)
    try:
        yield sessionmaker(bind=engine, expire_on_commit=False, future=True)
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE)'))
        admin.dispose()


def paymob_settings(**overrides: Any) -> PaymobSettings:
    values: dict[str, Any] = {
        "secret_key": "sk_test_x",
        "public_key": "egy_pk_test_x",
        "api_key": "api_x",
        "hmac_secret": HMAC_SECRET,
        "card_integration_id": 111,
        "moto_integration_id": 222,
        "notification_base_url": "https://api.lemely.test",
        "redirection_base_url": "https://app.lemely.test",
    }
    return PaymobSettings(**(values | overrides))


@dataclass
class FakePaymobClient:
    """Records calls; serves canned subscriptions and last transactions.

    ``failing`` holds method names that raise :class:`PaymobError`; ``fail_for`` holds Paymob
    subscription ids whose calls raise, so one subscription can fail while others succeed.
    """

    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    subscriptions: dict[int, dict[str, Any]] = field(default_factory=dict)
    last_transactions: dict[int, dict[str, Any]] = field(default_factory=dict)
    failing: set[str] = field(default_factory=set)
    fail_for: set[int] = field(default_factory=set)
    _ids: Iterator[int] = field(default_factory=lambda: itertools.count(9001))

    def _record(self, name: str, **kwargs: Any) -> None:
        self.calls.append((name, kwargs))
        if name in self.failing or kwargs.get("subscription_id") in self.fail_for:
            raise PaymobError(f"{name} failed (fake)")

    def names(self) -> list[str]:
        return [name for name, _ in self.calls]

    def create_intention(self, body: dict[str, Any]) -> dict[str, Any]:
        self._record("create_intention", body=body)
        n = next(self._ids)
        return {"id": f"pi_test_{n}", "client_secret": f"egy_csk_test_{n}", "intention_order_id": n}

    def create_plan(self, **kwargs: Any) -> dict[str, Any]:
        self._record("create_plan", **kwargs)
        return {"id": next(self._ids), **kwargs}

    def get_subscription(self, subscription_id: int) -> dict[str, Any]:
        self._record("get_subscription", subscription_id=subscription_id)
        return dict(self.subscriptions[subscription_id])

    def update_subscription(self, subscription_id: int, **kwargs: Any) -> dict[str, Any]:
        self._record("update_subscription", subscription_id=subscription_id, **kwargs)
        row = self.subscriptions.setdefault(subscription_id, {"id": subscription_id})
        row.update({k: v for k, v in kwargs.items() if v is not None})
        return dict(row)

    def cancel_subscription(self, subscription_id: int) -> dict[str, Any]:
        self._record("cancel_subscription", subscription_id=subscription_id)
        row = self.subscriptions.setdefault(subscription_id, {"id": subscription_id})
        row["state"] = "canceled"
        return dict(row)

    def last_transaction(self, subscription_id: int) -> dict[str, Any]:
        self._record("last_transaction", subscription_id=subscription_id)
        return dict(self.last_transactions[subscription_id])


def seed_user(sm: sessionmaker[Session], role: Role) -> uuid.UUID:
    uid = uuid.uuid4()
    with sm.begin() as session:
        session.add(
            User(id=uid, email=f"{uid}@example.com", role=role, display_name=f"{role.value} user")
        )
    return uid


def seed_tier(
    sm: sessionmaker[Session],
    *,
    audience: PlanAudience = PlanAudience.student,
    price_minor: int = 10_000,
    interval: PlanInterval | None = PlanInterval.monthly,
    allowance_units: int = 1_000,
    included_seats: int | None = None,
    seat_allowance_units: int | None = None,
    extra_seat_price_minor: int | None = None,
    paymob_plan_id: int | None = 5001,
    is_active: bool = True,
) -> uuid.UUID:
    tid = uuid.uuid4()
    with sm.begin() as session:
        session.add(
            PlanTier(
                id=tid,
                code=f"{audience.value}-{tid.hex[:8]}",
                name=f"{audience.value.title()} plan",
                price_minor=price_minor,
                currency="EGP",
                interval=interval,
                audience=audience,
                allowance_units=allowance_units,
                included_seats=included_seats,
                seat_allowance_units=seat_allowance_units,
                extra_seat_price_minor=extra_seat_price_minor,
                paymob_plan_id=paymob_plan_id,
                is_active=is_active,
            )
        )
    return tid


def link_parent(sm: sessionmaker[Session], parent_id: uuid.UUID, child_id: uuid.UUID) -> None:
    with sm.begin() as session:
        session.add(ParentChildLink(parent_id=parent_id, child_id=child_id))


def seed_subscription(
    sm: sessionmaker[Session],
    *,
    user_id: uuid.UUID,
    tier_id: uuid.UUID,
    payer_id: uuid.UUID | None = None,
    status: SubscriptionStatus = SubscriptionStatus.active,
    period_start: datetime | None = T0,
    period_end: datetime | None = T0 + timedelta(days=30),
    paymob_subscription_id: int | None = None,
    paymob_amount_minor: int | None = None,
    extra_seats: int = 0,
    cancel_at_period_end: bool = False,
    pending_plan_tier_id: uuid.UUID | None = None,
    grace_until: datetime | None = None,
    is_manually_activated: bool = False,
    paymob_cancelled_at: datetime | None = None,
) -> uuid.UUID:
    sid = uuid.uuid4()
    with sm.begin() as session:
        session.add(
            Subscription(
                id=sid,
                user_id=user_id,
                payer_user_id=payer_id,
                plan_tier_id=tier_id,
                status=status,
                current_period_start=period_start,
                current_period_end=period_end,
                paymob_subscription_id=paymob_subscription_id,
                paymob_amount_minor=paymob_amount_minor,
                extra_seats=extra_seats,
                cancel_at_period_end=cancel_at_period_end,
                pending_plan_tier_id=pending_plan_tier_id,
                grace_until=grace_until,
                is_manually_activated=is_manually_activated,
                paymob_cancelled_at=paymob_cancelled_at,
            )
        )
    return sid


def seed_first_payment(
    sm: sessionmaker[Session],
    *,
    subscription_id: uuid.UUID,
    amount_minor: int = 10_000,
    status: PaymentStatus = PaymentStatus.paid,
    paymob_txn_id: int | None = 777,
    paid_at: datetime | None = T0,
    created_at: datetime | None = None,
    seat_quantity: int = 0,
) -> uuid.UUID:
    pid = uuid.uuid4()
    with sm.begin() as session:
        sub = session.get(Subscription, subscription_id)
        payment = Payment(
            id=pid,
            special_reference=str(pid),
            payer_user_id=sub.payer_user_id,
            beneficiary_user_id=sub.user_id,
            purpose=PaymentPurpose.subscription_first,
            plan_tier_id=sub.plan_tier_id,
            subscription_id=sub.id,
            seat_quantity=seat_quantity,
            amount_minor=amount_minor,
            currency="EGP",
            status=status,
            paymob_txn_id=paymob_txn_id,
            paid_at=paid_at if status is PaymentStatus.paid else None,
        )
        if created_at is not None:
            payment.created_at = created_at
        session.add(payment)
    return pid


def seed_seat(
    sm: sessionmaker[Session],
    *,
    teacher_id: uuid.UUID,
    student_id: uuid.UUID,
    status: TeacherMemberStatus = TeacherMemberStatus.active,
    created_at: datetime | None = None,
    leaves_at: datetime | None = None,
) -> uuid.UUID:
    mid = uuid.uuid4()
    with sm.begin() as session:
        member = TeacherMember(
            id=mid,
            teacher_user_id=teacher_id,
            member_user_id=student_id,
            kind=TeacherMemberKind.student_seat,
            status=status,
            scope_subjects=[],
            scope_actions=[],
            cap_units=None,
            cap_period=CapPeriod.month,
            leaves_at=leaves_at,
        )
        if created_at is not None:
            member.created_at = created_at
        session.add(member)
    return mid


def grants_of(sm: sessionmaker[Session], owner_id: uuid.UUID) -> list[UsageGrant]:
    with sm() as session:
        return list(
            session.scalars(
                sa.select(UsageGrant)
                .where(UsageGrant.owner_user_id == owner_id)
                .order_by(UsageGrant.effective_at, UsageGrant.id)
            )
        )


def seed_debt(sm: sessionmaker[Session], owner_id: uuid.UUID, units: int) -> None:
    """Outstanding debt with no job (``usage_debts.job_id`` is nullable). ``UsageLedger.adjust``
    with negative units never creates debt (Phase 01), so tests seed the row directly."""
    with sm.begin() as session:
        session.add(UsageDebt(owner_user_id=owner_id, units=units, outstanding=units))


def subscription_webhook(
    trigger_type: str, paymob_id: int, *, request_id: str | None = None, secret: str = HMAC_SECRET
) -> dict[str, Any]:
    """A subscription callback body with a correct HMAC (research 02 §2.3)."""
    mac = hmac.new(
        secret.encode(), f"{trigger_type}for{paymob_id}".encode(), hashlib.sha512
    ).hexdigest()
    return {
        "paymob_request_id": request_id or str(uuid.uuid4()),
        "subscription_data": {"id": paymob_id, "state": "active", "amount_cents": 1},
        "trigger_type": trigger_type,
        "hmac": mac,
    }


def charge(
    txn_id: int,
    amount_cents: int,
    *,
    created_at: datetime = T0,
    success: bool = True,
    currency: str = "EGP",
) -> dict[str, Any]:
    """A ``GET subscriptions/{id}/last-transaction`` body (transaction object fields)."""
    return {
        "id": txn_id,
        "amount_cents": amount_cents,
        "currency": currency,
        "success": success,
        "pending": False,
        "is_voided": False,
        "is_refunded": False,
        "error_occured": False,
        "created_at": created_at.astimezone(UTC).replace(tzinfo=None).isoformat(),
    }


def remote_subscription(
    paymob_id: int,
    *,
    state: str = "active",
    amount_cents: int = 10_000,
    initial_transaction: int = 777,
) -> dict[str, Any]:
    """A ``GET subscriptions/{id}`` body (research 02 §6 field list)."""
    return {
        "id": paymob_id,
        "state": state,
        "amount_cents": amount_cents,
        "initial_transaction": initial_transaction,
        "frequency": 30,
        "next_billing": "2026-12-10",
    }
```

- [ ] **Step 2: Write the failing rule tests**

Create `tests/test_subscription_rules.py`:

```python
"""Pure subscription arithmetic (Phase 05). No database."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from lemely.core.subscription_rules import (
    GRACE_PERIOD,
    PERIOD_DAYS,
    calendar_month_bounds,
    is_successful_charge,
    parse_paymob_time,
    paymob_frequency,
    period_end,
    renewal_period_start,
    seat_capacity_for,
    start_of_day,
    subscription_amount_minor,
)

PAYMOB_FREQUENCIES = {7, 15, 30, 60, 90, 180, 360}


def test_period_days_are_paymob_frequencies() -> None:
    assert dict(PERIOD_DAYS) == {"monthly": 30, "yearly": 360}
    assert set(PERIOD_DAYS.values()) <= PAYMOB_FREQUENCIES
    assert GRACE_PERIOD == timedelta(days=3)


def test_period_end_adds_the_paymob_cycle() -> None:
    start = datetime(2026, 1, 31, 12, tzinfo=UTC)
    assert period_end(start, "monthly") == datetime(2026, 3, 2, 12, tzinfo=UTC)
    assert period_end(start, "yearly") == start + timedelta(days=360)
    with pytest.raises(ValueError, match="unknown plan interval"):
        paymob_frequency("weekly")


def test_amount_is_plan_plus_extra_seats() -> None:
    assert subscription_amount_minor(price_minor=10_000, extra_seats=0, extra_seat_price_minor=None) == 10_000
    assert subscription_amount_minor(price_minor=10_000, extra_seats=3, extra_seat_price_minor=2_500) == 17_500
    with pytest.raises(ValueError):
        subscription_amount_minor(price_minor=10_000, extra_seats=1, extra_seat_price_minor=None)
    with pytest.raises(ValueError):
        subscription_amount_minor(price_minor=10_000, extra_seats=-1, extra_seat_price_minor=100)


def test_seat_capacity() -> None:
    assert seat_capacity_for(included_seats=None, extra_seats=0) == 0
    assert seat_capacity_for(included_seats=10, extra_seats=2) == 12


def test_calendar_month_bounds_are_utc_and_wrap_the_year() -> None:
    assert calendar_month_bounds(datetime(2026, 11, 21, 15, tzinfo=UTC)) == (
        datetime(2026, 11, 1, tzinfo=UTC),
        datetime(2026, 12, 1, tzinfo=UTC),
    )
    assert calendar_month_bounds(datetime(2026, 12, 31, 23, 59, tzinfo=UTC))[1] == datetime(
        2027, 1, 1, tzinfo=UTC
    )
    cairo_midnight = datetime(2026, 12, 1, 0, 30, tzinfo=timezone(timedelta(hours=2)))
    assert calendar_month_bounds(cairo_midnight)[0] == datetime(2026, 11, 1, tzinfo=UTC)
    with pytest.raises(ValueError):
        calendar_month_bounds(datetime(2026, 11, 21))  # naive refused
    assert start_of_day(datetime(2026, 11, 21, 15, 7, tzinfo=UTC)) == datetime(2026, 11, 21, tzinfo=UTC)


def test_is_successful_charge_requires_success_and_no_failure_flag() -> None:
    good = {"success": True, "pending": False, "is_voided": False, "is_refunded": False, "error_occured": False}
    assert is_successful_charge(good)
    assert is_successful_charge({"success": True})  # absent flags read as false
    for flag in ("pending", "is_voided", "is_refunded", "error_occured"):
        assert not is_successful_charge({**good, flag: True})
    assert not is_successful_charge({**good, "success": False})
    assert not is_successful_charge({**good, "success": "true"})  # only a JSON true counts


def test_parse_paymob_time() -> None:
    assert parse_paymob_time("2026-11-18T13:42:08.456634") == datetime(
        2026, 11, 18, 13, 42, 8, 456634, tzinfo=UTC
    )
    assert parse_paymob_time("2026-11-18T13:42:08+02:00") == datetime(2026, 11, 18, 11, 42, 8, tzinfo=UTC)
    assert parse_paymob_time("not a time") is None
    assert parse_paymob_time(None) is None


def test_renewal_period_start_continues_on_time_and_restarts_late() -> None:
    end = datetime(2026, 12, 10, 9, tzinfo=UTC)
    early = end - timedelta(hours=8)  # Paymob bills on the next_billing date
    late = end + timedelta(days=2)  # after retries
    assert renewal_period_start(current_period_end=end, charged_at=early) == end
    assert renewal_period_start(current_period_end=end, charged_at=late) == late
    assert renewal_period_start(current_period_end=None, charged_at=late) == late
```

- [ ] **Step 3: Write the failing plan-sync tests**

Create `tests/test_subscription_plan_sync.py`:

```python
"""Admin plan tiers get a linked Paymob subscription plan (spec §4.1, §8 Catalogue)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from lemely.db.models.billing import PlanTier
from lemely.db.models.enums import PlanInterval
from lemely.db.subscription_repo import (
    SUBSCRIPTION_WEBHOOK_PATH,
    PlanNotPurchasable,
    sync_paymob_plan,
)
from tests.subscription_fixtures import (
    FakePaymobClient,
    paymob_settings,
    seed_tier,
    throwaway_database,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture
def pg_sessionmaker() -> Iterator[sessionmaker[Session]]:
    yield from throwaway_database()


@pytest.mark.parametrize(("interval", "frequency"), [(PlanInterval.monthly, 30), (PlanInterval.yearly, 360)])
def test_unlinked_tier_creates_and_links_a_plan(
    pg_sessionmaker: sessionmaker[Session], interval: PlanInterval, frequency: int
) -> None:
    tier_id = seed_tier(pg_sessionmaker, interval=interval, price_minor=12_000, paymob_plan_id=None)
    client = FakePaymobClient()
    with pg_sessionmaker.begin() as session:
        plan_id = sync_paymob_plan(session, client, paymob_settings(), tier_id)
    assert client.names() == ["create_plan"]
    sent = client.calls[0][1]
    assert sent["frequency_days"] == frequency
    assert sent["integration_id"] == 222  # the MOTO integration
    assert sent["amount_cents"] == 12_000
    assert sent["use_transaction_amount"] is True
    assert sent["webhook_url"] == "https://api.lemely.test" + SUBSCRIPTION_WEBHOOK_PATH
    with pg_sessionmaker() as session:
        assert session.get(PlanTier, tier_id).paymob_plan_id == plan_id


def test_linked_tier_is_left_alone_unless_forced(pg_sessionmaker: sessionmaker[Session]) -> None:
    tier_id = seed_tier(pg_sessionmaker, paymob_plan_id=4242)
    client = FakePaymobClient()
    with pg_sessionmaker.begin() as session:
        assert sync_paymob_plan(session, client, paymob_settings(), tier_id) == 4242
    assert client.calls == []
    with pg_sessionmaker.begin() as session:
        relinked = sync_paymob_plan(session, client, paymob_settings(), tier_id, force_new=True)
    assert relinked != 4242
    assert client.names() == ["create_plan"]


def test_tier_without_interval_cannot_sync(pg_sessionmaker: sessionmaker[Session]) -> None:
    tier_id = seed_tier(pg_sessionmaker, interval=None, paymob_plan_id=None)
    client = FakePaymobClient()
    with pytest.raises(PlanNotPurchasable), pg_sessionmaker.begin() as session:
        sync_paymob_plan(session, client, paymob_settings(), tier_id)
    assert client.calls == []
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest --no-cov tests/test_subscription_rules.py tests/test_subscription_plan_sync.py -v`
Expected: FAIL — `No module named 'lemely.core.subscription_rules'`, `No module named 'lemely.db.subscription_repo'`.

- [ ] **Step 5: Write the rules module**

Create `lemely/core/subscription_rules.py`:

```python
"""Pure subscription arithmetic: periods, amounts, seat capacity, month bounds, charge checks.

Paymob billing spec §2.6, §5.2-§5.4, §5.9. No database and no I/O. Intervals are the string
values of ``lemely.db.models.enums.PlanInterval`` (``monthly`` / ``yearly``): ``lemely.core``
never imports ``lemely.db``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Mapping

#: Access continues this long after a failed renewal while Paymob retries (spec §2.6).
GRACE_PERIOD: Final = timedelta(days=3)

#: A first-payment checkout older than this can be replaced by a new one. Paymob intentions
#: expire after 3600 s (spec §5.1 step 2); the second hour absorbs a late callback.
STALE_CHECKOUT_AFTER: Final = timedelta(hours=2)

#: Upper bound on extra seats bought with the first checkout.
MAX_EXTRA_SEATS_AT_CHECKOUT: Final = 200

#: Days per period. Paymob plans accept only 7/15/30/60/90/180/360-day frequencies
#: (research 02 §6), so a month is 30 days and a year 360, and Lemely's period matches the
#: Paymob billing cycle exactly.
PERIOD_DAYS: Final[Mapping[str, int]] = MappingProxyType({"monthly": 30, "yearly": 360})

_FAILURE_FLAGS: Final = ("pending", "is_voided", "is_refunded", "error_occured")


def paymob_frequency(interval: str) -> int:
    """The Paymob plan ``frequency`` (days) for a plan interval."""
    try:
        return PERIOD_DAYS[interval]
    except KeyError as exc:
        raise ValueError(f"unknown plan interval {interval!r}") from exc


def period_end(start: datetime, interval: str) -> datetime:
    """End of the period that starts at ``start``."""
    return start + timedelta(days=paymob_frequency(interval))


def subscription_amount_minor(
    *, price_minor: int, extra_seats: int, extra_seat_price_minor: int | None
) -> int:
    """Plan price plus extra seats, in minor units (spec §5.1 step 1)."""
    if extra_seats < 0:
        raise ValueError("extra_seats must be >= 0")
    if extra_seats and extra_seat_price_minor is None:
        raise ValueError("this tier has no extra seat price")
    return price_minor + extra_seats * (extra_seat_price_minor or 0)


def seat_capacity_for(*, included_seats: int | None, extra_seats: int) -> int:
    """Seats a teacher subscription holds: included plus extra (spec §4.4)."""
    return (included_seats or 0) + extra_seats


def calendar_month_bounds(now: datetime) -> tuple[datetime, datetime]:
    """``[start, end)`` of the UTC calendar month containing ``now`` (seat allowances, §5.9)."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    start = now.astimezone(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end


def start_of_day(now: datetime) -> datetime:
    """Midnight UTC of ``now``'s day; prorating from it counts today as a day left."""
    return now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


def is_successful_charge(txn: Mapping[str, object]) -> bool:
    """Paid iff ``success`` is JSON true and no failure flag is set (research 02 §3)."""
    return txn.get("success") is True and not any(txn.get(flag) for flag in _FAILURE_FLAGS)


def parse_paymob_time(value: object) -> datetime | None:
    """Parse a Paymob timestamp; a naive one is read as UTC. ``None`` when unparseable."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def renewal_period_start(*, current_period_end: datetime | None, charged_at: datetime) -> datetime:
    """Start of the period a successful renewal pays for.

    Paymob bills on the ``next_billing`` date, so an on-time charge can land hours before the
    period ends; it continues the current period with no gap and no overlap. A late charge
    (after retries) starts the new period at the charge.
    """
    if current_period_end is None:
        return charged_at
    return max(current_period_end, charged_at)


__all__ = [
    "GRACE_PERIOD",
    "MAX_EXTRA_SEATS_AT_CHECKOUT",
    "PERIOD_DAYS",
    "STALE_CHECKOUT_AFTER",
    "calendar_month_bounds",
    "is_successful_charge",
    "parse_paymob_time",
    "paymob_frequency",
    "period_end",
    "renewal_period_start",
    "seat_capacity_for",
    "start_of_day",
    "subscription_amount_minor",
]
```

- [ ] **Step 6: Create the repository with errors, plan sync and the service shell**

Create `lemely/db/subscription_repo.py`:

```python
"""Subscriptions on Paymob: checkout, first payment, renewal, grace, plan changes, drift.

Paymob billing spec §2.6, §4.3, §5.1-§5.3, §6 (Phase 05).

* Paymob's subscriptions module charges renewals (spec §3 approach Y). Lemely never trusts a
  subscription webhook's body: the HMAC covers only ``trigger_type`` and the id, so state and
  amounts are re-fetched (``GET subscriptions/{id}``, ``GET .../last-transaction``).
* Every paid period is one ``subscription_periods`` row and one ``period_allowance`` grant,
  issued through :meth:`UsageLedger.issue_grant`, which repays the owner's debt first (§5.8).
* Webhook and checkout methods leave the commit to the caller. Sweep methods
  (``expire_overdue``, ``apply_period_end_changes``, ``check_drift``) commit after each
  subscription, so one Paymob failure cannot undo another subscription's change.
* Subscription rows are always read ``FOR UPDATE`` before a change; ``version`` is advanced on
  every change for readers that compare it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Final

import structlog

from lemely.core.subscription_rules import paymob_frequency
from lemely.db.billing_repo import BillingService
from lemely.db.models.billing import PlanTier

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.orm import Session

    from lemely.io.paymob.client import PaymobClient
    from lemely.runtime.config import PaymobSettings

log = structlog.get_logger(__name__)

#: Path of the subscription webhook route (``lemely/web/routers/paymob_webhooks.py``, prefix
#: ``/api/webhooks/paymob``; the Cloudflare Worker proxies only ``/api/*``).
SUBSCRIPTION_WEBHOOK_PATH: Final = "/api/webhooks/paymob/subscription"


class SubscriptionError(Exception):
    """Base class; ``code`` is the machine-readable reason the API returns."""

    code: ClassVar[str] = "subscription_error"


class PlanNotPurchasable(SubscriptionError):
    code: ClassVar[str] = "plan_not_purchasable"


class AlreadySubscribed(SubscriptionError):
    code: ClassVar[str] = "already_subscribed"


class NotLinkedParent(SubscriptionError):
    code: ClassVar[str] = "not_linked_parent"


class InvalidExtraSeats(SubscriptionError):
    code: ClassVar[str] = "invalid_extra_seats"


class SubscriptionNotFound(SubscriptionError):
    code: ClassVar[str] = "subscription_not_found"


class InvalidPlanChange(SubscriptionError):
    code: ClassVar[str] = "invalid_plan_change"


class SeatsInsufficient(SubscriptionError):
    """A teacher plan change would leave fewer seats than seated students (spec §2.6)."""

    code: ClassVar[str] = "seats_insufficient"

    def __init__(self, *, in_use: int, capacity: int) -> None:
        super().__init__(f"{in_use} seats are in use but the plan would hold {capacity}")
        self.in_use = in_use
        self.capacity = capacity


class MalformedWebhook(SubscriptionError):
    code: ClassVar[str] = "malformed_webhook"


class DowngradeUnavailable(SubscriptionError):
    """Paymob cannot lower this subscription's amount (``subscription_amount_updatable=False``),
    so a downgrade would keep renewing at the old price. Same style as Phase 06's
    ``upgrade_unavailable``."""

    code: ClassVar[str] = "downgrade_unavailable"


def subscription_webhook_url(settings: PaymobSettings) -> str:
    """The ``webhook_url`` Paymob plans post subscription callbacks to."""
    return f"{settings.notification_base_url.rstrip('/')}{SUBSCRIPTION_WEBHOOK_PATH}"


def sync_paymob_plan(
    session: Session,
    client: PaymobClient,
    settings: PaymobSettings,
    plan_tier_id: uuid.UUID,
    *,
    force_new: bool = False,
) -> int:
    """Create the tier's Paymob subscription plan if it has none (or ``force_new``); link it.

    Plans use the MOTO integration (research 02 §6) and ``use_transaction_amount=true``, so extra
    seats bought at the first checkout are part of every renewal. ``force_new`` re-links a tier
    after an admin changes its price or interval; existing subscriptions keep their plan.

    Owned by Phase 05 with this exact signature (index R9). Phase 07 calls it from the admin
    catalogue and adds its synced-price and synced-frequency stamps (0057 columns) inside this
    function, right after ``tier.paymob_plan_id`` is set.

    Raises:
        PlanNotPurchasable: unknown tier, or a tier with no interval.
    """
    tier = session.get(PlanTier, plan_tier_id, with_for_update=True)
    if tier is None:
        raise PlanNotPurchasable(f"unknown plan tier {plan_tier_id}")
    if tier.interval is None:
        raise PlanNotPurchasable("a plan tier without an interval cannot renew")
    if tier.paymob_plan_id is not None and not force_new:
        return tier.paymob_plan_id
    if settings.moto_integration_id is None:
        raise PlanNotPurchasable("Paymob subscriptions need a MOTO integration id")
    created = client.create_plan(
        name=tier.code,
        frequency_days=paymob_frequency(tier.interval.value),
        amount_cents=tier.price_minor,
        integration_id=settings.moto_integration_id,
        webhook_url=subscription_webhook_url(settings),
        use_transaction_amount=True,
    )
    tier.paymob_plan_id = int(created["id"])
    log.info("paymob_plan_linked", plan_tier_id=str(tier.id), paymob_plan_id=tier.paymob_plan_id)
    return tier.paymob_plan_id


class SubscriptionService:
    """The subscription lifecycle, bound to one session (see the module docstring)."""

    def __init__(self, session: Session, client: PaymobClient, settings: PaymobSettings) -> None:
        self._session = session
        self._client = client
        self._settings = settings
        self._billing = BillingService(session, client, settings)


__all__ = [
    "SUBSCRIPTION_WEBHOOK_PATH",
    "AlreadySubscribed",
    "InvalidExtraSeats",
    "InvalidPlanChange",
    "DowngradeUnavailable",
    "MalformedWebhook",
    "NotLinkedParent",
    "PlanNotPurchasable",
    "SeatsInsufficient",
    "SubscriptionError",
    "SubscriptionNotFound",
    "SubscriptionService",
    "subscription_webhook_url",
    "sync_paymob_plan",
]
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest --no-cov tests/test_subscription_rules.py tests/test_subscription_plan_sync.py tests/architecture/ -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add lemely/core/subscription_rules.py lemely/db/subscription_repo.py tests/subscription_fixtures.py \
  tests/test_subscription_rules.py tests/test_subscription_plan_sync.py
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files
git commit -S -m "feat(billing): subscription rules and Paymob plan sync" -- \
  lemely/core/subscription_rules.py lemely/db/subscription_repo.py tests/subscription_fixtures.py \
  tests/test_subscription_rules.py tests/test_subscription_plan_sync.py
```

---

### Task 4: Subscription checkout

**Files:**
- Modify: `lemely/db/subscription_repo.py` (and `lemely/db/billing_repo.py` only if the pre-flight found the billing-data builder private)
- Test: `tests/test_subscription_checkout.py` (create)

**Interfaces:**
- Consumes: `BillingService.create_intention_checkout(*, payment, items, billing_data, subscription_plan_id) -> CheckoutResult` (commits; raises `CheckoutUnavailable` after marking the payment `failed`); `billing_data_for(user) -> dict[str, str]`; Task 3 rules and errors; `LIVE_SUBSCRIPTION_STATUSES`.
- Produces:
  - `SubscriptionCheckout(subscription_id: UUID, payment_id: UUID, checkout_url: str)` (frozen dataclass).
  - `SubscriptionService.create_subscription_checkout(self, *, payer_user_id: UUID, plan_tier_id: UUID, beneficiary_user_id: UUID | None = None, extra_seats: int = 0, now: datetime) -> SubscriptionCheckout`. Raises `PlanNotPurchasable`, `NotLinkedParent`, `InvalidExtraSeats`, `AlreadySubscribed` before anything is committed; lets `CheckoutUnavailable` propagate (the pending subscription and its `failed` payment are then committed, and the next checkout supersedes them). The caller must not wrap the call in `session.begin()`, because Phase 02 commits inside it.
  - Module helpers used by later tasks: `_bump(subscription) -> None`, `_has_other_live(session, subscription) -> bool`, `_line_items(tier, extra_seats) -> list[dict[str, object]]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_subscription_checkout.py`:

```python
"""Subscription checkout: who may buy what, priced on the server (spec §5.1, §7)."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa

from lemely.db.models.billing import (
    Payment,
    PaymentPurpose,
    PaymentStatus,
    PlanAudience,
    PlanTier,
    Subscription,
)
from lemely.db.models.enums import Role, SubscriptionStatus
from lemely.db.billing_repo import CheckoutUnavailable
from lemely.db.subscription_repo import (
    AlreadySubscribed,
    InvalidExtraSeats,
    NotLinkedParent,
    PlanNotPurchasable,
    SubscriptionCheckout,
    SubscriptionService,
    _line_items,
)
from tests.subscription_fixtures import (
    T0,
    FakePaymobClient,
    link_parent,
    paymob_settings,
    seed_first_payment,
    seed_subscription,
    seed_tier,
    seed_user,
    throwaway_database,
)

if TYPE_CHECKING:
    import uuid
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture
def pg_sessionmaker() -> Iterator[sessionmaker[Session]]:
    yield from throwaway_database()


def _checkout(
    sm: sessionmaker[Session], client: FakePaymobClient | None = None, **kwargs: object
) -> SubscriptionCheckout:
    """No ``sm.begin()``: Phase 02's create_intention_checkout commits inside the call."""
    client = client or FakePaymobClient()
    with sm() as session:
        result = SubscriptionService(session, client, paymob_settings()).create_subscription_checkout(
            now=T0, **kwargs
        )
        session.commit()
        return result


def _subs_of(sm: sessionmaker[Session], user: uuid.UUID) -> list[Subscription]:
    with sm() as session:
        return list(session.scalars(sa.select(Subscription).where(Subscription.user_id == user)))


def test_student_buys_own_plan(pg_sessionmaker: sessionmaker[Session]) -> None:
    student = seed_user(pg_sessionmaker, Role.student)
    tier = seed_tier(pg_sessionmaker, price_minor=9_900, paymob_plan_id=5001)
    client = FakePaymobClient()

    result = _checkout(pg_sessionmaker, client, payer_user_id=student, plan_tier_id=tier)

    with pg_sessionmaker() as session:
        sub = session.get(Subscription, result.subscription_id)
        payment = session.get(Payment, result.payment_id)
        assert sub.status is SubscriptionStatus.pending_first_payment
        assert (sub.user_id, sub.payer_user_id, sub.extra_seats) == (student, student, 0)
        assert payment.purpose is PaymentPurpose.subscription_first
        assert payment.amount_minor == 9_900
        assert payment.special_reference == str(payment.id)
        assert payment.subscription_id == sub.id
    assert client.names() == ["create_intention"]
    assert result.checkout_url.startswith("https://")


def test_teacher_extra_seats_are_priced_on_the_server(pg_sessionmaker: sessionmaker[Session]) -> None:
    teacher = seed_user(pg_sessionmaker, Role.teacher)
    tier = seed_tier(
        pg_sessionmaker,
        audience=PlanAudience.teacher,
        price_minor=50_000,
        included_seats=10,
        extra_seat_price_minor=2_500,
    )
    result = _checkout(pg_sessionmaker, payer_user_id=teacher, plan_tier_id=tier, extra_seats=3)
    with pg_sessionmaker() as session:
        assert session.get(Payment, result.payment_id).amount_minor == 57_500
        assert session.get(Payment, result.payment_id).seat_quantity == 3
        assert session.get(Subscription, result.subscription_id).extra_seats == 3
        items = _line_items(session.get(PlanTier, tier), 3)
    assert sum(int(i["amount"]) * int(i["quantity"]) for i in items) == 57_500
    assert all(len(str(i["name"])) <= 50 for i in items)


def test_extra_seats_refused_for_students_and_out_of_range(pg_sessionmaker: sessionmaker[Session]) -> None:
    student = seed_user(pg_sessionmaker, Role.student)
    teacher = seed_user(pg_sessionmaker, Role.teacher)
    s_tier = seed_tier(pg_sessionmaker)
    t_tier = seed_tier(pg_sessionmaker, audience=PlanAudience.teacher, extra_seat_price_minor=100)
    no_price = seed_tier(pg_sessionmaker, audience=PlanAudience.teacher, extra_seat_price_minor=None)
    with pytest.raises(InvalidExtraSeats):
        _checkout(pg_sessionmaker, payer_user_id=student, plan_tier_id=s_tier, extra_seats=1)
    with pytest.raises(InvalidExtraSeats):
        _checkout(pg_sessionmaker, payer_user_id=teacher, plan_tier_id=t_tier, extra_seats=201)
    with pytest.raises(InvalidExtraSeats):
        _checkout(pg_sessionmaker, payer_user_id=teacher, plan_tier_id=t_tier, extra_seats=-1)
    with pytest.raises(InvalidExtraSeats):
        _checkout(pg_sessionmaker, payer_user_id=teacher, plan_tier_id=no_price, extra_seats=1)
    assert _subs_of(pg_sessionmaker, student) == [] and _subs_of(pg_sessionmaker, teacher) == []


def test_tier_must_be_active_synced_and_for_the_beneficiarys_role(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    teacher = seed_user(pg_sessionmaker, Role.teacher)
    student_tier = seed_tier(pg_sessionmaker, audience=PlanAudience.student)
    inactive = seed_tier(pg_sessionmaker, audience=PlanAudience.teacher, is_active=False)
    unsynced = seed_tier(pg_sessionmaker, audience=PlanAudience.teacher, paymob_plan_id=None)
    no_interval = seed_tier(pg_sessionmaker, audience=PlanAudience.teacher, interval=None)
    for tier in (student_tier, inactive, unsynced, no_interval):
        with pytest.raises(PlanNotPurchasable):
            _checkout(pg_sessionmaker, payer_user_id=teacher, plan_tier_id=tier)
    admin = seed_user(pg_sessionmaker, Role.school_admin)
    with pytest.raises(PlanNotPurchasable):
        _checkout(pg_sessionmaker, payer_user_id=admin, plan_tier_id=student_tier)


def test_parent_buys_for_a_linked_child_only(pg_sessionmaker: sessionmaker[Session]) -> None:
    parent = seed_user(pg_sessionmaker, Role.parent)
    child = seed_user(pg_sessionmaker, Role.student)
    stranger = seed_user(pg_sessionmaker, Role.student)
    link_parent(pg_sessionmaker, parent, child)
    tier = seed_tier(pg_sessionmaker)

    result = _checkout(pg_sessionmaker, payer_user_id=parent, plan_tier_id=tier, beneficiary_user_id=child)
    with pg_sessionmaker() as session:
        sub = session.get(Subscription, result.subscription_id)
        assert (sub.user_id, sub.payer_user_id) == (child, parent)

    with pytest.raises(NotLinkedParent):
        _checkout(pg_sessionmaker, payer_user_id=parent, plan_tier_id=tier, beneficiary_user_id=stranger)
    with pytest.raises(NotLinkedParent):
        _checkout(pg_sessionmaker, payer_user_id=parent, plan_tier_id=tier)
    with pytest.raises(NotLinkedParent):
        _checkout(pg_sessionmaker, payer_user_id=stranger, plan_tier_id=tier, beneficiary_user_id=child)


@pytest.mark.parametrize(
    "status", [SubscriptionStatus.active, SubscriptionStatus.past_due]
)
def test_a_live_subscription_blocks_a_second(
    pg_sessionmaker: sessionmaker[Session], status: SubscriptionStatus
) -> None:
    student = seed_user(pg_sessionmaker, Role.student)
    tier = seed_tier(pg_sessionmaker)
    seed_subscription(pg_sessionmaker, user_id=student, tier_id=tier, payer_id=student, status=status)
    with pytest.raises(AlreadySubscribed):
        _checkout(pg_sessionmaker, payer_user_id=student, plan_tier_id=tier)


def test_a_manual_activation_blocks_checkout(pg_sessionmaker: sessionmaker[Session]) -> None:
    student = seed_user(pg_sessionmaker, Role.student)
    tier = seed_tier(pg_sessionmaker)
    seed_subscription(pg_sessionmaker, user_id=student, tier_id=tier, is_manually_activated=True)
    with pytest.raises(AlreadySubscribed):
        _checkout(pg_sessionmaker, payer_user_id=student, plan_tier_id=tier)


def test_pending_checkout_rules(pg_sessionmaker: sessionmaker[Session]) -> None:
    parent = seed_user(pg_sessionmaker, Role.parent)
    child = seed_user(pg_sessionmaker, Role.student)
    link_parent(pg_sessionmaker, parent, child)
    tier = seed_tier(pg_sessionmaker)

    # A fresh pending checkout by another payer blocks.
    pending = seed_subscription(
        pg_sessionmaker, user_id=child, tier_id=tier, payer_id=parent,
        status=SubscriptionStatus.pending_first_payment, period_start=None, period_end=None,
    )
    seed_first_payment(pg_sessionmaker, subscription_id=pending, status=PaymentStatus.created,
                       paymob_txn_id=None, created_at=T0 - timedelta(minutes=10))
    with pytest.raises(AlreadySubscribed):
        _checkout(pg_sessionmaker, payer_user_id=child, plan_tier_id=tier)

    # The same payer may start again: the old checkout is superseded.
    again = _checkout(pg_sessionmaker, payer_user_id=parent, plan_tier_id=tier, beneficiary_user_id=child)
    with pg_sessionmaker() as session:
        assert session.get(Subscription, pending).status is SubscriptionStatus.expired
        assert session.get(Subscription, again.subscription_id).status is SubscriptionStatus.pending_first_payment


def test_stale_or_failed_pending_checkout_is_superseded(pg_sessionmaker: sessionmaker[Session]) -> None:
    parent = seed_user(pg_sessionmaker, Role.parent)
    child = seed_user(pg_sessionmaker, Role.student)
    link_parent(pg_sessionmaker, parent, child)
    tier = seed_tier(pg_sessionmaker)
    stale = seed_subscription(
        pg_sessionmaker, user_id=child, tier_id=tier, payer_id=parent,
        status=SubscriptionStatus.pending_first_payment, period_start=None, period_end=None,
    )
    seed_first_payment(pg_sessionmaker, subscription_id=stale, status=PaymentStatus.created,
                       paymob_txn_id=None, created_at=T0 - timedelta(hours=3))
    first = _checkout(pg_sessionmaker, payer_user_id=child, plan_tier_id=tier)
    with pg_sessionmaker() as session:
        assert session.get(Subscription, stale).status is SubscriptionStatus.expired

    # A failed first payment is superseded at once, whatever its age.
    with pg_sessionmaker.begin() as session:
        session.execute(
            sa.update(Payment).where(Payment.subscription_id == first.subscription_id)
            .values(status=PaymentStatus.failed)
        )
    second = _checkout(pg_sessionmaker, payer_user_id=parent, plan_tier_id=tier, beneficiary_user_id=child)
    assert second.subscription_id != first.subscription_id


def test_paid_but_unactivated_checkout_is_never_superseded(pg_sessionmaker: sessionmaker[Session]) -> None:
    student = seed_user(pg_sessionmaker, Role.student)
    tier = seed_tier(pg_sessionmaker)
    pending = seed_subscription(
        pg_sessionmaker, user_id=student, tier_id=tier, payer_id=student,
        status=SubscriptionStatus.pending_first_payment, period_start=None, period_end=None,
    )
    seed_first_payment(pg_sessionmaker, subscription_id=pending, status=PaymentStatus.paid)
    with pytest.raises(AlreadySubscribed):
        _checkout(pg_sessionmaker, payer_user_id=student, plan_tier_id=tier)


def test_paymob_outage_leaves_a_failed_checkout_the_next_one_replaces(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student = seed_user(pg_sessionmaker, Role.student)
    tier = seed_tier(pg_sessionmaker)
    with pytest.raises(CheckoutUnavailable):
        _checkout(pg_sessionmaker, FakePaymobClient(failing={"create_intention"}),
                  payer_user_id=student, plan_tier_id=tier)
    [failed] = _subs_of(pg_sessionmaker, student)
    with pg_sessionmaker() as session:
        payment = session.scalars(sa.select(Payment).where(Payment.subscription_id == failed.id)).one()
        assert payment.status is PaymentStatus.failed  # Phase 02 committed the row first (spec §6)

    retry = _checkout(pg_sessionmaker, payer_user_id=student, plan_tier_id=tier)
    with pg_sessionmaker() as session:
        assert session.get(Subscription, failed.id).status is SubscriptionStatus.expired
        assert session.get(Subscription, retry.subscription_id).status is SubscriptionStatus.pending_first_payment


def test_refusals_commit_nothing(pg_sessionmaker: sessionmaker[Session]) -> None:
    student = seed_user(pg_sessionmaker, Role.student)
    tier = seed_tier(pg_sessionmaker, is_active=False)
    client = FakePaymobClient()
    with pytest.raises(PlanNotPurchasable):
        _checkout(pg_sessionmaker, client, payer_user_id=student, plan_tier_id=tier)
    assert _subs_of(pg_sessionmaker, student) == []
    assert client.calls == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest --no-cov tests/test_subscription_checkout.py -v`
Expected: FAIL — `cannot import name '_line_items'`.

- [ ] **Step 3: Implement checkout**

In `lemely/db/subscription_repo.py`, extend the imports:

```python
import uuid
from dataclasses import dataclass
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from lemely.core.subscription_rules import (
    MAX_EXTRA_SEATS_AT_CHECKOUT,
    STALE_CHECKOUT_AFTER,
    paymob_frequency,
    subscription_amount_minor,
)
from lemely.db.billing_repo import BillingService, billing_data_for
from lemely.db.models.billing import (
    LIVE_SUBSCRIPTION_STATUSES,
    Payment,
    PaymentPurpose,
    PaymentStatus,
    PlanAudience,
    PlanTier,
    Subscription,
)
from lemely.db.models.enums import Role, SubscriptionStatus
from lemely.db.models.users import ParentChildLink, User
```

(`uuid` moves out of the `TYPE_CHECKING` block.) Add module constants and helpers above
`SubscriptionService`:

```python
_AUDIENCE_FOR_ROLE: Final = {Role.student: PlanAudience.student, Role.teacher: PlanAudience.teacher}
_FAILED_PAYMENT: Final = frozenset(
    {PaymentStatus.failed, PaymentStatus.failed_mismatch, PaymentStatus.voided}
)
_ITEM_NAME_MAX: Final = 50  # Paymob items[].name limit (research 01 §2.1)


@dataclass(frozen=True, slots=True)
class SubscriptionCheckout:
    """What the checkout route returns: the browser redirects to ``checkout_url``."""

    subscription_id: uuid.UUID
    payment_id: uuid.UUID
    checkout_url: str


def _bump(subscription: Subscription) -> None:
    """Advance ``version`` unless the mapper already does it (``version_id_col``)."""
    if sa.inspect(Subscription).version_id_col is None:
        subscription.version = (subscription.version or 0) + 1


def _has_other_live(session: Session, subscription: Subscription) -> bool:
    """Whether the beneficiary holds another live subscription."""
    return (
        session.scalar(
            select(Subscription.id).where(
                Subscription.user_id == subscription.user_id,
                Subscription.id != subscription.id,
                Subscription.status.in_(LIVE_SUBSCRIPTION_STATUSES),
            )
        )
        is not None
    )


def _line_items(tier: PlanTier, extra_seats: int) -> list[dict[str, object]]:
    """Intention line items; their total equals the payment amount (research 01 §2.1)."""
    items: list[dict[str, object]] = [
        {"name": tier.name[:_ITEM_NAME_MAX], "amount": tier.price_minor, "quantity": 1}
    ]
    if extra_seats:
        items.append(
            {
                "name": "Extra student seats",
                "amount": tier.extra_seat_price_minor,
                "quantity": extra_seats,
            }
        )
    return items
```

Add the methods to `SubscriptionService`:

```python
    def create_subscription_checkout(
        self,
        *,
        payer_user_id: uuid.UUID,
        plan_tier_id: uuid.UUID,
        beneficiary_user_id: uuid.UUID | None = None,
        extra_seats: int = 0,
        now: datetime,
    ) -> SubscriptionCheckout:
        """Start a card subscription (spec §5.1 steps 1-3).

        The price comes from ``plan_tiers`` only. A parent buys for a linked child; anyone else
        buys for themselves. The tier's audience must match the beneficiary's role.

        Raises:
            NotLinkedParent: a parent without a linked beneficiary, or a non-parent naming
                another account.
            PlanNotPurchasable: unknown, inactive, unsynced or interval-less tier, or one for
                another audience.
            InvalidExtraSeats: extra seats on a student tier, on a tier without a seat price,
                or outside ``0..MAX_EXTRA_SEATS_AT_CHECKOUT``.
            AlreadySubscribed: the beneficiary already has a live subscription.
        """
        session = self._session
        payer = session.get(User, payer_user_id)
        if payer is None:
            raise PlanNotPurchasable("unknown payer")
        if payer.role is Role.parent:
            if beneficiary_user_id is None or not self._is_linked_child(
                payer_user_id, beneficiary_user_id
            ):
                raise NotLinkedParent("a parent can only buy for a linked child")
            beneficiary_id = beneficiary_user_id
        elif beneficiary_user_id not in (None, payer_user_id):
            raise NotLinkedParent("only a linked parent may buy for another account")
        else:
            beneficiary_id = payer_user_id
        beneficiary = session.get(User, beneficiary_id)
        audience = _AUDIENCE_FOR_ROLE.get(beneficiary.role) if beneficiary is not None else None
        tier = session.get(PlanTier, plan_tier_id)
        if (
            tier is None
            or audience is None
            or not tier.is_active
            or tier.interval is None
            or tier.paymob_plan_id is None
            or tier.audience is not audience
        ):
            raise PlanNotPurchasable("this plan cannot be bought for this account")
        if not 0 <= extra_seats <= MAX_EXTRA_SEATS_AT_CHECKOUT or (
            extra_seats
            and (tier.audience is not PlanAudience.teacher or tier.extra_seat_price_minor is None)
        ):
            raise InvalidExtraSeats("extra seats are only for teacher plans with a seat price")

        self._retire_stale_checkout(beneficiary_id, payer_user_id, now=now)
        # Phase 02's uq_subscriptions_one_live_paid ignores payer-less (complimentary) rows, so a
        # live manual activation is refused here; the index still guards two racing paid checkouts.
        if (
            session.scalar(
                select(Subscription.id).where(
                    Subscription.user_id == beneficiary_id,
                    Subscription.status.in_(LIVE_SUBSCRIPTION_STATUSES),
                )
            )
            is not None
        ):
            raise AlreadySubscribed("this account already has a live subscription")
        amount = subscription_amount_minor(
            price_minor=tier.price_minor,
            extra_seats=extra_seats,
            extra_seat_price_minor=tier.extra_seat_price_minor,
        )
        subscription = Subscription(
            id=uuid.uuid4(),
            user_id=beneficiary_id,
            payer_user_id=payer_user_id,
            plan_tier_id=tier.id,
            status=SubscriptionStatus.pending_first_payment,
            extra_seats=extra_seats,
        )
        try:
            with session.begin_nested():
                session.add(subscription)
                session.flush()
        except IntegrityError as exc:
            raise AlreadySubscribed("this account already has a live subscription") from exc
        payment_id = uuid.uuid4()
        payment = Payment(
            id=payment_id,
            special_reference=str(payment_id),
            payer_user_id=payer_user_id,
            beneficiary_user_id=beneficiary_id,
            purpose=PaymentPurpose.subscription_first,
            plan_tier_id=tier.id,
            subscription_id=subscription.id,
            seat_quantity=extra_seats,
            amount_minor=amount,
            currency=tier.currency,
            status=PaymentStatus.created,
        )
        session.add(payment)
        session.flush()
        result = self._billing.create_intention_checkout(
            payment=payment,
            items=_line_items(tier, extra_seats),
            billing_data=billing_data_for(payer),
            subscription_plan_id=tier.paymob_plan_id,
        )
        log.info(
            "subscription_checkout_created",
            subscription_id=str(subscription.id),
            payment_id=str(payment_id),
            amount_minor=amount,
        )
        return SubscriptionCheckout(subscription.id, result.payment_id, result.checkout_url)

    def _is_linked_child(self, parent_id: uuid.UUID, child_id: uuid.UUID) -> bool:
        return (
            self._session.scalar(
                select(ParentChildLink.child_id).where(
                    ParentChildLink.parent_id == parent_id, ParentChildLink.child_id == child_id
                )
            )
            is not None
        )

    def _retire_stale_checkout(
        self, beneficiary_id: uuid.UUID, payer_id: uuid.UUID, *, now: datetime
    ) -> None:
        """Expire the beneficiary's unpaid pending checkout when a new one may replace it.

        Replaceable: its first payment failed, it is older than ``STALE_CHECKOUT_AFTER``, or the
        same payer is starting again. A paid one is never replaced (its handler is running).
        """
        pending = self._session.scalars(
            select(Subscription)
            .where(
                Subscription.user_id == beneficiary_id,
                Subscription.status == SubscriptionStatus.pending_first_payment,
            )
            .with_for_update()
        ).one_or_none()
        if pending is None:
            return
        first = self._session.scalars(
            select(Payment)
            .where(
                Payment.subscription_id == pending.id,
                Payment.purpose == PaymentPurpose.subscription_first,
            )
            .order_by(Payment.created_at.desc())
            .limit(1)
        ).one_or_none()
        if first is not None and first.status is PaymentStatus.paid:
            return
        replaceable = (
            first is None
            or first.status in _FAILED_PAYMENT
            or first.created_at <= now - STALE_CHECKOUT_AFTER
            or pending.payer_user_id == payer_id
        )
        if not replaceable:
            return
        pending.status = SubscriptionStatus.expired
        _bump(pending)
        self._session.flush()
        log.info("subscription_checkout_superseded", subscription_id=str(pending.id))
```

Add `"SubscriptionCheckout"` to `__all__`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest --no-cov tests/test_subscription_checkout.py tests/test_subscription_plan_sync.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add lemely/db/subscription_repo.py tests/test_subscription_checkout.py
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files
git commit -S -m "feat(billing): subscription checkout priced on the server" -- \
  lemely/db/subscription_repo.py tests/test_subscription_checkout.py
```

(Add `lemely/db/billing_repo.py` to both lists if the builder was renamed.)

---

### Task 5: First payment activates the subscription

**Files:**
- Modify: `lemely/db/subscription_repo.py`
- Test: `tests/test_subscription_first_payment.py` (create)

**Interfaces:**
- Consumes: Phase 02 `register_paid_handler`, `BillingService.apply_transaction_callback`, `PaymobEvent`, `PaymobEventKind.subscription`; Phase 01 `UsageLedger.issue_grant`; Task 2 `enqueue_subscription_notice`; Task 4 helpers.
- Produces:
  - `handle_subscription_first(session: Session, payment: Payment, obj: Mapping[str, Any]) -> None`, registered for `PaymentPurpose.subscription_first` at import.
  - Module helpers: `_issue_period_grant(session, subscription, tier, period, payment) -> UsageGrant | None`, `_link_stored_created_event(session, subscription, payment) -> None`.
  - Grant idempotency key `f"period:{period.id}"`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_subscription_first_payment.py`:

```python
"""A verified first payment activates the subscription, its period and its allowance (§5.1 step 4)."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from structlog.testing import capture_logs

from lemely.db.billing_repo import BillingService
from lemely.db.models.billing import (
    Payment,
    PaymentStatus,
    PaymobEvent,
    PaymobEventKind,
    Subscription,
    SubscriptionPeriod,
)
from lemely.db.models.enums import PlanInterval, Role, SubscriptionStatus
from lemely.db.models.usage import GrantKind
from lemely.db.subscription_repo import SubscriptionService, handle_subscription_first
from lemely.db.usage_ledger_repo import UsageLedger
from tests.subscription_fixtures import (
    T0,
    FakePaymobClient,
    grants_of,
    paymob_settings,
    seed_debt,
    seed_first_payment,
    seed_subscription,
    seed_tier,
    seed_user,
    throwaway_database,
)

if TYPE_CHECKING:
    import uuid
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture
def pg_sessionmaker() -> Iterator[sessionmaker[Session]]:
    yield from throwaway_database()


def _pending(sm: sessionmaker[Session], *, interval: PlanInterval = PlanInterval.monthly,
             allowance: int = 1_000) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    student = seed_user(sm, Role.student)
    tier = seed_tier(sm, interval=interval, allowance_units=allowance)
    sid = seed_subscription(sm, user_id=student, tier_id=tier, payer_id=student,
                            status=SubscriptionStatus.pending_first_payment,
                            period_start=None, period_end=None)
    pid = seed_first_payment(sm, subscription_id=sid, amount_minor=10_000, paymob_txn_id=777)
    return student, sid, pid


def _handle(sm: sessionmaker[Session], pid: uuid.UUID) -> None:
    with sm.begin() as session:
        handle_subscription_first(session, session.get(Payment, pid), {})


def _periods(sm: sessionmaker[Session], sid: uuid.UUID) -> list[SubscriptionPeriod]:
    with sm() as session:
        return list(session.scalars(sa.select(SubscriptionPeriod).where(
            SubscriptionPeriod.subscription_id == sid).order_by(SubscriptionPeriod.period_start)))


def test_first_payment_activates_with_one_period_and_one_allowance(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student, sid, pid = _pending(pg_sessionmaker)
    _handle(pg_sessionmaker, pid)

    with pg_sessionmaker() as session:
        sub = session.get(Subscription, sid)
        assert sub.status is SubscriptionStatus.active
        assert (sub.current_period_start, sub.current_period_end) == (T0, T0 + timedelta(days=30))
        assert sub.activated_at == T0
        assert sub.paymob_amount_minor == 10_000
    [period] = _periods(pg_sessionmaker, sid)
    assert (period.period_start, period.period_end, period.payment_id) == (
        T0, T0 + timedelta(days=30), pid)
    [grant] = grants_of(pg_sessionmaker, student)
    assert grant.kind is GrantKind.period_allowance
    assert (grant.units, grant.visible) == (1_000, False)
    assert grant.expires_at == T0 + timedelta(days=30)
    assert (grant.subscription_period_id, grant.payment_id) == (period.id, pid)


def test_yearly_period_is_360_days(pg_sessionmaker: sessionmaker[Session]) -> None:
    _, sid, pid = _pending(pg_sessionmaker, interval=PlanInterval.yearly)
    _handle(pg_sessionmaker, pid)
    [period] = _periods(pg_sessionmaker, sid)
    assert period.period_end - period.period_start == timedelta(days=360)


def test_handler_is_idempotent(pg_sessionmaker: sessionmaker[Session]) -> None:
    student, sid, pid = _pending(pg_sessionmaker)
    _handle(pg_sessionmaker, pid)
    _handle(pg_sessionmaker, pid)
    assert len(_periods(pg_sessionmaker, sid)) == 1
    assert len(grants_of(pg_sessionmaker, student)) == 1


def test_allowance_repays_debt_first(pg_sessionmaker: sessionmaker[Session]) -> None:
    student, _, pid = _pending(pg_sessionmaker)
    seed_debt(pg_sessionmaker, student, 300)  # adjust(-n) never creates debt (Phase 01)
    with pg_sessionmaker() as session:
        assert UsageLedger(session).has_debt(student)  # non-vacuity
    _handle(pg_sessionmaker, pid)
    with pg_sessionmaker() as session:
        assert not UsageLedger(session).has_debt(student)


def test_zero_allowance_tier_makes_a_period_but_no_grant(pg_sessionmaker: sessionmaker[Session]) -> None:
    student, sid, pid = _pending(pg_sessionmaker, allowance=0)
    _handle(pg_sessionmaker, pid)
    assert len(_periods(pg_sessionmaker, sid)) == 1
    assert grants_of(pg_sessionmaker, student) == []


def test_links_a_subscription_created_event_that_arrived_first(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    _, sid, pid = _pending(pg_sessionmaker)
    with pg_sessionmaker.begin() as session:
        session.add(PaymobEvent(
            kind=PaymobEventKind.subscription,
            dedupe_key="subscription:4321:Subscription Created:req-1",
            payload={"body": {"trigger_type": "Subscription Created"},
                     "remote": {"id": 4321, "initial_transaction": 777}},
        ))
    _handle(pg_sessionmaker, pid)
    with pg_sessionmaker() as session:
        assert session.get(Subscription, sid).paymob_subscription_id == 4321
        event = session.scalars(sa.select(PaymobEvent)).one()
        assert event.processed_at is not None


def test_superseded_checkout_paid_while_another_is_live_is_not_activated(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    student, sid, pid = _pending(pg_sessionmaker)
    with pg_sessionmaker.begin() as session:
        session.get(Subscription, sid).status = SubscriptionStatus.expired
    seed_subscription(pg_sessionmaker, user_id=student, tier_id=seed_tier(pg_sessionmaker),
                      payer_id=student, status=SubscriptionStatus.pending_first_payment,
                      period_start=None, period_end=None)
    with capture_logs() as logs:
        _handle(pg_sessionmaker, pid)
    assert any(e["event"] == "subscription_first_paid_for_superseded_checkout" for e in logs)
    with pg_sessionmaker() as session:
        assert session.get(Subscription, sid).status is SubscriptionStatus.expired
    assert grants_of(pg_sessionmaker, student) == []


def test_superseded_checkout_paid_with_nothing_else_live_is_activated(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    _, sid, pid = _pending(pg_sessionmaker)
    with pg_sessionmaker.begin() as session:
        session.get(Subscription, sid).status = SubscriptionStatus.expired
    _handle(pg_sessionmaker, pid)
    with pg_sessionmaker() as session:
        assert session.get(Subscription, sid).status is SubscriptionStatus.active


def test_transaction_callback_dispatches_the_registered_handler(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """Wiring proof: Phase 02's verified callback reaches this phase's handler."""
    student = seed_user(pg_sessionmaker, Role.student)
    tier = seed_tier(pg_sessionmaker, price_minor=10_000)
    client = FakePaymobClient()
    with pg_sessionmaker() as session:  # create_intention_checkout commits itself
        checkout = SubscriptionService(session, client, paymob_settings()).create_subscription_checkout(
            payer_user_id=student, plan_tier_id=tier, now=T0)
    with pg_sessionmaker() as session:
        order_id = session.get(Payment, checkout.payment_id).paymob_order_id
    obj = {
        "id": 777, "amount_cents": 10_000, "currency": "EGP", "success": True, "pending": False,
        "is_voided": False, "is_refunded": False, "error_occured": False, "is_auth": False,
        "is_capture": False, "is_3d_secure": True, "is_standalone_payment": True,
        "has_parent_transaction": False, "integration_id": 111, "owner": 1,
        "created_at": "2026-11-10T09:00:00",
        "order": {"id": order_id, "merchant_order_id": str(checkout.payment_id)},
        "source_data": {"pan": "2346", "sub_type": "MasterCard", "type": "card"},
    }
    with pg_sessionmaker.begin() as session:
        BillingService(session, client, paymob_settings()).apply_transaction_callback(obj)
    with pg_sessionmaker() as session:
        assert session.get(Payment, checkout.payment_id).status is PaymentStatus.paid
        assert session.get(Subscription, checkout.subscription_id).status is SubscriptionStatus.active
    assert len(grants_of(pg_sessionmaker, student)) == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest --no-cov tests/test_subscription_first_payment.py -v`
Expected: FAIL — `cannot import name 'handle_subscription_first'`.

- [ ] **Step 3: Implement the handler**

In `lemely/db/subscription_repo.py`, extend imports:

```python
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, ClassVar, Final

from lemely.core.subscription_rules import period_end
from lemely.db.billing_repo import BillingService, billing_data_for, register_paid_handler
from lemely.db.models.billing import PaymobEvent, PaymobEventKind, SubscriptionPeriod
from lemely.db.models.usage import GrantKind
from lemely.db.usage_ledger_repo import UsageLedger
```

and under `TYPE_CHECKING`: `from collections.abc import Mapping` and
`from lemely.db.models.usage import UsageGrant`.

Add module functions after `_line_items`:

```python
def _issue_period_grant(
    session: Session,
    subscription: Subscription,
    tier: PlanTier,
    period: SubscriptionPeriod,
    payment: Payment,
) -> UsageGrant | None:
    """The period's ``period_allowance`` grant, expiring at period end; repays debt first."""
    if not tier.allowance_units:
        return None
    return UsageLedger(session).issue_grant(
        owner_user_id=subscription.user_id,
        kind=GrantKind.period_allowance,
        units=tier.allowance_units,
        idempotency_key=f"period:{period.id}",
        expires_at=period.period_end,
        visible=False,
        effective_at=period.period_start,
        payment_id=payment.id,
        subscription_period_id=period.id,
    )


def _period_for_payment(session: Session, payment_id: uuid.UUID) -> uuid.UUID | None:
    return session.scalar(
        select(SubscriptionPeriod.id).where(SubscriptionPeriod.payment_id == payment_id)
    )


def _link_stored_created_event(
    session: Session, subscription: Subscription, payment: Payment
) -> None:
    """Link a ``Subscription Created`` webhook that arrived before the first payment's callback.

    Matches only on ``payload["remote"]`` (fetched from Paymob, Contract deviation 9).
    """
    if subscription.paymob_subscription_id is not None or payment.paymob_txn_id is None:
        return
    event = session.scalars(
        select(PaymobEvent)
        .where(
            PaymobEvent.kind == PaymobEventKind.subscription,
            PaymobEvent.processed_at.is_(None),
            PaymobEvent.payload["remote"]["initial_transaction"].astext
            == str(payment.paymob_txn_id),
        )
        .order_by(PaymobEvent.created_at)
        .limit(1)
        .with_for_update()
    ).one_or_none()
    if event is None:
        return
    subscription.paymob_subscription_id = int(event.payload["remote"]["id"])
    event.processed_at = datetime.now(UTC)
    log.info(
        "paymob_subscription_linked",
        subscription_id=str(subscription.id),
        paymob_subscription_id=subscription.paymob_subscription_id,
    )


def handle_subscription_first(
    session: Session, payment: Payment, obj: Mapping[str, Any]
) -> None:
    """Paid handler for ``subscription_first`` (spec §5.1 step 4), in the callback's transaction.

    Activates the subscription, starts the first period at ``paid_at``, inserts the period row
    and its allowance grant, and links the Paymob subscription if its ``Subscription Created``
    webhook came first. A second call for the same payment does nothing.
    """
    del obj  # the verified callback was already checked by BillingService
    now = payment.paid_at or datetime.now(UTC)
    subscription = session.get(Subscription, payment.subscription_id, with_for_update=True)
    if subscription is None:
        log.error("subscription_first_paid_without_subscription", payment_id=str(payment.id))
        return
    if _period_for_payment(session, payment.id) is not None:
        return
    if subscription.status is SubscriptionStatus.expired:
        if _has_other_live(session, subscription):
            log.error(
                "subscription_first_paid_for_superseded_checkout",
                subscription_id=str(subscription.id),
                payment_id=str(payment.id),
            )
            return
    elif subscription.status is not SubscriptionStatus.pending_first_payment:
        log.error(
            "subscription_first_paid_in_unexpected_state",
            subscription_id=str(subscription.id),
            status=subscription.status.value,
        )
        return
    tier = session.get(PlanTier, subscription.plan_tier_id)
    end = period_end(now, tier.interval.value)
    subscription.status = SubscriptionStatus.active
    subscription.activated_at = now
    subscription.current_period_start = now
    subscription.current_period_end = end
    subscription.grace_until = None
    subscription.paymob_amount_minor = payment.amount_minor
    _bump(subscription)
    period = SubscriptionPeriod(
        subscription_id=subscription.id, period_start=now, period_end=end, payment_id=payment.id
    )
    session.add(period)
    session.flush()
    _issue_period_grant(session, subscription, tier, period, payment)
    _link_stored_created_event(session, subscription, payment)
    log.info("subscription_activated", subscription_id=str(subscription.id))
```

At the very end of the module (after `__all__`):

```python
register_paid_handler(PaymentPurpose.subscription_first, handle_subscription_first)
```

Add `"handle_subscription_first"` to `__all__`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest --no-cov tests/test_subscription_first_payment.py tests/test_subscription_checkout.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add lemely/db/subscription_repo.py tests/test_subscription_first_payment.py
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files
git commit -S -m "feat(billing): activate subscription and grant period allowance on first payment" -- \
  lemely/db/subscription_repo.py tests/test_subscription_first_payment.py
```

---

### Task 6: Subscription webhook — dedupe, linking, successful renewal

**Files:**
- Modify: `lemely/db/subscription_repo.py`
- Test: `tests/test_subscription_renewal.py` (create)

**Interfaces:**
- Consumes: `PaymobClient.get_subscription`, `.last_transaction`; Task 3 rules; Task 5 helpers; Phase 03 `TeacherTeamService(session).request_removal(member_id, *, now)`, `TeacherMember`.
- Produces:
  - Trigger constants `TRIGGER_CREATED = "Subscription Created"`, `TRIGGER_SUCCESS = "Successful Transaction"`, `TRIGGER_FAILED = "Failed Transaction"`, `TRIGGER_OVERDUE = "Failed Overdue Transaction"`, `TRIGGER_CANCELED = "canceled"`, `TRIGGER_SUSPENDED = "suspended"`, `TRIGGER_RESUMED = "resumed"`.
  - `parse_subscription_webhook(body: Mapping[str, Any]) -> tuple[str, int, str | None]` (raises `MalformedWebhook`).
  - `SubscriptionService.apply_renewal_webhook(self, body: Mapping[str, Any], *, now: datetime) -> None`.
  - `SubscriptionService._apply_successful_charge(self, subscription, txn: Mapping[str, Any], *, now) -> bool` (used by Task 9).
  - `handle_subscription_renewal(session, payment, obj) -> None`, registered for `PaymentPurpose.subscription_renewal`.
  - Module helpers `_grant_renewal_period(session, subscription, payment, *, charged_at, now) -> SubscriptionPeriod`, `_seats_in_use(session, teacher_user_id) -> int`, `_shed_excess_seats(session, subscription, tier, *, now) -> int`.
  - `SubscriptionService._handlers()` mapping trigger → bound method `(subscription, remote, now) -> None`; Task 7 replaces it with the full table.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_subscription_renewal.py`:

```python
"""Subscription webhooks: dedupe, linking and the successful renewal (spec §5.2, §6)."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from structlog.testing import capture_logs

from lemely.db.models.billing import (
    Payment,
    PaymentPurpose,
    PaymentStatus,
    PaymobEvent,
    PlanAudience,
    Subscription,
    SubscriptionPeriod,
)
from lemely.db.models.enums import Role, SubscriptionStatus
from lemely.db.models.team import TeacherMember, TeacherMemberStatus
from lemely.db.models.tutoring import EmailOutbox
from lemely.db.subscription_repo import (
    MalformedWebhook,
    SubscriptionService,
    handle_subscription_renewal,
    parse_subscription_webhook,
)
from tests.subscription_fixtures import (
    T0,
    FakePaymobClient,
    charge,
    grants_of,
    paymob_settings,
    remote_subscription,
    seed_first_payment,
    seed_seat,
    seed_subscription,
    seed_tier,
    seed_user,
    subscription_webhook,
    throwaway_database,
)

if TYPE_CHECKING:
    import uuid
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker

PID = 4321
END = T0 + timedelta(days=30)
NOW = END + timedelta(minutes=5)


@pytest.fixture
def pg_sessionmaker() -> Iterator[sessionmaker[Session]]:
    yield from throwaway_database()


def _linked(sm: sessionmaker[Session], **kwargs: object) -> tuple[uuid.UUID, uuid.UUID]:
    student = seed_user(sm, Role.student)
    tier = kwargs.pop("tier_id", None) or seed_tier(sm, allowance_units=1_000)
    sid = seed_subscription(sm, user_id=student, tier_id=tier, payer_id=student,
                            paymob_subscription_id=PID, paymob_amount_minor=10_000, **kwargs)
    return student, sid


def _client(amount: int = 10_000, txn: int = 888, charged=END - timedelta(hours=2), **kw) -> FakePaymobClient:
    client = FakePaymobClient()
    client.subscriptions[PID] = remote_subscription(PID, amount_cents=amount)
    client.last_transactions[PID] = charge(txn, amount, created_at=charged, **kw)
    return client


def _deliver(sm: sessionmaker[Session], client: FakePaymobClient, body: dict, now=NOW) -> None:
    with sm.begin() as session:
        SubscriptionService(session, client, paymob_settings()).apply_renewal_webhook(body, now=now)


def _periods(sm: sessionmaker[Session], sid: uuid.UUID) -> list[SubscriptionPeriod]:
    with sm() as session:
        return list(session.scalars(sa.select(SubscriptionPeriod).where(
            SubscriptionPeriod.subscription_id == sid).order_by(SubscriptionPeriod.period_start)))


def _renewals(sm: sessionmaker[Session], sid: uuid.UUID) -> list[Payment]:
    with sm() as session:
        return list(session.scalars(sa.select(Payment).where(
            Payment.subscription_id == sid, Payment.purpose == PaymentPurpose.subscription_renewal)))


def test_parse_rejects_malformed_bodies() -> None:
    assert parse_subscription_webhook(subscription_webhook("canceled", 7, request_id="r"))[:2] == ("canceled", 7)
    for body in ({}, {"trigger_type": "x"}, {"trigger_type": "x", "subscription_data": {"id": "abc"}},
                 {"trigger_type": 5, "subscription_data": {"id": 1}}):
        with pytest.raises(MalformedWebhook):
            parse_subscription_webhook(body)


def test_successful_renewal_adds_payment_period_grant_and_notice(pg_sessionmaker: sessionmaker[Session]) -> None:
    student, sid = _linked(pg_sessionmaker)
    client = _client()
    _deliver(pg_sessionmaker, client, subscription_webhook("Successful Transaction", PID))

    [renewal] = _renewals(pg_sessionmaker, sid)
    assert (renewal.status, renewal.amount_minor, renewal.paymob_txn_id) == (PaymentStatus.paid, 10_000, 888)
    periods = _periods(pg_sessionmaker, sid)
    assert [(p.period_start, p.period_end) for p in periods] == [(END, END + timedelta(days=30))]
    with pg_sessionmaker() as session:
        sub = session.get(Subscription, sid)
        assert sub.status is SubscriptionStatus.active
        assert sub.current_period_end == END + timedelta(days=30)
        notices = session.scalars(sa.select(EmailOutbox)).all()
        assert [n.context["notice"] for n in notices] == ["renewed"]
    [grant] = grants_of(pg_sessionmaker, student)
    assert grant.subscription_period_id == periods[0].id
    assert grant.expires_at == END + timedelta(days=30)
    assert client.names() == ["get_subscription", "last_transaction"]


def test_duplicate_webhook_is_a_no_op(pg_sessionmaker: sessionmaker[Session]) -> None:
    _, sid = _linked(pg_sessionmaker)
    client = _client()
    body = subscription_webhook("Successful Transaction", PID, request_id="req-1")
    _deliver(pg_sessionmaker, client, body)
    calls = len(client.calls)
    _deliver(pg_sessionmaker, client, body)
    assert len(client.calls) == calls
    with pg_sessionmaker() as session:
        assert session.scalar(sa.select(sa.func.count()).select_from(PaymobEvent)) == 1
    assert len(_periods(pg_sessionmaker, sid)) == 1


def test_same_charge_in_a_second_webhook_is_not_granted_twice(pg_sessionmaker: sessionmaker[Session]) -> None:
    student, sid = _linked(pg_sessionmaker)
    client = _client()
    _deliver(pg_sessionmaker, client, subscription_webhook("Successful Transaction", PID))
    _deliver(pg_sessionmaker, client, subscription_webhook("Successful Transaction", PID))
    assert len(_renewals(pg_sessionmaker, sid)) == 1
    assert len(grants_of(pg_sessionmaker, student)) == 1


def test_amount_mismatch_records_failed_mismatch_and_grants_nothing(pg_sessionmaker: sessionmaker[Session]) -> None:
    student, sid = _linked(pg_sessionmaker)
    client = _client(amount=9_000)
    with capture_logs() as logs:
        _deliver(pg_sessionmaker, client, subscription_webhook("Successful Transaction", PID))
    [payment] = _renewals(pg_sessionmaker, sid)
    assert payment.status is PaymentStatus.failed_mismatch
    assert _periods(pg_sessionmaker, sid) == []
    assert grants_of(pg_sessionmaker, student) == []
    assert any(e["event"] == "subscription_renewal_mismatch" for e in logs)


def test_unsuccessful_last_transaction_changes_nothing(pg_sessionmaker: sessionmaker[Session]) -> None:
    _, sid = _linked(pg_sessionmaker)
    _deliver(pg_sessionmaker, _client(success=False), subscription_webhook("Successful Transaction", PID))
    assert _renewals(pg_sessionmaker, sid) == []


def test_late_renewal_after_grace_starts_at_the_charge(pg_sessionmaker: sessionmaker[Session]) -> None:
    _, sid = _linked(pg_sessionmaker, status=SubscriptionStatus.past_due, grace_until=END + timedelta(days=3))
    charged = END + timedelta(days=2)
    _deliver(pg_sessionmaker, _client(charged=charged), subscription_webhook("Successful Transaction", PID),
             now=charged + timedelta(minutes=1))
    with pg_sessionmaker() as session:
        sub = session.get(Subscription, sid)
        assert (sub.status, sub.grace_until) == (SubscriptionStatus.active, None)
        assert sub.current_period_start == charged


def test_pending_downgrade_applies_at_renewal(pg_sessionmaker: sessionmaker[Session]) -> None:
    lower = seed_tier(pg_sessionmaker, price_minor=6_000, allowance_units=400)
    student, sid = _linked(pg_sessionmaker, pending_plan_tier_id=lower)
    with pg_sessionmaker.begin() as session:
        session.get(Subscription, sid).paymob_amount_minor = 6_000  # pushed by the period-end job
    _deliver(pg_sessionmaker, _client(amount=6_000), subscription_webhook("Successful Transaction", PID))
    with pg_sessionmaker() as session:
        sub = session.get(Subscription, sid)
        assert (sub.plan_tier_id, sub.pending_plan_tier_id) == (lower, None)
    [renewal] = _renewals(pg_sessionmaker, sid)
    assert renewal.plan_tier_id == lower
    assert [g.units for g in grants_of(pg_sessionmaker, student)] == [400]


def test_teacher_downgrade_moves_the_newest_excess_seats_to_leaving(pg_sessionmaker: sessionmaker[Session]) -> None:
    teacher = seed_user(pg_sessionmaker, Role.teacher)
    big = seed_tier(pg_sessionmaker, audience=PlanAudience.teacher, included_seats=3)
    small = seed_tier(pg_sessionmaker, audience=PlanAudience.teacher, included_seats=1, price_minor=6_000)
    seed_subscription(pg_sessionmaker, user_id=teacher, tier_id=big, payer_id=teacher,
                      paymob_subscription_id=PID, paymob_amount_minor=6_000,
                      pending_plan_tier_id=small)
    seats = [seed_seat(pg_sessionmaker, teacher_id=teacher, student_id=seed_user(pg_sessionmaker, Role.student),
                       created_at=T0 + timedelta(hours=i)) for i in range(3)]
    _deliver(pg_sessionmaker, _client(amount=6_000), subscription_webhook("Successful Transaction", PID))
    with pg_sessionmaker() as session:
        statuses = [session.get(TeacherMember, m).status for m in seats]
    assert statuses == [TeacherMemberStatus.active, TeacherMemberStatus.leaving, TeacherMemberStatus.leaving]


def test_unknown_subscription_is_linked_through_its_first_payment(pg_sessionmaker: sessionmaker[Session]) -> None:
    student = seed_user(pg_sessionmaker, Role.student)
    sid = seed_subscription(pg_sessionmaker, user_id=student, tier_id=seed_tier(pg_sessionmaker),
                            payer_id=student, paymob_amount_minor=10_000)
    seed_first_payment(pg_sessionmaker, subscription_id=sid, paymob_txn_id=777)
    client = _client()
    _deliver(pg_sessionmaker, client, subscription_webhook("Subscription Created", PID))
    with pg_sessionmaker() as session:
        assert session.get(Subscription, sid).paymob_subscription_id == PID
        assert session.scalars(sa.select(PaymobEvent)).one().processed_at is not None


def test_unmatched_webhook_is_stored_unprocessed_with_the_remote_copy(pg_sessionmaker: sessionmaker[Session]) -> None:
    client = _client()
    with capture_logs() as logs:
        _deliver(pg_sessionmaker, client, subscription_webhook("Subscription Created", PID))
    with pg_sessionmaker() as session:
        event = session.scalars(sa.select(PaymobEvent)).one()
    assert event.processed_at is None
    assert event.payload["remote"]["initial_transaction"] == 777
    assert any(e["event"] == "paymob_subscription_webhook_unmatched" for e in logs)


def test_charge_on_an_ended_subscription(pg_sessionmaker: sessionmaker[Session]) -> None:
    student, sid = _linked(pg_sessionmaker, status=SubscriptionStatus.expired)
    other = seed_subscription(pg_sessionmaker, user_id=student, tier_id=seed_tier(pg_sessionmaker),
                              payer_id=student, status=SubscriptionStatus.active)
    with capture_logs() as logs:
        _deliver(pg_sessionmaker, _client(), subscription_webhook("Successful Transaction", PID))
    [payment] = _renewals(pg_sessionmaker, sid)
    assert payment.status is PaymentStatus.paid  # money taken: kept for a manual refund
    assert _periods(pg_sessionmaker, sid) == []
    assert any(e["event"] == "subscription_charge_on_ended_subscription" for e in logs)
    with pg_sessionmaker.begin() as session:
        session.get(Subscription, other).status = SubscriptionStatus.cancelled
    _deliver(pg_sessionmaker, _client(txn=889), subscription_webhook("Successful Transaction", PID))
    with pg_sessionmaker() as session:
        assert session.get(Subscription, sid).status is SubscriptionStatus.active


def test_renewal_paid_handler_grants_once(pg_sessionmaker: sessionmaker[Session]) -> None:
    student, sid = _linked(pg_sessionmaker)
    with pg_sessionmaker.begin() as session:
        payment = Payment(special_reference="manual-renewal-1", payer_user_id=student,
                          beneficiary_user_id=student, purpose=PaymentPurpose.subscription_renewal,
                          subscription_id=sid, amount_minor=10_000, currency="EGP",
                          status=PaymentStatus.paid, paid_at=END)
        session.add(payment)
        session.flush()
        handle_subscription_renewal(session, payment, {})
        handle_subscription_renewal(session, payment, {})
    assert len(_periods(pg_sessionmaker, sid)) == 1
    assert len(grants_of(pg_sessionmaker, student)) == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest --no-cov tests/test_subscription_renewal.py -v`
Expected: FAIL — `cannot import name 'MalformedWebhook'`-adjacent names (`handle_subscription_renewal`, `parse_subscription_webhook`).

- [ ] **Step 3: Implement**

In `lemely/db/subscription_repo.py`, extend imports:

```python
from collections.abc import Callable  # runtime: used in a type alias below

from sqlalchemy.dialects.postgresql import insert as pg_insert

from lemely.core.subscription_rules import (
    is_successful_charge,
    parse_paymob_time,
    renewal_period_start,
    seat_capacity_for,
)
from lemely.db.billing_notices import enqueue_subscription_notice
from lemely.db.models.billing import PLAN_LIVE_STATUSES
from lemely.db.models.team import TeacherMember, TeacherMemberKind, TeacherMemberStatus
from lemely.db.teacher_team_repo import TeacherTeamService
```

Add constants after `SUBSCRIPTION_WEBHOOK_PATH`:

```python
TRIGGER_CREATED: Final = "Subscription Created"
TRIGGER_SUCCESS: Final = "Successful Transaction"
TRIGGER_FAILED: Final = "Failed Transaction"
TRIGGER_OVERDUE: Final = "Failed Overdue Transaction"
TRIGGER_CANCELED: Final = "canceled"
TRIGGER_SUSPENDED: Final = "suspended"
TRIGGER_RESUMED: Final = "resumed"

TriggerHandler = Callable[[Subscription, dict[str, Any], datetime], None]
```

Add module functions after `handle_subscription_first`:

```python
def parse_subscription_webhook(body: Mapping[str, Any]) -> tuple[str, int, str | None]:
    """``(trigger_type, subscription id, paymob_request_id)`` from a callback body."""
    trigger = body.get("trigger_type")
    data = body.get("subscription_data")
    raw_id = data.get("id") if isinstance(data, dict) else None
    if not isinstance(trigger, str) or not trigger or isinstance(raw_id, bool):
        raise MalformedWebhook("trigger_type and subscription_data.id are required")
    try:
        paymob_id = int(raw_id)
    except (TypeError, ValueError) as exc:
        raise MalformedWebhook("subscription_data.id must be an integer") from exc
    request_id = body.get("paymob_request_id")
    return trigger, paymob_id, request_id if isinstance(request_id, str) and request_id else None


def _seats_in_use(session: Session, teacher_user_id: uuid.UUID) -> int:
    """Active plus leaving seats: the count the seat rule caps (spec §4.4)."""
    return int(
        session.scalar(
            select(sa.func.count())
            .select_from(TeacherMember)
            .where(
                TeacherMember.teacher_user_id == teacher_user_id,
                TeacherMember.kind == TeacherMemberKind.student_seat,
                TeacherMember.status.in_(
                    (TeacherMemberStatus.active, TeacherMemberStatus.leaving)
                ),
            )
        )
        or 0
    )


def _shed_excess_seats(
    session: Session, subscription: Subscription, tier: PlanTier, *, now: datetime
) -> int:
    """Move the newest active seats over capacity to ``leaving`` (spec §5.4 fallback rule)."""
    capacity = seat_capacity_for(
        included_seats=tier.included_seats, extra_seats=subscription.extra_seats or 0
    )
    excess = _seats_in_use(session, subscription.user_id) - capacity
    if excess <= 0:
        return 0
    newest = session.scalars(
        select(TeacherMember.id)
        .where(
            TeacherMember.teacher_user_id == subscription.user_id,
            TeacherMember.kind == TeacherMemberKind.student_seat,
            TeacherMember.status == TeacherMemberStatus.active,
        )
        .order_by(TeacherMember.created_at.desc(), TeacherMember.id.desc())
        .limit(excess)
    ).all()
    team = TeacherTeamService(session)
    for member_id in newest:
        team.request_removal(member_id, now=now)
    log.warning(
        "seats_shed_after_plan_change",
        teacher_user_id=str(subscription.user_id),
        count=len(newest),
    )
    return len(newest)


def _grant_renewal_period(
    session: Session,
    subscription: Subscription,
    payment: Payment,
    *,
    charged_at: datetime,
    now: datetime,
) -> SubscriptionPeriod:
    """Apply pending plan and seat changes, insert the next period and its allowance."""
    if subscription.pending_plan_tier_id is not None:
        subscription.plan_tier_id = subscription.pending_plan_tier_id
        subscription.pending_plan_tier_id = None
    if subscription.pending_extra_seats is not None:
        subscription.extra_seats = subscription.pending_extra_seats
        subscription.pending_extra_seats = None
    tier = session.get(PlanTier, subscription.plan_tier_id)
    if subscription.status in PLAN_LIVE_STATUSES:
        start = renewal_period_start(
            current_period_end=subscription.current_period_end, charged_at=charged_at
        )
    else:
        start = charged_at
    end = period_end(start, tier.interval.value)
    period = SubscriptionPeriod(
        subscription_id=subscription.id, period_start=start, period_end=end, payment_id=payment.id
    )
    session.add(period)
    session.flush()
    subscription.status = SubscriptionStatus.active
    subscription.grace_until = None
    subscription.current_period_start = start
    subscription.current_period_end = end
    _bump(subscription)
    _issue_period_grant(session, subscription, tier, period, payment)
    if tier.audience is PlanAudience.teacher:
        _shed_excess_seats(session, subscription, tier, now=now)
    enqueue_subscription_notice(session, subscription=subscription, notice="renewed", effective_at=end)
    log.info("subscription_renewed", subscription_id=str(subscription.id), period_end=end.isoformat())
    return period


def handle_subscription_renewal(
    session: Session, payment: Payment, obj: Mapping[str, Any]
) -> None:
    """Paid handler for ``subscription_renewal``: a renewal payment marked paid elsewhere.

    The webhook path records renewals itself; this covers a renewal payment Phase 02 marks
    paid (for example after reconciliation). One period per payment.
    """
    del obj
    if _period_for_payment(session, payment.id) is not None:
        return
    subscription = session.get(Subscription, payment.subscription_id, with_for_update=True)
    if subscription is None:
        log.error("subscription_renewal_paid_without_subscription", payment_id=str(payment.id))
        return
    now = payment.paid_at or datetime.now(UTC)
    _grant_renewal_period(session, subscription, payment, charged_at=now, now=now)
```

Add methods to `SubscriptionService`:

```python
    # -- webhooks (spec §5.2) ------------------------------------------------

    def apply_renewal_webhook(self, body: Mapping[str, Any], *, now: datetime) -> None:
        """Apply one HMAC-verified subscription callback, at most once.

        The callback is stored in ``paymob_events`` under
        ``subscription:{id}:{trigger}:{paymob_request_id}``; a duplicate is a no-op. State and
        amounts come from Paymob (``GET subscriptions/{id}``), never from the body. An
        unmatched callback stays unprocessed (``processed_at`` NULL) so the first-payment
        handler can link it later.

        Raises:
            MalformedWebhook: the body lacks a trigger or a subscription id.
            PaymobError: Paymob could not be reached; the caller rolls back and answers 5xx so
                Paymob retries.
        """
        trigger, paymob_id, request_id = parse_subscription_webhook(body)
        dedupe_key = f"subscription:{paymob_id}:{trigger}:{request_id or uuid.uuid4()}"
        event_id = self._session.execute(
            pg_insert(PaymobEvent)
            .values(kind=PaymobEventKind.subscription, dedupe_key=dedupe_key, payload={"body": dict(body)})
            .on_conflict_do_nothing(index_elements=[PaymobEvent.dedupe_key])
            .returning(PaymobEvent.id)
        ).scalar_one_or_none()
        if event_id is None:
            log.info("paymob_subscription_webhook_duplicate", dedupe_key=dedupe_key)
            return
        event = self._session.get(PaymobEvent, event_id)
        remote = self._client.get_subscription(paymob_id)
        event.payload = {"body": dict(body), "remote": remote}
        subscription = self._resolve(paymob_id, remote)
        if subscription is None:
            log.warning(
                "paymob_subscription_webhook_unmatched",
                paymob_subscription_id=paymob_id,
                trigger_type=trigger,
            )
            return
        handler = self._handlers().get(trigger)
        if handler is not None:
            handler(subscription, remote, now)
        event.processed_at = now

    def _handlers(self) -> dict[str, TriggerHandler]:
        return {TRIGGER_SUCCESS: self._on_successful_transaction}

    def _resolve(self, paymob_id: int, remote: Mapping[str, Any]) -> Subscription | None:
        """Our subscription for a Paymob id, linking it through its first payment if needed."""
        subscription = self._session.scalars(
            select(Subscription)
            .where(Subscription.paymob_subscription_id == paymob_id)
            .with_for_update()
        ).one_or_none()
        if subscription is not None:
            return subscription
        initial = remote.get("initial_transaction")
        if initial is None:
            return None
        payment = self._session.scalars(
            select(Payment).where(
                Payment.paymob_txn_id == int(initial),
                Payment.purpose == PaymentPurpose.subscription_first,
            )
        ).one_or_none()
        if payment is None or payment.subscription_id is None:
            return None
        subscription = self._session.get(Subscription, payment.subscription_id, with_for_update=True)
        if subscription is not None and subscription.paymob_subscription_id is None:
            subscription.paymob_subscription_id = paymob_id
            _bump(subscription)
            log.info(
                "paymob_subscription_linked",
                subscription_id=str(subscription.id),
                paymob_subscription_id=paymob_id,
            )
        return subscription

    def _on_successful_transaction(
        self, subscription: Subscription, remote: dict[str, Any], now: datetime
    ) -> None:
        del remote
        txn = self._client.last_transaction(subscription.paymob_subscription_id)
        self._apply_successful_charge(subscription, txn, now=now)

    def _apply_successful_charge(
        self, subscription: Subscription, txn: Mapping[str, Any], *, now: datetime
    ) -> bool:
        """Record a renewal charge and grant its period. ``True`` when a period was granted.

        A charge already recorded (by Paymob transaction id) is ignored. A charge whose amount
        or currency differs from what Lemely set at Paymob is stored ``failed_mismatch`` with no
        grant (spec §6). A charge on an ended subscription reactivates it unless the user has
        another live subscription, in which case the payment is kept for a manual refund.
        """
        if not is_successful_charge(txn):
            log.warning(
                "subscription_last_transaction_not_successful",
                subscription_id=str(subscription.id),
            )
            return False
        txn_id = int(txn["id"])
        if self._session.scalar(select(Payment.id).where(Payment.paymob_txn_id == txn_id)):
            return False
        tier = self._session.get(PlanTier, subscription.plan_tier_id)
        amount = int(txn["amount_cents"])
        currency = str(txn.get("currency") or tier.currency)
        charged_at = parse_paymob_time(txn.get("created_at")) or now
        payment_id = uuid.uuid4()
        payment = Payment(
            id=payment_id,
            special_reference=f"subscription-renewal:{txn_id}",
            payer_user_id=subscription.payer_user_id,
            beneficiary_user_id=subscription.user_id,
            purpose=PaymentPurpose.subscription_renewal,
            plan_tier_id=subscription.pending_plan_tier_id or subscription.plan_tier_id,
            subscription_id=subscription.id,
            seat_quantity=(
                subscription.pending_extra_seats
                if subscription.pending_extra_seats is not None
                else subscription.extra_seats
            ),
            amount_minor=amount,
            currency=currency,
            status=PaymentStatus.paid,
            paymob_txn_id=txn_id,
            method="card",
            last_callback=dict(txn),
            paid_at=charged_at,
        )
        if amount != subscription.paymob_amount_minor or currency != tier.currency:
            payment.status = PaymentStatus.failed_mismatch
            payment.paid_at = None
            self._session.add(payment)
            log.error(
                "subscription_renewal_mismatch",
                subscription_id=str(subscription.id),
                expected_minor=subscription.paymob_amount_minor,
                received_minor=amount,
                currency=currency,
            )
            return False
        self._session.add(payment)
        if subscription.status not in PLAN_LIVE_STATUSES and _has_other_live(
            self._session, subscription
        ):
            log.error(
                "subscription_charge_on_ended_subscription",
                subscription_id=str(subscription.id),
                payment_id=str(payment_id),
            )
            return False
        self._session.flush()
        _grant_renewal_period(self._session, subscription, payment, charged_at=charged_at, now=now)
        return True
```

Register the renewal handler at the end of the module:

```python
register_paid_handler(PaymentPurpose.subscription_renewal, handle_subscription_renewal)
```

Add `"TRIGGER_CANCELED"`, `"TRIGGER_CREATED"`, `"TRIGGER_FAILED"`, `"TRIGGER_OVERDUE"`,
`"TRIGGER_RESUMED"`, `"TRIGGER_SUCCESS"`, `"TRIGGER_SUSPENDED"`, `"handle_subscription_renewal"`,
`"parse_subscription_webhook"` to `__all__`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest --no-cov tests/test_subscription_renewal.py tests/test_subscription_first_payment.py tests/architecture/ -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add lemely/db/subscription_repo.py tests/test_subscription_renewal.py
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files
git commit -S -m "feat(billing): subscription webhook dedupe, linking and renewal grants" -- \
  lemely/db/subscription_repo.py tests/test_subscription_renewal.py
```

---

### Task 7: Failed renewal, grace, expiry and state mirroring

**Files:**
- Modify: `lemely/db/subscription_repo.py`
- Test: `tests/test_subscription_lifecycle.py` (create)

**Interfaces:**
- Consumes: Task 6 dispatch; `GRACE_PERIOD`; `PaymobClient.cancel_subscription`; `PaymobError`.
- Produces:
  - `SubscriptionService.mark_past_due(self, subscription_id: UUID, *, now: datetime) -> Subscription`.
  - `SubscriptionService.expire_overdue(self, *, now: datetime) -> int` (commits per subscription).
  - Private methods used by Tasks 8–9: `_lock(subscription_id) -> Subscription` (raises `SubscriptionNotFound`), `_mark_past_due(sub, *, now)`, `_expire(sub, *, now)`, `_cancel_at_paymob(sub, *, now) -> bool`, `_on_canceled(sub, remote, now)`, `_on_suspended(sub, remote, now)`, `_sweep_one(subscription_id, step, now) -> int`.
  - `_handlers()` returns the full table: success, failed, overdue, canceled, suspended, resumed.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_subscription_lifecycle.py`:

```python
"""Failed renewals, grace, expiry and Paymob state mirroring (spec §2.6, §5.2)."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from structlog.testing import capture_logs

from lemely.db.models.billing import Subscription
from lemely.db.models.enums import Role, SubscriptionStatus
from lemely.db.models.tutoring import EmailOutbox
from lemely.db.subscription_repo import SubscriptionService
from tests.subscription_fixtures import (
    T0,
    FakePaymobClient,
    paymob_settings,
    remote_subscription,
    seed_subscription,
    seed_tier,
    seed_user,
    subscription_webhook,
    throwaway_database,
)

if TYPE_CHECKING:
    import uuid
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker

PID = 4321
END = T0 + timedelta(days=30)


@pytest.fixture
def pg_sessionmaker() -> Iterator[sessionmaker[Session]]:
    yield from throwaway_database()


def _linked(sm: sessionmaker[Session], pid: int = PID, **kwargs: object) -> uuid.UUID:
    student = seed_user(sm, Role.student)
    return seed_subscription(sm, user_id=student, tier_id=seed_tier(sm), payer_id=student,
                             paymob_subscription_id=pid, paymob_amount_minor=10_000, **kwargs)


def _client(state: str = "active", pid: int = PID) -> FakePaymobClient:
    client = FakePaymobClient()
    client.subscriptions[pid] = remote_subscription(pid, state=state)
    return client


def _deliver(sm: sessionmaker[Session], client: FakePaymobClient, trigger: str, now) -> None:
    with sm.begin() as session:
        SubscriptionService(session, client, paymob_settings()).apply_renewal_webhook(
            subscription_webhook(trigger, PID), now=now)


def _sub(sm: sessionmaker[Session], sid: uuid.UUID) -> Subscription:
    with sm() as session:
        return session.get(Subscription, sid)


def _notices(sm: sessionmaker[Session]) -> list[str]:
    with sm() as session:
        return [r.context["notice"] for r in session.scalars(
            sa.select(EmailOutbox).order_by(EmailOutbox.created_at))]


def test_failed_renewal_starts_three_days_of_grace(pg_sessionmaker: sessionmaker[Session]) -> None:
    sid = _linked(pg_sessionmaker)
    failed_at = END + timedelta(hours=1)
    _deliver(pg_sessionmaker, _client(), "Failed Transaction", failed_at)
    sub = _sub(pg_sessionmaker, sid)
    assert (sub.status, sub.grace_until) == (SubscriptionStatus.past_due, failed_at + timedelta(days=3))
    assert _notices(pg_sessionmaker) == ["payment_failed"]


def test_a_retry_failure_does_not_extend_grace(pg_sessionmaker: sessionmaker[Session]) -> None:
    sid = _linked(pg_sessionmaker)
    first = END + timedelta(hours=1)
    _deliver(pg_sessionmaker, _client(), "Failed Transaction", first)
    _deliver(pg_sessionmaker, _client(), "Failed Transaction", first + timedelta(days=1))
    assert _sub(pg_sessionmaker, sid).grace_until == first + timedelta(days=3)
    assert _notices(pg_sessionmaker) == ["payment_failed"]


def test_mark_past_due_by_id(pg_sessionmaker: sessionmaker[Session]) -> None:
    sid = _linked(pg_sessionmaker)
    with pg_sessionmaker.begin() as session:
        SubscriptionService(session, FakePaymobClient(), paymob_settings()).mark_past_due(sid, now=END)
    assert _sub(pg_sessionmaker, sid).status is SubscriptionStatus.past_due


def test_expire_overdue_waits_for_grace_then_expires_and_cancels_paymob(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    grace = END + timedelta(days=3)
    sid = _linked(pg_sessionmaker, status=SubscriptionStatus.past_due, grace_until=grace)
    client = _client()
    with pg_sessionmaker() as session:
        assert SubscriptionService(session, client, paymob_settings()).expire_overdue(
            now=grace - timedelta(minutes=1)) == 0
    assert _sub(pg_sessionmaker, sid).status is SubscriptionStatus.past_due
    with pg_sessionmaker() as session:
        assert SubscriptionService(session, client, paymob_settings()).expire_overdue(now=grace) == 1
    sub = _sub(pg_sessionmaker, sid)
    assert (sub.status, sub.grace_until, sub.paymob_cancelled_at) == (
        SubscriptionStatus.expired, None, grace)
    assert client.names() == ["cancel_subscription"]
    assert _notices(pg_sessionmaker) == ["expired"]


def test_expiry_survives_a_failed_paymob_cancel(pg_sessionmaker: sessionmaker[Session]) -> None:
    grace = END + timedelta(days=3)
    sid = _linked(pg_sessionmaker, status=SubscriptionStatus.past_due, grace_until=grace)
    client = FakePaymobClient(failing={"cancel_subscription"})
    with capture_logs() as logs, pg_sessionmaker() as session:
        assert SubscriptionService(session, client, paymob_settings()).expire_overdue(now=grace) == 1
    sub = _sub(pg_sessionmaker, sid)
    assert (sub.status, sub.paymob_cancelled_at) == (SubscriptionStatus.expired, None)
    assert any(e["event"] == "paymob_cancel_failed" for e in logs)


def test_failed_overdue_trigger_expires_at_once(pg_sessionmaker: sessionmaker[Session]) -> None:
    sid = _linked(pg_sessionmaker, status=SubscriptionStatus.past_due, grace_until=END + timedelta(days=3))
    _deliver(pg_sessionmaker, _client(), "Failed Overdue Transaction", END + timedelta(days=1))
    assert _sub(pg_sessionmaker, sid).status is SubscriptionStatus.expired


def test_paymob_cancel_of_our_period_end_cancel_keeps_access(pg_sessionmaker: sessionmaker[Session]) -> None:
    sid = _linked(pg_sessionmaker, cancel_at_period_end=True)
    now = END - timedelta(days=5)
    _deliver(pg_sessionmaker, _client(state="canceled"), "canceled", now)
    sub = _sub(pg_sessionmaker, sid)
    assert (sub.status, sub.paymob_cancelled_at) == (SubscriptionStatus.active, now)


def test_external_paymob_cancel_is_mirrored(pg_sessionmaker: sessionmaker[Session]) -> None:
    sid = _linked(pg_sessionmaker)
    _deliver(pg_sessionmaker, _client(state="canceled"), "canceled", END - timedelta(days=5))
    assert _sub(pg_sessionmaker, sid).status is SubscriptionStatus.cancelled
    assert _notices(pg_sessionmaker) == ["cancelled"]


def test_trigger_that_disagrees_with_paymob_state_is_ignored(pg_sessionmaker: sessionmaker[Session]) -> None:
    sid = _linked(pg_sessionmaker)
    with capture_logs() as logs:
        _deliver(pg_sessionmaker, _client(state="active"), "canceled", END - timedelta(days=5))
    assert _sub(pg_sessionmaker, sid).status is SubscriptionStatus.active
    assert any(e["event"] == "paymob_state_disagrees" for e in logs)


def test_suspend_then_resume(pg_sessionmaker: sessionmaker[Session]) -> None:
    sid = _linked(pg_sessionmaker)
    now = END - timedelta(days=10)
    _deliver(pg_sessionmaker, _client(state="suspended"), "suspended", now)
    sub = _sub(pg_sessionmaker, sid)
    assert (sub.status, sub.grace_until) == (SubscriptionStatus.past_due, END)
    _deliver(pg_sessionmaker, _client(state="active"), "resumed", now + timedelta(days=1))
    sub = _sub(pg_sessionmaker, sid)
    assert (sub.status, sub.grace_until) == (SubscriptionStatus.active, None)


def test_resume_after_the_paid_period_ended_stays_past_due(pg_sessionmaker: sessionmaker[Session]) -> None:
    sid = _linked(pg_sessionmaker, status=SubscriptionStatus.past_due, grace_until=END + timedelta(days=3))
    _deliver(pg_sessionmaker, _client(state="active"), "resumed", END + timedelta(days=1))
    assert _sub(pg_sessionmaker, sid).status is SubscriptionStatus.past_due


def test_one_failing_subscription_does_not_block_the_others(pg_sessionmaker: sessionmaker[Session]) -> None:
    grace = END + timedelta(days=3)
    bad = _linked(pg_sessionmaker, pid=1, status=SubscriptionStatus.past_due, grace_until=grace)
    good = _linked(pg_sessionmaker, pid=2, status=SubscriptionStatus.past_due, grace_until=grace)
    client = FakePaymobClient(fail_for={1})
    with pg_sessionmaker() as session:
        assert SubscriptionService(session, client, paymob_settings()).expire_overdue(now=grace) == 2
    assert _sub(pg_sessionmaker, bad).status is SubscriptionStatus.expired
    assert _sub(pg_sessionmaker, good).paymob_cancelled_at == grace
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest --no-cov tests/test_subscription_lifecycle.py -v`
Expected: FAIL — `AttributeError: 'SubscriptionService' object has no attribute 'mark_past_due'`, and the failed-trigger tests see no state change.

- [ ] **Step 3: Implement**

In `lemely/db/subscription_repo.py`, add `GRACE_PERIOD` to the `subscription_rules` import and
`from lemely.io.paymob.client import PaymobError` (runtime import). Replace `_handlers` and add the
methods:

```python
    def _handlers(self) -> dict[str, TriggerHandler]:
        return {
            TRIGGER_SUCCESS: self._on_successful_transaction,
            TRIGGER_FAILED: self._on_failed,
            TRIGGER_OVERDUE: self._on_overdue,
            TRIGGER_CANCELED: self._on_canceled,
            TRIGGER_SUSPENDED: self._on_suspended,
            TRIGGER_RESUMED: self._on_resumed,
        }

    # -- grace and expiry (spec §2.6, §5.2) -----------------------------------

    def mark_past_due(self, subscription_id: uuid.UUID, *, now: datetime) -> Subscription:
        """A renewal failed: ``past_due`` with ``grace_until = now + 3 days``."""
        subscription = self._lock(subscription_id)
        self._mark_past_due(subscription, now=now)
        return subscription

    def expire_overdue(self, *, now: datetime) -> int:
        """Expire every ``past_due`` subscription whose grace has elapsed. Commits per row."""
        ids = self._session.scalars(
            select(Subscription.id).where(
                Subscription.status == SubscriptionStatus.past_due,
                Subscription.grace_until <= now,
                # Complimentary rows have no Paymob link; Phase 07 ends those (index R15).
                Subscription.paymob_subscription_id.is_not(None),
            )
        ).all()
        return sum(self._sweep_one(sid, self._expire_if_due, now) for sid in ids)

    def _lock(self, subscription_id: uuid.UUID) -> Subscription:
        subscription = self._session.get(Subscription, subscription_id, with_for_update=True)
        if subscription is None:
            raise SubscriptionNotFound(f"unknown subscription {subscription_id}")
        return subscription

    def _sweep_one(
        self,
        subscription_id: uuid.UUID,
        step: Callable[[Subscription, datetime], bool],
        now: datetime,
    ) -> int:
        """Lock, apply ``step`` and commit one subscription; roll back and log on failure."""
        try:
            changed = step(self._lock(subscription_id), now)
            self._session.commit()
        except Exception:
            self._session.rollback()
            log.warning("subscription_sweep_failed", subscription_id=str(subscription_id), exc_info=True)
            return 0
        return int(changed)

    def _expire_if_due(self, subscription: Subscription, now: datetime) -> bool:
        if (
            subscription.status is not SubscriptionStatus.past_due
            or subscription.grace_until is None
            or subscription.grace_until > now
        ):
            return False
        self._expire(subscription, now=now)
        return True

    def _mark_past_due(self, subscription: Subscription, *, now: datetime) -> None:
        if subscription.status is not SubscriptionStatus.active:
            return  # already past_due: Paymob's retries must not extend the first deadline
        subscription.status = SubscriptionStatus.past_due
        subscription.grace_until = now + GRACE_PERIOD
        _bump(subscription)
        enqueue_subscription_notice(
            self._session,
            subscription=subscription,
            notice="payment_failed",
            effective_at=subscription.grace_until,
        )
        log.info("subscription_past_due", subscription_id=str(subscription.id))

    def _expire(self, subscription: Subscription, *, now: datetime) -> None:
        """Lapse the plan: no new allowance, no new seat allowances (spec §5.2)."""
        subscription.status = SubscriptionStatus.expired
        subscription.grace_until = None
        _bump(subscription)
        enqueue_subscription_notice(
            self._session, subscription=subscription, notice="expired", effective_at=now
        )
        self._cancel_at_paymob(subscription, now=now)
        log.info("subscription_expired", subscription_id=str(subscription.id))

    def _cancel_at_paymob(self, subscription: Subscription, *, now: datetime) -> bool:
        """Cancel the Paymob subscription once. ``False`` (and logged) when Paymob fails;
        the daily drift check retries."""
        if subscription.paymob_subscription_id is None or subscription.paymob_cancelled_at:
            return False
        try:
            self._client.cancel_subscription(subscription.paymob_subscription_id)
        except PaymobError:
            log.warning(
                "paymob_cancel_failed", subscription_id=str(subscription.id), exc_info=True
            )
            return False
        subscription.paymob_cancelled_at = now
        return True

    # -- mirrored Paymob states (spec §5.2) -----------------------------------

    def _on_failed(self, subscription: Subscription, remote: dict[str, Any], now: datetime) -> None:
        del remote
        self._mark_past_due(subscription, now=now)

    def _on_overdue(self, subscription: Subscription, remote: dict[str, Any], now: datetime) -> None:
        del remote
        if subscription.status in PLAN_LIVE_STATUSES:
            self._expire(subscription, now=now)

    def _on_canceled(self, subscription: Subscription, remote: dict[str, Any], now: datetime) -> None:
        if remote.get("state") != "canceled":
            log.warning("paymob_state_disagrees", subscription_id=str(subscription.id),
                        trigger_type=TRIGGER_CANCELED, state=remote.get("state"))
            return
        if subscription.paymob_cancelled_at is None:
            subscription.paymob_cancelled_at = now
        if subscription.status not in PLAN_LIVE_STATUSES:
            return
        if (
            subscription.cancel_at_period_end
            and subscription.current_period_end is not None
            and now < subscription.current_period_end
        ):
            return  # Lemely's own period-end cancel: access runs to period end
        subscription.status = SubscriptionStatus.cancelled
        subscription.grace_until = None
        _bump(subscription)
        enqueue_subscription_notice(
            self._session, subscription=subscription, notice="cancelled", effective_at=now
        )

    def _on_suspended(self, subscription: Subscription, remote: dict[str, Any], now: datetime) -> None:
        if remote.get("state") != "suspended":
            log.warning("paymob_state_disagrees", subscription_id=str(subscription.id),
                        trigger_type=TRIGGER_SUSPENDED, state=remote.get("state"))
            return
        if subscription.status is not SubscriptionStatus.active:
            return
        subscription.status = SubscriptionStatus.past_due
        subscription.grace_until = max(subscription.current_period_end or now, now)
        _bump(subscription)

    def _on_resumed(self, subscription: Subscription, remote: dict[str, Any], now: datetime) -> None:
        if remote.get("state") != "active" or subscription.status is not SubscriptionStatus.past_due:
            return
        if subscription.current_period_end is None or subscription.current_period_end <= now:
            return  # the paid period is over; the next renewal reactivates
        subscription.status = SubscriptionStatus.active
        subscription.grace_until = None
        _bump(subscription)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest --no-cov tests/test_subscription_lifecycle.py tests/test_subscription_renewal.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add lemely/db/subscription_repo.py tests/test_subscription_lifecycle.py
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files
git commit -S -m "feat(billing): renewal grace, expiry and Paymob state mirroring" -- \
  lemely/db/subscription_repo.py tests/test_subscription_lifecycle.py
```

---

### Task 8: Downgrade, cancel at period end, period-end changes

**Files:**
- Modify: `lemely/db/subscription_repo.py`, `lemely/runtime/config.py` (`PaymobSettings.subscription_amount_updatable`)
- Test: `tests/test_subscription_plan_changes.py` (create)

**Interfaces:**
- Consumes: Task 7 `_lock`, `_sweep_one`, `_cancel_at_paymob`; Task 6 `_seats_in_use`; `PaymobClient.update_subscription(id, *, amount_cents)`.
- Produces:
  - `PaymobSettings.subscription_amount_updatable: bool = True` (env `LEMELY_PAYMOB__SUBSCRIPTION_AMOUNT_UPDATABLE`). Phase 05 runs first, so it adds the field; Phase 06 uses it and must not add it again.
  - `SubscriptionService.schedule_downgrade(self, subscription_id: UUID, *, actor_user_id: UUID, plan_tier_id: UUID, now: datetime) -> Subscription` (raises `SubscriptionNotFound` for a non-payer, `InvalidPlanChange`, `SeatsInsufficient`, and `DowngradeUnavailable` (`downgrade_unavailable`, HTTP 409) when `subscription_amount_updatable` is `False`). Passing the current tier clears a pending downgrade, and works on the fallback path too.
  - `SubscriptionService.schedule_cancel(self, subscription_id: UUID, *, actor_user_id: UUID, now: datetime) -> Subscription`.
  - `SubscriptionService.apply_period_end_changes(self, *, now: datetime) -> int` (commits per subscription): PUTs a changed renewal amount, pushes a scheduled cancel to Paymob, ends cancelled subscriptions at period end.
  - `SubscriptionService.next_renewal_amount(self, subscription: Subscription) -> int` (the single source of the expected renewal amount, index R6).
  - `SubscriptionService.sync_renewal_amount(self, subscription: Subscription) -> bool` (PUT + stamp `paymob_amount_minor`; Phase 06 calls it after seat changes).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_subscription_plan_changes.py`:

```python
"""Downgrade and cancel take effect at period end (spec §2.6, §5.3)."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa

from lemely.db.models.billing import PlanAudience, Subscription
from lemely.db.models.enums import PlanInterval, Role, SubscriptionStatus
from lemely.db.models.team import TeacherMemberStatus
from lemely.db.models.tutoring import EmailOutbox
from lemely.db.subscription_repo import (
    DowngradeUnavailable,
    InvalidPlanChange,
    SeatsInsufficient,
    SubscriptionNotFound,
    SubscriptionService,
)
from tests.subscription_fixtures import (
    T0,
    FakePaymobClient,
    paymob_settings,
    remote_subscription,
    seed_seat,
    seed_subscription,
    seed_tier,
    seed_user,
    throwaway_database,
)

if TYPE_CHECKING:
    import uuid
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker

PID = 4321
END = T0 + timedelta(days=30)
NOW = T0 + timedelta(days=10)


@pytest.fixture
def pg_sessionmaker() -> Iterator[sessionmaker[Session]]:
    yield from throwaway_database()


def _svc(session: Session, client: FakePaymobClient | None = None) -> SubscriptionService:
    return SubscriptionService(session, client or FakePaymobClient(), paymob_settings())


def _student_sub(sm: sessionmaker[Session], pid: int = PID, **kwargs: object) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    payer = seed_user(sm, Role.student)
    tier = seed_tier(sm, price_minor=10_000)
    sid = seed_subscription(sm, user_id=payer, tier_id=tier, payer_id=payer,
                            paymob_subscription_id=pid, paymob_amount_minor=10_000, **kwargs)
    return payer, tier, sid


def _sub(sm: sessionmaker[Session], sid: uuid.UUID) -> Subscription:
    with sm() as session:
        return session.get(Subscription, sid)


def test_downgrade_is_scheduled_then_pushed_once(pg_sessionmaker: sessionmaker[Session]) -> None:
    payer, _, sid = _student_sub(pg_sessionmaker)
    lower = seed_tier(pg_sessionmaker, price_minor=6_000)
    client = FakePaymobClient()
    with pg_sessionmaker.begin() as session:
        _svc(session, client).schedule_downgrade(sid, actor_user_id=payer, plan_tier_id=lower, now=NOW)
    assert _sub(pg_sessionmaker, sid).pending_plan_tier_id == lower
    assert client.calls == []  # nothing at Paymob until the sweep

    with pg_sessionmaker() as session:
        assert _svc(session, client).apply_period_end_changes(now=NOW) == 1
    assert client.calls == [("update_subscription", {"subscription_id": PID, "amount_cents": 6_000})]
    assert _sub(pg_sessionmaker, sid).paymob_amount_minor == 6_000
    assert _sub(pg_sessionmaker, sid).plan_tier_id != lower  # switches at renewal, not now

    with pg_sessionmaker() as session:
        assert _svc(session, client).apply_period_end_changes(now=NOW) == 0
    assert len(client.calls) == 1


def test_choosing_the_current_tier_clears_a_pending_downgrade(pg_sessionmaker: sessionmaker[Session]) -> None:
    payer, tier, sid = _student_sub(pg_sessionmaker)
    lower = seed_tier(pg_sessionmaker, price_minor=6_000)
    with pg_sessionmaker.begin() as session:
        _svc(session).schedule_downgrade(sid, actor_user_id=payer, plan_tier_id=lower, now=NOW)
        _svc(session).schedule_downgrade(sid, actor_user_id=payer, plan_tier_id=tier, now=NOW)
    assert _sub(pg_sessionmaker, sid).pending_plan_tier_id is None


def test_downgrade_refusals(pg_sessionmaker: sessionmaker[Session]) -> None:
    payer, _, sid = _student_sub(pg_sessionmaker)
    higher = seed_tier(pg_sessionmaker, price_minor=20_000)
    teacher_tier = seed_tier(pg_sessionmaker, audience=PlanAudience.teacher, price_minor=1_000)
    yearly = seed_tier(pg_sessionmaker, interval=PlanInterval.yearly, price_minor=1_000)
    inactive = seed_tier(pg_sessionmaker, price_minor=1_000, is_active=False)
    for target in (higher, teacher_tier, yearly, inactive):
        with pytest.raises(InvalidPlanChange), pg_sessionmaker.begin() as session:
            _svc(session).schedule_downgrade(sid, actor_user_id=payer, plan_tier_id=target, now=NOW)
    stranger = seed_user(pg_sessionmaker, Role.student)
    lower = seed_tier(pg_sessionmaker, price_minor=6_000)
    with pytest.raises(SubscriptionNotFound), pg_sessionmaker.begin() as session:
        _svc(session).schedule_downgrade(sid, actor_user_id=stranger, plan_tier_id=lower, now=NOW)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"status": SubscriptionStatus.past_due},
        {"cancel_at_period_end": True},
        {"is_manually_activated": True},
    ],
)
def test_downgrade_refused_when_paymob_cannot_lower_the_amount_but_cancel_works(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """Fallback path (Phase 06's flag): the old price would keep renewing, so refuse."""
    payer, tier, sid = _student_sub(pg_sessionmaker)
    lower = seed_tier(pg_sessionmaker, price_minor=6_000)
    fallback = paymob_settings(subscription_amount_updatable=False)
    client = FakePaymobClient()
    with pytest.raises(DowngradeUnavailable) as refused, pg_sessionmaker.begin() as session:
        SubscriptionService(session, client, fallback).schedule_downgrade(
            sid, actor_user_id=payer, plan_tier_id=lower, now=NOW)
    assert refused.value.code == "downgrade_unavailable"
    assert _sub(pg_sessionmaker, sid).pending_plan_tier_id is None
    assert client.calls == []

    with pg_sessionmaker.begin() as session:  # clearing (current tier) and cancel stay allowed
        svc = SubscriptionService(session, client, fallback)
        svc.schedule_downgrade(sid, actor_user_id=payer, plan_tier_id=tier, now=NOW)
        svc.schedule_cancel(sid, actor_user_id=payer, now=NOW)
    assert _sub(pg_sessionmaker, sid).cancel_at_period_end is True


def test_downgrade_needs_an_active_card_subscription(
    pg_sessionmaker: sessionmaker[Session], kwargs: dict[str, object]
) -> None:
    payer, _, sid = _student_sub(pg_sessionmaker, **kwargs)
    lower = seed_tier(pg_sessionmaker, price_minor=6_000)
    with pytest.raises(InvalidPlanChange), pg_sessionmaker.begin() as session:
        _svc(session).schedule_downgrade(sid, actor_user_id=payer, plan_tier_id=lower, now=NOW)


def test_teacher_downgrade_refused_until_seats_fit(pg_sessionmaker: sessionmaker[Session]) -> None:
    teacher = seed_user(pg_sessionmaker, Role.teacher)
    big = seed_tier(pg_sessionmaker, audience=PlanAudience.teacher, price_minor=50_000, included_seats=10)
    small = seed_tier(pg_sessionmaker, audience=PlanAudience.teacher, price_minor=30_000, included_seats=3)
    sid = seed_subscription(pg_sessionmaker, user_id=teacher, tier_id=big, payer_id=teacher,
                            paymob_subscription_id=PID, paymob_amount_minor=50_000)
    for _ in range(3):
        seed_seat(pg_sessionmaker, teacher_id=teacher, student_id=seed_user(pg_sessionmaker, Role.student))
    leaving = seed_seat(pg_sessionmaker, teacher_id=teacher, student_id=seed_user(pg_sessionmaker, Role.student),
                        status=TeacherMemberStatus.leaving)
    with pytest.raises(SeatsInsufficient) as refused, pg_sessionmaker.begin() as session:
        _svc(session).schedule_downgrade(sid, actor_user_id=teacher, plan_tier_id=small, now=NOW)
    assert (refused.value.in_use, refused.value.capacity) == (4, 3)

    with pg_sessionmaker.begin() as session:  # the leaving seat is released
        session.execute(sa.text("UPDATE teacher_members SET status = 'removed' WHERE id = :m"), {"m": leaving})
        _svc(session).schedule_downgrade(sid, actor_user_id=teacher, plan_tier_id=small, now=NOW)
    assert _sub(pg_sessionmaker, sid).pending_plan_tier_id == small


def test_cancel_is_pushed_at_once_and_ends_at_period_end(pg_sessionmaker: sessionmaker[Session]) -> None:
    payer, _, sid = _student_sub(pg_sessionmaker)
    client = FakePaymobClient()
    client.subscriptions[PID] = remote_subscription(PID)
    with pg_sessionmaker.begin() as session:
        _svc(session, client).schedule_cancel(sid, actor_user_id=payer, now=NOW)
    assert _sub(pg_sessionmaker, sid).cancel_at_period_end is True

    with pg_sessionmaker() as session:
        assert _svc(session, client).apply_period_end_changes(now=NOW) == 1
    sub = _sub(pg_sessionmaker, sid)
    assert (sub.status, sub.paymob_cancelled_at) == (SubscriptionStatus.active, NOW)
    assert client.names() == ["cancel_subscription"]

    with pg_sessionmaker() as session:
        assert _svc(session, client).apply_period_end_changes(now=END - timedelta(seconds=1)) == 0
        assert _svc(session, client).apply_period_end_changes(now=END) == 1
    assert _sub(pg_sessionmaker, sid).status is SubscriptionStatus.cancelled
    assert client.names() == ["cancel_subscription"]
    with pg_sessionmaker() as session:
        assert [r.context["notice"] for r in session.scalars(sa.select(EmailOutbox))] == ["cancelled"]


def test_cancel_refused_for_others_and_ended_plans(pg_sessionmaker: sessionmaker[Session]) -> None:
    payer, _, sid = _student_sub(pg_sessionmaker, status=SubscriptionStatus.expired)
    with pytest.raises(InvalidPlanChange), pg_sessionmaker.begin() as session:
        _svc(session).schedule_cancel(sid, actor_user_id=payer, now=NOW)
    _, _, someone_elses = _student_sub(pg_sessionmaker, pid=99)
    with pytest.raises(SubscriptionNotFound), pg_sessionmaker.begin() as session:
        _svc(session).schedule_cancel(someone_elses, actor_user_id=payer, now=NOW)


def test_a_failed_put_keeps_the_change_pending_and_others_proceed(pg_sessionmaker: sessionmaker[Session]) -> None:
    payer1, _, sid1 = _student_sub(pg_sessionmaker, pid=1)
    payer2, _, sid2 = _student_sub(pg_sessionmaker, pid=2)
    lower = seed_tier(pg_sessionmaker, price_minor=6_000)
    with pg_sessionmaker.begin() as session:
        _svc(session).schedule_downgrade(sid1, actor_user_id=payer1, plan_tier_id=lower, now=NOW)
        _svc(session).schedule_downgrade(sid2, actor_user_id=payer2, plan_tier_id=lower, now=NOW)
    client = FakePaymobClient(fail_for={1})
    with pg_sessionmaker() as session:
        assert _svc(session, client).apply_period_end_changes(now=NOW) == 1
    assert _sub(pg_sessionmaker, sid1).paymob_amount_minor == 10_000
    assert _sub(pg_sessionmaker, sid1).pending_plan_tier_id == lower
    assert _sub(pg_sessionmaker, sid2).paymob_amount_minor == 6_000


def test_pending_seat_reduction_is_pushed(pg_sessionmaker: sessionmaker[Session]) -> None:
    """Contract deviation 10: Phase 06 sets pending_extra_seats; this job PUTs the amount."""
    teacher = seed_user(pg_sessionmaker, Role.teacher)
    tier = seed_tier(pg_sessionmaker, audience=PlanAudience.teacher, price_minor=50_000,
                     included_seats=10, extra_seat_price_minor=2_500)
    sid = seed_subscription(pg_sessionmaker, user_id=teacher, tier_id=tier, payer_id=teacher,
                            paymob_subscription_id=PID, paymob_amount_minor=57_500, extra_seats=3)
    with pg_sessionmaker.begin() as session:
        session.get(Subscription, sid).pending_extra_seats = 1
    client = FakePaymobClient()
    with pg_sessionmaker() as session:
        assert _svc(session, client).apply_period_end_changes(now=NOW) == 1
    assert client.calls == [("update_subscription", {"subscription_id": PID, "amount_cents": 52_500})]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest --no-cov tests/test_subscription_plan_changes.py -v`
Expected: FAIL — `AttributeError: ... 'schedule_downgrade'`.

- [ ] **Step 3: Implement**

In `lemely/runtime/config.py`, add to `PaymobSettings` (after `timeout_seconds`):

```python
    #: Whether Paymob honours ``PUT subscriptions/{id}`` with ``amount_cents`` (spec §10 q7).
    #: ``False`` is the fallback path: downgrades (Phase 05) and upgrades and seat reductions
    #: (Phase 06) are refused because the renewal amount cannot change. Env
    #: ``LEMELY_PAYMOB__SUBSCRIPTION_AMOUNT_UPDATABLE``.
    subscription_amount_updatable: bool = True
```

Add to `SubscriptionService` in `lemely/db/subscription_repo.py`:

```python
    # -- plan changes (spec §5.3) ---------------------------------------------

    def schedule_downgrade(
        self,
        subscription_id: uuid.UUID,
        *,
        actor_user_id: uuid.UUID,
        plan_tier_id: uuid.UUID,
        now: datetime,
    ) -> Subscription:
        """Switch to a cheaper tier at period end. The current tier clears a pending one.

        Raises:
            SubscriptionNotFound: unknown subscription, or the actor is not its payer.
            InvalidPlanChange: not an active card subscription, cancel already scheduled, or
                the target is not an active, cheaper tier of the same audience and interval.
            SeatsInsufficient: a teacher tier that cannot hold the seated students.
            DowngradeUnavailable: ``subscription_amount_updatable`` is ``False`` (fallback path).
        """
        del now
        subscription = self._payer_lock(subscription_id, actor_user_id)
        if subscription.status is not SubscriptionStatus.active or subscription.is_manually_activated:
            raise InvalidPlanChange("only an active card subscription can change plan")
        if subscription.cancel_at_period_end:
            raise InvalidPlanChange("this subscription is cancelled at period end")
        if plan_tier_id == subscription.plan_tier_id:
            subscription.pending_plan_tier_id = None
            _bump(subscription)
            return subscription
        if not self._settings.subscription_amount_updatable:
            # Paymob cannot lower the amount (plans use use_transaction_amount=true), so the
            # plan would keep renewing at the old price. Cancel stays available.
            raise DowngradeUnavailable("Plan downgrades are not available for this subscription yet.")
        current = self._session.get(PlanTier, subscription.plan_tier_id)
        target = self._session.get(PlanTier, plan_tier_id)
        if (
            target is None
            or not target.is_active
            or target.audience is not current.audience
            or target.interval is not current.interval
        ):
            raise InvalidPlanChange("choose an active plan for the same audience and interval")
        if target.price_minor >= current.price_minor:
            raise InvalidPlanChange("not a downgrade; upgrades apply immediately")
        extra = (
            subscription.pending_extra_seats
            if subscription.pending_extra_seats is not None
            else subscription.extra_seats or 0
        )
        if extra and target.extra_seat_price_minor is None:
            raise InvalidPlanChange("the new plan has no extra seats; remove them first")
        if current.audience is PlanAudience.teacher:
            capacity = seat_capacity_for(included_seats=target.included_seats, extra_seats=extra)
            in_use = _seats_in_use(self._session, subscription.user_id)
            if in_use > capacity:
                raise SeatsInsufficient(in_use=in_use, capacity=capacity)
        subscription.pending_plan_tier_id = target.id
        _bump(subscription)
        return subscription

    def schedule_cancel(
        self, subscription_id: uuid.UUID, *, actor_user_id: uuid.UUID, now: datetime
    ) -> Subscription:
        """Cancel at period end; access continues until then (spec §5.3).

        Raises:
            SubscriptionNotFound: unknown subscription, or the actor is not its payer.
            InvalidPlanChange: nothing live to cancel, or a manual activation.
        """
        del now
        subscription = self._payer_lock(subscription_id, actor_user_id)
        if subscription.status not in PLAN_LIVE_STATUSES or subscription.is_manually_activated:
            raise InvalidPlanChange("there is no live card subscription to cancel")
        subscription.cancel_at_period_end = True
        subscription.pending_plan_tier_id = None
        _bump(subscription)
        return subscription

    def next_renewal_amount(self, subscription: Subscription) -> int:
        """What Paymob should charge at the next renewal, pending changes included (index R6).

        The single source of the expected renewal amount: the period-end push, the drift check
        and (through ``paymob_amount_minor``) the renewal mismatch check all use it. Phase 06
        changes only this body for its extra-seat fallback path (seats charged separately, so
        the Paymob amount is the plan price alone); it never re-implements the comparison.
        """
        tier = self._session.get(
            PlanTier, subscription.pending_plan_tier_id or subscription.plan_tier_id
        )
        extra = (
            subscription.pending_extra_seats
            if subscription.pending_extra_seats is not None
            else subscription.extra_seats or 0
        )
        return subscription_amount_minor(
            price_minor=tier.price_minor,
            extra_seats=extra,
            extra_seat_price_minor=tier.extra_seat_price_minor,
        )

    def apply_period_end_changes(self, *, now: datetime) -> int:
        """Push pending amounts and cancels to Paymob; end cancelled plans at period end.

        Commits per subscription. Returns the number of subscriptions changed.
        """
        S = Subscription
        amount_ids = self._session.scalars(
            select(S.id).where(
                S.status == SubscriptionStatus.active,
                S.paymob_subscription_id.is_not(None),
                S.cancel_at_period_end.is_(False),
                sa.or_(S.pending_plan_tier_id.is_not(None), S.pending_extra_seats.is_not(None)),
            )
        ).all()
        cancel_ids = self._session.scalars(
            select(S.id).where(
                S.status.in_(PLAN_LIVE_STATUSES),
                S.cancel_at_period_end.is_(True),
                S.paymob_subscription_id.is_not(None),
                S.paymob_cancelled_at.is_(None),
            )
        ).all()
        end_ids = self._session.scalars(
            select(S.id).where(
                S.status.in_(PLAN_LIVE_STATUSES),
                S.cancel_at_period_end.is_(True),
                S.current_period_end <= now,
                S.paymob_subscription_id.is_not(None),  # index R15
            )
        ).all()
        changed = sum(self._sweep_one(sid, self._push_amount, now) for sid in amount_ids)
        changed += sum(self._sweep_one(sid, self._push_cancel, now) for sid in cancel_ids)
        changed += sum(self._sweep_one(sid, self._end_cancelled, now) for sid in end_ids)
        return changed

    def _payer_lock(self, subscription_id: uuid.UUID, actor_user_id: uuid.UUID) -> Subscription:
        """Lock a subscription the actor pays for; a stranger sees "not found" (no IDOR leak)."""
        subscription = self._lock(subscription_id)
        if subscription.payer_user_id != actor_user_id:
            raise SubscriptionNotFound(f"unknown subscription {subscription_id}")
        return subscription

    def sync_renewal_amount(self, subscription: Subscription) -> bool:
        """PUT ``next_renewal_amount`` to Paymob if it differs from ``paymob_amount_minor``.

        The one way any phase changes a Paymob subscription amount (index R6): it PUTs and stamps
        ``paymob_amount_minor`` in the caller's transaction. ``True`` when a PUT was made.
        Phase 06 calls it after changing ``extra_seats`` or ``pending_extra_seats`` on a locked
        row. Raises ``PaymobError`` on failure, leaving the stamp unchanged.
        """
        if subscription.paymob_subscription_id is None:
            return False
        expected = self.next_renewal_amount(subscription)
        if expected == subscription.paymob_amount_minor:
            return False
        self._client.update_subscription(subscription.paymob_subscription_id, amount_cents=expected)
        subscription.paymob_amount_minor = expected
        _bump(subscription)
        log.info("paymob_subscription_amount_set", subscription_id=str(subscription.id),
                 amount_minor=expected)
        return True

    def _push_amount(self, subscription: Subscription, now: datetime) -> bool:
        del now
        return self.sync_renewal_amount(subscription)

    def _push_cancel(self, subscription: Subscription, now: datetime) -> bool:
        return self._cancel_at_paymob(subscription, now=now)

    def _end_cancelled(self, subscription: Subscription, now: datetime) -> bool:
        if (
            not subscription.cancel_at_period_end
            or subscription.status not in PLAN_LIVE_STATUSES
            or subscription.current_period_end is None
            or subscription.current_period_end > now
        ):
            return False
        subscription.status = SubscriptionStatus.cancelled
        subscription.grace_until = None
        _bump(subscription)
        enqueue_subscription_notice(
            self._session,
            subscription=subscription,
            notice="cancelled",
            effective_at=subscription.current_period_end,
        )
        log.info("subscription_cancelled_at_period_end", subscription_id=str(subscription.id))
        return True
```

`_cancel_at_paymob` swallows `PaymobError` and returns `False`, so `_push_cancel` counts only real
cancels. `_push_amount` lets `PaymobError` reach `_sweep_one`, which rolls the row back and logs.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest --no-cov tests/test_subscription_plan_changes.py tests/test_subscription_lifecycle.py tests/test_subscription_renewal.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add lemely/db/subscription_repo.py lemely/runtime/config.py tests/test_subscription_plan_changes.py
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files
git commit -S -m "feat(billing): downgrade and cancel at period end" -- \
  lemely/db/subscription_repo.py lemely/runtime/config.py tests/test_subscription_plan_changes.py
```

---

### Task 9: Daily drift check

**Files:**
- Modify: `lemely/db/subscription_repo.py`
- Test: `tests/test_subscription_drift.py` (create)

**Interfaces:**
- Consumes: Task 6 `_apply_successful_charge`; Task 7 `_on_canceled`, `_on_suspended`, `_cancel_at_paymob`, `_sweep_one`; Task 8 `next_renewal_amount`; `PaymobClient.get_subscription`, `.last_transaction`, `.update_subscription`.
- Produces: `SubscriptionService.check_drift(self, *, now: datetime) -> int` (commits per subscription; returns the number repaired).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_subscription_drift.py`:

```python
"""The daily drift check repairs what missed webhooks left behind (spec §5.2 Daily job)."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa

from lemely.db.models.billing import Payment, PaymentPurpose, Subscription
from lemely.db.models.enums import Role, SubscriptionStatus
from lemely.db.subscription_repo import SubscriptionService
from tests.subscription_fixtures import (
    T0,
    FakePaymobClient,
    charge,
    paymob_settings,
    remote_subscription,
    seed_first_payment,
    seed_subscription,
    seed_tier,
    seed_user,
    throwaway_database,
)

if TYPE_CHECKING:
    import uuid
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker

PID = 4321
END = T0 + timedelta(days=30)
DAY = END + timedelta(hours=6)


@pytest.fixture
def pg_sessionmaker() -> Iterator[sessionmaker[Session]]:
    yield from throwaway_database()


def _linked(sm: sessionmaker[Session], pid: int = PID, **kwargs: object) -> uuid.UUID:
    student = seed_user(sm, Role.student)
    sid = seed_subscription(sm, user_id=student, tier_id=seed_tier(sm), payer_id=student,
                            paymob_subscription_id=pid, paymob_amount_minor=10_000, **kwargs)
    seed_first_payment(sm, subscription_id=sid, paymob_txn_id=700 + pid)
    return sid


def _client(pid: int = PID, *, state: str = "active", amount: int = 10_000, last: dict | None = None) -> FakePaymobClient:
    client = FakePaymobClient()
    client.subscriptions[pid] = remote_subscription(pid, state=state, amount_cents=amount)
    client.last_transactions[pid] = last or charge(700 + pid, 10_000)  # the first payment
    return client


def _drift(sm: sessionmaker[Session], client: FakePaymobClient) -> int:
    with sm() as session:
        return SubscriptionService(session, client, paymob_settings()).check_drift(now=DAY)


def _sub(sm: sessionmaker[Session], sid: uuid.UUID) -> Subscription:
    with sm() as session:
        return session.get(Subscription, sid)


def test_in_sync_subscription_needs_no_repair(pg_sessionmaker: sessionmaker[Session]) -> None:
    _linked(pg_sessionmaker)
    client = _client()
    assert _drift(pg_sessionmaker, client) == 0
    assert "update_subscription" not in client.names()


def test_missed_renewal_is_applied(pg_sessionmaker: sessionmaker[Session]) -> None:
    sid = _linked(pg_sessionmaker)
    client = _client(last=charge(888, 10_000, created_at=END - timedelta(hours=1)))
    assert _drift(pg_sessionmaker, client) == 1
    assert _sub(pg_sessionmaker, sid).current_period_end == END + timedelta(days=30)
    with pg_sessionmaker() as session:
        assert session.scalar(sa.select(sa.func.count()).select_from(Payment).where(
            Payment.purpose == PaymentPurpose.subscription_renewal)) == 1
    assert _drift(pg_sessionmaker, client) == 0  # the second day repeats nothing


def test_external_cancel_is_mirrored(pg_sessionmaker: sessionmaker[Session]) -> None:
    sid = _linked(pg_sessionmaker)
    assert _drift(pg_sessionmaker, _client(state="canceled")) == 1
    assert _sub(pg_sessionmaker, sid).status is SubscriptionStatus.cancelled


def test_expected_paymob_cancel_is_not_drift(pg_sessionmaker: sessionmaker[Session]) -> None:
    _linked(pg_sessionmaker, cancel_at_period_end=True, paymob_cancelled_at=T0 + timedelta(days=2))
    assert _drift(pg_sessionmaker, _client(state="canceled")) == 0


def test_suspension_is_mirrored(pg_sessionmaker: sessionmaker[Session]) -> None:
    sid = _linked(pg_sessionmaker, period_end=DAY + timedelta(days=5))
    assert _drift(pg_sessionmaker, _client(state="suspended")) == 1
    assert _sub(pg_sessionmaker, sid).status is SubscriptionStatus.past_due


def test_amount_drift_is_put_back(pg_sessionmaker: sessionmaker[Session]) -> None:
    _linked(pg_sessionmaker)
    client = _client(amount=12_345)
    assert _drift(pg_sessionmaker, client) == 1
    assert ("update_subscription", {"subscription_id": PID, "amount_cents": 10_000}) in client.calls


def test_failed_cancel_of_an_expired_subscription_is_retried(pg_sessionmaker: sessionmaker[Session]) -> None:
    sid = _linked(pg_sessionmaker, status=SubscriptionStatus.expired)
    client = _client()
    assert _drift(pg_sessionmaker, client) == 1
    assert client.names() == ["get_subscription", "cancel_subscription"]
    assert _sub(pg_sessionmaker, sid).paymob_cancelled_at == DAY
    assert _drift(pg_sessionmaker, client) == 0  # no longer a candidate


def test_one_paymob_failure_does_not_stop_the_rest(pg_sessionmaker: sessionmaker[Session]) -> None:
    _linked(pg_sessionmaker, pid=1)
    good = _linked(pg_sessionmaker, pid=2)
    client = _client(pid=1)
    client.subscriptions[2] = remote_subscription(2, state="canceled")
    client.last_transactions[2] = charge(702, 10_000)
    client.fail_for = {1}
    assert _drift(pg_sessionmaker, client) == 1
    assert _sub(pg_sessionmaker, good).status is SubscriptionStatus.cancelled


def test_manual_activation_is_untouched_by_every_sweep(pg_sessionmaker: sessionmaker[Session]) -> None:
    student = seed_user(pg_sessionmaker, Role.student)
    sid = seed_subscription(pg_sessionmaker, user_id=student, tier_id=seed_tier(pg_sessionmaker),
                            is_manually_activated=True, period_start=None, period_end=None)
    client = FakePaymobClient()
    with pg_sessionmaker() as session:
        svc = SubscriptionService(session, client, paymob_settings())
        assert svc.expire_overdue(now=DAY) == 0
        assert svc.apply_period_end_changes(now=DAY) == 0
        assert svc.check_drift(now=DAY) == 0
    assert client.calls == []
    assert _sub(pg_sessionmaker, sid).status is SubscriptionStatus.active
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest --no-cov tests/test_subscription_drift.py -v`
Expected: FAIL — `AttributeError: ... 'check_drift'`.

- [ ] **Step 3: Implement**

Add to `SubscriptionService`:

```python
    # -- daily drift check (spec §5.2) ----------------------------------------

    def check_drift(self, *, now: datetime) -> int:
        """Compare each linked subscription with Paymob and repair drift. Commits per row.

        Candidates: live subscriptions with a Paymob id, and ended ones whose Paymob cancel has
        not been confirmed. Repairs: a missed renewal, a Paymob-side cancel or suspension, an
        amount Paymob holds that differs from Lemely's, and a Paymob subscription still open
        after Lemely ended the plan.
        """
        S = Subscription
        ids = self._session.scalars(
            select(S.id).where(
                S.paymob_subscription_id.is_not(None),
                sa.or_(
                    S.status.in_(PLAN_LIVE_STATUSES),
                    sa.and_(
                        S.status.in_((SubscriptionStatus.expired, SubscriptionStatus.cancelled)),
                        S.paymob_cancelled_at.is_(None),
                    ),
                ),
            )
        ).all()
        return sum(self._sweep_one(sid, self._repair_drift, now) for sid in ids)

    def _repair_drift(self, subscription: Subscription, now: datetime) -> bool:
        paymob_id = subscription.paymob_subscription_id
        remote = self._client.get_subscription(paymob_id)
        state = remote.get("state")
        if subscription.status not in PLAN_LIVE_STATUSES:
            if state == "canceled":
                subscription.paymob_cancelled_at = now
                return True
            return self._cancel_at_paymob(subscription, now=now)
        if state == "canceled":
            if subscription.cancel_at_period_end and subscription.paymob_cancelled_at is not None:
                return False
            self._on_canceled(subscription, remote, now)
            log.warning("subscription_drift_repaired", subscription_id=str(subscription.id),
                        kind="canceled")
            return True
        if state == "suspended" and subscription.status is SubscriptionStatus.active:
            self._on_suspended(subscription, remote, now)
            log.warning("subscription_drift_repaired", subscription_id=str(subscription.id),
                        kind="suspended")
            return True
        repaired = self._apply_successful_charge(
            subscription, self._client.last_transaction(paymob_id), now=now
        )
        remote_amount = remote.get("amount_cents")
        expected = self.next_renewal_amount(subscription)
        if (
            not subscription.cancel_at_period_end
            and remote_amount is not None
            and int(remote_amount) != expected
        ):
            self._client.update_subscription(paymob_id, amount_cents=expected)
            subscription.paymob_amount_minor = expected
            _bump(subscription)
            repaired = True
        if repaired:
            log.warning("subscription_drift_repaired", subscription_id=str(subscription.id),
                        kind="charge_or_amount")
        return repaired
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest --no-cov tests/test_subscription_drift.py tests/test_subscription_lifecycle.py tests/test_subscription_plan_changes.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add lemely/db/subscription_repo.py tests/test_subscription_drift.py
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files
git commit -S -m "feat(billing): daily Paymob subscription drift check" -- \
  lemely/db/subscription_repo.py tests/test_subscription_drift.py
```

---

### Task 10: Monthly seat allowances and the seat-claim hook

**Files:**
- Create: `lemely/db/seat_allowance_repo.py`
- Modify: `lemely/db/teacher_team_repo.py` (end of `claim_seat_for_class_join`)
- Test: `tests/test_seat_allowances.py` (create)

**Interfaces:**
- Consumes: Phase 01 `UsageLedger.issue_grant`, `prorate_units`, `UsageGrant`, `UsageGrantBalance`; Phase 03 `TeacherMember`, `TeacherTeamService.claim_seat_for_class_join`; Task 3 `calendar_month_bounds`, `start_of_day`; Task 1 `PLAN_LIVE_STATUSES`.
- Produces:
  - `seat_grant_key(member_id: UUID, month_start: datetime) -> str` (`"seat:{member_id}:{YYYY-MM}"`).
  - `grant_seat_allowance_on_claim(session: Session, member_id: UUID, *, now: datetime) -> UsageGrant | None`.
  - `grant_monthly_seat_allowances(session: Session, *, now: datetime) -> int` (the caller commits).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_seat_allowances.py`:

```python
"""Seat allowances: one grant per active seat per calendar month while the plan lives (§5.9)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from lemely.db.models.billing import PlanAudience
from lemely.db.models.enums import PlanInterval, Role, SubscriptionStatus
from lemely.db.models.orgs import SchoolClass
from lemely.db.models.team import TeacherMemberStatus
from lemely.db.models.usage import GrantKind, UsageGrantBalance
from lemely.db.seat_allowance_repo import (
    grant_monthly_seat_allowances,
    grant_seat_allowance_on_claim,
    seat_grant_key,
)
from lemely.db.teacher_team_repo import TeacherTeamService
from lemely.db.usage_ledger_repo import UsageLedger
from tests.subscription_fixtures import (
    grants_of,
    seed_debt,
    seed_seat,
    seed_subscription,
    seed_tier,
    seed_user,
    throwaway_database,
)

if TYPE_CHECKING:
    import uuid
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker

DEC_1 = datetime(2026, 12, 1, 0, 5, tzinfo=UTC)
JAN_1 = datetime(2027, 1, 1, tzinfo=UTC)
NOV_21 = datetime(2026, 11, 21, 15, 0, tzinfo=UTC)


@pytest.fixture
def pg_sessionmaker() -> Iterator[sessionmaker[Session]]:
    yield from throwaway_database()


def _teacher(sm: sessionmaker[Session], *, status: SubscriptionStatus = SubscriptionStatus.active,
             interval: PlanInterval = PlanInterval.monthly, units: int = 300) -> uuid.UUID:
    teacher = seed_user(sm, Role.teacher)
    tier = seed_tier(sm, audience=PlanAudience.teacher, interval=interval, included_seats=5,
                     seat_allowance_units=units)
    seed_subscription(sm, user_id=teacher, tier_id=tier, payer_id=teacher, status=status)
    return teacher


def _monthly(sm: sessionmaker[Session], now: datetime) -> int:
    with sm.begin() as session:
        return grant_monthly_seat_allowances(session, now=now)


def test_month_start_grants_each_active_seat_in_full(pg_sessionmaker: sessionmaker[Session]) -> None:
    teacher = _teacher(pg_sessionmaker)
    a, b, c, d = (seed_user(pg_sessionmaker, Role.student) for _ in range(4))
    seat_a = seed_seat(pg_sessionmaker, teacher_id=teacher, student_id=a)
    seed_seat(pg_sessionmaker, teacher_id=teacher, student_id=b)
    seed_seat(pg_sessionmaker, teacher_id=teacher, student_id=c, status=TeacherMemberStatus.leaving)
    seed_seat(pg_sessionmaker, teacher_id=teacher, student_id=d, status=TeacherMemberStatus.removed)

    assert _monthly(pg_sessionmaker, DEC_1) == 2
    [grant] = grants_of(pg_sessionmaker, a)
    assert grant.kind is GrantKind.seat_allowance
    assert (grant.units, grant.visible, grant.teacher_member_id) == (300, False, seat_a)
    assert grant.expires_at == JAN_1
    assert grant.idempotency_key == seat_grant_key(seat_a, datetime(2026, 12, 1, tzinfo=UTC))
    assert grants_of(pg_sessionmaker, c) == [] and grants_of(pg_sessionmaker, d) == []
    assert _monthly(pg_sessionmaker, DEC_1) == 0  # dedupe (teacher_member_id, month_start)


def test_yearly_and_past_due_plans_grant_monthly(pg_sessionmaker: sessionmaker[Session]) -> None:
    yearly = _teacher(pg_sessionmaker, interval=PlanInterval.yearly)
    grace = _teacher(pg_sessionmaker, status=SubscriptionStatus.past_due)
    for teacher in (yearly, grace):
        seed_seat(pg_sessionmaker, teacher_id=teacher, student_id=seed_user(pg_sessionmaker, Role.student))
    assert _monthly(pg_sessionmaker, DEC_1) == 2


@pytest.mark.parametrize("status", [SubscriptionStatus.expired, SubscriptionStatus.cancelled])
def test_lapsed_plan_grants_nothing(pg_sessionmaker: sessionmaker[Session], status: SubscriptionStatus) -> None:
    teacher = _teacher(pg_sessionmaker, status=status)
    seed_seat(pg_sessionmaker, teacher_id=teacher, student_id=seed_user(pg_sessionmaker, Role.student))
    assert _monthly(pg_sessionmaker, DEC_1) == 0


def test_mid_month_claim_is_prorated_to_the_days_left(pg_sessionmaker: sessionmaker[Session]) -> None:
    teacher = _teacher(pg_sessionmaker)
    student = seed_user(pg_sessionmaker, Role.student)
    seat = seed_seat(pg_sessionmaker, teacher_id=teacher, student_id=student)
    with pg_sessionmaker.begin() as session:
        grant = grant_seat_allowance_on_claim(session, seat, now=NOV_21)
    # November has 30 days; 21..30 inclusive is 10 days left: ceil(300 * 10 / 30) = 100.
    assert grant is not None and grant.units == 100
    with pg_sessionmaker.begin() as session:
        again = grant_seat_allowance_on_claim(session, seat, now=NOV_21)
    assert again is not None and again.id == grant.id
    assert len(grants_of(pg_sessionmaker, student)) == 1


def test_seat_grant_never_repays_the_students_own_debt(pg_sessionmaker: sessionmaker[Session]) -> None:
    """Index R13: teacher-funded seat units never pay the student's own debt."""
    teacher = _teacher(pg_sessionmaker)
    student = seed_user(pg_sessionmaker, Role.student)
    seat = seed_seat(pg_sessionmaker, teacher_id=teacher, student_id=student)
    seed_debt(pg_sessionmaker, student, 50)
    with pg_sessionmaker.begin() as session:
        grant = grant_seat_allowance_on_claim(session, seat, now=DEC_1)
    with pg_sessionmaker() as session:
        assert session.get(UsageGrantBalance, grant.id).remaining == 300
        assert UsageLedger(session).has_debt(student)


def test_class_join_claim_issues_the_seat_allowance(pg_sessionmaker: sessionmaker[Session]) -> None:
    teacher = _teacher(pg_sessionmaker)
    student = seed_user(pg_sessionmaker, Role.student)
    with pg_sessionmaker.begin() as session:
        klass = SchoolClass(teacher_id=teacher, name="Maths 10A", subject_code=None, join_code="JOIN10A")
        session.add(klass)
        session.flush()
        member = TeacherTeamService(session).claim_seat_for_class_join(
            student_user_id=student, class_id=klass.id, now=NOV_21)
    [grant] = grants_of(pg_sessionmaker, student)
    assert (grant.teacher_member_id, grant.units) == (member.id, 100)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest --no-cov tests/test_seat_allowances.py -v`
Expected: FAIL — `No module named 'lemely.db.seat_allowance_repo'`.

- [ ] **Step 3: Implement the module**

Create `lemely/db/seat_allowance_repo.py`:

```python
"""Monthly seat allowances for seated students (Paymob billing spec §2.2, §5.9).

While a teacher's plan is live (``active`` or ``past_due``; monthly or yearly), each active
``student_seat`` gets one ``seat_allowance`` grant per UTC calendar month. The grant is owned by
the student, carries the ``teacher_member_id`` (so it pays only for in-scope work) and expires at
the month end. A seat claimed mid-month gets an allowance prorated to the days left, today
included. The idempotency key ``seat:{member_id}:{YYYY-MM}`` is the dedupe
``(teacher_member_id, month_start)``. A lapsed plan issues nothing; existing grants run out.

Both functions write in the caller's session and never commit.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
import structlog
from sqlalchemy import select

from lemely.core.subscription_rules import calendar_month_bounds, start_of_day
from lemely.core.usage_pricing import prorate_units
from lemely.db.models.billing import PLAN_LIVE_STATUSES, PlanAudience, PlanTier, Subscription
from lemely.db.models.team import TeacherMember, TeacherMemberKind, TeacherMemberStatus
from lemely.db.models.usage import GrantKind, UsageGrant
from lemely.db.usage_ledger_repo import UsageLedger

if TYPE_CHECKING:
    import uuid
    from datetime import datetime

    from sqlalchemy.orm import Session

log = structlog.get_logger(__name__)


def seat_grant_key(member_id: uuid.UUID, month_start: datetime) -> str:
    """The grant idempotency key for one seat and one month."""
    return f"seat:{member_id}:{month_start:%Y-%m}"


def _live_teacher_tier(session: Session, teacher_user_id: uuid.UUID) -> PlanTier | None:
    return session.scalars(
        select(PlanTier)
        .join(Subscription, Subscription.plan_tier_id == PlanTier.id)
        .where(
            Subscription.user_id == teacher_user_id,
            Subscription.status.in_(PLAN_LIVE_STATUSES),
            PlanTier.audience == PlanAudience.teacher,
        )
        .limit(1)
    ).one_or_none()


def grant_seat_allowance_on_claim(
    session: Session, member_id: uuid.UUID, *, now: datetime
) -> UsageGrant | None:
    """This month's seat allowance for one seat, prorated to the days left; idempotent.

    ``None`` when the member is not an active seat, the teacher's plan is not live, the tier
    has no seat allowance, or the prorated amount is zero.
    """
    member = session.get(TeacherMember, member_id)
    if (
        member is None
        or member.kind is not TeacherMemberKind.student_seat
        or member.status is not TeacherMemberStatus.active
    ):
        return None
    tier = _live_teacher_tier(session, member.teacher_user_id)
    if tier is None or not tier.seat_allowance_units:
        return None
    month_start, month_end = calendar_month_bounds(now)
    units = prorate_units(
        tier.seat_allowance_units, month_start, month_end, max(start_of_day(now), month_start)
    )
    if units <= 0:
        return None
    grant = UsageLedger(session).issue_grant(
        owner_user_id=member.member_user_id,
        kind=GrantKind.seat_allowance,
        units=units,
        idempotency_key=seat_grant_key(member.id, month_start),
        expires_at=month_end,
        visible=False,
        effective_at=now,
        teacher_member_id=member.id,
    )
    log.info("seat_allowance_granted", teacher_member_id=str(member.id), units=units)
    return grant


def grant_monthly_seat_allowances(session: Session, *, now: datetime) -> int:
    """Grant this month's allowance to every active seat of a live teacher plan that lacks one.

    Returns the number of grants issued. Safe to run every sweep: the anti-join skips seats
    already granted for this month, and the idempotency key makes a race harmless.
    """
    _, month_end = calendar_month_bounds(now)
    live_teachers = (
        select(Subscription.user_id)
        .join(PlanTier, PlanTier.id == Subscription.plan_tier_id)
        .where(
            Subscription.status.in_(PLAN_LIVE_STATUSES),
            PlanTier.audience == PlanAudience.teacher,
            PlanTier.seat_allowance_units > 0,
        )
    )
    candidates = session.scalars(
        select(TeacherMember.id)
        .where(
            TeacherMember.kind == TeacherMemberKind.student_seat,
            TeacherMember.status == TeacherMemberStatus.active,
            TeacherMember.teacher_user_id.in_(live_teachers),
            ~sa.exists().where(
                UsageGrant.teacher_member_id == TeacherMember.id,
                UsageGrant.kind == GrantKind.seat_allowance,
                UsageGrant.expires_at == month_end,
            ),
        )
        .order_by(TeacherMember.created_at, TeacherMember.id)
    ).all()
    issued = 0
    for member_id in candidates:
        if grant_seat_allowance_on_claim(session, member_id, now=now) is not None:
            issued += 1
    return issued


__all__ = ["grant_monthly_seat_allowances", "grant_seat_allowance_on_claim", "seat_grant_key"]
```

- [ ] **Step 4: Hook the claim**

In `lemely/db/teacher_team_repo.py`, add `from lemely.db.seat_allowance_repo import
grant_seat_allowance_on_claim`. In `claim_seat_for_class_join` (Phase 03 left a `del now` and two
returns for this hook):

1. Delete the line `del now  # the claim itself is instant-independent; Phase 05 adds the allowance`.
2. In the branch that re-uses a seat, replace `return existing` with:

```python
            grant_seat_allowance_on_claim(self._session, existing.id, now=now)
            return existing
```

3. Replace the final `return member` (after `self._session.flush()`) with:

```python
        grant_seat_allowance_on_claim(self._session, member.id, now=now)
        return member
```

Replace the docstring sentence "``now`` is the claim instant, passed on to Phase 05's
seat-allowance-on-claim hook." with "Issues this month's prorated seat allowance for the claim
instant ``now`` (spec §5.9); idempotent for a re-used seat." The re-use branch also covers a
`leaving` seat: `grant_seat_allowance_on_claim` returns `None` for it, because only `active` seats
are granted.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest --no-cov tests/test_seat_allowances.py tests/test_teacher_team_repo.py tests/architecture/ -v`
Expected: PASS. (`tests/test_teacher_team_repo.py` is Phase 03's; use its actual name from
`ls tests | grep -i team`.) `test_seat_grant_never_repays_the_students_own_debt` pins index R13;
if it fails, Phase 01's `issue_grant` is wrong, not this test.

- [ ] **Step 6: Commit**

```bash
git add lemely/db/seat_allowance_repo.py lemely/db/teacher_team_repo.py tests/test_seat_allowances.py
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files
git commit -S -m "feat(billing): monthly and on-claim seat allowances" -- \
  lemely/db/seat_allowance_repo.py lemely/db/teacher_team_repo.py tests/test_seat_allowances.py
```

---

### Task 11: HTTP routes — checkout, plan changes, list, subscription webhook

**Files:**
- Create: `lemely/web/subscription_deps.py`, `lemely/web/schemas_subscriptions.py`, `tests/test_web_subscriptions.py`
- Modify: `lemely/web/deps_billing.py`, `lemely/web/routers/billing.py`, `lemely/web/routers/paymob_webhooks.py`, `lemely/db/subscription_repo.py` (add `list_for_user`)

**Interfaces:**
- Consumes: all `SubscriptionService` methods; `verify_subscription_hmac`; Phase 02 `get_paymob_client`; `require_role`, `AuthContext`; `SlidingWindowLimiter`.
- Produces:
  - `lemely.web.subscription_deps.SubscriptionDeps(sessionmaker, client, settings)` with `.service(session) -> SubscriptionService`.
  - `lemely.web.deps_billing.get_subscription_deps() -> SubscriptionDeps`, `lemely.web.deps_billing.get_subscription_checkout_limiter() -> SlidingWindowLimiter` (10 per user per 10 minutes).
  - `SubscriptionService.list_for_user(self, user_id: UUID) -> list[tuple[Subscription, PlanTier]]`.
  - Routes (paths relative to Phase 02's routers): `POST {billing}/subscriptions/checkout` → 201 `{subscriptionId, paymentId, checkoutUrl}`; `GET {billing}/subscriptions` → `{subscriptions: [SubscriptionDTO]}`; `POST {billing}/subscriptions/{id}/downgrade` body `{planTierId}` → `SubscriptionDTO`; `POST {billing}/subscriptions/{id}/cancel` → `SubscriptionDTO`; `POST {webhooks}/subscription` → `{"ok": true}`.
  - Error body: `{"detail": {"error": <code>, "message": <text>}}`; `seats_insufficient` adds `inUse` and `capacity`. Status map: `already_subscribed` 409, `seats_insufficient` 409, `not_linked_parent` 403, `subscription_not_found` 404, `plan_not_purchasable`/`invalid_extra_seats`/`invalid_plan_change` 422, Paymob failure 503 `payments_unavailable`, limiter 429.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_web_subscriptions.py`:

```python
"""Subscription routes and the Paymob subscription webhook (spec §5.1-§5.3, §6, §7)."""

from __future__ import annotations

import time
import uuid
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from lemely.db.models.billing import PaymobEvent, PlanAudience, Subscription
from lemely.db.models.enums import Role, SubscriptionStatus
from lemely.db.subscription_repo import SUBSCRIPTION_WEBHOOK_PATH
from lemely.web.app import create_app
from lemely.web.deps import AuthContext, get_auth_context
from lemely.web.deps_billing import get_subscription_checkout_limiter, get_subscription_deps
from lemely.web.ratelimit import SlidingWindowLimiter
from lemely.web.routers import billing as billing_router
from lemely.web.routers import paymob_webhooks
from lemely.web.subscription_deps import SubscriptionDeps
from tests.subscription_fixtures import (
    FakePaymobClient,
    link_parent,
    paymob_settings,
    remote_subscription,
    seed_seat,
    seed_subscription,
    seed_tier,
    seed_user,
    subscription_webhook,
    throwaway_database,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker

BILLING = billing_router.router.prefix
WEBHOOK = paymob_webhooks.router.prefix + "/subscription"
PID = 4321


@pytest.fixture
def pg_sessionmaker() -> Iterator[sessionmaker[Session]]:
    yield from throwaway_database()


class Harness:
    def __init__(self, sm: sessionmaker[Session], limit: int = 100) -> None:
        self.client_fake = FakePaymobClient()
        self.app = create_app()
        self.app.dependency_overrides[get_subscription_deps] = lambda: SubscriptionDeps(
            sm, self.client_fake, paymob_settings())
        limiter = SlidingWindowLimiter(limit=limit, window_seconds=600, clock=time.monotonic)
        self.app.dependency_overrides[get_subscription_checkout_limiter] = lambda: limiter
        self.http = TestClient(self.app)

    def as_user(self, user_id: uuid.UUID, role: Role) -> Harness:
        self.app.dependency_overrides[get_auth_context] = lambda: AuthContext(
            user_id=str(user_id), role=role.value)
        return self


def test_webhook_path_matches_the_plan_webhook_url() -> None:
    assert WEBHOOK == SUBSCRIPTION_WEBHOOK_PATH


def test_checkout_creates_a_pending_subscription(pg_sessionmaker: sessionmaker[Session]) -> None:
    student = seed_user(pg_sessionmaker, Role.student)
    tier = seed_tier(pg_sessionmaker)
    h = Harness(pg_sessionmaker).as_user(student, Role.student)
    response = h.http.post(f"{BILLING}/subscriptions/checkout", json={"planTierId": str(tier)})
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["checkoutUrl"].startswith("https://")
    with pg_sessionmaker() as session:
        sub = session.get(Subscription, uuid.UUID(body["subscriptionId"]))
        assert sub.status is SubscriptionStatus.pending_first_payment  # committed


def test_checkout_error_mapping(pg_sessionmaker: sessionmaker[Session]) -> None:
    parent = seed_user(pg_sessionmaker, Role.parent)
    child = seed_user(pg_sessionmaker, Role.student)
    student = seed_user(pg_sessionmaker, Role.student)
    tier = seed_tier(pg_sessionmaker)
    teacher_tier = seed_tier(pg_sessionmaker, audience=PlanAudience.teacher)
    h = Harness(pg_sessionmaker)

    r = h.as_user(parent, Role.parent).http.post(
        f"{BILLING}/subscriptions/checkout", json={"planTierId": str(tier), "beneficiaryId": str(child)})
    assert (r.status_code, r.json()["detail"]["error"]) == (403, "not_linked_parent")
    link_parent(pg_sessionmaker, parent, child)
    r = h.http.post(f"{BILLING}/subscriptions/checkout",
                    json={"planTierId": str(tier), "beneficiaryId": str(child)})
    assert r.status_code == 201

    r = h.as_user(student, Role.student).http.post(
        f"{BILLING}/subscriptions/checkout", json={"planTierId": str(teacher_tier)})
    assert (r.status_code, r.json()["detail"]["error"]) == (422, "plan_not_purchasable")
    seed_subscription(pg_sessionmaker, user_id=student, tier_id=tier, payer_id=student)
    r = h.http.post(f"{BILLING}/subscriptions/checkout", json={"planTierId": str(tier)})
    assert (r.status_code, r.json()["detail"]["error"]) == (409, "already_subscribed")


def test_checkout_answers_503_when_paymob_is_down(pg_sessionmaker: sessionmaker[Session]) -> None:
    student = seed_user(pg_sessionmaker, Role.student)
    tier = seed_tier(pg_sessionmaker)
    h = Harness(pg_sessionmaker).as_user(student, Role.student)
    h.client_fake.failing = {"create_intention"}
    r = h.http.post(f"{BILLING}/subscriptions/checkout", json={"planTierId": str(tier)})
    assert (r.status_code, r.json()["detail"]["error"]) == (503, "payments_unavailable")
    h.client_fake.failing = set()
    r = h.http.post(f"{BILLING}/subscriptions/checkout", json={"planTierId": str(tier)})
    assert r.status_code == 201  # the failed checkout does not block the retry
    with pg_sessionmaker() as session:
        statuses = sorted(s.status.value for s in session.scalars(sa.select(Subscription)))
    assert statuses == ["expired", "pending_first_payment"]


def test_checkout_is_rate_limited_and_role_gated(pg_sessionmaker: sessionmaker[Session]) -> None:
    student = seed_user(pg_sessionmaker, Role.student)
    tier = seed_tier(pg_sessionmaker, is_active=False)
    h = Harness(pg_sessionmaker, limit=1).as_user(student, Role.student)
    assert h.http.post(f"{BILLING}/subscriptions/checkout", json={"planTierId": str(tier)}).status_code == 422
    assert h.http.post(f"{BILLING}/subscriptions/checkout", json={"planTierId": str(tier)}).status_code == 429
    admin = seed_user(pg_sessionmaker, Role.school_admin)
    r = h.as_user(admin, Role.school_admin).http.post(
        f"{BILLING}/subscriptions/checkout", json={"planTierId": str(tier)})
    assert r.status_code == 403


def test_list_shows_only_my_subscriptions(pg_sessionmaker: sessionmaker[Session]) -> None:
    parent = seed_user(pg_sessionmaker, Role.parent)
    child = seed_user(pg_sessionmaker, Role.student)
    stranger = seed_user(pg_sessionmaker, Role.student)
    tier = seed_tier(pg_sessionmaker)
    mine = seed_subscription(pg_sessionmaker, user_id=child, tier_id=tier, payer_id=parent)
    seed_subscription(pg_sessionmaker, user_id=stranger, tier_id=tier, payer_id=stranger)
    h = Harness(pg_sessionmaker)
    for user, role, is_payer in ((parent, Role.parent, True), (child, Role.student, False)):
        rows = h.as_user(user, role).http.get(f"{BILLING}/subscriptions").json()["subscriptions"]
        assert [(r["id"], r["isPayer"]) for r in rows] == [(str(mine), is_payer)]


def test_downgrade_and_cancel_routes(pg_sessionmaker: sessionmaker[Session]) -> None:
    teacher = seed_user(pg_sessionmaker, Role.teacher)
    big = seed_tier(pg_sessionmaker, audience=PlanAudience.teacher, price_minor=50_000, included_seats=5)
    small = seed_tier(pg_sessionmaker, audience=PlanAudience.teacher, price_minor=30_000, included_seats=1)
    sid = seed_subscription(pg_sessionmaker, user_id=teacher, tier_id=big, payer_id=teacher,
                            paymob_subscription_id=PID, paymob_amount_minor=50_000)
    for _ in range(2):
        seed_seat(pg_sessionmaker, teacher_id=teacher, student_id=seed_user(pg_sessionmaker, Role.student))
    h = Harness(pg_sessionmaker).as_user(teacher, Role.teacher)

    r = h.http.post(f"{BILLING}/subscriptions/{sid}/downgrade", json={"planTierId": str(small)})
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert (detail["error"], detail["inUse"], detail["capacity"]) == ("seats_insufficient", 2, 1)
    r = h.http.post(f"{BILLING}/subscriptions/{sid}/cancel")
    assert r.status_code == 200 and r.json()["cancelAtPeriodEnd"] is True

    stranger = seed_user(pg_sessionmaker, Role.teacher)
    r = h.as_user(stranger, Role.teacher).http.post(f"{BILLING}/subscriptions/{sid}/cancel")
    assert (r.status_code, r.json()["detail"]["error"]) == (404, "subscription_not_found")


def test_webhook_applies_a_verified_callback_after_commit(pg_sessionmaker: sessionmaker[Session]) -> None:
    student = seed_user(pg_sessionmaker, Role.student)
    sid = seed_subscription(pg_sessionmaker, user_id=student, tier_id=seed_tier(pg_sessionmaker),
                            payer_id=student, paymob_subscription_id=PID, paymob_amount_minor=10_000)
    h = Harness(pg_sessionmaker)
    h.client_fake.subscriptions[PID] = remote_subscription(PID)
    r = h.http.post(WEBHOOK, json=subscription_webhook("Failed Transaction", PID))
    assert r.status_code == 200 and r.json() == {"ok": True}
    with pg_sessionmaker() as session:
        assert session.get(Subscription, sid).status is SubscriptionStatus.past_due


def test_webhook_rejects_a_forged_hmac_and_stores_nothing(pg_sessionmaker: sessionmaker[Session]) -> None:
    h = Harness(pg_sessionmaker)
    forged = subscription_webhook("Successful Transaction", PID, secret="wrong")
    assert h.http.post(WEBHOOK, json=forged).status_code == 401
    tampered = subscription_webhook("Failed Transaction", PID)
    tampered["trigger_type"] = "Successful Transaction"  # HMAC binds the trigger
    assert h.http.post(WEBHOOK, json=tampered).status_code == 401
    assert h.http.post(WEBHOOK, json={"trigger_type": "x"}).status_code == 400
    with pg_sessionmaker() as session:
        assert session.scalars(sa.select(PaymobEvent)).all() == []
    assert h.client_fake.calls == []


def test_webhook_answers_503_and_rolls_back_when_paymob_is_down(pg_sessionmaker: sessionmaker[Session]) -> None:
    h = Harness(pg_sessionmaker)
    h.client_fake.failing = {"get_subscription"}
    body = subscription_webhook("Failed Transaction", PID, request_id="r-1")
    assert h.http.post(WEBHOOK, json=body).status_code == 503
    with pg_sessionmaker() as session:
        assert session.scalars(sa.select(PaymobEvent)).all() == []  # Paymob's retry is processed
    h.client_fake.failing = set()
    h.client_fake.subscriptions[PID] = remote_subscription(PID)
    assert h.http.post(WEBHOOK, json=body).status_code == 200
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest --no-cov tests/test_web_subscriptions.py -v`
Expected: FAIL — `cannot import name 'get_subscription_deps'`.

- [ ] **Step 3: Add `list_for_user` to the service**

In `lemely/db/subscription_repo.py`, add to `SubscriptionService`:

```python
    def list_for_user(self, user_id: uuid.UUID) -> list[tuple[Subscription, PlanTier]]:
        """Subscriptions the user pays for or benefits from, newest first.

        Abandoned checkouts (expired without ever activating) are left out.
        """
        rows = self._session.execute(
            select(Subscription, PlanTier)
            .join(PlanTier, PlanTier.id == Subscription.plan_tier_id)
            .where(
                sa.or_(Subscription.payer_user_id == user_id, Subscription.user_id == user_id),
                sa.not_(
                    sa.and_(
                        Subscription.status == SubscriptionStatus.expired,
                        Subscription.activated_at.is_(None),
                    )
                ),
            )
            .order_by(Subscription.created_at.desc())
        ).all()
        return [(sub, tier) for sub, tier in rows]
```

- [ ] **Step 4: Add the dependency bundle and providers**

Create `lemely/web/subscription_deps.py`:

```python
"""The collaborators every subscription route and job needs, as one overridable bundle."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from lemely.db.subscription_repo import SubscriptionService

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker

    from lemely.io.paymob.client import PaymobClient
    from lemely.runtime.config import PaymobSettings


@dataclass(frozen=True, slots=True)
class SubscriptionDeps:
    """Session factory, Paymob client and settings. Tests override the provider with a fake."""

    sessionmaker: sessionmaker[Session]
    client: PaymobClient
    settings: PaymobSettings

    def service(self, session: Session) -> SubscriptionService:
        return SubscriptionService(session, self.client, self.settings)


__all__ = ["SubscriptionDeps"]
```

In `lemely/web/deps_billing.py` (Phase 02's billing dependency module), import `SubscriptionDeps`
from `lemely.web.subscription_deps` (and `time`, `lru_cache`, `SlidingWindowLimiter`, `get_settings`,
`get_sessionmaker` if the module lacks them) and add after `get_paymob_client`:

```python
@lru_cache(maxsize=1)
def get_subscription_deps() -> SubscriptionDeps:
    """The subscription routes' and jobs' collaborators (Paymob billing Phase 05)."""
    settings = get_settings()
    return SubscriptionDeps(get_sessionmaker(settings), get_paymob_client(), settings.paymob)


# 10 subscription checkouts per user per 10 minutes (spec §7: checkout is rate-limited).
_SUBSCRIPTION_CHECKOUT_LIMIT = 10
_SUBSCRIPTION_CHECKOUT_WINDOW_SECONDS = 600.0


@lru_cache(maxsize=1)
def get_subscription_checkout_limiter() -> SlidingWindowLimiter:
    """The per-user limiter on ``POST .../subscriptions/checkout``."""
    return SlidingWindowLimiter(
        limit=_SUBSCRIPTION_CHECKOUT_LIMIT,
        window_seconds=_SUBSCRIPTION_CHECKOUT_WINDOW_SECONDS,
        clock=time.monotonic,
    )
```

Add both to `reset_billing_singletons()` (`get_subscription_deps.cache_clear()`,
`get_subscription_checkout_limiter.cache_clear()`) and to the module's `__all__` if present.

- [ ] **Step 5: Add the DTOs**

Create `lemely/web/schemas_subscriptions.py`:

```python
"""API DTOs for subscriptions (Paymob billing Phase 05). camelCase, like the other schemas."""

# FastAPI and pydantic need these imports at runtime (see the per-file-ignore in pyproject.toml).
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class SubscriptionCheckoutRequestDTO(ApiModel):
    planTierId: uuid.UUID
    beneficiaryId: uuid.UUID | None = None
    extraSeats: int = Field(default=0, ge=0)


class SubscriptionCheckoutDTO(ApiModel):
    subscriptionId: str
    paymentId: str
    checkoutUrl: str


class DowngradeRequestDTO(ApiModel):
    planTierId: uuid.UUID


class SubscriptionDTO(ApiModel):
    id: str
    beneficiaryUserId: str
    isPayer: bool
    planTierId: str
    planCode: str
    planName: str
    status: str
    currentPeriodStart: datetime | None
    currentPeriodEnd: datetime | None
    graceUntil: datetime | None
    cancelAtPeriodEnd: bool
    pendingPlanTierId: str | None
    extraSeats: int


class SubscriptionListDTO(ApiModel):
    subscriptions: list[SubscriptionDTO]
```

- [ ] **Step 6: Add the billing routes**

Append to `lemely/web/routers/billing.py` (merge the imports with the module's existing ones):

```python
from datetime import UTC, datetime
from typing import Annotated
import uuid

from fastapi import Depends, HTTPException

from lemely.db.billing_repo import CheckoutUnavailable
from lemely.db.models.billing import PlanTier, Subscription
from lemely.db.subscription_repo import SeatsInsufficient, SubscriptionError
from lemely.web.deps import AuthContext
from lemely.web.deps_billing import get_subscription_checkout_limiter, get_subscription_deps
from lemely.web.ratelimit import SlidingWindowLimiter
from lemely.web.schemas_subscriptions import (
    DowngradeRequestDTO,
    SubscriptionCheckoutDTO,
    SubscriptionCheckoutRequestDTO,
    SubscriptionDTO,
    SubscriptionListDTO,
)
from lemely.web.subscription_deps import SubscriptionDeps

_BUYERS = require_billing_party  # Phase 02's guard in this module: student, parent, teacher
_STATUS_FOR_CODE = {
    "already_subscribed": 409,
    "seats_insufficient": 409,
    "not_linked_parent": 403,
    "subscription_not_found": 404,
    "plan_not_purchasable": 422,
    "invalid_extra_seats": 422,
    "invalid_plan_change": 422,
    "downgrade_unavailable": 409,
}


def _subscription_error(exc: SubscriptionError) -> HTTPException:
    detail: dict[str, object] = {"error": exc.code, "message": str(exc)}
    if isinstance(exc, SeatsInsufficient):
        detail |= {"inUse": exc.in_use, "capacity": exc.capacity}
    return HTTPException(status_code=_STATUS_FOR_CODE.get(exc.code, 400), detail=detail)


def _paymob_unavailable() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={"error": "payments_unavailable",
                "message": "Payments are unavailable right now. Please try again shortly."},
    )


def _dto(subscription: Subscription, tier: PlanTier, user_id: uuid.UUID) -> SubscriptionDTO:
    return SubscriptionDTO(
        id=str(subscription.id),
        beneficiaryUserId=str(subscription.user_id),
        isPayer=subscription.payer_user_id == user_id,
        planTierId=str(tier.id),
        planCode=tier.code,
        planName=tier.name,
        status=subscription.status.value,
        currentPeriodStart=subscription.current_period_start,
        currentPeriodEnd=subscription.current_period_end,
        graceUntil=subscription.grace_until,
        cancelAtPeriodEnd=bool(subscription.cancel_at_period_end),
        pendingPlanTierId=(
            str(subscription.pending_plan_tier_id) if subscription.pending_plan_tier_id else None
        ),
        extraSeats=subscription.extra_seats or 0,
    )


@router.post("/subscriptions/checkout", response_model=SubscriptionCheckoutDTO, status_code=201)
def create_subscription_checkout(
    body: SubscriptionCheckoutRequestDTO,
    auth: Annotated[AuthContext, Depends(_BUYERS)],
    deps: Annotated[SubscriptionDeps, Depends(get_subscription_deps)],
    limiter: Annotated[SlidingWindowLimiter, Depends(get_subscription_checkout_limiter)],
) -> SubscriptionCheckoutDTO:
    """Start a card subscription; the browser redirects to ``checkoutUrl`` (spec §5.1)."""
    if not limiter.allow(auth.user_id):
        raise HTTPException(
            status_code=429,
            detail={"error": "rate_limited", "message": "Too many checkouts; try again later."},
            headers={"Retry-After": str(limiter.retry_after(auth.user_id))},
        )
    try:
        # No session.begin(): BillingService.create_intention_checkout commits inside the call
        # (spec §6). A refusal raises before that commit, so closing the session rolls it back.
        with deps.sessionmaker() as session:
            result = deps.service(session).create_subscription_checkout(
                payer_user_id=uuid.UUID(auth.user_id),
                plan_tier_id=body.planTierId,
                beneficiary_user_id=body.beneficiaryId,
                extra_seats=body.extraSeats,
                now=datetime.now(UTC),
            )
            session.commit()
    except SubscriptionError as exc:
        raise _subscription_error(exc) from exc
    except CheckoutUnavailable as exc:
        raise _paymob_unavailable() from exc
    return SubscriptionCheckoutDTO(
        subscriptionId=str(result.subscription_id),
        paymentId=str(result.payment_id),
        checkoutUrl=result.checkout_url,
    )


@router.get("/subscriptions", response_model=SubscriptionListDTO)
def list_subscriptions(
    auth: Annotated[AuthContext, Depends(_BUYERS)],
    deps: Annotated[SubscriptionDeps, Depends(get_subscription_deps)],
) -> SubscriptionListDTO:
    """The caller's subscriptions as payer or beneficiary (spec §7: beneficiary sees plan)."""
    user_id = uuid.UUID(auth.user_id)
    with deps.sessionmaker() as session:
        rows = deps.service(session).list_for_user(user_id)
        return SubscriptionListDTO(subscriptions=[_dto(s, t, user_id) for s, t in rows])


@router.post("/subscriptions/{subscription_id}/downgrade", response_model=SubscriptionDTO)
def downgrade_subscription(
    subscription_id: uuid.UUID,
    body: DowngradeRequestDTO,
    auth: Annotated[AuthContext, Depends(_BUYERS)],
    deps: Annotated[SubscriptionDeps, Depends(get_subscription_deps)],
) -> SubscriptionDTO:
    """Schedule a downgrade for period end; payer only (spec §5.3)."""
    user_id = uuid.UUID(auth.user_id)
    try:
        with deps.sessionmaker() as session, session.begin():
            sub = deps.service(session).schedule_downgrade(
                subscription_id, actor_user_id=user_id, plan_tier_id=body.planTierId,
                now=datetime.now(UTC),
            )
            return _dto(sub, sub.plan_tier, user_id)
    except SubscriptionError as exc:
        raise _subscription_error(exc) from exc


@router.post("/subscriptions/{subscription_id}/cancel", response_model=SubscriptionDTO)
def cancel_subscription(
    subscription_id: uuid.UUID,
    auth: Annotated[AuthContext, Depends(_BUYERS)],
    deps: Annotated[SubscriptionDeps, Depends(get_subscription_deps)],
) -> SubscriptionDTO:
    """Cancel at period end; access continues until then; payer only (spec §5.3)."""
    user_id = uuid.UUID(auth.user_id)
    try:
        with deps.sessionmaker() as session, session.begin():
            sub = deps.service(session).schedule_cancel(
                subscription_id, actor_user_id=user_id, now=datetime.now(UTC)
            )
            return _dto(sub, sub.plan_tier, user_id)
    except SubscriptionError as exc:
        raise _subscription_error(exc) from exc
```

- [ ] **Step 7: Add the webhook route**

Append to `lemely/web/routers/paymob_webhooks.py` (merge imports):

```python
from datetime import UTC, datetime
from typing import Annotated, Any

import structlog
from fastapi import Body, Depends, HTTPException

from lemely.db.subscription_repo import MalformedWebhook, parse_subscription_webhook
from lemely.io.paymob.client import PaymobError
from lemely.io.paymob.hmac import verify_subscription_hmac
from lemely.web.deps_billing import get_subscription_deps
from lemely.web.subscription_deps import SubscriptionDeps

log = structlog.get_logger(__name__)


def _secret(value: object) -> str:
    getter = getattr(value, "get_secret_value", None)
    return str(getter() if callable(getter) else value)


@router.post("/subscription")
def paymob_subscription_webhook(
    payload: Annotated[dict[str, Any], Body()],
    deps: Annotated[SubscriptionDeps, Depends(get_subscription_deps)],
) -> dict[str, bool]:
    """Paymob subscription callback; the HMAC is in the body (spec §5.2, §6).

    401 on a bad HMAC (logged as an alert), 400 on a malformed body, 503 when Paymob cannot be
    reached to re-fetch state (nothing is stored, so Paymob's retry is processed), 200 after
    commit otherwise, including for duplicates and unknown subscriptions.
    """
    try:
        trigger, paymob_id, _ = parse_subscription_webhook(payload)
    except MalformedWebhook as exc:
        raise HTTPException(status_code=400, detail="malformed subscription webhook") from exc
    received = payload.get("hmac")
    if not isinstance(received, str) or not verify_subscription_hmac(
        trigger, paymob_id, received, _secret(deps.settings.hmac_secret)
    ):
        log.error("paymob_subscription_hmac_mismatch", paymob_subscription_id=paymob_id,
                  trigger_type=trigger)
        raise HTTPException(status_code=401, detail="invalid hmac")
    try:
        with deps.sessionmaker() as session, session.begin():
            deps.service(session).apply_renewal_webhook(payload, now=datetime.now(UTC))
    except PaymobError as exc:
        log.warning("paymob_subscription_webhook_deferred", paymob_subscription_id=paymob_id,
                    trigger_type=trigger, error_type=type(exc).__name__)
        raise HTTPException(status_code=503, detail="paymob unavailable; retry") from exc
    return {"ok": True}
```

If the module already defines `log`, reuse it instead of redefining.

- [ ] **Step 8: Run the tests to verify they pass**

In `tests/test_authz_matrix_complete.py`, under the `TUTORING_PARTY` section where Phase 02 put
its billing routes (the same three roles), add:

```python
    # Billing Phase 05: payer-only actions and the beneficiary scope are object-level
    # (tests/test_web_subscriptions.py IDOR cases).
    ("POST", "/api/billing/subscriptions/checkout"): TUTORING_PARTY,
    ("GET", "/api/billing/subscriptions"): TUTORING_PARTY,
    ("POST", "/api/billing/subscriptions/{subscription_id}/downgrade"): TUTORING_PARTY,
    ("POST", "/api/billing/subscriptions/{subscription_id}/cancel"): TUTORING_PARTY,
```

and in the PUBLIC section `("POST", "/api/webhooks/paymob/subscription"): PUBLIC,` (HMAC-verified,
no bearer). Raise the `TUTORING_PARTY` heading count by 4 and the PUBLIC heading count, and the
`len(ROUTES) - N` expression derived from it, by 1.

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest --no-cov tests/test_web_subscriptions.py tests/test_subscription_checkout.py tests/test_authz_matrix_complete.py tests/architecture/ -v`
Expected: PASS, including `test_every_route_is_declared` and the section-count test.

- [ ] **Step 9: Commit**

```bash
git add lemely/web/subscription_deps.py lemely/web/schemas_subscriptions.py lemely/web/deps_billing.py \
  lemely/web/routers/billing.py lemely/web/routers/paymob_webhooks.py lemely/db/subscription_repo.py \
  tests/test_web_subscriptions.py tests/test_authz_matrix_complete.py
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files
git commit -S -m "feat(billing): subscription checkout, plan change and webhook routes" -- \
  lemely/web/subscription_deps.py lemely/web/schemas_subscriptions.py lemely/web/deps_billing.py \
  lemely/web/routers/billing.py lemely/web/routers/paymob_webhooks.py lemely/db/subscription_repo.py \
  tests/test_web_subscriptions.py tests/test_authz_matrix_complete.py
```

---

### Task 12: Sweeper jobs

**Files:**
- Create: `lemely/web/subscription_jobs.py`, `tests/test_subscription_jobs.py`
- Modify: `lemely/web/scheduled_notifications.py`, `lemely/web/deps.py` (`get_sweeper`)

**Interfaces:**
- Consumes: `SubscriptionDeps` (Task 11); `SubscriptionService.expire_overdue`, `.apply_period_end_changes`, `.check_drift`; `grant_monthly_seat_allowances` (Task 10); Phase 03 `TeacherTeamService.release_due`; `ZoneDateMemo`, `run_jobs`.
- Produces:
  - `lemely.web.subscription_jobs`: `expire_overdue_job(deps, *, now) -> int`, `period_end_job(deps, *, now) -> int`, `drift_check_job(deps, *, now, memo) -> int` (once per UTC day per process), `release_due_seats_job(sessionmaker, *, now) -> int`, `monthly_seat_allowance_job(sessionmaker, *, now) -> int`, `DRIFT_MEMO_KEY`.
  - `Sweeper.subscriptions: SubscriptionDeps | None = None`, `Sweeper.billing_day_memo: ZoneDateMemo`.
  - Job names, in this order, appended when `subscriptions` is set: `subscriptions.expire_overdue`, `subscriptions.period_end`, `subscriptions.drift_check`, `seats.release_due`, `seats.monthly_allowance`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_subscription_jobs.py`:

```python
"""Phase 05 sweeper jobs: registered, ordered, idempotent (spec §3 Jobs)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from lemely.db.announcement_repo import AnnouncementService
from lemely.db.class_repo import ClassService
from lemely.db.models.billing import PlanAudience, Subscription
from lemely.db.models.enums import Role, SubscriptionStatus
from lemely.db.models.team import TeacherMember, TeacherMemberStatus
from lemely.db.notification_prefs_repo import NotificationPreferencesService
from lemely.db.notification_repo import NotificationService
from lemely.runtime.config import NotificationsSettings
from lemely.web.push import RecordingPushTransport
from lemely.web.scheduled_notifications import Sweeper
from lemely.web.subscription_deps import SubscriptionDeps
from tests.subscription_fixtures import (
    FakePaymobClient,
    charge,
    grants_of,
    paymob_settings,
    remote_subscription,
    seed_seat,
    seed_subscription,
    seed_tier,
    seed_user,
    throwaway_database,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker

DEC_1 = datetime(2026, 12, 1, 0, 1, tzinfo=UTC)
JOBS = [
    "subscriptions.expire_overdue",
    "subscriptions.period_end",
    "subscriptions.drift_check",
    "seats.release_due",
    "seats.monthly_allowance",
]


@pytest.fixture
def pg_sessionmaker() -> Iterator[sessionmaker[Session]]:
    yield from throwaway_database()


def _sweeper(sm: sessionmaker[Session], client: FakePaymobClient, now: datetime,
             with_subscriptions: bool = True) -> Sweeper:
    return Sweeper(
        sessionmaker=sm,
        announcements=AnnouncementService(sm, ClassService(sm)),
        notifications=NotificationService(sm, NotificationPreferencesService(sm)),
        transport=RecordingPushTransport(),
        settings=NotificationsSettings(),
        now=lambda: now,
        subscriptions=SubscriptionDeps(sm, client, paymob_settings()) if with_subscriptions else None,
    )


def test_jobs_run_in_order_after_the_existing_ones(pg_sessionmaker: sessionmaker[Session]) -> None:
    results = _sweeper(pg_sessionmaker, FakePaymobClient(), DEC_1).sweep_once()
    assert list(results)[-5:] == JOBS
    assert all(results[name] == 0 for name in JOBS)


def test_without_subscription_deps_the_job_set_is_unchanged(pg_sessionmaker: sessionmaker[Session]) -> None:
    results = _sweeper(pg_sessionmaker, FakePaymobClient(), DEC_1, with_subscriptions=False).sweep_once()
    assert not set(JOBS) & set(results)


def test_drift_check_runs_once_per_utc_day(pg_sessionmaker: sessionmaker[Session]) -> None:
    student = seed_user(pg_sessionmaker, Role.student)
    seed_subscription(pg_sessionmaker, user_id=student, tier_id=seed_tier(pg_sessionmaker),
                      payer_id=student, paymob_subscription_id=4321, paymob_amount_minor=10_000)
    client = FakePaymobClient()
    # Paymob holds a different amount (repaired by a PUT); the last charge is a decline.
    client.subscriptions[4321] = remote_subscription(4321, amount_cents=12_345)
    client.last_transactions[4321] = charge(1, 10_000, success=False)
    sweeper = _sweeper(pg_sessionmaker, client, DEC_1)
    assert sweeper.sweep_once()["subscriptions.drift_check"] == 1
    calls = len(client.calls)
    assert sweeper.sweep_once()["subscriptions.drift_check"] == 0
    assert len(client.calls) == calls  # memo: no Paymob call the same day
    sweeper.now = lambda: DEC_1 + timedelta(days=1)
    assert sweeper.sweep_once()["subscriptions.drift_check"] == 0  # in sync now
    assert len(client.calls) > calls  # but it did check


def test_an_expiring_teacher_plan_gets_no_new_month_of_seat_allowance(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    """Order proof: expiry runs before the monthly seat grant in the same pass."""
    teacher = seed_user(pg_sessionmaker, Role.teacher)
    tier = seed_tier(pg_sessionmaker, audience=PlanAudience.teacher, included_seats=3, seat_allowance_units=300)
    sid = seed_subscription(pg_sessionmaker, user_id=teacher, tier_id=tier, payer_id=teacher,
                            status=SubscriptionStatus.past_due, grace_until=DEC_1 - timedelta(minutes=1),
                            paymob_subscription_id=4321, paymob_amount_minor=10_000)
    student = seed_user(pg_sessionmaker, Role.student)
    seed_seat(pg_sessionmaker, teacher_id=teacher, student_id=student)
    results = _sweeper(pg_sessionmaker, FakePaymobClient(), DEC_1).sweep_once()
    assert results["subscriptions.expire_overdue"] == 1
    assert results["seats.monthly_allowance"] == 0
    with pg_sessionmaker() as session:
        assert session.get(Subscription, sid).status is SubscriptionStatus.expired
    assert grants_of(pg_sessionmaker, student) == []


def test_a_seat_leaving_at_month_end_is_released_before_the_new_grant(
    pg_sessionmaker: sessionmaker[Session],
) -> None:
    teacher = seed_user(pg_sessionmaker, Role.teacher)
    tier = seed_tier(pg_sessionmaker, audience=PlanAudience.teacher, included_seats=3, seat_allowance_units=300)
    seed_subscription(pg_sessionmaker, user_id=teacher, tier_id=tier, payer_id=teacher)
    leaver, stayer = seed_user(pg_sessionmaker, Role.student), seed_user(pg_sessionmaker, Role.student)
    leaving = seed_seat(pg_sessionmaker, teacher_id=teacher, student_id=leaver,
                        status=TeacherMemberStatus.leaving, leaves_at=DEC_1 - timedelta(minutes=1))
    seed_seat(pg_sessionmaker, teacher_id=teacher, student_id=stayer)
    results = _sweeper(pg_sessionmaker, FakePaymobClient(), DEC_1).sweep_once()
    assert (results["seats.release_due"], results["seats.monthly_allowance"]) == (1, 1)
    with pg_sessionmaker() as session:
        assert session.get(TeacherMember, leaving).status is TeacherMemberStatus.removed
    assert grants_of(pg_sessionmaker, leaver) == []
    assert len(grants_of(pg_sessionmaker, stayer)) == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest --no-cov tests/test_subscription_jobs.py -v`
Expected: FAIL — `TypeError: Sweeper.__init__() got an unexpected keyword argument 'subscriptions'`.

- [ ] **Step 3: Write the job functions**

Create `lemely/web/subscription_jobs.py`:

```python
"""Sweeper jobs for subscriptions and seats (Paymob billing spec §3 Jobs, §5.2, §5.9).

Each job opens its own session. The subscription jobs commit per subscription inside
:class:`~lemely.db.subscription_repo.SubscriptionService`; the seat jobs commit once. All are
idempotent: re-running after a crash, or on a second replica, changes nothing twice.
"""

from __future__ import annotations

from datetime import UTC
from typing import TYPE_CHECKING, Final

from lemely.db.seat_allowance_repo import grant_monthly_seat_allowances
from lemely.db.teacher_team_repo import TeacherTeamService

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.orm import Session, sessionmaker

    from lemely.web.scheduled_notifications import ZoneDateMemo
    from lemely.web.subscription_deps import SubscriptionDeps

#: Memo key for the once-a-day drift check (an optimisation; repairs are idempotent).
DRIFT_MEMO_KEY: Final = "subscriptions.drift_check"


def expire_overdue_job(deps: SubscriptionDeps, *, now: datetime) -> int:
    with deps.sessionmaker() as session:
        return deps.service(session).expire_overdue(now=now)


def period_end_job(deps: SubscriptionDeps, *, now: datetime) -> int:
    with deps.sessionmaker() as session:
        return deps.service(session).apply_period_end_changes(now=now)


def drift_check_job(deps: SubscriptionDeps, *, now: datetime, memo: ZoneDateMemo) -> int:
    """Run the drift check once per UTC day per process; a pass that throws is retried."""
    day = now.astimezone(UTC).date()
    if memo.is_done(DRIFT_MEMO_KEY, day):
        return 0
    with deps.sessionmaker() as session:
        repaired = deps.service(session).check_drift(now=now)
    memo.mark_done(DRIFT_MEMO_KEY, day)
    return repaired


def release_due_seats_job(sm: sessionmaker[Session], *, now: datetime) -> int:
    with sm() as session, session.begin():
        return TeacherTeamService(session).release_due(now=now)


def monthly_seat_allowance_job(sm: sessionmaker[Session], *, now: datetime) -> int:
    with sm() as session, session.begin():
        return grant_monthly_seat_allowances(session, now=now)


__all__ = [
    "DRIFT_MEMO_KEY",
    "drift_check_job",
    "expire_overdue_job",
    "monthly_seat_allowance_job",
    "period_end_job",
    "release_due_seats_job",
]
```

- [ ] **Step 4: Register the jobs**

In `lemely/web/scheduled_notifications.py`:

- Add the runtime import:

```python
from lemely.web.subscription_jobs import (
    drift_check_job,
    expire_overdue_job,
    monthly_seat_allowance_job,
    period_end_job,
    release_due_seats_job,
)
```

and under `TYPE_CHECKING`: `from lemely.web.subscription_deps import SubscriptionDeps`.

- Add two fields to `Sweeper` after `email_daily_cap`:

```python
    #: Paymob billing Phase 05: subscription and seat jobs run only when given, the same
    #: optional-collaborator pattern as ``storage``/``bucket`` and ``email_provider``.
    subscriptions: SubscriptionDeps | None = None
    billing_day_memo: ZoneDateMemo = field(default_factory=ZoneDateMemo)
```

- In `sweep_once`, before `return run_jobs(jobs)` (after Phase 02's billing job block if it is
  there):

```python
        subscriptions = self.subscriptions
        if subscriptions is not None:
            jobs.extend(
                [
                    (
                        "subscriptions.expire_overdue",
                        lambda: expire_overdue_job(subscriptions, now=moment),
                    ),
                    (
                        "subscriptions.period_end",
                        lambda: period_end_job(subscriptions, now=moment),
                    ),
                    (
                        "subscriptions.drift_check",
                        lambda: drift_check_job(
                            subscriptions, now=moment, memo=self.billing_day_memo
                        ),
                    ),
                    (
                        "seats.release_due",
                        lambda: release_due_seats_job(subscriptions.sessionmaker, now=moment),
                    ),
                    (
                        "seats.monthly_allowance",
                        lambda: monthly_seat_allowance_job(subscriptions.sessionmaker, now=moment),
                    ),
                ]
            )
```

Update the `sweep_once` docstring's first line to mention the subscription and seat jobs.

In `lemely/web/deps.py`, `get_sweeper`: extend Phase 02's local import to
`from lemely.web.deps_billing import get_billing_reconcile_job, get_subscription_deps` and add
`subscriptions=get_subscription_deps(),` to the `Sweeper(...)` call after
`billing_reconcile=get_billing_reconcile_job(),`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest --no-cov tests/test_subscription_jobs.py tests/test_scheduled_notifications.py tests/test_scheduled_announcements.py tests/architecture/ -v`
Expected: PASS (`test_sweep_once_without_provider_keeps_existing_job_set` still sees the old job set
because it builds a sweeper without `subscriptions`).

- [ ] **Step 6: Final phase check and commit**

Run every Phase 05 test file and pre-commit on the final tree:

```bash
PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest --no-cov tests/test_migration_subscription_periods.py \
  tests/test_db_schema.py tests/test_web_platform_admin.py tests/test_notify_email.py \
  tests/test_billing_notices.py tests/test_subscription_rules.py tests/test_subscription_plan_sync.py \
  tests/test_subscription_checkout.py tests/test_subscription_first_payment.py \
  tests/test_subscription_renewal.py tests/test_subscription_lifecycle.py \
  tests/test_subscription_plan_changes.py tests/test_subscription_drift.py \
  tests/test_seat_allowances.py tests/test_web_subscriptions.py tests/test_subscription_jobs.py \
  tests/test_scheduled_notifications.py tests/architecture/ -v
git add lemely/web/subscription_jobs.py lemely/web/scheduled_notifications.py lemely/web/deps.py \
  tests/test_subscription_jobs.py
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files
git commit -S -m "feat(billing): subscription and seat sweeper jobs" -- \
  lemely/web/subscription_jobs.py lemely/web/scheduled_notifications.py lemely/web/deps.py \
  tests/test_subscription_jobs.py
```

Expected: all PASS.

---

### Task 13: Billing summary route (index R3)

**Files:**
- Create: `lemely/db/billing_summary.py`, `tests/test_web_billing_summary.py`
- Modify: `lemely/web/schemas_subscriptions.py`, `lemely/web/routers/billing.py`, `tests/test_authz_matrix_complete.py`

**Interfaces:**
- Consumes: Phase 02 `require_billing_party`, `_beneficiary(session, auth, payer, requested)` (both in `lemely/web/routers/billing.py`), `PlanTierDTO` (`lemely/web/schemas_billing.py`), `SavedCard`; Phase 01 `UsageLedger.meter_fraction`, `UsageGrant`, `UsageGrantBalance`, `UsageDebt`; Phase 03 `TeacherTeamService.seat_capacity`, `.seats_used`; Task 1 `LIVE_SUBSCRIPTION_STATUSES`; Task 11 `get_subscription_deps`.
- Produces:
  - `lemely.db.billing_summary.BillingSummary` (frozen dataclass) and `build_billing_summary(session: Session, *, caller_user_id: UUID, beneficiary_user_id: UUID, now: datetime) -> BillingSummary`.
  - `GET /api/billing/summary?beneficiaryId=` → `BillingSummaryDTO`:
    `{beneficiary: {userId, displayName, audience}, subscription: {subscriptionId, status, tier: PlanTierDTO, currentPeriodStart, currentPeriodEnd, cancelAtPeriodEnd, pendingTier: PlanTierDTO | null, graceUntil, extraSeats, pendingExtraSeats} | null, canManage, managedByName, savedCard: {cardId, maskedPan, brand} | null, usage: {fraction: float | null, resetsAt}, credits: {totalUnits, expiring: [{units, expiresAt | null}]}, debtUnits, seats: {capacity, used} | null}`.
  - The first five fields are Phase 08's `BillingSummary` type; `usage`, `credits`, `debtUnits` and `seats` are the R3 additions Phase 08 adds to its type.
  - Access: a student or teacher sees their own (naming anyone else is 403); a parent must name a linked child (422 without `beneficiaryId`, 403 for an unlinked one), the rule of Phase 02's `_beneficiary`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_web_billing_summary.py`:

```python
"""GET /api/billing/summary: plan, period, meter, credits, debt, seats (index R3, spec §2.1, §7)."""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from lemely.db.models.billing import PlanAudience, SavedCard
from lemely.db.models.enums import Role, SubscriptionStatus
from lemely.db.models.usage import GrantKind
from lemely.db.usage_ledger_repo import UsageLedger
from lemely.web.app import create_app
from lemely.web.deps import AuthContext, get_auth_context
from lemely.web.deps_billing import get_subscription_checkout_limiter, get_subscription_deps
from lemely.web.ratelimit import SlidingWindowLimiter
from lemely.web.subscription_deps import SubscriptionDeps
from tests.subscription_fixtures import (
    T0,
    FakePaymobClient,
    link_parent,
    paymob_settings,
    seed_debt,
    seed_seat,
    seed_subscription,
    seed_tier,
    seed_user,
    throwaway_database,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker

URL = "/api/billing/summary"


@pytest.fixture
def pg_sessionmaker() -> Iterator[sessionmaker[Session]]:
    yield from throwaway_database()


def _client(sm: sessionmaker[Session], user: uuid.UUID, role: Role) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_subscription_deps] = lambda: SubscriptionDeps(
        sm, FakePaymobClient(), paymob_settings())
    limiter = SlidingWindowLimiter(limit=100, window_seconds=600, clock=time.monotonic)
    app.dependency_overrides[get_subscription_checkout_limiter] = lambda: limiter
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(user_id=str(user), role=role.value)
    return TestClient(app)


def _grant(sm: sessionmaker[Session], owner: uuid.UUID, kind: GrantKind, units: int, *,
           expires_days: int | None, key: str, visible: bool) -> None:
    with sm.begin() as session:
        UsageLedger(session).issue_grant(
            owner_user_id=owner, kind=kind, units=units, idempotency_key=key,
            expires_at=None if expires_days is None else T0 + timedelta(days=expires_days),
            visible=visible, effective_at=T0 - timedelta(days=1),
        )


def test_student_summary_has_plan_meter_credits_debt_and_card(pg_sessionmaker: sessionmaker[Session]) -> None:
    student = seed_user(pg_sessionmaker, Role.student)
    tier = seed_tier(pg_sessionmaker, price_minor=9_900)
    sid = seed_subscription(pg_sessionmaker, user_id=student, tier_id=tier, payer_id=student,
                            paymob_subscription_id=4321, paymob_amount_minor=9_900)
    _grant(pg_sessionmaker, student, GrantKind.period_allowance, 1_000, expires_days=30,
           key="period", visible=False)
    _grant(pg_sessionmaker, student, GrantKind.credit_pack, 500, expires_days=365, key="pack-a", visible=True)
    _grant(pg_sessionmaker, student, GrantKind.credit_pack, 200, expires_days=90, key="pack-b", visible=True)
    with pg_sessionmaker.begin() as session:
        session.add(SavedCard(user_id=student, token="ciphertext", token_fingerprint="f" * 64,
                              masked_pan="xxxx-xxxx-xxxx-2346", brand="MasterCard", is_active=True))
    seed_debt(pg_sessionmaker, student, 40)

    body = _client(pg_sessionmaker, student, Role.student).get(URL).json()

    assert body["beneficiary"]["userId"] == str(student)
    assert body["beneficiary"]["audience"] == "student"
    assert body["subscription"]["subscriptionId"] == str(sid)
    assert body["subscription"]["tier"]["planTierId"] == str(tier)
    assert body["subscription"]["status"] == "active"
    assert (body["canManage"], body["managedByName"]) == (True, None)
    assert body["savedCard"]["maskedPan"] == "xxxx-xxxx-xxxx-2346"
    assert body["usage"]["fraction"] == 0.0  # allowance granted, nothing spent
    # The debt is seeded after the grants, so no repayment ran: the packs are whole, listed
    # soonest expiry first. Allowances (visible=False) are not credits.
    expiring = [
        (e["units"], datetime.fromisoformat(e["expiresAt"].replace("Z", "+00:00")))
        for e in body["credits"]["expiring"]
    ]
    assert expiring == [(200, T0 + timedelta(days=90)), (500, T0 + timedelta(days=365))]
    assert body["credits"]["totalUnits"] == 700
    assert body["debtUnits"] == 40
    assert body["seats"] is None


def test_no_subscription_means_null_and_may_buy(pg_sessionmaker: sessionmaker[Session]) -> None:
    student = seed_user(pg_sessionmaker, Role.student)
    body = _client(pg_sessionmaker, student, Role.student).get(URL).json()
    assert body["subscription"] is None
    assert body["canManage"] is True
    assert body["credits"] == {"totalUnits": 0, "expiring": []}
    assert (body["debtUnits"], body["usage"]["fraction"]) == (0, None)


def test_parent_pays_child_sees_who_manages(pg_sessionmaker: sessionmaker[Session]) -> None:
    parent = seed_user(pg_sessionmaker, Role.parent)
    child = seed_user(pg_sessionmaker, Role.student)
    link_parent(pg_sessionmaker, parent, child)
    seed_subscription(pg_sessionmaker, user_id=child, tier_id=seed_tier(pg_sessionmaker), payer_id=parent)

    as_parent = _client(pg_sessionmaker, parent, Role.parent).get(URL, params={"beneficiaryId": str(child)})
    assert as_parent.status_code == 200
    assert as_parent.json()["canManage"] is True
    as_child = _client(pg_sessionmaker, child, Role.student).get(URL).json()
    assert as_child["canManage"] is False
    assert as_child["managedByName"] == "parent user"  # seed_user display name


def test_access_rules(pg_sessionmaker: sessionmaker[Session]) -> None:
    parent = seed_user(pg_sessionmaker, Role.parent)
    stranger = seed_user(pg_sessionmaker, Role.student)
    student = seed_user(pg_sessionmaker, Role.student)
    assert _client(pg_sessionmaker, parent, Role.parent).get(URL).status_code == 422
    assert _client(pg_sessionmaker, parent, Role.parent).get(
        URL, params={"beneficiaryId": str(stranger)}).status_code == 403
    assert _client(pg_sessionmaker, student, Role.student).get(
        URL, params={"beneficiaryId": str(stranger)}).status_code == 403  # IDOR
    assert _client(pg_sessionmaker, student, Role.student).get(
        URL, params={"beneficiaryId": str(student)}).status_code == 200
    admin = seed_user(pg_sessionmaker, Role.school_admin)
    assert _client(pg_sessionmaker, admin, Role.school_admin).get(URL).status_code == 403


def test_teacher_summary_has_seats(pg_sessionmaker: sessionmaker[Session]) -> None:
    teacher = seed_user(pg_sessionmaker, Role.teacher)
    tier = seed_tier(pg_sessionmaker, audience=PlanAudience.teacher, included_seats=5,
                     extra_seat_price_minor=2_500)
    seed_subscription(pg_sessionmaker, user_id=teacher, tier_id=tier, payer_id=teacher, extra_seats=1)
    for _ in range(2):
        seed_seat(pg_sessionmaker, teacher_id=teacher, student_id=seed_user(pg_sessionmaker, Role.student))
    body = _client(pg_sessionmaker, teacher, Role.teacher).get(URL).json()
    assert body["seats"] == {"capacity": 6, "used": 2}
    assert body["subscription"]["extraSeats"] == 1


def test_ended_subscription_is_not_shown(pg_sessionmaker: sessionmaker[Session]) -> None:
    student = seed_user(pg_sessionmaker, Role.student)
    seed_subscription(pg_sessionmaker, user_id=student, tier_id=seed_tier(pg_sessionmaker),
                      payer_id=student, status=SubscriptionStatus.expired)
    assert _client(pg_sessionmaker, student, Role.student).get(URL).json()["subscription"] is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest --no-cov tests/test_web_billing_summary.py -v`
Expected: FAIL — 404 on `GET /api/billing/summary`.

- [ ] **Step 3: Build the summary**

Create `lemely/db/billing_summary.py`:

```python
"""What a billing screen shows for one beneficiary (index R3; spec §2.1, §2.2, §4.5, §7).

Read-only. Authorization (who may see whose summary) is the route's job; this module assumes the
caller may see ``beneficiary_user_id``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy import select

from lemely.db.models.billing import LIVE_SUBSCRIPTION_STATUSES, PlanTier, SavedCard, Subscription
from lemely.db.models.enums import Role
from lemely.db.models.usage import UsageDebt, UsageGrant, UsageGrantBalance
from lemely.db.models.users import User
from lemely.db.teacher_team_repo import TeacherTeamService
from lemely.db.usage_ledger_repo import UsageLedger

if TYPE_CHECKING:
    import uuid
    from datetime import datetime

    from sqlalchemy.orm import Session


@dataclass(frozen=True, slots=True)
class CreditLot:
    units: int
    expires_at: datetime | None


@dataclass(frozen=True, slots=True)
class BillingSummary:
    beneficiary: User
    audience: str
    subscription: Subscription | None
    tier: PlanTier | None
    pending_tier: PlanTier | None
    can_manage: bool
    managed_by_name: str | None
    saved_card: SavedCard | None
    meter_fraction: float | None
    meter_resets_at: datetime | None
    credits: list[CreditLot]
    debt_units: int
    seat_capacity: int | None
    seats_used: int | None


def build_billing_summary(
    session: Session, *, caller_user_id: uuid.UUID, beneficiary_user_id: uuid.UUID, now: datetime
) -> BillingSummary:
    """Plan, period, allowance meter, visible credits by expiry, debt and (teachers) seats."""
    beneficiary = session.get(User, beneficiary_user_id)
    if beneficiary is None:
        raise LookupError(f"unknown user {beneficiary_user_id}")
    is_teacher = beneficiary.role is Role.teacher
    subscription = session.scalars(
        select(Subscription)
        .where(
            Subscription.user_id == beneficiary_user_id,
            Subscription.status.in_(LIVE_SUBSCRIPTION_STATUSES),
        )
        .order_by(Subscription.created_at.desc())
        .limit(1)
    ).one_or_none()
    tier = session.get(PlanTier, subscription.plan_tier_id) if subscription else None
    pending_tier = (
        session.get(PlanTier, subscription.pending_plan_tier_id)
        if subscription is not None and subscription.pending_plan_tier_id is not None
        else None
    )
    payer_id = subscription.payer_user_id if subscription is not None else None
    can_manage = subscription is None or payer_id == caller_user_id
    managed_by = (
        session.get(User, payer_id) if payer_id is not None and payer_id != caller_user_id else None
    )
    card_owner = payer_id if payer_id is not None else caller_user_id
    saved_card = (
        session.scalars(
            select(SavedCard)
            .where(SavedCard.user_id == card_owner, SavedCard.is_active.is_(True))
            .order_by(SavedCard.created_at.desc())
            .limit(1)
        ).one_or_none()
        if can_manage
        else None
    )
    usable = sa.and_(
        UsageGrant.owner_user_id == beneficiary_user_id,
        UsageGrant.visible.is_(True),
        UsageGrant.effective_at <= now,
        sa.or_(UsageGrant.expires_at.is_(None), UsageGrant.expires_at > now),
    )
    lots = session.execute(
        select(
            UsageGrant.expires_at,
            sa.func.sum(UsageGrantBalance.remaining - UsageGrantBalance.held),
        )
        .join(UsageGrantBalance, UsageGrantBalance.grant_id == UsageGrant.id)
        .where(usable, UsageGrantBalance.remaining > UsageGrantBalance.held)
        .group_by(UsageGrant.expires_at)
        .order_by(UsageGrant.expires_at.asc().nulls_last())
    ).all()
    debt = session.scalar(
        select(sa.func.coalesce(sa.func.sum(UsageDebt.outstanding), 0)).where(
            UsageDebt.owner_user_id == beneficiary_user_id
        )
    )
    team = TeacherTeamService(session) if is_teacher else None
    return BillingSummary(
        beneficiary=beneficiary,
        audience="teacher" if is_teacher else "student",
        subscription=subscription,
        tier=tier,
        pending_tier=pending_tier,
        can_manage=can_manage,
        managed_by_name=managed_by.display_name if managed_by is not None else None,
        saved_card=saved_card,
        meter_fraction=UsageLedger(session).meter_fraction(
            beneficiary_user_id, teacher_member_id=None, now=now
        ),
        meter_resets_at=subscription.current_period_end if subscription is not None else None,
        credits=[CreditLot(units=int(units), expires_at=expires) for expires, units in lots],
        debt_units=int(debt or 0),
        seat_capacity=team.seat_capacity(beneficiary_user_id) if team is not None else None,
        seats_used=team.seats_used(beneficiary_user_id) if team is not None else None,
    )


__all__ = ["BillingSummary", "CreditLot", "build_billing_summary"]
```

- [ ] **Step 4: Add the DTOs**

Append to `lemely/web/schemas_subscriptions.py` (add `from lemely.web.schemas_billing import
PlanTierDTO`):

```python
class SummaryBeneficiaryDTO(ApiModel):
    userId: str
    displayName: str | None
    audience: str


class SubscriptionViewDTO(ApiModel):
    subscriptionId: str
    status: str
    tier: PlanTierDTO
    currentPeriodStart: datetime | None
    currentPeriodEnd: datetime | None
    cancelAtPeriodEnd: bool
    pendingTier: PlanTierDTO | None
    graceUntil: datetime | None
    extraSeats: int
    pendingExtraSeats: int | None


class SavedCardViewDTO(ApiModel):
    cardId: str
    maskedPan: str
    brand: str | None


class UsageMeterViewDTO(ApiModel):
    fraction: float | None
    resetsAt: datetime | None


class CreditLotDTO(ApiModel):
    units: int
    expiresAt: datetime | None


class CreditsViewDTO(ApiModel):
    totalUnits: int
    expiring: list[CreditLotDTO]


class SeatsViewDTO(ApiModel):
    capacity: int
    used: int


class BillingSummaryDTO(ApiModel):
    beneficiary: SummaryBeneficiaryDTO
    subscription: SubscriptionViewDTO | None
    canManage: bool
    managedByName: str | None
    savedCard: SavedCardViewDTO | None
    usage: UsageMeterViewDTO
    credits: CreditsViewDTO
    debtUnits: int
    seats: SeatsViewDTO | None
```

- [ ] **Step 5: Add the route**

Append to `lemely/web/routers/billing.py` (merge imports; `_beneficiary` and
`require_billing_party` are Phase 02's, already in this module):

```python
from lemely.db.billing_summary import build_billing_summary
from lemely.web.schemas_subscriptions import (
    BillingSummaryDTO,
    CreditLotDTO,
    CreditsViewDTO,
    SavedCardViewDTO,
    SeatsViewDTO,
    SubscriptionViewDTO,
    SummaryBeneficiaryDTO,
    UsageMeterViewDTO,
)


def _plan_tier_dto(t: PlanTier) -> PlanTierDTO:
    return PlanTierDTO(
        planTierId=str(t.id),
        code=t.code,
        name=t.name,
        priceMinor=t.price_minor,
        currency=t.currency,
        interval=t.interval.value if t.interval is not None else None,
        audience=t.audience.value,
        includedSeats=t.included_seats,
        extraSeatPriceMinor=t.extra_seat_price_minor,
        features=dict(t.features),
    )


@router.get("/summary", response_model=BillingSummaryDTO)
def get_billing_summary(
    auth: Annotated[AuthContext, Depends(require_billing_party)],
    deps: Annotated[SubscriptionDeps, Depends(get_subscription_deps)],
    beneficiaryId: uuid.UUID | None = None,  # noqa: N803 (query parameter name is the API's)
) -> BillingSummaryDTO:
    """Plan, period, usage meter, credits with expiry, debt and seats (index R3).

    A parent must name a linked child; anyone else sees only themselves (Phase 02's
    ``_beneficiary`` rule, the same one checkout uses).
    """
    caller = uuid.UUID(auth.user_id)
    with deps.sessionmaker() as session:
        target = _beneficiary(session, auth, caller, beneficiaryId)
        s = build_billing_summary(
            session, caller_user_id=caller, beneficiary_user_id=target, now=datetime.now(UTC)
        )
        sub = s.subscription
        return BillingSummaryDTO(
            beneficiary=SummaryBeneficiaryDTO(
                userId=str(s.beneficiary.id),
                displayName=s.beneficiary.display_name,
                audience=s.audience,
            ),
            subscription=(
                SubscriptionViewDTO(
                    subscriptionId=str(sub.id),
                    status=sub.status.value,
                    tier=_plan_tier_dto(s.tier),
                    currentPeriodStart=sub.current_period_start,
                    currentPeriodEnd=sub.current_period_end,
                    cancelAtPeriodEnd=bool(sub.cancel_at_period_end),
                    pendingTier=_plan_tier_dto(s.pending_tier) if s.pending_tier else None,
                    graceUntil=sub.grace_until,
                    extraSeats=sub.extra_seats or 0,
                    pendingExtraSeats=sub.pending_extra_seats,
                )
                if sub is not None and s.tier is not None
                else None
            ),
            canManage=s.can_manage,
            managedByName=s.managed_by_name,
            savedCard=(
                SavedCardViewDTO(
                    cardId=str(s.saved_card.id),
                    maskedPan=s.saved_card.masked_pan,
                    brand=s.saved_card.brand,
                )
                if s.saved_card is not None
                else None
            ),
            usage=UsageMeterViewDTO(fraction=s.meter_fraction, resetsAt=s.meter_resets_at),
            credits=CreditsViewDTO(
                totalUnits=sum(lot.units for lot in s.credits),
                expiring=[CreditLotDTO(units=lot.units, expiresAt=lot.expires_at) for lot in s.credits],
            ),
            debtUnits=s.debt_units,
            seats=(
                SeatsViewDTO(capacity=s.seat_capacity, used=s.seats_used or 0)
                if s.seat_capacity is not None
                else None
            ),
        )
```

Import `PlanTierDTO` from `lemely.web.schemas_billing` if the module does not already. If Phase 02
already has a tier-to-DTO helper in this module, use it instead of `_plan_tier_dto`.

- [ ] **Step 6: Declare the routes in the authz matrix**

In `tests/test_authz_matrix_complete.py`, after the Phase 05 entries Task 11 added to the
`TUTORING_PARTY` section, add:

```python
    # Object-level: a parent sees only a linked child (tests/test_web_billing_summary.py).
    ("GET", "/api/billing/summary"): TUTORING_PARTY,
```

and raise the `TUTORING_PARTY` heading count by 1.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest --no-cov tests/test_web_billing_summary.py tests/test_web_subscriptions.py tests/test_authz_matrix_complete.py tests/architecture/ -v`
Expected: PASS, including `test_every_route_is_declared` and the section-count test.

- [ ] **Step 8: Final phase check and commit**

```bash
PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest --no-cov tests/test_migration_subscription_periods.py \
  tests/test_db_schema.py tests/test_web_platform_admin.py tests/test_notify_email.py \
  tests/test_billing_notices.py tests/test_subscription_rules.py tests/test_subscription_plan_sync.py \
  tests/test_subscription_checkout.py tests/test_subscription_first_payment.py \
  tests/test_subscription_renewal.py tests/test_subscription_lifecycle.py \
  tests/test_subscription_plan_changes.py tests/test_subscription_drift.py \
  tests/test_seat_allowances.py tests/test_web_subscriptions.py tests/test_subscription_jobs.py \
  tests/test_web_billing_summary.py tests/test_authz_matrix_complete.py \
  tests/test_scheduled_notifications.py tests/architecture/ -v
git add lemely/db/billing_summary.py lemely/web/schemas_subscriptions.py lemely/web/routers/billing.py \
  tests/test_web_billing_summary.py tests/test_authz_matrix_complete.py
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files
git commit -S -m "feat(billing): billing summary route" -- \
  lemely/db/billing_summary.py lemely/web/schemas_subscriptions.py lemely/web/routers/billing.py \
  tests/test_web_billing_summary.py tests/test_authz_matrix_complete.py
```

Expected: all PASS.

---

## Spec coverage (self-review)

| Spec requirement | Task |
|---|---|
| §2.1 subscriptions card-only, auto-renew, monthly and yearly; parent buys for child, child is beneficiary | 3 (frequencies), 4 (parent link, beneficiary), 11 (list shows plan to beneficiary) |
| §2.6 downgrade/cancel at period end; access continues; teacher downgrade refused while seats exceed | 8 |
| §2.6 failed renewal: 3 days grace, then lapse; seats stop granting | 7, 10, 12 (order proof) |
| §2.6 unused allowance expires at period end, no rollover | 5, 6 (`expires_at = period_end`) |
| §4.3 `subscription_periods`, unique `(subscription_id, period_start)`; partial unique live index | 1 |
| §5.1 checkout: audience/role check, parent link, live check, server pricing incl. extra seats, `subscription_plan_id`, polling return | 4, 11 |
| §5.1 step 4: event, paid, activate, period, grant repaying debt, 200 after commit | Phase 02 callback + 5 |
| §5.2 Successful Transaction: re-fetch last transaction, renewal payment, next period and grant, duplicates harmless | 6 |
| §5.2 Failed → past_due + grace; Overdue/grace elapsed → expired; canceled/suspended mirrored after re-fetch; daily drift | 7, 9, 12 |
| §5.3 downgrade via PUT before renewal; cancel by sweeper | 8 |
| §5.4 extra seats at first checkout; pending seat reduction applied at renewal | 4, 6, 8 (Phase 06 owns add/upgrade) |
| §5.9 seat allowances: calendar month, live plan (monthly or yearly), prorated claim, dedupe, none when expired; seat release job | 10, 12 |
| §6 HMAC first, 401; duplicate 200 no-op; unknown 200 logged; mismatch → `failed_mismatch`, no grant | 6, 11 |
| §7 payer-only billing actions, IDOR, rate-limited checkout | 8 (`_payer_lock`), 11, 13 |
| §2.1 usage meter, credits with expiry breakdown, child sees plan/meter/balance (index R3 summary) | 13 |
| §8 plan tiers linked to Paymob plans with a sync action (service function; UI in Phase 07) | 3 |
| §8 manual activation kept for complimentary accounts | 1, 9 (untouched by sweeps) |
| §3 Jobs: renewal and expiry emails through the existing outbox | 2, 6, 7, 8 |
| §11 success criterion: renewal, failed renewal with grace, downgrade, cancel move through the documented states | 6, 7, 8 |

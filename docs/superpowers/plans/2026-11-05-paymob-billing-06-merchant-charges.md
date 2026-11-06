# Paymob billing phase 06: merchant-initiated charges, implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Charge a payer's saved card without the payer present (Paymob MOTO) for three things: a prorated plan upgrade, extra teacher seats (with a fallback for when the subscription amount cannot change), and auto top-up of credits. Every charge is recorded before Paymob is called, and none is ever retried blindly.

**Architecture:** One module, `lemely/db/merchant_charge_repo.py`, holds `MerchantChargeService` and the three paid handlers. A charge inserts a `payments` row, claims it (`created` → `pending`) and commits, then creates a MOTO intention and calls `pay_with_token`. If that call times out, the service asks Paymob's inquiry API and does not retry. Only the verified transaction callback (Phase 02's `BillingService.apply_transaction_callback`, or its `billing.reconcile_pending` inquiry) marks a payment `paid` and dispatches the purpose handler. Two sweeper jobs handle the background charges: `billing.auto_topup` and `billing.extra_seat_renewal_charge`. They also poll for failed payments to run the failure rules (disable auto top-up and email the payer; give a 3-day seat grace, then drop the seats). Usage settle triggers auto top-up through a generic post-settle hook registry added to `lemely/web/usage.py`.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2 (sync ORM), Alembic, Postgres, httpx (via Phase 02's `PaymobClient`), pydantic v2, pytest with throwaway Postgres databases (`migrated_sessionmaker`).

## Global Constraints

Copied from the index (`2026-11-05-paymob-billing-00-index.md`). They apply to every task.

- Signed commits only: `git commit -S -- <paths>`. Scope `feat(billing):` (tests-only commits `test(billing):`).
- Run `/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files` and fix every failure before each commit.
- Run Python with `PYTHONPATH=$PWD` from the worktree root `/home/sico/Code/Lemely/.claude/worktrees/paymob-integration`. Tests: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest <touched files> -v --no-cov`. Every pytest command carries `--no-cov`, because the repo's `--cov-fail-under=70` fails any subset run (index R2). Never run the full suite (`make test` or bare `pytest`).
- When a task adds a module under `lemely/`, also run `tests/architecture/`.
- Do not push. Do not open PRs.
- Money is integer minor units (piasters, `BIGINT`). Usage is integer units (`BIGINT`).
- UUID primary keys with `server_default=sa.text("gen_random_uuid()")`, Postgres enums, `TimestampMixin`.
- `lemely/db/models/*` never imports `lemely.core`. Import-linter contracts in `pyproject.toml` stay green. `lemely.db` never imports `lemely.web`.
- Paymob secret key, API key, HMAC secret and card tokens are never logged and never sent to the browser.
- Settings live in `PaymobSettings` (`lemely/runtime/config.py`), env prefix `LEMELY_PAYMOB__*`.
- Every webhook state change happens in one DB transaction.
- **No idempotency keys at Paymob (spec §6):** insert our own payment row before calling Paymob. After a timeout, query inquiry before any retry. Never retry a charge blindly.
- No placeholder code: no `TODO`, no `pass` bodies, no `test.skip`, no stub tests.

---

## Contract deviations

Each item changes or adds to the index's contracts. Each one gives the reason.

1. **`auto_topup_settings` is keyed by beneficiary, not by payer.** Spec §4.6 gives `user_id (unique)` and says "the payer owns it (a parent for a child)". A parent with two children would then get only one setting for two balances. The table has `beneficiary_user_id` (unique: one setting per balance) and `payer_user_id` (the owner, whose card is charged). Two more columns support the dedupe key `(user, threshold crossing)`: `armed` and `crossing_seq`. `last_payment_id` lets the failure sweep act on the latest top-up only. `disabled_reason` records why a setting was turned off.
2. **Migration `0056_auto_topup` changes more than the new table.** It also adds:
   - `payments.dedupe_key` (nullable, unique). The queue keys `auto_topup:{owner}:{crossing_seq}` and `extra_seat_renewal:{period_id}:{attempt}` make enqueueing idempotent.
   - `subscriptions.extra_seat_grace_until` and `subscriptions.extra_seat_grace_payment_id` for the fallback 3-day seat grace.
   The `billing` notification type comes from Phase 05's `0055` (index R7); `0056` does not touch it.
3. **Phase 06 changes one Phase 05 method body, nothing else (Task 4; index R6).** Phase 05 alone applies `pending_extra_seats` at renewal, in `_grant_renewal_period`. Phase 06 never applies it.
   - **Expected amount.** `SubscriptionService.next_renewal_amount` stays the single source of the expected renewal amount. Phase 05's deviation 10 asks for its body to be replaced: it now returns `expected_renewal_amount_minor(subscription, tier, self._settings)`. That function is fallback-aware: with `subscription_amount_updatable=False` it returns `paymob_amount_minor`, the amount Paymob really charges, so neither the period-end push nor the drift check tries a PUT Paymob cannot honour.
   - **Amount PUTs.** Every PUT goes through Phase 05's `SubscriptionService.sync_renewal_amount`, which PUTs and stamps `paymob_amount_minor`. This phase calls it after an upgrade and after a seat purchase.
   - **Fallback charge.** The sweeper job `billing.extra_seat_renewal_charge` polls; it is not called from Phase 05. For each live teacher subscription whose current period has no renewal-seat attempt yet, it calls `queue_renewal_seat_charge(session, subscription, period, *, now)`. That function queues an `extra_seats` payment for `subscription_amount_minor(price, extra_seats) − paymob_amount_minor` when the difference is positive and no seat purchase has been made since the period began. A seat bought during a period is prorated for that period, so the shortfall is first charged at the next renewal. The difference is 0 whenever Paymob is in step. It is positive on the fallback path, and also after a failed PUT.
   - **Upgrades and the Paymob plan id.** Paymob's `PUT subscriptions/{id}` changes only `amount_cents`, `ends_at` and `next_billing` (research 02 §6), so an upgrade leaves the Paymob plan id unchanged. Phase 05's drift check compares amount and state only, which already fits. The upgrade "PUT amount and plan" in spec §5.3 becomes "PUT amount, switch the local tier".
4. **Phase 06 changes Phase 03's `TeacherTeamService._capacity`, which backs `seat_capacity` and the seat claim (Task 5).** While a reduction is pending, usable extra seats are `min(extra_seats, pending_extra_seats)`. Without this, new class joins during the rest of the period could exceed the seat count the teacher will pay for at renewal.
5. **The upgrade allowance difference is prorated.** Spec §2.6 says "the allowance difference is granted at once". The price difference is prorated by the remaining fraction of the period, so granting the full allowance difference would let a user upgrade on the last day for a few piasters and get a full period's extra allowance. The grant is `prorate_units(new.allowance_units − old.allowance_units, period_start, period_end, now)` and expires at `current_period_end`.
6. **Upgrades are refused when `paymob.subscription_amount_updatable` is `False`** (error `upgrade_unavailable`). On the fallback path Paymob would keep renewing at the old price. Spec §5.4's fallback covers seats only. This is open question 7 in §10. On the fallback path a seat reduction that would need a lower Paymob amount is also refused (`seat_reduction_unavailable`): Paymob would keep charging the higher amount, because Phase 05's plans use `use_transaction_amount=true`.
7. **`paymob.subscription_amount_updatable` (added by Phase 05 Task 8) defaults to `True`.** Research 02 §6 documents `PUT subscriptions/{id}` with `amount_cents`. Set `LEMELY_PAYMOB__SUBSCRIPTION_AMOUNT_UPDATABLE=false` if Paymob answers question 7 with "no".
8. **The fallback seat charge is retried up to 3 times, once per day, inside the 3-day grace.** Spec §5.4 gives a failed seat charge "the same 3-day grace" that a renewal gets while Paymob retries. Each retry is a **new** `payments` row created only after the previous one reached a definite `failed`. A charge whose outcome is unknown is never retried (spec §6).
9. **The teacher gets an email when a seat charge fails** (template `extra_seats_charge_failed`). The spec requires an email only for a failed auto top-up. Without one, a teacher would lose seats with no warning.
10. **Routes follow Phase 02's layout (index R1).** They are added to `lemely/web/routers/billing.py` (`APIRouter(prefix="/api/billing")`), as Phase 05 does. The dependency bundle lives in `lemely/web/merchant_charge_deps.py` (like Phase 05's `subscription_deps.py`), with its lru-cached provider `get_merchant_charge_deps()` in `lemely/web/deps_billing.py`.
11. **Paid handlers are module-level functions registered on import, as Phase 02 does for `credit_pack`.** Phase 02's `register_paid_handler` raises `ValueError` when a *different* handler is already registered, so closures rebuilt on every `create_app()` would break. The handlers that PUT to Paymob (upgrade, extra seats) read their client from `configure_merchant_charges(client_factory, settings)`, which `create_app()` calls. Until it has been called, a handler still switches the tier or seats locally and logs that the PUT was skipped; Phase 05's drift check repairs the amount.
12. **Post-settle hook (Task 7).** Phase 04 Task 6 owns the registry in `lemely/web/usage.py` (`PostSettleHook`, `_POST_SETTLE_HOOKS`, `register_post_settle_hook`, `clear_post_settle_hooks`, `run_post_settle_hooks`). `MeteredJob._finish` calls it right after `ledger.settle(...)`, in the settle's transaction. This phase only registers `auto_topup_post_settle_hook` in `create_app()` and pins the registry's behaviour with a test. The usage module stays free of billing imports.
13. **Quote routes (index R3).** `POST /api/billing/subscriptions/{id}/upgrade/quote` and `POST /api/billing/subscriptions/{id}/seats/quote` return the prorated amount. They run the same validation as the charge, except the saved-card and in-flight checks, and they write nothing.
14. **Every Paymob amount PUT this phase triggers goes through Phase 05's `SubscriptionService.sync_renewal_amount` (index R6).** That method PUTs and stamps `subscriptions.paymob_amount_minor` in the same transaction. The upgrade handler and the extra-seats handler call it, through `push_subscription_amount`. A seat reduction makes no PUT itself: Phase 05's period-end job pushes `next_renewal_amount`, as its test `test_pending_seat_reduction_is_pushed` expects.

## Consumed contracts (exact names this plan relies on)

Each name below was checked against the drafted plans 01–05 (2026-11-05). If a merged phase differs, change only the call sites in this phase's files, never the earlier phase.

- **Phase 01** (`lemely/db/models/usage.py`, `lemely/core/usage_types.py`, `lemely/core/usage_pricing.py`, `lemely/db/usage_ledger_repo.py`):
  - `GrantKind`, `UsageGrant`, `UsageJob`, `GrantScope` (`ALLOWANCE`, `CREDITS`, `SEAT`) and the frozen dataclass `Payer(owner_user_id, scope, teacher_member_id=None, cap_units=None, cap_window_start=None, debt_exempt=False)`.
  - `prorate_minor(amount_minor, period_start, period_end, now)` and `prorate_units(units, period_start, period_end, now)`.
  - `UsageLedger(session)` with:
    - `issue_grant(*, owner_user_id, kind, units, idempotency_key, expires_at, visible, effective_at=None, payment_id=None, subscription_period_id=None, teacher_member_id=None)`, which repays the owner's debts first;
    - `available(payers, *, now) -> int`;
    - `adjust(*, owner_user_id, units, reason, idempotency_key, now)`.
- **Phase 02** (`lemely/db/models/billing.py`):
  - `PlanAudience` (`student`, `teacher`), `PaymentPurpose`, `PaymentStatus` (`created`, `pending`, `paid`, `failed`, `failed_mismatch`, `refunded`, `partially_refunded`, `voided`) and `LIVE_SUBSCRIPTION_STATUSES`.
  - `Payment` columns: `id`, `payer_user_id`, `beneficiary_user_id`, `purpose`, `plan_tier_id`, `credit_pack_id`, `subscription_id`, `seat_quantity` (nullable, positive), `amount_minor`, `currency`, `status`, `special_reference`, `paymob_intention_id` (str), `paymob_order_id` (BigInteger), `paymob_txn_id`, `method`, `paid_at`, `reconcile_attempts`, `next_reconcile_at`, `created_at`, `updated_at`.
  - `SavedCard` columns: `id`, `user_id`, `token` (AES-GCM **ciphertext**), `token_fingerprint` (NOT NULL), `masked_pan`, `brand`, `paymob_token_id`, `is_active`, `created_at`.
  - `CreditPack` columns: `id`, `code`, `name`, `units`, `price_minor`, `currency`, `is_active`.
  - New `PlanTier` columns: `audience`, `allowance_units`, `paymob_plan_id`, `is_active`, `included_seats`, `seat_allowance_units`, `extra_seat_price_minor`.
  - New `Subscription` columns: `payer_user_id`, `cancel_at_period_end`, `pending_plan_tier_id`, `current_period_start`, `grace_until`, `extra_seats`, `pending_extra_seats`, `paymob_subscription_id` (BigInteger), and `version` (plain Integer, server default 1).
- **Phase 02** (other modules):
  - `lemely/io/paymob/client.py`:
    - `PaymobClient.create_intention(body: Mapping[str, Any]) -> dict[str, Any]` takes **one body dict**. The response holds `id`, `intention_order_id` and `payment_keys[0].key`.
    - `pay_with_token(*, card_token, payment_token) -> dict`, `inquire_by_order_ref(merchant_order_id) -> dict | None`, and `update_subscription(subscription_id, *, amount_cents=None, ends_at=None, next_billing=None) -> dict`.
    - `PaymobError(message, *, status_code=None, timeout=False, body=None)`. The client wraps transport errors and timeouts in it.
  - `lemely/db/billing_repo.py`:
    - `register_paid_handler(purpose, handler)` raises `ValueError` if a different handler is already registered for that purpose. Also `paid_handler_for(purpose)`, `PaidHandler`, `billing_data_for(user) -> dict[str, str]`, `add_months(moment, months)`, `CREDIT_EXPIRY_MONTHS = 12`, `RECONCILE_AFTER = timedelta(minutes=15)` and `WEBHOOK_PATH = "/api/webhooks/paymob/transaction"`.
    - `BillingService(session, client, settings, *, cipher=None, now=...)` with `card_token(card) -> str` (decrypts; raises `BillingError` when no key is configured).
    - `reconcile_pending` picks up `created`/`pending` payments whose `next_reconcile_at` is due.
  - `PaymobSettings` fields: `moto_integration_id: int | None`, `card_token_key: SecretStr | None`, `notification_base_url: str = "https://lemelyig.com"`, `checkout_configured`.
  - `lemely/web/deps_billing.py`: `get_paymob_client()`, `get_billing_sessionmaker()`, `get_billing_reconcile_job()` and `reset_billing_singletons()`.
  - The sweeper pattern: an optional `Sweeper` field of type `Callable[[datetime], int] | None`, built by a `deps_billing` provider (`None` when Paymob is unconfigured) and passed in `deps.get_sweeper`.
  - Router: `lemely/web/routers/billing.py`, `APIRouter(prefix="/api/billing")`. Its authz rows use `TUTORING_PARTY`.
  - Test fixtures in `tests/paymob_fixtures.py`: `PAYMOB_SETTINGS`, `TEST_CARD_TOKEN_KEY`, `MOTO_INTEGRATION_ID = 4569877`.
- **Phase 03** (`lemely/db/models/team.py`, `lemely/db/teacher_team_repo.py`):
  - `TeacherMember` columns: `id`, `teacher_user_id`, `member_user_id`, `kind`, `scope_subjects`, `scope_actions`, `status`, `leaves_at`, `created_at`.
  - Enums `TeacherMemberKind.student_seat` and `TeacherMemberStatus` (`active`, `leaving`, `removed`).
  - `TeacherTeamService(session)` with `seat_capacity`, `request_removal(member_id, *, now)` and the internal `_capacity(teacher_user_id, *, lock)`.
- **Phase 04** (`lemely/web/usage.py`): `MeteredJob._finish(cost_usd, *, settle)` opens `meter.sessionmaker.begin()` and calls `ledger.settle(self.job_id, actual_cost_usd=cost_usd, now=now)`. The chain is `self.ctx.chain: tuple[Payer, ...]` (on `UsageGrantContext`).
- **Phase 05** (`lemely/db/models/billing.py`, `lemely/db/subscription_repo.py`, `lemely/core/subscription_rules.py`):
  - `SubscriptionPeriod` columns: `id`, `subscription_id`, `period_start`, `period_end`, `payment_id`.
  - `Subscription.paymob_amount_minor` (the renewal amount Paymob holds).
  - `subscription_amount_minor(*, price_minor, extra_seats, extra_seat_price_minor) -> int`.
  - `SubscriptionService(session, client, settings)` (settings stored as `self._settings`) with `next_renewal_amount(subscription)`, `sync_renewal_amount(subscription) -> bool` (PUTs `next_renewal_amount` when it differs and stamps `paymob_amount_minor`; raises `PaymobError` on failure), `apply_period_end_changes` and `check_drift`. The module helper `_grant_renewal_period(session, subscription, payment, *, charged_at, now) -> SubscriptionPeriod` applies pending tier and seats and sheds excess seats. Also `_bump(subscription)`.
  - `NotificationType.billing`, and `BILLING_EMAIL_TEMPLATES` in `lemely/io/notify_email.py`, currently `{"subscription_notice"}`.
  - Migration revision `0055_subscription_periods`.

## File map

| File | Status | Responsibility |
|---|---|---|
| `lemely/db/migrations/versions/0056_auto_topup.py` | create | Table and columns |
| `lemely/db/models/billing.py` | modify | `AutoTopupSettings`; `Payment.dedupe_key`; `Subscription.extra_seat_grace_until`, `extra_seat_grace_payment_id` |
| `lemely/db/models/__init__.py` | modify | Re-export `AutoTopupSettings` |
| `lemely/io/notify_email.py` | modify | `auto_topup_failed`, `extra_seats_charge_failed` templates, added to `BILLING_EMAIL_TEMPLATES` |
| `lemely/db/merchant_charge_repo.py` | create | `MerchantChargeService`, handlers, jobs, auto top-up settings |
| `lemely/db/teacher_team_repo.py` | modify | `_capacity` honours a pending reduction |
| `lemely/db/subscription_repo.py` | modify | `next_renewal_amount` body only |
| `lemely/web/scheduled_notifications.py`, `lemely/web/deps.py` | modify | Two sweeper job fields and their wiring |
| `lemely/web/merchant_charge_deps.py` | create | `MerchantChargeDeps` bundle |
| `lemely/web/deps_billing.py` | modify | `get_merchant_charge_deps`, `get_auto_topup_job`, `get_extra_seat_renewal_job` |
| `lemely/web/schemas_billing_charges.py` | create | DTOs |
| `lemely/web/routers/billing.py` | modify | Upgrade, quotes, extra seats, auto top-up routes |
| `lemely/web/app.py` | modify | `configure_merchant_charges` and the post-settle hook registration |
| `tests/merchant_charge_seed.py` | create | Seed helpers shared by this phase's tests |
| `tests/fake_paymob_moto.py` | create | `FakeMotoClient` |
| `tests/test_migration_auto_topup.py`, `tests/test_billing_email_templates.py`, `tests/test_merchant_charge_core.py`, `tests/test_merchant_charge_upgrade.py`, `tests/test_merchant_charge_seats.py`, `tests/test_merchant_charge_renewal_seats.py`, `tests/test_usage_post_settle_hooks.py`, `tests/test_auto_topup_enqueue.py`, `tests/test_auto_topup_job.py`, `tests/test_web_billing_charges.py` | create | Tests |
| `tests/test_notify_email.py`, `tests/test_authz_matrix_complete.py` | modify | Pins updated for the new templates and routes |

## Tasks

1. Schema: migration `0056_auto_topup`, models, settings flag
2. Billing email templates
3. `MerchantChargeService.charge_saved_card`: insert, claim, intention, pay, inquiry
4. Upgrade with proration and the `upgrade_proration` paid handler
5. Extra seats: add, schedule a reduction, the `extra_seats` paid handler, seat capacity
6. Fallback renewal seat charge, grace, `billing.extra_seat_renewal_charge`
7. Post-settle hook and `maybe_enqueue_auto_topup`
8. `billing.auto_topup` job, the `auto_topup` paid handler, failure handling
9. Routes: upgrade, quotes, extra seats, auto top-up settings, with IDOR and authz tests

---

### Task 1: Schema: migration `0056_auto_topup`, models, settings flag

**Files:**
- Create: `lemely/db/migrations/versions/0056_auto_topup.py`
- Modify: `lemely/db/models/billing.py` (add `AutoTopupSettings`; add columns to `Payment` and `Subscription`)
- Modify: `lemely/db/models/__init__.py` (re-export `AutoTopupSettings`)
- Read only: `lemely/runtime/config.py` (`PaymobSettings.subscription_amount_updatable`, added by Phase 05 Task 8)
- Modify: `tests/test_db_schema.py` (`EXPECTED_TABLES` gains `"auto_topup_settings"`)
- Create: `tests/merchant_charge_seed.py`
- Create: `tests/test_migration_auto_topup.py`

**Interfaces:**
- Consumes: Phase 02 models (`Payment`, `SavedCard`, `CreditPack`, `PlanTier`, `Subscription`), Phase 02 test fixtures (`PAYMOB_SETTINGS`, `TEST_CARD_TOKEN_KEY` in `tests/paymob_fixtures.py`), Phase 02 `TokenCipher` (`lemely/runtime/token_cipher.py`), Phase 05 `SubscriptionPeriod` and `Subscription.paymob_amount_minor`, Phase 03 `TeacherMember`.
- Produces:
  - `AutoTopupSettings` with columns `id`, `beneficiary_user_id`, `payer_user_id`, `enabled`, `threshold_units`, `credit_pack_id`, `saved_card_id`, `monthly_cap_minor`, `armed`, `crossing_seq`, `last_payment_id`, `disabled_reason`, `created_at`, `updated_at`.
  - `Payment.dedupe_key: str | None`, `Subscription.extra_seat_grace_until: datetime | None` and `Subscription.extra_seat_grace_payment_id: UUID | None`.
  - (Consumed, not produced: `PaymobSettings.subscription_amount_updatable`, Phase 05 Task 8.)
  - Seed helpers in `tests/merchant_charge_seed.py`: `make_user`, `make_credit_pack`, `make_saved_card`, `make_tier`, `make_subscription`, `make_seat`, `make_payment`, `link_parent` and `paymob_settings`. Saved cards store real AES-GCM ciphertext under `TEST_CARD_TOKEN_KEY`, so `BillingService.card_token` decrypts them.

- [ ] **Step 1: Write the seed helpers**

Create `tests/merchant_charge_seed.py`:

```python
"""Seed helpers for the Phase 06 merchant-charge tests.

Each helper adds rows to the caller's session and flushes, so ids are available
before commit. Column names follow spec §4 and the Phase 02/03/05 models. If a
merged model has an extra NOT NULL column, set it here and nowhere else.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from lemely.db.models import ParentChildLink, User
from lemely.db.models.billing import (
    CreditPack,
    Payment,
    PaymentPurpose,
    PaymentStatus,
    PlanAudience,
    PlanTier,
    SavedCard,
    Subscription,
    SubscriptionPeriod,
)
from lemely.db.models.enums import PlanInterval, Role, SubscriptionStatus
from lemely.db.models.team import TeacherMember, TeacherMemberKind, TeacherMemberStatus
from lemely.runtime.config import PaymobSettings
from lemely.runtime.token_cipher import TokenCipher
from tests.paymob_fixtures import PAYMOB_SETTINGS, TEST_CARD_TOKEN_KEY

_CIPHER = TokenCipher(TEST_CARD_TOKEN_KEY)


def paymob_settings(**overrides: object) -> PaymobSettings:
    """Phase 02's test settings (MOTO id 4569877, card token key set) plus ``overrides``."""
    return PAYMOB_SETTINGS.model_copy(update=overrides)


def make_user(
    session: Session,
    role: Role = Role.student,
    *,
    display_name: str | None = "Mona Adel",
    phone: str | None = "+201000000001",
) -> User:
    uid = uuid.uuid4()
    user = User(
        id=uid, email=f"{uid}@example.com", role=role, display_name=display_name, phone=phone
    )
    session.add(user)
    session.flush()
    return user


def link_parent(session: Session, *, parent_id: uuid.UUID, child_id: uuid.UUID) -> None:
    session.add(ParentChildLink(parent_id=parent_id, child_id=child_id))
    session.flush()


def make_credit_pack(
    session: Session, *, units: int = 1_000, price_minor: int = 10_000, is_active: bool = True
) -> CreditPack:
    pack = CreditPack(
        code=f"pack_{uuid.uuid4().hex[:8]}",
        name="Starter pack",
        units=units,
        price_minor=price_minor,
        currency="EGP",
        is_active=is_active,
    )
    session.add(pack)
    session.flush()
    return pack


def make_saved_card(
    session: Session, user_id: uuid.UUID, *, token: str = "tok_live_like", is_active: bool = True
) -> SavedCard:
    card = SavedCard(
        user_id=user_id,
        token=_CIPHER.encrypt(token),
        token_fingerprint=_CIPHER.fingerprint(token),
        masked_pan="xxxx-2346",
        brand="mastercard",
        is_active=is_active,
    )
    session.add(card)
    session.flush()
    return card


def make_tier(
    session: Session,
    *,
    audience: PlanAudience = PlanAudience.student,
    price_minor: int = 10_000,
    allowance_units: int = 1_000,
    interval: PlanInterval = PlanInterval.monthly,
    included_seats: int | None = None,
    extra_seat_price_minor: int | None = None,
    is_active: bool = True,
) -> PlanTier:
    tier = PlanTier(
        code=f"tier_{uuid.uuid4().hex[:8]}",
        name="Tier",
        price_minor=price_minor,
        currency="EGP",
        interval=interval,
        audience=audience,
        allowance_units=allowance_units,
        is_active=is_active,
        included_seats=included_seats,
        seat_allowance_units=100 if audience is PlanAudience.teacher else None,
        extra_seat_price_minor=extra_seat_price_minor,
    )
    session.add(tier)
    session.flush()
    return tier


def make_payment(
    session: Session,
    *,
    payer_user_id: uuid.UUID,
    beneficiary_user_id: uuid.UUID | None = None,
    purpose: PaymentPurpose,
    amount_minor: int,
    status: PaymentStatus = PaymentStatus.created,
    subscription_id: uuid.UUID | None = None,
    plan_tier_id: uuid.UUID | None = None,
    credit_pack_id: uuid.UUID | None = None,
    seat_quantity: int | None = None,
    dedupe_key: str | None = None,
    paid_at: datetime | None = None,
) -> Payment:
    pid = uuid.uuid4()
    payment = Payment(
        id=pid,
        payer_user_id=payer_user_id,
        beneficiary_user_id=beneficiary_user_id or payer_user_id,
        purpose=purpose,
        amount_minor=amount_minor,
        currency="EGP",
        status=status,
        special_reference=str(pid),
        subscription_id=subscription_id,
        plan_tier_id=plan_tier_id,
        credit_pack_id=credit_pack_id,
        seat_quantity=seat_quantity,
        dedupe_key=dedupe_key,
        paid_at=paid_at,
    )
    session.add(payment)
    session.flush()
    return payment


def make_subscription(
    session: Session,
    *,
    user: User,
    tier: PlanTier,
    period_start: datetime,
    period_end: datetime,
    payer: User | None = None,
    extra_seats: int = 0,
    pending_extra_seats: int | None = None,
    status: SubscriptionStatus = SubscriptionStatus.active,
    paymob_subscription_id: int | None = 9001,
    paymob_amount_minor: int | None = None,
) -> tuple[Subscription, SubscriptionPeriod]:
    """``paymob_amount_minor`` defaults to plan price plus extra seats: Paymob in step."""
    payer_id = (payer or user).id
    in_step = tier.price_minor + extra_seats * (tier.extra_seat_price_minor or 0)
    sub = Subscription(
        user_id=user.id,
        payer_user_id=payer_id,
        plan_tier_id=tier.id,
        status=status,
        current_period_start=period_start,
        current_period_end=period_end,
        extra_seats=extra_seats,
        pending_extra_seats=pending_extra_seats,
        paymob_subscription_id=paymob_subscription_id,
        paymob_amount_minor=in_step if paymob_amount_minor is None else paymob_amount_minor,
    )
    session.add(sub)
    session.flush()
    first = make_payment(
        session,
        payer_user_id=payer_id,
        beneficiary_user_id=user.id,
        purpose=PaymentPurpose.subscription_first,
        amount_minor=tier.price_minor,
        status=PaymentStatus.paid,
        subscription_id=sub.id,
        plan_tier_id=tier.id,
        paid_at=period_start,
    )
    period = SubscriptionPeriod(
        subscription_id=sub.id, period_start=period_start, period_end=period_end, payment_id=first.id
    )
    session.add(period)
    session.flush()
    return sub, period


def make_seat(
    session: Session,
    *,
    teacher_user_id: uuid.UUID,
    created_at: datetime,
    status: TeacherMemberStatus = TeacherMemberStatus.active,
) -> TeacherMember:
    student = make_user(session, Role.student)
    member = TeacherMember(
        teacher_user_id=teacher_user_id,
        member_user_id=student.id,
        kind=TeacherMemberKind.student_seat,
        status=status,
        scope_subjects=[],
        scope_actions=[],
        created_at=created_at,
    )
    session.add(member)
    session.flush()
    return member


__all__ = [
    "link_parent",
    "make_credit_pack",
    "make_payment",
    "make_saved_card",
    "make_seat",
    "make_subscription",
    "make_tier",
    "make_user",
    "paymob_settings",
]
```

- [ ] **Step 2: Write the failing migration test**

Create `tests/test_migration_auto_topup.py`:

```python
"""Migration 0056_auto_topup: auto top-up settings and the merchant-charge columns.

Expected object names come from the ORM (``lemely/db/models/billing.py``), so the
migration is compared with an independent declaration.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.exc import IntegrityError

from lemely.db.base import Base
from lemely.db.models import import_all_models
from lemely.db.models.billing import AutoTopupSettings, PaymentPurpose
from lemely.db.models.enums import Role
from tests.merchant_charge_seed import (
    make_credit_pack,
    make_payment,
    make_saved_card,
    make_user,
)
from tests.test_migration_tutoring_enums import (
    current_revision,
    object_names,
    upgrade_head,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.orm import Session, sessionmaker

import_all_models()

REVISION = "0056_auto_topup"
DOWN_REVISION = "0055_subscription_periods"
TABLE = "auto_topup_settings"


def _orm_names() -> set[str]:
    table = Base.metadata.tables[TABLE]
    names = {str(constraint.name) for constraint in table.constraints}
    return names | {str(index.name) for index in table.indexes}


def test_orm_declares_the_named_objects() -> None:
    assert _orm_names() == {
        "pk_auto_topup_settings",
        "uq_auto_topup_settings_beneficiary_user_id",
        "fk_auto_topup_settings_beneficiary_user_id_users",
        "fk_auto_topup_settings_payer_user_id_users",
        "fk_auto_topup_settings_credit_pack_id_credit_packs",
        "fk_auto_topup_settings_saved_card_id_saved_cards",
        "fk_auto_topup_settings_last_payment_id_payments",
        "ck_auto_topup_settings_threshold_positive",
        "ck_auto_topup_settings_cap_nonnegative",
        "ck_auto_topup_settings_enabled_needs_card",
        "ix_auto_topup_settings_payer_user_id",
    }


def test_revision_chains_from_0055_and_is_in_the_history() -> None:
    """Index R10: in the history and chained from 0055, never "is the head"."""
    script_dir = ScriptDirectory.from_config(Config("alembic.ini"))
    revision = script_dir.get_revision(REVISION)
    assert revision is not None
    assert revision.down_revision == DOWN_REVISION
    assert len(REVISION) <= 32
    assert REVISION in {rev.revision for rev in script_dir.walk_revisions()}


def test_constraints_present_by_name(migrated_sessionmaker: sessionmaker[Session]) -> None:
    with migrated_sessionmaker() as session:
        assert object_names(session, [TABLE]) == _orm_names()


def test_one_setting_per_beneficiary(migrated_sessionmaker: sessionmaker[Session]) -> None:
    with migrated_sessionmaker() as session:
        child = make_user(session, Role.student)
        parent = make_user(session, Role.parent)
        pack = make_credit_pack(session)
        card = make_saved_card(session, parent.id)
        for _ in range(2):
            session.add(
                AutoTopupSettings(
                    beneficiary_user_id=child.id,
                    payer_user_id=parent.id,
                    enabled=True,
                    threshold_units=100,
                    credit_pack_id=pack.id,
                    saved_card_id=card.id,
                    monthly_cap_minor=50_000,
                )
            )
        with pytest.raises(IntegrityError):
            session.flush()


def test_enabled_setting_needs_a_card(migrated_sessionmaker: sessionmaker[Session]) -> None:
    with migrated_sessionmaker() as session:
        user = make_user(session, Role.student)
        pack = make_credit_pack(session)
        session.add(
            AutoTopupSettings(
                beneficiary_user_id=user.id,
                payer_user_id=user.id,
                enabled=True,
                threshold_units=100,
                credit_pack_id=pack.id,
                saved_card_id=None,
                monthly_cap_minor=50_000,
            )
        )
        with pytest.raises(IntegrityError):
            session.flush()


def test_payment_dedupe_key_is_unique(migrated_sessionmaker: sessionmaker[Session]) -> None:
    with migrated_sessionmaker() as session:
        user = make_user(session, Role.student)
        make_payment(
            session,
            payer_user_id=user.id,
            purpose=PaymentPurpose.auto_topup,
            amount_minor=100,
            dedupe_key="auto_topup:x:0",
        )
        with pytest.raises(IntegrityError):
            make_payment(
                session,
                payer_user_id=user.id,
                purpose=PaymentPurpose.auto_topup,
                amount_minor=100,
                dedupe_key="auto_topup:x:0",
            )


def test_upgrade_downgrade_upgrade_round_trip(
    migrated_sessionmaker_with_downgrade: tuple[sessionmaker[Session], Callable[[str], None]],
) -> None:
    sm, downgrade_to = migrated_sessionmaker_with_downgrade
    downgrade_to(DOWN_REVISION)
    with sm() as session:
        assert current_revision(session) == DOWN_REVISION
        tables = set(
            session.scalars(
                sa.text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            ).all()
        )
        assert TABLE not in tables
        payment_cols = set(
            session.scalars(
                sa.text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'payments'"
                )
            ).all()
        )
        assert "dedupe_key" not in payment_cols
    upgrade_head()
    with sm() as session:
        assert object_names(session, [TABLE]) == _orm_names()
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_migration_auto_topup.py -v --no-cov`
Expected: FAIL with `ImportError: cannot import name 'AutoTopupSettings'`.

- [ ] **Step 4: Add the models and columns**

In `lemely/db/models/billing.py`, add these columns to the existing `Payment` class (after its Paymob reference columns):

```python
    dedupe_key: Mapped[str | None] = mapped_column(sa.String(200), nullable=True, unique=True)
    """Queue identity for background charges (``auto_topup:{owner}:{crossing}``,
    ``extra_seat_renewal:{period}:{attempt}``). NULL for user-initiated payments."""
```

Add these columns to the existing `Subscription` class:

```python
    extra_seat_grace_until: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    """Fallback path (spec §5.4): when the extra seats lapse if no seat charge succeeds."""
    extra_seat_grace_payment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("payments.id", ondelete="SET NULL"), nullable=True
    )
    """First failed renewal seat charge of the grace episode; kept after the drop so the
    same failure never starts a second grace."""
```

Add the class, then add `"AutoTopupSettings"` to `__all__`:

```python
class AutoTopupSettings(TimestampMixin, Base):
    """Auto top-up for one balance (spec §4.6, §5.5).

    The payer owns the row and the card. The beneficiary owns the balance. ``armed`` and
    ``crossing_seq`` implement the dedupe key ``(user, threshold crossing)``: a crossing
    below the threshold enqueues at most one top-up and disarms; seeing the balance at or
    above the threshold again, or the top-up resolving, re-arms and bumps ``crossing_seq``.
    """

    __tablename__ = "auto_topup_settings"
    __table_args__ = (
        sa.UniqueConstraint("beneficiary_user_id"),
        sa.CheckConstraint("threshold_units > 0", name="threshold_positive"),
        sa.CheckConstraint("monthly_cap_minor >= 0", name="cap_nonnegative"),
        sa.CheckConstraint("NOT enabled OR saved_card_id IS NOT NULL", name="enabled_needs_card"),
        sa.Index("ix_auto_topup_settings_payer_user_id", "payer_user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
    )
    beneficiary_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    payer_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    enabled: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, server_default=sa.false())
    threshold_units: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    credit_pack_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("credit_packs.id"), nullable=False
    )
    saved_card_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("saved_cards.id", ondelete="SET NULL"), nullable=True
    )
    monthly_cap_minor: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    armed: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, server_default=sa.true())
    crossing_seq: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default=sa.literal(0)
    )
    last_payment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("payments.id", ondelete="SET NULL"), nullable=True
    )
    disabled_reason: Mapped[str | None] = mapped_column(sa.String, nullable=True)
```

In `lemely/db/models/__init__.py`, extend the billing import line to re-export it, next to the Phase 02 names already there: `from lemely.db.models.billing import AutoTopupSettings, …`. If that module keeps an `__all__`, add `"AutoTopupSettings"` to it too.

In `tests/test_db_schema.py`, add `"auto_topup_settings"` to the `EXPECTED_TABLES` set. `test_all_tables_present` asserts `set(Base.metadata.tables) == EXPECTED_TABLES`.

- [ ] **Step 5: Confirm the settings flag exists (owned by Phase 05)**

Phase 05 Task 8 adds `PaymobSettings.subscription_amount_updatable: bool = True` to `lemely/runtime/config.py`. This phase only reads it; do not add it again.

Run: `grep -n "subscription_amount_updatable" lemely/runtime/config.py`
Expected: one line declaring the field. If it is missing, Phase 05 is not merged: stop and report it.

- [ ] **Step 6: Write the migration**

Create `lemely/db/migrations/versions/0056_auto_topup.py`:

```python
"""auto top-up settings and merchant-charge columns (Paymob billing phase 06)

Revision ID: 0056_auto_topup
Revises: 0055_subscription_periods
Create Date: 2026-11-05 00:00:00.000000

* ``auto_topup_settings``: one row per beneficiary balance, owned by the payer (spec §4.6).
* ``payments.dedupe_key``: unique queue identity for background charges.
* ``subscriptions.extra_seat_grace_until`` / ``extra_seat_grace_payment_id``: fallback
  seat grace (spec §5.4).

The ``billing`` notification type already exists (migration 0055). ``downgrade`` drops
everything above and nothing else.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Kept to <=32 chars: alembic_version.version_num is varchar(32).
revision: str = "0056_auto_topup"
down_revision: str | Sequence[str] | None = "0055_subscription_periods"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "auto_topup_settings",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("beneficiary_user_id", sa.UUID(), nullable=False),
        sa.Column("payer_user_id", sa.UUID(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("threshold_units", sa.BigInteger(), nullable=False),
        sa.Column("credit_pack_id", sa.UUID(), nullable=False),
        sa.Column("saved_card_id", sa.UUID(), nullable=True),
        sa.Column("monthly_cap_minor", sa.BigInteger(), nullable=False),
        sa.Column("armed", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("crossing_seq", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_payment_id", sa.UUID(), nullable=True),
        sa.Column("disabled_reason", sa.String(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint("threshold_units > 0", name=op.f("ck_auto_topup_settings_threshold_positive")),
        sa.CheckConstraint("monthly_cap_minor >= 0", name=op.f("ck_auto_topup_settings_cap_nonnegative")),
        sa.CheckConstraint(
            "NOT enabled OR saved_card_id IS NOT NULL",
            name=op.f("ck_auto_topup_settings_enabled_needs_card"),
        ),
        sa.ForeignKeyConstraint(
            ["beneficiary_user_id"], ["users.id"],
            name=op.f("fk_auto_topup_settings_beneficiary_user_id_users"), ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["payer_user_id"], ["users.id"],
            name=op.f("fk_auto_topup_settings_payer_user_id_users"), ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["credit_pack_id"], ["credit_packs.id"],
            name=op.f("fk_auto_topup_settings_credit_pack_id_credit_packs"),
        ),
        sa.ForeignKeyConstraint(
            ["saved_card_id"], ["saved_cards.id"],
            name=op.f("fk_auto_topup_settings_saved_card_id_saved_cards"), ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["last_payment_id"], ["payments.id"],
            name=op.f("fk_auto_topup_settings_last_payment_id_payments"), ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auto_topup_settings")),
        sa.UniqueConstraint(
            "beneficiary_user_id", name=op.f("uq_auto_topup_settings_beneficiary_user_id")
        ),
    )
    op.create_index(
        "ix_auto_topup_settings_payer_user_id", "auto_topup_settings", ["payer_user_id"]
    )

    op.add_column("payments", sa.Column("dedupe_key", sa.String(length=200), nullable=True))
    op.create_unique_constraint(op.f("uq_payments_dedupe_key"), "payments", ["dedupe_key"])

    op.add_column(
        "subscriptions",
        sa.Column("extra_seat_grace_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "subscriptions", sa.Column("extra_seat_grace_payment_id", sa.UUID(), nullable=True)
    )
    op.create_foreign_key(
        op.f("fk_subscriptions_extra_seat_grace_payment_id_payments"),
        "subscriptions", "payments", ["extra_seat_grace_payment_id"], ["id"], ondelete="SET NULL",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        op.f("fk_subscriptions_extra_seat_grace_payment_id_payments"), "subscriptions",
        type_="foreignkey",
    )
    op.drop_column("subscriptions", "extra_seat_grace_payment_id")
    op.drop_column("subscriptions", "extra_seat_grace_until")
    op.drop_constraint(op.f("uq_payments_dedupe_key"), "payments", type_="unique")
    op.drop_column("payments", "dedupe_key")
    op.drop_table("auto_topup_settings")
```

Ruff format may rewrap the long lines. Accept its formatting.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_migration_auto_topup.py tests/test_db_schema.py -v --no-cov`
Expected: PASS. Per index R10, no migration test in the tree asserts that a revision is the head, so nothing earlier needs retargeting.

- [ ] **Step 8: Commit**

```bash
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files
git commit -S -m "feat(billing): add auto top-up settings and merchant-charge columns (0056)" -- \
  lemely/db/migrations/versions/0056_auto_topup.py lemely/db/models/billing.py \
  lemely/db/models/__init__.py tests/test_db_schema.py \
  tests/merchant_charge_seed.py tests/test_migration_auto_topup.py
```

---

### Task 2: Billing email templates

**Files:**
- Modify: `lemely/io/notify_email.py`
- Modify: `tests/test_notify_email.py`
- Create: `tests/test_billing_email_templates.py`

**Interfaces:**
- Consumes: `NotificationType.billing` (Phase 05, migration 0055) and Phase 05's `BILLING_EMAIL_TEMPLATES = frozenset({SubscriptionNotice.template})` in `lemely.io.notify_email`.
- Produces: template names `"auto_topup_failed"` (context `{"payment_id": str(uuid)}`) and `"extra_seats_charge_failed"` (context `{"subscription_id": str(uuid)}`). Both are added to `BILLING_EMAIL_TEMPLATES`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_billing_email_templates.py`:

```python
"""The two billing emails (spec §5.4, §5.5): schema, gating type, copy."""

from __future__ import annotations

import uuid

import pytest

from lemely.db.models.enums import NotificationType
from lemely.io.notify_email import (
    BILLING_EMAIL_TEMPLATES,
    EMAIL_TEMPLATES,
    InvalidEmailContext,
    validate_context,
)

PAYMENT_ID = uuid.UUID("66666666-6666-4666-8666-666666666666")
SUBSCRIPTION_ID = uuid.UUID("77777777-7777-4777-8777-777777777777")


def test_billing_templates_are_registered_and_gated_by_billing() -> None:
    assert {"auto_topup_failed", "extra_seats_charge_failed"} <= BILLING_EMAIL_TEMPLATES
    for name in ("auto_topup_failed", "extra_seats_charge_failed"):
        assert EMAIL_TEMPLATES[name].notification_type is NotificationType.billing  # type: ignore[attr-defined]


def test_auto_topup_failed_context() -> None:
    stored = validate_context("auto_topup_failed", {"payment_id": str(PAYMENT_ID)})
    assert stored == {"payment_id": str(PAYMENT_ID)}
    with pytest.raises(InvalidEmailContext):
        validate_context("auto_topup_failed", {"payment_id": str(PAYMENT_ID), "amount": 5})


def test_extra_seats_charge_failed_context() -> None:
    stored = validate_context("extra_seats_charge_failed", {"subscription_id": str(SUBSCRIPTION_ID)})
    assert stored == {"subscription_id": str(SUBSCRIPTION_ID)}


def test_copy_states_the_consequence_once() -> None:
    topup = EMAIL_TEMPLATES["auto_topup_failed"].model_validate({"payment_id": str(PAYMENT_ID)})
    assert "turned off" in topup.lead()
    assert topup.path() == "/billing"
    seats = EMAIL_TEMPLATES["extra_seats_charge_failed"].model_validate(
        {"subscription_id": str(SUBSCRIPTION_ID)}
    )
    assert "3 days" in seats.lead()
    assert seats.path() == "/billing"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_billing_email_templates.py -v --no-cov`
Expected: FAIL with `KeyError: 'auto_topup_failed'` (or an assertion error on the subset check).

- [ ] **Step 3: Add the templates**

In `lemely/io/notify_email.py`, add these classes after Phase 05's `SubscriptionNotice`:

```python
class AutoTopupFailed(EmailContext):
    template: ClassVar[str] = "auto_topup_failed"
    notification_type: ClassVar[NotificationType] = NotificationType.billing
    subject: ClassVar[str] = "Auto top-up could not charge your card"
    button: ClassVar[str] = "Open billing"

    payment_id: uuid.UUID

    def lead(self) -> str:
        return "We could not charge your saved card for an auto top-up, so auto top-up is turned off."

    def detail(self) -> str | None:
        return "You can check your card and turn auto top-up back on in billing settings."

    def path(self) -> str:
        return "/billing"


class ExtraSeatsChargeFailed(EmailContext):
    template: ClassVar[str] = "extra_seats_charge_failed"
    notification_type: ClassVar[NotificationType] = NotificationType.billing
    subject: ClassVar[str] = "Your extra seats payment failed"
    button: ClassVar[str] = "Open billing"

    subscription_id: uuid.UUID

    def lead(self) -> str:
        return (
            "We could not charge your card for your extra student seats. We will try again "
            "each day; if no payment succeeds within 3 days, the extra seats are removed."
        )

    def detail(self) -> str | None:
        return "Students beyond your plan's included seats then keep their seat until the end of the month."

    def path(self) -> str:
        return "/billing"
```

Add both classes to the end of `_TEMPLATE_CLASSES`, after `SubscriptionNotice`. Then extend Phase 05's set so it reads:

```python
#: Templates outside the tutoring spec's §b.4 table (Paymob billing).
BILLING_EMAIL_TEMPLATES: Final[frozenset[str]] = frozenset(
    {SubscriptionNotice.template, AutoTopupFailed.template, ExtraSeatsChargeFailed.template}
)
```

Add `"AutoTopupFailed"` and `"ExtraSeatsChargeFailed"` to `__all__`.

- [ ] **Step 4: Update Phase 05's billing pin**

In `tests/test_notify_email.py`, Phase 05's `test_billing_templates_are_disjoint_from_the_tutoring_spec` asserts `BILLING_EMAIL_TEMPLATES == {"subscription_notice"}`. Change that line to:

```python
    assert BILLING_EMAIL_TEMPLATES == {
        "subscription_notice", "auto_topup_failed", "extra_seats_charge_failed",
    }
```

Leave `test_templates_are_exactly_the_ones_the_spec_table_names` alone; Phase 05 already changed it to `set(EMAIL_TEMPLATES) - BILLING_EMAIL_TEMPLATES == named`. Leave `VALID` alone too, since Phase 05 does not add billing templates to it. The forbidden-field test still passes, because `payment_id` and `subscription_id` do not match its pattern.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_billing_email_templates.py tests/test_notify_email.py tests/test_email_outbox_repo.py tests/test_tutoring_email.py -v --no-cov`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files
git commit -S -m "feat(billing): add auto top-up and extra-seat failure emails" -- \
  lemely/io/notify_email.py tests/test_notify_email.py tests/test_billing_email_templates.py
```

---

### Task 3: `MerchantChargeService.charge_saved_card`: insert, claim, intention, pay, inquiry

**Files:**
- Create: `lemely/db/merchant_charge_repo.py`
- Create: `tests/fake_paymob_moto.py`
- Create: `tests/test_merchant_charge_core.py`

**Interfaces:**
- Consumes:
  - Phase 02 `PaymobClient`: `create_intention(body)`, `pay_with_token(*, card_token, payment_token)` and `inquire_by_order_ref(merchant_order_id)`.
  - `PaymobError` (it wraps timeouts: `timeout=True`).
  - `BillingService(session, client, settings).card_token(card)` (decrypts the AES-GCM token), `billing_data_for(user)`, `WEBHOOK_PATH` and `RECONCILE_AFTER`.
  - Models `Payment` (with `next_reconcile_at`), `PaymentStatus` and `SavedCard`.
  - `PaymobSettings.moto_integration_id` and `PaymobSettings.notification_base_url`.
- Produces:
  - `MerchantChargeService(session: Session, client: PaymobClient, settings: PaymobSettings)`.
  - `MerchantChargeService.charge_saved_card(payment: Payment, card: SavedCard) -> None`, plus `active_card(payer_user_id) -> SavedCard | None` and `_new_payment(...) -> Payment` (used by Tasks 4, 5, 7).
  - `MerchantChargeError(code: str, message: str)` with `.code`, and `ChargeAlreadyAttempted(Exception)`.
  - Module constants `IN_FLIGHT_STATUSES`, `FAILED_STATUSES`.

- [ ] **Step 1: Write the fake client**

Create `tests/fake_paymob_moto.py`:

```python
"""A recording stand-in for the parts of ``PaymobClient`` a merchant charge uses."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker

from lemely.db.models.billing import Payment


@dataclass
class FakeMotoClient:
    #: When set, ``create_intention`` reads the payment's status in a *separate* session,
    #: proving the row was committed before Paymob heard of it.
    sessionmaker: sessionmaker[Session] | None = None
    pay_result: Mapping[str, Any] | BaseException = field(
        default_factory=lambda: {"id": 777001, "success": True, "pending": False}
    )
    intention_error: BaseException | None = None
    inquiry_result: Mapping[str, Any] | BaseException | None = None
    update_error: BaseException | None = None
    #: Runs inside ``pay_with_token`` before it answers (to simulate a racing callback).
    on_pay: Callable[[], None] | None = None
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    committed_status_at_intention: list[str] = field(default_factory=list)
    _order_seq: int = 5000

    def count(self, name: str) -> int:
        return sum(1 for call, _ in self.calls if call == name)

    def kwargs_of(self, name: str) -> list[dict[str, Any]]:
        return [kwargs for call, kwargs in self.calls if call == name]

    def create_intention(self, body: Mapping[str, Any]) -> Mapping[str, Any]:
        """Phase 02 signature: one body dict, as ``POST v1/intention/`` takes it."""
        self.calls.append(("create_intention", dict(body)))
        if self.sessionmaker is not None:
            with self.sessionmaker() as session:
                status = session.scalar(
                    sa.select(Payment.status).where(
                        Payment.special_reference == body["special_reference"]
                    )
                )
            self.committed_status_at_intention.append(status.value if status else "missing")
        if self.intention_error is not None:
            raise self.intention_error
        self._order_seq += 1
        return {
            "id": f"pi_test_{self._order_seq}",
            "intention_order_id": self._order_seq,
            "client_secret": f"cs_test_{self._order_seq}",
            "payment_keys": [
                {"key": f"ptok_{self._order_seq}", "integration": body["payment_methods"][0]}
            ],
        }

    def pay_with_token(self, *, card_token: str, payment_token: str) -> Mapping[str, Any]:
        self.calls.append(("pay_with_token", {"card_token": card_token, "payment_token": payment_token}))
        if self.on_pay is not None:
            self.on_pay()
        if isinstance(self.pay_result, BaseException):
            raise self.pay_result
        return self.pay_result

    def inquire_by_order_ref(self, merchant_order_id: str) -> Mapping[str, Any] | None:
        self.calls.append(("inquire_by_order_ref", {"merchant_order_id": merchant_order_id}))
        if isinstance(self.inquiry_result, BaseException):
            raise self.inquiry_result
        return self.inquiry_result

    def update_subscription(self, subscription_id: int, **kwargs: Any) -> Mapping[str, Any]:
        self.calls.append(("update_subscription", {"subscription_id": subscription_id, **kwargs}))
        if self.update_error is not None:
            raise self.update_error
        return {"id": subscription_id, **kwargs}


__all__ = ["FakeMotoClient"]
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_merchant_charge_core.py`:

```python
"""charge_saved_card: record first, claim once, never retry blindly (spec §6)."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa

from lemely.db.merchant_charge_repo import (
    ChargeAlreadyAttempted,
    MerchantChargeError,
    MerchantChargeService,
)
from lemely.db.models.billing import Payment, PaymentPurpose, PaymentStatus, SavedCard
from lemely.db.models.enums import Role
from lemely.io.paymob.client import PaymobError
from tests.fake_paymob_moto import FakeMotoClient

TIMEOUT = PaymobError("Paymob POST api/acceptance/payments/pay timed out", timeout=True)
from tests.merchant_charge_seed import (
    make_credit_pack,
    make_payment,
    make_saved_card,
    make_user,
    paymob_settings,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker

SETTINGS = paymob_settings()


def _seed(sm: sessionmaker[Session], *, card_owner_is_payer: bool = True) -> tuple[uuid.UUID, uuid.UUID]:
    with sm.begin() as s:
        payer = make_user(s, Role.student)
        other = make_user(s, Role.student)
        card = make_saved_card(s, payer.id if card_owner_is_payer else other.id, token="tok_abc")
        pack = make_credit_pack(s, price_minor=10_000)
        payment = make_payment(
            s,
            payer_user_id=payer.id,
            purpose=PaymentPurpose.auto_topup,
            amount_minor=10_000,
            credit_pack_id=pack.id,
        )
        return payment.id, card.id


def _charge(sm: sessionmaker[Session], fake: FakeMotoClient, payment_id: uuid.UUID, card_id: uuid.UUID) -> None:
    with sm() as s:
        MerchantChargeService(s, fake, SETTINGS).charge_saved_card(
            s.get_one(Payment, payment_id), s.get_one(SavedCard, card_id)
        )


def _status(sm: sessionmaker[Session], payment_id: uuid.UUID) -> PaymentStatus:
    with sm() as s:
        return s.get_one(Payment, payment_id).status


def test_payment_row_is_committed_before_paymob_is_called(migrated_sessionmaker: sessionmaker[Session]) -> None:
    payment_id, card_id = _seed(migrated_sessionmaker)
    fake = FakeMotoClient(sessionmaker=migrated_sessionmaker)
    _charge(migrated_sessionmaker, fake, payment_id, card_id)
    assert fake.committed_status_at_intention == ["pending"]


def test_accepted_charge_waits_for_the_verified_callback(migrated_sessionmaker: sessionmaker[Session]) -> None:
    payment_id, card_id = _seed(migrated_sessionmaker)
    fake = FakeMotoClient()
    _charge(migrated_sessionmaker, fake, payment_id, card_id)
    intention = fake.kwargs_of("create_intention")[0]
    assert intention["payment_methods"] == [4569877]  # PAYMOB_SETTINGS.moto_integration_id
    assert intention["amount"] == 10_000
    assert intention["currency"] == "EGP"
    assert intention["special_reference"] == str(payment_id)
    assert intention["notification_url"] == "https://lemelyig.com/api/webhooks/paymob/transaction"
    assert set(intention["billing_data"]) >= {"first_name", "last_name", "email", "phone_number"}
    # The decrypted token, never the stored ciphertext.
    assert fake.kwargs_of("pay_with_token") == [{"card_token": "tok_abc", "payment_token": "ptok_5001"}]
    with migrated_sessionmaker() as s:
        payment = s.get_one(Payment, payment_id)
        assert payment.status is PaymentStatus.pending  # only the callback marks it paid
        assert payment.paymob_order_id == 5001
        assert payment.paymob_intention_id == "pi_test_5001"
        assert payment.next_reconcile_at is not None  # billing.reconcile_pending covers it


def test_declined_charge_is_marked_failed(migrated_sessionmaker: sessionmaker[Session]) -> None:
    payment_id, card_id = _seed(migrated_sessionmaker)
    fake = FakeMotoClient(pay_result={"id": 1, "success": False, "pending": False})
    _charge(migrated_sessionmaker, fake, payment_id, card_id)
    assert _status(migrated_sessionmaker, payment_id) is PaymentStatus.failed


def test_timeout_queries_inquiry_and_never_retries_pay(migrated_sessionmaker: sessionmaker[Session]) -> None:
    payment_id, card_id = _seed(migrated_sessionmaker)
    fake = FakeMotoClient(
        pay_result=TIMEOUT,
        inquiry_result={"id": 9, "success": True, "pending": False},
    )
    _charge(migrated_sessionmaker, fake, payment_id, card_id)
    assert fake.count("pay_with_token") == 1
    assert fake.kwargs_of("inquire_by_order_ref") == [{"merchant_order_id": str(payment_id)}]
    assert _status(migrated_sessionmaker, payment_id) is PaymentStatus.pending


def test_timeout_then_declined_inquiry_marks_failed(migrated_sessionmaker: sessionmaker[Session]) -> None:
    payment_id, card_id = _seed(migrated_sessionmaker)
    fake = FakeMotoClient(
        pay_result=TIMEOUT,
        inquiry_result={"id": 9, "success": False, "pending": False},
    )
    _charge(migrated_sessionmaker, fake, payment_id, card_id)
    assert fake.count("pay_with_token") == 1
    assert _status(migrated_sessionmaker, payment_id) is PaymentStatus.failed


@pytest.mark.parametrize("inquiry", [None, PaymobError("down")])
def test_unknown_outcome_leaves_payment_pending(
    migrated_sessionmaker: sessionmaker[Session], inquiry: object
) -> None:
    payment_id, card_id = _seed(migrated_sessionmaker)
    fake = FakeMotoClient(pay_result=TIMEOUT, inquiry_result=inquiry)  # type: ignore[arg-type]
    _charge(migrated_sessionmaker, fake, payment_id, card_id)
    assert fake.count("pay_with_token") == 1
    assert _status(migrated_sessionmaker, payment_id) is PaymentStatus.pending


def test_second_charge_attempt_is_refused(migrated_sessionmaker: sessionmaker[Session]) -> None:
    payment_id, card_id = _seed(migrated_sessionmaker)
    fake = FakeMotoClient(pay_result=TIMEOUT)
    _charge(migrated_sessionmaker, fake, payment_id, card_id)
    with pytest.raises(ChargeAlreadyAttempted):
        _charge(migrated_sessionmaker, fake, payment_id, card_id)
    assert fake.count("pay_with_token") == 1


def test_intention_failure_never_calls_pay(migrated_sessionmaker: sessionmaker[Session]) -> None:
    payment_id, card_id = _seed(migrated_sessionmaker)
    fake = FakeMotoClient(intention_error=TIMEOUT)
    _charge(migrated_sessionmaker, fake, payment_id, card_id)
    assert fake.count("pay_with_token") == 0
    # Left for billing.reconcile_pending: inquiry by merchant_order_id, then failed after 24 h.
    assert _status(migrated_sessionmaker, payment_id) is PaymentStatus.pending


def test_card_of_another_user_is_refused(migrated_sessionmaker: sessionmaker[Session]) -> None:
    payment_id, card_id = _seed(migrated_sessionmaker, card_owner_is_payer=False)
    fake = FakeMotoClient()
    with pytest.raises(MerchantChargeError) as excinfo:
        _charge(migrated_sessionmaker, fake, payment_id, card_id)
    assert excinfo.value.code == "no_saved_card"
    assert fake.calls == []
    assert _status(migrated_sessionmaker, payment_id) is PaymentStatus.created


def test_late_decline_never_overwrites_a_paid_callback(migrated_sessionmaker: sessionmaker[Session]) -> None:
    payment_id, card_id = _seed(migrated_sessionmaker)

    def callback_lands_first() -> None:
        with migrated_sessionmaker.begin() as s:
            s.execute(
                sa.update(Payment).where(Payment.id == payment_id).values(status=PaymentStatus.paid)
            )

    fake = FakeMotoClient(
        pay_result={"id": 1, "success": False, "pending": False}, on_pay=callback_lands_first
    )
    _charge(migrated_sessionmaker, fake, payment_id, card_id)
    assert _status(migrated_sessionmaker, payment_id) is PaymentStatus.paid
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_merchant_charge_core.py -v --no-cov`
Expected: FAIL with `ModuleNotFoundError: No module named 'lemely.db.merchant_charge_repo'`.

- [ ] **Step 4: Write the module core**

Create `lemely/db/merchant_charge_repo.py`:

```python
"""Merchant-initiated (MOTO) charges: upgrade proration, extra seats, auto top-up.

Spec §5.3–§5.5 and §6. A charge always runs in this order:

1. The caller inserts a ``payments`` row (``created``).
2. :meth:`MerchantChargeService.charge_saved_card` claims it with a conditional
   ``created → pending`` update and **commits**, so the row is durable before Paymob
   hears of it and a second worker can never charge it again.
3. A MOTO intention is created, then ``POST api/acceptance/payments/pay`` with the
   saved card token (research 02 §5).
4. A decline is recorded as ``failed``. An accepted charge stays ``pending``: only the
   verified transaction callback (or ``billing.reconcile_pending``'s inquiry) marks it
   ``paid`` and dispatches the purpose handler registered here.
5. A timeout or transport error is never retried. The service asks Paymob's inquiry API
   by ``merchant_order_id`` once and records a definite decline. Anything else is left
   ``pending`` for reconciliation.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

import httpx
import sqlalchemy as sa
import structlog

from lemely.db.billing_repo import (
    RECONCILE_AFTER,
    WEBHOOK_PATH,
    BillingError,
    BillingService,
    billing_data_for,
)
from lemely.db.models.billing import Payment, PaymentPurpose, PaymentStatus, SavedCard
from lemely.db.models.users import User
from lemely.io.paymob.client import PaymobError

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from lemely.io.paymob.client import PaymobClient
    from lemely.runtime.config import PaymobSettings

log = structlog.get_logger(__name__)

#: A payment in one of these states may still turn into money.
IN_FLIGHT_STATUSES: Final = (PaymentStatus.created, PaymentStatus.pending)
#: A payment in one of these states definitely did not take money.
FAILED_STATUSES: Final = (PaymentStatus.failed, PaymentStatus.failed_mismatch, PaymentStatus.voided)

#: Paymob item names are capped at 50 characters (research 04 §5).
_ITEM_NAMES: Final[Mapping[PaymentPurpose, str]] = {
    PaymentPurpose.upgrade_proration: "Plan upgrade (prorated)",
    PaymentPurpose.extra_seats: "Extra student seats",
    PaymentPurpose.auto_topup: "Credit auto top-up",
}

#: Errors whose outcome is unknown: the request may or may not have reached Paymob.
#: Phase 02's client wraps transport errors and timeouts in ``PaymobError``; raw
#: ``httpx.HTTPError`` is listed too so an unwrapped one can never escape as "no charge".
_AMBIGUOUS: Final = (httpx.HTTPError, PaymobError)


class MerchantChargeError(Exception):
    """A request refused before any money moved. ``code`` is the API error code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ChargeAlreadyAttempted(Exception):
    """The payment was already claimed for charging; charging it again is forbidden."""


class MerchantChargeService:
    """Builds and sends merchant-initiated charges.

    The caller owns ``session``. :meth:`charge_saved_card` commits by design (spec §6:
    record before calling Paymob). Other methods leave the final commit to the caller.
    """

    def __init__(self, session: Session, client: PaymobClient, settings: PaymobSettings) -> None:
        self.session = session
        self.client = client
        self.settings = settings

    # -- Building blocks -----------------------------------------------------------

    def active_card(self, payer_user_id: uuid.UUID) -> SavedCard | None:
        """The payer's most recently saved active card, or ``None``."""
        return self.session.scalars(
            sa.select(SavedCard)
            .where(SavedCard.user_id == payer_user_id, SavedCard.is_active.is_(True))
            .order_by(SavedCard.created_at.desc(), SavedCard.id.desc())
            .limit(1)
        ).first()

    def _new_payment(
        self,
        *,
        purpose: PaymentPurpose,
        payer_user_id: uuid.UUID,
        beneficiary_user_id: uuid.UUID,
        amount_minor: int,
        currency: str,
        subscription_id: uuid.UUID | None = None,
        plan_tier_id: uuid.UUID | None = None,
        credit_pack_id: uuid.UUID | None = None,
        seat_quantity: int | None = None,
        dedupe_key: str | None = None,
    ) -> Payment:
        payment_id = uuid.uuid4()
        payment = Payment(
            id=payment_id,
            purpose=purpose,
            payer_user_id=payer_user_id,
            beneficiary_user_id=beneficiary_user_id,
            amount_minor=amount_minor,
            currency=currency,
            status=PaymentStatus.created,
            special_reference=str(payment_id),
            subscription_id=subscription_id,
            plan_tier_id=plan_tier_id,
            credit_pack_id=credit_pack_id,
            seat_quantity=seat_quantity,
            dedupe_key=dedupe_key,
        )
        self.session.add(payment)
        self.session.flush()
        return payment

    def _notification_url(self) -> str:
        return f"{self.settings.notification_base_url}{WEBHOOK_PATH}"

    def _card_token(self, card: SavedCard) -> str:
        """Decrypt the stored AES-GCM token through Phase 02's one decryption point."""
        try:
            return BillingService(self.session, self.client, self.settings).card_token(card)
        except (BillingError, ValueError) as exc:
            raise MerchantChargeError("no_saved_card", "The saved card cannot be used.") from exc

    # -- The charge ----------------------------------------------------------------

    def charge_saved_card(self, payment: Payment, card: SavedCard) -> None:
        """Charge ``card`` for ``payment`` once. Never retries; see the module docstring.

        Raises:
            MerchantChargeError: ``no_saved_card`` if the card is inactive or not the payer's.
            ChargeAlreadyAttempted: the payment is no longer ``created``.
        """
        if card.user_id != payment.payer_user_id or not card.is_active:
            raise MerchantChargeError("no_saved_card", "The payer has no usable saved card.")
        if self.settings.moto_integration_id is None:
            raise MerchantChargeError("charges_unavailable", "Merchant-initiated charges are not configured.")
        card_token = self._card_token(card)
        payer = self.session.get_one(User, payment.payer_user_id)
        claimed = self.session.execute(
            sa.update(Payment)
            .where(Payment.id == payment.id, Payment.status == PaymentStatus.created)
            .values(
                status=PaymentStatus.pending,
                method="card_moto",
                # billing.reconcile_pending (Phase 02) inquires once this is due.
                next_reconcile_at=datetime.now(UTC) + RECONCILE_AFTER,
                updated_at=sa.func.now(),
            )
            .returning(Payment.id)
        ).scalar_one_or_none()
        if claimed is None:
            self.session.rollback()
            raise ChargeAlreadyAttempted(str(payment.id))
        self.session.commit()
        self.session.refresh(payment)

        body: dict[str, Any] = {
            "amount": payment.amount_minor,
            "currency": payment.currency,
            "payment_methods": [self.settings.moto_integration_id],
            "items": [
                {"name": _ITEM_NAMES[payment.purpose], "amount": payment.amount_minor, "quantity": 1}
            ],
            "billing_data": billing_data_for(payer),
            "special_reference": payment.special_reference,
            "notification_url": self._notification_url(),
            "extras": {"payment_id": str(payment.id), "purpose": payment.purpose.value},
        }
        try:
            intention = self.client.create_intention(body)
        except _AMBIGUOUS:
            log.warning("moto_intention_failed", payment_id=str(payment.id), exc_info=True)
            return
        payment.paymob_intention_id = str(intention["id"])
        payment.paymob_order_id = int(intention["intention_order_id"])
        self.session.commit()

        try:
            result: Mapping[str, Any] | None = self.client.pay_with_token(
                card_token=card_token, payment_token=str(intention["payment_keys"][0]["key"])
            )
        except _AMBIGUOUS:
            log.warning("moto_pay_outcome_unknown", payment_id=str(payment.id), exc_info=True)
            result = self._inquire(payment)
        if result is not None:
            self._record_sync_answer(payment, result)

    def _inquire(self, payment: Payment) -> Mapping[str, Any] | None:
        try:
            return self.client.inquire_by_order_ref(payment.special_reference)
        except _AMBIGUOUS:
            log.warning("moto_inquiry_failed", payment_id=str(payment.id), exc_info=True)
            return None

    def _record_sync_answer(self, payment: Payment, obj: Mapping[str, Any]) -> None:
        """Record a definite decline. Success and pending wait for the verified callback."""
        if obj.get("success") is True or obj.get("pending") is True:
            log.info("moto_charge_accepted", payment_id=str(payment.id), txn_id=obj.get("id"))
            return
        self.session.execute(
            sa.update(Payment)
            .where(Payment.id == payment.id, Payment.status == PaymentStatus.pending)
            .values(status=PaymentStatus.failed, updated_at=sa.func.now())
        )
        self.session.commit()
        log.info("moto_charge_declined", payment_id=str(payment.id), txn_id=obj.get("id"))


__all__ = [
    "FAILED_STATUSES",
    "IN_FLIGHT_STATUSES",
    "ChargeAlreadyAttempted",
    "MerchantChargeError",
    "MerchantChargeService",
]
```

Phase 02 declares `payments.paymob_order_id` as `BigInteger`, which is why `int(...)` is used.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_merchant_charge_core.py tests/architecture/ -v --no-cov`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files
git commit -S -m "feat(billing): charge saved cards via MOTO with record-first, inquiry-before-retry" -- \
  lemely/db/merchant_charge_repo.py tests/fake_paymob_moto.py tests/test_merchant_charge_core.py
```

---

### Task 4: Upgrade with proration and the `upgrade_proration` paid handler

**Files:**
- Modify: `lemely/db/merchant_charge_repo.py`
- Modify: `lemely/web/app.py` (call `configure_merchant_charges` in `create_app()`)
- Modify: `lemely/db/subscription_repo.py` (body of `SubscriptionService.next_renewal_amount` only; index R6)
- Create: `tests/test_merchant_charge_upgrade.py`

**Interfaces:**
- Consumes:
  - Task 3: `MerchantChargeService`, `_new_payment`, `active_card`, `charge_saved_card`, `MerchantChargeError`.
  - Phase 01: `prorate_minor`, `prorate_units`, `UsageLedger.issue_grant` and `GrantKind.period_allowance`.
  - Phase 02: `register_paid_handler` and `paid_handler_for`. Phase 05: `subscription_amount_minor` (`lemely/core/subscription_rules.py`).
  - Models `PlanTier`, `Subscription` (with Phase 05's `paymob_amount_minor`), `SubscriptionPeriod` and `TeacherMember`.
  - `lemely.web.deps_billing.get_paymob_client`.
- Produces:
  - Helpers `expected_renewal_amount_minor(subscription: Subscription, tier: PlanTier, settings: PaymobSettings) -> int` (fallback-aware; Task 6 makes Phase 05's `next_renewal_amount` return it), `capacity_extra_seats(subscription) -> int` and `seated_count(session, teacher_user_id) -> int`.
  - `MerchantChargeService.upgrade(*, subscription_id: UUID, actor_user_id: UUID, plan_tier_id: UUID, now: datetime) -> Payment`.
  - `MerchantChargeService.quote_upgrade(...same args) -> ChargeQuote` and the frozen dataclass `ChargeQuote(amount_minor: int, currency: str, allowance_units: int | None, period_end: datetime)`.
  - `on_upgrade_paid(session, payment, *, client: PaymobClient | None, settings: PaymobSettings | None) -> None`.
  - `push_subscription_amount(session, client, settings, subscription) -> bool`, a thin wrapper over Phase 05's `SubscriptionService.sync_renewal_amount`, which PUTs and stamps `paymob_amount_minor` (index R6).
  - `configure_merchant_charges(client_factory: Callable[[], PaymobClient], settings: PaymobSettings) -> None`.
  - The module-level paid handler `handle_upgrade_paid(session, payment, obj)`, registered on import. Task 5 adds `handle_extra_seats_paid` and Task 8 adds `handle_auto_topup_paid` the same way.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_merchant_charge_upgrade.py`:

```python
"""Upgrade (spec §5.3): prorated charge now; tier, allowance and Paymob amount on callback."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa

import lemely.db.merchant_charge_repo as mcr
from lemely.db.merchant_charge_repo import MerchantChargeError, MerchantChargeService, on_upgrade_paid
from lemely.io.paymob.client import PaymobError
from lemely.db.models.billing import (
    Payment,
    PaymentPurpose,
    PaymentStatus,
    PlanAudience,
    Subscription,
)
from lemely.db.models.enums import PlanInterval, Role, SubscriptionStatus
from lemely.db.models.usage import GrantKind, UsageGrant
from tests.fake_paymob_moto import FakeMotoClient
from tests.merchant_charge_seed import (
    make_payment,
    make_saved_card,
    make_seat,
    make_subscription,
    make_tier,
    make_user,
    paymob_settings,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker

START = datetime(2026, 11, 1, tzinfo=UTC)
END = datetime(2026, 12, 1, tzinfo=UTC)
NOW = datetime(2026, 11, 16, tzinfo=UTC)  # half the period left
SETTINGS = paymob_settings()


def _seed(sm: sessionmaker[Session], *, card: bool = True) -> dict[str, uuid.UUID]:
    with sm.begin() as s:
        user = make_user(s, Role.student)
        basic = make_tier(s, price_minor=10_000, allowance_units=1_000)
        plus = make_tier(s, price_minor=20_000, allowance_units=3_000)
        cheaper = make_tier(s, price_minor=5_000)
        yearly = make_tier(s, price_minor=90_000, interval=PlanInterval.yearly)
        teacher_tier = make_tier(s, audience=PlanAudience.teacher, price_minor=30_000, included_seats=2)
        sub, period = make_subscription(s, user=user, tier=basic, period_start=START, period_end=END)
        if card:
            make_saved_card(s, user.id)
        return {
            "user": user.id, "basic": basic.id, "plus": plus.id, "cheaper": cheaper.id,
            "yearly": yearly.id, "teacher_tier": teacher_tier.id, "sub": sub.id, "period": period.id,
        }


def _upgrade(sm: sessionmaker[Session], fake: FakeMotoClient, ids: dict[str, uuid.UUID], *,
             tier: str = "plus", actor: uuid.UUID | None = None, settings: object = SETTINGS) -> Payment:
    with sm() as s:
        payment = MerchantChargeService(s, fake, settings).upgrade(  # type: ignore[arg-type]
            subscription_id=ids["sub"], actor_user_id=actor or ids["user"],
            plan_tier_id=ids[tier], now=NOW,
        )
        s.commit()
        return payment


def test_upgrade_charges_the_prorated_difference(migrated_sessionmaker: sessionmaker[Session]) -> None:
    ids = _seed(migrated_sessionmaker)
    fake = FakeMotoClient()
    payment = _upgrade(migrated_sessionmaker, fake, ids)
    assert fake.kwargs_of("create_intention")[0]["amount"] == 5_000
    with migrated_sessionmaker() as s:
        row = s.get_one(Payment, payment.id)
        assert row.purpose is PaymentPurpose.upgrade_proration
        assert row.amount_minor == 5_000
        assert row.plan_tier_id == ids["plus"]
        assert row.subscription_id == ids["sub"]
        assert row.status is PaymentStatus.pending
        # Nothing switches before the verified callback.
        assert s.get_one(Subscription, ids["sub"]).plan_tier_id == ids["basic"]


@pytest.mark.parametrize(
    ("tier", "code"),
    [("cheaper", "not_an_upgrade"), ("yearly", "not_an_upgrade"), ("teacher_tier", "not_an_upgrade")],
)
def test_non_upgrades_are_refused(migrated_sessionmaker: sessionmaker[Session], tier: str, code: str) -> None:
    ids = _seed(migrated_sessionmaker)
    fake = FakeMotoClient()
    with pytest.raises(MerchantChargeError) as excinfo:
        _upgrade(migrated_sessionmaker, fake, ids, tier=tier)
    assert excinfo.value.code == code
    assert fake.calls == []


def test_only_the_payer_can_upgrade(migrated_sessionmaker: sessionmaker[Session]) -> None:
    ids = _seed(migrated_sessionmaker)
    with migrated_sessionmaker.begin() as s:
        stranger = make_user(s, Role.student).id
    with pytest.raises(MerchantChargeError) as excinfo:
        _upgrade(migrated_sessionmaker, FakeMotoClient(), ids, actor=stranger)
    assert excinfo.value.code == "not_found"


def test_upgrade_needs_an_active_subscription(migrated_sessionmaker: sessionmaker[Session]) -> None:
    ids = _seed(migrated_sessionmaker)
    with migrated_sessionmaker.begin() as s:
        s.get_one(Subscription, ids["sub"]).status = SubscriptionStatus.past_due
    with pytest.raises(MerchantChargeError) as excinfo:
        _upgrade(migrated_sessionmaker, FakeMotoClient(), ids)
    assert excinfo.value.code == "subscription_not_active"


def test_upgrade_needs_a_saved_card(migrated_sessionmaker: sessionmaker[Session]) -> None:
    ids = _seed(migrated_sessionmaker, card=False)
    with pytest.raises(MerchantChargeError) as excinfo:
        _upgrade(migrated_sessionmaker, FakeMotoClient(), ids)
    assert excinfo.value.code == "no_saved_card"


def test_one_charge_in_flight_per_subscription(migrated_sessionmaker: sessionmaker[Session]) -> None:
    ids = _seed(migrated_sessionmaker)
    fake = FakeMotoClient(pay_result=PaymobError("timed out", timeout=True))
    _upgrade(migrated_sessionmaker, fake, ids)
    with pytest.raises(MerchantChargeError) as excinfo:
        _upgrade(migrated_sessionmaker, fake, ids)
    assert excinfo.value.code == "charge_in_flight"
    assert fake.count("pay_with_token") == 1


def test_upgrade_refused_on_the_fallback_path(migrated_sessionmaker: sessionmaker[Session]) -> None:
    ids = _seed(migrated_sessionmaker)
    with pytest.raises(MerchantChargeError) as excinfo:
        _upgrade(migrated_sessionmaker, FakeMotoClient(), ids,
                 settings=paymob_settings(subscription_amount_updatable=False))
    assert excinfo.value.code == "upgrade_unavailable"


def test_teacher_upgrade_must_hold_the_seated_students(migrated_sessionmaker: sessionmaker[Session]) -> None:
    with migrated_sessionmaker.begin() as s:
        teacher = make_user(s, Role.teacher)
        small = make_tier(s, audience=PlanAudience.teacher, price_minor=30_000, included_seats=5)
        big_fewer_seats = make_tier(s, audience=PlanAudience.teacher, price_minor=50_000, included_seats=2)
        sub, _ = make_subscription(s, user=teacher, tier=small, period_start=START, period_end=END)
        make_saved_card(s, teacher.id)
        for day in range(3):
            make_seat(s, teacher_user_id=teacher.id, created_at=datetime(2026, 11, 2 + day, tzinfo=UTC))
        ids = {"sub": sub.id, "user": teacher.id, "plus": big_fewer_seats.id}
    with pytest.raises(MerchantChargeError) as excinfo:
        _upgrade(migrated_sessionmaker, FakeMotoClient(), ids)
    assert excinfo.value.code == "seats_exceed_new_tier"


def _paid_upgrade(sm: sessionmaker[Session], ids: dict[str, uuid.UUID]) -> uuid.UUID:
    with sm.begin() as s:
        return make_payment(
            s, payer_user_id=ids["user"], purpose=PaymentPurpose.upgrade_proration,
            amount_minor=5_000, status=PaymentStatus.paid, subscription_id=ids["sub"],
            plan_tier_id=ids["plus"], paid_at=NOW,
        ).id


def test_paid_upgrade_switches_tier_grants_prorated_allowance_and_puts_amount(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    ids = _seed(migrated_sessionmaker)
    payment_id = _paid_upgrade(migrated_sessionmaker, ids)
    fake = FakeMotoClient()
    for _ in range(2):  # a duplicate dispatch is a no-op
        with migrated_sessionmaker.begin() as s:
            on_upgrade_paid(s, s.get_one(Payment, payment_id), client=fake, settings=SETTINGS)
    with migrated_sessionmaker() as s:
        assert s.get_one(Subscription, ids["sub"]).plan_tier_id == ids["plus"]
        grants = s.scalars(
            sa.select(UsageGrant).where(
                UsageGrant.owner_user_id == ids["user"], UsageGrant.payment_id == payment_id
            )
        ).all()
        assert len(grants) == 1
        assert grants[0].kind is GrantKind.period_allowance
        assert grants[0].units == 1_000  # (3000 - 1000) x half the period
        assert grants[0].expires_at == END
        assert grants[0].visible is False
        assert grants[0].subscription_period_id == ids["period"]
        # Index R6: the PUT and paymob_amount_minor move together, in the handler's transaction.
        assert s.get_one(Subscription, ids["sub"]).paymob_amount_minor == 20_000
    assert fake.kwargs_of("update_subscription") == [{"subscription_id": 9001, "amount_cents": 20_000}]


def test_put_failure_keeps_the_local_switch(migrated_sessionmaker: sessionmaker[Session]) -> None:
    ids = _seed(migrated_sessionmaker)
    payment_id = _paid_upgrade(migrated_sessionmaker, ids)
    fake = FakeMotoClient(update_error=PaymobError("down"))
    with migrated_sessionmaker.begin() as s:
        on_upgrade_paid(s, s.get_one(Payment, payment_id), client=fake, settings=SETTINGS)
    with migrated_sessionmaker() as s:
        sub = s.get_one(Subscription, ids["sub"])
        assert sub.plan_tier_id == ids["plus"]
        assert sub.paymob_amount_minor == 10_000  # unchanged: Paymob still holds the old amount


def test_quote_matches_the_charge_and_writes_nothing(migrated_sessionmaker: sessionmaker[Session]) -> None:
    ids = _seed(migrated_sessionmaker, card=False)  # a quote needs no card
    fake = FakeMotoClient()
    with migrated_sessionmaker() as s:
        quote = MerchantChargeService(s, fake, SETTINGS).quote_upgrade(
            subscription_id=ids["sub"], actor_user_id=ids["user"], plan_tier_id=ids["plus"], now=NOW
        )
    assert (quote.amount_minor, quote.currency, quote.allowance_units, quote.period_end) == (
        5_000, "EGP", 1_000, END,
    )
    assert fake.calls == []
    with migrated_sessionmaker() as s:
        assert s.scalar(sa.select(sa.func.count()).select_from(Payment).where(
            Payment.purpose == PaymentPurpose.upgrade_proration)) == 0


def test_quote_refuses_like_the_charge(migrated_sessionmaker: sessionmaker[Session]) -> None:
    ids = _seed(migrated_sessionmaker)
    with migrated_sessionmaker() as s, pytest.raises(MerchantChargeError) as excinfo:
        MerchantChargeService(s, FakeMotoClient(), SETTINGS).quote_upgrade(
            subscription_id=ids["sub"], actor_user_id=ids["user"], plan_tier_id=ids["cheaper"], now=NOW
        )
    assert excinfo.value.code == "not_an_upgrade"


def test_upgrade_handler_is_registered_on_import() -> None:
    from lemely.db.billing_repo import paid_handler_for

    assert paid_handler_for(PaymentPurpose.upgrade_proration) is mcr.handle_upgrade_paid
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_merchant_charge_upgrade.py -v --no-cov`
Expected: FAIL with `ImportError: cannot import name 'on_upgrade_paid'`.

- [ ] **Step 3: Implement the upgrade**

In `lemely/db/merchant_charge_repo.py`, extend the imports:

```python
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from lemely.core.subscription_rules import subscription_amount_minor
from lemely.core.usage_pricing import prorate_minor, prorate_units
from lemely.db.billing_repo import register_paid_handler
from lemely.db.models.billing import (
    Payment,
    PaymentPurpose,
    PaymentStatus,
    PlanTier,
    SavedCard,
    Subscription,
    SubscriptionPeriod,
)
from lemely.db.models.enums import SubscriptionStatus
from lemely.db.models.team import TeacherMember, TeacherMemberKind, TeacherMemberStatus
from lemely.db.models.usage import GrantKind
from lemely.db.usage_ledger_repo import UsageLedger
```

Add these module-level helpers above `MerchantChargeService`:

```python
def full_amount_minor(subscription: Subscription, tier: PlanTier, *, seats: int | None = None) -> int:
    """Plan price plus extra seats (the seats that will exist at renewal unless given)."""
    if seats is None:
        seats = (
            subscription.extra_seats
            if subscription.pending_extra_seats is None
            else subscription.pending_extra_seats
        )
    return subscription_amount_minor(
        price_minor=tier.price_minor,
        extra_seats=seats,
        extra_seat_price_minor=tier.extra_seat_price_minor,
    )


def expected_renewal_amount_minor(
    subscription: Subscription, tier: PlanTier, settings: PaymobSettings
) -> int:
    """What Paymob should charge at the next renewal (index R6: Phase 05's
    ``next_renewal_amount`` returns this).

    With amounts updatable it is the full amount. On the fallback path Paymob cannot be
    moved, so the honest expectation is the amount it already holds (``paymob_amount_minor``);
    any seats beyond it are charged by ``billing.extra_seat_renewal_charge`` (Task 6).
    """
    if not settings.subscription_amount_updatable and subscription.paymob_amount_minor is not None:
        return subscription.paymob_amount_minor
    return full_amount_minor(subscription, tier)


def capacity_extra_seats(subscription: Subscription) -> int:
    """Extra seats usable now. A pending reduction caps new joins at the post-renewal count."""
    if subscription.pending_extra_seats is None:
        return subscription.extra_seats
    return min(subscription.extra_seats, subscription.pending_extra_seats)


def seated_count(session: Session, teacher_user_id: uuid.UUID) -> int:
    """Active plus leaving seats: the count the seat rule (spec §4.4) checks."""
    return int(
        session.scalar(
            sa.select(sa.func.count())
            .select_from(TeacherMember)
            .where(
                TeacherMember.teacher_user_id == teacher_user_id,
                TeacherMember.kind == TeacherMemberKind.student_seat,
                TeacherMember.status.in_((TeacherMemberStatus.active, TeacherMemberStatus.leaving)),
            )
        )
        or 0
    )


def _touch(subscription: Subscription) -> None:
    """Bump the optimistic-lock version Phase 05's webhooks compare against."""
    subscription.version = subscription.version + 1


def _lock_subscription(session: Session, subscription_id: uuid.UUID | None) -> Subscription | None:
    if subscription_id is None:
        return None
    return session.execute(
        sa.select(Subscription).where(Subscription.id == subscription_id).with_for_update()
    ).scalar_one_or_none()


def _current_period(session: Session, subscription: Subscription) -> SubscriptionPeriod | None:
    return session.scalars(
        sa.select(SubscriptionPeriod).where(
            SubscriptionPeriod.subscription_id == subscription.id,
            SubscriptionPeriod.period_start == subscription.current_period_start,
        )
    ).first()


def push_subscription_amount(
    session: Session,
    client: PaymobClient | None,
    settings: PaymobSettings | None,
    subscription: Subscription,
) -> bool:
    """Sync the Paymob renewal amount through Phase 05's one seam (index R6).

    ``SubscriptionService.sync_renewal_amount`` PUTs ``next_renewal_amount`` when it differs
    from ``paymob_amount_minor`` and stamps ``paymob_amount_minor`` in the caller's
    transaction. On the fallback path ``next_renewal_amount`` equals the stamp, so no PUT is
    made. A failure is logged and leaves the stamp unchanged; Phase 05's drift check repairs it.
    ``True`` when a PUT was made.
    """
    if client is None or settings is None:
        log.info("paymob_subscription_amount_push_skipped", subscription_id=str(subscription.id))
        return False
    from lemely.db.subscription_repo import SubscriptionService  # it imports this module

    try:
        return SubscriptionService(session, client, settings).sync_renewal_amount(subscription)
    except _AMBIGUOUS:
        log.warning(
            "paymob_subscription_amount_sync_failed",
            subscription_id=str(subscription.id),
            exc_info=True,
        )
        return False


def _payable_subscription(
    session: Session, subscription_id: uuid.UUID, actor_user_id: uuid.UUID, *, lock: bool = True
) -> Subscription:
    """The payer's active subscription (row-locked unless ``lock=False``) or a refusal.

    Not the payer reads as not found (IDOR).
    """
    if lock:
        sub = _lock_subscription(session, subscription_id)
    else:
        sub = session.get(Subscription, subscription_id)
    if sub is None or sub.payer_user_id != actor_user_id:
        raise MerchantChargeError("not_found", "Subscription not found.")
    if sub.status is not SubscriptionStatus.active:
        raise MerchantChargeError("subscription_not_active", "The subscription is not active.")
    return sub


def _refuse_if_in_flight(session: Session, subscription_id: uuid.UUID) -> None:
    busy = session.scalar(
        sa.select(Payment.id)
        .where(
            Payment.subscription_id == subscription_id,
            Payment.purpose.in_((PaymentPurpose.upgrade_proration, PaymentPurpose.extra_seats)),
            Payment.status.in_(IN_FLIGHT_STATUSES),
            Payment.dedupe_key.is_(None),
        )
        .limit(1)
    )
    if busy is not None:
        raise MerchantChargeError("charge_in_flight", "A charge for this subscription is in progress.")


@dataclass(frozen=True, slots=True)
class ChargeQuote:
    """A prorated charge as it would be made now (index R3 quote routes)."""

    amount_minor: int
    currency: str
    allowance_units: int | None  # upgrade: prorated allowance difference; seats: None
    period_end: datetime
```

Add these methods to `MerchantChargeService`:

```python
    def _plan_upgrade(
        self,
        *,
        subscription_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        plan_tier_id: uuid.UUID,
        now: datetime,
        lock: bool,
    ) -> tuple[Subscription, PlanTier, ChargeQuote]:
        """Validation and pricing shared by :meth:`upgrade` and :meth:`quote_upgrade`."""
        if not self.settings.subscription_amount_updatable:
            raise MerchantChargeError(
                "upgrade_unavailable", "Plan upgrades are not available for this subscription yet."
            )
        sub = _payable_subscription(self.session, subscription_id, actor_user_id, lock=lock)
        if sub.cancel_at_period_end or sub.pending_plan_tier_id is not None:
            raise MerchantChargeError("plan_change_pending", "A plan change is already scheduled.")
        old = self.session.get_one(PlanTier, sub.plan_tier_id)
        new = self.session.get(PlanTier, plan_tier_id)
        if new is None or not new.is_active:
            raise MerchantChargeError("tier_not_found", "Plan not found.")
        if (
            new.audience != old.audience
            or new.interval != old.interval
            or new.price_minor <= old.price_minor
        ):
            raise MerchantChargeError("not_an_upgrade", "Choose a higher plan with the same billing interval.")
        if new.included_seats is not None and (
            new.included_seats + capacity_extra_seats(sub) < seated_count(self.session, sub.user_id)
        ):
            raise MerchantChargeError("seats_exceed_new_tier", "The new plan has too few seats for your students.")
        amount = prorate_minor(
            new.price_minor - old.price_minor, sub.current_period_start, sub.current_period_end, now
        )
        if amount <= 0:
            raise MerchantChargeError("period_ending", "The current period is ending; change plan at renewal.")
        units = max(
            0,
            prorate_units(
                (new.allowance_units or 0) - (old.allowance_units or 0),
                sub.current_period_start,
                sub.current_period_end,
                now,
            ),
        )
        return sub, new, ChargeQuote(amount, new.currency, units, sub.current_period_end)

    def quote_upgrade(
        self,
        *,
        subscription_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        plan_tier_id: uuid.UUID,
        now: datetime,
    ) -> ChargeQuote:
        """The prorated upgrade price now. No lock, no card or in-flight check, no writes."""
        _sub, _new, quote = self._plan_upgrade(
            subscription_id=subscription_id,
            actor_user_id=actor_user_id,
            plan_tier_id=plan_tier_id,
            now=now,
            lock=False,
        )
        return quote

    def upgrade(
        self,
        *,
        subscription_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        plan_tier_id: uuid.UUID,
        now: datetime,
    ) -> Payment:
        """Charge the prorated price difference now (spec §5.3). The switch waits for the callback."""
        sub, new, quote = self._plan_upgrade(
            subscription_id=subscription_id,
            actor_user_id=actor_user_id,
            plan_tier_id=plan_tier_id,
            now=now,
            lock=True,
        )
        _refuse_if_in_flight(self.session, sub.id)
        card = self.active_card(sub.payer_user_id)
        if card is None:
            raise MerchantChargeError("no_saved_card", "Add a card before upgrading.")
        amount = quote.amount_minor
        payment = self._new_payment(
            purpose=PaymentPurpose.upgrade_proration,
            payer_user_id=sub.payer_user_id,
            beneficiary_user_id=sub.user_id,
            amount_minor=amount,
            currency=new.currency,
            subscription_id=sub.id,
            plan_tier_id=new.id,
        )
        self.charge_saved_card(payment, card)
        return payment
```

Add the handler, its configuration and its registration below the class:

```python
def on_upgrade_paid(
    session: Session,
    payment: Payment,
    *,
    client: PaymobClient | None,
    settings: PaymobSettings | None,
) -> None:
    """Verified upgrade payment: switch tier, grant the prorated allowance difference, PUT amount."""
    sub = _lock_subscription(session, payment.subscription_id)
    if sub is None or payment.plan_tier_id is None or sub.plan_tier_id == payment.plan_tier_id:
        return
    old = session.get_one(PlanTier, sub.plan_tier_id)
    new = session.get_one(PlanTier, payment.plan_tier_id)
    now = payment.paid_at or datetime.now(UTC)
    sub.plan_tier_id = new.id
    _touch(sub)
    if sub.current_period_end is not None and sub.current_period_end > now:
        units = prorate_units(
            (new.allowance_units or 0) - (old.allowance_units or 0),
            sub.current_period_start,
            sub.current_period_end,
            now,
        )
        if units > 0:
            period = _current_period(session, sub)
            UsageLedger(session).issue_grant(
                owner_user_id=sub.user_id,
                kind=GrantKind.period_allowance,
                units=units,
                idempotency_key=f"upgrade:{payment.id}",
                expires_at=sub.current_period_end,
                visible=False,
                effective_at=now,
                payment_id=payment.id,
                subscription_period_id=period.id if period is not None else None,
            )
    session.flush()
    push_subscription_amount(session, client, settings, sub)


#: Set by :func:`configure_merchant_charges` (``create_app``). Handlers registered on
#: import read them, because Phase 02's ``PaidHandler`` signature carries no client.
_CLIENT_FACTORY: Callable[[], PaymobClient] | None = None
_SETTINGS: PaymobSettings | None = None


def configure_merchant_charges(
    client_factory: Callable[[], PaymobClient], settings: PaymobSettings
) -> None:
    """Give the paid handlers their Paymob client and settings. Safe to call again."""
    global _CLIENT_FACTORY, _SETTINGS  # noqa: PLW0603 - process-wide wiring, set once per app
    _CLIENT_FACTORY = client_factory
    _SETTINGS = settings


def _configured() -> tuple[PaymobClient | None, PaymobSettings | None]:
    return (_CLIENT_FACTORY() if _CLIENT_FACTORY is not None else None), _SETTINGS


def handle_upgrade_paid(session: Session, payment: Payment, obj: Mapping[str, Any]) -> None:
    """Phase 02 ``PaidHandler`` for ``upgrade_proration``."""
    del obj
    client, settings = _configured()
    on_upgrade_paid(session, payment, client=client, settings=settings)
```

At the very end of the module, after `__all__`, register it. Phase 02 registers `credit_pack` the same way. The function object is the same one on every import, so registering again is a no-op, never Phase 02's `ValueError`:

```python
register_paid_handler(PaymentPurpose.upgrade_proration, handle_upgrade_paid)
```

Add these names to `__all__`: `"ChargeQuote"`, `"capacity_extra_seats"`, `"configure_merchant_charges"`, `"expected_renewal_amount_minor"`, `"full_amount_minor"`, `"handle_upgrade_paid"`, `"on_upgrade_paid"`, `"push_subscription_amount"`, `"seated_count"`.

- [ ] **Step 4: Configure the handlers in the app**

In `lemely/web/app.py`, inside `create_app()`, after the routers are included:

```python
    from lemely.db.merchant_charge_repo import configure_merchant_charges
    from lemely.web.deps_billing import get_paymob_client

    configure_merchant_charges(get_paymob_client, get_settings().paymob)
```

Importing `merchant_charge_repo` here also registers its paid handlers before any webhook can arrive. If `create_app` receives a `settings` argument, pass `settings.paymob` instead. The factory is called only when a handler runs, so building the app opens no Paymob connection.

- [ ] **Step 5: Make Phase 05's `next_renewal_amount` fallback-aware (the only Phase 05 edit, index R6)**

In `lemely/db/subscription_repo.py`, add this import at the top:

```python
from lemely.db.merchant_charge_repo import expected_renewal_amount_minor
```

`merchant_charge_repo` imports `subscription_repo` only inside `push_subscription_amount` (a function-local import), so there is no import-time cycle.

Replace the body of `SubscriptionService.next_renewal_amount`, as Phase 05's deviation 10 asks. It keeps its "pending tier, else current tier" choice and delegates the amount. Phase 05's `sync_renewal_amount`, period-end push, renewal mismatch check and drift check all read this method. On the fallback path none of them tries a PUT Paymob cannot honour, and with amounts updatable the result is the same as before:

```python
    def next_renewal_amount(self, subscription: Subscription) -> int:
        """What the next renewal should charge, pending changes included (fallback-aware)."""
        tier = self._session.get(
            PlanTier, subscription.pending_plan_tier_id or subscription.plan_tier_id
        )
        return expected_renewal_amount_minor(subscription, tier, self._settings)
```

Phase 05's `__init__` stores settings as `self._settings`. Change nothing else in Phase 05.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_merchant_charge_upgrade.py tests/test_merchant_charge_core.py tests/test_web_app.py $(grep -ln "next_renewal_amount\|sync_renewal_amount\|apply_period_end_changes\|check_drift" tests/test_subscription*.py) tests/architecture/ -v --no-cov`
Expected: PASS, including Phase 05's subscription tests (in-step amounts are unchanged).

- [ ] **Step 7: Commit**

```bash
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files
git commit -S -m "feat(billing): prorated plan upgrade via merchant-initiated charge" -- \
  lemely/db/merchant_charge_repo.py lemely/db/subscription_repo.py lemely/web/app.py \
  tests/test_merchant_charge_upgrade.py
```

---

### Task 5: Extra seats: add, schedule a reduction, the `extra_seats` paid handler, seat capacity

**Files:**
- Modify: `lemely/db/merchant_charge_repo.py`
- Modify: `lemely/db/teacher_team_repo.py` (`seat_capacity`)
- Create: `tests/test_merchant_charge_seats.py`

**Interfaces:**
- Consumes: Task 4 (`_payable_subscription`, `_refuse_if_in_flight`, `capacity_extra_seats`, `seated_count`, `full_amount_minor`, `push_subscription_amount`, `_touch`, `_lock_subscription`, `_configured`, `ChargeQuote`), Phase 03's `TeacherTeamService._capacity` and `seat_capacity`.
- Produces:
  - `MerchantChargeService.add_extra_seats(*, subscription_id, actor_user_id, seats: int, now) -> Payment` and `quote_extra_seats(...same args) -> ChargeQuote`.
  - `MerchantChargeService.schedule_seat_reduction(*, subscription_id, actor_user_id, extra_seats: int, now) -> Subscription`. It makes no PUT: Phase 05's `apply_period_end_changes` pushes `next_renewal_amount`.
  - `on_extra_seats_paid(session, payment, *, client, settings) -> None` and its registered `handle_extra_seats_paid`.
  - Constants `RENEWAL_SEAT_DEDUPE_PREFIX = "extra_seat_renewal:"` and `MAX_SEATS_PER_PURCHASE = 100`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_merchant_charge_seats.py`:

```python
"""Extra seats (spec §5.4): prorated add, reduction at renewal, refused below seated students."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

import lemely.db.merchant_charge_repo as mcr
from lemely.db.merchant_charge_repo import MerchantChargeError, MerchantChargeService, on_extra_seats_paid
from lemely.db.models.billing import Payment, PaymentPurpose, PaymentStatus, PlanAudience, Subscription
from lemely.db.models.enums import Role
from lemely.db.models.team import TeacherMember, TeacherMemberStatus
from lemely.db.teacher_team_repo import TeacherTeamService
from tests.fake_paymob_moto import FakeMotoClient
from tests.merchant_charge_seed import (
    make_payment,
    make_saved_card,
    make_seat,
    make_subscription,
    make_tier,
    make_user,
    paymob_settings,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker

START = datetime(2026, 11, 1, tzinfo=UTC)
END = datetime(2026, 12, 1, tzinfo=UTC)
NOW = datetime(2026, 11, 16, tzinfo=UTC)
SETTINGS = paymob_settings()


def _seed(sm: sessionmaker[Session], *, seats: int = 3, extra: int = 1) -> dict[str, uuid.UUID]:
    with sm.begin() as s:
        teacher = make_user(s, Role.teacher)
        tier = make_tier(s, audience=PlanAudience.teacher, price_minor=30_000,
                         included_seats=2, extra_seat_price_minor=2_000)
        sub, period = make_subscription(s, user=teacher, tier=tier, period_start=START,
                                        period_end=END, extra_seats=extra)
        make_saved_card(s, teacher.id)
        members = [
            make_seat(s, teacher_user_id=teacher.id, created_at=datetime(2026, 11, 2 + i, tzinfo=UTC)).id
            for i in range(seats)
        ]
        return {"teacher": teacher.id, "sub": sub.id, "period": period.id, "newest": members[-1]}


def _svc(s: Session, fake: FakeMotoClient) -> MerchantChargeService:
    return MerchantChargeService(s, fake, SETTINGS)


def test_add_extra_seats_charges_prorated_price(migrated_sessionmaker: sessionmaker[Session]) -> None:
    ids = _seed(migrated_sessionmaker)
    fake = FakeMotoClient()
    with migrated_sessionmaker() as s:
        payment = _svc(s, fake).add_extra_seats(
            subscription_id=ids["sub"], actor_user_id=ids["teacher"], seats=2, now=NOW
        )
        s.commit()
    with migrated_sessionmaker() as s:
        row = s.get_one(Payment, payment.id)
        assert row.purpose is PaymentPurpose.extra_seats
        assert row.amount_minor == 2_000  # 2 seats x 2000 x half the period
        assert row.seat_quantity == 2
        assert s.get_one(Subscription, ids["sub"]).extra_seats == 1  # unchanged until callback


@pytest.mark.parametrize("seats", [0, -1, 101])
def test_seat_count_must_be_sane(migrated_sessionmaker: sessionmaker[Session], seats: int) -> None:
    ids = _seed(migrated_sessionmaker)
    with migrated_sessionmaker() as s, pytest.raises(MerchantChargeError) as excinfo:
        _svc(s, FakeMotoClient()).add_extra_seats(
            subscription_id=ids["sub"], actor_user_id=ids["teacher"], seats=seats, now=NOW
        )
    assert excinfo.value.code == "invalid_seats"


def test_student_plan_has_no_seats(migrated_sessionmaker: sessionmaker[Session]) -> None:
    with migrated_sessionmaker.begin() as s:
        student = make_user(s, Role.student)
        sub, _ = make_subscription(s, user=student, tier=make_tier(s), period_start=START, period_end=END)
        make_saved_card(s, student.id)
        sub_id, user_id = sub.id, student.id
    with migrated_sessionmaker() as s, pytest.raises(MerchantChargeError) as excinfo:
        _svc(s, FakeMotoClient()).add_extra_seats(subscription_id=sub_id, actor_user_id=user_id, seats=1, now=NOW)
    assert excinfo.value.code == "not_a_teacher_plan"


@pytest.mark.parametrize(
    ("column", "value", "code"),
    [("pending_extra_seats", 0, "seat_reduction_pending"),
     ("extra_seat_grace_until", datetime(2026, 11, 18, tzinfo=UTC), "seat_charge_overdue")],
)
def test_add_refused_while_seats_are_changing(
    migrated_sessionmaker: sessionmaker[Session], column: str, value: object, code: str
) -> None:
    ids = _seed(migrated_sessionmaker)
    with migrated_sessionmaker.begin() as s:
        setattr(s.get_one(Subscription, ids["sub"]), column, value)
    with migrated_sessionmaker() as s, pytest.raises(MerchantChargeError) as excinfo:
        _svc(s, FakeMotoClient()).add_extra_seats(
            subscription_id=ids["sub"], actor_user_id=ids["teacher"], seats=1, now=NOW
        )
    assert excinfo.value.code == code


def test_paid_extra_seats_raise_the_count_and_put_amount(migrated_sessionmaker: sessionmaker[Session]) -> None:
    ids = _seed(migrated_sessionmaker)
    with migrated_sessionmaker.begin() as s:
        payment_id = make_payment(
            s, payer_user_id=ids["teacher"], purpose=PaymentPurpose.extra_seats, amount_minor=2_000,
            status=PaymentStatus.paid, subscription_id=ids["sub"], seat_quantity=2, paid_at=NOW,
        ).id
    fake = FakeMotoClient()
    with migrated_sessionmaker.begin() as s:
        on_extra_seats_paid(s, s.get_one(Payment, payment_id), client=fake, settings=SETTINGS)
    with migrated_sessionmaker() as s:
        sub = s.get_one(Subscription, ids["sub"])
        assert sub.extra_seats == 3
        assert sub.paymob_amount_minor == 36_000  # index R6: set with the PUT
    assert fake.kwargs_of("update_subscription") == [{"subscription_id": 9001, "amount_cents": 36_000}]


def test_paid_extra_seats_on_the_fallback_path_make_no_put(migrated_sessionmaker: sessionmaker[Session]) -> None:
    ids = _seed(migrated_sessionmaker)
    with migrated_sessionmaker.begin() as s:
        payment_id = make_payment(
            s, payer_user_id=ids["teacher"], purpose=PaymentPurpose.extra_seats, amount_minor=2_000,
            status=PaymentStatus.paid, subscription_id=ids["sub"], seat_quantity=2, paid_at=NOW,
        ).id
    fake = FakeMotoClient()
    with migrated_sessionmaker.begin() as s:
        on_extra_seats_paid(s, s.get_one(Payment, payment_id), client=fake,
                            settings=paymob_settings(subscription_amount_updatable=False))
    with migrated_sessionmaker() as s:
        sub = s.get_one(Subscription, ids["sub"])
        assert (sub.extra_seats, sub.paymob_amount_minor) == (3, 32_000)  # Paymob unchanged
    assert fake.calls == []


def test_seats_quote_writes_nothing(migrated_sessionmaker: sessionmaker[Session]) -> None:
    ids = _seed(migrated_sessionmaker)
    fake = FakeMotoClient()
    with migrated_sessionmaker() as s:
        quote = _svc(s, fake).quote_extra_seats(
            subscription_id=ids["sub"], actor_user_id=ids["teacher"], seats=2, now=NOW
        )
    assert (quote.amount_minor, quote.currency, quote.allowance_units, quote.period_end) == (
        2_000, "EGP", None, END,
    )
    assert fake.calls == []


def test_paid_renewal_seat_charge_only_clears_grace(migrated_sessionmaker: sessionmaker[Session]) -> None:
    ids = _seed(migrated_sessionmaker, extra=2)
    with migrated_sessionmaker.begin() as s:
        s.get_one(Subscription, ids["sub"]).extra_seat_grace_until = datetime(2026, 11, 19, tzinfo=UTC)
        payment_id = make_payment(
            s, payer_user_id=ids["teacher"], purpose=PaymentPurpose.extra_seats, amount_minor=4_000,
            status=PaymentStatus.paid, subscription_id=ids["sub"], seat_quantity=2, paid_at=NOW,
            dedupe_key=f"{mcr.RENEWAL_SEAT_DEDUPE_PREFIX}{ids['period']}:1",
        ).id
    fake = FakeMotoClient()
    with migrated_sessionmaker.begin() as s:
        on_extra_seats_paid(s, s.get_one(Payment, payment_id), client=fake, settings=SETTINGS)
    with migrated_sessionmaker() as s:
        sub = s.get_one(Subscription, ids["sub"])
        assert sub.extra_seats == 2
        assert sub.extra_seat_grace_until is None
    assert fake.calls == []


def test_reduction_refused_below_seated_students(migrated_sessionmaker: sessionmaker[Session]) -> None:
    ids = _seed(migrated_sessionmaker, seats=3, extra=1)  # 2 included + 1 extra, 3 seated
    fake = FakeMotoClient()
    with migrated_sessionmaker() as s, pytest.raises(MerchantChargeError) as excinfo:
        _svc(s, fake).schedule_seat_reduction(
            subscription_id=ids["sub"], actor_user_id=ids["teacher"], extra_seats=0, now=NOW
        )
    assert excinfo.value.code == "seats_in_use"
    with migrated_sessionmaker.begin() as s:
        s.get_one(TeacherMember, ids["newest"]).status = TeacherMemberStatus.removed
    with migrated_sessionmaker() as s:
        _svc(s, fake).schedule_seat_reduction(
            subscription_id=ids["sub"], actor_user_id=ids["teacher"], extra_seats=0, now=NOW
        )
        s.commit()
    with migrated_sessionmaker() as s:
        sub = s.get_one(Subscription, ids["sub"])
        assert sub.extra_seats == 1  # Phase 05 applies it at renewal
        assert sub.pending_extra_seats == 0
        assert TeacherTeamService(s).seat_capacity(ids["teacher"]) == 2  # no new joins past it
    # No PUT here: Phase 05's period-end job pushes next_renewal_amount (index R6).
    assert fake.calls == []


def test_fallback_reduction_below_the_paymob_amount_is_refused(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    ids = _seed(migrated_sessionmaker, seats=2, extra=1)  # Paymob holds 32_000 (price + 1 seat)
    with migrated_sessionmaker() as s, pytest.raises(MerchantChargeError) as excinfo:
        MerchantChargeService(
            s, FakeMotoClient(), paymob_settings(subscription_amount_updatable=False)
        ).schedule_seat_reduction(
            subscription_id=ids["sub"], actor_user_id=ids["teacher"], extra_seats=0, now=NOW
        )
    assert excinfo.value.code == "seat_reduction_unavailable"


def test_reduction_to_the_current_count_cancels_it(migrated_sessionmaker: sessionmaker[Session]) -> None:
    ids = _seed(migrated_sessionmaker, seats=1, extra=2)
    with migrated_sessionmaker.begin() as s:
        s.get_one(Subscription, ids["sub"]).pending_extra_seats = 0
    with migrated_sessionmaker() as s:
        _svc(s, FakeMotoClient()).schedule_seat_reduction(
            subscription_id=ids["sub"], actor_user_id=ids["teacher"], extra_seats=2, now=NOW
        )
        s.commit()
    with migrated_sessionmaker() as s:
        assert s.get_one(Subscription, ids["sub"]).pending_extra_seats is None


def test_reduction_cannot_add_seats(migrated_sessionmaker: sessionmaker[Session]) -> None:
    ids = _seed(migrated_sessionmaker)
    with migrated_sessionmaker() as s, pytest.raises(MerchantChargeError) as excinfo:
        _svc(s, FakeMotoClient()).schedule_seat_reduction(
            subscription_id=ids["sub"], actor_user_id=ids["teacher"], extra_seats=5, now=NOW
        )
    assert excinfo.value.code == "not_a_reduction"


def test_extra_seats_handler_is_registered_on_import() -> None:
    from lemely.db.billing_repo import paid_handler_for

    assert paid_handler_for(PaymentPurpose.extra_seats) is mcr.handle_extra_seats_paid
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_merchant_charge_seats.py -v --no-cov`
Expected: FAIL with `ImportError: cannot import name 'on_extra_seats_paid'`.

- [ ] **Step 3: Implement seats**

In `lemely/db/merchant_charge_repo.py`, add constants next to the others:

```python
#: ``payments.dedupe_key`` prefix of a fallback renewal seat charge (Task 6).
RENEWAL_SEAT_DEDUPE_PREFIX: Final = "extra_seat_renewal:"
#: Upper bound on one purchase; a typo should not charge for a thousand seats.
MAX_SEATS_PER_PURCHASE: Final = 100
```

Add a helper above the class:

```python
def _teacher_tier(session: Session, subscription: Subscription) -> PlanTier:
    tier = session.get_one(PlanTier, subscription.plan_tier_id)
    if tier.included_seats is None or tier.extra_seat_price_minor is None:
        raise MerchantChargeError("not_a_teacher_plan", "This plan has no student seats.")
    return tier
```

Add these methods to `MerchantChargeService`:

```python
    def _plan_extra_seats(
        self,
        *,
        subscription_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        seats: int,
        now: datetime,
        lock: bool,
    ) -> tuple[Subscription, ChargeQuote]:
        """Validation and pricing shared by :meth:`add_extra_seats` and :meth:`quote_extra_seats`."""
        if not 1 <= seats <= MAX_SEATS_PER_PURCHASE:
            raise MerchantChargeError("invalid_seats", f"Buy between 1 and {MAX_SEATS_PER_PURCHASE} seats.")
        sub = _payable_subscription(self.session, subscription_id, actor_user_id, lock=lock)
        tier = _teacher_tier(self.session, sub)
        if sub.pending_extra_seats is not None:
            raise MerchantChargeError("seat_reduction_pending", "Cancel the scheduled seat reduction first.")
        if sub.extra_seat_grace_until is not None:
            raise MerchantChargeError("seat_charge_overdue", "Your last seat payment failed.")
        amount = prorate_minor(
            seats * (tier.extra_seat_price_minor or 0),
            sub.current_period_start,
            sub.current_period_end,
            now,
        )
        if amount <= 0:
            raise MerchantChargeError("period_ending", "The current period is ending; add seats after renewal.")
        return sub, ChargeQuote(amount, tier.currency, None, sub.current_period_end)

    def quote_extra_seats(
        self, *, subscription_id: uuid.UUID, actor_user_id: uuid.UUID, seats: int, now: datetime
    ) -> ChargeQuote:
        """The prorated seat price now. No lock, no card or in-flight check, no writes."""
        _sub, quote = self._plan_extra_seats(
            subscription_id=subscription_id, actor_user_id=actor_user_id, seats=seats, now=now, lock=False
        )
        return quote

    def add_extra_seats(
        self, *, subscription_id: uuid.UUID, actor_user_id: uuid.UUID, seats: int, now: datetime
    ) -> Payment:
        """Charge ``seats × extra_seat_price_minor × remaining fraction`` now (spec §5.4)."""
        sub, quote = self._plan_extra_seats(
            subscription_id=subscription_id, actor_user_id=actor_user_id, seats=seats, now=now, lock=True
        )
        _refuse_if_in_flight(self.session, sub.id)
        card = self.active_card(sub.payer_user_id)
        if card is None:
            raise MerchantChargeError("no_saved_card", "Add a card before buying seats.")
        payment = self._new_payment(
            purpose=PaymentPurpose.extra_seats,
            payer_user_id=sub.payer_user_id,
            beneficiary_user_id=sub.user_id,
            amount_minor=quote.amount_minor,
            currency=quote.currency,
            subscription_id=sub.id,
            seat_quantity=seats,
        )
        self.charge_saved_card(payment, card)
        return payment

    def schedule_seat_reduction(
        self, *, subscription_id: uuid.UUID, actor_user_id: uuid.UUID, extra_seats: int, now: datetime
    ) -> Subscription:
        """Set ``pending_extra_seats``. Phase 05 applies it at renewal and its period-end job
        PUTs ``next_renewal_amount`` before then (index R6), so this makes no Paymob call.

        Asking for the current count cancels a pending reduction.
        """
        sub = _payable_subscription(self.session, subscription_id, actor_user_id)
        tier = _teacher_tier(self.session, sub)
        if not 0 <= extra_seats <= sub.extra_seats:
            raise MerchantChargeError("not_a_reduction", "Buy seats to add them; this only removes seats.")
        if extra_seats == sub.extra_seats:
            sub.pending_extra_seats = None
        else:
            if (tier.included_seats or 0) + extra_seats < seated_count(self.session, sub.user_id):
                raise MerchantChargeError("seats_in_use", "Free seats before removing them.")
            if (
                not self.settings.subscription_amount_updatable
                and sub.paymob_amount_minor is not None
                and full_amount_minor(sub, tier, seats=extra_seats) < sub.paymob_amount_minor
            ):
                # Paymob would keep charging the higher amount (use_transaction_amount=true).
                raise MerchantChargeError(
                    "seat_reduction_unavailable", "These seats cannot be removed on this plan yet."
                )
            sub.pending_extra_seats = extra_seats
        _touch(sub)
        self.session.flush()
        log.info("seat_reduction_scheduled", subscription_id=str(sub.id),
                 pending=sub.pending_extra_seats, at=now.isoformat())
        return sub
```

Add the handler below `on_upgrade_paid`:

```python
def on_extra_seats_paid(
    session: Session,
    payment: Payment,
    *,
    client: PaymobClient | None,
    settings: PaymobSettings | None,
) -> None:
    """Verified seat payment.

    A fallback renewal seat charge (``dedupe_key`` starts with
    :data:`RENEWAL_SEAT_DEDUPE_PREFIX`) only ends the grace: it pays for seats that already
    exist. A purchase raises ``extra_seats`` and PUTs the new renewal amount.
    """
    sub = _lock_subscription(session, payment.subscription_id)
    if sub is None:
        return
    if payment.dedupe_key is not None and payment.dedupe_key.startswith(RENEWAL_SEAT_DEDUPE_PREFIX):
        sub.extra_seat_grace_until = None
        session.flush()
        return
    sub.extra_seats = sub.extra_seats + (payment.seat_quantity or 0)
    _touch(sub)
    session.flush()
    push_subscription_amount(session, client, settings, sub)


def handle_extra_seats_paid(session: Session, payment: Payment, obj: Mapping[str, Any]) -> None:
    """Phase 02 ``PaidHandler`` for ``extra_seats``."""
    del obj
    client, settings = _configured()
    on_extra_seats_paid(session, payment, client=client, settings=settings)
```

At the end of the module, next to the upgrade registration, add:

```python
register_paid_handler(PaymentPurpose.extra_seats, handle_extra_seats_paid)
```

Add `"MAX_SEATS_PER_PURCHASE"`, `"RENEWAL_SEAT_DEDUPE_PREFIX"`, `"handle_extra_seats_paid"` and `"on_extra_seats_paid"` to `__all__`.

- [ ] **Step 4: Make `seat_capacity` honour a pending reduction**

In `lemely/db/teacher_team_repo.py`, Phase 03's `TeacherTeamService._capacity(teacher_user_id, *, lock)` backs both `seat_capacity` and the locked seat claim. It selects `Subscription.extra_seats, PlanTier.included_seats` and returns their sum. Make three edits. The rest of the statement (joins, `LIVE_PLAN_STATUSES`, `TEACHER_AUDIENCE`, ordering, the `with_for_update(of=Subscription)` branch) stays as it is.

1. Select the pending count too:

```python
            select(Subscription.extra_seats, Subscription.pending_extra_seats, PlanTier.included_seats)
```

2. Replace the unpacking and the return:

```python
        extra, pending, included = row
        usable_extra = int(extra or 0) if pending is None else min(int(extra or 0), int(pending))
        return int(included or 0) + usable_extra
```

3. Update the `seat_capacity` docstring to: `"""Return included seats plus usable extra seats (capped by a pending reduction), or 0."""`.

This is the same rule as `capacity_extra_seats` in `merchant_charge_repo` (used by `upgrade`). It is inlined here because `_capacity` reads columns, not a loaded `Subscription`, and `teacher_team_repo` then needs no import from this phase.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_merchant_charge_seats.py tests/test_merchant_charge_upgrade.py $(grep -ln seat_capacity tests/test_*.py) -v --no-cov`
Expected: PASS, including Phase 03's tests of `seat_capacity`.

- [ ] **Step 6: Commit**

```bash
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files
git commit -S -m "feat(billing): buy extra seats now and schedule seat reductions for renewal" -- \
  lemely/db/merchant_charge_repo.py lemely/db/teacher_team_repo.py tests/test_merchant_charge_seats.py
```

---

### Task 6: Fallback renewal seat charge, grace, `billing.extra_seat_renewal_charge`

**Files:**
- Modify: `lemely/db/merchant_charge_repo.py`
- Modify: `lemely/web/scheduled_notifications.py` (`Sweeper.billing_extra_seat_renewal` field and job)
- Modify: `lemely/web/deps_billing.py` (`get_extra_seat_renewal_job`), `lemely/web/deps.py` (`get_sweeper`)
- Create: `tests/test_merchant_charge_renewal_seats.py`

**Interfaces:**
- Consumes:
  - Tasks 3–5.
  - `enqueue_in_session` (`lemely/db/email_outbox_repo.py`) and `TeacherTeamService.request_removal`.
  - Phase 02's sweeper pattern (`Sweeper.billing_reconcile`, `deps_billing.get_billing_reconcile_job`).
  - Phase 05's renewal (`_grant_renewal_period` applies `pending_extra_seats`, sheds excess seats and inserts the new `SubscriptionPeriod`; this phase reads the result) and `SubscriptionService.next_renewal_amount`.
- Produces:
  - `queue_renewal_seat_charge(session, subscription, period, *, now) -> Payment | None`.
  - `run_extra_seat_renewal_job(sessionmaker, client, settings, *, now) -> int`.
  - Constants `SEAT_GRACE = timedelta(days=3)`, `SEAT_RETRY_INTERVAL = timedelta(days=1)` and `SEAT_MAX_ATTEMPTS = 3`.
  - `Sweeper.billing_extra_seat_renewal: Callable[[datetime], int] | None`, run as job `billing.extra_seat_renewal_charge`, and `deps_billing.get_extra_seat_renewal_job()`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_merchant_charge_renewal_seats.py`:

```python
"""Seats at renewal (spec §5.4): the fallback seat charge, its grace, then the drop.

Phase 05 applies ``pending_extra_seats`` at renewal (index R6); this phase only charges
the seats Paymob's renewal did not cover.
"""

from __future__ import annotations

import ast
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import sqlalchemy as sa

import lemely.web.scheduled_notifications as sn
from lemely.db.merchant_charge_repo import (
    RENEWAL_SEAT_DEDUPE_PREFIX,
    SEAT_GRACE,
    on_extra_seats_paid,
    queue_renewal_seat_charge,
    run_extra_seat_renewal_job,
)
from lemely.db.models.billing import Payment, PaymentPurpose, PaymentStatus, PlanAudience, Subscription, SubscriptionPeriod
from lemely.db.models.enums import Role
from lemely.db.models.team import TeacherMember, TeacherMemberStatus
from lemely.db.models.tutoring import EmailOutbox
from tests.fake_paymob_moto import FakeMotoClient
from tests.merchant_charge_seed import (
    make_payment,
    make_saved_card,
    make_seat,
    make_subscription,
    make_tier,
    make_user,
    paymob_settings,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker

START = datetime(2026, 11, 1, tzinfo=UTC)
END = datetime(2026, 12, 1, tzinfo=UTC)
NOW = datetime(2026, 11, 1, 0, 5, tzinfo=UTC)
FALLBACK = paymob_settings(subscription_amount_updatable=False)
UPDATABLE = paymob_settings()


def _seed(
    sm: sessionmaker[Session], *, extra: int = 2, seats: int = 0, paymob_amount: int | None = 30_000
) -> dict[str, uuid.UUID]:
    """Default: the fallback picture. Paymob renews at the plan price alone (30_000) while the
    teacher holds ``extra`` paid seats. ``paymob_amount=None`` seeds Paymob in step."""
    with sm.begin() as s:
        teacher = make_user(s, Role.teacher)
        tier = make_tier(s, audience=PlanAudience.teacher, price_minor=30_000,
                         included_seats=2, extra_seat_price_minor=2_000)
        sub, period = make_subscription(s, user=teacher, tier=tier, period_start=START, period_end=END,
                                        extra_seats=extra, paymob_amount_minor=paymob_amount)
        make_saved_card(s, teacher.id)
        for i in range(seats):
            make_seat(s, teacher_user_id=teacher.id, created_at=datetime(2026, 10, 1 + i, tzinfo=UTC))
        return {"teacher": teacher.id, "sub": sub.id, "period": period.id}


def _renew(sm: sessionmaker[Session], ids: dict[str, uuid.UUID]) -> uuid.UUID | None:
    """What the job calls once for a period that has no renewal-seat attempt yet."""
    with sm.begin() as s:
        payment = queue_renewal_seat_charge(
            s, s.get_one(Subscription, ids["sub"]), s.get_one(SubscriptionPeriod, ids["period"]), now=NOW
        )
        return payment.id if payment is not None else None


def _attempts(sm: sessionmaker[Session], ids: dict[str, uuid.UUID]) -> list[Payment]:
    with sm() as s:
        return list(s.scalars(
            sa.select(Payment)
            .where(Payment.dedupe_key.like(f"{RENEWAL_SEAT_DEDUPE_PREFIX}{ids['period']}:%"))
            .order_by(Payment.created_at, Payment.dedupe_key)
        ))


def test_uncovered_seats_queue_one_charge_per_period(migrated_sessionmaker: sessionmaker[Session]) -> None:
    ids = _seed(migrated_sessionmaker, extra=2)
    first = _renew(migrated_sessionmaker, ids)
    second = _renew(migrated_sessionmaker, ids)
    assert first is not None and second is None
    [attempt] = _attempts(migrated_sessionmaker, ids)
    assert attempt.amount_minor == 4_000  # 30_000 + 2 x 2_000 expected, Paymob charged 30_000
    assert attempt.seat_quantity == 2
    assert attempt.status is PaymentStatus.created
    assert attempt.dedupe_key == f"{RENEWAL_SEAT_DEDUPE_PREFIX}{ids['period']}:1"


def test_paymob_in_step_queues_nothing(migrated_sessionmaker: sessionmaker[Session]) -> None:
    ids = _seed(migrated_sessionmaker, extra=2, paymob_amount=None)  # Paymob holds 34_000
    assert _renew(migrated_sessionmaker, ids) is None


def test_no_charge_without_extra_seats(migrated_sessionmaker: sessionmaker[Session]) -> None:
    ids = _seed(migrated_sessionmaker, extra=0)
    assert _renew(migrated_sessionmaker, ids) is None


def test_job_with_nothing_queued_does_nothing(migrated_sessionmaker: sessionmaker[Session]) -> None:
    _seed(migrated_sessionmaker, extra=2, paymob_amount=None)
    fake = FakeMotoClient()
    assert run_extra_seat_renewal_job(migrated_sessionmaker, fake, UPDATABLE, now=NOW) == 0
    assert fake.calls == []


def test_job_charges_queued_seat_payment(migrated_sessionmaker: sessionmaker[Session]) -> None:
    ids = _seed(migrated_sessionmaker, extra=2)
    _renew(migrated_sessionmaker, ids)
    fake = FakeMotoClient()
    assert run_extra_seat_renewal_job(migrated_sessionmaker, fake, FALLBACK, now=NOW) == 1
    assert fake.count("pay_with_token") == 1
    assert _attempts(migrated_sessionmaker, ids)[0].status is PaymentStatus.pending


def test_failure_starts_grace_emails_and_retries_daily(migrated_sessionmaker: sessionmaker[Session]) -> None:
    ids = _seed(migrated_sessionmaker, extra=2)
    _renew(migrated_sessionmaker, ids)
    declines = FakeMotoClient(pay_result={"id": 1, "success": False, "pending": False})
    run_extra_seat_renewal_job(migrated_sessionmaker, declines, FALLBACK, now=NOW)  # charge -> failed
    run_extra_seat_renewal_job(migrated_sessionmaker, declines, FALLBACK, now=NOW)  # grace starts
    with migrated_sessionmaker() as s:
        sub = s.get_one(Subscription, ids["sub"])
        assert sub.extra_seat_grace_until == NOW + SEAT_GRACE
        first_id = _attempts(migrated_sessionmaker, ids)[0].id
        assert sub.extra_seat_grace_payment_id == first_id
        mails = s.scalars(sa.select(EmailOutbox).where(EmailOutbox.template == "extra_seats_charge_failed")).all()
        assert [m.recipient_user_id for m in mails] == [ids["teacher"]]
    for day in (1, 2, 3):
        run_extra_seat_renewal_job(migrated_sessionmaker, declines, FALLBACK, now=NOW + timedelta(days=day, minutes=1))
    assert len(_attempts(migrated_sessionmaker, ids)) == 3  # capped at SEAT_MAX_ATTEMPTS
    with migrated_sessionmaker() as s:
        mails = s.scalars(sa.select(EmailOutbox).where(EmailOutbox.template == "extra_seats_charge_failed")).all()
        assert len(mails) == 1


def test_paid_retry_ends_grace_and_keeps_seats(migrated_sessionmaker: sessionmaker[Session]) -> None:
    ids = _seed(migrated_sessionmaker, extra=2)
    _renew(migrated_sessionmaker, ids)
    declines = FakeMotoClient(pay_result={"id": 1, "success": False, "pending": False})
    run_extra_seat_renewal_job(migrated_sessionmaker, declines, FALLBACK, now=NOW)
    run_extra_seat_renewal_job(migrated_sessionmaker, declines, FALLBACK, now=NOW)
    run_extra_seat_renewal_job(migrated_sessionmaker, FakeMotoClient(), FALLBACK, now=NOW + timedelta(days=1, minutes=1))
    retry = _attempts(migrated_sessionmaker, ids)[1]
    with migrated_sessionmaker.begin() as s:  # the verified callback for the retry
        payment = s.get_one(Payment, retry.id)
        payment.status, payment.paid_at = PaymentStatus.paid, NOW + timedelta(days=1)
        on_extra_seats_paid(s, payment, client=FakeMotoClient(), settings=FALLBACK)
    run_extra_seat_renewal_job(migrated_sessionmaker, FakeMotoClient(), FALLBACK, now=NOW + timedelta(days=4))
    with migrated_sessionmaker() as s:
        sub = s.get_one(Subscription, ids["sub"])
        assert (sub.extra_seats, sub.extra_seat_grace_until) == (2, None)


def test_grace_elapsed_drops_seats_and_newest_students_leave(migrated_sessionmaker: sessionmaker[Session]) -> None:
    ids = _seed(migrated_sessionmaker, extra=2, seats=4)
    _renew(migrated_sessionmaker, ids)
    declines = FakeMotoClient(pay_result={"id": 1, "success": False, "pending": False})
    run_extra_seat_renewal_job(migrated_sessionmaker, declines, FALLBACK, now=NOW)
    run_extra_seat_renewal_job(migrated_sessionmaker, declines, FALLBACK, now=NOW)
    later = NOW + SEAT_GRACE + timedelta(minutes=1)
    run_extra_seat_renewal_job(migrated_sessionmaker, declines, FALLBACK, now=later)
    with migrated_sessionmaker() as s:
        sub = s.get_one(Subscription, ids["sub"])
        assert (sub.extra_seats, sub.pending_extra_seats, sub.extra_seat_grace_until) == (0, None, None)
        members = s.scalars(
            sa.select(TeacherMember).where(TeacherMember.teacher_user_id == ids["teacher"])
            .order_by(TeacherMember.created_at)
        ).all()
        assert [m.status for m in members] == [
            TeacherMemberStatus.active, TeacherMemberStatus.active,
            TeacherMemberStatus.leaving, TeacherMemberStatus.leaving,
        ]
    # The same failed period never starts a second grace.
    run_extra_seat_renewal_job(migrated_sessionmaker, declines, FALLBACK, now=later + timedelta(days=1))
    with migrated_sessionmaker() as s:
        assert s.get_one(Subscription, ids["sub"]).extra_seat_grace_until is None


def _calls_in(path: str, function: str) -> set[str]:
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == function:
            return {
                n.func.id if isinstance(n.func, ast.Name) else getattr(n.func, "attr", "")
                for n in ast.walk(node) if isinstance(n, ast.Call)
            }
    raise AssertionError(f"{function} not found in {path}")


def test_job_queues_and_charges_a_new_periods_shortfall(migrated_sessionmaker: sessionmaker[Session]) -> None:
    ids = _seed(migrated_sessionmaker, extra=2)  # nothing queued yet: Phase 05 just renewed
    fake = FakeMotoClient()
    assert run_extra_seat_renewal_job(migrated_sessionmaker, fake, FALLBACK, now=NOW) == 2  # queue + charge
    [attempt] = _attempts(migrated_sessionmaker, ids)
    assert (attempt.amount_minor, attempt.status) == (4_000, PaymentStatus.pending)
    assert run_extra_seat_renewal_job(migrated_sessionmaker, fake, FALLBACK, now=NOW) == 0
    assert fake.count("pay_with_token") == 1


def test_seats_bought_this_period_are_not_charged_again(migrated_sessionmaker: sessionmaker[Session]) -> None:
    ids = _seed(migrated_sessionmaker, extra=2)
    with migrated_sessionmaker.begin() as s:  # the 2 seats were bought (prorated) in this period
        make_payment(s, payer_user_id=ids["teacher"], purpose=PaymentPurpose.extra_seats,
                     amount_minor=2_000, status=PaymentStatus.paid, subscription_id=ids["sub"],
                     seat_quantity=2, paid_at=START + timedelta(days=3))
    assert _renew(migrated_sessionmaker, ids) is None


def test_phase05_is_untouched_outside_next_renewal_amount() -> None:
    """Index R6: this phase never applies pending seats or queues charges from Phase 05 code."""
    source = Path("lemely/db/subscription_repo.py").read_text(encoding="utf-8")
    assert "queue_renewal_seat_charge" not in source


def test_phase05_next_renewal_amount_is_fallback_aware() -> None:
    assert "expected_renewal_amount_minor" in _calls_in("lemely/db/subscription_repo.py", "next_renewal_amount")


def test_sweeper_runs_the_seat_job() -> None:
    sweeper = sn.Sweeper(
        sessionmaker=MagicMock(), announcements=MagicMock(), notifications=MagicMock(),
        transport=MagicMock(), settings=MagicMock(), now=lambda: NOW,
        billing_extra_seat_renewal=lambda now: 7,
    )
    assert sweeper.sweep_once()["billing.extra_seat_renewal_charge"] == 7
    bare = sn.Sweeper(
        sessionmaker=MagicMock(), announcements=MagicMock(), notifications=MagicMock(),
        transport=MagicMock(), settings=MagicMock(), now=lambda: NOW,
    )
    assert "billing.extra_seat_renewal_charge" not in bare.sweep_once()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_merchant_charge_renewal_seats.py -v --no-cov`
Expected: FAIL with `ImportError: cannot import name 'queue_renewal_seat_charge'`.

- [ ] **Step 3: Implement the renewal hook and the job**

In `lemely/db/merchant_charge_repo.py`, extend the imports:

```python
from datetime import UTC, datetime, timedelta

from sqlalchemy.dialects.postgresql import insert as pg_insert

from lemely.db.email_outbox_repo import enqueue_in_session
```

Under `if TYPE_CHECKING:`, add `from sqlalchemy.orm import sessionmaker`.

Add the constants:

```python
#: Fallback seat grace (spec §5.4: "the same 3-day grace" as a failed renewal).
SEAT_GRACE: Final = timedelta(days=3)
#: A new seat charge is tried at most once a day, only after the last one definitely failed.
SEAT_RETRY_INTERVAL: Final = timedelta(days=1)
SEAT_MAX_ATTEMPTS: Final = 3
_JOB_BATCH: Final = 50
```

Add the module functions below the handlers:

```python
def _insert_queued_payment(
    session: Session,
    *,
    purpose: PaymentPurpose,
    payer_user_id: uuid.UUID,
    beneficiary_user_id: uuid.UUID,
    amount_minor: int,
    currency: str,
    dedupe_key: str,
    subscription_id: uuid.UUID | None = None,
    credit_pack_id: uuid.UUID | None = None,
    seat_quantity: int | None = None,
) -> Payment | None:
    """Insert a ``created`` payment keyed by ``dedupe_key``; ``None`` if that key exists."""
    payment_id = uuid.uuid4()
    inserted = session.execute(
        pg_insert(Payment)
        .values(
            id=payment_id,
            purpose=purpose,
            payer_user_id=payer_user_id,
            beneficiary_user_id=beneficiary_user_id,
            amount_minor=amount_minor,
            currency=currency,
            status=PaymentStatus.created,
            special_reference=str(payment_id),
            subscription_id=subscription_id,
            credit_pack_id=credit_pack_id,
            seat_quantity=seat_quantity,
            dedupe_key=dedupe_key,
        )
        .on_conflict_do_nothing(index_elements=[Payment.dedupe_key])
        .returning(Payment.id)
    ).scalar_one_or_none()
    return None if inserted is None else session.get_one(Payment, inserted)


def _renewal_seat_key(period_id: uuid.UUID, attempt: int) -> str:
    return f"{RENEWAL_SEAT_DEDUPE_PREFIX}{period_id}:{attempt}"


def queue_renewal_seat_charge(
    session: Session,
    subscription: Subscription,
    period: SubscriptionPeriod,
    *,
    now: datetime,
) -> Payment | None:
    """Queue this period's charge for the seats Paymob's renewal did not cover.

    Called by ``billing.extra_seat_renewal_charge`` for a current period that has no
    renewal-seat attempt yet. Phase 05's renewal has already applied ``pending_extra_seats``
    (index R6; this phase never applies it). The amount is ``full amount −
    paymob_amount_minor``. While Paymob is in step it is 0 and nothing is queued. It is
    positive on the fallback path (Paymob cannot be moved) and after a failed PUT, which is
    exactly when the seats are otherwise unpaid. Seats bought during this period were
    prorated for it, so a purchase since ``period_start`` defers the charge to the next
    renewal.
    """
    if subscription.extra_seats == 0 or subscription.paymob_amount_minor is None:
        return None
    bought_this_period = session.scalar(
        sa.select(Payment.id)
        .where(
            Payment.subscription_id == subscription.id,
            Payment.purpose == PaymentPurpose.extra_seats,
            Payment.dedupe_key.is_(None),
            Payment.status.in_((*IN_FLIGHT_STATUSES, PaymentStatus.paid)),
            sa.func.coalesce(Payment.paid_at, Payment.created_at) >= period.period_start,
        )
        .limit(1)
    )
    if bought_this_period is not None:
        return None
    tier = session.get_one(PlanTier, subscription.plan_tier_id)
    shortfall = full_amount_minor(subscription, tier, seats=subscription.extra_seats) - (
        subscription.paymob_amount_minor
    )
    if shortfall <= 0:
        return None
    price = tier.extra_seat_price_minor or 0
    uncovered = shortfall // price if price and shortfall % price == 0 else None
    log.info("seat_renewal_charge_queued", subscription_id=str(subscription.id),
             amount_minor=shortfall, at=now.isoformat())
    return _insert_queued_payment(
        session,
        purpose=PaymentPurpose.extra_seats,
        payer_user_id=subscription.payer_user_id,
        beneficiary_user_id=subscription.user_id,
        amount_minor=shortfall,
        currency=tier.currency,
        dedupe_key=_renewal_seat_key(period.id, 1),
        subscription_id=subscription.id,
        seat_quantity=uncovered,
    )


def _charge_queued(
    sessionmaker: sessionmaker[Session],
    client: PaymobClient,
    settings: PaymobSettings,
    *,
    purpose: PaymentPurpose,
    dedupe_prefix: str,
    card_for: Callable[[Session, Payment], SavedCard | None],
) -> int:
    """Charge every queued ``created`` payment of ``purpose`` once; returns how many were handled."""
    with sessionmaker() as session:
        queued = list(
            session.scalars(
                sa.select(Payment.id)
                .where(
                    Payment.purpose == purpose,
                    Payment.status == PaymentStatus.created,
                    Payment.dedupe_key.like(f"{dedupe_prefix}%"),
                )
                .order_by(Payment.created_at, Payment.id)
                .limit(_JOB_BATCH)
            )
        )
    handled = 0
    for payment_id in queued:
        with sessionmaker() as session:
            payment = session.get(Payment, payment_id)
            if payment is None or payment.status is not PaymentStatus.created:
                continue
            card = card_for(session, payment)
            if card is None or card.user_id != payment.payer_user_id or not card.is_active:
                session.execute(
                    sa.update(Payment)
                    .where(Payment.id == payment_id, Payment.status == PaymentStatus.created)
                    .values(status=PaymentStatus.failed, updated_at=sa.func.now())
                )
                session.commit()
                handled += 1
                continue
            try:
                MerchantChargeService(session, client, settings).charge_saved_card(payment, card)
            except ChargeAlreadyAttempted:
                continue
            handled += 1
    return handled


def _start_or_retry_seat_grace(
    session: Session,
    sub: Subscription,
    period_id: uuid.UUID,
    attempts: list[Payment],
    *,
    now: datetime,
) -> int:
    """Start the grace on the first definite failure; queue at most one retry per day in it.

    Retry spacing is measured from the grace start (``grace_until - SEAT_GRACE``), a value
    this job wrote with its own clock, so the schedule never depends on DB ``now()``.
    """
    latest = attempts[-1]
    if latest.status not in FAILED_STATUSES:
        return 0
    first = attempts[0]
    if sub.extra_seat_grace_payment_id != first.id:
        sub.extra_seat_grace_until = now + SEAT_GRACE
        sub.extra_seat_grace_payment_id = first.id
        enqueue_in_session(
            session,
            recipient_user_id=sub.payer_user_id,
            template="extra_seats_charge_failed",
            context={"subscription_id": str(sub.id)},
            dedupe_key=f"extra_seats_failed:{first.id}",
        )
        return 1
    if (
        sub.extra_seat_grace_until is not None
        and sub.extra_seat_grace_until > now
        and len(attempts) < SEAT_MAX_ATTEMPTS
        and now >= sub.extra_seat_grace_until - SEAT_GRACE + len(attempts) * SEAT_RETRY_INTERVAL
    ):
        retry = _insert_queued_payment(
            session,
            purpose=PaymentPurpose.extra_seats,
            payer_user_id=first.payer_user_id,
            beneficiary_user_id=first.beneficiary_user_id,
            amount_minor=first.amount_minor,
            currency=first.currency,
            dedupe_key=_renewal_seat_key(period_id, len(attempts) + 1),
            subscription_id=sub.id,
            seat_quantity=first.seat_quantity,
        )
        return 0 if retry is None else 1
    return 0


def _drop_extra_seats(session: Session, sub: Subscription, *, now: datetime) -> None:
    """Grace elapsed: extra seats go to zero and the newest active students start leaving."""
    from lemely.db.teacher_team_repo import TeacherTeamService

    tier = session.get_one(PlanTier, sub.plan_tier_id)
    sub.extra_seats = 0
    sub.pending_extra_seats = None
    sub.extra_seat_grace_until = None
    _touch(sub)
    active = list(
        session.scalars(
            sa.select(TeacherMember)
            .where(
                TeacherMember.teacher_user_id == sub.user_id,
                TeacherMember.kind == TeacherMemberKind.student_seat,
                TeacherMember.status == TeacherMemberStatus.active,
            )
            .order_by(TeacherMember.created_at.desc(), TeacherMember.id.desc())
        )
    )
    excess = max(0, len(active) - (tier.included_seats or 0))
    team = TeacherTeamService(session)
    for member in active[:excess]:
        team.request_removal(member.id, now=now)
    session.flush()
    log.warning("extra_seats_dropped", subscription_id=str(sub.id), students_leaving=excess)


def run_extra_seat_renewal_job(
    sessionmaker: sessionmaker[Session],
    client: PaymobClient,
    settings: PaymobSettings,
    *,
    now: datetime,
) -> int:
    """Sweeper job ``billing.extra_seat_renewal_charge`` (spec §5.4 fallback).

    It acts only on renewal seat charges that :func:`queue_renewal_seat_charge` queued, so
    with Paymob in step it finds nothing and does nothing.
    """
    handled = 0
    with sessionmaker() as session:
        subs = list(
            session.scalars(
                sa.select(Subscription)
                .where(
                    Subscription.status.in_((SubscriptionStatus.active, SubscriptionStatus.past_due)),
                    sa.or_(Subscription.extra_seats > 0, Subscription.extra_seat_grace_until.is_not(None)),
                )
                .with_for_update(skip_locked=True)
            )
        )
        for sub in subs:
            if sub.extra_seat_grace_until is not None and sub.extra_seat_grace_until <= now:
                _drop_extra_seats(session, sub, now=now)
                handled += 1
                continue
            period = _current_period(session, sub)
            if period is None:
                continue
            attempts = list(
                session.scalars(
                    sa.select(Payment)
                    .where(Payment.dedupe_key.like(f"{RENEWAL_SEAT_DEDUPE_PREFIX}{period.id}:%"))
                    .order_by(Payment.created_at, Payment.dedupe_key)
                )
            )
            if not attempts:
                if queue_renewal_seat_charge(session, sub, period, now=now) is not None:
                    handled += 1
                continue
            handled += _start_or_retry_seat_grace(session, sub, period.id, attempts, now=now)
        session.commit()
    handled += _charge_queued(
        sessionmaker,
        client,
        settings,
        purpose=PaymentPurpose.extra_seats,
        dedupe_prefix=RENEWAL_SEAT_DEDUPE_PREFIX,
        card_for=lambda session, payment: MerchantChargeService(session, client, settings).active_card(
            payment.payer_user_id
        ),
    )
    return handled
```

Add `"SEAT_GRACE"`, `"SEAT_MAX_ATTEMPTS"`, `"SEAT_RETRY_INTERVAL"`, `"queue_renewal_seat_charge"` and `"run_extra_seat_renewal_job"` to `__all__`.

The test `test_job_charges_queued_seat_payment` expects a return of `1` from one queued payment, with no failures and no grace work. The step order above gives that: the scan finds an attempt that has not failed, and the charge step handles one payment. In `test_job_queues_and_charges_a_new_periods_shortfall`, the scan queues the charge (1) and the charge step sends it (1).

- [ ] **Step 4: No Phase 05 edit here**

Task 4 already replaced the body of `next_renewal_amount`, the only Phase 05 edit (index R6). Leave every other Phase 05 function as it is, including `_grant_renewal_period`, which applies `pending_extra_seats`. The fallback seat charge is queued by this phase's own job (Step 3). `test_phase05_is_untouched_outside_next_renewal_amount` and `test_phase05_next_renewal_amount_is_fallback_aware` pin both facts.

- [ ] **Step 5: Wire the sweeper job (Phase 02's pattern)**

In `lemely/web/deps_billing.py`, next to `get_billing_reconcile_job`, add:

```python
def get_extra_seat_renewal_job() -> Callable[[datetime], int] | None:
    """The ``billing.extra_seat_renewal_charge`` job, or ``None`` when Paymob is unconfigured."""
    settings = get_settings().paymob
    if not settings.checkout_configured:
        return None

    def job(now: datetime) -> int:
        return run_extra_seat_renewal_job(
            get_billing_sessionmaker(), get_paymob_client(), settings, now=now
        )

    return job
```

Import `run_extra_seat_renewal_job` from `lemely.db.merchant_charge_repo`, and add `"get_extra_seat_renewal_job"` to `__all__`.

In `lemely/web/scheduled_notifications.py`, add this field to `class Sweeper`, after Phase 02's `billing_reconcile`:

```python
    #: ``billing.extra_seat_renewal_charge`` (billing spec §5.4 fallback), given only when
    #: Paymob is configured, like ``billing_reconcile``.
    billing_extra_seat_renewal: Callable[[datetime], int] | None = None
```

In `Sweeper.sweep_once`, directly before `return run_jobs(jobs)`, add:

```python
        billing_extra_seat_renewal = self.billing_extra_seat_renewal
        if billing_extra_seat_renewal is not None:
            jobs.append(
                ("billing.extra_seat_renewal_charge", lambda: billing_extra_seat_renewal(moment))
            )
```

In `lemely/web/deps.py` `get_sweeper`, extend Phase 02's local import to `from lemely.web.deps_billing import get_billing_reconcile_job, get_extra_seat_renewal_job`, and add `billing_extra_seat_renewal=get_extra_seat_renewal_job(),` to the `Sweeper(...)` call.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_merchant_charge_renewal_seats.py tests/test_merchant_charge_seats.py tests/test_scheduled_notifications.py tests/test_billing_reconcile.py $(grep -ln "next_renewal_amount\|_grant_renewal_period\|apply_period_end_changes" tests/test_subscription*.py) -v --no-cov`
Expected: PASS, including Phase 05's subscription tests: in-step subscriptions behave exactly as before.

- [ ] **Step 7: Commit**

```bash
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files
git commit -S -m "feat(billing): charge uncovered extra seats after renewal, with grace and drop" -- \
  lemely/db/merchant_charge_repo.py lemely/web/deps_billing.py \
  lemely/web/deps.py lemely/web/scheduled_notifications.py tests/test_merchant_charge_renewal_seats.py
```

---

### Task 7: Post-settle hook and `maybe_enqueue_auto_topup`

**Files:**
- Modify: `lemely/db/merchant_charge_repo.py`
- Modify: `lemely/web/app.py` (register the hook)
- Create: `tests/test_usage_post_settle_hooks.py` (pins Phase 04's registry, which this phase relies on)
- Create: `tests/test_auto_topup_enqueue.py`

`lemely/web/usage.py` is **not** modified. Phase 04 Task 6 defines the registry under these exact names (`PostSettleHook`, `_POST_SETTLE_HOOKS`, `register_post_settle_hook`, `clear_post_settle_hooks`, `run_post_settle_hooks`), and `MeteredJob._finish` calls `run_post_settle_hooks(session, settled_job, list(self.ctx.chain), now)` right after `ledger.settle(...)`, in the settle's transaction.

**Interfaces:**
- Consumes:
  - Phase 04's `lemely.web.usage` registry: `register_post_settle_hook(hook)`, `clear_post_settle_hooks()`, `run_post_settle_hooks(session, job, payers, now)` and `_POST_SETTLE_HOOKS`.
  - `UsageLedger.available`, `UsageLedger.issue_grant` and `UsageLedger.adjust`; `Payer` and `GrantScope`.
  - `AutoTopupSettings`, `CreditPack` and `_insert_queued_payment` (Task 6).
- Produces: in `lemely.db.merchant_charge_repo`, `enqueue_auto_topup(session, owner_user_id, *, now) -> Payment | None`, `MerchantChargeService.maybe_enqueue_auto_topup(owner_user_id: UUID, now: datetime) -> Payment | None`, `auto_topup_post_settle_hook(session, job, payers, now) -> None` and `AUTO_TOPUP_DEDUPE_PREFIX = "auto_topup:"`.

- [ ] **Step 1: Write the registry pin tests**

These pin the contract this phase depends on. They pass as soon as they are written, against Phase 04's registry. Their job is to go red if Phase 04 ever drops the savepoint or moves the call away from the settle.

Create `tests/test_usage_post_settle_hooks.py`:

```python
"""Post-settle hooks (Phase 04 registry, consumed by phase 06): run after a settle, never undo it."""

from __future__ import annotations

import ast
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
import sqlalchemy as sa

from lemely.db.models import User
from lemely.db.models.enums import Role
from lemely.web import usage

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker

NOW = datetime(2026, 11, 10, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _isolated_registry() -> Iterator[None]:
    saved = list(usage._POST_SETTLE_HOOKS)
    usage.clear_post_settle_hooks()
    yield
    usage.clear_post_settle_hooks()
    usage._POST_SETTLE_HOOKS.extend(saved)


def test_register_is_idempotent() -> None:
    def hook(*_: Any) -> None:
        return None

    usage.register_post_settle_hook(hook)
    usage.register_post_settle_hook(hook)
    assert usage._POST_SETTLE_HOOKS == [hook]


def test_failing_hook_is_rolled_back_alone(migrated_sessionmaker: sessionmaker[Session]) -> None:
    kept, dropped = uuid.uuid4(), uuid.uuid4()

    def writes_then_fails(session: Session, *_: Any) -> None:
        session.add(User(id=dropped, email=f"{dropped}@example.com", role=Role.student))
        session.flush()
        raise RuntimeError("boom")

    seen: list[object] = []
    usage.register_post_settle_hook(writes_then_fails)
    usage.register_post_settle_hook(lambda _s, job, payers, now: seen.append((job, payers, now)))
    with migrated_sessionmaker() as session:
        session.add(User(id=kept, email=f"{kept}@example.com", role=Role.student))
        session.flush()
        usage.run_post_settle_hooks(session, "job", [], NOW)  # type: ignore[arg-type]
        session.commit()
    with migrated_sessionmaker() as session:
        ids = set(session.scalars(sa.select(User.id).where(User.id.in_([kept, dropped]))))
    assert ids == {kept}
    assert seen == [("job", [], NOW)]


def test_usage_meter_runs_hooks_right_after_settle() -> None:
    """Structural pin: every function in usage.py that settles a job also runs the hooks after it."""
    tree = ast.parse(Path("lemely/web/usage.py").read_text(encoding="utf-8"))
    settling = []
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute | ast.Name)]
        settle_lines = [c.lineno for c in calls if getattr(c.func, "attr", None) == "settle"]
        hook_lines = [c.lineno for c in calls if getattr(c.func, "id", getattr(c.func, "attr", None)) == "run_post_settle_hooks"]
        if settle_lines:
            settling.append(fn.name)
            assert hook_lines and min(hook_lines) > max(settle_lines), fn.name
    assert settling  # non-vacuity: the meter does settle somewhere
```

- [ ] **Step 2: Write the failing enqueue tests**

Create `tests/test_auto_topup_enqueue.py`:

```python
"""maybe_enqueue_auto_topup (spec §5.5 steps 1-2): threshold, cap, in-flight, one per crossing."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa

from lemely.core.usage_types import GrantScope, Payer
from lemely.db.merchant_charge_repo import auto_topup_post_settle_hook, enqueue_auto_topup
from lemely.db.models.billing import AutoTopupSettings, Payment, PaymentPurpose, PaymentStatus
from lemely.db.models.enums import Role
from lemely.db.models.usage import GrantKind
from lemely.db.usage_ledger_repo import UsageLedger
from tests.merchant_charge_seed import link_parent, make_credit_pack, make_payment, make_saved_card, make_user

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker

NOW = datetime(2026, 11, 10, tzinfo=UTC)


def _seed(sm: sessionmaker[Session], *, credits: int, threshold: int = 500, cap: int = 50_000,
          enabled: bool = True) -> dict[str, uuid.UUID]:
    with sm.begin() as s:
        parent = make_user(s, Role.parent)
        child = make_user(s, Role.student)
        link_parent(s, parent_id=parent.id, child_id=child.id)
        pack = make_credit_pack(s, units=1_000, price_minor=10_000)
        card = make_saved_card(s, parent.id)
        if credits:
            UsageLedger(s).issue_grant(
                owner_user_id=child.id, kind=GrantKind.credit_pack, units=credits,
                idempotency_key="seed", expires_at=None, visible=True,
            )
        s.add(AutoTopupSettings(
            beneficiary_user_id=child.id, payer_user_id=parent.id, enabled=enabled,
            threshold_units=threshold, credit_pack_id=pack.id, saved_card_id=card.id,
            monthly_cap_minor=cap,
        ))
        return {"parent": parent.id, "child": child.id, "pack": pack.id}


def _enqueue(sm: sessionmaker[Session], owner: uuid.UUID, now: datetime = NOW) -> uuid.UUID | None:
    with sm.begin() as s:
        payment = enqueue_auto_topup(s, owner, now=now)
        return payment.id if payment is not None else None


def _setting(sm: sessionmaker[Session], child: uuid.UUID) -> AutoTopupSettings:
    with sm() as s:
        return s.scalars(sa.select(AutoTopupSettings).where(AutoTopupSettings.beneficiary_user_id == child)).one()


def test_below_threshold_enqueues_one_payment_for_the_crossing(migrated_sessionmaker: sessionmaker[Session]) -> None:
    ids = _seed(migrated_sessionmaker, credits=100)
    first = _enqueue(migrated_sessionmaker, ids["child"])
    second = _enqueue(migrated_sessionmaker, ids["child"])
    assert first is not None and second is None
    with migrated_sessionmaker() as s:
        payment = s.get_one(Payment, first)
        assert payment.purpose is PaymentPurpose.auto_topup
        assert payment.status is PaymentStatus.created
        assert (payment.payer_user_id, payment.beneficiary_user_id) == (ids["parent"], ids["child"])
        assert payment.amount_minor == 10_000
        assert payment.credit_pack_id == ids["pack"]
        assert payment.dedupe_key == f"auto_topup:{ids['child']}:0"
    setting = _setting(migrated_sessionmaker, ids["child"])
    assert (setting.armed, setting.last_payment_id) == (False, first)


def test_at_or_above_threshold_does_nothing(migrated_sessionmaker: sessionmaker[Session]) -> None:
    ids = _seed(migrated_sessionmaker, credits=500)
    assert _enqueue(migrated_sessionmaker, ids["child"]) is None


def test_disabled_setting_does_nothing(migrated_sessionmaker: sessionmaker[Session]) -> None:
    ids = _seed(migrated_sessionmaker, credits=0, enabled=False)
    assert _enqueue(migrated_sessionmaker, ids["child"]) is None


def test_monthly_cap_counts_this_months_top_ups(migrated_sessionmaker: sessionmaker[Session]) -> None:
    ids = _seed(migrated_sessionmaker, credits=0, cap=15_000)
    with migrated_sessionmaker.begin() as s:
        make_payment(s, payer_user_id=ids["parent"], beneficiary_user_id=ids["child"],
                     purpose=PaymentPurpose.auto_topup, amount_minor=10_000, status=PaymentStatus.paid)
    assert _enqueue(migrated_sessionmaker, ids["child"]) is None  # 10000 + 10000 > 15000
    assert _setting(migrated_sessionmaker, ids["child"]).armed is True  # retried next month


def test_in_flight_top_up_blocks_another(migrated_sessionmaker: sessionmaker[Session]) -> None:
    ids = _seed(migrated_sessionmaker, credits=0)
    with migrated_sessionmaker.begin() as s:
        make_payment(s, payer_user_id=ids["parent"], beneficiary_user_id=ids["child"],
                     purpose=PaymentPurpose.auto_topup, amount_minor=10_000, status=PaymentStatus.pending)
    assert _enqueue(migrated_sessionmaker, ids["child"]) is None


def test_back_above_threshold_rearms_for_the_next_crossing(migrated_sessionmaker: sessionmaker[Session]) -> None:
    ids = _seed(migrated_sessionmaker, credits=100)
    first = _enqueue(migrated_sessionmaker, ids["child"])
    with migrated_sessionmaker.begin() as s:
        s.get_one(Payment, first).status = PaymentStatus.paid
        UsageLedger(s).issue_grant(owner_user_id=ids["child"], kind=GrantKind.auto_topup, units=1_000,
                                   idempotency_key="topup", expires_at=None, visible=True)
    assert _enqueue(migrated_sessionmaker, ids["child"]) is None  # 1100 >= 500: re-arm only
    setting = _setting(migrated_sessionmaker, ids["child"])
    assert (setting.armed, setting.crossing_seq) == (True, 1)
    with migrated_sessionmaker.begin() as s:
        UsageLedger(s).adjust(owner_user_id=ids["child"], units=-900, reason="spend",
                              idempotency_key="spend", now=NOW)
    second = _enqueue(migrated_sessionmaker, ids["child"])
    with migrated_sessionmaker() as s:
        assert s.get_one(Payment, second).dedupe_key == f"auto_topup:{ids['child']}:1"


def test_post_settle_hook_checks_each_credits_owner_once(migrated_sessionmaker: sessionmaker[Session]) -> None:
    ids = _seed(migrated_sessionmaker, credits=0)
    payers = [
        Payer(owner_user_id=ids["child"], scope=GrantScope.ALLOWANCE),
        Payer(owner_user_id=ids["child"], scope=GrantScope.CREDITS),
    ]
    with migrated_sessionmaker.begin() as s:
        auto_topup_post_settle_hook(s, object(), payers, NOW)  # type: ignore[arg-type]
    with migrated_sessionmaker() as s:
        assert s.scalar(sa.select(sa.func.count()).select_from(Payment).where(
            Payment.purpose == PaymentPurpose.auto_topup)) == 1


def test_post_settle_hook_ignores_allowance_only_chains(migrated_sessionmaker: sessionmaker[Session]) -> None:
    ids = _seed(migrated_sessionmaker, credits=0)
    with migrated_sessionmaker.begin() as s:
        auto_topup_post_settle_hook(
            s, object(), [Payer(owner_user_id=ids["child"], scope=GrantScope.ALLOWANCE)], NOW  # type: ignore[arg-type]
        )
    with migrated_sessionmaker() as s:
        assert s.scalar(sa.select(sa.func.count()).select_from(Payment).where(
            Payment.purpose == PaymentPurpose.auto_topup)) == 0
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_usage_post_settle_hooks.py tests/test_auto_topup_enqueue.py -v --no-cov`
Expected: `tests/test_usage_post_settle_hooks.py` PASSES (Phase 04's registry is merged). `tests/test_auto_topup_enqueue.py` FAILS with `ImportError: cannot import name 'enqueue_auto_topup'`. If the registry pins fail, Phase 04's registry differs from its plan: stop and report it. Do not add a second registry here.

- [ ] **Step 4: Implement the enqueue**

In `lemely/db/merchant_charge_repo.py`, extend the imports:

```python
from collections.abc import Callable, Mapping, Sequence

from lemely.core.usage_types import GrantScope, Payer
from lemely.db.models.billing import AutoTopupSettings, CreditPack
```

`AutoTopupSettings` and `CreditPack` join the existing billing import. Under `TYPE_CHECKING`, add `from lemely.db.models.usage import UsageJob`.

Add the constant:

```python
AUTO_TOPUP_DEDUPE_PREFIX: Final = "auto_topup:"
```

Add the functions:

```python
def _month_start(now: datetime) -> datetime:
    return now.astimezone(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def enqueue_auto_topup(session: Session, owner_user_id: uuid.UUID, *, now: datetime) -> Payment | None:
    """Spec §5.5 steps 1-2. Queues at most one top-up per threshold crossing.

    Runs in the caller's transaction (the settle's, via the post-settle hook) and locks
    the setting row so two concurrent settles cannot both enqueue.
    """
    setting = session.execute(
        sa.select(AutoTopupSettings)
        .where(AutoTopupSettings.beneficiary_user_id == owner_user_id)
        .with_for_update()
    ).scalar_one_or_none()
    if setting is None or not setting.enabled or setting.saved_card_id is None:
        return None
    credits = UsageLedger(session).available(
        [Payer(owner_user_id=owner_user_id, scope=GrantScope.CREDITS)], now=now
    )
    if credits >= setting.threshold_units:
        if not setting.armed:
            setting.armed = True
            setting.crossing_seq = setting.crossing_seq + 1
            session.flush()
        return None
    if not setting.armed:
        return None
    pack = session.get(CreditPack, setting.credit_pack_id)
    if pack is None or not pack.is_active:
        log.warning("auto_topup_pack_inactive", beneficiary=str(owner_user_id))
        return None
    in_flight = session.scalar(
        sa.select(Payment.id)
        .where(
            Payment.beneficiary_user_id == owner_user_id,
            Payment.purpose == PaymentPurpose.auto_topup,
            Payment.status.in_(IN_FLIGHT_STATUSES),
        )
        .limit(1)
    )
    if in_flight is not None:
        return None
    spent = int(
        session.scalar(
            sa.select(sa.func.coalesce(sa.func.sum(Payment.amount_minor), 0)).where(
                Payment.beneficiary_user_id == owner_user_id,
                Payment.purpose == PaymentPurpose.auto_topup,
                Payment.status.in_((*IN_FLIGHT_STATUSES, PaymentStatus.paid)),
                Payment.created_at >= _month_start(now),
            )
        )
        or 0
    )
    if spent + pack.price_minor > setting.monthly_cap_minor:
        return None
    payment = _insert_queued_payment(
        session,
        purpose=PaymentPurpose.auto_topup,
        payer_user_id=setting.payer_user_id,
        beneficiary_user_id=owner_user_id,
        amount_minor=pack.price_minor,
        currency=pack.currency,
        dedupe_key=f"{AUTO_TOPUP_DEDUPE_PREFIX}{owner_user_id}:{setting.crossing_seq}",
        credit_pack_id=pack.id,
    )
    if payment is None:
        return None
    setting.armed = False
    setting.last_payment_id = payment.id
    session.flush()
    return payment


def auto_topup_post_settle_hook(
    session: Session, job: UsageJob, payers: Sequence[Payer], now: datetime
) -> None:
    """Post-settle hook: check auto top-up for every owner whose credits the chain could draw."""
    owners = dict.fromkeys(p.owner_user_id for p in payers if p.scope is GrantScope.CREDITS)
    for owner in owners:
        enqueue_auto_topup(session, owner, now=now)
```

Add a method to `MerchantChargeService`:

```python
    def maybe_enqueue_auto_topup(self, owner_user_id: uuid.UUID, now: datetime) -> Payment | None:
        """Index contract name for :func:`enqueue_auto_topup`."""
        return enqueue_auto_topup(self.session, owner_user_id, now=now)
```

Add `"AUTO_TOPUP_DEDUPE_PREFIX"`, `"auto_topup_post_settle_hook"` and `"enqueue_auto_topup"` to `__all__`.

- [ ] **Step 5: Register the hook at startup**

In `lemely/web/app.py` `create_app()`, next to `configure_merchant_charges(...)`:

```python
    from lemely.db.merchant_charge_repo import auto_topup_post_settle_hook
    from lemely.web.usage import register_post_settle_hook

    register_post_settle_hook(auto_topup_post_settle_hook)
```

Registration is idempotent (`register_post_settle_hook` skips a hook it already holds), so building many apps in tests is safe.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_usage_post_settle_hooks.py tests/test_auto_topup_enqueue.py $(grep -ln "UsageMeter\|MeteredJob" tests/test_*.py) tests/architecture/ -v --no-cov`
Expected: PASS, including Phase 04's meter tests.

- [ ] **Step 7: Commit**

```bash
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files
git commit -S -m "feat(billing): enqueue auto top-up after each settle via the post-settle hook" -- \
  lemely/db/merchant_charge_repo.py lemely/web/app.py \
  tests/test_usage_post_settle_hooks.py tests/test_auto_topup_enqueue.py
```

---

### Task 8: `billing.auto_topup` job, the `auto_topup` paid handler, failure handling

**Files:**
- Modify: `lemely/db/merchant_charge_repo.py`
- Modify: `lemely/web/scheduled_notifications.py` (`Sweeper.billing_auto_topup` field and job)
- Modify: `lemely/web/deps_billing.py` (`get_auto_topup_job`), `lemely/web/deps.py` (`get_sweeper`)
- Create: `tests/test_auto_topup_job.py`

**Interfaces:**
- Consumes:
  - `_charge_queued` (Task 6), `AUTO_TOPUP_DEDUPE_PREFIX` (Task 7) and `enqueue_in_session`.
  - `UsageLedger.issue_grant` and `GrantKind.auto_topup`.
  - Phase 02: `add_months`, `CREDIT_EXPIRY_MONTHS` and `register_paid_handler`.
- Produces:
  - `on_auto_topup_paid(session, payment) -> None` and `run_auto_topup_job(sessionmaker, client, settings, *, now) -> int`.
  - `handle_auto_topup_paid`, registered on import for `PaymentPurpose.auto_topup`.
  - `Sweeper.billing_auto_topup: Callable[[datetime], int] | None`, run as job `billing.auto_topup`, and `deps_billing.get_auto_topup_job()`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_auto_topup_job.py`:

```python
"""Auto top-up (spec §5.5 steps 3-5): charge from the sweeper, grant on callback, disable on failure."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import sqlalchemy as sa

import lemely.db.merchant_charge_repo as mcr
import lemely.web.scheduled_notifications as sn
from lemely.db.merchant_charge_repo import enqueue_auto_topup, on_auto_topup_paid, run_auto_topup_job
from lemely.db.models.billing import AutoTopupSettings, Payment, PaymentPurpose, PaymentStatus, SavedCard
from lemely.db.models.enums import Role
from lemely.db.models.tutoring import EmailOutbox
from lemely.db.models.usage import GrantKind, UsageGrant
from tests.fake_paymob_moto import FakeMotoClient
from tests.merchant_charge_seed import link_parent, make_credit_pack, make_payment, make_saved_card, make_user, paymob_settings

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker

NOW = datetime(2026, 11, 10, tzinfo=UTC)
SETTINGS = paymob_settings()


def _seed_queued(sm: sessionmaker[Session]) -> dict[str, uuid.UUID]:
    with sm.begin() as s:
        parent = make_user(s, Role.parent)
        child = make_user(s, Role.student)
        link_parent(s, parent_id=parent.id, child_id=child.id)
        pack = make_credit_pack(s, units=1_000, price_minor=10_000)
        card = make_saved_card(s, parent.id, token="tok_parent")
        s.add(AutoTopupSettings(
            beneficiary_user_id=child.id, payer_user_id=parent.id, enabled=True,
            threshold_units=500, credit_pack_id=pack.id, saved_card_id=card.id, monthly_cap_minor=50_000,
        ))
        s.flush()
        payment = enqueue_auto_topup(s, child.id, now=NOW)
        assert payment is not None
        return {"parent": parent.id, "child": child.id, "card": card.id, "payment": payment.id, "pack": pack.id}


def _setting(sm: sessionmaker[Session], child: uuid.UUID) -> AutoTopupSettings:
    with sm() as s:
        return s.scalars(sa.select(AutoTopupSettings).where(AutoTopupSettings.beneficiary_user_id == child)).one()


def _mails(sm: sessionmaker[Session]) -> list[EmailOutbox]:
    with sm() as s:
        return list(s.scalars(sa.select(EmailOutbox).where(EmailOutbox.template == "auto_topup_failed")))


def test_job_charges_the_payers_card(migrated_sessionmaker: sessionmaker[Session]) -> None:
    ids = _seed_queued(migrated_sessionmaker)
    fake = FakeMotoClient()
    assert run_auto_topup_job(migrated_sessionmaker, fake, SETTINGS, now=NOW) == 1
    assert fake.kwargs_of("pay_with_token")[0]["card_token"] == "tok_parent"
    with migrated_sessionmaker() as s:
        assert s.get_one(Payment, ids["payment"]).status is PaymentStatus.pending
    assert run_auto_topup_job(migrated_sessionmaker, fake, SETTINGS, now=NOW) == 0  # nothing new
    assert fake.count("pay_with_token") == 1


def test_declined_top_up_disables_and_emails_the_payer_once(migrated_sessionmaker: sessionmaker[Session]) -> None:
    ids = _seed_queued(migrated_sessionmaker)
    fake = FakeMotoClient(pay_result={"id": 1, "success": False, "pending": False})
    run_auto_topup_job(migrated_sessionmaker, fake, SETTINGS, now=NOW)
    run_auto_topup_job(migrated_sessionmaker, fake, SETTINGS, now=NOW)
    setting = _setting(migrated_sessionmaker, ids["child"])
    assert (setting.enabled, setting.disabled_reason) == (False, "payment_failed")
    mails = _mails(migrated_sessionmaker)
    assert [(m.recipient_user_id, m.context) for m in mails] == [
        (ids["parent"], {"payment_id": str(ids["payment"])})
    ]


def test_deactivated_card_fails_without_calling_paymob(migrated_sessionmaker: sessionmaker[Session]) -> None:
    ids = _seed_queued(migrated_sessionmaker)
    with migrated_sessionmaker.begin() as s:
        s.get_one(SavedCard, ids["card"]).is_active = False
    fake = FakeMotoClient()
    run_auto_topup_job(migrated_sessionmaker, fake, SETTINGS, now=NOW)
    assert fake.calls == []
    with migrated_sessionmaker() as s:
        assert s.get_one(Payment, ids["payment"]).status is PaymentStatus.failed
    assert _setting(migrated_sessionmaker, ids["child"]).enabled is False


def test_failure_of_an_older_top_up_is_ignored(migrated_sessionmaker: sessionmaker[Session]) -> None:
    ids = _seed_queued(migrated_sessionmaker)
    with migrated_sessionmaker.begin() as s:
        make_payment(s, payer_user_id=ids["parent"], beneficiary_user_id=ids["child"],
                     purpose=PaymentPurpose.auto_topup, amount_minor=10_000, status=PaymentStatus.failed)
    run_auto_topup_job(migrated_sessionmaker, FakeMotoClient(), SETTINGS, now=NOW)
    assert _setting(migrated_sessionmaker, ids["child"]).enabled is True
    assert _mails(migrated_sessionmaker) == []


def test_paid_top_up_grants_visible_credits_for_a_year_and_rearms(migrated_sessionmaker: sessionmaker[Session]) -> None:
    ids = _seed_queued(migrated_sessionmaker)
    with migrated_sessionmaker.begin() as s:
        payment = s.get_one(Payment, ids["payment"])
        payment.status, payment.paid_at = PaymentStatus.paid, NOW
        on_auto_topup_paid(s, payment)
        on_auto_topup_paid(s, payment)  # duplicate dispatch: issue_grant is idempotent
    with migrated_sessionmaker() as s:
        grants = s.scalars(sa.select(UsageGrant).where(UsageGrant.payment_id == ids["payment"])).all()
        assert len(grants) == 1
        grant = grants[0]
        assert grant.owner_user_id == ids["child"]
        assert grant.kind is GrantKind.auto_topup
        assert grant.units == 1_000
        assert grant.visible is True
        assert grant.expires_at == datetime(2027, 11, 10, tzinfo=UTC)
    setting = _setting(migrated_sessionmaker, ids["child"])
    assert (setting.armed, setting.crossing_seq) == (True, 1)


def test_all_three_handlers_are_registered_on_import() -> None:
    from lemely.db.billing_repo import paid_handler_for

    assert paid_handler_for(PaymentPurpose.upgrade_proration) is mcr.handle_upgrade_paid
    assert paid_handler_for(PaymentPurpose.extra_seats) is mcr.handle_extra_seats_paid
    assert paid_handler_for(PaymentPurpose.auto_topup) is mcr.handle_auto_topup_paid


def test_sweeper_runs_the_auto_topup_job() -> None:
    sweeper = sn.Sweeper(
        sessionmaker=MagicMock(), announcements=MagicMock(), notifications=MagicMock(),
        transport=MagicMock(), settings=MagicMock(), now=lambda: NOW,
        billing_auto_topup=lambda now: 3,
    )
    assert sweeper.sweep_once()["billing.auto_topup"] == 3
```

Debt repayment on this grant belongs to `UsageLedger.issue_grant` (spec §5.8), and Phase 01's tests cover it. This handler's part is to grant through `issue_grant`, which `test_paid_top_up_grants_visible_credits_for_a_year_and_rearms` checks via the stored grant.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_auto_topup_job.py -v --no-cov`
Expected: FAIL with `ImportError: cannot import name 'on_auto_topup_paid'`.

- [ ] **Step 3: Implement the handler, the job and the registration**

In `lemely/db/merchant_charge_repo.py`, add:

Extend the `lemely.db.billing_repo` import with `CREDIT_EXPIRY_MONTHS` and `add_months`, the same expiry rule Phase 02's credit-pack grant uses. Then add:

```python
def on_auto_topup_paid(session: Session, payment: Payment) -> None:
    """Verified top-up: a visible 12-month grant for the beneficiary (debt repaid first by
    ``issue_grant``), then re-arm the setting for the next crossing."""
    if payment.credit_pack_id is None:
        return
    pack = session.get_one(CreditPack, payment.credit_pack_id)
    paid_at = payment.paid_at or datetime.now(UTC)
    UsageLedger(session).issue_grant(
        owner_user_id=payment.beneficiary_user_id,
        kind=GrantKind.auto_topup,
        units=pack.units,
        idempotency_key=f"auto_topup:{payment.id}",
        expires_at=add_months(paid_at, CREDIT_EXPIRY_MONTHS),
        visible=True,
        effective_at=paid_at,
        payment_id=payment.id,
    )
    setting = session.execute(
        sa.select(AutoTopupSettings)
        .where(AutoTopupSettings.beneficiary_user_id == payment.beneficiary_user_id)
        .with_for_update()
    ).scalar_one_or_none()
    if setting is not None and setting.last_payment_id == payment.id and not setting.armed:
        setting.armed = True
        setting.crossing_seq = setting.crossing_seq + 1
    session.flush()


def _disable_failed_auto_topups(session: Session) -> int:
    """Spec §5.5 step 5: the latest top-up failed, so turn auto top-up off and email the payer."""
    rows = session.execute(
        sa.select(AutoTopupSettings, Payment)
        .join(Payment, Payment.id == AutoTopupSettings.last_payment_id)
        .where(AutoTopupSettings.enabled.is_(True), Payment.status.in_(FAILED_STATUSES))
        .with_for_update(of=AutoTopupSettings, skip_locked=True)
    ).all()
    for setting, payment in rows:
        setting.enabled = False
        setting.disabled_reason = "payment_failed"
        setting.armed = True
        setting.crossing_seq = setting.crossing_seq + 1
        enqueue_in_session(
            session,
            recipient_user_id=setting.payer_user_id,
            template="auto_topup_failed",
            context={"payment_id": str(payment.id)},
            dedupe_key=f"auto_topup_failed:{payment.id}",
        )
        log.warning("auto_topup_disabled", beneficiary=str(setting.beneficiary_user_id))
    return len(rows)


def _auto_topup_card(session: Session, payment: Payment) -> SavedCard | None:
    setting = session.scalars(
        sa.select(AutoTopupSettings).where(
            AutoTopupSettings.beneficiary_user_id == payment.beneficiary_user_id
        )
    ).first()
    if setting is None or not setting.enabled or setting.saved_card_id is None:
        return None
    return session.get(SavedCard, setting.saved_card_id)


def run_auto_topup_job(
    sessionmaker: sessionmaker[Session],
    client: PaymobClient,
    settings: PaymobSettings,
    *,
    now: datetime,
) -> int:
    """Sweeper job ``billing.auto_topup``: charge queued top-ups, then disable failed ones."""
    handled = _charge_queued(
        sessionmaker,
        client,
        settings,
        purpose=PaymentPurpose.auto_topup,
        dedupe_prefix=AUTO_TOPUP_DEDUPE_PREFIX,
        card_for=_auto_topup_card,
    )
    with sessionmaker() as session:
        handled += _disable_failed_auto_topups(session)
        session.commit()
    log.debug("auto_topup_job_done", at=now.isoformat(), handled=handled)
    return handled
```

`test_job_charges_the_payers_card` expects `1` on the first run and `0` on the second. The failure sweep counts only settings whose latest payment failed, so an accepted charge adds nothing.

Add the handler wrapper below `on_auto_topup_paid`:

```python
def handle_auto_topup_paid(session: Session, payment: Payment, obj: Mapping[str, Any]) -> None:
    """Phase 02 ``PaidHandler`` for ``auto_topup``."""
    del obj
    on_auto_topup_paid(session, payment)
```

At the end of the module, next to the other two registrations, add:

```python
register_paid_handler(PaymentPurpose.auto_topup, handle_auto_topup_paid)
```

Add `"handle_auto_topup_paid"`, `"on_auto_topup_paid"` and `"run_auto_topup_job"` to `__all__`.

- [ ] **Step 4: Wire the sweeper job (Phase 02's pattern)**

In `lemely/web/deps_billing.py`, next to `get_extra_seat_renewal_job`, add:

```python
def get_auto_topup_job() -> Callable[[datetime], int] | None:
    """The ``billing.auto_topup`` job, or ``None`` when Paymob is unconfigured."""
    settings = get_settings().paymob
    if not settings.checkout_configured:
        return None

    def job(now: datetime) -> int:
        return run_auto_topup_job(get_billing_sessionmaker(), get_paymob_client(), settings, now=now)

    return job
```

Import `run_auto_topup_job` next to `run_extra_seat_renewal_job`, and add `"get_auto_topup_job"` to `__all__`.

In `lemely/web/scheduled_notifications.py`, add this field to `class Sweeper`, after `billing_extra_seat_renewal`:

```python
    #: ``billing.auto_topup`` (billing spec §5.5), given only when Paymob is configured.
    billing_auto_topup: Callable[[datetime], int] | None = None
```

In `Sweeper.sweep_once`, directly before `return run_jobs(jobs)`, add:

```python
        billing_auto_topup = self.billing_auto_topup
        if billing_auto_topup is not None:
            jobs.append(("billing.auto_topup", lambda: billing_auto_topup(moment)))
```

In `lemely/web/deps.py` `get_sweeper`, extend the local import with `get_auto_topup_job`, and add `billing_auto_topup=get_auto_topup_job(),` to the `Sweeper(...)` call.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_auto_topup_job.py tests/test_auto_topup_enqueue.py tests/test_merchant_charge_renewal_seats.py tests/test_scheduled_notifications.py tests/test_billing_reconcile.py -v --no-cov`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files
git commit -S -m "feat(billing): charge queued auto top-ups, grant on callback, disable on failure" -- \
  lemely/db/merchant_charge_repo.py lemely/web/deps_billing.py lemely/web/deps.py \
  lemely/web/scheduled_notifications.py tests/test_auto_topup_job.py
```

---

### Task 9: Routes: upgrade, quotes, extra seats, auto top-up settings, with IDOR and authz tests

**Files:**
- Modify: `lemely/db/merchant_charge_repo.py` (auto top-up settings read and write)
- Create: `lemely/web/schemas_billing_charges.py`
- Create: `lemely/web/merchant_charge_deps.py` (`MerchantChargeDeps` bundle, like Phase 05's `subscription_deps.py`)
- Modify: `lemely/web/deps_billing.py` (`get_merchant_charge_deps`, and its `cache_clear()` in `reset_billing_singletons`)
- Modify: `lemely/web/routers/billing.py` (Phase 02's `/api/billing` router: seven routes)
- Modify: `tests/test_authz_matrix_complete.py` (declare the seven routes)
- Create: `tests/test_web_billing_charges.py`

**Interfaces:**
- Consumes: everything above; `require_role`, `AuthContext` and `get_settings` (`lemely.web.deps`); `get_parent_link_service` and `ParentLinkService.lock_link_in_session(session, parent_id, child_id) -> bool`; `get_paymob_client` and `get_billing_sessionmaker` (`lemely.web.deps_billing`).
- Produces:
  - `AutoTopupView` (frozen dataclass), `MerchantChargeService.get_auto_topup(*, payer_user_id, beneficiary_user_id, now) -> AutoTopupView` (a "not set up" view when no row exists; `not_found` when another payer owns it) and `MerchantChargeService.put_auto_topup(*, payer_user_id, beneficiary_user_id, enabled, threshold_units, credit_pack_id, saved_card_id, monthly_cap_minor, now) -> AutoTopupView`.
  - Routes on Phase 02's router (prefix `/api/billing`; Phase 08 matches these exactly, index R3):
    - `POST /subscriptions/{subscription_id}/upgrade/quote` → 200 `ChargeQuoteDTO` (no side effects)
    - `POST /subscriptions/{subscription_id}/upgrade` → 202 `ChargeDTO`
    - `POST /subscriptions/{subscription_id}/seats/quote` → 200 `ChargeQuoteDTO` (no side effects)
    - `POST /subscriptions/{subscription_id}/seats` → 202 `ChargeDTO`
    - `PUT /subscriptions/{subscription_id}/seats/pending` → 200 `SeatsDTO`
    - `GET /auto-topup?beneficiaryId=` → 200 `AutoTopupDTO` (not set up yet: `enabled=false`, `creditPackId`/`thresholdUnits`/`savedCardId`/`monthlyCapMinor` null); 404 when another payer manages it
    - `PUT /auto-topup` → 200 `AutoTopupDTO`
  - Error body: `{"detail": {"error": <code>, "message": <text>}}`.
  - `lemely.web.merchant_charge_deps.MerchantChargeDeps(sessionmaker, client, settings, parent_links)` and `lemely.web.deps_billing.get_merchant_charge_deps() -> MerchantChargeDeps`.

- [ ] **Step 1: Write the failing route tests**

Create `tests/test_web_billing_charges.py`:

```python
"""HTTP layer for merchant charges: payer-only access, IDOR, error codes."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from lemely.db.models.billing import Payment, PaymentPurpose, PlanAudience, SavedCard, Subscription
from lemely.db.models.enums import Role
from lemely.db.parent_repo import ParentLinkService
from lemely.web import create_app
from lemely.web.deps import AuthContext, get_auth_context
from lemely.web.deps_billing import get_merchant_charge_deps
from lemely.web.merchant_charge_deps import MerchantChargeDeps
from tests.fake_paymob_moto import FakeMotoClient
from tests.merchant_charge_seed import (
    link_parent,
    make_credit_pack,
    make_saved_card,
    make_seat,
    make_subscription,
    make_tier,
    make_user,
    paymob_settings,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker

START = datetime(2026, 11, 1, tzinfo=UTC)
END = datetime(2099, 12, 1, tzinfo=UTC)  # far future: proration never hits zero


@pytest.fixture
def fake() -> FakeMotoClient:
    return FakeMotoClient()


@pytest.fixture
def client(migrated_sessionmaker: sessionmaker[Session], fake: FakeMotoClient) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_merchant_charge_deps] = lambda: MerchantChargeDeps(
        sessionmaker=migrated_sessionmaker, client=fake, settings=paymob_settings(),
        parent_links=ParentLinkService(migrated_sessionmaker),
    )
    yield TestClient(app)
    app.dependency_overrides.clear()


def _as(client: TestClient, user_id: uuid.UUID, role: Role) -> None:
    client.app.dependency_overrides[get_auth_context] = lambda: AuthContext(  # type: ignore[union-attr]
        user_id=str(user_id), role=role.value
    )


@pytest.fixture
def world(migrated_sessionmaker: sessionmaker[Session]) -> dict[str, uuid.UUID]:
    with migrated_sessionmaker.begin() as s:
        student = make_user(s, Role.student)
        parent = make_user(s, Role.parent)
        child = make_user(s, Role.student)
        stranger_parent = make_user(s, Role.parent)
        link_parent(s, parent_id=parent.id, child_id=child.id)
        teacher = make_user(s, Role.teacher)
        other_teacher = make_user(s, Role.teacher)
        basic = make_tier(s, price_minor=10_000)
        plus = make_tier(s, price_minor=20_000)
        t_tier = make_tier(s, audience=PlanAudience.teacher, price_minor=30_000, included_seats=1,
                           extra_seat_price_minor=2_000)
        student_sub, _ = make_subscription(s, user=student, tier=basic, period_start=START, period_end=END)
        child_sub, _ = make_subscription(s, user=child, payer=parent, tier=basic, period_start=START, period_end=END)
        teacher_sub, _ = make_subscription(s, user=teacher, tier=t_tier, period_start=START, period_end=END,
                                           extra_seats=1)
        make_seat(s, teacher_user_id=teacher.id, created_at=START)
        make_seat(s, teacher_user_id=teacher.id, created_at=START)
        for owner in (student, parent, teacher):
            make_saved_card(s, owner.id)
        other_card = make_saved_card(s, stranger_parent.id)
        pack = make_credit_pack(s)
        return {
            "student": student.id, "parent": parent.id, "child": child.id,
            "stranger_parent": stranger_parent.id, "teacher": teacher.id, "other_teacher": other_teacher.id,
            "plus": plus.id, "student_sub": student_sub.id, "child_sub": child_sub.id,
            "teacher_sub": teacher_sub.id, "pack": pack.id, "other_card": other_card.id,
        }


def test_payer_upgrades_and_gets_a_pending_charge(client: TestClient, world: dict[str, uuid.UUID]) -> None:
    _as(client, world["student"], Role.student)
    response = client.post(f"/api/billing/subscriptions/{world['student_sub']}/upgrade",
                           json={"planTierId": str(world["plus"])})
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "pending"
    assert body["currency"] == "EGP"
    uuid.UUID(body["paymentId"])


def test_parent_payer_upgrades_childs_plan(client: TestClient, world: dict[str, uuid.UUID]) -> None:
    _as(client, world["parent"], Role.parent)
    response = client.post(f"/api/billing/subscriptions/{world['child_sub']}/upgrade",
                           json={"planTierId": str(world["plus"])})
    assert response.status_code == 202


@pytest.mark.parametrize(("actor", "role"), [("child", Role.student), ("stranger_parent", Role.parent)])
def test_non_payer_gets_404_not_403(client: TestClient, world: dict[str, uuid.UUID], fake: FakeMotoClient,
                                    actor: str, role: Role) -> None:
    _as(client, world[actor], role)
    response = client.post(f"/api/billing/subscriptions/{world['child_sub']}/upgrade",
                           json={"planTierId": str(world["plus"])})
    assert response.status_code == 404
    assert response.json()["detail"]["error"] == "not_found"
    assert fake.calls == []


def test_teacher_buys_extra_seats(client: TestClient, world: dict[str, uuid.UUID]) -> None:
    _as(client, world["teacher"], Role.teacher)
    response = client.post(f"/api/billing/subscriptions/{world['teacher_sub']}/seats", json={"seats": 2})
    assert response.status_code == 202


def test_other_teacher_cannot_touch_seats(client: TestClient, world: dict[str, uuid.UUID]) -> None:
    _as(client, world["other_teacher"], Role.teacher)
    add = client.post(f"/api/billing/subscriptions/{world['teacher_sub']}/seats", json={"seats": 1})
    reduce = client.put(f"/api/billing/subscriptions/{world['teacher_sub']}/seats/pending",
                        json={"extraSeats": 0})
    assert (add.status_code, reduce.status_code) == (404, 404)


def test_student_role_cannot_reach_seat_routes(client: TestClient, world: dict[str, uuid.UUID]) -> None:
    _as(client, world["student"], Role.student)
    response = client.post(f"/api/billing/subscriptions/{world['student_sub']}/seats", json={"seats": 1})
    assert response.status_code == 403


def test_seat_reduction_below_seated_students_is_409(client: TestClient, world: dict[str, uuid.UUID]) -> None:
    _as(client, world["teacher"], Role.teacher)
    response = client.put(f"/api/billing/subscriptions/{world['teacher_sub']}/seats/pending",
                          json={"extraSeats": 0})
    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "seats_in_use"


def test_invalid_seat_count_is_422(client: TestClient, world: dict[str, uuid.UUID]) -> None:
    _as(client, world["teacher"], Role.teacher)
    response = client.post(f"/api/billing/subscriptions/{world['teacher_sub']}/seats", json={"seats": 0})
    assert response.status_code == 422


def test_upgrade_quote_has_no_side_effects(client: TestClient, world: dict[str, uuid.UUID],
                                           fake: FakeMotoClient,
                                           migrated_sessionmaker: sessionmaker[Session]) -> None:
    _as(client, world["student"], Role.student)
    response = client.post(f"/api/billing/subscriptions/{world['student_sub']}/upgrade/quote",
                           json={"planTierId": str(world["plus"])})
    assert response.status_code == 200
    body = response.json()
    assert body["currency"] == "EGP"
    assert 0 < body["amountMinor"] <= 10_000
    assert set(body) == {"amountMinor", "currency", "allowanceUnits", "periodEnd"}
    assert fake.calls == []
    with migrated_sessionmaker() as s:
        assert s.scalar(sa.select(sa.func.count()).select_from(Payment).where(
            Payment.purpose == PaymentPurpose.upgrade_proration)) == 0


def test_seats_quote_for_the_teacher(client: TestClient, world: dict[str, uuid.UUID], fake: FakeMotoClient) -> None:
    _as(client, world["teacher"], Role.teacher)
    response = client.post(f"/api/billing/subscriptions/{world['teacher_sub']}/seats/quote", json={"seats": 2})
    assert response.status_code == 200
    assert 0 < response.json()["amountMinor"] <= 4_000
    assert fake.calls == []


@pytest.mark.parametrize(("actor", "role"), [("child", Role.student), ("stranger_parent", Role.parent)])
def test_quotes_are_payer_only(client: TestClient, world: dict[str, uuid.UUID], actor: str, role: Role) -> None:
    _as(client, world[actor], role)
    response = client.post(f"/api/billing/subscriptions/{world['child_sub']}/upgrade/quote",
                           json={"planTierId": str(world["plus"])})
    assert response.status_code == 404
    _as(client, world["other_teacher"], Role.teacher)
    seats = client.post(f"/api/billing/subscriptions/{world['teacher_sub']}/seats/quote", json={"seats": 1})
    assert seats.status_code == 404


def _card_of(sm: sessionmaker[Session], user_id: uuid.UUID) -> str:
    with sm() as s:
        return str(s.scalars(sa.select(SavedCard.id).where(SavedCard.user_id == user_id)).one())


def _settings_body(pack: uuid.UUID, card: str, **extra: object) -> dict[str, object]:
    return {"enabled": True, "thresholdUnits": 200, "creditPackId": str(pack), "savedCardId": card,
            "monthlyCapMinor": 30_000, **extra}


def test_student_manages_own_auto_topup(client: TestClient, world: dict[str, uuid.UUID],
                                        migrated_sessionmaker: sessionmaker[Session]) -> None:
    _as(client, world["student"], Role.student)
    empty = client.get("/api/billing/auto-topup")
    assert empty.status_code == 200  # "not set up yet" is a state, not a 404
    assert empty.json() == {
        "beneficiaryId": str(world["student"]), "enabled": False, "thresholdUnits": None,
        "creditPackId": None, "savedCardId": None, "monthlyCapMinor": None,
        "spentThisMonthMinor": 0, "currency": "EGP", "disabledReason": None,
    }
    put = client.put("/api/billing/auto-topup",
                     json=_settings_body(world["pack"], _card_of(migrated_sessionmaker, world["student"])))
    assert put.status_code == 200
    got = client.get("/api/billing/auto-topup").json()
    assert (got["enabled"], got["thresholdUnits"], got["beneficiaryId"]) == (True, 200, str(world["student"]))
    assert (got["creditPackId"], got["currency"]) == (str(world["pack"]), "EGP")


def test_parent_manages_linked_childs_auto_topup(client: TestClient, world: dict[str, uuid.UUID],
                                                 migrated_sessionmaker: sessionmaker[Session]) -> None:
    _as(client, world["parent"], Role.parent)
    body = _settings_body(world["pack"], _card_of(migrated_sessionmaker, world["parent"]),
                          beneficiaryId=str(world["child"]))
    assert client.put("/api/billing/auto-topup", json=body).status_code == 200
    # The child sees balance, not billing: the parent's setting is invisible to them.
    _as(client, world["child"], Role.student)
    assert client.get("/api/billing/auto-topup").status_code == 404
    child_put = client.put("/api/billing/auto-topup", json=_settings_body(world["pack"], str(uuid.uuid4())))
    assert child_put.status_code == 409
    assert child_put.json()["detail"]["error"] == "managed_by_another_payer"


def test_parent_cannot_manage_unlinked_child(client: TestClient, world: dict[str, uuid.UUID],
                                             migrated_sessionmaker: sessionmaker[Session]) -> None:
    _as(client, world["stranger_parent"], Role.parent)
    body = _settings_body(world["pack"], str(world["other_card"]), beneficiaryId=str(world["child"]))
    assert client.put("/api/billing/auto-topup", json=body).status_code == 403
    assert client.get(f"/api/billing/auto-topup?beneficiaryId={world['child']}").status_code == 403


def test_another_users_card_is_404(client: TestClient, world: dict[str, uuid.UUID]) -> None:
    _as(client, world["student"], Role.student)
    response = client.put("/api/billing/auto-topup", json=_settings_body(world["pack"], str(world["other_card"])))
    assert response.status_code == 404
    assert response.json()["detail"]["error"] == "card_not_found"


def test_student_cannot_target_another_beneficiary(client: TestClient, world: dict[str, uuid.UUID],
                                                   migrated_sessionmaker: sessionmaker[Session]) -> None:
    _as(client, world["student"], Role.student)
    body = _settings_body(world["pack"], _card_of(migrated_sessionmaker, world["student"]),
                          beneficiaryId=str(world["child"]))
    assert client.put("/api/billing/auto-topup", json=body).status_code == 403


def test_cap_below_pack_price_is_409(client: TestClient, world: dict[str, uuid.UUID],
                                     migrated_sessionmaker: sessionmaker[Session]) -> None:
    _as(client, world["student"], Role.student)
    body = _settings_body(world["pack"], _card_of(migrated_sessionmaker, world["student"]), monthlyCapMinor=5)
    response = client.put("/api/billing/auto-topup", json=body)
    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "cap_below_pack_price"


def test_subscription_untouched_by_refused_requests(client: TestClient, world: dict[str, uuid.UUID],
                                                    migrated_sessionmaker: sessionmaker[Session]) -> None:
    _as(client, world["child"], Role.student)
    client.post(f"/api/billing/subscriptions/{world['child_sub']}/upgrade", json={"planTierId": str(world["plus"])})
    with migrated_sessionmaker() as s:
        assert s.get_one(Subscription, world["child_sub"]).plan_tier_id != world["plus"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_web_billing_charges.py -v --no-cov`
Expected: FAIL with `ModuleNotFoundError: No module named 'lemely.web.merchant_charge_deps'`.

- [ ] **Step 3: Add the settings read and write to the service**

In `lemely/db/merchant_charge_repo.py`, add `from dataclasses import dataclass`, then add:

```python
#: Billing currency for a balance with no settings row yet (Lemely charges EGP only, spec §1).
DEFAULT_CURRENCY: Final = "EGP"


@dataclass(frozen=True, slots=True)
class AutoTopupView:
    """One balance's auto top-up. With no settings row yet ("not set up"): ``enabled`` is
    False and ``threshold_units``, ``credit_pack_id``, ``saved_card_id`` and
    ``monthly_cap_minor`` are None."""

    beneficiary_user_id: uuid.UUID
    enabled: bool
    threshold_units: int | None
    credit_pack_id: uuid.UUID | None
    saved_card_id: uuid.UUID | None
    monthly_cap_minor: int | None
    spent_this_month_minor: int
    currency: str
    disabled_reason: str | None


def _spent_this_month(session: Session, beneficiary_user_id: uuid.UUID, *, now: datetime) -> int:
    return int(
        session.scalar(
            sa.select(sa.func.coalesce(sa.func.sum(Payment.amount_minor), 0)).where(
                Payment.beneficiary_user_id == beneficiary_user_id,
                Payment.purpose == PaymentPurpose.auto_topup,
                Payment.status.in_((*IN_FLIGHT_STATUSES, PaymentStatus.paid)),
                Payment.created_at >= _month_start(now),
            )
        )
        or 0
    )


def _view(session: Session, setting: AutoTopupSettings, *, now: datetime) -> AutoTopupView:
    pack = session.get(CreditPack, setting.credit_pack_id)
    return AutoTopupView(
        beneficiary_user_id=setting.beneficiary_user_id,
        enabled=setting.enabled,
        threshold_units=setting.threshold_units,
        credit_pack_id=setting.credit_pack_id,
        saved_card_id=setting.saved_card_id,
        monthly_cap_minor=setting.monthly_cap_minor,
        spent_this_month_minor=_spent_this_month(session, setting.beneficiary_user_id, now=now),
        currency=pack.currency if pack is not None else DEFAULT_CURRENCY,
        disabled_reason=setting.disabled_reason,
    )


def _not_set_up_view(session: Session, beneficiary_user_id: uuid.UUID, *, now: datetime) -> AutoTopupView:
    return AutoTopupView(
        beneficiary_user_id=beneficiary_user_id,
        enabled=False,
        threshold_units=None,
        credit_pack_id=None,
        saved_card_id=None,
        monthly_cap_minor=None,
        spent_this_month_minor=_spent_this_month(session, beneficiary_user_id, now=now),
        currency=DEFAULT_CURRENCY,
        disabled_reason=None,
    )
```

Add these methods to `MerchantChargeService`. Callers must already have authorized `payer_user_id` to act for `beneficiary_user_id` (self, or a linked parent):

```python
    def get_auto_topup(
        self, *, payer_user_id: uuid.UUID, beneficiary_user_id: uuid.UUID, now: datetime
    ) -> AutoTopupView:
        """The setting for this balance; a "not set up" view when no row exists yet.

        Raises:
            MerchantChargeError: ``not_found`` when another payer owns the setting (the
                beneficiary sees balance, not billing; spec §7). The route maps it to 404.
        """
        setting = self.session.scalars(
            sa.select(AutoTopupSettings).where(
                AutoTopupSettings.beneficiary_user_id == beneficiary_user_id
            )
        ).first()
        if setting is None:
            return _not_set_up_view(self.session, beneficiary_user_id, now=now)
        if setting.payer_user_id != payer_user_id:
            raise MerchantChargeError("not_found", "No auto top-up for this account.")
        return _view(self.session, setting, now=now)

    def put_auto_topup(
        self,
        *,
        payer_user_id: uuid.UUID,
        beneficiary_user_id: uuid.UUID,
        enabled: bool,
        threshold_units: int,
        credit_pack_id: uuid.UUID,
        saved_card_id: uuid.UUID | None,
        monthly_cap_minor: int,
        now: datetime,
    ) -> AutoTopupView:
        if threshold_units <= 0 or monthly_cap_minor < 0:
            raise MerchantChargeError("invalid_settings", "Threshold must be positive and the cap not negative.")
        setting = self.session.execute(
            sa.select(AutoTopupSettings)
            .where(AutoTopupSettings.beneficiary_user_id == beneficiary_user_id)
            .with_for_update()
        ).scalar_one_or_none()
        if setting is not None and setting.payer_user_id != payer_user_id:
            raise MerchantChargeError("managed_by_another_payer", "Someone else manages auto top-up for this account.")
        pack = self.session.get(CreditPack, credit_pack_id)
        if pack is None or not pack.is_active:
            raise MerchantChargeError("pack_not_found", "Credit pack not found.")
        if saved_card_id is not None:
            card = self.session.get(SavedCard, saved_card_id)
            if card is None or card.user_id != payer_user_id or not card.is_active:
                raise MerchantChargeError("card_not_found", "Card not found.")
        if enabled and saved_card_id is None:
            raise MerchantChargeError("no_saved_card", "Choose a saved card for auto top-up.")
        if enabled and monthly_cap_minor < pack.price_minor:
            raise MerchantChargeError("cap_below_pack_price", "The monthly cap is below the pack price.")
        if setting is None:
            setting = AutoTopupSettings(
                beneficiary_user_id=beneficiary_user_id,
                payer_user_id=payer_user_id,
                enabled=False,
                threshold_units=threshold_units,
                credit_pack_id=credit_pack_id,
                monthly_cap_minor=monthly_cap_minor,
                armed=True,
                crossing_seq=0,
            )
            self.session.add(setting)
        if enabled and not setting.enabled:
            setting.armed = True
            setting.crossing_seq = setting.crossing_seq + 1
            setting.disabled_reason = None
        setting.enabled = enabled
        setting.threshold_units = threshold_units
        setting.credit_pack_id = credit_pack_id
        setting.saved_card_id = saved_card_id
        setting.monthly_cap_minor = monthly_cap_minor
        self.session.flush()
        return _view(self.session, setting, now=now)
```

Add `"AutoTopupView"` to `__all__`.

- [ ] **Step 4: Add the DTOs**

Create `lemely/web/schemas_billing_charges.py`:

```python
"""Merchant-charge API DTOs (camelCase wire format, Paymob billing phase 06)."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from lemely.db.merchant_charge_repo import MAX_SEATS_PER_PURCHASE
from lemely.web.schemas import ApiModel


class UpgradeRequest(ApiModel):
    planTierId: str


class ExtraSeatsRequest(ApiModel):
    seats: int = Field(ge=1, le=MAX_SEATS_PER_PURCHASE)


class SeatReductionRequest(ApiModel):
    extraSeats: int = Field(ge=0)


class ChargeDTO(ApiModel):
    """A merchant charge just sent. Poll ``GET /api/billing/payments/{paymentId}`` for the outcome."""

    paymentId: str
    status: str
    amountMinor: int
    currency: str


class ChargeQuoteDTO(ApiModel):
    """A prorated price as it would be charged now (index R3 quote routes; no side effects)."""

    amountMinor: int
    currency: str
    allowanceUnits: int | None = None  # upgrade only; null for seats
    periodEnd: datetime


class SeatsDTO(ApiModel):
    extraSeats: int
    pendingExtraSeats: int | None = None


class AutoTopupRequest(ApiModel):
    beneficiaryId: str | None = None
    enabled: bool
    thresholdUnits: int = Field(gt=0)
    creditPackId: str
    savedCardId: str | None = None
    monthlyCapMinor: int = Field(ge=0)


class AutoTopupDTO(ApiModel):
    """Not set up yet: ``enabled`` false and the four setting fields null."""

    beneficiaryId: str
    enabled: bool
    thresholdUnits: int | None = None
    creditPackId: str | None = None
    savedCardId: str | None = None
    monthlyCapMinor: int | None = None
    spentThisMonthMinor: int
    currency: str
    disabledReason: str | None = None
```

- [ ] **Step 5: Add the dependency bundle (Phase 05's `subscription_deps.py` pattern)**

Create `lemely/web/merchant_charge_deps.py`:

```python
"""Collaborators the merchant-charge routes share (Paymob billing phase 06)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker

    from lemely.db.parent_repo import ParentLinkService
    from lemely.io.paymob.client import PaymobClient
    from lemely.runtime.config import PaymobSettings


@dataclass(frozen=True, slots=True)
class MerchantChargeDeps:
    sessionmaker: sessionmaker[Session]
    client: PaymobClient
    settings: PaymobSettings
    parent_links: ParentLinkService


__all__ = ["MerchantChargeDeps"]
```

In `lemely/web/deps_billing.py`, add the provider and clear it in `reset_billing_singletons()` (`get_merchant_charge_deps.cache_clear()`). Add `"get_merchant_charge_deps"` to `__all__`:

```python
@lru_cache(maxsize=1)
def get_merchant_charge_deps() -> MerchantChargeDeps:
    """The merchant-charge routes' collaborators; tests override this dependency."""
    from lemely.web.deps import get_parent_link_service

    settings = get_settings()
    return MerchantChargeDeps(
        sessionmaker=get_billing_sessionmaker(),
        client=get_paymob_client(),
        settings=settings.paymob,
        parent_links=get_parent_link_service(),
    )
```

with `from lemely.web.merchant_charge_deps import MerchantChargeDeps` at the top. `lru_cache` and `get_settings` are already imported there for Phase 05's providers.

- [ ] **Step 6: Add the routes to Phase 02's router**

Append to `lemely/web/routers/billing.py`. Phase 02's router object (`router = APIRouter(prefix="/api/billing")`) is already mounted by `create_app`, so `lemely/web/app.py` does not change. Merge these imports into the module's import block, and skip any name it already imports:

```python
import uuid
from datetime import UTC, datetime
from typing import Annotated, Final

from fastapi import Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from lemely.db.merchant_charge_repo import (
    AutoTopupView,
    ChargeQuote,
    MerchantChargeError,
    MerchantChargeService,
)
from lemely.db.models.billing import Payment
from lemely.db.models.enums import Role
from lemely.web.deps import AuthContext, require_role
from lemely.web.deps_billing import get_merchant_charge_deps
from lemely.web.merchant_charge_deps import MerchantChargeDeps
from lemely.web.schemas_billing_charges import (
    AutoTopupDTO,
    AutoTopupRequest,
    ChargeDTO,
    ChargeQuoteDTO,
    ExtraSeatsRequest,
    SeatReductionRequest,
    SeatsDTO,
    UpgradeRequest,
)
```

Then append the code below. The module docstring gains one line: "Merchant charges (phase 06): upgrade and seat quotes and charges, seat reductions and auto top-up settings. Payer-only; a subscription the caller does not pay for answers 404 (IDOR)."

```python
# -- Merchant charges (Paymob billing phase 06, spec §5.3–§5.5) -------------------------

_PAYER_ROLES: Final = (Role.student, Role.parent, Role.teacher)
_NOT_FOUND: Final = frozenset({"not_found", "tier_not_found", "pack_not_found", "card_not_found"})
_UNPROCESSABLE: Final = frozenset({"invalid_seats", "invalid_settings"})

Deps = Annotated[MerchantChargeDeps, Depends(get_merchant_charge_deps)]


def _http(exc: MerchantChargeError) -> HTTPException:
    if exc.code in _NOT_FOUND:
        code = status.HTTP_404_NOT_FOUND
    elif exc.code in _UNPROCESSABLE:
        code = status.HTTP_422_UNPROCESSABLE_ENTITY
    else:
        code = status.HTTP_409_CONFLICT
    return HTTPException(status_code=code, detail={"error": exc.code, "message": str(exc)})


def _uuid(value: str, field: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"error": "invalid_id", "message": field}) from exc


def _charge_dto(payment: Payment) -> ChargeDTO:
    return ChargeDTO(
        paymentId=str(payment.id),
        status=payment.status.value,
        amountMinor=payment.amount_minor,
        currency=payment.currency,
    )


def _now() -> datetime:
    return datetime.now(UTC)


def _quote_dto(quote: ChargeQuote) -> ChargeQuoteDTO:
    return ChargeQuoteDTO(
        amountMinor=quote.amount_minor,
        currency=quote.currency,
        allowanceUnits=quote.allowance_units,
        periodEnd=quote.period_end,
    )


@router.post("/subscriptions/{subscription_id}/upgrade/quote", response_model=ChargeQuoteDTO)
def quote_upgrade(
    subscription_id: uuid.UUID,
    body: UpgradeRequest,
    deps: Deps,
    auth: Annotated[AuthContext, Depends(require_role(*_PAYER_ROLES))],
) -> ChargeQuoteDTO:
    """Index R3: the prorated upgrade price now. No side effects; payer only (404 otherwise)."""
    with deps.sessionmaker() as session:
        try:
            quote = MerchantChargeService(session, deps.client, deps.settings).quote_upgrade(
                subscription_id=subscription_id,
                actor_user_id=uuid.UUID(auth.user_id),
                plan_tier_id=_uuid(body.planTierId, "planTierId"),
                now=_now(),
            )
        except MerchantChargeError as exc:
            raise _http(exc) from exc
        return _quote_dto(quote)


@router.post("/subscriptions/{subscription_id}/seats/quote", response_model=ChargeQuoteDTO)
def quote_extra_seats(
    subscription_id: uuid.UUID,
    body: ExtraSeatsRequest,
    deps: Deps,
    auth: Annotated[AuthContext, Depends(require_role(Role.teacher))],
) -> ChargeQuoteDTO:
    """Index R3: the prorated price of ``seats`` extra seats now. No side effects; payer only."""
    with deps.sessionmaker() as session:
        try:
            quote = MerchantChargeService(session, deps.client, deps.settings).quote_extra_seats(
                subscription_id=subscription_id,
                actor_user_id=uuid.UUID(auth.user_id),
                seats=body.seats,
                now=_now(),
            )
        except MerchantChargeError as exc:
            raise _http(exc) from exc
        return _quote_dto(quote)


@router.post("/subscriptions/{subscription_id}/upgrade", status_code=202, response_model=ChargeDTO)
def upgrade_subscription(
    subscription_id: uuid.UUID,
    body: UpgradeRequest,
    deps: Deps,
    auth: Annotated[AuthContext, Depends(require_role(*_PAYER_ROLES))],
) -> ChargeDTO:
    with deps.sessionmaker() as session:
        service = MerchantChargeService(session, deps.client, deps.settings)
        try:
            payment = service.upgrade(
                subscription_id=subscription_id,
                actor_user_id=uuid.UUID(auth.user_id),
                plan_tier_id=_uuid(body.planTierId, "planTierId"),
                now=_now(),
            )
        except MerchantChargeError as exc:
            raise _http(exc) from exc
        session.refresh(payment)
        return _charge_dto(payment)


@router.post("/subscriptions/{subscription_id}/seats", status_code=202, response_model=ChargeDTO)
def buy_extra_seats(
    subscription_id: uuid.UUID,
    body: ExtraSeatsRequest,
    deps: Deps,
    auth: Annotated[AuthContext, Depends(require_role(Role.teacher))],
) -> ChargeDTO:
    with deps.sessionmaker() as session:
        service = MerchantChargeService(session, deps.client, deps.settings)
        try:
            payment = service.add_extra_seats(
                subscription_id=subscription_id,
                actor_user_id=uuid.UUID(auth.user_id),
                seats=body.seats,
                now=_now(),
            )
        except MerchantChargeError as exc:
            raise _http(exc) from exc
        session.refresh(payment)
        return _charge_dto(payment)


@router.put("/subscriptions/{subscription_id}/seats/pending", response_model=SeatsDTO)
def schedule_seat_reduction(
    subscription_id: uuid.UUID,
    body: SeatReductionRequest,
    deps: Deps,
    auth: Annotated[AuthContext, Depends(require_role(Role.teacher))],
) -> SeatsDTO:
    with deps.sessionmaker() as session:
        service = MerchantChargeService(session, deps.client, deps.settings)
        try:
            sub = service.schedule_seat_reduction(
                subscription_id=subscription_id,
                actor_user_id=uuid.UUID(auth.user_id),
                extra_seats=body.extraSeats,
                now=_now(),
            )
        except MerchantChargeError as exc:
            raise _http(exc) from exc
        session.commit()
        return SeatsDTO(extraSeats=sub.extra_seats, pendingExtraSeats=sub.pending_extra_seats)


def _authorized_beneficiary(
    session: Session, deps: MerchantChargeDeps, auth: AuthContext, beneficiary_id: str | None
) -> uuid.UUID:
    """Self, or (for a parent) a linked child. Anything else is 403."""
    caller = uuid.UUID(auth.user_id)
    if auth.role == Role.parent.value:
        if beneficiary_id is None:
            raise HTTPException(status_code=422, detail={"error": "beneficiary_required", "message": "beneficiaryId"})
        child = _uuid(beneficiary_id, "beneficiaryId")
        if not deps.parent_links.lock_link_in_session(session, caller, child):
            raise HTTPException(status_code=403, detail={"error": "not_linked", "message": "Child is not linked."})
        return child
    if beneficiary_id is not None and _uuid(beneficiary_id, "beneficiaryId") != caller:
        raise HTTPException(status_code=403, detail={"error": "not_linked", "message": "Not your account."})
    return caller


def _auto_topup_dto(view: AutoTopupView) -> AutoTopupDTO:
    return AutoTopupDTO(
        beneficiaryId=str(view.beneficiary_user_id),
        enabled=view.enabled,
        thresholdUnits=view.threshold_units,
        creditPackId=str(view.credit_pack_id) if view.credit_pack_id else None,
        savedCardId=str(view.saved_card_id) if view.saved_card_id else None,
        monthlyCapMinor=view.monthly_cap_minor,
        spentThisMonthMinor=view.spent_this_month_minor,
        currency=view.currency,
        disabledReason=view.disabled_reason,
    )


@router.get("/auto-topup", response_model=AutoTopupDTO)
def get_auto_topup(
    deps: Deps,
    auth: Annotated[AuthContext, Depends(require_role(*_PAYER_ROLES))],
    beneficiaryId: Annotated[str | None, Query()] = None,  # noqa: N803 - camelCase wire name
) -> AutoTopupDTO:
    with deps.sessionmaker() as session:
        beneficiary = _authorized_beneficiary(session, deps, auth, beneficiaryId)
        try:
            view = MerchantChargeService(session, deps.client, deps.settings).get_auto_topup(
                payer_user_id=uuid.UUID(auth.user_id), beneficiary_user_id=beneficiary, now=_now()
            )
        except MerchantChargeError as exc:
            raise _http(exc) from exc
        return _auto_topup_dto(view)


@router.put("/auto-topup", response_model=AutoTopupDTO)
def put_auto_topup(
    body: AutoTopupRequest,
    deps: Deps,
    auth: Annotated[AuthContext, Depends(require_role(*_PAYER_ROLES))],
) -> AutoTopupDTO:
    with deps.sessionmaker() as session:
        beneficiary = _authorized_beneficiary(session, deps, auth, body.beneficiaryId)
        try:
            view = MerchantChargeService(session, deps.client, deps.settings).put_auto_topup(
                payer_user_id=uuid.UUID(auth.user_id),
                beneficiary_user_id=beneficiary,
                enabled=body.enabled,
                threshold_units=body.thresholdUnits,
                credit_pack_id=_uuid(body.creditPackId, "creditPackId"),
                saved_card_id=_uuid(body.savedCardId, "savedCardId") if body.savedCardId else None,
                monthly_cap_minor=body.monthlyCapMinor,
                now=_now(),
            )
        except MerchantChargeError as exc:
            raise _http(exc) from exc
        session.commit()
        return _auto_topup_dto(view)
```

`put_auto_topup` (Step 3) checks the owning payer before it validates the pack or the card. That order is intended: a beneficiary whose balance a parent manages gets `managed_by_another_payer` (409), whatever card id they send. `test_parent_manages_linked_childs_auto_topup` relies on it.

The quote routes never commit and never call Paymob. `quote_upgrade` and `quote_extra_seats` read without a row lock, and the session closes without a commit. `test_upgrade_quote_has_no_side_effects` checks both.

- [ ] **Step 7: Declare the routes in the authz matrix**

In `tests/test_authz_matrix_complete.py`, add these entries to `EXPECTED`. They reuse Phase 02's guard for billing routes, `TUTORING_PARTY` (`{"student", "parent", "teacher"}`). Payer-only and IDOR rules are object-level and are tested in `tests/test_web_billing_charges.py`:

```python
    # Paymob billing phase 06 (spec §5.3–§5.5, index R3): payer-only and IDOR are object-level
    # (tests/test_web_billing_charges.py).
    ("POST", "/api/billing/subscriptions/{subscription_id}/upgrade/quote"): TUTORING_PARTY,
    ("POST", "/api/billing/subscriptions/{subscription_id}/upgrade"): TUTORING_PARTY,
    ("POST", "/api/billing/subscriptions/{subscription_id}/seats/quote"): TEACHER,
    ("POST", "/api/billing/subscriptions/{subscription_id}/seats"): TEACHER,
    ("PUT", "/api/billing/subscriptions/{subscription_id}/seats/pending"): TEACHER,
    ("GET", "/api/billing/auto-topup"): TUTORING_PARTY,
    ("PUT", "/api/billing/auto-topup"): TUTORING_PARTY,
```

If the file keeps a per-section count in comments (`# ── TEACHER (24)`), update the counts.

- [ ] **Step 8: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_web_billing_charges.py tests/test_authz_matrix_complete.py tests/test_authz_matrix.py tests/architecture/ -v --no-cov`
Expected: PASS.

- [ ] **Step 9: Run the phase's whole touched set once more on the final tree**

Run: `PYTHONPATH=$PWD /home/sico/Code/Lemely/.venv/bin/pytest tests/test_migration_auto_topup.py tests/test_billing_email_templates.py tests/test_notify_email.py tests/test_email_outbox_repo.py tests/test_merchant_charge_core.py tests/test_merchant_charge_upgrade.py tests/test_merchant_charge_seats.py tests/test_merchant_charge_renewal_seats.py tests/test_usage_post_settle_hooks.py tests/test_auto_topup_enqueue.py tests/test_auto_topup_job.py tests/test_web_billing_charges.py tests/test_authz_matrix_complete.py tests/test_db_schema.py tests/test_scheduled_notifications.py tests/test_billing_reconcile.py tests/architecture/ -v --no-cov`
Expected: PASS.

- [ ] **Step 10: Commit**

```bash
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files
git commit -S -m "feat(billing): upgrade and seat quotes, charges and auto top-up routes, payer-only" -- \
  lemely/db/merchant_charge_repo.py lemely/web/schemas_billing_charges.py \
  lemely/web/merchant_charge_deps.py lemely/web/deps_billing.py lemely/web/routers/billing.py \
  tests/test_authz_matrix_complete.py tests/test_web_billing_charges.py
```

---

## Spec coverage (self-review)

| Spec requirement | Task |
|---|---|
| §2.1 optional auto top-up: threshold, saved card, chosen pack, monthly cap | 7, 8, 9 |
| §2.2 extra seats charged prorated at once, then renew with the plan; removal at period end | 5, 6 |
| §2.5 receipts for upgrade, extra seats, auto top-up | A `paid` payment is the receipt (Phase 02); every charge here is a `payments` row |
| §2.6 upgrade immediate, prorated charge, allowance difference granted at once | 4 (prorated, deviation 5) |
| §4.6 `auto_topup_settings`, owned by the payer | 1 (deviation 1) |
| §5.3 upgrade: proration, MOTO intention + `payments/pay`, PUT on callback (via `sync_renewal_amount`), switch tier, grant to `period_end` | 3, 4 |
| §5.4 add (prorated charge, PUT via `sync_renewal_amount`); remove (pending, refused below seated); Phase 05 PUTs before renewal and applies at renewal (R6) | 5 (Phase 05 owns the renewal side) |
| Index R3 quote routes (prorated amount, no side effects, payer only) | 4, 5, 9 |
| §5.4 fallback: renewal seat charge, 3-day grace, seats to 0, newest students leaving | 6 |
| §5.5 auto top-up: after settle, threshold, cap, no in-flight, dedupe per crossing, sweeper charge, grant, disable and email | 7, 8 |
| §5.8 grants repay debt first | 4, 8 via `UsageLedger.issue_grant` |
| §6 record before calling Paymob, inquiry before any retry, never retry blindly | 3 (claim and commit, inquiry, `ChargeAlreadyAttempted`); 6 (retries only after a definite failure) |
| §7 only the payer manages billing; parent only for a linked child; beneficiary sees balance only; IDOR tests | 9 |
| §8 health: failed auto top-ups and failed extra-seat charges | Data lives in `payments` (`purpose`, `status`, `dedupe_key` prefix) and `auto_topup_settings.disabled_reason` for Phase 07 to read |
| §10 question 7 | Settings flag `paymob.subscription_amount_updatable` (deviations 6, 7) |

# Paymob billing — implementation plan index and shared contracts

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement each phase plan task-by-task.

**Spec:** `docs/superpowers/specs/2026-11-02-paymob-billing-design.md` (revision 2). The spec is
the source of truth for behaviour; this index is the source of truth for names, files,
migration numbers and cross-phase interfaces. A phase plan that disagrees with this index is
wrong.

**Branch:** `feat/paymob-integration`, rebased on `origin/develop` at `8d388747`. Latest
migration on develop: `0051_tutor_evidence_uploads.py`.

## Phases

Each phase is its own plan file and ships working, tested software on its own. Phases run in
order; a phase may start only when every phase it consumes is merged into the branch.

| # | Plan file | Delivers | Migration | Consumes |
|---|---|---|---|---|
| 01 | `2026-11-05-paymob-billing-01-usage-ledger.md` | Usage ledger models, pure pricing core, ledger repository (grants, reserve, settle, release, expire, debt, reconcile) | `0052_usage_ledger` | — |
| 02 | `2026-11-05-paymob-billing-02-payments-core.md` | Paymob settings, client, HMAC; payments, events, saved cards, credit packs; catalogue columns on `plan_tiers` and `subscriptions`; one-off checkout; transaction and token webhooks; reconciliation job; receipts API | `0053_billing_payments` | 01 |
| 03 | `2026-11-05-paymob-billing-03-teacher-team.md` | `teacher_members`, assistant invites, seat claim on class join, scope, caps, roles and permissions, `require_team_permission`, team router | `0054_teacher_team` | 02 |
| 04 | `2026-11-05-paymob-billing-04-metering.md` | Provider-agnostic LLM cost accumulator, `UsageMeter`, payer chain, `require_usage`, estimate endpoint, metering wired into every LLM-backed route, free allowances on signup, usage meter and usage history API | none (tables from 01) | 01, 03 |
| 05 | `2026-11-05-paymob-billing-05-subscriptions.md` | Subscription checkout, Paymob plans and subscription webhooks, renewal, grace, downgrade, cancel, daily drift check, monthly seat allowances and seat release | `0055_subscription_periods` | 02, 03, 04 |
| 06 | `2026-11-05-paymob-billing-06-merchant-charges.md` | MOTO merchant-initiated charges: upgrade proration, extra seats (with fallback), auto top-up | `0056_auto_topup` | 02, 05 |
| 07 | `2026-11-05-paymob-billing-07-admin-backend.md` | Admin audit log and all five admin API areas (catalogue, customer view, payments, margin, health) | `0057_admin_audit_log` | 01–06 |
| 08 | `2026-11-05-paymob-billing-08-frontend.md` | All UI: plans, checkout return, billing settings, usage meter, estimate range, usage history, receipts, auto top-up, teacher seats and assistants, admin dashboard | none | 02–07 APIs |

Phase 08 is executed by the `designer` agent with the impeccable skill invoked. Its tasks may be
started per screen as soon as the API the screen calls is merged.

## Global constraints (every task)

- Signed commits only: `git commit -S`. Conventional messages with scopes:
  `feat(billing):`, `feat(usage):`, `feat(paymob):`, `feat(team):`, `feat(admin):`,
  `feat(web):`, `test(billing):`, `fix(...)`.
- Run `pre-commit run --all-files` and fix every failure before each commit. Use the venv
  binary: `/home/sico/Code/Lemely/.venv/bin/pre-commit`. All worktrees share one venv; run
  Python with `PYTHONPATH=$PWD` so imports resolve to this worktree's `lemely`, not another
  checkout's.
- Never run the full test suite locally (`make test` or bare `pytest`). Run only the test files
  the task touches, plus any repo lint test that scans `lemely/` (for example
  `tests/architecture/`) when the task adds modules. CI runs the full suite.
- Do not push. Do not open PRs.
- Money is integer minor units (piasters, `BIGINT`). Usage is integer units (`BIGINT`). USD LLM
  cost is `Decimal`, stored as `NUMERIC(12, 6)`.
- UUID primary keys with `server_default=sa.text("gen_random_uuid()")`, Postgres enums,
  `TimestampMixin` from `lemely.db.models.enums`, as in existing models.
- `lemely/db/models/*` never imports `lemely.core` (existing rule; mirror enums instead and pin
  them with a test, as `study_plan.py` does). Import-linter contracts in `pyproject.toml` must stay
  green.
- Paymob secret key, API key and HMAC secret are read on the server only. Never log them. Never
  send them to the browser. Only the public key and per-intention client secret reach the browser.
- Settings use the existing pydantic `Settings` in `lemely/runtime/config.py`; env prefix
  `LEMELY_PAYMOB__*`.
- Every webhook state change happens in one DB transaction; return 200 only after commit.
- No placeholder code: no `TODO`, no `pass` bodies, no `test.skip`, no stub tests.

## Shared contracts

Names below are fixed. Later phases import them exactly as written.

### Phase 01 — usage ledger

`lemely/db/models/usage.py`:

- Enums: `GrantKind` (`period_allowance`, `seat_allowance`, `signup`, `credit_pack`,
  `auto_topup`, `refund`, `adjustment`), `UsageJobStatus` (`open`, `settled`, `released`,
  `expired`), `UsageEntryKind` (`grant`, `hold`, `release`, `settle`, `expire`, `refund`,
  `adjust`, `debt`, `debt_repay`), `EstimatorInputKind` (`pages`, `marks`, `questions`, `none`).
- Models: `UsageGrant`, `UsageJob`, `UsageEntry`, `UsageGrantBalance`, `UsageDebt`, `UsageRate`,
  `UsageEstimator`. Columns exactly as spec §4.1 and §4.5. `UsageGrant.payment_id`,
  `subscription_period_id` and `teacher_member_id` are plain nullable UUID columns in 0052; their
  foreign keys are added by the migrations that create the target tables (0053, 0055, 0054).

`lemely/core/usage_types.py` (pure, no DB):

```python
class GrantScope(StrEnum):
    ALLOWANCE = "allowance"   # visible=False, teacher_member_id IS NULL
    CREDITS = "credits"       # visible=True
    SEAT = "seat"             # kind=seat_allowance AND teacher_member_id = Payer.teacher_member_id

@dataclass(frozen=True)
class Payer:
    owner_user_id: UUID
    scope: GrantScope
    teacher_member_id: UUID | None = None   # SEAT grants, and cap accounting
    cap_units: int | None = None            # None = no cap
    cap_window_start: datetime | None = None  # None with a cap = lifetime ("total")
    debt_exempt: bool = False               # True only for SEAT payers

@dataclass(frozen=True)
class EstimatorParams:
    version: int
    input_kind: str
    base_low: int
    base_high: int
    per_input_low: int
    per_input_high: int
```

`lemely/core/usage_pricing.py` (pure, no DB):

```python
GRANT_PRIORITY: Mapping[str, int]  # period_allowance/seat_allowance 10, signup 20, refund 30,
                                   # credit_pack/auto_topup 50, adjustment 40
def usd_to_units(cost_usd: Decimal, units_per_usd: int) -> int          # ceil, >= 0
def estimate_range(params: EstimatorParams, input_count: int) -> tuple[int, int]
def prorate_minor(amount_minor: int, period_start: datetime, period_end: datetime,
                  now: datetime) -> int                                   # ceil, clamps 0..amount
def prorate_units(units: int, period_start: datetime, period_end: datetime,
                  now: datetime) -> int
```

`lemely/db/usage_ledger_repo.py`:

```python
class InsufficientBalance(Exception): ...
class UsageLedger:
    def __init__(self, session: Session) -> None
    def issue_grant(self, *, owner_user_id: UUID, kind: GrantKind, units: int,
                    idempotency_key: str, expires_at: datetime | None,
                    visible: bool, effective_at: datetime | None = None,
                    payment_id: UUID | None = None,
                    subscription_period_id: UUID | None = None,
                    teacher_member_id: UUID | None = None) -> UsageGrant
        # idempotent on (owner_user_id, idempotency_key); repays the owner's debts first (§5.8)
    def available(self, payers: Sequence[Payer], *, now: datetime) -> int
    def has_debt(self, owner_user_id: UUID) -> bool
    def reserve(self, *, job_id: UUID, actor_user_id: UUID, action: str,
                payers: Sequence[Payer], estimate_low: int, estimate_high: int,
                estimator_version: int, rate_version: int,
                teacher_member_id: UUID | None, expires_at: datetime,
                now: datetime) -> UsageJob             # raises InsufficientBalance
    def settle(self, job_id: UUID, *, actual_cost_usd: Decimal, now: datetime) -> UsageJob
    def release(self, job_id: UUID, *, now: datetime) -> UsageJob
    def expire_stale_jobs(self, *, now: datetime) -> int
    def expire_grants(self, *, now: datetime) -> int
    def claw_back_grant(self, grant_id: UUID, *, reason: str, now: datetime) -> int
    def adjust(self, *, owner_user_id: UUID, units: int, reason: str,
               idempotency_key: str, now: datetime) -> None   # +units grant / -units debit
    def forgive_debt(self, owner_user_id: UUID, *, units: int | None, reason: str,
                     now: datetime) -> int
    def reconcile_balances(self) -> list[tuple[UUID, int, int]]  # (grant_id, cached, actual)
    def meter_fraction(self, owner_user_id: UUID, *, teacher_member_id: UUID | None,
                       now: datetime) -> float | None
```

The payer chain passed to `reserve` and `available` is ordered; the last payer is the payer of
last resort (debt owner). Phase 01 does not build chains; Phase 04 does.

### Phase 02 — payments core

- `lemely/runtime/config.py`: `PaymobSettings` (`secret_key`, `public_key`, `api_key`,
  `hmac_secret`, `card_integration_id`, `moto_integration_id`, `apple_pay_integration_id`
  (optional), `api_base="https://accept.paymob.com"`,
  `checkout_base="https://eg.checkout.paymob.com"`, `notification_base_url`,
  `redirection_base_url`), exposed as `Settings.paymob`.
- `lemely/io/paymob/client.py`: `PaymobClient` with `create_intention`, `inquire_by_order_ref`,
  `inquire_by_transaction`, `refund`, `void`, `create_plan`, `get_subscription`,
  `update_subscription`, `suspend_subscription`, `resume_subscription`,
  `cancel_subscription`, `last_transaction`, `pay_with_token`. Phase 02 implements and tests all
  of them against recorded fixtures (subscription and MOTO calls are used later).
- `lemely/io/paymob/hmac.py`: `verify_transaction_hmac(obj: Mapping, received: str, secret: str)
  -> bool`, `verify_token_hmac(...)`, `verify_subscription_hmac(trigger_type: str, sub_id: int,
  received: str, secret: str) -> bool`.
- `lemely/db/models/billing.py` (extend): `PaymentPurpose` (`subscription_first`,
  `subscription_renewal`, `upgrade_proration`, `extra_seats`, `credit_pack`, `auto_topup`),
  `PaymentStatus`, `Payment`, `PaymobEvent`, `SavedCard`, `CreditPack`; `PlanTier` and
  `Subscription` gain every column in spec §4.1 and §4.3 (lifecycle code that uses them lands in
  Phase 05).
- `lemely/db/billing_repo.py`:

```python
PaidHandler = Callable[[Session, Payment, Mapping[str, Any]], None]
def register_paid_handler(purpose: PaymentPurpose, handler: PaidHandler) -> None
class BillingService:
    def __init__(self, session: Session, client: PaymobClient, settings: PaymobSettings) -> None
    def create_pack_checkout(self, *, payer_user_id: UUID, beneficiary_user_id: UUID,
                             credit_pack_id: UUID) -> CheckoutResult  # (payment_id, checkout_url)
    def create_intention_checkout(self, *, payment: Payment, items: Sequence[Mapping],
                                  billing_data: Mapping, subscription_plan_id: int | None
                                  ) -> CheckoutResult
    def apply_transaction_callback(self, obj: Mapping[str, Any]) -> None
        # verify amount/currency/state, record event, mark paid, dispatch handler by purpose
    def apply_token_callback(self, obj: Mapping[str, Any]) -> None
    def reconcile_pending(self, *, now: datetime) -> int
```

  Phase 02 registers the `credit_pack` handler (12-month `credit_pack` grant, visible).
  Phases 05 and 06 register the other purposes.
- Routers: `lemely/web/routers/billing.py` (prefix `/api/billing`), `lemely/web/routers/
  paymob_webhooks.py` (prefix `/api/webhooks/paymob`). Parent purchase authorization uses the
  existing `parent_child_links` relationship.
- Sweeper job names (dedupe-keyed, as in `lemely/web/scheduled_notifications.py`):
  `billing.reconcile_pending`.

### Phase 03 — teacher team

- `lemely/db/models/team.py`: `TeacherMemberKind` (`student_seat`, `assistant`),
  `TeacherMemberStatus` (`active`, `leaving`, `removed`), `AssistantRole` (`co_teacher`,
  `marker`, `viewer`), `CapPeriod` (`month`, `total`), `TeacherMember` (spec §4.4).
- `lemely/core/team_permissions.py`: `TeamPermission` StrEnum (`mark`, `regrade`,
  `generate_quiz`, `manage_classes`, `view_results`, `manage_students`, `view_usage`),
  `PRESET_PERMISSIONS: Mapping[AssistantRole, frozenset[TeamPermission]]`,
  `effective_permissions(role, overrides: Mapping[str, bool]) -> frozenset[TeamPermission]`.
  Billing and seats are never permissions.
- `lemely/db/teacher_team_repo.py`:

```python
class NoFreeSeat(Exception): ...
class TeacherTeamService:
    def seat_capacity(self, teacher_user_id: UUID) -> int     # included + extra; 0 if no live plan
    def claim_seat_for_class_join(self, *, student_user_id: UUID, class_id: UUID,
                                  now: datetime) -> TeacherMember   # raises NoFreeSeat
    def seats_for_student(self, student_user_id: UUID) -> list[TeacherMember]  # active+leaving, oldest first
    def set_scope(self, member_id: UUID, *, subjects: list[str], actions: list[str]) -> None
    def set_cap(self, member_id: UUID, *, cap_units: int | None, cap_period: CapPeriod) -> None
    def request_removal(self, member_id: UUID, *, now: datetime) -> None   # leaving, leaves_at = month end
    def release_due(self, *, now: datetime) -> int
    def create_assistant_invite(self, teacher_user_id: UUID, *, role: AssistantRole,
                                expires_at: datetime) -> Invite
    def redeem_assistant_invite(self, *, code: str, user_id: UUID, now: datetime) -> TeacherMember
    def assistant_membership(self, assistant_user_id: UUID, teacher_user_id: UUID
                             ) -> TeacherMember | None
```

- `lemely/web/deps.py`: `require_team_permission(perm: TeamPermission)` resolves the acting
  teacher (lead teacher themselves, or an active assistant with the permission) and returns
  `TeamActor(actor_user_id, lead_teacher_user_id, member_id | None)`.
- Action names used in `scope_actions` and metering are the `MeteredAction` values from Phase 04
  (listed below so Phase 03 can validate them).

### Phase 04 — metering

- `lemely/core/metered_actions.py`: `MeteredAction` StrEnum: `mark_paper`, `regrade`,
  `generate_quiz`, `preview_quiz`, `self_review`, `study_plan`, plus one value per other
  LLM-backed route found by the Phase 04 audit task. Each value declares whether it has a
  subject.
- `lemely/io/llm/cost_meter.py`: contextvar accumulator `cost_scope()` context manager and
  `record_llm_cost(cost_usd: Decimal)`; called wherever per-call cost is computed
  (`lemely/io/llm/pricing.py` call sites, covering both the Claude and Gemini providers).
- `lemely/core/payer_chain.py`: `build_payer_chain(ctx: ChainContext) -> list[Payer]`, pure, from
  a `ChainContext` (actor, action, subject, seats, assistant membership, cap usage).
- `lemely/web/usage.py`: `UsageMeter.job(...)` context manager (works across SSE generators),
  `require_usage(action: MeteredAction)` dependency returning `UsageGrantContext`, 402 body
  `{"error": "usage_blocked", "reason": <reason>, "estimate": [low, high]}` with reasons
  `usage_limit_reached`, `no_active_plan`, `insufficient_credits`, `outstanding_debt`,
  `out_of_seat_scope`.
- Routes: `POST /api/usage/estimate`, `GET /api/usage/meter`, `GET /api/usage/history`.
- Sweeper jobs: `usage.expire_stale_jobs`, `usage.expire_grants`, `usage.reconcile_balances`.

### Phase 05 — subscriptions

- `lemely/db/subscription_repo.py`: `SubscriptionService` (`create_subscription_checkout`,
  `apply_renewal_webhook`, `mark_past_due`, `expire_overdue`, `schedule_downgrade`,
  `schedule_cancel`, `apply_period_end_changes`, `check_drift`); registers paid handlers for
  `subscription_first` and `subscription_renewal`.
- `lemely/db/seat_allowance_repo.py`: `grant_monthly_seat_allowances(now) -> int`,
  `grant_seat_allowance_on_claim(member_id, now) -> UsageGrant | None`.
- Sweeper jobs: `subscriptions.expire_overdue`, `subscriptions.period_end`,
  `subscriptions.drift_check`, `seats.monthly_allowance`, `seats.release_due`.

### Phase 06 — merchant charges

- `lemely/db/merchant_charge_repo.py`: `MerchantChargeService.charge_saved_card(payment,
  card) -> None` (MOTO intention + `pay_with_token`, inquiry before any retry);
  `upgrade(...)`, `add_extra_seats(...)`, `schedule_seat_reduction(...)`,
  `maybe_enqueue_auto_topup(owner_user_id, now)`; registers paid handlers for
  `upgrade_proration`, `extra_seats`, `auto_topup`.
- Sweeper jobs: `billing.auto_topup`, `billing.extra_seat_renewal_charge` (fallback path only).

### Phase 07 — admin backend

- `lemely/db/models/admin_audit.py`: `AdminAuditLog` (spec §4.7, append-only trigger).
- `lemely/db/admin_billing_repo.py`: `audited(session, admin_user_id, action, target_kind,
  target_id, reason, before, after)` helper used by every admin money action.
- Router: `lemely/web/routers/admin_billing.py`, prefix `/api/admin/billing`, all routes
  `require_role(platform_admin)`.

## Reconciliation decisions (override the contracts above and any phase plan)

Recorded after all eight phase plans were drafted. Where a phase plan disagrees with a decision
below, the decision wins.

- **R1 Prefix.** Every route lives under `/api`: `/api/billing`, `/api/webhooks/paymob`,
  `/api/usage`, `/api/teacher/team`, `/api/admin/billing`.
- **R2 Test commands.** Every pytest command carries `--no-cov` (the repo's
  `--cov-fail-under=70` fails any subset run).
- **R3 Route ownership.** Backend plans own paths and shapes; Phase 08 matches them exactly.
  Routes the frontend needs that no draft had are added by these owners:
  - Phase 02: `GET /api/billing/cards` (payer's saved cards, masked only).
  - Phase 03: `DELETE /api/teacher/team/invites/{invite_id}` (revoke an unredeemed assistant
    invite).
  - Phase 05: `GET /api/billing/summary?beneficiaryId=` (plan, period, usage meter, credits with
    expiry, debt, and for teachers seat capacity and use).
  - Phase 06: `POST /api/billing/subscriptions/{id}/upgrade/quote` and
    `POST /api/billing/subscriptions/{id}/seats/quote` (prorated amount, no side effects).
- **R4 Assistant billing.** Assistant work is always charged to the lead teacher, resolved through
  Phase 03's `require_team_permission` / `TeamActor` (acting-teacher header). The assistant's own
  balance never pays for team work. Applies to upload, regrade and quiz generation alike.
- **R5 Enforcement switches.** `enforce_teacher_seats` (Phase 03) and `usage.enforce` (Phase 04)
  default to **on** in `Settings`. Only the test suite turns them off (conftest). Each owning
  phase adds a test that the app built from default settings enforces.
- **R6 Renewal seat changes.** Phase 05 alone applies `pending_extra_seats` at renewal, and its
  `next_renewal_amount` is the single source of the expected renewal amount (drift check and
  mismatch check). Phase 06 does not apply seat reductions itself; it schedules them and runs the
  fallback charge. Any phase that changes a subscription amount at Paymob also sets
  `subscriptions.paymob_amount_minor` in the same transaction.
- **R7 `billing` notification type** is created in `0055` (Phase 05). `0056` does not add it.
- **R8 One live subscription index** is created in `0053` (Phase 02: per user, where
  `payer_user_id IS NOT NULL`). `0055` does not recreate it.
- **R9 `sync_paymob_plan(session, client, settings, plan_tier_id, *, force_new=False) -> int`**
  is owned by Phase 05. Phase 07 calls it and adds the synced-price and synced-frequency stamps
  (its `0057` columns) inside that helper.
- **R10 Migration tests.** Phase 01 replaces the "0051 is head" assertions with a check that
  survives later migrations. Later phases assert only that their own revision is in the history
  and round-trips; none asserts it is head.
- **R11 Free allowances** are the inactive `signup_student` / `signup_teacher` rows in
  `credit_packs` (Phase 04). Phase 02's CHECK allows `price_minor >= 0`, and the public catalogue
  lists active packs only.
- **R12 Seat actions.** Phase 03 creates `MeteredAction` with `has_subject` and `seat_eligible`
  and exports `SEAT_ACTIONS`; scope validation uses `SEAT_ACTIONS`. Phase 04 adds `mark_quiz`
  and `generate_flashcards`.
- **R13 Seat grants never repay the student's own debt** (Phase 01 behaviour; spec updated).
- **R14 Lock order.** Owner locks first in global user-id order, then grant rows in chain order
  (Phase 01; spec updated).
- **R15 Complimentary subscriptions.** Phase 05's period-end, overdue and drift queries skip rows
  with no `paymob_subscription_id`; Phase 07's `admin.expire_manual_subscriptions` ends those.
- **R16 Accepted deviations.** Prorated upgrade allowance (Phase 06); auto top-up settings keyed
  by beneficiary with a payer owner (Phase 06); flat estimate range for marking, no page count
  (Phase 04); 30- and 360-day periods (Phase 05); `usage_jobs.payer_chain` JSONB (Phase 01);
  extra `0057` tables (Phase 07).

- **R17 Seat actions (final).** `SEAT_ACTIONS` = `mark_paper`, `self_review`, `study_plan`,
  `mark_quiz`, `generate_flashcards`. `study_plan` is off by default on new seats.
- **R18 Hidden allowances in history.** `GET /api/usage/history` reports allowance and seat
  usage as a percentage of the plan and credit usage in credits; it never returns allowance
  unit counts.
- **R19 Fallback path.** `PaymobSettings.subscription_amount_updatable` (added in Phase 05)
  defaults to `True`. When `False`, upgrades, downgrades and seat reductions are refused;
  extra seats are charged on each renewal by Phase 06's job; cancel still works.

## Accepted gaps (not built in this programme)

- No public pricing page: the catalogue route requires sign-in.
- Parents see a child's plan, meter, credits and debt (billing summary) but not the child's
  per-job usage history.
- Estimates name the payer generically ("your seat", "your plan"), not by teacher name.
- Receipts and admin payment rows carry no card or party names; the margin report has no
  per-month series.
- Error bodies use three shapes across phases (plain string, `{code, message}`,
  `{error, message}`); the frontend adapter accepts all three.

## Execution notes

- One fresh subagent per task. The implementer sees only its task plus this index's contracts.
- Parallel agents share one git index: give each agent its file set up front and require
  `git commit -S -- <paths>`.
- Review each task at its commit SHA, not from the working tree.
- After the last task of a phase, run that phase's touched test files and pre-commit once more
  on the final tree.

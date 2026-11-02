# Paymob billing: subscriptions, teacher credits and usage metering — design

**Date:** 2026-11-02
**Status:** Design approved in brainstorming; awaiting spec review
**Branch:** `feat/paymob-integration` (worktree off `develop` at `cdc814b5`)
**Scope:** Sub-projects A (payments core + credits) and C (subscriptions). Sub-project B (paid
tutor sessions and tutor payouts) is a separate, later spec.
**Research:** `docs/billing/research/01`–`08` (Paymob docs, payouts/fees/legal, AI and edu
pricing mechanics, Egypt payment mechanics, credit-ledger patterns). Claims below that depend on
Paymob behaviour cite those files.

---

## 1. Goal

Let Lemely charge money through Paymob (Egypt, EGP) and bound LLM spend per user:

- Students pay for a subscription. A hidden monthly LLM-cost allowance limits their usage.
- Teachers pay for a subscription, for credits, or for both. Credits cover usage beyond the plan
  allowance.
- Every LLM-backed action is metered at actual LLM cost through one usage ledger.

Today no payment code exists. `PlanTier` and `Subscription` exist
(`lemely/db/models/billing.py`), but activation is a manual platform-admin toggle. Marking has no
usage limit. The product is pre-launch with no real users, so no data migration is needed beyond
seed data.

## 2. Product rules

### 2.1 Students

- Students use subscriptions only. They never hold credits.
- At launch, subscriptions are paid by card only and always auto-renew (Paymob recurring is
  card-only, research 02 §6). Prepaid wallet periods are a later follow-up.
- Billing intervals: monthly and yearly.
- A student or a linked parent can buy the subscription. When a parent pays, the subscription is
  attached to the chosen child (the beneficiary). The parent (the payer) owns billing: card,
  cancel and receipts. The student sees only their plan and usage meter.
- Each tier carries a hidden monthly allowance in usage units. The student sees a usage meter
  ("Usage 63%, resets 14 Nov") and nothing else about cost.
- At 100% the student is blocked until the period resets or they upgrade. Students have no extra
  usage.
- A new student gets a one-time free allowance (about two papers' worth, admin-configurable). No
  card is needed. One per verified account.
- An active school seat counts as a subscription at the tier flagged `is_seat_default`. Schools
  are billed outside Paymob, as today.

### 2.2 Teachers

- A teacher can use a subscription, credits, or both.
- A teacher subscription works like a student one (hidden allowance, usage meter).
- With both, usage beyond 100% of the allowance draws from visible credits instead of blocking.
- Credits come from prepaid packs bought by card (Apple Pay after go-live).
- Optional auto top-up: when visible credits fall below a threshold, a saved card is charged for a
  chosen pack, subject to a monthly spend cap.
- Pay-as-you-go (postpaid) is deferred.
- Purchased credits expire 12 months after purchase. There are no cash refunds. Failed jobs refund
  automatically as credits.
- A new teacher gets one-time promotional signup credits that expire after 30 days.

### 2.3 Metering (every LLM-backed action)

- Metered actions include paper marking (student and teacher), regrade, quiz generation and
  preview, self-review, study plans, and any other action that calls an LLM.
- When the job starts, Lemely reserves an internal hold. When the job finishes, it charges the
  actual LLM cost converted to units and releases the rest.
- No estimate is shown before the action. A receipt and usage history are shown after it.
- The charge never exceeds the hold. Lemely absorbs any overrun and records it. Balances never go
  negative.
- Failed jobs and inputs rejected before any model call cost nothing.
- The balance is shown as abstract "credits" (teachers only), with no paper-equivalent
  translation.

### 2.4 Subscription lifecycle

- An upgrade applies immediately. The prorated price difference is charged at once, and the
  allowance difference is granted at once.
- A downgrade or cancel takes effect at period end. Access continues until then.
- A failed renewal gets 3 days of grace while Paymob retries. After that the plan lapses.
- Unused allowance expires at period end. There is no rollover.

### 2.5 Payments

- Launch accepts cards (Visa/Mastercard, 3DS) through Paymob Unified Checkout (hosted).
- Apple Pay is designed in but enabled only after go-live. It has live integration IDs only and
  needs an Apple Developer account and certificates (research 01 §4.3).
- Not in this release: mobile wallets, kiosk, BNPL, InstaPay.
- Prices, allowance sizes, pack sizes and unit rates are admin-configured data, not code. Pricing
  is still undecided.

### 2.6 Out of scope

Tutor session payments and payouts (sub-project B), prepaid wallet periods, pay-as-you-go, school
billing through Paymob, Pixel (embedded) checkout, mobile SDKs.

## 3. Architecture

Approach chosen: **one usage ledger for everyone (A) + Paymob's subscriptions module for renewals
(Y).** Rejected alternatives: two separate systems for student counters and teacher wallets
(duplicated metering, bridge bugs); Lemely-run renewals through merchant-initiated charges (kept
only for upgrade and auto top-up charges); a bought billing engine such as Lago (no Paymob
support, no reserve/settle, AGPL; research 08 §3).

The usage ledger knows nothing about Paymob, and the Paymob client knows nothing about credits.
Only the billing service joins them: a verified payment creates a ledger grant.

| Unit | Location | Responsibility |
|---|---|---|
| `PaymobClient` | `lemely/io/paymob/client.py` | Thin `httpx` client with no business logic. Covers Intention create (one-off, and with `subscription_plan_id`); auth token from the API key, cached under 1 hour; transaction inquiry by ID and by `merchant_order_id`; refund and void; subscription plans and subscriptions (create, PUT, suspend, resume, cancel, `last-transaction`); merchant-initiated pay (`POST api/acceptance/payments/pay` with a card token). |
| HMAC | `lemely/io/paymob/hmac.py` | Pure verification functions for transaction callbacks (20 fields, SHA-512, `hmac` in the query string), card-token callbacks (8 fields) and subscription callbacks (`"{trigger_type}for{id}"`, `hmac` in the body). Constant-time comparison; `None` becomes `""`; booleans become `true`/`false` (research 02 §2). |
| Settings | `PaymobSettings` in `lemely/runtime/config.py` | Env `LEMELY_PAYMOB__*`: secret key, public key, API key, HMAC secret, card / MOTO / Apple Pay integration IDs, API base `https://accept.paymob.com`, checkout base `https://eg.checkout.paymob.com`. Deployed as GitHub secrets, then Cloud Run env, as for existing secrets. |
| Usage pricing | `lemely/core/usage_pricing.py` | Pure: USD cost to units under a versioned rate; hold size per action; proration; spend order. No DB. |
| Usage ledger | `lemely/db/usage_ledger_repo.py` | Grants, holds, append-only entries; reserve / settle / release / expire under row locks taken in spend order. |
| Billing | `lemely/db/billing_repo.py` | Plans, packs, payments, subscriptions, periods, saved cards, auto top-up settings; turns verified payments into grants. |
| Metering hook | `UsageMeter` + contextvar cost accumulator in `lemely/io/gemini.py` | `with meter.job(owner, action):` reserves on entry, settles the accumulated actual cost on normal exit, releases on exception. The accumulator is fed where per-call cost is already computed (`_row_cost`). It must work inside SSE `StreamingResponse` generators: the job spans the generator, not the handler return. |
| Entitlement | FastAPI dependency `require_usage(action)` | Resolves the billing owner: self, a subscription paid by a parent, or a school seat. Checks plan state and available balance against the action's hold size. Returns 402 with a machine-readable reason (`usage_limit_reached`, `no_active_plan`, `insufficient_credits`). |
| Routers | `lemely/web/routers/billing.py`, `lemely/web/routers/paymob_webhooks.py` | Catalogue, checkout create, subscription manage, auto top-up settings, usage meter, receipts; transaction and subscription webhooks. |
| Jobs | Existing in-process sweeper, made idempotent with dedupe keys (as in `scheduled_notifications.py`) | Reconcile pending payments, expire stale holds, expire grants, run auto top-up, check subscriptions daily against Paymob, send expiry and renewal emails through the existing outbox. |
| Admin | Extend `lemely/web/routers/admin.py` and the admin UI | Edit plans, packs and rates; manual grant or adjustment with a required reason; payment lookup; refund or void. |
| Frontend | `web/` | Plans page, checkout redirect and return-status page, billing settings (student, parent, teacher), usage meter, teacher credit balance with expiry breakdown, receipts history, auto top-up settings. **All UI work goes to the `designer` agent with the impeccable skill invoked.** |

## 4. Data model (Alembic `0052`)

UUID primary keys (`gen_random_uuid()`), Postgres enums, `TimestampMixin`, matching the existing
models. Money is integer minor units (piasters). Usage is integer units (`BIGINT`).

### 4.1 Catalogue (admin-edited)

- **`plan_tiers` (extend).** Add `audience` (`student` | `teacher`), `allowance_units`
  (per period), `paymob_plan_id`, `is_active`, `is_seat_default`. Each row is one tier at one
  interval, so monthly and yearly variants are separate rows, each with its own Paymob plan
  (frequency 30 or 360). Keep `code`, `name`, `price_minor`, `currency`, `interval`, `features`.
- **`credit_packs`.** `code` (unique), `name`, `units`, `price_minor`, `currency`, `is_active`.
- **`usage_rates`.** Versioned. `version`, `action`, `units_per_usd`, `hold_units`,
  `effective_from`. Unique `(version, action)`. Every ledger entry records the `rate_version` it
  used.

### 4.2 Money

- **`payments`.**
  - Parties and purpose: `payer_user_id`, `beneficiary_user_id`, `purpose`
    (`subscription_first` | `subscription_renewal` | `upgrade_proration` | `credit_pack` |
    `auto_topup`).
  - Links: `plan_tier_id` / `credit_pack_id`.
  - Amount and state: `amount_minor`, `currency`, `status` (`created` | `pending` | `paid` |
    `failed` | `failed_mismatch` | `refunded` | `partially_refunded` | `voided`).
  - Paymob references: `special_reference` (unique; our ID sent to Paymob), `paymob_intention_id`,
    `paymob_order_id` (unique), `paymob_txn_id` (unique).
  - Audit: `method`, `last_callback` (JSONB), `paid_at`.
- **`paymob_events`.** Every verified callback, stored once. `kind` (`transaction` | `token` |
  `subscription`), `dedupe_key` (unique: txn ID plus state flags, or subscription ID plus trigger
  plus `paymob_request_id`), `payload` (JSONB), `processed_at`.
- **`saved_cards`.** `user_id`, `token` (encrypted at rest), `masked_pan`, `brand`, `is_active`.

### 4.3 Subscriptions

- **`subscriptions` (extend).**
  - Parties: `payer_user_id`, plus the existing `user_id` kept as the beneficiary.
  - Status: extend the enum to `pending_first_payment` | `active` | `past_due` | `cancelled` |
    `expired`, keeping `inactive` and `rejected` for the existing manual-activation path.
  - Plan change and period: `cancel_at_period_end`, `pending_plan_tier_id`,
    `current_period_start`, `current_period_end` (exists), `grace_until`.
  - Paymob link and concurrency: `paymob_subscription_id` (unique), `version` (optimistic lock
    against webhook races).
  - One live subscription per beneficiary per audience: a partial unique index on status
    `pending_first_payment`, `active` or `past_due`.
- **`subscription_periods`.** `subscription_id`, `period_start`, `period_end`, `payment_id`.
  Unique `(subscription_id, period_start)`. This guarantees one allowance grant per period.

### 4.4 Usage ledger

The owner is the user whose actions consume the units: the student, or the teacher.

- **`usage_grants`.**
  - Owner and type: `owner_user_id`, `kind` (`period_allowance` | `seat_allowance` | `signup` |
    `credit_pack` | `auto_topup` | `refund` | `adjustment`), `visible` (false for allowances,
    true for credits).
  - Amount and validity: `priority`, `units` (> 0), `effective_at`, `expires_at` (nullable).
  - Links: `payment_id`, `subscription_period_id`.
  - Idempotency: `idempotency_key`, unique `(owner_user_id, idempotency_key)`.
- **`usage_holds`.**
  - Job: `owner_user_id`, `job_id` (unique), `action`.
  - Amounts: `reserved`, `charged`, `absorbed`, `actual_cost_usd`, `rate_version`.
  - State: `status` (`open` | `settled` | `released` | `expired`), `expires_at`, `settled_at`.
  - These rows double as receipts.
- **`usage_entries`.** Append-only. A trigger rejects UPDATE and DELETE. `grant_id`, `hold_id`,
  `kind` (`grant` | `hold` | `release` | `settle` | `expire` | `refund` | `adjust`), signed
  `units`, `rate_version`, `event_at`, `idempotency_key`, unique
  `(grant_id, idempotency_key, kind)`.
- **`usage_grant_balances`.** A cache: `grant_id`, `remaining`, `held`, with CHECK
  `0 <= held <= remaining`. A nightly job rebuilds it from `usage_entries` and alerts on drift.

**Spend order** (reserve and settle use the same order, which also fixes lock order and avoids
deadlocks): `priority` ascending, then `expires_at` ascending with never-expiring last, then
`effective_at`, then `id`.

Default priorities:

| Grant kind | Priority |
|---|---|
| `period_allowance` / `seat_allowance` | 10 |
| `signup` | 20 |
| `refund` | 30 |
| `credit_pack` / `auto_topup` | 50 |

**Usage meter** = `(units − remaining)` ÷ `units` of the current `period_allowance` (or
`seat_allowance`) grant.

**Teacher extra usage** needs no special code: once the allowance grant is empty, spend order
falls through to visible credits. Students have no visible grants, so they receive a 402.

### 4.5 Teacher settings

- **`auto_topup_settings`.** `user_id` (unique), `enabled`, `threshold_units`, `credit_pack_id`,
  `saved_card_id`, `monthly_cap_minor`.

## 5. Flows

### 5.1 Subscribe (card)

1. `POST /billing/checkout {plan_tier_id, beneficiary_id?}`.
   - The server checks the audience matches the role, and for a parent checks the
     `parent_child_links` relationship to the beneficiary.
   - It rejects the request if the beneficiary already has a live subscription for that audience.
   - It prices the purchase from `plan_tiers` on the server, then inserts
     `payments(created)` and `subscriptions(pending_first_payment)`.
2. Create the Paymob Intention: `amount`, `currency=EGP`, card integration ID, one item, billing
   data from the payer profile (first and last name, email and phone are required; research 01
   §2.1), `subscription_plan_id`, `special_reference=payments.id`, `notification_url`,
   `redirection_url`, `expiration=3600`.
3. Return the Unified Checkout URL
   `https://eg.checkout.paymob.com/?publicKey=…&clientSecret=…`. The browser redirects there, and
   Paymob hosts 3DS.
4. Paymob sends the transaction callback (POST) to `/webhooks/paymob/transaction?hmac=…`. Lemely:
   1. verifies the HMAC;
   2. loads the payment by `obj.order.merchant_order_id`;
   3. checks `amount_cents` and `currency` against the payment row;
   4. requires `success = true`, `pending = false`, `is_voided = false`,
      `is_refunded = false` and `error_occured = false`.
   In one transaction it then:
   - records the `paymob_events` row;
   - marks the payment `paid`;
   - activates the subscription and sets the period;
   - inserts the `subscription_periods` row;
   - creates the `period_allowance` grant expiring at `period_end`.
   It returns 200 after commit.
5. The return page polls `GET /billing/payments/{id}`. The GET redirect is never used for state
   (research 02 §1).

### 5.2 Renewal (Paymob-scheduled)

Subscription webhooks arrive at `/webhooks/paymob/subscription` with the HMAC in the body.

- **`Successful Transaction`.** The HMAC covers only `trigger_type` and `id`, so Lemely calls
  `GET subscriptions/{id}/last-transaction` and checks the real charge. It then records a
  `subscription_renewal` payment and inserts the next `subscription_periods` row and allowance
  grant. The period uniqueness constraint makes duplicate webhooks harmless.
- **`Failed Transaction`.** Set `past_due` and `grace_until = now + 3 days`. Access continues.
- **`Failed Overdue Transaction`, or grace elapsed (sweeper).** Set `expired`. No new allowance is
  granted.
- **`canceled` / `suspended`.** Mirror the state after re-fetching the subscription from Paymob.
- **Daily job.** Compare every `active` and `past_due` subscription with Paymob
  (`GET subscriptions/{id}`) and repair drift.

### 5.3 Upgrade, downgrade, cancel

- **Upgrade.**
  1. Compute proration: (new price − old price) × remaining fraction of the period.
  2. Charge it as an `upgrade_proration` payment through a merchant-initiated charge on the saved
     card (MOTO Intention, then `payments/pay` with the token).
  3. On a verified callback, PUT the Paymob subscription to the new amount and plan, switch the
     tier, and grant the allowance difference with `expires_at` = the current `period_end`.
- **Downgrade.** Set `pending_plan_tier_id`. Apply it through a Paymob PUT before the next
  renewal.
- **Cancel.** Set `cancel_at_period_end`. A sweeper cancels the Paymob subscription at period
  end. Access continues until then.

### 5.4 Credit pack (teacher)

The same as 5.1 with a one-off Intention and no `subscription_plan_id`. A verified callback
creates a `credit_pack` grant with `expires_at = paid_at + 12 months`. A card-token callback
(`type: TOKEN`) stores or refreshes `saved_cards` for auto top-up.

### 5.5 Auto top-up (teacher)

1. After each settle, check whether visible credits are below `threshold_units`, this month's
   auto-top-up spend plus the pack price is within `monthly_cap_minor`, and no `auto_topup`
   payment is in flight.
2. If so, enqueue a top-up with dedupe key `(user, threshold crossing)`.
3. The sweeper charges the saved card through a merchant-initiated charge.
4. A verified callback creates the `auto_topup` grant.
5. On failure, disable auto top-up and email the teacher through the outbox.

### 5.6 Metering

1. `require_usage(action)` resolves the owner and checks the available balance (sum of
   `remaining − held` over live grants) is at least `hold_units` for the action at the current
   rate version. If not, it returns 402.
2. `meter.job(owner, action, job_id)` reserves `hold_units` across grants in spend order, under
   `FOR UPDATE` row locks, and writes `hold` entries and an `open` hold row with
   `expires_at = now + job timeout + slack`.
3. The contextvar accumulator sums the per-call USD cost of every LLM call made inside the job.
4. On normal exit:
   - convert `actual_cost_usd` to units at the hold's rate version;
   - set `charged = min(actual, reserved)` and `absorbed = max(0, actual − reserved)`;
   - write `settle` entries for the charged amount and `release` entries for the rest;
   - mark the hold `settled`.
5. On exception, or a reject before any model call, release everything and mark the hold
   `released`.
6. Crash safety: the sweeper releases `open` holds past `expires_at`.
7. Grants that expire while held: the `expire` entry covers only `remaining − held`; held units
   resolve with their hold (research 08 §7.3).
8. Hold sizes are tuned per action from observed cost data. The rate table is admin-editable and
   versioned, so a hold that is too small costs Lemely (absorbed) and never the user.

### 5.7 Reconciliation

- A payment `created` or `pending` for more than 15 minutes is checked with transaction inquiry
  by `merchant_order_id`. Retry on a backoff schedule for up to 24 hours, then mark it `failed`.
- This covers missed callbacks (about 2% reported, research 03 §5.2) and abandoned 3DS attempts,
  which send no callback (research 02 §0).

## 6. Error handling

- **Webhooks.**
  - Verify the HMAC first; a mismatch returns 401 and is logged as an alert.
  - A duplicate `dedupe_key` returns 200 as a no-op.
  - An unknown `special_reference` returns 200 and is logged, so Paymob does not retry forever.
  - All state changes happen in one transaction, and 200 is returned only after commit.
- **Mismatch.** If amount or currency differs from the server record, mark the payment
  `failed_mismatch`, issue no grant, raise an admin alert, and refund manually.
- **No idempotency keys at Paymob** (research 02 §8). Insert our own payment or refund row
  before calling Paymob. After a timeout, query inquiry before any retry. Never retry a charge or
  refund blindly.
- **Ledger invariants.** CHECK constraints prevent negative or over-held balances. A trigger
  enforces append-only entries. A nightly reconcile compares entries with the cached balances.
- **Refunds.** Admin only, through the Paymob refund API. A refunded credit pack claws back its
  unspent units only. Spent units stay spent.
- **Paymob outage.** Checkout returns 503 with a friendly message. Metering never calls Paymob,
  so existing allowances and credits keep working.

## 7. Security

- The secret key, API key and HMAC secret are used on the server only. Only the public key and the
  per-intention client secret reach the browser.
- Saved-card tokens are encrypted at rest.
- Authorization:
  - A parent may buy only for a linked child.
  - Only the payer manages a subscription's billing.
  - The beneficiary sees plan and usage only.
  - Admin endpoints require `platform_admin`.
  - Covered by IDOR tests.
- Lemely never handles card data (hosted checkout), which keeps PCI scope minimal.
- Checkout creation is rate-limited through `lemely/web/ratelimit.py`.

## 8. Testing

TDD. Locally, run only the test files touched; CI runs the full suite.

- **Unit.**
  - HMAC: the docs' worked concatenation example, `None` handling, wallet-shaped `source_data`.
  - Subscription HMAC.
  - Pricing: USD to units, rounding.
  - Proration.
  - Spend order.
- **Repository (Postgres).**
  - Concurrent reserve on one balance: no overdraw.
  - Settle under, at and over the hold.
  - Release on failure.
  - Hold expiry.
  - Grant expiry while held.
  - Duplicate webhook.
  - Period grant cannot be issued twice.
  - Mismatch rejection.
  - Nightly balance reconcile.
- **Router.**
  - Webhook endpoints with recorded fixture payloads.
  - Checkout authorization: parent and child, IDOR.
  - 402 reasons.
  - Teacher fall-through from allowance to credits.
- **Live test account** (manual, recorded as fixtures).
  - Test card `5123456789012346` (holder "Test Account", expiry 01/39, CVV 123), through a tunnel
    to `notification_url`.
  - Capture real transaction, token and subscription callbacks.

## 9. Delivery order and Paymob dependencies

1. Card one-off checkout and webhooks (credit packs): works on the test account today.
2. Usage ledger, metering hook, entitlement, student signup allowance, seat allowance.
3. Subscriptions (Paymob plans, webhooks, lifecycle).
4. Upgrade proration and auto top-up (merchant-initiated charges).

Steps 3–4 need **MOTO enabled by Paymob**. A Paymob delay blocks only those steps.

**Ask Paymob in writing now:**

1. Enable a MOTO integration on the test account.
2. Confirm subscriptions are available for Egypt accounts.
3. Callback retry policy and source IPs.
4. The live-account path (Starter vs Registered Business) and its limits.
5. Whether Apple Pay works on hosted Unified Checkout.
6. Whether `special_reference` uniqueness is enforced.

**Open for counsel and accountant** (these do not block the build): VAT timing on prepaid credits;
Egyptian consumer refund rights for digital services; acceptability of the 12-month expiry and of
"no cash refunds" (research 08 §4).

## 10. Success criteria

- A student (or a parent for a linked child) can subscribe by card on the test account. The
  allowance appears, the usage meter moves with each LLM action, and the student is blocked at
  100% with a clear message.
- A teacher can buy a credit pack, run actions beyond their plan allowance from credits, and see
  a receipt per job with actual credits charged.
- Duplicate, missing or forged callbacks never double-grant or grant falsely (tests prove each
  case).
- Ledger reconcile shows zero drift. No balance ever goes negative under concurrent jobs.
- Renewal, failed renewal with grace, upgrade, downgrade and cancel each move the subscription
  through the documented states.

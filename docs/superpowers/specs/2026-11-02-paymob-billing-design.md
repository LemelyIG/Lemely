# Paymob billing: subscriptions, credits, teacher seats and usage metering — design

**Date:** 2026-11-02 (revised 2026-11-05)
**Status:** Revision 2 approved in brainstorming; awaiting spec review
**Branch:** `feat/paymob-integration` (worktree off `develop` at `cdc814b5`)
**Scope:** Sub-projects A (payments core + credits) and C (subscriptions and teacher seats).
Sub-project B (paid tutor sessions and tutor payouts) is a separate, later spec.
**Research:** `docs/billing/research/01`–`08` (Paymob docs, payouts/fees/legal, AI and edu
pricing mechanics, Egypt payment mechanics, credit-ledger patterns). Claims below that depend on
Paymob behaviour cite those files.

**Revision 2 changes:** students can hold credits; schools are out and teacher seats are in;
teachers can attach free assistant accounts with roles and caps; usage is charged at actual cost
with a range estimate shown first and debt allowed; receipts exist only for money paid; the admin
dashboard is specified in full.

---

## 1. Goal

Let Lemely charge money through Paymob (Egypt, EGP) and bound LLM spend per account:

- Students and teachers pay for a subscription, for credits, or for both. Credits cover usage
  beyond the plan allowance.
- Teachers lease seats to students and attach assistants. Seats come with the teacher's plan,
  and extra seats are bought per seat.
- Every LLM-backed action is charged at actual LLM cost through one usage ledger, after a range
  estimate is shown.

Today no payment code exists. `PlanTier` and `Subscription` exist
(`lemely/db/models/billing.py`), but activation is a manual platform-admin toggle. Marking has no
usage limit. The product is pre-launch with no real users, so no data migration is needed beyond
seed data.

## 2. Product rules

### 2.1 Plans and credits (students and teachers)

- A student or a teacher can use a subscription, credits, or both. Usage draws from the plan
  allowance first, then from credits. Without credits, usage stops when the allowance runs out.
- Each tier carries a hidden allowance in usage units per period. Users on allowance see a usage
  meter ("Usage 63%, resets 14 Nov"). Credits are shown as an abstract "credits" balance with an
  expiry breakdown.
- Subscriptions are paid by card only at launch and always auto-renew (Paymob recurring is
  card-only, research 02 §6). Prepaid wallet periods are a later follow-up.
- Billing intervals: monthly and yearly.
- Credits come from prepaid packs bought by card (Apple Pay after go-live).
- Optional auto top-up: when credits fall below a threshold, a saved card is charged for a chosen
  pack, subject to a monthly spend cap.
- Pay-as-you-go (postpaid) is deferred.
- Purchased credits expire 12 months after purchase. There are no cash refunds. Failed jobs cost
  nothing.
- A linked parent can buy a subscription and credit packs for a child. The child is the
  beneficiary and owns the balance. The parent is the payer: they own the card, cancellation and
  receipts. The child sees their plan, usage meter and credit balance.
- Free start: a new student gets a one-time allowance (about two papers' worth, admin-configured,
  one per verified account, no card). A new teacher gets promotional signup credits that expire
  after 30 days.

### 2.2 Teacher seats

Schools are not part of billing. A teacher leases seats to students instead.

- Each teacher tier includes N student seats. Seats beyond N are an add-on to the teacher's card
  subscription: the prorated price is charged at once, and the seat then renews with the plan.
  Removing extra seats takes effect at period end.
- Students join by invite only. A student signs up for Lemely, then enters the code of one of the
  teacher's classes (the existing class `join_code`). One class code serves a whole class. The
  first join with a teacher takes one of that teacher's seats. Joining more of the same
  teacher's classes uses the same seat.
- The teacher sets each seat's scope: the subjects and the actions the seat covers. Subjects
  default to the subjects of the teacher's classes the student joined.
- Each seat carries its own monthly allowance (set by the teacher's tier). The teacher can let a
  student overflow into the teacher's credits, up to a per-student cap.
- Spend order for a seated student's in-scope action: seat allowance, then teacher credits
  (within the cap), then the student's own allowance, then the student's own credits.
  Out-of-scope actions use only the student's own plan and credits.
- Routing is per subject. A student seated with a maths teacher and a physics teacher who
  uploads a maths paper uses the maths teacher's seat; a physics paper uses the physics
  teacher's seat. The action's subject comes from the server-side record it works on (the paper,
  quiz or class), never from client input.
- Removing a student frees the seat at the end of the current month, not at once. Seat
  allowances are monthly, so this stops seat swapping from multiplying allowances.

### 2.3 Assistants and co-teachers

- A teacher can attach any number of assistant accounts at no charge. An assistant acts as a
  teacher account one level below the lead teacher.
- Assistants join by invite only: the teacher sends an assistant invite and the assistant redeems
  it with their own Lemely teacher account.
- Permissions come from preset roles with per-permission toggles:
  - **Co-teacher:** everything except billing and seats.
  - **Marker:** mark and regrade only.
  - **Viewer:** read only.
  Billing, plan changes and seat purchases always stay with the lead teacher.
- Assistant usage draws from the lead teacher's allowance, then the lead teacher's credits,
  within a cap the teacher sets per assistant (per month or total).

### 2.4 Metering (every LLM-backed action)

- Metered actions include paper marking (student and teacher), regrade, quiz generation and
  preview, self-review, study plans, and any other action that calls an LLM.
- Before the action, the user sees an estimate as a range: "3–5 credits" when credits will pay,
  or "2–4% of your monthly plan" when an allowance will pay.
- A job starts only if the available balance across the payer chain covers the top of the range.
- When the job finishes, the user is charged the actual LLM cost converted to units, with no
  cap.
- A charge larger than the balance makes the balance negative (debt). While an account has debt,
  it cannot start new jobs that draw on its own balance. The next grant to that account pays the
  debt first: a renewal allowance, a credit pack or an auto top-up.
- Failed jobs and inputs rejected before any model call cost nothing.
- There are no receipts for usage. A usage history lists each job with its estimate range and
  actual charge.

### 2.5 Receipts

Receipts exist only for real money: a subscription, a renewal, an upgrade, extra seats, a credit
pack or an auto top-up. The payer receives them.

### 2.6 Subscription lifecycle

- An upgrade applies immediately. The prorated price difference is charged at once, and the
  allowance difference is granted at once.
- A downgrade or cancel takes effect at period end. Access continues until then. A teacher
  downgrade that leaves more seated students than seats is refused until seats are freed.
- A failed renewal gets 3 days of grace while Paymob retries. After that the plan lapses, and
  the teacher's seats stop granting allowances.
- Unused allowance expires at period end. There is no rollover.

### 2.7 Payments

- Launch accepts cards (Visa/Mastercard, 3DS) through Paymob Unified Checkout (hosted).
- Apple Pay is designed in but enabled only after go-live. It has live integration IDs only and
  needs an Apple Developer account and certificates (research 01 §4.3).
- Not in this release: mobile wallets, kiosk, BNPL, InstaPay.
- Prices, allowance sizes, seat counts, pack sizes, unit rates and estimate settings are
  admin-configured data, not code. Pricing is still undecided.

### 2.8 Out of scope

Tutor session payments and payouts (sub-project B), prepaid wallet periods, pay-as-you-go,
school billing (the existing school and school-seat code stays untouched and unused by billing),
teacher-created student accounts, Pixel (embedded) checkout, mobile SDKs.

## 3. Architecture

Approach chosen: **one usage ledger for everyone (A) + Paymob's subscriptions module for renewals
(Y).** Rejected alternatives: separate systems for allowance counters and credit wallets
(duplicated metering, bridge bugs); Lemely-run renewals through merchant-initiated charges (kept
only for upgrade, extra-seat and auto top-up charges); a bought billing engine such as Lago (no
Paymob support, no reserve/settle, AGPL; research 08 §3).

The usage ledger knows nothing about Paymob, and the Paymob client knows nothing about credits.
Only the billing service joins them: a verified payment creates a ledger grant.

| Unit | Location | Responsibility |
|---|---|---|
| `PaymobClient` | `lemely/io/paymob/client.py` | Thin `httpx` client with no business logic. Covers Intention create (one-off, and with `subscription_plan_id`); auth token from the API key, cached under 1 hour; transaction inquiry by ID and by `merchant_order_id`; refund and void; subscription plans and subscriptions (create, PUT, suspend, resume, cancel, `last-transaction`); merchant-initiated pay (`POST api/acceptance/payments/pay` with a card token). |
| HMAC | `lemely/io/paymob/hmac.py` | Pure verification functions for transaction callbacks (20 fields, SHA-512, `hmac` in the query string), card-token callbacks (8 fields) and subscription callbacks (`"{trigger_type}for{id}"`, `hmac` in the body). Constant-time comparison; `None` becomes `""`; booleans become `true`/`false` (research 02 §2). |
| Settings | `PaymobSettings` in `lemely/runtime/config.py` | Env `LEMELY_PAYMOB__*`: secret key, public key, API key, HMAC secret, card / MOTO / Apple Pay integration IDs, API base `https://accept.paymob.com`, checkout base `https://eg.checkout.paymob.com`. Deployed as GitHub secrets, then Cloud Run env, as for existing secrets. |
| Usage pricing | `lemely/core/usage_pricing.py` | Pure, no DB: USD cost to units under a versioned rate; estimate range per action from countable inputs (pages, marks, questions) and estimator settings; proration (plan and seats); spend order. |
| Usage ledger | `lemely/db/usage_ledger_repo.py` | Grants, jobs, append-only entries, debts; reserve / settle / release / expire / repay under row locks taken in a fixed order. |
| Billing | `lemely/db/billing_repo.py` | Plans, packs, payments, subscriptions, periods, extra seats, saved cards, auto top-up settings; turns verified payments into grants. |
| Teacher team | `lemely/db/teacher_team_repo.py` | Seats and assistants (`teacher_members`), scope, caps, roles and permissions; seat claim on class join; seat release at period end. |
| Metering hook | `UsageMeter` + contextvar cost accumulator in `lemely/io/gemini.py` | `with meter.job(chain, action, estimate):` reserves on entry, settles the accumulated actual cost on normal exit, releases on exception. The accumulator is fed where per-call cost is already computed (`_row_cost`). It must work inside SSE `StreamingResponse` generators: the job spans the generator, not the handler return. |
| Entitlement | FastAPI dependency `require_usage(action)` | Builds the payer chain (§5.6), checks plan state, debt and available balance against the top of the estimate range. Returns 402 with a machine-readable reason (`usage_limit_reached`, `no_active_plan`, `insufficient_credits`, `outstanding_debt`, `out_of_seat_scope`). |
| Team permissions | FastAPI dependency `require_team_permission(perm)` | Lets an assistant act on the lead teacher's resources (classes, papers, results) when their role grants `perm`. Existing teacher endpoints adopt it where an assistant may act. |
| Routers | `lemely/web/routers/billing.py`, `lemely/web/routers/teacher_team.py`, `lemely/web/routers/paymob_webhooks.py` | Catalogue, checkout, subscription and seat management, auto top-up settings, usage meter, usage history, receipts, estimates; seats, scope, caps, assistants and invites; transaction and subscription webhooks. |
| Jobs | Existing in-process sweeper, made idempotent with dedupe keys (as in `scheduled_notifications.py`) | Reconcile pending payments, release stale jobs, expire grants, grant seat allowances each period, release removed seats at period end, run auto top-up, check subscriptions daily against Paymob, send expiry and renewal emails through the existing outbox. |
| Admin | Extend `lemely/web/routers/admin.py` and the admin portal (`web/src/portals/admin/`) | See §8. |
| Frontend | `web/` | Plans page, checkout redirect and return-status page, billing settings (student, parent, teacher), usage meter, credit balance with expiry breakdown, estimate range before actions, usage history, receipts, auto top-up settings, teacher seats and assistants. **All UI work goes to the `designer` agent with the impeccable skill invoked.** |

## 4. Data model (Alembic `0052`)

UUID primary keys (`gen_random_uuid()`), Postgres enums, `TimestampMixin`, matching the existing
models. Money is integer minor units (piasters). Usage is integer units (`BIGINT`).

### 4.1 Catalogue (admin-edited)

- **`plan_tiers` (extend).** Add `audience` (`student` | `teacher`), `allowance_units`
  (per period), `paymob_plan_id`, `is_active`, and for teacher tiers `included_seats`,
  `seat_allowance_units` (per seat per month) and `extra_seat_price_minor` (per seat per
  interval). Each row is one tier at one interval, so monthly and yearly variants are separate
  rows, each with its own Paymob plan (frequency 30 or 360). Keep `code`, `name`, `price_minor`,
  `currency`, `interval`, `features`.
- **`credit_packs`.** `code` (unique), `name`, `units`, `price_minor`, `currency`, `is_active`.
- **`usage_rates`.** Versioned. `version`, `action`, `units_per_usd`, `effective_from`. Unique
  `(version, action)`. Every job and entry records the `rate_version` it used.
- **`usage_estimators`.** Versioned. `version`, `action`, `input_kind` (`pages` | `marks` |
  `questions` | `none`), `base_low`, `base_high`, `per_input_low`, `per_input_high` (units),
  `effective_from`. Seeded by hand, then tuned from observed job costs shown in the admin margin
  view (§8).

### 4.2 Money

- **`payments`.**
  - Parties and purpose: `payer_user_id`, `beneficiary_user_id`, `purpose`
    (`subscription_first` | `subscription_renewal` | `upgrade_proration` | `extra_seats` |
    `credit_pack` | `auto_topup`).
  - Links: `plan_tier_id` / `credit_pack_id` / `subscription_id`, `seat_quantity`.
  - Amount and state: `amount_minor`, `currency`, `status` (`created` | `pending` | `paid` |
    `failed` | `failed_mismatch` | `refunded` | `partially_refunded` | `voided`).
  - Paymob references: `special_reference` (unique; our ID sent to Paymob), `paymob_intention_id`,
    `paymob_order_id` (unique), `paymob_txn_id` (unique).
  - Audit: `method`, `last_callback` (JSONB), `paid_at`.
  - A `paid` payment is the receipt. No other receipt record exists.
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
  - Seats (teacher only): `extra_seats` (paid now), `pending_extra_seats` (applies at the next
    renewal; used for reductions).
  - Paymob link and concurrency: `paymob_subscription_id` (unique), `version` (optimistic lock
    against webhook races).
  - One live subscription per beneficiary per audience: a partial unique index on status
    `pending_first_payment`, `active` or `past_due`.
- **`subscription_periods`.** `subscription_id`, `period_start`, `period_end`, `payment_id`.
  Unique `(subscription_id, period_start)`. This guarantees one allowance grant per period.

### 4.4 Teacher team

- **`teacher_members`.** One row per person attached to a teacher.
  - Who: `teacher_user_id`, `member_user_id`, unique `(teacher_user_id, member_user_id)`.
  - Kind: `kind` (`student_seat` | `assistant`).
  - Seat scope: `scope_subjects` (array of `subjects.code`), `scope_actions` (array of action
    names). Null on assistants.
  - Assistant role: `role_preset` (`co_teacher` | `marker` | `viewer`), `permissions` (JSONB
    overrides of the preset). Null on seats.
  - Cap on the teacher's credits (seats) or the teacher's balance (assistants): `cap_units`
    (nullable = no overflow for seats, no limit for assistants), `cap_period` (`month` |
    `total`).
  - State: `status` (`active` | `leaving` | `removed`), `leaves_at` (end of the month in which
    removal was requested).
  - Seat count rule, checked under a row lock on the teacher's subscription: active plus leaving
    `student_seat` rows ≤ `included_seats + extra_seats`.
- **Seat claim.** Redeeming a class `join_code` (existing flow in `lemely/web/routers/invites.py`)
  creates the `student_seat` row if the student has none with that teacher, or adds the class
  subject to `scope_subjects`. No free seat means the join is refused with a message to ask the
  teacher for more seats.
- **`invites` (extend).** Add a nullable `team_teacher_id` target and an `assistant` value to
  `InviteRole`; widen `ck_invites_target` to allow it. Assistant invites are single-use and expire.

### 4.5 Usage ledger

The owner of a grant is the account whose balance it is: a student, a teacher, or (for seat
allowances) the seated student, funded by the teacher.

- **`usage_grants`.**
  - Owner and type: `owner_user_id`, `kind` (`period_allowance` | `seat_allowance` | `signup` |
    `credit_pack` | `auto_topup` | `refund` | `adjustment`), `visible` (false for allowances,
    true for credits).
  - Seat link: `teacher_member_id` (set only on `seat_allowance`; such a grant pays only for
    actions inside that seat's scope).
  - Amount and validity: `priority`, `units` (> 0), `effective_at`, `expires_at` (nullable).
  - Links: `payment_id`, `subscription_period_id`.
  - Idempotency: `idempotency_key`, unique `(owner_user_id, idempotency_key)`.
- **`usage_jobs`.** One row per metered action. This is also the usage history.
  - Who: `actor_user_id` (who ran it), `teacher_member_id` (seat or assistant context, nullable),
    `job_id` (unique), `action`.
  - Estimate: `estimate_low`, `estimate_high`, `estimator_version`.
  - Charge: `reserved`, `charged`, `debt_created`, `actual_cost_usd`, `rate_version`.
  - State: `status` (`open` | `settled` | `released` | `expired`), `expires_at`, `settled_at`.
- **`usage_entries`.** Append-only. A trigger rejects UPDATE and DELETE. `grant_id` (nullable for
  debt entries), `job_id`, `debt_id`, `teacher_member_id` (copied from the job; used for caps),
  `kind` (`grant` | `hold` | `release` | `settle` | `expire` | `refund` | `adjust` | `debt` |
  `debt_repay`), signed `units`, `rate_version`, `event_at`, `idempotency_key`, unique
  `(grant_id, idempotency_key, kind)`.
- **`usage_grant_balances`.** A cache: `grant_id`, `remaining`, `held`, with CHECK
  `0 <= held <= remaining`. A nightly job rebuilds it from `usage_entries` and alerts on drift.
- **`usage_debts`.** `owner_user_id`, `job_id`, `units` (> 0), `outstanding` (CHECK
  `0 <= outstanding <= units`). An account has debt while any row has `outstanding > 0`.

**Grant spend order** within one owner (reserve and settle use the same order, which also fixes
lock order and avoids deadlocks): `priority` ascending, then `expires_at` ascending with
never-expiring last, then `effective_at`, then `id`. Across owners, locks are taken in payer-chain
order.

Default priorities:

| Grant kind | Priority |
|---|---|
| `period_allowance` / `seat_allowance` | 10 |
| `signup` | 20 |
| `refund` | 30 |
| `credit_pack` / `auto_topup` | 50 |

**Usage meter** = `(units − remaining)` ÷ `units` of the current `period_allowance` grant, or of
the `seat_allowance` grant for in-scope work.

### 4.6 Settings

- **`auto_topup_settings`.** `user_id` (unique), `enabled`, `threshold_units`, `credit_pack_id`,
  `saved_card_id`, `monthly_cap_minor`. The payer owns it (a parent for a child).

### 4.7 Admin

- **`admin_audit_log`.** Append-only (trigger rejects UPDATE and DELETE). `admin_user_id`,
  `action`, `target_kind`, `target_id`, `reason` (required), `before` / `after` (JSONB),
  `created_at`. Every admin money or catalogue action writes one row in the same transaction.

## 5. Flows

### 5.1 Subscribe (card)

1. `POST /billing/checkout {plan_tier_id, beneficiary_id?, extra_seats?}`.
   - The server checks the audience matches the role, and for a parent checks the
     `parent_child_links` relationship to the beneficiary.
   - It rejects the request if the beneficiary already has a live subscription for that audience.
   - It prices the purchase from `plan_tiers` on the server (plan price plus
     `extra_seats × extra_seat_price_minor`), then inserts `payments(created)` and
     `subscriptions(pending_first_payment)`.
2. Create the Paymob Intention: `amount`, `currency=EGP`, card integration ID, line items, billing
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
   - creates the `period_allowance` grant expiring at `period_end`, paying any debt first (§5.8).
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
  granted, and the teacher's seats grant no new seat allowances.
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
  renewal. Refused if the new tier's seats cannot hold the active seated students.
- **Cancel.** Set `cancel_at_period_end`. A sweeper cancels the Paymob subscription at period
  end. Access continues until then.

### 5.4 Extra seats (teacher)

- **Add.** Charge `seats × extra_seat_price_minor × remaining fraction of the period` as an
  `extra_seats` payment through a merchant-initiated charge on the saved card. On a verified
  callback, raise `extra_seats` and PUT the Paymob subscription amount to plan price plus seats.
- **Remove.** Set `pending_extra_seats`. Before the next renewal, PUT the lower amount; at
  renewal, apply it. Refused if it would leave fewer seats than active seated students.
- **Fallback** if Paymob cannot change a subscription's amount (question 7 in §10): keep the Paymob
  subscription at the plan price, and charge extra seats by a merchant-initiated charge on each
  renewal success, recorded as an `extra_seats` payment. A failed seat charge gets the same 3-day
  grace; after that, extra seats drop to zero and the newest seated students move to `leaving`.

### 5.5 Credit pack and auto top-up

- **Credit pack.** The same as 5.1 with a one-off Intention and no `subscription_plan_id`. The
  payer is the user or a linked parent. A verified callback creates a `credit_pack` grant for the
  beneficiary with `expires_at = paid_at + 12 months`, paying any debt first. A card-token
  callback (`type: TOKEN`) stores or refreshes `saved_cards` for auto top-up.
- **Auto top-up.**
  1. After each settle, check whether the owner's credits are below `threshold_units`, this
     month's auto-top-up spend plus the pack price is within `monthly_cap_minor`, and no
     `auto_topup` payment is in flight.
  2. If so, enqueue a top-up with dedupe key `(user, threshold crossing)`.
  3. The sweeper charges the payer's saved card through a merchant-initiated charge.
  4. A verified callback creates the `auto_topup` grant, paying any debt first.
  5. On failure, disable auto top-up and email the payer through the outbox.

### 5.6 Payer chain

`require_usage(action)` builds an ordered list of payers. Each payer is an owner plus a grant
filter and an optional cap.

| Actor and action | Chain |
|---|---|
| Seated student, action inside a seat's scope | seat allowance (that seat's grant) → teacher credits (cap from the seat) → own allowance → own credits |
| Seated student, other action | own allowance → own credits |
| Assistant acting for a lead teacher | teacher allowance → teacher credits (cap from the assistant row) |
| Anyone else | own allowance → own credits |

- Seat selection is per subject: the chain uses the seat whose `scope_subjects` contains the
  action's subject and whose `scope_actions` contains the action. A student seated with several
  teachers therefore draws from the maths teacher for maths work and the physics teacher for
  physics work.
- If two seats cover the same subject and action, the older seat pays first. Its teacher's
  credits are not tried before the second seat's allowance: the chain is all seat allowances in
  age order, then each seat's teacher credits in the same order, then the student's own balance.
- An action with no subject (for example a cross-subject study plan) uses no seat. It draws only
  from the student's own allowance and credits.
- A payer is skipped if its owner has debt, except a `seat_allowance` grant, which stays usable
  while the student has debt on their own balance.
- A cap counts settled `usage_entries` drawn from the teacher's grants with that
  `teacher_member_id` in the cap window, plus the reserved part of open jobs.
- The **payer of last resort** is the last payer in the chain. Debt lands on that payer's owner.

### 5.7 Metering

1. The client calls `POST /usage/estimate {action, inputs}` and shows the range. The estimate
   comes from `usage_estimators` and needs no DB writes.
2. `require_usage(action)` recomputes the estimate on the server, builds the chain, and checks the
   available balance across the chain (sum of `remaining − held` over usable grants, within caps)
   is at least `estimate_high`. If not, it returns 402.
3. `meter.job(chain, action, estimate, job_id)` reserves `estimate_high` across the chain in
   order, under `FOR UPDATE` row locks, writes `hold` entries and an `open` job row with
   `expires_at = now + job timeout + slack`. The reservation stops two concurrent jobs from
   spending the same balance.
4. The contextvar accumulator sums the per-call USD cost of every LLM call made inside the job.
5. On normal exit:
   - convert `actual_cost_usd` to units at the job's rate version;
   - settle from held units first; release any held units left over;
   - if actual exceeds the reservation, keep drawing down the chain from usable grants;
   - if the chain runs dry, create a `usage_debts` row for the remainder on the payer of last
     resort and write a `debt` entry;
   - mark the job `settled` and record `charged` and `debt_created`.
6. On exception, or a reject before any model call, release everything and mark the job
   `released`.
7. Crash safety: the sweeper releases `open` jobs past `expires_at` and marks them `expired`
   (no charge; the cost is recorded for the margin view).
8. Grants that expire while held: the `expire` entry covers only `remaining − held`; held units
   resolve with their job (research 08 §7.3).

### 5.8 Debt repayment

Every new grant to an owner with debt first writes `debt_repay` entries against that owner's
`usage_debts` rows (oldest first), lowering the grant's `remaining` and the debts' `outstanding`
in the same transaction. Admins can forgive debt (§8), which writes an `adjust` entry and an audit
row.

### 5.9 Seat allowances and seat release

- At the start of each calendar month while the teacher's plan is live (monthly or yearly), and
  when a seat is claimed mid-month, the sweeper creates one `seat_allowance` grant per active
  seat. The grant is owned by the student, carries the `teacher_member_id`, and expires at the
  end of the month. A seat claimed mid-month gets an allowance prorated to the days left. Dedupe
  key: `(teacher_member_id, month_start)`.
- Removing a student sets `leaving` and `leaves_at` = the end of the current month.
  At `leaves_at` the sweeper sets `removed` and frees the seat. The current seat grant runs to its
  normal expiry.
- If the teacher's plan expires, no new seat grants are issued. Existing seat grants run to
  expiry.

### 5.10 Reconciliation

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
- **Ledger invariants.** CHECK constraints prevent negative grant balances and over-holding;
  negative account balances exist only as `usage_debts` rows. A trigger enforces append-only
  entries. A nightly reconcile compares entries with the cached balances and debts.
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
  - The beneficiary sees plan, usage and balance only.
  - Only the lead teacher manages billing, seats, caps and assistants. An assistant acts only
    within their role's permissions, and only on the lead teacher's resources.
  - A seated student's in-scope check uses the server-side seat scope, never client input.
  - Admin endpoints require `platform_admin`.
  - Covered by IDOR tests.
- Lemely never handles card data (hosted checkout), which keeps PCI scope minimal.
- Checkout creation, estimate and invite redemption are rate-limited through
  `lemely/web/ratelimit.py`.

## 8. Admin dashboard

Extends the existing admin portal. Every endpoint requires `platform_admin`. Every money or
catalogue change requires a reason and writes `admin_audit_log`. All five areas ship in the first
release. The existing **Activations** screen (manual subscription toggle) becomes one action in the
customer view, kept for complimentary accounts. The **Schools** and **Seats** screens are left
as they are.

1. **Catalogue.** Plan tiers (price, interval, allowance, included seats, seat allowance, extra
   seat price), each linked to its Paymob plan with a sync action and a drift warning. Credit
   packs, signup grants and the student free allowance. Usage rates and estimators per action.
   All versioned.
2. **Customer view.** Search by name, email or Paymob order ID. Shows subscription and period,
   grants with expiry, balance, debt, usage jobs (estimate against actual), payments and receipts,
   seats and assistants (teachers) or linked parents (students). Actions: grant credits, adjust,
   forgive debt, extend or cancel a subscription, refund or void a payment, manual activation.
3. **Payments.** Live list with status filters. A problem queue: amount mismatches, payments
   pending over an hour, missing callbacks, HMAC failures. Manual reconcile against transaction
   inquiry.
4. **Money and margin.** Revenue (recurring and packs) against LLM cost, by action, plan and model.
   Estimate accuracy: how often and by how much actual charges fall outside the range, per action
   and estimator version. Outstanding debt, users at their limits, credits expiring unused, and
   the cost of expired jobs.
5. **Health.** Last run and outcome of each sweeper job, webhook error rate, renewal failures,
   failed auto top-ups and failed extra-seat charges.

## 9. Testing

TDD. Locally, run only the test files touched; CI runs the full suite.

- **Unit.**
  - HMAC: the docs' worked concatenation example, `None` handling, wallet-shaped `source_data`.
  - Subscription HMAC.
  - Pricing: USD to units, rounding, estimate ranges per input kind.
  - Proration for plans and seats.
  - Spend order and payer-chain building for each row of the §5.6 table.
  - Per-subject seat routing: maths work charges the maths seat, physics work the physics seat,
    subject-less work charges no seat; two seats on one subject follow the §5.6 order.
- **Repository (Postgres).**
  - Concurrent jobs on one balance: reservations prevent both starting when only one is covered.
  - Settle under, at and over the reservation; over-reservation draws down the chain, then
    creates debt on the payer of last resort.
  - Debt blocks new jobs on that owner; a seat allowance stays usable; a new grant repays debt
    first.
  - Caps: teacher credits stop at a seat's cap and an assistant's cap.
  - Release on failure; job expiry; grant expiry while held.
  - Seat count limit under concurrent class joins; seat release at period end; seat grant dedupe.
  - Duplicate webhook; period grant cannot be issued twice; mismatch rejection.
  - Nightly balance reconcile; audit log rows are append-only.
- **Router.**
  - Webhook endpoints with recorded fixture payloads.
  - Checkout authorization: parent and child, IDOR.
  - 402 reasons, including `outstanding_debt` and `out_of_seat_scope`.
  - Assistant permissions per role preset and toggle; assistants cannot reach billing or seats.
  - Admin endpoints reject non-admins; every admin money action writes an audit row.
- **Live test account** (manual, recorded as fixtures).
  - Test card `5123456789012346` (holder "Test Account", expiry 01/39, CVV 123), through a tunnel
    to `notification_url`.
  - Capture real transaction, token and subscription callbacks.

## 10. Delivery order and Paymob dependencies

1. Card one-off checkout and webhooks (credit packs, students and teachers): works on the test
   account today.
2. Usage ledger, estimates, metering hook, payer chain, debt, entitlement, free allowances.
3. Teacher team: seats on class join, scope, caps, assistants, invites, team permissions.
4. Subscriptions (Paymob plans, webhooks, lifecycle) and seat allowances.
5. Upgrade proration, extra seats and auto top-up (merchant-initiated charges).
6. Admin dashboard areas, built alongside the steps they observe; complete by the end of step 5.

Steps 4–5 need **MOTO enabled by Paymob**. A Paymob delay blocks only those steps.

**Ask Paymob in writing now:**

1. Enable a MOTO integration on the test account.
2. Confirm subscriptions are available for Egypt accounts.
3. Callback retry policy and source IPs.
4. The live-account path (Starter vs Registered Business) and its limits.
5. Whether Apple Pay works on hosted Unified Checkout.
6. Whether `special_reference` uniqueness is enforced.
7. Whether a subscription's amount can be changed by PUT between renewals (for extra seats).

**Open for counsel and accountant** (these do not block the build): VAT timing on prepaid credits;
Egyptian consumer refund rights for digital services; acceptability of the 12-month expiry, of
"no cash refunds", and of carrying usage debt into the next payment (research 08 §4).

## 11. Success criteria

- A student (or a parent for a linked child) can subscribe and buy credits by card on the test
  account. The allowance appears, the usage meter moves with each LLM action, and usage falls
  through to credits when the allowance runs out.
- Every metered action shows a range estimate first; the usage history shows the actual charge;
  no usage receipts exist.
- A job overrunning the balance creates debt on the payer of last resort, which blocks that
  account's new jobs until the next grant repays it.
- A teacher can seat students through a class code up to the plan's seat count, buy extra seats,
  set scope and caps, and add assistants whose permissions and caps hold.
- Duplicate, missing or forged callbacks never double-grant or grant falsely (tests prove each
  case).
- Ledger reconcile shows zero drift, including debts.
- Renewal, failed renewal with grace, upgrade, downgrade, cancel and seat changes each move the
  subscription through the documented states.
- Every admin money action appears in the audit log with a reason.

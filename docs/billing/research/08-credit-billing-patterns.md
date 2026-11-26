# Credit / usage billing patterns for AI products: research for Lemely

Research date: 2026-11-02. Method: web search plus page fetches. "(F)" = page fetched and read; "(S)" = search snippet only, not opened. Treat (S) claims as lower confidence. Where a requested item could not be found, it is listed under "Gaps".

Context: Lemely is an AI exam-marking SaaS in Egypt, priced in EGP, payments through Paymob (no Stripe). Users are students, parents and teachers. Backend is FastAPI + Postgres. Design goal: credits weighted by actual LLM cost, reserve-then-settle, prepaid bundles, one-time signup grant, subscriptions that grant credits per period.

---

## 0. Executive summary

1. Credits for AI are mainstream and driven by margin. Kyle Poyar's 2026 survey (230 B2B/AI companies) found a median target AI gross margin of about 50% against 70-80%+ for classic SaaS, and hybrid (subscription + consumption) was the most common model at 37%, up from 25% a year earlier. Poyar's own experience: 70-80% of token consumption comes from 10% of users.
2. Every serious credit system converges on the same ledger shape: immutable entries, grant "buckets" with priority and expiry, deterministic burn order (priority, then earliest expiry, then promotional before paid, then FIFO), idempotency keys with a unique constraint, and pending-then-post (two-phase) holds for in-flight spend.
3. Reserve-then-settle is the standard two-phase pattern (TigerBeetle pending/post/void with timeout; Modern Treasury pending/posted/archived). Consumer AI products mostly do not hold funds. They meter after the fact and pause at zero (Lovable, Cursor). Reserve-then-settle matters more for Lemely because marking jobs are discrete, have a pre-computable upper bound (page count), and the user must not be able to start more jobs than they can pay for.
4. Paymob recurring is card-only. Any wallet, Fawry or instalment user must renew by hand. The sound design is to make the period pass the primitive (a time-boxed grant bought one period at a time) and treat card auto-renewal as an optional convenience layer on top. Subscriptions are then just "auto-repurchase of a period pass".
5. Build the ledger in-house on Postgres (about 5 tables). Adopting Lago, OpenMeter, Polar or Flexprice is not worth it here: most assume Stripe or a merchant-of-record, and Lemely would still need its own Paymob adapter, its own reserve/settle, and a second datastore. Borrow their semantics, not their code.
6. Legal: prepaid credit expiry is common (Anthropic: 1 year, non-refundable), but Egyptian consumer-law, CBE stored-value and VAT treatment are unresolved by this research. Get Egyptian counsel before launch. Design so that paid credits never expire silently and the policy can be changed by config.

---

## 1. Pricing strategy and margin protection

| Claim | Source | Date | Conf. |
|---|---|---|---|
| Median target gross margin for AI features is about 50%. Only 12% target 80%+. Margin was the top factor when pricing AI (54%). Hybrid is the most popular model (37%); it was 25% twelve months earlier. Investors prefer hybrid (35%), outcome-based (26%) or usage-based (24%) over flat fee (10%) or seat (5%). | https://www.growthunhinged.com/p/the-state-of-b2b-monetization-in-2026 | 2026 report (published about May 2026) | F |
| "Credits or tokens are the ultimate commodity pricing metric for AI." Largest companies are making the most pricing changes. Clay split value and cost into separate buckets (March 2026). Anthropic moved Enterprise toward usage-based. | same | 2026 | F |
| Poyar's credit thesis: AI cost deflation did not remove the margin problem, because the latest models stay expensive and token use per task is exploding. 70-80% of token consumption comes from 10% of users; heavy users become very unprofitable without guardrails. | https://kylepoyar.substack.com/p/ai-credit-pricing ("Why everyone's switching to AI credits") | Sept 2025 (date from search snippet) | F (part free) |
| Hybrid = subscription base plus consumption on top is "a stepping stone" toward value-based pricing. | Poyar summaries via https://echai.ventures/gtm/gtm-pricing-packaging/ai-is-breaking-per-seat-pricing-what-are-the-best-companies-charging-for-now | 2026 | S |
| Cursor moved Pro from request counts to a dollar-denominated monthly credit pool at API prices ($20 of frontier-model usage; Auto unlimited; optional spend limit to buy more at cost). Rollout was unclear. Cursor apologised and offered refunds for unexpected usage from June 16 to July 4. | https://cursor.com/blog/june-2025-pricing ; https://techcrunch.com/2025/07/07/cursor-apologizes-for-unclear-pricing-changes-that-upset-users/ | 2025-07-04 and 2025-07-07 | F / S |
| Replit effort-based pricing: one checkpoint per request, priced by effort. Hard budget caps and usage alerts are offered. Agent 3 users reported surprise overruns. | https://docs.replit.com/billing/ai-billing.md (F); https://www.theregister.com/2025/09/18/replit_agent3_pricing/ (S) | 2025-09-18 | F / S |

Takeaways for Lemely:
- Margin protection comes from (a) denominating credits in cost (a credit is a fixed fraction of an EGP of LLM cost), (b) a published price per credit with a margin multiplier you control, (c) caps on the heavy tail (per-job cap, per-period cap), and (d) never promising "unlimited".
- Cursor shows the failure mode: moving to cost-based credits without a preview and without a transition caused a trust incident and refunds. Lemely starts clean, so show the estimate before every job (section 2).
- A pooled "included usage" model (a period grant sized to cost, with paid top-ups after) is what Cursor, Replit and Lovable all converged on.

---

## 2. Reserve-then-settle metering

### Evidence

- Two-phase transfers (TigerBeetle): pending reserves funds, then post (the posted amount may be less than the pending amount), void, or automatic expiry via a timeout; on expiry the full amount returns. https://docs.tigerbeetle.com/coding/two-phase-transfers/ (F, current docs, fetched 2026-11-02). The doc's table shows a pending 123 followed by a post of 100.
- Modern Treasury ledger transactions are pending (mutable) then posted (immutable), or archived on failure. https://www.moderntreasury.com/journal/enforcing-immutability-in-your-double-entry-ledger (F, 2021-12-14). Authorizing entries reserve the authorised amount until cleared, which is the card-authorization analogue. https://www.moderntreasury.com/journal/how-to-scale-a-ledger-part-iv (F, 2022-12-20, updated 2025-08-25).
- Orb keeps pending ledger entries until a reporting grace period passes, then commits them as immutable. Late events deduct by event time, so an event that happened before a block expired still draws from that block. https://docs.withorb.com/guides/product-catalog/prepurchase (F, fetched 2026-11-02).
- Lago exposes "balance" (invoiced) versus "ongoing balance" (includes current usage and draft invoices). That is the same available-versus-posted split. https://docs.getlago.com/guide/wallet-and-prepaid-credits (F, 2026).
- Stigg handles shortfall with an overdraft grant instead of rejecting the event: it deducts what exists, then tracks the remainder in a new overdraft grant. https://docs.stigg.io/documentation/modeling-your-pricing-in-stigg/credits/credit-consumption-logic (F, 2026).
- Lovable pauses a mid-flight message at zero balance rather than ending it (S, https://docs.lovable.dev/introduction/out-of-credits). Cursor gives "a short grace period beyond the credit pool" and a user-enabled spend limit (F, cursor blog above, 2025-07-04). Replit offers hard budget limits and alerts (F, 2025-2026).
- Anthropic API: prepaid usage credits, no reservation. Spend is metered after the call, and the balance floors at zero. https://support.claude.com/en/articles/8977456-how-do-i-pay-for-my-claude-api-usage (F, fetched 2026-11-02).

### Pattern synthesis (what to copy)

1. Estimate before, from known inputs (pages, mark scheme size, model). Show it as "up to N credits" (an upper bound), not a point estimate.
2. Reserve the upper bound (or estimate times a safety factor) as a hold. Available balance = posted balance minus open holds.
3. Run the job. Accumulate actual LLM cost (per call, from the provider's usage metadata).
4. Settle: post actual cost, release the unused hold. Hold timeout is the safety net for crashes (TigerBeetle-style expiry).
5. Overrun beyond reserve: cap at the reserve for the user (absorb the excess, record it as `absorbed_cost`). Optionally allow overrun up to a small percentage, drawn from balance if available. Do not interrupt a nearly finished job to ask for more money. Fail the job early with release if the running cost approaches the cap.
6. Failed job: release the full hold and post zero. Partial results: charge only for completed units (per-page or per-question granularity), release the rest.
7. Refunds: a compensating entry (reason code) back into a grant bucket. Per Stripe, voiding or credit-noting does not automatically restore applied credits and may require a fresh grant, and reinstated credits past expiry expire immediately (https://docs.stripe.com/billing/subscriptions/usage-based/billing-credits, F). Lemely refunds should therefore create a new grant with a fresh short expiry, not re-use the old bucket.
8. UX: always show "estimated up to X credits, you will only be charged the actual cost" before confirm. Receipt afterwards shows estimate versus actual.

---

## 3. Credit ledger engineering

### Vendor semantics worth copying

| Topic | Finding | Source | Date |
|---|---|---|---|
| Stripe credit grants | Priority 0-100 (default 50, lower applies first); then earlier `expires_at`; then `promotional` before other categories; then effective date, then created date. Grants have a `category` of paid or promotional. Expiry is opt-in. Credits apply after discounts, before tax. A grant can be voided only if not yet applied. Priority was added to the API in Feb 2025. | https://docs.stripe.com/billing/subscriptions/usage-based/billing-credits (F); https://usagebox.com/articles/prepaid-credits-usage-based-billing-drawdown-expiry (F) | docs 2026; article 2026-06-04 |
| Orb | Blocks, each with an amount and expiry. Burn order: license allocations; blocks with item filters; soonest-expiring; lower cost basis first (free before paid, which preserves revenue recognition); earliest created. Append-only trace of every balance change. Expiry-change is a ledger entry. | https://docs.withorb.com/guides/product-catalog/prepurchase (F); usagebox article above | 2026 |
| Stigg | Order: priority, expiration, promotional before paid, effective date, creation. A deduction spanning grants creates one ledger entry per grant consumed. | https://docs.stigg.io/documentation/modeling-your-pricing-in-stigg/credits/credit-consumption-logic (F) | 2026 |
| Lago | Up to 6 wallets per customer, priority 1-50, then soonest expiry, then no-expiry last, then oldest. Expiry voids remaining credits. Top-up min/max limits, recurring top-up rules. Prepaid credits apply to subscription invoices, not one-off invoices. AGPLv3 open-source edition. | https://docs.getlago.com/guide/wallet-and-prepaid-credits (F) | 2026 |
| Modern Treasury | Business objects are mutable presentation; ledger transactions are the immutable source of truth. Corrections are new reversing or difference entries. | https://www.moderntreasury.com/journal/enforcing-immutability-in-your-double-entry-ledger (F) | 2021-12-14 |
| pgledger | Double-entry ledger as Postgres tables, functions and views, no app code. Writes share a transaction with application writes. Entries carry `event_at` and `created_at`. Go tests, no Python library; usable from psycopg via its SQL functions (my inference). | https://github.com/pgr0ss/pgledger (F); https://pgrs.net/2025/06/17/double-entry-ledgers-missing-primitive-in-modern-software/ (F) | 2025-06-17 |
| Concurrency options | Unique `(tenant, idempotency_key)` constraint is the real guard; a preceding SELECT is not. A guarded single `UPDATE ... WHERE credits >= n` avoids a read-then-write race. Summing entries on every request is exact but slows at scale. | practitioner posts via search (S), e.g. https://oneuptime.com/blog/post/2026-07-21-deduplicate-idempotency-unique-constraint/markdown | 2026-07-21 |

### Open-source options and build-vs-buy facts

- Lago (AGPLv3, self-hostable; wallets and prepaid credits present). Postgres + Redis + Rails app. Assumes you push usage events to it and let it invoice, with Stripe/GoCardless style payment connectors. (F for wallets; license from S.)
- Polar: Apache-2.0, self-hostable, credits as a benefit on a meter, but it is a merchant of record on top of Stripe, so it does not fit Paymob. Its docs flagged usage-based billing as alpha at the time of the snippet (S).
- OpenMeter, Flexprice, Autumn: not researched successfully (no usable results). Unverified; do not rely on them.
- None of these has a Paymob connector that I could find. Lemely would write webhook-to-ledger glue regardless.

Verdict: build. The problem is small (grants, holds, entries, one Paymob adapter). A buy adds a second system of record, an AGPL or deployment burden, and still needs custom glue for reserve/settle and for period passes. Revisit if Lemely adds multi-currency, invoicing and tax automation, or enterprise contracts.

---

## 4. Legal and consumer issues

| Topic | Finding | Source | Date | Conf. |
|---|---|---|---|---|
| Expiry norm in AI | Anthropic Credit Terms: Usage Credits and Promotional Credits are non-refundable; Usage Credits lapse one calendar year after issuance; closing the account forfeits the balance. Support article says expiry cannot be extended. | https://www.anthropic.com/legal/credit-terms (S, quoted in search); https://support.claude.com/en/articles/8977456-how-do-i-pay-for-my-claude-api-usage (F) | fetched 2026-11-02 | F/S |
| User backlash | OpenAI forum threads and HN posts complain about prepaid credits expiring or zeroing without notice. Lesson: notify before expiry. | https://community.openai.com/t/you-should-notify-users-about-expiring-credit-or-how-i-lost-400-usd/1152685 ; https://hn.svelte.dev/item/44793446 (S) | 2025 | S |
| US analogue | California Civil Code 1749.5 bans expiry dates on gift certificates; federal CARD Act sets a 5-year floor for gift cards. A forum commenter argues it applies to AI credits; untested. Not Egyptian law. | https://dca.ca.gov/publications/legal_guides/s11_chart.pdf ; https://advocacy.consumerreports.org/research/fact_sheet_on_state_gift_card_protection_laws/ (S) | n/a | S |
| Egypt e-money | Law 194 of 2020 (Central Bank and Banking Sector Law) created the licensing regime for payment system operators and PSPs. Practitioner guide lists e-money institution capital of EGP 30m for full EMI. Penalties for unlicensed e-money issuance reported. | https://eg.andersen.com/electronic-money-institution-licensing-egypt/ (F) | 2026-03-05 | F |
| Egypt: do closed-loop service credits count as e-money? | Not found. The usual global exclusion is for "limited network" or single-merchant instruments redeemable only for the issuer's own services. I found no CBE text confirming that exclusion in Egypt. Needs counsel. | n/a | n/a | gap |
| Egypt consumer law | Law 181 of 2018 and Executive Regulation (PM Decree 822 of 2019): 14-day return right is widely reported; sources conflict on online-specific windows (3, 7 or 14 days) and I found nothing on a digital-content exception. | https://www.mondaq.com/Article/820956/New-Egyptian-Consumer-Protection-Law ; https://cairoscene.com/buzz/egyptian-retailers-refusing-customer-returns-within-14-days-will-be-fined-up-to-egp-500-000 (S) | 2019-2023 | S |
| Egypt VAT | 14% standard rate. B2C digital/online/e-learning services are in scope. Non-resident digital supplier registration threshold reported as EGP 500,000 (Fonoa); ETA guidelines for non-residents effective 2023-06-22. Online education is named as a digital service. | https://www.fonoa.com/resources/country-tax-guides/egypt/tax-on-digital-services (F); https://www.bdo.global/en-gb/insights/tax/indirect-tax/egypt-guidance-issued-on-vat-treatment-of-a-supply-of-digital-services (S) | 2023-2026 | F/S |
| VAT timing | Not found for Egypt. Common international treatment: a single-purpose voucher (service and place known at issue) is taxed at sale; a multi-purpose voucher is taxed at redemption. Lemely credits probably behave as single-purpose, so expect VAT at purchase. Confirm with an Egyptian tax adviser. | not found | n/a | gap |
| Minors | No source found. A parent pays, a child consumes. Practical stance: the payer (parent) is the account owner of the wallet and the contract party; the student is a "beneficiary seat". Refund goes to the payer. | n/a | n/a | gap |

Design consequence: keep expiry, refundability and breakage as per-grant-class config (`expires_at`, `refundable`), keep a clean audit trail for VAT-at-purchase, record payer versus beneficiary, and put the policy in the terms before launch.

---

## 5. Subscription + credits mechanics

### 5.1 Lifecycle state machine (adapted from Stripe, with a manual-renewal branch)

Stripe's statuses: incomplete, incomplete_expired, trialing, active, past_due, canceled, unpaid, paused. Failed renewal leaves `past_due` while retries run; after retries end it moves to `canceled`, `unpaid` or stays `past_due` per settings; `unpaid` stops payment attempts and Stripe advises revoking access; `canceled` is terminal and disables collection of unpaid invoices. Status resolves from the most recent non-voided invoice by default. https://docs.stripe.com/billing/subscriptions/overview (F, fetched 2026-11-02). Smart retries and `invoice.payment_failed` with `attempt_count` / `next_payment_attempt`: https://docs.stripe.com/billing/revenue-recovery/smart-retries (F). Hard declines cannot be retried without a new payment method.

Proposed Lemely states (each subscription has `renewal_mode` = `auto_card` or `manual`):

```
                 pay ok                      period_end
 (none) -> pending_first_payment ---> active ----------------> [renewal due]
                 | fail/timeout         |  ^                      |
                 v                      |  | pay ok               | auto_card: charge token
          incomplete_expired            |  |                      | manual: send reminders,
                                        |  |                      |   offer "renew now" link
        user cancels                    |  |                      v
        (cancel_at_period_end=true)     |  +----------------- renewed (new period grant)
                 |                      |                         |
                 v                      |            charge fails / no payment by period_end
   active(cancel_at_period_end) --period_end--> expired            v
                                                              past_due (grace window)
                                                                |        |
                                                  pay ok -> active       | grace elapsed
                                                                          v
                                                                       expired (terminal for the period,
                                                                       can be re-purchased -> new subscription row or reactivate)
```

State rules:
- `trialing`: optional. If used, grant trial credits as a normal grant with `source=trial` and promotional category. No card needed for manual mode.
- `active`: entitlement on; period grant exists with `expires_at = current_period_end` (or rollover policy, 5.3).
- `past_due` (grace): entitlement stays on but the period grant is NOT issued until payment. Grace length is config: 3 days for auto-card (retries 1, 3, 5 days after due), 7 days for manual (user must act). The Etisalat UAE pack model is the same idea (S): 30-day grace on monthly packs, 7 on weekly, after which re-subscription is needed (https://etisalat.ae/en/c/support/mobile/prepaid/prepaid-international-packs/billing-and-usage.html, S, undated).
- `cancel_at_period_end`: a flag, not a state. Lovable does this: the plan stays active until the period ends, then moves to Free (F, https://docs.lovable.dev/introduction/plans-and-credits, 2026).
- `expired`: entitlement drops to the free tier. Purchased bundle credits still usable, because they are separate grants.
- `paused`: only use for trial-without-payment-method; skip otherwise. Stripe restricts it the same way.

### 5.2 Paymob specifics

- Paymob subscriptions: you create a plan (amount, frequency weekly/monthly/yearly) and the customer enrols with a first 3DS transaction; Paymob then charges automatically. Developer doc says plan creation requires the MOTO integration ID and a `webhook_url`, and webhooks fire on subscription-level actions. Docs "last updated June 28, 2026". https://developers.paymob.com/paymob-docs/payments-and-features/core-features/subscriptions (F); https://developers.paymob.com/paymob-docs/llms.txt (F, 2026-06-28).
- Tokenization of cards for merchant-initiated charges is described on https://paymob.com/en/subscriptions (S).
- I found no Paymob documentation for recurring charges on wallets (Vodafone Cash etc.), Fawry or instalments. Assume none; confirm with Paymob support. A different provider's docs state a wallet should not be charged without an active mandate (https://docs.spotflow.one/features/mobile-money-subscriptions, S).
- Implication: the ledger must be indifferent to how the money arrived. A `payment` row (paymob_order_id, status, method) funds a grant; renewal logic only decides who initiates the next payment.

### 5.3 Monthly grant: expire or roll over

Observed vendor practice (S unless noted):
- Plan allowance usually resets each period (Lovable: resets on renewal date, no rollover unless the plan includes it; daily/monthly free grants reset at 00:00 UTC on the 1st) (F, Lovable docs, 2026).
- Caps are the compromise: Builder.io caps balance at 2x monthly; Captions allows rollover up to a 3x monthly cap. Top-up packs are separate, discounted for bigger sizes, and non-expiring or expiring in 12 months (Descript, JetBrains) (S, pages from the search "top-up credit packs", 2026).
- Orb supports "expire at end of cadence", "never expire" or "after N days/months" per block, so a use-it-or-lose-it allotment and a non-expiring top-up coexist (F via usagebox, 2026-06-04).

Recommendation: period grant expires at period end plus a short tail (for example 7 days) rather than a hard midnight cut-off; paid bundles last 12 months. Burn order puts the expiring period grant first, so top-ups are preserved.

### 5.4 Plan changes and proration

- Common practice: upgrades take effect immediately with proration; downgrades are scheduled to the period end, which avoids generating credit balances (S: https://dodopayments.com/blogs/subscription-upgrade-downgrade-proration ; https://www.chargebee.com/blog/ask-us-proration-saas-important/). Recurly: switches that change the billing period (monthly to annual) restart the term without proration (S, https://recurly.com/glossary/upgrades-and-downgrades/). Juicebox prorates the credit grant mid-cycle and grants the full amount at renewal (S, https://docs.juicebox.ai/help/plans/upgrade-plan).
- Credit-grant proration is not documented in Orb, Metronome or Lago in what I could retrieve. Lemely design: on upgrade, charge the price difference and issue a top-up grant for the difference in monthly credits, expiring at the same `period_end`; do not reset the period. On downgrade, schedule for period end (`pending_plan_id`).

### 5.5 Manual-renewal / prepaid-period patterns

- Telecom prepaid packs are the canonical model: a validity pack bought per period, with a grace window and a re-subscribe flow (Etisalat page above, S). Light Reading reports average prepaid users hit a zero-balance day weekly in many emerging markets and that prepaid churn is high (https://www.lightreading.com/services/we-need-to-talk-about-prepaid, S, undated). Juvo-sponsored figures (3.1-6.5% monthly prepaid churn across eight markets) come from a retention vendor, so treat as indicative (S).
- Mobile money rarely allows silent recurring pulls; a manual renewal link is the universal fallback with an estimated 75-85% success per a vendor blog (https://kolonell.com/en/blog/saas-subscription-recurring-mobile-money-payment-2026, S, vendor claim, unverified).
- ChatGPT Go launched in India in August 2025 at INR 399 per month with UPI payment, renewals needing a saved payment method, then was free for 12 months in India from 2025-11-04. It is available in 89 countries including Egypt. I could not find Egypt price, trial, or autopay detail. (https://techcrunch.com/2025/08/18/openai-launches-a-sub-5-chatgpt-plan-in-india ; https://inc42.com/buzz/openai-makes-chatgpt-go-free-for-users-in-india/ , S.)
- Jio/Airtel and Spotify prepaid card specifics: not found.

Design for manual renewal:
1. Reminders at T-7, T-3, T-1 days and at expiry, via WhatsApp/email/SMS with a one-tap Paymob checkout link pre-filled with the plan.
2. Extend rather than replace: if the user renews during grace, new period starts at the old `period_end` (no lost days); if after grace, starts at payment time.
3. Offer a prepay-N-periods discount (3 or 10 months) as the Egyptian-market analogue of annual plans. It improves cash collection and reduces renewal friction.
4. Offer "auto-renew with card" as an upgrade for card users only.
5. Never lock stored paid credits: lapse of the subscription only removes the period grant.

### 5.6 Entitlement checks

Separate three questions, answered in this order on every job start:
1. Feature entitlement: does the user's current plan (derived from subscription state, including grace) allow this feature, model tier, page cap, concurrency?
2. Balance: `available = SUM(active grant remaining) - SUM(open holds)`; must be at least reserve amount.
3. Caps: per-job max credits, per-period soft cap, per-day abuse cap.

Cache the entitlement snapshot per request, but perform the balance check and the hold insert in one transaction.

---

## 6. UX patterns

Findings are from help-center docs, mostly undated; low confidence on specifics.
- Two-tier alerts: notify at a higher threshold than the auto-top-up trigger. Usage-percentage triggers (alert at 90% used) suit variable usage. Warn before enabling auto top-up if the balance is already under the threshold, because the card is charged immediately. Cap auto-charges to once per minute. Send a receipt with amount and new balance on each top-up. Clear message about what happens at zero (https://docs.ltx.io/auto-top-up ; https://www.autobound.ai/blog/auto-top-up-api-credits ; https://help.mobilemessage.com.au/billing-payments/low-balance-alerts, S).
- Lovable: pause rather than kill when credits run out; usage limits and alerts per member (F, 2026). Replit: usage alerts, hard budget caps, real-time tracking, credit packs with volume discounts (F, 2025-2026). Cursor: explicit spend limit opt-in (F, 2025-07-04).
- Cost preview before action: I found no authoritative source. Treat it as a Lemely design decision (section 2).

Lemely UX rules: header shows "available" credits (posted minus holds) and, on hover, a breakdown by bucket with expiry dates; "N credits expire on D" banner at T-7 and T-1; estimate range on the upload screen; receipt per job with estimate, actual, and a refund line for failed pages; history page rendering ledger entries in plain language; parent view lists beneficiaries and spend per child.

---

## 7. Recommendations for Lemely

### 7.1 Unit of account
- 1 credit = fixed EGP value of LLM cost at a reference rate (for example 1 credit = EGP 0.50 of provider cost). Store `cost_micro_egp` alongside credits on each settlement for margin analysis. Sell credits at a published price with margin; update the credit weighting table per model/provider in config, versioned (`pricing_version`), so old ledger entries stay explainable.
- Integers only (`BIGINT` in milli-credits).

### 7.2 Ledger schema sketch (Postgres)

```sql
-- Owner of a wallet (the payer). Beneficiaries are separate.
CREATE TABLE wallet (
  id            BIGSERIAL PRIMARY KEY,
  owner_user_id UUID NOT NULL UNIQUE,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE credit_grant (            -- a bucket
  id             BIGSERIAL PRIMARY KEY,
  wallet_id      BIGINT NOT NULL REFERENCES wallet,
  source         TEXT NOT NULL CHECK (source IN
                  ('signup','promo','subscription_period','bundle','topup','refund','adjustment')),
  category       TEXT NOT NULL CHECK (category IN ('promotional','paid')),
  priority       SMALLINT NOT NULL DEFAULT 50,   -- lower burns first
  initial_amount BIGINT NOT NULL CHECK (initial_amount > 0),
  effective_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at     TIMESTAMPTZ,                     -- NULL = never
  refundable     BOOLEAN NOT NULL DEFAULT false,
  payment_id     BIGINT REFERENCES payment,       -- Paymob order that funded it
  subscription_period_id BIGINT REFERENCES subscription_period,
  cost_basis_egp NUMERIC(12,2) NOT NULL DEFAULT 0, -- 0 for free credit (revenue recognition)
  idempotency_key TEXT NOT NULL,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (wallet_id, idempotency_key)
);

CREATE TABLE ledger_entry (            -- append-only; no UPDATE/DELETE (revoke + trigger)
  id           BIGSERIAL PRIMARY KEY,
  wallet_id    BIGINT NOT NULL REFERENCES wallet,
  grant_id     BIGINT NOT NULL REFERENCES credit_grant,
  hold_id      BIGINT REFERENCES credit_hold,
  kind         TEXT NOT NULL CHECK (kind IN
                 ('grant','hold','release','settle','expire','refund','adjust','void')),
  amount       BIGINT NOT NULL,          -- signed; +increase, -decrease of grant remaining
  job_id       UUID,
  reason       TEXT,
  pricing_version INT,
  event_at     TIMESTAMPTZ NOT NULL,     -- when it happened (Orb/pgledger idea)
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  idempotency_key TEXT NOT NULL,
  UNIQUE (wallet_id, idempotency_key, grant_id, kind)
);

CREATE TABLE credit_hold (             -- two-phase reserve
  id          BIGSERIAL PRIMARY KEY,
  wallet_id   BIGINT NOT NULL REFERENCES wallet,
  job_id      UUID NOT NULL UNIQUE,
  reserved    BIGINT NOT NULL,
  status      TEXT NOT NULL CHECK (status IN ('open','settled','released','expired')),
  expires_at  TIMESTAMPTZ NOT NULL,      -- crash safety net
  settled     BIGINT,
  absorbed    BIGINT NOT NULL DEFAULT 0, -- overrun we ate
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Cache, derivable from ledger; rebuilt by a nightly reconciliation job.
CREATE TABLE grant_balance (
  grant_id  BIGINT PRIMARY KEY REFERENCES credit_grant,
  remaining BIGINT NOT NULL CHECK (remaining >= 0),
  held      BIGINT NOT NULL DEFAULT 0 CHECK (held >= 0 AND held <= remaining)
);

CREATE TABLE payment (                 -- Paymob side
  id BIGSERIAL PRIMARY KEY, wallet_id BIGINT NOT NULL,
  paymob_order_id TEXT UNIQUE, paymob_txn_id TEXT UNIQUE,
  method TEXT, amount_egp NUMERIC(12,2), vat_egp NUMERIC(12,2),
  status TEXT, purchased_for_user_id UUID, created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE subscription (
  id BIGSERIAL PRIMARY KEY, wallet_id BIGINT NOT NULL, plan_id TEXT NOT NULL,
  status TEXT NOT NULL,                  -- pending_first_payment|trialing|active|past_due|expired|incomplete_expired
  renewal_mode TEXT NOT NULL,            -- auto_card|manual
  current_period_start TIMESTAMPTZ, current_period_end TIMESTAMPTZ,
  grace_until TIMESTAMPTZ, cancel_at_period_end BOOLEAN NOT NULL DEFAULT false,
  pending_plan_id TEXT, paymob_subscription_id TEXT,
  version INT NOT NULL DEFAULT 0         -- optimistic lock for webhook races
);
CREATE TABLE subscription_period (
  id BIGSERIAL PRIMARY KEY, subscription_id BIGINT NOT NULL,
  period_start TIMESTAMPTZ NOT NULL, period_end TIMESTAMPTZ NOT NULL,
  payment_id BIGINT, UNIQUE (subscription_id, period_start)   -- idempotent period grant
);
```

### 7.3 Reserve/settle rules
1. `reserve(job_id, upper_bound)`: one transaction. `SELECT ... FROM grant_balance JOIN credit_grant WHERE wallet_id=? AND effective_at<=now() AND (expires_at IS NULL OR expires_at>now()) AND remaining-held>0 ORDER BY priority, expires_at NULLS LAST, (category='promotional') DESC, effective_at, id FOR UPDATE`. Walk the rows, increment `held`, insert one `hold` ledger entry per grant, insert `credit_hold(status=open, expires_at=now()+job_timeout+slack)`. Insufficient: return 402 with the shortfall. `UNIQUE(job_id)` makes retries idempotent. Lock order is the same order everywhere, which avoids deadlocks. Row locks on `grant_balance` are enough at this scale; no serializable isolation needed.
2. `settle(job_id, actual)`: lock hold and its grants. `charged = min(actual, reserved)`. Consume from held amounts in the same burn order, write `settle` entries, write `release` entries for the unused remainder, set `absorbed = max(0, actual - reserved)`. Idempotent on `(hold_id, status)`.
3. Overrun policy: absorb up to a configured ceiling (for example reserve times 1.5); beyond the ceiling the job aborts and releases, with partial results returned if the unit of work is complete (per-paper or per-question).
4. Failed or cancelled job: `release` all. Partial: settle completed units only.
5. A sweeper expires `open` holds past `expires_at` (release), and expires grants past `expires_at` (write `expire` entries for `remaining - held`; held amounts expire when their hold resolves unless an event_at before expiry).
6. Late settlements use `event_at` for eligibility, so a job begun before a bucket expired can still draw from it (Orb behaviour).
7. Reconciliation job: for each grant, `initial_amount + SUM(ledger.amount) = remaining`; alert on mismatch.
8. Refunds are `refund` ledger entries creating a new grant (`source=refund`, `expires_at` = now plus 30 days, or the original expiry if later).

Burn order (decided): priority, earliest expiry (NULLs last), promotional before paid, `effective_at`, `id`. This matches Stripe, Stigg and Orb. Default priorities: signup/promo 10, subscription_period 20, refund 30, bundle/topup 50.

### 7.4 Expiry and breakage policy (proposal, pending counsel)
- Signup grant: 30 days, promotional, non-refundable. One per verified phone/email; abuse-guard in `payment`/identity layer.
- Subscription period grant: expires at `period_end` plus 7 days; promotional-like priority.
- Paid bundles: 12 months from purchase, with email/WhatsApp warnings at 60, 14 and 3 days. Extend by 6 months on any new purchase. Anthropic's 1-year is the norm among AI vendors, but Egyptian law is unchecked, so keep expiry per-bundle configurable and consider no expiry for the first launch.
- Refunds: unused bundle credits refundable to the original Paymob method within 14 days of purchase if nothing consumed (aligns with the widely reported 14-day return right; confirm). After consumption, no refund except for failed/defective jobs, which refund as credit.
- Do not create a wallet-to-cash withdrawal path; that is what pushes a product toward e-money classification.

### 7.5 Subscription rules
- Plans grant a monthly credit pool sized by cost, and a top-up discount for subscribers (for example 10-20% on bundles).
- `renewal_mode=manual` default; `auto_card` offered only when the first payment was a tokenised card via a Paymob plan (MOTO integration, webhook configured).
- Webhook handler: verify HMAC, upsert `payment` by `paymob_txn_id` (unique), then in one transaction update subscription and insert `subscription_period` plus the period grant (unique `(subscription_id, period_start)` blocks double grants).
- Upgrade: immediate, charge the difference, issue difference grant expiring at the same `period_end`. Downgrade: `pending_plan_id`, applied at renewal. Cancel: `cancel_at_period_end`.
- Parent-for-child: `payment.purchased_for_user_id` records the beneficiary; the grant sits in the payer's wallet and the child consumes through delegated access, or the grant is pinned to the child via `grant.beneficiary_user_id` (add if required).

### 7.6 Build vs buy verdict
Build in Postgres, about 5-7 tables and two service functions. Reasons: Paymob is not supported by Lago/Polar/Orb/Stripe-based tools; reserve/settle is not a first-class feature in the OSS tools reviewed (Lago exposes ongoing balance but invoices in arrears); the dataset is small. Do borrow: Stripe's priority/expiry/category ordering, Orb's event-time eligibility and cost-basis-first burn, TigerBeetle's pending/post/void/timeout semantics, Modern Treasury's immutable ledger plus mutable business objects. Reconsider if Lemely needs invoice generation with Egyptian e-invoicing, multi-currency or enterprise contracts.

### 7.7 Open items for counsel and Paymob
1. Whether closed-loop prepaid service credits require CBE e-money licensing; whether a limited-network exemption exists.
2. Consumer-law treatment of expiry and of the 14-day return right for digital services.
3. VAT timing for prepaid credits (at sale or at consumption) and e-invoice requirements.
4. Paymob: recurring on wallets, Fawry, instalments; webhook retry semantics and signature; how failed renewals are reported on a plan.
5. Minors: who is the contract party when a parent buys for a child.

---

## 8. Gaps in this research
- a16z, OpenView, Madhavan Ramanujam, Bessemer, Metronome, Chargebee, Paddle/ProfitWell, m3ter, Schematic blog posts: not retrieved directly. Only Poyar's 2026 report and Orb/Stripe/Stigg/Lago docs were read in full.
- OpenMeter, Flexprice, Autumn: no usable results.
- Egyptian statutes (CBE rules on stored value, Consumer Protection Law text on digital content, VAT timing on vouchers): not found; secondary summaries only.
- Jio/Airtel recharge and Spotify prepaid mechanics, and ChatGPT Go Egypt pricing/payment: not found.
- Many search-snippet claims (marked S) were not verified against the primary page.

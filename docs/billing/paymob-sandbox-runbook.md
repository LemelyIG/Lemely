# Paymob sandbox and go-live runbook

Checks to run against the Paymob sandbox before launch, and the checks to run when the production
account goes live. Each check says what to do, what to record, what counts as a pass, and which
setting or constant in the code the answer controls.

Related docs:

- [`docs/deployment.md`](../deployment.md), including
  [§5.11, a payment held for a foreign integration](../deployment.md#511-runbook-a-payment-held-for-a-foreign-integration).
- [`docs/ci-cd.md`](../ci-cd.md), the deploy workflow that sets the `LEMELY_PAYMOB__*` variables.
- Paymob research: [core checkout](research/01-core-checkout.md),
  [webhooks, refunds, recurring](research/02-webhooks-refunds-recurring.md),
  [gap fill](research/04-gap-fill.md).

## 1. Purpose and when to run

Paymob's docs leave several questions open. Our code guards each one with a setting or a safe
default. This runbook answers the questions on a real Paymob account and turns the guesses into
facts.

Run it twice:

1. **Staging first.** Run S1-S20 on the Test account with Test keys and Test Integration IDs.
   Finish before any production deploy that sells subscriptions or charges saved cards.
2. **At go-live.** Run L1-L7 after Paymob approves the Live account and before the first customer
   pays.

Rules for every run:

- Record the raw body, URL and status code of each Paymob response and callback. Paste them into
  the evidence link in the results log (§6). Mask keys and card data first.
- Change one setting at a time. Write down the old and new value.
- A failed check is not a failed run. Record the answer, set the setting it controls, then re-run
  the checks that depend on it.

## 2. Prerequisites

Do these before the first check.

1. **Paymob account manager.** Ask them to enable **Subscriptions** and **MOTO** on the Test
   account. Neither is self-serve. MOTO gets its own Integration ID. Note the date you asked.
2. **Paymob support.** Ask for a decline method for the Test account. Paymob documents no decline
   or error-simulation numbers. Contact `support@paymob.com` if the account manager cannot help.
   Checks S9, S11 and S17 need it.
3. **Staging deploy with Test keys.**
   - Secret key, API key, HMAC secret and public key are all Test mode. Mixed modes give
     `404 Integration ID does not exist` at checkout.
   - `LEMELY_PAYMOB__CARD_INTEGRATION_ID` and `LEMELY_PAYMOB__MOTO_INTEGRATION_ID` are Test IDs.
   - `LEMELY_PAYMOB__NOTIFICATION_BASE_URL` and `LEMELY_PAYMOB__REDIRECTION_BASE_URL` are the
     public staging origin. A staging intention must never call back into production.
   - `LEMELY_PAYMOB__EXPECT_LIVE` is unset on staging.
4. **Callback URLs.** Register these in the Paymob dashboard for the Test integrations, on the
   staging origin:
   - Transaction: `/api/webhooks/paymob/transaction`
   - Subscription: `/api/webhooks/paymob/subscription`

   Set the MOTO integration's processed-callback URL to the transaction URL too. Renewal charges
   are ordinary transactions on the MOTO integration, and they have no intention to carry a
   `notification_url`.
5. **A raw look first.** Paymob's webhook inspector at `https://hooks.paymob.com` gives a Hook URL
   that shows callbacks live. Keep the page open, since it stores nothing. Point one test
   intention's `notification_url` at it to see what Paymob sends. Then run the real handler.
6. **Test users.** Create these on staging:
   - an admin,
   - a teacher,
   - a student,
   - a parent linked to the student,
   - a user with no phone number on the profile.
7. **Admin console.** Confirm you can reach the billing settings (`grace_days`), the plan sync
   action and the payment refund and void dialog.

## 3. Test credentials

Use these only with Test keys and Test Integration IDs. They never work against Live keys. Never
enter real card data in the sandbox.

| Method | Details |
|---|---|
| Mastercard, card 1 | `5123456789012346`, name `Test Account`, expiry `01/39`, CVV `123` |
| Mastercard, card 2 | `5123450000000008`, name `Test Account`, expiry `01/39`, CVV `123` |
| Visa | `4111111111111111`, name `Test Account`, expiry `01/39`, CVV `123` |
| Mobile wallet | number `01010101010`, MPIN `123456`, OTP `123456` |

Limits:

- **30-day retention.** Paymob keeps sandbox intentions and transactions for 30 days. Finish each
  flow inside that window.
- **No decline numbers.** Paymob documents none. Reusing a success card with wrong details may
  retry instead of declining. Use the method from Paymob support (§2).
- **No sandbox path.** Kiosk, BNPL (Valu, Souhoola, Tabby, Tamara, Sympl and the other
  providers), Apple Pay, Google Pay, Samsung Pay and bank installments cannot be tested end to end
  in the sandbox. This does not block launch. They use the same intention, checkout and callback
  code as cards. Check each on its first real transaction (see L5). Do not report one as tested
  because a test card passed.
- **3DS and OTP.** The same test cards walk through the 3DS challenge. The wallet uses the MPIN and
  OTP above.

## 4. Checks S1-S20

Three phases. Run them in order: later checks reuse the plan and payments from earlier ones.

### Phase A. One-off packs (S1-S9)

**S1. Return URL after payment**

- Steps: buy a credit pack with a test card on staging.
- Record: the exact URL Paymob redirects the browser to. It shows how Paymob appends its query
  string.
- Pass: the browser lands on `/billing/return/<payment id>` on the staging origin.
- Code depends on this: `redirection_base_url` and `RETURN_PATH` (`/billing/return`) in
  `lemely/db/billing_repo.py`. The backend builds the return URL. The frontend does not read
  Paymob's query string.

**S2. Card pack purchase and callback**

- Steps: buy a pack. Watch the intention call, the checkout page and the callback.
- Record: intention status (201) and body, checkout host (`eg.checkout.paymob.com`), the raw
  callback body, the `hmac` query value, the payment row status and the credit grant rows.
- Pass: the callback arrives at `/api/webhooks/paymob/transaction?hmac=...`. The HMAC verifies. The
  payment goes `paid` and credits are granted once. Replaying the same callback returns 200 and
  grants nothing twice.
- Code depends on this: `notification_base_url`, `WEBHOOK_PATH`, `card_integration_id`,
  `hmac_secret`, and `checkout_base` (default `https://eg.checkout.paymob.com`).

**S3. HMAC check in isolation**

- Steps: paste the raw callback from S2 into the Integration Wizard's HMAC Signature
  Troubleshooter (`https://wizard.paymob.com/`). It runs in the browser.
- Record: the computed HMAC and our computed value.
- Pass: both match.
- Code depends on this: the 20-field transaction HMAC concatenation in the transaction webhook
  route. A mismatch means every real callback is rejected.

**S4. Phone number on the intention**

- Steps: check out as the user with no phone. Then check out as a user with a stored phone in a
  local format, such as `01012345678`.
- Record: the checkout response, and `billing_data.phone_number` in the intention body.
- Pass: the user with no phone is stopped before Paymob is called, with `422` and
  `detail.code = "phone_required"`. The stored phone is sent as E.164 (`+201012345678`) and Paymob
  accepts it.
- Code depends on this: `lemely/core/phone.py` (`validate_phone`, `PHONE_REQUIRED`,
  `PHONE_INVALID`). The code sends no placeholder number. If Paymob rejects a valid E.164 number,
  record the response body and stop. That would need a code change.

**S5. Return page after login loss**

- Steps: pay, then clear the session cookie before the redirect completes.
- Record: the URL before and after login.
- Pass: login returns the browser to `/billing/return/<payment id>` and the query string is
  stripped.
- Code depends on this: `RETURN_PATH` and the login redirect in the frontend. No setting.

**S6. Abandoned payment and reconcile**

- Steps: start a payment and close the tab at the 3DS or OTP screen. Wait for the reconcile job.
- Record: that no callback arrived, the inquiry request and its response, and the final payment
  status.
- Pass: reconcile resolves the payment by inquiry on `merchant_order_id`. The inquiry uses a
  `Bearer` auth token, not `Token <secret key>`.
- Code depends on this: the inquiry call in `lemely/io/paymob/client.py` and `merchant_order_id`.
  The skill and our notes agree on the Bearer header.

**S7. Wallet purchase**

- Steps: none unless a wallet Integration ID is added to config.
- Record: write "not applicable" in the log.
- Pass: not applicable at HEAD. Settings have `card_integration_id`, `moto_integration_id` and
  `apple_pay_integration_id` only. If a wallet integration is ever added, pay with the test wallet,
  log `source_data` and confirm the HMAC. A null among the 20 signed fields needs the exact string
  form Paymob signs.
- Code depends on this: no wallet setting exists today.

**S8. Refund and void**

- Steps, for each of the following on a settled test payment and on a same-day payment:
  full refund, partial refund, a second partial refund, void.
- Record: each request, each response, the child transaction callback, the parent's `is_refunded`
  and `is_voided` callbacks, and the payment's refunded total.
- Pass:
  - Callbacks apply. Partial refunds add up. After a forced timeout, nothing retries before an
    inquiry.
  - Answer this: does Paymob refuse a refund before settlement? The Paymob skill says a refund
    returns funds after settlement and a void cancels before settlement, usually the same day.
    If a same-day refund is refused, only a void works on the day of purchase.
  - On a subscription payment, the admin void and refund dialogs offer "stop it renewing". Use
    it on one void and one refund. Confirm that the subscription ends and that no renewal is
    charged.
- Code depends on this: the admin refund and void routes (`reverseChange` on both). The 422 codes
  `reverse_unavailable` and `reverse_needs_full_refund`, and the outcome `nothing_ended`, are the
  messages an admin sees. No setting. If a same-day refund is refused, tell admins to void on the
  day of purchase.

**S9. Declined payment, then success**

- Steps: pay with the decline method from Paymob support. Then pay again on the same intention
  with a good card.
- Record: both callbacks and the payment status after each.
- Pass: the payment is `failed` after the decline. The later success on the same intention takes
  it to `paid`.
- Code depends on this: the failed-to-paid transition in the transaction callback handler. No
  setting.

### Phase B. Subscriptions (S10-S15)

Before this phase, confirm the account manager enabled Subscriptions and MOTO (§2).

**S10. Plan sync, first charge, subscription webhook**

- Steps: in the admin console, sync a plan tier to Paymob. Subscribe with a test card.
- Record: the plan create request and response, the first charge callback, and the raw
  subscription webhook, including the URL it arrived at.
- Pass:
  - The plan is created with a Bearer token and the MOTO Integration ID.
  - The first charge arrives as the intention's transaction callback and the payment is paid.
  - A `"Subscription Created"` webhook arrives at `/api/webhooks/paymob/subscription`. `hmac` is in
    the body and verifies over `"Subscription Createdfor<subscription id>"`.
  - Record whether a `"Successful Transaction"` webhook also fires for the first charge.
- Disagreement to settle: our client calls `POST api/acceptance/subscription-plans` (hyphen). The
  Paymob skill documents `POST api/acceptance/subscription_plans` (underscore). Record which
  path answers 2xx. The skill wins if they differ. The skill also says subscription events post
  to the intention's `notification_url`. Record whether the webhook reaches our fixed
  subscription route or the intention's URL.
- Code depends on this: `moto_integration_id`, `SUBSCRIPTION_WEBHOOK_PATH`, and the plan path in
  `lemely/io/paymob/client.py` (`create_plan`).

**S11. Retries, `retrial_days` and "Failed Overdue Transaction"**

- Steps:
  1. Set `grace_days` to 7 in the admin billing settings. Sync a new plan. `GET` it. Record
     whether Paymob accepts `retrial_days = 7` and what the plan returns.
  2. Create a second plan by hand with no `retrial_days`. Record the default. Our samples show
     `null`, and its meaning is undocumented.
  3. Force a failed renewal with the decline method, or a short-frequency plan. Record each retry
     and when `"Failed Overdue Transaction"` fires.
- Record: plan bodies, every webhook with timestamps, and the retry times.
- Pass: step 1 answers 2xx with `retrial_days = 7`. Answer these: does "Failed Overdue
  Transaction" fire for each failed retry, or only at the end? After a late retry succeeds, does
  the next billing date keep its original anchor and time of day? Answer from step 3.
- Code depends on this: `MAX_GRACE_DAYS` (7) in `lemely/core/subscription_rules.py` and the
  `grace_days_range` CHECK on `billing_settings`. They stay at 7 until step 1 passes. If Paymob
  rejects 7, lower both together. A test ties them. Also `GRACE_DAYS` (default 3) in
  `lemely/core/billing_defaults.py`, the value sent as `retrial_days` on a plan sync.
- Known limit to confirm: access grace follows the live `grace_days` setting, not the plan's
  synced `retrial_days`. A plan synced at 3 days keeps retrying for 3 days at Paymob after an admin
  raises `grace_days` to 7. Record how the customer's access and the admin plan drift flag behave
  in that gap.

**S12. Renewal charge**

- Steps: let a 7-day plan renew, or ask Paymob support to trigger a renewal.
- Record: the `"Successful Transaction"` webhook, then `GET subscriptions/{id}/last-transaction`
  with the shape of `order`, `api_source`, `integration_id` and `created_at`. Record whether a
  transaction callback also reaches `/api/webhooks/paymob/transaction`.
- Pass: the webhook arrives. `api_source` is `SUBSCRIPTION` and `integration_id` is the MOTO ID.
  With the MOTO integration's callback URL set (§2), a transaction callback arrives for the renewal.
- Code depends on this: `moto_integration_id` and the renewal path in the subscription webhook
  handler. An unmatched verified `SUBSCRIPTION` transaction callback logs at info and creates
  nothing. If no callback arrives, the drift check is the only backstop.

**S13. Time zones and the early-charge window**

- Steps: on the plan from S12, compare `created_at` in `last-transaction`, the timestamps in
  the webhook body and `next_billing` against the wall clock in Cairo.
- Record: each raw value and the Cairo wall time next to it.
- Pass: `created_at` is timezone-aware. Naive webhook timestamps read as `Africa/Cairo`.
  `next_billing` is a date. Then answer: how many days before our `current_period_end` can Paymob
  charge or fail a renewal? Is it within `EARLY_CHARGE_WINDOW`? Also record what
  `last-transaction` returns after a declined renewal.
- Code depends on this: `PAYMOB_ACCOUNT_TZ` and `parse_paymob_time`
  (`lemely/core/subscription_rules.py`), and `EARLY_CHARGE_WINDOW`,
  `NEXT_BILLING_LATER_TOLERANCE` and `NEXT_BILLING_EARLIER_TOLERANCE`
  (`lemely/db/subscription_repo.py`). `EARLY_CHARGE_WINDOW` is `MAX_GRACE_DAYS` days plus 6
  hours. A late retry shifts the anchor by up to `MAX_GRACE_DAYS`. If the observed gap is larger,
  widen the window.

**S14. Change the amount of a live subscription**

- Steps: on a plan with `use_transaction_amount = true`, send
  `PUT api/acceptance/subscriptions/{id}` with a new `amount_cents`. Let the next renewal run.
- Record: the PUT request and response, the `"updated"` webhook, and the next renewal's amount.
- Pass: the PUT succeeds, the renewal charges the new amount, and our handler ignores the
  `"updated"` webhook. The Paymob docs say nothing about this combination.
- Code depends on this: `subscription_amount_updatable` (`PaymobSettings`, env
  `LEMELY_PAYMOB__SUBSCRIPTION_AMOUNT_UPDATABLE`), default `true`. If the PUT fails, set it to
  `false`. Then upgrades answer 409 `upgrade_unavailable` with `detail.next =
  "cancel_and_resubscribe"`, seat reductions that need a lower amount are refused, and extra seats
  are charged at each renewal by the fallback job. Also `AMOUNT_SYNC_WINDOW` (2 days).

**S15. Cancel, suspend, resume, and saved-card charge**

- Part 1, subscription lifecycle:
  - Steps: `POST subscriptions/{id}/cancel`. Cancel again. Suspend and resume a second
    subscription once each. Try to cancel a suspended subscription.
  - Record: each status code and body, the `canceled` and `suspended` webhooks, and the second
    cancel's response.
  - Pass: the cancel returns `state: "canceled"` and a `"canceled"` webhook. The second cancel's
    status is recorded. Record whether Paymob accepts a cancel on a suspended subscription.
  - Code depends on this: the cancel and resume handling in `subscription_repo.py`. A 4xx is read
    back and only `canceled` counts as done. A 5xx or timeout is treated as unknown and retried
    by the sweep.
- Part 2, saved-card charge (MOTO):
  - Steps: confirm MOTO is enabled. Create a MOTO intention, then `POST
    api/acceptance/payments/pay` with a saved token, once with the `Token` header and once
    without.
  - Record: both responses and the pay response body for a success and a decline.
  - Pass: the charge succeeds. Record whether it works with and without the header.
  - Disagreement to settle: our client sends no `Authorization` header on `payments/pay`, as the
    live docs we read say. The Paymob skill shows `Authorization: Token {SECRET_KEY}`. The skill
    wins. If only the header works, the client needs it.
  - Code depends on this: the `payments/pay` call in `lemely/io/paymob/client.py`.

### Phase C. Saved-card charges and upgrades (S16-S20)

**S16. Saved-card callback**

- Steps: run a successful saved-card charge (S15 part 2).
- Record: the raw callback body.
- Pass: the callback reaches `/api/webhooks/paymob/transaction` with the MOTO `integration_id`.
  Its signed `order.id` equals the intention's `intention_order_id`. The HMAC verifies.
- Code depends on this: `moto_integration_id` and `intention_order_id`.

**S17. Declined saved-card charge**

- Steps: charge a saved card with the decline method from Paymob support.
- Record: the pay response and the callback.
- Pass: pay answers `success: false, pending: false`. The callback agrees. The payment is
  `failed`, auto top-up is disabled (`disabled_reason = charge_failed`) and the email is queued.
- Code depends on this: the MOTO charge handler in `merchant_charge_repo.py`.

**S18. Minimum charge amount**

- Steps: create a prorated upgrade for 1 piaster on the last day of a period, or charge a 1
  piaster saved-card amount.
- Record: Paymob's response and any error text.
- Pass: Paymob accepts it. If Paymob rejects small amounts, record the minimum.
- Code depends on this: no constant yet. If Paymob has a floor, add one to the upgrade and
  saved-card charge paths.

**S19. Upgrade checkout with a saved card**

- Steps: open an upgrade checkout with `card_tokens` set to one saved test card, on the card
  (3DS) integration. Pay with the saved card, then repeat once with a new card.
- Record: the checkout screen, the callback and the return URL. Record whether a token saved on
  one integration works on the other (card and MOTO), and whether a mode mismatch gives a 4xx.
- Pass: Unified Checkout shows the saved card and also lets the payer enter a new one. 3DS runs.
  The callback carries the card `integration_id`. It settles the `upgrade_proration` payment. The
  browser lands on `/billing/return/<payment id>`.
- Code depends on this: `card_tokens` on the intention and `card_integration_id`.

**S20. Two upgrade checkouts**

- Steps: open an upgrade checkout and abandon it. Open a second and pay it. Then pay the first
  within the hour.
- Record: both payments' statuses and the return page text.
- Pass: the second applies. The first is converted to credits and the return page says so.
- Code depends on this: the superseded-payment conversion in `merchant_charge_repo.py`. It needs a
  `credit_conversion_rates` row for the currency (see L1).

## 5. Go-live checks L1-L7

Run these after Paymob finishes its approval stages (paperwork, contract, risk, technical).
Code alone does not make an account live.

- **L1. Live keys and IDs.** Production uses the Live secret, public and API keys, the Live HMAC
  secret, and the Live card, MOTO and Apple Pay Integration IDs. Set
  `LEMELY_PAYMOB__EXPECT_LIVE=true` in the production deploy once Live keys are installed. The
  startup guard in `lemely/runtime/config.py` then refuses to start on a Test key. It is off by
  default and `.github/workflows/deploy.yml` does not set it yet. Check that the app starts.
- **L2. Origins.** `notification_base_url` and `redirection_base_url` are the production origin.
  They are never a hooks.paymob.com or tunnel URL.
- **L3. Callback URLs.** In the Paymob dashboard, set each Live integration's processed-callback
  URL to the transaction webhook. Set the MOTO integration's too. Register the subscription URL.
- **L4. Plans.** Re-sync every sellable plan tier against the Live account (`force_new`) before
  enabling subscription checkout. A plan id from the Test account gives
  `404 invalid subscription plan id` on Live.
- **L5. First real payments.** Take one small card payment end to end, then refund it. On the
  first real transaction of each method with no sandbox path, check the Integration ID, the
  callback field shape and the HMAC. Log the first raw callback per method. For kiosk, expect the
  callback hours or days later and rely on inquiry. Check refund support per method first, since
  kiosk has no refunds and some BNPL providers refund in full only.
- **L6. MOTO.** The Live MOTO Integration ID is set, and its processed-callback URL is set.
- **L7. Chargeback liability.** Lemely accepts chargeback liability for unattended MOTO charges
  only: auto top-up, the fallback seat charge and Paymob renewals. Upgrades and seat purchases run
  through 3DS. Record who approved this.

Also before launch:

- Set the EGP credit conversion rate in the admin console (a `credit_conversion_rates` row for
  each live currency). The migration seeds none. Until a row exists, every superseded payment
  alerts and needs a manual refund, and nothing re-runs the conversion afterwards.
- Check that `billing_settings` row `id = 1` exists (validity months, `grace_days`).

### Alerts to create

Create one log-based alert in GCP for each event name below.

Paymob webhooks and HMAC:

- `paymob_subscription_webhook_failed`: handling a verified subscription webhook raised.
- `paymob_subscription_webhook_malformed`: a subscription webhook body failed validation.
- `paymob_hmac_failure_unrecorded`: an HMAC failure could not be counted, so the failure count is
  too low.
- `subscription_webhook_not_deduplicable`: a subscription webhook lacked the facts needed to
  de-duplicate it, so it was refused.
- `paymob_unexpected_integration`: a genuinely signed transaction carried an integration id not in
  config. Nothing was settled. Follow
  [§5.11](../deployment.md#511-runbook-a-payment-held-for-a-foreign-integration).

Rate-based metrics, not per-event alerts: `paymob_subscription_hmac_mismatch` and the
transaction-route HMAC mismatch. A rotated HMAC secret rejects every callback with 401, so alert on
the rate.

Subscription renewals and drift:

- `subscription_link_conflict`: a Paymob subscription id conflicts with the one already linked.
- `subscription_paymob_missing`: Paymob no longer has the subscription, so the row ended.
- `subscription_next_billing_disagrees`: Paymob's `next_billing` differs from our period end by
  more than the tolerance.
- `subscription_renewal_without_payer`: a renewal arrived for a subscription with no payer.
- `subscription_renewal_for_unusable_tier`: a renewal arrived for a tier that can no longer be used.
- `subscription_renewal_paid_without_subscription`: a renewal payment matched no subscription.
- `subscription_renewal_after_cancel_request`: a renewal was paid after the customer asked to
  cancel.
- `subscription_charge_on_ended_subscription`: a charge landed on a subscription that had ended.
- `subscription_charge_after_terms_cancel`: a charge landed after a cancel caused by a terms change.
- `subscription_renewal_underpaid`: a renewal charged less than expected.
- `subscription_renewal_paid_above_expected`: a renewal charged more than expected.
- `subscription_renewal_paid_previous_amount`: a renewal charged the amount before a change.
- `renewal_seat_payment_credited`: a renewal seat payment arrived too late and became credits.

Cancel, grace and refunds:

- `paymob_cancel_refused`: Paymob refused a cancel request.
- `subscription_cancel_retrying`: a cancel keeps failing and is being retried.
- `subscription_resumed_after_cancel`: a resume could not be honoured because the plan had ended.
- `subscription_grace_extension_failed`: extending access for a failed renewal raised.
- `subscription_grace_end_failed`: ending a grace period raised.
- `subscription_old_period_refunded`: a refund hit an earlier period. Handle by hand.
- `subscription_future_period_refunded`: a refund hit an early-charged period that has not
  started. Handle by hand.
- `subscription_refund_with_later_paid_period`: a full refund of the current period while a later
  period is paid. It ends nothing. Handle by hand.
- `admin_refund_reverse_unavailable`: an admin asked to stop a renewal on a refund that could not
  do it.
- `admin_manual_expiry_failed`: an admin manual expiry of one row raised.

Amount pushes and seats:

- `subscription_amount_push_failed`: pushing a new amount to Paymob failed. The window refusal
  holds until the amount is confirmed.
- `paymob_amount_put_unknown_repeated`: the amount PUT keeps ending with an unknown result.
- `extra_seats_dropped`: extra seats were removed from a subscription.
- `extra_seats_drop_stuck`: dropping extra seats is stuck on an unknown payment.
- `extra_seat_charge_duplicate`: more than one paid charge exists for the same seat renewal.
- `extra_seat_terms_unknown`: the seat price could not be worked out from the subscription's terms.
- `seat_ceiling_setting_missing`: the seat ceiling setting is missing.
- `seat_grace_setting_missing`: the seat grace setting is missing.
- `seat_allowance_grant_failed`: granting one seat allowance raised. The others went ahead.

Merchant charges and upgrades:

- `merchant_charge_post_claim_error`: an error after a saved-card charge was claimed.
- `merchant_charge_sweep_failed`: the sweep rolled back one payment and carried on.
- `merchant_charge_sweep_gave_up`: the sweep stopped retrying a payment after repeated errors.
- `merchant_charge_sweep_error_note_failed`: the sweep could not record its own error note.
- `merchant_charge_unconvertible`: a superseded payment could not become credits. Refund by hand.
- `merchant_charge_paid_without_subscription`: an upgrade charge was paid with no subscription to
  apply it to.

Auto top-up:

- `auto_topup_sweep_failed`: the top-up sweep raised for one payment.
- `auto_topup_card_missing`: a top-up was due but no saved card was found.
- `auto_topup_no_consent`: a top-up was due but no consent was found.
- `auto_topup_enqueue_failed`: queueing a top-up charge raised.

Credits and usage:

- `credit_validity_setting_missing`: the `billing_settings` row was deleted. Restore `id = 1`
  (validity 12 months, or the admin value). The sweeper then settles the stuck pack payments.
- `usage_settle_on_closed_job`: a settle was refused because the job had closed.
- `usage_hold_lost_mid_run`: a hold was lost during a run, so that run is unbilled.
- `usage_deferred_unbound`: a deferred usage charge had no job to bind to.
- `usage_job_stranded_holds`: the sweep found and released holds stranded on a job.
- `usage_expire_job_failed`: expiring a job failed. The job stays open and is retried hourly.
- `usage_expire_grant_failed`: expiring one grant failed and was skipped.
- `usage_lease_cap_reached`: a job reached the cap of 3 leases. The sweeper expires the hold.

## 6. Results log

Copy this table into the run's ticket. Add one row per check, per run. Evidence is a link to the
saved raw bodies, not the bodies themselves. Never paste keys or card data.

| Check | Date | Who | Result (pass, fail, n/a) | Evidence link | Follow-up |
|---|---|---|---|---|---|
| S1 | | | | | |
| S2 | | | | | |
| S3 | | | | | |
| S4 | | | | | |
| S5 | | | | | |
| S6 | | | | | |
| S7 | | | | | |
| S8 | | | | | |
| S9 | | | | | |
| S10 | | | | | |
| S11 | | | | | |
| S12 | | | | | |
| S13 | | | | | |
| S14 | | | | | |
| S15 | | | | | |
| S16 | | | | | |
| S17 | | | | | |
| S18 | | | | | |
| S19 | | | | | |
| S20 | | | | | |
| L1 | | | | | |
| L2 | | | | | |
| L3 | | | | | |
| L4 | | | | | |
| L5 | | | | | |
| L6 | | | | | |
| L7 | | | | | |
| EGP conversion rate set | | | | | |
| Alerts created | | | | | |

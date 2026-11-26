# Paymob gap-fill research (2026-11-02)

Base (Egypt): `https://accept.paymob.com`. DOCS = https://developers.paymob.com/paymob-docs/ ; every page has a `.md` twin. Cached raw copies: `/tmp/claude-1000/-home-sico-Code-Lemely/f6a6c64c-5a9f-41bf-aa18-2a302c3f9b4d/scratchpad/paymob-research/raw/`.
Tags: [D] = stated in official docs, [PM] = official Paymob Postman collection / AI-skill repo, [INF] = my inference from indirect evidence (NOT a Paymob statement), [?] = unknown.

## 1. QuickLink (payment links) API

Source: DOCS/quicklink-apis/overview.md (updated 2026-06-28), create-quicklink.md (2026-09-23), cancel-quicklink.md (2026-06-01), integration-paths/no-code/payment-links.md.

- Auth: **Bearer auth token** from `POST api/auth/tokens` with `{api_key}`; NOT the `Token sk_...` secret key used by the Intention API. Auth token lasts 60 min [PM: Subscription Postman collection, https://github.com/PaymobAccept/API-Postman-Collections/blob/main/Paymob%20Subscription%20Module%20API.postman_collection.json; subscription docs say "valid for an hour"].
- **Create**: `POST api/ecommerce/payment-links`, content type `multipart/form-data` [D create-quicklink.md]. All fields are marked optional in the schema:
  - `amount_cents` (string, cents), `expires_at` (ISO datetime, must be future: 400 "expires_at can't be in the past"), `reference_id` (merchant id for the link), `payment_methods` (integration ID, must match `is_live`; the field is singular-valued "Integration ID of the payment method"), `is_live` (true/false), `description`, `notification_url`, `payment_link_image` (file).
  - Customer fields: `full_name`, `email` (if given, customer is emailed), `phone_number` (international +20..., if given, customer gets SMS).
  - Collect toggles: `collect_phone_number`, `collect_email_address`, `collect_customer_name`, `collect_billing_details`, `collect_shipping_details`, `allowed_countries` (comma list).
  - 200 response: `id`, `reference_id`, `shorten_url` (e.g. `https://paymob.link/xxxxx`), `client_url` (accept.paymob.com/api/ecommerce/payment-link/...), `state` ("created"), `paid_at`, `expires_at`, `amount_cents`, `redirection_url`, `notification_url`, `order` (Paymob order id), `origin`.
  - Errors: 400 `{"message":"Reference ID already exists."}` -> **`reference_id` uniqueness IS enforced** (contrast with Intention `special_reference`, see section 4); 401 `incorrect credentials`; 404 integration ID/mode mismatch.
- **Cancel**: `POST api/ecommerce/payment-links/cancel`, body `{"payment_link_id": "<id>"}` (JSON) -> `{success:true, message:"Canceled by merchant", payment_link_id}` [D cancel-quicklink.md]. Dashboard text says only **unpaid** links can be cancelled [D payment-links.md].
- Callback: `notification_url` is "Notification URL to receive the callback" [D]; overview warns "rely on backend callbacks, not the response (redirection) callback alone" [D overview.md]. The docs do NOT state that the QuickLink callback is the same Transaction Processed Callback with the same HMAC; the response has an `order` id and the link is paid through normal checkout, so it is very likely the same callback shape [INF]. Verify with a test link.
- QuickLink creation on the dashboard needs account enablement for "the new experience" (FAQ error "Next user doesn't exist" -> contact account manager) [D need-help/faqs.md, 2026-10-04].
- Link expiry has no default stated [?].

## 2. Subscriptions

Sources: DOCS/payments-and-features/core-features/subscriptions.md; DOCS/subscription/* (plan + subscription + actions + hmac-calculation-for-subscription-callback); [PM] Postman collection above.

- **Egypt availability**: Postman collection lists Egypt base URL `https://accept.paymob.com` first for the Subscription module [PM]. The docs have no "not available in Egypt" caveat and are not region-restricted [D]. Account enablement is not stated [?] (confirm with account manager).
- Prereqs [PM]: an **online 3DS integration ID** (enrolment) AND a **MOTO integration ID** (recurring charges). Optional 3DS-*verification* integration (zero-amount card check/free trial) must be requested from support@paymob.com.
- Endpoints (all Bearer auth-token; docs/subscription/...):
  - Create plan `POST api/acceptance/subscription-plans` body: `frequency` (required; 7,15,30,60,90,180,360 days), `name` (required, <=200), `integration` (required, MOTO id), `amount_cents`, `use_transaction_amount` (default false: first payment only saves card and renewal uses `amount_cents`; true: first transaction amount is used), `webhook_url`, `reminder_days` (email reminder), `retrial_days`, `number_of_deductions` (null = open ended), `plan_type` ("rent"; Postman text lists more), `is_active`, `fee`. Wrong frequency -> 400.
  - Plan actions: `PUT api/acceptance/subscription-plans/{id}` (amount_cents, number_of_deductions, integration only), `POST .../{id}/suspend`, `POST .../{id}/resume`, `GET api/acceptance/subscription-plans`. Suspending a plan only stops NEW enrolments; existing subscriptions keep running [PM].
  - Subscription actions: `POST api/acceptance/subscriptions/{id}/suspend`, `/resume` (400 "The subscription isn't suspended" if not suspended), `/cancel` (permanent), `POST .../{id}/register_webhook` body `{url}`, plus update, list details/transactions/cards, add/delete secondary card, change primary card.
- **First payment / creation**: via the Intention API (`POST v1/intention/`) with two extra fields: `subscription_plan_id` (required) and `subscription_start_date` (optional; only effective when `use_transaction_amount` is false). Creation completes by one 3DS transaction that saves the card [D subscription/create-subscription.md]. Wrong plan/key pairing -> 404 `invalid subscription plan id`.
- Subscription id lookup: from the subscription callback, or "Subscription Inquiry" using the first 3DS transaction id [D faqs.md].
- **Webhook payload** (POST, JSON; hmac is IN THE BODY) [D hmac-calculation-for-subscription-callback.md]: `{paymob_request_id, subscription_data:{id, client_info, frequency, name, plan_id, state, amount_cents, starts_at, next_billing, reminder_date, ends_at, resumed_at, suspended_at, webhook_url, integration, initial_transaction}, trigger_type, hmac}`; the Woo plugin also reads `transaction_id` from the body for charge events [INF from https://plugin-repo.wpbeacon.io/wporg/paymob-for-woocommerce/commit/80685789aa8bd7df1374df5856e9b81cf77550c5].
  - `trigger_type` catalogue: "Subscription Created", suspended, canceled, resumed, updated, add_secondry_card (sic), change_primary_card, delete_card, register_webhook, "Successful Transaction" (billing cycle), "Failed Transaction", "Failed Overdue Transaction" (failed retry).
  - HMAC: SHA-512 over the string `"{trigger_type}for{subscription_data.id}"` (e.g. `suspendedfor1264`) keyed with the account HMAC secret; compare to body `hmac`.
  - Weakness: HMAC does not cover amount/transaction id, so for charge events re-fetch the transaction (inquiry) before crediting.
- Not in docs [?]: trial handling beyond the verification integration, proration, what happens to subscriptions after `retrial_days` exhausted (state?), cancellation at period end vs immediate, whether renewals also emit a normal Transaction Processed callback.

## 3. Webhook delivery (retries, response, timeout, IPs, duplicates)

Sources: DOCS/webhook-callbacks-and-hmac/transaction-callbacks.md (2026-06-01) and overview.md; SKILL https://github.com/PaymobAccept/Paymob-AI-Integration-Skill (references/hmac-verification.md, transaction-inquiry.md).

- Re-checked: **no official statement** of retry schedule/count, expected status code, timeout, source IP ranges, ordering, or duplicate-delivery semantics. Only: callbacks fire when a txn is processed "or after any action on the payment" (refund/void/capture) [D transaction-callbacks.md; webhook-testing-tool page says "after a transaction succeeds, fails, or when an action (Refund, Void, Capture) is performed on a parent transaction"].
- The callback schema contains a field `transaction_processed_callback_responses` ("array containing responses received from downstream systems after processing the transaction callback") [D transaction-callbacks.md]. [INF] Paymob records your endpoint's response per attempt, which hints that delivery is tracked (dashboard may show it); not a documented retry contract.
- Vendor skill guidance (not spec): reply 200 promptly; "webhook senders typically retry on non-2xx or timeout"; HMAC mismatch -> 401; dedupe on `obj.id` with a DB unique constraint; compare-and-set order state; 2xx only after commit [SKILL hmac-verification.md]. A third-party Odoo plugin's FAQ says "Paymob retried a callback" is a real case [https://technovision.dev/docs/paymob-payment-provider/faq] [INF: duplicates exist in practice].
- Docs caution: authenticity is by HMAC only; no IP allowlist is published [D].
- Free test tool: Paymob's webhook testing tool at hooks.paymob.com [D webhook-testing-tool].

## 4. Intention API details

Sources: DOCS/intention-apis/create-intention.md (2026-10-15), update-intention.md (2026-06-22), overview.md, checkout-experiences/pixel-embedded.md.

- `POST v1/intention/`, header `Authorization: Token <secret_key>`. Required: `amount` (cents), `currency`, `payment_methods` (int IDs or names), `billing_data.first_name/last_name/email` (schema); error example shows `phone_number` required too. Max lengths: item name 50, item description 255, first/last name 50.
- **`items` sum validation**: "When multiple items are provided, the sum of all item amounts must equal the total transaction amount" [D]. Each item requires `name` + `amount` (400 otherwise). Items array itself optional.
- **`special_reference`**: documented as "unique", returned as `merchant_order_id` in callback [D]. **No documented duplicate error and no documented enforcement** (QuickLink's `reference_id` does document one) [?]. [INF] the official WooCommerce plugin builds it as `{order_id}_{time()}` (the line `'special_reference' => $order_id . '_' . time()` is visible, and the webhook strips the last 11 chars `substr(..., 0, -11)`), i.e. one reference per attempt with a timestamp suffix, suggesting plugin authors avoid reuse. Plan: make `special_reference` = our payment-attempt UUID (unique per intention), keep own order id separately in `extras`.
- **`extras`**: free-form object, returned in callbacks "under the payment key claims object" (`obj.payment_key_claims.extra`) [D create-intention.md].
- **Expiry**: `expiration` (seconds, example 3600) is accepted but undocumented (no default). Client secret "is unique for each Order and expires in an hour" [D pixel-embedded.md]. Behaviour after expiry/after a failed attempt not documented [?].
- **Retrieve intention**: no GET/retrieve endpoint exists in docs (only Create, Update). Use transaction inquiry [D intention-apis/overview.md lists only create + update].
- **Update**: `PUT v1/intention/{client_secret}/`; can change amount, payment_methods, items, billing_data, special_reference, expiration, notification_url, redirection_url. `billing_data.first_name/last_name/email/phone_number` required on update; error example demands `accept_order_id` ("pass the order ID related to the client secret") [D].
- **Per-intention URL overrides**: yes. FAQ: "define or override callback URLs directly in the intention creation request" via `notification_url` and `redirection_url` [D faqs.md]. Create page: notification_url "Supported with all payment methods"; redirection_url "Card and Wallet only". Update page still says notification_url "only card Integration IDs" (stale/contradictory; trust the create page + FAQ, verify with a wallet test). `notification_url` also receives the card token callback [D].
- **Minimum amount**: no general Intention minimum documented [?]. Only method-specific: bank-card payout min 5 EGP (payouts, not collection); installments min order EGP 1,000 [D llms.txt].
- Integration ID must be passed as an **integer**, not a string, and must match key mode (Test/Live) else 404 [D faqs.md].

## 5. Mobile wallet inside Unified Checkout

Sources: DOCS/payment-methods/mobile-wallets-egy-ksa.md (2026-06-01); SKILL references/test-credentials.md, payment-methods.md, intention-api.md.

- Wallets: Vodafone Cash, Orange Cash, e& money, We Pay, bank wallets; EGY only; refunds full/partial; channels APIs/SDKs/plugins/links; **Test and Live integration IDs both exist** [D].
- Flow: customer enters wallet number, then wallet MPIN/OTP, entirely on the hosted page [SKILL intention-api.md line "completes card entry, 3D Secure, or wallet OTP entirely on this Paymob-hosted page"].
- Test wallet: number `01010101010`, MPIN `123456`, OTP `123456` [SKILL test-credentials.md; same as docs test-credentials page].
- Callback timing: docs only say callbacks fire on success or decline; an abandoned challenge produces **no callback** [SKILL payment-methods.md; DOCS overview]. The `pending` boolean exists on the transaction object and is part of the HMAC string [D], but the docs never say whether a pending-state callback is sent for wallets or how long a wallet request stays pending [?]. Design: treat `success=false & pending=true` as non-final and run an inquiry reconciliation job.
- Wallet callbacks may have null/different `source_data` fields; SKILL says log the first real wallet callback and decide null stringification for HMAC explicitly [SKILL hmac-verification.md].

## 6. Apple Pay on hosted Unified Checkout

Sources: DOCS/payment-methods/apple-pay-all-regions.md (2026-06-01), need-help/setup-guides/apple-pay-setup.md (2026-07-28) + domain-verification page, checkout-experiences/overview.md, unified-checkout-redirection.md.

- Apple Pay: EGY supported, refunds full/partial, **"Live integration IDs only"** [D]. So not testable on the test account.
- Setup matrix [D apple-pay-setup.md]: Mobile SDK = certificates only; Pixel = domain verification + certificates; WooCommerce = domain verification + certificates; webviews unsupported. **Redirect/Unified Checkout is not listed at all.**
- Docs for hosted Unified Checkout never mention Apple Pay; docs say Pixel is "Embedded Card, Apple Pay, and Google Pay" [D checkout-experiences/overview.md]. Whether the hosted page shows an Apple Pay button, and whether it needs domain verification (it would be on Paymob's domain, so plausibly none) is **undocumented** [?]. Domain verification, where needed, = host `/.well-known/apple-developer-merchantid-domain-association` file from an Apple Developer Merchant ID [D]. Certificates: Merchant Identity + Payment Processing certs, emailed to Paymob support [D / report 01].
- Practical: Apple Pay via Pixel is the only documented route; plan it as a post-go-live phase with a Live integration ID.

## 7. Transaction inquiry

Sources: DOCS/transaction-inquiry-apis/transaction-inquiry.md (2026-08-04), .../by-transaction-id.md, .../by-order-id-or-reference.md (2026-06-28), FAQ.

- By transaction id: `GET api/acceptance/transactions/{transaction_id}` with `Authorization: Bearer <auth_token>` [D].
- By Paymob order id **or** our `special_reference`: `POST api/ecommerce/orders/transaction_inquiry` body `{auth_token, order_id}` or `{auth_token, merchant_order_id}` (merchant_order_id = the `special_reference`) [D]. Returns the **last** transaction of that order only (so earlier failed attempts are not listed) [D "Retrieve the last transaction details"]. The auth token goes in the JSON body (docs also say Bearer; send both if unsure).
- Auth token: `POST api/auth/tokens` `{api_key}`; valid 60 min; test-mode API key sees test txns [PM; SKILL transaction-inquiry.md]. API key is same for Test and Live [PM], so mode comes from the key/integration.
- Docs position inquiry as "manual checks or fallback when a callback is missed", callbacks primary [D]. Response object has same shape as callback `obj` (`pending`, `success`, `is_voided`, `is_refunded`, `refunded_amount_cents`, `order.id`, `order.merchant_order_id`).
- Rate limits not documented [?].

## 8. Marketplaces / third-party collection

Sources: DOCS/payments-and-features/core-features/split-features.md (2026-06-01), DOCS/split-features-implementation.md (2026-06-01); reports 03.

- **Split Amount**: "One payment, multiple recipients"; use cases listed: "Marketplaces with multiple sellers, platforms taking commissions, revenue-sharing" [D split-features.md].
- Implementation: add `split_amounts: [{mid: <connected_MID>, amount_cents, description}, ...]` to Create Intention. Checkout UX unchanged; "Each feature will require configuration on your account from our side ... contact support@paymob.com" [D split-features-implementation.md].
- Each recipient is a "connected MID" (a Paymob merchant id), so tutors would need to exist as Paymob merchants/sub-merchants; docs do not state KYC level, whether Lemely can hold funds then release, or how refunds split [?].
- No escrow/hold-and-release or "collect on behalf of" guidance exists in the docs. Alternative already in report 03: Paymob Send (payouts) to pay tutors from our balance (needs separate agreement).
- Callback shape for Split Payment (multi-card) differs (`is_split_payment`, `transactions[]`: two txns per sub-payment); sample only for split-payment, not split-amount [D].

## Still unknown: ask Paymob (support@paymob.com / account manager)

1. Webhook: retry count/schedule, expected HTTP status, timeout, order/duplicate guarantees, source IPs, whether a manual "resend callback" exists in dashboard.
2. Does wallet checkout emit a callback for `pending=true`; how long is a wallet request pending before auto-fail; is there a distinct callback for wallet timeout/cancel.
3. `special_reference`: hard uniqueness (duplicate returns 400?) or just informational; allowed length/charset; can a failed intention be re-paid on the same client secret; `expiration` default/max and behaviour after expiry; client secret single-use?
4. Minimum/maximum amount per method (card, wallet) on our contract.
5. QuickLink callback: same Processed Callback + same HMAC? Default link expiry? Is QuickLink enablement ("new experience") needed on our account?
6. Subscriptions: enabled for our Egypt account? need MOTO + 3DS integration IDs provisioned; behaviour after `retrial_days` exhausted; whether renewals also fire a Transaction Processed Callback; fees on MOTO renewals; Egyptian CBE recurring-card rules (OTP-less MIT permitted?).
7. Apple Pay: shown on hosted Unified Checkout? domain verification needed there? Egypt lead time for certs; Live-only so no sandbox.
8. Marketplace: split_amounts for tutors (connected MID onboarding/KYC for individuals), hold-and-release timing, refund/chargeback allocation, whether Lemely needs its own licence; fee on split.
9. Update-intention `notification_url` "card only" statement vs create page "all methods" (contradiction).
10. Inquiry/auth endpoints rate limits; is `api/ecommerce/orders/transaction_inquiry` returning all attempts for an order in any way.
11. Does `extras` come back on the redirect GET and inquiry response, or only the processed callback.

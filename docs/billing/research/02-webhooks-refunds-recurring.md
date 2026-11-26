# Paymob research 02: webhooks, HMAC, states, post-payment ops, saved cards, subscriptions, links

Researched 2026-11-02. Docs root: https://developers.paymob.com/paymob-docs/ . Every page fetched as `<url>.md`; the site started returning HTTP 403 (WAF) to my IP partway through, so QuickLink request-body details were NOT retrieved (see Open questions).

Source key (short names used below):
- DOC-CB = https://developers.paymob.com/paymob-docs/webhook-callbacks-and-hmac/transaction-callbacks.md (updated 2026-06-01)
- DOC-OV = .../webhook-callbacks-and-hmac/overview.md
- DOC-HMAC = .../webhook-callbacks-and-hmac/hmac/hmac-transaction-callback.md
- DOC-HMAC-TOK = .../webhook-callbacks-and-hmac/hmac/hmac-for-card-tokens.md
- DOC-HMAC-SUB = .../subscription/hmac-calculation-for-subscription-callback.md
- DOC-REFUND/VOID/CAPTURE = .../manage-payment-apis/{refund,void,capture}.md
- DOC-INQ = .../transaction-inquiry-apis/transaction-inquiry/{by-transaction-id,by-order-id-or-reference}.md and .../core-features/transaction-inquiry-and-reports.md
- DOC-SUB-* = .../subscription/*.md
- SKILL = Paymob's own official AI skill repo https://github.com/PaymobAccept/Paymob-AI-Integration-Skill (files under skills/paymob-integration/references/). First-party but not the docs site; some content is vendor-authored guidance, not a spec.
- GH = third-party implementations (frappe/payments, iMohamedSheta/Tickizy, ahmedehab2/gahezlak) cross-checks.

Base URL for Egypt: `https://accept.paymob.com` (all `api/...` paths below are relative to it; confirmed by `.../api/acceptance/post_pay` Egypt URL in the SDK docs in llms.txt).

---

## 0. TL;DR for implementation

1. Two callbacks: "Transaction Processed" (server POST, JSON, source of truth) and "Transaction Response" (browser GET redirect, query params, never trust). (DOC-CB)
2. HMAC = HMAC-SHA512, key = the account "HMAC secret" (Dashboard > Settings > API Keys), message = 20 values concatenated with no separator in a fixed order (section 2). For the POST callback, the `hmac` value arrives in the URL query string (`?hmac=...`), NOT in the JSON body. Subscription callbacks are the exception: hmac is in the body.
3. Paymob only sends a transaction callback when the transaction succeeds or is declined (DOC-OV). Abandoned 3DS/OTP screens and unpaid kiosk/wallet attempts therefore produce no callback; you need Transaction Inquiry reconciliation as a fallback (DOC-INQ explicitly says so).
4. Refund: `POST /api/acceptance/void_refund/refund` with `Authorization: Token <secret_key>`, body `{transaction_id, amount_cents}`; partial refunds allowed; supported for everything except Kiosk. Void: card only, before settlement (same business day). Capture: card Auth transactions only.
5. Saved card: card-token callback (type `TOKEN`) arrives after first payment; use it via `card_tokens` array (CIT) or MOTO pay endpoint (MIT). Subscriptions module exists, is card-only (requires a MOTO integration id), no explicit Egypt statement in docs.
6. Apple Pay: "Live integration IDs only" (no test integration), so it cannot be exercised on the TEST account. (payments-and-features/payment-methods/apple-pay-all-regions.md)

---

## 1. The two callbacks

Source: DOC-CB, DOC-OV.

| | Transaction Processed | Transaction Response |
|---|---|---|
| HTTP | POST | GET |
| Content | JSON | query params appended to your URL |
| Direction | server to server | customer's browser redirect |
| Use | update orders/business logic | show result page only |

"Don't use the transaction response callback to update your order status, as the customer may never complete the redirect. Always rely on the transaction processed callback instead." (DOC-CB). Also quickLink overview: "Always rely on backend callbacks, not the response (redirection) callback alone, to confirm payment success." (quicklink-apis/overview, via llms.txt)

When sent: "Paymob sends the transaction callback only if the transaction succeeds or is declined" (DOC-OV). It is also sent "after any action on the payment" i.e. refund/void/capture produce callbacks (DOC-CB; webhook-testing-tool page: "after a transaction succeeds, fails, or when an action (Refund, Void, or Capture) is performed on a parent transaction").

Where URLs are set:
- Per intention: `notification_url` (processed/POST) and `redirection_url` (response/GET) parameters on Create Intention (referenced in create-card-token page: "the endpoint sent in the notification_url parameter while creating the intention (Step 1), or in the endpoint configured as a processed callback URL in the integration ID you used").
- Per integration id in Dashboard > Settings > Payment Integrations (DOC-CB links to FAQ "Getting Integration Credentials"). Plugins and Payment Links rely on the per-integration setting (SKILL post-integration.md).
- Test tool: https://hooks.paymob.com/ (temporary endpoint capturing payload+headers; keeps no history; also works for subscription webhooks) (webhook-testing-tool.md).

### 1.1 Key fields highlighted by the docs (DOC-CB)
`id` (transaction id), `success` (true/false), `order.id` (Paymob order id; correlate with your own order), `is_refunded`, `refunded_amount_cents` (total; one transaction can have several partial refunds), `is_voided`, `is_captured`, `captured_amount` (total; several partial captures possible). The full field table on the site is a dynamic component not present in the .md; use the shape below.

### 1.2 Processed callback payload shape
The docs' JSON example is not in the .md rendering. The envelope per frappe/payments (GH) and docs HMAC text is `{"type": "TRANSACTION", "obj": {...transaction...}}` and the HMAC is computed from `obj`. The transaction object has the same shape as the Refund/Void/Capture API responses and the Transaction Inquiry response (DOC-REFUND, DOC-INQ; SKILL transaction-inquiry.md: "same shape as what arrives in the obj of a callback"). Full field list (from DOC-INQ by-transaction-id example, a successful card payment, dotted = nested):

Top level of `obj`:
`id, pending, amount_cents, success, is_auth, is_capture, is_standalone_payment, is_voided, is_refunded, is_3d_secure, integration_id, profile_id, has_parent_transaction, order{...}, created_at, transaction_processed_callback_responses, currency, source_data{type, pan, sub_type, tenure}, api_source, terminal_id, merchant_commission, installment, discount_details, is_void, is_refund, data{...gateway-specific...}, is_hidden, payment_key_claims{...}, error_occured, is_live, other_endpoint_reference, refunded_amount_cents, refunded_amount_cents_int, source_id, is_captured, captured_amount, captured_amount_int, settlement_amount_cents_int, merchant_staff_tag, accept_fees_cents_int, vat_cents_int, vat_cents_float, paymob_date, value_date, updated_at, is_settled, bill_balanced, is_bill, is_reconciled, cogs, reconciliation_id, owner, parent_transaction`

`order{}`: `id, created_at, delivery_needed, merchant{id, created_at, phones[], company_emails[], company_name, state, country, city, postal_code, street}, collector, amount_cents, shipping_data{id, first_name, last_name, street, building, floor, apartment, city, state, country, email, phone_number, postal_code, extra_description, shipping_method, order_id, order}, currency, is_payment_locked, is_return, is_cancel, is_returned, is_canceled, merchant_order_id, wallet_notification, paid_amount_cents, notify_user_with_email, items[{name, description, amount_cents, quantity}], order_url, commission_fees, delivery_fees_cents, delivery_vat_cents, payment_method, merchant_staff_tag, api_source, data{notification_url, ...}, payment_status (e.g. "PAID"), terminal_version, ...`

`data{}` (card/MIGS-MPGS): `gateway_integration_pk, klass, created_at, amount, currency, migs_order{id, amount, status (CAPTURED/REFUNDED...), currency, totalAuthorizedAmount, totalCapturedAmount, totalRefundedAmount, authenticationStatus, ...}, migs_result, migs_transaction{id, type (PAYMENT/REFUND/...), amount, receipt, acquirer{...}, ...}, txn_response_code (e.g. "APPROVED"), acq_response_code ("00"), message ("Approved"), merchant_txn_ref, order_info, receipt_no, transaction_no, batch_no, authorize_id, card_type, card_num (masked), secure_hash, avs_result_code, avs_acq_response_code, captured_amount, authorised_amount, refunded_amount, acs_eci`

`merchant_order_id` inside `order` is the `special_reference` you send on intention creation (DOC-INQ by-order-id: "Merchant Order ID (Which you sent while creating an Intention as a `special_reference`)"). Refund/void/capture child transactions carry `parent_transaction` = original transaction id and `has_parent_transaction: true` (DOC-REFUND).

NOTE: wallet / Apple Pay / kiosk callbacks have different `source_data.type` and different `data{}` contents. The docs do not publish wallet or Apple Pay callback JSON samples. SKILL hmac-verification.md: "wallets and cards can return slightly different nested shapes ... log the first real callback per method" (see Open questions).

### 1.3 Response (GET redirect) sample from the docs (DOC-CB)
```
https://webhook.site/...?id=316004&pending=false&amount_cents=50000&success=true&is_auth=false&is_capture=false&is_standalone_payment=true&is_voided=false&is_refunded=false&is_3d_secure=true&integration_id=2936&profile_id=106&has_parent_transaction=false&order=378804&created_at=2024-06-25T15%3A16%3A25.910710%2B04%3A00&currency=EGP&merchant_commission=0&discount_details=%5B%5D&is_void=false&is_refund=false&error_occured=false&refunded_amount_cents=0&captured_amount=0&updated_at=2024-06-25T15%3A16%3A46.544538%2B04%3A00&is_settled=false&bill_balanced=false&is_bill=false&owner=211&data.message=Approved&source_data.type=card&source_data.pan=2346&source_data.sub_type=MasterCard&acq_response_code=00&txn_response_code=APPROVED&hmac=8aa3e005...
```
Observations: flat query params; nested keys use dots (`source_data.pan`, `data.message`); the order id appears as `order=` in the real sample, while the HMAC doc table says "order_id for Response (GET)". Mismatch inside the docs; verify with a live test (Open questions).

### 1.4 What response Paymob expects, retries, ordering, duplicates, IPs
- The docs do NOT specify the expected HTTP response code, timeout, retry schedule, retry count, ordering guarantees, duplicate-delivery semantics, or source IP ranges. I searched all of llms.txt (378 KB) for retry/allowlist/IP/idempotency: only the glossary line "Callback (Webhook / HMAC-Signed): Server-to-server notifications for payment state changes. Must verify HMAC, support retries, and ensure idempotency." (llms.txt glossary).
- SKILL hmac-verification.md (vendor-authored guidance, not spec) says: reject with 401 on HMAC mismatch; "Paymob's retries give you a chance to fix it" and "Respond 200 OK promptly ... webhook senders typically retry on non-2xx or timeout". It hedges with "typically", so treat retry as likely but unspecified.
- No IP allowlist is published. HMAC is the only documented authenticity control (DOC-CB caution: "In order to verify that these requests are received from Accept's endpoint, you have to implement the HMAC authentication").
- Practical design (my recommendation, not from docs): dedupe on `obj.id` + transaction state with a DB unique constraint (SKILL idempotency section recommends exactly this); treat out-of-order delivery as possible (e.g. a refund callback for the parent can in theory arrive near the payment callback), so apply state by `(obj.id)` and flags (`is_refunded`, `is_voided`, `refunded_amount_cents`) rather than by arrival order; return 2xx only after commit; run a reconciliation job via Transaction Inquiry.

---

## 2. HMAC calculation (exact)

### 2.1 Transaction callbacks (Processed POST and Response GET). Source: DOC-HMAC
Algorithm: HMAC-SHA512, key = HMAC secret, message = concatenation of values (no separator), hex lowercase digest, compare with `hmac` received.

Doc says "Sort the Data Lexicographically by Key", then gives this list (which IS lexicographic order on the key with the `obj.`/`order.` nesting stripped to `id`/`order`):

```
amount_cents
created_at
currency
error_occured
has_parent_transaction
obj.id            // POST (processed) | id for GET (response)
integration_id
is_3d_secure
is_auth
is_capture
is_refunded
is_standalone_payment
is_voided
order.id          // POST | "order_id" for GET per doc text (real GET sample uses `order=`)
owner
pending
source_data.pan
source_data.sub_type
source_data.type
success
```
For POST, all values are read from `body.obj`. Booleans stringify as lowercase `true`/`false`; numbers as plain; strings raw (do not reformat `created_at`). Note the spelling `error_occured` (sic) in the payload.

Docs worked example (concatenated string):
`1000002024-06-13T11:33:44.592345EGPfalsefalse1920364654097558truefalsefalsefalsetruefalse217503754302852false2346MasterCardcardtrue`
(amount_cents=100000, created_at, EGP, error_occured=false, has_parent_transaction=false, id=192036465, integration_id=4097558, is_3d_secure=true, is_auth=false, is_capture=false, is_refunded=false, is_standalone_payment=true, is_voided=false, order.id=217503754, owner=302852, pending=false, pan=2346, sub_type=MasterCard, type=card, success=true).
Docs sample digest: `fa8ac0b7f3852e60c50e7fdd4ea5ef0bda96030c19dea1d55df8c76d6c08ab1877774662cbb04981dc84839ad4da560bcc8cb53b8973548657f7e8f8d2e79930` (secret not published, so cannot be reproduced; useful only to confirm string building).

Where `hmac` lives for the POST callback: query string `?hmac=` (DOC-HMAC step 4: "Compare ... with the hmac value received in the callback's query parameters"; SKILL: "?hmac=<value> on the URL"; the Python reference reads `request.GET.get("hmac")`). Not in the JSON body.

Cross-check (GH): frappe/payments `hmac_validator.py`, Tickizy Go `paymob_validate_hmac.go`, gahezlak TS all use the identical 20-key order, SHA512, `obj.*` source. Null handling: all three coerce null/None to empty string `""` and booleans to `true`/`false`. The official docs do not state null handling; SKILL explicitly warns about it (Python `str(None)` = "None" would break; use "").
Python reference (SKILL code-python.md, matches GH):
```python
parts = [obj["amount_cents"], obj["created_at"], obj["currency"], obj["error_occured"],
 obj["has_parent_transaction"], obj["id"], obj["integration_id"], obj["is_3d_secure"],
 obj["is_auth"], obj["is_capture"], obj["is_refunded"], obj["is_standalone_payment"],
 obj["is_voided"], obj["order"]["id"], obj["owner"], obj["pending"],
 obj["source_data"]["pan"], obj["source_data"]["sub_type"], obj["source_data"]["type"], obj["success"]]
# bool -> "true"/"false", None -> "", else str(); join with ""
hmac.new(secret.encode(), s.encode(), hashlib.sha512).hexdigest()  # compare_digest vs ?hmac=
```

Card vs wallet vs Apple Pay: the docs give ONE field list for all processed/response callbacks, and `source_data.pan/sub_type/type` are card-shaped. For wallets these may be different values (e.g. `source_data.type` = `wallet`, pan = phone) or null. Not documented; must test with the sandbox wallet (test wallet 01010101010, MPIN 123456, OTP 123456; need-help/setup-guides/test-credentials.md). Apple Pay cannot be sandbox-tested (live ids only).

### 2.2 Card token callback. Source: DOC-HMAC-TOK (updated 2026-08-24)
POST JSON, `type: "TOKEN"`, fields from `obj`. Keys in order:
`card_subtype, created_at, email, id, masked_pan, merchant_id, order_id, token`
Sample concat: `MasterCard2026-08-24T13:28:31.015314kiyedi3052@claspira.com15978654xxxx-xxxx-xxxx-234610539285938815813f22ce8a4e...`. Same SHA512 + HMAC secret. `hmac` in query string (frappe code reads the same `hmac` for all types).
Token object sample (create-card-token.md): `{"type":"TOKEN","obj":{"id":15978654,"token":"3f22ce8a...","masked_pan":"xxxx-xxxx-xxxx-2346","merchant_id":1053928,"card_subtype":"MasterCard","created_at":"2026-08-24T13:28:31.015314","email":"...","order_id":"593881581","user_added":false,"next_payment_intention":"pi_test_...","cardholder_name":"TEST ACCOUNT","expiry_month":"01","expiry_year":"38"}}`. (GH frappe also validates a "DELIVERY_STATUS" callback type: order_id, order_delivery_status, merchant_id, merchant_name, updated_at; irrelevant to us.)

### 2.3 Subscription callback. Source: DOC-HMAC-SUB
POST JSON. `hmac` is in the BODY (unlike transaction/token). String = `"{trigger_type}for{subscription_data.id}"`, e.g. `suspendedfor1264`; SHA512, HMAC secret. Matches gahezlak TS `verifyPaymobSubscriptionHmac`. Body shape:
```json
{"paymob_request_id":"df9e4ecf-...","subscription_data":{"id":1264,"client_info":{"email","full_name","phone_number"},"frequency":365,"created_at","updated_at","name","reminder_days":null,"retrial_days":null,"plan_id":1186,"state":"suspended","amount_cents":330,"starts_at":"2024-12-20","next_billing":"2024-12-20","reminder_date":null,"ends_at":null,"resumed_at":null,"suspended_at":"2024-12-03","webhook_url":"...","integration":4565330,"initial_transaction":241322967},"trigger_type":"suspended","hmac":"dd5b..."}
```
`trigger_type` values: `"Subscription Created"`, `suspended`, `canceled`, `resumed`, `updated`, `add_secondry_card` (sic), `change_primary_card`, `delete_card`, `register_webhook`, `"Successful Transaction"` (next billing cycle OK), `"Failed Transaction"` (deduction failed), `"Failed Overdue Transaction"` (retrial failed). Note the HMAC only covers trigger_type + id, so amounts/state in the body are unauthenticated; re-fetch subscription via API before acting.

---

## 3. Transaction states (state machine)

Flags on the transaction object (DOC-CB, DOC-INQ):
- `success` (bool) and `pending` (bool). Success: `success=true, pending=false`. Declined: `success=false, pending=false`, `data.txn_response_code` / `acq_response_code` / `data.message` carry the reason (sample APPROVED / "00" / "Approved"). Pending: `pending=true`; SKILL: treat pending as not yet paid.
- `error_occured` (bool): processing error.
- `is_auth` / `is_capture`: auth hold vs captured. `is_captured` + `captured_amount` (cumulative) on the parent.
- `is_voided` (bool) set on the parent after a void; `is_refunded` + `refunded_amount_cents` (cumulative) on the parent after refund(s).
- `is_void` / `is_refund` (note spelling, no "d"): true on the CHILD transaction that is itself the void/refund. `has_parent_transaction` + `parent_transaction` link child to parent.
- `is_standalone_payment`: true for a normal payment, `is_3d_secure`, `is_settled`, `is_live`.
- Order level: `order.payment_status` (e.g. "PAID"), `order.paid_amount_cents`. Dashboard filter statuses: Success / Pending / Declined.

Interpreting pending: Paymob docs do not publish a pending state table. Guidance from SKILL (vendor): kiosk settles asynchronously (callback hours/days later or never); abandoned 3DS/OTP produces no callback; wallets and SDKs expose `pending` states ("Treat pending as not yet paid until your backend confirms the final status", llms.txt SDK pages). Since Paymob sends a callback only on success or decline (DOC-OV), do not expect a callback for a still-pending wallet request; poll Transaction Inquiry by `special_reference` (merchant_order_id) on a backoff schedule.

Recommended mapping for Lemely (my synthesis): PAID iff HMAC ok AND `success==true` AND `pending==false` AND `is_voided==false` AND `is_refunded==false` AND `error_occured==false` AND `is_auth==false` (unless using auth/capture) AND `obj.amount_cents`/`currency` match the server-side order. Child callbacks (`has_parent_transaction==true`, refund/void/capture) must be routed to the parent, not treated as a new payment.

---

## 4. Post-payment operations

Auth for these three: `Authorization: Token <secret_key>` (Secret key `sk_test_...`/`sk_live_...`). Inquiry endpoints use the legacy auth-token flow (below).

| Op | Endpoint | Body | Notes |
|---|---|---|---|
| Refund | `POST /api/acceptance/void_refund/refund` | `transaction_id` (int, required), `amount_cents` (int, required) | full or partial; cumulative cannot exceed original; same payment method; supported for all methods except Kiosk (managing-payments/refund.md; wallets and Apple Pay: "Refund (Full/Partial)") |
| Void | `POST /api/acceptance/void_refund/void` | `transaction_id` | card only; cancels a successful payment before settlement, "mostly ... same business day" (managing-payments/void.md). Apple Pay void: SKILL table says Yes, Paymob's Apple Pay page lists only refund |
| Capture | `POST /api/acceptance/capture` | `transaction_id`, `amount_cents` | card Auth transactions only; partial captures allowed; must capture before auth expires; excess otherwise auto-voided (managing-payments/capture.md). Auth expiry duration not stated |

Responses: HTTP 200 with the full child transaction object (`id` new, `success`, `is_refund`/`is_void`, `parent_transaction`, `amount_cents`, `data.migs_transaction.type` = REFUND). Parent transaction then gets callback with `is_refunded:true` / `is_voided:true`; child's `parent_transaction` holds parent id (DOC-REFUND/VOID).
Errors documented: refund/void too large: `400 {"message":"Requested Refund Amount is greater than the maximum refund amount permissible. Maximum Refund Amount is EGP 100.0"}`; capture over auth: `400 {"detail":"Capture amount cannot exceed auth amount"}`; capture of non-auth/declined: `404 {"detail":"Invalid transaction id"}`.
Time limits: no explicit refund window documented. Void is same-day-before-settlement; after settlement use refund. No documented idempotency key header; SKILL: "Never auto-retry after a timeout ... inquire whether the first request succeeded". Because partial refunds are cumulative and there is no idempotency key, keep our own refund ledger row (unique per intended refund) before calling, and verify via inquiry (`refunded_amount_cents`) after ambiguous failures.

Inquiry (DOC-INQ). Docs say: callbacks are primary; inquiry only for manual checks or fallback when a callback is missed.
- Auth: `POST /api/auth/tokens` body `{"api_key": "<API KEY>"}` returns a token valid ONE HOUR ("Each auth token is valid for an hour", repeated across subscription/QuickLink pages).
- By transaction id: `GET /api/acceptance/transactions/{transaction_id}` header `Authorization: Bearer <auth_token>`.
- By order id or merchant order id: `POST /api/ecommerce/orders/transaction_inquiry` body `{"auth_token": "...", "order_id": 212245716, "merchant_order_id": "<special_reference>"}` (order_id and merchant_order_id both optional; returns the LAST transaction of that order).
- Card token by order: `POST /api/acceptance/order_card_tokens` body `{auth_token, order_id}` returns array of `{type:"TOKEN", obj:{...}}`.
- Dashboard reports: one-month max range, CSV; MCP server (https://mcp.paymob.com/mcp) offers transaction/balance/export tools (SKILL mcp-server.md; not needed).

---

## 5. Saved cards, tokenization, MOTO / card-on-file

Sources: payments-and-features/core-features/pay-with-saved-cards.md, pay-with-saved-cards/{create-card-token,cit,mit}.md.

Card integration types referenced: Normal 3DS, Auth, Card On File, MOTO, Verification (each is a separate integration id).

1. Create token (first payment): Create Intention using a Verification, Normal 3DS or Auth integration id; render Unified Checkout or Pixel; customer opts to save card; Paymob POSTs the card-token callback (section 2.2) to `notification_url` / integration processed-callback URL. Correlate via `intention_order_id` (same as `order_id` in token callback) and intention `id`. Token callback is separate from the transaction callback. No documented token expiry (glossary: "Scope and expiry depend on Paymob and the acquirer").
2. CIT (customer present): new intention with `card_tokens: ["<token>"]` (array, "accepts up to 3 card tokens"), integration type Normal 3DS, Auth, or Card On File; customer picks the saved card in Unified Checkout/Pixel without retyping details; 3DS may apply. Callbacks same as normal payments.
3. MIT (no customer interaction): create intention with a MOTO integration id; take `payment_keys[0].key` (payment token) from the response; then `POST /api/acceptance/payments/pay` body `{"source":{"identifier":"<card token>","subtype":"TOKEN"},"payment_token":"<payment_keys[0].key>"}` (mit.md). MOTO enablement is not self-serve per SKILL ("Paymob turns it on; separate Integration ID"; request shape "not published", though mit.md now shows it). MOTO = no 3DS, merchant bears chargeback liability (SKILL).
4. Card Token Inquiry lists tokens for an order (section 4).
5. Deleting a saved token via API: not found in the docs (only subscription cards have `delete-card`). Open question.

Relevance: for pay-per-use credits, saved cards are optional convenience; for tutor-session payments MIT is probably unnecessary.

---

## 6. Subscriptions / recurring module

Sources: payments-and-features/core-features/subscriptions.md and subscription/*.md (all updated 2026-06-01 to 2026-06-28).

Concept: Subscription Plan (blueprint) + Subscription (customer enrollment). Paymob charges automatically on schedule, with retries for failed payments. Card-only in practice: plans require "MIGS Moto Integration ID" (`integration` field; "Please make sure to use the Moto integration ID while creating a subscription plan"), and a subscription is created by completing one 3DS transaction that saves the card. No wallet/recurring documented anywhere (wallet needs OTP per payment; no token mechanism documented for wallets). No statement of regional availability in these pages (I found none naming Egypt or excluding it); the dashboard/API lives on accept.paymob.com, but Egypt/test-account availability and MOTO enablement must be confirmed with Paymob (Open questions).

Auth: Bearer auth token from `POST /api/auth/tokens` (1h) for plan and subscription management; creating a subscription uses the Intention API with the SECRET key.

Plan APIs (base `/api/acceptance/`):
- `POST subscription-plans` body: `frequency` (REQ; one of 7,15,30,60,90,180,360 days), `name` (REQ, max 200 chars), `integration` (REQ, MOTO integration id), `webhook_url` (opt, receives subscription-level events), `reminder_days` (email reminder before charge), `retrial_days` (retry days after failed deduction), `plan_type` ("rent" only/default), `number_of_deductions` (null = unlimited), `amount_cents`, `use_transaction_amount` (bool; use first transaction's amount instead of plan amount), `is_active` (default true), `fee`.
- `GET subscription-plans` (paginated `next/previous/results`), `PUT subscription-plans/{id}` (change `number_of_deductions`, `amount_cents`, `integration`), `POST subscription-plans/{id}/suspend`, `POST subscription-plans/{id}/resume`.
- Errors: invalid frequency `400 {"frequency":["\"5\" is not a valid choice."]}`; bad token `401 {"detail":"incorrect credentials"}`.

Subscription APIs:
- Create: Create Intention with extra params `subscription_plan_id` (REQ) and `subscription_start_date` (opt, only effective if `use_transaction_amount` is false). Wrong key/plan mismatch: `404 {"message":"invalid subscription plan id"}`.
- `GET subscriptions/{id}` (also list with filters: `transaction`, `plan_id`, subscription state), `PUT subscriptions/{id}` (`amount_cents`, `ends_at`, `next_billing`), `POST subscriptions/{id}/suspend|resume|cancel` (cancel is permanent; resume of non-suspended returns `400 {"message":"The subscription isn't suspended"}`).
- Cards: `GET subscriptions/{id}/card-tokens` (shows `is_primary`, `failed_attempts`), add secondary card via intention with `subscriptionv2_id` (Verification integration recommended), `POST .../change-primary-card` body `{card: id}`, `POST .../delete-card` body `{card: id}`.
- Webhook: `POST subscriptions/{subID}/register_webhook` body `{url}`; webhook inherits from plan unless overridden.
- Transactions: `GET subscriptions/{id}/transactions`, `GET subscriptions/{id}/last-transaction`.
- Subscription fields: `id, client_info{email,full_name,phone_number}, frequency, name, reminder_days, retrial_days, plan_id, state (active/suspended/canceled...), amount_cents, starts_at, next_billing, reminder_date, ends_at, resumed_at, suspended_at, reactivated_at, webhook_url, integration, initial_transaction`.
- Each recurring charge also yields a normal transaction (and, presumably, a transaction processed callback to the integration's callback URL); the docs do not say explicitly which callbacks fire per cycle beyond the subscription webhook `Successful Transaction` / `Failed Transaction` / `Failed Overdue Transaction` triggers.

Alternative to the module: roll your own with card token + MIT (section 5), giving full control of pricing logic, proration, plan changes, dunning; needs MOTO integration id either way. Given pricing is undecided, defer; but note both require MOTO enablement and are card-only.

---

## 7. Payment links / QuickLink (invoices)

Dashboard (integration-paths/no-code/payment-links.md, updated 2026-09-23): Create > Quick Link; configure currency, amount, reference id, image; one or multiple customers; contact method; pick payment methods and integration ids; share via QR/WhatsApp/SMS/email; unpaid links can be cancelled. Also PayMe (permanent reusable link, live mode only, customer enters amount; not usable in test).

API (quicklink-apis/overview, create-quicklink, cancel-quicklink; text retrieved only from llms.txt blurbs, because the site began returning 403): create + cancel link programmatically with Bearer auth token (1h). Known facts: `reference_id` must be unique (`400 {"message":"Reference ID already exists."}`), `expires_at` must be in the future (`400 {"message":"expires_at - expires_at can't be in the past."}`), `is_live` parameter must match integration id mode (`404 {"detail":"Integration ID/Name does not exist in our system..."}`), 401 for bad token. Exact endpoint path and body schema were NOT captured. The MCP server mentions `create_payment_link`, `create_scaling_payment_link` (multi-customer, optional usage limits) and `create_invoice`, `get_merchant_payment_links` (SKILL mcp-server.md), implying link/invoice concepts exist.

Fit for tutor sessions: our own server-side order + Create Intention (Unified Checkout) is the better fit because we want `special_reference` = our payment id, server-computed amount, and precise lifecycle control. QuickLinks are useful if we want to send a pay-by-link to a parent over WhatsApp, with `reference_id` = our id and `expires_at` as the booking hold expiry. The link flow also sends the normal processed callback (the integration-level callback URL must then be configured on the integration id; plugin/links "rely on" per-integration URL per SKILL).

---

## 8. Idempotency, rate limits, errors, timeouts, versioning

- Idempotency: no `Idempotency-Key` header or idempotent-create semantics documented for Create Intention, refund, void or capture. `special_reference` is the merchant order reference (QuickLink `reference_id` is enforced unique; intention `special_reference` uniqueness is not documented in my pages). Callback dedupe key = `obj.id` (SKILL). Client secret is unique per order and expires in an hour (Pixel docs in llms.txt); auth token 1 hour.
- Rate limits: security page only says "Rate limiting to prevent abuse" (need-help/security-and-privacy.md). No numeric limits, no 429 documentation. SKILL: don't poll in tight loops.
- Error format: two shapes: `{"message": "..."}` and `{"detail": "..."}`; field validation as `{"field": ["msg"]}`. Common: 401 `{"detail":"incorrect credentials"}` (expired auth token), 404 on mode mismatch (live secret key with test integration id), 400 for amount/validation. A full error-code catalogue doesn't exist in the pages I read.
- Timeouts: not documented for API calls; callback timeout not documented.
- API versioning: the site mixes the legacy "acceptance" APIs (`/api/acceptance/...`, `/api/auth/tokens`, `/api/ecommerce/...`) with the newer Intention API (`/v1/intention/`, Secret-key `Token` auth; covered by another agent). No version headers, no deprecation notices found. SKILL calls inquiry the "legacy/management API", which works alongside Intention payments. "Last Updated" dates on pages range May to Oct 2026 (card-token and CIT pages updated Aug/Oct 2026), so the docs are actively changing: re-verify field lists before go-live.
- Test data: sandbox test data expires after 30 days (SKILL SKILL.md, vendor claim); test cards: Mastercard 5123456789012346 and 5123450000000008, Visa 4111111111111111, exp 01/39, CVV 123, name "Test Account"; wallet 01010101010, MPIN 123456, OTP 123456 (need-help/setup-guides/test-credentials.md). Decline simulation is not officially documented (SKILL).

---

## 9. Security best practices (consolidated)

From Paymob docs/SKILL:
1. Verify HMAC on every callback before any state change; fail closed (DOC-CB caution; SKILL).
2. Never trust the browser redirect/response callback or SDK result; confirm via processed callback or inquiry (DOC-CB; llms.txt SDK pages: "Treat pending as not yet paid").
3. Compute amounts server-side from your own order record; compare `obj.amount_cents` and `currency` (and `order.merchant_order_id` / `special_reference`) to your record before crediting (SKILL post-integration checklist item 7).
4. Dedupe by `obj.id` with a DB unique constraint; atomic compare-and-set of order state; return 2xx after commit (SKILL).
5. Constant-time HMAC comparison; treat missing/wrong-length hmac as mismatch (SKILL).
6. Secrets: `sk_*`, API key, HMAC secret server-side only; only `pk_*` in frontend; rotate HMAC secret with a brief dual-secret window (SKILL).
7. Reconciliation job against Transaction Inquiry; alert on HMAC rejections; don't log PAN/CVV.
8. Callback URL: production HTTPS; also set per-integration callback URL in dashboard.
9. Ask Paymob before refunding a disputed transaction (SKILL).

Items 3, 4 (beyond obj.id) and the correlation-by-`special_reference` are vendor guidance rather than spec.

---

## 10. Implications for Lemely's three payment purposes

1. Credit bundles: Create Intention (server computes price), card + wallet integration ids, process on verified processed callback only (success && !pending), credit once keyed by `obj.id`; refund via refund API only for card/wallet (not kiosk).
2. Tutor marketplace: Lemely collects. Consider Auth + Capture (card only, `is_auth`) to hold funds until the session happens, with void/refund on cancellation; wallets cannot do auth/capture/void (refund only). Simpler: capture immediately, refund on cancel, keep an internal escrow ledger (payouts are handled by another research thread). Partial refund is supported, so partial cancellations are possible. Refund API is per-transaction and cumulative: track `refunded_amount_cents`.
3. Subscriptions: Paymob's module is card-only, MOTO-integration dependent, plan frequencies fixed to 7/15/30/60/90/180/360 days; wallets not usable for recurring. Defer.

---

## Open questions / unclear in docs

1. Callback delivery contract: expected response code, timeout, retry schedule/count, duplicate and ordering guarantees, and source IPs are NOT documented. Ask Paymob support or observe via hooks.paymob.com and the test account.
2. Wallet and Apple Pay callback payloads and HMAC: no samples; `source_data.pan/sub_type/type` content for wallets unknown (null vs value). Capture a real sandbox wallet callback and confirm HMAC with null as "" (all three third-party implementations use ""). Apple Pay has no test integration (live only), plus requires domain verification and certificates.
3. GET response callback: doc text says `order_id` but real sample uses `order=`; HMAC for GET may need `order` mapped to the `order.id` position. Verify empirically.
4. Docs example JSON for the processed callback and the field-description table were not retrievable in .md (dynamic component). The shape above is inferred from the API responses and GH.
5. Pending semantics: no state table; whether Paymob sends any callback for a pending wallet request that later expires, and how long a wallet request stays pending, is unknown.
6. Refund time window, void cut-off hour (settlement time), auth expiry duration: not stated.
7. Idempotency of Create Intention when `special_reference` repeats; whether the refund API dedupes: not documented.
8. Subscriptions: Egypt availability and test-account support for the MOTO integration (needs account-manager enablement); per-cycle processed callbacks; max retries semantics of `retrial_days`.
9. QuickLink API: path, request schema (amount, currency, payment methods, `reference_id`, `expires_at`, `is_live`, customer fields), response (link URL), and whether `special_reference`/callbacks map back. Page returned 403 after my fetch burst; retry from another IP or via Postman collection linked on the page.
10. Deleting a saved card token (non-subscription) API: not found.
11. Rate limit numbers and a full error-code table: not published.
12. Vendor-authored SKILL content (retries "typically", 30-day sandbox data expiry) is not from the official docs pages; treat as hints.

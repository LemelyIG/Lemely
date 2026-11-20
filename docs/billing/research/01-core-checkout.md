# Paymob docs research 01: core checkout, credentials, payment methods, test mode, SDKs

Researched 2026-11-02 (web only; no repo code touched). Docs site is a Theneo site; every page has a raw markdown twin at `<url>.md`.

Source key (used in citations below):
- D = https://developers.paymob.com/paymob-docs/ (official docs). Raw `.md` variants fetched; paths given relative to D.
- SKILL = Paymob's own official AI skill repo https://github.com/PaymobAccept/Paymob-AI-Integration-Skill (v3.3.0, Aug 2026), referenced from D `ai-agent-skill`. Secondary source (Paymob-authored, but not the API reference).
- PROBE = my own live HTTP probe on 2026-11-02.

Local copies: raw pages in `.../paymob-research/raw/`, flattened API schemas in `.../paymob-research/compact/`, skill files in `.../paymob-research/skill/`.

---

## 0. TL;DR for Lemely

1. Use the **Intention API** (`POST https://accept.paymob.com/v1/intention/`, `Authorization: Token <secret key>`) then redirect to **Unified Checkout** (`https://eg.checkout.paymob.com/?publicKey=...&clientSecret=...`). That is the current, recommended path. The legacy Accept flow (auth token, order, payment key, iframe) is no longer documented; the FAQ pushes new merchants to Unified Checkout and says new iframe setups must be requested from Paymob.
2. **Amounts are integers in cents/piasters** (`10000` = EGP 100.00). `currency: "EGP"` must match the integration ID's currency.
3. **Pixel (embedded) supports only card, Apple Pay, Google Pay. Mobile wallets, kiosk, BNPL are Unified Checkout only.** Google Pay is NOT available in Egypt per the live method docs (KSA/UAE/OMN). So in Egypt, Pixel = card (+ Apple Pay once live).
4. **Test mode covers only cards, mobile wallet, kiosk (kiosk has test IDs but SKILL says no test path).** Apple Pay, Google Pay, bank installments, BNPL have **Live integration IDs only**, so Apple Pay cannot be sandbox-tested at all. Sandbox data expires after 30 days (SKILL).
5. Three different auth styles exist across the API (see section 2.3). Do not assume one header everywhere.
6. The **webhook (`notification_url` POST, HMAC SHA-512) is the source of truth**; the `redirection_url` GET is UX only. `redirection_url` works only for card and wallet.
7. No official Python SDK for the Intention API. Official web SDK is `paymob-pixel` (npm, v1.2.10). Mobile SDKs (iOS/Android/Flutter/React Native) are not relevant to a FastAPI+React web app unless a native app is planned.
8. Account activation (test to live) is a business process (paperwork, contract, risk approval). The legal/payout agent should confirm whether commercial register / tax card is demanded; the checklist says "Paperwork Validation: business and legal documents are reviewed" (D `getting-started/integration-checklist`).

---

## 1. Getting started, account, test vs live

### 1.1 Account and environments
- Paymob offers Sandbox (test) and Production (live). "Test and live use the same regional base URL for each region. The mode is controlled by the keys and integration IDs you use." (D `getting-started/overview`)
- Regional base URLs (D `getting-started/overview`, SKILL `intention-api.md`):
  - Egypt: `https://accept.paymob.com/`
  - Oman: `https://oman.paymob.com/`; KSA: `https://ksa.paymob.com/`; UAE: `https://uae.paymob.com/`
- "Currently, Paymob does not support the creation of a global account. You can only create an account for a specific region." (D `need-help/faqs`)
- Go-live path (D `getting-started/integration-checklist`): Account Creation (dashboard + test env) -> Paperwork Validation -> Contract Finalization -> Risk Approvals -> Integration Cycle (test env) -> Test & Validation -> Technical Approval -> Live Credentials -> Going Live. "Don't skip steps."
- Prereqs (D `getting-started/overview`): merchant account, dashboard access, "Completed business verification"; for API/SDK: secret key + public key, integration ID(s), a webhook endpoint, success/failure redirect URLs.
- Dashboard roles (D `getting-started/new-dashboard`): Owner, Admin, Developer, Finance, Operations, Sales (+ custom roles). **Sub-users cannot see the HMAC secret**; only the main user can (D `need-help/faqs`).
- Dashboard also offers: transaction list with Refund/Void/Capture actions, Orders, Quick Links, Disputes & Chargebacks (Accept/Challenge/Arbitration), Checkout Customization (logo, colors, fonts, tabs vs list, enable/disable methods, save-card toggle, split payments, retries) (D `getting-started/dashboard`, `getting-started/new-dashboard`).
- Wizard tool https://wizard.paymob.com/ (Integration Wizard: Code Lab that runs an intention against sandbox, HMAC troubleshooter, Postman export, "Create Integration" for test integrations: Card (VPC), Mobile Wallet, valU, Cash Collection; wizard-created integrations are always test mode) (SKILL `post-integration.md`). PROBE: wizard.paymob.com and hooks.paymob.com both return 200.
- hooks.paymob.com = Paymob's webhook inspector (displays POST/GET/PUT, no retention, does not forward) (SKILL `intention-api.md`).

### 1.2 Credentials (D `need-help/setup-guides/getting-integration-credentials`)
Dashboard > Settings > Developers > API Keys. Toggle test/live at top right.
| Credential | Mode-specific? | Where used | Notes |
|---|---|---|---|
| Secret key | Yes (`sk_test_...`/`egy_sk_test_...` vs live `sk_live...`) | Server only; `Authorization: Token <sk>` for Intention + refund/void/capture | Never in frontend (D `checkout-experiences/pixel-embedded`) |
| Public key | Yes (`pk_test_...`/`egy_pk_test_...`, live `pk_live...`) | Safe client side: Unified Checkout URL, Pixel, mobile SDKs | "Cannot authorize payments on its own" (glossary) |
| API key | **No, same for test and live** | Body of `POST api/auth/tokens` to get a legacy auth token | Used for Subscriptions, QuickLink, transaction inquiry |
| HMAC secret | Shown on API Keys page | Verify callbacks (SHA-512) | Main user only |
| Integration ID(s) | Yes, per payment method and per mode | `payment_methods` array in intention | Dashboard > Settings > Payment Integrations. Must be passed as **integers**, not strings (D `need-help/faqs`) |
Also per-integration-ID: Webhook URL and Redirect URL can be set on the integration's detail page (D same page). The intention-level `notification_url`/`redirection_url` override these (D `need-help/faqs`).
- Key prefix evidence from doc samples: `egy_pk_test_...`, `egy_sk_test_...`, `egy_csk_test_...` (client secret) in D `checkout-experiences/pixel-embedded`; `sk_test_626...` in intention page; client_secret example `egy_csk_test_94042f79...`.

### 1.3 Auth model (three styles; verified from endpoint pages)
| Style | Header/body | Used by |
|---|---|---|
| Secret key | `Authorization: Token sk_test_...` (literal word Token, NOT Bearer) | `POST v1/intention/`, `PUT v1/intention/{client_secret}/`, `POST api/acceptance/void_refund/refund`, `.../void`, `POST api/acceptance/capture` |
| Auth token from API key | First `POST api/auth/tokens` body `{"api_key": "..."}` -> `token`. Then `Authorization: Bearer <token>` | Transaction inquiry by transaction id (`GET api/acceptance/transactions/{id}`), QuickLink (`POST api/ecommerce/payment-links`), subscriptions |
| Auth token in body | `{"auth_token": "...", "order_id": "...", "merchant_order_id": "..."}` | `POST api/ecommerce/orders/transaction_inquiry` |
Source: compact pages `authentication-request-generate-auth-token-1`, `manage-payment-apis/*`, `transaction-inquiry-apis/*`, `quicklink-apis/create-quicklink`. SKILL troubleshooting: "401 on intention create: wrong/expired Secret Key, or header missing the literal word Token: `Token <key>`, not `Bearer`."
- PROBE: `POST https://accept.paymob.com/v1/intention/` with bad token -> `401 {"detail":"Authentication credentials were not provided."}` (endpoint exists on the Egypt base URL).
- Auth token endpoint: `POST api/auth/tokens`, body `api_key` (required). Response is a huge profile object plus `token`. Auth token lifetime is not stated (open question).

---

## 2. Intention API (current recommended flow)

Source: D `intention-apis/overview`, `intention-apis/create-intention`, `intention-apis/update-intention` (create page last updated 2026-10-15).

Used for: normal redirect integration, Pixel, mobile SDKs, subscriptions, Auth/Cap, pay-with-saved-cards (D `intention-apis/overview`). Postman collection: https://github.com/PaymobAccept/API-Postman-Collections.

### 2.1 Create Intention
`POST https://accept.paymob.com/v1/intention/`
Headers: `Authorization: Token sk_test_...`, `Content-Type: application/json`

Request body (field, type, required?, official description):
| Field | Type | Req | Notes |
|---|---|---|---|
| `amount` | number | yes | "total transaction amount, expressed in cents" (example 2000) |
| `currency` | string | yes | Must match the currency of the selected Integration ID (example "EGP") |
| `payment_methods` | array | yes | Integration ID(s) as integers (e.g. 1256) "or as names enclosed in quotes (e.g. "card")". Status (live/test) must match secret key |
| `items` | array of objects | no (but see below) | each: `name` (req, max 50 chars), `amount` (req, cents), `description` (opt, max 255), `quantity` (opt). "When multiple items are provided, the sum of all item amounts must equal the total transaction amount." |
| `billing_data` | object | effectively yes | `first_name` (req, max 50), `last_name` (req, max 50), `email` (req), `phone_number` (see note), `apartment`, `street`, `building`, `floor`, `city`, `state`, `country`, `postal_code` (in response only) |
| `extras` | object | no | Custom key/values; "returned in callbacks under the payment key claims object". Response shows them as `extras.creation_extras` |
| `special_reference` | string | no | "unique reference ... returned in the transaction callback under `merchant_order_id`" (use as our internal order/payment id) |
| `expiration` | number | no | seconds (example 3600). Default not stated |
| `notification_url` | string | no | POST with full transaction details after success/fail. Create page: "Supported with all payment methods". (Update page says "Supported only with card Integration IDs" - docs inconsistent) Also receives card token for saved-card feature |
| `redirection_url` | string | no | Customer redirected here with query params. "Supported for Card and Wallet payment methods only." |
| `pre_selected_plan` | number | no | Only in SKILL (affordability widget / bank instalments). Not Lemely relevant |

billing_data requirement inconsistency: the schema marks `first_name`, `last_name`, `email` required and does not mark `phone_number`; but the official "Common errors" example is HTTP 400 `{"billing_data":{"phone_number":["This field is required."]}}`, and Update Intention marks `phone_number` required ("Both international and domestic formats are supported, including alpha-2 and standard numeric country codes."). Treat **first_name, last_name, email, phone_number as required**. Doc sample fills address fields with the literal "dumy" and the sample response shows `"+201010101010"` phone. SKILL example uses `country: "EGY"` (3-letter ISO) and a `+20...` phone.

Example request (D intention page example values, tidied; SKILL example uses same shape):
```json
{
  "amount": 10000,
  "currency": "EGP",
  "payment_methods": [4569876],
  "items": [{"name": "Item name", "amount": 10000, "description": "Item description", "quantity": 1}],
  "billing_data": {
    "first_name": "ala", "last_name": "zain", "email": "ali@gmail.com",
    "phone_number": "+201234567890",
    "apartment": "dumy", "floor": "dumy", "street": "dumy", "building": "dumy",
    "city": "dumy", "state": "dumy", "country": "EGY"
  },
  "extras": {"ee": 22},
  "special_reference": "phe4sjw11q-1xxxxxxxxx",
  "expiration": 3600,
  "notification_url": "https://webhook.site/dabe4968-...",
  "redirection_url": "https://www.google.com/"
}
```

Response `201` (D schema):
```json
{
  "payment_keys": [{"integration": 158, "key": "<long base64 JWT-like payment token>", "gateway_type": "MIGS", "iframe_id": null, "order_id": 265715202}],
  "intention_order_id": 265715202,
  "id": "pi_test_bd49bb7fb4da48cfac4ec71ab4d8c433",
  "intention_detail": {"amount": 10, "items": [...], "currency": "EGP",
     "billing_data": {"apartment":"dumy","floor":"dumy","first_name":"Andrea","last_name":"Nicolas","street":"dumy","building":"dumy","phone_number":"+201010101010","shipping_method":null,"city":"dumy","country":"dumy","state":"dumy","email":"test@test.com","postal_code":null}},
  "client_secret": "egy_csk_test_94042f793419c5a0f14a4cadfda9d626",
  "payment_methods": [{"integration_id": 4345907, "alias": null, "name": "CardF", "method_type": "online", "currency": "EGP", "live": false, "use_cvc_with_moto": false}],
  "special_reference": "phe4sjw111q-11221-221",
  "extras": {"creation_extras": {"ee": 22}, "confirmation_extras": null},
  "confirmed": false,
  "status": "intended",
  "created": "2024-11-18T13:42:08.456634",
  "card_detail": null,
  "card_tokens": [],
  "object": "paymentintention"
}
```
Key values per docs: `intention_order_id` = Paymob **Order ID** (appears in transaction callback as `order.id`; correlate with it), `id` = **Intention ID** (can do the same), `client_secret` = token for Unified Checkout / Pixel. (Doc sample response quirk: `intention_detail.amount` shows 10 while the request showed 2000; sample only, ignore.)
Note `payment_keys[].key` + `iframe_id` + `order_id` indicate the intention still creates legacy payment keys under the hood. Inference only, not documented; do not rely on it.

Errors documented: 404 `{"detail":"Integration ID/Name does not exist in our system..."}` (cause: test/live mismatch with secret key, ID not on this account or not an online integration, ID passed as string, or ID not "well-configured"); 400 `{"items":{"name":["This field is required."]}}` / `{"items":{"amount":[...]}}`; 400 billing_data.phone_number. (D create page, D `need-help/faqs`.)

Client secret lifetime: Pixel doc says "Client Secret is unique for each Order, and it expires in an hour." (D `checkout-experiences/pixel-embedded`). SKILL says single-use, new intention per payment attempt. Update Intention exists so an unpaid intention can be amended.

### 2.2 Update Intention
`PUT /v1/intention/{client_secret}/` with `Authorization: Token sk_...`. Updatable: `amount` (req), `payment_methods`, `items`, `billing_data`, `special_reference`, `expiration`, `notification_url`, `redirection_url`. Response mirrors create (sans payment_keys). Error: 400 `accept_order_id` required (doc quirk: says "pass the order ID related to the client secret you passed as a path parameter"). In Pixel, use `updateIntentionData` after changing. (D `intention-apis/update-intention`; page last updated 2026-06-22.)

### 2.3 Checkout experiences (D `checkout-experiences/overview`)
Both start with Create Intention then use the `client_secret`.

**Unified Checkout (hosted redirect)** (D `checkout-experiences/unified-checkout-redirection`, updated 2026-07-22):
- Egypt: `https://eg.checkout.paymob.com/?publicKey={your_public_key}&clientSecret={your_client_secret}` (UAE `uae.checkout.paymob.com`, Oman `om.checkout.paymob.com`, KSA `ksa.checkout.paymob.com`).
- SKILL documents the older form `https://accept.paymob.com/unifiedcheckout/?publicKey=...&clientSecret=...`. PROBE: `GET https://accept.paymob.com/unifiedcheckout/` returns `302` to `https://eg.checkout.paymob.com/?`, so the old URL redirects; use the new one.
- Supports all methods (card, wallets, kiosk, BNPL, Apple Pay on hosted page unclear, see open questions). Branding via dashboard Checkout Customization (no code).
- Test: use test public key + test client secret with test card/wallet (D same page).

**Pixel (embedded JS SDK)** (D `checkout-experiences/pixel-embedded`, updated 2026-09-07):
- Include `https://cdn.jsdelivr.net/npm/paymob-pixel@latest/styles.css`, `.../main.css`, `.../main.js` (type module). npm package `paymob-pixel` (PROBE npm registry: latest 1.2.10, 55 versions, modified 2026-10-27, "Paymob Web SDK, help our merchant to have the native payment experience").
- `new Pixel({ publicKey, clientSecret, paymentMethods: ['card','google-pay','apple-pay'], elementId, disablePay, showSaveCard, forceSaveCard, beforePaymentComplete, afterPaymentComplete, onPaymentCancel (Apple Pay only), cardValidationChanged, customStyle })`.
- `paymentMethods` accepts only `"card"`, `"google-pay"`, `"apple-pay"`. **No wallet, kiosk, BNPL in Pixel.** (Confirmed by D page and SKILL `choose-integration.md`: "wallets, BNPL, and kiosk go through Unified Checkout".)
- `disablePay: true` + `dispatchEvent` named `payFromOutside` lets you use your own pay button. `updateIntentionData` updates the intention in the SDK.
- `customStyle` keys: Font_Family, Font_Size_*, Color_Primary, Color_Container, Radius_Border, Width_of_Container, ... plus `Direction: 'rtl'`, `Label_Text`, `Placeholder_Text`, `Error_Text`, `Button_Text`, `Hint_Text` for Arabic localization (full sample in the page).
- Warning on page: "Never put the Secret Key in frontend code. Backend creates/updates intentions; frontend only receives public key and client secret."
- `afterPaymentComplete(response)` is client-side; do not trust it for fulfilment.
- Apple Pay via Pixel needs domain verification + certificates (section 4).
- Webview: "The webview doesn't support the Apple Pay payment method; you should integrate through the SDK" (D `integration-paths/overview`).

**Recommended for Lemely** (my judgment, not Paymob's): start with Unified Checkout redirect (covers card + wallet + later Apple Pay/kiosk with zero frontend code and keeps PCI scope minimal), add Pixel only if an embedded card form is wanted.

### 2.4 Post-payment: callbacks (brief; another agent owns this lane)
D `webhook-callbacks-and-hmac/*`:
- Two callbacks: **Transaction Processed Callback** (server POST JSON to `notification_url`) and **Transaction Response Callback** (browser GET redirect to `redirection_url` with query params; "Don't use ... to update your order status").
- Sent only when the transaction succeeds or is declined (an abandoned 3DS or abandoned checkout yields no callback: reconcile with Transaction Inquiry).
- Key POST fields: `obj.id` (transaction id), `obj.success`, `obj.order.id` (= `intention_order_id`), `obj.is_refunded`, `obj.refunded_amount_cents`, `obj.is_voided`, `obj.is_captured`, `obj.captured_amount`; merchant ref appears as `merchant_order_id` (from `special_reference`).
- HMAC: SHA-512 with HMAC secret over concatenated values of a fixed lexicographically sorted key list (amount_cents, created_at, currency, error_occured, has_parent_transaction, obj.id, integration_id, is_3d_secure, is_auth, is_capture, is_refunded, is_standalone_payment, is_voided, order.id, owner, pending, source_data.pan, source_data.sub_type, source_data.type, success) compared to the `hmac` query param. (Full list is in `raw/webhook-callbacks-and-hmac__hmac__hmac-transaction-callback.md`.)
- Transaction inquiry (fallback): `GET api/acceptance/transactions/{id}` (Bearer auth token) and `POST api/ecommerce/orders/transaction_inquiry` with `order_id`/`merchant_order_id` (docs say use only for manual checks or missed callbacks).
- Local dev: need a public URL (ngrok etc.) for `notification_url`; Paymob cannot hit localhost.

---

## 3. Legacy Accept flow (auth token, order, payment key, iframe)

- The current docs contain **no pages** for `POST api/ecommerce/orders` (order registration), `POST api/acceptance/payment_keys`, or iframe URLs. The page set is entirely Intention-based (see index below).
- Evidence it is superseded but still around:
  - FAQ: "Occurs when a merchant requires setting up a new IFrame integration. We recommend using Unified Checkout, our latest checkout experience ... All new merchants are encouraged to adopt this experience. If you are an existing merchant currently using the IFrame integration and require a new IFrame setup, ... this request must be handled by our team." (D `need-help/faqs`)
  - Intention response still carries `payment_keys[].iframe_id` and `order_id` (see 2.1).
  - Surviving legacy-style endpoints in docs: `POST api/auth/tokens`, `api/acceptance/void_refund/*`, `api/acceptance/capture`, `api/acceptance/transactions/{id}`, `api/ecommerce/orders/transaction_inquiry`, `api/ecommerce/payment-links`, `POST api/acceptance/payments/pay` (MIT with card token). These are the "management" APIs that remain current.
- No page says "deprecated" in so many words. Verdict: **legacy flow is de-emphasised/closed to new merchants, not formally announced as deprecated in the docs.** Do not build on it.
- Old community SDK repos (paymob-python/-node/-php/-java) last pushed 2021-2022 are for the legacy flow (PROBE GitHub org PaymobAccept).

---

## 4. Payment methods in Egypt

Source tables: D `payments-and-features/payment-methods/*` (alias URLs `payment-methods/...`), SKILL `references/payment-methods.md` (checked 2026-10), D `getting-started/overview`.

| Method | EGY? | Test integration IDs? | Refund | Notes |
|---|---|---|---|---|
| Cards (Visa, Mastercard; Amex conditional) | Yes | Yes (Cards "MIGS" test integration) | full/partial; void; capture for Auth/Cap | 3DS default; Paymob hosts 3DS. "EGY: VISA, Mastercard, Amex (Conditional; coordinate with the account manager to enable)" |
| Mobile wallets (Vodafone Cash, Orange Cash, e& money, We Pay, bank wallets) | Yes (EGY only) | Yes | full/partial | `redirection_url` supported for wallets. Unified Checkout only (not Pixel) |
| Apple Pay | Yes ("all regions EGY, KSA, UAE, OMN") | **No: "The Apple Pay payment method has Live integration IDs only."** | full/partial | Needs certificates (+ domain verification for Pixel/WooCommerce). Unsupported in mobile webviews |
| Google Pay | **No for EGY.** Page URL `google-pay-ksa-uae-omn` 404s on `.md`; SKILL says KSA, UAE only; D overview lists it under quick payments generally | No (live only) | | Do not plan on it for Egypt |
| Kiosk (Fawry-style cash outlet) | Yes (EGY only) | Test+Live IDs exist; SKILL says no sandbox path (confirmed w/ Paymob Aug 2026) | **no refunds** | Async: customer pays cash later. Provider name not stated in docs (no "Fawry" mention found) |
| Bank installments | Yes | Live only | full/partial | Needs instalment-enabled banks; EXCLUDE per brief |
| BNPL (valU, Souhoola, Sympl, Halan, etc. 15 providers) | Yes | Live only, no sandbox | provider-dependent | EXCLUDED by product owner |
| InstaPay | **Not found anywhere in the docs** (grep across all 236 fetched pages) | | | Not offered per docs |
| Samsung Pay | UAE only | | | n/a |
Notes:
- "Not all payment methods are enabled by default. Availability depends on your merchant account setup. Reach out to your Paymob account manager" (D `getting-started/overview`). Each method has its own Integration ID.
- MOTO and Verification card types are enabled per account by Paymob (SKILL), not self-serve.
- Methods catalogue: D `payments-and-features/payment-methods` lists Card, Mobile Wallets, BNPL, Apple Pay, Google Pay, Kiosk.

### 4.1 Cards
- Card payment types (D `payment-methods/cards-all-regions`, updated 2026-10-05): Normal 3DS (default; bank OTP), Moto (passes OTP and CVV), Card On File (passes OTP only), Auth/Cap, Verification.
- Supported actions: Void for all types, Refund full/partial for all types, Capture full/partial for Auth/Cap.
- 3DS needs no implementation: Paymob hosts it inside Unified Checkout / Pixel / SDKs (SKILL).
- Saved cards: customer opts in at checkout (Pixel `showSaveCard`/`forceSaveCard`, or dashboard "Save Card" toggle); the card token arrives in the callback to `notification_url`; later pay with token via MIT (`POST api/acceptance/payments/pay`, `source: {identifier: <token>, subtype: "TOKEN"}`) or CIT via intention (D `payments-and-features/core-features/pay-with-saved-cards`, `pay-with-saved-cards/*`). "Forced" saving requires a dedicated integration ID configured by account manager (D `need-help/faqs`).

### 4.2 Mobile wallets: how the flow differs
Official docs do not describe the wallet UI steps. What is documented:
- Wallet goes through the **same Intention + Unified Checkout** path; you just put the wallet Integration ID in `payment_methods` (alone or together with the card ID so the customer picks a tab).
- `redirection_url` supported for wallets; refunds full/partial supported.
- Sandbox wallet: number `01010101010`, MPIN `123456`, OTP `123456` (D `need-help/setup-guides/test-credentials`). SKILL: customer completes wallet OTP entirely on the Paymob page.
- Callback shape differs slightly from cards (SKILL `hmac-verification.md`: wallet callbacks can return null `source_data` fields; stringification of null in the HMAC concatenation is undocumented, capture a real wallet callback first).
- Wallet payment may remain pending until the user approves on phone; rely on webhook plus transaction inquiry.
- Bank wallets and e& money, We Pay listed; availability per account.

### 4.3 Apple Pay (D `need-help/setup-guides/apple-pay-setup`, `.../apple-pay-domain-verification`, `.../apple-pay-certificates-creation`, updated 2026-07-28)
- Setup by integration type: Mobile SDKs = certificates only; Pixel (embedded) = **domain verification + certificates**; WooCommerce plugin = domain verification + certificates. Hosted Unified Checkout is not mentioned in this table (open question).
- "Apple Pay isn't supported through webview integrations (mobile app webviews). Use the SDK instead."
- Domain verification: needs an Apple Developer account; create a Merchant ID; add domain (no https/www); download file `apple-developer-merchantid-domain-association` (do not rename); serve it at `https://yourdomain/.well-known/apple-developer-merchantid-domain-association` (chmod 644); click Verify in Apple portal.
- Certificates: two are required for every Apple Pay integration: **Merchant Identity Certificate** (RSA key via `openssl genpkey -algorithm RSA`, CSR, upload to Apple, convert `.cer` to PEM) and **Payment Processing Certificate** (EC key `prime256v1`, CSR with Common Name = exact domain, upload to Apple, convert to PEM). You end with 6 files; **send them zipped (password-protected) by email to support@paymob.com** with the password through another channel. (There is a helper tool on the page.)
- Live integration ID only; no sandbox. Needs Apple Developer Program membership (paid; Apple's requirement, not stated by Paymob).

### 4.4 Google Pay, kiosk, InstaPay
- Google Pay: not for Egypt (above).
- Kiosk: EGY only; customer gets a reference and pays cash at a kiosk; no refunds; callback can come hours or days later (SKILL).
- InstaPay: no mention in docs. If wanted, ask Paymob support (it may exist as an account-specific method or via bank wallets).

---

## 5. Test mode

Source: D `need-help/setup-guides/test-credentials` (updated 2026-06-01); SKILL `test-credentials.md`.
- Test cards (all: holder "Test Account", expiry 01/39, CVV 123): Mastercard `5123456789012346`; Mastercard `5123450000000008`; Visa `4111111111111111`.
- Test wallet: number `01010101010`, MPIN `123456`, OTP `123456`.
- 3DS challenge in sandbox: SKILL says the same cards walk through 3DS prompts. No decline-simulation cards are documented; ask the account manager for failure-path testing (SKILL, "Paymob does not officially document decline-simulation cards").
- Sandbox test data (transactions/intentions) are stored for **30 days** (SKILL).
- Test integrations can be added in dashboard > Payment Integrations: Cards (MIGS), Wallets, Kiosk (D `getting-started/dashboard`). Test keys use the same base URL as live; a test secret key with a live integration ID (or vice versa) returns 404.
- PayMe (permanent payment link) is **live mode only** (D `need-help/faqs`).
- Not testable in sandbox: Apple Pay, Google Pay, bank installments, BNPL, kiosk (SKILL). First real transaction per method is the test.
- Test webhooks: https://hooks.paymob.com/ (inspect only) or a tunnel; Webhook Testing Tool page in D `webhook-callbacks-and-hmac/webhook-testing-tool`.
- Switching to live: swap keys + integration IDs only (no code change if env-driven); live keys/IDs are issued after risk/technical approval (D checklist). The glossary recommends rotating keys on go-live.

---

## 6. SDKs and libraries

| Item | Detail | Source |
|---|---|---|
| `paymob-pixel` (web, npm) | latest 1.2.10 (2026-10-27); loaded from jsDelivr in docs (`@latest`); card, Google Pay, Apple Pay; no TypeScript types verified | PROBE npm registry; D pixel page |
| iOS SDK | Swift Package `https://gitlab.com/paymob-public/paymobsdk.git`; cards, wallets, Apple Pay, Google Pay, bank instalments, BNPL | D `mobile-sdks/ios-sdk` |
| Android SDK | Manual `.aar` download + `com.paymob.sdk:Paymob-SDK:{{latest version}}`; cards, wallets, Google Pay, instalments, BNPL | D `mobile-sdks/android-sdk` |
| Flutter | `flutter_paymob_sdk` via git `https://github.com/PaymobAccept/flutter_sdk.git` (min Android SDK 23, iOS 13) | D `mobile-sdks/flutter-sdk` |
| React Native | `paymob-reactnative` installed from git `https://github.com/PaymobAccept/paymob-reactnative-sdk.git` (not on npm: registry 404; no Expo Go) | D `mobile-sdks/react-native-sdk`, PROBE |
| Python | **No official Python SDK for the Intention API.** Official `PaymobAccept/paymob-python` repo is legacy (last push 2021-12). PyPI `paymob` 1.0.0 ("Paymob FLASH SDK") and `paymob-accept` 0.1.1 are third-party/old. Plain `httpx` against the REST API is the practical choice. | PROBE GitHub/PyPI |
| AI skill + MCP | Official Claude Code skill (`claude plugin marketplace add PaymobAccept/Paymob-AI-Integration-Skill`), v3.3.0; Paymob MCP server `https://mcp.paymob.com/mcp` (OAuth with dashboard login; **Egypt only**; ~25 tools: create/update intention, payment links, transactions, balances, instant settlement, invoices). Includes money-movement tools: use test mode and human confirmation. | D `ai-agent-skill`, `model-context-protocol-mcp` |
| Postman | https://github.com/PaymobAccept/API-Postman-Collections | D intention overview, PROBE GitHub |
| E-commerce plugins | WooCommerce, Shopify, Magento 2, Odoo, OpenCart, PrestaShop, WHMCS, CS-Cart, ZenCart, Joomla, Laravel-Bagisto, osCommerce, Drupal, Staah | D `integration-paths/plugins/*` (irrelevant to Lemely) |

Caution on the MCP/skill: it is Paymob's own tooling; the Lemely team can use the skill for code generation but should not give the MCP live credentials without scoping.

---

## 7. Things I stumbled on that belong to other lanes (pointers only)

- **Marketplace money flow (tutor payouts):** D has "Split Features" (`payments-and-features/core-features/split-features`, `split-features-implementation`): *Split Amount* = one payment divided among multiple parties/sub-accounts at payment time ("marketplaces with multiple sellers, platforms taking commissions"), configured per account setup; *Split Payment* = up to 3 cards per payment. Separately **Payouts / "Paymob Send"** (`beyond-payments/payouts/*`, `payouts-apis/*`: cash-in to Vodafone Cash, Etisalat Cash, Orange, bank wallet/card/instant, Egyptian Post; own auth token endpoints) and **Partner Onboarding** (`partner-onboarding-apis-1/*`). Payouts/legal agent should confirm requirements.
- **Subscriptions**: Paymob native subscription module (plans + subscriptions, card only, initial 3DS CIT then MITs, with plan/subscription action endpoints and own callback HMAC). Pages in index below.
- **Disputes**: dashboard supports chargeback handling; if you fully refund before a dispute Paymob auto-responds (D `getting-started/new-dashboard`).
- **Refund prerequisites:** FAQ says refunds can fail for **insufficient account balance** (D `need-help/faqs`), so the Paymob balance must hold enough cash to refund.
- **Instant settlement** exists (`request_instant_settlement` MCP tool; dashboard "instant_settlement_enabled" field in profile). Fees/timing not documented here.
- Refund/void/capture API: `POST api/acceptance/void_refund/refund` body `transaction_id`, `amount_cents` (cents), `Token sk_...`; `.../void` body `transaction_id`; `api/acceptance/capture` body `transaction_id`, `amount_cents`.
- Auth token response leaks lots of profile fields incl. `commercial_registration`, `identification_number`, `national_id`; shows these exist on the merchant profile (data model hint only, not proof they are mandatory).

---

## 8. Open questions / unclear in docs

1. **Is a commercial register or tax card required** to get a *live* Egypt account? Docs only say "Paperwork Validation: business and legal documents are reviewed", "Completed business verification". Not specified. (Legal agent / Paymob sales.)
2. Does **Apple Pay appear on the hosted Unified Checkout page** (redirect) or only in Pixel/SDK? The Apple Pay setup table lists only Pixel, SDK, WooCommerce; the method page lists "APIs, Mobile SDKs, Plugins, Payment Links" as channels. Needs support confirmation, along with whether domain verification is needed for the hosted flow.
3. **Apple Pay on Egypt accounts**: docs list EGY as supported but Live-IDs-only; requires Apple Developer Program and emailing six certificate files to support@paymob.com. Lead time unknown.
4. **InstaPay**: not mentioned. **Fawry**: kiosk is generic "kiosk"; no provider named.
5. **billing_data**: exactly which fields are enforced server side (docs contradict: schema vs error example). Are dummy values like "NA" accepted for address fields? Sample uses "dumy". Is `phone_number` format validated (Egyptian +20 vs 01xxxxxxxxx)?
6. **`special_reference` uniqueness**: described as "unique" but enforcement/duplicate behaviour not stated. Matters for idempotent retries (a duplicate intention creation for the same reference).
7. **`expiration` default** and `client_secret` lifetime: Pixel doc says 1 hour; SKILL says single-use; create doc example uses 3600. Unclear what happens on a second payment attempt after a decline (dashboard has a "payment retries" toggle).
8. `notification_url` support: Create page says all payment methods, Update page says "only card Integration IDs". Need to test wallets.
9. Whether **amount in `items` is required** (schema says items optional but each item needs name+amount; a 400 appears for missing item name/amount). Safe: always send one item per bundle/session.
10. **Rate limits, idempotency keys, callback retry policy** and secret key rotation: not covered in my pages ("rate limiting" claimed generically on the Security page).
11. **Auth token lifetime** for `api/auth/tokens` is not documented; refunds use Token sk_ so we may avoid auth tokens except for inquiry.
12. Sandbox: cards-only decline simulation not documented; 3DS sandbox behaviour inferred from SKILL.
13. Two different Egypt hostnames: API on `accept.paymob.com`, checkout on `eg.checkout.paymob.com` (doc consistent; old `/unifiedcheckout/` 302s).
14. Whether test-mode MIGS/"Card (VPC)" integration for Egypt is created automatically at account creation or requires the dashboard step "Add test integration" (dashboard text says you can add test integrations for Cards (MIGS), Wallets, Kiosk).
15. Doc page `payment-methods/google-pay-ksa-uae-omn` returns 404 (stale sitemap/link), and an FAQ link `need-help/faq` 404s, so some navigation links are broken.

---

## 9. Full docs page index

Enumeration method: https://developers.paymob.com/llms.txt and /llms-full.txt and /sitemap.xml at the site root return "not available / Project not found". The working endpoints are **under the doc slug**: `https://developers.paymob.com/paymob-docs/llms.txt` (147 pages, concatenated text with summaries only: no request schemas), `https://developers.paymob.com/paymob-docs/sitemap.xml` (102 URLs). Every page also has `<url>.md` (raw markdown including embedded endpoint/schema JSON for API pages). I fetched 236 URL variants (157 unique canonical pages after dropping alias duplicates; both `.../integration-paths/plugins/shopify` style structured URLs and short alias URLs resolve). Navigation tabs: Documentation (guides), Developers (API reference), AI Solutions.
Alias note: many pages exist under both a long structured path (e.g. `intention-apis/create-intention`) and a short sitemap path (`create-intention`); sitemap uses the short ones. Both work. `payment-methods/*` pages are listed by their short alias because the long form `payments-and-features/payment-methods/*` is only reachable via the alias list.
Pages with descriptions beginning `[METHOD path]` are API endpoint pages.

| Path (under https://developers.paymob.com/paymob-docs/ ; append `.md` for raw markdown) | Description |
|---|---|
| `ai-agent-skill` | Your agent produces correct, copy-ready Paymob integration code (Intention API, HMAC verification, mobile wallets, BNPLs, Apple Pay) instead of guessing at the API. |
| `authentication-request-generate-auth-token-1` | [POST api/auth/tokens] Generate an Auth token to use for authentication across multiple API endpoints (e.g., Subscription APIs, create QuickLink). |
| `beyond-payments` | Know what's covered under Beyond Payments and which path to follow next, whether you're sending payouts or onboarding merchants as a partner. |
| `beyond-payments-1` | Beyond Payments |
| `beyond-payments/partner-onboarding` | Understand how partner onboarding differs from a standard merchant integration, and walk through the full flow from setup to merchant status checks. |
| `beyond-payments/payouts` | Understand what Paymob Payout is, how to use it, and how to get started |
| `beyond-payments/payouts/dashboard` | Full guide for using the Paymob Send dashboard to manage disbursements |
| `beyond-payments/payouts/disbursement-channels` | Understand the available disbursement channels, what each one requires, and how to pick the right one for your use case |
| `beyond-payments/payouts/how-it-works-1` | Understand the end-to-end disbursement flow, from funding your balance to money reaching your recipients |
| `checkout-experiences/affordability-widget` | Add the Affordability Widget to your Product or Cart page and connect a selected plan to checkout. |
| `checkout-experiences/overview` | Understand the checkout experiences supported by Paymob, and know when to use Unified Checkout vs. Pixel. |
| `checkout-experiences/pixel-embedded` | Integrate Paymob's pre-built UI (Pixel) in the merchant's checkout. |
| `checkout-experiences/unified-checkout-redirection` | Redirect the customers to Paymob's Unified Checkout to process and complete the payment, and customize the Unified Checkout. |
| `getting-started/dashboard` | Full and quick guide for the Paymob dashboard |
| `getting-started/integration-checklist` | Confirm that your integration is complete, tested, and ready for a smooth go-live |
| `getting-started/new-dashboard` | Full and quick guide for the new Paymob dashboard |
| `getting-started/onboarding-wizard` | Build the integration plan using this interaction wizard |
| `getting-started/overview` | know where to start, what you need, and which path makes the most sense for you |
| `integration-paths/apis` | Understand the overall API payment flow, the available checkout options, and how payment results are securely communicated back to your system |
| `integration-paths/mobile-sdks` | Understand the overall Mobile flow, the available checkout options, and how payment results are securely communicated back to your system |
| `integration-paths/no-code` | Start accepting online payments using Payment Links even without a website or development team |
| `integration-paths/no-code/payme` | Create your PayMe handle and start collecting payments in minutes |
| `integration-paths/no-code/payment-links` | Create and share payment links in minutes, receive payments via any channel |
| `integration-paths/overview` | Understand the overall payment flow and the available integration options |
| `integration-paths/plugins` | Integrate Paymob payments into your existing e-commerce platform without writing code |
| `integration-paths/plugins/cs-cart` | Explore, Install, and Configure Paymob's CS-Cart plugin |
| `integration-paths/plugins/drupal` | Explore, Install, and Configure Paymob's Drupal plugin |
| `integration-paths/plugins/joomla` | Explore, Install, and Configure Paymob's Joomla plugin |
| `integration-paths/plugins/laravel-bagisto` | Explore, Install, and Configure Paymob's Laravel-Bagisto plugin |
| `integration-paths/plugins/magento` | Explore, Install, and Configure Paymob's Magento plugin |
| `integration-paths/plugins/odoo` | Explore, Install, and Configure Paymob's powerful Odoo modules |
| `integration-paths/plugins/opencart` | Explore, Install, and Configure Paymob's OpenCart plugin |
| `integration-paths/plugins/oscommerce` | Explore, Install, and Configure Paymob's ZenCart plugin |
| `integration-paths/plugins/prestashop` | Explore, Install, and Configure Paymob's PrestaShop plugin |
| `integration-paths/plugins/shopify` | Successfully activate Paymob payment services on your Shopify store and process transactions |
| `integration-paths/plugins/staah` | Explore, Install, and Configure Paymob's Staah plugin |
| `integration-paths/plugins/whmcs` | Explore, Install, and Configure Paymob's WHMCS plugin |
| `integration-paths/plugins/wordpress` | Explore, install, and Configure Paymob's powerful WooCommerce plugin |
| `integration-paths/plugins/zencart` | Explore, Install, and Configure Paymob's ZenCart plugin |
| `intention-apis/create-intention` | [POST v1/intention/] Create an Intention that will be used to complete a payment, either via APIs or through one of our UI options. |
| `intention-apis/overview` | Understand what Paymob's Payment Intention is and its APIs |
| `intention-apis/update-intention` | [put v1/intention/{client_secret}/] Update the (amount, payment_methods, items, billing_data, special_reference, notification_url, and redirection_url) of an existi |
| `manage-payment-apis/capture` | [post api/acceptance/capture] Capture Auth transactions through API |
| `manage-payment-apis/refund` | [post api/acceptance/void_refund/refund] Refund transactions through API |
| `manage-payment-apis/void` | [post api/acceptance/void_refund/void] Void transactions through API |
| `mobile-sdks/android-sdk` | Integrate Paymob's native Android SDK |
| `mobile-sdks/flutter-sdk` | Integrate Paymob's official Flutter SDK |
| `mobile-sdks/ios-sdk` | Integrate Paymob's native iOS SDK |
| `mobile-sdks/overview` | > > Know the available Mobile SDKs and how it works. > > > > |
| `mobile-sdks/react-native-sdk` | Integrate Paymob's React Native SDK |
| `model-context-protocol-mcp` | Connect an MCP client to your Paymob account and start using it to create payment links and more |
| `need-help` | Quickly find the right resource: complete setup steps, resolve common issues, or check a definition or security detail |
| `need-help/faq/apple-pay-certificates-creation` | ### What You'll Create * Certificate 1: Merchant Identity Certificate (verifies your business) * Certificate 2: Payment Processing Certificate (encrypts |
| `need-help/faq/apple-pay-domain-verification` | ### How to verify? 🔵 For Everyone: 1. Go to [Apple Developer Portal](https://developer.apple.com/account/) 2. Sign in with your Apple ID 3. Click "Certificat |
| `need-help/faq/getting-integration-credentials` | Get the Paymob credentials that will be used during the integration |
| `need-help/faq/test-credentials` | Get the test credentials to make test transactions while using test integration IDs |
| `need-help/faqs` | Explore common issues and the most commonly raised inquiries for faster resolution |
| `need-help/glossary` | Quickly understand key Paymob terms and payment concepts so you can navigate the documentation, dashboard, and APIs with confidence |
| `need-help/security-and-privacy` | Understand how security is embedded throughout Paymob's product lifecycle |
| `need-help/setup-guides` | Determine which Apple Pay setup steps your integration method requires, and complete domain verification and certificate creation |
| `need-help/setup-guides/apple-pay-setup` | Understand which setup steps your integration method requires and complete domain verification and certificate creation for Apple Pay |
| `need-help/setup-guides/apple-pay-setup/apple-pay-certificates-creation` | ### What You'll Create * Certificate 1: Merchant Identity Certificate (verifies your business) * Certificate 2: Payment Processing Certificate (encrypts |
| `need-help/setup-guides/apple-pay-setup/apple-pay-domain-verification` | ### How to verify? 🔵 For Everyone: 1. Go to [Apple Developer Portal](https://developer.apple.com/account/) 2. Sign in with your Apple ID 3. Click "Certificat |
| `need-help/setup-guides/getting-integration-credentials` | Get the Paymob credentials that will be used during the integration |
| `need-help/setup-guides/test-credentials` | Get the test credentials to make test transactions while using test integration IDs |
| `partner-onboarding-apis` | Partner Onboarding APIs |
| `partner-onboarding-apis-1/auth` | Authenticate as a partner, create your Partner API Key, and retrieve your HMAC secret. |
| `partner-onboarding-apis-1/auth/create-and-use-partner-api-key` | [POST api/auth/partner-api-keys] Create the Partner API Key you'll use to authenticate every onboarding request, and see how it's used differently across endpoints. Last Updated |
| `partner-onboarding-apis-1/auth/login` | [POST api/auth/tokens] Authenticate as a partner and get an auth token, used to generate your Partner API Key. |
| `partner-onboarding-apis-1/auth/retrieve-partner-hmac-secret` | [GET api/auth/hmac_secret/get_hmac] Retrieve the HMAC secret tied to your partner account. |
| `partner-onboarding-apis-1/onboarding-flow` | Register a merchant, walk them through the onboarding schema step by step, and check their status. |
| `partner-onboarding-apis-1/onboarding-flow/get-onboarding-schema` | [GET api/onboarding/flow/schema] Retrieve the current onboarding step's required fields and documents for a registered merchant. |
| `partner-onboarding-apis-1/onboarding-flow/partner-merchant-inquiry` | [GET api/onboarding/auth/partner-merchant-inquiry] Check a merchant's onboarding progress, legal status, and live integrations at any point after registration. |
| `partner-onboarding-apis-1/onboarding-flow/register-merchant` | [POST api/onboarding/auth/partner-register] Register a new merchant under your partner integration and get back the Merchant ID (MID) you'll use in every subsequent onboarding call. Last U |
| `partner-onboarding-apis-1/onboarding-flow/submit-onboarding-step` | [POST api/onboarding/flow/submit/{schema_id}/{step_id}/] Submit a merchant's data and documents for the current onboarding step. |
| `partner-onboarding-apis-1/overview` | Understand what the partner onboarding APIs let you do, and find the section you need to authenticate, register merchants, and manage their onboar |
| `pay-with-saved-cards/cit` | Make the customer pay with the saved card through one of the Paymob UIs without re-entering their card details |
| `pay-with-saved-cards/create-card-token` | Create a Card Token to be used in future payments |
| `pay-with-saved-cards/mit` | [POST api/acceptance/payments/pay] Make the merchant deduct from a saved card without the customer's interaction |
| `payment-methods/apple-pay-all-regions` | Understand how BNPL payments work, the supported providers, regional availability, and how customers complete payments |
| `payment-methods/bank-installments-egy` | Understand how bank installments work and the customer payment experience |
| `payment-methods/bnpls-egy-ksa-uae` | Understand how BNPL payments work, the supported providers, regional availability, and how customers complete payments |
| `payment-methods/cards-all-regions` | Understand how card payments work, the supported card networks, the regions where they are available, and the supported transaction actions (refund, void, and capture) |
| `payment-methods/kiosk-egy` | Understand how kiosk payments work and the end-to-end customer payment experience |
| `payment-methods/mobile-wallets-egy-ksa` | Understand how mobile wallet payments work, the supported wallet providers, the regions where they are available, and the customer payment experience |
| `payments-and-features/core-features` | Understand the key payment management and value-added features offered by Paymob, and identify which features are most relevant to your business mode |
| `payments-and-features/core-features/affordability-widget` | Understand what the Affordability Widget does and how it helps customers decide to buy |
| `payments-and-features/core-features/auth-cap` | Understand how Authorization & Capture works, when to use it, and how it helps control when customer funds are reserved and collected |
| `payments-and-features/core-features/convenience-fee` | Understand what convenience fees are, the supported configuration options, and how they can be applied to card and wallet payments |
| `payments-and-features/core-features/pay-with-saved-cards` | Understand what “Pay With Saved Cards” is, how it benefits your business and customers |
| `payments-and-features/core-features/split-features` | Understand the available split options, how each one works at a high level, and determine which split feature best fits your business model |
| `payments-and-features/core-features/subscriptions` | understand what Paymob Subscriptions are and how they work, when to use subscriptions instead of manual recurring charges, the key benefits and limitations of the feature |
| `payments-and-features/core-features/transaction-inquiry-and-reports` | Understand the available ways to access transaction data and card tokens, and identify which option best fits your needs |
| `payments-and-features/managing-payments` | Understand the different types of payment management actions and when to use each one |
| `payments-and-features/managing-payments/capture` | Understand what capture is, how it works at a high level, and when to capture the authorized amount or a lesser amount before it is automatically voided |
| `payments-and-features/managing-payments/refund` | Understand what refund transactions are, when to use them, and how to initiate refunds using the Paymob Dashboard |
| `payments-and-features/managing-payments/void` | Understand what void transactions are, when to use them, and how to initiate voids using the Paymob Dashboard |
| `payments-and-features/overview` | Identify the supported payment methods and features, and decide which ones best fit your business needs |
| `payments-and-features/payment-methods` | Identify the supported payment methods and decide which ones best fit your business needs |
| `payouts-apis/auth` | Understand what the Auth section is used for |
| `payouts-apis/auth/generate-auth-token` | [POST api/secure/o/token/] Generate an access token to use for authentication across every other Payouts API request. |
| `payouts-apis/auth/refresh-token` | [POST api/secure/o/token/] Outcome: Refresh an expired access token using your refresh token without resending your username and password. |
| `payouts-apis/cashin-api` | Understand what the Cashin API is used for |
| `payouts-apis/cashin-api/bank-card-cashin` | [POST /api/secure/disburse/] # Bank Card Cashin === ENDPOINT POST /api/secure/disburse/ [HEADERS] - Content-Type [string] = "application/json" - Authorization [string] = "{{TOKEN}}" [BODY] |
| `payouts-apis/cashin-api/bank-instant-cashin` | [POST /api/secure/disburse/] # Bank Instant Cashin === ENDPOINT POST /api/secure/disburse/ [HEADERS] - Content-Type [string] = "application/json" - Authorization [string] = "{{TOKEN}}" [BOD |
| `payouts-apis/cashin-api/bank-wallet` | [POST /api/secure/disburse/] # Bank Wallet === ENDPOINT POST /api/secure/disburse/ [HEADERS] - Content-Type [string] = "application/json" - Authorization [string] = "{{TOKEN}}" [BODY] - iss |
| `payouts-apis/cashin-api/egyptian-post` | [POST /api/secure/disburse/] # Egyptian POST === ENDPOINT POST /api/secure/disburse/ [HEADERS] - Content-Type [string] = "application/json" - Authorization [string] = "{{TOKEN}}" [BODY] - i |
| `payouts-apis/cashin-api/etisalat-cash` | [POST api/secure/disburse/] Disburse funds instantly to a recipient's Etisalat Cash mobile wallet. |
| `payouts-apis/cashin-api/orange-cashin` | [POST /api/secure/disburse/] # Orange Cashin === ENDPOINT POST /api/secure/disburse/ [HEADERS] - Content-Type [string] = "application/json" - Authorization [string] = "{{TOKEN}}" [BODY] - i |
| `payouts-apis/cashin-api/vodafone-cashin` | [POST api/secure/disburse/] Disburse funds instantly to a recipient's Vodafone Cash mobile wallet. |
| `payouts-apis/inquires` | Understand what the Inquires section is used for |
| `payouts-apis/inquires/bulk-transaction-inquiry-banking` | [GET /api/secure/transaction/inquire/] # Bulk Transaction Inquiry banking === ENDPOINT GET /api/secure/transaction/inquire/ [HEADERS] - Content-Type [string] = "application/json" - Authorization [str |
| `payouts-apis/inquires/bulk-transaction-inquiry-by-reference` | [GET api/secure/transaction/inquire/by-reference/] Look up the status of transactions using their custom reference values, instead of transaction IDs. |
| `payouts-apis/inquires/bulk-transaction-inquiry-non-banking` | [GET /api/secure/transaction/inquire/] # Bulk Transaction Inquiry non banking === ENDPOINT GET /api/secure/transaction/inquire/ [HEADERS] - Content-Type [string] = "application/json" - Authorization |
| `payouts-apis/inquires/topup-inquiry` | [GET /api/secure/topup/inquire/] # Topup Inquiry === ENDPOINT GET /api/secure/topup/inquire/ [HEADERS] - Content-Type [string] = "application/json" - Authorization [string] = "{{TOKEN}}" |
| `payouts-apis/inquires/user-budget-inquiry` | [GET api/secure/budget/inquire/] Check the remaining budget available in your Payouts account. |
| `payouts-apis/overview` | Serve as the entry point to the Payouts API section, giving a quick overview of what each part does. |
| `payouts-apis/payout-callbacks` | Understand how Payouts callbacks work for both disbursements and topups, and how to configure your callback URLs to get notified automatically ins |
| `payouts-apis/topup` | Understand what the Topup section is used for |
| `payouts-apis/topup/topup-request-accept-balance` | [POST api/secure/topup/request/] Request a topup to your Payouts merchant budget by transferring balance from your Accept account. |
| `payouts-apis/topup/topup-request-bank-transfer` | [POST api/secure/topup/request/] Request a top-up to your Payouts merchant budget via bank transfer. |
| `quicklink-apis/cancel-quicklink` | [POST api/ecommerce/payment-links/cancel] Cancel a QuickLink through API |
| `quicklink-apis/create-quicklink` | [post api/ecommerce/payment-links] Create a QuickLink through the API |
| `quicklink-apis/overview` | Understand what QuickLinks APIs are used for |
| `split-features-implementation` | Implement Split Payment and Split Amount using the Intention Creation API, and explain how each split type is represented in the payment request. |
| `subscription/create-subscription` | Create a subscription for a user under a specific subscription plan. |
| `subscription/create-subscription-plan` | [post api/acceptance/subscription-plans] Create a subscription plan that defines the characteristics of periodic subscription deductions per user |
| `subscription/hmac-calculation-for-subscription-callback` | Understand the subscription callback and calculate its HMAC |
| `subscription/plan-actions` | know briefly the actions that can be executed on the subscription plan. |
| `subscription/plan-actions/list-subscription-plans` | [GET api/acceptance/subscription-plans] Restore all subscription plans associated with a specific merchant |
| `subscription/plan-actions/resume-subscription-plan` | [POST api/acceptance/subscription-plans/{subscription_plan_id}/resume] Resume a suspended subscription plan |
| `subscription/plan-actions/suspend-subscription-plan` | [POST api/acceptance/subscription-plans/{subscription_plan_id}/suspend] Suspend a subscription plan |
| `subscription/plan-actions/update-subscription-plan` | [PUT api/acceptance/subscription-plans/{Subscription_Plan_Id}] Change a subscription plan’s amount, number of deductions, and integration ID for a specific plan |
| `subscription/subscription-actions` | A brief about the actions that can be executed on the subscription plans |
| `subscription/subscription-actions/add-secondary-card` | Add a secondary card for an existing subscription |
| `subscription/subscription-actions/cancel-subscription` | [post api/acceptance/subscriptions/{Subscription_id}/cancel] Permanently terminate subscription |
| `subscription/subscription-actions/change-subscription-primary-card` | [post api/acceptance/subscriptions/{Subscription_Id}/change-primary-card] Changing the primary card associated with a specific subscription |
| `subscription/subscription-actions/delete-secondary-card` | [POST api/acceptance/subscriptions/{Subscription_id}/delete-card] Delete a secondary card for a specific subscription |
| `subscription/subscription-actions/last-transaction-subscription` | [get api/acceptance/subscriptions/{Subscription_Id}/last-transaction] Retrieving the last transaction details associated with a specific subscription |
| `subscription/subscription-actions/list-subscription-cards` | [get api/acceptance/subscriptions/{Subscription_id}/card-tokens] List all the cards related to a specific subscription |
| `subscription/subscription-actions/list-subscription-details` | [get api/acceptance/subscriptions/{Subscription_id}] Retrieving detailed information for a specific subscription using its unique subscription ID, or fetching all subscriptions associated with a spe |
| `subscription/subscription-actions/list-subscription-transactions` | [get api/acceptance/subscriptions/{Subscription_id}/transactions] Retrieve all transactions associated with a specific subscription ID |
| `subscription/subscription-actions/register-webhook` | [POST api/acceptance/subscriptions/{subID}/register_webhook] Register a webhook endpoint to an existing subscription |
| `subscription/subscription-actions/resume-subscription` | [POST api/acceptance/subscriptions/{Subscription_id}/resume] Reactivating a subscription and resuming billing |
| `subscription/subscription-actions/suspend-subscription` | [post api/acceptance/subscriptions/{subscription_id}/suspend] Suspending a subscription and temporarily stopping its active billing |
| `subscription/subscription-actions/update-subscription` | [put api/acceptance/subscriptions/{Subscription_Id}] Modifying the subscription amount and the subscription end date for a specific subscription |
| `transaction-inquiry-apis/card-token-inquiry` | [POST api/acceptance/order_card_tokens] Retrieve card token details by the Order ID |
| `transaction-inquiry-apis/transaction-inquiry` | Understand the available Transaction Inquiry endpoints and which one to use to retrieve transaction details |
| `transaction-inquiry-apis/transaction-inquiry/by-order-id-or-reference` | [POST api/ecommerce/orders/transaction_inquiry] Retrieve the last transaction details by the Order ID or the Merchant Order ID |
| `transaction-inquiry-apis/transaction-inquiry/by-transaction-id` | [GET api/acceptance/transactions/{transaction_id}] Retrieve transaction details by transaction ID |
| `webhook-callbacks-and-hmac/hmac` | Outcome -Understand the HMAC calculation mechanism. |
| `webhook-callbacks-and-hmac/hmac/hmac-for-card-tokens` | Understand how to calculate the hmac value for the card token callback |
| `webhook-callbacks-and-hmac/hmac/hmac-transaction-callback` | Understand how to calculate the hmac value for the transaction callbacks (Processed and Response) |
| `webhook-callbacks-and-hmac/overview` | Understand the different types of Paymob callbacks, their purposes, and HMAC calculation. |
| `webhook-callbacks-and-hmac/transaction-callbacks` | Understand the different types of Paymob callbacks and the purpose of each one. |
| `webhook-callbacks-and-hmac/webhook-testing-tool` | Allow developers to capture and inspect webhook requests to verify that callback events are triggered correctly and contain the expected data La |
| `wizard` | Wizard |

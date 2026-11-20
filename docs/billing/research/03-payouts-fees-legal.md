# Paymob Egypt: payouts, fees, KYC, regulation, community (research 03)

Research date: 2026-11-02. Web research only. Dates in brackets are the source's own "Last Updated"/published date where shown; "n/d" means the page gave none. Nothing here is legal advice. Confidence is marked HIGH (Paymob primary docs), MED (third-party, consistent), LOW (single/unclear source).

Coverage note: developers.paymob.com/llms.txt returned nothing; paymob.com/llms.txt (updated 2026-04-09) exists and was read. Egypt dashboard docs were read through the search index, not by crawling every page.

---

## 1. Payouts / disbursements (Paymob Send)

### 1.1 What it is and how to get it
- "Paymob Payout (Paymob Send)" is a separate outbound product. Available in Egypt, UAE, KSA. [HIGH] https://developers.paymob.com/paymob-docs/beyond-payments/payouts [2026-07-15]
- **No self-signup.** The docs say "Your account is provisioned by Paymob". The steps are: contact your account manager (or support@paymob.com), sign a legal agreement, receive staging credentials, build, test, get technical approval, then go live on production. [HIGH] same URL.
- The legal agreement step is where the commercial register / tax card question will be decided. The docs do not state requirements. [OPEN QUESTION, see section 7]
- It is **separate from Accept (collections)**. Different hosts, different auth, staging/production environments. [HIGH] https://github.com/PaymobAccept/API-Postman-Collections (created 2026-01-22)
  - Egypt prod `https://payouts.paymobsolutions.com`, staging `https://stagingpayouts.paymobsolutions.com`. The old docs site uses `stg-payouts...`; confirm the host in your staging email.

### 1.2 Auth
- OAuth2 password grant. You send `client_id`, `client_secret`, `username` and `password` to get an access token plus a refresh token. A refresh endpoint exists. The token is a Bearer token and lives about 60 minutes. [HIGH] https://developers.paymob.com/paymob-docs/developers/payouts-apis/auth [2026-07-29]; the 60-minute figure is from https://raw.githubusercontent.com/api-evangelist/paymob/refs/heads/main/openapi/paymob-disbursement-api-openapi.yml (third-party spec, MED).
- The Accept API uses `Authorization: Token <secret_key>` for intentions and API-key-to-token for inquiries. Payouts credentials are entirely separate from those. [HIGH] Postman collection README above.

### 1.3 Endpoints
- New docs describe one endpoint for all channels, `/api/secure/disburse/`, with `issuer` selecting the channel. Issuers: `vodafone`, `etisalat`, `orange`, `bank_wallet`, `bank_card`, `instant_bank`, `post`. [HIGH] https://developers.paymob.com/paymob-docs/developers/payouts-apis/cashin-api [2026-07-29]
- The legacy portal docs describe `disburse/` (Instant Cashin), a bulk endpoint, a bulk inquiry by ID, an inquiry by reference, budget inquiry and topup. [HIGH/MED] https://payouts.paymobsolutions.com/docs/instant_cashin_api/ . The third-party OpenAPI file uses `/disburse/api/v1/disburse/instant_cashin/`, so paths differ between sources. Use the Postman collection from Paymob as the source of truth.
- Request fields:
  - `issuer` and `amount` (up to 2 decimals).
  - `msisdn` for wallets (11 digits, +2 is added automatically).
  - `bank_card_number` (account number, IBAN or card), `bank_code`, `full_name` and `bank_transaction_type` (`cash_transfer`) for bank channels.
  - `national_id`: the legacy docs mark it **mandatory** for the recipient (Egyptian 14-digit ID). Plan to collect tutors' national IDs. [HIGH] legacy doc URL above.
  - `client_reference_id` (uuid4, kept in case of timeouts), `client_reference` (unique), `comment`, and `customer_bears_fees`.
- Status:
  - Wallets are final immediately.
  - `bank_card` takes up to 2-3 working days.
  - `instant_bank` is async (hours), with status by callback or inquiry.
  - Egypt Post is next business day if submitted before 14:00, otherwise within 2 business days. [HIGH] https://developers.paymob.com/paymob-docs/beyond-payments/payouts/how-it-works-1 [2026-07-29]
- Callbacks: configure a disbursement callback URL in the dashboard, or poll the Inquiry APIs. [HIGH] same URL.

### 1.4 Channels, minimums and limits (Egypt)
Source: https://developers.paymob.com/paymob-docs/beyond-payments/payouts/disbursement-channels (n/d) [HIGH]

| Channel | Speed | Min per txn | Notes |
|---|---|---|---|
| Vodafone / Etisalat (e&) / Orange Cash, Bank Wallet | Instant | 1 EGP | Max per txn 60,000 EGP, per day 60,000, per month 200,000. These limits are on the recipient's wallet, not on Lemely. |
| Bank Card (card, account or IBAN) | Up to 3 working days | 5 EGP | Cheapest bank option. The docs say it has the best acceptance ratio. |
| Instant Bank (account or IBAN) | Hours, async | 112 EGP | More expensive. Instant-bank minimum is also stated as 112 EGP in the legacy docs. |
| Egypt Post | Next business day | 5 EGP | Needs national ID plus full name. |

- **InstaPay is not listed as a payout issuer.** It appears only for merchant instant settlement (see 1.7). The wallet list includes Vodafone Cash, Etisalat Cash, Orange Cash and Bank Wallet. The Aman option appears in the dashboard's file-upload tabs ("Vodafone/Etisalat/Aman"), not as an API issuer. [HIGH for the docs, MED for the interpretation]

### 1.5 Funding model (important for design)
- Every disbursement is charged from a **pre-funded "budget"**. The budget is separate from the Accept balance. You top it up by bank transfer (with proof) or by moving balance from the Accept account. A payout over the available budget is declined. [HIGH] how-it-works-1 URL above.
- Portal use has a Maker/Checker flow with a PIN. API use has a single role and no Maker/Checker. [HIGH]
- Fees: by default the merchant pays amount + fee + VAT on top. With `customer_bears_fees: true`, the budget is debited only the amount and the recipient gets amount - fee - VAT. If the recipient's details are wrong and the payout is returned, a customer-bears-fees payout refunds amount minus fees and VAT (fees act as a penalty), while merchant-pays refunds the amount only. System failures refund what was charged. [HIGH] legacy docs.
  - Implication: for tutor payouts, Lemely can pass fees to the tutor via `customer_bears_fees`. This is a product and consumer-law decision.
  - Fee-calculation endpoint: the Cashin overview says you can "Calculate fees and VAT for a disbursement before sending it". [HIGH]

### 1.6 Payout fees
- **Not published anywhere I could find.** The docs example uses "10 EGP fees + 1.40 EGP VAT" and the doc says this is illustrative. The pricing page (paymob.com/en/pricing, n/d) has a Payouts section but the visible text carries only the Accept 2.75% + 3 EGP block. Bank Card is "lower" cost and Instant Bank "higher". [OPEN QUESTION: ask the account manager for the payout rate card. VAT is 14% on fees, matching the example.]

### 1.7 Merchant settlement (Accept to your bank)
Sources disagree, which is itself a finding:
- paymob.com/en/pricing FAQ: "settled in your bank account **weekly**", no monthly fees. [HIGH-ish, undated page]
- Paymob's own WooCommerce plugin page: cards, Apple Pay and Google Pay settle **T+1**, and "instant settlement" is available "in select countries". BNPL varies. [HIGH] https://en-gb.wordpress.org/plugins/paymob-for-woocommerce/ [2026]
- paymentreview.com (2026-09): "Online payments are paid out weekly in Egypt and the UAE", "Your settlement frequency is fixed in your Merchant Application Form." Paymob publishes no paid faster option. [MED]
- Arabic blogs (2023-2025) for **individual accounts**: weekly auto-transfer only, no manual withdrawal, minimum withdrawal 5,000 EGP, one-time account setup fee 1,000-2,000 EGP. [LOW-MED; old] https://www.wpar.net/paymob/ [2023-11-06]; https://www.dropidea.com/en/blog/afdl-boabat-aldfaa-fy-msr-lmtgrk-aal-ook [2025-06-01]. These contradict the "no setup fee" line on the pricing page. Likely the setup fee and 5,000 EGP minimum apply to some account tiers or contracts. Verify.
- paymob.com/llms.txt [2026-04-09]: "Instant Settlement": merchant can request settlement of available funds, possibly via InstaPay or Aani. "Availability, limits, cutoffs, and fees are region/account dependent." [HIGH]
- Takeaway: plan on T+1 to weekly cash flow depending on the contract. Do not assume T+1 until it is in the signed Merchant Application Form.

### 1.8 Split payments / marketplace
- Paymob has **"Marketplace by Paymob"** (https://www.paymob.com/en/marketplace, n/d): "accept payments and distribute payouts automatically", with control over onboarding, payout timing and money movement. Marketing copy only, no pricing or requirements. [MED]
- API: **Split Amount** ("one payment, multiple recipients") is implemented via `split_amounts` on Create Intention: an array of `{mid: <connected_MID>, amount_cents, description}`. Each split part has a "connected MID". Each feature "requires configuration on your account from our side": contact support@paymob.com. [HIGH] https://developers.paymob.com/paymob-docs/developers/split-features-implementation [2026-06-01]; https://developers.paymob.com/paymob-docs/payments-and-features/core-features/split-features [2026-06-01]
  - **Inference (not stated in docs):** a "connected MID" implies each recipient (tutor) is a Paymob merchant/sub-merchant with its own account. That means each tutor would need Paymob onboarding. That could break the "no company, Lemely collects everything" assumption. Confirm with Paymob.
- Partner Onboarding APIs (register merchant, schema, steps, status) exist for partners that onboard merchants programmatically. Requires a Partner API Key. [HIGH] https://developers.paymob.com/paymob-docs/developers/partner-onboarding-apis-1/onboarding-flow [2026-09-15]. Likely aimed at platforms and ISVs. Eligibility unknown.
- Two realistic models:
  - A) Lemely collects into its own Paymob Accept account, then pays tutors via Paymob Send (needs both products and a budget top-up from the Accept balance, which is supported).
  - B) Marketplace/Split Amount, with tutors as connected merchants. Better regulatory story, heavier tutor KYC.

---

## 2. Pricing / fees (Egypt)

| Item | Value | Source |
|---|---|---|
| Standard plan, cards (local) | 2.75% + 3 EGP per transaction, no monthly or subscription fee | https://paymob.com/en/pricing (n/d), https://paymob.com/en/online-payment [HIGH] |
| Wallets (Vodafone Cash etc.) | Pricing page FAQ says "Standard pricing: 2.75% + 3 EGP per transaction" | https://paymob.com/en/pricing [HIGH-ish] |
| Apple Pay | **Not published.** Third-party calculators list "Not published". Treat as the card rate until quoted. | https://daliva.ai/en/eg/payment-gateways/paymob (n/d) [MED] |
| Refund / void | Full and partial refund supported, including for Apple Pay. **No refund fee published.** Whether the 3 EGP fixed fee is returned on refund is unknown. | developers.paymob.com Apple Pay page [2026-06-01]; daliva [MED] |
| Chargeback fee | Not published for Egypt. | daliva [MED] |
| Setup fee | The pricing page says no setup fee. Arabic blogs report 1,000-2,000 EGP one-off. Conflict. | see 1.7 |
| VAT | Other Egyptian gateways quote 14% VAT on the gateway fee. Assume the same for Paymob. | daliva guide; Kashier example [MED] |
| Enterprise | Custom pricing via sales. Rates "automatically adjusted as your business grows." | paymob.com/en/pricing [HIGH] |
| Convenience fee | Paymob lets the merchant add a percentage and/or fixed convenience fee (refundable or non-refundable), with per-card-type rules and uniform fees for wallets. | https://developers.paymob.com/paymob-docs/payments-and-features/core-features/convenience-fee (n/d) [HIGH] |
| Paymob Send fees | See 1.6. Unpublished. | |

- Unverified rate history: UnifyPay shows 2.75% + 2.50 EGP "estimate" since Sept 2022; this conflicts with the official 3 EGP, so ignore it. https://unifypay.io/methods/paymob [LOW]
- Worked example (assumed 3 EGP fixed, VAT on fee 14%): a 100 EGP bundle costs 2.75 + 3 = 5.75 EGP, plus VAT = 6.56 EGP, about 6.6% effective. Small baskets are heavily hit by the fixed fee. A 100 EGP charge returns about 93.4 EGP before any payout fee. Check this against the actual contract. Consider a minimum bundle size or a convenience fee.
- International cards cannot be accepted on individual accounts: a Paymob staff-like commenter said "International transactions won't be accepted for individual accounts, you must be a registered entity". [LOW-MED] https://www.linkedin.com/posts/youssef-al-brawy_im-looking-for-a-payment-gateway-solution-activity-7433951804209516544-G1iO [2026-03-01]. Also stated in the Arabic blogs. Matters if expat students or parents pay by foreign-issued cards.

---

## 3. Onboarding / KYC

### 3.1 Account types
- At signup in the dashboard there are two types: **"Registered Business"** (has a commercial register) and **"Starter Business"** ("for unregistered companies, or individuals and emerging stores"). [MED] https://motaber.com/paymob/ [2023-12-07]; https://www.wpar.net/paymob/ [2023-11-06]. Several Arabic blogs also say Paymob offers an individual account "without a commercial register or tax card". The 2025-26 sources still list Paymob as accepting freelancers: https://daliva.ai/en/eg/payment-gateways/paymob (n/d). I did not find a current primary Paymob page that states this explicitly. [OPEN QUESTION: confirm in writing that Starter Business is still offered in 2026 and what its limits are.]
- New accounts start in Test mode. Moving to Live requires contacting support@paymob.com, the account manager or the dashboard widget. [HIGH] developers.paymob.com (Context7 index of the Egypt docs, n/d)
- The WooCommerce docs describe a newer self-serve flow: upload business documents in a resumable onboarding, then **document verification takes up to 3 days**. Paymob then emails and enables your live integrations. [HIGH] https://woocommerce.com/document/paymob-for-woocommerce/ [2024-06-06]

### 3.2 Documents (third-party, not primary)
- Registered business: commercial register, tax card, owner ID or passport, business bank account. [MED] https://motaber.com/paymob/ [2023-12-07]
- Starter/individual (typical call-back from sales, per one blog): national ID or passport, proof of address (lease, or a home contract for individuals), bank account statement, a signed contract; tax card and company contract only for companies. [LOW-MED] https://www.wpar.net/paymob/ [2023-11-06]
- A 2026 AI-generated answer page lists commercial register and tax card for business accounts and says to ask support about individual onboarding. [LOW, ignore] https://askai.glarity.app/search/What-are-the-requirements-to-open-a-Paymob-account-in-Egypt [2026-09-09]
- Gateway comparison guide: freelancers are usually asked for a **personal** bank account. [MED] https://daliva.ai/en/eg/guides/get-a-payment-gateway
- Paymob's own FAQ has items "What documents are required?", "Is it for individuals or only companies?" and "How long does activation take?" but the answers were elided in the search index. Check https://paymob.com/support/faqs directly. [OPEN QUESTION]

### 3.3 Time to live and failure reports
- Reported activation: "3-7 days" (blog, 2026-04-23). https://samirgeorge.com/writing/payment-gateways-mena/ [LOW-MED]
- Counter-evidence: an individual waited 15+ days with "Your account is currently under review" (LinkedIn, 2026-03-01); a Google review mentions 3-4 days stuck turning an account Live (2024-10-22); a customer waited 5 months with missing documents (2026-01-14). [LOW-MED] https://exa.ai/library/place/7g14bszbnvv [2026-09-14]
- Rejections: a WooCommerce plugin reviewer (2026-09-30) says their account was rejected because "they do not support e-commerce or dropshipping business models" despite valid documents. [LOW] https://en-gb.wordpress.org/plugins/paymob-for-woocommerce/. Shows the compliance team applies business-model judgement.

### 3.4 Apple Pay and wallets
- Apple Pay is "supported in all regions (EGY, KSA, UAE, OMN)". It has **Live integration IDs only** (no test ID). Refund is supported. SDK integrations need Apple Pay certificates. Embedded/Pixel integrations need **domain verification and certificates**. [HIGH] https://developers.paymob.com/paymob-docs/payments-and-features/payment-methods/apple-pay-all-regions [2026-06-01]. Implication: Apple Pay can't be tested on a Test account.
- The plugin docs say enabling Apple Pay or Google Pay in the embedded (Pixel) form "contact your account manager or support@paymob.com", and wait for confirmation. [HIGH] WooCommerce docs above [2024-06-06]. So Apple Pay is an account-manager-gated feature, not a self-serve toggle.
- Wallets: "Not all payment methods are enabled by default. Availability depends on your merchant account setup." [HIGH] https://developers.paymob.com/paymob-docs [2026-08-03]. Wallet integration IDs appear in the dashboard under Payment Integrations. If one is missing, contact support. [HIGH] https://www.odoo.com/documentation/master/applications/finance/payment_providers/paymob.html
- Whether a Starter/individual account can get Apple Pay and wallets was not found. [OPEN QUESTION]

### 3.5 Education sector
- I found **no Paymob-published restricted-category list** for Egypt. Third-party calculators say restricted business types are "Not published." Paymob markets school-fee collection (e.g. OpenEduCat integration, n/d). No evidence either way for tutoring marketplaces. A restricted-category question must go to the account manager.
- Card-scheme high-risk lists used by other acquirers do put tutoring/e-learning and "ongoing services" into restricted categories. That is Zip's list, so it is not Paymob's rule. Mention only as a prompt to ask. [LOW]

---

## 4. Egyptian regulatory context (flag risks, not advice)

1. **CBE licensing of payment services (new, June 2025).** The CBE issued "Rules for Licensing and Registration of Payment System Operators and Payment Service Providers" under Central Bank and Banking Sector Law No. 194 of 2020. They cover payment aggregation, **payment facilitation** and cash collection, apply to any natural or legal person acting in Egypt "or from abroad to its residents", and require licensing as an Egyptian joint stock company with a minimum capital (EGP 10-30 million for PSPs). Existing operators had 12 months to apply (to **June 2026**). [HIGH] https://www.cbe.org.eg/-/media/project/cbe/page-content/rich-text/payment-system/payment-systems-and-services-oversight/rules-for-licensing-and-registration-of-payment-system-operators.pdf [2025-06]; https://www.cbe.org.eg/en/news-publications/news/2025/09/01/13/10/payment-system-operators-and-payment-service-providers [2025-09-01]; https://dailynewsegypt.com/2025/06/21/cbe-issues-new-licensing-framework-for-electronic-payment-service-providers-dailynewsegypt [2025-06-21]
2. **Older facilitator rules (IBA summary, undated, likely 2018-2019 CBE regulations).** Payment facilitators who receive money in their own account must keep a separate account for customer funds, settle to the merchant within three working days, hold a bank guarantee equal to three daily collections, and have a physical office in Egypt. The difference from a technical aggregator is that the facilitator is "involved in the settlement procedure (receiving payments in an account in its name and forwarding the proceeds to the merchant)". https://www.ibanet.org/article/6FC3317B-4F9C-4DFC-BDF1-80CF98B68B21 [LOW-MED, undated]
3. **Risk to flag for Lemely.** Lemely collecting tutor session money into its own Paymob account and paying tutors "later" resembles the facilitator pattern (receiving funds in its name and forwarding them). Whether a platform that is a merchant of record for sessions and pays contractors is caught is a legal question, not answered by these sources. Holding funds for days or weeks also lengthens the exposure. The Paymob-native routes (Split Amount to connected MIDs, or Marketplace) put the licensed entity in the funds flow. This is the main reason to ask Paymob and a lawyer before choosing model A above. Paymob's own terms say the merchant is "solely responsible for the products or services it offers, including ... returns, and refunds", and that Paymob does not mediate (UAE/Tabby tripartite text, and Click by Paymob 8.1; these are about UAE and the customer app, so treat as analogous only). https://paymob.com/click-by-paymob/ (n/d)
4. **Paymob's regulatory framing for Egypt** (its own page): CBE and FRA oversight; Fintech Law No. 5 of 2022; Data Protection Law No. 151 of 2020 (so tutor and student data, including national IDs, falls under it); AML Law No. 80 of 2002; Consumer Protection Law No. 181 of 2018; complaints to the CBE Consumer Protection Department. [HIGH] https://paymob.com/click-by-paymob/ (n/d)
5. **Tax: registration.** The ETA tells online sellers, freelancers, content creators and e-learning operators to open tax files; the documents are national ID, lease or ownership contract, and a utility bill; a person working from home on their ID address can use the ID plus a written declaration. Activity codes: 117 e-commerce, 118/119 content. [HIGH] https://eta.gov.eg/ar/news/ly-mzawly-nshat-altjart-alalktrwnyt-mn-khlal-wshra-almntjat-walkhdmat-wsna-almhtwy-bsrt [2022-05-23]. Taking payments through a gateway creates a visible revenue trail. Having no tax card does not remove the underlying duty; it may only mean the gateway lets you onboard as Starter.
6. **Tax: e-invoicing / e-receipts.** Resident businesses must issue e-invoices for B2B transactions, and e-receipts for sales to final consumers are being phased in by named taxpayer groups (Decision 281 of 2025, effective 2025-09-15; Decision 361 of 2025, effective 2025-11-15). Whether a given small business is on a list must be checked on the ETA site. [HIGH] https://eta.gov.eg/ar/news/sdwr-qrar-rqm-361-lsnt-2025-alkhas-balmrhlt-alfryt-alawly-mn-almrhlt-alryysyt-altast-lmnzwmt [2025-09-25]; https://europe.thomsonreuters.com/compliance/regulatory-updates/egypt (n/d). Paymob's FAQ lists "Can I issue electronic invoices?" with an answer I could not read. [OPEN QUESTION]
7. **Tax: platform VAT.** Egypt's VAT law (since 2023-06-01) defines an "Electronic Distribution Platform" and makes the platform liable to collect VAT on services sold through it to non-registered consumers, **unless** the platform's contracts, receipts and terms clearly say the provider (not the platform) supplies the service and remits the tax. VAT 14% (10% on professional/consulting). Registration threshold 500,000 EGP over 12 months (no threshold for professional/consultancy for non-residents). https://www.pwc.co.za/en/publications/vat-in-africa-ess/egypt-overview.html (n/d); https://www.eta.gov.eg/sites/default/files/2023-03/digital-service-guide-english.pdf (2023). That guidance targets non-resident vendors, but the EDP rule is framed generally. A tutor marketplace is a textbook EDP, so the T&C wording matters. [RISK, needs an accountant]
8. **Consumer refunds.** Law 181/2018 is the general consumer law. I did not find a specific refund-period rule for online services in these sources, so I cannot state one. Paymob supports full/partial refunds and void. A refund path for credits and sessions is a product requirement anyway.

---

## 5. Community knowledge and pitfalls

### 5.1 Support and onboarding
- Trustpilot (paymob.ae, UAE entity): 2.5/5 from about 21 reviews, 75% one-star, with complaints about funds held more than a month, rates above those agreed, slow support, and a platform freeze during enrollment (to 2026-09-02). Different entity from Egypt, so use as a signal about behaviour only. https://www.trustpilot.com/review/www.paymob.ae [MED]
- Review aggregator pulling Google reviews for Paymob (mixed countries): repeated complaints about account turn-live delays, manual closing of transactions, money suspended for a week, and an account deactivated without notice; some positive reviews and a 2023 case where the head of support resolved issues in 2 days. https://exa.ai/library/place/7g14bszbnvv [2026-09-14] [LOW-MED]
- LinkedIn thread: an individual's account stuck "under review" 15+ days; two Paymob employees replied publicly and asked for contact details (2026-03-01). [MED]
- App Store (Egypt) reviews: 3.8/5 from 127; one 2025 review calls the account manager unhelpful for small businesses. https://apps.apple.com/eg/app/paymob/id1625893719 [LOW]
- paymentreview.com summary (2026-09): B- grade; UAE/KSA contracts let Paymob withhold settlements and keep disputed amounts for 120 days after termination; no standing rolling reserve in published terms; Egypt not analysed in as much depth. https://paymentreview.com/reviews/paymob/ [MED]
- No Egypt-specific Reddit/Stack Overflow/Facebook-group threads were found in the search index. I could not verify the dev community at community.paymob.com. [GAP]

### 5.2 Technical pitfalls
- **Webhooks are not guaranteed.** One engineer reported about 2% of transactions never produced a webhook (order stuck pending while the customer was charged). Fix: poll the Inquiry API every few minutes for pending orders. The Paymob docs recommend the same (Inquiry as fallback). [LOW-MED single source, consistent with docs] https://samirgeorge.com/writing/payment-gateways-mena/ [2026-04-23]; https://github.com/paymobaccept/paymob-ai-integration-skill/blob/main/skills/paymob-integration/references/transaction-inquiry.md
- Do not trust the browser redirect (Transaction Response Callback) for order state. Use the server-to-server Transaction Processed Callback with HMAC verification. Paymob docs say this explicitly. [HIGH] https://developers.paymob.com/paymob-docs/developers/webhook-callbacks-and-hmac/transaction-callbacks (n/d)
- HMAC mistakes: the secret is Settings, Account Info, HMAC (not the secret or public key); proxies that rewrite the JSON body break verification. [MED] https://technovision.dev/docs/paymob-payment-provider/troubleshooting
- Iframe/redirect issue on some Android browsers (user stuck after payment); the engineer added a timer redirect. [LOW]
- Test vs Live: keys and integration IDs differ per mode, and mismatches are a common source of API errors. Test and Live share one base URL; mode is set by keys. [HIGH] developers.paymob.com/paymob-docs [2026-08-03]; paymob.com/llms.txt [2026-04-09]
- Auth style differences: intentions use `Authorization: Token <secret_key>` (not `Bearer`); amounts are in cents; inquiry uses an older API-key-to-token flow with a short-lived token. [HIGH] https://github.com/paymobaccept/paymob-ai-integration-skill (Paymob's own AI skill repo; e.g. references/code-python.md, advanced-features.md)
- Apple Pay has no test integration, and a WooCommerce plugin 4.0.0 update was reported to break a site (2025-08-13). [LOW]
- Duplicate or retried callbacks: dedupe on transaction `id`. [MED]
- Legacy "old" Accept flow (auth token, order registration, payment key, iframe) still appears in older tutorials. The current path is the **Intention API + Unified Checkout** or Pixel; prefer the new one. [HIGH] paymob.com/llms.txt, the Postman repo.
- Possible docs drift: payouts docs say `/api/secure/disburse/` while the legacy portal doc and the third-party spec say `disburse/api/v1/disburse/...`. [LOW]

### 5.3 Python libraries
| Package | Status | Notes |
|---|---|---|
| `paymob` (PyPI, PaymobAccept/paymob-python) | 1.0.0 uploaded 2022-04-23; GitHub repo created 2021, 1 star, an HMAC PR open since 2021-12-23 | Official-ish but dormant; `requests` only; has an Intention/refund/void API and a marketplace example. Do not depend on it. https://github.com/PaymobAccept/paymob-python |
| `paymob-solutions` (muhammedattif/Paymob-Solutions) | 35 stars, created 2023-06-12 | Accept only, Payouts "in the next releases". Community project. https://github.com/muhammedattif/Paymob-Solutions |
| `accept-paymob` (Shokr) | 1.0.0 from 2021-05-03 | Old Accept flow; dormant. https://github.com/Shokr/paymob.accept |
| Official Postman collections (PaymobAccept/API-Postman-Collections) | Created 2026-01-22, maintained by Paymob Integration Support | Best machine-readable reference for Accept and Payouts; no secrets in env files. |
| `paymobaccept/paymob-ai-integration-skill` | Paymob's own repo with Python reference code (Intention + HMAC) | Useful for a thin in-house client. |
- Recommendation: write a thin `httpx`/`requests` client (about 200 lines) rather than depend on a stale SDK. No third-party library covers Payouts.

---

## 6. Alternatives (context only)

- **Stripe: not available** for businesses based in Egypt (Egypt absent from Stripe's supported-country list; checked 2026-10-27). https://remotebuilders.io/payments/egypt/ [MED]; https://stripe.com/global. Merchant-of-record options that pay out to Egypt (Paddle, Lemon Squeezy, Polar) exist but are for global digital sales, not EGP wallets or tutor payouts.
- **Kashier**: 2.75% + 3 EGP per card, cards/wallets/Apple Pay/installments/links, digital onboarding for freelancers through enterprises. [MED] https://remotebuilders.io/payments/egypt/ ; daliva table (n/d).
- **Fawry**: cash-at-outlet reference codes (300,000+ points), accepts freelancers per Daliva; settlement weekly per one blog. [LOW-MED] https://bahrtech.net/en/blog/payment-stack-mena-paymob-fawry-stripe [2026-03-12]
- **Geidea**, **PayTabs** (2.5-2.7% + EGP 2-3, 2-day settlement, accepts freelancers per Daliva), **XPay** (2.5% + 2.5 EGP, individual track), **EasyKash** (3.5%, 7-day settlement, freelancers) are the other local options. [LOW-MED] https://daliva.ai/en/eg/payment-gateways (n/d)
- Trade-off summary: Paymob is the broadest local acceptor with a real payouts product and split features, but support quality and onboarding delays are the recurring complaints. Alternatives are cheaper or faster to onboard for individuals but I found no equivalent documented, self-serve payout-to-wallet API.

---

## 7. Open questions and risks (ask Paymob in writing)

1. **Does Starter Business (no commercial register, no tax card) still exist in 2026 for Egypt, and what are its limits?** Per-transaction, monthly volume, international cards, wallets, Apple Pay, payout eligibility.
2. **Paymob Send eligibility:** is a Starter/individual merchant allowed to sign the Payout legal agreement? What documents? Minimum budget top-up? Rate card (wallet, bank card, instant bank, VAT)? The docs are silent, and "no self-signup" means Paymob decides.
3. **Split Amount / Marketplace:** do connected MIDs require each tutor to be a fully onboarded Paymob merchant? What KYC level? Can funds be held and released later? Is there an escrow-like "payout timing" setting (the Marketplace page says payout timing is configurable)?
4. **Settlement:** weekly or T+1 for our contract? Is the 5,000 EGP minimum withdrawal real? Setup fee 1,000-2,000 EGP? Is instant settlement (InstaPay/Aani) available and at what fee?
5. **Fees:** Apple Pay rate, wallet rate, refund fee (is the 3 EGP fixed fee refunded?), chargeback fee, international-card rate, VAT on fees.
6. **Restricted categories:** is an online tutoring marketplace / AI exam-marking service in scope? Do they object to "pay-per-use credits" (stored value) or "subscription"?
7. **Regulatory:** whether Lemely's hold-and-pay-later model needs its own CBE licence (payment facilitation) or whether Paymob's licensed flow covers it. Needs a lawyer. Also whether credits bought in bundles count as stored value or e-money.
8. **Tax:** tax-file registration, whether Lemely must issue e-receipts to Egyptian consumers, and whether the EDP VAT rule applies to tutor sessions. Needs an accountant.
9. **Apple Pay on a Test account:** live-only integration ID, plus domain verification and certificates. Plan a staged go-live.
10. **Reliability:** budget for a polling reconciliation job (pending orders) and idempotent webhooks from day one; review and chargeback risk on held funds. Paymob UAE terms allow 120-day holds and withholding, so request the Egypt Merchant Application Form to see equivalent clauses.
11. **Support escalation:** reviewers report slow responses. Get a named account manager before committing, and keep a fallback gateway (Kashier is the closest equivalent) in the architecture (payment-provider interface).

### Source index (primary first)
- Paymob docs: payouts overview [2026-07-15], how it works [2026-07-29], disbursement channels (n/d), Cashin API [2026-07-29], auth [2026-07-29]; split features [2026-06-01]; Apple Pay [2026-06-01]; partner onboarding [2026-09-15]; overview [2026-08-03]; convenience fee (n/d).
- Paymob sites: https://paymob.com/en/pricing (n/d), https://paymob.com/llms.txt [2026-04-09], https://www.paymob.com/en/marketplace (n/d), https://paymob.com/click-by-paymob/ (n/d).
- CBE: June 2025 licensing rules PDF; news item 2025-09-01. ETA: 2022-05-23 e-commerce registration notice; 2025-09-25 e-receipt decision 361; digital-services VAT guide (2023).
- Third party: paymentreview.com, Trustpilot, Daliva, remotebuilders.io, samirgeorge.com, wpar.net, motaber.com, dropidea.com, GitHub repos, PyPI.

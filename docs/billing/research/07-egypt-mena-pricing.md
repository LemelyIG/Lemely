# 07 - Egypt/MENA monetization mechanics and price anchors (for Lemely + Paymob)

Research date: 2026-11-02. Scope was changed mid-task: the main subject is HOW Egyptian edtech and digital services collect money (subscription vs prepaid vs per-course, renewal without auto-pay, parent payment, tutoring escrow, vendor billing). Price points are secondary context.

FX used: **1 USD = EGP 55.8** (CBE close 1 Nov 2026: 55.72 buy / 55.86 sell; Banque Misr 55.77/55.87). Sources: https://www.cbe.org.eg/en/economic-research/statistics/exchange-rates (its published table was stale, 7 Oct = 52.4), https://www.banquemisr.com/en/CAPITAL-MARKETS/Exchange-Rates-and-Currencies (1 Nov 2026), https://elfolos.com/dollar-close-sunday-down-25-piasters/ (1 Nov 2026). Context: the CBE raised rates 100 bp on 29 Oct 2026 (deposit 20%, lending 21%), first hike since Mar 2024, "to defend the pound" (same elfolos source). The pound was about 15-16/USD in early 2022 (https://www.globalinvestments.net/expat/international-school-fees-cairo, undated 2026). Treat EGP prices as exposed to another repricing.

Source-quality note: many tutor and school-fee pages are SEO/aggregator content (Smartious, IG Catalog, Tutopiya, Global Investments). Their ranges are marked "low confidence". Official pages (British Council, CBE, ETA, Apple, Google, Orcas, Paymob, Fawry) are high confidence.

---

## 1. Collection mechanics (the main finding)

### 1.1 What Egyptians can actually pay with (rails)

| Fact | Detail | Source (date) |
|---|---|---|
| Wallets | 60M mobile wallets, ~EGP 4 trillion transacted, end-2025; 19M wallet holders are aged 15-35 | https://www.dailynewsegypt.com/2026/04/25/bank-financing-for-msmes-surges-390-over-decade-mobile-wallet-transactions-near-egp-4trn-cbe/ (25 Apr 2026); https://arabfinance.com/en/news/newdetails/cbe-says-egypt-financial-inclusion-rate-grow-in-2025 (23 Apr 2026) |
| Cards | 21.6M prepaid, 19.7M debit, only **4.8M credit** card holders (end-2025). Credit-card penetration estimated 5-10% of population, concentrated in higher income | same Arab Finance; https://ibsintelligence.com/ibsi-news/egypts-card-payments-grow-but-digital-wallets-take-the-lead/ (2 Jan 2026) |
| Account access | 79% of adults 15+ hold a transactional account (Jun 2026), 56.4M adults | https://www.ecofinagency.com/news-finances/0708-58034-egypt-plans-new-financial-inclusion-strategy-focused-on-digital-usage (7 Aug 2026) |
| Foreign-merchant card block | Oct 2023: CBE barred EGP debit cards for foreign-currency spend, restricted credit cards (about $250/month domestic-equivalent limit reported). Cards still work for local merchants in EGP | https://www.reuters.com/markets/currencies/egypt-restricts-foreign-currency-credit-card-use-2023-10-17/ (17 Oct 2023); https://forbesmiddleeast.com/money/banking-finance/egypts-banks-completely-suspend-using-debit-cards-abroad (11 Oct 2023). Entry-tier credit card limits "around EGP 5-6k/month" per https://www.sirapays.com/blog/how-to-pay-netflix-egypt-2026 (24 Aug 2026; vendor blog, low confidence) |
| Apple Pay | Phase 1 launched Dec 2024 (CBE tokenization). Egypt banks listed by Apple on 27 Oct 2026: ADCB, AAIB, Banque Misr, CIB, Emirates NBD, Fawry (yellowcard), KFH, NBE, QNB, Telda. Emirates NBD launch 25 Feb 2026 | https://support.apple.com/en-us/109516 (27 Oct 2026); https://www.cbe.org.eg/en/news-publications/news/2024/12/10/12/56/the-launch-of-payment-cards-tokenization-on-mobile-applications-and-apple-pay-service (12 Dec 2024); https://shore.africa/2026/03/07/apple-pay-launches-egypt-network-international-digital-payments/ (7 Mar 2026) |
| Apple/Google store billing | Apple Egypt: Apple Account balance, Vodafone carrier billing, most credit/debit cards. Google Play Egypt: Visa/MC/Amex plus Vodafone and e& carrier billing; prepaid numbers may not work; Google collects VAT | https://support.apple.com/en-eg/111741 (accessed 2 Nov 2026); https://support.google.com/googleplay/answer/2651410?co=GENIE.CountryCode%3DEG&hl=en (accessed 2 Nov 2026); https://support.google.com/googleplay/android-developer/answer/138000?hl=en |
| Fawry | cash/wallet network, 166k service points, 35M+ users (code paid at outlet or in app) | https://www.ebanx.com/en/insights/articles/what-is-fawry-in-egypt/ (20 Feb 2025) |
| Paymob | Gateway fee **2.75% + EGP 3** per successful card charge (page undated). "Subscriptions" product = monthly recurring via **card tokenization**; wallets, kiosks (Aman/Masary), COD, installments listed as separate non-recurring methods. Paymob processes ~87% of e-wallet volume in Egypt (2023 claim) | https://paymob.com/en/online-payment ; https://paymob.com/en/subscriptions ; https://www.zawya.com/en/press-release/companies-news/paymob-partners-with-shahid-to-expand-vod-digital-payments-an-industry-first-in-egypt-i1ecqzed (Mar 2023) |

Inference (not found stated anywhere): Paymob's recurring product is token-on-card, so wallet and Fawry/Aman payments are one-shot. This matches every local edtech/media flow below. Confirm with Paymob whether any wallet (Vodafone Cash) offers tokenized debit-on-renewal.

### 1.2 How local platforms bill (observed patterns)

| Pattern | Evidence | Source (date) |
|---|---|---|
| **Manual activation keys / codes** (pay, then receive a key) | Abwaab Egypt: payment via (1) WhatsApp support team, (2) Fawry code then upload receipt, then key, (3) Paymob wallet link sent by SMS, user enters wallet number, OTP, PIN, then sends a screenshot, then key, (4) Visa on site, (5) Apple Pay on site, (6) Google Pay in app. Card/Apple/Google Pay activate automatically with no key; wallet/Fawry need manual verification and a key. Subscription "cards" are also reserved via Telegram | https://help.abwaab.com/hc/ar/articles/11926104080402 (11 Feb 2024); https://t.me/abwaab99 |
| **Prepaid fixed-term passes, no auto-renew** | Zatoona AI: EGP 99/month, 249/3 months, 499/school year, one-time InstaPay or Vodafone Cash, "no auto-renewal", 7-day refund if fewer than 10 questions asked, unconfirmed transfer refunded within 24h; app stores sell nothing (website only); iPhone users get a 3-day trial | https://zatoona-ai.com/en (accessed 2 Nov 2026) |
| | EGS AI: EGP 60 (1 mo), 110 (2 mo), 140 (3 mo); "pay by Visa, wallets and InstaPay" | https://www.egsaiedu.com/ (accessed 2 Nov 2026) |
| | Ministry platform Hosas Misr: EGP 100/school year (was 599) payable by Fawry, Visa, Meeza, Orange Cash, Vodafone Cash | https://www.elwatannews.com/news/details/6594272 (25 May 2023) |
| **Wallet/Fawry cannot renew, are non-refundable, no trials** | Abjjad (Arabic e-books, Egypt): "Fawry and e-wallet payment does not support auto-renewal, no trial, non-refundable"; to switch to wallet the user must cancel the auto-renew first; card auto-renew works only with credit (not debit) cards because of the CBE decision; iOS has only Apple billing plus Fawry/wallet under "other payment methods" | https://www.abjjad.com/faq (accessed 2 Nov 2026); https://www.abjjad.com/egypt/payments/ewallets.html |
| **Prepaid voucher as workaround for subscriptions** | Anghami: international card, mobile operator billing, or **prepaid voucher from Fawry**. Shahid: Fawry cash code valid 48h, e-wallet via Paymob, subscription voucher | https://support.anghami.com/hc/en-us/articles/6244628311194 (accessed 2 Nov 2026); https://spartage.com/ (15 Apr 2025, secondary) |
| **Teacher-sold scratch/charge cards and codes** | Snatr (teacher-platform SaaS): teachers print prepaid cards and sell for cash at the centre or bookshops; a code can unlock a course for N months or N sessions, or load balance; "suits students with no card or wallet and parents who prefer to pay cash to someone they know"; Fawry/Aman codes valid 24h; gateway Fawaterak | https://snatr.com/en/features/payments (14 Oct 2026) |
| **Wallet/credit balance inside the platform** | Vedu, Code-UP (charge-balance, codes, 2% fee surcharge on some rails, 0% on InstaPay), Ostazy (charge wallet via Vodafone Cash/InstaPay then book), Shattor (coupons) | https://play.google.com/store/apps/details?hl=es&id=com.vedu.platforms ; https://code-up.tech/payment-methods ; https://ostazy.org/ ; https://shattor.com/en (all accessed 2 Nov 2026) |
| **Parents pay a centre by monthly cycle, partial payments, InstaPay + receipt upload** | Hadereg (centre-management app): monthly or per-session billing, full or partial payment, parent transfers via InstaPay or wallet and uploads the receipt for the owner to confirm; one app for several children; student app activation EGP 75/year (discounted from 200) or EGP 45/term | https://www.hadereg.com/ (accessed 2 Nov 2026) |
| **Auto-renew only where card or store billing exists** | Shattor auto-renews; Snatr's own SaaS: monthly invoice, optional saved-card auto-pay, reminder 2 days before end | shattor.com/en ; snatr.com (above) |
| **Gateway fee sometimes passed to payer** | Snatr: platform commission/gateway fee added on top for students; Code-UP shows a 2% fee line before paying; Classera Egypt parent portal charges EGP 3 for Fawry | https://manual.classera.com/docs/cpay-for-online-payments-egypt/ (accessed 2 Nov 2026) |

### 1.3 How the global services bill in Egypt

| Service | Mechanics | Source (date) |
|---|---|---|
| **Netflix** | Monthly only (no annual, multi-month or lifetime plans), billed on signup date. Egypt list: EGP 110 Basic / 190 Standard / 270 Premium (4 Oct 2026). Pays by card (must allow recurring e-commerce), gift card balance, local partner payments; Fawry has a help page. Because it is a foreign merchant, Egyptian cards hit the cross-border limits. A grey market resells profiles at EGP 100/mo, 500/6 mo, 1,000/yr via Vodafone Cash/InstaPay with screenshot proof, which shows demand for local-rail purchase of foreign subscriptions | https://help.netflix.com/en/node/116380 (accessed 2 Nov 2026); https://www.sirapays.com/blog/how-to-pay-netflix-egypt-2026 (24 Aug 2026); https://elharbystore.com/en/netflix/ (accessed 2 Nov 2026) |
| **Spotify** | Egypt: Individual EGP 79/mo (promo 39 for 6 months), Student EGP 39 after a free month, Duo 109. **Prepaid "pay once, top up, does not auto-renew"** offered on the Egypt page. Mobile carrier billing (Vodafone, Orange) works in practice, with user-reported failures and plan-specific availability. Community: Oct 2023 CBE rule broke card renewals | https://www.spotify.com/eg-en/premium/ (accessed 2 Nov 2026); https://community.spotify.com/t5/Subscriptions/Paying-from-egypt/td-p/5650323 (11 Oct 2023); https://community.spotify.com/t5/Subscriptions/Payment-Fails-After-SMS-Verification/td-p/7002063 (8 Jun 2025) |
| **Shahid** | First SVOD in Egypt with e-wallet payments, via Paymob; Vodafone Cash is the exclusive telco wallet (Mar 2023). Fawry cash code for EGP 20 VIP-Mobile launched Oct 2022. Vodafone ran 30% off 3-month and 1-year bundles when paid by VF Cash (a push toward longer prepaid terms). Shahid VIP EGP 99 / VIP+ 129 (Apr 2026, secondary source, medium-low confidence) | https://www.zawya.com/... (Mar 2023); https://www.fawry.com/2022/10/11/fawry-cooperates-with-shahid-to-offer-digital-payments-for-their-new-vip-mobile-package/ (11 Oct 2022); https://web.vodafone.com.eg/en/vodafone-cash-and-shahid (accessed 2 Nov 2026); https://themiddleeastinsider.com/2026/04/09/shahid-vip-vs-netflix-2026-arabic-content-comparison/ (9 Apr 2026) |
| **ChatGPT Go / Plus** | Egypt price list is **App-Store-billed EGP**: Go EGP 249.99/mo (about $4.48, 3rd cheapest of 41 countries), Plus 999.99, Pro 5,399.99 / 9,999.99. Pays by Egypt-issued card or Apple Pay; Apple/Play gift cards reportedly do not settle Plus; Fawry/Meeza do not pay it; web checkout is cards only; wallet balance exists only for US accounts. Workarounds sold in Egypt: App Store gift cards, virtual USD cards | https://biwu.ai/en/prices/chatgpt-go/egypt (checked 31 Oct 2026); https://subprice.org/en/countries/EG (1 Nov 2026); https://whereischeap.com/in/chatgpt/egypt/ (29 Aug 2026); https://help.openai.com/en/articles/10421635 (accessed 2 Nov 2026); https://help.openai.com/en/articles/20001508 (30 Oct 2026) |
| **Claude Pro, Notion etc.** | Same EGP store tiers: Claude Pro EGP 999.99/mo, 9,999.99/yr (annual = 10 months of price) | https://subprice.org/en/countries/EG (1 Nov 2026) |

### 1.4 Tutor marketplace holding/release, refunds, installments

**Orcas (Egypt's main hybrid tutoring marketplace)**
- Parents buy **prepaid hour bundles** (2, 12, 24, 40, 100 hours; Arabic page shows 2/12/30/60/100), bigger bundles cost less per hour (pricing pages show "save" labels of 10-40%, prices not extractable). Online and in-person tracks. Installment plans are advertised. https://www.orcas.io/pricing/prices (accessed 2 Nov 2026); https://www.orcas.io/en-qa/pricing/prices
- **Payment: online only, credit card or Fawry, paid in advance; no cash.** https://www.orcas.io/User-welcome (accessed 2 Nov 2026)
- **Escrow-like release:** tutor does not get paid until the parent confirms the session (auto-confirms after 3 days); tutors redeem confirmed earnings (even mid-package) to bank account, CIB wallet or cash collected at the Orcas office weekly. https://www.orcas.io/ar-eg/partner-policy (accessed 2 Nov 2026); https://www.orcas.io/Join-tutor
- **Cancellation:** at least 24h notice; paid session cancelled within 3h of start counts as one completed hour (tutor paid up to EGP 200); tutor no-shows are penalized. Parent refund only when Orcas or the tutor cancels; refund goes to the bank account in 5 working days after review. https://www.orcas.io/User-Refund-policy (accessed 2 Nov 2026)
- **Anti-disintermediation is the core revenue defence:** tutors may not take cash or work off-platform; a tutor who does must pay Orcas the service fee, else is blocked after 14 days. Commission is "off each hour sold" (company Gust profile, ~$1M TTM revenue, undated). Orcas uses Baims as technology partner. Fee % not published. https://gust.com/companies/orcas-2
- **Friction signal:** App Store review (undated) complains of 6-8 calls/day after a package ends to force renewal and post-package "extra lessons" billing. Renewal is run by phone sales. https://apps.apple.com/eg/app/orcas-private-tutoring/id1280468626
- Nafham older live-lesson booking: prepaid, paid via Fawry code (2018 post, EGP 280/lesson; a 2022 review says up to EGP 160/subject). Stale. Nafham Premium monthly EGP 49 (nafham.com via subger, checked 16 Mar 2026). https://abukabir.fawrye.com/2018/04/nafham.html ; https://subger.com/de/service/nafham-eg

**Other Egyptian tutor marketplaces**
- Ostazy: tutor wallet topped up by Vodafone Cash/InstaPay/PayPal, "credits" = EGP 1 each, parent portal, tutor prices EGP 150-1,000/hr for IGCSE. https://ostazy.org/ ; https://ostazi.net/en/browse/igcse (accessed 2 Nov 2026)
- Modarby: packages and "full refund guarantee if not satisfied after first session", 540-1,400 EGP. https://www.modarby.com/en/blog/private-tutoring-prices-in-egypt (undated)
- Darasly IGCSE listings, EGP 616-924. https://darasly.com/ig-curriculum/ (2 Nov 2025)

**Global commission norms (for the later tutor marketplace)**

| Platform | Take | Source (date) |
|---|---|---|
| Preply | 100% of trial lesson, then 33% falling to 18% by hours taught | https://help.preply.com/en/articles/4171383 (19 Sep 2024); smartcookieapp.com (30 Oct 2026) |
| italki | trial 0%, single 21%, 5-pack 19%, 10-pack 17%, 15/20-pack 15%, group 30% | https://support.italki.com/hc/en-us/articles/206352068 (accessed 2 Nov 2026) |
| Superprof | 10% only if paid via platform; students pay EUR 29/month pass | smartcookieapp.com (30 Oct 2026) |
| Classgap | 32% falling to 16% | same |
| AmazingTalker | 30% falling to 0% plus 8% fixed, students pay +10% | https://tutornetworking.com/en/tools/teacher-take-home (Sep-Oct 2026) |
| Bassata (Egyptian teacher platform) | 5% per sale | https://snatr.com/guides/best-platform-2026 (14 Oct 2026) |

Implication: Orcas-style prepaid bundles with confirmed-session release are the local norm; per-hour commission and a hard off-platform ban, enforced with prepayment, is how local marketplaces defend revenue. Teacher SaaS in Egypt sells flat monthly subscriptions (Snatr EGP 999/1,999/2,999 per month by student cap; Teachers EG from 600; Smart Center from 500).

---

## 2. Subscription vs credits vs per-course (what the evidence says)

| Model | Where it works in Egypt | Where it fails |
|---|---|---|
| Auto-renew subscription | Cards with tokenization (credit cards: only 4.8M holders), Apple/Google store billing, carrier billing | Wallet and Fawry users (the majority of the 79% with accounts); debit cards on foreign merchants |
| Prepaid fixed term (1/3/12 months) | The default for local edtech: Zatoona, EGS AI, Hosas Misr, Abjjad via wallet, Spotify prepaid, Vodafone/Shahid bundles. Longer terms are discounted (Zatoona 99 monthly vs 83/mo on 3 months vs 42/mo school year) | needs a manual renewal nudge and churn between terms |
| Prepaid hour/credit bundles | Orcas (bundles with volume discounts), Examiner AI (credit bundles, no expiry, no monthly fee), tutor2u | needs a rule for expiry and refunds |
| Per-course / per-term one-off | Abwaab (EGP 499-1,799 per grade-term package), Noon Academy in-app bundles (EGP 350-450 science mega-bundle) | one-off, no recurring revenue |
| Scratch card / code sold offline | Teacher-run centres (Snatr, Abwaab cards), Hadereg activation EGP 45/term | requires a distribution partner, no direct brand relationship |

Abwaab Egypt price points (App Store, undated): Prep 1/2 EGP 499.99, Secondary 1 EGP 899.99-999.99, Secondary 3 EGP 1,799.99; website bundles EGP 1,700-1,749 for secondary-level full-year packs (https://apps.apple.com/eg/app/abwaab/id1623367993 ; https://abwaabegypt.com/, accessed 2 Nov 2026).

---

## 3. Price anchors (brief context)

USD at 55.8.

### 3.1 Consumer digital price points in Egypt (store/list prices)

| Item | EGP/month | USD | Source (date) |
|---|---|---|---|
| ChatGPT Go (App Store) | 249.99 | 4.48 | biwu.ai (31 Oct 2026) |
| ChatGPT Plus / Claude Pro | 999.99 | 17.92 | subprice.org (1 Nov 2026) |
| Google AI Plus / Pro | 449.99 / 939.99 | 8.06 / 16.85 | subprice.org (1 Nov 2026) |
| Netflix Basic/Standard/Premium | 110 / 190 / 270 | 1.97 / 3.41 / 4.84 | sirapays (4 Oct 2026) |
| Spotify Individual | 79 | 1.42 | spotify.com/eg-en (2 Nov 2026) |
| YouTube Premium | 114.99 | 2.06 | subprice.org (1 Nov 2026) |
| Duolingo Super / Quizlet Plus / Gauth Plus | 64.99 / 499.99 / 179.99 | 1.16 / 8.96 / 3.23 | subpriced.com/country/egypt (1 Nov 2026) |
| Shahid VIP / VIP+ | 99 / 129 | 1.77 / 2.31 | themiddleeastinsider (Apr 2026, secondary) |
| Almentor | about USD 7.5 (2023); 30% promos; EGP 550/yr during a Banque Misr card offer | - | https://www.wearetech.africa/... (Feb 2023); firstbankeg.com (Feb 2023) |

Egypt is among the cheapest storefronts for AI subscriptions (ChatGPT Go 3rd of 41 at 44% below US), but Plus/Pro are priced near US parity (EGP 999.99), so the IGCSE-family segment already pays near-USD prices for premium AI.

### 3.2 Egyptian edtech and AI study apps (local ceilings)

| Product | Price | Notes | Source |
|---|---|---|---|
| Zatoona AI | EGP 99/mo, 249/3 mo, 499/yr (USD 1.77 / 4.46 / 8.94) | national curriculum, prepaid only | zatoona-ai.com/en |
| EGS AI | EGP 60/110/140 for 1/2/3 months (USD 1.08 / 1.97 / 2.51) | AI grading of generated exams | egsaiedu.com |
| Zaky AI | EGP 0 / 75 / 120 per month; "a semester for less than one private lesson (EGP 500)" | https://www.zaky-ai.com/pricing |
| Nafham Premium | EGP 49/mo | via subger, 16 Mar 2026 | https://subger.com/de/service/nafham-eg |
| Abwaab | EGP 500-1,800 per grade package | see above | |
| Noon Academy Egypt IAP | EGP 350-450 science bundles; large Saudi exam camps up to EGP 19,999 | https://apptail.io/app/noon-academy-uNT/egypt (accessed 2 Nov 2026) |
| Educatly | EGP 999/3 months, 2,499/yr | https://www.educatly.com/plans |
| Kai AI (GPT wrapper) | EGP 249.99/week, 999.99/yr | App Store EG (undated) |
| Orcas AI TA, Winny AI, imthan.com | free or free-tier | https://akta.pro/company-profiles/0000vcv/orcas ; winny-ai.com/en-EG |

No Egypt-specific AI exam-marking product for IGCSE/Cambridge found. Nearest comparable overseas: **Examiner AI (tutor2u)**: credit bundles GBP 5-100 (250 to 25,000 credits), no subscription, no expiry, each answer max 10 credits, typical GBP 0.03-0.10 per marked answer (about EGP 3-9); 100 free credits on signup (https://ai.tutor2u.net/ ; https://kinescope.com/edtech-map/tutor2u, 16 Oct 2026; linkedin post 12 Feb 2025). Closest local analogue is EGS AI's generated-and-graded exams at EGP 60-140/month, aimed at national-curriculum students.

### 3.3 IGCSE tutoring prices in Egypt (2026)

| Item | EGP | USD | Confidence / source |
|---|---|---|---|
| Online IGCSE tutor from | 450/hr | 8.06 | Eduremo, network of 1,800+ tutors (https://eduremo.com/en/program/igcse, 2026 term dates) |
| STO Education Cairo | 350-450/hr, bundle discounts at 8+ lessons, invoiced in EGP | 6.3-8.1 | https://www.sto-education.com/tutoring/egypt/cairo |
| Ostazi marketplace, first page | 150-1,000/hr (median about 350) | 2.7-17.9 | https://ostazi.net/en/browse/igcse (accessed 2 Nov 2026) |
| IG-COLOGY tutors | 250-400/session; group 250-350; course 7,000 | - | https://ig-cology.com/private-courses/ (undated) |
| Orcas (not published) | n/a | - | |
| Local IGCSE tutor range, general guides | 200-800/session; 500-1,200/hr | - | low confidence: theigcatalog.com (9 Jun 2026), smartioushomeschool.com (2026) |
| Thanaweya Amma parent quote | EGP 250+ per session; EGP 100k spent on lessons | - | https://www.vetogate.com/5685761 (2 Jul 2026) |
| Group centre packages | 800-2,500 per course | - | low confidence, smartious |
| Family tutoring budget | EGP 3-8k/month middle class; 10-25k/month upper-middle IGCSE | 54-143 / 179-448 | low confidence, smartious (2026) |
| Tutoring share of household education spend | 28.3% of the school-spend budget (2024); education CPI +20% y/y (Jul 2026); intl schools raised fees 30-40% for 2026/27 | - | https://enterpriseam.com/egypt/2026/08/21/... (21 Aug 2026) |

### 3.4 IGCSE exam entry fees and school fees (what the target family already spends)

| Item | EGP | USD | Source (date) |
|---|---|---|---|
| Cambridge IGCSE, one subject, Oct-Nov 2026 (British Council Egypt) | 7,860 (math/science single/ESL) to 11,990 (sciences), 10,960 (math 0580, business), 13,840 (languages); late fee 13-17k | 141-248 | https://www.britishcouncil.org.eg/en/exam/igcse-school/register/registration-dates-fees (price-list PDF); https://www.scribd.com/document/1071353734/ (Oct-Nov 2026 list) |
| Cambridge IGCSE May-Jun 2026 | Biology/Chem/Physics 10,805; Maths and most subjects 9,850; languages 12,525 | 177-224 | https://www.nrcschools.com/latest-news/ignews/Cambridge.pdf (2026 list) |
| Edexcel IGCSE May-Jun 2026 | 9,110 typical; 7,010-11,400; sciences double 16,110; late 16,110 | 126-289 | https://www.britishcouncil.org.eg/sites/default/files/pearson_edexcel_egypt_price_list_may-_june_2026.pdf |
| Edexcel IAL unit, Oct-Nov 2026 | 4,790 (science units) to 6,410 | 86-115 | https://www.britishcouncil.org.eg/sites/default/files/pearson_edexcel-eg-ial-price-list-oct-nov-26.pdf |
| A candidate with 5-7 IGCSE entries | about EGP 45k-85k | 800-1,500 | computed |
| International school tuition, 43 EGP-quoted schools | EGP 45k-405k/yr, median midpoint about 153.5k | 0.8k-7.3k | https://internationalschools.net/countries/egypt/fees (2025-26/2026-27) |
| ElMasareef 2026/27 examples | Hayah 186-220k; Nefertari IGCSE 75-200k; GEMS 165-247k | - | https://elmasareef.com/en/schools/type/international |
| Edarabia grade-level fees (Y10/Y11) | e.g. BICC 121k, Nefertari Brit 146.75k, El Alsson 234k, Metropolitan 205-210k | - | https://www.edarabia.com/cairo-school-fees/ (2026) |
| Premium tier quoting in USD/GBP | CAC USD 15.98k-30.46k; BISC GBP 6.4-16.8k; NCBIS GBP 8.1-14.8k | - | internationalschools.net |
| Low-confidence outlier | Tutopiya quotes EGP 180k-1.1M "primary/secondary" which conflicts with the official/aggregate data above; ignore | - | https://www.tutopiya.com/blog/international-school-fees/... |
| Parent testimonial (British school EGP 140-255k tuition, spends ~EGP 200k/yr on private lessons) | - | - | https://egyptianstreets.com/2024/09/12/school-tuition-fees-in-egypt-are-straining-families-amid-economic-challenges/ (12 Sep 2024) |

### 3.5 VAT and taxes

- Egypt VAT 14% general rate; remote digital services supplied by non-residents to Egyptian consumers are taxable at 14%; app stores (EDPs) collect it (Apple has done so since July 2023, Google collects Egypt VAT). Source: https://www.eta.gov.eg/sites/default/files/2023-03/digital-service-guide-english.pdf ; https://www.pwc.co.za/en/publications/vat-in-africa-ess/egypt-overview.html ; https://developer.apple.com/news/?id=9o2nwe38 (10 Jul 2023); https://support.google.com/googleplay/android-developer/answer/138000
- Resident providers must register at annual revenue of EGP 500,000; Deloitte lists "health and education services" among 58 VAT exemptions. Whether an AI marking service counts as exempt education is unclear (ask a tax advisor). https://www.deloitte.com/content/dam/assets-shared/docs/services/tax/2026/dttl-tax-egypthighlights-2026.pdf (2026)
- Unknown whether store list prices (e.g. EGP 249.99) are VAT-inclusive; treat as inclusive.

---

## 4. Price anchoring for Lemely (concise)

Reference frame: one IGCSE tutor hour is EGP 350-450 (online, ~$6-8); one exam entry is EGP 8-12k; a streaming month is EGP 100-190; ChatGPT Go EGP 250; local AI study apps for the national curriculum EGP 60-140/month (a lower-income segment); Examiner AI costs about GBP 0.03-0.10 (EGP 3-9) per marked answer. If marking COGS is about USD 0.10 per paper (about EGP 5.6), then EGP 12-20 per paper keeps 55-70% gross margin after Paymob's 2.75% + EGP 3.

### Credit bundle (primary product: prepaid, wallet/Fawry/card/Apple Pay all work)

| Pack | EGP | USD | Implied per paper | Why |
|---|---|---|---|---|
| Try | 99 | 1.77 | ~EGP 20 (5 papers) | impulse buy below any monthly sub, fee burden ~6% |
| Standard | 299 | 5.36 | ~EGP 15 (20 papers) | under ChatGPT Go; two exam-prep sessions of marking |
| Exam season | 799 | 14.3 | ~EGP 13 (60 papers) | about two tutor hours; sold before May/Jun and Oct/Nov series |
| Family / teacher | 1,999 | 35.8 | ~EGP 10 (200 papers) | 1/5 of one exam entry; matches Snatr teacher-SaaS tier (EGP 999-2,999/mo) |

Rules: 12-month expiry (not "no expiry", which Examiner AI uses but hurts renewal), free 100-credit-equivalent trial for new users (free tier norm: Zatoona 2/day, Zaky free tier, Examiner AI 100 credits).

### Monthly / term subscription (secondary product)

| Plan | EGP | USD | Notes |
|---|---|---|---|
| Student monthly | 199-299 (suggest 249) | 3.6-5.4 | at ChatGPT Go parity; stay under EGP 350-450 (one tutor hour) |
| 3-month term pass | 599-699 | 10.7-12.5 | 20-25% discount, prepaid, no auto-renew; the wallet/Fawry default |
| School-year / exam-season pass | 1,499 | 26.9 | Zatoona sells a year at ~5x monthly; Abwaab 500-1,800 per grade |
| Family (up to 3 children) | 399-499 | 7.2-8.9 | mirrors Orcas multi-learner bundles |
| Teacher / classroom | 999-1,999 | 17.9-35.8 | flat monthly like Egyptian teacher SaaS; verify teachers' WTP, thinly evidenced |

Floor and ceiling logic: floor about EGP 99/month (the national-curriculum AI apps; below this the IGCSE segment reads it as low quality and fees eat margin); ceiling about EGP 449/month (one tutor hour; above it you compete with a human). The target family spends EGP 150-400k/yr on tuition and tutoring is the largest line, so WTP is not the binding constraint, payment mechanics are.

### Mechanics recommendations (derived from section 1)

1. Lead with prepaid term passes and credit packs; treat auto-renew as an add-on available only to card users (Paymob tokenization) and Apple/Google billing. Cards are held by about 7% of adults (4.8M credit); 60M wallets cannot renew automatically.
2. Support the full Paymob menu: card, wallet (Vodafone Cash/others), Fawry/Aman code, Apple Pay (live at CIB, NBE, Banque Misr, AAIB, QNB, KFH, Emirates NBD, ADCB, Telda), InstaPay. Because Paymob is a domestic merchant, EGP debit cards should work (unlike foreign merchants since Oct 2023); this is inferred and should be confirmed with Paymob.
3. Wallet/Fawry flows: show a 24-48h code expiry (Fawry 24h, Shahid 48h), auto-activate on webhook (no manual key; Abwaab's key/screenshot flow is the anti-pattern), mark them non-refundable or short-refund-window (Abjjad non-refundable; Zatoona 7 days if under 10 uses).
4. Renewal nudge for prepaid: WhatsApp/SMS with a Paymob payment link 3-7 days before expiry (Snatr reminder at 2 days), exam-calendar reminders before May/Jun and Oct/Nov. Avoid Orcas-style aggressive phone-call renewal (named complaint).
5. Parent pays, student uses: one family account with child profiles; the payer view gets receipts; Hadereg shows parents already expect one login for multiple children and receipts.
6. Tutor marketplace (later): copy Orcas's mechanics, not its tone: prepaid hours, release on confirmed session (auto-confirm 3 days), cancellation 24h/3h rule, refund only if tutor cancels, platform-only payments. Commission norms 15-33%; Orcas does not publish its fee.
7. If selling on iOS/Android stores instead of Paymob, store EGP tiers apply (Egypt storefront prices are near USD parity for premium tiers) and store fees plus VAT collection apply; debit cards are blocked on store billing per Abjjad (undated, medium confidence). Carrier billing exists via Vodafone (Apple) and Vodafone/e& (Google).

### Gaps and uncertainty

- No published fee for Orcas, no per-hour price for Orcas bundles extractable, no first-party IGCSE tutor price survey; tutor prices come from marketplace listings and SEO guides.
- No evidence found of an AI exam-marking product sold in Egypt for IGCSE; Zatoona/EGS AI/Zaky/Winny target the Egyptian national curriculum.
- Wallet-tokenized recurring billing in Egypt unverified.
- Conflicting claims: Snatr withdrawal hold 3 days (Arabic page) vs 7 days (English page), same 14 Oct 2026 date; Orcas Arabic vs English bundle sizes (30/60 vs 24/40 hours); Netflix Standard EGP 190 vs ~200 vs 120 across sources (Netflix-help-based 110/190/270 used).
- Tutor and exam-fee pages dated by the pages' own price lists; the British Council "price list" PDFs were read via search extracts, not fully downloaded.

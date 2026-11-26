# Frontier AI pricing mechanics: what Lemely should copy and avoid

Research date: 2026-11-02. Every source was fetched live on 2026-11-01/02 unless marked otherwise. Per the scope change, this document emphasises HOW pricing works (metering, limits, overage, credit ordering, expiry, refunds, cost UX). Prices are brief context only.

Evidence grades: **[official]** = vendor docs or help center fetched live. **[3rd-party]** = price trackers or press. Where only 3rd-party data exists, it is flagged.

Access limits during research: openai.com/chatgpt/pricing, Midjourney, ElevenLabs help and Runway help pages returned HTTP 403 to the direct fetcher. I read them via a search mirror, which returned the vendors' own text. Anything not verifiable is marked.

---

## 0. Executive summary (the 10 things that matter)

1. **Every frontier vendor has converged on "subscription with included usage, then pay-as-you-go at API rates, prepaid, opt-in, with a spend cap".** Claude (usage credits), ChatGPT (Codex/Work credits), Cursor (prepaid top-ups), Perplexity (Computer credits), ElevenLabs (PAYG top-up), Runway, Lovable, Replit, v0 all do this. Postpaid overage (ElevenLabs "usage based billing") is being retired for self-serve in favour of prepaid.
2. **Included usage is a time-boxed allowance, not a balance.** Claude: rolling 5h session plus weekly cap, both reset in full, nothing rolls over. Gemini: 5h plus weekly. Cursor and SuperGrok: weekly pool. Midjourney: monthly "Fast hours". Purchased top-ups are a separate bucket with its own (longer) expiry. Lemely's signup grant and bundles map to the "purchased" bucket, not to the allowance bucket.
3. **Spend order is nearly universal: allowance first, then bonus/rollover (soonest-expiring first), then purchased.** Runway: monthly, then rollover, then purchased. Gamma: plan, purchased, workspace. Lovable: soonest-expiring general credits first. Replit: pack that expires earliest first. ElevenLabs: subscription, then PAYG. Bolt: oldest bucket first (FIFO).
4. **Expiry norms for purchased credit: 12 months is the modal value** (Anthropic API, OpenAI API, ChatGPT Business, ElevenLabs PAYG, Lovable top-ups, v0). Outliers: Replit packs 6 months, Midjourney extra Fast time 60 days, Runway purchased credits never expire, Gamma purchased credits do not expire while the plan is active. Purchased credit is non-refundable almost everywhere.
5. **Reserve-then-settle exists but is rarely marketed.** OpenAI documents that a task can start with positive balance and push it negative, with later top-ups offsetting the negative. Manus deducts each action's cost at the start of the next action, so balances go negative. OpenAI Enterprise: overage limit 0 blocks new requests, but in-flight requests finish and settle. Lovable shows live cost-so-far and pauses at a "credit check-in" threshold (20 credits default). Replit asks for confirmation before a paid action. Gamma shows image-model credit cost before generating. **Nobody shows an exact pre-quote for agentic work; they show a rate card, a typical range, and a live meter.**
6. **Refund-on-failure is explicit only at the "technical failure" level.** Anthropic API: failed requests are not charged (but a disconnected request that was on track to succeed IS charged). Gamma: no charge on error or clarifying question; charge on any completed action "even if the result isn't exactly what you wanted". Lovable: a request stopped before any change is not charged; stopped Build requests are charged for work done. Manus: full refund for platform-caused failure, none for "subjective dissatisfaction" or agent loops. This is the single biggest trust gap in the market.
7. **Backlash always comes from opacity or a silent switch, not from the price level.** Cursor June 2025 (request-based to API-rate credit pool, "unlimited" meant Auto only) forced a public apology and refunds. Manus 2026 (credits burn 2-7x faster after migration, agent-mode work unrefundable). Lesson: communicate unit changes with notice, a visible meter, and a default hard cap.
8. **Regional pricing is real but patchy, and Egypt is a favoured market.** ChatGPT Go in Egypt is EGP 249.99 per month (App Store, collected 2026-10-29), 44% below the US $8, third-cheapest of 39 storefronts. Gemini has Egyptian EGP prices (AI Plus 249.99 on Google's own page) and a free-AI-Plus-for-students deal with the Egyptian MCIT. Claude Pro is EGP 999.99 (about $17.84, only -11% vs US) so Anthropic gives little purchasing-power discount.
9. **Free-for-students is now a Gemini-led land grab in Egypt.** Google AI Plus is free for 12 months to Egyptian university students until 2026-12-31 (Cairo Portal, 2026-10-13). Lemely's student users have a free general-purpose AI tool at hand. Lemely's value must be paper-specific marking and not "chat".
10. **Users hate, in rank order:** (a) unexplained credit burn, (b) a unit change without notice, (c) expiry of money already paid, (d) no spend cap by default or a cap that fails (negative balances), (e) paying for failed or looping runs.

---

## 1. Anthropic Claude (consumer, team, API)

### 1.1 Plan structure (context only) [official, fetched 2026-11-02, claude.com/pricing]

| Plan | Price | Included usage | Notes |
|---|---|---|---|
| Free | $0 | "Limited usage every 5 hours and every week" | |
| Pro | $17/mo annual ($200 up front), $20 monthly | "At least 5x Free per 5-hour session" | Fable available but paid via usage credits |
| Max | $100/mo (monthly billing only) | 5x Pro every 5h and every week | Fable up to 50% of weekly limit; $100/mo API credits |
| Ultra | $200/mo (monthly only) | 10x Pro weekly, no 5h limit for verified accounts | $200/mo API credits |
| Team | Standard seat $20 annual / $25 monthly; Premium $100 annual / $125 monthly | Standard more than Pro; Premium 5x Standard | Up to $500/mo pooled API credits |
| Enterprise | Annual only; seat-based or usage-based | Usage-based enterprise bills on consumption | Volume and committed-spend discounts, not published |
| Education | University-wide plan "at discounted rates" | Dedicated API credits | No individual student discount: Pro help article says "We don't offer standard discounted pricing for individual plans" (support.claude.com/en/articles/8325606, fetched 2026-11-02) |

### 1.2 How usage is measured and enforced [official: support.claude.com/en/articles/11647753, fetched 2026-11-02]

- **Two meters on paid plans:** a session limit and weekly limits.
- **Session limit:** "The period starts when you send your first message, and your limit resets in full five hours later." This is a rolling window anchored on first use, not a clock-aligned one.
- **Weekly limits:** "reset at a fixed time each week that is assigned to your account... regardless of when you start using Claude or when your subscription begins." Applies across all models. Max and Ultra also have a separate Fable weekly limit.
- **Measurement is cost-weighted, not message-count.** "Your usage is affected by... the length and complexity of your conversations, the features you use, which Claude model you're chatting with, and the effort level you've selected." The pricing FAQ says: "there's no fixed message count." All surfaces (claude.ai, Claude Code, Desktop) draw one pool.
- **Visibility:** Settings > Usage shows current-session usage and time remaining, plus the weekly reset time. The product shows an "approaching your limit" notice, and after credits kick in, "Now using credits".
- **Capacity discretion:** "we may limit your usage in other ways, such as weekly and monthly caps or model and feature usage, at our discretion." (claude.com/pricing FAQ, 2026-11-02.)
- **User-controllable cost levers are documented**: lower effort level, extended thinking off, fewer tools and connectors, shorter project instructions.

### 1.3 What happens at the limit [official: support.claude.com/en/articles/12429409, fetched 2026-11-02]

Options at the limit: wait for reset, move up a plan, or (paid plans) **usage credits**.

- Usage credits are the opt-in overage: "once one of your included limits is fully used (any five-hour session limit or one of your weekly limits), your requests switch to pay-as-you-go pricing on usage credits and keep working." Billed at standard API rates.
- **Prepaid, not postpaid.** "You'll then need to prepay... Click 'Add funds.'" Optional **auto-reload** below a threshold. A **monthly spend cap** is configurable ("Adjust limit"), or "Set to unlimited."
- **Usage alerts** when approaching spend limits.
- Credits are "charged separately from your paid Claude subscription and appear as additional charges on your bill."
- If you subscribed via the mobile app, usage credits can only be enabled on the web. This is a store-billing workaround worth noting: IAP cannot easily handle metered overage.
- Monthly API credits that come with Max, Ultra and Team are a different bucket: "unused credits expire at the end of each billing cycle", spent before purchased credits, and cannot be used in Claude apps or for extra usage (support.claude.com/en/articles/8977456, 2026-11-02).
- Note the Egypt App Store listing shows "Usage Credits" IAP SKUs (EGP 999.99 for the 20-unit SKU, up to EGP 39,999.99 for 1000 units) [3rd-party, apppricelens.com via search, 2026-11]. The help article says mobile subscribers must buy on web, so treat the store SKU list with caution.

### 1.4 Subscription mechanics [official: claude.com/pricing FAQ, 2026-11-02]

- **Upgrade:** immediate; unused time on the old plan is credited toward the new one. Excess is stored as account credit and auto-applied to future purchases.
- **Downgrade:** effective at the end of the current billing period; chats and files remain.
- **Monthly to annual:** remaining time credited to the first annual invoice.
- **Annual discount:** Pro $17 vs $20 (15%). Annual is for Pro and Team only; Max and Ultra are monthly only.
- **Pause:** no pause feature documented in the sources I fetched.

### 1.5 API: prepaid credits [official: support.claude.com/en/articles/8977456 and platform.claude.com/docs/en/api/rate-limits, 2026-11-02]

- **Prepaid usage credits** cover API, Workbench/playground and Claude Code.
- **Expiry:** "Credits expire one year from the purchase date, and the expiration date can't be extended." **Non-refundable.**
- **Failed requests are not charged.** "If your client disconnects or times out in the middle of a request that was on track to succeed, that request is still charged."
- **Auto-reload:** "When credit balance reaches X" and "Bring credit balance back up to Y." If you are already below the threshold when you switch it on, you are charged immediately.
- **Run out:** "you can no longer call the API... until you add more." No negative balance model documented.
- **Tiers:** Start / Build / Scale / Custom, with monthly spend caps $500 / $1,000 / $200,000 / none. Your own limit can be set lower; at your own limit requests return HTTP 400 `invalid_request_error` with a message saying when access resumes.
- **Rate limits are token-bucket**, with cache-aware input counting (cached reads don't count toward ITPM for most models). OTPM counts actual tokens generated; `max_tokens` is not counted. This is the reservation-free design.
- **Batch:** 50% discount. Sonnet 5 listed at $2 in / $10 out per MTok, cache read $0.20 (claude.com/pricing, 2026-11-02).

### 1.6 Regional (Egypt)

- App Store Egypt: Pro EGP 999.99/mo, Pro annual EGP 9,999.99, Max EGP 6,999.99, Ultra EGP 12,999.99 [3rd-party, apppricelens/aipriceatlas, price since 2026-10-11].
- aipriceatlas ranks Egypt #2 cheapest of 166 storefronts, but only -11% vs US $20. So **Anthropic localises currency, not purchasing power.**

---

## 2. OpenAI (ChatGPT and API)

### 2.1 Plan structure [official, fetched 2026-11-02]

| Plan | Price | Mechanics |
|---|---|---|
| Free | $0 | "Unlimited text chats with GPT-5.6 Luna" (subject to abuse guardrails), limited uploads/images |
| Go | $8 US; EGP 249.99 Egypt | Unlimited text chats too; higher limits on tools. "All purchases are in USD - we offer local currency billing in a limited set of countries", though the App Store lists local prices. May show ads. Go is "available in all countries ChatGPT is supported in" (help.openai.com/en/articles/11989085) |
| Plus | $20 | Expanded limits; EGP 999.99 on App Store (about $17.85) |
| Pro | $100 (5x Plus) or $200 (20x Plus) | Two tiers, same capabilities, differing allowance |
| Business | Per-seat, with shared workspace credits | |
| Enterprise / Edu | Contract-level shared credit pool | |

- **No annual billing** for Go/Plus/Pro: "we do not support annual billing or the option to pay for multiple months in advance."
- **Student offer:** US-only 4 free months of Plus, claim by 2026-10-31 (now expired). Egypt gets nothing from OpenAI here [official: help.openai.com/en/articles/20001493].

### 2.2 Limits and what happens at the limit

- Included limits are per-feature, per-model allowances. "When you reach a model's allowance, that model may be temporarily unavailable until the allowance resets. ChatGPT displays the reset time." "There is no setting to increase or bypass a model's usage allowance." Support cannot reset limits (help.openai.com/en/articles/9793128).
- **Soft fallback:** use another model.
- **Credits for Plus/Pro/Go (new):** "Credits extend usage for supported features after included plan limits are reached." Currently Codex, ChatGPT Work and ChatGPT for Excel only. "Your plan's included usage is used first. After you hit plan limits, usage draws from your credit balance." Sold from Settings > Usage, with auto-reload ("purchase only the amount needed to return it to your selected target balance"). On Free/Go, credit purchase is only available to "a limited group" (help.openai.com/en/articles/12642688, 2026-11).
- **Reserve-then-settle in practice:** "If a task starts while your balance is positive but finishes after concurrent usage depletes it, your balance can go negative. In that case, later credit purchases or automatic reloads may first offset the negative balance." That is OpenAI documenting optimistic start plus settle-after.
- **Wallet is separate from credits.** Gift-card wallet in USD is not usage credits, which avoids dual-use confusion.

### 2.3 Business / Enterprise / Edu credit mechanics [official: help.openai.com/en/articles/11487671, 11481834, 20001001]

- Rate card is explicit: credits per message (e.g. Sol 10, Sol Pro 50, Instant unlimited) or token formula: `credits = in/1M x in_rate + cached/1M x cached_rate + out/1M x out_rate`. "Actual credit usage varies based on model, task complexity, input size, cached input, output length, automations, and fast mode." Rate card for Excel: a typical task is "5 to 20 credits per message".
- Higher reasoning effort does NOT change the per-message credit rate on Sol (10 credits), which is the "flat price per tier" simplification.
- Business credits "valid for 12 months after purchase".
- At the limit: Business sees a banner; with no pool credits "the feature is blocked and users can ask a workspace owner to add more". Enterprise/Edu: "advanced features will be paused unless Workspace Owners enable overages".
- **Overage settle detail:** "A limit of 0 blocks new requests, but requests already in progress may finish and settle afterward, leaving a small negative balance." Overage is invoiced after the period, with a five-business-day review window.
- Two independent caps: per-user limit and workspace spend cap; raising one does not raise the other.

### 2.4 API [official: help.openai.com/en/articles/8264644, developers.openai.com rate-limits, 2026-11]

- Prepaid since new accounts. Minimum purchase $5, default $10. **Purchased credits expire after 1 year**, non-refundable except billing error, unauthorised activity, or confirmed OpenAI service failure.
- Auto-recharge **on by default during setup**, with threshold, target and optional monthly recharge cap. Min recharge $5. Max balance and recharge size bounded by trust tier.
- **Negative balance:** "API access may not stop immediately after your credits run out. Usage processed during this delay can appear as a negative credit balance... deducted from your next credit purchase. Do not rely on the prepaid balance as an instantaneous spending cutoff."
- Free credits are consumed before purchased credits.
- Tiers now Build ($5 cumulative purchases, $500/mo), Launch ($100, $5,000/mo), Grow ($500, $200,000/mo). Tier is earned by lifetime purchases.
- Batch -50%. GPT-5.6 Sol $5 / $30 per 1M tokens (openai.com/api/pricing, 2026-11).

### 2.5 Egypt

- ChatGPT Go EGP 249.99 per month, VAT-inclusive 14% (apppricelens, scraped 2026-11-01), rank 3 of 39 (geosub, 2026-10-29). Plus EGP 999.99.
- **Go is a deliberate purchasing-power product** (launched India Aug 2025, global 2026-01-16 per a 3rd-party summary). It is ad-supported in places. Lesson: a low-cost tier is how OpenAI addresses EM markets, and it is paid via the App Store at local prices.

---

## 3. Google, Microsoft, Perplexity, xAI

### 3.1 Google Gemini [official: gemini.google/subscriptions, one.google.com, support.google.com/gemini/answer/16275805, 2026-11]

- **Limits mechanics (closest analogue to Claude):** "compute-based usage limits... factor in the complexity of your prompt, the models and features you use, and the length of your chat. Your limit refreshes every 5 hours until you reach your weekly limit." Plans scale as multipliers: Plus 2x, Pro 4x, Ultra 5x or 20x vs Pro.
- **At the limit:** subscribers "can continue your conversation with Flash-Lite" (graceful model downgrade), or wait, or upgrade. Heavy features (Deep Research, media) "consume more of your usage". Notifies "when you're close" and gives the reset time. No PAYG overage in the app. Limits "may change without notice".
- **Separate credit sub-currencies:** Google Flow Credits (Plus 200/mo, Pro 1,000, Ultra 10k/25k), Colab compute units, Cloud credits.
- **Egypt (official Google page, 2026-11):** AI Plus EGP 249.99/mo, AI Pro EGP 939.99, Ultra 5x EGP 2,199.99, Ultra 20x EGP 8,799.99. Lower tiers (Lite 41.99, Basic 94.99, Standard 144.99) exist for storage-led plans. Ultra 20x at EGP 8,799.99 versus US $199.99 is roughly 3% to 4% of nominal parity, which shows real localisation.
- **Students:** AI Plus free 12 months for eligible students in 140+ markets outside the US (Google blog, 2026-08-19); Egypt MCIT partnership: free AI Plus for one year for university students, register until 2026-12-31, "valued at approximately EGP 3,000"; up to 75% off AI Pro; 70% off Pro+YouTube Premium bundle (Cairo Portal, 2026-10-13). Egypt is on the supported-student-country list (support.google.com/googleone/answer/17422238).

### 3.2 Microsoft [official: support.microsoft.com ai-credits-and-limits, Oct 2026; microsoft.com/copilot/pricing]

- Two metering types coexist: **feature limits** (N uses per period) and **AI credits** (monthly allotment spent as you go across apps). "If you reach a feature limit or use all of your AI credits, that feature may be unavailable until your allowance resets." Credits visible in the Microsoft account. AI benefits are "only available to the subscription owner and cannot be shared."
- Tiers: Personal, Family, Premium, Pro with qualitative labels (Standard, More, Extensive, Highest usage) rather than numbers. Copilot Pro was $20 (legacy). Free trial one month. No overage purchase found.
- Takeaway: Microsoft deliberately avoids publishing quantities, and users complain about opacity [no source fetched for complaints; judgement].

### 3.3 Perplexity [official: perplexity.ai/help-center articles 11187416, 13838041, 11680686; 2026-11]

- Pro $17/mo billed annually; Max $200/mo or $2,000/yr (annual web only). Education Pro for verified students (about $10/mo via SheerID per the help text).
- **Pro: weekly limits** on Pro Search "(average use)", monthly on research. **Max: extended limits.** Free: 3 Pro Searches/day.
- **Perplexity Computer credits: the cleanest published credit definition in the set.** "100 credits equals $1". "A quick fact or definition uses about 15 to 70 credits." Typical range by task type is published. Paid Pro includes a weekly amount of Computer usage first; included usage resets weekly from first use, does not roll over, "cannot be purchased, transferred, or refunded". Max includes 10,000 credits/mo. New-subscriber bonus credits "expire in about 30 days", one per account, do not repeat on resubscribe.
- **Auto-refill triggers** at 500 credits (Pro) and 2,500 (Max), off by default. **Spending cap:** every Max account has a monthly cap, default **$200**, adjustable to $5,000; Pro also has one. "If you hit the cap: Active tasks pause... No more charges until you update settings."
- Egypt: Perplexity Pro EGP 999.99 on the App Store (subprice.org, 2026-11). No local-income discount.

### 3.4 xAI / SuperGrok [official: x.ai/pricing, 2026-11; subprice.org]

- Tiers Free / Plus $8 / Premium $30 / Super $100 / Ultra $200, with shared pool "refreshes weekly, so one heavy day never wipes out your whole month". At limit: "keep going with top-ups, or wait." Third-party models in Cursor are billed separately. Egypt App Store: SuperGrok Lite EGP 499.99, SuperGrok EGP 1,499.99, Heavy EGP 14,999.99 [3rd-party].

---

## 4. Credit-explicit AI products (mechanics comparison)

| Product | Unit | Allowance reset / rollover | Purchased credit expiry | Spend order | Cost UX before/after | Failure / refund | Spend cap |
|---|---|---|---|---|---|---|---|
| **Lovable** | credit ($0.25/credit on Pro, $0.50 on Business) | Monthly credits roll over; expire 2 months after issue (monthly plan), 1 month after annual period ends. Daily chat allowance and daily build credits expire end of day. | Top-ups 12 months. Referral credits 12 months. | Usage-specific grants first, then soonest-expiring general credits | "Credits used" per message in a menu; live cost while running; pause with "Continue" at a **credit check-in level (20 credits default)** | Request stopped before any change is not charged; stopped Build charged for work done | Caps per member, project, workspace plus threshold alerts (paid plans) |
| **Replit** | credit; "effort-based pricing" per checkpoint | Core monthly; Pro credits roll 2 months | Credit packs 6 months, no rollover, no renewal | Earliest-expiring pack first; limits apply after packs | Cost shown per checkpoint (hover); "Replit asks for confirmation before a paid action starts"; Plan Mode and Free Mode as cheap on-ramps | Free one-time checkpoints for all subscribers; no general refund policy found | Budgets are hard caps; alerts; set $0.01 to stay within packs only |
| **Cursor** | USD-denominated pool at API list price | Weekly pool (2026 X Subscription); legacy plans two monthly pools plus on-demand | Prepaid credit with auto top-up | Pool first, then prepaid credit | Dashboard shows approaching limits; "Requests are never downgraded in quality or speed" | n/a | Spending caps |
| **Bolt** | tokens | Paid: roll over, valid 2 months; free 1M/month plus 300K daily, no rollover | n/a in fetched page | FIFO oldest bucket first | Token meter in My Subscription | n/a | Daily cap on free |
| **v0** | USD credit | Monthly rolls over, expires after 65 days | Purchased credits last until 1 year but need active paid plan; remain after subscription lapses | Monthly first | "When credits are used up, generation pauses" | n/a | Pause at zero (hard stop) |
| **Midjourney** | GPU minutes ("Fast hours") | Fast time resets monthly, **does not carry over**; Relax = unlimited queued | Extra Fast time $4/hr, 60-day expiry, needs active sub, non-refundable | Fast time | Published approximate GPU cost per job type (SD prompt 0.8 min, HD 1.3, video batch 8 to 26 min); `/info` shows remaining | n/a | Relax mode is the graceful "slow lane" rather than a block |
| **Runway** | credit ($0.01 each for purchased) | Monthly credits expire on billing date; Max rolls up to 1 month; Free 125 one-time | Purchased credits never expire (min purchase 1,000 credits / $10) | Monthly, then rollover, then purchased | Rate card per second (Gen-4.5 12 credits per second, so 60 for 5s) shown on pricing page | n/a | Team auto-refill |
| **ElevenLabs** | credit | Monthly; up to 2 months' worth rolls over while subscribed; cancel/downgrade forfeits | PAYG 12 months; PAYG balance carries into subscription | Subscription first, then PAYG | Cost per 1,000 extra credits shown before enabling | n/a | Self-set threshold; legacy postpaid billed immediately if over 2x fee |
| **Suno** | credits | Paid replenish monthly to a fixed amount; **"paid subscriptions still have expiring credits"**; free 50/day | n/a | n/a | n/a | n/a | n/a |
| **Gamma** | credit per slide + image | Plan credits monthly; free credits do not refresh | Purchased: never expire while plan active, no cap | Plan, then purchased, then workspace | **Image model credit cost shown before generation**; API returns `credits.deducted` and `remaining` | "Not charged when an AI action fails, shows an error, or asks a clarifying question" but charged on completion even if unsatisfying | Auto-recharge recommended |
| **Manus** | credit per task, by "complexity and duration" | Monthly refresh, negative balance auto-resolves on refresh | Add-on credits can expire; deleted-account remainder refunded in 7 days | n/a | Cost deducted at start of the next action, so balances go negative; "you will not be able to start new tasks while credits are at or below zero" | Full refund only for verified platform bug; none for loops, "subjective dissatisfaction" or "hitting task limits" | n/a |
| **Notion AI** (new, from 2026-11-02 for existing workspaces) | Standard / Select / Notion credits | Standard 1,500 and Select 500 per member per month, **no rollover** | Notion credits: $10 per 1,000 monthly (reset), $13 per 1,000 annual (expire at renewal) | Free, monthly, then annual | **Published "estimated credits per task" table**: simple 5 (Auto) vs 50 (Opus 5.5); medium 10 vs 85; complex 25 vs 150 | n/a | "impacted work will pause until credits reset" |
| **Canva** | not researched in depth | | | | | | Canva Pro EGP 119.99/mo on Egypt App Store [3rd-party] |

Sources (all fetched 2026-11-01/02): docs.lovable.dev/introduction/plans-and-credits; docs.replit.com/billing/ai-billing and /managing-spend; cursor.com/docs/account/pricing and cursor.com/blog/june-2025-pricing (2025-07-04); support.bolt.new/account/tokens; v0.build/docs/pricing; docs.midjourney.com articles 27870484040333, 32016412137741, 33570952624141; help.runwayml.com articles 15124877443219, 23987639973267; elevenlabs.io/docs/overview/administration/billing and /pay-as-you-go; help.suno.com 2524993 and 2418177; help.gamma.app article 7834324 and developers.gamma.app access-and-pricing; help.manus.im 11711097 and 12992237; notion.com/help/manage-your-ai-credits (2026-11).

### 4.1 Cursor backlash, June to July 2025 (case study) [official + press]

- 2025-06-16: Pro moved from "500 fast requests then unlimited slow" to "$20 of usage at API rates", with "unlimited" only for Auto. Users ran out in days on Claude models; some were surprise-billed because spend limit was not set by default. One team reported burning a $7,000 annual plan in a day (ainews.com, 2025-07-07; headline claim from social posts, unverified).
- 2025-07-04: public apology, "Our communication was not clear enough," refunds for unexpected usage 2025-06-16 to 2025-07-04, clearer dashboard alerts, advance notice promised (cursor.com/blog/june-2025-pricing; TechCrunch 2025-07-07).
- Cursor's own explanation of the switch: "the hardest requests cost an order of magnitude more than simple ones. API-based pricing is the best way to reflect that." Same logic Lemely faces with long or messy scans.
- 2026 status: Cursor now bundles into "The X Subscription" with a weekly pool (Plus $8 to Ultra $200), third-party models at API list price from prepaid credit, and "Requests are never downgraded in quality or speed" (cursor.com/docs/account/pricing, 2026-11-02).

### 4.2 Manus credit revolt, 2026 (case study) [3rd-party press, Sonar Mag 2026-10-25; official help 2026-09-30]

- Complaints: same work burning 2-3x (and in some posts 7x) more credits after a platform migration; agent-mode work unrefundable while task mode was refundable; loops spending thousands of credits; partial refunds too small to retry.
- Manus' own mechanic: deducts each action's cost at the start of the next, so a task can overshoot the balance. This is exactly an after-the-fact settlement with no hard stop mid-action.
- Caveat: this is a press piece compiling Reddit posts. Treat quantities as anecdotal.

---

## 5. Regional and purchasing-power pricing

| Vendor | Egypt-specific price? (all collected Oct-Nov 2026) | Low-cost tier? | Purchasing-power discount vs US? |
|---|---|---|---|
| OpenAI ChatGPT | Yes, App Store EGP: Go 249.99, Plus 999.99, Plus annual 9,999.99 (apppricelens 2026-11-01) | **Go** ($8 US, EGP 249.99 Egypt) | Go: -44%. Plus: about -11% ($17.85 vs $19.99). Billing is USD by default on web, local currency in "a limited set of countries" |
| Anthropic Claude | Yes, App Store EGP: Pro 999.99, annual 9,999.99, Max 6,999.99, Ultra 12,999.99 | None | About -11% on Pro only |
| Google Gemini | Yes, Google pages: AI Plus 249.99, Pro 939.99, Ultra 2,199.99 / 8,799.99 | **AI Plus** ($4.99 US) | Pro -15% (linyan.org); Ultra 20x far lower than US |
| Perplexity | App Store EGP 999.99 for Pro | none | about parity |
| xAI SuperGrok | App Store EGP 499.99 / 1,499.99 / 14,999.99 | SuperGrok Lite | near parity [3rd-party] |
| Canva Pro | EGP 119.99 | | about $2.52 vs $15 US: strongly localised [3rd-party, subprice.org 2026-11] |
| Notion Plus | EGP 599.99 | | about parity |

Key facts for Lemely:
- **EGP price points end in .99 and are VAT-inclusive (14%)** on the App Store. Prices are quoted in round-hundreds EGP with a ".99" or ".49".
- **A "Go-style" cheap tier is how the leaders handle Egypt.** The price of ChatGPT Go in Egypt (about EGP 250) is a useful anchor for what Egyptian parents already compare against.
- Anthropic and Perplexity charge EGP 1,000 for chat access. That is the "premium AI tool" reference price, so a paper-marking product priced at a fraction of that per month is easy to justify.
- subprice.org shows the Egypt storefront rate used at 1 USD = EGP 47.6 (2026-11); apppricelens implied ~56 EGP/USD for ChatGPT Go. Treat FX as moving.

---

## 6. Cross-cutting patterns

### 6.1 Models of "subscription + usage"

| Model | Examples | Strength | Weakness |
|---|---|---|---|
| Subscription with allowance (time-boxed), hard stop or downgrade at limit | Claude, Gemini, ChatGPT included limits, Perplexity Pro, Midjourney Fast hours | Predictable bill, simple story | "Use it or lose it" resentment; opaque meter |
| Allowance plus opt-in prepaid overage (usage credits) | Claude usage credits, ChatGPT Codex credits, Cursor, Perplexity credits, ElevenLabs PAYG | Heavy users never hit a wall | Needs auto-reload and caps UI; IAP mismatch |
| Pure prepaid credits with expiry | Anthropic/OpenAI API, v0, Runway purchased, Lovable top-ups | Matches real cost, no subscription churn | Expiry resentment; payment friction for small tickets |
| Hybrid: recurring credits that roll over a limited window | Lovable (2 months), Bolt (2 months), ElevenLabs (2 months), v0 (65 days), Replit Pro (2 months) | Softens "use it or lose it" without unbounded liability | Complex to explain; needs bucket breakdown UI |

### 6.2 What happens at the limit (menu)

1. **Hard block until reset** (Notion, v0 at zero, Perplexity at cap, Anthropic API at spend limit).
2. **Graceful downgrade** (Gemini to Flash-Lite; Midjourney Relax mode; ChatGPT use another model). Cursor says explicitly it does NOT downgrade.
3. **Opt-in switch to metered billing** (Claude usage credits, ChatGPT credits).
4. **Pause and ask** (Lovable check-in at 20 credits; Replit confirmation; Perplexity "active tasks pause" at cap).

### 6.3 How reserve-then-settle is actually communicated

- Nobody publishes "we reserved X, settled Y". They show: (1) **rate card** (Runway credits per second, Midjourney GPU minutes, OpenAI rate card, Perplexity 100 credits = $1), (2) **typical ranges** (Perplexity 15-70 credits for a quick fact; OpenAI Excel 5-20 per message; Notion 5/10/25 by complexity), (3) **a live meter** (Lovable cost-so-far, Replit per-checkpoint hover, Anthropic Settings > Usage), and (4) **a per-item receipt** (Lovable "Credits used", Gamma API `credits.deducted`).
- Settlement edge case handling in the wild: allow negative balance (OpenAI, Manus), block new starts only (OpenAI "limit of 0"), or charge on stop for partial work (Lovable).
- **Failure rules that actually appear in docs:** no charge for errors or clarifying questions (Gamma); no charge if stopped before any change (Lovable); full refund for platform-caused task failure (Manus); disconnects still charged (Anthropic API).

### 6.4 Credit ordering and expiry (summary rules seen in the wild)

- Spend grants that expire soonest first (Lovable, Replit, Bolt FIFO, Runway monthly-before-purchased, Notion free-monthly-annual).
- Separate bucket types shown in a balance breakdown with expiry dates (Lovable credit balance dialog and History tab, 12 months of history).
- Purchased credits last longer than subscription credits, and almost always at least 12 months (6 months is the shortest seen for packs, 60 days for Midjourney extras).
- Cancel or downgrade forfeits unused subscription credits at period end (ElevenLabs, Bolt, Runway "if you've cancelled, your balance resets to 0").
- Promo credits are the shortest-lived (Perplexity bonus about 30 days; one per account).

### 6.5 Subscription lifecycle norms

- Upgrades immediate and prorated; downgrades at period end (Claude, Runway, ChatGPT Pro, ElevenLabs). Bolt: upgrade keeps billing cycle, charges difference, grants token difference immediately.
- Annual discounts: Midjourney 20%, Claude Pro about 15%, Runway 20%, Cursor roughly 17% ($80 vs $8x12=$96 for Plus). OpenAI offers none.
- Cancellation: access until period end (all). Lovable and Bolt: lose access to allocated tokens at cycle end; Bolt lets you regain unexpired rollover tokens if you resubscribe in time.
- Pause: none found in these sources.

### 6.6 What users hate (evidence)

| Complaint | Evidence |
|---|---|
| Unexplained credit burn | Manus Reddit revolt (Sonar Mag 2026-10-25); Cursor June 2025 |
| Silent unit change | Cursor 2025: apology and refunds; "Our communication was not clear enough" |
| "Unlimited" that isn't | Cursor: unlimited only in Auto; OpenAI now writes "Unlimited... subject to abuse guardrails" everywhere |
| Expiry of paid-for credit | Suno: "paid subscriptions still have expiring credits" page exists because users ask; Midjourney Fast time lapses; Manus add-ons |
| No default spend cap | Cursor 2025 surprise bills; Perplexity now defaults Max to $200 cap; OpenAI auto-recharge default-on at setup is the opposite |
| Pay for failed or looping runs | Manus; Anthropic API charges disconnected-but-succeeding requests |
| Negative balances | OpenAI, Manus (documented but surprising) |

---

## 7. Lessons for Lemely (opinionated, concrete)

**Context.** Lemely's marginal cost per paper is bounded (target at or below $0.10), the buyer is often a parent paying for a child, and the market is Egypt (EGP, VAT-inclusive, wallet and card payment, App Store optional). Competitors in the buyer's head: ChatGPT Go at EGP 249.99, Gemini AI Plus at EGP 249.99 (free for university students), Claude/Perplexity at EGP 999.99.

### 7.1 Structure: lead with prepaid bundles, add one cheap subscription, skip pay-as-you-go postpaid

1. **Bundles of marking credits as the primary SKU** (6 or 12-month expiry, see 7.3). Parents buy "N papers" before an exam season; there is no ongoing value between seasons, so a subscription alone punishes seasonal use. This matches how v0, Runway, Lovable top-ups and the API vendors sell.
2. **One subscription tier**, priced in the ChatGPT-Go range (EGP 200 to 300), that bundles a fixed number of "paper-equivalents" per month plus a roll-over of 2 months (Lovable, Bolt, ElevenLabs, Replit Pro all use exactly 2 months; v0 uses 65 days). Rolling over 2 months converts "use it or lose it" into a defendable cap on liability: at most 3 months of paper-equivalents outstanding.
3. **Never postpaid overage.** ElevenLabs is retiring it for self-serve; Cursor's 2025 surprise bills came from spend-without-cap. Lemely has an easy way out: when the allowance is gone, show "Add credits" and use the prepaid path (Claude, ChatGPT, Perplexity all pattern this).
4. **Teachers/schools: pooled credits** with per-user limit plus workspace cap that apply independently (OpenAI Business/Enterprise pattern; Notion, Runway Team, v0 Plus).

### 7.2 Metering unit: price the credit in "paper-equivalents", settle at actual LLM cost

- **Define 1 credit = a fixed EGP value (like Perplexity's 100 credits = $1, Lovable $0.25/credit),** not "1 paper". A paper's actual cost varies by page count, handwriting, scheme complexity. A credit denominated in money lets the reserve-then-settle logic work without exposing token math.
- **Publish a rate card plus typical range, not a per-paper quote.** Pattern: Perplexity "15 to 70 credits for a quick fact", Notion "simple 5 / medium 10 / complex 25". For Lemely: "a typical 2-hour paper uses about N credits; a messy 30-page scan can use up to M." Show before the user presses mark.
- **Reserve the estimate, hold it, settle at actual, release the delta.** Do the OpenAI-style "start allowed if balance positive" only up to a **hard reserve cap**: allow settlement to exceed the reserve by at most a small tolerance (for example 20%), and **absorb any further overrun yourself** (cap the charge at reserve x 1.2). Manus and OpenAI both leave users with negative balances, and in Manus' case with rage. Lemely controls the pipeline, so an overrun is a Lemely problem, not a user problem.
- **Show settlement, not just deduction.** A per-paper receipt ("Estimated 14, charged 11, 3 returned") is the Lovable "Credits used" and Gamma `credits.deducted/remaining` pattern and the best antidote to the Manus complaints. Return the delta immediately and visibly.
- **Add a "check-in" threshold for long jobs** (Lovable 20 credits default). For batch teacher uploads: confirm when a batch estimate exceeds a threshold, with a "Continue" and an "adjust" option.
- **Flatten what the user cannot control.** OpenAI charges the same 10 credits per message regardless of reasoning effort, so effort is not a user-facing price dial. Do the same: the model/effort ladder is Lemely's choice (Claude Haiku default marking), not a per-paper price tier. Offer at most one user choice (for example "fast marking" vs "careful re-mark") and price each as a fixed multiplier.

### 7.3 Expiry, ordering, rollover (copy the market norms)

| Bucket | Recommended rule | Precedent |
|---|---|---|
| Signup grant | One-time, **expires in 30 to 60 days**, one per verified account (phone-verified), not recurring, not renewed on resubscribe | Perplexity bonus (about 30 days, one per account); v0 one-time $5 |
| Subscription credits | Monthly, roll over up to 2 months, forfeited on cancel | Lovable, Bolt, ElevenLabs, Replit Pro |
| Purchased bundle credits | **12 months**, non-refundable once spent, **refundable unused if cancelled within 7 to 14 days** (consumer law angle in Egypt; confirm with counsel) | Anthropic, OpenAI, ElevenLabs PAYG, Lovable top-ups all 12 months |
| Referral/bonus | 12 months or shorter, shown in the breakdown | Lovable referral credits |

- **Spend order: signup grant, then subscription (soonest-expiring first), then purchased.** Universal precedent; protects the user's purchased money and minimises forfeits.
- **Show a bucket breakdown with an expiry date per bucket** and a history tab (Lovable credit-balance dialog; 12 months of history).
- **Email at 30 days and 7 days before expiry.** None of the sources documents expiry reminders, so doing it is a differentiator. Treat this as my recommendation, not market practice.
- **Never let purchased credit die because a subscription lapsed** (Gamma: purchased credits never expire "while your plan is active" is the wrong lesson; v0 requires an active plan to use purchased credits, a common complaint pattern). Prefer Runway's "purchased credits never expire when unused" or at least a clean 12 months with no plan dependency.

### 7.4 Failure, refund, and trust rules (the biggest differentiator)

- **Auto-refund on any pipeline failure the user did not cause** (timeout, parse failure, gate failure, unreadable scan flagged by Lemely's own checks). Do not require a ticket (Manus makes users prove it via an AI reviewer, which is the antipattern).
- **Charge for completed, delivered marking even if the user disagrees with the marks.** Gamma and Manus both state this. But give a **free re-mark or review request path** (Lemely's own accuracy gates make this a strength; use it as the dissatisfaction valve).
- **Charge zero for pre-flight rejects** (wrong paper code, blank pages, unreadable file) before the model runs. Lovable's "stopped before any change is not charged" is the precedent.
- **Partial work charged proportionally** if a batch is cancelled (Lovable: "charged based on the work completed so far").

### 7.5 Cost communication UX (checklist)

1. Pre-action: "About X credits (EGP Y)" and a range. Show before the upload is submitted.
2. During: progress and a running count for batches.
3. After: receipt with estimate, actual, delta returned.
4. Balance: always visible, with soonest expiry highlighted.
5. Defaults: **spend cap on by default**, **auto-reload off by default** (Perplexity pattern; OpenAI API's default-on auto-recharge is the opposite and creates support load).
6. One plain-language page explaining credits, with the rate card (Runway, OpenAI, Perplexity precedent).

### 7.6 Pricing level and Egypt

- **Anchor to the ChatGPT Go and Gemini AI Plus price (both EGP 249.99)** for a monthly plan, not to the EGP 999.99 of Claude/Perplexity. A parent comparing "AI for my child" will use those anchors.
- **Price bundles in round EGP with the .99 or round-hundred convention and VAT-inclusive display.** App Store EGP points end in .99 and are VAT-inclusive (14%).
- **Quote per-paper EGP, not USD.** Lemely's cost target ($0.10 per paper) is roughly EGP 5 to 5.6 at current FX (47.6 to 56 EGP/USD range seen in sources, FX moves), so a gross-margin floor should be set on the EGP price points with an FX buffer.
- **Seasonal pricing logic:** promote bundles before IGCSE/A-level exam windows. Subscription is for teachers and heavy users.
- **Beware the student giveaway.** Google gives Egyptian university students free AI Plus until 2026-12-31 (and 75% off Pro). Competition is "general chat", so the pitch is "marks to the mark scheme, with examiner-style feedback", not "AI help".
- **Card and wallet payment is the real constraint**, not the price (Paymob context). Cards can fail on foreign-currency AI apps; Egyptian local payment rails are an advantage Lemely can use. (The EverTry guide titled "How to Pay for ChatGPT in Egypt: Methods That Actually Work" is itself a signal; I did not fetch it, judgement only.)

### 7.7 Anti-patterns to avoid (each is a cited failure)

1. Changing the unit or meter without notice and advance warning (Cursor 2025).
2. Calling something "unlimited" that isn't (Cursor Auto; OpenAI's footnote).
3. Postpaid overage without a default cap (Cursor 2025 surprise bills).
4. Negative balances that block the user (OpenAI API, Manus).
5. Opaque credit burn on agentic work with no refund path (Manus).
6. Requiring a ticket and a reviewer to get refunds for platform failures (Manus).
7. Purchased credit that depends on an active plan (v0).

---

## 8. Open items and caveats

- **Not verified from official sources:** Claude and ChatGPT Egypt prices come from App Store scrapers (apppricelens.com, aipriceatlas.com, subprice.org, geosub.org). Egypt Google prices come from Google's own pages. Re-check in-app before using in any Lemely document.
- **Not found:** whether Anthropic or OpenAI send expiry reminder emails; any consumer "pause subscription" feature for Claude/ChatGPT; Canva AI credit mechanics (not researched); Midjourney, ElevenLabs and Runway help pages returned 403 to direct fetch and were read via search excerpts of the same pages.
- **Third-party summaries conflicted** on ChatGPT Pro tiers (some listed $500). The OpenAI help center (fetched live) states Pro $100 (5x) and $200 (20x) only; I used that.
- **Dates:** model names in 2026 sources (GPT-5.6 Sol/Terra/Luna, Gemini 4 Argon, Claude Fable/Opus 5.5) are as printed on vendor pages fetched 2026-11-01/02.
- **The user-comment evidence** for Cursor and Manus is anecdotal press and forum compilation, not telemetry.

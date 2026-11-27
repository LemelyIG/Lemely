# Paymob billing, Phase 08: frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Executor for every task: the `designer` agent, with the `impeccable` skill invoked** (project
> rule: all UI work goes to designer + impeccable). Each task below fixes behaviour, states
> (loading / empty / error / 402 / blocked / debt), data contracts, copy, accessibility and tests,
> and gives component code that follows existing patterns. Visual polish inside the design system
> (`DESIGN.md`, `PRODUCT.md`) is the designer's job: the designer may restyle markup and classes
> but must keep every behaviour, state, string, `aria-*`/role and `data-testid` the task's tests
> assert.

**Goal:** Ship every billing surface in `web/`: plans and checkout, checkout return, billing
settings for student, parent and teacher, usage meter, credit balance, pre-action estimate range
with 402 handling at every metered entry point, usage history, receipts, auto top-up, teacher
seats and assistants, and the platform-admin billing dashboard.

**Architecture:** One typed data layer (`web/src/lib/billingTypes.ts` plus fetchers and
react-query hooks) is written first and is the only place API shapes live, so it can be
reconciled against the real Phase 02–07 DTOs before any screen is built. Shared billing
components live in `web/src/components/billing/`; shared billing screens live in a new
`web/src/portals/billing/` folder (the same "shared portal" role `web/src/portals/settings/`
plays) and are mounted by the student, teacher and parent route trees. Admin billing lives in
`web/src/portals/admin/screens/billing/` under one `/platform/billing` nav entry.

**Tech Stack:** React 19, Vite, TypeScript, Tailwind v4 (Material 3 role tokens), react-router 7,
@tanstack/react-query 5, `@phosphor-icons/react`, vitest (`environment: "node"`, no jsdom: screens
are tested by `renderToStaticMarkup` from `react-dom/server`, as
`web/tests/unit/adminTutoring.test.ts` does), Playwright e2e (local only; CI has no e2e job).

## Global Constraints

- Work only in `/home/sico/Code/Lemely/.claude/worktrees/paymob-integration` on branch
  `feat/paymob-integration`. Never `cd` into `/home/sico/Code/Lemely` itself.
- Every task is executed by the `designer` agent with the `impeccable` skill invoked.
- Signed commits only, path-scoped: `git commit -S -m "feat(web): …" -- <paths>`. Scope `feat(web):`
  (tests in the same commit). Do not push. Do not open PRs.
- Before each commit, from the worktree root:
  `/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files` and fix every failure. Then
  `graphify update .` (repo CLAUDE.md rule after code changes).
- Never run the full suite (`npm test` bare, `make test`). Run only the test files the task
  touches **plus the source-scanning set** below, because those tests walk `web/src` and a new
  file can fail them (PR #310 failed exactly this way):
  `SCAN="tests/unit/a11yRules.test.ts tests/unit/adaptRules.test.ts tests/unit/celebration.test.ts tests/unit/chartTheme.test.ts tests/unit/contrastRules.test.ts tests/unit/darkConsumers.test.ts tests/unit/design-tokens.test.ts tests/unit/elevationScale.test.ts tests/unit/failureCopy.test.ts tests/unit/hoverTransition.test.ts tests/unit/motionDefaults.test.ts tests/unit/nativeMechanics.test.ts tests/unit/noHardcodedReferenceData.test.ts tests/unit/rtlSafety.test.ts tests/unit/screenEntrance.test.ts"`
- **Frontend gate** (derived from `.github/workflows/ci.yml` job `web`; run from `web/`, all must
  pass before commit): `npm run typecheck` · `npx vitest run <touched tests> $SCAN` ·
  `npm run lint` (oxlint + `check:native`) · `npm run check:copy` · `npm run build` (its
  `postbuild` runs `check:bundle`) · `npm run check:installable` (last task only, and any task
  that touches `routes.tsx`).
- Test files are typechecked (`tsconfig.test.json` is a `tsc -b` reference). Fake hook results
  (`okQuery`, `fakeMutation`) go through untyped `vi.mock` factories; a fake passed straight
  into a component prop is cast `as never`. Render helpers take `Partial<Props>` overrides,
  never `Record<string, unknown>`.
- Static markup escapes apostrophes (`&#x27;`), so test assertions match text fragments that
  avoid them; dates in assertions come from `formatBillingDate(...)` (the runner's locale) or
  pass an explicit locale to the pure function under test.
- Playwright specs (`web/e2e/*.spec.ts`) run locally only, against the real backend and the
  seeded local Supabase stack (`npx playwright test e2e/<file>`). If `supabase status` fails,
  record "e2e not run: local stack down" in the task report; never claim it passed.
- Copy rules (`scripts/check_copy.mjs`): no em dash (U+2014) in UI strings; no exclamation marks;
  en dash only for ranges ("3–5 credits"). Never say "cram", "hack", "easy A", "guaranteed".
- Design rules (`DESIGN.md`): Material 3 role classes only, never raw colours. Crimson (`error`)
  only for genuine errors, never for "plan used up" or debt. Gold (`tertiary`) never on billing:
  nothing here is earned. No Binny on billing surfaces. Money, credits, percentages and codes in
  JetBrains Mono / tabular figures (`text-data-md`, `text-data-sm`). Bricolage never below 28px.
  Typography classes that exist (`web/src/index.css`): `text-display-{lg,md,sm,xs}`,
  `text-body-{lg,md,sm}`, `text-label`, `text-eyebrow`, `text-data-{lg,md,sm}`. There is no
  `text-title`/`text-body`/`text-data`; a page `<h1>` uses `text-display-md`, a card heading
  `text-display-sm`.
  Logical properties only (`ms-`, `pe-`, `text-start`), never left/right.
- Accessibility: WCAG AA. Every progress meter has an accessible name. Every dialog has a
  heading. Status changes the user waits on (payment confirming, plan changed) are announced
  through `role="status"` (polite); blocking failures through `role="alert"`.
- Money is integer minor units (piasters) on the wire; format with `formatMoney`. Usage is
  integer units, shown to users only as "credits" or as a percentage of a plan, never raw units
  for allowances (allowance sizes are hidden, spec §2.1).
- No fallback values passed to `request()` anywhere in billing code (`useAdminApi.ts` header: a
  failed money read must never render as a plausible empty one).
- Never read Paymob secrets in the browser. The browser only ever receives `checkoutUrl`
  (public key + client secret, built server-side) and navigates to it.
- No placeholder code: no `TODO`, no `test.skip`/`.only`, no stub tests, no unimplemented
  branches.

## API assumptions

**Source of truth (index R3):** the backend phase plans 02–07 own every path and shape; this
plan matches them. Every route is under `/api` (index R1). The web client already prefixes it:
`request()` in `web/src/lib/api.ts` sends `fetch(\`${BASE}${path}\`)` with `BASE = "/api"`, so
fetchers pass paths **without** `/api` (`request("/billing/catalogue")` → `/api/billing/catalogue`).
DTOs are camelCase (`ApiModel`).

`web/src/lib/billingTypes.ts` holds two layers (Task 1):

1. **Wire DTOs** (`Wire…` types): field-for-field copies of the backend Pydantic models named in
   the table below. Fetchers return these.
2. **View types** (unprefixed: `PlanTier`, `BillingSummary`, `TeamView`, …): what components
   consume. Pure adapters in `web/src/lib/billingAdapters.ts` turn wire DTOs into view types
   (renames such as `planTierId → id`, `credits → units`, `monthly → month`, nested meters).
   Screens never read a wire type, so a backend rename is a change to one wire type and one
   adapter.

| # | Method and path (client path, `/api` added by `request`) | Request (backend model) | Response (backend model) | Phase |
|---|---|---|---|---|
| A1 | `GET /billing/catalogue` (auth: any billing party; returns every audience, filtered client-side) | — | `CatalogueDTO {planTiers: PlanTierDTO[], creditPacks: CreditPackDTO[]}`; `PlanTierDTO {planTierId, code, name, priceMinor, currency, interval: "monthly"\|"yearly"\|null, audience, includedSeats: int, extraSeatPriceMinor: int, features: dict}`; `CreditPackDTO {creditPackId, code, name, credits, priceMinor, currency}` | 02 |
| A1b | `GET /billing/public-catalogue?audience=student\|teacher` (no auth; 422 bad audience; 429 with `Retry-After`) | — | `PublicCatalogueDTO {audience, planTiers: [{code, name, audience, interval\|null, priceMinor, currency, features, includedSeats\|null, extraSeatPriceMinor\|null}], creditPacks: [{code, name, units, priceMinor, currency}]}` (no ids) | 02 |
| A2 | `POST /billing/subscriptions/checkout` (201) | `SubscriptionCheckoutRequestDTO {planTierId, beneficiaryId?, extraSeats=0}` | `SubscriptionCheckoutDTO {subscriptionId, paymentId, checkoutUrl}` | 05 |
| A3 | `POST /billing/checkout/pack` (201) | `PackCheckoutRequest {creditPackId, beneficiaryId?}` | `CheckoutDTO {paymentId, checkoutUrl}` | 02 |
| A4 | `GET /billing/payments/{payment_id}` | — | `PaymentStatusDTO {paymentId, status, purpose, amountMinor, currency, description, paidAt}` | 02 |
| A5 | `GET /billing/summary?beneficiaryId=` (R3, plan 05 Task 13) | — | `BillingSummaryDTO {beneficiary {userId, displayName, audience}, subscription: SubscriptionViewDTO {subscriptionId, status, tier: PlanTierDTO (02), currentPeriodStart, currentPeriodEnd, cancelAtPeriodEnd, pendingTier: PlanTierDTO\|null, graceUntil, extraSeats, pendingExtraSeats} \| null, canManage, managedByName, savedCard {cardId, maskedPan, brand\|null} \| null, usage {fraction, resetsAt}, credits {totalUnits, expiring: [{units, expiresAt}]}, debtUnits, seats {capacity, used} \| null}`. A parent must name a linked child (422 without, 403 unlinked). | 05 |
| A6 | `GET /billing/subscriptions` | — | `SubscriptionListDTO {subscriptions: SubscriptionDTO[]}`; `SubscriptionDTO {id, beneficiaryUserId, isPayer, planTierId, planCode, planName, status, currentPeriodStart, currentPeriodEnd, graceUntil, cancelAtPeriodEnd, pendingPlanTierId, extraSeats}` | 05 |
| A7 | `POST /billing/subscriptions/{id}/upgrade/quote` (new, R3) | `UpgradeRequest {planTierId}` | `ChargeQuoteDTO {amountMinor, currency, allowanceUnits (upgrade only, else null), periodEnd}` | 06 |
| A8 | `POST /billing/subscriptions/{id}/upgrade` (202) | `UpgradeRequest {planTierId}` | `ChargeDTO {paymentId, status, amountMinor, currency}` | 06 |
| A9 | `POST /billing/subscriptions/{id}/downgrade` | `DowngradeRequestDTO {planTierId}` | `SubscriptionDTO` | 05 |
| A10 | `POST /billing/subscriptions/{id}/cancel` | — | `SubscriptionDTO` | 05 |
| A11 | `GET /billing/receipts` | — | `ReceiptListDTO {receipts: ReceiptDTO[]}`; `ReceiptDTO {paymentId, purpose, description, amountMinor, currency, status, paidAt, beneficiaryId}` | 02 |
| A12 | `GET /billing/auto-topup?beneficiaryId=` / `PUT /billing/auto-topup` | `AutoTopupRequest {beneficiaryId?, enabled, thresholdUnits>0, creditPackId, savedCardId?, monthlyCapMinor>=0}` | `AutoTopupDTO {beneficiaryId, enabled, thresholdUnits\|null, creditPackId\|null, savedCardId\|null, monthlyCapMinor\|null, spentThisMonthMinor, currency, disabledReason\|null}`; "not set up" = `enabled: false`, nulls, `currency: "EGP"` | 06 |
| A13 | `GET /billing/cards` (R3) | — | `SavedCardList {cards: [SavedCardView {cardId, maskedPan, brand}]}` (`brand` `""` when Paymob sent none) | 02 |
| A14 | `POST /billing/subscriptions/{id}/seats/quote` (R3) | `ExtraSeatsRequest {seats}` | `ChargeQuoteDTO` (`allowanceUnits: null`) | 06 |
| A15 | `POST /billing/subscriptions/{id}/seats` (202) | `ExtraSeatsRequest {seats}` | `ChargeDTO` | 06 |
| A16 | `PUT /billing/subscriptions/{id}/seats/pending` | `SeatReductionRequest {extraSeats}` (the new **total**, not a delta) | `SeatsDTO {extraSeats, pendingExtraSeats}` | 06 |
| A17 | `POST /usage/estimate` | `EstimateRequestDTO {action, paperId?, attemptId?, questionResultId?, assignmentId?, subjectCode?, count?}` | `EstimateDTO {low, high, payer: "seat"\|"allowance"\|"credits"\|"none", percentLow, percentHigh, blockedReason}` | 04 |
| A18 | `GET /usage/meter` (caller only) | — | `UsageMeterDTO {allowanceFraction, allowanceResetsAt, creditsBalance, creditLots: [{remaining, expiresAt}], seats: [{teacherMemberId, teacherUserId, fraction, resetsAt}], debtUnits}` | 04 |
| A19 | `GET /usage/history?limit=25&cursor=` (caller only) | — | `UsageHistoryDTO {jobs: [UsageJobDTO {jobId, action, status, paidBy: "allowance"\|"seat"\|"credits"\|"teacher_credits"\|"mixed"\|"none", percentOfPlan, credits, debtCredits, estimatePercentOfPlan: [lo, hi]\|null, estimateCredits: [lo, hi]\|null, actorUserId, createdAt, settledAt}], nextCursor}` (no raw units for allowance rows) | 04 |
| A20 | `GET /teacher/team/seats` · `/capacity` · `/assistants` · `/memberships` · `/invites` | — | `SeatListDTO {seats: SeatDTO[]}` (`SeatDTO {memberId, studentId, studentName, status: "active"\|"leaving", leavesAt, scopeSubjects, scopeActions, capUnits, capPeriod, capUsedUnits, meterFraction}`) · `SeatCapacityDTO {capacity, used, free}` · `AssistantListDTO {assistants: AssistantDTO[]}` (`AssistantDTO {memberId, assistantId, assistantName, role, permissions: dict[str,bool], effectivePermissions, capUnits, capPeriod, capUsedUnits}`) · `MembershipListDTO {memberships: MembershipDTO[]}` · `{invites: AssistantInviteDTO[]}` | 03 |
| A21 | `PUT /teacher/team/seats/{member_id}/scope` | `SetSeatScopeRequestDTO {subjects, actions}` | `SeatDTO` | 03 |
| A22 | `PUT /teacher/team/members/{member_id}/cap` | `SetCapRequestDTO {capUnits?, capPeriod="month"}` | `SeatDTO \| AssistantDTO`, discriminated by `kind: "student_seat" \| "assistant"` | 03 |
| A23 | `DELETE /teacher/team/seats/{member_id}` | — | `SeatDTO` (status `leaving`, `leavesAt` = month end) | 03 |
| A24 | `POST /teacher/team/assistants/invites` (201) | `CreateAssistantInviteRequestDTO {role, expiresInDays 1–30 = 7}` | `AssistantInviteDTO {inviteId, code, role, expiresAt, createdAt}` | 03 |
| A25 | `DELETE /teacher/team/invites/{invite_id}` (new, R3) | — | 204 | 03 |
| A26 | `POST /teacher/team/assistants/redeem` | `RedeemAssistantInviteRequestDTO {code}` | `MembershipDTO {memberId, teacherId, teacherName, role, effectivePermissions}` | 03 |
| A27 | `PATCH /teacher/team/assistants/{member_id}` · `DELETE /teacher/team/assistants/{member_id}` (204) | `UpdateAssistantRequestDTO {role?, permissions?: dict[str,bool]}` | `AssistantDTO` | 03 |
| A28 | `GET /admin/billing/catalogue` | — | `AdminCatalogueDTO {planTiers, creditPacks, freeAllowances, usageRates, usageEstimators}` (07 `PlanTierDTO {id, code, name, audience, interval, priceMinor, currency, allowanceUnits, includedSeats, seatAllowanceUnits, extraSeatPriceMinor, features, isActive, paymobPlanId, paymobDrift: "in_sync"\|"not_synced"\|"unverified"\|"drifted"}`, `CreditPackDTO {id, code, name, units, priceMinor, currency, isActive}`, `FreeAllowanceDTO {audience, creditPackId, units, validDays}`, `UsageRateDTO {id, version, action, unitsPerUsd, effectiveFrom}`, `UsageEstimatorDTO {id, version, action, inputKind, baseLow, baseHigh, perInputLow, perInputHigh, effectiveFrom}`) | 07 |
| A29 | `POST /admin/billing/tiers` · `PUT /admin/billing/tiers/{plan_tier_id}` · `POST /admin/billing/tiers/{plan_tier_id}/sync` | `PlanTierCreateDTO {code, name, audience, interval: "monthly"\|"yearly", priceMinor, currency="EGP", allowanceUnits, includedSeats=0, seatAllowanceUnits=0, extraSeatPriceMinor=0, features, isActive, reason}` · `PlanTierUpdateDTO {name, priceMinor, allowanceUnits, includedSeats, seatAllowanceUnits, extraSeatPriceMinor, features, isActive, reason}` (every editable field, required) · `ReasonDTO {reason}` | `PlanTierDTO` (each) | 07 |
| A30 | `POST /admin/billing/packs` · `PUT /admin/billing/packs/{credit_pack_id}` | `CreditPackCreateDTO {code, name, units>0, priceMinor>0, currency="EGP", isActive, reason}` · `CreditPackUpdateDTO {name, units, priceMinor, isActive, reason}` (every editable field, required) | `CreditPackDTO` | 07 |
| A31 | `PUT /admin/billing/free-allowances` · `POST /admin/billing/rates` · `POST /admin/billing/estimators` | `FreeAllowanceUpdateDTO {audience, units, reason}` · `UsageRateVersionDTO {action, unitsPerUsd, effectiveFrom?, reason}` · `UsageEstimatorVersionDTO {action, inputKind, baseLow, baseHigh, perInputLow, perInputHigh, effectiveFrom?, reason}` | `FreeAllowanceDTO` · `UsageRateDTO` · `UsageEstimatorDTO` | 07 |
| A32 | `GET /admin/billing/customers?q=&limit=20` · `GET /admin/billing/customers/{user_id}` | — | `CustomerSearchResultDTO {hits: [{userId, email, displayName, role, matchedOn}]}` · `CustomerDetailDTO {user, balance, subscriptions, grants, debts, usageJobs, payments, seats, assistants, seatedWith, parents, children, audit}` (fields as in plan 07 Task "customer view") | 07 |
| A33 | `POST /admin/billing/customers/{user_id}/grant` · `/adjust` · `/forgive-debt` · `/manual-activation` | `AdminGrantRequestDTO {units 1–1e6, validDays?=365, requestId: uuid, reason}` · `AdminAdjustRequestDTO {units ±1e6, requestId, reason}` · `AdminForgiveRequestDTO {units?, reason}` · `ManualActivationRequestDTO {planTierId, periodDays 1–400, reason}` | `CustomerDetailDTO` | 07 |
| A34 | `POST /admin/billing/subscriptions/{subscription_id}/extend` · `/cancel` | `AdminExtendRequestDTO {days 1–366, reason}` · `AdminCancelRequestDTO {when: "period_end"\|"now", reason}` | `CustomerDetailDTO` | 07 |
| A35 | `POST /admin/billing/payments/{payment_id}/refund` · `/void` · `/reconcile` | `AdminRefundRequestDTO {amountMinor?, reason}` · `ReasonDTO` · `ReasonDTO` | `AdminPaymentRowDTO {id, payerUserId, beneficiaryUserId, purpose, status, amountMinor, currency, refundedMinor, paymobOrderId, paymobTxnId, planTierId, creditPackId, subscriptionId, seatQuantity, createdAt, paidAt, refunds}` | 07 |
| A36 | `GET /admin/billing/payments?status=&purpose=&userId=&from=&to=&cursor=&limit=50` · `GET /admin/billing/problems` | — | `AdminPaymentsPageDTO {items, nextCursor}` · `ProblemQueueDTO {mismatches, stalePending, missingCallbacks: AdminPaymentRowDTO[], hmacFailures: WebhookFailureDTO[], hmacFailures24h, refundsNeedingAttention: RefundDTO[]}` | 07 |
| A37 | `GET /admin/billing/margin?from=&to=&egpPerUsd=` (`from`/`to` ISO datetimes, required) | — | `MarginReportDTO {windowStart, windowEnd, revenue {recurringMinor, packsMinor, refundedMinor, netMinor, byPurpose, byPlan: [{key, minor}]}, cost {totalUsd, byAction, byPlan: [{key, jobs, costUsd}], byModel: [{model, costUsd}], unattributedModelUsd}, egpPerUsd, costMinor, marginMinor, accuracy: [{action, estimatorVersion, jobs, below, above, shareOutside, meanOverrunUnits, maxOverrunUnits}], exposure {outstandingDebtUnits, debtors, topDebtors, usersAtLimit, creditsExpiring30dUnits, creditsExpiring30dOwners, creditsExpiredUnusedUnits, expiredJobs {count, costUsd}}}` | 07 |
| A38 | `GET /admin/billing/health?hours=24` | — | `BillingHealthDTO {windowHours, jobs: [{name, neverRun, lastStartedAt, lastFinishedAt, lastOutcome, lastResultCount, lastError, lastSuccessAt, consecutiveFailures, totalRuns, totalFailures}], verifiedEvents, hmacFailures, webhookErrorRate, mismatches, renewalFailureEvents, pastDueNow, failedAutoTopups, failedExtraSeatCharges}` | 07 |

**Routes R3 added, as their owners specified them** (Task 1 Step 1 re-checks the landed DTOs):

- **A5 summary** (plan 05 Task 13): shape in the table. It is how a parent sees a child's plan,
  allowance meter, credits and debt (A18/A19 serve the caller only). It carries no per-seat
  meters, so a student's own seat meters still come from A18.
- **A7/A14 quotes** (plan 06 `ChargeQuoteDTO`): `{amountMinor, currency, allowanceUnits,
  periodEnd}`, `allowanceUnits` set on upgrade quotes only. The card a charge would use is the
  summary's `savedCard`.
- **A13 cards** (plan 02): shape in the table.
- **A20/A22/A24/A25 team additions** (plan 03): `GET /teacher/team/invites`, `inviteId` and
  `createdAt` on `AssistantInviteDTO`, `capUsedUnits` + `meterFraction` on `SeatDTO`,
  `capUsedUnits` on `AssistantDTO`, a `kind` discriminator on both, the cap `PUT` returning the
  member's DTO, and `DELETE /teacher/team/invites/{invite_id}`.

**Remaining mismatches** (left for the owners; the frontend handles each without inventing data):

| # | Gap | Frontend handling until resolved |
|---|---|---|
| M2 | `PlanTierDTO.features` is an untyped `dict` in 02 and 07 | Convention used by the adapter: each key is a feature line, shown when its value is `true`; the admin editor writes `{line: true}`. Owners to confirm. |
| M3 | `EstimateDTO` has no payer name (seat teacher, lead teacher) | Copy says "your seat" / "your monthly plan" without a name. |
| M4 | `SeatMeterDTO` (usage meter) has no teacher name or subjects; seats carry no class names and assistants no email or status (names only, by design) | Student meter reads "Seat from your teacher"; team screens show names only. |
| M6 | `/usage/meter` and `/usage/history` take no `beneficiaryId` | Parent sees the child's meter through A5; there is no parent view of a child's usage history. |
| M9 | `ReceiptDTO` has no card, Paymob order id or refunded amount; `AdminPaymentRowDTO` has no payer/beneficiary names | Receipts show description, purpose, amount, date and status; admin rows show user ids. |
| M10 | Margin report has no per-month series | Money view shows totals and breakdowns (revenue by purpose and plan, cost by action/plan/model) instead of a revenue-vs-cost-by-month line. |
| M11 | Error bodies differ: 02 plain-string `detail`, 03 `detail: {code, message}`, 05/06 `detail: {error, message}` | `billingErrorCode` reads `detail.code ?? detail.error`. |
| M12 | `/teacher/team/*` gives no plan state, included/extra split, price or period end | Taken from A5 for the teacher: `subscription` (status, `extraSeats`, `pendingExtraSeats`, `currentPeriodEnd`, `tier.includedSeats`, `tier.extraSeatPriceMinor`, `tier.currency`). |

Behavioural assumptions:

- **402 body** (Phase 04 `usage_blocked_handler`): flat `{"error": "usage_blocked", "reason":
  <UsageBlockReason>, "estimate": [low, high]}` (no `detail` wrapper). `parseUsageBlock` reads
  the flat body and also tolerates a `detail` wrapper.
- **Conflict codes** (M11): Phase 05 `already_subscribed`, `seats_insufficient`,
  `payments_unavailable` (503); Phase 06 `no_saved_card`, `charge_in_flight`,
  `plan_change_pending`, `period_ending`, `seats_exceed_new_tier`, `seats_in_use`,
  `seat_reduction_pending`, `seat_charge_overdue`, `managed_by_another_payer`; Phase 03
  `no_free_seat`, `invite_already_redeemed`, `invite_limit`. `billingFailureMessage` maps them;
  an unknown code falls back to generic copy.
- **Redirection URL**: Paymob's `redirection_url` is `{redirection_base_url}/billing/return/
  {paymentId}`. The frontend ignores every query parameter Paymob appends and reads state only
  from A4 (spec §5.1 step 5).
- **Estimate display**: `payer` `seat`/`allowance` → show `percentLow–percentHigh%`; `credits` →
  `low–high credits`; `none` with `blockedReason` → the blocked notice. Marking estimates are a
  flat range with no page count (index R16), so the upload screens send no page input.
- **Assistant work** is always charged to the lead teacher (index R4); the teacher screens need
  nothing extra, the server resolves the acting teacher.
- **Upgrade and extra seats** are merchant-initiated charges (MOTO, spec §5.3/§5.4): A8 and A15
  return a `paymentId` (202) that settles asynchronously; the UI polls A4 inline.
- **Manual activation** in the customer view uses A33 `POST /admin/billing/customers/{userId}/
  manual-activation`. The legacy Activations screen keeps its own API until the backend
  retires it.
- **Seat actions**: Phase 03 exports `SEAT_ACTIONS` (index R12) and Phase 04 adds `mark_quiz` and
  `generate_flashcards` to `MeteredAction`. `METERED_ACTIONS` in `billingTypes.ts` lists all
  eight; `SEAT_ACTIONS` in `teamModel.ts` mirrors the backend seat-eligible set: `mark_paper`,
  `self_review`, `study_plan`, `mark_quiz`, `generate_flashcards` (Phase 04 made the last two
  seat-eligible). The seat editor offers all five, with `study_plan` off by default.
- `preview_quiz`, `mark_quiz` and `generate_flashcards` get no estimate integration in this
  phase: QuizBuilder step 5 shows stored questions, and quiz marking and flashcard generation
  have their own screens outside this plan's file sets. Wiring them follows Task 9's pattern.

## File structure

| File | Responsibility | Task |
|---|---|---|
| `web/src/lib/billingTypes.ts` | Wire DTOs (backend models, exact) and view types | 1 (team: 11, admin: 13) |
| `web/src/lib/billingAdapters.ts` | Wire DTO → view type adapters (pure) | 1 (team: 11, admin: 13) |
| `web/src/lib/billingFormat.ts` | Money, credits, percent, date, estimate and payment-phase formatting (pure) | 1 |
| `web/src/lib/usageBlock.ts` | Parse a 402 into `UsageBlock`; per-reason copy | 1 |
| `web/src/lib/billingOutcome.ts` | Failure sentences for billing mutations | 1 |
| `web/src/lib/billingPaths.ts` | Per-role billing route builders | 1 |
| `web/src/lib/hooks/useBillingApi.ts` | Fetchers + hooks for A1–A16 | 1 |
| `web/src/lib/hooks/useUsageApi.ts` | Fetchers + hooks for A17–A19 | 1 |
| `web/tests/unit/support/billingFixtures.ts` | Typed fixtures for every DTO (unit tests) | 1 |
| `web/tests/unit/support/billingRender.ts` | Static render helpers and fake query/mutation objects | 1 |
| `web/src/lib/usageMeterModel.ts` | Pure meter/credit/debt view models | 2 |
| `web/src/components/billing/usage-meter.tsx` | Allowance and seat meters | 2 |
| `web/src/components/billing/credit-balance.tsx` | Credit total with expiry breakdown | 2 |
| `web/src/components/billing/debt-notice.tsx` | Debt banner | 2 |
| `web/src/lib/meteredGate.ts` | `useMeteredGate` hook (estimate + 402 capture) | 3 |
| `web/src/components/billing/usage-blocked-notice.tsx` | 402 / blocked notice with next steps | 3 |
| `web/src/components/billing/estimate-range.tsx` | Pre-action estimate line | 3 |
| `web/src/lib/checkoutReturn.ts` | Return-path memory and return-page copy (pure) | 4 |
| `web/src/portals/billing/PlansView.tsx` | Tier and pack cards, interval toggle, checkout start | 4 |
| `web/src/portals/billing/PlansScreen.tsx` | Route wrappers per role | 4 |
| `web/src/lib/pricingModel.ts`, `web/src/portals/marketing/Pricing.tsx` | Public `/pricing` page and its links/preselect | 17 |
| `web/src/lib/auth/signupNext.ts` | Remember a validated `next` across sign-up and verification | 18 |
| `web/src/portals/billing/CheckoutReturn.tsx` | `/billing/return/:paymentId` polling page | 4 |
| `web/src/portals/billing/PaymentProgress.tsx` | Inline polling readout for MOTO charges | 5 |
| `web/src/portals/billing/PlanChangeDialog.tsx` | Upgrade/downgrade quote and confirm | 5 |
| `web/src/portals/billing/CancelPlanDialog.tsx` | Cancel at period end | 5 |
| `web/src/portals/billing/BillingOverview.tsx` | Billing page body shared by student, teacher, parent | 5 |
| `web/src/portals/billing/BillingScreens.tsx` | Student/teacher route wrappers | 5 |
| `web/src/portals/billing/ParentBilling.tsx` | Parent's child billing + child link | 6 |
| `web/src/portals/billing/UsageHistory.tsx` | Usage history table | 7 |
| `web/src/portals/billing/Receipts.tsx` | Receipts list | 7 |
| `web/src/portals/billing/AutoTopupCard.tsx` | Auto top-up settings form | 8 |
| `web/src/lib/hooks/useTeamApi.ts` | Fetchers + hooks for A20–A27 | 11 |
| `web/src/portals/teacher/screens/team/*` | Seats and assistants screens | 11, 12 |
| `web/src/lib/hooks/useAdminBillingApi.ts` | Fetchers + hooks for A28–A38 | 13 |
| `web/src/portals/admin/screens/billing/*` | Admin billing layout and five areas | 13–16 |

## Tasks

| # | Task | Depends on |
|---|---|---|
| 1 | Billing data layer: types, formatting, 402 parser, outcome copy, hooks, test fixtures | — |
| 2 | Usage meter, credit balance and debt notice components | 1 |
| 3 | Estimate range and usage-blocked notice | 1 |
| 4 | Plans page, checkout redirect and checkout return page | 1 |
| 5 | Billing overview for student and teacher, with plan change and cancel | 1, 2, 4 |
| 6 | Parent: billing for a linked child | 5 |
| 7 | Usage history and receipts | 1, 5 |
| 8 | Auto top-up settings | 1, 5 |
| 9 | Student metered entry points: marking upload, self-review, study plan | 3 |
| 10 | Teacher metered entry points: marking upload, regrade, quiz generation | 3 |
| 11 | Teacher seats: capacity, buy/remove extra seats, scope, cap, removal | 1, 5 |
| 12 | Teacher assistants: invites, role presets and toggles, cap, joining a team | 11 |
| 13 | Admin billing shell and catalogue | 1 |
| 14 | Admin customer view with reasoned actions | 13 |
| 15 | Admin payments, problem queue and health | 13 |
| 16 | Admin money and margin | 13 |
| 17 | Public pricing page (`/pricing`) and plan preselect | 1, 4 |
| 18 | Carry `next` through sign-up and email verification | 17 |

Tasks 2, 3, 4 and 13 may run in parallel once Task 1 is merged (disjoint file sets; each commits
with `git commit -S -- <its paths>`). Tasks 9 and 10 may run in parallel after Task 3.

---

### Task 1: Billing data layer

**Files:**
- Create: `web/src/lib/billingTypes.ts`
- Create: `web/src/lib/billingAdapters.ts`
- Create: `web/src/lib/billingFormat.ts`
- Create: `web/src/lib/usageBlock.ts`
- Create: `web/src/lib/billingOutcome.ts`
- Create: `web/src/lib/billingPaths.ts`
- Create: `web/src/lib/hooks/useBillingApi.ts`
- Create: `web/src/lib/hooks/useUsageApi.ts`
- Create: `web/tests/unit/support/billingFixtures.ts`
- Create: `web/tests/unit/support/billingRender.ts`
- Test: `web/tests/unit/billingFormat.test.ts`, `web/tests/unit/usageBlock.test.ts`,
  `web/tests/unit/billingAdapters.test.ts`, `web/tests/unit/billingApi.test.ts`

**Interfaces:**
- Consumes: `request`, `ApiError` from `web/src/lib/api.ts` (`request` prefixes `/api`).
- Produces (every later task imports these exact names):
  - wire DTO types (`Wire…`) and view types from `billingTypes.ts` (Step 4);
  - adapters `toPlanTier`, `featureLines`, `toCatalogue`, `toSavedCard`, `toUsageMeter`,
    `toBillingSummary`, `toAutoTopup`, `toEstimate`, `toUsageJob` from `billingAdapters.ts`;
  - `formatMoney(amountMinor, currency, locale?)`, `formatCredits(units, locale?)`,
    `formatPercent(fraction)`, `formatBillingDate(iso, locale?)`, `intervalLabel(interval)`,
    `estimateSentence(estimate)`, `isPercentPayer(payer)`, `isLiveSubscription(status)`,
    `paymentPhase(status)`, `PaymentPhase` from `billingFormat.ts`;
  - `parseUsageBlock(err): UsageBlock | null`, `UsageBlock`, `usageBlockCopy(reason, audience)`,
    `UsageBlockCopy` from `usageBlock.ts`;
  - `billingFailureMessage(err, action)`, `billingErrorCode(err)` from `billingOutcome.ts`;
  - `billingPaths(scope)`, `BillingPaths` (`history: string | null`), `BillingScope` from
    `billingPaths.ts`;
  - `billingApi`, `billingKeys`, `nextPaymentPoll`, `PAYMENT_POLL_MS`, `PAYMENT_POLL_LIMIT_MS`,
    and hooks `useCatalogue(audience)`, `useBillingSummary(beneficiaryId)`,
    `usePaymentStatus(paymentId)`, `useStartSubscriptionCheckout`, `useStartPackCheckout`,
    `useUpgradeQuote`, `useUpgrade`, `useDowngrade`, `useCancelSubscription` (variables
    `{ subscriptionId, planTierId? }`; downgrade and cancel return the subscription),
    `useReceipts`,
    `useAutoTopup(beneficiaryId)`, `useSaveAutoTopup`, `useSavedCards`, `useSeatQuote`,
    `useAddSeats`, `useReduceSeats` from `useBillingApi.ts`;
  - `usageApi`, `usageKeys`, `useUsageEstimate(request)`, `useUsageMeter()`,
    `useUsageHistory()`, `invalidateUsage(queryClient)` from `useUsageApi.ts`;
  - test helpers `renderStatic`, `renderAt`, `okQuery`, `pendingQuery`, `errorQuery`,
    `fakeMutation` from `support/billingRender.ts`, and the `fx` view fixtures from
    `support/billingFixtures.ts`.

- [ ] **Step 1: Match the merged backend exactly**

Open the merged routers and schemas named in "API assumptions" (`lemely/web/routers/billing.py`,
`lemely/web/schemas_billing*.py`, `lemely/web/routers/usage.py`, `lemely/web/schemas_usage.py`)
and, for routers not merged yet, the router task of plan 02, 04, 05 or 06. Copy every field of
the models in rows A1–A19 into the `Wire…` types of Step 4, field-for-field and in camelCase, and
the requested shapes (A5, A7, A13, A14) as their owners landed them. Where a field differs from
Step 4, change the wire type and its adapter in Step 5b; keep view types and every exported name
unchanged; list each difference in the commit body. Paths in Step 11–12 carry no `/api`
(`request` adds it).

- [ ] **Step 2: Write the failing formatting and 402 tests**

`web/tests/unit/billingFormat.test.ts`:

```ts
import { describe, expect, it } from "vitest"
import {
  estimateSentence,
  formatBillingDate,
  formatCredits,
  formatMoney,
  formatPercent,
  intervalLabel,
  isLiveSubscription,
  isPercentPayer,
  paymentPhase,
} from "@/lib/billingFormat"
import type { EstimateResponse } from "@/lib/billingTypes"

const est = (over: Partial<EstimateResponse>): EstimateResponse => ({
  low: 3,
  high: 5,
  payer: "credits",
  percentLow: null,
  percentHigh: null,
  blockedReason: null,
  ...over,
})

describe("billing formatting", () => {
  it("formats piasters as EGP with two decimals and the currency code", () => {
    expect(formatMoney(125000, "EGP", "en-US")).toMatch(/^EGP\s1,250\.00$/)
    expect(formatMoney(0, "EGP", "en-US")).toMatch(/^EGP\s0\.00$/)
  })

  it("pluralises credits and groups thousands", () => {
    expect(formatCredits(1, "en-US")).toBe("1 credit")
    expect(formatCredits(1240, "en-US")).toBe("1,240 credits")
  })

  it("rounds a fraction to a whole percentage and never goes negative", () => {
    expect(formatPercent(0.634)).toBe("63%")
    expect(formatPercent(1.2)).toBe("120%")
    expect(formatPercent(-0.1)).toBe("0%")
  })

  it("names the month so 8/11 cannot be misread", () => {
    expect(formatBillingDate("2026-11-14T00:00:00Z", "en-GB")).toBe("14 Nov 2026")
  })

  it("labels intervals", () => {
    expect(intervalLabel("month")).toBe("per month")
    expect(intervalLabel("year")).toBe("per year")
  })

  it("states a credit range with an en dash and a percent range against the plan or seat", () => {
    expect(estimateSentence(est({}))).toBe("3–5 credits")
    expect(estimateSentence(est({ low: 4, high: 4 }))).toBe("about 4 credits")
    expect(estimateSentence(est({ payer: "allowance", percentLow: 2, percentHigh: 4 }))).toBe("2–4% of your monthly plan")
    expect(estimateSentence(est({ payer: "allowance", percentLow: 0, percentHigh: 0 }))).toBe("under 1% of your monthly plan")
    expect(estimateSentence(est({ payer: "seat", percentLow: 1, percentHigh: 3 }))).toBe(
      "1–3% of your seat's monthly allowance",
    )
    expect(estimateSentence(est({ payer: "allowance", percentLow: null, percentHigh: null }))).toBe("3–5 credits")
    expect(estimateSentence(est({ payer: "none" }))).toBe("no charge")
  })

  it("knows which payers are shown as a percentage", () => {
    expect(isPercentPayer("allowance")).toBe(true)
    expect(isPercentPayer("seat")).toBe(true)
    expect(isPercentPayer("credits")).toBe(false)
    expect(isPercentPayer("none")).toBe(false)
  })

  it("treats pending-first-payment, active and past-due as a live subscription", () => {
    expect(isLiveSubscription("pending_first_payment")).toBe(true)
    expect(isLiveSubscription("active")).toBe(true)
    expect(isLiveSubscription("past_due")).toBe(true)
    expect(isLiveSubscription("cancelled")).toBe(false)
    expect(isLiveSubscription("expired")).toBe(false)
    expect(isLiveSubscription(undefined)).toBe(false)
  })

  it("groups payment statuses into the phases the return page shows", () => {
    expect(paymentPhase("created")).toBe("confirming")
    expect(paymentPhase("pending")).toBe("confirming")
    expect(paymentPhase("paid")).toBe("paid")
    expect(paymentPhase("failed")).toBe("failed")
    expect(paymentPhase("failed_mismatch")).toBe("mismatch")
    expect(paymentPhase("refunded")).toBe("reversed")
    expect(paymentPhase("partially_refunded")).toBe("reversed")
    expect(paymentPhase("voided")).toBe("reversed")
  })
})
```

`web/tests/unit/usageBlock.test.ts`:

```ts
import { describe, expect, it } from "vitest"
import { ApiError } from "@/lib/api"
import { USAGE_BLOCK_REASONS } from "@/lib/billingTypes"
import { parseUsageBlock, usageBlockCopy } from "@/lib/usageBlock"

const body = { error: "usage_blocked", reason: "insufficient_credits", estimate: [3, 5] }

describe("parseUsageBlock", () => {
  it("reads the flat 402 body Phase 04's handler sends", () => {
    const err = new ApiError(402, "402 Payment Required", undefined, undefined, body)
    expect(parseUsageBlock(err)).toEqual({ reason: "insufficient_credits", estimate: [3, 5] })
  })

  it("also reads a 402 body nested in FastAPI's detail", () => {
    const err = new ApiError(402, "402", body, undefined, { detail: body })
    expect(parseUsageBlock(err)).toEqual({ reason: "insufficient_credits", estimate: [3, 5] })
  })

  it("keeps the reason when the estimate is missing or malformed", () => {
    const err = new ApiError(402, "402", undefined, undefined, { ...body, estimate: ["a"] })
    expect(parseUsageBlock(err)).toEqual({ reason: "insufficient_credits", estimate: null })
  })

  it("ignores other statuses, unknown reasons and non-ApiErrors", () => {
    expect(parseUsageBlock(new ApiError(403, "403", undefined, undefined, body))).toBeNull()
    expect(
      parseUsageBlock(new ApiError(402, "402", undefined, undefined, { ...body, reason: "nope" })),
    ).toBeNull()
    expect(parseUsageBlock(new Error("x"))).toBeNull()
    expect(parseUsageBlock(new ApiError(402, "402"))).toBeNull()
  })
})

describe("usageBlockCopy", () => {
  it("has a title, body and next step for every reason and audience", () => {
    for (const reason of USAGE_BLOCK_REASONS) {
      for (const audience of ["student", "teacher"] as const) {
        const copy = usageBlockCopy(reason, audience)
        expect(copy.title.length).toBeGreaterThan(0)
        expect(copy.body.length).toBeGreaterThan(0)
        expect(["buy_credits", "see_plans", "ask_teacher"]).toContain(copy.next)
        expect(copy.title + copy.body).not.toMatch(/[!—]/)
      }
    }
  })

  it("sends a student outside their seat's scope to buy credits, not to a plan page", () => {
    expect(usageBlockCopy("out_of_seat_scope", "student").next).toBe("buy_credits")
    expect(usageBlockCopy("no_active_plan", "student").next).toBe("see_plans")
  })
})
```

- [ ] **Step 3: Run the tests to verify they fail**

Run (from `web/`): `npx vitest run tests/unit/billingFormat.test.ts tests/unit/usageBlock.test.ts`
Expected: FAIL, "Failed to resolve import "@/lib/billingFormat"".

- [ ] **Step 4: Write `web/src/lib/billingTypes.ts`**

The admin and team types are added by Tasks 11 and 13 (their sections of this file); this step
writes the shared enums, the billing and usage wire DTOs, and their view types.

```ts
/*
 * Phase 08 · Billing, usage, teacher-team and admin-billing types.
 *
 * Two layers (plan "API assumptions"):
 *   - `Wire…` types copy the backend Pydantic models field-for-field (camelCase on the wire,
 *     plans 02–07 own them, index R3). Only fetchers and `billingAdapters.ts` read them.
 *   - Unprefixed view types are what components consume. Adapters build them from wire DTOs,
 *     so a backend rename is a change to one wire type and one adapter.
 *
 * Money is integer minor units (piasters). Usage is integer units. Allowance sizes are hidden
 * from users (spec §2.1): user-facing meters are fractions and estimates for allowance payers
 * are percentages.
 */

// ── Enumerations ────────────────────────────────────────────────────────────

export type Audience = "student" | "teacher"
export type BillingInterval = "month" | "year"

/** Phase 03 base values plus Phase 04's additions (index R12). */
export const METERED_ACTIONS = [
  "mark_paper",
  "regrade",
  "generate_quiz",
  "preview_quiz",
  "self_review",
  "study_plan",
  "mark_quiz",
  "generate_flashcards",
] as const
export type MeteredAction = (typeof METERED_ACTIONS)[number]

/** Phase 04's five 402 reasons. */
export const USAGE_BLOCK_REASONS = [
  "usage_limit_reached",
  "no_active_plan",
  "insufficient_credits",
  "outstanding_debt",
  "out_of_seat_scope",
] as const
export type UsageBlockReason = (typeof USAGE_BLOCK_REASONS)[number]

export type PaymentStatus =
  | "created"
  | "pending"
  | "paid"
  | "failed"
  | "failed_mismatch"
  | "refunded"
  | "partially_refunded"
  | "voided"

export type PaymentPurpose =
  | "subscription_first"
  | "subscription_renewal"
  | "upgrade_proration"
  | "extra_seats"
  | "credit_pack"
  | "auto_topup"

export type SubscriptionStatus =
  | "pending_first_payment"
  | "active"
  | "past_due"
  | "cancelled"
  | "expired"
  | "inactive"
  | "rejected"

/** Phase 04 `EstimateDTO.payer`. */
export type EstimatePayer = "seat" | "allowance" | "credits" | "none"

export type CapPeriod = "month" | "total"

// ── Wire DTOs: Phase 02 (payments core) ─────────────────────────────────────

/** 02 `PlanTierDTO` (public catalogue). */
export interface WirePlanTier {
  planTierId: string
  code: string
  name: string
  priceMinor: number
  currency: string
  interval: "monthly" | "yearly" | null
  audience: string
  includedSeats: number
  extraSeatPriceMinor: number
  features: Record<string, unknown>
}

/** 02 `CreditPackDTO`. */
export interface WireCreditPack {
  creditPackId: string
  code: string
  name: string
  credits: number
  priceMinor: number
  currency: string
}

/** 02 `CatalogueDTO` (`GET /billing/catalogue`). */
export interface WireCatalogue {
  planTiers: WirePlanTier[]
  creditPacks: WireCreditPack[]
}

/** 02 `PackCheckoutRequest`. */
export interface PackCheckoutRequest {
  creditPackId: string
  beneficiaryId: string | null
}

/** 02 `CheckoutDTO`. */
export interface WireCheckout {
  paymentId: string
  checkoutUrl: string
}

/** 02 `PaymentStatusDTO`. */
export interface WirePaymentStatus {
  paymentId: string
  status: PaymentStatus
  purpose: PaymentPurpose
  amountMinor: number
  currency: string
  description: string
  paidAt: string | null
}

/** 02 `ReceiptDTO`. */
export interface WireReceipt {
  paymentId: string
  purpose: PaymentPurpose
  description: string
  amountMinor: number
  currency: string
  status: PaymentStatus
  paidAt: string
  beneficiaryId: string
}

/** 02 `ReceiptListDTO`. */
export interface WireReceiptList {
  receipts: WireReceipt[]
}

/** 02 `SavedCardView` (R3). `brand` is `""` from `/billing/cards` and may be `null` in the summary. */
export interface WireSavedCard {
  cardId: string
  maskedPan: string
  brand: string | null
}

/** 02 `SavedCardList` (`GET /billing/cards`, R3). */
export interface WireSavedCardList {
  cards: WireSavedCard[]
}

// ── Wire DTOs: Phase 05 (subscriptions) ─────────────────────────────────────

/** 05 `SubscriptionCheckoutRequestDTO`. */
export interface SubscriptionCheckoutRequest {
  planTierId: string
  beneficiaryId: string | null
  extraSeats: number
}

/** 05 `SubscriptionCheckoutDTO`. */
export interface WireSubscriptionCheckout {
  subscriptionId: string
  paymentId: string
  checkoutUrl: string
}

/** 05 `SubscriptionDTO`. */
export interface WireSubscription {
  id: string
  beneficiaryUserId: string
  isPayer: boolean
  planTierId: string
  planCode: string
  planName: string
  status: SubscriptionStatus
  currentPeriodStart: string | null
  currentPeriodEnd: string | null
  graceUntil: string | null
  cancelAtPeriodEnd: boolean
  pendingPlanTierId: string | null
  extraSeats: number
}

/** 05 `SubscriptionViewDTO` (inside the summary). */
export interface WireSubscriptionView {
  subscriptionId: string
  status: SubscriptionStatus
  tier: WirePlanTier
  currentPeriodStart: string | null
  currentPeriodEnd: string | null
  cancelAtPeriodEnd: boolean
  pendingTier: WirePlanTier | null
  graceUntil: string | null
  extraSeats: number
  pendingExtraSeats: number | null
}

/** 05 `BillingSummaryDTO` (`GET /billing/summary?beneficiaryId=`, plan 05 Task 13, R3). */
export interface WireBillingSummary {
  beneficiary: { userId: string; displayName: string | null; audience: string }
  subscription: WireSubscriptionView | null
  canManage: boolean
  managedByName: string | null
  savedCard: WireSavedCard | null
  usage: { fraction: number | null; resetsAt: string | null }
  credits: { totalUnits: number; expiring: { units: number; expiresAt: string | null }[] }
  debtUnits: number
  seats: { capacity: number; used: number } | null
}

// ── Wire DTOs: Phase 06 (merchant charges) ──────────────────────────────────

/** 06 `ChargeDTO` (202 from upgrade and extra seats). */
export interface WireCharge {
  paymentId: string
  status: PaymentStatus
  amountMinor: number
  currency: string
}

/** 06 `ChargeQuoteDTO`, for `…/upgrade/quote` and `…/seats/quote` (R3). No side effects; the
 * card it would charge is the summary's `savedCard`. */
export interface WireQuote {
  amountMinor: number
  currency: string
  /** Upgrade quotes: prorated allowance difference. Seat quotes: `null`. */
  allowanceUnits: number | null
  periodEnd: string
}

/** 06 `SeatsDTO`. */
export interface WireSeats {
  extraSeats: number
  pendingExtraSeats: number | null
}

/** 06 `AutoTopupRequest`. */
export interface AutoTopupUpdate {
  beneficiaryId: string | null
  enabled: boolean
  thresholdUnits: number
  creditPackId: string
  savedCardId: string | null
  monthlyCapMinor: number
}

/** 06 `AutoTopupDTO`. "Not set up" = `enabled: false`, the nullable fields `null`, `currency` "EGP". */
export interface WireAutoTopup {
  beneficiaryId: string
  enabled: boolean
  thresholdUnits: number | null
  creditPackId: string | null
  savedCardId: string | null
  monthlyCapMinor: number | null
  spentThisMonthMinor: number
  currency: string
  disabledReason: string | null
}

// ── Wire DTOs: Phase 04 (metering) ──────────────────────────────────────────

/** 04 `EstimateRequestDTO`: which action, and which record it would work on. */
export interface EstimateRequest {
  action: MeteredAction
  paperId?: string
  attemptId?: string
  questionResultId?: string
  assignmentId?: string
  subjectCode?: string
  count?: number
}

/** 04 `EstimateDTO`. */
export interface WireEstimate {
  low: number
  high: number
  payer: EstimatePayer
  percentLow: number | null
  percentHigh: number | null
  blockedReason: string | null
}

/** 04 `UsageMeterDTO`. */
export interface WireUsageMeter {
  allowanceFraction: number | null
  allowanceResetsAt: string | null
  creditsBalance: number
  creditLots: { remaining: number; expiresAt: string | null }[]
  seats: { teacherMemberId: string; teacherUserId: string; fraction: number | null; resetsAt: string | null }[]
  debtUnits: number
}

/** 04 `UsageJobDTO` paid-by values. */
export type UsageJobPaidBy = "allowance" | "seat" | "credits" | "teacher_credits" | "mixed" | "none"

/** 04 `UsageJobDTO`: display values only; allowance rows carry no raw units (spec §2.1). */
export interface WireUsageJob {
  jobId: string
  action: string
  status: string
  paidBy: UsageJobPaidBy
  /** Charged share of the plan (allowance or seat part), in percentage points. */
  percentOfPlan: number | null
  /** Charged credits (credit part). */
  credits: number | null
  /** Credits that went below zero. */
  debtCredits: number | null
  estimatePercentOfPlan: [number, number] | null
  estimateCredits: [number, number] | null
  actorUserId: string
  createdAt: string
  settledAt: string | null
}

/** 04 `UsageHistoryDTO`. */
export interface WireUsageHistory {
  jobs: WireUsageJob[]
  nextCursor: string | null
}

// ── View types ──────────────────────────────────────────────────────────────

export interface PlanTier {
  id: string
  code: string
  name: string
  audience: Audience
  interval: BillingInterval
  priceMinor: number
  currency: string
  /** Feature lines (M2: the keys of `features` whose value is `true`). */
  features: string[]
  /** Teacher tiers only; `null` on student tiers. */
  includedSeats: number | null
  /** Teacher tiers only: per seat per interval. */
  extraSeatPriceMinor: number | null
}

export interface CreditPack {
  id: string
  code: string
  name: string
  units: number
  priceMinor: number
  currency: string
}

export interface Catalogue {
  audience: Audience
  tiers: PlanTier[]
  packs: CreditPack[]
}

export interface CheckoutResponse {
  paymentId: string
  checkoutUrl: string
}

export type PaymentStatusView = WirePaymentStatus

export interface SavedCardView {
  cardId: string
  maskedPan: string
  brand: string
}

export interface SubscriptionView {
  subscriptionId: string
  status: SubscriptionStatus
  tier: PlanTier
  currentPeriodStart: string | null
  currentPeriodEnd: string | null
  cancelAtPeriodEnd: boolean
  /** A scheduled downgrade, applied at `currentPeriodEnd`. */
  pendingTier: PlanTier | null
  /** Set while `past_due`: access continues until then. */
  graceUntil: string | null
  extraSeats: number
  pendingExtraSeats: number | null
}

export interface CreditBucket {
  /** Stable React key (lot index plus expiry). */
  key: string
  remaining: number
  /** `null` = never expires. */
  expiresAt: string | null
}

export interface CreditBalance {
  total: number
  buckets: CreditBucket[]
}

export interface AllowanceMeter {
  fraction: number
  resetsAt: string
}

export interface SeatMeter {
  teacherMemberId: string
  teacherUserId: string
  /** `null` before the first seat grant of the month. */
  fraction: number | null
  resetsAt: string | null
}

export interface UsageMeterView {
  allowance: AllowanceMeter | null
  seats: SeatMeter[]
  credits: CreditBalance
  /** Outstanding debt on the account's own balance, in credits. 0 when none. */
  debtUnits: number
}

export interface SeatSummary {
  capacity: number
  used: number
}

export interface BillingSummary {
  beneficiary: { userId: string; displayName: string | null; audience: Audience }
  subscription: SubscriptionView | null
  /** The caller pays (or nobody pays yet and the caller may buy). */
  canManage: boolean
  /** The payer's name when someone else (a parent) manages billing. */
  managedByName: string | null
  savedCard: SavedCardView | null
  /** Allowance, credits and debt for the beneficiary. `seats` is empty: the summary carries no
   * seat meters; a signed-in student's own seat meters come from `useUsageMeter()`. */
  meter: UsageMeterView
  /** Teachers only. */
  seats: SeatSummary | null
}

/** Both quote routes (06). */
export type Quote = WireQuote

export type Receipt = WireReceipt

export type AutoTopupSettings = WireAutoTopup

export type MerchantChargeStarted = WireCharge
export type SeatReductionResult = WireSeats

export interface EstimateResponse {
  low: number
  high: number
  payer: EstimatePayer
  percentLow: number | null
  percentHigh: number | null
  blockedReason: UsageBlockReason | null
}

export type UsageJobStatus = "open" | "settled" | "released" | "expired"

export interface UsageJobRow extends Omit<WireUsageJob, "action" | "status"> {
  action: MeteredAction
  status: UsageJobStatus
}

export interface UsageHistoryPage {
  jobs: UsageJobRow[]
  nextCursor: string | null
}
```

- [ ] **Step 5: Write `web/src/lib/billingFormat.ts`**

```ts
import type { BillingInterval, EstimatePayer, EstimateResponse, PaymentStatus, SubscriptionStatus } from "@/lib/billingTypes"

/*
 * Pure formatting for every billing surface. `locale` defaults to `undefined` so the reader's
 * own conventions order the parts; tests pin a locale. Months are always named (see
 * `formatAdminDate` in portals/admin/data.ts for why a numeric month is unsafe here).
 */

export function formatMoney(amountMinor: number, currency: string, locale?: string): string {
  return new Intl.NumberFormat(locale, {
    style: "currency",
    currency,
    currencyDisplay: "code",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(amountMinor / 100)
}

export function formatCredits(units: number, locale?: string): string {
  const n = new Intl.NumberFormat(locale).format(units)
  return `${n} ${units === 1 ? "credit" : "credits"}`
}

export function formatPercent(fraction: number): string {
  return `${Math.max(0, Math.round(fraction * 100))}%`
}

export function formatBillingDate(iso: string, locale?: string): string {
  return new Date(iso).toLocaleDateString(locale, { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" })
}

export function intervalLabel(interval: BillingInterval): string {
  return interval === "month" ? "per month" : "per year"
}

export function isPercentPayer(payer: EstimatePayer): boolean {
  return payer === "seat" || payer === "allowance"
}

function range(low: number, high: number): string {
  return low === high ? `about ${high}` : `${low}–${high}`
}

/** "3–5 credits" or "2–4% of your monthly plan" (spec §2.4). */
export function estimateSentence(e: EstimateResponse): string {
  if (isPercentPayer(e.payer) && e.percentLow !== null && e.percentHigh !== null) {
    const amount = e.percentHigh < 1 ? "under 1%" : `${range(e.percentLow, e.percentHigh)}%`
    return e.payer === "seat" ? `${amount} of your seat's monthly allowance` : `${amount} of your monthly plan`
  }
  if (e.payer === "none") return "no charge"
  return e.low === e.high ? `about ${formatCredits(e.high)}` : `${e.low}–${e.high} credits`
}

/** One live subscription per beneficiary per audience (spec §4.3 partial unique index). */
export function isLiveSubscription(status: SubscriptionStatus | undefined): boolean {
  return status === "pending_first_payment" || status === "active" || status === "past_due"
}

export type PaymentPhase = "confirming" | "paid" | "failed" | "mismatch" | "reversed"

export function paymentPhase(status: PaymentStatus): PaymentPhase {
  switch (status) {
    case "created":
    case "pending":
      return "confirming"
    case "paid":
      return "paid"
    case "failed":
      return "failed"
    case "failed_mismatch":
      return "mismatch"
    case "refunded":
    case "partially_refunded":
    case "voided":
      return "reversed"
  }
}
```

- [ ] **Step 5b: Write `web/src/lib/billingAdapters.ts` and its test**

`web/tests/unit/billingAdapters.test.ts`:

```ts
import { describe, expect, it } from "vitest"
import {
  featureLines,
  toAutoTopup,
  toBillingSummary,
  toCatalogue,
  toEstimate,
  toSavedCard,
  toUsageJob,
  toUsageMeter,
} from "@/lib/billingAdapters"
import type { WireBillingSummary, WirePlanTier, WireUsageMeter } from "@/lib/billingTypes"

const tier = (over: Partial<WirePlanTier> = {}): WirePlanTier => ({
  planTierId: "t1",
  code: "student_plus_m",
  name: "Student Plus",
  priceMinor: 25000,
  currency: "EGP",
  interval: "monthly",
  audience: "student",
  includedSeats: 0,
  extraSeatPriceMinor: 0,
  features: { "Mark past papers": true, hidden: false },
  ...over,
})
const meter: WireUsageMeter = {
  allowanceFraction: 0.63,
  allowanceResetsAt: "2026-12-01T00:00:00Z",
  creditsBalance: 700,
  creditLots: [{ remaining: 500, expiresAt: "2027-10-02T00:00:00Z" }],
  seats: [{ teacherMemberId: "m1", teacherUserId: "u9", fraction: null, resetsAt: null }],
  debtUnits: 0,
}

describe("billing adapters", () => {
  it("renames catalogue fields, maps intervals, keeps one audience and drops interval-less tiers", () => {
    const c = toCatalogue(
      {
        planTiers: [tier(), tier({ planTierId: "t2", audience: "teacher", includedSeats: 20, extraSeatPriceMinor: 3000 }), tier({ planTierId: "t3", interval: null })],
        creditPacks: [{ creditPackId: "p1", code: "pack_500", name: "500 credits", credits: 500, priceMinor: 15000, currency: "EGP" }],
      },
      "student",
    )
    expect(c.tiers).toEqual([
      { id: "t1", code: "student_plus_m", name: "Student Plus", audience: "student", interval: "month", priceMinor: 25000, currency: "EGP", features: ["Mark past papers"], includedSeats: null, extraSeatPriceMinor: null },
    ])
    expect(c.packs[0]).toEqual({ id: "p1", code: "pack_500", name: "500 credits", units: 500, priceMinor: 15000, currency: "EGP" })
    expect(toCatalogue({ planTiers: [tier({ audience: "teacher", includedSeats: 20, extraSeatPriceMinor: 3000 })], creditPacks: [] }, "teacher").tiers[0]).toMatchObject({ includedSeats: 20, extraSeatPriceMinor: 3000 })
    expect(featureLines({ a: true, b: "x", c: false })).toEqual(["a"])
  })

  it("nests the flat usage meter", () => {
    expect(toUsageMeter(meter)).toEqual({
      allowance: { fraction: 0.63, resetsAt: "2026-12-01T00:00:00Z" },
      seats: [{ teacherMemberId: "m1", teacherUserId: "u9", fraction: null, resetsAt: null }],
      credits: { total: 700, buckets: [{ key: "0-2027-10-02T00:00:00Z", remaining: 500, expiresAt: "2027-10-02T00:00:00Z" }] },
      debtUnits: 0,
    })
    expect(toUsageMeter({ ...meter, allowanceFraction: null }).allowance).toBeNull()
  })

  it("builds the summary: tier from 02's PlanTierDTO, flat usage and credits nested into a meter", () => {
    const w: WireBillingSummary = {
      beneficiary: { userId: "u2", displayName: "Omar", audience: "student" },
      subscription: {
        subscriptionId: "sub1",
        status: "active",
        tier: tier(),
        currentPeriodStart: "2026-11-01T00:00:00Z",
        currentPeriodEnd: "2026-12-01T00:00:00Z",
        cancelAtPeriodEnd: false,
        pendingTier: null,
        graceUntil: null,
        extraSeats: 0,
        pendingExtraSeats: null,
      },
      canManage: false,
      managedByName: "Mona",
      savedCard: { cardId: "c", maskedPan: "•••• 1", brand: null },
      usage: { fraction: 0.63, resetsAt: "2026-12-01T00:00:00Z" },
      credits: { totalUnits: 700, expiring: [{ units: 500, expiresAt: "2027-10-02T00:00:00Z" }] },
      debtUnits: 12,
      seats: null,
    }
    const s = toBillingSummary(w)
    expect(s.canManage).toBe(false)
    expect(s.managedByName).toBe("Mona")
    expect(s.subscription).toMatchObject({ subscriptionId: "sub1", status: "active", tier: { id: "t1", interval: "month" }, pendingTier: null })
    expect(s.meter).toEqual({
      allowance: { fraction: 0.63, resetsAt: "2026-12-01T00:00:00Z" },
      seats: [],
      credits: { total: 700, buckets: [{ key: "0-2027-10-02T00:00:00Z", remaining: 500, expiresAt: "2027-10-02T00:00:00Z" }] },
      debtUnits: 12,
    })
    expect(s.savedCard?.brand).toBe("Card")
    expect(toBillingSummary({ ...w, subscription: null }).subscription).toBeNull()
    expect(toSavedCard(null)).toBeNull()
  })

  it("maps auto top-up, estimates and jobs", () => {
    expect(toAutoTopup({ beneficiaryId: "u2", enabled: false, thresholdUnits: null, creditPackId: null, savedCardId: null, monthlyCapMinor: null, spentThisMonthMinor: 0, currency: "", disabledReason: null }).currency).toBe("EGP")
    expect(toEstimate({ low: 3, high: 5, payer: "credits", percentLow: null, percentHigh: null, blockedReason: "nope" }).blockedReason).toBeNull()
    expect(toEstimate({ low: 3, high: 5, payer: "none", percentLow: null, percentHigh: null, blockedReason: "insufficient_credits" }).blockedReason).toBe("insufficient_credits")
    expect(
      toUsageJob({ jobId: "j", action: "regrade", status: "released", paidBy: "none", percentOfPlan: null, credits: null, debtCredits: null, estimatePercentOfPlan: [1, 2], estimateCredits: null, actorUserId: "u", createdAt: "x", settledAt: null }),
    ).toMatchObject({ action: "regrade", status: "released", paidBy: "none" })
  })
})
```

`web/src/lib/billingAdapters.ts`:

```ts
import {
  USAGE_BLOCK_REASONS,
  type AutoTopupSettings,
  type BillingSummary,
  type Catalogue,
  type Audience,
  type CreditPack,
  type EstimateResponse,
  type MeteredAction,
  type PlanTier,
  type SavedCardView,
  type UsageBlockReason,
  type UsageJobRow,
  type UsageJobStatus,
  type UsageMeterView,
  type WireAutoTopup,
  type WireBillingSummary,
  type WireCatalogue,
  type WireCreditPack,
  type WireEstimate,
  type WirePlanTier,
  type WireSavedCard,
  type WireUsageJob,
  type WireUsageMeter,
} from "@/lib/billingTypes"

/*
 * Wire DTO → view type. Pure and unit-tested; the only code besides fetchers that reads a
 * `Wire…` type. Every rename between the backend plans and the screens lives here.
 */

/** M2 convention: each key of `features` is a line, shown when its value is `true`. */
export function featureLines(features: Record<string, unknown>): string[] {
  return Object.entries(features)
    .filter(([, v]) => v === true)
    .map(([k]) => k)
}

/** `null` for a tier with no interval (legacy manual plans are not sold). */
export function toPlanTier(w: WirePlanTier): PlanTier | null {
  if (w.interval === null) return null
  const teacher = w.audience === "teacher"
  return {
    id: w.planTierId,
    code: w.code,
    name: w.name,
    audience: teacher ? "teacher" : "student",
    interval: w.interval === "yearly" ? "year" : "month",
    priceMinor: w.priceMinor,
    currency: w.currency,
    features: featureLines(w.features),
    includedSeats: teacher ? w.includedSeats : null,
    extraSeatPriceMinor: teacher ? w.extraSeatPriceMinor : null,
  }
}

export function toCreditPack(w: WireCreditPack): CreditPack {
  return { id: w.creditPackId, code: w.code, name: w.name, units: w.credits, priceMinor: w.priceMinor, currency: w.currency }
}

export function toCatalogue(w: WireCatalogue, audience: Audience): Catalogue {
  return {
    audience,
    tiers: w.planTiers
      .map(toPlanTier)
      .filter((t): t is PlanTier => t !== null && t.audience === audience),
    packs: w.creditPacks.map(toCreditPack),
  }
}

export function toSavedCard(w: WireSavedCard | null): SavedCardView | null {
  return w ? { cardId: w.cardId, maskedPan: w.maskedPan, brand: w.brand || "Card" } : null
}

export function toUsageMeter(w: WireUsageMeter): UsageMeterView {
  return {
    allowance:
      w.allowanceFraction !== null && w.allowanceResetsAt !== null
        ? { fraction: w.allowanceFraction, resetsAt: w.allowanceResetsAt }
        : null,
    seats: w.seats.map((s) => ({ teacherMemberId: s.teacherMemberId, teacherUserId: s.teacherUserId, fraction: s.fraction, resetsAt: s.resetsAt })),
    credits: {
      total: w.creditsBalance,
      buckets: w.creditLots.map((l, i) => ({ key: `${i}-${l.expiresAt ?? "never"}`, remaining: l.remaining, expiresAt: l.expiresAt })),
    },
    debtUnits: w.debtUnits,
  }
}

export function toBillingSummary(w: WireBillingSummary): BillingSummary {
  const sub = w.subscription
  const tier = sub ? toPlanTier(sub.tier) : null
  return {
    beneficiary: { ...w.beneficiary, audience: w.beneficiary.audience === "teacher" ? "teacher" : "student" },
    subscription:
      sub && tier
        ? {
            subscriptionId: sub.subscriptionId,
            status: sub.status,
            tier,
            currentPeriodStart: sub.currentPeriodStart,
            currentPeriodEnd: sub.currentPeriodEnd,
            cancelAtPeriodEnd: sub.cancelAtPeriodEnd,
            pendingTier: sub.pendingTier ? toPlanTier(sub.pendingTier) : null,
            graceUntil: sub.graceUntil,
            extraSeats: sub.extraSeats,
            pendingExtraSeats: sub.pendingExtraSeats,
          }
        : null,
    canManage: w.canManage,
    managedByName: w.managedByName,
    savedCard: toSavedCard(w.savedCard),
    meter: {
      allowance:
        w.usage.fraction !== null && w.usage.resetsAt !== null ? { fraction: w.usage.fraction, resetsAt: w.usage.resetsAt } : null,
      seats: [],
      credits: {
        total: w.credits.totalUnits,
        buckets: w.credits.expiring.map((l, i) => ({ key: `${i}-${l.expiresAt ?? "never"}`, remaining: l.units, expiresAt: l.expiresAt })),
      },
      debtUnits: w.debtUnits,
    },
    seats: w.seats,
  }
}

/** 06 sends `currency`; an empty one (defensive) falls back to EGP, the only catalogue currency. */
export function toAutoTopup(w: WireAutoTopup): AutoTopupSettings {
  return { ...w, currency: w.currency || "EGP" }
}

function blockReason(value: string | null): UsageBlockReason | null {
  return value !== null && (USAGE_BLOCK_REASONS as readonly string[]).includes(value) ? (value as UsageBlockReason) : null
}

export function toEstimate(w: WireEstimate): EstimateResponse {
  return { ...w, blockedReason: blockReason(w.blockedReason) }
}

export function toUsageJob(w: WireUsageJob): UsageJobRow {
  return { ...w, action: w.action as MeteredAction, status: w.status as UsageJobStatus }
}
```

- [ ] **Step 6: Write `web/src/lib/usageBlock.ts`**

```ts
import { ApiError } from "@/lib/api"
import { USAGE_BLOCK_REASONS, type Audience, type UsageBlockReason } from "@/lib/billingTypes"

/*
 * A 402 from any metered route. Phase 04's `usage_blocked_handler` sends the flat body
 * `{"error": "usage_blocked", "reason", "estimate": [low, high]}`; a `detail`-wrapped body is
 * tolerated too. Anything else (another status, an unknown reason) is not a usage block and
 * returns `null`, so the caller's ordinary failure copy still applies.
 */

export interface UsageBlock {
  reason: UsageBlockReason
  estimate: [number, number] | null
}

function fromBody(value: unknown): UsageBlock | null {
  if (!value || typeof value !== "object") return null
  const v = value as { error?: unknown; reason?: unknown; estimate?: unknown }
  if (v.error !== "usage_blocked" || typeof v.reason !== "string") return null
  if (!(USAGE_BLOCK_REASONS as readonly string[]).includes(v.reason)) return null
  const e = v.estimate
  const estimate =
    Array.isArray(e) && e.length === 2 && typeof e[0] === "number" && typeof e[1] === "number"
      ? ([e[0], e[1]] as [number, number])
      : null
  return { reason: v.reason as UsageBlockReason, estimate }
}

export function parseUsageBlock(err: unknown): UsageBlock | null {
  if (!(err instanceof ApiError) || err.status !== 402) return null
  return fromBody(err.body) ?? fromBody(err.detail)
}

export interface UsageBlockCopy {
  title: string
  body: string
  /** The one next step the notice offers. */
  next: "buy_credits" | "see_plans" | "ask_teacher"
}

const STUDENT: Record<UsageBlockReason, UsageBlockCopy> = {
  usage_limit_reached: {
    title: "You've used this month's plan",
    body: "Credits take over once your plan runs out. Add a pack to keep going, or wait for your plan to reset.",
    next: "buy_credits",
  },
  no_active_plan: {
    title: "You need a plan or credits for this",
    body: "Marking and the other AI tools run on a plan or a credit pack. Pick one to get started.",
    next: "see_plans",
  },
  insufficient_credits: {
    title: "Not enough credits for this one",
    body: "This could cost more than you have left. Add a pack, then try again. You only pay what it actually costs.",
    next: "buy_credits",
  },
  outstanding_debt: {
    title: "Your balance is below zero",
    body: "A recent job cost more than you had left. Your next credit pack or plan renewal clears that first, then you can start new work.",
    next: "buy_credits",
  },
  out_of_seat_scope: {
    title: "Your teacher's seat doesn't cover this",
    body: "Your own plan or credits would pay instead, and they can't cover it right now. Add credits, or ask your teacher to include it.",
    next: "buy_credits",
  },
}

const TEACHER: Record<UsageBlockReason, UsageBlockCopy> = {
  usage_limit_reached: {
    title: "This month's plan allowance is used",
    body: "Credits pay once the allowance runs out. Buy a pack to continue, or upgrade the plan.",
    next: "buy_credits",
  },
  no_active_plan: {
    title: "No active plan or credits",
    body: "AI marking, regrades and quiz generation need a plan or a credit pack.",
    next: "see_plans",
  },
  insufficient_credits: {
    title: "Not enough credits for this job",
    body: "The top of the estimate is more than the balance left. Buy a pack and try again. Only the actual cost is charged.",
    next: "buy_credits",
  },
  outstanding_debt: {
    title: "Balance below zero",
    body: "A recent job cost more than the balance. The next pack or renewal clears it, then new jobs can start.",
    next: "buy_credits",
  },
  out_of_seat_scope: {
    title: "Outside your team's limits",
    body: "The lead teacher's balance, or the cap they set for you, doesn't cover this job. Ask them to raise it.",
    next: "ask_teacher",
  },
}

export function usageBlockCopy(reason: UsageBlockReason, audience: Audience): UsageBlockCopy {
  return (audience === "student" ? STUDENT : TEACHER)[reason]
}
```

- [ ] **Step 7: Run the format, adapter and 402 tests to verify they pass**

Run: `npx vitest run tests/unit/billingFormat.test.ts tests/unit/usageBlock.test.ts tests/unit/billingAdapters.test.ts`
Expected: PASS (three files).

- [ ] **Step 8: Write the failing fetcher tests**

`web/tests/unit/billingApi.test.ts`:

```ts
import { beforeEach, describe, expect, it, vi } from "vitest"

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  request: vi.fn(),
}))

import { ApiError, request } from "@/lib/api"
import { billingApi, nextPaymentPoll, PAYMENT_POLL_LIMIT_MS, PAYMENT_POLL_MS } from "@/lib/hooks/useBillingApi"
import { usageApi } from "@/lib/hooks/useUsageApi"
import { billingErrorCode, billingFailureMessage } from "@/lib/billingOutcome"
import { billingPaths } from "@/lib/billingPaths"

const req = vi.mocked(request)

beforeEach(() => {
  req.mockReset()
  req.mockResolvedValue({})
})

const calls = () => req.mock.calls.map((c) => [c[0], (c[1] as RequestInit | undefined)?.method ?? "GET"])

describe("billing fetchers (paths without /api: request() adds it)", () => {
  it("hits every billing route with the right method", async () => {
    await billingApi.catalogue()
    await billingApi.summary(null)
    await billingApi.summary("child 1")
    await billingApi.startSubscriptionCheckout({ planTierId: "t1", beneficiaryId: null, extraSeats: 2 })
    await billingApi.startPackCheckout({ creditPackId: "p1", beneficiaryId: "c1" })
    await billingApi.payment("pay/1")
    await billingApi.upgradeQuote("s1", "t2")
    await billingApi.upgrade("s1", "t2")
    await billingApi.downgrade("s1", "t0")
    await billingApi.cancel("s1")
    await billingApi.receipts()
    await billingApi.autoTopup(null)
    await billingApi.autoTopup("c1")
    await billingApi.saveAutoTopup({ beneficiaryId: null, enabled: true, thresholdUnits: 100, creditPackId: "p1", savedCardId: "card1", monthlyCapMinor: 50000 })
    await billingApi.cards()
    await billingApi.seatQuote("s1", 3)
    await billingApi.addSeats("s1", 3)
    await billingApi.reduceSeats("s1", 1)
    expect(calls()).toEqual([
      ["/billing/catalogue", "GET"],
      ["/billing/summary", "GET"],
      ["/billing/summary?beneficiaryId=child%201", "GET"],
      ["/billing/subscriptions/checkout", "POST"],
      ["/billing/checkout/pack", "POST"],
      ["/billing/payments/pay%2F1", "GET"],
      ["/billing/subscriptions/s1/upgrade/quote", "POST"],
      ["/billing/subscriptions/s1/upgrade", "POST"],
      ["/billing/subscriptions/s1/downgrade", "POST"],
      ["/billing/subscriptions/s1/cancel", "POST"],
      ["/billing/receipts", "GET"],
      ["/billing/auto-topup", "GET"],
      ["/billing/auto-topup?beneficiaryId=c1", "GET"],
      ["/billing/auto-topup", "PUT"],
      ["/billing/cards", "GET"],
      ["/billing/subscriptions/s1/seats/quote", "POST"],
      ["/billing/subscriptions/s1/seats", "POST"],
      ["/billing/subscriptions/s1/seats/pending", "PUT"],
    ])
  })

  it("sends the backend request bodies", async () => {
    await billingApi.upgrade("s1", "t2")
    await billingApi.addSeats("s1", 3)
    await billingApi.reduceSeats("s1", 1)
    const bodies = req.mock.calls.map((c) => JSON.parse(String((c[1] as RequestInit).body)))
    expect(bodies).toEqual([{ planTierId: "t2" }, { seats: 3 }, { extraSeats: 1 }])
  })
})

describe("usage fetchers", () => {
  it("posts the flat estimate body and pages history with a cursor", async () => {
    await usageApi.estimate({ action: "regrade", paperId: "p1" })
    await usageApi.meter()
    await usageApi.history(null)
    await usageApi.history("next 2")
    expect(calls()).toEqual([
      ["/usage/estimate", "POST"],
      ["/usage/meter", "GET"],
      ["/usage/history?limit=25", "GET"],
      ["/usage/history?limit=25&cursor=next+2", "GET"],
    ])
    expect(JSON.parse(String((req.mock.calls[0][1] as RequestInit).body))).toEqual({ action: "regrade", paperId: "p1" })
  })
})

describe("payment polling", () => {
  it("polls every 2s while confirming and stops at terminal states or after 3 minutes", () => {
    expect(PAYMENT_POLL_MS).toBe(2000)
    expect(PAYMENT_POLL_LIMIT_MS).toBe(180_000)
    expect(nextPaymentPoll(undefined, 0, 1000)).toBe(2000)
    expect(nextPaymentPoll("pending", 0, 1000)).toBe(2000)
    expect(nextPaymentPoll("created", 0, 179_999)).toBe(2000)
    expect(nextPaymentPoll("pending", 0, 180_000)).toBe(false)
    expect(nextPaymentPoll("paid", 0, 1000)).toBe(false)
    expect(nextPaymentPoll("failed", 0, 1000)).toBe(false)
  })
})

describe("billing failure copy", () => {
  it("reads both backend error shapes and keeps unknown codes generic", () => {
    const errorShape = (error: string) => new ApiError(409, "409", { error, message: "x" })
    const codeShape = (code: string) => new ApiError(409, "409", { code, message: "x" })
    expect(billingErrorCode(errorShape("no_saved_card"))).toBe("no_saved_card")
    expect(billingErrorCode(codeShape("no_free_seat"))).toBe("no_free_seat")
    expect(billingErrorCode(new ApiError(403, "You can only buy for a linked child", "You can only buy for a linked child"))).toBeNull()
    expect(billingFailureMessage(errorShape("no_saved_card"), "upgrade")).toMatch(/saved card/)
    expect(billingFailureMessage(errorShape("seats_in_use"), "remove seats")).toMatch(/seat/)
    expect(billingFailureMessage(errorShape("seats_insufficient"), "downgrade")).toMatch(/seat/)
    expect(billingFailureMessage(errorShape("weird"), "upgrade")).toBe("Couldn't upgrade. Nothing was charged. Try again.")
  })

  it("says nothing was charged when offline or when payments are down", () => {
    expect(billingFailureMessage(new ApiError(0, "x"), "buy credits")).toMatch(/offline/)
    expect(billingFailureMessage(new ApiError(503, "x"), "buy credits")).toMatch(/Payments are unavailable/)
    for (const s of [0, 403, 409, 422, 429, 500, 503]) {
      expect(billingFailureMessage(new ApiError(s, "x"), "pay")).not.toMatch(/[!—]/)
    }
  })
})

describe("billing paths", () => {
  it("builds per-role billing routes; a parent has no child usage history (M6)", () => {
    expect(billingPaths({ role: "student" }).plans).toBe("/student/billing/plans")
    expect(billingPaths({ role: "teacher" }).overview).toBe("/teacher/billing")
    expect(billingPaths({ role: "parent", childId: "c1" })).toEqual({
      overview: "/parent/children/c1/billing",
      plans: "/parent/children/c1/billing/plans",
      packs: "/parent/children/c1/billing/plans#packs",
      history: null,
      receipts: "/parent/billing/receipts",
    })
  })
})
```

- [ ] **Step 9: Run it to verify it fails**

Run: `npx vitest run tests/unit/billingApi.test.ts`
Expected: FAIL, "Failed to resolve import "@/lib/hooks/useBillingApi"".

- [ ] **Step 10: Write `web/src/lib/billingOutcome.ts` and `web/src/lib/billingPaths.ts`**

```ts
// web/src/lib/billingOutcome.ts
import { ApiError } from "@/lib/api"

/*
 * What a payer is told when a billing write fails. Every billing write inserts its payment row
 * before calling Paymob (spec §6), so a failed request never charged anyone, and saying so is
 * the one thing a payer most needs to hear. Status-first: the backend's own messages are
 * written for client authors, not payers.
 *
 * Error bodies differ by phase (M11): Phase 03 sends `detail: {code, message}`, Phases 05/06
 * `detail: {error, message}`, Phase 02 a plain-string `detail`. `billingErrorCode` reads both
 * object shapes.
 */

export function billingErrorCode(err: unknown): string | null {
  if (!(err instanceof ApiError)) return null
  const d = err.detail as { code?: unknown; error?: unknown } | undefined
  if (!d || typeof d !== "object") return null
  if (typeof d.code === "string") return d.code
  return typeof d.error === "string" ? d.error : null
}

const CONFLICTS: Record<string, string> = {
  already_subscribed: "There's already an active plan on this account. Change it from the billing page instead.",
  no_saved_card: "There's no saved card for this. Buy a credit pack by card once and Lemely keeps the card for later charges.",
  seats_in_use:
    "More students hold seats than this would leave. Remove students first. A removed student's seat frees up at the end of the month.",
  seats_insufficient: "That plan has fewer seats than students you have seated. Remove students first, then change the plan.",
  seats_exceed_new_tier: "That plan has fewer seats than students you have seated. Remove students first, then change the plan.",
  charge_in_flight: "A charge for this is already being confirmed. Wait a minute, then check again.",
  plan_change_pending: "A plan change is already scheduled. It applies at the end of this period.",
  period_ending: "This period ends too soon to change now. Try again after the renewal.",
  seat_reduction_pending: "A seat reduction is already scheduled for the end of this period.",
  seat_charge_overdue: "The last seat charge hasn't been paid yet. Check the saved card, then try again.",
  managed_by_another_payer: "Someone else pays for this account, so only they can change it.",
  no_free_seat: "This teacher has no free seats. Ask them to add a seat.",
  invite_already_redeemed: "That invite has already been used. Ask for a new one.",
  invite_limit: "There are too many open invites. Revoke one first.",
}

export function billingFailureMessage(err: unknown, action: string): string {
  const status = err instanceof ApiError ? err.status : -1
  if (status === 0) return "You're offline. Nothing was charged. Try again when you're back online."
  if (status === 503) return "Payments are unavailable right now. Nothing was charged. Try again in a few minutes."
  if (status === 403) return "This account can't manage billing here. Only the person who pays can."
  if (status === 429) return "Too many attempts. Wait a minute and try again."
  if (status === 409) {
    const code = billingErrorCode(err)
    if (code && CONFLICTS[code]) return CONFLICTS[code]
  }
  if (status === 422) return `Couldn't ${action}. Check the details and try again.`
  return `Couldn't ${action}. Nothing was charged. Try again.`
}
```

```ts
// web/src/lib/billingPaths.ts
/*
 * Where each role's billing screens live. Parents reach a child's billing under the child; the
 * child's usage history has no parent route (M6: `/usage/history` serves the caller only), and
 * receipts belong to the payer, so a parent's receipts are one list across all children.
 */

export type BillingScope = { role: "student" } | { role: "teacher" } | { role: "parent"; childId: string }

export interface BillingPaths {
  overview: string
  plans: string
  packs: string
  history: string | null
  receipts: string
}

export function billingPaths(scope: BillingScope): BillingPaths {
  if (scope.role === "parent") {
    const base = `/parent/children/${scope.childId}/billing`
    return { overview: base, plans: `${base}/plans`, packs: `${base}/plans#packs`, history: null, receipts: "/parent/billing/receipts" }
  }
  const base = `/${scope.role}/billing`
  return { overview: base, plans: `${base}/plans`, packs: `${base}/plans#packs`, history: `${base}/history`, receipts: `${base}/receipts` }
}
```

- [ ] **Step 11: Write `web/src/lib/hooks/useBillingApi.ts`**

```ts
import { useRef } from "react"
import { useMutation, useQuery, useQueryClient, type UseMutationResult, type UseQueryResult } from "@tanstack/react-query"
import { request } from "@/lib/api"
import { toAutoTopup, toBillingSummary, toCatalogue, toSavedCard } from "@/lib/billingAdapters"
import type {
  Audience,
  AutoTopupSettings,
  AutoTopupUpdate,
  BillingSummary,
  Catalogue,
  CheckoutResponse,
  MerchantChargeStarted,
  PackCheckoutRequest,
  PaymentStatus,
  PaymentStatusView,
  Quote,
  Receipt,
  SavedCardView,
  SeatReductionResult,
  SubscriptionCheckoutRequest,
  WireAutoTopup,
  WireBillingSummary,
  WireCatalogue,
  WireCharge,
  WireCheckout,
  WirePaymentStatus,
  WireQuote,
  WireReceiptList,
  WireSavedCardList,
  WireSeats,
  WireSubscription,
  WireSubscriptionCheckout,
} from "@/lib/billingTypes"

/*
 * React-query hooks over `/api/billing/*` (plans 02, 05, 06). Paths omit `/api`: `request()`
 * adds it. Fetchers return wire DTOs; hooks adapt them to view types. No `fallback` is passed
 * to `request()`: a failed money read must surface as a failure, never as an empty plan.
 */

const enc = encodeURIComponent
const post = (body?: unknown): RequestInit => (body === undefined ? { method: "POST" } : { method: "POST", body: JSON.stringify(body) })
const sub = (id: string) => `/billing/subscriptions/${enc(id)}`

function withBeneficiary(path: string, beneficiaryId: string | null): string {
  return beneficiaryId ? `${path}?beneficiaryId=${enc(beneficiaryId)}` : path
}

export const billingApi = {
  catalogue: () => request<WireCatalogue>("/billing/catalogue"),
  summary: (beneficiaryId: string | null) => request<WireBillingSummary>(withBeneficiary("/billing/summary", beneficiaryId)),
  startSubscriptionCheckout: (body: SubscriptionCheckoutRequest) =>
    request<WireSubscriptionCheckout>("/billing/subscriptions/checkout", post(body)),
  startPackCheckout: (body: PackCheckoutRequest) => request<WireCheckout>("/billing/checkout/pack", post(body)),
  payment: (paymentId: string) => request<WirePaymentStatus>(`/billing/payments/${enc(paymentId)}`),
  upgradeQuote: (subscriptionId: string, planTierId: string) =>
    request<WireQuote>(`${sub(subscriptionId)}/upgrade/quote`, post({ planTierId })),
  upgrade: (subscriptionId: string, planTierId: string) => request<WireCharge>(`${sub(subscriptionId)}/upgrade`, post({ planTierId })),
  downgrade: (subscriptionId: string, planTierId: string) =>
    request<WireSubscription>(`${sub(subscriptionId)}/downgrade`, post({ planTierId })),
  cancel: (subscriptionId: string) => request<WireSubscription>(`${sub(subscriptionId)}/cancel`, post()),
  receipts: () => request<WireReceiptList>("/billing/receipts"),
  autoTopup: (beneficiaryId: string | null) => request<WireAutoTopup>(withBeneficiary("/billing/auto-topup", beneficiaryId)),
  saveAutoTopup: (body: AutoTopupUpdate) => request<WireAutoTopup>("/billing/auto-topup", { method: "PUT", body: JSON.stringify(body) }),
  cards: () => request<WireSavedCardList>("/billing/cards"),
  seatQuote: (subscriptionId: string, seats: number) => request<WireQuote>(`${sub(subscriptionId)}/seats/quote`, post({ seats })),
  addSeats: (subscriptionId: string, seats: number) => request<WireCharge>(`${sub(subscriptionId)}/seats`, post({ seats })),
  /** `extraSeats` is the new total from the next renewal, not a delta (06 `SeatReductionRequest`). */
  reduceSeats: (subscriptionId: string, extraSeats: number) =>
    request<WireSeats>(`${sub(subscriptionId)}/seats/pending`, { method: "PUT", body: JSON.stringify({ extraSeats }) }),
}

export const billingKeys = {
  all: ["billing"] as const,
  catalogue: ["billing", "catalogue"] as const,
  summary: (beneficiaryId: string | null) => ["billing", "summary", beneficiaryId ?? "me"] as const,
  payment: (paymentId: string) => ["billing", "payment", paymentId] as const,
  receipts: ["billing", "receipts"] as const,
  autoTopup: (beneficiaryId: string | null) => ["billing", "auto-topup", beneficiaryId ?? "me"] as const,
  cards: ["billing", "cards"] as const,
}

export const PAYMENT_POLL_MS = 2000
export const PAYMENT_POLL_LIMIT_MS = 180_000

/** Poll while the payment is unconfirmed, for at most three minutes. Pure, for tests. */
export function nextPaymentPoll(status: PaymentStatus | undefined, startedAt: number, now: number): number | false {
  if (status !== undefined && status !== "created" && status !== "pending") return false
  return now - startedAt < PAYMENT_POLL_LIMIT_MS ? PAYMENT_POLL_MS : false
}

/** One catalogue request; each audience is a `select` over it. */
export function useCatalogue(audience: Audience): UseQueryResult<Catalogue, Error> {
  return useQuery({ queryKey: billingKeys.catalogue, queryFn: billingApi.catalogue, select: (w) => toCatalogue(w, audience) })
}

export function useBillingSummary(beneficiaryId: string | null = null): UseQueryResult<BillingSummary, Error> {
  return useQuery({ queryKey: billingKeys.summary(beneficiaryId), queryFn: () => billingApi.summary(beneficiaryId), select: toBillingSummary })
}

/**
 * `GET /billing/payments/{id}`, polled every 2s while `created`/`pending`, for three minutes at
 * most (spec §5.1 step 5). `pollingStopped` turns true when the limit ends polling on an
 * unconfirmed payment, so the screen can say so.
 */
export function usePaymentStatus(paymentId: string | null): UseQueryResult<PaymentStatusView, Error> & { pollingStopped: boolean } {
  const startedAt = useRef(Date.now())
  const query = useQuery({
    queryKey: billingKeys.payment(paymentId ?? ""),
    queryFn: () => billingApi.payment(paymentId ?? ""),
    enabled: paymentId !== null,
    refetchInterval: (q) => nextPaymentPoll(q.state.data?.status, startedAt.current, Date.now()),
  })
  const status = query.data?.status
  const pollingStopped =
    (status === "created" || status === "pending") && nextPaymentPoll(status, startedAt.current, Date.now()) === false
  return Object.assign(query, { pollingStopped })
}

export function useStartSubscriptionCheckout(): UseMutationResult<CheckoutResponse, Error, SubscriptionCheckoutRequest> {
  return useMutation({
    mutationFn: async (body) => {
      const w = await billingApi.startSubscriptionCheckout(body)
      return { paymentId: w.paymentId, checkoutUrl: w.checkoutUrl }
    },
  })
}

export function useStartPackCheckout(): UseMutationResult<CheckoutResponse, Error, PackCheckoutRequest> {
  return useMutation({ mutationFn: billingApi.startPackCheckout })
}

type PlanTarget = { subscriptionId: string; planTierId: string }

export function useUpgradeQuote(): UseMutationResult<Quote, Error, PlanTarget> {
  return useMutation({ mutationFn: ({ subscriptionId, planTierId }) => billingApi.upgradeQuote(subscriptionId, planTierId) })
}

/** 202 `ChargeDTO`: poll its `paymentId` (spec §5.3). */
export function useUpgrade(): UseMutationResult<WireCharge, Error, PlanTarget> {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ subscriptionId, planTierId }) => billingApi.upgrade(subscriptionId, planTierId),
    onSuccess: () => qc.invalidateQueries({ queryKey: billingKeys.all }),
  })
}

/** Returns the subscription; the downgrade applies at its `currentPeriodEnd`. */
export function useDowngrade(): UseMutationResult<WireSubscription, Error, PlanTarget> {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ subscriptionId, planTierId }) => billingApi.downgrade(subscriptionId, planTierId),
    onSuccess: () => qc.invalidateQueries({ queryKey: billingKeys.all }),
  })
}

/** Returns the subscription; access ends at its `currentPeriodEnd`. */
export function useCancelSubscription(): UseMutationResult<WireSubscription, Error, { subscriptionId: string }> {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ subscriptionId }) => billingApi.cancel(subscriptionId),
    onSuccess: () => qc.invalidateQueries({ queryKey: billingKeys.all }),
  })
}

export function useReceipts(): UseQueryResult<{ receipts: Receipt[] }, Error> {
  return useQuery({ queryKey: billingKeys.receipts, queryFn: billingApi.receipts })
}

export function useAutoTopup(beneficiaryId: string | null = null): UseQueryResult<AutoTopupSettings, Error> {
  return useQuery({ queryKey: billingKeys.autoTopup(beneficiaryId), queryFn: () => billingApi.autoTopup(beneficiaryId), select: toAutoTopup })
}

export function useSaveAutoTopup(): UseMutationResult<WireAutoTopup, Error, AutoTopupUpdate> {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: billingApi.saveAutoTopup,
    onSuccess: (data, body) => qc.setQueryData(billingKeys.autoTopup(body.beneficiaryId), data),
  })
}

export function useSavedCards(): UseQueryResult<{ cards: SavedCardView[] }, Error> {
  return useQuery({
    queryKey: billingKeys.cards,
    queryFn: billingApi.cards,
    select: (w) => ({ cards: w.cards.flatMap((c) => toSavedCard(c) ?? []) }),
  })
}

export function useSeatQuote(): UseMutationResult<Quote, Error, { subscriptionId: string; seats: number }> {
  return useMutation({ mutationFn: ({ subscriptionId, seats }) => billingApi.seatQuote(subscriptionId, seats) })
}

export function useAddSeats(): UseMutationResult<MerchantChargeStarted, Error, { subscriptionId: string; seats: number }> {
  return useMutation({ mutationFn: ({ subscriptionId, seats }) => billingApi.addSeats(subscriptionId, seats) })
}

export function useReduceSeats(): UseMutationResult<SeatReductionResult, Error, { subscriptionId: string; extraSeats: number }> {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ subscriptionId, extraSeats }) => billingApi.reduceSeats(subscriptionId, extraSeats),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: billingKeys.all })
      void qc.invalidateQueries({ queryKey: ["team"] })
    },
  })
}
```

- [ ] **Step 12: Write `web/src/lib/hooks/useUsageApi.ts`**

```ts
import {
  useInfiniteQuery,
  useQuery,
  type InfiniteData,
  type QueryClient,
  type UseInfiniteQueryResult,
  type UseQueryResult,
} from "@tanstack/react-query"
import { request } from "@/lib/api"
import { toEstimate, toUsageJob, toUsageMeter } from "@/lib/billingAdapters"
import type {
  EstimateRequest,
  EstimateResponse,
  UsageHistoryPage,
  UsageMeterView,
  WireEstimate,
  WireUsageHistory,
  WireUsageMeter,
} from "@/lib/billingTypes"

/*
 * React-query hooks over `/api/usage/*` (plan 04). The estimate writes nothing server-side
 * (spec §5.7 step 1), so it is a query keyed by the request: the same request on the same screen
 * reuses the answer for a minute. Meter and history serve the caller only (M6); a parent reads a
 * child's meter through the billing summary.
 */

export const usageApi = {
  estimate: (body: EstimateRequest) => request<WireEstimate>("/usage/estimate", { method: "POST", body: JSON.stringify(body) }),
  meter: () => request<WireUsageMeter>("/usage/meter"),
  history: (cursor: string | null) => {
    const params = new URLSearchParams({ limit: "25" })
    if (cursor) params.set("cursor", cursor)
    return request<WireUsageHistory>(`/usage/history?${params.toString()}`)
  },
}

export const usageKeys = {
  all: ["usage"] as const,
  estimate: (body: EstimateRequest) => ["usage", "estimate", body] as const,
  meter: ["usage", "meter"] as const,
  history: ["usage", "history"] as const,
}

/** `null` request = nothing to estimate yet; the query stays idle. */
export function useUsageEstimate(body: EstimateRequest | null): UseQueryResult<EstimateResponse, Error> {
  return useQuery({
    queryKey: body ? usageKeys.estimate(body) : ["usage", "estimate", "idle"],
    queryFn: async () => toEstimate(await usageApi.estimate(body as EstimateRequest)),
    enabled: body !== null,
    staleTime: 60_000,
    retry: false,
  })
}

export function useUsageMeter(): UseQueryResult<UsageMeterView, Error> {
  return useQuery({ queryKey: usageKeys.meter, queryFn: usageApi.meter, select: toUsageMeter })
}

export function useUsageHistory(): UseInfiniteQueryResult<InfiniteData<UsageHistoryPage, string | null>, Error> {
  return useInfiniteQuery({
    queryKey: usageKeys.history,
    queryFn: async ({ pageParam }) => {
      const w = await usageApi.history(pageParam)
      return { jobs: w.jobs.map(toUsageJob), nextCursor: w.nextCursor }
    },
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.nextCursor,
  })
}

/** After a metered action settles: meter, credits, history and summaries all moved. */
export function invalidateUsage(queryClient: QueryClient): void {
  void queryClient.invalidateQueries({ queryKey: usageKeys.all })
  void queryClient.invalidateQueries({ queryKey: ["billing", "summary"] })
}
```

- [ ] **Step 13: Run the fetcher tests to verify they pass**

Run: `npx vitest run tests/unit/billingApi.test.ts tests/unit/billingFormat.test.ts tests/unit/usageBlock.test.ts tests/unit/billingAdapters.test.ts`
Expected: PASS (4 files).

- [ ] **Step 14: Write the shared test support files**

`web/tests/unit/support/billingRender.ts`:

```ts
import { createElement as h, type ReactElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { MemoryRouter, Route, Routes } from "react-router-dom"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { vi } from "vitest"

/*
 * Static-render helpers for billing component tests. The web runner is `environment: "node"`
 * with no jsdom (D3.20), so components render to markup with `react-dom/server` and hooks are
 * replaced with these fake query/mutation objects through `vi.mock`.
 */

function client(): QueryClient {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } })
}

export function renderStatic(el: ReactElement, path = "/"): string {
  return renderToStaticMarkup(h(QueryClientProvider, { client: client() }, h(MemoryRouter, { initialEntries: [path] }, el)))
}

/** Render `el` as the element of route `pattern`, visited at `url` (for `useParams`). */
export function renderAt(el: ReactElement, pattern: string, url: string): string {
  return renderToStaticMarkup(
    h(QueryClientProvider, { client: client() }, h(MemoryRouter, { initialEntries: [url] }, h(Routes, null, h(Route, { path: pattern, element: el })))),
  )
}

const base = { refetch: () => undefined, isFetching: false, isLoading: false, isRefetching: false }

export function okQuery<T>(data: T) {
  return { ...base, status: "success" as const, fetchStatus: "idle" as const, data, error: null, isPending: false, isError: false, isSuccess: true }
}

export function pendingQuery() {
  return { ...base, status: "pending" as const, fetchStatus: "fetching" as const, data: undefined, error: null, isPending: true, isError: false, isSuccess: false, isLoading: true }
}

export function errorQuery(error: unknown) {
  return { ...base, status: "error" as const, fetchStatus: "idle" as const, data: undefined, error, isPending: false, isError: true, isSuccess: false }
}

export function fakeMutation<T = unknown>(over: Partial<{ isPending: boolean; isError: boolean; isSuccess: boolean; error: unknown; data: T }> = {}) {
  return {
    mutate: vi.fn(),
    mutateAsync: vi.fn(),
    reset: vi.fn(),
    isPending: false,
    isError: false,
    isSuccess: false,
    isIdle: true,
    error: null as unknown,
    data: undefined as T | undefined,
    ...over,
  }
}
```

`web/tests/unit/support/billingFixtures.ts` (view-type fixtures; Tasks 11 and 13 append team and
admin fixtures to the same `fx` object):

```ts
import type {
  AutoTopupSettings,
  BillingSummary,
  Catalogue,
  EstimateResponse,
  PaymentStatusView,
  PlanTier,
  Receipt,
  SubscriptionView,
  UsageHistoryPage,
  UsageJobRow,
  UsageMeterView,
} from "@/lib/billingTypes"

const studentMonthly: PlanTier = {
  id: "t-s-m",
  code: "student_plus_m",
  name: "Student Plus",
  audience: "student",
  interval: "month",
  priceMinor: 25000,
  currency: "EGP",
  features: ["Mark past papers", "Study plans"],
  includedSeats: null,
  extraSeatPriceMinor: null,
}
const studentYearly: PlanTier = { ...studentMonthly, id: "t-s-y", code: "student_plus_y", interval: "year", priceMinor: 250000 }
const teacherMonthly: PlanTier = {
  ...studentMonthly,
  id: "t-t-m",
  code: "teacher_pro_m",
  name: "Teacher Pro",
  audience: "teacher",
  priceMinor: 90000,
  includedSeats: 20,
  extraSeatPriceMinor: 3000,
}
const teacherMax: PlanTier = { ...teacherMonthly, id: "t-t-max", code: "teacher_max_m", name: "Teacher Max", priceMinor: 150000, includedSeats: 40 }

const activeSub: SubscriptionView = {
  subscriptionId: "sub1",
  status: "active",
  tier: studentMonthly,
  currentPeriodStart: "2026-11-01T00:00:00Z",
  currentPeriodEnd: "2026-12-01T00:00:00Z",
  cancelAtPeriodEnd: false,
  pendingTier: null,
  graceUntil: null,
  extraSeats: 0,
  pendingExtraSeats: null,
}

const estimate: EstimateResponse = { low: 30, high: 60, payer: "allowance", percentLow: 2, percentHigh: 4, blockedReason: null }

const meter: UsageMeterView = {
  allowance: { fraction: 0.63, resetsAt: "2026-12-01T00:00:00Z" },
  seats: [],
  credits: {
    total: 700,
    buckets: [
      { key: "0-2027-10-02", remaining: 500, expiresAt: "2027-10-02T00:00:00Z" },
      { key: "1-2026-12-05", remaining: 200, expiresAt: "2026-12-05T00:00:00Z" },
    ],
  },
  debtUnits: 0,
}

const job: UsageJobRow = {
  jobId: "j1",
  action: "mark_paper",
  status: "settled",
  paidBy: "credits",
  percentOfPlan: null,
  credits: 4,
  debtCredits: null,
  estimatePercentOfPlan: null,
  estimateCredits: [3, 5],
  actorUserId: "u2",
  createdAt: "2026-11-03T10:00:00Z",
  settledAt: "2026-11-03T10:02:00Z",
}

const receipt: Receipt = {
  paymentId: "pay1",
  purpose: "credit_pack",
  status: "paid",
  amountMinor: 15000,
  currency: "EGP",
  paidAt: "2026-11-02T09:00:00Z",
  description: "500 credits",
  beneficiaryId: "u2",
}

const payment: PaymentStatusView = {
  paymentId: "pay1",
  status: "pending",
  purpose: "credit_pack",
  amountMinor: 15000,
  currency: "EGP",
  description: "500 credits",
  paidAt: null,
}

// "Not set up" exactly as plan 06 sends it.
const autoTopup: AutoTopupSettings = {
  beneficiaryId: "u2",
  enabled: false,
  thresholdUnits: null,
  creditPackId: null,
  savedCardId: null,
  monthlyCapMinor: null,
  spentThisMonthMinor: 0,
  currency: "EGP",
  disabledReason: null,
}

const summary: BillingSummary = {
  beneficiary: { userId: "u2", displayName: "Omar Hassan", audience: "student" },
  subscription: activeSub,
  canManage: true,
  managedByName: null,
  savedCard: { cardId: "card1", maskedPan: "•••• 2346", brand: "Mastercard" },
  meter,
  seats: null,
}

const studentCatalogue: Catalogue = {
  audience: "student",
  tiers: [studentMonthly, studentYearly],
  packs: [{ id: "p1", code: "pack_500", name: "500 credits", units: 500, priceMinor: 15000, currency: "EGP" }],
}
const teacherCatalogue: Catalogue = { audience: "teacher", tiers: [teacherMonthly, teacherMax], packs: studentCatalogue.packs }

const history: UsageHistoryPage = { jobs: [job], nextCursor: null }

export const fx = {
  studentMonthly,
  studentYearly,
  teacherMonthly,
  teacherMax,
  activeSub,
  summary,
  estimate,
  meter,
  job,
  history,
  receipt,
  payment,
  autoTopup,
  studentCatalogue,
  teacherCatalogue,
}
```

- [ ] **Step 15: Run the frontend gate**

Run from `web/`:
```bash
npm run typecheck
npx vitest run tests/unit/billingFormat.test.ts tests/unit/usageBlock.test.ts tests/unit/billingAdapters.test.ts tests/unit/billingApi.test.ts $SCAN
npm run lint
npm run check:copy
npm run build
```
Expected: every command exits 0.

- [ ] **Step 16: Commit**

```bash
cd /home/sico/Code/Lemely/.claude/worktrees/paymob-integration
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files
graphify update .
P="web/src/lib/billingTypes.ts web/src/lib/billingAdapters.ts web/src/lib/billingFormat.ts web/src/lib/usageBlock.ts web/src/lib/billingOutcome.ts web/src/lib/billingPaths.ts web/src/lib/hooks/useBillingApi.ts web/src/lib/hooks/useUsageApi.ts web/tests/unit/support/billingFixtures.ts web/tests/unit/support/billingRender.ts web/tests/unit/billingFormat.test.ts web/tests/unit/usageBlock.test.ts web/tests/unit/billingAdapters.test.ts web/tests/unit/billingApi.test.ts"
git add $P
git commit -S -m "feat(web): billing data layer, adapters and 402 parsing" -- $P
```

---

### Task 2: Usage meter, credit balance and debt notice

**Files:**
- Create: `web/src/lib/usageMeterModel.ts`
- Create: `web/src/components/billing/usage-meter.tsx`
- Create: `web/src/components/billing/credit-balance.tsx`
- Create: `web/src/components/billing/debt-notice.tsx`
- Test: `web/tests/unit/usageMeterModel.test.ts`, `web/tests/unit/billingMeters.test.ts`

**Interfaces:**
- Consumes (Task 1): `AllowanceMeter`, `SeatMeter`, `CreditBucket`, `CreditBalance`,
  `UsageMeterView`, `Audience` types; `formatBillingDate`, `formatCredits`; `fx`,
  `renderStatic` test helpers.
- Produces:
  - `allowanceMeterModel(meter: AllowanceMeter, locale?: string): MeterModel`,
    `seatMeterModel(seat: SeatMeter, locale?: string): MeterModel`,
    `creditExpiryLines(buckets: CreditBucket[], now: Date, locale?: string): CreditExpiryLine[]`,
    `debtSentence(debtUnits: number, audience: Audience): string | null`, types `MeterModel`,
    `CreditExpiryLine`;
  - `<UsageMeterCard meter={UsageMeterView} />`, `<CreditBalanceCard credits={CreditBalance}
    now={Date} buyHref={string | null} />`, `<DebtNotice debtUnits={number}
    audience={Audience} buyHref={string | null} />`.

States (all asserted by tests):

| Component | State | What renders |
|---|---|---|
| `UsageMeterCard` | allowance under 80% | bar, "Usage 63%, resets 1 Dec 2026", no note |
| | allowance 80–99% | bar plus "Most of this month's plan is used." |
| | allowance ≥ 100% | full bar plus "This month's plan is used up. Credits pay from here." (accent fill, never `error`) |
| | seat meters | one bar per seat: "Seat from your teacher: 40% used", reset date underneath (M4: no teacher name in the DTO) |
| | no allowance, no seats | "No plan allowance. Usage comes from your credits." |
| `CreditBalanceCard` | credits | total in data type; one line per expiry date, soonest first, "never expire" last; lines within 30 days carry "Expires soon" |
| | zero credits | "No credits yet." plus a "Buy credits" link when `buyHref` is set |
| `DebtNotice` | debt 0 | renders nothing |
| | debt > 0 | `role="status"` panel, neutral warning tone (not crimson, not gold), the debt sentence and a "Buy credits" link when `buyHref` is set |

- [ ] **Step 1: Write the failing model test**

`web/tests/unit/usageMeterModel.test.ts`:

```ts
import { describe, expect, it } from "vitest"
import {
  allowanceMeterModel,
  creditExpiryLines,
  debtSentence,
  seatMeterModel,
} from "@/lib/usageMeterModel"

const resetsAt = "2026-12-01T00:00:00Z"

describe("allowanceMeterModel", () => {
  it("labels usage with the reset date and bands the note", () => {
    expect(allowanceMeterModel({ fraction: 0.63, resetsAt }, "en-GB")).toEqual({
      percent: 63,
      barValue: 63,
      label: "Usage 63%, resets 1 Dec 2026",
      note: null,
      state: "ok",
    })
    expect(allowanceMeterModel({ fraction: 0.85, resetsAt }, "en-GB").state).toBe("high")
    expect(allowanceMeterModel({ fraction: 0.85, resetsAt }, "en-GB").note).toBe(
      "Most of this month's plan is used.",
    )
    const used = allowanceMeterModel({ fraction: 1.02, resetsAt }, "en-GB")
    expect(used).toMatchObject({ percent: 102, barValue: 100, state: "used_up" })
    expect(used.note).toBe("This month's plan is used up. Credits pay from here.")
  })
})

describe("seatMeterModel", () => {
  it("labels a seat meter without a teacher name (M4) and handles a seat not granted yet", () => {
    const m = seatMeterModel({ teacherMemberId: "m1", teacherUserId: "u9", fraction: 0.4, resetsAt }, "en-GB")
    expect(m.label).toBe("Seat from your teacher: 40% used")
    expect(m.note).toBe("Resets 1 Dec 2026.")
    const fresh = seatMeterModel({ teacherMemberId: "m1", teacherUserId: "u9", fraction: null, resetsAt: null }, "en-GB")
    expect(fresh).toMatchObject({ percent: 0, label: "Seat from your teacher: 0% used", note: "This month's seat allowance starts with your first job." })
  })
})

describe("creditExpiryLines", () => {
  const now = new Date("2026-11-05T00:00:00Z")

  it("sums buckets per expiry day, sorts soonest first, never-expiring last, and drops empties", () => {
    const lines = creditExpiryLines(
      [
        { key: "a", remaining: 300, expiresAt: "2027-10-02T10:00:00Z" },
        { key: "b", remaining: 200, expiresAt: "2027-10-02T18:00:00Z" },
        { key: "c", remaining: 50, expiresAt: null },
        { key: "d", remaining: 100, expiresAt: "2026-11-20T00:00:00Z" },
        { key: "e", remaining: 0, expiresAt: "2026-11-10T00:00:00Z" },
      ],
      now,
      "en-GB",
    )
    expect(lines).toEqual([
      { key: "2026-11-20", units: 100, label: "100 credits expire 20 Nov 2026", soon: true },
      { key: "2027-10-02", units: 500, label: "500 credits expire 2 Oct 2027", soon: false },
      { key: "never", units: 50, label: "50 credits never expire", soon: false },
    ])
  })
})

describe("debtSentence", () => {
  it("returns null with no debt and a role-voiced sentence otherwise", () => {
    expect(debtSentence(0, "student")).toBeNull()
    expect(debtSentence(12, "student")).toBe(
      "A recent job cost 12 credits more than your balance. New work that uses your own balance is paused until your next credit pack or plan renewal clears it.",
    )
    expect(debtSentence(1, "teacher")).toBe(
      "A recent job cost 1 credit more than the balance. New jobs on this balance are paused until the next pack or renewal clears it.",
    )
  })
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npx vitest run tests/unit/usageMeterModel.test.ts`
Expected: FAIL, "Failed to resolve import "@/lib/usageMeterModel"".

- [ ] **Step 3: Write `web/src/lib/usageMeterModel.ts`**

```ts
import { formatBillingDate, formatCredits } from "@/lib/billingFormat"
import type { AllowanceMeter, Audience, CreditBucket, SeatMeter } from "@/lib/billingTypes"

/*
 * View models for the usage meter, the credit balance and the debt notice. Pure, so every
 * band and sentence is unit-tested; the components only lay them out.
 *
 * "Used up" is deliberately not an error state: running through an allowance is the plan
 * working as designed (spec §2.1), and crimson means lost marks or genuine errors only
 * (DESIGN.md "The Red Means Lost Rule").
 */

export interface MeterModel {
  percent: number
  /** Clamped 0..100 for the bar. */
  barValue: number
  label: string
  note: string | null
  state: "ok" | "high" | "used_up"
}

function band(percent: number): MeterModel["state"] {
  if (percent >= 100) return "used_up"
  if (percent >= 80) return "high"
  return "ok"
}

export function allowanceMeterModel(meter: AllowanceMeter, locale?: string): MeterModel {
  const percent = Math.max(0, Math.round(meter.fraction * 100))
  const state = band(percent)
  return {
    percent,
    barValue: Math.min(100, percent),
    label: `Usage ${percent}%, resets ${formatBillingDate(meter.resetsAt, locale)}`,
    note:
      state === "used_up"
        ? "This month's plan is used up. Credits pay from here."
        : state === "high"
          ? "Most of this month's plan is used."
          : null,
    state,
  }
}

/** `SeatMeterDTO` carries no teacher name or subjects (M4). */
export function seatMeterModel(seat: SeatMeter, locale?: string): MeterModel {
  const percent = Math.max(0, Math.round((seat.fraction ?? 0) * 100))
  return {
    percent,
    barValue: Math.min(100, percent),
    label: `Seat from your teacher: ${percent}% used`,
    note: seat.resetsAt
      ? `Resets ${formatBillingDate(seat.resetsAt, locale)}.`
      : "This month's seat allowance starts with your first job.",
    state: band(percent),
  }
}

export interface CreditExpiryLine {
  key: string
  units: number
  label: string
  soon: boolean
}

const SOON_MS = 30 * 24 * 60 * 60 * 1000

export function creditExpiryLines(buckets: CreditBucket[], now: Date, locale?: string): CreditExpiryLine[] {
  const byDay = new Map<string, { units: number; at: string | null }>()
  for (const b of buckets) {
    if (b.remaining <= 0) continue
    const key = b.expiresAt === null ? "never" : b.expiresAt.slice(0, 10)
    const prev = byDay.get(key)
    byDay.set(key, { units: (prev?.units ?? 0) + b.remaining, at: b.expiresAt })
  }
  return [...byDay.entries()]
    .sort(([a], [b]) => (a === "never" ? 1 : b === "never" ? -1 : a.localeCompare(b)))
    .map(([key, { units, at }]) => ({
      key,
      units,
      label:
        at === null
          ? `${formatCredits(units, locale)} never expire`
          : `${formatCredits(units, locale)} expire ${formatBillingDate(at, locale)}`,
      soon: at !== null && new Date(at).getTime() - now.getTime() <= SOON_MS,
    }))
}

export function debtSentence(debtUnits: number, audience: Audience): string | null {
  if (debtUnits <= 0) return null
  const amount = formatCredits(debtUnits)
  return audience === "student"
    ? `A recent job cost ${amount} more than your balance. New work that uses your own balance is paused until your next credit pack or plan renewal clears it.`
    : `A recent job cost ${amount} more than the balance. New jobs on this balance are paused until the next pack or renewal clears it.`
}
```

- [ ] **Step 4: Run it to verify it passes**

Run: `npx vitest run tests/unit/usageMeterModel.test.ts`
Expected: PASS.

- [ ] **Step 5: Write the failing component test**

`web/tests/unit/billingMeters.test.ts`:

```ts
import { createElement as h } from "react"
import { describe, expect, it } from "vitest"
import { CreditBalanceCard } from "@/components/billing/credit-balance"
import { DebtNotice } from "@/components/billing/debt-notice"
import { UsageMeterCard } from "@/components/billing/usage-meter"
import { fx } from "./support/billingFixtures"
import { renderStatic } from "./support/billingRender"

const now = new Date("2026-11-05T00:00:00Z")

describe("UsageMeterCard", () => {
  it("renders the allowance bar with an accessible name and no note under 80%", () => {
    const html = renderStatic(h(UsageMeterCard, { meter: fx.meter }))
    expect(html).toContain('role="progressbar"')
    expect(html).toMatch(/Usage 63%, resets/)
    expect(html).not.toContain("Most of this month")
  })

  it("says credits pay once the plan is used up, without an error fill", () => {
    const html = renderStatic(
      h(UsageMeterCard, { meter: { ...fx.meter, allowance: { fraction: 1, resetsAt: "2026-12-01T00:00:00Z" } } }),
    )
    expect(html).toContain("Credits pay from here.")
    expect(html).not.toContain("bg-error")
  })

  it("lists seat meters and explains a credits-only account", () => {
    const seats = renderStatic(
      h(UsageMeterCard, {
        meter: {
          ...fx.meter,
          allowance: null,
          seats: [
            { teacherMemberId: "m1", teacherUserId: "u9", fraction: 0.4, resetsAt: "2026-12-01T00:00:00Z" },
          ],
        },
      }),
    )
    expect(seats).toContain("Seat from your teacher: 40% used")
    const none = renderStatic(h(UsageMeterCard, { meter: { ...fx.meter, allowance: null, seats: [] } }))
    expect(none).toContain("No plan allowance. Usage comes from your credits.")
  })
})

describe("CreditBalanceCard", () => {
  it("shows the total and the expiry breakdown, soonest first", () => {
    const html = renderStatic(h(CreditBalanceCard, { credits: fx.meter.credits, now, buyHref: "/student/billing/plans#packs" }))
    expect(html).toContain("700")
    expect(html.indexOf("200 credits expire")).toBeLessThan(html.indexOf("500 credits expire"))
    expect(html).toContain("Expires soon")
  })

  it("offers a way to buy when there are no credits, and none when buying is someone else's job", () => {
    const empty = { total: 0, buckets: [] }
    expect(renderStatic(h(CreditBalanceCard, { credits: empty, now, buyHref: "/x#packs" }))).toContain("Buy credits")
    expect(renderStatic(h(CreditBalanceCard, { credits: empty, now, buyHref: null }))).not.toContain("Buy credits")
  })
})

describe("DebtNotice", () => {
  it("renders nothing without debt and a status panel with it", () => {
    expect(renderStatic(h(DebtNotice, { debtUnits: 0, audience: "student", buyHref: null }))).toBe("")
    const html = renderStatic(h(DebtNotice, { debtUnits: 12, audience: "student", buyHref: "/x#packs" }))
    expect(html).toContain('role="status"')
    expect(html).toContain("12 credits more than your balance")
    expect(html).toContain("Buy credits")
    expect(html).not.toMatch(/bg-error|text-error|tertiary/)
  })
})
```

- [ ] **Step 6: Run it to verify it fails**

Run: `npx vitest run tests/unit/billingMeters.test.ts`
Expected: FAIL, "Failed to resolve import "@/components/billing/credit-balance"".

- [ ] **Step 7: Write the three components**

`web/src/components/billing/usage-meter.tsx`:

```tsx
import { ProgressBar } from "@/components/ui/progress-bar"
import type { UsageMeterView } from "@/lib/billingTypes"
import { allowanceMeterModel, seatMeterModel, type MeterModel } from "@/lib/usageMeterModel"

/*
 * The usage meter (spec §2.1: "Usage 63%, resets 14 Nov"). Allowances are shown only as a
 * share of the plan, never in units: allowance sizes are hidden by design.
 */

function MeterRow({ model }: { model: MeterModel }) {
  return (
    <div className="flex flex-col gap-1.5" data-state={model.state}>
      <ProgressBar value={model.barValue} label={model.label} />
      {model.note ? <p className="m-0 text-body-sm text-on-surface-variant">{model.note}</p> : null}
    </div>
  )
}

export function UsageMeterCard({ meter }: { meter: UsageMeterView }) {
  const hasAny = meter.allowance !== null || meter.seats.length > 0
  return (
    <section aria-labelledby="usage-meter-heading" className="flex flex-col gap-4 rounded-lg border border-outline-variant bg-surface-container-lowest p-5">
      <h2 id="usage-meter-heading" className="m-0 text-display-sm text-on-surface">
        Usage
      </h2>
      {meter.allowance ? <MeterRow model={allowanceMeterModel(meter.allowance)} /> : null}
      {meter.seats.map((seat) => (
        <MeterRow key={seat.teacherMemberId} model={seatMeterModel(seat)} />
      ))}
      {hasAny ? null : (
        <p className="m-0 text-body-sm text-on-surface-variant">No plan allowance. Usage comes from your credits.</p>
      )}
    </section>
  )
}
```

`web/src/components/billing/credit-balance.tsx`:

```tsx
import { Link } from "react-router-dom"
import type { CreditBalance } from "@/lib/billingTypes"
import { creditExpiryLines } from "@/lib/usageMeterModel"

/*
 * Credits are an abstract balance with an expiry breakdown (spec §2.1). Purchased credits
 * expire 12 months after purchase; signup credits for teachers after 30 days. Lines within
 * 30 days of expiry are marked so a payer can spend them first.
 */

export function CreditBalanceCard({
  credits,
  now,
  buyHref,
}: {
  credits: CreditBalance
  now: Date
  buyHref: string | null
}) {
  const lines = creditExpiryLines(credits.buckets, now)
  return (
    <section aria-labelledby="credit-balance-heading" className="flex flex-col gap-3 rounded-lg border border-outline-variant bg-surface-container-lowest p-5">
      <div className="flex items-baseline justify-between gap-3">
        <h2 id="credit-balance-heading" className="m-0 text-display-sm text-on-surface">
          Credits
        </h2>
        <span className="text-data-md text-on-surface" aria-label={`${credits.total} credits`}>
          {new Intl.NumberFormat().format(credits.total)}
        </span>
      </div>
      {lines.length === 0 ? (
        <div className="flex flex-wrap items-center gap-3">
          <p className="m-0 text-body-sm text-on-surface-variant">No credits yet.</p>
          {buyHref ? (
            <Link to={buyHref} className="text-body-sm font-medium text-primary underline-offset-2 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary pointer-coarse:min-h-11 pointer-coarse:inline-flex pointer-coarse:items-center">
              Buy credits
            </Link>
          ) : null}
        </div>
      ) : (
        <ul className="m-0 flex list-none flex-col gap-1.5 p-0">
          {lines.map((line) => (
            <li key={line.key} className="flex items-center justify-between gap-3 text-body-sm text-on-surface">
              <span>{line.label}</span>
              {line.soon ? (
                <span className="rounded-pill bg-surface-container-high px-2.5 py-0.5 text-body-sm text-on-surface">
                  Expires soon
                </span>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
```

`web/src/components/billing/debt-notice.tsx`:

```tsx
import { Warning } from "@phosphor-icons/react"
import { Link } from "react-router-dom"
import type { Audience } from "@/lib/billingTypes"
import { debtSentence } from "@/lib/usageMeterModel"

/*
 * Debt (spec §2.4, §5.8): a job that overran the balance leaves the account negative, and new
 * jobs on that balance wait until the next grant repays it. A neutral warning, not crimson
 * (PRODUCT.md: students under stress get amber/neutral, never red-heavy states), not gold
 * (nothing here was earned).
 */

export function DebtNotice({
  debtUnits,
  audience,
  buyHref,
}: {
  debtUnits: number
  audience: Audience
  buyHref: string | null
}) {
  const sentence = debtSentence(debtUnits, audience)
  if (sentence === null) return null
  return (
    <div role="status" className="flex items-start gap-3 rounded-lg bg-surface-container-high p-4 text-on-surface">
      <Warning size={20} aria-hidden="true" className="mt-0.5 shrink-0 text-on-surface-variant" />
      <div className="flex flex-col gap-2">
        <p className="m-0 text-body-sm">{sentence}</p>
        {buyHref ? (
          <Link to={buyHref} className="self-start text-body-sm font-medium text-primary underline-offset-2 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary pointer-coarse:min-h-11 pointer-coarse:inline-flex pointer-coarse:items-center">
            Buy credits
          </Link>
        ) : null}
      </div>
    </div>
  )
}
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `npx vitest run tests/unit/usageMeterModel.test.ts tests/unit/billingMeters.test.ts`
Expected: PASS. If `ProgressBar` does not render `role="progressbar"`, read
`web/src/components/ui/progress-bar.tsx` and assert the attribute it does render for its
accessible name instead; do not add a second progressbar.

- [ ] **Step 9: Run the frontend gate**

```bash
npm run typecheck
npx vitest run tests/unit/usageMeterModel.test.ts tests/unit/billingMeters.test.ts $SCAN
npm run lint && npm run check:copy && npm run build
```
Expected: all exit 0.

- [ ] **Step 10: Commit**

```bash
cd /home/sico/Code/Lemely/.claude/worktrees/paymob-integration
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files && graphify update .
git add web/src/lib/usageMeterModel.ts web/src/components/billing/usage-meter.tsx web/src/components/billing/credit-balance.tsx web/src/components/billing/debt-notice.tsx web/tests/unit/usageMeterModel.test.ts web/tests/unit/billingMeters.test.ts
git commit -S -m "feat(web): usage meter, credit balance and debt notice" -- web/src/lib/usageMeterModel.ts web/src/components/billing/usage-meter.tsx web/src/components/billing/credit-balance.tsx web/src/components/billing/debt-notice.tsx web/tests/unit/usageMeterModel.test.ts web/tests/unit/billingMeters.test.ts
```

---

### Task 3: Estimate range and usage-blocked notice

**Files:**
- Create: `web/src/lib/meteredGate.ts`
- Create: `web/src/components/billing/usage-blocked-notice.tsx`
- Create: `web/src/components/billing/estimate-range.tsx`
- Test: `web/tests/unit/meteredGate.test.ts`, `web/tests/unit/estimateRange.test.ts`

**Interfaces:**
- Consumes (Task 1): `EstimateRequest`, `EstimateResponse`, `Audience` types,
  `useUsageEstimate`, `parseUsageBlock`, `UsageBlock`, `usageBlockCopy`, `estimateSentence`,
  `BillingPaths`.
- Produces:
  - `resolveBlock(estimate: EstimateResponse | undefined, caught: CaughtBlock | null,
    requestKey: string | null): UsageBlock | null`, `requestKeyOf(req: EstimateRequest |
    null): string | null`, type `CaughtBlock = { key: string | null; block: UsageBlock }`;
  - `useMeteredGate(request: EstimateRequest | null): MeteredGate` with
    `MeteredGate = { request; estimate: UseQueryResult<EstimateResponse, Error>; block:
    UsageBlock | null; captureError(err: unknown): boolean; clear(): void }`;
  - `<UsageBlockedNotice block audience paths managedByName />`;
  - `<EstimateRange gate audience paths managedByName subjectUnknown? />`.

Behaviour: a job is blocked **before** it starts when the estimate says `blockedReason`, and
**after** a start attempt when the route answers 402. Either way the same notice renders and the
caller disables its start control while `gate.block !== null`. A caught 402 belongs to the
request it was caught for: changing the request (a different file, a different quiz count)
clears it, so a stale block never sits under new input.

| State | `EstimateRange` renders |
|---|---|
| `request === null` | nothing |
| estimate loading | `role="status"` "Working out the cost…" |
| estimate failed (non-402) | "Couldn't estimate the cost right now. You can still start: you're only charged what the job actually costs." |
| estimate ok | "Estimated cost: **3–5 credits**. You're charged the actual cost when it finishes." (+ seat sentence when `subjectUnknown` and the payer is `allowance` or `credits`) |
| blocked (estimate or 402) | `UsageBlockedNotice` |

| `UsageBlockedNotice` next step | When | Renders |
|---|---|---|
| `buy_credits` | `managedByName` set | "Ask {name} to add credits." (no link) |
| `buy_credits` | `paths` set | link "Buy credits" → `paths.packs`; for `usage_limit_reached` also "See plans" → `paths.plans` |
| `see_plans` | `paths` set | link "See plans" → `paths.plans` |
| `ask_teacher` | always | "Ask your lead teacher to raise it." |
| any | `paths` null and no `managedByName` | title and body only |

- [ ] **Step 1: Write the failing tests**

`web/tests/unit/meteredGate.test.ts`:

```ts
import { describe, expect, it } from "vitest"
import { requestKeyOf, resolveBlock } from "@/lib/meteredGate"
import { fx } from "./support/billingFixtures"

const req = { action: "regrade" as const, paperId: "p1" }

describe("resolveBlock", () => {
  it("is null when the estimate allows the job and nothing was caught", () => {
    expect(resolveBlock(fx.estimate, null, requestKeyOf(req))).toBeNull()
    expect(resolveBlock(undefined, null, null)).toBeNull()
  })

  it("blocks from the estimate's reason", () => {
    expect(resolveBlock({ ...fx.estimate, blockedReason: "insufficient_credits" }, null, requestKeyOf(req))).toEqual({
      reason: "insufficient_credits",
      estimate: null,
    })
  })

  it("prefers a 402 caught for the same request, and drops it once the request changes", () => {
    const caught = { key: requestKeyOf(req), block: { reason: "outstanding_debt" as const, estimate: [3, 5] as [number, number] } }
    expect(resolveBlock(fx.estimate, caught, requestKeyOf(req))?.reason).toBe("outstanding_debt")
    const changed = requestKeyOf({ ...req, paperId: "p2" })
    expect(resolveBlock(fx.estimate, caught, changed)).toBeNull()
  })

  it("keys requests by value", () => {
    expect(requestKeyOf(req)).toBe(requestKeyOf({ ...req }))
    expect(requestKeyOf(null)).toBeNull()
  })
})
```

`web/tests/unit/estimateRange.test.ts`:

```ts
import { createElement as h } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { ApiError } from "@/lib/api"
import { billingPaths } from "@/lib/billingPaths"
import { fx } from "./support/billingFixtures"
import { errorQuery, okQuery, pendingQuery, renderStatic } from "./support/billingRender"

const state = vi.hoisted(() => ({ estimate: null as unknown }))
vi.mock("@/lib/hooks/useUsageApi", () => ({ useUsageEstimate: () => state.estimate }))

import { EstimateRange } from "@/components/billing/estimate-range"
import { UsageBlockedNotice } from "@/components/billing/usage-blocked-notice"
import type { MeteredGate } from "@/lib/meteredGate"

const paths = billingPaths({ role: "student" })
const req = { action: "regrade" as const, paperId: "p1" }

function gate(over: Partial<MeteredGate>): MeteredGate {
  return {
    request: req,
    estimate: state.estimate as MeteredGate["estimate"],
    block: null,
    captureError: () => false,
    clear: () => undefined,
    ...over,
  }
}

const render = (g: MeteredGate, extra: Partial<Parameters<typeof EstimateRange>[0]> = {}) =>
  renderStatic(h(EstimateRange, { gate: g, audience: "student", paths, managedByName: null, ...extra }))

beforeEach(() => {
  state.estimate = okQuery(fx.estimate)
})

describe("EstimateRange", () => {
  it("renders nothing without a request", () => {
    expect(render(gate({ request: null }))).toBe("")
  })

  it("announces the loading state", () => {
    state.estimate = pendingQuery()
    expect(render(gate({}))).toMatch(/role="status"[^>]*>.*Working out the cost/)
  })

  it("lets the user start when the estimate fails", () => {
    state.estimate = errorQuery(new ApiError(500, "x"))
    expect(render(gate({}))).toContain("You can still start")
  })

  it("states the range and that the actual cost is charged", () => {
    const html = render(gate({}))
    expect(html).toContain('data-testid="estimate-range"')
    expect(html).toContain("2–4% of your monthly plan")
    expect(html).toContain("charged the actual cost")
  })

  it("warns that a seat may pay when the subject is not known yet", () => {
    state.estimate = okQuery({ ...fx.estimate, payer: "credits" })
    expect(render(gate({}), { subjectUnknown: true })).toContain("seat pays first")
  })

  it("swaps to the blocked notice when blocked", () => {
    const html = render(gate({ block: { reason: "insufficient_credits", estimate: null } }))
    expect(html).toContain('data-testid="usage-blocked-notice"')
    expect(html).not.toContain('data-testid="estimate-range"')
  })
})

describe("UsageBlockedNotice", () => {
  const notice = (
    reason: Parameters<typeof UsageBlockedNotice>[0]["block"]["reason"],
    extra: Partial<Parameters<typeof UsageBlockedNotice>[0]> = {},
  ) =>
    renderStatic(h(UsageBlockedNotice, { block: { reason, estimate: null }, audience: "student", paths, managedByName: null, ...extra }))

  it("is an alert with a next step per reason", () => {
    expect(notice("insufficient_credits")).toContain('role="alert"')
    expect(notice("insufficient_credits")).toContain(`href="${paths.packs}"`)
    expect(notice("no_active_plan")).toContain(`href="${paths.plans}"`)
    const limit = notice("usage_limit_reached")
    expect(limit).toContain(`href="${paths.packs}"`)
    expect(limit).toContain(`href="${paths.plans}"`)
  })

  it("asks the payer instead of linking when someone else manages billing", () => {
    const html = notice("insufficient_credits", { managedByName: "Mona" })
    expect(html).toContain("Ask Mona to add credits.")
    expect(html).not.toContain("href=")
  })

  it("asks the lead teacher for an assistant's cap and shows no links without paths", () => {
    const html = renderStatic(
      h(UsageBlockedNotice, { block: { reason: "out_of_seat_scope", estimate: null }, audience: "teacher", paths: null, managedByName: null }),
    )
    expect(html).toContain("Ask your lead teacher to raise it.")
    expect(html).not.toContain("href=")
  })
})
```

- [ ] **Step 2: Run them to verify they fail**

Run: `npx vitest run tests/unit/meteredGate.test.ts tests/unit/estimateRange.test.ts`
Expected: FAIL, "Failed to resolve import "@/lib/meteredGate"".

- [ ] **Step 3: Write `web/src/lib/meteredGate.ts`**

```ts
import { useCallback, useState } from "react"
import type { UseQueryResult } from "@tanstack/react-query"
import type { EstimateRequest, EstimateResponse } from "@/lib/billingTypes"
import { useUsageEstimate } from "@/lib/hooks/useUsageApi"
import { parseUsageBlock, type UsageBlock } from "@/lib/usageBlock"

/*
 * One gate per metered start control (spec §2.4: estimate first, start only if covered).
 * The estimate can block before the start; the route's 402 can block after. Both feed the
 * same `block`, and the screen disables its start control while `block` is set.
 */

export interface CaughtBlock {
  key: string | null
  block: UsageBlock
}

export interface MeteredGate {
  request: EstimateRequest | null
  estimate: UseQueryResult<EstimateResponse, Error>
  block: UsageBlock | null
  /** Records a 402 usage block and returns true; returns false for any other error. */
  captureError: (err: unknown) => boolean
  clear: () => void
}

export function requestKeyOf(request: EstimateRequest | null): string | null {
  return request === null ? null : JSON.stringify(request)
}

export function resolveBlock(
  estimate: EstimateResponse | undefined,
  caught: CaughtBlock | null,
  requestKey: string | null,
): UsageBlock | null {
  if (caught && caught.key === requestKey) return caught.block
  if (estimate?.blockedReason) return { reason: estimate.blockedReason, estimate: null }
  return null
}

export function useMeteredGate(request: EstimateRequest | null): MeteredGate {
  const estimate = useUsageEstimate(request)
  const [caught, setCaught] = useState<CaughtBlock | null>(null)
  const key = requestKeyOf(request)
  const captureError = useCallback(
    (err: unknown) => {
      const block = parseUsageBlock(err)
      if (block === null) return false
      setCaught({ key, block })
      return true
    },
    [key],
  )
  const clear = useCallback(() => setCaught(null), [])
  return { request, estimate, block: resolveBlock(estimate.data, caught, key), captureError, clear }
}
```

- [ ] **Step 4: Write `web/src/components/billing/usage-blocked-notice.tsx`**

```tsx
import type { ReactNode } from "react"
import { Info } from "@phosphor-icons/react"
import { Link } from "react-router-dom"
import type { Audience } from "@/lib/billingTypes"
import type { BillingPaths } from "@/lib/billingPaths"
import { usageBlockCopy, type UsageBlock } from "@/lib/usageBlock"

/*
 * What a blocked metered action says, and the one next step it offers (spec §2.4, 402
 * reasons). `role="alert"` because it replaces an action the user just tried or was about to
 * try. Neutral tone: a missing balance is not an error in the user's work.
 */

const LINK =
  "inline-flex items-center rounded-button px-4 py-2 text-label font-medium focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary pointer-coarse:min-h-11"

export function UsageBlockedNotice({
  block,
  audience,
  paths,
  managedByName,
}: {
  block: UsageBlock
  audience: Audience
  paths: BillingPaths | null
  managedByName: string | null
}) {
  const copy = usageBlockCopy(block.reason, audience)
  let next: ReactNode = null
  if (copy.next === "ask_teacher") {
    next = <p className="m-0 text-body-sm text-on-surface">Ask your lead teacher to raise it.</p>
  } else if (managedByName) {
    next = <p className="m-0 text-body-sm text-on-surface">Ask {managedByName} to add credits.</p>
  } else if (paths && copy.next === "buy_credits") {
    next = (
      <div className="flex flex-wrap gap-2">
        <Link to={paths.packs} className={`${LINK} bg-primary text-on-primary hover:bg-primary-hover`}>
          Buy credits
        </Link>
        {block.reason === "usage_limit_reached" ? (
          <Link to={paths.plans} className={`${LINK} bg-primary-container text-on-primary-container`}>
            See plans
          </Link>
        ) : null}
      </div>
    )
  } else if (paths && copy.next === "see_plans") {
    next = (
      <Link to={paths.plans} className={`${LINK} self-start bg-primary text-on-primary hover:bg-primary-hover`}>
        See plans
      </Link>
    )
  }
  return (
    <div
      role="alert"
      data-testid="usage-blocked-notice"
      data-reason={block.reason}
      className="flex items-start gap-3 rounded-lg bg-surface-container-high p-4 text-on-surface"
    >
      <Info size={20} aria-hidden="true" className="mt-0.5 shrink-0 text-on-surface-variant" />
      <div className="flex flex-col gap-2">
        <h3 className="m-0 text-body-md font-semibold">{copy.title}</h3>
        <p className="m-0 text-body-sm text-on-surface-variant">{copy.body}</p>
        {next}
      </div>
    </div>
  )
}
```

- [ ] **Step 5: Write `web/src/components/billing/estimate-range.tsx`**

```tsx
import type { Audience } from "@/lib/billingTypes"
import { estimateSentence } from "@/lib/billingFormat"
import type { BillingPaths } from "@/lib/billingPaths"
import type { MeteredGate } from "@/lib/meteredGate"
import { UsageBlockedNotice } from "./usage-blocked-notice"

/*
 * The estimate shown before every metered action (spec §2.4, §5.7 step 1). The range is a
 * promise about the top only: the job starts if the balance covers the top, and charges the
 * actual cost when it ends. `subjectUnknown` is for upload screens, where the server cannot
 * yet route the job to a teacher's seat because the paper's subject is detected later.
 */

export function EstimateRange({
  gate,
  audience,
  paths,
  managedByName,
  subjectUnknown = false,
}: {
  gate: MeteredGate
  audience: Audience
  paths: BillingPaths | null
  managedByName: string | null
  subjectUnknown?: boolean
}) {
  if (gate.request === null) return null
  if (gate.block) {
    return <UsageBlockedNotice block={gate.block} audience={audience} paths={paths} managedByName={managedByName} />
  }
  const { estimate } = gate
  if (estimate.isPending) {
    return (
      <p role="status" className="m-0 text-body-sm text-on-surface-variant">
        Working out the cost…
      </p>
    )
  }
  if (estimate.isError || !estimate.data) {
    return (
      <p className="m-0 text-body-sm text-on-surface-variant">
        Couldn't estimate the cost right now. You can still start: you're only charged what the job actually costs.
      </p>
    )
  }
  const data = estimate.data
  const ownPayer = data.payer === "allowance" || data.payer === "credits"
  return (
    <p data-testid="estimate-range" className="m-0 text-body-sm text-on-surface-variant">
      Estimated cost: <span className="text-data-sm text-on-surface">{estimateSentence(data)}</span>. You're
      charged the actual cost when it finishes.
      {subjectUnknown && ownPayer ? " If a teacher's seat covers this paper's subject, the seat pays first." : null}
    </p>
  )
}
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `npx vitest run tests/unit/meteredGate.test.ts tests/unit/estimateRange.test.ts`
Expected: PASS.

- [ ] **Step 7: Run the frontend gate**

```bash
npm run typecheck
npx vitest run tests/unit/meteredGate.test.ts tests/unit/estimateRange.test.ts $SCAN
npm run lint && npm run check:copy && npm run build
```
Expected: all exit 0.

- [ ] **Step 8: Commit**

```bash
cd /home/sico/Code/Lemely/.claude/worktrees/paymob-integration
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files && graphify update .
git add web/src/lib/meteredGate.ts web/src/components/billing/usage-blocked-notice.tsx web/src/components/billing/estimate-range.tsx web/tests/unit/meteredGate.test.ts web/tests/unit/estimateRange.test.ts
git commit -S -m "feat(web): estimate range and usage-blocked notice" -- web/src/lib/meteredGate.ts web/src/components/billing/usage-blocked-notice.tsx web/src/components/billing/estimate-range.tsx web/tests/unit/meteredGate.test.ts web/tests/unit/estimateRange.test.ts
```

---

### Task 4: Plans page, checkout redirect and checkout return page

**Files:**
- Create: `web/src/lib/checkoutReturn.ts`
- Create: `web/src/portals/billing/PlansView.tsx`
- Create: `web/src/portals/billing/PlansScreen.tsx`
- Create: `web/src/portals/billing/CheckoutReturn.tsx`
- Modify: `web/src/routes.tsx` (add `/billing/return/:paymentId` and `/billing`)
- Modify: `web/src/portals/student/index.tsx` (route `billing/plans`)
- Modify: `web/src/portals/teacher/index.tsx` (route `billing/plans`)
- Modify: `web/src/portals/parent/index.tsx` (route `children/:childId/billing/plans`)
- Test: `web/tests/unit/checkoutReturn.test.ts`, `web/tests/unit/billingPurchase.test.ts`
- E2E: `web/e2e/billing-purchase.spec.ts`

**Interfaces:**
- Consumes (Task 1): `useCatalogue`, `useBillingSummary`, `useStartSubscriptionCheckout`,
  `useStartPackCheckout`, `usePaymentStatus`, `billingPaths`, `BillingPaths`,
  `billingFailureMessage`, `formatMoney`, `formatCredits`, `intervalLabel`,
  `isLiveSubscription`, `paymentPhase`, `PaymentPhase`, types `Audience`, `BillingInterval`,
  `CheckoutResponse`, `PaymentPurpose`, `PlanTier`, `CreditPack`.
- Produces:
  - `rememberReturnTo(paymentId, path, storage?)`, `returnToFor(paymentId, fallback, storage?)`,
    `defaultBillingPath(role: string | undefined): string`, `isSafeCheckoutUrl(url): boolean`,
    `startCheckoutRedirect(res: CheckoutResponse, returnTo: string, go?: (url: string) => void):
    boolean`, `returnCopy(phase, purpose, pollingStopped): ReturnCopy`;
  - `<PlansView audience beneficiaryId paths currentTierId hasLiveSubscription canManage
    managedByName />`;
  - screens `StudentPlans`, `TeacherPlans`, `ParentChildPlans`,
    `CheckoutReturn`.

Behaviour:

1. **Plans** list the audience's tiers for the chosen interval (Monthly default, Yearly
   toggle), cheapest first, then credit packs under `id="packs"` (so `paths.packs` deep-links).
   Allowance sizes never appear (hidden by design); tier cards show `features` lines, price
   and interval, and for teacher tiers the included seats and the extra-seat price.
2. **Buy** (no live subscription): "Choose {tier}" posts A2 with `extraSeats` (teacher only, a
   0–200 number field) and redirects to `checkoutUrl`. Packs post A3. Before redirecting, the
   overview path is remembered against the `paymentId` in `sessionStorage` so the return page
   can send the payer back where they started.
3. **Live subscription**: the current tier's button reads "Current plan" (disabled); other
   tiers link to `{paths.overview}?change={tierId}` (Task 5 opens the plan-change dialog from
   that parameter). Packs stay buyable.
4. **Not the payer** (`canManage === false`): no buy controls; one line "{managedByName}
   manages billing for this account. Ask them to make changes."
5. **Public pricing** lives in Task 17 (`/pricing`, from the no-auth public catalogue).
   **`/billing`** exists because plan 05's billing emails link there: it sends a signed-in user
   to their own billing page (`defaultBillingPath(role)`; a parent lands on `/parent`, where each
   child's billing is linked).
6. **Return page** `/billing/return/:paymentId` polls A4 every 2s for up to 3 minutes, shows a
   `role="status"` heading and body per phase, and never trusts Paymob's query parameters.
7. `checkoutUrl` is followed only when it is `https://…` or a same-origin path; anything else
   shows "Couldn't start checkout. Nothing was charged. Try again."

Return page copy (pinned by tests):

| Phase | Heading | Body | Actions |
|---|---|---|---|
| confirming | Confirming your payment | Paymob is confirming the payment with your bank. This usually takes a few seconds. Keep this page open. | — |
| confirming, polling stopped | Still confirming | Your bank hasn't confirmed this payment yet. You can leave this page: it is added to your account as soon as it's confirmed. | Check again (refetch) · Go to billing |
| paid, `credit_pack`/`auto_topup` | Credits added | Your credits are ready to use. | Back to billing |
| paid, `subscription_first` | Your plan is active | This month's allowance is ready to use. | Back to billing |
| paid, `upgrade_proration` | Plan upgraded | The extra allowance is ready now. | Back to billing |
| paid, `extra_seats` | Seats added | The new seats are ready for students to join. | Back to billing |
| paid, `subscription_renewal` | Renewal paid | Your plan continues for another period. | Back to billing |
| failed | Payment didn't go through | The payment wasn't completed, so nothing was added to your account. You can try again with the same card or a different one. | Try again (→ plans) · Back to billing |
| mismatch | We couldn't confirm this payment | The amount reported for this payment didn't match the order, so nothing was added. Our team has been alerted and will refund it. You don't need to pay again. | Back to billing |
| reversed | This payment was reversed | It was refunded or cancelled, so it doesn't add anything to your account. | Back to billing |
| load error | Couldn't load this payment | Check your connection and try again. If you paid, the payment is still confirmed on our side. | Try again |

- [ ] **Step 1: Write the failing pure test**

`web/tests/unit/checkoutReturn.test.ts`:

```ts
import { describe, expect, it, vi } from "vitest"
import {
  defaultBillingPath,
  isSafeCheckoutUrl,
  rememberReturnTo,
  returnCopy,
  returnToFor,
  startCheckoutRedirect,
} from "@/lib/checkoutReturn"

function memoryStorage(): Storage {
  const m = new Map<string, string>()
  return {
    get length() {
      return m.size
    },
    clear: () => m.clear(),
    getItem: (k) => m.get(k) ?? null,
    key: (i) => [...m.keys()][i] ?? null,
    removeItem: (k) => void m.delete(k),
    setItem: (k, v) => void m.set(k, v),
  }
}

describe("return path memory", () => {
  it("remembers a same-origin path per payment and falls back otherwise", () => {
    const s = memoryStorage()
    rememberReturnTo("p1", "/teacher/billing", s)
    expect(returnToFor("p1", "/", s)).toBe("/teacher/billing")
    expect(returnToFor("p2", "/student/billing", s)).toBe("/student/billing")
    rememberReturnTo("p3", "//evil.example", s)
    expect(returnToFor("p3", "/", s)).toBe("/")
    rememberReturnTo("p4", "https://evil.example", s)
    expect(returnToFor("p4", "/", s)).toBe("/")
  })

  it("defaults by role", () => {
    expect(defaultBillingPath("student")).toBe("/student/billing")
    expect(defaultBillingPath("teacher")).toBe("/teacher/billing")
    expect(defaultBillingPath("school_admin")).toBe("/teacher/billing")
    expect(defaultBillingPath("parent")).toBe("/parent")
    expect(defaultBillingPath(undefined)).toBe("/")
  })
})

describe("checkout redirect", () => {
  it("only follows https or same-origin checkout URLs", () => {
    expect(isSafeCheckoutUrl("https://eg.checkout.paymob.com/?publicKey=a&clientSecret=b")).toBe(true)
    expect(isSafeCheckoutUrl("/billing/return/p1")).toBe(true)
    expect(isSafeCheckoutUrl("//evil.example")).toBe(false)
    expect(isSafeCheckoutUrl("javascript:alert(1)")).toBe(false)
    expect(isSafeCheckoutUrl("http://eg.checkout.paymob.com")).toBe(false)
  })

  it("remembers the return path, then navigates; refuses unsafe URLs", () => {
    const go = vi.fn()
    const store = memoryStorage()
    vi.stubGlobal("sessionStorage", store)
    expect(startCheckoutRedirect({ paymentId: "p9", checkoutUrl: "https://eg.checkout.paymob.com/x" }, "/student/billing", go)).toBe(true)
    expect(go).toHaveBeenCalledWith("https://eg.checkout.paymob.com/x")
    expect(store.getItem("lemely.billing.returnTo.p9")).toBe("/student/billing")
    expect(startCheckoutRedirect({ paymentId: "p10", checkoutUrl: "javascript:x" }, "/", go)).toBe(false)
    expect(go).toHaveBeenCalledTimes(1)
    vi.unstubAllGlobals()
  })
})

describe("returnCopy", () => {
  it("covers every phase with the pinned copy", () => {
    expect(returnCopy("confirming", "credit_pack", false).heading).toBe("Confirming your payment")
    expect(returnCopy("confirming", "credit_pack", true).heading).toBe("Still confirming")
    expect(returnCopy("paid", "credit_pack", false).heading).toBe("Credits added")
    expect(returnCopy("paid", "auto_topup", false).heading).toBe("Credits added")
    expect(returnCopy("paid", "subscription_first", false).heading).toBe("Your plan is active")
    expect(returnCopy("paid", "upgrade_proration", false).heading).toBe("Plan upgraded")
    expect(returnCopy("paid", "extra_seats", false).heading).toBe("Seats added")
    expect(returnCopy("paid", "subscription_renewal", false).heading).toBe("Renewal paid")
    expect(returnCopy("failed", "credit_pack", false).heading).toBe("Payment didn't go through")
    expect(returnCopy("mismatch", "credit_pack", false).body).toContain("You don't need to pay again.")
    expect(returnCopy("reversed", "credit_pack", false).heading).toBe("This payment was reversed")
  })
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npx vitest run tests/unit/checkoutReturn.test.ts`
Expected: FAIL, "Failed to resolve import "@/lib/checkoutReturn"".

- [ ] **Step 3: Write `web/src/lib/checkoutReturn.ts`**

```ts
import type { PaymentPhase } from "@/lib/billingFormat"
import type { CheckoutResponse, PaymentPurpose } from "@/lib/billingTypes"

/*
 * Leaving for Paymob's hosted checkout and coming back (spec §5.1 steps 3–5). The redirect
 * back carries Paymob's own query parameters; none of them is read. State comes only from
 * `GET /billing/payments/{id}`. Where to send the payer afterwards is remembered here, per
 * payment, in sessionStorage (same tab), and only same-origin paths are honoured.
 */

const KEY = "lemely.billing.returnTo"

function isSamePath(path: string): boolean {
  return path.startsWith("/") && !path.startsWith("//")
}

/** `null` where there is no sessionStorage (the node test runner, a locked-down browser). */
function tabStorage(): Storage | null {
  return typeof sessionStorage === "undefined" ? null : sessionStorage
}

export function rememberReturnTo(paymentId: string, path: string, storage: Storage | null = tabStorage()): void {
  storage?.setItem(`${KEY}.${paymentId}`, path)
}

export function returnToFor(paymentId: string, fallback: string, storage: Storage | null = tabStorage()): string {
  const stored = storage?.getItem(`${KEY}.${paymentId}`) ?? null
  return stored !== null && isSamePath(stored) ? stored : fallback
}

export function defaultBillingPath(role: string | undefined): string {
  if (role === "student") return "/student/billing"
  if (role === "teacher" || role === "school_admin") return "/teacher/billing"
  if (role === "parent") return "/parent"
  return "/"
}

export function isSafeCheckoutUrl(url: string): boolean {
  return url.startsWith("https://") || isSamePath(url)
}

/** Remember where to come back to, then leave for checkout. False when the URL is unsafe. */
export function startCheckoutRedirect(
  res: CheckoutResponse,
  returnTo: string,
  go: (url: string) => void = (url) => window.location.assign(url),
): boolean {
  if (!isSafeCheckoutUrl(res.checkoutUrl)) return false
  rememberReturnTo(res.paymentId, returnTo)
  go(res.checkoutUrl)
  return true
}

export interface ReturnCopy {
  heading: string
  body: string
}

const PAID: Record<PaymentPurpose, ReturnCopy> = {
  credit_pack: { heading: "Credits added", body: "Your credits are ready to use." },
  auto_topup: { heading: "Credits added", body: "Your credits are ready to use." },
  subscription_first: { heading: "Your plan is active", body: "This month's allowance is ready to use." },
  upgrade_proration: { heading: "Plan upgraded", body: "The extra allowance is ready now." },
  extra_seats: { heading: "Seats added", body: "The new seats are ready for students to join." },
  subscription_renewal: { heading: "Renewal paid", body: "Your plan continues for another period." },
}

export function returnCopy(phase: PaymentPhase, purpose: PaymentPurpose, pollingStopped: boolean): ReturnCopy {
  switch (phase) {
    case "confirming":
      return pollingStopped
        ? {
            heading: "Still confirming",
            body: "Your bank hasn't confirmed this payment yet. You can leave this page: it is added to your account as soon as it's confirmed.",
          }
        : {
            heading: "Confirming your payment",
            body: "Paymob is confirming the payment with your bank. This usually takes a few seconds. Keep this page open.",
          }
    case "paid":
      return PAID[purpose]
    case "failed":
      return {
        heading: "Payment didn't go through",
        body: "The payment wasn't completed, so nothing was added to your account. You can try again with the same card or a different one.",
      }
    case "mismatch":
      return {
        heading: "We couldn't confirm this payment",
        body: "The amount reported for this payment didn't match the order, so nothing was added. Our team has been alerted and will refund it. You don't need to pay again.",
      }
    case "reversed":
      return {
        heading: "This payment was reversed",
        body: "It was refunded or cancelled, so it doesn't add anything to your account.",
      }
  }
}
```

- [ ] **Step 4: Run it to verify it passes**

Run: `npx vitest run tests/unit/checkoutReturn.test.ts`
Expected: PASS.

- [ ] **Step 5: Write the failing screen test**

`web/tests/unit/billingPurchase.test.ts` (apostrophes render as `&#x27;` in static markup, so
assertions avoid them):

```ts
import { createElement as h } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { ApiError } from "@/lib/api"
import { billingPaths } from "@/lib/billingPaths"
import { fx } from "./support/billingFixtures"
import { errorQuery, fakeMutation, okQuery, pendingQuery, renderAt, renderStatic } from "./support/billingRender"

const s = vi.hoisted(() => ({
  catalogue: null as unknown,
  summary: null as unknown,
  payment: null as unknown,
  subCheckout: null as unknown,
  packCheckout: null as unknown,
}))

vi.mock("@/lib/hooks/useBillingApi", () => ({
  useCatalogue: () => s.catalogue,
  useBillingSummary: () => s.summary,
  usePaymentStatus: () => s.payment,
  useStartSubscriptionCheckout: () => s.subCheckout,
  useStartPackCheckout: () => s.packCheckout,
}))
vi.mock("@/lib/auth/AuthContext", () => ({ useAuth: () => ({ session: { role: "student" } }) }))

import { BillingRedirect, CheckoutReturn } from "@/portals/billing/CheckoutReturn"
import { Route, Routes } from "react-router-dom"
import { PlansView, type PlansViewProps } from "@/portals/billing/PlansView"

const paths = billingPaths({ role: "student" })
const view = (over: Partial<PlansViewProps> = {}) =>
  renderStatic(
    h(PlansView, {
      audience: "student",
      beneficiaryId: null,
      paths,
      currentTierId: null,
      hasLiveSubscription: false,
      canManage: true,
      managedByName: null,
      ...over,
    }),
  )

beforeEach(() => {
  s.catalogue = okQuery(fx.studentCatalogue)
  s.summary = okQuery(fx.summary)
  s.subCheckout = fakeMutation()
  s.packCheckout = fakeMutation()
  s.payment = Object.assign(okQuery(fx.payment), { pollingStopped: false })
})

describe("PlansView", () => {
  it("shows monthly tiers by default with price and interval, and packs under #packs", () => {
    const html = view()
    expect(html).toContain("Student Plus")
    expect(html).toMatch(/EGP\s250\.00/)
    expect(html).toContain("per month")
    expect(html).not.toMatch(/EGP\s2,500\.00/)
    expect(html).toContain('id="packs"')
    expect(html).toContain("500 credits")
    expect(html).toContain("Choose Student Plus")
  })

  it("never shows usage units (allowance sizes are hidden)", () => {
    expect(view()).not.toMatch(/\bunits\b/i)
  })

  it("marks the current plan and links other tiers to the plan-change dialog", () => {
    s.catalogue = okQuery({ ...fx.studentCatalogue, tiers: [fx.studentMonthly, { ...fx.studentMonthly, id: "t-s-m2", name: "Student Max" }] })
    const html = view({ currentTierId: "t-s-m", hasLiveSubscription: true })
    expect(html).toContain("Current plan")
    expect(html).toContain(`href="${paths.overview}?change=t-s-m2"`)
  })

  it("hides buy controls from a non-payer", () => {
    const html = view({ canManage: false, managedByName: "Mona" })
    expect(html).toContain("Mona manages billing for this account.")
    expect(html).not.toContain("Choose Student Plus")
  })


  it("shows teacher seats and the extra-seat field", () => {
    s.catalogue = okQuery(fx.teacherCatalogue)
    const html = view({ audience: "teacher", paths: billingPaths({ role: "teacher" }) })
    expect(html).toContain("20 student seats included")
    expect(html).toMatch(/Extra seats EGP\s30\.00 each per month/)
    expect(html).toContain('name="extraSeats"')
  })

  it("renders loading, error and empty states", () => {
    s.catalogue = pendingQuery()
    expect(view()).toContain('aria-label="Loading"')
    s.catalogue = errorQuery(new ApiError(500, "x"))
    expect(view()).toContain("load plans")
    s.catalogue = okQuery({ ...fx.studentCatalogue, tiers: [], packs: [] })
    expect(view()).toContain("No plans are on sale right now.")
  })

  it("shows a checkout failure as an alert that says nothing was charged", () => {
    s.packCheckout = fakeMutation({ isError: true, error: new ApiError(503, "x") })
    const html = view()
    expect(html).toContain('role="alert"')
    expect(html).toContain("Payments are unavailable right now. Nothing was charged.")
  })
})

describe("BillingRedirect", () => {
  it("sends a student from /billing to their billing page", () => {
    const html = renderAt(
      h(Routes, null, h(Route, { path: "/billing", element: h(BillingRedirect) }), h(Route, { path: "/student/billing", element: h("p", null, "student billing") })),
      "/*",
      "/billing",
    )
    expect(html).toContain("student billing")
  })
})

describe("CheckoutReturn", () => {
  const at = () => renderAt(h(CheckoutReturn), "/billing/return/:paymentId", "/billing/return/pay1")

  it("announces confirming while pending", () => {
    const html = at()
    expect(html).toMatch(/role="status"/)
    expect(html).toContain("Confirming your payment")
  })

  it("offers a manual re-check once polling stops", () => {
    s.payment = Object.assign(okQuery(fx.payment), { pollingStopped: true })
    const html = at()
    expect(html).toContain("Still confirming")
    expect(html).toContain("Check again")
  })

  it("confirms a paid pack and links back to billing", () => {
    s.payment = Object.assign(okQuery({ ...fx.payment, status: "paid", paidAt: "2026-11-05T09:01:00Z" }), { pollingStopped: false })
    const html = at()
    expect(html).toContain("Credits added")
    expect(html).toContain('href="/student/billing"')
  })

  it("offers a retry to plans after a failure", () => {
    s.payment = Object.assign(okQuery({ ...fx.payment, status: "failed" }), { pollingStopped: false })
    expect(at()).toContain('href="/student/billing/plans"')
  })

  it("shows a load error with a retry", () => {
    s.payment = Object.assign(errorQuery(new ApiError(0, "x")), { pollingStopped: false })
    expect(at()).toContain("load this payment")
  })
})
```

- [ ] **Step 6: Run it to verify it fails**

Run: `npx vitest run tests/unit/billingPurchase.test.ts`
Expected: FAIL, "Failed to resolve import "@/portals/billing/CheckoutReturn"".

- [ ] **Step 7: Write `web/src/portals/billing/PlansView.tsx`**

```tsx
import { useState } from "react"
import { Link } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Card, CardBody } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { CardGridSkeleton } from "@/components/ui/loading-shapes"
import { QueryState } from "@/components/ui/query-state"
import { EmptyState } from "@/components/ui/state-views"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { formatCredits, formatMoney, intervalLabel } from "@/lib/billingFormat"
import { billingFailureMessage } from "@/lib/billingOutcome"
import type { BillingPaths } from "@/lib/billingPaths"
import type { Audience, BillingInterval, CreditPack, PlanTier } from "@/lib/billingTypes"
import { startCheckoutRedirect } from "@/lib/checkoutReturn"
import {
  useCatalogue,
  useStartPackCheckout,
  useStartSubscriptionCheckout,
} from "@/lib/hooks/useBillingApi"

/*
 * Plans and credit packs for one audience (spec §2.1, §2.2). Allowance sizes are hidden by
 * design, so a tier card sells on its `features` lines, its price and (teachers) its seats.
 * Prices come only from the catalogue: nothing here is a hard-coded number (PRODUCT.md: no
 * fabricated pricing).
 */

export interface PlansViewProps {
  audience: Audience
  beneficiaryId: string | null
  paths: BillingPaths
  currentTierId: string | null
  hasLiveSubscription: boolean
  canManage: boolean
  managedByName: string | null
}

const UNSAFE_URL = "Couldn't start checkout. Nothing was charged. Try again."

export function PlansView(props: PlansViewProps) {
  const { audience, beneficiaryId, paths, currentTierId, hasLiveSubscription, canManage, managedByName } = props
  const catalogue = useCatalogue(audience)
  const subCheckout = useStartSubscriptionCheckout()
  const packCheckout = useStartPackCheckout()
  const [interval, setInterval] = useState<BillingInterval>("month")
  const [extraSeats, setExtraSeats] = useState(0)
  const [unsafe, setUnsafe] = useState(false)
  const busy = subCheckout.isPending || packCheckout.isPending
  const buying = canManage
  const failure = subCheckout.isError ? subCheckout.error : packCheckout.isError ? packCheckout.error : null

  const redirect = (res: { paymentId: string; checkoutUrl: string }) => {
    if (!startCheckoutRedirect(res, paths.overview)) setUnsafe(true)
  }

  const tierAction = (tier: PlanTier) => {
    if (!buying) return null
    if (tier.id === currentTierId) return <Button disabled>Current plan</Button>
    if (hasLiveSubscription) {
      return (
        <Link to={`${paths.overview}?change=${tier.id}`} className="inline-flex items-center justify-center rounded-button border border-outline-variant bg-surface-container-lowest px-4 py-2.5 text-label text-on-surface hover:border-outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary pointer-coarse:min-h-11">
          Change to {tier.name}
        </Link>
      )
    }
    return (
      <Button
        variant="primary"
        disabled={busy}
        loading={subCheckout.isPending && subCheckout.variables?.planTierId === tier.id}
        onClick={() =>
          subCheckout.mutate(
            { planTierId: tier.id, beneficiaryId, extraSeats: audience === "teacher" ? extraSeats : 0 },
            { onSuccess: redirect },
          )
        }
      >
        Choose {tier.name}
      </Button>
    )
  }

  const packAction = (pack: CreditPack) => {
    if (!buying) return null
    return (
      <Button
        variant="secondary"
        disabled={busy}
        loading={packCheckout.isPending && packCheckout.variables?.creditPackId === pack.id}
        onClick={() => packCheckout.mutate({ creditPackId: pack.id, beneficiaryId }, { onSuccess: redirect })}
      >
        Buy {pack.name}
      </Button>
    )
  }

  return (
    <div className="flex flex-col gap-6">
      {!canManage ? (
        <p className="m-0 text-body-md text-on-surface-variant">
          {managedByName ?? "Someone else"} manages billing for this account. Ask them to make changes.
        </p>
      ) : null}
      {failure || unsafe ? (
        <p role="alert" className="m-0 text-body-sm text-error">
          {unsafe ? UNSAFE_URL : billingFailureMessage(failure, "start checkout")}
        </p>
      ) : null}
      <QueryState
        query={catalogue}
        skeleton={<CardGridSkeleton count={3} />}
        error={{ heading: "Couldn't load plans" }}
        isEmpty={(c) => c.tiers.length === 0 && c.packs.length === 0}
        empty={<EmptyState heading="No plans are on sale right now." body="Check back soon." />}
      >
        {(c) => {
          const tiers = c.tiers.filter((t) => t.interval === interval).sort((a, b) => a.priceMinor - b.priceMinor)
          return (
            <>
              <section aria-labelledby="plans-heading" className="flex flex-col gap-4">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <h2 id="plans-heading" className="m-0 text-display-sm text-on-surface">Plans</h2>
                  <ToggleGroup
                    type="single"
                    value={interval}
                    onValueChange={(v) => (v === "month" || v === "year" ? setInterval(v) : undefined)}
                    aria-label="Billing interval"
                  >
                    <ToggleGroupItem value="month">Monthly</ToggleGroupItem>
                    <ToggleGroupItem value="year">Yearly</ToggleGroupItem>
                  </ToggleGroup>
                </div>
                {audience === "teacher" && buying && !hasLiveSubscription ? (
                  <div className="max-w-xs">
                    <Input
                      label="Extra seats at checkout"
                      hint="Seats beyond the plan's included seats, billed with the plan."
                      name="extraSeats"
                      type="number"
                      inputMode="numeric"
                      min={0}
                      max={200}
                      value={extraSeats}
                      onChange={(e) => setExtraSeats(Math.max(0, Math.min(200, Number(e.target.value) || 0)))}
                    />
                  </div>
                ) : null}
                <ul className="m-0 grid list-none gap-4 p-0 md:grid-cols-2 lg:grid-cols-3">
                  {tiers.map((tier) => (
                    <li key={tier.id}>
                      <Card className="h-full">
                        <CardBody className="flex h-full flex-col gap-3">
                          <h3 className="m-0 text-display-sm text-on-surface">{tier.name}</h3>
                          <p className="m-0">
                            <span className="text-data-lg text-on-surface">{formatMoney(tier.priceMinor, tier.currency)}</span>{" "}
                            <span className="text-body-sm text-on-surface-variant">{intervalLabel(tier.interval)}</span>
                          </p>
                          {tier.includedSeats !== null ? (
                            <p className="m-0 text-body-sm text-on-surface">{tier.includedSeats} student seats included</p>
                          ) : null}
                          {tier.extraSeatPriceMinor !== null ? (
                            <p className="m-0 text-body-sm text-on-surface-variant">
                              Extra seats {formatMoney(tier.extraSeatPriceMinor, tier.currency)} each {intervalLabel(tier.interval)}
                            </p>
                          ) : null}
                          <ul className="m-0 flex flex-1 flex-col gap-1 ps-4 text-body-sm text-on-surface">
                            {tier.features.map((f) => (
                              <li key={f}>{f}</li>
                            ))}
                          </ul>
                          {tierAction(tier)}
                        </CardBody>
                      </Card>
                    </li>
                  ))}
                </ul>
                {tiers.length === 0 ? (
                  <p className="m-0 text-body-sm text-on-surface-variant">
                    No {interval === "month" ? "monthly" : "yearly"} plans right now.
                  </p>
                ) : null}
              </section>
              <section id="packs" aria-labelledby="packs-heading" className="flex scroll-mt-24 flex-col gap-4">
                <h2 id="packs-heading" className="m-0 text-display-sm text-on-surface">Credit packs</h2>
                <p className="m-0 text-body-sm text-on-surface-variant">
                  Credits pay once a plan's allowance runs out, or on their own without a plan. They last 12 months from purchase.
                </p>
                <ul className="m-0 grid list-none gap-4 p-0 md:grid-cols-2 lg:grid-cols-3">
                  {c.packs.map((pack) => (
                    <li key={pack.id}>
                      <Card className="h-full">
                        <CardBody className="flex h-full flex-col gap-2">
                          <h3 className="m-0 text-display-xs text-on-surface">{pack.name}</h3>
                          <p className="m-0 text-data-md text-on-surface">{formatCredits(pack.units)}</p>
                          <p className="m-0 flex-1 text-body-sm text-on-surface-variant">{formatMoney(pack.priceMinor, pack.currency)}</p>
                          {packAction(pack)}
                        </CardBody>
                      </Card>
                    </li>
                  ))}
                </ul>
              </section>
            </>
          )
        }}
      </QueryState>
    </div>
  )
}
```

`CardGridSkeleton`, `PageHeaderSkeleton` and `ListSkeleton` (all in
`web/src/components/ui/loading-shapes.tsx`) each render one `role="status" aria-label="Loading"`
region; that is what the loading assertions look for.

- [ ] **Step 8: Write `web/src/portals/billing/PlansScreen.tsx`**

```tsx
import { useParams } from "react-router-dom"
import { PageHeaderSkeleton } from "@/components/ui/loading-shapes"
import { QueryState } from "@/components/ui/query-state"
import { Eyebrow } from "@/components/ui/primitives"
import { billingPaths, type BillingScope } from "@/lib/billingPaths"
import { isLiveSubscription } from "@/lib/billingFormat"
import type { Audience } from "@/lib/billingTypes"
import { useBillingSummary } from "@/lib/hooks/useBillingApi"
import { PlansView } from "./PlansView"

/*
 * Route wrappers around `PlansView`: which audience, whose account, and where "back to
 * billing" is. A parent buys student plans for a linked child (spec §2.1); the backend
 * re-checks the `parent_child_links` relationship on every checkout.
 */

function SignedInPlans({ scope, audience, beneficiaryId }: { scope: BillingScope; audience: Audience; beneficiaryId: string | null }) {
  const summary = useBillingSummary(beneficiaryId)
  const paths = billingPaths(scope)
  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-2">
        <Eyebrow>Plan and billing</Eyebrow>
        <h1 className="m-0 text-display-md text-on-surface">Plans and credits</h1>
      </div>
      <QueryState
        query={summary}
        skeleton={<PageHeaderSkeleton />}
        error={{ heading: "Couldn't load your billing" }}
      >
        {(s) => (
          <PlansView
            audience={audience}
            beneficiaryId={beneficiaryId}
            paths={paths}
            currentTierId={isLiveSubscription(s.subscription?.status) ? (s.subscription?.tier.id ?? null) : null}
            hasLiveSubscription={isLiveSubscription(s.subscription?.status)}
            canManage={s.canManage}
            managedByName={s.managedByName}
          />
        )}
      </QueryState>
    </div>
  )
}

export function StudentPlans() {
  return <SignedInPlans scope={{ role: "student" }} audience="student" beneficiaryId={null} />
}

export function TeacherPlans() {
  return <SignedInPlans scope={{ role: "teacher" }} audience="teacher" beneficiaryId={null} />
}

export function ParentChildPlans() {
  const { childId = "" } = useParams<{ childId: string }>()
  return <SignedInPlans scope={{ role: "parent", childId }} audience="student" beneficiaryId={childId} />
}
```

- [ ] **Step 9: Write `web/src/portals/billing/CheckoutReturn.tsx`**

```tsx
import type { ReactNode } from "react"
import { Link, Navigate, useParams } from "react-router-dom"
import { BrandLockup } from "@/components/ui/brand-lockup"
import { Button } from "@/components/ui/button"
import { MAIN_CONTENT_ID } from "@/components/ui/skip-link"
import { ErrorState } from "@/components/ui/state-views"
import { useAuth } from "@/lib/auth/AuthContext"
import { formatMoney, paymentPhase } from "@/lib/billingFormat"
import { defaultBillingPath, returnCopy, returnToFor } from "@/lib/checkoutReturn"
import { usePaymentStatus } from "@/lib/hooks/useBillingApi"

/*
 * `/billing/return/:paymentId`: where Paymob's hosted checkout sends the payer back (spec §5.1
 * step 5). Paymob's query parameters are ignored; this page polls our own payment record.
 */

const LINK =
  "inline-flex items-center justify-center rounded-button px-4 py-2.5 text-label focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary pointer-coarse:min-h-11"

/** `/billing` (plan 05's email links): the signed-in user's own billing page. */
export function BillingRedirect() {
  const { session } = useAuth()
  return <Navigate to={defaultBillingPath(session?.role)} replace />
}

export function CheckoutReturn() {
  const { paymentId = "" } = useParams<{ paymentId: string }>()
  const { session } = useAuth()
  const backTo = returnToFor(paymentId, defaultBillingPath(session?.role))
  const plansTo = backTo === "/" || backTo === "/parent" ? backTo : `${backTo}/plans`
  const payment = usePaymentStatus(paymentId || null)

  let body: ReactNode
  if (payment.isError) {
    body = (
      <ErrorState
        heading="Couldn't load this payment"
        body="Check your connection and try again. If you paid, the payment is still confirmed on our side."
        action={{ label: "Try again", onClick: () => void payment.refetch() }}
      />
    )
  } else if (!payment.data) {
    body = (
      <div role="status" className="flex flex-col gap-2">
        <h1 id="return-heading" className="m-0 text-display-sm text-on-surface">Confirming your payment</h1>
      </div>
    )
  } else {
    const data = payment.data
    const phase = paymentPhase(data.status)
    const copy = returnCopy(phase, data.purpose, payment.pollingStopped)
    body = (
      <>
        <div role="status" className="flex flex-col gap-2">
          <h1 id="return-heading" className="m-0 text-display-sm text-on-surface">{copy.heading}</h1>
          <p className="m-0 text-body-md text-on-surface-variant">{copy.body}</p>
        </div>
        <p className="m-0 text-data-md text-on-surface">{formatMoney(data.amountMinor, data.currency)}</p>
        <div className="flex flex-wrap gap-2">
          {phase === "confirming" && payment.pollingStopped ? (
            <Button variant="primary" onClick={() => void payment.refetch()}>Check again</Button>
          ) : null}
          {phase === "failed" ? (
            <Link to={plansTo} className={`${LINK} bg-primary text-on-primary hover:bg-primary-hover`}>Try again</Link>
          ) : null}
          {phase !== "confirming" || payment.pollingStopped ? (
            <Link to={backTo} className={`${LINK} border border-outline-variant bg-surface-container-lowest text-on-surface`}>
              {phase === "confirming" ? "Go to billing" : "Back to billing"}
            </Link>
          ) : null}
        </div>
      </>
    )
  }

  return (
    <main
      id={MAIN_CONTENT_ID}
      tabIndex={-1}
      className="flex min-h-dvh flex-col items-center justify-center gap-6 bg-surface px-page-mobile py-12 focus:outline-none"
    >
      <BrandLockup />
      <section aria-labelledby="return-heading" className="flex w-full max-w-[480px] flex-col gap-4 rounded-card border border-outline-variant bg-surface-container-lowest p-7">
        {body}
      </section>
    </main>
  )
}
```

- [ ] **Step 10: Register the routes**

In `web/src/routes.tsx`, add lazy imports beside the other settings lazies:

```tsx
const CheckoutReturn = lazy(() =>
  import("@/portals/billing/CheckoutReturn").then((m) => ({ default: m.CheckoutReturn })),
)
const BillingRedirect = lazy(() =>
  import("@/portals/billing/CheckoutReturn").then((m) => ({ default: m.BillingRedirect })),
)
```

and two entries in `appRoutes`, after the `/data` entry:

```tsx
  /*
   * Where Paymob's hosted checkout returns the payer (spec §5.1 step 5). Any signed-in role:
   * students, teachers and parents all pay.
   */
  /*
   * Plan 05's billing emails link to `/billing`; send each role to its own billing page.
   */
  {
    path: "/billing",
    errorElement,
    handle: { title: "Plan and billing", skeleton: "standalone" } satisfies PageMeta,
    element: (
      <RequireAuth allowedRoles={ALL_ROLES}>
        <Suspense fallback={<RouteSkeleton />}>
          <BillingRedirect />
        </Suspense>
      </RequireAuth>
    ),
  },
  {
    path: "/billing/return/:paymentId",
    errorElement,
    handle: { title: "Payment status", skeleton: "standalone" } satisfies PageMeta,
    element: (
      <RequireAuth allowedRoles={ALL_ROLES}>
        <Suspense fallback={<RouteSkeleton />}>
          <CheckoutReturn />
        </Suspense>
      </RequireAuth>
    ),
  },
```

In `web/src/portals/student/index.tsx`, add beside the settings lazies:

```tsx
const StudentPlans = lazy(() =>
  import("@/portals/billing/PlansScreen").then((m) => ({ default: m.StudentPlans })),
)
```

and a child before the `settings` child:

```tsx
    {
      path: "billing/plans",
      element: <StudentPlans />,
      handle: { title: "Plans and credits", skeleton: "page-header" },
    },
```

In `web/src/portals/teacher/index.tsx`, the same with `TeacherPlans` (lazy import from
`@/portals/billing/PlansScreen`, child `path: "billing/plans"`, placed before the `settings`
child so `teacherContentRoutes()` includes it).

In `web/src/portals/parent/index.tsx`, the same with `ParentChildPlans`, child
`path: "children/:childId/billing/plans"`, placed after the `children/:childId/tutor-access`
child, `handle: { title: "Plans and credits", skeleton: "page-header" }`.

- [ ] **Step 11: Run the unit tests to verify they pass**

Run: `npx vitest run tests/unit/checkoutReturn.test.ts tests/unit/billingPurchase.test.ts tests/unit/documentMeta.test.ts tests/unit/adminRoutes.test.ts tests/unit/settingsTabs.test.ts`
Expected: PASS.

- [ ] **Step 12: Write the e2e spec**

`web/e2e/billing-purchase.spec.ts` (real login from the seed; billing API stubbed with
`page.route`, because the hosted checkout is Paymob's page and cannot be driven locally):

```ts
import { test, expect, type Page } from "@playwright/test"
import { watchConsole } from "./console-errors"
import { readSeed } from "./seed"

// Wire shapes (plan 02 `CatalogueDTO`, plan 05 `BillingSummaryDTO`, plan 02 `PaymentStatusDTO`).
const catalogue = {
  planTiers: [
    { planTierId: "t1", code: "s_m", name: "Student Plus", priceMinor: 25000, currency: "EGP", interval: "monthly", audience: "student", includedSeats: 0, extraSeatPriceMinor: 0, features: { "Mark past papers": true } },
  ],
  creditPacks: [{ creditPackId: "p1", code: "pack_500", name: "500 credits", credits: 500, priceMinor: 15000, currency: "EGP" }],
}
const summary = {
  beneficiary: { userId: "u", displayName: "S", audience: "student" },
  subscription: null,
  canManage: true,
  managedByName: null,
  savedCard: null,
  usage: { fraction: null, resetsAt: null },
  credits: { totalUnits: 0, expiring: [] },
  debtUnits: 0,
  seats: null,
}

async function stubBilling(page: Page) {
  let polls = 0
  await page.route("**/api/billing/catalogue**", (r) => r.fulfill({ json: catalogue }))
  await page.route("**/api/billing/summary**", (r) => r.fulfill({ json: summary }))
  await page.route("**/api/billing/checkout/pack", (r) =>
    r.fulfill({ json: { paymentId: "pay-e2e", checkoutUrl: "/billing/return/pay-e2e" } }),
  )
  await page.route("**/api/billing/payments/pay-e2e", (r) => {
    polls += 1
    r.fulfill({
      json: {
        paymentId: "pay-e2e",
        status: polls < 2 ? "pending" : "paid",
        purpose: "credit_pack",
        amountMinor: 15000,
        currency: "EGP",
        description: "500 credits",
        paidAt: polls < 2 ? null : "2026-11-05T09:01:00Z",
      },
    })
  })
}

test("a student buys a credit pack and the return page confirms it by polling", async ({ page }) => {
  const seed = readSeed()
  const errors = watchConsole(page)
  const student = seed.students.control
  await stubBilling(page)

  await page.goto("/login")
  await page.getByLabel("Email").fill(student.email)
  await page.getByLabel("Password").fill(student.password)
  await page.getByRole("button", { name: /sign in/i }).click()
  await expect(page).toHaveURL(/\/student$/, { timeout: 15_000 })

  await page.goto("/student/billing/plans")
  await expect(page.getByRole("heading", { name: "Credit packs" })).toBeVisible()
  await page.getByRole("button", { name: "Buy 500 credits" }).click()

  await expect(page).toHaveURL(/\/billing\/return\/pay-e2e$/)
  await expect(page.getByRole("status")).toContainText("Confirming your payment")
  await expect(page.getByRole("heading", { name: "Credits added" })).toBeVisible({ timeout: 10_000 })
  await expect(page.getByRole("link", { name: "Back to billing" })).toHaveAttribute("href", "/student/billing")
  expect(errors).toEqual([])
})
```

- [ ] **Step 13: Run the e2e spec (local stack only)**

Run: `npx playwright test e2e/billing-purchase.spec.ts`
Expected: 2 passed. If `supabase status` fails, record "e2e not run: local stack down".

- [ ] **Step 14: Run the frontend gate**

```bash
npm run typecheck
npx vitest run tests/unit/checkoutReturn.test.ts tests/unit/billingPurchase.test.ts tests/unit/documentMeta.test.ts tests/unit/adminRoutes.test.ts tests/unit/settingsTabs.test.ts $SCAN
npm run lint && npm run check:copy && npm run build && npm run check:installable
```
Expected: all exit 0.

- [ ] **Step 15: Commit**

```bash
cd /home/sico/Code/Lemely/.claude/worktrees/paymob-integration
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files && graphify update .
P="web/src/lib/checkoutReturn.ts web/src/portals/billing/PlansView.tsx web/src/portals/billing/PlansScreen.tsx web/src/portals/billing/CheckoutReturn.tsx web/src/routes.tsx web/src/portals/student/index.tsx web/src/portals/teacher/index.tsx web/src/portals/parent/index.tsx web/tests/unit/checkoutReturn.test.ts web/tests/unit/billingPurchase.test.ts web/e2e/billing-purchase.spec.ts"
git add $P
git commit -S -m "feat(web): plans page, checkout redirect and return page" -- $P
```

---

### Task 5: Billing overview for student and teacher, with plan change and cancel

**Files:**
- Create: `web/src/portals/billing/PaymentProgress.tsx`
- Create: `web/src/portals/billing/PlanChangeDialog.tsx`
- Create: `web/src/portals/billing/CancelPlanDialog.tsx`
- Create: `web/src/portals/billing/BillingOverview.tsx`
- Create: `web/src/portals/billing/BillingScreens.tsx`
- Modify: `web/src/portals/student/index.tsx` (route `billing`)
- Modify: `web/src/portals/student/data.ts` (nav entry, crumbs)
- Modify: `web/src/portals/teacher/index.tsx` (route `billing`, `NAV_ICON.billing`)
- Modify: `web/src/portals/teacher/data.ts` (nav entry, icon union, trail arms)
- Modify: `web/tests/unit/navigation.test.ts` (only if it pins the exact nav lists)
- Test: `web/tests/unit/billingOverview.test.ts`

**Interfaces:**
- Consumes (Tasks 1, 2, 4): `useBillingSummary`, `useCatalogue`, `useUpgradeQuote`,
  `useUpgrade`, `useDowngrade`, `useCancelSubscription`, `usePaymentStatus`, `useUsageMeter`,
  `billingPaths`, `BillingScope`, `billingFailureMessage`, `formatMoney`, `formatBillingDate`,
  `intervalLabel`, `isLiveSubscription`, `paymentPhase`, `returnCopy`, `UsageMeterCard`,
  `CreditBalanceCard`, `DebtNotice`, types `Audience`, `PlanTier`, `SubscriptionView`,
  `SavedCardView`, `BillingSummary`.
- Produces:
  - `<PaymentProgress paymentId={string} />` (inline polling readout; reused by Task 11);
  - `<PlanChangeDialog open onClose subscription={SubscriptionView} tier={PlanTier | null}
    savedCard={SavedCardView | null} />`;
  - `<CancelPlanDialog open onClose subscription={SubscriptionView} audience />`;
  - `<BillingOverview scope audience beneficiaryId heading extra? />` where `extra?:
    ReactNode` renders after the meters (Task 8 passes the auto top-up card);
  - screens `StudentBilling`, `TeacherBilling`.

Data sources: everything on the page comes from `GET /billing/summary` (A5) for the
beneficiary; a signed-in student's or teacher's own **seat meters** come from `/usage/meter`
(A18), because the summary carries none. Plan change and cancel act on the summary's
`subscription.subscriptionId` (plan 05/06 routes are keyed by subscription), so a parent paying
for a child needs no `beneficiaryId` on those writes.

Overview states (all asserted):

| Data | Plan card shows | Actions (payer only) |
|---|---|---|
| no live subscription | "No plan" · "You're using credits only." | See plans |
| `pending_first_payment` | tier name · "Waiting for the first payment to confirm." | — |
| `active` | tier, price per interval, "Renews {date}" | Change plan · Cancel plan |
| `active` + `cancelAtPeriodEnd` | "Ends {date}. Usage comes from credits after that." | Change plan |
| `active` + `pendingTier` | "Changes to {pending} on {date}" | Change plan · Cancel plan |
| `past_due` | `role="status"` panel: "Your last renewal didn't go through. Paymob is retrying, and your plan keeps working until {graceUntil}." | Change plan · Cancel plan |
| teacher | "{used} of {capacity} seats used" (summary `seats`), "{included} included, {extra} extra" + link "Manage seats" → `/teacher/team` | as above |
| `canManage === false` | everything read-only, "{managedByName} manages this plan." | none; no receipts link |
| debt > 0 | `DebtNotice` above the plan card | Buy credits (payer only) |
| `paths.history === null` (parent) | no usage-history link (M6) | — |

Plan change dialog (opened by `?change={tierId}` from the plans page). A tier priced above the
current one is an **upgrade** (quote, then a merchant charge now, spec §5.3); one priced at or
below is a **downgrade** (scheduled for period end, no quote and no charge):

| Step | Renders |
|---|---|
| upgrade, quoting | `role="status"` "Working out the price…" |
| upgrade quote with card | "You pay {amount} now for the rest of this period, charged to {brand} {maskedPan}. The extra allowance is added straight away." · button "Pay {amount} and upgrade" |
| upgrade quote, no card | "Upgrades are charged to a saved card. Buy a credit pack by card once and Lemely keeps the card for later charges." · no confirm button |
| downgrade | "{tier} starts on {currentPeriodEnd}. You keep {current} until then, and nothing is charged now." · button "Schedule the change" |
| upgrade started | `PaymentProgress` for the returned `paymentId` |
| downgrade scheduled | `role="status"` "Scheduled. {tier} starts on {date}." (date = the returned subscription's `currentPeriodEnd`) |
| any failure | `role="alert"` `billingFailureMessage(err, "change your plan")` |

- [ ] **Step 1: Write the failing test**

`web/tests/unit/billingOverview.test.ts`:

```ts
import { createElement as h } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { ApiError } from "@/lib/api"
import { fx } from "./support/billingFixtures"
import { errorQuery, fakeMutation, okQuery, pendingQuery, renderStatic } from "./support/billingRender"

const s = vi.hoisted(() => ({
  summary: null as unknown,
  ownMeter: null as unknown,
  catalogue: null as unknown,
  quote: null as unknown,
  upgrade: null as unknown,
  downgrade: null as unknown,
  cancel: null as unknown,
  payment: null as unknown,
}))

vi.mock("@/lib/hooks/useBillingApi", () => ({
  useBillingSummary: () => s.summary,
  useCatalogue: () => s.catalogue,
  useUpgradeQuote: () => s.quote,
  useUpgrade: () => s.upgrade,
  useDowngrade: () => s.downgrade,
  useCancelSubscription: () => s.cancel,
  usePaymentStatus: () => s.payment,
}))
vi.mock("@/lib/hooks/useUsageApi", () => ({ useUsageMeter: () => s.ownMeter }))
vi.mock("@/components/ui/modal", () => ({
  Modal: (p: { open: boolean; title: unknown; children: unknown; footer?: unknown }) =>
    p.open ? h("div", { role: "dialog" }, h("h2", null, p.title as never), p.children as never, p.footer as never) : null,
}))

import { BillingOverview } from "@/portals/billing/BillingOverview"
import { CancelPlanDialog } from "@/portals/billing/CancelPlanDialog"
import { PlanChangeDialog } from "@/portals/billing/PlanChangeDialog"

const overview = (over: Partial<Parameters<typeof BillingOverview>[0]> = {}, path = "/student/billing") =>
  renderStatic(
    h(BillingOverview, { scope: { role: "student" }, audience: "student", beneficiaryId: null, heading: "Plan and billing", ...over }),
    path,
  )

const wireSub = { ...fx.activeSub, id: "sub1", beneficiaryUserId: "u2", isPayer: true, planTierId: "t-s-m", planCode: "x", planName: "Student Plus", pendingPlanTierId: null }

beforeEach(() => {
  s.summary = okQuery(fx.summary)
  s.ownMeter = okQuery({ ...fx.meter, seats: [{ teacherMemberId: "m1", teacherUserId: "u9", fraction: 0.4, resetsAt: "2026-12-01T00:00:00Z" }] })
  s.catalogue = okQuery(fx.studentCatalogue)
  s.quote = fakeMutation()
  s.upgrade = fakeMutation()
  s.downgrade = fakeMutation()
  s.cancel = fakeMutation()
  s.payment = Object.assign(okQuery(fx.payment), { pollingStopped: false })
})

describe("BillingOverview", () => {
  it("shows an active plan with renewal date, meters and payer actions", () => {
    const html = overview()
    expect(html).toContain("Student Plus")
    expect(html).toMatch(/EGP\s250\.00/)
    expect(html).toContain("Renews")
    expect(html).toContain("Usage 63%")
    expect(html).toContain("Seat from your teacher: 40% used")
    expect(html).toContain("Change plan")
    expect(html).toContain("Cancel plan")
    expect(html).toContain('href="/student/billing/history"')
    expect(html).toContain('href="/student/billing/receipts"')
  })

  it("explains a credits-only account", () => {
    s.summary = okQuery({ ...fx.summary, subscription: null })
    const html = overview()
    expect(html).toContain("No plan")
    expect(html).toContain('href="/student/billing/plans"')
  })

  it("shows waiting, ending, scheduled-change and past-due states", () => {
    s.summary = okQuery({ ...fx.summary, subscription: { ...fx.activeSub, status: "pending_first_payment" } })
    expect(overview()).toContain("Waiting for the first payment to confirm.")
    s.summary = okQuery({ ...fx.summary, subscription: { ...fx.activeSub, cancelAtPeriodEnd: true } })
    const ending = overview()
    expect(ending).toContain("Usage comes from credits after that.")
    expect(ending).not.toContain("Cancel plan")
    s.summary = okQuery({ ...fx.summary, subscription: { ...fx.activeSub, pendingTier: { ...fx.studentMonthly, name: "Student Lite" } } })
    expect(overview()).toContain("Changes to Student Lite on")
    s.summary = okQuery({ ...fx.summary, subscription: { ...fx.activeSub, status: "past_due", graceUntil: "2026-11-08T00:00:00Z" } })
    expect(overview()).toMatch(/role="status"[^>]*>.*renewal didn/)
  })

  it("is read-only for a non-payer and hides receipts", () => {
    s.summary = okQuery({ ...fx.summary, canManage: false, managedByName: "Mona" })
    const html = overview()
    expect(html).toContain("Mona manages this plan.")
    expect(html).not.toContain("Cancel plan")
    expect(html).not.toContain("/receipts")
  })

  it("puts the debt notice above the plan", () => {
    s.summary = okQuery({ ...fx.summary, meter: { ...fx.meter, debtUnits: 12 } })
    const html = overview()
    expect(html.indexOf("12 credits more")).toBeLessThan(html.indexOf("Student Plus"))
  })

  it("shows teacher seats from the summary with a link to manage them", () => {
    s.summary = okQuery({
      ...fx.summary,
      beneficiary: { ...fx.summary.beneficiary, audience: "teacher" },
      subscription: { ...fx.activeSub, tier: fx.teacherMonthly, extraSeats: 2 },
      seats: { capacity: 22, used: 5 },
    })
    s.catalogue = okQuery(fx.teacherCatalogue)
    const html = overview({ scope: { role: "teacher" }, audience: "teacher" }, "/teacher/billing")
    expect(html).toContain("5 of 22 seats used")
    expect(html).toContain("20 included, 2 extra")
    expect(html).toContain('href="/teacher/team"')
  })

  it("has no usage-history link for a parent and skips own seat meters for a child", () => {
    const html = overview({ scope: { role: "parent", childId: "c1" }, beneficiaryId: "c1" }, "/parent/children/c1/billing")
    expect(html).not.toContain("Usage history")
    expect(html).not.toContain("Seat from your teacher")
  })

  it("renders loading and error states", () => {
    s.summary = pendingQuery()
    expect(overview()).toContain('aria-label="Loading"')
    s.summary = errorQuery(new ApiError(500, "x"))
    expect(overview()).toContain("load your billing")
  })

  it("opens the plan-change dialog from ?change=", () => {
    s.catalogue = okQuery({ ...fx.studentCatalogue, tiers: [fx.studentMonthly, { ...fx.studentMonthly, id: "t-up", name: "Student Max", priceMinor: 40000 }] })
    expect(overview({}, "/student/billing?change=t-up")).toContain('role="dialog"')
  })
})

describe("PlanChangeDialog", () => {
  const up = { ...fx.studentMonthly, id: "t-up", name: "Student Max", priceMinor: 40000 }
  const down = { ...fx.studentMonthly, id: "t-down", name: "Student Lite", priceMinor: 10000 }
  const dialog = (tier = up, savedCard = fx.summary.savedCard) =>
    renderStatic(h(PlanChangeDialog, { open: true, onClose: () => undefined, subscription: fx.activeSub, tier, savedCard }))

  it("announces quoting an upgrade", () => {
    s.quote = fakeMutation({ isPending: true })
    expect(dialog()).toContain("Working out the price")
  })

  it("prices an upgrade against the saved card", () => {
    s.quote = fakeMutation({ isSuccess: true, data: { amountMinor: 7500, currency: "EGP", allowanceUnits: 900, periodEnd: "2026-12-01T00:00:00Z" } })
    const html = dialog()
    expect(html).toMatch(/Pay EGP\s75\.00 and upgrade/)
    expect(html).toContain("Mastercard")
  })

  it("refuses an upgrade without a saved card", () => {
    s.quote = fakeMutation({ isSuccess: true, data: { amountMinor: 7500, currency: "EGP", allowanceUnits: 900, periodEnd: "2026-12-01T00:00:00Z" } })
    const html = dialog(up, null)
    expect(html).toContain("Upgrades are charged to a saved card.")
    expect(html).not.toContain("and upgrade")
  })

  it("schedules a downgrade with no quote and no charge", () => {
    const html = dialog(down)
    expect(html).toContain("nothing is charged now")
    expect(html).toContain("Schedule the change")
  })

  it("follows an upgrade payment and reports a scheduled downgrade", () => {
    s.upgrade = fakeMutation({ isSuccess: true, data: { paymentId: "pay1", status: "pending", amountMinor: 7500, currency: "EGP" } })
    expect(dialog()).toContain("Confirming your payment")
    s.upgrade = fakeMutation()
    s.downgrade = fakeMutation({ isSuccess: true, data: { ...wireSub, pendingPlanTierId: "t-down" } })
    expect(dialog(down)).toMatch(/role="status"[^>]*>Scheduled\. Student Lite starts on/)
  })

  it("shows a seats conflict as an alert", () => {
    s.downgrade = fakeMutation({ isError: true, error: new ApiError(409, "x", { error: "seats_insufficient", message: "x" }) })
    const html = dialog(down)
    expect(html).toContain('role="alert"')
    expect(html).toContain("fewer seats than students")
  })
})

describe("CancelPlanDialog", () => {
  it("states what happens at period end and confirms after success", () => {
    const render = () =>
      renderStatic(h(CancelPlanDialog, { open: true, onClose: () => undefined, subscription: fx.activeSub, audience: "teacher" }))
    const html = render()
    expect(html).toContain("Your plan stays active until")
    expect(html).toContain("Seats stop getting monthly allowances")
    expect(html).toContain("Cancel at period end")
    s.cancel = fakeMutation({ isSuccess: true, data: { ...wireSub, cancelAtPeriodEnd: true } })
    expect(render()).toMatch(/Cancelled\. Your plan ends on/)
  })
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npx vitest run tests/unit/billingOverview.test.ts`
Expected: FAIL, "Failed to resolve import "@/portals/billing/BillingOverview"".

- [ ] **Step 3: Write `web/src/portals/billing/PaymentProgress.tsx`**

```tsx
import { paymentPhase } from "@/lib/billingFormat"
import { returnCopy } from "@/lib/checkoutReturn"
import { usePaymentStatus } from "@/lib/hooks/useBillingApi"

/*
 * Inline readout for a merchant-initiated charge (upgrade proration, extra seats; spec §5.3,
 * §5.4). The charge settles by webhook, so the dialog polls the same payment record the
 * checkout return page polls, with the same copy.
 */

export function PaymentProgress({ paymentId }: { paymentId: string }) {
  const payment = usePaymentStatus(paymentId)
  if (payment.isError) {
    return (
      <p role="alert" className="m-0 text-body-sm text-error">
        Couldn't check this payment. It is still processed on our side; reload this page in a minute.
      </p>
    )
  }
  const data = payment.data
  const copy = data
    ? returnCopy(paymentPhase(data.status), data.purpose, payment.pollingStopped)
    : returnCopy("confirming", "upgrade_proration", false)
  return (
    <div role="status" className="flex flex-col gap-1">
      <p className="m-0 text-body-md font-semibold text-on-surface">{copy.heading}</p>
      <p className="m-0 text-body-sm text-on-surface-variant">{copy.body}</p>
    </div>
  )
}
```

- [ ] **Step 4: Write `web/src/portals/billing/PlanChangeDialog.tsx`**

```tsx
import { useEffect, type ReactNode } from "react"
import { Button } from "@/components/ui/button"
import { Modal } from "@/components/ui/modal"
import { formatBillingDate, formatMoney } from "@/lib/billingFormat"
import { billingFailureMessage } from "@/lib/billingOutcome"
import type { PlanTier, SavedCardView, SubscriptionView } from "@/lib/billingTypes"
import { useDowngrade, useUpgrade, useUpgradeQuote } from "@/lib/hooks/useBillingApi"
import { PaymentProgress } from "./PaymentProgress"

/*
 * Upgrade now, downgrade at period end (spec §2.6, §5.3). An upgrade is quoted first
 * (`…/upgrade/quote`, no side effects) so the payer sees the exact prorated charge, then charged
 * to the saved card as a merchant-initiated payment and confirmed by webhook. A downgrade has no
 * charge and applies at the current period end.
 */

export function PlanChangeDialog({
  open,
  onClose,
  subscription,
  tier,
  savedCard,
}: {
  open: boolean
  onClose: () => void
  subscription: SubscriptionView
  tier: PlanTier | null
  savedCard: SavedCardView | null
}) {
  const quote = useUpgradeQuote()
  const upgrade = useUpgrade()
  const downgrade = useDowngrade()
  const { mutate: requestQuote } = quote
  const isUpgrade = tier !== null && tier.priceMinor > subscription.tier.priceMinor
  const tierId = tier?.id ?? null
  const subscriptionId = subscription.subscriptionId

  useEffect(() => {
    if (open && isUpgrade && tierId) requestQuote({ subscriptionId, planTierId: tierId })
  }, [open, isUpgrade, tierId, subscriptionId, requestQuote])

  if (!tier) return null
  const q = quote.data
  const done = upgrade.isSuccess || downgrade.isSuccess
  const failure = upgrade.isError ? upgrade.error : downgrade.isError ? downgrade.error : quote.isError ? quote.error : null
  const canConfirm = !done && (isUpgrade ? q !== undefined && savedCard !== null : true)
  const end = subscription.currentPeriodEnd ? formatBillingDate(subscription.currentPeriodEnd) : "the end of this period"

  let body: ReactNode = null
  if (upgrade.isSuccess && upgrade.data) {
    body = <PaymentProgress paymentId={upgrade.data.paymentId} />
  } else if (downgrade.isSuccess && downgrade.data) {
    body = (
      <p role="status" className="m-0 text-body-md text-on-surface">
        Scheduled. {tier.name} starts on{" "}
        {downgrade.data.currentPeriodEnd ? formatBillingDate(downgrade.data.currentPeriodEnd) : end}.
      </p>
    )
  } else if (!isUpgrade) {
    body = (
      <p className="m-0 text-body-md text-on-surface">
        {tier.name} starts on {end}. You keep {subscription.tier.name} until then, and nothing is charged now.
      </p>
    )
  } else if (quote.isPending) {
    body = (
      <p role="status" className="m-0 text-body-sm text-on-surface-variant">
        Working out the price…
      </p>
    )
  } else if (q) {
    body = savedCard ? (
      <p className="m-0 text-body-md text-on-surface">
        You pay <span className="text-data-md">{formatMoney(q.amountMinor, q.currency)}</span> now for the rest of this period,
        charged to {savedCard.brand} {savedCard.maskedPan}. The extra allowance is added straight away.
      </p>
    ) : (
      <p className="m-0 text-body-md text-on-surface">
        Upgrades are charged to a saved card. Buy a credit pack by card once and Lemely keeps the card for later charges.
      </p>
    )
  }

  const confirm = () =>
    isUpgrade ? upgrade.mutate({ subscriptionId, planTierId: tier.id }) : downgrade.mutate({ subscriptionId, planTierId: tier.id })

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={`Change to ${tier.name}`}
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            {done ? "Close" : "Not now"}
          </Button>
          {canConfirm ? (
            <Button variant="primary" loading={upgrade.isPending || downgrade.isPending} onClick={confirm}>
              {isUpgrade && q ? `Pay ${formatMoney(q.amountMinor, q.currency)} and upgrade` : "Schedule the change"}
            </Button>
          ) : null}
        </div>
      }
    >
      <div className="flex flex-col gap-3">
        {body}
        {failure ? (
          <p role="alert" className="m-0 text-body-sm text-error">
            {billingFailureMessage(failure, "change your plan")}
          </p>
        ) : null}
      </div>
    </Modal>
  )
}
```

- [ ] **Step 5: Write `web/src/portals/billing/CancelPlanDialog.tsx`**

```tsx
import { Button } from "@/components/ui/button"
import { Modal } from "@/components/ui/modal"
import { formatBillingDate } from "@/lib/billingFormat"
import { billingFailureMessage } from "@/lib/billingOutcome"
import type { Audience, SubscriptionView } from "@/lib/billingTypes"
import { useCancelSubscription } from "@/lib/hooks/useBillingApi"

/*
 * Cancel takes effect at period end; access continues until then (spec §2.6, §5.3). Unused
 * allowance ends with the period (no rollover), and a teacher's seats stop receiving monthly
 * allowances once the plan ends (spec §5.9). The route returns the subscription.
 */

export function CancelPlanDialog({
  open,
  onClose,
  subscription,
  audience,
}: {
  open: boolean
  onClose: () => void
  subscription: SubscriptionView
  audience: Audience
}) {
  const cancel = useCancelSubscription()
  const end = subscription.currentPeriodEnd ? formatBillingDate(subscription.currentPeriodEnd) : "the end of this period"
  const endsOn = cancel.data?.currentPeriodEnd ? formatBillingDate(cancel.data.currentPeriodEnd) : end
  return (
    <Modal
      open={open}
      onClose={onClose}
      size="sm"
      dismissible={!cancel.isPending}
      title="Cancel your plan"
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            {cancel.isSuccess ? "Close" : "Keep my plan"}
          </Button>
          {cancel.isSuccess ? null : (
            <Button variant="primary" loading={cancel.isPending} onClick={() => cancel.mutate({ subscriptionId: subscription.subscriptionId })}>
              Cancel at period end
            </Button>
          )}
        </div>
      }
    >
      {cancel.isSuccess ? (
        <p role="status" className="m-0 text-body-md text-on-surface">
          Cancelled. Your plan ends on {endsOn}.
        </p>
      ) : (
        <div className="flex flex-col gap-2 text-body-md text-on-surface">
          <p className="m-0">
            Your plan stays active until {end}. After that, usage comes from credits only, and any unused allowance ends with the
            period.
          </p>
          {audience === "teacher" ? <p className="m-0">Seats stop getting monthly allowances when the plan ends.</p> : null}
          {cancel.isError ? (
            <p role="alert" className="m-0 text-body-sm text-error">
              {billingFailureMessage(cancel.error, "cancel your plan")}
            </p>
          ) : null}
        </div>
      )}
    </Modal>
  )
}
```

- [ ] **Step 6: Write `web/src/portals/billing/BillingOverview.tsx`**

```tsx
import { useState, type ReactNode } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { CreditBalanceCard } from "@/components/billing/credit-balance"
import { DebtNotice } from "@/components/billing/debt-notice"
import { UsageMeterCard } from "@/components/billing/usage-meter"
import { Button } from "@/components/ui/button"
import { Card, CardBody } from "@/components/ui/card"
import { PageHeaderSkeleton } from "@/components/ui/loading-shapes"
import { Eyebrow } from "@/components/ui/primitives"
import { QueryState } from "@/components/ui/query-state"
import { formatBillingDate, formatMoney, intervalLabel, isLiveSubscription } from "@/lib/billingFormat"
import { billingPaths, type BillingScope } from "@/lib/billingPaths"
import type { Audience, BillingSummary } from "@/lib/billingTypes"
import { useBillingSummary, useCatalogue } from "@/lib/hooks/useBillingApi"
import { useUsageMeter } from "@/lib/hooks/useUsageApi"
import { CancelPlanDialog } from "./CancelPlanDialog"
import { PlanChangeDialog } from "./PlanChangeDialog"

/*
 * The billing page body shared by the student, teacher and parent-for-child screens, read from
 * `GET /billing/summary` (A5). The beneficiary sees plan, usage and balance; only the payer
 * (`canManage`) sees buy, change, cancel and receipts (spec §7 authorization).
 */

const LINK =
  "inline-flex items-center justify-center rounded-button px-4 py-2.5 text-label focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary pointer-coarse:min-h-11"
const TEXT_LINK =
  "font-medium text-primary underline-offset-2 hover:underline pointer-coarse:min-h-11 pointer-coarse:inline-flex pointer-coarse:items-center"

function PlanCard({
  summary,
  audience,
  plansHref,
  onCancel,
}: {
  summary: BillingSummary
  audience: Audience
  plansHref: string
  onCancel: () => void
}) {
  const sub = summary.subscription
  const live = isLiveSubscription(sub?.status)
  return (
    <Card>
      <CardBody className="flex flex-col gap-3">
        <h2 className="m-0 text-display-sm text-on-surface">{live && sub ? sub.tier.name : "No plan"}</h2>
        {!live || !sub ? (
          <p className="m-0 text-body-md text-on-surface-variant">You're using credits only.</p>
        ) : (
          <>
            <p className="m-0">
              <span className="text-data-md text-on-surface">{formatMoney(sub.tier.priceMinor, sub.tier.currency)}</span>{" "}
              <span className="text-body-sm text-on-surface-variant">{intervalLabel(sub.tier.interval)}</span>
            </p>
            {sub.status === "pending_first_payment" ? (
              <p className="m-0 text-body-sm text-on-surface-variant">Waiting for the first payment to confirm.</p>
            ) : sub.cancelAtPeriodEnd && sub.currentPeriodEnd ? (
              <p className="m-0 text-body-sm text-on-surface-variant">
                Ends {formatBillingDate(sub.currentPeriodEnd)}. Usage comes from credits after that.
              </p>
            ) : sub.currentPeriodEnd ? (
              <p className="m-0 text-body-sm text-on-surface-variant">Renews {formatBillingDate(sub.currentPeriodEnd)}</p>
            ) : null}
            {sub.pendingTier && sub.currentPeriodEnd ? (
              <p className="m-0 text-body-sm text-on-surface-variant">
                Changes to {sub.pendingTier.name} on {formatBillingDate(sub.currentPeriodEnd)}
              </p>
            ) : null}
            {audience === "teacher" && summary.seats ? (
              <div className="flex flex-wrap items-center gap-3 text-body-sm text-on-surface">
                <span>
                  {summary.seats.used} of {summary.seats.capacity} seats used
                </span>
                <span className="text-on-surface-variant">
                  {sub.tier.includedSeats ?? 0} included, {sub.extraSeats} extra
                </span>
                <Link to="/teacher/team" className={TEXT_LINK}>
                  Manage seats
                </Link>
              </div>
            ) : null}
          </>
        )}
        {summary.canManage ? (
          <div className="flex flex-wrap gap-2">
            <Link to={plansHref} className={`${LINK} bg-primary text-on-primary hover:bg-primary-hover`}>
              {live ? "Change plan" : "See plans"}
            </Link>
            {live && sub && sub.status !== "pending_first_payment" && !sub.cancelAtPeriodEnd ? (
              <Button variant="ghost" onClick={onCancel}>
                Cancel plan
              </Button>
            ) : null}
          </div>
        ) : (
          <p className="m-0 text-body-sm text-on-surface-variant">{summary.managedByName ?? "Someone else"} manages this plan.</p>
        )}
      </CardBody>
    </Card>
  )
}

export function BillingOverview({
  scope,
  audience,
  beneficiaryId,
  heading,
  extra,
}: {
  scope: BillingScope
  audience: Audience
  beneficiaryId: string | null
  heading: string
  extra?: ReactNode
}) {
  const paths = billingPaths(scope)
  const summary = useBillingSummary(beneficiaryId)
  // Own seat meters only: `/usage/meter` serves the caller (M6), the summary carries none.
  const ownMeter = useUsageMeter()
  const catalogue = useCatalogue(audience)
  const [params, setParams] = useSearchParams()
  const [cancelOpen, setCancelOpen] = useState(false)
  const changeTo = params.get("change")
  const changeTier = catalogue.data?.tiers.find((t) => t.id === changeTo) ?? null
  const closeChange = () => {
    const next = new URLSearchParams(params)
    next.delete("change")
    setParams(next, { replace: true })
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-2">
        <Eyebrow>Account</Eyebrow>
        <h1 className="m-0 text-display-md text-on-surface">{heading}</h1>
      </div>
      <QueryState query={summary} skeleton={<PageHeaderSkeleton />} error={{ heading: "Couldn't load your billing" }}>
        {(s) => {
          const sub = s.subscription
          const live = isLiveSubscription(sub?.status)
          const meter = beneficiaryId === null ? { ...s.meter, seats: ownMeter.data?.seats ?? [] } : s.meter
          return (
            <>
              {sub?.status === "past_due" && sub.graceUntil ? (
                <div role="status" className="rounded-lg bg-surface-container-high p-4 text-body-sm text-on-surface">
                  Your last renewal didn't go through. Paymob is retrying, and your plan keeps working until{" "}
                  {formatBillingDate(sub.graceUntil)}. Check the card with your bank if it keeps failing.
                </div>
              ) : null}
              <DebtNotice debtUnits={meter.debtUnits} audience={audience} buyHref={s.canManage ? paths.packs : null} />
              <PlanCard summary={s} audience={audience} plansHref={paths.plans} onCancel={() => setCancelOpen(true)} />
              <div className="grid gap-4 md:grid-cols-2">
                <UsageMeterCard meter={meter} />
                <CreditBalanceCard credits={meter.credits} now={new Date()} buyHref={s.canManage ? paths.packs : null} />
              </div>
              {extra}
              <nav aria-label="More billing" className="flex flex-wrap gap-4 text-body-sm">
                {paths.history ? (
                  <Link to={paths.history} className={TEXT_LINK}>
                    Usage history
                  </Link>
                ) : null}
                {s.canManage ? (
                  <Link to={paths.receipts} className={TEXT_LINK}>
                    Receipts
                  </Link>
                ) : null}
              </nav>
              {live && sub && s.canManage ? (
                <>
                  <PlanChangeDialog
                    open={changeTier !== null && changeTier.id !== sub.tier.id}
                    onClose={closeChange}
                    subscription={sub}
                    tier={changeTier}
                    savedCard={s.savedCard}
                  />
                  <CancelPlanDialog open={cancelOpen} onClose={() => setCancelOpen(false)} subscription={sub} audience={audience} />
                </>
              ) : null}
            </>
          )
        }}
      </QueryState>
    </div>
  )
}
```

- [ ] **Step 7: Write `web/src/portals/billing/BillingScreens.tsx`**

```tsx
import { BillingOverview } from "./BillingOverview"

/* Route elements for `/student/billing` and `/teacher/billing`. */

export function StudentBilling() {
  return <BillingOverview scope={{ role: "student" }} audience="student" beneficiaryId={null} heading="Plan and billing" />
}

export function TeacherBilling() {
  return <BillingOverview scope={{ role: "teacher" }} audience="teacher" beneficiaryId={null} heading="Plan and billing" />
}
```

- [ ] **Step 8: Run the test to verify it passes**

Run: `npx vitest run tests/unit/billingOverview.test.ts`
Expected: PASS.

- [ ] **Step 9: Mount routes and navigation**

`web/src/portals/student/index.tsx`: lazy import

```tsx
const StudentBilling = lazy(() =>
  import("@/portals/billing/BillingScreens").then((m) => ({ default: m.StudentBilling })),
)
```

and a child before `billing/plans`:

```tsx
    {
      path: "billing",
      element: <StudentBilling />,
      handle: { title: "Plan and billing", skeleton: "page-header" },
    },
```

`web/src/portals/student/data.ts`: import `CreditCard` from `@phosphor-icons/react` alongside
the other icons; add `{ to: "/student/billing", label: "Plan and billing", icon: CreditCard },`
directly before the Settings entry in `navGroups[0].items`; add to the `crumbs` map:

```ts
  "/student/billing": "Home / Plan and billing",
  "/student/billing/plans": "Home / Plan and billing / Plans",
  "/student/billing/history": "Home / Plan and billing / Usage history",
  "/student/billing/receipts": "Home / Plan and billing / Receipts",
```

`web/src/portals/teacher/data.ts`: add `| "billing"` to `NavItem["icon"]`; add
`{ to: "/teacher/billing", label: "Plan and billing", icon: "billing" },` directly before the
Settings entry; in `resolveTrail`, before the tutoring arms, add:

```ts
  const billingChild = path.match(/^\/teacher\/billing\/(plans|history|receipts)$/)
  if (billingChild) {
    const label = { plans: "Plans", history: "Usage history", receipts: "Receipts" }[
      billingChild[1] as "plans" | "history" | "receipts"
    ]
    return [root, { label: "Plan and billing", to: "/teacher/billing" }, { label }]
  }
```

`web/src/portals/teacher/index.tsx`: import `CreditCard` from `@phosphor-icons/react`, add
`billing: CreditCard,` to `NAV_ICON`; lazy import `TeacherBilling` from
`@/portals/billing/BillingScreens`; add a child before `billing/plans`:

```tsx
    {
      path: "billing",
      element: <TeacherBilling />,
      handle: { title: "Plan and billing", skeleton: "page-header" },
    },
```

If `web/tests/unit/navigation.test.ts` pins the exact student or teacher nav list, add the new
"Plan and billing" entry to that expectation in the same position; do not loosen the test.

- [ ] **Step 10: Run the frontend gate**

```bash
npm run typecheck
npx vitest run tests/unit/billingOverview.test.ts tests/unit/navigation.test.ts tests/unit/navigationModel.test.ts tests/unit/navRowIconGuard.test.ts tests/unit/navShells.test.ts tests/unit/documentMeta.test.ts tests/unit/settingsTabs.test.ts $SCAN
npm run lint && npm run check:copy && npm run build
```
Expected: all exit 0.

- [ ] **Step 11: Commit**

```bash
cd /home/sico/Code/Lemely/.claude/worktrees/paymob-integration
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files && graphify update .
P="web/src/portals/billing/PaymentProgress.tsx web/src/portals/billing/PlanChangeDialog.tsx web/src/portals/billing/CancelPlanDialog.tsx web/src/portals/billing/BillingOverview.tsx web/src/portals/billing/BillingScreens.tsx web/src/portals/student/index.tsx web/src/portals/student/data.ts web/src/portals/teacher/index.tsx web/src/portals/teacher/data.ts web/tests/unit/billingOverview.test.ts"
git diff --quiet -- web/tests/unit/navigation.test.ts || P="$P web/tests/unit/navigation.test.ts"
git add $P
git commit -S -m "feat(web): billing overview with plan change and cancel" -- $P
```

---

### Task 6: Parent: billing for a linked child

**Files:**
- Create: `web/src/portals/billing/ParentBilling.tsx`
- Modify: `web/src/portals/parent/index.tsx` (route `children/:childId/billing`, trail arms)
- Modify: `web/src/portals/parent/screens/ChildOverview.tsx` (add the billing link)
- Test: `web/tests/unit/parentBilling.test.ts`

**Interfaces:**
- Consumes (Tasks 1, 5): `BillingOverview`, `billingPaths`, `useChildren` from
  `web/src/lib/hooks/useParentApi.ts` (`ChildList.children[].childId/displayName`).
- Produces: screen `ParentChildBilling`; component `<ChildBillingLink childId={string} />`.

Behaviour (spec §2.1, §7): a linked parent is the payer for a child. The child is the
beneficiary and owns the balance; the parent owns the card, cancellation and receipts. The page
heading names the child ("Plan and billing for Omar"); before `useChildren` resolves it reads
"Plan and billing". Every billing request carries `beneficiaryId = childId`; the server rejects
an unlinked child with 403, which renders the overview's error state. The child sees the same
plan, meter and credits on `/student/billing` with `canManage === false` and the parent's name
(Task 5 covers that state).

- [ ] **Step 1: Write the failing test**

`web/tests/unit/parentBilling.test.ts`:

```ts
import { createElement as h } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { renderAt, renderStatic, okQuery, pendingQuery } from "./support/billingRender"

const s = vi.hoisted(() => ({ children: null as unknown, overviewProps: [] as Array<Record<string, unknown>> }))
vi.mock("@/lib/hooks/useParentApi", () => ({ useChildren: () => s.children }))
vi.mock("@/portals/billing/BillingOverview", () => ({
  BillingOverview: (p: Record<string, unknown>) => {
    s.overviewProps.push(p)
    return h("h1", null, p.heading as string)
  },
}))

import { ChildBillingLink, ParentChildBilling } from "@/portals/billing/ParentBilling"

beforeEach(() => {
  s.overviewProps = []
  s.children = okQuery({ children: [{ childId: "c1", displayName: "Omar", classes: [] }] })
})

describe("ParentChildBilling", () => {
  it("scopes the overview to the child and names them", () => {
    const html = renderAt(h(ParentChildBilling), "/parent/children/:childId/billing", "/parent/children/c1/billing")
    expect(html).toContain("Plan and billing for Omar")
    expect(s.overviewProps[0]).toMatchObject({
      scope: { role: "parent", childId: "c1" },
      audience: "student",
      beneficiaryId: "c1",
    })
  })

  it("falls back to a generic heading before the child list loads", () => {
    s.children = pendingQuery()
    const html = renderAt(h(ParentChildBilling), "/parent/children/:childId/billing", "/parent/children/c1/billing")
    expect(html).toContain(">Plan and billing<")
  })
})

describe("ChildBillingLink", () => {
  it("links to the child's billing page", () => {
    expect(renderStatic(h(ChildBillingLink, { childId: "c1" }))).toContain('href="/parent/children/c1/billing"')
  })
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npx vitest run tests/unit/parentBilling.test.ts`
Expected: FAIL, "Failed to resolve import "@/portals/billing/ParentBilling"".

- [ ] **Step 3: Write `web/src/portals/billing/ParentBilling.tsx`**

```tsx
import { CaretRight } from "@phosphor-icons/react"
import { Link, useParams } from "react-router-dom"
import { billingPaths } from "@/lib/billingPaths"
import { useChildren } from "@/lib/hooks/useParentApi"
import { BillingOverview } from "./BillingOverview"

/*
 * A parent paying for a linked child (spec §2.1). The child owns the balance; the parent is
 * the payer, so the overview's payer-only actions and receipts appear here, scoped to the
 * child by `beneficiaryId`.
 */

export function ParentChildBilling() {
  const { childId = "" } = useParams<{ childId: string }>()
  const children = useChildren()
  const name = children.data?.children.find((c) => c.childId === childId)?.displayName
  return (
    <BillingOverview
      scope={{ role: "parent", childId }}
      audience="student"
      beneficiaryId={childId}
      heading={name ? `Plan and billing for ${name}` : "Plan and billing"}
    />
  )
}

/** One quiet link on the child overview, beside "Tutoring". */
export function ChildBillingLink({ childId }: { childId: string }) {
  return (
    <Link
      to={billingPaths({ role: "parent", childId }).overview}
      className="mt-1 inline-flex w-fit items-center gap-1.5 rounded-md text-body-md text-on-primary-container underline underline-offset-4 transition-colors hover:text-primary-hover focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary pointer-coarse:min-h-11"
    >
      Plan and billing
      <CaretRight size={14} aria-hidden="true" />
    </Link>
  )
}
```

(`CaretRight` points inline-end in LTR; it is the same glyph and treatment the adjacent
"Tutoring" link already uses, so an RTL flip is handled in one place for both.)

- [ ] **Step 4: Run it to verify it passes**

Run: `npx vitest run tests/unit/parentBilling.test.ts`
Expected: PASS.

- [ ] **Step 5: Mount the route, trail and link**

`web/src/portals/parent/index.tsx`: lazy import

```tsx
const ParentChildBilling = lazy(() =>
  import("@/portals/billing/ParentBilling").then((m) => ({ default: m.ParentChildBilling })),
)
```

child route after `children/:childId/tutor-access`, before `children/:childId/billing/plans`:

```tsx
    {
      path: "children/:childId/billing",
      element: <ParentChildBilling />,
      handle: { title: "Plan and billing", skeleton: "page-header" },
    },
```

In `ParentTrail`, before the `/subjects/` arm, add:

```tsx
  } else if (path === `${childOverview}/billing`) {
    trail.push({ label: "Overview", to: childOverview }, { label: "Plan and billing" })
  } else if (path === `${childOverview}/billing/plans`) {
    trail.push(
      { label: "Overview", to: childOverview },
      { label: "Plan and billing", to: `${childOverview}/billing` },
      { label: "Plans" },
    )
```

`web/src/portals/parent/screens/ChildOverview.tsx`: import
`{ ChildBillingLink } from "@/portals/billing/ParentBilling"` and render
`<ChildBillingLink childId={childId} />` directly after the existing "Tutoring" `<Link>` inside
the heading block.

- [ ] **Step 6: Run the frontend gate**

```bash
npm run typecheck
npx vitest run tests/unit/parentBilling.test.ts tests/unit/parentOutcome.test.ts tests/unit/parentTutoring.test.ts $SCAN
npm run lint && npm run check:copy && npm run build
```
Expected: all exit 0.

- [ ] **Step 7: Commit**

```bash
cd /home/sico/Code/Lemely/.claude/worktrees/paymob-integration
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files && graphify update .
P="web/src/portals/billing/ParentBilling.tsx web/src/portals/parent/index.tsx web/src/portals/parent/screens/ChildOverview.tsx web/tests/unit/parentBilling.test.ts"
git add $P
git commit -S -m "feat(web): parent billing for a linked child" -- $P
```

---

### Task 7: Usage history and receipts

**Files:**
- Create: `web/src/lib/usageHistoryModel.ts`
- Create: `web/src/portals/billing/UsageHistory.tsx`
- Create: `web/src/portals/billing/Receipts.tsx`
- Modify: `web/src/portals/student/index.tsx`, `web/src/portals/teacher/index.tsx`,
  `web/src/portals/parent/index.tsx` (routes)
- Test: `web/tests/unit/usageHistory.test.ts`

**Interfaces:**
- Consumes (Task 1): `useUsageHistory`, `useReceipts`, `billingPaths`, `formatMoney`,
  `formatBillingDate`, types `UsageJobRow`, `Receipt`, `MeteredAction`, `PaymentPurpose`.
- Produces: `actionLabel(action)`, `jobChargeText(row)`, `jobEstimateText(row)`,
  `jobStatusText(row)`, `purposeLabel(purpose)`, `receiptStatusText(receipt)` from
  `usageHistoryModel.ts`; screens `StudentUsageHistory`, `TeacherUsageHistory`,
  `StudentReceipts`, `TeacherReceipts`, `ParentReceipts`; generic `<UsageHistoryView backHref />`,
  `<ReceiptsView backHref />`.

Behaviour: usage history lists each metered job with its estimate range and actual charge
(spec §2.4: no receipts for usage), for the signed-in caller only (A19; M6: no parent view of a
child's history). Rows come as display values (plan 04 `UsageJobDTO`): the plan share in
percentage points (`percentOfPlan`, `estimatePercentOfPlan`) and the credit part in credits
(`credits`, `estimateCredits`); a `mixed` job shows both ("1% of plan + 2 credits"). Allowance
rows never carry raw units, so allowance sizes stay hidden (spec §2.1). Released and expired jobs
read "No charge" ("Failed jobs cost nothing"). Debt shows as "(n credits went below zero)". 25 rows per page, "Load more" while `nextCursor`. Receipts (A11) list only real
money (spec §2.5), newest first, each with description, purpose, amount, date and status;
refunded payments read "Refunded" / "Partly refunded" (M9: no card, order id or refunded amount
in `ReceiptDTO`). Receipts are the payer's: a parent sees one list across children.

Table states: loading skeleton; error (`QueryState`); empty ("No usage yet. Jobs you run appear
here with their estimate and what they actually cost." / "No receipts yet. Payments for plans,
seats and credit packs appear here.").

- [ ] **Step 1: Write the failing test**

`web/tests/unit/usageHistory.test.ts`:

```ts
import { createElement as h } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { fx } from "./support/billingFixtures"
import { okQuery, renderStatic } from "./support/billingRender"
import {
  actionLabel,
  jobChargeText,
  jobEstimateText,
  jobStatusText,
  purposeLabel,
  receiptStatusText,
} from "@/lib/usageHistoryModel"

const s = vi.hoisted(() => ({ history: null as unknown, receipts: null as unknown }))
vi.mock("@/lib/hooks/useUsageApi", () => ({ useUsageHistory: () => s.history }))
vi.mock("@/lib/hooks/useBillingApi", () => ({ useReceipts: () => s.receipts }))

import { ReceiptsView } from "@/portals/billing/Receipts"
import { UsageHistoryView } from "@/portals/billing/UsageHistory"

const infinite = (pages: unknown[], hasNextPage = false) => ({
  ...okQuery({ pages, pageParams: [null] }),
  hasNextPage,
  isFetchingNextPage: false,
  fetchNextPage: vi.fn(),
})

beforeEach(() => {
  s.history = infinite([fx.history])
  s.receipts = okQuery({ receipts: [fx.receipt] })
})

describe("usage history model", () => {
  it("labels actions and formats estimate and charge from the display values", () => {
    expect(actionLabel("mark_paper")).toBe("Paper marking")
    expect(actionLabel("study_plan")).toBe("Weekly study plan")
    expect(actionLabel("generate_flashcards")).toBe("Flashcard generation")
    expect(jobEstimateText(fx.job)).toBe("3–5 credits")
    expect(jobEstimateText({ ...fx.job, estimateCredits: [4, 4] })).toBe("4 credits")
    expect(jobChargeText(fx.job)).toBe("4 credits")
    const plan = { ...fx.job, paidBy: "allowance" as const, credits: null, percentOfPlan: 3, estimateCredits: null, estimatePercentOfPlan: [2, 4] as [number, number] }
    expect(jobEstimateText(plan)).toBe("2–4% of plan")
    expect(jobChargeText(plan)).toBe("3% of plan")
    const mixed = { ...plan, paidBy: "mixed" as const, percentOfPlan: 1, credits: 2, estimateCredits: [1, 3] as [number, number] }
    expect(jobEstimateText(mixed)).toBe("2–4% of plan + 1–3 credits")
    expect(jobChargeText(mixed)).toBe("1% of plan + 2 credits")
    expect(jobEstimateText({ ...fx.job, estimateCredits: null })).toBe("—")
  })

  it("says failed jobs cost nothing and shows debt", () => {
    expect(jobChargeText({ ...fx.job, status: "released", credits: null, paidBy: "none" })).toBe("No charge")
    expect(jobChargeText({ ...fx.job, status: "expired", credits: null, paidBy: "none" })).toBe("No charge")
    expect(jobStatusText({ ...fx.job, status: "open", credits: null })).toBe("Running")
    expect(jobChargeText({ ...fx.job, credits: 9, debtCredits: 4 })).toBe("9 credits (4 credits went below zero)")
  })

  it("labels payment purposes and refunds", () => {
    expect(purposeLabel("extra_seats")).toBe("Extra seats")
    expect(receiptStatusText(fx.receipt)).toBeNull()
    expect(receiptStatusText({ ...fx.receipt, status: "refunded" })).toBe("Refunded")
    expect(receiptStatusText({ ...fx.receipt, status: "partially_refunded" })).toBe("Partly refunded")
  })
})

describe("UsageHistoryView", () => {
  it("renders a table with estimate and actual columns", () => {
    const html = renderStatic(h(UsageHistoryView, { backHref: "/student/billing" }))
    expect(html).toContain("<table")
    expect(html).toContain("Estimate")
    expect(html).toContain("Charged")
    expect(html).toContain("Paper marking")
    expect(html).toContain("3–5 credits")
  })

  it("offers more pages while there is a cursor", () => {
    s.history = infinite([{ jobs: [fx.job], nextCursor: "n2" }], true)
    expect(renderStatic(h(UsageHistoryView, { backHref: "/teacher/billing" }))).toContain("Load more")
  })

  it("explains an empty history", () => {
    s.history = infinite([{ jobs: [], nextCursor: null }])
    expect(renderStatic(h(UsageHistoryView, { backHref: "/x" }))).toContain("No usage yet.")
  })
})

describe("ReceiptsView", () => {
  it("lists money receipts with description, purpose and amount", () => {
    const html = renderStatic(h(ReceiptsView, { backHref: "/student/billing" }))
    expect(html).toContain("500 credits")
    expect(html).toMatch(/EGP\s150\.00/)
    expect(html).toContain("Credit pack")
  })

  it("explains an empty list", () => {
    s.receipts = okQuery({ receipts: [] })
    expect(renderStatic(h(ReceiptsView, { backHref: "/x" }))).toContain("No receipts yet.")
  })
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npx vitest run tests/unit/usageHistory.test.ts`
Expected: FAIL, "Failed to resolve import "@/lib/usageHistoryModel"".

- [ ] **Step 3: Write `web/src/lib/usageHistoryModel.ts`**

```ts
import { formatCredits } from "@/lib/billingFormat"
import type { MeteredAction, PaymentPurpose, Receipt, UsageJobRow } from "@/lib/billingTypes"

/* Row text for the usage history and receipts tables. Pure, unit-tested. */

const ACTIONS: Record<MeteredAction, string> = {
  mark_paper: "Paper marking",
  regrade: "Regrade",
  generate_quiz: "Quiz generation",
  preview_quiz: "Quiz preview",
  self_review: "Self-review",
  study_plan: "Weekly study plan",
  mark_quiz: "Quiz marking",
  generate_flashcards: "Flashcard generation",
}

export function actionLabel(action: MeteredAction): string {
  return ACTIONS[action]
}

/* Plan 04 sends display values: plan share in percentage points, credit part in credits. */
function span([lo, hi]: [number, number], unit: (n: number) => string, rangeUnit: string): string {
  return lo === hi ? unit(hi) : `${lo}–${hi}${rangeUnit}`
}
const pct = (n: number) => `${n}% of plan`

export function jobEstimateText(row: UsageJobRow): string {
  const parts = [
    row.estimatePercentOfPlan ? span(row.estimatePercentOfPlan, pct, "% of plan") : null,
    row.estimateCredits ? span(row.estimateCredits, (n) => formatCredits(n), " credits") : null,
  ].filter((x): x is string => x !== null)
  return parts.length > 0 ? parts.join(" + ") : "—"
}

export function jobStatusText(row: UsageJobRow): string {
  switch (row.status) {
    case "open":
      return "Running"
    case "settled":
      return "Done"
    case "released":
      return "Failed, not charged"
    case "expired":
      return "Timed out, not charged"
  }
}

export function jobChargeText(row: UsageJobRow): string {
  if (row.status === "open") return "Not charged yet"
  const parts = [
    row.percentOfPlan !== null ? pct(row.percentOfPlan) : null,
    row.credits !== null ? formatCredits(row.credits) : null,
  ].filter((x): x is string => x !== null)
  if (parts.length === 0) return "No charge"
  const base = parts.join(" + ")
  return row.debtCredits ? `${base} (${formatCredits(row.debtCredits)} went below zero)` : base
}

const PURPOSES: Record<PaymentPurpose, string> = {
  subscription_first: "Plan",
  subscription_renewal: "Plan renewal",
  upgrade_proration: "Plan upgrade",
  extra_seats: "Extra seats",
  credit_pack: "Credit pack",
  auto_topup: "Auto top-up",
}

export function purposeLabel(purpose: PaymentPurpose): string {
  return PURPOSES[purpose]
}

/** M9: `ReceiptDTO` has no refunded amount, so the status is named, not priced. */
export function receiptStatusText(receipt: Receipt): string | null {
  if (receipt.status === "refunded") return "Refunded"
  if (receipt.status === "partially_refunded") return "Partly refunded"
  return null
}
```

- [ ] **Step 4: Write `web/src/portals/billing/UsageHistory.tsx`**

```tsx
import { Link } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { ListSkeleton } from "@/components/ui/loading-shapes"
import { Eyebrow } from "@/components/ui/primitives"
import { QueryState } from "@/components/ui/query-state"
import { EmptyState } from "@/components/ui/state-views"
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table"
import { formatBillingDate } from "@/lib/billingFormat"
import { billingPaths } from "@/lib/billingPaths"
import { useUsageHistory } from "@/lib/hooks/useUsageApi"
import { actionLabel, jobChargeText, jobEstimateText, jobStatusText } from "@/lib/usageHistoryModel"

/*
 * Usage history (spec §2.4): one row per metered job, estimate against actual. This is the
 * whole record of usage; there are no usage receipts.
 */

export function UsageHistoryView({ backHref }: { backHref: string }) {
  const history = useUsageHistory()
  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-2">
        <Eyebrow>
          <Link to={backHref} className="underline-offset-2 hover:underline">Plan and billing</Link>
        </Eyebrow>
        <h1 className="m-0 text-display-md text-on-surface">Usage history</h1>
      </div>
      <QueryState
        query={history}
        skeleton={<ListSkeleton />}
        error={{ heading: "Couldn't load your usage history" }}
        isEmpty={(d) => d.pages.every((p) => p.jobs.length === 0)}
        empty={
          <EmptyState
            heading="No usage yet."
            body="Jobs you run appear here with their estimate and what they actually cost."
          />
        }
      >
        {(d) => (
          <>
            <Table>
              <caption className="sr-only">Usage history</caption>
              <THead>
                <TR>
                  <TH>Date</TH>
                  <TH>Action</TH>
                  <TH>Status</TH>
                  <TH numeric>Estimate</TH>
                  <TH numeric>Charged</TH>
                </TR>
              </THead>
              <TBody>
                {d.pages.flatMap((p) => p.jobs).map((row) => (
                  <TR key={row.jobId}>
                    <TD>{formatBillingDate(row.createdAt)}</TD>
                    <TD>
                      {actionLabel(row.action)}
                    </TD>
                    <TD>{jobStatusText(row)}</TD>
                    <TD numeric>{jobEstimateText(row)}</TD>
                    <TD numeric>{jobChargeText(row)}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
            {history.hasNextPage ? (
              <Button variant="secondary" loading={history.isFetchingNextPage} onClick={() => void history.fetchNextPage()}>
                Load more
              </Button>
            ) : null}
          </>
        )}
      </QueryState>
    </div>
  )
}

export function StudentUsageHistory() {
  return <UsageHistoryView backHref={billingPaths({ role: "student" }).overview} />
}

export function TeacherUsageHistory() {
  return <UsageHistoryView backHref={billingPaths({ role: "teacher" }).overview} />
}
```

`Table` (`web/src/components/ui/table.tsx`) renders its children inside `<table>`, so the
`<caption>` gives the table its accessible name; its `density` prop stays at the default
`"comfortable"`.

- [ ] **Step 5: Write `web/src/portals/billing/Receipts.tsx`**

```tsx
import { Link } from "react-router-dom"
import { ListSkeleton } from "@/components/ui/loading-shapes"
import { Eyebrow } from "@/components/ui/primitives"
import { QueryState } from "@/components/ui/query-state"
import { EmptyState } from "@/components/ui/state-views"
import { formatBillingDate, formatMoney } from "@/lib/billingFormat"
import { billingPaths } from "@/lib/billingPaths"
import { useReceipts } from "@/lib/hooks/useBillingApi"
import { purposeLabel, receiptStatusText } from "@/lib/usageHistoryModel"

/*
 * Receipts exist only for real money (spec §2.5). A `paid` payment is the receipt; the payer
 * sees them, so a parent's list spans every child they pay for.
 */

export function ReceiptsView({ backHref }: { backHref: string }) {
  const receipts = useReceipts()
  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-2">
        <Eyebrow>
          <Link to={backHref} className="underline-offset-2 hover:underline">Plan and billing</Link>
        </Eyebrow>
        <h1 className="m-0 text-display-md text-on-surface">Receipts</h1>
      </div>
      <QueryState
        query={receipts}
        skeleton={<ListSkeleton />}
        error={{ heading: "Couldn't load your receipts" }}
        isEmpty={(d) => d.receipts.length === 0}
        empty={<EmptyState heading="No receipts yet." body="Payments for plans, seats and credit packs appear here." />}
      >
        {(d) => (
          <ul className="m-0 flex list-none flex-col gap-3 p-0">
            {d.receipts.map((r) => {
              const refund = receiptStatusText(r)
              return (
                <li key={r.paymentId} className="flex flex-col gap-1 rounded-lg border border-outline-variant bg-surface-container-lowest p-4">
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <span className="text-body-md font-semibold text-on-surface">{r.description}</span>
                    <span className="text-data-md text-on-surface">{formatMoney(r.amountMinor, r.currency)}</span>
                  </div>
                  <p className="m-0 text-body-sm text-on-surface-variant">
                    {purposeLabel(r.purpose)} · {formatBillingDate(r.paidAt)}
                  </p>
                  {refund ? <p className="m-0 text-body-sm text-on-surface">{refund}</p> : null}
                </li>
              )
            })}
          </ul>
        )}
      </QueryState>
    </div>
  )
}

export function StudentReceipts() {
  return <ReceiptsView backHref={billingPaths({ role: "student" }).overview} />
}

export function TeacherReceipts() {
  return <ReceiptsView backHref={billingPaths({ role: "teacher" }).overview} />
}

/** All of a parent's receipts, across children: receipts belong to the payer. */
export function ParentReceipts() {
  return <ReceiptsView backHref="/parent" />
}
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `npx vitest run tests/unit/usageHistory.test.ts`
Expected: PASS.

- [ ] **Step 7: Mount the routes**

Student (`web/src/portals/student/index.tsx`) and teacher (`web/src/portals/teacher/index.tsx`):
lazy-import `StudentUsageHistory`/`TeacherUsageHistory` from `@/portals/billing/UsageHistory`
and `StudentReceipts`/`TeacherReceipts` from `@/portals/billing/Receipts`, then add after the
`billing/plans` child:

```tsx
    {
      path: "billing/history",
      element: <StudentUsageHistory />,
      handle: { title: "Usage history", skeleton: "list" },
    },
    {
      path: "billing/receipts",
      element: <StudentReceipts />,
      handle: { title: "Receipts", skeleton: "list" },
    },
```

(teacher: the same two children with `TeacherUsageHistory` and `TeacherReceipts`).

Parent (`web/src/portals/parent/index.tsx`): lazy-import `ParentReceipts`; add after
`children/:childId/billing/plans` (no child usage-history route: M6):

```tsx
    {
      path: "billing/receipts",
      element: <ParentReceipts />,
      handle: { title: "Receipts", skeleton: "list" },
    },
```

- [ ] **Step 8: Run the frontend gate**

```bash
npm run typecheck
npx vitest run tests/unit/usageHistory.test.ts tests/unit/tableDensity.test.ts tests/unit/teacherTables.test.ts $SCAN
npm run lint && npm run check:copy && npm run build
```
Expected: all exit 0.

- [ ] **Step 9: Commit**

```bash
cd /home/sico/Code/Lemely/.claude/worktrees/paymob-integration
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files && graphify update .
P="web/src/lib/usageHistoryModel.ts web/src/portals/billing/UsageHistory.tsx web/src/portals/billing/Receipts.tsx web/src/portals/student/index.tsx web/src/portals/teacher/index.tsx web/src/portals/parent/index.tsx web/tests/unit/usageHistory.test.ts"
git add $P
git commit -S -m "feat(web): usage history and receipts" -- $P
```

---

### Task 8: Auto top-up settings

**Files:**
- Create: `web/src/lib/autoTopupForm.ts`
- Create: `web/src/portals/billing/AutoTopupCard.tsx`
- Modify: `web/src/portals/billing/BillingScreens.tsx` (pass the card as `extra`)
- Modify: `web/src/portals/billing/ParentBilling.tsx` (pass the card as `extra`)
- Test: `web/tests/unit/autoTopup.test.ts`

**Interfaces:**
- Consumes (Tasks 1, 5, 6): `useAutoTopup`, `useSaveAutoTopup`, `useSavedCards`,
  `useCatalogue`, `useBillingSummary`, `billingFailureMessage`, `formatMoney`, `formatCredits`,
  types `AutoTopupSettings`, `AutoTopupUpdate`, `CreditPack`, `Audience`; `BillingOverview`'s
  `extra` prop.
- Produces: `AutoTopupFormState`, `formFromSettings(settings)`,
  `validateAutoTopup(form, packs): string[]`, `toUpdate(form, beneficiaryId): AutoTopupUpdate`;
  `<AutoTopupCard beneficiaryId audience packsHref />`.

Behaviour (spec §2.1, §4.6, §5.5): when credits fall below a threshold, a saved card is charged
for a chosen pack, within a monthly spend cap. The payer owns the setting (a parent for a child),
so the card renders only when `summary.canManage`. With no saved card the switch is disabled and
the card explains how a card gets saved. "Not set up" (06: `enabled: false`, nulls) shows empty
fields. If the server switched top-up off after a failed charge
(`disabledReason: "charge_failed"`) a `role="status"` notice says so. The cap is entered in EGP
(major units) and sent as piasters. Plan 06's `AutoTopupRequest` requires `creditPackId` and
`thresholdUnits > 0` on every save (even with top-up off), so those two are always validated.
Cards come from `GET /billing/cards` (A13); `currency` comes from the DTO.

| Validation | When | Message |
|---|---|---|
| no pack | always | Choose a pack to buy. |
| threshold < 1 | always | Set a threshold of at least 1 credit. |
| no card | enabled | Choose a saved card. |
| cap < chosen pack price | enabled | The monthly limit must cover at least one pack ({price}). |

- [ ] **Step 1: Write the failing test**

`web/tests/unit/autoTopup.test.ts`:

```ts
import { createElement as h } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { ApiError } from "@/lib/api"
import { formFromSettings, toUpdate, validateAutoTopup } from "@/lib/autoTopupForm"
import { fx } from "./support/billingFixtures"
import { fakeMutation, okQuery, renderStatic } from "./support/billingRender"

const s = vi.hoisted(() => ({
  settings: null as unknown,
  cards: null as unknown,
  catalogue: null as unknown,
  summary: null as unknown,
  save: null as unknown,
}))
vi.mock("@/lib/hooks/useBillingApi", () => ({
  useAutoTopup: () => s.settings,
  useSavedCards: () => s.cards,
  useCatalogue: () => s.catalogue,
  useBillingSummary: () => s.summary,
  useSaveAutoTopup: () => s.save,
}))

import { AutoTopupCard } from "@/portals/billing/AutoTopupCard"

const packs = fx.studentCatalogue.packs
const card = () => renderStatic(h(AutoTopupCard, { beneficiaryId: null, audience: "student", packsHref: "/student/billing/plans#packs" }))

beforeEach(() => {
  s.settings = okQuery(fx.autoTopup)
  s.cards = okQuery({ cards: [fx.summary.savedCard] })
  s.catalogue = okQuery(fx.studentCatalogue)
  s.summary = okQuery(fx.summary)
  s.save = fakeMutation()
})

describe("auto top-up form", () => {
  it("round-trips settings, converting the cap between EGP and piasters", () => {
    const form = formFromSettings({ ...fx.autoTopup, monthlyCapMinor: 50000 })
    expect(form.monthlyCapMajor).toBe("500")
    expect(toUpdate({ ...form, monthlyCapMajor: "250.5" }, "c1")).toMatchObject({ beneficiaryId: "c1", monthlyCapMinor: 25050 })
  })

  it("always needs a pack and a threshold, and a card and a covering cap when enabled", () => {
    const off = formFromSettings(fx.autoTopup)
    expect(off).toMatchObject({ thresholdUnits: "", monthlyCapMajor: "", creditPackId: null })
    expect(validateAutoTopup(off, packs)).toEqual(["Choose a pack to buy.", "Set a threshold of at least 1 credit."])
    expect(validateAutoTopup({ ...off, creditPackId: "p1", thresholdUnits: "100" }, packs)).toEqual([])
    const on = { ...off, enabled: true, creditPackId: null, savedCardId: null, thresholdUnits: "0", monthlyCapMajor: "100" }
    expect(validateAutoTopup(on, packs)).toEqual([
      "Choose a pack to buy.",
      "Set a threshold of at least 1 credit.",
      "Choose a saved card.",
    ])
    const lowCap = { ...on, creditPackId: "p1", savedCardId: "card1", thresholdUnits: "50", monthlyCapMajor: "100" }
    expect(validateAutoTopup(lowCap, packs)[0]).toMatch(/^The monthly limit must cover at least one pack \(EGP\s150\.00\)\.$/)
  })
})

describe("AutoTopupCard", () => {
  it("renders the switch, threshold, pack, card and cap fields with spend so far", () => {
    const html = card()
    expect(html).toContain('role="switch"')
    expect(html).toContain("When credits fall below")
    expect(html).toContain("500 credits")
    expect(html).toContain("2346")
    expect(html).toContain("Spent this month")
  })

  it("explains a missing card and disables the switch", () => {
    s.cards = okQuery({ cards: [] })
    const html = card()
    expect(html).toContain("Auto top-up needs a saved card.")
    // Attribute order is React's, so match the switch's tag with lookaheads.
    expect(html).toMatch(/<button(?=[^>]*role="switch")(?=[^>]*disabled)[^>]*>/)
  })

  it("reports a failed charge that switched top-up off", () => {
    s.settings = okQuery({ ...fx.autoTopup, disabledReason: "charge_failed" })
    expect(card()).toMatch(/role="status"[^>]*>.*last charge failed/)
  })

  it("is hidden from a non-payer", () => {
    s.summary = okQuery({ ...fx.summary, canManage: false, managedByName: "Mona" })
    expect(card()).toBe("")
  })

  it("shows save success and failure", () => {
    s.save = fakeMutation({ isSuccess: true })
    expect(card()).toContain("Saved.")
    s.save = fakeMutation({ isError: true, error: new ApiError(409, "x", { code: "no_saved_card" }) })
    expect(card()).toContain('role="alert"')
  })
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npx vitest run tests/unit/autoTopup.test.ts`
Expected: FAIL, "Failed to resolve import "@/lib/autoTopupForm"".

- [ ] **Step 3: Write `web/src/lib/autoTopupForm.ts`**

```ts
import { formatMoney } from "@/lib/billingFormat"
import type { AutoTopupSettings, AutoTopupUpdate, CreditPack } from "@/lib/billingTypes"

/* Auto top-up form state, validation and wire conversion. Numbers are kept as strings while
 * editing so a half-typed value is not coerced under the user's cursor. */

export interface AutoTopupFormState {
  enabled: boolean
  thresholdUnits: string
  creditPackId: string | null
  savedCardId: string | null
  /** EGP, as typed. Sent as piasters. */
  monthlyCapMajor: string
}

/** "Not set up" (06: `enabled: false` and nulls) becomes empty fields. */
export function formFromSettings(settings: AutoTopupSettings): AutoTopupFormState {
  return {
    enabled: settings.enabled,
    thresholdUnits: settings.thresholdUnits === null ? "" : String(settings.thresholdUnits),
    creditPackId: settings.creditPackId,
    savedCardId: settings.savedCardId,
    monthlyCapMajor: settings.monthlyCapMinor === null ? "" : String(settings.monthlyCapMinor / 100),
  }
}

function capMinor(form: AutoTopupFormState): number {
  return Math.round((Number(form.monthlyCapMajor) || 0) * 100)
}

/** 06 `AutoTopupRequest` needs a pack and a positive threshold on every save. */
export function validateAutoTopup(form: AutoTopupFormState, packs: CreditPack[]): string[] {
  const errors: string[] = []
  const pack = packs.find((p) => p.id === form.creditPackId) ?? null
  if (!pack) errors.push("Choose a pack to buy.")
  if (!(Number(form.thresholdUnits) >= 1)) errors.push("Set a threshold of at least 1 credit.")
  if (!form.enabled) return errors
  if (!form.savedCardId) errors.push("Choose a saved card.")
  if (pack && capMinor(form) < pack.priceMinor) {
    errors.push(`The monthly limit must cover at least one pack (${formatMoney(pack.priceMinor, pack.currency)}).`)
  }
  return errors
}

export function toUpdate(form: AutoTopupFormState, beneficiaryId: string | null): AutoTopupUpdate {
  return {
    beneficiaryId,
    enabled: form.enabled,
    thresholdUnits: Math.max(1, Math.floor(Number(form.thresholdUnits) || 1)),
    // `validateAutoTopup` refuses a save without a pack, so this is never "" on the wire.
    creditPackId: form.creditPackId ?? "",
    savedCardId: form.savedCardId,
    monthlyCapMinor: capMinor(form),
  }
}
```

The test's `validateAutoTopup(lowCap…)` regex uses `\s` for the non-breaking space
`Intl.NumberFormat` puts after the currency code; it runs in the runner's default locale, which
is `en-US` in CI's Ubuntu image. If the local default locale differs, run with `LANG=en_US.UTF-8`.

- [ ] **Step 4: Write `web/src/portals/billing/AutoTopupCard.tsx`**

```tsx
import { useState } from "react"
import { Link } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Card, CardBody } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Select } from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"
import { formFromSettings, toUpdate, validateAutoTopup, type AutoTopupFormState } from "@/lib/autoTopupForm"
import { formatCredits, formatMoney } from "@/lib/billingFormat"
import { billingFailureMessage } from "@/lib/billingOutcome"
import type { Audience, AutoTopupSettings, CreditPack, SavedCardView } from "@/lib/billingTypes"
import { useAutoTopup, useBillingSummary, useCatalogue, useSaveAutoTopup, useSavedCards } from "@/lib/hooks/useBillingApi"

/*
 * Auto top-up (spec §2.1, §5.5). Payer-only. The server enforces the threshold, the cap and
 * the one-charge-in-flight rule; this form only collects the settings.
 */

function Form({
  settings,
  packs,
  cards,
  beneficiaryId,
  packsHref,
}: {
  settings: AutoTopupSettings
  packs: CreditPack[]
  cards: SavedCardView[]
  beneficiaryId: string | null
  packsHref: string
}) {
  const save = useSaveAutoTopup()
  const [form, setForm] = useState<AutoTopupFormState>(() => formFromSettings(settings))
  const [submitted, setSubmitted] = useState(false)
  const errors = validateAutoTopup(form, packs)
  const set = (patch: Partial<AutoTopupFormState>) => setForm((f) => ({ ...f, ...patch }))
  const noCard = cards.length === 0

  return (
    <form
      className="flex flex-col gap-4"
      onSubmit={(e) => {
        e.preventDefault()
        setSubmitted(true)
        if (errors.length === 0) save.mutate(toUpdate(form, beneficiaryId))
      }}
    >
      {settings.disabledReason === "charge_failed" ? (
        <p role="status" className="m-0 rounded-lg bg-surface-container-high p-3 text-body-sm text-on-surface">
          Auto top-up was switched off because the last charge failed. Check the card, then switch it back on.
        </p>
      ) : null}
      <Switch
        label="Top up automatically"
        description="Buy a pack by card when your credits run low."
        layout="row"
        checked={form.enabled}
        disabled={noCard}
        onCheckedChange={(enabled) => set({ enabled })}
      />
      {noCard ? (
        <p className="m-0 text-body-sm text-on-surface-variant">
          Auto top-up needs a saved card. Buy a credit pack by card once and Lemely keeps the card.{" "}
          <Link to={packsHref} className="font-medium text-primary underline-offset-2 hover:underline">
            Buy credits
          </Link>
        </p>
      ) : null}
      <div className="grid gap-4 md:grid-cols-2">
        <Input
          label="When credits fall below"
          type="number"
          inputMode="numeric"
          min={1}
          value={form.thresholdUnits}
          onChange={(e) => set({ thresholdUnits: e.target.value })}
        />
        <Select label="Buy this pack" value={form.creditPackId ?? ""} onChange={(e) => set({ creditPackId: e.target.value || null })}>
          <option value="">Choose a pack</option>
          {packs.map((p) => (
            <option key={p.id} value={p.id}>
              {formatCredits(p.units)} for {formatMoney(p.priceMinor, p.currency)}
            </option>
          ))}
        </Select>
        <Select label="Charge this card" value={form.savedCardId ?? ""} onChange={(e) => set({ savedCardId: e.target.value || null })} disabled={noCard}>
          <option value="">Choose a card</option>
          {cards.map((c) => (
            <option key={c.cardId} value={c.cardId}>
              {c.brand} {c.maskedPan}
            </option>
          ))}
        </Select>
        <Input
          label={`Spend at most per month (${settings.currency})`}
          hint={`Spent this month: ${formatMoney(settings.spentThisMonthMinor, settings.currency)}`}
          type="number"
          inputMode="decimal"
          min={0}
          step="0.01"
          value={form.monthlyCapMajor}
          onChange={(e) => set({ monthlyCapMajor: e.target.value })}
        />
      </div>
      {submitted && errors.length > 0 ? (
        <ul role="alert" className="m-0 flex flex-col gap-1 ps-4 text-body-sm text-error">
          {errors.map((m) => (
            <li key={m}>{m}</li>
          ))}
        </ul>
      ) : null}
      {save.isError ? (
        <p role="alert" className="m-0 text-body-sm text-error">{billingFailureMessage(save.error, "save auto top-up")}</p>
      ) : null}
      {save.isSuccess ? (
        <p role="status" className="m-0 text-body-sm text-on-surface-variant">Saved.</p>
      ) : null}
      <Button type="submit" variant="primary" loading={save.isPending} className="self-start">
        Save auto top-up
      </Button>
    </form>
  )
}

export function AutoTopupCard({
  beneficiaryId,
  audience,
  packsHref,
}: {
  beneficiaryId: string | null
  audience: Audience
  packsHref: string
}) {
  const summary = useBillingSummary(beneficiaryId)
  const settings = useAutoTopup(beneficiaryId)
  const cards = useSavedCards()
  const catalogue = useCatalogue(audience)
  if (!summary.data?.canManage) return null
  return (
    <Card>
      <CardBody className="flex flex-col gap-3">
        <h2 className="m-0 text-display-sm text-on-surface">Auto top-up</h2>
        {settings.isError || cards.isError || catalogue.isError ? (
          <p role="alert" className="m-0 text-body-sm text-error">Couldn't load auto top-up settings. Reload the page to try again.</p>
        ) : settings.data && cards.data && catalogue.data ? (
          <Form
            key={JSON.stringify(settings.data)}
            settings={settings.data}
            packs={catalogue.data.packs}
            cards={cards.data.cards}
            beneficiaryId={beneficiaryId}
            packsHref={packsHref}
          />
        ) : (
          <p role="status" className="m-0 text-body-sm text-on-surface-variant">Loading auto top-up…</p>
        )}
      </CardBody>
    </Card>
  )
}
```

- [ ] **Step 5: Wire the card into the overviews**

`web/src/portals/billing/BillingScreens.tsx` becomes:

```tsx
import { billingPaths } from "@/lib/billingPaths"
import { AutoTopupCard } from "./AutoTopupCard"
import { BillingOverview } from "./BillingOverview"

/* Route elements for `/student/billing` and `/teacher/billing`. */

export function StudentBilling() {
  return (
    <BillingOverview
      scope={{ role: "student" }}
      audience="student"
      beneficiaryId={null}
      heading="Plan and billing"
      extra={<AutoTopupCard beneficiaryId={null} audience="student" packsHref={billingPaths({ role: "student" }).packs} />}
    />
  )
}

export function TeacherBilling() {
  return (
    <BillingOverview
      scope={{ role: "teacher" }}
      audience="teacher"
      beneficiaryId={null}
      heading="Plan and billing"
      extra={<AutoTopupCard beneficiaryId={null} audience="teacher" packsHref={billingPaths({ role: "teacher" }).packs} />}
    />
  )
}
```

In `web/src/portals/billing/ParentBilling.tsx`, pass to `BillingOverview`:
`extra={<AutoTopupCard beneficiaryId={childId} audience="student" packsHref={billingPaths({ role: "parent", childId }).packs} />}`
and import `AutoTopupCard` from `./AutoTopupCard`. Update `parentBilling.test.ts`'s overview
mock assertion to also check `typeof s.overviewProps[0].extra === "object"`.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `npx vitest run tests/unit/autoTopup.test.ts tests/unit/parentBilling.test.ts tests/unit/billingOverview.test.ts`
Expected: PASS.

- [ ] **Step 7: Run the frontend gate**

```bash
npm run typecheck
npx vitest run tests/unit/autoTopup.test.ts tests/unit/parentBilling.test.ts tests/unit/billingOverview.test.ts tests/unit/formsMigration.test.ts $SCAN
npm run lint && npm run check:copy && npm run build
```
Expected: all exit 0.

- [ ] **Step 8: Commit**

```bash
cd /home/sico/Code/Lemely/.claude/worktrees/paymob-integration
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files && graphify update .
P="web/src/lib/autoTopupForm.ts web/src/portals/billing/AutoTopupCard.tsx web/src/portals/billing/BillingScreens.tsx web/src/portals/billing/ParentBilling.tsx web/tests/unit/autoTopup.test.ts web/tests/unit/parentBilling.test.ts"
git add $P
git commit -S -m "feat(web): auto top-up settings" -- $P
```

---

### Task 9: Student metered entry points: marking upload, self-review, study plan

**Files:**
- Modify: `web/src/portals/student/screens/CorrectPaper.tsx`
- Modify: `web/src/portals/student/components/SelfReviewPanel.tsx`
- Modify: `web/src/portals/student/screens/studyplan/StudyPlanWeek.tsx`
- Test: `web/tests/unit/studentMeteredWiring.test.ts`
- E2E: `web/e2e/billing-metered-student.spec.ts`

**Interfaces:**
- Consumes (Tasks 1, 3): `useMeteredGate`, `MeteredGate`, `EstimateRange`, `parseUsageBlock`,
  `invalidateUsage`, `useBillingSummary`, `billingPaths`, type `EstimateRequest`.
- Produces: nothing new.

Behaviour per entry point (spec §2.4, §5.7):

| Entry point | Action | Estimate request | Start control gated |
|---|---|---|---|
| `CorrectPaper` (file picked) | `mark_paper` | `{ action }` (flat range, no page count: index R16); `subjectUnknown` | "Mark this paper" and the in-panel retry |
| `CorrectPaper` (scan already uploaded, retry) | `mark_paper` | `{ action, paperId }` | same |
| `SelfReviewPanel` (`not_started`) | `self_review` | `{ action, attemptId, questionResultId }` | "Submit and reveal the marker's verdict" |
| `StudyPlanWeek` | `study_plan` | `{ action, subjectCode }` | "Build this week's plan" / rebuild (early return while blocked) |

On every one: the estimate renders above the start control; `gate.block` disables the control
and shows the notice; a 402 from the mutation is captured by `gate.captureError(err)` and shown
as the notice **instead of** the screen's generic failure line; on success the usage queries are
invalidated so the meter and credits move. A student whose parent pays sees "Ask {parent} to add
credits" (`managedByName` from `useBillingSummary()`).

The offline upload queue (`lib/offline/useUploadQueue.ts`) is unchanged: it already stops after
five attempts for any persistent failure, and a student only queues a scan after the estimate
step has been shown.

- [ ] **Step 1: Write the failing tests**

`web/tests/unit/studentMeteredWiring.test.ts` (source wiring, the pattern
`selfReviewPanelWiring.test.ts` uses for screens too large to render statically):

```ts
import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"
import { stripComments } from "./support/jsxSource"

const ROOT = join(import.meta.dirname, "..", "..")
const read = (p: string) => stripComments(readFileSync(join(ROOT, p), "utf8"))

const SCREENS = [
  { file: "src/portals/student/screens/CorrectPaper.tsx", action: "mark_paper" },
  { file: "src/portals/student/components/SelfReviewPanel.tsx", action: "self_review" },
  { file: "src/portals/student/screens/studyplan/StudyPlanWeek.tsx", action: "study_plan" },
] as const

describe.each(SCREENS)("$file", ({ file, action }) => {
  const source = read(file)

  it("opens a metered gate for its action", () => {
    expect(source).toContain("useMeteredGate(")
    expect(source).toContain(`action: "${action}"`)
  })

  it("renders the estimate with the student audience", () => {
    expect(source).toMatch(/<EstimateRange[\s\S]*?audience="student"/)
  })

  it("captures a 402 into the gate", () => {
    expect(source).toContain(".captureError(")
  })

  it("refreshes the meter after the action", () => {
    expect(source).toContain("invalidateUsage(")
  })
})

describe("start controls are disabled while blocked", () => {
  it("CorrectPaper disables both start buttons", () => {
    const source = read("src/portals/student/screens/CorrectPaper.tsx")
    expect(source.match(/disabled=\{!canStart \|\| markGate\.block !== null\}/g)?.length).toBe(2)
    expect(source).toContain("subjectUnknown")
  })

  it("SelfReviewPanel passes the block into PendingForm without a fragment in the not_started branch", () => {
    const source = read("src/portals/student/components/SelfReviewPanel.tsx")
    expect(source).toContain("blocked={reviewGate.block !== null}")
    expect(source).toContain("disabled={!complete || submitting || blocked}")
  })

  it("StudyPlanWeek refuses to start while blocked and hides the generic error for a 402", () => {
    const source = read("src/portals/student/screens/studyplan/StudyPlanWeek.tsx")
    expect(source).toContain("if (planGate.block) return")
    expect(source).toContain("!parseUsageBlock(rebuild.error)")
  })
})
```

- [ ] **Step 2: Run them to verify they fail**

Run: `npx vitest run tests/unit/studentMeteredWiring.test.ts`
Expected: FAIL on the wiring assertions.

- [ ] **Step 3: Wire `CorrectPaper.tsx`**

Add imports:

```tsx
import { useQueryClient } from "@tanstack/react-query"
import { EstimateRange } from "@/components/billing/estimate-range"
import { billingPaths } from "@/lib/billingPaths"
import type { EstimateRequest } from "@/lib/billingTypes"
import { useBillingSummary } from "@/lib/hooks/useBillingApi"
import { invalidateUsage } from "@/lib/hooks/useUsageApi"
import { useMeteredGate } from "@/lib/meteredGate"
```

(skip `useQueryClient` if the file already has a `queryClient` from it). Directly after the
`const resumableId = …` line, add:

```tsx
  const queryClient = useQueryClient()
  const billing = useBillingSummary()
  const markRequest: EstimateRequest | null = scanFile
    ? { action: "mark_paper" }
    : canRetryInPlace(resumableId) && resumableId
      ? { action: "mark_paper", paperId: resumableId }
      : null
  const markGate = useMeteredGate(markRequest)
```

In `runPipeline`'s `catch (err)` block, as its first statement:

```tsx
      if (markGate.captureError(err)) {
        setStages(initialStages)
        return
      }
```

and in its `finally` block, after `setRunning(false)`: `invalidateUsage(queryClient)`.

Change both start buttons' `disabled={!canStart}` (the header "Mark this paper" and the
in-panel retry) to `disabled={!canStart || markGate.block !== null}`. Directly above the
`<QueuedBanner …/>` line, render:

```tsx
      <EstimateRange
        gate={markGate}
        audience="student"
        paths={billingPaths({ role: "student" })}
        managedByName={billing.data?.managedByName ?? null}
        subjectUnknown
      />
```

- [ ] **Step 4: Wire `SelfReviewPanel.tsx`**

Add imports for `useQueryClient`, `EstimateRange`, `billingPaths`, `useBillingSummary`,
`invalidateUsage`, `useMeteredGate` as above, plus `import type { ReactNode } from "react"` if
not present. In `SelfReviewPanel`, directly after `const submit = useSubmitSelfReview()` (before
any early return, so hook order never changes):

```tsx
  const queryClient = useQueryClient()
  const billing = useBillingSummary()
  const reviewGate = useMeteredGate(
    query.data?.state === "not_started" ? { action: "self_review", attemptId, questionResultId } : null,
  )
```

In the `not_started` branch, pass two new props to `PendingForm` (no fragment: the existing
wiring test forbids one in this branch):

```tsx
        blocked={reviewGate.block !== null}
        estimate={
          <EstimateRange
            gate={reviewGate}
            audience="student"
            paths={billingPaths({ role: "student" })}
            managedByName={billing.data?.managedByName ?? null}
          />
        }
```

and change the `submit.mutate(…, { onError })` options to:

```tsx
            {
              onSuccess: () => invalidateUsage(queryClient),
              onError: (error) => {
                if (reviewGate.captureError(error)) return
                toast({
                  title:
                    error instanceof ApiError && error.status === 409
                      ? "You have already self-marked this question. Showing the result."
                      : "We couldn't submit your self-mark. Please try again.",
                })
              },
            },
```

In `PendingForm`, add `blocked: boolean` and `estimate: ReactNode` to its props, render
`{estimate}` directly above the submit `<Button>`, change the submit button to
`disabled={!complete || submitting || blocked}`, and change the form's guard to
`if (canSubmit && !submitting && !blocked) {`.

- [ ] **Step 5: Wire `StudyPlanWeek.tsx`**

Add imports for `useQueryClient`, `EstimateRange`, `billingPaths`, `useBillingSummary`,
`invalidateUsage`, `useMeteredGate`, `parseUsageBlock`. After `const complete = …`:

```tsx
  const queryClient = useQueryClient()
  const billing = useBillingSummary()
  const planGate = useMeteredGate(subjectCode ? { action: "study_plan", subjectCode } : null)
```

Replace `const onRebuild = () => rebuild.mutate({ subjectCode })` with:

```tsx
  const onRebuild = () => {
    if (planGate.block) return
    rebuild.mutate(
      { subjectCode },
      { onSuccess: () => invalidateUsage(queryClient), onError: (err) => void planGate.captureError(err) },
    )
  }
  const estimate = (
    <EstimateRange
      gate={planGate}
      audience="student"
      paths={billingPaths({ role: "student" })}
      managedByName={billing.data?.managedByName ?? null}
    />
  )
```

Change the `rebuildError` condition to `rebuild.isError && !parseUsageBlock(rebuild.error) ? (`
and render `{estimate}` directly before each of the three `{rebuildError}` occurrences.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `npx vitest run tests/unit/studentMeteredWiring.test.ts tests/unit/selfReviewPanelWiring.test.ts tests/unit/selfReviewWiring.test.ts tests/unit/selfReview.test.ts tests/unit/studyPlan.test.ts tests/unit/studyPlanHeader.test.ts tests/unit/correctPaperSource.test.ts tests/unit/correctionOutcome.test.ts`
Expected: PASS.

- [ ] **Step 7: Write the e2e spec**

`web/e2e/billing-metered-student.spec.ts`:

```ts
import { test, expect, type Page } from "@playwright/test"
import { readSeed } from "./seed"

async function login(page: Page) {
  const student = readSeed().students.control
  await page.goto("/login")
  await page.getByLabel("Email").fill(student.email)
  await page.getByLabel("Password").fill(student.password)
  await page.getByRole("button", { name: /sign in/i }).click()
  await expect(page).toHaveURL(/\/student$/, { timeout: 15_000 })
}

// Wire shapes: plan 05 `BillingSummaryDTO`, plan 04 `EstimateDTO`, plan 04's flat 402 body.
const summary = {
  beneficiary: { userId: "u", displayName: "S", audience: "student" },
  subscription: null, canManage: true, managedByName: null, savedCard: null,
  usage: { fraction: null, resetsAt: null }, credits: { totalUnits: 0, expiring: [] }, debtUnits: 0, seats: null,
}
const estimate = (over: Record<string, unknown>) => ({
  low: 3, high: 5, payer: "credits", percentLow: null, percentHigh: null, blockedReason: null, ...over,
})
const pdf = { name: "scan.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4\n%%EOF") }

test("the marking screen shows the estimate, then a 402 as a buy-credits notice", async ({ page }) => {
  await page.route("**/api/billing/summary**", (r) => r.fulfill({ json: summary }))
  await page.route("**/api/usage/estimate", (r) => r.fulfill({ json: estimate({}) }))
  await page.route("**/api/student/uploads", (r) =>
    r.fulfill({ status: 402, json: { error: "usage_blocked", reason: "insufficient_credits", estimate: [3, 5] } }),
  )
  await login(page)
  await page.goto("/student/correct")
  await page.locator('input[type="file"]').first().setInputFiles(pdf)
  await expect(page.getByTestId("estimate-range")).toContainText("3–5 credits")
  await page.getByRole("button", { name: "Mark this paper" }).click()
  const notice = page.getByTestId("usage-blocked-notice")
  await expect(notice).toHaveAttribute("data-reason", "insufficient_credits")
  await expect(notice.getByRole("link", { name: "Buy credits" })).toHaveAttribute("href", "/student/billing/plans#packs")
  await expect(page.getByRole("button", { name: "Mark this paper" })).toBeDisabled()
})

test("a blocked estimate disables the start control before any upload", async ({ page }) => {
  let uploads = 0
  await page.route("**/api/billing/summary**", (r) => r.fulfill({ json: summary }))
  await page.route("**/api/usage/estimate", (r) => r.fulfill({ json: estimate({ blockedReason: "no_active_plan" }) }))
  await page.route("**/api/student/uploads", (r) => {
    uploads += 1
    return r.abort()
  })
  await login(page)
  await page.goto("/student/correct")
  await page.locator('input[type="file"]').first().setInputFiles(pdf)
  await expect(page.getByTestId("usage-blocked-notice")).toHaveAttribute("data-reason", "no_active_plan")
  await expect(page.getByRole("button", { name: "Mark this paper" })).toBeDisabled()
  expect(uploads).toBe(0)
})
```

- [ ] **Step 8: Run the e2e spec (local stack only)**

Run: `npx playwright test e2e/billing-metered-student.spec.ts`
Expected: 2 passed, or "e2e not run: local stack down" recorded.

- [ ] **Step 9: Run the frontend gate**

```bash
npm run typecheck
npx vitest run tests/unit/studentMeteredWiring.test.ts tests/unit/selfReviewPanelWiring.test.ts tests/unit/selfReviewWiring.test.ts tests/unit/selfReview.test.ts tests/unit/studyPlan.test.ts tests/unit/studyPlanHeader.test.ts tests/unit/correctPaperSource.test.ts tests/unit/correctionOutcome.test.ts $SCAN
npm run lint && npm run check:copy && npm run build
```
Expected: all exit 0.

- [ ] **Step 10: Commit**

```bash
cd /home/sico/Code/Lemely/.claude/worktrees/paymob-integration
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files && graphify update .
P="web/src/portals/student/screens/CorrectPaper.tsx web/src/portals/student/components/SelfReviewPanel.tsx web/src/portals/student/screens/studyplan/StudyPlanWeek.tsx web/web/tests/unit/studentMeteredWiring.test.ts web/e2e/billing-metered-student.spec.ts"
git add $P
git commit -S -m "feat(web): estimate and 402 handling on student metered actions" -- $P
```

---

### Task 10: Teacher metered entry points: marking upload, regrade, quiz generation

**Files:**
- Modify: `web/src/portals/teacher/screens/Grading.tsx`
- Modify: `web/src/portals/teacher/screens/QuizBuilder.tsx`
- Test: `web/tests/unit/teacherMeteredWiring.test.ts`
- E2E: `web/e2e/billing-metered-teacher.spec.ts`

**Interfaces:**
- Consumes (Tasks 1, 3, 9): `useMeteredGate`, `EstimateRange`, `parseUsageBlock`,
  `invalidateUsage`, `billingPaths`, type `EstimateRequest`.
- Produces: nothing new.

| Entry point | Action | Estimate request | Gated control |
|---|---|---|---|
| Grading upload panel (scan picked) | `mark_paper` | `{ action }` (flat range, index R16); `subjectUnknown` | the upload/mark button that calls `handleUpload` |
| Grading failed-paper panel | `regrade` | `{ action, paperId: detail.id }` | "Try again" (calls `regrade.mutate`) |
| QuizBuilder step 5 | `generate_quiz` | `{ action, count: min(50, max(1, requestedCount − included)) }`, or `{ action }` with no requested count (04 `EstimateRequestDTO.count` is 1–50; it has no quiz id) | "Generate questions" / "Generate more questions" |

Teacher copy comes from `usageBlockCopy(reason, "teacher")`. Paths point at the teacher's own
billing. An assistant acting for a lead teacher gets the server's reason for the lead's
balance; `out_of_seat_scope` there reads "Outside your team's limits … Ask them to raise it."
with no billing link.

- [ ] **Step 1: Write the failing wiring test**

`web/tests/unit/teacherMeteredWiring.test.ts`:

```ts
import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"
import { stripComments } from "./support/jsxSource"

const ROOT = join(import.meta.dirname, "..", "..")
const read = (p: string) => stripComments(readFileSync(join(ROOT, p), "utf8"))

describe("Grading.tsx", () => {
  const source = read("src/portals/teacher/screens/Grading.tsx")

  it("gates the upload on a mark_paper estimate with the page count", () => {
    expect(source).toContain('action: "mark_paper"')
    expect(source).toMatch(/<EstimateRange[\s\S]*?gate=\{uploadGate\}[\s\S]*?audience="teacher"[\s\S]*?subjectUnknown/)
    expect(source).toContain("if (uploadGate.captureError(err))")
  })

  it("gates the regrade on a regrade estimate for the selected paper", () => {
    expect(source).toContain('action: "regrade"')
    expect(source).toMatch(/<EstimateRange[\s\S]*?gate=\{regradeGate\}/)
    expect(source).toContain("disabled={regrade.isPending || regradeGate.block !== null}")
    expect(source).toContain("!parseUsageBlock(regrade.error)")
  })

  it("refreshes the meter after both", () => {
    expect(source.match(/invalidateUsage\(/g)?.length ?? 0).toBeGreaterThanOrEqual(2)
  })
})

describe("QuizBuilder.tsx", () => {
  const source = read("src/portals/teacher/screens/QuizBuilder.tsx")

  it("gates generation on a generate_quiz estimate", () => {
    expect(source).toContain('action: "generate_quiz"')
    expect(source).toMatch(/<EstimateRange[\s\S]*?gate=\{generateGate\}[\s\S]*?audience="teacher"/)
    expect(source).toContain("disabled={!canGenerate || generate.isPending || generateGate.block !== null}")
    expect(source).toContain("generateGate.captureError(")
    expect(source).toContain("!parseUsageBlock(generate.error)")
    expect(source).toContain("invalidateUsage(")
  })
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npx vitest run tests/unit/teacherMeteredWiring.test.ts`
Expected: FAIL on every assertion.

- [ ] **Step 3: Wire `Grading.tsx`**

Add imports:

```tsx
import { EstimateRange } from "@/components/billing/estimate-range"
import { billingPaths } from "@/lib/billingPaths"
import type { EstimateRequest } from "@/lib/billingTypes"
import { invalidateUsage } from "@/lib/hooks/useUsageApi"
import { useMeteredGate } from "@/lib/meteredGate"
import { parseUsageBlock } from "@/lib/usageBlock"
```

After `const regrade = useRegradePaper()` add:

```tsx
  const teacherPaths = billingPaths({ role: "teacher" })
  const uploadRequest: EstimateRequest | null = scanFile
    ? { action: "mark_paper" }
    : null
  const uploadGate = useMeteredGate(uploadRequest)
  // Exactly when the "Try again" panel renders: `detail.error` is set (see the JSX below).
  const regradeGate = useMeteredGate(
    paperDetailQuery.data?.error
      ? { action: "regrade", paperId: paperDetailQuery.data.id }
      : null,
  )
```

In `handleUpload`'s `catch (err)` block, as its first statement (`UPLOAD_STAGES` is the
stepper's initial value, line ~353):

```tsx
      if (uploadGate.captureError(err)) {
        setStages(UPLOAD_STAGES)
        return
      }
```

After the
`queryClient.invalidateQueries({ queryKey: ["teacher", "papers"] })` line in the `try`, add
`invalidateUsage(queryClient)`. Add `|| uploadGate.block !== null` to the `disabled` of the
button with `onClick={handleUpload}` (line ~764), and render directly above that button:

```tsx
                <EstimateRange
                  gate={uploadGate}
                  audience="teacher"
                  paths={teacherPaths}
                  managedByName={null}
                  subjectUnknown
                />
```

For regrade, change the button to
`disabled={regrade.isPending || regradeGate.block !== null}` and
`onClick={() => regrade.mutate(detail.id, { onSuccess: () => invalidateUsage(queryClient), onError: (err) => void regradeGate.captureError(err) })}`;
change `{regrade.isError ? (` to `{regrade.isError && !parseUsageBlock(regrade.error) ? (`;
render directly above the button:

```tsx
                            <EstimateRange gate={regradeGate} audience="teacher" paths={teacherPaths} managedByName={null} />
```

- [ ] **Step 4: Wire `QuizBuilder.tsx`**

Add the same imports, plus `useQueryClient` if absent. In the
step-5 component, after `const generate = useGenerateQuizQuestions(quizId)` and the `included`
computation:

```tsx
  const queryClient = useQueryClient()
  const remaining = quiz.requestedCount != null ? Math.min(50, Math.max(1, quiz.requestedCount - included.length)) : null
  const generateGate = useMeteredGate(
    isDraft && canGenerate && quizId
      ? { action: "generate_quiz", ...(remaining !== null ? { count: remaining } : {}) }
      : null,
  )
```

(move `const included = …` and `const canGenerate = …` above this block if they are declared
after it). Replace `handleGenerate` with:

```tsx
  function handleGenerate() {
    if (generateGate.block) return
    generate.mutate(undefined, {
      onSuccess: (data) => {
        setLastGenerated(data)
        invalidateUsage(queryClient)
      },
      onError: (err) => void generateGate.captureError(err),
    })
  }
```

Change the generate button to
`disabled={!canGenerate || generate.isPending || generateGate.block !== null}`, change
`{generate.isError ? (` to `{generate.isError && !parseUsageBlock(generate.error) ? (`, and render
directly after the button row's closing `</div>`:

```tsx
      {isDraft ? (
        <EstimateRange gate={generateGate} audience="teacher" paths={billingPaths({ role: "teacher" })} managedByName={null} />
      ) : null}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `npx vitest run tests/unit/teacherMeteredWiring.test.ts tests/unit/gradingCamera.test.ts tests/unit/quizBuilderSummary.test.ts tests/unit/teacherOutcome.test.ts tests/unit/teacherTables.test.ts`
Expected: PASS.

- [ ] **Step 6: Write the e2e spec**

`web/e2e/billing-metered-teacher.spec.ts`:

```ts
import { test, expect } from "@playwright/test"
import { readSeed } from "./seed"

test("the grading console blocks an upload the balance cannot cover", async ({ page }) => {
  const teacher = readSeed().teacher
  let uploads = 0
  await page.route("**/api/usage/estimate", (r) =>
    r.fulfill({
      json: { low: 3, high: 5, payer: "none", percentLow: null, percentHigh: null, blockedReason: "outstanding_debt" },
    }),
  )
  await page.route("**/api/papers/upload", (r) => {
    uploads += 1
    return r.abort()
  })
  await page.goto("/login")
  await page.getByLabel("Email").fill(teacher.email)
  await page.getByLabel("Password").fill(teacher.password)
  await page.getByRole("button", { name: /sign in/i }).click()
  await expect(page).toHaveURL(/\/teacher/, { timeout: 15_000 })

  await page.goto("/teacher/grading")
  await page.locator('input[type="file"]').first().setInputFiles({ name: "scan.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4\n%%EOF") })
  const notice = page.getByTestId("usage-blocked-notice")
  await expect(notice).toHaveAttribute("data-reason", "outstanding_debt")
  await expect(notice).toContainText("Balance below zero")
  expect(uploads).toBe(0)
})
```

- [ ] **Step 7: Run the e2e spec (local stack only)**

Run: `npx playwright test e2e/billing-metered-teacher.spec.ts`
Expected: 1 passed, or "e2e not run: local stack down" recorded.

- [ ] **Step 8: Run the frontend gate**

```bash
npm run typecheck
npx vitest run tests/unit/teacherMeteredWiring.test.ts tests/unit/gradingCamera.test.ts tests/unit/quizBuilderSummary.test.ts tests/unit/teacherOutcome.test.ts tests/unit/teacherTables.test.ts $SCAN
npm run lint && npm run check:copy && npm run build
```
Expected: all exit 0.

- [ ] **Step 9: Commit**

```bash
cd /home/sico/Code/Lemely/.claude/worktrees/paymob-integration
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files && graphify update .
P="web/src/portals/teacher/screens/Grading.tsx web/src/portals/teacher/screens/QuizBuilder.tsx web/tests/unit/teacherMeteredWiring.test.ts web/e2e/billing-metered-teacher.spec.ts"
git add $P
git commit -S -m "feat(web): estimate and 402 handling on teacher metered actions" -- $P
```

---

### Task 11: Teacher seats: capacity, buy/remove extra seats, scope, cap, removal

**Files:**
- Modify: `web/src/lib/billingTypes.ts` (team wire DTOs and view types)
- Modify: `web/src/lib/billingAdapters.ts` (team adapters)
- Modify: `web/tests/unit/support/billingFixtures.ts` (team fixtures)
- Create: `web/src/lib/hooks/useTeamApi.ts`
- Create: `web/src/lib/teamModel.ts`
- Create: `web/src/portals/teacher/screens/team/Team.tsx`
- Create: `web/src/portals/teacher/screens/team/SeatsPanel.tsx`
- Create: `web/src/portals/teacher/screens/team/SeatEditorDialog.tsx`
- Create: `web/src/portals/teacher/screens/team/SeatCountDialogs.tsx`
- Modify: `web/src/portals/teacher/index.tsx` (route `team`, `NAV_ICON.team`)
- Modify: `web/src/portals/teacher/data.ts` (nav entry, icon union)
- Test: `web/tests/unit/teamModel.test.ts`, `web/tests/unit/teamSeats.test.ts`
- E2E: `web/e2e/billing-team.spec.ts`

**Interfaces:**
- Consumes (Tasks 1, 5): `billingApi.summary`, `useSeatQuote`, `useAddSeats`, `useReduceSeats`,
  `PaymentProgress`, `billingFailureMessage`, `formatMoney`, `formatCredits`,
  `formatBillingDate`, `formatPercent`, `isLiveSubscription`, `toPlanTier`, `toSavedCard`,
  types `MeteredAction`, `CapPeriod`, `SavedCardView`, `WireBillingSummary`; `ClassList` from
  `web/src/lib/teacherTypes.ts` (`GET /teacher/classes`, existing).
- Produces:
  - types (wire) `WireSeat`, `WireSeatCapacity`, `WireAssistant`, `WireAssistantInvite`,
    `WireMembership`, `WireAssistantUpdate`, and (view) `TeacherMemberStatus`,
    `AssistantRole`, `TEAM_PERMISSIONS`, `TeamPermission`, `SeatRow`, `AssistantRow`,
    `AssistantInvite`, `TeamView`, `SeatScopeUpdate`, `CapUpdate`, `AssistantInviteCreate`,
    `AssistantRoleUpdate`, `TeamMembership` in `billingTypes.ts`;
  - adapters `toSeatRow`, `toAssistantRow`, `toTeamView` in `billingAdapters.ts`;
  - `teamApi`, `teamKeys`, hooks `useTeam`, `useSetSeatScope`, `useSetMemberCap`,
    `useRemoveSeat`, `useCreateAssistantInvite`, `useRevokeAssistantInvite` (variable
    `inviteId`), `useSetAssistantRole`, `useRemoveAssistant`, `useJoinTeam` (mutation variables
    `{ memberId, body }` where a body exists);
  - `SEAT_ACTIONS`, `SeatAction`, `SEAT_ACTION_COPY`, `seatCapacityModel(team)`,
    `seatStatusText(seat)`, `seatCapText(seat)`, `assistantCapText(row)`,
    `scopeSummary(seat, subjects)` from `teamModel.ts`;
  - screen `Team` (Task 12 adds the assistants panel to it), `<SeatsPanel team />`.

Data sources (plan 03 Task 7 router, index R3): seats, capacity, assistants and invites from
`/teacher/team/{seats,capacity,assistants,invites}`; plan state, included/extra split, pending
reduction, extra-seat price, currency, period end and the saved card from the teacher's
`GET /billing/summary` (M12); scope subjects from the teacher's existing `GET /teacher/classes`.
`useTeam` fetches all six in parallel and assembles one `TeamView`, so every screen consumes one
object. Seats carry no class names, and assistants no email or status (names only, by design).

Behaviour (spec §2.2, §4.4, §5.4, §5.9):

- **Capacity**: "{used} of {capacity} seats used" (active plus leaving count), "{included}
  included with your plan, {extra} extra"; a scheduled reduction reads "Drops to {n} extra seats
  on {date}". With no live plan: `role="status"` "Your plan isn't active, so seats get no new
  monthly allowances. Students keep their seats." plus a link to `/teacher/billing/plans`.
- **Add seats**: quantity 1–100 → quote (A14) → "You pay {amount} now for the rest of this
  period, then {perSeat} per seat each period with your plan. Charged to {brand} {pan}." →
  "Pay {amount} and add seats" (A15) → `PaymentProgress`. No saved card: the saved-card
  sentence, no confirm.
- **Remove extra seats**: quantity 1..`extraSeats` → A16 with the new **total**
  (`extraSeats − n`) → "{n} extra seats from the end of this period." A `seats_in_use` 409 reads
  the mapped sentence.
- **Seat list**: student, subjects and actions covered, this month's seat use
  (`meterFraction`), overflow cap with use (`capUsedUnits`), status ("Active" or "Leaving on
  {date}"). Empty: "No students hold a seat yet. Students take a seat when they join one of your
  classes with its code."
- **Edit seat** (dialog): subject checkboxes from the classes' subjects; action checkboxes from
  `SEAT_ACTIONS` with `study_plan` off unless already in scope and its hint ("Off by default.
  When on, the seat pays for the first plan per subject each week. Regenerating that week uses
  the student's own balance."); overflow: "No overflow" or "Let them use my credits" with a
  credits amount and "per month" / "in total". Saves scope (A21) then cap (A22). A seat with no
  subjects shows "With no subjects, this seat pays for nothing." (allowed).
- **Remove seat** (dialog): "{name} keeps the seat until {month end}, then it frees up. Their
  current monthly allowance runs until it expires." → "Remove at month end" (A23,
  `DELETE /teacher/team/seats/{id}`). Leaving seats show no remove control.
- An assistant opening `/teacher/team` gets 403 → "Seats and assistants are managed by the lead
  teacher."

- [ ] **Step 0: Match the merged team routes exactly**

Open the merged `lemely/web/routers/teacher_team.py` and `lemely/web/schemas_team.py` (or plan
03 Task 7's router and schemas). Copy every field of `SeatDTO`, `SeatCapacityDTO`,
`AssistantDTO`, `AssistantInviteDTO`, `MembershipDTO`, `SetSeatScopeRequestDTO`,
`SetCapRequestDTO`, `CreateAssistantInviteRequestDTO`, `UpdateAssistantRequestDTO` and the
invites list into the wire types of Step 3a; keep view names; record differences in the commit.

- [ ] **Step 1: Write the failing model and fetcher test**

`web/tests/unit/teamModel.test.ts`:

```ts
import { beforeEach, describe, expect, it, vi } from "vitest"

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  request: vi.fn(),
}))

import { request } from "@/lib/api"
import { toTeamView } from "@/lib/billingAdapters"
import { formatBillingDate } from "@/lib/billingFormat"
import { teamApi } from "@/lib/hooks/useTeamApi"
import {
  SEAT_ACTIONS,
  SEAT_ACTION_COPY,
  assistantCapText,
  scopeSummary,
  seatCapText,
  seatCapacityModel,
  seatStatusText,
} from "@/lib/teamModel"
import { fx } from "./support/billingFixtures"

const req = vi.mocked(request)
beforeEach(() => {
  req.mockReset()
  req.mockResolvedValue({})
})

describe("team fetchers (plan 03 routes; request() adds /api)", () => {
  it("hits every team route with the right method", async () => {
    await teamApi.seats()
    await teamApi.capacity()
    await teamApi.assistants()
    await teamApi.invites()
    await teamApi.memberships()
    await teamApi.setScope("m 1", { subjects: ["0580"], actions: ["mark_paper"] })
    await teamApi.setCap("m1", { capUnits: 500, capPeriod: "month" })
    await teamApi.removeSeat("m1")
    await teamApi.createInvite({ role: "marker", expiresInDays: 7 })
    await teamApi.revokeInvite("inv1")
    await teamApi.updateAssistant("m9", { role: "viewer", permissions: {} })
    await teamApi.removeAssistant("m9")
    await teamApi.redeem("AST-1")
    expect(req.mock.calls.map((c) => [c[0], (c[1] as RequestInit | undefined)?.method ?? "GET"])).toEqual([
      ["/teacher/team/seats", "GET"],
      ["/teacher/team/capacity", "GET"],
      ["/teacher/team/assistants", "GET"],
      ["/teacher/team/invites", "GET"],
      ["/teacher/team/memberships", "GET"],
      ["/teacher/team/seats/m%201/scope", "PUT"],
      ["/teacher/team/members/m1/cap", "PUT"],
      ["/teacher/team/seats/m1", "DELETE"],
      ["/teacher/team/assistants/invites", "POST"],
      ["/teacher/team/invites/inv1", "DELETE"],
      ["/teacher/team/assistants/m9", "PATCH"],
      ["/teacher/team/assistants/m9", "DELETE"],
      ["/teacher/team/assistants/redeem", "POST"],
    ])
  })
})

describe("toTeamView", () => {
  it("assembles seats, assistants, invites, plan fields from the summary and subjects from classes", () => {
    const view = toTeamView({
      seats: { seats: [fx.wireSeat] },
      capacity: { capacity: 22, used: 1, free: 21 },
      assistants: { assistants: [fx.wireAssistant] },
      invites: { invites: [fx.team.invites[0]] },
      summary: fx.wireTeacherSummary,
      classes: {
        classes: [
          { subjectCode: "0580", subjectName: "Mathematics" },
          { subjectCode: "0580", subjectName: "Mathematics" },
          { subjectCode: null, subjectName: null },
        ],
      },
    })
    expect(view).toEqual(fx.team)
  })
})

describe("team model", () => {
  it("summarises capacity", () => {
    expect(seatCapacityModel(fx.team)).toEqual({
      used: 1,
      capacity: 22,
      free: 21,
      barValue: 5,
      label: "1 of 22 seats used",
      detail: "20 included with your plan, 2 extra",
    })
  })

  it("lists student seat actions with study plans explained", () => {
    expect(SEAT_ACTIONS).toEqual(["mark_paper", "self_review", "study_plan", "mark_quiz", "generate_flashcards"])
    expect(SEAT_ACTION_COPY.study_plan.hint).toContain("Off by default.")
  })

  it("describes status, caps and scope", () => {
    expect(seatStatusText(fx.seat)).toBe("Active")
    expect(seatStatusText({ ...fx.seat, status: "leaving", leavesAt: "2026-11-30T23:59:59Z" })).toBe(
      `Leaving on ${formatBillingDate("2026-11-30T23:59:59Z")}`,
    )
    expect(seatCapText(fx.seat)).toBe("No overflow")
    expect(seatCapText({ ...fx.seat, capUnits: 500, capPeriod: "month", capUsedUnits: 120 })).toBe(
      "Up to 500 of your credits a month (120 used)",
    )
    expect(assistantCapText({ ...fx.assistant, capUnits: null })).toBe("No limit")
    expect(assistantCapText(fx.assistant)).toBe("Up to 2,000 credits a month (300 used)")
    expect(scopeSummary(fx.seat, fx.team.subjects)).toBe("Mathematics · Paper marking, Self-review")
  })
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npx vitest run tests/unit/teamModel.test.ts`
Expected: FAIL, "Failed to resolve import "@/lib/hooks/useTeamApi"".

- [ ] **Step 3a: Add the team types to `web/src/lib/billingTypes.ts`**

Append:

```ts
// ── Teacher team (plan 03 Task 7) ───────────────────────────────────────────

export type TeacherMemberStatus = "active" | "leaving" | "removed"
export type AssistantRole = "co_teacher" | "marker" | "viewer"

/** Plan 03 `TeamPermission`. Billing and seats are never permissions (spec §2.3). */
export const TEAM_PERMISSIONS = [
  "mark",
  "regrade",
  "generate_quiz",
  "manage_classes",
  "view_results",
  "manage_students",
  "view_usage",
] as const
export type TeamPermission = (typeof TEAM_PERMISSIONS)[number]

/** 03 `SeatDTO` (with `kind`, `capUsedUnits`, `meterFraction` added by plan 03). */
export interface WireSeat {
  kind: "student_seat"
  memberId: string
  studentId: string
  studentName: string
  status: "active" | "leaving"
  leavesAt: string | null
  scopeSubjects: string[]
  scopeActions: string[]
  capUnits: number | null
  capPeriod: CapPeriod
  capUsedUnits: number
  meterFraction: number | null
}

/** 03 `SeatCapacityDTO`. */
export interface WireSeatCapacity {
  capacity: number
  used: number
  free: number
}

/** 03 `AssistantDTO` (with `kind`, `capUsedUnits`). `permissions` = toggles off the preset. */
export interface WireAssistant {
  kind: "assistant"
  memberId: string
  assistantId: string
  assistantName: string
  role: AssistantRole
  permissions: Record<string, boolean>
  effectivePermissions: string[]
  capUnits: number | null
  capPeriod: CapPeriod
  capUsedUnits: number
}

/** 03 `AssistantInviteDTO` (with `inviteId`, `createdAt`). */
export interface WireAssistantInvite {
  inviteId: string
  code: string
  role: AssistantRole
  expiresAt: string
  createdAt: string
}

/** 03 `MembershipDTO`. */
export interface WireMembership {
  memberId: string
  teacherId: string
  teacherName: string
  role: AssistantRole
  effectivePermissions: string[]
}

/** 03 `UpdateAssistantRequestDTO`. */
export interface WireAssistantUpdate {
  role?: AssistantRole
  permissions?: Record<string, boolean>
}

/** 03 `SetSeatScopeRequestDTO`. */
export interface SeatScopeUpdate {
  subjects: string[]
  actions: MeteredAction[]
}

/** 03 `SetCapRequestDTO`. */
export interface CapUpdate {
  capUnits: number | null
  capPeriod: CapPeriod
}

/** 03 `CreateAssistantInviteRequestDTO` (`expiresInDays` 1–30). */
export interface AssistantInviteCreate {
  role: AssistantRole
  expiresInDays: number
}

export interface SeatRow {
  memberId: string
  studentUserId: string
  studentName: string
  status: TeacherMemberStatus
  /** End of the month removal was requested in; set while `leaving`. */
  leavesAt: string | null
  scopeSubjects: string[]
  scopeActions: MeteredAction[]
  /** Overflow into the teacher's credits. `null` = no overflow. */
  capUnits: number | null
  capPeriod: CapPeriod
  capUsedUnits: number
  /** This month's seat allowance used, 0..1; `null` before the first grant. */
  meterFraction: number | null
}

export interface AssistantRow {
  memberId: string
  userId: string
  name: string
  rolePreset: AssistantRole
  /** Toggles that differ from the preset. */
  overrides: Partial<Record<TeamPermission, boolean>>
  /** Effective permissions after overrides. */
  permissions: TeamPermission[]
  /** Cap on the lead's balance. `null` = no limit. */
  capUnits: number | null
  capPeriod: CapPeriod
  capUsedUnits: number
}

export type AssistantInvite = WireAssistantInvite

export interface TeamView {
  planActive: boolean
  subscriptionId: string | null
  seatCapacity: number
  /** Active plus leaving seats: both count against capacity (spec §4.4). */
  seatsUsed: number
  includedSeats: number
  extraSeats: number
  pendingExtraSeats: number | null
  extraSeatPriceMinor: number | null
  currency: string
  currentPeriodEnd: string | null
  savedCard: SavedCardView | null
  /** Subjects of the teacher's classes, for the scope editor. */
  subjects: { code: string; name: string }[]
  seats: SeatRow[]
  assistants: AssistantRow[]
  invites: AssistantInvite[]
}

export interface AssistantRoleUpdate {
  rolePreset: AssistantRole
  overrides: Partial<Record<TeamPermission, boolean>>
}

export interface TeamMembership {
  teacherName: string
  role: AssistantRole
}
```

- [ ] **Step 3b: Add the team adapters to `web/src/lib/billingAdapters.ts`**

Append (merge the new names into the file's type import from `@/lib/billingTypes`, and add
`import { isLiveSubscription } from "@/lib/billingFormat"`):

```ts
const PERMISSION_SET: ReadonlySet<string> = new Set(TEAM_PERMISSIONS)

export function toSeatRow(w: WireSeat): SeatRow {
  return {
    memberId: w.memberId,
    studentUserId: w.studentId,
    studentName: w.studentName,
    status: w.status,
    leavesAt: w.leavesAt,
    scopeSubjects: w.scopeSubjects,
    scopeActions: w.scopeActions as MeteredAction[],
    capUnits: w.capUnits,
    capPeriod: w.capPeriod,
    capUsedUnits: w.capUsedUnits,
    meterFraction: w.meterFraction,
  }
}

export function toAssistantRow(w: WireAssistant): AssistantRow {
  const overrides: Partial<Record<TeamPermission, boolean>> = {}
  for (const [k, v] of Object.entries(w.permissions)) if (PERMISSION_SET.has(k)) overrides[k as TeamPermission] = v
  return {
    memberId: w.memberId,
    userId: w.assistantId,
    name: w.assistantName,
    rolePreset: w.role,
    overrides,
    permissions: w.effectivePermissions.filter((p): p is TeamPermission => PERMISSION_SET.has(p)),
    capUnits: w.capUnits,
    capPeriod: w.capPeriod,
    capUsedUnits: w.capUsedUnits,
  }
}

export interface TeamParts {
  seats: { seats: WireSeat[] }
  capacity: WireSeatCapacity
  assistants: { assistants: WireAssistant[] }
  invites: { invites: WireAssistantInvite[] }
  summary: WireBillingSummary
  classes: { classes: { subjectCode: string | null; subjectName: string | null }[] }
}

/** Plan fields come from the teacher's billing summary (M12); subjects from their classes. */
export function toTeamView(p: TeamParts): TeamView {
  const sub = p.summary.subscription
  const subjects = new Map<string, string>()
  for (const c of p.classes.classes) if (c.subjectCode) subjects.set(c.subjectCode, c.subjectName ?? c.subjectCode)
  return {
    planActive: isLiveSubscription(sub?.status),
    subscriptionId: sub?.subscriptionId ?? null,
    seatCapacity: p.capacity.capacity,
    seatsUsed: p.capacity.used,
    includedSeats: sub?.tier.includedSeats ?? 0,
    extraSeats: sub?.extraSeats ?? 0,
    pendingExtraSeats: sub?.pendingExtraSeats ?? null,
    extraSeatPriceMinor: sub ? sub.tier.extraSeatPriceMinor : null,
    currency: sub?.tier.currency ?? "EGP",
    currentPeriodEnd: sub?.currentPeriodEnd ?? null,
    savedCard: toSavedCard(p.summary.savedCard),
    subjects: [...subjects].map(([code, name]) => ({ code, name })),
    seats: p.seats.seats.map(toSeatRow),
    assistants: p.assistants.assistants.map(toAssistantRow),
    invites: p.invites.invites,
  }
}
```

- [ ] **Step 3c: Append team fixtures to `web/tests/unit/support/billingFixtures.ts`**

```ts
import type { AssistantRow, SeatRow, TeamView, WireAssistant, WireBillingSummary, WireSeat } from "@/lib/billingTypes"

const wireSeat: WireSeat = {
  kind: "student_seat",
  memberId: "m1",
  studentId: "u-s1",
  studentName: "Omar Hassan",
  status: "active",
  leavesAt: null,
  scopeSubjects: ["0580"],
  scopeActions: ["mark_paper", "self_review"],
  capUnits: null,
  capPeriod: "month",
  capUsedUnits: 0,
  meterFraction: 0.4,
}
const seat: SeatRow = {
  memberId: "m1",
  studentUserId: "u-s1",
  studentName: "Omar Hassan",
  status: "active",
  leavesAt: null,
  scopeSubjects: ["0580"],
  scopeActions: ["mark_paper", "self_review"],
  capUnits: null,
  capPeriod: "month",
  capUsedUnits: 0,
  meterFraction: 0.4,
}
const wireAssistant: WireAssistant = {
  kind: "assistant",
  memberId: "m9",
  assistantId: "u-a1",
  assistantName: "Sara Ali",
  role: "marker",
  permissions: {},
  effectivePermissions: ["mark", "regrade", "view_results"],
  capUnits: 2000,
  capPeriod: "month",
  capUsedUnits: 300,
}
const assistant: AssistantRow = {
  memberId: "m9",
  userId: "u-a1",
  name: "Sara Ali",
  rolePreset: "marker",
  overrides: {},
  permissions: ["mark", "regrade", "view_results"],
  capUnits: 2000,
  capPeriod: "month",
  capUsedUnits: 300,
}
const wireTeacherTier = {
  planTierId: "t-t-m",
  code: "teacher_pro_m",
  name: "Teacher Pro",
  priceMinor: 90000,
  currency: "EGP",
  interval: "monthly" as const,
  audience: "teacher",
  includedSeats: 20,
  extraSeatPriceMinor: 3000,
  features: {},
}
const wireTeacherSummary: WireBillingSummary = {
  beneficiary: { userId: "u-t", displayName: "Ms Nour", audience: "teacher" },
  subscription: {
    subscriptionId: "sub-t",
    status: "active",
    tier: wireTeacherTier,
    currentPeriodStart: "2026-11-01T00:00:00Z",
    currentPeriodEnd: "2026-12-01T00:00:00Z",
    cancelAtPeriodEnd: false,
    pendingTier: null,
    graceUntil: null,
    extraSeats: 2,
    pendingExtraSeats: null,
  },
  canManage: true,
  managedByName: null,
  savedCard: { cardId: "card1", maskedPan: "•••• 2346", brand: "Mastercard" },
  usage: { fraction: 0.2, resetsAt: "2026-12-01T00:00:00Z" },
  credits: { totalUnits: 5000, expiring: [] },
  debtUnits: 0,
  seats: { capacity: 22, used: 1 },
}
const team: TeamView = {
  planActive: true,
  subscriptionId: "sub-t",
  seatCapacity: 22,
  seatsUsed: 1,
  includedSeats: 20,
  extraSeats: 2,
  pendingExtraSeats: null,
  extraSeatPriceMinor: 3000,
  currency: "EGP",
  currentPeriodEnd: "2026-12-01T00:00:00Z",
  savedCard: { cardId: "card1", maskedPan: "•••• 2346", brand: "Mastercard" },
  subjects: [{ code: "0580", name: "Mathematics" }],
  seats: [seat],
  assistants: [assistant],
  invites: [{ inviteId: "inv1", code: "AST-7KQ2", role: "viewer", expiresAt: "2026-11-12T00:00:00Z", createdAt: "2026-11-05T00:00:00Z" }],
}
```

Place this block above `export const fx = {` (merge its type import into the file's existing
`import type … from "@/lib/billingTypes"`), and add `wireSeat, seat, wireAssistant, assistant,
wireTeacherSummary, team` to the `fx` object literal. The fixture file stays one object
literal, typed by inference.

- [ ] **Step 3d: Write `web/src/lib/hooks/useTeamApi.ts`**

```ts
import { useMutation, useQuery, useQueryClient, type UseMutationResult, type UseQueryResult } from "@tanstack/react-query"
import { request } from "@/lib/api"
import { toTeamView } from "@/lib/billingAdapters"
import type {
  AssistantInviteCreate,
  AssistantRoleUpdate,
  CapUpdate,
  SeatScopeUpdate,
  TeamMembership,
  TeamView,
  WireAssistant,
  WireAssistantInvite,
  WireAssistantUpdate,
  WireMembership,
  WireSeat,
  WireSeatCapacity,
} from "@/lib/billingTypes"
import { billingApi } from "@/lib/hooks/useBillingApi"
import type { ClassList } from "@/lib/teacherTypes"

/*
 * React-query hooks over `/api/teacher/team/*` (plan 03 Task 7). Lead teacher only: billing,
 * seats, caps and assistants are never assistant permissions (spec §2.3, §7). Every write
 * refetches the team, because seat counts, scope and caps are read together on one screen.
 */

const enc = encodeURIComponent
const json = (method: string, body: unknown): RequestInit => ({ method, body: JSON.stringify(body) })
const T = "/teacher/team"

export const teamApi = {
  seats: () => request<{ seats: WireSeat[] }>(`${T}/seats`),
  capacity: () => request<WireSeatCapacity>(`${T}/capacity`),
  assistants: () => request<{ assistants: WireAssistant[] }>(`${T}/assistants`),
  invites: () => request<{ invites: WireAssistantInvite[] }>(`${T}/invites`),
  memberships: () => request<{ memberships: WireMembership[] }>(`${T}/memberships`),
  setScope: (memberId: string, body: SeatScopeUpdate) => request<WireSeat>(`${T}/seats/${enc(memberId)}/scope`, json("PUT", body)),
  /** Returns the member's DTO, discriminated by `kind`. */
  setCap: (memberId: string, body: CapUpdate) => request<WireSeat | WireAssistant>(`${T}/members/${enc(memberId)}/cap`, json("PUT", body)),
  /** Starts month-end release: the seat comes back `leaving` with `leavesAt`. */
  removeSeat: (memberId: string) => request<WireSeat>(`${T}/seats/${enc(memberId)}`, { method: "DELETE" }),
  createInvite: (body: AssistantInviteCreate) => request<WireAssistantInvite>(`${T}/assistants/invites`, json("POST", body)),
  revokeInvite: (inviteId: string) => request<void>(`${T}/invites/${enc(inviteId)}`, { method: "DELETE" }),
  updateAssistant: (memberId: string, body: WireAssistantUpdate) =>
    request<WireAssistant>(`${T}/assistants/${enc(memberId)}`, json("PATCH", body)),
  removeAssistant: (memberId: string) => request<void>(`${T}/assistants/${enc(memberId)}`, { method: "DELETE" }),
  redeem: (code: string) => request<WireMembership>(`${T}/assistants/redeem`, json("POST", { code })),
}

export const teamKeys = { team: ["team"] as const }

export function useTeam(): UseQueryResult<TeamView, Error> {
  return useQuery({
    queryKey: teamKeys.team,
    queryFn: async () => {
      const [seats, capacity, assistants, invites, summary, classes] = await Promise.all([
        teamApi.seats(),
        teamApi.capacity(),
        teamApi.assistants(),
        teamApi.invites(),
        billingApi.summary(null),
        request<ClassList>("/teacher/classes"),
      ])
      return toTeamView({ seats, capacity, assistants, invites, summary, classes })
    },
  })
}

function useTeamWrite<TVars, TData>(fn: (vars: TVars) => Promise<TData>): UseMutationResult<TData, Error, TVars> {
  const qc = useQueryClient()
  return useMutation({ mutationFn: fn, onSuccess: () => qc.invalidateQueries({ queryKey: teamKeys.team }) })
}

export const useSetSeatScope = () =>
  useTeamWrite((v: { memberId: string; body: SeatScopeUpdate }) => teamApi.setScope(v.memberId, v.body))
export const useSetMemberCap = () => useTeamWrite((v: { memberId: string; body: CapUpdate }) => teamApi.setCap(v.memberId, v.body))
export const useRemoveSeat = () => useTeamWrite((memberId: string) => teamApi.removeSeat(memberId))
export const useCreateAssistantInvite = () => useTeamWrite((body: AssistantInviteCreate) => teamApi.createInvite(body))
export const useRevokeAssistantInvite = () => useTeamWrite((inviteId: string) => teamApi.revokeInvite(inviteId))
export const useSetAssistantRole = () =>
  useTeamWrite((v: { memberId: string; body: AssistantRoleUpdate }) =>
    teamApi.updateAssistant(v.memberId, { role: v.body.rolePreset, permissions: v.body.overrides as Record<string, boolean> }),
  )
export const useRemoveAssistant = () => useTeamWrite((memberId: string) => teamApi.removeAssistant(memberId))
export const useJoinTeam = () =>
  useTeamWrite(async (code: string): Promise<TeamMembership> => {
    const m = await teamApi.redeem(code)
    return { teacherName: m.teacherName, role: m.role }
  })
```

- [ ] **Step 4: Write `web/src/lib/teamModel.ts`**

```ts
import { formatBillingDate, formatCredits } from "@/lib/billingFormat"
import type { AssistantRow, MeteredAction, SeatRow, TeamView } from "@/lib/billingTypes"

/* Pure view models for the seats and assistants screens. */

/** Mirrors the backend seat-eligible set (`SEAT_ACTIONS`, index R12; Phase 04 added
 * `mark_quiz` and `generate_flashcards`). */
export const SEAT_ACTIONS = ["mark_paper", "self_review", "study_plan", "mark_quiz", "generate_flashcards"] as const satisfies readonly MeteredAction[]
export type SeatAction = (typeof SEAT_ACTIONS)[number]

export const SEAT_ACTION_COPY: Record<SeatAction, { label: string; hint: string | null }> = {
  mark_paper: { label: "Paper marking", hint: null },
  self_review: { label: "Self-review", hint: null },
  study_plan: {
    label: "Weekly study plans",
    hint: "Off by default. When on, the seat pays for the first plan per subject each week. Regenerating that week uses the student's own balance.",
  },
  mark_quiz: { label: "Quiz marking", hint: null },
  generate_flashcards: { label: "Flashcard generation", hint: null },
}

export function seatCapacityModel(team: TeamView) {
  const capacity = team.seatCapacity
  const used = team.seatsUsed
  return {
    used,
    capacity,
    free: Math.max(0, capacity - used),
    barValue: capacity > 0 ? Math.min(100, Math.round((used / capacity) * 100)) : 0,
    label: `${used} of ${capacity} seats used`,
    detail: `${team.includedSeats} included with your plan, ${team.extraSeats} extra`,
  }
}

export function seatStatusText(seat: SeatRow): string {
  if (seat.status === "leaving" && seat.leavesAt) return `Leaving on ${formatBillingDate(seat.leavesAt)}`
  return seat.status === "removed" ? "Removed" : "Active"
}

const period = (p: "month" | "total") => (p === "month" ? "a month" : "in total")

export function seatCapText(seat: SeatRow): string {
  if (seat.capUnits === null) return "No overflow"
  return `Up to ${new Intl.NumberFormat().format(seat.capUnits)} of your credits ${period(seat.capPeriod)} (${seat.capUsedUnits} used)`
}

export function assistantCapText(row: AssistantRow): string {
  if (row.capUnits === null) return "No limit"
  return `Up to ${formatCredits(row.capUnits)} ${period(row.capPeriod)} (${row.capUsedUnits} used)`
}

export function scopeSummary(seat: SeatRow, subjects: { code: string; name: string }[]): string {
  const names = seat.scopeSubjects.map((code) => subjects.find((s) => s.code === code)?.name ?? code)
  const actions = seat.scopeActions
    .filter((a): a is SeatAction => (SEAT_ACTIONS as readonly string[]).includes(a))
    .map((a) => SEAT_ACTION_COPY[a].label)
  return `${names.join(", ") || "No subjects"} · ${actions.join(", ") || "No actions"}`
}
```

- [ ] **Step 5: Run it to verify it passes**

Run: `npx vitest run tests/unit/teamModel.test.ts`
Expected: PASS.

- [ ] **Step 6: Write the failing screen test**

`web/tests/unit/teamSeats.test.ts`:

```ts
import { createElement as h } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { ApiError } from "@/lib/api"
import { formatBillingDate } from "@/lib/billingFormat"
import { fx } from "./support/billingFixtures"
import { errorQuery, fakeMutation, okQuery, renderStatic } from "./support/billingRender"

const s = vi.hoisted(() => ({
  team: null as unknown,
  m: {} as Record<string, unknown>,
}))
vi.mock("@/lib/hooks/useTeamApi", () => ({
  useTeam: () => s.team,
  useSetSeatScope: () => s.m.scope,
  useSetMemberCap: () => s.m.cap,
  useRemoveSeat: () => s.m.remove,
}))
vi.mock("@/lib/hooks/useBillingApi", () => ({
  useSeatQuote: () => s.m.quote,
  useAddSeats: () => s.m.add,
  useReduceSeats: () => s.m.reduce,
  usePaymentStatus: () => Object.assign(okQuery(fx.payment), { pollingStopped: false }),
}))
vi.mock("@/components/ui/modal", () => ({
  Modal: (p: { open: boolean; title: unknown; children: unknown; footer?: unknown }) =>
    p.open ? h("div", { role: "dialog" }, h("h2", null, p.title as never), p.children as never, p.footer as never) : null,
}))

import { AddSeatsDialog, ReduceSeatsDialog } from "@/portals/teacher/screens/team/SeatCountDialogs"
import { RemoveSeatDialog, SeatEditorDialog } from "@/portals/teacher/screens/team/SeatEditorDialog"
import { SeatsPanel } from "@/portals/teacher/screens/team/SeatsPanel"
import { Team } from "@/portals/teacher/screens/team/Team"

beforeEach(() => {
  s.team = okQuery(fx.team)
  s.m = { scope: fakeMutation(), cap: fakeMutation(), remove: fakeMutation(), quote: fakeMutation(), add: fakeMutation(), reduce: fakeMutation() }
})

const addDialog = (savedCard = fx.team.savedCard) =>
  renderStatic(h(AddSeatsDialog, { open: true, onClose: () => undefined, subscriptionId: "sub-t", perSeatMinor: 3000, savedCard }))

describe("SeatsPanel", () => {
  it("shows capacity, the seat list and actions", () => {
    const html = renderStatic(h(SeatsPanel, { team: fx.team }))
    expect(html).toContain("1 of 22 seats used")
    expect(html).toContain("20 included with your plan, 2 extra")
    expect(html).toContain("Omar Hassan")
    expect(html).toContain("Mathematics · Paper marking, Self-review")
    expect(html).toContain("40%")
    expect(html).toContain("Add seats")
    expect(html).toContain("Remove extra seats")
  })

  it("explains an inactive plan, a scheduled reduction and an empty list", () => {
    const html = renderStatic(h(SeatsPanel, { team: { ...fx.team, planActive: false, pendingExtraSeats: 0, seats: [] } }))
    expect(html).toMatch(/role="status"[^>]*>.*seats get no new monthly allowances/)
    expect(html).toContain('href="/teacher/billing/plans"')
    expect(html).toContain("Drops to 0 extra seats on")
    expect(html).toContain("No students hold a seat yet.")
  })

  it("hides removal for a leaving seat", () => {
    const leaving = { ...fx.seat, status: "leaving" as const, leavesAt: "2026-11-30T23:59:59Z" }
    const html = renderStatic(h(SeatsPanel, { team: { ...fx.team, seats: [leaving] } }))
    expect(html).toContain(`Leaving on ${formatBillingDate("2026-11-30T23:59:59Z")}`)
    expect(html).not.toContain("Remove Omar Hassan")
  })
})

describe("Team screen", () => {
  it("tells an assistant that the lead teacher manages seats", () => {
    s.team = errorQuery(new ApiError(403, "x"))
    expect(renderStatic(h(Team))).toContain("managed by the lead teacher")
  })
})

describe("SeatEditorDialog", () => {
  const render = (seat = fx.seat) =>
    renderStatic(h(SeatEditorDialog, { open: true, onClose: () => undefined, seat, subjects: [...fx.team.subjects, { code: "0625", name: "Physics" }] }))

  it("lists subjects and actions, study plans unchecked by default with its hint", () => {
    const html = render()
    expect(html).toContain("Mathematics")
    expect(html).toContain("Physics")
    expect(html).toContain("Weekly study plans")
    expect(html).toContain("Off by default.")
    expect(html).toMatch(/<input(?=[^>]*value="study_plan")(?![^>]*checked)[^>]*>/)
    expect(html).toMatch(/<input(?=[^>]*value="mark_paper")(?=[^>]*checked)[^>]*>/)
  })

  it("warns when a seat covers no subjects", () => {
    expect(render({ ...fx.seat, scopeSubjects: [] })).toContain("With no subjects, this seat pays for nothing.")
  })
})

describe("RemoveSeatDialog", () => {
  it("states month-end release", () => {
    const html = renderStatic(h(RemoveSeatDialog, { open: true, onClose: () => undefined, seat: fx.seat }))
    expect(html).toContain("keeps the seat until")
    expect(html).toContain("Remove at month end")
  })
})

describe("seat count dialogs", () => {
  it("quotes and confirms extra seats against the saved card", () => {
    s.m.quote = fakeMutation({ isSuccess: true, data: { amountMinor: 4500, currency: "EGP", allowanceUnits: null, periodEnd: "2026-12-01T00:00:00Z" } })
    const html = addDialog()
    expect(html).toMatch(/Pay EGP\s45\.00 and add seats/)
    expect(html).toMatch(/EGP\s30\.00 per seat/)
    expect(html).toContain("Mastercard")
  })

  it("refuses without a saved card", () => {
    s.m.quote = fakeMutation({ isSuccess: true, data: { amountMinor: 4500, currency: "EGP", allowanceUnits: null, periodEnd: "2026-12-01T00:00:00Z" } })
    const html = addDialog(null)
    expect(html).toContain("Seats are charged to a saved card.")
    expect(html).not.toContain("and add seats")
  })

  it("follows the charge after confirming", () => {
    s.m.add = fakeMutation({ isSuccess: true, data: { paymentId: "pay1", status: "pending", amountMinor: 4500, currency: "EGP" } })
    expect(addDialog()).toContain("Confirming your payment")
  })

  it("maps a seats-in-use refusal when reducing and reports the new total", () => {
    s.m.reduce = fakeMutation({ isError: true, error: new ApiError(409, "x", { error: "seats_in_use", message: "x" }) })
    const reduce = () =>
      renderStatic(h(ReduceSeatsDialog, { open: true, onClose: () => undefined, subscriptionId: "sub-t", extraSeats: 2 }))
    expect(reduce()).toContain("More students hold seats than this would leave.")
    s.m.reduce = fakeMutation({ isSuccess: true, data: { extraSeats: 2, pendingExtraSeats: 1 } })
    expect(reduce()).toContain("1 extra seat from the end of this period.")
  })
})
```

- [ ] **Step 7: Run it to verify it fails**

Run: `npx vitest run tests/unit/teamSeats.test.ts`
Expected: FAIL, "Failed to resolve import "@/portals/teacher/screens/team/SeatCountDialogs"".

- [ ] **Step 8: Write `SeatCountDialogs.tsx`**

`web/src/portals/teacher/screens/team/SeatCountDialogs.tsx`:

```tsx
import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Modal } from "@/components/ui/modal"
import { formatMoney } from "@/lib/billingFormat"
import { billingFailureMessage } from "@/lib/billingOutcome"
import type { SavedCardView } from "@/lib/billingTypes"
import { useAddSeats, useReduceSeats, useSeatQuote } from "@/lib/hooks/useBillingApi"
import { PaymentProgress } from "@/portals/billing/PaymentProgress"

/*
 * Extra seats (spec §2.2, §5.4): adding charges the prorated price now on the saved card
 * (`…/seats/quote`, then `…/seats`, 202) and the seats renew with the plan; removing
 * schedules a lower total for the next renewal (`…/seats/pending`) and is refused while
 * it would leave fewer seats than seated students.
 */

const clamp = (v: string, max: number) => Math.max(1, Math.min(max, Math.floor(Number(v) || 1)))

export function AddSeatsDialog({
  open,
  onClose,
  subscriptionId,
  perSeatMinor,
  savedCard,
}: {
  open: boolean
  onClose: () => void
  subscriptionId: string
  perSeatMinor: number | null
  savedCard: SavedCardView | null
}) {
  const [qty, setQty] = useState("1")
  const quote = useSeatQuote()
  const add = useAddSeats()
  const q = quote.data
  const seats = clamp(qty, 100)
  const failure = add.isError ? add.error : quote.isError ? quote.error : null
  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Add seats"
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>{add.isSuccess ? "Close" : "Not now"}</Button>
          {add.isSuccess ? null : q && savedCard ? (
            <Button variant="primary" loading={add.isPending} onClick={() => add.mutate({ subscriptionId, seats })}>
              Pay {formatMoney(q.amountMinor, q.currency)} and add seats
            </Button>
          ) : q ? null : (
            <Button variant="primary" loading={quote.isPending} onClick={() => quote.mutate({ subscriptionId, seats })}>
              Get the price
            </Button>
          )}
        </div>
      }
    >
      <div className="flex flex-col gap-3">
        {add.isSuccess && add.data ? (
          <PaymentProgress paymentId={add.data.paymentId} />
        ) : (
          <>
            <Input
              label="How many seats"
              type="number"
              inputMode="numeric"
              min={1}
              max={100}
              value={qty}
              onChange={(e) => {
                setQty(e.target.value)
                quote.reset()
              }}
            />
            {q ? (
              savedCard ? (
                <p className="m-0 text-body-md text-on-surface">
                  You pay <span className="text-data-md">{formatMoney(q.amountMinor, q.currency)}</span> now for the rest of this
                  period
                  {perSeatMinor !== null ? `, then ${formatMoney(perSeatMinor, q.currency)} per seat each period with your plan` : ""}.
                  Charged to {savedCard.brand} {savedCard.maskedPan}.
                </p>
              ) : (
                <p className="m-0 text-body-md text-on-surface">
                  Seats are charged to a saved card. Buy a credit pack by card once and Lemely keeps the card for later charges.
                </p>
              )
            ) : null}
          </>
        )}
        {failure ? <p role="alert" className="m-0 text-body-sm text-error">{billingFailureMessage(failure, "add seats")}</p> : null}
      </div>
    </Modal>
  )
}

export function ReduceSeatsDialog({
  open,
  onClose,
  subscriptionId,
  extraSeats,
}: {
  open: boolean
  onClose: () => void
  subscriptionId: string
  extraSeats: number
}) {
  const [qty, setQty] = useState("1")
  const reduce = useReduceSeats()
  const pending = reduce.data?.pendingExtraSeats ?? null
  return (
    <Modal
      open={open}
      onClose={onClose}
      size="sm"
      title="Remove extra seats"
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>{reduce.isSuccess ? "Close" : "Not now"}</Button>
          {reduce.isSuccess ? null : (
            <Button
              variant="primary"
              loading={reduce.isPending}
              onClick={() => reduce.mutate({ subscriptionId, extraSeats: extraSeats - clamp(qty, extraSeats) })}
            >
              Remove at period end
            </Button>
          )}
        </div>
      }
    >
      <div className="flex flex-col gap-3">
        {reduce.isSuccess && pending !== null ? (
          <p role="status" className="m-0 text-body-md text-on-surface">
            {pending} extra {pending === 1 ? "seat" : "seats"} from the end of this period.
          </p>
        ) : (
          <>
            <p className="m-0 text-body-md text-on-surface">
              Seats you remove stay usable until the end of this period. You can't remove seats students still hold.
            </p>
            <Input label="How many seats" type="number" inputMode="numeric" min={1} max={extraSeats} value={qty} onChange={(e) => setQty(e.target.value)} />
          </>
        )}
        {reduce.isError ? <p role="alert" className="m-0 text-body-sm text-error">{billingFailureMessage(reduce.error, "remove seats")}</p> : null}
      </div>
    </Modal>
  )
}
```

- [ ] **Step 9: Write `SeatEditorDialog.tsx`**

`web/src/portals/teacher/screens/team/SeatEditorDialog.tsx`:

```tsx
import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Modal } from "@/components/ui/modal"
import { Select } from "@/components/ui/select"
import { formatBillingDate } from "@/lib/billingFormat"
import { billingFailureMessage } from "@/lib/billingOutcome"
import type { CapPeriod, MeteredAction, SeatRow } from "@/lib/billingTypes"
import { useRemoveSeat, useSetMemberCap, useSetSeatScope } from "@/lib/hooks/useTeamApi"
import { SEAT_ACTIONS, SEAT_ACTION_COPY } from "@/lib/teamModel"

/*
 * A seat's scope and overflow cap (spec §2.2). Subjects route work per subject; actions say
 * what the seat pays for. Weekly study plans are off unless the teacher turns them on.
 * The scope is enforced server-side; this dialog only edits it.
 */

const toggle = <T,>(list: T[], item: T, on: boolean) => (on ? [...new Set([...list, item])] : list.filter((x) => x !== item))

export function SeatEditorDialog({
  open,
  onClose,
  seat,
  subjects,
}: {
  open: boolean
  onClose: () => void
  seat: SeatRow
  subjects: { code: string; name: string }[]
}) {
  const scope = useSetSeatScope()
  const cap = useSetMemberCap()
  const [subjectCodes, setSubjectCodes] = useState<string[]>(seat.scopeSubjects)
  const [actions, setActions] = useState<MeteredAction[]>(seat.scopeActions)
  const [overflow, setOverflow] = useState(seat.capUnits !== null)
  const [capUnits, setCapUnits] = useState(String(seat.capUnits ?? 500))
  const [capPeriod, setCapPeriod] = useState<CapPeriod>(seat.capPeriod)
  const failure = scope.isError ? scope.error : cap.isError ? cap.error : null

  const save = () =>
    scope.mutate(
      { memberId: seat.memberId, body: { subjects: subjectCodes, actions } },
      {
        onSuccess: () =>
          cap.mutate(
            {
              memberId: seat.memberId,
              body: { capUnits: overflow ? Math.max(1, Math.floor(Number(capUnits) || 1)) : null, capPeriod },
            },
            { onSuccess: onClose },
          ),
      },
    )

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={`Seat for ${seat.studentName}`}
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button variant="primary" loading={scope.isPending || cap.isPending} onClick={save}>Save seat</Button>
        </div>
      }
    >
      <div className="flex flex-col gap-5">
        <fieldset className="m-0 flex flex-col gap-2 border-0 p-0">
          <legend className="mb-2 text-label text-on-surface">Subjects this seat covers</legend>
          {subjects.map((s) => (
            <Checkbox
              key={s.code}
              name="subjects"
              value={s.code}
              label={s.name}
              checked={subjectCodes.includes(s.code)}
              onChange={(e) => setSubjectCodes((l) => toggle(l, s.code, e.target.checked))}
            />
          ))}
          {subjectCodes.length === 0 ? (
            <p className="m-0 text-body-sm text-on-surface-variant">With no subjects, this seat pays for nothing.</p>
          ) : null}
        </fieldset>
        <fieldset className="m-0 flex flex-col gap-2 border-0 p-0">
          <legend className="mb-2 text-label text-on-surface">What the seat pays for</legend>
          {SEAT_ACTIONS.map((a) => (
            <div key={a} className="flex flex-col gap-0.5">
              <Checkbox
                name="actions"
                value={a}
                label={SEAT_ACTION_COPY[a].label}
                checked={actions.includes(a)}
                onChange={(e) => setActions((l) => toggle(l, a, e.target.checked))}
              />
              {SEAT_ACTION_COPY[a].hint ? (
                <p className="m-0 ps-7 text-body-sm text-on-surface-variant">{SEAT_ACTION_COPY[a].hint}</p>
              ) : null}
            </div>
          ))}
        </fieldset>
        <fieldset className="m-0 flex flex-col gap-2 border-0 p-0">
          <legend className="mb-2 text-label text-on-surface">When the seat's monthly allowance runs out</legend>
          <Checkbox
            name="overflow"
            label="Let them use my credits"
            checked={overflow}
            onChange={(e) => setOverflow(e.target.checked)}
          />
          {overflow ? (
            <div className="grid gap-3 md:grid-cols-2">
              <Input label="Up to (credits)" type="number" inputMode="numeric" min={1} value={capUnits} onChange={(e) => setCapUnits(e.target.value)} />
              <Select label="Limit resets" value={capPeriod} onChange={(e) => setCapPeriod(e.target.value === "total" ? "total" : "month")}>
                <option value="month">Every month</option>
                <option value="total">Never (total)</option>
              </Select>
            </div>
          ) : (
            <p className="m-0 text-body-sm text-on-surface-variant">Their own plan or credits pay once the seat's allowance is used.</p>
          )}
        </fieldset>
        {failure ? <p role="alert" className="m-0 text-body-sm text-error">{billingFailureMessage(failure, "save this seat")}</p> : null}
      </div>
    </Modal>
  )
}

function monthEnd(now: Date): string {
  return new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() + 1, 0, 23, 59, 59)).toISOString()
}

export function RemoveSeatDialog({ open, onClose, seat }: { open: boolean; onClose: () => void; seat: SeatRow }) {
  const remove = useRemoveSeat()
  return (
    <Modal
      open={open}
      onClose={onClose}
      size="sm"
      title={`Remove ${seat.studentName}`}
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>Keep seat</Button>
          <Button variant="primary" loading={remove.isPending} onClick={() => remove.mutate(seat.memberId, { onSuccess: onClose })}>
            Remove at month end
          </Button>
        </div>
      }
    >
      <p className="m-0 text-body-md text-on-surface">
        {seat.studentName} keeps the seat until {formatBillingDate(monthEnd(new Date()))}, then it frees up. Their current monthly
        allowance runs until it expires.
      </p>
      {remove.isError ? <p role="alert" className="m-0 mt-2 text-body-sm text-error">{billingFailureMessage(remove.error, "remove this seat")}</p> : null}
    </Modal>
  )
}
```

`Checkbox` (`web/src/components/ui/checkbox.tsx`) takes a visible `label` and passes `name`,
`value`, `checked` and `onChange` to its native input, which is what the test's
`value="study_plan"` lookahead reads.

- [ ] **Step 10: Write `SeatsPanel.tsx` and `Team.tsx`**

`web/src/portals/teacher/screens/team/SeatsPanel.tsx`:

```tsx
import { useState } from "react"
import { Link } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Card, CardBody } from "@/components/ui/card"
import { ProgressBar } from "@/components/ui/progress-bar"
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table"
import { formatBillingDate, formatPercent } from "@/lib/billingFormat"
import type { SeatRow, TeamView } from "@/lib/billingTypes"
import { scopeSummary, seatCapText, seatCapacityModel, seatStatusText } from "@/lib/teamModel"
import { AddSeatsDialog, ReduceSeatsDialog } from "./SeatCountDialogs"
import { RemoveSeatDialog, SeatEditorDialog } from "./SeatEditorDialog"

/* Seat capacity, extra seats and the per-seat list (spec §2.2, §4.4). */

export function SeatsPanel({ team }: { team: TeamView }) {
  const cap = seatCapacityModel(team)
  const [adding, setAdding] = useState(false)
  const [reducing, setReducing] = useState(false)
  const [editing, setEditing] = useState<SeatRow | null>(null)
  const [removing, setRemoving] = useState<SeatRow | null>(null)
  return (
    <section aria-labelledby="seats-heading" className="flex flex-col gap-4">
      <h2 id="seats-heading" className="m-0 text-display-sm text-on-surface">Student seats</h2>
      {!team.planActive ? (
        <p role="status" className="m-0 rounded-lg bg-surface-container-high p-4 text-body-sm text-on-surface">
          Your plan isn't active, so seats get no new monthly allowances. Students keep their seats.{" "}
          <Link to="/teacher/billing/plans" className="font-medium text-primary underline-offset-2 hover:underline">See plans</Link>
        </p>
      ) : null}
      <Card>
        <CardBody className="flex flex-col gap-3">
          <ProgressBar value={cap.barValue} label={cap.label} />
          <p className="m-0 text-body-sm text-on-surface-variant">{cap.detail}</p>
          {team.pendingExtraSeats !== null && team.currentPeriodEnd ? (
            <p className="m-0 text-body-sm text-on-surface-variant">
              Drops to {team.pendingExtraSeats} extra seats on {formatBillingDate(team.currentPeriodEnd)}
            </p>
          ) : null}
          <div className="flex flex-wrap gap-2">
            <Button variant="primary" onClick={() => setAdding(true)} disabled={!team.planActive || team.subscriptionId === null}>Add seats</Button>
            {team.extraSeats > 0 ? <Button variant="ghost" onClick={() => setReducing(true)}>Remove extra seats</Button> : null}
          </div>
        </CardBody>
      </Card>
      {team.seats.length === 0 ? (
        <p className="m-0 text-body-md text-on-surface-variant">
          No students hold a seat yet. Students take a seat when they join one of your classes with its code.
        </p>
      ) : (
        <Table density="operate">
          <caption className="sr-only">Student seats</caption>
          <THead>
            <TR>
              <TH>Student</TH>
              <TH>Covers</TH>
              <TH numeric>This month</TH>
              <TH>Overflow</TH>
              <TH>Status</TH>
              <TH><span className="sr-only">Actions</span></TH>
            </TR>
          </THead>
          <TBody>
            {team.seats.map((seat) => (
              <TR key={seat.memberId}>
                <TD>
                  {seat.studentName}
                </TD>
                <TD>{scopeSummary(seat, team.subjects)}</TD>
                <TD numeric>{seat.meterFraction === null ? "—" : formatPercent(seat.meterFraction)}</TD>
                <TD>{seatCapText(seat)}</TD>
                <TD>{seatStatusText(seat)}</TD>
                <TD>
                  <div className="flex gap-1">
                    <Button size="sm" variant="ghost" onClick={() => setEditing(seat)} aria-label={`Edit seat for ${seat.studentName}`}>Edit</Button>
                    {seat.status === "active" ? (
                      <Button size="sm" variant="ghost" onClick={() => setRemoving(seat)} aria-label={`Remove ${seat.studentName}`}>Remove</Button>
                    ) : null}
                  </div>
                </TD>
              </TR>
            ))}
          </TBody>
        </Table>
      )}
      {team.subscriptionId ? (
        <>
          <AddSeatsDialog
            open={adding}
            onClose={() => setAdding(false)}
            subscriptionId={team.subscriptionId}
            perSeatMinor={team.extraSeatPriceMinor}
            savedCard={team.savedCard}
          />
          <ReduceSeatsDialog open={reducing} onClose={() => setReducing(false)} subscriptionId={team.subscriptionId} extraSeats={team.extraSeats} />
        </>
      ) : null}
      {editing ? <SeatEditorDialog key={editing.memberId} open onClose={() => setEditing(null)} seat={editing} subjects={team.subjects} /> : null}
      {removing ? <RemoveSeatDialog open onClose={() => setRemoving(null)} seat={removing} /> : null}
    </section>
  )
}
```

(The empty-meter cell is the repo's `{value ?? "—"}` empty-value glyph, which
`scripts/check_copy.mjs` allows by design.)

`web/src/portals/teacher/screens/team/Team.tsx`:

```tsx
import { ApiError } from "@/lib/api"
import { PageHeaderSkeleton } from "@/components/ui/loading-shapes"
import { Eyebrow } from "@/components/ui/primitives"
import { QueryState } from "@/components/ui/query-state"
import { useTeam } from "@/lib/hooks/useTeamApi"
import { SeatsPanel } from "./SeatsPanel"

/*
 * `/teacher/team`: the lead teacher's seats (and, from Task 12, assistants). Billing, seats,
 * caps and assistants stay with the lead teacher (spec §2.3), so an assistant gets 403 here.
 */

export function Team() {
  const team = useTeam()
  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-2">
        <Eyebrow>Your team</Eyebrow>
        <h1 className="m-0 text-display-md text-on-surface">Seats and assistants</h1>
      </div>
      <QueryState
        query={team}
        skeleton={<PageHeaderSkeleton />}
        error={{
          heading: "Couldn't load your team",
          body: (e) =>
            e instanceof ApiError && e.status === 403
              ? "Seats and assistants are managed by the lead teacher."
              : "Check your connection and try again.",
        }}
      >
        {(t) => <SeatsPanel team={t} />}
      </QueryState>
    </div>
  )
}
```

- [ ] **Step 11: Mount the route and nav entry**

`web/src/portals/teacher/data.ts`: add `| "team"` to `NavItem["icon"]`; add
`{ to: "/teacher/team", label: "Seats and assistants", icon: "team" },` directly before the
"Plan and billing" entry. `web/src/portals/teacher/index.tsx`: import `UsersFour` from
`@phosphor-icons/react`, add `team: UsersFour,` to `NAV_ICON`, lazy-import
`Team` from `./screens/team/Team`, and add a child before `billing`:

```tsx
    {
      path: "team",
      element: <Team />,
      handle: { title: "Seats and assistants", skeleton: "page-header" },
    },
```

Update `web/tests/unit/navigation.test.ts` the same way as Task 5 if it pins the teacher list.

- [ ] **Step 12: Run the tests to verify they pass**

Run: `npx vitest run tests/unit/teamModel.test.ts tests/unit/teamSeats.test.ts tests/unit/navigation.test.ts`
Expected: PASS.

- [ ] **Step 13: Write the e2e spec**

`web/e2e/billing-team.spec.ts`:

```ts
import { test, expect } from "@playwright/test"
import { readSeed } from "./seed"

// Wire shapes: plan 03 team DTOs, plan 05 summary, the existing classes list.
const seat = {
  kind: "student_seat", memberId: "m1", studentId: "s1", studentName: "Omar Hassan", status: "active", leavesAt: null,
  scopeSubjects: ["0580"], scopeActions: ["mark_paper"], capUnits: null, capPeriod: "month", capUsedUnits: 0, meterFraction: 0.4,
}
const tier = {
  planTierId: "t", code: "teacher_pro_m", name: "Teacher Pro", priceMinor: 90000, currency: "EGP", interval: "monthly",
  audience: "teacher", includedSeats: 20, extraSeatPriceMinor: 3000, features: {},
}
const summary = {
  beneficiary: { userId: "u", displayName: "T", audience: "teacher" },
  subscription: {
    subscriptionId: "sub-t", status: "active", tier, currentPeriodStart: null, currentPeriodEnd: "2026-12-01T00:00:00Z",
    cancelAtPeriodEnd: false, pendingTier: null, graceUntil: null, extraSeats: 2, pendingExtraSeats: null,
  },
  canManage: true, managedByName: null, savedCard: null,
  usage: { fraction: null, resetsAt: null }, credits: { totalUnits: 0, expiring: [] }, debtUnits: 0, seats: { capacity: 22, used: 1 },
}

test("a teacher turns on weekly study plans for a seat", async ({ page }) => {
  const teacher = readSeed().teacher
  let scopeBody: unknown = null
  await page.route("**/api/teacher/team/seats", (r) => r.fulfill({ json: { seats: [seat] } }))
  await page.route("**/api/teacher/team/capacity", (r) => r.fulfill({ json: { capacity: 22, used: 1, free: 21 } }))
  await page.route("**/api/teacher/team/assistants", (r) => r.fulfill({ json: { assistants: [] } }))
  await page.route("**/api/teacher/team/invites", (r) => r.fulfill({ json: { invites: [] } }))
  await page.route("**/api/billing/summary**", (r) => r.fulfill({ json: summary }))
  await page.route("**/api/teacher/team/seats/m1/scope", async (r) => {
    scopeBody = r.request().postDataJSON()
    await r.fulfill({ json: seat })
  })
  await page.route("**/api/teacher/team/members/m1/cap", (r) => r.fulfill({ json: seat }))
  await page.goto("/login")
  await page.getByLabel("Email").fill(teacher.email)
  await page.getByLabel("Password").fill(teacher.password)
  await page.getByRole("button", { name: /sign in/i }).click()
  await expect(page).toHaveURL(/\/teacher/, { timeout: 15_000 })

  await page.goto("/teacher/team")
  await expect(page.getByText("1 of 22 seats used")).toBeVisible()
  await page.getByRole("button", { name: "Edit seat for Omar Hassan" }).click()
  const dialog = page.getByRole("dialog")
  await expect(dialog.getByLabel("Weekly study plans")).not.toBeChecked()
  await dialog.getByLabel("Weekly study plans").check()
  await dialog.getByRole("button", { name: "Save seat" }).click()
  await expect(dialog).toBeHidden()
  expect(scopeBody).toEqual({ subjects: ["0580"], actions: ["mark_paper", "study_plan"] })
})
```

- [ ] **Step 14: Run the e2e spec (local stack only)**

Run: `npx playwright test e2e/billing-team.spec.ts`
Expected: 1 passed, or "e2e not run: local stack down" recorded.

- [ ] **Step 15: Run the frontend gate**

```bash
npm run typecheck
npx vitest run tests/unit/teamModel.test.ts tests/unit/teamSeats.test.ts tests/unit/navigation.test.ts tests/unit/navRowIconGuard.test.ts tests/unit/tableDensity.test.ts $SCAN
npm run lint && npm run check:copy && npm run build
```
Expected: all exit 0.

- [ ] **Step 16: Commit**

```bash
cd /home/sico/Code/Lemely/.claude/worktrees/paymob-integration
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files && graphify update .
P="web/src/lib/billingTypes.ts web/src/lib/billingAdapters.ts web/tests/unit/support/billingFixtures.ts web/src/lib/hooks/useTeamApi.ts web/src/lib/teamModel.ts web/src/portals/teacher/screens/team/Team.tsx web/src/portals/teacher/screens/team/SeatsPanel.tsx web/src/portals/teacher/screens/team/SeatEditorDialog.tsx web/src/portals/teacher/screens/team/SeatCountDialogs.tsx web/src/portals/teacher/index.tsx web/src/portals/teacher/data.ts web/tests/unit/teamModel.test.ts web/tests/unit/teamSeats.test.ts web/e2e/billing-team.spec.ts"
git diff --quiet -- web/tests/unit/navigation.test.ts || P="$P web/tests/unit/navigation.test.ts"
git add $P
git commit -S -m "feat(web): teacher seats with scope, caps and extra seats" -- $P
```

---

### Task 12: Teacher assistants: invites, role presets and toggles, cap, joining a team

**Files:**
- Create: `web/src/lib/assistantRoles.ts`
- Create: `web/src/portals/teacher/screens/team/AssistantsPanel.tsx`
- Create: `web/src/portals/teacher/screens/team/AssistantDialogs.tsx`
- Create: `web/src/portals/teacher/screens/team/JoinTeamCard.tsx`
- Modify: `web/src/portals/teacher/screens/team/Team.tsx`
- Test: `web/tests/unit/assistantRoles.test.ts`, `web/tests/unit/teamAssistants.test.ts`

**Interfaces:**
- Consumes (Task 11): `useTeam`, `useCreateAssistantInvite`, `useRevokeAssistantInvite`,
  `useSetAssistantRole`, `useSetMemberCap`, `useRemoveAssistant`, `useJoinTeam`,
  `assistantCapText`; types `AssistantRole`, `AssistantRow`, `TeamPermission`,
  `TEAM_PERMISSIONS`, `TeamView`.
- Produces: `ROLE_COPY`, `PERMISSION_COPY`, `PRESET_PERMISSIONS` (frontend mirror of plan 03's
  presets), `effectivePermissions(preset, overrides)`, `overridesFor(preset, selected)`; `<AssistantsPanel team />`,
  `<RoleDialog>`, `<AssistantCapDialog>`, `<RemoveAssistantDialog>`, `<InviteDialog>`,
  `<JoinTeamCard />`.

Behaviour (spec §2.3, §4.4, index Phase 03 `TeamPermission`):

- Assistants are free and unlimited. Each row shows name (no email, by design), role, effective permissions,
  cap ("No limit" or "Up to {n} credits a month (used)") and Edit role · Set cap · Remove.
- Roles: **Co-teacher** "Everything except billing and seats." · **Marker** "Mark and regrade, and see the results they mark." · **Viewer** "Read only." Choosing a preset resets the toggles to that preset; each
  permission toggle can then differ, and only the differences are sent as `overrides`. The
  dialog states "Billing, plans and seats always stay with you."
- Invites: role + expiry (1, 7 or 14 days) → code shown once with a Copy button and its expiry;
  pending invites listed with Revoke. Empty: "No assistants yet. Invite a colleague with their
  own Lemely teacher account."
- Remove: "{name} loses access to your classes straight away." → "Remove assistant".
- Join (always shown, also to assistants who get 403 on the team): "Joining someone else's
  team? Enter the assistant code they sent you." → A25 → `role="status"` "You're now on
  {lead}'s team as {role}." Errors: 404 "That code isn't valid or has expired."; others use
  the generic sentence.

Permission labels: `mark` "Mark papers", `regrade` "Regrade papers", `generate_quiz` "Generate
quizzes", `manage_classes` "Manage classes", `view_results` "See results", `manage_students`
"Manage students", `view_usage` "See usage".

- [ ] **Step 1: Write the failing tests**

`web/tests/unit/assistantRoles.test.ts`:

```ts
import { describe, expect, it } from "vitest"
import { PERMISSION_COPY, PRESET_PERMISSIONS, ROLE_COPY, effectivePermissions, overridesFor } from "@/lib/assistantRoles"
import { TEAM_PERMISSIONS } from "@/lib/billingTypes"


describe("assistant roles", () => {
  it("labels every role and permission", () => {
    expect(ROLE_COPY.co_teacher.description).toBe("Everything except billing and seats.")
    expect(ROLE_COPY.marker.description).toBe("Mark and regrade, and see the results they mark.")
    expect(ROLE_COPY.viewer.description).toBe("Read only.")
    for (const p of TEAM_PERMISSIONS) expect(PERMISSION_COPY[p].length).toBeGreaterThan(0)
  })

  it("mirrors plan 03's presets", () => {
    expect(PRESET_PERMISSIONS.co_teacher).toEqual([...TEAM_PERMISSIONS])
    expect(PRESET_PERMISSIONS.marker).toEqual(["mark", "regrade", "view_results"])
    expect(PRESET_PERMISSIONS.viewer).toEqual(["view_results", "view_usage"])
  })

  it("applies overrides on top of a preset", () => {
    expect(effectivePermissions("marker", {})).toEqual(["mark", "regrade", "view_results"])
    expect(effectivePermissions("marker", { regrade: false, view_usage: true })).toEqual(["mark", "view_results", "view_usage"])
  })

  it("sends only the differences from the preset", () => {
    expect(overridesFor("marker", ["mark", "regrade", "view_results"])).toEqual({})
    expect(overridesFor("marker", ["mark", "view_results", "view_usage"])).toEqual({ regrade: false, view_usage: true })
  })
})
```

`web/tests/unit/teamAssistants.test.ts`:

```ts
import { createElement as h } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { ApiError } from "@/lib/api"
import { fx } from "./support/billingFixtures"
import { fakeMutation, renderStatic } from "./support/billingRender"

const m = vi.hoisted(() => ({} as Record<string, unknown>))
vi.mock("@/lib/hooks/useTeamApi", () => ({
  useCreateAssistantInvite: () => m.invite,
  useRevokeAssistantInvite: () => m.revoke,
  useSetAssistantRole: () => m.role,
  useSetMemberCap: () => m.cap,
  useRemoveAssistant: () => m.remove,
  useJoinTeam: () => m.join,
}))
vi.mock("@/components/ui/modal", () => ({
  Modal: (p: { open: boolean; title: unknown; children: unknown; footer?: unknown }) =>
    p.open ? h("div", { role: "dialog" }, h("h2", null, p.title as never), p.children as never, p.footer as never) : null,
}))

import { InviteDialog, RemoveAssistantDialog, RoleDialog } from "@/portals/teacher/screens/team/AssistantDialogs"
import { AssistantsPanel } from "@/portals/teacher/screens/team/AssistantsPanel"
import { JoinTeamCard } from "@/portals/teacher/screens/team/JoinTeamCard"

beforeEach(() => {
  for (const k of ["invite", "revoke", "role", "cap", "remove", "join"]) m[k] = fakeMutation()
})

describe("AssistantsPanel", () => {
  it("lists assistants with role, permissions and cap, and pending invites", () => {
    const html = renderStatic(h(AssistantsPanel, { team: fx.team }))
    expect(html).toContain("Sara Ali")
    expect(html).toContain("Marker")
    expect(html).toContain("Mark papers, Regrade papers, See results")
    expect(html).toContain("Up to 2,000 credits a month (300 used)")
    expect(html).toContain("AST-7KQ2")
    expect(html).toContain("Revoke")
  })

  it("explains an empty team", () => {
    const html = renderStatic(h(AssistantsPanel, { team: { ...fx.team, assistants: [], invites: [] } }))
    expect(html).toContain("No assistants yet.")
  })
})

describe("RoleDialog", () => {
  it("shows the presets, the toggles and the billing rule", () => {
    const html = renderStatic(h(RoleDialog, { open: true, onClose: () => undefined, assistant: fx.assistant }))
    expect(html).toContain("Co-teacher")
    expect(html).toContain("Everything except billing and seats.")
    expect(html).toContain("Billing, plans and seats always stay with you.")
    expect(html.match(/role="switch"/g)?.length).toBe(7)
  })
})

describe("InviteDialog", () => {
  it("shows a created code once with its expiry and a copy control", () => {
    m.invite = fakeMutation({ isSuccess: true, data: fx.team.invites[0] })
    const html = renderStatic(h(InviteDialog, { open: true, onClose: () => undefined }))
    expect(html).toContain("AST-7KQ2")
    expect(html).toContain("Copy code")
  })
})

describe("RemoveAssistantDialog", () => {
  it("states that access ends straight away", () => {
    const html = renderStatic(h(RemoveAssistantDialog, { open: true, onClose: () => undefined, assistant: fx.assistant }))
    expect(html).toContain("loses access to your classes straight away")
  })
})

describe("JoinTeamCard", () => {
  it("confirms a joined team and maps an invalid code", () => {
    m.join = fakeMutation({ isSuccess: true, data: { teacherName: "Ms Nour", role: "marker" } })
    expect(renderStatic(h(JoinTeamCard))).toMatch(/role="status"[^>]*>.*Ms Nour/)
    m.join = fakeMutation({ isError: true, error: new ApiError(404, "x") })
    expect(renderStatic(h(JoinTeamCard))).toContain("That code isn")
  })
})
```

- [ ] **Step 2: Run them to verify they fail**

Run: `npx vitest run tests/unit/assistantRoles.test.ts tests/unit/teamAssistants.test.ts`
Expected: FAIL, "Failed to resolve import "@/lib/assistantRoles"".

- [ ] **Step 3: Write `web/src/lib/assistantRoles.ts`**

```ts
import { TEAM_PERMISSIONS, type AssistantRole, type TeamPermission } from "@/lib/billingTypes"

/* Assistant role presets and per-permission toggles (spec §2.3). Billing and seats are never
 * permissions; the server enforces that, and the UI says it. */

export const ROLE_COPY: Record<AssistantRole, { label: string; description: string }> = {
  co_teacher: { label: "Co-teacher", description: "Everything except billing and seats." },
  marker: { label: "Marker", description: "Mark and regrade, and see the results they mark." },
  viewer: { label: "Viewer", description: "Read only." },
}

export const PERMISSION_COPY: Record<TeamPermission, string> = {
  mark: "Mark papers",
  regrade: "Regrade papers",
  generate_quiz: "Generate quizzes",
  manage_classes: "Manage classes",
  view_results: "See results",
  manage_students: "Manage students",
  view_usage: "See usage",
}

/** Frontend mirror of plan 03 `PRESET_PERMISSIONS` (no API serves it; update it with 03). */
export const PRESET_PERMISSIONS: Record<AssistantRole, TeamPermission[]> = {
  co_teacher: [...TEAM_PERMISSIONS],
  marker: ["mark", "regrade", "view_results"],
  viewer: ["view_results", "view_usage"],
}

export function effectivePermissions(
  preset: AssistantRole,
  overrides: Partial<Record<TeamPermission, boolean>>,
): TeamPermission[] {
  const base = new Set(PRESET_PERMISSIONS[preset])
  return TEAM_PERMISSIONS.filter((p) => overrides[p] ?? base.has(p))
}

export function overridesFor(preset: AssistantRole, selected: TeamPermission[]): Partial<Record<TeamPermission, boolean>> {
  const base = new Set(PRESET_PERMISSIONS[preset])
  const chosen = new Set(selected)
  const out: Partial<Record<TeamPermission, boolean>> = {}
  for (const p of TEAM_PERMISSIONS) {
    if (base.has(p) !== chosen.has(p)) out[p] = chosen.has(p)
  }
  return out
}
```

- [ ] **Step 4: Write `AssistantDialogs.tsx`**

`web/src/portals/teacher/screens/team/AssistantDialogs.tsx`:

```tsx
import { useState, type ReactNode } from "react"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Modal } from "@/components/ui/modal"
import { Select } from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"
import { PERMISSION_COPY, PRESET_PERMISSIONS, ROLE_COPY, effectivePermissions, overridesFor } from "@/lib/assistantRoles"
import { formatBillingDate } from "@/lib/billingFormat"
import { billingFailureMessage } from "@/lib/billingOutcome"
import { TEAM_PERMISSIONS, type AssistantRole, type AssistantRow, type CapPeriod, type TeamPermission } from "@/lib/billingTypes"
import { useCreateAssistantInvite, useRemoveAssistant, useSetAssistantRole, useSetMemberCap } from "@/lib/hooks/useTeamApi"

/* Dialogs for the assistants panel (spec §2.3). */

const ROLES: AssistantRole[] = ["co_teacher", "marker", "viewer"]

function Footer({ onClose, done, primary }: { onClose: () => void; done: boolean; primary: ReactNode }) {
  return (
    <div className="flex justify-end gap-2">
      <Button variant="ghost" onClick={onClose}>{done ? "Close" : "Cancel"}</Button>
      {done ? null : primary}
    </div>
  )
}

export function RoleDialog({
  open,
  onClose,
  assistant,
}: {
  open: boolean
  onClose: () => void
  assistant: AssistantRow
}) {
  const save = useSetAssistantRole()
  const [preset, setPreset] = useState<AssistantRole>(assistant.rolePreset)
  const [selected, setSelected] = useState<TeamPermission[]>(() => effectivePermissions(assistant.rolePreset, assistant.overrides))
  return (
    <Modal
      open={open}
      onClose={onClose}
      title={`Role for ${assistant.name}`}
      footer={
        <Footer
          onClose={onClose}
          done={false}
          primary={
            <Button
              variant="primary"
              loading={save.isPending}
              onClick={() =>
                save.mutate(
                  { memberId: assistant.memberId, body: { rolePreset: preset, overrides: overridesFor(preset, selected) } },
                  { onSuccess: onClose },
                )
              }
            >
              Save role
            </Button>
          }
        />
      }
    >
      <div className="flex flex-col gap-4">
        <fieldset className="m-0 flex flex-col gap-2 border-0 p-0">
          <legend className="mb-2 text-label text-on-surface">Role</legend>
          {ROLES.map((r) => (
            <label key={r} className="flex items-start gap-3 rounded-row p-2 hover:bg-surface-container-low pointer-coarse:min-h-11">
              <input
                type="radio"
                name="rolePreset"
                value={r}
                checked={preset === r}
                onChange={() => {
                  setPreset(r)
                  setSelected([...PRESET_PERMISSIONS[r]])
                }}
                className="mt-1"
              />
              <span className="flex flex-col">
                <span className="text-body-md font-semibold text-on-surface">{ROLE_COPY[r].label}</span>
                <span className="text-body-sm text-on-surface-variant">{ROLE_COPY[r].description}</span>
              </span>
            </label>
          ))}
        </fieldset>
        <fieldset className="m-0 flex flex-col gap-2 border-0 p-0">
          <legend className="mb-2 text-label text-on-surface">Permissions</legend>
          {TEAM_PERMISSIONS.map((p) => (
            <Switch
              key={p}
              layout="row"
              label={PERMISSION_COPY[p]}
              checked={selected.includes(p)}
              onCheckedChange={(on) => setSelected((l) => (on ? [...new Set([...l, p])] : l.filter((x) => x !== p)))}
            />
          ))}
        </fieldset>
        <p className="m-0 text-body-sm text-on-surface-variant">Billing, plans and seats always stay with you.</p>
        {save.isError ? <p role="alert" className="m-0 text-body-sm text-error">{billingFailureMessage(save.error, "save this role")}</p> : null}
      </div>
    </Modal>
  )
}

export function AssistantCapDialog({ open, onClose, assistant }: { open: boolean; onClose: () => void; assistant: AssistantRow }) {
  const cap = useSetMemberCap()
  const [limited, setLimited] = useState(assistant.capUnits !== null)
  const [units, setUnits] = useState(String(assistant.capUnits ?? 1000))
  const [period, setPeriod] = useState<CapPeriod>(assistant.capPeriod)
  return (
    <Modal
      open={open}
      onClose={onClose}
      size="sm"
      title={`Spending cap for ${assistant.name}`}
      footer={
        <Footer
          onClose={onClose}
          done={false}
          primary={
            <Button
              variant="primary"
              loading={cap.isPending}
              onClick={() =>
                cap.mutate(
                  { memberId: assistant.memberId, body: { capUnits: limited ? Math.max(1, Math.floor(Number(units) || 1)) : null, capPeriod: period } },
                  { onSuccess: onClose },
                )
              }
            >
              Save cap
            </Button>
          }
        />
      }
    >
      <div className="flex flex-col gap-3">
        <p className="m-0 text-body-sm text-on-surface-variant">Their work uses your plan allowance first, then your credits.</p>
        <Checkbox label="Limit how much they can use" checked={limited} onChange={(e) => setLimited(e.target.checked)} />
        {limited ? (
          <div className="grid gap-3 md:grid-cols-2">
            <Input label="Up to (credits)" type="number" inputMode="numeric" min={1} value={units} onChange={(e) => setUnits(e.target.value)} />
            <Select label="Limit resets" value={period} onChange={(e) => setPeriod(e.target.value === "total" ? "total" : "month")}>
              <option value="month">Every month</option>
              <option value="total">Never (total)</option>
            </Select>
          </div>
        ) : null}
        {cap.isError ? <p role="alert" className="m-0 text-body-sm text-error">{billingFailureMessage(cap.error, "save this cap")}</p> : null}
      </div>
    </Modal>
  )
}

export function RemoveAssistantDialog({ open, onClose, assistant }: { open: boolean; onClose: () => void; assistant: AssistantRow }) {
  const remove = useRemoveAssistant()
  return (
    <Modal
      open={open}
      onClose={onClose}
      size="sm"
      title={`Remove ${assistant.name}`}
      footer={
        <Footer
          onClose={onClose}
          done={false}
          primary={
            <Button variant="primary" loading={remove.isPending} onClick={() => remove.mutate(assistant.memberId, { onSuccess: onClose })}>
              Remove assistant
            </Button>
          }
        />
      }
    >
      <p className="m-0 text-body-md text-on-surface">{assistant.name} loses access to your classes straight away.</p>
      {remove.isError ? <p role="alert" className="m-0 mt-2 text-body-sm text-error">{billingFailureMessage(remove.error, "remove this assistant")}</p> : null}
    </Modal>
  )
}

export function InviteDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const invite = useCreateAssistantInvite()
  const [role, setRole] = useState<AssistantRole>("marker")
  const [days, setDays] = useState("7")
  const [copied, setCopied] = useState(false)
  const created = invite.isSuccess ? invite.data : undefined
  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Invite an assistant"
      footer={
        <Footer
          onClose={onClose}
          done={created !== undefined}
          primary={
            <Button variant="primary" loading={invite.isPending} onClick={() => invite.mutate({ role, expiresInDays: Number(days) })}>
              Create invite code
            </Button>
          }
        />
      }
    >
      {created ? (
        <div role="status" className="flex flex-col gap-2">
          <p className="m-0 text-body-md text-on-surface">
            Send this code to your assistant. It works once, until {formatBillingDate(created.expiresAt)}.
          </p>
          <p className="m-0 text-data-lg text-on-surface">{created.code}</p>
          <Button
            variant="secondary"
            className="self-start"
            onClick={() => void navigator.clipboard.writeText(created.code).then(() => setCopied(true))}
          >
            {copied ? "Copied" : "Copy code"}
          </Button>
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          <Select label="Role" value={role} onChange={(e) => setRole(e.target.value as AssistantRole)}>
            {ROLES.map((r) => (
              <option key={r} value={r}>{ROLE_COPY[r].label}: {ROLE_COPY[r].description}</option>
            ))}
          </Select>
          <Select label="Code expires after" value={days} onChange={(e) => setDays(e.target.value)}>
            <option value="1">1 day</option>
            <option value="7">7 days</option>
            <option value="14">14 days</option>
          </Select>
          <p className="m-0 text-body-sm text-on-surface-variant">Assistants are free. They need their own Lemely teacher account.</p>
          {invite.isError ? <p role="alert" className="m-0 text-body-sm text-error">{billingFailureMessage(invite.error, "create the invite")}</p> : null}
        </div>
      )}
    </Modal>
  )
}
```

- [ ] **Step 5: Write `AssistantsPanel.tsx` and `JoinTeamCard.tsx`**

`web/src/portals/teacher/screens/team/AssistantsPanel.tsx`:

```tsx
import { useState } from "react"
import { Button } from "@/components/ui/button"
import { PERMISSION_COPY, ROLE_COPY } from "@/lib/assistantRoles"
import { formatBillingDate } from "@/lib/billingFormat"
import { billingFailureMessage } from "@/lib/billingOutcome"
import type { AssistantRow, TeamView } from "@/lib/billingTypes"
import { useRevokeAssistantInvite } from "@/lib/hooks/useTeamApi"
import { assistantCapText } from "@/lib/teamModel"
import { AssistantCapDialog, InviteDialog, RemoveAssistantDialog, RoleDialog } from "./AssistantDialogs"

/* Assistants and pending invites (spec §2.3). */

type Open = { kind: "role" | "cap" | "remove"; row: AssistantRow } | { kind: "invite" } | null

export function AssistantsPanel({ team }: { team: TeamView }) {
  const revoke = useRevokeAssistantInvite()
  const [open, setOpen] = useState<Open>(null)
  const close = () => setOpen(null)
  return (
    <section aria-labelledby="assistants-heading" className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 id="assistants-heading" className="m-0 text-display-sm text-on-surface">Assistants</h2>
        <Button variant="primary" onClick={() => setOpen({ kind: "invite" })}>Invite an assistant</Button>
      </div>
      {team.assistants.length === 0 && team.invites.length === 0 ? (
        <p className="m-0 text-body-md text-on-surface-variant">No assistants yet. Invite a colleague with their own Lemely teacher account.</p>
      ) : null}
      <ul className="m-0 flex list-none flex-col gap-3 p-0">
        {team.assistants.map((a) => (
          <li key={a.memberId} className="flex flex-col gap-2 rounded-lg border border-outline-variant bg-surface-container-lowest p-4">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <span className="text-body-md font-semibold text-on-surface">{a.name}</span>
            </div>
            <p className="m-0 text-body-sm text-on-surface">
              {ROLE_COPY[a.rolePreset].label} · {a.permissions.map((p) => PERMISSION_COPY[p]).join(", ") || "No permissions"}
            </p>
            <p className="m-0 text-body-sm text-on-surface-variant">{assistantCapText(a)}</p>
            <div className="flex flex-wrap gap-1">
              <Button size="sm" variant="ghost" onClick={() => setOpen({ kind: "role", row: a })}>Edit role</Button>
              <Button size="sm" variant="ghost" onClick={() => setOpen({ kind: "cap", row: a })}>Set cap</Button>
              <Button size="sm" variant="ghost" onClick={() => setOpen({ kind: "remove", row: a })} aria-label={`Remove ${a.name}`}>Remove</Button>
            </div>
          </li>
        ))}
      </ul>
      {team.invites.length > 0 ? (
        <div className="flex flex-col gap-2">
          <h3 className="m-0 text-label text-on-surface">Pending invites</h3>
          <ul className="m-0 flex list-none flex-col gap-2 p-0">
            {team.invites.map((inv) => (
              <li key={inv.inviteId} className="flex flex-wrap items-center justify-between gap-2 rounded-row bg-surface-container-low px-3 py-2">
                <span className="text-data-sm text-on-surface">{inv.code}</span>
                <span className="text-body-sm text-on-surface-variant">
                  {ROLE_COPY[inv.role].label} · expires {formatBillingDate(inv.expiresAt)}
                </span>
                <Button size="sm" variant="ghost" loading={revoke.isPending && revoke.variables === inv.inviteId} onClick={() => revoke.mutate(inv.inviteId)}>
                  Revoke
                </Button>
              </li>
            ))}
          </ul>
          {revoke.isError ? <p role="alert" className="m-0 text-body-sm text-error">{billingFailureMessage(revoke.error, "revoke the invite")}</p> : null}
        </div>
      ) : null}
      {open?.kind === "invite" ? <InviteDialog open onClose={close} /> : null}
      {open?.kind === "role" ? <RoleDialog key={open.row.memberId} open onClose={close} assistant={open.row} /> : null}
      {open?.kind === "cap" ? <AssistantCapDialog key={open.row.memberId} open onClose={close} assistant={open.row} /> : null}
      {open?.kind === "remove" ? <RemoveAssistantDialog open onClose={close} assistant={open.row} /> : null}
    </section>
  )
}
```

`web/src/portals/teacher/screens/team/JoinTeamCard.tsx`:

```tsx
import { useState } from "react"
import { ApiError } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Card, CardBody } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { ROLE_COPY } from "@/lib/assistantRoles"
import { useJoinTeam } from "@/lib/hooks/useTeamApi"

/* Redeeming an assistant invite with your own teacher account (spec §2.3, §4.4). */

export function JoinTeamCard() {
  const join = useJoinTeam()
  const [code, setCode] = useState("")
  const error = join.isError
    ? join.error instanceof ApiError && join.error.status === 404
      ? "That code isn't valid or has expired. Ask for a new one."
      : "Couldn't join that team. Check the code and try again."
    : null
  return (
    <Card>
      <CardBody className="flex flex-col gap-3">
        <h2 className="m-0 text-display-xs text-on-surface">Join a team</h2>
        {join.isSuccess && join.data ? (
          <p role="status" className="m-0 text-body-md text-on-surface">
            You're now on {join.data.teacherName}'s team as {ROLE_COPY[join.data.role].label.toLowerCase()}.
          </p>
        ) : (
          <form
            className="flex flex-wrap items-end gap-3"
            onSubmit={(e) => {
              e.preventDefault()
              if (code.trim()) join.mutate(code.trim())
            }}
          >
            <div className="min-w-48 flex-1">
              <Input
                label="Assistant code"
                hint="Joining someone else's team? Enter the assistant code they sent you."
                value={code}
                onChange={(e) => setCode(e.target.value)}
                autoComplete="off"
                error={error ?? undefined}
              />
            </div>
            <Button type="submit" variant="secondary" loading={join.isPending}>Join team</Button>
          </form>
        )}
      </CardBody>
    </Card>
  )
}
```

- [ ] **Step 6: Add the assistants panel and join card to `Team.tsx`**

In `Team.tsx`, import `AssistantsPanel` and `JoinTeamCard`; change the `QueryState` child to

```tsx
        {(t) => (
          <>
            <SeatsPanel team={t} />
            <AssistantsPanel team={t} />
          </>
        )}
```

and render `<JoinTeamCard />` after the `QueryState` (outside it, so an assistant who gets 403
can still join a team).

- [ ] **Step 7: Run the tests to verify they pass**

Run: `npx vitest run tests/unit/assistantRoles.test.ts tests/unit/teamAssistants.test.ts tests/unit/teamSeats.test.ts`
Expected: PASS. (`teamSeats.test.ts`'s `Team` render still passes: its mocks return idle
mutations for the hooks the new panels call; add `useCreateAssistantInvite`,
`useRevokeAssistantInvite`, `useSetAssistantRole`, `useRemoveAssistant`, `useJoinTeam` to that
file's `vi.mock("@/lib/hooks/useTeamApi")` factory, each returning `fakeMutation()`.)

- [ ] **Step 8: Run the frontend gate**

```bash
npm run typecheck
npx vitest run tests/unit/assistantRoles.test.ts tests/unit/teamAssistants.test.ts tests/unit/teamSeats.test.ts $SCAN
npm run lint && npm run check:copy && npm run build
```
Expected: all exit 0.

- [ ] **Step 9: Commit**

```bash
cd /home/sico/Code/Lemely/.claude/worktrees/paymob-integration
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files && graphify update .
P="web/src/lib/assistantRoles.ts web/src/portals/teacher/screens/team/AssistantsPanel.tsx web/src/portals/teacher/screens/team/AssistantDialogs.tsx web/src/portals/teacher/screens/team/JoinTeamCard.tsx web/src/portals/teacher/screens/team/Team.tsx web/tests/unit/assistantRoles.test.ts web/tests/unit/teamAssistants.test.ts web/tests/unit/teamSeats.test.ts"
git add $P
git commit -S -m "feat(web): teacher assistants with roles, caps and invites" -- $P
```

---

### Task 13: Admin billing shell and catalogue

**Files:**
- Modify: `web/src/lib/billingTypes.ts`, `web/src/lib/billingAdapters.ts`,
  `web/tests/unit/support/billingFixtures.ts` (admin types, catalogue adapter, fixtures)
- Create: `web/src/lib/hooks/useAdminBillingApi.ts`
- Create: `web/src/lib/adminBillingModel.ts`
- Create: `web/src/portals/admin/screens/billing/BillingLayout.tsx`
- Create: `web/src/portals/admin/screens/billing/ReasonedFormDialog.tsx`
- Create: `web/src/portals/admin/screens/billing/Catalogue.tsx`
- Modify: `web/src/portals/admin/index.tsx` (route subtree `billing`, `NAV_ICON.billing`)
- Modify: `web/src/portals/admin/data.ts` (nav entry, icon union, trail)
- Test: `web/tests/unit/adminBillingApi.test.ts`, `web/tests/unit/adminBillingModel.test.ts`,
  `web/tests/unit/adminCatalogue.test.ts`

**Interfaces:**
- Consumes (Task 1): `formatMoney`, `formatBillingDate`, `billingFailureMessage`, `request`,
  `featureLines`, types `Audience`, `BillingInterval`, `MeteredAction`, `PaymentStatus`,
  `PaymentPurpose`, `SubscriptionStatus`.
- Produces:
  - admin wire DTOs and view types in `billingTypes.ts` (Step 3a) and `toAdminCatalogue` in
    `billingAdapters.ts`;
  - `adminBillingApi`, `adminBillingKeys` and hooks `useAdminCatalogue`, `useCreateTier`,
    `useUpdateTier`, `useSyncTier`, `useCreatePack`, `useUpdatePack`, `useCreateRate`,
    `useCreateEstimator`, `useUpdateFreeAllowances`, `useCustomerSearch(q)`,
    `useCustomer(userId)`, `useGrantCredits`, `useAdjustBalance`, `useForgiveDebt`,
    `useManualActivation`, `useExtendSubscription`, `useAdminCancelSubscription`,
    `useRefundPayment`, `useVoidPayment`, `useReconcilePayment`, `useAdminPayments(status)`,
    `useProblemQueue`, `useMarginReport(from, to)`, `useBillingHealth` (mutation variables are
    `{ id, body }` where an id is in the path);
  - `reasonError(reason)`, `minorFromMajor(text)`, `majorFromMinor(minor)`, `FieldSpec`,
    `FormValues`, `validateFields(fields, values)`, `TIER_FIELDS`, `TIER_UPDATE_FIELDS`,
    `tierValues(tier)`, `tierBody(values, reason)`, `tierUpdateBody(values, reason)`,
    `PACK_FIELDS`, `PACK_UPDATE_FIELDS`, `packValues`, `packBody`, `packUpdateBody`,
    `RATE_FIELDS`, `rateBody`, `ESTIMATOR_FIELDS`, `estimatorBody`, `FREE_FIELDS`, `freeValues`,
    `freeBody`, `freeFormBody`, `isoDay(date)` from `adminBillingModel.ts`;
  - `<ReasonedFormDialog open onClose title fields initial submitLabel mutation toBody
    note? />` (also used by Tasks 14 and 15);
  - `BillingLayout` with exported `BILLING_AREAS` (later tasks append their area), screen
    `Catalogue`.

Behaviour (spec §8.1, §4.1; plan 07 catalogue routes A28–A31): one "Billing" entry in the
platform sidebar opens `/platform/billing` with a pill nav of its areas. Catalogue shows plan
tiers (with their hidden allowance units, seats, seat allowance, extra-seat price, active flag,
Paymob plan id and a drift warning from `paymobDrift` with a "Sync to Paymob" action), credit
packs, usage rates and estimators by version, and the free allowances (the inactive
`signup_student` / `signup_teacher` packs, index R11). Rates and estimators are versioned: "New
version" creates a row, never edits one. Editing a tier or pack sends **every editable field**
(`PlanTierUpdateDTO`, `CreditPackUpdateDTO` require them all); code, audience, interval and
currency are fixed after creation. **Every write requires a reason** (≥ 5 characters, "It is
saved in the audit log."), and the server writes `admin_audit_log` in the same transaction.
Money is entered in EGP and sent as piasters. Catalogue writes return the single row, so the
hooks refetch the catalogue. No `fallback` on any request (`useAdminApi.ts` rule).

- [ ] **Step 0: Match the merged admin routes exactly**

Open the merged `lemely/web/routers/admin_billing.py` and `lemely/web/schemas_admin_billing.py`
(or plan 07's router tasks). Copy every field of the models in rows A28–A38 into the admin wire
types of Step 3a; keep view and hook names; record differences in the commit body.

- [ ] **Step 1: Write the failing fetcher and model tests**

`web/tests/unit/adminBillingApi.test.ts`:

```ts
import { beforeEach, describe, expect, it, vi } from "vitest"

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  request: vi.fn(),
}))

import { request } from "@/lib/api"
import { toAdminCatalogue } from "@/lib/billingAdapters"
import { adminBillingApi as api } from "@/lib/hooks/useAdminBillingApi"

const req = vi.mocked(request)
beforeEach(() => {
  req.mockReset()
  req.mockResolvedValue({})
})

const r = { reason: "because" }

describe("admin billing fetchers (plan 07; request() adds /api)", () => {
  it("hits every admin billing route with the right method", async () => {
    await api.catalogue()
    await api.createTier({ ...r } as never)
    await api.updateTier("t1", { ...r } as never)
    await api.syncTier("t1", r)
    await api.createPack({ ...r } as never)
    await api.updatePack("p1", { ...r } as never)
    await api.createRate({ ...r } as never)
    await api.createEstimator({ ...r } as never)
    await api.updateFreeAllowance({ audience: "student", units: 300, ...r })
    await api.searchCustomers("omar h")
    await api.customer("u1")
    await api.grant("u1", { units: 5, validDays: null, requestId: "rq1", ...r })
    await api.adjust("u1", { units: -5, requestId: "rq2", ...r })
    await api.forgiveDebt("u1", { units: null, ...r })
    await api.manualActivation("u1", { planTierId: "t1", periodDays: 30, ...r })
    await api.extend("s1", { days: 7, ...r })
    await api.cancelSubscription("s1", { when: "period_end", ...r })
    await api.refund("p1", { amountMinor: 100, ...r })
    await api.voidPayment("p1", r)
    await api.reconcile("p1", r)
    await api.payments("pending", "c 2")
    await api.problems()
    await api.margin("2026-10-01", "2026-11-30")
    await api.health()
    expect(req.mock.calls.map((c) => [c[0], (c[1] as RequestInit | undefined)?.method ?? "GET"])).toEqual([
      ["/admin/billing/catalogue", "GET"],
      ["/admin/billing/tiers", "POST"],
      ["/admin/billing/tiers/t1", "PUT"],
      ["/admin/billing/tiers/t1/sync", "POST"],
      ["/admin/billing/packs", "POST"],
      ["/admin/billing/packs/p1", "PUT"],
      ["/admin/billing/rates", "POST"],
      ["/admin/billing/estimators", "POST"],
      ["/admin/billing/free-allowances", "PUT"],
      ["/admin/billing/customers?q=omar%20h", "GET"],
      ["/admin/billing/customers/u1", "GET"],
      ["/admin/billing/customers/u1/grant", "POST"],
      ["/admin/billing/customers/u1/adjust", "POST"],
      ["/admin/billing/customers/u1/forgive-debt", "POST"],
      ["/admin/billing/customers/u1/manual-activation", "POST"],
      ["/admin/billing/subscriptions/s1/extend", "POST"],
      ["/admin/billing/subscriptions/s1/cancel", "POST"],
      ["/admin/billing/payments/p1/refund", "POST"],
      ["/admin/billing/payments/p1/void", "POST"],
      ["/admin/billing/payments/p1/reconcile", "POST"],
      ["/admin/billing/payments?status=pending&cursor=c+2", "GET"],
      ["/admin/billing/problems", "GET"],
      ["/admin/billing/margin?from=2026-10-01T00%3A00%3A00Z&to=2026-11-30T23%3A59%3A59Z", "GET"],
      ["/admin/billing/health", "GET"],
    ])
  })

  it("lists all payments when no status filter is set", async () => {
    await api.payments(null, null)
    expect(req.mock.calls[0][0]).toBe("/admin/billing/payments")
  })
})

describe("toAdminCatalogue", () => {
  it("maps intervals and features, nulls student seat fields, names drift and folds free allowances", () => {
    const c = toAdminCatalogue({
      planTiers: [
        { id: "t1", code: "s_m", name: "Student Plus", audience: "student", interval: "monthly", priceMinor: 25000, currency: "EGP", allowanceUnits: 4000, includedSeats: 0, seatAllowanceUnits: 0, extraSeatPriceMinor: 0, features: { "Mark past papers": true }, isActive: true, paymobPlanId: 77, paymobDrift: "in_sync" },
        { id: "t2", code: "t_m", name: "Teacher Pro", audience: "teacher", interval: "yearly", priceMinor: 900000, currency: "EGP", allowanceUnits: 9000, includedSeats: 20, seatAllowanceUnits: 300, extraSeatPriceMinor: 3000, features: {}, isActive: true, paymobPlanId: null, paymobDrift: "not_synced" },
      ],
      creditPacks: [],
      freeAllowances: [
        { audience: "student", creditPackId: "fs", units: 300, validDays: null },
        { audience: "teacher", creditPackId: "ft", units: 1000, validDays: 30 },
      ],
      usageRates: [],
      usageEstimators: [],
    })
    expect(c.tiers[0]).toMatchObject({ interval: "month", features: ["Mark past papers"], includedSeats: null, seatAllowanceUnits: null, extraSeatPriceMinor: null, drift: null })
    expect(c.tiers[1]).toMatchObject({ interval: "year", includedSeats: 20, seatAllowanceUnits: 300, extraSeatPriceMinor: 3000, drift: "Not synced to Paymob yet" })
    expect(c.freeAllowances).toEqual({ studentSignupUnits: 300, teacherSignupUnits: 1000, teacherSignupExpiryDays: 30 })
  })
})
```

`web/tests/unit/adminBillingModel.test.ts`:

```ts
import { describe, expect, it } from "vitest"
import {
  PACK_FIELDS,
  TIER_FIELDS,
  estimatorBody,
  freeBody,
  isoDay,
  majorFromMinor,
  minorFromMajor,
  packBody,
  packUpdateBody,
  rateBody,
  reasonError,
  tierBody,
  tierUpdateBody,
  tierValues,
  validateFields,
} from "@/lib/adminBillingModel"
import { fx } from "./support/billingFixtures"

describe("admin billing model", () => {
  it("requires a real reason", () => {
    expect(reasonError("")).toBe("Give a reason of at least 5 characters. It is saved in the audit log.")
    expect(reasonError("  ok  ")).not.toBeNull()
    expect(reasonError("refund for duplicate charge")).toBeNull()
  })

  it("converts EGP to piasters and back, and dates to ISO datetimes", () => {
    expect(minorFromMajor("250")).toBe(25000)
    expect(minorFromMajor("250.5")).toBe(25050)
    expect(minorFromMajor("-1")).toBeNull()
    expect(minorFromMajor("abc")).toBeNull()
    expect(majorFromMinor(25050)).toBe("250.50")
    expect(isoDay("2026-12-01")).toBe("2026-12-01T00:00:00Z")
  })

  it("builds plan 07's create body and its full update body from the form", () => {
    const tier = fx.adminCatalogue.tiers[0]
    const v = tierValues(tier)
    expect(tierBody(v, "price check")).toEqual({
      code: tier.code,
      name: tier.name,
      audience: "student",
      interval: "monthly",
      priceMinor: tier.priceMinor,
      currency: "EGP",
      allowanceUnits: tier.allowanceUnits,
      includedSeats: 0,
      seatAllowanceUnits: 0,
      extraSeatPriceMinor: 0,
      features: { "Mark past papers": true, "Study plans": true },
      isActive: true,
      reason: "price check",
    })
    expect(tierUpdateBody(v, "price check")).toEqual({
      name: tier.name,
      priceMinor: tier.priceMinor,
      allowanceUnits: tier.allowanceUnits,
      includedSeats: 0,
      seatAllowanceUnits: 0,
      extraSeatPriceMinor: 0,
      features: { "Mark past papers": true, "Study plans": true },
      isActive: true,
      reason: "price check",
    })
  })

  it("validates required text and non-negative numbers", () => {
    const values = { ...tierValues(null), code: "", priceMajor: "-3" }
    const errors = validateFields(TIER_FIELDS, values)
    expect(errors).toContain("Code is required.")
    expect(errors).toContain("Price (EGP) must be zero or more.")
    expect(validateFields(PACK_FIELDS, { code: "p", name: "P", units: "500", priceMajor: "150", isActive: true })).toEqual([])
  })

  it("builds pack, rate, estimator and free-allowance bodies", () => {
    const pack = { code: "p", name: "P", units: "500", priceMajor: "150", isActive: true }
    expect(packBody(pack, "new pack")).toEqual({ code: "p", name: "P", units: 500, priceMinor: 15000, currency: "EGP", isActive: true, reason: "new pack" })
    expect(packUpdateBody(pack, "edit pack")).toEqual({ name: "P", units: 500, priceMinor: 15000, isActive: true, reason: "edit pack" })
    expect(rateBody({ action: "regrade", unitsPerUsd: "1200", effectiveFrom: "2026-12-01" }, "rate")).toEqual({
      action: "regrade", unitsPerUsd: 1200, effectiveFrom: "2026-12-01T00:00:00Z", reason: "rate",
    })
    expect(rateBody({ action: "regrade", unitsPerUsd: "1200", effectiveFrom: "" }, "rate").effectiveFrom).toBeNull()
    expect(
      estimatorBody({ action: "mark_paper", inputKind: "none", baseLow: "2", baseHigh: "4", perInputLow: "0", perInputHigh: "0", effectiveFrom: "" }, "tune"),
    ).toMatchObject({ inputKind: "none", baseLow: 2, baseHigh: 4, effectiveFrom: null })
    expect(freeBody({ studentSignupUnits: "300", teacherSignupUnits: "1000" }, "free")).toEqual([
      { audience: "student", units: 300, reason: "free" },
      { audience: "teacher", units: 1000, reason: "free" },
    ])
  })
})
```

- [ ] **Step 2: Run them to verify they fail**

Run: `npx vitest run tests/unit/adminBillingApi.test.ts tests/unit/adminBillingModel.test.ts`
Expected: FAIL, "Failed to resolve import "@/lib/hooks/useAdminBillingApi"".

- [ ] **Step 3a: Add the admin types to `web/src/lib/billingTypes.ts` and the catalogue adapter**

Append to `billingTypes.ts`:

```ts
// ── Admin billing (plan 07) ─────────────────────────────────────────────────

export type PaymobDrift = "in_sync" | "not_synced" | "unverified" | "drifted"
export type EstimatorInputKind = "pages" | "marks" | "questions" | "none"

/** 07 `PlanTierDTO` (admin). */
export interface WireAdminPlanTier {
  id: string
  code: string
  name: string
  audience: string
  interval: "monthly" | "yearly" | null
  priceMinor: number
  currency: string
  allowanceUnits: number
  includedSeats: number
  seatAllowanceUnits: number
  extraSeatPriceMinor: number
  features: Record<string, unknown>
  isActive: boolean
  paymobPlanId: number | null
  paymobDrift: PaymobDrift
}

/** 07 `CreditPackDTO` (admin). */
export interface AdminCreditPack {
  id: string
  code: string
  name: string
  units: number
  priceMinor: number
  currency: string
  isActive: boolean
}

/** 07 `FreeAllowanceDTO` (the inactive signup packs, index R11). */
export interface WireFreeAllowance {
  audience: "student" | "teacher"
  creditPackId: string
  units: number
  validDays: number | null
}

/** 07 `UsageRateDTO`. */
export interface UsageRateRow {
  id: string
  version: number
  action: MeteredAction
  unitsPerUsd: number
  effectiveFrom: string
}

/** 07 `UsageEstimatorDTO`. */
export interface EstimatorRow {
  id: string
  version: number
  action: MeteredAction
  inputKind: EstimatorInputKind
  baseLow: number
  baseHigh: number
  perInputLow: number
  perInputHigh: number
  effectiveFrom: string
}

/** 07 `AdminCatalogueDTO`. */
export interface WireAdminCatalogue {
  planTiers: WireAdminPlanTier[]
  creditPacks: AdminCreditPack[]
  freeAllowances: WireFreeAllowance[]
  usageRates: UsageRateRow[]
  usageEstimators: EstimatorRow[]
}

export interface Reasoned {
  reason: string
}

/** 07 `PlanTierCreateDTO`. */
export interface TierCreate extends Reasoned {
  code: string
  name: string
  audience: Audience
  interval: "monthly" | "yearly"
  priceMinor: number
  currency: "EGP"
  allowanceUnits: number
  includedSeats: number
  seatAllowanceUnits: number
  extraSeatPriceMinor: number
  features: Record<string, boolean>
  isActive: boolean
}

/** 07 `PlanTierUpdateDTO`: every editable field, all required. */
export interface TierUpdate extends Reasoned {
  name: string
  priceMinor: number
  allowanceUnits: number
  includedSeats: number
  seatAllowanceUnits: number
  extraSeatPriceMinor: number
  features: Record<string, boolean>
  isActive: boolean
}

/** 07 `CreditPackCreateDTO`. */
export interface PackCreate extends Reasoned {
  code: string
  name: string
  units: number
  priceMinor: number
  currency: "EGP"
  isActive: boolean
}

/** 07 `CreditPackUpdateDTO`: every editable field, all required. */
export interface PackUpdate extends Reasoned {
  name: string
  units: number
  priceMinor: number
  isActive: boolean
}

/** 07 `FreeAllowanceUpdateDTO` (one audience per request). */
export interface FreeAllowanceUpdate extends Reasoned {
  audience: "student" | "teacher"
  units: number
}

/** 07 `UsageRateVersionDTO`. */
export interface RateCreate extends Reasoned {
  action: MeteredAction
  unitsPerUsd: number
  effectiveFrom: string | null
}

/** 07 `UsageEstimatorVersionDTO`. */
export interface EstimatorCreate extends Reasoned {
  action: MeteredAction
  inputKind: EstimatorInputKind
  baseLow: number
  baseHigh: number
  perInputLow: number
  perInputHigh: number
  effectiveFrom: string | null
}

/** View: tier with student-only seat fields as `null`, feature lines and a drift sentence. */
export interface AdminPlanTier {
  id: string
  code: string
  name: string
  audience: Audience
  interval: BillingInterval | null
  priceMinor: number
  currency: string
  allowanceUnits: number
  includedSeats: number | null
  seatAllowanceUnits: number | null
  extraSeatPriceMinor: number | null
  features: string[]
  isActive: boolean
  paymobPlanId: number | null
  /** `null` when in sync with Paymob. */
  drift: string | null
}

export interface FreeAllowances {
  studentSignupUnits: number
  teacherSignupUnits: number
  /** Read-only: `FreeAllowanceUpdateDTO` carries no validity. */
  teacherSignupExpiryDays: number | null
}

export interface AdminCatalogue {
  tiers: AdminPlanTier[]
  packs: AdminCreditPack[]
  rates: UsageRateRow[]
  estimators: EstimatorRow[]
  freeAllowances: FreeAllowances
}

export interface FreeAllowancesUpdate extends Reasoned {
  studentSignupUnits: number
  teacherSignupUnits: number
}

// Customer view (07 `CustomerDetailDTO` and friends).

export interface CustomerHit {
  userId: string
  email: string
  displayName: string | null
  role: string
  matchedOn: "user_id" | "payment_id" | "paymob_order" | "email" | "name"
}

export interface CustomerSearchResult {
  hits: CustomerHit[]
}

export interface AdminRefund {
  id: string
  kind: "refund" | "void"
  status: "requested" | "succeeded" | "failed" | "unknown"
  amountMinor: number
  reason: string
  adminUserId: string
  clawedBackUnits: number
  createdAt: string
  updatedAt: string
}

export interface AdminPaymentRow {
  id: string
  payerUserId: string
  beneficiaryUserId: string
  purpose: PaymentPurpose
  status: PaymentStatus
  amountMinor: number
  currency: string
  refundedMinor: number
  paymobOrderId: string | null
  paymobTxnId: string | null
  planTierId: string | null
  creditPackId: string | null
  subscriptionId: string | null
  seatQuantity: number | null
  createdAt: string
  paidAt: string | null
  refunds: AdminRefund[]
}

export interface AdminSubscription {
  id: string
  planTierId: string
  planCode: string
  planName: string
  status: SubscriptionStatus
  payerUserId: string | null
  currentPeriodStart: string | null
  currentPeriodEnd: string | null
  cancelAtPeriodEnd: boolean
  pendingPlanTierId: string | null
  graceUntil: string | null
  extraSeats: number
  pendingExtraSeats: number | null
  paymobSubscriptionId: string | null
  isManuallyActivated: boolean
  periods: { periodStart: string; periodEnd: string; paymentId: string | null }[]
}

export interface AdminGrant {
  id: string
  kind: string
  visible: boolean
  units: number
  remaining: number
  held: number
  effectiveAt: string
  expiresAt: string | null
  teacherMemberId: string | null
  paymentId: string | null
}

export interface AdminDebt {
  id: string
  jobId: string | null
  units: number
  outstanding: number
  createdAt: string
}

export interface AdminUsageJob {
  jobId: string
  action: string
  status: string
  estimateLow: number
  estimateHigh: number
  estimatorVersion: number
  rateVersion: number
  reserved: number
  charged: number | null
  debtCreated: number | null
  /** Decimal string, e.g. "0.041230". */
  actualCostUsd: string | null
  actualUnits: number | null
  outsideRange: boolean
  createdAt: string
  settledAt: string | null
}

export interface AdminMember {
  memberId: string
  userId: string
  email: string
  kind: string
  status: string
  scopeSubjects: string[] | null
  scopeActions: string[] | null
  rolePreset: string | null
  capUnits: number | null
  capPeriod: string | null
  leavesAt: string | null
}

export interface LinkedUser {
  userId: string
  email: string
  displayName: string | null
}

export interface AuditEntry {
  id: string
  adminUserId: string
  action: string
  targetKind: string
  targetId: string
  reason: string
  before: Record<string, unknown> | null
  after: Record<string, unknown> | null
  createdAt: string
}

export interface CustomerDetail {
  user: { id: string; email: string; displayName: string | null; role: string; createdAt: string }
  balance: { allowanceAvailable: number; creditsAvailable: number; seatAvailable: number; outstandingDebt: number }
  subscriptions: AdminSubscription[]
  grants: AdminGrant[]
  debts: AdminDebt[]
  usageJobs: AdminUsageJob[]
  payments: AdminPaymentRow[]
  seats: AdminMember[]
  assistants: AdminMember[]
  seatedWith: AdminMember[]
  parents: LinkedUser[]
  children: LinkedUser[]
  audit: AuditEntry[]
}

/** 07 `AdminGrantRequestDTO` (`requestId` makes the grant idempotent). */
export interface AdminGrantRequest extends Reasoned {
  units: number
  /** `null` = never expires; backend default 365. */
  validDays: number | null
  requestId: string
}

/** 07 `AdminAdjustRequestDTO` (signed units). */
export interface AdminAdjustRequest extends Reasoned {
  units: number
  requestId: string
}

/** 07 `AdminForgiveRequestDTO` (`null` forgives all). */
export interface AdminForgiveRequest extends Reasoned {
  units: number | null
}

/** 07 `ManualActivationRequestDTO`. */
export interface ManualActivationRequest extends Reasoned {
  planTierId: string
  periodDays: number
}

/** 07 `AdminExtendRequestDTO`. */
export interface AdminExtendRequest extends Reasoned {
  days: number
}

/** 07 `AdminCancelRequestDTO`. */
export interface AdminCancelRequest extends Reasoned {
  when: "period_end" | "now"
}

/** 07 `AdminRefundRequestDTO` (`null` = the full refundable amount). */
export interface AdminRefundRequest extends Reasoned {
  amountMinor: number | null
}

export interface AdminPaymentsPage {
  items: AdminPaymentRow[]
  nextCursor: string | null
}

export interface WebhookFailure {
  id: string
  kind: "transaction" | "token" | "subscription"
  reason: string
  remoteAddr: string | null
  receivedAt: string
}

export interface ProblemQueue {
  mismatches: AdminPaymentRow[]
  stalePending: AdminPaymentRow[]
  missingCallbacks: AdminPaymentRow[]
  hmacFailures: WebhookFailure[]
  hmacFailures24h: number
  refundsNeedingAttention: AdminRefund[]
}

export interface MarginReport {
  windowStart: string
  windowEnd: string
  revenue: {
    recurringMinor: number
    packsMinor: number
    refundedMinor: number
    netMinor: number
    byPurpose: Record<string, number>
    byPlan: { key: string; minor: number }[]
  }
  cost: {
    totalUsd: string
    byAction: { key: string | null; jobs: number; costUsd: string }[]
    byPlan: { key: string | null; jobs: number; costUsd: string }[]
    byModel: { model: string; costUsd: string }[]
    unattributedModelUsd: string
  }
  egpPerUsd: string | null
  costMinor: number | null
  marginMinor: number | null
  accuracy: {
    action: string
    estimatorVersion: number
    jobs: number
    below: number
    above: number
    shareOutside: number
    meanOverrunUnits: number | null
    maxOverrunUnits: number | null
  }[]
  exposure: {
    outstandingDebtUnits: number
    debtors: number
    topDebtors: { userId: string; email: string; outstanding: number }[]
    usersAtLimit: number
    creditsExpiring30dUnits: number
    creditsExpiring30dOwners: number
    creditsExpiredUnusedUnits: number
    expiredJobs: { count: number; costUsd: string }
  }
}

export interface SweeperJobHealth {
  name: string
  neverRun: boolean
  lastStartedAt: string | null
  lastFinishedAt: string | null
  lastOutcome: "ok" | "failed" | null
  lastResultCount: number | null
  lastError: string | null
  lastSuccessAt: string | null
  consecutiveFailures: number
  totalRuns: number
  totalFailures: number
}

export interface BillingHealth {
  windowHours: number
  jobs: SweeperJobHealth[]
  verifiedEvents: number
  hmacFailures: number
  /** 0..1, `null` with no events in the window. */
  webhookErrorRate: number | null
  mismatches: number
  renewalFailureEvents: number
  pastDueNow: number
  failedAutoTopups: number
  failedExtraSeatCharges: number
}
```

Append to `billingAdapters.ts` (merge the type imports):

```ts
const DRIFT: Record<PaymobDrift, string | null> = {
  in_sync: null,
  not_synced: "Not synced to Paymob yet",
  unverified: "Paymob plan not checked",
  drifted: "Paymob plan differs from the catalogue",
}

export function toAdminCatalogue(w: WireAdminCatalogue): AdminCatalogue {
  const free = (a: "student" | "teacher") => w.freeAllowances.find((f) => f.audience === a)
  return {
    tiers: w.planTiers.map((t) => {
      const teacher = t.audience === "teacher"
      return {
        id: t.id,
        code: t.code,
        name: t.name,
        audience: teacher ? "teacher" : "student",
        interval: t.interval === "yearly" ? "year" : t.interval === "monthly" ? "month" : null,
        priceMinor: t.priceMinor,
        currency: t.currency,
        allowanceUnits: t.allowanceUnits,
        includedSeats: teacher ? t.includedSeats : null,
        seatAllowanceUnits: teacher ? t.seatAllowanceUnits : null,
        extraSeatPriceMinor: teacher ? t.extraSeatPriceMinor : null,
        features: featureLines(t.features),
        isActive: t.isActive,
        paymobPlanId: t.paymobPlanId,
        drift: DRIFT[t.paymobDrift],
      }
    }),
    packs: w.creditPacks,
    rates: w.usageRates,
    estimators: w.usageEstimators,
    freeAllowances: {
      studentSignupUnits: free("student")?.units ?? 0,
      teacherSignupUnits: free("teacher")?.units ?? 0,
      teacherSignupExpiryDays: free("teacher")?.validDays ?? null,
    },
  }
}
```

Append an `adminCatalogue` view fixture and a `customer` fixture to `billingFixtures.ts` (above
the `fx` literal, listed inside it):

```ts
import type { AdminCatalogue, AdminPaymentRow, BillingHealth, CustomerDetail, MarginReport, ProblemQueue } from "@/lib/billingTypes"

const adminCatalogue: AdminCatalogue = {
  tiers: [
    {
      id: "t-s-m", code: "student_plus_m", name: "Student Plus", audience: "student", interval: "month", priceMinor: 25000,
      currency: "EGP", allowanceUnits: 4000, includedSeats: null, seatAllowanceUnits: null, extraSeatPriceMinor: null,
      features: ["Mark past papers", "Study plans"], isActive: true, paymobPlanId: 77, drift: null,
    },
  ],
  packs: [{ id: "p1", code: "pack_500", name: "500 credits", units: 500, priceMinor: 15000, currency: "EGP", isActive: true }],
  rates: [{ id: "r1", version: 1, action: "mark_paper", unitsPerUsd: 1000, effectiveFrom: "2026-11-01T00:00:00Z" }],
  estimators: [
    { id: "e1", version: 1, action: "mark_paper", inputKind: "none", baseLow: 2, baseHigh: 4, perInputLow: 0, perInputHigh: 0, effectiveFrom: "2026-11-01T00:00:00Z" },
  ],
  freeAllowances: { studentSignupUnits: 300, teacherSignupUnits: 1000, teacherSignupExpiryDays: 30 },
}

const adminPayment: AdminPaymentRow = {
  id: "pay1", payerUserId: "u1", beneficiaryUserId: "u2", purpose: "subscription_first", status: "paid", amountMinor: 25000,
  currency: "EGP", refundedMinor: 0, paymobOrderId: "PM-1", paymobTxnId: "TX-1", planTierId: "t-s-m", creditPackId: null,
  subscriptionId: "sub1", seatQuantity: null, createdAt: "2026-11-01T09:00:00Z", paidAt: "2026-11-01T09:01:00Z", refunds: [],
}

const customer: CustomerDetail = {
  user: { id: "u2", email: "omar@example.com", displayName: "Omar Hassan", role: "student", createdAt: "2026-10-01T00:00:00Z" },
  balance: { allowanceAvailable: 1500, creditsAvailable: 0, seatAvailable: 0, outstandingDebt: 12 },
  subscriptions: [
    {
      id: "sub1", planTierId: "t-s-m", planCode: "student_plus_m", planName: "Student Plus", status: "active", payerUserId: "u1",
      currentPeriodStart: "2026-11-01T00:00:00Z", currentPeriodEnd: "2026-12-01T00:00:00Z", cancelAtPeriodEnd: false,
      pendingPlanTierId: null, graceUntil: null, extraSeats: 0, pendingExtraSeats: null, paymobSubscriptionId: "501",
      isManuallyActivated: false, periods: [{ periodStart: "2026-11-01T00:00:00Z", periodEnd: "2026-12-01T00:00:00Z", paymentId: "pay1" }],
    },
  ],
  grants: [
    { id: "g1", kind: "period_allowance", visible: false, units: 4000, remaining: 1500, held: 0, effectiveAt: "2026-11-01T00:00:00Z", expiresAt: "2026-12-01T00:00:00Z", teacherMemberId: null, paymentId: "pay1" },
  ],
  debts: [{ id: "d1", jobId: "j9", units: 12, outstanding: 12, createdAt: "2026-11-04T00:00:00Z" }],
  usageJobs: [
    { jobId: "j9", action: "mark_paper", status: "settled", estimateLow: 3, estimateHigh: 5, estimatorVersion: 1, rateVersion: 1, reserved: 5, charged: 9, debtCreated: 12, actualCostUsd: "0.009000", actualUnits: 9, outsideRange: true, createdAt: "2026-11-04T00:00:00Z", settledAt: "2026-11-04T00:01:00Z" },
  ],
  payments: [adminPayment],
  seats: [],
  assistants: [],
  seatedWith: [],
  parents: [{ userId: "u1", email: "mona@example.com", displayName: "Mona Said" }],
  children: [],
  audit: [],
}
```

(Tasks 15 and 16 add `problems`, `health` and `margin` fixtures the same way.)

- [ ] **Step 3: Write `web/src/lib/hooks/useAdminBillingApi.ts`**

```ts
import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
  type InfiniteData,
  type UseInfiniteQueryResult,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query"
import { request } from "@/lib/api"
import { toAdminCatalogue } from "@/lib/billingAdapters"
import type {
  AdminAdjustRequest,
  AdminCancelRequest,
  AdminCatalogue,
  AdminCreditPack,
  AdminExtendRequest,
  AdminForgiveRequest,
  AdminGrantRequest,
  AdminPaymentRow,
  AdminPaymentsPage,
  AdminRefundRequest,
  BillingHealth,
  CustomerDetail,
  CustomerSearchResult,
  EstimatorCreate,
  EstimatorRow,
  FreeAllowanceUpdate,
  FreeAllowancesUpdate,
  ManualActivationRequest,
  MarginReport,
  PackCreate,
  PackUpdate,
  PaymentStatus,
  ProblemQueue,
  RateCreate,
  Reasoned,
  TierCreate,
  TierUpdate,
  UsageRateRow,
  WireAdminCatalogue,
  WireAdminPlanTier,
  WireFreeAllowance,
} from "@/lib/billingTypes"

/*
 * React-query hooks over `/api/admin/billing/*` (plan 07), all `platform_admin` only. Same
 * rule as `useAdminApi.ts`: no `fallback` anywhere, because an empty payload on the console
 * whose job is noticing money trouble reads as "nothing is wrong". Paths omit `/api`.
 */

const enc = encodeURIComponent
const post = (b: unknown): RequestInit => ({ method: "POST", body: JSON.stringify(b) })
const put = (b: unknown): RequestInit => ({ method: "PUT", body: JSON.stringify(b) })
const B = "/admin/billing"

export const adminBillingApi = {
  catalogue: () => request<WireAdminCatalogue>(`${B}/catalogue`),
  createTier: (b: TierCreate) => request<WireAdminPlanTier>(`${B}/tiers`, post(b)),
  updateTier: (id: string, b: TierUpdate) => request<WireAdminPlanTier>(`${B}/tiers/${enc(id)}`, put(b)),
  syncTier: (id: string, b: Reasoned) => request<WireAdminPlanTier>(`${B}/tiers/${enc(id)}/sync`, post(b)),
  createPack: (b: PackCreate) => request<AdminCreditPack>(`${B}/packs`, post(b)),
  updatePack: (id: string, b: PackUpdate) => request<AdminCreditPack>(`${B}/packs/${enc(id)}`, put(b)),
  createRate: (b: RateCreate) => request<UsageRateRow>(`${B}/rates`, post(b)),
  createEstimator: (b: EstimatorCreate) => request<EstimatorRow>(`${B}/estimators`, post(b)),
  updateFreeAllowance: (b: FreeAllowanceUpdate) => request<WireFreeAllowance>(`${B}/free-allowances`, put(b)),
  searchCustomers: (q: string) => request<CustomerSearchResult>(`${B}/customers?q=${enc(q)}`),
  customer: (userId: string) => request<CustomerDetail>(`${B}/customers/${enc(userId)}`),
  grant: (userId: string, b: AdminGrantRequest) => request<CustomerDetail>(`${B}/customers/${enc(userId)}/grant`, post(b)),
  adjust: (userId: string, b: AdminAdjustRequest) => request<CustomerDetail>(`${B}/customers/${enc(userId)}/adjust`, post(b)),
  forgiveDebt: (userId: string, b: AdminForgiveRequest) =>
    request<CustomerDetail>(`${B}/customers/${enc(userId)}/forgive-debt`, post(b)),
  manualActivation: (userId: string, b: ManualActivationRequest) =>
    request<CustomerDetail>(`${B}/customers/${enc(userId)}/manual-activation`, post(b)),
  extend: (subId: string, b: AdminExtendRequest) => request<CustomerDetail>(`${B}/subscriptions/${enc(subId)}/extend`, post(b)),
  cancelSubscription: (subId: string, b: AdminCancelRequest) =>
    request<CustomerDetail>(`${B}/subscriptions/${enc(subId)}/cancel`, post(b)),
  refund: (paymentId: string, b: AdminRefundRequest) => request<AdminPaymentRow>(`${B}/payments/${enc(paymentId)}/refund`, post(b)),
  voidPayment: (paymentId: string, b: Reasoned) => request<AdminPaymentRow>(`${B}/payments/${enc(paymentId)}/void`, post(b)),
  reconcile: (paymentId: string, b: Reasoned) => request<AdminPaymentRow>(`${B}/payments/${enc(paymentId)}/reconcile`, post(b)),
  payments: (status: PaymentStatus | null, cursor: string | null) => {
    const p = new URLSearchParams()
    if (status) p.set("status", status)
    if (cursor) p.set("cursor", cursor)
    const qs = p.toString()
    return request<AdminPaymentsPage>(qs ? `${B}/payments?${qs}` : `${B}/payments`)
  },
  problems: () => request<ProblemQueue>(`${B}/problems`),
  /** `from`/`to` are calendar days; the route takes ISO datetimes (whole days, UTC). */
  margin: (from: string, to: string) =>
    request<MarginReport>(`${B}/margin?from=${enc(`${from}T00:00:00Z`)}&to=${enc(`${to}T23:59:59Z`)}`),
  health: () => request<BillingHealth>(`${B}/health`),
}

export const adminBillingKeys = {
  all: ["admin", "billing"] as const,
  catalogue: ["admin", "billing", "catalogue"] as const,
  customers: (q: string) => ["admin", "billing", "customers", q] as const,
  customer: (userId: string) => ["admin", "billing", "customer", userId] as const,
  payments: (status: PaymentStatus | null) => ["admin", "billing", "payments", status ?? "all"] as const,
  problems: ["admin", "billing", "problems"] as const,
  margin: (from: string, to: string) => ["admin", "billing", "margin", from, to] as const,
  health: ["admin", "billing", "health"] as const,
}

export const useAdminCatalogue = (): UseQueryResult<AdminCatalogue, Error> =>
  useQuery({ queryKey: adminBillingKeys.catalogue, queryFn: adminBillingApi.catalogue, select: toAdminCatalogue })

/** Catalogue writes return the single row, so the catalogue is refetched. */
function useCatalogueWrite<V, D>(fn: (v: V) => Promise<D>): UseMutationResult<D, Error, V> {
  const qc = useQueryClient()
  return useMutation({ mutationFn: fn, onSuccess: () => qc.invalidateQueries({ queryKey: adminBillingKeys.catalogue }) })
}

export const useCreateTier = () => useCatalogueWrite((b: TierCreate) => adminBillingApi.createTier(b))
export const useUpdateTier = () => useCatalogueWrite((v: { id: string; body: TierUpdate }) => adminBillingApi.updateTier(v.id, v.body))
export const useSyncTier = () => useCatalogueWrite((v: { id: string; body: Reasoned }) => adminBillingApi.syncTier(v.id, v.body))
export const useCreatePack = () => useCatalogueWrite((b: PackCreate) => adminBillingApi.createPack(b))
export const useUpdatePack = () => useCatalogueWrite((v: { id: string; body: PackUpdate }) => adminBillingApi.updatePack(v.id, v.body))
export const useCreateRate = () => useCatalogueWrite((b: RateCreate) => adminBillingApi.createRate(b))
export const useCreateEstimator = () => useCatalogueWrite((b: EstimatorCreate) => adminBillingApi.createEstimator(b))
/** One form, two requests: 07 updates one audience per call. */
export const useUpdateFreeAllowances = () =>
  useCatalogueWrite((b: FreeAllowancesUpdate) =>
    Promise.all([
      adminBillingApi.updateFreeAllowance({ audience: "student", units: b.studentSignupUnits, reason: b.reason }),
      adminBillingApi.updateFreeAllowance({ audience: "teacher", units: b.teacherSignupUnits, reason: b.reason }),
    ]),
  )

export function useCustomerSearch(q: string): UseQueryResult<CustomerSearchResult, Error> {
  const term = q.trim()
  return useQuery({ queryKey: adminBillingKeys.customers(term), queryFn: () => adminBillingApi.searchCustomers(term), enabled: term.length >= 2 })
}

export const useCustomer = (userId: string): UseQueryResult<CustomerDetail, Error> =>
  useQuery({ queryKey: adminBillingKeys.customer(userId), queryFn: () => adminBillingApi.customer(userId), enabled: userId !== "" })

function useCustomerWrite<V extends { id: string }>(userId: string, fn: (v: V) => Promise<CustomerDetail>): UseMutationResult<CustomerDetail, Error, V> {
  const qc = useQueryClient()
  return useMutation({ mutationFn: fn, onSuccess: (data) => qc.setQueryData(adminBillingKeys.customer(userId), data) })
}

export const useGrantCredits = (userId: string) =>
  useCustomerWrite(userId, (v: { id: string; body: AdminGrantRequest }) => adminBillingApi.grant(v.id, v.body))
export const useAdjustBalance = (userId: string) =>
  useCustomerWrite(userId, (v: { id: string; body: AdminAdjustRequest }) => adminBillingApi.adjust(v.id, v.body))
export const useForgiveDebt = (userId: string) =>
  useCustomerWrite(userId, (v: { id: string; body: AdminForgiveRequest }) => adminBillingApi.forgiveDebt(v.id, v.body))
export const useManualActivation = (userId: string) =>
  useCustomerWrite(userId, (v: { id: string; body: ManualActivationRequest }) => adminBillingApi.manualActivation(v.id, v.body))
export const useExtendSubscription = (userId: string) =>
  useCustomerWrite(userId, (v: { id: string; body: AdminExtendRequest }) => adminBillingApi.extend(v.id, v.body))
export const useAdminCancelSubscription = (userId: string) =>
  useCustomerWrite(userId, (v: { id: string; body: AdminCancelRequest }) => adminBillingApi.cancelSubscription(v.id, v.body))

function usePaymentWrite<B>(fn: (id: string, b: B) => Promise<AdminPaymentRow>): UseMutationResult<AdminPaymentRow, Error, { id: string; body: B }> {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (v: { id: string; body: B }) => fn(v.id, v.body),
    onSuccess: () => qc.invalidateQueries({ queryKey: adminBillingKeys.all }),
  })
}

export const useRefundPayment = () => usePaymentWrite(adminBillingApi.refund)
export const useVoidPayment = () => usePaymentWrite(adminBillingApi.voidPayment)
export const useReconcilePayment = () => usePaymentWrite(adminBillingApi.reconcile)

export function useAdminPayments(status: PaymentStatus | null): UseInfiniteQueryResult<InfiniteData<AdminPaymentsPage, string | null>, Error> {
  return useInfiniteQuery({
    queryKey: adminBillingKeys.payments(status),
    queryFn: ({ pageParam }) => adminBillingApi.payments(status, pageParam),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.nextCursor,
  })
}

export const useProblemQueue = (): UseQueryResult<ProblemQueue, Error> =>
  useQuery({ queryKey: adminBillingKeys.problems, queryFn: adminBillingApi.problems, refetchInterval: 60_000 })

export const useMarginReport = (from: string, to: string): UseQueryResult<MarginReport, Error> =>
  useQuery({ queryKey: adminBillingKeys.margin(from, to), queryFn: () => adminBillingApi.margin(from, to) })

export const useBillingHealth = (): UseQueryResult<BillingHealth, Error> =>
  useQuery({ queryKey: adminBillingKeys.health, queryFn: adminBillingApi.health, refetchInterval: 60_000 })
```

- [ ] **Step 4: Write `web/src/lib/adminBillingModel.ts`**

```ts
import { METERED_ACTIONS } from "@/lib/billingTypes"
import type {
  AdminCreditPack,
  AdminPlanTier,
  EstimatorCreate,
  EstimatorInputKind,
  FreeAllowances,
  FreeAllowanceUpdate,
  MeteredAction,
  PackCreate,
  PackUpdate,
  RateCreate,
  TierCreate,
  TierUpdate,
} from "@/lib/billingTypes"

/* Pure form models for the admin billing console. Every write carries a reason (spec §8). Bodies
 * match plan 07's request models exactly. */

export function reasonError(reason: string): string | null {
  return reason.trim().length >= 5 ? null : "Give a reason of at least 5 characters. It is saved in the audit log."
}

export function minorFromMajor(text: string): number | null {
  if (!/^\d+(\.\d{1,2})?$/.test(text.trim())) return null
  return Math.round(Number(text) * 100)
}

export function majorFromMinor(minor: number): string {
  return (minor / 100).toFixed(2)
}

/** A date input's `YYYY-MM-DD` as the ISO datetime the routes take (UTC midnight). */
export function isoDay(date: string): string {
  return `${date}T00:00:00Z`
}

export type FieldSpec =
  | { name: string; label: string; kind: "text" | "date"; optional?: boolean }
  | { name: string; label: string; kind: "number" | "money"; optional?: boolean }
  | { name: string; label: string; kind: "select"; options: { value: string; label: string }[] }
  | { name: string; label: string; kind: "checkbox" }
  | { name: string; label: string; kind: "lines" }

export type FormValues = Record<string, string | boolean>

const str = (v: FormValues, k: string) => String(v[k] ?? "").trim()
const num = (v: FormValues, k: string) => Number(str(v, k))
const intOrZero = (v: FormValues, k: string) => (str(v, k) === "" ? 0 : Number(str(v, k)))
const numOrNull = (v: FormValues, k: string) => (str(v, k) === "" ? null : Number(str(v, k)))
const dayOrNull = (v: FormValues, k: string) => (str(v, k) === "" ? null : isoDay(str(v, k)))
const moneyOrZero = (v: FormValues, k: string) => (str(v, k) === "" ? 0 : (minorFromMajor(str(v, k)) ?? 0))
/** M2 convention: each feature line is a key set to `true`. */
const featureDict = (v: FormValues) =>
  Object.fromEntries(
    str(v, "features")
      .split("\n")
      .map((l) => l.trim())
      .filter(Boolean)
      .map((l) => [l, true] as const),
  )

export function validateFields(fields: FieldSpec[], values: FormValues): string[] {
  const errors: string[] = []
  for (const f of fields) {
    const raw = str(values, f.name)
    if ((f.kind === "text" || f.kind === "date") && raw === "" && !f.optional) errors.push(`${f.label} is required.`)
    if (f.kind === "number" || f.kind === "money") {
      if (raw === "" && f.optional) continue
      const ok = f.kind === "money" ? minorFromMajor(raw) !== null : raw !== "" && Number.isFinite(Number(raw)) && Number(raw) >= 0
      if (!ok) errors.push(`${f.label} must be zero or more.`)
    }
  }
  return errors
}

const ACTION_OPTIONS = METERED_ACTIONS.map((a) => ({ value: a, label: a }))

/** Editable after creation (07 `PlanTierUpdateDTO`). */
export const TIER_UPDATE_FIELDS: FieldSpec[] = [
  { name: "name", label: "Name", kind: "text" },
  { name: "priceMajor", label: "Price (EGP)", kind: "money" },
  { name: "allowanceUnits", label: "Allowance per period (units)", kind: "number" },
  { name: "includedSeats", label: "Included seats (teacher)", kind: "number", optional: true },
  { name: "seatAllowanceUnits", label: "Seat allowance per month (units)", kind: "number", optional: true },
  { name: "extraSeatPriceMajor", label: "Extra seat price (EGP)", kind: "money", optional: true },
  { name: "features", label: "Feature lines, one per line", kind: "lines" },
  { name: "isActive", label: "On sale", kind: "checkbox" },
]

/** Creation also fixes code, audience and interval (07 `PlanTierCreateDTO`; currency is EGP). */
export const TIER_FIELDS: FieldSpec[] = [
  { name: "code", label: "Code", kind: "text" },
  { name: "audience", label: "Audience", kind: "select", options: [{ value: "student", label: "Student" }, { value: "teacher", label: "Teacher" }] },
  { name: "interval", label: "Interval", kind: "select", options: [{ value: "monthly", label: "Monthly" }, { value: "yearly", label: "Yearly" }] },
  ...TIER_UPDATE_FIELDS,
]

export function tierValues(t: AdminPlanTier | null): FormValues {
  return {
    code: t?.code ?? "",
    name: t?.name ?? "",
    audience: t?.audience ?? "student",
    interval: t?.interval === "year" ? "yearly" : "monthly",
    priceMajor: t ? majorFromMinor(t.priceMinor) : "",
    allowanceUnits: t ? String(t.allowanceUnits) : "",
    includedSeats: t?.includedSeats != null ? String(t.includedSeats) : "",
    seatAllowanceUnits: t?.seatAllowanceUnits != null ? String(t.seatAllowanceUnits) : "",
    extraSeatPriceMajor: t?.extraSeatPriceMinor != null ? majorFromMinor(t.extraSeatPriceMinor) : "",
    features: (t?.features ?? []).join("\n"),
    isActive: t?.isActive ?? true,
  }
}

export function tierUpdateBody(v: FormValues, reason: string): TierUpdate {
  return {
    name: str(v, "name"),
    priceMinor: minorFromMajor(str(v, "priceMajor")) ?? 0,
    allowanceUnits: num(v, "allowanceUnits"),
    includedSeats: intOrZero(v, "includedSeats"),
    seatAllowanceUnits: intOrZero(v, "seatAllowanceUnits"),
    extraSeatPriceMinor: moneyOrZero(v, "extraSeatPriceMajor"),
    features: featureDict(v),
    isActive: v.isActive === true,
    reason,
  }
}

export function tierBody(v: FormValues, reason: string): TierCreate {
  const { name, priceMinor, allowanceUnits, includedSeats, seatAllowanceUnits, extraSeatPriceMinor, features, isActive } = tierUpdateBody(v, reason)
  return {
    code: str(v, "code"),
    name,
    audience: str(v, "audience") === "teacher" ? "teacher" : "student",
    interval: str(v, "interval") === "yearly" ? "yearly" : "monthly",
    priceMinor,
    currency: "EGP",
    allowanceUnits,
    includedSeats,
    seatAllowanceUnits,
    extraSeatPriceMinor,
    features,
    isActive,
    reason,
  }
}

export const PACK_UPDATE_FIELDS: FieldSpec[] = [
  { name: "name", label: "Name", kind: "text" },
  { name: "units", label: "Credits", kind: "number" },
  { name: "priceMajor", label: "Price (EGP)", kind: "money" },
  { name: "isActive", label: "On sale", kind: "checkbox" },
]

export const PACK_FIELDS: FieldSpec[] = [{ name: "code", label: "Code", kind: "text" }, ...PACK_UPDATE_FIELDS]

export function packValues(p: AdminCreditPack | null): FormValues {
  return {
    code: p?.code ?? "",
    name: p?.name ?? "",
    units: p ? String(p.units) : "",
    priceMajor: p ? majorFromMinor(p.priceMinor) : "",
    isActive: p?.isActive ?? true,
  }
}

export function packUpdateBody(v: FormValues, reason: string): PackUpdate {
  return { name: str(v, "name"), units: num(v, "units"), priceMinor: minorFromMajor(str(v, "priceMajor")) ?? 0, isActive: v.isActive === true, reason }
}

export function packBody(v: FormValues, reason: string): PackCreate {
  const { name, units, priceMinor, isActive } = packUpdateBody(v, reason)
  return { code: str(v, "code"), name, units, priceMinor, currency: "EGP", isActive, reason }
}

export const RATE_FIELDS: FieldSpec[] = [
  { name: "action", label: "Action", kind: "select", options: ACTION_OPTIONS },
  { name: "unitsPerUsd", label: "Units per USD", kind: "number" },
  { name: "effectiveFrom", label: "Effective from (empty = now)", kind: "date", optional: true },
]

export function rateBody(v: FormValues, reason: string): RateCreate {
  return { action: str(v, "action") as MeteredAction, unitsPerUsd: num(v, "unitsPerUsd"), effectiveFrom: dayOrNull(v, "effectiveFrom"), reason }
}

export const ESTIMATOR_FIELDS: FieldSpec[] = [
  { name: "action", label: "Action", kind: "select", options: ACTION_OPTIONS },
  {
    name: "inputKind",
    label: "Counted input",
    kind: "select",
    options: ["none", "pages", "marks", "questions"].map((k) => ({ value: k, label: k })),
  },
  { name: "baseLow", label: "Base low (units)", kind: "number" },
  { name: "baseHigh", label: "Base high (units)", kind: "number" },
  { name: "perInputLow", label: "Per input low (units)", kind: "number" },
  { name: "perInputHigh", label: "Per input high (units)", kind: "number" },
  { name: "effectiveFrom", label: "Effective from (empty = now)", kind: "date", optional: true },
]

export function estimatorBody(v: FormValues, reason: string): EstimatorCreate {
  return {
    action: str(v, "action") as MeteredAction,
    inputKind: str(v, "inputKind") as EstimatorInputKind,
    baseLow: num(v, "baseLow"),
    baseHigh: num(v, "baseHigh"),
    perInputLow: num(v, "perInputLow"),
    perInputHigh: num(v, "perInputHigh"),
    effectiveFrom: dayOrNull(v, "effectiveFrom"),
    reason,
  }
}

/** 07's free-allowance update carries units only; the teacher credits' validity is read-only. */
export const FREE_FIELDS: FieldSpec[] = [
  { name: "studentSignupUnits", label: "Student free allowance (units)", kind: "number" },
  { name: "teacherSignupUnits", label: "Teacher signup credits (units)", kind: "number" },
]

export function freeValues(f: FreeAllowances): FormValues {
  return { studentSignupUnits: String(f.studentSignupUnits), teacherSignupUnits: String(f.teacherSignupUnits) }
}

/** The two `FreeAllowanceUpdateDTO` bodies the form produces. */
export function freeBody(v: FormValues, reason: string): FreeAllowanceUpdate[] {
  return [
    { audience: "student", units: num(v, "studentSignupUnits"), reason },
    { audience: "teacher", units: num(v, "teacherSignupUnits"), reason },
  ]
}

/** The hook's single variable: both audiences in one reasoned submit. */
export function freeFormBody(v: FormValues, reason: string) {
  const [student, teacher] = freeBody(v, reason)
  return { studentSignupUnits: student.units, teacherSignupUnits: teacher.units, reason }
}
```

- [ ] **Step 5: Run the model and fetcher tests to verify they pass**

Run: `npx vitest run tests/unit/adminBillingApi.test.ts tests/unit/adminBillingModel.test.ts`
Expected: PASS.

- [ ] **Step 6: Write the failing screen test**

`web/tests/unit/adminCatalogue.test.ts`:

```ts
import { createElement as h } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { fx } from "./support/billingFixtures"
import { fakeMutation, okQuery, renderStatic } from "./support/billingRender"

const s = vi.hoisted(() => ({ catalogue: null as unknown }))
vi.mock("@/lib/hooks/useAdminBillingApi", () => ({
  useAdminCatalogue: () => s.catalogue,
  useCreateTier: () => fakeMutation(),
  useUpdateTier: () => fakeMutation(),
  useSyncTier: () => fakeMutation(),
  useCreatePack: () => fakeMutation(),
  useUpdatePack: () => fakeMutation(),
  useCreateRate: () => fakeMutation(),
  useCreateEstimator: () => fakeMutation(),
  useUpdateFreeAllowances: () => fakeMutation(),
}))
vi.mock("@/components/ui/modal", () => ({
  Modal: (p: { open: boolean; title: unknown; children: unknown; footer?: unknown }) =>
    p.open ? h("div", { role: "dialog" }, h("h2", null, p.title as never), p.children as never, p.footer as never) : null,
}))

import { Catalogue } from "@/portals/admin/screens/billing/Catalogue"
import { ReasonedFormDialog } from "@/portals/admin/screens/billing/ReasonedFormDialog"
import { PACK_FIELDS, packValues } from "@/lib/adminBillingModel"

beforeEach(() => {
  s.catalogue = okQuery(fx.adminCatalogue)
})

describe("Catalogue", () => {
  it("shows tiers with hidden allowance units, packs, rates, estimators and free allowances", () => {
    const html = renderStatic(h(Catalogue))
    expect(html).toContain("student_plus_m")
    expect(html).toContain("4,000")
    expect(html).toContain("pack_500")
    expect(html).toContain("Units per USD")
    expect(html).toContain("none")
    expect(html).toContain("Student free allowance")
  })

  it("warns about Paymob drift and offers a sync", () => {
    s.catalogue = okQuery({ ...fx.adminCatalogue, tiers: [{ ...fx.adminCatalogue.tiers[0], drift: "Paymob amount is 240.00" }] })
    const html = renderStatic(h(Catalogue))
    expect(html).toContain("Paymob amount is 240.00")
    expect(html).toContain("Sync to Paymob")
  })
})

describe("ReasonedFormDialog", () => {
  it("always asks for a reason and names the audit log", () => {
    const html = renderStatic(
      h(ReasonedFormDialog, {
        open: true,
        onClose: () => undefined,
        title: "Edit pack",
        fields: PACK_FIELDS,
        initial: packValues(fx.adminCatalogue.packs[0]),
        submitLabel: "Save pack",
        // Test files are typechecked; a fake passed straight in as a prop is cast.
        mutation: fakeMutation() as never,
        toBody: () => ({}) as never,
      }),
    )
    expect(html).toContain("Reason")
    expect(html).toContain("saved in the audit log")
    expect(html).toContain("Save pack")
  })
})
```

- [ ] **Step 7: Run it to verify it fails**

Run: `npx vitest run tests/unit/adminCatalogue.test.ts`
Expected: FAIL, "Failed to resolve import "@/portals/admin/screens/billing/Catalogue"".

- [ ] **Step 8: Write `ReasonedFormDialog.tsx`**

`web/src/portals/admin/screens/billing/ReasonedFormDialog.tsx`:

```tsx
import { useState, type ReactNode } from "react"
import type { UseMutationResult } from "@tanstack/react-query"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Modal } from "@/components/ui/modal"
import { Select } from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import { reasonError, validateFields, type FieldSpec, type FormValues } from "@/lib/adminBillingModel"
import { billingFailureMessage } from "@/lib/billingOutcome"

/*
 * Every admin money or catalogue write goes through this dialog: the fields, plus a required
 * reason that the server writes to `admin_audit_log` in the same transaction (spec §4.7, §8).
 */

export function ReasonedFormDialog<TBody>({
  open,
  onClose,
  title,
  fields,
  initial,
  submitLabel,
  mutation,
  toBody,
  note,
}: {
  open: boolean
  onClose: () => void
  title: string
  fields: FieldSpec[]
  initial: FormValues
  submitLabel: string
  mutation: UseMutationResult<unknown, Error, TBody>
  toBody: (values: FormValues, reason: string) => TBody
  note?: ReactNode
}) {
  const [values, setValues] = useState<FormValues>(initial)
  const [reason, setReason] = useState("")
  const [submitted, setSubmitted] = useState(false)
  const errors = [...validateFields(fields, values), ...(reasonError(reason) ? [reasonError(reason) as string] : [])]
  const set = (name: string, value: string | boolean) => setValues((v) => ({ ...v, [name]: value }))

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={title}
      dismissible={!mutation.isPending}
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button
            variant="primary"
            loading={mutation.isPending}
            onClick={() => {
              setSubmitted(true)
              if (errors.length === 0) mutation.mutate(toBody(values, reason.trim()), { onSuccess: onClose })
            }}
          >
            {submitLabel}
          </Button>
        </div>
      }
    >
      <div className="flex flex-col gap-3">
        {note}
        {fields.map((f) => {
          const value = values[f.name]
          if (f.kind === "checkbox") {
            return <Checkbox key={f.name} label={f.label} checked={value === true} onChange={(e) => set(f.name, e.target.checked)} />
          }
          if (f.kind === "select") {
            return (
              <Select key={f.name} label={f.label} value={String(value ?? "")} onChange={(e) => set(f.name, e.target.value)}>
                {f.options.map((o) => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </Select>
            )
          }
          if (f.kind === "lines") {
            return <Textarea key={f.name} label={f.label} value={String(value ?? "")} onChange={(e) => set(f.name, e.target.value)} />
          }
          return (
            <Input
              key={f.name}
              label={f.label}
              type={f.kind === "date" ? "date" : f.kind === "text" ? "text" : "number"}
              inputMode={f.kind === "money" ? "decimal" : f.kind === "number" ? "numeric" : undefined}
              step={f.kind === "money" ? "0.01" : undefined}
              value={String(value ?? "")}
              onChange={(e) => set(f.name, e.target.value)}
            />
          )
        })}
        <Textarea
          label="Reason"
          hint="Required. It is saved in the audit log with this change."
          value={reason}
          onChange={(e) => setReason(e.target.value)}
        />
        {submitted && errors.length > 0 ? (
          <ul role="alert" className="m-0 flex flex-col gap-1 ps-4 text-body-sm text-error">
            {errors.map((m) => <li key={m}>{m}</li>)}
          </ul>
        ) : null}
        {mutation.isError ? <p role="alert" className="m-0 text-body-sm text-error">{billingFailureMessage(mutation.error, "save this change")}</p> : null}
      </div>
    </Modal>
  )
}
```

- [ ] **Step 9: Write `BillingLayout.tsx` and `Catalogue.tsx`**

`web/src/portals/admin/screens/billing/BillingLayout.tsx`:

```tsx
import { NavLink, Outlet } from "react-router-dom"
import { cn } from "@/lib/utils"

/*
 * `/platform/billing` and its areas (spec §8). One sidebar entry, a pill nav per area, so the
 * platform sidebar stays short. Tasks 14–16 append their areas to `BILLING_AREAS`.
 */

export const BILLING_AREAS: readonly { to: string; label: string; end?: boolean }[] = [
  { to: "/platform/billing/catalogue", label: "Catalogue" },
]

export function BillingLayout() {
  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-1">
        <div className="text-eyebrow text-on-surface-variant">Platform</div>
        <h1 className="m-0 text-display-md text-on-surface">Billing</h1>
      </div>
      <nav aria-label="Billing areas" className="flex flex-wrap gap-1">
        {BILLING_AREAS.map((a) => (
          <NavLink
            key={a.to}
            to={a.to}
            end={a.end}
            className={({ isActive }) =>
              cn(
                "rounded-md px-3 py-1.5 text-body-sm transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary pointer-coarse:flex pointer-coarse:items-center pointer-coarse:min-h-11",
                isActive ? "bg-surface-container-low font-medium text-on-surface" : "text-on-surface-variant hover:bg-surface-container-low hover:text-on-surface",
              )
            }
          >
            {a.label}
          </NavLink>
        ))}
      </nav>
      <Outlet />
    </div>
  )
}
```

`web/src/portals/admin/screens/billing/Catalogue.tsx`:

```tsx
import { useState, type ReactNode } from "react"
import { Button } from "@/components/ui/button"
import { PageHeaderSkeleton } from "@/components/ui/loading-shapes"
import { QueryState } from "@/components/ui/query-state"
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table"
import {
  ESTIMATOR_FIELDS,
  FREE_FIELDS,
  PACK_FIELDS,
  PACK_UPDATE_FIELDS,
  RATE_FIELDS,
  TIER_FIELDS,
  TIER_UPDATE_FIELDS,
  estimatorBody,
  freeFormBody,
  freeValues,
  packBody,
  packUpdateBody,
  packValues,
  rateBody,
  tierBody,
  tierUpdateBody,
  tierValues,
} from "@/lib/adminBillingModel"
import { formatBillingDate, formatMoney } from "@/lib/billingFormat"
import type { AdminCatalogue, AdminCreditPack, AdminPlanTier } from "@/lib/billingTypes"
import {
  useAdminCatalogue,
  useCreateEstimator,
  useCreatePack,
  useCreateRate,
  useCreateTier,
  useSyncTier,
  useUpdateFreeAllowances,
  useUpdatePack,
  useUpdateTier,
} from "@/lib/hooks/useAdminBillingApi"
import { ReasonedFormDialog } from "./ReasonedFormDialog"

/* Catalogue (spec §8.1): every price, allowance, pack, rate and estimator is data, versioned
 * where it affects charging, and every change carries a reason. */

type Dialog =
  | { kind: "tier"; tier: AdminPlanTier | null }
  | { kind: "sync"; tier: AdminPlanTier }
  | { kind: "pack"; pack: AdminCreditPack | null }
  | { kind: "rate" }
  | { kind: "estimator" }
  | { kind: "free" }
  | null

const n = (v: number) => new Intl.NumberFormat().format(v)
const today = () => new Date().toISOString().slice(0, 10)

function Section({ title, action, children }: { title: string; action: ReactNode; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="m-0 text-display-sm text-on-surface">{title}</h2>
        {action}
      </div>
      {children}
    </section>
  )
}

function Body({ c, open }: { c: AdminCatalogue; open: (d: Dialog) => void }) {
  return (
    <div className="flex flex-col gap-8">
      <Section title="Plan tiers" action={<Button variant="secondary" onClick={() => open({ kind: "tier", tier: null })}>New tier</Button>}>
        <Table density="operate">
          <caption className="sr-only">Plan tiers</caption>
          <THead>
            <TR>
              <TH>Code</TH><TH>Name</TH><TH>Audience</TH><TH>Interval</TH><TH numeric>Price</TH><TH numeric>Allowance</TH>
              <TH numeric>Seats</TH><TH numeric>Seat allowance</TH><TH numeric>Extra seat</TH><TH>On sale</TH><TH>Paymob</TH>
              <TH><span className="sr-only">Actions</span></TH>
            </TR>
          </THead>
          <TBody>
            {c.tiers.map((t) => (
              <TR key={t.id}>
                <TD><span className="text-data-sm">{t.code}</span></TD>
                <TD>{t.name}</TD>
                <TD>{t.audience}</TD>
                <TD>{t.interval}</TD>
                <TD numeric>{formatMoney(t.priceMinor, t.currency)}</TD>
                <TD numeric>{n(t.allowanceUnits)}</TD>
                <TD numeric>{t.includedSeats ?? "—"}</TD>
                <TD numeric>{t.seatAllowanceUnits === null ? "—" : n(t.seatAllowanceUnits)}</TD>
                <TD numeric>{t.extraSeatPriceMinor === null ? "—" : formatMoney(t.extraSeatPriceMinor, t.currency)}</TD>
                <TD>{t.isActive ? "Yes" : "No"}</TD>
                <TD>
                  <span className="text-data-sm">{t.paymobPlanId ?? "—"}</span>
                  {t.drift ? <span role="note" className="block text-body-sm text-error">{t.drift}</span> : null}
                </TD>
                <TD>
                  <div className="flex gap-1">
                    <Button size="sm" variant="ghost" onClick={() => open({ kind: "tier", tier: t })} aria-label={`Edit ${t.code}`}>Edit</Button>
                    <Button size="sm" variant="ghost" onClick={() => open({ kind: "sync", tier: t })} aria-label={`Sync ${t.code} to Paymob`}>Sync to Paymob</Button>
                  </div>
                </TD>
              </TR>
            ))}
          </TBody>
        </Table>
      </Section>

      <Section title="Credit packs" action={<Button variant="secondary" onClick={() => open({ kind: "pack", pack: null })}>New pack</Button>}>
        <Table density="operate">
          <caption className="sr-only">Credit packs</caption>
          <THead><TR><TH>Code</TH><TH>Name</TH><TH numeric>Credits</TH><TH numeric>Price</TH><TH>On sale</TH><TH><span className="sr-only">Actions</span></TH></TR></THead>
          <TBody>
            {c.packs.map((p) => (
              <TR key={p.id}>
                <TD><span className="text-data-sm">{p.code}</span></TD>
                <TD>{p.name}</TD>
                <TD numeric>{n(p.units)}</TD>
                <TD numeric>{formatMoney(p.priceMinor, p.currency)}</TD>
                <TD>{p.isActive ? "Yes" : "No"}</TD>
                <TD><Button size="sm" variant="ghost" onClick={() => open({ kind: "pack", pack: p })} aria-label={`Edit ${p.code}`}>Edit</Button></TD>
              </TR>
            ))}
          </TBody>
        </Table>
      </Section>

      <Section title="Usage rates" action={<Button variant="secondary" onClick={() => open({ kind: "rate" })}>New rate version</Button>}>
        <Table density="operate">
          <caption className="sr-only">Usage rates</caption>
          <THead><TR><TH numeric>Version</TH><TH>Action</TH><TH numeric>Units per USD</TH><TH>Effective from</TH></TR></THead>
          <TBody>
            {c.rates.map((r) => (
              <TR key={`${r.version}-${r.action}`}>
                <TD numeric>{r.version}</TD><TD>{r.action}</TD><TD numeric>{n(r.unitsPerUsd)}</TD><TD>{formatBillingDate(r.effectiveFrom)}</TD>
              </TR>
            ))}
          </TBody>
        </Table>
      </Section>

      <Section title="Estimators" action={<Button variant="secondary" onClick={() => open({ kind: "estimator" })}>New estimator version</Button>}>
        <Table density="operate">
          <caption className="sr-only">Estimators</caption>
          <THead><TR><TH numeric>Version</TH><TH>Action</TH><TH>Input</TH><TH numeric>Base</TH><TH numeric>Per input</TH><TH>Effective from</TH></TR></THead>
          <TBody>
            {c.estimators.map((e) => (
              <TR key={`${e.version}-${e.action}`}>
                <TD numeric>{e.version}</TD><TD>{e.action}</TD><TD>{e.inputKind}</TD>
                <TD numeric>{e.baseLow}–{e.baseHigh}</TD><TD numeric>{e.perInputLow}–{e.perInputHigh}</TD><TD>{formatBillingDate(e.effectiveFrom)}</TD>
              </TR>
            ))}
          </TBody>
        </Table>
      </Section>

      <Section title="Free allowances" action={<Button variant="secondary" onClick={() => open({ kind: "free" })}>Edit</Button>}>
        <dl className="m-0 grid gap-2 text-body-sm md:grid-cols-3">
          <div><dt className="text-on-surface-variant">Student free allowance</dt><dd className="m-0 text-data-md">{n(c.freeAllowances.studentSignupUnits)} units</dd></div>
          <div><dt className="text-on-surface-variant">Teacher signup credits</dt><dd className="m-0 text-data-md">{n(c.freeAllowances.teacherSignupUnits)} units</dd></div>
          <div><dt className="text-on-surface-variant">Teacher credits expire after</dt><dd className="m-0 text-data-md">{c.freeAllowances.teacherSignupExpiryDays === null ? "Never" : `${c.freeAllowances.teacherSignupExpiryDays} days`}</dd></div>
        </dl>
      </Section>
    </div>
  )
}

export function Catalogue() {
  const catalogue = useAdminCatalogue()
  const createTier = useCreateTier()
  const updateTier = useUpdateTier()
  const syncTier = useSyncTier()
  const createPack = useCreatePack()
  const updatePack = useUpdatePack()
  const createRate = useCreateRate()
  const createEstimator = useCreateEstimator()
  const updateFree = useUpdateFreeAllowances()
  const [dialog, setDialog] = useState<Dialog>(null)
  const close = () => setDialog(null)

  return (
    <QueryState query={catalogue} skeleton={<PageHeaderSkeleton />} error={{ heading: "Couldn't load the catalogue" }}>
      {(c) => (
        <>
          <Body c={c} open={setDialog} />
          {dialog?.kind === "tier" ? (
            dialog.tier ? (
              <ReasonedFormDialog open onClose={close} title={`Edit ${dialog.tier.code}`} fields={TIER_UPDATE_FIELDS} initial={tierValues(dialog.tier)}
                submitLabel="Save tier" mutation={updateTier} toBody={(v, r) => ({ id: dialog.tier!.id, body: tierUpdateBody(v, r) })} />
            ) : (
              <ReasonedFormDialog open onClose={close} title="New plan tier" fields={TIER_FIELDS} initial={tierValues(null)}
                submitLabel="Create tier" mutation={createTier} toBody={tierBody} />
            )
          ) : null}
          {dialog?.kind === "sync" ? (
            <ReasonedFormDialog open onClose={close} title={`Sync ${dialog.tier.code} to Paymob`} fields={[]} initial={{}}
              submitLabel="Sync to Paymob" mutation={syncTier} toBody={(_v, r) => ({ id: dialog.tier.id, body: { reason: r } })}
              note={<p className="m-0 text-body-sm text-on-surface">This writes the tier's price and interval to its Paymob plan.</p>} />
          ) : null}
          {dialog?.kind === "pack" ? (
            dialog.pack ? (
              <ReasonedFormDialog open onClose={close} title={`Edit ${dialog.pack.code}`} fields={PACK_UPDATE_FIELDS} initial={packValues(dialog.pack)}
                submitLabel="Save pack" mutation={updatePack} toBody={(v, r) => ({ id: dialog.pack!.id, body: packUpdateBody(v, r) })} />
            ) : (
              <ReasonedFormDialog open onClose={close} title="New credit pack" fields={PACK_FIELDS} initial={packValues(null)}
                submitLabel="Create pack" mutation={createPack} toBody={packBody} />
            )
          ) : null}
          {dialog?.kind === "rate" ? (
            <ReasonedFormDialog open onClose={close} title="New usage rate version" fields={RATE_FIELDS}
              initial={{ action: "mark_paper", unitsPerUsd: "", effectiveFrom: today() }} submitLabel="Create version" mutation={createRate} toBody={rateBody} />
          ) : null}
          {dialog?.kind === "estimator" ? (
            <ReasonedFormDialog open onClose={close} title="New estimator version" fields={ESTIMATOR_FIELDS}
              initial={{ action: "mark_paper", inputKind: "none", baseLow: "", baseHigh: "", perInputLow: "", perInputHigh: "", effectiveFrom: today() }}
              submitLabel="Create version" mutation={createEstimator} toBody={estimatorBody} />
          ) : null}
          {dialog?.kind === "free" ? (
            <ReasonedFormDialog open onClose={close} title="Free allowances" fields={FREE_FIELDS} initial={freeValues(c.freeAllowances)}
              submitLabel="Save allowances" mutation={updateFree} toBody={freeFormBody} />
          ) : null}
        </>
      )}
    </QueryState>
  )
}
```

The drift note uses `text-error`: drift is a genuine error state (the live Paymob plan disagrees
with the catalogue), which is what the Red Means Lost rule reserves crimson for.

- [ ] **Step 10: Mount the route, nav entry and trail**

`web/src/portals/admin/data.ts`: add `| "billing"` to `AdminNavItem["icon"]`; insert
`{ to: "/platform/billing", label: "Billing", icon: "billing" },` directly after the Console
entry in `platformNavItems`; in `resolveAdminTrail`, before the `PLATFORM_DETAIL_CRUMBS` loop:

```ts
  if (lane === "platform" && path.startsWith("/platform/billing/")) {
    const area = path.slice("/platform/billing/".length).split("/")[0]
    const label = ({ catalogue: "Catalogue", payments: "Payments", margin: "Money and margin", health: "Health", customers: "Customer" } as Record<string, string>)[area]
    if (label) return [{ label: rootLabel, to: rootPath }, { label: "Billing", to: "/platform/billing" }, { label }]
  }
```

`web/src/portals/admin/index.tsx`: import `Receipt` from `@phosphor-icons/react`, add
`billing: Receipt,` to `NAV_ICON`; add lazies

```tsx
const BillingLayout = lazy(() => import("./screens/billing/BillingLayout").then((m) => ({ default: m.BillingLayout })))
const BillingCatalogue = lazy(() => import("./screens/billing/Catalogue").then((m) => ({ default: m.Catalogue })))
```

and, in `platformAdminRoute.children` after `schools`:

```tsx
    // Billing (Paymob phase 08, spec §8). Inherits the platform_admin guard.
    {
      path: "billing",
      element: <BillingLayout />,
      handle: { title: "Platform billing", skeleton: "page-header" },
      children: [
        { index: true, element: <Navigate to="catalogue" replace /> },
        { path: "catalogue", element: <BillingCatalogue />, handle: { title: "Billing catalogue", skeleton: "page-header" } },
      ],
    },
```

(import `Navigate` from `react-router-dom`). Add to `web/tests/unit/adminRoutes.test.ts`:

```ts
  it("puts Billing in the platform navigation and trails its areas", () => {
    expect(platformNavItems.map((item) => item.to)).toContain("/platform/billing")
    expect(resolveAdminTrail("/platform/billing/catalogue", "platform")).toEqual([
      { label: "Console", to: "/platform" },
      { label: "Billing", to: "/platform/billing" },
      { label: "Catalogue" },
    ])
  })
```

- [ ] **Step 11: Run the tests to verify they pass**

Run: `npx vitest run tests/unit/adminBillingApi.test.ts tests/unit/adminBillingModel.test.ts tests/unit/adminCatalogue.test.ts tests/unit/adminRoutes.test.ts tests/unit/navigation.test.ts`
Expected: PASS.

- [ ] **Step 12: Run the frontend gate**

```bash
npm run typecheck
npx vitest run tests/unit/adminBillingApi.test.ts tests/unit/adminBillingModel.test.ts tests/unit/adminCatalogue.test.ts tests/unit/adminRoutes.test.ts tests/unit/navigation.test.ts tests/unit/tableDensity.test.ts $SCAN
npm run lint && npm run check:copy && npm run build
```
Expected: all exit 0.

- [ ] **Step 13: Commit**

```bash
cd /home/sico/Code/Lemely/.claude/worktrees/paymob-integration
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files && graphify update .
P="web/src/lib/billingTypes.ts web/src/lib/billingAdapters.ts web/tests/unit/support/billingFixtures.ts web/src/lib/hooks/useAdminBillingApi.ts web/src/lib/adminBillingModel.ts web/src/portals/admin/screens/billing/BillingLayout.tsx web/src/portals/admin/screens/billing/ReasonedFormDialog.tsx web/src/portals/admin/screens/billing/Catalogue.tsx web/src/portals/admin/index.tsx web/src/portals/admin/data.ts web/tests/unit/adminBillingApi.test.ts web/tests/unit/adminBillingModel.test.ts web/tests/unit/adminCatalogue.test.ts web/tests/unit/adminRoutes.test.ts"
git add $P
git commit -S -m "feat(web): admin billing shell and catalogue" -- $P
```

---

### Task 14: Admin customer view with reasoned actions

**Files:**
- Modify: `web/src/lib/adminBillingModel.ts` (action field specs and bodies)
- Create: `web/src/portals/admin/screens/billing/Customers.tsx`
- Create: `web/src/portals/admin/screens/billing/PaymentActions.tsx`
- Create: `web/src/portals/admin/screens/billing/CustomerDetail.tsx`
- Modify: `web/src/portals/admin/screens/billing/BillingLayout.tsx` (`BILLING_AREAS`)
- Modify: `web/src/portals/admin/index.tsx` (index route, `customers/:userId`)
- Modify: `web/src/portals/admin/screens/Activations.tsx` (pointer to the customer view)
- Test: `web/tests/unit/adminCustomer.test.ts` (and extend `adminBillingModel.test.ts`)

**Interfaces:**
- Consumes (Task 13): `useCustomerSearch`, `useCustomer`, `useGrantCredits`,
  `useAdjustBalance`, `useForgiveDebt`, `useManualActivation`, `useExtendSubscription`,
  `useAdminCancelSubscription`, `useRefundPayment`, `useVoidPayment`, `useAdminCatalogue`,
  `ReasonedFormDialog`, `FieldSpec`, `FormValues`, `majorFromMinor`, `minorFromMajor`;
  `randomUuid` from `web/src/lib/uuid.ts`; `formatMoney`, `formatBillingDate`; types
  `CustomerDetail`, `AdminPaymentRow`, `AdminSubscription`.
- Produces: `GRANT_FIELDS`, `grantBody`, `ADJUST_FIELDS`, `adjustBody`, `FORGIVE_FIELDS`,
  `forgiveBody`, `EXTEND_FIELDS`, `extendBody`, `CANCEL_FIELDS`, `cancelBody`,
  `activationFields(tiers)`, `activationBody`, `REFUND_FIELDS`, `refundBody` in
  `adminBillingModel.ts` (Task 15 reuses `REFUND_FIELDS`, `refundBody`); screens `Customers`,
  `CustomerDetail`; `<PaymentActions payment />` from `PaymentActions.tsx` (Task 15 reuses it).

Behaviour (spec §8.2; plan 07 A32–A35): search by name, email, payment id or Paymob order id
(≥ 2 characters; fewer shows "Type at least two characters."), each hit showing what it matched
on. Detail shows the user, the balance (allowance, credits, seat and outstanding debt), every
subscription with its periods, grants with expiry and held units, debt rows, usage jobs with
estimate against actual (rows outside the range read "Outside range"), payments with their
refunds, seats, assistants and seats held with other teachers (teachers/students), parents and
children, and the audit trail. Actions, each through `ReasonedFormDialog` (reason required,
audited server-side): Grant credits (units, valid days, a fresh `requestId` per dialog so a
double submit cannot double-grant) · Adjust balance (signed units, `requestId`) · Forgive debt
(shown only with debt) · Activate manually (`POST /admin/billing/customers/{userId}/manual-
activation` with a plan tier from the catalogue and a period in days; for complimentary
accounts) · Extend subscription · Cancel subscription (`when: period_end | now`) · Refund ·
Void. The legacy Activations screen keeps working and gains a line: "Manual activation also
lives in each customer's billing view." linking to `/platform/billing`. User ids stand in for
names on payments (M9).

- [ ] **Step 1: Extend the model test (failing)**

Append to `web/tests/unit/adminBillingModel.test.ts` (merge the new names into the file's
existing import from `@/lib/adminBillingModel`):

```ts
describe("customer action bodies", () => {
  it("builds plan 07's grant, adjust, forgive, activation, extend, cancel and refund bodies", () => {
    expect(grantBody({ units: "200", validDays: "" }, "goodwill", "rq1")).toEqual({ units: 200, validDays: null, requestId: "rq1", reason: "goodwill" })
    expect(grantBody({ units: "200", validDays: "90" }, "goodwill", "rq1").validDays).toBe(90)
    expect(adjustBody({ units: "-40" }, "correction", "rq2")).toEqual({ units: -40, requestId: "rq2", reason: "correction" })
    expect(forgiveBody({ units: "" }, "forgive all")).toEqual({ units: null, reason: "forgive all" })
    expect(forgiveBody({ units: "12" }, "forgive part")).toEqual({ units: 12, reason: "forgive part" })
    expect(activationBody({ planTierId: "t1", periodDays: "30" }, "complimentary")).toEqual({ planTierId: "t1", periodDays: 30, reason: "complimentary" })
    expect(extendBody({ days: "7" }, "outage")).toEqual({ days: 7, reason: "outage" })
    expect(cancelBody({ immediate: true }, "fraud")).toEqual({ when: "now", reason: "fraud" })
    expect(cancelBody({ immediate: false }, "asked")).toEqual({ when: "period_end", reason: "asked" })
    expect(refundBody({ amountMajor: "150" }, "duplicate")).toEqual({ amountMinor: 15000, reason: "duplicate" })
    expect(refundBody({ amountMajor: "" }, "full")).toEqual({ amountMinor: null, reason: "full" })
  })
})
```

- [ ] **Step 2: Write the failing screen test**

`web/tests/unit/adminCustomer.test.ts`:

```ts
import { createElement as h } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { fx } from "./support/billingFixtures"
import { fakeMutation, okQuery, renderAt, renderStatic } from "./support/billingRender"

const s = vi.hoisted(() => ({ search: null as unknown, customer: null as unknown, catalogue: null as unknown }))
vi.mock("@/lib/hooks/useAdminBillingApi", () => ({
  useCustomerSearch: () => s.search,
  useCustomer: () => s.customer,
  useAdminCatalogue: () => s.catalogue,
  useGrantCredits: () => fakeMutation(),
  useAdjustBalance: () => fakeMutation(),
  useForgiveDebt: () => fakeMutation(),
  useManualActivation: () => fakeMutation(),
  useExtendSubscription: () => fakeMutation(),
  useAdminCancelSubscription: () => fakeMutation(),
  useRefundPayment: () => fakeMutation(),
  useVoidPayment: () => fakeMutation(),
}))

import { CustomerDetail } from "@/portals/admin/screens/billing/CustomerDetail"
import { Customers } from "@/portals/admin/screens/billing/Customers"

beforeEach(() => {
  s.search = okQuery({ hits: [{ userId: "u2", displayName: "Omar Hassan", email: "omar@example.com", role: "student", matchedOn: "email" }] })
  s.customer = okQuery(fx.customer)
  s.catalogue = okQuery(fx.adminCatalogue)
})

const detail = () => renderAt(h(CustomerDetail), "/platform/billing/customers/:userId", "/platform/billing/customers/u2")

describe("Customers", () => {
  it("links each hit to its detail page and says what matched", () => {
    const html = renderStatic(h(Customers), "/platform/billing?q=omar")
    expect(html).toContain('href="/platform/billing/customers/u2"')
    expect(html).toContain("omar@example.com")
    expect(html).toContain("Email")
  })
})

describe("CustomerDetail", () => {
  it("shows subscription, balance, debt, grants, jobs and payments", () => {
    const html = detail()
    expect(html).toContain("Omar Hassan")
    expect(html).toContain("Student Plus")
    expect(html).toContain("1,500")
    expect(html).toContain("period_allowance")
    expect(html).toContain("Outside range")
    expect(html).toContain("0.009000")
    expect(html).toContain("PM-1")
  })

  it("offers every reasoned action, forgiving debt only when there is debt", () => {
    const html = detail()
    for (const label of ["Grant credits", "Adjust balance", "Forgive debt", "Activate manually", "Extend subscription", "Cancel subscription", "Refund", "Void"]) {
      expect(html).toContain(label)
    }
    s.customer = okQuery({ ...fx.customer, balance: { ...fx.customer.balance, outstandingDebt: 0 }, debts: [] })
    expect(detail()).not.toContain("Forgive debt")
  })

  it("shows parents for a student", () => {
    expect(detail()).toContain("mona@example.com")
  })
})
```

- [ ] **Step 3: Run them to verify they fail**

Run: `npx vitest run tests/unit/adminBillingModel.test.ts tests/unit/adminCustomer.test.ts`
Expected: FAIL (missing exports and modules).

- [ ] **Step 4: Append the action specs to `web/src/lib/adminBillingModel.ts`**

```ts
export const GRANT_FIELDS: FieldSpec[] = [
  { name: "units", label: "Credits to grant", kind: "number" },
  { name: "validDays", label: "Valid for (days, empty = never expires)", kind: "number", optional: true },
]
/** `requestId` is minted once per open dialog so a double submit is one grant. */
export function grantBody(v: FormValues, reason: string, requestId: string): AdminGrantRequest {
  return { units: num(v, "units"), validDays: numOrNull(v, "validDays"), requestId, reason }
}

export const ADJUST_FIELDS: FieldSpec[] = [{ name: "units", label: "Units (negative to debit)", kind: "text" }]
export function adjustBody(v: FormValues, reason: string, requestId: string): AdminAdjustRequest {
  return { units: Math.trunc(num(v, "units")), requestId, reason }
}

export const FORGIVE_FIELDS: FieldSpec[] = [{ name: "units", label: "Units to forgive (empty = all)", kind: "number", optional: true }]
export function forgiveBody(v: FormValues, reason: string): AdminForgiveRequest {
  return { units: numOrNull(v, "units"), reason }
}

export function activationFields(tiers: { id: string; code: string; name: string }[]): FieldSpec[] {
  return [
    { name: "planTierId", label: "Plan", kind: "select", options: tiers.map((t) => ({ value: t.id, label: `${t.name} (${t.code})` })) },
    { name: "periodDays", label: "Period (days)", kind: "number" },
  ]
}
export function activationBody(v: FormValues, reason: string): ManualActivationRequest {
  return { planTierId: str(v, "planTierId"), periodDays: num(v, "periodDays"), reason }
}

export const EXTEND_FIELDS: FieldSpec[] = [{ name: "days", label: "Days to add", kind: "number" }]
export function extendBody(v: FormValues, reason: string): AdminExtendRequest {
  return { days: num(v, "days"), reason }
}

export const CANCEL_FIELDS: FieldSpec[] = [{ name: "immediate", label: "End access now instead of at period end", kind: "checkbox" }]
export function cancelBody(v: FormValues, reason: string): AdminCancelRequest {
  return { when: v.immediate === true ? "now" : "period_end", reason }
}

export const REFUND_FIELDS: FieldSpec[] = [
  { name: "amountMajor", label: "Refund amount (EGP, empty = everything refundable)", kind: "money", optional: true },
]
export function refundBody(v: FormValues, reason: string): AdminRefundRequest {
  return { amountMinor: str(v, "amountMajor") === "" ? null : minorFromMajor(str(v, "amountMajor")), reason }
}
```

Merge `AdminGrantRequest`, `AdminAdjustRequest`, `AdminForgiveRequest`,
`ManualActivationRequest`, `AdminExtendRequest`, `AdminCancelRequest`, `AdminRefundRequest` into
the file's `import type … from "@/lib/billingTypes"`. `activationFields` is a function because its plan
options come from the catalogue.

- [ ] **Step 5: Write `Customers.tsx`**

`web/src/portals/admin/screens/billing/Customers.tsx`:

```tsx
import { useState } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { ListSkeleton } from "@/components/ui/loading-shapes"
import { QueryState } from "@/components/ui/query-state"
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table"
import type { CustomerHit } from "@/lib/billingTypes"
import { useCustomerSearch } from "@/lib/hooks/useAdminBillingApi"

/* Customer search (spec §8.2): name, email, payment id or Paymob order id. The query lives in
 * the URL so a search can be shared with another admin. */

const MATCHED: Record<CustomerHit["matchedOn"], string> = {
  user_id: "User id",
  payment_id: "Payment id",
  paymob_order: "Paymob order",
  email: "Email",
  name: "Name",
}

export function Customers() {
  const [params, setParams] = useSearchParams()
  const q = params.get("q") ?? ""
  const [draft, setDraft] = useState(q)
  const search = useCustomerSearch(q)
  return (
    <div className="flex flex-col gap-4">
      <form
        className="flex flex-wrap items-end gap-3"
        onSubmit={(e) => {
          e.preventDefault()
          setParams(draft.trim() ? { q: draft.trim() } : {})
        }}
      >
        <div className="min-w-64 flex-1">
          <Input label="Find a customer" hint="Name, email, payment id or Paymob order id" value={draft} onChange={(e) => setDraft(e.target.value)} />
        </div>
        <Button type="submit" variant="primary">Search</Button>
      </form>
      {q.trim().length < 2 ? (
        <p className="m-0 text-body-sm text-on-surface-variant">Type at least two characters.</p>
      ) : (
        <QueryState
          query={search}
          skeleton={<ListSkeleton />}
          error={{ heading: "Couldn't search customers" }}
          isEmpty={(d) => d.hits.length === 0}
          empty={<p className="m-0 text-body-md text-on-surface-variant">No customer matches that search.</p>}
        >
          {(d) => (
            <Table density="operate">
              <caption className="sr-only">Customers</caption>
              <THead><TR><TH>Name</TH><TH>Email</TH><TH>Role</TH><TH>Matched on</TH></TR></THead>
              <TBody>
                {d.hits.map((c) => (
                  <TR key={c.userId}>
                    <TD>
                      <Link to={`/platform/billing/customers/${c.userId}`} className="font-medium text-primary underline-offset-2 hover:underline">
                        {c.displayName ?? c.email}
                      </Link>
                    </TD>
                    <TD>{c.email}</TD>
                    <TD>{c.role}</TD>
                    <TD>{MATCHED[c.matchedOn]}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </QueryState>
      )}
    </div>
  )
}
```

- [ ] **Step 6: Write `PaymentActions.tsx` and `CustomerDetail.tsx`**

`web/src/portals/admin/screens/billing/PaymentActions.tsx`:

```tsx
import { useState } from "react"
import { Button } from "@/components/ui/button"
import { REFUND_FIELDS, majorFromMinor, refundBody } from "@/lib/adminBillingModel"
import type { AdminPaymentRow } from "@/lib/billingTypes"
import { useRefundPayment, useVoidPayment } from "@/lib/hooks/useAdminBillingApi"
import { ReasonedFormDialog } from "./ReasonedFormDialog"

/** Refund and void for one payment (spec §6 refunds, §8.2). Shared by the customer view and
 * the payments list. */
export function PaymentActions({ payment }: { payment: AdminPaymentRow }) {
  const refund = useRefundPayment()
  const voidPayment = useVoidPayment()
  const [open, setOpen] = useState<"refund" | "void" | null>(null)
  const refundable = payment.status === "paid" || payment.status === "partially_refunded"
  if (!refundable) return null
  return (
    <>
      <Button size="sm" variant="ghost" onClick={() => setOpen("refund")} aria-label={`Refund ${payment.id}`}>Refund</Button>
      <Button size="sm" variant="ghost" onClick={() => setOpen("void")} aria-label={`Void ${payment.id}`}>Void</Button>
      {open === "refund" ? (
        <ReasonedFormDialog
          open
          onClose={() => setOpen(null)}
          title="Refund payment"
          fields={REFUND_FIELDS}
          initial={{ amountMajor: majorFromMinor(payment.amountMinor - payment.refundedMinor) }}
          submitLabel="Refund"
          mutation={refund}
          toBody={(v, r) => ({ id: payment.id, body: refundBody(v, r) })}
          note={<p className="m-0 text-body-sm text-on-surface">A refunded credit pack claws back only its unspent credits.</p>}
        />
      ) : null}
      {open === "void" ? (
        <ReasonedFormDialog
          open
          onClose={() => setOpen(null)}
          title="Void payment"
          fields={[]}
          initial={{}}
          submitLabel="Void"
          mutation={voidPayment}
          toBody={(_v, r) => ({ id: payment.id, body: { reason: r } })}
          note={<p className="m-0 text-body-sm text-on-surface">Paymob voids only same-day transactions. Use refund otherwise.</p>}
        />
      ) : null}
    </>
  )
}
```

`web/src/portals/admin/screens/billing/CustomerDetail.tsx`:

```tsx
import { useMemo, useState, type ReactNode } from "react"
import { useParams } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { PageHeaderSkeleton } from "@/components/ui/loading-shapes"
import { QueryState } from "@/components/ui/query-state"
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table"
import {
  ADJUST_FIELDS,
  CANCEL_FIELDS,
  EXTEND_FIELDS,
  FORGIVE_FIELDS,
  GRANT_FIELDS,
  activationBody,
  activationFields,
  adjustBody,
  cancelBody,
  extendBody,
  forgiveBody,
  grantBody,
} from "@/lib/adminBillingModel"
import { formatBillingDate, formatMoney } from "@/lib/billingFormat"
import type { AdminMember } from "@/lib/billingTypes"
import {
  useAdjustBalance,
  useAdminCancelSubscription,
  useAdminCatalogue,
  useCustomer,
  useExtendSubscription,
  useForgiveDebt,
  useGrantCredits,
  useManualActivation,
} from "@/lib/hooks/useAdminBillingApi"
import { randomUuid } from "@/lib/uuid"
import { PaymentActions } from "./PaymentActions"
import { ReasonedFormDialog } from "./ReasonedFormDialog"

/* One customer's whole billing picture (plan 07 `CustomerDetailDTO`) and every admin money
 * action (spec §8.2). Each action carries a reason the server audits. */

const n = (v: number) => new Intl.NumberFormat().format(v)
const d = (iso: string | null) => (iso ? formatBillingDate(iso) : "—")
const LIVE = new Set(["pending_first_payment", "active", "past_due"])

function Panel({ title, action, children }: { title: string; action?: ReactNode; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="m-0 text-display-sm text-on-surface">{title}</h2>
        {action ? <div className="flex flex-wrap gap-1">{action}</div> : null}
      </div>
      {children}
    </section>
  )
}

function Members({ title, rows }: { title: string; rows: AdminMember[] }) {
  if (rows.length === 0) return null
  return (
    <Panel title={title}>
      <ul className="m-0 flex list-none flex-col gap-1 p-0 text-body-sm text-on-surface">
        {rows.map((m) => (
          <li key={m.memberId}>
            {m.email} · {m.kind}
            {m.rolePreset ? ` (${m.rolePreset})` : ""} · {m.status}
            {m.leavesAt ? ` until ${d(m.leavesAt)}` : ""}
          </li>
        ))}
      </ul>
    </Panel>
  )
}

type Action = { kind: "grant" | "adjust" | "forgive" | "activate" } | { kind: "extend" | "cancel"; subscriptionId: string } | null

export function CustomerDetail() {
  const { userId = "" } = useParams<{ userId: string }>()
  const customer = useCustomer(userId)
  const catalogue = useAdminCatalogue()
  const grant = useGrantCredits(userId)
  const adjust = useAdjustBalance(userId)
  const forgive = useForgiveDebt(userId)
  const activate = useManualActivation(userId)
  const extend = useExtendSubscription(userId)
  const cancel = useAdminCancelSubscription(userId)
  const [action, setAction] = useState<Action>(null)
  // One idempotency key per opened grant/adjust dialog (07 `requestId`).
  const requestId = useMemo(() => (action ? randomUuid() : ""), [action])
  const close = () => setAction(null)

  return (
    <QueryState query={customer} skeleton={<PageHeaderSkeleton />} error={{ heading: "Couldn't load this customer" }}>
      {(c) => (
        <div className="flex flex-col gap-8">
          <header className="flex flex-col gap-1">
            <h2 className="m-0 text-display-md text-on-surface">{c.user.displayName ?? c.user.email}</h2>
            <p className="m-0 text-body-sm text-on-surface-variant">
              {c.user.email} · {c.user.role} · joined {d(c.user.createdAt)}
            </p>
          </header>

          <Panel
            title="Balance"
            action={
              <>
                <Button size="sm" variant="secondary" onClick={() => setAction({ kind: "grant" })}>Grant credits</Button>
                <Button size="sm" variant="secondary" onClick={() => setAction({ kind: "adjust" })}>Adjust balance</Button>
                {c.balance.outstandingDebt > 0 ? (
                  <Button size="sm" variant="secondary" onClick={() => setAction({ kind: "forgive" })}>Forgive debt</Button>
                ) : null}
              </>
            }
          >
            <dl className="m-0 grid gap-2 text-body-sm md:grid-cols-4">
              <div><dt className="text-on-surface-variant">Allowance available</dt><dd className="m-0 text-data-md">{n(c.balance.allowanceAvailable)}</dd></div>
              <div><dt className="text-on-surface-variant">Credits available</dt><dd className="m-0 text-data-md">{n(c.balance.creditsAvailable)}</dd></div>
              <div><dt className="text-on-surface-variant">Seat allowance available</dt><dd className="m-0 text-data-md">{n(c.balance.seatAvailable)}</dd></div>
              <div><dt className="text-on-surface-variant">Outstanding debt</dt><dd className="m-0 text-data-md">{n(c.balance.outstandingDebt)}</dd></div>
            </dl>
            <Table density="operate">
              <caption className="sr-only">Grants</caption>
              <THead><TR><TH>Kind</TH><TH numeric>Units</TH><TH numeric>Remaining</TH><TH numeric>Held</TH><TH>Expires</TH><TH>Seat</TH></TR></THead>
              <TBody>
                {c.grants.map((g) => (
                  <TR key={g.id}>
                    <TD><span className="text-data-sm">{g.kind}</span></TD>
                    <TD numeric>{n(g.units)}</TD><TD numeric>{n(g.remaining)}</TD><TD numeric>{n(g.held)}</TD>
                    <TD>{g.expiresAt ? d(g.expiresAt) : "Never"}</TD><TD>{g.teacherMemberId ? "Seat" : "—"}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
            {c.debts.length > 0 ? (
              <ul className="m-0 flex list-none flex-col gap-1 p-0 text-body-sm text-on-surface">
                {c.debts.map((x) => (
                  <li key={x.id}>{n(x.outstanding)} of {n(x.units)} outstanding{x.jobId ? ` from job ${x.jobId}` : ""}, {d(x.createdAt)}</li>
                ))}
              </ul>
            ) : null}
          </Panel>

          <Panel title="Subscriptions" action={<Button size="sm" variant="secondary" onClick={() => setAction({ kind: "activate" })}>Activate manually</Button>}>
            {c.subscriptions.length === 0 ? <p className="m-0 text-body-sm text-on-surface-variant">No subscription.</p> : null}
            {c.subscriptions.map((sub) => (
              <div key={sub.id} className="flex flex-col gap-2 rounded-lg border border-outline-variant p-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="m-0 text-body-md font-semibold text-on-surface">
                    {sub.planName} · {sub.status}
                    {sub.cancelAtPeriodEnd ? ", ends at period end" : ""}
                    {sub.isManuallyActivated ? ", complimentary" : ""}
                  </p>
                  {LIVE.has(sub.status) ? (
                    <div className="flex gap-1">
                      <Button size="sm" variant="secondary" onClick={() => setAction({ kind: "extend", subscriptionId: sub.id })}>Extend subscription</Button>
                      <Button size="sm" variant="secondary" onClick={() => setAction({ kind: "cancel", subscriptionId: sub.id })}>Cancel subscription</Button>
                    </div>
                  ) : null}
                </div>
                <p className="m-0 text-body-sm text-on-surface-variant">
                  {d(sub.currentPeriodStart)} to {d(sub.currentPeriodEnd)} · payer {sub.payerUserId ?? "—"} · Paymob{" "}
                  <span className="text-data-sm">{sub.paymobSubscriptionId ?? "—"}</span>
                  {sub.graceUntil ? ` · grace until ${d(sub.graceUntil)}` : ""}
                </p>
                {sub.periods.length > 0 ? (
                  <ul className="m-0 flex list-none flex-col gap-1 p-0 text-body-sm text-on-surface-variant">
                    {sub.periods.map((p) => (
                      <li key={p.periodStart}>{d(p.periodStart)} to {d(p.periodEnd)}{p.paymentId ? ` · payment ${p.paymentId}` : ""}</li>
                    ))}
                  </ul>
                ) : null}
              </div>
            ))}
          </Panel>

          <Panel title="Usage jobs">
            <Table density="operate">
              <caption className="sr-only">Usage jobs</caption>
              <THead><TR><TH>Date</TH><TH>Action</TH><TH>Status</TH><TH numeric>Estimate</TH><TH numeric>Charged</TH><TH numeric>Cost (USD)</TH><TH>Versions</TH></TR></THead>
              <TBody>
                {c.usageJobs.map((j) => (
                  <TR key={j.jobId}>
                    <TD>{d(j.createdAt)}</TD><TD>{j.action}</TD><TD>{j.status}</TD>
                    <TD numeric>{j.estimateLow}–{j.estimateHigh}</TD>
                    <TD numeric>
                      {j.charged ?? "—"}
                      {j.outsideRange ? <span className="block text-body-sm text-on-surface-variant">Outside range</span> : null}
                      {j.debtCreated ? <span className="block text-body-sm text-on-surface-variant">{j.debtCreated} into debt</span> : null}
                    </TD>
                    <TD numeric><span className="text-data-sm">{j.actualCostUsd ?? "—"}</span></TD>
                    <TD><span className="text-data-sm">rate {j.rateVersion} · est {j.estimatorVersion}</span></TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          </Panel>

          <Panel title="Payments">
            <Table density="operate">
              <caption className="sr-only">Payments</caption>
              <THead><TR><TH>Date</TH><TH>Purpose</TH><TH numeric>Amount</TH><TH>Status</TH><TH>Paymob order</TH><TH><span className="sr-only">Actions</span></TH></TR></THead>
              <TBody>
                {c.payments.map((p) => (
                  <TR key={p.id}>
                    <TD>{d(p.createdAt)}</TD><TD>{p.purpose}</TD>
                    <TD numeric>
                      {formatMoney(p.amountMinor, p.currency)}
                      {p.refundedMinor > 0 ? <span className="block text-body-sm text-on-surface-variant">refunded {formatMoney(p.refundedMinor, p.currency)}</span> : null}
                    </TD>
                    <TD>{p.status}</TD>
                    <TD><span className="text-data-sm">{p.paymobOrderId ?? "—"}</span></TD>
                    <TD><div className="flex gap-1"><PaymentActions payment={p} /></div></TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          </Panel>

          <Members title="Seats" rows={c.seats} />
          <Members title="Assistants" rows={c.assistants} />
          <Members title="Seats with teachers" rows={c.seatedWith} />
          {c.parents.length > 0 || c.children.length > 0 ? (
            <Panel title="Family">
              <ul className="m-0 flex list-none flex-col gap-1 p-0 text-body-sm text-on-surface">
                {c.parents.map((p) => <li key={p.userId}>Parent: {p.displayName ?? p.email} · {p.email}</li>)}
                {c.children.map((p) => <li key={p.userId}>Child: {p.displayName ?? p.email} · {p.email}</li>)}
              </ul>
            </Panel>
          ) : null}
          {c.audit.length > 0 ? (
            <Panel title="Audit trail">
              <ul className="m-0 flex list-none flex-col gap-1 p-0 text-body-sm text-on-surface">
                {c.audit.map((a) => <li key={a.id}>{d(a.createdAt)} · {a.action} · {a.reason}</li>)}
              </ul>
            </Panel>
          ) : null}

          {action?.kind === "grant" ? (
            <ReasonedFormDialog open onClose={close} title="Grant credits" fields={GRANT_FIELDS} initial={{ units: "", validDays: "365" }}
              submitLabel="Grant credits" mutation={grant} toBody={(v, r) => ({ id: userId, body: grantBody(v, r, requestId) })} />
          ) : null}
          {action?.kind === "adjust" ? (
            <ReasonedFormDialog open onClose={close} title="Adjust balance" fields={ADJUST_FIELDS} initial={{ units: "" }}
              submitLabel="Adjust balance" mutation={adjust} toBody={(v, r) => ({ id: userId, body: adjustBody(v, r, requestId) })} />
          ) : null}
          {action?.kind === "forgive" ? (
            <ReasonedFormDialog open onClose={close} title="Forgive debt" fields={FORGIVE_FIELDS} initial={{ units: "" }}
              submitLabel="Forgive debt" mutation={forgive} toBody={(v, r) => ({ id: userId, body: forgiveBody(v, r) })} />
          ) : null}
          {action?.kind === "activate" ? (
            <ReasonedFormDialog open onClose={close} title="Activate manually" fields={activationFields(catalogue.data?.tiers ?? [])}
              initial={{ planTierId: catalogue.data?.tiers[0]?.id ?? "", periodDays: "30" }}
              submitLabel="Activate" mutation={activate} toBody={(v, r) => ({ id: userId, body: activationBody(v, r) })}
              note={<p className="m-0 text-body-sm text-on-surface">For complimentary accounts. No payment is taken.</p>} />
          ) : null}
          {action?.kind === "extend" ? (
            <ReasonedFormDialog open onClose={close} title="Extend subscription" fields={EXTEND_FIELDS} initial={{ days: "7" }}
              submitLabel="Extend subscription" mutation={extend} toBody={(v, r) => ({ id: action.subscriptionId, body: extendBody(v, r) })} />
          ) : null}
          {action?.kind === "cancel" ? (
            <ReasonedFormDialog open onClose={close} title="Cancel subscription" fields={CANCEL_FIELDS} initial={{ immediate: false }}
              submitLabel="Cancel subscription" mutation={cancel} toBody={(v, r) => ({ id: action.subscriptionId, body: cancelBody(v, r) })} />
          ) : null}
        </div>
      )}
    </QueryState>
  )
}
```

The admin layout's `<h1>` is "Billing" (Task 13), so the customer name is an `<h2>`.

- [ ] **Step 7: Mount routes, area and the Activations pointer**

`BillingLayout.tsx`: make `BILLING_AREAS` start with
`{ to: "/platform/billing", label: "Customers", end: true },`.
`web/src/portals/admin/index.tsx`: lazies `BillingCustomers` (`./screens/billing/Customers`,
`m.Customers`) and `BillingCustomerDetail` (`./screens/billing/CustomerDetail`,
`m.CustomerDetail`); replace the billing index child with
`{ index: true, element: <BillingCustomers />, handle: { title: "Billing customers", skeleton: "list" } }`
and add
`{ path: "customers/:userId", element: <BillingCustomerDetail />, handle: { title: "Billing customer", skeleton: "page-header" } }`.
Remove the now-unused `Navigate` import if nothing else uses it.

`web/src/portals/admin/screens/Activations.tsx`: after the header's description `<p>`, add

```tsx
        <p className="max-w-prose text-body-sm text-on-surface-variant">
          Manual activation also lives in each customer's billing view.{" "}
          <Link to="/platform/billing" className="font-medium text-primary underline-offset-2 hover:underline">Open billing</Link>
        </p>
```

(import `Link` from `react-router-dom` if absent).

- [ ] **Step 8: Run the tests to verify they pass**

Run: `npx vitest run tests/unit/adminBillingModel.test.ts tests/unit/adminCustomer.test.ts tests/unit/adminCatalogue.test.ts tests/unit/adminRoutes.test.ts`
Expected: PASS.

- [ ] **Step 9: Run the frontend gate**

```bash
npm run typecheck
npx vitest run tests/unit/adminBillingModel.test.ts tests/unit/adminCustomer.test.ts tests/unit/adminCatalogue.test.ts tests/unit/adminRoutes.test.ts tests/unit/tableDensity.test.ts $SCAN
npm run lint && npm run check:copy && npm run build
```
Expected: all exit 0.

- [ ] **Step 10: Commit**

```bash
cd /home/sico/Code/Lemely/.claude/worktrees/paymob-integration
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files && graphify update .
P="web/src/lib/adminBillingModel.ts web/src/portals/admin/screens/billing/Customers.tsx web/src/portals/admin/screens/billing/PaymentActions.tsx web/src/portals/admin/screens/billing/CustomerDetail.tsx web/src/portals/admin/screens/billing/BillingLayout.tsx web/src/portals/admin/index.tsx web/src/portals/admin/screens/Activations.tsx web/tests/unit/adminBillingModel.test.ts web/tests/unit/adminCustomer.test.ts"
git add $P
git commit -S -m "feat(web): admin billing customer view with audited actions" -- $P
```

---

### Task 15: Admin payments, problem queue and health

**Files:**
- Create: `web/src/lib/adminOpsModel.ts`
- Create: `web/src/portals/admin/screens/billing/Payments.tsx`
- Create: `web/src/portals/admin/screens/billing/Health.tsx`
- Modify: `web/src/portals/admin/screens/billing/BillingLayout.tsx` (`BILLING_AREAS`)
- Modify: `web/src/portals/admin/index.tsx` (routes `payments`, `health`)
- Modify: `web/tests/unit/support/billingFixtures.ts` (`problems`, `health` fixtures)
- Test: `web/tests/unit/adminOps.test.ts`
- E2E: `web/e2e/billing-admin.spec.ts`

**Interfaces:**
- Consumes (Tasks 13, 14): `useAdminPayments`, `useProblemQueue`, `useReconcilePayment`,
  `useBillingHealth`, `ReasonedFormDialog`, `PaymentActions` (`./PaymentActions`); types
  `PaymentStatus`, `ProblemQueue`, `AdminPaymentRow`, `SweeperJobHealth`, `BillingHealth`.
- Produces: `PROBLEM_SECTIONS`, `PAYMENT_STATUS_OPTIONS`, `problemCount(queue)`,
  `webhookErrorText(health)`, `jobOutcomeText(job)`, `canReconcile(status)` from
  `adminOpsModel.ts`; screens `Payments`, `Health`.

Behaviour (spec §8.3, §8.5; plan 07 A35–A38): Payments shows the problem queue first, grouped as
plan 07 returns it: amount mismatches, payments pending over an hour (`stalePending`), missing
callbacks, HMAC failures (with the 24-hour count) and refunds needing attention; it refreshes
every minute, and "No payment problems right now." shows only after a successful load with all
lists empty. Then a filterable list (status filter, Load more while `nextCursor`) with payer and
beneficiary ids (M9), purpose, amount, status, Paymob order and transaction ids, and actions:
Reconcile (created/pending/failed; asks Paymob's transaction inquiry), Refund, Void. Health
lists every sweeper job's last finished run and outcome (`failed` in error text with
`lastError` and the consecutive-failure count; `neverRun` stated), the webhook error rate over
the window (`webhookErrorRate`, `verifiedEvents`, `hmacFailures`), mismatches, renewal failures,
subscriptions past due now, failed auto top-ups and failed extra-seat charges.

- [ ] **Step 1: Write the failing test**

Add to `web/tests/unit/support/billingFixtures.ts` (above `fx`, listed inside it):

```ts
const problems: ProblemQueue = {
  mismatches: [{ ...adminPayment, id: "pay7", status: "failed_mismatch", amountMinor: 24000, paymobOrderId: "PM-7" }],
  stalePending: [],
  missingCallbacks: [],
  hmacFailures: [{ id: "w1", kind: "transaction", reason: "bad hmac", remoteAddr: "1.2.3.4", receivedAt: "2026-11-05T07:00:00Z" }],
  hmacFailures24h: 1,
  refundsNeedingAttention: [],
}

const health: BillingHealth = {
  windowHours: 24,
  jobs: [
    { name: "billing.reconcile_pending", neverRun: false, lastStartedAt: "2026-11-05T08:00:00Z", lastFinishedAt: "2026-11-05T08:00:05Z", lastOutcome: "ok", lastResultCount: 2, lastError: null, lastSuccessAt: "2026-11-05T08:00:05Z", consecutiveFailures: 0, totalRuns: 40, totalFailures: 0 },
    { name: "usage.reconcile_balances", neverRun: false, lastStartedAt: "2026-11-05T02:00:00Z", lastFinishedAt: "2026-11-05T02:00:09Z", lastOutcome: "failed", lastResultCount: null, lastError: "drift on 2 grants", lastSuccessAt: "2026-11-04T02:00:09Z", consecutiveFailures: 1, totalRuns: 10, totalFailures: 1 },
    { name: "billing.auto_topup", neverRun: true, lastStartedAt: null, lastFinishedAt: null, lastOutcome: null, lastResultCount: null, lastError: null, lastSuccessAt: null, consecutiveFailures: 0, totalRuns: 0, totalFailures: 0 },
  ],
  verifiedEvents: 197,
  hmacFailures: 3,
  webhookErrorRate: 0.015,
  mismatches: 1,
  renewalFailureEvents: 1,
  pastDueNow: 2,
  failedAutoTopups: 0,
  failedExtraSeatCharges: 0,
}
```

`web/tests/unit/adminOps.test.ts`:

```ts
import { createElement as h } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { canReconcile, jobOutcomeText, problemCount, PROBLEM_SECTIONS, webhookErrorText } from "@/lib/adminOpsModel"
import { fx } from "./support/billingFixtures"
import { fakeMutation, okQuery, renderStatic } from "./support/billingRender"

const s = vi.hoisted(() => ({ payments: null as unknown, problems: null as unknown, health: null as unknown }))
vi.mock("@/lib/hooks/useAdminBillingApi", () => ({
  useAdminPayments: () => s.payments,
  useProblemQueue: () => s.problems,
  useBillingHealth: () => s.health,
  useReconcilePayment: () => fakeMutation(),
  useRefundPayment: () => fakeMutation(),
  useVoidPayment: () => fakeMutation(),
}))

import { Health } from "@/portals/admin/screens/billing/Health"
import { Payments } from "@/portals/admin/screens/billing/Payments"

const infinite = (pages: unknown[]) => ({ ...okQuery({ pages, pageParams: [null] }), hasNextPage: false, isFetchingNextPage: false, fetchNextPage: vi.fn() })
const emptyQueue = { mismatches: [], stalePending: [], missingCallbacks: [], hmacFailures: [], hmacFailures24h: 0, refundsNeedingAttention: [] }

beforeEach(() => {
  s.payments = infinite([{ items: [fx.adminPayment, { ...fx.adminPayment, id: "pay2", status: "pending", paidAt: null }], nextCursor: null }])
  s.problems = okQuery(fx.problems)
  s.health = okQuery(fx.health)
})

describe("ops model", () => {
  it("labels sections, counts problems and describes webhooks and jobs", () => {
    expect(PROBLEM_SECTIONS.map((x) => x.label)).toEqual([
      "Amount mismatches",
      "Pending over an hour",
      "Missing callbacks",
      "HMAC failures",
      "Refunds needing attention",
    ])
    expect(problemCount(fx.problems)).toBe(2)
    expect(problemCount(emptyQueue)).toBe(0)
    expect(webhookErrorText(fx.health)).toBe("1.5% failed (3 HMAC failures, 197 verified) in 24 hours")
    expect(webhookErrorText({ ...fx.health, webhookErrorRate: null })).toBe("No webhooks in 24 hours")
    expect(jobOutcomeText(fx.health.jobs[2])).toBe("Never run")
    expect(jobOutcomeText(fx.health.jobs[1])).toBe("Failed: drift on 2 grants (1 in a row)")
    expect(jobOutcomeText(fx.health.jobs[0])).toBe("OK")
    expect(canReconcile("pending")).toBe(true)
    expect(canReconcile("paid")).toBe(false)
  })
})

describe("Payments", () => {
  it("shows the problem queue above the list with reconcile actions", () => {
    const html = renderStatic(h(Payments))
    expect(html.indexOf("Amount mismatches")).toBeLessThan(html.indexOf("All payments"))
    expect(html).toContain("PM-7")
    expect(html).toContain("bad hmac")
    expect(html).toContain("Reconcile")
    expect(html).toContain("Refund")
  })

  it("says the queue is clear only after a successful load", () => {
    s.problems = okQuery(emptyQueue)
    expect(renderStatic(h(Payments))).toContain("No payment problems right now.")
  })
})

describe("Health", () => {
  it("lists job outcomes and failure counts", () => {
    const html = renderStatic(h(Health))
    expect(html).toContain("billing.reconcile_pending")
    expect(html).toContain("Failed: drift on 2 grants")
    expect(html).toContain("Never run")
    expect(html).toContain("1.5% failed")
    expect(html).toContain("Renewal failures")
    expect(html).toContain("Past due now")
  })
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npx vitest run tests/unit/adminOps.test.ts`
Expected: FAIL, "Failed to resolve import "@/lib/adminOpsModel"".

- [ ] **Step 3: Write `web/src/lib/adminOpsModel.ts`**

```ts
import type { AdminPaymentRow, AdminRefund, BillingHealth, PaymentStatus, ProblemQueue, SweeperJobHealth, WebhookFailure } from "@/lib/billingTypes"

/* Labels for the payments and health areas (spec §8.3, §8.5; plan 07 `ProblemQueueDTO`,
 * `BillingHealthDTO`). */

type PaymentSection = { key: "mismatches" | "stalePending" | "missingCallbacks"; label: string; rows: "payments" }
type WebhookSection = { key: "hmacFailures"; label: string; rows: "webhooks" }
type RefundSection = { key: "refundsNeedingAttention"; label: string; rows: "refunds" }

export const PROBLEM_SECTIONS: readonly (PaymentSection | WebhookSection | RefundSection)[] = [
  { key: "mismatches", label: "Amount mismatches", rows: "payments" },
  { key: "stalePending", label: "Pending over an hour", rows: "payments" },
  { key: "missingCallbacks", label: "Missing callbacks", rows: "payments" },
  { key: "hmacFailures", label: "HMAC failures", rows: "webhooks" },
  { key: "refundsNeedingAttention", label: "Refunds needing attention", rows: "refunds" },
]

export function sectionRows(q: ProblemQueue, key: (typeof PROBLEM_SECTIONS)[number]["key"]): (AdminPaymentRow | WebhookFailure | AdminRefund)[] {
  return q[key]
}

export function problemCount(q: ProblemQueue): number {
  return PROBLEM_SECTIONS.reduce((sum, s) => sum + q[s.key].length, 0)
}

export const PAYMENT_STATUS_OPTIONS: { value: PaymentStatus | ""; label: string }[] = [
  { value: "", label: "All statuses" },
  { value: "created", label: "Created" },
  { value: "pending", label: "Pending" },
  { value: "paid", label: "Paid" },
  { value: "failed", label: "Failed" },
  { value: "failed_mismatch", label: "Amount mismatch" },
  { value: "refunded", label: "Refunded" },
  { value: "partially_refunded", label: "Partly refunded" },
  { value: "voided", label: "Voided" },
]

export function canReconcile(status: PaymentStatus): boolean {
  return status === "created" || status === "pending" || status === "failed"
}

export function webhookErrorText(h: BillingHealth): string {
  if (h.webhookErrorRate === null) return `No webhooks in ${h.windowHours} hours`
  const pct = Math.round(h.webhookErrorRate * 1000) / 10
  return `${pct}% failed (${h.hmacFailures} HMAC failures, ${h.verifiedEvents} verified) in ${h.windowHours} hours`
}

export function jobOutcomeText(job: SweeperJobHealth): string {
  if (job.neverRun) return "Never run"
  if (job.lastOutcome === "failed") return `Failed${job.lastError ? `: ${job.lastError}` : ""} (${job.consecutiveFailures} in a row)`
  return "OK"
}
```

- [ ] **Step 4: Write `Payments.tsx` and `Health.tsx`**

`web/src/portals/admin/screens/billing/Payments.tsx`:

```tsx
import { useState } from "react"
import { Button } from "@/components/ui/button"
import { ListSkeleton } from "@/components/ui/loading-shapes"
import { QueryState } from "@/components/ui/query-state"
import { Select } from "@/components/ui/select"
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table"
import { canReconcile, PAYMENT_STATUS_OPTIONS, PROBLEM_SECTIONS, problemCount } from "@/lib/adminOpsModel"
import { formatBillingDate, formatMoney } from "@/lib/billingFormat"
import type { AdminPaymentRow, PaymentStatus, ProblemQueue } from "@/lib/billingTypes"
import { useAdminPayments, useProblemQueue, useReconcilePayment } from "@/lib/hooks/useAdminBillingApi"
import { PaymentActions } from "./PaymentActions"
import { ReasonedFormDialog } from "./ReasonedFormDialog"

/* Payments and the problem queue (spec §8.3). Reconcile asks Paymob's transaction inquiry for
 * the real state; it never re-charges. */

function PaymentLine({ p, onReconcile }: { p: AdminPaymentRow; onReconcile: (id: string) => void }) {
  return (
    <li className="flex flex-wrap items-center justify-between gap-2 rounded-row bg-surface-container-low px-3 py-2">
      <span className="text-data-sm text-on-surface">{p.paymobOrderId ?? p.id}</span>
      <span className="text-body-sm text-on-surface">
        {p.purpose} · {formatMoney(p.amountMinor, p.currency)} · {p.status}
      </span>
      <span className="text-body-sm text-on-surface-variant">{formatBillingDate(p.createdAt)}</span>
      <Button size="sm" variant="ghost" onClick={() => onReconcile(p.id)}>Reconcile</Button>
    </li>
  )
}

function Queue({ q, onReconcile }: { q: ProblemQueue; onReconcile: (id: string) => void }) {
  return (
    <div className="flex flex-col gap-4">
      {PROBLEM_SECTIONS.map((section) => {
        const count = q[section.key].length
        if (count === 0) return null
        return (
          <div key={section.key} className="flex flex-col gap-2">
            <h3 className="m-0 text-body-md font-semibold text-error">
              {section.label} <span className="text-data-sm">({section.key === "hmacFailures" ? q.hmacFailures24h : count})</span>
            </h3>
            <ul className="m-0 flex list-none flex-col gap-2 p-0">
              {section.key === "hmacFailures"
                ? q.hmacFailures.map((w) => (
                    <li key={w.id} className="flex flex-wrap justify-between gap-2 rounded-row bg-surface-container-low px-3 py-2 text-body-sm">
                      <span className="text-on-surface">{w.kind} · {w.reason}</span>
                      <span className="text-on-surface-variant">{w.remoteAddr ?? "—"} · {formatBillingDate(w.receivedAt)}</span>
                    </li>
                  ))
                : section.key === "refundsNeedingAttention"
                  ? q.refundsNeedingAttention.map((r) => (
                      <li key={r.id} className="flex flex-wrap justify-between gap-2 rounded-row bg-surface-container-low px-3 py-2 text-body-sm">
                        <span className="text-on-surface">{r.kind} · {formatMoney(r.amountMinor, "EGP")} · {r.status}</span>
                        <span className="text-on-surface-variant">{r.reason} · {formatBillingDate(r.updatedAt)}</span>
                      </li>
                    ))
                  : q[section.key].map((p) => <PaymentLine key={p.id} p={p} onReconcile={onReconcile} />)}
            </ul>
          </div>
        )
      })}
    </div>
  )
}

export function Payments() {
  const [status, setStatus] = useState<PaymentStatus | null>(null)
  const payments = useAdminPayments(status)
  const problems = useProblemQueue()
  const reconcile = useReconcilePayment()
  const [reconciling, setReconciling] = useState<string | null>(null)

  return (
    <div className="flex flex-col gap-8">
      <section className="flex flex-col gap-3">
        <h2 className="m-0 text-display-sm text-on-surface">Problem queue</h2>
        <QueryState
          query={problems}
          skeleton={<ListSkeleton rows={2} />}
          error={{ heading: "Couldn't load the problem queue", compact: true }}
          isEmpty={(q) => problemCount(q) === 0}
          empty={<p className="m-0 text-body-md text-on-surface-variant">No payment problems right now.</p>}
        >
          {(q) => <Queue q={q} onReconcile={setReconciling} />}
        </QueryState>
      </section>

      <section className="flex flex-col gap-3">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <h2 className="m-0 text-display-sm text-on-surface">All payments</h2>
          <div className="w-56">
            <Select label="Status" value={status ?? ""} onChange={(e) => setStatus((e.target.value || null) as PaymentStatus | null)}>
              {PAYMENT_STATUS_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </Select>
          </div>
        </div>
        <QueryState
          query={payments}
          skeleton={<ListSkeleton />}
          error={{ heading: "Couldn't load payments" }}
          isEmpty={(d) => d.pages.every((p) => p.items.length === 0)}
          empty={<p className="m-0 text-body-md text-on-surface-variant">No payments with this status.</p>}
        >
          {(d) => (
            <>
              <Table density="operate">
                <caption className="sr-only">Payments</caption>
                <THead>
                  <TR><TH>Created</TH><TH>Payer</TH><TH>For</TH><TH>Purpose</TH><TH numeric>Amount</TH><TH>Status</TH><TH>Paymob</TH><TH><span className="sr-only">Actions</span></TH></TR>
                </THead>
                <TBody>
                  {d.pages.flatMap((pg) => pg.items).map((p) => (
                    <TR key={p.id}>
                      <TD>{formatBillingDate(p.createdAt)}</TD>
                      <TD><span className="text-data-sm">{p.payerUserId}</span></TD>
                      <TD><span className="text-data-sm">{p.beneficiaryUserId}</span></TD>
                      <TD>{p.purpose}</TD>
                      <TD numeric>{formatMoney(p.amountMinor, p.currency)}</TD>
                      <TD>{p.status}</TD>
                      <TD><span className="text-data-sm">{p.paymobOrderId ?? "—"} · {p.paymobTxnId ?? "—"}</span></TD>
                      <TD>
                        <div className="flex gap-1">
                          {canReconcile(p.status) ? (
                            <Button size="sm" variant="ghost" onClick={() => setReconciling(p.id)} aria-label={`Reconcile ${p.id}`}>Reconcile</Button>
                          ) : null}
                          <PaymentActions payment={p} />
                        </div>
                      </TD>
                    </TR>
                  ))}
                </TBody>
              </Table>
              {payments.hasNextPage ? (
                <Button variant="secondary" loading={payments.isFetchingNextPage} onClick={() => void payments.fetchNextPage()}>Load more</Button>
              ) : null}
            </>
          )}
        </QueryState>
      </section>

      {reconciling ? (
        <ReasonedFormDialog
          open
          onClose={() => setReconciling(null)}
          title="Reconcile payment"
          fields={[]}
          initial={{}}
          submitLabel="Reconcile"
          mutation={reconcile}
          toBody={(_v, r) => ({ id: reconciling, body: { reason: r } })}
          note={<p className="m-0 text-body-sm text-on-surface">Asks Paymob for this payment's real state and applies it. Nothing is charged.</p>}
        />
      ) : null}
    </div>
  )
}
```

`web/src/portals/admin/screens/billing/Health.tsx`:

```tsx
import { PageHeaderSkeleton } from "@/components/ui/loading-shapes"
import { QueryState } from "@/components/ui/query-state"
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table"
import { jobOutcomeText, webhookErrorText } from "@/lib/adminOpsModel"
import { formatBillingDate } from "@/lib/billingFormat"
import { useBillingHealth } from "@/lib/hooks/useAdminBillingApi"

/* Billing health (spec §8.5): only what is recorded. A job that never ran says so. */

export function Health() {
  const health = useBillingHealth()
  return (
    <QueryState query={health} skeleton={<PageHeaderSkeleton />} error={{ heading: "Couldn't load billing health" }}>
      {(h) => (
        <div className="flex flex-col gap-6">
          <dl className="m-0 grid gap-3 text-body-sm md:grid-cols-2 lg:grid-cols-3">
            <div><dt className="text-on-surface-variant">Webhooks</dt><dd className="m-0 text-data-md">{webhookErrorText(h)}</dd></div>
            <div><dt className="text-on-surface-variant">Amount mismatches</dt><dd className="m-0 text-data-md">{h.mismatches}</dd></div>
            <div><dt className="text-on-surface-variant">Renewal failures</dt><dd className="m-0 text-data-md">{h.renewalFailureEvents}</dd></div>
            <div><dt className="text-on-surface-variant">Past due now</dt><dd className="m-0 text-data-md">{h.pastDueNow}</dd></div>
            <div><dt className="text-on-surface-variant">Failed auto top-ups</dt><dd className="m-0 text-data-md">{h.failedAutoTopups}</dd></div>
            <div><dt className="text-on-surface-variant">Failed extra-seat charges</dt><dd className="m-0 text-data-md">{h.failedExtraSeatCharges}</dd></div>
          </dl>
          <Table density="operate">
            <caption className="sr-only">Sweeper jobs</caption>
            <THead><TR><TH>Job</TH><TH>Last finished</TH><TH>Outcome</TH><TH numeric>Runs</TH></TR></THead>
            <TBody>
              {h.jobs.map((j) => (
                <TR key={j.name}>
                  <TD><span className="text-data-sm">{j.name}</span></TD>
                  <TD>{j.lastFinishedAt ? formatBillingDate(j.lastFinishedAt) : "—"}</TD>
                  <TD><span className={j.lastOutcome === "failed" ? "text-error" : "text-on-surface"}>{jobOutcomeText(j)}</span></TD>
                  <TD numeric>{j.totalRuns}</TD>
                </TR>
              ))}
            </TBody>
          </Table>
          <p className="m-0 text-body-sm text-on-surface-variant">Counts cover the last {h.windowHours} hours.</p>
        </div>
      )}
    </QueryState>
  )
}
```

- [ ] **Step 5: Mount routes and areas**

`BILLING_AREAS`: append `{ to: "/platform/billing/payments", label: "Payments" }` after
Customers and `{ to: "/platform/billing/health", label: "Health" }` at the end.
`web/src/portals/admin/index.tsx`: lazies `BillingPayments` (`./screens/billing/Payments`) and
`BillingHealth` (`./screens/billing/Health`); children
`{ path: "payments", element: <BillingPayments />, handle: { title: "Billing payments", skeleton: "list" } }`
and `{ path: "health", element: <BillingHealth />, handle: { title: "Billing health", skeleton: "page-header" } }`.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `npx vitest run tests/unit/adminOps.test.ts tests/unit/adminCustomer.test.ts tests/unit/adminRoutes.test.ts`
Expected: PASS.

- [ ] **Step 7: Write the e2e spec**

`web/e2e/billing-admin.spec.ts`:

```ts
import { test, expect } from "@playwright/test"
import { readSeed } from "./seed"

// Wire shapes: plan 07 `ProblemQueueDTO`, `AdminPaymentsPageDTO`, `AdminPaymentRowDTO`.
const stale = {
  id: "pay7", payerUserId: "u1", beneficiaryUserId: "u2", purpose: "credit_pack", status: "pending", amountMinor: 15000,
  currency: "EGP", refundedMinor: 0, paymobOrderId: "PM-7", paymobTxnId: null, planTierId: null, creditPackId: "p1",
  subscriptionId: null, seatQuantity: null, createdAt: "2026-11-05T08:00:00Z", paidAt: null, refunds: [],
}

test("a platform admin sees the problem queue and must give a reason to reconcile", async ({ page }) => {
  const admin = readSeed().tutoring.platformAdmin
  let reconcileBody: unknown = null
  await page.route("**/api/admin/billing/problems", (r) =>
    r.fulfill({ json: { mismatches: [], stalePending: [stale], missingCallbacks: [], hmacFailures: [], hmacFailures24h: 0, refundsNeedingAttention: [] } }),
  )
  await page.route("**/api/admin/billing/payments**", (r) => r.fulfill({ json: { items: [], nextCursor: null } }))
  await page.route("**/api/admin/billing/payments/pay7/reconcile", async (r) => {
    reconcileBody = r.request().postDataJSON()
    await r.fulfill({ json: { ...stale, status: "paid" } })
  })
  await page.goto("/login")
  await page.getByLabel("Email").fill(admin.email)
  await page.getByLabel("Password").fill(admin.password)
  await page.getByRole("button", { name: /sign in/i }).click()
  await expect(page).toHaveURL(/\/platform/, { timeout: 15_000 })

  await page.goto("/platform/billing/payments")
  await expect(page.getByText("Pending over an hour")).toBeVisible()
  await page.getByRole("button", { name: "Reconcile" }).first().click()
  const dialog = page.getByRole("dialog")
  await dialog.getByRole("button", { name: "Reconcile" }).click()
  await expect(dialog.getByRole("alert")).toContainText("Give a reason of at least 5 characters.")
  await dialog.getByLabel("Reason").fill("callback never arrived")
  await dialog.getByRole("button", { name: "Reconcile" }).click()
  await expect(dialog).toBeHidden()
  expect(reconcileBody).toEqual({ reason: "callback never arrived" })
})
```

(The two `payments` routes overlap; Playwright matches the most recently registered route
first, so the specific `reconcile` route registered last wins.)

- [ ] **Step 8: Run the e2e spec (local stack only)**

Run: `npx playwright test e2e/billing-admin.spec.ts`
Expected: 1 passed, or "e2e not run: local stack down" recorded.

- [ ] **Step 9: Run the frontend gate**

```bash
npm run typecheck
npx vitest run tests/unit/adminOps.test.ts tests/unit/adminCustomer.test.ts tests/unit/adminRoutes.test.ts tests/unit/tableDensity.test.ts $SCAN
npm run lint && npm run check:copy && npm run build
```
Expected: all exit 0.

- [ ] **Step 10: Commit**

```bash
cd /home/sico/Code/Lemely/.claude/worktrees/paymob-integration
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files && graphify update .
P="web/tests/unit/support/billingFixtures.ts web/src/lib/adminOpsModel.ts web/src/portals/admin/screens/billing/Payments.tsx web/src/portals/admin/screens/billing/Health.tsx web/src/portals/admin/screens/billing/BillingLayout.tsx web/src/portals/admin/index.tsx web/tests/unit/adminOps.test.ts web/e2e/billing-admin.spec.ts"
git add $P
git commit -S -m "feat(web): admin payments, problem queue and billing health" -- $P
```

---

### Task 16: Admin money and margin

**Files:**
- Create: `web/src/lib/marginModel.ts`
- Create: `web/src/portals/admin/screens/billing/Margin.tsx`
- Modify: `web/src/portals/admin/screens/billing/BillingLayout.tsx` (`BILLING_AREAS`)
- Modify: `web/src/portals/admin/index.tsx` (route `margin`)
- Modify: `web/tests/unit/support/billingFixtures.ts` (`margin` fixture)
- Test: `web/tests/unit/adminMargin.test.ts`

**Interfaces:**
- Consumes (Task 13): `useMarginReport`; `BarChart` from `web/src/components/ui/lazy-chart.tsx`;
  `ChartFrame`; `formatMoney`, `formatCredits`, `formatPercent`; type `MarginReport`.
- Produces: `marginShare(report)`, `revenueBars(report)`, `costByActionBars(report)`,
  `accuracyFlag(row)`, `defaultRange(now)` from `marginModel.ts`; screen `Margin`.

Behaviour (spec §8.4; plan 07 A37): date range (default the last 90 days, sent as whole UTC days)
→ revenue (recurring, packs, refunded, net; by purpose and by plan) against LLM cost (USD total,
and EGP plus margin when the server has a USD rate: `costMinor`/`marginMinor` are `null`
otherwise, stated as "No USD to EGP rate set"), cost by action (bar chart, USD), by plan and by
model, unattributed cost; estimate accuracy per action and estimator version (jobs, below,
above, share outside the range, mean overrun) with rows over 20% outside flagged "Retune"; and
exposure: outstanding debt with debtor count and the top debtors, users at their limits, credits
expiring unused in the next 30 days (units and owners), credits that already expired unused, and
the count and cost of expired jobs. Plan 07 has no per-month series (M10), so there is no
revenue-against-cost line over time. Figures are a plain definition strip, not metric cards
(DESIGN.md anti-reference). Every chart has an empty state with a reason and an accessible table
(the chart components provide it).

- [ ] **Step 1: Write the failing test**

Add to `web/tests/unit/support/billingFixtures.ts` (above `fx`, listed inside it):

```ts
const margin: MarginReport = {
  windowStart: "2026-08-07T00:00:00Z",
  windowEnd: "2026-11-05T23:59:59Z",
  revenue: {
    recurringMinor: 1150000,
    packsMinor: 270000,
    refundedMinor: 20000,
    netMinor: 1400000,
    byPurpose: { subscription_first: 600000, subscription_renewal: 550000, credit_pack: 270000 },
    byPlan: [{ key: "student_plus_m", minor: 600000 }],
  },
  cost: {
    totalUsd: "44.120000",
    byAction: [
      { key: "mark_paper", jobs: 420, costUsd: "38.120000" },
      { key: null, jobs: 3, costUsd: "0.400000" },
    ],
    byPlan: [{ key: "student_plus_m", jobs: 300, costUsd: "22.000000" }],
    byModel: [{ model: "claude-haiku", costUsd: "30.000000" }],
    unattributedModelUsd: "0.100000",
  },
  egpPerUsd: "50.00",
  costMinor: 220600,
  marginMinor: 1179400,
  accuracy: [
    { action: "mark_paper", estimatorVersion: 1, jobs: 420, below: 10, above: 19, shareOutside: 0.07, meanOverrunUnits: 1.8, maxOverrunUnits: 6 },
  ],
  exposure: {
    outstandingDebtUnits: 340,
    debtors: 4,
    topDebtors: [{ userId: "u9", email: "debtor@example.com", outstanding: 120 }],
    usersAtLimit: 9,
    creditsExpiring30dUnits: 4200,
    creditsExpiring30dOwners: 12,
    creditsExpiredUnusedUnits: 800,
    expiredJobs: { count: 2, costUsd: "0.420000" },
  },
}
```

`web/tests/unit/adminMargin.test.ts`:

```ts
import { createElement as h } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { accuracyFlag, costByActionBars, defaultRange, marginShare, revenueBars } from "@/lib/marginModel"
import { fx } from "./support/billingFixtures"
import { okQuery, renderStatic } from "./support/billingRender"

const s = vi.hoisted(() => ({ report: null as unknown }))
vi.mock("@/lib/hooks/useAdminBillingApi", () => ({ useMarginReport: () => s.report }))
vi.mock("@/components/ui/lazy-chart", () => ({
  BarChart: (p: { ariaLabel: string }) => h("div", { "data-chart": "bar", "aria-label": p.ariaLabel }),
}))

import { Margin } from "@/portals/admin/screens/billing/Margin"

beforeEach(() => {
  s.report = okQuery(fx.margin)
})

describe("margin model", () => {
  it("computes the margin share against net revenue, or null without an EGP cost", () => {
    expect(marginShare(fx.margin)).toBeCloseTo(1179400 / 1400000)
    expect(marginShare({ ...fx.margin, marginMinor: null })).toBeNull()
  })

  it("builds revenue bars in EGP and cost-by-action bars in USD", () => {
    expect(revenueBars(fx.margin)).toEqual([
      { label: "Recurring", value: 11500 },
      { label: "Packs", value: 2700 },
      { label: "Refunded", value: 200 },
    ])
    expect(costByActionBars(fx.margin)).toEqual([
      { label: "mark_paper", value: 38.12 },
      { label: "Unattributed", value: 0.4 },
    ])
  })

  it("flags estimators that miss too often", () => {
    expect(accuracyFlag({ ...fx.margin.accuracy[0], shareOutside: 0.25 })).toBe("Retune")
    expect(accuracyFlag(fx.margin.accuracy[0])).toBeNull()
  })

  it("defaults to the last 90 days", () => {
    expect(defaultRange(new Date("2026-11-05T12:00:00Z"))).toEqual({ from: "2026-08-07", to: "2026-11-05" })
  })
})

describe("Margin", () => {
  it("renders the figures, both charts, the tables and exposure", () => {
    const html = renderStatic(h(Margin))
    expect(html).toContain("Outstanding debt")
    expect(html).toContain("340")
    expect(html.match(/data-chart="bar"/g)?.length).toBe(2)
    expect(html).toContain("student_plus_m")
    expect(html).toContain("claude-haiku")
    expect(html).toContain("7%")
    expect(html).toContain("debtor@example.com")
  })

  it("says when there is no USD to EGP rate", () => {
    s.report = okQuery({ ...fx.margin, egpPerUsd: null, costMinor: null, marginMinor: null })
    expect(renderStatic(h(Margin))).toContain("No USD to EGP rate set")
  })
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npx vitest run tests/unit/adminMargin.test.ts`
Expected: FAIL, "Failed to resolve import "@/lib/marginModel"".

- [ ] **Step 3: Write `web/src/lib/marginModel.ts`**

```ts
import type { BarPoint } from "@/components/ui/bar-chart"
import type { MarginReport } from "@/lib/billingTypes"

/* Money and margin view models (spec §8.4; plan 07 `MarginReportDTO`). Revenue bars plot EGP
 * (major units), cost bars USD. */

export function marginShare(r: MarginReport): number | null {
  return r.marginMinor === null || r.revenue.netMinor <= 0 ? null : r.marginMinor / r.revenue.netMinor
}

export function revenueBars(r: MarginReport): BarPoint[] {
  return [
    { label: "Recurring", value: r.revenue.recurringMinor / 100 },
    { label: "Packs", value: r.revenue.packsMinor / 100 },
    { label: "Refunded", value: r.revenue.refundedMinor / 100 },
  ]
}

export function costByActionBars(r: MarginReport): BarPoint[] {
  return r.cost.byAction.map((a) => ({ label: a.key ?? "Unattributed", value: Number(a.costUsd) }))
}

export function accuracyFlag(row: MarginReport["accuracy"][number]): "Retune" | null {
  return row.shareOutside > 0.2 ? "Retune" : null
}

export function defaultRange(now: Date): { from: string; to: string } {
  const to = now.toISOString().slice(0, 10)
  const from = new Date(now.getTime() - 90 * 24 * 60 * 60 * 1000).toISOString().slice(0, 10)
  return { from, to }
}
```

- [ ] **Step 4: Write `Margin.tsx`**

`web/src/portals/admin/screens/billing/Margin.tsx`:

```tsx
import { useState } from "react"
import { ChartFrame } from "@/components/ui/chart-frame"
import { Input } from "@/components/ui/input"
import { BarChart } from "@/components/ui/lazy-chart"
import { PageHeaderSkeleton } from "@/components/ui/loading-shapes"
import { QueryState } from "@/components/ui/query-state"
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table"
import { formatCredits, formatMoney, formatPercent } from "@/lib/billingFormat"
import { useMarginReport } from "@/lib/hooks/useAdminBillingApi"
import { accuracyFlag, costByActionBars, defaultRange, marginShare, revenueBars } from "@/lib/marginModel"

/* Money and margin (spec §8.4). Revenue against LLM cost, estimate accuracy, and the standing
 * money risks. Every figure is a counted fact from the report. */

const CUR = "EGP"

export function Margin() {
  const [range, setRange] = useState(() => defaultRange(new Date()))
  const report = useMarginReport(range.from, range.to)
  const egp = (v: number) => formatMoney(Math.round(v * 100), CUR)
  const usd = (v: number) => `USD ${v.toFixed(2)}`
  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap gap-3">
        <div className="w-48"><Input label="From" type="date" value={range.from} onChange={(e) => setRange((r) => ({ ...r, from: e.target.value }))} /></div>
        <div className="w-48"><Input label="To" type="date" value={range.to} onChange={(e) => setRange((r) => ({ ...r, to: e.target.value }))} /></div>
      </div>
      <QueryState query={report} skeleton={<PageHeaderSkeleton />} error={{ heading: "Couldn't load money and margin" }}>
        {(r) => {
          const share = marginShare(r)
          return (
            <>
              <dl className="m-0 grid gap-3 text-body-sm md:grid-cols-3 lg:grid-cols-4">
                <div><dt className="text-on-surface-variant">Net revenue</dt><dd className="m-0 text-data-md">{formatMoney(r.revenue.netMinor, CUR)}</dd></div>
                <div><dt className="text-on-surface-variant">LLM cost</dt><dd className="m-0 text-data-md">USD {r.cost.totalUsd}{r.costMinor !== null ? ` · ${formatMoney(r.costMinor, CUR)}` : ""}</dd></div>
                <div>
                  <dt className="text-on-surface-variant">Margin</dt>
                  <dd className="m-0 text-data-md">
                    {r.marginMinor !== null && share !== null ? `${formatMoney(r.marginMinor, CUR)} · ${formatPercent(share)}` : "No USD to EGP rate set"}
                  </dd>
                </div>
                <div><dt className="text-on-surface-variant">Outstanding debt</dt><dd className="m-0 text-data-md">{formatCredits(r.exposure.outstandingDebtUnits)} · {r.exposure.debtors} accounts</dd></div>
                <div><dt className="text-on-surface-variant">Users at their limit</dt><dd className="m-0 text-data-md">{r.exposure.usersAtLimit}</dd></div>
                <div><dt className="text-on-surface-variant">Credits expiring unused, next 30 days</dt><dd className="m-0 text-data-md">{formatCredits(r.exposure.creditsExpiring30dUnits)} · {r.exposure.creditsExpiring30dOwners} owners</dd></div>
                <div><dt className="text-on-surface-variant">Credits expired unused</dt><dd className="m-0 text-data-md">{formatCredits(r.exposure.creditsExpiredUnusedUnits)}</dd></div>
                <div><dt className="text-on-surface-variant">Expired jobs</dt><dd className="m-0 text-data-md">{r.exposure.expiredJobs.count} · USD {r.exposure.expiredJobs.costUsd}</dd></div>
              </dl>

              <div className="grid gap-6 lg:grid-cols-2">
                <ChartFrame headingLevel={2} title="Revenue" subtitle="EGP, this range" isEmpty={r.revenue.recurringMinor + r.revenue.packsMinor === 0}
                  emptyBody="No payments in this range.">
                  <BarChart data={revenueBars(r)} formatValue={egp} ariaLabel="Revenue by kind" />
                </ChartFrame>
                <ChartFrame headingLevel={2} title="LLM cost by action" subtitle="USD" isEmpty={r.cost.byAction.length === 0}
                  emptyBody="No metered jobs settled in this range.">
                  <BarChart data={costByActionBars(r)} horizontal formatValue={usd} ariaLabel="LLM cost by action" />
                </ChartFrame>
              </div>

              <div className="grid gap-6 lg:grid-cols-3">
                <Table density="operate">
                  <caption className="text-start text-label text-on-surface">Revenue by plan</caption>
                  <THead><TR><TH>Plan</TH><TH numeric>Revenue</TH></TR></THead>
                  <TBody>
                    {r.revenue.byPlan.map((p) => (
                      <TR key={p.key}><TD><span className="text-data-sm">{p.key}</span></TD><TD numeric>{formatMoney(p.minor, CUR)}</TD></TR>
                    ))}
                  </TBody>
                </Table>
                <Table density="operate">
                  <caption className="text-start text-label text-on-surface">Cost by plan</caption>
                  <THead><TR><TH>Plan</TH><TH numeric>Jobs</TH><TH numeric>Cost (USD)</TH></TR></THead>
                  <TBody>
                    {r.cost.byPlan.map((p) => (
                      <TR key={p.key ?? "none"}><TD><span className="text-data-sm">{p.key ?? "No plan"}</span></TD><TD numeric>{p.jobs}</TD><TD numeric>{p.costUsd}</TD></TR>
                    ))}
                  </TBody>
                </Table>
                <Table density="operate">
                  <caption className="text-start text-label text-on-surface">Cost by model</caption>
                  <THead><TR><TH>Model</TH><TH numeric>Cost (USD)</TH></TR></THead>
                  <TBody>
                    {r.cost.byModel.map((m) => (
                      <TR key={m.model}><TD><span className="text-data-sm">{m.model}</span></TD><TD numeric>{m.costUsd}</TD></TR>
                    ))}
                    <TR><TD>Unattributed</TD><TD numeric>{r.cost.unattributedModelUsd}</TD></TR>
                  </TBody>
                </Table>
              </div>

              <Table density="operate">
                <caption className="text-start text-label text-on-surface">Estimate accuracy</caption>
                <THead><TR><TH>Action</TH><TH numeric>Estimator</TH><TH numeric>Jobs</TH><TH numeric>Below</TH><TH numeric>Above</TH><TH numeric>Outside range</TH><TH numeric>Mean overrun</TH><TH>Flag</TH></TR></THead>
                <TBody>
                  {r.accuracy.map((a) => (
                    <TR key={`${a.action}-${a.estimatorVersion}`}>
                      <TD>{a.action}</TD>
                      <TD numeric>v{a.estimatorVersion}</TD>
                      <TD numeric>{a.jobs}</TD>
                      <TD numeric>{a.below}</TD>
                      <TD numeric>{a.above}</TD>
                      <TD numeric>{formatPercent(a.shareOutside)}</TD>
                      <TD numeric>{a.meanOverrunUnits === null ? "—" : a.meanOverrunUnits.toFixed(1)}</TD>
                      <TD>{accuracyFlag(a) ?? ""}</TD>
                    </TR>
                  ))}
                </TBody>
              </Table>

              {r.exposure.topDebtors.length > 0 ? (
                <Table density="operate">
                  <caption className="text-start text-label text-on-surface">Top debtors</caption>
                  <THead><TR><TH>Account</TH><TH numeric>Outstanding</TH></TR></THead>
                  <TBody>
                    {r.exposure.topDebtors.map((d) => (
                      <TR key={d.userId}><TD>{d.email}</TD><TD numeric>{formatCredits(d.outstanding)}</TD></TR>
                    ))}
                  </TBody>
                </Table>
              ) : null}
            </>
          )
        }}
      </QueryState>
    </div>
  )
}
```

`ChartFrame` defaults `emptyMarginalia`; `headingLevel={2}` because the billing layout owns the
page's `<h1>`. `tests/unit/chartTheme.test.ts` (in `$SCAN`) pins how charts take their colours;
neither chart here overrides colours.

- [ ] **Step 5: Mount the route and area**

`BILLING_AREAS`: insert `{ to: "/platform/billing/margin", label: "Money and margin" }` before
Health. `web/src/portals/admin/index.tsx`: lazy `BillingMargin` (`./screens/billing/Margin`)
and child `{ path: "margin", element: <BillingMargin />, handle: { title: "Billing money and margin", skeleton: "page-header" } }`.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `npx vitest run tests/unit/adminMargin.test.ts tests/unit/adminRoutes.test.ts`
Expected: PASS.

- [ ] **Step 7: Run the full frontend gate (last task of the phase)**

```bash
npm run typecheck
npx vitest run tests/unit/adminMargin.test.ts tests/unit/adminOps.test.ts tests/unit/adminCustomer.test.ts tests/unit/adminCatalogue.test.ts tests/unit/adminBillingModel.test.ts tests/unit/adminBillingApi.test.ts tests/unit/adminRoutes.test.ts tests/unit/billingFormat.test.ts tests/unit/usageBlock.test.ts tests/unit/billingApi.test.ts tests/unit/billingAdapters.test.ts tests/unit/usageMeterModel.test.ts tests/unit/billingMeters.test.ts tests/unit/meteredGate.test.ts tests/unit/estimateRange.test.ts tests/unit/checkoutReturn.test.ts tests/unit/billingPurchase.test.ts tests/unit/billingOverview.test.ts tests/unit/parentBilling.test.ts tests/unit/usageHistory.test.ts tests/unit/autoTopup.test.ts tests/unit/studentMeteredWiring.test.ts tests/unit/teacherMeteredWiring.test.ts tests/unit/teamModel.test.ts tests/unit/teamSeats.test.ts tests/unit/assistantRoles.test.ts tests/unit/teamAssistants.test.ts tests/unit/documentMeta.test.ts tests/unit/navigation.test.ts $SCAN
npm run lint && npm run check:copy && npm run build && npm run check:installable
```
Expected: all exit 0. Then run every billing e2e spec once if the local stack is up:
`npx playwright test e2e/billing-purchase.spec.ts e2e/billing-metered-student.spec.ts e2e/billing-metered-teacher.spec.ts e2e/billing-team.spec.ts e2e/billing-admin.spec.ts`.

- [ ] **Step 8: Commit**

```bash
cd /home/sico/Code/Lemely/.claude/worktrees/paymob-integration
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files && graphify update .
P="web/tests/unit/support/billingFixtures.ts web/src/lib/marginModel.ts web/src/portals/admin/screens/billing/Margin.tsx web/src/portals/admin/screens/billing/BillingLayout.tsx web/src/portals/admin/index.tsx web/tests/unit/adminMargin.test.ts"
git add $P
git commit -S -m "feat(web): admin money and margin" -- $P
```

---

### Task 17: Public pricing page

**Files:**
- Modify: `web/src/lib/billingTypes.ts` (public catalogue wire and view types)
- Modify: `web/src/lib/billingAdapters.ts` (`toPublicCatalogue`)
- Modify: `web/src/lib/hooks/useBillingApi.ts` (`billingApi.publicCatalogue`, `usePublicCatalogue`)
- Create: `web/src/lib/pricingModel.ts`
- Create: `web/src/portals/marketing/Pricing.tsx`
- Modify: `web/src/portals/marketing/index.tsx` (`pricingRoute`)
- Modify: `web/src/routes.tsx` (`/pricing`)
- Modify: `web/src/portals/billing/PlansView.tsx` (preselect from `?plan=&interval=`)
- Modify: `web/tests/unit/documentMeta.test.ts` (`/pricing` is public with a description)
- Test: `web/tests/unit/publicPricing.test.ts`, `web/tests/unit/billingPurchase.test.ts`
  (preselect case)
- E2E: `web/e2e/billing-pricing.spec.ts`

**Interfaces:**
- Consumes (Tasks 1, 4): `request`, `featureLines`, `formatMoney`, `formatCredits`,
  `intervalLabel`, `MarketingFrame`, `PlansView`, types `Audience`, `BillingInterval`.
- Produces: types `WirePublicCatalogue`, `PublicTier`, `PublicPack`, `PublicCatalogue`;
  `toPublicCatalogue(w)`; `billingApi.publicCatalogue(audience)`,
  `usePublicCatalogue(audience)`; `chooseHref(tier)`, `signupHref(audience)`,
  `planPath(tier)`, `planPreselect(params)`, `publicCatalogueFailure(err)` from `pricingModel.ts`; screen
  `Pricing`; `pricingRoute` from the marketing portal.

Backend (plan 02, resolves M1): `GET /api/billing/public-catalogue?audience=student|teacher`, no
auth, returns `PublicCatalogueDTO {audience, planTiers: [{code, name, audience, interval |
null, priceMinor, currency, features, includedSeats | null, extraSeatPriceMinor | null}],
creditPacks: [{code, name, units, priceMinor, currency}]}`; 422 on a bad audience; 429 with
`Retry-After` when rate-limited. There are no ids, so the page never starts a checkout.

Behaviour:

- **Toggles**: Students / Teachers (`ToggleGroup`, default Students, `?audience=teacher` honoured)
  and Monthly / Yearly (default Monthly). Tiers for the chosen interval, cheapest first; teacher
  tiers show "{n} student seats included" and "Extra seats {price} each {interval}". Credit
  packs under `id="packs"`, with "Credits last 12 months from purchase."
- **Choose plan**: each tier links "Choose {name}" to
  `/login?next=/{audience}/billing/plans?plan={code}&interval={month|year}` (the `next` value
  URL-encoded; `Login` already honours `?next=` through `safeNextPath`), and under it "New to
  Lemely? Sign up" to `/signup/{audience}?next=<the same plans path>` (Task 18 makes signup carry
  `next` through email verification). Under the tiers: "New to Lemely? Create a student account"
  (or teacher) → `/signup/{audience}?next=/{audience}/billing/plans`. Packs link "Sign in to buy"
  to `/login?next=/{audience}/billing/plans#packs`.
- **Preselect** on the signed-in plans page: `PlansView` reads `?plan=` and `?interval=`; the
  interval toggle starts on `interval`, and the tier whose `code` matches is marked
  (`data-preselected="true"`, a "Selected on the pricing page" line) with its button first in
  tab order inside its card. An unknown code is ignored.
- **States**: loading skeleton; 429 → "Too many requests. Try again in {n} seconds." (from
  `retryAfter`) else "Try again in a minute."; other failures → "Couldn't load prices. Check your
  connection and try again." with Retry; empty (no tiers and no packs) → "No plans are on sale
  right now." Prices come only from the API (PRODUCT.md: no fabricated pricing).
- Marketing chrome: `MarketingFrame` (it renders the page's one `<main>`); one `<h1>` "Pricing".

- [ ] **Step 1: Write the failing tests**

`web/tests/unit/publicPricing.test.ts`:

```ts
import { createElement as h } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { ApiError } from "@/lib/api"
import { toPublicCatalogue } from "@/lib/billingAdapters"
import { chooseHref, planPath, planPreselect, publicCatalogueFailure, signupHref } from "@/lib/pricingModel"
import type { WirePublicCatalogue } from "@/lib/billingTypes"
import { errorQuery, okQuery, pendingQuery, renderStatic } from "./support/billingRender"

const wire: WirePublicCatalogue = {
  audience: "teacher",
  planTiers: [
    { code: "teacher_max_m", name: "Teacher Max", audience: "teacher", interval: "monthly", priceMinor: 150000, currency: "EGP", features: {}, includedSeats: 40, extraSeatPriceMinor: 3000 },
    { code: "teacher_pro_m", name: "Teacher Pro", audience: "teacher", interval: "monthly", priceMinor: 90000, currency: "EGP", features: { "Class analytics": true }, includedSeats: 20, extraSeatPriceMinor: 3000 },
    { code: "teacher_pro_y", name: "Teacher Pro", audience: "teacher", interval: "yearly", priceMinor: 900000, currency: "EGP", features: {}, includedSeats: 20, extraSeatPriceMinor: 30000 },
    { code: "legacy", name: "Legacy", audience: "teacher", interval: null, priceMinor: 0, currency: "EGP", features: {}, includedSeats: null, extraSeatPriceMinor: null },
  ],
  creditPacks: [{ code: "pack_500", name: "500 credits", units: 500, priceMinor: 15000, currency: "EGP" }],
}

const s = vi.hoisted(() => ({ catalogue: null as unknown }))
vi.mock("@/lib/hooks/useBillingApi", () => ({ usePublicCatalogue: () => s.catalogue }))
vi.mock("@/portals/marketing", () => ({ MarketingFrame: (p: { children: unknown }) => h("main", null, p.children as never) }))

import { Pricing } from "@/portals/marketing/Pricing"

beforeEach(() => {
  s.catalogue = okQuery(toPublicCatalogue(wire))
})

describe("toPublicCatalogue", () => {
  it("maps intervals and features and drops interval-less tiers", () => {
    const c = toPublicCatalogue(wire)
    expect(c.tiers.map((t) => t.code)).toEqual(["teacher_max_m", "teacher_pro_m", "teacher_pro_y"])
    expect(c.tiers[1]).toEqual({
      code: "teacher_pro_m", name: "Teacher Pro", audience: "teacher", interval: "month", priceMinor: 90000, currency: "EGP",
      features: ["Class analytics"], includedSeats: 20, extraSeatPriceMinor: 3000,
    })
    expect(c.packs).toEqual(wire.creditPacks)
  })
})

describe("pricing model", () => {
  it("sends Choose plan through sign-in to the plans page with the tier code", () => {
    const tier = toPublicCatalogue(wire).tiers[1]
    expect(planPath(tier)).toBe("/teacher/billing/plans?plan=teacher_pro_m&interval=month")
    expect(chooseHref(tier)).toBe(`/login?next=${encodeURIComponent(planPath(tier))}`)
    expect(signupHref("teacher", planPath(tier))).toBe(`/signup/teacher?next=${encodeURIComponent(planPath(tier))}`)
    expect(signupHref("student")).toBe(`/signup/student?next=${encodeURIComponent("/student/billing/plans")}`)
  })

  it("reads a preselection only when both parts are valid", () => {
    expect(planPreselect(new URLSearchParams("plan=teacher_pro_m&interval=year"))).toEqual({ code: "teacher_pro_m", interval: "year" })
    expect(planPreselect(new URLSearchParams("plan=teacher_pro_m"))).toEqual({ code: "teacher_pro_m", interval: null })
    expect(planPreselect(new URLSearchParams("interval=week"))).toEqual({ code: null, interval: null })
  })

  it("words a rate limit with its countdown and other failures plainly", () => {
    expect(publicCatalogueFailure(new ApiError(429, "x", undefined, 30))).toBe("Too many requests. Try again in 30 seconds.")
    expect(publicCatalogueFailure(new ApiError(429, "x"))).toBe("Too many requests. Try again in a minute.")
    expect(publicCatalogueFailure(new ApiError(0, "x"))).toBe("Couldn't load prices. Check your connection and try again.")
  })
})

describe("Pricing", () => {
  const page = (path = "/pricing") => renderStatic(h(Pricing), path)

  it("shows monthly tiers cheapest first with seats, and packs", () => {
    const html = page("/pricing?audience=teacher")
    expect(html.indexOf("Teacher Pro")).toBeLessThan(html.indexOf("Teacher Max"))
    expect(html).toContain("20 student seats included")
    expect(html).toMatch(/Extra seats EGP\s30\.00 each per month/)
    expect(html).not.toMatch(/EGP\s9,000\.00/)
    expect(html).toContain('id="packs"')
    expect(html).toContain("500 credits")
    expect(html).toContain(`href="${chooseHref(toPublicCatalogue(wire).tiers[1]).replace(/&/g, "&amp;")}"`)
    expect(html).toContain(`href="${signupHref("teacher")}"`)
    expect(html).toContain(`href="${signupHref("teacher", planPath(toPublicCatalogue(wire).tiers[1]))}"`)
  })

  it("has one h1 and the two toggles", () => {
    const html = page()
    expect(html.match(/<h1/g)?.length).toBe(1)
    expect(html).toContain('aria-label="Who is this for"')
    expect(html).toContain('aria-label="Billing interval"')
  })

  it("renders loading, rate-limit and empty states", () => {
    s.catalogue = pendingQuery()
    expect(page()).toContain('aria-label="Loading"')
    s.catalogue = errorQuery(new ApiError(429, "x", undefined, 12))
    expect(page()).toContain("Try again in 12 seconds.")
    s.catalogue = okQuery({ audience: "student", tiers: [], packs: [] })
    expect(page()).toContain("No plans are on sale right now.")
  })
})
```

Add to `web/tests/unit/billingPurchase.test.ts`, inside `describe("PlansView", …)`:

```ts
  it("preselects the tier and interval chosen on the public pricing page", () => {
    const html = renderStatic(
      h(PlansView, { audience: "student", beneficiaryId: null, paths, currentTierId: null, hasLiveSubscription: false, canManage: true, managedByName: null }),
      "/student/billing/plans?plan=student_plus_y&interval=year",
    )
    expect(html).toMatch(/EGP\s2,500\.00/)
    expect(html).toContain('data-preselected="true"')
    expect(html).toContain("Selected on the pricing page")
  })
```

- [ ] **Step 2: Run them to verify they fail**

Run: `npx vitest run tests/unit/publicPricing.test.ts tests/unit/billingPurchase.test.ts`
Expected: FAIL ("Failed to resolve import "@/lib/pricingModel"" and the preselect case).

- [ ] **Step 3: Add the types, adapter and fetcher**

Append to `web/src/lib/billingTypes.ts`:

```ts
// ── Public catalogue (plan 02, no auth) ─────────────────────────────────────

/** 02 `PublicCatalogueDTO` (`GET /billing/public-catalogue?audience=`). No ids. */
export interface WirePublicCatalogue {
  audience: Audience
  planTiers: {
    code: string
    name: string
    audience: string
    interval: "monthly" | "yearly" | null
    priceMinor: number
    currency: string
    features: Record<string, unknown>
    includedSeats: number | null
    extraSeatPriceMinor: number | null
  }[]
  creditPacks: PublicPack[]
}

export interface PublicPack {
  code: string
  name: string
  units: number
  priceMinor: number
  currency: string
}

export interface PublicTier {
  code: string
  name: string
  audience: Audience
  interval: BillingInterval
  priceMinor: number
  currency: string
  features: string[]
  includedSeats: number | null
  extraSeatPriceMinor: number | null
}

export interface PublicCatalogue {
  audience: Audience
  tiers: PublicTier[]
  packs: PublicPack[]
}
```

Append to `web/src/lib/billingAdapters.ts` (merge the type imports):

```ts
export function toPublicCatalogue(w: WirePublicCatalogue): PublicCatalogue {
  return {
    audience: w.audience,
    tiers: w.planTiers.flatMap((t): PublicTier[] =>
      t.interval === null
        ? []
        : [
            {
              code: t.code,
              name: t.name,
              audience: t.audience === "teacher" ? "teacher" : "student",
              interval: t.interval === "yearly" ? "year" : "month",
              priceMinor: t.priceMinor,
              currency: t.currency,
              features: featureLines(t.features),
              includedSeats: t.includedSeats,
              extraSeatPriceMinor: t.extraSeatPriceMinor,
            },
          ],
    ),
    packs: w.creditPacks,
  }
}
```

In `web/src/lib/hooks/useBillingApi.ts`, add to `billingApi`:

```ts
  /** No auth (plan 02). `request` still adds a bearer if a session exists; the route ignores it. */
  publicCatalogue: (audience: Audience) => request<WirePublicCatalogue>(`/billing/public-catalogue?audience=${audience}`),
```

to `billingKeys`: `publicCatalogue: (audience: Audience) => ["billing", "public-catalogue", audience] as const,`
and the hook (import `toPublicCatalogue`, `PublicCatalogue`, `WirePublicCatalogue`):

```ts
export function usePublicCatalogue(audience: Audience): UseQueryResult<PublicCatalogue, Error> {
  return useQuery({
    queryKey: billingKeys.publicCatalogue(audience),
    queryFn: () => billingApi.publicCatalogue(audience),
    select: toPublicCatalogue,
    staleTime: 5 * 60_000,
    retry: false,
  })
}
```

Add to `billingApi.test.ts`'s route list: `await billingApi.publicCatalogue("teacher")` and the
expected `["/billing/public-catalogue?audience=teacher", "GET"]` (append to both lists).

- [ ] **Step 4: Write `web/src/lib/pricingModel.ts`**

```ts
import { ApiError } from "@/lib/api"
import type { Audience, BillingInterval, PublicTier } from "@/lib/billingTypes"

/* Public pricing links and preselection. The public catalogue has no ids, so a choice travels
 * by tier code through sign-in to the signed-in plans page, which matches it by code. */

/** The signed-in plans page with this tier preselected. */
export function planPath(tier: PublicTier): string {
  return `/${tier.audience}/billing/plans?plan=${encodeURIComponent(tier.code)}&interval=${tier.interval}`
}

export function chooseHref(tier: PublicTier): string {
  return `/login?next=${encodeURIComponent(planPath(tier))}`
}

export function packsHref(audience: Audience): string {
  return `/login?next=${encodeURIComponent(`/${audience}/billing/plans#packs`)}`
}

/** Sign-up that lands on the plans page afterwards (Task 18 carries `next` through verification). */
export function signupHref(audience: Audience, next: string = `/${audience}/billing/plans`): string {
  return `/signup/${audience}?next=${encodeURIComponent(next)}`
}

export function planPreselect(params: URLSearchParams): { code: string | null; interval: BillingInterval | null } {
  const interval = params.get("interval")
  return {
    code: params.get("plan") || null,
    interval: interval === "month" || interval === "year" ? interval : null,
  }
}

export function publicCatalogueFailure(err: unknown): string {
  if (err instanceof ApiError && err.status === 429) {
    return err.retryAfter ? `Too many requests. Try again in ${err.retryAfter} seconds.` : "Too many requests. Try again in a minute."
  }
  return "Couldn't load prices. Check your connection and try again."
}
```

- [ ] **Step 5: Write `web/src/portals/marketing/Pricing.tsx`**

```tsx
import { useState } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { Card, CardBody } from "@/components/ui/card"
import { CardGridSkeleton } from "@/components/ui/loading-shapes"
import { QueryState } from "@/components/ui/query-state"
import { EmptyState } from "@/components/ui/state-views"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { formatCredits, formatMoney, intervalLabel } from "@/lib/billingFormat"
import type { Audience, BillingInterval } from "@/lib/billingTypes"
import { usePublicCatalogue } from "@/lib/hooks/useBillingApi"
import { chooseHref, packsHref, planPath, publicCatalogueFailure, signupHref } from "@/lib/pricingModel"
import { MarketingFrame } from "@/portals/marketing"

/*
 * `/pricing`: public prices from `GET /billing/public-catalogue` (plan 02, no auth). Nothing here
 * is a hard-coded number (PRODUCT.md: no fabricated pricing). Choosing a plan goes through sign-in
 * to the signed-in plans page, which preselects the tier by its code.
 */

const CTA =
  "inline-flex items-center justify-center rounded-button bg-primary px-4 py-2.5 text-label text-on-primary hover:bg-primary-hover focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary pointer-coarse:min-h-11"
const TEXT_LINK = "font-medium text-primary underline-offset-2 hover:underline pointer-coarse:min-h-11 pointer-coarse:inline-flex pointer-coarse:items-center"

export function Pricing() {
  const [params] = useSearchParams()
  const [audience, setAudience] = useState<Audience>(params.get("audience") === "teacher" ? "teacher" : "student")
  const [interval, setInterval] = useState<BillingInterval>("month")
  const catalogue = usePublicCatalogue(audience)

  return (
    <MarketingFrame>
      <div className="mx-auto flex w-full max-w-app flex-col gap-6 px-page-mobile py-12 md:px-page-desktop">
        <h1 className="m-0 text-display-lg text-on-surface">Pricing</h1>
        <div className="flex flex-wrap gap-3">
          <ToggleGroup type="single" value={audience} onValueChange={(v) => (v === "student" || v === "teacher" ? setAudience(v) : undefined)} aria-label="Who is this for">
            <ToggleGroupItem value="student">Students</ToggleGroupItem>
            <ToggleGroupItem value="teacher">Teachers</ToggleGroupItem>
          </ToggleGroup>
          <ToggleGroup type="single" value={interval} onValueChange={(v) => (v === "month" || v === "year" ? setInterval(v) : undefined)} aria-label="Billing interval">
            <ToggleGroupItem value="month">Monthly</ToggleGroupItem>
            <ToggleGroupItem value="year">Yearly</ToggleGroupItem>
          </ToggleGroup>
        </div>
        <QueryState
          query={catalogue}
          skeleton={<CardGridSkeleton count={3} />}
          error={{ heading: "Couldn't load prices", body: publicCatalogueFailure }}
          isEmpty={(c) => c.tiers.length === 0 && c.packs.length === 0}
          empty={<EmptyState heading="No plans are on sale right now." body="Check back soon." />}
        >
          {(c) => {
            const tiers = c.tiers.filter((t) => t.interval === interval).sort((a, b) => a.priceMinor - b.priceMinor)
            return (
              <>
                <section aria-labelledby="pricing-plans" className="flex flex-col gap-4">
                  <h2 id="pricing-plans" className="m-0 text-display-sm text-on-surface">Plans</h2>
                  <ul className="m-0 grid list-none gap-4 p-0 md:grid-cols-2 lg:grid-cols-3">
                    {tiers.map((tier) => (
                      <li key={tier.code}>
                        <Card className="h-full">
                          <CardBody className="flex h-full flex-col gap-3">
                            <h3 className="m-0 text-display-sm text-on-surface">{tier.name}</h3>
                            <p className="m-0">
                              <span className="text-data-lg text-on-surface">{formatMoney(tier.priceMinor, tier.currency)}</span>{" "}
                              <span className="text-body-sm text-on-surface-variant">{intervalLabel(tier.interval)}</span>
                            </p>
                            {tier.includedSeats !== null ? <p className="m-0 text-body-sm text-on-surface">{tier.includedSeats} student seats included</p> : null}
                            {tier.extraSeatPriceMinor !== null ? (
                              <p className="m-0 text-body-sm text-on-surface-variant">
                                Extra seats {formatMoney(tier.extraSeatPriceMinor, tier.currency)} each {intervalLabel(tier.interval)}
                              </p>
                            ) : null}
                            <ul className="m-0 flex flex-1 flex-col gap-1 ps-4 text-body-sm text-on-surface">
                              {tier.features.map((f) => <li key={f}>{f}</li>)}
                            </ul>
                            <Link to={chooseHref(tier)} className={CTA}>Choose {tier.name}</Link>
                            <Link to={signupHref(audience, planPath(tier))} className={TEXT_LINK}>New to Lemely? Sign up</Link>
                          </CardBody>
                        </Card>
                      </li>
                    ))}
                  </ul>
                  {tiers.length === 0 ? (
                    <p className="m-0 text-body-sm text-on-surface-variant">No {interval === "month" ? "monthly" : "yearly"} plans right now.</p>
                  ) : null}
                  <p className="m-0 text-body-sm text-on-surface-variant">
                    New to Lemely?{" "}
                    <Link to={signupHref(audience)} className={TEXT_LINK}>Create a {audience} account</Link>
                  </p>
                </section>
                <section id="packs" aria-labelledby="pricing-packs" className="flex scroll-mt-24 flex-col gap-4">
                  <h2 id="pricing-packs" className="m-0 text-display-sm text-on-surface">Credit packs</h2>
                  <p className="m-0 text-body-sm text-on-surface-variant">Credits last 12 months from purchase.</p>
                  <ul className="m-0 grid list-none gap-4 p-0 md:grid-cols-2 lg:grid-cols-3">
                    {c.packs.map((pack) => (
                      <li key={pack.code}>
                        <Card className="h-full">
                          <CardBody className="flex h-full flex-col gap-2">
                            <h3 className="m-0 text-display-xs text-on-surface">{pack.name}</h3>
                            <p className="m-0 text-data-md text-on-surface">{formatCredits(pack.units)}</p>
                            <p className="m-0 flex-1 text-body-sm text-on-surface-variant">{formatMoney(pack.priceMinor, pack.currency)}</p>
                            <Link to={packsHref(audience)} className={TEXT_LINK}>Sign in to buy</Link>
                          </CardBody>
                        </Card>
                      </li>
                    ))}
                  </ul>
                </section>
              </>
            )
          }}
        </QueryState>
      </div>
    </MarketingFrame>
  )
}
```

- [ ] **Step 6: Preselect in `PlansView.tsx`**

Import `useSearchParams` from `react-router-dom` and `planPreselect` from `@/lib/pricingModel`.
At the top of `PlansView`, replace the interval state with:

```tsx
  const [params] = useSearchParams()
  const preselect = planPreselect(params)
  const [interval, setInterval] = useState<BillingInterval>(preselect.interval ?? "month")
```

On each tier's `<Card>` add `data-preselected={tier.code === preselect.code ? "true" : undefined}`,
and directly under the tier name render:

```tsx
                          {tier.code === preselect.code ? (
                            <p className="m-0 text-body-sm font-medium text-primary">Selected on the pricing page</p>
                          ) : null}
```

- [ ] **Step 7: Register the route**

`web/src/portals/marketing/index.tsx`: lazy-import `Pricing` (`./Pricing`, `m.Pricing`) the way
`DataHandling` is loaded, and export:

```tsx
export const pricingRoute: RouteObject = {
  path: "pricing",
  element: (
    <Suspense fallback={<RouteSkeleton />}>
      <Pricing />
    </Suspense>
  ),
  /* Public, like `/data`: a visitor deciding whether to sign up most needs prices. The
   * description states the page's subject only; prices come from the live catalogue. */
  handle: {
    title: "Pricing",
    description: "Lemely plans and credit packs for students and teachers, monthly or yearly.",
    skeleton: "page-header",
  } satisfies PageMeta,
}
```

(`Pricing` renders its own `MarketingFrame`.) `web/src/routes.tsx`: import `pricingRoute` with
the other marketing exports and add `{ ...pricingRoute, path: "/pricing", errorElement },` right
after the `/data` entry. `web/tests/unit/documentMeta.test.ts`: add `"/pricing",` to
`PUBLIC_WITH_DESCRIPTION` after `"/data",`.

- [ ] **Step 8: Run the tests to verify they pass**

Run: `npx vitest run tests/unit/publicPricing.test.ts tests/unit/billingPurchase.test.ts tests/unit/billingApi.test.ts tests/unit/documentMeta.test.ts tests/unit/marketing.test.ts tests/unit/marketingContent.test.ts`
Expected: PASS.

- [ ] **Step 9: Write the e2e stub**

`web/e2e/billing-pricing.spec.ts`:

```ts
import { test, expect } from "@playwright/test"

// Wire shape: plan 02 `PublicCatalogueDTO` (no ids, no auth).
const student = {
  audience: "student",
  planTiers: [{ code: "student_plus_m", name: "Student Plus", audience: "student", interval: "monthly", priceMinor: 25000, currency: "EGP", features: { "Mark past papers": true }, includedSeats: null, extraSeatPriceMinor: null }],
  creditPacks: [{ code: "pack_500", name: "500 credits", units: 500, priceMinor: 15000, currency: "EGP" }],
}
const teacher = {
  audience: "teacher",
  planTiers: [{ code: "teacher_pro_m", name: "Teacher Pro", audience: "teacher", interval: "monthly", priceMinor: 90000, currency: "EGP", features: {}, includedSeats: 20, extraSeatPriceMinor: 3000 }],
  creditPacks: [],
}

test("public pricing switches audience and sends a choice through sign-in with the tier code", async ({ page }) => {
  await page.route("**/api/billing/public-catalogue?audience=student", (r) => r.fulfill({ json: student }))
  await page.route("**/api/billing/public-catalogue?audience=teacher", (r) => r.fulfill({ json: teacher }))
  await page.goto("/pricing")
  await expect(page.getByRole("heading", { level: 1, name: "Pricing" })).toBeVisible()
  await expect(page.getByText("Student Plus")).toBeVisible()
  await page.getByRole("radio", { name: "Teachers" }).click()
  await expect(page.getByText("20 student seats included")).toBeVisible()
  await page.getByRole("link", { name: "Choose Teacher Pro" }).click()
  await expect(page).toHaveURL(/\/login\?next=/)
  expect(decodeURIComponent(new URL(page.url()).searchParams.get("next") ?? "")).toBe(
    "/teacher/billing/plans?plan=teacher_pro_m&interval=month",
  )
})

test("a rate-limited catalogue shows the countdown", async ({ page }) => {
  await page.route("**/api/billing/public-catalogue**", (r) =>
    r.fulfill({ status: 429, headers: { "Retry-After": "20" }, json: { detail: "Too many requests" } }),
  )
  await page.goto("/pricing")
  await expect(page.getByText("Try again in 20 seconds.")).toBeVisible()
})
```

Radix single `ToggleGroup` items render `role="radio"`.

- [ ] **Step 10: Run the e2e spec (local stack only)**

Run: `npx playwright test e2e/billing-pricing.spec.ts`
Expected: 2 passed, or "e2e not run: local stack down" recorded.

- [ ] **Step 11: Run the frontend gate**

```bash
npm run typecheck
npx vitest run tests/unit/publicPricing.test.ts tests/unit/billingPurchase.test.ts tests/unit/billingApi.test.ts tests/unit/documentMeta.test.ts tests/unit/marketing.test.ts tests/unit/marketingContent.test.ts tests/unit/marketingCardPadding.test.ts tests/unit/robotsTxt.test.ts $SCAN
npm run lint && npm run check:copy && npm run build && npm run check:installable
```
Expected: all exit 0.

- [ ] **Step 12: Commit**

```bash
cd /home/sico/Code/Lemely/.claude/worktrees/paymob-integration
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files && graphify update .
P="web/src/lib/billingTypes.ts web/src/lib/billingAdapters.ts web/src/lib/hooks/useBillingApi.ts web/src/lib/pricingModel.ts web/src/portals/marketing/Pricing.tsx web/src/portals/marketing/index.tsx web/src/routes.tsx web/src/portals/billing/PlansView.tsx web/tests/unit/documentMeta.test.ts web/tests/unit/publicPricing.test.ts web/tests/unit/billingPurchase.test.ts web/tests/unit/billingApi.test.ts web/e2e/billing-pricing.spec.ts"
git add $P
git commit -S -m "feat(web): public pricing page with plan preselect" -- $P
```

---

### Task 18: Carry `next` through sign-up and email verification

**Files:**
- Create: `web/src/lib/auth/signupNext.ts`
- Modify: `web/src/portals/auth/SignupDetails.tsx` (read and remember `next`)
- Modify: `web/src/portals/auth/SignupRoleSelect.tsx` (pass `next` on to the role pages)
- Modify: `web/src/portals/auth/VerifyEmail.tsx` (use the remembered `next` after verifying)
- Test: `web/tests/unit/signupNext.test.ts`, `web/tests/unit/signupNextWiring.test.ts`

**Interfaces:**
- Consumes: `safeNextPath(raw)`, `withNext(base, next)` from `web/src/lib/nextPath.ts` (what
  `Login` already uses); `portalPathForRole(role)` from `web/src/lib/auth/RequireAuth.tsx` (what
  `postVerifyPath` returns);
  Task 17's `signupHref(audience, next)`.
- Produces: `rememberSignupNext(next, storage?)`, `takeSignupNext(storage?)`,
  `afterVerifyPath(session, storage?)` from `signupNext.ts`.

How the flow works today (read in the source): `/signup` (role select) links to
`/signup/student|teacher`; `SignupDetails` creates the account and navigates to
`/verify-email`; there the user either types the emailed code (`SignedInPending`) or opens the
emailed link `/verify-email/:token` (`ConfirmScreen`); both then navigate to
`postVerifyPath(session)` (the role's portal home).

Behaviour:

- `SignupDetails` reads `next` from its URL with `safeNextPath` (same-origin relative paths only:
  `//evil.example`, `/\evil`, `https://…` and anything without a leading `/` are rejected). On a
  successful sign-up it stores the validated value with `rememberSignupNext` before navigating
  to `/verify-email`; a missing or rejected `next` clears any stale value.
- Both verification paths (typed code and emailed link) navigate to `afterVerifyPath(session)`:
  the remembered `next`, re-validated, consumed once; otherwise `postVerifyPath(session)`, which
  keeps today's behaviour exactly.
- `SignupRoleSelect` forwards a valid `next` to `/signup/student?next=…` and
  `/signup/teacher?next=…` (`withNext`).
- Storage is `localStorage`, so the emailed link works when opened in another tab of the same
  browser. The value is dropped after one use and whenever a different `next` is remembered.
- A new student's portal may still route through its onboarding gate after landing on `next`;
  that is the gate's existing behaviour and is not changed here.

**Backend check (flag):** the verification email's link (`/verify-email/:token`) is built by
the backend auth service, which carries no `next`. This task stays frontend-only, so the choice
survives verification **in the same browser**. If the emailed link is opened on another device,
the user lands on their portal home as today and finds the plan from there. Making that
cross-device case carry the plan would need the backend to append a validated `next` to the
emailed link; that is not requested here.

- [ ] **Step 1: Write the failing tests**

`web/tests/unit/signupNext.test.ts`:

```ts
import { describe, expect, it } from "vitest"
import { afterVerifyPath, rememberSignupNext, takeSignupNext } from "@/lib/auth/signupNext"

function memoryStorage(): Storage {
  const m = new Map<string, string>()
  return {
    get length() {
      return m.size
    },
    clear: () => m.clear(),
    getItem: (k) => m.get(k) ?? null,
    key: (i) => [...m.keys()][i] ?? null,
    removeItem: (k) => void m.delete(k),
    setItem: (k, v) => void m.set(k, v),
  }
}

const plans = "/teacher/billing/plans?plan=teacher_pro_m&interval=month"

describe("signup next", () => {
  it("honours a valid same-origin next once, after verification", () => {
    const s = memoryStorage()
    rememberSignupNext(plans, s)
    expect(afterVerifyPath({ role: "teacher" }, s)).toBe(plans)
    expect(afterVerifyPath({ role: "teacher" }, s)).toBe("/teacher")
  })

  it("rejects external, protocol-relative and absolute next values", () => {
    for (const bad of ["https://evil.example/x", "//evil.example/x", "/\\evil.example", "evil", ""]) {
      const s = memoryStorage()
      rememberSignupNext(bad, s)
      expect(takeSignupNext(s)).toBeNull()
    }
  })

  it("keeps today's behaviour with no next, and a new signup clears a stale one", () => {
    const s = memoryStorage()
    expect(afterVerifyPath({ role: "student" }, s)).toBe("/student")
    rememberSignupNext(plans, s)
    rememberSignupNext(null, s)
    expect(takeSignupNext(s)).toBeNull()
    expect(afterVerifyPath(null, s)).toBe("/login")
  })

  it("re-validates on read, so a tampered stored value is ignored", () => {
    const s = memoryStorage()
    s.setItem("lemely.signup.next", "//evil.example")
    expect(takeSignupNext(s)).toBeNull()
  })
})
```

(`/teacher` and `/student` are the portal homes `portalPathForRole` returns, the same targets
`postVerifyPath` uses today.)

`web/tests/unit/signupNextWiring.test.ts` (source wiring, like `selfReviewPanelWiring.test.ts`;
these screens are covered end to end by `e2e/signup.spec.ts`):

```ts
import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"
import { stripComments } from "./support/jsxSource"

const ROOT = join(import.meta.dirname, "..", "..")
const read = (p: string) => stripComments(readFileSync(join(ROOT, p), "utf8"))

describe("signup carries next", () => {
  it("SignupDetails validates next with safeNextPath and remembers it on success", () => {
    const src = read("src/portals/auth/SignupDetails.tsx")
    expect(src).toContain('safeNextPath(searchParams.get("next"))')
    expect(src).toContain("rememberSignupNext(next)")
  })

  it("both verification paths use afterVerifyPath instead of postVerifyPath", () => {
    const src = read("src/portals/auth/VerifyEmail.tsx")
    expect(src.match(/navigate\(afterVerifyPath\(session\), \{ replace: true \}\)/g)?.length).toBe(2)
    expect(src).not.toContain("navigate(postVerifyPath(session)")
  })

  it("the role picker forwards a valid next", () => {
    const src = read("src/portals/auth/SignupRoleSelect.tsx")
    expect(src).toContain('safeNextPath(searchParams.get("next"))')
    expect(src).toContain("withNext(choice.to, next)")
  })
})
```

- [ ] **Step 2: Run them to verify they fail**

Run: `npx vitest run tests/unit/signupNext.test.ts tests/unit/signupNextWiring.test.ts`
Expected: FAIL ("Failed to resolve import "@/lib/auth/signupNext"" and the wiring assertions).

- [ ] **Step 3: Write `web/src/lib/auth/signupNext.ts`**

```ts
import { portalPathForRole } from "@/lib/auth/RequireAuth"
import type { Session } from "@/lib/auth/storage"
import { safeNextPath } from "@/lib/nextPath"

/*
 * Where to go after a new account is verified (e.g. the plan chosen on `/pricing`). Sign-up and
 * verification are separate screens, and the emailed link may open in another tab, so the
 * validated `next` is kept in localStorage for one use. It is validated with `safeNextPath` on
 * the way in and again on the way out, so a tampered value never navigates off-origin.
 */

const KEY = "lemely.signup.next"

function store(): Storage | null {
  return typeof localStorage === "undefined" ? null : localStorage
}

/** Remember a validated `next`, or clear any stale one when it is missing or rejected. */
export function rememberSignupNext(next: string | null, storage: Storage | null = store()): void {
  const safe = safeNextPath(next)
  if (safe) storage?.setItem(KEY, safe)
  else storage?.removeItem(KEY)
}

/** Read and drop the remembered `next`. */
export function takeSignupNext(storage: Storage | null = store()): string | null {
  const raw = storage?.getItem(KEY) ?? null
  storage?.removeItem(KEY)
  return safeNextPath(raw)
}

/** After verification: the remembered `next`, else today's target (`postVerifyPath`'s rule:
 * `/login` without a session, the role's portal home with one). */
export function afterVerifyPath(session: Pick<Session, "role"> | null, storage: Storage | null = store()): string {
  if (!session) return "/login"
  return takeSignupNext(storage) ?? portalPathForRole(session.role)
}
```

- [ ] **Step 4: Wire the three screens**

`web/src/portals/auth/SignupDetails.tsx`: import `safeNextPath` from `@/lib/nextPath` and
`rememberSignupNext` from `@/lib/auth/signupNext`. Next to `const inviteCode =
searchParams.get("code")` add `const next = safeNextPath(searchParams.get("next"))`. In
`signup.mutate`'s `onSuccess`, as its first statement: `rememberSignupNext(next)`.

`web/src/portals/auth/VerifyEmail.tsx`: import `afterVerifyPath` from `@/lib/auth/signupNext`;
replace both `navigate(postVerifyPath(session), { replace: true })` calls (the typed-code path
in `SignedInPending` and `ConfirmScreen`) with `navigate(afterVerifyPath(session), { replace:
true })`. Remove the `postVerifyPath` import if nothing else uses it.

`web/src/portals/auth/SignupRoleSelect.tsx`: import `useSearchParams` from `react-router-dom` and
`safeNextPath`, `withNext` from `@/lib/nextPath`. In `SignupRoleSelect`, add `const [searchParams]
= useSearchParams()` and `const next = safeNextPath(searchParams.get("next"))`, and render
`<RoleChoiceLink key={choice.to} {...choice} to={withNext(choice.to, next)} />`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `npx vitest run tests/unit/signupNext.test.ts tests/unit/signupNextWiring.test.ts tests/unit/signup.test.ts tests/unit/verifyEmail.test.ts tests/unit/nextPath.test.ts tests/unit/postLoginTarget.test.ts tests/unit/authInputAttributes.test.ts`
Expected: PASS.

- [ ] **Step 6: Extend the pricing e2e (local stack only)**

Append to `web/e2e/billing-pricing.spec.ts`:

```ts
test("the pricing page's sign-up link carries the chosen plan as next", async ({ page }) => {
  await page.route("**/api/billing/public-catalogue?audience=student", (r) => r.fulfill({ json: student }))
  await page.goto("/pricing")
  await page.getByRole("link", { name: "New to Lemely? Sign up" }).first().click()
  await expect(page).toHaveURL(/\/signup\/student\?next=/)
  expect(new URL(page.url()).searchParams.get("next")).toBe("/student/billing/plans?plan=student_plus_m&interval=month")
})
```

Run: `npx playwright test e2e/billing-pricing.spec.ts e2e/signup.spec.ts`
Expected: all pass (`signup.spec.ts` unchanged, proving the no-`next` path), or "e2e not run:
local stack down" recorded.

- [ ] **Step 7: Run the frontend gate**

```bash
npm run typecheck
npx vitest run tests/unit/signupNext.test.ts tests/unit/signupNextWiring.test.ts tests/unit/signup.test.ts tests/unit/verifyEmail.test.ts tests/unit/nextPath.test.ts tests/unit/postLoginTarget.test.ts $SCAN
npm run lint && npm run check:copy && npm run build && npm run check:installable
```
Expected: all exit 0.

- [ ] **Step 8: Commit**

```bash
cd /home/sico/Code/Lemely/.claude/worktrees/paymob-integration
/home/sico/Code/Lemely/.venv/bin/pre-commit run --all-files && graphify update .
P="web/src/lib/auth/signupNext.ts web/src/portals/auth/SignupDetails.tsx web/src/portals/auth/SignupRoleSelect.tsx web/src/portals/auth/VerifyEmail.tsx web/tests/unit/signupNext.test.ts web/tests/unit/signupNextWiring.test.ts web/e2e/billing-pricing.spec.ts"
git add $P
git commit -S -m "feat(web): carry next through sign-up and email verification" -- $P
```

---

## Self-review (completed while writing)

- **Spec coverage.** §2.1 plans/credits/parent payer → Tasks 4–8; free start and signup credits
  appear as balance and catalogue data (Tasks 2, 13). §2.2 seats (included/extra, scope,
  per-subject routing via server-side subject, `study_plan` off by default, per-seat cap,
  month-end removal) → Task 11; class-code seat claim is backend-only (Phase 03) and surfaces
  as the seat list. §2.3 assistants (free, invite-only, presets + toggles, cap, billing never a
  permission) → Task 12. §2.4 estimate before every metered action, 402 handling, debt,
  failed jobs free, usage history without receipts → Tasks 3, 7, 9, 10. §2.5 receipts for money
  only → Task 7. §2.6 upgrade now / downgrade and cancel at period end / grace → Task 5.
  §5.1 step 5 return page polling → Task 4. §5.5 auto top-up → Task 8. §8 admin areas 1–5 →
  Tasks 13–16, Activations kept and pointed at the customer view → Task 14.
- **Placeholder scan.** No TBD/TODO; every code step has code; no "similar to Task N".
- **Type consistency.** Hook, model and component names are produced in the task that writes
  them and consumed under the same names later (`useMeteredGate`/`MeteredGate.captureError`,
  `PaymentProgress`, `ReasonedFormDialog`, `PaymentActions`, `BILLING_AREAS`,
  `billingPaths().packs`).
- **Reconciled against plans 02–07 (index R1, R3).** Paths, request bodies and response shapes
  follow the backend plans; wire types copy their models and adapters isolate the renames.
  Re-check at execution (Task 1 Step 1, Task 11 Step 0, Task 13 Step 0): the R3 routes' landed
  DTOs (summary, quotes, cards, invites), `SEAT_ACTIONS` against Phase 04's `ACTION_SPECS`, and
  the open items in "API assumptions" (M2–M4, M6, M9–M12).

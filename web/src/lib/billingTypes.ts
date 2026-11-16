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
  /** Credits an upgrade or seat payment became when its effect was void at settle time; else null. */
  creditedUnits: number | null
  /** What a paid upgrade or seat payment came to; null for other purposes and before it is paid. */
  outcome: PaymentOutcome | null
  /** Why an upgrade or seat payment was voided, credited or not; null otherwise. */
  voidReason: PaymentVoidReason | null
}

/** `outcome` on `GET /billing/payments/{id}`. */
export type PaymentOutcome = "applied" | "credited" | "needs_attention"

/** `voidReason` on `GET /billing/payments/{id}`: the nine reasons the backend can stamp. */
export type PaymentVoidReason =
  | "plan_ended"
  | "period_rolled"
  | "superseded"
  | "not_an_upgrade_now"
  | "seats_changing"
  | "seats_over_limit"
  | "seats_not_sold"
  | "period_ended"
  | "seats_dropped"

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

/**
 * A tier as a held subscription shows it. Unlike a sellable `PlanTier`, a legacy manual plan
 * has no billing interval and a tier of an unrecognised audience is never relabelled, so both
 * are nullable here.
 */
export interface HeldPlanTier extends Omit<PlanTier, "audience" | "interval"> {
  audience: Audience | null
  interval: BillingInterval | null
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
  tier: HeldPlanTier
  currentPeriodStart: string | null
  currentPeriodEnd: string | null
  cancelAtPeriodEnd: boolean
  /** A scheduled downgrade, applied at `currentPeriodEnd`. */
  pendingTier: HeldPlanTier | null
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
  /** `audience` is `null` when the backend sent a value that is not student or teacher. */
  beneficiary: { userId: string; displayName: string | null; audience: Audience | null }
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
  joinedAt: string
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
  /** False while the lead holds school data: assistants cannot act for that lead until that changes. */
  available: boolean
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
  features: Record<string, unknown>
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
  features: Record<string, unknown>
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
  /** The server's drift verdict, kept so the screen can tell "not checked" from "differs". */
  driftState: PaymobDrift
  /**
   * The tier's whole `features` object as stored. `features` above is only its `true` lines; an
   * edit must send the rest back untouched (the update replaces the dict).
   */
  rawFeatures: Record<string, unknown>
}

export interface FreeAllowances {
  /** `null` while the signup pack does not exist yet (nothing has set it). */
  studentSignupUnits: number | null
  teacherSignupUnits: number | null
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

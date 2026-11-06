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

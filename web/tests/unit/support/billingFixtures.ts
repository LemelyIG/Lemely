import type {
  AdminCatalogue,
  BillingSettings,
  CreditRate,
  LlmModelPrice,
  AdminPaymentRow,
  AssistantRow,
  AutoTopupSettings,
  BillingHealth,
  BillingSummary,
  Catalogue,
  CustomerDetail,
  EstimateResponse,
  MarginReport,
  PaymentStatusView,
  PlanTier,
  ProblemQueue,
  Receipt,
  SeatRow,
  SubscriptionView,
  TeamView,
  UsageHistoryPage,
  UsageJobRow,
  UsageMeterView,
  WireAssistant,
  WireBillingSummary,
  WireSeat,
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
  pendingTermsChange: null,
  cancelReason: null,
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
  creditedUnits: null,
  outcome: null,
  voidReason: null,
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
  creditValidityMonths: 12,
  tiers: [studentMonthly, studentYearly],
  packs: [{ id: "p1", code: "pack_500", name: "500 credits", units: 500, priceMinor: 15000, currency: "EGP" }],
}
const teacherCatalogue: Catalogue = { audience: "teacher", creditValidityMonths: 12, tiers: [teacherMonthly, teacherMax], packs: studentCatalogue.packs }

const history: UsageHistoryPage = { jobs: [job], nextCursor: null }

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
  joinedAt: "2026-10-12T09:00:00Z",
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
    pendingTermsChange: null,
    cancelReason: null,
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

const adminCatalogue: AdminCatalogue = {
  subscriptionAmountUpdatable: true,
  priceChangeNoticeDays: 30,
  tiers: [
    {
      id: "t-s-m", code: "student_plus_m", name: "Student Plus", audience: "student", interval: "month", priceMinor: 25000,
      currency: "EGP", allowanceUnits: 4000, includedSeats: null, seatAllowanceUnits: null, extraSeatPriceMinor: null,
      features: ["Mark past papers", "Study plans"], isActive: true, version: 4, termsVersion: 2, liveSubscriptionCount: 14, pendingMoves: 3, paymobPlanId: 77, drift: null,
      driftState: "in_sync",
      rawFeatures: { "Mark past papers": true, "Study plans": true },
    },
  ],
  packs: [{ id: "p1", code: "pack_500", name: "500 credits", units: 500, priceMinor: 15000, currency: "EGP", isActive: true, version: 2, autoTopupCount: 6, autoTopupCapBelowPriceCount: 0 }],
  rates: [{ id: "r1", version: 1, action: "mark_paper", unitsPerUsd: 1000, effectiveFrom: "2026-11-01T00:00:00Z" }],
  estimators: [
    { id: "e1", version: 1, action: "mark_paper", inputKind: "none", baseLow: 2, baseHigh: 4, perInputLow: 0, perInputHigh: 0, effectiveFrom: "2026-11-01T00:00:00Z" },
  ],
  freeAllowances: {
    studentSignupUnits: 300,
    teacherSignupUnits: 1000,
    studentSignupExpiryDays: null,
    teacherSignupExpiryDays: 30,
    studentVersion: 2,
    teacherVersion: 3,
  },
}

const billingSettings: BillingSettings = {
  creditValidityMonths: 12,
  graceDays: 3,
  maxExtraSeats: 200,
  priceChangeNoticeDays: 30,
  marginEgpPerUsd: "50",
  codeExecutionUsdPerHour: null,
  version: 4,
  updatedAt: "2026-11-12T09:30:00Z",
  updatedBy: "3f2a91c4-0000-4000-8000-000000000001",
}

const creditRate: CreditRate = {
  currency: "EGP",
  unitsPerMinor: "12.500000",
  version: 2,
  updatedAt: "2026-11-12T09:30:00Z",
  updatedBy: "3f2a91c4-0000-4000-8000-000000000001",
}

const noCache = { cachedInputUsdPerMtok: null, cacheWrite5mUsdPerMtok: null, cacheWrite1hUsdPerMtok: null }
const noTier = { tierThresholdTokens: null, tier2InputUsdPerMtok: null, tier2OutputUsdPerMtok: null }
const CLAUDE_SOURCE = "https://platform.claude.com/docs/en/about-claude/pricing"
const GEMINI_SOURCE = "built-in table, lemely.io.gemini"

/**
 * Shaped like the backend's `GET /llm-prices`: the one tiered code row is `claude-haiku-5-5`
 * (100k tokens, cache rates present, normalised strings); Gemini rows are flat and read from the
 * built-in table; a model the code does not price has no `codeDefault`.
 */
const llmModels: LlmModelPrice[] = [
  {
    model: "claude-haiku-5-5",
    provider: "anthropic",
    codeDefault: {
      inputUsdPerMtok: "0.1",
      outputUsdPerMtok: "0.5",
      cachedInputUsdPerMtok: "0.01",
      cacheWrite5mUsdPerMtok: "0.125",
      cacheWrite1hUsdPerMtok: "0.2",
      tiered: true,
      tierThresholdTokens: 100000,
      tier2InputUsdPerMtok: "0.5",
      tier2OutputUsdPerMtok: "2.5",
      source: CLAUDE_SOURCE,
      readOn: "2026-10-19",
    },
    override: null,
    seenInLast30Days: true,
  },
  {
    model: "gemini-2.5-flash",
    provider: "gemini",
    codeDefault: { inputUsdPerMtok: "0.3", outputUsdPerMtok: "2.5", cachedInputUsdPerMtok: "0.03", cacheWrite5mUsdPerMtok: null, cacheWrite1hUsdPerMtok: null, tiered: false, ...noTier, source: GEMINI_SOURCE, readOn: null },
    override: {
      model: "gemini-2.5-flash",
      inputUsdPerMtok: "0.250000",
      outputUsdPerMtok: "2.200000",
      ...noCache,
      ...noTier,
      version: 3,
      updatedAt: "2026-11-12T09:30:00Z",
      updatedBy: "3f2a91c4-0000-4000-8000-000000000001",
    },
    seenInLast30Days: false,
  },
  { model: "gemini-3-pro-preview", provider: "gemini", codeDefault: null, override: null, seenInLast30Days: true },
  { model: "claude-future-x", provider: "anthropic", codeDefault: null, override: null, seenInLast30Days: false },
]

const adminPayment: AdminPaymentRow = {
  id: "pay1", payerUserId: "u1", beneficiaryUserId: "u2", purpose: "subscription_first", status: "paid", amountMinor: 25000,
  currency: "EGP", refundedMinor: 0, convertedToCredits: false, creditedUnits: null, paymobOrderId: "PM-1", paymobTxnId: "TX-1", planTierId: "t-s-m", creditPackId: null,
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
  egpPerUsd: "50",
  egpPerUsdSource: "settings",
  costMinor: 220600,
  marginMinor: 1179400,
  accuracy: [{ action: "mark_paper", estimatorVersion: 1, jobs: 420, below: 10, above: 19, shareOutside: 0.07, meanOverrunUnits: 1.8, maxOverrunUnits: 6 }],
  exposure: {
    outstandingDebtUnits: 340,
    debtors: 4,
    topDebtors: [{ userId: "u9", email: "debtor@example.com", outstanding: 120 }],
    usersAtLimit: 9,
    creditsExpiring30dUnits: 4200,
    creditsExpiring30dOwners: 12,
    creditsExpiredUnusedUnits: 800,
    expiredJobs: { count: 2 },
  },
}

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
  wireSeat,
  seat,
  wireAssistant,
  assistant,
  wireTeacherSummary,
  team,
  studentCatalogue,
  teacherCatalogue,
  adminCatalogue,
  billingSettings,
  creditRate,
  llmModels,
  adminPayment,
  customer,
  problems,
  health,
  margin,
}

import type {
  AssistantRow,
  AutoTopupSettings,
  BillingSummary,
  Catalogue,
  EstimateResponse,
  PaymentStatusView,
  PlanTier,
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
}

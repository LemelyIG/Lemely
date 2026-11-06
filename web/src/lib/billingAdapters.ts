import { isLiveSubscription } from "@/lib/billingFormat"
import {
  TEAM_PERMISSIONS,
  USAGE_BLOCK_REASONS,
  type AdminCatalogue,
  type AssistantRow,
  type AutoTopupSettings,
  type BillingInterval,
  type BillingSummary,
  type Catalogue,
  type Audience,
  type CreditPack,
  type EstimateResponse,
  type HeldPlanTier,
  type MeteredAction,
  type PaymobDrift,
  type PlanTier,
  type SeatRow,
  type SavedCardView,
  type TeamPermission,
  type TeamView,
  type UsageBlockReason,
  type UsageJobRow,
  type UsageJobStatus,
  type UsageMeterView,
  type WireAdminCatalogue,
  type WireAssistant,
  type WireAssistantInvite,
  type WireAutoTopup,
  type WireBillingSummary,
  type WireCatalogue,
  type WireCreditPack,
  type WireEstimate,
  type WirePlanTier,
  type WireSavedCard,
  type WireSeat,
  type WireSeatCapacity,
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

function toAudience(value: string): Audience | null {
  return value === "student" || value === "teacher" ? value : null
}

function toInterval(value: string | null): BillingInterval | null {
  return value === "monthly" ? "month" : value === "yearly" ? "year" : null
}

/** A tier as a held subscription shows it: never dropped, never relabelled. */
export function toHeldTier(w: WirePlanTier): HeldPlanTier {
  const audience = toAudience(w.audience)
  const teacher = audience === "teacher"
  return {
    id: w.planTierId,
    code: w.code,
    name: w.name,
    audience,
    interval: toInterval(w.interval),
    priceMinor: w.priceMinor,
    currency: w.currency,
    features: featureLines(w.features),
    includedSeats: teacher ? w.includedSeats : null,
    extraSeatPriceMinor: teacher ? w.extraSeatPriceMinor : null,
  }
}

/** `null` for a tier that cannot be sold: no interval (legacy manual plan) or unknown audience. */
export function toPlanTier(w: WirePlanTier): PlanTier | null {
  const held = toHeldTier(w)
  if (held.interval === null || held.audience === null) return null
  return { ...held, interval: held.interval, audience: held.audience }
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
  return {
    beneficiary: { ...w.beneficiary, audience: toAudience(w.beneficiary.audience) },
    subscription:
      sub
        ? {
            subscriptionId: sub.subscriptionId,
            status: sub.status,
            tier: toHeldTier(sub.tier),
            currentPeriodStart: sub.currentPeriodStart,
            currentPeriodEnd: sub.currentPeriodEnd,
            cancelAtPeriodEnd: sub.cancelAtPeriodEnd,
            pendingTier: sub.pendingTier ? toHeldTier(sub.pendingTier) : null,
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
        driftState: t.paymobDrift,
        rawFeatures: t.features,
      }
    }),
    packs: w.creditPacks,
    rates: w.usageRates,
    estimators: w.usageEstimators,
    freeAllowances: {
      studentSignupUnits: free("student")?.units ?? null,
      teacherSignupUnits: free("teacher")?.units ?? null,
      teacherSignupExpiryDays: free("teacher")?.validDays ?? null,
    },
  }
}

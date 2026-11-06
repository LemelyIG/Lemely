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

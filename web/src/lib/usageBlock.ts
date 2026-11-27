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

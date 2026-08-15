/*
 * Pure data + decision logic for S-03 (placement invite) and S-05
 * (placement results). No React, no DOM — exercised directly by
 * `web/tests/unit/placement.test.ts`, same split as `onboardingData.ts`.
 */

import type {
  PlacementAvailability,
  PlacementResult,
  PlacementTopicBreakdown,
} from "@/lib/placementTypes"

// ── S-03: honest per-reason messaging (D4.6 §5's `UnavailableReason`) ───

export interface UnavailableMessage {
  heading: string
  body: string
}

/**
 * One specific message per `lemely.core.placement.UnavailableReason` value
 * — never a generic "something went wrong" (UI spec §1.4, "never invent
 * precision" and D4.6's "S-03 says something specific per subject"). The
 * fallback branch only fires for a reason string this frontend has never
 * seen (a future backend addition), and still names the reason rather than
 * hiding it.
 */
export function unavailableMessage(reason: string | null): UnavailableMessage {
  switch (reason) {
    case "no_questions":
      return {
        heading: "No placement test yet for this subject",
        body: "We haven't ingested any questions for this subject yet, so there's nothing to build a placement test from. This isn't something you can fix. Check back once more content has been added.",
      }
    case "no_eligible_questions":
      return {
        heading: "Not enough usable questions yet",
        body: "We have questions for this subject, but not enough that are tagged to a topic and fully ready to serve. Check back later. This fills in as more content is classified.",
      }
    case "insufficient_topics":
      return {
        heading: "Not enough topic coverage yet",
        body: "There isn't enough topic breadth in the question bank yet to give you a meaningful baseline across this subject. Check back once more topics are covered.",
      }
    case "insufficient_questions":
      return {
        heading: "Not enough questions yet",
        body: "There aren't quite enough eligible questions to assemble a real placement test for this subject yet. Check back later.",
      }
    case "insufficient_duration":
      return {
        heading: "Not enough for a full-length test yet",
        body: "The eligible questions for this subject don't add up to a worthwhile placement test length yet. Check back later.",
      }
    default:
      return {
        heading: "Placement test not available right now",
        body: reason
          ? `This subject's placement test isn't available right now (reason: ${reason}).`
          : "This subject's placement test isn't available right now.",
      }
  }
}

/** "9 questions across 6 topics, about 15 minutes" — never rounds
 * `estimatedMinutes` to a false precision beyond whole minutes; the backend
 * value is itself an estimate (`lemely.core.placement.TARGET_MINUTES`), so
 * this only formats it, never re-derives one. */
export function formatPlacementEstimate(
  questionCount: number,
  topicCount: number,
  estimatedMinutes: number,
): string {
  const q = `${questionCount} question${questionCount === 1 ? "" : "s"}`
  const t = `${topicCount} topic${topicCount === 1 ? "" : "s"}`
  const minutes = Math.round(estimatedMinutes)
  return `${q} across ${t}, about ${minutes} minute${minutes === 1 ? "" : "s"}`
}

// ── S-03 view state — the whole render decision as one discriminated
// union, so `PlacementInvite.tsx` switches on it instead of re-deriving
// "available" vs "not" from raw fields in JSX (untestable there, since
// `vitest.config.ts` runs unit-only, no jsdom, D3.20). Pins the *inverse* of
// the unavailable-reason panel: `available: true` must yield the invite
// (`kind: "available"`), never the unavailable panel. ────────────────────

export type PlacementInviteView =
  | { kind: "unavailable"; message: UnavailableMessage }
  | { kind: "available"; estimate: string }

export function placementInviteView(availability: PlacementAvailability): PlacementInviteView {
  if (!availability.available) {
    return { kind: "unavailable", message: unavailableMessage(availability.reason) }
  }
  return {
    kind: "available",
    estimate: formatPlacementEstimate(
      availability.questionCount,
      availability.topicCount,
      availability.estimatedMinutes,
    ),
  }
}

// ── S-05: strongest/weakest topics from the real breakdown ──────────────

export interface RankedTopics {
  strongest: PlacementTopicBreakdown[]
  weakest: PlacementTopicBreakdown[]
}

/**
 * Rank `topicBreakdown` by `accuracy` and split into up to `limit` strongest
 * and up to `limit` weakest, with no overlap when the list is smaller than
 * `2 * limit` (a 3-topic breakdown does not show the same topic as both its
 * own strength and weakness). Ties keep the DTO's original order (a stable
 * sort), so this never invents a distinction the data doesn't support.
 */
export function rankTopics(
  topicBreakdown: readonly PlacementTopicBreakdown[],
  limit = 3,
): RankedTopics {
  const sorted = [...topicBreakdown]
    .map((t, index) => ({ t, index }))
    .sort((a, b) => b.t.accuracy - a.t.accuracy || a.index - b.index)
    .map(({ t }) => t)

  const strongest = sorted.slice(0, limit)
  const strongestTopics = new Set(strongest.map((t) => t.topic))
  const weakest = [...sorted]
    .reverse()
    .filter((t) => !strongestTopics.has(t.topic))
    .slice(0, limit)

  return { strongest, weakest }
}

// ── S-05 view state — the whole render decision as one discriminated
// union, so `PlacementResult.tsx` switches on it instead of branching on
// `marked`/`spansMultipleBands` directly in JSX. `kind: "unmarked"` carries
// no topic lists and no marks field at all (by the type, not by convention)
// — there is no `awardedMarks`/`maximumMarks` slot on this branch for a
// `null` to be coerced into a rendered `0`. `showWorkingLevel` is exactly
// `spansMultipleBands`: `false` forbids a working-level estimate (the
// sample was too narrow, UI spec §1.4 "never invent precision"); `true`
// permits one (S-05 doesn't compute a level itself here — that's a future
// chunk's — but this is the gate the caller checks before it would). ────

export type PlacementResultView =
  | { kind: "unmarked" }
  | {
      kind: "ranked"
      strongest: PlacementTopicBreakdown[]
      weakest: PlacementTopicBreakdown[]
      showWorkingLevel: boolean
    }

export function placementResultView(result: PlacementResult): PlacementResultView {
  if (!result.marked) return { kind: "unmarked" }
  const { strongest, weakest } = rankTopics(result.topicBreakdown)
  return { kind: "ranked", strongest, weakest, showWorkingLevel: result.spansMultipleBands }
}

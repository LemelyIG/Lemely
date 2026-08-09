/*
 * Pure data + decision logic for S-20 (practice generator) and S-21
 * (practice set working view + finish summary). No React, no DOM —
 * exercised directly by `web/tests/unit/practice.test.ts`, same split as
 * `placementData.ts` (D3.20: `vitest.config.ts` runs unit-only, no jsdom).
 */

import type { PracticePreview, PracticeResult, PracticeTopicCount } from "@/lib/practiceTypes"

/*
 * `PracticeConfidenceTier`/`PracticeMarkState` deliberately duplicate the
 * literal unions `ConfidenceTier` (`components/ui/confidence-indicator.tsx`)
 * and `MarkState` (`components/ui/question-row.tsx`) rather than importing
 * them: this module is pulled in by `tests/unit/practice.test.ts` under
 * `tsconfig.test.json`, which has no `jsx` compiler option set (D3.20's
 * unit-only, no-jsdom runner has no need for one) — even a type-only import
 * of a `.tsx` module fails to resolve under that config (TS6142). The
 * literal sets are identical, so a value typed here still satisfies the
 * component prop's own type at every call site (structural typing).
 */
export type PracticeConfidenceTier = "confident" | "uncertain" | "needs-review"
export type PracticeMarkState = "correct" | "partial" | "wrong"

// ── S-20: topic chips nested by syllabusGroup ────────────────────────────

export interface TopicGroup {
  syllabusGroup: string
  topics: PracticeTopicCount[]
}

/**
 * Group servable topics by `syllabusGroup`, preserving every distinct
 * `topic` row inside its group rather than collapsing rows that share a
 * group. The bank mixes taxonomy levels — measured live, 0625 returns
 * `"1 Motion, forces and energy"` (152) and `"1.2 Motion"` (6) as peers with
 * disjoint counts — so a parent topic and its child both surface as their
 * own selectable rows under the same group heading; nothing here merges a
 * parent's count into a child's or vice versa (that would offer the parent
 * chip as though picking it also covered the child, which the pool does not
 * support). Groups appear in first-seen order; a topic with no distinct
 * group (`syllabusGroup === topic`) is still its own one-row group.
 */
export function groupTopicsBySyllabusGroup(
  topics: readonly PracticeTopicCount[],
): TopicGroup[] {
  const order: string[] = []
  const byGroup = new Map<string, PracticeTopicCount[]>()
  for (const t of topics) {
    if (!byGroup.has(t.syllabusGroup)) {
      byGroup.set(t.syllabusGroup, [])
      order.push(t.syllabusGroup)
    }
    byGroup.get(t.syllabusGroup)!.push(t)
  }
  return order.map((syllabusGroup) => ({ syllabusGroup, topics: byGroup.get(syllabusGroup)! }))
}

export interface WeakTopicPrefill {
  /** The weak topics that actually have a chip on this screen. */
  selected: string[]
  /** Weak topics with no servable chip, dropped from the prefill. */
  dropped: string[]
}

/**
 * Resolve S-20's weak-topic prefill against the topics the screen actually
 * renders a control for.
 *
 * `PracticeTopicsDTO.weakTopics` and `.topics` are resolved **independently**
 * server-side — `weakTopics` from the student's `WeaknessRecord` rows,
 * `topics` from the servable bank pool through `_matching_clauses` — so
 * nothing guarantees the first is a subset of the second. Measured against
 * the live DB: 8 of 15 recorded weakness topics have no servable bank topic,
 * including the weakness engine's own `"unknown"` fallback label and
 * older-vocabulary labels like `"Electricity"`.
 *
 * Prefilling those verbatim would put a topic into the filter set that has
 * **no checkbox on the screen**: it is sent to `preview`/`create`, narrows
 * or empties the pool, and the student sees no chip checked and no way to
 * clear it — a filter applied invisibly, which can render as a flat "no
 * practice material" with no visible cause. So the prefill is the
 * intersection, and what was dropped is returned rather than discarded, so
 * the screen can say so instead of silently showing a shorter list.
 */
export function weakTopicPrefill(
  weakTopics: readonly string[],
  servableTopics: readonly PracticeTopicCount[],
): WeakTopicPrefill {
  const servable = new Set(servableTopics.map((t) => t.topic))
  const selected: string[] = []
  const dropped: string[] = []
  for (const topic of weakTopics) {
    if (servable.has(topic)) selected.push(topic)
    else dropped.push(topic)
  }
  return { selected, dropped }
}

// ── S-20: tri-state availability (spec §1.4 — honest shortfall, still
// creatable; a hard refusal is not a rendering choice) ───────────────────

export type PracticeAvailabilityView =
  | { kind: "unavailable"; reason: string | null }
  | { kind: "shortfall"; availableCount: number; requestedCount: number }
  | { kind: "available"; availableCount: number; requestedCount: number }

/**
 * The whole S-20 availability render decision as one discriminated union,
 * so the screen switches on `view.kind` instead of re-deriving "available
 * but short" vs. "fully available" vs. "refused" from raw fields in JSX.
 *
 *   - `available: false` -> `"unavailable"`: a real refusal (`no_questions`
 *     / `no_weaknesses`), never padded or presented as success.
 *   - `available: true` with `availableCount < requestedCount` (the
 *     `"insufficient_pool"` reason server-side, but this branch keys on the
 *     count comparison directly so it still catches the honest-shortfall
 *     case even if a future reason string names it differently) ->
 *     `"shortfall"`: still creatable, offer to broaden.
 *   - otherwise -> `"available"`: the filter set fully covers the request.
 */
export function practiceAvailabilityView(preview: PracticePreview): PracticeAvailabilityView {
  if (!preview.available) {
    return { kind: "unavailable", reason: preview.reason }
  }
  if (preview.availableCount < preview.requestedCount) {
    return {
      kind: "shortfall",
      availableCount: preview.availableCount,
      requestedCount: preview.requestedCount,
    }
  }
  return {
    kind: "available",
    availableCount: preview.availableCount,
    requestedCount: preview.requestedCount,
  }
}

export interface PracticeUnavailableMessage {
  heading: string
  body: string
}

/** One specific message per practice `reason` value — never a generic
 * "something went wrong", mirroring `unavailableMessage` in
 * `placementData.ts`. The fallback branch only fires for a reason string
 * this frontend has never seen, and still names the reason rather than
 * hiding it. */
export function practiceUnavailableMessage(reason: string | null): PracticeUnavailableMessage {
  switch (reason) {
    case "no_questions":
      return {
        heading: "No practice material for this filter set",
        body: "There's nothing in the question bank that matches what you've selected. Try widening your topic or difficulty selection.",
      }
    case "no_weaknesses":
      return {
        heading: "No weak topics recorded yet",
        body: "\"Weak topics only\" needs at least one recorded weakness for this subject — take a placement test or some general practice first, then this option will have something to draw from.",
      }
    default:
      return {
        heading: "Practice isn't available for this filter set right now",
        body: reason
          ? `This filter set isn't available right now (reason: ${reason}).`
          : "This filter set isn't available right now.",
      }
  }
}

// ── S-21: unsubmitted / marking / marked, never a fabricated zero ───────

export type PracticeResultView =
  | { kind: "not_submitted" }
  | { kind: "marking" }
  | {
      kind: "marked"
      awardedMarks: number
      maximumMarks: number
      questions: PracticeResult["questions"]
    }

/**
 * The whole S-21 finish-summary render decision as one discriminated union.
 * `marked: false` never yields a marks field the screen could coerce into a
 * rendered `0` — `"not_submitted"` and `"marking"` both carry no marks slot
 * at all (by the type, not by convention), split by `submissionStatus` so
 * "haven't started/finished yet" reads differently from "submitted, being
 * marked". `"marked"` only fires once the server has actually supplied both
 * mark fields — a `marked: true` row with a `null` mark field (should not
 * happen, but the wire type allows it) still falls through to `"marking"`
 * rather than rendering an invented number.
 */
export function practiceResultView(result: PracticeResult): PracticeResultView {
  if (result.marked && result.awardedMarks !== null && result.maximumMarks !== null) {
    return {
      kind: "marked",
      awardedMarks: result.awardedMarks,
      maximumMarks: result.maximumMarks,
      questions: result.questions,
    }
  }
  if (result.submissionStatus === "not_started" || result.submissionStatus === "in_progress") {
    return { kind: "not_submitted" }
  }
  return { kind: "marking" }
}

// ── S-21: per-question mark state + confidence tier ──────────────────────

/** Correct/partial/wrong from a real awarded/total pair — mirrors
 * `PaperResult.tsx`'s identical judgement call for the placement/paper
 * result surfaces, kept local here since practice results are a distinct
 * DTO the two screens don't share. */
export function practiceMarkState(awardedMarks: number, totalMarks: number): PracticeMarkState {
  if (awardedMarks >= totalMarks) return "correct"
  if (awardedMarks <= 0) return "wrong"
  return "partial"
}

/** `confidenceBand` on the wire is `"high" | "medium" | "low"`
 * (`lemely.db.models.enums.ConfidenceBand`) — maps onto the shared C-4
 * `ConfidenceTier` ladder rather than inlining a new confidence display. An
 * unrecognised band (future backend addition) reads as `"uncertain"` rather
 * than silently as `"confident"`, so an unknown value is never hidden. */
export function confidenceBandTier(band: string): PracticeConfidenceTier {
  if (band === "high") return "confident"
  if (band === "low") return "needs-review"
  return "uncertain"
}

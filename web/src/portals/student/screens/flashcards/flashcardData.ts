/*
 * Pure data + decision logic for S-22 (flashcard decks) and S-23 (flashcard
 * review session). No React, no DOM — exercised directly by
 * `web/tests/unit/flashcards.test.ts`, same split as `practiceData.ts`
 * (D3.20: `vitest.config.ts` runs unit-only, no jsdom).
 *
 * `flashcardTypes.ts` is a plain `.ts` module (not `.tsx`), so — unlike
 * `practiceData.ts`'s `ConfidenceTier`/`MarkState` situation — this file can
 * type-import from it directly under the unit-test tsconfig without hitting
 * TS6142. Nothing here duplicates a literal union from a `.tsx` component.
 */

import type {
  CardDTO,
  CardSource,
  CreateDeckRequest,
  DeckSummaryDTO,
  DueSessionDTO,
  GenerateDeckResponseDTO,
  ReviewGrade,
  ReviewResultDTO,
} from "@/lib/flashcardTypes"

// ── S-22: a hand-made deck's provenance survives having a topic ──────────

/**
 * Build the `POST /decks` body for the "write my own" mode.
 *
 * **`origin` stays `"manual"` whether or not the student typed a topic.**
 * The backend accepts a topic freely on the manual origin (`create_deck`:
 * "`origin=manual`: `topic` is whatever the caller passes"), so nothing in
 * the contract requires promoting a topic-bearing manual deck to
 * `origin: "topic"` — and doing so is a provenance lie. `DeckSummaryDTO.
 * origin` is what tells the screen whether a deck was hand-made, picked by
 * topic, or generated against a recorded weakness; `"topic"` renders as
 * "Topic-generated", which claims a model wrote a deck the student built by
 * hand. Same honesty rule as `source` on a card (rule 1), one level up: the
 * label describes who *made* the thing, and typing a topic into a form is
 * not a model generating cards.
 *
 * A blank title falls back to a subject-named default rather than being sent
 * empty; a blank topic is `null`, never `""` — an empty string would read
 * back as a topic the student chose.
 */
export function manualDeckRequest(
  subjectCode: string,
  subjectName: string,
  title: string,
  topic: string,
): CreateDeckRequest {
  return {
    subjectCode,
    title: title.trim() || `${subjectName} deck`,
    description: null,
    origin: "manual",
    topic: topic.trim() || null,
  }
}

// ── S-22: "nothing due today" says *when*, never renders a bare void ────

export type DueStateView =
  | { kind: "due"; cards: CardDTO[]; totalDue: number }
  | { kind: "none"; totalDue: number; nextDueAt: string | null }

/**
 * The whole S-22/S-23 "what's due" render decision as one discriminated
 * union. `totalDue` is always the real whole-backlog figure regardless of
 * any `limit` the caller applied (P4.9 honesty rule 3) — this function never
 * substitutes `cards.length` for it. An empty `cards` list carries
 * `nextDueAt` through to the `"none"` branch so the screen can say *when*
 * the next card comes due instead of rendering a void.
 */
export function dueStateView(session: DueSessionDTO): DueStateView {
  if (session.cards.length > 0) {
    return { kind: "due", cards: session.cards, totalDue: session.totalDue }
  }
  return { kind: "none", totalDue: session.totalDue, nextDueAt: session.nextDueAt }
}

/** Format `nextDueAt` into what-to-do-instead copy for the "nothing due
 * today" state. `null` (no cards scheduled at all — an empty deck, or no
 * decks yet) gets its own distinct copy, never coerced into a date string. */
export function nextDueMessage(nextDueAt: string | null): string {
  if (!nextDueAt) {
    return "You have no cards scheduled yet. Create or generate a deck to get started."
  }
  const date = new Date(nextDueAt)
  if (Number.isNaN(date.getTime())) {
    return "Your next card will be due soon."
  }
  const formatted = date.toLocaleString(undefined, {
    weekday: "short",
    hour: "numeric",
    minute: "2-digit",
  })
  return `Your next card is due ${formatted}.`
}

// ── Deck list grouping (S-22: "decks by subject and topic") ─────────────

export interface DeckTopicGroup {
  topic: string | null
  decks: DeckSummaryDTO[]
}

/** Group decks by `topic`, preserving first-seen order. A deck with no
 * topic (a manual deck that was never topic-targeted) groups under `null`,
 * rendered as its own "Untopiced" group rather than merged into another. */
export function groupDecksByTopic(decks: readonly DeckSummaryDTO[]): DeckTopicGroup[] {
  const order: (string | null)[] = []
  const byTopic = new Map<string | null, DeckSummaryDTO[]>()
  for (const deck of decks) {
    if (!byTopic.has(deck.topic)) {
      byTopic.set(deck.topic, [])
      order.push(deck.topic)
    }
    byTopic.get(deck.topic)!.push(deck)
  }
  return order.map((topic) => ({ topic, decks: byTopic.get(topic)! }))
}

// ── Honest refusal messages (409 `{"reason": ...}`) — mirrors
// `practiceUnavailableMessage`, never a generic "something went wrong" ────

export interface FlashcardUnavailableMessage {
  heading: string
  body: string
}

/** One specific message per flashcard `reason` value. Today the only
 * refusal this API raises is `origin="weakness"` with no recorded
 * weaknesses (`no_weaknesses`, shared vocabulary with P4.5/P4.9 chunk A) —
 * the fallback branch only fires for a reason string this frontend has
 * never seen, and still names the reason rather than hiding it. */
export function flashcardUnavailableMessage(reason: string | null): FlashcardUnavailableMessage {
  switch (reason) {
    case "no_weaknesses":
      return {
        heading: "No weak topics recorded yet",
        body: "A weakness-targeted deck needs at least one recorded weakness for this subject. Take a placement test or some practice first, then this option will have something to draw from.",
      }
    default:
      return {
        heading: "That deck can't be created right now",
        body: reason
          ? `This request isn't available right now (reason: ${reason}).`
          : "This request isn't available right now.",
      }
  }
}

// ── `generatedCount`, never `requestedCount` (P4.9 honesty rule 2) ──────

export interface GenerateDeckSummary {
  headline: string
  shortfall: boolean
}

/**
 * The generated-deck outcome message. Always keys off `generatedCount` —
 * `requestedCount` only appears in the shortfall copy, and never as the
 * reported total. A short response is named as short, not silently
 * presented as complete.
 */
export function generateDeckSummary(response: GenerateDeckResponseDTO): GenerateDeckSummary {
  const { generatedCount, requestedCount } = response
  if (generatedCount < requestedCount) {
    return {
      headline: `${generatedCount} card${generatedCount === 1 ? "" : "s"} generated (of ${requestedCount} requested)`,
      shortfall: true,
    }
  }
  return {
    headline: `${generatedCount} card${generatedCount === 1 ? "" : "s"} generated`,
    shortfall: false,
  }
}

// ── `CardDTO.source` stays visible on the card for its whole life
// (P4.9 honesty rule 1) ───────────────────────────────────────────────────

/** Human label for a card's `source`, distinct in both directions — never
 * blank, never the same string for both values. Every surface that renders
 * a card must call this rather than hiding `source`. */
export function cardSourceLabel(source: CardSource): string {
  return source === "ai" ? "AI-generated" : "Your card"
}

// ── S-23: keyboard operability — reveal + the four grade buttons need
// real key affordances, not mouse-only handlers (P4.9 honesty rule 7) ────

/** Space or Enter reveals the card's back. */
export function isRevealKey(key: string): boolean {
  return key === " " || key === "Enter"
}

/** 1-4 map onto the four SM-2 grades in the spec's again/hard/good/easy
 * order — the same left-to-right order the buttons render in, so a keyboard
 * or thumb user has a real, memorable affordance. An unrecognised key
 * yields `null`, never a guessed grade. */
export function gradeForKey(key: string): ReviewGrade | null {
  switch (key) {
    case "1":
      return "again"
    case "2":
      return "hard"
    case "3":
      return "good"
    case "4":
      return "easy"
    default:
      return null
  }
}

// ── S-23: session progress ────────────────────────────────────────────────

export interface SessionProgress {
  current: number
  total: number
  remaining: number
}

/** `current` is 1-indexed (the card being shown now), never exceeding
 * `total`, and `remaining` never goes negative — a session with more
 * reviews recorded than cards it started with (should not happen, but the
 * caller supplies both numbers independently) still reports `0`, not a
 * negative count. */
export function sessionProgress(current: number, total: number): SessionProgress {
  const clampedCurrent = Math.min(current, total)
  return { current: clampedCurrent, total, remaining: Math.max(total - clampedCurrent, 0) }
}

// ── S-23: end-of-session summary — real session facts only, no XP
// (P4.9 honesty rule 5) ───────────────────────────────────────────────────

export interface IntervalChange {
  cardId: string
  beforeDays: number
  afterDays: number
}

/** The end-of-session summary's full shape. Deliberately has no `xp` key,
 * no points, no streak field — the UI spec names XP here but XP is Phase 5
 * and does not exist in this codebase (MISSION §12); an invented number
 * would be exactly the fabricated precision spec §1.4 forbids. Every field
 * here is a fact `ReviewResultDTO` actually returned. */
export interface SessionSummary {
  reviewed: number
  gradeCounts: Record<ReviewGrade, number>
  intervalChanges: IntervalChange[]
}

/** Aggregate a session's `ReviewResultDTO`s into the end-of-session summary
 * — cards reviewed, the again/hard/good/easy distribution, and the
 * before/after interval change per card, in review order. */
export function summarizeSession(results: readonly ReviewResultDTO[]): SessionSummary {
  const gradeCounts: Record<ReviewGrade, number> = { again: 0, hard: 0, good: 0, easy: 0 }
  const intervalChanges: IntervalChange[] = []
  for (const result of results) {
    gradeCounts[result.grade] += 1
    intervalChanges.push({
      cardId: result.card.id,
      beforeDays: result.intervalBeforeDays,
      afterDays: result.intervalAfterDays,
    })
  }
  return { reviewed: results.length, gradeCounts, intervalChanges }
}

/** Render an interval change as "3d -> 7d" (or "New -> 1d" from a first
 * review at interval 0) — the scheduler's real effect, not a number the
 * student has to trust blindly. */
export function intervalChangeLabel(change: IntervalChange): string {
  const before = change.beforeDays === 0 ? "New" : `${change.beforeDays}d`
  return `${before} -> ${change.afterDays}d`
}

import type { CreateDeckRequest, GenerateDeckRequest, WeakTopicDTO } from "@/lib/flashcardTypes"
import { topicName } from "./flashcardsView"

export type NewDeckMode = "weakness" | "topic" | "manual"
export const COUNT_MIN = 1
export const COUNT_MAX = 50
export const COUNT_DEFAULT = 12
export const GENERATION_FAILED_TEXT = "Couldn't write the cards. Nothing was saved."

export function clampCount(n: number): number {
  return Math.min(COUNT_MAX, Math.max(COUNT_MIN, Math.round(n)))
}

/** The subject row is a choice only when there is more than one subject to choose. */
export function showSubjectChips(subjectCount: number): boolean {
  return subjectCount >= 2
}

export interface NewDeckOptionView {
  mode: NewDeckMode
  title: string
  sub: string
  disabled: boolean
}

export function newDeckOptions(weak: readonly WeakTopicDTO[], subjectCode: string): NewDeckOptionView[] {
  const hasWeak = weak.some((t) => t.subjectCode === subjectCode)
  return [
    {
      mode: "weakness",
      title: "From a weakness",
      sub: hasWeak ? "Cards on what cost you marks" : "Needs a marked paper first",
      disabled: !hasWeak,
    },
    { mode: "topic", title: "For a topic", sub: "Pick any syllabus topic", disabled: false },
    { mode: "manual", title: "Write my own", sub: "Type your own cards", disabled: false },
  ]
}

export interface ChipView {
  topic: string
  label: string
  badge: string | null
}

export function weaknessChips(weak: readonly WeakTopicDTO[], subjectCode: string): ChipView[] {
  return weak
    .filter((t) => t.subjectCode === subjectCode)
    .map((t) => ({ topic: t.topic, label: topicName(t.topic), badge: `${t.accuracyPct}%` }))
}

export function topicChips(topics: readonly string[]): ChipView[] {
  return topics.map((t) => ({ topic: t, label: topicName(t), badge: null }))
}

export function submitLabel(mode: NewDeckMode, count: number, pending: boolean): string {
  if (pending) return "Starting…"
  if (mode === "manual") return "Make deck"
  return `Make ${count} card${count === 1 ? "" : "s"}`
}

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

export type NewDeckRequest =
  | { kind: "generate"; body: GenerateDeckRequest }
  | { kind: "create"; body: CreateDeckRequest }
  | { kind: "invalid"; reason: string }

/** `weakTopics` is the student's recorded weak topics for this subject. The screen always passes
 * it; in weakness mode a topic outside it is refused, so a weakness deck can only be about a
 * weakness the student really has. */
export function buildNewDeckRequest(input: {
  mode: NewDeckMode
  subjectCode: string
  subjectName: string
  topic: string | null
  count: number
  title: string
  weakTopics?: readonly string[]
}): NewDeckRequest {
  if (input.mode === "manual") {
    return { kind: "create", body: manualDeckRequest(input.subjectCode, input.subjectName, input.title, input.topic ?? "") }
  }
  if (!input.topic) return { kind: "invalid", reason: "Pick a topic first." }
  if (input.mode === "weakness" && input.weakTopics && !input.weakTopics.includes(input.topic)) {
    return { kind: "invalid", reason: "Pick one of your weak topics." }
  }
  return {
    kind: "generate",
    body: {
      subjectCode: input.subjectCode,
      origin: input.mode,
      count: clampCount(input.count),
      topic: input.topic,
      title: input.title.trim() || null,
    },
  }
}

/** Structural, so this file never imports `lib/api.ts` (which touches browser globals). */
export function newDeckErrorMessage(err: { status?: number; detail?: unknown } | null): string {
  if (err?.status === 409) {
    const reason = (err.detail as { reason?: string } | undefined)?.reason
    if (reason === "no_weaknesses") return "No weak topics yet. Mark a paper first."
    return reason ? `That deck can't be made right now (${reason}).` : "That deck can't be made right now."
  }
  if (err?.status === 503) return "Card writing is off right now."
  if (err?.status === 422) return "Pick a topic from the list."
  return "Couldn't make the deck. Try again."
}

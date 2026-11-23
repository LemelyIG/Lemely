import type { CreateDeckRequest, GenerateDeckRequest, GenerateDeckResponseDTO, WeakTopicDTO } from "@/lib/flashcardTypes"
import { topicName } from "./flashcardsView"
import { generationOutcome } from "./reviewView"

export type NewDeckMode = "weakness" | "topic" | "manual"
export const COUNT_MIN = 1
export const COUNT_MAX = 50
export const COUNT_DEFAULT = 12
export const GENERATION_FAILED_TEXT = "Couldn't write the cards. Nothing was saved."

/**
 * FGX: the new-deck sheet reopened for a deck whose cards did not get written. It carries the deck's
 * own subject, topic and kind (a manual deck has no kind to preselect) and the id to retry or discard.
 */
export function failedDeckSeed(
  deck: { origin: NewDeckMode; subjectCode: string; topic: string | null },
  deckId: string,
): { mode: NewDeckMode | null; subjectCode: string; topic: string | null; failedDeckId: string } {
  return {
    mode: deck.origin === "manual" ? null : deck.origin,
    subjectCode: deck.subjectCode,
    topic: deck.topic,
    failedDeckId: deckId,
  }
}

/**
 * The failed deck to delete when its sheet closes: any close that is not a retry, so "Nothing was
 * saved" stays true. Null once a retry started or is running, or when the sheet is not for a failed deck.
 */
export function failedDeckToDiscard(c: { failedDeckId: string | undefined; retryStarted: boolean; retrying: boolean }): string | null {
  if (!c.failedDeckId || c.retryStarted || c.retrying) return null
  return c.failedDeckId
}

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

/** What the student has picked so far. `chosenMode` stays null until they pick, so the default can follow the data. */
export interface DeckSelection {
  subject: string
  chosenMode: NewDeckMode | null
  topic: string | null
}

/** The kind in force: the student's own pick, else weakness when one exists, else topic. */
export function resolveMode(chosen: NewDeckMode | null, options: readonly NewDeckOptionView[]): NewDeckMode {
  return chosen ?? (options[0].disabled ? "topic" : "weakness")
}

/**
 * A kind and a topic both belong to one subject, so a new subject drops both. Tapping the subject
 * already in force changes nothing and keeps the pick (`inForce` is the subject on screen, which can
 * be the first-subject fallback while `sel.subject` is still empty).
 */
export function selectSubject(sel: DeckSelection, subject: string, inForce: string): DeckSelection {
  if (subject === inForce) return sel
  return { subject, chosenMode: null, topic: null }
}

/** A topic belongs to one kind, so a new kind clears it. */
export function selectKind(sel: DeckSelection, mode: NewDeckMode): DeckSelection {
  return { ...sel, chosenMode: mode, topic: null }
}

/** Picking a chip fixes the kind in force, so weaknesses arriving late cannot flip it under the student. */
export function selectChip(sel: DeckSelection, resolved: NewDeckMode, topic: string): DeckSelection {
  return { ...sel, chosenMode: resolved, topic }
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

/** `weakTopics` is required so the guard cannot be skipped by mistake: the student's recorded weak
 * topics for this subject. In weakness mode a topic outside it is refused, so a weakness deck can only be about a
 * weakness the student really has. */
export function buildNewDeckRequest(input: {
  mode: NewDeckMode
  subjectCode: string
  subjectName: string
  topic: string | null
  count: number
  title: string
  weakTopics: readonly string[]
}): NewDeckRequest {
  if (input.mode === "manual") {
    return { kind: "create", body: manualDeckRequest(input.subjectCode, input.subjectName, input.title, input.topic ?? "") }
  }
  if (!input.topic) return { kind: "invalid", reason: "Pick a topic first." }
  if (input.mode === "weakness" && !input.weakTopics.includes(input.topic)) {
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

export interface NewDeckOutcome {
  variant: "success" | "info" | "error"
  title: string
  description?: string
}

/**
 * What to tell the student when a generated deck comes back. Generation is synchronous: the 201 is
 * already ready or failed, so the sheet closing is no answer. Reports the real count, never the
 * requested one (P4.9 rule 2, K11). `null` means the deck is still writing and its own page says so.
 */
export function newDeckOutcome(res: GenerateDeckResponseDTO): NewDeckOutcome | null {
  const status = res.deck.generationStatus
  if (status === "writing") return null
  if (status === "failed") return { variant: "error", title: "Couldn’t write the cards", description: "Nothing was saved." }
  const { text, shortfall } = generationOutcome({
    deckId: res.deck.id,
    status,
    requestedCount: res.requestedCount,
    generatedCount: res.generatedCount,
    error: null,
  })
  if (res.generatedCount === 0) return { variant: "error", title: text }
  return { variant: shortfall ? "info" : "success", title: text }
}

/**
 * The tail of a generate submit: say how it went, then hand over to the deck. A deck still writing
 * has nothing to report yet, so it goes straight through.
 */
export function finishGeneration(
  res: GenerateDeckResponseDTO,
  toast: (outcome: NewDeckOutcome) => unknown,
  onStarted: (deckId: string) => void,
): void {
  const outcome = newDeckOutcome(res)
  if (outcome) toast(outcome)
  onStarted(res.deck.id)
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

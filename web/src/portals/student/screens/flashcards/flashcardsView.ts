// web/src/portals/student/screens/flashcards/flashcardsView.ts
import type { DeckOrigin, DeckSummaryDTO, DueSessionDTO, WeakTopicDTO } from "@/lib/flashcardTypes"

/*
 * L10 · every decision on the decks screen, as plain data. No React, no DOM, so Vitest runs it
 * in node (vitest.config.ts). The screen renders `decksScreenView(...)` and decides nothing.
 */

/** Structurally the F1 `BinnyMood`; declared here so this `.ts` file never imports a `.tsx`. */
export type FcMood = "happy" | "wink" | "open" | "thinking" | "sad"
export type OriginIcon = "target" | "sparkle" | "pen"
type QueryStatus = "pending" | "error" | "success"

export const SECONDS_PER_CARD = 18
export const SPARSE_MAX_CARDS = 10

const TOPIC_CODE = /^[A-Z]?\d+(?:\.\d+)*\s+/

export function topicName(topic: string): string {
  return topic.replace(TOPIC_CODE, "").trim() || topic
}

/** Dot colours from existing tokens only (no new tokens; mock blue/violet map to tide/orange). */
const SUBJECT_DOTS = [
  "var(--color-grade-a)",
  "var(--color-inverse-primary)",
  "var(--color-grade-d)",
  "var(--color-primary)",
  "var(--color-grade-b)",
]

export function subjectDot(code: string, order: readonly string[]): string {
  const i = order.indexOf(code)
  return i < 0 ? "var(--color-on-surface-variant)" : SUBJECT_DOTS[i % SUBJECT_DOTS.length]
}

export function originView(origin: DeckOrigin): { icon: OriginIcon; label: string } {
  if (origin === "weakness") return { icon: "target", label: "From a weakness" }
  if (origin === "topic") return { icon: "sparkle", label: "For a topic" }
  return { icon: "pen", label: "Written by you" }
}

export interface MasteryView {
  known: number
  learning: number
  fresh: number
  total: number
  knownPct: number
  learningPct: number
  label: string
}

export function masteryView(c: { newCount: number; learningCount: number; knownCount: number }): MasteryView {
  const total = c.newCount + c.learningCount + c.knownCount
  return {
    known: c.knownCount,
    learning: c.learningCount,
    fresh: c.newCount,
    total,
    knownPct: total ? (c.knownCount / total) * 100 : 0,
    learningPct: total ? (c.learningCount / total) * 100 : 0,
    label: `${c.knownCount} known, ${c.learningCount} learning, ${c.newCount} new`,
  }
}

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`

export interface DeckRowView {
  id: string
  title: string
  subjectCode: string
  originIcon: OriginIcon
  originLabel: string
  meta: string
  mastery: MasteryView
  due: number
  status: DeckSummaryDTO["generationStatus"]
  /** Failed decks offer a Retry; the screen renders it from this flag. */
  canRetry: boolean
  statusLine: string | null
}

export function deckRowView(deck: DeckSummaryDTO): DeckRowView {
  const origin = originView(deck.origin)
  const statusLine =
    deck.generationStatus === "writing"
      ? `Writing ${plural(deck.requestedCount ?? 0, "card")}…`
      : deck.generationStatus === "failed"
        ? "Couldn't write the cards"
        : null
  return {
    id: deck.id,
    title: deck.title,
    subjectCode: deck.subjectCode,
    originIcon: origin.icon,
    originLabel: origin.label,
    meta: `${origin.label} · ${plural(deck.cardCount, "card")}`,
    mastery: masteryView(deck),
    due: deck.dueCount,
    status: deck.generationStatus,
    canRetry: deck.generationStatus === "failed",
    statusLine,
  }
}

export function estimateMinutes(cards: number): number {
  return Math.max(1, Math.round((cards * SECONDS_PER_CARD) / 60))
}

function localDayIndex(d: Date, now: Date): number {
  const a = new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()
  const b = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  return Math.round((a - b) / 86_400_000)
}

/** "N cards back tomorrow" from the forecast; else the next due weekday; else a nudge. */
export function comingBackLine(upcoming: readonly string[], nextDueAt: string | null, now: Date): string {
  const tomorrow = upcoming.filter((iso) => localDayIndex(new Date(iso), now) === 1).length
  if (tomorrow > 0) return `${plural(tomorrow, "card")} back tomorrow`
  if (nextDueAt) {
    const d = new Date(nextDueAt)
    if (!Number.isNaN(d.getTime())) {
      const day = localDayIndex(d, now)
      if (day <= 0) return "Next card later today"
      return `Next card ${d.toLocaleDateString(undefined, { weekday: "long" })}`
    }
  }
  return "Add cards to start"
}

export interface SubjectGroupView {
  subjectCode: string
  subjectName: string
  dot: string
  decks: DeckRowView[]
}

export interface HeroView {
  mood: FcMood
  headline: string
  sub: string
  reviewLabel: string | null
}

export interface SparseView {
  tip: { title: string; body: string; subjectCode: string; topic: string } | null
}

export type DecksScreenView =
  | { kind: "loading" }
  | { kind: "error" }
  | { kind: "empty"; mood: FcMood; weakHint: string | null }
  | {
      kind: "ready"
      header: { title: string; sub: string }
      hero: HeroView
      groups: SubjectGroupView[]
      sparse: SparseView | null
      firstDeckId: string | null
    }

export interface DecksScreenInput {
  decks: DeckSummaryDTO[] | undefined
  decksStatus: QueryStatus
  due: DueSessionDTO | undefined
  dueStatus: QueryStatus
  weakTopics: readonly WeakTopicDTO[]
  subjectName: (code: string) => string
  subjectOrder: readonly string[]
  filterSubject: string | null
  now: Date
}

function hero(input: DecksScreenInput, decks: DeckSummaryDTO[]): HeroView {
  if (input.dueStatus === "pending" && !input.due) {
    return { mood: "happy", headline: "Your cards", sub: "Checking what's due…", reviewLabel: null }
  }
  if (input.dueStatus === "error" && !input.due) {
    return { mood: "happy", headline: "Your cards", sub: "Couldn't check what's due", reviewLabel: null }
  }
  const due = input.due!
  // A subject filter scopes the hero to the visible decks; unfiltered keeps the session total.
  const totalDue = input.filterSubject
    ? decks.reduce((s, d) => s + (d.generationStatus === "ready" ? d.dueCount : 0), 0)
    : due.totalDue
  if (totalDue > 0) {
    const decksDue = decks.filter((d) => d.dueCount > 0).length
    return {
      mood: "happy",
      headline: `${plural(totalDue, "card")} due`,
      sub: `About ${plural(estimateMinutes(totalDue), "minute")} · ${plural(decksDue, "deck")}`,
      reviewLabel: `Review ${plural(totalDue, "card")}`,
    }
  }
  return {
    mood: "happy",
    headline: "Nothing due",
    sub: comingBackLine(due.upcoming, due.nextDueAt, input.now),
    reviewLabel: null,
  }
}

const groupOrderRank = (order: readonly string[], code: string) => {
  const i = order.indexOf(code)
  return i < 0 ? order.length : i
}

export function decksScreenView(input: DecksScreenInput): DecksScreenView {
  if (!input.decks) return input.decksStatus === "error" ? { kind: "error" } : { kind: "loading" }
  const decks = input.filterSubject
    ? input.decks.filter((d) => d.subjectCode === input.filterSubject)
    : input.decks
  if (decks.length === 0) {
    const weak = input.weakTopics.find((t) => !input.filterSubject || t.subjectCode === input.filterSubject)
    return {
      kind: "empty",
      mood: "open",
      weakHint: weak ? `${topicName(weak.topic)} cost you ${plural(weak.marksLost, "mark")}` : null,
    }
  }

  const bySubject = new Map<string, DeckSummaryDTO[]>()
  for (const d of decks) bySubject.set(d.subjectCode, [...(bySubject.get(d.subjectCode) ?? []), d])
  const statusRank = (d: DeckSummaryDTO) => (d.generationStatus === "ready" ? 0 : 1)
  const groups: SubjectGroupView[] = [...bySubject.entries()]
    .map(([code, list]) => ({
      subjectCode: code,
      subjectName: input.subjectName(code),
      dot: subjectDot(code, input.subjectOrder),
      decks: [...list]
        .sort((a, b) => statusRank(a) - statusRank(b) || b.dueCount - a.dueCount || a.title.localeCompare(b.title))
        .map(deckRowView),
      dueTotal: list.reduce((s, d) => s + d.dueCount, 0),
    }))
    .sort(
      (a, b) =>
        b.dueTotal - a.dueTotal ||
        groupOrderRank(input.subjectOrder, a.subjectCode) - groupOrderRank(input.subjectOrder, b.subjectCode),
    )
    .map(({ dueTotal: _dueTotal, ...g }) => g)

  const totalCards = decks.reduce((s, d) => s + d.cardCount, 0)
  const counts = `${plural(decks.length, "deck")} · ${plural(totalCards, "card")}`
  const sub = input.filterSubject ? `${input.subjectName(input.filterSubject)} · ${counts}` : counts

  const isSparse = decks.length === 1 && decks[0].generationStatus === "ready" && totalCards <= SPARSE_MAX_CARDS
  let sparse: SparseView | null = null
  if (isSparse) {
    const covered = new Set(decks.map((d) => `${d.subjectCode}|${d.topic ?? ""}`))
    const next = input.weakTopics.find((t) => !covered.has(`${t.subjectCode}|${t.topic}`))
    sparse = {
      tip: next
        ? {
            title: "One more deck?",
            body: `${topicName(next.topic)} cost you ${plural(next.marksLost, "mark")}.`,
            subjectCode: next.subjectCode,
            topic: next.topic,
          }
        : null,
    }
  }

  return {
    kind: "ready",
    header: { title: "Flashcards", sub },
    hero: hero(input, decks),
    groups,
    sparse,
    firstDeckId: groups.flatMap((g) => g.decks).find((d) => d.status === "ready")?.id ?? null,
  }
}

/**
 * The deck the side panel shows. A pick (history state or a `?deck=` deep link) counts only while
 * that deck is still on the shelf; a deleted or unknown id falls back to the first ready deck.
 */
export function resolveSelectedDeck(view: DecksScreenView, picked: string | null): string | null {
  if (view.kind !== "ready") return null
  if (picked && view.groups.some((g) => g.decks.some((d) => d.id === picked))) return picked
  return view.firstDeckId
}

/** `location.search` minus `deck`, so clearing a selection cannot re-seed it from the deep link. */
export function searchWithoutDeck(search: string): string {
  const params = new URLSearchParams(search)
  params.delete("deck")
  const rest = params.toString()
  return rest ? `?${rest}` : ""
}

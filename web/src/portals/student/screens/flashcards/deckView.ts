import type { CardSource, DeckDetailDTO, DeckOrigin } from "@/lib/flashcardTypes"
import {
  masteryLegend,
  masteryView,
  originView,
  topicName,
  type MasteryLegendItem,
  type MasteryView,
  type OriginIcon,
} from "./flashcardsView"

const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? "" : "s"}`

/** Distinct both ways, never blank (P4.9 honesty rule 1). */
export function cardSourceLabel(source: CardSource): string {
  return source === "ai" ? "AI-generated" : "Your card"
}

export interface CardRowView {
  id: string
  front: string
  back: string
  ai: boolean
  sourceLabel: string
}

export interface DeckDetailView {
  title: string
  sub: string
  dot: string
  originIcon: OriginIcon
  originLine: string
  mastery: MasteryView
  legend: readonly MasteryLegendItem[]
  review: { label: string; enabled: boolean }
  cards: CardRowView[]
  emptyCards: boolean
  state: DeckDetailDTO["generationStatus"]
}

export function deckDetailView(deck: DeckDetailDTO, subjectName: string, dot: string): DeckDetailView {
  const origin = originView(deck.origin)
  const mastery = masteryView(deck)
  return {
    title: deck.title,
    sub: `${subjectName} · ${plural(deck.cards.length, "card")}`,
    dot,
    originIcon: origin.icon,
    originLine: deck.marksLost ? `${origin.label} · cost you ${plural(deck.marksLost, "mark")}` : origin.label,
    mastery,
    legend: masteryLegend(mastery),
    review: deck.dueCount > 0 ? { label: `Review ${deck.dueCount} due`, enabled: true } : { label: "Nothing due", enabled: false },
    cards: deck.cards.map((c) => ({
      id: c.id,
      front: c.front,
      back: c.back,
      ai: c.source === "ai",
      sourceLabel: cardSourceLabel(c.source),
    })),
    emptyCards: deck.cards.length === 0,
    state: deck.generationStatus,
  }
}

export interface WritingView {
  title: string
  body: string
  hint: string
}

export function writingView(deck: { topic: string | null; origin: DeckOrigin; requestedCount: number | null }): WritingView {
  const topic = deck.topic ? topicName(deck.topic) : "your topic"
  return {
    // No count from the server means no number on screen.
    title: deck.requestedCount ? `Writing ${plural(deck.requestedCount, "card")}…` : "Writing your cards…",
    body: deck.origin === "weakness" ? `On ${topic}, from the questions that cost you marks.` : `On ${topic}.`,
    hint: "You can leave. The deck shows up when it's ready.",
  }
}

/** Honest-looking progress with no server progress to read: eases toward 0.9 over the expected
 * time (6 s plus 0.75 s a card) and never reaches 1 until the status says ready. */
export function writingProgress(elapsedMs: number, requested: number): number {
  const expectedMs = (6 + 0.75 * Math.max(1, requested)) * 1000
  const p = 0.9 * (1 - Math.exp(-elapsedMs / expectedMs))
  return Math.min(0.9, Math.round(p * 1000) / 1000)
}

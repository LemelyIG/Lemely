// web/tests/unit/reviewCardName.test.ts
// WCAG 2.5.3 (axe `label-in-name`): the review card is `role="button"`, so its accessible name must
// contain the words printed on it, in the order they are printed. An injected "Answer:" between the
// question and the answer broke that. The rule pinned here: the card carries no aria-label, so the
// name is its own content, and the flipped cue ("Answer shown") is a description, outside the name.
// Node has no DOM, so the card is rendered to markup and the name is read the way a browser does it
// for this markup: aria-hidden pieces dropped, everything else joined in document order.
import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"
import type { CardDTO } from "@/lib/flashcardTypes"

vi.mock("@/lib/gestures/useDragGesture", () => ({ useDragGesture: () => {} }))
import { ReviewCard } from "@/portals/student/screens/flashcards/ReviewCard"
import { cardSourceLabel } from "@/portals/student/screens/flashcards/deckView"

const manual = { id: "card-1", front: "Capital of France", back: "Paris", source: "manual" } as CardDTO
const ai = { ...manual, id: "card-2", source: "ai" } as CardDTO

function render(card: CardDTO, revealed: boolean): string {
  return renderToStaticMarkup(createElement(ReviewCard, { card, revealed, onReveal: () => {}, onGrade: () => {} }))
}

/** The card surface: its opening tag, and everything inside it (it holds spans only, never a nested div). */
function surface(html: string): { open: string; inner: string } {
  const match = /(<div[^>]*role="button"[^>]*>)([\s\S]*?)<\/div>/.exec(html)
  if (!match) throw new Error(`no role="button" in ${html}`)
  return { open: match[1], inner: match[2] }
}

/** Name from content: aria-hidden pieces are skipped, tags removed, whitespace collapsed. */
function nameFromContent(inner: string): string {
  return inner
    .replace(/<svg[\s\S]*?<\/svg>/g, "")
    .replace(/<span[^>]*aria-hidden[^>]*>[^<]*<\/span>/g, "")
    .replace(/<[^>]+>/g, "")
    .replace(/\s+/g, " ")
    .trim()
}

describe("review card accessible name", () => {
  it("is the printed question and prompt when not flipped, with no label override", () => {
    const { open, inner } = surface(render(manual, false))
    expect(open).not.toContain("aria-label")
    expect(nameFromContent(inner)).toBe("Capital of France Tap to flip")
  })

  it("is the printed question then answer when flipped, with no injected words between them", () => {
    const { open, inner } = surface(render(manual, true))
    expect(open).not.toContain("aria-label")
    expect(nameFromContent(inner)).toBe("Capital of France Paris")
  })

  it("keeps the flipped cue as a description outside the name, and only once flipped", () => {
    const html = render(manual, true)
    const { open, inner } = surface(html)
    const hintId = /aria-describedby="([^"]+)"/.exec(open)?.[1]
    expect(hintId).toBeTruthy()
    const hint = new RegExp(`<span id="${hintId}"[^>]*>([^<]*)</span>`).exec(html)
    expect(hint?.[1]).toBe("Answer shown. Rate how well you knew it.")
    expect(inner).not.toContain(hintId as string)
    expect(surface(render(manual, false)).open).not.toContain("aria-describedby")
  })

  it("still announces that an AI card is AI-written, ahead of the printed words", () => {
    for (const revealed of [false, true]) {
      const name = nameFromContent(surface(render(ai, revealed)).inner)
      expect(name.startsWith(cardSourceLabel("ai"))).toBe(true)
      expect(name).toContain(revealed ? "Capital of France Paris" : "Capital of France Tap to flip")
    }
  })
})

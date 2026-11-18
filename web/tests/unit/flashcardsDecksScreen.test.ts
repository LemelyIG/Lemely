// web/tests/unit/flashcardsDecksScreen.test.ts
// Task 10 review fixes: deck selection, the Retry guard and the loading region.
import { createElement, isValidElement, type ReactElement, type ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"

vi.mock("@/lib/gestures/useLongPress", () => ({ useLongPress: () => ({}) }))

import { DecksLoading } from "@/portals/student/screens/flashcards/DecksStates"
import { DeckRow } from "@/portals/student/screens/flashcards/parts/DeckRow"
import {
  resolveSelectedDeck,
  searchWithoutDeck,
  type DeckRowView,
  type DecksScreenView,
} from "@/portals/student/screens/flashcards/flashcardsView"

function row(o: Partial<DeckRowView> & { id: string }): DeckRowView {
  return {
    title: o.id,
    subjectCode: "0580",
    originIcon: "pen",
    originLabel: "Yours",
    meta: "Yours · 10 cards",
    mastery: { known: 2, learning: 4, fresh: 4, total: 10, label: "" } as unknown as DeckRowView["mastery"],
    due: 0,
    status: "ready",
    canRetry: false,
    statusLine: null,
    ...o,
  }
}

function ready(rows: DeckRowView[], firstDeckId: string | null): DecksScreenView {
  return {
    kind: "ready",
    header: { title: "Flashcards", sub: "" },
    hero: {} as never,
    groups: [{ subjectCode: "0580", subjectName: "Maths", dot: "red", decks: rows } as never],
    sparse: null,
    firstDeckId,
  }
}

describe("resolveSelectedDeck", () => {
  const view = ready([row({ id: "a" }), row({ id: "b" }), row({ id: "w", status: "writing" })], "a")

  it("keeps a pick that is still on the shelf, including a deck still being written", () => {
    expect(resolveSelectedDeck(view, "b")).toBe("b")
    expect(resolveSelectedDeck(view, "w")).toBe("w")
  })

  it("falls back to the first ready deck when the pick is gone (deleted deep link)", () => {
    expect(resolveSelectedDeck(view, "deleted")).toBe("a")
    expect(resolveSelectedDeck(view, null)).toBe("a")
  })

  it("selects nothing outside the ready state", () => {
    expect(resolveSelectedDeck({ kind: "loading" }, "a")).toBeNull()
  })
})

describe("searchWithoutDeck", () => {
  it("drops only the deck param", () => {
    expect(searchWithoutDeck("?deck=a")).toBe("")
    expect(searchWithoutDeck("?deck=a&x=1")).toBe("?x=1")
    expect(searchWithoutDeck("")).toBe("")
  })
})

function findRetry(node: ReactNode): ReactElement<{ onClick?: () => void }> | null {
  if (Array.isArray(node)) {
    for (const n of node) {
      const hit = findRetry(n)
      if (hit) return hit
    }
    return null
  }
  if (!isValidElement<{ children?: ReactNode; "aria-label"?: string }>(node)) return null
  if (node.type === "button" && String(node.props["aria-label"] ?? node.props.children).includes("Retr")) {
    return node as ReactElement<{ onClick?: () => void }>
  }
  return findRetry(node.props.children)
}

describe("DeckRow Retry", () => {
  const failed = row({ id: "d1", title: "Algebra", status: "failed", canRetry: true, statusLine: "Couldn't write the cards" })
  const props = { row: failed, onOpen: () => {}, onLongPress: () => {} }

  it("ignores a second tap while the first retry is in flight", () => {
    const onRetry = vi.fn()
    const busy = findRetry(DeckRow({ ...props, onRetry, retrying: true }))
    busy?.props.onClick?.()
    expect(onRetry).not.toHaveBeenCalled()

    const idle = findRetry(DeckRow({ ...props, onRetry, retrying: false }))
    idle?.props.onClick?.()
    expect(onRetry).toHaveBeenCalledTimes(1)
  })

  it("names each Retry after its deck", () => {
    const html = renderToStaticMarkup(createElement(DeckRow, { ...props, onRetry: () => {} }))
    expect(html).toContain('aria-label="Retry Algebra"')
  })
})

describe("DecksLoading", () => {
  it("announces once, not once per skeleton block", () => {
    const html = renderToStaticMarkup(createElement(DecksLoading))
    expect(html.match(/role="status"/g)?.length).toBe(1)
    expect(html).toContain('aria-label="Loading your decks"')
  })
})

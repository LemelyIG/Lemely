import { describe, expect, it, vi } from "vitest"
import type { CardDTO } from "@/lib/flashcardTypes"

const gesture = vi.hoisted(() => ({ commit: (_x: number) => {} }))
vi.mock("react", async (importOriginal) => ({
  ...await importOriginal<typeof import("react")>(),
  useRef: () => ({ current: null }),
  useEffect: () => {},
  useState: (value: unknown) => [value, vi.fn()],
}))
vi.mock("@/lib/gestures/useDragGesture", () => ({
  useDragGesture: (_ref: unknown, options: { onCommit: (x: number) => void }) => { gesture.commit = options.onCommit },
}))
import { ReviewCard } from "@/portals/student/screens/flashcards/ReviewCard"

const card = { id: "one", front: "Question", back: "Answer", source: "manual" } as CardDTO
type KeyEvent = { key: string; repeat: boolean; preventDefault: () => void; stopPropagation: () => void }
type ElementNode = { type: unknown; props: { children?: unknown; onClick?: () => void; onKeyDown?: (e: KeyEvent) => void; role?: string } }
function findButton(node: unknown): ElementNode | undefined {
  if (Array.isArray(node)) return node.map(findButton).find(Boolean)
  if (!node || typeof node !== "object" || !("props" in node)) return undefined
  const element = node as ElementNode
  return element.props.role === "button" ? element : findButton(element.props.children)
}

describe("review card interactions", () => {
  it("reveals the front on tap and on a right swipe", () => {
    const reveal = vi.fn()
    const grade = vi.fn()
    const tree = ReviewCard({ card, revealed: false, onReveal: reveal, onGrade: grade })
    findButton(tree)?.props.onClick?.()
    gesture.commit(80)
    expect(reveal).toHaveBeenCalledTimes(2)
    expect(grade).not.toHaveBeenCalled()
  })

  it("does not reveal on a left swipe", () => {
    const reveal = vi.fn()
    ReviewCard({ card, revealed: false, onReveal: reveal, onGrade: vi.fn() })
    gesture.commit(-100)
    expect(reveal).not.toHaveBeenCalled()
  })

  it("flips on Space and Enter from the keyboard, once, without the screen shortcut seeing the key", () => {
    for (const key of [" ", "Enter"]) {
      const reveal = vi.fn()
      const event = { key, repeat: false, preventDefault: vi.fn(), stopPropagation: vi.fn() }
      findButton(ReviewCard({ card, revealed: false, onReveal: reveal, onGrade: vi.fn() }))?.props.onKeyDown?.(event)
      expect(reveal).toHaveBeenCalledTimes(1)
      expect(event.preventDefault).toHaveBeenCalled()
      expect(event.stopPropagation).toHaveBeenCalled()
    }
  })

  it("ignores other keys, held keys, and any key once the card is flipped", () => {
    const cases = [
      { revealed: false, key: "a", repeat: false },
      { revealed: false, key: " ", repeat: true },
      { revealed: true, key: " ", repeat: false },
      { revealed: true, key: "Enter", repeat: false },
    ]
    for (const c of cases) {
      const reveal = vi.fn()
      const event = { key: c.key, repeat: c.repeat, preventDefault: vi.fn(), stopPropagation: vi.fn() }
      findButton(ReviewCard({ card, revealed: c.revealed, onReveal: reveal, onGrade: vi.fn() }))?.props.onKeyDown?.(event)
      expect(reveal).not.toHaveBeenCalled()
      expect(event.preventDefault).not.toHaveBeenCalled()
    }
  })
})

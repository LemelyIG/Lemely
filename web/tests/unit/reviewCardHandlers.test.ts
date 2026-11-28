import { describe, expect, it, vi } from "vitest"
import type { CardDTO } from "@/lib/flashcardTypes"

const gesture = vi.hoisted(() => ({ commit: (_x: number) => {} }))
// Every ref resolves to this fake element: the frame (gesture hook is mocked) and the face, which is also the scroller.
const body = vi.hoisted(() => ({ scrollHeight: 0, clientHeight: 0, scrollBy: (_o: unknown) => {} }))
vi.mock("react", async (importOriginal) => ({
  ...await importOriginal<typeof import("react")>(),
  useRef: () => ({ current: body }),
  useEffect: () => {},
  useLayoutEffect: () => {},
  useState: (value: unknown) => [value, vi.fn()],
}))
vi.mock("@/lib/gestures/useDragGesture", () => ({
  useDragGesture: (_ref: unknown, options: { onCommit: (x: number) => void }) => { gesture.commit = options.onCommit },
}))
import { ReviewCard } from "@/portals/student/screens/flashcards/ReviewCard"

const card = { id: "one", front: "Question", back: "Answer", source: "manual" } as CardDTO
type KeyEvent = { key: string; repeat: boolean; preventDefault: () => void; stopPropagation: () => void }
type PointerPoint = { clientX: number; clientY: number }
type ElementNode = { type: unknown; props: { children?: unknown; onClick?: (e: PointerPoint) => void; onPointerDown?: (e: PointerPoint) => void; onKeyDown?: (e: KeyEvent) => void; role?: string } }
function findButton(node: unknown): ElementNode | undefined {
  if (Array.isArray(node)) return node.map(findButton).find(Boolean)
  if (!node || typeof node !== "object" || !("props" in node)) return undefined
  const element = node as ElementNode
  return element.props.role === "button" ? element : findButton(element.props.children)
}

// The click handler lives on the frame, not on the face: the swipe gesture captures the pointer on the frame, so a real click
// is dispatched there and never reaches the face (the Playwright "mouse or trackpad click" cases drive the real thing).
function findClickable(node: unknown): ElementNode | undefined {
  if (Array.isArray(node)) return node.map(findClickable).find(Boolean)
  if (!node || typeof node !== "object" || !("props" in node)) return undefined
  const element = node as ElementNode
  return element.props.onClick ? element : findClickable(element.props.children)
}

describe("review card interactions", () => {
  it("reveals the front on tap and on a right swipe", () => {
    const reveal = vi.fn()
    const grade = vi.fn()
    const tree = ReviewCard({ card, revealed: false, onReveal: reveal, onGrade: grade })
    findClickable(tree)?.props.onPointerDown?.({ clientX: 10, clientY: 10 })
    findClickable(tree)?.props.onClick?.({ clientX: 10, clientY: 10 })
    gesture.commit(80)
    expect(reveal).toHaveBeenCalledTimes(2)
    expect(grade).not.toHaveBeenCalled()
  })

  it("puts the click on the frame that owns the gesture, never on the face, which is the one named button", () => {
    const tree = ReviewCard({ card, revealed: false, onReveal: vi.fn(), onGrade: vi.fn() })
    const clickable = findClickable(tree)
    const face = findButton(tree)
    expect(clickable, "something handles the click").toBeDefined()
    expect(face, "the face is the named button").toBeDefined()
    expect(clickable, "the click handler is not on the face").not.toBe(face)
    expect(face?.props.onClick, "a click on the face bubbles to the frame").toBeUndefined()
    expect(clickable?.props.role, "the frame is not a second control").toBeUndefined()
  })

  it("ignores a click once the card is flipped", () => {
    const reveal = vi.fn()
    findClickable(ReviewCard({ card, revealed: true, onReveal: reveal, onGrade: vi.fn() }))?.props.onClick?.({ clientX: 10, clientY: 10 })
    expect(reveal).not.toHaveBeenCalled()
  })

  it("treats a press that travelled as a swipe, not a tap, and a press that barely moved as a tap", () => {
    const reveal = vi.fn()
    const frame = findClickable(ReviewCard({ card, revealed: false, onReveal: reveal, onGrade: vi.fn() }))
    frame?.props.onPointerDown?.({ clientX: 200, clientY: 100 })
    frame?.props.onClick?.({ clientX: 40, clientY: 100 })
    expect(reveal, "a mouse drag to the left ends in a click that must not flip the card").not.toHaveBeenCalled()
    frame?.props.onPointerDown?.({ clientX: 200, clientY: 100 })
    frame?.props.onClick?.({ clientX: 203, clientY: 98 })
    expect(reveal).toHaveBeenCalledTimes(1)
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

  it("scrolls a card taller than its face from the arrow and Page keys, and leaves the key alone otherwise", () => {
    const run = (key: string) => {
      const scrollBy = vi.fn()
      body.scrollBy = scrollBy
      const event = { key, repeat: false, preventDefault: vi.fn(), stopPropagation: vi.fn() }
      const reveal = vi.fn()
      findButton(ReviewCard({ card, revealed: false, onReveal: reveal, onGrade: vi.fn() }))?.props.onKeyDown?.(event)
      return { scrollBy, event, reveal }
    }
    body.scrollHeight = 900
    body.clientHeight = 300
    const down = run("ArrowDown")
    expect(down.scrollBy).toHaveBeenCalledWith(expect.objectContaining({ top: 48 }))
    expect(down.event.preventDefault).toHaveBeenCalled()
    expect(down.event.stopPropagation).toHaveBeenCalled()
    expect(run("PageUp").scrollBy).toHaveBeenCalledWith(expect.objectContaining({ top: -255 }))
    // Flipping still works on a long card.
    expect(run(" ").reveal).toHaveBeenCalledTimes(1)

    body.scrollHeight = 300
    const fits = run("ArrowDown")
    expect(fits.scrollBy).not.toHaveBeenCalled()
    expect(fits.event.preventDefault).not.toHaveBeenCalled()
  })
})

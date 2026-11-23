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
type ElementNode = { type: unknown; props: { children?: unknown; onClick?: () => void; role?: string } }
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
})

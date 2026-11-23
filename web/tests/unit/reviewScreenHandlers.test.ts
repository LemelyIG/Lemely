import { beforeEach, describe, expect, it, vi } from "vitest"

/*
 * ReviewScreen called as a function. React's state hooks are replaced by a slot store that survives
 * between calls, so a test can press something and render again, with no DOM and no react-dom.
 */
const h = vi.hoisted(() => ({
  slots: [] as unknown[],
  refs: [] as { current: unknown }[],
  si: 0,
  ri: 0,
  effects: [] as (() => unknown)[],
  listeners: [] as ((e: unknown) => void)[],
  grade: vi.fn(),
  due: { data: undefined as unknown, status: "success", error: null, refetch: vi.fn() },
  mutateAsync: vi.fn(),
  navigate: vi.fn(),
  haptic: vi.fn(),
}))

vi.mock("react", async (importOriginal) => ({
  ...(await importOriginal<typeof import("react")>()),
  useState: (init: unknown) => {
    const k = h.si++
    if (!(k in h.slots)) h.slots[k] = typeof init === "function" ? (init as () => unknown)() : init
    return [h.slots[k], (v: unknown) => { h.slots[k] = typeof v === "function" ? (v as (p: unknown) => unknown)(h.slots[k]) : v }]
  },
  useRef: (init: unknown) => {
    const k = h.ri++
    return (h.refs[k] ??= { current: init })
  },
  useEffect: (fn: () => unknown) => { h.effects.push(fn) },
}))
vi.mock("react-router-dom", () => ({ useNavigate: () => h.navigate, useSearchParams: () => [new URLSearchParams("deck=d1")] }))
vi.mock("@/lib/haptics", () => ({ haptic: h.haptic }))
vi.mock("@/lib/hooks/useReferenceApi", () => ({ useSubjectName: () => "Maths" }))
vi.mock("@/lib/hooks/useFlashcardApi", () => ({
  useDueSession: () => h.due,
  useFlashcardDeck: () => ({ data: { title: "Vectors", origin: "manual", topic: null, marksLost: null, subjectCode: "0580" } }),
  useReviewCard: () => ({ mutateAsync: h.mutateAsync }),
}))
vi.stubGlobal("window", { addEventListener: (_t: string, f: (e: unknown) => void) => { h.listeners.push(f) }, removeEventListener: () => {}, matchMedia: () => ({ matches: false }) })

import { ReviewCard } from "@/portals/student/screens/flashcards/ReviewCard"
import { ReviewScreen } from "@/portals/student/screens/flashcards/ReviewScreen"

type El = { type: unknown; key?: string | null; props: Record<string, unknown> }
function findAll(node: unknown, match: (el: El) => boolean, found: El[] = []): El[] {
  if (Array.isArray(node)) node.forEach((n) => findAll(n, match, found))
  else if (node && typeof node === "object" && "props" in node) {
    const el = node as El
    if (match(el)) found.push(el)
    findAll(el.props.children, match, found)
  }
  return found
}

const card = (id: string) => ({
  id, front: `Front ${id}`, back: `Back ${id}`, source: "manual",
  nextIntervalDays: { again: 0, hard: 1, good: 3, easy: 7 },
})

function render() {
  h.si = 0
  h.ri = 0
  h.effects = []
  h.listeners = []
  const tree = ReviewScreen()
  for (const e of h.effects) e()
  return tree
}
/** The first render takes the snapshot; the second shows the card. */
function start() {
  render()
  return render()
}
const press = (target: unknown, key: string) => {
  const preventDefault = vi.fn()
  h.listeners.at(-1)?.({ key, target, preventDefault })
  return preventDefault
}
const gradeButton = (tree: unknown, label: string) =>
  findAll(tree, (e) => e.type === "button" && JSON.stringify(e.props.children).includes(`"${label}`))[0]
const banner = (tree: unknown) => findAll(tree, (e) => e.props.role === "status")[0]
const focusable = (own: boolean) => ({
  closest: (sel: string) => (sel.startsWith("button") ? { hasAttribute: (n: string) => own && n === "data-review-primary" } : null),
})
const plainTarget = { closest: () => null }

beforeEach(() => {
  h.slots = []
  h.refs = []
  h.mutateAsync = vi.fn().mockResolvedValue({ grade: "good", xpAwarded: 2, card: { id: "a" } })
  h.navigate.mockClear()
  h.haptic.mockClear()
  h.due = {
    data: { cards: [card("a"), card("b")], totalDue: 2, nextDueAt: null, againDelayMinutes: 10, upcoming: [] },
    status: "success", error: null, refetch: vi.fn(),
  }
})

describe("review screen: grading", () => {
  it("sends one grade per card however many times it is pressed", () => {
    let tree = start()
    press(plainTarget, " ")
    tree = render()
    const good = gradeButton(tree, "Good")
    ;(good.props.onClick as () => void)()
    ;(good.props.onClick as () => void)()
    expect(h.mutateAsync).toHaveBeenCalledTimes(1)
    expect(h.mutateAsync.mock.calls[0][0]).toMatchObject({ cardId: "a", grade: "good" })
    expect(typeof h.mutateAsync.mock.calls[0][0].clientReviewId).toBe("string")
  })

  it("moves to the next card before the request settles", () => {
    start()
    press(plainTarget, " ")
    h.mutateAsync.mockReturnValue(new Promise(() => {}))
    ;(gradeButton(render(), "Easy").props.onClick as () => void)()
    const card2 = findAll(render(), (e) => e.type === ReviewCard)[0]
    expect((card2.props.card as { id: string }).id).toBe("b")
    expect(card2.props.revealed).toBe(false)
  })

  it("a failed grade keeps the student's place and offers Retry with the same key", async () => {
    h.mutateAsync.mockRejectedValueOnce(new Error("offline"))
    start()
    press(plainTarget, " ")
    ;(gradeButton(render(), "Good").props.onClick as () => void)()
    await Promise.resolve()
    await Promise.resolve()
    const tree = render()
    expect((findAll(tree, (e) => e.type === ReviewCard)[0].props.card as { id: string }).id).toBe("b")
    expect(JSON.stringify(banner(tree).props.children)).toContain("1 rating not saved yet")

    const first = h.mutateAsync.mock.calls[0][0]
    const retry = findAll(banner(tree), (e) => e.type === "button")[0]
    ;(retry.props.onClick as () => void)()
    ;(retry.props.onClick as () => void)()
    expect(h.mutateAsync).toHaveBeenCalledTimes(2)
    expect(h.mutateAsync.mock.calls[1][0]).toEqual(first)
  })
})

describe("review screen: keyboard", () => {
  it("Space flips, then 1 to 4 rate", () => {
    start()
    expect(press(plainTarget, "1")).not.toHaveBeenCalled()
    expect(press(plainTarget, " ")).toHaveBeenCalled()
    render()
    press(plainTarget, "3")
    expect(h.mutateAsync.mock.calls[0][0]).toMatchObject({ cardId: "a", grade: "good" })
  })

  it("ignores keys typed inside an input", () => {
    start()
    const input = { closest: (s: string) => (s.startsWith("input") ? {} : null) }
    expect(press(input, " ")).not.toHaveBeenCalled()
  })

  it("leaves Space and Enter to a focused End or Retry button", () => {
    start()
    expect(press(focusable(false), "Enter")).not.toHaveBeenCalled()
    expect(press(focusable(false), " ")).not.toHaveBeenCalled()
    expect(press(focusable(true), "Enter")).toHaveBeenCalled()
  })
})

import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { beforeEach, describe, expect, it, vi } from "vitest"

const state = vi.hoisted(() => {
  const mutation = () => ({ isPending: false, isSuccess: false, isError: false, mutate: vi.fn(), reset: vi.fn() })
  return {
    mutation,
    del: mutation(),
    rename: mutation(),
    toasts: [] as { title: string }[],
    sheet: null as unknown,
  }
})

vi.mock("@/components/ui/toast", () => ({ useToast: () => ({ toast: (o: { title: string }) => state.toasts.push(o) }) }))
vi.mock("@/lib/hooks/useFlashcardApi", () => ({
  useDeleteDeck: () => state.del,
  useRenameDeck: () => state.rename,
}))
vi.mock("@/portals/student/screens/flashcards/parts/FcSheet", async () => {
  const { createElement: el } = await import("react")
  return {
    FcSheet: ({ open, children }: { open: boolean; children: never }) => {
      state.sheet = children
      return open ? el("div", null, children) : null
    },
  }
})

import { CardDeleteStep } from "@/portals/student/screens/flashcards/parts/CardDeleteStep"
import { DeleteDeckSheet } from "@/portals/student/screens/flashcards/DeleteDeckSheet"
import { RenameDeckSheet } from "@/portals/student/screens/flashcards/RenameDeckSheet"

type El = { type: unknown; props: Record<string, unknown> }
/** Every element under a rendered tree that matches, found without a DOM. */
function findAll(node: unknown, match: (el: El) => boolean, found: El[] = []): El[] {
  if (Array.isArray(node)) node.forEach((n) => findAll(n, match, found))
  else if (node && typeof node === "object" && "props" in node) {
    const el = node as El
    if (match(el)) found.push(el)
    findAll(el.props.children, match, found)
  }
  return found
}
const button = (tree: unknown, label: string) => {
  const found = findAll(tree, (el) => el.type === "button" && el.props.children === label)[0]
  if (!found) throw new Error(`no "${label}" button`)
  return found
}
const press = (tree: unknown, label: string) => (button(tree, label).props.onClick as () => void)()
const disabled = (tree: unknown, label: string) => button(tree, label).props.disabled === true

beforeEach(() => {
  state.del = state.mutation()
  state.rename = state.mutation()
  state.toasts = []
  state.sheet = null
})

describe("DeleteDeckSheet", () => {
  const onClose = vi.fn()
  const onDeleted = vi.fn()
  const render = () => {
    onClose.mockClear()
    onDeleted.mockClear()
    renderToStaticMarkup(createElement(DeleteDeckSheet, {
      deckId: "d1", title: "Vectors", cardCount: 18, open: true, onClose, onDeleted,
    }))
  }

  it("asks the server first: onDeleted and onClose wait for the delete to succeed", () => {
    render()
    press(state.sheet, "Delete deck")
    expect(state.del.mutate).toHaveBeenCalledTimes(1)
    expect(state.del.mutate.mock.calls[0][0]).toBe("d1")
    expect(onDeleted).not.toHaveBeenCalled()
    expect(onClose).not.toHaveBeenCalled()

    state.del.mutate.mock.calls[0][1].onSuccess()
    expect(onClose).toHaveBeenCalledTimes(1)
    expect(onDeleted).toHaveBeenCalledTimes(1)
    expect(state.toasts.map((t) => t.title)).toEqual(["Vectors deleted"])
  })

  it("a failed delete tells nothing and closes nothing", () => {
    render()
    press(state.sheet, "Delete deck")
    expect(onDeleted).not.toHaveBeenCalled()
    expect(onClose).not.toHaveBeenCalled()
    expect(state.toasts).toEqual([])
  })

  it("Keep it closes the sheet when nothing is in flight", () => {
    render()
    expect(disabled(state.sheet, "Keep it")).toBe(false)
    press(state.sheet, "Keep it")
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it("in flight: Keep it and the confirm are both held", () => {
    state.del.isPending = true
    render()
    expect(disabled(state.sheet, "Keep it")).toBe(true)
    expect(disabled(state.sheet, "Deleting…")).toBe(true)
  })

  it("after success: the confirm cannot send a second DELETE during the exit animation", () => {
    state.del.isSuccess = true
    render()
    expect(disabled(state.sheet, "Delete deck")).toBe(true)
    expect(disabled(state.sheet, "Keep it")).toBe(true)
  })
})

describe("RenameDeckSheet", () => {
  const render = () => renderToStaticMarkup(createElement(RenameDeckSheet, {
    deckId: "d1", title: "Vectors", open: true, onClose: () => {},
  }))

  it("Cancel works when nothing is in flight", () => {
    render()
    expect(disabled(state.sheet, "Cancel")).toBe(false)
  })

  it("Cancel is held while the rename is in flight", () => {
    state.rename.isPending = true
    render()
    expect(disabled(state.sheet, "Cancel")).toBe(true)
  })
})

describe("CardDeleteStep", () => {
  const card = { id: "c1", front: "Magnitude of (x, y)" }
  const step = (s: Partial<{ isPending: boolean; isSuccess: boolean; isError: boolean }> = {}) => CardDeleteStep({
    card, state: { isPending: false, isSuccess: false, isError: false, ...s }, onConfirm: vi.fn(), onKeep: vi.fn(),
  })

  it("names the card and offers Delete card and Keep it", () => {
    const tree = step()
    expect(findAll(tree, (el) => el.type === "p")[0].props.children).toBe(card.front)
    expect(disabled(tree, "Delete card")).toBe(false)
    expect(disabled(tree, "Keep it")).toBe(false)
  })

  it("in flight: Keep it is held, because resetting would not cancel the request", () => {
    const tree = step({ isPending: true })
    expect(disabled(tree, "Keep it")).toBe(true)
    expect(disabled(tree, "Deleting…")).toBe(true)
  })

  it("after success: no second DELETE and no way back to a card that is gone", () => {
    const tree = step({ isSuccess: true })
    expect(disabled(tree, "Delete card")).toBe(true)
    expect(disabled(tree, "Keep it")).toBe(true)
  })

  it("a failure is announced and leaves both buttons usable to try again or keep", () => {
    const tree = step({ isError: true })
    expect(findAll(tree, (el) => el.props.role === "alert")).toHaveLength(1)
    expect(disabled(tree, "Delete card")).toBe(false)
    expect(disabled(tree, "Keep it")).toBe(false)
  })

  it("focus lands on Keep it when the step opens, the safe choice, not on the button that just went", () => {
    expect(button(step(), "Keep it").props.autoFocus).toBe(true)
    expect(button(step(), "Delete card").props.autoFocus).toBeUndefined()
  })

  it("the buttons forward to what the sheet passed", () => {
    const onConfirm = vi.fn()
    const onKeep = vi.fn()
    const tree = CardDeleteStep({ card, state: { isPending: false, isSuccess: false, isError: false }, onConfirm, onKeep })
    press(tree, "Delete card")
    press(tree, "Keep it")
    expect(onConfirm).toHaveBeenCalledTimes(1)
    expect(onKeep).toHaveBeenCalledTimes(1)
  })
})

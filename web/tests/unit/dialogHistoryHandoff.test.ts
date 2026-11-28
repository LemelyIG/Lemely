import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

/*
 * One overlay hands over to another in a single commit: a menu item closes the menu's sheet and opens
 * the sheet it leads to (DeckMenu to Rename/Delete). The closing overlay's `navigate(-1)` is a
 * traversal, so it lands a tick later; the opening overlay's push is synchronous. A push that goes
 * first breaks the hand-off either way a browser may order it:
 *
 * - Chromium fixes the traversal's target when it is issued (measured: at index 2, `go(-1)` then a
 *   push lands on index 1). The move lands on the page's own entry and is taken for ours, so the new
 *   sheet is left open with no current entry and the next Back leaves the page.
 * - Resolved against the entry current when it lands, it stops on the menu's old entry, which is no
 *   move target: the stack takes it for a real Back and closes the sheet that has just opened.
 *
 * Node has no DOM and no renderer, so the real `useDialogHistory` and the real `dialogHistoryStack`
 * run here over a model history (synchronous push, queued traversal, both orderings) and a small
 * hook runner that keeps refs per instance and runs effects in the order React would.
 */

type Ordering = "target fixed when issued" | "target resolved on landing"

interface Instance {
  refs: { current: unknown }[]
  deps: (readonly unknown[] | undefined)[]
  pending: (() => void)[]
  refAt: number
  effectAt: number
}

const env = vi.hoisted(() => {
  const state = {
    rendering: null as Instance | null,
    entries: [{ idx: 0, usr: null as unknown }],
    cursor: 0,
    traversals: [] as { delta: number; from: number }[],
    ordering: "target fixed when issued" as Ordering,
    listeners: new Set<() => void>(),
  }
  return state
})

vi.mock("react", async (importOriginal) => ({
  ...(await importOriginal<typeof import("react")>()),
  useRef: (initial: unknown) => {
    const inst = env.rendering!
    inst.refs[inst.refAt] ??= { current: initial }
    return inst.refs[inst.refAt++]
  },
  useEffect: (effect: () => void, deps?: readonly unknown[]) => {
    const inst = env.rendering!
    const before = inst.deps[inst.effectAt]
    const first = inst.deps.length <= inst.effectAt
    const changed = first || !deps || !before || deps.some((d, i) => !Object.is(d, before[i]))
    inst.deps[inst.effectAt++] = deps
    if (changed) inst.pending.push(effect)
  },
}))

vi.mock("react-router-dom", () => ({
  useLocation: () => ({ pathname: "/student/flashcards/maths", search: "", hash: "", key: "k", state: env.entries[env.cursor].usr }),
  useNavigate: () => (to: unknown, options?: { state?: unknown }) => {
    if (typeof to === "number") {
      env.traversals.push({ delta: to, from: env.cursor })
      return
    }
    env.entries.length = env.cursor + 1
    env.entries.push({ idx: env.cursor + 1, usr: options?.state ?? null })
    env.cursor += 1
  },
}))

type Hook = typeof import("@/lib/nav/useDialogHistory").useDialogHistory
let useDialogHistory: Hook

function sheet() {
  const inst: Instance = { refs: [], deps: [], pending: [], refAt: 0, effectAt: 0 }
  const onClose = vi.fn()
  // Named as a hook because it calls one: this is one render of the instance.
  const useRender = (open: boolean) => {
    inst.refAt = 0
    inst.effectAt = 0
    env.rendering = inst
    useDialogHistory({ open, dismissible: true, onClose })
    env.rendering = null
  }
  return {
    onClose,
    render: useRender,
    runEffects() {
      inst.pending.splice(0).forEach((effect) => effect())
    },
  }
}

/** The next queued traversal lands and fires its popstate; traversals land in the order they were issued. */
function land() {
  const move = env.traversals.shift()
  if (move === undefined) return
  const next = (env.ordering === "target fixed when issued" ? move.from : env.cursor) + move.delta
  if (next < 0 || next >= env.entries.length) return
  env.cursor = next
  ;[...env.listeners].forEach((listener) => listener())
}
function landAll() {
  while (env.traversals.length > 0) land()
}
function pressBack() {
  env.traversals.push({ delta: -1, from: env.cursor })
  landAll()
}
const here = () => env.entries[env.cursor]
const isDialog = (entry: { usr: unknown }) => (entry.usr as { lemelyDialog?: boolean } | null)?.lemelyDialog === true

beforeEach(async () => {
  vi.useFakeTimers()
  env.entries = [{ idx: 0, usr: null }]
  env.cursor = 0
  env.traversals = []
  env.listeners = new Set()
  vi.stubGlobal("window", {
    history: { get state() { return { idx: here().idx, usr: here().usr, key: "k" } } },
    addEventListener: (_: string, listener: () => void) => env.listeners.add(listener),
    removeEventListener: (_: string, listener: () => void) => env.listeners.delete(listener),
  })
  // The stack and the listener flag are module state: each case gets its own.
  vi.resetModules()
  useDialogHistory = (await import("@/lib/nav/useDialogHistory")).useDialogHistory
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

/** The menu is open on its own entry; the sheet it leads to is mounted and closed. */
function openMenu() {
  const menu = sheet()
  const next = sheet()
  menu.render(true)
  next.render(false)
  menu.runEffects()
  next.runEffects()
  expect(env.cursor).toBe(1)
  return { menu, next }
}

describe.each<Ordering>(["target fixed when issued", "target resolved on landing"])("one overlay hands over to another in a single commit (%s)", (ordering) => {
  beforeEach(() => {
    env.ordering = ordering
  })

  it("the sheet a menu item opens stays open when the menu's own unwind lands", () => {
    const { menu, next } = openMenu()

    menu.render(false)
    next.render(true)
    menu.runEffects() // the earlier sibling: its navigate(-1) is queued
    next.runEffects()
    landAll()

    expect(next.onClose).not.toHaveBeenCalled()
    expect(menu.onClose).not.toHaveBeenCalled()
    // One dialog entry above the page, and it is the open sheet's: the menu's is gone, not orphaned.
    expect(env.cursor).toBe(1)
    expect(env.entries).toHaveLength(2)
    expect(isDialog(here())).toBe(true)
  })

  it("Back then closes that sheet and leaves the page's own entry current, with nothing orphaned", () => {
    const { menu, next } = openMenu()
    menu.render(false)
    next.render(true)
    menu.runEffects()
    next.runEffects()
    landAll()

    pressBack()
    expect(next.onClose).toHaveBeenCalledTimes(1)
    next.render(false)
    next.runEffects()
    landAll()

    expect(env.cursor).toBe(0)
    expect(isDialog(here())).toBe(false)
    expect(env.traversals).toEqual([])
  })

  it("closing that sheet from its own button unwinds its entry and no more", () => {
    const { menu, next } = openMenu()
    menu.render(false)
    next.render(true)
    menu.runEffects()
    next.runEffects()
    landAll()

    next.render(false)
    next.runEffects()
    landAll()

    expect(next.onClose).not.toHaveBeenCalled()
    expect(env.cursor).toBe(0)
  })

  it("a sheet closed again before the menu's unwind lands pushes nothing", () => {
    const { menu, next } = openMenu()
    menu.render(false)
    next.render(true)
    menu.runEffects()
    next.runEffects()
    next.render(false)
    next.runEffects()
    landAll()

    expect(env.cursor).toBe(0)
    expect(env.entries.slice(0, env.cursor + 1).some(isDialog)).toBe(false)
    expect(next.onClose).not.toHaveBeenCalled()
  })

  it("the other effect order (the opening sheet first) also ends on the page's own entry", () => {
    const { menu, next } = openMenu()
    menu.render(false)
    next.render(true)
    next.runEffects()
    menu.runEffects()
    landAll()
    expect(next.onClose).not.toHaveBeenCalled()

    pressBack()
    expect(next.onClose).toHaveBeenCalledTimes(1)
    next.render(false)
    next.runEffects()
    landAll()

    expect(env.cursor).toBe(0)
    expect(menu.onClose).not.toHaveBeenCalled()
  })
})

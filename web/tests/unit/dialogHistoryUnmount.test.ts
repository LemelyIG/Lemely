import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

/*
 * An overlay unmounted while a history move is still in flight must not push an entry afterwards.
 * `useDialogHistory` defers two pushes until a traversal lands: a hand-over queued behind another
 * overlay's `navigate(-1)` (`pushWhenCursorSettles`) and a reopen waiting for its own old entry to
 * unwind (`settleUnwind`). Both re-check `mountedRef` when the move lands; without that check the
 * torn-down overlay pushes a dialog entry nothing will ever pop, and the reader's next Back appears
 * to do nothing.
 *
 * Node has no DOM and no renderer, so the real hook and the real `dialogHistoryStack` run over a model
 * history and a small hook runner (the same one as dialogHistoryHandoff.test.ts, plus an unmount that
 * runs effect cleanups).
 */

interface Instance {
  refs: { current: unknown }[]
  deps: (readonly unknown[] | undefined)[]
  pending: (() => void | (() => void))[]
  cleanups: (() => void)[]
  refAt: number
  effectAt: number
}

const env = vi.hoisted(() => ({
  rendering: null as Instance | null,
  entries: [{ idx: 0, usr: null as unknown }],
  cursor: 0,
  traversals: [] as { delta: number; from: number }[],
  listeners: new Set<() => void>(),
}))

vi.mock("react", async (importOriginal) => ({
  ...(await importOriginal<typeof import("react")>()),
  useRef: (initial: unknown) => {
    const inst = env.rendering!
    inst.refs[inst.refAt] ??= { current: initial }
    return inst.refs[inst.refAt++]
  },
  useEffect: (effect: () => void | (() => void), deps?: readonly unknown[]) => {
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
  const inst: Instance = { refs: [], deps: [], pending: [], cleanups: [], refAt: 0, effectAt: 0 }
  const useRender = (open: boolean) => {
    inst.refAt = 0
    inst.effectAt = 0
    env.rendering = inst
    useDialogHistory({ open, dismissible: true, onClose: vi.fn() })
    env.rendering = null
  }
  return {
    render: useRender,
    runEffects() {
      inst.pending.splice(0).forEach((effect) => {
        const cleanup = effect()
        if (typeof cleanup === "function") inst.cleanups.push(cleanup)
      })
    },
    unmount() {
      inst.cleanups.splice(0).forEach((cleanup) => cleanup())
    },
  }
}

function landAll() {
  while (env.traversals.length > 0) {
    const move = env.traversals.shift()!
    const next = move.from + move.delta
    if (next < 0 || next >= env.entries.length) continue
    env.cursor = next
    ;[...env.listeners].forEach((listener) => listener())
  }
}

beforeEach(async () => {
  vi.useFakeTimers()
  env.entries = [{ idx: 0, usr: null }]
  env.cursor = 0
  env.traversals = []
  env.listeners = new Set()
  vi.stubGlobal("window", {
    history: { get state() { return { idx: env.entries[env.cursor].idx, usr: env.entries[env.cursor].usr, key: "k" } } },
    addEventListener: (_: string, listener: () => void) => env.listeners.add(listener),
    removeEventListener: (_: string, listener: () => void) => env.listeners.delete(listener),
  })
  vi.resetModules()
  useDialogHistory = (await import("@/lib/nav/useDialogHistory")).useDialogHistory
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe("an overlay unmounted while a history move is in flight", () => {
  it("does not push the entry it queued behind another overlay's unwind", () => {
    const menu = sheet()
    const next = sheet()
    menu.render(true)
    next.render(false)
    menu.runEffects()
    next.runEffects()
    expect(env.cursor).toBe(1)

    menu.render(false)
    next.render(true)
    menu.runEffects() // the menu's navigate(-1) is now in flight
    next.runEffects() // the sheet's push is queued behind it
    next.unmount() // the sheet's screen goes away before the move lands
    landAll()

    expect(env.cursor).toBe(0)
    expect(env.entries.slice(0, env.cursor + 1).some((e) => (e.usr as { lemelyDialog?: boolean } | null)?.lemelyDialog)).toBe(false)
  })

  it("does not push the reopen that waited for its own old entry to unwind", () => {
    const only = sheet()
    only.render(true)
    only.runEffects()
    expect(env.cursor).toBe(1)

    only.render(false)
    only.runEffects() // unwind issued
    only.render(true)
    only.runEffects() // reopen: push deferred until the unwind lands
    only.unmount()
    landAll()

    expect(env.cursor).toBe(0)
    expect(env.entries.slice(0, env.cursor + 1).some((e) => (e.usr as { lemelyDialog?: boolean } | null)?.lemelyDialog)).toBe(false)
  })
})

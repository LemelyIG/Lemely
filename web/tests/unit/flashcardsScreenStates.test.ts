// web/tests/unit/flashcardsScreenStates.test.ts
// Task 10 P1 review fixes, against the real FlashcardsScreen. The query hooks, router and toast are
// mocked; the retry mutation is the real hook on a real QueryClient so "in flight" is the library's
// truth, not a stand-in. Node has no DOM, so the screen is rendered with react-dom/server and the
// callbacks it hands to its children are called directly, then it is rendered again.
import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

interface CapturedRow { row: { id: string }; retrying?: boolean; onRetry?: () => void }
interface CapturedPanel { deckId: string; onDeleted: () => void }

const h = vi.hoisted(() => ({
  navigate: vi.fn(),
  toast: vi.fn(),
  retryRequest: vi.fn(),
  wide: false,
  location: { pathname: "/student/flashcards", search: "", state: null as unknown },
  decks: {} as Record<string, unknown>,
  rows: [] as CapturedRow[],
  panels: [] as CapturedPanel[],
}))

vi.mock("react-router-dom", async () => {
  const { createElement: el } = await import("react")
  return {
    useNavigate: () => h.navigate,
    useLocation: () => h.location,
    useParams: () => ({}),
    useSearchParams: () => [new URLSearchParams(h.location.search)],
    Link: ({ to, children, className }: { to: string; children?: unknown; className?: string }) =>
      el("a", { href: to, className }, children as never),
  }
})
vi.mock("@/components/ui/toast", () => ({ useToast: () => ({ toast: h.toast }) }))
vi.mock("@/lib/gestures/useLongPress", () => ({ useLongPress: () => ({}) }))
vi.mock("@/portals/student/screens/flashcards/isWide", () => ({
  isWide: () => h.wide,
  useIsWide: () => h.wide,
}))
vi.mock("@/lib/hooks/useStudentApi", () => ({ useOverview: () => ({ data: { subjects: [{ code: "0580", name: "Maths" }] } }) }))
vi.mock("@/lib/hooks/useReferenceApi", () => ({ useReference: () => ({ data: undefined }) }))
vi.mock("@/lib/flashcardApi", async (importActual) => {
  const actual = await importActual<typeof import("@/lib/flashcardApi")>()
  return { ...actual, flashcardApi: { ...actual.flashcardApi, retryGeneration: h.retryRequest } }
})
vi.mock("@/lib/hooks/useFlashcardApi", async (importActual) => {
  const actual = await importActual<typeof import("@/lib/hooks/useFlashcardApi")>()
  return {
    ...actual,
    useFlashcardDecks: () => h.decks,
    useDueSession: () => ({ data: { cards: [], totalDue: 0, nextDueAt: null, upcoming: [], againDelayMinutes: 10 }, status: "success" }),
    useWeakTopics: () => ({ data: [], status: "success" }),
  }
})
vi.mock("@/portals/student/screens/flashcards/parts/DeckRow", async () => {
  const { createElement: el } = await import("react")
  return {
    DeckRow: (props: CapturedRow) => {
      h.rows.push(props)
      return el("li", { "data-row": props.row.id, "data-retrying": String(Boolean(props.retrying)) })
    },
  }
})
vi.mock("@/portals/student/screens/flashcards/DeckBody", async () => {
  const { createElement: el } = await import("react")
  return {
    DeckPanel: (props: CapturedPanel) => {
      h.panels.push(props)
      return el("div", { "data-panel": props.deckId })
    },
  }
})
vi.mock("@/portals/student/screens/flashcards/DeckMenu", () => ({ DeckMenu: () => null }))
vi.mock("@/portals/student/screens/flashcards/NewDeckSheet", () => ({ NewDeckSheet: () => null }))

import { ApiError } from "@/lib/api"
import { flashcardKeys } from "@/lib/flashcardApi"
import { useRetryGeneration } from "@/lib/hooks/useFlashcardApi"
import type { DeckSummaryDTO, GenerationStatusDTO } from "@/lib/flashcardTypes"
import { FlashcardsScreen } from "@/portals/student/screens/flashcards/FlashcardsScreen"

function deck(o: Partial<DeckSummaryDTO> & { id: string }): DeckSummaryDTO {
  return {
    subjectCode: "0580", topic: null, title: o.id, description: null, origin: "manual", cardCount: 10,
    dueCount: 0, createdAt: "2026-11-01T00:00:00Z", newCount: 4, learningCount: 4, knownCount: 2,
    marksLost: null, generationStatus: "ready", requestedCount: null, ...o,
  }
}

const refetch = vi.fn()
function query(o: { status: "pending" | "error" | "success"; data?: DeckSummaryDTO[]; error?: unknown }) {
  return { status: o.status, data: o.data, error: o.error ?? null, refetch, fetchStatus: "idle" }
}

let client: QueryClient
function render(): string {
  h.rows.length = 0
  h.panels.length = 0
  return renderToStaticMarkup(createElement(QueryClientProvider, { client }, createElement(FlashcardsScreen)))
}
const lastRow = (id: string) => [...h.rows].reverse().find((r) => r.row.id === id)
const flush = () => new Promise((resolve) => setTimeout(resolve, 20))

beforeEach(() => {
  client = new QueryClient({ defaultOptions: { mutations: { retry: false }, queries: { retry: false } } })
  h.wide = false
  h.location = { pathname: "/student/flashcards", search: "", state: null }
  h.navigate.mockReset()
  h.toast.mockReset()
  h.retryRequest.mockReset()
  refetch.mockReset()
  h.decks = query({ status: "success", data: [deck({ id: "a" }), deck({ id: "b" })] })
})
afterEach(() => client.clear())

describe("a failed refetch with decks already loaded", () => {
  it("keeps the shelf and says so inline instead of replacing it with the load error", () => {
    h.decks = query({ status: "error", data: [deck({ id: "a" }), deck({ id: "b" })], error: new Error("poll failed") })
    const html = render()
    expect(html).toContain('data-row="a"')
    expect(html).toContain('data-row="b"')
    expect(html).not.toContain("Couldn’t load your decks")
    expect(html).toContain("Couldn’t refresh your decks")
  })

  it("shows no notice while the refetch is healthy", () => {
    const html = render()
    expect(html).toContain('data-row="a"')
    expect(html).not.toContain("Couldn’t refresh")
  })
})

describe("the first load failing", () => {
  it("shows the FE state: sad Binny, heading, line, Try again, Back to Home", () => {
    h.decks = query({ status: "error", error: new Error("boom") })
    const html = render()
    expect(html).toContain('data-mood="sad"')
    expect(html).toContain("<h2")
    expect(html).toContain("Couldn’t load your decks")
    expect(html).toContain("Check your connection, then try again.")
    expect(html).toContain("Try again")
    expect(html).toContain('href="/student"')
    expect(html).toContain("Back to Home")
    expect(html).not.toContain('data-row=')
  })

  it("keeps the offline state for a request that never left the device", () => {
    h.decks = query({ status: "error", error: new ApiError(0, "Failed to fetch") })
    const html = render()
    expect(html).not.toContain('data-mood="sad"')
    expect(html).toContain("Couldn’t load your decks")
    expect(html).toContain("Back to Home")
  })
})

describe("the empty shelf", () => {
  it("says “No decks yet” once, in the header, and gives the Binny heading its own line", () => {
    h.decks = query({ status: "success", data: [] })
    const html = render()
    expect(html.split("No decks yet").length - 1).toBe(1)
    expect(html).toContain("Your shelf is empty")
  })
})

describe("retrying failed decks", () => {
  beforeEach(() => {
    h.decks = query({
      status: "success",
      data: [deck({ id: "a", generationStatus: "failed" }), deck({ id: "b", generationStatus: "failed" })],
    })
  })

  it("exposes only the retry action and ignores per-call callbacks after the session is cleared", async () => {
    let retry!: ReturnType<typeof useRetryGeneration>
    const callback = vi.fn()
    let settle!: (state: GenerationStatusDTO) => void
    h.retryRequest.mockImplementation(() => new Promise((resolve) => { settle = resolve }))
    function Probe() {
      retry = useRetryGeneration()
      return null
    }
    renderToStaticMarkup(createElement(QueryClientProvider, { client }, createElement(Probe)))
    expect(Object.keys(retry)).toEqual(["mutate"])
    // Extra arguments from untyped callers must not reach the underlying observer.
    ;(retry.mutate as (...args: unknown[]) => void)("a", { onSuccess: callback, onSettled: callback })
    await flush()
    client.clear()
    settle({ deckId: "a", status: "ready", requestedCount: 10, generatedCount: 10, error: null })
    await flush()
    expect(callback).not.toHaveBeenCalled()
    expect(client.getQueryData(flashcardKeys.generation("a"))).toBeUndefined()
  })

  it("retrying A then B keeps A busy and sends one request per deck", async () => {
    const settle: Array<() => void> = []
    h.retryRequest.mockImplementation(() => new Promise((resolve) => settle.push(() => resolve({ status: "writing" }))))
    render()
    const firstA = lastRow("a")
    lastRow("a")?.onRetry?.()
    render()
    expect(lastRow("a")?.retrying).toBe(true)
    expect(lastRow("b")?.retrying).toBe(false)

    lastRow("b")?.onRetry?.()
    render()
    expect(lastRow("a")?.retrying).toBe(true)
    expect(lastRow("b")?.retrying).toBe(true)

    // A tap on A from a render that predates the first request lands in the same frame; it must not send again.
    firstA?.onRetry?.()
    await flush()
    expect(h.retryRequest.mock.calls.map((c) => c[0])).toEqual(["a", "b"])

    // Settling the requests frees both rows again; the in-flight table must not outlive the test.
    settle.forEach((done) => done())
    await flush()
    render()
    expect(lastRow("a")?.retrying).toBe(false)
    expect(lastRow("b")?.retrying).toBe(false)
    lastRow("a")?.onRetry?.()
    await flush()
    expect(h.retryRequest).toHaveBeenCalledTimes(3)
    settle[2]()
    await flush()
  })

  // renderToStaticMarkup never unmounts, so this does not prove unmount survival. It proves that
  // stale same-frame calls and a second screen instance on one QueryClient share one mutation per
  // deck, and that the failure callback lives on that mutation: one toast each, then a new retry runs.
  it("shares one mutation and one toast per deck across stale and second-instance calls, then permits another retry", async () => {
    const reject: Array<(error: Error) => void> = []
    h.retryRequest.mockImplementation(() => new Promise((_resolve, fail) => reject.push(fail)))
    render()
    const staleRetry = lastRow("a")?.onRetry
    staleRetry?.()
    staleRetry?.()
    render() // a new screen instance sharing the same QueryClient
    lastRow("a")?.onRetry?.()
    lastRow("b")?.onRetry?.()
    await flush()
    expect(h.retryRequest.mock.calls.map((call) => call[0])).toEqual(["a", "b"])
    const pending = client.getMutationCache().getAll().filter((m) => m.state.status === "pending").length
    reject.forEach((fail) => fail(new Error("nope")))
    await flush()
    expect(h.toast).toHaveBeenCalledTimes(2)
    expect(pending).toBe(2)
    render()
    lastRow("a")?.onRetry?.()
    await flush()
    expect(h.retryRequest).toHaveBeenCalledTimes(3)
    reject[2](new Error("again"))
    await flush()
    expect(h.toast).toHaveBeenCalledTimes(3)
  })

  it("a cleared session neither swallows the next retry nor toasts the old request's late failure", async () => {
    const reject: Array<(error: Error) => void> = []
    h.retryRequest.mockImplementation(() => new Promise((_resolve, fail) => reject.push(fail)))
    render()
    lastRow("a")?.onRetry?.()
    await flush()
    expect(h.retryRequest).toHaveBeenCalledTimes(1)

    client.clear() // sign-out: web/src/lib/auth/storage.ts clearQueries
    render()
    expect(lastRow("a")?.retrying).toBe(false)

    lastRow("a")?.onRetry?.()
    await flush()
    expect(h.retryRequest).toHaveBeenCalledTimes(2)
    render()
    expect(lastRow("a")?.retrying).toBe(true)

    reject[0](new Error("old session"))
    await flush()
    expect(h.toast).not.toHaveBeenCalled()
    reject[1](new Error("new session"))
    await flush()
    expect(h.toast).toHaveBeenCalledTimes(1)
  })

  it("a late success from a cleared session never overwrites the new session's cache or refetches for it", async () => {
    const settle: Array<(state: GenerationStatusDTO) => void> = []
    h.retryRequest.mockImplementation(() => new Promise((resolve) => settle.push(resolve)))
    const state = (generatedCount: number): GenerationStatusDTO =>
      ({ deckId: "a", status: "ready", requestedCount: 10, generatedCount, error: null })
    const invalidate = vi.spyOn(client, "invalidateQueries")
    render()
    lastRow("a")?.onRetry?.()
    await flush()

    client.clear() // sign-out, then a second sign-in on the same QueryClient
    render()
    lastRow("a")?.onRetry?.()
    await flush()
    expect(h.retryRequest).toHaveBeenCalledTimes(2)

    settle[1](state(2)) // the new session's request lands first
    await flush()
    expect(client.getQueryData(flashcardKeys.generation("a"))).toEqual(state(2))
    const refetches = invalidate.mock.calls.length
    expect(refetches).toBeGreaterThan(0)

    settle[0](state(1)) // the old session's request lands late
    await flush()
    expect(client.getQueryData(flashcardKeys.generation("a"))).toEqual(state(2))
    expect(invalidate.mock.calls.length).toBe(refetches)
    expect(h.toast).not.toHaveBeenCalled()
  })

  it("a live request is still owned: its success seeds the cache once, and a restored pending mutation is not mistaken for it", async () => {
    const settle: Array<(state: GenerationStatusDTO) => void> = []
    h.retryRequest.mockImplementation(() => new Promise((resolve) => settle.push(resolve)))
    const ready: GenerationStatusDTO = { deckId: "a", status: "ready", requestedCount: 10, generatedCount: 10, error: null }
    const invalidate = vi.spyOn(client, "invalidateQueries")
    render()
    const retryA = lastRow("a")?.onRetry // a stale closure: it predates the restored mutation below
    // A pending mutation for the same deck that this screen never started (restored, nothing running it).
    const restored = client.getMutationCache().build(client, {
      mutationKey: ["flashcards", "retry-generation"],
      mutationFn: () => new Promise<GenerationStatusDTO>(() => {}),
    })
    restored.state = { ...restored.state, status: "pending", variables: "a" }
    retryA?.()
    retryA?.() // same frame: joins the request just started, not the restored mutation
    await flush()
    expect(h.retryRequest).toHaveBeenCalledTimes(1)

    client.getMutationCache().remove(restored) // the restored one going away must not orphan the live request
    settle[0](ready)
    await flush()
    expect(client.getQueryData(flashcardKeys.generation("a"))).toEqual(ready)
    expect(invalidate.mock.calls.filter(([f]) => JSON.stringify(f?.queryKey) === JSON.stringify(flashcardKeys.deck("a")))).toHaveLength(1)
  })

  it("toasts every failure, not only the latest deck's", async () => {
    h.retryRequest.mockImplementation(() => Promise.reject(new Error("nope")))
    render()
    lastRow("a")?.onRetry?.()
    lastRow("b")?.onRetry?.()
    await flush()
    expect(h.toast).toHaveBeenCalledTimes(2)
    expect(h.toast).toHaveBeenCalledWith(expect.objectContaining({ variant: "error", title: "Couldn’t retry that deck" }))
    render()
    expect(lastRow("a")?.retrying).toBe(false)
    expect(lastRow("b")?.retrying).toBe(false)
  })
})

describe("the deck side panel", () => {
  beforeEach(() => {
    h.location = { pathname: "/student/flashcards", search: "?deck=a&x=1", state: null }
  })

  it("is not mounted below the wide breakpoint", () => {
    h.wide = false
    const html = render()
    expect(html).not.toContain("<aside")
    expect(h.panels).toHaveLength(0)
  })

  it("is mounted at the wide breakpoint with a selection", () => {
    h.wide = true
    const html = render()
    expect(html).toContain("<aside")
    expect(h.panels.map((p) => p.deckId)).toEqual(["a"])
  })

  it("clearing the selection drops ?deck= and keeps the other params", () => {
    h.wide = true
    render()
    h.panels[0]?.onDeleted()
    expect(h.navigate).toHaveBeenCalledWith("/student/flashcards?x=1", { replace: true, state: null })
  })
})

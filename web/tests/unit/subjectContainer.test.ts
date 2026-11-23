import { QueryClient, QueryObserver, type QueryObserverResult } from "@tanstack/react-query"
import { isValidElement, type ComponentProps, type ElementType, type ReactNode } from "react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { ApiError } from "@/lib/api"
import type { Subject as SubjectDTO } from "@/lib/studentTypes"
import { Subject } from "@/portals/student/screens/Subject"
import { SubjectBody } from "@/portals/student/screens/subject/SubjectBody"
import { SubjectError } from "@/portals/student/screens/subject/SubjectError"
import { SubjectFirstRun } from "@/portals/student/screens/subject/SubjectFirstRun"
import { SubjectLoading } from "@/portals/student/screens/subject/SubjectLoading"
import { SubjectRefreshNotice } from "@/portals/student/screens/subject/SubjectRefreshNotice"
import { MATHS, MATHS_ONE } from "@/portals/student/screens/subject/fixtures"

/*
 * The container's two query rules, proved against a real TanStack v5 QueryObserver rather than a
 * hand-built result. v5 reports `status: "error"` for a failed refetch yet keeps the last good `data`,
 * so the container must pass `hasData` into the screen-state facts: a failed first load is the error
 * screen, a failed refetch over loaded data keeps the body and adds the notice. The data hooks are the
 * only thing replaced (by the observer's own result); `Subject` is called directly, which is safe
 * because every hook it calls is stubbed here, and its returned element tree is read.
 */
const stub = vi.hoisted(() => ({ result: undefined as unknown, search: "" }))
vi.mock("react-router-dom", async (importOriginal) => ({
  ...(await importOriginal<typeof import("react-router-dom")>()),
  useParams: () => ({ code: "0580" }),
  useSearchParams: () => [new URLSearchParams(stub.search), vi.fn()],
}))
vi.mock("@/lib/hooks/useStudentApi", () => ({ useSubject: () => stub.result }))
vi.mock("@/lib/hooks/useReferenceApi", () => ({ useReference: () => ({ data: undefined }), useSubjectName: () => "Mathematics" }))
vi.mock("@/lib/hooks/useAnnouncementApi", () => ({ useExamCalendar: () => ({ data: undefined }) }))
vi.mock("@/lib/hooks/useFlashcardApi", () => ({ useFlashcardDecks: () => ({ data: [] }) }))
vi.mock("@/portals/student/screens/subject/useMinWidth", () => ({ useMinWidth: () => false }))

function propsOf<T extends ElementType>(root: ReactNode, type: T): ComponentProps<T>[] {
  const found: ComponentProps<T>[] = []
  const walk = (node: ReactNode): void => {
    if (Array.isArray(node)) return node.forEach(walk)
    if (!isValidElement<{ children?: ReactNode }>(node)) return
    if (node.type === type) found.push(node.props as unknown as ComponentProps<T>)
    walk(node.props.children)
  }
  walk(root)
  return found
}

const KEY = ["student", "subject", "0580"]
const cleanups: (() => void)[] = []
afterEach(() => {
  cleanups.splice(0).forEach((fn) => fn())
  stub.search = ""
})

type Step = () => Promise<SubjectDTO>
const ok = (data: SubjectDTO): Step => () => Promise.resolve(data)
const fail = (status: number, detail?: string): Step => () => Promise.reject(new ApiError(status, `HTTP ${status}`, detail))
const absent = (kind: "history" | "papers"): Step => fail(404, `No ${kind} for subject 0580`)

/** A real observer over a query that answers each call from `steps` in order. */
function observe(...steps: Step[]) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } })
  let calls = 0
  const observer = new QueryObserver<SubjectDTO, Error>(client, { queryKey: KEY, queryFn: () => steps[Math.min(calls++, steps.length - 1)]() })
  const stop = observer.subscribe(() => {})
  cleanups.push(() => {
    stop()
    client.clear()
  })
  const result = (): QueryObserverResult<SubjectDTO, Error> => observer.getCurrentResult()
  return {
    observer,
    result,
    calls: () => calls,
    settled: (status: "success" | "error") =>
      vi.waitFor(() => {
        expect(result().fetchStatus).toBe("idle")
        expect(result().status).toBe(status)
      }),
  }
}

/** The element tree the container returns for the observer's current result. */
function screenFor(result: QueryObserverResult<SubjectDTO, Error>) {
  stub.result = result
  return Subject()
}
const count = (tree: ReactNode, type: ElementType) => propsOf(tree, type).length

describe("Subject container: a failed first load", () => {
  it("shows the error screen, with no body and no refresh notice", async () => {
    const q = observe(fail(500), ok(MATHS))
    await q.settled("error")
    expect(q.result().data).toBeUndefined()
    const tree = screenFor(q.result())
    expect(count(tree, SubjectError)).toBe(1)
    expect(propsOf(tree, SubjectError)[0].name).toBe("Mathematics")
    expect(count(tree, SubjectBody)).toBe(0)
    expect(count(tree, SubjectRefreshNotice)).toBe(0)
  })
  it("retries for real: the screen's retry runs the query again and the body arrives", async () => {
    const q = observe(fail(500), ok(MATHS))
    await q.settled("error")
    expect(q.calls()).toBe(1)
    propsOf(screenFor(q.result()), SubjectError)[0].onRetry()
    await q.settled("success")
    expect(q.calls()).toBe(2)
    const tree = screenFor(q.result())
    expect(count(tree, SubjectError)).toBe(0)
    expect(count(tree, SubjectBody)).toBe(1)
  })
  it("treats an authoritative absence as the first run, never an error", async () => {
    const q = observe(absent("history"))
    await q.settled("error")
    const tree = screenFor(q.result())
    expect(count(tree, SubjectFirstRun)).toBe(1)
    expect(count(tree, SubjectError)).toBe(0)
    expect(count(tree, SubjectRefreshNotice)).toBe(0)
  })
  it("shows an error for an unrelated 404", async () => {
    const q = observe(fail(404, "Not Found"))
    await q.settled("error")
    const tree = screenFor(q.result())
    expect(count(tree, SubjectError)).toBe(1)
    expect(count(tree, SubjectFirstRun)).toBe(0)
  })
  it("shows the loading screen while the first request is in flight", () => {
    const q = observe(() => new Promise<SubjectDTO>(() => {}))
    const tree = screenFor(q.result())
    expect(count(tree, SubjectLoading)).toBe(1)
    expect(count(tree, SubjectError)).toBe(0)
  })
})

describe("Subject container: a failed refetch over loaded data", () => {
  it.each(["history", "papers"] as const)("shows first run after cached data receives no %s", async (kind) => {
    const q = observe(ok(MATHS_ONE), absent(kind))
    await q.settled("success")
    void q.observer.refetch()
    await q.settled("error")
    expect(q.result().data).toEqual(MATHS_ONE)
    const tree = screenFor(q.result())
    expect(count(tree, SubjectFirstRun)).toBe(1)
    expect(count(tree, SubjectBody)).toBe(0)
    expect(count(tree, SubjectRefreshNotice)).toBe(0)
  })
  it("retains cached data and retry on an unrelated 404", async () => {
    const q = observe(ok(MATHS_ONE), fail(404, "Not Found"))
    await q.settled("success")
    void q.observer.refetch()
    await q.settled("error")
    const tree = screenFor(q.result())
    expect(count(tree, SubjectBody)).toBe(1)
    expect(count(tree, SubjectRefreshNotice)).toBe(1)
  })
  async function loadedThenFailed(data: SubjectDTO) {
    const q = observe(ok(data), fail(500), ok(data))
    await q.settled("success")
    void q.observer.refetch()
    await q.settled("error")
    // The v5 fact the whole rule rests on: error status, last good payload still held.
    expect(q.result().status).toBe("error")
    expect(q.result().data).toEqual(data)
    return q
  }

  it("keeps the full body and adds the refresh notice instead of the error screen", async () => {
    const q = await loadedThenFailed(MATHS)
    const tree = screenFor(q.result())
    expect(count(tree, SubjectError)).toBe(0)
    expect(count(tree, SubjectFirstRun)).toBe(0)
    const body = propsOf(tree, SubjectBody)
    expect(body).toHaveLength(1)
    expect(body[0].view.mode).toBe("full")
    const notice = propsOf(tree, SubjectRefreshNotice)
    expect(notice).toHaveLength(1)
    expect(notice[0].name).toBe(MATHS.header.name)
    expect(notice[0].pending).toBe(false)
  })
  it("keeps the sparse body too", async () => {
    const q = await loadedThenFailed(MATHS_ONE)
    const tree = screenFor(q.result())
    expect(propsOf(tree, SubjectBody)[0].view.mode).toBe("sparse")
    expect(count(tree, SubjectRefreshNotice)).toBe(1)
    expect(count(tree, SubjectError)).toBe(0)
  })
  it("retries with the query's own refetch, disables the notice's button while it runs, then clears it", async () => {
    let release: (data: SubjectDTO) => void = () => {}
    const q = observe(ok(MATHS), fail(500), () => new Promise<SubjectDTO>((resolve) => (release = resolve)))
    await q.settled("success")
    void q.observer.refetch()
    await q.settled("error")
    expect(q.calls()).toBe(2)

    propsOf(screenFor(q.result()), SubjectRefreshNotice)[0].onRetry()
    await vi.waitFor(() => expect(q.result().isFetching).toBe(true))
    expect(q.calls()).toBe(3)
    const inFlight = screenFor(q.result())
    expect(propsOf(inFlight, SubjectRefreshNotice)[0].pending).toBe(true)
    expect(count(inFlight, SubjectBody)).toBe(1)
    expect(count(inFlight, SubjectError)).toBe(0)

    release(MATHS)
    await q.settled("success")
    const healed = screenFor(q.result())
    expect(count(healed, SubjectRefreshNotice)).toBe(0)
    expect(count(healed, SubjectBody)).toBe(1)
  })
  it("shows no notice after a successful load", async () => {
    const q = observe(ok(MATHS))
    await q.settled("success")
    expect(count(screenFor(q.result()), SubjectRefreshNotice)).toBe(0)
  })
})

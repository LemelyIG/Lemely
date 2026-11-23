import { readFileSync } from "node:fs"
import { join } from "node:path"
import { QueryClient, QueryObserver } from "@tanstack/react-query"
import { matchRoutes } from "react-router-dom"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { ApiError, request } from "@/lib/api"
import * as studyPlanApi from "@/lib/hooks/useStudyPlanApi"
import { COPY, movedToast } from "@/portals/student/screens/studyplan/planCopy"
import {
  dayScrollTarget,
  gateWeek,
  moveFailureMessage,
  planListUrl,
  planSessionUrl,
} from "@/portals/student/screens/studyplan/planFlow"
import type { StudyPlanOverviewDTO } from "@/lib/studyPlanTypes"

/*
 * L9 · the study plan orchestrator (Task 11).
 *
 * The vitest env is node with no DOM, so the screen itself is not mounted.
 * What is checked instead is everything that decides what it does: the gate
 * between the week query and the screen (against a REAL `QueryObserver`, run
 * through the real `useStudyPlanWeek` options), the failure copy, the URLs and
 * the scroll target. The wiring that remains (routes, `QueryState`, the hooks
 * the screen calls) is read out of the source as text, the way
 * `queryStateGate.test.ts` and `hallmarkStamp.test.ts` do.
 */

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>()
  return { ...actual, request: vi.fn() }
})

// `useQuery` becomes an identity, so `useStudyPlanWeek()` returns the options
// the real hook would have handed to react-query, and a real observer runs them.
vi.mock("@tanstack/react-query", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@tanstack/react-query")>()
  return { ...actual, useQuery: (options: unknown) => options }
})

const WEB = join(import.meta.dirname, "..", "..")
/** A file as text, or "" when it is missing, so each check below fails on its own assertion. */
const read = (path: string) => {
  try {
    return readFileSync(join(WEB, path), "utf8")
  } catch {
    return ""
  }
}
const SCREEN = read("src/portals/student/screens/studyplan/StudyPlanScreen.tsx")
const ROUTES = read("src/portals/student/index.tsx")

const OVERVIEW: StudyPlanOverviewDTO = {
  today: "2026-08-06",
  weekStart: "2026-08-03",
  weekEnd: "2026-08-09",
  subjects: [],
}

const settle = () => new Promise((resolve) => setTimeout(resolve, 20))

describe("the week query gate (real QueryObserver)", () => {
  let client: QueryClient
  let stop: (() => void) | undefined
  beforeEach(() => {
    client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    vi.mocked(request).mockReset()
  })
  afterEach(() => stop?.())

  /** Mount the real hook's options on a real observer, the way React does. */
  function mount(): QueryObserver<StudyPlanOverviewDTO, Error> {
    const options = studyPlanApi.useStudyPlanWeek() as unknown as ConstructorParameters<
      typeof QueryObserver<StudyPlanOverviewDTO, Error>
    >[1]
    const observer = new QueryObserver<StudyPlanOverviewDTO, Error>(client, options)
    stop = observer.subscribe(() => {})
    return observer
  }

  it("holds on the skeleton while the first fetch is in flight", () => {
    vi.mocked(request).mockReturnValue(new Promise(() => {}))
    const gate = gateWeek(mount().getCurrentResult())
    expect(gate.status).toBe("pending")
    expect(gate.data).toBeUndefined()
  })

  it("passes a loaded week straight through", async () => {
    vi.mocked(request).mockResolvedValue(OVERVIEW)
    const observer = mount()
    await settle()
    const gate = gateWeek(observer.getCurrentResult())
    expect(gate.status).toBe("success")
    expect(gate.data).toBe(OVERVIEW)
  })

  it("reports a load failure only when there is no week to show", async () => {
    vi.mocked(request).mockRejectedValue(new ApiError(500, "500", undefined))
    const observer = mount()
    await settle()
    const gate = gateWeek(observer.getCurrentResult())
    expect(gate.status).toBe("error")
    expect(gate.data).toBeUndefined()
  })

  it("keeps the cached week when a refetch fails", async () => {
    client.setQueryData(studyPlanApi.studyPlanKeys.week, OVERVIEW)
    vi.mocked(request).mockRejectedValue(new ApiError(0, "offline", undefined))
    const observer = mount()
    await settle()
    // What react-query hands the screen: an error status that still carries the data.
    const raw = observer.getCurrentResult()
    expect(raw.status).toBe("error")
    expect(raw.data).toBe(OVERVIEW)
    // The screen must not trade a working week for an error panel.
    const gate = gateWeek(raw)
    expect(gate.status).toBe("success")
    expect(gate.data).toBe(OVERVIEW)
  })

  it("wires the retry to the query's own refetch", async () => {
    vi.mocked(request).mockRejectedValue(new ApiError(500, "500", undefined))
    const observer = mount()
    await settle()
    expect(vi.mocked(request)).toHaveBeenCalledTimes(1)
    vi.mocked(request).mockResolvedValue(OVERVIEW)
    await gateWeek(observer.getCurrentResult()).refetch()
    expect(vi.mocked(request)).toHaveBeenCalledTimes(2)
    expect(gateWeek(observer.getCurrentResult()).data).toBe(OVERVIEW)
  })
})

describe("move failures", () => {
  const conflict = (code: string) => new ApiError(409, "409", { code, message: "x" })

  it("says the plan was rebuilt when the session is superseded", () => {
    expect(moveFailureMessage(conflict("superseded"))).toBe(COPY.moveSuperseded)
  })
  it("says it is already done when the session is completed", () => {
    expect(moveFailureMessage(conflict("completed"))).toBe(COPY.moveCompleted)
  })
  it("falls back to the plain failure for any other refusal", () => {
    expect(moveFailureMessage(conflict("past_day"))).toBe(COPY.moveError)
    expect(moveFailureMessage(new ApiError(0, "offline", undefined))).toBe(COPY.moveError)
    expect(moveFailureMessage(new ApiError(422, "422", "a string detail"))).toBe(COPY.moveError)
    expect(moveFailureMessage(new Error("boom"))).toBe(COPY.moveError)
  })
})

describe("the move confirmation", () => {
  it("names the day, and says today for today", () => {
    expect(movedToast("2026-08-08", "2026-08-06")).toBe("Moved to Sat")
    expect(movedToast("2026-08-06", "2026-08-06")).toBe("Moved to today")
  })
  it("has a line for moving everything missed to today", () => {
    expect(COPY.movedToday).toBe("Moved to today")
  })
})

describe("urls", () => {
  it("keeps the filter in the url", () => {
    expect(planListUrl(null)).toBe("/student/plan")
    expect(planListUrl("0625")).toBe("/student/plan/0625")
  })
  it("puts an open session in the url, under its filter", () => {
    expect(planSessionUrl(null, "s1")).toBe("/student/plan/session/s1")
    expect(planSessionUrl("0625", "s1")).toBe("/student/plan/0625/session/s1")
  })
})

describe("the day strip's scroll target", () => {
  const day = (date: string, ...statuses: string[]) => statuses.map((status) => ({ date, status })) as never[]

  it("opens the done fold for a day that is all done", () => {
    expect(dayScrollTarget(day("2026-08-05", "done", "done"), "2026-08-05")).toEqual({ id: "plan-done", opensDone: true })
  })
  it("goes to the missed group for a day with something missed", () => {
    expect(dayScrollTarget(day("2026-08-04", "done", "missed"), "2026-08-04")).toEqual({ id: "plan-missed", opensDone: false })
  })
  it("goes to the day's own heading otherwise, and for an empty day", () => {
    expect(dayScrollTarget(day("2026-08-07", "later"), "2026-08-07")).toEqual({ id: "plan-day-2026-08-07", opensDone: false })
    expect(dayScrollTarget([], "2026-08-08")).toEqual({ id: "plan-day-2026-08-08", opensDone: false })
  })
  it("ignores other days' sessions", () => {
    const all = [...day("2026-08-05", "missed"), ...day("2026-08-07", "later")]
    expect(dayScrollTarget(all, "2026-08-07")).toEqual({ id: "plan-day-2026-08-07", opensDone: false })
  })
})

describe("routes", () => {
  const entries = [...ROUTES.matchAll(/\{\s*path:\s*"(plan[^"]*)",\s*element:\s*<StudyPlanScreen \/>,\s*handle:\s*(\{[^}]*\})/g)]

  it("serves the four study plan urls from one screen", () => {
    expect(entries.map((m) => m[1]).sort()).toEqual(
      ["plan", "plan/:subjectCode", "plan/:subjectCode/session/:sessionId", "plan/session/:sessionId"].sort(),
    )
  })

  it("gives each the page title and skeleton", () => {
    for (const m of entries) expect(m[2], m[1]).toContain('title: "This week"')
    for (const m of entries) expect(m[2], m[1]).toContain('skeleton: "page-header"')
  })

  it("lazy-loads only the new screen, and retires the old two from the routes", () => {
    expect(ROUTES).toMatch(/const StudyPlanScreen = lazy\(/)
    expect(ROUTES).toContain("./screens/studyplan/StudyPlanScreen")
    expect(ROUTES).not.toContain("StudyPlanWeek")
    expect(ROUTES).not.toContain("StudyPlanSession")
    expect(ROUTES).not.toMatch(/section="plan"/)
  })

  it("matches each url to the route that owns it (the static session route outranks a subject)", () => {
    const routes = entries.map((m) => ({ path: m[1] }))
    const hit = (url: string) => {
      const found = matchRoutes(routes, url)
      return { path: found?.[0].route.path, params: found?.[0].params }
    }
    expect(hit("/plan")).toEqual({ path: "plan", params: {} })
    expect(hit("/plan/session/abc")).toEqual({ path: "plan/session/:sessionId", params: { sessionId: "abc" } })
    expect(hit("/plan/0625")).toEqual({ path: "plan/:subjectCode", params: { subjectCode: "0625" } })
    expect(hit("/plan/0625/session/abc")).toEqual({
      path: "plan/:subjectCode/session/:sessionId",
      params: { subjectCode: "0625", sessionId: "abc" },
    })
  })
})

describe("the orchestrator's source", () => {
  it("gates the week through QueryState, which the adoption gate requires of a data-loading screen", () => {
    expect(SCREEN).toMatch(/import \{[^}]*\bQueryState\b[^}]*\} from "@\/components\/ui\/query-state"/)
    expect(SCREEN).toMatch(/<QueryState\b/)
    expect(SCREEN).toContain("gateWeek(")
  })

  it("never reads the raw week query's status itself", () => {
    expect(SCREEN).not.toMatch(/weekQuery\.isPending|weekQuery\.isError/)
  })

  it("exports the screen the routes load", () => {
    expect(SCREEN).toMatch(/export function StudyPlanScreen\(/)
  })

  it("reads the week, rebuilds and both session mutations from the study plan hooks", () => {
    for (const hook of ["useStudyPlanWeek", "useCompleteStudyPlanSession", "useMoveStudyPlanSession", "useRebuildStudyPlans"]) {
      expect(SCREEN, hook).toContain(hook)
    }
  })

  it("asks before a rebuild would discard done work", () => {
    expect(SCREEN).toContain("ConfirmModal")
    expect(SCREEN).toContain('status === "done"')
  })
})

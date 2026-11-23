import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { MemoryRouter } from "react-router-dom"
import { describe, expect, it } from "vitest"
import {
  ActionError,
  FirstRun,
  NeedPaper,
  NoSubjects,
  NotInWeekNote,
  NothingScheduled,
  PlanLoadError,
  PlanLoading,
  RebuildingBanner,
  WeekDone,
} from "@/portals/student/screens/studyplan/PlanStates"
import { COPY } from "@/portals/student/screens/studyplan/planCopy"

const render = (child: ReturnType<typeof createElement>) =>
  renderToStaticMarkup(createElement(MemoryRouter, null, child))

describe("study plan states", () => {
  it("announces loading and supplies a retry on failure", () => {
    const loading = render(createElement(PlanLoading))
    expect(loading).toContain('aria-busy="true"')
    // One announcement for the whole skeleton, not one per block.
    expect(loading.match(/role="status"/g)).toHaveLength(1)
    const html = render(createElement(PlanLoadError, { onRetry: () => {} }))
    expect(html).toContain(COPY.tryAgain)
    expect(html).toContain('href="/student"')
  })

  it("presents the first run walkthrough and any build failure", () => {
    const html = render(createElement(FirstRun, { building: false, error: "Try again", onBuild: () => {} }))
    expect(html).toContain(COPY.firstRunCta)
    expect(html).toContain(COPY.walk[0].title)
    expect(html).toContain('role="alert"')
  })

  it("renders navigation as links without nested buttons", () => {
    const html = render(createElement(NeedPaper, { copy: { heading: "More information", body: "Add a paper" }, placementCode: "0580" }))
    expect(html).toContain('href="/student/correct"')
    expect(html).toContain('href="/student/placement/0580"')
    expect(html).not.toMatch(/<a\b[^>]*>\s*<button/)
  })

  it("links the sparse and no-subject states to real routes", () => {
    const nothing = render(createElement(NothingScheduled, { practiceCode: "0580" }))
    expect(nothing).toContain('href="/student/practice/0580"')
    expect(nothing).toContain(COPY.nothingCta)
    const none = render(createElement(NoSubjects))
    expect(none).toContain('href="/student/onboard"')
    expect(none).not.toMatch(/<a\b[^>]*>\s*<button/)
  })

  it("shows the week done stats and disables planning once next week is ready", () => {
    const props = {
      body: "All 9 sessions.",
      stats: [
        { value: "9", label: "sessions", tone: "ok" as const },
        { value: "+260", label: "XP", tone: "primary" as const },
      ],
      practiceCode: "0580",
      planning: false,
      onPlanNextWeek: () => {},
    }
    const open = render(createElement(WeekDone, { ...props, nextWeekReady: false }))
    expect(open).toContain("+260")
    expect(open).toContain(COPY.planNextWeek)
    expect(open).not.toMatch(/\sdisabled=""/)
    const ready = render(createElement(WeekDone, { ...props, nextWeekReady: true }))
    expect(ready).toContain(COPY.nextWeekReady)
    expect(ready).toMatch(/\sdisabled=""/)
    expect(ready).toContain('href="/student/practice/0580"')
  })

  it("announces the rebuild, the missing session and an action failure", () => {
    expect(render(createElement(RebuildingBanner))).toContain('role="status"')
    expect(render(createElement(NotInWeekNote))).toContain(COPY.notInWeek)
    const err = render(createElement(ActionError, { message: COPY.moveError }))
    expect(err).toContain('role="alert"')
    expect(err).toContain(COPY.moveError)
  })
})

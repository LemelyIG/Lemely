import { createElement, isValidElement, type ReactElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { MemoryRouter } from "react-router-dom"
import { describe, expect, it } from "vitest"
import { Button } from "@/components/ui/button"
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

const count = (html: string, needle: string) => html.split(needle).length - 1

/** Walks a returned element tree (the vitest env is node, so nothing is mounted) for every element of one type. */
function findAll(node: unknown, type: unknown): ReactElement<Record<string, unknown>>[] {
  if (Array.isArray(node)) return node.flatMap((n) => findAll(n, type))
  if (!isValidElement<Record<string, unknown>>(node)) return []
  const own = node.type === type ? [node] : []
  return [...own, ...findAll(node.props.children, type)]
}

/** The one Button a state renders, so a test can read the handler it was wired to. */
function onlyButton(tree: unknown) {
  const found = findAll(tree, Button)
  expect(found).toHaveLength(1)
  return found[0]
}

describe("study plan states", () => {
  it("announces loading once", () => {
    const loading = render(createElement(PlanLoading))
    expect(loading).toContain('aria-busy="true"')
    // One announcement for the whole skeleton, not one per block.
    expect(count(loading, 'role="status"')).toBe(1)
  })

  it("announces a load failure once, and wires its retry", () => {
    const onRetry = () => {}
    const tree = PlanLoadError({ onRetry })
    expect(onlyButton(tree).props.onClick).toBe(onRetry)
    expect(onlyButton(tree).props.children).toBe(COPY.tryAgain)
    const html = render(createElement(PlanLoadError, { onRetry }))
    expect(html).toContain('href="/student"')
    expect(count(html, 'role="alert"')).toBe(1)
    expect(html).not.toContain('role="status"')
    expect(html).toContain(COPY.loadErrorTitle)
  })

  it("presents the first run walkthrough and wires the build", () => {
    const onBuild = () => {}
    const idle = FirstRun({ building: false, error: null, onBuild })
    const button = onlyButton(idle)
    expect(button.props.onClick).toBe(onBuild)
    expect(button.props.loading).toBe(false)
    expect(button.props.children).toBe(COPY.firstRunCta)
    const html = render(createElement(FirstRun, { building: false, error: null, onBuild }))
    expect(html).toContain(COPY.firstRunCta)
    expect(html).toContain(COPY.walk[0].title)
    // Nothing is in flight and nothing failed, so nothing is announced.
    expect(html).not.toContain(COPY.buildingAnnounce)
    expect(html).not.toContain('role="alert"')
  })

  it("announces the first run build once while it is in flight", () => {
    const onBuild = () => {}
    const tree = FirstRun({ building: true, error: null, onBuild })
    const button = onlyButton(tree)
    expect(button.props.loading).toBe(true)
    expect(button.props.onClick).toBe(onBuild)
    expect(button.props.children).toBe(COPY.building)
    const html = render(createElement(FirstRun, { building: true, error: null, onBuild }))
    expect(count(html, 'role="status"')).toBe(1)
    expect(count(html, COPY.buildingAnnounce)).toBe(1)
    expect(html).not.toContain('role="alert"')
  })

  it("announces a first run build failure once, and not as a status", () => {
    const html = render(createElement(FirstRun, { building: false, error: "Try again", onBuild: () => {} }))
    expect(count(html, 'role="alert"')).toBe(1)
    expect(html).toContain("Try again")
    expect(html).not.toContain(COPY.buildingAnnounce)
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

  describe("week done", () => {
    const onPlanNextWeek = () => {}
    const props = {
      body: "All 9 sessions, 1 h 55 min.",
      stats: [
        { value: "+260", label: "XP", tone: "primary" as const },
        { value: "7", label: "days in a row", tone: "ok" as const },
      ],
      practiceCode: "0580",
      planning: false,
      onPlanNextWeek,
    }

    it("shows the stats and disables planning once next week is ready", () => {
      const open = render(createElement(WeekDone, { ...props, nextWeekReady: false }))
      expect(open).toContain("+260")
      expect(open).toContain("days in a row")
      expect(open).toContain(COPY.planNextWeek)
      expect(open).not.toMatch(/\sdisabled=""/)
      const ready = render(createElement(WeekDone, { ...props, nextWeekReady: true }))
      expect(ready).toContain(COPY.nextWeekReady)
      expect(ready).toMatch(/\sdisabled=""/)
      expect(ready).toContain('href="/student/practice/0580"')
    })

    it("wires planning to the button", () => {
      const open = onlyButton(WeekDone({ ...props, nextWeekReady: false }))
      expect(open.props.onClick).toBe(onPlanNextWeek)
      expect(open.props.disabled).toBe(false)
      expect(open.props.loading).toBe(false)
      const busy = onlyButton(WeekDone({ ...props, planning: true, nextWeekReady: false }))
      expect(busy.props.loading).toBe(true)
      expect(onlyButton(WeekDone({ ...props, nextWeekReady: true })).props.disabled).toBe(true)
    })

    it("draws no stats row when there is no XP to show", () => {
      const html = render(createElement(WeekDone, { ...props, stats: [], nextWeekReady: false }))
      expect(html).toContain(props.body)
      expect(html).toContain(COPY.planNextWeek)
      expect(html).not.toContain("grid-template-columns")
      expect(html).not.toContain("font-mono")
    })
  })

  it("announces the rebuild, the missing session and an action failure", () => {
    expect(render(createElement(RebuildingBanner))).toContain('role="status"')
    expect(render(createElement(NotInWeekNote))).toContain(COPY.notInWeek)
    const err = render(createElement(ActionError, { message: COPY.moveError }))
    expect(err).toContain('role="alert"')
    expect(err).toContain(COPY.moveError)
  })
})

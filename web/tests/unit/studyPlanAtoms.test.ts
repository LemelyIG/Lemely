import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { MemoryRouter } from "react-router-dom"
import { describe, expect, it } from "vitest"
import { HairRows } from "@/components/redesign"
import { BasedOn } from "@/portals/student/screens/studyplan/BasedOn"
import { ActivityGlyph, CalendarGlyph, RebuildGlyph, TickGlyph } from "@/portals/student/screens/studyplan/icons"
import { MissedGroup } from "@/portals/student/screens/studyplan/MissedGroup"
import { PlanHeader, SubjectFilter } from "@/portals/student/screens/studyplan/PlanHeader"
import type { DayCell, FilterChip, HeaderModel, SessionVM } from "@/portals/student/screens/studyplan/planModel"
import { ACTIVITY_TILE, DONE_TILE } from "@/portals/student/screens/studyplan/planStyles"
import { ActivityTile, SessionRow } from "@/portals/student/screens/studyplan/SessionRow"
import { useWide } from "@/portals/student/screens/studyplan/useWide"
import { WeekStrip } from "@/portals/student/screens/studyplan/WeekStrip"

const html = (node: Parameters<typeof renderToStaticMarkup>[0]) => renderToStaticMarkup(createElement(MemoryRouter, null, node))
const noop = () => {}

const session = (over: Partial<SessionVM> = {}): SessionVM => ({
  id: "s1",
  subjectCode: "0580",
  subjectName: "Mathematics",
  dotIndex: 0,
  activity: "practice",
  activityLabel: "Practice set",
  title: "Vectors",
  minutes: 15,
  minutesLabel: "15 min",
  date: "2026-08-06",
  dayShort: "Thu",
  anyDay: false,
  status: "today",
  why: "Cost you 9 marks",
  whyBody: "",
  start: null,
  canMove: true,
  moveDays: [],
  ...over,
})

const row = (s: SessionVM, props: { big?: boolean; selected?: boolean } = {}) =>
  html(createElement(HairRows, null, createElement(SessionRow, { session: s, onOpen: noop, ...props })))

describe("glyphs", () => {
  it("draw a decorative svg per activity, with a fallback for an unknown one", () => {
    for (const activity of ["practice", "flashcards", "past_paper", "review", "mystery"]) {
      const out = renderToStaticMarkup(createElement(ActivityGlyph, { activity }))
      expect(out).toMatch(/^<svg /)
      expect(out).toContain('aria-hidden="true"')
    }
    expect(renderToStaticMarkup(createElement(ActivityGlyph, { activity: "review" }))).toBe(
      renderToStaticMarkup(createElement(RebuildGlyph, { size: 20 })),
    )
  })
  it("honour a size", () => {
    expect(renderToStaticMarkup(createElement(TickGlyph, { size: 12 }))).toContain('width="12"')
    expect(renderToStaticMarkup(createElement(CalendarGlyph))).toContain('width="14"')
  })
})

describe("tile colours", () => {
  it("map every activity and the done state onto tokens", () => {
    expect(Object.keys(ACTIVITY_TILE).sort()).toEqual(["flashcards", "past_paper", "practice", "review"])
    for (const cls of [...Object.values(ACTIVITY_TILE), DONE_TILE]) expect(cls).toMatch(/^bg-[a-z-]+ text-[a-z-]+$/)
  })
  it("ActivityTile shows a tick when done and falls back to the review tile for an unknown activity", () => {
    const done = renderToStaticMarkup(createElement(ActivityTile, { session: session({ status: "done" }) }))
    expect(done).toContain(DONE_TILE)
    expect(done).toContain("M3.5 8.3")
    const unknown = renderToStaticMarkup(createElement(ActivityTile, { session: session({ activity: "mystery" }) }))
    expect(unknown).toContain(ACTIVITY_TILE.review)
  })
})

describe("SessionRow", () => {
  it("is one hairline row with title, subject, activity and minutes, and exactly one chevron", () => {
    const out = row(session())
    expect(out).toContain('<li class="rd-hairrow-item">')
    expect(out).toMatch(/<button type="button" class="rd-hairrow"/)
    expect(out).toContain("Vectors")
    expect(out).toContain("Mathematics · Practice set · 15 min")
    expect(out.match(/rd-chev/g)).toHaveLength(1)
  })
  it("uses the kit's subject dot, so a subject keeps its colour across screens", () => {
    expect(row(session({ subjectCode: "0580" }))).toContain("background:var(--grade-a)")
    expect(row(session({ subjectCode: "0625", subjectName: "Physics" }))).toContain("background:var(--md-primary)")
  })
  it("only the big row carries its reason line", () => {
    expect(row(session())).not.toContain("Cost you 9 marks")
    expect(row(session(), { big: true })).toContain("Cost you 9 marks")
    expect(row(session({ why: null }), { big: true })).not.toContain('class="font-semibold text-primary"')
  })
  it("a done row is struck through, announced as done and ticked", () => {
    const out = row(session({ status: "done" }))
    expect(out).toContain("line-through")
    expect(out).toContain('<span class="sr-only">Done: </span>')
    expect(row(session())).not.toContain("line-through")
    expect(row(session())).not.toContain("sr-only")
  })
  it("a selected row says so", () => {
    expect(row(session(), { selected: true })).toContain('aria-current="true"')
    expect(row(session())).not.toContain("aria-current")
  })
})

const chips: FilterChip[] = [
  { code: null, label: "All", dotIndex: null, selected: false },
  { code: "0580", label: "Mathematics", dotIndex: 0, selected: true },
  { code: "0625", label: "Physics", dotIndex: 1, selected: false },
]
const header = (over: Partial<HeaderModel> = {}): HeaderModel => ({
  title: "This week",
  sub: "2 of 8 done · 1 h 40 min",
  examDate: "2026-08-20",
  filters: chips,
  ...over,
})
const now = new Date(2026, 7, 6, 12)

describe("SubjectFilter", () => {
  it("is a tablist with one selected tab, and a dot on every subject chip but All", () => {
    const out = html(createElement(SubjectFilter, { filters: chips, onFilter: noop }))
    expect(out).toContain('role="tablist"')
    expect(out.match(/role="tab"/g)).toHaveLength(3)
    expect(out.match(/aria-selected="true"/g)).toHaveLength(1)
    expect(out.match(/class="rd-dot"/g)).toHaveLength(2)
    expect(out).toContain("background:var(--md-primary)")
  })
  /*
   * A scroller clips at its padding edge on both axes, so a focus ring drawn
   * outside a chip needs that much padding on every side or it is cut off.
   * Tailwind's spacing step is 4px.
   */
  it("leaves room inside the scroller for the whole focus ring, on every side", () => {
    const px = (cls: string, name: string) => {
      const m = cls.match(new RegExp(`(?:^| )${name}-(\\d+(?:\\.\\d+)?)(?= |$)`))
      return m ? Number(m[1]) * 4 : 0
    }
    for (const inline of [false, true]) {
      const out = html(createElement(SubjectFilter, { filters: chips, onFilter: noop, inline }))
      const list = out.match(/<div role="tablist"[^>]*class="([^"]*)"/)?.[1] ?? ""
      const tab = out.match(/<button[^>]*class="([^"]*)"/)?.[1] ?? ""
      expect(list).toContain("overflow-x-auto")
      // outline-offset-N is N literal pixels, not a spacing step.
      const ring = Number(tab.match(/focus-visible:outline-\[([\d.]+)px\]/)?.[1]) + Number(tab.match(/focus-visible:outline-offset-(\d+)/)?.[1])
      expect(ring).toBe(4.5)
      expect(px(list, "py"), `block padding, inline=${inline}`).toBeGreaterThanOrEqual(ring)
      expect(px(list, "px"), `inline padding, inline=${inline}`).toBeGreaterThanOrEqual(ring)
      // A chip scrolled into view by focus stops short of the clip edge by the same room.
      expect(px(list, "scroll-px"), `scroll padding, inline=${inline}`).toBeGreaterThanOrEqual(ring)
      // The room is paid back by negative margins, so the header lays out as it did: 2px of block padding, none inline.
      expect(px(list, "py") - px(list, "-my"), `net block extent, inline=${inline}`).toBe(2)
      expect(px(list, "px") - px(list, "-mx"), `net inline extent, inline=${inline}`).toBe(0)
    }
  })
})

describe("PlanHeader", () => {
  it("narrow: the one h1, the sub line, the exam pill as a link, then the filter under it", () => {
    const out = html(createElement(PlanHeader, { header: header(), wide: false, now, onFilter: noop }))
    expect(out).toMatch(/<h1[^>]*>This week<\/h1>/)
    expect(out).toContain("2 of 8 done · 1 h 40 min")
    expect(out).toMatch(/<a class="rd-pill"[^>]*href="\/student\/announcements"/)
    expect(out).toContain("14 days to exams")
    expect(out.indexOf("14 days to exams")).toBeLessThan(out.indexOf('role="tablist"'))
  })
  it("wide: the filter sits inline in the header row", () => {
    const wide = html(createElement(PlanHeader, { header: header(), wide: true, now, onFilter: noop }))
    const narrow = html(createElement(PlanHeader, { header: header(), wide: false, now, onFilter: noop }))
    expect(wide).toContain('role="tablist"')
    expect(wide).not.toContain("-mx-4")
    expect(narrow).toContain("-mx-4")
  })
  it("no exam date, no pill; one subject, no filter", () => {
    const out = html(createElement(PlanHeader, { header: header({ examDate: null, filters: [] }), wide: false, now, onFilter: noop }))
    expect(out).not.toContain("rd-pill")
    expect(out).not.toContain("tablist")
  })
  it("an exam that has passed shows no pill", () => {
    const out = html(createElement(PlanHeader, { header: header({ examDate: "2026-08-01" }), wide: false, now, onFilter: noop }))
    expect(out).not.toContain("rd-pill")
  })
})

const day = (over: Partial<DayCell>): DayCell => ({
  date: "2026-08-03",
  letter: "M",
  label: "Monday",
  count: 2,
  isToday: false,
  allDone: false,
  hasMissed: false,
  ...over,
})

describe("WeekStrip", () => {
  const days = [
    day({}),
    day({ date: "2026-08-04", letter: "T", label: "Tuesday", count: 1, allDone: true }),
    day({ date: "2026-08-05", letter: "W", label: "Wednesday", count: 1, hasMissed: true }),
    day({ date: "2026-08-06", letter: "T", label: "Thursday", count: 1, isToday: true }),
    day({ date: "2026-08-07", letter: "F", label: "Friday", count: 0 }),
  ]
  const out = renderToStaticMarkup(createElement(WeekStrip, { days, onDay: noop }))
  it("is a list of day buttons, today marked as the current date", () => {
    expect(out).toContain('aria-label="This week by day"')
    expect(out.match(/<button/g)).toHaveLength(5)
    expect(out.match(/aria-current="date"/g)).toHaveLength(1)
  })
  it("names each day by its state, not by colour alone", () => {
    expect(out).toContain('aria-label="Monday: 2 sessions"')
    expect(out).toContain('aria-label="Tuesday: all done"')
    expect(out).toContain('aria-label="Wednesday: 1 session, missed"')
    expect(out).toContain('aria-label="Friday: nothing planned"')
  })
  it("a done day shows a tick instead of its count", () => {
    expect(out).toContain("M3.5 8.3")
  })
})

describe("MissedGroup", () => {
  const props = { movingId: null, onOpen: noop, onMoveToday: noop, onMoveAllToday: noop }
  const missed = (n: number) =>
    Array.from({ length: n }, (_, i) => session({ id: `m${i}`, title: `Topic ${i}`, status: "missed", dayShort: i === 0 ? "Mon" : "Tue" }))
  it("renders nothing when nothing is missed", () => {
    expect(renderToStaticMarkup(createElement(MissedGroup, { ...props, missed: [] }))).toBe("")
  })
  it("one or two missed sessions get a bar each, each with its own move button", () => {
    const out = renderToStaticMarkup(createElement(MissedGroup, { ...props, missed: missed(2) }))
    expect(out).toContain("Missed Mon · Topic 0")
    expect(out).toContain("Missed Tue · Topic 1")
    expect(out.match(/Move to today/g)).toHaveLength(2)
  })
  it("three or more collapse into one bar with a move-all action", () => {
    const out = renderToStaticMarkup(createElement(MissedGroup, { ...props, missed: missed(3) }))
    expect(out).toContain("Missed 3 sessions")
    expect(out).toContain("Move all to today")
    expect(out).not.toContain("Topic 0")
  })
  it("while a move is in flight every action is disabled and the moving one says so", () => {
    const out = renderToStaticMarkup(createElement(MissedGroup, { ...props, missed: missed(2), movingId: "m0" }))
    expect(out.match(/disabled=""/g)).toHaveLength(2)
    expect(out).toContain("Moving…")
    expect(out.match(/Move to today/g)).toHaveLength(1)
  })
})

describe("BasedOn", () => {
  it("states what the plan was built from, with a rebuild action", () => {
    const out = renderToStaticMarkup(createElement(BasedOn, { line: "Built from your 4 papers and weak topics", rebuilding: false, onRebuild: noop }))
    expect(out).toContain("Built from your 4 papers and weak topics")
    expect(out).toContain("Rebuild")
    expect(out).not.toContain("disabled")
  })
  it("while rebuilding it is disabled and says so", () => {
    const out = renderToStaticMarkup(createElement(BasedOn, { line: "x", rebuilding: true, onRebuild: noop }))
    expect(out).toContain("Rebuilding…")
    expect(out).toContain('disabled=""')
  })
})

describe("useWide", () => {
  it("is false where there is no window to measure (server render)", () => {
    function Probe() {
      return createElement("i", null, String(useWide()))
    }
    expect(renderToStaticMarkup(createElement(Probe))).toBe("<i>false</i>")
  })
})

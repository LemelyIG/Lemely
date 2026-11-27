import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { MemoryRouter } from "react-router-dom"
import { describe, expect, it } from "vitest"
import { PlanList } from "@/portals/student/screens/studyplan/PlanList"
import type { DayCell, PlanBody, SessionVM } from "@/portals/student/screens/studyplan/planModel"

const noop = () => {}
type Props = Parameters<typeof PlanList>[0]

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

const days: DayCell[] = ["2026-08-03", "2026-08-04", "2026-08-05", "2026-08-06", "2026-08-07", "2026-08-08", "2026-08-09"].map(
  (date, i) => ({ date, letter: "MTWTFSS"[i], label: date, count: i === 3 ? 1 : 0, isToday: i === 3, allDone: false, hasMissed: false }),
)

const body = (over: Partial<PlanBody> = {}): PlanBody => ({
  ring: [0.5, 0, 1],
  ringLabel: "Today: 1 of 2 goals done. This week: 1 of 1 paper done",
  today: { date: "2026-08-06", heading: "Today · Thursday", sub: "1 session · 15 min", sessions: [session()] },
  missed: [],
  week: { show: false, days, anyDay: [] },
  later: [],
  done: { count: 0, title: "0 done this week", daysLabel: "", openByDefault: false, sessions: [] },
  basedOn: "Built from your last 4 papers and weak topics",
  subjectTop: null,
  whyTopics: [],
  whyHint: null,
  pending: [],
  firstOpenId: "s1",
  binnyLine: "15 minutes today.",
  ...over,
})

const props = (b: PlanBody, over: Partial<Props> = {}): Props => ({
  body: b,
  wide: false,
  selectedId: null,
  movingId: null,
  rebuilding: false,
  onOpen: noop,
  onMoveToday: noop,
  onMoveAllToday: noop,
  onDay: noop,
  onRebuild: noop,
  onBuild: noop,
  ...over,
})
const render = (b: PlanBody, over: Partial<Props> = {}) =>
  renderToStaticMarkup(createElement(MemoryRouter, null, createElement(PlanList, props(b, over))))

describe("plan list: today", () => {
  it("leads with the gold ring named by the model's own label, then the heading and its sub", () => {
    const html = render(body())
    expect(html).toContain('role="img"')
    expect(html).toContain('aria-label="Today: 1 of 2 goals done. This week: 1 of 1 paper done"')
    expect(html).toContain("Today · Thursday")
    expect(html).toContain("1 session · 15 min")
    expect(html.indexOf("rd-goldring")).toBeLessThan(html.indexOf("Today · Thursday"))
  })
  it("draws each ring part from body.ring: gold when complete, partial when under", () => {
    const html = render(body())
    expect(html).toContain('data-part="partial"')
    expect(html).toContain('data-part="empty"')
    expect(html).toContain('data-part="done"')
  })
  it("shows today's sessions as big rows with their reason line, and anchors the section by its date", () => {
    const html = render(body())
    expect(html).toContain('id="plan-day-2026-08-06"')
    expect(html).toContain('aria-label="Today&#x27;s sessions"')
    expect(html).toContain("Cost you 9 marks")
  })
  it("is quiet when nothing is planned today: the ring and heading stay, no empty list", () => {
    const html = render(
      body({
        ring: [0, 0, 0],
        ringLabel: "Today: nothing planned",
        today: { date: "2026-08-06", heading: "Today · Thursday", sub: "Nothing planned today", sessions: [] },
      }),
    )
    expect(html).toContain("Nothing planned today")
    expect(html).toContain('aria-label="Today: nothing planned"')
    expect(html).not.toContain("Today&#x27;s sessions")
  })
})

describe("plan list: the rest of the week", () => {
  it("shows the missed bar above the any-day section", () => {
    const html = render(
      body({
        missed: [session({ id: "m1", status: "missed", dayShort: "Wed", title: "Quadratics" })],
        week: { show: true, days, anyDay: [] },
      }),
    )
    expect(html).toContain("Missed Wed · Quadratics")
    expect(html.indexOf("plan-missed")).toBeLessThan(html.indexOf("Any day this week"))
  })
  it("passes the move in flight to the missed bar", () => {
    const html = render(body({ missed: [session({ id: "m1", status: "missed", dayShort: "Wed" })] }), { movingId: "m1" })
    expect(html).toContain("Moving…")
  })
  it("shows the week strip and any-day rows only when the model says to", () => {
    expect(render(body())).not.toContain("This week by day")
    const html = render(
      body({ week: { show: true, days, anyDay: [session({ id: "a1", status: "anyDay", activity: "past_paper", title: "Paper 4" })] } }),
    )
    expect(html).toContain("Any day this week")
    expect(html).toContain("This week by day")
    expect(html).toContain("Paper 4")
  })
  it("groups later days under their label, each anchored by date", () => {
    const html = render(
      body({
        later: [
          { date: "2026-08-07", label: "Fri", sessions: [session({ id: "l1", status: "later", title: "Algebra" })] },
          { date: "2026-08-10", label: "Next Mon", sessions: [session({ id: "l2", status: "later", title: "Trig" })] },
        ],
      }),
    )
    expect(html).toContain("Later this week")
    expect(html).toContain('id="plan-day-2026-08-07"')
    expect(html).toContain("Next Mon")
    expect(html).toContain("Algebra")
    expect(html).toContain("Trig")
  })
  it("omits the later section when there is nothing later", () => {
    expect(render(body())).not.toContain("Later this week")
  })
})

describe("plan list: done fold", () => {
  const done = (openByDefault: boolean) =>
    body({
      done: {
        count: 2,
        title: "2 done this week",
        daysLabel: "Mon · Tue",
        openByDefault,
        sessions: [session({ id: "d1", status: "done", title: "Fractions" }), session({ id: "d2", status: "done", title: "Ratio" })],
      },
    })
  it("folds shut in the all-subjects view and is anchored for the day strip", () => {
    const html = render(done(false))
    expect(html).toContain('<details id="plan-done">')
    expect(html).toContain("2 done this week")
    expect(html).toContain("Mon · Tue")
    expect(html).toContain("Fractions")
  })
  it("opens by default in a subject's view", () => {
    expect(render(done(true))).toContain('<details id="plan-done" open="">')
  })
  it("is absent with no done sessions", () => {
    expect(render(body())).not.toContain("plan-done")
  })
})

describe("plan list: why these topics and the subject line", () => {
  const filtered = body({
    subjectTop: { targetGrade: "A*", exam: "Paper 4 in 188 days" },
    whyTopics: [
      { topic: "Vectors", pct: 41, tone: "w" },
      { topic: "Trigonometry", pct: 62, tone: "m" },
    ],
    whyHint: "Your weakest Maths topics from 4 papers.",
  })
  it("shows target and exam in the subject line", () => {
    const html = render(filtered)
    expect(html).toContain("A*")
    expect(html).toContain("target")
    expect(html).toContain("Paper 4 in 188 days")
  })
  it("shows the topics as kit chips with the percentage and a state said in words, plus the hint", () => {
    const html = render(filtered)
    expect(html).toContain("Why these topics")
    expect(html).toContain("Vectors")
    expect(html).toContain("41%")
    expect(html).toContain('data-state="work"')
    expect(html).toContain('data-state="getting"')
    expect(html).toContain("Work on")
    expect(html).toContain("Getting there")
    expect(html).toContain("Your weakest Maths topics from 4 papers.")
  })
  it("leaves both out of the all-subjects view", () => {
    const html = render(body())
    expect(html).not.toContain("Why these topics")
    expect(html).not.toContain("target")
  })
  it("shows the subject line with only the facts it has", () => {
    const html = render(body({ subjectTop: { targetGrade: null, exam: "Paper 2 in 30 days" } }))
    expect(html).toContain("Paper 2 in 30 days")
    expect(html).not.toContain("target")
  })
})

describe("plan list: subjects without a plan", () => {
  const pending = body({
    pending: [
      { subjectCode: "0625", subjectName: "Physics", kind: "notGenerated" },
      { subjectCode: "0606", subjectName: "Additional Mathematics", kind: "refused" },
    ],
  })
  it("names each subject and what it needs, with one action", () => {
    const html = render(pending)
    expect(html).toContain("Physics: no plan yet")
    expect(html).toContain(">Build<")
    expect(html).toContain("Additional Mathematics: needs a paper first")
    expect(html).toContain(">Rebuild<")
  })
  it("waits while a rebuild runs", () => {
    const html = render(pending, { rebuilding: true })
    const buttons = html.match(/<button[^>]*>(?:Build|Rebuild)<\/button>/g) ?? []
    expect(buttons).toHaveLength(2)
    for (const b of buttons) expect(b).toMatch(/\sdisabled(?:="")?(?:\s|>)/)
  })
})

describe("plan list: query and layout state", () => {
  it("dims the list and marks it busy while the week rebuilds", () => {
    const html = render(body(), { rebuilding: true })
    expect(html).toContain('aria-busy="true"')
    expect(html).toContain("opacity-50")
  })
  it("is neither busy nor dimmed otherwise", () => {
    const html = render(body())
    expect(html).not.toContain("opacity-50")
    expect(html.match(/id="plan-list"[^>]*aria-busy/)).toBeNull()
  })
  it("carries the provenance line below 1280px and leaves it to the panel from there", () => {
    expect(render(body(), { wide: false })).toContain("Built from your last 4 papers and weak topics")
    expect(render(body(), { wide: true })).not.toContain("Built from your last 4 papers and weak topics")
  })
  it("says the rebuild is running in the provenance line", () => {
    expect(render(body(), { rebuilding: true })).toContain("Rebuilding…")
  })
  it("marks the selected row only on desktop, where the panel follows it", () => {
    expect(render(body(), { wide: true, selectedId: "s1" })).toContain("rd-selected")
    expect(render(body(), { wide: false, selectedId: "s1" })).not.toContain("rd-selected")
  })
})

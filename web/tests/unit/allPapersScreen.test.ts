import { readFileSync } from "node:fs"
import { join } from "node:path"
import { createElement, type ComponentType } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { MemoryRouter, Route, Routes } from "react-router-dom"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { Breadcrumbs } from "@/components/ui/breadcrumbs"
import { ApiError } from "@/lib/api"
import type { PaperHistoryRow, Subject } from "@/lib/studentTypes"
import { decideBackPlan } from "@/portals/student/backControl"
import { currentSubjectCode, resolveCrumb, resolveCrumbTrail, studentShellTrail } from "@/portals/student/data"
import { AllPapers } from "@/portals/student/screens/AllPapers"
import { AllPapersList } from "@/portals/student/screens/papers/AllPapersList"
import { ComparePanel } from "@/portals/student/screens/papers/ComparePanel"
import { PapersBody } from "@/portals/student/screens/papers/PapersBody"
import { PapersControls } from "@/portals/student/screens/papers/PapersControls"
import { PapersLoading } from "@/portals/student/screens/papers/PapersLoading"
import {
  DEFAULT_FILTERS,
  compareView,
  filterOptions,
  rowViews,
} from "@/portals/student/screens/papers/papersModel"
import { MATHS, NOW } from "@/portals/student/screens/subject/fixtures"

const WEB_ROOT = join(import.meta.dirname, "..", "..")
const read = (rel: string) => readFileSync(join(WEB_ROOT, rel), "utf8")

const query = vi.hoisted(() => ({ current: {} as Record<string, unknown> }))
vi.mock("@/lib/hooks/useStudentApi", () => ({ useSubject: () => query.current }))
vi.mock("@/lib/hooks/useReferenceApi", () => ({ useSubjectName: () => "Mathematics" }))

const html = <P extends object>(node: ComponentType<P>, props: P) =>
  renderToStaticMarkup(createElement(MemoryRouter, null, createElement(node, props)))
const screen = (search = "") =>
  renderToStaticMarkup(
    createElement(
      MemoryRouter,
      { initialEntries: [`/student/subject/0580/papers${search}`] },
      createElement(Routes, null, createElement(Route, { path: "/student/subject/:code/papers", element: createElement(AllPapers) })),
    ),
  )

const refetch = vi.fn()
const settled = (over: Record<string, unknown>) => ({ refetch, isFetching: false, fetchStatus: "idle", error: null, ...over })
const history: PaperHistoryRow[] = MATHS.paperHistory.map((h, i) => ({
  ...h,
  confidence: i === 0 ? { scored: 14, uncertain: 2, needsReview: 0 } : null,
  teacherCorrected: i === 1 ? 3 : 0,
}))
const subject = (rows: PaperHistoryRow[]): Subject => ({ ...MATHS, paperHistory: rows })

beforeEach(() => refetch.mockClear())

describe("the route", () => {
  const index = read("src/portals/student/index.tsx")
  it("is lazy-loaded under the Subject route with a title and a page-header skeleton", () => {
    expect(index).toMatch(/const AllPapers = lazy\(\(\) => import\("\.\/screens\/AllPapers"\)\.then\(\(m\) => \(\{ default: m\.AllPapers \}\)\)\)/)
    expect(index).toMatch(
      /path: "subject\/:code\/papers",\s*element: <AllPapers \/>,\s*handle: \{ title: "All papers", skeleton: "page-header" \}/,
    )
  })
  it("is a different path from the Subject screen, so one never shadows the other", () => {
    expect(index.match(/path: "subject\/:code"/g)).toHaveLength(1)
    expect(index.match(/path: "subject\/:code\/papers"/g)).toHaveLength(1)
  })
})

describe("the trail and the way back", () => {
  it("reads Home / code / All papers", () => {
    expect(resolveCrumb("/student/subject/0580/papers")).toBe("Home / 0580 / All papers")
  })
  it("links Home and the subject code, and not the page it is on", () => {
    expect(resolveCrumbTrail("/student/subject/0580/papers")).toEqual([
      { label: "Home", to: "/student" },
      { label: "0580", to: "/student/subject/0580" },
      { label: "All papers" },
    ])
  })
  it("leaves the Subject screen's own trail unlinked after Home", () => {
    expect(resolveCrumbTrail("/student/subject/0580")).toEqual([{ label: "Home", to: "/student" }, { label: "0580" }])
  })
  it("the shell trail drops Home, so back from a phone falls to the Subject screen", () => {
    expect(studentShellTrail("/student/subject/0580/papers")).toEqual([{ label: "0580", to: "/student/subject/0580" }, { label: "All papers" }])
  })
  it("keeps the subject open in the sidebar", () => {
    expect(currentSubjectCode("/student/subject/0580/papers")).toBe("0580")
  })
})

describe("one back control on the phone header", () => {
  const shell = read("src/portals/student/shell.tsx")
  const plan = (pathname: string) => decideBackPlan({ trail: studentShellTrail(pathname), previousPath: null, hasHistory: false })
  it("All papers' trail links its subject, so the trail carries the one back control and leads there", () => {
    expect(plan("/student/subject/0580/papers")).toMatchObject({ control: "trail", parentTo: "/student/subject/0580", ariaLabel: "Back to 0580" })
  })
  it("a page whose trail links nothing keeps the bar's Back", () => {
    expect(plan("/student/subject/0580")).toEqual({ control: "bar" })
    expect(plan("/student/result/3")).toEqual({ control: "bar" })
  })
  it("the shell owns the hide, so the screens carry no back logic of their own", () => {
    expect(shell).toContain("useStudentBackPlan(location.pathname, trail)")
    expect(shell).toContain('backPlan.control === "trail" && "max-sm:hidden"')
    expect(shell).not.toContain("shellParentTo")
  })
  it("the native back falls back to the same parent", () => {
    expect(shell).toContain('backFallback: backPlan.control === "trail" ? backPlan.parentTo : "/student"')
  })
})

describe("rows", () => {
  it("each opens its result when not comparing", () => {
    const out = html(AllPapersList, { rows: rowViews(history, NOW), picks: null, onPick: () => {}, label: "Papers" })
    expect(out.match(/href="\/student\/result\/\d+"/g)).toHaveLength(history.length)
    expect(out).toContain("Teacher re-marked 3 questions")
    expect(out).toContain("2 of 14 unsure")
  })
  it("pick instead of open when comparing: a pressed toggle with no chevron, and the pick order read aloud", () => {
    const out = html(AllPapersList, { rows: rowViews(history, NOW), picks: [history[1].id], onPick: () => {}, label: "Papers" })
    expect(out).not.toContain("href=")
    expect(out.match(/<button/g)).toHaveLength(history.length)
    expect(out.match(/aria-pressed="true"/g)).toHaveLength(1)
    expect(out.match(/aria-pressed="false"/g)).toHaveLength(history.length - 1)
    expect(out).not.toContain("aria-current")
    expect(out).not.toContain("rd-chev")
    expect(out).toContain('<span class="ap-pick"><span class="sr-only">Pick </span>1</span>')
    expect(out).not.toContain('aria-label="Pick')
  })
  it("keep their chevron when a row opens its result", () => {
    const out = html(AllPapersList, { rows: rowViews(history, NOW), picks: null, onPick: () => {}, label: "Papers" })
    expect(out.match(/rd-chev/g)).toHaveLength(history.length)
    expect(out).not.toContain("aria-pressed")
  })
  it("set the numbers in Mono", () => {
    const out = html(AllPapersList, { rows: rowViews(history, NOW), picks: null, onPick: () => {}, label: "Papers" })
    expect(out).toMatch(/<span class="ap-num">61\/80<\/span>/)
  })
})

describe("controls", () => {
  it("show a filter only when the data offers a choice, and always date and sort", () => {
    const out = html(PapersControls, {
      filters: DEFAULT_FILTERS,
      options: { papers: [], variants: [1, 2], sessions: [] },
      onChange: () => {},
    })
    expect(out).not.toContain("Paper</span>")
    expect(out).toContain("Variant</span>")
    expect(out).not.toContain("Session</span>")
    expect(out).toContain("Date</span>")
    expect(out).toContain("Sort</span>")
  })
  it("mark the chosen option with aria-pressed and count the filters that are on", () => {
    const out = html(PapersControls, {
      filters: { ...DEFAULT_FILTERS, paper: 4, period: "90d" },
      options: filterOptions(history),
      onChange: () => {},
    })
    expect(out).toMatch(/aria-pressed="true"[^>]*aria-label="Paper: paper 4"/)
    expect(out).toContain('aria-expanded="true"')
    expect(out).toContain('aria-label="2 on"')
  })
  it("fold shut with nothing on", () => {
    const out = html(PapersControls, { filters: DEFAULT_FILTERS, options: filterOptions(history), onChange: () => {} })
    expect(out).toContain('aria-expanded="false"')
    expect(out).toContain('data-open="false"')
  })
})

describe("tidy-ups from the review", () => {
  it("a session tray scrolls the picked choice into view and fades its end while more lies past it", () => {
    const controls = read("src/portals/student/screens/papers/PapersControls.tsx")
    expect(controls).toContain("scrollDeltaToReveal(")
    expect(controls).toContain("data-more={more}")
    const css = read("src/portals/student/screens/papers/papers.css")
    expect(css).toMatch(/\.ap-seg\[data-more="true"\] \{ mask-image:/)
    expect(css).toMatch(/\.ap-seg\[data-more="true"\]:dir\(rtl\) \{ mask-image: linear-gradient\(to left/)
  })
  it("changing a filter drops the compare picks it hides", () => {
    const body = read("src/portals/student/screens/papers/PapersBody.tsx")
    expect(body).toContain("setPicks((p) => prunePicks(p, applyFilters(history, next, now)))")
    expect(body).toContain("onChange={changeFilters}")
    expect(body).toContain("picked={held.length}")
  })
  it("the phone back link names where it goes", () => {
    const items = [{ label: "0580", to: "/student/subject/0580" }, { label: "All papers" }]
    const plan = decideBackPlan({ trail: items, previousPath: null, hasHistory: false })
    if (plan.control !== "trail") throw new Error("All papers' trail must carry the back control")
    const out = html(Breadcrumbs, { items, back: { label: plan.label, ariaLabel: plan.ariaLabel, onActivate: () => {} } })
    expect(out.match(/aria-label="Back to 0580"/g)).toHaveLength(1)
    expect(out).toContain(">0580</span>")
  })
})

describe("the compare panel", () => {
  it("asks for two picks, then one more", () => {
    expect(html(ComparePanel, { view: null, picked: 0 })).toContain("Pick two papers from the list.")
    expect(html(ComparePanel, { view: null, picked: 1 })).toContain("Pick one more.")
  })
  it("shows earlier then later, the change in words, and a way into each result", () => {
    const view = compareView(history, [history[0].id, history[history.length - 1].id], NOW)
    const out = html(ComparePanel, { view, picked: 2 })
    expect(out.indexOf("Earlier")).toBeLessThan(out.indexOf("Later"))
    expect(out).toContain("Up ")
    expect(out).toContain(`href="/student/result/${history[history.length - 1].id}"`)
    expect(out).toContain(`href="/student/result/${history[0].id}"`)
    expect(out).toContain("Open earlier result")
  })
})

describe("the loaded body", () => {
  const body = (rows: PaperHistoryRow[], filters = DEFAULT_FILTERS) => html(PapersBody, { history: rows, filters, onFilters: () => {}, now: NOW })
  it("says a trend needs a second paper when there is one, and offers no filters or compare", () => {
    const out = body([history[0]])
    expect(out).toContain("One paper so far. Your trend starts with the next one.")
    expect(out).not.toContain("Compare two")
    expect(out).not.toContain("Filter and sort")
  })
  it("with many papers offers filters, sort and compare beside a count", () => {
    const out = body(history)
    expect(out).toContain("Filter and sort")
    expect(out).toContain("Compare two")
    expect(out).toContain(`<span class="ap-num">${history.length}</span> of <span class="ap-num">${history.length}</span> papers`)
  })
  it("says so, and offers to clear, when the filters match nothing", () => {
    const out = body(history, { ...DEFAULT_FILTERS, paper: 99 })
    expect(out).toContain("No papers match these filters.")
    expect(out).toContain("Clear filters")
    expect(out).not.toContain("rd-hairrows")
  })
})

describe("loading", () => {
  it("is a status named for the subject, with a row-sized block per row", () => {
    const out = html(PapersLoading, { name: "Mathematics" })
    expect(out).toContain('role="status"')
    expect(out).toContain('aria-label="Loading Mathematics papers"')
    expect(out.match(/height:64px/g)).toHaveLength(6)
  })
})

describe("the screen, state by state", () => {
  it("loading: the heading and the skeleton", () => {
    query.current = settled({ status: "pending", data: undefined, fetchStatus: "fetching" })
    const out = screen()
    expect(out).toMatch(/<h1[^>]*>All papers<\/h1>/)
    expect(out).toContain("Loading Mathematics papers")
  })
  it("error before anything loaded: a retry and a way back to the subject, no rows", () => {
    query.current = settled({ status: "error", data: undefined, error: new ApiError(500, "boom") })
    const out = screen()
    expect(out).toContain("We couldn’t load Mathematics papers")
    expect(out).toContain("Try again")
    expect(out).toContain("Back to Mathematics")
    expect(out).not.toContain("rd-hairrows")
  })
  it("error over loaded rows: keeps the rows and says it could not refresh", () => {
    query.current = settled({ status: "error", data: subject(history), error: new ApiError(500, "boom") })
    const out = screen()
    expect(out).toContain("Couldn’t refresh Mathematics. Showing what loaded before.")
    expect(out).toContain("rd-hairrows")
    expect(out).not.toContain("We couldn’t load")
  })
  it("empty: the endpoint's no-papers 404 is the first run, with Binny and a scan link", () => {
    query.current = settled({
      status: "error",
      data: undefined,
      error: new ApiError(404, "No papers for subject 0580", "No papers for subject 0580"),
    })
    const out = screen()
    expect(out).toContain("No papers yet")
    expect(out).toContain('href="/student/correct?subject=0580"')
    expect(out).toContain("Scan a Mathematics paper")
    expect(out).not.toContain("We couldn’t load")
    expect(out.match(/class="[^"]*binny/gi)?.length ?? 0).toBeGreaterThan(0)
  })
  it("empty: a loaded subject with no attempts reads the same", () => {
    query.current = settled({ status: "success", data: subject([]) })
    expect(screen()).toContain("No papers yet")
  })
  it("single: one paper and the no-trend sentence", () => {
    query.current = settled({ status: "success", data: subject([history[0]]) })
    const out = screen()
    expect(out).toContain("Mathematics, 1 paper")
    expect(out).toContain("One paper so far.")
  })
  it("full: every paper, newest first by default, and the subtitle counts them", () => {
    query.current = settled({ status: "success", data: subject(history) })
    const out = screen()
    expect(out).toContain(`Mathematics, ${history.length} papers`)
    expect(out.match(/href="\/student\/result\/\d+"/g)).toHaveLength(history.length)
    expect(out.indexOf(history[0].label)).toBeLessThan(out.indexOf(history[history.length - 1].label))
  })
  it("reads filters from the address", () => {
    query.current = settled({ status: "success", data: subject(history) })
    const out = screen("?paper=2")
    expect(out.match(/href="\/student\/result\/\d+"/g)?.length).toBe(history.filter((h) => h.paperNumber === 2).length)
  })
})

describe("the Subject screen links here", () => {
  it("the Papers heading and the All N papers control both go to the All papers screen, with no in-place reveal left", () => {
    const source = read("src/portals/student/screens/subject/PapersList.tsx")
    expect(source).toContain('<SectionHeading id="sj-papers-h" title="Papers" to={allTo} />')
    expect(source).toContain("<Link to={allTo}")
    expect(source).not.toContain("onShowAll")
    expect(read("src/portals/student/screens/subject/SubjectBody.tsx")).toContain("allTo={links.papers(code)}")
  })
})

describe("the stylesheet", () => {
  it("places the list column only inside the two-column layout, so the single-paper list stays under its heading", () => {
    const css = read("src/portals/student/screens/papers/papers.css")
    expect(css).toMatch(/\.ap-layout > \.ap-main \{ grid-column: 1; grid-row: 1; \}/)
    expect(css).not.toMatch(/^\s*\.ap-main \{[^}]*grid-row/m)
  })
})

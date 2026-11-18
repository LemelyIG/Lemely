import { readFileSync } from "node:fs"
import { join } from "node:path"
import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { MemoryRouter } from "react-router-dom"
import { describe, expect, it } from "vitest"
import { HomeBand } from "@/portals/student/home/HomeBand"
import { HomeSkeleton } from "@/portals/student/home/HomeSkeleton"
import { HomeTopRow } from "@/portals/student/home/HomeTopRow"
import { homeView } from "@/portals/student/home/model"
import { BadgeRow } from "@/portals/student/home/me/BadgeRow"
import { BADGES } from "@/portals/student/home/me/meModel"
import { MeSkeleton } from "@/portals/student/home/me/MeSkeleton"
import { MomentRows } from "@/portals/student/home/MomentRows"
import { SectionLink } from "@/portals/student/home/SectionLink"
import { makeHome } from "./studentHomeFixture"

/*
 * Home and Me announcements, labels and link feedback. This repo's runner is node-only (no jsdom, no
 * testing-library, see vitest.config.ts), so these render to static markup, the way listGroup.test.ts does.
 */

const html = (node: Parameters<typeof renderToStaticMarkup>[0]) =>
  renderToStaticMarkup(createElement(MemoryRouter, null, node))
const statusCount = (out: string) => (out.match(/role="status"/g) ?? []).length
const NONE: ReadonlySet<string> = new Set()

function band(overrides: Parameters<typeof makeHome>[0] = {}) {
  const vm = homeView(makeHome(overrides), NONE)
  return html(
    createElement(HomeBand, { band: vm.band, week: vm.week, planTo: "/student/plan", allPapersTo: vm.allPapersTo }),
  )
}

describe("HomeBand empty states", () => {
  it("an empty papers list is copy, not a loading announcement", () => {
    const out = band({ recentPapers: [], lastPaperAt: null })
    expect(out).toContain("Your marked papers land here.")
    expect(statusCount(out)).toBe(0)
    expect(out).not.toContain('aria-label="Loading"')
  })

  it("the ghost rows next to the empty copy are decorative and hidden from assistive tech", () => {
    const out = band({ recentPapers: [], lastPaperAt: null })
    expect(out).toMatch(/<div[^>]*aria-hidden="true"[^>]*class="rd-ghostrows"|<div[^>]*class="rd-ghostrows"[^>]*aria-hidden="true"/)
  })
})

describe("skeletons announce once", () => {
  it("HomeSkeleton has exactly one status region", () => {
    expect(statusCount(html(createElement(HomeSkeleton)))).toBe(1)
  })

  it("MeSkeleton has exactly one status region", () => {
    expect(statusCount(html(createElement(MeSkeleton)))).toBe(1)
  })
})

describe("MeSkeleton geometry", () => {
  const out = html(createElement(MeSkeleton))

  it("keeps the loaded two-column desktop grid and its gap, so content swaps in without a jump", () => {
    const screen = readFileSync(join(process.cwd(), "src/portals/student/home/me/MeScreen.tsx"), "utf8")
    const grid = /md:grid md:grid-cols-2 md:items-start md:gap-12/
    expect(screen).toMatch(grid)
    expect(out).toMatch(grid)
  })

  it("splits into the same two flex columns as MeScreen", () => {
    expect((out.match(/md:flex md:min-w-0 md:flex-col md:gap-\[18px\]/g) ?? []).length).toBe(2)
  })
})

describe("HomeTopRow countdown label", () => {
  const vm = homeView(makeHome(), NONE)
  const examLabel = (date: string, days: number, localDate = "2026-11-12") => {
    const out = html(
      createElement(HomeTopRow, { pill: vm.streakPill, exam: { date, days, near: days <= 30 }, examTo: "/student/plan", localDate }),
    )
    return [...out.matchAll(/aria-label="([^"]*)"/g)].map((m) => m[1]).find((l) => l?.includes("study plan"))
  }

  it("names the number of days", () => {
    expect(examLabel("2026-11-24", 12)).toBe("Exam in 12 days. Open your study plan")
  })

  it("uses the singular for one day", () => {
    expect(examLabel("2026-11-13", 1)).toBe("Exam in 1 day. Open your study plan")
  })

  it("says today on the day", () => {
    expect(examLabel("2026-11-12", 0)).toBe("Exam today. Open your study plan")
  })
})

describe("BadgeRow", () => {
  const badges = BADGES.map((b) => ({ ...b, earned: b.id === "first-paper" }))
  const out = html(createElement(BadgeRow, { badges, onAll: () => {} }))

  it("has one control that opens the badges sheet", () => {
    expect((out.match(/<button/g) ?? []).length).toBe(1)
    expect(out).not.toContain("All badges")
  })

  it("keeps the heading control, so the sheet stays reachable", () => {
    expect(out).toMatch(/<h2[^>]*id="me-badges"[^>]*><button[^>]*>Badges/)
  })

  it("bleeds by the shell gutter (14px), not past it", () => {
    expect(out).toContain("-mx-3.5")
    expect(out).toContain("px-3.5")
    expect(out).not.toContain("-mx-[18px]")
  })
})

describe("MomentRows list label", () => {
  const rows = homeView(makeHome(), NONE).band.classRows

  it("uses the label it is given", () => {
    const out = html(createElement(MomentRows, { rows, label: "From your class" }))
    expect(out).toContain('aria-label="From your class"')
    expect(out).not.toContain('aria-label="For you"')
  })

  it("the class band labels its rows for the class, not 'For you'", () => {
    const out = band()
    expect(out).toMatch(/<ul[^>]*aria-label="From your class"/)
    expect(out).not.toContain('aria-label="For you"')
  })
})

describe("SectionLink feedback", () => {
  const out = html(createElement(SectionLink, { id: "home-week", title: "This week", to: "/student/plan" }))

  it("changes colour on hover and when pressed", () => {
    expect(out).toContain("hover:text-primary")
    expect(out).toMatch(/active:text-\[color-mix\(/)
  })

  it("presses with motion gated on reduced motion, and keeps the focus ring", () => {
    expect(out).toContain("motion-safe:active:scale-[0.97]")
    expect(out).toContain("focus-visible:outline-primary")
  })
})

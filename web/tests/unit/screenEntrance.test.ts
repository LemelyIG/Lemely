import { describe, expect, it } from "vitest"
import { readdirSync, readFileSync } from "node:fs"
import { join, relative } from "node:path"
import { stripComments } from "./support/jsxSource"

/*
 * Packet B2b · source-text pins for screen entrance / View Transitions, the
 * pieces of this packet that are wiring rather than pure logic and so cannot
 * be exercised under vitest's Node/no-jsdom environment (D3.20) — see
 * `navigationDirection.test.ts` and `overlayExit.test.ts` for the pure half.
 */

const ROOT = join(process.cwd())

function sourceOf(relativePath: string): string {
  return stripComments(readFileSync(join(ROOT, relativePath), "utf8"))
}

function tsxFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = join(dir, entry.name)
    if (entry.isDirectory()) return tsxFiles(full)
    return /\.tsx$/.test(entry.name) ? [full] : []
  })
}

describe("no screen root under src/portals carries lm-screen except PaperResult.tsx", () => {
  it("PaperResult.tsx is the sole exception", () => {
    const offenders: string[] = []
    for (const file of tsxFiles(join(ROOT, "src/portals"))) {
      const relativePath = relative(ROOT, file).split("\\").join("/")
      if (relativePath.endsWith("PaperResult.tsx")) continue
      const source = stripComments(readFileSync(file, "utf8"))
      if (source.includes("lm-screen")) offenders.push(relativePath)
    }
    expect(offenders).toEqual([])
  })

  it("PaperResult.tsx still carries lm-screen — it keeps its own entrance", () => {
    expect(sourceOf("src/portals/student/screens/PaperResult.tsx")).toContain("lm-screen")
  })
})

describe("screen-outlet.tsx", () => {
  const source = sourceOf("src/components/ui/screen-outlet.tsx")

  it("keys its wrapper on location.key, so it remounts on navigation only", () => {
    expect(source).toContain("key={location.key}")
  })

  it("carries the lm-screen class", () => {
    expect(source).toContain("lm-screen")
  })

  it("exports both ScreenOutlet and ScreenFrame", () => {
    expect(source).toContain("export function ScreenOutlet")
    expect(source).toContain("export function ScreenFrame")
  })
})

describe("every portal layout renders <ScreenOutlet instead of a bare <Outlet", () => {
  const PORTAL_LAYOUTS = [
    "src/portals/student/index.tsx",
    "src/portals/teacher/index.tsx",
    "src/portals/admin/index.tsx",
    "src/portals/parent/index.tsx",
  ] as const

  it.each(PORTAL_LAYOUTS)("%s", (relativePath) => {
    const source = sourceOf(relativePath)
    expect(source).toContain("<ScreenOutlet")
    expect(source).not.toContain("<Outlet")
  })
})

describe("routes.tsx groups the top-level non-portal routes in a ScreenFrame layout route", () => {
  it("imports and uses ScreenFrame", () => {
    const source = sourceOf("src/routes.tsx")
    expect(source).toContain("ScreenFrame")
  })
})

describe("View Transitions are wired from shell chrome", () => {
  it("breadcrumbs.tsx passes viewTransition on its Links", () => {
    expect(sourceOf("src/components/ui/breadcrumbs.tsx")).toContain("viewTransition")
  })

  it("back-control.tsx passes viewTransition on its navigate() call", () => {
    expect(sourceOf("src/components/ui/back-control.tsx")).toContain("viewTransition")
  })

  it("student's sidebar NavLink passes viewTransition inline", () => {
    expect(sourceOf("src/portals/student/index.tsx")).toContain("viewTransition")
  })

  it.each(["src/portals/teacher/index.tsx", "src/portals/admin/index.tsx"])(
    "%s's sidebar renders through nav-shells.tsx, which passes viewTransition on its NavLink",
    (relativePath) => {
      // Teacher and admin sidebars render their nav rows through the shared
      // `SidebarNav` component rather than an inline NavLink, so the assertion
      // lives where the behavior actually is: nav-shells.tsx always renders
      // viewTransition on any NavLink item that carries a `to`.
      expect(sourceOf(relativePath)).toContain("SidebarNav")
      expect(sourceOf("src/components/ui/nav-shells.tsx")).toContain("viewTransition")
    },
  )

  it("the /student/result/:paperId route opts out with handle.viewTransition: false", () => {
    const source = sourceOf("src/portals/student/index.tsx")
    const resultRouteAt = source.indexOf('path: "result/:paperId"')
    expect(resultRouteAt).toBeGreaterThan(-1)
    const nextRouteAt = source.indexOf("path:", resultRouteAt + 1)
    const routeBlock = source.slice(resultRouteAt, nextRouteAt === -1 ? undefined : nextRouteAt)
    expect(routeBlock).toContain("viewTransition: false")
  })

  it("CorrectPaper.tsx's navigate() to the result route does not pass viewTransition", () => {
    const source = sourceOf("src/portals/student/screens/CorrectPaper.tsx")
    for (const match of source.matchAll(/navigate\([^)]*\/student\/result[^)]*\)/g)) {
      expect(match[0]).not.toContain("viewTransition")
    }
  })
})

describe("index.css carries the View Transition rules and their reduced-motion guard", () => {
  const css = sourceOf("src/index.css")

  it("suppresses .lm-screen's own entrance while a View Transition is active", () => {
    expect(css).toContain("html:active-view-transition .lm-screen")
  })

  it("styles the root pseudo-elements directionally", () => {
    expect(css).toContain("::view-transition-old(root)")
    expect(css).toContain("::view-transition-new(root)")
  })

  it("the reduced-motion block flattens the View Transition pseudo-elements too", () => {
    const block = css.match(/@media\s*\(\s*prefers-reduced-motion:\s*reduce\s*\)\s*\{[\s\S]*?\n\}/)
    expect(block).not.toBeNull()
    expect(block![0]).toContain("::view-transition-group(*)")
    expect(block![0]).toContain("::view-transition-old(*)")
    expect(block![0]).toContain("::view-transition-new(*)")
  })
})

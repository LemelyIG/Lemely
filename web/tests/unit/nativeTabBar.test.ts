import { readFileSync } from "node:fs"
import { join } from "node:path"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"
import { activeTabTap, isPlainPrimaryClick } from "@/components/shell/tabTap"
import { isTabRoot, titleLevelFor } from "@/components/shell/largeTitle"
import { isStudentSubjectRoot, STUDENT_PLAN_TO, STUDENT_PRACTICE_TO } from "@/portals/student/shellNav"

const SRC = join(fileURLToPath(new URL("../../", import.meta.url)), "src")
const css = readFileSync(join(SRC, "index.css"), "utf8")
const nav = readFileSync(join(SRC, "components/ui/nav-shells.tsx"), "utf8")
const shell = readFileSync(join(SRC, "components/shell/PortalShell.tsx"), "utf8")
const studentRoutes = readFileSync(join(SRC, "portals/student/index.tsx"), "utf8")
const teacherRoutes = readFileSync(join(SRC, "portals/teacher/index.tsx"), "utf8")

describe("tapping the active tab (audit A item 10)", () => {
  it("drilled in below the tab root, a tap pops to the root whatever the scroll", () => {
    expect(activeTabTap({ pathname: "/student/classes/7", tabTo: "/student/classes", scrollY: 300 })).toBe("pop-root")
    expect(activeTabTap({ pathname: "/student/classes/7", tabTo: "/student/classes", scrollY: 0 })).toBe("pop-root")
  })
  it("at the root, the first tap scrolls to the top", () => {
    expect(activeTabTap({ pathname: "/student/classes", tabTo: "/student/classes", scrollY: 300 })).toBe("scroll-top")
  })
  it("does nothing at the top of the root itself", () => {
    expect(activeTabTap({ pathname: "/student/classes", tabTo: "/student/classes", scrollY: 0 })).toBe("none")
    expect(activeTabTap({ pathname: "/student/classes/", tabTo: "/student/classes", scrollY: 0 })).toBe("none")
  })
})

describe("BottomNav native markup", () => {
  it("carries the native tab bar class and swaps to the filled icon only on native", () => {
    expect(nav).toContain("lm-native-tabbar")
    expect(nav).toMatch(/<span className="native:hidden">\{item\.icon\}<\/span>/)
    expect(nav).toMatch(/<span className="hidden native:inline-flex">\{item\.activeIcon\}<\/span>/)
  })
  it("PortalShell hides the tab bar on immersive routes on native", () => {
    expect(shell).toMatch(/immersive && "native:hidden"/)
  })
  it("main clears the native tab bar through one per-platform height", () => {
    expect(shell).toContain("lm-native-main")
    expect(shell).toContain("data-immersive={immersive || undefined}")
  })
})

describe("immersive routes (user decision 2026-11-09)", () => {
  it("only student correct and teacher review-a-mark are immersive", () => {
    expect(studentRoutes.match(/immersive: true/g)).toHaveLength(1)
    expect(studentRoutes).toMatch(/title: "Mark a paper", skeleton: "page-header", immersive: true/)
    expect(teacherRoutes.match(/immersive: true/g)).toHaveLength(1)
    expect(teacherRoutes).toMatch(/title: "Review a mark", skeleton: "list", immersive: true/)
  })
})

describe("tab bar CSS (preview 4447a571)", () => {
  const block = css.slice(css.indexOf("/* ── Native frame: tab bar"))
  it("one --native-tabbar-h per platform, which main's padding reads", () => {
    expect(block).toMatch(/:root\[data-platform="ios"\] \{[^}]*--native-tabbar-h: var\(--native-tabbar-h-ios\)/)
    expect(block).toMatch(/:root\[data-platform="android"\] \{[^}]*--native-tabbar-h: var\(--native-tabbar-h-android\)/)
    expect(block).toMatch(/\.lm-native-main:not\(\[data-immersive\]\) \{[^}]*padding-bottom: calc\(var\(--native-tabbar-h\) \+ env\(safe-area-inset-bottom\)\)/)
  })
  it("iOS: 49px + home indicator, glass, 10px labels", () => {
    expect(block).toMatch(/\[data-platform="ios"\] \.lm-native-tabbar \{[^}]*block-size: calc\(var\(--native-tabbar-h-ios\) \+ env\(safe-area-inset-bottom\)\)/)
    expect(block).toMatch(/\[data-platform="ios"\] \.lm-native-tabbar \{[^}]*backdrop-filter: blur\(var\(--blur-nav\)\) saturate\(var\(--native-glass-saturate\)\)/)
    expect(block).toMatch(/\[data-theme="dark"\]\[data-platform="ios"\] \.lm-native-tabbar \{[^}]*var\(--md-surface-container-low\) var\(--native-glass-mix\)/)
    expect(block).toMatch(/\[data-platform="ios"\] \.lm-native-tabbar \.lm-native-tab-label \{[^}]*font-size: var\(--native-tab-label-ios\)/)
  })
  it("Android: 80dp, 12px labels, a 64x32 secondary-container pill behind the active icon", () => {
    expect(block).toMatch(/\[data-platform="android"\] \.lm-native-tabbar \{[^}]*block-size: calc\(var\(--native-tabbar-h-android\) \+ env\(safe-area-inset-bottom\)\)/)
    expect(block).toMatch(/\[data-platform="android"\] \.lm-native-tabbar \.lm-native-tab-label \{[^}]*font-size: var\(--native-tab-label-android\)/)
    expect(block).toMatch(/\[data-platform="android"\] \.lm-native-tabbar \[aria-current="page"\] \.lm-native-tab-icon:not\(\[data-emphasis\]\)::before \{[^}]*inset-inline-start: calc\(50% - var\(--native-tab-pill-w\) \/ 2\);[^}]*inline-size: var\(--native-tab-pill-w\);[^}]*block-size: var\(--native-tab-pill-h\);[^}]*background: var\(--md-secondary-container\)/)
  })
  it("tab links take the preview metrics and the selected rules skip the raised tab", () => {
    expect(block).toMatch(/\[data-platform="ios"\] \.lm-native-tabbar > \* \{[^}]*padding-block-start: var\(--native-tab-pad-top-ios\);[^}]*gap: var\(--native-tab-gap-ios\)/)
    expect(block).toMatch(/\[data-platform="android"\] \.lm-native-tabbar > \* \{[^}]*padding-block-start: var\(--space-3\);[^}]*gap: var\(--space-1\)/)
    expect(block).toMatch(/\.lm-native-tabbar > \* \{[^}]*min-block-size: 0;[^}]*justify-content: flex-start/)
    expect(block).not.toMatch(/inset-inline: 0;\s*margin-inline: auto/)
    expect(block).not.toMatch(/\[aria-current="page"\] \{/)
  })
  it("tab labels inherit the link weight (500, 600 iOS / 700 Android selected) and track 0.01em", () => {
    expect(block).toMatch(/\.lm-native-tabbar > \* \{[^}]*font-weight: 500/)
    expect(block).toMatch(/\.lm-native-tabbar \.lm-native-tab-label \{[^}]*font-weight: inherit;[^}]*letter-spacing: 0\.01em/)
    expect(block).toMatch(/\[data-platform="ios"\] \.lm-native-tabbar \[aria-current="page"\]:not\(:has\(\[data-emphasis\]\)\) \{[^}]*font-weight: 600/)
    expect(block).toMatch(/\[data-platform="android"\] \.lm-native-tabbar \[aria-current="page"\]:not\(:has\(\[data-emphasis\]\)\) \{[^}]*font-weight: 700/)
  })
  it("24px icons on both platforms", () => {
    expect(block).toMatch(/\.lm-native-tabbar \.lm-native-tab-icon svg \{[^}]*inline-size: var\(--native-tab-icon\);[^}]*block-size: var\(--native-tab-icon\)/)
  })
  it("owns the native page ground in both themes", () => {
    expect(css).toMatch(/--native-page-ios: var\(--md-surface-container\)/)
    expect(css).toMatch(/:root\[data-theme="dark"\]\[data-platform\] \{[^}]*--native-page-ios: var\(--md-surface-container-lowest\)/)
    expect(css).toMatch(/--native-page-android: var\(--md-surface-container-low\)/)
    expect(css).toMatch(/:root\[data-theme="dark"\]\[data-platform\] \{[^}]*--native-page-android: var\(--md-surface\)/)
    expect(block).toMatch(/\[data-portal\] \{[^}]*background-color: var\(--native-page\)/)
  })
})

describe("isPlainPrimaryClick (final review minor 1)", () => {
  const click = { button: 0, metaKey: false, ctrlKey: false, shiftKey: false, altKey: false }
  it("accepts a plain primary click", () => {
    expect(isPlainPrimaryClick(click)).toBe(true)
  })
  it("leaves modified and non-primary clicks to the browser", () => {
    expect(isPlainPrimaryClick({ ...click, ctrlKey: true })).toBe(false)
    expect(isPlainPrimaryClick({ ...click, metaKey: true })).toBe(false)
    expect(isPlainPrimaryClick({ ...click, shiftKey: true })).toBe(false)
    expect(isPlainPrimaryClick({ ...click, altKey: true })).toBe(false)
    expect(isPlainPrimaryClick({ ...click, button: 1 })).toBe(false)
  })
})

describe("redirecting tab roots (Practice and Plan land on a subject page)", () => {
  it("treats the subject page as the root: /student/practice/:code and /student/plan/:code, one segment only", () => {
    for (const p of ["/student/practice/0580", "/student/practice/0580/", "/student/plan/0580"]) expect(isStudentSubjectRoot(p), p).toBe(true)
    for (const p of ["/student/practice", "/student/practice/set/a1", "/student/plan/0580/session/s1", "/student/flashcards/0580", "/student/classes/7"])
      expect(isStudentSubjectRoot(p), p).toBe(false)
  })
  it("re-tapping Practice on a subject page scrolls to top instead of popping to the redirect", () => {
    const tap = (pathname: string, tabTo: string, scrollY: number) =>
      activeTabTap({ pathname, tabTo, scrollY, isRoot: isStudentSubjectRoot })
    expect(tap("/student/practice/0580", STUDENT_PRACTICE_TO, 300)).toBe("scroll-top")
    expect(tap("/student/practice/0580", STUDENT_PRACTICE_TO, 0)).toBe("none")
    expect(tap("/student/plan/9709", STUDENT_PLAN_TO, 200)).toBe("scroll-top")
    // Drilled in deeper than the subject page: still pops.
    expect(tap("/student/practice/set/a1", STUDENT_PRACTICE_TO, 0)).toBe("pop-root")
    expect(tap("/student/plan/0580/session/s1", STUDENT_PLAN_TO, 0)).toBe("pop-root")
  })
  it("without the predicate (teacher, parent) the old behaviour holds", () => {
    expect(activeTabTap({ pathname: "/student/practice/0580", tabTo: STUDENT_PRACTICE_TO, scrollY: 0 })).toBe("pop-root")
  })
  it("the subject page gets the root title level", () => {
    const tabs = ["/student", STUDENT_PRACTICE_TO, "/student/correct", STUDENT_PLAN_TO, "/student/profile"]
    const level = (p: string) => titleLevelFor([{}, {}], isTabRoot(p, tabs, isStudentSubjectRoot))
    expect(level("/student/practice/0580")).toBe("root")
    expect(level("/student/plan/0580")).toBe("root")
    expect(level("/student/practice/set/a1")).toBe("detail")
    expect(level("/student/plan/0580/session/s1")).toBe("detail")
  })
})

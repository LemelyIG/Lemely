import { describe, expect, it } from "vitest"
import { readFileSync } from "node:fs"
import { join } from "node:path"
import { stripComments } from "./support/jsxSource"

/*
 * Task 1 (C1a) · `SectionHead` replaces the ad hoc eyebrow/title/kicker divs
 * scattered across page and panel heads (`x-sectionhead-no-equivalent`).
 * Source-text pins only, same constraint as `brandLockup.test.ts` (D3.20).
 */

const ROOT = join(process.cwd())

function sourceOf(relativePath: string): string {
  return stripComments(readFileSync(join(ROOT, relativePath), "utf8"))
}

const SECTION_HEAD_FILE = "src/components/ui/section-head.tsx"

const MIGRATED_SCREENS = [
  "src/portals/student/screens/Overview.tsx",
  "src/portals/teacher/screens/Overview.tsx",
  "src/portals/teacher/screens/ClassAnalytics.tsx",
  "src/portals/teacher/screens/Review.tsx",
] as const

describe("section-head.tsx", () => {
  const source = sourceOf(SECTION_HEAD_FILE)

  it("exports SectionHead", () => {
    expect(source).toContain("export function SectionHead")
  })

  it("imports Eyebrow and Display from ./primitives", () => {
    // primitives.tsx is off-limits this task; SectionHead composes what's
    // already there rather than adding a sibling primitive.
    const importMatch = source.match(/import\s*\{([^}]*)\}\s*from\s*"\.\/primitives"/)
    expect(importMatch).not.toBeNull()
    const names = importMatch![1]
    expect(names).toContain("Eyebrow")
    expect(names).toContain("Display")
  })

  it("renders Display", () => {
    expect(source).toContain("<Display")
  })

  it("renders no literal h1/h2/h3 JSX tag — the heading level is computed, not hardcoded", () => {
    // "Exactly one h* element, level chosen by the caller so document outline
    // stays honest" (Task 1 interfaces) means SectionHead cannot hardcode a
    // heading tag per rung — it must compute the tag name from `level` so a
    // caller's choice is the only source of the document outline. A literal
    // `<h1`/`<h2`/`<h3` in this file would mean the level is NOT actually
    // caller-controlled.
    expect(source).not.toMatch(/<h[123][\s>]/)
  })
})

describe("every migrated screen renders <SectionHead", () => {
  it.each(MIGRATED_SCREENS)("%s", (relativePath) => {
    expect(sourceOf(relativePath)).toContain("<SectionHead")
  })
})

describe("primitives.tsx is untouched by this task", () => {
  it("still exports Eyebrow and Display exactly as before — no new primitive added here", () => {
    const source = sourceOf("src/components/ui/primitives.tsx")
    expect(source).toContain("export function Eyebrow")
    expect(source).toContain("export function Display")
    expect(source).not.toContain("SectionHead")
  })
})

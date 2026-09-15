import { describe, expect, it } from "vitest"
import fs from "node:fs"
import path from "node:path"
import {
  Atom,
  BookOpen,
  Flask,
  GraduationCap,
  Leaf,
  MathOperations,
} from "@phosphor-icons/react"
import { stripComments } from "./support/jsxSource"
import { subjectGlyphFor } from "@/components/ui/subject-glyph"

/*
 * C1b (Task 2). `subjectGlyphFor` is the pure tone->icon lookup DESIGN.md
 * §3.8's pastel table was missing a glyph half for — every consumer that
 * wants "Physics, but as a shape, not just a colour" (a subject tile, a nav
 * row, a leading icon on a tag) goes through this one table so the mapping
 * cannot drift between call sites the way `student/data.ts`'s old
 * `subjectIcon(code)` switch had already started to (`Calculator` for maths,
 * not `MathOperations` — a different glyph than this table picks).
 */

const ROOT = path.join(import.meta.dirname, "..", "..")

function sourceOf(relative: string): string {
  return stripComments(fs.readFileSync(path.join(ROOT, relative), "utf8"))
}

describe("subjectGlyphFor", () => {
  it.each([
    ["sky", MathOperations],
    ["lilac", Atom],
    ["sage", Flask],
    ["clay", Leaf],
    ["amber", BookOpen],
    ["rose", GraduationCap],
  ] as const)("maps the %s pastel tone to its subject glyph", (tone, icon) => {
    expect(subjectGlyphFor(tone)).toBe(icon)
  })

  it("falls back to GraduationCap for a tone with no subject affinity (ok/warn/err/info)", () => {
    expect(subjectGlyphFor("ok")).toBe(GraduationCap)
    expect(subjectGlyphFor("warn")).toBe(GraduationCap)
    expect(subjectGlyphFor("err")).toBe(GraduationCap)
    expect(subjectGlyphFor("info")).toBe(GraduationCap)
  })
})

describe("subject-glyph.tsx (source)", () => {
  const source = sourceOf("src/components/ui/subject-glyph.tsx")

  it("renders the tile as an accessible image, not a decorative icon plus nothing", () => {
    expect(source).toContain('role="img"')
  })
})

describe("SubjectTag gains a leading-icon prop (source)", () => {
  const source = sourceOf("src/components/ui/subject-tag.tsx")

  it("subject-tag.tsx exposes an icon prop", () => {
    expect(source).toContain("icon")
  })
})

describe("SubjectGlyph consumers (source)", () => {
  it("the student Subject page's header renders SubjectGlyph beside the subject name", () => {
    expect(sourceOf("src/portals/student/screens/Subject.tsx")).toContain("<SubjectGlyph")
  })

  it("the student sidebar's per-subject accordion rows render SubjectGlyph", () => {
    expect(sourceOf("src/portals/student/index.tsx")).toContain("<SubjectGlyph")
  })

  it("the old per-subject icon switch (student/data.ts subjectIcon) is gone, not left as dead duplicate logic", () => {
    expect(sourceOf("src/portals/student/data.ts")).not.toContain("subjectIcon")
  })
})

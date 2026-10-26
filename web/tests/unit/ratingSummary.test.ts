import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"
import { MIN_RATED_STUDENTS, ratingDisplay } from "@/lib/tutoring/ratingLabel"
import type { Rating } from "@/lib/tutoringTypes"
import { stripComments } from "./support/jsxSource"

/*
 * C-22 (SPEC §d, §i.4): "4.6 · 12 students" with a star glyph, or a "New" pill
 * below three students, never stars. The aria-label is a full sentence (SC-16).
 */

const SPEC = readFileSync(
  join(import.meta.dirname, "..", "..", "..", "docs", "tutoring", "SPEC.md"),
  "utf8",
)

const rated = (average: number, count: number): Rating => ({ state: "rated", average, count })
const fresh = (count: number): Rating => ({ state: "new", average: null, count })

describe("threshold", () => {
  it("is the three students the SPEC names, read from its text", () => {
    expect(SPEC).toContain(`"New" below 3 students`)
    expect(MIN_RATED_STUDENTS).toBe(3)
  })
})

describe("rated tutors", () => {
  it("shows one decimal and the number of students", () => {
    const d = ratingDisplay(rated(4.6, 12))
    expect(d.kind).toBe("rated")
    expect(d.text).toBe("4.6 · 12 students")
  })

  it("keeps a trailing zero (4.0 is not 4)", () => {
    expect(ratingDisplay(rated(4, 5)).text).toBe("4.0 · 5 students")
  })

  it("uses the singular for one student", () => {
    // Defensive: the server never calls one student "rated".
    expect(ratingDisplay(rated(5, 1)).countText).toBe("1 student")
  })

  it("aria-label is a full sentence", () => {
    const label = ratingDisplay(rated(4.6, 12)).ariaLabel
    expect(label).toBe("Rated 4.6 out of 5 by 12 students.")
    expect(label).toMatch(/^[A-Z]/)
    expect(label.endsWith(".")).toBe(true)
    expect(label).not.toMatch(/[★☆]/u)
  })
})

describe("new tutors", () => {
  it("shows New and no number, whatever the count below three", () => {
    for (const count of [0, 1, 2]) {
      const d = ratingDisplay(fresh(count))
      expect(d.kind).toBe("new")
      expect(d.text).toBe("New")
      expect(d.text).not.toMatch(/\d/)
    }
  })

  it("aria-label is a full sentence that says why", () => {
    const label = ratingDisplay(fresh(1)).ariaLabel
    expect(label).toBe("New tutor. Fewer than 3 students have rated this tutor so far.")
    expect(label).toMatch(/^[A-Z]/)
    expect(label.endsWith(".")).toBe(true)
  })

  it("does not trust a rated state that carries fewer than three students", () => {
    expect(ratingDisplay(rated(5, 2)).kind).toBe("new")
  })

  it("does not trust a rated state with no average, which would invent a number", () => {
    expect(ratingDisplay({ state: "rated", average: null, count: 9 }).kind).toBe("new")
  })

  it("does not show an average on a new rating even if the server sent one", () => {
    expect(ratingDisplay({ state: "new", average: 4.5, count: 10 }).text).toBe("New")
  })
})

describe("component source (C-22)", () => {
  const readRaw = () => readFileSync(
    join(import.meta.dirname, "..", "..", "src", "components", "ui", "rating-summary.tsx"),
    "utf8",
  )
  // Comments are blanked: the file's header prose quotes the very strings checked here.
  const read = () => stripComments(readRaw())

  it("labels the whole thing with the sentence and hides the glyph from AT", () => {
    expect(read()).toContain("ariaLabel")
    expect(read()).toContain('role="img"')
    expect(read()).toContain("aria-hidden")
  })

  it("draws one star glyph for a rated tutor and none for a new one", () => {
    expect(read()).toContain("Star")
    expect(read()).not.toMatch(/Array\.from\(\s*\{\s*length:\s*5/)
  })
})

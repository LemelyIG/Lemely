import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"

/*
 * C3e (Task 10): five audit-ledger findings turn out to be a written record
 * rather than a code change — the exploration canvas the audit dossier
 * reviewed said something DESIGN.md or PRODUCT.md now supersede. Closing
 * them means the decision is written down and findable, not merely "closed"
 * in the ledger with nothing behind it.
 *
 * v5 Abyss: DESIGN.md was rewritten with six sections (Overview, Colors,
 * Typography, Elevation, Components, Do's and Don'ts), so the old "§16 Recorded
 * decisions", "§12 Cards" and "§13 knobs" assertions are replaced by a check on
 * the new structure. The ledger ids stay asserted in docs/design-canvas-notes.md.
 *
 * Source-text assertions only, against the repo root (not `web/`): both
 * files this test reads live outside the `web/` package.
 */

const ROOT = join(import.meta.dirname, "..", "..", "..")
const read = (p: string) => readFileSync(join(ROOT, p), "utf8")

const LEDGER_IDS = [
  "trust-ops-device-limit-count-divergence",
  "brand-subject-color-mapping-mismatch",
  "x-type-instrument-serif-rejected",
  "brand-color-system-superseded",
  "student-home-no-hero-grade",
] as const

describe("DESIGN.md has the six sections of the v5 Abyss system", () => {
  const designMd = read("DESIGN.md")
  const headings = [...designMd.matchAll(/^## (\d+)\. (.+)$/gm)].map((m) => `${m[1]}. ${m[2]}`)

  it("has exactly Overview, Colors, Typography, Elevation, Components, Do's and Don'ts, in order", () => {
    expect(headings).toEqual([
      "1. Overview",
      "2. Colors",
      "3. Typography",
      "4. Elevation",
      "5. Components",
      "6. Do's and Don'ts",
    ])
  })

  it("declares the system in frontmatter with colours, typography, rounded and spacing", () => {
    const frontmatter = designMd.match(/^---\n([\s\S]*?)\n---/)?.[1] ?? ""
    for (const key of ["name:", "colors:", "typography:", "rounded:", "spacing:", "components:"]) {
      expect(frontmatter).toContain(key)
    }
  })

  it("states the card padding as 28px outer and 22px inner", () => {
    const components = designMd.match(/## 5\. Components[\s\S]*?(?=\n## 6\.)/)?.[0] ?? ""
    expect(components).toMatch(/Internal Padding[^\n]*28px[^\n]*22px/)
  })
})

describe("docs/design-canvas-notes.md", () => {
  it("exists", () => {
    expect(() => read("docs/design-canvas-notes.md")).not.toThrow()
  })

  it.each(LEDGER_IDS)("names ledger id %s", (id) => {
    const notes = read("docs/design-canvas-notes.md")
    expect(notes).toContain(id)
  })
})

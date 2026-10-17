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

describe("DESIGN.md §16 Recorded decisions", () => {
  const designMd = read("DESIGN.md")

  it("has a '## 16. Recorded decisions' heading", () => {
    expect(designMd).toMatch(/## 16\. Recorded decisions/)
  })

  it("points at docs/design-canvas-notes.md", () => {
    expect(designMd).toMatch(/docs\/design-canvas-notes\.md/)
  })

  it.each(LEDGER_IDS)("mentions ledger id %s", (id) => {
    expect(designMd).toContain(id)
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

describe("DESIGN.md §13 card padding range", () => {
  const designMd = read("DESIGN.md")
  const section13 = designMd.match(/## 13\. Variation knobs[\s\S]*?(?=\n## 14\.)/)?.[0] ?? ""

  it("Card padding row uses space-6 … space-8, not space-5 … space-10", () => {
    expect(section13).toMatch(/Card padding[^\n]*space-6[^\n]*space-8/)
    expect(section13).not.toMatch(/Card padding[^\n]*space-5[^\n]*space-10/)
  })
})

describe("DESIGN.md §12 Cards rule", () => {
  const designMd = read("DESIGN.md")
  const section12 = designMd.match(/## 12\. Component rules[\s\S]*?(?=\n## 13\.)/)?.[0] ?? ""

  it("notes that marketing cards turn the knob to space-8", () => {
    expect(section12).toMatch(/[Mm]arketing cards[^\n]*space-8/)
  })
})

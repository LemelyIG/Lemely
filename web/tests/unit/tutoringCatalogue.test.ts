import { existsSync, readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"
import { stripComments } from "./support/jsxSource"

/*
 * T15: docs/COMPONENT_CATALOGUE.md gains the rows C-17..C-24 of SPEC §d, each
 * naming a file that exists and an export that file really has. The expected
 * rows come from the SPEC's own component table.
 *
 * The same tests scan the ten files this task added for the two design rules
 * the unit runner can see: design tokens only (no arbitrary Tailwind literal,
 * no raw colour) and logical properties (SPEC §0, PRODUCT.md "RTL").
 */

const WEB = join(import.meta.dirname, "..", "..")
const REPO = join(WEB, "..")
const SPEC = readFileSync(join(REPO, "docs", "tutoring", "SPEC.md"), "utf8")
const CATALOGUE = readFileSync(join(REPO, "docs", "COMPONENT_CATALOGUE.md"), "utf8")

interface SpecRow {
  id: string
  file: string
}

function specRows(): SpecRow[] {
  const rows: SpecRow[] = []
  for (const line of SPEC.split("\n")) {
    const match = /^\| (C-\d+) \| `([a-z-]+\.tsx)` \|/.exec(line)
    if (match) rows.push({ id: match[1], file: match[2] })
  }
  return rows
}

function catalogueSection(id: string): string | null {
  const lines = CATALOGUE.split("\n")
  const start = lines.findIndex((line) => line.startsWith(`## ${id} `))
  if (start === -1) return null
  let end = lines.findIndex((line, i) => i > start && line.startsWith("## "))
  if (end === -1) end = lines.length
  return lines.slice(start, end).join("\n")
}

const ROWS = specRows()

describe("SPEC section d component table", () => {
  it("lists C-17 to C-24, eight components", () => {
    expect(ROWS.map((r) => r.id)).toEqual([
      "C-17",
      "C-18",
      "C-19",
      "C-20",
      "C-21",
      "C-22",
      "C-23",
      "C-24",
    ])
  })
})

describe("COMPONENT_CATALOGUE.md rows", () => {
  for (const row of ROWS) {
    it(`${row.id} names ${row.file}, which exists, and an export that file has`, () => {
      const section = catalogueSection(row.id)
      expect(section, `no "## ${row.id} " heading in the catalogue`).not.toBeNull()
      expect(section).toContain(`\`${row.file}\``)

      const path = join(WEB, "src", "components", "ui", row.file)
      expect(existsSync(path), path).toBe(true)

      const exported = /`([A-Z][A-Za-z]+)\(\{/.exec(section ?? "")?.[1]
      expect(exported, "the row should show the component and its props").toBeDefined()
      expect(readFileSync(path, "utf8")).toMatch(new RegExp(`export function ${exported}\\b`))
    })
  }

  it("also lists the report and block sheets by their files", () => {
    for (const file of ["report-sheet.tsx", "block-sheet.tsx"]) {
      expect(CATALOGUE).toContain(`web/src/components/tutoring/${file}`)
      expect(existsSync(join(WEB, "src", "components", "tutoring", file))).toBe(true)
    }
  })

  it("keeps the earlier rows C-1 to C-16", () => {
    for (let n = 1; n <= 16; n++) expect(catalogueSection(`C-${n}`), `C-${n}`).not.toBeNull()
  })
})

const OWNED_COMPONENTS = [
  ...ROWS.map((r) => join("components", "ui", r.file)),
  join("components", "tutoring", "report-sheet.tsx"),
  join("components", "tutoring", "block-sheet.tsx"),
]

describe("design rules in the new components", () => {
  const sources = () => OWNED_COMPONENTS.map((file) => ({
    file,
    code: stripComments(readFileSync(join(WEB, "src", file), "utf8")),
  }))

  it("scans ten files", () => {
    expect(sources()).toHaveLength(10)
  })

  it("uses tokens: no arbitrary Tailwind value, no raw colour", () => {
    for (const { file, code } of sources()) {
      expect(code, `${file}: arbitrary value`).not.toMatch(/\b[a-z-]+-\[[^\]]*\d[^\]]*\]/)
      expect(code, `${file}: hex colour`).not.toMatch(/#[0-9a-fA-F]{3,8}\b/)
      expect(code, `${file}: raw colour function`).not.toMatch(/\b(?:rgb|rgba|hsl|oklch)\(/)
    }
  })

  it("uses logical properties, never a hard-coded left or right", () => {
    for (const { file, code } of sources()) {
      expect(code, file).not.toMatch(/\b(?:ml|mr|pl|pr)-\d/)
      expect(code, file).not.toMatch(/\b(?:left|right)-\d/)
      expect(code, file).not.toMatch(/\btext-(?:left|right)\b/)
    }
  })

  it("keeps pills for chips and badges: no stray rounded-full", () => {
    for (const { file, code } of sources()) {
      expect(code, file).not.toContain("rounded-full")
    }
  })
})

describe("pre-emit critique stamps", () => {
  // `hallmarkStamp.test.ts` checks that a stamp exists and scores 3 or better. It
  // cannot tell a critique from a copy, so this reads each stamp's own line: the
  // six scores, then a rationale saying what was checked in THIS file.
  const LINE = /^\/\* Hallmark · pre-emit critique: (P[1-5] H[1-5] E[1-5] S[1-5] R[1-5] V[1-5]) — (.+) \*\/$/

  const stamps = OWNED_COMPONENTS.map((file) => {
    const first = readFileSync(join(WEB, "src", file), "utf8").split("\n", 1)[0]
    return { file, match: LINE.exec(first), first }
  })

  it("every new component carries a stamp with a rationale on its first line", () => {
    for (const { file, match, first } of stamps) {
      expect(match, `${file}: ${first}`).not.toBeNull()
      expect(match?.[2].length ?? 0, `${file}: rationale too short`).toBeGreaterThanOrEqual(40)
    }
  })

  it("no two components share a rationale, and the scores are not one stamp copied around", () => {
    const rationales = stamps.map((s) => s.match?.[2])
    expect(new Set(rationales).size).toBe(stamps.length)
    const scores = stamps.map((s) => s.match?.[1])
    expect(new Set(scores).size).toBeGreaterThanOrEqual(5)
  })

  it("scores every axis at 3 or better, as the stamp gate requires", () => {
    for (const { file, match } of stamps) {
      for (const axis of (match?.[1] ?? "").split(" ")) {
        expect(Number(axis.slice(1)), `${file}: ${axis}`).toBeGreaterThanOrEqual(3)
      }
    }
  })
})

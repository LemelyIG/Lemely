import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"
import { PRACTICE_SOURCES } from "@/lib/practiceSources"

/*
 * Task 8 (C3c) · `content-practice-source-filter-dead-in-ui`. Cross-language
 * pin, the same technique `design-tokens.test.ts` uses for `index.css`:
 * reads `lemely/db/models/enums.py`'s `QuestionSource` enum with a regex and
 * checks `PRACTICE_SOURCES` names the identical values, so a renamed or
 * added backend source can never go stale in this control silently.
 */

const ENUMS_PY = fileURLToPath(new URL("../../../lemely/db/models/enums.py", import.meta.url))
const source = readFileSync(ENUMS_PY, "utf8")
const block = source.match(/class QuestionSource\(enum\.Enum\):([\s\S]*?)\n\n\n/)
const backendValues = block
  ? [...block[1].matchAll(/^\s*\w+\s*=\s*"([^"]+)"/gm)].map((m) => m[1])
  : []

describe("PRACTICE_SOURCES mirrors the backend QuestionSource enum", () => {
  it("finds the QuestionSource block in enums.py", () => {
    // If this fails, the case below passes vacuously over an empty list.
    expect(block, "QuestionSource enum not found in lemely/db/models/enums.py").not.toBeNull()
    expect(backendValues.length).toBeGreaterThan(0)
  })

  it("has one entry per backend value, plus the 'All sources' null option", () => {
    const nonNullValues = PRACTICE_SOURCES.filter((s) => s.value !== null).map((s) => s.value)
    expect([...nonNullValues].sort()).toEqual([...backendValues].sort())
    expect(
      PRACTICE_SOURCES.some((s) => s.value === null && s.label === "All sources"),
    ).toBe(true)
  })

  it("has exactly one null 'All sources' entry, not a real source masquerading as it", () => {
    expect(PRACTICE_SOURCES.filter((s) => s.value === null)).toHaveLength(1)
  })
})

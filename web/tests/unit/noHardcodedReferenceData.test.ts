import { readdirSync, readFileSync, statSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"

/*
 * The frontend must not declare data the backend owns.
 *
 * Six copies of the grade vocabulary drifted apart before `/api/reference`
 * existed, and they disagreed: four omitted F and G, which Core-tier papers
 * genuinely award. Nothing caught that, because a constant no list claims is a
 * constant no gate reads. This is that list.
 *
 * Add a pattern here whenever the backend takes ownership of a table. Do not
 * add an exemption for a new file — fetch the data instead.
 */

const ROOT = new URL("../../src", import.meta.url).pathname

/** Files allowed to mention a value, because they define the fetch or the test. */
const ALLOWED = new Set([
  "lib/referenceTypes.ts",
  "lib/reference.ts",
  "lib/hooks/useReferenceApi.ts",
  // `subjectIcon`'s glyph map keys on syllabus codes, so it trips the catalogue
  // pattern. Spec D6 keeps it in the frontend deliberately: a glyph is
  // presentation with no backend counterpart, and it already falls back to a
  // generic icon for an unknown code. Exempted by path, not by loosening the
  // pattern, so the pattern still guards every other file.
  "portals/student/data.ts",
])

const FORBIDDEN: { name: string; pattern: RegExp }[] = [
  {
    name: "the grade vocabulary (served as targetGradeVocabularies)",
    pattern: /\[\s*"A\*"\s*,\s*"A"\s*,\s*"B"\s*,/,
  },
  {
    name: "qualification levels (served as qualificationLevels)",
    pattern: /"igcse"[\s\S]{0,80}"o_level"/,
  },
  {
    name: "session months (served as sessionMonths)",
    pattern: /"may_june"[\s\S]{0,80}"oct_nov"/,
  },
  {
    name: "difficulty bands (served as difficultyBands)",
    pattern: /"foundation"[\s\S]{0,60}"standard"[\s\S]{0,60}"challenge"/,
  },
  {
    name: "the subject catalogue (served as subjects)",
    pattern: /"0625"[\s\S]{0,120}"0580"/,
  },
]

function sourceFiles(dir: string, base = ""): string[] {
  const out: string[] = []
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry)
    const rel = base ? `${base}/${entry}` : entry
    if (statSync(full).isDirectory()) out.push(...sourceFiles(full, rel))
    else if (/\.tsx?$/.test(entry)) out.push(rel)
  }
  return out
}

describe("no hardcoded reference data in web/src", () => {
  const files = sourceFiles(ROOT)

  it("finds source files to scan", () => {
    expect(files.length).toBeGreaterThan(50)
  })

  for (const { name, pattern } of FORBIDDEN) {
    it(`does not redeclare ${name}`, () => {
      const offenders = files.filter(
        (rel) => !ALLOWED.has(rel) && pattern.test(readFileSync(join(ROOT, rel), "utf8")),
      )
      expect(offenders, `fetch this from /api/reference instead of declaring it`).toEqual([])
    })
  }
})

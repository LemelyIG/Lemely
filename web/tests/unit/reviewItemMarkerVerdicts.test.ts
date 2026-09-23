import { describe, expect, it } from "vitest"
import { readFileSync } from "node:fs"
import { join } from "node:path"
import { stripComments } from "./support/jsxSource"

/*
 * US-046 (task #46), the frontend half of US-013 acceptance 4. US-045
 * persisted I6/I7's per-point marker verdict (`verdict`/`evidenceSpan`/
 * `ecfApplied`) on `question_result_points`; nothing read it. Before this:
 * `SelfReviewPoints` filtered to `p.studentSelfmark !== null`, so a point the
 * marker verdicted and the student never touched rendered nowhere on this
 * screen at all, and `withheld`/`unverifiable` both collapsed to
 * `awarded: false` with no way to tell them apart.
 *
 * Source-text checks (not render tests), same reasoning as
 * `selfReviewTeacherWiring.test.ts`: this repo's vitest runner is
 * `environment: "node"` with no jsdom/RTL (`vitest.config.ts`) — component
 * rendering is Playwright's job, this gate is for the pure logic and the
 * repo invariants no browser test can see.
 */

const ROOT = join(import.meta.dirname, "..", "..")

function readSource(relativePath: string): string {
  return stripComments(readFileSync(join(ROOT, relativePath), "utf8"))
}

const reviewItemSource = readSource("src/portals/teacher/screens/ReviewItem.tsx")
const teacherTypesSource = readSource("src/lib/teacherTypes.ts")

function functionBody(source: string, name: string, nextName: string): string {
  const fnStart = source.indexOf(`function ${name}(`)
  expect(fnStart, `function ${name} not found`).toBeGreaterThan(-1)
  const fnEnd = source.indexOf(`function ${nextName}(`, fnStart)
  expect(fnEnd, `function ${nextName} not found after ${name}`).toBeGreaterThan(fnStart)
  return source.slice(fnStart, fnEnd)
}

describe("teacherTypes.ts — ReviewItemPoint carries the marker's verdict", () => {
  it("adds verdict, evidenceSpan and ecfApplied to ReviewItemPoint", () => {
    const ifaceStart = teacherTypesSource.indexOf("export interface ReviewItemPoint {")
    expect(ifaceStart).toBeGreaterThan(-1)
    const ifaceEnd = teacherTypesSource.indexOf("}", ifaceStart)
    const body = teacherTypesSource.slice(ifaceStart, ifaceEnd)
    expect(body).toMatch(/verdict:\s*"awarded"\s*\|\s*"withheld"\s*\|\s*"unverifiable"\s*\|\s*null/)
    expect(body).toContain("evidenceSpan: string")
    expect(body).toContain("ecfApplied: boolean")
  })

  it("ReviewItemDetail's doc comment no longer calls matchedPointIds the honest substitute this backend can provide", () => {
    // The false-precision docstring this task was told to correct
    // (`ReviewItemDetailDTO`'s Python mirror, same claim). It must not
    // survive verbatim on the TS side either.
    expect(teacherTypesSource).not.toContain(
      "the honest substitutes this backend can actually provide",
    )
  })
})

describe("ReviewItem.tsx — MarkerVerdicts renders I6/I7 for every point", () => {
  const body = functionBody(reviewItemSource, "MarkerVerdicts", "AwardedMarks")

  it("is not filtered by studentSelfmark, unlike SelfReviewPoints beside it", () => {
    // The actual defect: SelfReviewPoints' filter hid every marker-verdicted
    // point the student never self-marked. MarkerVerdicts must not repeat it.
    // Asserting the row-list structure, not the absence of one string: a
    // `.filter(...)` gated on any other field (e.g. `p.verdict !== null`)
    // would silently reintroduce the same defect and pass a substring check.
    expect(body).toMatch(/\{points\.map\(/)
    expect(body).not.toMatch(/points\.filter\(/)
  })

  it("bails out only on an empty points array, not any other filter", () => {
    expect(body).toContain("if (points.length === 0) return null")
  })

  it("renders a distinct tone AND a distinct label for each of the three verdicts", () => {
    const toneMapStart = reviewItemSource.indexOf("const POINT_VERDICT_TONE")
    const labelMapStart = reviewItemSource.indexOf("const POINT_VERDICT_LABEL")
    expect(toneMapStart).toBeGreaterThan(-1)
    expect(labelMapStart).toBeGreaterThan(-1)
    const toneMapEnd = reviewItemSource.indexOf("}", reviewItemSource.indexOf("{", toneMapStart))
    const labelMapEnd = reviewItemSource.indexOf("}", reviewItemSource.indexOf("{", labelMapStart))
    const toneMap = reviewItemSource.slice(toneMapStart, toneMapEnd)
    const labelMap = reviewItemSource.slice(labelMapStart, labelMapEnd)

    // withheld and unverifiable both read `awarded: false`; the tones (and
    // the labels) for them must differ from each other, not just from
    // awarded's.
    const toneOf = (verdict: string) => {
      const match = toneMap.match(new RegExp(`${verdict}:\\s*"([a-z]+)"`))
      expect(match, `${verdict} missing from POINT_VERDICT_TONE`).not.toBeNull()
      return match?.[1]
    }
    const labelOf = (verdict: string) => {
      const match = labelMap.match(new RegExp(`${verdict}:\\s*"([^"]+)"`))
      expect(match, `${verdict} missing from POINT_VERDICT_LABEL`).not.toBeNull()
      return match?.[1]
    }
    expect(toneOf("withheld")).not.toBe(toneOf("unverifiable"))
    expect(toneOf("awarded")).not.toBe(toneOf("withheld"))
    expect(toneOf("awarded")).not.toBe(toneOf("unverifiable"))
    expect(labelOf("withheld")).not.toBe(labelOf("unverifiable"))
  })

  it("falls back to point.awarded when verdict is null, never to a bare denial that any verdict exists", () => {
    // Team-lead finding on c15c119a: a pre-I6 point has no `verdict`, but
    // `derive_point_rows` never wrote anything else before I6, so `awarded`
    // IS that point's marker verdict. Rendering "No verdict recorded" and
    // stopping there threw away real information the row carries -- worse
    // than the invisibility defect this task exists to fix, because it
    // replaces a real answer with an explicit denial that one exists.
    expect(body).not.toContain("No verdict recorded")
    // The fallback branch must be gated on the verdict itself, not reachable
    // only alongside one specific real verdict, and it must read `awarded`.
    const fallbackMatch = body.match(/point\.verdict\s*\?[\s\S]*?:\s*\(([\s\S]*?)\)\s*}/)
    expect(fallbackMatch, "verdict ? ... : ( ... ) branch not found").not.toBeNull()
    const fallback = fallbackMatch?.[1] ?? ""
    expect(fallback).toContain("point.awarded")
    expect(fallback).toMatch(/awarded.*not awarded/)
  })

  it("marks an ecfApplied point as carried forward", () => {
    expect(body).toContain("point.ecfApplied")
    expect(body).toMatch(/Carried forward/)
  })

  it("renders evidenceSpan, the quoted student text the marker cited, when non-empty", () => {
    expect(body).toContain("point.evidenceSpan")
  })

  it("keys each row on markPointId, same as SelfReviewPoints, so React never misidentifies rows across re-renders", () => {
    expect(body).toContain("key={point.markPointId}")
  })
})

describe("ReviewItem.tsx — SelfReviewPoints keeps answering a different question", () => {
  it("still filters to what the student actually self-marked", () => {
    const body = functionBody(reviewItemSource, "SelfReviewPoints", "MarkerVerdicts")
    expect(body).toContain("p.studentSelfmark !== null")
  })
})

describe("ReviewItem.tsx — matchedPointIds is demoted beneath the real per-point verdicts", () => {
  it("MarkerVerdicts renders before the matchedPointIds chip block, which renders before SelfReviewPoints", () => {
    const markerVerdictsCall = reviewItemSource.indexOf("<MarkerVerdicts points={detail.points} />")
    const matchedPointIdsBlock = reviewItemSource.indexOf("detail.matchedPointIds.map((id) =>")
    const selfReviewPointsCall = reviewItemSource.indexOf("<SelfReviewPoints points={detail.points} />")

    expect(markerVerdictsCall).toBeGreaterThan(-1)
    expect(matchedPointIdsBlock).toBeGreaterThan(-1)
    expect(selfReviewPointsCall).toBeGreaterThan(-1)
    expect(matchedPointIdsBlock).toBeGreaterThan(markerVerdictsCall)
    expect(selfReviewPointsCall).toBeGreaterThan(matchedPointIdsBlock)
  })

  it("the evidence section's expected-answer card no longer carries its own matchedPointIds chips", () => {
    // Requirement 8: replaced by, or demoted beneath, MarkerVerdicts — not
    // left duplicated in both places.
    const evidenceSectionStart = reviewItemSource.indexOf("What Lemely saw")
    const whatLemelyAwardedStart = reviewItemSource.indexOf("What Lemely awarded")
    expect(evidenceSectionStart).toBeGreaterThan(-1)
    expect(whatLemelyAwardedStart).toBeGreaterThan(evidenceSectionStart)
    const evidenceSection = reviewItemSource.slice(evidenceSectionStart, whatLemelyAwardedStart)
    expect(evidenceSection).not.toContain("detail.matchedPointIds.map")
  })
})

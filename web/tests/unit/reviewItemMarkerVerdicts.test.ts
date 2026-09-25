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
    // `verdict` is typed by the exported alias rather than an inline union, so
    // the three members are pinned at the alias's own declaration below. Both
    // halves are asserted: the field must use the alias, and the alias must
    // still name exactly those three members — checking only the field would
    // let the alias widen silently, and checking only the alias would let the
    // field stop using it.
    expect(body).toMatch(/verdict:\s*PointVerdictWire\s*\|\s*null/)
    // Anchored to end-of-line on purpose: an unanchored pattern matches a
    // PREFIX, so `| "partial"` appended to the alias slides straight past it
    // — verified by appending exactly that and watching the unanchored form
    // still pass 12/12.
    expect(teacherTypesSource).toMatch(
      /^export type PointVerdictWire = "awarded" \| "withheld" \| "unverifiable"$/m,
    )
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
    //
    // What this pins and what it cannot: this is source text, not a render,
    // so it can only pin the SHAPE of the iteration — that the list comes
    // from `{points.map(`, not from a `.filter(` placed around it. It cannot
    // pin "every element of `points` produces output", which is a runtime
    // property only a render can observe. A guard placed one level deeper,
    // inside the map callback itself —
    // `points.map((point) => point.verdict === null ? null : (...))` —
    // re-creates the exact same invisible-point defect this test exists to
    // catch, while still matching `{points.map(` and never matching
    // `points.filter(`: it passes every assertion here, with a clean
    // `tsc --noEmit`. This runner is `environment: "node"` with no jsdom
    // (see the module doc comment above), so no render is possible in this
    // file to close that gap. The real closure is a Playwright spec for
    // `/teacher/review`, which does not exist yet (task #50) — do not add
    // another regex here to chase the callback-guard shape; the next
    // mutation just steps one level deeper again.
    expect(body).toMatch(/\{points\.map\(/)
    expect(body).not.toMatch(/points\.filter\(/)
  })

  it("still bails out on an empty points array, now as one arm of a broader suppression guard", () => {
    // US-046 follow-up (task #4): the guard widened to also suppress a
    // section where every point carries `verdict: null` (see the dedicated
    // suppression test below) — `points.length === 0` remains one of its two
    // conditions rather than the whole guard, so this only pins that the
    // empty-array case still short-circuits, not the old exact-string form.
    expect(body).toMatch(/points\.length === 0 \|\|/)
  })

  it("renders the marker's rationale when present", () => {
    expect(body).toContain("point.rationale")
  })

  it("suppresses the section only when no point carries a verdict or a rationale", () => {
    // Section-level suppression, NOT per-point: a per-point filter re-creates
    // the invisible-point defect this component exists to fix. Verified
    // behaviourally in web/e2e/teacher-review.spec.ts; this only pins that the
    // guard is on the collection, not on each element. The `{points.map(` /
    // `not.toMatch(points.filter()` half of this is already pinned by "is not
    // filtered by studentSelfmark" above; this test's own contribution is the
    // guard expression itself.
    //
    // The `|| p.rationale` half matters: with `equivalence_gate` off, every
    // `verdict` is null, so a `p.verdict !== null`-only guard would suppress
    // this section even when a point carries a marker `rationale` -- the one
    // thing this component exists to surface today. A guard narrowed back to
    // `p.verdict !== null` alone passes every OTHER assertion in this file
    // (including the one above) with a clean `tsc --noEmit`; only this line
    // catches it.
    expect(body).toMatch(/points\.some\(\(p\) => p\.verdict !== null \|\| p\.rationale\)/)
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

describe("ReviewItem.tsx — evidence banner no longer misdescribes what's retained", () => {
  // Whitespace-normalized: the JSX text wraps mid-sentence across several
  // indented lines, so the literal multi-word phrase is never one contiguous
  // substring of the raw source (different lines carry different indentation)
  // — an un-normalized `.not.toContain` check on this exact phrase trivially
  // passes even against the unfixed source, which is a false RED. Verified by
  // running the un-normalized form first and watching it pass before any
  // implementation change.
  const normalizedSource = reviewItemSource.replace(/\s+/g, " ")

  it("the evidence banner no longer claims the mark scheme's wording isn't stored", () => {
    // False, and the same class of false as the sentence this test module's
    // name commemorates fixing: `AnswerPoint.point` IS stored verbatim
    // (`loose_schemas.py:205-208`, snapshotted onto `point_text` per
    // `attempts.py:333,378`) and rendered on this same screen as
    // `point.pointText` (`MarkerVerdicts`/`SelfReviewPoints`, a screenful
    // below this banner). Dropped rather than replaced with another claim
    // about what the scheme does or doesn't store -- every version of this
    // clause tried so far has been false.
    expect(normalizedSource).not.toContain("mark scheme's own wording isn't stored")
  })

  it("the 'does not display the scan' clause survives, gated behind whatever renders the crop", () => {
    // Task #72: the clause is no longer unconditionally true -- once a crop
    // renders, this screen DOES display a region of the scan. The false
    // branch must still read exactly this, since it remains the honest
    // answer for the (common) case where no crop is showing.
    expect(normalizedSource).toContain("This screen does not display the original scan.")
    // Anchored to the exact boolean this task's own binding requirement
    // names: `hasSourceBox` alone over-promises (a 404 is still possible),
    // so the guard must also depend on `cropUrl` actually being present, not
    // just on the flag.
    expect(normalizedSource).toMatch(/detail\.hasSourceBox && cropUrl/)
  })

  it("the transcription sentence sits outside the conditional, exactly once", () => {
    // If this sentence were duplicated inside both ternary branches (rather
    // than written once, after the conditional), it would still read
    // correctly on screen but would double the surface area for the two
    // copies to drift apart, which is exactly the failure mode this banner
    // has now hit twice. Counting occurrences (not just presence) is what
    // catches a regression back to "one copy per branch".
    const sentence = "What's below is Lemely's own transcription of the student's answer."
    const occurrences = normalizedSource.split(sentence).length - 1
    expect(occurrences).toBe(1)
  })

  it("the true branch says the screen shows the region of the scan, not just that a box exists", () => {
    expect(normalizedSource).toContain(
      "This screen shows the region of the student's scan this answer was read from.",
    )
  })
})

describe("ReviewItem.tsx — the scan crop renders only when a crop is actually available", () => {
  it("useReviewItemCrop is called at the top level, gated on hasSourceBox, not inside the render prop", () => {
    // Rules-of-Hooks: a hook called inside `<QueryState>`'s render-prop
    // callback would belong to QueryState's own fiber, not this component's,
    // and QueryState does not call that callback on every one of ITS
    // renders (loading/error branches skip it) -- exactly the conditional
    // hook call React's rules forbid. Every other per-detail hook in this
    // file (none exist yet) would hit the same trap; this one is called
    // where `detailQuery`/`queueQuery` already are.
    const topLevelStart = reviewItemSource.indexOf("const detailQuery = useReviewItem(itemId)")
    const renderPropStart = reviewItemSource.indexOf("{(detail) => {")
    const cropHookCall = reviewItemSource.indexOf("useReviewItemCrop(itemId,")
    expect(topLevelStart).toBeGreaterThan(-1)
    expect(renderPropStart).toBeGreaterThan(topLevelStart)
    expect(cropHookCall).toBeGreaterThan(topLevelStart)
    expect(cropHookCall).toBeLessThan(renderPropStart)
    expect(reviewItemSource).toContain("detailQuery.data?.hasSourceBox ?? false")
  })

  it("guards the image on hasSourceBox AND the fetched url, and the guard wraps the whole image", () => {
    // "wraps the image" rather than sitting elsewhere: the img element must
    // be inside the branch this condition selects, not merely present
    // somewhere later in the file. `functionBody`-style slicing isn't
    // available here (this isn't a named function), so the check is
    // structural: the guard, the `<img`, and its closing `) : null}` appear
    // in that order with nothing but the image's own card between them.
    const guardStart = reviewItemSource.indexOf("scanCropVisible && cropUrl ? (")
    expect(guardStart).toBeGreaterThan(-1)
    const imgStart = reviewItemSource.indexOf("<img", guardStart)
    const guardEnd = reviewItemSource.indexOf(") : null}", guardStart)
    expect(imgStart).toBeGreaterThan(guardStart)
    expect(guardEnd).toBeGreaterThan(imgStart)
  })

  it("the image src is built from the crop route, with alt text naming what it is", () => {
    const guardStart = reviewItemSource.indexOf("scanCropVisible && cropUrl ? (")
    const guardEnd = reviewItemSource.indexOf(") : null}", guardStart)
    const block = reviewItemSource.slice(guardStart, guardEnd)
    expect(block).toContain("src={cropUrl}")
    // `cropUrl` itself comes from `useReviewItemCrop`, which fetches
    // `/teacher/review/${itemId}/crop` -- asserted on the hook, not here,
    // since this block only ever sees the already-fetched object URL. What
    // this DOES pin: the alt text names the region as what it is, and never
    // as evidence for one mark point (question-level, not per-point).
    expect(block).toMatch(/alt="[^"]*region of the student's scan[^"]*"/)
    expect(block).not.toMatch(/alt="[^"]*mark point[^"]*"/)
  })

  it("useReviewItemCrop fetches the crop route and never introduces a lightbox, zoom, or placeholder image", () => {
    const hooksSource = readSource("src/lib/hooks/useTeacherApi.ts")
    expect(hooksSource).toContain("`/teacher/review/${itemId}/crop`")
    expect(reviewItemSource).not.toMatch(/lightbox/i)
    expect(reviewItemSource).not.toMatch(/zoom/i)
  })

  it("the caption does not imply the region justifies a particular mark point", () => {
    const guardStart = reviewItemSource.indexOf("scanCropVisible && cropUrl ? (")
    const guardEnd = reviewItemSource.indexOf(") : null}", guardStart)
    const block = reviewItemSource.slice(guardStart, guardEnd)
    expect(block).toContain("The region of the student's scan this answer was read from")
    expect(block).not.toMatch(/mark point|justifies|awarded this mark/i)
  })
})

import { describe, expect, it } from "vitest"
import { readFileSync } from "node:fs"
import { join } from "node:path"
import { stripComments } from "./support/jsxSource"
import { cropUrlFor, type FetchedCrop } from "@/lib/hooks/useTeacherApi"
import { markPointsFrom } from "@/portals/teacher/screens/review/markModel"
import type { ReviewItemPoint } from "@/lib/teacherTypes"

/*
 * US-046 (task #46), the frontend half of US-013 acceptance 4. US-045
 * persisted I6/I7's per-point marker verdict (`verdict`/`evidenceSpan`/
 * `ecfApplied`) on `question_result_points`; nothing read it. Before this:
 * the old `SelfReviewPoints` filtered to `p.studentSelfmark !== null`, so a point the
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

const markControlsSource = readSource("src/portals/teacher/screens/review/MarkControls.tsx")
const teacherTypesSource = readSource("src/lib/teacherTypes.ts")

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

/*
 * The old `ReviewItem.tsx` that these checks used to read is gone (L5). The marker's verdict now
 * reaches the teacher through `markPointsFrom` (the data) and `MarkControls` (one row per point).
 */
const wire = (over: Partial<ReviewItemPoint>): ReviewItemPoint => ({
  markPointId: "mp", pointText: "Point", awarded: false, studentSelfmark: null, studentEvidence: null,
  evidenceVerdict: null, verdict: null, evidenceSpan: "", ecfApplied: false, rationale: null,
  ordinal: 1, markType: "M", tariff: 1, groupKey: null, groupMaxMarks: null, ...over,
})

describe("markPointsFrom carries the marker's verdict for every point, selfmarked or not", () => {
  const rows = markPointsFrom([
    wire({ markPointId: "a", ordinal: 1, verdict: "awarded", awarded: true, evidenceSpan: "54 / 20" }),
    wire({ markPointId: "b", ordinal: 2, verdict: "withheld", rationale: "No unit." }),
    wire({ markPointId: "c", ordinal: 3, verdict: "unverifiable", ecfApplied: true }),
    wire({ markPointId: "d", ordinal: 4, studentSelfmark: null }),
  ])

  it("returns one row per point, so a point the student never touched is not dropped", () => {
    expect(rows.map((r) => r.markPointId)).toEqual(["a", "b", "c", "d"])
  })

  it("labels withheld and unverifiable differently, and says nothing for awarded or no verdict", () => {
    expect(rows.map((r) => r.verdictLabel)).toEqual([null, "Judged absent", "Couldn't confirm", null])
  })

  it("quotes the evidence span, falls back to the rationale, and flags carried-forward marks", () => {
    expect(rows[0].note).toBe("\u201c54 / 20\u201d")
    expect(rows[1].note).toBe("No unit.")
    expect(rows[2].ecf).toBe(true)
    expect(rows[3].note).toBeNull()
  })
})

describe("MarkControls.tsx renders a verdict row for every point", () => {
  it("iterates the whole points array, never a filtered one", () => {
    // Source text, not a render (environment: "node"): it pins the shape of the iteration. The
    // render itself is covered by reviewAnswerPanel.test.ts and the Playwright review spec.
    expect(markControlsSource).toMatch(/\bpoints\.map\(/)
    expect(markControlsSource).not.toMatch(/points\.filter\(/)
  })

  it("draws the verdict row inside that map, with its label and the carried-forward tag", () => {
    const mapAt = markControlsSource.search(/\bpoints\.map\(/)
    const rowAt = markControlsSource.indexOf('data-testid="marker-verdict-row"')
    expect(rowAt).toBeGreaterThan(mapAt)
    expect(markControlsSource).toContain("p.verdictLabel")
    expect(markControlsSource).toContain("Carried forward")
  })
})

describe("the scan crop is fetched by the shared image hook", () => {
  it("useAnswerImages asks for the crop only when the item has a scan, at the top level of the hook", () => {
    const src = readSource("src/portals/teacher/screens/review/useAnswerImages.ts")
    expect(src).toMatch(/useReviewItemImage\(itemId, "crop", hasScan\)/)
    // Rules of Hooks: both image hooks run unconditionally, inside the function body.
    expect(src.indexOf('useReviewItemImage(itemId, "crop"')).toBeGreaterThan(src.indexOf("export function useAnswerImages"))
  })

  it("useReviewItemCrop fetches the crop route", () => {
    const hooksSource = readSource("src/lib/hooks/useTeacherApi.ts")
    expect(hooksSource).toContain("`/teacher/review/${itemId}/crop`")
  })
})

describe("cropUrlFor — the C1 fix, as a real behavioural unit (team-lead review of task #72)", () => {
  // A genuine import and call, not a source-text check: `cropUrlFor` is a
  // pure function with no DOM/render dependency, so this runs in
  // milliseconds with no stack and actually exercises the rule C1 is about,
  // rather than pinning its call site's spelling. This is strictly better
  // than the Playwright navigation spec for THIS one rule -- the render test
  // still exists (`web/e2e/teacher-review.spec.ts`) because it is the only
  // thing that can prove the fix survives inside a real React render/effect
  // cycle, not because this unit test is insufficient on its own terms.
  const boxedA: FetchedCrop = { itemId: "item-a", url: "blob:a" }

  it("returns the fetched url when it matches the current itemId", () => {
    expect(cropUrlFor("item-a", boxedA)).toBe("blob:a")
  })

  it("returns null when nothing has been fetched yet", () => {
    expect(cropUrlFor("item-a", null)).toBeNull()
  })

  it("C1: returns null when the fetched url belongs to a DIFFERENT itemId", () => {
    // This is the exact shape of the bug: `fetched` still holds item A's
    // (or B's) url from before a client-side navigation, and the CURRENT
    // `itemId` has already moved on to a render restoring a different item.
    expect(cropUrlFor("item-b", boxedA)).toBeNull()
  })

  it("returns null when itemId is undefined", () => {
    expect(cropUrlFor(undefined, boxedA)).toBeNull()
  })

  // F2 (team-lead review): the unit cases above close the RULE, but they say
  // nothing about whether `useReviewItemCrop` actually CALLS `cropUrlFor` --
  // a hook that bypasses it (e.g. `return { url: fetched?.url ?? null,
  // onDecodeError }`) keeps all four green, since none of them import or
  // exercise the hook itself. Traced against the C1 Playwright test: on
  // navigating back to A, a bypassed hook renders B's stale entry under A's
  // name for exactly the one render before its OWN effect resets and
  // refetches -- the same racy window the original defect lived in, and one
  // `expect.poll` waiting for `naturalWidth > 0` can miss it entirely if A's
  // refetch resolves before the poll's next tick. So this IS a structural
  // invariant that is behaviourally unreachable without jsdom (D3.20 rules
  // that out) -- the same justification the kept Rules-of-Hooks check
  // carries, and the opposite of the five pins deleted earlier in this
  // task's review, which Playwright already covered without racing.
  it("F2: useReviewItemCrop's return actually composes cropUrlFor, not a bypass", () => {
    const hooksSource = readSource("src/lib/hooks/useTeacherApi.ts")
    expect(hooksSource).toContain("url: cropUrlFor(itemId, fetched)")
  })
})

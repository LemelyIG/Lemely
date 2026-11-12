import { describe, expect, it } from "vitest"
import { readFileSync } from "node:fs"
import { join } from "node:path"
import { functionBody, stripComments } from "./support/jsxSource"

/*
 * Source-text gates for student paper deletion (spec 2026-09-22, Task 14).
 * Neither the hooks nor the screens are mountable under this suite's
 * DOM-less Node environment (`vitest.config.ts`, D3.20) — same reasoning
 * `selfReviewWiring.test.ts` records for the sibling self-review surface.
 *
 * What these gates exist to catch, specifically:
 *   - a delete that trusts its own optimistic row removal for the overview
 *     and subject screens, which is exactly the positional-URL trap
 *     (design §2.1) this feature was built around;
 *   - a delete control that pre-signals a held paper (design §8) by
 *     rendering disabled or differently for one;
 *   - a Recently Deleted screen that quietly drops back to the mock/empty
 *     shape instead of the real hooks.
 */

const ROOT = join(import.meta.dirname, "..", "..")

function readSource(relativePath: string): string {
  return stripComments(readFileSync(join(ROOT, relativePath), "utf8"))
}

describe("usePaperDeletionApi.ts — useDeletePaper", () => {
  const source = readSource("src/lib/hooks/usePaperDeletionApi.ts")

  it("invalidates the overview after a delete rather than trusting the optimistic list", () => {
    const body = functionBody(source, "useDeletePaper")
    expect(body).toContain("invalidateQueries")
    expect(body).toMatch(/overview/)
  })

  it("also invalidates the subject query, the list's own screen", () => {
    const body = functionBody(source, "useDeletePaper")
    expect(body).toMatch(/"student", "subject"/)
  })

  it("requests no fallback value, so a 409 hold reaches the caller as an error", () => {
    expect(source).not.toContain("fallback")
  })

  it("useRestorePaper invalidates the same surfaces a delete does", () => {
    const body = functionBody(source, "useRestorePaper")
    expect(body).toContain("invalidateQueries")
    expect(body).toMatch(/overview/)
  })

  it("drops the cached result for the just-deleted paper, since its own URL is positional too", () => {
    const body = functionBody(source, "useDeletePaper")
    expect(body).toMatch(/removeQueries/)
    expect(body).toMatch(/"student", "result"/)
  })

  it("useRestorePaper drops the same cached result", () => {
    const body = functionBody(source, "useRestorePaper")
    expect(body).toMatch(/removeQueries/)
    expect(body).toMatch(/"student", "result"/)
  })
})

describe("PaperResult.tsx — the delete control", () => {
  const source = readSource("src/portals/student/screens/PaperResult.tsx")

  it("never renders a disabled delete control", () => {
    expect(source).not.toMatch(/disabled=\{[^}]*deletabl/i)
  })

  it("the control's own body carries no disabled prop at all", () => {
    const body = functionBody(source, "DeletePaperControl")
    expect(body).not.toMatch(/disabled/i)
  })

  it("renders only when the DTO carries a real attempt id, never a disabled stand-in", () => {
    expect(source).toContain("res.attemptId ? (")
    expect(source).toContain("<DeletePaperControl")
  })

  it("waits for the mutation before navigating, rather than firing both at once", () => {
    const body = functionBody(source, "handleConfirm")
    const awaitIndex = body.indexOf("await deletePaper.mutateAsync")
    const navigateIndex = body.indexOf("navigate(")
    expect(awaitIndex).toBeGreaterThan(-1)
    expect(navigateIndex).toBeGreaterThan(awaitIndex)
  })

  it("renders the refusal through deletionRefusal, reading the flat body not just .detail", () => {
    // Task 14 review, Critical 1: the backend's 409 is a flat body
    // (`{"detail": "...", "deletableFrom": "..."}`), so `deletableFrom` is a
    // sibling of `detail`, not nested in it — reading `err.detail` alone
    // (as an earlier version of this file did, cast with `as`) loses it.
    expect(source).toContain("deletionRefusal(err.body")
    expect(source).not.toMatch(/deletionRefusal\(err\.detail/)
  })

  it("narrows err.body through a real type guard, never an `as` cast", () => {
    expect(source).toContain("isDeletionRefusal(err.body)")
    expect(source).not.toMatch(/err\.detail\s+as\s+DeletionRefusal/)
  })
})

describe("RecentlyDeleted.tsx — real data, not a mock shape", () => {
  const source = readSource("src/portals/student/screens/RecentlyDeleted.tsx")

  it("reads from the real deletion hooks", () => {
    expect(source).toContain("useDeletedPapers()")
    expect(source).toContain("useRestorePaper()")
  })

  it("renders an explicit empty state rather than an empty list with nothing said", () => {
    expect(source).toContain("data.papers.length === 0")
    expect(source).toContain("<EmptyState")
  })

  it("counts down with the shared pure helper, not a re-derived one", () => {
    expect(source).toContain("deleteCountdown(")
  })

  it("never uses the word 'review' anywhere on this student-facing screen", () => {
    expect(source).not.toMatch(/review/i)
  })
})

describe("student route table — Recently Deleted is reachable", () => {
  const source = readSource("src/portals/student/index.tsx")

  it("mounts the route", () => {
    expect(source).toContain('path: "recently-deleted"')
    expect(source).toContain("<RecentlyDeleted />")
  })
})

describe("student/data.ts — nav and breadcrumb agree with the route", () => {
  const source = readSource("src/portals/student/data.ts")

  it("has a nav entry pointing at the route", () => {
    expect(source).toContain('"/student/recently-deleted"')
  })

  it("has a breadcrumb entry for the route", () => {
    expect(source).toContain('"/student/recently-deleted": "Home / Recently deleted"')
  })
})

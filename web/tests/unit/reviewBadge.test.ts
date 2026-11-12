import { readFileSync } from "node:fs"
import { join } from "node:path"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"
import { stripComments } from "./support/jsxSource"

/*
 * Task 9 (C3d) · review-queue count badge on the teacher sidebar's "Review"
 * item and the bottom-nav Review tab, both reading `useReviewQueueCount`.
 * Source-text checks (not render tests) because both nav sites live inside
 * `TeacherLayout`/`TeacherNav`, which pull in the full teacher shell (react-
 * router routes, react-query providers, every lazy screen) — the same
 * reason `navShells.test.ts` inspects `index.tsx`'s stripped source rather
 * than mounting the portal.
 */

const SRC = fileURLToPath(new URL("../../src/", import.meta.url))

function read(relPath: string): string {
  return readFileSync(join(SRC, relPath), "utf8")
}

describe("both teacher nav sites wire the review-queue badge", () => {
  const source = stripComments(read("portals/teacher/index.tsx"))

  it("imports useReviewQueueCount", () => {
    expect(source).toMatch(
      /import\s*\{[^}]*\buseReviewQueueCount\b[^}]*\}\s*from\s*"@\/lib\/hooks\/useReviewQueueCount"/,
    )
  })

  it("the sidebar's toNavShellItem call site resolves a badge for the review-queue marker", () => {
    expect(source).toMatch(/item\.badge\s*===\s*"review-queue"/)
  })

  it("the BottomNav items array passes a badge for the review tab", () => {
    // `tab.id === "review"` gates the bottom-nav badge onto the one tab it
    // belongs to, alongside a `badge:` key in the same NavShellItem literal.
    expect(source).toMatch(/tab\.id\s*===\s*"review"/)
    expect(source).toMatch(/badge:/)
  })

  it("no longer says Review carries no badge", () => {
    // The pre-Task-9 comment this replaced ("Review carries no badge: no
    // client-side count of the review queue's depth exists…") must be gone,
    // not just superseded in spirit.
    expect(read("portals/teacher/index.tsx")).not.toContain("Review carries no badge")
  })
})

describe("useReviewQueueCount.ts", () => {
  const source = stripComments(read("lib/hooks/useReviewQueueCount.ts"))

  it("fetches with limit: 1 — the badge never pulls a full page of items", () => {
    expect(source).toMatch(/limit:\s*1\b/)
  })

  it("is built on useReviewQueue, so it shares that hook's query-key prefix", () => {
    // `useReviewQueue`'s own queryKey starts `["teacher", "review", "queue",
    // ...]` — calling the hook itself (rather than hand-rolling a fetch)
    // guarantees this can never drift from that prefix.
    expect(source).toMatch(/import\s*\{[^}]*\buseReviewQueue\b[^}]*\}\s*from\s*"\.\/useTeacherApi"/)
    expect(source).toMatch(/useReviewQueue\(/)
  })

  it("returns null while loading or on error", () => {
    expect(source).toMatch(/isPending/)
    expect(source).toMatch(/isError/)
    expect(source).toMatch(/return null/)
  })
})

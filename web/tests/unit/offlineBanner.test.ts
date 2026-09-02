import { describe, expect, it } from "vitest"
import fs from "node:fs"
import path from "node:path"
import { stripComments } from "./support/jsxSource"

/*
 * PR 2 part C · every portal layout renders `<OfflineBanner` inside its
 * `<main>`.
 *
 * Same shape as `outletBoundary.test.ts`'s gate for the same four layouts:
 * read as text (`stripComments` + `indexOf`), not by rendering, since this
 * suite runs under Node with no jsdom (`vitest.config.ts`, D3.20) and a
 * component tree cannot be mounted here. `stripComments` matters
 * specifically because the placement comment this PR adds at each call site
 * itself says "OfflineBanner" in prose — a naive substring search that
 * didn't strip comments first would already be satisfied by the comment
 * alone, with no real `<OfflineBanner` anywhere nearby.
 */

const ROOT = path.join(import.meta.dirname, "..", "..")

/** Same population `outletBoundary.test.ts` and `notFoundFallback.test.ts`
 * name for the identical reason — the four portals with real chrome worth
 * showing an offline banner over, kept in one list so a fifth portal layout
 * falls into this gate rather than out of it. */
const PORTAL_LAYOUTS = [
  "src/portals/student/index.tsx",
  "src/portals/teacher/index.tsx",
  "src/portals/parent/index.tsx",
  "src/portals/admin/index.tsx",
] as const

function sourceOf(relative: string): string {
  return fs.readFileSync(path.join(ROOT, relative), "utf8")
}

/**
 * True when `stripped` (already comment-stripped source) shows a genuine
 * `<main` opening tag containing an `<OfflineBanner` before its matching
 * `</main>` — not merely "both strings appear somewhere in the file",
 * which a banner rendered outside `<main>` (in the sidebar, say) would also
 * satisfy.
 */
function mainContainsOfflineBanner(stripped: string): boolean {
  const mainAt = stripped.indexOf("<main")
  if (mainAt === -1) return false
  const mainTagEnd = stripped.indexOf(">", mainAt)
  if (mainTagEnd === -1) return false

  const mainCloseAt = stripped.indexOf("</main>", mainTagEnd)
  if (mainCloseAt === -1) return false

  const bannerAt = stripped.indexOf("<OfflineBanner", mainTagEnd)
  if (bannerAt === -1) return false

  return bannerAt < mainCloseAt
}

describe("every portal layout renders <OfflineBanner /> inside its <main> — PR 2 part C", () => {
  it.each(PORTAL_LAYOUTS)("%s renders <OfflineBanner inside <main>", (relative) => {
    const stripped = stripComments(sourceOf(relative))

    expect(stripped, `${relative} has no <main> element`).toContain("<main")
    expect(
      mainContainsOfflineBanner(stripped),
      `${relative} does not render <OfflineBanner inside its <main>...</main>`,
    ).toBe(true)
  })
})

describe("mainContainsOfflineBanner — the detector itself, on literals (not real files)", () => {
  it("passes the genuine shape", () => {
    const wrapped = stripComments(`
      <main id="x">
        <OfflineBanner onRetry={() => {}} />
        <Suspense><Outlet /></Suspense>
      </main>
    `)
    expect(mainContainsOfflineBanner(wrapped)).toBe(true)
  })

  it("fails when OfflineBanner sits outside main entirely", () => {
    const outside = stripComments(`
      <OfflineBanner onRetry={() => {}} />
      <main id="x">
        <Suspense><Outlet /></Suspense>
      </main>
    `)
    expect(mainContainsOfflineBanner(outside)).toBe(false)
  })

  it("fails when main has no OfflineBanner at all", () => {
    const missing = stripComments(`
      <main id="x">
        <Suspense><Outlet /></Suspense>
      </main>
    `)
    expect(mainContainsOfflineBanner(missing)).toBe(false)
  })
})

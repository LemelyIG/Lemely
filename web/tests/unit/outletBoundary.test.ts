import { describe, expect, it } from "vitest"
import fs from "node:fs"
import path from "node:path"
import { stripComments } from "./support/jsxSource"

/*
 * PR 1B (part B, client error reporting) · every portal's `<Outlet/>` sits
 * inside an `<ErrorBoundary resetKey={...}>`, pinned.
 *
 * `error-boundary.tsx` existed since an earlier phase and was placed
 * nowhere — `routes.tsx` carried the note "Phase 4 places those as it
 * rebuilds each surface" for that whole time, and nothing ever checked that
 * the promise was kept. That is the exact shape `hallmarkStamp.test.ts`
 * documents for the stamp convention: a rule with no reader is a rule that
 * silently stops applying. A future refactor of any one portal layout could
 * drop the boundary — accidentally, or "just for this one screen, I'll add
 * it back later" — and nothing but this test would notice, the same way
 * nothing noticed the boundary being unplaced at all for four phases.
 *
 * Read as text (`stripComments` + `indexOf`), not by rendering: this repo's
 * unit suite runs under Node with no jsdom (`vitest.config.ts`, D3.20), so a
 * component tree, `useLocation()`, or a caught error cannot be produced
 * here. `stripComments` (the same lexer `notFoundFallback.test.ts`'s sibling
 * gates and `hallmarkStamp.test.ts` use) matters specifically because two of
 * these four files mention `<Outlet />` inside a comment as well as in real
 * JSX — student's module docstring ("wrap an <Outlet/>") and admin's own
 * inline note ("the layout `<Outlet />` renders every child of this array
 * into") — and a naive substring search would count either as satisfying
 * the assertion below without a real `<ErrorBoundary>` anywhere near it.
 */

const ROOT = path.join(import.meta.dirname, "..", "..")

/**
 * The four portals that own real chrome (a sidebar, a header, or both) worth
 * keeping painted around a crashed screen. Same population `notFoundFallback
 * .test.ts`'s `PORTALS` list names for the identical reason — a list that
 * only grows by hand is a list new work falls out of, so if a fifth portal
 * layout is ever added, it belongs here as much as in that file.
 */
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
 * True when `stripped` (already comment-stripped source) shows its first
 * `<Outlet` genuinely *contained* by an `<ErrorBoundary resetKey={...}>` —
 * not merely "an ErrorBoundary open tag appears somewhere before it, and a
 * close tag appears somewhere after it", which a decoy boundary wrapping
 * unrelated markup would also satisfy: e.g.
 * `<ErrorBoundary resetKey={x}><span/></ErrorBoundary><Outlet />`, followed
 * anywhere later by any stray `</ErrorBoundary>`, reads as "open tag
 * before, close tag after" without the Outlet being inside anything.
 *
 * Containment is checked two ways:
 *  - nothing but whitespace sits between the nearest preceding boundary's
 *    opening tag's `>` and `<Outlet` itself (a decoy's `<span/>` and its
 *    own `</ErrorBoundary>` would land here as non-whitespace content);
 *  - the first `</ErrorBoundary>` found after the Outlet must close *this*
 *    boundary, not some later, unrelated one — so no other
 *    `<ErrorBoundary` open tag may appear first.
 */
function outletIsWrapped(stripped: string): boolean {
  const outletAt = stripped.indexOf("<Outlet")
  if (outletAt === -1) return false

  // The *nearest* ErrorBoundary opening tag before the Outlet, not merely
  // "ErrorBoundary appears somewhere in this file" — a boundary placed
  // around something unrelated (a chart, a sidebar widget) would satisfy
  // a bare `toContain` and prove nothing about the Outlet itself.
  const beforeOutlet = stripped.slice(0, outletAt)
  const boundaryOpenAt = beforeOutlet.lastIndexOf("<ErrorBoundary")
  if (boundaryOpenAt === -1) return false

  const boundaryTagEnd = stripped.indexOf(">", boundaryOpenAt)
  if (boundaryTagEnd === -1) return false
  const boundaryOpenTag = stripped.slice(boundaryOpenAt, boundaryTagEnd + 1)
  if (!boundaryOpenTag.includes("resetKey")) return false

  const between = stripped.slice(boundaryTagEnd + 1, outletAt)
  if (!/^\s*$/.test(between)) return false

  const closeAfterOutlet = stripped.indexOf("</ErrorBoundary>", outletAt)
  if (closeAfterOutlet === -1) return false

  const nextOpenAfterOutlet = stripped.indexOf("<ErrorBoundary", outletAt)
  if (nextOpenAfterOutlet !== -1 && nextOpenAfterOutlet < closeAfterOutlet) return false

  return true
}

describe("every portal Outlet is wrapped by an ErrorBoundary with resetKey — PR 1B", () => {
  it.each(PORTAL_LAYOUTS)("%s wraps its <Outlet /> in <ErrorBoundary resetKey=...>", (relative) => {
    const stripped = stripComments(sourceOf(relative))

    expect(stripped, `${relative} has no <Outlet /> to wrap`).toContain("<Outlet")
    expect(
      outletIsWrapped(stripped),
      `${relative}'s <Outlet /> is not genuinely contained by an <ErrorBoundary resetKey={...}> — ` +
        "check for a decoy boundary wrapping something else, a missing resetKey, or a close tag " +
        "belonging to a different <ErrorBoundary>",
    ).toBe(true)
  })

  /*
   * `portals/marketing/index.tsx` is deliberately not in `PORTAL_LAYOUTS`
   * above. Its two `<Suspense>` boundaries each wrap a lazy *screen element*
   * directly (`MarketingLanding`, `DataHandling`) rather than a shared
   * layout's `<Outlet/>` — see the comment at that file's own Suspense
   * blocks. There is no chrome to keep painted around a crash (no sidebar,
   * no header shared across routes the way the four gated portals have one),
   * and it is the one portal a signed-out reader can land on directly, so
   * routing a crash there through the same reporting/reset machinery the
   * other four use would be solving a problem this page does not have.
   *
   * Asserted rather than merely omitted: this fails the moment marketing's
   * layout grows an `<Outlet/>` of its own without this file's author also
   * deciding, on purpose, whether it needs the same wrapping.
   */
  it("marketing has no layout Outlet, so it is excluded above rather than left unwrapped", () => {
    const stripped = stripComments(sourceOf("src/portals/marketing/index.tsx"))
    expect(stripped).not.toContain("<Outlet")
  })
})

describe("outletIsWrapped — the detector itself, on literals (not real files)", () => {
  /*
   * Mirrors how `queryStateGate.test.ts` tests its own detector functions
   * against string literals rather than real files: the point here is
   * `outletIsWrapped`'s own behaviour on three shapes, not any particular
   * portal layout. Each fixture is comment-stripped the same way real
   * source is before the detector ever sees it — none of these carry
   * comments, but running them through `stripComments` keeps the self-test
   * honest about exercising the exact function `it.each` above calls.
   */

  it("passes the genuinely wrapped shape", () => {
    const wrapped = stripComments(`
      <ErrorBoundary resetKey={location.pathname}>
        <Outlet />
      </ErrorBoundary>
    `)
    expect(outletIsWrapped(wrapped)).toBe(true)
  })

  it("fails the decoy shape — a boundary wrapping unrelated markup, with a bare Outlet after it", () => {
    // The exact adversarial shape: an ErrorBoundary that opens, wraps a
    // <span/>, and closes — all before a bare <Outlet />, with a stray
    // </ErrorBoundary> further down. "An open tag before, a close tag
    // after" is true here; containment is not.
    const decoy = stripComments(`
      <ErrorBoundary resetKey={location.pathname}><span/></ErrorBoundary>
      <Outlet />
      </ErrorBoundary>
    `)
    expect(outletIsWrapped(decoy)).toBe(false)
  })

  it("fails the missing-resetKey shape", () => {
    const missingResetKey = stripComments(`
      <ErrorBoundary>
        <Outlet />
      </ErrorBoundary>
    `)
    expect(outletIsWrapped(missingResetKey)).toBe(false)
  })
})

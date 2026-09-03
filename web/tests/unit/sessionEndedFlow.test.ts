import { describe, expect, it } from "vitest"
import fs from "node:fs"
import path from "node:path"
import { stripComments } from "./support/jsxSource"

/*
 * SHOULD-FIX 3/4 + NIT (adversarial review, PR 2) · the rest of the
 * `/session-ended` fix that `requireAuth.test.ts` and `sessionExpiry.test.ts`
 * don't already cover: `FullPageState`'s `sign-in` action resolving through
 * `loginPathForRole`, `SessionEnded` consuming the expiry flag on mount and
 * handing the role down, and `routes.tsx` guarding the route against a
 * reader who already has a live session. Read as text, not rendered — same
 * reasoning as `requireAuth.test.ts`'s own header (D3.20, no DOM here).
 */

const ROOT = path.join(import.meta.dirname, "..", "..")

function sourceOf(relative: string): string {
  return fs.readFileSync(path.join(ROOT, relative), "utf8")
}

describe("FullPageState.tsx — sign-in resolves through loginPathForRole", () => {
  const stripped = stripComments(sourceOf("src/portals/misc/FullPageState.tsx"))

  it("imports loginPathForRole alongside portalPathForRole", () => {
    expect(stripped).toMatch(/import\s*\{[^}]*loginPathForRole[^}]*\}\s*from\s*"@\/lib\/auth\/RequireAuth"/)
  })

  it("resolves the sign-in target from the live session's role, then expiredRole, then the pending flag", () => {
    // The third fallback (`peekExpiredRole`) covers a caller that never
    // consumed the flag: a route-level 401 reaching `route-error.tsx`.
    expect(stripped).toContain(
      "loginPathForRole(session ? session.role : (expiredRole ?? peekExpiredRole()))",
    )
    expect(stripped).toMatch(/import\s*\{[^}]*peekExpiredRole[^}]*\}\s*from\s*"@\/lib\/auth\/storage"/)
  })

  it("appends ?next= to the resolved sign-in path through withNext, not a hand-built string", () => {
    expect(stripped).toContain("withNext(ctx.signIn, ctx.returnTo ?? null)")
    // The old hand-built `/login?next=${encodeURIComponent(...)}` shape must
    // be gone — a stray `?next=` template outside of `withNext` would be a
    // second, un-validated carrier next to the real one.
    expect(stripped).not.toMatch(/["'`]\?next=/)
  })

  it("FullPageStateProps carries expiredRole, and both components forward it", () => {
    expect(stripped).toContain("expiredRole?: string")
    expect(stripped).toContain("expiredRole={expiredRole}") // FullPageState -> FullPageStateBody
  })
})

describe("SessionEnded.tsx — consumes the expiry flag once, on mount", () => {
  const stripped = stripComments(sourceOf("src/portals/misc/SessionEnded.tsx"))

  it("reads the role via peekExpiredRole inside a useState initializer, before consuming", () => {
    // Order matters: `takeSessionExpired` clears the role together with the
    // boolean flag (`storage.ts`'s own doc comment), so the role must be
    // read first, in the same initializer, or it is already gone.
    expect(stripped).toMatch(
      /useState\(\(\)\s*=>\s*\{\s*const expiredRole = peekExpiredRole\(\)\s*takeSessionExpired\(\)\s*return expiredRole\s*\}\)/,
    )
  })

  it("passes the role it read down to FullPageState as expiredRole", () => {
    expect(stripped).toContain("expiredRole={role}")
  })

  it("still re-validates ?next= through safeNextPath, same as every other reader of it", () => {
    expect(stripped).toContain('safeNextPath(searchParams.get("next"))')
  })
})

describe("routes.tsx — /session-ended is guarded against a live session (NIT)", () => {
  const stripped = stripComments(sourceOf("src/routes.tsx"))

  it("wraps the /session-ended element in SessionEndedRoute", () => {
    const pathAt = stripped.indexOf('path: "/session-ended"')
    expect(pathAt).toBeGreaterThan(-1)
    const nextRouteAt = stripped.indexOf("path:", pathAt + 1)
    const block = stripped.slice(pathAt, nextRouteAt === -1 ? undefined : nextRouteAt)
    expect(block).toContain("<SessionEndedRoute>")
    expect(block).toContain("<SessionEnded")
  })

  it("SessionEndedRoute sends a signed-in reader to next, or their portal root, instead of rendering the screen", () => {
    const guardAt = stripped.indexOf("function SessionEndedRoute")
    expect(guardAt).toBeGreaterThan(-1)
    const guardBody = stripped.slice(guardAt, guardAt + 700)
    expect(guardBody).toContain("if (!session) return children")
    expect(guardBody).toContain('safeNextPath(searchParams.get("next"))')
    expect(guardBody).toContain("Navigate to={next ?? portalPathForRole(session.role)}")
  })
})

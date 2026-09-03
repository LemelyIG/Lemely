import { describe, expect, it } from "vitest"
import fs from "node:fs"
import path from "node:path"
import { stripComments } from "./support/jsxSource"
import { loginPathForRole } from "@/lib/auth/RequireAuth"

/*
 * Finding 14 (test coverage, adversarial review, PR 2) · `RequireAuth`'s
 * three-way redirect shape, and the two login screens' `?next=` handling,
 * pinned.
 *
 * `loginPathForRole` is a plain exported function, so it is called directly
 * below — no source-text gate needed for that half. `RequireAuth` itself is
 * a component that reads `useAuth()`/`useLocation()`, and this suite runs
 * under Node with no jsdom (`vitest.config.ts`, D3.20), so its render
 * branches are read as text instead (`stripComments` + `indexOf`/`toMatch`,
 * the same pattern `outletBoundary.test.ts` and `offlineBanner.test.ts`
 * use) rather than mounted with a router and an auth context stood up
 * around it.
 */

const ROOT = path.join(import.meta.dirname, "..", "..")

function sourceOf(relative: string): string {
  return fs.readFileSync(path.join(ROOT, relative), "utf8")
}

describe("loginPathForRole", () => {
  it("sends a parent to the phone OTP form — parents have no password (G-05)", () => {
    expect(loginPathForRole("parent")).toBe("/login/parent")
  })

  it.each(["student", "teacher", "school_admin", "platform_admin", "some-future-role"])(
    "sends every other role (%s) to the email+password form",
    (role) => {
      expect(loginPathForRole(role)).toBe("/login")
    },
  )

  it("defaults an unknown role to the email+password form — the one screen every role can always use", () => {
    expect(loginPathForRole(undefined)).toBe("/login")
  })
})

describe("RequireAuth.tsx — the three-way redirect shape (source-text gate, no DOM)", () => {
  const stripped = stripComments(sourceOf("src/lib/auth/RequireAuth.tsx"))

  it("redirects a dead (stranded, or flagged with no session) session to /session-ended via withNext", () => {
    expect(stripped).toContain('withNext("/session-ended", currentPath)')
  })

  it("redirects a missing session (no expiry) to /login via withNext", () => {
    expect(stripped).toContain('withNext("/login", currentPath)')
  })

  it("renders the standalone no-access screen for a wrong role, with no redirect", () => {
    expect(stripped).toContain('variant="no-access"')
    expect(stripped).toContain('frame="standalone"')
  })

  it("builds next exclusively through safeNextPath/withNext — no hand-built ?next= string", () => {
    // Every `?next=` this file produces goes through `withNext`'s own
    // `encodeURIComponent`, imported at the top of the file. A raw
    // `"?next="` literal anywhere in this component would be a second,
    // un-validated carrier sitting next to the real one — exactly the class
    // of bug `lib/nextPath.ts` exists to rule out everywhere it is used.
    expect(stripped).toContain('import { withNext } from "@/lib/nextPath"')
    expect(stripped).not.toMatch(/["'`]\?next=/)
    // Both redirect branches route through it — this also catches a future
    // edit that adds a third `<Navigate>` without carrying `next` along.
    expect((stripped.match(/withNext\(/g) ?? []).length).toBeGreaterThanOrEqual(2)
  })
})

describe("Login.tsx / ParentLogin.tsx — next is read only through safeNextPath", () => {
  it.each([
    ["src/portals/auth/Login.tsx", "Login"],
    ["src/portals/auth/ParentLogin.tsx", "ParentLogin"],
  ])("%s reads next through safeNextPath(searchParams.get(\"next\")), never a raw searchParams.get", (relative) => {
    const stripped = stripComments(sourceOf(relative))

    expect(stripped).toContain('safeNextPath(searchParams.get("next"))')

    // Never handed a raw, un-validated `searchParams.get("next")` straight
    // to `navigate()` or a JSX `to=`/`href=` prop — every use of `next` past
    // this point in either file must be the already-validated local
    // binding, not a second, un-sanitised read of the same query param.
    expect(stripped).not.toMatch(/navigate\(\s*searchParams\.get\("next"\)/)
    expect(stripped).not.toMatch(/\bto=\{?\s*searchParams\.get\("next"\)/)
  })

  it("Login.tsx's success handler prefers next over the role-derived portal home", () => {
    const stripped = stripComments(sourceOf("src/portals/auth/Login.tsx"))
    expect(stripped).toContain("navigate(next ?? portalPathForRole(result.role)")
  })

  it("ParentLogin.tsx's verify success handler prefers next over the role-derived portal home", () => {
    const stripped = stripComments(sourceOf("src/portals/auth/ParentLogin.tsx"))
    expect(stripped).toContain("navigate(next ?? portalPathForRole(result.role)")
  })
})

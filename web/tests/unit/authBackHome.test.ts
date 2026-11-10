import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"
import { stripComments } from "./support/jsxSource"

/*
 * Source-text pins (no jsdom, D3.20). Every signed-out auth screen renders
 * inside `AuthFrame`, so the way back to "/" lives there once: a "Back to home"
 * link plus a wordmark that links home. Behaviour is covered by
 * e2e/auth-back-home.spec.ts.
 */
const read = (p: string) => stripComments(readFileSync(join(process.cwd(), p), "utf8"))

describe("AuthFrame back affordance", () => {
  const login = read("src/portals/auth/Login.tsx")
  const frame = login.slice(login.indexOf("export function AuthFrame"), login.indexOf("const LINK_CLASS"))

  it("links the wordmark and a text link to the landing page", () => {
    expect(frame).toMatch(/<Link\s+to="\/"[\s\S]*?data-testid="auth-back-home"/)
    expect(frame).toMatch(/<Link\s+to="\/"[\s\S]*?aria-label="Lemely, go to the home page"[\s\S]*?<BrandLockup/)
    expect(frame).toContain("Back to home")
  })

  it("keeps a visible keyboard focus ring and a 44px target on the back link", () => {
    expect(frame).toMatch(/min-h-11[^"]*focus-visible:outline-2/)
  })

  it("is the frame every auth screen uses", () => {
    for (const f of ["SignupRoleSelect", "SignupDetails", "SignupParent", "VerifyEmail", "PasswordReset", "JoinWithCode"]) {
      expect(read(`src/portals/auth/${f}.tsx`)).toContain("<AuthFrame")
    }
  })
})

describe("handwriting face", () => {
  it("is self-hosted and scoped to the marketing tokens, with marks left in the UI face", () => {
    const tokens = readFileSync(join(process.cwd(), "src/portals/marketing/brand-tokens.css"), "utf8")
    expect(tokens).toMatch(/@import '@fontsource-variable\/caveat'/)
    expect(tokens).toMatch(/--brand-hand: 'Caveat Variable'/)
    expect(JSON.parse(readFileSync(join(process.cwd(), "package.json"), "utf8")).dependencies).toHaveProperty("@fontsource-variable/caveat")
    const motion = readFileSync(join(process.cwd(), "src/portals/marketing/walkthrough-motion.css"), "utf8")
    expect(motion).toMatch(/\.wt-mark\s*\{[^}]*var\(--brand-body\)/)
    expect(motion).toMatch(/\.wt-write\s*\{[^}]*var\(--brand-hand\)/)
  })
})

import { describe, expect, it } from "vitest"

import {
  buildSignupPayload,
  passwordStrength,
  validateSignupFields,
  type SignupFormValues,
} from "@/portals/auth/signupDetailsLogic"
import type { SelfServiceRole } from "@/lib/auth/AuthContext"

/*
 * Task 15 (G-03) · the payload builder, pinned directly.
 *
 * `vitest.config.ts` runs the node environment on purpose (D3.20) — no
 * jsdom, no renderer, nothing that could mount `SignupDetails` itself. What
 * IS reachable here is the decision the screen makes before it ever talks to
 * the network, which lives in the sibling module `signupDetailsLogic.ts`
 * rather than in `SignupDetails.tsx` itself — that split (mirroring
 * `onboardingData.ts`/`onboarding.test.ts` and Task 16's
 * `verifyEmailLogic.ts`/`verifyEmail.test.ts`) is what lets a component file
 * export nothing but its component (satisfying `oxlint`'s
 * `react/only-export-components`) while `buildSignupPayload`/
 * `validateSignupFields`/`passwordStrength` stay real, exported, pure
 * functions — the same shape `studentOnboardingRedirect`
 * (`portals/student/index.tsx`) and `teacherFirstClassRedirect`
 * (`portals/teacher/index.tsx`) already use for exactly this reason.
 *
 * The two behaviours this task names explicitly get the most scrutiny:
 * consent unticked must never produce a submittable payload (D7.11), and
 * `role` must survive into the payload exactly as given, for both
 * self-service roles, with no hardcoding. That second one is not a
 * hypothetical regression — `AuthContext.tsx`'s own module comment records
 * that `signup` "currently hardcodes role: 'student'" before Task 13 fixed
 * it, so a `SignupDetails` that repeated the mistake at its own layer would
 * be a real bug, not a theoretical one, and it would pass any test that only
 * ever exercises the student variant.
 */

const SELF_SERVICE_ROLES: readonly SelfServiceRole[] = ["student", "teacher"]

const VALID_FIELDS: SignupFormValues = {
  name: "Amina Farouk",
  email: "amina@example.com",
  password: "correct horse battery staple",
  acceptedTerms: true,
}

describe("buildSignupPayload", () => {
  it("refuses to build a payload when consent is unticked (D7.11)", () => {
    // The one assertion this task names by name. Every other field is
    // otherwise perfectly valid, so a regression where the checkbox renders
    // but nothing actually gates submission on it is exactly what this
    // catches — and nothing else in this file would.
    for (const role of SELF_SERVICE_ROLES) {
      expect(buildSignupPayload(role, { ...VALID_FIELDS, acceptedTerms: false })).toBeNull()
    }
  })

  it("builds a real payload once every field is valid and consent is ticked", () => {
    const payload = buildSignupPayload("student", VALID_FIELDS)
    expect(payload).not.toBeNull()
    expect(payload?.acceptedTerms).toBe(true)
    expect(payload?.email).toBe(VALID_FIELDS.email)
    expect(payload?.password).toBe(VALID_FIELDS.password)
  })

  it("carries role through exactly as given, for both self-service roles", () => {
    // The regression this guards against: a SignupDetails that ignores its
    // own `role` prop and always submits one role regardless of which
    // variant is actually rendered. See the module docstring above.
    for (const role of SELF_SERVICE_ROLES) {
      const payload = buildSignupPayload(role, VALID_FIELDS)
      expect(payload?.role).toBe(role)
    }
  })

  it("never produces a role outside student or teacher", () => {
    for (const role of SELF_SERVICE_ROLES) {
      const payload = buildSignupPayload(role, VALID_FIELDS)
      expect(payload).not.toBeNull()
      expect(["student", "teacher"]).toContain(payload?.role)
    }
  })

  it("trims the name into displayName and trims the email, leaving the password untouched", () => {
    const payload = buildSignupPayload("teacher", {
      ...VALID_FIELDS,
      name: "  Amina Farouk  ",
      email: "  amina@example.com  ",
      password: "  correct horse battery staple  ",
    })
    expect(payload?.displayName).toBe("Amina Farouk")
    expect(payload?.email).toBe("amina@example.com")
    // A password's leading/trailing spaces are part of the credential, not
    // formatting noise — trimming them would silently change what the
    // visitor typed into what they have to type back in to sign in again.
    expect(payload?.password).toBe("  correct horse battery staple  ")
  })

  it("refuses a blank or whitespace-only name", () => {
    expect(buildSignupPayload("student", { ...VALID_FIELDS, name: "" })).toBeNull()
    expect(buildSignupPayload("student", { ...VALID_FIELDS, name: "   " })).toBeNull()
  })

  it("refuses a malformed email", () => {
    expect(buildSignupPayload("teacher", { ...VALID_FIELDS, email: "not-an-email" })).toBeNull()
    expect(buildSignupPayload("teacher", { ...VALID_FIELDS, email: "" })).toBeNull()
  })

  it("refuses a password under the screen's own floor", () => {
    expect(buildSignupPayload("teacher", { ...VALID_FIELDS, password: "short" })).toBeNull()
    expect(buildSignupPayload("teacher", { ...VALID_FIELDS, password: "" })).toBeNull()
  })

  it("refuses when every problem is present at once, not just the first one checked", () => {
    expect(
      buildSignupPayload("student", {
        name: "",
        email: "nope",
        password: "x",
        acceptedTerms: false,
      }),
    ).toBeNull()
  })
})

describe("validateSignupFields", () => {
  it("reports no errors for a fully valid set of fields", () => {
    expect(validateSignupFields(VALID_FIELDS)).toEqual({})
  })

  it("keys each error to its own field, independently of the others", () => {
    const errors = validateSignupFields({
      name: "",
      email: "nope",
      password: "x",
      acceptedTerms: true,
    })
    expect(errors.name).toBeTruthy()
    expect(errors.email).toBeTruthy()
    expect(errors.password).toBeTruthy()
  })

  it("does not flag a field that is already valid", () => {
    const errors = validateSignupFields({ ...VALID_FIELDS, email: "" })
    expect(errors.email).toBeTruthy()
    expect(errors.name).toBeUndefined()
    expect(errors.password).toBeUndefined()
  })
})

describe("passwordStrength", () => {
  it("scores anything under the length floor as 0, regardless of character variety", () => {
    // "Ab1!" mixes all four character classes and would score high on
    // variety alone — the length floor must win regardless, so this never
    // reads as partial credit for a password `validateSignupFields` would
    // reject outright.
    expect(passwordStrength("").score).toBe(0)
    expect(passwordStrength("Ab1!").score).toBe(0)
    expect(passwordStrength("Ab1!").label).toBe("Too short")
  })

  it("scores a long, single-character-class password as weak", () => {
    expect(passwordStrength("abcdefghijkl").label).toBe("Weak")
  })

  it("scores higher for more character variety at the same length", () => {
    const weak = passwordStrength("abcdefghijkl")
    const fair = passwordStrength("abcdefgh1234")
    expect(fair.score).toBeGreaterThan(weak.score)
  })

  it("scores a long password mixing all four character classes as strong", () => {
    const strong = passwordStrength("Correct1Horse!Battery")
    expect(strong.label).toBe("Strong")
    expect(strong.score).toBe(4)
  })
})

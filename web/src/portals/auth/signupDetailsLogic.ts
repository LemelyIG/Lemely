/*
 * Pure logic for G-03 (`SignupDetails.tsx`). No React, no DOM — the same
 * split `onboardingData.ts` uses for the S-01/S-02 wizard, and for the same
 * reason: `vitest.config.ts` runs the unit suite in a Node environment with
 * no jsdom/@testing-library (D3.20), so this is what `signup.test.ts`
 * exercises directly, and it is also the house fix for `oxlint`'s
 * `react/only-export-components` (`.oxlintrc.json`) — a file that exports a
 * component may not also export plain functions/constants without warning,
 * and the fix the warning itself names is exactly this: a second, non-
 * component module. `verifyEmailLogic.ts` (Task 16, G-07 — the screen this
 * one hands off to on success) lands the identical split; component
 * behaviour beyond these decisions is Playwright's job (Task 23), not this
 * file's.
 */

import type { SelfServiceRole, SignupVariables } from "@/lib/auth/AuthContext"

/**
 * The frontend's own floor, not a mirrored backend rule — grepping
 * `lemely/web/schemas_auth.py` and `lemely/auth/gotrue.py` turns up no
 * documented minimum length for a self-service password anywhere in this
 * repository, so there is nothing here to stay consistent with. Eight is a
 * plain, defensible default (NIST 800-63B's own floor) chosen for this
 * screen alone; the true source of truth remains whatever GoTrue itself
 * enforces on `admin_create_user`.
 */
export const MIN_PASSWORD_LENGTH = 8

/** Loose but sufficient for a client-side hint. The server is the real
 * validator; this only stops an obviously-malformed address reaching it. */
const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

export interface SignupFormValues {
  name: string
  email: string
  password: string
  acceptedTerms: boolean
}

export interface SignupFieldErrors {
  name?: string
  email?: string
  password?: string
}

/**
 * One field's error, or none. Called from each field's own `onBlur` in
 * `SignupDetails.tsx` (binding requirement 2: validation on blur, never on
 * every keystroke) and, once more, from `buildSignupPayload` at submit time
 * so a submit with no blurred field yet still reports every problem instead
 * of silently doing nothing.
 */
export function validateSignupFields(values: SignupFormValues): SignupFieldErrors {
  const errors: SignupFieldErrors = {}

  if (values.name.trim().length === 0) {
    errors.name = "Enter your name."
  }

  const email = values.email.trim()
  if (email.length === 0) {
    errors.email = "Enter your email address."
  } else if (!EMAIL_PATTERN.test(email)) {
    errors.email = "Enter a valid email address."
  }

  if (values.password.length === 0) {
    errors.password = "Enter a password."
  } else if (values.password.length < MIN_PASSWORD_LENGTH) {
    errors.password = `Use at least ${MIN_PASSWORD_LENGTH} characters.`
  }

  return errors
}

export type PasswordStrengthLabel = "Weak" | "Fair" | "Good" | "Strong"

export interface PasswordStrength {
  /** 0 (below the floor) to 4 (every character class, and long). Drives how
   * many of the four meter segments `SignupDetails.tsx` renders filled. */
  score: number
  label: PasswordStrengthLabel | "Too short"
}

function characterClassCount(password: string): number {
  let classes = 0
  if (/[a-z]/.test(password)) classes += 1
  if (/[A-Z]/.test(password)) classes += 1
  if (/[0-9]/.test(password)) classes += 1
  if (/[^A-Za-z0-9]/.test(password)) classes += 1
  return classes
}

/**
 * Live strength feedback (§G-03's "with strength feedback"), continuous
 * rather than deferred to blur. This is a different mechanism from binding
 * requirement 2's error validation, not an exception to it: nothing here is
 * a pass/fail judgement or an error message, only affirmative, always-
 * updating guidance while the visitor is still composing the value, the same
 * way a live character counter is not "validation on every keystroke" in the
 * sense that rule is about. The hard floor (`validateSignupFields`) still
 * only ever fires on blur.
 *
 * Below `MIN_PASSWORD_LENGTH`, score is always 0 regardless of character
 * variety — length is the gate `validateSignupFields` itself enforces first,
 * so a short-but-varied password reading as partially "strong" here would
 * contradict the field error sitting right below it once the visitor blurs.
 */
export function passwordStrength(password: string): PasswordStrength {
  if (password.length < MIN_PASSWORD_LENGTH) return { score: 0, label: "Too short" }
  const classes = characterClassCount(password)
  const long = password.length >= 12
  if (classes <= 1) return { score: 1, label: "Weak" }
  if (classes === 2) return long ? { score: 3, label: "Good" } : { score: 2, label: "Fair" }
  return long ? { score: 4, label: "Strong" } : { score: 3, label: "Good" }
}

/** Tone-to-class mapping for the meter's four segments. The tone ladder
 * matches DESIGN.md §3.6's descending err/warn/ok relative luminance, so the
 * meter stays readable in greyscale, not only by hue. */
export function strengthFillClass(score: number): string {
  if (score <= 1) return "bg-err"
  if (score === 2) return "bg-warn"
  return "bg-ok"
}

/**
 * The one function `web/tests/unit/signup.test.ts` exists to pin (task
 * instruction: "Unit-test the payload builder: consent unticked never
 * submits, and role is only ever student or teacher").
 *
 * Returns `null` — never a payload with a false claim in it — whenever the
 * form is not ready to submit: consent unticked (binding requirement 3), or
 * any field `validateSignupFields` would reject. `role` is typed
 * `SelfServiceRole` (`AuthContext.tsx`), the same narrowed type
 * `AuthContext.signup` itself requires, so a value outside `"student" |
 * "teacher"` cannot reach this function's return at all — belt — and the
 * server independently 403s anything else via `_SELF_SERVICE_SIGNUP_ROLES`
 * (`lemely/web/routers/auth.py`) — suspenders. The concrete regression this
 * guards against already happened once: `AuthContext.tsx`'s own module
 * comment records that `signup` "currently hardcodes role: 'student'" before
 * Task 13 fixed it. A `SignupDetails` that repeated that mistake at its own
 * layer — ignoring its own `role` prop and always building a student
 * payload — would pass every other check in this file and only this
 * function's own test catches it.
 */
export function buildSignupPayload(
  role: SelfServiceRole,
  values: SignupFormValues,
): SignupVariables | null {
  if (!values.acceptedTerms) return null
  if (Object.keys(validateSignupFields(values)).length > 0) return null
  return {
    email: values.email.trim(),
    password: values.password,
    role,
    acceptedTerms: true,
    displayName: values.name.trim(),
  }
}

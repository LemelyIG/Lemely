/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import { useState, type FormEvent } from "react"
import { Link, useNavigate, useSearchParams } from "react-router-dom"
import { Eye, EyeSlash } from "@phosphor-icons/react"
import { useAuth, type SelfServiceRole } from "@/lib/auth/AuthContext"
import { useRedeemInvite } from "@/lib/hooks/useInvitesApi"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Checkbox } from "@/components/ui/checkbox"
import { ApiError } from "@/lib/api"
import { signUpFailureMessage } from "@/lib/authOutcome"
import { cn } from "@/lib/utils"
import { AuthFrame } from "./Login"
import {
  MIN_PASSWORD_LENGTH,
  buildSignupPayload,
  passwordStrength,
  strengthFillClass,
  validateSignupFields,
  type SignupFieldErrors,
  type SignupFormValues,
} from "./signupDetailsLogic"

/*
 * G-03 · Sign up details, student and teacher variants (Task 15; UI spec
 * §G-03; design spec §4.4; decisions D7.1, D7.2, D7.11).
 *
 * One component for both variants. `role` is a prop, not something this file
 * parses out of the URL itself: design spec §4.4 fixes `/signup/student` and
 * `/signup/teacher` as two separate static paths, not one route with a
 * `:role` segment, so whichever of the two Task 19 mounts this element on is
 * already the single source of truth for which variant is which
 * (`<SignupDetails role="student" />` / `<SignupDetails role="teacher" />`,
 * the same "same element, two RouteObjects" shape `/login` and
 * `/login/parent` already use, and that `VerifyEmail.tsx`'s own docstring
 * names as the pattern for `/verify-email` vs `/verify-email/:token`).
 *
 * ── Binding requirement 1 — no school field on the teacher variant (D7.2) ──
 *
 * UI spec §G-03 lists, for the teacher variant, an optional "school or centre
 * name (optional, with 'I work independently' option)". It is deliberately
 * ABSENT here, and this paragraph is that "next reader" warning: if you are
 * here to restore it, don't, read D7.2 first.
 *
 * D7.2: "A self-registered teacher is always independent." `SchoolClass.
 * school_id` is already nullable for exactly this case (D3.1) — a teacher
 * with no school is a normal, supported state, not a gap to fill in on this
 * form. A school is a commercial artefact: it carries a seat quota, seats and
 * memberships (spec §1.1), and letting an anonymous visitor mint one by
 * typing a name into a signup field would produce a School with a quota of
 * zero, unusable until a platform admin intervened anyway — worse than not
 * creating one at all. Membership arrives later, by invite (G-08's `/join`,
 * which hands a signed-out visitor to this exact screen with the code
 * retained — see the invite section below), never by this field. The banner
 * rendered below for a code-less teacher visit says as much in plain
 * language, so a teacher who actually wants a school seat has a chance of
 * finding that door instead of assuming this is the only one.
 *
 * ── Binding requirement 2 — validation on blur, not on keystroke (§G-03) ───
 *
 * `validateSignupFields` (`signupDetailsLogic.ts`) runs from each field's
 * `onBlur`, never `onChange`. `onChange` only clears that one field's
 * *existing* error, so a message computed against the previous value does
 * not linger, unexplained, while the visitor is actively retyping it — that
 * is housekeeping on the display, not a second validation pass keyed to a
 * keystroke; the value itself is re-validated only on the next blur (or on
 * submit, which validates every field at once so a submit with no blurred
 * field yet still explains itself rather than failing silently).
 *
 * ── Binding requirement 3 — consent to /data, recorded (D7.11) ─────────────
 *
 * The checkbox links to `/data`, the page that genuinely describes what
 * happens to a scan (`DataHandling.tsx`) — never a terms-of-service document,
 * because this repository has none and PRODUCT.md's "Absent — must not be
 * fabricated" list names exactly that. Unticked, `buildSignupPayload` returns
 * `null` and nothing is submitted (pinned in `tests/unit/signup.test.ts`).
 * Ticked, the request carries `acceptedTerms: true`, which the server
 * requires with no default (`SignupRequestDTO.acceptedTerms`,
 * `lemely/web/schemas_auth.py`: "an absent field is a pydantic 422 ...
 * never a silently assumed False") — so this box is not decorative on either
 * end of the wire.
 *
 * ── Binding requirement 4 — the already-registered case ────────────────────
 *
 * `signUpFailureMessage` (`lib/authOutcome.ts`) is rendered here verbatim,
 * unmodified, with a `/login` link added alongside it. That function
 * deliberately does not say whether the address is already held — spec
 * §4.3's own anti-enumeration rule, mirroring `signInFailureMessage` — and
 * this screen must never strengthen that claim: no echoing the typed address
 * back next to it, no wording that would let a visitor distinguish "already
 * registered" from any other rejected signup. The link is offered
 * unconditionally alongside the same sentence every 400 produces, not
 * because this screen knows the address exists, but because the sentence
 * itself already invites that reading ("If you already have one, sign in
 * instead") and a 400 is the one status class that sentence was written for.
 *
 * ── Binding requirement 5 — the invite code, retained and redeemed ─────────
 *
 * G-08's own line: "If the person has no account yet, this flows into G-03
 * with the code retained." `JoinWithCode.tsx` (Task 18) confirms the split in
 * its own docstring: confirming while signed out is "a plain client-side
 * navigation to G-03 with the code carried in the query string
 * (`signupPathForInvite`), never a redeem call this screen makes itself" —
 * so redemption for a brand-new account is this file's job, not shared with
 * or duplicated by G-08.
 *
 * The code arrives as `?code=<code>` (read via `useSearchParams`, matching
 * `signupPathForInvite`'s own `` `/signup/${role}?code=${encodeURIComponent(code)}` ``
 * exactly — verified against that function's real implementation, not
 * assumed), because spec §4.4 fixes `/signup/student` and `/signup/teacher`
 * as two static paths with no segment to carry it, and this task does not
 * touch `routes.tsx`. It never becomes part of `SignupVariables` — the
 * Task 13 contract this file is instructed to code against has no field for
 * it, and `AuthService.signup` knows nothing about invites. Instead,
 * `useRedeemInvite()` (`lib/hooks/useInvitesApi.ts`, Task 18's own hook) is
 * called once, from `signup`'s `onSuccess`, after `AuthContext`'s own
 * `onSuccess` has already persisted the fresh session — `request()` reads
 * that session synchronously from storage, so the redeem call carries the
 * new account's bearer token with no extra wiring needed here.
 *
 * A failed redemption is swallowed rather than surfaced: by the time it runs,
 * `POST /auth/signup` has already succeeded and a real account exists. The
 * account this screen exists to create must not be held hostage to a second,
 * unrelated request — a seat that raced away between G-08's preview and this
 * moment costs the visitor a seat association, which is recoverable (ask the
 * school for a fresh code), not the account itself. Either way, submit routes
 * to `/verify-email`, per this task's own instruction, unconditionally.
 *
 * ── Frame ────────────────────────────────────────────────────────────────
 *
 * `AuthFrame` (`Login.tsx`) is reused, not copied — see its own docstring for
 * what a third copy of that markup already cost this codebase once.
 * `dataPortal={role}` is passed once `role` is known, the same way
 * `ParentLogin.tsx` passes `dataPortal="parent"`; `SignupRoleSelect.tsx`
 * (G-02, which precedes any known role) is the sibling screen that passes
 * none.
 *
 * ── Why the pure logic lives in `signupDetailsLogic.ts`, not here ──────────
 *
 * `oxlint`'s `react/only-export-components` (`.oxlintrc.json`) warns on a
 * file that exports a component alongside anything else, and "no new lint
 * warnings" is one of this task's binding gates. This task's own instruction
 * is equally explicit that the payload/validation logic must be "a pure
 * exported function" tested directly by `web/tests/unit/signup.test.ts` —
 * naming `studentOnboardingRedirect`/`teacherFirstClassRedirect` as the
 * pattern — so it cannot simply stay private the way it could if no test
 * required it. `onboardingData.ts` (the S-01/S-02 wizard) and
 * `verifyEmailLogic.ts` (Task 16, `VerifyEmail.tsx` — the very screen this
 * one hands off to) already resolve the identical conflict the identical
 * way: a second, sibling `.ts` module holding every pure function, so the
 * component file here exports nothing but the component itself and the rule
 * has nothing to warn about. `SignupDetailsProps` below is the one exception
 * kept in this file — a type-only export carries no runtime value for the
 * rule to flag (verified empirically, not assumed) and it documents this
 * component's own prop contract, which belongs beside the component that
 * takes it.
 */

export interface SignupDetailsProps {
  /** Which self-service account this screen creates (D7.1). Supplied by
   * whichever route rendered this component — see the module docstring for
   * why that is a prop and not something parsed from the URL here. */
  role: SelfServiceRole
}

const ROLE_COPY: Record<SelfServiceRole, { heading: string; subheading: string }> = {
  student: {
    heading: "Create your student account",
    subheading: "Upload a past paper and see exactly what to study next.",
  },
  teacher: {
    heading: "Create your teacher account",
    subheading: "Mark past papers faster, with partial credit worked out for you.",
  },
}

/** Matches `SignupRoleSelect.tsx`'s own link recipe exactly, so every link on
 * the signed-out signup surface looks and behaves like the same control. */
const LINK_CLASS =
  "rounded-sm text-accent-ink underline underline-offset-2 transition-colors hover:text-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"

export function SignupDetails({ role }: SignupDetailsProps) {
  const { signup } = useAuth()
  const redeemInvite = useRedeemInvite()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  // See the module docstring's invite section: `?code=`, matching
  // `signupPathForInvite` (`lib/hooks/useInvitesApi.ts`) exactly.
  const inviteCode = searchParams.get("code")

  const [values, setValues] = useState<SignupFormValues>({
    name: "",
    email: "",
    password: "",
    acceptedTerms: false,
  })
  const [fieldErrors, setFieldErrors] = useState<SignupFieldErrors>({})
  const [consentError, setConsentError] = useState(false)
  const [showPassword, setShowPassword] = useState(false)

  const busy = signup.isPending || redeemInvite.isPending
  const strength = passwordStrength(values.password)

  const updateField = (field: keyof SignupFieldErrors, value: string) => {
    setValues((previous) => ({ ...previous, [field]: value }))
    // Clears a stale message the moment the visitor edits the field again,
    // rather than leaving a blur-triggered error describing a value they
    // have already started changing. The value itself is re-checked only on
    // the next blur (binding requirement 2) — this only stops the display
    // from lying about the field's current state in the meantime.
    setFieldErrors((previous) => ({ ...previous, [field]: undefined }))
    if (signup.isError) signup.reset()
  }

  const handleBlur = (field: keyof SignupFieldErrors) => {
    setFieldErrors((previous) => ({ ...previous, [field]: validateSignupFields(values)[field] }))
  }

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const payload = buildSignupPayload(role, values)
    if (!payload) {
      // Reveals every field's error at once, not only the ones already
      // blurred — a visitor who reaches the button by autofill or by Enter,
      // never blurring a field by hand, still gets told what is wrong rather
      // than watching the submit silently do nothing.
      setFieldErrors(validateSignupFields(values))
      setConsentError(!values.acceptedTerms)
      return
    }
    setConsentError(false)
    signup.mutate(payload, {
      onSuccess: () => {
        const proceed = () => navigate("/verify-email", { replace: true })
        if (inviteCode) {
          redeemInvite.mutate({ code: inviteCode }, { onSuccess: proceed, onError: proceed })
        } else {
          proceed()
        }
      },
    })
  }

  const signupError = signup.error
  // Binding requirement 4: the login link is offered only for the 400 class
  // `signUpFailureMessage`'s own "sign in instead" wording is written for —
  // never for a network failure, a cooldown 429, or a 5xx, where "sign in
  // instead" is not the sentence being shown.
  const addressConflict = signupError instanceof ApiError && signupError.status === 400
  const copy = ROLE_COPY[role]

  return (
    <AuthFrame
      dataPortal={role}
      footer={
        <p className="text-body-sm text-ink-muted">
          Already have an account?{" "}
          <Link to="/login" className={LINK_CLASS}>
            Sign in
          </Link>
        </p>
      }
    >
      <form
        onSubmit={handleSubmit}
        noValidate
        className="flex w-full max-w-100 flex-col gap-5 rounded-lg border border-rule bg-paper-raised p-8"
      >
        <div className="flex flex-col gap-1.5">
          <h1 className="text-display-lg text-ink">{copy.heading}</h1>
          <p className="text-body-md text-ink-muted">{copy.subheading}</p>
        </div>

        {inviteCode ? (
          <p className="rounded-md border border-rule bg-paper-sunk px-3 py-2.5 text-body-sm text-ink-muted">
            Signing up with an invite code. We'll finish setting that up right after your account
            is created.
          </p>
        ) : role === "teacher" ? (
          /*
           * D7.2, restated for the person reading the SCREEN rather than the
           * code — see the module docstring's fuller version above. Shown
           * only when there is no invite code: a teacher arriving via one is
           * not the self-registering, independent case D7.2 describes, and
           * this sentence would be actively wrong for them.
           */
          <p className="rounded-md border border-rule bg-paper-sunk px-3 py-2.5 text-body-sm text-ink-muted">
            This creates an independent account, not tied to a school. If your school already
            uses Lemely, ask them for an invite link instead.
          </p>
        ) : null}

        <Input
          label="Name"
          autoComplete="name"
          required
          disabled={busy}
          value={values.name}
          onChange={(event) => updateField("name", event.target.value)}
          onBlur={() => handleBlur("name")}
          error={fieldErrors.name}
        />
        <Input
          label="Email"
          type="email"
          autoComplete="email"
          required
          disabled={busy}
          value={values.email}
          onChange={(event) => updateField("email", event.target.value)}
          onBlur={() => handleBlur("email")}
          error={fieldErrors.email}
        />

        <div className="flex flex-col gap-2">
          <Input
            label="Password"
            type={showPassword ? "text" : "password"}
            autoComplete="new-password"
            required
            disabled={busy}
            value={values.password}
            onChange={(event) => updateField("password", event.target.value)}
            onBlur={() => handleBlur("password")}
            error={fieldErrors.password}
          />
          {/*
           * The show/hide toggle is a real, independently-focusable button
           * beside the field rather than an icon dropped into `Input`'s own
           * `trailingIcon` slot. That slot renders inside an
           * `aria-hidden`-wrapped span with `pointer-events-none` on the
           * wrapper (`components/ui/input.tsx`) — correct for a decorative
           * status glyph, and it would make an interactive control placed
           * there invisible to assistive tech regardless of any CSS override
           * on the control itself. Verified by reading that component's
           * actual render output, not assumed from its prop doc comment.
           */}
          <div className="flex items-center justify-between gap-3">
            {values.password.length > 0 ? (
              <div className="flex flex-1 items-center gap-2">
                <div aria-hidden="true" className="flex flex-1 gap-1">
                  {[0, 1, 2, 3].map((segment) => (
                    <span
                      key={segment}
                      className={cn(
                        "h-1 flex-1 rounded-full transition-colors duration-[var(--dur-instant)] ease-out-soft",
                        segment < strength.score ? strengthFillClass(strength.score) : "bg-rule",
                      )}
                    />
                  ))}
                </div>
                {/* The text label is the real carrier of meaning; the bars
                    above are `aria-hidden` decoration (colour is never the
                    sole carrier, per DESIGN.md §3.6 / QUALITY-BAR.md). */}
                <span className="text-body-sm text-ink-faint">{strength.label}</span>
              </div>
            ) : (
              <span className="flex-1 text-body-sm text-ink-faint">
                At least {MIN_PASSWORD_LENGTH} characters.
              </span>
            )}
            <button
              type="button"
              disabled={busy}
              onClick={() => setShowPassword((previous) => !previous)}
              className="inline-flex shrink-0 items-center gap-1 text-body-sm text-ink-muted transition-colors duration-[var(--dur-instant)] ease-out-soft hover:text-ink disabled:cursor-not-allowed disabled:opacity-50"
            >
              {showPassword ? (
                <EyeSlash aria-hidden weight="regular" size={16} />
              ) : (
                <Eye aria-hidden weight="regular" size={16} />
              )}
              {/*
               * Visually hidden below `sm`, not removed: `sr-only` clips
               * rather than `display: none`-ing, so the accessible name is
               * "Show password"/"Hide password" at every width, and only the
               * 320-375px row's visual budget changes. At 320px this row
               * holds four meter segments, a strength word up to nine
               * characters ("Too short") and this button in ~224px of card
               * content width (`AuthFrame`'s own `px-4` plus the card's own
               * `p-8`, arithmetic checked against both, not eyeballed) — the
               * full "Show password" label left the bar cluster a few px
               * wide, which is legible but tighter than the rest of this
               * screen; the icon alone carries the control at that width, the
               * same way `SignupRoleSelect.tsx`'s CaretRight is icon-only.
               */}
              <span className="sr-only sm:not-sr-only">
                {showPassword ? "Hide password" : "Show password"}
              </span>
            </button>
          </div>
        </div>

        <div className="flex flex-col gap-1.5">
          {/*
           * `Checkbox`'s own `label` prop is a plain string (`components/ui/
           * checkbox.tsx`), which cannot hold the `/data` link this consent
           * needs. So the box is rendered with no `label` (leaving its own
           * internal wrapping label empty, box-only) and named instead via
           * `aria-labelledby` pointing at the paragraph beside it — a naming
           * relationship only, unlike a native `<label for>` wrapping that
           * same paragraph, which would also forward a click on the nested
           * `<a>` into a toggle of the box (a real, commonly-hit behaviour
           * for a link inside a `<label>`, not a hypothetical one).
           * `aria-labelledby` carries no such forwarding, so the link stays a
           * link and nothing else.
           */}
          <div className="flex items-start gap-2.5">
            <Checkbox
              id="signup-consent"
              required
              checked={values.acceptedTerms}
              disabled={busy}
              state={consentError ? "error" : undefined}
              aria-labelledby="signup-consent-copy"
              aria-describedby={consentError ? "signup-consent-error" : undefined}
              className="mt-0.5"
              onChange={(event) => {
                setValues((previous) => ({ ...previous, acceptedTerms: event.target.checked }))
                if (event.target.checked) setConsentError(false)
              }}
            />
            <p id="signup-consent-copy" className="text-body-sm text-ink-muted">
              I agree to how Lemely handles my data, described on the{" "}
              {/* New tab: this form's own half-filled state would otherwise
                  unmount the moment a same-tab navigation left the page. */}
              <Link to="/data" target="_blank" rel="noopener noreferrer" className={LINK_CLASS}>
                data handling page
              </Link>
              .
            </p>
          </div>
          {consentError ? (
            <p id="signup-consent-error" role="alert" className="text-body-sm text-err">
              Agree to how Lemely handles your data before continuing.
            </p>
          ) : null}
        </div>

        {signup.isError ? (
          <div className="flex flex-col gap-1.5">
            <p role="alert" className="text-body-sm text-err">
              {signUpFailureMessage(signup.error)}
            </p>
            {addressConflict ? (
              <Link to="/login" className={cn(LINK_CLASS, "w-fit")}>
                Log in
              </Link>
            ) : null}
          </div>
        ) : null}

        <Button type="submit" variant="accent" size="lg" loading={busy}>
          {busy ? "Creating account…" : "Create account"}
        </Button>
      </form>
    </AuthFrame>
  )
}

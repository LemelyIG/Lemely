/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import { useEffect, useRef, useState, type FormEvent } from "react"
import { Link, useNavigate, useSearchParams } from "react-router-dom"
import { useAuth } from "@/lib/auth/AuthContext"
import { portalPathForRole } from "@/lib/auth/RequireAuth"
import { Button, buttonVariants } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Checkbox } from "@/components/ui/checkbox"
import { CodeInput } from "@/components/auth/CodeInput"
import { ApiError } from "@/lib/api"
import { withNext } from "@/lib/nextPath"
import { normalizeInviteCode } from "@/lib/hooks/useInvitesApi"
import { useRequestParentCode, useVerifyParentCode } from "@/lib/hooks/useParentSignupApi"
import { MIN_PASSWORD_LENGTH, passwordStrength, strengthFillClass } from "./signupDetailsLogic"
import {
  parentInviteMissingCopy,
  parentRequestCodeFailure,
  parentSignupDevPanel,
  parentSignupFailureMessage,
  parentSignupStep,
  parentVerifyCodeFailure,
  validateParentEmailStep,
  validateParentPasswordStep,
} from "./signupParentLogic"
import { AuthFrame } from "./Login"

/*
 * `/signup/parent` · parent signup by invite (design spec §4/§5, superseding
 * D3.11's phone-OTP parent login and `ParentLogin.tsx`, which this task
 * deletes).
 *
 * ── The shape: three steps, one invite code carried through all of them ────
 *
 * Decision 2 (spec §2): "The student generates an invite. The parent opens
 * it, enters an email address, verifies a six-digit code sent to that
 * address, sets a password, and in one server call the account is created
 * (email already verified), linked to the child, and signed in." That is
 * three network calls (`request-code`, `verify-code`, `signup`) behind three
 * screens at one route, exactly the "one screen, several states" shape
 * `PasswordReset.tsx` and `VerifyEmail.tsx` already use rather than three
 * separate routes — `parentSignupStep` (`signupParentLogic.ts`) derives which
 * of the three from two pieces of state (`sentTo`, `proofToken`) instead of a
 * fourth, independently-tracked one that could drift from them.
 *
 * The invite `code` itself comes from `?code=`, matching
 * `signupPathForInvite`'s `parent` branch (`useInvitesApi.ts`) exactly, and is
 * carried on every one of the three calls — `request-code` and `verify-code`
 * both re-check the invite is still live server-side, and `signup` redeems it
 * as part of the same call that creates the account. Unlike
 * `SignupDetails.tsx`'s student/teacher path, there is no separate
 * `useRedeemInvite` call here afterwards: `POST /auth/parent/signup`'s own
 * docstring is explicit that it redeems the invite itself, in the same
 * request, before returning a session.
 *
 * ── No `?code=` at all, or a code that stops resolving ──────────────────────
 *
 * Both render the same panel (`parentInviteMissingCopy()`), the same
 * anti-enumeration reasoning `previewErrorCopy` documents for G-08's own
 * 404 (`useInvitesApi.ts`): a dead code and a code that never existed are
 * indistinguishable to a signed-out visitor by construction, so there is
 * nothing more specific this screen is entitled to say. The panel links to
 * `/join`, the one screen built for "I have a code, let's see what it is."
 *
 * ── The developer code panel, and the resend cooldown ───────────────────────
 *
 * `parentSignupDevPanel` mirrors `passwordResetDevPanel`'s D3.16 rule exactly
 * (`passwordResetLogic.ts`'s own comment): visible only when the configured
 * `EmailProvider` does not deliver out of band. Rendered at `text-data-lg`,
 * the same "hero number" treatment `ParentLogin.tsx`'s own six-digit devCode
 * panel used and `PasswordReset.tsx`'s long opaque token deliberately does
 * not (that one is `text-data-sm`, per its own comment) — a six-digit code is
 * short enough to read as one, a reset token is not.
 *
 * The 30-second resend cooldown is display-only, the same "the server stays
 * authoritative" reasoning `ParentLogin.tsx`'s own `RESEND_COOLDOWN_SECONDS`
 * gave: an early resend is a real 429 whose detail already names the seconds
 * remaining (`parentRequestCodeFailure`'s own 429 branch), and that message is
 * what gets rendered. This countdown only stops a tap that cannot work yet.
 *
 * ── Password step ────────────────────────────────────────────────────────
 *
 * Strength feedback and the minimum-length floor are `signupDetailsLogic.ts`
 * and `signupParentLogic.ts`'s re-export of its `MIN_PASSWORD_LENGTH` — one
 * floor and one meter for every self-service account, not a second copy for
 * parents. The D7.11 terms checkbox is the identical control, copy and
 * `aria-labelledby` naming relationship `SignupDetails.tsx` uses, because it
 * is the identical consent (`/data`, not a terms-of-service document this
 * repository does not have).
 *
 * ── Frame ────────────────────────────────────────────────────────────────
 *
 * `AuthFrame` (`Login.tsx`) is reused, not copied — see that export's own
 * docstring for what a third copy of this frame cost the codebase before
 * (`ParentLogin.tsx` carried one until P7.1, and this task deletes that file
 * for good).
 */

/** Display-only mirror of the server's own signup cooldown — see the module
 * docstring's "resend cooldown" section for why the server stays
 * authoritative regardless of what this counts down. */
const RESEND_COOLDOWN_SECONDS = 30

const CODE_LENGTH = 6

/** Matches `SignupDetails.tsx`/`SignupRoleSelect.tsx`'s own link recipe.
 * `Login.tsx`'s own `LINK_CLASS` diverges from this one on purpose (packet
 * A2): it adds `inline-flex min-h-11 items-center` for a 44px tap target on
 * that screen's sign-up/forgot-password/parent links. This file's links
 * were not part of that finding, so this recipe is unchanged. */
const LINK_CLASS =
  "rounded-sm text-accent-ink underline underline-offset-2 transition-colors hover:text-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"

/** The "this invite doesn't work" panel — rendered instead of the whole
 * three-step form when `?code=` is missing, or once any of the three calls
 * reports the invite as dead (a 404 anywhere along the flow). */
function InviteMissingPanel() {
  const copy = parentInviteMissingCopy()
  return (
    <AuthFrame dataPortal="parent">
      <div className="flex w-full max-w-100 flex-col gap-5 rounded-lg border border-rule bg-paper-raised p-8">
        <div className="flex flex-col gap-1.5">
          <h1 className="text-display-lg text-ink">{copy.heading}</h1>
          <p className="text-body-md text-ink-muted">{copy.body}</p>
        </div>
        <Link to="/join" className={buttonVariants({ variant: "accent", size: "lg" })}>
          {copy.actionLabel}
        </Link>
      </div>
    </AuthFrame>
  )
}

export function SignupParent() {
  const { parentSignup } = useAuth()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  // Matches `signupPathForInvite`'s parent branch (`useInvitesApi.ts`)
  // exactly: `/signup/parent?code=<code>`.
  const code = normalizeInviteCode(searchParams.get("code") ?? "")

  const [inviteDead, setInviteDead] = useState(false)

  const [name, setName] = useState("")
  const [email, setEmail] = useState("")
  const [emailError, setEmailError] = useState<string | undefined>(undefined)

  const [sentTo, setSentTo] = useState<string | null>(null)
  const [devCode, setDevCode] = useState<string | null>(null)
  const [codeValue, setCodeValue] = useState("")
  const [cooldown, setCooldown] = useState(0)
  const lastAttempted = useRef<string | null>(null)
  // Bumped on every successful `request-code` call, fresh send or resend
  // alike — used only as part of `CodeInput`'s `key` below, to force a real
  // remount (and therefore a genuinely cleared digit array) whenever a new
  // code has been sent. `CodeInput` itself does not resync its boxes from a
  // later `value` prop change (review round 1's Important finding 1 — see
  // that component's own module docstring), so this is how this screen
  // clears the boxes for a resend without giving `CodeInput` a resync path
  // that would reintroduce the bug that fix removed.
  const [codeGeneration, setCodeGeneration] = useState(0)

  const [proofToken, setProofToken] = useState<string | null>(null)
  const [password, setPassword] = useState("")
  const [passwordError, setPasswordError] = useState<string | undefined>(undefined)
  const [acceptedTerms, setAcceptedTerms] = useState(false)
  const [consentError, setConsentError] = useState(false)
  const [showPassword, setShowPassword] = useState(false)

  const requestCode = useRequestParentCode()
  const verifyCode = useVerifyParentCode()

  const step = parentSignupStep({ codeSentTo: sentTo, proofToken })
  const strength = passwordStrength(password)

  useEffect(() => {
    if (cooldown <= 0) return
    const timer = window.setTimeout(() => setCooldown((n) => n - 1), 1000)
    return () => window.clearTimeout(timer)
  }, [cooldown])

  const sendCode = (targetEmail: string) => {
    requestCode.mutate(
      { email: targetEmail, inviteCode: code },
      {
        onSuccess: (result) => {
          setSentTo(targetEmail)
          setDevCode(result.devCode)
          setCodeValue("")
          lastAttempted.current = null
          setCooldown(RESEND_COOLDOWN_SECONDS)
          setCodeGeneration((n) => n + 1)
          // Review round 1, Minor finding 10: a resend must not leave a
          // stale "that code doesn't match" sitting under boxes the reader
          // has not touched yet — the fresh code just sent has nothing to
          // do with the one that failed.
          verifyCode.reset()
        },
        onError: (err) => {
          if (parentRequestCodeFailure(err).deadInvite) setInviteDead(true)
        },
      },
    )
  }

  const handleEmailSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const errors = validateParentEmailStep(email)
    setEmailError(errors.email)
    if (errors.email) return
    sendCode(email.trim())
  }

  const handleVerify = (submittedCode: string) => {
    if (!sentTo) return
    if (verifyCode.isPending) return
    if (lastAttempted.current === submittedCode) return
    lastAttempted.current = submittedCode
    verifyCode.mutate(
      { email: sentTo, inviteCode: code, code: submittedCode },
      {
        onSuccess: (result) => setProofToken(result.proofToken),
        onError: (err) => {
          if (err instanceof ApiError && err.status === 404) setInviteDead(true)
        },
      },
    )
  }

  const handlePasswordSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const errors = validateParentPasswordStep(password)
    setPasswordError(errors.password)
    const missingConsent = !acceptedTerms
    setConsentError(missingConsent)
    if (errors.password || missingConsent || !proofToken) return
    parentSignup.mutate(
      {
        proofToken,
        password,
        displayName: name.trim() || undefined,
        acceptedTerms: true,
      },
      {
        onSuccess: (result) => navigate(portalPathForRole(result.role), { replace: true }),
        onError: (err) => {
          if (err instanceof ApiError && err.status === 404) setInviteDead(true)
        },
      },
    )
  }

  /** "Start again with your email address" — the recovery this screen offers
   * for a proof token that expired before step 3 was submitted (a 401 on
   * `parentSignup`, per `parentSignupFailureMessage`'s own comment). Clears
   * every later-step fact so `parentSignupStep` falls all the way back to
   * `"email"`, rather than leaving a half-verified state on screen. */
  const restart = () => {
    setSentTo(null)
    setDevCode(null)
    setCodeValue("")
    setProofToken(null)
    parentSignup.reset()
  }

  if (code === "" || inviteDead) {
    return <InviteMissingPanel />
  }

  const requestFailure = requestCode.isError ? parentRequestCodeFailure(requestCode.error) : null
  // `verifyCode`'s 404 (the invite died between `request-code` and this
  // call) is handled in `handleVerify`'s own `onError` by setting
  // `inviteDead`, which swaps the whole screen above — so by the time this
  // renders, any surviving `verifyCode` error is never a 404, and
  // `parentVerifyCodeFailure` only ever sees the cases it classifies.
  const verifyFailure =
    verifyCode.isError && !(verifyCode.error instanceof ApiError && verifyCode.error.status === 404)
      ? parentVerifyCodeFailure(verifyCode.error)
      : null
  // Matches `JoinWithCode.tsx`'s own use of `withNext` exactly (review round
  // 1, Minor finding 8) — one allowlisted `?next=` encoder for every screen
  // that carries a reader back to an invite after signing in, not a second,
  // hand-built query string that could drift from it.
  const signInHref = withNext("/login", `/join/${code}`)

  /**
   * The request-code failure panel, shared between the email step (a failed
   * initial send) and the code step (a failed resend) — `requestCode` is one
   * mutation object used by both `sendCode` call sites, so its `error` at
   * any given moment reflects whichever step's own last attempt produced it.
   * Review round 1, Important finding 2: the first cut only ever rendered
   * this inside the email step, so a resend that hit the server's cooldown
   * or a 5xx left the reader with no explanation at all.
   */
  const renderRequestFailure = () => {
    if (!requestFailure || requestFailure.deadInvite) return null
    return (
      <div className="flex flex-col gap-1.5">
        <p role="alert" className="text-body-sm text-err">
          {requestFailure.message}
        </p>
        {requestFailure.hasAccount ? (
          <Link to={signInHref} className={`${LINK_CLASS} w-fit`}>
            Sign in
          </Link>
        ) : null}
      </div>
    )
  }

  return (
    <AuthFrame
      dataPortal="parent"
      footer={
        <p className="text-body-sm text-ink-muted">
          Already have an account?{" "}
          <Link to={signInHref} className={LINK_CLASS}>
            Sign in
          </Link>
        </p>
      }
    >
      <div className="flex w-full max-w-100 flex-col gap-6">
        <div className="rounded-lg border border-rule bg-paper-raised p-8">
          {step === "email" ? (
            <form onSubmit={handleEmailSubmit} className="flex flex-col gap-5" noValidate>
              <div className="flex flex-col gap-1.5">
                <h1 className="text-display-lg text-ink">Create your parent account</h1>
                <p className="text-body-md text-ink-muted">
                  We'll send a code to your email to confirm it's you.
                </p>
              </div>

              <Input
                label="Your name"
                autoComplete="name"
                disabled={requestCode.isPending}
                value={name}
                onChange={(event) => setName(event.target.value)}
              />
              <Input
                label="Email"
                type="email"
                autoComplete="email"
                enterKeyHint="send"
                required
                disabled={requestCode.isPending}
                value={email}
                onChange={(event) => {
                  setEmail(event.target.value)
                  setEmailError(undefined)
                }}
                error={emailError}
              />

              {renderRequestFailure()}

              <Button type="submit" variant="accent" size="lg" loading={requestCode.isPending}>
                {requestCode.isPending ? "Sending…" : "Send code"}
              </Button>
            </form>
          ) : step === "code" ? (
            <div className="flex flex-col gap-5">
              <div className="flex flex-col gap-1.5">
                <h1 className="text-display-lg text-ink">Enter your code</h1>
                <p className="text-body-md text-ink-muted">
                  We sent a {CODE_LENGTH}-digit code to{" "}
                  <span className="text-data-md text-ink">{sentTo}</span>.
                </p>
              </div>

              <CodeInput
                // Forces a real remount, and therefore a freshly-cleared
                // digit array, whenever a new code is sent — see
                // `codeGeneration`'s own comment for why `CodeInput` cannot
                // be trusted to resync itself from `value` alone.
                key={`${sentTo}-${codeGeneration}`}
                length={CODE_LENGTH}
                value={codeValue}
                onChange={setCodeValue}
                onComplete={handleVerify}
                disabled={verifyCode.isPending}
                error={verifyFailure?.message ?? null}
              />

              {verifyCode.isPending ? (
                <p role="status" aria-live="polite" className="text-body-md text-ink-muted">
                  Checking your code…
                </p>
              ) : null}

              {/* The email gained an account in the window since this same
                  address's own `request-code` call — no code will ever
                  verify against it now, so this offers the way out
                  `parentVerifyCodeFailure`'s message names rather than
                  leaving the reader to keep retrying a dead code. */}
              {verifyFailure?.hasAccount ? (
                <Link to={signInHref} className={`${LINK_CLASS} w-fit`}>
                  Sign in
                </Link>
              ) : null}

              {/* Review round 1, Important finding 2: a failed resend (the
                  server's own cooldown, a 5xx, a dropped connection) used to
                  render nothing at all on this step. */}
              {renderRequestFailure()}

              {devCode
                ? (() => {
                    const panel = parentSignupDevPanel(devCode)
                    return panel.visible ? (
                      <div className="rounded-md border border-dashed border-rule bg-paper-sunk p-4">
                        <div className="text-eyebrow text-ink-faint">
                          Developer only · no email was sent
                        </div>
                        <div className="mt-1.5 text-data-lg text-ink">{panel.code}</div>
                        <p className="mt-1.5 text-body-sm text-ink-muted">
                          This appears because Lemely is running with the offline mock email
                          provider. With a real provider configured, the code is never shown here.
                        </p>
                      </div>
                    ) : null
                  })()
                : null}

              <div className="flex flex-col gap-3">
                <Button
                  type="button"
                  variant="secondary"
                  size="md"
                  onClick={() => sentTo && sendCode(sentTo)}
                  disabled={requestCode.isPending || cooldown > 0}
                >
                  {cooldown > 0
                    ? `Resend code in ${cooldown}s`
                    : requestCode.isPending
                      ? "Sending…"
                      : "Resend code"}
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="md"
                  onClick={() => {
                    setSentTo(null)
                    setDevCode(null)
                    setCodeValue("")
                    verifyCode.reset()
                    // A stale send/resend failure (the 400 "this email
                    // already has an account", a cooldown 429) is tied to
                    // the email being left behind — carrying it onto a blank
                    // "enter your email" form would read as a complaint
                    // about an address not yet typed.
                    requestCode.reset()
                  }}
                >
                  Change email
                </Button>
              </div>
            </div>
          ) : (
            <form onSubmit={handlePasswordSubmit} noValidate className="flex flex-col gap-5">
              <div className="flex flex-col gap-1.5">
                <h1 className="text-display-lg text-ink">Set a password</h1>
                <p className="text-body-md text-ink-muted">
                  One more step, and you'll be able to see how your child is doing.
                </p>
              </div>

              <div className="flex flex-col gap-2">
                <Input
                  label="Password"
                  type={showPassword ? "text" : "password"}
                  autoComplete="new-password"
                  required
                  disabled={parentSignup.isPending}
                  value={password}
                  onChange={(event) => {
                    setPassword(event.target.value)
                    setPasswordError(undefined)
                  }}
                  onBlur={() => setPasswordError(validateParentPasswordStep(password).password)}
                  error={passwordError}
                />
                <div className="flex items-center justify-between gap-3">
                  {password.length > 0 ? (
                    <div className="flex flex-1 items-center gap-2">
                      <div aria-hidden="true" className="flex flex-1 gap-1">
                        {[0, 1, 2, 3].map((segment) => (
                          <span
                            key={segment}
                            className={`h-1 flex-1 rounded-full transition-colors duration-[var(--dur-instant)] ease-out-soft ${
                              segment < strength.score ? strengthFillClass(strength.score) : "bg-rule"
                            }`}
                          />
                        ))}
                      </div>
                      <span className="text-body-sm text-ink-faint">{strength.label}</span>
                    </div>
                  ) : (
                    <span className="flex-1 text-body-sm text-ink-faint">
                      At least {MIN_PASSWORD_LENGTH} characters.
                    </span>
                  )}
                  <button
                    type="button"
                    disabled={parentSignup.isPending}
                    onClick={() => setShowPassword((previous) => !previous)}
                    className="inline-flex shrink-0 items-center gap-1 rounded-sm text-body-sm text-ink-muted transition-[color,transform] duration-[var(--dur-fast)] ease-out-soft hover:text-ink active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50 disabled:active:scale-100"
                  >
                    <span>{showPassword ? "Hide password" : "Show password"}</span>
                  </button>
                </div>
              </div>

              <div className="flex flex-col gap-1.5">
                <div className="flex items-start gap-2.5">
                  <Checkbox
                    id="parent-signup-consent"
                    required
                    checked={acceptedTerms}
                    disabled={parentSignup.isPending}
                    state={consentError ? "error" : undefined}
                    aria-labelledby="parent-signup-consent-copy"
                    aria-describedby={consentError ? "parent-signup-consent-error" : undefined}
                    className="mt-0.5"
                    onChange={(event) => {
                      setAcceptedTerms(event.target.checked)
                      if (event.target.checked) setConsentError(false)
                    }}
                  />
                  <p id="parent-signup-consent-copy" className="text-body-sm text-ink-muted">
                    I agree to how Lemely handles my data, described on the{" "}
                    <Link to="/data" target="_blank" rel="noopener noreferrer" className={LINK_CLASS}>
                      data handling page
                    </Link>
                    .
                  </p>
                </div>
                {consentError ? (
                  <p id="parent-signup-consent-error" role="alert" className="text-body-sm text-err">
                    Agree to how Lemely handles your data before continuing.
                  </p>
                ) : null}
              </div>

              {parentSignup.isError ? (
                <div className="flex flex-col gap-1.5">
                  <p role="alert" className="text-body-sm text-err">
                    {parentSignupFailureMessage(parentSignup.error)}
                  </p>
                  {parentSignup.error instanceof ApiError && parentSignup.error.status === 401 ? (
                    <Button type="button" variant="ghost" size="sm" className="w-fit" onClick={restart}>
                      Start again
                    </Button>
                  ) : null}
                </div>
              ) : null}

              <Button type="submit" variant="accent" size="lg" loading={parentSignup.isPending}>
                {parentSignup.isPending ? "Creating account…" : "Create account"}
              </Button>
            </form>
          )}
        </div>
      </div>
    </AuthFrame>
  )
}

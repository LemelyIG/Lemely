/* Hallmark · pre-emit critique: P4 H5 E4 S5 R4 V4 */
import { useEffect, useRef, useState } from "react"
import { Link, useNavigate, useParams } from "react-router-dom"
import { useAuth } from "@/lib/auth/AuthContext"
import { portalPathForRole } from "@/lib/auth/RequireAuth"
import type { Session } from "@/lib/auth/storage"
import { useProfile } from "@/lib/hooks/useMeApi"
import { Button, buttonVariants } from "@/components/ui/button"
import { SkeletonLine } from "@/components/ui/skeleton"
import { verificationFailureMessage } from "@/lib/authOutcome"
import { AuthFrame } from "./Login"
import { postVerifyPath, resendButtonLabel } from "./verifyEmailLogic"

/*
 * G-07 · Email verification, pending and confirm — the Study Notebook.
 *
 * One file serves both routes spec §4.4 lists: `/verify-email` (this screen
 * with no `:token`) and `/verify-email/:token` (the same screen, with one).
 * `VerifyEmail` below is the whole surface; which of `PendingScreen` or
 * `ConfirmScreen` renders is decided by `useParams().token` alone, so however
 * Task 19 mounts the two route entries (same element, two `RouteObject`s —
 * the pattern `/login` and `/login/parent` already use), this component
 * answers correctly.
 *
 * ── Binding requirement 1: a soft gate, not a wall (D7.4, D7.5) ─────────────
 *
 * `email_verified_at` lives on `users`, not in GoTrue, precisely so the
 * password grant always succeeds for an unverified account (D7.4) — the
 * alternative, GoTrue-native confirmation, refuses to authenticate at all,
 * which is the "hard wall" §G-07 explicitly rules out. D7.5 gates exactly one
 * route behind it, `POST /student/correct` (the Gemini spend), and nothing
 * else. `SignedInPending` below states that plainly, on this screen, before
 * the reader could stumble into the refusal somewhere else and have to piece
 * together why — the failure mode the parent task calls out by name.
 *
 * ── Binding requirement 2: never claim a mail was sent (D7.6, D3.16) ───────
 *
 * `deps.py` wires `MockEmailProvider()` unconditionally (`lemely/auth/
 * email.py`), so no deployment of this code as written delivers anything to
 * an inbox. `ResendVerificationResponse.devLink` is the single source of
 * truth this screen is allowed to read: non-null exactly when the configured
 * provider did **not** deliver out of band. Two consequences follow, both
 * different from the literal example copy in `docs/LEMELY_UI_SPEC.md` §G-07
 * ("Check your email"), which is not used verbatim here on purpose:
 *
 *   1. The heading and the standing copy never assert delivery. "Verify your
 *      email" is a status, not a claim about an inbox. Nothing on first paint
 *      says a mail is on its way, because nothing here yet knows that — see
 *      the next point.
 *   2. A `devLink` only exists as the *result* of a mutation this component
 *      itself fires (`resendVerification`). `signup`'s own send (Task 15,
 *      `SignupDetails.tsx`) happens in a different component and its
 *      `TokenResponse.devLink` is not persisted anywhere this screen could
 *      read on mount — `Session` (`lib/auth/storage.ts`) carries only
 *      `accessToken`/`refreshToken`/`userId`/`role`. Reaching for an
 *      undocumented hand-off (router state, say) would be coupling this file
 *      to an assumption about a sibling task's implementation that nothing in
 *      the Task 13 contract promises. So the pending screen asks, on mount,
 *      only what it can honestly answer ("this account is not verified yet")
 *      and defers the delivery question entirely to an explicit "Resend"
 *      click, which is what the spec asks the button to be anyway.
 *
 * When a resend succeeds, its own response is read directly: `devLink` present
 * renders the developer panel (worded on the "Developer only" pattern
 * `ParentLogin.tsx`'s `devCode` panel established for §G-05, swapped from SMS
 * to email); `devLink` null means a real provider just delivered, which is
 * the one moment this screen is entitled to say a mail was sent, and does.
 *
 * ── Binding requirement 3: pending state ────────────────────────────────────
 *
 * Address shown (`GET /me/profile`, role-agnostic so it works for both the
 * student and teacher variants of G-03), a resend action with a cooldown, and
 * a "Wrong address?" route — `handleWrongAddress` below explains why that
 * route is "sign out and start a fresh signup" rather than an in-place edit.
 *
 * ── Binding requirement 4: confirm routes to the role home ──────────────────
 *
 * See `postVerifyPath`'s own docstring (`./verifyEmailLogic.ts`) for exactly
 * what "the role home" can and cannot mean against this contract.
 *
 * ── Where the pure logic lives ──────────────────────────────────────────────
 *
 * `postVerifyPath` and `resendButtonLabel` are in `./verifyEmailLogic.ts`,
 * not here — the same split `onboardingData.ts` uses for the S-01/S-02
 * wizard (pure logic in its own module, tested directly by
 * `verifyEmail.test.ts`; component behaviour is Playwright's job, Task 23).
 * It is also the house fix for `oxlint`'s `react/only-export-components`
 * (`.oxlintrc.json`), which would otherwise warn on this file: a component
 * module may not also export plain functions without one.
 */

/**
 * Matches `AuthSettings.resend_verification_cooldown_seconds`
 * (`lemely/runtime/config.py`, default 30). Display-only, the same convention
 * `ParentLogin.tsx`'s `RESEND_COOLDOWN_SECONDS` already uses for the OTP
 * resend: the server stays authoritative (D7.12) and answers a too-early
 * resend with a real 429, mapped by `verificationFailureMessage` to
 * `AUTH_COOLDOWN_ACTIVE`. This constant only stops the button being tapped
 * again before the server would plausibly accept it.
 */
const RESEND_COOLDOWN_SECONDS = 30

/**
 * The §G-07 developer affordance, worded on the same "Developer only" pattern
 * `ParentLogin.tsx` uses for `devCode` (D3.16, applied to `devLink` by D7.6).
 * A real anchor rather than a code display: `devLink` is a redeemable URL, not
 * digits to retype, so the honest control is one that navigates.
 */
function DevLinkPanel({ link }: { link: string }) {
  return (
    <div className="rounded-md border border-dashed border-rule bg-paper-sunk p-4">
      <div className="text-eyebrow text-ink-faint">Developer only · no email was sent</div>
      <a
        href={link}
        target="_blank"
        rel="noopener noreferrer"
        className="mt-1.5 block truncate rounded-sm text-data-sm text-ink underline underline-offset-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
      >
        {link}
      </a>
      <p className="mt-1.5 text-body-sm text-ink-muted">
        This appears because Lemely is running with the offline mock email provider. With a
        real provider configured, this link is never shown here.
      </p>
    </div>
  )
}

/**
 * `/verify-email` with no live session. Reachable because the route is
 * deliberately not wrapped in `LoginRoute` (Task 19: wrapping it "would make
 * verification unreachable for the account that needs it") — but the pending
 * experience itself (an address to show, a resend to fire) has nothing to
 * work from without one, so this is its own honest, designed state rather
 * than a half-populated version of `SignedInPending`.
 */
function SignedOutPending() {
  return (
    <div className="flex w-full max-w-100 flex-col gap-5 rounded-lg border border-rule bg-paper-raised p-8">
      <div className="flex flex-col gap-1.5">
        <h1 className="text-display-lg text-ink">Sign in to check your verification status</h1>
        <p className="text-body-md text-ink-muted">
          We can only show whether your email is verified while you are signed in.
        </p>
      </div>
      <div className="flex flex-wrap gap-3">
        <Link to="/login" className={buttonVariants({ variant: "accent", size: "lg" })}>
          Sign in
        </Link>
        <Link to="/signup" className={buttonVariants({ variant: "secondary", size: "lg" })}>
          Create an account
        </Link>
      </div>
    </div>
  )
}

/**
 * The visible result of the last `resendVerification` attempt, as one value
 * rather than three independent booleans/strings. A three-state-flags version
 * of this (tried first, then caught here in review) let a *previous*
 * successful `devLink` keep rendering underneath a *new* failed attempt's
 * error, because nothing cleared it on the next click — two outcomes on
 * screen at once, one of them stale. A discriminated union makes "exactly one
 * outcome, or none yet" true by construction: setting the next one always
 * replaces the last.
 */
type ResendOutcome =
  | { kind: "idle" }
  | { kind: "devLink"; link: string }
  | { kind: "sentByProvider" }
  | { kind: "error"; message: string }

/**
 * `/verify-email` with a live session — the common case reached straight from
 * signup (D7.4: signup succeeds and mints a session for a still-unverified
 * account).
 */
function SignedInPending({ session }: { session: Session }) {
  const { resendVerification, logout } = useAuth()
  const navigate = useNavigate()
  const profile = useProfile()
  const [cooldown, setCooldown] = useState(0)
  const [outcome, setOutcome] = useState<ResendOutcome>({ kind: "idle" })

  useEffect(() => {
    if (cooldown <= 0) return
    const timer = window.setTimeout(() => setCooldown((n) => n - 1), 1000)
    return () => window.clearTimeout(timer)
  }, [cooldown])

  const handleResend = () => {
    resendVerification.mutate(undefined, {
      onSuccess: (result) => {
        setOutcome(
          result.devLink !== null
            ? { kind: "devLink", link: result.devLink }
            : { kind: "sentByProvider" },
        )
        setCooldown(RESEND_COOLDOWN_SECONDS)
      },
      onError: (err) => setOutcome({ kind: "error", message: verificationFailureMessage(err) }),
    })
  }

  /*
   * "Wrong address? Change it" (§G-07). Against this task's contract there is
   * no change-email endpoint — Task 13 lists `verifyEmail` and
   * `resendVerification` only, and inventing an in-place edit here would be
   * UI for a capability the backend does not have. PRODUCT.md's rule for
   * exactly this situation is to say so and offer the honest alternative
   * rather than pretend: signing out and starting a fresh signup is the one
   * real way to attach a different address to a new account. `logout()`
   * clears the mistyped account's session first, so the signup form that
   * follows is not silently reusing it.
   */
  const handleWrongAddress = () => {
    logout()
    navigate("/signup", { replace: true })
  }

  return (
    <div className="flex w-full max-w-100 flex-col gap-6">
      <div className="flex flex-col gap-5 rounded-lg border border-rule bg-paper-raised p-8">
        <div className="flex flex-col gap-1.5">
          <h1 className="text-display-lg text-ink">Verify your email</h1>
          {profile.isPending ? (
            <div className="flex flex-wrap items-center gap-1.5 text-body-md text-ink-muted">
              <span>Confirm</span>
              <SkeletonLine announce={false} width="9rem" className="h-4" />
              <span>to unlock everything Lemely does.</span>
            </div>
          ) : (
            <p className="text-body-md text-ink-muted">
              Confirm{" "}
              <span className="text-data-md text-ink">
                {profile.data?.email ?? "the email on your account"}
              </span>{" "}
              to unlock everything Lemely does.
            </p>
          )}
        </div>

        {/*
         * Binding requirement 1, stated here rather than left for a student
         * to discover at a 403 from `POST /student/correct` (D7.5). Named
         * once, plainly: submitting a paper for marking is the *only* thing
         * behind this gate — uploads, browsing and onboarding are not.
         */}
        <div className="rounded-md border border-rule bg-paper-sunk p-4">
          <p className="text-body-sm text-ink-muted">
            Browsing Lemely does not need a verified email. Submitting a paper for marking
            does, so verify when you are ready.
          </p>
        </div>

        {outcome.kind === "error" ? (
          <p role="status" aria-live="polite" className="text-body-sm text-warn">
            {outcome.message}
          </p>
        ) : outcome.kind === "devLink" ? (
          <DevLinkPanel link={outcome.link} />
        ) : outcome.kind === "sentByProvider" ? (
          <p role="status" aria-live="polite" className="text-body-sm text-ok">
            A new verification link is on its way to your inbox.
          </p>
        ) : null}

        <div className="flex flex-col gap-3">
          <Button
            type="button"
            variant="secondary"
            size="md"
            onClick={handleResend}
            disabled={resendVerification.isPending || cooldown > 0}
          >
            {resendButtonLabel({
              cooldownSeconds: cooldown,
              isPending: resendVerification.isPending,
            })}
          </Button>
          {/*
           * The clear route into a limited preview binding requirement 1
           * asks for. A real navigation (`Link` + `buttonVariants`, not a
           * `Button onClick`) because it has nowhere to report back to and
           * nothing to submit — it is a destination, matching the `Link`
           * convention `Overview.tsx` and `CreateFirstClass.tsx` already use
           * for the same shape of action. Accent, the screen's most
           * prominent control: the soft-gate promise is only real if
           * continuing is at least as inviting as verifying.
           */}
          <Link
            to={portalPathForRole(session.role)}
            className={buttonVariants({ variant: "accent", size: "lg" })}
          >
            Continue to Lemely
          </Link>
        </div>
      </div>

      <button
        type="button"
        onClick={handleWrongAddress}
        className="self-start rounded-sm pointer-coarse:min-h-11 text-body-sm text-ink-muted underline underline-offset-2 transition-colors hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
      >
        Wrong address? Change it
      </button>
    </div>
  )
}

function PendingScreen() {
  const { session } = useAuth()
  return session ? <SignedInPending session={session} /> : <SignedOutPending />
}

/**
 * `/verify-email/:token`. Fires `verifyEmail` once per distinct token on
 * mount — `attempted` guards the re-invocation the same way `ParentLogin.tsx`
 * guards its auto-submit-on-complete-code effect: every dependency is listed
 * honestly, and the ref (not an omitted dependency) is what stops a second
 * redemption attempt of a token that has already been sent.
 */
function ConfirmScreen({ token }: { token: string }) {
  const { verifyEmail, session } = useAuth()
  const navigate = useNavigate()
  const attempted = useRef<string | null>(null)

  useEffect(() => {
    if (attempted.current === token) return
    attempted.current = token
    verifyEmail.mutate(
      { token },
      { onSuccess: () => navigate(postVerifyPath(session), { replace: true }) },
    )
  }, [token, verifyEmail, session, navigate])

  return (
    <div className="flex w-full max-w-100 flex-col gap-5 rounded-lg border border-rule bg-paper-raised p-8">
      <h1 className="text-display-lg text-ink">
        {verifyEmail.isError ? "We could not verify that link" : "Verifying your email"}
      </h1>
      <p role="status" aria-live="polite" className="text-body-md">
        {verifyEmail.isError ? (
          <span className="text-warn">{verificationFailureMessage(verifyEmail.error)}</span>
        ) : (
          <span className="text-ink-muted">One moment…</span>
        )}
      </p>
      {/*
       * A failed token is not worth retrying as-is (a used, expired or
       * unknown token fails identically the second time — note 5 in
       * `authOutcome.ts`), so the way out is a fresh link, not a retry
       * button. Signed in can get one without leaving; signed out cannot
       * call the authenticated resend at all, so the honest options are
       * sign in or start over.
       */}
      {verifyEmail.isError ? (
        session ? (
          <Link to="/verify-email" className={buttonVariants({ variant: "accent", size: "lg" })}>
            Get a new verification link
          </Link>
        ) : (
          <div className="flex flex-wrap gap-3">
            <Link to="/login" className={buttonVariants({ variant: "accent", size: "lg" })}>
              Sign in
            </Link>
            <Link to="/signup" className={buttonVariants({ variant: "secondary", size: "lg" })}>
              Create an account
            </Link>
          </div>
        )
      ) : null}
    </div>
  )
}

export function VerifyEmail() {
  const { token } = useParams<{ token?: string }>()
  return <AuthFrame>{token ? <ConfirmScreen token={token} /> : <PendingScreen />}</AuthFrame>
}

/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V5 */
import { useState, type FormEvent } from "react"
import { Link, useParams } from "react-router-dom"
import { ArrowLeft } from "@phosphor-icons/react"
import { useAuth } from "@/lib/auth/AuthContext"
import { Button, buttonVariants } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { resetFailureMessage } from "@/lib/authOutcome"
import { cn } from "@/lib/utils"
import { AuthFrame } from "./Login"
import {
  PASSWORD_RESET_SUCCESS_BODY,
  passwordResetDevPanel,
  passwordResetSentBody,
  showResetSuccess,
} from "./passwordResetLogic"

/*
 * G-06 · Password reset (Task 17, spec §4.3/§4.4, decisions D7.6/D7.7).
 *
 * Before this file there was no password reset anywhere in the product: no
 * route, no service, no screen. A forgotten password was a permanently dead
 * account. This is the flow people reach already frustrated, so it is built
 * to be plain and to hold no surprises for them.
 *
 * ── "Three screens, no surprises" (UI spec §G-06), reconciled with four ────
 *
 * The spec's one line of guidance names four stages: "request by email →
 * confirmation screen → reset form from link → success." Task 17 names the
 * same four stages explicitly. Read literally that is four states, and the
 * reconciliation is in the grouping, not in dropping one: `/reset` carries
 * the request form and, once submitted, the confirmation, as two states of
 * ONE screen at one URL; `/reset/:token` carries the new-password form and,
 * once submitted, success, as two states of the other screen at the other
 * URL. Two routes, two views each, no third route and no extra hop between
 * them — which is the "no surprises" the spec actually asks for. Neither
 * transition calls `navigate()`; both are a local re-render at the same
 * address, exactly like `ParentLogin`'s phone step becoming its code step.
 *
 * ── AuthFrame, not a third copy of it ───────────────────────────────────────
 *
 * `AuthFrame` (`Login.tsx`) is reused rather than copied. `dataPortal` is
 * left unset on both screens here, matching `Login` itself rather than
 * `ParentLogin`: that prop identifies a ROLE's alternate sign-in surface, and
 * a password reset is not scoped to any one role the way the parent phone
 * flow is.
 *
 * ── Requirement 1 — identical wording regardless of whether the address exists
 *
 * `AuthService.request_password_reset` answers 200 either way and mints
 * nothing for an unknown address (D7's anti-enumeration rule, restated in
 * the backend's own docstring: "these two cases are indistinguishable by
 * design"). The UI half of that guarantee is `passwordResetSentBody` below:
 * it takes only the email the visitor themselves just typed, never a
 * server-asserted "found" flag, so there is no data path by which its output
 * could differ between an address that exists and one that does not. Echoing
 * the typed address back is not a leak — the visitor already knows what they
 * typed — the same reasoning `CodeStep` in `ParentLogin.tsx` relies on when
 * it echoes the phone number back.
 *
 * ── Requirement 3 — never claim a mail was sent, and the tension with 1 ─────
 *
 * `deps.py` wires `MockEmailProvider()` unconditionally (D7.6), so `devLink`
 * is non-null exactly when the address is known AND nothing has reached an
 * inbox — see `PasswordResetRequestResponse.devLink`'s own comment in
 * `authTypes.ts`. That is worth being explicit about: as long as this is the
 * only provider ever wired, the PRESENCE of the developer panel below is
 * itself correlated with account existence, in a way the response body's
 * headline `status: "sent"` deliberately is not. This is not a gap this file
 * introduces or can close — the panel is exactly what Task 17's requirement
 * 3 and the D3.16 `devCode` precedent instruct building, and `deps.py`'s
 * wiring is backend, committed, and out of this file's scope — but it is
 * recorded here rather than left for a future reader to rediscover, the same
 * way the SMS mock's own honesty gap is recorded in `routes.tsx` rather than
 * hidden. What this file DOES control is kept honest: `passwordResetSentBody`
 * never varies by `devLink`, and it never asserts delivery happened — it says
 * only what is true in every case, that a reset was started for an account
 * that exists. The panel is additional, clearly labelled, and never replaces
 * that sentence.
 *
 * `routes.tsx` already records the sibling defect this must not repeat:
 * `ParentLogin`'s code step says "We sent a {N}-digit code to {number}" as a
 * flat, unconditional past-tense claim, true only if a real SMS provider were
 * ever configured, which none is. Nothing in this file makes an unconditional
 * delivery claim; "Check your email" is an instruction, not an assertion, and
 * `passwordResetSentBody` is phrased "if an account exists ... we've started"
 * rather than "we've sent."
 *
 * ── Requirement 2 — the success screen names the device sign-out plainly ────
 *
 * `AuthService.reset_password` revokes every outstanding `auth_tokens` row
 * AND every device session (`lemely/auth/service.py`, step 3 of its own
 * docstring) because the reason for a reset may be a compromise. Surfacing
 * that here, in plain language, is the difference between a stated security
 * property and a stranger's phone quietly signing out later with no
 * explanation attached.
 *
 * ── Why the two screens pick their "which view" logic differently ───────────
 *
 * `PasswordResetRequest` gates on local `useState`, re-initialised to "form"
 * on every mount. That is deliberate: `requestPasswordReset` lives in
 * `AuthContext`, which never unmounts, so its own `isSuccess`/`data` persist
 * for the life of the tab. If this screen read those directly, a visitor who
 * requests a reset, navigates away to `/login`, and later returns to `/reset`
 * fresh would see stale confirmation copy from their earlier visit before
 * typing anything this time. Local state, reset by the mount that a real
 * navigation away and back causes, avoids that.
 *
 * `PasswordResetConfirm` cannot use the same trick safely, because `/reset`
 * has no dynamic segment to distinguish "fresh mount" from "same mount, new
 * resource" and `/reset/:token` does. React Router does not remount a routed
 * component merely because its own `:token` param changed — only local state
 * keyed on nothing would carry a SUCCEEDED flag from one token onto a
 * DIFFERENT token viewed in the same tab (reachable via the browser's
 * back/forward history across two `/reset/:token` visits). `showResetSuccess`
 * (`passwordResetLogic.ts`) closes that instead of local state: it is true
 * only when the last successful call's own token matches the token currently
 * in the URL, so switching the URL without a fresh submission cannot show
 * success for a token nothing was actually confirmed for.
 *
 * ── The `passwordResetLogic.ts` split ────────────────────────────────────────
 *
 * The three binding-requirement decisions above (`passwordResetSentBody`,
 * `passwordResetDevPanel`, `PASSWORD_RESET_SUCCESS_BODY`) and the token guard
 * (`showResetSuccess`) are pure and live in `./passwordResetLogic.ts`, not
 * here — the same split `onboardingData.ts` and `verifyEmailLogic.ts` use,
 * for the same two reasons: `vitest.config.ts` runs the unit suite in a Node
 * environment with no DOM, so pure logic needs a plain `.ts` module to be
 * importable by `passwordReset.test.ts` at all; and this project's
 * `react/only-export-components` oxlint rule (`.oxlintrc.json`) warns on any
 * `.tsx` file that exports both a component and a plain function/constant,
 * which a second, non-component module is the rule's own suggested fix for.
 * Read `passwordResetLogic.ts`'s docstrings for the full reasoning behind
 * each of the four; this file's own docstring stays focused on the screen.
 */

/**
 * The "go back to signing in" link shared by every state in this file.
 *
 * Passed to `AuthFrame`'s `footer` prop rather than folded into `children`
 * (contrast `ParentLogin`, whose own back-link sits inside an extra
 * `flex-col` wrapper it shares with its card): `footer` renders as a direct
 * child of `AuthFrame`'s own `items-center` row, so `w-full max-w-100` here
 * — matching the card's own width — is what keeps this link's start edge
 * flush with the card's, the same alignment `ParentLogin` gets from its
 * wrapper div. `self-start` alone would not do this from inside `footer`: it
 * would flush the link to the viewport edge, not to the card.
 */
function BackToSignIn({ label }: { label: string }) {
  return (
    <Link
      to="/login"
      className="flex w-full max-w-100 items-center gap-1.5 rounded-sm pointer-coarse:min-h-11 text-body-sm text-ink-muted transition-colors hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
    >
      {/* Direction-dependent: points at the reading start, mirrors under
          `dir="rtl"` (matches the identical control in ParentLogin.tsx). */}
      <ArrowLeft size={14} aria-hidden="true" className="rtl:-scale-x-100" />
      {label}
    </Link>
  )
}

/**
 * The developer-only affordance shown on `/reset` when `devLink` is present.
 *
 * Styled identically to `ParentLogin.tsx`'s `devCode` panel (same border,
 * same wash, same eyebrow-then-value-then-note shape) with one deliberate
 * difference: the value renders at `text-data-sm`, not `text-data-lg`. A
 * six-digit OTP is short enough to read as a hero number; a reset token is a
 * long opaque string, and DESIGN.md §4.2 names `data-sm` for exactly this
 * job ("paper codes, IDs, timestamps, metadata"), with `break-all` so it
 * wraps instead of forcing the card wider. The link is also rendered as a
 * real in-app `Link`, not just displayed text: a six-digit code is retyped
 * by hand into the boxes already on screen, but a URL has nowhere to be
 * retyped into, so a developer needs to be able to follow it directly the
 * way a real emailed link would be clicked.
 */
function DeveloperResetLinkPanel({ link }: { link: string }) {
  return (
    <div className="rounded-md border border-dashed border-rule bg-paper-sunk p-4">
      <div className="text-eyebrow text-ink-faint">Developer only · no email was sent</div>
      <div className="mt-1.5 break-all text-data-sm text-ink">{link}</div>
      <p className="mt-1.5 text-body-sm text-ink-muted">
        This appears because Lemely is running with the offline mock email provider. With a
        real provider configured, this panel never appears.
      </p>
      <Link
        to={link}
        className={cn(buttonVariants({ variant: "secondary", size: "sm" }), "mt-3")}
      >
        Open this link
      </Link>
    </div>
  )
}

/** `/reset` · request a reset link by email. */
export function PasswordResetRequest() {
  const { requestPasswordReset } = useAuth()
  const [email, setEmail] = useState("")
  // See the module docstring's last section for why this is local state
  // rather than a read of `requestPasswordReset.isSuccess` directly.
  const [sentEmail, setSentEmail] = useState<string | null>(null)
  const [devLink, setDevLink] = useState<string | null>(null)

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    requestPasswordReset.mutate(
      { email },
      {
        onSuccess: (result) => {
          setSentEmail(email)
          setDevLink(result.devLink)
        },
      },
    )
  }

  if (sentEmail !== null) {
    const panel = passwordResetDevPanel(devLink)
    return (
      <AuthFrame footer={<BackToSignIn label="Remembered it? Sign in" />}>
        <div className="flex w-full max-w-100 flex-col gap-5 rounded-lg border border-rule bg-paper-raised p-8">
          <div className="flex flex-col gap-1.5">
            <h1 className="text-display-lg text-ink">Check your email</h1>
            <p className="text-body-md text-ink-muted">{passwordResetSentBody(sentEmail)}</p>
          </div>

          <p className="text-body-sm text-ink-faint">
            Check your spam folder if you do not see it soon.
          </p>

          {panel.visible && panel.link ? <DeveloperResetLinkPanel link={panel.link} /> : null}

          <Button
            type="button"
            variant="ghost"
            size="md"
            onClick={() => {
              setSentEmail(null)
              setDevLink(null)
              // Clears the mutation's own isError/isPending/data so a retry
              // after a cooldown 429 does not carry a stale error banner
              // into the fresh form (matches `login.reset()` in Login.tsx).
              requestPasswordReset.reset()
            }}
          >
            Try a different email
          </Button>
        </div>
      </AuthFrame>
    )
  }

  return (
    <AuthFrame footer={<BackToSignIn label="Remembered it? Sign in" />}>
      <form
        onSubmit={handleSubmit}
        className="flex w-full max-w-100 flex-col gap-5 rounded-lg border border-rule bg-paper-raised p-8"
      >
        <div className="flex flex-col gap-1.5">
          <h1 className="text-display-lg text-ink">Reset your password</h1>
          <p className="text-body-md text-ink-muted">
            Enter the email you use to sign in. If we find a match, we&rsquo;ll help you set a
            new one.
          </p>
        </div>

        <Input
          label="Email"
          type="email"
          required
          autoComplete="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
        />

        {requestPasswordReset.isError ? (
          <p role="alert" className="text-body-sm text-err">
            {resetFailureMessage(requestPasswordReset.error)}
          </p>
        ) : null}

        <Button type="submit" variant="accent" size="lg" loading={requestPasswordReset.isPending}>
          {requestPasswordReset.isPending ? "Sending…" : "Send reset link"}
        </Button>
      </form>
    </AuthFrame>
  )
}

/** `/reset/:token` · set a new password from an emailed link. */
export function PasswordResetConfirm() {
  // Default to "", matching the established convention across the portal
  // (`Subject.tsx`, `PaperResult.tsx`, ...) rather than leaving this
  // `string | undefined` — see `showResetSuccess`, which treats "" as "no
  // token" explicitly instead of a second falsy shape to check for.
  const { token = "" } = useParams<{ token: string }>()
  const { confirmPasswordReset } = useAuth()
  const [newPassword, setNewPassword] = useState("")

  const succeeded = showResetSuccess(
    confirmPasswordReset.isSuccess,
    confirmPasswordReset.variables?.token,
    token,
  )

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    // Defensive only: the route this screen is mounted on (spec §4.4,
    // `/reset/:token`) cannot match with an empty segment, so this is not
    // reachable in normal operation. Left as a guard rather than a dead
    // assumption, matching the same discipline `AuthService.reset_password`
    // applies server-side to a token that fails to redeem.
    if (token === "") return
    confirmPasswordReset.mutate({ token, newPassword })
  }

  if (succeeded) {
    return (
      <AuthFrame>
        <div className="flex w-full max-w-100 flex-col gap-5 rounded-lg border border-rule bg-paper-raised p-8">
          <div className="flex flex-col gap-1.5">
            <h1 className="text-display-lg text-ink">Password changed</h1>
            {/* Requirement 2 — see PASSWORD_RESET_SUCCESS_BODY's own
                docstring in passwordResetLogic.ts for why this is stated
                plainly rather than left to be discovered later as an
                unexplained sign-out on someone's phone. */}
            <p className="text-body-md text-ink-muted">{PASSWORD_RESET_SUCCESS_BODY}</p>
          </div>
          <Link to="/login" className={buttonVariants({ variant: "accent", size: "lg" })}>
            Sign in
          </Link>
        </div>
      </AuthFrame>
    )
  }

  return (
    <AuthFrame footer={<BackToSignIn label="Remembered your password? Sign in" />}>
      <form
        onSubmit={handleSubmit}
        className="flex w-full max-w-100 flex-col gap-5 rounded-lg border border-rule bg-paper-raised p-8"
      >
        <div className="flex flex-col gap-1.5">
          <h1 className="text-display-lg text-ink">Set a new password</h1>
          <p className="text-body-md text-ink-muted">Choose a new password for your account.</p>
        </div>

        <Input
          label="New password"
          type="password"
          required
          autoComplete="new-password"
          value={newPassword}
          onChange={(event) => setNewPassword(event.target.value)}
        />

        {confirmPasswordReset.isError ? (
          <p role="alert" className="text-body-sm text-err">
            {resetFailureMessage(confirmPasswordReset.error)}
          </p>
        ) : null}

        <Button type="submit" variant="accent" size="lg" loading={confirmPasswordReset.isPending}>
          {confirmPasswordReset.isPending ? "Saving…" : "Set new password"}
        </Button>
      </form>
    </AuthFrame>
  )
}

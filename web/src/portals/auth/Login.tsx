/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import { useState, type FormEvent } from "react"
import { Link, useNavigate } from "react-router-dom"
import { useAuth } from "@/lib/auth/AuthContext"
import { portalPathForRole } from "@/lib/auth/RequireAuth"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { ApiError } from "@/lib/api"
import { isDeviceLimitChallenge, type DeviceLimitChallenge } from "@/lib/deviceTypes"
import { takeSessionExpired } from "@/lib/auth/storage"
import { signInFailureMessage } from "@/lib/authOutcome"
import { DeviceLimitNotice } from "./DeviceLimitNotice"

/*
 * G-04 · Sign in with email and password — the Study Notebook (P4.7).
 *
 * This file's own module docstring used to open "infrastructure to exercise
 * the auth plumbing …, not final UI. Screen polish is P2.7/P2.8's job." Those
 * chunks came and went and the note stayed true, so the first screen every
 * user of this product meets spent the whole build era as scaffolding. Three
 * of its defects follow directly from that.
 *
 * **The card was invisible.** The page and the card were both `bg-surface`, so
 * a panel sat on a background of its own colour with only a hairline to say it
 * was there. DESIGN.md §3.1's whole tonal system exists for this: the canvas
 * is `--paper` and a card is `--paper-raised`, "the way a sheet laid on a desk
 * catches more light". Now it is.
 *
 * **The error was at the bottom of the form**, under the fields and above the
 * button, which is the one place §12 rules out ("errors inline and adjacent to
 * the field, never only at the top of the form" — the bottom is no better).
 * The fields are the kit's `Input` now, which puts a field-level error under
 * its own field and has all eight states; the form-level error, which is what
 * a rejected credential really is, sits directly above the button that
 * produced it.
 *
 * **It rendered `login.error.message` raw.** `request()` falls back to
 * `` `${res.status} ${res.statusText}` `` when a body carries no string
 * detail, so a failed sign-in could put **"401 Unauthorized"** in front of a
 * fifteen-year-old. `signInFailureMessage` owns that now, and it deliberately
 * does not say whether the email exists — see `lib/authOutcome.ts`.
 *
 * G-10 lives here rather than on its own route (P5.7): the challenge is a
 * refusal of *this* submission, and the credentials needed to confirm it are in
 * this component's state. A route change would either lose them or have to park
 * a password somewhere it does not belong.
 */

/**
 * The signed-out frame both auth screens sit in.
 *
 * Shared rather than repeated: the mark, the paper, the grain and the column
 * are the same on the password screen, the device-limit refusal and the parent
 * phone flow, and three copies of a frame is how three signed-out screens end
 * up with three different ideas of where the logo goes.
 */
export function AuthFrame({
  children,
  footer,
}: {
  children: React.ReactNode
  footer?: React.ReactNode
}) {
  return (
    <main className="paper-grain flex min-h-screen flex-col items-center justify-center gap-6 bg-paper px-4 py-12">
      {/* `alt=""` and `aria-hidden`: the wordmark beside it already says
          "Lemely", so describing the mark too announces the brand twice. */}
      <div className="flex items-center gap-2.5">
        <img src="/brand/mark.svg" alt="" aria-hidden="true" className="h-7 w-7 shrink-0" />
        <span className="text-display-md text-ink">Lemely</span>
      </div>
      {children}
      {footer}
    </main>
  )
}

export function Login() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [challenge, setChallenge] = useState<DeviceLimitChallenge | null>(null)
  // Read once, on mount, and cleared by the read: landing here after a session
  // expired should say so. Being silently returned to a login screen reads as
  // the app having lost your work, which is the impression the old behaviour
  // gave once it stopped showing raw 401 text.
  const [expired] = useState(() => takeSessionExpired())

  const signIn = (confirmDeviceEviction: boolean) => {
    login.mutate(
      { email, password, confirmDeviceEviction },
      {
        onSuccess: (result) => navigate(portalPathForRole(result.role), { replace: true }),
        // A 409 is not a failed login: the password was right and nothing has
        // been signed out yet. Anything else stays an ordinary error message.
        onError: (error) => {
          const detail = error instanceof ApiError ? error.detail : undefined
          setChallenge(isDeviceLimitChallenge(detail) ? detail : null)
        },
      },
    )
  }

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    signIn(false)
  }

  if (challenge) {
    const failedConfirm =
      login.isError &&
      !isDeviceLimitChallenge(login.error instanceof ApiError ? login.error.detail : undefined)
    return (
      <AuthFrame>
        <DeviceLimitNotice
          challenge={challenge}
          isPending={login.isPending}
          error={failedConfirm ? signInFailureMessage(login.error) : null}
          onConfirm={() => signIn(true)}
          onCancel={() => {
            setChallenge(null)
            login.reset()
          }}
        />
      </AuthFrame>
    )
  }

  return (
    <AuthFrame
      footer={
        /* UI spec §G-04: "Parent → G-05 (parents authenticate by phone)".
           Parents have no password to type here — this is the only way in. */
        <p className="text-body-sm text-ink-muted">
          Are you a parent?{" "}
          <Link
            to="/login/parent"
            className="rounded-sm text-accent-ink underline underline-offset-2 transition-colors hover:text-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
          >
            Sign in with your phone
          </Link>
        </p>
      }
    >
      <form
        onSubmit={handleSubmit}
        className="flex w-full max-w-100 flex-col gap-5 rounded-lg border border-rule bg-paper-raised p-8"
      >
        <div className="flex flex-col gap-1.5">
          <h1 className="text-display-lg text-ink">Sign in</h1>
          {expired ? (
            // A status, not an error: nothing went wrong, a session simply ran
            // out. `role="status"` so it is announced without interrupting.
            <p role="status" className="text-body-md text-ink-muted">
              Your session expired. Please sign in again.
            </p>
          ) : (
            <p className="text-body-md text-ink-muted">
              Students and teachers sign in here.
            </p>
          )}
        </div>

        <Input
          label="Email"
          type="email"
          required
          autoComplete="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
        />
        <Input
          label="Password"
          type="password"
          required
          autoComplete="current-password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />

        {/*
         * The form-level error sits with the control that produced it. A
         * rejected credential is not a property of either field on its own —
         * `authOutcome` deliberately declines to say which half was wrong —
         * so it belongs here rather than under one of them.
         */}
        {login.isError && !challenge ? (
          <p role="alert" className="text-body-sm text-err">
            {signInFailureMessage(login.error)}
          </p>
        ) : null}

        <Button type="submit" variant="accent" size="lg" loading={login.isPending}>
          {login.isPending ? "Signing in…" : "Sign in"}
        </Button>
      </form>
    </AuthFrame>
  )
}

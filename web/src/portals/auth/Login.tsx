import { useState, type FormEvent } from "react"
import { Link, useNavigate } from "react-router-dom"
import { useAuth } from "@/lib/auth/AuthContext"
import { portalPathForRole } from "@/lib/auth/RequireAuth"
import { Button } from "@/components/ui/button"
import { ApiError } from "@/lib/api"
import { isDeviceLimitChallenge, type DeviceLimitChallenge } from "@/lib/deviceTypes"
import { DeviceLimitNotice } from "./DeviceLimitNotice"

/*
 * Minimal email/password login screen — infrastructure to exercise the auth
 * plumbing (AuthContext, storage, api bearer header), not final UI. Screen
 * polish is P2.7/P2.8's job.
 *
 * G-10 lives here rather than on its own route (P5.7): the challenge is a
 * refusal of *this* submission, and the credentials needed to confirm it are in
 * this component's state. A route change would either lose them or have to park
 * a password somewhere it does not belong.
 */
export function Login() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [challenge, setChallenge] = useState<DeviceLimitChallenge | null>(null)

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
      <main className="flex min-h-screen items-center justify-center bg-surface px-4">
        <DeviceLimitNotice
          challenge={challenge}
          isPending={login.isPending}
          error={failedConfirm ? login.error.message : null}
          onConfirm={() => signIn(true)}
          onCancel={() => {
            setChallenge(null)
            login.reset()
          }}
        />
      </main>
    )
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-surface px-4">
      <form
        onSubmit={handleSubmit}
        className="flex w-full max-w-90 flex-col gap-4 rounded-md border border-border bg-surface p-8"
      >
        <h1 className="text-display-md">Lemely</h1>
        <label className="flex flex-col gap-1.5 text-sm">
          Email
          <input
            type="email"
            required
            autoComplete="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            className="rounded border border-border px-3 py-2 text-sm"
          />
        </label>
        <label className="flex flex-col gap-1.5 text-sm">
          Password
          <input
            type="password"
            required
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            className="rounded border border-border px-3 py-2 text-sm"
          />
        </label>
        {login.isError ? (
          <p className="text-xs text-err">
            {login.error instanceof Error ? login.error.message : "Login failed."}
          </p>
        ) : null}
        <Button type="submit" variant="ink" size="lg" disabled={login.isPending}>
          {login.isPending ? "Signing in…" : "Sign in"}
        </Button>
        {/* UI spec §G-04: "Parent → G-05 (parents authenticate by phone)".
            Parents have no password to type here — this is the only way in. */}
        <p className="text-body-md text-t2">
          Are you a parent?{" "}
          <Link to="/login/parent" className="text-accent hover:underline">
            Sign in with your phone
          </Link>
        </p>
      </form>
    </main>
  )
}

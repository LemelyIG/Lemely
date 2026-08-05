import { useState, type FormEvent } from "react"
import { useNavigate } from "react-router-dom"
import { useAuth } from "@/lib/auth/AuthContext"
import { portalPathForRole } from "@/lib/auth/RequireAuth"
import { Button } from "@/components/ui/button"

/*
 * Minimal email/password login screen — infrastructure to exercise the auth
 * plumbing (AuthContext, storage, api bearer header), not final UI. Screen
 * polish is P2.7/P2.8's job.
 */
export function Login() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    login.mutate(
      { email, password },
      {
        onSuccess: (result) => navigate(portalPathForRole(result.role), { replace: true }),
      },
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
      </form>
    </main>
  )
}

import { useState, type FormEvent } from "react"
import { useNavigate } from "react-router-dom"
import { useAuth } from "@/lib/auth/AuthContext"
import { portalPathForRole } from "@/lib/auth/RequireAuth"

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
    <div className="flex min-h-screen items-center justify-center bg-surface px-4">
      <form
        onSubmit={handleSubmit}
        className="flex w-full max-w-[360px] flex-col gap-4 rounded-[12px] border border-border bg-white p-8"
      >
        <div className="font-serif text-[24px]">Lemely</div>
        <label className="flex flex-col gap-1.5 text-[13px]">
          Email
          <input
            type="email"
            required
            autoComplete="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            className="rounded-[8px] border border-border px-3 py-2 text-[14px]"
          />
        </label>
        <label className="flex flex-col gap-1.5 text-[13px]">
          Password
          <input
            type="password"
            required
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            className="rounded-[8px] border border-border px-3 py-2 text-[14px]"
          />
        </label>
        {login.isError ? (
          <p className="text-[12.5px] text-[oklch(0.42_0.10_22)]">
            {login.error instanceof Error ? login.error.message : "Login failed."}
          </p>
        ) : null}
        <button
          type="submit"
          disabled={login.isPending}
          className="rounded-[10px] bg-ink px-4 py-2.5 text-[13.5px] font-medium text-accent-on disabled:opacity-50"
        >
          {login.isPending ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </div>
  )
}

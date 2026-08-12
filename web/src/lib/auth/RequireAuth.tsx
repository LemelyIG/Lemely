import type { ReactNode } from "react"
import { Navigate } from "react-router-dom"
import { useAuth } from "./AuthContext"

/*
 * Role-gated route guard for the portal subtrees. Wraps a portal's root
 * element (not each screen) so the whole subtree is gated in one place:
 *   - no session              -> /login
 *   - session, wrong role     -> the portal that does match the session's role
 * `allowedRoles` lists which roles may render this subtree.
 */

/**
 * The portal a role belongs in. `parent` resolves to its own portal as of
 * P3.9 — it previously fell through to `/teacher`, which meant a parent
 * completing the OTP flow landed in the teacher console (every screen there
 * then 403'd, since `/api/teacher/*` is gated `teacher`+`school_admin`).
 *
 * `school_admin` and `platform_admin` still resolve to `/teacher`, which is
 * deliberate and not the same bug: they hold the teacher-router roles, so the
 * screens there genuinely serve them. Their dedicated surfaces (K-01, X-01)
 * are Phase-5/6 work.
 */
export function portalPathForRole(role: string): string {
  if (role === "student") return "/student"
  if (role === "parent") return "/parent"
  return "/teacher"
}

export function RequireAuth({
  allowedRoles,
  children,
}: {
  allowedRoles: readonly string[]
  children: ReactNode
}) {
  const { session } = useAuth()
  if (!session) return <Navigate to="/login" replace />
  if (!allowedRoles.includes(session.role)) {
    return <Navigate to={portalPathForRole(session.role)} replace />
  }
  return children
}

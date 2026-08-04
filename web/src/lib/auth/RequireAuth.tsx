import type { ReactNode } from "react"
import { Navigate } from "react-router-dom"
import { useAuth } from "./AuthContext"

/*
 * Role-gated route guard for the portal subtrees. Wraps a portal's root
 * element (not each screen) so the whole subtree is gated in one place:
 *   - no session              -> /login
 *   - session, wrong role     -> the portal that does match the session's role
 * `allowedRoles` lists which roles may render this subtree; everything else
 * (parent/school_admin/platform_admin today) resolves to /teacher, the
 * closest existing surface until Phase 3 gives them dedicated portals.
 */

export function portalPathForRole(role: string): string {
  return role === "student" ? "/student" : "/teacher"
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

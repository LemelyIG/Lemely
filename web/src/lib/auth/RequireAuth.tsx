import { useEffect, type ReactNode } from "react"
import { Navigate } from "react-router-dom"
import { useAuth } from "./AuthContext"
import { isTokenExpired } from "./jwt"
import { clearSession, markSessionExpired, type Session } from "./storage"

/*
 * Role-gated route guard for the portal subtrees. Wraps a portal's root
 * element (not each screen) so the whole subtree is gated in one place:
 *   - no session              -> /login
 *   - session past saving     -> /login, with a "session expired" notice
 *   - session, wrong role     -> the portal that does match the session's role
 * `allowedRoles` lists which roles may render this subtree.
 */

/**
 * Whether this session can still reach the API, now or after a refresh.
 *
 * An expired *access* token is emphatically not a dead session — that is the
 * ordinary state of affairs between refreshes, and bouncing on it would defeat
 * the silent renewal in `lib/api.ts` entirely. What cannot be saved is an
 * expired access token with no live refresh token behind it: every request from
 * such a session will 401 forever. This guard used to check only that *some*
 * session object existed, which is why a month-old one still rendered the full
 * portal with every screen inside it showing the server's 401 text.
 */
function isSessionRecoverable(session: Session): boolean {
  if (!isTokenExpired(session.accessToken)) return true
  if (!session.refreshToken) return false
  return !isTokenExpired(session.refreshToken)
}

/**
 * The portal a role belongs in. `parent` resolves to its own portal as of
 * P3.9 — it previously fell through to `/teacher`, which meant a parent
 * completing the OTP flow landed in the teacher console (every screen there
 * then 403'd, since `/api/teacher/*` is gated `teacher`+`school_admin`).
 *
 * P4.7 gave the two admin roles their own homes, and they arrived there by
 * different routes:
 *
 * * `school_admin` → `/school`. Not because `/teacher` was broken for them —
 *   it genuinely works, and they can still reach it — but because seats, staff
 *   and the school's own figures had no screen at all, and those are the things
 *   an administrator signs in to do.
 * * `platform_admin` → `/platform`, and they can no longer reach `/teacher` at
 *   all. That is a fix, not a restriction: every service behind the teacher
 *   portal returns empty for this role on purpose (no super-role bypass,
 *   D1.6/D1.10), so the console they used to land in was guaranteed blank.
 */
export function portalPathForRole(role: string): string {
  if (role === "student") return "/student"
  if (role === "parent") return "/parent"
  if (role === "school_admin") return "/school"
  if (role === "platform_admin") return "/platform"
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
  const stranded = session !== null && !isSessionRecoverable(session)

  // Drop the dead session rather than merely navigating away from it: left in
  // localStorage it would strand the user again on the next reload, and the
  // login screen has no other way to know this was an expiry rather than an
  // ordinary sign-out. Clearing it also notifies `AuthContext`, so the redirect
  // below settles onto the plain `!session` case.
  useEffect(() => {
    if (stranded) {
      clearSession()
      markSessionExpired()
    }
  }, [stranded])

  if (!session || stranded) return <Navigate to="/login" replace />
  if (!allowedRoles.includes(session.role)) {
    return <Navigate to={portalPathForRole(session.role)} replace />
  }
  return children
}

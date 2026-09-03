import { useEffect, type ReactNode } from "react"
import { Navigate, useLocation } from "react-router-dom"
import { useAuth } from "./AuthContext"
import { isTokenExpired } from "./jwt"
import { clearSession, markSessionExpired, peekSessionExpired, type Session } from "./storage"
import { withNext } from "@/lib/nextPath"
import { FullPageState } from "@/portals/misc/FullPageState"

/*
 * Role-gated route guard for the portal subtrees. Wraps a portal's root
 * element (not each screen) so the whole subtree is gated in one place:
 *   - session stranded (refresh token dead)      -> /session-ended?next=…
 *   - no session, but a refresh was just refused -> /session-ended?next=…
 *     (`api.ts`'s silent refresh cleared the session and flagged it mid-
 *     session; `peekSessionExpired()` is how this guard hears about that
 *     without consuming the flag `Login.tsx` still needs to read)
 *   - no session, otherwise                       -> /login?next=…
 *   - session, wrong role                         -> `no-access`, standalone,
 *     no redirect (PR 2 part A2 — see the module note below)
 * `allowedRoles` lists which roles may render this subtree. `next` is the
 * pathname + search the reader was trying to reach, so a successful sign-in
 * (`Login.tsx`) can carry them back to it instead of always landing on their
 * portal's root.
 *
 * PR 2 part A2 changed the wrong-role case specifically. It used to redirect
 * silently to `portalPathForRole(session.role)` — a teacher clicking a stale
 * `/school/...` link landed on `/teacher` with no explanation, which reads as
 * the link being broken rather than as the page belonging to someone else.
 * `FullPageState variant="no-access"` says so, in `frame="standalone"`
 * because this guard sits *outside* every portal layout (it wraps the whole
 * subtree, chrome included — see `routes.tsx`), so nothing has rendered a
 * `<SkipLink>`/`<main>` yet for this to collide with.
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

/**
 * The sign-in screen a role uses.
 *
 * Only `parent` differs: parents authenticate by phone + OTP at
 * `/login/parent` (G-05), not with a password, so sending one to `/login`
 * puts them in front of a form with no field they can fill in. Every other
 * role — and an unknown or absent one, `undefined` included — uses the
 * email+password form at `/login`. That undefined case is not a hole: a
 * reader with no session and no recorded expiry (`RequireAuth`'s own
 * `!session` branch, `FullPageStateBody` outside `session-ended`) was never
 * some particular role to begin with, and `/login` is the one sign-in
 * screen every role can always use, so it is the honest default rather than
 * a guess.
 *
 * SHOULD-FIX 3 (adversarial review, PR 2): a parent whose session expired
 * used to land on this same `/login` regardless of role, unconditionally,
 * because nothing upstream of it tracked which role had just been signed
 * out. `markSessionExpired`/`SessionEnded` now carry that role forward so
 * `FullPageStateBody`'s `sign-in` action can resolve through this function
 * instead.
 */
export function loginPathForRole(role: string | undefined): string {
  if (role === "parent") return "/login/parent"
  return "/login"
}

export function RequireAuth({
  allowedRoles,
  children,
}: {
  allowedRoles: readonly string[]
  children: ReactNode
}) {
  const { session } = useAuth()
  const location = useLocation()
  const currentPath = location.pathname + location.search
  // The role of a session that is present but no longer usable, or `null`
  // when this session is fine or absent — doubles as the old `stranded`
  // boolean (`strandedRole !== null`) while also giving the effect below a
  // role to hand `markSessionExpired`, which `stranded` on its own could
  // not: TS does not narrow `session` inside the effect closure just because
  // a same-render boolean derived from it happens to be true (SHOULD-FIX 3).
  const strandedRole = session !== null && !isSessionRecoverable(session) ? session.role : null

  // Drop the dead session rather than merely navigating away from it: left in
  // localStorage it would strand the user again on the next reload, and the
  // login screen has no other way to know this was an expiry rather than an
  // ordinary sign-out. Clearing it also notifies `AuthContext`, so the redirect
  // below settles onto the plain `!session` case.
  useEffect(() => {
    if (strandedRole !== null) {
      clearSession()
      markSessionExpired(strandedRole)
    }
  }, [strandedRole])

  // `strandedRole !== null` and `!session && peekSessionExpired()` both land
  // on the same screen for the same reason: either way, a session that was
  // working a moment ago just ended without the reader doing anything, and
  // that is a different — kinder — story than "you are not signed in",
  // which is what `!session` alone means for a reader who never had a
  // session this visit.
  if (strandedRole !== null || (!session && peekSessionExpired())) {
    return <Navigate to={withNext("/session-ended", currentPath)} replace />
  }
  if (!session) {
    return <Navigate to={withNext("/login", currentPath)} replace />
  }
  if (!allowedRoles.includes(session.role)) {
    return <FullPageState variant="no-access" frame="standalone" />
  }
  return children
}

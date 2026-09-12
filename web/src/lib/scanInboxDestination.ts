import { portalPathForRole } from "@/lib/auth/RequireAuth"
import { withNext } from "@/lib/nextPath"

/**
 * Where `/scan-inbox` (`routes.tsx`) lands a reader — the role-aware target
 * both the Web Share Target redirect (`sw/shareTarget.ts`) and the File
 * Handling API route point at, instead of hardcoding `/student/correct`.
 * That used to leave a teacher who shared or opened a scan on a no-access
 * page (`InstallBanner` is mounted in both the student and teacher shells,
 * but `/student/correct` is `RequireAuth`-gated to students only) while the
 * stashed file quietly expired on the 10-minute TTL.
 *
 * Student and teacher are the two portals with a real scan-upload surface
 * today (`/student/correct`, `/teacher/grading`); every other role falls
 * back to its own portal home via `portalPathForRole`, since none of them
 * has a marking/upload flow of their own to receive a shared scan.
 * `school_admin` gets `/teacher/grading` too, not its own portal home:
 * `routes.tsx`'s `TEACHER_ROLES` grants that role the teacher subtree
 * (`RequireAuth allowedRoles={TEACHER_ROLES}`), so `/teacher/grading` is a
 * real destination for it, not a no-access page — the same bug this
 * function exists to fix for `teacher` would otherwise still apply to it.
 * No session (`role: null`) falls back to `/student/correct` too — that
 * route's own `RequireAuth` guard is what actually sends a signed-out
 * reader to `/login`, the same reasoning `routes.tsx`'s old `/file-handler`
 * route comment already gave. (`ScanInbox.tsx` does not actually call this
 * function with `role: null` — see `scanInboxLandingFor` below for why —
 * but the fallback stays correct for any other caller.)
 */
export function scanInboxDestination(role: string | null): string {
  if (role === "student") return "/student/correct"
  if (role === "teacher" || role === "school_admin") return "/teacher/grading"
  if (role === null) return "/student/correct"
  return portalPathForRole(role)
}

/**
 * What `ScanInbox.tsx` actually navigates to — a session-aware wrapper
 * `scanInboxDestination` above can't be, since it only ever sees a role.
 *
 * A signed-out reader needs `/login?next=/scan-inbox`, not
 * `scanInboxDestination(null)`'s `/student/correct`: landing there directly
 * freezes `RequireAuth`'s own `next` to the *student* destination before
 * the reader's real role is known, so a teacher signing in from that link
 * gets bounced straight back to a no-access page instead of
 * `/teacher/grading`. Routing back through `/scan-inbox` itself re-resolves
 * the role on the second pass, once a session exists.
 */
export function scanInboxLandingFor(role: string | null): string {
  if (role === null) return withNext("/login", "/scan-inbox")
  return scanInboxDestination(role)
}

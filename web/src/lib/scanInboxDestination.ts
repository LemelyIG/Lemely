import { portalPathForRole } from "@/lib/auth/RequireAuth"

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
 * has a marking/upload flow of their own to receive a shared scan. No
 * session (`role: null`) falls back to `/student/correct` too — that
 * route's own `RequireAuth` guard is what actually sends a signed-out
 * reader to `/login`, the same reasoning `routes.tsx`'s old `/file-handler`
 * route comment already gave.
 */
export function scanInboxDestination(role: string | null): string {
  if (role === "student") return "/student/correct"
  if (role === "teacher") return "/teacher/grading"
  if (role === null) return "/student/correct"
  return portalPathForRole(role)
}

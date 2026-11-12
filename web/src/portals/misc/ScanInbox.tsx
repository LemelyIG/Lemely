/* Hallmark · pre-emit critique: P4 H4 E5 S4 R5 V4 */
import { Navigate } from "react-router-dom"
import { useAuth } from "@/lib/auth/AuthContext"
import { scanInboxLandingFor } from "@/lib/scanInboxDestination"

/*
 * Role-aware landing for the Web Share Target (`sw/shareTarget.ts`'s
 * redirect) and the File Handling API (`routes.tsx`'s `/file-handler`
 * route) — both used to hardcode `/student/correct`, which left a teacher
 * who shared or opened a scan on a no-access page (`InstallBanner` is
 * mounted in both portal shells, but `/student/correct` is `RequireAuth`-
 * gated to students only) while the stashed file quietly expired on its
 * 10-minute TTL.
 *
 * Deliberately outside `RequireAuth` — `scanInboxLandingFor` sends a
 * signed-out reader to `/login?next=/scan-inbox` itself, re-resolving the
 * role on the second pass through this same route after sign-in, rather
 * than freezing early to a role-specific destination (`scanInboxLandingFor`'s
 * own doc explains why that matters for a teacher).
 */
export function ScanInbox() {
  const { session } = useAuth()
  return <Navigate to={scanInboxLandingFor(session?.role ?? null)} replace />
}

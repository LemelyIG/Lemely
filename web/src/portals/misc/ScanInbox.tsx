/* Hallmark · pre-emit critique: P4 H4 E5 S4 R5 V4 */
import { Navigate } from "react-router-dom"
import { useAuth } from "@/lib/auth/AuthContext"
import { scanInboxDestination } from "@/lib/scanInboxDestination"

/*
 * Role-aware landing for the Web Share Target (`sw/shareTarget.ts`'s
 * redirect) and the File Handling API (`routes.tsx`'s `/file-handler`
 * route) — both used to hardcode `/student/correct`, which left a teacher
 * who shared or opened a scan on a no-access page (`InstallBanner` is
 * mounted in both portal shells, but `/student/correct` is `RequireAuth`-
 * gated to students only) while the stashed file quietly expired on its
 * 10-minute TTL.
 *
 * Deliberately outside `RequireAuth` — `routes.tsx`'s own registration of
 * this route explains why, the same reasoning the old `/file-handler` route
 * comment gave: `scanInboxDestination` degrades to `/student/correct` with
 * no session, and that route's own guard is what actually sends a
 * signed-out reader to `/login`.
 */
export function ScanInbox() {
  const { session } = useAuth()
  return <Navigate to={scanInboxDestination(session?.role ?? null)} replace />
}

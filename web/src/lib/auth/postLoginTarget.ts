import { safeNextPath } from "@/lib/nextPath"
import { portalPathForRole } from "@/lib/auth/RequireAuth"

/*
 * Packet B2a · where `Login.tsx` sends a reader once `login.mutate` succeeds.
 *
 * `next` — an explicit `?next=`, e.g. carried by `RequireAuth`'s own
 * redirect or a "sign in to continue" link — wins over `from`: a reader
 * bounced off a specific page wants back to that page. Failing that, `from`
 * (the `state.from` `RequireAuth` now attaches to its redirect, the location
 * it was guarding when a dead session sent the reader to `/login`) is used
 * instead. Both `next` and `from` are honoured only when they sit inside the
 * signed-in role's own portal — a teacher account signing back in from a
 * stale `/student/...` bookmark, or a crafted `?next=`/`state.from`, must
 * not land inside a different role's portal. Both are re-validated through
 * `safeNextPath` here exactly as every other reader of a `?next=`/
 * `state.from` value already does (`nextPath.ts`), since router state is
 * exactly as attacker-reachable as a query string is.
 */
export function postLoginTarget(input: {
  next: string | null
  from: unknown
  role: string
}): string {
  const { next, from, role } = input
  const portal = portalPathForRole(role)

  const safeNext = safeNextPath(next)
  if (safeNext && safeNext.startsWith(portal)) return safeNext

  const safeFrom = safeNextPath(typeof from === "string" ? from : null)
  if (safeFrom && safeFrom.startsWith(portal)) return safeFrom

  return portal
}

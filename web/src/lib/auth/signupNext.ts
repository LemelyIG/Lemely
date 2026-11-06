import { portalPathForRole } from "@/lib/auth/RequireAuth"
import type { Session } from "@/lib/auth/storage"
import { safeNextPath } from "@/lib/nextPath"

/*
 * Where to go after a new account is verified (e.g. the plan chosen on `/pricing`). Sign-up and
 * verification are separate screens, and the emailed link may open in another tab, so the
 * validated `next` is kept in localStorage for one use. It is validated with `safeNextPath` on
 * the way in and again on the way out, so a tampered value never navigates off-origin.
 */

const KEY = "lemely.signup.next"

function store(): Storage | null {
  return typeof localStorage === "undefined" ? null : localStorage
}

/** Remember a validated `next`, or clear any stale one when it is missing or rejected. */
export function rememberSignupNext(next: string | null, storage: Storage | null = store()): void {
  const safe = safeNextPath(next)
  if (safe) storage?.setItem(KEY, safe)
  else storage?.removeItem(KEY)
}

/** Read and drop the remembered `next`. */
export function takeSignupNext(storage: Storage | null = store()): string | null {
  const raw = storage?.getItem(KEY) ?? null
  storage?.removeItem(KEY)
  return safeNextPath(raw)
}

/** After verification: the remembered `next`, else today's target (`postVerifyPath`'s rule:
 * `/login` without a session, the role's portal home with one). */
export function afterVerifyPath(session: Pick<Session, "role"> | null, storage: Storage | null = store()): string {
  if (!session) return "/login"
  return takeSignupNext(storage) ?? portalPathForRole(session.role)
}

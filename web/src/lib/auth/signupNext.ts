import { portalPathForRole } from "@/lib/auth/RequireAuth"
import { SIGNUP_NEXT_KEY, type Session } from "@/lib/auth/storage"
import { safeNextPath } from "@/lib/nextPath"

/*
 * Where to go after a new account is verified (e.g. the plan chosen on `/pricing`). Sign-up and
 * verification are separate screens, and the emailed link may open in another tab, so the
 * validated `next` is kept in localStorage for one use. It is validated with `safeNextPath` on
 * the way in and again on the way out, so a tampered value never navigates off-origin.
 */

const KEY = SIGNUP_NEXT_KEY
/** A remembered `next` is only honoured for an hour: long enough to find the verification email,
 * short enough that an abandoned sign-up never reaches a later user of the same browser. */
const TTL_MS = 60 * 60 * 1000

function store(): Storage | null {
  return typeof localStorage === "undefined" ? null : localStorage
}

/** Remember a validated `next`, or clear any stale one when it is missing or rejected. */
export function rememberSignupNext(next: string | null, storage: Storage | null = store(), now: number = Date.now()): void {
  const safe = safeNextPath(next)
  if (safe) storage?.setItem(KEY, JSON.stringify({ path: safe, ts: now }))
  else storage?.removeItem(KEY)
}

/** Read and drop the remembered `next`. */
export function takeSignupNext(storage: Storage | null = store(), now: number = Date.now()): string | null {
  const raw = storage?.getItem(KEY) ?? null
  storage?.removeItem(KEY)
  if (raw === null) return null
  try {
    const parsed: unknown = JSON.parse(raw)
    if (typeof parsed !== "object" || parsed === null) return null
    const { path, ts } = parsed as { path?: unknown; ts?: unknown }
    if (typeof path !== "string" || typeof ts !== "number") return null
    if (now - ts > TTL_MS || ts > now + 60_000) return null
    return safeNextPath(path)
  } catch {
    // Old plain-string format or garbage: ignored.
    return null
  }
}

/** After verification: the remembered `next`, else today's target (`postVerifyPath`'s rule:
 * `/login` without a session, the role's portal home with one). */
export function afterVerifyPath(
  session: Pick<Session, "role"> | null,
  storage: Storage | null = store(),
  now: number = Date.now(),
): string {
  const next = takeSignupNext(storage, now)
  if (!session) return "/login"
  return next ?? portalPathForRole(session.role)
}

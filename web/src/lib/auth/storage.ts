/*
 * Local persistence for the auth device id and the current session. Both live
 * in localStorage (no server-side session store on the client) so a reload
 * keeps the user signed in and reuses the same device fingerprint across
 * logins (D1.11's 3-device-limit semantics rely on a stable device id).
 */

import { randomUuid } from "@/lib/uuid"

const DEVICE_ID_KEY = "lemely.deviceId"
const SESSION_KEY = "lemely.session"

/**
 * Return the client's device fingerprint, minting one via `randomUuid()` on
 * first use and persisting it so every subsequent call (and every login)
 * reuses the same id.
 *
 * `randomUuid`, not `crypto.randomUUID` directly: this runs on the login path
 * before a session exists, and `crypto.randomUUID` is undefined outside a
 * secure context — over plain HTTP on a non-localhost origin the bare call
 * threw and took the whole sign-in with it. See `lib/uuid.ts`.
 */
export function getDeviceId(): string {
  const existing = localStorage.getItem(DEVICE_ID_KEY)
  if (existing) return existing
  const minted = randomUuid()
  localStorage.setItem(DEVICE_ID_KEY, minted)
  return minted
}

export interface Session {
  accessToken: string
  refreshToken: string | null
  userId: string
  role: string
}

/** Read the persisted session, or `null` if absent or unparseable. */
export function getSession(): Session | null {
  const raw = localStorage.getItem(SESSION_KEY)
  if (!raw) return null
  try {
    return JSON.parse(raw) as Session
  } catch {
    return null
  }
}

type SessionListener = (session: Session | null) => void

const listeners = new Set<SessionListener>()

/**
 * Observe session changes, returning an unsubscribe function.
 *
 * `lib/api.ts` writes here too — it stores a silently-refreshed token, and
 * clears the session when a refresh is refused — and it has no way to reach
 * React state. Without this, a session dropped mid-request left `AuthContext`
 * still holding the dead one, so the route guard kept rendering a portal in
 * which every single request failed.
 */
export function subscribeToSession(listener: SessionListener): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

function notify(session: Session | null): void {
  for (const listener of listeners) listener(session)
}

/** Persist the session (JSON-serialized) for subsequent requests/reloads. */
export function setSession(session: Session): void {
  localStorage.setItem(SESSION_KEY, JSON.stringify(session))
  notify(session)
}

/**
 * Drop the persisted session.
 *
 * Covers both a deliberate sign-out and `RequireAuth`/`api.ts` dropping a
 * dead one — but only a deliberate sign-out reaches here with the expiry
 * flag still unset. A dropped-dead session always calls `markSessionExpired`
 * in the same breath as this (see both call sites), so clearing the flag
 * here is never in tension with recording it: whichever of the two runs
 * second is what the flag ends up saying. Without this, a reader who signs
 * out, then later opens a portal URL directly, would still see "you were
 * signed out to keep your account safe" — a stale flag from an expiry that
 * may have happened tabs or days earlier, describing a sign-out that this
 * reader chose themselves (SHOULD-FIX 4).
 */
export function clearSession(): void {
  localStorage.removeItem(SESSION_KEY)
  notify(null)
  expiredSignal = false
  expiredRole = undefined
}

/*
 * Whether the session that just ended did so because it expired, rather than
 * because the user chose to sign out — the difference between "Signed out" and
 * "Your session expired, please sign in again", which is the whole point of
 * telling them. Deliberately in memory rather than storage: it describes this
 * navigation only, and a stale flag surfacing on a later visit would be a lie.
 */
let expiredSignal = false

/**
 * The role of the session that just expired, alongside `expiredSignal`.
 *
 * `undefined` either because nothing has expired, or because the caller did
 * not pass one — `role` is an optional parameter on `markSessionExpired`
 * precisely so a caller with no role in hand (or, as of this fix, one this
 * PR's scope did not touch — `api.ts`'s silent-refresh-refusal call site
 * still calls it bare; see that call site for why) keeps compiling and
 * behaving exactly as before. `loginPathForRole` treats an unknown role the
 * same as any other it does not recognise: the email+password form, which is
 * the only sign-in screen a reader can always use regardless of which role
 * they were.
 */
let expiredRole: string | undefined

/** Record that the session ended by expiry (called when a refresh is
 * refused, or when `RequireAuth` finds a stranded session on mount), and
 * which role it belonged to when the caller knows it. */
export function markSessionExpired(role?: string): void {
  expiredSignal = true
  expiredRole = role
}

/** `takeSessionExpired`/`peekSessionExpired`'s shared read shape: whether a
 * session just expired, and the role it belonged to (if known). */
export interface SessionExpiry {
  expired: boolean
  role: string | undefined
}

/** Read and clear the expiry flag (and the role recorded alongside it), so
 * the notice shows once. */
export function takeSessionExpired(): SessionExpiry {
  const expiry: SessionExpiry = { expired: expiredSignal, role: expiredRole }
  expiredSignal = false
  expiredRole = undefined
  return expiry
}

/**
 * Read the expiry flag (and role) without clearing it.
 *
 * Two readers need two different reads of the same bit. `SessionEnded` and
 * `Login.tsx` both want `takeSessionExpired`: each reads once on mount to
 * pick up the role and decide whether to show the notice, and must consume
 * the flag so a later remount (its own, or the other screen's, whichever a
 * reader reaches second) does not show it a second time for the same
 * expiry. `RequireAuth` cannot use that same consuming read — it renders on
 * every navigation inside a guarded subtree, not once, and it is asking a
 * different question ("did `api.ts`'s silent refresh just get refused,
 * mid-session, on this very render?") than either screen's "show the notice
 * now, on the screen built to say so". Taking the flag there would clear it
 * before the reader ever reaches `/session-ended` or `/login` to see it —
 * `peekSessionExpired` lets `RequireAuth` route a dead session to
 * `/session-ended` without deciding, on its behalf, that the flag has been
 * shown.
 */
export function peekSessionExpired(): boolean {
  return expiredSignal
}

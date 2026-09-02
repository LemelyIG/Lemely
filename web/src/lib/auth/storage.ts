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

/** Drop the persisted session (logout). */
export function clearSession(): void {
  localStorage.removeItem(SESSION_KEY)
  notify(null)
}

/*
 * Whether the session that just ended did so because it expired, rather than
 * because the user chose to sign out — the difference between "Signed out" and
 * "Your session expired, please sign in again", which is the whole point of
 * telling them. Deliberately in memory rather than storage: it describes this
 * navigation only, and a stale flag surfacing on a later visit would be a lie.
 */
let expiredSignal = false

/** Record that the session ended by expiry (called when a refresh is refused). */
export function markSessionExpired(): void {
  expiredSignal = true
}

/** Read and clear the expiry flag, so the notice shows once. */
export function takeSessionExpired(): boolean {
  const expired = expiredSignal
  expiredSignal = false
  return expired
}

/**
 * Read the expiry flag without clearing it.
 *
 * Two readers need two different reads of the same bit. `Login.tsx` wants
 * `takeSessionExpired`: it reads once on mount to decide whether to show
 * "Your session expired", and must consume the flag so a later remount does
 * not show the notice a second time for the same expiry. `RequireAuth`
 * cannot use that same consuming read — it renders on every navigation
 * inside a guarded subtree, not once, and it is asking a different question
 * ("did `api.ts`'s silent refresh just get refused, mid-session, on this
 * very render?") than Login's "should I show the notice right now". Taking
 * the flag there would clear it before the reader ever reaches `/login` to
 * see it — `peekSessionExpired` lets `RequireAuth` route a dead session to
 * `/session-ended` without deciding, on its behalf, that the flag has been
 * shown.
 */
export function peekSessionExpired(): boolean {
  return expiredSignal
}

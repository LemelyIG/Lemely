/*
 * Local persistence for the auth device id and the current session. Both live
 * in localStorage (no server-side session store on the client) so a reload
 * keeps the user signed in and reuses the same device fingerprint across
 * logins (D1.11's 3-device-limit semantics rely on a stable device id).
 */

const DEVICE_ID_KEY = "lemely.deviceId"
const SESSION_KEY = "lemely.session"

/**
 * Return the client's device fingerprint, minting one via `crypto.randomUUID()`
 * on first use and persisting it so every subsequent call (and every login)
 * reuses the same id.
 */
export function getDeviceId(): string {
  const existing = localStorage.getItem(DEVICE_ID_KEY)
  if (existing) return existing
  const minted = crypto.randomUUID()
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

/** Persist the session (JSON-serialized) for subsequent requests/reloads. */
export function setSession(session: Session): void {
  localStorage.setItem(SESSION_KEY, JSON.stringify(session))
}

/** Drop the persisted session (logout). */
export function clearSession(): void {
  localStorage.removeItem(SESSION_KEY)
}

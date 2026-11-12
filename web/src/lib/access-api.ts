/**
 * The pre-launch access gate: the public "is sign-in restricted?" call and the recogniser for the
 * `access_restricted` refusal.
 *
 * While Lemely is not launched, only verified accounts on the allow-listed email domain can sign
 * up, sign in or call an authenticated route (`lemely/web/deps.py` `get_auth_context`,
 * `lemely/auth/service.py`). Everyone else is answered `403` with
 * `{"detail": {"code": "access_restricted", "reason": "domain" | "unverified"}}`. The server never
 * names the allowed domains, and neither does this module.
 *
 * `getAccessConfig` is a plain fetch, not `request` from `@/lib/api`: the visitor is signed out,
 * and that helper attaches a bearer token, refreshes it on 401 and can end the session (the same
 * reason `waitlist-api.ts` makes its public calls this way). `isAccessRestricted` reads the
 * `ApiError` that `request` throws, so it works on any authenticated call's failure.
 */

import { ApiError } from '@/lib/api'
import { matchAccessRestricted, setAccessRestrictedHandler, type AccessRestrictedReason } from '@/lib/accessRestricted'

export { setAccessRestrictedHandler }

/** The react-query key for `getAccessConfig`. */
export const ACCESS_CONFIG_QUERY_KEY = ['access', 'config'] as const

/** `GET /api/access/config`: `restricted` is true while the server holds an allow-list. */
export interface AccessConfig {
  restricted: boolean
}

/** Thrown by `getAccessConfig` on a network failure (`status` 0) or any non-2xx answer. */
export class AccessConfigError extends Error {
  status: number

  constructor(status: number) {
    super(`Access config request failed with status ${status}`)
    this.name = 'AccessConfigError'
    this.status = status
  }
}

/**
 * Whether sign-in is restricted right now. While `restricted` is true, show the "coming soon"
 * screen instead of a signup or login form. Not cacheable (a deploy flips it), so the server
 * answers `Cache-Control: no-store`. On a failure the caller chooses what to show; the server still
 * enforces the gate either way.
 */
export async function getAccessConfig(): Promise<AccessConfig> {
  let res: Response
  try {
    res = await fetch('/api/access/config', { headers: { Accept: 'application/json' } })
  } catch {
    throw new AccessConfigError(0)
  }
  if (!res.ok) throw new AccessConfigError(res.status)
  const body = (await res.json()) as Partial<AccessConfig> | null
  return { restricted: body?.restricted === true }
}

/** Why the server refused: `domain` (not an allowed address) or `unverified` (allowed, inbox not proven). */
export type { AccessRestrictedReason }

/** The `detail` of an access refusal. */
export interface AccessRestrictedDetail {
  code: 'access_restricted'
  reason: AccessRestrictedReason
}

/** Narrow an `ApiError.detail` onto the access refusal marker (an object, never a sentence). */
export function isAccessRestrictedDetail(detail: unknown): detail is AccessRestrictedDetail {
  if (typeof detail !== 'object' || detail === null) return false
  return (detail as Partial<AccessRestrictedDetail>).code === 'access_restricted'
}

/** True when `error` is the server's `403 access_restricted`, from any authenticated or auth call. */
export function isAccessRestricted(error: unknown): boolean {
  return error instanceof ApiError && matchAccessRestricted(error.status, error.detail, error.body) !== null
}

/** The refusal's reason, or `null` when `error` is not an access refusal (or names no known reason). */
export function accessRestrictedReason(error: unknown): AccessRestrictedReason | null {
  if (!isAccessRestricted(error)) return null
  const { detail, body } = error as ApiError
  const reason = (detail as Partial<AccessRestrictedDetail> | undefined)?.reason ?? (body as Partial<AccessRestrictedDetail> | undefined)?.reason
  return reason === 'domain' || reason === 'unverified' ? reason : null
}

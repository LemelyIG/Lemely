/**
 * The 403 `access_restricted` refusal as seen by the transport layer, and the one handler that
 * reacts to it.
 *
 * Kept free of imports from `api.ts` (which calls into this module on every non-OK path) so the
 * two do not form a cycle; `access-api.ts` builds the `ApiError`-aware helpers on top.
 *
 * The server's shape is `{"detail": {"code": "access_restricted", "reason": "domain" | "unverified"}}`.
 * A top-level `code` is accepted as well, in case a proxy or a later backend flattens it.
 */

export type AccessRestrictedReason = "domain" | "unverified"

export interface AccessRestrictedInfo {
  /** `unverified`: an allowed address whose inbox is not proven yet. Anything else counts as `domain`. */
  reason: AccessRestrictedReason
}

const CODE = "access_restricted"

function codeOf(value: unknown): { code?: unknown; reason?: unknown } | null {
  return typeof value === "object" && value !== null ? (value as { code?: unknown; reason?: unknown }) : null
}

/** Recognises the refusal from a response's status plus its parsed `detail` and whole `body`. */
export function matchAccessRestricted(status: number, detail: unknown, body?: unknown): AccessRestrictedInfo | null {
  if (status !== 403) return null
  const fromDetail = codeOf(detail)
  const fromBody = codeOf(body)
  const hit = fromDetail?.code === CODE ? fromDetail : fromBody?.code === CODE ? fromBody : null
  if (!hit) return null
  return { reason: hit.reason === "unverified" ? "unverified" : "domain" }
}

type Handler = (info: AccessRestrictedInfo) => void
let handler: Handler | null = null
const lastFired: Partial<Record<AccessRestrictedReason, number>> = {}

/** Register (or clear, with `null`) the one reaction to a refusal. `main.tsx` owns it. */
export function setAccessRestrictedHandler(fn: Handler | null): void {
  handler = fn
}

/**
 * Called by every non-OK path in `api.ts` except the sign-in/sign-up forms (`/auth/*`, which show
 * the refusal inline). Fires the handler at most once per burst and per reason, because a
 * screenful of queries is refused together; a later refusal after the window fires again. Keyed on
 * the reason so an `unverified` refusal never swallows a `domain` cut-off that follows it.
 */
export function reportAccessRestricted(status: number, detail: unknown, body?: unknown, now: number = Date.now()): void {
  const info = matchAccessRestricted(status, detail, body)
  if (!info || !handler) return
  const last = lastFired[info.reason]
  if (last !== undefined && now - last < 2000) return
  lastFired[info.reason] = now
  handler(info)
}

/** Test seam: forget the burst windows. */
export function resetAccessRestrictedBurst(): void {
  delete lastFired.domain
  delete lastFired.unverified
}

/*
 * Read-only inspection of a token's `exp` claim, client-side.
 *
 * The signature is emphatically NOT checked here and must never be treated as
 * if it were — the server is the only thing that decides whether a token is
 * valid. This exists purely so the SPA can answer "is it even worth sending?"
 * and "can this session still be recovered?" without a round trip that is
 * guaranteed to come back 401.
 */

/** Decode a JWT's payload without verifying it, or `null` if it isn't one. */
function payloadOf(token: string): Record<string, unknown> | null {
  const segment = token.split(".")[1]
  if (!segment) return null
  try {
    // base64url -> base64, re-padded: `atob` rejects an unpadded string.
    const base64 = segment.replace(/-/g, "+").replace(/_/g, "/")
    const padded = base64.padEnd(base64.length + ((4 - (base64.length % 4)) % 4), "=")
    // Via bytes rather than `atob` straight into JSON.parse, so a non-ASCII
    // claim (an accented email, say) decodes as UTF-8 instead of mojibake.
    const bytes = Uint8Array.from(atob(padded), (ch) => ch.charCodeAt(0))
    const parsed: unknown = JSON.parse(new TextDecoder().decode(bytes))
    return parsed && typeof parsed === "object" ? (parsed as Record<string, unknown>) : null
  } catch {
    return null
  }
}

/** The token's expiry in epoch milliseconds, or `null` if it declares none. */
export function tokenExpiresAt(token: string): number | null {
  const exp = payloadOf(token)?.exp
  return typeof exp === "number" ? exp * 1000 : null
}

/**
 * Seconds of slack applied when judging expiry. A token that dies while in
 * flight is indistinguishable to the user from one that was dead on arrival, so
 * we treat the last half-minute as already gone and refresh early.
 */
const CLOCK_SKEW_SECONDS = 30

/**
 * Whether `token` is expired (or about to be), erring towards "yes".
 *
 * A token carrying no readable `exp` counts as **not** expired: it may be a
 * shape we don't understand, and the server — which actually verifies it — gets
 * the final say. Guessing "expired" here would throw away a working session.
 */
export function isTokenExpired(token: string, now: number = Date.now()): boolean {
  const expiresAt = tokenExpiresAt(token)
  if (expiresAt === null) return false
  return expiresAt - CLOCK_SKEW_SECONDS * 1000 <= now
}

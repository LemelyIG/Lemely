/*
 * PR 2 part A2 · the `?next=` open-redirect guard.
 *
 * `RequireAuth` (a dead session), `SessionEnded.tsx` and `Login.tsx` all want
 * to carry a reader back to the page they were on before they had to sign in
 * again — and all three read that destination from somewhere an attacker also
 * controls: a query parameter, echoed straight off the URL bar. Handing that
 * value to `<Navigate>` or `navigate()` unchecked would let a crafted link
 * ("sign in, then we'll take you to https://evil.example") use this product's
 * own auth flow to redirect a reader off it entirely after they type their
 * real password.
 *
 * `safeNextPath` is the allowlist: a same-origin, absolute path, and nothing
 * else. It does not attempt to sanitise a bad value into a good one — a
 * `raw` that fails any check is rejected outright, because a same-origin path
 * is the only shape this app ever legitimately needs to return to.
 */

const MAX_LENGTH = 500

/** True where `code` is a control character or plain space — every one of
 * which some browser, at some point, has been observed to treat as
 * insignificant leading noise before a URL's real scheme, which is exactly
 * how `" javascript:alert(1)"` or a tab-hidden scheme sneaks past a naive
 * `startsWith("/")` check. Rejecting any control character or space anywhere
 * in the value, not only at the start, is the cheaper and more honest rule:
 * a legitimate in-app path never contains one. */
function isWhitespaceOrControl(code: number): boolean {
  return code <= 0x20 || code === 0x7f
}

/**
 * Accepts only a same-origin absolute path a reader could legitimately have
 * been on: starts with a single `/`, not `//` (a protocol-relative URL — the
 * browser resolves `//evil.example/x` against the *current scheme*, landing
 * on a different origin) and not `/\` (some browsers normalise a leading
 * backslash to a second forward slash, so `/\evil.example` is the same attack
 * spelled to dodge the `//` check). No scheme, since anything not starting
 * with `/` is rejected outright — `https://evil.example` and
 * `javascript:alert(1)` both fail the very first check. No whitespace or
 * control characters, and a 500-character ceiling generous enough for any
 * real in-app path with a query string, and no reason to carry more.
 *
 * Returns `raw` verbatim when it passes — nothing is stripped or rewritten,
 * since a value that needed rewriting to become safe was not safe to begin
 * with.
 */
export function safeNextPath(raw: string | null): string | null {
  if (raw === null) return null
  if (raw.length === 0 || raw.length > MAX_LENGTH) return null
  if (!raw.startsWith("/")) return null
  if (raw.startsWith("//")) return null
  if (raw.startsWith("/\\")) return null

  for (let i = 0; i < raw.length; i++) {
    if (isWhitespaceOrControl(raw.charCodeAt(i))) return null
  }

  return raw
}

/**
 * Append `next` (already validated by `safeNextPath`, or freshly minted from
 * a known-safe in-app pathname) to `base` as an encoded `?next=` query
 * parameter. Returns `base` unchanged when `next` is `null` — every caller of
 * this function already has a plain `base` to fall back to, so there is
 * nothing to append a bare `?next=` with no value onto.
 */
export function withNext(base: string, next: string | null): string {
  if (next === null) return base
  return `${base}?next=${encodeURIComponent(next)}`
}

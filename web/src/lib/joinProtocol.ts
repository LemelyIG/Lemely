/*
 * Parses the `code` param `/join/:code` (`routes.tsx`) receives.
 *
 * `vite/manifest.ts`'s `protocol_handlers` registers `web+lemely` as this
 * app's own URI scheme, resolving `web+lemely://join/<code>` to
 * `/join/%s` — and per the Web Application Manifest spec, `%s` is filled
 * with the *whole* invoked URL (URL-encoded), not just the trailing code
 * segment. So when the OS launches this app from a `web+lemely://join/...`
 * link, `JoinWithCode.tsx`'s `useParams<{ code }>().code` receives the full
 * scheme URL as the `:code` segment, not a bare code — the same field a
 * normal `/join/ABC123` navigation fills with a bare code. This is the one
 * function that tells the two apart, so `JoinWithCode.tsx` needs no
 * awareness of the protocol handler at all.
 */

const PROTOCOL_PREFIX = "web+lemely://join/"

/** A bare invite code, or the code embedded in a `web+lemely://join/<code>` URL. */
export function parseJoinCode(input: string): string {
  if (!input.startsWith(PROTOCOL_PREFIX)) return input
  const encoded = input.slice(PROTOCOL_PREFIX.length)
  try {
    return decodeURIComponent(encoded)
  } catch {
    return encoded
  }
}

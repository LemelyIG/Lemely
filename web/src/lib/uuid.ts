/*
 * A UUID mint that works outside a secure context.
 *
 * `crypto.randomUUID` is gated on `isSecureContext` — it exists on https:// and
 * on http://localhost, and is simply absent everywhere else. Serving the SPA
 * over plain HTTP on any other origin (a LAN IP, a `*.local` hostname, a
 * tunnel) therefore turns `crypto.randomUUID()` into a TypeError, and
 * `getDeviceId` is on the login path: the first thing a fresh browser profile
 * does when signing in is mint a device id, so the whole sign-in died with
 * "crypto.randomUUID is not a function" rendered as the form's error. Some
 * older in-app webviews are missing the method for the same reason even on
 * https.
 *
 * `crypto.getRandomValues`, unlike `randomUUID` and `crypto.subtle`, is NOT
 * secure-context-gated, so the RFC 4122 v4 layout below is a real
 * cryptographic UUID in exactly the environments that lack the one-liner.
 * `CameraCapture` already carried its own inline `typeof crypto` guard for
 * this; both call sites now share this helper rather than growing a third
 * private copy (the `initialsOf` lesson from P3.7 chunk c).
 */

/** Format 16 bytes as the canonical 8-4-4-4-12 hyphenated hex string. */
function formatUuid(bytes: Uint8Array): string {
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("")
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}

/**
 * Return a random RFC 4122 version-4 UUID, by whichever of the three routes the
 * host actually supports: `crypto.randomUUID` when present, else
 * `crypto.getRandomValues` (available in insecure contexts too), else
 * `Math.random` as a last resort.
 *
 * The `Math.random` tier is NOT cryptographically random and is only reachable
 * on a host with no Web Crypto at all. Both current callers — the device
 * fingerprint and a React list key — need uniqueness, not unguessability; the
 * device id is a slot label the server matches against, never a credential
 * (`client_device_id` is an unvalidated nullable string column, and the session
 * itself is the bearer token). Do not reach for this function for anything that
 * must be unguessable.
 */
export function randomUuid(): string {
  const webCrypto = typeof globalThis.crypto === "undefined" ? undefined : globalThis.crypto

  if (typeof webCrypto?.randomUUID === "function") return webCrypto.randomUUID()

  const bytes = new Uint8Array(16)
  if (typeof webCrypto?.getRandomValues === "function") {
    webCrypto.getRandomValues(bytes)
  } else {
    for (let i = 0; i < bytes.length; i++) bytes[i] = Math.floor(Math.random() * 256)
  }
  // Version 4 in the high nibble of byte 6, RFC 4122 variant in the top two
  // bits of byte 8 — the two fields `randomUUID` would have set itself.
  bytes[6] = (bytes[6] & 0x0f) | 0x40
  bytes[8] = (bytes[8] & 0x3f) | 0x80
  return formatUuid(bytes)
}

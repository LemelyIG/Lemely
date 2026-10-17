/*
 * Client-side validation for a profile-picture upload (Profile settings
 * screen), mirroring the limits `POST /me/avatar` enforces server-side.
 *
 * Pure and framework-free, the same shape as `notificationPrefs.ts`'s
 * validators, so vitest can drive it directly — `vitest.config.ts` runs in
 * `environment: "node"`, so `ProfileSettingsSection` itself is not mountable
 * in a unit test and the decision worth pinning has to live outside it. This
 * check exists to give the reader a fast, specific answer before a bad file
 * ever leaves the browser; the server remains the actual authority and
 * re-validates on its own, since a client check can always be bypassed.
 */

/** The three image types the upload accepts. `POST /me/avatar` rejects
 * anything else with a 415. */
export const ALLOWED_AVATAR_TYPES = ["image/png", "image/jpeg", "image/webp"] as const

/** 5 MiB, matching the backend's own limit. A file at exactly this size is
 * accepted — only strictly larger is rejected. */
export const MAX_AVATAR_BYTES = 5 * 1024 * 1024

/**
 * Check a candidate file against the type and size limits.
 *
 * Takes `{ type, size }` rather than a `File` so a test can pass a plain
 * object with no `File`/`Blob` polyfill needed under Node.
 *
 * Returns the user-facing sentence to show when the file is rejected, or
 * `null` when it passes both checks.
 */
export function validateAvatarFile(file: { type: string; size: number }): string | null {
  if (!ALLOWED_AVATAR_TYPES.includes(file.type as (typeof ALLOWED_AVATAR_TYPES)[number])) {
    return "Choose a PNG, JPEG, or WEBP picture."
  }
  if (file.size > MAX_AVATAR_BYTES) {
    return "That picture is too large. Choose one under 5 MB."
  }
  return null
}

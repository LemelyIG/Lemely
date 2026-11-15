/*
 * The platform for the native phone frame (brief §3.7). The only resolver is
 * `public/shell-init.js` (ES5, runs before first paint) and it writes
 * `html[data-platform]`; this module just reads that attribute back.
 * tests/unit/platform.test.ts drives shell-init.js directly.
 */
export type Platform = "ios" | "android" | "other"

export function readPlatform(): Platform {
  if (typeof document === "undefined") return "other"
  const value = document.documentElement.dataset.platform
  return value === "ios" || value === "android" ? value : "other"
}

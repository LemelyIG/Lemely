/*
 * One boot-time platform answer for the native phone frame (brief §3.7).
 * `public/shell-init.js` runs the same table in ES5 before first paint and
 * writes `html[data-platform]`; this module is the typed twin, pinned against
 * it by tests/unit/platform.test.ts. UA-CH only decides "Android" (Safari has
 * no UA-CH, and an emulated UA on a Linux host still reports "Linux"); the UA
 * string decides the rest. iPadOS sends a Mac UA, so Mac + touch is iOS.
 */
export type Platform = "ios" | "android" | "other"

export interface PlatformInput {
  uaDataPlatform?: string | null
  userAgent: string
  maxTouchPoints: number
}

export function resolvePlatform({ uaDataPlatform, userAgent, maxTouchPoints }: PlatformInput): Platform {
  if (uaDataPlatform === "Android") return "android"
  if (/\b(iPhone|iPad|iPod)\b/.test(userAgent)) return "ios"
  if (/\bMacintosh\b/.test(userAgent) && maxTouchPoints > 1) return "ios"
  if (/\bAndroid\b/.test(userAgent)) return "android"
  return "other"
}

export function readPlatform(): Platform {
  if (typeof document === "undefined") return "other"
  const value = document.documentElement.dataset.platform
  return value === "ios" || value === "android" ? value : "other"
}

import { createContext, createElement, useContext, useSyncExternalStore, type ReactNode } from "react"
import { readPlatform, type Platform } from "@/lib/platform"

/** The shell-sm edge (`--breakpoint-shell-sm: 721px`), as a media query. */
export const PHONE_MEDIA = "(max-width: 720px)"

export interface NativeFrame {
  platform: Platform
  phone: boolean
  native: boolean
}

export function isNativeFrame(platform: Platform, phone: boolean): boolean {
  return phone && platform !== "other"
}

const Override = createContext<NativeFrame | null>(null)

/** Tests and harness only: force a frame without a DOM. */
export function NativeFrameProvider({ value, children }: { value: NativeFrame; children: ReactNode }) {
  return createElement(Override.Provider, { value }, children)
}

function subscribe(onChange: () => void): () => void {
  const media = window.matchMedia(PHONE_MEDIA)
  media.addEventListener("change", onChange)
  return () => media.removeEventListener("change", onChange)
}

/**
 * The one JS switch for markup that differs on the native frame (sheets).
 * Styling differences use the `native:`/`ios:`/`android:` variants instead.
 */
export function useNativeFrame(): NativeFrame {
  const forced = useContext(Override)
  const phone = useSyncExternalStore(
    subscribe,
    () => window.matchMedia(PHONE_MEDIA).matches,
    () => false,
  )
  if (forced) return forced
  const platform = readPlatform()
  return { platform, phone, native: isNativeFrame(platform, phone) }
}

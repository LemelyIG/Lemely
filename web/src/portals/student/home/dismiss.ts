/*
 * "Not now" memory. A per-viewer convenience, so browser storage is right:
 * it may come back empty (private window, cleared data) and Home still works,
 * Binny just suggests the same thing again. Keys reset each new local day.
 */
export const DISMISS_KEY = "lemely.home.notNow"

type Reader = Pick<Storage, "getItem">
type Writer = Pick<Storage, "setItem">

export function safeLocalStorage(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage
  } catch {
    return null
  }
}

export function readDismissed(storage: Reader | null, day: string): Set<string> {
  if (!storage) return new Set()
  try {
    const raw = storage.getItem(DISMISS_KEY)
    if (!raw) return new Set()
    const parsed = JSON.parse(raw) as { day?: unknown; keys?: unknown }
    if (parsed.day !== day || !Array.isArray(parsed.keys)) return new Set()
    return new Set(parsed.keys.filter((k): k is string => typeof k === "string"))
  } catch {
    return new Set()
  }
}

export function writeDismissed(storage: Writer | null, day: string, keys: ReadonlySet<string>): void {
  if (!storage) return
  try {
    storage.setItem(DISMISS_KEY, JSON.stringify({ day, keys: [...keys] }))
  } catch {
    // Storage full or blocked: the dismissal lasts until the page reloads.
  }
}

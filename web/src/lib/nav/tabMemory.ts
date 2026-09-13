import { useSyncExternalStore } from "react"
import { useLocation } from "react-router-dom"
import { TAB_ROOTS } from "./scrollRestorationKey"

/*
 * Packet B3 (Task 4) · per-tab UI memory (a filter, an expanded section) to
 * go alongside `scrollRestorationKey.ts`'s scroll memory: switching from
 * Overview to Classes and back to Overview is the same screen, and both
 * kinds of "where the reader left off" should survive the round trip the
 * same way. `TAB_ROOTS` is the one shared definition of "which pathnames are
 * a tab" — imported from `scrollRestorationKey.ts` rather than duplicated,
 * so the two memories can never disagree about what counts as a tab.
 */

/** The tab-root pathname `pathname` belongs to, or `null` if it is not
 * itself a tab root (a drilldown reached *from* a tab, e.g.
 * `/student/subject/9709`, does not share its parent tab's memory). */
export function tabRoot(pathname: string, tabRoots: ReadonlySet<string> = TAB_ROOTS): string | null {
  return tabRoots.has(pathname) ? pathname : null
}

const store = new Map<string, unknown>()
const listeners = new Set<() => void>()

function notify(): void {
  for (const listener of listeners) listener()
}

function subscribe(onStoreChange: () => void): () => void {
  listeners.add(onStoreChange)
  return () => listeners.delete(onStoreChange)
}

/**
 * Like `useState`, but backed by a module-level `Map` keyed by the current
 * tab root plus `key` — so the value survives switching away to another tab
 * and back, the same way the browser's own scroll restoration does for
 * scroll position. Falls back to `location.pathname` for a screen that is
 * not itself a tab root, which gives it ordinary per-screen persistence
 * (survives a re-render, not a navigation away) rather than sharing another
 * screen's slot.
 */
export function useTabState<T>(key: string, initial: T): [T, (next: T) => void] {
  const location = useLocation()
  const storeKey = `${tabRoot(location.pathname) ?? location.pathname}:${key}`

  const value = useSyncExternalStore(subscribe, () =>
    store.has(storeKey) ? (store.get(storeKey) as T) : initial,
  )

  function setValue(next: T): void {
    store.set(storeKey, next)
    notify()
  }

  return [value, setValue]
}

/** Called on sign-out — a signed-out-then-signed-in-as-someone-else session
 * must not inherit the previous account's filters/expanded sections. */
export function clearTabMemory(): void {
  store.clear()
  notify()
}

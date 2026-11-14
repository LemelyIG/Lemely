/*
 * Native frame Task 12b · the previous page, kept as an inert clone so an edge swipe-back can
 * show it under the moving column (iOS shows the live previous screen there). Snapshots live in a
 * small LRU keyed by `history.state.idx`.
 *
 * Capture happens after a page has settled (and again just before a link click leaves it),
 * because React has already swapped the DOM by the time any layout effect of the new location runs.
 */

/** Entries kept. Five screens back is further than a thumb swipes in one sitting. */
export const SNAPSHOT_LIMIT = 5
/** A column with more elements than this is not cloned: the ground shows instead. */
export const SNAPSHOT_NODE_CAP = 3000

export interface PageSnapshot {
  /** The detached, sanitised copy of the column. */
  node: HTMLElement
  /** The document scroll offset the page was left at. */
  scrollY: number
}

export interface SnapshotStore<T> {
  get(idx: number): T | undefined
  set(idx: number, value: T): void
  delete(idx: number): void
  /** Drop every entry at or beyond `idx` (a push overwrites the forward history). */
  dropFrom(idx: number): void
  clear(): void
  keys(): number[]
}

/** A least-recently-used map keyed by history index. */
export function createSnapshotStore<T>(limit: number = SNAPSHOT_LIMIT): SnapshotStore<T> {
  const map = new Map<number, T>()
  return {
    get(idx) {
      const value = map.get(idx)
      if (value === undefined) return undefined
      map.delete(idx)
      map.set(idx, value)
      return value
    },
    set(idx, value) {
      map.delete(idx)
      map.set(idx, value)
      while (map.size > limit) {
        const oldest = map.keys().next().value
        if (oldest === undefined) break
        map.delete(oldest)
      }
    },
    delete(idx) {
      map.delete(idx)
    },
    dropFrom(idx) {
      for (const key of [...map.keys()]) if (key >= idx) map.delete(key)
    },
    clear() {
      map.clear()
    },
    keys() {
      return [...map.keys()]
    },
  }
}

/** Canvases bigger than this (in pixels) are left blank rather than encoded. */
const CANVAS_PIXEL_CAP = 1_000_000
/** Elements that are dropped from a clone: nothing may play, load or run inside a parked page. */
const LIVE_MEDIA = new Set(["video", "audio", "iframe", "embed", "object", "script"])
/** Attributes removed from every cloned element: duplicate ids, focus entry points, and form
 * names (a cloned radio would otherwise join, and uncheck, a real radio group). */
const STRIPPED_ATTRS = ["id", "autofocus", "name", "tabindex", "data-shell-column"]

/** Thrown from the copy when the column has more elements than the cap. */
export class SnapshotCapExceeded extends Error {}

interface CopyState {
  count: number
  cap: number
}

/**
 * One pass over `src`: counts, clones and sanitises together, and stops (throws
 * `SnapshotCapExceeded`) the moment the count passes the cap, so an oversized page costs at most
 * `cap` elements of work. Returns null for an element that is dropped (live media).
 */
export function copyElement(src: Element, state: CopyState): Element | null {
  const tag = src.localName
  if (LIVE_MEDIA.has(tag)) return null
  state.count += 1
  if (state.count > state.cap) throw new SnapshotCapExceeded()
  let copy: Element | null = null
  if (tag === "canvas") copy = canvasToImage(src as HTMLCanvasElement)
  if (!copy) {
    copy = src.cloneNode(false) as Element
    for (const attr of STRIPPED_ATTRS) copy.removeAttribute(attr)
    for (const child of Array.from(src.childNodes)) {
      if (child.nodeType === 1) {
        const inner = copyElement(child as Element, state)
        if (inner) copy.appendChild(inner)
      } else if (child.nodeType === 3) {
        copy.appendChild(child.cloneNode(false))
      }
    }
  }
  return copy
}

/** A canvas clone is blank, so a small, readable canvas becomes an image of its current pixels. */
function canvasToImage(source: HTMLCanvasElement): Element | null {
  if (source.width * source.height > CANVAS_PIXEL_CAP) return null
  try {
    const img = document.createElement("img")
    img.src = source.toDataURL()
    img.className = source.className
    const style = source.getAttribute("style")
    if (style) img.setAttribute("style", style)
    return img
  } catch {
    // A tainted canvas cannot be read: it stays a blank clone.
    return null
  }
}

/** Clone `column` into a detached, inert copy, or null when it is too large to be worth holding. */
export function captureColumn(column: HTMLElement, scrollY: number, cap: number = SNAPSHOT_NODE_CAP): PageSnapshot | null {
  let node: Element | null
  try {
    node = copyElement(column, { count: 0, cap })
  } catch (error) {
    if (error instanceof SnapshotCapExceeded) return null
    throw error
  }
  if (!node) return null
  node.setAttribute("aria-hidden", "true")
  node.setAttribute("inert", "")
  return { node: node as HTMLElement, scrollY }
}

export interface SessionLike {
  userId: string
}

/**
 * Snapshots are one user's pages, held in memory: they must not outlive the session. Clears the
 * store when the session ends or the signed-in user changes; a silent token refresh (same user)
 * keeps them. Returns the unsubscribe.
 */
export function watchSessionForSnapshots(
  subscribe: (listener: (session: SessionLike | null) => void) => () => void,
  store: Pick<SnapshotStore<unknown>, "clear">,
  initialUserId: string | null,
): () => void {
  let current = initialUserId
  return subscribe((session) => {
    const next = session?.userId ?? null
    if (next !== current) store.clear()
    current = next
  })
}

/**
 * What a `navigate(to, options)` call means for the snapshot of the page being left: a push
 * clones it; a replace swaps the page at the same history index, so that index's old copy is
 * dropped; a numeric delta (back or forward) needs nothing.
 */
export function navigateSnapshotAction(to: unknown, options?: { replace?: boolean }): "capture" | "drop" | "none" {
  if (typeof to === "number") return "none"
  return options?.replace ? "drop" : "capture"
}

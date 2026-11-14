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

/** Whether a column of `nodeCount` elements may be cloned. */
export function withinNodeCap(nodeCount: number, cap: number = SNAPSHOT_NODE_CAP): boolean {
  return nodeCount <= cap
}

/** Canvases bigger than this (in pixels) are left blank rather than encoded. */
const CANVAS_PIXEL_CAP = 1_000_000
const LIVE_MEDIA = "video, audio, iframe, embed, object, script"

/**
 * Make a deep clone safe to park in the document: no duplicate ids, nothing focusable or
 * announced, nothing playing, no form control that could join a real radio group.
 */
export function sanitizeClone(clone: HTMLElement, original: HTMLElement): void {
  const sourceCanvases = original.querySelectorAll("canvas")
  clone.querySelectorAll("canvas").forEach((copy, i) => {
    const source = sourceCanvases[i]
    if (!source || source.width * source.height > CANVAS_PIXEL_CAP) return
    try {
      const img = document.createElement("img")
      img.src = source.toDataURL()
      img.className = copy.className
      img.setAttribute("style", copy.getAttribute("style") ?? "")
      copy.replaceWith(img)
    } catch {
      // A tainted canvas cannot be read: it stays blank.
    }
  })
  clone.querySelectorAll(LIVE_MEDIA).forEach((el) => el.remove())
  const strip = (el: Element) => {
    el.removeAttribute("id")
    el.removeAttribute("autofocus")
    el.removeAttribute("name")
    el.removeAttribute("data-shell-column")
    el.removeAttribute("tabindex")
  }
  strip(clone)
  clone.querySelectorAll("[id], [autofocus], [name], [data-shell-column], [tabindex]").forEach(strip)
  clone.setAttribute("aria-hidden", "true")
  clone.setAttribute("inert", "")
}

/** Clone `column`, or null when it is too large to be worth holding. */
export function captureColumn(column: HTMLElement, scrollY: number): PageSnapshot | null {
  if (!withinNodeCap(column.querySelectorAll("*").length)) return null
  const node = column.cloneNode(true) as HTMLElement
  sanitizeClone(node, column)
  return { node, scrollY }
}

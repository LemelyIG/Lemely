/*
 * Packet B2a · shared background-scroll lock for `Modal` and `NavDrawer`.
 *
 * Replaces setting the body's `overflow` style to `hidden`, which merely
 * stops the body from scrolling but does not stop the *page* from jumping:
 * iOS Safari in particular still lets a touch on the frozen body scroll the visual
 * viewport behind a fixed-position overlay. Pinning the body at its current
 * offset with `position: fixed` (the "scroll lock" recipe every dialog
 * pattern in the wild converges on) stops the page moving at all, and the
 * saved offset is exactly where `window.scrollTo` restores it on release.
 *
 * Reference-counted at module scope: `Modal` and `NavDrawer` share this one
 * lock, so a drawer opened underneath a modal (or vice versa) must not have
 * the second overlay's release unlock scrolling while the first is still
 * open. Only the outermost lock's acquire saves state; only the last
 * release's unlock restores it.
 *
 * Takes an injectable target rather than reading `window`/`document`
 * directly so the reference-counting logic itself runs under vitest's Node
 * environment (D3.20, no jsdom) — see `tests/unit/scrollLock.test.ts`.
 */

export interface ScrollLockTarget {
  body: { style: { position: string; top: string; insetInline: string; width: string } }
  scrollY: number
  scrollTo: (x: number, y: number) => void
}

function browserTarget(): ScrollLockTarget {
  return {
    body: document.body as unknown as ScrollLockTarget["body"],
    scrollY: window.scrollY,
    scrollTo: (x, y) => window.scrollTo(x, y),
  }
}

let lockCount = 0
let savedScrollY = 0
let savedStyle: { position: string; top: string; insetInline: string; width: string } | null = null

export function lockScroll(target: ScrollLockTarget = browserTarget()): () => void {
  lockCount += 1

  if (lockCount === 1) {
    savedScrollY = target.scrollY
    const { style } = target.body
    savedStyle = {
      position: style.position,
      top: style.top,
      insetInline: style.insetInline,
      width: style.width,
    }
    style.position = "fixed"
    style.top = `-${savedScrollY}px`
    style.insetInline = "0"
    style.width = "100%"
  }

  let released = false
  return () => {
    if (released) return
    released = true
    lockCount = Math.max(0, lockCount - 1)

    if (lockCount === 0 && savedStyle) {
      const { style } = target.body
      style.position = savedStyle.position
      style.top = savedStyle.top
      style.insetInline = savedStyle.insetInline
      style.width = savedStyle.width
      target.scrollTo(0, savedScrollY)
      savedStyle = null
    }
  }
}

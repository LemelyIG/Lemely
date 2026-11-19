import { useCallback, useEffect, useRef, type RefObject } from "react"

/*
 * The one focus trap for dialogs (`Modal`, and `Popover` when it is a native
 * sheet). Moved out of `modal.tsx` unchanged so the two cannot drift apart.
 *
 *   - on open: remember `document.activeElement`, then focus the panel's
 *     `[data-autofocus]` element (the iOS action sheet's Cancel row, which is
 *     not first in DOM order) or else its first focusable element, one frame
 *     later so the panel is in the DOM;
 *   - the returned handler cycles Tab and Shift+Tab inside the panel (wire it
 *     to the panel's `onKeyDown`; it ignores every other key);
 *   - on close: focus returns to the remembered element.
 */

export const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'

const AUTOFOCUS_SELECTOR = "[data-autofocus]"

export function useDialogFocus(
  panelRef: RefObject<HTMLElement | null>,
  open: boolean,
): (event: KeyboardEvent) => void {
  const previouslyFocused = useRef<HTMLElement | null>(null)

  useEffect(() => {
    if (!open) return

    previouslyFocused.current = document.activeElement as HTMLElement | null

    const raf = requestAnimationFrame(() => {
      const panel = panelRef.current
      const preferred =
        panel?.querySelector<HTMLElement>(AUTOFOCUS_SELECTOR) ?? panel?.querySelector<HTMLElement>(FOCUSABLE_SELECTOR)
      ;(preferred ?? panel)?.focus()
    })

    return () => {
      cancelAnimationFrame(raf)
      previouslyFocused.current?.focus()
    }
  }, [open, panelRef])

  return useCallback(
    (event) => {
      if (event.key !== "Tab") return
      const panel = panelRef.current
      if (!panel) return
      const focusable = Array.from(panel.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR))
      if (focusable.length === 0) {
        event.preventDefault()
        return
      }
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      const active = document.activeElement

      if (event.shiftKey && active === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && active === last) {
        event.preventDefault()
        first.focus()
      }
    },
    [panelRef],
  )
}

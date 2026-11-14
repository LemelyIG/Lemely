import { createPortal } from "react-dom"
import {
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode,
} from "react"
import { cn } from "@/lib/utils"
import { lockScroll } from "@/lib/scrollLock"
import { useDialogHistory } from "@/lib/nav/useDialogHistory"
import { useNativeFrame } from "@/lib/useNativeFrame"
import { BottomSheetSurface } from "@/components/ui/bottom-sheet"
import { useDialogFocus } from "@/components/ui/use-dialog-focus"

/*
 * Anchored popover for menus, filter panels and small pickers — content that
 * floats near a trigger rather than taking over the screen like `Modal`.
 * Positioned with plain CSS (`absolute` inside a `relative` wrapper) instead
 * of a portal-plus-`getBoundingClientRect` scheme: every current call site
 * anchors to a trigger that already lives in normal flow with room to open
 * below it, so the extra positioning-engine complexity (viewport-edge
 * flipping, scroll-container awareness) isn't earning its cost yet. If a
 * future call site needs viewport-aware flipping, that's the moment to reach
 * for `@floating-ui/react` rather than growing this file into one.
 *
 * State can be controlled (`open`/`onOpenChange`, for a caller that needs to
 * close the popover from elsewhere, e.g. after a menu item's action runs) or
 * uncontrolled (`defaultOpen` only) for the common case.
 *
 * Native frame (D4): on an iOS or Android phone the anchored panel becomes a
 * content-fit bottom sheet (`BottomSheetSurface`) in a portal, with the same
 * dialog contract as `Modal`: `role="dialog"`, `aria-modal`, a label (the
 * trigger), the shared `useDialogFocus` trap, and Escape plus browser Back
 * (`useDialogHistory`) closing it. `contentClassName` and `align` are
 * desktop-only there; the sheet is full width.
 */

export interface PopoverRenderProps {
  open: boolean
  /** Spread onto the trigger element: wires the click handler, the ref
   * needed for outside-click detection, and the ARIA popup attributes. */
  triggerProps: {
    ref: (node: HTMLElement | null) => void
    id: string
    onClick: () => void
    "aria-haspopup": "dialog"
    "aria-expanded": boolean
    "aria-controls": string
  }
}

export interface PopoverProps {
  /** Render prop for the trigger, so any element (button, chip, avatar) can
   * become a popover trigger by spreading `triggerProps` onto it. */
  renderTrigger: (props: PopoverRenderProps) => ReactNode
  children: ReactNode
  open?: boolean
  defaultOpen?: boolean
  onOpenChange?: (open: boolean) => void
  /** Which edge of the trigger the panel's inline-start edge aligns to.
   * Logical (`start`/`end`), never `left`/`right`, so it flips correctly
   * under `dir="rtl"` (DESIGN.md §12 gate 11). */
  align?: "start" | "end"
  className?: string
  contentClassName?: string
}

export function Popover({
  renderTrigger,
  children,
  open: openProp,
  defaultOpen = false,
  onOpenChange,
  align = "start",
  className,
  contentClassName,
}: PopoverProps) {
  const [uncontrolledOpen, setUncontrolledOpen] = useState(defaultOpen)
  const isControlled = openProp !== undefined
  const open = isControlled ? openProp : uncontrolledOpen
  const contentId = useId()
  const triggerId = useId()
  const { native } = useNativeFrame()
  const sheetOpen = native && open
  const sheetRef = useRef<HTMLDivElement>(null)

  const wrapperRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLElement | null>(null)

  function setOpen(next: boolean) {
    if (!isControlled) setUncontrolledOpen(next)
    onOpenChange?.(next)
  }

  function toggle() {
    setOpen(!open)
  }

  function close() {
    setOpen(false)
  }

  // Native sheet: one history entry so Back closes it, a pinned page behind it,
  // and the shared focus trap (focus returns to the trigger on close).
  useDialogHistory({ open: sheetOpen, dismissible: true, onClose: close })
  const trapFocus = useDialogFocus(sheetRef, sheetOpen)
  useEffect(() => {
    if (!sheetOpen) return
    return lockScroll()
  }, [sheetOpen])

  // Click-outside (the sheet has its own scrim): closes the popover on any pointerdown outside both the
  // trigger and the content. `pointerdown` rather than `click` so a drag
  // that starts inside and releases outside doesn't count as an outside
  // click, matching native `<select>` behaviour.
  useEffect(() => {
    if (!open || native) return
    function handlePointerDown(event: PointerEvent) {
      const target = event.target as Node
      if (wrapperRef.current?.contains(target)) return
      close()
    }
    document.addEventListener("pointerdown", handlePointerDown)
    return () => document.removeEventListener("pointerdown", handlePointerDown)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, native])

  // The trigger names the sheet. A call site that does not spread `triggerProps.id`
  // (the notification row wires only the ref) would leave a dangling reference, so
  // those fall back to a plain label rather than an unnamed dialog. Read from the ref in
  // a layout effect (before paint), never from the DOM during render.
  const [triggerNamed, setTriggerNamed] = useState(false)
  useLayoutEffect(() => {
    setTriggerNamed(sheetOpen && triggerRef.current?.id === triggerId)
  }, [sheetOpen, triggerId])
  const sheetLabel = triggerNamed ? { "aria-labelledby": triggerId } : { "aria-label": "More actions" }

  function handleKeyDown(event: ReactKeyboardEvent<HTMLDivElement>) {
    if (event.key !== "Escape") return
    event.stopPropagation()
    close()
    triggerRef.current?.focus()
  }

  return (
    <div ref={wrapperRef} className={cn("relative inline-block", className)}>
      {renderTrigger({
        open,
        triggerProps: {
          ref: (node) => {
            triggerRef.current = node
          },
          id: triggerId,
          onClick: toggle,
          "aria-haspopup": "dialog",
          "aria-expanded": open,
          "aria-controls": contentId,
        },
      })}
      {sheetOpen
        ? createPortal(
            <div className="fixed inset-0 z-modal">
              <div
                className="fixed inset-0 z-scrim bg-scrim-dialog motion-safe:animate-[lm-in_var(--dur-base)_var(--ease-out-soft)_both]"
                aria-hidden="true"
                onClick={close}
              />
              <BottomSheetSurface
                ref={sheetRef}
                role="dialog"
                aria-modal="true"
                {...sheetLabel}
                id={contentId}
                tabIndex={-1}
                onKeyDown={(event) => {
                  if (event.key === "Escape") {
                    event.stopPropagation()
                    close()
                    triggerRef.current?.focus()
                    return
                  }
                  trapFocus(event.nativeEvent)
                }}
                detents={["content"]}
                onDismiss={close}
                bodyClassName="flex flex-col gap-1 px-1 pb-4 [&_button]:min-h-11"
              >
                {children}
              </BottomSheetSurface>
            </div>,
            document.body,
          )
        : null}
      {open && !native ? (
        <div
          id={contentId}
          role="dialog"
          aria-modal="false"
          onKeyDown={handleKeyDown}
          className={cn(
            "absolute top-full z-dropdown mt-2 min-w-48 rounded-lg border border-outline-variant bg-surface-container-lowest p-2 shadow-[var(--shadow-float)]",
            "motion-safe:animate-[lm-in_var(--dur-fast)_var(--ease-spring)_both]",
            align === "start" ? "start-0" : "end-0",
            contentClassName,
          )}
        >
          {children}
        </div>
      ) : null}
    </div>
  )
}

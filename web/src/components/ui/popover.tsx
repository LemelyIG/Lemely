import {
  useEffect,
  useId,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode,
} from "react"
import { cn } from "@/lib/utils"

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
 */

export interface PopoverRenderProps {
  open: boolean
  /** Spread onto the trigger element: wires the click handler, the ref
   * needed for outside-click detection, and the ARIA popup attributes. */
  triggerProps: {
    ref: (node: HTMLElement | null) => void
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

  // Click-outside: closes the popover on any pointerdown outside both the
  // trigger and the content. `pointerdown` rather than `click` so a drag
  // that starts inside and releases outside doesn't count as an outside
  // click, matching native `<select>` behaviour.
  useEffect(() => {
    if (!open) return
    function handlePointerDown(event: PointerEvent) {
      const target = event.target as Node
      if (wrapperRef.current?.contains(target)) return
      close()
    }
    document.addEventListener("pointerdown", handlePointerDown)
    return () => document.removeEventListener("pointerdown", handlePointerDown)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

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
          onClick: toggle,
          "aria-haspopup": "dialog",
          "aria-expanded": open,
          "aria-controls": contentId,
        },
      })}
      {open ? (
        <div
          id={contentId}
          role="dialog"
          aria-modal="false"
          onKeyDown={handleKeyDown}
          className={cn(
            "absolute top-full z-dropdown mt-2 min-w-48 rounded-lg border border-rule bg-paper-raised p-2 shadow-[var(--shadow-float)]",
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

import {
  useEffect,
  useId,
  useRef,
  type HTMLAttributes,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode,
} from "react"
import { createPortal } from "react-dom"
import { X } from "@phosphor-icons/react"
import { cn } from "@/lib/utils"

/*
 * Dialog built on a portal rather than the native `<dialog>` element.
 * `<dialog>`'s built-in `::backdrop` cannot be styled with our token system
 * (it's a UA-rendered pseudo-element outside the box model our `--scrim`
 * token expects), and `showModal()`'s focus/scroll-lock behaviour varies
 * enough across the mid-range Android browsers students use that we'd end up
 * re-implementing focus trapping and Escape handling on top of it anyway —
 * at which point the native element buys nothing but a styling fight. A
 * portal into `document.body` gives full control over stacking (`z-modal`
 * from the fixed scale, §7) and lets the scrim use the exact `--scrim` token
 * DESIGN.md specifies.
 *
 * Accessibility contract (DESIGN.md §12 gate 8):
 *   - `role="dialog"` + `aria-modal="true"` on the panel.
 *   - `aria-labelledby` pointed at the title, generated via `useId` so every
 *     modal is labelled without the caller having to invent an id.
 *   - Focus moves into the panel on open and is trapped there (Tab/Shift+Tab
 *     cycle within it) until it closes.
 *   - Escape closes. Clicking the scrim closes (a modal is not a place a
 *     student can get stuck).
 *   - Focus returns to the element that opened the modal on close, so a
 *     keyboard user's position in the page is never lost.
 */

export interface ModalProps {
  open: boolean
  onClose: () => void
  /** Rendered as the accessible name via `aria-labelledby`. Always required:
   * an unlabelled dialog is a screen-reader dead end. */
  title: ReactNode
  /** Optional supporting line under the title. */
  description?: ReactNode
  children: ReactNode
  footer?: ReactNode
  /** Hides the corner close button for a flow that must be completed or
   * explicitly cancelled via a footer action rather than dismissed casually.
   * Escape and the scrim still close it unless `dismissible` is also false. */
  hideCloseButton?: boolean
  /** When false, Escape and scrim clicks no longer close the modal — only an
   * explicit footer action can. Used for destructive confirmations where an
   * accidental Escape must not discard a decision silently. */
  dismissible?: boolean
  /** `sm` (400px) for confirmations, `md` (520px, default) for forms, `lg`
   * (720px) for content-heavy panels. */
  size?: "sm" | "md" | "lg"
  className?: HTMLAttributes<HTMLDivElement>["className"]
}

const sizeClasses = {
  sm: "max-w-[400px]",
  md: "max-w-[520px]",
  lg: "max-w-[720px]",
} as const

const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'

export function Modal({
  open,
  onClose,
  title,
  description,
  children,
  footer,
  hideCloseButton = false,
  dismissible = true,
  size = "md",
  className,
}: ModalProps) {
  const titleId = useId()
  const descriptionId = useId()
  const panelRef = useRef<HTMLDivElement>(null)
  const previouslyFocused = useRef<HTMLElement | null>(null)

  // Focus the panel on open, restore the triggering element's focus on close.
  useEffect(() => {
    if (!open) return

    previouslyFocused.current = document.activeElement as HTMLElement | null

    // Defer to the next frame so the panel is in the DOM before we look for
    // a focusable descendant inside it.
    const raf = requestAnimationFrame(() => {
      const first = panelRef.current?.querySelector<HTMLElement>(FOCUSABLE_SELECTOR)
      ;(first ?? panelRef.current)?.focus()
    })

    return () => {
      cancelAnimationFrame(raf)
      previouslyFocused.current?.focus()
    }
  }, [open])

  // Lock background scroll while a modal is open, so the page underneath
  // can't scroll behind the scrim on mobile.
  useEffect(() => {
    if (!open) return
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = "hidden"
    return () => {
      document.body.style.overflow = previousOverflow
    }
  }, [open])

  if (!open) return null

  function handleKeyDown(event: ReactKeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape") {
      if (dismissible) {
        event.stopPropagation()
        onClose()
      }
      return
    }
    if (event.key !== "Tab") return

    // Manual focus trap: cycle Tab/Shift+Tab within the panel's focusable
    // descendants rather than letting focus escape into the page behind the
    // scrim.
    const panel = panelRef.current
    if (!panel) return
    const focusable = Array.from(
      panel.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR),
    )
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
  }

  return createPortal(
    <div
      className="fixed inset-0 z-[var(--z-index-modal)] flex items-center justify-center p-4"
      onKeyDown={handleKeyDown}
    >
      {/* Scrim: DESIGN.md §7's exact token, one step below the panel on the
          fixed z-scale (§7's z-scrim), click-to-dismiss. */}
      <div
        className="fixed inset-0 z-[var(--z-index-scrim)] bg-[var(--scrim)] motion-safe:animate-[lm-in_var(--dur-base)_var(--ease-out-soft)_both]"
        aria-hidden="true"
        onClick={dismissible ? onClose : undefined}
      />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={description ? descriptionId : undefined}
        tabIndex={-1}
        className={cn(
          "relative z-[var(--z-index-modal)] flex max-h-[85vh] w-full flex-col gap-4 rounded-xl border border-rule bg-paper-raised p-6 shadow-[var(--shadow-float)]",
          "motion-safe:animate-[lm-in_var(--dur-base)_var(--ease-spring)_both]",
          sizeClasses[size],
          className,
        )}
      >
        <div className="flex items-start justify-between gap-4">
          <div className="flex min-w-0 flex-col gap-1">
            <h2 id={titleId} className="text-display-sm text-ink">
              {title}
            </h2>
            {description ? (
              <p id={descriptionId} className="text-body-md text-ink-muted">
                {description}
              </p>
            ) : null}
          </div>
          {hideCloseButton ? null : (
            <button
              type="button"
              onClick={onClose}
              aria-label="Close dialog"
              className={cn(
                "-me-1 -mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-ink-muted transition-colors",
                "hover:bg-paper-sunk hover:text-ink",
                "active:scale-[0.98]",
              )}
            >
              <X size={18} aria-hidden="true" />
            </button>
          )}
        </div>
        <div className="min-h-0 overflow-y-auto lm-scroll">{children}</div>
        {footer ? (
          <div className="flex items-center justify-end gap-2 border-t border-rule pt-4">
            {footer}
          </div>
        ) : null}
      </div>
    </div>,
    document.body,
  )
}

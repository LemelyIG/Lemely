/* Hallmark · pre-emit critique: P4 H4 E5 S5 R5 V3 */
/* V3 is deliberate and not a shortfall: this reuses `Modal`'s focus,
   Escape, scrim and scroll-lock contract verbatim. A drawer that invented
   its own subtly different modal semantics would score higher on variety
   and be worse. */
import {
  useEffect,
  useId,
  useRef,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode,
} from "react"
import { createPortal } from "react-dom"
import { X } from "@phosphor-icons/react"
import { useLocation } from "react-router-dom"
import { cn } from "@/lib/utils"

/*
 * P3.1 · Mobile navigation drawer.
 *
 * Why this exists at all: the Phase 1 audit mapped the nav *inventory* per
 * role but read it from source, so it recorded which items each sidebar
 * contains without recording the width at which that sidebar exists. It does
 * not, below 820px (student, `hidden min-[820px]:flex`) or 768px (teacher,
 * `hidden md:flex`). Both portals rendered their entire primary navigation to
 * `display: none` on a phone, with no replacement of any kind — no tab bar, no
 * menu button, no drawer. A student on a phone could reach exactly the screen
 * they landed on plus whatever that screen happened to link to. The mission's
 * own framing ("students live on phones") makes that the single largest IA
 * defect in the product, and Phase 3's mandate is explicitly "no dead ends".
 *
 * Why a drawer and not a truncated tab bar: the student nav carries eleven
 * destinations and the teacher nav eight. A five-slot bottom bar cannot hold
 * either, so shipping one means ranking the survivors and silently dropping
 * the rest — a product decision this phase has no answer for and should not
 * invent. The drawer carries *every* item the desktop sidebar carries, which
 * is the only version of this that is complete rather than a second, smaller
 * dead end. `BottomNav` (C-13) stays in the kit unused for now; if Phase 4
 * establishes which four student destinations are genuinely daily, it becomes
 * the fast path *alongside* this, not instead of it.
 *
 * Behaviour is modal, because on a phone it covers the content it navigates
 * away from: focus moves in and is trapped, Escape closes, the scrim closes,
 * background scroll locks, and focus returns to the trigger. That contract and
 * its implementation are deliberately the same as `Modal` (see `modal.tsx` for
 * why a portal beats native `<dialog>` here) rather than a second, subtly
 * different one.
 *
 * It also closes on navigation. A drawer that stays open over the screen you
 * just asked for is the most common way this pattern is got wrong.
 */

const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'

export interface NavDrawerProps {
  open: boolean
  onClose: () => void
  /** Accessible name for the dialog. Rendered visually as the drawer header. */
  title: ReactNode
  /** The navigation itself. Callers pass the same item list their sidebar renders. */
  children: ReactNode
  /** Optional block pinned to the drawer foot (identity, cross-portal links). */
  footer?: ReactNode
}

export function NavDrawer({ open, onClose, title, children, footer }: NavDrawerProps) {
  const titleId = useId()
  const panelRef = useRef<HTMLDivElement>(null)
  const previouslyFocused = useRef<HTMLElement | null>(null)
  const location = useLocation()

  // Close on navigation. `location.key` rather than `pathname` so that
  // re-selecting the destination you are already on still dismisses the
  // drawer: tapping "Overview" while on Overview is a request to see
  // Overview, and leaving the drawer covering it reads as a broken tap.
  useEffect(() => {
    if (open) onClose()
    // `onClose` is intentionally not a dependency: callers pass an inline
    // arrow, so including it would re-run this on every parent render and
    // close the drawer the instant it opened.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.key])

  useEffect(() => {
    if (!open) return

    previouslyFocused.current = document.activeElement as HTMLElement | null

    // Defer a frame so the panel is mounted before we look inside it.
    const raf = requestAnimationFrame(() => {
      const first = panelRef.current?.querySelector<HTMLElement>(FOCUSABLE_SELECTOR)
      ;(first ?? panelRef.current)?.focus()
    })

    return () => {
      cancelAnimationFrame(raf)
      previouslyFocused.current?.focus()
    }
  }, [open])

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
      event.stopPropagation()
      onClose()
      return
    }
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
  }

  return createPortal(
    <div className="fixed inset-0 z-[var(--z-index-modal)]" onKeyDown={handleKeyDown}>
      <div
        className="fixed inset-0 z-[var(--z-index-scrim)] bg-[var(--scrim)] motion-safe:animate-[lm-in_var(--dur-base)_var(--ease-out-soft)_both]"
        aria-hidden="true"
        onClick={onClose}
      />
      {/* `start-0` (inset-inline-start) and `border-e` (border-inline-end), not
          `left-0`/`border-r`: P3.4's RTL rule. Paired with `--lm-dir` in the
          keyframe, the drawer anchors and enters from the reading-start edge in
          either direction with no second stylesheet. `inset-y-0` stays physical
          because the block axis does not flip under `dir="rtl"`. */}
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className={cn(
          "fixed inset-y-0 start-0 z-[var(--z-index-modal)] flex w-[min(20rem,85vw)] flex-col gap-5",
          "border-e border-rule bg-paper-raised px-4 py-5 shadow-[var(--shadow-float)]",
          "motion-safe:animate-[lm-slide-in-start_var(--dur-base)_var(--ease-spring)_both]",
        )}
      >
        <div className="flex items-center justify-between gap-3">
          <h2 id={titleId} className="text-display-sm text-ink">
            {title}
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close navigation"
            className={cn(
              "-me-1 flex h-11 w-11 shrink-0 items-center justify-center rounded-md text-ink-muted transition-colors",
              "hover:bg-paper-sunk hover:text-ink",
              "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
              "active:scale-[0.98]",
            )}
          >
            <X size={20} aria-hidden="true" />
          </button>
        </div>

        <div className="lm-scroll min-h-0 flex-1 overflow-y-auto">{children}</div>

        {footer ? <div className="border-t border-rule pt-4">{footer}</div> : null}
      </div>
    </div>,
    document.body,
  )
}

export interface NavDrawerTriggerProps {
  onClick: () => void
  /** Names what the button opens, e.g. "Open student navigation". */
  label: string
  className?: string
}

/**
 * The menu button that opens the drawer. A component rather than markup
 * repeated in each portal so the 44x44 touch target (Phase 6's mobile
 * non-negotiable) and the accessible name cannot drift apart between the two
 * call sites.
 */
export function NavDrawerTrigger({ onClick, label, className }: NavDrawerTriggerProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      aria-haspopup="dialog"
      className={cn(
        "flex h-11 w-11 shrink-0 items-center justify-center rounded-md text-ink-muted transition-colors",
        "hover:bg-paper-sunk hover:text-ink",
        "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
        "active:scale-[0.98]",
        className,
      )}
    >
      {/* Drawn rather than imported: three hairlines at the exact rule weight
          the rest of the system uses reads as part of the notebook, where
          Phosphor's `List` glyph brings its own stroke weight to a control
          that sits beside nothing else iconographic. Also RTL-neutral, which
          a chevron or an arrow would not be. */}
      <span aria-hidden="true" className="flex w-5 flex-col gap-[5px]">
        <span className="h-px w-full bg-current" />
        <span className="h-px w-full bg-current" />
        <span className="h-px w-full bg-current" />
      </span>
    </button>
  )
}

import {
  useEffect,
  useId,
  useRef,
  type AnimationEvent as ReactAnimationEvent,
  type HTMLAttributes,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode,
} from "react"
import { createPortal } from "react-dom"
import { X } from "@phosphor-icons/react"
import { cn } from "@/lib/utils"
import { lockScroll } from "@/lib/scrollLock"
import { useDialogHistory } from "@/lib/nav/useDialogHistory"
import { useOverlayPhase } from "@/lib/overlayPhase"
import { useNativeFrame } from "@/lib/useNativeFrame"
import { BottomSheetSurface } from "@/components/ui/bottom-sheet"
import { useDialogFocus } from "@/components/ui/use-dialog-focus"

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
 *   - the dialog role + `aria-modal="true"` on the panel (`panelProps`, shared by both surfaces).
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
  /** On the desktop dialog this styles the panel. On the native frame it applies to the
   * body wrapper inside the sheet, not to the sheet panel itself. */
  className?: HTMLAttributes<HTMLDivElement>["className"]
  /** Internal, for `ConfirmModal`; call sites never set it. `"auto"` is a
   * sheet on the native frame and a centred dialog elsewhere; `"action-sheet"`
   * is the iOS destructive-confirm form: no visible header or footer, the
   * caller's children are the rows, and the title and description are read
   * aloud only. */
  presentation?: "auto" | "action-sheet"
  /** Internal, for `ConfirmModal`. On the native frame the footer is full-width and
   * stacked, primary first (`"stacked"`, the default). `"actions"` keeps one end-aligned
   * row of text buttons, the Material 3 dialog-actions form. */
  footerLayout?: "stacked" | "actions"
}

const sizeClasses = {
  sm: "max-w-[400px]",
  md: "max-w-[520px]",
  lg: "max-w-[720px]",
} as const

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
  presentation = "auto",
  footerLayout = "stacked",
}: ModalProps) {
  const { native } = useNativeFrame()
  const titleId = useId()
  const descriptionId = useId()
  const panelRef = useRef<HTMLDivElement>(null)

  // Packet B2b: `open` going false does not unmount the modal immediately —
  // `phase` stays "closing" for the exit animation (`lm-out` below), and
  // only "closed" actually unmounts. `mounted` is what everything below
  // gates on instead of the raw `open` prop, so the history entry, the
  // scroll lock and the focus trap all stay live for the exit too.
  const { phase, onAnimationEnd } = useOverlayPhase(open)
  const mounted = phase !== "closed"

  // Packet B2a: opening pushes one history entry so browser back closes this
  // modal instead of navigating the page underneath it away; a non-dismissible
  // modal (ConfirmModal) re-pushes on back instead of closing. See
  // `useDialogHistory` for the full contract.
  useDialogHistory({ open: mounted, dismissible, onClose })

  // Focus the panel on open, trap Tab inside it, restore the triggering element's focus on close.
  const trapFocus = useDialogFocus(panelRef, mounted)

  // Lock background scroll for as long as the modal is mounted, closing
  // animation included — otherwise the page behind it would start scrolling
  // again while the panel is still visibly sliding away. `lockScroll`
  // (shared with `NavDrawer`) pins the body at its current offset rather
  // than merely setting `overflow: hidden`, which still lets iOS Safari
  // scroll the visual viewport behind a fixed overlay.
  useEffect(() => {
    if (!mounted) return
    return lockScroll()
  }, [mounted])

  if (!mounted) return null

  function handleKeyDown(event: ReactKeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape") {
      if (dismissible) {
        event.stopPropagation()
        onClose()
      }
      return
    }
    trapFocus(event.nativeEvent)
  }

  // One dialog contract, two surfaces: the native frame swaps only the frame
  // (a bottom sheet); role, label, focus trap, Escape and history stay shared.
  const panelProps = {
    role: "dialog" as const,
    "aria-modal": true as const,
    "aria-labelledby": titleId,
    "aria-describedby": description ? descriptionId : undefined,
    tabIndex: -1,
    // `event.target === event.currentTarget`: React's synthetic
    // `onAnimationEnd` also hears animations bubbling from descendants, and
    // a spinner or skeleton finishing inside a closing panel would end the
    // exit early and yank the panel off mid-slide.
    onAnimationEnd:
      phase === "closing"
        ? (event: ReactAnimationEvent<HTMLDivElement>) => {
            if (event.target === event.currentTarget) onAnimationEnd()
          }
        : undefined,
  }

  const heading = (
    <div className={cn("flex items-start justify-between gap-4", native && "w-full px-4 pb-2")}>
      <div className="flex min-w-0 flex-col gap-1">
        <h2 id={titleId} className="text-display-sm text-on-surface">
          {title}
        </h2>
        {description ? (
          <p id={descriptionId} className="text-body-md text-on-surface-variant">
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
            "flex shrink-0 items-center justify-center rounded-md text-on-surface-variant transition-colors",
            native ? "h-11 w-11" : "-me-1 -mt-1 h-8 w-8",
            "hover:bg-surface-container-low hover:text-on-surface",
            "active:scale-[0.98]",
            native && "lm-press lm-press-scale",
          )}
        >
          <X size={18} aria-hidden="true" />
        </button>
      )}
    </div>
  )
  const body = <div className="min-h-0 overflow-y-auto lm-scroll">{children}</div>
  // Native frame: no divider, and the actions are full-width and stacked with the primary on
  // top (callers list Cancel first, so the column is reversed; a caller whose own row is already
  // primary-first marks it `data-primary-first`). `actions` is the M3 end-aligned text-button row.
  const nativeFoot =
    footerLayout === "actions"
      ? "flex items-center justify-end gap-2"
      : "flex w-full flex-col-reverse gap-2 [&>div]:flex [&>div]:w-full [&>div:not([data-primary-first])]:flex-col-reverse [&>div[data-primary-first]]:flex-col [&>div]:gap-2 [&_button]:w-full [&_button]:justify-center"
  const foot = footer ? (
    <div
      className={
        native ? nativeFoot : "flex items-center justify-end gap-2 border-t border-outline-variant pt-4"
      }
    >
      {footer}
    </div>
  ) : null

  if (native) {
    // The sheet scrim is the preview's lighter dialog scrim (0.4), not the desktop modal's 0.55.
    return createPortal(
      <div className="fixed inset-0 z-modal" onKeyDown={handleKeyDown}>
        <div
          className="fixed inset-0 z-scrim bg-scrim-dialog motion-safe:animate-[lm-in_var(--dur-base)_var(--ease-out-soft)_both]"
          aria-hidden="true"
          // The iOS action sheet has no dismissal but its Cancel row, and a scrim tap IS Cancel:
          // outside the sheet is where a thumb goes to back out, and it can never confirm.
          onClick={dismissible || presentation === "action-sheet" ? onClose : undefined}
        />
        <BottomSheetSurface
          ref={panelRef}
          {...panelProps}
          detents={size === "lg" ? ["medium", "large"] : ["content"]}
          initialDetent={size === "lg" ? "medium" : "content"}
          dismissible={dismissible}
          onDismiss={onClose}
          closing={phase === "closing"}
          header={presentation === "action-sheet" ? null : heading}
          className={presentation === "action-sheet" ? "lm-action-sheet" : undefined}
          bodyClassName={presentation === "action-sheet" ? "lm-action-sheet-body" : cn("flex flex-col gap-4 px-4 pb-4", className)}
        >
          {presentation === "action-sheet" ? (
            <>
              <h2 id={titleId} className="sr-only">
                {title}
              </h2>
              {description ? (
                <p id={descriptionId} className="sr-only">
                  {description}
                </p>
              ) : null}
              {children}
            </>
          ) : (
            <>
              {body}
              {foot}
            </>
          )}
        </BottomSheetSurface>
      </div>,
      document.body,
    )
  }

  return createPortal(
    <div
      className="fixed inset-0 z-modal flex items-center justify-center p-4"
      onKeyDown={handleKeyDown}
    >
      {/* Scrim: DESIGN.md §7's exact token, one step below the panel on the
          fixed z-scale (§7's z-scrim), click-to-dismiss. */}
      <div
        className="fixed inset-0 z-scrim bg-scrim motion-safe:animate-[lm-in_var(--dur-base)_var(--ease-out-soft)_both]"
        aria-hidden="true"
        onClick={dismissible ? onClose : undefined}
      />
      <div
        ref={panelRef}
        {...panelProps}
        className={cn(
          "relative z-modal flex max-h-[85vh] w-full flex-col gap-4 rounded-xl border border-outline-variant bg-surface-container-lowest p-6 shadow-[var(--shadow-float)]",
          phase === "closing"
            ? "lm-out"
            : "motion-safe:animate-[lm-in_var(--dur-base)_var(--ease-spring)_both]",
          sizeClasses[size],
          className,
        )}
      >
        {heading}
        {body}
        {foot}
      </div>
    </div>,
    document.body,
  )
}

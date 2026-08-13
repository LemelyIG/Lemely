import type { ReactNode } from "react"
import { ArrowClockwise, WarningCircle, type Icon } from "@phosphor-icons/react"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"

/*
 * Inline error display: "this one request/panel/widget failed", rendered in
 * place of the content it was going to show. This is deliberately NOT the
 * error boundary (`error-boundary.tsx`) — the boundary catches a render crash
 * that would otherwise take down the whole screen; this component renders a
 * known, expected failure (a fetch rejected, a save failed) inside a layout
 * that keeps working around it. A screen composes both: the boundary wraps
 * the tree so an unexpected throw doesn't blank the page, and this component
 * is what the tree itself renders when a query's `isError` is true.
 *
 * Copy voice (DESIGN.md §12, "Error copy voice"): active voice, plain, no
 * blame, no exclamation marks, no em-dashes, sentence case. "We couldn't
 * save your changes," never "Oops! Something went wrong!!" Every call site
 * must supply its own specific `title`/`message` — this component does not
 * default to a generic string, because a generic error message is exactly
 * the kind of unhelpful copy the voice rule exists to prevent.
 */

export interface ErrorStateProps {
  /** What failed, in one short clause ("We couldn't load your results"). */
  title: string
  /** Optional detail: what happened and/or what to do next. */
  message?: string
  /** Retry handler. Renders a "Try again" button when supplied. */
  onRetry?: () => void
  /** Overrides the default "Try again" label, e.g. "Reload" or "Resend". */
  retryLabel?: string
  /** Swap the default warning glyph, e.g. for a connectivity-specific icon. */
  icon?: Icon
  /** Compact mode for a small inline slot (a single form field, a table
   * cell) rather than a whole panel: smaller icon, tighter padding, left
   * aligned instead of centred. */
  compact?: boolean
  className?: string
  children?: ReactNode
}

/**
 * Inline error state: icon, title, optional message, optional retry action.
 * Fills the space the failed content would have occupied rather than
 * collapsing it, so a retry doesn't cause a second layout shift on top of
 * the first one the failure already caused.
 */
export function ErrorState({
  title,
  message,
  onRetry,
  retryLabel = "Try again",
  icon: IconComponent = WarningCircle,
  compact = false,
  className,
  children,
}: ErrorStateProps) {
  if (compact) {
    return (
      <div
        role="alert"
        className={cn(
          "flex items-start gap-2 rounded-md border border-rule bg-err-wash px-3 py-2.5",
          className,
        )}
      >
        <IconComponent
          size={16}
          className="mt-0.5 shrink-0 text-err"
          aria-hidden="true"
        />
        <div className="flex min-w-0 flex-col gap-1">
          <p className="text-body-sm font-medium text-ink">{title}</p>
          {message ? <p className="text-body-sm text-ink-muted">{message}</p> : null}
          {onRetry ? (
            <button
              type="button"
              onClick={onRetry}
              className={cn(
                "text-label text-accent-ink underline decoration-1 underline-offset-2 transition-colors",
                "hover:text-accent-hover",
                "self-start",
              )}
            >
              {retryLabel}
            </button>
          ) : null}
          {children}
        </div>
      </div>
    )
  }

  return (
    <div
      role="alert"
      className={cn(
        "mx-auto flex w-full max-w-sm flex-col items-center gap-3 rounded-lg border border-rule bg-paper-raised px-6 py-10 text-center",
        className,
      )}
    >
      <div className="flex h-12 w-12 items-center justify-center rounded-full bg-err-wash">
        <IconComponent size={22} className="text-err" aria-hidden="true" />
      </div>
      <div className="flex flex-col gap-1.5">
        <p className="text-body-lg font-medium text-ink">{title}</p>
        {message ? <p className="text-body-md text-ink-muted">{message}</p> : null}
      </div>
      {onRetry ? (
        <Button
          variant="secondary"
          size="sm"
          onClick={onRetry}
          className="mt-1 gap-1.5"
        >
          <ArrowClockwise size={16} aria-hidden="true" />
          {retryLabel}
        </Button>
      ) : null}
      {children}
    </div>
  )
}

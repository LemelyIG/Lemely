/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V3 */
import { useId, type ReactNode } from "react"
import { CaretRight } from "@phosphor-icons/react"
import { Link } from "react-router-dom"
import { cn } from "@/lib/utils"
import { useDialogExitClick } from "@/lib/nav/dialogExit"

/*
 * Native frame grouped lists (brief §3.4). One component, two platform looks:
 * iOS inset-grouped (radius, 16px margins from the page padding, 44px rows,
 * separators inset from the leading edge); Android full-width M3 list items
 * (56/72/88 by line count, 16px padding, no separators). Design A, desktop
 * and `other` get the card look: surface-container-lowest, outline, radius-lg.
 */
export function ListGroup({
  label,
  footer,
  children,
  className,
}: {
  label?: string
  footer?: ReactNode
  children: ReactNode
  className?: string
}) {
  const id = useId()
  return (
    <section aria-labelledby={label ? id : undefined} className={cn("flex flex-col gap-2", className)}>
      {label ? (
        <h2 id={id} className="lm-native-group-label px-1 text-label text-on-surface-variant">
          {label}
        </h2>
      ) : null}
      <div data-list-group className="lm-native-group overflow-hidden rounded-lg border border-outline-variant bg-surface-container-lowest dark:bg-surface-container-high">
        {children}
      </div>
      {footer ? <div className="lm-native-group-label px-1 text-body-sm text-on-surface-variant">{footer}</div> : null}
    </section>
  )
}

/** `state` carries router state (an overlay's background). A row never closes its own sheet: the sheet closes when the location changes. */
type ListRowAction =
  | { to: string; state?: unknown; href?: never; onClick?: never }
  | { href: string; to?: never; state?: never; onClick?: never }
  | { onClick: () => void; to?: never; href?: never; state?: never }
  | { to?: undefined; href?: undefined; onClick?: undefined; state?: never }

export type ListRowProps = {
  title: ReactNode
  subtitle?: ReactNode
  leading?: ReactNode
  trailing?: ReactNode
  lines?: 1 | 2 | 3
  /** Title lines allowed before it clamps; 1 truncates. */
  titleLines?: 1 | 2
  /** Off for rows inside a sheet, which stays up while the destination loads. */
  viewTransition?: boolean
  /** A second control beside the row's own tap target (for example "Acknowledge").
   * Rendered outside the link, so there is never an interactive element inside
   * another. The control brings its own 44px (iOS) / 48px (Android) target. */
  action?: ReactNode
} & ListRowAction

/** The row's router link. A tap inside an open dialog replaces the dialog's history entry (see `dialogExit`). */
function RowLink({ to, state, viewTransition, className, lines, children }: { to: string; state?: unknown; viewTransition: boolean; className: string; lines?: number; children: ReactNode }) {
  const onClick = useDialogExitClick(to, { state, viewTransition })
  return (
    <Link to={to} state={state} viewTransition={viewTransition} onClick={onClick} className={className} data-lines={lines}>
      {children}
    </Link>
  )
}

export function ListRow({ title, subtitle, leading, trailing, to, href, state, onClick, action, lines = subtitle ? 2 : 1, titleLines = 1, viewTransition = true }: ListRowProps) {
  const base = "lm-press lm-press-delay flex items-center gap-3 px-4 py-2.5 text-start"
  const cls = cn("lm-list-row lm-native-row w-full", base)
  const inner = (
    <>
      {leading ? <span className="flex-none">{leading}</span> : null}
      <span className="flex min-w-0 flex-1 flex-col">
        <span className={cn("text-body-md text-on-surface", titleLines === 2 ? "line-clamp-2" : "truncate")}>{title}</span>
        {subtitle ? (
          <span className={cn("text-body-sm text-on-surface-variant", lines === 3 ? "line-clamp-2" : "truncate")}>
            {subtitle}
          </span>
        ) : null}
      </span>
      {trailing ? <span className="flex-none text-on-surface-variant">{trailing}</span> : null}
      {/* iOS discloses a destination with a chevron; Android rows carry none. */}
      {to ? <CaretRight aria-hidden="true" data-disclosure className="hidden size-4 flex-none text-on-surface-variant native:ios:block rtl:rotate-180" /> : null}
    </>
  )
  if (action && (to || onClick)) {
    // The wrapper carries the row classes so separators and min-heights keep
    // working; the tap target and the action sit side by side inside it.
    const main = cn("min-w-0 flex-1 self-stretch", base)
    return (
      <div className="lm-list-row lm-native-row flex w-full items-center" data-lines={lines}>
        {to ? (
          <RowLink to={to} state={state} viewTransition={viewTransition} className={main}>
            {inner}
          </RowLink>
        ) : (
          <button type="button" onClick={onClick} className={main}>
            {inner}
          </button>
        )}
        <div className="flex flex-none items-center pe-3">{action}</div>
      </div>
    )
  }
  if (to)
    return (
      <RowLink to={to} state={state} viewTransition={viewTransition} className={cls} lines={lines}>
        {inner}
      </RowLink>
    )
  if (href)
    return (
      <a href={href} className={cls} data-lines={lines}>
        {inner}
      </a>
    )
  if (onClick)
    return (
      <button type="button" onClick={onClick} className={cls} data-lines={lines}>
        {inner}
      </button>
    )
  return (
    <div className={cls} data-lines={lines}>
      {inner}
    </div>
  )
}

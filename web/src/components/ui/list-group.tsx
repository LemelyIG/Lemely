/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V3 */
import { useId, type ReactNode } from "react"
import { Link } from "react-router-dom"
import { cn } from "@/lib/utils"

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
} & ListRowAction

export function ListRow({ title, subtitle, leading, trailing, to, href, state, onClick, lines = subtitle ? 2 : 1, titleLines = 1, viewTransition = true }: ListRowProps) {
  const cls = "lm-list-row lm-native-row lm-press lm-press-delay flex w-full items-center gap-3 px-4 py-2.5 text-start"
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
    </>
  )
  if (to)
    return (
      <Link to={to} state={state} viewTransition={viewTransition} className={cls} data-lines={lines}>
        {inner}
      </Link>
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

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
      <div className="lm-native-group overflow-hidden rounded-lg border border-outline-variant bg-surface-container-lowest dark:bg-surface-container-high">
        {children}
      </div>
      {footer ? <div className="lm-native-group-label px-1 text-body-sm text-on-surface-variant">{footer}</div> : null}
    </section>
  )
}

export function ListRow({
  title,
  subtitle,
  leading,
  trailing,
  to,
  onClick,
  lines = subtitle ? 2 : 1,
}: {
  title: ReactNode
  subtitle?: ReactNode
  leading?: ReactNode
  trailing?: ReactNode
  to?: string
  onClick?: () => void
  lines?: 1 | 2 | 3
}) {
  const cls = "lm-list-row lm-native-row lm-press flex w-full items-center gap-3 px-4 py-2.5 text-start"
  const inner = (
    <>
      {leading ? <span className="flex-none">{leading}</span> : null}
      <span className="flex min-w-0 flex-1 flex-col">
        <span className="truncate text-body-md text-on-surface">{title}</span>
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
      <Link to={to} viewTransition className={cls} data-lines={lines}>
        {inner}
      </Link>
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

/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import type { ReactNode } from "react"
import { Link } from "react-router-dom"

/** A row's hit area: a Link for a route, a button for an action, otherwise a plain div. */
export function RowAction({
  to,
  onClick,
  selected,
  pressed,
  className,
  children,
}: {
  to?: string
  onClick?: () => void
  selected?: boolean
  /** A row that toggles, not navigates: aria-pressed on the button (and no aria-current). */
  pressed?: boolean
  className: string
  children: ReactNode
}) {
  const current = selected ? ("true" as const) : undefined
  if (to) {
    return (
      <Link to={to} className={className} aria-current={current}>
        {children}
      </Link>
    )
  }
  if (onClick) {
    return (
      <button
        type="button"
        className={className}
        aria-current={pressed === undefined ? current : undefined}
        aria-pressed={pressed}
        onClick={onClick}
      >
        {children}
      </button>
    )
  }
  return <div className={className} aria-current={current}>{children}</div>
}

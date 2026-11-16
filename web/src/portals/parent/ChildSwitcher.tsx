/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import { CaretDown } from "@phosphor-icons/react"
import { useLocation, useNavigate, useParams } from "react-router-dom"
import { Select } from "@/components/ui/select"
import { useChildren } from "@/lib/hooks/useParentApi"
import { cn } from "@/lib/utils"
import { switchChildPath } from "./shellModel"

/* The ring is a control boundary, so it is held to 3:1 on the pill fill:
 * 70% on-surface-variant over the pill is 3.36:1 light and 5.13:1 dark
 * (outline-variant alone is 1.27:1 and 1.49:1). */
const PILL =
  "relative inline-flex min-h-11 max-w-full min-w-0 flex-none items-center max-phone:max-w-36 gap-1.5 rounded-full bg-surface-container-lowest ps-1.5 pe-3 text-label text-on-surface shadow-[inset_0_0_0_1.5px_color-mix(in_srgb,var(--color-on-surface-variant)_70%,var(--color-surface-container-lowest))]"

function Initial({ name }: { name: string }) {
  return (
    <span aria-hidden="true" className="grid size-8 flex-none place-items-center rounded-full bg-primary-container font-display text-label text-primary">
      {name.trim().charAt(0).toUpperCase()}
    </span>
  )
}

/**
 * The parent child switcher (mock pa.js `kid`): an initial and the child's name.
 * Only on a child route. With one child it is a plain name label (no ring or caret), not a control,
 * so the parent always sees whose data this is; with two or more a native select
 * sits over the pill, so it is keyboard- and screen-reader-complete and keeps the
 * old switcher's tails (switchChildPath). On a phone narrower than 414px the pill is capped at 9rem and the name truncates; it is never hidden. While the list loads a same-size
 * placeholder holds the space so the top bar does not jump; on an error or an
 * unknown child it renders nothing and the trail still names the page.
 */
export function ChildSwitcher({ className }: { className?: string }) {
  const { childId } = useParams<{ childId: string }>()
  const navigate = useNavigate()
  const location = useLocation()
  const { data, isPending } = useChildren()
  if (!childId) return null
  if (isPending) {
    return <span aria-hidden="true" className={cn("inline-block h-11 w-32 max-w-full rounded-full bg-surface-container motion-safe:animate-pulse", className)} />
  }
  const children = data?.children ?? []
  const current = children.find((c) => c.childId === childId)
  if (!current) return null
  if (children.length < 2) {
    // A label, not a control: no ring, no fill, no caret, so it never reads as a button.
    return (
      <span data-child-switcher="" className={cn("inline-flex min-h-11 max-w-full min-w-0 flex-none items-center gap-2 text-label text-on-surface max-phone:max-w-36", className)}>
        <Initial name={current.displayName} />
        <span className="min-w-0 truncate" title={current.displayName}>{current.displayName}</span>
      </span>
    )
  }
  return (
    <span data-child-switcher="" className={cn(PILL, "cursor-pointer focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-primary", className)}>
      <Initial name={current.displayName} />
      {/* The name is always visible. Below 414px the whole pill is capped at 9rem so the page title keeps its room (390 left "Ph" of "Physics"), and a long name truncates. */}
      <span aria-hidden="true" className="min-w-0 truncate" title={current.displayName}>
        {current.displayName}
      </span>
      <CaretDown size={12} weight="bold" aria-hidden="true" className="flex-none" />
      {/* The kit's Select as a transparent overlay: the pill underneath is the visible control, the native picker stays on top. */}
      <Select
        label="Choose which child to view"
        labelClassName="sr-only"
        wrapperClassName="absolute inset-0 block [&>div]:h-full [&_svg]:hidden"
        aria-label="Choose which child to view"
        title={current.displayName}
        value={childId}
        onChange={(event) => navigate(switchChildPath(location.pathname, event.target.value))}
        className="h-full cursor-pointer rounded-full border-0 bg-transparent p-0 opacity-0"
      >
        {children.map((child) => (
          <option key={child.childId} value={child.childId}>
            {child.displayName}
          </option>
        ))}
      </Select>
    </span>
  )
}

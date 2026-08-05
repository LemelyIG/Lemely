import { useEffect, useRef, useState, type ReactNode } from "react"
import { CaretUpDown, Check } from "@phosphor-icons/react"
import { cn } from "@/lib/utils"

/*
 * C-12 · Role switcher — for an account holding more than one role (e.g. a
 * teacher who is also a parent).
 *
 * OPEN QUESTION (documented, not resolved here): LEMELY_UI_SPEC names this
 * component once ("Role switcher... for people who hold more than one
 * role") with no detail on where it lives or what triggers it — no screen
 * in Part 3/4 shows it. Built as a small, self-contained dropdown trigger
 * (current role + an accessible menu of the others) so it can be dropped
 * into a portal header, a sidebar footer, or G-11 account settings wherever
 * the P2.5.3 retrofit needs it. Placement is that task's call.
 */

export interface RoleOption {
  id: string
  label: string
  icon?: ReactNode
}

export interface RoleSwitcherProps {
  roles: RoleOption[]
  currentRoleId: string
  onSwitch: (roleId: string) => void
  className?: string
}

export function RoleSwitcher({
  roles,
  currentRoleId,
  onSwitch,
  className,
}: RoleSwitcherProps) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)
  const current = roles.find((r) => r.id === currentRoleId) ?? roles[0]

  useEffect(() => {
    if (!open) return

    function onPointerDown(e: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false)
    }

    document.addEventListener("mousedown", onPointerDown)
    document.addEventListener("keydown", onKeyDown)
    return () => {
      document.removeEventListener("mousedown", onPointerDown)
      document.removeEventListener("keydown", onKeyDown)
    }
  }, [open])

  if (!current) return null

  return (
    <div ref={rootRef} className={cn("relative inline-block", className)}>
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 rounded-md border border-border bg-surface px-3 py-2 text-body-md text-t1 transition-colors hover:bg-surface-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
      >
        {current.icon}
        <span className="font-medium">{current.label}</span>
        <CaretUpDown size={13} className="text-t3" />
      </button>
      {open ? (
        <div
          role="menu"
          aria-label="Switch role"
          className="absolute right-0 z-30 mt-1.5 min-w-48 rounded-md border border-border bg-surface py-1"
        >
          {roles.map((role) => {
            const active = role.id === current.id
            return (
              <button
                key={role.id}
                type="button"
                role="menuitemradio"
                aria-checked={active}
                onClick={() => {
                  setOpen(false)
                  if (!active) onSwitch(role.id)
                }}
                className={cn(
                  "flex w-full items-center gap-2.5 px-3 py-2 text-left text-body-md transition-colors hover:bg-surface-2",
                  active ? "font-medium text-t1" : "text-t2",
                )}
              >
                {role.icon}
                <span className="flex-1">{role.label}</span>
                {active ? <Check size={14} className="text-accent" /> : null}
              </button>
            )
          })}
        </div>
      ) : null}
    </div>
  )
}

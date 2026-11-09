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
  /** The menu's accessible name. Defaults to "Switch role". */
  menuLabel?: string
  /**
   * The trigger's accessible name, for when the current label alone ("Me") says too little.
   * Must contain the visible label (WCAG 2.5.3). Defaults to the visible label.
   */
  triggerLabel?: string
  /** Which side of the trigger the menu opens on. "above" for a trigger at the foot of a column. */
  placement?: "below" | "above"
  /** Extra classes for the menu, e.g. `start-0 end-auto w-full` to line it up under a full-width trigger. */
  menuClassName?: string
}

export function RoleSwitcher({
  roles,
  currentRoleId,
  onSwitch,
  className,
  menuLabel = "Switch role",
  triggerLabel,
  placement = "below",
  menuClassName,
}: RoleSwitcherProps) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const current = roles.find((r) => r.id === currentRoleId) ?? roles[0]

  useEffect(() => {
    if (!open) return

    function onPointerDown(e: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        setOpen(false)
        // Focus was on a menu item that is about to leave the page.
        triggerRef.current?.focus()
      }
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
        ref={triggerRef}
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={triggerLabel}
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 pointer-coarse:min-h-11 rounded-md border border-outline-variant bg-surface-container-lowest px-3 py-2 text-body-md text-on-surface transition-[background-color,transform] hover:bg-surface-container-low active:scale-[0.98] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
      >
        {current.icon}
        <span className="min-w-0 truncate font-medium">{current.label}</span>
        <CaretUpDown size={13} className="ms-auto flex-none text-on-surface-variant" aria-hidden="true" />
      </button>
      {open ? (
        <div
          role="menu"
          aria-label={menuLabel}
          // P6.3: `z-dropdown` names the band the raw `z-30` happened to land
          // on. Same value, but a reader can now tell it was chosen.
          className={cn(
            "absolute end-0 z-dropdown min-w-48 rounded-md border border-outline-variant bg-surface-container-lowest py-1",
            placement === "above" ? "bottom-full mb-1.5" : "mt-1.5",
            menuClassName,
          )}
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
                  // §6.1 touch floor — see the note in nav-shells.tsx.
                  "flex w-full items-center gap-2.5 px-3 py-2 pointer-coarse:min-h-11 text-start text-body-md transition-[background-color,transform] hover:bg-surface-container-low active:scale-[0.98]",
                  active ? "font-medium text-on-surface" : "text-on-surface-variant",
                )}
              >
                {role.icon}
                <span className="min-w-0 flex-1">{role.label}</span>
                {active ? <Check size={14} className="text-primary" /> : null}
              </button>
            )
          })}
        </div>
      ) : null}
    </div>
  )
}

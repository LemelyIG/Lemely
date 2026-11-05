/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import { Link, useNavigate } from "react-router-dom"
import { Gear, Lifebuoy, SignOut, UserCircle } from "@phosphor-icons/react"
import { DropdownMenu } from "radix-ui"
import { Avatar } from "@/components/ui/avatar"
import { useAuth } from "@/lib/auth/AuthContext"
import { useProfile } from "@/lib/hooks/useMeApi"
import { useOverlayState } from "@/lib/nav/useOverlayState"
import { cn } from "@/lib/utils"
import { FOCUS_RING, IconTile } from "./TopBarSheets"
import { HELP_HREF, PROFILE_EDIT_TO, SETTINGS_TO, roleLabel } from "./topBarActions"

/** Panel surface: the prototype's `.pop-panel` (lowest container, 18px radius, panel shadow). */
const MENU_SURFACE =
  "z-dropdown w-[260px] max-w-[calc(100vw-20px)] rounded-card bg-surface-container-lowest p-2 text-on-surface shadow-[var(--shadow-float)] dark:bg-surface-container-high motion-safe:animate-[lm-in_var(--dur-base)_var(--ease-out-soft)_both]"

const MENU_ITEM =
  "flex w-full cursor-pointer items-center gap-3 rounded-lg p-2.5 text-on-surface transition-colors duration-150 data-[highlighted]:bg-surface-container-low dark:data-[highlighted]:bg-surface-container-highest focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-primary"

/**
 * The signed-in teacher's avatar at the end of the top bar, dropping a small
 * account panel from itself. Name, email and role all come from
 * `GET /api/me/profile`; nothing renders until it resolves rather than a
 * placeholder person. Radix DropdownMenu supplies the menu semantics:
 * `aria-haspopup`/`aria-expanded` on the trigger, focus into the panel and
 * back to the avatar, arrow keys, Escape and outside-click dismissal.
 */
export function ProfileMenu({ triggerClassName }: { triggerClassName?: string }) {
  const { data } = useProfile()
  const { logout } = useAuth()
  const navigate = useNavigate()
  const overlayState = useOverlayState()
  if (!data) return null
  const name = data.displayName ?? data.email.split("@")[0]

  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger
        aria-label={`Your profile and account, ${name}`}
        className={cn("flex-none rounded-lg", FOCUS_RING, triggerClassName)}
      >
        <Avatar name={name} src={data.avatarUrl ?? undefined} size="sm" className="h-9 w-9 pointer-coarse:h-11 pointer-coarse:w-11" />
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content align="end" sideOffset={8} collisionPadding={10} className={MENU_SURFACE}>
          <div className="mb-1 flex items-center gap-3 border-b border-outline-variant px-2 pb-3 pt-2.5">
            <Avatar name={name} src={data.avatarUrl ?? undefined} size="md" />
            <div className="min-w-0">
              <p className="truncate text-label">{name}</p>
              <p className="truncate text-body-sm text-on-surface-variant">{data.email}</p>
              <p className="text-body-sm text-on-surface-variant">{roleLabel(data.role)}</p>
            </div>
          </div>
          <DropdownMenu.Item asChild>
            <Link to={PROFILE_EDIT_TO} state={overlayState} className={MENU_ITEM}>
              <IconTile><UserCircle size={20} aria-hidden="true" /></IconTile>
              <span className="text-label">Edit profile</span>
            </Link>
          </DropdownMenu.Item>
          <DropdownMenu.Item asChild>
            <Link to={SETTINGS_TO} state={overlayState} className={MENU_ITEM}>
              <IconTile><Gear size={20} aria-hidden="true" /></IconTile>
              <span className="text-label">Settings</span>
            </Link>
          </DropdownMenu.Item>
          <DropdownMenu.Item asChild>
            <a href={HELP_HREF} className={MENU_ITEM}>
              <IconTile><Lifebuoy size={20} aria-hidden="true" /></IconTile>
              <span className="min-w-0">
                <span className="block text-label">Help and feedback</span>
                <span className="block text-body-sm text-on-surface-variant">Email the Lemely team</span>
              </span>
            </a>
          </DropdownMenu.Item>
          <DropdownMenu.Item
            className={cn(MENU_ITEM, "text-start")}
            onSelect={() => {
              logout()
              navigate("/login", { replace: true })
            }}
          >
            <IconTile><SignOut size={20} aria-hidden="true" /></IconTile>
            <span className="text-label">Sign out</span>
          </DropdownMenu.Item>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  )
}

/* Hallmark · pre-emit critique: P4 H4 E4 S3 R4 V3 */
import { Link, useNavigate } from "react-router-dom"
import type { ReactNode } from "react"
import { SignOut } from "@phosphor-icons/react"
import { DropdownMenu } from "radix-ui"
import { Avatar } from "@/components/ui/avatar"
import { PROFILE_AVATAR_BOX, ShellAvatarPlaceholder, profileName } from "./ShellAvatar"
import { useAuth } from "@/lib/auth/AuthContext"
import { useProfile } from "@/lib/hooks/useMeApi"
import { useOverlayState } from "@/lib/nav/useOverlayState"
import { cn } from "@/lib/utils"
import { SHEET_FOCUS_RING as FOCUS_RING, IconTile } from "./TopBarSheets"

export interface AccountLink {
  id: string
  label: string
  icon: ReactNode
  /** An in-app route. Exactly one of `to` / `href`. */
  to?: string
  href?: string
  /** Carry the current page as the overlay background (settings links). */
  overlay?: boolean
  /** A second line under the label. */
  description?: string
}

export interface AccountPanelProps {
  links: readonly AccountLink[]
  /** The line under the email (teacher: role; student: qualification and subject count). */
  detail: string | null
  triggerClassName?: string
}

function LinkText({ link }: { link: AccountLink }) {
  return link.description ? (
    <span className="min-w-0">
      <span className="block text-label">{link.label}</span>
      <span className="block text-body-sm text-on-surface-variant">{link.description}</span>
    </span>
  ) : (
    <span className="text-label">{link.label}</span>
  )
}

/** Panel surface: the prototype's `.pop-panel` (lowest container, 18px radius, panel shadow). */
const MENU_SURFACE =
  "z-dropdown w-65 max-w-[calc(100vw-20px)] rounded-card bg-surface-container-lowest p-2 text-on-surface shadow-[var(--shadow-float)] dark:bg-surface-container-high motion-safe:animate-[lm-in_var(--dur-base)_var(--ease-out-soft)_both]"

const MENU_ITEM =
  "flex w-full cursor-pointer items-center gap-3 rounded-lg p-2.5 text-on-surface transition-colors duration-150 data-[highlighted]:bg-surface-container-low dark:data-[highlighted]:bg-surface-container-highest focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-primary"

/**
 * The signed-in teacher's avatar at the end of the top bar, dropping a small
 * account panel from itself. Name, email and role all come from
 * `GET /api/me/profile`; until it resolves the slot holds
 * `ShellAvatarPlaceholder` (the same box, no invented person), which is
 * also this module's `Suspense` fallback, so the avatar never pops in. Radix DropdownMenu supplies the menu semantics:
 * `aria-haspopup`/`aria-expanded` on the trigger, focus into the panel and
 * back to the avatar, arrow keys, Escape and outside-click dismissal.
 */
export function AccountPanel({ links, detail, triggerClassName }: AccountPanelProps) {
  const { data } = useProfile()
  const { logout } = useAuth()
  const navigate = useNavigate()
  const overlayState = useOverlayState()
  if (!data) return <ShellAvatarPlaceholder />
  const name = profileName(data)

  return (
    <DropdownMenu.Root modal={false}>
      <DropdownMenu.Trigger
        aria-label={`Your profile and account, ${name}`}
        className={cn("flex-none rounded-lg", FOCUS_RING, triggerClassName)}
      >
        <Avatar name={name} src={data.avatarUrl ?? undefined} size="sm" className={PROFILE_AVATAR_BOX} />
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content align="end" sideOffset={8} collisionPadding={10} className={MENU_SURFACE}>
          <div className="mb-1 flex items-center gap-3 border-b border-outline-variant px-2 pb-3 pt-2.5">
            <Avatar name={name} src={data.avatarUrl ?? undefined} size="md" />
            <div className="min-w-0">
              <p className="truncate text-label">{name}</p>
              <p className="truncate text-body-sm text-on-surface-variant">{data.email}</p>
              {detail ? <p className="text-body-sm text-on-surface-variant">{detail}</p> : null}
            </div>
          </div>
          {links.map((link) => (
            <DropdownMenu.Item key={link.id} asChild>
              {link.href ? (
                <a href={link.href} className={MENU_ITEM}>
                  <IconTile>{link.icon}</IconTile>
                  <LinkText link={link} />
                </a>
              ) : (
                <Link to={link.to ?? "/"} state={link.overlay ? overlayState : undefined} className={MENU_ITEM}>
                  <IconTile>{link.icon}</IconTile>
                  <LinkText link={link} />
                </Link>
              )}
            </DropdownMenu.Item>
          ))}
          <DropdownMenu.Item
            className={cn(MENU_ITEM, "text-start")}
            onSelect={() => {
              // Session caches finish clearing before the sign-in screen
              // mounts, so it never renders over a half-cleared session.
              void logout().then(() => navigate("/login", { replace: true }))
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

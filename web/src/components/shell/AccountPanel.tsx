import type { ReactNode } from "react"
import { Link, useNavigate } from "react-router-dom"
import { DropdownMenu } from "radix-ui"
import { useAuth } from "@/lib/auth/AuthContext"
import { useProfile } from "@/lib/hooks/useMeApi"
import { useOverlayState } from "@/lib/nav/useOverlayState"
import { cn } from "@/lib/utils"
import { ShellIcon } from "./icons"
import { ShellAvatar, ShellAvatarPlaceholder, profileName } from "./ShellAvatar"
import { SHELL_ICON_BUTTON, SHELL_PANEL } from "./shellStyles"

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

const LINK =
  "flex w-full cursor-pointer items-center gap-2.5 rounded-chip px-2 py-[9px] text-start text-label text-on-surface transition-colors duration-150 data-[highlighted]:bg-surface-container-low pointer-coarse:min-h-11 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-primary [&>svg]:text-on-surface-variant"

function LinkText({ link }: { link: AccountLink }) {
  return link.description ? (
    <span className="min-w-0">
      <span className="block">{link.label}</span>
      <span className="block text-body-sm font-normal text-on-surface-variant">{link.description}</span>
    </span>
  ) : (
    <span>{link.label}</span>
  )
}

/**
 * The signed-in person's avatar at the end of the top bar and the panel it
 * drops: who, then the portal's links, then Sign out. Until the profile
 * resolves the slot holds `ShellAvatarPlaceholder`. Radix DropdownMenu gives
 * aria-haspopup/expanded, focus into the panel and back to the avatar.
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
        className={cn(SHELL_ICON_BUTTON, triggerClassName)}
      >
        <ShellAvatar name={name} src={data.avatarUrl} />
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content align="end" sideOffset={8} collisionPadding={10} className={cn(SHELL_PANEL, "w-65")}>
          <div className="mb-1 flex items-center gap-2.5 border-b border-outline-variant px-2 pt-2.5 pb-3">
            <ShellAvatar name={name} src={data.avatarUrl} size="md" />
            <span className="flex min-w-0 flex-col">
              <b className="text-body-sm font-bold leading-[1.3] text-on-surface">{name}</b>
              <small className="truncate text-body-sm leading-[1.4] text-on-surface-variant">{data.email}</small>
              {detail ? (
                <small className="truncate text-body-sm leading-[1.4] text-on-surface-variant">{detail}</small>
              ) : null}
            </span>
          </div>
          {links.map((link) => (
            <DropdownMenu.Item key={link.id} asChild>
              {link.href ? (
                <a href={link.href} className={LINK}>
                  {link.icon}
                  <LinkText link={link} />
                </a>
              ) : (
                <Link to={link.to ?? "/"} state={link.overlay ? overlayState : undefined} className={LINK}>
                  {link.icon}
                  <LinkText link={link} />
                </Link>
              )}
            </DropdownMenu.Item>
          ))}
          <DropdownMenu.Item
            className={LINK}
            onSelect={() => {
              // Session caches finish clearing before the sign-in screen mounts.
              void logout().then(() => navigate("/login", { replace: true }))
            }}
          >
            <ShellIcon name="out" />
            <span>Sign out</span>
          </DropdownMenu.Item>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  )
}

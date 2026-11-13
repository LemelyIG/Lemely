/* Hallmark · pre-emit critique: P4 H4 E3 S4 R3 V3 */
import type { ReactNode } from "react"
import { Link, useNavigate } from "react-router-dom"
import { DropdownMenu } from "radix-ui"
import { useAuth } from "@/lib/auth/AuthContext"
import { useProfile } from "@/lib/hooks/useMeApi"
import { useOverlayState } from "@/lib/nav/useOverlayState"
import { cn } from "@/lib/utils"
import { useNativeFrame } from "@/lib/useNativeFrame"
import { ListGroup, ListRow } from "@/components/ui/list-group"
import { ShellIcon } from "./icons"
import { PanelSheet } from "./PanelSheet"
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

function Identity({ name, email, detail, avatarUrl, sheet }: { name: string; email: string; detail: string | null; avatarUrl: string | null; sheet: boolean }) {
  return (
    <div
      className={cn(
        "flex items-center gap-2.5",
        sheet ? "px-1 pb-1" : "mb-1 border-b border-outline-variant px-2 pt-2.5 pb-3",
      )}
    >
      <ShellAvatar name={name} src={avatarUrl} size="md" />
      <span className="flex min-w-0 flex-col">
        {/* `--fs-body-sm` alone, not `text-body-sm`: its unlayered `font:` shorthand would undo weight and leading. */}
        <b className="text-(length:--fs-body-sm) font-bold leading-[1.3] text-on-surface">{name}</b>
        <small className="truncate text-(length:--fs-body-sm) leading-[1.4] text-on-surface-variant">{email}</small>
        {detail ? (
          <small className="truncate text-(length:--fs-body-sm) leading-[1.4] text-on-surface-variant">{detail}</small>
        ) : null}
      </span>
    </div>
  )
}

/**
 * The signed-in person's avatar at the end of the top bar and the panel it
 * drops: who, then the portal's links, then Sign out. Until the profile
 * resolves the slot holds `ShellAvatarPlaceholder`. Desktop and tablet: a
 * Radix DropdownMenu (aria-haspopup/expanded, focus into the panel and back
 * to the avatar). Native phones: a content-fit sheet of grouped rows.
 */
export function AccountPanel({ links, detail, triggerClassName }: AccountPanelProps) {
  const { data } = useProfile()
  const { logout } = useAuth()
  const navigate = useNavigate()
  const overlayState = useOverlayState()
  const { native } = useNativeFrame()
  if (!data) return <ShellAvatarPlaceholder />
  const name = profileName(data)
  const label = `Your profile and account, ${name}`
  const signOut = () => {
    // Session caches finish clearing before the sign-in screen mounts.
    void logout().then(() => navigate("/login", { replace: true }))
  }
  const trigger = <ShellAvatar name={name} src={data.avatarUrl} />
  return native ? (
    <PanelSheet triggerLabel={label} triggerClassName={cn(SHELL_ICON_BUTTON, triggerClassName)} trigger={trigger} title="Account">
      {() => (
        <div className="flex flex-col gap-3">
          <Identity name={name} email={data.email} detail={detail} avatarUrl={data.avatarUrl} sheet />
          <ListGroup>
            {links.map((link) =>
              link.href ? (
                <ListRow key={link.id} leading={link.icon} title={link.label} subtitle={link.description} href={link.href} />
              ) : (
                <ListRow
                  key={link.id}
                  leading={link.icon}
                  title={link.label}
                  subtitle={link.description}
                  to={link.to ?? "/"}
                  state={link.overlay ? overlayState : undefined}
                  viewTransition={false}
                />
              ),
            )}
          </ListGroup>
          <ListGroup>
            <ListRow
              leading={<ShellIcon name="out" />}
              title="Sign out"
              onClick={signOut}
            />
          </ListGroup>
        </div>
      )}
    </PanelSheet>
  ) : (
    <DropdownMenu.Root modal={false}>
      <DropdownMenu.Trigger aria-label={label} className={cn(SHELL_ICON_BUTTON, triggerClassName)}>
        {trigger}
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content align="end" sideOffset={8} collisionPadding={10} className={cn(SHELL_PANEL, "w-65")}>
          <Identity name={name} email={data.email} detail={detail} avatarUrl={data.avatarUrl} sheet={false} />
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
          <DropdownMenu.Item className={LINK} onSelect={signOut}>
            <ShellIcon name="out" />
            <span>Sign out</span>
          </DropdownMenu.Item>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  )
}

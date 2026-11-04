/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import type { ReactNode } from "react"
import { Link, useNavigate } from "react-router-dom"
import {
  Books,
  Gear,
  Lifebuoy,
  Megaphone,
  Plus,
  SignOut,
  Sparkle,
  UserCircle,
  UsersThree,
  X,
  type Icon,
} from "@phosphor-icons/react"
import { Avatar } from "@/components/ui/avatar"
import {
  Sheet,
  SheetClose,
  SheetContent,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet"
import { useAuth } from "@/lib/auth/AuthContext"
import { useProfile } from "@/lib/hooks/useMeApi"
import { cn } from "@/lib/utils"
import {
  CREATE_ACTIONS,
  HELP_HREF,
  PROFILE_EDIT_TO,
  SETTINGS_TO,
  roleLabel,
  type CreateActionIcon,
} from "./topBarActions"

const ACTION_ICON: Record<CreateActionIcon, Icon> = {
  scheme: Books,
  quiz: Sparkle,
  announcement: Megaphone,
  class: UsersThree,
}

const FOCUS_RING =
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"

/** Light: the lowest container, like every panel. Dark: one step up so it lifts off the page. */
const SHEET_SURFACE =
  "gap-1.5 rounded-card border-0 bg-surface-container-lowest p-6 text-on-surface dark:bg-surface-container-high"

const ROW =
  "flex items-center gap-3 rounded-lg p-2.5 text-on-surface transition-colors duration-150 hover:bg-surface-container-low dark:hover:bg-surface-container-highest " +
  FOCUS_RING

function CloseButton() {
  return (
    <SheetClose
      className={cn(
        "absolute end-4 top-4 flex h-9 w-9 items-center justify-center rounded-pill bg-surface-container-low text-on-surface-variant transition-colors hover:text-on-surface pointer-coarse:h-11 pointer-coarse:w-11 dark:bg-surface-container-highest",
        FOCUS_RING,
      )}
    >
      <X size={16} aria-hidden="true" />
      <span className="sr-only">Close</span>
    </SheetClose>
  )
}

function IconTile({ children }: { children: ReactNode }) {
  return (
    <span className="flex h-10 w-10 flex-none items-center justify-center rounded-md bg-primary-container text-primary">
      {children}
    </span>
  )
}

/**
 * The top bar's Create button and the sheet it opens: four starting points,
 * each a link to the screen that does the work. Radix Dialog underneath gives
 * the focus trap, Escape, scrim dismissal, the title as the accessible name and
 * focus back on this button on close.
 */
export function CreateSheet({ triggerClassName }: { triggerClassName: string }) {
  return (
    <Sheet>
      <SheetTrigger className={triggerClassName}>
        <Plus size={16} aria-hidden="true" />
        <span className="hidden sm:inline">Create</span>
        <span className="sr-only sm:hidden">Create</span>
      </SheetTrigger>
      <SheetContent side="adaptive" showCloseButton={false} aria-describedby={undefined} className={SHEET_SURFACE}>
        <CloseButton />
        <p className="text-eyebrow text-on-surface-variant">Create</p>
        <SheetTitle className="mb-2 text-display-md">Start something</SheetTitle>
        <ul className="flex flex-col gap-1">
          {CREATE_ACTIONS.map((action) => {
            const Glyph = ACTION_ICON[action.icon]
            return (
              <li key={action.id}>
                <SheetClose asChild>
                  <Link to={action.to} className={ROW}>
                    <IconTile>
                      <Glyph size={20} aria-hidden="true" />
                    </IconTile>
                    <span className="min-w-0">
                      <span className="block text-label">{action.title}</span>
                      <span className="block text-body-sm text-on-surface-variant">{action.description}</span>
                    </span>
                  </Link>
                </SheetClose>
              </li>
            )
          })}
        </ul>
      </SheetContent>
    </Sheet>
  )
}

/**
 * The signed-in teacher's avatar at the end of the top bar, opening their
 * account sheet. Name, email and role all come from `GET /api/me/profile`;
 * nothing renders until it resolves rather than a placeholder person.
 */
export function ProfileSheet({ triggerClassName }: { triggerClassName?: string }) {
  const { data } = useProfile()
  const { logout } = useAuth()
  const navigate = useNavigate()
  if (!data) return null
  const name = data.displayName ?? data.email.split("@")[0]

  return (
    <Sheet>
      <SheetTrigger
        aria-label={`Your profile and account, ${name}`}
        className={cn("flex-none rounded-lg", FOCUS_RING, triggerClassName)}
      >
        <Avatar name={name} src={data.avatarUrl ?? undefined} size="sm" className="h-9 w-9 pointer-coarse:h-11 pointer-coarse:w-11" />
      </SheetTrigger>
      <SheetContent side="adaptive" showCloseButton={false} aria-describedby={undefined} className={SHEET_SURFACE}>
        <CloseButton />
        <p className="text-eyebrow text-on-surface-variant">Account</p>
        <div className="mb-3 mt-1 flex items-center gap-3 pe-12">
          <Avatar name={name} src={data.avatarUrl ?? undefined} size="md" />
          <div className="min-w-0">
            <SheetTitle className="truncate text-display-xs">{name}</SheetTitle>
            <p className="truncate text-body-sm text-on-surface-variant">{data.email}</p>
            <p className="text-body-sm text-on-surface-variant">{roleLabel(data.role)}</p>
          </div>
        </div>
        <ul className="flex flex-col gap-1 border-t border-outline-variant pt-3">
          <li>
            <SheetClose asChild>
              <Link to={PROFILE_EDIT_TO} className={ROW}>
                <IconTile><UserCircle size={20} aria-hidden="true" /></IconTile>
                <span className="text-label">Edit profile</span>
              </Link>
            </SheetClose>
          </li>
          <li>
            <SheetClose asChild>
              <Link to={SETTINGS_TO} className={ROW}>
                <IconTile><Gear size={20} aria-hidden="true" /></IconTile>
                <span className="text-label">Settings</span>
              </Link>
            </SheetClose>
          </li>
          <li>
            <a href={HELP_HREF} className={ROW}>
              <IconTile><Lifebuoy size={20} aria-hidden="true" /></IconTile>
              <span className="min-w-0">
                <span className="block text-label">Help and feedback</span>
                <span className="block text-body-sm text-on-surface-variant">Email the Lemely team</span>
              </span>
            </a>
          </li>
          <li>
            <button
              type="button"
              onClick={() => {
                logout()
                navigate("/login", { replace: true })
              }}
              className={cn(ROW, "w-full cursor-pointer border-0 bg-transparent text-start")}
            >
              <IconTile><SignOut size={20} aria-hidden="true" /></IconTile>
              <span className="text-label">Sign out</span>
            </button>
          </li>
        </ul>
      </SheetContent>
    </Sheet>
  )
}

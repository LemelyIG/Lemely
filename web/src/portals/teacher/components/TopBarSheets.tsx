/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import type { ReactNode } from "react"
import { Link } from "react-router-dom"
import {
  Books,
  Megaphone,
  Plus,
  Sparkle,
  UsersThree,
  X,
  type Icon,
} from "@phosphor-icons/react"
import {
  Sheet,
  SheetClose,
  SheetContent,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet"
import { cn } from "@/lib/utils"
import {
  CREATE_ACTIONS,
  type CreateActionIcon,
} from "./topBarActions"

const ACTION_ICON: Record<CreateActionIcon, Icon> = {
  scheme: Books,
  quiz: Sparkle,
  announcement: Megaphone,
  class: UsersThree,
}

export const FOCUS_RING =
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

export function IconTile({ children }: { children: ReactNode }) {
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

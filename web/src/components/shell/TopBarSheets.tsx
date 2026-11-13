/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import type { ReactNode, RefObject } from "react"
import { Link } from "react-router-dom"
import { X } from "@phosphor-icons/react"
import {
  Sheet,
  SheetClose,
  SheetContent,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet"
import { cn } from "@/lib/utils"

export const SHEET_FOCUS_RING =
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"

/** Light: the lowest container, like every panel. Dark: one step up so it lifts off the page. */
const SHEET_SURFACE =
  "gap-1.5 rounded-card border-0 bg-surface-container-lowest p-6 text-on-surface dark:bg-surface-container-high"

const ROW =
  "flex items-center gap-3 rounded-lg p-2.5 text-on-surface transition-colors duration-150 hover:bg-surface-container-low dark:hover:bg-surface-container-highest " +
  SHEET_FOCUS_RING

function CloseButton() {
  return (
    <SheetClose
      className={cn(
        "absolute end-4 top-4 flex h-9 w-9 items-center justify-center rounded-pill bg-surface-container-low text-on-surface-variant transition-colors hover:text-on-surface pointer-coarse:h-11 pointer-coarse:w-11 dark:bg-surface-container-highest",
        SHEET_FOCUS_RING,
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

export interface SheetAction {
  id: string
  title: string
  description: string
  to: string
  icon: ReactNode
}

export interface ActionSheetProps {
  triggerClassName: string
  triggerIcon: ReactNode
  triggerLabel: string
  eyebrow: string
  title: string
  actions: readonly SheetAction[]
  /** Controlled use: a second opener (the native FAB, the iOS large-title plus) drives the same sheet. */
  open?: boolean
  onOpenChange?: (open: boolean) => void
  /** Where focus goes on close when the opener that was used is not the bar trigger. */
  restoreFocusTo?: RefObject<HTMLElement | null>
  /** Phones in the native frame hide the bar trigger: the action lives in the FAB or the large-title row. */
  hideTriggerOnNative?: boolean
}

/**
 * A top-bar button and the sheet it opens: a list of starting points, each a
 * link to the screen that does the work. Radix Dialog underneath gives the
 * focus trap, Escape, scrim dismissal, the title as the accessible name and
 * focus back on the button on close.
 */
export function ActionSheet({
  triggerClassName,
  triggerIcon,
  triggerLabel,
  eyebrow,
  title,
  actions,
  open,
  onOpenChange,
  restoreFocusTo,
  hideTriggerOnNative = false,
}: ActionSheetProps) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetTrigger className={cn(triggerClassName, hideTriggerOnNative && "native:hidden")}>
        {triggerIcon}
        <span className="hidden sm:inline">{triggerLabel}</span>
        <span className="sr-only sm:hidden">{triggerLabel}</span>
      </SheetTrigger>
      <SheetContent
        side="adaptive"
        showCloseButton={false}
        aria-describedby={undefined}
        className={SHEET_SURFACE}
        onCloseAutoFocus={(event) => {
          const target = restoreFocusTo?.current
          if (target && target.isConnected && target.checkVisibility()) {
            event.preventDefault()
            target.focus()
          }
        }}
      >
        <CloseButton />
        {/* No eyebrow above a heading on the native frame (craft floor); the sheet title leads. */}
        <p className="text-eyebrow text-on-surface-variant native:hidden">{eyebrow}</p>
        <SheetTitle className="lm-native-sheet-title mb-2 text-display-md">{title}</SheetTitle>
        <ul className="flex flex-col gap-1">
          {actions.map((action) => (
            <li key={action.id}>
              <SheetClose asChild>
                <Link to={action.to} className={ROW}>
                  <IconTile>{action.icon}</IconTile>
                  <span className="min-w-0">
                    <span className="block text-label">{action.title}</span>
                    <span className="block text-body-sm text-on-surface-variant">{action.description}</span>
                  </span>
                </Link>
              </SheetClose>
            </li>
          ))}
        </ul>
      </SheetContent>
    </Sheet>
  )
}

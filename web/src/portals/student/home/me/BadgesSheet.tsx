import type { RefObject } from "react"
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet"
import { cn } from "@/lib/utils"
import { BADGE_ICON } from "./BadgeRow"
import type { deriveBadges } from "./meModel"

export function BadgesSheet({ open, onOpenChange, badges, returnFocusRef }: { open: boolean; onOpenChange: (o: boolean) => void; badges: ReturnType<typeof deriveBadges>; returnFocusRef: RefObject<HTMLElement | null> }) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="adaptive"
        className="flex flex-col gap-4 p-6"
        onCloseAutoFocus={(e) => {
          e.preventDefault()
          returnFocusRef.current?.focus()
        }}
      >
        <SheetTitle className="pe-10 text-display-md">Badges</SheetTitle>
        <SheetDescription>Earned from real work only.</SheetDescription>
        <ul className="grid">
          {badges.map((b) => {
            const Icon = BADGE_ICON[b.id]
            return (
              <li key={b.id} className="grid grid-cols-[52px_minmax(0,1fr)] items-center gap-3 py-2.5 [&+&]:border-t [&+&]:border-outline-variant">
                <span className={cn("grid size-[52px] place-items-center rounded-full", b.earned ? "bg-primary-container text-on-primary-container" : "bg-surface-container-high text-outline")}>
                  <Icon size={24} aria-hidden="true" />
                </span>
                <span>
                  <b className="block text-[15px] font-semibold text-on-surface">{b.label}</b>
                  <span className="text-[13px] text-on-surface-variant">{b.earned ? "Earned" : b.hint}</span>
                </span>
              </li>
            )
          })}
        </ul>
      </SheetContent>
    </Sheet>
  )
}

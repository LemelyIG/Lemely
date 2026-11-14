import { useEffect } from "react"
import { matchPath, useLocation } from "react-router-dom"
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet"
import { ListGroup, ListRow } from "@/components/ui/list-group"
import type { NavShellItem } from "@/components/ui/nav-shells"
import { useDialogHistory } from "@/lib/nav/useDialogHistory"
import { CloseButton } from "./TopBarSheets"

/**
 * The More tab on native phones (user decision, 2026-11-13): a titled bottom sheet listing only the
 * destinations the tab bar does not already hold. Rows navigate and the sheet closes on the location
 * change, the way the shell drawer does; the same sheet contract as every native sheet (dialog role,
 * label, focus trap, focus back on the tab, Escape and browser Back close it). Desktop and tablet keep
 * the drawer.
 */
export function MoreSheet({
  open,
  onClose,
  items,
}: {
  open: boolean
  onClose: () => void
  /** Overflow destinations, already filtered against the tab bar. */
  items: readonly NavShellItem[]
}) {
  const location = useLocation()
  useDialogHistory({ open, dismissible: true, onClose })
  // Close on navigation, but not on the history entry this sheet's own Back trap pushes.
  useEffect(() => {
    if (!open) return
    if ((location.state as { lemelyDialog?: boolean } | null)?.lemelyDialog) return
    onClose()
    // `onClose` is an inline arrow in the caller; depending on it would close the sheet the moment it opens.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.key])
  return (
    <Sheet open={open} onOpenChange={(next) => !next && onClose()}>
      <SheetContent
        side="bottom"
        showCloseButton={false}
        aria-describedby={undefined}
        // The title rides in the drag region right under the grabber; the list gets its own margin
        // from the header's bottom padding (the sheet title rule zeroes margins, padding is not reset).
        nativeHeader={<SheetTitle className="lm-native-sheet-title w-full px-6 pb-4 pt-0 text-display-md">More</SheetTitle>}
        nativeBodyClassName="px-6 pb-6 pt-0"
      >
        {/* iOS sheets close from the top corner, as the Create sheet does; Android has the scrim and Back. */}
        <div className="hidden native:ios:contents">
          <CloseButton className="top-[27px] -translate-y-1/2" />
        </div>
        <ListGroup>
          {items.map((item) => (
            <ListRow
              key={item.id}
              to={item.to ?? "/"}
              title={item.label}
              leading={item.icon}
              trailing={item.badge !== undefined ? <span className="text-metadata">{item.badge}</span> : undefined}
              lines={1}
              current={Boolean(item.to && matchPath({ path: item.to, end: item.end ?? false }, location.pathname))}
              // The sheet closes on arrival: native iOS dismisses it and shows the destination, with no push.
              viewTransition={false}
            />
          ))}
        </ListGroup>
      </SheetContent>
    </Sheet>
  )
}

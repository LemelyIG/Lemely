import { useEffect } from "react"
import { useLocation } from "react-router-dom"
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet"
import { ListGroup, ListRow } from "@/components/ui/list-group"
import type { NavShellItem } from "@/components/ui/nav-shells"
import { useDialogHistory } from "@/lib/nav/useDialogHistory"

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
      <SheetContent side="bottom" showCloseButton={false} aria-describedby={undefined} className="lm-more-sheet">
        <SheetTitle className="lm-native-sheet-title mb-4 text-display-md">More</SheetTitle>
        <ListGroup>
          {items.map((item) => (
            <ListRow
              key={item.id}
              to={item.to ?? "/"}
              title={item.label}
              leading={item.icon}
              trailing={item.badge !== undefined ? <span className="text-metadata">{item.badge}</span> : undefined}
              lines={1}
            />
          ))}
        </ListGroup>
      </SheetContent>
    </Sheet>
  )
}

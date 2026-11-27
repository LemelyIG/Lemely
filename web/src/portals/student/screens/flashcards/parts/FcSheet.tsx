/* Hallmark · pre-emit critique: P4 H4 E3 S3 R5 V3 */
import type { ReactNode } from "react"
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet"
import { useDialogHistory } from "@/lib/nav/useDialogHistory"

/** The id of the consequence paragraph on an alert sheet. Only one sheet is open at a time, so one
 * id serves both (Delete deck, Delete card). An alertdialog is described by what will be lost. */
export const ALERT_BODY_ID = "fc-alert-body"

/** pr.css `.rvl.leave.ssh`: white, r28 top, 22px 20px 26px padding, 12px gap, grabber (kit).
 * `SheetContent` renders `nativeHeader` first in the content when the frame is not native, so the
 * title is rendered once, there, in both frames. */
export function FcSheet({
  open, onOpenChange, title, alert = false, dismissible = true, restoreFocusTo, children,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  alert?: boolean
  /** False while the sheet's action is in flight: Back then re-pushes its entry (the page stays) instead of
   * popping it while the caller's pending guard keeps the sheet open. */
  dismissible?: boolean
  /** Where focus goes on close when the opener is not a Radix trigger and may be gone (a menu item,
   * a deleted card's pencil). Null or absent keeps the sheet's own return to the opener. */
  restoreFocusTo?: () => HTMLElement | null
  children: ReactNode
}) {
  // Back and Escape both close the sheet (brief 2026-11-08:37). A menu-to-confirm hand-off closes the menu
  // (unwinding its entry) and opens the confirm (pushing its own), via the shared dialog-history stack.
  useDialogHistory({ open, dismissible, onClose: () => onOpenChange(false) })
  const heading = <SheetTitle className="block w-full text-start native:px-5 font-sans text-[22px] font-extrabold leading-tight text-on-surface">{title}</SheetTitle>
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="adaptive"
        role={alert ? "alertdialog" : "dialog"}
        aria-describedby={alert ? ALERT_BODY_ID : undefined}
        showCloseButton={false}
        nativeHeader={heading}
        nativeBodyClassName="px-5 pb-[26px] pt-3"
        className="sm:max-w-[420px]"
        onCloseAutoFocus={(event) => {
          const target = restoreFocusTo?.()
          if (!target) return
          event.preventDefault()
          target.focus()
        }}
      >
        <div className="grid gap-3">{children}</div>
      </SheetContent>
    </Sheet>
  )
}

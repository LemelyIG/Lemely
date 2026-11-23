/* Hallmark · pre-emit critique: P4 H4 E3 S3 R5 V3 */
import type { ReactNode } from "react"
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet"

/** pr.css `.rvl.leave.ssh`: white, r28 top, 22px 20px 26px padding, 12px gap, grabber (kit).
 * `SheetContent` renders `nativeHeader` first in the content when the frame is not native, so the
 * title is rendered once, there, in both frames. */
export function FcSheet({
  open, onOpenChange, title, alert = false, restoreFocusTo, children,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  alert?: boolean
  /** Where focus goes on close when the opener is not a Radix trigger and may be gone (a menu item,
   * a deleted card's pencil). Null or absent keeps the sheet's own return to the opener. */
  restoreFocusTo?: () => HTMLElement | null
  children: ReactNode
}) {
  const heading = <SheetTitle className="font-sans text-[22px] font-extrabold text-on-surface">{title}</SheetTitle>
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="adaptive"
        role={alert ? "alertdialog" : "dialog"}
        aria-describedby={undefined}
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

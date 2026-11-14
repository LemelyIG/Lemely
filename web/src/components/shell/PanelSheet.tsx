/* Hallmark · pre-emit critique: P4 H3 E4 S4 R4 V3 */
import { useEffect, useRef, useState, type ReactNode } from "react"
import { useLocation } from "react-router-dom"
import { Modal } from "@/components/ui/modal"

/** Native frame Task 8: the bell and account panels as content-fit sheets
 * (preview: `data-sheet="fit"`, no scale-back). `Modal` owns focus, Escape,
 * history and scroll lock, and returns focus to this trigger on close. Only
 * rendered on the native frame, so `Modal` always takes its sheet branch.
 *
 * A row inside never closes the sheet itself. It navigates, and the sheet
 * closes when the location changes (the way `NavDrawer` does). Closing first
 * would have `useDialogHistory` unwind its entry with `navigate(-1)` while the
 * URL is still the opening page, and that pop can land before a lazy route's
 * push does, so the tap would go nowhere. After the route has moved, the unwind
 * sees a different path and leaves the history alone. */
export function PanelSheet({
  triggerLabel,
  triggerClassName,
  trigger,
  title,
  children,
}: {
  triggerLabel: string
  triggerClassName?: string
  trigger: ReactNode
  title: string
  children: ReactNode
}) {
  const [open, setOpen] = useState(false)
  const openRef = useRef(open)
  openRef.current = open
  const location = useLocation()
  const close = () => setOpen(false)
  // `location.key`, not `pathname`, so a row to the page you are on still
  // dismisses. `lemelyDialog` skips the same-URL entry the dialog itself pushes.
  useEffect(() => {
    if (!openRef.current) return
    if ((location.state as { lemelyDialog?: boolean } | null)?.lemelyDialog) return
    setOpen(false)
  }, [location.key, location.state])
  return (
    <>
      <button
        type="button"
        aria-label={triggerLabel}
        aria-haspopup="dialog"
        aria-expanded={open}
        className={triggerClassName}
        onClick={() => setOpen(true)}
      >
        {trigger}
      </button>
      <Modal open={open} onClose={close} title={title} size="md" hideCloseButton>
        {children}
      </Modal>
    </>
  )
}

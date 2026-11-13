import { useState, type ReactNode } from "react"
import { Modal } from "@/components/ui/modal"

/** Native frame Task 8: the bell and account panels as content-fit sheets
 * (preview: `data-sheet="fit"`, no scale-back). `Modal` owns focus, Escape,
 * history and scroll lock, and returns focus to this trigger on close. Only
 * rendered on the native frame, so `Modal` always takes its sheet branch. */
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
  children: (close: () => void) => ReactNode
}) {
  const [open, setOpen] = useState(false)
  const close = () => setOpen(false)
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
        {children(close)}
      </Modal>
    </>
  )
}

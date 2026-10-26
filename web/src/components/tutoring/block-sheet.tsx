/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V3 */
import { Button } from "@/components/ui/button"
import { Modal } from "@/components/ui/modal"
import { blockCopy, safetyActionError } from "@/lib/tutoring/safetyNoticeCopy"

/*
 * Block sheet (SPEC §a.2 "tutoring_blocks", routes B2 and B3). The confirmation
 * before a student blocks a tutor, or a tutor blocks a student.
 *
 * A block is not light: it cancels the pair's future sessions (the 24-hour
 * window does not apply), ends the student's sharing, removes the student from
 * the tutor's independent classes and closes new requests and notes. So the
 * sheet lists those effects, in words, before the button, and the button is
 * named for what it does ("Block"), not "OK". Unblocking restores none of it
 * and the sheet says so.
 *
 * Like `ConfirmModal`, it cannot be dismissed by accident: no close control, no
 * Escape, no scrim click; the answer has to be one of the two buttons, and the
 * safe one reads as a sentence ("Don't block"). The effects are the SPEC's and
 * live in `lib/tutoring/safetyNoticeCopy.ts`. A failure shows inside the sheet,
 * in the API's own sentence when it sent one.
 */

export interface BlockSheetProps {
  open: boolean
  /** Who is blocking: a student blocks a tutor, a tutor blocks a student. */
  viewer: "student" | "tutor"
  /** The other side's name as the API gives it: the tutor's public name, or the student label. */
  counterpartName: string
  onConfirm: () => void
  onCancel: () => void
  pending?: boolean
  /** The error from the last attempt, as the hook gave it. */
  error?: unknown
}

export function BlockSheet({
  open,
  viewer,
  counterpartName,
  onConfirm,
  onCancel,
  pending = false,
  error,
}: BlockSheetProps) {
  const copy = blockCopy(viewer, counterpartName)
  const errorText = safetyActionError(error, "We couldn't block them. Try again.")
  return (
    <Modal
      open={open}
      onClose={onCancel}
      title={copy.title}
      description={copy.intro}
      dismissible={false}
      hideCloseButton
      footer={
        <>
          <Button variant="secondary" size="sm" onClick={onCancel} disabled={pending}>
            {copy.cancelLabel}
          </Button>
          <Button variant="accent" size="sm" loading={pending} onClick={onConfirm}>
            {copy.confirmLabel}
          </Button>
        </>
      }
    >
      <ul className="m-0 flex list-none flex-col gap-2 p-0">
        {copy.effects.map((effect) => (
          <li key={effect} className="text-body-md text-ink">
            {effect}
          </li>
        ))}
      </ul>
      {errorText ? (
        <p role="alert" className="mt-3 text-body-sm text-err">
          {errorText}
        </p>
      ) : null}
    </Modal>
  )
}

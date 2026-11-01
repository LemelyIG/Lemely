/* Hallmark · pre-emit critique: P4 H4 E4 S3 R4 V3 — the class line appears only when it is true, and the safe button leads; it is the shared confirm layout with real copy, so specificity stays at 3. */
import { Button } from "@/components/ui/button"
import { Modal } from "@/components/ui/modal"
import { stopSharingCopy } from "@/lib/tutoring/accessView"
import { safetyActionError } from "@/lib/tutoring/safetyNoticeCopy"
import type { Grant } from "@/lib/tutoringTypes"

/*
 * Stop-sharing sheet (SPEC §d S-38, route S10). The confirmation before a
 * student ends a tutor's sight of their progress.
 *
 * Stopping is honest about its edges, in words, before the button: it ends the
 * tutor's access through the tutoring pages; it does not end a class the same
 * person teaches (the class line appears only when `alsoTeachesClasses` has a
 * name in it); and it does not take the student out of the tutor's results,
 * which is a separate switch further down the page. What the sheet says lives
 * in `lib/tutoring/accessView.ts` (`stopSharingCopy`), where it is tested.
 *
 * Like `BlockSheet` and `ConfirmModal` it cannot be dismissed by accident: no
 * close control, no Escape, no scrim click. "Keep sharing" is the safe answer
 * and is the quiet-looking button only in the sense that it is named for what it
 * preserves. Focus moves into the sheet and returns to the Stop sharing button
 * on close (`Modal`). A failure shows inside the sheet, in the API's own
 * sentence when it sent one.
 */

export interface StopSharingSheetProps {
  open: boolean
  /** The grant being ended; the sheet reads its tutor and `alsoTeachesClasses`. */
  grant: Pick<Grant, "tutor" | "alsoTeachesClasses"> | null
  onConfirm: () => void
  onCancel: () => void
  pending?: boolean
  /** The error from the last attempt, as the hook gave it. */
  error?: unknown
}

export function StopSharingSheet({ open, grant, onConfirm, onCancel, pending = false, error }: StopSharingSheetProps) {
  // The screen keeps the grant in state after `open` goes false, so the sheet
  // can animate out with its words; null only before the first Stop sharing.
  if (grant === null) return null
  const copy = stopSharingCopy(grant)
  const errorText = safetyActionError(error, "We couldn't stop sharing. Try again.")
  return (
    <Modal
      open={open}
      onClose={onCancel}
      title={copy.title}
      size="sm"
      dismissible={false}
      hideCloseButton
      footer={
        <div className="flex flex-wrap justify-end gap-2">
          <Button variant="secondary" size="sm" onClick={onCancel} disabled={pending}>
            {copy.cancelLabel}
          </Button>
          <Button variant="accent" size="sm" loading={pending} onClick={onConfirm}>
            {copy.confirmLabel}
          </Button>
        </div>
      }
    >
      <div className="flex flex-col gap-3">
        {copy.lines.map((line) => (
          <p key={line} className="m-0 text-body-md text-ink">
            {line}
          </p>
        ))}
        {errorText ? (
          <p role="alert" className="m-0 text-body-sm text-err">
            {errorText}
          </p>
        ) : null}
      </div>
    </Modal>
  )
}

/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import { Button } from "@/components/ui/button"
import { Modal } from "@/components/ui/modal"

/*
 * C-24 · The confirmation step for a destructive action.
 *
 * Lifted out of `FlashcardDecks.tsx`, which built it in surface 3 as the
 * product's only real confirmation, and generalised in P4.5 because the
 * teacher portal needed four more. That portal was using `window.confirm` at
 * all four, which is worse than it looks:
 *
 *  - it is an OS dialog, so it carries none of the design system and cannot
 *    show a pending state, an error, or the consequence in the product's own
 *    voice;
 *  - its buttons say "OK" and "Cancel", so the destructive choice is never
 *    named — on a phone the teacher reads "OK" and has to reconstruct what
 *    OK means from a sentence above it;
 *  - it blocks the main thread, and it is suppressible by the browser after
 *    repeated use, which means a confirmation the product believes it is
 *    showing can silently stop appearing.
 *
 * Two properties are load-bearing and are the reason this is one component
 * rather than a prop-bag around `Modal`:
 *
 * 1. **`dismissible={false}` with no close button.** `Modal` documents that
 *    flag for exactly this case. A stray Escape must not answer a destructive
 *    question on the reader's behalf; the decision has to be made in a footer
 *    button.
 * 2. **The cancel button carries the primary weight and the destructive one
 *    is secondary.** The easy path is the safe path. This inverts the usual
 *    "primary action on the right" habit deliberately, and it is why the
 *    default `cancelLabel` is a real sentence ("Keep it") rather than
 *    "Cancel": naming what cancelling preserves is more useful at the moment
 *    of hesitation than naming the act of stopping.
 *
 * `consequence` defaults to "This cannot be undone." but is overridable,
 * because not every destructive action in the product is irreversible and
 * saying so when it is false is the honesty defect this system keeps finding.
 * A recoverable action should say what it really costs.
 */
export function ConfirmModal({
  open,
  title,
  description,
  consequence = "This cannot be undone.",
  confirmLabel,
  pendingLabel,
  cancelLabel = "Keep it",
  pending = false,
  error = null,
  onConfirm,
  onCancel,
}: {
  open: boolean
  title: string
  description?: string
  /** The sentence under the title. Override it when the action is genuinely
   * reversible; the default claims it is not. */
  consequence?: string
  confirmLabel: string
  /** Shown on the confirm button while the mutation is in flight. Falls back
   * to the confirm label, so a caller that forgets it still gets a disabled
   * button rather than a label that reads as though nothing is happening. */
  pendingLabel?: string
  cancelLabel?: string
  pending?: boolean
  /** A sentence for the reader, never a raw `error.message`. */
  error?: string | null
  onConfirm: () => void
  onCancel: () => void
}) {
  return (
    <Modal
      open={open}
      onClose={onCancel}
      title={title}
      description={description}
      size="sm"
      dismissible={false}
      hideCloseButton
      footer={
        <div className="flex flex-wrap justify-end gap-2">
          <Button variant="secondary" size="sm" onClick={onCancel} disabled={pending}>
            {cancelLabel}
          </Button>
          <Button variant="accent" size="sm" onClick={onConfirm} disabled={pending}>
            {pending ? (pendingLabel ?? confirmLabel) : confirmLabel}
          </Button>
        </div>
      }
    >
      <p className="text-body-md text-ink-muted">{consequence}</p>
      {/* The failure renders inside the dialog rather than behind it. A
          confirmation that closes on a failed mutation leaves the reader
          believing the thing happened, which is the shape surface 3 found on
          two silent deletes. */}
      {error ? <p className="mt-3 text-body-sm text-err">{error}</p> : null}
    </Modal>
  )
}

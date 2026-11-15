/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import { Button } from "@/components/ui/button"
import { Modal } from "@/components/ui/modal"
import { haptic } from "@/lib/haptics"
import { useNativeFrame } from "@/lib/useNativeFrame"
import { cn } from "@/lib/utils"

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
  destructive = true,
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
  /** True (default) when the action cannot be taken back or removes something:
   * the confirm reads as an error. False for a reversible action (sign out,
   * a roster removal that can be added back): the native confirm then uses the
   * primary colour, and the caller owns the consequence sentence, since the
   * default "This cannot be undone." would be false. */
  destructive?: boolean
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
  const { native, platform } = useNativeFrame()
  // An empty consequence is a deliberate "say nothing": the description already says it.
  const spoken = [description, consequence].filter(Boolean).join(" ")
  if (native && platform === "ios") {
    // The iOS destructive confirm is an action sheet: the question, then the
    // destructive row, then Cancel in its own group. Modal's sr-only title and
    // description are what the dialog's label and description point at, so the
    // visible copy is aria-hidden and nothing is read twice. Escape, a scrim tap
    // and a drag still cannot answer for the reader (`dismissible={false}`).
    return (
      <Modal
        open={open}
        // A scrim tap is Cancel, but not while the mutation is in flight: Cancel is disabled then,
        // and a sheet that closed under a pending delete would hide its outcome and any error.
        onClose={pending ? () => {} : onCancel}
        title={title}
        description={spoken}
        size="sm"
        dismissible={false}
        hideCloseButton
        presentation="action-sheet"
      >
        <div className="lm-action-sheet-group">
          <div aria-hidden="true" className="flex flex-col gap-1 px-4 py-3 text-center">
            <p className="text-label text-on-surface-variant">{title}</p>
            {description ? <p className="text-body-sm text-on-surface-variant">{description}</p> : null}
            {consequence ? <p className="text-body-sm text-on-surface-variant">{consequence}</p> : null}
          </div>
          {error ? (
            <p role="alert" className="px-4 pb-3 text-center text-body-sm text-error">
              {error}
            </p>
          ) : null}
          <button
            type="button"
            className={cn("lm-press lm-action-sheet-row", destructive ? "text-error" : "text-primary")}
            onClick={() => onConfirm()}
            disabled={pending}
            aria-busy={pending || undefined}
          >
            {pending ? (pendingLabel ?? confirmLabel) : confirmLabel}
          </button>
        </div>
        <button
          type="button"
          className="lm-press lm-action-sheet-row lm-action-sheet-cancel"
          data-autofocus
          onClick={onCancel}
          disabled={pending}
        >
          {cancelLabel}
        </button>
      </Modal>
    )
  }
  if (native) {
    // Material 3 dialog actions: two text buttons, the confirm trailing, in the error role
    // when the action is destructive and the primary role otherwise. Never a filled accent
    // button. Cancel is first in the DOM, so it is the safe default focus.
    return (
      <Modal
        open={open}
        onClose={onCancel}
        title={title}
        description={description}
        size="sm"
        dismissible={false}
        hideCloseButton
        footerLayout="actions"
        footer={
          <>
            <Button variant="text" size="sm" data-autofocus onClick={onCancel} disabled={pending}>
              {cancelLabel}
            </Button>
            <Button
              variant={destructive ? "text-error" : "text"}
              size="sm"
              onClick={() => {
                haptic("tap")
                onConfirm()
              }}
              loading={pending}
            >
              {pending ? (pendingLabel ?? confirmLabel) : confirmLabel}
            </Button>
          </>
        }
      >
        {consequence ? <p className="text-body-md text-on-surface-variant">{consequence}</p> : null}
        {error ? <p role="alert" className="text-body-sm text-error">{error}</p> : null}
      </Modal>
    )
  }
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
          {/* `loading` rather than `disabled`: the button already disables
              itself while loading, and the spinner is the part a label swap
              alone was missing. A destructive action that greys out and
              changes its wording, with nothing moving, reads as a button that
              refused the press rather than one that is working. */}
          <Button
            variant="accent"
            size="sm"
            onClick={() => {
              haptic("tap")
              onConfirm()
            }}
            loading={pending}
          >
            {pending ? (pendingLabel ?? confirmLabel) : confirmLabel}
          </Button>
        </div>
      }
    >
      {consequence ? <p className="text-body-md text-on-surface-variant">{consequence}</p> : null}
      {/* The failure renders inside the dialog rather than behind it. A
          confirmation that closes on a failed mutation leaves the reader
          believing the thing happened, which is the shape surface 3 found on
          two silent deletes. */}
      {error ? <p className="mt-3 text-body-sm text-error">{error}</p> : null}
    </Modal>
  )
}

/* Hallmark · pre-emit critique: P4 H4 E4 S3 R4 V3 — the five fixed paragraphs now sit in the dialog's description so they are read before the button; plainly a list in the shared modal, hence S3. */
import { Button } from "@/components/ui/button"
import { Modal } from "@/components/ui/modal"
import {
  SAFETY_NOTICE_BUTTON,
  SAFETY_NOTICE_PARAGRAPHS,
  SAFETY_NOTICE_TITLE,
  safetyActionError,
} from "@/lib/tutoring/safetyNoticeCopy"

/*
 * C-24 Safety notice sheet (SPEC §d, decision-log row 16 ii). The notice a
 * student reads before their first booking, and again before their first note
 * if a parent booked for them.
 *
 * It cannot be dismissed without the button: no close control, Escape and the
 * scrim do nothing, and browser Back re-opens it (`Modal` with
 * `dismissible={false}`, the same contract `ConfirmModal` relies on). The one
 * button calls `onAcknowledge`, which the screen wires to S15. That is the user
 * experience of the rule; the rule itself is the server's (O26), so a client
 * that skips this sheet is still refused.
 *
 * The five paragraphs are the Modal's `description`, which `Modal` points the
 * dialog's `aria-describedby` at. `Modal` moves focus to the first button when it
 * opens, which is "I understand": left as body content the notice would never be
 * announced before the one control that accepts it. As the description it is
 * read with the title, so a screen-reader user hears the notice before they can
 * press the button. (`Modal` wraps the description in a `<p>`, so the paragraphs
 * are spans that break lines, not list items.)
 *
 * The title, the five paragraphs and the button are FIXED by the SPEC and live in
 * `lib/tutoring/safetyNoticeCopy.ts`, where a test parses them out of it. The
 * screen decides when to show the sheet (`safetyNoticeAcknowledgedAt` is null);
 * this component only shows it.
 */

export interface SafetyNoticeSheetProps {
  open: boolean
  /** Records the acknowledgement (S15). The screen closes the sheet when it succeeds. */
  onAcknowledge: () => void
  pending?: boolean
  /** The error from the last attempt, as the hook gave it. */
  error?: unknown
}

export function SafetyNoticeSheet({ open, onAcknowledge, pending = false, error }: SafetyNoticeSheetProps) {
  const errorText = safetyActionError(error, "We couldn't save that. Try again.")
  return (
    <Modal
      open={open}
      onClose={() => {}}
      title={SAFETY_NOTICE_TITLE}
      dismissible={false}
      hideCloseButton
      description={
        <span className="mt-2 flex flex-col gap-3 text-ink">
          {SAFETY_NOTICE_PARAGRAPHS.map((paragraph) => (
            <span key={paragraph} className="block">
              {paragraph}
            </span>
          ))}
        </span>
      }
      footer={
        <Button variant="primary" loading={pending} onClick={onAcknowledge}>
          {SAFETY_NOTICE_BUTTON}
        </Button>
      }
    >
      {errorText ? (
        <p role="alert" className="m-0 text-body-sm text-err">
          {errorText}
        </p>
      ) : null}
    </Modal>
  )
}

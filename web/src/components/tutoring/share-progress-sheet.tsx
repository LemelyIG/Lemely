/* Hallmark · pre-emit critique: P4 H4 E4 S3 R4 V3 — says what is shared, for how long and who can see it before the button, in the student's own terms; the confirmation points at where it is undone. */
import { CheckCircle } from "@phosphor-icons/react"
import { Link } from "react-router-dom"
import { Button, buttonVariants } from "@/components/ui/button"
import { Modal } from "@/components/ui/modal"
import { bookingRefusalOf } from "@/lib/tutoring/bookingErrors"
import { SHARE_EXPLAINER, shareSheetLines } from "@/lib/tutoring/discovery"
import { cn } from "@/lib/utils"

/*
 * Share-progress sheet (SPEC §d, S-34 "Share my progress"; route S9). The
 * confirmation before a student lets one tutor see their progress.
 *
 * Sharing is the student's decision and the sheet makes it an informed one:
 * what the tutor can see (S-38's explainer, word for word), that it covers all
 * subjects until the student stops it, that every visit is recorded and the
 * student can see it, and that linked parents are told and can see who the
 * student shares with. It does not say anything is "safe". The two buttons are
 * "Share my progress" and "Don't share"; Escape and the scrim mean "Don't
 * share", which does nothing, so they are left working.
 *
 * Once S9 succeeds the sheet becomes its own receipt: it says the tutor can now
 * see the student's progress and links to Tutors & your data, where sharing is
 * stopped. A refusal reads through `bookingRefusalOf`: a tutor who has become
 * hidden is the same "isn't taking bookings" answer as everywhere else, and an
 * unconfirmed email says to confirm it. The screen owns the mutation.
 */

export const SHARE_ACCESS_PATH = "/student/tutor-access"

const SHARE_FALLBACK = "We couldn't share your progress. Try again."

export interface ShareProgressSheetProps {
  open: boolean
  tutorName: string
  onConfirm: () => void
  onCancel: () => void
  pending?: boolean
  /** The error from the last attempt, as the hook gave it. */
  error?: unknown
  /** True once S9 has answered; the sheet then shows the receipt. */
  shared?: boolean
}

export function ShareProgressSheet({
  open,
  tutorName,
  onConfirm,
  onCancel,
  pending = false,
  error,
  shared = false,
}: ShareProgressSheetProps) {
  if (shared) {
    return (
      <Modal
        open={open}
        onClose={onCancel}
        title="You're sharing your progress"
        size="sm"
        footer={
          <>
            <Link to={SHARE_ACCESS_PATH} className={cn(buttonVariants({ variant: "secondary", size: "sm" }))}>
              Open Tutors &amp; your data
            </Link>
            <Button variant="primary" size="sm" onClick={onCancel}>
              Done
            </Button>
          </>
        }
      >
        <p className="m-0 flex items-start gap-2 text-body-md text-ink">
          <CheckCircle size={20} weight="bold" className="mt-0.5 shrink-0 text-ok" aria-hidden />
          {tutorName} can now see your progress. You can stop sharing at any time in Tutors &amp; your data.
        </p>
      </Modal>
    )
  }

  const errorText =
    error === null || error === undefined ? null : (bookingRefusalOf(error)?.message ?? SHARE_FALLBACK)

  return (
    <Modal
      open={open}
      onClose={onCancel}
      title={`Share your progress with ${tutorName}?`}
      footer={
        <>
          <Button variant="secondary" size="sm" onClick={onCancel} disabled={pending}>
            Don&apos;t share
          </Button>
          <Button variant="primary" size="sm" loading={pending} onClick={onConfirm}>
            Share my progress
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <p className="m-0 text-body-md text-ink">{SHARE_EXPLAINER}</p>
        <ul className="m-0 flex list-none flex-col gap-2 p-0">
          {shareSheetLines(tutorName).map((line) => (
            <li key={line} className="text-body-md text-ink">
              {line}
            </li>
          ))}
        </ul>
        {errorText ? (
          <p role="alert" className="m-0 text-body-sm text-err">
            {errorText}
          </p>
        ) : null}
      </div>
    </Modal>
  )
}

/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V3 */
import { useState } from "react"
import { CheckCircle } from "@phosphor-icons/react"
import { Button } from "@/components/ui/button"
import { Modal } from "@/components/ui/modal"
import { Radio, RadioGroup } from "@/components/ui/radio"
import { Textarea } from "@/components/ui/textarea"
import {
  HELPLINE_LINE,
  REPORT_DETAILS_MAX,
  reportReasonsFor,
  safetyActionError,
  type ReportReason,
  type ReportTargetType,
} from "@/lib/tutoring/safetyNoticeCopy"

/*
 * Report sheet (SPEC §d, route R1). One sheet for every Report in the feature:
 * a tutor's profile, a review, a reply, a booking, a note. The screen says what
 * is being reported (`targetType`, `targetId` stays with the screen's own
 * submit), the reader picks why and may add words, and the screen sends it.
 *
 * Reporting is a safety path and is never made hard:
 *   - A reason is the only thing required; the free text is optional.
 *   - A safety concern shows the helpline beside it, the same line as the first
 *     booking notice, because a report is not a rescue.
 *   - "The session outcome is wrong" is offered only when the target is a
 *     booking, because that is the only report an admin can act on that way.
 *   - A failure names its cause when the API gave one ("You have already
 *     reported this.") and otherwise says plainly that it did not send. It never
 *     shows a raw error message.
 *   - Once it has gone through, the sheet says so and the screen can close it.
 *
 * Free text is plain text and is length-limited to what the database accepts.
 */

const SEND_FALLBACK = "We couldn't send your report. Try again."

export interface ReportSheetProps {
  open: boolean
  onClose: () => void
  targetType: ReportTargetType
  /** What is being reported, in the reader's words: "this review", "this note". */
  targetLabel: string
  /** Sends the report. The screen adds `targetType` and `targetId`. */
  onSubmit: (report: { reason: ReportReason; details: string | null }) => void
  pending?: boolean
  /** The error from the last attempt, as the hook gave it. */
  error?: unknown
  /** True once the report has been received; the sheet then shows the thanks. */
  sent?: boolean
}

export function ReportSheet({
  open,
  onClose,
  targetType,
  targetLabel,
  onSubmit,
  pending = false,
  error,
  sent = false,
}: ReportSheetProps) {
  const [reason, setReason] = useState<ReportReason | null>(null)
  const [details, setDetails] = useState("")
  const [wasOpen, setWasOpen] = useState(open)

  // A sheet opened again starts empty, whatever was typed the last time.
  if (open !== wasOpen) {
    setWasOpen(open)
    if (open) {
      setReason(null)
      setDetails("")
    }
  }

  const reasons = reportReasonsFor(targetType)
  const errorText = safetyActionError(error, SEND_FALLBACK)

  if (sent) {
    return (
      <Modal
        open={open}
        onClose={onClose}
        title="Report sent"
        size="sm"
        footer={
          <Button variant="primary" size="sm" onClick={onClose}>
            Done
          </Button>
        }
      >
        <p className="m-0 flex items-start gap-2 text-body-md text-ink">
          <CheckCircle size={20} weight="bold" className="mt-0.5 shrink-0 text-ok" aria-hidden />
          Thank you. Lemely has your report about {targetLabel}.
        </p>
      </Modal>
    )
  }

  const trimmed = details.trim()
  return (
    <Modal
      open={open}
      onClose={onClose}
      title={`Report ${targetLabel}`}
      description="Choose what is wrong. You can add a few words if it helps."
      footer={
        <>
          <Button variant="secondary" size="sm" onClick={onClose} disabled={pending}>
            Cancel
          </Button>
          <Button
            variant="primary"
            size="sm"
            loading={pending}
            disabled={reason === null}
            onClick={() => {
              if (reason !== null) onSubmit({ reason, details: trimmed === "" ? null : trimmed })
            }}
          >
            Send report
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <RadioGroup
          label="What is wrong?"
          value={reason ?? undefined}
          onValueChange={(value) => setReason(value as ReportReason)}
          disabled={pending}
        >
          {reasons.map((option) => (
            <Radio key={option.value} value={option.value} label={option.label} />
          ))}
        </RadioGroup>

        {reason === "safety_concern" ? (
          <p role="note" className="m-0 rounded-md border border-rule bg-warn-wash px-3 py-2.5 text-body-sm text-ink">
            {HELPLINE_LINE}
          </p>
        ) : null}

        <Textarea
          label="Anything else we should know? (optional)"
          value={details}
          maxLength={REPORT_DETAILS_MAX}
          rows={3}
          disabled={pending}
          onChange={(event) => setDetails(event.target.value)}
          error={errorText ?? undefined}
        />
      </div>
    </Modal>
  )
}

/* Hallmark · pre-emit critique: P4 H4 E4 S3 R4 V3 — one column in the order a person decides (what, how, how long, when), the summary and the counting notice right above the button, every refusal said where it happened. */
import { useRef, useState, type FormEvent, type ReactNode, type RefObject } from "react"
import { Link, useNavigate } from "react-router-dom"
import { Button, buttonVariants } from "@/components/ui/button"
import { ErrorState } from "@/components/ui/state-views"
import { Radio, RadioGroup } from "@/components/ui/radio"
import { Select } from "@/components/ui/select"
import { SlotPicker } from "@/components/ui/slot-picker"
import { Textarea } from "@/components/ui/textarea"
import { TutorFailure } from "@/components/tutoring/tutor-profile-view"
import { useCreateBooking, useTutorSlots } from "@/lib/hooks/useTutoringApi"
import { useOnlineStatus } from "@/lib/online"
import { describeQueryFailure } from "@/lib/queryFailure"
import {
  bookingRefusalOf,
  isTutorHidden,
  noteFieldTargets,
  refusalIsCurrent,
  type BookingRefusal,
} from "@/lib/tutoring/bookingErrors"
import {
  FEES_LINE,
  MODE_OPTIONS,
  countingNotice,
  slotAfterLengthChange,
  slotWindow,
  todayInZone,
} from "@/lib/tutoring/discovery"
import { TUTORING_ERROR_COPY } from "@/lib/tutoring/apiErrors"
import { formatSlotRange } from "@/lib/tutoring/slotGroups"
import { cn } from "@/lib/utils"
import type { Booking, BookingCreate, Slot, TutorProfile, TutoringMode } from "@/lib/tutoringTypes"

/*
 * Booking form (SPEC §d, S-35; P-07 mounts it again in the parent shell with
 * `audience="parent"`). Subject, way of meeting, length, a time from the slot
 * picker, an optional first note, a summary of what is being asked, and the
 * counting notice, then "Send request".
 *
 * What differs for a parent (F19, row 8b): there is no first-note field (only
 * the student may write one, and the server refuses it from a parent), the
 * request carries `studentId`, the screen supplies the required "Booking for"
 * selector as `childPicker`, and the counting notice is phrased for the child.
 * The safety notice (C-24) is the screen's concern, not this form's: it opens
 * the sheet before the form is usable and again if the server answers
 * `safety_notice_required`, which this form reports through
 * `onSafetyNoticeRequired`.
 *
 * Times are the tutor's, in the tutor's zone with its label, and the window
 * starts at the tutor's today. It asks for 14 days and "Show later dates" asks
 * for 28. The picker drops a chosen time that is no longer offered.
 *
 * Every refusal is said where it happened (`lib/tutoring/bookingErrors.ts`):
 * a taken time under the picker, with the times fetched again and the chosen
 * one cleared; a refused note on the note; "already waiting" with a link to the
 * requests; an unconfirmed email with the way to confirm it; a hidden tutor
 * replaces the form with the one "isn't taking bookings" answer. Missing
 * answers are named on the field and focus goes to the first one; the button is
 * never disabled for a reason the reader cannot see. Offline, the picker and
 * the button are disabled and the reason is written beside them.
 */

const DURATIONS = [45, 60, 90, 120] as const
type Duration = (typeof DURATIONS)[number]

const CHOOSE_CHILD = TUTORING_ERROR_COPY.student_required

interface Missing {
  child?: string
  subject?: string
  mode?: string
  slot?: string
}

export interface BookingFormProps {
  audience: "student" | "parent"
  tutor: TutorProfile
  /** Parent only: the child being booked for. */
  student?: { id: string; name: string }
  /** Parent only: the required "Booking for" control, rendered first. */
  childPicker?: ReactNode
  /** Where the requests are listed, for "already waiting". */
  sessionsPath: string
  /** Where "Find a tutor" goes if the tutor turns out to be hidden. */
  directoryPath: string
  /** Where a sent request goes (S-37 for a student). */
  bookedPath: (booking: Booking) => string
  /** Called when the server says the safety notice has not been read. */
  onSafetyNoticeRequired?: () => void
  /**
   * Whether the screen's safety notice sheet is open. When it closes after an
   * acknowledgement, the "read the safety notice" refusal is dropped instead of
   * waiting for the next submit.
   */
  safetyNoticeOpen?: boolean
  className?: string
}

/** The counting notice with its "Tutors & your data" phrase as a link, for the student. */
function CountingNotice({ audience, childName }: { audience: "student" | "parent"; childName?: string }) {
  const text = countingNotice(audience, childName)
  const phrase = "Tutors & your data"
  const at = audience === "student" ? text.indexOf(phrase) : -1
  return (
    <p role="note" className="m-0 max-w-prose text-body-sm text-ink-muted">
      {at < 0 ? (
        text
      ) : (
        <>
          {text.slice(0, at)}
          <Link to="/student/tutor-access" className="underline underline-offset-4">
            {phrase}
          </Link>
          {text.slice(at + phrase.length)}
        </>
      )}
    </p>
  )
}

/** One line of the request summary: the term at a fixed width, the answer beside it. */
function SummaryRow({ term, children }: { term: string; children: ReactNode }) {
  return (
    <div className="flex gap-x-4">
      <dt className="w-20 shrink-0 text-ink-muted">{term}</dt>
      <dd className="m-0 min-w-0 text-ink">{children}</dd>
    </div>
  )
}

function Refusal({ refusal, sessionsPath }: { refusal: BookingRefusal; sessionsPath: string }) {
  return (
    <div role="alert" className="flex flex-col items-start gap-2 text-body-sm text-err">
      <p className="m-0">{refusal.message}</p>
      {refusal.action === "open_requests" ? (
        <Link to={sessionsPath} className={cn(buttonVariants({ variant: "secondary", size: "sm" }))}>
          See your requests
        </Link>
      ) : null}
      {refusal.action === "verify_email" ? (
        <Link to="/verify-email" className={cn(buttonVariants({ variant: "secondary", size: "sm" }))}>
          Verify your email
        </Link>
      ) : null}
    </div>
  )
}

export function BookingForm({
  audience,
  tutor,
  student,
  childPicker,
  sessionsPath,
  directoryPath,
  bookedPath,
  onSafetyNoticeRequired,
  safetyNoticeOpen,
  className,
}: BookingFormProps) {
  const navigate = useNavigate()
  const online = useOnlineStatus()
  const [subjectCode, setSubjectCode] = useState(tutor.subjects.length === 1 ? tutor.subjects[0].code : "")
  const [mode, setMode] = useState<TutoringMode | "">(tutor.modes.length === 1 ? tutor.modes[0] : "")
  const [duration, setDuration] = useState<Duration>(60)
  const [slot, setSlot] = useState<Slot | null>(null)
  const [showLater, setShowLater] = useState(false)
  const [note, setNote] = useState("")
  const [otherNote, setOtherNote] = useState("")
  const [missing, setMissing] = useState<Missing>({})
  // The window starts at the tutor's today, fixed for the life of the form so the key does not move at midnight.
  const [today] = useState(() => todayInZone(tutor.zone, new Date()))

  const childRef = useRef<HTMLDivElement>(null)
  const subjectRef = useRef<HTMLDivElement>(null)
  const modeRef = useRef<HTMLDivElement>(null)
  const slotRef = useRef<HTMLDivElement>(null)

  const slots = useTutorSlots(tutor.tutorId, {
    from: today,
    days: slotWindow(showLater),
    durationMinutes: duration,
  })
  const create = useCreateBooking()
  const raised = create.isError ? bookingRefusalOf(create.error) : null
  const refusal = raised && refusalIsCurrent(raised, safetyNoticeOpen) ? raised : null

  if (isTutorHidden(slots.error) || isTutorHidden(create.error)) {
    return (
      <TutorFailure
        error={slots.error ?? create.error}
        onRetry={() => void slots.refetch()}
        directoryPath={directoryPath}
      />
    )
  }

  const subject = tutor.subjects.find((s) => s.code === subjectCode)
  const modeLabel = MODE_OPTIONS.find((m) => m.value === mode)?.label
  const offlineReason = online ? undefined : "You're offline. Reconnect to choose a time and send your request."

  function focusFirstMissing(next: Missing) {
    const order: [keyof Missing, RefObject<HTMLDivElement | null>][] = [
      ["child", childRef],
      ["subject", subjectRef],
      ["mode", modeRef],
      ["slot", slotRef],
    ]
    const hit = order.find(([key]) => next[key] !== undefined)
    hit?.[1].current?.querySelector<HTMLElement>("select, input, button")?.focus()
  }

  function submit(event: FormEvent) {
    event.preventDefault()
    if (create.isPending || !online) return
    const next: Missing = {}
    if (audience === "parent" && !student) next.child = CHOOSE_CHILD
    if (subjectCode === "") next.subject = "Choose a subject."
    if (mode === "") next.mode = "Choose how you would like to meet."
    if (slot === null) next.slot = "Choose a time."
    setMissing(next)
    if (Object.keys(next).length > 0 || mode === "" || slot === null) {
      focusFirstMissing(next)
      return
    }
    const body: BookingCreate = {
      tutorId: tutor.tutorId,
      subjectCode,
      mode,
      startsAt: slot.startsAt,
      durationMinutes: duration,
    }
    if (audience === "parent" && student) body.studentId = student.id
    if (mode === "other" && otherNote.trim() !== "") body.otherModeNote = otherNote.trim()
    if (audience === "student" && note.trim() !== "") body.firstNote = note.trim()
    create.mutate(body, {
      onSuccess: (booking) => navigate(bookedPath(booking), { replace: true }),
      onError: (error) => {
        const reason = bookingRefusalOf(error)
        if (reason?.action === "refresh_slots") {
          setSlot(null)
          void slots.refetch()
        }
        if (reason?.action === "choose_another_time") setSlot(null)
        if (reason?.action === "show_safety_notice") onSafetyNoticeRequired?.()
      },
    })
  }

  const noteTargets = noteFieldTargets({ audience, firstNote: note, mode, otherNote })
  const noteError = refusal?.field === "note" ? refusal.message : undefined
  const slotRefusal = refusal?.field === "slot" ? refusal : null
  const generalRefusal = refusal && refusal.field !== "note" && refusal.field !== "slot" ? refusal : null

  return (
    <form onSubmit={submit} noValidate className={cn("flex flex-col gap-6", className)}>
      {childPicker ? (
        <div ref={childRef} className="flex flex-col gap-1.5">
          {childPicker}
          {missing.child ? (
            <p role="alert" className="m-0 text-body-sm text-err">
              {missing.child}
            </p>
          ) : null}
        </div>
      ) : null}

      <div ref={subjectRef}>
        <Select
          label="Subject"
          value={subjectCode}
          error={missing.subject}
          onChange={(e) => {
            setSubjectCode(e.target.value)
            setMissing((m) => ({ ...m, subject: undefined }))
          }}
        >
          {tutor.subjects.length === 1 ? null : <option value="">Choose a subject</option>}
          {tutor.subjects.map((s) => (
            <option key={s.code} value={s.code}>
              {s.name}
            </option>
          ))}
        </Select>
      </div>

      <div ref={modeRef} className="flex flex-col gap-3">
        <RadioGroup
          label="How you will meet"
          orientation="horizontal"
          value={mode}
          error={missing.mode}
          onValueChange={(value) => {
            setMode(value as TutoringMode)
            setMissing((m) => ({ ...m, mode: undefined }))
          }}
        >
          {MODE_OPTIONS.filter((m) => tutor.modes.includes(m.value)).map((m) => (
            <Radio key={m.value} value={m.value} label={m.label} className="min-h-11 items-center" />
          ))}
        </RadioGroup>
        {mode === "other" ? (
          <div className="flex flex-col gap-3">
            {tutor.otherModeNote ? (
              <p className="m-0 max-w-prose whitespace-pre-line text-body-md text-ink">
                <span className="text-label text-ink">The tutor says. </span>
                {tutor.otherModeNote}
              </p>
            ) : null}
            <Textarea
              label="How would you like to meet? (optional)"
              rows={2}
              maxLength={300}
              value={otherNote}
              onChange={(e) => setOtherNote(e.target.value)}
              error={noteTargets.other ? noteError : undefined}
            />
          </div>
        ) : null}
      </div>

      <RadioGroup
        label="Length"
        orientation="horizontal"
        value={String(duration)}
        onValueChange={(value) => {
          const next = Number(value) as Duration
          // The chosen time was cut for the old length; the picker refetches for the new one.
          setSlot((current) => slotAfterLengthChange(current, duration, next))
          setDuration(next)
        }}
      >
        {DURATIONS.map((d) => (
          <Radio key={d} value={String(d)} label={`${d} minutes`} className="min-h-11 items-center" />
        ))}
      </RadioGroup>

      <div ref={slotRef} className="flex flex-col gap-3">
        <div className="text-label text-ink">Time</div>
        {slots.isError ? (
          <ErrorState
            compact
            heading="We couldn't load this tutor's times"
            body={describeQueryFailure(slots.error)}
            action={{ label: "Try again", onClick: () => void slots.refetch() }}
          />
        ) : (
          <SlotPicker
            slots={slots.data}
            value={slot?.startsAt ?? null}
            onChange={(next) => {
              setSlot(next)
              if (next) setMissing((m) => ({ ...m, slot: undefined }))
            }}
            loading={slots.isPending}
            disabled={!online || create.isPending}
            disabledReason={offlineReason}
          />
        )}
        {slots.data && !showLater ? (
          <div>
            <Button type="button" variant="ghost" size="sm" onClick={() => setShowLater(true)}>
              Show later dates
            </Button>
          </div>
        ) : null}
        {missing.slot ? (
          <p role="alert" className="m-0 text-body-sm text-err">
            {missing.slot}
          </p>
        ) : null}
        {slotRefusal ? (
          <p role="alert" className="m-0 text-body-sm text-err">
            {slotRefusal.message}
          </p>
        ) : null}
      </div>

      {audience === "student" ? (
        <Textarea
          label="First note (optional)"
          hint="Your tutor and your linked parents can read it. Keep contact details off Lemely."
          rows={3}
          maxLength={2000}
          value={note}
          onChange={(e) => setNote(e.target.value)}
          error={noteTargets.first ? noteError : undefined}
        />
      ) : null}

      <section aria-labelledby="booking-summary" className="flex flex-col gap-2 border-t border-rule pt-5">
        <h2 id="booking-summary" className="m-0 text-display-sm text-ink">
          Your request
        </h2>
        <dl className="m-0 flex flex-col gap-y-1 text-body-md">
          <SummaryRow term="Tutor">{tutor.publicName}</SummaryRow>
          <SummaryRow term="Subject">{subject?.name ?? "Not chosen yet"}</SummaryRow>
          <SummaryRow term="How">{modeLabel ?? "Not chosen yet"}</SummaryRow>
          <SummaryRow term="Length">{duration} minutes</SummaryRow>
          <SummaryRow term="When">
            {slot ? formatSlotRange(slot.startsAt, slot.endsAt, tutor.zone, tutor.zoneLabel) : "Not chosen yet"}
          </SummaryRow>
        </dl>
        <p className="m-0 text-body-sm text-ink-muted">{FEES_LINE}</p>
        <CountingNotice audience={audience} childName={student?.name} />
      </section>

      {generalRefusal ? <Refusal refusal={generalRefusal} sessionsPath={sessionsPath} /> : null}
      {create.isError && !refusal ? (
        <p role="alert" className="m-0 text-body-sm text-err">
          {describeQueryFailure(create.error)}
        </p>
      ) : null}

      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" variant="primary" loading={create.isPending} disabled={!online}>
          Send request
        </Button>
        {offlineReason ? <span className="text-body-sm text-ink-muted">{offlineReason}</span> : null}
      </div>
    </form>
  )
}

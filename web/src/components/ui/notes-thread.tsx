/* Hallmark · pre-emit critique: P4 H4 E4 S3 R3 V3 — fixed lines kept word for word; the frozen banner, composer, parents line and report line stack densely, and it has not been seen in a browser. */
import { useState, type ReactNode } from "react"
import { EyeSlash, Flag, PauseCircle } from "@phosphor-icons/react"
import { Button } from "@/components/ui/button"
import { Chip } from "@/components/ui/chip"
import { SkeletonBlock } from "@/components/ui/skeleton"
import { Textarea } from "@/components/ui/textarea"
import { TUTORING_ERROR_COPY, isTutoringError } from "@/lib/tutoring/apiErrors"
import {
  NOTES_CONTACT_DETAILS_MESSAGE,
  NOTES_FIXED_LINE,
  NOTES_FROZEN_LINE,
  NOTES_HIDDEN_PLACEHOLDER,
  NOTES_TUTOR_PARENTS_LINE,
  notesComposerState,
  safetyActionError,
  sendNoteDraft,
  type NotesViewer,
} from "@/lib/tutoring/safetyNoticeCopy"
import { formatTutorInstant } from "@/lib/tutoring/slotGroups"
import { cn } from "@/lib/utils"
import type { Note } from "@/lib/tutoringTypes"

/*
 * C-21 Notes thread (SPEC §d, §a.3 "Notes"). The notes between a student and a
 * tutor on one booking, oldest first, with who wrote each and when (in the
 * tutor's zone, like every tutoring time).
 *
 * What it does and does not do:
 *   - Every note body is plain text. React renders it as text and
 *     `whitespace-pre-wrap` keeps the author's line breaks; nothing is parsed
 *     into a link (SC-7).
 *   - A note an admin hid keeps its place and reads "Removed by Lemely". It has
 *     no Report button, because there is nothing left to report.
 *   - Reporting is the screen's: `onReport` is given the note. A parent's thread
 *     is read-only (`canPost` is always false for them) but they can still
 *     report, so the button does not depend on `canPost`.
 *   - Posting is allowed only when the API says `canPost` and the thread is not
 *     frozen. A frozen thread (`notesFrozen`, a report is open) says so and
 *     shows no composer. When posting is closed for any other reason the
 *     student or tutor is told that, in the API's own words.
 *   - The fixed lines are the SPEC's: the report line always, and for a tutor
 *     composer "This student's parents can read these notes." (SC-9).
 *   - What the foot of the thread shows (composer, parents line, frozen line,
 *     closed line) is decided by `notesComposerState`, which is tested; this file
 *     only draws it. The draft is cleared when `onPost` resolves and kept when
 *     it rejects (`sendNoteDraft`).
 *
 * The first-note safety notice (C-24) is the screen's to show before it mounts a
 * student's composer. A refused contact detail is worded for notes here, with
 * `NOTES_CONTACT_DETAILS_MESSAGE`: the sentence every other free-text screen
 * shows points people at the session notes, which would be circular in the
 * notes themselves. Only that refusal sits on the field; any other failure is
 * an alert line under it.
 */

const SENT_FALLBACK = "We couldn't send your note. Try again."

export interface NotesThreadProps {
  notes: readonly Note[]
  /** Who is looking. A parent reads and reports; they never write. */
  viewer: NotesViewer
  /** `NotesPage.canPost`, as the API computed it for this viewer. */
  canPost: boolean
  /** `Booking.notesFrozen`. */
  frozen: boolean
  /** The tutor's zone and its label, for the time on each note. */
  zone: string
  zoneLabel: string
  /**
   * Sends a note. It must return the promise (`mutateAsync`, not `mutate`): the
   * box clears when it resolves and keeps the author's text when it rejects.
   */
  onPost?: (body: string) => Promise<unknown>
  posting?: boolean
  /** The error from the last post, as the hook gave it. */
  postError?: unknown
  /** Opens the report sheet for a note. Omit to hide the Report buttons. */
  onReport?: (note: Note) => void
  loading?: boolean
  hasMore?: boolean
  loadingMore?: boolean
  onLoadMore?: () => void
  /** A line shown under the thread for this viewer, e.g. the parent's read-only line. */
  footnote?: ReactNode
  className?: string
}

const NOTE_MAX = 2000

export function NotesThread({
  notes,
  viewer,
  canPost,
  frozen,
  zone,
  zoneLabel,
  onPost,
  posting = false,
  postError,
  onReport,
  loading = false,
  hasMore = false,
  loadingMore = false,
  onLoadMore,
  footnote,
  className,
}: NotesThreadProps) {
  const [draft, setDraft] = useState("")
  const trimmed = draft.trim()
  const foot = notesComposerState({ viewer, canPost, frozen, loading, canSend: onPost !== undefined })

  const errorText = safetyActionError(postError, SENT_FALLBACK, NOTES_CONTACT_DETAILS_MESSAGE)
  // The refusal is about what was typed, so it sits on the field. A busy server
  // or a closed thread is not, and is told apart in an alert line.
  const contactRefused = isTutoringError(postError, "contact_details_not_allowed")

  async function send() {
    if (!onPost || trimmed.length === 0 || posting) return
    // The hook reports a failure through `postError`; a refused post keeps the text.
    if (await sendNoteDraft(onPost, trimmed)) setDraft("")
  }

  return (
    <section className={cn("flex flex-col gap-4", className)} aria-label="Session notes">
      {loading ? (
        <div className="flex flex-col gap-3" role="status" aria-label="Loading notes">
          <SkeletonBlock announce={false} className="h-16" />
          <SkeletonBlock announce={false} className="h-16" />
        </div>
      ) : notes.length === 0 ? (
        <p className="m-0 text-body-md text-ink-muted">No notes yet.</p>
      ) : (
        <ol className="m-0 flex list-none flex-col gap-3 p-0">
          {notes.map((note) => (
            <li
              key={note.noteId}
              className="flex flex-col gap-1.5 rounded-lg border border-rule bg-paper-raised p-4"
            >
              <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <span className="text-label text-ink">{note.authorName}</span>
                <Chip tone={note.authorParty === "tutor" ? "info" : "neutral"}>
                  {note.authorParty === "tutor" ? "Tutor" : "Student"}
                </Chip>
                <span className="text-body-sm text-ink-muted">
                  {formatTutorInstant(note.createdAt, zone, zoneLabel)}
                </span>
              </div>

              {note.hidden || note.body === null ? (
                <p className="m-0 flex items-center gap-1.5 text-body-md text-ink-muted">
                  <EyeSlash size={16} aria-hidden />
                  {NOTES_HIDDEN_PLACEHOLDER}
                </p>
              ) : (
                <p className="m-0 whitespace-pre-wrap break-words text-body-md text-ink">{note.body}</p>
              )}

              {onReport && !note.hidden && note.body !== null ? (
                <div className="flex justify-end">
                  <Button
                    variant="ghost"
                    size="sm"
                    icon={<Flag size={14} />}
                    aria-label={`Report the note from ${note.authorName}`}
                    onClick={() => onReport(note)}
                  >
                    Report
                  </Button>
                </div>
              ) : null}
            </li>
          ))}
        </ol>
      )}

      {hasMore && onLoadMore ? (
        <div>
          <Button variant="secondary" size="sm" loading={loadingMore} onClick={onLoadMore}>
            Show more notes
          </Button>
        </div>
      ) : null}

      {foot.frozenLine ? (
        <p
          role="status"
          className="m-0 flex items-start gap-2 rounded-md border border-rule bg-info-wash px-3 py-2.5 text-body-sm text-ink"
        >
          <PauseCircle size={16} className="mt-0.5 shrink-0 text-info" aria-hidden />
          {NOTES_FROZEN_LINE}
        </p>
      ) : null}

      {foot.composer ? (
        <form
          className="flex flex-col gap-2"
          onSubmit={(event) => {
            event.preventDefault()
            void send()
          }}
        >
          <Textarea
            label="Write a note"
            value={draft}
            maxLength={NOTE_MAX}
            rows={3}
            autoResize
            onChange={(event) => setDraft(event.target.value)}
            error={contactRefused ? (errorText ?? undefined) : undefined}
          />
          {errorText && !contactRefused ? (
            <p role="alert" className="m-0 text-body-sm text-err">
              {errorText}
            </p>
          ) : null}
          {/* Always shown with a tutor's composer, error or not (SC-9), so it is
              a line of its own rather than the field's hint, which an error replaces. */}
          {foot.tutorParentsLine ? (
            <p className="m-0 text-body-sm text-ink-muted">{NOTES_TUTOR_PARENTS_LINE}</p>
          ) : null}
          <div className="flex justify-end">
            <Button type="submit" variant="primary" size="sm" loading={posting} disabled={trimmed.length === 0}>
              Send note
            </Button>
          </div>
        </form>
      ) : foot.closedLine ? (
        <p className="m-0 text-body-sm text-ink-muted">{TUTORING_ERROR_COPY.notes_closed}</p>
      ) : null}

      {footnote ? <div className="text-body-sm text-ink-muted">{footnote}</div> : null}
      <p className="m-0 text-body-sm text-ink-muted">{NOTES_FIXED_LINE}</p>
    </section>
  )
}

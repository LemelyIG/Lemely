/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import { useMemo, useState, type FormEvent } from "react"
import { Trash } from "@phosphor-icons/react"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Chip } from "@/components/ui/chip"
import { EmptyState, ErrorState } from "@/components/ui/state-views"
import { initialsOf, relativeTime } from "@/lib/utils"
import {
  useAnnouncements,
  useCreateAnnouncement,
  useDeleteAnnouncement,
  useTeacherClasses,
} from "@/lib/hooks/useTeacherApi"
import { useAdminSchools } from "@/lib/hooks/useSchoolApi"
import { ListSkeleton } from "@/components/ui/loading-shapes"
import { ConfirmModal } from "@/components/ui/confirm-modal"
import {
  teacherLoadFailureMessage,
  teacherMutationFailureMessage,
} from "@/lib/teacherOutcome"
import { useProfile } from "@/lib/hooks/useMeApi"
import type { Announcement } from "@/lib/teacherTypes"

/*
 * Announcement composer (T-12) at `/teacher/announcements`, on P3.8 chunk a's
 * `/api/teacher/announcements` (POST/GET/DELETE).
 *
 * **The audience is exclusive, structurally.** `AnnouncementCreateRequest`
 * takes `classIds` OR `schoolWide`, never both — the two audiences overlap, so
 * a combined request would hand Phase 5's unwritten delivery layer two rows
 * for one recipient, and chunk a's follow-up made it a 422. The control here
 * is a radio pair, not two independent checkboxes, so the rejected state is
 * unreachable rather than merely validated. Do not "restore" the union.
 *
 * **School-wide is `school_admin`-only** (a teacher requesting it is a 403).
 * The option only renders for that role, and its school picker is fed by
 * `GET /api/school/seats` (`useAdminSchools`) — the only client-reachable
 * source of the caller's school memberships. An admin can administer several
 * schools, which is why `schoolId` is required alongside the flag rather than
 * inferred from it.
 *
 * **Fan-out is all-or-nothing.** A teacher targeting ten classes but owning
 * nine gets a 403 and *zero* rows. The composer therefore surfaces the error
 * and reports the exact rows the server says it created (`announcements`),
 * rather than claiming a send it cannot verify.
 *
 * Two things the spec asks for that are honestly absent, per D3.14 §2 — do
 * not stub either:
 * - **No attachment.** There is no attachment column and no storage wiring.
 *   It is omitted entirely rather than rendered as a disabled upload control,
 *   the same treatment T-05's absent integrity signals got.
 * - **`publishAt` is stored but never read.** No scheduler exists; delivery is
 *   Phase 5's. The field is offered because the column is real, and it is
 *   labelled with exactly what it does and does not do. Never word it as
 *   "will be sent at".
 *
 * **Nothing delivers these to a student yet.** There is no student-facing
 * announcement surface and no notification send path (MISSION §4 puts both in
 * Phase 5). The screen says so in the composer, because a teacher who writes
 * an announcement will otherwise reasonably assume it reached someone.
 *
 * The "how it appears to a student" preview is therefore rendered as exactly
 * what is stored — title, body, audience, timestamp — and captioned as a
 * preview of the record, not of a student's inbox, since no student inbox
 * design exists to preview against.
 */

type Audience = "classes" | "school"

function AnnouncementRow({
  announcement,
  audienceLabel,
  onDelete,
  deleting,
}: {
  announcement: Announcement
  audienceLabel: string
  onDelete: () => void
  deleting: boolean
}) {
  return (
    <li className="bg-paper-raised border border-rule rounded-lg px-4 py-3.5 flex items-start gap-3">
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-body-md text-ink font-medium">{announcement.title}</span>
          <Chip tone="neutral">{audienceLabel}</Chip>
          {announcement.publishAt ? <Chip tone="warn">Dated</Chip> : null}
        </div>
        <p className="text-body-md text-ink-muted m-0 mt-1 whitespace-pre-wrap text-pretty">
          {announcement.body}
        </p>
        <div className="text-body-sm text-ink-muted mt-1.5">
          Written {relativeTime(announcement.createdAt)}
          {announcement.publishAt
            ? ` · dated ${new Date(announcement.publishAt).toLocaleString()}`
            : ""}
        </div>
      </div>
      <Button
        type="button"
        variant="secondary"
        size="sm"
        onClick={onDelete}
        disabled={deleting}
        aria-label={`Delete announcement ${announcement.title}`}
      >
        <Trash size={14} aria-hidden />
        Delete
      </Button>
    </li>
  )
}

export function Announcements() {
  const profileQuery = useProfile()
  const classesQuery = useTeacherClasses()
  const isSchoolAdmin = profileQuery.data?.role === "school_admin"
  const schoolsQuery = useAdminSchools(isSchoolAdmin)

  const announcementsQuery = useAnnouncements()
  const createAnnouncement = useCreateAnnouncement()
  const deleteAnnouncement = useDeleteAnnouncement()

  const [title, setTitle] = useState("")
  const [body, setBody] = useState("")
  const [audience, setAudience] = useState<Audience>("classes")
  const [selectedClassIds, setSelectedClassIds] = useState<string[]>([])
  const [schoolId, setSchoolId] = useState("")
  const [publishAt, setPublishAt] = useState("")
  const [sentCount, setSentCount] = useState<number | null>(null)
  const [pendingDelete, setPendingDelete] = useState<Announcement | null>(null)

  const classes = useMemo(() => classesQuery.data?.classes ?? [], [classesQuery.data])
  const classNameById = useMemo(
    () => new Map(classes.map((c) => [c.id, c.label])),
    [classes],
  )
  const schools = useMemo(() => schoolsQuery.data?.schools ?? [], [schoolsQuery.data])
  const schoolNameById = useMemo(
    () => new Map(schools.map((s) => [s.schoolId, s.schoolName])),
    [schools],
  )

  /** An announcement row stores a raw class/school id and nothing else, so
   * naming it means resolving against the caller's own lists. An id we can't
   * resolve is labelled honestly rather than guessed at. */
  function audienceLabelFor(a: Announcement): string {
    if (a.classId) return classNameById.get(a.classId) ?? "A class"
    if (a.schoolId) return schoolNameById.get(a.schoolId) ?? "Whole school"
    return "Unknown audience"
  }

  const canSubmit =
    title.trim().length > 0 &&
    body.trim().length > 0 &&
    (audience === "classes" ? selectedClassIds.length > 0 : schoolId.length > 0)

  function toggleClass(id: string) {
    setSelectedClassIds((prev) =>
      prev.includes(id) ? prev.filter((c) => c !== id) : [...prev, id],
    )
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault()
    if (!canSubmit) return
    setSentCount(null)
    createAnnouncement.mutate(
      {
        title: title.trim(),
        body: body.trim(),
        // Exactly one audience is ever sent — the other stays at its default,
        // because supplying both is a 422 by design.
        ...(audience === "classes"
          ? { classIds: selectedClassIds }
          : { schoolWide: true, schoolId }),
        publishAt: publishAt ? new Date(publishAt).toISOString() : null,
      },
      {
        onSuccess: (data) => {
          setSentCount(data.announcements.length)
          setTitle("")
          setBody("")
          setSelectedClassIds([])
          setPublishAt("")
        },
      },
    )
  }

  const announcements = announcementsQuery.data?.announcements ?? []

  return (
    <div className="flex flex-col gap-6 min-w-0">
      <header>
        <h1 className="text-display-md text-ink m-0">Announcements</h1>
        <p className="text-body-md text-ink-muted m-0 mt-1 max-w-[640px] text-pretty">
          Write a note for one or more of your classes. Announcements are saved against the
          classes you pick. <strong className="text-ink font-medium">Students cannot see them
          yet</strong>, and no notification is sent; the student-facing surface and delivery
          arrive in a later phase.
        </p>
      </header>

      <form
        onSubmit={handleSubmit}
        className="bg-paper-raised border border-rule rounded-lg p-[18px] flex flex-col gap-4 max-w-[720px]"
      >
        <label className="flex flex-col gap-1.5 text-body-sm text-ink-muted">
          Title
          <input
            required
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="e.g. Thermal physics test moved to Thursday"
            className="border border-rule bg-paper-raised rounded-lg px-3 py-2 text-body-md text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
          />
        </label>

        <label className="flex flex-col gap-1.5 text-body-sm text-ink-muted">
          Message
          <textarea
            required
            value={body}
            onChange={(e) => setBody(e.target.value)}
            rows={5}
            placeholder="Plain text. Line breaks are kept as you type them."
            className="border border-rule bg-paper-raised rounded-lg px-3 py-2 text-body-lg text-ink resize-y focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
          />
        </label>

        <fieldset className="border-0 p-0 m-0 flex flex-col gap-2">
          <legend className="text-eyebrow text-ink-faint p-0 mb-1">
            Audience
          </legend>
          <label className="flex items-center gap-2 text-body-md text-ink">
            <input
              type="radio"
              name="audience"
              value="classes"
              checked={audience === "classes"}
              onChange={() => setAudience("classes")}
              className="accent-accent"
            />
            My classes
          </label>

          {audience === "classes" ? (
            <div className="ps-6 flex flex-col gap-1.5">
              {classesQuery.isPending ? (
                <span className="text-body-sm text-ink-muted">Loading your classes…</span>
              ) : classesQuery.isError ? (
                <span className="text-body-sm text-err">
                  Couldn't load your classes: {teacherLoadFailureMessage(classesQuery.error)}
                </span>
              ) : classes.length === 0 ? (
                <span className="text-body-sm text-ink-muted">
                  You have no classes yet. Create one before writing an announcement.
                </span>
              ) : (
                classes.map((c) => (
                  <Checkbox
                    key={c.id}
                    checked={selectedClassIds.includes(c.id)}
                    onChange={() => toggleClass(c.id)}
                    label={c.label}
                  />
                ))
              )}
            </div>
          ) : null}

          {isSchoolAdmin ? (
            <>
              <label className="flex items-center gap-2 text-body-md text-ink">
                <input
                  type="radio"
                  name="audience"
                  value="school"
                  checked={audience === "school"}
                  onChange={() => setAudience("school")}
                  className="accent-accent"
                />
                Whole school
              </label>
              {audience === "school" ? (
                <div className="ps-6">
                  {schoolsQuery.isPending ? (
                    <span className="text-body-sm text-ink-muted">Loading your schools…</span>
                  ) : schoolsQuery.isError ? (
                    <span className="text-body-sm text-err">
                      Couldn't load your schools: {teacherLoadFailureMessage(schoolsQuery.error)}
                    </span>
                  ) : (
                    <label className="flex flex-col gap-1.5 text-body-sm text-ink-muted max-w-[320px]">
                      School
                      <select
                        required
                        value={schoolId}
                        onChange={(e) => setSchoolId(e.target.value)}
                        className="border border-rule bg-paper-raised rounded-lg px-3 py-2 text-body-md text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
                      >
                        <option value="" disabled>
                          Choose a school…
                        </option>
                        {schools.map((s) => (
                          <option key={s.schoolId} value={s.schoolId}>
                            {s.schoolName}
                          </option>
                        ))}
                      </select>
                    </label>
                  )}
                </div>
              ) : null}
            </>
          ) : null}
          <p className="text-body-sm text-ink-muted m-0 mt-0.5 text-pretty">
            One audience or the other. A class announcement and a school-wide one would reach the
            same student twice.
          </p>
        </fieldset>

        <label className="flex flex-col gap-1.5 text-body-sm text-ink-muted max-w-[280px]">
          Date it (optional)
          <input
            type="datetime-local"
            value={publishAt}
            onChange={(e) => setPublishAt(e.target.value)}
            className="border border-rule bg-paper-raised rounded-lg px-3 py-2 text-data-md text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
          />
          <span className="text-body-sm text-ink-muted text-pretty">
            Recorded with the announcement. It does <strong>not</strong> schedule anything. There
            is no delivery yet, so nothing will fire at this time.
          </span>
        </label>

        <div className="flex items-center gap-3 flex-wrap">
          <Button type="submit" variant="ink" disabled={!canSubmit || createAnnouncement.isPending}>
            {createAnnouncement.isPending ? "Saving…" : "Save announcement"}
          </Button>
          {sentCount != null ? (
            <span role="status" className="text-body-sm text-ok">
              Saved to {sentCount} class{sentCount === 1 ? "" : "es"}.
            </span>
          ) : null}
        </div>

        {createAnnouncement.isError ? (
          <div role="alert" className="text-body-sm text-err">
            Couldn't save it: {teacherMutationFailureMessage(createAnnouncement.error)}
            <span className="block text-ink-muted mt-0.5">
              Nothing was written. An announcement is saved for every class you picked or for
              none of them.
            </span>
          </div>
        ) : null}
      </form>

      {/* Preview of the stored record, deliberately not of a student's inbox —
          no student-facing surface exists to preview against. */}
      {title.trim() || body.trim() ? (
        <section className="max-w-[720px]">
          <h2 className="text-eyebrow text-ink-faint m-0 mb-2">
            Preview
          </h2>
          <div className="bg-paper-sunk border border-rule rounded-lg p-4">
            <div className="flex items-center gap-2">
              <span className="h-7 w-7 rounded-full bg-accent-wash text-accent flex items-center justify-center text-data-sm">
                {initialsOf(profileQuery.data?.displayName ?? profileQuery.data?.email ?? "?")}
              </span>
              <span className="text-body-sm text-ink-muted">
                {profileQuery.data?.displayName ?? profileQuery.data?.email ?? "You"}
              </span>
            </div>
            <div className="text-display-sm text-ink mt-2.5">{title || "Untitled"}</div>
            <p className="text-body-lg text-ink-muted m-0 mt-1 whitespace-pre-wrap text-pretty">
              {body || "No message yet."}
            </p>
          </div>
          <p className="text-body-sm text-ink-muted mt-1.5 m-0 text-pretty">
            This shows what gets stored. It is not a preview of a student's view, and students have
            no announcements surface yet.
          </p>
        </section>
      ) : null}

      <section>
        <h2 className="text-eyebrow text-ink-faint m-0 mb-2.5">
          Your announcements
        </h2>
        {announcementsQuery.isPending ? (
          <ListSkeleton rows={4} />
        ) : announcementsQuery.isError ? (
          <ErrorState
            heading="Couldn't load your announcements"
            body={teacherLoadFailureMessage(announcementsQuery.error)}
            action={{ label: "Retry", onClick: () => announcementsQuery.refetch() }}
          />
        ) : announcements.length === 0 ? (
          <EmptyState
            heading="Nothing written yet"
            body="Announcements you write appear here, newest first, with the class they were saved against. You can delete one at any time."
          />
        ) : (
          <ul className="flex flex-col gap-2 m-0 p-0 list-none">
            {announcements.map((a) => (
              <AnnouncementRow
                key={a.announcementId}
                announcement={a}
                audienceLabel={audienceLabelFor(a)}
                onDelete={() => setPendingDelete(a)}
                deleting={deleteAnnouncement.isPending}
              />
            ))}
          </ul>
        )}
        <ConfirmModal
          open={pendingDelete !== null}
          title="Delete this announcement?"
          description={pendingDelete ? `"${pendingDelete.title}"` : undefined}
          consequence="It stops being visible to everyone it was sent to. You would have to write it again."
          confirmLabel="Delete"
          pendingLabel="Deleting…"
          pending={deleteAnnouncement.isPending}
          error={
            deleteAnnouncement.isError
              ? teacherMutationFailureMessage(deleteAnnouncement.error)
              : null
          }
          onCancel={() => setPendingDelete(null)}
          onConfirm={() => {
            if (!pendingDelete) return
            deleteAnnouncement.mutate(pendingDelete.announcementId, {
              onSuccess: () => setPendingDelete(null),
            })
          }}
        />
        {deleteAnnouncement.isError ? (
          <div role="alert" className="text-body-sm text-err mt-2">
            Couldn't delete it: {teacherMutationFailureMessage(deleteAnnouncement.error)}
          </div>
        ) : null}
      </section>
    </div>
  )
}

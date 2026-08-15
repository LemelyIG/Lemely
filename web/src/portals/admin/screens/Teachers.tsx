/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import { useState } from "react"
import { Card, CardBody } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Select } from "@/components/ui/select"
import { Eyebrow } from "@/components/ui/primitives"
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table"
import { EmptyState, ErrorState } from "@/components/ui/state-views"
import { ListSkeleton, PageHeaderSkeleton } from "@/components/ui/loading-shapes"
import { Modal } from "@/components/ui/modal"
import {
  adminLoadFailureMessage,
  adminMutationFailureMessage,
  teacherRemovalFailureMessage,
} from "@/lib/adminOutcome"
import { useInviteTeacher, useRemoveTeacher, useSchoolTeachers } from "@/lib/hooks/useSchoolApi"
import type { SchoolTeacher, SchoolTeacherGroup } from "@/lib/schoolTypes"

/**
 * K-03 · Teachers.
 *
 * Reads `GET /api/school/teachers`; writes through `POST /school/teachers/invite`
 * and `POST /school/teachers/{id}/remove`.
 *
 * ── Removal is the whole screen ────────────────────────────────────────────
 *
 * K-03's requirement is precise: "remove a teacher, with reassignment of their
 * classes handled explicitly rather than orphaned". Three things follow, and
 * each one is a decision this screen makes rather than a default it inherits:
 *
 * **The dialog will not submit without a successor.** For a teacher who owns
 * classes the select has no empty option and the button stays disabled until
 * one is chosen. The backend refuses the orphaning case with a 409 regardless,
 * but a screen that lets you press a button the server will reject has taught
 * you nothing about why.
 *
 * **The successor list is this school's other teachers, and nobody else.** It
 * is filtered from the roster already on screen, so it cannot offer a teacher
 * from another school (which the backend also refuses) or the person leaving.
 *
 * **The word is "remove", not "delete", because the account survives.** The
 * route deletes the school membership only. Their name stays on the
 * announcements they wrote and the marking they did. A button labelled "Delete
 * teacher" would describe a destruction that does not happen, which is the
 * inverse of the usual honesty failure and just as wrong.
 */
export function Teachers() {
  const { data, isPending, isError, error } = useSchoolTeachers()

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-col gap-1.5">
        <Eyebrow>School admin</Eyebrow>
        <h1 className="text-display-lg text-ink">Teachers</h1>
        <p className="max-w-prose text-body-md text-ink-muted">
          Who teaches here, how much each of them carries, and how to add or move someone on.
        </p>
      </header>

      {isPending ? (
        <>
          <PageHeaderSkeleton />
          <ListSkeleton rows={4} avatar />
        </>
      ) : isError ? (
        <ErrorState
          heading="We couldn't load your staff list"
          body={adminLoadFailureMessage(error)}
          action={{ label: "Try again", onClick: () => window.location.reload() }}
        />
      ) : data.schools.length === 0 ? (
        <EmptyState
          heading="No school is assigned to you"
          body="This account holds no school membership, so there is no staff list to show."
        />
      ) : (
        data.schools.map((group) => <SchoolStaff key={group.schoolId} group={group} />)
      )}
    </div>
  )
}

function SchoolStaff({ group }: { group: SchoolTeacherGroup }) {
  const [removing, setRemoving] = useState<SchoolTeacher | null>(null)

  return (
    <section className="flex flex-col gap-4" aria-label={group.schoolName}>
      <h2 className="text-display-sm text-ink">{group.schoolName}</h2>

      <InviteTeacherPanel schoolId={group.schoolId} />

      {group.teachers.length === 0 ? (
        <EmptyState
          marginalia="an empty staff room"
          heading="No teachers yet"
          body="Invite one above. They will be able to create classes and mark papers for this school straight away."
        />
      ) : (
        <Table>
          <THead>
            <tr>
              <TH>Teacher</TH>
              <TH numeric>Classes</TH>
              <TH numeric>Students</TH>
              <TH>
                <span className="sr-only">Actions</span>
              </TH>
            </tr>
          </THead>
          <TBody>
            {group.teachers.map((teacher) => (
              <TR key={teacher.userId}>
                <TD>
                  <div className="flex flex-col">
                    <span className="text-body-sm text-ink">
                      {teacher.displayName ?? teacher.email}
                    </span>
                    {teacher.displayName ? (
                      <span className="text-body-sm text-ink-faint">{teacher.email}</span>
                    ) : null}
                  </div>
                </TD>
                <TD numeric>{teacher.classCount}</TD>
                {/* Distinct across their classes here, so a student they teach
                    twice counts once. Summing rosters would inflate every
                    number in this column. */}
                <TD numeric>{teacher.studentCount}</TD>
                <TD>
                  <Button size="sm" onClick={() => setRemoving(teacher)}>
                    Remove
                  </Button>
                </TD>
              </TR>
            ))}
          </TBody>
        </Table>
      )}

      {removing ? (
        <RemoveTeacherDialog
          schoolId={group.schoolId}
          teacher={removing}
          colleagues={group.teachers.filter((t) => t.userId !== removing.userId)}
          onClose={() => setRemoving(null)}
        />
      ) : null}
    </section>
  )
}

function InviteTeacherPanel({ schoolId }: { schoolId: string }) {
  const [email, setEmail] = useState("")
  const [displayName, setDisplayName] = useState("")
  const invite = useInviteTeacher()

  return (
    <Card>
      <CardBody className="flex flex-col gap-4">
        <Eyebrow>Add a teacher</Eyebrow>
        <form
          className="flex flex-col gap-3"
          onSubmit={(event) => {
            event.preventDefault()
            if (!email.trim()) return
            invite.mutate(
              { schoolId, email: email.trim(), displayName: displayName.trim() || null },
              {
                onSuccess: () => {
                  setEmail("")
                  setDisplayName("")
                },
              },
            )
          }}
        >
          <div className="grid gap-3 sm:grid-cols-2">
            <Input
              label="Email address"
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              error={invite.isError ? adminMutationFailureMessage(invite.error) : undefined}
              autoComplete="off"
            />
            <Input
              label="Name (optional)"
              value={displayName}
              onChange={(event) => setDisplayName(event.target.value)}
              hint="Shown to their students and on their classes."
              autoComplete="off"
            />
          </div>
          <p className="max-w-prose text-body-sm text-ink-muted">
            Adding a teacher uses no seats. Seats are for students.
          </p>
          <div>
            <Button type="submit" variant="primary" loading={invite.isPending}>
              Add this teacher
            </Button>
          </div>
        </form>

        {/* The one-time password exists only in this response: the backend
            keeps its hash and nothing else, and there is no email provider in
            v1 to send it. Shown once, said plainly. */}
        {invite.isSuccess ? (
          <div className="flex flex-col gap-1.5 border-t border-rule pt-4">
            <p className="text-body-sm text-ink">
              {invite.data.email} can sign in now.
              {invite.data.temporaryPassword
                ? " Copy this password and give it to them: it is shown once and cannot be read again."
                : null}
            </p>
            {invite.data.temporaryPassword ? (
              <code className="w-fit rounded-sm bg-paper-sunk px-1.5 py-0.5 text-data-sm text-ink">
                {invite.data.temporaryPassword}
              </code>
            ) : null}
          </div>
        ) : null}
      </CardBody>
    </Card>
  )
}

/**
 * The removal dialog.
 *
 * Not `ConfirmModal`: this is not a yes/no question. Removing a teacher who
 * owns classes requires a *choice* — who takes them — and the kit's
 * confirmation deliberately has no room for a field. It is still built on the
 * same `Modal` with `dismissible={false}`, for the same reason: a stray Escape
 * must not answer a staffing question on the reader's behalf.
 */
function RemoveTeacherDialog({
  schoolId,
  teacher,
  colleagues,
  onClose,
}: {
  schoolId: string
  teacher: SchoolTeacher
  colleagues: SchoolTeacher[]
  onClose: () => void
}) {
  const [successor, setSuccessor] = useState("")
  const remove = useRemoveTeacher()
  const ownsClasses = teacher.classCount > 0
  const stuck = ownsClasses && colleagues.length === 0
  const canSubmit = !ownsClasses || successor !== ""

  return (
    <Modal
      open
      onClose={onClose}
      dismissible={false}
      size="sm"
      title={`Remove ${teacher.displayName ?? teacher.email}?`}
      description={
        ownsClasses
          ? `They own ${teacher.classCount} ${
              teacher.classCount === 1 ? "class" : "classes"
            } here, so someone has to take over before they can be removed.`
          : "They own no classes here, so nothing needs reassigning."
      }
      footer={
        <div className="flex flex-wrap justify-end gap-2">
          <Button variant="primary" onClick={onClose}>
            Keep them
          </Button>
          <Button
            loading={remove.isPending}
            disabled={!canSubmit || stuck}
            onClick={() =>
              remove.mutate(
                {
                  schoolId,
                  teacherId: teacher.userId,
                  reassignToTeacherId: ownsClasses ? successor : null,
                },
                { onSuccess: onClose },
              )
            }
          >
            Remove from this school
          </Button>
        </div>
      }
    >
      <div className="flex flex-col gap-4">
        {/* Said before the decision, not after it. An administrator hesitating
            over this button is asking "what does this destroy?", and the
            answer is: nothing. */}
        <p className="text-body-sm text-ink-muted">
          Their Lemely account stays, and so does everything they have already done here. Their
          name remains on the papers they marked and the announcements they wrote. Only their
          place on this school's staff is removed.
        </p>

        {stuck ? (
          <p className="text-body-sm text-ink">
            There is nobody else on this school's staff to take the classes on. Add another
            teacher first, then come back.
          </p>
        ) : ownsClasses ? (
          <Select
            label="Who takes over their classes?"
            value={successor}
            onChange={(event) => setSuccessor(event.target.value)}
            hint="All of their classes move to this teacher, along with the students in them."
          >
            {/* No empty option once a choice is required: an unselected select
                that can be submitted is how the orphaning case reaches the
                server at all. */}
            <option value="" disabled>
              Choose a teacher
            </option>
            {colleagues.map((colleague) => (
              <option key={colleague.userId} value={colleague.userId}>
                {colleague.displayName ?? colleague.email} ({colleague.classCount}{" "}
                {colleague.classCount === 1 ? "class" : "classes"} already)
              </option>
            ))}
          </Select>
        ) : null}

        {remove.isError ? (
          <p className="text-body-sm text-err">{teacherRemovalFailureMessage(remove.error)}</p>
        ) : null}
      </div>
    </Modal>
  )
}

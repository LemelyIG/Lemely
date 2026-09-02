/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import { useState, type FormEvent } from "react"
import { Link } from "react-router-dom"
import { Button, buttonVariants } from "@/components/ui/button"
import { Card, CardBody } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { useCreateClass } from "@/lib/hooks/useTeacherApi"
import { teacherMutationFailureMessage } from "@/lib/teacherOutcome"
import type { ClassSummary } from "@/lib/teacherTypes"
import { JoinCodeChip } from "./ClassDetail"

/*
 * D7.10 · the create-first-class step. `TeacherLayout`'s gate
 * (`teacherFirstClassRedirect`, `../index.tsx`) sends a teacher with zero
 * classes here, mounted at `/teacher/first-class`. Every downstream teacher
 * screen — the review queue, the at-risk list, class analytics — reads data
 * scoped to a class, and the join code a teacher needs to hand to students
 * does not exist until a class does; without this step a freshly
 * self-registered teacher would land on a dashboard of correctly-empty
 * panels indistinguishable, on screen, from a broken product.
 *
 * **Reuse, not a second implementation.** This calls `useCreateClass()` —
 * the identical `POST /classes` mutation `Classes.tsx`'s "+ New class" panel
 * calls for T-02 — rather than a second write path, and the field set
 * (`name`, required; `subjectCode`, optional) and the trim-then-no-op-on-empty
 * submit guard match `Classes.tsx`'s own `handleCreate` for the same reason:
 * this screen and that panel are two presentations of one create-class
 * operation, not two operations. Only the *layout* differs — a full first-run
 * step here, a table-toolbar panel there — which is why this is new markup
 * rather than an import of that form: the two contexts do not share a
 * container to import into, only the operation they both call. Built against
 * the kit's `Input`/`Button`/`Card` per the Frontend preamble, rather than
 * copying `Classes.tsx`'s hand-rolled `<input>` elements, which predate that
 * rule and are not this task's to fix.
 *
 * **No school field (D7.2).** A self-registered teacher is always
 * independent — `CreateClassRequest.schoolId` is left unset here and never
 * surfaced. This is not an omission: the backend has no membership to attach
 * the class to at this point in the flow (a self-registered teacher has no
 * `SchoolMembership` row), so a field for it would either do nothing or
 * invite a request the server can only refuse. Membership, and the school
 * field that goes with it, arrive later, by invite.
 *
 * **Ends on the join code.** That is the artifact D7.10 says a teacher came
 * for. `JoinCodeChip` is imported from `ClassDetail.tsx` rather than rebuilt
 * here — same copy-to-clipboard affordance, same component, two screens that
 * need it. Once `useCreateClass()` succeeds, its own `onSuccess` invalidates
 * the `["teacher", "classes"]` query `TeacherLayout`'s gate reads, so by the
 * time a teacher reads the code, copies it and clicks onward, that query has
 * already refetched and the gate no longer sends them back here — the same
 * invalidate-then-refetch contract every other mutation in this portal
 * already relies on, not a guarantee this screen invents for itself.
 */

/** The terminal state: the class exists, and its join code is the point. */
function CreatedClassPanel({ created }: { created: ClassSummary }) {
  return (
    <Card>
      <CardBody className="flex flex-col items-start gap-4">
        <div>
          <div className="text-eyebrow text-ink-faint">You're set up</div>
          <h1 className="text-display-md mt-1.5 text-pretty">"{created.label}" is ready</h1>
        </div>
        <p className="text-body-md text-ink-muted max-w-prose">
          Share this code with your students so they can join. You'll find it again on the class
          page any time you need it.
        </p>
        {created.joinCode ? (
          <div className="flex flex-col items-start gap-1.5">
            <span className="text-eyebrow text-ink-faint">Invite code</span>
            <JoinCodeChip code={created.joinCode} />
          </div>
        ) : (
          // Honestly nullable in the type (see `ClassDetail.tsx`'s own note on
          // `classes.join_code`) even though a class created here — always
          // independent, per D7.2 — should always receive one, since for this
          // teacher the code is their only invite path. If it is ever absent,
          // saying so plainly beats a silently blank slot.
          <p className="text-body-sm text-ink-faint">
            We couldn't generate an invite code just now. Open the class page below to find it
            once it appears.
          </p>
        )}
        <div className="flex flex-wrap gap-3 pt-1">
          <Link to="/teacher" className={buttonVariants({ variant: "ink" })}>
            Go to your dashboard
          </Link>
          <Link
            to={`/teacher/classes/${created.id}`}
            className={buttonVariants({ variant: "secondary" })}
          >
            Open this class
          </Link>
        </div>
      </CardBody>
    </Card>
  )
}

export function CreateFirstClass() {
  const createClass = useCreateClass()
  const [created, setCreated] = useState<ClassSummary | null>(null)
  const [name, setName] = useState("")
  const [subjectCode, setSubjectCode] = useState("")
  const [nameError, setNameError] = useState<string | null>(null)

  function handleCreate(e: FormEvent) {
    e.preventDefault()
    const trimmed = name.trim()
    if (!trimmed) {
      setNameError("Give the class a name before continuing.")
      return
    }
    setNameError(null)
    createClass.mutate(
      { name: trimmed, subjectCode: subjectCode.trim() || null },
      { onSuccess: (data) => setCreated(data) },
    )
  }

  if (created) {
    return (
      <div className="lm-screen flex flex-col gap-5 min-w-0 max-w-[680px]">
        <CreatedClassPanel created={created} />
      </div>
    )
  }

  return (
    <div className="lm-screen flex flex-col gap-5 min-w-0 max-w-[680px]">
      <div>
        <div className="text-eyebrow text-ink-faint">One quick step</div>
        <h1 className="text-display-md mt-1.5">Create your first class</h1>
      </div>
      <p className="text-body-md text-ink-muted max-w-prose">
        A class is where your students' work lands. It's where you'll see their marks, their weak
        topics, and who needs attention. Give it a name and you're ready to start marking.
      </p>

      <Card>
        <CardBody>
          <form onSubmit={handleCreate} className="flex flex-col gap-4" noValidate>
            <Input
              label="Class name"
              required
              value={name}
              onChange={(e) => {
                setName(e.target.value)
                if (nameError) setNameError(null)
              }}
              placeholder="e.g. Y11 Physics"
              error={nameError ?? undefined}
            />
            <Input
              label="Subject code"
              hint="Optional, e.g. 0625"
              value={subjectCode}
              onChange={(e) => setSubjectCode(e.target.value)}
            />
            <Button type="submit" variant="ink" loading={createClass.isPending} className="self-start">
              Create class
            </Button>
            {createClass.isError ? (
              <p className="text-body-sm text-err" role="alert">
                Couldn't create the class: {teacherMutationFailureMessage(createClass.error)}
              </p>
            ) : null}
          </form>
        </CardBody>
      </Card>
    </div>
  )
}

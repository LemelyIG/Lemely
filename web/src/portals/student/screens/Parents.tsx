/* Hallmark · pre-emit critique: P5 H4 E4 S5 R5 V4 */
import { useState, type FormEvent } from "react"
import { Trash } from "@phosphor-icons/react"
import { useLinkParent, useParentLinks, useUnlinkParent } from "@/lib/hooks/useStudentApi"
import { ApiError } from "@/lib/api"
import { Avatar } from "@/components/ui/avatar"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { EmptyState, ErrorState } from "@/components/ui/state-views"
import { ListSkeleton } from "@/components/ui/loading-shapes"
import { studentLoadFailureMessage, studentSaveFailureMessage } from "@/lib/studentOutcome"

/*
 * Student-side parent-link management.
 *
 * Not one of the numbered screens: `parent_child_links` rows are created here
 * and nowhere else, so without this surface the entire parent portal is
 * reachable only from a seed script — "a read surface with no way to grant it
 * is not a delivered feature" (D3.11's scope note). Kept deliberately small;
 * the full G-11 profile/settings screen this will eventually live inside is a
 * later phase.
 *
 * ── Why the student owns this ───────────────────────────────────────────────
 * The data being shared is theirs (UI spec §1.4: grades are private to the
 * student, their linked parents and their teachers), so they grant and revoke
 * it. D3.11 also fixes the ordering: the backend links only to a `role=parent`
 * user that **already exists**, i.e. one who has completed a phone-OTP login.
 * That is what stops a student-supplied phone number becoming an
 * account-creation primitive, and it is why a 404 here is not a failure to
 * report generically — it is the single most actionable message on the screen
 * ("they haven't signed in yet"), so it is surfaced as its own state.
 *
 * ── P4.10, the Study Notebook pass ────────────────────────────────────────
 *
 * **`linkErrorMessage`'s own comment was wrong about what it did.** It said
 * anything but a 404 "keeps the backend's own `detail`", implying the backend
 * had written one worth keeping. It has not: `routers/student.py:1071/1073`
 * both answer `str(exc)`, and the only `ValueError` the parent-link repo
 * raises reads `f"Identifier must be a UUID, got {value!r}"`. So the sentence
 * a student saw when adding a parent went wrong could be a Python repr. This
 * is the third time this phase a docstring has described an intention the code
 * did not meet (surface 2's `MarkDisplay`, surface 8's `ParentLogin`).
 *
 * The 404 copy stays exactly as it was, and that is the family rule working
 * rather than an exception to it: that sentence is ours, written here for a
 * fifteen-year-old, and it is the only one on the screen that tells them what
 * to do next.
 *
 * **A failed removal reported itself below every section.** `unlink.isError`
 * rendered as the last element on the page, so failing to remove the first of
 * five parents put the message under the fifth. Surface 4 found the identical
 * shape on Friends. It sits with its own row now (§12).
 *
 * **The avatar was a hand-rolled circle.** §6 reserves the circle for status
 * and live dots "so a dot never reads as a person", and the kit's `Avatar` is
 * a squircle for exactly that reason. This was the seventh call site of the
 * same violation found across this phase, and the last one.
 */

/** A 404 from POST /student/parent-links means precisely one thing, and it is
 * fixable by the student — so it keeps its own sentence. Everything else goes
 * through the shared student wording; see the module note for why the previous
 * "keep the backend's detail" fallback was not safe. */
function linkErrorMessage(error: Error): string {
  if (error instanceof ApiError && error.status === 404) {
    return "No Lemely account is using that number yet. Ask them to sign in with their phone first, then add them here."
  }
  return studentSaveFailureMessage(error)
}

export function Parents() {
  const { data, isPending, isError, error } = useParentLinks()
  const link = useLinkParent()
  const unlink = useUnlinkParent()
  const [phone, setPhone] = useState("")
  /** A failed removal, kept against the parent it failed on. */
  const [unlinkError, setUnlinkError] = useState<{ id: string; message: string } | null>(null)
  const [removingId, setRemovingId] = useState<string | null>(null)

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!phone.trim()) return
    link.mutate({ phone: phone.trim() }, { onSuccess: () => setPhone("") })
  }

  const handleRemove = (parentId: string) => {
    setRemovingId(parentId)
    setUnlinkError(null)
    unlink.mutate(
      { parentId },
      {
        onError: (err) =>
          setUnlinkError({ id: parentId, message: studentSaveFailureMessage(err) }),
        onSettled: () => setRemovingId(null),
      },
    )
  }

  return (
    <div className="lm-screen flex w-full max-w-160 flex-col gap-6">
      <div className="flex flex-col gap-2">
        <h1 className="text-display-md text-ink">Your parents</h1>
        <p className="max-w-[65ch] text-body-md text-ink-muted">
          Anyone you add here can see your marks, predicted grades and weak topics. They can't
          change anything, and you can remove them at any time.
        </p>
      </div>

      <form
        onSubmit={handleSubmit}
        className="flex flex-col gap-3 rounded-lg border border-rule bg-paper-raised p-5"
      >
        <div className="flex flex-col gap-1">
          <div className="text-body-md font-medium text-ink">Add a parent by phone number</div>
          <p className="max-w-[65ch] text-body-sm text-ink-muted">
            Use the number they signed in with, including the country code. For example
            +201234567890.
          </p>
        </div>
        <div className="flex flex-wrap items-start gap-2">
          <Input
            label="Parent's phone number"
            // The label is visible and the heading above is a separate
            // sentence, so the two do not duplicate: one says what this form
            // does, the other names the field.
            type="tel"
            inputMode="tel"
            autoComplete="off"
            placeholder="+20…"
            value={phone}
            onChange={(event) => setPhone(event.target.value)}
            error={link.isError ? linkErrorMessage(link.error) : undefined}
            wrapperClassName="min-w-0 flex-1"
          />
          <Button
            type="submit"
            variant="accent"
            size="md"
            disabled={link.isPending || !phone.trim()}
            // Aligns the button with the field rather than its label.
            className="mt-6"
          >
            {link.isPending ? "Adding…" : "Add parent"}
          </Button>
        </div>
      </form>

      {isPending ? (
        <ListSkeleton rows={2} avatar />
      ) : isError ? (
        <ErrorState
          heading="We couldn't load your parents"
          body={studentLoadFailureMessage(error)}
          action={{ label: "Try again", onClick: () => window.location.reload() }}
        />
      ) : data.parents.length === 0 ? (
        <EmptyState
          heading="Nobody is linked to your account yet"
          body="Only you can add someone. Nothing is shared until you do."
        />
      ) : (
        <ul className="flex flex-col gap-2">
          {data.parents.map((parent) => {
            const failed = unlinkError?.id === parent.parentId ? unlinkError.message : null
            return (
              <li
                key={parent.parentId}
                className="flex flex-col gap-3 rounded-lg border border-rule bg-paper-raised p-4"
              >
                <div className="flex items-center gap-3">
                  <Avatar name={parent.displayName} size="md" />
                  <div className="flex min-w-0 flex-1 flex-col">
                    <span className="text-body-md text-ink">{parent.displayName}</span>
                    {/* `phone` is nullable on the wire; absence is left blank
                        rather than filled with a placeholder number. */}
                    {parent.phone ? (
                      <span className="text-data-sm text-ink-muted">{parent.phone}</span>
                    ) : null}
                  </div>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    aria-label={`Remove ${parent.displayName}`}
                    disabled={removingId === parent.parentId}
                    onClick={() => handleRemove(parent.parentId)}
                  >
                    <Trash size={15} aria-hidden="true" />
                    {removingId === parent.parentId ? "Removing…" : "Remove"}
                  </Button>
                </div>
                {failed ? (
                  <p role="alert" className="text-body-sm text-err">
                    {failed}
                  </p>
                ) : null}
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}

import { useState, type FormEvent } from "react"
import { Trash } from "@phosphor-icons/react"
import {
  useLinkParent,
  useParentLinks,
  useUnlinkParent,
} from "@/lib/hooks/useStudentApi"
import { ApiError } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { ErrorState } from "@/components/ui/state-views"
import { initialsOf } from "@/lib/utils"

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
 */

/** A 404 from POST /student/parent-links means precisely one thing, and it is
 * fixable by the user. Anything else is a real error and keeps the backend's
 * own `detail` (which `request()` surfaces — P3.7d). */
function linkErrorMessage(error: Error): string {
  if (error instanceof ApiError && error.status === 404) {
    return "No Lemely account is using that number yet. Ask them to sign in with their phone first — then add them here."
  }
  return error.message
}

export function Parents() {
  const { data, isPending, isError, error } = useParentLinks()
  const link = useLinkParent()
  const unlink = useUnlinkParent()
  const [phone, setPhone] = useState("")

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!phone.trim()) return
    link.mutate(
      { phone: phone.trim() },
      { onSuccess: () => setPhone("") },
    )
  }

  return (
    <div className="flex max-w-160 flex-col gap-6">
      <div className="flex flex-col gap-2">
        <h1 className="text-display-md text-t1">Your parents</h1>
        <p className="text-body-md text-t2">
          Anyone you add here can see your marks, predicted grades and weak topics. They
          can't change anything, and you can remove them at any time.
        </p>
      </div>

      <form
        onSubmit={handleSubmit}
        className="flex flex-col gap-3 rounded-md border border-border bg-surface p-5"
      >
        <label htmlFor="parent-link-phone" className="text-body-md font-medium text-t1">
          Add a parent by phone number
        </label>
        <p className="text-body-md text-t2">
          Use the number they signed in with, including the country code — for example
          +201234567890.
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <input
            id="parent-link-phone"
            type="tel"
            inputMode="tel"
            autoComplete="off"
            placeholder="+20…"
            value={phone}
            onChange={(event) => setPhone(event.target.value)}
            className="min-w-0 flex-1 rounded border border-border bg-surface px-3 py-2.5 text-body-md text-t1"
          />
          <Button type="submit" variant="accent" size="md" disabled={link.isPending || !phone.trim()}>
            {link.isPending ? "Adding…" : "Add parent"}
          </Button>
        </div>
        {link.isError ? (
          <p role="alert" className="text-body-md text-warn">
            {linkErrorMessage(link.error)}
          </p>
        ) : null}
      </form>

      {isPending ? (
        <p role="status" aria-live="polite" className="text-body-md text-t2">
          Loading…
        </p>
      ) : isError ? (
        <ErrorState
          heading="We couldn't load your parents"
          body={error instanceof Error ? error.message : "Please try again in a moment."}
          action={{ label: "Try again", onClick: () => window.location.reload() }}
        />
      ) : data.parents.length === 0 ? (
        <p className="rounded-md border border-border bg-surface p-4 text-body-md text-t2">
          Nobody is linked to your account yet. Only you can add someone.
        </p>
      ) : (
        <ul className="flex flex-col gap-2">
          {data.parents.map((parent) => (
            <li
              key={parent.parentId}
              className="flex items-center gap-3 rounded-md border border-border bg-surface p-4"
            >
              <span
                aria-hidden="true"
                className="flex h-9 w-9 flex-none items-center justify-center rounded-full bg-accent-subtle text-body-md font-medium text-accent"
              >
                {initialsOf(parent.displayName)}
              </span>
              <div className="flex min-w-0 flex-1 flex-col">
                <span className="text-body-md text-t1">{parent.displayName}</span>
                {/* `phone` is nullable on the wire; absence is left blank
                    rather than filled with a placeholder number. */}
                {parent.phone ? (
                  <span className="text-body-md text-t2">{parent.phone}</span>
                ) : null}
              </div>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                aria-label={`Remove ${parent.displayName}`}
                disabled={unlink.isPending}
                onClick={() => unlink.mutate({ parentId: parent.parentId })}
              >
                <Trash size={15} aria-hidden="true" />
                Remove
              </Button>
            </li>
          ))}
        </ul>
      )}
      {unlink.isError ? (
        <p role="alert" className="text-body-md text-warn">
          {unlink.error.message}
        </p>
      ) : null}
    </div>
  )
}

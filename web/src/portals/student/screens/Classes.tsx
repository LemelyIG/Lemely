/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import { useState, type FormEvent } from "react"
import { Card, CardBody } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import { Eyebrow } from "@/components/ui/primitives"
import { EmptyState } from "@/components/ui/state-views"
import { QueryState } from "@/components/ui/query-state"
import { ListSkeleton } from "@/components/ui/loading-shapes"
import { normalizeInviteCode } from "@/lib/hooks/useInvitesApi"
import { useMyClasses } from "@/lib/hooks/useLeaderboardApi"
import { useJoinClass } from "@/lib/hooks/useStudentApi"
import { joinClassFailureMessage, studentLoadFailureMessage } from "@/lib/studentOutcome"

/*
 * The student-side half of G-08's other gap: `POST /api/student/classes/join`
 * has had a screen since G-08 shipped `JoinWithCode.tsx`, but that screen is
 * reachable only from a link a teacher hands out, `/join` or `/join/:code`.
 * A student who is already signed in, already inside the portal, and simply
 * remembers "my teacher gave me a code" had no destination for it anywhere in
 * the sidebar — `Standings.tsx` tells them "Ask your teacher for a join
 * code" and points nowhere. This screen is that destination, mounted at
 * `/student/classes` and linked from the "Your classes" nav row right after
 * Overview.
 *
 * `useMyClasses()` (`useLeaderboardApi.ts`) and `useJoinClass()`
 * (`useStudentApi.ts`) are both reused, not duplicated: `useMyClasses` already
 * backs the S-29 class-scope selector on `Standings.tsx`, and `useJoinClass`
 * wraps the same `POST /student/classes/join` endpoint `JoinWithCode.tsx`'s
 * signed-in branch calls. `normalizeInviteCode` (`useInvitesApi.ts`) is reused
 * for the same reason: a join code and an invite code are minted from the
 * same non-ambiguous, uppercase-only alphabets (`class_repo.py`'s
 * `_JOIN_CODE_ALPHABET`, `invite_repo.py`'s `_INVITE_CODE_ALPHABET`) and
 * matched with the identical case-sensitive `==`, so the normalisation a
 * holder's code needs is the same trim-and-uppercase either way — a second
 * copy of that one-line function would only be a second place for it to drift.
 *
 * The classes list carries no mark, average or join date — `StudentClassDTO`
 * declares none, and this screen renders nothing that field would have to
 * come from.
 */

export function StudentClasses() {
  const classes = useMyClasses()
  const join = useJoinClass()
  const [code, setCode] = useState("")
  const [joinedClassName, setJoinedClassName] = useState<string | null>(null)

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const normalized = normalizeInviteCode(code)
    if (!normalized) return
    setJoinedClassName(null)
    join.mutate(
      { joinCode: normalized },
      {
        onSuccess: (data) => {
          setJoinedClassName(data.className)
          setCode("")
        },
      },
    )
  }

  return (
    <div className="lm-screen flex w-full max-w-160 flex-col gap-6">
      <div className="flex flex-col gap-1">
        <Eyebrow>Classes</Eyebrow>
        <h1 className="text-display-md text-ink">Your classes</h1>
      </div>

      <Card>
        <CardBody className="flex flex-col gap-3">
          <div className="flex flex-col gap-1">
            <h2 className="text-body-md font-medium text-ink">Join a class</h2>
            <p className="text-body-sm text-ink-muted">
              Your teacher gives you a class code. Enter it here to join.
            </p>
          </div>
          <form onSubmit={handleSubmit} className="flex flex-wrap items-start gap-2">
            <Input
              label="Class code"
              wrapperClassName="min-w-0 flex-1 max-w-xs"
              className="font-mono tracking-[0.08em]"
              value={code}
              onChange={(event) => {
                setCode(event.target.value)
                setJoinedClassName(null)
              }}
              autoCapitalize="characters"
              autoComplete="off"
              spellCheck={false}
              placeholder="e.g. K7P4RQ2"
              error={join.isError ? joinClassFailureMessage(join.error) : undefined}
            />
            <Button
              type="submit"
              variant="accent"
              size="md"
              loading={join.isPending}
              disabled={code.trim().length === 0}
              // Aligns with the field itself rather than its label, matching
              // `Parents.tsx`'s identical add-by-field row.
              className="mt-6"
            >
              Join
            </Button>
          </form>
          {joinedClassName ? (
            <p role="status" className="text-body-sm text-ok">
              You joined {joinedClassName}.
            </p>
          ) : null}
        </CardBody>
      </Card>

      {/* A panel inside the screen above, not a whole-route load: the page's
          own `<h1>` and the join form both render unconditionally above this,
          so no `srHeading` is needed — there is already a landmark to land on
          mid-load or mid-failure. */}
      <QueryState
        query={classes}
        skeleton={<ListSkeleton rows={2} />}
        error={{ heading: "We couldn't load your classes", body: studentLoadFailureMessage }}
        isEmpty={(data) => data.classes.length === 0}
        empty={
          <EmptyState
            heading="You're not in a class yet"
            body="Enter a code above to join your teacher's class."
          />
        }
      >
        {(data) => (
          <ul className="flex flex-col gap-2">
            {data.classes.map((cls) => {
              // `subjectCode` and `schoolName` are both nullable on the wire
              // (an unscoped class, an independent teacher) — `null` means
              // genuinely absent, not "unknown", so it is dropped from the
              // line rather than printed as a placeholder. When both are
              // absent there is no second line at all, rather than an empty
              // `<span>` taking up a line of nothing.
              const meta = [cls.subjectCode, cls.schoolName].filter(Boolean).join(" · ")
              return (
                <li
                  key={cls.classId}
                  className="flex flex-col gap-0.5 rounded-lg border border-rule bg-paper-raised p-4"
                >
                  <span className="text-body-md text-ink">{cls.name}</span>
                  {meta ? <span className="text-body-sm text-ink-faint">{meta}</span> : null}
                </li>
              )
            })}
          </ul>
        )}
      </QueryState>
    </div>
  )
}

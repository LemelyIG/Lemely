import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Card, CardBody } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { joinCodeDraft, joinFailureMessage, joinedMessage } from "@/lib/assistantRoles"
import { useJoinTeam } from "@/lib/hooks/useTeamApi"

/*
 * Redeeming an assistant invite with your own teacher account (spec §2.3, §4.4). Always shown,
 * including to an assistant, who gets a 403 on the team itself. The code is secret-ish: it is
 * sent once and never logged.
 */

export function JoinTeamCard() {
  const join = useJoinTeam()
  const [code, setCode] = useState("")
  const [fieldError, setFieldError] = useState<string | null>(null)
  const joined = join.isSuccess && join.data ? join.data : null
  return (
    <section aria-labelledby="join-heading" className="flex flex-col gap-4">
      <h2 id="join-heading" className="m-0 text-display-sm text-on-surface">Join a team</h2>
      <Card>
        <CardBody className="flex flex-col gap-3">
          {joined ? (
            <>
              <p role="status" className="m-0 text-body-md text-on-surface">{joinedMessage(joined.teacherName, joined.role)}</p>
              <Button
                variant="ghost"
                className="self-start"
                onClick={() => {
                  join.reset()
                  setCode("")
                }}
              >
                Join another team
              </Button>
            </>
          ) : (
            <>
              <p className="m-0 max-w-[65ch] text-body-sm text-on-surface-variant">
                Joining someone else's team? Enter the assistant code they sent you.
              </p>
              <form
                noValidate
                className="flex flex-col gap-3 sm:flex-row sm:items-start"
                onSubmit={(e) => {
                  e.preventDefault()
                  const draft = joinCodeDraft(code)
                  setFieldError(draft.ok ? null : draft.error)
                  if (draft.ok) join.mutate(draft.code)
                }}
              >
                <Input
                  label="Assistant code"
                  value={code}
                  autoComplete="off"
                  autoCapitalize="characters"
                  spellCheck={false}
                  error={fieldError ?? undefined}
                  wrapperClassName="min-w-0 flex-1"
                  onChange={(e) => {
                    setCode(e.target.value)
                    setFieldError(null)
                  }}
                />
                {/* Offset by the label so the button sits level with the field, not the label. */}
                <Button type="submit" variant="primary" loading={join.isPending} className="sm:mt-[1.625rem]">
                  Join team
                </Button>
              </form>
              {join.isError ? <p role="alert" className="m-0 text-body-sm text-error">{joinFailureMessage(join.error)}</p> : null}
            </>
          )}
        </CardBody>
      </Card>
    </section>
  )
}

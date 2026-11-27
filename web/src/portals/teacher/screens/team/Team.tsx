/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V3 */
/* The 403 for an assistant renders a plain ErrorState with no retry, because retrying cannot change who the teacher is. JoinTeamCard stays outside the query so an assistant can still join a team. */
import { ApiError } from "@/lib/api"
import { PageHeaderSkeleton } from "@/components/ui/loading-shapes"
import { PageHeading } from "@/components/ui/page-heading"
import { QueryState } from "@/components/ui/query-state"
import { ErrorState } from "@/components/ui/state-views"
import { useTeam } from "@/lib/hooks/useTeamApi"
import { AssistantsPanel } from "./AssistantsPanel"
import { JoinTeamCard } from "./JoinTeamCard"
import { SeatsPanel } from "./SeatsPanel"
import { OwnAccountNote } from "@/components/acting/own-account-note"

/*
 * `/teacher/team`: the lead teacher's seats and assistants, and joining someone else's team. Billing, seats,
 * caps and assistants stay with the lead teacher (spec §2.3), so an assistant gets 403 here.
 */

const isForbidden = (e: unknown) => e instanceof ApiError && e.status === 403

export function Team() {
  const team = useTeam()
  return (
    <div className="flex flex-col gap-6">
      <PageHeading repeatsTitle className="m-0 text-display-md text-on-surface">Seats and assistants</PageHeading>
      {/* The team is the caller's own whoever they are working as; say so while they act for a lead. */}
      <OwnAccountNote />
      {team.status === "error" && isForbidden(team.error) ? (
        // Retrying cannot change who the teacher is, so this one carries no "Try again".
        <ErrorState heading="You can't manage seats" body="Seats and assistants are managed by the lead teacher." />
      ) : (
        <QueryState
          query={team}
          skeleton={<PageHeaderSkeleton />}
          error={{ heading: "Couldn't load your team", body: "Check your connection and try again." }}
        >
          {(t) => (
            <>
              <SeatsPanel team={t} />
              <AssistantsPanel team={t} />
            </>
          )}
        </QueryState>
      )}
      {/* Outside the query: an assistant, who gets a 403 on the team, can still join a team. */}
      <JoinTeamCard />
    </div>
  )
}

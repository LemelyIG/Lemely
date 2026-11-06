import { ApiError } from "@/lib/api"
import { PageHeaderSkeleton } from "@/components/ui/loading-shapes"
import { QueryState } from "@/components/ui/query-state"
import { ErrorState } from "@/components/ui/state-views"
import { useTeam } from "@/lib/hooks/useTeamApi"
import { SeatsPanel } from "./SeatsPanel"

/*
 * `/teacher/team`: the lead teacher's seats (and, from Task 12, assistants). Billing, seats,
 * caps and assistants stay with the lead teacher (spec §2.3), so an assistant gets 403 here.
 */

const isForbidden = (e: unknown) => e instanceof ApiError && e.status === 403

export function Team() {
  const team = useTeam()
  return (
    <div className="flex flex-col gap-6">
      <h1 className="m-0 text-display-md text-on-surface">Seats and assistants</h1>
      {team.status === "error" && isForbidden(team.error) ? (
        // Retrying cannot change who the teacher is, so this one carries no "Try again".
        <ErrorState heading="You can't manage seats" body="Seats and assistants are managed by the lead teacher." />
      ) : (
        <QueryState
          query={team}
          skeleton={<PageHeaderSkeleton />}
          error={{ heading: "Couldn't load your team", body: "Check your connection and try again." }}
        >
          {(t) => <SeatsPanel team={t} />}
        </QueryState>
      )}
    </div>
  )
}

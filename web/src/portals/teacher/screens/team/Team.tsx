import { ApiError } from "@/lib/api"
import { PageHeaderSkeleton } from "@/components/ui/loading-shapes"
import { QueryState } from "@/components/ui/query-state"
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
      <QueryState
        query={team}
        skeleton={<PageHeaderSkeleton />}
        error={{
          heading: isForbidden(team.error) ? "You can't manage seats" : "Couldn't load your team",
          body: (e) =>
            isForbidden(e) ? "Seats and assistants are managed by the lead teacher." : "Check your connection and try again.",
        }}
      >
        {(t) => <SeatsPanel team={t} />}
      </QueryState>
    </div>
  )
}

/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import { QueryState } from "@/components/ui/query-state"
import { useStudentHome } from "@/lib/hooks/useStudentHomeApi"
import { useOnlineStatus } from "@/lib/online"
import { studentLoadFailureMessage } from "@/lib/studentOutcome"
import { HomeScreen } from "../home/HomeScreen"
import { HomeSkeleton } from "../home/HomeSkeleton"

/*
 * Student Home, the hub (redesign lane L1, mock student-r2/home4.html + h6.js).
 * Route entry only: one query, one QueryState, one screen. Every decision is
 * in `../home/model.ts`.
 */
export function Overview() {
  const query = useStudentHome()
  const online = useOnlineStatus()
  return (
    <QueryState
      query={query}
      srHeading="Home"
      skeleton={<HomeSkeleton />}
      error={
        online
          ? { heading: "Couldn't load your home", body: studentLoadFailureMessage }
          : { heading: "You're offline", body: "Home comes back when you reconnect. Nothing you did is lost." }
      }
    >
      {(home) => <HomeScreen home={home} />}
    </QueryState>
  )
}

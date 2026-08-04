import { Card } from "@/components/ui/card"
import { useStandings } from "@/lib/hooks/useStudentApi"
import { vizText } from "../components/colors"

/*
 * Standings (isBoard). Wired to `GET /student/standings` via useStandings().
 * The mock's friends/school/global leaderboard is removed entirely —
 * `StandingsDTO` has no `boards` field and no backend exists for it yet
 * (Phase 5/XP). The 28-cell streak heatmap is also unbacked (`streakDays` is
 * a scalar, no per-day array) — replaced with an honest stat card. Subject
 * standings stays, backed by the real `subjectRanks` field.
 */
export function Standings() {
  const { data, isPending, isError, error } = useStandings()

  if (isPending) {
    return (
      <div className="lm-screen flex flex-col gap-[22px]">
        <div className="text-[13.5px] text-t2">Loading standings…</div>
      </div>
    )
  }

  if (isError) {
    return (
      <div className="lm-screen flex flex-col gap-[22px]">
        <div className="text-[13.5px] text-accent">
          Couldn't load your standings: {error.message}
        </div>
      </div>
    )
  }

  const { subjectRanks, paperCount, streakDays } = data

  return (
    <div className="lm-screen flex flex-col gap-[22px]">
      <div className="font-serif text-[36px] leading-[1.1]">Standings</div>

      <div className="lm-cols grid grid-cols-2 gap-5 max-[1180px]:grid-cols-1">
        <Card className="p-5 text-center">
          <div className="text-[11px] tracking-[0.09em] uppercase text-t3">
            Streak
          </div>
          <div className="font-serif text-[44px] leading-[1.1]">
            {streakDays}
            <span className="text-[18px]"> days</span>
          </div>
        </Card>
        <Card className="p-5 text-center">
          <div className="text-[11px] tracking-[0.09em] uppercase text-t3">
            Papers corrected
          </div>
          <div className="font-serif text-[44px] leading-[1.1]">
            {paperCount}
          </div>
        </Card>
      </div>

      <Card className="p-5">
        <div className="text-[15px] font-semibold mb-[14px]">
          Subject standings
        </div>
        {subjectRanks.length === 0 ? (
          <div className="text-[13px] text-t2">No subjects ranked yet.</div>
        ) : (
          <div className="flex flex-col gap-[11px]">
            {subjectRanks.map((s) => (
              <div key={s.code} className="flex items-center gap-3">
                <span className="font-mono text-[11.5px] text-t2 w-[38px]">
                  {s.code}
                </span>
                <span className="text-[12.5px] flex-1">{s.name}</span>
                <span className="text-[11.5px] text-t2">
                  {s.papers} papers
                </span>
                <span className={`font-mono text-[12.5px] ${vizText(s.color)}`}>
                  {s.rank}
                </span>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  )
}

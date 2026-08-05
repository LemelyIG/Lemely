import { useNavigate } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { StatCard } from "../components/StatCard"
import { Avatar } from "../components/Avatar"
import { useTeacherOverview } from "@/lib/hooks/useTeacherApi"

/*
 * Overview. Wired to `GET /teacher/overview` via `useTeacherOverview()`.
 *
 * Cuts made vs. the mock (see `OverviewDTO` in `lib/teacherTypes.ts` /
 * `lemely/web/routers/teacher.py::teacher_overview`):
 *  - "Lesson retention" card dropped entirely — `retention` is always `[]`
 *    (no lesson-video data source exists), so the chart + its narrative copy
 *    would only ever render an empty/fabricated state.
 *  - The "hours saved" ink box dropped entirely — no backing field anywhere
 *    in `OverviewDTO`.
 *  - "Needs you" cards render only the 4 real `AtRiskStudent` fields
 *    (name/grade/delta/weakTopic); the mock's tag/note/action/avatar-tone
 *    and the "Message parents" + per-student action buttons had no backend
 *    source and are gone. Initials are derived client-side from `name`, a
 *    pure display transform (same pattern as `data.ts`'s `student()`).
 *  - The greeting paragraph now interpolates real numbers pulled from
 *    `stats`/`atRisk` instead of the mock's hardcoded "twenty-eight papers…"
 *    copy.
 */

function initialsOf(name: string): string {
  return name
    .split(" ")
    .map((w) => w[0])
    .join("")
}

export function Overview() {
  const navigate = useNavigate()
  const { data, isPending, isError, error } = useTeacherOverview()

  if (isPending) {
    return (
      <div className="lm-screen flex flex-col gap-6">
        <div className="text-[13.5px] text-t2">Loading overview…</div>
      </div>
    )
  }

  if (isError) {
    return (
      <div className="lm-screen flex flex-col gap-6">
        <div className="text-[13.5px] text-accent">
          Couldn't load the overview: {error.message}
        </div>
      </div>
    )
  }

  const { stats, atRisk } = data
  const papersGraded = stats.find((s) => s.key === "Papers graded")
  const needsEyes = stats.find((s) => s.key === "Need your eyes")

  return (
    <div className="lm-screen flex flex-col gap-6">
      <div className="flex items-end gap-5 flex-wrap gap-y-2.5">
        <div>
          <div className="font-mono text-[11px] tracking-[0.11em] uppercase text-t3">
            Helwan Science Centre · Sunday 27 July
          </div>
          <div className="font-serif text-[40px] leading-[1.08] mt-2">
            Good morning.
          </div>
          <div className="text-[14.5px] text-t2 mt-2 max-w-[62ch] text-pretty">
            {papersGraded ? `${papersGraded.value} papers graded so far. ` : ""}
            {needsEyes
              ? `${needsEyes.value} answers want your eyes`
              : ""}
            {atRisk.length > 0
              ? `, and ${atRisk.length} student${atRisk.length === 1 ? "" : "s"} want${
                  atRisk.length === 1 ? "s" : ""
                } your attention.`
              : "."}
          </div>
        </div>
        <div className="flex-1" />
        <Button variant="ink" size="lg" onClick={() => navigate("/teacher/review")}>
          Open review queue →
        </Button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
        {stats.map((s) => (
          <StatCard
            key={s.key}
            stat={{
              k: s.key,
              v: s.value,
              unit: s.unit ?? undefined,
              foot: s.foot ?? undefined,
              valueTone: s.valueTone,
              footTone: s.footTone,
            }}
          />
        ))}
      </div>

      {/* Needs you */}
      <div className="bg-surface border border-border rounded-[14px] overflow-hidden max-w-[560px] w-full">
        <div className="px-5 pt-[18px] pb-[13px]">
          <div className="font-serif text-[22px]">Needs you</div>
          <div className="font-mono text-[10.5px] tracking-[0.1em] uppercase text-t3 mt-[5px]">
            Flagged by trajectory, not by one bad day
          </div>
        </div>
        {atRisk.length === 0 ? (
          <div className="border-t border-border px-5 py-[15px] text-[13px] text-t2">
            No students flagged right now.
          </div>
        ) : (
          atRisk.map((r) => (
            <div
              key={r.name}
              className="border-t border-border px-5 py-[15px] flex gap-[13px] items-start"
            >
              <Avatar initials={initialsOf(r.name)} className="w-8 h-8 text-[11.5px]" />
              <div className="flex-1">
                <div className="flex items-center gap-[9px]">
                  <div className="text-[13.5px] font-medium">{r.name}</div>
                  <div className="text-[12px] text-t2">Grade {r.grade}</div>
                  <div className="flex-1" />
                  {r.delta !== null ? (
                    <div
                      className={cn(
                        "font-mono text-[12px]",
                        r.delta < 0 ? "text-err" : r.delta > 0 ? "text-ok" : "text-t2",
                      )}
                    >
                      {r.delta > 0 ? "+" : ""}
                      {Math.round(r.delta)} pts
                    </div>
                  ) : null}
                </div>
                {r.weakTopic ? (
                  <div className="text-[12.5px] text-t2 mt-[5px] leading-[1.45] text-pretty">
                    Weakest topic: {r.weakTopic}
                  </div>
                ) : null}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  )
}

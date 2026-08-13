/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import { useState } from "react"
import { Link, NavLink, Outlet, useOutletContext, useParams } from "react-router-dom"
import { ErrorState } from "@/components/ui/state-views"
import { cn, relativeTime } from "@/lib/utils"
import { StatCard } from "../components/StatCard"
import { useClassDetail } from "@/lib/hooks/useTeacherApi"
import { PanelSkeleton } from "@/components/ui/loading-shapes"
import { teacherLoadFailureMessage } from "@/lib/teacherOutcome"
import type { ClassDetail as ClassDetailData } from "@/lib/teacherTypes"

/*
 * Class detail shell (T-03/T-04's shared header + tabs). Fetches
 * `GET /classes/{classId}` (`useClassDetail()`) once here — the header
 * strip (name, subject, join code, `stats`/`atRiskCount`/`lastActivityAt`/
 * `topWeakness`) and the roster tab (T-03) both read this same response via
 * `useOutletContext`, so T-03 needs no second fetch. The analytics tab
 * (T-04) still runs its own `GET /classes/{classId}/analytics` — a
 * different DTO — but reads the header context too, for the roster's
 * student id -> display name map the heatmap columns need.
 *
 * `stats` (class average / students / at risk) is rendered here as the
 * header strip using the same `StatCard` component as Overview/Classes.
 * `mastery`/`distribction` are deliberately NOT rendered anywhere — see
 * `ClassDetail` in `lib/teacherTypes.ts` for why (a second, differently
 * derived per-topic/per-grade computation next to T-04's authoritative one
 * would recreate the "same label, two numbers" bug D3.3-D3.5 each fixed
 * once already).
 *
 * Join code: the real invite route (D3.1's `classes.join_code`), always
 * shown when present — a class with no `schoolId` has no seat pool to
 * enroll-by-id from, so the join code is that class's *only* working invite
 * path, not just a convenience.
 */

export interface ClassDetailContext {
  classDetail: ClassDetailData
  classId: string
}

export function useClassDetailContext(): ClassDetailContext {
  return useOutletContext<ClassDetailContext>()
}

function JoinCodeChip({ code }: { code: string }) {
  const [copied, setCopied] = useState(false)
  async function copy() {
    try {
      await navigator.clipboard.writeText(code)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      // Clipboard API unavailable (permissions, non-secure context) — the
      // code is still visible in the DOM, so the invite route still works
      // by hand-copy; nothing to recover from here.
    }
  }
  return (
    <button
      type="button"
      onClick={copy}
      className="inline-flex items-center gap-2 border border-rule bg-paper-raised rounded-lg px-3 py-1.5 text-data-md tracking-[0.06em] hover:bg-paper-sunk cursor-pointer focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
      title="Copy join code"
    >
      {code}
      <span className="text-body-sm text-ink-faint">{copied ? "Copied" : "Copy"}</span>
    </button>
  )
}

export function ClassDetailLayout() {
  const { classId } = useParams<{ classId: string }>()
  const detailQuery = useClassDetail(classId)

  if (detailQuery.isPending) {
    return (
      <div className="lm-screen flex flex-col gap-6 min-w-0">
        <h1 className="sr-only">Class detail</h1>
        <PanelSkeleton />
      </div>
    )
  }

  if (detailQuery.isError) {
    return (
      <div className="lm-screen flex flex-col gap-6 min-w-0">
        <h1 className="sr-only">Class detail</h1>
        <ErrorState
          heading="Couldn't load this class"
          body={teacherLoadFailureMessage(detailQuery.error)}
          action={{ label: "Retry", onClick: () => detailQuery.refetch() }}
          secondaryAction={{ label: "Back to classes", onClick: () => history.back() }}
        />
      </div>
    )
  }

  const classDetail = detailQuery.data

  return (
    <div className="lm-screen flex flex-col gap-6 min-w-0">
      <div className="flex flex-col gap-1">
        <Link to="/teacher/classes" className="text-body-sm text-ink-faint hover:text-ink w-fit">
          ← All classes
        </Link>
        <div className="flex items-start gap-4 flex-wrap gap-y-2 mt-1">
          <div className="min-w-0">
            <div className="text-eyebrow text-ink-faint">
              {classDetail.subjectCode ?? "No subject set"}
            </div>
            <h1 className="text-display-md mt-1.5 text-pretty">
              {classDetail.label}
            </h1>
          </div>
          <div className="flex-1" />
          {classDetail.joinCode ? (
            <div className="flex flex-col items-end gap-1">
              <span className="text-eyebrow text-ink-faint">
                Invite code
              </span>
              <JoinCodeChip code={classDetail.joinCode} />
            </div>
          ) : null}
        </div>
        <div className="flex items-center gap-3 flex-wrap text-body-sm text-ink-muted mt-1">
          <span>{classDetail.topWeakness ? `Top weakness: ${classDetail.topWeakness}` : "Not enough data for a top weakness yet"}</span>
          <span aria-hidden="true">·</span>
          <span>
            {classDetail.lastActivityAt
              ? `Active ${relativeTime(classDetail.lastActivityAt)}`
              : "No activity yet"}
          </span>
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        {classDetail.stats.map((s) => (
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

      <nav aria-label="Class detail sections" className="flex gap-1 border-b border-rule">
        <NavLink
          to="."
          end
          className={({ isActive }) =>
            cn(
              "px-4 py-2.5 text-body-lg border-b-2 -mb-px",
              isActive
                ? "border-accent text-ink font-medium"
                : "border-transparent text-ink-muted hover:text-ink",
            )
          }
        >
          Roster
        </NavLink>
        <NavLink
          to="analytics"
          className={({ isActive }) =>
            cn(
              "px-4 py-2.5 text-body-lg border-b-2 -mb-px",
              isActive
                ? "border-accent text-ink font-medium"
                : "border-transparent text-ink-muted hover:text-ink",
            )
          }
        >
          Analytics
        </NavLink>
      </nav>

      <Outlet context={{ classDetail, classId: classId! } satisfies ClassDetailContext} />
    </div>
  )
}

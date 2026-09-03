/* Hallmark · pre-emit critique: P5 H5 E4 S5 R5 V4 */
import { useNavigate, useParams } from "react-router-dom"
import { Card } from "@/components/ui/card"
import { EmptyState } from "@/components/ui/state-views"
import { QueryState } from "@/components/ui/query-state"
import { PageHeaderSkeleton, CardGridSkeleton } from "@/components/ui/loading-shapes"
import { ApiError } from "@/lib/api"
import { studentLoadFailureMessage } from "@/lib/studentOutcome"
import { subjectIdentifier } from "@/lib/subjectIdentifier"
import { useSubject } from "@/lib/hooks/useStudentApi"
import { cn } from "@/lib/utils"
import { vizText } from "../components/colors"

/*
 * Subject (isSubject). Wired to `GET /student/subject/{code}` via
 * useSubject(code), code taken from the `subject/:code` route param. Header
 * with forecast/weighted-mean stat cards, two per-paper breakdown cards (bar
 * strips + boundary/position), then a paper history ledger and a topic map
 * grid — every section is backed by the `Subject` DTO.
 *
 * ── P4.10, and a topic map that printed an impossible fraction ────────────
 *
 * **Every tile read "73% / of 24 marks".** The section was titled "Marks
 * earned / marks available, per syllabus unit", each tile printed `t.acc`, and
 * under it a hardcoded "of 24 marks". Two things are wrong and they compound:
 *
 *   - `acc` is not a mark count. `routers/student.py:364` builds it as
 *     `f"{round(area.accuracy * 100.0)}%"` — a percentage. So the pair read as
 *     a numerator of 73 over a denominator of 24.
 *   - **There is no denominator on the wire at all.** `TopicTileDTO` carries
 *     `name`, `acc`, `color`, `weak` and nothing else, so the 24 was not a
 *     stale value or a rounding of something real; it was invented, and it was
 *     the same 24 on every tile of every subject.
 *
 * The fix is to say what the number is. The tiles show accuracy per syllabus
 * unit, the heading now says that, and no denominator is rendered because none
 * exists (UI spec §1.4: an absent figure beats an invented one).
 *
 * **The weighted-mean delta was green whatever it said.** `weightedMeanDelta`
 * is built as `f"{'+' if delta >= 0 else ''}{delta} since first paper"`, so it
 * is "-8 since first paper" for a student who has got worse — and it was
 * rendered in `text-ok` unconditionally. A student sliding backwards was shown
 * their decline in the product's success colour. This is D4.1's "+0 in teal"
 * finding on a different screen, and the tone is derived from the sign now.
 *
 * **The whole screen was arbitrary values.** ~40 `text-[13.5px]`-class
 * literals, three raw `oklch()` backgrounds bypassing the token block
 * entirely (§3.2 item 13), and `font-serif`/`font-mono` paired with a size
 * literal rather than the rungs that name their own face.
 */
export function Subject() {
  const navigate = useNavigate()
  const { code } = useParams<{ code: string }>()
  const query = useSubject(code ?? "")

  /*
   * A 404 here is not a failure: it is a subject with no corrected papers yet,
   * which is every subject on a new account. It is handled before
   * `<QueryState>` rather than through its `error` prop: that prop renders one
   * treatment per query (a heading, a body, and a retry that calls
   * `query.refetch()`), and this case needs a different heading, a different
   * body and an action that navigates to `/student/correct` rather than
   * retrying a request that will 404 again. `EmptyState`, not `ErrorState`,
   * for the same reason the original branch used it: nothing is broken.
   */
  if (query.status === "error" && query.error instanceof ApiError && query.error.status === 404) {
    return (
      <div className="lm-screen flex flex-col gap-6">
        {/* The page must identify itself in every state, not only the populated
            one — see the same heading inside `<QueryState>` below for the
            pending/generic-error cases this mirrors. */}
        <h1 className="sr-only">Subject {code}</h1>
        <EmptyState
          heading={`Nothing recorded for ${code} yet`}
          body="Once you correct a paper in this subject, your grade forecast, per-paper breakdown and topic map all appear here."
          action={{ label: "Correct a paper", onClick: () => navigate("/student/correct") }}
        />
      </div>
    )
  }

  return (
    <div className="lm-screen flex flex-col gap-6">
      <QueryState
        query={query}
        srHeading={`Subject ${code}`}
        skeleton={
          <>
            <PageHeaderSkeleton />
            <CardGridSkeleton count={2} />
          </>
        }
        error={{ heading: "We couldn't load this subject", body: studentLoadFailureMessage }}
      >
        {(data) => {
          const { header: subjectHeader, papersBreakdown, topicMap, paperHistory } = data
          const { primary, secondary } = subjectIdentifier(
            subjectHeader.name,
            subjectHeader.code,
            subjectHeader.qualificationLevel,
          )

          // The backend renders the sign into the string ("+4 since first paper" /
          // "-8 since first paper"), so the sign is what decides the tone. Neither
          // arm is the accent: on this palette accent is the alert register, and a
          // decline is disappointing news rather than an error the student can act on.
          const declining = subjectHeader.weightedMeanDelta.trimStart().startsWith("-")

          return (
            <>
              <div className="flex flex-wrap items-start gap-6">
                {/* `basis-80` + `min-w-0`, not `min-w-80` (P6.1). The intent is "keep
                    this column beside the cards until there is no longer room for
                    both", and a flex BASIS says that without also forbidding the column
                    from ever being narrower than 320px. `min-w-80` forbade it: at the
                    320px viewport §6.1 requires, 320px of column plus the screen's own
                    horizontal padding is wider than the screen, so the header ran off
                    the side. It did not show up as a scrollbar either, because html and
                    body clip — the title simply had its end cut off. */}
                <div className="min-w-0 flex-1 basis-80">
                  {/* Rendered only when there is something to show: an unregistered
                      subject code resolves `name === code` and `secondary` collapses
                      to "" (see `subjectIdentifier`'s docstring), and an empty
                      eyebrow `<div>` would still take up a line of vertical rhythm. */}
                  {secondary ? (
                    <div className="text-data-sm text-ink-muted">{secondary}</div>
                  ) : null}
                  <h1 className="mt-1 text-display-lg text-ink">{primary}</h1>
                  <div className="mt-2 max-w-[62ch] text-pretty text-body-md text-ink-muted">
                    {subjectHeader.intro}
                  </div>
                </div>
                <div className="flex flex-wrap gap-3">
                  <Card className="min-w-33 px-5 py-4 text-center">
                    <div className="text-eyebrow text-ink-faint">Forecast grade</div>
                    {/* The data face for both figures: §4.2 puts grades, scores and
                        percentages on the tabular rung, not the display face. They
                        were `font-serif text-[44px]`, which is the display face wearing
                        a literal size. */}
                    <div className="text-data-lg text-ink">{subjectHeader.forecast}</div>
                    <div className="text-body-sm text-ink-muted">at current trajectory</div>
                  </Card>
                  <Card className="min-w-33 px-5 py-4 text-center">
                    <div className="text-eyebrow text-ink-faint">Weighted mean</div>
                    <div className="text-data-lg text-ink">
                      {subjectHeader.weightedMean}
                      <span className="text-data-md">%</span>
                    </div>
                    <div className={cn("text-body-sm", declining ? "text-ink-muted" : "text-ok")}>
                      {subjectHeader.weightedMeanDelta}
                    </div>
                  </Card>
                </div>
              </div>

              <div className="grid grid-cols-1 gap-5 min-[1180px]:grid-cols-2">
                {papersBreakdown.map((p) => (
                  <Card key={p.title} className="p-5">
                    <div className="flex items-baseline gap-2.5">
                      <div className="text-body-md font-semibold text-ink">{p.title}</div>
                      <div className="text-body-sm text-ink-muted">{p.sub}</div>
                      <div className="flex-1" />
                      <div className="text-data-md text-ink">{p.mean}</div>
                    </div>
                    <div className="my-5 mb-2.5 flex h-24 items-end gap-1.5">
                      {p.bars.map((b) => (
                        <div
                          key={b.label}
                          className="flex h-full flex-1 flex-col items-center justify-end gap-1.5"
                        >
                          {/* Two fixes in one element. `bg-rule-strong` for the
                              resting bar, not a raw `oklch()` literal (§3.2 item 13:
                              every colour comes from the token block, and this one
                              bypassed it).

                              And `bg-ink` for the highlighted bar, not `bg-accent`.
                              `highlight` marks the most recent paper, which is
                              emphasis; the row directly beneath it uses accent to mean
                              "you are short of the boundary". Having one colour carry
                              both in the same card is how a student reads "your latest
                              paper" as "your latest paper is a problem" on the card
                              where it isn't. */}
                          <div
                            className={cn(
                              "w-full rounded-t-sm",
                              b.highlight ? "bg-ink" : "bg-rule-strong",
                            )}
                            style={{ height: `${b.value}%` }}
                          />
                          <div className="text-data-sm text-ink-faint">{b.label}</div>
                        </div>
                      ))}
                    </div>
                    <div className="flex gap-5 border-t border-rule pt-3">
                      <div>
                        <div className="text-eyebrow text-ink-faint">Predicted boundary</div>
                        <div className="mt-0.5 text-data-sm text-ink">{p.boundary}</div>
                      </div>
                      <div>
                        <div className="text-eyebrow text-ink-faint">Your position</div>
                        <div
                          className={cn(
                            "mt-0.5 text-data-sm",
                            p.positionOk ? "text-ok" : "text-accent-ink",
                          )}
                        >
                          {p.position}
                        </div>
                      </div>
                    </div>
                  </Card>
                ))}
              </div>

              <div className="grid grid-cols-1 items-start gap-5 min-[1180px]:grid-cols-[1.3fr_1fr]">
                <Card className="overflow-hidden">
                  <div className="flex items-baseline gap-2.5 px-5 pt-4 pb-3">
                    <div className="text-body-md font-semibold text-ink">Paper history</div>
                    <div className="text-body-sm text-ink-muted">newest first</div>
                  </div>
                  {paperHistory.map((h) => (
                    <button
                      key={h.id}
                      onClick={() => navigate(`/student/result/${h.id}`)}
                      className="grid w-full cursor-pointer grid-cols-[150px_1fr_90px_70px_44px] items-center gap-3 border-0 border-t border-rule bg-transparent px-5 py-3 text-start transition-colors hover:bg-paper-sunk focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
                    >
                      <span className="text-data-sm text-ink">{h.paper}</span>
                      <span className="text-body-sm text-ink-muted">{h.note}</span>
                      <span className="text-data-sm text-ink-muted">{h.marks}</span>
                      <span className="text-data-sm text-ink">{h.pct}</span>
                      {/* `text-end`, not `text-right`: this column follows `dir`. */}
                      <span className={cn("text-data-md text-end", vizText(h.gradeColor))}>
                        {h.grade}
                      </span>
                    </button>
                  ))}
                </Card>

                <Card className="p-5">
                  <div className="text-body-md font-semibold text-ink">Topic map</div>
                  {/* Says what the number is. It used to promise "marks earned /
                      marks available", which no field on this DTO supplies. */}
                  <div className="mb-4 text-body-sm text-ink-muted">
                    Your accuracy in each syllabus unit, across every paper you've corrected
                  </div>
                  <div className="grid grid-cols-1 gap-2 min-[1180px]:grid-cols-2">
                    {topicMap.map((t) => (
                      <div
                        key={t.name}
                        className={cn(
                          "rounded-lg border border-rule px-3 py-2.5",
                          t.weak ? "bg-accent-wash" : "bg-paper-sunk",
                        )}
                      >
                        <div className="text-body-sm font-medium text-ink">{t.name}</div>
                        <div className="mt-1.5 flex items-baseline gap-1.5">
                          <div className={cn("text-data-md", vizText(t.color))}>{t.acc}</div>
                          {/* No denominator: `TopicTileDTO` carries none, and the one
                              that used to be here was a hardcoded 24 on every tile of
                              every subject. `acc` is already a percentage. */}
                          <div className="text-body-sm text-ink-muted">accuracy</div>
                        </div>
                      </div>
                    ))}
                  </div>
                </Card>
              </div>
            </>
          )
        }}
      </QueryState>
    </div>
  )
}

import { useState } from "react"
import { cn } from "@/lib/utils"
import { Avatar } from "../components/Avatar"
import { ApiError } from "@/lib/api"
import { useGradingQueue, usePaperDetail } from "@/lib/hooks/useTeacherApi"
import type { QueueRow } from "@/lib/teacherTypes"

/*
 * Review. Wired to `GET /grading/queue` (`useGradingQueue()`) for the
 * right-hand queue list — one row per flagged QUESTION, not per paper — and
 * `GET /papers/{paperId}` (`usePaperDetail()`) for the selected row's full
 * paper, from which the matching `QuestionResult` is picked out by
 * `questionId`. See BUILD/STATE.md's P2.8 step 4 plan for the full design.
 *
 * Cuts / judgment calls made vs. the mock (`flagged`/`queue`/`reviewProgress`
 * in the old `data.ts`):
 *  - The handwriting-transcript panel and the per-mark-point ok/no/dependent
 *    breakdown (`PointRow`/`POINT_STYLE`/`MarkingPoint`) are dropped
 *    entirely — no OCR transcript or per-mark-point field exists on
 *    `QuestionResult`.
 *  - The award-option buttons + "Confirm & next" button are dropped — there
 *    is no override-submission endpoint yet (Phase 3 per MISSION §4).
 *  - The "Filter" button is dropped — `GradingQueueDTO` has no filter
 *    concept.
 *  - "Approve all (N)" is dropped — no bulk-approve endpoint exists.
 *  - The bottom "Auto-graded 156/168" progress bar is dropped — the queue
 *    count is per-question while the overview stats are per-paper, so there
 *    is no clean same-unit backend source to render it honestly.
 *  - The mock's fabricated "why Lemely flagged this" narrative is replaced
 *    by the question's real `reviewReason` field — a genuine data upgrade,
 *    not just a cut.
 *  - The "Live" pill next to the title had no real backing signal (no
 *    push/poll freshness concept on the queue) — dropped rather than kept
 *    as decoration.
 *  - The header's hardcoded "12 answers · 0625/31 · May/June 2020" is
 *    replaced by a real `{rows.length} flagged answer(s)` count.
 *  - Plagiarism/AI-detection badges (same pattern as
 *    `student/screens/PaperResult.tsx`) render when the matched question's
 *    `plagiarismFlagged`/`aiDetectionFlagged` are true.
 *  - Prev/next navigation through queue rows is kept — pure client-side
 *    array navigation over `useGradingQueue()`'s real rows, no backend
 *    change needed.
 */

function confidencePercent(confidence: number | null): number | null {
  return confidence == null ? null : Math.round(confidence * 100)
}

function initialsOf(name: string): string {
  return name
    .split(" ")
    .map((w) => w[0])
    .join("")
}

export function Review() {
  const [selectedIndex, setSelectedIndex] = useState(0)

  const queueQuery = useGradingQueue()
  const rows = queueQuery.data?.rows ?? []
  const index = rows.length > 0 ? selectedIndex % rows.length : 0
  const selectedRow: QueueRow | undefined = rows[index]

  const paperDetailQuery = usePaperDetail(selectedRow?.paperId)

  const prev = () => {
    if (rows.length === 0) return
    setSelectedIndex((v) => (v + rows.length - 1) % rows.length)
  }
  const next = () => {
    if (rows.length === 0) return
    setSelectedIndex((v) => (v + 1) % rows.length)
  }

  if (queueQuery.isPending) {
    return (
      <div className="lm-screen flex flex-col gap-5">
        <div className="text-[13.5px] text-t2">Loading review queue…</div>
      </div>
    )
  }

  if (queueQuery.isError) {
    return (
      <div className="lm-screen flex flex-col gap-5">
        <div className="text-[13.5px] text-accent">
          Couldn't load the review queue: {queueQuery.error.message}
        </div>
      </div>
    )
  }

  if (rows.length === 0 || !selectedRow) {
    return (
      <div className="lm-screen flex flex-col gap-5">
        <div className="pb-[18px] border-b border-border">
          <div className="font-serif text-[34px] leading-[1.1]">Review AI grading</div>
        </div>
        <div className="text-[13.5px] text-t2">Nothing flagged right now.</div>
      </div>
    )
  }

  const isNotGraded =
    paperDetailQuery.isError &&
    paperDetailQuery.error instanceof ApiError &&
    paperDetailQuery.error.status === 409

  const matchedQuestion = paperDetailQuery.data?.questions.find(
    (q) => q.questionId === selectedRow.questionId,
  )

  const confPct = confidencePercent(selectedRow.confidence)

  return (
    <div className="lm-screen flex flex-col gap-5">
      <div className="flex items-end gap-[18px] pb-[18px] border-b border-border flex-wrap gap-y-2.5">
        <div>
          <div className="font-serif text-[34px] leading-[1.1]">Review AI grading</div>
          <div className="font-mono text-[11.5px] text-t2 mt-[7px]">
            {rows.length} flagged answer{rows.length === 1 ? "" : "s"}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-[1fr_262px] gap-5 items-start">
        {/* Detail panel */}
        <div className="bg-surface border border-border rounded-[14px] p-[18px]">
          <div className="flex items-center gap-3">
            <Avatar
              initials={initialsOf(selectedRow.name)}
              tone="accent"
              className="w-[34px] h-[34px] text-[12px]"
            />
            <div className="flex-1">
              <div className="text-[14px] font-medium">{selectedRow.name}</div>
              <div className="font-mono text-[11px] text-t2 mt-0.5">
                {selectedRow.questionId}
                {selectedRow.topic ? ` · ${selectedRow.topic}` : ""}
              </div>
            </div>
            <button
              onClick={prev}
              aria-label="Previous flagged answer"
              className="w-[30px] h-[30px] border border-border bg-surface rounded-lg cursor-pointer text-t2 hover:bg-surface-2"
            >
              ‹
            </button>
            <button
              onClick={next}
              aria-label="Next flagged answer"
              className="w-[30px] h-[30px] border border-border bg-surface rounded-lg cursor-pointer text-t2 hover:bg-surface-2"
            >
              ›
            </button>
          </div>

          <div className="border border-border rounded-[11px] p-[18px] mt-4 bg-[oklch(0.985_0.008_80)] flex flex-col gap-4">
            <div className="flex items-center gap-[14px] flex-wrap">
              <div className="text-[11.5px] text-t2 leading-[1.3]">AI confidence</div>
              {confPct != null ? (
                <>
                  <div className="font-mono text-[14px] text-err">{confPct}%</div>
                  <div className="w-20 h-1.5 rounded-[3px] bg-[oklch(0.92_0.012_78)]">
                    <div
                      className="h-full rounded-[3px] bg-err"
                      style={{ width: `${confPct}%` }}
                    />
                  </div>
                </>
              ) : (
                <div className="font-mono text-[12px] text-t3">unavailable</div>
              )}
              <div className="flex-1" />
              <div className="font-serif text-[24px]">
                {selectedRow.awardedMarks}
                <span className="text-[14px] text-t2">/{selectedRow.maxMarks}</span>
              </div>
            </div>

            {paperDetailQuery.isPending ? (
              <div className="text-[13px] text-t2">Loading paper detail…</div>
            ) : isNotGraded ? (
              <div className="text-[13px] text-t2">This paper hasn't been graded yet.</div>
            ) : paperDetailQuery.isError ? (
              <div className="text-[13px] text-accent">
                Couldn't load paper detail: {paperDetailQuery.error.message}
              </div>
            ) : !matchedQuestion ? (
              <div className="text-[13px] text-t2">
                Couldn't find this question in the paper's results.
              </div>
            ) : (
              <>
                {matchedQuestion.feedback ? (
                  <div className="text-[13.5px] leading-[1.55] text-pretty">
                    {matchedQuestion.feedback}
                  </div>
                ) : null}

                {matchedQuestion.reviewReason ? (
                  <div className="border border-border rounded-[12px] px-[18px] py-4 bg-surface">
                    <div className="flex items-center gap-2.5">
                      <span className="w-[22px] h-[22px] rounded-md bg-accent-subtle flex items-center justify-center">
                        <span className="w-2 h-2 bg-accent rotate-45" />
                      </span>
                      <div className="text-[13.5px] font-medium">
                        Why Lemely flagged this
                      </div>
                    </div>
                    <div className="text-[13px] leading-[1.55] text-t2 mt-3 text-pretty">
                      {matchedQuestion.reviewReason}
                    </div>
                  </div>
                ) : null}

                {matchedQuestion.plagiarismFlagged || matchedQuestion.aiDetectionFlagged ? (
                  <div className="flex gap-[9px]">
                    {matchedQuestion.plagiarismFlagged ? (
                      <span className="text-[11px] border border-border rounded-[20px] px-[9px] py-0.5 text-accent">
                        Plagiarism flagged
                      </span>
                    ) : null}
                    {matchedQuestion.aiDetectionFlagged ? (
                      <span className="text-[11px] border border-border rounded-[20px] px-[9px] py-0.5 text-accent">
                        AI-detection flagged
                      </span>
                    ) : null}
                  </div>
                ) : null}
              </>
            )}
          </div>
        </div>

        {/* Queue */}
        <div className="bg-surface border border-border rounded-[14px] overflow-hidden">
          <div className="px-4 pt-[15px] pb-3 font-mono text-[10.5px] tracking-[0.1em] uppercase text-t3">
            Review queue · {rows.length}
          </div>
          {rows.map((row, i) => {
            const on = i === index
            const pct = confidencePercent(row.confidence)
            return (
              <button
                key={`${row.paperId}-${row.questionId}`}
                onClick={() => setSelectedIndex(i)}
                className={cn(
                  "grid grid-cols-[28px_1fr_auto] gap-2.5 items-center w-full text-left border-0 border-t border-border cursor-pointer px-4 py-3",
                  on ? "bg-surface" : "bg-transparent hover:bg-[oklch(0.975_0.01_78)]",
                )}
              >
                <Avatar
                  initials={initialsOf(row.name)}
                  tone={on ? "accent" : "neutral"}
                  className="w-[26px] h-[26px] text-[10.5px]"
                />
                <span>
                  <span
                    className={cn(
                      "block text-[12.5px]",
                      on ? "font-semibold" : "font-normal",
                    )}
                  >
                    {row.name}
                  </span>
                  <span className="block font-mono text-[10.5px] text-t3 mt-0.5">
                    {row.questionId}
                    {row.topic ? ` · ${row.topic}` : ""}
                  </span>
                </span>
                <span className="text-right">
                  <span
                    className={cn(
                      "block font-mono text-[11.5px]",
                      pct != null && pct < 70 ? "text-err" : "text-t2",
                    )}
                  >
                    {pct != null ? `${pct}%` : "—"}
                  </span>
                  <span className="block font-mono text-[10.5px] text-t3 mt-0.5">
                    {row.awardedMarks}/{row.maxMarks}
                  </span>
                </span>
              </button>
            )
          })}
        </div>
      </div>
    </div>
  )
}

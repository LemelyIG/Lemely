import { useLocation, useParams } from "react-router-dom"
import { Check, Minus, Warning } from "@phosphor-icons/react"
import { Card } from "@/components/ui/card"
import { ApiError } from "@/lib/api"
import { useResult } from "@/lib/hooks/useStudentApi"
import type { IntegrityRow, QuestionResult, Result } from "@/lib/studentTypes"
import { BoundaryRail } from "../components/BoundaryRail"

/*
 * Paper Result (isResult) - the flagship screen. Renders one result, from
 * either of two sources:
 *   - live: `location.state`, set by `CorrectPaper`'s navigate() right after a
 *     `/student/correct` run completes - carries a real `questions` array, so
 *     the flat per-question list renders.
 *   - history: `GET /student/result/{paperId}` (useResult) when there's no
 *     live state (browsing from `Subject`'s paper-history table) - no
 *     per-question detail is stored for history records, so an honest note
 *     replaces the list instead of an empty or fabricated one.
 * The shared header (marks/percentage/grade, boundary rail, integrity +
 * provenance sidebar) renders from whichever source is active.
 */

type LiveResult = Result & { questions: QuestionResult[] }

function isLiveResult(state: unknown): state is LiveResult {
  return !!state && typeof state === "object" && "questions" in state
}

function IntegrityMark({ row }: { row: IntegrityRow }) {
  const Icon = row.mark === "check" ? Check : row.mark === "bang" ? Warning : Minus
  return (
    <div
      className={`w-4 h-4 flex-none mt-px rounded-full border-[1.5px] flex items-center justify-center ${
        row.color === "ok"
          ? "border-ok text-ok"
          : row.color === "warn"
            ? "border-warn text-warn"
            : "border-t2 text-t2"
      }`}
    >
      <Icon size={9} weight="bold" />
    </div>
  )
}

function ResultHeader({ res }: { res: Result }) {
  return (
    <Card className="rounded-xl overflow-hidden">
      <div className="lm-cols grid grid-cols-[1fr_300px] max-[1180px]:grid-cols-1">
        <div className="px-7 py-[26px]">
          <div className="flex items-center gap-[9px] font-mono text-[11.5px] text-t2 flex-wrap">
            <span>{res.code}</span>
            <span className="text-border">/</span>
            <span>{res.paper}</span>
            <span className="text-border">/</span>
            <span>{res.session}</span>
            {res.markerLabel ? (
              <span className="border border-border rounded-[20px] px-2 py-0.5 text-[10px] tracking-[0.06em]">
                {res.markerLabel}
              </span>
            ) : null}
          </div>
          {res.headline ? (
            <div className="font-serif text-[34px] leading-[1.12] mt-2.5">
              {res.headline}
            </div>
          ) : null}
          {res.summary ? (
            <div className="text-[14px] text-t2 mt-[9px] max-w-[56ch] text-pretty">
              {res.summary}
            </div>
          ) : null}

          <div className="flex gap-[26px] mt-6 flex-wrap">
            <div>
              <div className="text-[11px] tracking-[0.09em] uppercase text-t3">
                Marks
              </div>
              <div className="font-serif text-[38px] leading-[1.1]">
                {res.awarded}
                <span className="text-[20px] text-t2">/{res.max}</span>
              </div>
            </div>
            <div>
              <div className="text-[11px] tracking-[0.09em] uppercase text-t3">
                Percentage
              </div>
              <div className="font-serif text-[38px] leading-[1.1]">
                {res.pct}
                <span className="text-[20px] text-t2">%</span>
              </div>
            </div>
            <div>
              <div className="text-[11px] tracking-[0.09em] uppercase text-t3">
                Predicted grade
              </div>
              <div className="font-serif text-[38px] leading-[1.1] text-accent">
                {res.grade}
              </div>
            </div>
          </div>

          <div className="mt-[30px] border-t border-border pt-[22px]">
            <div className="flex items-baseline gap-2.5">
              <div className="text-[11px] tracking-[0.09em] uppercase text-t3">
                Against the {res.boundaryYear} boundaries
              </div>
              <div className="flex-1" />
              <div className="font-mono text-[11.5px] text-t2">
                {res.railFoot}
              </div>
            </div>
            <BoundaryRail pct={res.railLeft} />
            {res.railNote ? (
              <div className="text-[13px] text-t2 leading-[1.5] text-pretty">
                {res.railNote}
              </div>
            ) : null}
          </div>
        </div>

        <div className="border-l border-border bg-surface-2 px-[22px] py-6 flex flex-col gap-4">
          <div className="text-[12.5px] font-semibold">
            Integrity &amp; provenance
          </div>
          {res.integrity.length === 0 ? (
            <div className="text-[11.5px] text-t2 leading-[1.4]">
              No integrity checks recorded for this paper.
            </div>
          ) : (
            res.integrity.map((i) => (
              <div key={i.label} className="flex gap-2.5 items-start">
                <IntegrityMark row={i} />
                <div>
                  <div className="text-[12.5px] leading-[1.3]">{i.label}</div>
                  <div className="text-[11.5px] text-t2 mt-0.5 leading-[1.35]">
                    {i.detail}
                  </div>
                </div>
              </div>
            ))
          )}
          {res.provenance ? (
            <div className="mt-auto font-mono text-[10.5px] text-t3 leading-[1.6] break-all border-t border-border pt-3 whitespace-pre-line">
              {res.provenance}
            </div>
          ) : null}
        </div>
      </div>
    </Card>
  )
}

function QuestionCard({ q }: { q: QuestionResult }) {
  return (
    <div className="bg-surface border border-border rounded-lg px-5 py-[18px]">
      <div className="flex items-center gap-3 flex-wrap">
        <div className="font-mono text-[13px] font-medium">{q.questionId}</div>
        {q.topic ? <div className="text-[12.5px] text-t2">{q.topic}</div> : null}
        <div className="flex-1" />
        <div className="text-[10.5px] tracking-[0.06em] uppercase text-t2 border border-border rounded-[20px] px-[9px] py-0.5">
          {q.markerSource}
        </div>
        {q.confidence != null ? (
          <div className="font-mono text-[11.5px] text-t2">
            conf {q.confidence.toFixed(2)}
          </div>
        ) : null}
        <div className="font-serif text-[23px] leading-none">
          {q.awardedMarks}
          <span className="text-[14px] text-t2">/{q.maxMarks}</span>
        </div>
      </div>
      {q.feedback ? (
        <div className="mt-[14px] px-[14px] py-3 rounded-[10px] text-[12.5px] leading-[1.5] text-pretty bg-surface-2 text-t2">
          {q.feedback}
        </div>
      ) : null}
      {q.reviewReason ? (
        <div className="mt-[10px] text-[12px] text-warn leading-[1.4]">
          Needs review: {q.reviewReason}
        </div>
      ) : null}
      {q.plagiarismFlagged || q.aiDetectionFlagged ? (
        <div className="mt-[10px] flex gap-[9px]">
          {q.plagiarismFlagged ? (
            <span className="text-[11px] border border-border rounded-[20px] px-[9px] py-0.5 text-accent">
              Plagiarism flagged
            </span>
          ) : null}
          {q.aiDetectionFlagged ? (
            <span className="text-[11px] border border-border rounded-[20px] px-[9px] py-0.5 text-accent">
              AI-detection flagged
            </span>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}

function QuestionList({ questions }: { questions: QuestionResult[] }) {
  if (questions.length === 0) {
    return (
      <Card className="p-5">
        <div className="text-[13px] text-t2 leading-[1.5]">
          No per-question detail was returned for this paper.
        </div>
      </Card>
    )
  }
  return (
    <div className="flex flex-col gap-3">
      {questions.map((q) => (
        <QuestionCard key={q.questionId} q={q} />
      ))}
    </div>
  )
}

export function PaperResult() {
  const { paperId } = useParams<{ paperId: string }>()
  const location = useLocation()
  const live = isLiveResult(location.state) ? location.state : null

  const { data, isPending, isError, error } = useResult(live ? "" : (paperId ?? ""))

  if (live) {
    return (
      <div className="lm-screen flex flex-col gap-[22px]">
        <ResultHeader res={live} />
        <QuestionList questions={live.questions} />
      </div>
    )
  }

  if (isPending) {
    return (
      <div className="lm-screen flex flex-col gap-6">
        <div className="text-[13.5px] text-t2">Loading result…</div>
      </div>
    )
  }

  if (isError) {
    if (error instanceof ApiError && error.status === 404) {
      return (
        <div className="lm-screen flex flex-col gap-6">
          <div className="text-[13.5px] text-t2">
            No paper recorded at {paperId}.
          </div>
        </div>
      )
    }
    return (
      <div className="lm-screen flex flex-col gap-6">
        <div className="text-[13.5px] text-accent">
          Couldn't load this result: {error.message}
        </div>
      </div>
    )
  }

  return (
    <div className="lm-screen flex flex-col gap-[22px]">
      <ResultHeader res={data} />
      <Card className="p-5">
        <div className="text-[13px] text-t2 leading-[1.5]">
          Per-question detail is only available right after correcting a paper.
        </div>
      </Card>
    </div>
  )
}

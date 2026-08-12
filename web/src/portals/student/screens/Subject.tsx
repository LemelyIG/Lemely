import { useNavigate, useParams } from "react-router-dom"
import { Card } from "@/components/ui/card"
import { ApiError } from "@/lib/api"
import { useSubject } from "@/lib/hooks/useStudentApi"
import { vizText } from "../components/colors"

/*
 * Subject (isSubject). Wired to `GET /student/subject/{code}` via
 * useSubject(code), code taken from the `subject/:code` route param. Header
 * with forecast/weighted-mean stat cards, two per-paper breakdown cards (bar
 * strips + boundary/position), then a paper history ledger and a topic map
 * grid — every section is backed by the `Subject` DTO.
 */
export function Subject() {
  const navigate = useNavigate()
  const { code } = useParams<{ code: string }>()
  const { data, isPending, isError, error } = useSubject(code ?? "")

  /* The page must identify itself in every state, not only the populated one.
     The visible title below is the subject's full name, which is exactly what
     these three states do not have yet — so they carry the code instead, for
     assistive tech only, rather than going without a page heading precisely
     when there is least other content to orient by. Same defect G-13 shipped
     with and the same fix; it stayed invisible here because this route had no
     audit-registry entry at all until P5.11. */
  const fallbackHeading = <h1 className="sr-only">Subject {code}</h1>

  if (isPending) {
    return (
      <div className="lm-screen flex flex-col gap-6">
        {fallbackHeading}
        <div className="text-[13.5px] text-t2">Loading subject…</div>
      </div>
    )
  }

  if (isError) {
    if (error instanceof ApiError && error.status === 404) {
      return (
        <div className="lm-screen flex flex-col gap-6">
          {fallbackHeading}
          <div className="text-[13.5px] text-t2">
            No papers recorded for {code} yet.
          </div>
        </div>
      )
    }
    return (
      <div className="lm-screen flex flex-col gap-6">
        {fallbackHeading}
        <div className="text-[13.5px] text-accent">
          Couldn't load this subject: {error.message}
        </div>
      </div>
    )
  }

  const { header: subjectHeader, papersBreakdown, topicMap, paperHistory } =
    data

  return (
    <div className="lm-screen flex flex-col gap-6">
      <div className="flex items-start gap-[22px] flex-wrap">
        <div className="flex-1 min-w-[320px]">
          <div className="font-mono text-[12px] text-t2">
            {subjectHeader.meta}
          </div>
          <h1 className="font-serif text-[38px] leading-[1.1] mt-1">
            {subjectHeader.title}
          </h1>
          <div className="text-[14px] text-t2 mt-2 max-w-[62ch] text-pretty">
            {subjectHeader.intro}
          </div>
        </div>
        <div className="flex gap-3">
          <Card className="px-5 py-4 rounded-[13px] text-center min-w-[132px]">
            <div className="text-[11px] tracking-[0.09em] uppercase text-t3">
              Forecast grade
            </div>
            <div className="font-serif text-[44px] leading-[1.1] text-accent">
              {subjectHeader.forecast}
            </div>
            <div className="text-[11.5px] text-t2">at current trajectory</div>
          </Card>
          <Card className="px-5 py-4 rounded-[13px] text-center min-w-[132px]">
            <div className="text-[11px] tracking-[0.09em] uppercase text-t3">
              Weighted mean
            </div>
            <div className="font-serif text-[44px] leading-[1.1]">
              {subjectHeader.weightedMean}
              <span className="text-[22px]">%</span>
            </div>
            <div className="text-[11.5px] text-ok">
              {subjectHeader.weightedMeanDelta}
            </div>
          </Card>
        </div>
      </div>

      <div className="lm-cols grid grid-cols-2 gap-5 max-[1180px]:grid-cols-1">
        {papersBreakdown.map((p) => (
          <Card key={p.title} className="p-5">
            <div className="flex items-baseline gap-2.5">
              <div className="text-[15px] font-semibold">{p.title}</div>
              <div className="text-[12px] text-t2">{p.sub}</div>
              <div className="flex-1" />
              <div className="font-serif text-[26px] leading-none">{p.mean}</div>
            </div>
            <div className="flex items-end gap-1.5 h-24 my-5 mb-2.5">
              {p.bars.map((b) => (
                <div
                  key={b.label}
                  className="flex-1 flex flex-col justify-end items-center gap-1.5 h-full"
                >
                  <div
                    className={`w-full rounded-t-[4px] ${b.highlight ? "bg-accent" : "bg-[oklch(0.88_0.02_35)]"}`}
                    style={{ height: `${b.value}%` }}
                  />
                  <div className="text-[9.5px] text-t3 font-mono">{b.label}</div>
                </div>
              ))}
            </div>
            <div className="border-t border-border pt-3 flex gap-[18px]">
              <div>
                <div className="text-[11px] text-t3 tracking-[0.08em] uppercase">
                  Predicted boundary
                </div>
                <div className="text-[13.5px] font-mono mt-[3px]">
                  {p.boundary}
                </div>
              </div>
              <div>
                <div className="text-[11px] text-t3 tracking-[0.08em] uppercase">
                  Your position
                </div>
                <div
                  className={`text-[13.5px] font-mono mt-[3px] ${p.positionOk ? "text-ok" : "text-accent"}`}
                >
                  {p.position}
                </div>
              </div>
            </div>
          </Card>
        ))}
      </div>

      <div className="lm-cols grid grid-cols-[1.3fr_1fr] gap-5 items-start max-[1180px]:grid-cols-1">
        <Card className="overflow-hidden">
          <div className="px-5 pt-[18px] pb-3 flex items-baseline gap-2.5">
            <div className="text-[15px] font-semibold">Paper history</div>
            <div className="text-[12px] text-t2">newest first</div>
          </div>
          {paperHistory.map((h) => (
            <button
              key={h.id}
              onClick={() => navigate(`/student/result/${h.id}`)}
              className="grid grid-cols-[150px_1fr_90px_70px_44px] gap-3 items-center w-full text-left border-0 border-t border-border bg-transparent font-sans cursor-pointer px-5 py-3 transition-colors hover:bg-surface-2"
            >
              <span className="font-mono text-[12px]">{h.paper}</span>
              <span className="text-[12.5px] text-t2">{h.note}</span>
              <span className="font-mono text-[12px] text-t2">{h.marks}</span>
              <span className="font-mono text-[12px]">{h.pct}</span>
              <span
                className={`font-serif text-[21px] text-right ${vizText(h.gradeColor)}`}
              >
                {h.grade}
              </span>
            </button>
          ))}
        </Card>

        <Card className="p-5">
          <div className="text-[15px] font-semibold">Topic map</div>
          <div className="text-[12px] text-t2 mb-4">
            Marks earned / marks available, per syllabus unit
          </div>
          <div className="lm-cols grid grid-cols-2 gap-2 max-[1180px]:grid-cols-1">
            {topicMap.map((t) => (
              <div
                key={t.name}
                className={`border border-border rounded-[10px] px-3 py-[11px] ${t.weak ? "bg-[oklch(0.985_0.012_35)]" : "bg-[oklch(0.985_0.004_40)]"}`}
              >
                <div className="text-[12.5px] font-medium leading-[1.25]">
                  {t.name}
                </div>
                <div className="flex items-baseline gap-1.5 mt-1.5">
                  <div className={`font-mono text-[16px] ${vizText(t.color)}`}>
                    {t.acc}
                  </div>
                  <div className="text-[11px] text-t2">of 24 marks</div>
                </div>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  )
}

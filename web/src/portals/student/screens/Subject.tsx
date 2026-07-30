import { useNavigate } from "react-router-dom"
import { Card } from "@/components/ui/card"
import {
  paperHistory,
  papersBreakdown,
  subjectHeader,
  topicMap,
} from "../data"
import { vizText } from "../components/colors"

/*
 * Subject (isSubject) - Physics. Header with forecast/weighted-mean stat cards,
 * two per-paper breakdown cards (bar strips + boundary/position), then a paper
 * history ledger and a topic map grid.
 */
export function Subject() {
  const navigate = useNavigate()
  return (
    <div className="lm-screen flex flex-col gap-6">
      <div className="flex items-start gap-[22px] flex-wrap">
        <div className="flex-1 min-w-[320px]">
          <div className="font-mono text-[12px] text-t2">
            {subjectHeader.meta}
          </div>
          <div className="font-serif text-[38px] leading-[1.1] mt-1">
            {subjectHeader.title}
          </div>
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
              key={h.paper}
              onClick={() => navigate(`/student/result?tab=${h.tab}`)}
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

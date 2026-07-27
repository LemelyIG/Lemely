import { useState } from "react"
import { useSearchParams } from "react-router-dom"
import { Check, Minus, Warning } from "@phosphor-icons/react"
import { Card } from "@/components/ui/card"
import {
  dropped,
  mcq,
  paperTabs,
  resultP1,
  resultP3,
  theory,
  theoryWeak,
  type IntegrityRow,
  type ResultData,
} from "../data"
import { Bar } from "../components/viz"
import { vizText } from "../components/colors"
import { BoundaryRail } from "../components/BoundaryRail"

/*
 * Paper Result (isResult) - the flagship screen. Tabs switch between Paper 1
 * (isP1, MCQ answer grid) and Paper 3 (isP3, topic-tagged theory). The shared
 * header carries marks/percentage/grade, the boundary rail, and an integrity +
 * provenance sidebar.
 */

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

function ResultHeader({ res }: { res: ResultData }) {
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
            <span className="border border-border rounded-[20px] px-2 py-0.5 text-[10px] tracking-[0.06em]">
              {res.markerLabel}
            </span>
          </div>
          <div className="font-serif text-[34px] leading-[1.12] mt-2.5">
            {res.headline}
          </div>
          <div className="text-[14px] text-t2 mt-[9px] max-w-[56ch] text-pretty">
            {res.summary}
          </div>

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
            <div className="text-[13px] text-t2 leading-[1.5] text-pretty">
              {res.railNote}
            </div>
          </div>
        </div>

        <div className="border-l border-border bg-surface-2 px-[22px] py-6 flex flex-col gap-4">
          <div className="text-[12.5px] font-semibold">
            Integrity &amp; provenance
          </div>
          {res.integrity.map((i) => (
            <div key={i.label} className="flex gap-2.5 items-start">
              <IntegrityMark row={i} />
              <div>
                <div className="text-[12.5px] leading-[1.3]">{i.label}</div>
                <div className="text-[11.5px] text-t2 mt-0.5 leading-[1.35]">
                  {i.detail}
                </div>
              </div>
            </div>
          ))}
          <div className="mt-auto font-mono text-[10.5px] text-t3 leading-[1.6] break-all border-t border-border pt-3 whitespace-pre-line">
            {res.provenance}
          </div>
        </div>
      </div>
    </Card>
  )
}

function Paper1View({ onSeeP3 }: { onSeeP3: () => void }) {
  return (
    <div className="lm-cols grid grid-cols-[1.6fr_1fr] gap-5 items-start max-[1180px]:grid-cols-1">
      <Card className="p-5">
        <div className="flex items-baseline gap-3 mb-4">
          <div className="text-[15px] font-semibold">Answer grid</div>
          <div className="text-[12px] text-t2">
            40 questions - marked deterministically against 0625/12 mark scheme
          </div>
        </div>
        <div className="grid grid-cols-10 gap-[7px]">
          {mcq.map((q) => (
            <div
              key={q.id}
              title={q.title}
              className={`border rounded-lg px-1 py-[7px] text-center transition-transform hover:-translate-y-0.5 ${
                q.correct
                  ? "bg-[oklch(0.96_0.02_150)] border-[oklch(0.90_0.03_150)]"
                  : "bg-accent-subtle border-[oklch(0.87_0.05_35)]"
              }`}
            >
              <div className="text-[9.5px] text-t3 font-mono">{q.id}</div>
              <div
                className={`font-mono text-[14px] font-medium leading-[1.4] ${q.correct ? "text-[oklch(0.38_0.09_150)]" : "text-accent"}`}
              >
                {q.ans}
              </div>
            </div>
          ))}
        </div>
        <div className="flex gap-[18px] mt-4 text-[11.5px] text-t2 items-center">
          <span className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-[3px] bg-[oklch(0.93_0.03_150)]" />
            correct
          </span>
          <span className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-[3px] bg-accent-subtle" />
            dropped
          </span>
          <span className="flex-1" />
          <span className="font-mono">
            extraction confidence 97% across all 40
          </span>
        </div>
      </Card>

      <div className="flex flex-col gap-5">
        <Card className="p-5">
          <div className="text-[15px] font-semibold mb-[3px]">
            The two you dropped
          </div>
          <div className="text-[12px] text-t2 mb-[15px]">
            Both single-mark, both recoverable
          </div>
          <div className="flex flex-col gap-3">
            {dropped.map((d) => (
              <div
                key={d.id}
                className="border border-border rounded-[11px] p-[14px] bg-surface-2"
              >
                <div className="flex items-center gap-2.5">
                  <div className="font-mono text-[12px] text-t2">Q{d.id}</div>
                  <div className="flex items-center gap-[7px] font-mono text-[13px]">
                    <span className="text-accent line-through">{d.you}</span>
                    <span className="text-t3">-&gt;</span>
                    <span className="text-ok font-medium">{d.right}</span>
                  </div>
                  <div className="flex-1" />
                  <div className="text-[10.5px] text-t3 font-mono">
                    {d.region}
                  </div>
                </div>
                <div className="text-[12.5px] text-t2 mt-[9px] leading-[1.45] text-pretty">
                  {d.note}
                </div>
              </div>
            ))}
          </div>
        </Card>

        <Card className="p-5">
          <div className="text-[15px] font-semibold mb-[3px]">
            Weakness report
          </div>
          <div className="text-[12px] text-t2 mb-[14px]">
            From the engine's topic grouping
          </div>
          <div className="flex items-baseline gap-2.5 p-3 border border-border rounded-[10px] bg-surface-2">
            <div className="text-[13px]">Unclassified</div>
            <div className="flex-1" />
            <div className="font-mono text-[13px]">95%</div>
            <div className="text-[11.5px] text-t2">2 / 40 lost</div>
          </div>
          <div className="text-[11.5px] text-t2 mt-[11px] leading-[1.5] text-pretty">
            Multiple-choice mark schemes carry no topic tags, so these two marks
            stay unclassified until the syllabus map runs. Theory papers group by
            unit automatically.
          </div>
          <button
            onClick={onSeeP3}
            className="mt-[14px] border border-border bg-transparent font-sans text-[12.5px] px-[13px] py-2 rounded-lg cursor-pointer text-t1 transition-colors hover:bg-surface-2"
          >
            See a topic-tagged theory paper -&gt;
          </button>
        </Card>
      </div>
    </div>
  )
}

function Paper3View() {
  return (
    <div className="lm-cols grid grid-cols-[1.6fr_1fr] gap-5 items-start max-[1180px]:grid-cols-1">
      <div className="flex flex-col gap-3">
        {theory.map((q) => (
          <div
            key={q.id}
            className={`bg-surface border rounded-lg px-5 py-[18px] ${q.cardWeak ? "border-[oklch(0.86_0.06_70)]" : "border-border"}`}
          >
            <div className="flex items-center gap-3">
              <div className="font-mono text-[13px] font-medium">{q.id}</div>
              <div className="text-[12.5px] text-t2">{q.topic}</div>
              <div className="flex-1" />
              <div className="text-[10.5px] tracking-[0.06em] uppercase text-t2 border border-border rounded-[20px] px-[9px] py-0.5">
                {q.marker}
              </div>
              <div className={`font-mono text-[11.5px] ${vizText(q.confColor)}`}>
                conf {q.conf}
              </div>
              <div
                className={`font-serif text-[23px] leading-none ${q.markOk ? "text-ok" : "text-accent"}`}
              >
                {q.marks}
              </div>
            </div>
            <div className="flex flex-col gap-1.5 mt-[14px]">
              {q.points.map((p) => (
                <div
                  key={p.id}
                  className="grid grid-cols-[22px_42px_1fr] gap-2.5 items-start text-[12.5px] leading-[1.4]"
                >
                  <span
                    className={`font-mono ${p.got ? "text-ok" : "text-t3"}`}
                  >
                    {p.mark === "check" ? "✓" : "·"}
                  </span>
                  <span className="font-mono text-[11px] text-t3">{p.id}</span>
                  <span className={p.got ? "text-t1" : "text-t2"}>{p.text}</span>
                </div>
              ))}
            </div>
            <div
              className={`mt-[14px] px-[14px] py-3 rounded-[10px] text-[12.5px] leading-[1.5] text-pretty ${
                q.feedbackTone === "ok"
                  ? "bg-[oklch(0.96_0.02_150)] text-[oklch(0.34_0.07_150)]"
                  : q.feedbackTone === "warn"
                    ? "bg-[oklch(0.96_0.03_70)] text-[oklch(0.40_0.07_70)]"
                    : "bg-accent-subtle text-[oklch(0.38_0.06_35)]"
              }`}
            >
              {q.feedback}
            </div>
          </div>
        ))}
      </div>

      <div className="flex flex-col gap-5">
        <Card className="p-5">
          <div className="text-[15px] font-semibold mb-[14px]">
            Where the marks went
          </div>
          <div className="flex flex-col gap-[13px]">
            {theoryWeak.map((w) => (
              <div key={w.topic} className="flex flex-col gap-[5px]">
                <div className="flex justify-between text-[12.5px]">
                  <span>{w.topic}</span>
                  <span className="font-mono text-t2">{w.marks}</span>
                </div>
                <Bar width={w.width} color={w.color} />
              </div>
            ))}
          </div>
        </Card>

        <div className="bg-accent-subtle border border-[oklch(0.88_0.05_35)] rounded-lg p-5">
          <div className="text-[15px] font-semibold mb-1">Generated for you</div>
          <div className="text-[12.5px] text-[oklch(0.42_0.05_35)] leading-[1.5] mb-[14px] text-pretty">
            A classified worksheet of 12 moments-and-equilibrium questions,
            pulled from 2015-2024 papers where you lost marks on the same step.
          </div>
          <div className="flex gap-[9px]">
            <button className="border-0 bg-accent text-accent-on font-sans text-[12.5px] px-[15px] py-[9px] rounded-lg cursor-pointer transition-colors hover:bg-accent-hover">
              Open worksheet
            </button>
            <button className="border border-[oklch(0.82_0.05_35)] bg-transparent text-[oklch(0.35_0.06_35)] font-sans text-[12.5px] px-[15px] py-[9px] rounded-lg cursor-pointer">
              18 flashcards
            </button>
          </div>
        </div>

        <Card className="p-5">
          <div className="text-[15px] font-semibold mb-1">
            One question needs a human
          </div>
          <div className="text-[12.5px] text-t2 leading-[1.5] text-pretty">
            12(c) fell below the escalation threshold (0.61). It is queued for Mr
            Sabry, who marks it in one tap - the engine learns from the
            correction.
          </div>
          <div className="flex items-center gap-[9px] mt-[14px] text-[12px] text-warn">
            <span className="w-[7px] h-[7px] rounded-full bg-warn animate-[lm-pulse_1.8s_infinite]" />{" "}
            awaiting teacher review
          </div>
        </Card>
      </div>
    </div>
  )
}

export function PaperResult() {
  const [searchParams, setSearchParams] = useSearchParams()
  const initialTab = searchParams.get("tab") === "p3" ? "p3" : "p1"
  const [tab, setTab] = useState<"p1" | "p3">(initialTab)

  const selectTab = (id: "p1" | "p3") => {
    setTab(id)
    setSearchParams(id === "p3" ? { tab: "p3" } : {}, { replace: true })
  }

  const res = tab === "p1" ? resultP1 : resultP3

  return (
    <div className="lm-screen flex flex-col gap-[22px]">
      <div className="flex gap-2.5">
        {paperTabs.map((t) => {
          const active = t.id === tab
          return (
            <button
              key={t.id}
              onClick={() => selectTab(t.id)}
              className={`border font-mono text-[12px] px-[14px] py-2 rounded-lg cursor-pointer transition-colors ${
                active
                  ? "border-ink bg-ink text-accent-on"
                  : "border-border bg-surface text-t2 hover:bg-surface-2"
              }`}
            >
              {t.label}
            </button>
          )
        })}
      </div>

      <ResultHeader res={res} />

      {tab === "p1" ? <Paper1View onSeeP3={() => selectTab("p3")} /> : <Paper3View />}
    </div>
  )
}

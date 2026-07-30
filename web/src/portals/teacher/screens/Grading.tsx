import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import {
  detected,
  pipeline,
  autoGrade,
  batchTabs,
  filterPapers,
  type BatchTabId,
  type Paper,
} from "../data"

const CIRC = 2 * Math.PI * 42

const PIPE_MARK = { done: "✓", active: "●", idle: "" } as const

const CHIP_TONE: Record<Paper["kind"], string> = {
  graded: "bg-ok-bg text-[oklch(0.36_0.09_152)]",
  review: "bg-err-bg text-[oklch(0.40_0.10_22)]",
  processing: "bg-accent-subtle text-[oklch(0.42_0.10_68)]",
  queued: "bg-[oklch(0.93_0.008_78)] text-t2",
}

function PaperCard({ paper, onOpen }: { paper: Paper; onOpen: () => void }) {
  const dim = paper.kind === "processing" || paper.kind === "queued"
  const confTone =
    paper.kind === "review"
      ? "text-err"
      : paper.kind === "graded"
        ? "text-t2"
        : "text-t3"

  return (
    <div
      onClick={onOpen}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault()
          onOpen()
        }
      }}
      className={cn(
        "rounded-[13px] overflow-hidden bg-surface cursor-pointer transition-transform hover:-translate-y-0.5 border",
        paper.kind === "review" ? "border-[oklch(0.84_0.06_22)]" : "border-border",
      )}
    >
      <div className="relative h-[150px] bg-[oklch(0.975_0.008_78)] border-b border-border px-[13px] py-3 overflow-hidden">
        <div className="font-mono text-[8.5px] text-t3 tracking-[0.06em]">
          0625/31 · MAY 2020
        </div>
        <div
          className="flex flex-col gap-1.5 mt-[9px]"
          style={{ opacity: dim ? 0.45 : 1 }}
        >
          {paper.lines.map((w, i) => (
            <div
              key={i}
              className="h-[3px] rounded-sm bg-[oklch(0.87_0.01_78)]"
              style={{ width: `${w}%` }}
            />
          ))}
        </div>
        {paper.kind === "review" ? (
          <div className="absolute top-2.5 right-2.5 w-5 h-5 rounded-full bg-err text-accent-on text-[10px] flex items-center justify-center font-mono">
            !
          </div>
        ) : null}
        {paper.kind === "processing" ? (
          <div className="absolute inset-0 flex items-center justify-center">
            <div className="w-[34px] h-[34px] rounded-full border-[3px] border-[oklch(0.90_0.012_78)] border-t-accent animate-spin" />
          </div>
        ) : null}
      </div>
      <div className="px-[13px] py-3">
        <div className="flex items-center gap-2">
          <div className="text-[13.5px] font-medium flex-1">{paper.name}</div>
          <div
            className={cn(
              "text-[10.5px] rounded-full px-[9px] py-0.5",
              CHIP_TONE[paper.kind],
            )}
          >
            {paper.status}
          </div>
        </div>
        <div className="flex items-baseline gap-2 mt-[9px]">
          <div className={cn("font-mono text-[11.5px]", confTone)}>
            {paper.conf}
          </div>
          <div className="flex-1" />
          <div className="font-mono text-[15px]">{paper.score}</div>
        </div>
      </div>
    </div>
  )
}

export function Grading() {
  const navigate = useNavigate()
  const [tab, setTab] = useState<BatchTabId>("all")
  const papers = filterPapers(tab)

  const dash = `${((CIRC * autoGrade.progress).toFixed(1))} ${CIRC.toFixed(1)}`

  return (
    <div className="lm-screen flex flex-col gap-5">
      <div className="flex items-end gap-[18px] pb-[18px] border-b border-border flex-wrap gap-y-2.5">
        <div>
          <div className="font-mono text-[11px] tracking-[0.11em] uppercase text-t3">
            New batch · 0625/31 · May/June 2020
          </div>
          <div className="font-serif text-[34px] leading-[1.1] mt-1.5">
            Grading 24 papers
          </div>
        </div>
        <div className="flex-1" />
        <Button variant="secondary">Pause</Button>
        <Button variant="ink" onClick={() => navigate("/teacher/review")}>
          Open review queue →
        </Button>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-[340px_1fr] gap-6 items-start">
        {/* Left column */}
        <div className="flex flex-col gap-4">
          <div className="bg-surface border border-border rounded-[14px] px-5 py-[18px]">
            <div className="flex items-center gap-2">
              <div className="font-mono text-[10.5px] tracking-[0.1em] uppercase text-t3">
                Detected from page 1
              </div>
              <div className="flex-1" />
              <span className="w-1.5 h-1.5 rounded-full bg-ok" />
              <span className="font-mono text-[11px] text-t2">99% match</span>
            </div>
            <div className="grid grid-cols-2 gap-x-[14px] gap-y-4 mt-[18px]">
              {detected.map((d) => (
                <div key={d.k}>
                  <div className="font-mono text-[10px] tracking-[0.1em] uppercase text-t3">
                    {d.k}
                  </div>
                  <div className="font-mono text-[15px] mt-1">{d.v}</div>
                </div>
              ))}
            </div>
            <Button
              variant="secondary"
              className="w-full mt-5 bg-transparent justify-start text-[13px] py-[11px]"
            >
              <span className="flex-1 text-left">Use custom mark scheme</span>
              <span className="text-t3">→</span>
            </Button>
          </div>

          <div className="bg-surface border border-border rounded-[14px] p-5 flex gap-5 items-center">
            <svg
              viewBox="0 0 100 100"
              className="w-[92px] h-[92px] flex-none -rotate-90"
            >
              <circle
                cx="50"
                cy="50"
                r="42"
                fill="none"
                stroke="oklch(0.92 0.012 78)"
                strokeWidth="10"
              />
              <circle
                cx="50"
                cy="50"
                r="42"
                fill="none"
                stroke="var(--accent)"
                strokeWidth="10"
                strokeLinecap="round"
                strokeDasharray={dash}
              />
            </svg>
            <div className="flex-1">
              <div className="text-[15px] font-semibold">
                Auto-grading in progress
              </div>
              <div className="font-mono text-[11.5px] text-t2 mt-[5px]">
                {autoGrade.remaining}
              </div>
              <div className="flex gap-[22px] mt-[14px]">
                <div>
                  <div className="font-serif text-[26px] leading-none">
                    {autoGrade.confirmed}
                  </div>
                  <div className="font-mono text-[10px] text-t3 mt-[3px]">
                    AUTO-CONFIRMED
                  </div>
                </div>
                <div>
                  <div className="font-serif text-[26px] leading-none text-err">
                    {autoGrade.needReview}
                  </div>
                  <div className="font-mono text-[10px] text-t3 mt-[3px]">
                    NEED REVIEW
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div className="bg-surface border border-border rounded-[14px] px-5 py-[18px]">
            <div className="font-mono text-[10.5px] tracking-[0.1em] uppercase text-t3 mb-[14px]">
              Pipeline
            </div>
            {pipeline.map((p) => (
              <div key={p.label} className="flex items-center gap-3 py-[9px]">
                <span
                  className={cn(
                    "w-[19px] h-[19px] flex-none rounded-full border-[1.5px] flex items-center justify-center text-[10px] font-mono",
                    p.state === "done"
                      ? "bg-ok border-ok text-accent-on"
                      : p.state === "active"
                        ? "bg-transparent border-accent text-accent"
                        : "bg-transparent border-border text-accent",
                  )}
                >
                  {PIPE_MARK[p.state]}
                </span>
                <span
                  className={cn(
                    "flex-1 text-[13.5px]",
                    p.state === "idle" ? "text-t3" : "text-t1",
                  )}
                >
                  {p.label}
                </span>
                <span className="font-mono text-[12px] text-t2">{p.count}</span>
              </div>
            ))}
          </div>

          <div className="border border-dashed border-border rounded-[14px] p-[26px] text-center bg-[oklch(0.975_0.01_78)]">
            <div className="text-[14px] font-medium">Drop more scans</div>
            <div className="font-mono text-[11px] text-t3 mt-[7px]">
              PDF · JPG · PNG · or scan with phone
            </div>
          </div>
        </div>

        {/* Right column: tabs + papers */}
        <div className="flex flex-col gap-4">
          <div className="flex items-center gap-[14px] flex-wrap">
            <div className="flex gap-1 bg-[oklch(0.945_0.012_78)] p-1 rounded-[11px]">
              {batchTabs.map((t) => {
                const on = tab === t.id
                return (
                  <button
                    key={t.id}
                    onClick={() => setTab(t.id)}
                    className={cn(
                      "border-0 cursor-pointer text-[13px] px-[14px] py-2 rounded-lg",
                      on
                        ? "bg-surface text-t1 font-medium shadow-[0_1px_3px_oklch(0.2_0.02_60/.08)]"
                        : "bg-transparent text-t2 font-normal",
                    )}
                  >
                    {t.label}{" "}
                    <span
                      className={cn(
                        "font-mono text-[11.5px]",
                        on ? "text-accent" : "text-t3",
                      )}
                    >
                      {t.count}
                    </span>
                  </button>
                )
              })}
            </div>
            <div className="flex-1" />
            <div className="font-mono text-[11px] tracking-[0.08em] uppercase text-t3">
              Detected · MS 0625/31 v3
            </div>
            <Button variant="secondary" size="sm">
              Change
            </Button>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
            {papers.map((p) => (
              <PaperCard
                key={p.name}
                paper={p}
                onOpen={() => navigate("/teacher/review")}
              />
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

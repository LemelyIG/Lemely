import { useState } from "react"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { Avatar } from "../components/Avatar"
import {
  flagged,
  queue,
  reviewProgress,
  type MarkingPoint,
  type PointState,
} from "../data"

const POINT_STYLE: Record<
  PointState,
  { row: string; mark: string; glyph: string; award: string }
> = {
  ok: {
    row: "bg-ok-bg border-[oklch(0.86_0.05_152)]",
    mark: "bg-ok",
    glyph: "✓",
    award: "text-[oklch(0.36_0.09_152)]",
  },
  no: {
    row: "bg-err-bg border-[oklch(0.86_0.05_22)]",
    mark: "bg-err",
    glyph: "✕",
    award: "text-[oklch(0.40_0.10_22)]",
  },
  dep: {
    row: "bg-[oklch(0.965_0.008_78)] border-border",
    mark: "bg-[oklch(0.78_0.01_60)]",
    glyph: "-",
    award: "text-t2",
  },
}

function PointRow({ p }: { p: MarkingPoint }) {
  const st = POINT_STYLE[p.state]
  return (
    <div
      className={cn(
        "grid grid-cols-[26px_44px_1fr_50px] gap-3 items-start border rounded-[11px] px-[14px] py-[13px]",
        st.row,
      )}
    >
      <span
        className={cn(
          "w-5 h-5 rounded-[5px] text-accent-on flex items-center justify-center text-[11px]",
          st.mark,
        )}
      >
        {st.glyph}
      </span>
      <span className="font-mono text-[12px] text-t2">{p.code}</span>
      <span>
        <span className="block text-[13px] leading-[1.4]">{p.text}</span>
        {p.note ? (
          <span className="block font-serif italic text-[13.5px] text-t2 mt-1">
            {p.note}
          </span>
        ) : null}
      </span>
      <span className="text-right">
        <span className="block font-mono text-[11.5px] text-t2">{p.conf}</span>
        <span className={cn("block font-mono text-[13px] mt-1", st.award)}>
          {p.award}
        </span>
      </span>
    </div>
  )
}

export function Review() {
  const [qi, setQi] = useState(0)
  const [award, setAward] = useState<number | null>(null)

  const current = flagged[qi % flagged.length]

  const prev = () => {
    setQi((v) => (v + flagged.length - 1) % flagged.length)
    setAward(null)
  }
  const next = () => {
    setQi((v) => (v + 1) % flagged.length)
    setAward(null)
  }

  const [got, outOf] = current.marks.split("/")
  const awardOpts = [
    `${got}/${outOf}`,
    `${Number(got) + 1}/${outOf}`,
    `${outOf}/${outOf}`,
    "Skip",
  ]

  return (
    <div className="lm-screen flex flex-col gap-5">
      <div className="flex items-end gap-[18px] pb-[18px] border-b border-border flex-wrap gap-y-2.5">
        <div>
          <div className="flex items-center gap-2.5">
            <div className="font-serif text-[34px] leading-[1.1]">
              Review AI grading
            </div>
            <div className="bg-accent-subtle text-[oklch(0.44_0.10_68)] text-[11.5px] px-[11px] py-[3px] rounded-full">
              Live
            </div>
          </div>
          <div className="font-mono text-[11.5px] text-t2 mt-[7px]">
            12 answers · 0625/31 · May/June 2020
          </div>
        </div>
        <div className="flex-1" />
        <Button variant="secondary">Filter</Button>
        <Button variant="ink">Approve all (12)</Button>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-[1fr_1.05fr_262px] gap-5 items-start">
        {/* Answer panel */}
        <div className="bg-surface border border-border rounded-[14px] p-[18px]">
          <div className="flex items-center gap-3">
            <div className="w-[34px] h-[34px] rounded-[9px] bg-accent-subtle text-[oklch(0.44_0.10_68)] flex items-center justify-center text-[12px] font-semibold">
              {current.initials}
            </div>
            <div className="flex-1">
              <div className="text-[14px] font-medium">{current.name}</div>
              <div className="font-mono text-[11px] text-t2 mt-0.5">
                0625/31 · {current.q}
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

          <div className="border border-border rounded-[11px] p-[18px] mt-4 bg-[oklch(0.985_0.008_80)]">
            <div className="flex justify-between font-mono text-[9.5px] tracking-[0.08em] text-t3">
              <span>CAMBRIDGE IGCSE PHYSICS · 0625/31</span>
              <span>{current.page}</span>
            </div>
            <div className="text-[13.5px] leading-[1.55] mt-[14px] text-pretty">
              <span className="font-semibold">{current.qLabel}</span>{" "}
              {current.prompt}
            </div>
            <div className="font-serif italic text-[19px] leading-[1.9] text-[oklch(0.42_0.09_255)] mt-[18px]">
              {current.working.map((w, i) => (
                <div key={i}>
                  <span
                    className={cn(
                      "px-[3px] rounded-[3px]",
                      w.flagged ? "bg-[oklch(0.92_0.055_22)]" : "bg-transparent",
                    )}
                  >
                    {w.t}
                  </span>
                </div>
              ))}
            </div>
            <div className="border-t border-dashed border-border mt-[18px] pt-3 flex justify-between font-mono text-[11px] text-t3">
              <span>scanned · 09:14</span>
              <span className="text-err">✕ {current.marks}</span>
            </div>
          </div>

          <div className="flex gap-[9px] mt-4 justify-center">
            <Button variant="secondary" size="sm" className="text-[12.5px] px-4 py-[9px]">
              Re-scan
            </Button>
            <Button variant="secondary" size="sm" className="text-[12.5px] px-4 py-[9px]">
              Edit transcript
            </Button>
          </div>
        </div>

        {/* Marking points + award */}
        <div className="flex flex-col gap-4">
          <div className="flex items-center gap-[14px] pb-[14px] border-b border-border">
            <div className="font-mono text-[11px] tracking-[0.08em] uppercase text-t3 leading-[1.5]">
              {current.q} · mark scheme
              <br />
              alignment
            </div>
            <div className="flex-1" />
            <div className="text-[11.5px] text-t2 leading-[1.3] text-right">
              AI
              <br />
              confidence
            </div>
            <div className="font-mono text-[14px] text-err">{current.conf}</div>
            <div className="w-20 h-1.5 rounded-[3px] bg-[oklch(0.92_0.012_78)]">
              <div
                className="h-full rounded-[3px] bg-err"
                style={{ width: `${current.confW}%` }}
              />
            </div>
          </div>

          <div className="flex items-baseline gap-3">
            <div className="font-serif text-[24px]">Marking points</div>
            <div className="flex-1" />
            <div className="font-mono text-[11.5px] text-t2">{current.total}</div>
          </div>

          <div className="flex flex-col gap-[9px]">
            {current.points.map((p, i) => (
              <PointRow key={i} p={p} />
            ))}
          </div>

          <div className="border border-border rounded-[12px] px-[18px] py-4 bg-surface">
            <div className="flex items-center gap-2.5">
              <span className="w-[22px] h-[22px] rounded-md bg-accent-subtle flex items-center justify-center">
                <span className="w-2 h-2 bg-accent rotate-45" />
              </span>
              <div>
                <div className="text-[13.5px] font-medium">
                  Why Lemely flagged this
                </div>
                <div className="font-mono text-[10.5px] text-t3 mt-0.5">
                  CONFIDENCE BELOW 0.90
                </div>
              </div>
            </div>
            <div className="text-[13px] leading-[1.55] text-t2 mt-3 text-pretty">
              {current.why}
            </div>
          </div>

          <div className="flex items-center gap-2.5 flex-wrap pt-1.5">
            <div className="text-[13px] text-t2">Award:</div>
            {awardOpts.map((label, i) => {
              const on = award === null ? i === 0 : award === i
              return (
                <button
                  key={label}
                  onClick={() => setAward(i)}
                  className={cn(
                    "border font-mono text-[13px] px-4 py-[9px] rounded-[9px] cursor-pointer",
                    on
                      ? "border-ink bg-ink text-accent-on"
                      : "border-border bg-surface text-t1",
                  )}
                >
                  {label}
                </button>
              )
            })}
            <div className="flex-1" />
            <Button variant="ink" size="lg" onClick={next}>
              ✓ Confirm &amp; next
            </Button>
          </div>
        </div>

        {/* Queue */}
        <div className="bg-surface border border-border rounded-[14px] overflow-hidden">
          <div className="px-4 pt-[15px] pb-3 font-mono text-[10.5px] tracking-[0.1em] uppercase text-t3">
            Review queue · 12
          </div>
          {queue.map((q) => {
            const on = current.name === q.name
            return (
              <button
                key={q.name}
                onClick={() => {
                  setQi(q.target)
                  setAward(null)
                }}
                className={cn(
                  "grid grid-cols-[28px_1fr_auto] gap-2.5 items-center w-full text-left border-0 border-t border-border cursor-pointer px-4 py-3",
                  on ? "bg-surface" : "bg-transparent hover:bg-[oklch(0.975_0.01_78)]",
                )}
              >
                <Avatar
                  initials={q.initials}
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
                    {q.name}
                  </span>
                  <span className="block font-mono text-[10.5px] text-t3 mt-0.5">
                    {q.meta}
                  </span>
                </span>
                <span className="text-right">
                  <span
                    className={cn(
                      "block font-mono text-[11.5px]",
                      parseInt(q.conf) < 70 ? "text-err" : "text-t2",
                    )}
                  >
                    {q.conf}
                  </span>
                  <span className="block font-mono text-[10.5px] text-t3 mt-0.5">
                    {q.marks}
                  </span>
                </span>
              </button>
            )
          })}
          <div className="border-t border-border p-4">
            <div className="flex justify-between text-[12px] text-t2">
              <span>Auto-graded</span>
              <span className="font-mono">{reviewProgress.autoGraded}</span>
            </div>
            <div className="h-1.5 rounded-[3px] bg-[oklch(0.92_0.012_78)] mt-[9px]">
              <div
                className="h-full rounded-[3px] bg-ok"
                style={{ width: `${reviewProgress.percent}%` }}
              />
            </div>
            <div className="font-mono text-[10.5px] text-t3 mt-2">
              {reviewProgress.note}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

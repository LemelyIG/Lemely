import { useEffect, useRef, useState } from "react"
import { useNavigate } from "react-router-dom"
import { Check } from "@phosphor-icons/react"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import {
  detected,
  progressSteps,
  reassure,
  readChips,
  scanMeta,
} from "../data"

/*
 * Correct a paper (isCorrect). The primary run button advances a marking
 * pipeline: each step completes on a timer, and when the pipeline finishes it
 * navigates to the Paper 1 result (mirrors the mock's runPipeline). Local
 * useState drives the progress panel; timers are cleaned up on unmount.
 */
export function CorrectPaper() {
  const navigate = useNavigate()
  const [running, setRunning] = useState(false)
  // done = number of completed steps; -1 sentinel means "never run" (all shown done).
  const [done, setDone] = useState(-1)
  const timers = useRef<number[]>([])

  useEffect(
    () => () => {
      timers.current.forEach(clearTimeout)
    },
    [],
  )

  const runPipeline = () => {
    if (running) return
    setRunning(true)
    setDone(0)
    progressSteps.forEach((_, i) => {
      const t = window.setTimeout(() => setDone(i + 1), 400 + (i + 1) * 620)
      timers.current.push(t)
    })
    const finish = window.setTimeout(
      () => navigate("/student/result?tab=p1"),
      400 + (progressSteps.length + 1) * 620,
    )
    timers.current.push(finish)
  }

  // When idle before any run, every step reads as complete (the mock shows the
  // "Marked in 41 seconds" resting state).
  const completed = done === -1 ? progressSteps.length : done

  return (
    <div className="lm-screen flex flex-col gap-[22px]">
      <div className="flex items-end gap-5 flex-wrap">
        <div>
          <div className="font-serif text-[36px] leading-[1.1]">
            Correct a paper
          </div>
          <div className="text-[14px] text-t2 mt-[7px] max-w-[60ch] text-pretty">
            Scan or drop the paper. Lemely reads page one, identifies the exam,
            fetches the official mark scheme, and marks it.
          </div>
        </div>
        <div className="flex-1" />
        <Button variant="accent" size="lg" onClick={runPipeline} disabled={running}>
          {running ? "Marking..." : "Mark this paper"}
        </Button>
      </div>

      <div className="lm-cols grid grid-cols-[1.5fr_1fr] gap-5 items-start max-[1180px]:grid-cols-1">
        <div className="flex flex-col gap-5">
          <div className="bg-surface border border-dashed border-border rounded-lg p-[22px] flex gap-5 items-center">
            <div
              className="w-24 h-[126px] flex-none border border-border rounded-lg flex items-end justify-center p-2"
              style={{
                background:
                  "repeating-linear-gradient(135deg, oklch(0.955 0.008 40) 0 7px, oklch(0.975 0.006 40) 7px 14px)",
              }}
            >
              <span className="font-mono text-[9px] text-t3 text-center">
                {scanMeta.thumbLabel}
              </span>
            </div>
            <div className="flex-1">
              <div className="font-mono text-[12px] text-t2">
                {scanMeta.filename}
              </div>
              <div className="text-[13px] mt-2 leading-[1.5] text-t2 text-pretty">
                {scanMeta.detail}
              </div>
              <div className="flex flex-wrap gap-x-[26px] gap-y-2.5 mt-4">
                {detected.map((d) => (
                  <div key={d.k}>
                    <div className="text-[10.5px] tracking-[0.08em] uppercase text-t3">
                      {d.k}
                    </div>
                    <div className="font-mono text-[13.5px] mt-[3px] text-t1">
                      {d.v}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          <Card className="overflow-hidden">
            <div className="px-5 pt-4 pb-3 flex items-baseline gap-2.5">
              <div className="text-[15px] font-semibold">
                What we read from the paper
              </div>
              <div className="text-[12px] text-t2">
                Change anything before marking - you always have the last word
              </div>
            </div>
            <div className="px-5 pt-1.5 pb-5">
              <div className="grid grid-cols-10 gap-[7px]">
                {readChips.map((c) => (
                  <div
                    key={c.id}
                    className="border border-border bg-surface-2 rounded-lg px-1 py-1.5 text-center cursor-text transition-colors hover:border-accent"
                  >
                    <div className="text-[9.5px] text-t3">{c.id}</div>
                    <div className="text-[14px] font-medium leading-[1.4]">
                      {c.ans}
                    </div>
                  </div>
                ))}
              </div>
              <div className="flex items-center gap-2.5 mt-4 px-[14px] py-3 rounded-[10px] bg-[oklch(0.96_0.02_150)] text-[12.5px] text-[oklch(0.34_0.07_150)]">
                <span className="w-4 h-4 flex-none rounded-full border-[1.5px] border-ok flex items-center justify-center">
                  <Check size={9} weight="bold" />
                </span>
                <span>
                  All forty answers came through clearly. Nothing needs a second
                  look.
                </span>
              </div>
            </div>
          </Card>
        </div>

        <div className="flex flex-col gap-5">
          <Card className="p-5">
            <div className="flex items-center gap-[9px] mb-4">
              <span
                className={`w-[7px] h-[7px] rounded-full animate-[lm-pulse_1.6s_infinite] ${running ? "bg-accent" : "bg-ok"}`}
              />
              <div className="text-[15px] font-semibold">
                {running ? "Marking now" : "Marked in 41 seconds"}
              </div>
            </div>
            <div className="flex flex-col min-h-[214px]">
              {progressSteps.map((p, i) => {
                const isDone = i < completed
                const active = running && i === completed
                return (
                  <div
                    key={p.title}
                    className="grid grid-cols-[20px_1fr] gap-3 items-start py-[11px] border-t border-border"
                    style={{ opacity: isDone ? 1 : active ? 0.85 : 0.42 }}
                  >
                    <span
                      className={`w-[18px] h-[18px] rounded-full border-[1.5px] flex items-center justify-center mt-px ${isDone ? "border-ok text-ok" : "border-t3 text-t3"}`}
                    >
                      {isDone ? (
                        <Check size={9} weight="bold" />
                      ) : (
                        <span className="text-[9px]">·</span>
                      )}
                    </span>
                    <span>
                      <span className="block text-[13px] leading-[1.35]">
                        {p.title}
                      </span>
                      <span className="block text-[12px] text-t2 leading-[1.4] mt-[3px]">
                        {isDone ? p.detail : active ? "working..." : "waiting"}
                      </span>
                    </span>
                  </div>
                )
              })}
            </div>
          </Card>

          <Card className="p-5">
            <div className="text-[15px] font-semibold mb-[5px]">
              How this gets marked
            </div>
            <div className="text-[12.5px] text-t2 mb-[15px]">
              Worth knowing before you trust the number
            </div>
            <div className="flex flex-col gap-[13px]">
              {reassure.map((r, i) => (
                <div key={i} className="flex gap-[11px] items-start">
                  <span className="w-[5px] h-[5px] rounded-full bg-accent mt-[7px] flex-none" />
                  <span className="text-[12.5px] leading-[1.5] text-t2 text-pretty">
                    {r.t}
                  </span>
                </div>
              ))}
            </div>
          </Card>
        </div>
      </div>
    </div>
  )
}

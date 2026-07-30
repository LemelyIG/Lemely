import { useState } from "react"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import {
  difficulties,
  difficultyNote,
  predictedAvg,
  defaultTopics,
  pools,
  defaultPools,
  preview,
  estMinutes,
  type Difficulty,
  type PreviewQuestion,
} from "../data"

function PreviewCard({ q }: { q: PreviewQuestion }) {
  const isPast = q.src === "past"
  return (
    <div className="bg-surface border border-border rounded-[12px] px-[18px] py-4">
      <div className="flex items-center gap-2.5">
        <span className="font-mono text-[12px] text-t2">{q.n}</span>
        <span
          className={cn(
            "border font-mono text-[11px] px-2.5 py-[3px] rounded-full",
            isPast
              ? "border-border bg-[oklch(0.97_0.008_78)] text-t2"
              : "border-[oklch(0.88_0.06_68)] bg-accent-subtle text-[oklch(0.42_0.10_68)]",
          )}
        >
          {q.source}
        </span>
        <span className="flex-1" />
        <span
          className={cn(
            "w-[22px] h-[22px] rounded-full flex items-center justify-center font-serif text-[13px]",
            q.grade === "A*"
              ? "bg-ok-bg text-[oklch(0.34_0.09_152)]"
              : q.grade === "A"
                ? "bg-accent-subtle text-[oklch(0.42_0.10_68)]"
                : "bg-[oklch(0.93_0.01_78)] text-t2",
          )}
        >
          {q.grade}
        </span>
        <span className="font-mono text-[11.5px] text-t3">[{q.marks}]</span>
      </div>
      <div className="font-serif italic text-[17px] leading-[1.45] mt-3 text-pretty">
        {q.text}
      </div>
    </div>
  )
}

export function Quizzes() {
  const [difficulty, setDifficulty] = useState<Difficulty>("A")
  const [qLen, setQLen] = useState(12)
  const [topics, setTopics] = useState<Record<string, boolean>>(defaultTopics)
  const [selectedPools, setSelectedPools] =
    useState<Record<string, boolean>>(defaultPools)

  const toggleTopic = (t: string) =>
    setTopics((s) => ({ ...s, [t]: !s[t] }))
  const togglePool = (p: string) =>
    setSelectedPools((s) => ({ ...s, [p]: !s[p] }))

  const est = estMinutes(qLen)

  return (
    <div className="lm-screen flex flex-col gap-0">
      <div className="flex items-end gap-[18px] pb-[18px] border-b border-border flex-wrap gap-y-2.5">
        <div>
          <div className="font-mono text-[11px] tracking-[0.11em] uppercase text-t3">
            New AI quiz · draft
          </div>
          <div className="font-serif text-[34px] leading-[1.1] mt-1.5">
            Build a quiz
          </div>
        </div>
        <div className="flex-1" />
        <Button variant="secondary">Save draft</Button>
        <Button variant="ink">
          <span className="w-2 h-2 bg-accent rotate-45" />
          Generate · {qLen} questions
        </Button>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-[1fr_1.18fr] items-stretch">
        {/* Form column */}
        <div className="py-7 pr-0 xl:pr-[34px] pb-[34px] flex flex-col gap-[26px]">
          <div>
            <div className="font-mono text-[10.5px] tracking-[0.1em] uppercase text-t3 mb-2.5">
              Title
            </div>
            <div className="border border-border bg-surface rounded-[11px] px-4 py-[14px] text-[15px]">
              Y11 · Thermal physics catch-up
            </div>
          </div>

          <div>
            <div className="font-mono text-[10.5px] tracking-[0.1em] uppercase text-t3 mb-2.5">
              Target difficulty
            </div>
            <div className="flex gap-1 bg-[oklch(0.945_0.012_78)] p-[5px] rounded-[12px]">
              {difficulties.map((d) => {
                const on = difficulty === d
                return (
                  <button
                    key={d}
                    onClick={() => setDifficulty(d)}
                    className={cn(
                      "flex-1 border cursor-pointer font-serif text-[21px] py-[11px] rounded-[9px]",
                      on
                        ? "border-border bg-surface text-t1 shadow-[0_1px_3px_oklch(0.2_0.02_60/.08)]"
                        : "border-transparent bg-transparent text-t2",
                    )}
                  >
                    {d}
                  </button>
                )
              })}
            </div>
            <div className="font-mono text-[12px] text-t2 leading-[1.6] mt-3">
              {difficultyNote}
            </div>
          </div>

          <div>
            <div className="font-mono text-[10.5px] tracking-[0.1em] uppercase text-t3 mb-2.5">
              Topics to include
            </div>
            <div className="flex flex-wrap gap-[9px]">
              {Object.keys(topics).map((t) => {
                const on = topics[t]
                return (
                  <button
                    key={t}
                    onClick={() => toggleTopic(t)}
                    className={cn(
                      "flex items-center gap-[7px] border text-[13px] px-[15px] py-2 rounded-full cursor-pointer",
                      on
                        ? "border-[oklch(0.86_0.07_68)] bg-accent-subtle text-[oklch(0.40_0.10_68)]"
                        : "border-border bg-surface text-t2",
                    )}
                  >
                    {on ? <span className="text-[11px]">✓</span> : null}
                    {t}
                  </button>
                )
              })}
            </div>
          </div>

          <div>
            <div className="font-mono text-[10.5px] tracking-[0.1em] uppercase text-t3 mb-2.5">
              Question pool
            </div>
            <div className="flex flex-col gap-2.5">
              {pools.map((p) => {
                const on = selectedPools[p.key]
                return (
                  <button
                    key={p.key}
                    onClick={() => togglePool(p.key)}
                    className={cn(
                      "flex items-center gap-[14px] w-full text-left border bg-surface rounded-[11px] px-4 py-[14px] cursor-pointer hover:bg-[oklch(0.985_0.008_78)]",
                      on ? "border-[oklch(0.84_0.012_75)]" : "border-border",
                    )}
                  >
                    <span
                      className={cn(
                        "w-5 h-5 flex-none rounded-[5px] border-[1.5px] text-accent-on flex items-center justify-center text-[11px]",
                        on
                          ? "bg-ink border-ink"
                          : "bg-transparent border-border",
                      )}
                    >
                      {on ? "✓" : ""}
                    </span>
                    <span>
                      <span className="block text-[14px] text-t1">
                        {p.label}
                      </span>
                      <span className="block font-mono text-[11.5px] text-t2 mt-[3px]">
                        {p.detail}
                      </span>
                    </span>
                  </button>
                )
              })}
            </div>
          </div>

          <div>
            <div className="font-mono text-[10.5px] tracking-[0.1em] uppercase text-t3 mb-3">
              Quiz length · {qLen} questions
            </div>
            <input
              type="range"
              min={5}
              max={30}
              value={qLen}
              onChange={(e) => setQLen(Number(e.target.value))}
              className="w-full h-5 accent-ink"
              aria-label="Quiz length"
            />
            <div className="flex justify-between font-mono text-[11px] text-t3 mt-1.5">
              <span>5</span>
              <span>{est}</span>
              <span>30</span>
            </div>
          </div>
        </div>

        {/* Preview column */}
        <div className="bg-[oklch(0.955_0.014_78)] border-l border-border rounded-r-[14px] px-[30px] py-7 flex flex-col gap-[18px]">
          <div className="flex items-start gap-3 flex-wrap gap-y-2">
            <div className="flex-1 min-w-[200px]">
              <div className="font-mono text-[10.5px] tracking-[0.1em] uppercase text-t3">
                Preview · 4 of {qLen} shown
              </div>
              <div className="font-serif text-[26px] mt-[7px]">
                Y11 · Thermal physics catch-up
              </div>
            </div>
            <div className="bg-accent text-accent-on text-[12px] px-3 py-[5px] rounded-full whitespace-nowrap">
              Grade {difficulty} target
            </div>
            <div className="border border-border bg-surface font-mono text-[11.5px] px-[11px] py-[5px] rounded-full whitespace-nowrap">
              {est}
            </div>
          </div>

          <div className="flex flex-col gap-3">
            {preview.map((q) => (
              <PreviewCard key={q.n} q={q} />
            ))}
          </div>

          <button className="border border-dashed border-border bg-transparent text-[13px] p-[14px] rounded-[12px] cursor-pointer text-t2 hover:bg-[oklch(0.975_0.012_78)]">
            + Show all {qLen} questions
          </button>

          <div className="bg-surface border border-border rounded-[12px] p-[18px] flex items-center gap-4 mt-auto flex-wrap gap-y-3">
            <span className="w-8 h-8 flex-none rounded-[9px] bg-accent-subtle flex items-center justify-center">
              <span className="w-[11px] h-[11px] bg-accent rotate-45" />
            </span>
            <div className="flex-1 min-w-[220px]">
              <div className="text-[14px] font-medium">
                Predicted class average
              </div>
              <div className="flex gap-[18px] mt-[7px] font-mono text-[11.5px] text-t2 flex-wrap">
                <span className="text-[14px] text-t1">
                  {predictedAvg[difficulty]}
                </span>
                <span>4 likely to fall under 50%</span>
                <span>3 likely above 90%</span>
              </div>
            </div>
            <Button variant="secondary" size="sm" className="text-[12.5px] whitespace-nowrap">
              Adjust difficulty
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}

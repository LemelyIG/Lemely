/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 — design import, part B. */
import { Check, CircleHalf, XCircle, type Icon } from "@phosphor-icons/react"
import { useState, type CSSProperties } from "react"
import { Card } from "@/components/ui/card"
import { Chip } from "@/components/ui/chip"
import { MarkDisplay } from "@/components/ui/mark-display"
import { PaperIdentity } from "@/components/ui/paper-identity"
import { cn } from "@/lib/utils"
import { openedQuestion, type LineTone, type MarkState } from "./data"

/*
 * `OpenedQuestion` — design-import-spec.md, "Components to build". The dark
 * trust band's visual: a `Card` the reader drives. A picker of the three
 * fixture questions replays the whole reading below it (mark pops, the
 * handwritten working slides in, the scheme lines rise on a stagger) when a
 * different one is selected.
 *
 * The replay is the entire mechanism: `.spec__body` is keyed on the
 * selected question's id, so React unmounts and remounts it on every pick.
 * `marketing.css`'s `.spec__body`/`.spec__mark`/`.spec__work`/`.line`/
 * `.spec__foot` animations all run on mount with `animation-fill-mode:
 * both`, so a fresh mount is a fresh play of the same reveal the page's own
 * scroll-in `.reveal` mechanism does not need to drive here — this replay is
 * click-triggered, not scroll-triggered, matching the spec's "selecting one
 * replays the whole body."
 */

const lineIcon: Record<LineTone, Icon> = {
  ok: Check,
  warn: CircleHalf,
  err: XCircle,
}

const qpickState: Record<MarkState, "correct" | "partial" | "wrong"> = {
  correct: "correct",
  partial: "partial",
  wrong: "wrong",
}

export function OpenedQuestion() {
  const [selectedId, setSelectedId] = useState(openedQuestion.defaultId)
  const selected =
    openedQuestion.questions.find((q) => q.id === selectedId) ?? openedQuestion.questions[0]

  return (
    <Card className="spec">
      <div className="spec__head">
        <PaperIdentity
          code={openedQuestion.paper.code}
          session={openedQuestion.paper.session}
          paperLabel={openedQuestion.paper.paperLabel}
        />
        <Chip tone="neutral">Example</Chip>
      </div>

      <div className="spec__picker" role="group" aria-label="Open a question">
        <span className="spec__picker-label text-label-sm" aria-hidden="true">
          Open a question
        </span>
        {openedQuestion.questions.map((q) => (
          <button
            key={q.id}
            type="button"
            className="qpick pointer-coarse:min-h-11"
            aria-pressed={q.id === selectedId}
            onClick={() => setSelectedId(q.id)}
          >
            <span className="qpick__mark text-data-sm" data-state={qpickState[q.state]}>
              {q.awarded}/{q.available}
            </span>
            <span className="text-label-sm">Question {q.label}</span>
          </button>
        ))}
      </div>

      <div className="spec__body" key={selected.id}>
        <div className="spec__q">
          <h3 className="text-display-sm text-ink">{selected.title}</h3>
          <span className="spec__mark">
            <MarkDisplay awarded={selected.awarded} available={selected.available} size="inline" />
          </span>
        </div>
        <p className="spec__work">{selected.work}</p>
        <ul className="lines">
          {selected.lines.map((line, i) => {
            const Glyph = lineIcon[line.tone]
            return (
              <li className="line" data-tone={line.tone} key={line.code} style={{ "--i": i } as CSSProperties}>
                <span className="line__icon">
                  <Glyph size={16} weight="bold" aria-hidden />
                </span>
                <span className="line__code text-data-sm">{line.code}</span>
                <span className="line__text text-body-sm">{line.text}</span>
              </li>
            )
          })}
        </ul>
        <div className="spec__foot">
          <Chip tone={selected.confidenceTier === "confident" ? "ok" : "warn"}>
            {selected.confidence}
          </Chip>
          <span className={cn("spec__hand text-hand")} aria-hidden="true">
            {openedQuestion.hand}
          </span>
        </div>
      </div>
    </Card>
  )
}

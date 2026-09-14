/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 — design import, part B. */
import { useEffect, useRef, useState, type CSSProperties } from "react"
import { FileText } from "@phosphor-icons/react"
import { Badge } from "@/components/ui/badge"
import { Chip } from "@/components/ui/chip"
import { QuestionRow } from "@/components/ui/question-row"
import { Stepper } from "@/components/ui/stepper"
import { prefersReducedMotion } from "@/lib/celebration"
import { lineIcon } from "./OpenedQuestion"
import { openedQuestion, scanSequence } from "./data"

/*
 * `ScanSequence` — design-import-spec.md, "Components to build". A
 * scroll-driven three-step stepper (Scan / Mark / Practise) inside `.seq`.
 * Three invisible sentinels, stacked across the card's own rendered height
 * (`.seq__mark`, `marketing.css`), are watched by one IntersectionObserver
 * whose `rootMargin` ("-45% 0px -45% 0px") shrinks its effective root to a
 * thin band at the vertical centre of the viewport: whichever sentinel
 * crosses that band as the page scrolls sets the active step, so the card
 * advances Scan → Mark → Practise purely from the reader scrolling past it.
 * No scroll listener anywhere.
 *
 * `Stepper` (`ui/stepper`) is also a real control here: clicking a step
 * pins it — a `pinnedRef` flag the observer's callback checks and, once
 * set, ignores every further report, so a reader who jumps ahead by hand
 * is never dragged back by the next scroll tick. Reduced motion skips the
 * whole mechanism and mounts straight on the final step.
 *
 * The failsafe is armed by a SECOND observer, on `.seq` itself, with no
 * `rootMargin` narrowing — it fires as soon as the card is anywhere on
 * screen, well before the `-45%` band the sentinels need. Only once that
 * happens does the 2600ms clock start, so it measures "visible but the
 * sentinel band never reported" (a stalled layout, a test environment's
 * partial DOM), not "not yet scrolled to" — which is what a clock started
 * at mount was measuring, and why review flagged it (I-1): a reader
 * scrolling at ordinary speed takes longer than 2600ms just to REACH the
 * card, so the old timer fired before the mechanism it was guarding ever
 * had a chance to run, freezing the stepper on step 1 for every reader.
 * When the failsafe does fire, it settles the step at the final one rather
 * than disconnecting the sentinel observer — disconnecting only stops the
 * stepper from ever correcting itself again, which is the same defect
 * class as the reveal failsafe fixed in `ad2b206d`: a recovery path that
 * disables the feature instead of completing it.
 */

const SENTINEL_COUNT = 3
const FAILSAFE_MS = 2600

export function ScanSequence() {
  const [reduced] = useState(prefersReducedMotion)
  const [step, setStep] = useState(reduced ? 3 : 1)
  const pinnedRef = useRef(false)
  const observedRef = useRef(false)
  const sentinelRefs = useRef<(HTMLDivElement | null)[]>([])
  const containerRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (reduced) return
    if (typeof IntersectionObserver === "undefined") return

    const nodes = sentinelRefs.current.filter((n): n is HTMLDivElement => n !== null)
    if (nodes.length === 0) return

    const observer = new IntersectionObserver(
      (entries) => {
        if (pinnedRef.current) return
        for (const entry of entries) {
          if (!entry.isIntersecting) continue
          const index = nodes.indexOf(entry.target as HTMLDivElement)
          if (index === -1) continue
          observedRef.current = true
          setStep(index + 1)
        }
      },
      { rootMargin: "-45% 0px -45% 0px" },
    )
    nodes.forEach((node) => observer.observe(node))

    let failsafe: number | undefined
    const visibilityObserver = new IntersectionObserver((entries) => {
      if (!entries.some((entry) => entry.isIntersecting)) return
      visibilityObserver.disconnect()
      failsafe = window.setTimeout(() => {
        if (!pinnedRef.current && !observedRef.current) setStep(SENTINEL_COUNT)
      }, FAILSAFE_MS)
    })
    if (containerRef.current) visibilityObserver.observe(containerRef.current)

    return () => {
      observer.disconnect()
      visibilityObserver.disconnect()
      if (failsafe !== undefined) window.clearTimeout(failsafe)
    }
  }, [reduced])

  function handleSelect(id: number) {
    pinnedRef.current = true
    setStep(id)
  }

  return (
    <div className="seq" ref={containerRef}>
      {!reduced &&
        Array.from({ length: SENTINEL_COUNT }, (_, i) => (
          <div
            key={i}
            ref={(node) => {
              sentinelRefs.current[i] = node
            }}
            className="seq__mark"
            style={{ top: `${(i * 100) / SENTINEL_COUNT}%` }}
            aria-hidden="true"
          />
        ))}

      <Stepper
        steps={scanSequence.steps}
        current={step}
        onSelect={handleSelect}
        label="Scan, mark and practise"
      />

      <div className="seq__panel" key={step}>
        {step === 1 && (
          <div className="seq__scan">
            <div className="seq__row">
              <FileText size={18} weight="regular" aria-hidden />
              <span className="text-data-sm">{scanSequence.scan.fileName}</span>
              <Chip tone="info">{scanSequence.scan.chip}</Chip>
            </div>
            <dl className="seq__facts">
              {scanSequence.scan.facts.map((fact, i) => (
                <div className="fact" key={fact.term} style={{ "--i": i } as CSSProperties}>
                  <dt className="text-eyebrow">{fact.term}</dt>
                  <dd className="text-data-md">{fact.detail}</dd>
                </div>
              ))}
            </dl>
            <p className="seq__note text-body-sm">{scanSequence.scan.note}</p>
          </div>
        )}

        {step === 2 && (
          <div className="seq__marks">
            {openedQuestion.questions.map((q, i) => (
              <div className="seq__mrow" key={q.id} style={{ "--i": i } as CSSProperties}>
                <QuestionRow
                  number={q.label}
                  awarded={q.awarded}
                  available={q.available}
                  state={q.state}
                  topic={q.title}
                  confidence={q.confidenceTier}
                >
                  {/*
                    The row's own note promises "Every row opens onto the
                    scheme line it came from", and `QuestionRow` renders its
                    detail only when it HAS children — so without these the
                    caret toggles, rotates, and reveals nothing. The imported
                    design passes the same lines here; the port dropped the
                    children argument along with `topic`.
                  */}
                  <ul className="lines">
                    {q.lines.map((line) => {
                      const Glyph = lineIcon[line.tone]
                      return (
                        <li key={line.code} className="line" data-tone={line.tone}>
                          {/* `.line` is a three-column grid (icon / code / text,
                              marketing.css) — the icon cell is not optional, or
                              the code and text land in the wrong columns. Same
                              markup as OpenedQuestion's lines, deliberately. */}
                          <span className="line__icon">
                            <Glyph size={16} weight="bold" aria-hidden />
                          </span>
                          <span className="line__code text-data-sm">{line.code}</span>
                          <span className="line__text text-body-sm">{line.text}</span>
                        </li>
                      )
                    })}
                  </ul>
                </QuestionRow>
              </div>
            ))}
            <p className="seq__note text-body-sm">{scanSequence.mark.note}</p>
          </div>
        )}

        {step === 3 && (
          <div className="seq__practise">
            <div className="seq__row seq__row--flourish">
              <span className="flourish" aria-hidden="true" />
              <Badge tone="lilac">{scanSequence.practise.badge}</Badge>
            </div>
            <p className="text-body-md">{scanSequence.practise.line}</p>
            <ol className="seq__list">
              {scanSequence.practise.shapes.map((shape, i) => (
                <li key={shape} style={{ "--i": i } as CSSProperties}>
                  {shape}
                </li>
              ))}
            </ol>
            <p className="seq__note text-body-sm">{scanSequence.practise.note}</p>
          </div>
        )}
      </div>
    </div>
  )
}

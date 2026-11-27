/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react"
import { Link } from "react-router-dom"
import { Flag, TextAlignLeft } from "@phosphor-icons/react"
import { useCan, useDeniedReason } from "@/components/acting/acting-state"
import { KeyRing } from "@/components/redesign"
import { Textarea } from "@/components/ui/textarea"
import { relativeTime } from "@/lib/utils"
import type { AnswerView } from "./answerView"
import { MarkControls } from "./MarkControls"
import { canSave, notePlaceholder, primaryActionLabel, totalOf, type MarkState } from "./markModel"
import { ringLabel, ringText, ringTone, ringValue } from "./reviewQueueModel"
import "./review.css"
import { pageFrame, type AnswerImages } from "./useAnswerImages"

export type { AnswerImages } from "./useAnswerImages"

export interface AnswerNav {
  pos: number
  total: number
  onPrev: () => void
  onNext: () => void
}

export interface AnswerMarking {
  state: MarkState
  onChange: (s: MarkState) => void
  note: string
  onNote: (s: string) => void
  /** Accept or Save, at the current total. */
  onAccept: () => void
  /** Integrity flags only. */
  onDismiss: (note: string) => void
}

export interface AnswerPanelProps {
  view: AnswerView
  images: AnswerImages
  nav?: AnswerNav
  /** Phone only. */
  onBack?: () => void
  /** Null is read-only: a closed item, or L8. */
  marking: AnswerMarking | null
  showShortcuts?: boolean
}

const ICON_BACK = <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M11 4 6 9l5 5" /></svg>
const ICON_NEXT = <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="m7 4 5 5-5 5" /></svg>

const FOCUS = "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
const NAV_BTN = `grid size-11 place-items-center rounded-chip bg-primary-container text-primary disabled:opacity-35 ${FOCUS}`
const LABEL = "font-mono text-xs font-semibold uppercase tracking-[0.08em] text-on-surface-variant"
const FRAME = "m-0 grid gap-1.5 rounded-2xl bg-surface-container-lowest p-3.5 shadow-[inset_0_0_0_1px_var(--color-outline)]"

export function AnswerPanel({ view, images, nav, onBack, marking, showShortcuts }: AnswerPanelProps) {
  const [mode, setMode] = useState<"crop" | "page">("crop")
  const [dismissNote, setDismissNote] = useState("")
  const uid = useId()
  // Read-only for a role without `mark`: every control below is inert, and the one reason sits by the actions.
  const canMark = useCan("mark")
  const markDenied = useDeniedReason("mark")
  const tabRefs = useRef<Record<"crop" | "page", HTMLButtonElement | null>>({ crop: null, page: null })
  const pick = (m: "crop" | "page") => { setMode(m); if (m === "page") images.requestPage() }
  const onTabKey = (e: KeyboardEvent<HTMLButtonElement>) => {
    const to = e.key === "ArrowRight" || e.key === "ArrowLeft" ? (mode === "crop" ? "page" : "crop") : e.key === "Home" ? "crop" : e.key === "End" ? "page" : null
    if (!to) return
    e.preventDefault()
    pick(to)
    tabRefs.current[to]?.focus()
  }
  const total = marking ? totalOf(view.points, marking.state, view.maximumMarks) : (view.lemelyMarks ?? 0)
  const changed = view.lemelyMarks != null && total !== view.lemelyMarks
  const showPage = mode === "page" && view.hasScan
  const wholePage = showPage ? pageFrame(images) : null
  // The page tab is open for an item whose page nobody asked for yet (the queue moved on under it): ask now.
  const requestPage = images.requestPage
  useEffect(() => { if (wholePage === "idle") requestPage() }, [wholePage, requestPage])
  const cropFrame = images.cropUrl ? "image" : images.cropFailed ? "failed" : "loading"
  // One polite region that stays mounted across tabs and scanned answers, so a failure is announced when it happens.
  const scanFailure = showPage ? (wholePage === "failed" ? "Couldn't show the page." : "") : cropFrame === "failed" ? "Couldn't show the scan. Lemely's reading is below." : ""
  const tone = ringTone(view.confidenceScore)
  // The phone answer page has no queue column, so the answer's title is the page's h1.
  const Title = onBack ? "h1" : "h2"
  const saveable = marking ? canSave(view.points, marking.state, view.maximumMarks, view.lemelyMarks) : false
  return (
    <article aria-label={view.title} className="flex min-h-0 w-full max-w-[780px] flex-1 flex-col">
      {/* The answer scrolls; the action bar below it does not, so Accept never leaves the screen. */}
      <div data-answer-scroll className="-mx-1 grid min-h-0 flex-1 content-start gap-3.5 overflow-y-auto px-1 pb-3 [scrollbar-width:thin]">
      <header className="flex flex-wrap items-center gap-3 shell-lg:flex-nowrap">
        {onBack ? (
          <button type="button" onClick={onBack} aria-label="Back to the queue" className={`inline-flex min-h-11 items-center gap-1.5 rounded-button bg-surface-container-lowest px-3 py-2 text-sm font-bold shadow-[inset_0_0_0_1.5px_var(--color-outline)] ${FOCUS}`}>{ICON_BACK}Queue</button>
        ) : null}
        <div className="order-3 flex min-w-0 flex-[1_1_100%] items-center gap-3 shell-lg:order-none shell-lg:flex-1">
          <KeyRing
            value={ringValue(view.confidenceScore)}
            size={96}
            tone={tone === "gold" ? "gold" : tone === "neutral" ? "neutral" : "warn"}
            label={ringLabel(view.confidenceScore)}
            center={view.confidenceScore == null ? (
              <span className="block h-[3px] w-[18px] rounded-full bg-current opacity-80" />
            ) : (
              <span dir="ltr" className="rq-ring-num font-mono text-[28px] font-semibold tabular-nums slashed-zero tracking-[-0.03em]">
                {ringText(view.confidenceScore)}<small className="rq-ring-pct font-sans text-sm font-bold opacity-70">%</small>
              </span>
            )}
          />
          <div className="min-w-0">
            <Title className="text-display-sm">
              {view.studentHref ? <Link to={view.studentHref} className="relative hover:underline pointer-coarse:after:absolute pointer-coarse:after:-inset-y-[9px] pointer-coarse:after:inset-x-0 pointer-coarse:after:content-['']">{view.title}</Link> : view.title}
            </Title>
            <div className="mt-0.5 font-mono text-dense-sm font-semibold leading-[1.3] text-on-surface-variant">{view.subtitle}</div>
          </div>
        </div>
        {nav ? (
          <div className="ms-auto flex items-center gap-1.5">
            <button type="button" aria-label="Previous answer" disabled={nav.pos <= 1} onClick={nav.onPrev} className={NAV_BTN}>{ICON_BACK}</button>
            <span className="min-w-16 text-center font-mono text-dense text-on-surface-variant tabular-nums">{nav.pos || "–"} of {nav.total}</span>
            <button type="button" aria-label="Next answer" disabled={nav.pos >= nav.total} onClick={nav.onNext} className={NAV_BTN}>{ICON_NEXT}</button>
          </div>
        ) : null}
      </header>

      {view.hasScan ? (
        <div role="tablist" aria-label="Answer view" className="inline-flex justify-self-start rounded-chip bg-surface-container p-[3px]">
          {(["crop", "page"] as const).map((m) => (
            <button key={m} ref={(el) => { tabRefs.current[m] = el }} id={`${uid}-tab-${m}`} aria-controls={`${uid}-panel`} tabIndex={mode === m ? 0 : -1} onKeyDown={onTabKey} type="button" role="tab" aria-selected={mode === m} onClick={() => pick(m)} className={`min-h-11 rounded-row px-3.5 py-1.5 text-dense font-bold text-on-surface-variant aria-selected:bg-surface-container-lowest aria-selected:text-primary aria-selected:shadow-[0_0_0_1px_var(--color-outline-variant)] ${FOCUS}`}>
              {m === "crop" ? "Answer" : "Whole page"}
            </button>
          ))}
        </div>
      ) : null}

      <div role={view.hasScan ? "tabpanel" : undefined} id={`${uid}-panel`} aria-labelledby={view.hasScan ? `${uid}-tab-${showPage ? "page" : "crop"}` : undefined} className="grid gap-3.5">
      {/* Only a scanned answer has an image that can fail; one with no scan (and the sample) adds no live region. */}
      {view.hasScan ? <p role="status" aria-live="polite" dir="auto" className="sr-only">{scanFailure}</p> : null}
      {showPage ? (
        <figure className={`${FRAME} ${wholePage === "failed" ? "" : "min-h-[300px]"}`}>
          {view.pageLabel ? <figcaption className={LABEL}>{view.pageLabel}</figcaption> : null}
          {wholePage === "image" ? (
            <img src={images.pageUrl ?? undefined} alt="The whole page this answer is on" onError={images.onPageError} decoding="async" className="max-h-[70vh] w-full rounded-row object-contain" />
          ) : wholePage === "failed" ? (
            <p aria-hidden="true" dir="auto" className="text-on-surface-variant">Couldn't show the page.</p>
          ) : (
            <div className="rq-skel h-[300px] rounded-row bg-surface-container-high" role="status" aria-label="Loading the page" />
          )}
        </figure>
      ) : view.hasScan ? (
        <figure className={`${FRAME} min-w-0 gap-2.5`}>
          {cropFrame === "image" ? (
            <img src={images.cropUrl ?? undefined} alt="The region of the student's scan this question's answer was read from" onError={images.onCropError} decoding="async" className="max-h-[360px] w-auto max-w-full justify-self-start rounded-row object-contain" />
          ) : cropFrame === "failed" ? (
            <p aria-hidden="true" dir="auto" className="grid min-h-24 place-items-center rounded-row bg-surface-container px-4 text-center text-sm text-on-surface-variant">Couldn't show the scan.</p>
          ) : (
            <div className="rq-skel h-[150px] rounded-row bg-surface-container-high" role="status" aria-label="Loading the scan" />
          )}
          <figcaption className="grid min-w-0 gap-1 rounded-row bg-surface-container-low px-3 py-2.5">
            <span className="flex items-center gap-1.5 text-dense-sm text-on-surface-variant"><TextAlignLeft size={14} aria-hidden />Lemely read</span>
            <span dir="auto" className={`whitespace-pre-wrap text-base leading-normal wrap-anywhere ${view.transcription ? "text-on-surface" : "text-on-surface-variant"}`}>
              {view.transcription || "No transcription recorded for this question."}
            </span>
          </figcaption>
        </figure>
      ) : (
        <figure className={`${FRAME} min-w-0`}>
          <div className="rq-ruled text-2xl leading-[36px] shell-sm:text-3xl shell-sm:leading-[42px]">
            <p dir="auto" className="m-0 whitespace-pre-wrap wrap-anywhere text-on-surface">{view.transcription || "No transcription recorded for this question."}</p>
          </div>
          <figcaption className="text-dense-sm text-on-surface-variant">Lemely's reading of the answer · no scan for this answer</figcaption>
        </figure>
      )}
      </div>

      <section className="grid gap-0.5 rounded-button bg-surface-container-low px-3.5 py-2.5">
        <span className={LABEL}>Student said</span>
        {view.selfReview.length === 0 ? (
          <div className="text-sm leading-[1.45] text-on-surface-variant">No self-review yet.</div>
        ) : (
          view.selfReview.map((s) => (
            <div key={s.code} className="text-sm leading-[1.45]">
              <b className="font-mono text-dense-sm">{s.code}</b> {s.claim}{s.evidence ? <> · “{s.evidence}”</> : null}
              <span className="text-on-surface-variant"> · {s.judge}</span>
            </div>
          ))
        )}
      </section>

      {view.status === "open" && marking && !view.integrity ? (
        <fieldset disabled={!canMark} className="m-0 min-w-0 border-0 p-0">
          <MarkControls points={view.points} state={marking.state} max={view.maximumMarks} lemely={view.lemelyMarks} disabled={!view.canAdjust} disabledReason={view.cannotAdjustReason} clampNote={view.clampNote} matchedPointIds={view.matchedPointIds} onChange={marking.onChange} />
        </fieldset>
      ) : view.clampNote ? (
        <p className="text-dense text-on-surface-variant">{view.clampNote}</p>
      ) : null}

      {view.scheme.expected || view.scheme.topic ? (
        <details className="rounded-button bg-surface-container-low px-3.5 py-2.5">
          <summary className={`cursor-pointer text-sm font-bold text-primary ${FOCUS}`}>Mark scheme wording</summary>
          {view.scheme.expected ? <p className="mt-2 max-w-[68ch] whitespace-pre-wrap text-sm leading-[1.5] text-on-surface-variant">{view.scheme.expected}</p> : null}
          {view.scheme.topic ? <p className="mt-1 text-dense text-on-surface-variant">Topic: {view.scheme.topic}</p> : null}
        </details>
      ) : null}

      {view.notes.reason || view.notes.feedback ? (
        <details className="rounded-button bg-surface-container-low px-3.5 py-2.5">
          <summary className={`cursor-pointer text-sm font-bold text-primary ${FOCUS}`}>Lemely's notes</summary>
          {view.notes.feedback ? <p className="mt-2 max-w-[68ch] text-sm leading-[1.5] text-on-surface-variant">{view.notes.feedback}</p> : null}
          {view.notes.reason ? <p className="mt-1 max-w-[68ch] font-mono text-dense-sm text-on-surface-variant">{view.notes.reason}</p> : null}
        </details>
      ) : null}

      {view.status !== "open" ? (
        <section role="status" className="grid gap-1.5 rounded-button bg-surface-container px-3.5 py-2.5 text-sm">
          <b>{view.status === "dismissed" ? "Dismissed" : "Resolved"}</b>
          {view.correction ? <span>Changed to <span className="font-mono">{view.correction.marks}/{view.maximumMarks ?? "–"}</span>{view.correction.note ? ` · “${view.correction.note}”` : ""}{view.correction.at ? ` · ${relativeTime(view.correction.at)}` : ""}</span> : null}
          {view.resolutionNote ? <span className="text-on-surface-variant">Note: “{view.resolutionNote}”</span> : null}
        </section>
      ) : null}

      {view.status === "open" && marking ? (
        <>
          {view.integrity ? (
            <p className="flex items-start gap-2 text-dense text-on-surface-variant"><Flag weight="fill" className="mt-0.5 size-4 flex-none text-on-tertiary-container" aria-hidden />A signal to look at, not a verdict. Dismissing never changes the student's mark.</p>
          ) : null}
          <Textarea rows={2} disabled={!canMark} value={view.integrity ? dismissNote : marking.note} onChange={(e) => (view.integrity ? setDismissNote(e.target.value) : marking.onNote(e.target.value))} placeholder={view.integrity ? "Note for your records (optional)" : notePlaceholder(changed)} label={view.integrity ? "Note for your records" : notePlaceholder(changed)} labelClassName="sr-only" className="rq-note resize-none py-2.5 caret-primary" />
        </>
      ) : null}
      </div>

      {view.status === "open" && marking ? (
        <footer data-answer-actions className="grid shrink-0 gap-1.5 border-t border-outline-variant bg-surface pt-3 pb-3 max-shell-sm:pb-[max(12px,env(safe-area-inset-bottom))]">
          {!canMark && markDenied ? <p role="note" className="text-dense text-on-surface-variant">{markDenied}</p> : null}
          <div className="flex gap-2">
            {view.integrity ? (
              <button type="button" data-testid="primary-action" disabled={!canMark} onClick={() => marking.onDismiss(dismissNote)} className={`min-h-11 flex-1 rounded-button bg-primary px-[18px] py-[11px] text-sm font-bold text-on-primary transition-transform duration-150 active:scale-[.97] disabled:opacity-40 motion-reduce:transition-none ${FOCUS}`}>Dismiss flag</button>
            ) : (
              <button type="button" data-testid="primary-action" disabled={!saveable || !canMark} onClick={marking.onAccept} className={`min-h-11 flex-1 rounded-button bg-primary px-[18px] py-[11px] text-sm font-bold text-on-primary transition-transform duration-150 active:scale-[.97] disabled:opacity-40 motion-reduce:transition-none ${FOCUS}`}>{primaryActionLabel(total, view.maximumMarks, view.lemelyMarks)}</button>
            )}
          </div>
          {showShortcuts ? (
            <p className="hidden font-mono text-xs text-on-surface-variant shell-lg:block" aria-hidden="true">A accept · N next · J/K move · / search</p>
          ) : null}
        </footer>
      ) : null}
    </article>
  )
}

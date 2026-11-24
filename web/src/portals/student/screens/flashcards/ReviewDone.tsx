/* Hallmark · pre-emit critique: P4 H4 E3 S3 R4 V4 */
import { X } from "@phosphor-icons/react"
import { Link } from "react-router-dom"
import { useEffect, useRef } from "react"
import { Binny, GoldRing } from "@/components/redesign"
import type { DoneView } from "./reviewView"
import { PRIMARY_BTN } from "./parts/buttonStyles"
import "./flashcards.css"

/** RD: green-to-surface wash, Binny 110 hop, "All caught up!", gain3, Coming back, Back to decks. */
export function ReviewDone({
  view, onBack, today, banner,
}: { view: DoneView; onBack: () => void; today: [number, number, number] | null; banner: React.ReactNode }) {
  const heading = useRef<HTMLHeadingElement>(null)
  useEffect(() => { heading.current?.focus() }, [])
  const done = today ? today.filter((p) => p >= 1).length : 0
  return (
    <div className="fc-review-done flex min-h-[calc(100dvh-var(--native-bar-h,56px)-env(safe-area-inset-top)-0.25rem)] flex-1 flex-col gap-[18px] overflow-auto lg:min-h-0 bg-[linear-gradient(180deg,var(--color-success-container),var(--color-surface)_45%)] -ml-[var(--fc-bleed-l)] -mr-[var(--fc-bleed-r)] pl-[calc(var(--fc-bleed-l)+6px)] pr-[calc(var(--fc-bleed-r)+6px)] pb-[26px] pt-4 [scrollbar-width:none] lg:mx-auto lg:w-full lg:max-w-[640px] lg:bg-none lg:px-5">
      <button type="button" aria-label="Close" onClick={onBack} className="grid size-11 place-items-center rounded-[14px] bg-primary-container text-primary"><X size={20} aria-hidden /></button>
      <div className="grid justify-items-center gap-1.5 leading-tight">
        <Binny mood={view.mood} size={110} motion="hop" />
        <h1 ref={heading} tabIndex={-1} className="text-center font-display text-[34px] font-extrabold leading-[1.05] tracking-[-0.03em] text-primary">{view.title}</h1>
        <p className="text-center text-[14px] font-medium text-on-surface-variant">{view.sub}</p>
      </div>
      {banner}
      <div className={`grid text-center leading-tight ${today ? "grid-cols-3" : "grid-cols-2"}`}>
        <span className="grid justify-items-center gap-0.5"><b className="font-mono text-[24px] font-extrabold text-success-text">{view.knew}</b><small className="text-[12.5px] font-medium text-on-surface-variant">knew it</small></span>
        <span className="grid justify-items-center gap-0.5"><b className="font-mono text-[24px] font-extrabold text-primary">+{view.xp}</b><small className="text-[12.5px] font-medium text-on-surface-variant">XP</small></span>
        {today ? (
          <span className="grid justify-items-center gap-0.5"><GoldRing parts={today} size={32} label={`Today ${done} of 3`} /><small className="text-[12.5px] font-medium text-on-surface-variant">Today {done} of 3</small></span>
        ) : null}
      </div>
      {view.stillDueLine || view.savingLine ? (
        <p className="text-center text-[13px] text-on-surface-variant">{[view.stillDueLine, view.savingLine].filter(Boolean).join(" · ")}</p>
      ) : null}
      <div className="grid leading-tight">
        <h2 className="font-sans text-[18px] font-extrabold tracking-[-0.01em] text-on-surface">Coming back</h2>
        {view.comingBack.map((r) => (
          <div key={r.title} className="grid py-2.5 shadow-[0_-1px_0_var(--color-outline-variant)]">
            <b className="text-[15px] font-bold text-on-surface">{r.title}</b>
            {r.sub ? <span className="text-[13px] text-on-surface-variant">{r.sub}</span> : null}
          </div>
        ))}
      </div>
      <button type="button" onClick={onBack} className={PRIMARY_BTN}>Back to decks</button>
      {view.practiceLink ? <Link to={view.practiceLink.to} className="inline-flex min-h-11 items-center self-center px-3.5 text-[15px] font-bold text-primary">{view.practiceLink.label}</Link> : null}
    </div>
  )
}

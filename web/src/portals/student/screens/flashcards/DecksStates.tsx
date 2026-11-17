import { CaretRight, PencilSimple, Sparkle, Target } from "@phosphor-icons/react"
import { Link } from "react-router-dom"
import { Binny, Walkthrough } from "@/components/redesign"
import { SkeletonBlock } from "@/components/ui/skeleton"
import type { NewDeckMode } from "./newDeckView"

/** FL: 64 r16, 56 r16, 120×20, 4 × 60 r14 (fc.js `put('FL',…)`). */
export function DecksLoading() {
  return (
    <div className="grid gap-3.5" aria-busy="true" aria-label="Loading your decks">
      <SkeletonBlock className="h-16 rounded-2xl" />
      <SkeletonBlock className="h-14 rounded-2xl" />
      <SkeletonBlock className="h-5 w-[120px] rounded-[10px]" />
      {[0, 1, 2, 3].map((i) => <SkeletonBlock key={i} className="h-[60px] rounded-[14px]" />)}
    </div>
  )
}

const FOCUS = "focus-visible:outline-[2.5px] focus-visible:outline-offset-2 focus-visible:outline-primary"

/** FE. */
export function DecksError({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="grid flex-1 content-center justify-items-center gap-3 px-2 py-6 text-center" role="alert">
      <Binny mood="sad" size={96} />
      <h2 className="mt-1.5 font-display text-[26px] font-extrabold leading-[1.15] tracking-[-0.02em] text-balance text-primary">
        We couldn’t load your decks
      </h2>
      <p className="mb-1.5 max-w-[30ch] text-[15px] leading-[1.4] text-on-surface-variant">Check your connection, then try again.</p>
      <button type="button" onClick={onRetry} className={`min-h-[50px] w-full max-w-[320px] rounded-[18px] bg-primary px-7 text-[15.5px] font-bold text-on-primary ${FOCUS}`}>
        Try again
      </button>
      <Link to="/student" className={`inline-flex min-h-11 items-center px-3.5 text-[15px] font-bold text-primary ${FOCUS}`}>Back to Home</Link>
    </div>
  )
}

const OPTIONS: { mode: NewDeckMode; icon: typeof Target; title: string; tone: string }[] = [
  { mode: "weakness", icon: Target, title: "From a weakness", tone: "bg-error-container text-on-error-container" },
  { mode: "topic", icon: Sparkle, title: "For a topic", tone: "bg-secondary-container text-on-secondary-container" },
  { mode: "manual", icon: PencilSimple, title: "Write my own", tone: "bg-primary-container text-primary" },
]

/** FZ: Binny open 96, heading, line, then the three ways in (`.ndo` with chevrons). */
export function EmptyShelf({ weakHint, onPick }: { weakHint: string | null; onPick: (mode: NewDeckMode) => void }) {
  const subs: Record<NewDeckMode, string> = {
    weakness: weakHint ?? "Cards on what cost you marks",
    topic: "Pick any syllabus topic",
    manual: "Type your own cards",
  }
  return (
    <div className="mx-auto flex w-full max-w-[520px] flex-col gap-6">
      <div className="grid justify-items-center gap-3 pt-3 text-center">
        <Binny mood="open" size={96} />
        <h2 className="mt-1.5 font-display text-[26px] font-extrabold leading-[1.15] tracking-[-0.02em] text-balance text-primary">Nothing on the shelf yet</h2>
        <p className="max-w-[30ch] text-[15px] leading-[1.4] text-on-surface-variant">Make a deck from what cost you marks. Lemely writes the cards.</p>
      </div>
      <div className="grid gap-2">
        {OPTIONS.map((o, i) => (
          <button key={o.mode} type="button" onClick={() => onPick(o.mode)}
            className={[
              "grid min-h-[60px] grid-cols-[40px_minmax(0,1fr)_auto] items-center gap-3 rounded-2xl px-3 py-2.5 text-start text-on-surface",
              FOCUS,
              i === 0 ? "bg-primary-container shadow-[inset_0_0_0_2px_var(--color-primary)]" : "bg-surface-container-lowest shadow-[inset_0_0_0_1.5px_var(--color-outline-variant)]",
            ].join(" ")}>
            <span className={`grid size-10 place-items-center rounded-xl ${o.tone}`}><o.icon size={16} weight="bold" aria-hidden /></span>
            <span className="grid"><b className="text-[15px] font-bold">{o.title}</b><span className="text-[13px] text-on-surface-variant">{subs[o.mode]}</span></span>
            <CaretRight size={18} aria-hidden className="text-on-surface-variant" />
          </button>
        ))}
      </div>
    </div>
  )
}

/** FS extras: `.tipr` + `.walk2` (2 steps). */
export function SparseExtras({
  tip, onMakeTip,
}: { tip: { title: string; body: string } | null; onMakeTip: () => void }) {
  return (
    <>
      {tip ? (
        <div className="flex items-center justify-between gap-3 py-3 shadow-[0_-1px_0_var(--color-outline-variant)]">
          <span className="grid"><b className="text-[15px] font-bold">{tip.title}</b><span className="text-[13px] text-on-surface-variant">{tip.body}</span></span>
          <button type="button" onClick={onMakeTip} className={`min-h-11 flex-none rounded-[14px] bg-primary px-4 text-[14px] font-bold text-on-primary ${FOCUS}`}>Make it</button>
        </div>
      ) : null}
      <Walkthrough
        steps={[
          { icon: Sparkle, title: "A few minutes a day", body: "Cards show up here when they’re due." },
          { icon: Target, title: "Be honest when you rate", body: "Again brings a card back soon. Easy sends it away for a week." },
        ]}
      />
    </>
  )
}

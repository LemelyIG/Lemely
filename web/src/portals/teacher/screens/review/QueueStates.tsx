import { CheckCircle, Flag, Stack } from "@phosphor-icons/react"
import { Link } from "react-router-dom"
import { Binny, GhostRows, Walkthrough, type BinnyMood } from "@/components/redesign"
import "./review.css"
import { clearedSummary, type Tally } from "./reviewQueueModel"

const PRIMARY_BTN = "rounded-[14px] bg-primary px-[18px] py-[11px] text-[14px] font-bold text-on-primary active:scale-[.97] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary pointer-coarse:min-h-11"

/** Teacher Binny: the head crop only, calm states only. */
export function TeacherBinny({ mood, size = 56 }: { mood: BinnyMood; size?: number }) {
  return (
    <span className="inline-block flex-none" style={{ width: size, height: size }} aria-hidden="true">
      <Binny mood={mood} size={size} motion="idle" headCrop aria-hidden />
    </span>
  )
}

export function QueueLoading() {
  return (
    <div className="grid gap-2" aria-busy="true" aria-label="Loading the review queue">
      {[0, 1, 2, 3].map((i) => (
        <div key={i} className="lm-rq-skel h-[76px] rounded-[14px] bg-surface-container-high" />
      ))}
    </div>
  )
}

export function QueueError({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div role="alert" className="grid justify-items-start gap-2.5 px-1 py-7">
      <h2 className="text-[24px] font-extrabold leading-[1.2] tracking-[-0.02em]">Couldn't load the review queue.</h2>
      <p className="text-on-surface-variant">{message}</p>
      <button type="button" onClick={onRetry} className={PRIMARY_BTN}>Try again</button>
    </div>
  )
}

export function NoMatch({ onClear }: { onClear: () => void }) {
  return (
    <div role="status" className="grid justify-items-center gap-3 px-3 py-7 text-center text-on-surface-variant">
      <b className="text-[16px] font-bold text-on-surface">No answers match these filters.</b>
      <button type="button" onClick={onClear} className="rounded-[14px] bg-primary-container px-[18px] py-[11px] text-[14px] font-bold text-primary active:scale-[.97] focus-visible:outline-2 focus-visible:outline-primary pointer-coarse:min-h-11">Clear filters</button>
    </div>
  )
}

export function SparseNote({ markHref }: { markHref: string }) {
  return (
    <div className="grid gap-1.5 rounded-[18px] bg-primary-container px-[18px] py-4">
      <b className="text-[16px] font-bold text-primary">That's the only one.</b>
      <p className="text-[14px] text-primary opacity-85">Each class set you mark adds a few answers here. Checking them keeps every grade honest.</p>
      <Link to={markHref} className="justify-self-start rounded-[14px] bg-surface-container-lowest px-3.5 py-2 text-[13px] font-bold text-primary focus-visible:outline-2 focus-visible:outline-primary pointer-coarse:min-h-11">Mark another class set</Link>
    </div>
  )
}

export function FirstRun({ markHref, phone }: { markHref: string; phone: boolean }) {
  const steps = phone
    ? [
        { icon: Stack, title: "Mark a class set", body: "Names are read off the covers." },
        { icon: Flag, title: "Lemely flags unsure answers", body: "Usually two or three a paper." },
        { icon: CheckCircle, title: "You decide", body: "Under a minute each." },
      ]
    : [
        { icon: Stack, title: "Mark a class set", body: "Drop the PDFs on Papers. Names are read off the covers." },
        { icon: Flag, title: "Lemely flags the unsure answers", body: "Most papers come back with two or three." },
        { icon: CheckCircle, title: "You decide here", body: "Tick or change the mark. Usually under a minute each." },
      ]
  return (
    <div className="grid gap-6">
      <section className="grid max-w-[820px] gap-[22px] rounded-[28px] bg-surface-container-lowest p-7 shadow-[inset_0_0_0_1px_var(--color-outline-variant)] max-shell-sm:gap-4 max-shell-sm:p-5">
        <div className="flex items-center gap-4">
          <TeacherBinny mood="open" size={phone ? 48 : 56} />
          <div>
            <h2 className="font-display text-[28px] font-extrabold leading-[1.15] tracking-[-0.03em] text-primary">Nothing to review yet</h2>
            {phone ? null : <p className="mt-1 max-w-[46ch] text-on-surface-variant">When Lemely isn't sure about a mark, the answer comes here for you to decide.</p>}
          </div>
        </div>
        {phone ? <p className="text-[14.5px] text-on-surface-variant">When Lemely isn't sure about a mark, the answer lands here for you.</p> : null}
        <Walkthrough steps={steps} />
        <Link to={markHref} className={`${PRIMARY_BTN} justify-self-start`}>Mark papers</Link>
      </section>
      {phone ? null : (
        <div className="grid max-w-[820px] gap-2.5 opacity-75" aria-hidden="true">
          <span className="text-[13px] font-semibold text-on-surface-variant">Answers to check will look like this</span>
          <GhostRows rows={2} withLeading />
        </div>
      )}
    </div>
  )
}

export function NothingWaiting() {
  return (
    <div className="grid justify-items-center gap-3 px-6 py-16 text-center">
      <TeacherBinny mood="happy" size={48} />
      <h2 className="text-[24px] font-extrabold tracking-[-0.02em]">Nothing to review.</h2>
      <p className="text-on-surface-variant">Every mark is confident or already decided.</p>
    </div>
  )
}

export function Cleared({ tally, markHref }: { tally: Tally; markHref: string }) {
  return (
    <div role="status" className="grid justify-items-center px-6 py-16 text-center">
      <div className="lm-rq-bump-lg font-display text-[120px] font-extrabold leading-none tracking-[-0.05em] text-primary tabular-nums">{tally.decided}</div>
      <div className="mt-1.5 flex items-center gap-3">
        <TeacherBinny mood="happy" size={40} />
        <h2 className="text-[32px] font-extrabold leading-[1.15] tracking-[-0.02em]">Queue clear.</h2>
      </div>
      <p className="mb-5 mt-2 text-[16px] leading-[1.5] text-on-surface-variant">{clearedSummary(tally)}</p>
      <Link to={markHref} className={PRIMARY_BTN}>Mark another class set</Link>
    </div>
  )
}

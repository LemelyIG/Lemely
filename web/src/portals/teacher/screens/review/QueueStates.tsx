/* Hallmark · pre-emit critique: P4 H4 E3 S4 R4 V4 */
import { useState } from "react"
import { Link } from "react-router-dom"
import { Binny, GhostRows, Walkthrough, type BinnyMood } from "@/components/redesign"
import { PageHeading } from "@/components/ui/page-heading"
import "./review.css"
import { clearedSummary, type Tally } from "./reviewQueueModel"
import { SampleAnswer } from "./SampleAnswer"

const PRIMARY_BTN = "rounded-button bg-primary px-[18px] py-[11px] text-sm font-bold text-on-primary transition-transform duration-150 motion-reduce:transition-none active:scale-[.97] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary pointer-coarse:min-h-11"

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
      <h1 className="sr-only">Review</h1>
      {[0, 1, 2, 3].map((i) => (
        <div key={i} className="rq-skel h-[76px] rounded-button bg-surface-container-high" />
      ))}
    </div>
  )
}

export function NoMatch({ onClear }: { onClear: () => void }) {
  return (
    <div role="status" className="grid justify-items-center gap-3 px-3 py-7 text-center text-on-surface-variant">
      <b className="text-base font-bold text-on-surface">No answers match these filters.</b>
      <button type="button" onClick={onClear} className="rounded-button bg-primary-container px-[18px] py-[11px] text-sm font-bold text-primary transition-transform duration-150 motion-reduce:transition-none active:scale-[.97] focus-visible:outline-2 focus-visible:outline-primary pointer-coarse:min-h-11">Clear filters</button>
    </div>
  )
}

export function SparseNote({ markHref }: { markHref: string }) {
  return (
    <div className="grid gap-1.5 rounded-inner bg-primary-container px-[18px] py-4">
      <b className="text-base font-bold text-primary">That's the only one.</b>
      <p className="text-sm text-primary opacity-85">Each class set you mark adds a few answers here. Checking them keeps every grade honest.</p>
      <Link to={markHref} className="justify-self-start rounded-button bg-surface-container-lowest px-3.5 py-2 text-dense font-bold text-primary focus-visible:outline-2 focus-visible:outline-primary pointer-coarse:min-h-11">Mark another class set</Link>
    </div>
  )
}

export function FirstRun({ markHref, phone }: { markHref: string; phone: boolean }) {
  const [sampleOpen, setSampleOpen] = useState(false)
  // Numbered, not iconed: the order is the point (states-r1 RQ1/RQ3).
  const steps = phone
    ? [
        { title: "Mark a class set", body: "Names are read off the covers." },
        { title: "Lemely flags unsure answers", body: "Usually two or three a paper." },
        { title: "You decide", body: "Under a minute each." },
      ]
    : [
        { title: "Mark a class set", body: "Drop the PDFs on Papers. Names are read off the covers." },
        { title: "Lemely flags the unsure answers", body: "Most papers come back with two or three." },
        { title: "You decide here", body: "Tick or change the mark. Usually under a minute each." },
      ]
  return (
    <div className="grid gap-6">
      <section className="grid max-w-[820px] gap-[22px] rounded-card bg-surface-container-lowest p-7 shadow-[inset_0_0_0_1px_var(--color-outline-variant)] max-shell-sm:gap-4 max-shell-sm:p-5">
        <div className="flex items-center gap-4">
          <TeacherBinny mood="open" size={phone ? 48 : 56} />
          <div>
            <PageHeading repeatsTitle={false} className="font-display text-3xl font-extrabold leading-[1.15] tracking-[-0.03em] text-primary">Nothing to review yet</PageHeading>
            {phone ? null : <p className="mt-1 max-w-[46ch] text-on-surface-variant">When Lemely isn't sure about a mark, the answer comes here for you to decide.</p>}
          </div>
        </div>
        {phone ? <p className="text-sm text-on-surface-variant">When Lemely isn't sure about a mark, the answer lands here for you.</p> : null}
        <Walkthrough steps={steps} />
        <div className="flex flex-wrap items-center gap-2.5">
          <Link to={markHref} className={PRIMARY_BTN}>Mark papers</Link>
          <button
            type="button"
            aria-haspopup="dialog"
            // Focus the link first: Safari does not focus a clicked button, and the dialog hands focus back to
            // whatever held it when it opened.
            onClick={(e) => { e.currentTarget.focus(); setSampleOpen(true) }}
            className="inline-flex min-h-11 items-center rounded-button px-3.5 text-sm font-bold text-primary underline-offset-4 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
          >See a sample answer</button>
        </div>
      </section>
      {phone ? null : (
        <div className="grid max-w-[820px] gap-2.5 opacity-75" aria-hidden="true">
          <span className="text-dense font-semibold text-on-surface-variant">Answers to check will look like this</span>
          <GhostRows rows={2} withLeading />
        </div>
      )}
      <SampleAnswer open={sampleOpen} onClose={() => setSampleOpen(false)} />
    </div>
  )
}

export function NothingWaiting() {
  return (
    <div className="grid justify-items-center gap-3 px-6 py-16 text-center">
      <TeacherBinny mood="happy" size={48} />
      <PageHeading repeatsTitle={false} tabIndex={-1} data-review-heading className="text-2xl font-extrabold tracking-[-0.02em] outline-none">Nothing to review.</PageHeading>
      <p className="text-on-surface-variant">Every mark is confident or already decided.</p>
    </div>
  )
}

export function Cleared({ tally, markHref }: { tally: Tally; markHref: string }) {
  return (
    <div role="status" className="grid justify-items-center px-6 py-16 text-center">
      <div className="rq-bump-lg font-display text-9xl font-extrabold leading-none tracking-[-0.05em] text-primary tabular-nums">{tally.decided}</div>
      <div className="mt-1.5 flex items-center gap-3">
        <TeacherBinny mood="happy" size={40} />
        <PageHeading repeatsTitle={false} tabIndex={-1} data-review-heading className="text-display-md outline-none">Queue clear.</PageHeading>
      </div>
      <p className="mb-5 mt-2 text-base leading-[1.5] text-on-surface-variant">{clearedSummary(tally)}</p>
      <Link to={markHref} className={PRIMARY_BTN}>Mark another class set</Link>
    </div>
  )
}

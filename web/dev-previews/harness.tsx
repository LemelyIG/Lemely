/**
 * Preview harness for the Study Notebook component kit.
 *
 * REDESIGN-MISSION §5 Phase 2.6 requires every component in the kit to
 * implement all eight states (default / hover / focus-visible / active /
 * disabled / loading / error / success) and to have a preview page proving it.
 * This file is the scaffolding that page is built from; `App.tsx` beside it is
 * the page.
 *
 * Two of the eight states cannot be produced by a static render, because they
 * only exist while a pointer or the keyboard is interacting with the element:
 * `hover` and `active`. The honest thing is to say so rather than to fake them
 * with a class that merely looks like the hover style. So each state cell is
 * labelled with how it is produced:
 *
 *   - **prop**   the component genuinely is in that state (disabled, loading,
 *                error, success) and what you see is real
 *   - **live**   you must hover, focus or press the control to see it; the
 *                cell renders the ordinary component and says exactly what to do
 *
 * There is deliberately no third "forced" mode. One was built: a
 * `@custom-variant` pinning `hover`/`active` under a `data-force` wrapper, so a
 * static screenshot could capture them. It emitted zero CSS in this setup (the
 * reason is recorded in `preview.css`) and was removed rather than left in
 * place. A cell labelled as showing a hover state while actually rendering the
 * default state is worse than a cell that simply tells you to hover, because
 * the first one quietly passes review. Hover and active are verified with a
 * real pointer in the Phase 6 pass.
 *
 * This directory is NOT part of the app build. It is a separate Vite entry
 * (see `vite.preview.config.ts`) so that shipping the product never ships the
 * preview page, and so the preview cannot drift into being a real route.
 */

import type { ReactNode } from "react"

/** The eight states every interactive component must implement. */
export const STATES = [
  "default",
  "hover",
  "focus-visible",
  "active",
  "disabled",
  "loading",
  "error",
  "success",
] as const

export type State = (typeof STATES)[number]

/** How a given state cell was produced. See the file header. */
export type Provenance = "prop" | "live"

const PROVENANCE_LABEL: Record<Provenance, string> = {
  prop: "real",
  live: "interact",
}

const PROVENANCE_TONE: Record<Provenance, string> = {
  prop: "bg-ok-wash text-ok",
  live: "bg-info-wash text-info",
}

/**
 * A single labelled state cell.
 *
 * The label is not decoration. A preview page whose cells are unlabelled is
 * how a component ends up shipping with a `disabled` style that was never
 * actually rendered in the disabled state, because the reviewer assumed the
 * cell was real when it was a mock.
 */
export function StateCell({
  state,
  provenance,
  note,
  children,
}: {
  state: State
  provenance: Provenance
  note?: string
  children: ReactNode
}) {
  return (
    <div className="flex flex-col gap-3 rounded-lg border border-rule bg-paper p-4">
      <div className="flex items-center justify-between gap-2">
        <span className="text-eyebrow text-ink-muted">{state}</span>
        <span
          className={`rounded-full px-2 py-0.5 text-eyebrow ${PROVENANCE_TONE[provenance]}`}
          title={
            provenance === "live"
              ? "Interact with this control to see the state"
              : "The component really is in this state"
          }
        >
          {PROVENANCE_LABEL[provenance]}
        </span>
      </div>
      <div className="flex min-h-16 flex-wrap items-center gap-3">{children}</div>
      {note ? <p className="text-body-sm text-ink-faint">{note}</p> : null}
    </div>
  )
}

/** One component's section: a title, an optional note, and its state grid. */
export function ComponentSection({
  name,
  summary,
  children,
}: {
  name: string
  summary: string
  children: ReactNode
}) {
  return (
    <section className="flex flex-col gap-5 scroll-mt-24" id={slug(name)}>
      <header className="flex flex-col gap-2 margin-rule">
        <h2 className="text-display-md text-ink">{name}</h2>
        <p className="text-body-md max-w-[65ch] text-ink-muted">{summary}</p>
      </header>
      <div className="grid grid-cols-[repeat(auto-fill,minmax(260px,1fr))] gap-4">{children}</div>
    </section>
  )
}

/** A group of related component sections. */
export function Group({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-section-sm">
      <h1 className="text-display-lg text-ink">{title}</h1>
      {children}
    </div>
  )
}

export function slug(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "")
}

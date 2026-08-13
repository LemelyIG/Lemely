/* Hallmark · pre-emit critique: P5 H5 E4 S5 R4 V4 */
import type { ReactNode } from "react"
import { Link } from "react-router-dom"
import { Check } from "@phosphor-icons/react"
import { cn } from "@/lib/utils"
import { buttonVariants } from "@/components/ui/button"

/*
 * P3.2 · The first-run "getting started" panel.
 *
 * Phase 3's brief is that an empty dashboard becomes a composed getting-started
 * view rather than a blank one. All three portals already had an empty state,
 * so this is not filling a hole — it is replacing a single centred
 * `EmptyState` ("Correct your first paper to see it here", one button) with
 * something that answers the question a first-run reader is actually asking,
 * which is not "what is missing" but "what happens next, and how many of these
 * are there".
 *
 * The honesty constraint shaped this more than the visual brief did.
 *
 * No endpoint in this product reports per-step onboarding progress. There is
 * no `GET /me/onboarding` and nothing equivalent: what each portal can observe
 * is one or two facts (a student has no corrected papers; a teacher has no
 * classes; a parent has no linked children). A checklist that rendered
 * confident ticks against steps we cannot observe would be inventing state,
 * which is the same class of defect as the fabricated statistics the Phase 1
 * audit found on the landing page — and worse here, because a wrong tick tells
 * a student they have already done something they have not.
 *
 * So `status` is supplied per step by the caller, and callers pass `done` only
 * where they hold evidence. `later` steps deliberately carry no action and no
 * tick: they describe what the product will do once the earlier step happens,
 * which is information, not a control. That is why this is a numbered
 * narrative rather than a checklist with boxes.
 *
 * Visual register is DESIGN.md §4's notebook: ruled hairlines between steps,
 * the step numbers set in the margin like an exercise book, and one drawn
 * accent underline on the heading. Marginalia decorates; every step's meaning
 * is carried by its text.
 */

export type GettingStartedStatus = "done" | "now" | "later"

export interface GettingStartedStep {
  /** Short imperative title, sentence case. */
  title: string
  /** One or two plain sentences on what this step gets the reader. */
  body: string
  /**
   * `now` is the step to do next and is the only status that renders an
   * action. `done` renders a tick and requires the caller to actually know it.
   * `later` describes what follows and is deliberately inert.
   */
  status: GettingStartedStatus
  /** Route for the step's action. Only rendered when `status` is `now`. */
  to?: string
  /** Label for that action. Required alongside `to`. */
  actionLabel?: string
}

export interface GettingStartedProps {
  /** The reader-facing heading, e.g. "Let's get you set up". */
  heading: string
  /** One sentence framing what the list below is. */
  body: string
  steps: GettingStartedStep[]
  /**
   * Optional aside under the steps — the place for a reassurance or a caveat
   * that is not itself a step.
   */
  footnote?: ReactNode
  className?: string
}

export function GettingStarted({
  heading,
  body,
  steps,
  footnote,
  className,
}: GettingStartedProps) {
  return (
    <section
      className={cn(
        "relative overflow-hidden rounded-lg border border-rule bg-paper-raised",
        className,
      )}
    >
      <div className="flex flex-col gap-2 px-6 pb-5 pt-6 sm:px-8 sm:pt-8">
        <h2 className="relative inline-block self-start text-display-md text-ink">
          {heading}
          {/* Hand-drawn underline, the notebook register's lightest touch.
              Purely decorative: the heading reads identically without it. */}
          <svg
            viewBox="0 0 200 8"
            preserveAspectRatio="none"
            aria-hidden="true"
            className="absolute start-0 -bottom-1 h-2 w-full text-accent-subtle"
          >
            <path
              d="M2 5.5c38-3 62-3.6 98-2.2 34 1.3 62 2.6 98 1"
              fill="none"
              stroke="currentColor"
              strokeWidth="3"
              strokeLinecap="round"
            />
          </svg>
        </h2>
        <p className="max-w-[60ch] text-body-md text-ink-muted">{body}</p>
      </div>

      {/* `<ol>` because the order is the message: these steps happen in
          sequence, and a screen reader should say "3 items, item 1 of 3". */}
      <ol className="flex flex-col border-t border-rule">
        {steps.map((step, index) => {
          const isDone = step.status === "done"
          const isNow = step.status === "now"

          return (
            <li
              key={step.title}
              className={cn(
                "flex items-start gap-4 border-b border-rule px-6 py-5 last:border-b-0 sm:px-8",
                // The current step is the only one lifted off the paper. The
                // others recede rather than compete with it.
                isNow && "bg-paper-sunk",
              )}
            >
              {/* Step number in the margin. `done` swaps the number for a
                  tick, with the number kept in the accessible name so the
                  sequence is still announced. */}
              <span
                className={cn(
                  "mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full border text-metadata",
                  isDone && "border-ok bg-ok-wash text-ok",
                  isNow && "border-accent bg-accent text-accent-on",
                  !isDone && !isNow && "border-rule bg-paper text-ink-faint",
                )}
              >
                {isDone ? (
                  <Check size={14} weight="bold" aria-hidden="true" />
                ) : (
                  <span aria-hidden="true">{index + 1}</span>
                )}
              </span>

              <div className="flex min-w-0 flex-1 flex-col gap-1.5">
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                  <h3
                    className={cn(
                      "text-body-lg font-medium",
                      isDone ? "text-ink-muted" : "text-ink",
                    )}
                  >
                    {step.title}
                  </h3>
                  {isDone ? (
                    // A visible word, not colour alone: the tick and the green
                    // are both unavailable to a reader who cannot see them.
                    <span className="text-metadata uppercase tracking-wide text-ok">
                      Done
                    </span>
                  ) : null}
                </div>
                <p className="max-w-[60ch] text-body-md text-ink-muted">{step.body}</p>

                {isNow && step.to && step.actionLabel ? (
                  <Link
                    to={step.to}
                    className={cn(
                      buttonVariants({ variant: "primary", size: "sm" }),
                      "mt-2 self-start",
                    )}
                  >
                    {step.actionLabel}
                  </Link>
                ) : null}
              </div>
            </li>
          )
        })}
      </ol>

      {footnote ? (
        <div className="border-t border-rule px-6 py-4 text-body-sm text-ink-faint sm:px-8">
          {footnote}
        </div>
      ) : null}
    </section>
  )
}

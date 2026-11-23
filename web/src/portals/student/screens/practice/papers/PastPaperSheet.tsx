/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V3 */
/* L4 · past paper sheet (mock PQ). Two ways to do the paper, one button; the decisions are in papersFlow. */
import { useEffect, useRef, useState } from "react"
import { Button } from "@/components/ui/button"
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet"
import type { PastPaper } from "@/lib/practiceHubTypes"
import { radioKeyDown } from "../builder/radioKeys"
import { MonoNumbers } from "../hub/MonoNumbers"
import { subjectDotColor } from "../practiceCopy"
import { ClockIcon, PaperIcon, PrintIcon, SubjectDot } from "../practiceIcons"
import { NOT_PRINTABLE, canDismissSheet, effectiveOption } from "./papersFlow"
import { paperSheetView, type PaperOption } from "./papersModel"
import { usePrintPaper } from "./usePrintPaper"

const OPTION =
  "grid min-h-[60px] grid-cols-[40px_minmax(0,1fr)] items-center gap-3 rounded-2xl px-3 py-2.5 text-start text-on-surface bg-surface-container-lowest shadow-[inset_0_0_0_1.5px_var(--color-outline-variant)] aria-checked:bg-primary-container aria-checked:shadow-[inset_0_0_0_2px_var(--color-primary)] focus-visible:outline-[2.5px] focus-visible:outline-offset-2 focus-visible:outline-primary"

export function PastPaperSheet({
  paper,
  subjectName,
  subjectOrder = [],
  onClose,
}: {
  paper: PastPaper
  subjectName: string
  /** The student's subjects in list order, so the dot is the colour the subject choice drew. */
  subjectOrder?: readonly string[]
  onClose: () => void
}) {
  const view = paperSheetView(paper, subjectName)
  const [chosen, setChosen] = useState<PaperOption>(view.defaultOption)
  const choice = effectiveOption(view, chosen)
  const { print, pending, failure } = usePrintPaper(paper, view)

  // The busy button is disabled while the paper is made, which drops keyboard focus. When the alert
  // appears, focus goes back to the button, or to the chosen option when retrying cannot help.
  const ctaRef = useRef<HTMLButtonElement>(null)
  const checkedRef = useRef<HTMLButtonElement>(null)
  const failed = failure !== null
  const retryable = failure?.retryable ?? true
  useEffect(() => {
    if (failed) (retryable ? ctaRef : checkedRef).current?.focus()
  }, [failed, retryable])

  const blocked = !view.printable || (failure !== null && !failure.retryable)

  return (
    <Sheet open onOpenChange={(open) => (open || !canDismissSheet(pending) ? undefined : onClose())}>
      <SheetContent
        side="adaptive"
        aria-describedby={undefined}
        nativeHeader={
          <div className="flex items-center gap-3">
            <span className="grid size-10 flex-none place-items-center rounded-[13px] bg-success-container text-success-text">
              <PaperIcon size={20} />
            </span>
            <div className="grid gap-0.5">
              <SheetTitle className="text-[22px] font-extrabold text-on-surface">{view.title}</SheetTitle>
              <span className="inline-flex items-center text-[13px] font-medium text-on-surface-variant">
                <SubjectDot color={subjectDotColor(paper.subjectCode, subjectOrder)} />
                <MonoNumbers text={view.sub} />
              </span>
            </div>
          </div>
        }
        nativeBodyClassName="grid gap-3 px-5 pt-1 pb-6"
      >
        <div className="grid gap-3">
          {failure ? (
            <div role="alert" className="rounded-xl bg-error-container px-3 py-2.5 text-[13.5px] font-semibold leading-[1.35] text-on-error-container">
              {failure.message}
            </div>
          ) : null}

          <div
            role="radiogroup"
            aria-label="How do you want to do it"
            onKeyDown={(e) => radioKeyDown(e, (i) => setChosen(view.options[i].key))}
            className="grid gap-2"
          >
            {view.options.map((o) => (
              <button
                key={o.key}
                ref={o.key === choice ? checkedRef : undefined}
                type="button"
                role="radio"
                aria-checked={choice === o.key}
                tabIndex={choice === o.key ? 0 : -1}
                className={OPTION}
                onClick={() => setChosen(o.key)}
              >
                <span className="grid size-10 place-items-center rounded-[13px] text-primary">
                  {o.key === "timed" ? <ClockIcon /> : <PrintIcon />}
                </span>
                <span className="grid gap-0.5">
                  <b className="text-[15px] font-bold">{o.title}</b>
                  <span className="text-[13px] text-on-surface-variant">
                    <MonoNumbers text={o.body} />
                  </span>
                </span>
              </button>
            ))}
          </div>

          <Button
            variant="primary"
            size="lg"
            ref={ctaRef}
            className="min-h-[50px] w-full rounded-[18px] text-[15.5px] shadow-hover disabled:shadow-none"
            disabled={blocked}
            loading={pending}
            onClick={() => void print(choice)}
          >
            {pending ? "Getting it ready…" : "Print paper"}
          </Button>

          <p className="text-[14px] font-medium leading-[1.4] text-pretty text-on-surface-variant">
            {view.printable ? <MonoNumbers text={view.hint} /> : NOT_PRINTABLE}
          </p>
        </div>
      </SheetContent>
    </Sheet>
  )
}

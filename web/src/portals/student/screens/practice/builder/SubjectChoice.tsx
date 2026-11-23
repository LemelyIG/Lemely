/* Hallmark · pre-emit critique: P4 H4 E3 S4 R4 V3 */
/* L4 · subject choice (the mock's `sfilt`). Single choice with no panels, so a radiogroup, not tabs. */
import { subjectDotColor } from "../practiceCopy"
import { SubjectDot } from "../practiceIcons"
import { radioKeyDown } from "./radioKeys"

const CHIP =
  "relative inline-flex min-h-11 flex-none cursor-pointer items-center gap-1.5 rounded-xl px-3.5 text-[13.5px] font-semibold text-on-surface bg-surface-container-lowest shadow-[inset_0_0_0_1.5px_var(--color-outline-variant)] aria-checked:bg-primary aria-checked:text-on-primary aria-checked:shadow-none focus-visible:outline-[2.5px] focus-visible:outline-offset-2 focus-visible:outline-primary"

export function SubjectChoice({
  subjects,
  value,
  onChange,
}: {
  subjects: readonly { code: string; name: string }[]
  value: string
  onChange: (code: string) => void
}) {
  const order = subjects.map((s) => s.code)
  // Roving tabindex: the checked chip is the one Tab stop; arrows move within the group.
  const stop = subjects.some((s) => s.code === value) ? value : subjects[0]?.code
  return (
    // The padding keeps a focus ring inside the scroller, which clips its own overflow.
    <div
      role="radiogroup"
      aria-label="Subject"
      onKeyDown={(e) => radioKeyDown(e, (i) => onChange(subjects[i].code))}
      className="-mx-4 -my-1.5 flex flex-none gap-1.5 overflow-x-auto px-4 py-1.5 [scrollbar-width:none]"
    >
      {subjects.map((s) => (
        <button
          key={s.code}
          type="button"
          role="radio"
          aria-checked={s.code === value}
          tabIndex={s.code === stop ? 0 : -1}
          className={CHIP}
          onClick={() => onChange(s.code)}
        >
          <SubjectDot color={s.code === value ? "currentColor" : subjectDotColor(s.code, order)} className="me-0" />
          {s.name}
        </button>
      ))}
    </div>
  )
}

export { CHIP as SUBJECT_CHIP_CLASS }

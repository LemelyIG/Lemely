/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V3 */
import type { KeyboardEvent } from "react"
import { CountdownPill, SubjectDot } from "@/components/redesign"
import { PageHeading } from "@/components/ui/page-heading"
import { cn } from "@/lib/utils"
import type { FilterChip, HeaderModel } from "./planModel"

const NEXT: Record<string, (i: number, n: number) => number> = {
  ArrowRight: (i, n) => (i + 1) % n,
  ArrowLeft: (i, n) => (i - 1 + n) % n,
  Home: () => 0,
  End: (_, n) => n - 1,
}

/*
 * The subject chips (`.sfilt` / `.pill4`). A tablist with automatic activation:
 * the arrows move focus and select, and only the selected chip is in the tab
 * order. On a selected (navy) chip the subject dot gets a light ring, so a navy
 * subject dot never vanishes into the chip.
 */
export function SubjectFilter({
  filters,
  onFilter,
  inline = false,
}: {
  filters: FilterChip[]
  onFilter: (code: string | null) => void
  inline?: boolean
}) {
  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const step = NEXT[e.key]
    if (!step) return
    const tabs = [...e.currentTarget.querySelectorAll<HTMLButtonElement>('[role="tab"]')]
    const at = tabs.indexOf(document.activeElement as HTMLButtonElement)
    if (at < 0) return
    e.preventDefault()
    const to = step(at, tabs.length)
    tabs[to]?.focus()
    onFilter(filters[to]?.code ?? null)
  }
  return (
    <div
      role="tablist"
      aria-label="Subject"
      onKeyDown={onKeyDown}
      className={cn(
        // The padding is the room the focus ring needs inside the clip; the negative margins give back what it adds, so the layout is the one it was.
        "-my-1 flex gap-1.5 overflow-x-auto py-1.5 scroll-px-1.5 [scrollbar-width:none]",
        inline ? "-mx-1.5 min-w-0 px-1.5" : "-mx-4 flex-none px-4",
      )}
    >
      {filters.map((f) => (
        <button
          key={f.code ?? "all"}
          type="button"
          role="tab"
          aria-selected={f.selected}
          aria-controls="plan-list"
          tabIndex={f.selected ? 0 : -1}
          onClick={() => onFilter(f.code)}
          className={cn(
            "relative inline-flex min-h-10 flex-none items-center rounded-xl px-3.5 font-sans text-[13.5px] font-semibold whitespace-nowrap",
            "before:absolute before:inset-x-0 before:-inset-y-0.5 before:content-['']",
            "transition-[background-color,box-shadow] duration-150 ease-out motion-reduce:transition-none",
            "focus-visible:outline-[2.5px] focus-visible:outline-offset-2 focus-visible:outline-primary",
            f.selected
              ? "bg-primary text-on-primary [&_.rd-dot]:shadow-[0_0_0_1.5px_var(--color-on-primary)]"
              : "bg-surface-container-lowest text-on-surface shadow-[inset_0_0_0_1.5px_var(--color-outline-variant)] hover:bg-surface-container-high",
          )}
        >
          {f.code !== null ? <SubjectDot subject={f.code} /> : null}
          {f.label}
        </button>
      ))}
    </div>
  )
}

/* The exam pill goes to the exam dates, through the kit's own link variant. */
const EXAM_DATES = "/student/announcements"

/** `.sjhd` on phone and tablet, `.dtop` on desktop. The back control is the shell's. */
export function PlanHeader({
  header,
  wide,
  now,
  onFilter,
}: {
  header: HeaderModel
  wide: boolean
  now: Date
  onFilter: (code: string | null) => void
}) {
  const title = (size: string) => (
    <PageHeading repeatsTitle className={cn("font-display leading-[1.1] font-extrabold tracking-[-0.03em] text-balance text-primary", size)}>
      {header.title}
    </PageHeading>
  )
  const sub = <span className="font-sans text-[13px] font-medium text-on-surface-variant">{header.sub}</span>
  const pill = header.examDate ? (
    <span className="shrink-0">
      <CountdownPill examDate={header.examDate} now={now} to={EXAM_DATES} />
    </span>
  ) : null
  const filter = header.filters.length > 0
  if (wide) {
    return (
      <header className="flex items-center gap-5 pb-2">
        <div className="grid min-w-0 flex-1 gap-0.5">
          {title("text-[32px]")}
          {sub}
        </div>
        {filter ? <SubjectFilter filters={header.filters} onFilter={onFilter} inline /> : null}
        {pill}
      </header>
    )
  }
  return (
    <header className="flex flex-col gap-4">
      <div className="flex items-center gap-2.5">
        <div className="grid min-w-0 flex-1 gap-0.5">
          {title("text-[28px]")}
          {sub}
        </div>
        {pill}
      </div>
      {filter ? <SubjectFilter filters={header.filters} onFilter={onFilter} /> : null}
    </header>
  )
}

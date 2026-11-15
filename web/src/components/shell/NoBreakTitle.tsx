/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V3 */
import { titleRuns } from "./shellModel"

const WEEKDAY_BEFORE = /\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) $/

/**
 * A notification title with its dates held together: "12 Nov" and "2026/27"
 * never break inside the token, and a weekday before a date stays with it (in the
 * text face), so a long title wraps before "Thu 12 Nov", not in it. `mono` also sets the date in the data face (the bell panel does; the
 * Notifications pages keep one voice).
 */
export function NoBreakTitle({ title, mono = false }: { title: string; mono?: boolean }) {
  const runs = titleRuns(title)
  return (
    <>
      {runs.map((run, i) => {
        if (!run.mono) {
          // A weekday that leads into the next date moves into that date's no-wrap span, still in the text face.
          const next = runs[i + 1]
          return next?.mono ? run.text.replace(WEEKDAY_BEFORE, "") : run.text
        }
        const lead = runs[i - 1]?.text.match(WEEKDAY_BEFORE)?.[0] ?? ""
        return (
          <span key={i} className="whitespace-nowrap">
            {lead}
            <span className={mono ? "font-mono font-semibold tabular-nums" : undefined}>{run.text}</span>
          </span>
        )
      })}
    </>
  )
}

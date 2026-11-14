/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V3 */
import { titleRuns } from "./shellModel"

/**
 * A notification title with its dates held together: "12 Nov" and "2026/27"
 * never break inside the token, so a long title wraps before the date, not in
 * it. `mono` also sets the date in the data face (the bell panel does; the
 * Notifications pages keep one voice).
 */
export function NoBreakTitle({ title, mono = false }: { title: string; mono?: boolean }) {
  return (
    <>
      {titleRuns(title).map((run, i) =>
        run.mono ? (
          <span key={i} className={mono ? "font-mono font-semibold tabular-nums whitespace-nowrap" : "whitespace-nowrap"}>
            {run.text}
          </span>
        ) : (
          run.text
        ),
      )}
    </>
  )
}

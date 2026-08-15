/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import { cn } from "@/lib/utils"
import type { StatCard as StatCardData } from "../data"

/*
 * The tone keys are the wire's, not this file's. `valueTone`/`footTone` arrive
 * from `StatCardDTO` (`lemely/web/schemas_teacher.py`), chosen by the backend
 * from computed thresholds — "err" when a class actually has students at risk,
 * "t1" when it does not. Renaming them to Study Notebook names here would be a
 * cross-language contract change for a cosmetic gain, so the build-era names
 * stay on the wire and this table is where they become tokens. That is what a
 * mapping table is for.
 */
const VALUE_TONE = {
  t1: "text-ink",
  accent: "text-accent-ink",
  err: "text-err",
} as const

const FOOT_TONE = {
  t2: "text-ink-muted",
  ok: "text-ok",
  err: "text-err",
} as const

/**
 * The four-up metric card used on Overview, Classes and Mark schemes.
 *
 * The big number is `data-lg` — JetBrains Mono, tabular — and not the
 * `display-lg` Newsreader rung it used to carry. DESIGN.md §4 gives the data
 * face "all scores, grades, marks, XP" and names `data-lg` as "the big number:
 * a score, a predicted grade"; every value this card ever renders is a count
 * or a percentage produced by `str(round(...))` on the server, so it is that
 * number and nothing else.
 *
 * This is D4.2's finding on the teacher side. There it was `MarkDisplay`
 * setting a student's mark and grade in the heading face; the same figures in
 * the same product were being set two different ways depending on which portal
 * you were looking at, which is precisely what a shared type scale exists to
 * stop. Tabular numerals also matter more here than on a hero: four of these
 * sit in one row and their digits should line up column-wise.
 */
export function StatCard({ stat }: { stat: StatCardData }) {
  return (
    <div className="bg-paper-raised border border-rule rounded-lg px-6 py-5">
      <div className="text-eyebrow text-ink-faint">{stat.k}</div>
      <div className="flex items-baseline gap-1.5 mt-2">
        <div className={cn("text-data-lg", VALUE_TONE[stat.valueTone ?? "t1"])}>
          {stat.v}
        </div>
        {stat.unit ? <div className="text-body-sm text-ink-muted">{stat.unit}</div> : null}
      </div>
      {stat.foot ? (
        <div className={cn("text-data-sm mt-2", FOOT_TONE[stat.footTone ?? "t2"])}>
          {stat.foot}
        </div>
      ) : null}
    </div>
  )
}

/* Hallmark · pre-emit critique: P5 H4 E4 S5 R4 V4 */
import { Card } from "@/components/ui/card"
import type { McqCell } from "./data"

/**
 * The hero's live example: `heroExample` marked against `mcq`, rendered as a
 * real component rather than a picture of one. BUILD/BRAND.md §2 bans the
 * whole "screenshot of the product" move (fake browser chrome, div-drawn UI,
 * photos, generated images), because a mark is a claim and a picture of one
 * cannot be audited the way the component itself can. This IS the product's
 * result view, at hero scale.
 *
 * `marketing.test.ts`'s "the hero example card cannot contradict itself"
 * block pins three facts about `example`/`cells` as one derived truth: 40
 * cells, exactly 2 dropped, the score and the note both saying so. Nothing
 * in this component recomputes any of that; it only renders what
 * `data.ts`'s `heroExample`/`mcq` already derived from one source array.
 *
 * `exampleLabel` ("Example") sits inside the card next to the provenance
 * line, not as a caption underneath the score, so a reader cannot see the
 * 38/40 without also seeing the word that keeps it honest: the product has
 * no customer whose result this could be (P4.9's finding).
 *
 * The note is BUILD/BRAND.md §2's marginalia territory in its narrowest
 * sense, "the note beside the work, not on top of it": set in `--font-hand`
 * (Caveat) and placed beside the grid rather than stacked under it or
 * overlaid on it, the way a teacher's aside sits in the margin next to what
 * it is about. It stays in the accessibility tree with no `aria-hidden` —
 * unlike the close section's purely decorative aside, this sentence is the
 * one piece of context a reader actually needs to make sense of the score.
 */
export function HeroExampleCard({
  example,
  cells,
}: {
  example: {
    exampleLabel: string
    meta: string
    score: string
    max: string
    grade: string
    note: string
  }
  cells: McqCell[]
}) {
  return (
    <Card className="p-6">
      <div className="flex items-center justify-between gap-3">
        <div className="text-data-sm flex items-center gap-2 text-ink-muted">
          <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-ok" aria-hidden="true" />
          {example.meta}
        </div>
        <span className="text-label-sm shrink-0 rounded-full bg-paper-sunk px-2.5 py-1 text-ink-faint">
          {example.exampleLabel}
        </span>
      </div>

      <div className="mt-5 flex items-baseline gap-3.5">
        {/*
          The mark and the grade are data, so they are set in the data face
          (mono, tabular), not the display face — DESIGN.md §4's rule for
          any figure a reader scans rather than reads.
        */}
        <div className="text-data-lg text-ink">
          {example.score}
          <span className="text-data-md text-ink-faint">{example.max}</span>
        </div>
        <div className="text-data-lg text-accent">{example.grade}</div>
      </div>

      <div className="mt-5 flex flex-col gap-4 border-t border-rule pt-5 sm:flex-row sm:items-start sm:gap-5">
        {/*
          Forty cells, two dropped. `aria-hidden` on the grid itself: forty
          individually-labelled squares is forty stops for a screen-reader
          user to walk through a decorative picture of a result the note
          beside it already gives them in words.

          `mark-correct`/`mark-wrong`, not `ok`/`accent`: these cells are
          marked answers, which is exactly what §3's marking tokens name.
        */}
        {/*
          `sm:flex-1`, not `shrink-0`: inside the `sm:flex-row` layout below,
          a flex item with no explicit width sizes its `1fr` grid tracks
          against its own max-content, and every cell here is an empty div
          with zero intrinsic content, so the whole grid collapsed to a
          sliver a few pixels wide, gap-only. `flex-1` gives it a definite
          basis to lay ten real columns out against; the note takes a fixed
          column instead (`sm:max-w-36` below) so the two never fight over
          the same space.
        */}
        <div className="grid grid-cols-10 gap-[5px] sm:w-auto sm:flex-1" aria-hidden="true">
          {cells.map((q) => (
            <div
              key={q.id}
              title={q.title}
              className={`aspect-square rounded-[5px] border ${
                q.correct
                  ? "border-mark-correct/25 bg-mark-correct-bg"
                  : "border-mark-wrong/30 bg-mark-wrong-bg"
              }`}
            />
          ))}
        </div>

        <p className="text-hand text-pretty text-ink-muted sm:max-w-36 sm:shrink-0 sm:border-s sm:border-rule sm:ps-4">
          {example.note}
        </p>
      </div>
    </Card>
  )
}

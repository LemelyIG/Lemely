/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V3 */
import { Link } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { BoundaryBar } from "@/components/ui/boundary-bar"
import { directionsIntro, railTicks } from "../data"

/*
 * Directions (isDirections). An internal gallery of the three result-header
 * treatments that were considered: A (ledger), B (boundary rail), C (two
 * sentences on a dark panel).
 *
 * ────────────────────────────────────────────────────────────────────────────
 * THIS SCREEN IS INTERNAL, AND IT IS MOUNTED IN THE PRODUCT
 * ────────────────────────────────────────────────────────────────────────────
 * It is reachable by any signed-in student at `/student/directions`. D1.1
 * removed its nav entry for exactly the right reason ("means nothing to a
 * fifteen-year-old") and kept the route, so it is invisible rather than gone.
 * That is the same shape as the kit preview, which Phase 2 moved to
 * `web/dev-previews/` behind its own Vite entry precisely so the product could
 * never ship it.
 *
 * **DECISION D4.8** asks whether this follows it there. It is not resolved as
 * this is written, so the screen is migrated to the Study Notebook in place
 * rather than moved unattended: a gallery that has to argue for design
 * decisions in the old palette is not much of an argument, and moving a file
 * the audit script visits by path is not a change to make while the question
 * of whether it should exist is still open.
 *
 * WHAT CHANGED BEYOND THE PALETTE
 * -------------------------------
 * The gallery had gone stale in a way worth recording, because a design
 * gallery that misdescribes the design is worse than no gallery:
 *
 *   - Every heading here was `font-serif`, which D4.1 established is **not a
 *     token**. It resolved to Georgia, the browser's default serif, so the
 *     screen whose entire job is to show typographic treatments was showing
 *     them in the wrong face.
 *   - Direction C is a dark panel, and DESIGN.md §3.1 now rules that out in as
 *     many words: `--paper-inverse` is "the one dark surface permitted, for a
 *     single proof/close band on marketing only. **Never a dark section inside
 *     an app screen.**" C is therefore not an option any more, and the gallery
 *     was still offering it as the "warmest" one. It stays on the page,
 *     labelled as ruled out, because deleting the alternative is how the next
 *     person proposes it again.
 *   - Its "Show the marking detail" control was a hand-rolled `<button>` with
 *     its own border recipe, on a screen demonstrating the design system.
 */

/*
 * Direction B's boundary example uses `BoundaryBar` (C-3) over the old
 * `BoundaryRail` (deleted — hardcoded literal-color gradient, superseded per
 * docs/COMPONENT_CATALOGUE.md). `railTicks`' fixed grade/percentage pairs are
 * illustrative only here (this screen is a static design gallery, not live
 * data) so they're reused as-is for `boundaries`, scored out of 100.
 */
const directionsBoundaries = railTicks.map((t) => ({ grade: t.g, minMark: t.left }))

function DirectionLabel({
  letter,
  title,
  note,
  status,
}: {
  letter: string
  title: string
  note: string
  /** What became of this direction. Rendered, not just commented. */
  status: "shipped" | "ruled-out"
}) {
  return (
    <div className="flex flex-wrap items-baseline gap-x-2.5 gap-y-1">
      <span className="text-data-sm rounded-md bg-paper-inverse px-2 py-1 text-ink-inverse">
        {letter}
      </span>
      <span className="text-label text-ink">{title}</span>
      <span className="text-body-sm text-ink-muted">{note}</span>
      {/*
        The status a reader of a gallery actually needs, and the thing this
        screen did not say anywhere: which of these three is the product. It
        was in the intro paragraph as prose and nowhere on the treatments
        themselves, so scrolling to C told you nothing about C.
      */}
      <span
        className={`text-label-sm rounded-full px-2.5 py-1 ${
          status === "shipped" ? "bg-ok-wash text-ok" : "bg-paper-sunk text-ink-faint"
        }`}
      >
        {status === "shipped" ? "In the product" : "Ruled out"}
      </span>
    </div>
  )
}

export function Directions() {
  return (
    <div className="lm-screen flex flex-col gap-7">
      <div>
        {/* The gallery's own title, as an <h1> — this route had no
            audit-registry entry until P5.11, so its missing page heading had
            never been looked at. */}
        <h1 className="text-display-lg text-ink">{directionsIntro.title}</h1>
        <p className="text-body-md lm-prose mt-3 text-pretty text-ink-muted">
          The result header is the emotional moment of the product, the screen a student opens
          after a mock. The app uses <Link to="/student/result">A and B together</Link>: the ledger
          reading, with the boundary rail underneath it.
        </p>
        <p className="text-body-sm lm-prose mt-2 text-pretty text-ink-faint">
          Internal reference. This page is not linked from anywhere a student navigates.
        </p>
      </div>

      <div className="flex flex-col gap-5">
        <DirectionLabel
          letter="A"
          title="Ledger, marks first, boundaries beside them"
          note="calm, teacherly, reads like a marked script"
          status="shipped"
        />
        <Card className="px-7 py-6">
          <div className="text-data-sm text-ink-muted">
            0625 / Paper 1 Variant 2 / May-June 2020
          </div>
          <div className="text-display-md mt-2.5 text-ink">Thirty-eight out of forty.</div>
          <div className="mt-5 flex flex-wrap items-end gap-6">
            <div>
              <div className="text-eyebrow text-ink-faint">Marks</div>
              {/* The mark and the grade in the data face, not the display
                  face — DESIGN.md §4, and D4.2's finding on the real result
                  screen, which had the same two figures in the same wrong
                  place. A gallery demonstrating the treatment has to get this
                  right or it teaches the mistake. */}
              <div className="text-data-lg mt-1.5 text-ink">
                38<span className="text-data-md text-ink-faint">/40</span>
              </div>
            </div>
            <div>
              <div className="text-eyebrow text-ink-faint">Grade</div>
              <div className="text-data-lg mt-1.5 text-accent">A</div>
            </div>
            {/* `margin-rule` (§8), not a hand-written `border-s` plus padding:
                it is the project's own hairline-in-the-margin utility and it
                is already RTL-safe by construction. */}
            <div className="text-body-sm margin-rule max-w-[44ch] flex-1 text-pretty text-ink-muted">
              Above the 2020 A boundary by 15 marks. Two dropped, both single-mark recall.
            </div>
          </div>
        </Card>

        <DirectionLabel
          letter="B"
          title="Boundary rail, where you sit on the curve"
          note="the grade becomes a position, not a verdict"
          status="shipped"
        />
        <Card className="px-7 py-6">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <div className="text-display-sm text-ink">Physics, Paper 1</div>
            <div className="text-data-sm text-ink-muted">2020 boundaries, 95%</div>
          </div>
          <BoundaryBar score={95} maxScore={100} boundaries={directionsBoundaries} />
          <p className="text-body-sm mt-3 text-pretty text-ink-muted">
            Fifteen marks of headroom above A. Even a bad day keeps you in the band.
          </p>
        </Card>

        <DirectionLabel
          letter="C"
          title="Two sentences, the grade is secondary"
          note="warmest, and no longer available: DESIGN.md §3.1 rules out a dark panel inside an app screen"
          status="ruled-out"
        />
        {/*
          Rendered on `--paper-inverse`, the token, rather than `bg-ink`, which
          is the *text* colour and was being used as a background: close enough
          in value to look right and wrong by name, so changing the ink colour
          would have repainted this panel.

          Keeping the treatment visible while marking it ruled out is
          deliberate. It is a real option for a future Read-lane screen or a
          marketing band, and the reason it cannot be a result header is a
          system rule rather than a judgement about the design.
        */}
        <div className="rounded-xl bg-paper-inverse px-8 py-9">
          <div className="text-display-lg max-w-[26ch] text-ink-inverse">
            You are marking at grade A, and the only two marks you lost were the same kind of
            question.
          </div>
          <div className="mt-7 flex flex-wrap items-center gap-6">
            <div className="text-data-sm text-ink-inverse/60">0625/12, 38/40, 95%</div>
            <div className="flex-1" />
            {/* The kit's Button, not a hand-rolled one with its own border
                recipe — on the screen whose subject is the design system. */}
            <Button variant="secondary" size="sm" className="shrink-0">
              Show the marking detail
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}

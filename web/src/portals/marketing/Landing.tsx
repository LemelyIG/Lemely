/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import { useNavigate } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Reveal } from "@/components/ui/reveal"
import {
  heroExample,
  landingClose,
  landingHero,
  landingProofIntro,
  loopIntro,
  loopSteps,
  mcq,
  pillars,
  pricing,
  pricingPlaceholder,
  proof,
} from "./data"

/*
 * The public landing page. Persuade lane (DESIGN.md §2): full-bleed warm
 * paper, 96–128px between sections, one idea per section, a 1280px container,
 * and display type doing the work. Dials per REDESIGN-MISSION §3.3:
 * VARIANCE 7 / MOTION 7 / DENSITY 4 — the loosest and most expressive row in
 * the product, and the only surface that turns section spacing up to
 * `section-xl`.
 *
 * Section rhythm, in §2's order: hero → proof → the loop → who it serves →
 * plans → close.
 *
 * WHAT THIS FILE IS NOT ALLOWED TO DO
 * -----------------------------------
 * Read `./data.ts`'s header before editing a single string here. Six separate
 * fabrications were live on this page after DESIGN-AUDIT C1/C2/C3 had been
 * closed, because that pass deleted the *numbers* and left the *sentences*.
 * Every claim now carries the module that implements it, in a comment beside
 * it. A new sentence without one does not ship.
 *
 * The plans section renders `pricingPlaceholder` while `pricing` is empty. It
 * is empty on purpose: see the C2 note in ./data.ts. Do not repopulate it with
 * example tiers to "fill the space" — the placeholder stating that pricing is
 * undecided is the honest render, and inventing a price is the specific defect
 * that note exists to prevent recurring.
 */

/**
 * A page section at marketing rhythm.
 *
 * The spacing rungs are the reason this is a component rather than a repeated
 * class string: §13's knob for this lane is `section-lg`…`section-xl`, and six
 * hand-written paddings is how a page ends up with five different section
 * gaps and no one able to say which was intended.
 *
 * ONE container width, and the first draft got this wrong in a way the
 * captures made obvious: it took a `wide` prop, so the hero and the proof band
 * sat in `max-w-marketing` (1280) while the loop, the pillars and the close
 * sat in `max-w-app` (1200). The page had two left edges 40px apart and jogged
 * between them on alternate sections. §13 gives the Persuade lane one
 * container, 1280px, and a page with two of them reads as a page nobody
 * aligned.
 */
function Section({
  children,
  className = "",
  id,
}: {
  children: React.ReactNode
  className?: string
  id?: string
}) {
  return (
    <section
      id={id}
      className={`mx-auto w-full max-w-marketing px-page-mobile md:px-page-tablet lg:px-page-desktop ${className}`}
    >
      {children}
    </section>
  )
}

/**
 * The hero's secondary CTA scrolls here rather than navigating. Named so the
 * button and the section cannot drift apart into a scroll to nothing, which
 * fails silently: `getElementById` returning null does nothing at all, and a
 * button that does nothing at all is indistinguishable from a slow one.
 */
const SERVES_SECTION_ID = "who-it-serves"

/** Uppercase kicker above a section title. §4.2's `eyebrow` rung. */
function Eyebrow({ children }: { children: React.ReactNode }) {
  return <div className="text-eyebrow text-accent">{children}</div>
}

export function Landing() {
  const navigate = useNavigate()

  return (
    <div className="flex flex-col gap-section-lg pb-section-lg pt-section md:gap-section-xl md:pt-section-lg">
      {/* ── Hero ─────────────────────────────────────────────────────────── */}
      <Section>
        {/*
          Asymmetric by design (§2: "asymmetric and deliberately broken
          symmetry"), and the ratio is deliberate: the copy column carries the
          argument and the card carries the evidence, so the copy gets the
          wider share. Collapses to one column at `lg`, above the 1180px the
          old page used, because the card stops being readable beside the
          hero well before the grid technically stops fitting.
        */}
        <div className="grid grid-cols-1 items-center gap-10 lg:grid-cols-[1.1fr_1fr] lg:gap-14">
          <Reveal>
            <Eyebrow>{landingHero.eyebrow}</Eyebrow>
            {/*
              The page's heading, and an <h1>. It rendered as a plain <div>
              until P5.11, which went unnoticed because this route had no
              audit-registry entry.

              `display-hero` is §4.2's top rung and this is the one surface in
              the product entitled to it (§13: the display-rung knob runs
              `display-md`…`display-hero`, and only marketing turns it all the
              way up). It drops to 38px under 768px, from the rung itself, so
              there is no per-screen font size here.
            */}
            <h1 className="text-display-hero mt-5 text-ink text-balance">
              {landingHero.titleTop}
              <br />
              {landingHero.titleBottom}
            </h1>
            <p className="text-body-lg mt-6 max-w-[52ch] text-pretty text-ink-muted">
              {landingHero.body}
            </p>
            {/*
              `flex-wrap`, not a narrower button: Button carries
              `whitespace-nowrap`, so at 380px the secondary CTA cannot shrink
              and instead ran to x=409 — a horizontal-scroll violation, which
              `check_ui_gates.py` fails the build on (zero tolerated). Wrapping
              stacks the two CTAs and keeps both labels intact; truncating
              "For centres and teachers" would hide who the link is for.
            */}
            <div className="mt-8 flex flex-wrap gap-3">
              {/*
                Both CTAs go to /login rather than deep into the app. The old
                page sent "Mark a paper" straight to `/student/correct`, which
                for a signed-out visitor — every visitor this page now has —
                is a bounce to /login with the destination lost. Sending them
                to the sign-in they were always going to need is one step, not
                two, and it is the step that is honest about what happens next.
              */}
              <Button variant="primary" size="lg" onClick={() => navigate("/login")}>
                {landingHero.primaryCta}
              </Button>
              {/*
                The secondary CTA goes to the teacher case on this page, not
                to the same sign-in the primary already offers. Two buttons
                side by side pointing at one destination is not a choice, and
                "For centres and teachers" promises something specific: the
                part of the page written for them. There is no separate
                centres product to link to, and inventing a route to one is
                the fabrication this surface spent its whole audit removing.
              */}
              <Button
                variant="secondary"
                size="lg"
                onClick={() => {
                  document
                    .getElementById(SERVES_SECTION_ID)
                    ?.scrollIntoView({ behavior: "smooth", block: "start" })
                }}
              >
                {landingHero.secondaryCta}
              </Button>
            </div>
            <p className="text-body-sm mt-5 text-ink-faint">{landingHero.footnote}</p>
          </Reveal>

          <Reveal delay={120}>
            {/*
              No shadow. `Card`'s own docstring says "no shadow, ever"
              (DESIGN.md §7 — depth here is tonal layering and hairlines, not
              elevation), and the build-era version of this hero attached a
              60px drop shadow to it anyway, which is the single most
              generic-SaaS gesture on the page and precisely the anti-reference
              §4 names.
            */}
            <Card className="p-6">
              <div className="flex items-center justify-between gap-3">
                <div className="text-data-sm flex items-center gap-2 text-ink-muted">
                  <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-ok" aria-hidden="true" />
                  {heroExample.meta}
                </div>
                {/*
                  The label that makes this card honest. A hero showing 38/40
                  reads as somebody's result, and the product has no customers
                  whose result it could be (PRODUCT.md's must-not-fabricate
                  list). It sits *in* the card, beside the provenance line,
                  rather than as a caption below the number, so it cannot be
                  read separately from the figure it qualifies.
                */}
                <span className="text-label-sm shrink-0 rounded-full bg-paper-sunk px-2.5 py-1 text-ink-faint">
                  {heroExample.exampleLabel}
                </span>
              </div>

              <div className="mt-5 flex items-baseline gap-3.5">
                {/*
                  The mark and the grade are data, so they are set in the data
                  face, not the display face. This is D4.2's finding on the
                  student's own result screen (`MarkDisplay`), where the two
                  figures a reader looks at first were in Newsreader while
                  DESIGN.md §4 puts them in the mono face. The same two figures
                  were in the same wrong face here.
                */}
                <div className="text-data-lg text-ink">
                  {heroExample.score}
                  <span className="text-data-md text-ink-faint">{heroExample.max}</span>
                </div>
                <div className="text-data-lg text-accent">{heroExample.grade}</div>
              </div>

              {/*
                Forty cells, two of them dropped. `aria-hidden` with a text
                summary beside it: forty individually-labelled squares is forty
                stops for a screen-reader user to walk through for a decorative
                picture of a result the sentence below already gives them.
              */}
              <div className="mt-5 grid grid-cols-10 gap-[5px]" aria-hidden="true">
                {mcq.map((q) => (
                  <div
                    key={q.id}
                    title={q.title}
                    /*
                      `mark-correct`/`mark-wrong`, not `ok`/`accent`. These
                      cells are marked answers, which is exactly what §3's
                      marking tokens name, and the build-era grid used a raw
                      `oklch(0.96 0.02 150)` fill with a hand-picked green
                      border — a token-discipline gate failure (§3.2 item 13)
                      that also meant the one place in the product showing a
                      marked script to a stranger used a different green from
                      every place showing one to a student.
                    */
                    className={`aspect-square rounded-[5px] border ${
                      q.correct
                        ? "border-mark-correct/25 bg-mark-correct-bg"
                        : "border-mark-wrong/30 bg-mark-wrong-bg"
                    }`}
                  />
                ))}
              </div>

              <p className="text-body-sm mt-5 border-t border-rule pt-4 text-pretty text-ink-muted">
                {heroExample.note}
              </p>
            </Card>
          </Reveal>
        </div>
      </Section>

      {/* ── Proof ────────────────────────────────────────────────────────── */}
      <Section>
        <Reveal>
          {/*
            `--paper-inverse`, which §3.1 defines as "the one dark surface
            permitted, for a single proof/close band on marketing only". The
            build-era band used `bg-ink`, the *text* token, as a background:
            close enough in value to look right and wrong by name, so a future
            change to the ink colour would have repainted a panel.

            One such band on the page. §3.2 item 8 bans dark sections that
            break the warm paper page, and the exception is this, once.
          */}
          <div className="grid grid-cols-1 items-center gap-10 rounded-xl bg-paper-inverse p-8 md:p-11 lg:grid-cols-2 lg:gap-14">
            <div>
              <h2 className="text-display-lg text-ink-inverse text-balance">
                {landingProofIntro.title}
              </h2>
              <p className="text-body-md mt-4 max-w-[54ch] text-pretty text-ink-inverse/75">
                {landingProofIntro.body}
              </p>
            </div>
            {/*
              One column, not two. Three stats in a two-column grid leaves the
              third alone beside an empty cell, which the capture round showed
              as a hole in the middle of the one band on the page that has to
              look considered. Stacked, they read as a short list of facts,
              which is what they are.
            */}
            <div className="grid grid-cols-1 gap-4">
              {proof.map((p, i) => (
                <Reveal key={p.l} delay={80 * i}>
                  <div className="h-full rounded-lg border border-ink-inverse/15 p-5">
                    {/*
                      Every one of these is a constant from the Python source
                      (see ./data.ts), so they are figures, and figures are set
                      in the data face. The build-era band set them in the
                      display serif, which is where a marketing statistic goes
                      when nobody is quite sure it is a number.
                    */}
                    <div className="text-data-lg text-ink-inverse">{p.n}</div>
                    <div className="text-body-sm mt-2 text-pretty text-ink-inverse/70">{p.l}</div>
                  </div>
                </Reveal>
              ))}
            </div>
          </div>
        </Reveal>
      </Section>

      {/* ── The loop ─────────────────────────────────────────────────────── */}
      <Section>
        <Reveal>
          <Eyebrow>How it goes</Eyebrow>
          <h2 className="text-display-xl mt-4 text-ink text-balance">{loopIntro.title}</h2>
          <p className="text-body-lg mt-4 max-w-[62ch] text-pretty text-ink-muted">
            {loopIntro.body}
          </p>
        </Reveal>
        {/*
          `ruled-bg` was on this container in the first draft and is gone,
          because it drew nothing: the three cards are opaque `--paper-raised`
          and cover every pixel of their parent, so the ruled texture existed
          in the class list and nowhere on screen. That is the same shape as
          the classes `utilityExistence.test.ts` was written for, one step
          along — the rule is emitted, it is simply painted over — and the
          honest fix for a texture nobody can see is to remove it rather than
          to keep it as a claim in the markup.

          The notebook layer on this page is therefore the grain (everywhere,
          0.035), the hairline grid here, and the handwritten aside at the
          close. §8's restraint rule reads that as enough.
        */}
        <div className="mt-10 grid grid-cols-1 gap-px overflow-hidden rounded-xl border border-rule bg-rule md:grid-cols-3">
          {loopSteps.map((s, i) => (
            <Reveal key={s.step} delay={90 * i} className="h-full">
              <div className="flex h-full flex-col gap-3 bg-paper-raised p-7">
                <div className="text-data-md text-accent">{s.step}</div>
                <h3 className="text-display-sm text-ink">{s.title}</h3>
                <p className="text-body-sm text-pretty text-ink-muted">{s.body}</p>
              </div>
            </Reveal>
          ))}
        </div>
      </Section>

      {/* ── Who it serves ────────────────────────────────────────────────── */}
      <Section id={SERVES_SECTION_ID}>
        <Reveal>
          <Eyebrow>Who it serves</Eyebrow>
          <h2 className="text-display-xl mt-4 text-ink text-balance">
            One engine, three people served
          </h2>
          <p className="text-body-lg mt-4 max-w-[62ch] text-pretty text-ink-muted">
            The same corrected paper becomes a study plan for the student, a teaching signal for
            the teacher, and a plain answer for the parent who asks how she is doing.
          </p>
        </Reveal>
        <div className="mt-10 grid grid-cols-1 gap-5 lg:grid-cols-3">
          {pillars.map((p, i) => (
            <Reveal key={p.kicker} delay={90 * i} className="h-full">
              {/*
                `h-full` on the reveal and `flex-col` here, with the bullet
                block pushed down by `mt-auto`: §12 asks siblings to align
                their titles and pin their footers rather than being forced to
                equal height by a grid row. The three bodies are different
                lengths and always will be.
              */}
              <Card className="flex h-full flex-col gap-3 p-7">
                <div className="text-eyebrow text-accent">{p.kicker}</div>
                <h3 className="text-display-sm text-ink">{p.title}</h3>
                <p className="text-body-sm text-pretty text-ink-muted">{p.body}</p>
                <ul className="mt-auto flex list-none flex-col gap-2.5 border-t border-rule pt-4">
                  {p.bullets.map((b) => (
                    <li key={b} className="text-body-sm flex items-start gap-2.5 text-ink-muted">
                      <span
                        className="mt-[9px] h-[5px] w-[5px] shrink-0 rounded-full bg-accent"
                        aria-hidden="true"
                      />
                      <span className="text-pretty">{b}</span>
                    </li>
                  ))}
                </ul>
              </Card>
            </Reveal>
          ))}
        </div>
      </Section>

      {/* ── Plans ────────────────────────────────────────────────────────── */}
      <Section>
        <Reveal>
          <Eyebrow>Plans</Eyebrow>
          <h2 className="text-display-xl mt-4 text-ink text-balance">What it costs</h2>
        </Reveal>
        {pricing.length === 0 ? (
          <Reveal delay={80}>
            <Card className="mt-8 flex max-w-[560px] flex-col gap-3 p-7">
              <div className="text-eyebrow text-ink-faint">{pricingPlaceholder.label}</div>
              <div className="text-display-sm text-ink">{pricingPlaceholder.title}</div>
              <p className="text-body-md text-pretty text-ink-muted">{pricingPlaceholder.body}</p>
            </Card>
          </Reveal>
        ) : (
          <div className="mt-8 grid grid-cols-1 gap-5 lg:grid-cols-3">
            {pricing.map((p, i) => (
              <Reveal key={p.name} delay={90 * i} className="h-full">
                <Card className="flex h-full flex-col gap-3 p-7">
                  <div className="text-label text-ink">{p.name}</div>
                  <div className="text-data-lg text-ink">{p.price}</div>
                  <p className="text-body-sm text-pretty text-ink-muted">{p.who}</p>
                  <div className="mt-2 flex flex-col gap-2">
                    {p.feats.map((f) => (
                      <div key={f} className="text-body-sm text-ink-muted">
                        {f}
                      </div>
                    ))}
                  </div>
                  {/*
                    The kit's Button, not a hand-rolled <button> with its own
                    border recipe. The build-era version wrote three variant
                    branches inline, one of which set a raw `oklch()` border —
                    a token-discipline gate failure (§3.2 item 13) sitting in
                    the one section that also carried the invented prices.
                  */}
                  <Button
                    variant={p.ctaAccent ? "primary" : "secondary"}
                    className="mt-auto w-full"
                    onClick={() => navigate("/login")}
                  >
                    {p.cta}
                  </Button>
                </Card>
              </Reveal>
            ))}
          </div>
        )}
      </Section>

      {/* ── Close ────────────────────────────────────────────────────────── */}
      <Section>
        <Reveal>
          <div className="flex flex-col items-start gap-5 border-t border-rule pt-section-sm">
            <h2 className="text-display-xl text-ink text-balance">{landingClose.title}</h2>
            <p className="text-body-lg max-w-[52ch] text-pretty text-ink-muted">
              {landingClose.body}
            </p>
            <div className="flex flex-wrap items-center gap-5">
              <Button variant="primary" size="lg" onClick={() => navigate("/login")}>
                {landingClose.cta}
              </Button>
              {/*
                Marginalia (§8), and the only handwritten text on the page.
                `aria-hidden`: §4.1 restricts this face to things that may be
                lost without cost, and this is a nudge beside a button whose
                own label already says what to do.
              */}
              <span className="text-hand text-ink-faint sticker" aria-hidden="true">
                {landingClose.aside}
              </span>
            </div>
          </div>
        </Reveal>
      </Section>
    </div>
  )
}

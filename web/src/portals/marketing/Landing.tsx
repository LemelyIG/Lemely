/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 — design import, part A.
   V4, not 5: five sections mount a StubMount placeholder rather than their
   real visual, by design — part B builds OpenedQuestion, ScanSequence,
   SchemeExcerpt, ClassBatch and Readings next. Every other section's copy
   is now the verbatim source text, no gaps left open. */
import type { CSSProperties } from "react"
import { useNavigate } from "react-router-dom"
import { ArrowDown, Books, CursorClick } from "@phosphor-icons/react"
import { Button } from "@/components/ui/button"
import { SubjectTag } from "@/components/ui/subject-tag"
import { prefersReducedMotion } from "@/lib/celebration"
import { RevealBlock, Words } from "./motion"
import { close, hero, howItWorks, readingsIntro, schemeSection, subjects, trustBand, classBatchSection } from "./data"

/*
 * The public landing page, rebuilt from the imported design
 * (`.superpowers/sdd/design-import-spec.md`). The design is authoritative
 * for this page's structure, layout and motion — see that file and
 * `.superpowers/sdd/design-import-claims.md`'s RULING before touching
 * anything here.
 *
 * THIS IS PART A OF TWO. Five sections mount a `StubMount` placeholder in
 * place of a real component another agent builds next: `OpenedQuestion`
 * (the trust band, `#marked`), `ScanSequence` ("How it works"),
 * `SchemeExcerpt` ("Where the marks come from"), `ClassBatch` ("A class at a
 * time") and `Readings` ("The same paper, three ways"). Everything else on
 * the page — the hero, every section's surrounding copy, and the close — is
 * real, not a stub.
 *
 * Page classes throughout (`.wrap`, `.hero`, `.sect`, `.band`, `.split`,
 * `.copy`, `.close`, …) come from `./marketing.css`, the verbatim port of the
 * design's own stylesheet, imported once at the portal frame
 * (`index.tsx`). Typography utilities alongside them (`text-display-xl`,
 * `text-ink`, `text-balance`, …) are this repo's existing tokens: the
 * imported CSS handles this page's layout/motion/spacing, the token system
 * still handles type.
 */

/** Where the hero's secondary CTA scrolls to — the dark trust band. */
const MARKED_SECTION_ID = "marked"

/**
 * A clearly-not-finished placeholder for one of the five specimen
 * components part B builds. Dashed border and muted ink so it cannot be
 * mistaken for shipped content; its label is developer scaffolding, not
 * page copy, so it is written directly here rather than routed through
 * `data.ts`'s honest-copy gate — there is nothing to audit about a
 * "pending" marker that never ships.
 */
function StubMount({ label }: { label: string }) {
  return (
    <div
      className="flex min-h-64 w-full items-center justify-center rounded-lg border border-dashed border-rule-strong bg-paper-sunk px-6 py-12 text-center text-body-sm text-ink-faint"
      data-stub={label}
    >
      {/* TODO(part B): replace with the real component. */}
      {label}, pending
    </div>
  )
}

export function Landing() {
  const navigate = useNavigate()

  return (
    <div>
      {/* ── Hero ─────────────────────────────────────────────────────────── */}
      <div className="ruled-bg hero__bed">
        <div className="wrap">
          <div className="hero">
            <RevealBlock as="p" className="hero__eyebrow text-eyebrow">
              {hero.eyebrow}
            </RevealBlock>
            <Words as="h1" text={hero.headline} className="text-display-hero text-ink text-balance" />
            <RevealBlock as="p" index={1} className="hero__sub text-body-lg text-pretty">
              {hero.sub}
            </RevealBlock>
            <RevealBlock as="div" index={2} className="cta">
              <Button variant="primary" size="lg" onClick={() => navigate(hero.primaryCta.to)}>
                {hero.primaryCta.label}
              </Button>
              <Button
                variant="secondary"
                size="lg"
                icon={<ArrowDown size={16} weight="regular" aria-hidden />}
                onClick={() => {
                  document.getElementById(MARKED_SECTION_ID)?.scrollIntoView({
                    behavior: prefersReducedMotion() ? "auto" : "smooth",
                    block: "start",
                  })
                }}
              >
                {hero.secondaryCta.label}
              </Button>
            </RevealBlock>
            <RevealBlock as="div" index={3} className="hero__scope">
              {subjects.map((s, i) => (
                <span key={s.code} className="tagpop scope__item" style={{ "--i": i } as CSSProperties}>
                  <SubjectTag subject={s.code} />
                  <span className="scope__name text-body-sm">{s.name}</span>
                </span>
              ))}
            </RevealBlock>
          </div>
        </div>
      </div>

      {/* ── The dark trust band ─────────────────────────────────────────── */}
      <section id={MARKED_SECTION_ID} className="band">
        <div className="wrap">
          <div className="split">
            <RevealBlock as="div" className="copy" data-tone="inverse">
              <p className="text-eyebrow">{trustBand.eyebrow}</p>
              <h2 className="text-display-xl text-balance">{trustBand.heading}</h2>
              <p className="copy__body text-body-lg text-pretty">{trustBand.body}</p>
              <p className="copy__aside text-body-sm">
                <CursorClick size={16} weight="regular" aria-hidden />
                {trustBand.aside}
              </p>
            </RevealBlock>
            <RevealBlock as="div" index={1} className="drift">
              <StubMount label="OpenedQuestion" />
            </RevealBlock>
          </div>
        </div>
      </section>

      {/* ── How it works ─────────────────────────────────────────────────── */}
      <section id="how-it-works" className="sect">
        <div className="wrap">
          <div className="split split--flip">
            <RevealBlock as="div" className="copy">
              <p className="text-eyebrow">{howItWorks.eyebrow}</p>
              <h2 className="text-display-xl text-ink text-balance">{howItWorks.heading}</h2>
              <p className="copy__body text-body-lg text-pretty">{howItWorks.body}</p>
              <p className="copy__fine text-body-sm">{howItWorks.finePrint}</p>
            </RevealBlock>
            <RevealBlock as="div" index={1} className="drift drift--soft">
              <StubMount label="ScanSequence" />
            </RevealBlock>
          </div>
        </div>
      </section>

      {/* ── Where the marks come from ───────────────────────────────────── */}
      <section id="scheme" className="sect sect--sunk">
        <div className="wrap">
          <div className="split">
            <RevealBlock as="div" className="copy">
              <p className="text-eyebrow">{schemeSection.eyebrow}</p>
              <h2 className="text-display-xl text-ink text-balance">{schemeSection.heading}</h2>
              <p className="copy__body text-body-lg text-pretty">{schemeSection.body}</p>
              <p className="copy__aside text-body-sm">
                <Books size={16} weight="regular" aria-hidden />
                {schemeSection.aside}
              </p>
            </RevealBlock>
            {/* No `.drift` wrapper here — the spec gives this visual no
                parallax class, unlike the trust band's and the two
                `split--flip` sections'. */}
            <RevealBlock as="div" index={1}>
              <StubMount label="SchemeExcerpt" />
            </RevealBlock>
          </div>
        </div>
      </section>

      {/* ── A class at a time ────────────────────────────────────────────── */}
      <section id="class-batch" className="sect">
        <div className="wrap">
          <div className="split split--flip">
            <RevealBlock as="div" className="copy">
              <p className="text-eyebrow">{classBatchSection.eyebrow}</p>
              <h2 className="text-display-xl text-ink text-balance">{classBatchSection.heading}</h2>
              <p className="copy__body text-body-lg text-pretty">{classBatchSection.body}</p>
              <p className="copy__fine text-body-sm">{classBatchSection.finePrint}</p>
            </RevealBlock>
            <RevealBlock as="div" index={1} className="drift drift--soft">
              <StubMount label="ClassBatch" />
            </RevealBlock>
          </div>
        </div>
      </section>

      {/* ── The same paper, three ways ──────────────────────────────────── */}
      <section id="readings" className="sect sect--centre">
        <div className="wrap">
          <RevealBlock as="div" className="centre">
            <p className="text-eyebrow">{readingsIntro.eyebrow}</p>
            <h2 className="text-display-xl text-ink text-balance">{readingsIntro.heading}</h2>
            <p className="centre__sub text-body-lg text-pretty">{readingsIntro.sub}</p>
          </RevealBlock>
          <div className="readings">
            <StubMount label="Readings (teacher / student / parent)" />
          </div>
        </div>
      </section>

      {/* ── Close ────────────────────────────────────────────────────────── */}
      <section id="start" className="close">
        <div className="wrap">
          <div className="close__inner">
            <RevealBlock as="div" className="close__copy">
              <Words as="h2" text={close.heading} className="text-display-xl text-ink text-balance" />
              <p className="close__sub text-body-lg text-pretty">{close.sub}</p>
              <div className="cta cta--start">
                <span className="ctapop">
                  <Button variant="primary" size="lg" onClick={() => navigate(close.cta.to)}>
                    {close.cta.label}
                  </Button>
                </span>
                {/* Marginalia: a nudge beside a button whose own label
                    already says what to do, so it stays out of the
                    accessibility tree. */}
                <span className="text-hand handwrite" aria-hidden="true">
                  {close.aside}
                </span>
              </div>
            </RevealBlock>
            <RevealBlock as="dl" index={1} className="needs">
              {close.needs.map((row) => (
                <div key={row.term}>
                  <dt className="text-label">{row.term}</dt>
                  <dd className="text-body-md text-pretty">{row.detail}</dd>
                </div>
              ))}
            </RevealBlock>
          </div>
        </div>
      </section>
    </div>
  )
}

/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 — design import, part B.
   All five specimen components (OpenedQuestion, ScanSequence, SchemeExcerpt,
   ClassBatch, Readings) now render for real; the StubMount placeholders
   part A left are gone. */
import type { CSSProperties } from "react"
import { useNavigate } from "react-router-dom"
import { ArrowDown, Books, CursorClick } from "@phosphor-icons/react"
import { Button } from "@/components/ui/button"
import { SubjectTag } from "@/components/ui/subject-tag"
import { prefersReducedMotion } from "@/lib/celebration"
import { RevealBlock, Words } from "./motion"
import { close, hero, howItWorks, readingsIntro, schemeSection, subjects, trustBand, classBatchSection } from "./data"
import { OpenedQuestion } from "./OpenedQuestion"
import { ScanSequence } from "./ScanSequence"
import { SchemeExcerpt } from "./SchemeExcerpt"
import { ClassBatch } from "./ClassBatch"
import { Readings } from "./Readings"

/*
 * The public landing page, rebuilt from the imported design
 * (`.superpowers/sdd/design-import-spec.md`). The design is authoritative
 * for this page's structure, layout and motion — see that file and
 * `.superpowers/sdd/design-import-claims.md`'s RULING before touching
 * anything here.
 *
 * Five sections mount a real specimen component: `OpenedQuestion` (the
 * trust band, `#marked`), `ScanSequence` ("How it works"), `SchemeExcerpt`
 * ("Where the marks come from"), `ClassBatch` ("A class at a time") and
 * `Readings` ("The same paper, three ways") — built in part B, replacing
 * part A's `StubMount` placeholders. Everything else on the page — the
 * hero, every section's surrounding copy, and the close — was part A's.
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
              <OpenedQuestion />
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
              <ScanSequence />
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
              <SchemeExcerpt />
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
              <ClassBatch />
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
            <Readings />
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

import { useNavigate } from "react-router-dom"
import { Card } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import {
  landingHero,
  landingProofIntro,
  mcq,
  pillars,
  pillarsIntro,
  pricing,
  pricingPlaceholder,
  proof,
} from "../data"

/*
 * Landing (isLanding) - the public marketing page. Hero with a live result
 * card, the "one engine, three people served" pillars, a dark accuracy proof
 * band, and the plans section.
 *
 * The plans section renders `pricingPlaceholder` while `pricing` is empty. It
 * is empty on purpose: see the DESIGN-AUDIT C2 note in ../data.ts. Do not
 * repopulate it with example tiers to "fill the space" — the placeholder
 * stating that pricing is undecided is the honest render, and inventing a
 * price is the specific defect that note exists to prevent recurring.
 */
export function Landing() {
  const navigate = useNavigate()
  return (
    <div className="lm-screen flex flex-col gap-16 pb-10">
      <div className="grid grid-cols-[1.15fr_1fr] gap-12 items-center pt-[26px] max-[1180px]:grid-cols-1">
        <div>
          <div className="font-mono text-[11.5px] tracking-[0.09em] uppercase text-accent">
            {landingHero.eyebrow}
          </div>
          {/* The hero title is the page's heading, so it is an <h1> rather
              than a large <div>. It rendered as a div until P5.11, which went
              unnoticed because this route had no audit-registry entry — the
              same silent shape as G-13's missing heading. */}
          <h1 className="font-serif text-[62px] leading-[1.04] mt-4 -tracking-[0.01em]">
            {landingHero.titleTop}
            <br />
            {landingHero.titleBottom}
          </h1>
          <div className="text-[16.5px] text-t2 leading-[1.55] mt-5 max-w-[52ch] text-pretty">
            {landingHero.body}
          </div>
          {/* `flex-wrap`, not a narrower button: Button carries
              `whitespace-nowrap`, so at 380px the secondary CTA cannot shrink
              and instead ran to x=409 — a horizontal-scroll violation, which
              `check_ui_gates.py` fails the build on (zero tolerated). Wrapping
              stacks the two CTAs and keeps both labels intact; truncating
              "For centres & teachers" would hide who the link is for. */}
          <div className="flex flex-wrap gap-3 mt-7">
            <Button
              variant="accent"
              size="lg"
              onClick={() => navigate("/student/correct")}
            >
              {landingHero.primaryCta}
            </Button>
            <Button variant="secondary" size="lg">
              {landingHero.secondaryCta}
            </Button>
          </div>
          <div className="text-[12.5px] text-t3 mt-4">
            {landingHero.footnote}
          </div>
        </div>
        <Card className="rounded-[18px] p-6 shadow-[0_24px_60px_-30px_oklch(0.2_0.02_35/.38)]">
          <div className="font-mono text-[11px] text-t2 flex gap-2 items-center">
            <span className="w-1.5 h-1.5 rounded-full bg-ok" />
            {landingHero.cardMeta}
          </div>
          <div className="flex items-baseline gap-3.5 mt-4">
            <div className="font-serif text-[60px] leading-none">
              {landingHero.cardScore}
              <span className="text-[26px] text-t2">{landingHero.cardMax}</span>
            </div>
            <div className="font-serif text-[44px] text-accent leading-none">
              {landingHero.cardGrade}
            </div>
          </div>
          <div className="grid grid-cols-10 gap-[5px] mt-5">
            {mcq.map((q) => (
              <div
                key={q.id}
                className={`aspect-square rounded-[5px] border ${q.correct ? "bg-[oklch(0.96_0.02_150)] border-[oklch(0.90_0.03_150)]" : "bg-accent-subtle border-[oklch(0.87_0.05_35)]"}`}
              />
            ))}
          </div>
          <div className="border-t border-border mt-5 pt-4 text-[12.5px] text-t2 leading-[1.5] text-pretty">
            {landingHero.cardNote}
          </div>
        </Card>
      </div>

      <div>
        <div className="font-serif text-[34px] mb-1.5">{pillarsIntro.title}</div>
        <div className="text-[14.5px] text-t2 mb-[26px] max-w-[66ch] text-pretty">
          {pillarsIntro.body}
        </div>
        <div className="grid grid-cols-3 gap-5 max-[1180px]:grid-cols-1">
          {pillars.map((p) => (
            <Card
              key={p.kicker}
              className="rounded-xl p-6 flex flex-col gap-2.5"
            >
              <div className="font-mono text-[11px] tracking-[0.09em] uppercase text-accent">
                {p.kicker}
              </div>
              <div className="font-serif text-[25px] leading-[1.2]">
                {p.title}
              </div>
              <div className="text-[13.5px] text-t2 leading-[1.55] text-pretty">
                {p.body}
              </div>
              <div className="border-t border-border mt-1.5 pt-3 flex flex-col gap-[7px]">
                {p.bullets.map((b) => (
                  <div
                    key={b}
                    className="flex gap-[9px] text-[12.5px] text-t2 items-start"
                  >
                    <span className="w-[5px] h-[5px] rounded-full bg-accent mt-[7px] flex-none" />
                    <span>{b}</span>
                  </div>
                ))}
              </div>
            </Card>
          ))}
        </div>
      </div>

      <div className="bg-ink rounded-[20px] p-11 text-bg grid grid-cols-2 gap-11 items-center max-[1180px]:grid-cols-1">
        <div>
          <div className="font-serif text-[34px] leading-[1.2]">
            {landingProofIntro.title}
          </div>
          <div className="text-[14.5px] opacity-[0.74] leading-[1.6] mt-3.5 text-pretty">
            {landingProofIntro.body}
          </div>
        </div>
        <div className="grid grid-cols-2 gap-4 max-[1180px]:grid-cols-1">
          {proof.map((p) => (
            <div
              key={p.l}
              className="border border-[oklch(0.32_0.02_35)] rounded-[13px] p-[18px]"
            >
              <div className="font-serif text-[32px] leading-[1.1]">{p.n}</div>
              <div className="text-[12.5px] opacity-[0.68] mt-[5px] leading-[1.4]">
                {p.l}
              </div>
            </div>
          ))}
        </div>
      </div>

      <div>
        <div className="font-serif text-[34px] mb-6">Plans</div>
        {pricing.length === 0 ? (
          <div className="bg-surface border border-border rounded-xl p-[26px] flex flex-col gap-3 max-w-[560px]">
            <div className="text-metadata uppercase text-t3">
              {pricingPlaceholder.label}
            </div>
            <div className="text-display-sm text-t1">
              {pricingPlaceholder.title}
            </div>
            <div className="text-body-lg text-t2 text-pretty">
              {pricingPlaceholder.body}
            </div>
          </div>
        ) : (
        <div className="grid grid-cols-3 gap-5 max-[1180px]:grid-cols-1">
          {pricing.map((p) => (
            <div
              key={p.name}
              className={`rounded-xl p-[26px] flex flex-col gap-3 border ${p.dark ? "bg-ink border-ink text-bg" : "bg-surface border-border text-t1"}`}
            >
              <div className="text-[13.5px] font-semibold">{p.name}</div>
              <div className="font-serif text-[38px] leading-none">
                {p.price}
              </div>
              <div className="text-[12.5px] opacity-[0.72] leading-[1.45]">
                {p.who}
              </div>
              <div className="flex flex-col gap-2 mt-2">
                {p.feats.map((f) => (
                  <div key={f} className="text-[12.5px] leading-[1.4] opacity-[0.86]">
                    {f}
                  </div>
                ))}
              </div>
              <button
                className={`mt-auto font-sans text-[13px] p-[11px] rounded-[9px] cursor-pointer border ${
                  p.ctaAccent
                    ? "bg-accent border-accent text-accent-on"
                    : p.dark
                      ? "bg-transparent border-[oklch(0.42_0.02_35)] text-bg"
                      : "bg-transparent border-border text-t1"
                }`}
              >
                {p.cta}
              </button>
            </div>
          ))}
        </div>
        )}
      </div>
    </div>
  )
}

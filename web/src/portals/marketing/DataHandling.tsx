/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import { Badge } from "@/components/ui/badge"
import { Card } from "@/components/ui/card"
import { Reveal } from "@/components/ui/reveal"
import {
  dataHandlingClose,
  dataHandlingIntro,
  dataHandlingSections,
  notYetBuilt,
} from "./dataHandling"

/*
 * "How Lemely handles your data" (P6.5, D6.8 option A).
 *
 * The Persuade lane's shell, the Read lane's insides. `MarketingFrame` wraps it
 * (see `index.tsx`) because it is a public page reached from the public footer,
 * but the page itself is running prose, so it uses `lm-read` (680px) with
 * `lm-prose` (65ch) on the paragraphs rather than the landing page's 1280px
 * asymmetric grid. §13's two rules for the Read lane, not the marketing one:
 * this page is read, not scanned, and a 1280px measure is unreadable.
 *
 * The dial row is marketing's (VARIANCE 7 / MOTION 7 / DENSITY 4) and this page
 * deliberately spends none of the variance. A page whose entire job is to be
 * believed does not get broken symmetry, and §4's celebration register has
 * nothing to celebrate here. `Reveal` stays, because it is the lane's baseline
 * entry and this page is in the lane.
 *
 * Every sentence rendered here comes from `./dataHandling.ts`, where each one
 * carries the module that implements it. Read that file's header before adding
 * a line: **a claim with no source comment does not ship**, and on this page in
 * particular the difference between a fact and a promise is the whole point.
 */
export function DataHandling() {
  return (
    <div className="px-page-mobile py-section md:px-page-tablet md:py-section-lg lg:px-page-desktop">
      <div className="lm-read flex flex-col gap-10">
        <Reveal>
          <header className="flex flex-col gap-4">
            <div className="text-eyebrow text-accent-ink">{dataHandlingIntro.eyebrow}</div>
            <h1 className="text-display-lg text-ink">{dataHandlingIntro.title}</h1>
            <p className="lm-prose text-body-lg text-ink-muted">
              {dataHandlingIntro.standfirst}
            </p>
          </header>
        </Reveal>

        {/*
          A hairline between entries and nothing else: no cards, no icons, no
          two-column split. §3.2 item 5's flat surfaces, and the plainest
          treatment available on purpose, because decoration on this page reads
          as an attempt to make it go down easier.

          `<section>` with its own `<h2>`, so the page has a real outline a
          screen reader can jump through. Six headings is exactly the case
          heading navigation exists for.
        */}
        <div className="flex flex-col">
          {dataHandlingSections.map((section, i) => (
            <Reveal key={section.heading} delay={i * 40}>
              <section className="border-t border-rule py-7">
                <h2 className="text-display-sm text-ink">{section.heading}</h2>
                <p className="lm-prose mt-2.5 text-body-md text-ink-muted">{section.body}</p>
              </section>
            </Reveal>
          ))}
        </div>

        {/*
          The one panel on the page, and the one item that is an absence rather
          than a behaviour. §4's rule for a caveat is a labelled chip rather
          than a colour carrying the meaning alone, so the `warn` tone comes
          with the words "Not built yet" inside it and the heading says the same
          thing again in a full sentence.

          It sits at the foot rather than buried between two ordinary sections
          because a reader who stops early should still have met it.
        */}
        <Reveal>
          <Card className="p-6">
            <Badge tone="warn">{notYetBuilt.tag}</Badge>
            <h2 className="mt-3.5 text-display-sm text-ink">{notYetBuilt.heading}</h2>
            <p className="lm-prose mt-2.5 text-body-md text-ink-muted">{notYetBuilt.body}</p>
          </Card>
        </Reveal>

        <Reveal>
          <p className="lm-prose text-body-sm text-ink-faint">{dataHandlingClose}</p>
        </Reveal>
      </div>
    </div>
  )
}

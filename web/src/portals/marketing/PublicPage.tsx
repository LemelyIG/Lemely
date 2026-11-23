/* Hallmark · pre-emit critique: P3 H4 E4 S3 R4 V3 */
import { Link } from 'react-router-dom'
import { marketingLinks } from './content'
import type { PublicPageCopy } from './publicPages'
import './public-page.css'

/* A calendar date has no time or zone, so format it as UTC to keep the day the page states. */
const updatedFormat = new Intl.DateTimeFormat('en-GB', {
  day: 'numeric',
  month: 'long',
  year: 'numeric',
  timeZone: 'UTC',
})

export function PublicPage({ page }: { page: PublicPageCopy }) {
  return (
    <article className="brand-public-page px-page-mobile py-section md:px-page-tablet md:py-section-lg lg:px-page-desktop">
      <div className="lm-read flex flex-col gap-7 md:gap-9">
        <header className="flex flex-col gap-3">
          <div className="flex flex-col gap-2">
            <h1 className="text-on-surface">{page.title}</h1>
            {page.lastUpdated && (
              <p className="text-sm text-on-surface-variant">
                Last updated{' '}
                <time dateTime={page.lastUpdated}>
                  {updatedFormat.format(new Date(page.lastUpdated))}
                </time>
              </p>
            )}
          </div>
          <p className="brand-public-intro lm-prose text-on-surface-variant">{page.description}</p>
        </header>
        <div>
          {page.sections.map(({ heading, paragraphs }) => (
            <section key={heading} className="border-t border-outline-variant py-6 md:py-7">
              <h2 className="text-on-surface">{heading}</h2>
              {paragraphs.map((paragraph) => (
                <p key={paragraph} className="lm-prose text-on-surface-variant">
                  {paragraph}
                </p>
              ))}
            </section>
          ))}
          {page.path === '/about' && (
            <p className="lm-prose pb-6 text-on-surface-variant md:pb-7">
              <Link to="/landing#how">See how Lemely marks a past paper.</Link>
            </p>
          )}
          {page.path === '/privacy' && (
            <p className="lm-prose pb-6 md:pb-7 text-on-surface-variant">
              Read more about <Link to="/data">what happens to your work</Link>.
            </p>
          )}
          <section className="border-t border-outline-variant py-6 md:py-7">
            <h2 className="text-on-surface">Contact us</h2>
            <p className="lm-prose text-on-surface-variant">
              Email <a href={marketingLinks.contact}>contact@lemelyig.com</a>{' '}
              or call <a href={marketingLinks.phone}>+201067661974</a>.
            </p>
            {page.path === '/terms' && (
              <p className="lm-prose text-on-surface-variant">
                See our <Link to="/refund-policy">Refund Policy</Link>{' '}
                and <Link to="/privacy">Privacy Policy</Link>.
              </p>
            )}
          </section>
        </div>
      </div>
    </article>
  )
}

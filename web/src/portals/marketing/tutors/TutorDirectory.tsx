/* Hallmark · pre-emit critique: P4 H4 E4 S3 R4 V3 — the open web sees a plain, honest list: who, what they teach, how they meet; everything that needs an account is behind one sentence that says so. */
import { Link, Navigate, useLocation, useSearchParams } from "react-router-dom"
import { MarketingFrame } from "@/portals/marketing"
import { NotFound } from "@/portals/misc/NotFound"
import { DirectoryView } from "@/components/tutoring/directory-view"
import {
  DIRECTORY_INTRO,
  DIRECTORY_SIGN_IN_LINE,
  filtersFromSearchParams,
  filtersToSearchParams,
  type DirectoryFilterState,
} from "@/lib/tutoring/discovery"
import {
  NOINDEX_ROBOTS,
  classifyTutorPath,
  robotsForDirectory,
} from "@/lib/tutoring/robotsMeta"

/*
 * G-16 · Tutor directory (`/tutors`, public, SPEC §d). The open web's list of
 * listed tutors: filters, C-23 cards, "Load more", and one line saying that
 * full profiles, availability, reviews and results are for people who sign in.
 * It reads P1 and P3 only, so it carries public fields and nothing else.
 *
 * Search indexing (row 17): this page is always `noindex, follow`. It lists
 * tutors who opted out of search too, so it is never indexed itself, and
 * `follow` lets a crawler reach the cards that are. The worker sends the same
 * `X-Robots-Tag`; this tag is for crawlers that run JavaScript. The page only
 * answers to `/tutors` itself: any other spelling of the address (`/Tutors`,
 * `/tutors/`) is sent to the canonical one, because the worker serves those
 * with no robots header at all (`lib/tutoring/robotsMeta.ts`).
 */

const SIGN_IN = "Sign in"

export function TutorDirectory() {
  const { pathname, search } = useLocation()
  const [params, setParams] = useSearchParams()
  const page = classifyTutorPath(pathname)

  if (page.kind === "redirect") return <Navigate to={`${page.to}${search}`} replace />
  if (page.kind !== "directory") {
    return (
      <>
        <meta name="robots" content={NOINDEX_ROBOTS} />
        <NotFound />
      </>
    )
  }

  const filters = filtersFromSearchParams(params, "public")
  const change = (next: DirectoryFilterState) => setParams(filtersToSearchParams(next, "public"), { replace: true })

  return (
    <MarketingFrame>
      <meta name="robots" content={robotsForDirectory()} />
      <div className="mx-auto flex w-full max-w-marketing flex-col gap-8 px-page-mobile py-section md:px-page-tablet md:py-section-lg lg:px-page-desktop">
        <header className="flex flex-col gap-3">
          <h1 className="m-0 text-display-lg text-ink">Tutors</h1>
          <p className="m-0 max-w-prose text-body-lg text-ink-muted">{DIRECTORY_INTRO}</p>
        </header>
        <DirectoryView
          audience="public"
          tutorPath={(tutorId) => `/tutors/${tutorId}`}
          filters={filters}
          onFiltersChange={change}
          aside={
            <p className="m-0 max-w-prose text-body-md text-ink-muted">
              <Link to="/login" className="text-ink underline underline-offset-4">
                {DIRECTORY_SIGN_IN_LINE.slice(0, SIGN_IN.length)}
              </Link>
              {DIRECTORY_SIGN_IN_LINE.slice(SIGN_IN.length)}
            </p>
          }
        />
      </div>
    </MarketingFrame>
  )
}

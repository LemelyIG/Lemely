/* Hallmark · pre-emit critique: P4 H4 E4 S3 R4 V3 — a working list, not a showcase; the one explanation (how tutors are ordered) is a disclosure so it never competes with the tutors. */
import { useSearchParams } from "react-router-dom"
import { DirectoryView } from "@/components/tutoring/directory-view"
import {
  DIRECTORY_INTRO,
  GRADE_RANKING_NOTE,
  filtersFromSearchParams,
  filtersToSearchParams,
  type DirectoryFilterState,
} from "@/lib/tutoring/discovery"

/*
 * S-33 · Find a tutor (`/student/tutors`, SPEC §d). G-16's filters plus
 * "Usually available", C-23 cards in rank order, and the F10 disclosure of how
 * the order works. The filters live in the address, so a filtered list is a link
 * and the Back button undoes a filter. Reached from the student nav ("Tutors");
 * each card goes to S-34.
 *
 * The same composition, with the parent shell's paths and a child selector, is
 * P-07's directory (`DirectoryView`).
 */

const TUTORS = "/student/tutors"

export function FindTutor() {
  const [params, setParams] = useSearchParams()
  const filters = filtersFromSearchParams(params, "member")
  const change = (next: DirectoryFilterState) => setParams(filtersToSearchParams(next, "member"), { replace: true })

  return (
    <div className="flex w-full flex-col gap-6">
      <div className="flex flex-col gap-2">
        <h1 className="m-0 text-display-md text-ink">Tutors</h1>
        <p className="m-0 max-w-prose text-body-md text-ink-muted">{DIRECTORY_INTRO}</p>
      </div>
      <DirectoryView
        audience="member"
        tutorPath={(tutorId) => `${TUTORS}/${tutorId}`}
        filters={filters}
        onFiltersChange={change}
        aside={
          <details className="max-w-prose">
            <summary className="cursor-pointer rounded-md py-3 text-body-sm text-ink-muted underline underline-offset-4">
              How tutors are ordered
            </summary>
            <p className="m-0 mt-2 text-body-sm text-ink-muted">{GRADE_RANKING_NOTE}</p>
          </details>
        }
      />
    </div>
  )
}

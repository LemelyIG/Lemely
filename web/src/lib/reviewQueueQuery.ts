import type { ReviewSort } from "@/lib/teacherTypes"

/**
 * The review queue's filters, sort and search, as one value. The URL is the
 * source of truth (K1: filters live in the query string and travel into the
 * answer URL), and the same names are the API's query params, so one codec
 * serves both the address bar and `GET /teacher/review`.
 *
 * `reasons` is an open string list: the server may add reasons (e.g. a
 * student challenge) and the client passes unknown ones through untouched.
 */
export interface ReviewQueueFilters {
  q: string
  classIds: string[]
  reasons: string[]
  subjects: string[]
  minAgeHours: number | null
  sort: ReviewSort
}

/** The approved mock opens on "Marks lost". The API's own default stays `oldest`. */
export const DEFAULT_SORT: ReviewSort = "lost"

export const EMPTY_FILTERS: ReviewQueueFilters = {
  q: "",
  classIds: [],
  reasons: [],
  subjects: [],
  minAgeHours: null,
  sort: DEFAULT_SORT,
}

const SORTS: readonly ReviewSort[] = ["oldest", "lost", "confidence"]

export function filtersFromSearch(sp: URLSearchParams): ReviewQueueFilters {
  const sortRaw = sp.get("sort")
  const ageRaw = sp.get("min_age_hours")
  const age = ageRaw !== null && ageRaw.trim() !== "" ? Number(ageRaw) : NaN
  return {
    q: (sp.get("q") ?? "").trim(),
    classIds: sp.getAll("class_id").filter(Boolean),
    reasons: sp.getAll("reason").filter(Boolean),
    subjects: sp.getAll("subject").filter(Boolean),
    minAgeHours: Number.isFinite(age) ? age : null,
    sort: SORTS.includes(sortRaw as ReviewSort) ? (sortRaw as ReviewSort) : DEFAULT_SORT,
  }
}

function appendFilters(sp: URLSearchParams, f: ReviewQueueFilters): void {
  const q = f.q.trim()
  if (q) sp.set("q", q)
  for (const id of f.classIds) sp.append("class_id", id)
  for (const r of f.reasons) sp.append("reason", r)
  for (const s of f.subjects) sp.append("subject", s)
  if (f.minAgeHours !== null) sp.set("min_age_hours", String(f.minAgeHours))
}

/** For the address bar: defaults are left out so a clean queue has a clean URL. */
export function filtersToSearch(f: ReviewQueueFilters): URLSearchParams {
  const sp = new URLSearchParams()
  appendFilters(sp, f)
  if (f.sort !== DEFAULT_SORT) sp.set("sort", f.sort)
  return sp
}

/** Sort is an ordering, not a filter: it never makes "Clear filters" appear. */
export function filtersActive(f: ReviewQueueFilters): boolean {
  return (
    f.q.trim() !== "" ||
    f.classIds.length > 0 ||
    f.reasons.length > 0 ||
    f.subjects.length > 0 ||
    f.minAgeHours !== null
  )
}

export function filterKey(f: ReviewQueueFilters): string {
  const sorted = (xs: string[]) => [...xs].sort().join(",")
  return [f.q.trim(), sorted(f.classIds), sorted(f.reasons), sorted(f.subjects), f.minAgeHours ?? "", f.sort].join("|")
}

/** For the API: the sort is always explicit, because the server defaults to `oldest`. */
export function reviewQueuePath(f: ReviewQueueFilters, page: { limit?: number; cursor?: string } = {}): string {
  const sp = new URLSearchParams()
  appendFilters(sp, f)
  sp.set("sort", f.sort)
  if (page.limit !== undefined) sp.set("limit", String(page.limit))
  if (page.cursor) sp.set("cursor", page.cursor)
  return `/teacher/review?${sp.toString()}`
}

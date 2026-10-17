import { useQuery, type UseQueryResult } from "@tanstack/react-query"
import { request } from "@/lib/api"
import { subjectNameFor } from "@/lib/reference"
import type { ReferenceData } from "@/lib/referenceTypes"

/*
 * React-query hook wrapping `GET /api/reference` (`lemely/web/routers/reference.py`),
 * reachable by every authenticated role. Follows useMeApi.ts's conventions: one
 * hook per endpoint, and **no `fallback` passed to `request()`** — a real
 * backend or auth failure must surface as a query error the screen can render,
 * never silently resolve to an empty catalogue. An empty subject list would
 * read as "we support no subjects", which is a claim, not an absence.
 */

const REFERENCE_KEY = ["reference"] as const

/**
 * The reference payload.
 *
 * `staleTime: Infinity` because this data changes only when the catalogue is
 * re-seeded or the threshold ingest runs — both deploy-time events. Nine screens
 * read it; refetching per mount would be nine requests for a payload that
 * cannot have changed between them.
 */
export function useReference(): UseQueryResult<ReferenceData, Error> {
  return useQuery({
    queryKey: REFERENCE_KEY,
    queryFn: () => request<ReferenceData>("/reference"),
    staleTime: Number.POSITIVE_INFINITY,
  })
}

/** A subject's display name, or the raw code while loading or when unknown. */
export function useSubjectName(code: string): string {
  const { data } = useReference()
  return subjectNameFor(data, code)
}

import { useMemo } from "react"
import { usePlacementAvailabilities } from "@/lib/hooks/usePlacementApi"
import { useDueSession, useFlashcardDecks } from "@/lib/hooks/useFlashcardApi"
import { useStudentProfile } from "@/lib/hooks/useMeApi"
import { usePracticeRuns, usePracticeTopicsMany, useStudentQuizzes } from "@/lib/hooks/usePracticeHubApi"
import { useReference } from "@/lib/hooks/useReferenceApi"
import { useOverview } from "@/lib/hooks/useStudentApi"
import { subjectNameFor } from "@/lib/reference"
import type { HubInput, HubSubject } from "./hubModel"

/**
 * Composes every query the hub reads into one `HubInput`. Subjects are the
 * overview's (they carry paper counts) followed by any enrolled subject with
 * no paper yet, so a first-time student can still open the builder.
 *
 * `refetchAll` retries exactly the queries `hubState` turns into the error
 * state (overview, runs, topics); `refetching` is true while any of them is in
 * flight, so the retry button can show it is working instead of looking dead.
 */
export function usePracticeHubData(): {
  input: HubInput
  builderSubjects: { code: string; name: string }[]
  refetchAll: () => void
  refetching: boolean
} {
  const overview = useOverview()
  const profile = useStudentProfile()
  const { data: reference } = useReference()

  const subjects = useMemo<HubSubject[]>(() => {
    const fromOverview = (overview.data?.subjects ?? []).map((s) => ({ code: s.code, name: s.name, papers: s.papers }))
    const seen = new Set(fromOverview.map((s) => s.code))
    const fromEnrolments = (profile.data?.enrolments ?? [])
      .filter((e) => !seen.has(e.subjectCode))
      .map((e) => ({ code: e.subjectCode, name: subjectNameFor(reference, e.subjectCode), papers: 0 }))
    return [...fromOverview, ...fromEnrolments]
  }, [overview.data, profile.data, reference])

  const codes = subjects.map((s) => s.code)
  const topicQueries = usePracticeTopicsMany(codes)
  const runs = usePracticeRuns()
  const quizzes = useStudentQuizzes()
  const due = useDueSession()
  const decks = useFlashcardDecks()
  const placement = usePlacementAvailabilities(codes)
  const now = useMemo(() => new Date(), [])

  const input: HubInput = {
    overviewStatus: overview.status,
    subjects,
    topics: codes.map((code, i) => ({ code, status: topicQueries[i].status, data: topicQueries[i].data })),
    runsStatus: runs.status,
    runs: runs.data?.runs ?? [],
    homework: quizzes.data?.quizzes ?? [],
    dueTotal: due.data?.totalDue ?? null,
    deckCount: decks.data ? decks.data.length : null,
    placement: codes.map((code, i) => ({
      code,
      available: placement[i].data?.available ?? null,
      minutes: placement[i].data?.estimatedMinutes ?? null,
    })),
    now,
  }

  return {
    input,
    builderSubjects: subjects.map(({ code, name }) => ({ code, name })),
    refetchAll: () => {
      void overview.refetch()
      void runs.refetch()
      for (const q of topicQueries) void q.refetch()
    },
    refetching: overview.isFetching || runs.isFetching || topicQueries.some((q) => q.isFetching),
  }
}

import { useQuery, type UseQueryResult } from "@tanstack/react-query"
import { fetchStudentHome } from "@/lib/studentHomeApi"
import type { StudentHome } from "@/lib/studentHomeTypes"

export const STUDENT_HOME_KEY = ["student", "home"] as const

/** While a paper is marking, Home re-reads every 5s so the stage moves on by itself. */
export const MARKING_POLL_MS = 5_000

export function homeRefetchInterval(data: StudentHome | undefined): number | false {
  return data?.moments.some((m) => m.kind === "marking" && !m.stale) ? MARKING_POLL_MS : false
}

export function useStudentHome(): UseQueryResult<StudentHome, Error> {
  return useQuery({
    queryKey: STUDENT_HOME_KEY,
    queryFn: fetchStudentHome,
    refetchInterval: (query) => homeRefetchInterval(query.state.data),
  })
}

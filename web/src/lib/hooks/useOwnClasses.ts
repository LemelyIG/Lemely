import { useQuery, type UseQueryResult } from "@tanstack/react-query"
import { request } from "@/lib/api"
import type { ClassList } from "@/lib/teacherTypes"

/*
 * The signed-in teacher's OWN classes, whoever they are working as.
 *
 * For own-account screens (Settings). `GET /teacher/classes` is an adopted route, so while acting
 * for a lead the shared `useTeacherClasses` returns the lead's list under a lead-partitioned key.
 * This reads the same route as the caller (`asSelf`, no acting header) and keys it under
 * `["team", ...]`, which is exempt from the lead partition (`OWN_ACCOUNT_ROOTS`), so the answer is
 * the caller's whichever lead is selected.
 */
export function useOwnClasses(): UseQueryResult<ClassList, Error> {
  return useQuery({
    queryKey: ["team", "own-classes"],
    queryFn: () => request<ClassList>("/teacher/classes", { asSelf: true }),
  })
}

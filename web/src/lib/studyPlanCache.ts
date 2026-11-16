import type {
  CurrentStudyPlanDTO,
  StudyPlanOverviewDTO,
  StudyPlanSessionDTO,
} from "@/lib/studyPlanTypes"

/*
 * Pure cache patchers for the study-plan queries (L9). Kept out of the hooks
 * module so Vitest's node runner can import them without react-query.
 *
 * Every patch writes the session the SERVER returned (its completion
 * timestamp, its new date), never a client-side guess. The one field kept
 * from the cached copy is `reason`: complete and move return `null` there,
 * and the week route computed the real one.
 */

function merge(cached: StudyPlanSessionDTO, server: StudyPlanSessionDTO): StudyPlanSessionDTO {
  return { ...cached, ...server, reason: server.reason ?? cached.reason ?? null }
}

/** ISO dates sort lexically in calendar order; `sort` is stable, so ties keep order. */
function byDate(sessions: StudyPlanSessionDTO[]): StudyPlanSessionDTO[] {
  return [...sessions].sort((a, b) => a.date.localeCompare(b.date))
}

export function patchOverviewSession(
  overview: StudyPlanOverviewDTO | undefined,
  session: StudyPlanSessionDTO,
): StudyPlanOverviewDTO | undefined {
  if (!overview) return overview
  let changed = false
  const subjects = overview.subjects.map((subject) => {
    const plan = subject.plan
    if (!plan || !plan.sessions.some((s) => s.id === session.id)) return subject
    changed = true
    const sessions = byDate(plan.sessions.map((s) => (s.id === session.id ? merge(s, session) : s)))
    return { ...subject, plan: { ...plan, sessions } }
  })
  return changed ? { ...overview, subjects } : overview
}

export function patchCurrentSession(
  current: CurrentStudyPlanDTO | undefined,
  session: StudyPlanSessionDTO,
): CurrentStudyPlanDTO | undefined {
  if (!current?.plan) return current
  if (!current.plan.sessions.some((s) => s.id === session.id)) return current
  return {
    ...current,
    plan: {
      ...current.plan,
      sessions: byDate(current.plan.sessions.map((s) => (s.id === session.id ? merge(s, session) : s))),
    },
  }
}

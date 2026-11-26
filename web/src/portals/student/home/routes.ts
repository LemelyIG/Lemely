import type { StudentHome } from "@/lib/studentHomeTypes"

/*
 * Every door Home and Me open, in one place. Routes that do not exist yet
 * (the Practice tab root from L4, the all-subjects week from L9) fall back to
 * the per-subject routes that exist today. When L4 and L9 merge, only this
 * file changes.
 */
export const homeRoutes = {
  scan: "/student/correct",
  me: "/student/profile",
  subject: (code: string) => `/student/subject/${code}`,
  result: (paperId: string, filter?: "lost") =>
    filter ? `/student/result/${paperId}?q=${filter}` : `/student/result/${paperId}`,
  practice: (code: string) => `/student/practice/${code}`,
  practiceTopic: (code: string, topic: string) =>
    `/student/practice/${code}?topic=${encodeURIComponent(topic)}`,
  practiceSet: (assignmentId: string) => `/student/practice/set/${assignmentId}`,
  flashcards: (code: string) => `/student/flashcards/${code}`,
  plan: (code: string) => `/student/plan/${code}`,
  session: (code: string, sessionId: string) => `/student/plan/${code}/session/${sessionId}`,
  classes: "/student/classes",
  standings: "/student/board",
  friends: "/student/friends",
  parents: "/student/parents",
  tutoring: "/student/tutors",
  placement: (code: string) => `/student/placement/${code}`,
  settings: "/student/settings",
  notifications: "/student/notifications",
  recentlyDeleted: "/student/recently-deleted",
} as const

/** Where "practice" goes: the top topic to win back, else the first subject, else scan. */
export function practiceTarget(home: StudentHome): string {
  const top = home.winBack[0]
  if (top) return homeRoutes.practiceTopic(top.subjectCode, top.topic)
  const first = home.floor[0]
  return first ? homeRoutes.practice(first.code) : homeRoutes.scan
}

/** The subject whose plan Home opens: today's first session, else the first subject. */
export function planSubject(home: StudentHome): string | null {
  return home.todaySessions[0]?.subjectCode ?? home.floor[0]?.code ?? null
}

export function planTarget(home: StudentHome): string {
  const code = planSubject(home)
  return code ? homeRoutes.plan(code) : homeRoutes.scan
}

export function flashcardsTarget(home: StudentHome): string {
  const code = home.winBack[0]?.subjectCode ?? home.floor[0]?.code
  return code ? homeRoutes.flashcards(code) : homeRoutes.scan
}

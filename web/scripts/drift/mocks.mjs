/*
 * API mocks for the shell scenes. Teacher scenes layer these on top of the
 * capture-surface registry's own stubs (`capture_surface.mjs`). Student scenes
 * use `studentShellMocks` alone: the values copy design A's populated and new
 * states (`student-home-a.html` shell markup).
 */

function json(route, body) {
  return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) })
}

export const TEACHER_NOTIFICATIONS = {
  notifications: [
    {
      notificationId: "tn-1",
      type: "at_risk_alert",
      title: "Omar Said may need support in 0625",
      body: "Two papers below his target grade",
      payload: { studentId: "stu-1" },
      createdAt: "2026-11-05T09:12:00",
      readAt: null,
    },
    {
      notificationId: "tn-2",
      type: "announcement",
      title: "Mock exams start on 16 Nov",
      body: "Year 11, all subjects",
      payload: {},
      createdAt: "2026-11-04T18:00:00",
      readAt: "2026-11-04T19:00:00",
    },
  ],
}
export const TEACHER_COUNTS = { unread: 1, total: 2, unreadByType: { at_risk_alert: 1 } }

export async function teacherShellMocks(page) {
  await page.route("**/api/notifications", (route) => json(route, TEACHER_NOTIFICATIONS))
  await page.route("**/api/notifications/counts", (route) => json(route, TEACHER_COUNTS))
  await page.route("**/api/teacher/review?**", (route) => json(route, { items: [], total: 3 }))
}

export const STUDENT_PROFILE = {
  userId: "capture-student",
  email: "mariam.hassan@student.lemely.app",
  displayName: "Mariam",
  role: "student",
  emailVerified: true,
  avatarUrl: null,
  timezone: "Africa/Cairo",
  timezoneIsExplicit: true,
}

const STUDENT_PROFILE_RECORD = {
  profile: {
    qualificationLevel: "igcse",
    gradeLevel: null,
    schoolName: null,
    hasExternalLessons: null,
    weeklyStudyHours: null,
    onboardingCompletedAt: "2026-09-01T10:00:00Z",
    leaderboardOptOut: false,
  },
  enrolments: [],
}

const REFERENCE = {
  subjects: [],
  targetGradeVocabularies: [],
  qualificationLevels: [{ value: "igcse", label: "IGCSE" }],
  sessionMonths: [],
  difficultyBands: [],
}

const row = (code, name, grade, pct) => ({
  code,
  name,
  qualificationLevel: "igcse",
  detail: "",
  pct,
  papers: 1,
  trend: "",
  grade,
  barColor: "accent",
  trendUp: true,
})

const STUDENT_DATA = {
  populated: {
    subjects: [row("0580", "Mathematics", "A", 40), row("0606", "Add Maths", "B", 36), row("0625", "Physics", "C", 43)],
    notifications: [
      { notificationId: "sn-1", type: "announcement", title: "Physics mock moved to Thu 12 Nov", body: "Ms Farouk · Year 11 Physics", payload: {}, createdAt: "2026-11-05T09:12:00", readAt: null },
      { notificationId: "sn-3", type: "grade_ready", title: "0580/42 is marked", body: "Grade A, up from B", payload: {}, createdAt: "2026-11-04T18:00:00", readAt: "2026-11-04T18:30:00" },
    ],
    counts: { unread: 1, total: 2, unreadByType: { announcement: 1 } },
  },
  new: { subjects: [], notifications: [], counts: { unread: 0, total: 0, unreadByType: {} } },
}

export function studentShellMocks(state) {
  const data = STUDENT_DATA[state]
  if (!data) throw new Error(`no student shell mock for ${state}`)
  return async (page) => {
    await page.route("**/api/me/student-profile", (route) => json(route, STUDENT_PROFILE_RECORD))
    await page.route("**/api/reference", (route) => json(route, REFERENCE))
    await page.route("**/api/student/overview", (route) =>
      json(route, { studentName: "Mariam", forecast: "", subjects: data.subjects, weakGlobal: [], momentum: { points: [] } }),
    )
    await page.route("**/api/notifications", (route) => json(route, { notifications: data.notifications }))
    await page.route("**/api/notifications/counts", (route) => json(route, data.counts))
  }
}

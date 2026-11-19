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
  // Grading polls `/papers` through a refetchInterval that reads `.papers.some`; the catch-all `{}` threw there.
  await page.route(/\/api\/papers(\?|$)/, (route) => json(route, { papers: [], tabs: [] }))
  await page.route(/\/api\/teacher\/announcements(\?|$)/, (route) => json(route, { announcements: [] }))
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
    // Overview's join-class prompt reads `classes.length`; the catch-all `{}`
    // would crash the page under the settings dialog and take the dialog with it.
    await page.route("**/api/student/classes", (route) =>
      json(route, { classes: state === "new" ? [] : [{ classId: "class-1", className: "Year 11 Physics" }] }),
    )
    // The settings dialog's Account and devices tab: the two devices design A
    // shows (this browser, a phone used yesterday). The harness clock is fixed at
    // 2026-11-05 10:00 local time (`NOW` in harness.mjs).
    const now = new Date(2026, 10, 5, 10, 0)
    await page.route("**/api/me/devices", (route) =>
      json(route, {
        maxDevices: 3,
        devices: [
          {
            deviceId: "device-1",
            label: null,
            userAgent: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
            lastActiveAt: now.toISOString(),
            isCurrent: true,
          },
          {
            deviceId: "device-2",
            label: null,
            userAgent: "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1",
            lastActiveAt: new Date(now.getTime() - 24 * 60 * 60 * 1000).toISOString(),
            isCurrent: false,
          },
        ],
      }),
    )
    await page.route("**/api/notifications", (route) => json(route, { notifications: data.notifications }))
    await page.route("**/api/notifications/counts", (route) => json(route, data.counts))
    // The Announcements screen (and the study plan's exam strip) read these three; the catch-all `{}` has no
    // `entries`, so `nextExam` threw inside a memo.
    await page.route(/\/api\/student\/announcements(\?|$)/, (route) => json(route, { announcements: [] }))
    await page.route("**/api/student/announcements/unread-count", (route) => json(route, { unreadCount: 0 }))
    await page.route("**/api/student/exam-calendar", (route) =>
      json(route, { availability: state === "new" ? "no_enrolment" : "no_timetable", entries: [] }),
    )
  }
}

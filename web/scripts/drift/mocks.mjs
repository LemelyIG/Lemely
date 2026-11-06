/*
 * API mocks for the shell scenes. Teacher scenes layer these on top of the
 * capture-surface registry's own stubs (`capture_surface.mjs`).
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

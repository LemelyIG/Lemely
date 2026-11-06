import { teacherShellMocks } from "./mocks.mjs"

const teacher = (extra) => ({ surface: "teacher-overview", state: "populated", mocks: teacherShellMocks, ...extra })

async function openTeacherNav(page) {
  const more = page.getByRole("button", { name: "More", exact: true })
  if (await more.isVisible()) await more.click()
  else await page.getByRole("button", { name: /Open teacher navigation/ }).click()
  await page.getByRole("dialog").waitFor()
}
async function openBell(page) {
  await page.getByRole("button", { name: /^Notifications/ }).click()
  await page.getByRole("menu").waitFor()
}
async function openAccount(page) {
  await page.getByRole("button", { name: /^Your profile and account/ }).click()
  await page.getByRole("menu").waitFor()
}

const TEACHER_SETTINGS = [
  ["profile", ""],
  ["account", "/devices"],
  ["notifications", "/notifications"],
  ["appearance", "/appearance"],
  ["classes", "/classes"],
  ["install", "/install"],
]

/** Teacher: no design A preview exists, so each scene compares the merged
 * `develop` capture (recorded with --record-baseline in Task 1) to the current
 * one. Frame scenes are "log": the shell is meant to change; every difference
 * needs a justification naming the design A rule. Content scenes are "gate":
 * the page below the shell must not change. */
export const TEACHER_SCENES = [
  { id: "teacher-home-frame", kind: "before-vs-after", capture: "frame", rule: "log", app: teacher({}) },
  { id: "teacher-home-content", kind: "before-vs-after", capture: "content", app: teacher({}) },
  {
    id: "teacher-class-frame",
    kind: "before-vs-after",
    capture: "frame",
    rule: "log",
    app: { surface: "teacher-analytics", mocks: teacherShellMocks },
  },
  {
    id: "teacher-class-content",
    kind: "before-vs-after",
    capture: "content",
    app: { surface: "teacher-analytics", mocks: teacherShellMocks },
  },
  {
    id: "teacher-notifications-frame",
    kind: "before-vs-after",
    capture: "frame",
    rule: "log",
    app: teacher({ path: "/teacher/notifications" }),
  },
  {
    id: "teacher-notifications-content",
    kind: "before-vs-after",
    capture: "content",
    app: teacher({ path: "/teacher/notifications" }),
  },
  {
    id: "teacher-drawer",
    kind: "before-vs-after",
    capture: "frame",
    rule: "log",
    windows: [390, 768],
    app: teacher({ act: openTeacherNav }),
  },
  { id: "teacher-bell", kind: "before-vs-after", capture: "frame", rule: "log", app: teacher({ act: openBell }) },
  { id: "teacher-account", kind: "before-vs-after", capture: "frame", rule: "log", app: teacher({ act: openAccount }) },
  ...TEACHER_SETTINGS.map(([tab, suffix]) => ({
    id: `teacher-settings-${tab}`,
    kind: "before-vs-after",
    capture: "frame",
    rule: "log",
    app: teacher({ path: `/teacher/settings${suffix}` }),
  })),
]

export const SHELL_SCENES = [...TEACHER_SCENES]

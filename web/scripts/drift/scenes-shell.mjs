import { STUDENT_PROFILE, studentShellMocks, teacherShellMocks } from "./mocks.mjs"

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
    windows: [390, 768, 1100],
    // develop showed the sidebar column at 1100 px (drawer below 820 only), so
    // there is no baseline to diff; the key captures the new drawer, log-only.
    baselineless: [1100],
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

/** The app reserves the scrollbar's space on html (`scrollbar-gutter: stable`,
 * index.css); headless Chromium hides scrollbars, so the preview has no such
 * strip. Dropping the reservation in the capture compares both at the full
 * window width. (A page-environment difference, not a shell rule.) */
const NO_GUTTER = "html{scrollbar-gutter:auto!important}"

const student = (state, extra = {}) => ({
  path: "/student",
  profile: STUDENT_PROFILE,
  mocks: studentShellMocks(state),
  css: NO_GUTTER,
  ...extra,
})

/** Make the preview stand for another route: its route-dependent parts are a
 * title and which row is current (design A rules), nothing else. */
function asRoute({ title, current }) {
  return (page) =>
    page.evaluate(
      ([t, c]) => {
        document.querySelector(".as-title").textContent = t
        for (const a of document.querySelectorAll(".as-list a[aria-current]")) a.removeAttribute("aria-current")
        if (c) document.querySelector(`.as-list a[href="${c}"]`)?.setAttribute("aria-current", "page")
      },
      [title, current],
    )
}

async function openStudentNav(page) {
  const more = page.getByRole("button", { name: "More", exact: true })
  if (await more.isVisible()) await more.click()
  else await page.getByRole("button", { name: "Open student navigation" }).click()
  await page.getByRole("dialog").waitFor()
}
async function openPreviewNav(page) {
  const more = page.locator(".a-bottombar button[popovertarget]")
  if (await more.isVisible()) await more.click()
  else await page.click(".as-menu")
}

/** Decision 1: the app's drawer range runs to 1247px, design A's only to
 * 1000px. At the 1024 window the app shows the menu button and a full-width
 * page where design A shows the 216px sidebar, which no 15% cap can absorb.
 * So each student scene splits in two. The gate scene keeps 390, 768, 1440
 * and 1920. A log-only `<id>-1024` scene has no cap but needs an approved
 * entry, the same rule as the teacher frames. */
const GATE_WINDOWS = [390, 768, 1440, 1920]
function byWindowRule(scene) {
  return [
    { ...scene, windows: GATE_WINDOWS },
    { ...scene, id: `${scene.id}-1024`, windows: [1024], rule: "log" },
  ]
}

export const STUDENT_SCENES = [
  ...["populated", "new"].flatMap((state) =>
    byWindowRule({
      id: `student-${state}-frame`,
      kind: "preview-vs-app",
      capture: "frame",
      app: student(state),
      preview: { state },
    }),
  ),
  ...byWindowRule({
    id: "student-subject-frame",
    kind: "preview-vs-app",
    capture: "frame",
    app: student("populated", { path: "/student/subject/0606" }),
    preview: { state: "populated", act: asRoute({ title: "Add Maths", current: null }) },
  }),
  ...byWindowRule({
    id: "student-notifications-frame",
    kind: "preview-vs-app",
    capture: "frame",
    app: student("populated", { path: "/student/notifications" }),
    preview: { state: "populated", act: asRoute({ title: "Notifications", current: null }) },
  }),
  {
    // 390 and 768 only: at 1024 design A has no drawer to open (its sidebar
    // shows from 1001px). The app's 1024 drawer is covered by the
    // student-sidebar-xor-menu-* behaviour checks instead.
    id: "student-drawer",
    kind: "preview-vs-app",
    capture: "frame",
    windows: [390, 768],
    // On the subject route, so the app's tree opens and tints Add Maths as
    // design A does (on /student the app has no fallback subject until the
    // Overview plan; that closed group alone moves the phone sheet's top).
    app: student("populated", { path: "/student/subject/0606", act: openStudentNav }),
    preview: {
      state: "populated",
      act: async (page) => {
        await asRoute({ title: "Add Maths", current: null })(page)
        await openPreviewNav(page)
      },
    },
  },
  {
    // The drawer as /student shows it. Log-only: the closed Add Maths group
    // (no session subject until the Overview plan passes fallbackId) moves the
    // phone sheet's top and puts 390 light over the 15% gate cap, so the gate
    // scene above runs on the subject route.
    id: "student-drawer-home",
    kind: "preview-vs-app",
    capture: "frame",
    rule: "log",
    windows: [390, 768],
    app: student("populated", { act: openStudentNav }),
    preview: { state: "populated", act: openPreviewNav },
  },
  ...byWindowRule({
    id: "student-bell",
    kind: "preview-vs-app",
    capture: "frame",
    app: student("populated", { act: openBell }),
    preview: { state: "populated", act: (page) => page.click(".as-pop-bell summary") },
  }),
  ...byWindowRule({
    id: "student-account",
    kind: "preview-vs-app",
    capture: "frame",
    app: student("populated", { act: openAccount }),
    preview: { state: "populated", act: (page) => page.click(".as-pop-me summary") },
  }),
  ...[
    ["profile", ""],
    ["account", "/devices"],
    ["notifications", "/notifications"],
    ["appearance", "/appearance"],
    ["install", "/install"],
  ].flatMap(([tab, suffix]) =>
    byWindowRule({
      id: `student-settings-${tab}`,
      kind: "preview-vs-app",
      capture: "frame",
      app: student("populated", { path: `/student/settings${suffix}` }),
      preview: {
        state: "populated",
        act: async (page) => {
          await page.click('[data-a-open="as-settings"]')
          await page.click(`[data-a-tab="${tab}"]`)
        },
      },
    }),
  ),
]

export const SHELL_SCENES = [...TEACHER_SCENES, ...STUDENT_SCENES]

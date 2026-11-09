import { STUDENT_PROFILE, studentShellMocks, teacherShellMocks } from "./mocks.mjs"

export const NATIVE_HOME = { path: "/student", profile: STUDENT_PROFILE, mocks: studentShellMocks("populated") }
export const NATIVE_TEACHER_HOME = { surface: "teacher-overview", state: "populated", mocks: teacherShellMocks }

/** Each check: { id, platform, width (default 390), theme, app, run(page) }. */
export const NATIVE_CHECKS = [
  ...["ios", "android"].map((platform) => ({
    id: `native-${platform}-platform-resolves`,
    platform,
    width: 390,
    app: NATIVE_HOME,
    async run(page) {
      const got = await page.evaluate(() => document.documentElement.dataset.platform)
      if (got !== platform) throw new Error(`data-platform=${got}`)
    },
  })),
  {
    id: "native-other-keeps-design-a",
    width: 390,
    app: NATIVE_HOME,
    async run(page) {
      const got = await page.evaluate(() => document.documentElement.dataset.platform)
      if (got !== "other") throw new Error(`no UA override should resolve to other, got ${got}`)
    },
  },
]

import { test, expect } from "@playwright/test"
import { watchConsole } from "./console-errors"
import { injectSession, readSeed, type SeedAccount, type SeedContract } from "./seed"

/*
 * Tutoring smoke table (T00). One row per screen the tutoring build adds, each
 * checked the same cheap way: sign in as the row's role with a real seeded
 * session, open the path, and assert that
 *
 *   - the page has exactly one `h1` and it reads `heading`;
 *   - no loading skeleton is left on the page (`status` named "Loading");
 *   - no C-11 error state is showing (`StateView kind="error"` renders
 *     `role="alert"`, see `web/src/components/ui/state-views.tsx`);
 *   - nothing was written to the console as an error and no page error fired
 *     (`watchConsole`, the same filter every other spec uses).
 *
 * The table starts with one control row: an existing screen for an existing
 * role. It proves the harness (seed contract, session injection, assertions)
 * before any tutoring screen exists, and it is what the live probe at I0b
 * runs. The lead adds a row per screen at the integration rows (I6: T22 to
 * T24, I7: T26 to T28) as a hot patch to ROWS below; no screen task edits
 * this file.
 *
 * The roles here are the ones the seed contract already holds. A platform
 * admin account is not seeded yet, so the X-04 to X-07 rows need `ROLE_ACCOUNT`
 * to grow a `platform_admin` entry when T29 adds that account.
 */

type SmokeRole = "student" | "teacher" | "parent" | "school_admin"

interface SmokeRow {
  role: SmokeRole
  path: string
  /** The text of the page's single `h1`, exactly. */
  heading: string
}

const ROWS: readonly SmokeRow[] = [
  // Control row: T-02, the teacher's class list, long-standing and seeded.
  { role: "teacher", path: "/teacher/classes", heading: "Classes" },
  // I6: T22 to T24. Rows that need a seeded tutor or booking id (S-34, S-35, S-37, T-18)
  // and the public G-16/G-17 pages join when T29 seeds them.
  { role: "student", path: "/student/tutors", heading: "Tutors" },
  { role: "student", path: "/student/sessions", heading: "My sessions" },
  { role: "student", path: "/student/tutor-access", heading: "Tutors & your data" },
  { role: "teacher", path: "/teacher/tutoring", heading: "Tutoring" },
  { role: "teacher", path: "/teacher/tutoring/profile", heading: "Tutor profile" },
  { role: "teacher", path: "/teacher/tutoring/availability", heading: "Weekly availability" },
  { role: "teacher", path: "/teacher/tutoring/preview", heading: "Profile preview and reviews" },
  // I7: T26 to T28. T-20, P-05, P-06, P-08 and the admin rows need seeded ids or a platform
  // admin (T29).
  { role: "teacher", path: "/teacher/tutoring/students", heading: "My students" },
  { role: "parent", path: "/parent/tutors", heading: "Tutors" },
  // I6b: T26. T-20 (`/teacher/tutoring/students/:studentId`) joins when T29 seeds a granted student.
  { role: "teacher", path: "/teacher/tutoring/students", heading: "My students" },
]

const ROLE_ACCOUNT: Record<SmokeRole, (seed: SeedContract) => SeedAccount> = {
  student: (seed) => seed.students.correctedPaper,
  teacher: (seed) => seed.teacher,
  parent: (seed) => seed.parent,
  school_admin: (seed) => seed.schoolWithSeats.admin,
}

test("the smoke table has at least one row", () => {
  expect(ROWS.length).toBeGreaterThanOrEqual(1)
})

for (const row of ROWS) {
  test(`${row.role} opens ${row.path}: one h1 "${row.heading}", no console error, no error state`, async ({
    page,
  }) => {
    const seed = readSeed()
    const account = ROLE_ACCOUNT[row.role](seed)
    const errors = watchConsole(page)

    await injectSession(page, {
      accessToken: account.accessToken,
      userId: account.userId,
      role: row.role,
    })
    await page.goto(row.path)

    // `toHaveText` on a locator that matches two elements is a strict-mode
    // failure, so this also asserts that there is exactly one `h1`.
    await expect(page.locator("h1")).toHaveText(row.heading, { timeout: 15_000 })
    await expect(page.getByRole("status", { name: "Loading" })).toHaveCount(0, {
      timeout: 15_000,
    })
    await expect(page.getByRole("alert")).toHaveCount(0)

    expect(errors, `console/page errors: ${JSON.stringify(errors, null, 2)}`).toEqual([])
  })
}

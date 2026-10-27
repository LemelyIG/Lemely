import { test, expect } from "@playwright/test"
import { watchConsole } from "./console-errors"
import { injectSession, readSeed, type SeedAccount, type SeedContract } from "./seed"

/*
 * Tutoring smoke table (T00, extended by T32). One row per screen the tutoring
 * build adds, each checked the same cheap way: open the path (signed in as the
 * row's account, or signed out for the public pages), and assert that
 *
 *   - the page has exactly one `h1` and it reads `heading`;
 *   - no loading skeleton is left on the page (`status` named "Loading");
 *   - no C-11 error state is showing (`StateView kind="error"` renders
 *     `role="alert"`, see `web/src/components/ui/state-views.tsx`);
 *   - nothing was written to the console as an error and no page error fired
 *     (`watchConsole`, the same filter every other spec uses).
 *
 * A row names the session ROLE it signs in with (what the app routes on) and,
 * separately, an optional account key `as` (WHICH seeded account holds that
 * role). Without `as` the role's default account is used. `role: "none"` signs
 * nobody in: the public G-16 and G-17.
 *
 * A row's `path` and `heading` may be functions of the seed, because the ids
 * they need (a tutor profile, a booking, a grant, a report) exist only after
 * global setup has seeded, which is after this file is collected.
 */

type SmokeRole = "student" | "teacher" | "parent" | "school_admin" | "platform_admin" | "none"

/** Which seeded account holds the role, where the role's default is not the right one. */
type AccountKey = "tutoringStudent" | "child" | "tutor" | "admin"

type FromSeed<T> = T | ((seed: SeedContract) => T)

interface SmokeRow {
  role: SmokeRole
  as?: AccountKey
  /** The screen's SPEC id, for the test title of a row whose path needs a seeded id. */
  screen?: string
  path: FromSeed<string>
  /** The text of the page's single `h1`, exactly. */
  heading: FromSeed<string>
}

const resolve = <T>(value: FromSeed<T>, seed: SeedContract): T =>
  typeof value === "function" ? (value as (s: SeedContract) => T)(seed) : value

const tut = (seed: SeedContract) => seed.tutoring
const AMIRA = "Amira K."
const sessionHeading = (seed: SeedContract) => `${tut(seed).subjectName} with ${AMIRA}`

const ROWS: readonly SmokeRow[] = [
  // Control row: T-02, the teacher's class list, long-standing and seeded.
  { role: "teacher", path: "/teacher/classes", heading: "Classes" },
  // I6: T22 to T24, the screens that need no id.
  { role: "student", path: "/student/tutors", heading: "Tutors" },
  { role: "student", path: "/student/sessions", heading: "My sessions" },
  { role: "student", path: "/student/tutor-access", heading: "Tutors & your data" },
  { role: "teacher", path: "/teacher/tutoring", heading: "Tutoring" },
  { role: "teacher", path: "/teacher/tutoring/profile", heading: "Tutor profile" },
  { role: "teacher", path: "/teacher/tutoring/availability", heading: "Weekly availability" },
  { role: "teacher", path: "/teacher/tutoring/preview", heading: "Profile preview and reviews" },
  // I7: T26 to T28, the screens that need no id.
  { role: "teacher", path: "/teacher/tutoring/students", heading: "My students" },
  { role: "parent", path: "/parent/tutors", heading: "Tutors" },

  // T32: the rows that need a seeded id. The booking student, with the tutor's profile id.
  {
    role: "student",
    as: "tutoringStudent",
    screen: "S-34",
    path: (s) => `/student/tutors/${tut(s).tutors.sufficient.tutorProfileId}`,
    heading: AMIRA,
  },
  {
    role: "student",
    as: "tutoringStudent",
    screen: "S-35",
    path: (s) => `/student/tutors/${tut(s).tutors.sufficient.tutorProfileId}/book`,
    heading: `Book a session with ${AMIRA}`,
  },
  {
    role: "student",
    as: "tutoringStudent",
    screen: "S-37",
    path: (s) => `/student/sessions/${tut(s).bookings.accepted}`,
    heading: sessionHeading,
  },
  // The tutor's own side: Amira, the tutor of every seeded booking and grant.
  {
    role: "teacher",
    as: "tutor",
    screen: "T-18",
    path: (s) => `/teacher/tutoring/sessions/${tut(s).bookings.accepted}`,
    heading: (s) => `Session with ${s.tutoring.student.displayName}`,
  },
  {
    role: "teacher",
    as: "tutor",
    screen: "T-20",
    path: (s) => `/teacher/tutoring/students/${tut(s).grants.live.studentUserId}`,
    // T-20 reuses T-05's composition, whose h1 is the student's name.
    heading: (s) => s.students.declining.displayName,
  },
  // The parent and the child they are linked to (`seed.parent` links `students.declining`).
  {
    role: "parent",
    screen: "P-05",
    path: (s) => `/parent/children/${s.students.declining.userId}/tutoring`,
    heading: (s) => `${s.students.declining.displayName}'s tutoring`,
  },
  {
    role: "parent",
    screen: "P-06",
    path: (s) =>
      `/parent/children/${s.students.declining.userId}/sessions/${tut(s).bookings.child.parentAccepted}`,
    heading: sessionHeading,
  },
  {
    role: "parent",
    screen: "P-08",
    path: (s) => `/parent/children/${s.students.declining.userId}/tutor-access`,
    heading: (s) => `Who ${s.students.declining.displayName} shares progress with`,
  },
  // The platform admin (X-04 to X-07).
  { role: "platform_admin", as: "admin", path: "/platform/tutors", heading: "Tutors" },
  {
    role: "platform_admin",
    as: "admin",
    screen: "X-05",
    path: (s) => `/platform/tutors/${tut(s).tutors.sufficient.tutorProfileId}`,
    heading: AMIRA,
  },
  { role: "platform_admin", as: "admin", path: "/platform/moderation", heading: "Moderation" },
  { role: "platform_admin", as: "admin", path: "/platform/reports", heading: "Reports" },
  {
    role: "platform_admin",
    as: "admin",
    screen: "X-07 detail",
    path: (s) => `/platform/reports/${tut(s).reports.openSafety.reportId}`,
    heading: "Booking report",
  },
  // The public pages: nobody is signed in (G-16, G-17).
  { role: "none", path: "/tutors", heading: "Tutors" },
  {
    role: "none",
    screen: "G-17",
    path: (s) => `/tutors/${tut(s).tutors.sufficient.tutorProfileId}`,
    heading: AMIRA,
  },
]

/** The default account behind each signed-in role. */
const ROLE_ACCOUNT: Record<Exclude<SmokeRole, "none">, (seed: SeedContract) => SeedAccount> = {
  student: (seed) => seed.students.correctedPaper,
  teacher: (seed) => seed.teacher,
  parent: (seed) => seed.parent,
  school_admin: (seed) => seed.schoolWithSeats.admin,
  platform_admin: (seed) => seed.tutoring.platformAdmin,
}

/** The accounts a row can pick with `as`. */
const NAMED_ACCOUNT: Record<AccountKey, (seed: SeedContract) => SeedAccount> = {
  tutoringStudent: (seed) => seed.tutoring.student,
  child: (seed) => seed.students.declining,
  tutor: (seed) => seed.tutoring.tutors.sufficient,
  admin: (seed) => seed.tutoring.platformAdmin,
}

test("the smoke table has at least one row", () => {
  expect(ROWS.length).toBeGreaterThanOrEqual(1)
})

test("no two smoke rows are the same screen for the same account", () => {
  // The test titles print the path, or the screen id for a row that needs a seeded id.
  const keys = ROWS.map(
    (row) => `${row.role}|${row.as ?? ""}|${typeof row.path === "string" ? row.path : row.screen}`,
  )
  expect(new Set(keys).size).toBe(keys.length)
})

for (const row of ROWS) {
  const title = typeof row.path === "string" ? row.path : (row.screen ?? "a screen with a seeded id")
  const who = row.role === "none" ? "a signed-out visitor" : `${row.role}${row.as ? ` (${row.as})` : ""}`
  test(`${who} opens ${title}: one h1, no console error, no error state`, async ({ page }) => {
    const seed = readSeed()
    const path = resolve(row.path, seed)
    const heading = resolve(row.heading, seed)
    const errors = watchConsole(page)

    if (row.role !== "none") {
      const account = row.as ? NAMED_ACCOUNT[row.as](seed) : ROLE_ACCOUNT[row.role](seed)
      await injectSession(page, {
        accessToken: account.accessToken,
        userId: account.userId,
        role: row.role,
      })
    }
    await page.goto(path)

    // `toHaveText` on a locator that matches two elements is a strict-mode
    // failure, so this also asserts that there is exactly one `h1`.
    await expect(page.locator("h1"), `h1 of ${path}`).toHaveText(heading, { timeout: 15_000 })
    await expect(page.getByRole("status", { name: "Loading" })).toHaveCount(0, {
      timeout: 15_000,
    })
    await expect(page.getByRole("alert")).toHaveCount(0)

    expect(errors, `console/page errors: ${JSON.stringify(errors, null, 2)}`).toEqual([])
  })
}

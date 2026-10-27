import { test, expect, type Page } from "@playwright/test"
import { watchConsole } from "./console-errors"
import { injectSession, readSeed } from "./seed"

/*
 * E2E 1 (SPEC §e.4): a student discovers a tutor, opens the profile, books a
 * session, the tutor accepts it, and both see it.
 *
 * Seeded accounts (T29): `tutoring.discover.student` (verified, nothing booked,
 * the safety notice not yet acknowledged) books `tutoring.tutors.sufficient`
 * ("Amira K.": listed, every day 15:00-21:00, virtual and in person, five past
 * students so her results show). `tutors.insufficient` ("Omar H.": weekdays only,
 * virtual only, three past students so his results are hidden) is the contrast.
 *
 * The three tests are one story and run in order: the student books, the tutor
 * accepts in a SECOND browser context, then both sides read the accepted session.
 * They are not `describe.serial`, so a failure in the tutor's part does not hide the
 * student's; each later test says in its first assertion which earlier step it
 * needs. The afterAll cancels a request left waiting so that the other journeys
 * that use the same student (the double-booking race) start clean.
 */

const BACKEND_URL = "http://127.0.0.1:8000"
const MEETING_LINK = "https://meet.google.com/abc-defg-hij"
const FIRST_NOTE = "Could we start with circuits and series resistors?"

const BOOKING_PATH = /\/student\/sessions\/([0-9a-f-]{36})$/

/** Opens a fresh page for `userId`'s token in its own browser context. */
async function openAs(
  browser: import("@playwright/test").Browser,
  who: { accessToken: string; userId: string },
  role: string,
): Promise<Page> {
  const context = await browser.newContext()
  const page = await context.newPage()
  await injectSession(page, { accessToken: who.accessToken, userId: who.userId, role })
  return page
}

test.describe("E2E 1: a student discovers a tutor, books a session, the tutor accepts it", () => {
  let bookingId = ""

  test.afterAll(async ({ playwright }) => {
    if (bookingId === "") return
    const seed = readSeed()
    const request = await playwright.request.newContext({
      baseURL: BACKEND_URL,
      extraHTTPHeaders: { Authorization: `Bearer ${seed.tutoring.discover.student.accessToken}` },
    })
    const current = await request.get(`/api/student/bookings/${bookingId}`)
    const booking = (await current.json()) as { effectiveState: string }
    if (booking.effectiveState === "requested") {
      await request.post(`/api/student/bookings/${bookingId}/cancel`, { data: {} })
    }
    await request.dispose()
  })

  test("the student finds Amira in the directory, signs in, filters, reads her results and requests a session", async ({
    page,
  }) => {
    const seed = readSeed()
    const errors = watchConsole(page)
    const { tutors, discover, subjectName, outcomes } = seed.tutoring
    const amira = tutors.sufficient
    const omar = tutors.insufficient
    const student = discover.student

    await test.step("the public directory lists both seeded tutors and offers sign in", async () => {
      await page.goto("/tutors")
      await expect(page.locator("h1")).toHaveText("Tutors", { timeout: 15_000 })
      await expect(page.getByRole("link", { name: amira.publicName })).toBeVisible({ timeout: 15_000 })
      await expect(page.getByRole("link", { name: omar.publicName })).toBeVisible()
    })

    await test.step("the public card shows the tutor and sends a visitor to sign in", async () => {
      await page.getByRole("link", { name: amira.publicName }).click()
      await expect(page).toHaveURL(`/tutors/${amira.tutorProfileId}`)
      await expect(page.locator("h1")).toHaveText(amira.publicName, { timeout: 15_000 })
      const signIn = page.getByRole("link", { name: "Sign in to book" })
      await expect(signIn).toHaveAttribute("href", /^\/login\?next=%2Fstudent%2Ftutors%2F/)
    })

    await test.step("sign in from the directory with the real login form", async () => {
      await page.goto("/tutors")
      await page.getByRole("link", { name: "Sign in", exact: true }).click()
      await expect(page).toHaveURL(/\/login/)
      await page.getByLabel("Email").fill(student.email)
      await page.getByLabel("Password").fill(student.password)
      await page.getByRole("button", { name: /sign in/i }).click()
      await expect(page).toHaveURL(/\/student$/, { timeout: 15_000 })
    })

    await test.step("the student directory filters by subject and availability", async () => {
      await page.getByRole("link", { name: "Tutors", exact: true }).first().click()
      await expect(page).toHaveURL(/\/student\/tutors/)
      await expect(page.locator("h1")).toHaveText("Tutors", { timeout: 15_000 })
      await expect(page.getByRole("link", { name: amira.publicName })).toBeVisible({ timeout: 15_000 })
      await expect(page.getByRole("link", { name: omar.publicName })).toBeVisible()

      await page.getByLabel("Subject").selectOption({ label: subjectName })
      // Saturday evening: Amira teaches every day 15:00-21:00, Omar weekdays 16:00-19:00 only.
      await page.getByRole("checkbox", { name: "Saturday" }).check()
      await page.getByRole("checkbox", { name: /^Evening/ }).check()
      await expect(page.getByRole("link", { name: omar.publicName })).toHaveCount(0, { timeout: 15_000 })
      await expect(page.getByRole("link", { name: amira.publicName })).toBeVisible()
    })

    await test.step("Amira's profile shows her results, weekly times and the actions", async () => {
      await page.getByRole("link", { name: amira.publicName }).click()
      await expect(page).toHaveURL(`/student/tutors/${amira.tutorProfileId}`)
      await expect(page.locator("h1")).toHaveText(amira.publicName, { timeout: 15_000 })
      await expect(page.getByRole("heading", { name: "Results with this tutor" })).toBeVisible()
      await expect(page.getByRole("heading", { name: "Change in grade while with this tutor" })).toBeVisible()

      // The grade counts the seed derived from the same cohort (A1 B2 C2, n = 5), read from the table.
      await page.getByRole("button", { name: "Show as table" }).first().click()
      const sufficient = outcomes.sufficient
      for (const [grade, count] of Object.entries(sufficient.buckets)) {
        const escaped = grade.replace("*", "\\*")
        await expect(
          page.getByRole("row", { name: new RegExp(`^${escaped}\\s+${count}$`) }),
          `grade ${grade} has ${count} student(s)`,
        ).toBeVisible()
      }
      await expect(page.getByRole("link", { name: "Book a session" })).toBeVisible()
      await expect(page.getByRole("button", { name: "Share my progress" })).toBeVisible()
    })

    await test.step("Omar's results are hidden, with the plain explanation", async () => {
      await page.goto(`/student/tutors/${omar.tutorProfileId}`)
      await expect(page.locator("h1")).toHaveText(omar.publicName, { timeout: 15_000 })
      await expect(page.getByText("Results are hidden for now")).toBeVisible()
      await expect(page.getByRole("button", { name: "Show as table" })).toHaveCount(0)
    })

    await test.step("booking: the safety notice comes first, then one request goes through", async () => {
      await page.goto(`/student/tutors/${amira.tutorProfileId}`)
      await page.getByRole("link", { name: "Book a session" }).click()
      await expect(page).toHaveURL(`/student/tutors/${amira.tutorProfileId}/book`)
      await expect(page.locator("h1")).toHaveText(`Book a session with ${amira.publicName}`, {
        timeout: 15_000,
      })

      const notice = page.getByRole("dialog", { name: "Before your first session" })
      await expect(notice).toBeVisible({ timeout: 15_000 })
      await notice.getByRole("button", { name: "I understand" }).click()
      await expect(notice).toBeHidden()

      await page.getByRole("radio", { name: "Virtual" }).check()
      // The first day with times, its first time.
      const times = page.getByRole("group", { name: /^Times on/ }).getByRole("radio")
      await expect(times.first()).toBeAttached({ timeout: 15_000 })
      await times.first().check({ force: true })
      await page.getByLabel("First note (optional)").fill(FIRST_NOTE)

      await expect(page.getByText("Not chosen yet")).toHaveCount(0)
      await page.getByRole("button", { name: "Send request" }).click()

      await expect(page).toHaveURL(BOOKING_PATH, { timeout: 15_000 })
      bookingId = BOOKING_PATH.exec(page.url())?.[1] ?? ""
      expect(bookingId).not.toBe("")
      await expect(page.locator("h1")).toHaveText(`${subjectName} with ${amira.publicName}`, {
        timeout: 15_000,
      })
      await expect(page.getByLabel("Session status: Waiting for reply")).toBeVisible()
    })

    await test.step("the request is listed under My sessions", async () => {
      await page.goto("/student/sessions")
      await expect(
        page.locator(`a[href="/student/sessions/${bookingId}"]`),
        "the new request is on the Upcoming tab",
      ).toBeVisible({ timeout: 15_000 })
    })

    expect(errors, `console/page errors: ${JSON.stringify(errors, null, 2)}`).toEqual([])
  })

  test("the tutor sees the request and accepts it with a meeting link", async ({ browser }) => {
    const seed = readSeed()
    const amira = seed.tutoring.tutors.sufficient
    expect(bookingId, "the student's request from the first test").not.toBe("")
    const page = await openAs(browser, amira, "teacher")
    const errors = watchConsole(page)

    await page.goto("/teacher/tutoring")
    await expect(page.locator("h1")).toHaveText("Tutoring", { timeout: 15_000 })
    const accept = page.locator(`a[href="/teacher/tutoring/sessions/${bookingId}#accept"]`)
    await expect(accept, "the request is waiting under Requests").toBeVisible({ timeout: 15_000 })
    await accept.click()

    await expect(page.locator("h1")).toContainText("Session with", { timeout: 15_000 })
    await page.getByLabel("Meeting link").fill(MEETING_LINK)
    await page.getByRole("button", { name: "Accept request" }).click()

    await expect(page.getByLabel("Session status: Confirmed")).toBeVisible({ timeout: 15_000 })
    await expect(page.getByRole("link", { name: MEETING_LINK })).toBeVisible()

    // The accepted session is under the tutor's Upcoming list.
    await page.goto("/teacher/tutoring")
    await expect(
      page.locator(`a[href="/teacher/tutoring/sessions/${bookingId}"]`).first(),
      "the accepted session is listed as upcoming",
    ).toBeVisible({ timeout: 15_000 })
    await expect(accept).toHaveCount(0)

    expect(errors, `console/page errors: ${JSON.stringify(errors, null, 2)}`).toEqual([])
    await page.context().close()
  })

  test("the student sees the confirmed session with the meeting link", async ({ browser }) => {
    const seed = readSeed()
    const { discover, subjectName, tutors } = seed.tutoring
    expect(bookingId, "the student's request from the first test").not.toBe("")
    const page = await openAs(browser, discover.student, "student")
    const errors = watchConsole(page)

    await page.goto(`/student/sessions/${bookingId}`)
    await expect(page.locator("h1")).toHaveText(`${subjectName} with ${tutors.sufficient.publicName}`, {
      timeout: 15_000,
    })
    await expect(page.getByLabel("Session status: Confirmed")).toBeVisible()
    const link = page.getByRole("link", { name: /Open the meeting link/ })
    await expect(link).toHaveAttribute("href", MEETING_LINK)
    await expect(link).toHaveAttribute("rel", /noopener/)
    await expect(page.getByText("You can cancel up to 24 hours before the start.")).toBeVisible()

    expect(errors, `console/page errors: ${JSON.stringify(errors, null, 2)}`).toEqual([])
    await page.context().close()
  })
})

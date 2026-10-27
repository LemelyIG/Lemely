import { test, expect, type APIRequest, type Browser, type Page } from "@playwright/test"
import { watchConsole } from "./console-errors"
import { injectSession, readSeed } from "./seed"

/*
 * E2E 4 (SPEC §e.4): a parent books for their child. Parent `/parent/tutors` ->
 * book (no first-note field) -> the child sees the session on S-36 -> the
 * parent's P-06 has no composer -> the booking shows for the tutor.
 *
 * Seeded accounts (T29): `seed.parent` (verified, linked to `students.declining`)
 * books `tutors.insufficient` ("Omar H.": weekdays 16:00-19:00, virtual only, one
 * subject, so the subject and the way to meet are already chosen). The child
 * already has a request waiting with Amira; one waiting request per student and
 * tutor is the rule, so this journey uses Omar. The tests are one story in order.
 */

const SESSION_PATH = /\/parent\/children\/([0-9a-f-]{36})\/sessions\/([0-9a-f-]{36})$/

async function openAs(
  browser: Browser,
  who: { accessToken: string; userId: string },
  role: string,
): Promise<Page> {
  const context = await browser.newContext()
  const page = await context.newPage()
  await injectSession(page, { accessToken: who.accessToken, userId: who.userId, role })
  return page
}

const BACKEND_URL = "http://127.0.0.1:8000"

/**
 * The child's earliest waiting request with this tutor, read from the API. A failed test
 * discards its worker, and module state with it, so the later tests find the booking again.
 */
async function earliestRequest(api: APIRequest, token: string, tutorId: string): Promise<string> {
  const request = await api.newContext({
    baseURL: BACKEND_URL,
    extraHTTPHeaders: { Authorization: `Bearer ${token}` },
  })
  const response = await request.get("/api/student/bookings", { params: { when: "upcoming" } })
  expect(response.status()).toBe(200)
  const body = (await response.json()) as {
    items: { bookingId: string; startsAt: string; effectiveState: string; tutor: { tutorId: string } }[]
  }
  await request.dispose()
  const mine = body.items
    .filter((b) => b.tutor.tutorId === tutorId && b.effectiveState === "requested")
    .sort((a, b) => Date.parse(a.startsAt) - Date.parse(b.startsAt))
  return mine[0]?.bookingId ?? ""
}

test.describe("E2E 4: a parent books a session for their child", () => {
  test("the parent finds Omar, books for the child without a first note, and lands on the read-only session", async ({
    browser,
    playwright,
  }) => {
    const seed = readSeed()
    const { tutors, subjectName } = seed.tutoring
    const omar = tutors.insufficient
    const child = seed.students.declining
    const page = await openAs(browser, seed.parent, "parent")
    const errors = watchConsole(page)

    await test.step("the parent's directory lists the tutors", async () => {
      await page.goto("/parent/tutors")
      await expect(page.locator("h1")).toHaveText("Tutors", { timeout: 15_000 })
      await expect(page.getByRole("link", { name: omar.publicName })).toBeVisible({ timeout: 15_000 })
    })

    await test.step("a tutor's page offers Book and Report, and none of the student-only actions", async () => {
      await page.getByRole("link", { name: omar.publicName }).click()
      await expect(page).toHaveURL(new RegExp(`/parent/tutors/${omar.tutorProfileId}`))
      await expect(page.locator("h1")).toHaveText(omar.publicName, { timeout: 15_000 })
      await expect(page.getByRole("link", { name: "Book a session" })).toBeVisible()
      await expect(page.getByRole("button", { name: "Report" })).toBeVisible()
      await expect(page.getByRole("button", { name: "Share my progress" })).toHaveCount(0)
      await expect(page.getByRole("button", { name: "Block" })).toHaveCount(0)
    })

    await test.step("the booking form has the child selector and no first note, and no safety notice", async () => {
      await page.getByRole("link", { name: "Book a session" }).click()
      await expect(page.locator("h1")).toHaveText(`Book a session with ${omar.publicName}`, {
        timeout: 15_000,
      })
      await expect(page.getByLabel("Booking for")).toHaveValue(child.userId)
      await expect(page.getByLabel("Booking for").locator("option:checked")).toHaveText(child.displayName)
      await expect(page.getByLabel(/First note/)).toHaveCount(0)
      await expect(page.getByRole("dialog")).toHaveCount(0)
      // The counting notice is about the child.
      await expect(page.getByRole("note")).toContainText(child.displayName)
    })

    await test.step("pick the first time and send the request", async () => {
      const times = page.getByRole("group", { name: /^Times on/ }).getByRole("radio")
      await expect(times.first()).toBeAttached({ timeout: 15_000 })
      await times.first().check({ force: true })
      await expect(page.getByText("Not chosen yet")).toHaveCount(0)
      await page.getByRole("button", { name: "Send request" }).click()
      await expect(page).toHaveURL(SESSION_PATH, { timeout: 15_000 })
      const match = SESSION_PATH.exec(page.url())
      expect(match?.[1], "the session is under the child").toBe(child.userId)
      const bookingId = match?.[2] ?? ""
      expect(bookingId).not.toBe("")
      expect(await earliestRequest(playwright.request, child.accessToken, omar.tutorProfileId)).toBe(bookingId)
    })

    await test.step("P-06 shows the request read-only: notes are the child's and the tutor's", async () => {
      await expect(page.locator("h1")).toHaveText(`${subjectName} with ${omar.publicName}`, {
        timeout: 15_000,
      })
      await expect(page.getByText("Waiting for reply", { exact: true })).toBeVisible()
      await expect(page.getByText(`Notes are between ${child.displayName} and the tutor.`)).toBeVisible()
      await expect(page.getByLabel("Write a note")).toHaveCount(0)
      await expect(page.getByRole("button", { name: "Send note" })).toHaveCount(0)
      // The parent made this request, so they may cancel it.
      await expect(page.getByRole("button", { name: "Withdraw request" })).toBeVisible()
    })

    expect(errors, `console/page errors: ${JSON.stringify(errors, null, 2)}`).toEqual([])
    await page.context().close()
  })

  test("the child sees the session under My sessions and is told a parent booked it", async ({
    browser,
    playwright,
  }) => {
    const seed = readSeed()
    const { tutors, subjectName } = seed.tutoring
    const child = seed.students.declining
    const bookingId = await earliestRequest(playwright.request, child.accessToken, tutors.insufficient.tutorProfileId)
    expect(bookingId, "the parent's request from the first test").not.toBe("")
    const page = await openAs(browser, child, "student")
    const errors = watchConsole(page)

    await page.goto("/student/sessions")
    await expect(page.locator("h1")).toHaveText("My sessions", { timeout: 15_000 })
    const row = page.locator(`a[href="/student/sessions/${bookingId}"]`)
    await expect(row).toBeVisible({ timeout: 15_000 })
    await row.click()

    await expect(page.locator("h1")).toHaveText(`${subjectName} with ${tutors.insufficient.publicName}`, {
      timeout: 15_000,
    })
    await expect(page.getByText("A parent booked this session for you.")).toBeVisible()

    expect(errors, `console/page errors: ${JSON.stringify(errors, null, 2)}`).toEqual([])
    await page.context().close()
  })

  test("the tutor sees the request, as from the student", async ({ browser, playwright }) => {
    const seed = readSeed()
    const omar = seed.tutoring.tutors.insufficient
    const bookingId = await earliestRequest(playwright.request, seed.students.declining.accessToken, omar.tutorProfileId)
    expect(bookingId, "the parent's request from the first test").not.toBe("")
    const page = await openAs(browser, omar, "teacher")
    const errors = watchConsole(page)

    await page.goto("/teacher/tutoring")
    await expect(page.locator("h1")).toHaveText("Tutoring", { timeout: 15_000 })
    await expect(
      page.locator(`a[href="/teacher/tutoring/sessions/${bookingId}#accept"]`),
      "the request waits under Requests",
    ).toBeVisible({ timeout: 15_000 })

    await page.goto(`/teacher/tutoring/sessions/${bookingId}`)
    await expect(page.locator("h1")).toContainText("Session with", { timeout: 15_000 })
    // A tutor never learns that a parent link exists (SC-9): whoever asked, it is "the student".
    await expect(page.getByText("the student", { exact: true })).toBeVisible()
    // (The notes thread's fixed line "This student's parents can read these notes." is for every
    // student and says nothing about this one; what must not appear is who made the request.)
    await expect(page.getByRole("main").getByText(/A parent booked|Booked by|booked by a parent/i)).toHaveCount(0)

    expect(errors, `console/page errors: ${JSON.stringify(errors, null, 2)}`).toEqual([])
    await page.context().close()
  })
})

import { test, expect, type APIRequest, type Browser, type Page } from "@playwright/test"
import { watchConsole } from "./console-errors"
import { injectSession, readSeed } from "./seed"

/*
 * E2E 3 (SPEC §e.4): consent revoked. The student stops sharing on S-38; the
 * tutor reloads the student's page (T-20) and sees the "no longer shared" state,
 * no data, and NO new audit row is written.
 *
 * Seeded accounts (T29): `tutoring.student` (verified, onboarded) with
 * `tutoring.grants.revocable` to `tutors.sufficient` (Amira K.). The live grant
 * of the parent's child (`grants.live`) is never touched: other journeys and the
 * smoke table read it.
 *
 * "No new audit row" is read from the student's own log (S11,
 * `GET /api/student/tutor-access-log`, every page): the count after the tutor's
 * denied reload equals the count at the moment the student stopped sharing. A
 * positive control comes first: while sharing was live the tutor's visit DID add
 * rows, so an unchanged count after the revocation is not a log that never moves.
 */

const BACKEND_URL = "http://127.0.0.1:8000"

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

/** Every entry of the student's access log, across pages. */
async function auditRows(api: APIRequest, token: string): Promise<{ tutorName: string; action: string }[]> {
  const request = await api.newContext({
    baseURL: BACKEND_URL,
    extraHTTPHeaders: { Authorization: `Bearer ${token}` },
  })
  const rows: { tutorName: string; action: string }[] = []
  let cursor: string | null = null
  for (let guard = 0; guard < 50; guard += 1) {
    const response = await request.get("/api/student/tutor-access-log", {
      params: cursor ? { cursor } : {},
    })
    expect(response.status(), "the student reads their own access log").toBe(200)
    const body = (await response.json()) as {
      items: { tutorName: string; action: string }[]
      nextCursor: string | null
    }
    rows.push(...body.items)
    cursor = body.nextCursor
    if (cursor === null) break
  }
  await request.dispose()
  return rows
}

test("the student stops sharing; the tutor's reload is denied with no data and no new audit row", async ({
  browser,
  playwright,
}) => {
  const seed = readSeed()
  const { student, tutors, grants } = seed.tutoring
  const amira = tutors.sufficient
  const grant = grants.revocable
  expect(grant.studentUserId, "the revocable grant belongs to the booking student").toBe(student.userId)

  const tutorPage = await openAs(browser, amira, "teacher")
  const studentPage = await openAs(browser, student, "student")
  const tutorErrors = watchConsole(tutorPage)
  const studentErrors = watchConsole(studentPage)
  const studentPath = `/teacher/tutoring/students/${student.userId}`

  let rowsBeforeVisit = 0
  let rowsAtRevoke = 0

  await test.step("while sharing is live the tutor lists the student and opens their page", async () => {
    rowsBeforeVisit = (await auditRows(playwright.request, student.accessToken)).length

    await tutorPage.goto("/teacher/tutoring/students")
    await expect(tutorPage.locator("h1")).toHaveText("My students", { timeout: 15_000 })
    const row = tutorPage.locator(`a[href="${studentPath}"]`)
    await expect(row).toBeVisible({ timeout: 15_000 })
    await row.click()

    await expect(tutorPage.locator("h1")).toHaveText(student.displayName, { timeout: 15_000 })
    await expect(tutorPage.getByText(`${student.displayName} shared this with you on`)).toBeVisible()
  })

  await test.step("positive control: that live visit wrote audit rows the student can see", async () => {
    const rows = await auditRows(playwright.request, student.accessToken)
    expect(rows.length, "the tutor's list and detail reads were recorded").toBeGreaterThanOrEqual(
      rowsBeforeVisit + 2,
    )
    const mine = rows.filter((r) => r.tutorName === amira.publicName)
    expect(mine.map((r) => r.action).sort()).toEqual(expect.arrayContaining(["detail", "list"]))
  })

  await test.step("the student stops sharing on Tutors & your data", async () => {
    await studentPage.goto("/student/tutor-access")
    await expect(studentPage.locator("h1")).toHaveText("Tutors & your data", { timeout: 15_000 })
    const sharing = studentPage.getByRole("region", { name: "Sharing" })
    await expect(sharing.getByRole("link", { name: amira.publicName })).toBeVisible({ timeout: 15_000 })
    await studentPage.getByRole("button", { name: `Stop sharing with ${amira.publicName}` }).click()

    const sheet = studentPage.getByRole("dialog", { name: `Stop sharing with ${amira.publicName}?` })
    await expect(sheet).toBeVisible()
    await expect(
      sheet.getByText("They can't see your progress through Lemely's tutoring pages from now on."),
    ).toBeVisible()
    await sheet.getByRole("button", { name: "Stop sharing" }).click()
    await expect(sheet).toBeHidden({ timeout: 15_000 })

    await expect(sharing.getByText("You aren't sharing your progress with any tutor.")).toBeVisible({
      timeout: 15_000,
    })
    await expect(sharing.getByRole("button", { name: /Show earlier sharing \(1\)/ })).toBeVisible()
    rowsAtRevoke = (await auditRows(playwright.request, student.accessToken)).length
  })

  await test.step("the tutor reloads the student's page: one sentence, no data", async () => {
    await tutorPage.reload()
    await expect(
      tutorPage.getByText(`${student.displayName}'s progress is no longer shared with you.`),
    ).toBeVisible({ timeout: 15_000 })
    await expect(tutorPage.getByText("shared this with you on")).toHaveCount(0)
    await expect(tutorPage.getByRole("heading", { name: student.displayName })).toHaveCount(0)
    // The one page-level heading is the hidden one of the route; nothing of the student is drawn.
    await expect(tutorPage.locator("h1")).toHaveText("Student progress")
    await expect(tutorPage.getByRole("button", { name: "Try again" })).toHaveCount(0)
  })

  await test.step("the API agrees: access_ended, and the tutor's list no longer holds the student", async () => {
    const request = await playwright.request.newContext({
      baseURL: BACKEND_URL,
      extraHTTPHeaders: { Authorization: `Bearer ${amira.accessToken}` },
    })
    const detail = await request.get(`/api/tutor/students/${student.userId}`)
    expect(detail.status()).toBe(403)
    expect(JSON.stringify(await detail.json())).toContain("access_ended")
    await request.dispose()

    await tutorPage.goto("/teacher/tutoring/students")
    await expect(tutorPage.locator("h1")).toHaveText("My students", { timeout: 15_000 })
    await expect(tutorPage.locator(`a[href="${studentPath}"]`)).toHaveCount(0)
  })

  await test.step("no new audit row appeared after the revocation", async () => {
    const after = await auditRows(playwright.request, student.accessToken)
    expect(after.length, "audit rows after the denied reads equal the count at revocation").toBe(rowsAtRevoke)
  })

  await test.step("the student still sees the earlier visits, and the grant as ended", async () => {
    await studentPage.reload()
    const log = studentPage.getByRole("region", { name: "Who looked" })
    await expect(log.getByText(`${amira.publicName} viewed your progress`).first()).toBeVisible({
      timeout: 15_000,
    })
    await studentPage.getByRole("button", { name: /Show earlier sharing/ }).click()
    await expect(studentPage.getByText("You stopped sharing")).toBeVisible()
  })

  expect(tutorErrors, `tutor console/page errors: ${JSON.stringify(tutorErrors, null, 2)}`).toEqual([])
  expect(studentErrors, `student console/page errors: ${JSON.stringify(studentErrors, null, 2)}`).toEqual([])
  await tutorPage.context().close()
  await studentPage.context().close()
})

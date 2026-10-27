import { test, expect, type Browser, type Page } from "@playwright/test"
import { watchConsole } from "./console-errors"
import { injectSession, readSeed } from "./seed"

/*
 * E2E 2 (SPEC §e.4): a tutor onboards, a platform admin approves, the tutor is
 * listed, a student shares their progress, the tutor opens the student's page,
 * and the student's S-38 and the parent's P-08 show the visit.
 *
 * Seeded accounts (T29): `tutoring.tutors.draft` ("Layla S.", a verified teacher
 * with a complete draft: card, weekly times, no documents, no About text),
 * `tutoring.platformAdmin`, and the parent's child `students.declining`
 * (verified, onboarded, linked to `seed.parent`), who shares with Layla.
 *
 * The tests are one story in order. They are not `describe.serial`, so a failure in
 * one does not hide the next from the run; each later test says in its first
 * assertion which earlier step it needs.
 *
 * Why the child and not the booking student: P-08 is the PARENT's page, and the
 * seeded parent is linked to the child only.
 */

const ABOUT = "I teach IGCSE Physics in small groups and one to one, starting from the student's last marked paper."

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

test.describe("E2E 2: tutor onboarding, approval, sharing and the visit", () => {
  test("a draft tutor completes the About step and sends the profile for review", async ({ browser }) => {
    const seed = readSeed()
    const layla = seed.tutoring.tutors.draft
    const page = await openAs(browser, layla, "teacher")
    const errors = watchConsole(page)

    await test.step("the profile screen says it is a draft", async () => {
      await page.goto("/teacher/tutoring/profile")
      await expect(page.locator("h1")).toHaveText("Tutor profile", { timeout: 15_000 })
      await expect(page.getByText("Your profile is a draft")).toBeVisible()
    })

    await test.step("About: write the bio and continue", async () => {
      await page.getByRole("navigation", { name: "Profile steps" }).getByRole("button", { name: "About" }).click()
      await expect(page.getByRole("heading", { level: 2, name: "2. About" })).toBeVisible()
      await page.getByLabel("About you").fill(ABOUT)
      await page.getByRole("button", { name: "Save and continue" }).click()
      await expect(page.getByRole("heading", { level: 2, name: "3. Evidence" })).toBeVisible({ timeout: 15_000 })
    })

    await test.step("Evidence and Availability are passed through; the seeded weekly times are there", async () => {
      await page.getByRole("button", { name: "Continue" }).click()
      await expect(page.getByRole("heading", { level: 2, name: "4. Availability" })).toBeVisible()
      await page.getByRole("button", { name: "Continue" }).click()
      await expect(page.getByRole("heading", { level: 2, name: "5. Submit" })).toBeVisible()
    })

    await test.step("Submit: nothing is missing, and sending puts the profile under review", async () => {
      await expect(page.getByText("Everything Lemely needs is in place.")).toBeVisible()
      await page.getByRole("button", { name: "Send for review" }).click()
      await expect(page.getByRole("heading", { name: "Sent for review" })).toBeVisible({ timeout: 15_000 })
      await expect(page.getByText("Lemely is reviewing your profile.").first()).toBeVisible()
    })

    await test.step("the tutoring home shows it as under review", async () => {
      await page.goto("/teacher/tutoring")
      await expect(page.locator("h1")).toHaveText("Tutoring", { timeout: 15_000 })
      await expect(page.getByText("Under review").first()).toBeVisible()
    })

    expect(errors, `console/page errors: ${JSON.stringify(errors, null, 2)}`).toEqual([])
    await page.context().close()
  })

  test("the platform admin finds the profile in the queue and approves it without the documents-seen mark (no files)", async ({
    browser,
    page: signedOut,
  }) => {
    const seed = readSeed()
    const { platformAdmin, tutors } = seed.tutoring
    const layla = tutors.draft

    // Not listed yet: the open directory does not show a profile that is under review.
    await signedOut.goto("/tutors")
    await expect(signedOut.locator("h1")).toHaveText("Tutors", { timeout: 15_000 })
    await expect(signedOut.getByRole("link", { name: tutors.sufficient.publicName })).toBeVisible({
      timeout: 15_000,
    })
    await expect(signedOut.getByRole("link", { name: layla.publicName })).toHaveCount(0)

    const page = await openAs(browser, platformAdmin, "platform_admin")
    const errors = watchConsole(page)

    await page.goto("/platform/tutors")
    await expect(page.locator("h1")).toHaveText("Tutors", { timeout: 15_000 })
    const row = page.getByRole("link", { name: layla.publicName })
    await expect(row, "the submitted profile is in the approval queue (needs the first test)").toBeVisible({
      timeout: 15_000,
    })
    await row.click()
    await expect(page).toHaveURL(`/platform/tutors/${layla.tutorProfileId}`)
    await expect(page.locator("h1")).toHaveText(layla.publicName, { timeout: 15_000 })

    const approve = page.getByRole("button", { name: "Approve" })
    await expect(
      page.getByText("This tutor has not uploaded any files. They will be listed without the documents-seen mark."),
    ).toBeVisible()
    await expect(page.getByLabel("I looked at the documents"), "no documents box when there are no files").toHaveCount(0)
    await expect(approve).toBeEnabled()
    await approve.click()
    await expect(page.getByText(/Approved\. The tutor is listed\./)).toBeVisible({ timeout: 15_000 })

    expect(errors, `console/page errors: ${JSON.stringify(errors, null, 2)}`).toEqual([])
    await page.context().close()
  })

  test("the approved tutor is listed on the open directory and on her own home", async ({
    browser,
    page: signedOut,
  }) => {
    const seed = readSeed()
    const layla = seed.tutoring.tutors.draft

    await signedOut.goto("/tutors")
    await expect(signedOut.getByRole("link", { name: layla.publicName })).toBeVisible({ timeout: 15_000 })
    await signedOut.getByRole("link", { name: layla.publicName }).click()
    await expect(signedOut).toHaveURL(`/tutors/${layla.tutorProfileId}`)
    await expect(signedOut.locator("h1")).toHaveText(layla.publicName, { timeout: 15_000 })

    const page = await openAs(browser, layla, "teacher")
    const errors = watchConsole(page)
    await page.goto("/teacher/tutoring")
    await expect(page.locator("h1")).toHaveText("Tutoring", { timeout: 15_000 })
    await expect(page.getByText("Your profile is listed")).toBeVisible()
    expect(errors, `console/page errors: ${JSON.stringify(errors, null, 2)}`).toEqual([])
    await page.context().close()
  })

  test("a student shares their progress with the new tutor from her profile", async ({ browser }) => {
    const seed = readSeed()
    const layla = seed.tutoring.tutors.draft
    const child = seed.students.declining
    const page = await openAs(browser, child, "student")
    const errors = watchConsole(page)

    await page.goto(`/student/tutors/${layla.tutorProfileId}`)
    await expect(page.locator("h1")).toHaveText(layla.publicName, { timeout: 15_000 })
    await page.getByRole("button", { name: "Share my progress" }).click()

    const sheet = page.getByRole("dialog", { name: `Share your progress with ${layla.publicName}?` })
    await expect(sheet).toBeVisible()
    await expect(sheet.getByText(/it is recorded and you can see it in Tutors & your data/)).toBeVisible()
    await sheet.getByRole("button", { name: "Share my progress" }).click()
    await expect(page.getByRole("dialog", { name: "You're sharing your progress" })).toBeVisible({ timeout: 15_000 })
    await page.getByRole("button", { name: "Done" }).click()
    await expect(page.getByText("Sharing your progress", { exact: true })).toBeVisible()

    expect(errors, `console/page errors: ${JSON.stringify(errors, null, 2)}`).toEqual([])
    await page.context().close()
  })

  test("the tutor sees the student in My students and opens their page", async ({ browser }) => {
    const seed = readSeed()
    const layla = seed.tutoring.tutors.draft
    const child = seed.students.declining
    const page = await openAs(browser, layla, "teacher")
    const errors = watchConsole(page)

    await page.goto("/teacher/tutoring/students")
    await expect(page.locator("h1")).toHaveText("My students", { timeout: 15_000 })
    const row = page.locator(`a[href="/teacher/tutoring/students/${child.userId}"]`)
    await expect(row, "the student who shared is listed (needs the sharing test)").toBeVisible({
      timeout: 15_000,
    })
    await row.click()

    await expect(page.locator("h1")).toHaveText(child.displayName, { timeout: 15_000 })
    await expect(page.getByText(`${child.displayName} shared this with you on`)).toBeVisible()
    await expect(page.getByText(/Each visit is recorded and they can see it\./)).toBeVisible()
    // T-20 removes the teacher-only controls of T-05.
    await expect(page.getByRole("button", { name: /Assign practice|Acknowledge/ })).toHaveCount(0)

    expect(errors, `console/page errors: ${JSON.stringify(errors, null, 2)}`).toEqual([])
    await page.context().close()
  })

  test("the student's Tutors & your data shows that Layla looked", async ({ browser }) => {
    const seed = readSeed()
    const layla = seed.tutoring.tutors.draft
    const child = seed.students.declining
    const page = await openAs(browser, child, "student")
    const errors = watchConsole(page)

    await page.goto("/student/tutor-access")
    await expect(page.locator("h1")).toHaveText("Tutors & your data", { timeout: 15_000 })
    const log = page.getByRole("region", { name: "Who looked" })
    await expect(log.getByText(`${layla.publicName} viewed your progress`).first()).toBeVisible({
      timeout: 15_000,
    })
    await expect(log.getByText(`${layla.publicName} saw you in their student list`).first()).toBeVisible()
    const sharing = page.getByRole("region", { name: "Sharing" })
    await expect(sharing.getByRole("link", { name: layla.publicName })).toBeVisible()

    expect(errors, `console/page errors: ${JSON.stringify(errors, null, 2)}`).toEqual([])
    await page.context().close()
  })

  test("the parent's Who they share with shows the same visit in the third person", async ({ browser }) => {
    const seed = readSeed()
    const layla = seed.tutoring.tutors.draft
    const child = seed.students.declining
    const page = await openAs(browser, seed.parent, "parent")
    const errors = watchConsole(page)

    await page.goto(`/parent/children/${child.userId}/tutor-access`)
    await expect(page.locator("h1")).toHaveText(`Who ${child.displayName} shares progress with`, {
      timeout: 15_000,
    })
    const log = page.getByRole("region", { name: "Who looked" })
    await expect(log.getByText(`${layla.publicName} viewed ${child.displayName}'s progress`).first()).toBeVisible({
      timeout: 15_000,
    })
    await expect(
      log.getByText(`${layla.publicName} saw ${child.displayName} in their student list`).first(),
    ).toBeVisible()
    const sharing = page.getByRole("region", { name: "Sharing" })
    await expect(sharing.getByRole("link", { name: layla.publicName })).toBeVisible()
    // A parent can read this and cannot change it: no stop-sharing control.
    await expect(page.getByRole("button", { name: /Stop sharing/ })).toHaveCount(0)

    expect(errors, `console/page errors: ${JSON.stringify(errors, null, 2)}`).toEqual([])
    await page.context().close()
  })
})

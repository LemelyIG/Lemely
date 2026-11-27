import { expect, test, type BrowserContext, type Page } from "@playwright/test"

/*
 * Long-press on a deck row -> deck menu -> delete confirmation (live K15), mounted in a real browser
 * and DB-free: every request is a synthetic page.route fixture, so it runs with
 * flashcards-geometry.config.ts and none of the acceptance suite's global setup.
 *
 * It replaces the source-text assertions that used to guard the legacy FlashcardDecks screen
 * (longPressSafety / gestureWiring): those read a file and could not see whether a hold really
 * opened the menu, whether the click the browser sends after the hold was swallowed, or whether
 * the delete confirmation actually removed the row. A control case (a plain tap still opens the
 * deck) is here so the suppression assertion can go red: without it "the URL did not change"
 * would also pass on a screen whose row never navigates at all.
 */

const artifacts = process.env.GEOMETRY_ARTIFACTS
const b64 = (value: object) => Buffer.from(JSON.stringify(value)).toString("base64url")
const session = { accessToken: `${b64({ alg: "none" })}.${b64({ exp: 4102444800 })}.x`, refreshToken: null, userId: "u1", role: "student" }

const deck = (id: string, title: string, cardCount: number) => ({
  id, subjectCode: "9709", topic: null, title, description: null, origin: "manual", cardCount, dueCount: 0,
  createdAt: "2025-01-01T00:00:00Z", newCount: cardCount, learningCount: 0, knownCount: 0, marksLost: null,
  generationStatus: "ready", requestedCount: null,
})
const card = (n: number) => ({
  id: `card-${n}`, front: `Question ${n}`, back: "Answer", position: n, source: "manual", sourceQuestionId: null,
  repetitions: 0, easeFactor: 2.5, intervalDays: 0, lapses: 0, dueAt: "2099-01-01T00:00:00Z", lastReviewedAt: null,
  nextIntervalDays: { again: 0, hard: 1, good: 2, easy: 4 },
})

interface Backend { deleted: string[]; page: Page }

async function open(context: BrowserContext, failDelete = false): Promise<Backend> {
  const page = await context.newPage()
  const decks = [deck("deck-1", "Vectors", 2), deck("deck-2", "Kinematics", 1)]
  const deleted: string[] = []
  await page.addInitScript((value) => localStorage.setItem("lemely.session", JSON.stringify(value)), session)
  await page.route("**/api/**", (route) => {
    const req = route.request()
    const path = new URL(req.url()).pathname
    const detail = path.match(/\/flashcards\/decks\/(deck-\d)$/)
    if (detail && req.method() === "DELETE") {
      if (failDelete) return route.fulfill({ status: 500, json: { detail: "boom" } })
      deleted.push(detail[1])
      decks.splice(decks.findIndex((d) => d.id === detail[1]), 1)
      return route.fulfill({ status: 204, body: "" })
    }
    if (detail) {
      const d = decks.find((x) => x.id === detail[1])
      return route.fulfill({ json: { id: d?.id, subjectCode: "9709", topic: null, title: d?.title, origin: "manual", cards: Array.from({ length: d?.cardCount ?? 0 }, (_, i) => card(i)), dueCount: 0 } })
    }
    if (path.endsWith("/flashcards/decks")) return route.fulfill({ json: decks })
    if (path.endsWith("/flashcards/due")) return route.fulfill({ json: { cards: [], totalDue: 0, nextDueAt: null, upcoming: [], againDelayMinutes: 10 } })
    if (path.endsWith("/flashcards/weak-topics")) return route.fulfill({ json: [] })
    if (path.endsWith("/student/overview")) return route.fulfill({ json: { studentName: "Student", forecast: "", subjects: [{ code: "9709", name: "Mathematics" }], weakGlobal: [], momentum: {} } })
    if (path.endsWith("/me/student-profile")) return route.fulfill({ json: { profile: { qualificationLevel: null, onboardingCompletedAt: "2025-01-01T00:00:00Z" }, enrolments: [] } })
    if (path.endsWith("/me/profile")) return route.fulfill({ json: { email: "student@example.com", displayName: "Student", emailVerified: true } })
    if (path.endsWith("/reference")) return route.fulfill({ json: { subjects: [], qualificationLevels: [] } })
    if (path.endsWith("/access/config")) return route.fulfill({ json: { restricted: false } })
    return route.fulfill({ json: {} })
  })
  await page.goto("/student/flashcards")
  await expect(page.getByRole("button", { name: /Vectors/ })).toBeVisible()
  return { deleted, page }
}

const shot = (page: Page, name: string) => page.screenshot({ path: artifacts ? `${artifacts}/${name}.png` : test.info().outputPath(`${name}.png`) })

/** A mouse hold past the 500ms threshold, released over the same row: the browser then sends a click. */
async function hold(page: Page, name: RegExp) {
  const box = (await page.getByRole("button", { name }).first().boundingBox())!
  await page.mouse.move(box.x + 40, box.y + box.height / 2)
  await page.mouse.down()
  await page.waitForTimeout(650)
}

for (const viewport of [{ width: 380, height: 800 }, { width: 1440, height: 900 }]) {
  test.describe(`deck long-press at ${viewport.width}px`, () => {
    test.use({ viewport })

    test("control: a plain tap opens the deck (so the suppression check below can fail)", async ({ context }) => {
      const { page } = await open(context)
      // Tap whichever deck is not already the selected one at desktop width.
      const before = await page.locator("[data-fc-selected-row]").allTextContents()
      const target = before.some((t) => t.includes("Kinematics")) ? "Vectors" : "Kinematics"
      await page.getByRole("button", { name: new RegExp(target) }).first().click()
      if (viewport.width < 1024) await expect(page).toHaveURL(target === "Vectors" ? /deck\/deck-1/ : /deck\/deck-2/)
      else await expect(page.locator("[data-fc-selected-row]").filter({ hasText: target })).toHaveCount(1)
      await expect(page.getByRole("dialog")).toHaveCount(0)
    })

    test("a hold opens the menu and the click after it neither navigates nor selects the row", async ({ context }) => {
      const { page } = await open(context)
      const url = page.url()
      const selected = () => page.locator("[data-fc-selected-row]").allTextContents()
      const selectedBefore = await selected()
      await hold(page, /Kinematics/)
      await page.mouse.up()
      const menu = page.getByRole("dialog", { name: "Kinematics" })
      await expect(menu).toBeVisible()
      await expect(menu.getByRole("button", { name: "Rename" })).toBeVisible()
      await expect(menu.getByRole("button", { name: "Delete deck" })).toBeVisible()
      expect(page.url(), "the click synthesised after a hold must not open the deck").toBe(url)
      // The page behind a modal is hidden from the role tree, so ask the DOM directly.
      expect(await selected(), "the click synthesised after a hold must not change the selected deck").toEqual(selectedBefore)
      await shot(page, `longpress-menu-${viewport.width}`)
    })

    test("a short press, or one that drifts, does not open the menu", async ({ context }) => {
      const { page } = await open(context)
      const box = (await page.getByRole("button", { name: /Vectors/ }).first().boundingBox())!
      await page.mouse.move(box.x + 40, box.y + box.height / 2)
      await page.mouse.down()
      await page.mouse.move(box.x + 80, box.y + box.height / 2, { steps: 4 })
      await page.waitForTimeout(650)
      await page.mouse.up()
      await expect(page.getByRole("dialog")).toHaveCount(0)
    })

    test("hold -> Delete deck -> confirm removes only that row", async ({ context }) => {
      const { page, deleted } = await open(context)
      await hold(page, /Vectors/)
      await page.mouse.up()
      await page.getByRole("dialog", { name: "Vectors" }).getByRole("button", { name: "Delete deck" }).click()
      const confirm = page.getByRole("alertdialog", { name: "Delete Vectors?" })
      await expect(confirm).toBeVisible()
      await expect(confirm).toContainText("All 2 cards and their progress go. This can’t be undone.")
      // Focus must be on the safe way out, not on the held row behind the sheet (the menu sheet
      // used to hand focus back to that row as it finished closing).
      await expect(confirm.getByRole("button", { name: "Keep it" })).toBeFocused()
      expect(deleted, "nothing is deleted before the student confirms").toEqual([])
      await shot(page, `longpress-delete-confirm-${viewport.width}`)
      await confirm.getByRole("button", { name: "Delete deck" }).click()
      await expect(page.getByRole("button", { name: /Vectors/ })).toHaveCount(0)
      await expect(page.getByRole("button", { name: /Kinematics/ })).toBeVisible()
      expect(deleted).toEqual(["deck-1"])
      await shot(page, `longpress-after-delete-${viewport.width}`)
    })

    test("hold -> Delete deck -> Keep it deletes nothing", async ({ context }) => {
      const { page, deleted } = await open(context)
      await hold(page, /Vectors/)
      await page.mouse.up()
      await page.getByRole("dialog", { name: "Vectors" }).getByRole("button", { name: "Delete deck" }).click()
      await page.getByRole("alertdialog", { name: "Delete Vectors?" }).getByRole("button", { name: "Keep it" }).click()
      await expect(page.getByRole("alertdialog")).toHaveCount(0)
      await expect(page.getByRole("button", { name: /Vectors/ }).first()).toBeVisible()
      expect(deleted).toEqual([])
    })

    test("a failed delete keeps the deck and says so", async ({ context }) => {
      const { page, deleted } = await open(context, true)
      await hold(page, /Vectors/)
      await page.mouse.up()
      await page.getByRole("dialog", { name: "Vectors" }).getByRole("button", { name: "Delete deck" }).click()
      const confirm = page.getByRole("alertdialog", { name: "Delete Vectors?" })
      await confirm.getByRole("button", { name: "Delete deck" }).click()
      await expect(confirm.getByRole("alert")).toContainText("Couldn’t delete the deck. It’s still here.")
      expect(deleted).toEqual([])
      await shot(page, `longpress-delete-failed-${viewport.width}`)
    })

    test("hold -> Rename is offered (rename is supported, K27)", async ({ context }) => {
      const { page } = await open(context)
      await hold(page, /Kinematics/)
      await page.mouse.up()
      await page.getByRole("dialog", { name: "Kinematics" }).getByRole("button", { name: "Rename" }).click()
      await expect(page.getByRole("dialog").filter({ hasText: /rename/i })).toBeVisible()
    })
  })
}

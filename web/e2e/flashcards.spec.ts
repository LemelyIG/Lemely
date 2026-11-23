import { randomUUID } from "node:crypto"
import { test, expect, type APIRequestContext, type Locator, type Page } from "@playwright/test"
import AxeBuilder from "@axe-core/playwright"
import { watchConsole } from "./console-errors"
import { injectSession, readSeed, type SeedAccount } from "./seed"

const BACKEND_URL = "http://127.0.0.1:8000"

/*
 * L10 flashcards: one happy path per screen (decks, deck, review) on a phone, plus the desktop
 * side panel. Each test makes a fresh manual deck through the API, so a retry never meets cards
 * an earlier attempt already reviewed, and the shared seeded student is left as it was found.
 *
 * Selectors follow the live screens in web/src/portals/student/screens/flashcards/: the decks
 * shelf (FlashcardsScreen, DeckRow), the deck page and panel (DeckBody, DeckContent, DeckMenu and
 * the Card, Rename and Delete sheets), and the review (ReviewScreen, ReviewCard, ReviewDone).
 */

/* a11y:begin
 * The accessibility step Task 14 deferred to this spec. Axe covers the WCAG rules; the two floors
 * axe does not enforce (44x44 targets, 12px text) are measured in the page. Both scan one scope and
 * skip `role="status"` regions, which on a seeded (unverified) student include the shell's email
 * banner: that is not L10's markup, and its small link would fail a flashcards test. */

interface FloorReport {
  roots: number
  smallTargets: string[]
  smallText: string[]
}

/** The shell banners and live regions that sit beside the screen inside `main`. */
const NOT_THE_SCREEN = '[role="status"]'

/** Runs in the page, so it must stay self-contained. Sheets, popovers and sr-only text are skipped by size. */
function measureFloors(args: { scope: string; skip: string }): FloorReport {
  const MIN_TARGET = 44
  const MIN_TEXT = 12
  const TOLERANCE = 0.5
  const INTERACTIVE =
    'button, a[href], input:not([type="hidden"]), select, textarea, summary, [role="button"], [role="radio"], [role="checkbox"], [role="switch"], [role="tab"], [role="menuitem"], [tabindex]:not([tabindex="-1"])'
  const roots = Array.from(document.querySelectorAll(args.scope))
  const smallTargets: string[] = []
  const smallText: string[] = []
  const seen = new Set<Element>()

  const label = (el: Element) => (el.getAttribute("aria-label") ?? el.textContent ?? "").trim().replace(/\s+/g, " ").slice(0, 40)
  // sr-only content is 1px by 1px, display:none is 0x0: neither is a target or readable text.
  const rendered = (el: Element) => {
    const box = el.getBoundingClientRect()
    return box.width > 1 && box.height > 1 && getComputedStyle(el).visibility !== "hidden"
  }

  for (const root of roots) {
    const candidates = [root, ...Array.from(root.querySelectorAll(INTERACTIVE))].filter((el) => el.matches(INTERACTIVE))
    for (const el of candidates) {
      if (seen.has(el) || el.closest(args.skip) || !rendered(el)) continue
      seen.add(el)
      const box = el.getBoundingClientRect()
      if (box.width < MIN_TARGET - TOLERANCE || box.height < MIN_TARGET - TOLERANCE) {
        smallTargets.push(`${el.tagName.toLowerCase()} "${label(el)}" ${Math.round(box.width)}x${Math.round(box.height)}`)
      }
    }
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      const text = (node.nodeValue ?? "").trim()
      const parent = node.parentElement
      if (!text || !parent || parent.closest(args.skip) || !rendered(parent)) continue
      const size = parseFloat(getComputedStyle(parent).fontSize)
      if (size < MIN_TEXT) smallText.push(`"${text.slice(0, 30)}" ${size}px`)
    }
  }
  return { roots: roots.length, smallTargets, smallText }
}

/** Sheets slide and cards rise and flip: measure and contrast-check only once they have landed. Looping animations (Binny) are left running. */
async function settle(page: Page): Promise<void> {
  await page.waitForFunction(
    () => document.getAnimations().every((a) => a.effect?.getTiming().iterations === Infinity || a.playState === "finished"),
    undefined,
    { timeout: 10_000 },
  )
}

async function expectNoAxeViolations(page: Page, scope: string): Promise<void> {
  await settle(page)
  // `include` throws when nothing matches, so a wrong scope cannot pass by checking nothing.
  const results = await new AxeBuilder({ page })
    .include(scope)
    .exclude(NOT_THE_SCREEN)
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze()
  const blocking = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical")
  expect(
    blocking.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(" | ")}`),
    `axe serious or critical violations in ${scope}`,
  ).toEqual([])
}

async function expectFloors(page: Page, scope: string): Promise<void> {
  await settle(page)
  const report = await page.evaluate(measureFloors, { scope, skip: NOT_THE_SCREEN })
  expect(report.roots, `nothing matches ${scope}`).toBeGreaterThan(0)
  expect(report.smallTargets, `targets under 44x44 in ${scope}`).toEqual([])
  expect(report.smallText, `text under 12px in ${scope}`).toEqual([])
}

async function expectAccessible(page: Page, scope: string): Promise<void> {
  await expectNoAxeViolations(page, scope)
  await expectFloors(page, scope)
}
/* a11y:end */

const SCREEN = "main"
const DIALOG = '[role="dialog"]'
const ALERT_DIALOG = '[role="alertdialog"]'

function authHeaders(account: SeedAccount): Record<string, string> {
  return { Authorization: `Bearer ${account.accessToken}` }
}

const createdDecks: string[] = []

async function makeDeck(request: APIRequestContext, account: SeedAccount, cards: number): Promise<{ id: string; title: string }> {
  const headers = authHeaders(account)
  const title = `L10 e2e ${randomUUID().slice(0, 8)}`
  const deck = await request.post(`${BACKEND_URL}/api/student/flashcards/decks`, {
    headers,
    data: { subjectCode: readSeed().practice.subjectCode, title, origin: "manual" },
  })
  expect(deck.status()).toBe(201)
  const { id } = (await deck.json()) as { id: string }
  createdDecks.push(id)
  for (let i = 1; i <= cards; i++) {
    const card = await request.post(`${BACKEND_URL}/api/student/flashcards/decks/${id}/cards`, {
      headers,
      data: { front: `L10 front ${i}`, back: `L10 back ${i}` },
    })
    expect(card.status()).toBe(201)
  }
  return { id, title }
}

// Best effort: the delete test has already removed its deck, so a 404 here is expected and ignored.
test.afterEach(async ({ request }) => {
  const account = readSeed().practice.students.active
  for (const id of createdDecks.splice(0)) {
    await request.delete(`${BACKEND_URL}/api/student/flashcards/decks/${id}`, { headers: authHeaders(account) })
  }
})

async function asStudent(page: Page, account: SeedAccount): Promise<void> {
  await injectSession(page, { accessToken: account.accessToken, userId: account.userId, role: "student" })
}

/** An open sheet is named by exactly one heading: Radix points aria-labelledby at it, and the name is how this finds the sheet. */
async function expectSheet(page: Page, role: "dialog" | "alertdialog", name: string): Promise<Locator> {
  const sheet = page.getByRole(role, { name })
  await expect(sheet).toBeVisible()
  await expect(sheet.getByRole("heading")).toHaveCount(1)
  return sheet
}

test.describe("flashcards on a phone", () => {
  test.use({ viewport: { width: 390, height: 844 } })

  test("decks: the new deck shows under its subject with cards due", async ({ page, request }) => {
    test.slow()
    const account = readSeed().practice.students.active
    const errors = watchConsole(page)
    const deck = await makeDeck(request, account, 2)
    await asStudent(page, account)

    await page.goto("/student/flashcards")
    await expect(page.getByRole("heading", { level: 1, name: "Flashcards" })).toBeVisible({ timeout: 15_000 })
    await expect(page.getByText(/^\d+ cards? due$/)).toBeVisible()
    await expect(page.getByRole("button", { name: /^Review \d+ cards?$/ })).toBeVisible()

    const row = page.getByRole("list", { name: /decks$/ }).getByRole("button", { name: deck.title })
    await expect(row).toBeVisible()
    await expect(row).toContainText("2 cards")
    await expect(row).toContainText(/2\s*due/)
    await expectAccessible(page, SCREEN)

    // The new-deck sheet: one title, an announced "Kind of deck" radio group, and topic chips that report pressed.
    await page.getByRole("button", { name: "New deck", exact: true }).click()
    const sheet = await expectSheet(page, "dialog", "New deck")
    const kinds = sheet.getByRole("radiogroup", { name: "Kind of deck" })
    await expect(kinds.getByRole("radio")).toHaveCount(3)
    await expect(kinds.getByRole("radio", { checked: true })).toHaveCount(1)
    const chip = sheet.getByRole("group", { name: "Topic", exact: true }).getByRole("button").first()
    await expect(chip).toHaveAttribute("aria-pressed", "false", { timeout: 15_000 })
    await chip.click()
    await expect(chip).toHaveAttribute("aria-pressed", "true")
    await expectAccessible(page, DIALOG)
    await page.keyboard.press("Escape")
    await expect(sheet).toBeHidden()

    expect(errors, JSON.stringify(errors, null, 2)).toEqual([])
  })

  test("deck: add a card, rename the deck, then delete it", async ({ page, request }) => {
    test.slow()
    const account = readSeed().practice.students.active
    const errors = watchConsole(page)
    const deck = await makeDeck(request, account, 1)
    const renamed = `${deck.title} renamed`
    await asStudent(page, account)

    await page.goto(`/student/flashcards/deck/${deck.id}`)
    await expect(page.getByRole("heading", { level: 1, name: deck.title })).toBeVisible({ timeout: 15_000 })
    await expect(page.getByRole("button", { name: "Review 1 due" })).toBeVisible()
    await expectAccessible(page, SCREEN)

    // Add a card. The page's own "Add card" button is behind the sheet while it is open, so the sheet's is scoped.
    await page.getByRole("button", { name: "Add card", exact: true }).click()
    const cardSheet = await expectSheet(page, "dialog", "New card")
    await cardSheet.getByLabel("Front", { exact: true }).fill("L10 added front")
    await cardSheet.getByLabel("Back", { exact: true }).fill("L10 added back")
    await expectAccessible(page, DIALOG)
    await cardSheet.getByRole("button", { name: "Add card", exact: true }).click()
    await expect(cardSheet).toBeHidden()
    await expect(page.getByRole("list", { name: "Cards" }).getByText("L10 added front")).toBeVisible()
    await expect(page.getByRole("button", { name: "Review 2 due" })).toBeVisible()

    // Rename.
    await page.getByRole("button", { name: "Deck options" }).click()
    await page.getByRole("button", { name: "Rename", exact: true }).click()
    const renameSheet = await expectSheet(page, "dialog", "Rename deck")
    await renameSheet.getByLabel("Name", { exact: true }).fill(renamed)
    await expectAccessible(page, DIALOG)
    await renameSheet.getByRole("button", { name: "Save", exact: true }).click()
    await expect(renameSheet).toBeHidden()
    await expect(page.getByRole("heading", { level: 1, name: renamed })).toBeVisible()

    // Delete. The sheet names the deck, says what goes, and opens on Keep it, the safe way out.
    await page.getByRole("button", { name: "Deck options" }).click()
    await page.getByRole("button", { name: "Delete deck", exact: true }).click()
    const deleteSheet = await expectSheet(page, "alertdialog", `Delete ${renamed}?`)
    await expect(deleteSheet.getByRole("button", { name: "Keep it" })).toBeFocused()
    await expect(deleteSheet).toContainText("All 2 cards and their progress go")
    await expectAccessible(page, ALERT_DIALOG)
    await deleteSheet.getByRole("button", { name: "Delete deck", exact: true }).click()

    await expect(page).toHaveURL(/\/student\/flashcards$/)
    await expect(page.getByRole("heading", { level: 1, name: "Flashcards" })).toBeVisible()
    await expect(page.getByText(`${renamed} deleted`, { exact: true })).toBeVisible()
    await expect(page.getByRole("button", { name: renamed })).toHaveCount(0)
    expect(errors, JSON.stringify(errors, null, 2)).toEqual([])
  })

  test("review: flip, rate both cards, all caught up", async ({ page, request }) => {
    test.slow()
    const account = readSeed().practice.students.active
    const errors = watchConsole(page)
    const deck = await makeDeck(request, account, 2)
    await asStudent(page, account)

    await page.goto(`/student/flashcards/deck/${deck.id}`)
    await page.getByRole("button", { name: "Review 2 due" }).click()
    await expect(page).toHaveURL(new RegExp(`/student/flashcards/review\\?deck=${deck.id}`))
    await expect(page.getByText("1/2", { exact: true })).toBeVisible({ timeout: 15_000 })
    await expect(page.getByRole("heading", { level: 1, name: "Review flashcards" })).toHaveCount(1)

    // The progress bar and the sync live region are announced; the region exists before any failure, so a later banner is read out.
    const progress = page.getByRole("progressbar", { name: "Cards reviewed" })
    await expect(progress).toHaveAttribute("aria-valuemax", "2")
    await expect(progress).toHaveAttribute("aria-valuenow", "0")
    await expect(page.getByRole("status").first()).toBeAttached()
    await expectAccessible(page, SCREEN)

    // Card one, with the mouse. The grade buttons name their key for assistive tech instead of reading the on-screen keycap.
    await page.getByRole("button", { name: "Show answer" }).click()
    await expect(page.getByText(/^L10 back \d$/)).toBeVisible()
    const grades = page.getByRole("group", { name: "How well did you know it?" })
    await expect(grades.getByRole("button", { name: /Easy/ })).toHaveAttribute("aria-keyshortcuts", "4")
    await expectAccessible(page, SCREEN)
    await grades.getByRole("button", { name: /Good/ }).click()

    // Card two, with the keyboard: Space flips, 4 rates Easy. The group appearing proves the flip landed before the rating key.
    await expect(page.getByText("2/2", { exact: true })).toBeVisible()
    await expect(progress).toHaveAttribute("aria-valuenow", "1")
    await page.keyboard.press("Space")
    await expect(grades).toBeVisible()
    await page.keyboard.press("4")

    await expect(page.getByRole("heading", { name: "All caught up" })).toBeVisible()
    // Both ratings counted as known once the server has settled them; Back is guarded until nothing is still saving.
    await expect(page.getByText("knew it").locator("..")).toHaveText(/^2\s*knew it$/)
    await expectAccessible(page, SCREEN)

    await page.getByRole("button", { name: "Back to decks" }).click()
    await expect(page).toHaveURL(new RegExp(`/student/flashcards/deck/${deck.id}`))
    await expect(page.getByRole("button", { name: "Nothing due" })).toBeDisabled()
    expect(errors, JSON.stringify(errors, null, 2)).toEqual([])
  })
})

test.describe("flashcards on a desktop", () => {
  test.use({ viewport: { width: 1280, height: 900 } })

  test("desktop: list with a side panel and review keys", async ({ page, request }) => {
    const account = readSeed().practice.students.active
    const errors = watchConsole(page)
    const deck = await makeDeck(request, account, 1)
    await asStudent(page, account)

    await page.goto(`/student/flashcards?deck=${deck.id}`)
    const panel = page.getByRole("complementary", { name: "Deck", exact: true })
    await expect(panel.getByRole("heading", { name: deck.title })).toBeVisible({ timeout: 15_000 })
    await panel.getByRole("button", { name: "Review 1 due" }).click()

    await expect(page.getByText(/Press Space to flip/)).toBeVisible()
    await page.keyboard.press("Space")
    await expect(page.getByRole("group", { name: "How well did you know it?" })).toBeVisible()
    await page.keyboard.press("3")
    await expect(page.getByRole("heading", { name: "All caught up" })).toBeVisible()
    expect(errors, JSON.stringify(errors, null, 2)).toEqual([])
  })
})

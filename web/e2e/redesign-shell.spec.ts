import { expect, test, type Page } from "@playwright/test"
import { watchConsole } from "./console-errors"
import { injectSession, readSeed } from "./seed"

/*
 * F1 shell happy path (Task 13): the redesigned student and parent shells,
 * phone and desktop. Real backend, seeded accounts, role-based selectors.
 *
 * Student nav follows the Task 10 user ruling: phone tabs are Home, Practice,
 * the raised "Scan a paper", Plan, Me (no Subjects tab, no More cell). The
 * subject tree and the More group live in the navigation sheet the top bar's
 * menu button opens (the rail on desktop).
 *
 * Parent: the seed links exactly one child (`students.declining`) to
 * `parent`, so the one-child label is asserted against real data. No seeded
 * parent has two children, so the two-child switcher test stubs the children
 * list response (the real list plus one extra child) and asserts only the
 * URL the switcher navigates to.
 */

/** The Inbox tab carries an unread badge inside the link ("Inbox 3"). */
const INBOX = /^Inbox(\s\d+\+?)?$/

async function signInStudent(page: Page): Promise<void> {
  const student = readSeed().students.correctedPaper
  await page.goto("/login")
  await page.getByLabel("Email").fill(student.email)
  await page.getByLabel("Password").fill(student.password)
  await page.getByRole("button", { name: /sign in/i }).click()
  await expect(page).toHaveURL(/\/student$/, { timeout: 15_000 })
}

async function openParent(page: Page): Promise<{ childId: string; childName: string }> {
  const seed = readSeed()
  const child = seed.students.declining
  await injectSession(page, { accessToken: seed.parent.accessToken, userId: seed.parent.userId, role: "parent" })
  await page.goto("/parent")
  await expect(page).toHaveURL(new RegExp(`/parent/children/${child.userId}$`), { timeout: 15_000 })
  return { childId: child.userId, childName: child.displayName }
}

test.describe("F1 student shell", () => {
  test("phone: five tabs with Scan raised in the centre, the menu opens the sheet, tabs reach their screens", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    const errors = watchConsole(page)
    await signInStudent(page)

    const nav = page.getByRole("navigation", { name: "Primary" })
    const tabs = nav.locator(":scope > *")
    await expect(tabs).toHaveCount(5)
    for (const [i, name] of ["Home", "Practice", "Scan a paper", "Plan", "Me"].entries()) {
      await expect(tabs.nth(i)).toHaveAccessibleName(name)
    }
    await expect(nav.getByRole("link", { name: "Subjects" })).toHaveCount(0)
    await expect(nav.getByRole("button", { name: "More" })).toHaveCount(0)
    await expect(nav.getByRole("link", { name: "Home", exact: true })).toHaveAttribute("aria-current", "page")

    // The top bar's menu button opens the sheet: subject tree plus the More group.
    const menu = page.getByRole("button", { name: "Open student navigation" })
    await expect(menu).toHaveAttribute("aria-haspopup", "dialog")
    await expect(nav.getByRole("link", { name: "Scan a paper" }).locator("[data-emphasis]")).toHaveAttribute("data-emphasis", "true")
    await menu.click()
    const sheet = page.getByRole("dialog")
    await expect(sheet).toBeVisible()
    for (const name of ["Your classes", "Standings", "Friends", "Tutors", "Sessions"]) {
      await expect(sheet.getByRole("link", { name, exact: true })).toBeVisible()
    }
    await expect(sheet.getByText("Subjects", { exact: true })).toBeVisible()
    await page.keyboard.press("Escape")
    await expect(sheet).toBeHidden()

    // Practice redirects to the first subject's practice and stays lit.
    await nav.getByRole("link", { name: "Practice", exact: true }).click()
    await expect(page).toHaveURL(/\/student\/practice\/[^/]+$/, { timeout: 15_000 })
    await expect(nav.getByRole("link", { name: "Practice", exact: true })).toHaveAttribute("aria-current", "page")

    // Plan redirects to the first subject's study plan and stays lit.
    await nav.getByRole("link", { name: "Plan", exact: true }).click()
    await expect(page).toHaveURL(/\/student\/plan\/[^/]+$/, { timeout: 15_000 })
    await expect(nav.getByRole("link", { name: "Plan", exact: true })).toHaveAttribute("aria-current", "page")

    await nav.getByRole("link", { name: "Me", exact: true }).click()
    await expect(page).toHaveURL(/\/student\/profile$/)

    await nav.getByRole("link", { name: "Scan a paper" }).click()
    await expect(page).toHaveURL(/\/student\/correct$/)
    expect(errors).toEqual([])
  })

  test("desktop: the rail is Home, Practice, Plan, Me, the More group and a Scan a paper action", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 900 })
    const errors = watchConsole(page)
    await signInStudent(page)

    const rail = page.getByRole("navigation", { name: "Main" })
    for (const name of ["Home", "Practice", "Plan", "Me", "Your classes", "Standings", "Friends", "Tutors", "Sessions", "Scan a paper"]) {
      await expect(rail.getByRole("link", { name, exact: true })).toBeVisible()
    }
    await expect(rail.getByRole("link", { name: "Home", exact: true })).toHaveAttribute("aria-current", "page")
    await rail.getByRole("link", { name: "Plan", exact: true }).click()
    await expect(page).toHaveURL(/\/student\/plan\/[^/]+$/, { timeout: 15_000 })
    await expect(rail.getByRole("link", { name: "Plan", exact: true })).toHaveAttribute("aria-current", "page")
    expect(errors).toEqual([])
  })
})

test.describe("F1 parent shell", () => {
  test("phone: four tabs plus More, a static child name, Topics opens the weak topics screen", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    const errors = watchConsole(page)
    const { childId, childName } = await openParent(page)

    const nav = page.getByRole("navigation", { name: "Primary" })
    for (const name of [/^Overview$/, /^Topics$/, INBOX, /^Tutoring$/]) {
      await expect(nav.getByRole("link", { name })).toBeVisible()
    }
    await expect(nav.getByRole("button", { name: "More" })).toBeVisible()
    // One child: the name is a plain label in the top bar, not a control.
    await expect(page.locator("header").getByText(childName)).toBeVisible()
    await expect(page.getByRole("combobox", { name: "Choose which child to view" })).toHaveCount(0)

    await nav.getByRole("link", { name: "Topics", exact: true }).click()
    await expect(page).toHaveURL(new RegExp(`/parent/children/${childId}/topics$`))
    await expect(page.getByRole("heading", { name: "What to work on next" })).toBeVisible({ timeout: 15_000 })
    await expect(nav.getByRole("link", { name: "Topics", exact: true })).toHaveAttribute("aria-current", "page")

    await nav.getByRole("link", { name: "Tutoring", exact: true }).click()
    await expect(page).toHaveURL(new RegExp(`/parent/children/${childId}/tutoring$`))
    expect(errors).toEqual([])
  })

  test("desktop: the child name sits in the rail beside Tutors", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 900 })
    const errors = watchConsole(page)
    const { childName } = await openParent(page)

    const rail = page.getByRole("navigation", { name: "Main" })
    await expect(rail.getByText(childName)).toBeVisible({ timeout: 15_000 })
    for (const name of [/^Overview$/, /^Topics$/, INBOX, /^Tutoring$/, /^Tutors$/]) {
      await expect(rail.getByRole("link", { name })).toBeVisible()
    }
    // One child, so no "Your children" row.
    await expect(rail.getByRole("link", { name: "Your children" })).toHaveCount(0)
    expect(errors).toEqual([])
  })

  test("two children: the switcher is a select and keeps the topics and tutoring tails", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 900 })
    const errors = watchConsole(page)
    const seed = readSeed()
    const childId = seed.students.declining.userId
    const other = { childId: "00000000-0000-4000-8000-0000000000b2", displayName: "Second Child" }
    // Real list plus one extra child; the extra child's pages are never loaded as data.
    await page.route("**/api/parent/children", async (route) => {
      const response = await route.fetch()
      const body = (await response.json()) as { children: Record<string, unknown>[] }
      await route.fulfill({ json: { ...body, children: [...body.children, { ...body.children[0], ...other }] } })
    })
    // With two children /parent stays on the list, so open the child directly.
    await injectSession(page, { accessToken: seed.parent.accessToken, userId: seed.parent.userId, role: "parent" })
    await page.goto(`/parent/children/${childId}`)

    const rail = page.getByRole("navigation", { name: "Main" })
    await expect(rail.getByRole("link", { name: "Your children" })).toBeVisible({ timeout: 15_000 })
    const switcher = rail.getByRole("combobox", { name: "Choose which child to view" })
    await expect(switcher).toBeVisible()
    await expect(switcher).toHaveValue(childId)

    for (const tail of ["topics", "tutoring"]) {
      await page.goto(`/parent/children/${childId}/${tail}`)
      await expect(switcher).toHaveValue(childId, { timeout: 15_000 })
      await switcher.selectOption(other.childId)
      await expect(page).toHaveURL(new RegExp(`/parent/children/${other.childId}/${tail}$`))
    }
    // Switching lands on the fake child's pages, whose data requests 404 (the browser's own
    // "Failed to load resource" lines, already filtered); an app error from rendering that
    // not-found state is the only thing that would reach this list.
    expect(errors).toEqual([])
  })
})

import { test, expect } from "@playwright/test"
import { watchConsole } from "./console-errors"
import { injectSession, readSeed } from "./seed"

/*
 * The teacher and parent inboxes (push-delivery spec §6, §8). Each renders for
 * its own role and is unreachable for the other.
 *
 * **What the wrong role actually gets is not a 404 and not a redirect.**
 * `RequireAuth` renders `FullPageState variant="no-access"` in place, at the
 * same URL, and its module note says why the redirect this spec first
 * asserted was deliberately removed (PR 2 part A2): landing someone on their
 * own portal root with no explanation "reads as the link being broken rather
 * than as the page belonging to someone else". So the negative case asserts
 * the refusal itself — the 403 state is shown and the inbox copy is not —
 * which is a stronger claim than a redirect anyway.
 *
 * The seed creates no notifications, so the state these screens ship in is
 * the empty one — which is exactly the state with the least other content to
 * orient a reader, and the one the heading has to be present in.
 */

test.describe("teacher inbox", () => {
  test("renders for a teacher", async ({ page }) => {
    const seed = readSeed()
    const errors = watchConsole(page)
    await injectSession(page, { ...seed.teacher, role: "teacher" })

    await page.goto("/teacher/notifications")

    await expect(page.getByRole("heading", { level: 1, name: "Notifications" })).toBeVisible()
    await expect(page.getByText("When a student you teach may need support")).toBeVisible()
    await expect(page.getByRole("link", { name: "Notification settings" })).toHaveAttribute(
      "href",
      "/teacher/settings/notifications",
    )
    expect(errors).toEqual([])
  })

  test("is refused for a parent, in place, with the 403 state", async ({ page }) => {
    const seed = readSeed()
    await injectSession(page, { ...seed.parent, role: "parent" })

    await page.goto("/teacher/notifications")

    await expect(
      page.getByRole("heading", { name: "You don't have access to this page" }),
    ).toBeVisible()
    await expect(page.getByText("When a student you teach may need support")).toHaveCount(0)
  })
})

test.describe("parent inbox", () => {
  test("renders for a parent", async ({ page }) => {
    const seed = readSeed()
    const errors = watchConsole(page)
    await injectSession(page, { ...seed.parent, role: "parent" })

    await page.goto("/parent/notifications")

    await expect(page.getByRole("heading", { level: 1, name: "Notifications" })).toBeVisible()
    await expect(page.getByText("When your child may need support")).toBeVisible()
    await expect(page.getByRole("link", { name: "Notification settings" })).toHaveAttribute(
      "href",
      "/settings/notifications",
    )
    expect(errors).toEqual([])
  })

  test("is refused for a teacher, in place, with the 403 state", async ({ page }) => {
    const seed = readSeed()
    await injectSession(page, { ...seed.teacher, role: "teacher" })

    await page.goto("/parent/notifications")

    await expect(
      page.getByRole("heading", { name: "You don't have access to this page" }),
    ).toBeVisible()
    await expect(page.getByText("When your child may need support")).toHaveCount(0)
  })

  test("sends a signed-out visitor to sign in", async ({ page }) => {
    await page.goto("/parent/notifications")
    await expect(page).toHaveURL(/\/login/)
  })
})

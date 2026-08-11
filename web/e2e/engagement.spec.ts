import { test, expect } from "@playwright/test"
import { watchConsole } from "./console-errors"
import { injectSession, readSeed } from "./seed"

/*
 * Phase 5's named acceptance criteria (BUILD/MISSION.md §4, Phase 5): "E2E
 * covering XP accrual, leaderboard ordering, push delivery (headless push
 * mock), announcement flow".
 *
 * Two of the four live here. The other two ride on `correct-paper.spec.ts`,
 * because `POST /student/correct` is *both* the `paper_corrected` XP seam and
 * the `grade_ready` notification seam — a driver of their own would only
 * re-run that journey. See the P5.11 block at the end of that file.
 *
 * Scope note on "push delivery", stated here rather than discovered later:
 * this machine has no VAPID keys, so the push transport reports itself
 * unavailable by design (D5.9 §4) and `notify_safely` records
 * `push_suppressed_reason="transport_unavailable"` *after* writing the
 * notification row. The row is the assertable fact. No harness on this
 * machine can deliver a real push, and asserting one would mean asserting a
 * mock of our own making.
 */

test("the weekly class board ranks the seeded roster by XP, highest first", async ({ page }) => {
  const seed = readSeed()
  const errors = watchConsole(page)
  const { leaderboard } = seed.engagement

  // Any seeded student works — the class board is the same board for all
  // three. `control` is the one with no at-risk flags, so nothing else on the
  // screen competes for attention in the capture.
  await injectSession(page, {
    accessToken: seed.students.control.accessToken,
    userId: seed.students.control.userId,
    role: "student",
  })
  await page.goto("/student/board")

  // S-29 opens on the FRIENDS scope (`useState<LeaderboardScope>("friends")`),
  // and no friendships are seeded — so a spec that just navigates here and
  // reads rows is looking at a legitimately empty board and would fail as "the
  // board is empty", which reads as a backend defect and is really a default.
  const scopes = page.getByRole("group", { name: "Board scope" })
  await expect(scopes).toBeVisible({ timeout: 15_000 })
  const classTab = scopes.getByRole("button", { name: "Class" })
  await classTab.click()
  await expect(classTab).toHaveAttribute("aria-pressed", "true")

  /*
   * Since P5.11 the ranked container is a real <ol> and each row an <li>, so
   * DOM order is readable as list order. Before that `BoardRow` was a bare
   * <div> in a bare <div> — no role, no accessible name, nothing to grab —
   * and the only way to read ordering was raw DOM order out of the section,
   * which asserts nothing a refactor would not silently break.
   *
   * `getByRole("listitem")` deliberately does NOT pick up the viewer's pinned
   * row: that row is the same component rendered outside the <ol> on purpose,
   * because its rank is out of sequence with the list above it. If it were
   * inside, this assertion could pass on a board where the viewer ranks last.
   */
  const rows = page.getByRole("listitem")
  await expect(rows).toHaveCount(leaderboard.expectedOrderByStudentKey.length)

  const expectedNames = leaderboard.expectedOrderByStudentKey.map(
    (key) => seed.students[key as keyof typeof seed.students].displayName,
  )
  const renderedNames = await rows.allInnerTexts()
  for (const [index, name] of expectedNames.entries()) {
    expect(
      renderedNames[index],
      `row ${index + 1} should be ${name} (expected order: ${expectedNames.join(" > ")})`,
    ).toContain(name)
  }

  // And the XP itself, so the ordering cannot be right by coincidence on a
  // board whose numbers are wrong. Ranks are 1..n because the seeded totals
  // are strictly distinct — equal XP is equal rank by design (D5.1), which is
  // exactly why the seed asserts distinctness before this spec ever runs.
  for (const [index, key] of leaderboard.expectedOrderByStudentKey.entries()) {
    const xp = leaderboard.weeklyXpByStudentKey[key]
    await expect(rows.nth(index)).toContainText(String(xp))
  }

  expect(errors, `console errors: ${errors.join("\n")}`).toEqual([])
})

test("a teacher's announcement reaches the class as a notice and an inbox row", async ({
  page,
}) => {
  const seed = readSeed()
  const { class: seedClass, teacher, students } = seed

  // A title unique to this run: `Read it` and `Mark as read` are otherwise
  // per-card generic names, and the whole flow is scoped through this string.
  const title = `P5.11 announcement ${Date.now()}`
  const body = "Bring a calculator to Thursday's session."

  // ── Teacher composes, through the real UI ────────────────────────────────
  // Real login rather than `injectSession`: the compose screen is what is
  // under test here, so the teacher half goes through the front door. (The
  // student half below injects, because its login is not what is being
  // tested — the same split phase4-journey.spec.ts already documents.)
  await page.goto("/login")
  await page.getByLabel("Email").fill(teacher.email)
  await page.getByLabel("Password").fill(teacher.password)
  await page.getByRole("button", { name: /sign in/i }).click()
  await expect(page).toHaveURL(/\/teacher$/, { timeout: 15_000 })

  await page.goto("/teacher/announcements")
  await page.getByLabel("Title").fill(title)
  await page.getByLabel("Message").fill(body)

  /*
   * Ticking the class is NOT optional, and skipping it is the trap in this
   * flow. `audience` already defaults to "classes", so the radio needs no
   * click and it looks like title + message + submit is the whole driver. But
   * `selectedClassIds` starts empty and gates the submit button's `disabled`
   * attribute — a spec that skips this line clicks a disabled button and dies
   * as a 30-second "element is not enabled" timeout, which reads as a hung app
   * rather than a missing tick.
   *
   * The checkbox's visible text is exactly the seeded class name: the DTO is
   * built as `label=row.name`, verbatim and undecorated.
   */
  await page.getByLabel(seedClass.name).check()

  const submit = page.getByRole("button", { name: "Save announcement" })
  await expect(submit).toBeEnabled()
  await submit.click()

  // The success signal is server-derived — the count comes from the rows the
  // server says it created, not an optimistic local value — and the screen
  // does not navigate, so asserting on a URL change would wait forever.
  await expect(page.getByRole("status")).toContainText("Saved to 1 class", {
    timeout: 15_000,
  })

  // ── The student sees it on S-28, and reading it is one click ─────────────
  const student = students.declining
  await injectSession(page, {
    accessToken: student.accessToken,
    userId: student.userId,
    role: "student",
  })
  await page.goto("/student/announcements")

  const heading = page.getByRole("heading", { name: title })
  await expect(heading).toBeVisible({ timeout: 15_000 })
  await expect(page.getByText("Unread")).toBeVisible()

  /*
   * Opening *is* reading — the expand handler fires the receipt on first open
   * — so this single click is the whole `POST /{id}/read` round trip asserted
   * end to end through the UI.
   *
   * Scoped by title rather than by the bare "Read it" name. Every card renders
   * an identically-named button, so the bare locator resolves today only
   * because the seed seeds zero announcements and this flow posts exactly one.
   * That is a precondition of the fixture, not a property of the screen: the
   * day any session seeds an announcement, a bare locator becomes a
   * strict-mode violation in a spec that never changed. (P5.11 also gave the
   * button a title-bearing accessible name, which is what makes this scoping
   * possible — and fixes the same ambiguity for screen-reader users.)
   */
  await page.getByRole("button", { name: `Read it: ${title}` }).click()
  await expect(page.getByText("Unread")).toHaveCount(0, { timeout: 15_000 })
  await expect(page.getByText(body)).toBeVisible()

  // ── …and the same POST fanned out to the notification inbox (G-13) ───────
  // One driver, two assertions: the teacher's POST notifies every student
  // recipient, so "push delivery" needs no separate cause. No preference
  // seeding either — a student with no stored preferences row reads DEFAULTS,
  // which is every type enabled.
  await page.goto("/student/notifications")
  await expect(
    page.getByRole("heading", { name: "New announcement" }),
  ).toBeVisible({ timeout: 15_000 })
  // Unlike `grade_ready`, an announcement DOES have a resolvable destination,
  // so this row carries a working Open button.
  await expect(page.getByRole("button", { name: "Open" }).first()).toBeVisible()
})

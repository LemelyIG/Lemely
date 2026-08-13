import { test, expect } from "@playwright/test"
import { watchConsole } from "./console-errors"
import { readSeed } from "./seed"

/*
 * Phase 3's named acceptance criterion (BUILD/MISSION.md §4, Phase 3): "E2E
 * per role (Playwright)". Teacher journey: real UI login (email/password —
 * teachers/school_admins have no OTP path; G-05 is parent-only, covered in
 * parent-journey.spec.ts), then T-01 -> T-02 -> T-03 -> T-04 -> T-05 -> T-06,
 * asserting the seeded class and its three roster students render, and that
 * headline numbers (average mark, at-risk count, the declining student's own
 * roster row) come from the real seeded data in scripts/seed_e2e.py, not
 * placeholders.
 *
 * The at-risk *engine* itself — the backend reasons matching
 * `expectedAtRiskReasons` exactly, and the T-06 acknowledge/undo round trip
 * (D3.5: a flag stays listed and tagged, never disappears) — is asserted
 * exhaustively in at-risk-flags.spec.ts. This spec only checks the flags
 * surface at all on the screens a teacher actually walks through in order.
 */

test("teacher walks overview -> classes -> roster -> analytics -> student detail -> at-risk", async ({
  page,
}) => {
  const seed = readSeed()
  const errors = watchConsole(page)
  const { teacher, class: seedClass, students } = seed
  const { declining, inactive, control } = students

  // ── Real login UI (not session injection) ────────────────────────────────
  await page.goto("/login")
  await page.getByLabel("Email").fill(teacher.email)
  await page.getByLabel("Password").fill(teacher.password)
  await page.getByRole("button", { name: /sign in/i }).click()
  await expect(page).toHaveURL(/\/teacher$/, { timeout: 15_000 })

  // ── T-01 Overview ────────────────────────────────────────────────────────
  // A regex across all three greetings, not the literal "Good morning" this
  // asserted until P3.2. The screen used to render "Good morning." at every
  // hour of the day, so a literal was safe; it now greets by the reader's
  // actual local time, which means a fixed string turns this suite red for
  // sixteen hours out of every twenty-four. `greetingFor` owns the boundaries
  // and is unit-tested at each of them (tests/unit/utils.test.ts); this only
  // needs to prove the header rendered at all.
  await expect(page.getByText(/Good (morning|afternoon|evening)/)).toBeVisible({
    timeout: 15_000,
  })
  // Scoped to <main>, not the whole page: the sidebar's "Your classes" list
  // (ClassesNavSection) links to the same class with the same accessible
  // name, which would otherwise make this locator ambiguous.
  const overviewCard = page.locator("main a").filter({ hasText: seedClass.name })
  await expect(overviewCard).toBeVisible()
  // Average mark: mean of the roster's 3 latest paper percentages
  // (55, 75, 78) -> 69%. At-risk count: declining + inactive, never
  // control -> 2. Both are real numbers from the seeded attempts, not a
  // fixed mock.
  await expect(overviewCard).toContainText("69%")
  await expect(overviewCard).toContainText("2 at risk")

  // ── T-02 Classes ──────────────────────────────────────────────────────────
  await page.getByRole("link", { name: "Classes", exact: true }).click()
  await expect(page.getByText("New class")).toBeVisible({ timeout: 15_000 })
  const classesRow = page.locator("tbody tr").filter({ hasText: seedClass.name })
  await expect(classesRow).toBeVisible()
  const classesCells = classesRow.locator("td")
  await expect(classesCells.nth(2)).toHaveText("3") // student count
  await expect(classesCells.nth(3)).toHaveText("69%") // average mark
  await expect(classesCells.nth(5)).toHaveText("2") // at-risk count

  // ── T-03 Class detail roster ─────────────────────────────────────────────
  await classesRow.getByRole("link", { name: seedClass.name }).click()
  await expect(page.getByText("All classes")).toBeVisible({ timeout: 15_000 })
  for (const name of [declining.displayName, inactive.displayName, control.displayName]) {
    await expect(page.getByRole("link", { name })).toBeVisible()
  }
  const decliningRoster = page.locator("tbody tr").filter({ hasText: declining.displayName })
  const rosterCells = decliningRoster.locator("td")
  await expect(rosterCells.nth(2)).toHaveText("55/100") // latest mark
  await expect(decliningRoster.getByRole("img", { name: "Predicted grade D" })).toBeVisible()
  // "Trend" (`_student_delta`, teacher.py) compares the latest paper only
  // against a PRIOR ATTEMPT OF THE SAME PAPER NUMBER (`compare_performance`
  // matches on subject_code + paper_number) — scripts/seed_e2e.py's 3
  // declining attempts are paper_number 1/2/3 (a different paper each time,
  // by construction of `_persist_attempts`' enumerate loop), so there is no
  // same-paper prior and this column honestly reads "No prior paper", not a
  // delta. The 27pp *decline* is a real, separate signal — asserted via the
  // at-risk flag's own evidence sentence below, which reads the last 3
  // grade-bearing records regardless of paper number (D3.3 rule 1).
  await expect(rosterCells.nth(4)).toContainText("No prior paper")

  // ── T-04 Analytics ────────────────────────────────────────────────────────
  const tabs = page.getByRole("navigation", { name: "Class detail sections" })
  await tabs.getByRole("link", { name: "Analytics", exact: true }).click()
  await expect(page.getByText("Topic weakness heatmap")).toBeVisible({ timeout: 15_000 })

  // ── T-05 Student detail (declining) ──────────────────────────────────────
  await tabs.getByRole("link", { name: "Roster", exact: true }).click()
  await expect(page.getByText("All classes")).toBeVisible({ timeout: 15_000 })
  await page
    .locator("tbody tr")
    .filter({ hasText: declining.displayName })
    .getByRole("link", { name: declining.displayName })
    .click()
  await expect(page.getByText("At-risk flags")).toBeVisible({ timeout: 15_000 })
  await expect(page.getByRole("heading", { name: declining.displayName })).toBeVisible()
  // The engine's real, data-derived sentence (82% -> 68% -> 55%, the exact
  // seeded scores) — not just a chip with no evidence attached.
  await expect(
    page.getByText("Declining over the last 3 papers: 82% -> 68% -> 55% (27pp drop)."),
  ).toBeVisible()

  // ── T-06 At-risk list ─────────────────────────────────────────────────────
  await page.getByRole("link", { name: "At-risk students", exact: true }).click()
  await expect(page.getByText("Flagged by trajectory")).toBeVisible({ timeout: 15_000 })
  await expect(page.getByRole("link", { name: declining.displayName })).toBeVisible()
  await expect(page.getByRole("link", { name: inactive.displayName })).toBeVisible()
  await expect(page.getByRole("link", { name: control.displayName })).toHaveCount(0)

  expect(errors, `console/page errors: ${JSON.stringify(errors, null, 2)}`).toEqual([])
})

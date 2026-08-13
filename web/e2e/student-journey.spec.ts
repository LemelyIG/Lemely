import { test, expect } from "@playwright/test"
import { watchConsole } from "./console-errors"
import { readSeed } from "./seed"

/*
 * Student journey — the seeded `correctedPaper` student: a standalone
 * student (not enrolled in the seed's class) with one persisted past-paper
 * attempt, kept separate from the roster's at-risk scenarios specifically
 * so grade/percentage surfaces are non-empty without entangling the at-risk
 * assertions (see scripts/seed_e2e.py's module docstring).
 *
 * correct-paper.spec.ts already covers the P2.10 upload/marking core loop
 * end to end (its own fresh signup, a real scan upload, real Gemini-mocked
 * marking) and is left untouched. This spec is deliberately narrower: real
 * UI login onto data seeded through a different path
 * (`AttemptRepository.persist_correction`, not a live upload) landing on a
 * genuinely non-empty dashboard, plus the P3.9-added `/student/parents`
 * screen this student has no reason to see populated.
 */

test("the corrected-paper student sees their real dashboard data and the parents screen", async ({
  page,
}) => {
  const seed = readSeed()
  const errors = watchConsole(page)
  const student = seed.students.correctedPaper

  await page.goto("/login")
  await page.getByLabel("Email").fill(student.email)
  await page.getByLabel("Password").fill(student.password)
  await page.getByRole("button", { name: /sign in/i }).click()
  await expect(page).toHaveURL(/\/student$/, { timeout: 15_000 })

  await expect(page.getByText("Loading overview…")).toHaveCount(0, { timeout: 15_000 })
  // Non-empty: the first-run view must NOT render — this student has one
  // seeded, persisted attempt (88%, subject 0625). P3.2 replaced the single
  // centred EmptyState ("Correct your first paper to see it here") with the
  // composed `GettingStarted` panel, so the string this asserted against no
  // longer exists anywhere. Anchored on the new panel's heading instead.
  await expect(page.getByText("Let's get your first paper marked")).toHaveCount(0)
  await expect(page.getByText("Subjects this session")).toBeVisible()
  // The subject row itself, not a bare `getByText("0625")` — the sidebar's
  // static "Physics" nav item is also tagged "0625" (student/data.ts), and
  // `SubjectRowDTO.name` echoes `code` (no human subject name source), so
  // "0625" appears twice more inside the row's own button — all three would
  // make an untargeted text lookup ambiguous.
  const subjectRow = page.getByRole("button", { name: /0625/ })
  await expect(subjectRow).toBeVisible()
  await expect(subjectRow).toContainText("1 papers corrected")
  await expect(page.getByRole("progressbar", { name: "0625 mastery: 88%" })).toBeVisible()
  await expect(
    page.getByRole("img", { name: /^Predicted grade [A-Z*]+$/ }).first(),
  ).toBeVisible()

  await page.goto("/student/parents")
  await expect(page.getByRole("heading", { name: "Your parents" })).toBeVisible({
    timeout: 15_000,
  })
  // This student was never linked to a parent (only the "declining" student
  // was, by scripts/seed_e2e.py) — the honest empty state, not a fabricated
  // row.
  await expect(page.getByText("Nobody is linked to your account yet.")).toBeVisible()

  expect(errors, `console/page errors: ${JSON.stringify(errors, null, 2)}`).toEqual([])
})

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

  // P3.3 replaced the "Loading overview…" text with layout-matching
  // skeletons, which announce themselves as a `status` region named
  // "Loading" instead of rendering that string.
  await expect(page.getByRole("status", { name: "Loading" })).toHaveCount(0, {
    timeout: 15_000,
  })
  // Lane L1: Home replaced the Overview. The first-run view must NOT render
  // for this student (one seeded paper in 0625), and the grade floor links
  // the subject.
  await expect(page.getByText("Let's mark your first paper")).toHaveCount(0)
  const floor = page.getByRole("main").getByRole("navigation", { name: "Your grades" })
  await expect(floor).toBeVisible()
  const subjectDoor = floor.getByRole("link").first()
  await expect(subjectDoor).toHaveAttribute("href", "/student/subject/0625")
  await expect(subjectDoor).toContainText(/pts to|Top grade/)

  await page.goto("/student/parents")
  await expect(page.getByRole("heading", { name: "Your parents" })).toBeVisible({
    timeout: 15_000,
  })
  // This student was never linked to a parent (only the "declining" student
  // was, by scripts/seed_e2e.py) — the honest empty state, not a fabricated
  // row.
  /*
   * P4.10 · the bare `<p>` became the kit's `EmptyState` (§9.7), so the
   * sentence is split: the heading states the fact, the body says what to do
   * about it. Both are asserted rather than only the first, because the second
   * half is the part that stops an empty screen reading as a broken one.
   */
  // `getByText`, not `getByRole("heading")`: `EmptyState` renders its heading
  // as a non-heading element, a Phase-2.5 gap recorded in that phase's report
  // §8 and still open. Asserting the role here would fail for a reason that has
  // nothing to do with this journey.
  await expect(page.getByText("Nobody is linked to your account yet")).toBeVisible()
  await expect(page.getByText("Only you can add someone.")).toBeVisible()

  expect(errors, `console/page errors: ${JSON.stringify(errors, null, 2)}`).toEqual([])
})

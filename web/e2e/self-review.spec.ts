import { test, expect } from "@playwright/test"
import { watchConsole } from "./console-errors"
import { readSeed } from "./seed"

/*
 * Student self-review (spec 2026-09-17), end to end against the real
 * backend: the seeded `selfReview` student opens their one paper from
 * history (a refresh-safe route, not the live post-correction state),
 * self-marks the low-confidence question "2" as fully earned, and only then
 * sees the marker's verdict. The marks move 3/5 -> 5/5 because the marker
 * was unsure (D2); no judge and no Gemini key are involved.
 */

const ROW_2 = /^2 (Correct|Partial credit|Incorrect)\./

test("a student self-marks a low-confidence question and the verdict is revealed only after", async ({
  page,
}) => {
  const seed = readSeed()
  const errors = watchConsole(page)
  const student = seed.students.selfReview

  await page.goto("/login")
  await page.getByLabel("Email").fill(student.email)
  await page.getByLabel("Password").fill(student.password)
  await page.getByRole("button", { name: /sign in/i }).click()
  await expect(page).toHaveURL(/\/student$/, { timeout: 15_000 })

  // This student's only paper is history index 0.
  await page.goto("/student/result/0")
  await expect(page.getByRole("status", { name: "Loading" })).toHaveCount(0, { timeout: 15_000 })
  await expect(page.getByLabel("3 out of 5 marks, 60 percent")).toBeVisible()

  await page.getByRole("button", { name: ROW_2 }).click()
  const form = page.getByTestId("self-review-form")
  await expect(form).toBeVisible()

  // Nothing about the marker's verdict is in the DOM before submission.
  await expect(page.getByTestId("self-review-outcome")).toHaveCount(0)
  await expect(page.getByText(/^Marker:/)).toHaveCount(0)
  // The three student-facing verdict strings (I6, task #63) use student
  // wording, deliberately distinct from the teacher screen's, and appear
  // only post-reveal.
  //
  // NOTE: the seeded `selfReview` student's paper is marked with
  // `equivalence_gate` off (`scripts/seed_e2e.py::self_review_report`), so
  // every point's `verdict` is null server-side (see
  // `lemely/db/review_repo.py`'s own comment: "unlike verdict [evidence_span]
  // is present today with equivalence_gate off"). That means the post-reveal
  // half of this assertion cannot yet be exercised by this seed: no verdict
  // chip ever renders for this student today. Extending the seed to produce
  // a verdict-bearing row requires `scripts/seed_e2e.py` (Python), which is
  // out of this task's file set. Only the pre-submit absence is asserted
  // below until that seed change lands.
  await expect(
    page.getByText(/Marked correct|Not shown in your answer|We could not find this in your working/),
  ).toHaveCount(0)

  const submit = form.getByRole("button", { name: /submit and reveal/i })
  await expect(submit).toBeDisabled()

  // Three points, one radio group each. Choose "earned" on all three.
  const groups = form.getByRole("group")
  await expect(groups).toHaveCount(3)
  for (const index of [0, 1, 2]) {
    await groups.nth(index).getByLabel("I earned this").check()
  }
  await expect(submit).toBeEnabled()
  await submit.click()

  const outcome = page.getByTestId("self-review-outcome")
  await expect(outcome).toBeVisible({ timeout: 15_000 })
  await expect(
    outcome.getByText("Your self-mark moved this question from 1 to 3 out of 3."),
  ).toBeVisible()
  await expect(outcome.getByText("Your mark was applied")).toHaveCount(2)
  await expect(outcome.getByText("You and the marker agree")).toHaveCount(1)
  await expect(page.getByTestId("self-review-form")).toHaveCount(0)

  // One pass per question: a reload shows the revealed state, never the form.
  await page.reload()
  await expect(page.getByRole("status", { name: "Loading" })).toHaveCount(0, { timeout: 15_000 })
  await expect(page.getByLabel("5 out of 5 marks, 100 percent")).toBeVisible()
  await page.getByRole("button", { name: ROW_2 }).click()
  await expect(page.getByTestId("self-review-outcome")).toBeVisible()
  await expect(page.getByTestId("self-review-form")).toHaveCount(0)

  expect(errors, `console/page errors: ${JSON.stringify(errors, null, 2)}`).toEqual([])
})

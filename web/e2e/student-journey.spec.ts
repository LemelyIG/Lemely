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
  /*
   * P4.10 · updated for the redesign, and the change is the point (§9.7).
   *
   * This was `getByRole("button")`. Surface 1 replaced the
   * `<button onClick={navigate(...)}>` with a real `<Link>` — the audit's M8
   * finding, raised against the teacher portal and sitting unremarked on the
   * student side: a button that navigates cannot be opened in a new tab,
   * middle-clicked or copied as a link, and it tells assistive technology that
   * something will happen rather than that somewhere will be reached. So the
   * role is `link` now, deliberately, and this asserts the better markup.
   *
   * The row's own text changed with it: "1 papers corrected" (which was also
   * ungrammatical at one) is now "88% · 1 paper", pluralised.
   *
   * And it is scoped to the ledger panel. The comment above warned that a bare
   * "0625" lookup is ambiguous; as a `link` it is ambiguous four more ways,
   * because P3.1's sidebar gives Physics, Practice, Flashcards and Study plan
   * their own `0625`-tagged links. Scoping to the panel is what makes the
   * assertion about the ledger row rather than about whatever matched first.
   */
  const ledger = page.locator("section, div").filter({
    has: page.getByRole("heading", { name: "Subjects this session" }),
  }).last()
  const subjectRow = ledger.getByRole("link", { name: /0625/ })
  await expect(subjectRow).toBeVisible()
  await expect(subjectRow).toContainText("1 paper")
  // Subject NAME, not the syllabus code: `e3d5afd` ("lead the student Overview
  // ledger row with the subject name") made `Overview.tsx` build this label
  // from `row.name`, so the accessible name became "Physics mastery: 88%". The
  // assertion kept asserting "0625" and had failed every sweep since. The
  // mastery figure itself is unchanged and still asserted — only the identifier
  // moved. The row locator above still matches on /0625/, which is correct:
  // the code remains in the row's own text, just not in this label.
  await expect(page.getByRole("progressbar", { name: "Physics mastery: 88%" })).toBeVisible()
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

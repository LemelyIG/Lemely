import { test, expect, type Page } from "@playwright/test"
import { watchConsole } from "./console-errors"
import { injectSession, readSeed, type SeedAccount } from "./seed"

/*
 * MISSION §4's named Phase-4 acceptance: "a new student onboards, takes
 * placement, receives a plan" — S-01/S-02 → S-03/S-04/S-05 → S-24.
 *
 * Greenfield: before this file, a case-insensitive grep for
 * `placement|study-plan|/plan/|practice|flashcard|onboard` across `web/e2e/`
 * returned nothing at all. Every prior spec is Phase-2/Phase-3 surface.
 *
 * WHY THIS IS FIVE TESTS AND NOT ONE LINEAR JOURNEY. The journey is spread
 * across four purpose-built placement accounts that must not be collapsed
 * into one, and the reason is a product rule, not a seeding convenience:
 * placement availability excludes a student's own prior placement questions
 * for the same subject, so driving `completed` onto the "available" screen
 * reports the pool exhausted on the very screen meant to show it available
 * (see `seed.ts`'s `placement.students` comment). One account cannot hold
 * two of these states at once, so the journey is expressed over the accounts
 * the seed builds for it. Each leg watches its own console and ends on
 * `expect(errors).toEqual([])`.
 *
 * RELATIONSHIP TO `web/scripts/audit.mjs`. The Puppeteer registry already
 * drives these same screens for axe/Lighthouse/screenshots. It proves they
 * *render clean*; this file proves they *behave*. The identifying strings and
 * the S-02 drive are deliberately inherited from that registry rather than
 * re-derived, including the three traps it already paid for:
 *
 *   1. `sessions? done` is a REGEX with an optional plural against
 *      `StudyPlanWeek.tsx`'s `{sessionCount === 1 ? "" : "s"} done`. It is
 *      not a literal `?`; a literal-string port silently never matches.
 *   2. S-05 must NOT be identified by "starting picture" — that phrase also
 *      renders on `PlacementInvite`, so the assertion would pass without the
 *      result screen ever loading. The registry caught exactly that vacuous
 *      pass. The string used below is unique to `PlacementResult`'s *marked*
 *      branch.
 *   3. The onboarding wizard's step is component state that remounts as
 *      `"subjects"` on every load (`Onboarding.tsx`'s seeding effect restores
 *      the *answers* from the server but never the step), so S-02 is
 *      unreachable by deep link and must be driven through the real UI.
 *
 * That same remount is why this file is safe to re-run and safe under
 * Playwright retry: `/student/onboard` does not redirect an already-onboarded
 * student, so the onboard leg is idempotent. And `audit.mjs` runs its own
 * `scripts/seed_e2e.py` invocation (separate from `global-setup.ts`'s), so
 * mutating a seeded account here cannot poison the later `puppeteer-audit`
 * leg of the same `check.sh` run.
 */

/** The real login UI, per the `student-journey.spec.ts` idiom. Used where the
 * point is that a *new* student can get in and onboard; the later legs use
 * `injectSession` because the login itself is not what they are testing. */
async function logIn(page: Page, account: SeedAccount): Promise<void> {
  await page.goto("/login")
  await page.getByLabel("Email").fill(account.email)
  await page.getByLabel("Password").fill(account.password)
  await page.getByRole("button", { name: /sign in/i }).click()
  await expect(page).toHaveURL(/\/student$/, { timeout: 15_000 })
}

async function asStudent(page: Page, account: SeedAccount): Promise<void> {
  await injectSession(page, {
    accessToken: account.accessToken,
    userId: account.userId,
    role: "student",
  })
}

/** Playwright's equivalent of `audit.mjs::pressToggleOnce` — the subject
 * chips are `button[aria-pressed]`. Toggling *once* rather than clicking
 * blindly is what makes the drive safe against an account a previous run
 * already onboarded. */
async function toggleSubjectOnce(page: Page, name: RegExp): Promise<void> {
  const chip = page.locator("button[aria-pressed]").filter({ hasText: name }).first()
  await expect(chip).toBeVisible({ timeout: 15_000 })
  if ((await chip.getAttribute("aria-pressed")) !== "true") await chip.click()
  await expect(chip).toHaveAttribute("aria-pressed", "true")
}

test("S-01/S-02 · a new student onboards through the real UI", async ({ page }) => {
  const seed = readSeed()
  const errors = watchConsole(page)
  const student = seed.placement.students.unonboarded

  // A genuinely un-onboarded account: no profile, no enrolment. The real
  // first-run state, not a reset one.
  await logIn(page, student)

  await page.goto("/student/onboard")
  await expect(page.getByText("What are you studying?")).toBeVisible({ timeout: 15_000 })

  await toggleSubjectOnce(page, /Physics/i)
  await page.getByRole("button", { name: /^continue$/i }).click()

  // S-02. Only reachable by actually completing S-01 (trap 3).
  await expect(page.getByText(/Which school/)).toBeVisible({ timeout: 15_000 })

  // The skipped-answer rendering, which is the one D4.5 turns on: every
  // questionnaire field is skippable, a skipped answer is NULL, and
  // `SkippableSlider` must show its `unsetLabel` rather than the value its
  // thumb happens to rest on. A regression to `formatValue(min)` would print
  // "0 hours/week" — invented precision (UI spec §1.4) that screenshots
  // perfectly clean, which is why it is asserted here and not left to the
  // visual gate.
  await page.getByRole("button", { name: /^skip$/i }).click()
  await expect(page.getByText(/outside school/)).toBeVisible({ timeout: 15_000 })
  await page.getByRole("button", { name: /^skip$/i }).click()
  await expect(page.getByText(/hours can you study each week/)).toBeVisible({ timeout: 15_000 })
  await expect(page.getByText("Not set").first()).toBeVisible()

  expect(errors, `console/page errors: ${JSON.stringify(errors, null, 2)}`).toEqual([])
})

test("S-03 · placement is offered where the bank supports it and honestly refused where it does not", async ({
  page,
}) => {
  const seed = readSeed()
  const errors = watchConsole(page)
  await asStudent(page, seed.placement.students.available)

  // 0625 is the only subject with a viable bank, and the seed guarantees it
  // with a pinned Paper-2 bank of its own rows.
  await page.goto(`/student/placement/${seed.placement.subjectCode}`)
  await expect(page.getByText("Get a real starting picture")).toBeVisible({ timeout: 15_000 })

  // The refusal is not a second-class case and it is asserted on the same
  // account: 0580 genuinely has zero ingested questions (D4.6 §5), so the
  // honest `no_questions` path is real product behaviour. Testing only the
  // happy path here would pass on a screen that had lost the refusal
  // entirely.
  await page.goto("/student/placement/0580")
  await expect(page.getByText("No placement test yet for this subject")).toBeVisible({
    timeout: 15_000,
  })
  // ...and it must be the refusal, not the invite wearing a different subject.
  await expect(page.getByText("Get a real starting picture")).toHaveCount(0)

  expect(errors, `console/page errors: ${JSON.stringify(errors, null, 2)}`).toEqual([])
})

test("S-04 · an in-progress placement test serves its questions", async ({ page }) => {
  const seed = readSeed()
  const errors = watchConsole(page)
  const student = seed.placement.students.inProgress
  await asStudent(page, student)

  // The seed leaves this assignment created and never submitted.
  await page.goto(`/student/placement/test/${student.assignmentId}`)
  await expect(page.getByText("Question 1 of")).toBeVisible({ timeout: 15_000 })
  // The count is the seed's own, not a hardcoded number: a test serving the
  // wrong number of questions still renders a perfectly good "Question 1 of".
  await expect(page.getByText(`Question 1 of ${student.questionCount}`)).toBeVisible()

  expect(errors, `console/page errors: ${JSON.stringify(errors, null, 2)}`).toEqual([])
})

test("S-05 · a submitted placement returns a marked baseline with real weak topics", async ({
  page,
}) => {
  const seed = readSeed()
  const errors = watchConsole(page)
  const student = seed.placement.students.completed
  await asStudent(page, student)

  // The seed takes and submits this one through the unmodified quiz
  // take/submit/mark path with exactly one deliberately wrong answer.
  await page.goto(`/student/placement/result/${student.assignmentId}`)

  // Trap 2: unique to the *marked* branch. "starting picture" also renders on
  // PlacementInvite.
  await expect(page.getByText(/This is a baseline, not a grade/)).toBeVisible({ timeout: 15_000 })
  // Really marked, not still processing — the pending branch renders its own
  // copy and would otherwise be indistinguishable from a slow pass.
  await expect(page.getByText("This usually only takes a moment")).toHaveCount(0)

  // The breakdown is backed by a real `WeaknessRecord`, which is the whole
  // point of the seed's one deliberately-wrong answer: a perfect score
  // produces no weakness rows at all, because `group_weak_areas` excludes any
  // topic with zero net lost marks. Verified directly against the DB while
  // writing this: the completed account holds exactly one row, "1 Motion,
  // forces and energy", 2 of 4 marks lost, accuracy 0.5.
  //
  // Each card body is reached from its own label. A `filter({ hasText })`
  // over `div` matches every ancestor as well, so `.last()` resolves to the
  // bare label (and passes vacuously on nothing) while `.first()` resolves to
  // an outer container holding *both* cards — which would let the weakest
  // assertion be satisfied by the strongest card's text.
  const card = (label: string) => page.getByText(label, { exact: true }).locator("..")

  // One topic in the breakdown, so it lands here — this is where the real
  // marked data has to show up.
  await expect(card("Strongest topics")).toContainText(/% accuracy/)

  // And "Weakest topics" is legitimately empty, which is worth pinning rather
  // than working around: `rankTopics` (placementData.ts) refuses to show the
  // same topic as both a strength and a weakness when the breakdown is
  // smaller than `2 * limit`. With a single topic that leaves this card on
  // its honest empty state — the alternative would be inventing a distinction
  // the data does not support (UI spec §1.4). A regression that dropped the
  // no-overlap rule would render the identical topic in both cards and fail
  // here.
  await expect(card("Weakest topics")).toContainText("Not enough data yet.")

  expect(errors, `console/page errors: ${JSON.stringify(errors, null, 2)}`).toEqual([])
})

test("S-24 · the student receives a study plan with concrete sessions", async ({ page }) => {
  const seed = readSeed()
  const errors = watchConsole(page)
  await asStudent(page, seed.practice.students.active)

  await page.goto(`/student/plan/${seed.studyPlan.subjectCode}`)

  // Trap 1: a regex with the plural optional, mirroring the registry.
  await expect(
    page.getByText(new RegExp(`0 of ${seed.studyPlan.activeSessionCount} sessions? done`)),
  ).toBeVisible({ timeout: 15_000 })

  // MISSION §4 asks for "concrete sessions (topic, activity, duration), not
  // vague advice" — so assert the plan names the topic the seed recorded,
  // rather than merely that a week rendered with a count in it.
  await expect(page.getByText(seed.studyPlan.activeSessionTopic).first()).toBeVisible()

  // Neither of the two honest not-a-plan states, which are real product
  // behaviour on other accounts and would otherwise satisfy a laxer check.
  await expect(page.getByText("Not enough to plan from yet")).toHaveCount(0)
  await expect(page.getByText("No plan for this week yet")).toHaveCount(0)

  expect(errors, `console/page errors: ${JSON.stringify(errors, null, 2)}`).toEqual([])
})

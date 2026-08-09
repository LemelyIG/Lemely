import { test, expect, type Page } from "@playwright/test"
import { watchConsole } from "./console-errors"
import { injectSession, readSeed, type SeedAccount } from "./seed"

/*
 * MISSION §4's *second* named Phase-4 acceptance criterion: "generated
 * practice demonstrably targets seeded weaknesses" (S-20). The first half —
 * onboard → placement → plan — is `phase4-journey.spec.ts`.
 *
 * WHAT MAKES THIS ONE DIFFERENT FROM "S-20 RENDERS". A spec that merely
 * loads the generator and asserts a heading passes just as happily on a
 * screen that ignores weaknesses entirely. The word in the criterion is
 * *demonstrably*, so the assertion here names a specific topic string and
 * requires the screen to have pre-selected it — and is paired with its
 * inverse on an account that has no weakness rows, where the same screen
 * must honestly refuse rather than invent a set.
 *
 * WHERE THE EXPECTED TOPIC COMES FROM, AND WHY IT IS NOT HARDCODED.
 * `seed.studyPlan.activeSessionTopic` is provably one of
 * `practice.students.active`'s recorded weak topics: `scripts/seed_e2e.py`
 * selects it from `PracticeService.topics(...).weak_topics` — the byte-
 * identical query `GET /practice/{code}/topics` serves this screen — and
 * **raises** if no plan session matches. So the seed cannot hand this spec a
 * topic that is not a real weakness, and a hardcoded literal here would
 * instead pin whatever the corpus happened to yield the day it was written.
 * That weakness itself is real: it comes from the seed marking one
 * deliberately-wrong answer through the unmodified engine.
 *
 * The identifying strings are inherited from `web/scripts/audit.mjs`'s
 * registry (`:1535-1581`) rather than re-derived, including its two traps
 * for this screen:
 *
 *   1. The shortfall panel — "Only N of M requested questions match" — is
 *      the *normal* path for this corpus, not an error (D4.10: a short set
 *      is not a failed set). It is a regex; the numbers are corpus-dependent
 *      and pinning them would break on every ingest.
 *   2. The `no_weaknesses` refusal only renders once the "Weak topics only"
 *      filter is actually applied, so it must be driven live rather than
 *      deep-linked. Toggling *once* (rather than clicking blindly) keeps the
 *      drive safe under Playwright retry.
 */

async function asStudent(page: Page, account: SeedAccount): Promise<void> {
  await injectSession(page, {
    accessToken: account.accessToken,
    userId: account.userId,
    role: "student",
  })
}

/** Playwright's equivalent of `audit.mjs::pressCheckboxOnce`: tolerant of the
 * box already being checked, so a re-run or a retry does not toggle it back
 * off and quietly test the opposite state. */
async function checkOnce(page: Page, name: string): Promise<void> {
  const box = page.getByRole("checkbox", { name })
  await expect(box).toBeVisible({ timeout: 15_000 })
  if (!(await box.isChecked())) await box.check()
  await expect(box).toBeChecked()
}

test("S-20 · the generated set demonstrably targets a seeded weakness", async ({ page }) => {
  const seed = readSeed()
  const errors = watchConsole(page)

  // The cross-reference below is only legitimate if the plan and the practice
  // generator are talking about the same subject. They are, but asserting it
  // means a future seed that splits them fails here loudly instead of
  // comparing a physics topic against a maths topic list and finding nothing.
  expect(seed.studyPlan.subjectCode).toBe(seed.practice.subjectCode)

  await asStudent(page, seed.practice.students.active)
  await page.goto(`/student/practice/${seed.practice.subjectCode}`)

  // Trap 1: the honest-shortfall panel is the normal path for this corpus.
  // Waiting on it also guarantees the *preview* query has resolved, so the
  // topic assertions below run against a settled screen rather than racing
  // the prefill.
  await expect(page.getByText(/Only \d+ of \d+ requested questions match/)).toBeVisible({
    timeout: 15_000,
  })

  // THE ACCEPTANCE ASSERTION. The chip label is `${topic} (${count})`, so
  // this is a substring match on the accessible name — and it must be
  // *checked*, not merely present: every topic in the subject has a chip on
  // this screen regardless of weakness, so asserting visibility alone would
  // pass on a generator that had lost the prefill entirely.
  const weakTopic = seed.studyPlan.activeSessionTopic
  await expect(page.getByRole("checkbox", { name: weakTopic })).toBeChecked()

  // And the prefill must be *selective*. `weakTopicPrefill` selects only the
  // student's weak topics; a regression that checked every chip would satisfy
  // the assertion above while making the word "targets" meaningless.
  const checkedTopics = page.locator("fieldset input[type=checkbox]:checked")
  await expect(checkedTopics).toHaveCount(1)

  expect(errors, `console/page errors: ${JSON.stringify(errors, null, 2)}`).toEqual([])
})

test("S-20 · a student with no recorded weaknesses is honestly refused, not given an invented set", async ({
  page,
}) => {
  const seed = readSeed()
  const errors = watchConsole(page)

  // The inverse of the test above, and the reason it is not vacuous. `bare`
  // is the same subject and the same bank — the only difference is that it
  // has no `WeaknessRecord` rows at all.
  await asStudent(page, seed.practice.students.bare)
  await page.goto(`/student/practice/${seed.practice.subjectCode}`)

  await expect(page.getByRole("heading", { name: /^Practice —/ })).toBeVisible({ timeout: 15_000 })

  // Nothing prefilled, because there is nothing to target. Same locator as
  // above, so the pair reads as one measurement taken twice.
  await expect(page.locator("fieldset input[type=checkbox]:checked")).toHaveCount(0)

  // Trap 2: the refusal only exists once the filter is applied.
  await checkOnce(page, "Weak topics only")
  await expect(page.getByText("No weak topics recorded yet")).toBeVisible({ timeout: 15_000 })

  // It must be the refusal, not a set that happens to be empty: an empty
  // preview would still render the "N questions match" panel and read as a
  // pass to any check that only asserted the absence of a set.
  await expect(page.getByText(/requested questions match/)).toHaveCount(0)

  expect(errors, `console/page errors: ${JSON.stringify(errors, null, 2)}`).toEqual([])
})

test("S-20 · a subject with no ingested questions gets the honest no-questions refusal", async ({
  page,
}) => {
  const seed = readSeed()
  const errors = watchConsole(page)
  await asStudent(page, seed.practice.students.active)

  // 0580 genuinely has zero ingested questions (D4.6 §5) — real product
  // behaviour on the real corpus, not a gap to code around. Asserted on the
  // *active* account so the refusal cannot be confused with the
  // `no_weaknesses` one above: this student has weaknesses, just not in a
  // subject the bank can serve.
  await page.goto("/student/practice/0580")
  await expect(page.getByText("No practice material for this filter set")).toBeVisible({
    timeout: 15_000,
  })
  await expect(page.getByText("No weak topics recorded yet")).toHaveCount(0)

  expect(errors, `console/page errors: ${JSON.stringify(errors, null, 2)}`).toEqual([])
})

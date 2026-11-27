import { test, expect, type Page } from "@playwright/test"
import { watchConsole } from "./console-errors"
import { injectSession, readSeed, type SeedAccount } from "./seed"

/*
 * MISSION §4's *second* named Phase-4 acceptance criterion: "generated
 * practice demonstrably targets seeded weaknesses" (S-20). The first half —
 * onboard → placement → plan — is `phase4-journey.spec.ts`.
 *
 * WHAT MAKES THIS ONE DIFFERENT FROM "S-20 RENDERS". A spec that merely
 * loads the set builder and asserts a heading passes just as happily on a
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
 * registry rather than re-derived, including its two traps for this screen.
 * L4 moved the screen into the set builder sheet
 * (`builder/SetBuilderSheet.tsx`), so every locator below is scoped to that
 * sheet's dialog. The measurements are unchanged; only the controls moved.
 *
 *   1. The shortfall line, "Only N questions match", is the *normal* path
 *      for this corpus, not an error (D4.10: a short set is not a failed
 *      set). It is a regex; the numbers are corpus-dependent and pinning
 *      them would break on every ingest.
 *   2. The `no_weaknesses` refusal only renders once the "Weak topics only"
 *      switch is actually on, so it must be driven live rather than
 *      deep-linked. Switching on *once* (rather than clicking blindly) keeps
 *      the drive safe under Playwright retry.
 */

async function asStudent(page: Page, account: SeedAccount): Promise<void> {
  await injectSession(page, {
    accessToken: account.accessToken,
    userId: account.userId,
    role: "student",
  })
}

/** Playwright's equivalent of `audit.mjs::pressSwitchOnce`: tolerant of the
 * switch already being on, so a re-run or a retry does not toggle it back
 * off and quietly test the opposite state. */
async function switchOnOnce(page: Page, name: string): Promise<void> {
  const sw = page.getByRole("switch", { name })
  await expect(sw).toBeVisible({ timeout: 15_000 })
  if ((await sw.getAttribute("aria-checked")) !== "true") await sw.click()
  await expect(sw).toHaveAttribute("aria-checked", "true")
}

const escapeRegExp = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")

test("S-20 · the generated set demonstrably targets a seeded weakness", async ({ page }) => {
  const seed = readSeed()
  const errors = watchConsole(page)

  // The cross-reference below is only legitimate if the plan and the practice
  // builder are talking about the same subject. They are, but asserting it
  // means a future seed that splits them fails here loudly instead of
  // comparing a physics topic against a maths topic list and finding nothing.
  expect(seed.studyPlan.subjectCode).toBe(seed.practice.subjectCode)

  await asStudent(page, seed.practice.students.active)
  await page.goto(`/student/practice/${seed.practice.subjectCode}`)
  const sheet = page.getByRole("dialog", { name: "Practice set" })

  // Trap 1: the honest shortfall is the normal path for this corpus.
  // Waiting on it also guarantees the *preview* query has resolved, so the
  // topic assertions below run against a settled screen rather than racing
  // the prefill.
  await expect(sheet.getByText(/Only \d+ questions? match/)).toBeVisible({ timeout: 15_000 })

  // THE ACCEPTANCE ASSERTION. The chip's accessible name is `${topic} ${count}`,
  // so it is matched as a whole name, and it must be *pressed*, not merely
  // present: every topic in the subject has a chip on this sheet regardless of
  // weakness, so asserting visibility alone would pass on a builder that had
  // lost the prefill entirely.
  const weakTopic = seed.studyPlan.activeSessionTopic
  await expect(sheet.getByRole("button", { name: new RegExp(`^${escapeRegExp(weakTopic)} \\d+$`) })).toHaveAttribute(
    "aria-pressed",
    "true",
  )

  // And the prefill must be *selective*. The weak-topic prefill selects only
  // the student's weak topics; a regression that pressed every chip would
  // satisfy the assertion above while making the word "targets" meaningless.
  await expect(sheet.getByRole("group", { name: "Topics" }).locator('[aria-pressed="true"]')).toHaveCount(1)

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
  const sheet = page.getByRole("dialog", { name: "Practice set" })
  await expect(sheet.getByRole("switch", { name: "Weak topics only" })).toBeVisible({ timeout: 15_000 })

  // Nothing prefilled, because there is nothing to target. Same locator as
  // above, so the pair reads as one measurement taken twice.
  await expect(sheet.getByRole("group", { name: "Topics" }).locator('[aria-pressed="true"]')).toHaveCount(0)

  // Trap 2: the refusal only exists once the filter is applied.
  await switchOnOnce(page, "Weak topics only")
  await expect(sheet.getByText("No weak topics yet. Turn this off to pick any topic.")).toBeVisible({
    timeout: 15_000,
  })

  // It must be the refusal, not a set that happens to be empty: an empty
  // preview would still render the "N questions match" status and read as a
  // pass to any check that only asserted the absence of a set.
  await expect(sheet.getByText(/questions? match/)).toHaveCount(0)
  await expect(sheet.getByRole("button", { name: "Start now" })).toBeDisabled()

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
  const sheet = page.getByRole("dialog", { name: "Practice set" })
  await expect(sheet.getByText(/^No .+ questions yet$/)).toBeVisible({ timeout: 15_000 })
  await expect(sheet.getByText("No weak topics yet", { exact: false })).toHaveCount(0)
  await expect(sheet.getByRole("button", { name: "Start now" })).toBeDisabled()

  expect(errors, `console/page errors: ${JSON.stringify(errors, null, 2)}`).toEqual([])
})

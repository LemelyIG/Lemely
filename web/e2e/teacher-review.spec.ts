import { test, expect } from "@playwright/test"
import { watchConsole } from "./console-errors"
import { readSeed } from "./seed"

/*
 * Teacher review item (T-08), end to end. This screen had NO behavioural
 * coverage before: `web/vitest.config.ts` is `environment: "node"` with no
 * jsdom, so its unit tests (`tests/unit/reviewItemMarkerVerdicts.test.ts`)
 * assert source text, and a reviewer showed that a guard placed one level
 * deeper — inside `MarkerVerdicts`' `points.map` callback rather than around
 * it — re-creates the exact invisible-point defect I6 exists to fix while
 * still passing every one of those assertions with a clean `tsc`. These are
 * the assertions that cannot be satisfied by a string check.
 *
 * Only ONE seeded review-queue row exists (`seed.reviewItem`, task #66's
 * `inactive`-student T-08 item) and its one question now carries all three
 * I6 verdicts on its three points. There is no second, legacy (no-verdict)
 * review-queue row in the seed to open — the seed's only other attempts
 * (`declining`/`control`/`corrected`/`belowTarget`) are all persisted at
 * HIGH confidence and never fan out into `review_queue` at all
 * (`scripts/seed_e2e.py::accuracy_report_for_score`'s `needs_teacher_review`
 * defaults false). Producing that second scenario needs a change to
 * `scripts/seed_e2e.py`, out of this file set — see the report for task #7 for
 * what's missing. The "legacy item, no marker-verdict section" half of this
 * screen's behaviour is therefore verified today only by
 * `reviewItemMarkerVerdicts.test.ts`'s source-text guard
 * ("renders nothing when no point carries a verdict"), not by this spec.
 */

test("a teacher sees every point's marker verdict, with awarded, withheld and unverifiable distinguishable", async ({
  page,
}) => {
  const seed = readSeed()
  const errors = watchConsole(page)
  const { teacher, reviewItem } = seed

  await page.goto("/login")
  await page.getByLabel("Email").fill(teacher.email)
  await page.getByLabel("Password").fill(teacher.password)
  await page.getByRole("button", { name: /sign in/i }).click()
  await expect(page).toHaveURL(/\/teacher$/, { timeout: 15_000 })

  await page.goto(`/teacher/review/${reviewItem.itemId}`)
  await expect(page.getByRole("status", { name: "Loading" })).toHaveCount(0, { timeout: 15_000 })

  const section = page.getByRole("region", { name: "Marker's per-point verdicts" })
  await expect(section).toBeVisible()

  // Every point renders — p1/p2/p3, not only the one the student self-marked
  // (there is no self-mark on this item at all: `SelfReviewPoints` answers a
  // different question and is asserted separately not to leak in here). This
  // is the assertion a source-text test cannot make: it requires a real
  // render to know the map callback actually produced three DOM rows rather
  // than silently dropping one.
  await expect(section.getByTestId("marker-verdict-row")).toHaveCount(3)

  // The three I6 verdicts must be distinguishable from each other on screen,
  // not just in the label map's source text (`review_item_point_verdicts()`
  // in `scripts/seed_e2e.py`: p1 awarded, p2 withheld, p3 unverifiable).
  await expect(section.getByText("Awarded", { exact: true })).toBeVisible()
  await expect(section.getByText("Withheld, judged absent")).toBeVisible()
  await expect(section.getByText("Unverifiable, could not confirm")).toBeVisible()

  // The quoted evidence span on p1 and the ECF chip on p3 — both real,
  // seeded fields (`ReviewItemPoint.evidenceSpan`/`ecfApplied`), not just
  // present in the wire type.
  await expect(section.getByText('"a = (v - u) / t = (20 - 0) / 4 = 5 m/s^2"')).toBeVisible()
  await expect(section.getByText("Carried forward from a prior point (ECF)")).toBeVisible()

  expect(errors, `console/page errors: ${JSON.stringify(errors, null, 2)}`).toEqual([])
})

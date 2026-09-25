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
 * Three seeded review-queue rows exist:
 *  - `seed.reviewItem` (task #66's `inactive`-student T-08 item), whose one
 *    question carries all three I6 verdicts on its three points — the
 *    "verdicts render, and are distinguishable" half below.
 *  - `seed.reviewItem.legacyItemId` (task #67), a SECOND row whose one
 *    question carries a mark scheme but neither a verdict nor a rationale on
 *    any point — the ordinary legacy shape every row has in production today
 *    (`equivalence_gate` defaults off) — the "no marker-verdict section at
 *    all" half below. A real render is the only thing that can establish an
 *    absence like this: `reviewItemMarkerVerdicts.test.ts`'s own source-text
 *    guard ("renders nothing when no point carries a verdict") cannot tell a
 *    correctly-suppressed section from a defect that silently drops content
 *    one level *inside* the guard, which is exactly the failure mode task #7's
 *    docstring above already describes for the verdicts-present case.
 *  - `seed.reviewItem.rationaleOnlyItemId` (final-review coverage gap), a
 *    THIRD row whose one question carries a marker's `rationale`
 *    (Python's `point_notes`) but no `verdict` on any point — the shape
 *    production actually ships today whenever a marker writes a note
 *    without `equivalence_gate` on, and exactly the shape
 *    `MarkerVerdicts`' guard was widened
 *    (`p.verdict !== null || p.rationale`) to keep rendering. Neither of the
 *    two rows above can stand in for it: the first carries a verdict on
 *    every point, the second carries neither a verdict nor a rationale on
 *    any.
 *
 * Task #72 adds the scan-crop coverage below. `seed.reviewItem.itemId`'s
 * question now also carries a real `source_box` and a real stored scan
 * (`scripts/seed_e2e.py`'s `review_item_source_scan`/`REVIEW_ITEM_SOURCE_BOX`,
 * added alongside this task), so it doubles as the box-bearing case;
 * `seed.reviewItem.legacyItemId` carries neither, so it doubles as the
 * boxless case. Neither of `reviewItemMarkerVerdicts.test.ts`'s new source-
 * text assertions can tell "the guard renders nothing" from "the guard
 * renders something the fetch then silently fails to load" — only a real
 * render, and a real check that the image actually decoded
 * (`naturalWidth > 0`), can.
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

test("a legacy question with no per-point verdict or rationale renders no marker-verdict section", async ({
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

  await page.goto(`/teacher/review/${reviewItem.legacyItemId}`)
  await expect(page.getByRole("status", { name: "Loading" })).toHaveCount(0, { timeout: 15_000 })

  // The screen itself must still have rendered (its own `<h1>`, distinct
  // from the verdicts section) — this is not a blank/broken page, only one
  // whose one question carries nothing for `MarkerVerdicts` to show.
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible()
  await expect(page.getByText("Marker's per-point verdicts")).toHaveCount(0)
  await expect(page.getByRole("region", { name: "Marker's per-point verdicts" })).toHaveCount(0)

  expect(errors, `console/page errors: ${JSON.stringify(errors, null, 2)}`).toEqual([])
})

test("a rationale-only question with no verdict still renders the marker's per-point rationale", async ({
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

  await page.goto(`/teacher/review/${reviewItem.rationaleOnlyItemId}`)
  await expect(page.getByRole("status", { name: "Loading" })).toHaveCount(0, { timeout: 15_000 })

  // This is exactly the shape production ships today: a marker's note
  // written with `equivalence_gate` off, so no point on this question ever
  // carries a `verdict` — only a `rationale`. `MarkerVerdicts`' guard was
  // widened to `p.verdict !== null || p.rationale` specifically to keep this
  // section rendering for it, and a real render is the only thing that can
  // prove the widening actually works at runtime — a source-text check
  // (`reviewItemMarkerVerdicts.test.ts`) cannot tell a section that renders
  // the rationale from one a narrower guard silently suppresses.
  const section = page.getByRole("region", { name: "Marker's per-point verdicts" })
  await expect(section).toBeVisible()
  await expect(
    section.getByText(
      "Working shown but the final line is illegible; benefit of the doubt given.",
    ),
  ).toBeVisible()

  expect(errors, `console/page errors: ${JSON.stringify(errors, null, 2)}`).toEqual([])
})

const SCAN_CROP_ALT = "The region of the student's scan this question's answer was read from"

test("a boxless question shows no scan-crop affordance", async ({ page }) => {
  const seed = readSeed()
  const errors = watchConsole(page)
  const { teacher, reviewItem } = seed

  await page.goto("/login")
  await page.getByLabel("Email").fill(teacher.email)
  await page.getByLabel("Password").fill(teacher.password)
  await page.getByRole("button", { name: /sign in/i }).click()
  await expect(page).toHaveURL(/\/teacher$/, { timeout: 15_000 })

  // `legacyItemId`'s question carries no `source_box` (task #67's seed never
  // set one), so `hasSourceBox` is `false` and no crop request should even go
  // out — see `useReviewItemCrop`'s own doc for why `enabled` must be exactly
  // that flag.
  await page.goto(`/teacher/review/${reviewItem.legacyItemId}`)
  await expect(page.getByRole("status", { name: "Loading" })).toHaveCount(0, { timeout: 15_000 })
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible()

  await expect(page.getByAltText(SCAN_CROP_ALT)).toHaveCount(0)
  await expect(page.getByText("This screen does not display the original scan.")).toBeVisible()

  expect(errors, `console/page errors: ${JSON.stringify(errors, null, 2)}`).toEqual([])
})

test("a box-bearing question shows the scan crop, and the image actually loads", async ({
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

  // `reviewItem.itemId`'s question now carries a real `source_box` AND a
  // real stored scan (`scripts/seed_e2e.py`'s `review_item_source_scan`), so
  // `GET .../crop` answers 200, not the 404 a box with no upload behind it
  // would produce.
  await page.goto(`/teacher/review/${reviewItem.itemId}`)
  await expect(page.getByRole("status", { name: "Loading" })).toHaveCount(0, { timeout: 15_000 })

  const crop = page.getByAltText(SCAN_CROP_ALT)
  await expect(crop).toBeVisible()
  // Presence in the DOM is not proof the image loaded -- a 404'd `src` is
  // still an `<img>` element sitting there. `naturalWidth` stays 0 until the
  // browser has actually decoded real image bytes into it, so this is the
  // one assertion that tells "the object URL resolved to a real PNG" apart
  // from "the fetch failed and this is a broken image". `expect.poll`, not a
  // bare `evaluate`, because the blob fetch that produces `src` is itself
  // asynchronous relative to the element first mounting.
  await expect
    .poll(() => crop.evaluate((el) => (el as HTMLImageElement).naturalWidth), {
      timeout: 15_000,
    })
    .toBeGreaterThan(0)
  await expect(
    page.getByText("This screen shows the region of the student's scan this answer was read from."),
  ).toBeVisible()

  expect(errors, `console/page errors: ${JSON.stringify(errors, null, 2)}`).toEqual([])
})

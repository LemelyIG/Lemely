import { test, expect, type Locator } from "@playwright/test"
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
 *
 * The C1 review of that task found a render-timing defect: `ReviewItem`'s
 * route carries no `key` (`portals/teacher/index.tsx`), so navigating
 * between two boxed items keeps the same component instance, and a stale
 * object URL from the PREVIOUS item could commit under the CURRENT item's
 * name for one render, before the crop hook's own effect had a chance to
 * clear it. `seed.reviewItem.rationaleOnlyItemId` (already seeded above for
 * the rationale-only case) now ALSO carries a real `source_box`, coloured
 * green EXACTLY at that box versus `itemId`'s red (`review_item_source_scan`
 * `"b"` vs `"a"`, both box-aligned, never a uniform page fill -- a uniform
 * fill cannot tell a correctly-cropped region from the wrong one or the
 * whole page uncropped) specifically so the two items' crops are
 * distinguishable by a pixel sample, not merely by both being present. The
 * navigation test below walks
 * `itemId` (A) -> `rationaleOnlyItemId` (B) -> back to A via the on-screen
 * "Next item" control and the browser's own back button — real client-side
 * transitions, never `page.goto` between two detail routes, which would
 * remount the screen and never exercise the bug at all.
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

/** Every request whose URL matches `.../review/{itemId}/crop`, collected via
 * `page.on("request", ...)` rather than polled from the DOM afterward. A
 * DOM check ("no image present") taken right after navigation is racy in
 * the direction that matters here: it can pass merely because an in-flight
 * fetch has not resolved YET, not because none was ever made -- this is
 * event-based, so it cannot be fooled by timing either way. Install it
 * BEFORE navigating, so a request fired during the very first render is
 * still caught. */
function watchCropRequests(page: import("@playwright/test").Page, itemId: string): string[] {
  const requests: string[] = []
  const pattern = new RegExp(`/review/${itemId}/crop$`)
  page.on("request", (request) => {
    if (pattern.test(request.url())) requests.push(request.url())
  })
  return requests
}

test("a boxless question shows no scan-crop affordance, and makes no crop request at all", async ({
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

  // `legacyItemId`'s question carries no `source_box` (task #67's seed never
  // set one), so `hasSourceBox` is `false` and no crop request should even go
  // out — see `useReviewItemCrop`'s own doc for why `enabled` must be exactly
  // that flag.
  const cropRequests = watchCropRequests(page, reviewItem.legacyItemId)
  await page.goto(`/teacher/review/${reviewItem.legacyItemId}`)
  await expect(page.getByRole("status", { name: "Loading" })).toHaveCount(0, { timeout: 15_000 })
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible()

  await expect(page.getByAltText(SCAN_CROP_ALT)).toHaveCount(0)
  await expect(
    page.getByText(
      "This screen does not display the original scan. What's below is Lemely's own transcription of the student's answer.",
    ),
  ).toBeVisible()
  // The request-level proof, paired with the box-bearing test's
  // `toHaveLength(1)` below: this is what actually discriminates "the fetch
  // never fired" from "it fired and got ignored", which the DOM checks above
  // cannot tell apart on their own.
  expect(cropRequests).toEqual([])

  expect(errors, `console/page errors: ${JSON.stringify(errors, null, 2)}`).toEqual([])
})

test("a box-bearing question shows the scan crop, the image actually loads, and exactly one crop request fires", async ({
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
  const cropRequests = watchCropRequests(page, reviewItem.itemId)
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
    page.getByText(
      "This screen shows the region of the student's scan this answer was read from, alongside Lemely's own transcription of it.",
    ),
  ).toBeVisible()
  // Paired with the boxless test's `toEqual([])` above: exactly one fetch,
  // not zero and not a retry storm.
  expect(cropRequests).toHaveLength(1)

  expect(errors, `console/page errors: ${JSON.stringify(errors, null, 2)}`).toEqual([])
})

test("a 404 from the crop route renders as absence, even though hasSourceBox is true", async ({
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

  // `hasSourceBox` is true for this item -- it has a real `source_box`
  // persisted -- but the crop route is forced to 404 here regardless,
  // standing in for the case `ReviewItemDetailDTO.hasSourceBox`'s own doc
  // names explicitly: the attempt may have no upload, or the stored object
  // may have expired, and `hasSourceBox` alone does not rule either out.
  await page.route(`**/teacher/review/${reviewItem.itemId}/crop`, async (route) => {
    await route.fulfill({
      status: 404,
      contentType: "application/json",
      body: JSON.stringify({ detail: "Not found" }),
    })
  })

  await page.goto(`/teacher/review/${reviewItem.itemId}`)
  await expect(page.getByRole("status", { name: "Loading" })).toHaveCount(0, { timeout: 15_000 })

  // Renders exactly like a genuinely boxless row: no crop image, no
  // broken-image frame standing in for it, no error affordance of any kind,
  // and the banner reads the SAME false-branch sentence a boxless item
  // gets -- not a half-true one that still claims to show the region.
  await expect(page.getByAltText(SCAN_CROP_ALT)).toHaveCount(0)
  await expect(
    page.getByText(
      "This screen does not display the original scan. What's below is Lemely's own transcription of the student's answer.",
    ),
  ).toBeVisible()
  // Scoped to a blob-sourced `<img>` specifically, not `getByRole("img")` --
  // this page legitimately carries two unrelated `role="img"` avatars (the
  // signed-in teacher's own, in the nav chrome, and the student's initials
  // fallback on this very item), neither of which is the crop. A blob: src
  // is the one thing only a successfully-fetched crop ever produces.
  await expect(page.locator('img[src^="blob:"]')).toHaveCount(0)
  await expect(page.getByText(/could not load|failed to load|error/i)).toHaveCount(0)

  // `errors` (from `watchConsole`) staying `[]` is half of "no error toast":
  // `console-errors.ts` already filters the browser's own "Failed to load
  // resource: ... 404" logging (which fires for ANY non-2xx response, this
  // one deliberately triggered), so this specifically proves the APP itself
  // never surfaced the forced 404 as a React error or an uncaught exception,
  // not merely that the browser's own network log was ignored.
  expect(errors, `console/page errors: ${JSON.stringify(errors, null, 2)}`).toEqual([])
})

/** Reads the crop `<img>`'s own centre pixel through an offscreen canvas —
 * the two seeded boxed items render a colour EXACTLY at
 * `REVIEW_ITEM_SOURCE_BOX` (red for item A, green for the rationale-only
 * item, `scripts/seed_e2e.py`'s `review_item_source_scan("a" | "b")`), on a
 * DIFFERENT background colour everywhere else -- not a uniform page fill.
 * A uniform fill cannot tell "the right region" from "the wrong region" or
 * "the whole page, uncropped" apart; a box-aligned fill can, because only
 * the correctly-cropped-and-padded region samples as pure red (or green) at
 * its centre. Waits for `naturalWidth > 0` first, same reasoning as the
 * box-bearing test above: presence in the DOM proves nothing about whether
 * the bytes actually decoded. */
async function sampleCropCentrePixel(crop: Locator): Promise<[number, number, number]> {
  await expect(crop).toBeVisible()
  await expect
    .poll(() => crop.evaluate((el) => (el as HTMLImageElement).naturalWidth), { timeout: 15_000 })
    .toBeGreaterThan(0)
  return crop.evaluate((el) => {
    const img = el as HTMLImageElement
    const canvas = document.createElement("canvas")
    canvas.width = img.naturalWidth
    canvas.height = img.naturalHeight
    const ctx = canvas.getContext("2d")
    if (!ctx) throw new Error("2d canvas context unavailable")
    ctx.drawImage(img, 0, 0)
    const { data } = ctx.getImageData(
      Math.floor(img.naturalWidth / 2),
      Math.floor(img.naturalHeight / 2),
      1,
      1,
    )
    return [data[0], data[1], data[2]]
  })
}

test("C1: navigating boxed item A to boxed item B and back to A shows A's crop, never B's", async ({
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

  // First visit to A: a real navigation is fine here, this establishes the
  // fiber the rest of the test reuses -- there is no "same instance" claim
  // to protect on a first mount.
  await page.goto(`/teacher/review/${reviewItem.itemId}`)
  await expect(page.getByRole("status", { name: "Loading" })).toHaveCount(0, { timeout: 15_000 })
  const colorA1 = await sampleCropCentrePixel(page.getByAltText(SCAN_CROP_ALT))

  // Walk forward via the on-screen "Next item" control -- a real client-side
  // `navigate()`, never `page.goto` -- until item B's own URL is reached.
  // The teacher's own unfiltered queue only ever holds this run's own three
  // low-confidence rows (queue visibility is scoped to the teacher's own
  // roster, so nothing from any other seed run or any other teacher can
  // appear in it), so this is bounded and terminates quickly; the count is
  // not hardcoded because the ordering is an implementation detail of
  // `scripts/seed_e2e.py`'s own persist order, not a contract this spec
  // should pin.
  const nextItemButton = page.getByRole("button", { name: /next item/i })
  let hops = 0
  while (!page.url().endsWith(`/teacher/review/${reviewItem.rationaleOnlyItemId}`)) {
    hops += 1
    if (hops > 5) {
      throw new Error(
        `Could not reach rationaleOnlyItemId (${reviewItem.rationaleOnlyItemId}) from itemId ` +
          `(${reviewItem.itemId}) via "Next item" within 5 hops -- current URL: ${page.url()}`,
      )
    }
    await nextItemButton.click()
    await expect(page.getByRole("status", { name: "Loading" })).toHaveCount(0, { timeout: 15_000 })
  }
  const colorB = await sampleCropCentrePixel(page.getByAltText(SCAN_CROP_ALT))
  expect(colorB).not.toEqual(colorA1)

  // Back to A, `hops` times, via the BROWSER's own back button -- a real
  // `popstate`-driven client-side transition, same fiber throughout. This is
  // the render C1 names: `ReviewItem`'s route carries no `key`, so React
  // Router does not remount the screen on this transition, and the first
  // render after it is exactly the render that used to commit B's
  // still-live object URL under A's name before the render-time `itemId` tag
  // (`useReviewItemCrop`) closed it.
  for (let i = 0; i < hops; i += 1) {
    await page.goBack()
    await expect(page.getByRole("status", { name: "Loading" })).toHaveCount(0, { timeout: 15_000 })
  }
  expect(page.url()).toContain(`/teacher/review/${reviewItem.itemId}`)
  const colorA2 = await sampleCropCentrePixel(page.getByAltText(SCAN_CROP_ALT))

  expect(colorA2).toEqual(colorA1)
  expect(colorA2).not.toEqual(colorB)

  expect(errors, `console/page errors: ${JSON.stringify(errors, null, 2)}`).toEqual([])
})

import { test, expect, type APIRequestContext, type Page } from "@playwright/test"
import { watchConsole } from "./console-errors"
import { injectSession, readSeed, type SeedAccount } from "./seed"

/*
 * Task 18 — end-to-end proof of paper deletion (spec 2026-09-22), against
 * the real FastAPI backend and a real browser (scripts/e2e_server.py; only
 * the Gemini-vision seam is mocked, and nothing in this spec touches it —
 * every paper here is seeded straight through AttemptRepository, never
 * uploaded).
 *
 * Nine scenarios, run in order against `scripts/seed_e2e.py`'s dedicated
 * `deletion` fixture (a class + three students, kept off every other class
 * in the seed so none of their pinned numbers move — see that fixture's own
 * docstring). Playwright runs this file's tests sequentially
 * (`workers: 1`, `fullyParallel: false` in playwright.config.ts) and they
 * share the one seeded backend, so later scenarios build on earlier ones'
 * mutations exactly as a real session would — `test.describe.serial` makes
 * that ordering an explicit contract rather than an accident of config.
 *
 * Logins use `injectSession` (a real access token `seed_e2e.py` minted
 * through the actual AuthService, placed in localStorage exactly as the
 * app's own login flow would) rather than driving the login form each time —
 * the same established pattern `staff-inbox.spec.ts`/`engagement.spec.ts`
 * use, and the login form itself is already proven end to end in
 * `student-journey.spec.ts`/`teacher-journey.spec.ts`. Every request this
 * spec makes, whether through the UI or through `page.request` (scenarios
 * 5/6/7's numeric assertions), is a real HTTP call to the real backend —
 * `page.request` shares this test's `baseURL` (127.0.0.1:5173), and vite's
 * `/api` proxy forwards it to the real FastAPI server the same as any click.
 *
 * Forbidden-word check (design §8, `QUALITY-BAR.md`): a deletion refusal
 * must never leak why a paper is held. Mirrors `paperDeletion.test.ts`'s own
 * regex.
 */
const INTEGRITY_LANGUAGE = /review|flag|plagiar|integrity|score/i

function authHeaders(account: { accessToken: string }): { Authorization: string } {
  return { Authorization: `Bearer ${account.accessToken}` }
}

async function apiGet(
  request: APIRequestContext,
  url: string,
  account: { accessToken: string },
): Promise<unknown> {
  const res = await request.get(url, { headers: authHeaders(account) })
  expect(res.ok(), `${url} -> ${res.status()}: ${await res.text()}`).toBeTruthy()
  return res.json()
}

async function apiPost(
  request: APIRequestContext,
  url: string,
  account: { accessToken: string },
  data: Record<string, unknown> = {},
): Promise<unknown> {
  const res = await request.post(url, { headers: authHeaders(account), data })
  expect(res.ok(), `${url} -> ${res.status()}: ${await res.text()}`).toBeTruthy()
  return res.json()
}

/** One row of `GET /api/teacher/classes`, narrowed to the fields this spec reads. */
interface ClassSummaryRow {
  id: string
  average: number | null
}

/** One row of `GET /api/teacher/review`, narrowed to the fields this spec reads. */
interface ReviewQueueRow {
  itemId: string
  attemptId: string | null
}

async function classAverage(
  request: APIRequestContext,
  teacher: SeedAccount,
  classId: string,
): Promise<number | null> {
  const body = (await apiGet(request, "/api/teacher/classes", teacher)) as { classes: ClassSummaryRow[] }
  const row = body.classes.find((c) => c.id === classId)
  expect(row, `class ${classId} missing from GET /api/teacher/classes`).toBeTruthy()
  return row!.average
}

async function reviewAttemptIds(
  request: APIRequestContext,
  teacher: SeedAccount,
  classId: string,
): Promise<string[]> {
  const body = (await apiGet(
    request,
    `/api/teacher/review?class_id=${classId}&limit=200`,
    teacher,
  )) as { items: ReviewQueueRow[] }
  return body.items.map((r) => r.attemptId).filter((id): id is string => id !== null)
}

/** The Subject page's paper-history row for one paper (identified by its
 * `_paper_label`-format text, e.g. "0625/21"). Scoped to the "Paper history"
 * card so it can never match the sidebar's unrelated subject-code chips. */
function paperHistoryRow(page: Page, codeFragment: string) {
  return page.getByRole("button").filter({ hasText: codeFragment })
}

async function deleteFromResultScreen(page: Page): Promise<void> {
  await page.getByRole("button", { name: "Delete" }).click()
  await page.getByRole("dialog").getByRole("button", { name: "Delete" }).click()
}

test.describe.serial("paper deletion (Task 18)", () => {
  const seed = readSeed()
  const { deletion, teacher } = seed
  const { student, integrityStudent, remarkStudent } = deletion

  // Paper labels this spec identifies papers by, matching
  // `routers/student.py::_paper_label` ("{code}/{number}{variant}{year}")
  // exactly — see that function. `student`'s four papers are paper_number
  // 1..4, oldest to newest.
  const P1 = "0625/11"
  const P2 = "0625/21"
  const P3 = "0625/31"
  const P4 = "0625/41"

  // The teacher class-Papers-tab table renders a different, longer label
  // for the same paper (`classPaperLabel`, `lib/teacherPaperDeletion.ts`:
  // "{code} Paper {n} Variant {v}, {session}"), not the compact
  // `_paper_label` format above — "Paper 4" alone is enough to pick out
  // `student`'s row unambiguously (the class's other enrolled student,
  // `integrityStudent`, has only a "Paper 1").
  const P4_CLASS_ROW = "Paper 4"

  test("1. delete a paper from the result screen: gone from the overview, grade moves", async ({
    page,
  }) => {
    const errors = watchConsole(page)
    await injectSession(page, { ...student, role: "student" })
    await page.goto("/student/subject/0625")

    // Precondition: all four papers are there before anything is deleted —
    // an assertion of absence later is only meaningful against a proven
    // presence now.
    await expect(paperHistoryRow(page, P1)).toBeVisible()
    await expect(paperHistoryRow(page, P4)).toBeVisible()
    await expect(page.getByRole("button").filter({ hasText: "0625/" })).toHaveCount(4)
    const weightedMeanBefore = await page.getByText("Weighted mean").locator("..").innerText()

    await paperHistoryRow(page, P1).click()
    await expect(page).toHaveURL(/\/student\/result\//)
    await expect(page.getByText("Paper 1 - Variant 1")).toBeVisible()

    await deleteFromResultScreen(page)
    await expect(page).toHaveURL(/\/student\/subject\/0625$/, { timeout: 15_000 })

    // Gone from the list — proven absent against the proven-present set above.
    await expect(paperHistoryRow(page, P1)).toHaveCount(0)
    await expect(page.getByRole("button").filter({ hasText: "0625/" })).toHaveCount(3)

    // The grade moved: the weighted mean over {P2,P3,P4} differs from the
    // one over all four papers captured above (60/68/74/81 — no coincidental
    // tie is possible across the two overlapping sets).
    const weightedMeanAfter = await page.getByText("Weighted mean").locator("..").innerText()
    expect(weightedMeanAfter).not.toEqual(weightedMeanBefore)

    expect(errors, `console/page errors: ${JSON.stringify(errors, null, 2)}`).toEqual([])
  })

  test("2. the positional-URL trap: delete the second of three, open the new second, get the right paper", async ({
    page,
  }) => {
    const errors = watchConsole(page)
    await injectSession(page, { ...student, role: "student" })
    await page.goto("/student/subject/0625")

    // Exactly three papers now (P1 went in scenario 1): newest-first, so
    // position 1/2/3 are P4/P3/P2.
    const rows = page.getByRole("button").filter({ hasText: "0625/" })
    await expect(rows).toHaveCount(3)

    // Prove the "second" position really is P3 before touching anything —
    // the trap this scenario exists to catch is a STALE association, and a
    // stale association can only be detected against a proven-fresh one.
    await expect(rows.nth(1)).toContainText(P3)
    await rows.nth(1).click()
    await expect(page.getByText("Paper 3 - Variant 1")).toBeVisible()

    // Delete P3 from its own result screen.
    await deleteFromResultScreen(page)
    await expect(page).toHaveURL(/\/student\/subject\/0625$/, { timeout: 15_000 })

    // Two papers left: P4, P2. The Subject query was invalidated before this
    // navigation landed (`useDeletePaper`'s `onSuccess`, Task 14) — this is
    // the live-browser proof that invalidation actually reaches the network,
    // not just the unit-level source-text gate `recentlyDeletedWiring.test.ts`
    // already pins.
    const rowsAfter = page.getByRole("button").filter({ hasText: "0625/" })
    await expect(rowsAfter).toHaveCount(2)
    await expect(rowsAfter.nth(0)).toContainText(P4)
    // The new "second" row: must be P2 — the paper actually at that position
    // now, not P3 (already deleted) surviving from a stale cache.
    await expect(rowsAfter.nth(1)).toContainText(P2)
    await rowsAfter.nth(1).click()
    await expect(page).toHaveURL(/\/student\/result\//)
    await expect(page.getByText("Paper 2 - Variant 1")).toBeVisible()
    await expect(page.getByText("Paper 3 - Variant 1")).toHaveCount(0)

    expect(errors, `console/page errors: ${JSON.stringify(errors, null, 2)}`).toEqual([])
  })

  test("3. restore from recently deleted: the paper and the grade come back", async ({ page }) => {
    const errors = watchConsole(page)
    await injectSession(page, { ...student, role: "student" })

    // The header's own paper count before restore ("2 papers corrected." —
    // P2, P4 survive scenarios 1/2) — captured so restore's effect on the
    // grade context is proven the same way scenario 1 proves delete's, not
    // just asserted by the paper reappearing in the history list below.
    // Not the weighted-mean text itself: the two-paper mean {P2,P4}=68,81
    // and the three-paper mean {P2,P3,P4}=68,74,81 round to the same
    // displayed percentage, so an inequality check on that text would be a
    // coincidental, not a real, proof — the paper count cannot tie the same
    // way.
    await page.goto("/student/subject/0625")
    const introBefore = await page.getByText(/papers corrected\.$/).innerText()
    expect(introBefore).toContain("2 papers")

    await page.goto("/student/recently-deleted")

    // Two rows: P1 (scenario 1) and P3 (scenario 2). Restore P3 specifically.
    // Three ancestors up: the label span -> its flex-col wrapper -> the row
    // div the Restore button is ALSO a child of (`RecentlyDeleted.tsx`'s
    // `DeletedPaperRow`) -> the Card.
    const p3Row = page.getByText("Paper 3,").locator("../../..")
    await expect(p3Row).toBeVisible()
    await p3Row.getByRole("button", { name: "Restore" }).click()
    await expect(p3Row).toHaveCount(0)

    // P1's row is untouched — proves this restored the one row asked for,
    // not every row.
    await expect(page.getByText("Paper 1,")).toBeVisible()

    await page.goto("/student/subject/0625")
    // Back to three papers: P4, P3, P2.
    const rows = page.getByRole("button").filter({ hasText: "0625/" })
    await expect(rows).toHaveCount(3)
    await expect(paperHistoryRow(page, P3)).toBeVisible()

    // The grade context came back too: a real third paper counted again, not
    // just its row reappearing in the list above.
    const introAfter = await page.getByText(/papers corrected\.$/).innerText()
    expect(introAfter).toContain("3 papers")
    expect(introAfter).not.toEqual(introBefore)
    await expect(page.getByText("Weighted mean")).toBeVisible()

    expect(errors, `console/page errors: ${JSON.stringify(errors, null, 2)}`).toEqual([])
  })

  test("4. an integrity-flagged paper refuses to delete: a date, and no integrity language", async ({
    page,
  }) => {
    const errors = watchConsole(page)
    await injectSession(page, { ...integrityStudent, role: "student" })
    await page.goto("/student/subject/0625")
    await paperHistoryRow(page, P1).click()
    await expect(page).toHaveURL(/\/student\/result\//)

    await page.getByRole("button", { name: "Delete" }).click()
    await page.getByRole("dialog").getByRole("button", { name: "Delete" }).click()

    const dialog = page.getByRole("dialog")
    // The hold's flat 409: a date, in "You'll be able to delete it from
    // <day> <Month>" shape (`deletionRefusal`).
    await expect(dialog.getByText(/You'll be able to delete it from/)).toBeVisible()
    const refusalText = await dialog.innerText()
    expect(refusalText).not.toMatch(INTEGRITY_LANGUAGE)
    // The dialog must still be open — a refused delete is not a silent no-op.
    await expect(dialog).toBeVisible()

    expect(errors, `console/page errors: ${JSON.stringify(errors, null, 2)}`).toEqual([])
  })

  test("5. R4 end to end: the teacher resolves the item, then the same paper deletes with no explanation shown", async ({
    page,
    request,
  }) => {
    // Resolve via the real routes named in the brief.
    const items = (await apiGet(
      request,
      `/api/teacher/review?class_id=${deletion.classId}&reason=plagiarism_flag`,
      teacher,
    )) as { items: ReviewQueueRow[] }
    const item = items.items.find((i) => i.attemptId === integrityStudent.attemptId)
    expect(item, "the integrity student's plagiarism_flag review item").toBeTruthy()
    await apiPost(request, `/api/teacher/review/${item!.itemId}/resolve`, teacher, {})

    const errors = watchConsole(page)
    await injectSession(page, { ...integrityStudent, role: "student" })
    await page.goto("/student/subject/0625")
    await paperHistoryRow(page, P1).click()
    await expect(page).toHaveURL(/\/student\/result\//)

    await deleteFromResultScreen(page)
    // The hold lifted — succeeds exactly like an ordinary delete, landing
    // back on the subject page with nothing left to explain (D8: the block
    // lifted without any screen saying why).
    await expect(page).toHaveURL(/\/student\/subject\/0625$/, { timeout: 15_000 })
    await expect(page.getByRole("dialog")).toHaveCount(0)
    await expect(page.getByText(P1)).toHaveCount(0)

    expect(errors, `console/page errors: ${JSON.stringify(errors, null, 2)}`).toEqual([])
  })

  test("6. a teacher unshares a paper: the class average moves, it leaves the review queue, the student's own overview is untouched", async ({
    page,
    request,
  }) => {
    const beforeAverage = await classAverage(request, teacher, deletion.classId)
    const beforeQueueAttemptIds = await reviewAttemptIds(request, teacher, deletion.classId)
    expect(beforeQueueAttemptIds).toContain(student.attemptIds[3])
    const studentOverviewBefore = await apiGet(request, "/api/student/subject/0625", student)

    const errors = watchConsole(page)
    await injectSession(page, { ...teacher, role: "teacher" })
    await page.goto(`/teacher/classes/${deletion.classId}/papers`)

    const row = page.getByRole("row").filter({ hasText: P4_CLASS_ROW })
    await expect(row).toBeVisible()
    await expect(row.getByText("Shared", { exact: true })).toBeVisible()
    await row.getByRole("button", { name: "Unshare" }).click()
    await page.getByRole("dialog").getByRole("button", { name: "Unshare" }).click()
    await expect(row.getByText("Unshared from this class")).toBeVisible()
    await expect(row.getByRole("button", { name: "Reshare" })).toBeVisible()

    const afterAverage = await classAverage(request, teacher, deletion.classId)
    expect(afterAverage).not.toEqual(beforeAverage)
    const afterQueueAttemptIds = await reviewAttemptIds(request, teacher, deletion.classId)
    expect(afterQueueAttemptIds).not.toContain(student.attemptIds[3])

    // R9: the student's own overview is byte-identical — unsharing reaches
    // class pages only.
    const studentOverviewAfter = await apiGet(request, "/api/student/subject/0625", student)
    expect(studentOverviewAfter).toEqual(studentOverviewBefore)

    expect(errors, `console/page errors: ${JSON.stringify(errors, null, 2)}`).toEqual([])
  })

  test("7. reshare: the average and the queue item both come back", async ({ page, request }) => {
    const beforeAverage = await classAverage(request, teacher, deletion.classId)
    const beforeQueueAttemptIds = await reviewAttemptIds(request, teacher, deletion.classId)
    expect(beforeQueueAttemptIds).not.toContain(student.attemptIds[3])

    const errors = watchConsole(page)
    await injectSession(page, { ...teacher, role: "teacher" })
    await page.goto(`/teacher/classes/${deletion.classId}/papers`)

    const row = page.getByRole("row").filter({ hasText: P4_CLASS_ROW })
    await row.getByRole("button", { name: "Reshare" }).click()
    await expect(row.getByText("Shared", { exact: true })).toBeVisible()

    const afterAverage = await classAverage(request, teacher, deletion.classId)
    expect(afterAverage).not.toEqual(beforeAverage)
    const afterQueueAttemptIds = await reviewAttemptIds(request, teacher, deletion.classId)
    expect(afterQueueAttemptIds).toContain(student.attemptIds[3])

    expect(errors, `console/page errors: ${JSON.stringify(errors, null, 2)}`).toEqual([])
  })

  test("8. R2: a teacher deletes their own console paper, sees it recently-deleted, and restores it", async ({
    page,
  }) => {
    const errors = watchConsole(page)
    await injectSession(page, { ...teacher, role: "teacher" })
    // The console card lives on the Grading screen (`_paper_label`: "Paper 9
    // V1 <session> - <date>"), not the Overview page.
    await page.goto("/teacher/grading")

    const card = page.getByRole("button", { name: /Open.*Paper 9/ })
    await expect(card).toBeVisible()
    await page.getByRole("button", { name: /Delete.*Paper 9/ }).click()
    await page.getByRole("dialog").getByRole("button", { name: "Delete" }).click()
    await expect(card).toHaveCount(0)

    await page.goto("/teacher/deleted")
    // Three ancestors up — same `DeletedPaperRow` shape as the student
    // screen (see scenario 3's own comment).
    const deletedRow = page.getByText(/Paper 9/).locator("../../..")
    await expect(deletedRow).toBeVisible()
    await deletedRow.getByRole("button", { name: "Restore" }).click()
    await expect(page.getByText("Nothing deleted right now")).toBeVisible()

    await page.goto("/teacher/grading")
    await expect(page.getByRole("button", { name: /Open.*Paper 9/ })).toBeVisible()

    expect(errors, `console/page errors: ${JSON.stringify(errors, null, 2)}`).toEqual([])
  })

  test("9. R7: a scan re-marked twice — deleting one result removes both", async ({ page }) => {
    const errors = watchConsole(page)
    await injectSession(page, { ...remarkStudent, role: "student" })
    await page.goto("/student/subject/0625")

    // Both attempts share one upload, so the paper-history table shows two
    // rows for the same "0625/11" paper — present, before either is touched.
    const rows = page.getByRole("button").filter({ hasText: "0625/" })
    await expect(rows).toHaveCount(2)

    await rows.first().click()
    await expect(page).toHaveURL(/\/student\/result\//)
    await deleteFromResultScreen(page)

    // The upload is gone, and with it every attempt marked from it (R7) —
    // the subject has nothing left to show at all, not one row.
    await expect(page.getByText("Nothing recorded for 0625 yet")).toBeVisible({ timeout: 15_000 })

    expect(errors, `console/page errors: ${JSON.stringify(errors, null, 2)}`).toEqual([])
  })
})

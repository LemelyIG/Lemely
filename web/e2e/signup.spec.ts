import { test, expect } from "@playwright/test"
import { watchConsole } from "./console-errors"
import { readSeed } from "./seed"

const BACKEND_URL = "http://127.0.0.1:8000"

/*
 * The three sign-up-flows acceptance journeys (issue #10, design spec §6,
 * plan Task 23): student, teacher, invite. Each drives the real UI against
 * the real backend exactly like every other spec in this suite — no mocked
 * network, only the real `MockEmailProvider`/`MockSmsProvider` seams the app
 * itself is wired with (D7.6). Follows `web/e2e/global-setup.ts`'s seeded-
 * identity pattern for the one journey that needs a pre-existing identity
 * (Invite); the other two create a brand-new account through the UI, which
 * is the thing under test.
 *
 * ── Selectors below are grounded in the shipped component source, not
 * guessed — every label/button-name string here was read out of the actual
 * `.tsx` it exercises (SignupRoleSelect.tsx, SignupDetails.tsx,
 * VerifyEmail.tsx, SubjectsStep.tsx, QuestionnaireStep.tsx, PlacementInvite.tsx,
 * CreateFirstClass.tsx, ClassDetail.tsx's JoinCodeChip, JoinWithCode.tsx) —
 * see this task's own report for the sandbox constraint that meant this file
 * could be written and typechecked but not run end to end here.
 *
 * ── The onboarding wizard is driven to completion, not merely reached ──────
 *
 * D7.9's gate is the point being tested through `/student`, so the journey
 * has to actually clear it to reach "dashboard". The click path (select one
 * subject → Continue; repeatedly press whichever of Skip/Continue/Finish the
 * questionnaire's one primary button currently reads, per
 * `QuestionnaireStep.tsx`'s own `isLast ? "Finish" : answered ? "Continue" :
 * "Skip"` label rule; "Later" on the placement invite that follows) is the
 * genuine shortest real path through the wizard, not a shortcut around it.
 */

test.describe("student sign-up: landing to dashboard", () => {
  test("a visitor signs up, verifies via the dev link, and clears onboarding onto the dashboard", async ({
    page,
  }) => {
    const errors = watchConsole(page)
    const runTag = `e2e${Date.now().toString(36)}`
    const email = `student-${runTag}@example.com`

    // /landing -> /signup (the hero CTA, Landing.tsx's own `landingHero.primaryCta`).
    await page.goto("/landing")
    // `.first()` because the landing page carries the hero CTA and the closing
    // CTA, both labelled "Mark a paper" and both routed to /signup by Task 19 —
    // `landingHero.primaryCta` and `landingClose.cta` share the label
    // deliberately. Without .first() Playwright's strict mode refuses the
    // ambiguity rather than silently picking one, which is the correct
    // behaviour and why this names the hero explicitly.
    await page.getByRole("button", { name: "Mark a paper" }).first().click()
    await expect(page).toHaveURL(/\/signup$/)

    // G-02 -> G-03 student variant. The link's accessible name is the whole
    // card (title + description, SignupRoleSelect.tsx's own composition), so
    // this matches on the title only.
    await page.getByRole("link", { name: /I'm a student/ }).click()
    await expect(page).toHaveURL(/\/signup\/student$/)

    // G-03: fill, consent, submit.
    await page.getByLabel("Name").fill("E2E Student")
    await page.getByLabel("Email").fill(email)
    await page.getByLabel("Password").fill("a-genuinely-strong-passphrase-1")
    await page.getByRole("checkbox").check()
    await page.getByRole("button", { name: "Create account" }).click()
    await expect(page).toHaveURL(/\/verify-email$/, { timeout: 15_000 })
    await expect(page.getByRole("heading", { name: "Verify your email" })).toBeVisible()

    // G-07: resend to obtain the dev link (D7.6 — MockEmailProvider never
    // delivers out of band, so this is the one UI-reachable way to it) and
    // follow it, exactly as G-07's own "developer only" panel intends.
    await page.getByRole("button", { name: "Resend verification link" }).click()
    const devLink = page.getByRole("link", { name: /^\/verify-email\// })
    await expect(devLink).toBeVisible({ timeout: 10_000 })
    const href = await devLink.getAttribute("href")
    if (!href) throw new Error("dev verification link had no href")

    await page.goto(href)
    // ConfirmScreen fires verifyEmail on mount and navigates away on success
    // (postVerifyPath -> the role home) — nothing here to assert on this
    // screen itself beyond the URL settling past it.
    await expect(page).toHaveURL(/\/student(\/onboard)?$/, { timeout: 15_000 })

    // D7.9: a fresh account has no onboardingCompletedAt, so the portal gate
    // sends it to /student/onboard regardless of which of the two the
    // previous line actually landed on.
    await expect(page).toHaveURL(/\/student\/onboard$/, { timeout: 15_000 })
    await expect(page.getByRole("heading", { name: "What are you studying?" })).toBeVisible({
      timeout: 15_000,
    })

    // S-01 subjects step: one subject is enough to unlock Continue
    // (SubjectsStep.tsx: `disabled={selectedCount === 0 || saving}`).
    await page.getByRole("button", { name: /Physics/ }).click()
    await page.getByRole("button", { name: "Continue" }).click()

    // S-01 questionnaire: press the one primary action (Skip/Continue/Finish)
    // until it finishes the wizard. Bounded rather than infinite — a stuck
    // loop should fail loudly, not hang the suite.
    for (let i = 0; i < 10 && page.url().includes("/student/onboard"); i++) {
      await page.getByRole("button", { name: /^(Skip|Continue|Finish)$/ }).click()
      await page.waitForTimeout(300)
    }
    expect(page.url(), "onboarding questionnaire never finished").not.toContain(
      "/student/onboard",
    )

    // handleFinish routes to the placement invite for the one subject
    // selected above (Onboarding.tsx: `firstSubject ? .../placement/... :
    // "/student"`) — "Later" (PlacementInvite.tsx's `handleLater`) is the
    // real, shipped way off that screen onto the dashboard.
    await expect(page).toHaveURL(/\/student\/placement\/0625$/, { timeout: 15_000 })
    await page.getByRole("button", { name: "Later" }).click()

    await expect(page).toHaveURL(/\/student$/, { timeout: 15_000 })
    await expect(page.getByRole("status", { name: "Loading" })).toHaveCount(0, {
      timeout: 15_000,
    })

    expect(errors, `console errors during the student journey:\n${errors.join("\n")}`).toEqual([])
  })
})

test.describe("teacher sign-up: role select to a class join code", () => {
  test("a visitor signs up as a teacher, skips verification, and ends the first-class step holding a join code", async ({
    page,
  }) => {
    const errors = watchConsole(page)
    const runTag = `e2e${Date.now().toString(36)}`
    const email = `teacher-${runTag}@example.com`

    await page.goto("/signup")
    await page.getByRole("link", { name: /I'm a teacher or tutor/ }).click()
    await expect(page).toHaveURL(/\/signup\/teacher$/)

    // D7.2/D7.2: the independent-account banner is the one thing this
    // variant shows that the student one does not.
    await expect(
      page.getByText("This creates an independent account, not tied to a school."),
    ).toBeVisible()

    await page.getByLabel("Name").fill("E2E Teacher")
    await page.getByLabel("Email").fill(email)
    await page.getByLabel("Password").fill("a-genuinely-strong-passphrase-2")
    await page.getByRole("checkbox").check()
    await page.getByRole("button", { name: "Create account" }).click()
    await expect(page).toHaveURL(/\/verify-email$/, { timeout: 15_000 })

    // D7.5's soft gate, exercised directly: continue WITHOUT verifying.
    // Marking is the only thing this account cannot do yet; creating a
    // class is not gated, and this is the assertion that it really is not.
    await page.getByRole("link", { name: "Continue to Lemely" }).click()

    // D7.10: zero classes sends a fresh teacher to the first-class step.
    await expect(page).toHaveURL(/\/teacher\/first-class$/, { timeout: 15_000 })
    await expect(page.getByRole("heading", { name: "Create your first class" })).toBeVisible()

    await page.getByLabel("Class name").fill(`E2E Class ${runTag}`)
    await page.getByRole("button", { name: "Create class" }).click()

    await expect(page.getByRole("heading", { name: /is ready/ })).toBeVisible({ timeout: 15_000 })
    // JoinCodeChip (ClassDetail.tsx, reused here per D7.10's own docstring) —
    // "the artifact a teacher came for". The button's own accessible name is
    // the code followed by "Copy", so this asserts a real code rendered
    // rather than an empty chip.
    // `JoinCodeChip` renders the code and the word "Copy" as two sibling nodes,
    // so the computed accessible name joins them with whitespace ("ABC123 Copy").
    // The first draft of this locator forbade that space and matched nothing.
    const joinCodeButton = page.getByRole("button", { name: /^[A-Z0-9]+\s*Copy$/ })
    await expect(joinCodeButton).toBeVisible()
    const joinCodeText = (await joinCodeButton.textContent()) ?? ""
    expect(joinCodeText.replace("Copy", "").trim().length).toBeGreaterThan(0)

    expect(errors, `console errors during the teacher journey:\n${errors.join("\n")}`).toEqual([])
  })
})

test.describe("invite redemption: a minted seat code, redeemed signed out", () => {
  test("a school admin mints a seat invite, and a signed-out visitor previews it and signs up straight into the seat", async ({
    page,
    playwright,
  }) => {
    const seed = readSeed()
    const errors = watchConsole(page)
    const admin = seed.schoolWithSeats.admin
    const schoolId = seed.schoolWithSeats.schoolId

    // ── Mint, via the real API with the seeded school_admin's token ────────
    //
    // Not through the product's own UI: as recorded in BUILD/BLOCKERS.md B8,
    // no screen in this build calls `POST /school/seats/invite-code` —
    // `Seats.tsx` never grew a "generate an invite code" action, only the
    // pre-existing direct-create flow. This is the one step of this journey
    // that is API-only rather than UI-driven, and it is deliberate, not a
    // shortcut around a control that exists.
    const apiContext = await playwright.request.newContext()
    // Seat usage BEFORE the mint, not before the redemption. D7.3 reserves the
    // seat at mint time on purpose, so that is when the school's quota moves.
    // `InviteService.mint_seat_invite`'s docstring is explicit that the
    // reservation "is the whole point": a seat assigned only at redemption
    // could race away between G-08's preview and the visitor typing the code,
    // and `_used_seats` counts a reserved seat exactly like a directly-created
    // one.
    //
    // The first draft of this journey baselined AFTER the mint and asserted
    // seatsUsed rose across the redemption alone. It cannot: redemption assigns
    // a seat the mint already counted, so that assertion failed against correct
    // behaviour. The delta below spans mint-plus-redeem, which is the real
    // quota story for one invited student.
    const overviewBefore = await apiContext.get(`${BACKEND_URL}/api/school/overview`, {
      headers: { Authorization: `Bearer ${admin.accessToken}` },
    })
    expect(overviewBefore.status()).toBe(200)
    const schoolsBefore = (await overviewBefore.json()) as {
      schools: { schoolId: string; seatsUsed: number }[]
    }
    const before = schoolsBefore.schools.find((s) => s.schoolId === schoolId)
    if (!before) throw new Error(`seeded school ${schoolId} missing from the admin's own overview`)

    const mintResponse = await apiContext.post(`${BACKEND_URL}/api/school/seats/invite-code`, {
      headers: { Authorization: `Bearer ${admin.accessToken}` },
      data: { schoolId },
    })
    expect(mintResponse.status(), await mintResponse.text()).toBe(200)
    const minted = (await mintResponse.json()) as { code: string; role: string }
    expect(minted.role).toBe("student")
    const code = minted.code

    // ── Preview, signed out ─────────────────────────────────────────────────
    await page.goto(`/join/${code}`)
    await expect(page.getByRole("heading", { name: "You're about to join" })).toBeVisible({
      timeout: 15_000,
    })
    await expect(page.getByText(seed.schoolWithSeats.name)).toBeVisible()

    // Signed out: "Continue" carries the code into G-03 with it retained
    // (JoinWithCodeScreen's own `confirmSignedOut` -> `signupPathForInvite`),
    // never a redeem call this screen makes itself.
    await page.getByRole("button", { name: "Continue" }).click()
    await expect(page).toHaveURL(/\/signup\/student\?code=/, { timeout: 15_000 })

    const runTag = `e2e${Date.now().toString(36)}`
    const studentEmail = `invited-student-${runTag}@example.com`
    await page.getByLabel("Name").fill("E2E Invited Student")
    await page.getByLabel("Email").fill(studentEmail)
    await page.getByLabel("Password").fill("a-genuinely-strong-passphrase-3")
    await page.getByRole("checkbox").check()

    // The redeem call SignupDetails.tsx fires from signup's own onSuccess —
    // waited for explicitly rather than inferred from the next screen, so a
    // silently-swallowed failure (that component's own documented behaviour
    // for THIS call, deliberately, so a raced seat cannot strand the fresh
    // account) cannot be mistaken for a real redemption.
    const redeemResponse = page.waitForResponse(
      (res) => res.url().includes(`/api/invites/${code}/redeem`),
      { timeout: 15_000 },
    )
    await page.getByRole("button", { name: "Create account" }).click()
    expect((await redeemResponse).status()).toBe(200)

    await expect(page).toHaveURL(/\/verify-email$/, { timeout: 15_000 })
    await expect(page.getByRole("heading", { name: "Verify your email" })).toBeVisible()

    // ── Land on a seat: verified against the school's own seat count ───────
    const overviewAfter = await apiContext.get(`${BACKEND_URL}/api/school/overview`, {
      headers: { Authorization: `Bearer ${admin.accessToken}` },
    })
    const schoolsAfter = (await overviewAfter.json()) as {
      schools: { schoolId: string; seatsUsed: number }[]
    }
    const after = schoolsAfter.schools.find((s) => s.schoolId === schoolId)
    expect(after?.seatsUsed, "seatsUsed did not increase after redemption").toBe(
      before.seatsUsed + 1,
    )

    await apiContext.dispose()
    expect(errors, `console errors during the invite journey:\n${errors.join("\n")}`).toEqual([])
  })
})

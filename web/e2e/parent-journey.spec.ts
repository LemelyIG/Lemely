import { test, expect } from "@playwright/test"
import { watchConsole } from "./console-errors"
import { injectSession, readSeed } from "./seed"

/*
 * Parent journey (G-05's real OTP UI + the seeded parent's read-only walk).
 * Two halves, deliberately independent:
 *
 * (a) Drives the real OTP UI end to end on a phone that has NEVER had a
 * challenge, because the seeded parent's own phone already spent its one
 * challenge inside scripts/seed_e2e.py (D3.16/D3.11's docstring is explicit
 * that a consumer must reuse the token that verify already produced) and the
 * resend cooldown (otp_min_resend_seconds, default 30s) makes a second
 * request for that same number a real 429 — not something to dodge by
 * racing the cooldown timer.
 *
 * (b) Walks the seeded parent (session-injected — G-05 itself is already
 * exercised in full by (a); injecting here is for the *other* routes,
 * per the brief) through their one linked child's real data.
 */

/** A random 10-digit local number, always non-zero-leading so
 * `toE164`/`localDigits` (ParentLogin.tsx) never strips a leading zero and
 * shortens it below the client's 7-digit floor. Not scripts/seed_e2e.py's
 * `build_phone()` (that's the seeded parent's already-spent number) and,
 * with ~1-in-1e9 odds per call, not shared with any other invocation either. */
function freshLocalNumber(): string {
  const rand = Math.floor(Math.random() * 1e9)
    .toString()
    .padStart(9, "0")
  return `9${rand}`
}

test("a parent with a never-challenged phone completes the real OTP UI and lands on the empty state", async ({
  page,
}) => {
  const errors = watchConsole(page)
  await page.goto("/login/parent")

  await page.getByLabel("Phone number").fill(freshLocalNumber())
  await page.getByRole("button", { name: "Send code" }).click()

  // D3.16's developer affordance: POST /auth/otp/request returns `devCode`
  // (the offline mock SMS provider), and ParentLogin.tsx renders it in an
  // explicitly-labelled developer panel. Read the code from THAT panel and
  // complete the login through the real UI, exactly as the spec asks.
  const devLabel = page.getByText("Developer only · no SMS was sent")
  await expect(devLabel).toBeVisible({ timeout: 15_000 })
  const devPanel = devLabel.locator("xpath=..")
  const code = (await devPanel.locator("div.text-data-lg").innerText()).trim()
  expect(code).toMatch(/^\d{6}$/)

  await page.getByLabel("Digit 1 of 6").click()
  await page.keyboard.type(code)

  // `verify_otp` auto-creates the parent user on a fresh phone's first
  // successful verify (D3.11) — no children linked yet, so P-01 renders its
  // empty state, not a list.
  await expect(page).toHaveURL(/\/parent$/, { timeout: 15_000 })
  await expect(
    // Copy changed in P3.2: the em-dash the mission bans in UI text (§3.2
    // item 10) became a full stop. Same heading, same level, same meaning.
    page.getByRole("heading", { name: "You're signed in. One step to go." }),
  ).toBeVisible({ timeout: 15_000 })
  // The "how to link" explanation the spec mandates in place of a bare
  // empty list.
  await expect(
    page.getByText("Nobody has shared their results with you yet."),
  ).toBeVisible()
  await expect(page.getByText("Ask your child to open Lemely and sign in.")).toBeVisible()
  await expect(
    page.getByText("In their account, they add a parent using the phone number you just signed in with."),
  ).toBeVisible()

  expect(errors, `console/page errors: ${JSON.stringify(errors, null, 2)}`).toEqual([])
})

test("the seeded parent sees their one linked (declining) child's real data across P-01 -> P-04", async ({
  page,
}) => {
  const seed = readSeed()
  const errors = watchConsole(page)
  const { parent, students } = seed
  const declining = students.declining

  await injectSession(page, {
    accessToken: parent.accessToken,
    userId: parent.userId,
    role: "parent",
  })

  // P-01: with exactly one linked child, the spec mandates skipping
  // straight to P-02 (Children.tsx's `<Navigate replace>`) — genuinely
  // visiting /parent, not faking the redirect, mirroring audit.mjs's own
  // documented treatment of this identical seed shape.
  await page.goto("/parent")
  await expect(page).toHaveURL(new RegExp(`/parent/children/${declining.userId}$`), {
    timeout: 15_000,
  })

  // P-02: child overview — the linked child really is the declining student.
  await expect(page.getByRole("heading", { name: declining.displayName })).toBeVisible({
    timeout: 15_000,
  })
  await expect(page.getByText("Subjects")).toBeVisible()
  // At-risk signal, in parent-facing wording (never the teacher's "27pp
  // drop" jargon sentence verbatim).
  await expect(page.getByText("Their marks have been falling")).toBeVisible()
  await expect(
    page.getByText("These are signals to look into, not conclusions. Their teacher sees the same ones."),
  ).toBeVisible()

  // P-03: subject detail (0625 — scripts/seed_e2e.py's SUBJECT_CODE; every
  // declining-student attempt is this one subject).
  await page.getByRole("link", { name: /0625/ }).first().click()
  await expect(page.getByText("Papers they've done")).toBeVisible({ timeout: 15_000 })
  await expect(page.getByRole("img", { name: "Predicted grade D" })).toBeVisible()

  // P-04: weaknesses. scripts/seed_e2e.py persists every attempt with
  // `weak_areas=[]` (its scenarios are about grade trajectory, not topic
  // weakness) — the honest render here is the genuine empty state, not a
  // fabricated topic, asserted as such rather than worked around.
  await page.getByRole("link", { name: "All subjects" }).click()
  await expect(page.getByText("What to work on next")).toBeVisible({ timeout: 15_000 })
  await expect(page.getByText("Nothing stands out yet.")).toBeVisible()

  expect(errors, `console/page errors: ${JSON.stringify(errors, null, 2)}`).toEqual([])
})

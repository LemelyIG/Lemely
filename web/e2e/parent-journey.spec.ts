import { test, expect } from "@playwright/test"
import { watchConsole } from "./console-errors"
import { injectSession, readSeed } from "./seed"

/*
 * Parent journey (parent-invites design, spec §5/§6), superseding D3.11's
 * phone-OTP parent login (`ParentLogin.tsx`, `/login/parent`), which the
 * parent-invites design deletes. Three journeys, deliberately independent:
 *
 * (a) A fresh, signed-out visitor drives the real G-08 -> G-05 UI end to end:
 * opens a child's own `/join/:code` invite link, confirms an email code, sets
 * a password, and — because `POST /auth/parent/signup` redeems the invite and
 * signs the caller in as part of that one call (`signupParentLogic.ts`'s own
 * module docstring) — lands straight on the child they just gained access to.
 *
 * (b) Walks the seeded parent (session-injected — G-05 itself is already
 * exercised in full by (a); injecting here is for the *other* routes, per the
 * brief) through their one linked child's real data, P-01 -> P-04.
 *
 * (c) A signed-out returning parent — one who already has an account and is
 * already linked to a child, unlike (a)'s freshly-created one — signs in with
 * an ordinary email/password at `/login` like any other role now (design spec
 * §2: "a parent is an ordinary email/password account", superseding the old
 * per-role `/login/parent` OTP screen this suite used to drive here).
 */

test("a fresh visitor joins via a child's invite code, signs up with an emailed code, and lands on that child", async ({
  page,
}) => {
  const errors = watchConsole(page)
  const seed = readSeed()
  const declining = seed.students.declining

  // Run-tagged (seed_e2e.py mints a fresh `runTag` every seed run) so a
  // re-run of this suite against a re-seeded stack never collides with a
  // GoTrue user this very test created on a previous run — a second signup
  // attempt for the same email is a real 400 "already has an account"
  // (`parentRequestCodeFailure`), not something to dodge by cleaning up.
  const email = `parent-fresh-${seed.runTag}@example.com`

  // G-08: a signed-out visitor opens the child's own invite link directly,
  // exactly as a parent would from a link their child shared with them.
  await page.goto(`/join/${declining.parentInviteCode}`)
  await expect(
    page.getByText(`${declining.displayName} invited you to follow their progress on Lemely`),
  ).toBeVisible({ timeout: 15_000 })

  await page.getByRole("button", { name: "Create your parent account" }).click()
  await expect(page).toHaveURL(new RegExp(`/signup/parent\\?code=${declining.parentInviteCode}$`))

  // G-05 step 1: email + display name. `Your name` is optional on the wire
  // (`validateParentEmailStep`'s own docstring) but filled in here anyway,
  // matching a real visitor who has no reason to skip it.
  await expect(page.getByRole("heading", { name: "Create your parent account" })).toBeVisible()
  await page.getByLabel("Your name").fill("E2E Parent")
  await page.getByLabel("Email").fill(email)
  await page.getByRole("button", { name: "Send code" }).click()

  // G-05 step 2: D3.16's developer affordance — `POST /auth/parent/request-
  // code` returns `devCode` under the offline mock email provider, and
  // `SignupParent.tsx` renders it in an explicitly-labelled developer panel.
  // Read the code from THAT panel and complete verification through the real
  // `CodeInput` UI, exactly as this suite's retired phone-OTP test did.
  const devLabel = page.getByText("Developer only · no email was sent")
  await expect(devLabel).toBeVisible({ timeout: 15_000 })
  const devPanel = devLabel.locator("xpath=..")
  const code = (await devPanel.locator("div.text-data-lg").innerText()).trim()
  expect(code).toMatch(/^\d{6}$/)

  await page.getByLabel("Digit 1 of 6").click()
  await page.keyboard.type(code)

  // G-05 step 3: password + the D7.11 data-handling consent checkbox.
  await expect(page.getByRole("heading", { name: "Set a password" })).toBeVisible({
    timeout: 15_000,
  })
  await page.getByLabel("Password").fill("a-genuinely-strong-passphrase-1")
  await page.getByRole("checkbox").check()
  await page.getByRole("button", { name: "Create account" }).click()

  // `POST /auth/parent/signup` creates the account (email already verified),
  // links it to `declining` and signs in, all in one call — Children.tsx's
  // own single-child redirect (P-01 -> P-02, `<Navigate replace>`) then sends
  // this brand-new parent straight past the children list onto the one child
  // they just gained access to.
  await expect(page).toHaveURL(new RegExp(`/parent/children/${declining.userId}$`), {
    timeout: 15_000,
  })
  await expect(page.getByRole("heading", { name: declining.displayName })).toBeVisible({
    timeout: 15_000,
  })

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

test("a signed-out returning parent signs in with email and password and lands on their linked child", async ({
  page,
}) => {
  const errors = watchConsole(page)
  const seed = readSeed()
  const { parent, students } = seed
  // `parent.linkedStudent` is a key into `students` ("declining" today —
  // scripts/seed_e2e.py's `_provision_school_with_admin`-adjacent parent
  // block links this account to that student via `ParentLinkService.
  // link_in_session`, never through an invite), not a userId itself.
  const linkedChild = students[parent.linkedStudent as keyof typeof students]

  // G-04: a parent is an ordinary email/password account now (design spec
  // §2, superseding D3.11's phone-OTP `/login/parent`) — this drives the same
  // sign-in form every other role uses, real UI end to end, no session
  // injection.
  await page.goto("/login")
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible()
  await page.getByLabel("Email").fill(parent.email)
  await page.getByLabel("Password").fill(parent.password)
  await page.getByRole("button", { name: "Sign in" }).click()

  // `portalPathForRole("parent")` is `/parent`, but Children.tsx's own
  // single-child redirect (the same one (a) and (b) above exercise) sends a
  // parent with exactly one linked child straight past it onto that child —
  // this seeded parent, like the freshly-signed-up one, has exactly one.
  await expect(page).toHaveURL(new RegExp(`/parent/children/${linkedChild.userId}$`), {
    timeout: 15_000,
  })
  await expect(page.getByRole("heading", { name: linkedChild.displayName })).toBeVisible({
    timeout: 15_000,
  })

  expect(errors, `console/page errors: ${JSON.stringify(errors, null, 2)}`).toEqual([])
})

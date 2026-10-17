import { expect, type Locator, type Page } from "@playwright/test"
import { watchConsole } from "./console-errors"
import { readSeed } from "./seed"

/*
 * Shared helpers for native-feel.spec.ts (Task 12/B7). Kept separate from
 * the spec itself so the ten assertions read as assertions, not as repeated
 * login/selector/network-watching boilerplate.
 */

/**
 * Signs in through the real `/login` form (the `reduced-motion.spec.ts`
 * pattern — `getByLabel` + `getByRole("button", { name: /sign in/i })`),
 * using the fixed seeded account for the given role: the teacher, and the
 * student `control` account (no special seeded state, so any assertion that
 * just needs "a signed-in student" doesn't accidentally depend on one).
 * Assertions that need a specific seeded student's state (e.g. Assertion 5's
 * flashcard deck) sign in directly with that account's own credentials
 * instead of going through this helper.
 */
export async function signInAs(page: Page, role: "student" | "teacher"): Promise<void> {
  const seed = readSeed()
  const account = role === "student" ? seed.students.control : seed.teacher
  await page.goto("/login")
  await page.getByLabel("Email").fill(account.email)
  await page.getByLabel("Password").fill(account.password)
  await page.getByRole("button", { name: /sign in/i }).click()
  await expect(page).toHaveURL(new RegExp(`/${role}$`), { timeout: 15_000 })
}

/**
 * Waits out the route's own loading tier before an assertion inspects the
 * page, so a still-in-flight query (a route's profile/auth check) can't
 * make a size/count assertion look at an empty "Loading" screen and pass
 * vacuously. Every loading tier renders one `role="status"
 * aria-label="Loading"` region (`loading-shapes.tsx`/`state-views.tsx`);
 * this waits for it to be gone if one ever appeared, and is a no-op on a
 * route that never showed one.
 */
export async function waitForRouteReady(page: Page): Promise<void> {
  const loading = page.getByRole("status", { name: "Loading" })
  if (await loading.count()) {
    await expect(loading.first()).toBeHidden({ timeout: 15_000 })
  }
}

/**
 * Every element Assertion 2's tap-target rule governs: `button` and
 * `[role="button"]` unconditionally; `nav a` and any other `a` that is not
 * inside a `<p>` (a prose link is exempt — the same distinction the rule
 * text draws); and `label.cursor-pointer` — the `Checkbox`/`Radio`/`Switch`/
 * `FileDrop` idiom where the label itself is the tap target (each of those
 * four components puts `cursor-pointer` on its clickable `<label>`; see
 * `switch.tsx`'s own comment: "clicking the text toggles the switch").
 * `Input`/`Textarea`'s field-name caption is also a `<label>` but is never
 * `cursor-pointer` — it names the field, it isn't itself a control, so the
 * 44px rule does not apply to it any more than it applies to a paragraph of
 * body text. Returns a `Locator`, not a resolved list, so a caller can
 * `.all()` it after `page.emulateMedia`/route setup without re-querying.
 */
export function interactiveTargets(page: Page): Locator {
  return page.locator('button, [role="button"], nav a, label.cursor-pointer, a:not(p a)')
}

/**
 * Collects every signal a cold or authenticated load "went wrong" over the
 * network: built on `watchConsole` (console errors / uncaught page errors
 * already collected there) plus `requestfailed` events and any response
 * with `status >= 400` — the same shape `watchConsole` uses (push onto one
 * array, let the caller assert it's empty), so Assertion 9 reads as one
 * `expect(events).toEqual([])` rather than three separate listeners.
 */
export function failedRequests(page: Page): string[] {
  const events = watchConsole(page)
  page.on("requestfailed", (request) => {
    events.push(
      `[requestfailed] ${request.method()} ${request.url()} — ${
        request.failure()?.errorText ?? "unknown"
      }`,
    )
  })
  page.on("response", (response) => {
    if (response.status() >= 400) {
      events.push(`[response ${response.status()}] ${response.request().method()} ${response.url()}`)
    }
  })
  return events
}

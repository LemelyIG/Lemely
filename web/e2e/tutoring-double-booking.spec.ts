import { test, expect, type Browser, type Page } from "@playwright/test"
import { watchConsole } from "./console-errors"
import { injectSession, readSeed, type SeedAccount } from "./seed"

/*
 * E2E 5 (SPEC §e.4): double booking. Two students race for ONE slot of the same
 * tutor; exactly one request goes through and the other sees "Someone just
 * requested that time. Pick another."
 *
 * Seeded accounts (T29): `tutoring.discover.student` and `tutoring.discover.rival`,
 * both verified, with nothing booked and no safety notice acknowledged, racing for
 * a slot of `tutors.sufficient` (Amira K., every day 15:00-21:00). Each student has
 * their own browser context. Both fill the whole form to the point where only
 * "Send request" is left, and both press it in the same `Promise.all`; the
 * database's exclusion constraint on a tutor's live requests decides the winner.
 *
 * The slot is the first time of the FOURTH day, a day the other journeys that
 * use the same student (E2E 1 books the first day) never touch, so a student's
 * own earlier session cannot turn this refusal into "You already have a session
 * then."
 *
 * "Exactly one" is asserted twice: on the two screens, and from the API with each
 * student's own token (their lists hold one request for that start between them).
 */

const BACKEND_URL = "http://127.0.0.1:8000"
const TAKEN = "Someone just requested that time. Pick another."
const BOOKED = /\/student\/sessions\/[0-9a-f-]{36}$/
const RACE_DAY_INDEX = 3

interface Racer {
  who: SeedAccount
  page: Page
  errors: string[]
  slot: string
}

async function openRacer(browser: Browser, who: SeedAccount, tutorId: string): Promise<Racer> {
  const context = await browser.newContext()
  const page = await context.newPage()
  const errors = watchConsole(page)
  await injectSession(page, { accessToken: who.accessToken, userId: who.userId, role: "student" })
  await page.goto(`/student/tutors/${tutorId}/book`)
  await expect(page.locator("h1")).toContainText("Book a session with", { timeout: 15_000 })

  // Their first booking: the safety notice is up before the form can be used.
  const notice = page.getByRole("dialog", { name: "Before your first session" })
  if (await notice.isVisible().catch(() => false)) {
    await notice.getByRole("button", { name: "I understand" }).click()
    await expect(notice).toBeHidden()
  }
  return { who, page, errors, slot: "" }
}

/** Mode, the race day's first time, and nothing else; the form is then one click from sending. */
async function fillUpToSend(racer: Racer): Promise<void> {
  const { page } = racer
  await page.getByRole("radio", { name: "Virtual" }).check()
  const days = page.getByRole("group", { name: "Day" }).getByRole("radio")
  await expect(days.nth(RACE_DAY_INDEX)).toBeAttached({ timeout: 15_000 })
  await days.nth(RACE_DAY_INDEX).check({ force: true })
  const first = page.getByRole("group", { name: /^Times on/ }).getByRole("radio").first()
  await expect(first).toBeAttached()
  await first.check({ force: true })
  racer.slot = (await first.getAttribute("value")) ?? ""
  expect(racer.slot, "the chosen time's start").toMatch(/^\d{4}-\d{2}-\d{2}T/)
  await expect(page.getByText("Not chosen yet")).toHaveCount(0)
}

async function outcomeOf(page: Page): Promise<"booked" | "taken"> {
  await expect
    .poll(
      async () => {
        if (BOOKED.test(page.url())) return "booked"
        if ((await page.getByText(TAKEN).count()) > 0) return "taken"
        return "pending"
      },
      { timeout: 20_000, message: "the request resolves to a session or a taken-time message" },
    )
    .not.toBe("pending")
  return BOOKED.test(page.url()) ? "booked" : "taken"
}

test("two students race for one slot: exactly one request goes through", async ({ browser, playwright }) => {
  const seed = readSeed()
  const { discover, tutors } = seed.tutoring
  const tutorId = tutors.sufficient.tutorProfileId

  const a = await openRacer(browser, discover.student, tutorId)
  const b = await openRacer(browser, discover.rival, tutorId)
  await fillUpToSend(a)
  await fillUpToSend(b)
  expect(b.slot, "both students picked the same start").toBe(a.slot)

  await Promise.all([
    a.page.getByRole("button", { name: "Send request" }).click(),
    b.page.getByRole("button", { name: "Send request" }).click(),
  ])
  const outcomes = await Promise.all([outcomeOf(a.page), outcomeOf(b.page)])

  expect([...outcomes].sort(), "one booked, one taken").toEqual(["booked", "taken"])

  const [winner, loser] = outcomes[0] === "booked" ? [a, b] : [b, a]
  await expect(winner.page).toHaveURL(BOOKED)
  await expect(loser.page.getByText(TAKEN)).toBeVisible()
  // The loser stays on the form, the taken time is cleared and they can pick another.
  await expect(loser.page).toHaveURL(`/student/tutors/${tutorId}/book`)
  await expect(loser.page.getByText("Not chosen yet").first()).toBeVisible({ timeout: 15_000 })

  // From the API: between the two students, exactly one request holds that start with this tutor.
  let holding = 0
  for (const racer of [a, b]) {
    const request = await playwright.request.newContext({
      baseURL: BACKEND_URL,
      extraHTTPHeaders: { Authorization: `Bearer ${racer.who.accessToken}` },
    })
    const response = await request.get("/api/student/bookings", { params: { when: "upcoming" } })
    expect(response.status()).toBe(200)
    const page = (await response.json()) as {
      items: { startsAt: string; effectiveState: string; tutor: { tutorId: string } }[]
    }
    holding += page.items.filter(
      (booking) =>
        booking.tutor.tutorId === tutorId &&
        Date.parse(booking.startsAt) === Date.parse(a.slot) &&
        booking.effectiveState === "requested",
    ).length
    await request.dispose()
  }
  expect(holding, "requests holding the raced start").toBe(1)

  for (const racer of [a, b]) {
    expect(racer.errors, `console/page errors: ${JSON.stringify(racer.errors, null, 2)}`).toEqual([])
    await racer.page.context().close()
  }
})

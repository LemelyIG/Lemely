/**
 * The tutoring marketplace's entries for `audit.mjs`'s route registry (T33).
 *
 * SPEC `docs/tutoring/SPEC.md` §d, "Accessibility and performance gate routes",
 * lists 23 routes that need zero serious/critical axe violations, Lighthouse
 * accessibility >= 95 and no horizontal scroll at 320 px (and, for `/tutors`,
 * `/tutors/:id` and every `/student/*` route among them, performance >= 80).
 * This module is where those routes are registered, with the states each
 * screen has (default, loading, error, empty and the screen-specific ones from
 * §d, plus the dark theme). `web/tests/unit/auditTutoringRegistry.test.ts`
 * parses that SPEC list and fails when a route is missing here.
 *
 * ── Why `ready` is built from an expectation and not from a sentence ─────────
 *
 * Every state declares `expect`, the content that is specific to it, and
 * `ready` is derived from `expect` by `waitForExpectation`. That one function is
 * what keeps axe from passing on a page that is not the state it is filed
 * under (P28): it requires the route's own pathname (a redirect to /login
 * fails it), the state's heading and text, and the absence of everything that
 * would mean "a different state" (a C-11 error panel on a loaded state, a
 * loading skeleton on anything that is not the loading state). A login page, a
 * 404 and a crash screen all fail it, in the same way: `ready` times out and
 * the route is recorded in `route-failures.json`, which `check_ui_gates.py`
 * fails on.
 *
 * Lighthouse runs on each route's default state only (SPEC D3.17): every other
 * state sets `lighthouse: false`. Lighthouse drives its own navigation and never
 * replays `ready`, so it could only ever score the default view anyway.
 *
 * The module takes the two request-interception helpers from `audit.mjs`
 * (`hooks`) rather than importing that file, which runs the audit when loaded.
 * It imports nothing else, so the unit test loads it in Node without a browser.
 */

/** Phone, tablet, laptop. 320 px is the narrowest width the product promises to fit. */
export const TUTORING_BREAKPOINTS = [
  { width: 320, height: 740 },
  { width: 768, height: 1024 },
  { width: 1280, height: 900 },
]
const DARK_BREAKPOINTS = [{ width: 1280, height: 900 }]

/** How long a loading state holds the screen's own request, long enough to read the page. */
const LOADING_HOLD_MS = 6_000

const LOADING_SELECTOR = '[role="status"][aria-label^="Loading"]'

/** The pathname of a registry path, without its query. */
export const pathnameOf = (routePath) => new URL(routePath, "http://audit.invalid").pathname

/**
 * Waits for the page to be exactly the state `want` describes.
 *
 * `want.h1` is a pattern for a visible heading (not `sr-only`), `want.anyH1` for
 * any heading, `want.text` for the page text, `want.alert` for an `alert` region
 * and `want.loading` says the loading skeleton is the point. When `want.alert`
 * is absent the page must show no `alert` region at all, and when
 * `want.loading` is absent it must show no loading skeleton.
 */
export async function waitForExpectation(page, routePath, want, timeout = 20_000) {
  await page.waitForFunction(
    (pathname, expected, loadingSelector) => {
      if (window.location.pathname !== pathname) return false
      const matches = (source, value) => new RegExp(source, "i").test(value)
      const headings = Array.from(document.querySelectorAll("h1"))
      const visible = headings.filter((h) => !h.classList.contains("sr-only"))
      if (expected.h1 && !visible.some((h) => matches(expected.h1, h.textContent ?? ""))) return false
      if (expected.anyH1 && !headings.some((h) => matches(expected.anyH1, h.textContent ?? ""))) return false
      if (expected.text && !matches(expected.text, document.body.innerText)) return false
      if (expected.status) {
        const statuses = Array.from(document.querySelectorAll('[role="status"]'))
        if (!statuses.some((r) => matches(expected.status, r.textContent ?? ""))) return false
      }
      const alerts = Array.from(document.querySelectorAll('[role="alert"]'))
      if (expected.alert) {
        if (!alerts.some((a) => matches(expected.alert, a.textContent ?? ""))) return false
      } else if (alerts.length > 0) {
        return false
      }
      const loading = document.querySelector(loadingSelector) !== null
      return expected.loading ? loading : !loading
    },
    { timeout },
    pathnameOf(routePath),
    want,
    LOADING_SELECTOR,
  )
}

/**
 * `setup`/`teardown` for an offline state: the screen's own request fails the way a dropped
 * connection fails (the request is aborted, so `fetch` rejects), which `lib/api.ts` reports as
 * status 0 and the screen answers with C-11's offline panel instead of its error panel.
 */
export function offlineStateHooks(urlSubstring) {
  let handler
  return {
    setup: async (page) => {
      await page.setRequestInterception(true)
      handler = (req) => {
        if (req.url().includes(urlSubstring)) req.abort("internetdisconnected").catch(() => {})
        else req.continue().catch(() => {})
      }
      page.on("request", handler)
    },
    teardown: async (page) => {
      page.off("request", handler)
      await page.setRequestInterception(false)
    },
  }
}

/** Clicks the first enabled button whose label matches `pattern` (a RegExp source). */
async function clickButton(page, pattern, timeout = 15_000) {
  const handle = await page.waitForFunction(
    (source) => {
      const re = new RegExp(source, "i")
      return (
        Array.from(document.querySelectorAll("button")).find(
          (b) => re.test(b.textContent || b.getAttribute("aria-label") || "") && !b.disabled,
        ) ?? null
      )
    },
    { timeout },
    pattern,
  )
  const element = handle.asElement()
  if (!element) throw new Error(`No enabled button matching ${pattern}`)
  await element.click()
}

const escapeRe = (text) => text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
const exactly = (text) => `^${escapeRe(text)}$`

/**
 * One state of a route. `base` is the route's path; a state may name a different
 * `path` (a filter, another booking) and `session` (another account) only
 * through `buildEntry`, which splits those into separate registry entries.
 */
function state(name, slug, routePath, want, extra = {}) {
  return {
    state: name,
    slug,
    expect: want,
    ready: extra.drive
      ? async (page) => {
          await waitForExpectation(page, routePath, want)
          await extra.drive(page)
        }
      : (page) => waitForExpectation(page, routePath, want),
    ...(extra.lighthouse === false ? { lighthouse: false } : {}),
    ...(extra.waitUntil ? { waitUntil: extra.waitUntil } : {}),
    ...(extra.setup ? { setup: extra.setup } : {}),
    ...(extra.teardown ? { teardown: extra.teardown } : {}),
    ...(extra.colorScheme ? { colorScheme: extra.colorScheme } : {}),
    ...(extra.breakpoints ? { breakpoints: extra.breakpoints } : {}),
    ...(extra.shotSuffix ? { shotSuffix: extra.shotSuffix } : {}),
  }
}

/**
 * The registry entries for the tutoring screens.
 *
 * @param seed  the parsed `scripts/seed_e2e.py` contract
 * @param hooks `{ loadingStateHooks, errorStateHooks }` from `audit.mjs`
 */
export function buildTutoringRegistry(seed, hooks) {
  const T = seed.tutoring
  if (!T) throw new Error("the seed contract has no `tutoring` group; re-run scripts/seed_e2e.py from this tree")
  const { loadingStateHooks, errorStateHooks } = hooks

  const session = (account, role) => ({ accessToken: account.accessToken, userId: account.userId, role })
  const studentSession = session(T.student, "student")
  // A student with no sessions, no grants and no acknowledged safety notice.
  const newStudentSession = session(T.discover.student, "student")
  const tutorSession = session(T.tutors.sufficient, "teacher")
  const draftTutorSession = session(T.tutors.draft, "teacher")
  // The tutor whose results are hidden (fewer than five students) and who has no live grant.
  const sparseTutorSession = session(T.tutors.insufficient, "teacher")
  // A teacher with a class and no tutor profile.
  const teacherSession = session(seed.teacher, "teacher")
  const parentSession = session(seed.parent, "parent")
  const adminSession = session(T.platformAdmin, "platform_admin")

  const amiraId = T.tutors.sufficient.tutorProfileId
  const omarId = T.tutors.insufficient.tutorProfileId
  const draftTutorId = T.tutors.draft.tutorProfileId
  const bookings = T.bookings
  const child = seed.students.declining
  const kidName = child.displayName
  const grantedStudentId = T.grants.live.studentUserId
  const reportId = T.reports.openSafety.reportId

  const AMIRA = exactly("Amira K.")
  const sessionTitle = exactly(`${T.subjectName} with Amira K.`)

  /** loading + error + dark around a default state; `api` is the request the screen waits on. */
  function around(base, defaultState, api, { errorWant, loadingWant, dark = true, offline = true }) {
    const { screenId, path: routePath, slug } = base
    const loadingHooks = loadingStateHooks(api, LOADING_HOLD_MS)
    const errorHooks = errorStateHooks(api)
    const states = [
      defaultState,
      state("loading", `${slug}-loading`, routePath, loadingWant, {
        lighthouse: false,
        waitUntil: "domcontentloaded",
        ...loadingHooks,
      }),
      state("error", `${slug}-error`, routePath, errorWant, { lighthouse: false, ...errorHooks }),
    ]
    if (offline) {
      // The same screen, with the connection down: an offline panel, announced as a status, not an alert.
      const { alert: _alert, ...kept } = errorWant
      states.push(
        state("offline", `${slug}-offline`, routePath, { ...kept, status: "^offline" }, {
          lighthouse: false,
          ...offlineStateHooks(api),
        }),
      )
    }
    if (dark) {
      states.push(
        state("default", `${slug}-dark`, routePath, defaultState.expect, {
          lighthouse: false,
          colorScheme: "dark",
          breakpoints: DARK_BREAKPOINTS,
          shotSuffix: "--dark",
        }),
      )
    }
    return { screenId, path: routePath, states }
  }

  /** A second view of a route (another account or query), with its own states. */
  const extra = (screenId, routePath, sessionOf, states) => ({
    screenId,
    path: routePath,
    session: sessionOf,
    authed: sessionOf !== null,
    breakpoints: TUTORING_BREAKPOINTS,
    hideBottomChrome: true,
    states,
  })

  const withSession = (entry, sessionOf) => ({
    ...entry,
    session: sessionOf,
    authed: sessionOf !== null,
    breakpoints: TUTORING_BREAKPOINTS,
    hideBottomChrome: true,
  })

  const directoryError = { alert: "couldn.t load the tutors", anyH1: exactly("Tutors") }
  const directoryLoading = { loading: true, anyH1: exactly("Tutors") }
  const noMatch = { h1: exactly("Tutors"), text: "No tutors match these filters yet" }
  const profileError = { alert: "couldn.t load this tutor", anyH1: "Tutor profile" }
  const profileLoading = { loading: true, anyH1: "Tutor profile" }
  const sessionError = (what) => ({ alert: `couldn.t load ${what}`, anyH1: "Session" })

  const entries = []

  // ── G-16 · Tutor directory (public) ─────────────────────────────────────────
  const g16 = { screenId: "G-16", path: "/tutors", slug: "tutors-directory" }
  entries.push(
    withSession(
      around(
        g16,
        state("default", g16.slug, g16.path, {
          h1: exactly("Tutors"),
          text: "Find a tutor for IGCSE Maths, Additional Maths and Physics[\\s\\S]*Amira K\\.",
        }),
        "/api/public/tutors",
        { errorWant: directoryError, loadingWant: directoryLoading },
      ),
      null,
    ),
    extra("G-16", "/tutors?area=alexandria", null, [
      state("empty", "tutors-directory-empty", "/tutors?area=alexandria", noMatch, { lighthouse: false }),
    ]),
  )

  // ── G-17 · Tutor public card ────────────────────────────────────────────────
  const g17 = { screenId: "G-17", path: `/tutors/${amiraId}`, slug: "tutors-public-card" }
  entries.push(
    withSession(
      around(
        g17,
        state("default", g17.slug, g17.path, { h1: AMIRA, text: "Sign in to book" }),
        `/api/public/tutors/${amiraId}`,
        {
          errorWant: { alert: "couldn.t load this tutor", anyH1: "Tutor profile" },
          loadingWant: { loading: true, anyH1: "Tutor profile" },
        },
      ),
      null,
    ),
    extra("G-17", `/tutors/${draftTutorId}`, null, [
      state("unlisted", "tutors-public-card-unlisted", `/tutors/${draftTutorId}`, {
        anyH1: "Tutor profile",
        text: "This tutor isn't listed",
      }, { lighthouse: false }),
    ]),
  )

  // ── S-33 · Find a tutor ─────────────────────────────────────────────────────
  const s33 = { screenId: "S-33", path: "/student/tutors", slug: "student-tutors" }
  entries.push(
    withSession(
      around(
        s33,
        state("default", s33.slug, s33.path, {
          h1: exactly("Tutors"),
          // At 320 px the filters sit behind a "Filters" button, so the card and the ranking note are what is always there.
          text: "(?=[\\s\\S]*Amira K\\.)(?=[\\s\\S]*How tutors are ordered)",
        }),
        "/api/tutors",
        { errorWant: directoryError, loadingWant: directoryLoading },
      ),
      studentSession,
    ),
    extra("S-33", "/student/tutors?area=alexandria", studentSession, [
      state("empty", "student-tutors-empty", "/student/tutors?area=alexandria", noMatch, { lighthouse: false }),
    ]),
  )

  // ── S-34 · Tutor profile ────────────────────────────────────────────────────
  const s34 = { screenId: "S-34", path: `/student/tutors/${amiraId}`, slug: "student-tutor-profile" }
  entries.push(
    withSession(
      around(
        s34,
        state("default", s34.slug, s34.path, { h1: AMIRA, text: "Book a session[\\s\\S]*Results with this tutor" }),
        `/api/tutors/${amiraId}`,
        { errorWant: profileError, loadingWant: profileLoading },
      ),
      studentSession,
    ),
    extra("S-34", s34.path, studentSession, [
      state(
        "results-table",
        "student-tutor-profile-table",
        s34.path,
        { h1: AMIRA, text: "Grades during their time with this tutor" },
        {
          lighthouse: false,
          // Both figures offer "Show as table"; open both so the real tables are on screen.
          drive: async (page) => {
            // The toggles keep their label and flip `aria-pressed`, so press each one that is still off.
            const pressOne = () =>
              page.evaluate(() => {
                const off = Array.from(document.querySelectorAll('button[aria-pressed="false"]')).find((b) =>
                  /^show as table$/i.test(b.textContent ?? ""),
                )
                off?.click()
                return off !== undefined
              })
            while (await pressOne()) await new Promise((resolve) => setTimeout(resolve, 150))
            await page.waitForSelector("table")
          },
        },
      ),
    ]),
    extra("S-34", `/student/tutors/${omarId}`, studentSession, [
      state("insufficient", "student-tutor-profile-insufficient", `/student/tutors/${omarId}`, {
        h1: exactly("Omar H."),
        text: "Results are hidden for now",
      }, { lighthouse: false }),
    ]),
    extra("S-34", `/student/tutors/${draftTutorId}`, studentSession, [
      state("not-listed", "student-tutor-profile-not-listed", `/student/tutors/${draftTutorId}`, {
        anyH1: "Tutor profile",
        text: "This tutor isn't taking bookings right now",
      }, { lighthouse: false }),
    ]),
  )

  // ── S-35 · Book a session ───────────────────────────────────────────────────
  const s35 = { screenId: "S-35", path: `/student/tutors/${amiraId}/book`, slug: "student-tutor-book" }
  entries.push(
    withSession(
      around(
        s35,
        state("default", s35.slug, s35.path, {
          h1: exactly("Book a session with Amira K."),
          text: "How you will meet[\\s\\S]*Time",
        }),
        `/api/tutors/${amiraId}`,
        {
          errorWant: { alert: "couldn.t load this tutor", anyH1: "Book a session" },
          loadingWant: { loading: true, anyH1: "Book a session" },
        },
      ),
      studentSession,
    ),
    // C-24 opens first for a student who has not acknowledged it.
    extra("S-35", s35.path, newStudentSession, [
      state("safety-notice", "student-tutor-book-safety-notice", s35.path, {
        h1: exactly("Book a session with Amira K."),
        text: "Before your first session",
      }, { lighthouse: false }),
    ]),
  )

  // ── S-36 · My sessions ──────────────────────────────────────────────────────
  const s36 = { screenId: "S-36", path: "/student/sessions", slug: "student-sessions" }
  entries.push(
    withSession(
      around(
        s36,
        state("default", s36.slug, s36.path, { h1: exactly("My sessions"), text: "Waiting for reply" }),
        "/api/student/bookings",
        {
          errorWant: { alert: "couldn.t load your sessions", anyH1: exactly("My sessions") },
          loadingWant: { loading: true, anyH1: exactly("My sessions") },
        },
      ),
      studentSession,
    ),
    extra("S-36", "/student/sessions?when=past", studentSession, [
      state("past", "student-sessions-past", "/student/sessions?when=past", {
        h1: exactly("My sessions"),
        text: "Declined",
      }, { lighthouse: false }),
    ]),
    extra("S-36", s36.path, newStudentSession, [
      state("empty", "student-sessions-empty", s36.path, {
        h1: exactly("My sessions"),
        text: "No sessions booked",
      }, { lighthouse: false }),
    ]),
  )

  // ── S-37 · Session detail ───────────────────────────────────────────────────
  const s37 = { screenId: "S-37", path: `/student/sessions/${bookings.accepted}`, slug: "student-session-detail" }
  const sessionExtra = (name, bookingId, text) =>
    extra("S-37", `/student/sessions/${bookingId}`, studentSession, [
      state(name, `student-session-detail-${name}`, `/student/sessions/${bookingId}`, {
        h1: sessionTitle,
        text,
      }, { lighthouse: false }),
    ])
  entries.push(
    withSession(
      around(
        s37,
        state("default", s37.slug, s37.path, { h1: sessionTitle, text: "Cancel session[\\s\\S]*Session notes" }),
        `/api/student/bookings/${bookings.accepted}`,
        {
          errorWant: sessionError("this session"),
          loadingWant: { loading: true, anyH1: "Session" },
        },
      ),
      studentSession,
    ),
    sessionExtra("completed", bookings.completed, "Your review"),
    sessionExtra("cancelled-late", bookings.cancelledByTutorLate, "less than 24 hours before the start"),
    sessionExtra("awaiting-outcome", bookings.awaitingOutcome, "hasn.t recorded whether it took place"),
    sessionExtra("expired", bookings.expired, "didn.t reply before the start time"),
  )

  // ── S-38 · Tutors & your data ───────────────────────────────────────────────
  const s38 = { screenId: "S-38", path: "/student/tutor-access", slug: "student-tutor-access" }
  entries.push(
    withSession(
      around(
        s38,
        state("default", s38.slug, s38.path, { h1: exactly("Tutors & your data"), text: "Stop sharing[\\s\\S]*Who looked" }),
        "/api/student/tutor-grants",
        {
          // The grants list fails on its own; the rest of the page still renders.
          errorWant: { h1: exactly("Tutors & your data"), text: "couldn.t load who you share with" },
          loadingWant: { loading: true, h1: exactly("Tutors & your data") },
          // The grants list fails inline, in a compact panel that has no offline variant.
          offline: false,
        },
      ),
      studentSession,
    ),
    extra("S-38", s38.path, studentSession, [
      state(
        "stop-sharing-sheet",
        "student-tutor-access-stop-sheet",
        s38.path,
        { h1: exactly("Tutors & your data"), text: "Stop sharing" },
        {
          lighthouse: false,
          // Opens the confirm sheet and stops there: nothing is confirmed, so the grant survives.
          drive: async (page) => {
            await clickButton(page, "^stop sharing$")
            await page.waitForSelector('[role="dialog"]')
          },
        },
      ),
    ]),
    extra("S-38", s38.path, newStudentSession, [
      state("empty", "student-tutor-access-empty", s38.path, {
        h1: exactly("Tutors & your data"),
        text: "You aren.t sharing your progress with any tutor",
      }, { lighthouse: false }),
    ]),
  )

  // ── T-15 · Tutoring home ────────────────────────────────────────────────────
  const t15 = { screenId: "T-15", path: "/teacher/tutoring", slug: "teacher-tutoring-home" }
  entries.push(
    withSession(
      around(
        t15,
        state("default", t15.slug, t15.path, { h1: exactly("Tutoring"), text: "Your profile is listed[\\s\\S]*Requests waiting for a reply" }),
        "/api/tutor/profile",
        { errorWant: { alert: "Couldn.t load your tutoring page", anyH1: exactly("Tutoring") }, loadingWant: { loading: true, anyH1: exactly("Tutoring") } },
      ),
      tutorSession,
    ),
    extra("T-15", t15.path, teacherSession, [
      state("no-profile", "teacher-tutoring-home-no-profile", t15.path, {
        h1: exactly("Tutoring"),
        text: "Set up your tutor profile",
      }, { lighthouse: false }),
    ]),
    extra("T-15", t15.path, draftTutorSession, [
      state("draft", "teacher-tutoring-home-draft", t15.path, {
        h1: exactly("Tutoring"),
        text: "Your profile is a draft",
      }, { lighthouse: false }),
    ]),
  )

  // ── T-16 · Tutor profile and onboarding ─────────────────────────────────────
  const t16 = { screenId: "T-16", path: "/teacher/tutoring/profile", slug: "teacher-tutoring-profile" }
  entries.push(
    withSession(
      around(
        t16,
        state("default", t16.slug, t16.path, { h1: exactly("Tutor profile"), text: "Your profile is listed[\\s\\S]*Public card" }),
        "/api/tutor/profile",
        { errorWant: { alert: "Couldn.t load your profile", anyH1: "Tutor profile" }, loadingWant: { loading: true, anyH1: "Tutor profile" } },
      ),
      tutorSession,
    ),
    extra("T-16", t16.path, draftTutorSession, [
      state("onboarding", "teacher-tutoring-profile-onboarding", t16.path, {
        h1: exactly("Tutor profile"),
        text: "Your profile is a draft[\\s\\S]*Public card",
      }, { lighthouse: false }),
    ]),
  )

  // ── T-17 · Weekly availability ──────────────────────────────────────────────
  const t17 = { screenId: "T-17", path: "/teacher/tutoring/availability", slug: "teacher-tutoring-availability" }
  entries.push(
    withSession(
      around(
        t17,
        state("default", t17.slug, t17.path, { h1: exactly("Weekly availability"), text: "Cairo time; daylight saving is handled for you" }),
        "/api/tutor/profile",
        { errorWant: { alert: "Couldn.t load your weekly times", anyH1: "Weekly availability" }, loadingWant: { loading: true, anyH1: "Weekly availability" } },
      ),
      tutorSession,
    ),
  )

  // ── T-18 · Session detail (tutor) ───────────────────────────────────────────
  const t18 = { screenId: "T-18", path: `/teacher/tutoring/sessions/${bookings.accepted}`, slug: "teacher-tutoring-session" }
  const tutorTitle = exactly(`Session with ${T.student.displayName}`)
  const tutorSessionExtra = (name, bookingId, text) =>
    extra("T-18", `/teacher/tutoring/sessions/${bookingId}`, tutorSession, [
      state(name, `teacher-tutoring-session-${name}`, `/teacher/tutoring/sessions/${bookingId}`, {
        h1: tutorTitle,
        text,
      }, { lighthouse: false }),
    ])
  entries.push(
    withSession(
      around(
        t18,
        state("default", t18.slug, t18.path, { h1: tutorTitle, text: "Cancel session[\\s\\S]*Session notes" }),
        `/api/tutor/bookings/${bookings.accepted}`,
        { errorWant: { alert: "Couldn.t load this session", anyH1: "Session" }, loadingWant: { loading: true, anyH1: "Session" } },
      ),
      tutorSession,
    ),
    tutorSessionExtra("requested", bookings.requested, "Reply to this request"),
    tutorSessionExtra("completed", bookings.completed, "You recorded this session as completed"),
  )

  // ── T-19 · My students ──────────────────────────────────────────────────────
  const t19 = { screenId: "T-19", path: "/teacher/tutoring/students", slug: "teacher-tutoring-students" }
  entries.push(
    withSession(
      around(
        t19,
        state("default", t19.slug, t19.path, { h1: exactly("My students"), text: "Sharing since" }),
        "/api/tutor/students",
        { errorWant: { alert: "couldn.t load your students", anyH1: exactly("My students") }, loadingWant: { loading: true, anyH1: exactly("My students") } },
      ),
      tutorSession,
    ),
    extra("T-19", t19.path, sparseTutorSession, [
      state("empty", "teacher-tutoring-students-empty", t19.path, {
        h1: exactly("My students"),
        text: "No students are sharing their progress with you yet",
      }, { lighthouse: false }),
    ]),
  )

  // ── T-20 · Student detail (tutor view) ──────────────────────────────────────
  const t20 = { screenId: "T-20", path: `/teacher/tutoring/students/${grantedStudentId}`, slug: "teacher-tutoring-student" }
  entries.push(
    withSession(
      around(
        t20,
        state("default", t20.slug, t20.path, { h1: exactly(kidName), text: "shared this with you on" }),
        `/api/tutor/students/${grantedStudentId}`,
        { errorWant: { alert: "couldn.t load this student", anyH1: "Student progress" }, loadingWant: { loading: true, anyH1: "Student progress" } },
      ),
      tutorSession,
    ),
    // 403 access_ended: one message for every reason (SC-11). The C-11 state is a status, not an alert.
    extra("T-20", t20.path, sparseTutorSession, [
      state("access-ended", "teacher-tutoring-student-ended", t20.path, {
        anyH1: "Student progress",
        text: "no longer shared with you",
      }, { lighthouse: false }),
    ]),
  )

  // ── T-21 · Profile preview and reviews ──────────────────────────────────────
  const t21 = { screenId: "T-21", path: "/teacher/tutoring/preview", slug: "teacher-tutoring-preview" }
  entries.push(
    withSession(
      around(
        t21,
        state("default", t21.slug, t21.path, { h1: exactly("Profile preview and reviews"), text: "Your profile[\\s\\S]*Reviews" }),
        "/api/tutor/profile/preview",
        { errorWant: { alert: "Couldn.t load your preview", anyH1: exactly("Profile preview and reviews") }, loadingWant: { loading: true, anyH1: exactly("Profile preview and reviews") } },
      ),
      tutorSession,
    ),
  )

  // ── P-05 · Child's tutoring ─────────────────────────────────────────────────
  const kid = child.userId
  const p05 = { screenId: "P-05", path: `/parent/children/${kid}/tutoring`, slug: "parent-child-tutoring" }
  entries.push(
    withSession(
      around(
        p05,
        state("default", p05.slug, p05.path, { h1: exactly(`${kidName}'s tutoring`), text: `Who ${escapeRe(kidName)} shares progress with` }),
        `/api/parent/children/${kid}/bookings`,
        { errorWant: { alert: "couldn.t load .* sessions", anyH1: "tutoring" }, loadingWant: { loading: true, anyH1: "tutoring" } },
      ),
      parentSession,
    ),
  )

  // ── P-06 · Session detail (parent) ──────────────────────────────────────────
  const p06 = { screenId: "P-06", path: `/parent/children/${kid}/sessions/${bookings.child.parentAccepted}`, slug: "parent-child-session" }
  entries.push(
    withSession(
      around(
        p06,
        state("default", p06.slug, p06.path, { h1: sessionTitle, text: "Report this session" }),
        `/api/parent/children/${kid}/bookings/${bookings.child.parentAccepted}`,
        { errorWant: sessionError("this session"), loadingWant: { loading: true, anyH1: "Session" } },
      ),
      parentSession,
    ),
  )

  // ── P-07 · Find a tutor (parent) ────────────────────────────────────────────
  const p07 = { screenId: "P-07", path: "/parent/tutors", slug: "parent-tutors" }
  entries.push(
    withSession(
      around(
        p07,
        state("default", p07.slug, p07.path, { h1: exactly("Tutors"), text: "Find a tutor for IGCSE Maths, Additional Maths and Physics" }),
        "/api/tutors",
        { errorWant: directoryError, loadingWant: directoryLoading },
      ),
      parentSession,
    ),
  )

  // ── P-08 · Who {child} shares progress with ─────────────────────────────────
  const p08 = { screenId: "P-08", path: `/parent/children/${kid}/tutor-access`, slug: "parent-child-tutor-access" }
  const p08Heading = exactly(`Who ${kidName} shares progress with`)
  entries.push(
    withSession(
      around(
        p08,
        state("default", p08.slug, p08.path, { h1: p08Heading, text: "Who looked" }),
        `/api/parent/children/${kid}/tutor-grants`,
        {
          errorWant: { h1: p08Heading, text: "couldn.t load who .* shares with" },
          loadingWant: { loading: true, h1: p08Heading },
          offline: false,
        },
      ),
      parentSession,
    ),
  )

  // ── X-04 · Tutor approval queue ─────────────────────────────────────────────
  const x04 = { screenId: "X-04", path: "/platform/tutors", slug: "platform-tutors" }
  entries.push(
    withSession(
      around(
        x04,
        state("default", x04.slug, x04.path, { h1: exactly("Tutors"), text: "Email delivery: mock[\\s\\S]*Waiting for review" }),
        "/api/admin/tutors",
        { errorWant: { alert: "couldn.t load the tutors", anyH1: exactly("Tutors") }, loadingWant: { loading: true, anyH1: exactly("Tutors") } },
      ),
      adminSession,
    ),
    extra("X-04", "/platform/tutors?state=listed", adminSession, [
      state("listed", "platform-tutors-listed", "/platform/tutors?state=listed", {
        h1: exactly("Tutors"),
        text: "Amira K\\.[\\s\\S]*Omar H\\.",
      }, { lighthouse: false }),
    ]),
  )

  // ── X-05 · Tutor application ────────────────────────────────────────────────
  const x05 = { screenId: "X-05", path: `/platform/tutors/${amiraId}`, slug: "platform-tutor" }
  entries.push(
    withSession(
      around(
        x05,
        state("default", x05.slug, x05.path, { h1: AMIRA, text: "Account email[\\s\\S]*History" }),
        `/api/admin/tutors/${amiraId}`,
        { errorWant: { alert: "couldn.t load this tutor", anyH1: "Tutor application" }, loadingWant: { loading: true, anyH1: "Tutor application" } },
      ),
      adminSession,
    ),
  )

  // ── X-06 · Moderation queue ─────────────────────────────────────────────────
  const x06 = { screenId: "X-06", path: "/platform/moderation", slug: "platform-moderation" }
  entries.push(
    withSession(
      around(
        x06,
        state("default", x06.slug, x06.path, { h1: exactly("Moderation"), text: "Review text[\\s\\S]*Approve" }),
        "/api/admin/tutoring/moderation",
        { errorWant: { alert: "couldn.t load the queue", anyH1: exactly("Moderation") }, loadingWant: { loading: true, anyH1: exactly("Moderation") } },
      ),
      adminSession,
    ),
  )

  // ── X-07 · Reports ──────────────────────────────────────────────────────────
  const x07 = { screenId: "X-07", path: "/platform/reports", slug: "platform-reports" }
  entries.push(
    withSession(
      around(
        x07,
        state("default", x07.slug, x07.path, { h1: exactly("Reports"), text: "Safety concern" }),
        "/api/admin/tutoring/reports",
        { errorWant: { alert: "couldn.t load the reports", anyH1: exactly("Reports") }, loadingWant: { loading: true, anyH1: exactly("Reports") } },
      ),
      adminSession,
    ),
  )

  // X-07 detail is not on the SPEC gate list but is a screen of its own; it is audited by axe and screenshots.
  const x07d = { screenId: "X-07-detail", path: `/platform/reports/${reportId}`, slug: "platform-report" }
  entries.push(
    withSession(
      around(
        x07d,
        state("default", x07d.slug, x07d.path, { h1: exactly("Booking report"), text: "What was reported" }, { lighthouse: false }),
        `/api/admin/tutoring/reports/${reportId}`,
        { errorWant: { alert: "couldn.t load this report", anyH1: "Report" }, loadingWant: { loading: true, anyH1: "Report" } },
      ),
      adminSession,
    ),
  )

  return entries
}

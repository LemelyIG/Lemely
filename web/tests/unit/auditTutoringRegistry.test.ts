import { readFileSync } from "node:fs"
import { join } from "node:path"
import { randomUUID } from "node:crypto"
import { afterEach, describe, expect, it } from "vitest"
// @ts-expect-error -- a plain ESM script with no type declarations; the audit runs it under Node.
import { TUTORING_BREAKPOINTS, buildTutoringRegistry, pathnameOf, waitForExpectation } from "../../scripts/audit_tutoring_registry.mjs"

/*
 * T33 · the audit registry for the tutoring marketplace.
 *
 * SPEC §d, "Accessibility and performance gate routes", lists the routes that need zero
 * serious/critical axe violations, Lighthouse accessibility >= 95 and no horizontal scroll at
 * 320 px. `web/scripts/audit_tutoring_registry.mjs` is where they are registered, and this file
 * is what stops that list and the SPEC drifting apart: the expected side is PARSED out of the
 * SPEC text, never copied, and the count is asserted so an empty parse cannot pass.
 *
 * It also pins the property P28 asks for: a `ready` predicate that cannot be satisfied by a
 * login redirect or an error page. That is exercised against a minimal stand-in for the page
 * (`waitForExpectation` runs the real predicate function over a fake `window` and `document`).
 */

const ROOT = join(import.meta.dirname, "..", "..", "..")
const SPEC = readFileSync(join(ROOT, "docs", "tutoring", "SPEC.md"), "utf8")
const AUDIT = readFileSync(join(ROOT, "web", "scripts", "audit.mjs"), "utf8")
const GATES = readFileSync(join(ROOT, "scripts", "check_ui_gates.py"), "utf8")

// ── The SPEC side, parsed ──────────────────────────────────────────────────

const GATE_SECTION = SPEC.slice(
  SPEC.indexOf("### Accessibility and performance gate routes"),
  SPEC.indexOf("## e. Core modules and test strategy"),
)
const LIST_START = GATE_SECTION.indexOf("a11y ≥ 95 on:")
const LIST_END = GATE_SECTION.indexOf("**Lighthouse runs on each route's default state only**")
const SPEC_PATHS: string[] = [...GATE_SECTION.slice(LIST_START, LIST_END).matchAll(/`(\/[^`]+)`/g)].map((m) => m[1] as string)

/** `/parent/children/:id/sessions/:id` stays as written; ids in the registry become `:id`. */
const UUID = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/g
const canonical = (path: string) => pathnameOf(path).replace(UUID, ":id")

// ── A seed with the shape of scripts/seed_e2e.py's contract ────────────────

const account = (label: string, role?: string) => ({
  userId: randomUUID(),
  email: `${label}@e2e.lemely.local`,
  password: "x",
  displayName: `Seed ${label}`,
  accessToken: `token-${label}`,
  ...(role ? { role } : {}),
})
const tutor = (label: string, publicName: string) => ({ ...account(label), tutorProfileId: randomUUID(), publicName })

function fakeSeed() {
  const declining = account("declining")
  return {
    teacher: account("teacher"),
    parent: account("parent"),
    students: { declining },
    tutoring: {
      subjectCode: "0625",
      subjectName: "Physics",
      platformAdmin: account("platform-admin"),
      tutors: {
        sufficient: tutor("tutor-sufficient", "Amira K."),
        insufficient: tutor("tutor-insufficient", "Omar H."),
        draft: tutor("tutor-draft", "Layla S."),
      },
      student: account("tutoring-student"),
      discover: { student: account("discover"), rival: account("rival") },
      bookings: {
        requested: randomUUID(),
        accepted: randomUUID(),
        awaitingOutcome: randomUUID(),
        completed: randomUUID(),
        cancelledByTutorLate: randomUUID(),
        expired: randomUUID(),
        child: { parentAccepted: randomUUID() },
      },
      grants: { live: { studentUserId: declining.userId } },
      reports: { openSafety: { reportId: randomUUID() } },
    },
  }
}

interface State {
  state: string
  slug: string
  expect: { h1?: string; anyH1?: string; text?: string; alert?: string; status?: string; loading?: boolean }
  ready: unknown
  lighthouse?: boolean
  colorScheme?: string
  shotSuffix?: string
  breakpoints?: Array<{ width: number; height: number }>
}
interface Entry {
  screenId: string
  path: string
  session: { role: string; userId: string } | null
  authed: boolean
  breakpoints: Array<{ width: number; height: number }>
  states: State[]
}

const noHooks = () => ({ setup: async () => {}, teardown: async () => {} })
const registry = (): Entry[] =>
  buildTutoringRegistry(fakeSeed(), { loadingStateHooks: noHooks, errorStateHooks: noHooks }) as Entry[]

// ── The route list ──────────────────────────────────────────────────────────

describe("the tutoring registry covers the SPEC gate routes", () => {
  it("parses 23 routes out of the SPEC list (non-vacuity)", () => {
    expect(SPEC_PATHS).toHaveLength(23)
    expect(new Set(SPEC_PATHS).size).toBe(23)
    expect(SPEC_PATHS).toContain("/tutors")
    expect(SPEC_PATHS).toContain("/platform/reports")
  })

  const entries = registry()
  const registered = new Set(entries.map((e) => canonical(e.path)))

  it("registers every route on the SPEC list", () => {
    const missing = SPEC_PATHS.filter((p) => !registered.has(p))
    expect(missing, `routes on the SPEC list with no registry entry: ${missing.join(", ")}`).toEqual([])
  })

  it("registers nothing else, apart from the one detail screen it audits for axe and screenshots", () => {
    const extras = [...registered].filter((p) => !SPEC_PATHS.includes(p))
    expect(extras).toEqual(["/platform/reports/:id"])
  })

  it("gives every SPEC route a default state that Lighthouse scores, exactly once", () => {
    for (const path of SPEC_PATHS) {
      const scored = entries
        .filter((e) => canonical(e.path) === path)
        .flatMap((e) => e.states)
        .filter((s) => s.state === "default" && s.colorScheme === undefined && s.lighthouse !== false)
      expect(scored, `Lighthouse states for ${path}`).toHaveLength(1)
    }
  })

  it("never asks Lighthouse to score a state other than the default (SPEC D3.17)", () => {
    for (const entry of entries) {
      for (const st of entry.states) {
        if (st.lighthouse === false) continue
        expect(st.state, `${entry.path} [${st.state}]`).toBe("default")
        expect(st.colorScheme).toBeUndefined()
      }
    }
  })
})

describe("sessions", () => {
  const entries = registry()

  it("audits the platform admin routes as a platform_admin and nothing else", () => {
    const platform = entries.filter((e) => e.path.startsWith("/platform"))
    expect(platform.length).toBeGreaterThanOrEqual(5)
    for (const entry of platform) expect(entry.session?.role, entry.path).toBe("platform_admin")
  })

  it("audits the two public pages signed out", () => {
    const publicEntries = entries.filter((e) => e.path.startsWith("/tutors"))
    expect(publicEntries.length).toBeGreaterThanOrEqual(2)
    for (const entry of publicEntries) {
      expect(entry.session, entry.path).toBeNull()
      expect(entry.authed).toBe(false)
    }
  })

  it("audits each portal's routes under that portal's role", () => {
    const roleOf = (prefix: string) => new Set(entries.filter((e) => e.path.startsWith(prefix)).map((e) => e.session?.role))
    expect(roleOf("/student")).toEqual(new Set(["student"]))
    expect(roleOf("/teacher")).toEqual(new Set(["teacher"]))
    expect(roleOf("/parent")).toEqual(new Set(["parent"]))
  })
})

describe("states", () => {
  const entries = registry()
  const states = entries.flatMap((e) => e.states.map((s) => ({ entry: e, st: s })))

  it("every screen has default, loading, error and dark states", () => {
    const byScreen = new Map<string, Set<string>>()
    for (const { entry, st } of states) {
      const key = entry.screenId
      const label = st.colorScheme === "dark" ? "dark" : st.state
      byScreen.set(key, (byScreen.get(key) ?? new Set()).add(label))
    }
    // The extra entries of a screen (another account) share its id, so check the union.
    for (const [screenId, labels] of byScreen) {
      if (screenId === "X-07-detail" || screenId.length === 0) continue
      for (const needed of ["default", "loading", "error", "dark"]) {
        expect(labels.has(needed), `${screenId} has no ${needed} state`).toBe(true)
      }
    }
  })

  it("registers an offline state wherever the screen has an offline panel, and it waits for a status, not an alert", () => {
    const offline = states.filter(({ st }) => st.state === "offline")
    expect(offline.length).toBeGreaterThanOrEqual(20)
    for (const { entry, st } of offline) {
      expect(st.expect.status, `${entry.screenId} offline`).toBeTruthy()
      expect(st.expect.alert, `${entry.screenId} offline`).toBeFalsy()
    }
    // The two inline grant lists have no offline variant, and say so by having no state.
    const screens = new Set(offline.map(({ entry }) => entry.screenId))
    expect(screens.has("S-38")).toBe(false)
    expect(screens.has("P-08")).toBe(false)
    expect(screens.has("G-16")).toBe(true)
  })

  it("registers the SPEC's screen-specific states", () => {
    const has = (screenId: string, state: string) =>
      states.some(({ entry, st }) => entry.screenId === screenId && st.state === state)
    expect(has("G-16", "empty")).toBe(true)
    expect(has("G-17", "unlisted")).toBe(true)
    expect(has("S-33", "empty")).toBe(true)
    expect(has("S-34", "insufficient")).toBe(true)
    expect(has("S-34", "not-listed")).toBe(true)
    expect(has("S-35", "safety-notice")).toBe(true)
    expect(has("S-36", "empty")).toBe(true)
    expect(has("S-37", "cancelled-late")).toBe(true)
    expect(has("S-38", "empty")).toBe(true)
    expect(has("T-15", "no-profile")).toBe(true)
    expect(has("T-19", "empty")).toBe(true)
    expect(has("T-20", "access-ended")).toBe(true)
  })

  it("has unique slugs, so no axe or Lighthouse row overwrites another", () => {
    const slugs = states.map(({ st }) => st.slug)
    expect(new Set(slugs).size).toBe(slugs.length)
  })

  it("has unique screenshot names within a screen", () => {
    const names = states.flatMap(({ entry, st }) =>
      (st.breakpoints ?? entry.breakpoints).map((bp) => `${entry.screenId}/${st.state}--${bp.width}${st.shotSuffix ?? ""}`),
    )
    expect(new Set(names).size).toBe(names.length)
    expect(names.some((n) => n.endsWith("--320"))).toBe(true)
    expect(names.some((n) => n.endsWith("--1280--dark"))).toBe(true)
  })

  it("captures at 320, 768 and 1280", () => {
    expect(TUTORING_BREAKPOINTS.map((bp: { width: number }) => bp.width)).toEqual([320, 768, 1280])
    for (const entry of entries) expect(entry.breakpoints).toEqual(TUTORING_BREAKPOINTS)
  })

  it("gives every state a ready predicate that names content specific to it", () => {
    expect(states.length).toBeGreaterThan(100)
    for (const { entry, st } of states) {
      const label = `${entry.screenId} [${st.state}] ${st.slug}`
      expect(typeof st.ready, label).toBe("function")
      const want = st.expect
      expect(want.h1 || want.anyH1 || want.text || want.alert, `${label} expects nothing specific`).toBeTruthy()
    }
  })

  it("makes every ready wait on its own route's pathname, so a login redirect is never ready", async () => {
    let checked = 0
    for (const { entry, st } of states) {
      const waitedOn: unknown[] = []
      const page = {
        waitForFunction: async (_fn: unknown, _options: unknown, ...args: unknown[]) => {
          waitedOn.push(args[0])
          return { asElement: () => null }
        },
        waitForSelector: async () => {},
        evaluate: async () => false,
      }
      await (st.ready as (page: unknown) => Promise<void>)(page).catch(() => {})
      expect(waitedOn[0], `${entry.screenId} [${st.state}] ${entry.path}`).toBe(pathnameOf(entry.path))
      checked += 1
    }
    expect(checked).toBe(states.length)
  })

  it("makes a loaded default state require its own heading and forbid a skeleton and an alert", () => {
    for (const { entry, st } of states) {
      if (st.state !== "default") continue
      expect(st.expect.loading, `${entry.screenId} ${st.slug}`).toBeFalsy()
      expect(st.expect.alert, `${entry.screenId} ${st.slug}`).toBeFalsy()
      expect(st.expect.h1, `${entry.screenId} ${st.slug} waits on no visible heading`).toBeTruthy()
    }
  })

  it("makes error states wait for an alert and loading states for a skeleton", () => {
    for (const { entry, st } of states) {
      if (st.state === "error" && entry.screenId !== "S-38" && entry.screenId !== "P-08") {
        expect(st.expect.alert, `${entry.screenId} error`).toBeTruthy()
      }
      if (st.state === "loading") expect(st.expect.loading, `${entry.screenId} loading`).toBe(true)
    }
  })
})

// ── `ready` cannot be satisfied by the wrong page (P28) ─────────────────────

interface FakeNode {
  textContent: string
  classList: { contains: (name: string) => boolean }
}

function node(text: string, classes: string[] = []): FakeNode {
  return { textContent: text, classList: { contains: (name) => classes.includes(name) } }
}

interface FakePage {
  pathname: string
  text: string
  h1s?: FakeNode[]
  alerts?: FakeNode[]
  loading?: boolean
}

const original = { window: (globalThis as Record<string, unknown>).window, document: (globalThis as Record<string, unknown>).document }
afterEach(() => {
  ;(globalThis as Record<string, unknown>).window = original.window
  ;(globalThis as Record<string, unknown>).document = original.document
})

/** Runs the predicate `waitForExpectation` hands to the browser, over a fake page. True when it is satisfied. */
async function satisfied(routePath: string, want: object, fake: FakePage): Promise<boolean> {
  const g = globalThis as Record<string, unknown>
  g.window = { location: { pathname: fake.pathname } }
  g.document = {
    body: { innerText: fake.text },
    querySelectorAll: (selector: string) => (selector === "h1" ? (fake.h1s ?? []) : selector === '[role="alert"]' ? (fake.alerts ?? []) : []),
    querySelector: () => (fake.loading ? {} : null),
  }
  const page = {
    waitForFunction: async (fn: (...args: unknown[]) => boolean, _opts: unknown, ...args: unknown[]) => {
      if (!fn(...args)) throw new Error("not ready")
    },
  }
  try {
    await waitForExpectation(page, routePath, want)
    return true
  } catch {
    return false
  }
}

describe("waitForExpectation (the predicate behind every ready)", () => {
  const route = "/student/tutors/abc"
  const want = { h1: "^Amira K\\.$", text: "Book a session" }
  const loaded: FakePage = { pathname: route, text: "Amira K. Book a session", h1s: [node("Amira K.")] }

  it("accepts the page it describes", async () => {
    expect(await satisfied(route, want, loaded)).toBe(true)
  })

  it("rejects a login redirect, even one that shows the same words", async () => {
    expect(await satisfied(route, want, { ...loaded, pathname: "/login" })).toBe(false)
  })

  it("rejects the login page", async () => {
    expect(
      await satisfied(route, want, { pathname: "/login", text: "Sign in to Lemely", h1s: [node("Sign in")] }),
    ).toBe(false)
  })

  it("rejects an error page on a state that is not the error state", async () => {
    expect(await satisfied(route, want, { ...loaded, alerts: [node("We couldn't load this tutor")] })).toBe(false)
  })

  it("rejects a skeleton on a state that is not the loading state", async () => {
    expect(await satisfied(route, want, { ...loaded, loading: true })).toBe(false)
  })

  it("rejects a page whose heading is only the screen-reader one", async () => {
    expect(await satisfied(route, want, { ...loaded, h1s: [node("Amira K.", ["sr-only"])] })).toBe(false)
  })

  it("rejects a page that is missing the state's text", async () => {
    expect(await satisfied(route, want, { ...loaded, text: "Amira K." })).toBe(false)
  })

  it("ignores the query string when comparing paths", async () => {
    expect(await satisfied("/tutors?area=alexandria", { h1: "Tutors" }, { pathname: "/tutors", text: "", h1s: [node("Tutors")] })).toBe(true)
  })

  it("lets the error state through only with its alert, and the loading state only with its skeleton", async () => {
    const errorWant = { alert: "couldn.t load this tutor", anyH1: "Tutor profile" }
    const errorPage: FakePage = { pathname: route, text: "", h1s: [node("Tutor profile", ["sr-only"])], alerts: [node("We couldn't load this tutor")] }
    expect(await satisfied(route, errorWant, errorPage)).toBe(true)
    expect(await satisfied(route, errorWant, { ...errorPage, alerts: [] })).toBe(false)
    const loadingWant = { loading: true, anyH1: "Tutor profile" }
    const loadingPage: FakePage = { pathname: route, text: "", h1s: [node("Tutor profile", ["sr-only"])], loading: true }
    expect(await satisfied(route, loadingWant, loadingPage)).toBe(true)
    expect(await satisfied(route, loadingWant, { ...loadingPage, loading: false })).toBe(false)
  })
})

// ── Wiring ──────────────────────────────────────────────────────────────────

describe("the audit runner uses the registry", () => {
  it("imports it and appends its entries to the registry", () => {
    expect(AUDIT).toMatch(/import \{ buildTutoringRegistry \} from "\.\/audit_tutoring_registry\.mjs"/)
    expect(AUDIT).toMatch(/buildTutoringRegistry\(seed, \{ loadingStateHooks, errorStateHooks \}\)/)
    expect(AUDIT).toMatch(/\]\.concat\(tutoringEntries\)/)
  })

  it("reads each state's own widths and screenshot suffix", () => {
    expect(AUDIT).toMatch(/st\.breakpoints \?\? route\.breakpoints \?\? BREAKPOINTS/)
    expect(AUDIT).toMatch(/shoot\(page, route\.screenId, st\.state, bp\.width, st\.shotSuffix, \{/)
    expect(AUDIT).toMatch(/hideBottomChrome: route\.hideBottomChrome === true/)
  })

  it("gates performance on the slugs the registry writes", () => {
    const registrySource = readFileSync(join(ROOT, "web", "scripts", "audit_tutoring_registry.mjs"), "utf8")
    const gated = /PERF_GATED_TUTORING_SLUGS = \(([^)]*)\)/.exec(GATES)?.[1] ?? ""
    const slugs = [...gated.matchAll(/"([^"]+)"/g)].map((m) => m[1] as string)
    expect(slugs).toHaveLength(2)
    for (const slug of slugs) expect(registrySource).toContain(`slug: "${slug}"`)
    // And those two are the public pages, so the SPEC's "/tutors and /tutors/:id" are what is gated.
    const published = registry()
      .filter((e) => e.path.startsWith("/tutors"))
      .flatMap((e) => e.states)
      .filter((s) => s.lighthouse !== false)
      .map((s) => s.slug)
    expect(published.sort()).toEqual([...slugs].sort())
  })
})

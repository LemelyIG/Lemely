import { describe, expect, it } from "vitest"
import fs from "node:fs"
import path from "node:path"
import type { RouteObject } from "react-router-dom"

import { appRoutes } from "@/routes"
import {
  DEFAULT_DESCRIPTION,
  DEFAULT_TITLE,
  SITE_NAME,
  formatTitle,
  isPageMeta,
  pageMetaFromMatches,
} from "@/lib/meta/documentMeta"

/*
 * P6.5 · the gate for per-route page metadata.
 *
 * The defect this closes is that **no screen in the product ever set a
 * `document.title`**, so all 48 routes were "Lemely" — in the tab, in the
 * bookmark, in the history entry, and, worst, in the announcement a screen
 * reader makes on every single-page navigation.
 *
 * The reason the fix is a route `handle` and not a hook in each screen is the
 * reason this file exists. A per-screen hook has nothing to check itself
 * against, so route 49 ships untitled and nothing says so — which is exactly
 * how `text-title` sat on a live `<h1>` emitting no CSS for a whole build, how
 * the compat layer outlived every screen that used it, and how two admin
 * portals ended up in none of the three gate lists (P4.10). Metadata in the
 * route table can be walked. So it is walked.
 */

/** Every route in the tree, flattened, with the path it was reached by. */
function flatten(routes: readonly RouteObject[], prefix = ""): { path: string; route: RouteObject }[] {
  const out: { path: string; route: RouteObject }[] = []
  for (const route of routes) {
    const segment = route.index ? "(index)" : (route.path ?? "")
    const full = [prefix, segment].filter(Boolean).join("/")
    out.push({ path: full || "/", route })
    if (route.children) out.push(...flatten(route.children, full))
  }
  return out
}

/**
 * A route a reader can actually land on: one with no children of its own.
 *
 * Layout routes are deliberately exempt from *requiring* a title, because the
 * reader never sees a layout alone — some child is always rendered inside it,
 * and `pageMetaFromMatches` takes the deepest. A layout MAY carry one as a
 * fallback for its children (`teacher/classes/:classId` does), and that is
 * checked below by the assertion that the chain always resolves.
 */
function leafRoutes(): { path: string; route: RouteObject }[] {
  return flatten(appRoutes).filter(({ route }) => !route.children?.length)
}

describe("every route names itself", () => {
  it("has a valid PageMeta handle on every leaf route", () => {
    const untitled = leafRoutes()
      .filter(({ route }) => !isPageMeta(route.handle))
      .map(({ path }) => path)

    expect(
      untitled,
      "These routes would render with the default document title, so their tab, their " +
        "bookmark and the screen-reader announcement on arrival would all say only " +
        '"Lemely". Add `handle: { title: "..." }` to each. See src/lib/meta/documentMeta.ts.',
    ).toEqual([])
  })

  it("covers enough routes that the walk is not vacuously passing", () => {
    // The guard against the failure mode this suite has hit twice: a matcher
    // that stops matching reports zero problems and reads as a clean sweep
    // (D6.4's `route-failures.json`, D6.2's `aimedAt`). If `flatten` ever stops
    // descending into portal children, the test above passes on an empty list.
    expect(leafRoutes().length).toBeGreaterThanOrEqual(45)
  })

  it("gives no two leaf routes the same title where one reader can hold both", () => {
    /*
     * Not a global uniqueness rule: a student's "Announcements" and a teacher's
     * "Announcements" are the same word for the same idea, and no account holds
     * both, so two identical tabs is impossible.
     *
     * A `school_admin` genuinely holds two portals at once (`/teacher` and
     * `/school`, per P4.7), which is the one case where a repeated title really
     * would put two different screens over different data in two tabs reading
     * the same thing. Hence the "School ..." prefixes in `portals/admin`.
     */
    const titlesIn = (prefix: string) =>
      leafRoutes()
        .filter(({ path, route }) => path.startsWith(prefix) && isPageMeta(route.handle))
        .map(({ route }) => (route.handle as { title: string }).title)
        // The portal 404s are the same screen in both, correctly.
        .filter((title) => title !== "Page not found")

    const overlap = titlesIn("teacher").filter((title) => titlesIn("school").includes(title))
    expect(overlap, "A school admin holds both portals and would see two identical tabs").toEqual(
      [],
    )
  })

  it("writes no em-dash into a title, which is UI copy like any other", () => {
    const offenders = leafRoutes()
      .filter(({ route }) => isPageMeta(route.handle))
      .map(({ path, route }) => ({ path, title: (route.handle as { title: string }).title }))
      .filter(({ title }) => title.includes("—") || title.includes("–"))
    expect(offenders).toEqual([])
  })
})

/*
 * Task 19 (spec §4.4) · the nine signup/verify/reset/join routes' metadata.
 *
 * These nine join `/`, `/landing`, `/data`, `/login` and `/login/parent` as
 * the only routes in the product a signed-out reader can reach, so — unlike
 * every authenticated screen this file's other tests only require a title
 * from — each of the nine must carry a real `description` too (P6.5, above).
 * And because `deps.py` wires `MockEmailProvider` unconditionally, the same
 * finding `routes.tsx` already records for `MockSmsProvider` on
 * `/login/parent`, not one of the nine may claim a mail or a text was sent.
 * The banned-claim assertion below is deliberately literal, matching
 * `marketing.test.ts`'s own approach to the identical kind of risk: the
 * failure mode is not a wrong word, it is a plausible sentence about a
 * delivery nothing in this codebase performs.
 */
describe("the nine signup/verify/reset/join routes carry honest metadata — Task 19", () => {
  const NEW_PATHS = [
    "/signup",
    "/signup/student",
    "/signup/teacher",
    "/verify-email",
    "/verify-email/:token",
    "/reset",
    "/reset/:token",
    "/join",
    "/join/:code",
  ]

  /** Each of the nine, resolved to its `PageMeta`. Throws rather than
   * returning `undefined` for a missing route, so a route that Task 19
   * failed to register fails every test below with a clear cause instead of
   * a downstream `Cannot read properties of undefined`. */
  const metaFor = (path: string): { title: string; description?: string } => {
    const route = appRoutes.find((r) => r.path === path)
    if (!route) throw new Error(`${path} is not mounted`)
    const handle = route.handle
    if (!isPageMeta(handle)) throw new Error(`${path} has no valid PageMeta handle`)
    return handle
  }

  it("mounts all nine as leaf routes with a valid PageMeta handle", () => {
    const found = leafRoutes()
      .filter(({ path }) => NEW_PATHS.includes(path))
      .map(({ path }) => path)
    expect(found.sort()).toEqual([...NEW_PATHS].sort())
    for (const path of NEW_PATHS) {
      expect(isPageMeta(appRoutes.find((r) => r.path === path)?.handle), path).toBe(true)
    }
  })

  it("gives every one of the nine a non-empty description", () => {
    for (const path of NEW_PATHS) {
      const { description } = metaFor(path)
      expect(typeof description, `${path} has no description`).toBe("string")
      expect((description ?? "").length, `${path}'s description is empty`).toBeGreaterThan(0)
    }
  })

  /*
   * The exact rule Task 19 states: no description may say a mail or a link
   * was sent. Matches "send"/"sent"/"resend" and their -ing/-s forms as whole
   * words, plus "delivered"/"emailed"/"texted", rather than a bare substring
   * match — narrow enough not to flag an unrelated word, wide enough to catch
   * the actual shapes a fabricated delivery claim would take.
   */
  it("claims no mail or text was sent, delivered, emailed, or texted", () => {
    const bannedClaim = /\b(re)?sen(d|t|ds|ding)\b|\bdelivered\b|\bemailed\b|\btexted\b/i
    for (const path of NEW_PATHS) {
      const { description } = metaFor(path)
      expect(description, `${path} claims a delivery: "${description}"`).not.toMatch(bannedClaim)
    }
  })

  it("writes no em-dash into any of the nine titles or descriptions", () => {
    for (const path of NEW_PATHS) {
      const { title, description } = metaFor(path)
      expect(title, `${path} title`).not.toMatch(/[—–]/)
      expect(description ?? "", `${path} description`).not.toMatch(/[—–]/)
    }
  })

  it("gives each of the nine a title distinct from the other eight", () => {
    const titles = NEW_PATHS.map((path) => metaFor(path).title)
    expect(new Set(titles).size).toBe(titles.length)
  })

  /*
   * The other direction, and the reason this describe block is not just five
   * assertions about nine strings: a description is exactly as much a claim
   * of "this route is signed-out-reachable" as its absence is a claim of
   * "this one is not", and only testing the nine additions would let a
   * tenth, accidental description slip onto an authenticated screen with
   * every test above still green. Pinned against the full leaf-route walk,
   * not a hand-picked list of "the other ones I remembered" — a route this
   * suite forgot to name is a route this assertion still sees.
   */
  it("gives a description to exactly the signed-out-reachable routes and no others", () => {
    const PUBLIC_WITH_DESCRIPTION = new Set([
      "/",
      "/landing",
      "/data",
      "/login",
      "/login/parent",
      ...NEW_PATHS,
      "*",
    ])
    const offenders: string[] = []
    for (const { path, route } of leafRoutes()) {
      const handle = route.handle
      const hasDescription = isPageMeta(handle) && Boolean(handle.description)
      const shouldHaveOne = PUBLIC_WITH_DESCRIPTION.has(path)
      if (hasDescription !== shouldHaveOne) offenders.push(`${path} (has one: ${hasDescription})`)
    }
    expect(offenders).toEqual([])
  })
})

describe("resolving a title from a match chain", () => {
  it("takes the deepest handle, so a child overrides its layout", () => {
    const meta = pageMetaFromMatches([
      { handle: { title: "Class" } },
      { handle: { title: "Class analytics" } },
    ])
    expect(meta?.title).toBe("Class analytics")
  })

  it("falls back to an ancestor when the leaf carries none", () => {
    const meta = pageMetaFromMatches([{ handle: { title: "Class" } }, { handle: undefined }])
    expect(meta?.title).toBe("Class")
  })

  it("returns null rather than guessing when nothing in the chain has one", () => {
    expect(pageMetaFromMatches([{ handle: undefined }, {}])).toBeNull()
  })

  it("rejects a handle whose title is not a non-empty string", () => {
    // The type guard is the boundary where react-router's `unknown` becomes a
    // PageMeta. An empty title is the interesting case: it is a string, it
    // passes a naive `typeof` check, and it produces the tab title " · Lemely".
    expect(isPageMeta({ title: "" })).toBe(false)
    expect(isPageMeta({ title: 404 })).toBe(false)
    expect(isPageMeta({})).toBe(false)
    expect(isPageMeta(null)).toBe(false)
    expect(isPageMeta("Dashboard")).toBe(false)
  })
})

describe("the tab string", () => {
  it("suffixes the product name with a middot, not an em-dash", () => {
    expect(formatTitle({ title: "Review queue" })).toBe(`Review queue · ${SITE_NAME}`)
  })

  it("does not suffix a title that already carries the product name", () => {
    // Otherwise the landing page reads "Lemely, marking for CAIE past papers ·
    // Lemely", which is the shape this rule exists to prevent.
    expect(formatTitle({ title: DEFAULT_TITLE })).toBe(DEFAULT_TITLE)
    expect(formatTitle({ title: SITE_NAME })).toBe(SITE_NAME)
  })

  it("falls back to the default when a route resolves no metadata at all", () => {
    expect(formatTitle(null)).toBe(DEFAULT_TITLE)
  })
})

describe("the defaults are the same in the HTML and in the module", () => {
  /*
   * `index.html` is what a scraper with no JavaScript reads and what shows
   * before React mounts; the module is what a client-side navigation restores.
   * Two copies of one string, which is precisely the shape D6.7 was about, so
   * they are pinned equal rather than trusted to stay so.
   */
  const html = fs.readFileSync(path.resolve(__dirname, "../../index.html"), "utf8")

  it("uses the same default title", () => {
    expect(html).toContain(`<title>${DEFAULT_TITLE}</title>`)
  })

  it("uses the same default description", () => {
    expect(html).toContain(DEFAULT_DESCRIPTION)
  })

  it("still injects the theme colour rather than hardcoding a hex", () => {
    // If someone replaces the placeholder with a literal, `vite/themeColor.ts`
    // throws at build time — but only if the build runs. This fails faster and
    // says why.
    expect(html).toContain("%LEMELY_THEME_COLOR%")
  })

  it("points the icon at the real brand mark and not the build-era favicon", () => {
    expect(html).toContain('href="/brand/mark-favicon.svg"')
    expect(html).not.toContain("/favicon.svg\"")
  })
})

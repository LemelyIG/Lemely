import { describe, expect, it } from "vitest"
import fs from "node:fs"
import path from "node:path"

import { appRoutes } from "@/routes"
import { marketingRoute } from "@/portals/marketing"
import { studentRoute } from "@/portals/student"
import * as marketingData from "@/portals/marketing/data"
import {
  landingClose,
  landingHero,
  heroExample,
  mcq,
  pricing,
  roleTabs,
} from "@/portals/marketing/data"

/*
 * P4.9 · the Persuade lane, pinned.
 *
 * Two classes of fact live here, and they are both the kind that rot in
 * silence — the kind this project has now been bitten by often enough to stop
 * arguing about whether they deserve a test.
 *
 * 1. REACHABILITY. The marketing page spent the whole build behind
 *    `RequireAuth allowedRoles={["student"]}` at `/student/landing`, where the
 *    only reader who could open it was a student who had already signed up.
 *    Nothing failed. Typecheck passed, lint passed, the route rendered
 *    perfectly for the one person who did not need it, and the *audit* found
 *    it only as a note in a comment. A guard placed around the wrong subtree
 *    is invisible to every gate this build runs except a test that says out
 *    loud which routes are public.
 *
 * 2. HONEST COPY. DESIGN-AUDIT C1/C2/C3 deleted the fabricated numbers from
 *    this page and left six fabricated sentences behind them, including the
 *    exact figure C1 had just removed, four sections up the same file. The
 *    banned-claim assertions below are deliberately literal: they name the
 *    words, because the failure mode is not a wrong number, it is a plausible
 *    sentence about a feature nobody built.
 */

/** Top-level route paths the product mounts, in order. */
const topLevelPaths = appRoutes.map((r) => r.path)

/**
 * Walk a route element tree looking for a component by display name.
 *
 * Guards are React elements, so this is the only honest way to ask "is this
 * route behind `RequireAuth`" without rendering it — and asking that question
 * is the entire point of this file. Matching by name rather than by type
 * identity means it keeps working when a guard is wrapped in a Suspense or a
 * frame, which is exactly how the original defect hid.
 */
function containsComponent(node: unknown, name: string): boolean {
  if (!node || typeof node !== "object") return false
  if (Array.isArray(node)) return node.some((n) => containsComponent(n, name))
  const el = node as { type?: unknown; props?: { children?: unknown } }
  const type = el.type as { name?: string; displayName?: string } | undefined
  if (type && (type.name === name || type.displayName === name)) return true
  return containsComponent(el.props?.children, name)
}

describe("the marketing lane is public — P4.9", () => {
  it("mounts /landing at the top level, outside every portal subtree", () => {
    expect(topLevelPaths).toContain("/landing")
  })

  /*
   * The assertion that would have caught the original defect, made against the
   * route table itself rather than against the source text.
   */
  it("puts no auth guard on the marketing route", () => {
    const route = appRoutes.find((r) => r.path === "/landing")
    expect(route).toBeDefined()
    expect(containsComponent(route!.element, "RequireAuth")).toBe(false)
  })

  /*
   * The inverse, so this file cannot pass by the guards having been removed
   * everywhere. Each portal must still be behind one.
   */
  it.each(["teacher", "student", "parent"])("keeps the %s portal guarded", (portal) => {
    const route = appRoutes.find((r) => r.path === portal)
    expect(route).toBeDefined()
    expect(containsComponent(route!.element, "RequireAuth")).toBe(true)
  })

  it("keeps /student/landing mounted so saved links and D1.1's condition survive", () => {
    const paths = (studentRoute.children ?? []).map((c) =>
      c.index ? "" : (c as { path: string }).path,
    )
    expect(paths).toContain("landing")
  })

  it("does not mount the marketing route inside the student portal", () => {
    expect(marketingRoute.path).toBe("landing")
    // Sanity: the student portal no longer imports the landing screen at all.
    const source = fs.readFileSync(
      path.resolve(__dirname, "../../src/portals/student/index.tsx"),
      "utf8",
    )
    expect(source).not.toMatch(/screens\/Landing/)
  })

  it("no longer ships a Landing screen inside the student portal", () => {
    expect(
      fs.existsSync(path.resolve(__dirname, "../../src/portals/student/screens/Landing.tsx")),
    ).toBe(false)
  })
})

/*
 * Task 19 (spec §4.4) · marketing CTAs point at `/signup`, not `/login`.
 *
 * A source-text check rather than a rendered one, matching this file's own
 * established method above (`does not mount the marketing route inside the
 * student portal` reads `student/index.tsx` as text for the same reason):
 * `vitest.config.ts` runs the node environment on purpose, with no jsdom and
 * no React Testing Library, so there is nothing here to click a `<Button>`
 * and inspect what `navigate` was called with. Reading the source for the
 * literal call sites is the honest substitute available at this layer, and
 * it is exactly the kind of fact — "this string appears in this file" — that
 * a source-text check is good at pinning down.
 *
 * Before Task 19, `/signup` did not exist, so every CTA on this page
 * (correctly, at the time) pointed at `/login` — spec §1's own problem
 * statement records that as the headline finding this whole redesign closes.
 * Now that `/signup` exists, a `navigate("/login")` reappearing here is a
 * regression to that exact defect, not a stylistic choice, which is why this
 * gets its own test rather than living only as a comment in `Landing.tsx`.
 */
describe("marketing CTAs route to signup, not sign-in — Task 19", () => {
  const source = fs.readFileSync(
    path.resolve(__dirname, "../../src/portals/marketing/Landing.tsx"),
    "utf8",
  )

  it("contains no navigate(\"/login\") call anywhere on the page", () => {
    expect(source).not.toMatch(/navigate\(["']\/login["']\)/)
  })

  /*
   * Two call sites in this file: the hero's primary CTA and the close CTA. A
   * third used to live here too, a per-plan CTA inside the "Plans" section's
   * populated-pricing branch — but that branch was dead code (Task 4, F3):
   * `pricing` is `[]` (the `landing copy claims only what the product does`
   * describe block above pins that directly) and always has been, so the
   * branch, and its CTA, could never render. Task 4 deletes the branch rather
   * than guard it, which drops this count from three to two.
   *
   * A fourth site exists on the page but not in this file: the per-role CTA
   * rendered once for each `roleTabs` entry, `navigate(active.cta.to)` in
   * `RoleTabs.tsx` since Task 3 moved the role panels out of `Landing.tsx`.
   * It is not a literal `/signup` string, so the regex below cannot see it
   * regardless of which file it lives in. Two things pin it instead: the
   * data-level assertion further down this block, which catches a `roleTabs`
   * entry silently re-targeted at `/login`, and the "reads the destination
   * from data" check below, which catches `RoleTabs.tsx` itself silently
   * hardcoding a destination instead of consuming that data (Task 4, F7).
   *
   * Task 2 (M-2): the hero's primary CTA now calls
   * `navigate(landingHero.primaryCta.to)` rather than repeating the literal
   * `"/signup"` string, so the data field the "routes every roleTabs CTA"
   * assertion below already pins is actually consumed by the page instead of
   * sitting unread beside it. The close CTA (Task 19 twin fix) does the same
   * with `navigate(landingClose.cta.to)`, so neither remaining call site is a
   * literal string anymore. The regex matches both data-consuming forms (and
   * the literal, in case either site ever reverts to one), so the count it
   * checks stays at two either way.
   */
  it("routes exactly two CTAs to /signup", () => {
    const matches =
      source.match(
        /navigate\(["']\/signup["']\)|navigate\(landingHero\.primaryCta\.to\)|navigate\(landingClose\.cta\.to\)/g,
      ) ?? []
    expect(matches).toHaveLength(2)
  })

  /*
   * I-2: the fourth CTA call site above (`navigate(r.cta.to)`) is invisible
   * to both source-text checks in this block, because its destination is a
   * data value, not a literal string. Pointing `roleTabs[].cta.to` at
   * `/login` would pass every assertion above while reintroducing exactly
   * the defect this describe block exists to prevent — but a blanket "never
   * /login" is too weak a guard on its own: it also passed the PARENT entry
   * pointed at `/signup` or `/signup/parent`, both wrong for a parent for the
   * same reason `SignupRoleSelect.tsx`'s own comment gives — a parent account
   * only ever comes from a child-issued invite, so `/join` is that role's
   * only destination, never a self-service signup form. This pins the exact
   * destination per role instead of a blanket "not /login".
   */
  it("routes every roleTabs CTA to the destination its role actually has, never to /login", () => {
    const EXPECTED_CTA_TO: Record<string, string> = {
      student: "/signup/student",
      // Parents have no self-service signup — SignupRoleSelect.tsx.
      parent: "/join",
      teacher: "/signup/teacher",
    }
    for (const r of roleTabs) {
      expect(r.cta.to).toBe(EXPECTED_CTA_TO[r.id])
      expect(r.cta.to).not.toBe("/login")
    }
    expect(landingHero.primaryCta.to.startsWith("/signup")).toBe(true)
    expect(landingClose.cta.to.startsWith("/signup")).toBe(true)
  })

  /*
   * The hero's *secondary* CTA ("For centres and teachers") is deliberately
   * excluded from both checks above: it was never a `navigate("/login")` call
   * to begin with, and its own comment in `Landing.tsx` explains why it
   * scrolls to the "who it serves" section instead of navigating anywhere.
   * Pinned here so a future edit that folds it into the signup-routing
   * pattern above (a plausible-looking "consistency" fix) has to remove this
   * assertion on purpose rather than by accident.
   */
  it("leaves the hero's secondary CTA scrolling to a section, not navigating", () => {
    expect(source).toMatch(/scrollIntoView/)
    expect(source).toMatch(/SERVES_SECTION_ID/)
  })

  /*
   * Review finding A: this whole describe block reads only `Landing.tsx`, so
   * the header's own "Get started" — rendered by `portals/marketing/index.tsx`,
   * not `Landing.tsx` — was never checked here. It is the page's most
   * prominent primary action (the only header link styled with
   * `buttonVariants`), and before `/signup` existed it pointed at `/login`
   * exactly like the CTAs above. A regression there must fail a test the same
   * way a regression in the hero or close CTA already does.
   */
  const shellSource = fs.readFileSync(
    path.resolve(__dirname, "../../src/portals/marketing/index.tsx"),
    "utf8",
  )

  it("keeps the header's primary action on /signup", () => {
    expect(shellSource).toMatch(/to="\/signup"[\s\S]{0,120}buttonVariants/)
    // The header also carries "Log in" (nav) and "Log in" (footer) — both
    // legitimately point at /login. Exactly two, never a third.
    expect(shellSource.match(/to="\/login"/g) ?? []).toHaveLength(2)
  })

  /*
   * F7: this whole describe block read only `Landing.tsx` and, once the
   * header check above was added, `portals/marketing/index.tsx`. Task 3
   * moved the role panels' CTA into `RoleTabs.tsx`, so that render site was
   * unguarded by any source-text check here — the same failure mode as
   * review finding A just above and I-2 further down this block, a third
   * time on this branch. The data-level assertion below (`routes every
   * roleTabs CTA...`) pins `roleTabs[].cta.to` itself, but nothing pinned
   * that `RoleTabs.tsx` actually reads that data rather than hardcoding a
   * destination of its own — which is exactly the gap a "consistency" edit
   * to `RoleTabs.tsx` could fall into without touching `data.ts` at all.
   */
  const roleTabsSource = fs.readFileSync(
    path.resolve(__dirname, "../../src/portals/marketing/RoleTabs.tsx"),
    "utf8",
  )

  it("routes the role panel's CTA from roleTabs data, not a hardcoded path", () => {
    expect(roleTabsSource).toMatch(/navigate\(active\.cta\.to\)/)
  })

  it("contains no navigate(\"/login\") call in the role panel", () => {
    expect(roleTabsSource).not.toMatch(/navigate\(["']\/login["']\)/)
  })
})

describe("landing copy claims only what the product does — P4.9", () => {
  /*
   * Item 3 (final whole-branch review) · this used to be a hand-built array
   * that pulled specific fields off specific exports. That shape is exactly
   * why `loopIntro` shipped for five commits with zero failing tests: it
   * renders as the second section's own `<h2>` and lead paragraph
   * (`Landing.tsx:236,238`) but nobody added its two lines to this list, and
   * nothing here could ever have noticed the omission — the list was the
   * only source of truth for what counted as "copy", and it disagreed with
   * the page. This is the fourth time this exact mechanism drifted on this
   * branch (I-6 added `rolesIntro`/`subjectsTitle`, F6 added
   * `pricingTitle`/`pricingPlaceholder`, and `subjects[].code` and
   * `mcq[].title` were two more silent gaps found in the same review that
   * added this comment).
   *
   * Fixed structurally instead of with a fifteenth line: `collectStrings`
   * walks every value of every listed export recursively, so a field cannot
   * be missed once its export is in scope — there is no per-field list left
   * to fall out of sync. What is still an explicit, hand-maintained list is
   * the much smaller, coarser thing: which *exports* are copy at all. That
   * list is self-checking (see the exhaustiveness test below), which is the
   * difference that matters — a `data.ts` export in neither `COPY_EXPORTS`
   * nor `NOT_COPY` fails this suite outright instead of silently rendering
   * ungated, the way `loopIntro` did.
   */

  /**
   * Recursively collects every string leaf under `value` into `out`.
   * Non-string, non-container leaves (numbers, booleans) are not copy and
   * are skipped rather than stringified, so a route like `roleTabs[].cta.to`
   * is swept in as harmlessly-scanned text and a count like `mcq[].id`
   * never becomes a phantom "0" in `allCopy`.
   */
  function collectStrings(value: unknown, out: string[]): void {
    if (typeof value === "string") {
      out.push(value)
    } else if (Array.isArray(value)) {
      value.forEach((v) => collectStrings(v, out))
    } else if (value !== null && typeof value === "object") {
      Object.values(value).forEach((v) => collectStrings(v, out))
    }
  }

  /**
   * Every `data.ts` export that renders as visible (or accessible, e.g. the
   * mcq cells' `title` tooltip) copy on the page. Walked recursively above,
   * so listing the export here is enough to gate every field it has now and
   * every field a future edit adds to it — the per-field gap this rewrite
   * closes.
   */
  const COPY_EXPORTS = [
    "landingHero",
    "heroExample",
    "mcq",
    "loopIntro",
    "loopSteps",
    "roleTabs",
    "rolesIntro",
    "subjectsTitle",
    "subjects",
    "subjectsNote",
    "pricingTitle",
    "pricingPlaceholder",
    "landingClose",
  ] as const

  /** Exports deliberately excluded from the copy gate, one reason each. */
  const NOT_COPY: Record<string, string> = {
    pricing:
      "empty ([]) while pricing is undecided; the 'ships no pricing tiers' test below asserts that directly",
  }

  /*
   * The exhaustiveness check the old list never had: every export the
   * compiled module actually has must appear in exactly one of the two
   * classifications above. A new `data.ts` export that lands in neither —
   * the fabricated-`loopIntro` failure mode, reproduced on purpose as one of
   * the two sabotage checks for this rewrite — fails here, not silently.
   */
  it("classifies every data.ts export as copy or NOT_COPY, with none left unclassified", () => {
    const actualExportNames = Object.keys(marketingData).sort()
    const classifiedNames = [...COPY_EXPORTS, ...Object.keys(NOT_COPY)].sort()
    expect(actualExportNames).toEqual(classifiedNames)
  })

  const copyValues: string[] = []
  for (const name of COPY_EXPORTS) {
    collectStrings((marketingData as unknown as Record<string, unknown>)[name], copyValues)
  }

  it("gates only string values", () => {
    copyValues.forEach((v) => expect(typeof v).toBe("string"))
  })

  const allCopy = copyValues.join("\n")

  /*
   * Each entry is a claim that was live on this page and had no
   * implementation. The comment is the verification, not a guess: these were
   * checked against the backend one at a time.
   */
  const bannedClaims: [RegExp, string][] = [
    // Notifications are web push and an in-app inbox. WhatsApp appeared
    // nowhere in the repository except this page.
    [/whatsapp/i, "no WhatsApp delivery exists"],
    // `lemely/web/schemas_teacher.py` records attendance and retention as
    // screen fields with no backend source, and there is no QR code, facial
    // check or 2FA anywhere in the product.
    [/\bQR\b/i, "no QR attendance exists"],
    [/\b2FA\b/i, "no second-factor check exists"],
    [/replayed minute/i, "lesson retention is structurally empty"],
    // PRODUCT.md:74 — payment processing is out of scope.
    [/payments?\b/i, "payment processing is out of scope"],
    // PRODUCT.md:105 — partner schools are on the must-not-fabricate list.
    [/partner(ed|ship)?\b/i, "there are no partner schools or teachers"],
    // C1 deleted this figure from the proof band; it survived in the hero.
    [/\b41s\b/i, "the marking-time figure has no source"],
    [/19\.5h/i, "the hours-saved figure has no source"],
    // Pricing is undecided, so no free/trial/card claim can be made.
    [/free\b/i, "pricing is undecided, so nothing can be called free"],
    [/\btrial\b/i, "no trial has ever existed"],
  ]

  it.each(bannedClaims)("makes no claim matching %s (%s)", (pattern) => {
    expect(allCopy).not.toMatch(pattern)
  })

  /*
   * The other half of C2, and the half a regex cannot express: the plans
   * section must stay empty until a real price exists. A future edit that
   * "fills the space" with example tiers fails here rather than shipping a
   * price to a prospective customer.
   */
  it("ships no pricing tiers while pricing is undecided", () => {
    expect(pricing).toHaveLength(0)
  })

  /*
   * The hero card shows a marked script, and the product has no customers
   * whose script it could be. The label is what makes the card honest, so it
   * is a fact about the data and not a detail of the markup.
   */
  it("labels the hero result card as an example", () => {
    expect(heroExample.exampleLabel).toMatch(/example/i)
  })
})

describe("the hero example card cannot contradict itself — P4.9", () => {
  /*
   * Three things state the same fact in three registers: the grid draws forty
   * cells with some marked wrong, the score reads 38/40, and the note says
   * "two marks dropped". They are derived from one array so they cannot
   * drift, and this pins that they agree — the defect the parent portal shipped
   * in another form, where one timestamp rendered as "1d ago" directly above
   * "2 days ago".
   */
  it("draws one cell per question", () => {
    expect(mcq).toHaveLength(40)
  })

  it("drops exactly as many marks as the score and the note both claim", () => {
    const dropped = mcq.filter((c) => !c.correct).length
    expect(dropped).toBe(2)
    expect(Number(heroExample.score)).toBe(mcq.length - dropped)
    expect(heroExample.max).toBe(`/${mcq.length}`)
    expect(heroExample.note.toLowerCase()).toContain("two marks dropped")
  })
})

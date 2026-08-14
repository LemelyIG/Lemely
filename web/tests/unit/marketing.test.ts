import { describe, expect, it } from "vitest"
import fs from "node:fs"
import path from "node:path"

import { appRoutes } from "@/routes"
import { marketingRoute } from "@/portals/marketing"
import { studentRoute } from "@/portals/student"
import {
  landingHero,
  heroExample,
  landingClose,
  loopSteps,
  mcq,
  pillars,
  pricing,
  proof,
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

describe("landing copy claims only what the product does — P4.9", () => {
  /** Every string a visitor can read on the page, flattened. */
  const allCopy = [
    ...Object.values(landingHero),
    ...Object.values(heroExample),
    ...Object.values(landingClose),
    ...loopSteps.flatMap((s) => [s.step, s.title, s.body]),
    ...pillars.flatMap((p) => [p.kicker, p.title, p.body, ...p.bullets]),
    ...proof.flatMap((p) => [p.n, p.l]),
  ].join("\n")

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

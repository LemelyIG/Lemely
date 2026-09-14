import { describe, expect, it } from "vitest"
import fs from "node:fs"
import path from "node:path"

import { appRoutes } from "@/routes"
import { marketingRoute } from "@/portals/marketing"
import { studentRoute } from "@/portals/student"
import * as marketingData from "@/portals/marketing/data"
import { close, hero } from "@/portals/marketing/data"

/*
 * P4.9 · the Persuade lane, pinned. Rewritten for the design import
 * (feat/landing-redesign, 2026-09-14) — see `.superpowers/sdd/
 * design-import-spec.md` and `design-import-claims.md`'s RULING. The design
 * replaced the page's structure and copy wholesale (role-neutral hero and
 * card grid out; centred hero, dark trust band, and the imported section
 * order in), so most of this file's assertions changed shape along with it.
 * What did NOT change is the intent behind each one: this page is still the
 * only public one in the product, its CTAs still have to route to signup
 * rather than sign-in, and its copy is still gated against inventing a claim
 * the product's code does not back.
 *
 * Two classes of fact live here, and they are both the kind that rot in
 * silence:
 *
 * 1. REACHABILITY. The marketing page spent a whole build behind
 *    `RequireAuth allowedRoles={["student"]}` at `/student/landing`, where
 *    the only reader who could open it was a student who had already signed
 *    up. A guard placed around the wrong subtree is invisible to every gate
 *    this build runs except a test that says out loud which routes are
 *    public.
 *
 * 2. HONEST COPY. Every claim on this page traces to a comment saying where
 *    it was verified, or to the RULING that says it ships anyway as the
 *    design's own authoritative call. The banned-claim assertions below are
 *    deliberately literal: they name the words, because the failure mode is
 *    not a wrong number, it is a plausible sentence about a feature nobody
 *    built.
 */

/** Top-level route paths the product mounts, in order. */
const topLevelPaths = appRoutes.map((r) => r.path)

/**
 * Walk a route element tree looking for a component by display name.
 *
 * Guards are React elements, so this is the only honest way to ask "is this
 * route behind `RequireAuth`" without rendering it. Matching by name rather
 * than by type identity means it keeps working when a guard is wrapped in a
 * Suspense or a frame, which is exactly how the original defect hid.
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

  it("puts no auth guard on the marketing route", () => {
    const route = appRoutes.find((r) => r.path === "/landing")
    expect(route).toBeDefined()
    expect(containsComponent(route!.element, "RequireAuth")).toBe(false)
  })

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
 * Marketing CTAs point at `/signup`, not `/login`. A source-text check
 * rather than a rendered one: `vitest.config.ts` runs the node environment,
 * with no jsdom and no React Testing Library, so reading the literal call
 * sites is the honest substitute available at this layer.
 */
describe("marketing CTAs route to signup, not sign-in", () => {
  const source = fs.readFileSync(
    path.resolve(__dirname, "../../src/portals/marketing/Landing.tsx"),
    "utf8",
  )

  it("contains no navigate(\"/login\") call anywhere on the page", () => {
    expect(source).not.toMatch(/navigate\(["']\/login["']\)/)
  })

  /*
   * Two call sites: the hero's primary CTA and the close CTA. The imported
   * design's "who it serves" section (`Readings`, part B) carries no CTA of
   * its own — unlike the previous build's `RoleTabs`, whose per-role signup
   * buttons this design replaces with three read-only tab panels — so there
   * is no third or fourth call site to account for here anymore.
   */
  it("routes exactly two CTAs to /signup", () => {
    const matches =
      source.match(
        /navigate\(["']\/signup["']\)|navigate\(hero\.primaryCta\.to\)|navigate\(close\.cta\.to\)/g,
      ) ?? []
    expect(matches).toHaveLength(2)
  })

  it("reads both CTA destinations from data.ts, not a hardcoded literal", () => {
    expect(hero.primaryCta.to.startsWith("/signup")).toBe(true)
    expect(close.cta.to.startsWith("/signup")).toBe(true)
  })

  /*
   * The hero's *secondary* CTA ("See a marked script") is deliberately
   * excluded: it scrolls to the dark trust band rather than navigating
   * anywhere, same reasoning as the previous build's own secondary CTA.
   */
  it("leaves the hero's secondary CTA scrolling to a section, not navigating", () => {
    expect(source).toMatch(/scrollIntoView/)
    expect(source).toMatch(/MARKED_SECTION_ID/)
  })

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
})

/*
 * Design import: `marketing.css` (the verbatim page CSS port) and the
 * components that consume it stay token-only, per design-import-spec.md's
 * hard constraint ("Tokens only: zero raw oklch(, hex, or text-[...] under
 * portals/marketing/**"). A source-text sweep, same method the rest of this
 * file already uses for facts a rendered test can't see.
 */
describe("design import: token purity and the z-nav rename", () => {
  const marketingDir = path.resolve(__dirname, "../../src/portals/marketing")
  const files = fs
    .readdirSync(marketingDir)
    .filter((f) => /\.(tsx?|css)$/.test(f))
    .map((f) => ({ name: f, source: fs.readFileSync(path.join(marketingDir, f), "utf8") }))

  it("has files to check (sanity — the glob above did not silently match nothing)", () => {
    expect(files.length).toBeGreaterThan(0)
  })

  it.each(files.map((f) => f.name))("contains no raw oklch(...) literal (%s)", (name) => {
    const file = files.find((f) => f.name === name)!
    expect(file.source).not.toMatch(/oklch\(/)
  })

  it.each(files.map((f) => f.name))("contains no raw hex color literal (%s)", (name) => {
    const file = files.find((f) => f.name === name)!
    // Matches #abc / #aabbcc style literals but not something like a URL
    // fragment; this codebase's design tokens never need a bare hex.
    expect(file.source).not.toMatch(/#[0-9a-fA-F]{3,8}\b/)
  })

  it.each(files.filter((f) => f.name.endsWith(".tsx")).map((f) => f.name))(
    "contains no Tailwind arbitrary color value text-[...]/bg-[#...] (%s)",
    (name) => {
      const file = files.find((f) => f.name === name)!
      expect(file.source).not.toMatch(/\b(?:text|bg|border)-\[#/)
    },
  )

  it("marketing.css rewrites the design's --z-nav to the repo's --z-index-nav, and defines no duplicate token", () => {
    const css = files.find((f) => f.name === "marketing.css")!.source
    expect(css).toMatch(/var\(--z-index-nav\)/)
    expect(css).not.toMatch(/--z-nav\b/)
  })
})

/*
 * Part B swapped every `StubMount` placeholder for the real specimen
 * component. Pinned the other direction from part A's own check: this
 * asserts the stubs are GONE and each real component is both imported and
 * mounted, so a future edit that reverts one to a placeholder (or imports
 * it without ever rendering it) fails here rather than silently.
 */
describe("design import: part B's five specimen components are all mounted", () => {
  const source = fs.readFileSync(
    path.resolve(__dirname, "../../src/portals/marketing/Landing.tsx"),
    "utf8",
  )
  const specimens = ["OpenedQuestion", "ScanSequence", "SchemeExcerpt", "ClassBatch", "Readings"]

  it("mounts no StubMount placeholder anywhere", () => {
    // A regex on the literal call/definition forms, not the bare word —
    // the surrounding prose (this file's own comments included) narrates
    // the swap using the word "StubMount" without it being a live call.
    expect(source).not.toMatch(/<StubMount\b|function StubMount\b/)
  })

  it.each(specimens)("imports and renders %s", (name) => {
    expect(source).toMatch(new RegExp(`import\\s*\\{[^}]*\\b${name}\\b[^}]*\\}\\s*from\\s*"\\./${name}"`))
    expect(source).toMatch(new RegExp(`<${name}\\s*/>`))
  })
})

describe("landing copy claims only what the product does — P4.9", () => {
  /**
   * Recursively collects every string leaf under `value` into `out`.
   * Non-string, non-container leaves (numbers, booleans, undefined — two
   * fields below are deliberately undefined pending a verbatim quote, see
   * data.ts's header) are skipped rather than stringified.
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
   * Every `data.ts` export that renders as visible copy on the page. Walked
   * recursively, so listing the export here gates every field it has now
   * and every field a future edit adds to it.
   */
  const COPY_EXPORTS = [
    "hero",
    "subjects",
    "trustBand",
    "howItWorks",
    "schemeSection",
    "classBatchSection",
    "readingsIntro",
    "close",
    "openedQuestion",
    "scanSequence",
    "schemeExcerpt",
    "classBatch",
    "readings",
  ] as const

  /** Exports deliberately excluded from the copy gate, one reason each. */
  const NOT_COPY: Record<string, string> = {}

  /*
   * The exhaustiveness check: every export the compiled module actually has
   * must appear in exactly one of the two classifications above. A new
   * `data.ts` export that lands in neither fails here, not silently — the
   * same mechanism the previous build's own `loopIntro` slipped past before
   * this check existed.
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
   * Each entry is a claim that was live on the PREVIOUS build's page and had
   * no implementation. Carried forward unchanged into the design import:
   * none of the design's own (verbatim-shipped, per the RULING) claims trip
   * any of these, so the gate still does useful work rather than being
   * loosened to fit.
   */
  const bannedClaims: [RegExp, string][] = [
    [/whatsapp/i, "no WhatsApp delivery exists"],
    [/\bQR\b/i, "no QR attendance exists"],
    [/\b2FA\b/i, "no second-factor check exists"],
    [/replayed minute/i, "lesson retention is structurally empty"],
    [/payments?\b/i, "payment processing is out of scope"],
    [/partner(ed|ship)?\b/i, "there are no partner schools or teachers"],
    [/\b41s\b/i, "the marking-time figure has no source"],
    [/19\.5h/i, "the hours-saved figure has no source"],
    [/free\b/i, "pricing is undecided, so nothing can be called free"],
    [/\btrial\b/i, "no trial has ever existed"],
  ]

  it.each(bannedClaims)("makes no claim matching %s (%s)", (pattern) => {
    expect(allCopy).not.toMatch(pattern)
  })

  it("contains no em dash anywhere in gated copy", () => {
    expect(allCopy).not.toMatch(/—/)
  })
})

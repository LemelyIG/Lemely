import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"
import {
  FULL_PAGE_STATE_COPY,
  FULL_PAGE_STATE_VARIANTS,
  type FullPageStateVariant,
} from "@/portals/misc/fullPageStateCopy"
import type { DoodleKind } from "@/components/ui/doodle"

/*
 * PR 2 part A1 · the full-page-state copy table, checked as data.
 *
 * No DOM and no React import: `fullPageStateCopy.ts` is deliberately pure so
 * this suite can run under plain Node and check the approved canvas's copy
 * mechanically rather than by re-reading it. Same two rules the rest of the
 * product's copy answers to (`checkCopy.test.ts`'s narrower em-dash-only
 * check, `scripts/check_copy.mjs`) plus two structural ones specific to this
 * table: every variant maps to a real `DoodleKind` except the one that
 * deliberately does not (`slow-load`, which is copy-only — see
 * `fullPageStateCopy.ts`'s header), and the ordered list `FullPageState.tsx`'s
 * kit-preview page iterates covers every key exactly once.
 */

const EM_DASH = /[—–]/
const EXCLAMATION = /!/

/** True where the first alphabetic character is lowercase — i.e. NOT sentence
 * case. A string with no letters at all (there is none here, but future-proof)
 * trivially passes. Mirrors the sentence-case rule DESIGN.md §4.2 states for
 * headings and prose. */
function startsLowercase(text: string): boolean {
  const firstLetter = text.match(/[A-Za-z]/)
  if (!firstLetter) return false
  return firstLetter[0] === firstLetter[0].toLowerCase() && firstLetter[0] !== firstLetter[0].toUpperCase()
}

const DOODLE_KINDS: readonly DoodleKind[] = [
  "not-found",
  "crash",
  "offline",
  "new-version",
  "session-ended",
  "no-access",
  "service-trouble",
  "too-many-requests",
]

describe("FULL_PAGE_STATE_COPY", () => {
  it("gives every variant a non-empty heading and body", () => {
    for (const [variant, copy] of Object.entries(FULL_PAGE_STATE_COPY)) {
      expect(copy.heading, variant).not.toBe("")
      expect(copy.body, variant).not.toBe("")
    }
  })

  it("never uses an em-dash or en-dash in any copy field", () => {
    const offenders: string[] = []
    for (const [variant, copy] of Object.entries(FULL_PAGE_STATE_COPY)) {
      for (const field of ["kicker", "heading", "body"] as const) {
        if (EM_DASH.test(copy[field])) offenders.push(`${variant}.${field}`)
      }
    }
    expect(offenders).toEqual([])
  })

  it("never uses an exclamation mark in any copy field", () => {
    const offenders: string[] = []
    for (const [variant, copy] of Object.entries(FULL_PAGE_STATE_COPY)) {
      for (const field of ["kicker", "heading", "body"] as const) {
        if (EXCLAMATION.test(copy[field])) offenders.push(`${variant}.${field}`)
      }
    }
    expect(offenders).toEqual([])
  })

  it("starts every non-empty kicker, heading and body with sentence case", () => {
    const offenders: string[] = []
    for (const [variant, copy] of Object.entries(FULL_PAGE_STATE_COPY)) {
      for (const field of ["kicker", "heading", "body"] as const) {
        const value = copy[field]
        if (value !== "" && startsLowercase(value)) offenders.push(`${variant}.${field} — "${value}"`)
      }
    }
    expect(offenders).toEqual([])
  })

  it("maps every variant except slow-load to a real DoodleKind", () => {
    const nonDoodle = (Object.keys(FULL_PAGE_STATE_COPY) as FullPageStateVariant[]).filter(
      (variant) => variant !== "slow-load" && !DOODLE_KINDS.includes(variant as DoodleKind),
    )
    expect(nonDoodle).toEqual([])
  })

  it("gives slow-load no DoodleKind of its own", () => {
    expect(DOODLE_KINDS.includes("slow-load" as DoodleKind)).toBe(false)
  })
})

describe("new-version copy (SHOULD-FIX 7): describes the observation, not an asserted deploy", () => {
  const copy = FULL_PAGE_STATE_COPY["new-version"]

  it("does not claim a new version is ready or that a deploy happened", () => {
    // `navigator.onLine` (what `routeError.ts` gates this variant on) reads
    // `true` behind a captive portal and on flaky wifi, not only after a
    // real deploy — asserting "a new version of Lemely is ready" for every
    // such failure would often be a guess dressed up as a fact.
    expect(copy.heading.toLowerCase()).not.toContain("new version")
    expect(copy.heading.toLowerCase()).not.toContain("ready")
    expect(copy.body.toLowerCase()).not.toMatch(/\bwas built for an older version\b/)
  })

  it("still names reloading as the fix, honestly framed as a maybe for the deploy part", () => {
    expect(copy.body.toLowerCase()).toContain("reload")
    expect(copy.body.toLowerCase()).toMatch(/\bif\b.*\bupdated\b/)
  })

  it("keeps the single reload action and no second action", () => {
    expect(copy.primary).toBe("reload")
    expect(copy.secondary).toBeNull()
  })
})

describe("FULL_PAGE_STATE_VARIANTS", () => {
  it("covers every key of FULL_PAGE_STATE_COPY exactly once", () => {
    const keys = Object.keys(FULL_PAGE_STATE_COPY).sort()
    const listed = [...FULL_PAGE_STATE_VARIANTS].sort()
    expect(listed).toEqual(keys)
    expect(new Set(FULL_PAGE_STATE_VARIANTS).size).toBe(FULL_PAGE_STATE_VARIANTS.length)
  })
})

describe("the slow-load identity is the v5 'lm' icon", () => {
  const root = join(import.meta.dirname, "..", "..")
  const source = readFileSync(join(root, "src/portals/misc/FullPageState.tsx"), "utf8")
  const css = readFileSync(join(root, "src/index.css"), "utf8")

  it("renders the generated lm icon, not the retired notebook Mark", () => {
    expect(source).toContain('src="/brand/mark.svg"')
    expect(source).not.toMatch(/<Mark\b|ui\/mark"|brandMark/)
  })

  it("pulses with the opacity-only breathe animation", () => {
    expect(source).toContain("animate-lm-breathe")
    const keyframes = css.match(/@keyframes lm-breathe\s*\{([\s\S]*?)\n\}/)
    expect(keyframes, "lm-breathe keyframes").not.toBeNull()
    const properties = [...keyframes![1].matchAll(/([a-z-]+)\s*:/g)].map((m) => m[1])
    expect(new Set(properties)).toEqual(new Set(["opacity"]))
  })

  it("is covered by the global prefers-reduced-motion rule", () => {
    const block = css.match(/@media \(prefers-reduced-motion: reduce\)\s*\{\s*\*,[\s\S]*?\n\}/)
    expect(block?.[0]).toMatch(/animation-duration:\s*0\.001ms !important/)
    expect(block?.[0]).toMatch(/animation-iteration-count:\s*1 !important/)
  })
})

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

describe("FULL_PAGE_STATE_VARIANTS", () => {
  it("covers every key of FULL_PAGE_STATE_COPY exactly once", () => {
    const keys = Object.keys(FULL_PAGE_STATE_COPY).sort()
    const listed = [...FULL_PAGE_STATE_VARIANTS].sort()
    expect(listed).toEqual(keys)
    expect(new Set(FULL_PAGE_STATE_VARIANTS).size).toBe(FULL_PAGE_STATE_VARIANTS.length)
  })
})

import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"
import { DIRECTORY_ROBOTS_TAG, NOINDEX_ROBOTS_TAG } from "../../worker/robots.ts"
import {
  DIRECTORY_ROBOTS,
  NOINDEX_ROBOTS,
  classifyTutorPath,
  robotsForCard,
  robotsForDirectory,
} from "@/lib/tutoring/robotsMeta"

/*
 * T22: the client half of decision row 17 (SPEC §b.5, "Client meta"). G-16 is
 * always `noindex, follow`; G-17 is `noindex, nofollow` unless P2 returned
 * `indexable === true`, and also while P2 is loading or has failed. The tag
 * must match what the edge worker sends, so the two constants are compared
 * with the worker's own, and the canonical-path guard keeps a differently
 * spelled address (which the worker would serve without any tag) from ever
 * rendering a card.
 */

const SPEC = readFileSync(
  join(import.meta.dirname, "..", "..", "..", "docs", "tutoring", "SPEC.md"),
  "utf8",
)

const ID = "0b6a8d1e-52f3-4c1a-9a47-5d2f0e6c7b13"

describe("the tags", () => {
  it("are the worker's, word for word", () => {
    expect(DIRECTORY_ROBOTS).toBe(DIRECTORY_ROBOTS_TAG)
    expect(NOINDEX_ROBOTS).toBe(NOINDEX_ROBOTS_TAG)
  })

  it("are the ones SPEC §d names", () => {
    expect(SPEC).toContain("G-16 is always `noindex, follow`")
    expect(SPEC).toContain("`noindex, nofollow` when they opted out or are not listed")
    expect(DIRECTORY_ROBOTS).toBe("noindex, follow")
    expect(NOINDEX_ROBOTS).toBe("noindex, nofollow")
  })
})

describe("G-16, the directory", () => {
  it("is always noindex, follow", () => {
    expect(robotsForDirectory()).toBe("noindex, follow")
  })
})

describe("G-17, a tutor's public card", () => {
  it("is noindex, nofollow while P2 is loading", () => {
    expect(robotsForCard({ status: "pending" })).toBe("noindex, nofollow")
  })

  it("is noindex, nofollow when P2 failed, whatever data it may still hold", () => {
    expect(robotsForCard({ status: "error" })).toBe("noindex, nofollow")
    expect(robotsForCard({ status: "error", data: { indexable: true } })).toBe("noindex, nofollow")
  })

  it("is indexable (no tag, matching the absent header) only when indexable is exactly true", () => {
    expect(robotsForCard({ status: "success", data: { indexable: true } })).toBeNull()
  })

  it("is noindex, nofollow when the tutor opted out", () => {
    expect(robotsForCard({ status: "success", data: { indexable: false } })).toBe("noindex, nofollow")
  })

  it("fails closed on anything that is not the boolean true", () => {
    for (const indexable of [undefined, null, "true", 1, "yes", {}, []]) {
      expect(robotsForCard({ status: "success", data: { indexable } }), String(indexable)).toBe("noindex, nofollow")
    }
    expect(robotsForCard({ status: "success", data: undefined })).toBe("noindex, nofollow")
    expect(robotsForCard({ status: "success", data: null })).toBe("noindex, nofollow")
  })
})

describe("which address a page may answer to", () => {
  it("serves the directory and a card only at their canonical paths", () => {
    expect(classifyTutorPath("/tutors")).toEqual({ kind: "directory" })
    expect(classifyTutorPath(`/tutors/${ID}`)).toEqual({ kind: "card", tutorId: ID })
    // The worker accepts either case of the id, so the page does too.
    expect(classifyTutorPath(`/tutors/${ID.toUpperCase()}`)).toEqual({
      kind: "card",
      tutorId: ID.toUpperCase(),
    })
  })

  it("sends a variant spelling to the canonical path instead of rendering it", () => {
    for (const path of ["/tutors/", "/Tutors", "/TUTORS", "/tutors//"]) {
      expect(classifyTutorPath(path), path).toEqual({ kind: "redirect", to: "/tutors" })
    }
    for (const path of [`/tutors/${ID}/`, `/Tutors/${ID}`, `/TUTORS/${ID}//`]) {
      expect(classifyTutorPath(path), path).toEqual({ kind: "redirect", to: `/tutors/${ID}` })
    }
  })

  it("never renders an id the worker would not look up", () => {
    for (const path of [
      "/tutors/not-a-uuid",
      `/tutors/${ID}/extra`,
      `/tutors/${ID.slice(0, -1)}`,
      `/tutors/${ID}%20`,
      `/tutors/%30b6a8d1e-52f3-4c1a-9a47-5d2f0e6c7b13`,
      "/tutors/../student",
      "/tutorsx",
      "/tutor/abc",
      "/",
      "",
    ]) {
      expect(classifyTutorPath(path), path).toEqual({ kind: "not_found" })
    }
  })

  it("agrees with the worker about what a card path is", () => {
    // The worker's own pattern, restated from its source comment: exactly one
    // segment of canonical 8-4-4-4-12 hex in either case.
    const workerCard = /^\/tutors\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
    const paths = [
      `/tutors/${ID}`,
      `/tutors/${ID.toUpperCase()}`,
      "/tutors/12345678-1234-1234-1234-123456789abc",
      "/tutors/12345678-1234-1234-1234-123456789abg",
      "/tutors/1234567812341234123412345678",
      "/tutors/abc",
    ]
    for (const path of paths) {
      expect(classifyTutorPath(path).kind === "card", path).toBe(workerCard.test(path))
    }
  })
})

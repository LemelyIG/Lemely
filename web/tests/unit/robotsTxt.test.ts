import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"

/*
 * Decision-log row 17: tutor cards are indexable by default, and the edge worker
 * decides each card from P2 (`/api/public/tutors/{id}`). Google applies the most
 * specific matching rule, so `Disallow: /api/` alone would stop it fetching P2
 * for its own purposes (rendering a card, a client-side lookup), every card would
 * then error, fail closed and carry `noindex, nofollow`. The one carve-out is the
 * public tutor lookup; nothing else under /api/ may be allowed.
 */

const TXT = readFileSync(join(import.meta.dirname, "..", "..", "public", "robots.txt"), "utf8")

interface Rule {
  kind: "allow" | "disallow"
  path: string
  group: string[]
}

function parse(text: string): { rules: Rule[]; groups: number } {
  const rules: Rule[] = []
  let agents: string[] = []
  let lastWasAgent = false
  let groups = 0
  for (const raw of text.split("\n")) {
    const line = raw.replace(/#.*/, "").trim()
    if (!line) continue
    const [field, ...rest] = line.split(":")
    const value = rest.join(":").trim()
    const key = field.trim().toLowerCase()
    if (key === "user-agent") {
      if (!lastWasAgent) {
        agents = []
        groups += 1
      }
      agents.push(value)
      lastWasAgent = true
      continue
    }
    lastWasAgent = false
    if (key === "allow" || key === "disallow") rules.push({ kind: key, path: value, group: [...agents] })
  }
  return { rules, groups }
}

const { rules, groups } = parse(TXT)

describe("robots.txt and the public tutor lookup", () => {
  it("parses the groups and rules it asserts over (non-vacuity)", () => {
    expect(groups).toBeGreaterThanOrEqual(1)
    expect(rules.length).toBeGreaterThanOrEqual(8)
    expect(rules.some((r) => r.kind === "disallow" && r.path === "/api/")).toBe(true)
  })

  it("allows /api/public/tutors/ and lists that Allow before Disallow: /api/", () => {
    const allow = rules.findIndex((r) => r.kind === "allow" && r.path === "/api/public/tutors/")
    const disallow = rules.findIndex((r) => r.kind === "disallow" && r.path === "/api/")
    expect(allow, "Allow: /api/public/tutors/ is missing").toBeGreaterThan(-1)
    expect(disallow).toBeGreaterThan(-1)
    expect(allow).toBeLessThan(disallow)
  })

  it("allows nothing else under /api/", () => {
    const allowedApi = rules.filter((r) => r.kind === "allow" && r.path.startsWith("/api"))
    expect(allowedApi.map((r) => r.path)).toEqual(["/api/public/tutors/"])
  })

  it("still disallows /api/ and every portal for the same agents", () => {
    const disallowed = rules.filter((r) => r.kind === "disallow").map((r) => r.path)
    for (const path of ["/api/", "/student", "/teacher", "/parent", "/admin", "/settings", "/join"]) {
      expect(disallowed, path).toContain(path)
    }
    // Only the carve-out and the root are allowed anywhere.
    expect(rules.filter((r) => r.kind === "allow").map((r) => r.path).sort()).toEqual(["/", "/api/public/tutors/"])
  })
})

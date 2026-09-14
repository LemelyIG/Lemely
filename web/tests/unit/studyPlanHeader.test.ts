import { describe, expect, it } from "vitest"
import { readFileSync } from "node:fs"
import { join } from "node:path"
import { stripComments } from "./support/jsxSource"

/*
 * C3b · Source-text pins for the wiring pieces this packet touches — the
 * component composition can't be exercised under vitest's Node/no-jsdom
 * environment (D3.20); the pure half (`daysUntil`/`formatCountdown`,
 * `weekHeaderKicker`, `activityIcon`, the session-length presets) is pinned
 * in `countdown.test.ts`, `studyPlan.test.ts` and `sessionLengthPresets.test.ts`.
 */

const ROOT = process.cwd()

function sourceOf(relativePath: string): string {
  return stripComments(readFileSync(join(ROOT, relativePath), "utf8"))
}

describe("StudyPlanWeek.tsx", () => {
  const source = sourceOf("src/portals/student/screens/studyplan/StudyPlanWeek.tsx")

  it("builds its header from SectionHead", () => {
    expect(source).toContain("<SectionHead")
  })

  it("uses weekHeaderKicker (built on daysUntil/formatCountdown) for the kicker", () => {
    expect(source).toContain("weekHeaderKicker")
  })

  it("carries no leftover 14-day framing", () => {
    expect(source).not.toContain("14 days")
  })
})

describe("Announcements.tsx", () => {
  const source = sourceOf("src/portals/student/screens/Announcements.tsx")

  it("imports daysUntil/formatCountdown from lib/countdown instead of defining them locally", () => {
    expect(source).toContain('from "@/lib/countdown"')
    expect(source).not.toMatch(/export function daysUntil/)
    expect(source).not.toMatch(/export function formatCountdown/)
  })
})

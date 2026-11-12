import { describe, expect, it } from "vitest"
import { readFileSync } from "node:fs"
import { join } from "node:path"
import { stripComments } from "./support/jsxSource"

/*
 * Task 7 (B5a) · source-text gates for the capability wiring this packet
 * adds: optimistic flashcard grading, haptics, Wake Lock, Web Share and app
 * badging. None of the components involved are mountable under this suite's
 * DOM-less Node environment (`vitest.config.ts`, D3.20) — same reasoning as
 * `routeErrorWiring.test.ts` — so these gates pin the wiring as text instead.
 */

const ROOT = join(import.meta.dirname, "..", "..")

function readSource(relativePath: string): string {
  return stripComments(readFileSync(join(ROOT, relativePath), "utf8"))
}

describe("useFlashcardApi.ts — useReviewCard retries", () => {
  it("configures retry: 3 with an exponential-backoff delay", () => {
    const source = readSource("src/lib/hooks/useFlashcardApi.ts")
    expect(source).toContain("retry: 3")
    expect(source).toContain("retryDelay:")
  })
})

describe("FlashcardReview.tsx — optimistic advance and capability imports", () => {
  const source = readSource("src/portals/student/screens/flashcards/FlashcardReview.tsx")

  it("imports applyGradeOutcome and haptic", () => {
    expect(source).toContain("applyGradeOutcome")
    expect(source).toContain("haptic")
  })

  it("advances the index before the mutation is sent (optimistic advance)", () => {
    expect(source).toMatch(/setIndex[\s\S]{0,200}reviewCard\.mutate/)
  })
})

describe("confirm-modal.tsx — haptic tap on confirm", () => {
  it("imports haptic", () => {
    const source = readSource("src/components/ui/confirm-modal.tsx")
    expect(source).toContain("haptic")
  })
})

describe("CameraCapture.tsx — wake lock and landscape hint", () => {
  const source = readSource("src/components/CameraCapture.tsx")

  it("imports useWakeLock", () => {
    expect(source).toContain("useWakeLock")
  })

  it("carries a landscape hint using Tailwind's built-in landscape: variant", () => {
    expect(source).toContain("landscape:")
  })
})

describe("PaperResult.tsx — Web Share", () => {
  it("imports shareResult", () => {
    const source = readSource("src/portals/student/screens/PaperResult.tsx")
    expect(source).toContain("shareResult")
  })
})

describe("BadgeSync mounted in the three authenticated portal layouts, not main.tsx", () => {
  it.each([
    "src/portals/student/index.tsx",
    "src/portals/teacher/index.tsx",
    "src/portals/parent/index.tsx",
  ])("%s mounts <BadgeSync", (path) => {
    expect(readSource(path)).toContain("<BadgeSync")
  })

  it("main.tsx does not mount BadgeSync — its data hits an auth-gated endpoint", () => {
    expect(readSource("src/main.tsx")).not.toContain("BadgeSync")
  })
})

describe("Notifications.tsx — clears the badge on mount", () => {
  it("calls setAppBadge(0)", () => {
    expect(readSource("src/portals/student/screens/Notifications.tsx")).toContain("setAppBadge(0)")
  })
})

describe("sw.ts — badge count rides the push content-request handshake", () => {
  it("calls setAppBadge from the push handler", () => {
    expect(readSource("src/sw.ts")).toContain("setAppBadge")
  })
})

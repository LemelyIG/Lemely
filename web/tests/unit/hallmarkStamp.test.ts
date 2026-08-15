import { readFileSync, statSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"
import { relativeTo, sourceFiles } from "./support/jsxSource"

/**
 * §9 Hard Gate 1, as a test (P7.1).
 *
 * ── Why this arrives in the last phase ─────────────────────────────────────
 *
 * REDESIGN-MISSION §9.1 requires the hallmark pre-emit self-critique stamp
 * `/* Hallmark · pre-emit critique: P_ H_ E_ S_ R_ V_ *\/` on **every emitted
 * surface**, with every axis at 3 or better, and names the reviewer subagent as
 * its enforcer. A human reading a diff was the whole mechanism. Nothing in the
 * repo ever checked it, so the gate could report green while surfaces shipped
 * without one, and two did: `Quizzes.tsx` (surface 5) and `PracticeGenerator`
 * (surface 3), both listed DONE in the surface ledger.
 *
 * ── The part that makes this worth a gate rather than two edits ────────────
 *
 * The gap was already known. D3's record ends with a standing note: "Phase 2
 * emitted 19 kit components without the hallmark pre-emit critique stamp §9.1
 * requires... Phase 4 should stamp each as it touches it rather than back-fill
 * scores nobody re-derived." That is a good plan — a score you did not derive
 * is a fabricated critique, which is worse than a missing one — and it was
 * recorded honestly and given to a convention to carry.
 *
 * The population it was meant to drain went from **19 to 33**. Nothing was
 * watching, so every component added after that note was also added unstamped,
 * and the mitigation quietly ran backwards for four phases. That is the shape
 * this repo keeps re-finding: a rule with no reader.
 *
 * ── What this gate does and does not require ──────────────────────────────
 *
 * A *surface* is a screen. `src/portals/**` must be stamped, with no
 * exceptions, because those are the things §9.1 names. Kit primitives compose
 * into surfaces rather than being them, so they are not required to carry one —
 * but the 33 that currently do not are frozen into a list below, so the
 * population can only ever shrink. A new kit component fails this gate until
 * somebody critiques it, which is exactly the reader D3's note lacked.
 *
 * Placement is deliberately not policed. Six screens carry their stamp below
 * the imports rather than on line 1; §9.1 says "present", and moving six
 * comments to satisfy a rule nobody wrote would be churn in files this phase
 * has no other reason to open.
 */

const ROOT = join(import.meta.dirname, "..", "..")
const SRC = join(ROOT, "src")

const STAMP = /Hallmark · pre-emit critique: P([1-5]) H([1-5]) E([1-5]) S([1-5]) R([1-5]) V([1-5])/

/** Any stamp-looking line, so a malformed one is caught rather than ignored by
 * a stricter pattern that simply fails to match it. */
const STAMP_LOOSE = /Hallmark[^\n]*pre-emit critique[^\n]*/g

/*
 * The kit components that predate the stamp convention, frozen 2026-08-14.
 *
 * This list may shrink and must never grow. Stamp a component when you next
 * have real reason to open it and derive the six scores from what you actually
 * read — do not back-fill the whole list in one sitting, which would produce 33
 * critiques nobody performed and make this gate a liar.
 */
const UNSTAMPED_KIT = [
  "src/components/CameraCapture.tsx",
  "src/components/quiz/QuizTaker.tsx",
  "src/components/ui/avatar.tsx",
  "src/components/ui/badge.tsx",
  "src/components/ui/button.tsx",
  "src/components/ui/celebration.tsx",
  "src/components/ui/chart-frame.tsx",
  "src/components/ui/checkbox.tsx",
  "src/components/ui/confidence-indicator.tsx",
  "src/components/ui/error-boundary.tsx",
  "src/components/ui/error-state.tsx",
  "src/components/ui/input.tsx",
  "src/components/ui/kbd.tsx",
  "src/components/ui/modal.tsx",
  "src/components/ui/nav-shells.tsx",
  "src/components/ui/paper-identity.tsx",
  "src/components/ui/popover.tsx",
  "src/components/ui/progress-bar.tsx",
  "src/components/ui/question-row.tsx",
  "src/components/ui/radio.tsx",
  "src/components/ui/role-switcher.tsx",
  "src/components/ui/select.tsx",
  "src/components/ui/skeleton.tsx",
  "src/components/ui/slider.tsx",
  "src/components/ui/stepper.tsx",
  "src/components/ui/subject-tag.tsx",
  "src/components/ui/switch.tsx",
  "src/components/ui/table.tsx",
  "src/components/ui/tabs.tsx",
  "src/components/ui/textarea.tsx",
  "src/components/ui/toast.tsx",
  "src/components/ui/trend-sparkline.tsx",
  "src/components/ui/weakness-chip.tsx",
]

const FILES = sourceFiles(SRC).map((file) => ({
  path: relativeTo(ROOT, file),
  source: readFileSync(file, "utf8"),
}))

describe("every emitted surface carries a pre-emit critique stamp", () => {
  it("stamps every screen under src/portals", () => {
    const missing = FILES.filter(
      (f) => f.path.startsWith("src/portals/") && !STAMP.test(f.source),
    ).map((f) => f.path)
    expect(missing).toEqual([])
  })

  it("scores every axis at 3 or better", () => {
    const weak: string[] = []
    for (const { path, source } of FILES) {
      const match = source.match(STAMP)
      if (!match) continue
      const axes = ["P", "H", "E", "S", "R", "V"]
      match.slice(1).forEach((value, i) => {
        // §9.1: "every axis >= 3 (revise until true)". A 2 is not a finding to
        // record, it is an instruction to go back and fix the surface.
        if (Number(value) < 3) weak.push(`${path} — ${axes[i]}${value}`)
      })
    }
    expect(weak).toEqual([])
  })

  it("has no malformed stamp anywhere", () => {
    const malformed: string[] = []
    for (const { path, source } of FILES) {
      for (const found of source.match(STAMP_LOOSE) ?? []) {
        if (!STAMP.test(found)) malformed.push(`${path} — ${found.trim()}`)
      }
    }
    expect(malformed).toEqual([])
  })
})

describe("the unstamped kit only ever shrinks", () => {
  it("has no unstamped component outside the frozen list", () => {
    const unexpected = FILES.filter(
      (f) => f.path.startsWith("src/components/") && !STAMP.test(f.source),
    )
      .map((f) => f.path)
      .filter((path) => !UNSTAMPED_KIT.includes(path))
    expect(unexpected, "a new kit component needs a real critique, not a copied stamp").toEqual([])
  })

  it("lists only files that still exist, and none that have since been stamped", () => {
    const stale: string[] = []
    for (const path of UNSTAMPED_KIT) {
      const absolute = join(ROOT, path)
      if (!statSync(absolute, { throwIfNoEntry: false })?.isFile()) {
        stale.push(`${path} — listed but gone; delete the entry`)
        continue
      }
      if (STAMP.test(readFileSync(absolute, "utf8"))) {
        stale.push(`${path} — now stamped; delete the entry so the list keeps shrinking`)
      }
    }
    expect(stale).toEqual([])
  })
})

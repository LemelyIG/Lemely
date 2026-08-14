import { readFileSync, readdirSync } from "node:fs"
import { join, relative as pathRelative } from "node:path"
import { describe, expect, it } from "vitest"
import {
  countUpProgress,
  countUpValue,
  cubicBezier,
  easeCelebrate,
  isCelebratory,
  isStreakMilestone,
  lastStreakMilestone,
} from "@/lib/celebration"

/**
 * The celebration register's rules, DESIGN.md §9.3.
 *
 * These are not tests of an animation looking nice. Each one pins a rule that,
 * if it broke, would put a number on screen that the student did not earn or
 * fire a flourish on a moment §9.3 forbids — both of which are honesty
 * defects wearing motion's clothes.
 */

describe("easing", () => {
  it("matches the endpoints and monotonicity a cubic-bezier guarantees", () => {
    expect(cubicBezier(0.22, 0.61, 0.36, 1, 0)).toBe(0)
    expect(cubicBezier(0.22, 0.61, 0.36, 1, 1)).toBe(1)
    let previous = -1
    for (let x = 0; x <= 1.0001; x += 0.05) {
      const y = cubicBezier(0.22, 0.61, 0.36, 1, x)
      expect(y).toBeGreaterThanOrEqual(previous)
      previous = y
    }
  })

  /**
   * A point derived by hand from the Bézier definition, not read off this
   * implementation — otherwise the test only asserts that the code equals
   * itself.
   *
   * For `cubic-bezier(0.22, 0.61, 0.36, 1)`, solving
   * `x(t) = 3(1-t)²t(0.22) + 3(1-t)t²(0.36) + t³ = 0.5` gives t ≈ 0.6622
   * (x(0.66) = 0.4978, x(0.67) ≈ 0.5075). At that t,
   * `y(t) = 3(1-t)²t(0.61) + 3(1-t)t²(1) + t³`
   *       = 0.13828 + 0.44439 + 0.29038 ≈ 0.8730.
   */
  it("solves a hand-derived point on --ease-out-soft", () => {
    expect(cubicBezier(0.22, 0.61, 0.36, 1, 0.5)).toBeCloseTo(0.873, 3)
  })

  /**
   * The overshoot is real and is the whole reason the count-up clamps.
   * `--ease-celebrate` is `cubic-bezier(0.18, 1.5, 0.5, 1)`; if this ever
   * stops exceeding 1 somewhere in its range, the spring has been flattened
   * and `countUpProgress`'s clamp is silently doing nothing.
   */
  it("overshoots above 1 on the celebrate curve", () => {
    const peak = Math.max(
      ...Array.from({ length: 101 }, (_, i) => easeCelebrate(i / 100)),
    )
    expect(peak).toBeGreaterThan(1)
  })

  it("clamps that overshoot out of the count-up's progress", () => {
    for (let i = 0; i <= 100; i += 1) {
      const p = countUpProgress(i / 100)
      expect(p).toBeGreaterThanOrEqual(0)
      expect(p).toBeLessThanOrEqual(1)
    }
  })
})

describe("countUpValue", () => {
  /**
   * The rule that matters most on this surface: no frame may display a figure
   * above the target. Without the clamp the celebrate curve would render
   * ~1,240 XP on the way to 1,180 — a total the account never held, on the one
   * screen whose claim is that it measures work actually done.
   */
  it("never displays a value above the target", () => {
    for (let ms = 0; ms <= 900; ms += 5) {
      expect(countUpValue(0, 1180, ms, 900)).toBeLessThanOrEqual(1180)
    }
  })

  it("never displays a value below where it started", () => {
    for (let ms = 0; ms <= 900; ms += 5) {
      expect(countUpValue(300, 1180, ms, 900)).toBeGreaterThanOrEqual(300)
    }
  })

  it("is monotonically non-decreasing while counting up", () => {
    let previous = -Infinity
    for (let ms = 0; ms <= 900; ms += 5) {
      const value = countUpValue(0, 1180, ms, 900)
      expect(value).toBeGreaterThanOrEqual(previous)
      previous = value
    }
  })

  it("lands exactly on the target at and after the duration", () => {
    expect(countUpValue(0, 1180, 900, 900)).toBe(1180)
    expect(countUpValue(0, 1180, 5000, 900)).toBe(1180)
  })

  it("starts at the origin", () => {
    expect(countUpValue(300, 1180, 0, 900)).toBe(300)
  })

  /**
   * A zero-length duration must resolve rather than divide by zero. This is
   * the path a reduced-motion caller takes if it routes through here.
   */
  it("resolves immediately on a zero duration", () => {
    expect(countUpValue(0, 1180, 0, 0)).toBe(1180)
  })

  /**
   * A decrease is not celebrated (`isCelebratory` refuses it), but the maths
   * must still be sound if some future caller animates one — a frame below the
   * target would be as wrong in that direction as above it is in this one.
   */
  it("stays within bounds when the value falls", () => {
    for (let ms = 0; ms <= 900; ms += 5) {
      const value = countUpValue(1180, 300, ms, 900)
      expect(value).toBeLessThanOrEqual(1180)
      expect(value).toBeGreaterThanOrEqual(300)
    }
  })
})

describe("isCelebratory", () => {
  it("celebrates an increase", () => {
    expect(isCelebratory(100, 140)).toBe(true)
  })

  /** §9.3: never on a failure. A value that fell is shown, not celebrated. */
  it("does not celebrate a decrease", () => {
    expect(isCelebratory(140, 100)).toBe(false)
  })

  it("does not celebrate a value that did not move", () => {
    expect(isCelebratory(140, 140)).toBe(false)
  })

  /**
   * The first observation is not an event. Without this, every mount and every
   * page refresh would stage a gain that did not happen on this visit — the
   * "celebrating engagement rather than achievement" §9.3 bans, arrived at by
   * accident rather than by design.
   */
  it("does not celebrate a first observation", () => {
    expect(isCelebratory(null, 1180)).toBe(false)
    expect(isCelebratory(null, 0)).toBe(false)
  })
})

describe("streak milestones", () => {
  it("recognises the ladder", () => {
    for (const day of [3, 7, 14, 21, 30, 50, 75, 100]) {
      expect(isStreakMilestone(day), `${day}`).toBe(true)
    }
  })

  /**
   * Day 1 is deliberately not a milestone. A badge for showing up once is the
   * clearest possible instance of §9.3's banned engagement celebration, and
   * the easiest way to breach it is to lower this bar one step at a time.
   */
  it("does not treat showing up as an achievement", () => {
    expect(isStreakMilestone(1)).toBe(false)
    expect(isStreakMilestone(2)).toBe(false)
    expect(isStreakMilestone(0)).toBe(false)
  })

  it("continues every fifty days past a hundred", () => {
    expect(isStreakMilestone(150)).toBe(true)
    expect(isStreakMilestone(200)).toBe(true)
    expect(isStreakMilestone(151)).toBe(false)
    expect(isStreakMilestone(125)).toBe(false)
  })

  it("rejects a non-integer or negative streak", () => {
    expect(isStreakMilestone(7.5)).toBe(false)
    expect(isStreakMilestone(-7)).toBe(false)
  })

  it("reports the milestone a student currently holds", () => {
    expect(lastStreakMilestone(0)).toBeNull()
    expect(lastStreakMilestone(2)).toBeNull()
    expect(lastStreakMilestone(3)).toBe(3)
    expect(lastStreakMilestone(6)).toBe(3)
    expect(lastStreakMilestone(7)).toBe(7)
    expect(lastStreakMilestone(29)).toBe(21)
    expect(lastStreakMilestone(100)).toBe(100)
    expect(lastStreakMilestone(149)).toBe(100)
    expect(lastStreakMilestone(150)).toBe(150)
    expect(lastStreakMilestone(199)).toBe(150)
  })
})

/* ── The reveal exception (P5.2) ─────────────────────────────────────────── */

/**
 * `CountUp`'s `from` prop makes a value animate on its *first* observation,
 * which the default deliberately refuses. It exists for exactly one thing:
 * §9.3's marked-paper result reveal, where the mark genuinely arrived while the
 * student watched their script being marked.
 *
 * These are source-level assertions rather than render tests because what
 * matters is not that a number animates — it is *which* number, on *which
 * path*. A reveal on the history route would animate a mark that has been true
 * since the student last closed the tab, and no render test of a single
 * component can see that distinction; it lives in which call site passes the
 * prop.
 */
describe("the count-up reveal stays on the live marking path", () => {
  const ROOT = join(import.meta.dirname, "..", "..")
  const read = (p: string) => readFileSync(join(ROOT, p), "utf8")

  it("reveals the live result and not the one opened from history", () => {
    const src = read("src/portals/student/screens/PaperResult.tsx")
    // The live path: `location.state` set by `CorrectPaper` right after marking.
    expect(src).toMatch(/<ResultHeader\s+res=\{live\}\s+reveal\s*\/>/)
    // The history path: fetched by paper id, and must not animate.
    expect(src).toMatch(/<ResultHeader\s+res=\{data\}\s*\/>/)
    expect(src).not.toMatch(/<ResultHeader\s+res=\{data\}\s+reveal/)
  })

  it("counts up only the hero mark, never an inline one", () => {
    const src = read("src/components/ui/mark-display.tsx")
    // The `reveal` branch sits inside the `size === "hero"` return, so an
    // inline mark in a history row cannot animate even if a caller asks.
    const heroStart = src.indexOf('if (size === "hero")')
    expect(heroStart).toBeGreaterThan(-1)
    const revealAt = src.indexOf("reveal ? <CountUp")
    expect(revealAt).toBeGreaterThan(heroStart)
  })

  /**
   * Every file allowed to opt a first observation into animating, and why.
   *
   * Both are the same moment: a mark that arrived while the student was
   * waiting for it, on a path that can prove the student was waiting. Both gate
   * on that proof rather than on the screen they are rendered by, which is the
   * distinction that makes the animation honest.
   *
   * A third entry needs the same proof. "It looks nicer" is not it.
   */
  const REVEAL_CALL_SITES = new Map<string, string>([
    [
      "src/components/ui/mark-display.tsx",
      "the paper result's hero mark, gated on PaperResult's `live` state",
    ],
    [
      "src/portals/student/screens/practice/PracticeResult.tsx",
      "the practice set's mark, gated on PracticeSet's `justSubmitted` state",
    ],
  ])

  it("has no unlisted call site opting a first observation into animating", () => {
    /*
     * The guard that matters. `from` is a narrow, justified exception, and the
     * failure mode is that it quietly becomes the house style — every figure in
     * the product spinning up from zero on arrival, which is the slot-machine
     * register §9.3 exists to keep out.
     */
    const offenders: string[] = []
    const walk = (dir: string): void => {
      for (const entry of readdirSync(dir, { withFileTypes: true })) {
        const full = join(dir, entry.name)
        if (entry.isDirectory()) walk(full)
        else if (/\.tsx$/.test(entry.name)) {
          const relative = pathRelative(ROOT, full).split("\\").join("/")
          if (REVEAL_CALL_SITES.has(relative)) continue
          if (relative === "src/components/ui/celebration.tsx") continue
          if (/<CountUp[^>]*\bfrom=/.test(readFileSync(full, "utf8"))) {
            offenders.push(relative)
          }
        }
      }
    }
    walk(join(ROOT, "src"))
    expect(offenders).toEqual([])
  })

  it("gates each listed call site on evidence the student was waiting", () => {
    // The allowlist is only honest if each entry actually checks something.
    // A file that reveals unconditionally would sit on the list and pass the
    // test above while animating a mark opened from history.
    const paper = read("src/components/ui/mark-display.tsx")
    expect(paper).toMatch(/reveal \? <CountUp/)

    const practice = read("src/portals/student/screens/practice/PracticeResult.tsx")
    expect(practice).toMatch(/justSubmitted \? <CountUp/)
    // And the state it reads must actually be set by the submit path.
    expect(read("src/portals/student/screens/practice/PracticeSet.tsx")).toMatch(
      /justSubmitted: true/,
    )
  })
})

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

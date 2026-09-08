import { describe, expect, it } from "vitest"
import {
  applyBackspace,
  applyDigitChange,
  applyPaste,
  digitsFromValue,
  isCodeComplete,
  joinDigits,
} from "@/components/auth/codeInputLogic"

/*
 * Review round 1, Important finding 1: the position-preserving logic behind
 * `CodeInput.tsx`, pinned directly rather than left untestable inside a
 * component this project's node-only vitest config cannot render.
 *
 * The regression this suite exists to catch: correcting a middle digit (or
 * clicking into an empty box out of typing order) must never shift the
 * digits after it, which a join()-then-resplit representation cannot
 * guarantee — see `codeInputLogic.ts`'s own module docstring for the exact
 * mechanism of the bug this module replaces.
 */

describe("digitsFromValue", () => {
  it("splits a value into one slot per box", () => {
    expect(digitsFromValue("123", 6)).toEqual(["1", "2", "3", "", "", ""])
  })

  it("pads a shorter value with empty boxes", () => {
    expect(digitsFromValue("", 6)).toEqual(["", "", "", "", "", ""])
  })
})

describe("applyDigitChange", () => {
  it("sets the box and advances focus on an actual digit", () => {
    const digits = ["", "", "", "", "", ""]
    const result = applyDigitChange(digits, 0, "7")
    expect(result.digits).toEqual(["7", "", "", "", "", ""])
    expect(result.focusIndex).toBe(1)
  })

  it("does not advance past the last box", () => {
    const digits = ["1", "2", "3", "4", "5", ""]
    const result = applyDigitChange(digits, 5, "6")
    expect(result.digits).toEqual(["1", "2", "3", "4", "5", "6"])
    expect(result.focusIndex).toBe(5)
  })

  it("does not advance when the box was cleared, not filled", () => {
    const digits = ["1", "2", "3", "", "", ""]
    const result = applyDigitChange(digits, 2, "")
    expect(result.digits).toEqual(["1", "2", "", "", "", ""])
    expect(result.focusIndex).toBe(2)
  })

  it("keeps only the last character typed (IME/mobile multi-char input)", () => {
    const digits = ["", "", "", "", "", ""]
    const result = applyDigitChange(digits, 0, "12")
    expect(result.digits[0]).toBe("2")
  })

  it("strips non-digit characters", () => {
    const digits = ["", "", "", "", "", ""]
    const result = applyDigitChange(digits, 0, "a")
    expect(result.digits[0]).toBe("")
  })

  /**
   * The regression itself. Filling every box, then re-entering box 2 as a
   * correction, must change only box 2 — the boxes after it must not shift.
   * A join()/re-split representation cannot express "box 2 changed, box 3
   * onward unchanged" once box 2 is momentarily empty; an array can.
   */
  it("correcting a middle digit leaves every other box untouched", () => {
    const digits = ["1", "2", "3", "4", "5", "6"]
    const result = applyDigitChange(digits, 2, "9")
    expect(result.digits).toEqual(["1", "2", "9", "4", "5", "6"])
  })
})

describe("applyBackspace", () => {
  it("clears the previous box and moves focus there, when the current box is empty", () => {
    const digits = ["1", "2", "", "", "", ""]
    const result = applyBackspace(digits, 2)
    expect(result).toEqual({ digits: ["1", "", "", "", "", ""], focusIndex: 1 })
  })

  it("is a no-op on the first box", () => {
    const digits = ["", "", "", "", "", ""]
    expect(applyBackspace(digits, 0)).toBeNull()
  })

  it("is a no-op when the current box already holds a digit", () => {
    const digits = ["1", "2", "3", "", "", ""]
    expect(applyBackspace(digits, 2)).toBeNull()
  })

  /**
   * The regression's other shape: backspacing box 3 (which holds "4" in a
   * fully-filled code) must not silently shift boxes 4 and 5 left. Per
   * `applyBackspace`'s own contract, backspacing a *filled* box is a no-op
   * here — the box's own `onChange` (an empty `raw`) is what clears it, via
   * `applyDigitChange`, one box at a time, with no shift either.
   */
  it("backspacing a filled middle box changes nothing here (the box's own onChange clears it)", () => {
    const digits = ["1", "2", "3", "4", "5", "6"]
    expect(applyBackspace(digits, 3)).toBeNull()
    const cleared = applyDigitChange(digits, 3, "")
    expect(cleared.digits).toEqual(["1", "2", "3", "", "5", "6"])
  })
})

describe("applyPaste", () => {
  it("distributes a pasted code across every box from position 0", () => {
    const result = applyPaste(6, "123456")
    expect(result?.digits).toEqual(["1", "2", "3", "4", "5", "6"])
    expect(result?.focusIndex).toBe(5)
  })

  it("truncates a pasted string longer than the code", () => {
    const result = applyPaste(6, "1234567890")
    expect(result?.digits).toEqual(["1", "2", "3", "4", "5", "6"])
  })

  it("strips non-digit characters before distributing", () => {
    const result = applyPaste(6, "1a2b3c4d5e6f")
    expect(result?.digits).toEqual(["1", "2", "3", "4", "5", "6"])
  })

  it("pads a short paste with empty boxes and focuses the box after the last pasted digit", () => {
    const result = applyPaste(6, "123")
    expect(result?.digits).toEqual(["1", "2", "3", "", "", ""])
    expect(result?.focusIndex).toBe(3)
  })

  it("returns null for a paste with no digit at all", () => {
    expect(applyPaste(6, "abc")).toBeNull()
  })
})

describe("isCodeComplete", () => {
  it("is true only when every box holds a character", () => {
    expect(isCodeComplete(["1", "2", "3", "4", "5", "6"])).toBe(true)
    expect(isCodeComplete(["1", "2", "3", "4", "5", ""])).toBe(false)
    expect(isCodeComplete(["", "", "", "", "", ""])).toBe(false)
  })

  it("is false for an empty array", () => {
    expect(isCodeComplete([])).toBe(false)
  })
})

describe("joinDigits", () => {
  it("joins with no separator", () => {
    expect(joinDigits(["1", "2", "3", "4", "5", "6"])).toBe("123456")
  })

  it("joins a partial code as a shorter string", () => {
    expect(joinDigits(["1", "2", "", "4", "5", "6"])).toBe("12456")
  })
})

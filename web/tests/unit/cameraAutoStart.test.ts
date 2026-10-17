import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"
import { shouldAutoStartCamera } from "@/lib/cameraAutoStart"

/*
 * A4 review (HIGH) · The camera must never be acquired without a user
 * gesture behind it.
 *
 * Before this fix, `CorrectPaper` could default `scanSource` to "camera" on
 * a coarse pointer (`defaultScanSource`) and mount `<CameraCapture>`
 * straight into its "live" phase, which calls `getUserMedia` unconditionally
 * on mount — a permission prompt (and the camera LED) firing from mere
 * navigation to the screen, with no tap behind it at all. A reflexive
 * "Block" on that prompt is sticky per-origin and effectively kills the
 * camera path for that student from then on.
 *
 * `cameraSessionKey` (`CorrectPaper.tsx`) is bumped only by an explicit tap —
 * the "Camera" entry in `SourceToggle`, or "Rescan" — and starts at 0, so
 * "was this CameraCapture mount preceded by a tap" is exactly "is
 * cameraSessionKey nonzero". See `shouldAutoStartCamera`'s own doc.
 */

describe("shouldAutoStartCamera", () => {
  it("does not auto-start on the unprompted first mount (key 0, no tap yet)", () => {
    expect(shouldAutoStartCamera(0)).toBe(false)
  })

  it("auto-starts once a tap has bumped the session key", () => {
    expect(shouldAutoStartCamera(1)).toBe(true)
    expect(shouldAutoStartCamera(2)).toBe(true)
  })
})

/*
 * Source-level checks, for the same reason `offlineClassification.test.ts`'s
 * wiring block gives — no jsdom/@testing-library in this repo, so a real
 * render-and-click proving `getUserMedia` is not called isn't available.
 * These fail if either half of the fix (the caller passing a real decision,
 * or the callee actually gating on it) regresses.
 */
describe("camera-gesture gating wiring (source-level check)", () => {
  const correctPaperSource = readFileSync(
    join(import.meta.dirname, "..", "..", "src", "portals", "student", "screens", "CorrectPaper.tsx"),
    "utf8",
  )
  const cameraCaptureSource = readFileSync(
    join(import.meta.dirname, "..", "..", "src", "components", "CameraCapture.tsx"),
    "utf8",
  )

  it("CorrectPaper passes a real autoStart decision to CameraCapture, not a hardcoded true", () => {
    expect(correctPaperSource).toMatch(
      /<CameraCapture\b[\s\S]*?autoStart=\{shouldAutoStartCamera\(cameraSessionKey\)\}/,
    )
  })

  it("CameraCapture gates its getUserMedia effect on having started, not on phase alone", () => {
    const effectStart = cameraCaptureSource.indexOf("navigator.mediaDevices")
    expect(effectStart, "expected a getUserMedia call in CameraCapture.tsx").toBeGreaterThan(-1)
    const before = cameraCaptureSource.slice(0, effectStart)
    const guardIndex = before.lastIndexOf("if (phase !== \"live\"")
    expect(guardIndex, "expected the phase guard ahead of the getUserMedia call").toBeGreaterThan(-1)
    const guardLine = cameraCaptureSource.slice(guardIndex, cameraCaptureSource.indexOf("\n", guardIndex))
    expect(guardLine).toMatch(/!started/)
  })
})

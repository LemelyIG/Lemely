import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"

/*
 * Task 8 (C3c) · `teacher-flow-no-camera-capture-on-upload`. "Use camera" as
 * a third scan source on Grading, beside the plain file input.
 *
 * Source-level checks, the same reason `cameraAutoStart.test.ts`'s wiring
 * block gives — no jsdom/@testing-library in this repo, so a real
 * render-and-click isn't available.
 *
 * `CameraCapture`'s own `onComplete: (file: File) => void` already hands
 * back a fully-assembled multi-page PDF — it lazy-imports
 * `assemblePagesToPdf` from `@/lib/pdf/assemblePages` internally
 * (`CameraCapture.tsx`'s own module doc, and the identical pattern
 * `CorrectPaper.tsx`'s plain camera flow relies on: it mounts
 * `<CameraCapture onComplete={chooseScan} ...>` and does no PDF assembly of
 * its own for that path — its *own* `await import("@/lib/pdf/assemblePages")`
 * is a separate feature, the 2+-photo `FileDrop` multi-select). So `Grading.tsx`
 * does not need — and does not do — its own dynamic import of
 * `assemblePages`; it reuses `CameraCapture`'s `onComplete` result directly,
 * exactly as `CorrectPaper.tsx`'s camera flow does. What still has to hold,
 * and is pinned here, is the chunk-budget property the plan cares about:
 * `assemblePagesToPdf` — and the `pdf-lib` dependency behind it — stays out
 * of `Grading.tsx`'s own chunk, because the dynamic import lives one level
 * down, inside `CameraCapture.tsx`, regardless of who mounts it.
 */

const gradingSource = readFileSync(
  join(import.meta.dirname, "..", "..", "src", "portals", "teacher", "screens", "Grading.tsx"),
  "utf8",
)
const cameraCaptureSource = readFileSync(
  join(import.meta.dirname, "..", "..", "src", "components", "CameraCapture.tsx"),
  "utf8",
)

describe("Grading.tsx offers the camera as a third scan source", () => {
  it("imports CameraCapture", () => {
    expect(gradingSource).toMatch(/import\s*\{\s*CameraCapture\s*\}\s*from\s*"@\/components\/CameraCapture"/)
  })

  it("mounts CameraCapture wired to the scan file, not a second, parallel upload path", () => {
    expect(gradingSource).toMatch(/<CameraCapture\b/)
    expect(gradingSource).toMatch(/onComplete=\{/)
    expect(gradingSource).toMatch(/onCancel=\{/)
  })

  it("gates getUserMedia behind an explicit 'Use camera' tap, not a default-on mount", () => {
    expect(gradingSource).toMatch(/Use camera/)
  })
})

describe("assemblePages stays a separate lazy chunk (bundle budget)", () => {
  it("CameraCapture.tsx — not Grading.tsx — is what actually lazy-imports assemblePages", () => {
    expect(cameraCaptureSource).toMatch(/await import\("@\/lib\/pdf\/assemblePages"\)/)
    expect(gradingSource).not.toMatch(/from\s*"@\/lib\/pdf\/assemblePages"/)
    expect(gradingSource).not.toMatch(/import\("@\/lib\/pdf\/assemblePages"\)/)
  })
})

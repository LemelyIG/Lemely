import { describe, expect, it } from "vitest"

import { confidenceTone } from "@/portals/teacher/screens/Review"

/*
 * US-039 finding G. `confidenceTone` used to call
 * `confidenceTierFor({ confidence: score })` -- only the score -- so no gate
 * `confidenceTierFor` might add could ever fire on this screen. These pin the
 * widened signature: a caller that has a `markerSource` can now get the
 * dedicated "not-marked" tier (rendered as the `neutral` chip tone, matching
 * `<Chip tone="neutral">`'s muted styling elsewhere on this screen), and every
 * existing single-argument call keeps behaving exactly as before.
 *
 * `ReviewQueueItemDTO` (the queue list this screen renders,
 * `lemely/web/schemas_review.py`) does not carry `markerSource` on the wire
 * today -- only `ReviewItemDetailDTO` (T-08's single-item view) does -- so the
 * queue list itself cannot supply the second argument yet. That is a
 * cross-lane gap (adding the field is a backend/DTO change), not something
 * this test can close; it pins the function so the gate is ready the moment a
 * caller can supply the data.
 */
describe("confidenceTone", () => {
  it("treats a missing score as needing attention, not confident", () => {
    expect(confidenceTone(null)).toBe("warn")
  })

  it("reuses the backend's 0.90 review floor", () => {
    expect(confidenceTone(0.95)).toBe("ok")
    expect(confidenceTone(0.9)).toBe("ok")
    expect(confidenceTone(0.85)).toBe("warn")
  })

  it("single-argument calls (every caller that predates markerSource) are unchanged", () => {
    expect(confidenceTone(0)).toBe("warn")
    expect(confidenceTone(1)).toBe("ok")
  })

  it("a not-marked score renders as the neutral tone, not ok or warn", () => {
    // The unflagged-blank shape `_build_blank_corrected` produces: score 0.0
    // with a marker source that means no marker ever looked. Without the
    // second argument this would render `warn` -- "this needs attention" --
    // for a question nobody was ever unsure about.
    expect(confidenceTone(0, "missing")).toBe("neutral")
    expect(confidenceTone(0, "dropped")).toBe("neutral")
    // Task #36: `"blank"` reaches the same branch because this guard asks
    // `markerScored` now. It used to be a hand-spelled
    // `=== "missing" || === "dropped"` here, which would have silently
    // excluded the new value and painted a question nobody read in the same
    // green as one the marker was sure about.
    expect(confidenceTone(0, "blank")).toBe("neutral")
  })

  it("a marker source without a low score does not spuriously go neutral", () => {
    expect(confidenceTone(0.95, "ai")).toBe("ok")
    expect(confidenceTone(0.5, "deterministic")).toBe("warn")
  })
})

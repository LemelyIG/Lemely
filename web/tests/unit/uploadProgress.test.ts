import { describe, expect, it } from "vitest"
import { formatMegabytes, uploadStageProgress } from "../../src/lib/uploadProgress"

/*
 * Loading/error screens PR 4 · the upload stage's byte formatting.
 *
 * This function was private inside `CorrectPaper.tsx` when it was written,
 * which is why it had no tests: there was nowhere to import it from. Byte
 * formatting is a poor thing to leave unpinned — every case below is one a
 * reader actually hits (a small scan, a phone photo, the moment the loaded
 * figure rounds up to meet the total) and every one fails silently rather
 * than loudly if the rule changes.
 */

describe("formatMegabytes", () => {
  it("uses decimal megabytes, to one place", () => {
    // 1000-based, not 1024-based: this figure sits next to the ones a
    // browser's download manager and a phone's data screen show for the same
    // file, and a mebibyte reading would be about 5% smaller than all of them.
    expect(formatMegabytes(3_200_000)).toBe("3.2 MB")
    expect(formatMegabytes(1_000_000)).toBe("1.0 MB")
  })

  it("keeps the unit for a file smaller than a megabyte", () => {
    // Deliberately not switched to KB. The total beside it is in MB, and two
    // units in one sentence ("512.0 KB of 8.1 MB") is harder to compare at a
    // glance than a small number in the same unit.
    expect(formatMegabytes(512_000)).toBe("0.5 MB")
  })

  it("renders the very start of an upload as zero rather than blank", () => {
    expect(formatMegabytes(0)).toBe("0.0 MB")
  })
})

describe("uploadStageProgress", () => {
  it("reads as 'loaded of total' when the browser reported a length", () => {
    expect(uploadStageProgress({ loaded: 3_200_000, total: 8_100_000 })).toEqual({
      current: 3_200_000,
      total: 8_100_000,
      label: "3.2 MB of 8.1 MB",
    })
  })

  it("drops the total, and says only what moved, when the length is unknown", () => {
    // `total: undefined` is what `uploadWithProgress` passes through when
    // `event.lengthComputable` is false. It must survive to the caller:
    // `StageProgressBar` keys the no-bar, no-percentage render off exactly
    // this, and inventing a total here would put back the guessed progress
    // bar that whole branch exists to avoid.
    expect(uploadStageProgress({ loaded: 1_200_000, total: undefined })).toEqual({
      current: 1_200_000,
      total: undefined,
      label: "1.2 MB uploaded",
    })
  })

  it("carries the raw byte counts through, not the rounded ones", () => {
    // The numbers matter: at 8_099_000 of 8_100_000 the two figures round to
    // the SAME label ("8.1 MB of 8.1 MB") while the upload is genuinely still
    // going. That is the collision this test exists for — if `current` were
    // fed the rounded value the bar would sit at a full 100% beside a label
    // that has not finished. An earlier draft used 8_049_999, which rounds to
    // "8.0 MB of 8.1 MB" and so never reached the case its own comment named.
    const progress = uploadStageProgress({ loaded: 8_099_000, total: 8_100_000 })
    expect(progress.label).toBe("8.1 MB of 8.1 MB")
    expect(progress.current).toBe(8_099_000)
    expect(progress.total).toBe(8_100_000)
    expect(progress.current).toBeLessThan(progress.total!)
  })

  it("treats a zero total as indeterminate rather than dividing by it", () => {
    // `StageProgressBar` renders a bar for any defined total, so a zero would
    // paint NaN% at width NaN%. Both the bar and the sentence have to agree
    // that the length is unknown.
    expect(uploadStageProgress({ loaded: 0, total: 0 })).toEqual({
      current: 0,
      total: undefined,
      label: "0.0 MB uploaded",
    })
  })
})

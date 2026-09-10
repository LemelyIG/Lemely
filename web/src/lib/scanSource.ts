/*
 * A4 · Which scan source `CorrectPaper` opens to first.
 *
 * A coarse pointer (touch — phone, tablet) means the device in the student's
 * hand almost certainly has a camera, and the workflow this screen exists for
 * is "photograph the paper you just corrected on paper" — so that device
 * opens straight to the camera rather than to a file picker built for a
 * laptop's trackpad. Pulled out of `CorrectPaper.tsx` so the branch is
 * testable without rendering the screen.
 */
export function defaultScanSource(
  matchMedia?: (query: string) => MediaQueryList,
): "file" | "camera" {
  return matchMedia?.("(pointer: coarse)").matches ? "camera" : "file"
}

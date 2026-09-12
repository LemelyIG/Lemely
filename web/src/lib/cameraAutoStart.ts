/*
 * A4 review (HIGH) · Whether mounting `<CameraCapture>` should acquire the
 * camera immediately, or wait for an explicit tap inside it.
 *
 * `CorrectPaper`'s scan source can default to "camera" on a coarse pointer
 * with no user action at all (`defaultScanSource`) — mounting straight into
 * a live camera stream there fires a permission prompt (and the camera LED)
 * from mere navigation to the screen. Every OTHER mount of `<CameraCapture>`
 * is the direct result of a tap — the "Camera" entry in `SourceToggle`, or
 * "Rescan" — and `cameraSessionKey` (bumped by both, and only by them) is
 * what tells the two apart: it starts at 0 for the unprompted default mount
 * and is never 0 again once a tap has happened.
 */
export function shouldAutoStartCamera(cameraSessionKey: number): boolean {
  return cameraSessionKey > 0
}

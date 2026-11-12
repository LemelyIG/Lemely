/*
 * Task 8 (B5b) · torch (camera flashlight) control.
 *
 * `torch` is not part of TypeScript's DOM lib on `MediaTrackCapabilities`/
 * `MediaTrackConstraintSet` (only `MediaTrackSettings` carries it) even
 * though every Chromium-based mobile browser implements it via the Media
 * Capture and Streams "Image Capture" extensions — hence the two local
 * extended interfaces below rather than a cast to `any`.
 */

interface TorchCapabilities extends MediaTrackCapabilities {
  torch?: boolean
}

interface TorchConstraintSet extends MediaTrackConstraintSet {
  torch?: boolean
}

export function torchSupported(track: MediaStreamTrack): boolean {
  const capabilities = track.getCapabilities?.() as TorchCapabilities | undefined
  return capabilities?.torch === true
}

/** Best-effort: resolves `false` (never rejects) on any failure. */
export async function setTorch(track: MediaStreamTrack, on: boolean): Promise<boolean> {
  try {
    const constraints: TorchConstraintSet = { torch: on }
    await track.applyConstraints({ advanced: [constraints] })
    return true
  } catch {
    return false
  }
}

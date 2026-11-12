import type { UploadProgress } from "@/lib/api"
import type { ProcessingStageProgress } from "@/components/ui/processing-state"

/*
 * Loading/error screens PR 4 · turning one `xhr.upload.onprogress` reading
 * into the `upload` stage's progress row.
 *
 * ── Why this is a module and not a private helper ───────────────────────────
 *
 * It began life private inside `CorrectPaper.tsx`, which cost two things.
 * It could not be unit tested, and byte formatting is exactly the kind of
 * pure function whose edge cases (zero, sub-megabyte, a total the loaded
 * figure has already rounded up to) are got wrong silently rather than
 * loudly. And the preview kit, which cannot import a non-export, carried a
 * hand-copied second implementation described in its own comment as a
 * "kept-identical reproduction" — which is a promise no code can keep. The
 * whole point of this programme has been removing second copies that drift,
 * so it would be a poor place to add one.
 *
 * A `.ts` module exporting no components also sidesteps the `only-export-
 * components` lint rule that made exporting it from the screen unattractive
 * in the first place.
 */

/**
 * "3.2 MB", decimal (1000-based) megabytes — the convention a browser's own
 * download manager and a phone's data-usage screen use, which is what a
 * reader is comparing this figure against. Not the 1024-based mebibyte: it
 * would read 5% smaller than every other number this reader sees for the
 * same file.
 */
export function formatMegabytes(bytes: number): string {
  return `${(bytes / 1_000_000).toFixed(1)} MB`
}

/**
 * `total` stays `undefined` exactly when `UploadProgress.total` is —
 * `uploadWithProgress` (`lib/api.ts`) only ever sets it from
 * `event.lengthComputable`, so an `undefined` here means the browser
 * genuinely could not tell us how large the request is, not that nobody
 * asked. `StageProgressBar` reads `total === undefined` as the honest
 * indeterminate case: the bytes moved so far, no bar, no percentage, never a
 * guessed total.
 */
export function uploadStageProgress(progress: UploadProgress): ProcessingStageProgress {
  // `total <= 0` degrades to the indeterminate render rather than dividing by
  // it: `StageProgressBar` treats any defined total as bar-worthy, so a zero
  // would paint `NaN%` at `width: NaN%`. `frameProgress` in
  // `pipelineStages.ts` rejects the same shape for the same reason ("Question
  // 3 of 0 is not a fact about anything"), and the two helpers feeding one bar
  // should not disagree about what a total is. Not reachable from
  // `xhr.upload` today, whose total is the whole multipart body and never
  // zero, but `uploadWithProgress` is exported and generic.
  //
  // The label reads off this guarded value, not the raw one, so the sentence
  // and the bar always describe the same thing — otherwise a zero total would
  // hide the bar while the label still claimed "of 0.0 MB".
  const total = progress.total !== undefined && progress.total > 0 ? progress.total : undefined
  const loaded = formatMegabytes(progress.loaded)
  const label =
    total === undefined ? `${loaded} uploaded` : `${loaded} of ${formatMegabytes(total)}`
  return { current: progress.loaded, total, label }
}

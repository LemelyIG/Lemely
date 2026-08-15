import type { WeaknessSeverity } from "@/components/ui/weakness-chip"

/*
 * The one accuracy -> tone -> severity ladder shared by every teacher surface
 * that colours a proportion (T-04's topic x student heatmap and ranked
 * topics, T-10's per-question analysis, score distribution and per-student
 * scores).
 *
 * Extracted from `ClassAnalytics.tsx` in P3.8 chunk d, where it had lived as
 * three private consts. T-10 needed the identical ladder, and this codebase
 * has already had to fix the "same label, two numbers" divergence three times
 * (D3.3, D3.4, D3.5) — a second private copy of the thresholds is how the
 * fourth one starts. **Do not inline these thresholds into a screen.** If a
 * surface needs a different ladder, that is a product decision to record, not
 * a local const to redefine.
 */

export type Tone = "ok" | "warn" | "err"

/** Accuracy (0.0-1.0) -> semantic tone. */
export function accuracyTone(accuracy: number): Tone {
  if (accuracy >= 0.75) return "ok"
  if (accuracy >= 0.5) return "warn"
  return "err"
}

/** Tone -> the `WeaknessChip` severity tier that carries the same meaning.
 * `WeaknessChip` never signals by colour alone (it renders a 1/2/3 bar count
 * plus an aria-label), which is why the tone table and this one are separate. */
export const TONE_TO_SEVERITY: Record<Tone, WeaknessSeverity> = {
  ok: "minor",
  warn: "moderate",
  err: "significant",
}

/** Tone -> background/foreground token pair. Uses the shared semantic
 * `--ok/--warn/--err` scales from index.css; there is no dedicated severity
 * scale and one must not be invented locally. */
/*
 * P4.5: `bg-ok-bg`/`bg-warn-bg`/`bg-err-bg` were three of the build-era compat
 * aliases in `index.css`, which resolve to `--ok-wash`/`--warn-wash`/
 * `--err-wash` by definition. Renaming them here is therefore a pure rename —
 * every pixel is identical — and it retires three alias call sites shared by
 * two teacher screens and three parent ones, so the parent surface inherits
 * the fix rather than repeating it.
 */
export const TONE_CLASS: Record<Tone, string> = {
  ok: "bg-ok-wash text-ok",
  warn: "bg-warn-wash text-warn",
  err: "bg-err-wash text-err",
}

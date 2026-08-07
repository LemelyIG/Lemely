/**
 * Resolves where a Playwright run's screenshot artifacts land.
 *
 * Defaults to the gitignored scratch dir `reports/.scratch` so a routine
 * `./scripts/check.sh` never overwrites a committed phase baseline — doing so
 * would destroy the very reference MISSION §11's "an unintended diff is a
 * blocker" rule compares against (a backend-only change was producing a
 * 53-file dirty tree of re-rendered PNGs before this seam existed).
 *
 * Re-baselining is the explicit act of naming the phase:
 *   LEMELY_REPORT_DIR=reports/phase-3 npm run test:e2e
 *
 * Keep the default in sync with web/scripts/audit.mjs and
 * scripts/check_ui_gates.py — all three must agree on the directory or the
 * threshold gate reads output the audit runner never wrote.
 */
import path from "node:path"
import { fileURLToPath } from "node:url"

const here = path.dirname(fileURLToPath(import.meta.url))
const repoRoot = path.resolve(here, "../..")

/** Absolute path to this run's report directory. */
export function reportDir(): string {
  const setting = process.env.LEMELY_REPORT_DIR || "reports/.scratch"
  return path.isAbsolute(setting) ? setting : path.resolve(repoRoot, setting)
}

/** Absolute path to this run's `screens/` subdirectory. */
export function screensDir(): string {
  return path.join(reportDir(), "screens")
}

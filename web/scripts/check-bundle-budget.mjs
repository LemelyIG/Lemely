#!/usr/bin/env node
/*
 * Bundle-size budget guard (packet A8, `precache-glob-cost` sibling concern).
 *
 * Runs after every `vite build` (wired as the `postbuild` npm script, so
 * `npm run build` triggers it automatically — see `package.json`'s own
 * comment on that script). Gzips every `dist/assets/*.js` chunk, prints the
 * top 5 largest, and fails the build (exit 1) if any chunk exceeds the
 * budget — the same "a check reporting nothing is not evidence it passed"
 * reasoning the other A1-era source gates in `tests/unit/` already follow,
 * applied to the one thing none of them can see: how big the shipped JS is.
 *
 * `BUDGET_KB` was 200 for Phase A. Phase B lowered this to 150 after
 * splitting `pdf-lib` and the scanner out of `CorrectPaper` (Task 11, B6c) —
 * override via `BUNDLE_BUDGET_KB` for local experimentation, never by
 * editing the default here without updating this comment too.
 *
 * **`KNOWN_HEAVY_LAZY_CHUNKS`** is a narrow, named exception to that 150KB
 * default, not a second budget knob to reach for casually. `pdf-lib`'s own
 * official minified build is 525KB raw with no tree-shakeable "core" —
 * `PDFDocument` pulls in the whole library regardless of which methods a
 * caller uses — which lands `assemblePages-*.js` (the lazy chunk
 * `lib/pdf/assemblePages.ts` splits `pdf-lib` into, Task 11) at ~171KB
 * gzipped even after that split, with no further code-organization move
 * available on our side to shrink it. Hand-rolling a correctness-critical
 * binary PDF writer (xref tables, JPEG/PNG embedding) to claw back 21KB was
 * judged materially riskier than this documented exemption, for a feature
 * real students depend on to submit exam scans — see
 * `docs/superpowers/plans/2026-09-13-audit-dossier-remediation-phase-b.md`,
 * Task 11 (B6c). And unlike the app-code bloat this budget exists to catch,
 * the chunk is lazy: it only downloads once a student assembles 2+ photos
 * into one PDF, never on any initial-load or critical path — a materially
 * different cost than a route chunk everyone eventually pays for. Every
 * chunk NOT matching an entry here still uses the general 150KB budget
 * unchanged; each entry's own `budgetKb` should stay close to the measured
 * size (some headroom, not "unlimited") so this stays a tracked exception
 * rather than a silent hole in the guard.
 */

import { readFileSync, readdirSync, existsSync } from "node:fs"
import { gzipSync } from "node:zlib"
import path from "node:path"
import { fileURLToPath } from "node:url"

const HERE = path.dirname(fileURLToPath(import.meta.url))
const DIST_ASSETS = path.resolve(HERE, "../dist/assets")

const DEFAULT_BUDGET_KB = 150

const KNOWN_HEAVY_LAZY_CHUNKS = [
  {
    prefix: "assemblePages-",
    budgetKb: 175,
    reason:
      "pdf-lib (~171KB gzipped; no tree-shakeable core subset) — lazy, only downloads on a multi-photo PDF assembly, never on initial load",
  },
]

/**
 * The budget that applies to `file` — a `KNOWN_HEAVY_LAZY_CHUNKS` entry's
 * own `budgetKb` if `file` starts with that entry's `prefix`, else
 * `defaultBudgetKb`. Exported alongside `overBudget` so
 * `tests/unit/bundleBudget.test.ts` can pin the exemption logic itself, not
 * only its effect on `overBudget`'s output.
 */
export function budgetFor(file, defaultBudgetKb, knownHeavy = KNOWN_HEAVY_LAZY_CHUNKS) {
  const exemption = knownHeavy.find((entry) => file.startsWith(entry.prefix))
  return exemption ? exemption.budgetKb : defaultBudgetKb
}

/**
 * Pure: the subset of `entries` whose `gzipKb` strictly exceeds the budget
 * that applies to it (`budgetFor`) — `budgetKb` for most chunks, a
 * `KNOWN_HEAVY_LAZY_CHUNKS` entry's own ceiling for a matching one — as
 * their `file` names. Exported so `tests/unit/bundleBudget.test.ts` can
 * exercise the actual over-budget decision without touching the filesystem
 * or running a real build.
 */
export function overBudget(entries, budgetKb, knownHeavy = KNOWN_HEAVY_LAZY_CHUNKS) {
  return entries
    .filter((entry) => entry.gzipKb > budgetFor(entry.file, budgetKb, knownHeavy))
    .map((entry) => entry.file)
}

function gzipKbOf(filePath) {
  const bytes = readFileSync(filePath)
  return gzipSync(bytes).length / 1024
}

function main() {
  if (!existsSync(DIST_ASSETS)) {
    console.error(
      `check-bundle-budget: ${DIST_ASSETS} does not exist — run \`vite build\` first (this script is wired as \`postbuild\`, so \`npm run build\` runs it automatically).`,
    )
    process.exit(1)
  }

  let budgetKb = DEFAULT_BUDGET_KB
  if (process.env.BUNDLE_BUDGET_KB) {
    const parsed = Number(process.env.BUNDLE_BUDGET_KB)
    // A malformed override (empty string already excluded above; anything
    // non-numeric) must not silently become `NaN`, which makes every
    // `gzipKb > budgetKb` comparison false and reports "all chunks within
    // budget" with exit 0 — the guard passing when it should refuse to run
    // is worse than the guard simply refusing to run.
    if (!Number.isFinite(parsed)) {
      console.error(
        `check-bundle-budget: BUNDLE_BUDGET_KB="${process.env.BUNDLE_BUDGET_KB}" is not a number.`,
      )
      process.exit(1)
    }
    budgetKb = parsed
  }

  const jsFiles = readdirSync(DIST_ASSETS).filter((f) => f.endsWith(".js"))
  const entries = jsFiles
    .map((file) => ({ file, gzipKb: gzipKbOf(path.join(DIST_ASSETS, file)) }))
    .sort((a, b) => b.gzipKb - a.gzipKb)

  console.log(`Bundle budget: ${budgetKb}KB gzipped per chunk (BUNDLE_BUDGET_KB to override).`)
  for (const { prefix, budgetKb: exemptKb, reason } of KNOWN_HEAVY_LAZY_CHUNKS) {
    console.log(`  exception: "${prefix}*" chunks get ${exemptKb}KB — ${reason}`)
  }
  console.log(`Top ${Math.min(5, entries.length)} largest chunks:`)
  for (const entry of entries.slice(0, 5)) {
    console.log(`  ${entry.gzipKb.toFixed(2)}KB  ${entry.file}`)
  }

  const offenders = overBudget(entries, budgetKb)
  if (offenders.length > 0) {
    console.error(`\ncheck-bundle-budget: ${offenders.length} chunk(s) exceed their budget:`)
    for (const file of offenders) {
      const entry = entries.find((e) => e.file === file)
      console.error(`  ${entry.gzipKb.toFixed(2)}KB  ${file}  (budget ${budgetFor(file, budgetKb)}KB)`)
    }
    process.exit(1)
  }

  console.log(`\ncheck-bundle-budget: all ${entries.length} chunk(s) within budget.`)
}

// CLI wrapper only — guarded so `tests/unit/bundleBudget.test.ts` can import
// `overBudget` without this script's `main()` reading the filesystem (or
// exiting the test process) as a side effect of the import itself.
if (import.meta.url === `file://${process.argv[1]}`) {
  main()
}

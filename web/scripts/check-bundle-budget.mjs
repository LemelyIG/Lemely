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
 * `BUDGET_KB` is 200 for Phase A. It drops to 150 in Phase B (tighter, once
 * the route-level code-splitting work planned there lands) — override via
 * `BUNDLE_BUDGET_KB` in the meantime for local experimentation, never by
 * editing the default here without updating this comment too.
 */

import { readFileSync, readdirSync, existsSync } from "node:fs"
import { gzipSync } from "node:zlib"
import path from "node:path"
import { fileURLToPath } from "node:url"

const HERE = path.dirname(fileURLToPath(import.meta.url))
const DIST_ASSETS = path.resolve(HERE, "../dist/assets")

const DEFAULT_BUDGET_KB = 200

/**
 * Pure: the subset of `entries` whose `gzipKb` strictly exceeds `budgetKb`,
 * as their `file` names. Exported so `tests/unit/bundleBudget.test.ts` can
 * exercise the actual over-budget decision without touching the filesystem
 * or running a real build.
 */
export function overBudget(entries, budgetKb) {
  return entries.filter((entry) => entry.gzipKb > budgetKb).map((entry) => entry.file)
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

  const budgetKb = process.env.BUNDLE_BUDGET_KB
    ? Number(process.env.BUNDLE_BUDGET_KB)
    : DEFAULT_BUDGET_KB

  const jsFiles = readdirSync(DIST_ASSETS).filter((f) => f.endsWith(".js"))
  const entries = jsFiles
    .map((file) => ({ file, gzipKb: gzipKbOf(path.join(DIST_ASSETS, file)) }))
    .sort((a, b) => b.gzipKb - a.gzipKb)

  console.log(`Bundle budget: ${budgetKb}KB gzipped per chunk (BUNDLE_BUDGET_KB to override).`)
  console.log(`Top ${Math.min(5, entries.length)} largest chunks:`)
  for (const entry of entries.slice(0, 5)) {
    console.log(`  ${entry.gzipKb.toFixed(2)}KB  ${entry.file}`)
  }

  const offenders = overBudget(entries, budgetKb)
  if (offenders.length > 0) {
    console.error(`\ncheck-bundle-budget: ${offenders.length} chunk(s) exceed ${budgetKb}KB gzipped:`)
    for (const file of offenders) {
      const entry = entries.find((e) => e.file === file)
      console.error(`  ${entry.gzipKb.toFixed(2)}KB  ${file}`)
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

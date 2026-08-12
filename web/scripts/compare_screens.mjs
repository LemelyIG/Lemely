#!/usr/bin/env node
/**
 * Cross-phase screenshot regression compare (P3.10 chunk e2b).
 *
 * MISSION §11 requires each phase to diff its screenshot corpus against the
 * committed baselines: "an unintended diff is a blocker, an intended diff is
 * re-baselined with a note in the phase report." Nothing in this repo did
 * that comparison — `audit.mjs` and `screenshots.spec.ts` only ever *wrote*
 * PNGs, so the baselines were decoration.
 *
 * **This is deliberately NOT a `scripts/check.sh` gate.** A per-run gate over
 * screenshots re-fails on every intended visual change, which trains everyone
 * to ignore it (the same way the pre-P3.1b baseline gate became vacuous by
 * overwriting the very files it compared against — D3.2). It is an explicit
 * phase act: you run it when re-baselining, read the three lists, and account
 * for each entry in the phase report.
 *
 * Usage:
 *   node scripts/compare_screens.mjs [--baseline DIR] [--candidate DIR]
 *                                    [--json PATH] [--fail-on-change]
 * Defaults: baseline `reports/phase-2.5/screens`, candidate
 * `${LEMELY_REPORT_DIR:-reports/.scratch}/screens`, both repo-relative.
 *
 * Output is three lists — added / removed / changed — plus an unchanged
 * count, written to stdout and (as JSON) to `--json`. Exit code is 0 unless
 * `--fail-on-change` is passed, because "changed" is a question for a human,
 * not an assertion.
 *
 * ── Comparison method and its stated threshold ────────────────────────────
 * `sharp` (already a devDependency — no new package) decodes both PNGs to raw
 * RGB. Alpha is dropped: these are opaque full-page captures, and a decoder
 * difference in a fully-transparent region is not a visual regression.
 *   1. Different dimensions -> `changed`, reason `dimensions`. No pixel pass;
 *      there is no meaningful per-pixel correspondence between two sizes.
 *   2. Same dimensions -> per-pixel. A pixel counts as differing when any
 *      channel differs by more than CHANNEL_TOLERANCE (8/255 ~ 3%). That
 *      absorbs PNG encoder and font-rasterisation noise, which moves
 *      antialiased edge pixels by a few levels between runs, without
 *      absorbing a real colour-token change (the smallest step in DESIGN.md's
 *      scales is far larger than 3%).
 *   3. A file is `changed` when differing pixels exceed PIXEL_RATIO_THRESHOLD
 *      (0.1%) of the image. Below that it is `unchanged`, but the ratio is
 *      still reported so a sub-threshold drift is visible rather than hidden.
 *
 * Both thresholds are deliberately loose enough to survive re-rendering and
 * tight enough that a moved element, a changed token, or new copy trips them.
 * They are stated here, in the JSON output, and in the printed summary so a
 * report can quote them instead of implying a pixel-exact comparison.
 *
 * ── What this cannot tell you ─────────────────────────────────────────────
 * It compares *files*, so a screen the candidate run never captured shows up
 * as `removed` exactly like a deleted screen. The Phase-2.5 baseline holds
 * only 6 screen ids / 39 PNGs (G-04, S-06, S-10, S-14, S-15, S-17) while a
 * Phase-3 corpus covers the whole teacher/parent surface, so the overwhelming
 * majority of a Phase-3 run is legitimately `added`. Read `removed` closely:
 * for this pair it means a screen that used to be audited and no longer is.
 */

import fs from "node:fs/promises"
import path from "node:path"
import process from "node:process"
import { fileURLToPath } from "node:url"

import sharp from "sharp"

const scriptDir = path.dirname(fileURLToPath(import.meta.url))
const repoRoot = path.resolve(scriptDir, "..", "..")

/** Max per-channel delta (0-255) still considered "the same pixel". */
const CHANNEL_TOLERANCE = 8
/** Fraction of differing pixels above which a file is reported `changed`. */
const PIXEL_RATIO_THRESHOLD = 0.001

function parseArgs(argv) {
  const args = {
    baseline: "reports/phase-2.5/screens",
    candidate: path.join(process.env.LEMELY_REPORT_DIR || "reports/.scratch", "screens"),
    json: null,
    failOnChange: false,
  }
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i]
    if (arg === "--baseline") args.baseline = argv[++i]
    else if (arg === "--candidate") args.candidate = argv[++i]
    else if (arg === "--json") args.json = argv[++i]
    else if (arg === "--fail-on-change") args.failOnChange = true
    else throw new Error(`Unknown argument: ${arg}`)
  }
  return args
}

/** Every `*.png` under `dir`, as paths relative to `dir` (so `G-04/default--380.png`). */
async function listPngs(dir) {
  const out = []
  async function walk(current, prefix) {
    let entries
    try {
      entries = await fs.readdir(current, { withFileTypes: true })
    } catch (err) {
      if (err.code === "ENOENT") return
      throw err
    }
    for (const entry of entries) {
      const rel = prefix ? path.join(prefix, entry.name) : entry.name
      if (entry.isDirectory()) await walk(path.join(current, entry.name), rel)
      else if (entry.isFile() && entry.name.endsWith(".png")) out.push(rel)
    }
  }
  await walk(dir, "")
  return out.sort()
}

/** Decode to raw RGB (alpha dropped — see the header's method note). */
async function decode(file) {
  const { data, info } = await sharp(file)
    .removeAlpha()
    .raw()
    .toBuffer({ resolveWithObject: true })
  return { data, width: info.width, height: info.height, channels: info.channels }
}

/**
 * Compare one relative path present in both corpora. Returns a verdict object
 * carrying the measured ratio even when the verdict is `unchanged`, so a
 * sub-threshold drift is reported rather than silently swallowed.
 */
async function compareOne(rel, baselineDir, candidateDir) {
  const [base, cand] = await Promise.all([
    decode(path.join(baselineDir, rel)),
    decode(path.join(candidateDir, rel)),
  ])

  if (base.width !== cand.width || base.height !== cand.height) {
    return {
      file: rel,
      verdict: "changed",
      reason: "dimensions",
      baseline: `${base.width}x${base.height}`,
      candidate: `${cand.width}x${cand.height}`,
    }
  }

  let differing = 0
  const len = Math.min(base.data.length, cand.data.length)
  for (let i = 0; i < len; i += base.channels) {
    for (let c = 0; c < base.channels; c += 1) {
      if (Math.abs(base.data[i + c] - cand.data[i + c]) > CHANNEL_TOLERANCE) {
        differing += 1
        break
      }
    }
  }

  const total = base.width * base.height
  const ratio = total === 0 ? 0 : differing / total
  return {
    file: rel,
    verdict: ratio > PIXEL_RATIO_THRESHOLD ? "changed" : "unchanged",
    reason: "pixels",
    dimensions: `${base.width}x${base.height}`,
    differingPixels: differing,
    totalPixels: total,
    ratio: Number(ratio.toFixed(6)),
  }
}

function screenIdOf(rel) {
  const [head] = rel.split(path.sep)
  return head
}

/** Group a file list by screen id so a 39-vs-200-file diff reads as screens. */
function summariseByScreen(files) {
  const byScreen = new Map()
  for (const file of files) {
    const id = screenIdOf(file)
    byScreen.set(id, (byScreen.get(id) || 0) + 1)
  }
  return [...byScreen.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([id, count]) => `${id} (${count})`)
}

async function main() {
  const args = parseArgs(process.argv.slice(2))
  const baselineDir = path.resolve(repoRoot, args.baseline)
  const candidateDir = path.resolve(repoRoot, args.candidate)

  const [baselineFiles, candidateFiles] = await Promise.all([
    listPngs(baselineDir),
    listPngs(candidateDir),
  ])

  if (baselineFiles.length === 0) {
    throw new Error(
      `No PNGs under the baseline dir ${baselineDir}. Refusing to report ` +
        `"everything added" against an empty or wrong baseline.`,
    )
  }
  if (candidateFiles.length === 0) {
    throw new Error(
      `No PNGs under the candidate dir ${candidateDir}. Run the audit first ` +
        `(cd web && LEMELY_REPORT_DIR=<dir> npm run audit).`,
    )
  }

  const baselineSet = new Set(baselineFiles)
  const candidateSet = new Set(candidateFiles)
  const added = candidateFiles.filter((f) => !baselineSet.has(f))
  const removed = baselineFiles.filter((f) => !candidateSet.has(f))
  const common = baselineFiles.filter((f) => candidateSet.has(f))

  const comparisons = []
  for (const rel of common) {
    comparisons.push(await compareOne(rel, baselineDir, candidateDir))
  }
  const changed = comparisons.filter((c) => c.verdict === "changed")
  const unchanged = comparisons.filter((c) => c.verdict === "unchanged")

  const report = {
    baseline: path.relative(repoRoot, baselineDir),
    candidate: path.relative(repoRoot, candidateDir),
    thresholds: {
      channelTolerance: CHANNEL_TOLERANCE,
      pixelRatioThreshold: PIXEL_RATIO_THRESHOLD,
      note:
        "A pixel differs when any RGB channel differs by more than " +
        `${CHANNEL_TOLERANCE}/255; a file is 'changed' when more than ` +
        `${PIXEL_RATIO_THRESHOLD * 100}% of its pixels differ. Alpha is ` +
        "dropped. This is not a pixel-exact comparison.",
    },
    counts: {
      baselineFiles: baselineFiles.length,
      candidateFiles: candidateFiles.length,
      added: added.length,
      removed: removed.length,
      changed: changed.length,
      unchanged: unchanged.length,
    },
    added,
    removed,
    changed,
    unchanged,
  }

  console.log(`[compare] baseline  ${report.baseline} — ${baselineFiles.length} PNGs`)
  console.log(`[compare] candidate ${report.candidate} — ${candidateFiles.length} PNGs`)
  console.log(`[compare] ${report.thresholds.note}`)
  console.log("")
  console.log(`[compare] ADDED    ${added.length} — ${summariseByScreen(added).join(", ") || "none"}`)
  console.log(
    `[compare] REMOVED  ${removed.length} — ${summariseByScreen(removed).join(", ") || "none"}`,
  )
  for (const file of removed) console.log(`[compare]   removed: ${file}`)
  console.log(`[compare] CHANGED  ${changed.length} of ${common.length} shared files`)
  for (const c of changed) {
    const detail =
      c.reason === "dimensions"
        ? `dimensions ${c.baseline} -> ${c.candidate}`
        : `${c.differingPixels}/${c.totalPixels} px (${(c.ratio * 100).toFixed(3)}%)`
    console.log(`[compare]   changed: ${c.file} — ${detail}`)
  }
  console.log(`[compare] UNCHANGED ${unchanged.length}`)

  if (args.json) {
    const jsonPath = path.resolve(repoRoot, args.json)
    // Every path here resolves against the repo root, so a caller who passes a
    // `web/`-relative `../reports/...` (the natural mistake when running this
    // from `web/`, where every other npm script lives) escapes the repo and
    // writes to its parent. That happened once and left a stray file outside
    // the working tree; MISSION §5 says never touch anything outside the repo,
    // so refuse rather than create the directory.
    if (jsonPath !== repoRoot && !jsonPath.startsWith(repoRoot + path.sep)) {
      throw new Error(
        `--json ${args.json} resolves to ${jsonPath}, outside the repo at ` +
          `${repoRoot}. Paths are repo-relative regardless of your cwd — drop the "../".`,
      )
    }
    await fs.mkdir(path.dirname(jsonPath), { recursive: true })
    await fs.writeFile(jsonPath, `${JSON.stringify(report, null, 2)}\n`)
    console.log(`[compare] wrote ${path.relative(repoRoot, jsonPath)}`)
  }

  if (args.failOnChange && changed.length > 0) {
    console.error(`[compare] FAIL — ${changed.length} changed file(s) and --fail-on-change was set.`)
    process.exit(1)
  }
}

main().catch((err) => {
  console.error(`[compare] ${err.stack || err.message}`)
  process.exit(1)
})

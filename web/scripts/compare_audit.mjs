#!/usr/bin/env node
/**
 * Before/after comparison for a pair of `scripts/audit.mjs` report directories
 * (P6.3's confirm round).
 *
 * The audit writes `lighthouse/_summary.json` and `axe/_summary.json` per run,
 * but nothing reads two runs against each other, so "did that change help?" was
 * being answered by eye across two directories of 41 JSON files. This prints
 * the per-route deltas and, more importantly, the routes present in one run and
 * missing from the other — a route that failed and produced no entry is
 * otherwise indistinguishable from one that was never in the registry.
 *
 * Usage:
 *   node scripts/compare_audit.mjs <before-dir> <after-dir>
 *
 * Paths are resolved from the repo root, not the cwd, so it behaves the same
 * whether it is run from `web/` or from the root.
 */
import { readFileSync, existsSync } from "node:fs"
import { join, isAbsolute } from "node:path"

const REPO_ROOT = join(import.meta.dirname, "..", "..")

function resolveDir(arg) {
  return isAbsolute(arg) ? arg : join(REPO_ROOT, arg)
}

function readSummary(dir, kind) {
  const path = join(dir, kind, "_summary.json")
  if (!existsSync(path)) return null
  return JSON.parse(readFileSync(path, "utf8"))
}

/** `[{slug, scores}]` -> `Map<slug, scores>`. */
function bySlug(rows) {
  const out = new Map()
  for (const row of rows ?? []) out.set(row.slug, row)
  return out
}

const [beforeArg, afterArg] = process.argv.slice(2)
if (!beforeArg || !afterArg) {
  console.error("usage: node scripts/compare_audit.mjs <before-dir> <after-dir>")
  process.exit(2)
}

const beforeDir = resolveDir(beforeArg)
const afterDir = resolveDir(afterArg)

const CATEGORIES = ["performance", "accessibility", "best-practices", "seo"]

const lhBefore = bySlug(readSummary(beforeDir, "lighthouse"))
const lhAfter = bySlug(readSummary(afterDir, "lighthouse"))

console.log(`before: ${beforeDir}  (${lhBefore.size} routes)`)
console.log(`after:  ${afterDir}  (${lhAfter.size} routes)`)

// Coverage first. A route that vanished between runs is the finding most
// easily mistaken for an improvement, because its bad score simply stops
// being printed.
const onlyBefore = [...lhBefore.keys()].filter((s) => !lhAfter.has(s))
const onlyAfter = [...lhAfter.keys()].filter((s) => !lhBefore.has(s))
if (onlyBefore.length) console.log(`\n!! in before only (no after result): ${onlyBefore.join(", ")}`)
if (onlyAfter.length) console.log(`\n!! in after only (no before result): ${onlyAfter.join(", ")}`)

console.log("\n── Lighthouse category deltas (after - before), non-zero only ──")
const shared = [...lhAfter.keys()].filter((s) => lhBefore.has(s)).sort()
const totals = Object.fromEntries(CATEGORIES.map((c) => [c, { sum: 0, n: 0 }]))
let changedRoutes = 0

for (const slug of shared) {
  const b = lhBefore.get(slug).scores ?? {}
  const a = lhAfter.get(slug).scores ?? {}
  const parts = []
  for (const cat of CATEGORIES) {
    if (typeof b[cat] !== "number" || typeof a[cat] !== "number") continue
    const delta = a[cat] - b[cat]
    totals[cat].sum += delta
    totals[cat].n += 1
    if (delta !== 0) parts.push(`${cat} ${b[cat]}->${a[cat]} (${delta > 0 ? "+" : ""}${delta})`)
  }
  if (parts.length) {
    changedRoutes += 1
    console.log(`  ${slug.padEnd(34)} ${parts.join("  ")}`)
  }
}
if (changedRoutes === 0) console.log("  (no category score changed on any shared route)")

console.log("\n── Mean delta per category ──")
for (const cat of CATEGORIES) {
  const { sum, n } = totals[cat]
  if (n === 0) continue
  console.log(`  ${cat.padEnd(16)} ${(sum / n >= 0 ? "+" : "")}${(sum / n).toFixed(2)}  over ${n} routes`)
}

/**
 * Routes below the §11 floors in the after run, using `check_ui_gates.py`'s
 * OWN rules rather than a uniform floor invented here.
 *
 * The performance floor is **student routes only**, and that is deliberate:
 * MISSION §11 only ever claimed "performance >= 80 on the student routes", and
 * the gate's docstring is explicit that inventing a floor for teacher routes
 * would be dishonest. A comparison tool that applied 80 everywhere would report
 * three teacher routes as gate failures the gate does not claim — so it is
 * mirrored here, and teacher performance is printed separately as information.
 */
const STUDENT_PATH_PREFIX = "/student"
function isStudentRoute(row) {
  const path = row.path
  if (path != null) return path === STUDENT_PATH_PREFIX || path.startsWith(`${STUDENT_PATH_PREFIX}/`)
  return row.slug.startsWith("student-")
}

console.log("\n── After-run gate failures (check_ui_gates.py rules: a11y 95 all, perf 80 student-only) ──")
const belowFloor = []
const teacherPerf = []
for (const slug of [...lhAfter.keys()].sort()) {
  const row = lhAfter.get(slug)
  const s = row.scores ?? {}
  if (typeof s.accessibility === "number" && s.accessibility < 95) {
    belowFloor.push(`  ${slug.padEnd(34)} accessibility ${s.accessibility}`)
  }
  if (typeof s.performance !== "number" || s.performance >= 80) continue
  if (isStudentRoute(row)) belowFloor.push(`  ${slug.padEnd(34)} performance ${s.performance}`)
  else teacherPerf.push(`  ${slug.padEnd(34)} performance ${s.performance}`)
}
console.log(belowFloor.length ? belowFloor.join("\n") : "  (none)")
if (teacherPerf.length) {
  console.log("\n  non-student routes under 80 (NOT gated — reported, never invented into a failure):")
  console.log(teacherPerf.join("\n"))
}

/**
 * axe serious+critical per route.
 *
 * The `_summary.json` rows carry `counts` (by impact), not the violations
 * themselves — the rule ids and node counts live in the per-route file. Both
 * are read: the summary for the comparison, the per-route file for the
 * by-rule breakdown that says *what* is still failing rather than how many.
 */
function axeSerious(dir) {
  const rows = readSummary(dir, "axe")
  if (!rows) return null
  const out = new Map()
  for (const row of rows) {
    const counts = row.counts ?? {}
    const serious = (counts.serious ?? 0) + (counts.critical ?? 0)
    if (serious > 0) out.set(row.slug, serious)
  }
  return out
}

/** Rule id -> node count, over the serious/critical violations of one run. */
function axeRuleBreakdown(dir, slugs) {
  const rules = new Map()
  for (const slug of slugs) {
    const path = join(dir, "axe", `${slug}.json`)
    if (!existsSync(path)) continue
    const report = JSON.parse(readFileSync(path, "utf8"))
    for (const v of report.violations ?? []) {
      if (v.impact !== "serious" && v.impact !== "critical") continue
      rules.set(v.id, (rules.get(v.id) ?? 0) + (v.nodes?.length ?? 1))
    }
  }
  return rules
}

const axeB = axeSerious(beforeDir)
const axeA = axeSerious(afterDir)
if (axeB && axeA) {
  const total = (m) => [...m.values()].reduce((n, v) => n + v, 0)
  console.log(
    `\n── axe serious/critical: before ${total(axeB)} across ${axeB.size} routes, ` +
      `after ${total(axeA)} across ${axeA.size} routes ──`,
  )
  const slugs = [...new Set([...axeB.keys(), ...axeA.keys()])].sort()
  for (const slug of slugs) {
    const b = axeB.get(slug) ?? 0
    const a = axeA.get(slug) ?? 0
    console.log(`  ${slug.padEnd(34)} ${b} -> ${a}${b === a ? "" : "   <-- changed"}`)
  }

  const rules = axeRuleBreakdown(afterDir, [...axeA.keys()])
  if (rules.size) {
    console.log("\n  after-run serious/critical by rule (node count):")
    for (const [id, n] of [...rules].sort((x, y) => y[1] - x[1])) {
      console.log(`    ${id.padEnd(24)} ${n}`)
    }
  }
}

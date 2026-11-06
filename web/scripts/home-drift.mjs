#!/usr/bin/env node
/*
 * Drift gate (docs/superpowers/specs/2026-11-06-portal-shell-design.md §4 and
 * 2026-11-06-student-home-overview-design.md §4).
 *
 *   node scripts/home-drift.mjs [--scene a,b] [--windows 390,1440] [--themes light]
 *                               [--record-baseline] [--selftest] [--list]
 *
 * Needs a fresh `npm run build` (the app side is `vite preview` of dist/).
 * Writes reports/.scratch/drift/<timestamp>/{<key>.a.png,<key>.b.png,<key>.diff.png,report.json,report.md}.
 * Baselines for before-vs-after scenes live in reports/.scratch/drift/baseline/.
 * Exit 0 only when every selected scene key passes (see compare.mjs verdict).
 */
import { execFileSync } from "node:child_process"
import fs from "node:fs"
import os from "node:os"
import path from "node:path"
import { chromium } from "@playwright/test"
import { HEIGHT, SCENES, THEMES, WINDOWS } from "./drift/scenes.mjs"
import {
  KIT_PORT,
  KIT_PROBES,
  REPO_DIR,
  SELECTORS,
  capture,
  contentBox,
  matchContentWidth,
  pinContentWidth,
  openApp,
  openPreview,
  stableShot,
  startServers,
  verifyRunningKit,
} from "./drift/harness.mjs"
import { diffPngs, exitCodeFor, findJustification, judge, readJustifications, verdict } from "./drift/compare.mjs"
import { PNG } from "pngjs"

function parseArgs(argv) {
  const out = { scene: [], windows: null, themes: null, recordBaseline: false, recordProvenance: false, selftest: false, list: false }
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]
    if (a === "--scene") out.scene = argv[++i].split(",")
    else if (a === "--windows") out.windows = argv[++i].split(",").map(Number)
    else if (a === "--themes") out.themes = argv[++i].split(",")
    else if (a === "--record-baseline") out.recordBaseline = true
    else if (a === "--record-provenance") out.recordProvenance = true
    else if (a === "--selftest") out.selftest = true
    else if (a === "--list") out.list = true
    else throw new Error(`unknown argument ${a}`)
  }
  return out
}

const args = parseArgs(process.argv.slice(2))
const DRIFT_DIR = path.join(REPO_DIR, "reports", ".scratch", "drift")
const BASELINE_DIR = path.join(DRIFT_DIR, "baseline")
const PROVENANCE_FILE = "provenance.json"

function expand() {
  const keys = []
  for (const scene of SCENES) {
    if (args.scene.length && !args.scene.some((p) => scene.id.startsWith(p))) continue
    for (const width of args.windows ?? scene.windows ?? WINDOWS) {
      if (scene.windows && !scene.windows.includes(width)) continue
      for (const theme of args.themes ?? scene.themes ?? THEMES) {
        keys.push({ scene, width, theme, key: `${scene.id}@${width}@${theme}` })
      }
    }
  }
  return keys
}

/**
 * The x the baseline's content was rastered at when its sidecar does not record
 * one (baselines recorded before the field existed): the merged `develop`
 * shell laid the teacher content out at x=324 (252 px sidebar + 72 px page
 * padding) from 820 px up. Fallback only; a sidecar with `originX` wins.
 */
const LEGACY_ORIGIN_X = 324
const LEGACY_ORIGIN_MIN_WIDTH = 820
const SIDEBAR_COLUMN_WIDTH = 1248

async function shoot(browser, side, item, meta = {}) {
  const { scene, width, theme } = item
  const { contentWidth: targetWidth } = meta
  const beforeVsAfter = side === "app" && scene.kind === "before-vs-after"
  const height = HEIGHT[width] ?? 900
  const opened =
    side === "preview"
      ? await openPreview(browser, { width, height, theme, preview: scene.preview })
      : await openApp(browser, { width, height, theme, app: scene.app })
  try {
    const selector = SELECTORS[side === "preview" ? "preview" : "app"]
    if (scene.capture === "content" && targetWidth !== undefined) {
      // Below the sidebar breakpoint the window keeps its native width (viewport
      // media queries must equal the baseline's) and the content selector is
      // pinned to the baseline's width; from 1248 up (and preview-vs-app) the
      // window is resized until the content matches.
      const ok =
        beforeVsAfter && width < SIDEBAR_COLUMN_WIDTH
          ? await pinContentWidth(opened.page, selector, targetWidth)
          : await matchContentWidth(opened.page, selector, targetWidth, height)
      if (!ok) throw new Error(`${item.key}: could not match content width ${targetWidth}`)
    }
    const width_ = scene.capture === "content" ? (await contentBox(opened.page, selector)).width : undefined
    const report = {}
    const png = await capture(opened.page, {
      capture: scene.capture,
      selector,
      neutral: scene.kind === "before-vs-after",
      // See snapContentOrigin: the baseline's recorded content x, else the legacy constant.
      originX: beforeVsAfter ? (meta.originX ?? (width >= LEGACY_ORIGIN_MIN_WIDTH ? LEGACY_ORIGIN_X : undefined)) : undefined,
      report,
    })
    return { png, contentWidth: width_, contentX: report.x }
  } finally {
    await opened.context.close()
  }
}

function gitHead() {
  return execFileSync("git", ["rev-parse", "HEAD"], { cwd: REPO_DIR, encoding: "utf8" }).trim()
}

/** True when tracked files have uncommitted changes (untracked files are ignored on purpose). */
function gitDirty() {
  return execFileSync("git", ["status", "--porcelain", "--untracked-files=no"], { cwd: REPO_DIR, encoding: "utf8" }).trim() !== ""
}

/** The per-key sidecar: content width plus the capturing checkout. */
function sidecarFor(shot) {
  return JSON.stringify({ contentWidth: shot.contentWidth ?? null, originX: shot.contentX ?? null, sha: gitHead(), dirty: gitDirty() })
}

/** Summarise the per-key sidecars: which SHAs are present, and how many keys lack one. */
function scanSidecars(baselineDir) {
  const shas = {}
  let missing = 0
  let dirty = 0
  for (const f of fs.existsSync(baselineDir) ? fs.readdirSync(baselineDir) : []) {
    if (!f.endsWith(".json") || f === PROVENANCE_FILE) continue
    const meta = JSON.parse(fs.readFileSync(path.join(baselineDir, f), "utf8"))
    if (!meta.sha) missing++
    else shas[meta.sha] = (shas[meta.sha] ?? 0) + 1
    if (meta.dirty) dirty++
  }
  return { shas, missing, dirty }
}

/** Write the global provenance summary, derived from the per-key sidecars (the source of truth). */
function writeProvenance(baselineDir, extra = {}) {
  const provenance = { ...scanSidecars(baselineDir), recordedAt: new Date().toISOString(), ...extra }
  fs.mkdirSync(baselineDir, { recursive: true })
  fs.writeFileSync(path.join(baselineDir, PROVENANCE_FILE), JSON.stringify(provenance, null, 2) + "\n")
  return provenance
}

function printProvenance(baselineDir) {
  const file = path.join(baselineDir, PROVENANCE_FILE)
  if (!fs.existsSync(file)) {
    console.log(`baseline provenance: none recorded (${path.relative(REPO_DIR, file)} missing)`)
    return
  }
  const p = scanSidecars(baselineDir)
  const list = Object.entries(p.shas).map(([sha, n]) => `${sha.slice(0, 8)} x${n}`).join(", ")
  console.log(`baseline provenance (per-key sidecars): ${list || "none"}; missing sha: ${p.missing}; dirty: ${p.dirty}`)
}

/**
 * Compare one scene key and return its report row. A failure to capture (for
 * example the content width cannot be matched) fails that one key and does not
 * abort the run.
 */
async function compareItem(browser, item, { baselineDir, runDir, table }) {
  const { scene, key } = item
  try {
    let a
    let b
    if (scene.kind === "preview-vs-app") {
      a = await shoot(browser, "preview", item)
      b = await shoot(browser, "app", item, { contentWidth: a.contentWidth })
    } else {
      const basePng = path.join(baselineDir, `${key}.png`)
      if (!fs.existsSync(basePng) && scene.baselineless?.includes(item.width)) {
        // A state `develop` could not show at this width (its sidebar column was
        // still up at 1100 px, so there was no drawer): capture the new side only
        // so the picture is on file; nothing to diff against.
        const only = await shoot(browser, "app", item, {})
        fs.writeFileSync(path.join(runDir, `${key}.b.png`), only.png)
        return { key, diff: 0, pct: 0, outcome: "pass", reason: "log-only: no develop baseline at this width (captured, not compared)", justification: null }
      }
      if (!fs.existsSync(basePng)) throw new Error(`no baseline; run with --record-baseline on merged develop`)
      const meta = JSON.parse(fs.readFileSync(path.join(baselineDir, `${key}.json`), "utf8"))
      if (!meta.sha) throw new Error(`baseline sidecar ${key}.json has no sha; re-record with --record-baseline`)
      a = { png: fs.readFileSync(basePng) }
      b = await shoot(browser, "app", item, { contentWidth: meta.contentWidth ?? undefined, originX: meta.originX ?? undefined })
    }
    fs.writeFileSync(path.join(runDir, `${key}.a.png`), a.png)
    fs.writeFileSync(path.join(runDir, `${key}.b.png`), b.png)
    const result = diffPngs(a.png, b.png, path.join(runDir, `${key}.diff.png`))
    const justification = findJustification(key, table)
    const { outcome, reason } = judge(result, justification, scene.rule ?? "gate")
    return { key, ...result, outcome, reason, justification }
  } catch (error) {
    return { key, diff: null, pct: 0, outcome: "fail", reason: `capture failed: ${error.message}`, justification: null }
  }
}

function assertEqual(actual, expected, label) {
  if (actual !== expected) throw new Error(`selftest: ${label}: expected ${expected}, got ${actual}`)
}

function selftestVerdicts() {
  const approved = { justification: "design A rule X", approved: "yes" }
  const pending = { justification: "design A rule X", approved: "no" }
  const unmarked = { justification: "design A rule X" }
  assertEqual(verdict({ diff: 0, pct: 0 }, null), "pass", "0 px")
  assertEqual(verdict({ diff: 10, pct: 14.9 }, approved, "gate"), "pass-justified", "gate <=15% approved")
  assertEqual(verdict({ diff: 10, pct: 15 }, approved, "gate"), "pass-justified", "gate exactly 15% approved")
  assertEqual(verdict({ diff: 10, pct: 15.1 }, approved, "gate"), "fail", "gate >15% approved")
  assertEqual(verdict({ diff: 10, pct: 60 }, approved, "log"), "pass-justified", "log has no cap")
  assertEqual(verdict({ diff: 10, pct: 1 }, null, "gate"), "fail", "unjustified")
  assertEqual(verdict({ diff: 10, pct: 1 }, { justification: "  " }, "gate"), "fail", "blank justification")
  assertEqual(verdict({ diff: 10, pct: 1 }, pending, "gate"), "fail", "gate justified, approval pending")
  assertEqual(verdict({ diff: 10, pct: 60 }, pending, "log"), "fail", "log justified, approval pending")
  assertEqual(verdict({ diff: 10, pct: 1 }, unmarked, "log"), "fail", "approved key missing")
  if (!/pending/.test(judge({ diff: 10, pct: 1 }, pending, "log").reason)) {
    throw new Error("selftest: an unapproved justified diff must say approval is pending")
  }
  console.log("selftest verdict table passed")
}

async function selftestEndToEnd(browser, width = 1440) {
  // The real before-vs-after path against a temp baseline: record, mutate a
  // copy, compare, and require a red verdict and exit code 1. The real
  // baseline directory is never written.
  const scene = SCENES.find((s) => s.id === "teacher-home-content")
  if (!scene) throw new Error("selftest: scene teacher-home-content not found")
  const item = { scene, width, theme: "light", key: `teacher-home-content@${width}@light` }
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "drift-selftest-"))
  const baselineDir = path.join(tmp, "baseline")
  const runDir = path.join(tmp, "run")
  fs.mkdirSync(baselineDir, { recursive: true })
  fs.mkdirSync(runDir, { recursive: true })
  try {
    const shot = await shoot(browser, "app", item)
    fs.writeFileSync(path.join(baselineDir, `${item.key}.png`), shot.png)
    fs.writeFileSync(path.join(baselineDir, `${item.key}.json`), sidecarFor(shot))
    const clean = await compareItem(browser, item, { baselineDir, runDir, table: {} })
    assertEqual(clean.outcome, "pass", `unmodified baseline (${clean.reason}; ${clean.diff} px)`)
    assertEqual(exitCodeFor([clean]), 0, "exit code, unmodified baseline")
    // A sidecar without a sha has no provable origin: that key must fail.
    const sidecarPath = path.join(baselineDir, `${item.key}.json`)
    const sidecarText = fs.readFileSync(sidecarPath, "utf8")
    const { sha: _sha, dirty: _dirty, ...bare } = JSON.parse(sidecarText)
    fs.writeFileSync(sidecarPath, JSON.stringify(bare))
    const noSha = await compareItem(browser, item, { baselineDir, runDir, table: {} })
    assertEqual(noSha.outcome, "fail", "sidecar without sha")
    if (!/no sha/.test(noSha.reason)) throw new Error("selftest: a sha-less sidecar must say it has no sha")
    fs.writeFileSync(sidecarPath, sidecarText)
    // Mutate the temp baseline: paint a 60x60 block magenta.
    const png = PNG.sync.read(fs.readFileSync(path.join(baselineDir, `${item.key}.png`)))
    for (let y = 0; y < 60; y++) {
      for (let x = 0; x < 60; x++) {
        const i = (y * png.width + x) * 4
        png.data[i] = 255
        png.data[i + 1] = 0
        png.data[i + 2] = 255
        png.data[i + 3] = 255
      }
    }
    fs.writeFileSync(path.join(baselineDir, `${item.key}.png`), PNG.sync.write(png))
    const mutated = await compareItem(browser, item, { baselineDir, runDir, table: {} })
    console.log(`selftest mutated baseline: ${mutated.diff} px, ${mutated.outcome} (${mutated.reason})`)
    assertEqual(mutated.outcome, "fail", "mutated baseline, no justification")
    assertEqual(exitCodeFor([mutated]), 1, "exit code, mutated baseline")
    // Same mutation, justified but not approved: still red; approved: green.
    const entry = { [item.key]: { justification: "selftest", approved: "no" } }
    const pending = await compareItem(browser, item, { baselineDir, runDir, table: entry })
    assertEqual(pending.outcome, "fail", "mutated baseline, approval pending")
    entry[item.key].approved = "yes"
    const ok = await compareItem(browser, item, { baselineDir, runDir, table: entry })
    assertEqual(ok.outcome, "pass-justified", "mutated baseline, approved")
    assertEqual(exitCodeFor([ok]), 0, "exit code, approved")
    console.log(`selftest end-to-end passed at ${width}px`)
  } finally {
    fs.rmSync(tmp, { recursive: true, force: true })
  }
}

async function selftestForeignKit() {
  const foreign = async () => new Response("/* another worktree */", { status: 200 })
  let message = ""
  try {
    await verifyRunningKit(foreign)
  } catch (error) {
    message = error.message
  }
  if (!message.includes(String(KIT_PORT)) || (message.match(/hash [0-9a-f]{12}/g) ?? []).length !== 2 * KIT_PROBES.length) {
    throw new Error(`selftest: a foreign kit server was not rejected with both hashes: ${message || "no error"}`)
  }
  assertEqual(await verifyRunningKit(async () => Promise.reject(new Error("refused"))), false, "free port")
  console.log("selftest foreign kit check passed")
}

function selftestEmptySelection() {
  assertEqual(exitCodeFor([]), 1, "exit code, empty selection")
  assertEqual(exitCodeFor([{ outcome: "pass" }]), 0, "exit code, one pass")
  assertEqual(exitCodeFor([{ outcome: "pass" }, { outcome: "fail" }]), 1, "exit code, one fail")
  console.log("selftest empty selection passed")
}

async function selftestContentIgnoresChrome(browser) {
  // Content mode: a fixed or sticky element outside the content selector must
  // not reach the capture, and a real content change must still differ.
  const context = await browser.newContext({ viewport: { width: 390, height: 600 } })
  try {
    const page = await context.newPage()
    const html = (chrome, body) =>
      `<body style="margin:0;background:#fff"><div style="position:fixed;bottom:0;left:0;right:0;height:60px;background:${chrome}"></div>` +
      `<div style="position:sticky;top:0;height:40px;background:${chrome}"></div>` +
      `<main id="m" style="height:560px;background:${body}"><div style="margin:10px;height:80px;border-radius:24px;background:#fff;border-left:4px solid #036"></div></main></body>`
    const shoot = async (chrome, body, lift = 0) => {
      await page.setContent(html(chrome, body))
      if (lift) await page.addStyleTag({ content: `#m { transform: translateY(${lift}px); }` })
      return capture(page, { capture: "content", selector: "#m" })
    }
    const base = await shoot("#f00", "#0a0")
    const chromeOnly = await shoot("#00f", "#0a0")
    const contentChanged = await shoot("#f00", "#a0a")
    // The same content a fraction of a pixel lower (a shell change that moves the
    // content origin by a rem fraction) must still compare as 0 px.
    const shifted = await shoot("#f00", "#0a0", 0.3)
    const fraction = diffPngs(base, shifted, path.join(DRIFT_DIR, "selftest", "fraction.diff.png"))
    if (fraction.diff !== 0) throw new Error(`selftest: a fractional content origin leaked into the capture (${fraction.diff} px)`)
    // A capture moved sideways (a shell that shifts the content column) against
    // an unshifted baseline is judged on content, not position: same content 0
    // px, changed content still differs.
    const baseX = {}
    await page.setContent(html("#f00", "#0a0"))
    await page.addStyleTag({ content: `#m { width: 300px; }` })
    const sidewaysBase = await capture(page, { capture: "content", selector: "#m", report: baseX })
    const sideways = async (body) => {
      await page.setContent(html("#f00", body))
      await page.addStyleTag({ content: `#m { position: relative; left: 37px; width: 300px; }` })
      return capture(page, { capture: "content", selector: "#m", originX: baseX.x })
    }
    const widthPinned = async (body) => {
      await page.setContent(html("#f00", body))
      await page.addStyleTag({ content: `#m { width: 100px; }` })
      if (!(await pinContentWidth(page, "#m", 300))) throw new Error("selftest: pinContentWidth did not reach the target width")
      return capture(page, { capture: "content", selector: "#m", originX: baseX.x })
    }
    const sidewaysSame = diffPngs(sidewaysBase, await sideways("#0a0"), path.join(DRIFT_DIR, "selftest", "sideways.diff.png"))
    const sidewaysChanged = diffPngs(sidewaysBase, await sideways("#a0a"), path.join(DRIFT_DIR, "selftest", "sideways-changed.diff.png"))
    if (sidewaysSame.diff !== 0) throw new Error(`selftest: a horizontal shift leaked into the capture (${sidewaysSame.diff} px)`)
    if (sidewaysChanged.diff === 0) throw new Error("selftest: a shifted capture with changed content did not differ")
    const pinnedSame = diffPngs(sidewaysBase, await widthPinned("#0a0"), path.join(DRIFT_DIR, "selftest", "pinned.diff.png"))
    const pinnedChanged = diffPngs(sidewaysBase, await widthPinned("#a0a"), path.join(DRIFT_DIR, "selftest", "pinned-changed.diff.png"))
    if (pinnedSame.diff !== 0) throw new Error(`selftest: a pinned width differed from the same-width baseline (${pinnedSame.diff} px)`)
    if (pinnedChanged.diff === 0) throw new Error("selftest: a pinned-width capture with changed content did not differ")
    console.log(`selftest sideways/pinned passed (shift ${sidewaysSame.diff} px, shift+change ${sidewaysChanged.diff} px, pinned ${pinnedSame.diff} px, pinned+change ${pinnedChanged.diff} px)`)
    const same = diffPngs(base, chromeOnly, path.join(DRIFT_DIR, "selftest", "chrome.diff.png"))
    const changed = diffPngs(base, contentChanged, path.join(DRIFT_DIR, "selftest", "content.diff.png"))
    if (same.diff !== 0) throw new Error(`selftest: a fixed/sticky element outside the content leaked into the capture (${same.diff} px)`)
    if (changed.diff === 0) throw new Error("selftest: a real content change did not differ in content mode")
    console.log(`selftest content ignores chrome passed (chrome change ${same.diff} px, content change ${changed.diff} px)`)
  } finally {
    await context.close()
  }
}

async function selftestStableShot(browser) {
  // A static page must settle: the stabiliser returns a buffer equal to a fresh one.
  const context = await browser.newContext({ viewport: { width: 400, height: 300 } })
  try {
    const page = await context.newPage()
    await page.setContent("<body style='margin:0;background:#def'><h1>static</h1></body>")
    const taken = []
    const settled = await stableShot(page, async () => {
      const png = await page.screenshot()
      taken.push(png)
      return png
    })
    if (taken.length < 2 || !taken[taken.length - 1].equals(taken[taken.length - 2]) || !settled.equals(taken[taken.length - 1])) {
      throw new Error("selftest: stableShot did not return identical consecutive buffers for a static page")
    }
    // And an ever-changing page must fail loudly, not pass.
    let n = 0
    let message = ""
    try {
      await stableShot(page, async () => Buffer.from(String(n++)), { intervalMs: 1, maxTries: 4 })
    } catch (error) {
      message = error.message
    }
    if (!/unstable capture/.test(message)) throw new Error("selftest: a never-stable capture did not fail")
    console.log(`selftest stable capture passed (${taken.length} shots to settle)`)
  } finally {
    await context.close()
  }
}

async function runSelftest(browser) {
  selftestVerdicts()
  selftestEmptySelection()
  await selftestForeignKit()
  // Proves the gate can go red: the same preview twice must be 0 px, and the
  // same preview with its title recoloured must fail.
  const item = {
    scene: { id: "selftest", kind: "preview-vs-app", capture: "frame", preview: { state: "populated" } },
    width: 1440,
    theme: "light",
    key: "selftest@1440@light",
  }
  const a = await shoot(browser, "preview", item)
  const b = await shoot(browser, "preview", item)
  const same = diffPngs(a.png, b.png, path.join(DRIFT_DIR, "selftest", "same.diff.png"))
  const perturbed = await shoot(browser, "preview", {
    ...item,
    scene: {
      ...item.scene,
      preview: {
        state: "populated",
        act: (page) => page.addStyleTag({ content: ".as-title{color:rgb(255 0 0)!important}" }),
      },
    },
  })
  const changed = diffPngs(a.png, perturbed.png, path.join(DRIFT_DIR, "selftest", "changed.diff.png"))
  console.log(`selftest same: ${same.diff} px; perturbed: ${changed.diff} px`)
  if (same.diff !== 0) throw new Error("selftest: identical captures differ, the capture is not deterministic")
  if (verdict(changed, null) !== "fail") throw new Error("selftest: a recoloured title did not fail the gate")
  await selftestStableShot(browser)
  await selftestContentIgnoresChrome(browser)
  const realBaseline = path.join(BASELINE_DIR, "teacher-home-content@1440@light.png")
  const before = fs.existsSync(realBaseline) ? fs.readFileSync(realBaseline) : null
  await selftestEndToEnd(browser)
  // Content mode must still go red on a real content mutation at the phone width,
  // where the fixed bottom tabs and the shell bar are hidden before capture.
  await selftestEndToEnd(browser, 390)
  const after = fs.existsSync(realBaseline) ? fs.readFileSync(realBaseline) : null
  if (before && (!after || !before.equals(after))) throw new Error("selftest: the real baseline was modified")
  console.log("selftest passed")
}

async function main() {
  const items = expand()
  if (!items.length && !args.recordProvenance && !args.selftest) {
    console.error(
      `no scenes matched: --scene ${args.scene.join(",") || "(all)"} --windows ${
        args.windows?.join(",") ?? "(default)"
      } --themes ${args.themes?.join(",") ?? "(default)"}`,
    )
    process.exitCode = 1
    return
  }
  if (args.list) {
    for (const i of items) console.log(i.key)
    return
  }
  if (args.recordProvenance) {
    const p = writeProvenance(BASELINE_DIR, { note: "summary rescanned from per-key sidecars" })
    console.log(`baseline provenance written: ${JSON.stringify(p.shas)} missing ${p.missing}`)
    return
  }
  const needKit = args.selftest || items.some((i) => i.scene.kind === "preview-vs-app")
  const servers = await startServers({ needKit })
  let browser
  const runDir = path.join(DRIFT_DIR, new Date().toISOString().replace(/[:.]/g, "-"))
  const rows = []
  try {
    browser = await chromium.launch()
    fs.mkdirSync(runDir, { recursive: true })
    fs.mkdirSync(BASELINE_DIR, { recursive: true })
    if (args.selftest) {
      await runSelftest(browser)
      return
    }
    if (args.recordBaseline) {
      for (const item of items) {
        if (item.scene.kind !== "before-vs-after") continue
        if (item.scene.baselineless?.includes(item.width)) continue
        const shot = await shoot(browser, "app", item)
        fs.writeFileSync(path.join(BASELINE_DIR, `${item.key}.png`), shot.png)
        fs.writeFileSync(path.join(BASELINE_DIR, `${item.key}.json`), sidecarFor(shot))
        console.log(`baseline ${item.key}`)
      }
      const p = writeProvenance(BASELINE_DIR)
      console.log(`baseline provenance written: ${JSON.stringify(p.shas)} missing ${p.missing} dirty ${p.dirty}`)
      return
    }
    if (items.some((i) => i.scene.kind === "before-vs-after")) printProvenance(BASELINE_DIR)
    const table = readJustifications()
    for (const item of items) {
      const row = await compareItem(browser, item, { baselineDir: BASELINE_DIR, runDir, table })
      rows.push(row)
      const pct = row.diff === null ? "     n/a" : row.pct.toFixed(3).padStart(8)
      const note = row.outcome === "fail" ? `  [${row.reason}]` : ""
      console.log(`${row.outcome.padEnd(14)} ${pct}%  ${row.key}${note}`)
    }
  } finally {
    await browser?.close()
    servers.stop()
  }
  fs.writeFileSync(path.join(runDir, "report.json"), JSON.stringify(rows, null, 2))
  const md = [
    "| Scene | Difference | % pixels | Justification | Approved | Verdict |",
    "|---|---|---|---|---|---|",
    ...rows
      .filter((r) => r.diff === null || r.diff > 0)
      .map(
        (r) =>
          `| ${r.key} | ${r.justification?.difference ?? "(none)"} | ${r.pct.toFixed(2)} | ${
            r.justification?.justification ?? "(missing)"
          } | ${r.justification?.approved ?? "no"} | ${r.outcome}: ${r.reason} |`,
      ),
  ].join("\n")
  fs.writeFileSync(path.join(runDir, "report.md"), md + "\n")
  console.log(`report: ${path.relative(REPO_DIR, runDir)}`)
  const failed = rows.filter((r) => r.outcome === "fail")
  if (failed.length) console.error(`${failed.length} scene key(s) failed`)
  process.exitCode = exitCodeFor(rows)
}

main().catch((error) => {
  console.error(error)
  process.exitCode = 1
})

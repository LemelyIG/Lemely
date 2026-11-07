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
import { createHash } from "node:crypto"
import fs from "node:fs"
import os from "node:os"
import path from "node:path"
import { fileURLToPath } from "node:url"
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
  horizontalOverflow,
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
 * one (baselines recorded before the field existed); a sidecar with `originX`
 * wins. Content x of the merged develop teacher shell (aa533580): <main> was
 * `px-page-mobile md:px-page-tablet lg:px-[72px]` (16/20/72), sidebar column 252px from 820.
 */
function legacyOriginX(width) {
  const sidebar = width >= 820 ? 252 : 0
  const gutter = width >= 1024 ? 72 : width >= 768 ? 20 : 16
  return sidebar + gutter
}
const SCROLLBAR_WIDTH = 15
// The guard covers below 820 only: no baseline sidecar exists at 820-1023 (WINDOWS are 390, 768, 1024, 1440, 1920), so the shell relation there is unproven.
/** Below 820 the legacy content is the window less the scrollbar and both gutters; anything else makes the fallback origin unprovable. */
function assertLegacyBelowSidebar(width, contentWidth) {
  if (width >= 820 || contentWidth === undefined) return
  const gutter = width >= 768 ? 20 : 16
  const expected = width - SCROLLBAR_WIDTH - 2 * gutter
  if (expected !== contentWidth) {
    throw new Error(`legacy originX at ${width}px: expected content ${expected}px (window - scrollbar - 2 x ${gutter}px gutter), baseline is ${contentWidth}px; re-record the baseline with --record-baseline`)
  }
}
const SIDEBAR_COLUMN_WIDTH = 1248
const OVERFLOW_MIN_WIDTH = 820
/** Content scenes also get an unpinned natural-width capture at these windows (human review). */
const NATURAL_CAPTURE_WIDTHS = [768, 1024]

async function shoot(browser, side, item, meta = {}) {
  const { scene, width, theme } = item
  const { contentWidth: targetWidth, natural = false } = meta
  const beforeVsAfter = side === "app" && scene.kind === "before-vs-after"
  const height = HEIGHT[width] ?? 900
  const opened =
    side === "preview"
      ? await openPreview(browser, { width, height, theme, preview: scene.preview })
      : await openApp(browser, { width, height, theme, app: scene.app })
  try {
    const selector = SELECTORS[side === "preview" ? "preview" : "app"]
    // App side only: the preview kit is a static mock with its own fixed layout; the shipped shell is what must not scroll sideways.
    if (side === "app" && width >= OVERFLOW_MIN_WIDTH && width < SIDEBAR_COLUMN_WIDTH) {
      // Natural layout, before any pin: the pin below proves content equivalence
      // at the baseline width, not that 820-1247 lays out without a sideways scroll.
      const over = await horizontalOverflow(opened.page, selector)
      if (over.length) throw new Error(`horizontal overflow at ${width}px: ${over.join("; ")}`)
    }
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
    const box_ = scene.capture === "content" ? await contentBox(opened.page, selector) : undefined
    const width_ = box_?.width
    let originX
    if (beforeVsAfter && !natural) {
      originX = meta.originX
      if (originX === undefined) {
        assertLegacyBelowSidebar(width, targetWidth)
        originX = legacyOriginX(width)
        if (scene.capture === "content" && originX + width_ > width) {
          throw new Error(`legacy originX ${originX} + content ${width_} exceeds the ${width}px viewport; re-record the baseline with --record-baseline`)
        }
      }
    }
    const { png, x } = await capture(opened.page, {
      capture: scene.capture,
      selector,
      neutral: scene.kind === "before-vs-after",
      // See snapContentOrigin: the baseline's recorded content x, else the legacy constant.
      originX,
    })
    return { png, contentWidth: width_, contentHeight: box_?.height, contentX: x }
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

const HARNESS_DIR = path.dirname(fileURLToPath(import.meta.url))

/** sha256 over the harness source (home-drift.mjs and every file in drift/, by name), so a baseline names the capture code that made it. */
function harnessHashOf(files) {
  const h = createHash("sha256")
  for (const [name, buffer] of [...files].sort(([a], [b]) => (a < b ? -1 : 1))) {
    h.update(`${name}\0`)
    h.update(buffer)
    h.update("\0")
  }
  return h.digest("hex")
}

function harnessHash() {
  const files = [["home-drift.mjs", fs.readFileSync(path.join(HARNESS_DIR, "home-drift.mjs"))]]
  const dir = path.join(HARNESS_DIR, "drift")
  for (const f of fs.readdirSync(dir)) {
    if (fs.statSync(path.join(dir, f)).isFile()) files.push([`drift/${f}`, fs.readFileSync(path.join(dir, f))])
  }
  return harnessHashOf(files)
}

/** The commit that last touched the harness files in the checkout that holds them; DRIFT_HARNESS_SHA names it when the files were copied into another checkout. */
function harnessSha() {
  if (process.env.DRIFT_HARNESS_SHA) return process.env.DRIFT_HARNESS_SHA
  return execFileSync("git", ["log", "-1", "--format=%H", "--", "web/scripts/home-drift.mjs", "web/scripts/drift"], { cwd: REPO_DIR, encoding: "utf8" }).trim()
}

/** True when the harness files differ from HEAD in the checkout holding them (skip-worktree copies read as clean, so record from a clean checkout). */
function harnessDirty() {
  return execFileSync("git", ["status", "--porcelain", "--untracked-files=no", "--", "web/scripts/home-drift.mjs", "web/scripts/drift"], { cwd: REPO_DIR, encoding: "utf8" }).trim() !== ""
}

/** The per-key sidecar: content size, origin, the capturing checkout and the harness that captured it. */
function sidecarFor(shot) {
  return JSON.stringify({
    contentWidth: shot.contentWidth ?? null,
    contentHeight: shot.contentHeight ?? null,
    originX: shot.contentX ?? null,
    sha: gitHead(),
    dirty: gitDirty(),
    harnessSha: harnessSha(),
    harnessDirty: harnessDirty(),
    harnessHash: harnessHash(),
  })
}

/** Summarise the per-key sidecars: which SHAs are present, and how many keys lack one. */
function scanSidecars(baselineDir) {
  const shas = {}
  const harnessShas = {}
  const harnessHashes = {}
  let harnessDirtyCount = 0
  let missing = 0
  let dirty = 0
  for (const f of fs.existsSync(baselineDir) ? fs.readdirSync(baselineDir) : []) {
    if (!f.endsWith(".json") || f === PROVENANCE_FILE) continue
    const meta = JSON.parse(fs.readFileSync(path.join(baselineDir, f), "utf8"))
    if (!meta.sha) missing++
    else shas[meta.sha] = (shas[meta.sha] ?? 0) + 1
    if (meta.dirty) dirty++
    if (meta.harnessDirty) harnessDirtyCount++
    const hs = meta.harnessSha ?? "none"
    const hh = meta.harnessHash ?? "none"
    harnessShas[hs] = (harnessShas[hs] ?? 0) + 1
    harnessHashes[hh] = (harnessHashes[hh] ?? 0) + 1
  }
  return { shas, missing, dirty, harnessShas, harnessHashes, harnessDirty: harnessDirtyCount }
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

function capturedRow(key, artifact, why = "no baseline at this width") {
  return {
    key,
    diff: null,
    pct: null,
    outcome: "captured",
    reason: `captured, not compared: ${why} - needs human review`,
    artifact,
    justification: null,
  }
}

/** Unpinned natural-width capture of a content scene: logged for a human, never diffed. */
async function captureNatural(browser, item, { runDir }) {
  const key = `${item.key}#natural`
  try {
    const only = await shoot(browser, "app", item, { natural: true })
    const artifact = path.join(runDir, `${item.key}.natural.png`)
    fs.writeFileSync(artifact, only.png)
    return capturedRow(key, artifact, "natural unpinned width, real layout")
  } catch (error) {
    return { key, diff: null, pct: null, outcome: "fail", reason: `capture failed: ${error.message}`, justification: null }
  }
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
        // still up at 1100 px, so there was no drawer): capture the new side only.
        // Nothing was diffed, so this is "captured", never a pass.
        const only = await shoot(browser, "app", item, {})
        const artifact = path.join(runDir, `${key}.b.png`)
        fs.writeFileSync(artifact, only.png)
        return capturedRow(key, artifact)
      }
      if (!fs.existsSync(basePng)) throw new Error(`no baseline; run with --record-baseline on merged develop`)
      const meta = JSON.parse(fs.readFileSync(path.join(baselineDir, `${key}.json`), "utf8"))
      if (!meta.sha) throw new Error(`baseline sidecar ${key}.json has no sha; re-record with --record-baseline`)
      a = { png: fs.readFileSync(basePng) }
      b = await shoot(browser, "app", item, {
        contentWidth: meta.contentWidth ?? undefined,
        originX: meta.originX ?? undefined,
      })
    }
    fs.writeFileSync(path.join(runDir, `${key}.a.png`), a.png)
    fs.writeFileSync(path.join(runDir, `${key}.b.png`), b.png)
    const result = diffPngs(a.png, b.png, path.join(runDir, `${key}.diff.png`))
    const justification = findJustification(key, table)
    const { outcome, reason } = judge(result, justification, scene.rule ?? "gate")
    return { key, ...result, outcome, reason, justification }
  } catch (error) {
    return { key, diff: null, pct: null, outcome: "fail", reason: `capture failed: ${error.message}`, justification: null }
  }
}

function assertEqual(actual, expected, label) {
  if (actual !== expected) throw new Error(`selftest: ${label}: expected ${expected}, got ${actual}`)
}

function selftestLegacyOrigin() {
  const want = { 390: 16, 768: 20, 819: 20, 820: 272, 1023: 272, 1024: 324, 1440: 324 }
  for (const [w, x] of Object.entries(want)) assertEqual(legacyOriginX(Number(w)), x, `legacyOriginX(${w})`)
  assertLegacyBelowSidebar(390, 390 - 15 - 32)
  assertLegacyBelowSidebar(768, 768 - 15 - 40)
  assertLegacyBelowSidebar(1440, undefined)
  let threw = false
  try {
    assertLegacyBelowSidebar(768, 700)
  } catch {
    threw = true
  }
  if (!threw) throw new Error("selftest: a sub-820 legacy baseline with the wrong content width was not rejected")
  console.log("selftest legacy origin passed")
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
    // A baselineless key with no baseline file is "captured", never "pass"; the
    // same missing baseline on a key that does not list the width fails.
    const missing = path.join(baselineDir, `${item.key}.png`)
    fs.rmSync(missing)
    const listed = { ...item, scene: { ...scene, baselineless: [width] } }
    const captured = await compareItem(browser, listed, { baselineDir, runDir, table: {} })
    assertEqual(captured.outcome, "captured", `baselineless key (${captured.reason})`)
    assertEqual(captured.diff, null, "captured diff is null")
    assertEqual(exitCodeFor([captured]), 1, "exit code, captured only")
    const unlisted = await compareItem(browser, { ...item, scene: { ...scene, baselineless: [width + 1] } }, { baselineDir, runDir, table: {} })
    assertEqual(unlisted.outcome, "fail", "missing baseline, width not listed baselineless")
    const none = await compareItem(browser, item, { baselineDir, runDir, table: {} })
    assertEqual(none.outcome, "fail", "missing baseline, no baselineless list")
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
  assertEqual(exitCodeFor([{ outcome: "captured" }]), 1, "exit code, only captured rows (nothing compared)")
  assertEqual(exitCodeFor([{ outcome: "captured" }, { outcome: "pass" }]), 0, "exit code, captured plus a pass")
  assertEqual(exitCodeFor([{ outcome: "captured" }, { outcome: "fail" }]), 1, "exit code, captured plus a fail")
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
      `<main id="m" style="height:560px;background:${body}"><div style="margin:10px;height:80px;border-radius:24px;background:#fff;border-left:4px solid #036"></div></main><div style="height:80px"></div></body>`
    const shoot = async (chrome, body, lift = 0) => {
      await page.setContent(html(chrome, body))
      if (lift) await page.addStyleTag({ content: `#m { transform: translateY(${lift}px); }` })
      return (await capture(page, { capture: "content", selector: "#m" })).png
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
    await page.setContent(html("#f00", "#0a0"))
    await page.addStyleTag({ content: `#m { width: 300px; }` })
    const baseShot = await capture(page, { capture: "content", selector: "#m" })
    const sidewaysBase = baseShot.png
    const baseX = baseShot.x
    const sideways = async (body) => {
      await page.setContent(html("#f00", body))
      await page.addStyleTag({ content: `#m { position: relative; left: 37px; width: 300px; }` })
      return (await capture(page, { capture: "content", selector: "#m", originX: baseX })).png
    }
    const widthPinned = async (body) => {
      await page.setContent(html("#f00", body))
      await page.addStyleTag({ content: `#m { width: 100px; }` })
      if (!(await pinContentWidth(page, "#m", 300))) throw new Error("selftest: pinContentWidth did not reach the target width")
      return (await capture(page, { capture: "content", selector: "#m", originX: baseX })).png
    }
    const sidewaysSame = diffPngs(sidewaysBase, await sideways("#0a0"), path.join(DRIFT_DIR, "selftest", "sideways.diff.png"))
    const sidewaysChanged = diffPngs(sidewaysBase, await sideways("#a0a"), path.join(DRIFT_DIR, "selftest", "sideways-changed.diff.png"))
    if (sidewaysSame.diff !== 0) throw new Error(`selftest: a horizontal shift leaked into the capture (${sidewaysSame.diff} px)`)
    if (sidewaysChanged.diff === 0) throw new Error("selftest: a shifted capture with changed content did not differ")
    const pinnedSame = diffPngs(sidewaysBase, await widthPinned("#0a0"), path.join(DRIFT_DIR, "selftest", "pinned.diff.png"))
    const pinnedChanged = diffPngs(sidewaysBase, await widthPinned("#a0a"), path.join(DRIFT_DIR, "selftest", "pinned-changed.diff.png"))
    // Painted-extent capture height: the capture is as tall as what paints, compare pads the
    // shorter side with magenta, so extra painted content is a diff and empty trailing space is not.
    const para = (w) => `<p style="position:absolute;top:520px;left:0;width:${w}px;margin:0;font:16px/20px monospace;color:#000">aaa bbb ccc</p>`
    const lastCard = `<div style="position:absolute;top:511px;left:20px;width:100px;height:48px;background:#fff;border-bottom:1px solid #888;box-shadow:0 2px 8px rgba(0,0,0,.4)"></div>`
    const extent = async (boxHeight, appendHtml = "", css = "") => {
      await page.setContent(html("#f00", "#0a0"))
      await page.addStyleTag({ content: `#m { width: 300px; height: ${boxHeight}px !important; position: relative; } ${css}` })
      if (appendHtml) await page.$eval("#m", (el, h) => el.insertAdjacentHTML("beforeend", h), appendHtml)
      return (await capture(page, { capture: "content", selector: "#m", neutral: true, originX: baseX })).png
    }
    const dpx = (x, y, name) => diffPngs(x, y, path.join(DRIFT_DIR, "selftest", `${name}.diff.png`)).diff
    const plain = await extent(560, para(300))
    const cardBase = await extent(560, lastCard + para(300))
    const heightResults = {
      "(a) taller empty trailing space": [dpx(plain, await extent(600, para(300)), "ext-a"), true],
      "(b) absolutely positioned element below the old bottom (grows scrollHeight)": [dpx(plain, await extent(560, para(300) + `<div style="position:absolute;top:566px;left:0;width:40px;height:8px;background:#a0f"></div>`), "ext-b"), false],
      "(c) ::after on a descendant below the old bottom (grows scrollHeight)": [dpx(plain, await extent(560, para(300), "#m > div::after { content: ''; position: absolute; top: 562px; left: 0; width: 60px; height: 6px; background: #0ff; }"), "ext-c"), false],
      "(d) text wrapping onto extra lines": [dpx(plain, await extent(560, para(40)), "ext-d"), false],
      "(e) card border and shadow in both (same height)": [dpx(cardBase, await extent(560, lastCard + para(300)), "ext-e1"), true],
      "(e) card border and shadow in both (taller root)": [dpx(cardBase, await extent(600, lastCard + para(300)), "ext-e2"), true],
    }
    // Isolating the walks scrollHeight cannot see. Shadows are ink overflow: a card that ends
    // above the root bottom, its shadow crossing it, leaves scrollHeight at 560, so only the
    // descendant walk's shadow reach lengthens the capture. Cropping both captures to the root
    // bottom proves the whole difference lies in the rows below it (0 px with shadowReach removed).
    const shadowCard = (shadow) => `<div style="position:absolute;top:520px;left:20px;width:100px;height:39px;background:#fff;border-bottom:1px solid #888;box-shadow:${shadow}"></div>`
    const withShadow = await extent(560, para(300) + shadowCard("0 40px 2px -4px rgba(0,0,0,.5)"))
    const noShadow = await extent(560, para(300) + shadowCard("none"))
    const cropTo = (buffer, rows) => {
      const src = PNG.sync.read(buffer)
      const out = new PNG({ width: src.width, height: rows })
      PNG.bitblt(src, out, 0, 0, src.width, rows, 0, 0)
      return PNG.sync.write(out)
    }
    heightResults["(i) shadow-only difference crossing the root bottom (scrollHeight unchanged)"] = [dpx(noShadow, withShadow, "ext-i"), false]
    const shadowCropped = dpx(cropTo(noShadow, 560), cropTo(withShadow, 560), "ext-i-cropped")
    if (shadowCropped !== 0) throw new Error(`selftest: (i) the shadow-only difference is not confined to the rows below the root bottom (${shadowCropped} px)`)
    // Text-shadow and outline reach likewise are ink overflow.
    // Text-shadow: identical glyphs at the same place (line ends at 558); the variant's shadow is
    // offset 30px so it paints only below the root bottom. Crop control: 0 px inside the root rows.
    const shadowText = (shadow) => `<p style="position:absolute;top:538px;left:0;width:300px;margin:0;font:16px/20px monospace;color:#000;text-shadow:${shadow}">aaa</p>`
    const textPlain = await extent(560, shadowText("none"))
    const textShadowed = await extent(560, shadowText("0 30px 0 #000"))
    heightResults["(i) text-shadow painting only below the root bottom"] = [dpx(textPlain, textShadowed, "ext-i-text"), false]
    const textCropped = dpx(cropTo(textPlain, 560), cropTo(textShadowed, 560), "ext-i-text-cropped")
    if (textCropped !== 0) throw new Error(`selftest: (i) the text-shadow difference is not confined to the rows below the root bottom (${textCropped} px)`)
    // Outline: a ring surrounds its box, so an opaque cover (neutral colour) over the root rows hides the
    // ring's upper part and only the bottom edge of the ring shows below row 560. Crop control: 0 px.
    const outlineBox = (outline) => `<div style="position:absolute;top:540px;left:20px;width:60px;height:19px;z-index:1;outline:${outline}"></div><div style="position:absolute;top:0;left:0;width:300px;height:560px;z-index:2;background:rgb(255 0 255)"></div>`
    const outlinePlain = await extent(560, outlineBox("none"))
    const outlined = await extent(560, outlineBox("6px solid #00f"))
    heightResults["(i) outline ring showing only below the root bottom"] = [dpx(outlinePlain, outlined, "ext-i-outline"), false]
    const outlineCropped = dpx(cropTo(outlinePlain, 560), cropTo(outlined, 560), "ext-i-outline-cropped")
    if (outlineCropped !== 0) throw new Error(`selftest: (i) the outline difference is not confined to the rows below the root bottom (${outlineCropped} px)`)
    // Layout overflow also grows scrollHeight in Chrome (transforms, text overflowing a fixed-height box),
    // so these go red through every walk; the walks are belt and braces for them.
    heightResults["(ii) transformed descendant painting below the root bottom"] = [dpx(plain, await extent(560, para(300) + `<div style="position:absolute;top:540px;left:0;width:40px;height:10px;background:#000;transform:translateY(30px)"></div>`), "ext-ii"), false]
    heightResults["(iii) text overflowing a fixed-height element"] = [dpx(plain, await extent(560, para(300) + `<div style="position:absolute;top:540px;left:0;width:30px;height:10px;font:16px/20px monospace;color:#000">aaa bbb ccc ddd</div>`), "ext-iii"), false]
    // Clipped text inflates the extent without painting: the extra rows are neutral fill on both sides, 0 px.
    const clippedBox = (text) => `<div style="position:absolute;top:540px;left:0;width:30px;height:10px;overflow:hidden;font:16px/20px monospace;color:#000">${text}</div>`
    heightResults["(iv) clipped text inflating the extent, nothing extra painted"] = [dpx(await extent(560, para(300) + clippedBox("aaa")), await extent(560, para(300) + clippedBox("aaa bbb ccc ddd")), "ext-iv"), true]
    for (const [label, [diff, zero]] of Object.entries(heightResults)) {
      if (zero && diff !== 0) throw new Error(`selftest: ${label}: expected 0 px, got ${diff} px`)
      if (!zero && diff === 0) throw new Error(`selftest: ${label}: expected a diff, got 0 px`)
    }
    console.log(`selftest painted extent passed (${Object.entries(heightResults).map(([l, [d]]) => `${l.slice(0, 3)} ${d} px`).join(", ")})`)
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

async function selftestOverflow(browser) {
  // The overflow check must go red on a forced overflow and stay green without.
  const context = await browser.newContext({ viewport: { width: 1000, height: 600 } })
  try {
    const page = await context.newPage()
    await page.setContent('<body style="margin:0"><main id="m" style="width:100%;height:100px"><div style="height:10px">fits</div></main></body>')
    const clean = await horizontalOverflow(page, "#m")
    assertEqual(clean.length, 0, "overflow check on a fitting page")
    await page.addStyleTag({ content: "#m > div { width: 1400px; }" })
    const rootOver = await horizontalOverflow(page, "#m")
    if (rootOver.length < 2) throw new Error(`selftest: forced overflow not detected on document and root (${rootOver.join("; ")})`)
    console.log(`selftest overflow check passed (forced: ${rootOver.join("; ")})`)
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
  selftestLegacyOrigin()
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
  await selftestOverflow(browser)
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
      if (item.scene.capture === "content" && item.scene.kind === "before-vs-after" && NATURAL_CAPTURE_WIDTHS.includes(item.width)) {
        const natural = await captureNatural(browser, item, { runDir })
        rows.push(natural)
        console.log(`${natural.outcome.padEnd(14)}      n/a%  ${natural.key}${natural.outcome === "fail" ? `  [${natural.reason}]` : ""}`)
      }
    }
  } finally {
    await browser?.close()
    servers.stop()
  }
  fs.writeFileSync(path.join(runDir, "report.json"), JSON.stringify(rows, null, 2))
  const captured = rows.filter((r) => r.outcome === "captured")
  const compared = rows.filter((r) => r.outcome !== "captured")
  const md = [
    "| Scene | Difference | % pixels | Justification | Approved | Verdict |",
    "|---|---|---|---|---|---|",
    ...compared
      .filter((r) => r.diff === null || r.diff > 0)
      .map(
        (r) =>
          `| ${r.key} | ${r.justification?.difference ?? "(none)"} | ${(r.pct ?? 0).toFixed(2)} | ${
            r.justification?.justification ?? "(missing)"
          } | ${r.justification?.approved ?? "no"} | ${r.outcome}: ${r.reason} |`,
      ),
    ...(captured.length
      ? ["", "## Needs human review (not compared)", "", ...captured.map((r) => `- ${r.key}: ${r.reason} (${path.relative(REPO_DIR, r.artifact)})`)]
      : []),
  ].join("\n")
  fs.writeFileSync(path.join(runDir, "report.md"), md + "\n")
  console.log(`report: ${path.relative(REPO_DIR, runDir)}`)
  const failed = rows.filter((r) => r.outcome === "fail")
  if (failed.length) console.error(`${failed.length} scene key(s) failed`)
  const needReview = rows.filter((r) => r.outcome === "captured")
  if (needReview.length) {
    console.log("Needs human review (not compared):")
    for (const r of needReview) console.log(`  ${r.key}  ${path.relative(REPO_DIR, r.artifact)}`)
  }
  if (rows.length && rows.every((r) => r.outcome === "captured")) console.error("no scene key was compared; only captures were taken")
  process.exitCode = exitCodeFor(rows)
}

main().catch((error) => {
  console.error(error)
  process.exitCode = 1
})

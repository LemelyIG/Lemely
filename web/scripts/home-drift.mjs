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
import fs from "node:fs"
import path from "node:path"
import { chromium } from "@playwright/test"
import { HEIGHT, SCENES, THEMES, WINDOWS } from "./drift/scenes.mjs"
import {
  REPO_DIR,
  SELECTORS,
  capture,
  contentBox,
  matchContentWidth,
  openApp,
  openPreview,
  startServers,
} from "./drift/harness.mjs"
import { diffPngs, findJustification, verdict } from "./drift/compare.mjs"

function parseArgs(argv) {
  const out = { scene: [], windows: null, themes: null, recordBaseline: false, selftest: false, list: false }
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]
    if (a === "--scene") out.scene = argv[++i].split(",")
    else if (a === "--windows") out.windows = argv[++i].split(",").map(Number)
    else if (a === "--themes") out.themes = argv[++i].split(",")
    else if (a === "--record-baseline") out.recordBaseline = true
    else if (a === "--selftest") out.selftest = true
    else if (a === "--list") out.list = true
    else throw new Error(`unknown argument ${a}`)
  }
  return out
}

const args = parseArgs(process.argv.slice(2))
const DRIFT_DIR = path.join(REPO_DIR, "reports", ".scratch", "drift")
const BASELINE_DIR = path.join(DRIFT_DIR, "baseline")

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

async function shoot(browser, side, item, targetWidth) {
  const { scene, width, theme } = item
  const height = HEIGHT[width] ?? 900
  const opened =
    side === "preview"
      ? await openPreview(browser, { width, height, theme, preview: scene.preview })
      : await openApp(browser, { width, height, theme, app: scene.app })
  try {
    const selector = SELECTORS[side === "preview" ? "preview" : "app"]
    if (scene.capture === "content" && targetWidth !== undefined) {
      const ok = await matchContentWidth(opened.page, selector, targetWidth, height)
      if (!ok) throw new Error(`${item.key}: could not match content width ${targetWidth}`)
    }
    const width_ = scene.capture === "content" ? (await contentBox(opened.page, selector)).width : undefined
    const png = await capture(opened.page, {
      capture: scene.capture,
      selector,
      neutral: scene.kind === "before-vs-after",
    })
    return { png, contentWidth: width_ }
  } finally {
    await opened.context.close()
  }
}

async function runSelftest(browser) {
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
  console.log("selftest passed")
}

async function main() {
  const items = expand()
  if (args.list) {
    for (const i of items) console.log(i.key)
    return
  }
  const needKit = args.selftest || items.some((i) => i.scene.kind === "preview-vs-app")
  const servers = await startServers({ needKit })
  const browser = await chromium.launch()
  const runDir = path.join(DRIFT_DIR, new Date().toISOString().replace(/[:.]/g, "-"))
  fs.mkdirSync(runDir, { recursive: true })
  fs.mkdirSync(BASELINE_DIR, { recursive: true })
  const rows = []
  try {
    if (args.selftest) {
      await runSelftest(browser)
      return
    }
    for (const item of items) {
      const { scene, key } = item
      if (args.recordBaseline) {
        if (scene.kind !== "before-vs-after") continue
        const shot = await shoot(browser, "app", item)
        fs.writeFileSync(path.join(BASELINE_DIR, `${key}.png`), shot.png)
        fs.writeFileSync(
          path.join(BASELINE_DIR, `${key}.json`),
          JSON.stringify({ contentWidth: shot.contentWidth ?? null }),
        )
        console.log(`baseline ${key}`)
        continue
      }
      let a
      let b
      if (scene.kind === "preview-vs-app") {
        a = await shoot(browser, "preview", item)
        b = await shoot(browser, "app", item, a.contentWidth)
      } else {
        const basePng = path.join(BASELINE_DIR, `${key}.png`)
        if (!fs.existsSync(basePng)) throw new Error(`${key}: no baseline; run with --record-baseline on merged develop`)
        const meta = JSON.parse(fs.readFileSync(path.join(BASELINE_DIR, `${key}.json`), "utf8"))
        a = { png: fs.readFileSync(basePng) }
        b = await shoot(browser, "app", item, meta.contentWidth ?? undefined)
      }
      fs.writeFileSync(path.join(runDir, `${key}.a.png`), a.png)
      fs.writeFileSync(path.join(runDir, `${key}.b.png`), b.png)
      const result = diffPngs(a.png, b.png, path.join(runDir, `${key}.diff.png`))
      const justification = findJustification(key)
      const outcome = verdict(result, justification, scene.rule ?? "gate")
      rows.push({ key, ...result, outcome, justification })
      console.log(`${outcome.padEnd(14)} ${result.pct.toFixed(3).padStart(8)}%  ${key}`)
    }
  } finally {
    await browser.close()
    servers.stop()
  }
  if (args.recordBaseline || args.selftest) return
  fs.writeFileSync(path.join(runDir, "report.json"), JSON.stringify(rows, null, 2))
  const md = [
    "| Scene | Difference | % pixels | Justification | Approved |",
    "|---|---|---|---|---|",
    ...rows
      .filter((r) => r.diff > 0)
      .map(
        (r) =>
          `| ${r.key} | ${r.justification?.difference ?? "(none)"} | ${r.pct.toFixed(2)} | ${
            r.justification?.justification ?? "(missing)"
          } | ${r.justification?.approved ?? "no"} |`,
      ),
  ].join("\n")
  fs.writeFileSync(path.join(runDir, "report.md"), md + "\n")
  console.log(`report: ${path.relative(REPO_DIR, runDir)}`)
  const failed = rows.filter((r) => r.outcome === "fail")
  if (failed.length) {
    console.error(`${failed.length} scene key(s) failed`)
    process.exitCode = 1
  }
}

main().catch((error) => {
  console.error(error)
  process.exitCode = 1
})

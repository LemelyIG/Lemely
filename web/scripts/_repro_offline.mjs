#!/usr/bin/env node
/** THROWAWAY repro for the P3.10 e2a offline-capture crash. Delete after use.
 * Boots the same servers audit.mjs does, then drives ONLY the T-01
 * default -> offline sequence and reports whether the page and the browser
 * survive it. */
import { spawn, execSync, spawnSync } from "node:child_process"
import path from "node:path"
import { fileURLToPath } from "node:url"
import puppeteer from "puppeteer"
import lighthouse from "lighthouse"

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const webRoot = path.resolve(__dirname, "..")
const repoRoot = path.resolve(webRoot, "..")
const BACKEND_URL = "http://127.0.0.1:8000"
const PREVIEW_URL = "http://127.0.0.1:4173"
const log = (m) => process.stdout.write(`[repro] ${m}\n`)

function resolveSupabaseEnv() {
  const raw = execSync("supabase status -o json", {
    stdio: ["ignore", "pipe", "ignore"],
    env: { ...process.env, PATH: `${process.env.HOME}/.local/bin:${process.env.PATH}` },
  }).toString()
  const s = JSON.parse(raw)
  return {
    LEMELY_SUPABASE__SERVICE_ROLE_KEY: s.SERVICE_ROLE_KEY,
    LEMELY_SUPABASE__ANON_KEY: s.ANON_KEY,
  }
}

async function waitForHttp(url, timeoutMs) {
  const deadline = Date.now() + timeoutMs
  for (;;) {
    try {
      await fetch(url)
      return
    } catch {
      if (Date.now() > deadline) throw new Error(`timeout waiting for ${url}`)
      await new Promise((r) => setTimeout(r, 500))
    }
  }
}

async function waitForText(page, text) {
  await page.waitForFunction(
    (t) => document.body?.innerText?.includes(t),
    { timeout: 20_000 },
    text,
  )
}

const supabaseEnv = resolveSupabaseEnv()
if (!process.env.SKIP_BUILD) {
  log("build...")
  execSync("npm run build", { cwd: webRoot, stdio: "ignore" })
}
log("backend...")
const backend = spawn(path.join(repoRoot, ".venv/bin/python"), ["scripts/e2e_server.py"], {
  cwd: repoRoot,
  env: { ...process.env, ...supabaseEnv },
})
await waitForHttp(`${BACKEND_URL}/docs`, 30_000)
log("seed...")
const seedRun = spawnSync(path.join(repoRoot, ".venv/bin/python"), ["scripts/seed_e2e.py"], {
  cwd: repoRoot,
  env: { ...process.env, ...supabaseEnv },
  encoding: "utf-8",
  maxBuffer: 16 * 1024 * 1024,
})
if (seedRun.status !== 0) {
  process.stderr.write(seedRun.stderr ?? "")
  throw new Error("seed failed")
}
const seed = JSON.parse(seedRun.stdout)
log("preview...")
const preview = spawn(
  path.join(webRoot, "node_modules/.bin/vite"),
  ["preview", "--host", "127.0.0.1", "--port", "4173", "--strictPort"],
  { cwd: webRoot },
)
await waitForHttp(PREVIEW_URL, 30_000)

const browser = await puppeteer.launch({ headless: true })
try {
  const ctx = await browser.createBrowserContext()
  const page = await ctx.newPage()
  page.on("error", (e) => log(`PAGE CRASH EVENT: ${e}`))
  await page.evaluateOnNewDocument(
    (session) => {
      if (window.location.origin === "null") return
      window.localStorage.setItem("lemely.session", JSON.stringify(session))
    },
    {
      accessToken: seed.teacher.accessToken,
      refreshToken: null,
      userId: seed.teacher.userId,
      role: "teacher",
    },
  )

  log("default state: goto /teacher")
  await page.setViewport({ width: 1440, height: 900 })
  await page.goto(`${PREVIEW_URL}/teacher`, { waitUntil: "networkidle0" })
  await waitForText(page, "Good morning")
  log("default OK")

  if (!process.env.SKIP_LH) {
    log("lighthouse on the same page (the variable the first repro was missing)...")
    const lhResult = await lighthouse(
      `${PREVIEW_URL}/teacher`,
      {
        onlyCategories: ["performance", "accessibility", "best-practices", "seo"],
        logLevel: "error",
        disableStorageReset: true,
      },
      undefined,
      page,
    )
    log(`lighthouse done: a11y=${lhResult.lhr.categories.accessibility?.score}`)
    log(`  page.isClosed()=${page.isClosed()} browser.connected=${browser.connected}`)
  }

  log("sw ready...")
  const swInfo = await page.evaluate(async () => {
    const reg = await navigator.serviceWorker.ready
    return { scope: reg.scope, hasController: !!navigator.serviceWorker.controller }
  })
  log(`sw: ${JSON.stringify(swInfo)}`)

  log("setOfflineMode(true)")
  await page.setOfflineMode(true)

  for (const bp of [{ width: 380, height: 800 }, { width: 768, height: 1024 }, { width: 1440, height: 900 }]) {
    log(`offline @ ${bp.width}: setViewport`)
    await page.setViewport(bp)
    try {
      log(`offline @ ${bp.width}: goto`)
      await page.goto(`${PREVIEW_URL}/teacher`, { waitUntil: "networkidle0" })
      log(`offline @ ${bp.width}: navigated, waiting for text`)
      await waitForText(page, "Couldn't load the overview")
      log(`offline @ ${bp.width}: OK`)
    } catch (err) {
      log(`offline @ ${bp.width}: FAILED ${err?.message ?? err}`)
      log(`  page.isClosed()=${page.isClosed()} browser.connected=${browser.connected}`)
      try {
        const t = await page.evaluate(() => document.body?.innerText?.slice(0, 400))
        log(`  body text: ${JSON.stringify(t)}`)
      } catch (e2) {
        log(`  cannot evaluate: ${e2?.message ?? e2}`)
      }
      break
    }
  }

  log(`after loop: page.isClosed()=${page.isClosed()} browser.connected=${browser.connected}`)
  await page.setOfflineMode(false).catch((e) => log(`teardown failed: ${e?.message}`))
  log("can the browser still make a context?")
  try {
    const c2 = await browser.createBrowserContext()
    const p2 = await c2.newPage()
    await p2.goto(`${PREVIEW_URL}/login`, { waitUntil: "networkidle0" })
    log("YES — browser survived")
  } catch (e) {
    log(`NO — browser is dead: ${e?.message}`)
  }
} finally {
  await browser.close().catch(() => {})
  backend.kill("SIGTERM")
  preview.kill("SIGTERM")
}

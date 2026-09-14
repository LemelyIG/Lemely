#!/usr/bin/env node
/**
 * Installability gate (Task 12, B7).
 *
 * Google removed Lighthouse's PWA category — and with it the
 * `installable-manifest` audit — some time ago (`audit.mjs:210-214` records
 * this and its date). That audit used to be a thin wrapper around one CDP
 * call: `Page.getInstallabilityErrors`. This script is that same call, run
 * directly against a real production build (`vite preview`, not `vite dev`
 * — the service worker only exists after `npm run build`), so "is this
 * build installable" still has an answer.
 *
 * WHY A PRODUCTION HOSTNAME, NOT 127.0.0.1. The manifest's `scope_extensions`
 * (`vite/manifest.ts`) is keyed to the real `lemelyig.com` origin family, and
 * Chromium's installability checks are the same checks a real user's browser
 * runs on the real domain — testing them against `127.0.0.1` would prove
 * less than testing them against the origin the app is actually served
 * from. `--host-resolver-rules` maps that hostname to the local preview
 * server without needing real DNS or a certificate; a service worker still
 * needs a secure context, so `--unsafely-treat-insecure-origin-as-secure`
 * grants that to plain `http://lemelyig.com:4173` the same way `localhost`
 * gets it for free.
 */

import { withRetry } from "./nav_retry.mjs"
import { startPreview, assertPortFree } from "./serve_guard.mjs"
import path from "node:path"
import { fileURLToPath } from "node:url"
import puppeteer from "puppeteer"

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const repoRoot = path.resolve(__dirname, "..")
const PORT = 4173
const HOST = "lemelyig.com"
const ORIGIN = `http://${HOST}:${PORT}`

function log(msg) {
  process.stdout.write(`[check:installable] ${msg}\n`)
}

/** Polls until the preview server answers, per `audit.mjs`'s own
 * `waitForHttp` — a spawned server takes a moment to bind, so this waits
 * with a delay between attempts rather than `withRetry`'s deliberately
 * immediate ones (`nav_retry.mjs`'s own doc comment: those are for
 * transient failures against an already-running server, not for "hasn't
 * started yet"). `withRetry` is reserved below for the actual CDP call. */
async function waitForHttp(url, timeoutMs) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    try {
      await fetch(url, { signal: AbortSignal.timeout(2_000) })
      return
    } catch {
      await new Promise((resolve) => setTimeout(resolve, 500))
    }
  }
  throw new Error(`Timed out waiting for ${url} to respond`)
}

async function main() {
  await assertPortFree(`http://127.0.0.1:${PORT}`, PORT, "check_installability.mjs")

  const preview = startPreview(PORT, repoRoot)
  let browser
  try {
    await waitForHttp(`http://127.0.0.1:${PORT}`, 30_000)

    browser = await puppeteer.launch({
      headless: true,
      args: [
        `--host-resolver-rules=MAP ${HOST} 127.0.0.1`,
        `--unsafely-treat-insecure-origin-as-secure=${ORIGIN}`,
      ],
    })

    const errors = await withRetry(
      async () => {
        const page = await browser.newPage()
        const client = await page.target().createCDPSession()
        await page.goto(ORIGIN, { waitUntil: "networkidle0" })
        // Give the service worker registration promise (main.tsx) a moment
        // to settle before asking Chromium whether the app is installable —
        // the manifest/SW-scope checks this call runs need it registered.
        await page.evaluate(() => navigator.serviceWorker?.ready)
        const result = await client.send("Page.getInstallabilityErrors")
        await page.close()
        return result.installabilityErrors ?? []
      },
      { attempts: 3, label: "Page.getInstallabilityErrors" },
    )

    if (errors.length > 0) {
      log(`installable: ${errors.length} error(s)`)
      for (const err of errors) {
        log(`  - ${err.errorId}${err.errorArguments?.length ? ` (${JSON.stringify(err.errorArguments)})` : ""}`)
      }
      process.exitCode = 1
      return
    }

    log("installable: no errors")
  } finally {
    await browser?.close()
    preview.stop()
  }
}

await main()

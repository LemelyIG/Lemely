#!/usr/bin/env node
/*
 *   node scripts/shell-behaviour.mjs [--check <prefix>] [--axe]
 *
 * Runs SHELL_CHECKS against `vite preview` of dist/ (run `npm run build`
 * first). --axe additionally runs axe-core after each check's final state
 * (skipping checks marked `axe: false`) and fails on any violation. --check
 * with no value, or a prefix that matches no check, exits 1. Exit 0 only when
 * every check passes.
 */
import path from "node:path"
import { chromium } from "@playwright/test"
import { NATIVE_CHECKS } from "./drift/checks-native.mjs"
import { SHELL_CHECKS } from "./drift/checks-shell.mjs"
import { WEB_DIR, openApp, startServers } from "./drift/harness.mjs"

const argv = process.argv.slice(2)
const checkAt = argv.indexOf("--check")
const prefix = checkAt === -1 ? "" : (argv[checkAt + 1] ?? "")
if (checkAt !== -1 && (!prefix || prefix.startsWith("--"))) {
  console.error("--check needs a check id prefix")
  process.exit(1)
}
const withAxe = argv.includes("--axe")
const AXE = path.join(WEB_DIR, "node_modules", "axe-core", "axe.min.js")

async function main() {
  const checks = [...SHELL_CHECKS, ...NATIVE_CHECKS].filter((c) => c.id.startsWith(prefix))
  if (!checks.length) {
    console.error(`no checks match --check ${prefix}`)
    process.exitCode = 1
    return
  }
  const servers = await startServers({ needKit: false })
  const browser = await chromium.launch()
  let failed = 0
  try {
    for (const check of checks) {
      const width = check.width ?? 1440
      const { context, page } = await openApp(browser, {
        width,
        height: width === 412 ? 915 : width <= 390 ? 844 : 900,
        theme: check.theme ?? "light",
        app: check.app,
        platform: check.platform,
      })
      try {
        await check.run(page)
        if (withAxe && check.axe !== false) {
          await page.addScriptTag({ path: AXE })
          const result = await page.evaluate(async () => await window.axe.run())
          if (result.violations.length) {
            const lines = result.violations.map((v) => `${v.impact} ${v.id} (${v.nodes.length})`).join("; ")
            throw new Error(`axe: ${lines}`)
          }
        }
        console.log(`pass  ${check.id}`)
      } catch (error) {
        failed++
        console.log(`FAIL  ${check.id}: ${error.message}`)
      } finally {
        await context.close()
      }
    }
  } finally {
    await browser.close()
    servers.stop()
  }
  if (failed) {
    console.error(`${failed} check(s) failed`)
    process.exitCode = 1
  }
}

main().catch((error) => {
  console.error(error)
  process.exitCode = 1
})

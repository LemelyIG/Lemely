import { execSync } from "node:child_process"
import path from "node:path"
import { fileURLToPath } from "node:url"
import { defineConfig, devices } from "@playwright/test"

const __dirname = path.dirname(fileURLToPath(import.meta.url))

/*
 * P2.10 acceptance suite. Two real webServer processes are booted by
 * Playwright itself: the backend (scripts/e2e_server.py — the real FastAPI
 * app against the real local Supabase stack, only the Gemini-vision seam
 * mocked) and the frontend (vite dev server, whose existing /api proxy
 * targets the backend's default port 8000 — see vite.config.ts).
 *
 * The backend needs the local Supabase stack's service-role/anon keys. We
 * resolve those once at config-eval time via `supabase status -o json` so
 * the test run is self-contained and doesn't depend on the invoking shell
 * already having them exported.
 */

interface SupabaseStatus {
  ANON_KEY: string
  SERVICE_ROLE_KEY: string
}

function resolveSupabaseEnv(): Record<string, string> {
  try {
    // The Supabase CLI is installed at ~/.local/bin/supabase, which this
    // sandbox's non-interactive/non-login shells do not put on PATH
    // (~/.bash_profile only sources ~/.bashrc, never ~/.profile, so the
    // ~/.local/bin PATH entry there never applies) — prepend it explicitly
    // rather than depend on the invoking shell's PATH.
    const raw = execSync("supabase status -o json", {
      stdio: ["ignore", "pipe", "ignore"],
      env: { ...process.env, PATH: `${process.env.HOME}/.local/bin:${process.env.PATH}` },
    }).toString()
    const status = JSON.parse(raw) as SupabaseStatus
    return {
      LEMELY_SUPABASE__SERVICE_ROLE_KEY: status.SERVICE_ROLE_KEY,
      LEMELY_SUPABASE__ANON_KEY: status.ANON_KEY,
    }
  } catch (err) {
    // Surface a clear failure at config-eval time rather than a confusing
    // "service-role key is not configured" error deep in a test run.
    throw new Error(
      `Could not resolve Supabase local-stack keys via "supabase status -o json". Is the local stack up? (${String(err)})`,
    )
  }
}

const repoRoot = path.resolve(__dirname, "..")
const supabaseEnv = resolveSupabaseEnv()
// Exported into this process's own env (not just threaded into webServer's
// `env` below) so `./e2e/global-setup.ts` — a bare module path Playwright
// invokes directly, which cannot receive config-module-scoped values any
// other way — inherits them without re-shelling out to `supabase status`
// itself.
Object.assign(process.env, supabaseEnv)

/**
 * `process.env` is typed `string | undefined` per key, but Playwright's
 * `webServer.env` requires `string`. Node never actually *stores* an undefined
 * value — the type is wide because reading an unset key yields `undefined` — so
 * dropping those keys matches the runtime exactly. Filtering rather than
 * asserting keeps the guarantee real: if a value ever genuinely is undefined it
 * is omitted, instead of reaching the subprocess as the literal "undefined".
 *
 * Found by P6.1 when `e2e/` and this file entered a tsconfig for the first time
 * since Phase 3 (D3.20) — it was the only error in 13 files and 30 test blocks.
 */
function definedEnv(env: NodeJS.ProcessEnv): Record<string, string> {
  return Object.fromEntries(
    Object.entries(env).filter((entry): entry is [string, string] => entry[1] !== undefined),
  )
}

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 1,
  reporter: "list",
  // P3.10 chunk d: seeds the shared multi-role fixture (scripts/seed_e2e.py)
  // exactly once for the whole run — see global-setup.ts for why this can't
  // be a cached-promise helper instead.
  globalSetup: path.join(__dirname, "e2e/global-setup.ts"),
  use: {
    baseURL: "http://127.0.0.1:5173",
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    /*
     * P5.11: pin one `lemely.deviceId` across every browser context so the
     * whole run presents as a single device to the D1.11 3-device registry.
     *
     * WHY THIS IS CORRECT AND NOT A WORKAROUND. `lemely/db/device_repo.py`'s
     * own contract: "A stable, client-supplied `client_device_id` ... lets a
     * re-login on the *same* device reuse its row — its `last_seen_at` is
     * refreshed rather than a new slot consumed." The SPA mints that id once
     * into localStorage (`src/lib/auth/storage.ts`) precisely so repeated
     * logins from one browser do not eat slots. Playwright hands every test a
     * fresh context, hence a fresh localStorage, hence a *fresh* id — so the
     * suite was manufacturing a new "device" per spec. One CI browser on one
     * machine is one device; the fresh id was the test-isolation artifact, and
     * this restores the semantics the product was built with.
     *
     * WHAT IT COST TO LEARN. The seeded teacher is shared, and three specs log
     * in as it through the real UI (`reduced-motion` twice via `gotoSchemes`,
     * `engagement`, `teacher-journey`). That was exactly MAX_DEVICES=3 — at
     * the cap with zero headroom — so P5.11 adding the `engagement` login made
     * a fourth, and `teacher-journey` (last alphabetically, so last to run)
     * was served G-10's 409 device-limit challenge instead of `/teacher`. It
     * read as a broken teacher login; it was the device limit working.
     *
     * WHY GLOBAL RATHER THAN PER-SPEC. Getting under the cap by converting one
     * spec to `injectSession` would leave headroom of one, and the next spec
     * that logs in as a shared account breaks a *different*, alphabetically
     * later spec. That failure is silent and order-dependent. Pinning the id
     * removes the class of bug rather than this instance of it.
     *
     * IT DOES NOT WEAKEN G-10. The dedicated device-limit account is seeded
     * with three rows whose `client_device_id` is NULL (`scripts/seed_e2e.py`),
     * deliberately so no browser can ever match one — a pinned id matches
     * nothing there and still gets its 409 challenge.
     */
    storageState: path.join(__dirname, "e2e/device-state.json"),
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: [
    {
      command: `${path.join(repoRoot, ".venv/bin/python")} scripts/e2e_server.py`,
      cwd: repoRoot,
      port: 8000,
      timeout: 60_000,
      reuseExistingServer: !process.env.CI,
      env: definedEnv({ ...process.env, ...supabaseEnv }),
    },
    {
      // vite (v8) binds "localhost" to [::1] only by default, which Playwright's
      // 127.0.0.1 readiness probe (and baseURL) can't reach — force an IPv4 bind.
      command: "npm run dev -- --host 127.0.0.1",
      cwd: __dirname,
      url: "http://127.0.0.1:5173",
      timeout: 60_000,
      reuseExistingServer: !process.env.CI,
    },
  ],
})

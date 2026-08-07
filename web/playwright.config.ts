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
      env: {
        ...process.env,
        ...supabaseEnv,
      },
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

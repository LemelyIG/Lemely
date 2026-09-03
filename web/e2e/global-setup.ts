import { spawnSync } from "node:child_process"
import fs from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"
import { reportDir } from "./report-dir"
import { seedFilePath } from "./seed"

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const repoRoot = path.resolve(__dirname, "..", "..")

/**
 * Playwright `globalSetup` (registered in `playwright.config.ts`): runs
 * `scripts/seed_e2e.py` exactly ONCE for the whole test run and writes its
 * JSON output contract to `<reportDir()>/e2e-seed.json`. Every P3.10 spec
 * reads it back through `readSeed()` in `./seed.ts`.
 *
 * Why this has to be `globalSetup` and not a cached promise in a shared
 * helper module: Playwright forks a separate worker process per running
 * test file (even at `workers: 1`, sequential test files still don't share
 * the process that evaluated this config), so in-memory module state cannot
 * be shared across them — a "seed once, cache the promise" helper would
 * silently re-seed on every spec file instead of memoizing anything.
 * `globalSetup` itself runs exactly once, in the single runner process,
 * before workers start — a file on disk is the one thing every worker can
 * actually read back.
 *
 * `scripts/seed_e2e.py` resolves the Supabase service-role/anon keys itself
 * (`ensure_supabase_env()`, reading `supabase status -o json` when they
 * aren't already exported) and talks to Supabase/Postgres directly — it
 * never touches the app's own HTTP server, so it needs no `webServer` up.
 * `playwright.config.ts` exports the same resolved keys into `process.env`
 * right after computing them for the backend `webServer`'s env, so this
 * process inherits them for free; whether Playwright happens to run
 * `globalSetup` before or after booting `webServer` is irrelevant either way.
 *
 * Before seeding, this also runs `alembic upgrade head` against that same
 * stack. Migration 0024 inserts the subject/paper/topic catalogue as part of
 * the schema upgrade (Task 18) — without it `seed_e2e.py` would be seeding
 * demo accounts and attempts on top of a database with no subjects at all,
 * and S-01 would render an empty subject list, failing `phase4-journey` and
 * `signup` at their first step. `make db-up` already runs this migration for
 * local dev, but the E2E stack is not guaranteed to have gone through it
 * (e.g. a stack started directly via `supabase start` and never migrated),
 * so this can't assume it already happened.
 */
export default function globalSetup(): void {
  const outDir = reportDir()
  fs.mkdirSync(outDir, { recursive: true })

  const migrate = spawnSync(path.join(repoRoot, ".venv/bin/alembic"), ["upgrade", "head"], {
    cwd: repoRoot,
    env: process.env,
    encoding: "utf-8",
    maxBuffer: 16 * 1024 * 1024,
  })
  if (migrate.status !== 0) {
    throw new Error(`alembic upgrade head failed (exit ${migrate.status}):\n${migrate.stderr}`)
  }

  const result = spawnSync(
    path.join(repoRoot, ".venv/bin/python"),
    ["scripts/seed_e2e.py"],
    {
      cwd: repoRoot,
      env: process.env,
      encoding: "utf-8",
      maxBuffer: 16 * 1024 * 1024,
    },
  )
  if (result.status !== 0) {
    throw new Error(
      `scripts/seed_e2e.py failed (exit ${result.status}):\n${result.stderr}`,
    )
  }
  fs.writeFileSync(seedFilePath(), result.stdout)
}

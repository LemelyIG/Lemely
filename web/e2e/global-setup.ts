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
 * process inherits them for free.
 *
 * ORDER. Playwright starts the `webServer` processes BEFORE it runs this
 * function, so the backend is already up, pointed at `lemely_e2e`, while the
 * reset below drops and recreates that database under it (the reset's
 * `DROP ... WITH (FORCE)` closes its pooled connections; `pool_pre_ping`
 * recovers them). That is harmless because no spec runs yet and nothing in the
 * backend works on the database in the meantime; the notification sweeper
 * would, so `playwright.config.ts` turns it off for this server. The same
 * ordering is what makes a second concurrent run fail on the busy port 8000
 * before it can reach its own reset.
 *
 * OWN DATABASE. The app's data does not go in the shared local `postgres`
 * database. `playwright.config.ts` points `LEMELY_DATABASE__URL` at
 * `lemely_e2e` on the same Supabase server, and every run starts here by
 * dropping and recreating it (`scripts/reset_e2e_db.py`, which refuses any
 * name but exactly `lemely_e2e` on a loopback host), so another branch's
 * alembic stamp on `postgres` can never break a run and a run can never move
 * that stamp. Auth is the one exception: GoTrue only reads its own `auth`
 * schema in `postgres`, so the specs and `seed_e2e.py` still create their users
 * there over GoTrue's HTTP API. Every such account is on the
 * `e2e.lemely.local` domain, and the same reset deletes the GoTrue users on
 * that domain (admin API, loopback Supabase only, no other domain) because
 * once the database is dropped they are orphans. `public.users` is a mirror
 * with no foreign key to them, so nothing else touches `postgres`.
 *
 * Then `alembic upgrade head` builds the schema from this checkout. Migration
 * 0024 inserts the subject/paper/topic catalogue as part of that upgrade
 * (Task 18) — without it `seed_e2e.py` would be seeding demo accounts and
 * attempts on top of a database with no subjects at all, and S-01 would
 * render an empty subject list, failing `phase4-journey` and `signup` at their
 * first step. `scripts/seed_e2e_boundaries.py` adds synthetic grade
 * boundaries (not exam board data), since grading refuses an empty table and
 * the real ones come from a network scrape.
 */
export default function globalSetup(): void {
  const outDir = reportDir()
  fs.mkdirSync(outDir, { recursive: true })

  const reset = spawnSync(path.join(repoRoot, ".venv/bin/python"), ["scripts/reset_e2e_db.py"], {
    cwd: repoRoot,
    env: process.env,
    encoding: "utf-8",
  })
  if (reset.status !== 0) {
    throw new Error(`e2e database reset failed (exit ${reset.status}):\n${reset.stderr}`)
  }
  process.stderr.write(reset.stderr)

  const migrate = spawnSync(path.join(repoRoot, ".venv/bin/alembic"), ["upgrade", "head"], {
    cwd: repoRoot,
    env: process.env,
    encoding: "utf-8",
    maxBuffer: 16 * 1024 * 1024,
  })
  if (migrate.status !== 0) {
    throw new Error(`alembic upgrade head failed (exit ${migrate.status}):\n${migrate.stderr}`)
  }

  const boundaries = spawnSync(path.join(repoRoot, ".venv/bin/python"), ["scripts/seed_e2e_boundaries.py"], {
    cwd: repoRoot,
    env: process.env,
    encoding: "utf-8",
  })
  if (boundaries.status !== 0) {
    throw new Error(`e2e boundary fixtures failed (exit ${boundaries.status}):\n${boundaries.stderr}`)
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

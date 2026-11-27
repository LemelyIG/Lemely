/**
 * Pure helpers `playwright.config.ts` uses to point a run at its own database and to
 * keep ambient environment from steering it elsewhere. Kept free of side effects (and
 * of the `supabase status` call the config makes on import) so
 * `tests/unit/e2eEnv.test.ts` can exercise every guard directly.
 */

/** The one database a run may reset; `scripts/e2e_fixtures.py` holds the same name. */
export const E2E_DATABASE_NAME = "lemely_e2e"

/** What `supabase status` reports for a stock local stack; used only if it omits DB_URL. */
export const DEFAULT_DB_URL = "postgresql://postgres:postgres@127.0.0.1:54322/postgres"

/**
 * libpq environment variables that override the explicit host in the database URL:
 * `hostaddr` wins over `host`, and a `PGSERVICE` entry (read from `PGSERVICEFILE`, or
 * `~/.pg_service.conf`) can set `hostaddr`, `dbname` or `host` on its own. A run must
 * not inherit them, or "loopback `lemely_e2e`" would be a claim about the URL only.
 */
export const LIBPQ_OVERRIDE_VARS = ["PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE"] as const

/** The names a loopback Supabase/Postgres/backend is reached by. */
export const LOOPBACK_HOSTS = ["127.0.0.1", "localhost", "::1"] as const

/**
 * The SQLAlchemy URL of the e2e database: the local stack's own Postgres (host, port
 * and credentials from `supabase status`), with only the database name swapped, so a
 * customised local stack needs no edit here.
 *
 * Refuses a query string or fragment. SQLAlchemy's psycopg dialect passes every query
 * parameter on to libpq, so `?dbname=postgres` or `?hostaddr=...` would send alembic,
 * the seeds and the backend somewhere other than the database every name check
 * approved. Throwing is deliberate: silently dropping a parameter such as `sslmode`
 * would change how the run connects without saying so.
 */
export function e2eDatabaseUrl(statusDbUrl: string | undefined): string {
  const url = new URL(statusDbUrl ?? DEFAULT_DB_URL)
  if (url.search !== "" || url.hash !== "") {
    throw new Error(
      "Refusing the Supabase DB_URL for the e2e database: it carries a query string or " +
        "fragment, which libpq would apply on top of the host and database name checked here.",
    )
  }
  url.pathname = `/${E2E_DATABASE_NAME}`
  return url.toString().replace(/^postgres(ql)?:/, "postgresql+psycopg:")
}

/** Delete, in place, every libpq variable that could override the URL's explicit host. */
export function scrubLibpqOverrides(env: NodeJS.ProcessEnv): void {
  for (const name of LIBPQ_OVERRIDE_VARS) {
    delete env[name]
  }
}

/**
 * Make every process of the run reach loopback directly, in place.
 *
 * `httpx` (the GoTrue admin calls, which carry the service-role key) and most HTTP
 * clients honour `HTTP_PROXY` and send even a 127.0.0.1 request through it unless
 * `NO_PROXY` names that host. This adds the loopback names to `NO_PROXY` and
 * `no_proxy` (clients differ on which case wins), keeping whatever entries were
 * already there, and leaves the proxy variables themselves alone so anything that
 * genuinely needs the proxy to reach the internet still has it.
 */
export function bypassProxyForLoopback(env: NodeJS.ProcessEnv): void {
  const existing = [env.NO_PROXY, env.no_proxy]
    .flatMap((value) => (value ?? "").split(","))
    .map((entry) => entry.trim())
    .filter((entry) => entry !== "")
  const merged = [...new Set([...existing, ...LOOPBACK_HOSTS])].join(",")
  env.NO_PROXY = merged
  env.no_proxy = merged
}

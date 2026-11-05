/*
 * The Workers runtime names that `worker/index.ts` and `worker/robots.ts`
 * use, declared for the unit-test project (`tsconfig.test.json`) only.
 *
 * `workerTutorRobots.test.ts` imports the worker, so this project compiles
 * the worker source too. It uses the DOM lib, whose globals conflict with
 * @cloudflare/workers-types (see `worker/tsconfig.json`'s own comment), so it
 * cannot load that package. The worker project still typechecks the same
 * source against the real package; these are the slices the test stubs
 * provide, nothing more. No other project includes this file.
 */

interface CacheStorage {
  /** Cloudflare's per-colo cache (`caches.default`). */
  readonly default: Cache
}

interface Fetcher {
  fetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response>
}

interface ExecutionContext {
  waitUntil(promise: Promise<unknown>): void
  passThroughOnException(): void
}

interface ExportedHandler<Env = unknown> {
  fetch?: (request: Request, env: Env, ctx: ExecutionContext) => Response | Promise<Response>
}

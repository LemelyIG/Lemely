import { describe, expect, it } from "vitest"
import {
  DEFAULT_DB_URL,
  E2E_DATABASE_NAME,
  LIBPQ_OVERRIDE_VARS,
  bypassProxyForLoopback,
  e2eDatabaseUrl,
  scrubLibpqOverrides,
} from "../../e2e/e2e-env.ts"

/**
 * The guards `playwright.config.ts` applies before any process of an e2e run starts:
 * which database the run is pointed at, and the ambient environment it must not inherit.
 * Each case pins a way a run could otherwise leave `lemely_e2e` without any name check
 * noticing.
 */
describe("e2eDatabaseUrl", () => {
  it("swaps only the database name and selects the psycopg driver", () => {
    expect(e2eDatabaseUrl("postgresql://postgres:secret@127.0.0.1:54322/postgres")).toBe(
      `postgresql+psycopg://postgres:secret@127.0.0.1:54322/${E2E_DATABASE_NAME}`,
    )
  })

  it("falls back to the stock local stack when supabase status omits DB_URL", () => {
    expect(e2eDatabaseUrl(undefined)).toBe(e2eDatabaseUrl(DEFAULT_DB_URL))
    expect(e2eDatabaseUrl(undefined)).toContain("@127.0.0.1:54322/lemely_e2e")
  })

  it.each([
    "?dbname=postgres",
    "?hostaddr=10.0.0.5",
    "?host=db.example.com",
    "?sslmode=disable",
    "#fragment",
  ])("refuses a DB_URL carrying %s instead of passing it on to libpq", (suffix) => {
    expect(() => e2eDatabaseUrl(`postgresql://postgres:secret@127.0.0.1:54322/postgres${suffix}`)).toThrow(
      /query string or fragment/,
    )
  })

  it("does not echo the credentials when it refuses", () => {
    let message = ""
    try {
      e2eDatabaseUrl("postgresql://postgres:hunter2@127.0.0.1:54322/postgres?dbname=postgres")
    } catch (err) {
      message = String(err)
    }
    expect(message).not.toBe("")
    expect(message).not.toContain("hunter2")
  })
})

describe("scrubLibpqOverrides", () => {
  it("deletes PGHOSTADDR, PGSERVICE and PGSERVICEFILE and nothing else", () => {
    const env: NodeJS.ProcessEnv = {
      PGHOSTADDR: "10.0.0.5",
      PGSERVICE: "prod",
      PGSERVICEFILE: "/home/someone/.pg_service.conf",
      PGPASSWORD: "kept",
      PATH: "/usr/bin",
    }
    scrubLibpqOverrides(env)
    expect(env).toEqual({ PGPASSWORD: "kept", PATH: "/usr/bin" })
  })

  it("covers exactly the variables that can override the explicit host", () => {
    expect([...LIBPQ_OVERRIDE_VARS].sort()).toEqual(["PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE"])
  })
})

describe("bypassProxyForLoopback", () => {
  it("adds the loopback names under both cases and leaves the proxy variables alone", () => {
    const env: NodeJS.ProcessEnv = { HTTP_PROXY: "http://proxy.corp:3128", HTTPS_PROXY: "http://proxy.corp:3128" }
    bypassProxyForLoopback(env)
    expect(env.NO_PROXY).toBe("127.0.0.1,localhost,::1")
    expect(env.no_proxy).toBe(env.NO_PROXY)
    expect(env.HTTP_PROXY).toBe("http://proxy.corp:3128")
    expect(env.HTTPS_PROXY).toBe("http://proxy.corp:3128")
  })

  it("keeps existing entries from either case, once, and trims them", () => {
    const env: NodeJS.ProcessEnv = { NO_PROXY: "internal.corp, localhost", no_proxy: ".svc,127.0.0.1" }
    bypassProxyForLoopback(env)
    expect(env.NO_PROXY).toBe("internal.corp,localhost,.svc,127.0.0.1,::1")
    expect(env.no_proxy).toBe(env.NO_PROXY)
  })
})

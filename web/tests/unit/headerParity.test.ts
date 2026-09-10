import { readFileSync } from "node:fs"
import { join } from "node:path"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"

/**
 * Packet A6 review fix (HIGH 2 root cause, MEDIUM 5 / addendum M5) — this
 * product ships the same five security headers from three independent
 * deploy targets (`public/_headers` for Cloudflare Pages/Workers Static
 * Assets, `nginx.conf` for the Docker/nginx deploy, `worker/index.ts` for
 * the Cloudflare Worker's `/api/*` proxy hop), each written by hand in a
 * different syntax. `headers.test.ts` and the worker source only ever
 * proved each file's OWN content was internally correct — nothing proved
 * the three stayed in agreement with each other, which is exactly the kind
 * of drift HIGH 2 turned out to be (nginx.conf's five headers existed but
 * only reached 3 of 5 locations). This test reads all three and cross-
 * checks every value.
 */

const ROOT = fileURLToPath(new URL("../../", import.meta.url))

const headersFile = readFileSync(join(ROOT, "public/_headers"), "utf8")
const nginxConf = readFileSync(join(ROOT, "nginx.conf"), "utf8")
const workerSource = readFileSync(join(ROOT, "worker/index.ts"), "utf8")

const HEADER_NAMES = [
  "Strict-Transport-Security",
  "X-Content-Type-Options",
  "Referrer-Policy",
  "Permissions-Policy",
  "Content-Security-Policy",
] as const

/** `public/_headers`' Netlify/Cloudflare-style format: `  Name: value`,
 * one per line, no quoting. */
function valueFromHeadersFile(name: string): string | null {
  const match = headersFile.match(new RegExp(`^ {2}${name}: (.+)$`, "m"))
  return match ? match[1].trim() : null
}

/** Every `add_header Name "value"` occurrence in nginx.conf for `name` —
 * there should be one per location that carries it (server scope plus the
 * three Cache-Control locations that must repeat it, per nginx's
 * per-context add_header inheritance — see nginx.conf's own comment). */
function valuesFromNginxConf(name: string): string[] {
  const re = new RegExp(`add_header ${name} "((?:[^"\\\\]|\\\\.)*)"`, "g")
  return [...nginxConf.matchAll(re)].map((m) => m[1])
}

/** `out.headers.set("Name", "value")` in worker/index.ts. */
function valueFromWorkerSource(name: string): string | null {
  const match = workerSource.match(new RegExp(`headers\\.set\\(\\s*"${name}",\\s*"([^"]+)"`))
  return match ? match[1] : null
}

describe("security header parity across the three deploy targets", () => {
  it.each(HEADER_NAMES)("%s is defined in all three files", (name) => {
    expect(valueFromHeadersFile(name), `missing from public/_headers`).not.toBeNull()
    expect(valuesFromNginxConf(name).length, `missing from nginx.conf`).toBeGreaterThan(0)
    expect(valueFromWorkerSource(name), `missing from worker/index.ts`).not.toBeNull()
  })

  it.each(HEADER_NAMES)("%s carries the identical value in all three files", (name) => {
    const fromHeadersFile = valueFromHeadersFile(name)
    const fromNginx = valuesFromNginxConf(name)
    const fromWorker = valueFromWorkerSource(name)

    for (const nginxValue of fromNginx) {
      expect(nginxValue, `nginx.conf's ${name} disagrees with public/_headers`).toBe(
        fromHeadersFile,
      )
    }
    expect(fromWorker, `worker/index.ts's ${name} disagrees with public/_headers`).toBe(
      fromHeadersFile,
    )
  })

  it("nginx.conf declares every header at server scope, plus once more in each of the three Cache-Control locations (HIGH 2 regression guard)", () => {
    for (const name of HEADER_NAMES) {
      // 1 at server scope (inherited by /api/ and the SPA-fallback /) + 3
      // repeats (index.html, sw.js, /assets/ — each sets its own
      // Cache-Control, which per nginx's inheritance rule means it does NOT
      // inherit the server-level headers and must repeat them).
      expect(valuesFromNginxConf(name).length, `${name} should appear 4 times`).toBe(4)
    }
  })
})

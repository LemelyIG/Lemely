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

/**
 * Every `location ... { ... }` block body in an nginx config — a plain,
 * non-nested match (nginx.conf has no location block nested inside another),
 * so a body is just "everything between this block's braces."
 */
function parseLocationBlocks(conf: string): string[] {
  return [...conf.matchAll(/location\s+[^{]*\{([^}]*)\}/g)].map((m) => m[1])
}

/** True when `block` sets its own `Cache-Control` — nginx's `add_header`
 * inheritance is all-or-nothing per context (see nginx.conf's own comment
 * on the server block), so a location that does this does NOT inherit the
 * server-scope security headers and must repeat every one of them itself. */
function setsOwnCacheControl(block: string): boolean {
  return /add_header Cache-Control/.test(block)
}

function blockDeclaresHeader(block: string, name: string): boolean {
  return new RegExp(`add_header ${name} `).test(block)
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

  /*
   * The predecessor of this test asserted `valuesFromNginxConf(name).length
   * === 4` — a file-wide COUNT with no check of which location block each
   * occurrence sits inside. That is provably too weak to be the HIGH 2
   * regression guard it claimed to be: a 4th Cache-Control location added
   * with all 5 security headers omitted leaves every header's total count
   * at 4 (unchanged), so the count-based test would still pass while
   * silently reintroducing HIGH 2's exact partial-coverage bug. This
   * asserts the actual invariant structurally instead — per location
   * block, not per file.
   */
  it("every nginx.conf location that sets its own Cache-Control repeats all 5 security headers (HIGH 2 regression guard, structural)", () => {
    const cacheControlBlocks = parseLocationBlocks(nginxConf).filter(setsOwnCacheControl)
    // A parser that silently matched nothing would make every assertion
    // below vacuously true — this is what stops that from reading as green.
    expect(
      cacheControlBlocks.length,
      "expected to find at least one Cache-Control location in nginx.conf",
    ).toBeGreaterThan(0)

    for (const block of cacheControlBlocks) {
      for (const name of HEADER_NAMES) {
        expect(
          blockDeclaresHeader(block, name),
          `a Cache-Control location in nginx.conf is missing add_header ${name}`,
        ).toBe(true)
      }
    }
  })

  /*
   * Canary for the structural check itself — the same discipline
   * `queryStateGate.test.ts`'s "detects Overview.tsx" test and
   * `failureCopy.test.ts` apply to their own detectors: prove the detector
   * actually flags the exact bug shape (HIGH 2 — a Cache-Control location
   * missing a security header) rather than trusting it silently. Built from
   * a string literal, not read from disk, because the point is the parsing
   * functions' own behaviour on a known-bad shape.
   */
  it("the structural check actually catches a Cache-Control location missing a security header (canary)", () => {
    const badConf = `
      server {
        add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;

        location = /bad.js {
          add_header Cache-Control "no-cache";
          add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
          add_header X-Content-Type-Options "nosniff" always;
          add_header Referrer-Policy "strict-origin-when-cross-origin" always;
          add_header Permissions-Policy "camera=(self)" always;
          # Content-Security-Policy omitted — the exact HIGH 2 shape.
        }
      }
    `
    const cacheControlBlocks = parseLocationBlocks(badConf).filter(setsOwnCacheControl)
    expect(cacheControlBlocks.length).toBe(1)
    expect(blockDeclaresHeader(cacheControlBlocks[0], "Content-Security-Policy")).toBe(false)
    expect(blockDeclaresHeader(cacheControlBlocks[0], "X-Content-Type-Options")).toBe(true)
  })
})

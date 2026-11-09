import { afterEach, describe, expect, it, vi } from "vitest"

import worker, { type Env } from "../../worker/index.ts"

/*
 * The Worker stamps every request it forwards to the backend with the shared edge secret
 * (X-Lemely-Edge-Secret) and the Cloudflare-verified client address (CF-Connecting-IP), and a
 * visitor-supplied value of either is never passed through. The backend's edge guard
 * (lemely/web/edge.py) relies on exactly this.
 */

const ctx = { waitUntil: () => {}, passThroughOnException: () => {} }
const assets = { fetch: () => Promise.resolve(new Response("")) } as unknown as Fetcher

function env(secret?: string): Env {
  return { BACKEND_URL: "https://backend.invalid", ASSETS: assets, ORIGIN_SECRET: secret }
}

async function forwarded(secret: string | undefined, inbound: Record<string, string>) {
  let seen: Request | undefined
  vi.stubGlobal("fetch", (input: Request) => {
    seen = input
    return Promise.resolve(new Response("{}", { status: 200 }))
  })
  const request = new Request("https://lemelyig.com/api/waitlist/config", { headers: inbound })
  await worker.fetch(request, env(secret), ctx)
  if (!seen) throw new Error("the Worker did not forward the request")
  return seen.headers
}

afterEach(() => vi.unstubAllGlobals())

describe("Worker edge stamping", () => {
  it("sends the configured secret and the edge-verified client IP", async () => {
    const headers = await forwarded("s3cret", { "CF-Connecting-IP": "203.0.113.9" })
    expect(headers.get("X-Lemely-Edge-Secret")).toBe("s3cret")
    expect(headers.get("CF-Connecting-IP")).toBe("203.0.113.9")
  })

  it("replaces a secret the visitor supplied", async () => {
    const headers = await forwarded("s3cret", {
      "CF-Connecting-IP": "203.0.113.9",
      "X-Lemely-Edge-Secret": "forged",
    })
    expect(headers.get("X-Lemely-Edge-Secret")).toBe("s3cret")
  })

  it("drops a visitor-supplied secret when the Worker has none", async () => {
    const headers = await forwarded(undefined, {
      "CF-Connecting-IP": "203.0.113.9",
      "X-Lemely-Edge-Secret": "forged",
    })
    expect(headers.has("X-Lemely-Edge-Secret")).toBe(false)
  })

  it("never forwards a client-chosen CF-Connecting-IP when Cloudflare supplied none", async () => {
    const headers = await forwarded("s3cret", {})
    expect(headers.has("CF-Connecting-IP")).toBe(false)
  })
})

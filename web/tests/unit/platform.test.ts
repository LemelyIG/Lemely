import { readFileSync } from "node:fs"
import { join } from "node:path"
import { fileURLToPath } from "node:url"
import { runInNewContext } from "node:vm"
import { describe, expect, it } from "vitest"
import { isNativeFrame, PHONE_MEDIA } from "@/lib/useNativeFrame"
import { resolvePlatform, type Platform } from "@/lib/platform"

const ROOT = fileURLToPath(new URL("../../", import.meta.url))

const UA = {
  iphone: "Mozilla/5.0 (iPhone; CPU iPhone OS 26_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.0 Mobile/15E148 Safari/604.1",
  ipadOs: "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.0 Safari/605.1.15",
  mac: "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
  android: "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Mobile Safari/537.36",
  linux: "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
  crios: "Mozilla/5.0 (iPhone; CPU iPhone OS 26_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/141.0 Mobile/15E148 Safari/604.1",
}

const CASES: [string, Parameters<typeof resolvePlatform>[0], Platform][] = [
  ["iPhone Safari", { userAgent: UA.iphone, maxTouchPoints: 5 }, "ios"],
  ["iPhone Chrome (CriOS)", { userAgent: UA.crios, maxTouchPoints: 5 }, "ios"],
  ["iPadOS desktop UA with touch", { userAgent: UA.ipadOs, maxTouchPoints: 5 }, "ios"],
  ["real Mac (no touch)", { userAgent: UA.mac, maxTouchPoints: 0 }, "other"],
  ["Android Chrome via UA-CH", { uaDataPlatform: "Android", userAgent: UA.android, maxTouchPoints: 5 }, "android"],
  ["Android via UA fallback", { uaDataPlatform: null, userAgent: UA.android, maxTouchPoints: 5 }, "android"],
  // Playwright emulation on a Linux host: UA-CH still says "Linux"; the UA string decides.
  ["iPhone UA on a Linux host", { uaDataPlatform: "Linux", userAgent: UA.iphone, maxTouchPoints: 5 }, "ios"],
  ["desktop Linux", { uaDataPlatform: "Linux", userAgent: UA.linux, maxTouchPoints: 0 }, "other"],
]

describe("resolvePlatform", () => {
  it.each(CASES)("%s", (_name, input, want) => {
    expect(resolvePlatform(input)).toBe(want)
  })
})

/** Run public/shell-init.js in a sandbox and return the data-platform it set. */
function shellInitPlatform(input: Parameters<typeof resolvePlatform>[0]): string | undefined {
  const source = readFileSync(join(ROOT, "public/shell-init.js"), "utf8")
  const html = { dataset: {} as Record<string, string> }
  runInNewContext(source, {
    document: {
      documentElement: html,
      querySelector: () => null,
      getElementById: () => ({ dataset: {} }),
      addEventListener: () => {},
    },
    navigator: {
      userAgent: input.userAgent,
      maxTouchPoints: input.maxTouchPoints,
      userAgentData: input.uaDataPlatform ? { platform: input.uaDataPlatform } : undefined,
    },
    localStorage: { getItem: () => null },
    matchMedia: () => ({ matches: false }),
    window: { matchMedia: () => ({ matches: false }) },
    location: { pathname: "/student" },
  })
  return html.dataset.platform
}

describe("shell-init.js sets html[data-platform] before paint, same table as resolvePlatform", () => {
  it.each(CASES)("%s", (_name, input, want) => {
    expect(shellInitPlatform(input)).toBe(want)
  })
})

describe("native frame = phone width AND ios|android", () => {
  it("the phone media query is the shell-sm edge (721px - 1)", () => {
    expect(PHONE_MEDIA).toBe("(max-width: 720px)")
  })
  it.each([
    ["ios", true, true],
    ["android", true, true],
    ["other", true, false],
    ["ios", false, false],
  ] as const)("%s phone=%s -> %s", (platform, phone, want) => {
    expect(isNativeFrame(platform, phone)).toBe(want)
  })
})

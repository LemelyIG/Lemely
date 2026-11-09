import { readFileSync } from "node:fs"
import { join } from "node:path"
import { fileURLToPath } from "node:url"
import { runInNewContext } from "node:vm"
import { afterEach, describe, expect, it } from "vitest"
import { isNativeFrame, PHONE_MEDIA } from "@/lib/useNativeFrame"
import { readPlatform, type Platform } from "@/lib/platform"

const ROOT = fileURLToPath(new URL("../../", import.meta.url))
const SHELL_INIT = join(ROOT, "public/shell-init.js")

const UA = {
  iphone: "Mozilla/5.0 (iPhone; CPU iPhone OS 26_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.0 Mobile/15E148 Safari/604.1",
  ipadOs: "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.0 Safari/605.1.15",
  mac: "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
  android: "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Mobile Safari/537.36",
  linux: "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
  crios: "Mozilla/5.0 (iPhone; CPU iPhone OS 26_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/141.0 Mobile/15E148 Safari/604.1",
}

interface NavInput {
  uaDataPlatform?: string | null
  userAgent: string
  maxTouchPoints: number
}

const CASES: [string, NavInput, Platform][] = [
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

interface Sandbox {
  htmlDataset: Record<string, string>
  rootDataset: Record<string, string>
}

/** Run public/shell-init.js in a vm sandbox with the given navigator. */
function runShellInit(navigator: object): Sandbox {
  const source = readFileSync(SHELL_INIT, "utf8")
  const htmlDataset: Record<string, string> = {}
  const rootDataset: Record<string, string> = {}
  runInNewContext(source, {
    document: {
      documentElement: { dataset: htmlDataset },
      querySelector: () => null,
      getElementById: () => ({ dataset: rootDataset }),
      addEventListener: () => {},
    },
    navigator,
    localStorage: { getItem: () => null },
    window: { matchMedia: () => ({ matches: false }) },
    location: { pathname: "/student" },
  })
  return { htmlDataset, rootDataset }
}

function navigatorFor(input: NavInput): object {
  return {
    userAgent: input.userAgent,
    maxTouchPoints: input.maxTouchPoints,
    userAgentData: input.uaDataPlatform ? { platform: input.uaDataPlatform } : undefined,
  }
}

describe("shell-init.js is the platform resolver: it sets html[data-platform] before paint", () => {
  it.each(CASES)("%s", (_name, input, want) => {
    expect(runShellInit(navigatorFor(input)).htmlDataset.platform).toBe(want)
  })

  it("a throwing navigator getter leaves data-platform unset but still runs theme and data-shell", () => {
    const hostile = {
      get userAgent(): string {
        throw new Error("navigator blocked")
      },
    }
    const { htmlDataset, rootDataset } = runShellInit(hostile)
    expect(htmlDataset.platform).toBeUndefined()
    expect(htmlDataset.theme).toBe("light")
    expect(rootDataset.shell).toBe("portal")
  })
})

describe("readPlatform reads html[data-platform] back", () => {
  const g = globalThis as { document?: unknown }
  const original = g.document
  afterEach(() => {
    g.document = original
  })

  function withAttribute(value: string | undefined): void {
    g.document = { documentElement: { dataset: value === undefined ? {} : { platform: value } } }
  }

  it.each([["ios"], ["android"], ["other"]] as const)("maps %s to itself", (value) => {
    withAttribute(value)
    expect(readPlatform()).toBe(value)
  })

  it.each([["windows"], [""], [undefined]])("maps unknown or missing (%s) to other", (value) => {
    withAttribute(value)
    expect(readPlatform()).toBe("other")
  })

  it("returns other when there is no document", () => {
    g.document = undefined
    expect(readPlatform()).toBe("other")
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
    ["android", false, false],
    ["other", false, false],
  ] as const)("%s phone=%s -> %s", (platform, phone, want) => {
    expect(isNativeFrame(platform, phone)).toBe(want)
  })
})

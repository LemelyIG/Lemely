import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { cn, downloadCsv, greetingFor, initialsOf, relativeTime } from "@/lib/utils"

describe("cn", () => {
  it("merges conditional inputs the way clsx does", () => {
    const off: boolean = false
    expect(cn("a", off && "b", undefined, ["c", { d: true, e: false }])).toBe("a c d")
  })

  it("lets a later Tailwind utility win over an earlier conflicting one", () => {
    expect(cn("p-2", "p-4")).toBe("p-4")
  })

  /*
   * The reason `extendTailwindMerge` is there at all. Without the
   * CUSTOM_FONT_SIZE_CLASSES registration, `text-display-md` falls into
   * twMerge's `text-color` group, collides with the real colour `text-t1`, and
   * one of the two is silently dropped — degrading to inherited type rather
   * than to a visible error. That shipped live in five shared C-* components
   * before P3.10 chunk c.
   *
   * `design-tokens.test.ts` proves the same property exhaustively across every
   * registered name and against `index.css`; this case pins the specific shape
   * the bug took, through `cn` itself rather than through a rebuilt twMerge.
   */
  it("keeps a custom type class and a colour class together, in both orders", () => {
    expect(cn("text-display-md", "text-t1").split(" ").sort()).toEqual(["text-display-md", "text-t1"])
    expect(cn("text-t1", "text-display-md").split(" ").sort()).toEqual(["text-display-md", "text-t1"])
  })

  it("still collapses two custom type classes to the later one", () => {
    expect(cn("text-dense", "text-display-md")).toBe("text-display-md")
  })
})

describe("relativeTime", () => {
  const NOW = new Date("2026-08-07T12:00:00.000Z")

  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(NOW)
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  const ago = (ms: number) => new Date(NOW.getTime() - ms).toISOString()
  const MIN = 60_000
  const HOUR = 60 * MIN
  const DAY = 24 * HOUR

  it.each([
    ["just now", 0],
    ["just now", 59_999],
    ["1m ago", MIN],
    ["59m ago", 59 * MIN],
    ["1h ago", HOUR],
    ["23h ago", 23 * HOUR],
    ["1d ago", DAY],
    ["29d ago", 29 * DAY],
    // `relativeTime` uses a flat 30-day month and a 12-month year, so the
    // boundaries are exact multiples, not calendar dates. That imprecision is
    // intended for a glance-level label; pinning it here stops someone
    // "fixing" it into calendar arithmetic without deciding to.
    ["1mo ago", 30 * DAY],
    ["11mo ago", 11 * 30 * DAY],
    ["1y ago", 12 * 30 * DAY],
    ["2y ago", 24 * 30 * DAY],
  ])("renders %s", (expected, elapsed) => {
    expect(relativeTime(ago(elapsed))).toBe(expected)
  })

  it("reads a future timestamp as 'just now' rather than a negative duration", () => {
    // Clock skew between the server's `recordedAt` and the browser is real and
    // the label must not read "-3m ago". `Math.floor` of a negative is < 1, so
    // the first branch catches it — asserted so a refactor to `Math.round` or
    // an absolute value can't silently change it.
    expect(relativeTime(ago(-5 * MIN))).toBe("just now")
  })
})

describe("initialsOf", () => {
  it("takes the first letter of each space-separated word", () => {
    expect(initialsOf("Yassin Diab")).toBe("YD")
    expect(initialsOf("Maya")).toBe("M")
    expect(initialsOf("Ada Byron King Lovelace")).toBe("ABKL")
  })

  it("returns an empty string for an empty name", () => {
    expect(initialsOf("")).toBe("")
  })

  /*
   * A doubled or trailing space yields an empty segment, so `w[0]` is
   * `undefined` — but `Array.join` renders `undefined` as an empty string
   * rather than the literal "undefined", so the initials come out clean. That
   * is load-bearing and easy to break: a refactor to `.map(w => String(w[0]))`
   * or a template literal would put "undefined" inside an avatar. Pinned here
   * because it holds by accident, not by design.
   */
  it("skips empty segments from doubled or trailing spaces", () => {
    expect(initialsOf("Ada  Lovelace")).toBe("AL")
    expect(initialsOf("Ada Lovelace ")).toBe("AL")
  })
})

describe("downloadCsv", () => {
  /*
   * `environment: "node"` (see vitest.config.ts), so `document` does not
   * exist. Rather than pull in jsdom for one function, the anchor is stubbed:
   * what is worth testing here is the RFC 4180 escaping and the filename
   * slug, both pure string work. The Blob/anchor/click dance itself is
   * browser plumbing that a stub cannot meaningfully verify anyway — it is
   * exercised for real by the T-04/T-10 export paths in the Playwright suite.
   *
   * Node ≥16.7 provides `Blob` and `URL.createObjectURL`/`revokeObjectURL`
   * natively, so only `document` needs faking.
   */
  let anchor: { href: string; download: string; click: () => void }

  beforeEach(() => {
    anchor = { href: "", download: "", click: vi.fn() }
    vi.stubGlobal("document", { createElement: () => anchor })
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  const capture = async (rows: string[][]): Promise<string> => {
    const seen: Blob[] = []
    const real = URL.createObjectURL.bind(URL)
    const spy = vi.spyOn(URL, "createObjectURL").mockImplementation((blob: Blob | MediaSource) => {
      seen.push(blob as Blob)
      return real(blob)
    })
    try {
      downloadCsv("x", rows)
    } finally {
      spy.mockRestore()
    }
    expect(seen).toHaveLength(1)
    return await seen[0].text()
  }

  it("quotes only the cells that need it, doubling embedded quotes", async () => {
    const csv = await capture([
      ["topic", "note"],
      ["Forces", "plain"],
      ["Waves", 'has "quotes"'],
      ["Energy", "has,comma"],
      ["Momentum", "has\nnewline"],
    ])
    expect(csv).toBe(
      ["topic,note", "Forces,plain", 'Waves,"has ""quotes"""', 'Energy,"has,comma"', 'Momentum,"has\nnewline"'].join(
        "\n",
      ),
    )
  })

  it("slugifies the caller's human filename label", () => {
    downloadCsv("Y11 Physics — quiz 3", [["a"]])
    expect(anchor.download).toBe("y11-physics-quiz-3.csv")
  })

  it("clicks the anchor exactly once", () => {
    downloadCsv("x", [["a"]])
    expect(anchor.click).toHaveBeenCalledTimes(1)
  })
})

/*
 * P3.2. The student Overview greeted every reader with "Good afternoon"
 * unconditionally, at every hour of the day, and the teacher Overview with
 * "Good morning." — the first line of the first screen in both portals, and
 * the one sentence on either page that was reliably false for most readers.
 * Students revise at night.
 *
 * Boundaries get their own cases because that is the whole of this function:
 * an off-by-one here is invisible in review and wrong for exactly one hour a
 * day, which is the kind of defect that survives for years.
 */
describe("greetingFor", () => {
  it.each([
    [5, "Good morning"],
    [8, "Good morning"],
    [11, "Good morning"],
    [12, "Good afternoon"],
    [15, "Good afternoon"],
    [17, "Good afternoon"],
    [18, "Good evening"],
    [22, "Good evening"],
    [23, "Good evening"],
  ])("greets hour %i with %s", (hour, expected) => {
    expect(greetingFor(hour)).toBe(expected)
  })

  /*
   * Evening deliberately wraps past midnight rather than flipping to morning
   * at 00:00. "Good morning" at two in the morning is the same error in the
   * other direction, and a student still working then has not started their
   * morning yet.
   */
  it.each([0, 2, 4])("still says evening at %i:00, not morning", (hour) => {
    expect(greetingFor(hour)).toBe("Good evening")
  })

  it("covers all 24 hours with no gap", () => {
    for (let hour = 0; hour < 24; hour += 1) {
      expect(["Good morning", "Good afternoon", "Good evening"]).toContain(greetingFor(hour))
    }
  })
})

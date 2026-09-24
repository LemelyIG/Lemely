import { describe, expect, it } from "vitest"
import fs from "node:fs"
import path from "node:path"
import { ApiError } from "@/lib/api"
import {
  RETENTION_DAYS,
  deleteCountdown,
  deletionRefusal,
  formatDay,
  isDeletionRefusal,
} from "@/lib/paperDeletion"
import type { DeletionRefusal } from "@/lib/studentTypes"

function iso(s: string): string {
  return s
}

const repoRoot = path.resolve(__dirname, "../../..")

describe("RETENTION_DAYS", () => {
  it("pins to lemely/core/deletion.py's RETENTION_DAYS, so the two cannot drift apart", () => {
    const source = fs.readFileSync(path.join(repoRoot, "lemely/core/deletion.py"), "utf8")
    const match = source.match(/^RETENTION_DAYS\s*=\s*(\d+)/m)
    expect(match, "RETENTION_DAYS not found in lemely/core/deletion.py").not.toBeNull()
    expect(RETENTION_DAYS).toBe(Number(match![1]))
  })
})

describe("formatDay", () => {
  it("reads day-then-month, no year, regardless of host locale", () => {
    expect(formatDay(iso("2026-10-21T00:00:00Z"))).toBe("21 October")
  })
})

describe("deleteCountdown", () => {
  it("floors to whole days", () => {
    expect(deleteCountdown(iso("2026-10-21T12:00:00Z"), iso("2026-09-22T00:00:00Z"))).toBe(29)
  })

  it("reads a past deadline as gone, never as negative", () => {
    expect(deleteCountdown(iso("2026-09-01T00:00:00Z"), iso("2026-09-22T00:00:00Z"))).toBe(0)
  })

  it("reads the exact deadline instant as gone", () => {
    expect(deleteCountdown(iso("2026-09-22T00:00:00Z"), iso("2026-09-22T00:00:00Z"))).toBe(0)
  })
})

describe("deletionRefusal", () => {
  it("renders the hold with its date and no reason", () => {
    const copy = deletionRefusal({
      detail: "This paper can't be deleted yet.",
      deletableFrom: "2026-10-21T00:00:00Z",
    })
    expect(copy).toBe("This paper can't be deleted yet. You'll be able to delete it from 21 October.")
    expect(copy).not.toMatch(/review|flag|plagiar|integrity|score/i)
  })

  it("renders the non-hold refusal with no date sentence appended", () => {
    const copy = deletionRefusal({ detail: "Only uploaded papers can be deleted." })
    expect(copy).toBe("Only uploaded papers can be deleted.")
  })

  it("the forbidden-word check would catch a leak", () => {
    expect("flagged for plagiarism").toMatch(/review|flag|plagiar|integrity|score/i)
  })
})

describe("isDeletionRefusal", () => {
  it("accepts the flat hold shape", () => {
    expect(
      isDeletionRefusal({ detail: "This paper can't be deleted yet.", deletableFrom: "2026-10-21T00:00:00Z" }),
    ).toBe(true)
  })

  it("accepts the shape with no deletableFrom at all", () => {
    expect(isDeletionRefusal({ detail: "Only uploaded papers can be deleted." })).toBe(true)
  })

  it("rejects a bare string — the exact value err.detail carries on its own", () => {
    expect(isDeletionRefusal("This paper can't be deleted yet.")).toBe(false)
  })

  it("rejects null, undefined, and an unrelated object", () => {
    expect(isDeletionRefusal(null)).toBe(false)
    expect(isDeletionRefusal(undefined)).toBe(false)
    expect(isDeletionRefusal({ reason: "device_limit_reached" })).toBe(false)
  })
})

describe("the real request() error-parsing path (Task 14 review, Critical 1)", () => {
  /*
   * `parseErrorBody` is the exact function `request()`, `streamActivity()`
   * and `uploadWithProgress()` all call on a non-OK response — this test
   * runs a real 409 body through it, then through `isDeletionRefusal` and
   * `deletionRefusal`, the same two functions `PaperResult.tsx`'s
   * `handleConfirm` calls. A hand-built `ApiError` (the shape the first
   * version of this suite used) can pass while the real parser still drops
   * the field nobody exercised — this is the regression that shipped: the
   * flat 409 body has `deletableFrom` as a SIBLING of `detail`, and the
   * first version read only `err.detail` (a string), cast with `as`, so
   * `deletionRefusal` always rendered `undefined`.
   */
  it("renders a hold's date from the real flat 409 body", async () => {
    const { parseErrorBody } = await import("@/lib/api")
    const bodyText = JSON.stringify({
      detail: "This paper can't be deleted yet.",
      deletableFrom: "2026-10-21T00:00:00Z",
    })
    const { message, detail, body } = parseErrorBody(409, "Conflict", bodyText)
    const err = new ApiError(409, message, detail, undefined, body)

    expect(isDeletionRefusal(err.body)).toBe(true)
    if (!isDeletionRefusal(err.body)) throw new Error("unreachable")
    const copy = deletionRefusal(err.body)
    expect(copy).toBe("This paper can't be deleted yet. You'll be able to delete it from 21 October.")
    expect(copy).not.toMatch(/review|flag|plagiar|integrity|score/i)
  })

  it("renders the non-hold refusal's own sentence, with no date appended", async () => {
    const { parseErrorBody } = await import("@/lib/api")
    const bodyText = JSON.stringify({ detail: "Only uploaded papers can be deleted." })
    const { message, detail, body } = parseErrorBody(409, "Conflict", bodyText)
    const err = new ApiError(409, message, detail, undefined, body)

    expect(isDeletionRefusal(err.body)).toBe(true)
    if (!isDeletionRefusal(err.body)) throw new Error("unreachable")
    expect(deletionRefusal(err.body)).toBe("Only uploaded papers can be deleted.")
  })

  it("would have caught the regression: reading err.detail (a string) as a DeletionRefusal renders nothing", () => {
    // This is the exact defect: `detail` is ONLY the `detail` key's own
    // value (a string here), never the sibling `deletableFrom`. Casting it
    // with `as DeletionRefusal` produces an object-shaped type over a
    // string value — `.detail`/`.deletableFrom` are both `undefined` at
    // runtime. `isDeletionRefusal` — the guard that replaced the cast —
    // correctly refuses it.
    const detail = "This paper can't be deleted yet." as unknown as DeletionRefusal
    expect(isDeletionRefusal(detail)).toBe(false)
  })

  it("parseErrorBody keeps `detail` unchanged for an existing nested-detail body (no regression)", async () => {
    const { parseErrorBody } = await import("@/lib/api")
    // Placement's own 409 shape (api.ts's own `detail` doc comment): a full
    // structured object AS the `detail` value, not a sibling of it.
    const bodyText = JSON.stringify({
      detail: { reason: "device_limit_reached", devices: [{ id: "d1" }] },
    })
    const { detail, body } = parseErrorBody(409, "Conflict", bodyText)
    expect(detail).toEqual({ reason: "device_limit_reached", devices: [{ id: "d1" }] })
    expect(body).toEqual({ detail: { reason: "device_limit_reached", devices: [{ id: "d1" }] } })
  })
})

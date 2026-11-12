import { describe, expect, it } from "vitest"
import { ALLOWED_AVATAR_TYPES, MAX_AVATAR_BYTES, validateAvatarFile } from "@/lib/avatarUpload"

/*
 * Profile settings' client-side avatar checks. Pure functions, so these run
 * under `vitest.config.ts`'s `environment: "node"` with no `File`/DOM needed —
 * see the module's own header for why `validateAvatarFile` takes a plain
 * `{ type, size }` object rather than a real `File`.
 */

describe("validateAvatarFile", () => {
  it("accepts every allowed type at a small size", () => {
    for (const type of ALLOWED_AVATAR_TYPES) {
      expect(validateAvatarFile({ type, size: 1024 })).toBeNull()
    }
  })

  it("rejects a disallowed type", () => {
    expect(validateAvatarFile({ type: "image/gif", size: 1024 })?.length).toBeGreaterThan(0)
    expect(validateAvatarFile({ type: "application/pdf", size: 1024 })?.length).toBeGreaterThan(0)
  })

  it("accepts a file at exactly the 5 MiB boundary", () => {
    expect(validateAvatarFile({ type: "image/png", size: MAX_AVATAR_BYTES })).toBeNull()
  })

  it("rejects a file one byte over the 5 MiB boundary", () => {
    const message = validateAvatarFile({ type: "image/png", size: MAX_AVATAR_BYTES + 1 })
    expect(message?.length).toBeGreaterThan(0)
  })

  it("checks type before size, so a huge disallowed file gets the type message", () => {
    const message = validateAvatarFile({ type: "image/gif", size: MAX_AVATAR_BYTES + 1 })
    expect(message).toBe(validateAvatarFile({ type: "image/gif", size: 1024 }))
  })
})

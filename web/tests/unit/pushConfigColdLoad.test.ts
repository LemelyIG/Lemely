import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"

/**
 * Packet A7 — root cause: `PushAutoEnable` (mounted unconditionally in
 * `main.tsx`, above the router, so it runs before any session exists) called
 * `usePushConfig()` with no auth gate at all — confirmed live (chrome-devtools
 * against a local dev server): `GET /api/notifications/push/config` fires
 * on a cold, logged-out load of `/login`, before the reader has ever signed
 * in. `NotificationSettings.tsx`'s own call to the same hook is not the
 * cause — that screen sits behind `RequireAuth` and is unreachable pre-login.
 *
 * Fix: `usePushConfig` takes an `enabled` flag (same shape as
 * `useAdminSchools(enabled: boolean)` in `useSchoolApi.ts`), and
 * `PushAutoEnable` is the one caller that passes `false` pre-session.
 *
 * Neither half is exercisable as a behaviour test here (`useQuery`/effects
 * need a real render, and this suite has no jsdom, D3.20), so both are
 * pinned as source-text gates.
 */

const hookSource = readFileSync(
  join(import.meta.dirname, "..", "..", "src", "lib", "hooks", "useNotificationApi.ts"),
  "utf8",
)
const componentSource = readFileSync(
  join(import.meta.dirname, "..", "..", "src", "components", "push-auto-enable.tsx"),
  "utf8",
)

describe("usePushConfig takes an enabled flag", () => {
  it("declares an enabled parameter, defaulting to true (NotificationSettings.tsx's unauthenticated-unreachable call keeps firing)", () => {
    expect(hookSource).toMatch(/function usePushConfig\(enabled\s*=\s*true\)/)
  })

  it("threads it into useQuery's own enabled option", () => {
    const fnMatch = hookSource.match(/function usePushConfig\([\s\S]*?\n\}/)
    expect(fnMatch).not.toBeNull()
    expect(fnMatch ? fnMatch[0] : "").toMatch(/enabled,/)
  })
})

describe("PushAutoEnable gates usePushConfig on session state", () => {
  it("passes enabled: userId !== null (or equivalent session check) rather than calling it bare", () => {
    expect(componentSource).not.toMatch(/usePushConfig\(\)/)
    expect(componentSource).toMatch(/usePushConfig\(/)
  })
})

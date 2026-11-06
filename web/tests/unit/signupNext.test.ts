import { describe, expect, it } from "vitest"
import { afterVerifyPath, rememberSignupNext, takeSignupNext } from "@/lib/auth/signupNext"
import { safeNextPath } from "@/lib/nextPath"

function memoryStorage(): Storage {
  const m = new Map<string, string>()
  return {
    get length() {
      return m.size
    },
    clear: () => m.clear(),
    getItem: (k) => m.get(k) ?? null,
    key: (i) => [...m.keys()][i] ?? null,
    removeItem: (k) => void m.delete(k),
    setItem: (k, v) => void m.set(k, v),
  }
}

const plans = "/teacher/billing/plans?plan=teacher_pro_m&interval=month"

const BAD = [
  "https://evil.example/x",
  "//evil.example/x",
  "/\\evil.example",
  "/a\\..\\evil",
  "javascript:alert(1)",
  "data:text/html,x",
  "/\tfoo",
  "/\nfoo",
  "/\rfoo",
  "/a\u0000b",
  "\t//evil.example",
  " /x",
  "evil",
  "",
]

describe("signup next", () => {
  it("honours a valid same-origin next once, after verification", () => {
    const s = memoryStorage()
    rememberSignupNext(plans, s)
    expect(afterVerifyPath({ role: "teacher" }, s)).toBe(plans)
    expect(afterVerifyPath({ role: "teacher" }, s)).toBe("/teacher")
  })

  it("rejects external, protocol-relative, backslash, control-char and scheme values", () => {
    for (const bad of BAD) {
      expect(safeNextPath(bad), JSON.stringify(bad)).toBeNull()
      const s = memoryStorage()
      rememberSignupNext(bad, s)
      expect(takeSignupNext(s)).toBeNull()
    }
  })

  it("keeps today's behaviour with no next, and a new signup clears a stale one", () => {
    const s = memoryStorage()
    expect(afterVerifyPath({ role: "student" }, s)).toBe("/student")
    rememberSignupNext(plans, s)
    rememberSignupNext(null, s)
    expect(takeSignupNext(s)).toBeNull()
    expect(afterVerifyPath(null, s)).toBe("/login")
  })

  it("re-validates on read, so every tampered stored value is ignored", () => {
    for (const bad of BAD) {
      const s = memoryStorage()
      s.setItem("lemely.signup.next", bad)
      expect(takeSignupNext(s), JSON.stringify(bad)).toBeNull()
      expect(s.getItem("lemely.signup.next")).toBeNull()
    }
  })

  it("a later remembered value replaces the earlier one", () => {
    const s = memoryStorage()
    rememberSignupNext("/student/billing/plans", s)
    rememberSignupNext(plans, s)
    expect(takeSignupNext(s)).toBe(plans)
  })
})

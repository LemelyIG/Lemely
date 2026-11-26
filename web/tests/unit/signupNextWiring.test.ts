import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"
import { stripComments } from "./support/jsxSource"

const ROOT = join(import.meta.dirname, "..", "..")
const read = (p: string) => stripComments(readFileSync(join(ROOT, p), "utf8"))

describe("signup carries next", () => {
  it("SignupDetails validates next with safeNextPath and remembers it on success", () => {
    const src = read("src/portals/auth/SignupDetails.tsx")
    expect(src).toContain('safeNextPath(searchParams.get("next"))')
    expect(src).toContain("rememberSignupNext(next)")
  })

  it("both verification paths use afterVerifyPath instead of postVerifyPath", () => {
    const src = read("src/portals/auth/VerifyEmail.tsx")
    expect(src.match(/navigate\(afterVerifyPath\(session\), \{ replace: true \}\)/g)?.length).toBe(2)
    expect(src).not.toContain("navigate(postVerifyPath(session)")
  })

  it("the role picker forwards a valid next", () => {
    const src = read("src/portals/auth/SignupRoleSelect.tsx")
    expect(src).toContain('safeNextPath(searchParams.get("next"))')
    expect(src).toContain("withNext(choice.to, next)")
  })
})

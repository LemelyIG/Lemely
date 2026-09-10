import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"
import { stripComments } from "./support/jsxSource"

/*
 * Packet A2 (audit dossier remediation: kb-2, kb-3, kb-4,
 * login-links-under-44px-tap-target) — input attributes and tap targets on
 * the signed-out auth screens.
 *
 * A plain `.ts` source-text gate, not a rendered-component test: this repo's
 * `vitest.config.ts` deliberately runs `environment: "node"` with no jsdom
 * and no @testing-library (see that file's own docstring, D3.20) — component
 * behaviour is Playwright E2E's job. This mirrors the tree-walking gates in
 * this same directory (`a11yRules.test.ts` et al.): read the real source,
 * strip comments so a rule can't fire on prose, and assert the attribute is
 * present inside the one element's open tag it's supposed to be on, not
 * merely somewhere in the file.
 *
 * `SignupParent.tsx`'s case is `enterKeyHint="send"`, not a phone field: the
 * audit finding this packet traces to (`ParentLogin.tsx` PhoneStep, phone-OTP
 * parent login) was retired before this packet started (commit f7fa328,
 * "retire phone login") and replaced by this screen's email → code →
 * password flow — see that file's own module docstring. There is no
 * `<select>` or hand-rolled phone input left to migrate onto the kit
 * components; `enterKeyHint="send"` lands on the email-step Email field
 * instead, the field that actually drives "Send code".
 */

const AUTH_DIR = join(import.meta.dirname, "..", "..", "src", "portals", "auth")

function readSource(file: string): string {
  return stripComments(readFileSync(join(AUTH_DIR, file), "utf8"))
}

/**
 * The self-closing JSX element whose open tag contains `anchor` (e.g. a
 * `label="Password"` prop) — bounds an attribute assertion to the one field
 * it's actually about, rather than letting a substring match land anywhere
 * else in the file.
 */
function elementContaining(source: string, anchor: string): string {
  const anchorIndex = source.indexOf(anchor)
  if (anchorIndex === -1) throw new Error(`anchor not found: ${anchor}`)
  const openIndex = source.lastIndexOf("<", anchorIndex)
  const closeIndex = source.indexOf("/>", anchorIndex)
  if (openIndex === -1 || closeIndex === -1) {
    throw new Error(`unterminated element for anchor: ${anchor}`)
  }
  return source.slice(openIndex, closeIndex + 2)
}

/** The quoted string literal assigned to `const <name> = "..."`. */
function constStringValue(source: string, name: string): string {
  const declIndex = source.indexOf(`const ${name} =`)
  if (declIndex === -1) throw new Error(`const not found: ${name}`)
  const quoteStart = source.indexOf('"', declIndex)
  const quoteEnd = source.indexOf('"', quoteStart + 1)
  return source.slice(quoteStart + 1, quoteEnd)
}

describe("Login.tsx", () => {
  const source = readSource("Login.tsx")

  it("LINK_CLASS gives every text link a real touch target", () => {
    const value = constStringValue(source, "LINK_CLASS")
    expect(value).toContain("inline-flex")
    expect(value).toContain("min-h-11")
    expect(value).toContain("items-center")
  })

  it("the password field submits on Enter", () => {
    const field = elementContaining(source, 'label="Password"')
    expect(field).toContain('enterKeyHint="go"')
  })
})

describe("JoinWithCode.tsx", () => {
  const source = readSource("JoinWithCode.tsx")

  it("the invite code field submits on Enter", () => {
    const field = elementContaining(source, 'label="Invite code"')
    expect(field).toContain('enterKeyHint="go"')
  })
})

describe("SignupDetails.tsx", () => {
  const source = readSource("SignupDetails.tsx")

  it("the Name field capitalizes words and disables autocorrect", () => {
    const field = elementContaining(source, 'label="Name"')
    expect(field).toContain('autoCapitalize="words"')
    expect(field).toContain('autoCorrect="off"')
  })
})

describe("SignupParent.tsx", () => {
  const source = readSource("SignupParent.tsx")

  it("the email-step Email field submits on Enter", () => {
    const field = elementContaining(source, 'label="Email"')
    expect(field).toContain('enterKeyHint="send"')
  })
})

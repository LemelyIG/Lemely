import { readFileSync, existsSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"
import { profileName } from "@/components/shell/ShellAvatar"
import { stripComments } from "./support/jsxSource"

/*
 * The teacher top-bar pieces moved into components/shell and became
 * portal-neutral: no file under components/shell may import a portal, and the
 * old teacher copies are gone (moved, not copied).
 */

const SRC = join(import.meta.dirname, "..", "..", "src")
const SHELL_FILES = ["NotificationsPanel.tsx", "AccountPanel.tsx", "ShellAvatar.tsx", "TopBarSheets.tsx", "shellModel.ts"]

describe("components/shell is portal-neutral", () => {
  it.each(SHELL_FILES)("%s imports no portal module", (file) => {
    const source = stripComments(readFileSync(join(SRC, "components/shell", file), "utf8"))
    expect(source).not.toMatch(/from\s+"@\/portals\/(teacher|student)\//)
    expect(source).not.toMatch(/from\s+"\.\.\/\.\.\/portals\//)
  })

  it.each(["NotificationsMenu.tsx", "ProfileMenu.tsx", "ProfileAvatar.tsx", "TopBarSheets.tsx"])(
    "the teacher copy %s no longer exists",
    (file) => {
      expect(existsSync(join(SRC, "portals/teacher/components", file))).toBe(false)
    },
  )
})

describe("profileName", () => {
  it("uses the display name when set", () => {
    expect(profileName({ displayName: "Mariam", email: "m@x.io" })).toBe("Mariam")
  })
  it("falls back to the email's local part, never an invented name", () => {
    expect(profileName({ displayName: null, email: "mariam.hassan@student.lemely.app" })).toBe("mariam.hassan")
  })
})

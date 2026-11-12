import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"
import { installSettingsVariant } from "@/portals/settings/InstallSettings"

/**
 * A6/A7 follow-up · `InstallSettings.tsx`'s bug was gating its "Install
 * Lemely" button on `canInstall`, which folds in `dismissed` — a Chromium
 * reader who dismissed `InstallBanner` and came to THIS screen specifically
 * to install later was told "Your browser doesn't support installing
 * Lemely as an app yet," which is false and exactly backwards: this
 * screen's own module header says "Reachable even while dismissed: the
 * 14-day cooldown only hides the banner."
 *
 * `installSettingsVariant` fixes this structurally rather than by
 * remembering to pass the right flag: its input has no `dismissed` field at
 * all, so there is no way for this decision to depend on it, unlike
 * `shouldShowInstallAffordance` (`useInstallPrompt.ts`), which correctly
 * DOES fold in `dismissed` for `InstallBanner`'s different job ("don't keep
 * nagging").
 */

describe("installSettingsVariant", () => {
  it("shows the install button whenever a real prompt event exists — the A7 follow-up fix: dismissed is not even a parameter, so a reader who dismissed InstallBanner and came to this screen on purpose still sees it", () => {
    expect(
      installSettingsVariant({ isStandalone: false, hasPromptEvent: true, isIos: false }),
    ).toBe("install")
    // Also true when isIos is true — a real prompt event always wins over
    // iOS's own instructions branch.
    expect(
      installSettingsVariant({ isStandalone: false, hasPromptEvent: true, isIos: true }),
    ).toBe("install")
  })

  it("standalone wins over everything else — already installed", () => {
    expect(
      installSettingsVariant({ isStandalone: true, hasPromptEvent: true, isIos: true }),
    ).toBe("standalone")
  })

  it("falls back to iOS instructions when there is no prompt event", () => {
    expect(
      installSettingsVariant({ isStandalone: false, hasPromptEvent: false, isIos: true }),
    ).toBe("ios")
  })

  it("falls back to the unsupported-browser message only when neither a prompt event nor iOS applies", () => {
    expect(
      installSettingsVariant({ isStandalone: false, hasPromptEvent: false, isIos: false }),
    ).toBe("unsupported")
  })
})

/**
 * Pins the wiring, not just the pure function — same discipline
 * `installPrompt.test.ts`'s "InstallBanner source-text gate" applies to
 * `shouldShowInstallAffordance`: a correct pure function nobody calls (or
 * called with the wrong hook field) fixes nothing.
 */
describe("InstallSettingsSection source-text gate — decides via installSettingsVariant, not canInstall", () => {
  const source = readFileSync(
    join(import.meta.dirname, "..", "..", "src", "portals", "settings", "InstallSettings.tsx"),
    "utf8",
  )

  it("destructures hasPromptEvent from useInstallPrompt", () => {
    expect(source).toMatch(/const\s*\{[^}]*\bhasPromptEvent\b[^}]*\}\s*=\s*useInstallPrompt\(\)/)
  })

  it("calls installSettingsVariant to decide what to render", () => {
    expect(source).toMatch(/installSettingsVariant\(\{/)
  })

  it("does not gate the render decision on canInstall", () => {
    // `canInstall` may still appear (e.g. re-exported types), but must not
    // drive InstallSettingsSection's own conditional rendering — the exact
    // regression this fix closes.
    expect(source).not.toMatch(/canInstall\s*\?/)
    expect(source).not.toMatch(/:\s*canInstall\b/)
  })
})

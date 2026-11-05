/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import { useState } from "react"
import { Radio, RadioGroup } from "@/components/ui/radio"
import { isThemePreference, type ThemePreference } from "@/lib/theme/theme"
import { useTheme } from "@/lib/theme/useTheme"
import { SettingsCard, SettingsSection, SettingsStatus } from "./SettingsRows"

/*
 * Appearance: the theme choice. Stored on this device only (localStorage via
 * `useTheme`); the backend keeps no theme preference, so the copy says
 * "on this device" rather than implying it follows the account.
 *
 * Rendered as its own tab in the teacher Settings dialog, and still inside
 * `ProfileSettingsSection` for the page-based lanes (student, parent, admin),
 * which have no Appearance tab of their own.
 */

const SAVED_COPY: Record<ThemePreference, string> = {
  system: "Saved. Lemely now follows your device setting.",
  light: "Saved. Lemely now uses the light theme on this device.",
  dark: "Saved. Lemely now uses the dark theme on this device.",
}

export function AppearanceSettingsSection() {
  const { preference, setPreference } = useTheme()
  const [saved, setSaved] = useState<ThemePreference | null>(null)

  return (
    <SettingsSection
      title="Theme"
      description="Applies straight away on this device. System follows your device and switches when it does."
    >
      <SettingsCard>
        {/* The group's own legend is the row label: wrapping it in a
            `SettingsRow` would name the same control twice. */}
        <div className="flex flex-col gap-3 px-4 py-4 sm:px-5">
          <RadioGroup
            label="Theme"
            value={preference}
            onValueChange={(value) => {
              if (!isThemePreference(value)) return
              setPreference(value)
              setSaved(value)
            }}
            orientation="horizontal"
          >
            <Radio label="System" value="system" />
            <Radio label="Light" value="light" />
            <Radio label="Dark" value="dark" />
          </RadioGroup>
          {saved ? <SettingsStatus>{SAVED_COPY[saved]}</SettingsStatus> : null}
        </div>
      </SettingsCard>
    </SettingsSection>
  )
}

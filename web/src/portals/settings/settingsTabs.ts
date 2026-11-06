/*
 * The tabs of the Settings dialog, as data.
 *
 * Each tab is its own route under the portal's settings base
 * (`/teacher/settings`, `/teacher/settings/notifications`, ...), so the list
 * here is the single place that decides a tab's label, URL segment and the
 * one-line helper shown under its heading. The route block in
 * `portals/teacher/index.tsx` mounts one child per entry, and
 * `settingsTabs.test.ts` holds the two in step.
 */

export type SettingsTabId =
  | "profile"
  | "account"
  | "notifications"
  | "appearance"
  | "classes"
  | "install"

export interface SettingsTab {
  id: SettingsTabId
  label: string
  /** Path segment under the settings base. `""` is the index route. */
  segment: string
  /** One sentence under the tab's heading saying what lives here. */
  description: string
}

/** The teacher portal's tabs, in rail order. Segments keep the paths the
 * page-based settings already used (`devices`, `notifications`, `install`),
 * so every existing link and bookmark still lands on the same section. */
export const TEACHER_SETTINGS_TABS: readonly SettingsTab[] = [
  {
    id: "profile",
    label: "Profile",
    segment: "",
    description: "How you appear in Lemely, and the time zone your reminders follow.",
  },
  {
    id: "account",
    label: "Account and devices",
    segment: "devices",
    description: "Your sign-in details and every device signed in to your account.",
  },
  {
    id: "notifications",
    label: "Notifications",
    segment: "notifications",
    description: "Choose what you hear about, and when.",
  },
  {
    id: "appearance",
    label: "Appearance",
    segment: "appearance",
    description: "How Lemely looks on this device.",
  },
  {
    id: "classes",
    label: "Classes and grading",
    segment: "classes",
    description:
      "Each class keeps its own name, subject and join code. Open a class to change them.",
  },
  {
    id: "install",
    label: "Install Lemely",
    segment: "install",
    description: "Add Lemely to your home screen for faster access and offline marking.",
  },
]

/** The URL a tab lives at. */
export function settingsTabPath(basePath: string, tab: Pick<SettingsTab, "segment">): string {
  return tab.segment ? `${basePath}/${tab.segment}` : basePath
}

/** The tab a pathname belongs to, or `null` for a path no tab owns (the
 * portal's not-found route then answers it). A trailing slash is ignored. */
export function activeSettingsTab(
  tabs: readonly SettingsTab[],
  basePath: string,
  pathname: string,
): SettingsTab | null {
  const trimmed = pathname.length > 1 ? pathname.replace(/\/+$/, "") : pathname
  return tabs.find((tab) => settingsTabPath(basePath, tab) === trimmed) ?? null
}

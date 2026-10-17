/*
 * Barrel for the settings lane, for the routes that mount it from outside
 * this directory (`routes.tsx`'s top-level `/settings/*`, and the teacher and
 * student portals' `/teacher/settings/*` / `/student/settings/*`). Individual
 * files keep their own named exports too — `routes.tsx` already lazy-imports
 * `DeviceSettings`/`NotificationSettings` by name from their own modules, and
 * this barrel does not replace that, only adds one place to reach everything
 * at once for the two portals wiring in the frameless sections.
 */

export { PortalSettingsLayout, type PortalSettingsLayoutProps } from "./PortalSettingsLayout"
export { ProfileSettings, ProfileSettingsSection } from "./ProfileSettings"
export { DeviceSettings, DeviceSettingsSection } from "./DeviceSettings"
export { NotificationSettings, NotificationSettingsSection } from "./NotificationSettings"

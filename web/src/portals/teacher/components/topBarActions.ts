/*
 * The two top-bar sheets' destinations, as data. Kept out of the JSX so
 * `tests/unit/teacherTopBarSheets.test.ts` can assert every `to` here is a
 * route `teacherRoute` actually mounts: a renamed screen breaks a test rather
 * than a link a teacher clicks.
 */
import { marketingLinks } from "@/portals/marketing/content"

export type CreateActionIcon = "scheme" | "quiz" | "announcement" | "class"

export interface CreateAction {
  id: string
  icon: CreateActionIcon
  title: string
  description: string
  /** A pathname under `/teacher`, optionally with a query the screen reads. */
  to: string
}

export const CREATE_ACTIONS: readonly CreateAction[] = [
  {
    id: "scheme",
    icon: "scheme",
    title: "Add a mark scheme",
    description: "Parse an official CAIE scheme",
    to: "/teacher/schemes",
  },
  {
    id: "quiz",
    icon: "quiz",
    title: "AI quiz",
    description: "Draft from a weak topic",
    // `Quizzes` opens its "New quiz" form when it sees `?new=1`; creating the
    // draft there is what hands the teacher on to the builder.
    to: "/teacher/quizzes?new=1",
  },
  {
    id: "announcement",
    icon: "announcement",
    title: "Announcement",
    description: "Post to your students",
    // The announcements route is the composer itself.
    to: "/teacher/announcements",
  },
  {
    id: "class",
    icon: "class",
    title: "Class",
    description: "Share an invite code",
    to: "/teacher/first-class",
  },
]

/** Profile settings is the settings index; Settings opens the same place. */
export const PROFILE_EDIT_TO = "/teacher/settings"
export const SETTINGS_TO = "/teacher/settings"

/**
 * The app has no in-product help or feedback screen, so this is the same
 * contact address the marketing site publishes.
 */
export const HELP_HREF = marketingLinks.contact

/** `school_admin` reads as "School Admin": the caller's real role, title-cased. */
export function roleLabel(role: string): string {
  return role
    .split("_")
    .filter(Boolean)
    .map((w) => w[0].toUpperCase() + w.slice(1))
    .join(" ")
}

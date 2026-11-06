import { cn } from "@/lib/utils"

/*
 * Design A's stroke icons (the <symbol>s at the top of
 * web/dev-previews/student-home-a.html, 24-unit grid). Drawn as the design
 * draws `.as-ico`: 18px, no fill, 1.7 stroke, round caps and joins.
 */
const PATHS = {
  home: "M3 11l9-8 9 8v9a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z",
  review: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z M8 12l3 3 5-6",
  class: "M9 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6z M3 20c0-3.3 2.7-6 6-6s6 2.7 6 6 M17 11a2.5 2.5 0 1 0 0-5 M17 14c2.5 0 4 2 4 5",
  mega: "M3 10v4h4l7 4V6l-7 4z M17 9a4 4 0 0 1 0 6",
  bell: "M6 9a6 6 0 0 1 12 0c0 6 2 7 2 7H4s2-1 2-7 M10 20a2 2 0 0 0 4 0",
  up: "M12 16V4 M7 9l5-5 5 5 M4 20h16",
  out: "M9 4H5v16h4 M16 8l4 4-4 4 M20 12H9",
  menu: "M4 7h16M4 12h16M4 17h16",
  x: "M6 6l12 12M18 6L6 18",
  trophy: "M7 4h10v5a5 5 0 0 1-10 0z M7 6H4v1a3 3 0 0 0 3 3 M17 6h3v1a3 3 0 0 1-3 3 M12 14v3 M8 20h8",
  friends: "M8 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6z M2 20c0-3.3 2.7-6 6-6s6 2.7 6 6 M16 11a3 3 0 1 0 0-6 M16 14c3.3 0 6 2.7 6 6",
  practice: "M15 4l5 5L9 20H4v-5z M13 6l5 5",
  cards: "M4 8h12v12H4z M8 4h12v12",
  plan: "M4 6h16v14H4z M4 10h16 M8 3v4 M16 3v4 M8 14h3 M8 17h6",
  heart: "M12 20s-8-4.6-8-10.2A4.3 4.3 0 0 1 12 7.5a4.3 4.3 0 0 1 8 2.3C20 15.4 12 20 12 20z",
  user: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8z M4 21c0-4.4 3.6-7 8-7s8 2.6 8 7",
  trash: "M4 7h16 M9 7V4h6v3 M6 7l1 13h10l1-13 M10 11v6 M14 11v6",
  more: "M4 4h6v6H4z M14 4h6v6h-6z M4 14h6v6H4z M14 14h6v6h-6z",
  chev: "M9 6l6 6-6 6",
} as const

export type ShellIconName = keyof typeof PATHS

export function ShellIcon({ name, size = 18, className }: { name: ShellIconName; size?: number; className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth={1.7}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      className={cn("flex-none", className)}
    >
      <path d={PATHS[name]} />
    </svg>
  )
}

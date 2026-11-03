import type { VizColor } from "../data"

/*
 * Viz colour helpers shared across student screens. The mock colours bars,
 * grades and marks by a handful of semantic roles (accent / ok / warn / text
 * tints); these map each role to a token-backed Tailwind class so the portal's
 * terracotta scope stays consistent.
 */

/** text-* utility class for a viz colour role. */
export function vizText(color: VizColor): string {
  switch (color) {
    case "accent":
      return "text-primary"
    case "ok":
      return "text-success-text"
    case "warn":
      return "text-on-tertiary-container"
    case "t1":
      return "text-on-surface"
    case "t2":
      return "text-on-surface-variant"
    case "t3":
      return "text-on-surface-variant"
  }
}

/** bg-* utility class for a viz colour role (used for meter fills, dots). */
export function vizBg(color: VizColor): string {
  switch (color) {
    case "accent":
      return "bg-primary"
    case "ok":
      return "bg-success"
    case "warn":
      return "bg-tertiary"
    case "t1":
      return "bg-inverse-surface"
    case "t2":
      return "bg-on-surface-variant"
    case "t3":
      return "bg-on-surface-variant"
  }
}

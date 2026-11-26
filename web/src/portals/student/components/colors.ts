import type { VizColor } from "../data"

/*
 * Viz colour helpers shared across student screens. The mock colours
 * grades and marks by a handful of semantic roles (accent / ok / warn / text
 * tints); this maps each role to a token-backed Tailwind class so the portal's
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

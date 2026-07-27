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
      return "text-accent"
    case "ok":
      return "text-ok"
    case "warn":
      return "text-warn"
    case "t1":
      return "text-t1"
    case "t2":
      return "text-t2"
    case "t3":
      return "text-t3"
  }
}

/** bg-* utility class for a viz colour role (used for meter fills, dots). */
export function vizBg(color: VizColor): string {
  switch (color) {
    case "accent":
      return "bg-accent"
    case "ok":
      return "bg-ok"
    case "warn":
      return "bg-warn"
    case "t1":
      return "bg-t1"
    case "t2":
      return "bg-t2"
    case "t3":
      return "bg-t3"
  }
}

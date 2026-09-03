/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import { cn } from "@/lib/utils"

/*
 * Full-page-state doodles (PR 2 part A1).
 *
 * The grammar is `NotFound.tsx`'s original inline SVG, generalised from one
 * kind to eight: a hairline-only sketch (`--rule`, inherited via `currentColor`
 * off `text-rule`) with a small accent overlay in `--accent`, always at
 * `stroke-width="2"` against the hairlines' `1.5`, so the accent mark reads as
 * the one thing drawn *on top of* the printed page rather than one more line in
 * it — the same printed/handwritten contrast the brand mark itself is built on
 * (see `mark.tsx`). `aria-hidden` on every kind: per DESIGN.md §4.1/§8, this is
 * marginalia, and the heading beside it carries the whole meaning on its own.
 *
 * One `<svg>` wrapper, one hairline `<path>` per kind (each a single multi-
 * subpath string, exactly as the original screen wrote it), and a per-kind
 * accent overlay. The accent shapes are literal paths from the approved
 * canvas, not descriptions rebuilt from scratch, so this file is a transcription
 * rather than a redesign.
 */

export type DoodleKind =
  | "not-found"
  | "crash"
  | "offline"
  | "new-version"
  | "session-ended"
  | "no-access"
  | "service-trouble"
  | "too-many-requests"

/** One multi-subpath `d` string per kind — the printed hairlines. */
const HAIRLINES: Record<DoodleKind, string> = {
  "not-found": "M6 14h108M6 30h74M6 46h96M6 62h58",
  crash: "M6 14h108M6 30h58M6 46h96M6 62h58",
  offline: "M6 14h108M6 46h96M6 62h58",
  "new-version": "M6 14h76M6 30h74M6 46h96M6 62h58M114 34v28",
  "session-ended": "M6 14h108M6 30h74M6 46h96M6 62h58",
  "no-access": "M6 14h108M6 30h34M80 30h34M6 46h34M80 46h34M6 62h58",
  "service-trouble": "M6 14h108M6 30h74M6 46h96M6 62h58",
  "too-many-requests": "M6 14h108M6 30h74M6 46h96M6 62h58",
}

/** The handwritten accent overlay, per kind. Every element repeats
 * `stroke="currentColor"` explicitly (it would inherit anyway) to match the
 * convention `NotFound.tsx`'s original SVG set on its own accent paths. */
function DoodleAccent({ kind }: { kind: DoodleKind }) {
  switch (kind) {
    case "not-found":
      return (
        <>
          <path
            d="M78 8c-14 10-30 34-38 52"
            className="text-accent"
            stroke="currentColor"
            strokeWidth="2"
          />
          <path
            d="M40 8c12 14 26 38 34 52"
            className="text-accent"
            stroke="currentColor"
            strokeWidth="2"
          />
        </>
      )
    case "crash":
      return (
        <path
          d="M64 30c6-9 15-5 11 2c-4 6-13 2-7-4c6-7 17 0 11 7c-5 5-13 1-8-4c4-4 11-2 8 3"
          className="text-accent"
          stroke="currentColor"
          strokeWidth="2"
        />
      )
    case "offline":
      return (
        <>
          <path
            d="M6 30h40M74 30h40"
            className="text-accent"
            stroke="currentColor"
            strokeWidth="2"
          />
          <path
            d="M50 24v12M70 24v12"
            className="text-accent"
            stroke="currentColor"
            strokeWidth="2"
          />
        </>
      )
    case "new-version":
      // The one filled accent shape. `fill-accent-wash` resolves off the
      // `--color-accent-wash` token Tailwind v4 generates from `@theme
      // inline`, so the wash is a token, not a literal — the outline stays
      // `currentColor` (accent), inherited from `text-accent`.
      return (
        <path
          d="M86 6L114 34L86 34Z"
          className="text-accent fill-accent-wash"
          stroke="currentColor"
          strokeWidth="2"
        />
      )
    case "session-ended":
      return (
        <path
          d="M84 4v46l7-8 7 8V4"
          className="text-accent"
          stroke="currentColor"
          strokeWidth="2"
        />
      )
    case "no-access":
      return (
        <>
          <path
            d="M52 34v-8a8 8 0 0 1 16 0v8"
            className="text-accent"
            stroke="currentColor"
            strokeWidth="2"
          />
          <rect
            x="46"
            y="34"
            width="28"
            height="22"
            rx="3"
            className="text-accent"
            stroke="currentColor"
            strokeWidth="2"
          />
        </>
      )
    case "service-trouble":
      return (
        <>
          <path
            d="M24 58L72 20M31 65L79 27M24 58l7 7"
            className="text-accent"
            stroke="currentColor"
            strokeWidth="2"
          />
          <path
            d="M72 20l7 7 6-15z"
            className="text-accent"
            stroke="currentColor"
            strokeWidth="2"
          />
          <circle cx="90" cy="20" r="1.8" className="text-accent" fill="currentColor" stroke="none" />
        </>
      )
    case "too-many-requests":
      return (
        <>
          <path
            d="M50 18h20M50 54h20"
            className="text-accent"
            stroke="currentColor"
            strokeWidth="2"
          />
          <path
            d="M52 18c0 12 12 12 12 18s-12 6-12 18"
            className="text-accent"
            stroke="currentColor"
            strokeWidth="2"
          />
          <path
            d="M68 18c0 12-12 12-12 18s12 6 12 18"
            className="text-accent"
            stroke="currentColor"
            strokeWidth="2"
          />
        </>
      )
  }
}

export function Doodle({ kind, className }: { kind: DoodleKind; className?: string }) {
  return (
    <svg
      viewBox="0 0 120 72"
      aria-hidden="true"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={cn("h-16 w-28 text-rule", className)}
    >
      <path d={HAIRLINES[kind]} />
      <DoodleAccent kind={kind} />
    </svg>
  )
}

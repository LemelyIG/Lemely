import { useEffect, useState } from "react"
import type { HTMLAttributes } from "react"
import { User } from "@phosphor-icons/react"
import { cn } from "@/lib/utils"
import { initialsOf } from "@/lib/utils"

/*
 * DESIGN.md §6: "Avatars are squircles, `radius-lg` on a square, not
 * circles. Circles are reserved for live/status dots so a dot never reads as
 * a person." That is the one non-negotiable rule this file exists to
 * enforce — `rounded-lg` on the frame, never `rounded-full`, and the optional
 * status indicator is the only circle allowed to touch this component.
 *
 * Fallback order: image (if it loads) -> initials from `name` -> a generic
 * person glyph if there is no name to derive initials from (e.g. an
 * unclaimed seat in a roster). The image's own `onError` is what drives the
 * fallback rather than a `naturalWidth` check on load, since a broken/expired
 * signed URL fails asynchronously and only `onError` reliably catches that.
 */

export type AvatarSize = "sm" | "md" | "lg"
export type AvatarStatus = "online" | "offline" | "away"

const sizeClasses: Record<AvatarSize, string> = {
  sm: "h-8 w-8",
  md: "h-10 w-10",
  lg: "h-14 w-14",
}

const initialsTextClasses: Record<AvatarSize, string> = {
  sm: "text-body-sm",
  md: "text-body-lg",
  lg: "text-display-sm",
}

const iconSize: Record<AvatarSize, number> = {
  sm: 14,
  md: 18,
  lg: 26,
}

// Circle dots, deliberately the ONE shape on this component allowed to be
// round — this is the exact distinction DESIGN.md §6 is protecting.
const statusClasses: Record<AvatarStatus, string> = {
  online: "bg-ok",
  offline: "bg-ink-faint",
  away: "bg-warn",
}

const statusLabel: Record<AvatarStatus, string> = {
  online: "Online",
  offline: "Offline",
  away: "Away",
}

export interface AvatarProps extends Omit<HTMLAttributes<HTMLDivElement>, "children"> {
  /** Full display name. Source for the initials fallback and the accessible
   * name; pass this even when `src` is given. */
  name?: string
  /** Image URL. Falls back to initials (then a generic icon) if it fails to
   * load or is omitted. */
  src?: string
  size?: AvatarSize
  /** Renders a small circular status dot in the corner. Omitted entirely by
   * default — most avatars (a class roster row, a paper's marker) have no
   * presence concept, and a dot with no meaning would violate "colour never
   * carries meaning alone" the moment someone asks what it means. */
  status?: AvatarStatus
}

export function Avatar({ name, src, size = "md", status, className, ...props }: AvatarProps) {
  const [imageFailed, setImageFailed] = useState(false)
  // A new `src` deserves a fresh attempt: without this, a caller that swaps
  // in a different (working) URL after one image failed to load stays pinned
  // on the initials fallback forever, since `imageFailed` never had a reason
  // to go back to false.
  useEffect(() => {
    setImageFailed(false)
  }, [src])
  const showImage = Boolean(src) && !imageFailed
  const initials = name ? initialsOf(name).slice(0, 2).toUpperCase() : null

  return (
    <div
      className={cn("relative inline-flex shrink-0", sizeClasses[size], className)}
      {...props}
    >
      <div
        role="img"
        aria-label={name ?? "Unknown user"}
        className={cn(
          "flex h-full w-full items-center justify-center overflow-hidden rounded-lg border border-rule bg-paper-sunk",
        )}
      >
        {showImage ? (
          // eslint-disable-next-line jsx-a11y/alt-text -- accessible name is
          // carried by the wrapping `role="img"` aria-label above, so the
          // image itself is decorative (alt="") to avoid double-announcing.
          <img
            src={src}
            alt=""
            className="h-full w-full object-cover"
            onError={() => setImageFailed(true)}
          />
        ) : initials ? (
          <span
            className={cn(
              "select-none font-medium text-ink-muted",
              initialsTextClasses[size],
            )}
          >
            {initials}
          </span>
        ) : (
          <User size={iconSize[size]} weight="regular" className="text-ink-faint" />
        )}
      </div>
      {status ? (
        <span
          className={cn(
            "absolute -bottom-0.5 -end-0.5 h-2.5 w-2.5 rounded-full border-2 border-paper-raised",
            statusClasses[status],
          )}
          role="img"
          aria-label={statusLabel[status]}
        />
      ) : null}
    </div>
  )
}

/* Hallmark · pre-emit critique: P3 H4 E4 S4 R4 V3 */
import { Avatar } from "@/components/ui/avatar"
import { useProfile } from "@/lib/hooks/useMeApi"
import type { Profile } from "@/lib/meTypes"
import { cn } from "@/lib/utils"

/** The name the avatar's initial and the panel's label come from. */
export function profileName(profile: Pick<Profile, "displayName" | "email">): string {
  return profile.displayName ?? profile.email.split("@")[0]
}

/** `.as-avatar` (32px) and `.as-ident .as-avatar` (38px). The kit's squircle
 * `Avatar` stands in for design A's circle (user decision, logged as drift). */
export function ShellAvatar({
  name,
  src,
  size = "sm",
  className,
}: {
  name: string
  src?: string | null
  size?: "sm" | "md"
  className?: string
}) {
  const box = size === "sm" ? "size-8" : "size-[38px]"
  return <Avatar name={name} src={src ?? undefined} size="sm" className={cn("flex-none", box, className)} />
}

/**
 * What stands in the account panel's slot until its chunk and the profile
 * have loaded: the same box, so nothing shifts when the trigger replaces it.
 * Not interactive.
 */
export function ShellAvatarPlaceholder() {
  const { data } = useProfile()
  return (
    <span aria-hidden="true" className="grid size-9 flex-none place-items-center pointer-coarse:size-11">
      {data ? (
        <ShellAvatar name={profileName(data)} src={data.avatarUrl} />
      ) : (
        <span className="size-8 rounded-lg bg-surface-container" />
      )}
    </span>
  )
}

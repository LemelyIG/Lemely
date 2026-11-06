/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V3 */
import { Avatar } from "@/components/ui/avatar"
import { useProfile } from "@/lib/hooks/useMeApi"
import type { Profile } from "@/lib/meTypes"
import { cn } from "@/lib/utils"

/** The top-bar avatar's box: 36px, 44px on coarse pointers. */
export const PROFILE_AVATAR_BOX = "h-9 w-9 pointer-coarse:h-11 pointer-coarse:w-11"

/** The name the avatar's initials and the menu's label come from. */
export function profileName(profile: Pick<Profile, "displayName" | "email">): string {
  return profile.displayName ?? profile.email.split("@")[0]
}

/**
 * What stands in the profile menu's slot until the menu's own chunk (and the
 * profile) have loaded: the same avatar, same box, so nothing pops in or
 * shifts when the real trigger replaces it. Initials once the profile is
 * known, an empty squircle before that. Not interactive: the trigger that
 * replaces it is.
 */
export function ProfileAvatarPlaceholder() {
  const { data } = useProfile()
  return (
    <span aria-hidden="true" className={cn("flex flex-none rounded-lg", PROFILE_AVATAR_BOX)}>
      {data ? (
        <Avatar name={profileName(data)} src={data.avatarUrl ?? undefined} size="sm" className={PROFILE_AVATAR_BOX} />
      ) : (
        <span className={cn("rounded-lg bg-surface-container", PROFILE_AVATAR_BOX)} />
      )}
    </span>
  )
}

/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V3 */
/*
 * ── The critique those six digits came from ────────────────────────────────
 * Axes are Hallmark's six (Philosophy, Hierarchy, Execution, Specificity, Restraint, Variety),
 * scored on the first build and re-scored after looking at it at 380, 768 and 1440 (screenshots
 * in `.superpowers/sdd/screens/p03-acting/`).
 *
 * P · philosophy — 4. Identity is a choice made out loud: a labelled control that says who you
 *   are working as, placed beside the signed-in person's own name, not buried in settings.
 * H · hierarchy — 4. "Working as" is the eyebrow, the current choice is the one bold thing, the
 *   menu is the only other element. One withheld: in the sidebar footer it competes with the
 *   Upload button for the eye, deliberately, because it changes what Upload does.
 * E · execution — 4. Reuses the kit's RoleSwitcher (C-12) rather than a second menu; opens
 *   upward from the foot of the column, 44px rows on coarse pointers, Escape returns focus to the
 *   trigger, accessible name says "Working as <choice>" and contains the visible text. One
 *   withheld: the menu is a `menu` role without arrow-key movement, inherited from C-12.
 * S · specificity — 4. Options read "Mr Hassan (Marker)": the two facts a person picks by.
 * R · restraint — 4. Renders nothing for a teacher who assists nobody, which is nearly everyone.
 * V · variety — 3. A dropdown trigger in a footer is the expected shape. Kept: a switcher that
 *   is novel is a switcher people mistake, and this one gates who they act as.
 *
 * Revision pass, from the open menu at 380 and 1440: the menu was right-aligned to a full-width
 * trigger and covered the "Working as" label; it now lines up under the trigger at its width.
 */
import { UserSwitch } from "@phosphor-icons/react"
import { RoleSwitcher } from "@/components/ui/role-switcher"
import { SELF_OPTION_ID, switcherOptions } from "@/lib/actingModel"
import { cn } from "@/lib/utils"
import { useActingTeacher } from "./acting-state"

/**
 * "Working as: Me / <Lead> (Role)". Only for a teacher who assists at least one team; for everyone
 * else it renders nothing and takes no space.
 */
export function ActingSwitcher({ className }: { className?: string }) {
  const { memberships, lead, choose } = useActingTeacher()
  if (memberships.length === 0) return null

  const options = switcherOptions(memberships).map((o) => ({
    ...o,
    icon: <UserSwitch size={16} aria-hidden="true" className="flex-none text-on-surface-variant" />,
  }))
  const currentId = lead ? lead.teacherId : SELF_OPTION_ID
  const currentLabel = options.find((o) => o.id === currentId)?.label ?? "Me"

  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      <div className="px-0.5 text-eyebrow text-on-surface-variant">Working as</div>
      <RoleSwitcher
        roles={options}
        currentRoleId={currentId}
        onSwitch={(id) => choose(id === SELF_OPTION_ID ? null : id)}
        menuLabel="Work as"
        triggerLabel={`Working as ${currentLabel}`}
        placement="above"
        menuClassName="start-0 end-auto w-full"
      />
    </div>
  )
}

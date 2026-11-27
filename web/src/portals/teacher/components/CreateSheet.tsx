/* Hallmark · pre-emit critique: P4 H4 E4 S4 R5 V3 */
import type { RefObject } from "react"
import { Books, Megaphone, Plus, Sparkle, UsersThree, type Icon } from "@phosphor-icons/react"
import { ActionSheet } from "@/components/shell/TopBarSheets"
import { useActingTeacher } from "@/components/acting/acting-state"
import { CREATE_ACTIONS, type CreateActionIcon } from "./topBarActions"

const ACTION_ICON: Record<CreateActionIcon, Icon> = {
  scheme: Books,
  quiz: Sparkle,
  announcement: Megaphone,
  class: UsersThree,
}

/** The glyph and label every Create opener shares (bar button, native FAB, iOS large-title plus). */
export const CREATE_LABEL = "Create"
export const createGlyph = (size: number, weight?: "bold") => <Plus size={size} weight={weight} aria-hidden="true" />

/**
 * The teacher's Create sheet: four starting points (`CREATE_ACTIONS`). On desktop the bar button
 * opens it. On native phones that button is hidden and the controlled `open` state is driven by
 * the Android FAB or the iOS large-title plus (`TeacherLayout`).
 */
export function CreateSheet({
  triggerClassName,
  open,
  onOpenChange,
  restoreFocusTo,
}: {
  triggerClassName: string
  /** Omit all three for the self-contained bar button (dev previews). */
  open?: boolean
  onOpenChange?: (open: boolean) => void
  restoreFocusTo?: RefObject<HTMLElement | null>
}) {
  // While acting for a lead, only what the role may do is offered.
  const { can } = useActingTeacher()
  const actions = CREATE_ACTIONS.filter((action) => !action.permission || can(action.permission))
  return (
    <ActionSheet
      open={open}
      onOpenChange={onOpenChange}
      restoreFocusTo={restoreFocusTo}
      hideTriggerOnNative
      triggerClassName={triggerClassName}
      triggerIcon={createGlyph(16)}
      triggerLabel={CREATE_LABEL}
      eyebrow={CREATE_LABEL}
      title="Start something"
      actions={actions.map((action) => {
        const Glyph = ACTION_ICON[action.icon]
        return {
          id: action.id,
          title: action.title,
          description: action.description,
          to: action.to,
          icon: <Glyph size={20} aria-hidden="true" />,
        }
      })}
    />
  )
}

import { Books, Megaphone, Plus, Sparkle, UsersThree, type Icon } from "@phosphor-icons/react"
import { ActionSheet } from "@/components/shell/TopBarSheets"
import { CREATE_ACTIONS, type CreateActionIcon } from "./topBarActions"

const ACTION_ICON: Record<CreateActionIcon, Icon> = {
  scheme: Books,
  quiz: Sparkle,
  announcement: Megaphone,
  class: UsersThree,
}

/** The teacher top bar's Create button: four starting points (`CREATE_ACTIONS`). */
export function CreateSheet({ triggerClassName }: { triggerClassName: string }) {
  return (
    <ActionSheet
      triggerClassName={triggerClassName}
      triggerIcon={<Plus size={16} aria-hidden="true" />}
      triggerLabel="Create"
      eyebrow="Create"
      title="Start something"
      actions={CREATE_ACTIONS.map((action) => {
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

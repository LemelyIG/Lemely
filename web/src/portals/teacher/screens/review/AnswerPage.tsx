import { AnswerPanel, type AnswerPanelProps } from "./AnswerPanel"

/** Phone (< 721px): the answer as its own full-screen page, on the immersive
 * route `/teacher/review/:itemId`. The shell hides the tab bar on native. */
export function AnswerPage(props: AnswerPanelProps) {
  return (
    <div className="min-h-[100dvh] bg-surface px-4 pb-6 pt-3">
      <AnswerPanel {...props} />
    </div>
  )
}

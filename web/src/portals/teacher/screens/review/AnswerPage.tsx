/* Hallmark · pre-emit critique: P4 H4 E4 S4 R5 V3 */
import { AnswerPanel, type AnswerPanelProps } from "./AnswerPanel"
import { useFillViewport } from "./useFillViewport"

/** Phone (< 721px): the answer as its own full-screen page, on the immersive
 * route `/teacher/review/:itemId`. The shell hides the tab bar on native.
 * Bounded to the viewport so the answer scrolls inside it and the action bar stays on screen. */
export function AnswerPage(props: AnswerPanelProps) {
  const fill = useFillViewport<HTMLDivElement>(true, true)
  return (
    <div ref={fill.ref} style={fill.style} className="flex min-h-0 flex-col bg-surface px-4 pt-3">
      <AnswerPanel {...props} />
    </div>
  )
}

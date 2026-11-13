import { ArrowLeft, CaretLeft } from "@phosphor-icons/react"
import { useBackAction } from "@/components/ui/back-control"

/** Native frame Task 4: the detail bar's leading back control (preview `.as-back`). */
export function NativeBack({ fallback, label }: { fallback: string; label: string }) {
  const back = useBackAction(fallback)
  return (
    <button type="button" onClick={back} aria-label={`Back to ${label}`} className="lm-native-back lm-native-iconbtn lm-press lm-press-scale hidden items-center ios:gap-0.5 native:flex">
      <CaretLeft weight="bold" className="lm-native-back-ios" aria-hidden="true" />
      <ArrowLeft className="lm-native-back-md" aria-hidden="true" />
      <span className="lm-native-back-label" aria-hidden="true">{label}</span>
    </button>
  )
}

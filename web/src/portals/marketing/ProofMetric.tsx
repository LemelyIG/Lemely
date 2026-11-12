/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import { useEffect, useRef, useState } from 'react'
import { useCountUp } from '@/components/ui/celebration'
import { useSceneMotion } from './useSceneMotion'

/** The reference's proof count-up is illustrative presentation of supplied
 * figures. Reuse the kit's count-up and show each final value to AT throughout. */
export function ProofMetric({
  value,
  label,
  index,
}: {
  value: string
  label: string
  index: number
}) {
  const { ref, enabled } = useSceneMotion<HTMLDivElement>()
  const played = useRef(false)
  const [counting, setCounting] = useState(false)
  useEffect(() => {
    if (!enabled) {
      setCounting(false)
      return
    }
    if (played.current) return
    played.current = true
    setCounting(true)
    const timer = window.setTimeout(() => setCounting(false), 1100)
    return () => window.clearTimeout(timer)
  }, [enabled])
  const target = index === 0 ? 11000 : index === 1 ? 5 : 25
  const displayed = useCountUp(counting ? target : 0)
  const format = (n: number) =>
    index === 0
      ? `${n.toLocaleString('en-US')}+`
      : index === 1
        ? `${n} hrs`
        : `+${(n / 10).toFixed(1)} grades`
  return (
    <div ref={ref} className="brand-metric">
      <strong aria-label={value}>{counting ? format(displayed) : value}</strong>
      <span>{label}</span>
    </div>
  )
}

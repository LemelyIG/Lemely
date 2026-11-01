import { useEffect, useRef, useState } from 'react'
import { prefersReducedMotion } from '@/lib/celebration'

/** One lifecycle for visible artwork: stop work offscreen, in a hidden tab,
 * or whenever the visitor switches their system to reduced motion. */
export function useSceneMotion<T extends HTMLElement>() {
  const ref = useRef<T | null>(null)
  const [inView, setInView] = useState(false)
  const [reducedMotion, setReducedMotion] = useState(prefersReducedMotion)
  const [pageVisible, setPageVisible] = useState(() =>
    typeof document === 'undefined' ? true : !document.hidden,
  )

  useEffect(() => {
    const media = window.matchMedia('(prefers-reduced-motion: reduce)')
    const updateMotion = () => setReducedMotion(media.matches)
    const updateVisibility = () => setPageVisible(!document.hidden)
    updateMotion()
    updateVisibility()
    media.addEventListener('change', updateMotion)
    document.addEventListener('visibilitychange', updateVisibility)
    const element = ref.current
    const observer =
      typeof IntersectionObserver === 'undefined'
        ? null
        : new IntersectionObserver(
            (entries) => {
              setInView(entries.some((entry) => entry.isIntersecting))
            },
            { threshold: 0.12 },
          )
    if (element && observer) observer.observe(element)
    else setInView(true)
    return () => {
      observer?.disconnect()
      media.removeEventListener('change', updateMotion)
      document.removeEventListener('visibilitychange', updateVisibility)
    }
  }, [])

  return {
    ref,
    inView,
    reducedMotion,
    pageVisible,
    enabled: inView && !reducedMotion && pageVisible,
  }
}

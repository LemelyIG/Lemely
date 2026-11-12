import { useEffect } from 'react'
import type { RefObject } from 'react'

/** Decorate already-visible content only when it enters. An interrupted
 * observer, disabled animation, or JS error can never leave a section hidden. */
export function useLandingMotion(ref: RefObject<HTMLDivElement | null>) {
  useEffect(() => {
    const root = ref.current
    if (!root) return
    const media = window.matchMedia('(prefers-reduced-motion: reduce)')
    const played = new WeakSet<Element>()
    const animations = new Set<Animation>()
    const play = (element: HTMLElement) => {
      if (
        played.has(element) ||
        media.matches ||
        document.hidden ||
        typeof element.animate !== 'function'
      )
        return
      played.add(element)
      element.dataset.revealed = 'true'
      const isHeading = element.matches('h1,h2')
      const isDots = element.classList.contains('brand-dot-grid')
      const targets = isDots ? [...element.children] : [element]
      targets.forEach((target, i) => {
        const animation = target.animate(
          isDots
            ? [
                { transform: 'scale(.5)', opacity: 0.25 },
                { transform: 'scale(1)', opacity: 1 },
              ]
            : isHeading
              ? [
                  {
                    transform: 'translateY(24px)',
                    opacity: 0.3,
                    clipPath: 'inset(0 0 25% 0)',
                  },
                  { transform: 'none', opacity: 1, clipPath: 'inset(0 0 0 0)' },
                ]
              : [
                  { transform: 'translateY(14px)', opacity: 0.4 },
                  { transform: 'none', opacity: 1 },
                ],
          {
            duration: isDots ? 400 : isHeading ? 700 : 550,
            delay: isDots ? i * 22 : 0,
            easing: 'cubic-bezier(.16,1,.3,1)',
          },
        )
        animations.add(animation)
        animation.onfinish = () => animations.delete(animation)
      })
    }
    const targets = [
      ...root.querySelectorAll<HTMLElement>(
        'h1,h2,.brand-accuracy,.brand-dot-grid,.brand-teacher-grid article,.brand-school,.brand-closing .brand-actions',
      ),
    ]
    const observer =
      typeof IntersectionObserver === 'undefined'
        ? null
        : new IntersectionObserver(
            (entries) => {
              entries.forEach((entry) => {
                if (entry.isIntersecting) play(entry.target as HTMLElement)
              })
            },
            { threshold: 0.12 },
          )
    targets.forEach((element) => observer?.observe(element))
    const update = () => {
      if (media.matches || document.hidden) {
        animations.forEach((animation) => animation.cancel())
        animations.clear()
      }
    }
    media.addEventListener('change', update)
    document.addEventListener('visibilitychange', update)
    return () => {
      observer?.disconnect()
      animations.forEach((animation) => animation.cancel())
      media.removeEventListener('change', update)
      document.removeEventListener('visibilitychange', update)
    }
  }, [ref])
}

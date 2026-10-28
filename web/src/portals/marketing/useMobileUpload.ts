import { useEffect, useState } from 'react'

export function useMobileUpload(closingInView: boolean) {
  const [shown, setShown] = useState(true)
  useEffect(() => {
    let previous = window.scrollY
    let frame = 0
    const onScroll = () => {
      if (frame) return
      frame = requestAnimationFrame(() => {
        frame = 0
        const current = window.scrollY
        const delta = current - previous
        if (delta < -6 || current < 80) setShown(true)
        else if (delta > 6) setShown(false)
        previous = current
      })
    }
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => {
      window.removeEventListener('scroll', onScroll)
      cancelAnimationFrame(frame)
    }
  }, [])
  return shown && !closingInView
}

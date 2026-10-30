import { useEffect, useState } from 'react'

export function useMobileUpload() {
  const [shown, setShown] = useState(true)
  const [atClosing, setAtClosing] = useState(false)
  useEffect(() => {
    let previous = window.scrollY
    let frame = 0
    const onScroll = () => {
      if (frame) return
      frame = requestAnimationFrame(() => {
        frame = 0
        const current = window.scrollY
        const delta = current - previous
        if (delta < -6) setShown(true)
        else if (delta > 6) setShown(false)
        const closing = document.getElementById('start')
        setAtClosing(
          Boolean(
            closing &&
            closing.getBoundingClientRect().top < window.innerHeight * 0.95,
          ),
        )
        previous = current
      })
    }
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => {
      window.removeEventListener('scroll', onScroll)
      cancelAnimationFrame(frame)
    }
  }, [])
  return shown && !atClosing
}

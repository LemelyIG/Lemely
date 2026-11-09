import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * Cloudflare Turnstile, managed mode: the widget only shows itself when it needs the visitor to
 * do something. With no site key (dev, the preview, or a server that does not enforce it) the
 * hook does nothing and `required` is false, so the form never waits on it.
 *
 * The script is loaded once, on demand. Tokens are single use: call `reset()` after each submit.
 */
interface TurnstileApi {
  render: (el: HTMLElement, options: Record<string, unknown>) => string
  reset: (id?: string) => void
  remove: (id?: string) => void
}
declare global {
  interface Window {
    turnstile?: TurnstileApi
  }
}

const SCRIPT = 'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit'
let loading: Promise<void> | null = null
function loadTurnstile(): Promise<void> {
  if (window.turnstile) return Promise.resolve()
  loading ??= new Promise<void>((resolve, reject) => {
    const tag = document.createElement('script')
    tag.src = SCRIPT
    tag.async = true
    tag.onload = () => resolve()
    tag.onerror = () => {
      loading = null
      reject(new Error('turnstile script failed'))
    }
    document.head.appendChild(tag)
  })
  return loading
}

export type TurnstileState = 'off' | 'loading' | 'ready' | 'error'

export function useTurnstile(siteKey: string | null, box: React.RefObject<HTMLElement | null>) {
  const [token, setToken] = useState('')
  const [state, setState] = useState<TurnstileState>(siteKey ? 'loading' : 'off')
  const widget = useRef<string | null>(null)

  useEffect(() => {
    if (!siteKey || !box.current) {
      setState('off')
      return
    }
    let cancelled = false
    setState('loading')
    loadTurnstile()
      .then(() => {
        if (cancelled || !box.current || !window.turnstile) return
        widget.current = window.turnstile.render(box.current, {
          sitekey: siteKey,
          appearance: 'interaction-only',
          callback: (t: string) => {
            setToken(t)
            setState('ready')
          },
          'expired-callback': () => setToken(''),
          'error-callback': () => {
            setToken('')
            setState('error')
          },
        })
      })
      .catch(() => !cancelled && setState('error'))
    return () => {
      cancelled = true
      if (widget.current) window.turnstile?.remove(widget.current)
      widget.current = null
    }
  }, [siteKey, box])

  const reset = useCallback(() => {
    setToken('')
    if (widget.current) {
      setState('loading')
      window.turnstile?.reset(widget.current)
    } else if (siteKey) setState('error')
  }, [siteKey])

  return { required: Boolean(siteKey), token, state, reset }
}

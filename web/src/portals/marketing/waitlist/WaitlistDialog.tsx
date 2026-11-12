/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetTitle,
} from '@/components/ui/sheet'
import { WaitlistPanel, liveWaitlistClient, type WaitlistClient, type WaitlistSeed } from './WaitlistPanel'
import { captureWaitlistUtm } from './utm'
import './waitlist.css'

interface WaitlistContextValue {
  /** Opens the application surface; focus returns to the caller's element when it closes. */
  open: (from?: HTMLElement | null) => void
}
const WaitlistContext = createContext<WaitlistContextValue | null>(null)

export function useWaitlist(): WaitlistContextValue {
  const value = useContext(WaitlistContext)
  if (!value) throw new Error('useWaitlist must be used inside <WaitlistProvider>')
  return value
}

function useMobile() {
  const query = '(max-width: 639px)'
  const [mobile, setMobile] = useState(() => window.matchMedia(query).matches)
  useEffect(() => {
    const mq = window.matchMedia(query)
    const on = () => setMobile(mq.matches)
    mq.addEventListener('change', on)
    return () => mq.removeEventListener('change', on)
  }, [])
  return mobile
}

/**
 * One shared application surface: a centred dialog from `sm` up, a bottom sheet below it.
 * The Sheet portals to <body>, so it takes its theme from `<html data-theme>` like the page.
 */
/** Lets a harness or test swap the network client without touching the marketing frame. */
export const WaitlistClientContext = createContext<WaitlistClient>(liveWaitlistClient)

export function WaitlistProvider({
  children,
  client: clientProp,
  seed,
  defaultOpen = false,
}: {
  children: ReactNode
  client?: WaitlistClient
  seed?: WaitlistSeed
  defaultOpen?: boolean
}) {
  const contextClient = useContext(WaitlistClientContext)
  const client = clientProp ?? contextClient
  const [open, setOpen] = useState(defaultOpen)
  const opener = useRef<HTMLElement | null>(null)
  const escapeGuard = useRef<(() => boolean) | null>(null)
  const mobile = useMobile()
  useEffect(() => captureWaitlistUtm(), [])
  const show = useCallback((from?: HTMLElement | null) => {
    opener.current = from ?? (document.activeElement as HTMLElement | null)
    setOpen(true)
  }, [])
  const value = useMemo(() => ({ open: show }), [show])
  return (
    <WaitlistContext.Provider value={value}>
      {children}
      <Sheet open={open} onOpenChange={setOpen}>
        {open ? (
          <SheetContent
            side="bottom"
            showCloseButton={false}
            data-mobile={mobile}
            onEscapeKeyDown={(event) => {
              if (escapeGuard.current?.()) event.preventDefault()
            }}
            onCloseAutoFocus={(event) => {
              event.preventDefault()
              opener.current?.focus()
            }}
            className="lw-dialog gap-0 p-0"
          >
            {mobile ? <div className="lw-grab" aria-hidden /> : null}
            <SheetDescription className="sr-only">
              Join the Lemely waitlist in two short steps.
            </SheetDescription>
            <WaitlistPanel
              seed={seed}
              client={client}
              mobile={mobile}
              Title={SheetTitle}
              escapeGuard={escapeGuard}
              onClose={() => setOpen(false)}
            />
          </SheetContent>
        ) : null}
      </Sheet>
    </WaitlistContext.Provider>
  )
}

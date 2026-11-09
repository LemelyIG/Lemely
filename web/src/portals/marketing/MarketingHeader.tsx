/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import { useEffect, useRef, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { List, X } from '@phosphor-icons/react'
import { BrandLockup } from '@/components/ui/brand-lockup'
import { Button } from '@/components/ui/button'
import {
  Sheet,
  SheetTrigger,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
  SheetClose,
} from '@/components/ui/sheet'
import { marketingLinks } from './content'
import { useWaitlist } from './waitlist/WaitlistDialog'

export const sectionLinks = [
  { id: 'how', href: '/landing#how', label: 'How it works' },
  { id: 'features', href: '/landing#features', label: 'Features' },
  { id: 'teachers', href: '/landing#teachers', label: 'For teachers' },
] as const

/** The honest affordance for the demo link: it opens the mail app. */
export const DEMO_LABEL = 'Book a Demo (opens your email app)'

/**
 * Section links stay on whichever route the visitor is on (`/` or `/landing`)
 * so a click is a router navigation, never a full reload; from any other
 * marketing page they go to the canonical landing route.
 */
function useSectionTo() {
  const { pathname } = useLocation()
  const base = pathname === '/' || pathname === '/landing' ? pathname : '/landing'
  return (id: string) => ({ pathname: base, hash: `#${id}` })
}

export function MarketingHeader() {
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState('')
  const sectionTo = useSectionTo()
  const waitlist = useWaitlist()
  const menuTrigger = useRef<HTMLButtonElement>(null)
  const progress = useRef<HTMLDivElement>(null)
  useEffect(() => {
    let frame = 0
    const measure = () => {
      frame = 0
      const doc = document.documentElement
      const max = Math.max(1, doc.scrollHeight - window.innerHeight)
      if (progress.current)
        progress.current.style.transform = `scaleX(${Math.min(1, window.scrollY / max)})`
      let current = ''
      for (const id of ['teachers', 'how', 'features']) {
        const parts = document.querySelectorAll(`#${id}`)
        if (!parts.length) continue
        let top = Infinity
        let bottom = -Infinity
        parts.forEach((part) => {
          const bounds = part.getBoundingClientRect()
          top = Math.min(top, bounds.top)
          bottom = Math.max(bottom, bounds.bottom)
        })
        if (top < 140 && bottom > 140) current = id
      }
      setActive(current)
    }
    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(measure)
    }
    measure()
    window.addEventListener('scroll', schedule, { passive: true })
    window.addEventListener('resize', schedule)
    return () => {
      window.removeEventListener('scroll', schedule)
      window.removeEventListener('resize', schedule)
      cancelAnimationFrame(frame)
    }
  }, [])
  return (
    <header className="brand-header lm-app-header lm-nav-chrome">
      <div
        ref={progress}
        className="brand-reading-progress"
        aria-hidden="true"
      />
      <div className="brand-wrap brand-nav">
        <Link to="/landing" aria-label="Lemely home">
          <BrandLockup as="span" identity="clip" />
        </Link>
        <nav className="brand-desktop-nav" aria-label="Main">
          {sectionLinks.map((x) => (
            <Link
              key={x.id}
              to={sectionTo(x.id)}
              aria-current={x.id === active ? 'location' : undefined}
            >
              {x.label}
            </Link>
          ))}
        </nav>
        <div className="brand-nav-actions">
          <a
            className="brand-demo"
            href={marketingLinks.demo}
            aria-label={DEMO_LABEL}
          >
            Book a Demo
          </a>
          <Link className="brand-signin" to={marketingLinks.login}>
            Sign in
          </Link>
          <Link className="brand-signin" to={marketingLinks.signup}>
            Sign up
          </Link>
          <Button
            className="brand-join"
            variant="primary"
            size="sm"
            onClick={(e) => waitlist.open(e.currentTarget)}
          >
            Join the waitlist
          </Button>
          <Sheet open={open} onOpenChange={setOpen}>
            <SheetTrigger asChild>
              <Button
                ref={menuTrigger}
                className="brand-menu-trigger"
                variant="ghost"
                aria-label="Open menu"
              >
                <List aria-hidden="true" size={22} />
              </Button>
            </SheetTrigger>
            <SheetContent
              className="marketing-brand lw-light brand-menu"
              showCloseButton={false}
            >
              <SheetClose asChild>
                <button
                  type="button"
                  className="brand-menu-close"
                  aria-label="Close menu"
                >
                  <X aria-hidden="true" size={22} />
                </button>
              </SheetClose>
              <SheetHeader>
                <SheetTitle>Explore Lemely</SheetTitle>
                <SheetDescription>Every mark, explained.</SheetDescription>
              </SheetHeader>
              <nav aria-label="Mobile navigation">
                {sectionLinks.map((x) => (
                  <SheetClose key={x.id} asChild>
                    <Link
                      to={sectionTo(x.id)}
                      aria-current={x.id === active ? 'location' : undefined}
                    >
                      {x.label}
                    </Link>
                  </SheetClose>
                ))}
                <SheetClose asChild>
                  <a href={marketingLinks.demo} aria-label={DEMO_LABEL}>
                    Book a Demo
                  </a>
                </SheetClose>
                <SheetClose asChild>
                  <Link to={marketingLinks.login}>Sign in</Link>
                </SheetClose>
                <SheetClose asChild>
                  <Link to={marketingLinks.signup}>Sign up</Link>
                </SheetClose>
                <Button
                  variant="primary"
                  size="lg"
                  className="brand-menu-signup"
                  onClick={() => {
                    setOpen(false)
                    window.setTimeout(() => waitlist.open(menuTrigger.current), 0)
                  }}
                >
                  Join the waitlist
                </Button>
              </nav>
            </SheetContent>
          </Sheet>
        </div>
      </div>
    </header>
  )
}

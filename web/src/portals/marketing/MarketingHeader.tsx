/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { List } from '@phosphor-icons/react'
import { BrandLockup } from '@/components/ui/brand-lockup'
import { Button, buttonVariants } from '@/components/ui/button'
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

export const sectionLinks = [
  { href: '/landing#how', label: 'How it works' },
  { href: '/landing#features', label: 'Features' },
  { href: '/landing#teachers', label: 'For teachers' },
] as const

export function MarketingHeader() {
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState('')
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
        // A nav target can span several sections (Proof plus the teacher
        // features), so measure the union of every element that claims it.
        const parts = document.querySelectorAll(
          `#${id}, [data-nav-section="${id}"]`,
        )
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
            <a
              key={x.href}
              href={x.href}
              aria-current={
                x.href.endsWith(`#${active}`) ? 'location' : undefined
              }
            >
              {x.label}
            </a>
          ))}
        </nav>
        <div className="brand-nav-actions">
          <a className="brand-demo" href={marketingLinks.demo}>
            Book a Demo
          </a>
          <Link className="brand-signin" to={marketingLinks.login}>
            Sign in
          </Link>
          <Link
            className={buttonVariants({ variant: 'primary', size: 'sm' })}
            to={marketingLinks.signup}
          >
            Sign up
          </Link>
          <Sheet open={open} onOpenChange={setOpen}>
            <SheetTrigger asChild>
              <Button
                className="brand-menu-trigger"
                variant="ghost"
                aria-label="Open menu"
              >
                <List aria-hidden="true" size={22} />
              </Button>
            </SheetTrigger>
            <SheetContent className="marketing-brand brand-menu">
              <SheetHeader>
                <SheetTitle>Explore Lemely</SheetTitle>
                <SheetDescription>Every mark, explained.</SheetDescription>
              </SheetHeader>
              <nav aria-label="Mobile navigation">
                {sectionLinks.map((x) => (
                  <SheetClose key={x.href} asChild>
                    <a href={x.href}>{x.label}</a>
                  </SheetClose>
                ))}
                <SheetClose asChild>
                  <a href={marketingLinks.demo}>Book a Demo</a>
                </SheetClose>
                <SheetClose asChild>
                  <Link to={marketingLinks.login}>Sign in</Link>
                </SheetClose>
              </nav>
            </SheetContent>
          </Sheet>
        </div>
      </div>
    </header>
  )
}

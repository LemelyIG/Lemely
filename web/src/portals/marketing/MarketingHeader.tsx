/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import { useState } from 'react'
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
  return (
    <header className="brand-header lm-app-header lm-nav-chrome">
      <div className="brand-wrap brand-nav">
        <Link to="/landing" aria-label="Lemely home">
          <BrandLockup as="span" identity="clip" />
        </Link>
        <nav className="brand-desktop-nav" aria-label="Main">
          {sectionLinks.map((x) => (
            <a key={x.href} href={x.href}>
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

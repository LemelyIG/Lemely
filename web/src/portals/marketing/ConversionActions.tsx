/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import { buttonVariants } from '@/components/ui/button'
import { marketingLinks } from './content'
import { useWaitlist } from './waitlist/WaitlistDialog'

export function ConversionActions() {
  const waitlist = useWaitlist()
  return (
    <div className="brand-actions">
      <button
        type="button"
        onClick={(e) => waitlist.open(e.currentTarget)}
        className={buttonVariants({ variant: 'primary', size: 'lg' })}
      >
        Join the waitlist
      </button>
      <a
        href={marketingLinks.demo}
        aria-label="Book a Demo (opens your email app)"
        className={buttonVariants({ variant: 'secondary', size: 'lg' })}
      >
        Book a Demo
      </a>
    </div>
  )
}

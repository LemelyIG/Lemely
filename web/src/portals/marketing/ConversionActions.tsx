/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import { Link } from 'react-router-dom'
import { buttonVariants } from '@/components/ui/button'
import { marketingLinks } from './content'

export function ConversionActions() {
  return (
    <div className="brand-actions">
      <Link
        to={marketingLinks.signup}
        className={buttonVariants({ variant: 'primary', size: 'lg' })}
      >
        Upload your first paper free
      </Link>
      <a
        href={marketingLinks.demo}
        className={buttonVariants({ variant: 'secondary', size: 'lg' })}
      >
        Book a Demo
      </a>
    </div>
  )
}

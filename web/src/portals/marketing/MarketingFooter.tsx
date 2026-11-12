/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import { Link } from 'react-router-dom'
import { BrandLockup } from '@/components/ui/brand-lockup'
import { marketingLinks } from './content'
import { sectionLinks } from './MarketingHeader'

export function MarketingFooter() {
  return (
    <footer className="brand-footer">
      <div className="brand-wrap">
        <div className="brand-footer-grid">
          <div>
            <Link to="/landing" aria-label="Lemely home">
              <BrandLockup identity="clip" />
            </Link>
            <p>Every mark, explained.</p>
          </div>
          <nav aria-label="Product">
            <span className="brand-label">PRODUCT</span>
            {sectionLinks.map((x) => (
              <a key={x.href} href={x.href}>
                {x.label}
              </a>
            ))}
            <Link to="/join">Parent access</Link>
          </nav>
          <nav aria-label="Contact">
            <span className="brand-label">CONTACT</span>
            <a href={marketingLinks.contact}>contact@lemelyig.com</a>
            <a href={marketingLinks.demo}>Book a Demo</a>
            <a href={marketingLinks.contact}>Support</a>
          </nav>
          <nav aria-label="Data">
            <span className="brand-label">YOUR DATA</span>
            <Link to="/data">How your data is handled</Link>
          </nav>
        </div>
        <div className="brand-footer-bottom">
          <span>Lemely {new Date().getFullYear()}</span>
          <span>Made for Cambridge IGCSE, O Level &amp; A Level</span>
        </div>
      </div>
    </footer>
  )
}

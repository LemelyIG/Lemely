/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import { Hero } from './Hero'
import { Proof } from './Proof'
import { TeacherFeatures } from './TeacherFeatures'
import { MarkingWalkthrough } from './MarkingWalkthrough'
import { FeatureGrid } from './FeatureGrid'
import { BinnyFaq } from './BinnyFaq'
import { ConversionActions } from './ConversionActions'
import { useRef } from 'react'
import { createPortal } from 'react-dom'
import { useWaitlist } from './waitlist/WaitlistDialog'
import { useLandingMotion } from './useLandingMotion'
import { useSceneMotion } from './useSceneMotion'
import { useMobileUpload } from './useMobileUpload'
import { BinnyPeek } from './Binny'
import './page-motion.css'
import './desktop-fidelity.css'
import './tablet-fidelity.css'
import './a11y-fixes.css'

export function Landing() {
  const ref = useRef<HTMLDivElement>(null)
  const closing = useSceneMotion<HTMLElement>()
  const showUpload = useMobileUpload()
  const waitlist = useWaitlist()
  useLandingMotion(ref)
  return (
    <div ref={ref} className="brand-landing">
      <Hero />
      <MarkingWalkthrough />
      <FeatureGrid />
      <Proof />
      <TeacherFeatures />
      <BinnyFaq />
      <section
        ref={closing.ref}
        data-motion={closing.enabled ? 'active' : 'still'}
        id="start"
        className="brand-closing brand-section"
      >
        <div className="brand-wrap">
          <h2>
            Every mark,
            <br />
            <span>explained.</span>
          </h2>
          <p>
            Apply for early access in about 30 seconds. We'll email you when it
            opens. No card, no setup.
          </p>
          <ConversionActions />
        </div>
        <div className="brand-closing-cameo" aria-hidden="true">
          <span className="brand-closing-bubble">Go on. Two steps.</span>
          <div className="brand-closing-peek">
            <BinnyPeek />
          </div>
        </div>
      </section>
      {createPortal(
        <aside
          className="marketing-brand brand-mobile-upload-host"
          aria-label="Join the waitlist"
        >
          <button
            type="button"
            className="brand-mobile-upload"
            data-shown={showUpload}
            tabIndex={showUpload ? undefined : -1}
            onClick={(e) => waitlist.open(e.currentTarget)}
          >
            Join the waitlist
          </button>
        </aside>,
        document.body,
      )}
    </div>
  )
}

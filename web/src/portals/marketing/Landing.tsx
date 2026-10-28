/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import { Hero } from './Hero'
import { Proof } from './Proof'
import { TeacherFeatures } from './TeacherFeatures'
import { MarkingWalkthrough } from './MarkingWalkthrough'
import { FeatureGrid } from './FeatureGrid'
import { BinnyFaq } from './BinnyFaq'
import { ConversionActions } from './ConversionActions'
import { useRef } from 'react'
import { Link } from 'react-router-dom'
import { useLandingMotion } from './useLandingMotion'
import { useSceneMotion } from './useSceneMotion'
import { useMobileUpload } from './useMobileUpload'
import { Binny } from './Binny'
import './page-motion.css'

export function Landing() {
  const ref = useRef<HTMLDivElement>(null)
  const closing = useSceneMotion<HTMLElement>()
  const showUpload = useMobileUpload(closing.inView)
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
            Upload your first hand-written paper free. Marks, explanations and a
            next step in minutes. No card, no setup.
          </p>
          <ConversionActions />
          <span className="brand-hand">Go on. One paper.</span>
          <Binny className="brand-closing-binny" active={closing.enabled} />
        </div>
      </section>
      <Link to="/signup" className="brand-mobile-upload" hidden={!showUpload}>
        Upload free
      </Link>
    </div>
  )
}

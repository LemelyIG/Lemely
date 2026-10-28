/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import { Hero } from './Hero'
import { Proof } from './Proof'
import { TeacherFeatures } from './TeacherFeatures'
import { MarkingWalkthrough } from './MarkingWalkthrough'
import { FeatureGrid } from './FeatureGrid'
import { BinnyFaq } from './BinnyFaq'
import { ConversionActions } from './ConversionActions'

export function Landing() {
  return <>
    <Hero />
    <Proof />
    <TeacherFeatures />
    <MarkingWalkthrough />
    <FeatureGrid />
    <BinnyFaq />
    <section id="start" className="brand-closing brand-section"><div className="brand-wrap"><h2>Every mark,<br />explained.</h2><p>Upload your first hand-written paper free. Marks, explanations and a next step in minutes. No card, no setup.</p><ConversionActions /><span className="brand-hand">Go on. One paper.</span><img src="/marketing/brand/binny.svg" width="180" height="180" alt="" loading="lazy" /></div></section>
  </>
}

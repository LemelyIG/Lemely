/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import { ConversionActions } from './ConversionActions'
import { useHeroArtMotion } from './useHeroArtMotion'
import { HeroChartArt } from './ReferenceArt'

export function Hero() {
  const motion = useHeroArtMotion()
  return (
    <section id="top" className="brand-hero brand-section">
      <div className="brand-wrap brand-hero-grid">
        <div className="brand-hero-copy">
          <h1>
            Every mark, <br />
            <span>explained.</span>
          </h1>
          <p className="brand-hero-description">
            <span className="brand-hero-description-full">
              Hand-written past papers, marked against the official mark scheme
              in minutes. See every lost mark, and what to do next.
            </span>
            <span className="brand-hero-description-short">
              Snap a past paper. Get every mark explained.
            </span>
          </p>
          <ConversionActions />
          <p className="brand-fine">
            First paper free · No card · Cambridge IGCSE, O Level &amp; A Level
          </p>
        </div>
        <figure
          ref={motion.ref}
          data-art-scene="hero"
          data-motion={motion.enabled ? 'running' : 'static'}
          className="brand-hero-art"
          aria-label="Illustrative student progress from C to A star across five Physics papers"
        >
          <div className="brand-chart">
            <div className="brand-chart-head">
              <span className="brand-avatar">LA</span>
              <div>
                <strong>Layan A. · Physics 0625</strong>
                <span className="brand-label">
                  SAMPLE STUDENT · 5 PAST PAPERS
                </span>
              </div>
              <div className="brand-predicted">
                <span className="brand-label">PREDICTED</span>
                <b>A*</b>
              </div>
            </div>
            <div>
              <HeroChartArt />
            </div>
            <div className="brand-chart-foot">
              <span className="brand-label">C to A* · 5 PAPERS</span>
              <span>Every paper is progress.</span>
            </div>
          </div>
        </figure>
      </div>
    </section>
  )
}

/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import { features } from './content'
import { FeatureMotion } from './FeatureMotion'
import { FeatureArt } from './ReferenceArt'
import { ResponsiveDeck } from './ResponsiveDeck'

export function FeatureGrid() {
  return (
    <section id="features" className="brand-features brand-section">
      <div className="brand-wrap">
        <span className="brand-label">FEATURES</span>
        <h2>
          Everything that happens
          <br /> after the mark.
        </h2>
        <ResponsiveDeck label="Lemely features" className="brand-feature-grid">
          {features.map((x, i) => (
            <article
              key={x.key}
              className={
                i === 0
                  ? 'brand-feature brand-feature-core'
                  : x.key === 'content'
                    ? 'brand-feature brand-feature-content'
                    : 'brand-feature'
              }
            >
              {i === 0 && <span className="brand-label">THE CORE</span>}
              <h3>{x.title}</h3>
              <p>{x.description}</p>
              <div className="brand-feature-art" aria-hidden="true">
                <FeatureMotion name={x.key}>
                  <FeatureArt name={x.key} />
                </FeatureMotion>
              </div>
            </article>
          ))}
        </ResponsiveDeck>
      </div>
    </section>
  )
}
